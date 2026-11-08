"""hubris: research the live web before answering from memory.

HUBRIS -- Heuristic Unverified-Belief Research Injection Signal.

Why this exists: an agent with a large context and a confident voice will answer a
"what is the best X right now" question out of its training data or a local archive, and
be wrong in a way that reads exactly like being right. The knowledge was true when it was
learned; nothing about it carries a date. Past the training cutoff it is at best undated and
at worst OBE -- overtaken by events. Instructions to search first are advisory, and an
advisory loses to whatever skill or habit is closest at hand. This is the mechanical version:

  pre_llm_call        classify the turn; if it turns on current external facts, inject a
                      directive that says search first and label everything else.
  post_tool_call      record whether a real web tool was used during the turn.
  transform_llm_output if the turn needed research and none ran, stamp the reply with a
                      visible footer naming that fact.

The footer is the part that cannot be ignored, because the reader sees it in the same
message as the answer. Nothing here blocks a reply or calls a model: a broken classifier
degrades to silence, never to a stuck turn.

Settings come from the plugin's own ``config_schema`` entry, which the Desktop app renders
as a form under Settings, Plugins. Nothing is read from a file in this directory: an update
replaces the plugin tree, and a config written there would be the one thing users lose.

Formerly named source-first.
"""

from __future__ import annotations

import json
import logging
import re

from .classifier import classify, counts_as_research
from .taxonomy import TOPICS, enabled_subjects

log = logging.getLogger("plugins.hubris")

# session_id -> {"research": bool, "searched": bool, "reason": str, "stamped": bool,
#                "platform": str, "quiet": bool}
_TURNS: dict[str, dict] = {}

# Set by register(); the context is the documented route to this plugin's own settings.
_CTX = None

_DIRECTIVE = (
    "[hubris] This turn turns on current external facts. Search the live web before "
    "answering: web_search first, then web_extract on the pages that matter. Local archives, "
    "stored notes and your own training are FALLBACKS: they may be past their date or OBE "
    "(overtaken by events), so anything taken from them must be labelled as not verified "
    "against a live source. Cite the URLs you actually read. If the network is blocked, say "
    "plainly that you could not reach a source rather than answering as though you had."
)

_FOOTER = (
    "\n\n---\n"
    "**hubris:** this turn turned on {subject} and no live web search ran. "
    "Treat the answer above as potentially OBE (overtaken by events): undated background "
    "knowledge, not verified current fact."
)

_DEFAULTS = {
    "enabled": True,
    "quiet_platforms": "",
    "extra_trigger_phrases": "",
    "extra_skip_phrases": "",
}


def _as_phrases(value) -> list[str]:
    """A phrase list from whichever shape the settings ended up holding.

    The form stores a plain string because a comma-separated line is what a person can
    actually type, but someone editing config.yaml by hand may write a real list, and an
    older copy of this plugin wrote JSON arrays. All three are accepted so no saved
    setting is ever silently dropped.
    """
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        return [p.strip() for p in re.split(r"[,\n]", text) if p.strip()]
    return []


def _flag(value, default: bool = True) -> bool:
    """A switch from whatever the config holds: real bool, or a string a hand edit left."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return default
        return text not in ("false", "0", "no", "off", "disabled")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _settings() -> dict:
    """This plugin's settings, fail-open.

    ``ctx.get_config`` reads ``plugins.entries.hubris.settings.<key>``, which is what the
    Desktop form and ``hermes config set`` write. Without a context (unit test, CLI probe)
    every switch stands at its default -- on -- so the hooks never fail on configuration and
    a probe sees the full taxonomy rather than an empty one.
    """
    every_subject = {s.full_key for t in TOPICS for s in t.subjects}
    getter = getattr(_CTX, "get_config", None)
    if not callable(getter):
        return {
            "enabled": True,
            "quiet_platforms": [],
            "extra_trigger_phrases": [],
            "extra_skip_phrases": [],
            "live_subjects": every_subject,
        }

    def read(key, default):
        try:
            return getter(key, default)
        except Exception:
            return default

    out = {
        "enabled": _flag(read("enabled", True)),
        "quiet_platforms": _as_phrases(read("quiet_platforms", "")),
        "extra_trigger_phrases": _as_phrases(read("extra_trigger_phrases", "")),
        "extra_skip_phrases": _as_phrases(read("extra_skip_phrases", "")),
    }
    topic_flags = {t.key: _flag(read(t.setting_key, True)) for t in TOPICS}
    subject_flags = {
        s.full_key: _flag(read(s.setting_key, True)) for t in TOPICS for s in t.subjects
    }
    out["live_subjects"] = enabled_subjects(topic_flags, subject_flags)
    return out


def _subject_phrase(subjects) -> str:
    """`money.prices, games.guides` for the footer, or the generic phrase when only shape matched."""
    if not subjects:
        return "current external facts"
    return ", ".join(subjects)


def _text_of(user_message) -> str:
    """A multimodal turn arrives as a list of content parts."""
    if isinstance(user_message, str):
        return user_message
    if isinstance(user_message, list):
        pieces = []
        for part in user_message:
            if isinstance(part, dict) and part.get("type") == "text":
                pieces.append(str(part.get("text", "")))
        return " ".join(pieces)
    return str(user_message or "")


# --------------------------------------------------------------------------- hooks


def on_pre_llm_call(session_id: str = "", user_message=None, platform: str = "", **_kw):
    """Classify the turn, reset its search ledger, and inject the directive when needed."""
    settings = _settings()
    if not settings["enabled"]:
        _TURNS.pop(session_id, None)
        return None

    text = _text_of(user_message)
    verdict = classify(
        text,
        extra_trigger_phrases=settings["extra_trigger_phrases"],
        extra_skip_phrases=settings["extra_skip_phrases"],
        live_subjects=settings["live_subjects"],
    )
    quiet = platform in settings["quiet_platforms"]
    _TURNS[session_id] = {
        "research": verdict.research,
        "searched": False,
        "reason": verdict.reason,
        "subjects": verdict.subjects,
        "stamped": False,
        "platform": platform,
        "quiet": quiet,
    }

    if not verdict.research or quiet:
        return None

    log.info("hubris: research directive injected (%s, %s)", session_id[:12], verdict.reason)
    return {"context": _DIRECTIVE}


def on_post_tool_call(tool_name: str = "", session_id: str = "", **_kw):
    """Mark this session's turn as searched once a live-web tool fires."""
    turn = _TURNS.get(session_id)
    if not turn or not turn.get("research") or turn.get("searched"):
        return None
    if not counts_as_research(tool_name):
        return None
    turn["searched"] = True
    turn["used"] = tool_name
    return None


def on_transform_llm_output(response_text: str = "", session_id: str = "", **_kw):
    """Stamp a reply that needed research and did not get any."""
    turn = _TURNS.get(session_id)
    if not turn or not turn.get("research") or turn.get("searched") or turn.get("stamped"):
        return None
    if turn.get("quiet") or not _settings()["enabled"]:
        return None
    if not response_text:
        return None

    turn["stamped"] = True
    log.warning("hubris: research turn %s answered without a web search (%s)",
                session_id[:12], turn.get("reason"))
    return response_text + _FOOTER.format(subject=_subject_phrase(turn.get("subjects")))


def register(ctx) -> None:  # noqa: ANN001 - PluginContext
    global _CTX
    _CTX = ctx
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
    ctx.register_hook("transform_llm_output", on_transform_llm_output)
    log.info("hubris: registered (search directive + missing-search footer)")
