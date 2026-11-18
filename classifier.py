"""Turn classification for hubris.

One job: decide whether a user message turns on facts that live outside this machine and
outside the model's weights. Deterministic regex work, no model call, no network.

Three layers, in this order:

  SKIP_PATTERNS   things that must never leave the machine: this install, the family, code,
                  memory, bare acknowledgements. Checked first and wins over everything.
  CORE_PATTERNS   question *shape*: recency, comparison, an explicit "go and find out",
                  how-to. Grammar rather than subject matter, so a user does not switch it
                  off by accident and degrade the plugin's judgement.
  TAXONOMY        domain *vocabulary*, from taxonomy.py, filtered by the topic and subject
                  switches. This is the part a user owns.

The classifier is deliberately asymmetric. A false positive costs one nudge line and, at
worst, one visible footer. A false negative is the failure this plugin exists to prevent,
which is an agent answering from memory something the internet already settled.

Every pattern is an *external-facts* shape, not an everyday word. An earlier version fired
on bare "now", "still", "today" and "which is", which put the footer on "are you still
working" and on local device control. That is why the core layer holds phrases rather than
single common words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .taxonomy import TOPICS, enabled_subjects

# --- things that are never an external-facts question -------------------------------------

SKIP_PATTERNS = [
    # this installation, the box, the fleet
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",              # IP addresses
    r"\b(localhost|ssh|scp|tailscale|ping|systemctl|journalctl|docker|pct|proxmox)\b",
    r"\b(cron|gateway|plugin|kanban|profile|skill|session|dashboard)\b",
    r"/(?:root|mnt|etc|proc|var|opt|home|tmp|usr)/",  # filesystem paths
    r"\b(service|unit|process|pid|log ?file)\b",
    # personal record and family: recall of our own history, not the state of the world.
    # Kinship rather than a list of first names: a published plugin cannot know whose family it
    # runs beside, and a hardcoded name list is both useless to anyone else and a privacy leak
    # for the author. Anyone whose household uses first names adds them to `exempt_patterns`,
    # which is per-installation and never leaves `config.yaml`.
    # Entitlement *rules* stay researchable through the law topic; the household records do not.
    r"\b(my |our )?(wife|husband|spouse|partner|son|daughter|kid|child|children|"
    r"family|mom|dad|mother|father|brother|sister|grandma|grandpa)\b",
    r"\b(troop|scout|school|iep|va claim|appointment|"
    r"doctor|prescription|paycheck|shutdown)\b",
    # coding and repo work
    r"\b(repo|repository|commit|branch|diff|patch|refactor|unit test|pytest|traceback|"
    r"stack trace|compile|import error|function|class|regex)\b",
    # memory, recall, and meta about the assistant itself
    r"\b(remember|recall|your memory|last time|earlier|yesterday we|we discussed|"
    r"as i said|your training|model cutoff)\b",
    # a standing instruction about how to answer later is not a question now
    r"\b(?:when|whenever|if) you (?:are|were|do) (?:research|search|look)",
    # operational confirmation, not research: a bare acknowledgement and nothing else
    r"^\s*(?:yes|no|ok|okay|sure|thanks|thank you|do it|go ahead|continue|stop|"
    r"proceed|retry|again)[.!]*\s*$",
]

# --- question shape: an explicit request to go and look -----------------------------------
#
# Only the requests that need no domain knowledge to honour. Everything a user might want to
# switch off -- recency wording, comparisons, every domain word -- lives in the taxonomy, so
# disabling a topic actually silences it instead of leaving a "latest" to fire behind your back.

CORE_PATTERNS = [
    # an explicit request to go and find something, or a link to go and read
    r"(\b(look (?:it |this |that )?up|looking for|find out|search (?:for|online|the web)|"
    r"web search|check online|search online|go find|can you (?:find|look|check|search|see if)|"
    r"research|sources? for)\b|https?://)",
    # how-to and where-to: asking for instructions is asking for an external artifact
    r"\b(how do i|how to|how does|where can i|where do i|does .* support|is it possible)\b",
]

# Hardware-resource words are a local-inventory signal only when nothing else says otherwise:
# "what's the best local model for 8GB of VRAM" is a question about models, and the word VRAM
# must not bury it. So this list is checked separately, and an AI match cancels it.
RESOURCE_SKIP = r"\b(disk|ram|cpu|gpu|vram|port \d+)\b"


def _resource_is_the_subject(text: str) -> bool:
    """True when the message is about this machine's resources, not about a model's needs."""
    if not re.search(RESOURCE_SKIP, text, re.IGNORECASE):
        return False
    for subject in TOPICS[0].subjects:  # the AI topic
        for pattern in subject.patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False
    return True


# An injected instruction block is machinery, not a question: an async-delegation result, a
# kanban task body, a background-process notice. These arrive as the "user" message, so without
# this the plugin scores a machine's text as though the user had typed it. Measured 2026-11-18:
# two of seventeen no-search fires were exactly this shape.
_MACHINE_PREAMBLE_RE = re.compile(
    r"^\s*(?:\[(?:ASYNC DELEGATION|IMPORTANT|OUT-OF-BAND USER MESSAGE|Replying to|System:|"
    r"The user sent)|# Kanban task\b|\[Replying to:)",
    re.IGNORECASE,
)

# Local machine work: the words that make a message about this box, not about the world. The
# taxonomy owns model names as AI vocabulary, which is right for "which model is better" and wrong
# for "the local model is up and running now". A continuation turn carries these, so they are only
# consulted when the session is already doing local work.
_LOCAL_WORK_RE = re.compile(
    r"\b(?:llama\.?cpp|llama-server|ollama|vllm|gguf|model load|"
    # "local <thing>": the words that make a model reference about this box. Model names are public
    # product names and already live in the taxonomy, so listing them here leaks nothing.
    r"local ?(?:models?|servers?|instances?|llms?|run|build|"
    r"qwen|gemma|llama|mistral|glm|kimi|deepseek|phi|nomic)|"
    r"systemctl|journalctl|ps aux|"
    r"localhost|127\.0\.0\.1|exit code|stdout|stderr)\b",
    re.IGNORECASE,
)

# Tools whose use marks a session as local machine work rather than external research.
_LOCAL_TOOL_RE = re.compile(
    r"^(?:read_file|write_file|patch|search_files|terminal|process_manage|"
    r"local_models|look_at_screen|screen_capture)",
    re.IGNORECASE,
)


# Asking for a judgement — best, cheapest, compare — is asking for knowledge that lives outside
# this machine, whatever else the sentence mentions. This is the exception to the local-work rule:
# "what's the best local model for 8GB of VRAM" is about models, not about our box. Mirrors the
# reasoning behind `_resource_is_the_subject`.
_RECOMMEND_RE = re.compile(
    r"\b(?:best|cheapest|fastest|top|recommended|worth it|"
    r"compar(?:e|ison)|vs\.?|better|worse)\b",
    re.IGNORECASE,
)


# Own-app vocabulary comes from the installation, not from the plugin: a published plugin cannot
# know what its user has built. `own_apps` in the settings supplies the names, and the judgement
# exemption below still applies, because "review our dashboard for custom components vs existing
# libraries" is asking what the ecosystem offers and silencing it would be a real loss.
def _own_app_re(own_apps):
    """A matcher for this installation's own product names, or None when none are configured."""
    phrases = _user_phrases(own_apps)
    if not phrases:
        return None
    return re.compile(r"\b(?:" + "|".join(phrases) + r")\b", re.IGNORECASE)


def _is_machine_turn(text: str) -> bool:
    """True when the "user" message is an injected block rather than something typed."""
    return bool(_MACHINE_PREAMBLE_RE.match(text))


def session_is_local_work(history) -> bool:
    """True when this session is already working on the local machine.

    ``history`` is the turn's ``conversation_history`` as the host passes it: a list of message
    dicts (or objects with a ``role``). A session counts as local work when it has already used a
    local tool, or when an earlier turn carried local-machine vocabulary. Used only to decide
    whether local vocabulary is the subject of the message or just a word inside it.
    """
    for message in history or ():
        role = getattr(message, "role", None)
        if role is None and isinstance(message, dict):
            role = message.get("role")
        if role != "tool":
            continue
        name = getattr(message, "tool_name", None)
        if name is None and isinstance(message, dict):
            name = message.get("tool_name") or message.get("name")
        if name and _LOCAL_TOOL_RE.match(str(name)):
            return True
    return False


# A bare acknowledgement is the one message that is never a request, however it is phrased.
BARE_ACK_RE = re.compile(
    r"^\s*(?:yes|no|ok|okay|sure|thanks|thank you|do it|go ahead|continue|stop|"
    r"proceed|retry|again)[.!]*\s*$",
    re.IGNORECASE,
)

# A complaint about the agent's searching is not a request to search. Checked before CORE,
# because the sentence contains the very words CORE looks for ("you never search online").
COMPLAINT_RE = re.compile(
    r"\b(?:you never|you didn'?t|why didn'?t you|why did you not|my complaint|"
    r"i complained|stop guessing|stop searching)\b",
    re.IGNORECASE,
)


QUESTION_SHAPE = re.compile(r"\?")

# A clause that is actually a request. `which` is deliberately absent: as a determiner
# ("which sucks") it opens a relative clause, not a question, and it was letting a statement
# about a past election through. A real "which" question almost always carries a "?".
_OPENERS = (
    "what", "who", "when", "where", "why", "how", "is", "are", "was", "were", "does", "do",
    "did", "can", "could", "should", "would", "will", "any",
    # imperatives that ask for something external
    "give", "show", "find", "get", "send", "list", "bring", "pull", "point", "tell",
    "check", "look", "compare", "search", "research",
)
_CLAUSE_SPLIT = re.compile(r"[.!?;\n]+")
_OPENER_RE = re.compile(
    r"^\W*(?:what|who|when|where|why|how|is|are|was|were|does|do|did|can|could|should|would|"
    r"will|any|give|show|find|get|send|list|bring|pull|point|tell|check|look|compare|search|"
    r"research)\b"
    # `which` opens a real question ("which modpack version") but also a relative clause
    # ("which sucks"); only the first kind is a request.
    r"|^\W*which\b(?!\s+(?:is|was|sucks|means|makes|would|could|has|had|i|we|they|he|she)\b)"
    # A superlative-leading fragment is a request for a recommendation: "best model for coding".
    r"|^\W*(?:best|cheapest|fastest|top|recommended)\b",
    re.IGNORECASE,
)

# A question can sit mid-clause ("in the recent elections who won the mayor race") and a
# request can be a statement of need ("I just need a checklist"). Both are requests; neither
# starts with a question word.
_EMBEDDED_QUESTION_RE = re.compile(
    r"\b(?:who|what|when|where|which|how|why)\b\s+(?:\w+\s+){0,3}?"
    r"(?:won|is|are|was|were|did|does|do|can|could|should|would|will|has|have|much|many)\b",
    re.IGNORECASE,
)
_NEED_RE = re.compile(
    r"\b(?:i (?:just |really |only )?need|i'?d like|i would like|i want|i'?m looking|"
    r"i am looking|looking for|help me|i'?m trying|i am trying|any idea|do you know|"
    r"tell me about|(?:give|show|send|get|find|list|bring|pull|point)\s+me)\b",
    re.IGNORECASE,
)

# Pasted logs and code are not prose. Matching "version" inside `x.version`, or "available"
# inside a provider error, is how a classifier earns a false positive with no recall cost to
# avoid: strip them before any pattern sees the text. URLs are kept -- a pasted link is itself
# a request to read it.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_LOG_LINE_RE = re.compile(
    r"^(?:traceback \(most recent call last\)|file \".*\", line \d+|"
    r"\s*at [\w.$]+\(.*\)|\w*(?:error|exception|warning)\w*: .*)$",
    re.IGNORECASE | re.MULTILINE,
)


def _scrub(text: str) -> str:
    """Remove pasted code and log lines, keeping prose and links."""
    text = _FENCE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _LOG_LINE_RE.sub(" ", text)
    return text


def _is_request(text: str) -> bool:
    """True when some clause is a question or an imperative ask.

    Clause-scoped on purpose: a statement of fact that happens to mention an election is not a
    question just because a question word appears later in a different clause.
    """
    if "?" in text:
        return True
    if _EMBEDDED_QUESTION_RE.search(text) or _NEED_RE.search(text):
        return True
    for clause in _CLAUSE_SPLIT.split(text):
        if _OPENER_RE.match(clause.strip()):
            return True
    return False



@dataclass(frozen=True)
class Verdict:
    research: bool
    reason: str
    subjects: tuple[str, ...] = ()


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _user_phrases(phrases) -> list[str]:
    """User-supplied phrases, escaped so a stray bracket cannot become a broken regex."""
    out = []
    for phrase in phrases or ():
        cleaned = _normalise(str(phrase))
        if cleaned:
            out.append(re.escape(cleaned))
    return out


def classify(
    message: str,
    extra_trigger_phrases=None,
    extra_skip_phrases=None,
    live_subjects: set[str] | None = None,
    local_work: bool = False,
    own_apps=None,
) -> Verdict:
    """Decide whether this message should be researched before it is answered.

    ``extra_*_phrases`` come from the plugin's own settings, so a user can teach it a domain
    that is not in the taxonomy. ``live_subjects`` is the resolved set of enabled
    ``topic.subject`` keys; ``None`` means every subject, which is what a probe or a test
    with no settings wants. Skip wins over trigger: "never leave the machine for this" is
    the safer override.

    ``local_work`` says the session is already doing local machine work, so local vocabulary in
    this message is about this box. It silences a taxonomy match and nothing else: an explicit
    request in the same message still fires.
    """
    text = _scrub(_normalise(message))
    if not text.strip():
        return Verdict(False, "empty")

    # An injected block is the machinery talking, not the user asking. Checked before everything,
    # because a delegated task body can name any subject at all and no word list can tell it from
    # a real question.
    if _is_machine_turn(message or ""):
        return Verdict(False, "machine-turn")

    # A bare acknowledgement is never a request, whatever else it might match.
    if BARE_ACK_RE.match(text):
        return Verdict(False, "acknowledgement")

    # A phrase the user taught the plugin is an explicit opt-in, and their never-list is an
    # explicit opt-out. Both outrank everything below.
    for pattern in _user_phrases(extra_skip_phrases):
        if re.search(pattern, text, re.IGNORECASE):
            return Verdict(False, f"user-skip:{pattern[:24]}")
    for pattern in _user_phrases(extra_trigger_phrases):
        if re.search(pattern, text, re.IGNORECASE):
            return Verdict(True, "user-phrase:" + pattern[:24], ("user",))

    # A complaint about searching mentions searching; it is not a request to search.
    if COMPLAINT_RE.search(text):
        return Verdict(False, "complaint")

    # CORE is an explicit request by definition, so it needs neither the clause gate nor the
    # local-domain skip list. This ordering is the whole point: "did you check online whether
    # other Hermes users hit this?" is research, and a skip rule on the word "hermes" must not
    # swallow it. Measured on 77 real directives, skipping first cost 42% recall.
    core_hits = []
    for pattern in CORE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            core_hits.append(m.group(0).strip())

    if not core_hits:
        for pattern in SKIP_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return Verdict(False, f"local-or-personal:{pattern[:24]}")
        if _resource_is_the_subject(text):
            return Verdict(False, "local-or-personal:resource")
        # This installation's own apps are local unless the message asks for a judgement about them.
        own_re = _own_app_re(own_apps)
        if own_re is not None and own_re.search(text) and not _RECOMMEND_RE.search(text):
            return Verdict(False, "own-app")
        if not _is_request(text):
            return Verdict(False, "no-request")

    # A session already doing local machine work reads its own vocabulary differently: "qwen is up
    # and running now" is a status update about this box, not a question about which model is best.
    # Only the taxonomy match is suppressed, and only when the message carries a local-work word,
    # no explicit request, and is not asking for a judgement. Measured 2026-11-18: four of
    # seventeen no-search fires were this shape, and "best local model for 8GB of VRAM" must survive.
    if (
        local_work
        and not core_hits
        and _LOCAL_WORK_RE.search(text)
        and not _RECOMMEND_RE.search(text)
    ):
        return Verdict(False, "local-work-continuation")

    hits: list[str] = list(core_hits)
    subjects: list[str] = []

    if live_subjects is None:
        live_subjects = {s.full_key for t in TOPICS for s in t.subjects}
    for topic in TOPICS:
        for subject in topic.subjects:
            if subject.full_key not in live_subjects:
                continue
            for pattern in subject.patterns:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    hits.append(m.group(0).strip())
                    subjects.append(subject.full_key)
                    break

    if not hits:
        return Verdict(False, "no-external-trigger")

    found = tuple(sorted(set(subjects)))
    label = ",".join(found) or "shape"
    return Verdict(True, f"external[{label}]:" + ",".join(sorted(set(hits))[:4]), found)


# Tools that reach the live web. A name fragment is enough: MCP servers namespace their tools
# (`mcp__searxng__searxng_web_search`), and a search that errored still counts, because the
# footer says no search *ran*, and an attempt did run.
WEB_TOOL_HINTS = (
    "web_search", "websearch", "search_web", "web_extract", "url_read", "read_url",
    "fetch_url", "open_url", "browse_url", "searxng", "perplexica", "brave_search",
    "brave_web", "tavily", "exa_search", "exa_web", "serper", "firecrawl", "jina",
    "browser_", "google_search", "duckduckgo", "wikipedia",
)

# Tools that run arbitrary code. The agent reaches the live web from inside them too:
# `execute_code` imports web_search and web_extract from hermes_tools, and `terminal` runs curl.
# The outer tool NAME therefore says nothing about whether the turn was researched. Observed
# live on 2026-11-09: a turn that read six pages through execute_code came back stamped "no live
# web search ran", which is exactly how a warning loses its authority. Their arguments are read
# instead. See `counts_as_research`.
CODE_TOOL_HINTS = ("execute_code", "terminal", "run_command", "shell", "bash", "python", "node")

# A web function called from inside code: the call itself is the evidence, so no URL is needed.
_CODE_WEB_CALLS = (
    "web_search(", "web_extract(", "web_url_read(", "websearch(", "search_web(",
    "searxng_web_search(", "perplexica_search(", "brave_web_search(", "brave_search(",
    "tavily", "exa_search(", "firecrawl", "jina_reader",
)

# A raw fetch has to show both halves: a fetching call or command AND an http URL. Code that
# merely prints or echoes a link is not research, because a false "researched" verdict silences
# the footer on an answer nobody checked, and that is the one failure this plugin exists to stop.
_FETCH_CALLS = ("urlopen(", "requests.get(", "requests.post(", "httpx.", "aiohttp.", "http.get(")
_FETCH_COMMANDS = ("curl", "wget", "aria2c", "lynx", "links")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)

# Local search is not web research. `search_files` is a ripgrep over the disk and
# `session_search` reads the local session DB; both used to satisfy the old "search"
# substring test, which silenced the footer on turns that never left the machine.
LOCAL_SEARCH_HINTS = (
    "search_files", "file_search", "session_search", "search_history", "search_sessions",
    "code_search", "grep", "search_docs", "search_skills", "tool_search", "memory_search",
)


def _args_text(args: object) -> str:
    """Every string inside a tool's arguments, flattened.

    `execute_code` carries ``{"code": ...}``, `terminal` carries ``{"command": ...}``, and a
    later tool may nest them, so walk the structure instead of assuming one key.
    """
    if args is None:
        return ""
    if isinstance(args, str):
        return args
    if isinstance(args, dict):
        return "\n".join(_args_text(value) for value in args.values())
    if isinstance(args, (list, tuple, set)):
        return "\n".join(_args_text(value) for value in args)
    return str(args)


def _code_reaches_web(args: object) -> bool:
    """True when a code tool's arguments show it fetched from the live web.

    Two shapes count: a web function imported or called from inside the code (the name is the
    proof), and a raw fetch that carries both a fetching verb and an http URL. A URL on its own
    never counts, so code that prints a link cannot silence the footer.
    """
    text = _normalise(_args_text(args))
    if not text:
        return False
    if any(marker in text for marker in _CODE_WEB_CALLS):
        return True
    if not _URL_RE.search(text):
        return False
    if any(call in text for call in _FETCH_CALLS):
        return True
    return any(re.search(rf"\b{command}\b", text) for command in _FETCH_COMMANDS)


def counts_as_research(tool_name: str, args: object = None, result: object = None) -> bool:
    """True when a tool call actually reached the live web.

    A code tool is judged by what it ran, not by its name; a named web tool is its own proof.
    """
    name = _normalise(tool_name)
    if not name:
        return False
    if any(hint in name for hint in LOCAL_SEARCH_HINTS):
        return False
    if name.startswith("research_guard_"):
        return False  # a different plugin's bookkeeping tools
    if any(hint in name for hint in WEB_TOOL_HINTS):
        return True
    if any(hint in name for hint in CODE_TOOL_HINTS):
        return _code_reaches_web(args)
    return False


def resolve_subjects(topic_flags: dict[str, bool], subject_flags: dict[str, bool]) -> set[str]:
    """Thin re-export so the hook layer imports one module, not two."""
    return enabled_subjects(topic_flags, subject_flags)
