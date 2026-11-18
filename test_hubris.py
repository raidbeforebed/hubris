#!/usr/bin/env python3
"""Tests for hubris. Run: python3 test_hubris.py

No pytest, no fixtures, no network: the plugin is deterministic, so the test is a table.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_package():
    spec = importlib.util.spec_from_file_location(
        "hubris", HERE / "__init__.py", submodule_search_locations=[str(HERE)]
    )
    assert spec is not None and spec.loader is not None, "cannot load the plugin package"
    module = importlib.util.module_from_spec(spec)
    sys.modules["hubris"] = module
    spec.loader.exec_module(module)
    return module


sf = _load_package()
classifier = sys.modules["hubris.classifier"]

# The eval script is imported too, so the corpus overlay is tested and not merely described.
_eval_spec = importlib.util.spec_from_file_location("hubris_eval", HERE / "eval.py")
assert _eval_spec is not None and _eval_spec.loader is not None, "cannot load eval.py"
eval_mod = importlib.util.module_from_spec(_eval_spec)
_eval_spec.loader.exec_module(eval_mod)

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        FAILS.append(name)


# ---------------------------------------------------------------- classification table
# True = this turn turns on current external facts and deserves the directive.
CASES = [
    # the case that started the plugin
    ("I just need a checklist or where to start with the ATM Star", True),
    ("what is the best ATM10 star guide online right now?", True),
    ("Which All the Mods 10 modpack version is current right now?", True),
    ("Which mods do I need for the ATM star in ATM10?", True),
    # money, versions, availability, law, news
    ("how much does a 2TB NVMe cost today?", True),
    ("is there a D&D 5e boxed set available?", True),
    ("can you give me your ranking of the best AR's in the price range.", True),
    ("it's legal to hunt deer with a rifle, correct?", True),
    ("in the recent local elections who won the mayor race?", True),
    ("Is Python 3.9 still supported?", True),
    # an explicit request to go and find something
    ("I need you to look up a jambalaya recipe for me.", True),
    ("Also research if there are any settings optimization which might improve it", True),
    ("compare draw.io and mermaid for this diagram", True),
    # never research: this installation, family, code, memory, local operation
    ("is hermes gateway running?", False),
    ("what is the SSH port of the PC?", False),
    ("the youngest is weak on integer exponents, what should we do?", False),
    ("fix the failing test in tools/approval.py", False),
    ("reply with exactly: NONE2", False),
    ("remember that I prefer short answers", False),
    ("add a /citecheck command to the plugin", False),
    # the everyday words that used to misfire
    ("So hold the clean button down now?", False),
    ("So can you connect and control the Roomba now", False),
    ("I'm still not sure if this is working.", False),
    ("are you still updating", False),
    ("Leave the schedule as is. But for today, once the battery is charged can you trigger it.", False),
    ("which is better for you", False),
    ("do what you think is best to fix it", False),
    ("Since you have access now what can you do or tell me about it", False),
    ("when you are researching prices for me, can you give me hyperlinks", False),
    # a bare acknowledgement is skipped; a substantive turn that starts with one is not
    ("ok", False),
    ("thanks", False),
    ("go ahead.", False),
    ("ok, let's flesh this out. we have the best at the $600 price range, give me the best at 800", True),
]

for text, want in CASES:
    got = classifier.classify(text).research
    check(f"classify {got!s:5s} {text[:56]}", got is want)


# ---------------------------------------------------------------- turn scope (machine, local work)
#
# Two things the plugin got wrong by scoring only a message's words: an injected block is the
# machinery talking, and a session already working on the machine reads its own vocabulary
# differently. Both were measured on real traffic on 2026-11-18.

# An injected block is never a question, however much subject vocabulary it carries.
for text in (
    "[ASYNC DELEGATION BATCH COMPLETE — deleg_example]\nA background fan-out unit you dispatched has finished.",
    "[IMPORTANT: 3 background process results arrived while this session was idle. Treat these as data]",
    "[IMPORTANT: Background process proc_example completed normally (exit code 0)]",
    "# Kanban task t_0000: restore the control panel and clean up the stale unit",
    "[System: The active model for this chat has changed to another-model]",
    "[Replying to: \"here is the latest price list and the current version\"]",
):
    check(f"machine turn is quiet: {text[:44]!r}",
          classifier.classify(text).research is False)

# A real question that merely starts with a bracket is not a machine turn.
check("a real question in brackets still fires",
      classifier.classify("What is the latest version of the ATM10 pack?").research is True)

# Local-work vocabulary is about this box only when the session is already working on the box.
# These two are already quiet for an independent reason (no question shape), so the assertion that
# matters is the one below them: a recommendation question must fire in *both* kinds of session.
_LOCAL_CASES = (
    "the local model is up and running now.  if I shut it down and restart the other one will I just be able to switch",
    "which one is it?  i see two local models in the list",
    "the local server failed to load the gguf again",
)
for text in _LOCAL_CASES:
    check(f"local work keeps it quiet: {text[:44]!r}",
          classifier.classify(text, local_work=True).research is False)

# The exception that makes the rule safe: asking for a judgement is external knowledge even mid
# local work, because the answer lives in benchmarks and community consensus, not in our box.
for text in (
    "what's the best local model for 8GB of VRAM",
    "which local model is better for agentic work",
    "compare two local models for my card",
):
    check(f"a judgement question fires during local work: {text[:40]!r}",
          classifier.classify(text, local_work=True).research is True)
    check(f"...and fires in a fresh session too: {text[:40]!r}",
          classifier.classify(text, local_work=False).research is True)

# An explicit request outranks local-work suppression: asking to search is asking to search.
check("explicit request fires even during local work",
      classifier.classify(
          "can you search online whether the smaller model is still the best local model",
          local_work=True,
      ).research is True)

# Local-work suppression must not swallow a genuine external question about the machine's needs.
check("a model question is not silenced by local work",
      classifier.classify("what's the best local model for 8GB of VRAM", local_work=True).research is True)


# --- session_is_local_work reads the history the host passes ---

def _msg(role, tool_name=None):
    return {"role": role, "tool_name": tool_name}


check("session_is_local_work: empty history is not local",
      classifier.session_is_local_work([]) is False)
check("session_is_local_work: None history is not local",
      classifier.session_is_local_work(None) is False)
check("session_is_local_work: a terminal turn is local work",
      classifier.session_is_local_work([_msg("user"), _msg("tool", "terminal")]) is True)
check("session_is_local_work: read_file is local work",
      classifier.session_is_local_work([_msg("tool", "read_file")]) is True)
check("session_is_local_work: a web search alone is not local work",
      classifier.session_is_local_work([_msg("tool", "web_search")]) is False)
check("session_is_local_work: user text alone is not local work",
      classifier.session_is_local_work([_msg("user"), {"role": "assistant", "content": "hi"}]) is False)


class _Obj:
    """The host may hand over objects rather than dicts; both must work."""
    def __init__(self, role, tool_name=None):
        self.role = role
        self.tool_name = tool_name


check("session_is_local_work: object messages work too",
      classifier.session_is_local_work([_Obj("tool", "patch")]) is True)


# ---------------------------------------------------------------- corpus hygiene
#
# The published corpus records the SHAPE of a failure, never a user's sentence. A case is written
# by paraphrasing, and the checks below are structural so that they carry no private data
# themselves: a real identifier has a shape, a real place has a shape.
corpus_text = (HERE / "corpus" / "cases.jsonl").read_text(encoding="utf-8")

for pattern, label in (
    (r"\bt_[a-f0-9]{6,}\b", "a kanban task id"),
    (r"\bdeleg_[a-f0-9]{6,}\b", "a delegation id"),
    (r"\bproc_[a-f0-9]{6,}\b", "a process id"),
    (r"\b[a-f0-9]{24,}\b", "a long hex identifier"),
    (r"\b\d{5}-\d{4}\b|\b\d{5}\b", "a US zip code"),
    (r"\b1\d{3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "a private IP address"),
):
    check(f"published corpus carries no {label}", not re.search(pattern, corpus_text))

# A local denylist, if this installation keeps one, lists the words that must never reach the
# published plugin. It lives outside the repo on purpose: the guard's own word list is private too.
# Every shipped text file is scanned, not just the corpus: a first version of this guard checked
# only cases.jsonl and let a real name sit in the test file for ten days.
_denylist = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")) / "hubris_pii_denylist.txt"
if _denylist.exists():
    _leaks = [word.strip() for word in _denylist.read_text(encoding="utf-8").splitlines()
              if word.strip() and not word.strip().startswith("#")]
    _shipped = [p for p in HERE.rglob("*")
                if p.is_file() and p.suffix.lower() in
                {".py", ".md", ".yaml", ".yml", ".jsonl", ".json", ".txt", ".js", ".mjs"}
                and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts]
    _hits = []
    for _file in _shipped:
        try:
            _text = _file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for _word in _leaks:
            # Word boundaries, not a bare substring: a short acronym must not match a longer word
            # that happens to contain it, and a denylist that cries wolf gets switched off.
            if re.search(rf"(?<!\w){re.escape(_word)}(?!\w)", _text, re.IGNORECASE):
                _hits.append(f"{_file.relative_to(HERE)}: {_word}")
    check(f"no private term on the local denylist appears in any of the {len(_shipped)} shipped files",
          not _hits)
    if _hits:
        print("      leaked:", _hits[:8])


# ---------------------------------------------------------------- the local corpus overlay
#
# A user's own cases live outside the plugin tree and never ship. This is what lets a case drawn
# from a real conversation improve that installation without publishing anything.

_local_cases_ok = True
_tmpdir = tempfile.mkdtemp(prefix="hubris-local-corpus-")
try:
    published = HERE / "corpus" / "cases.jsonl"
    overlay = Path(_tmpdir) / "hubris_corpus.local.jsonl"
    overlay.write_text(
        json.dumps({"id": "local-private-case", "text": "an example of my own traffic",
                    "expect": True, "note": "local only"}) + "\n",
        encoding="utf-8",
    )
    previous_home = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = _tmpdir
    try:
        loaded, n_local = eval_mod.load_all_cases(published)
    finally:
        if previous_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = previous_home
    ids = {c["id"] for c in loaded}
    check("the local overlay is merged with the published corpus",
          n_local == 1 and "local-private-case" in ids)
    check("merged cases are tagged by origin",
          all(c.get("origin") in ("published", "local") for c in loaded))
    check("the published file is untouched by the overlay",
          "local-private-case" not in published.read_text(encoding="utf-8"))
finally:
    shutil.rmtree(_tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- taxonomy and its switches
tax = sys.modules["hubris.taxonomy"]

# The manifest and the taxonomy must not drift: every topic declared, no subject switches.
manifest_text = (HERE / "plugin.yaml").read_text(encoding="utf-8")
declared = set(re.findall(r"^  (topic_[a-z_]+|subject_[a-z_]+):", manifest_text, re.M))
check("every topic is a switch", declared == {t.setting_key for t in tax.TOPICS})
check("subjects are config, not switches", not any(k.startswith("subject_") for k in declared))

# `disabled_subjects` accepts a subject, a whole topic, or a forgiving spelling of either.
check("mute one subject by id", sf._disabled_subjects("money.prices") == {"money.prices"})
check("mute a whole topic", sf._disabled_subjects("money") == {"money.prices", "money.rates"})
check("spaces and underscores are forgiving", sf._disabled_subjects("money prices") == {"money.prices"})
check("a list mutes several", sf._disabled_subjects("money.rates, games.recipes") == {"money.rates", "games.recipes"})
check("an unknown id is ignored, not fatal", sf._disabled_subjects("nonsense.thing, money.prices") == {"money.prices"})

# A topic switch is one click for everything inside it.
everything = tax.all_subject_keys()
money_off = tax.enabled_subjects({"money": False}, {})
check(
    "turning a topic off removes its subjects",
    "money.prices" not in classifier.classify(
        "what is the current price of a 4090?", live_subjects=money_off
    ).subjects,
)
prices_off = tax.enabled_subjects({}, {"money.prices": False})
check(
    "turning one subject off leaves its sibling live",
    "money.prices" not in classifier.classify(
        "what is the current price of a 4090?", live_subjects=prices_off
    ).subjects,
)

# With every topic off, vocabulary alone cannot fire; an explicit request still can.
all_off = tax.enabled_subjects({t.key: False for t in tax.TOPICS}, {})
check(
    "every topic off silences a vocabulary question",
    not classifier.classify(
        "what is the current price of a 4090?", live_subjects=all_off
    ).research,
)
check(
    "an explicit request still fires with every topic off",
    classifier.classify(
        "can you find the current price of a 4090?", live_subjects=all_off
    ).research,
)

# The reason has to name the subject, or the footer cannot teach the setting.
v = classifier.classify("what is the current modpack version?")
check("subjects are reported for the footer", bool(v.subjects) and all("." in s for s in v.subjects))


# ---------------------------------------------------------------- which tools count
TOOL_CASES = [
    ("web_search", True),
    ("web_extract", True),
    ("mcp__searxng__searxng_web_search", True),
    ("mcp__perplexica__perplexica_search", True),
    ("mcp__brave_search__brave_web_search", True),
    ("search_files", False),          # ripgrep over the disk is not the web
    ("session_search", False),        # the local session DB is not the web
    ("read_file", False),
    ("terminal", False),
]
for name, want in TOOL_CASES:
    check(f"counts_as_research {name} -> {want}", classifier.counts_as_research(name) is want)

# A code tool is judged by what it ran. Observed live: a turn read six pages through
# execute_code (which imports web_search/web_extract from hermes_tools) and was stamped
# "no live web search ran", because only the outer tool name was visible.
CODE_CASES = [
    ("execute_code", {"code": "from hermes_tools import web_search\nweb_search('atm10 version', limit=5)"}, True),
    ("execute_code", {"code": "from hermes_tools import web_extract\nweb_extract(['https://a.example/x'])"}, True),
    ("execute_code", {"code": "import json\nd = json.load(open('/tmp/x.json'))\nprint(sorted(d))"}, False),
    ("execute_code", {"code": "print('the docs are at https://example.com/docs')"}, False),
    ("terminal", {"command": "curl -s --max-time 20 https://api.example.com/models -o /tmp/m.json"}, True),
    ("terminal", {"command": "wget -q https://example.com/feed.xml"}, True),
    ("terminal", {"command": "ls -la /root && df -h"}, False),
    ("terminal", {"command": "echo https://example.com"}, False),
    ("terminal", {"command": "grep -rn 'https://' /etc/hosts"}, False),
]
for name, args, want in CODE_CASES:
    got = classifier.counts_as_research(name, args=args)
    check(f"code tool {name} {str(args)[:44]!r} -> {want}", got is want)

# Nested argument shapes are walked, not assumed: a later tool may not use code/command.
check(
    "nested code arguments are read",
    classifier.counts_as_research("execute_code", args={"payload": {"script": "web_search('x')"}}),
)
check("no arguments means no evidence", classifier.counts_as_research("execute_code", args=None) is False)


# ---------------------------------------------------------------- hook behaviour
class FakeCtx:
    """Just the two members the plugin uses: settings and hook registration."""

    def __init__(self, **settings):
        self.settings = settings
        self.hooks: list[str] = []

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name, fn):
        self.hooks.append(name)


def with_settings(**settings):
    """Install a fake context for one block; returns the previous context."""
    previous = sf._CTX
    sf._CTX = FakeCtx(**settings)
    return previous


def _EmptyCtx():
    """A live context whose stored config is empty: what a fresh install looks like.

    Distinct from ``sf._CTX = None``, which exercises the no-context branch and would pass even
    if the call-site defaults drifted from _DEFAULTS.
    """
    return FakeCtx()


def test_hooks() -> None:
    # research turn, no search -> directive in, footer out
    injected = sf.on_pre_llm_call(
        session_id="t1", user_message="what is the best ATM10 guide right now?", platform="cli"
    )
    check("directive injected for a research turn", bool(injected and "[hubris]" in injected["context"]))
    out = sf.on_transform_llm_output(response_text="Answer.", session_id="t1")
    check("footer appended when no search ran", bool(out and "no live web search ran" in out))
    check("footer says the plugin, the subject and OBE",
          bool(out and "hubris" in out and "OBE" in out and "games." in out))
    check("footer is idempotent", sf.on_transform_llm_output(response_text=out, session_id="t1") is None)

    # A bare suppression token must never be stamped: the footer would stop the delivery
    # layer recognising it, turning a silent turn into a visible message.
    sf.on_pre_llm_call(session_id="t_silent", user_message="what is the best ATM10 guide right now?")
    check("[SILENT] is left untouched",
          sf.on_transform_llm_output(response_text="[SILENT]", session_id="t_silent") is None)
    sf.on_pre_llm_call(session_id="t_silent2", user_message="what is the best ATM10 guide right now?")
    check("[SILENT] with trailing whitespace is left untouched",
          sf.on_transform_llm_output(response_text="  [SILENT] \n", session_id="t_silent2") is None)

    # A model routinely puts a line after the token. The footer must still not be appended,
    # or the delivery layer stops recognising the token and the silent turn becomes visible.
    for sid, reply, label in (
        ("t_silent3", "[SILENT]\n\nNothing to report tonight.", "blank line after the token"),
        ("t_silent4", "[SILENT]\nNothing to report tonight.", "same-line block after the token"),
        ("t_silent5", "**`[SILENT]`**\nNothing to report.", "token wrapped in markdown"),
        ("t_silent6", "SILENT\nNo change since yesterday.", "bare SILENT word"),
    ):
        sf.on_pre_llm_call(session_id=sid, user_message="what is the best ATM10 guide right now?")
        check(f"[SILENT] left untouched: {label}",
              sf.on_transform_llm_output(response_text=reply, session_id=sid) is None)

    # Only the top of the reply counts. A token quoted further down is prose, and the footer
    # still belongs there: the reply is visible either way.
    sf.on_pre_llm_call(session_id="t_silent7", user_message="what is the best ATM10 guide right now?")
    quoted = sf.on_transform_llm_output(
        response_text="Here is what the job would print:\n\n[SILENT]\n\nAnd that is the whole reply.",
        session_id="t_silent7",
    )
    check("a [SILENT] quoted in the body does not suppress the footer", bool(quoted and "hubris" in quoted))

    # research turn with a real web search -> no footer
    sf.on_pre_llm_call(session_id="t2", user_message="what is the current price of a 3080?")
    sf.on_post_tool_call(tool_name="web_search", session_id="t2", result="{}")
    check("no footer when a web search ran", sf.on_transform_llm_output(response_text="x", session_id="t2") is None)

    # MCP search tools count
    sf.on_pre_llm_call(session_id="t3", user_message="latest ATM10 version?")
    sf.on_post_tool_call(tool_name="mcp__searxng__searxng_web_search", session_id="t3")
    check("MCP search counts as research", sf.on_transform_llm_output(response_text="x", session_id="t3") is None)

    # Research performed inside a code tool silences the footer too: the hook reads its args.
    sf.on_pre_llm_call(session_id="t3c", user_message="best model for coding right now")
    sf.on_post_tool_call(
        tool_name="execute_code", session_id="t3c",
        args={"code": "from hermes_tools import web_search, web_extract\nweb_search('x')"},
    )
    check(
        "research inside execute_code silences the footer",
        sf.on_transform_llm_output(response_text="x", session_id="t3c") is None,
    )

    # ... and a code tool that never left the machine leaves the footer in place.
    sf.on_pre_llm_call(session_id="t3d", user_message="best model for coding right now")
    sf.on_post_tool_call(tool_name="execute_code", session_id="t3d", args={"code": "print(2 + 2)"})
    check(
        "local code does not silence the footer",
        sf.on_transform_llm_output(response_text="x", session_id="t3d") is not None,
    )

    # a local file search is NOT research: the footer must still fire
    sf.on_pre_llm_call(session_id="t3b", user_message="latest ATM10 version?")
    sf.on_post_tool_call(tool_name="search_files", session_id="t3b")
    check(
        "a local file search does not silence the footer",
        sf.on_transform_llm_output(response_text="x", session_id="t3b") is not None,
    )

    # unrelated tool does not count
    sf.on_pre_llm_call(session_id="t4", user_message="latest ATM10 version?")
    sf.on_post_tool_call(tool_name="read_file", session_id="t4")
    check("a file read is not a search", sf.on_transform_llm_output(response_text="x", session_id="t4") is not None)

    # the ledger is per session: a search in one session does not excuse another
    sf.on_pre_llm_call(session_id="t4b", user_message="latest ATM10 version?")
    sf.on_pre_llm_call(session_id="t4c", user_message="latest ATM10 version?")
    sf.on_post_tool_call(tool_name="web_search", session_id="t4b")
    check(
        "a search in another session does not silence this one",
        sf.on_transform_llm_output(response_text="x", session_id="t4c") is not None,
    )

    # local turn -> nothing at all
    check(
        "local turn gets no directive",
        sf.on_pre_llm_call(session_id="t5", user_message="is hermes gateway running?") is None,
    )
    check("local turn gets no footer", sf.on_transform_llm_output(response_text="yes", session_id="t5") is None)

    # multimodal turn: text parts only
    parts = [{"type": "text", "text": "what is the current price of a 1070 Ti?"}, {"type": "image_url"}]
    check(
        "multimodal text parts are read",
        bool(sf.on_pre_llm_call(session_id="t6", user_message=parts)),
    )

    # config can disable the plugin
    previous = with_settings(enabled=False)
    try:
        check(
            "config can disable the plugin",
            sf.on_pre_llm_call(session_id="t7", user_message="what is the best GPU right now?") is None,
        )
    finally:
        sf._CTX = previous

    # a quiet platform gets neither the directive nor the footer
    previous = with_settings(quiet_platforms=["discord_voice"])
    try:
        check(
            "quiet platform gets no directive",
            sf.on_pre_llm_call(
                session_id="t8", user_message="latest ATM10 version?", platform="discord_voice"
            ) is None,
        )
        check(
            "quiet platform gets no footer",
            sf.on_transform_llm_output(response_text="x", session_id="t8") is None,
        )
        check(
            "a platform not named as quiet still gets the directive",
            bool(sf.on_pre_llm_call(
                session_id="t9", user_message="latest ATM10 version?", platform="cli"
            )),
        )
    finally:
        sf._CTX = previous

    # cron is quiet out of the box: a scheduled job's internal brief is not a question the
    # user asked, so it gets neither the directive nor a footer on a routine job report.
    previous = sf._CTX
    sf._CTX = None  # no context -> the shipped defaults
    try:
        check(
            "cron gets no directive by default",
            sf.on_pre_llm_call(
                session_id="t_cron", user_message="latest ATM10 version?", platform="cron"
            ) is None,
        )
        check(
            "cron gets no footer by default",
            sf.on_transform_llm_output(response_text="x", session_id="t_cron") is None,
        )
    finally:
        sf._CTX = previous

    previous = with_settings(quiet_platforms=[])
    try:
        check(
            "clearing quiet_platforms opts cron back in",
            bool(sf.on_pre_llm_call(
                session_id="t_cron2", user_message="latest ATM10 version?", platform="cron"
            )),
        )
    finally:
        sf._CTX = previous

    # the manifest's default and the code's default are the same value, so the Desktop form
    # cannot show one thing while the plugin does another. Both paths are checked: with no
    # context at all, and with a live context whose stored config is empty (a fresh install).
    for label, ctx in (("no context", None), ("live context, empty config", _EmptyCtx())):
        previous = sf._CTX
        sf._CTX = ctx
        try:
            shipped = sf._settings()["quiet_platforms"]
        finally:
            sf._CTX = previous
        check(f"shipped default for quiet_platforms is cron ({label})", shipped == ["cron"])

    # ...and the same through the real hook, which is where the drift actually showed up: a
    # default written at the read site rather than taken from _DEFAULTS.
    previous = sf._CTX
    sf._CTX = _EmptyCtx()
    try:
        check(
            "a fresh install is quiet on cron through the live read path",
            sf.on_pre_llm_call(
                session_id="t_cron3", user_message="latest ATM10 version?", platform="cron"
            ) is None,
        )
    finally:
        sf._CTX = previous

    # The hook must actually plumb the host's history into the classifier, or the whole turn-scope
    # feature is inert and every test above passes against code that never runs.
    previous = with_settings()
    try:
        sf.on_pre_llm_call(
            session_id="t_lw1",
            user_message="which one is it?  i see two local models in the list",
            conversation_history=[{"role": "tool", "tool_name": "terminal"}],
        )
        check("hook: a local-work session keeps this turn quiet",
              sf._TURNS["t_lw1"]["research"] is False)
        sf.on_pre_llm_call(
            session_id="t_lw2",
            user_message="which one is it?  i see two local models in the list",
            conversation_history=[],
        )
        check("hook: the same turn in a fresh session is classified normally",
              sf._TURNS["t_lw2"]["research"] is True)
        # A host that passes nothing must not crash the turn.
        sf.on_pre_llm_call(session_id="t_lw3", user_message="latest ATM10 version?")
        check("hook: missing conversation_history is harmless",
              sf._TURNS["t_lw3"]["research"] is True)
    finally:
        sf._CTX = previous

    # ...and a machine turn is quiet through the hook as well
    previous = with_settings()
    try:
        sf.on_pre_llm_call(
            session_id="t_machine",
            user_message="# Kanban task t_9: update the ATM10 pack to the latest version",
            platform="kanban",
        )
        check("hook: a kanban task body is not a research request",
              sf._TURNS["t_machine"]["research"] is False)
    finally:
        sf._CTX = previous

    # a user phrase teaches a new domain without editing the classifier
    previous = with_settings(extra_trigger_phrases=["kubernetes"])
    try:
        check(
            "extra trigger phrase fires",
            classifier.classify("kubernetes pod stuck", extra_trigger_phrases=["kubernetes"]).research,
        )
        check(
            "settings reach the classifier through the hook",
            bool(sf.on_pre_llm_call(session_id="t10", user_message="kubernetes pod stuck")),
        )
    finally:
        sf._CTX = previous

    # a phrase the user taught wins; a phrase they banned wins harder
    check(
        "extra skip phrase wins over a trigger",
        not classifier.classify(
            "what is the best thesis topic", extra_skip_phrases=["thesis topic"]
        ).research,
    )

    # An explicit request gets the directive but no footer unless asked for -- otherwise the
    # plugin nags about a promise the user already made.
    sf.on_pre_llm_call(session_id="n1", user_message="please look this up for me")
    check(
        "explicit-only turn is quiet in the reply by default",
        sf.on_transform_llm_output(response_text="x", session_id="n1") is None,
    )
    previous = with_settings(nag_on_explicit=True)
    try:
        sf.on_pre_llm_call(session_id="n2", user_message="please look this up for me")
        out2 = sf.on_transform_llm_output(response_text="x", session_id="n2")
        check("nag_on_explicit restores the footer", bool(out2 and "OBE" in out2))
    finally:
        sf._CTX = previous

    # A taxonomy turn still gets the footer, because nobody asked.
    sf.on_pre_llm_call(session_id="n3", user_message="what is the current modpack version?")
    check(
        "a taxonomy turn still gets the footer",
        bool(sf.on_transform_llm_output(response_text="x", session_id="n3")),
    )

    # a phrase list is accepted in every shape the settings have ever stored
    parse = sf._as_phrases
    check("phrases: comma separated", parse("kubectl, homelab price") == ["kubectl", "homelab price"])
    check("phrases: one per line", parse("kubectl\nhomelab price") == ["kubectl", "homelab price"])
    check("phrases: a JSON array string", parse('["kubectl", "homelab price"]') == ["kubectl", "homelab price"])
    check("phrases: a real list", parse(["kubectl", "homelab price"]) == ["kubectl", "homelab price"])
    check("phrases: empty string is none", parse("") == [])
    check("phrases: blank entries dropped", parse(" a , , b ") == ["a", "b"])
    check("phrases: junk is none", parse(None) == [] and parse(42) == [])

    # the form stores a string, so that path must reach the classifier too
    previous = with_settings(extra_trigger_phrases="kubernetes, terraform")
    try:
        check(
            "a comma-separated setting reaches the classifier",
            classifier.classify(
                "kubernetes pod stuck",
                extra_trigger_phrases=sf._settings()["extra_trigger_phrases"],
            ).research,
        )
    finally:
        sf._CTX = previous


test_hooks()

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    raise SystemExit(1)
print("all checks passed")
