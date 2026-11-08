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
    # Entitlement *rules* stay researchable through the law topic; the claim packet does not.
    r"\b(sarah|violet|jackson|troop|scout|school|iep|va claim|appointment|"
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
) -> Verdict:
    """Decide whether this message should be researched before it is answered.

    ``extra_*_phrases`` come from the plugin's own settings, so a user can teach it a domain
    that is not in the taxonomy. ``live_subjects`` is the resolved set of enabled
    ``topic.subject`` keys; ``None`` means every subject, which is what a probe or a test
    with no settings wants. Skip wins over trigger: "never leave the machine for this" is
    the safer override.
    """
    text = _scrub(_normalise(message))
    if not text.strip():
        return Verdict(False, "empty")

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
        if not _is_request(text):
            return Verdict(False, "no-request")

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

# Local search is not web research. `search_files` is a ripgrep over the disk and
# `session_search` reads the local session DB; both used to satisfy the old "search"
# substring test, which silenced the footer on turns that never left the machine.
LOCAL_SEARCH_HINTS = (
    "search_files", "file_search", "session_search", "search_history", "search_sessions",
    "code_search", "grep", "search_docs", "search_skills", "tool_search", "memory_search",
)


def counts_as_research(tool_name: str, result: object = None) -> bool:
    """True when a tool call actually reached the live web."""
    name = _normalise(tool_name)
    if not name:
        return False
    if any(hint in name for hint in LOCAL_SEARCH_HINTS):
        return False
    if name.startswith("research_guard_"):
        return False  # a different plugin's bookkeeping tools
    return any(hint in name for hint in WEB_TOOL_HINTS)


def resolve_subjects(topic_flags: dict[str, bool], subject_flags: dict[str, bool]) -> set[str]:
    """Thin re-export so the hook layer imports one module, not two."""
    return enabled_subjects(topic_flags, subject_flags)
