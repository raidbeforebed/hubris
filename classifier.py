"""Turn classification for hubris.

One job: decide whether a user message turns on facts that live outside this machine and
outside the model's weights. Deterministic regex work, no model call, no network.

The classifier is deliberately asymmetric. A false positive costs one nudge line and, at
worst, one visible footer. A false negative is the failure this plugin exists to prevent,
which is an agent answering from memory something the internet already settled. So the
skip list is explicit and narrow, and anything that survives it with a question shape is
treated as researchable.

Every trigger is an *external-facts* shape, not an everyday word. An earlier version fired
on bare "now", "still", "today" and "which is", which put the footer on "are you still
working" and on local device control. Recency only counts in a phrase that means the world
moved ("current version", "still supported", "as of"), never on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- things that are never an external-facts question -------------------------------------

SKIP_PATTERNS = [
    # this installation, the box, the fleet
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",              # IP addresses
    r"\b(localhost|ssh|scp|tailscale|ping|systemctl|journalctl|docker|pct|proxmox)\b",
    r"\b(hermes|cron|gateway|plugin|kanban|profile|skill|session|dashboard|mcp)\b",
    r"/(?:root|mnt|etc|proc|var|opt|home|tmp|usr)/",  # filesystem paths
    r"\b(disk|ram|cpu|gpu|vram|port \d+|service|unit|process|pid|log ?file)\b",
    # personal and family
    r"\b(sarah|violet|jackson|troop|scout|school|iep|va claim|disability|appointment|"
    r"doctor|prescription|fehb|fedvip|paycheck|shutdown)\b",
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

# --- things that make a question turn on the outside world ---------------------------------

TRIGGER_PATTERNS = [
    # recency, only in a phrase that means the world moved
    r"\b(latest|newest|current|currently|up to date|up-to-date|this (?:year|month|week)|"
    r"as of|new release|recently|recent|anymore|still (?:supported|available|made|sold|"
    r"maintained|in print)|new (?:version|model|release))\b",
    # money, versions, availability
    r"\b(price|prices|pricing|cost|costs|how much|cheap(?:est)?|deal|discount|sale|msrp|"
    r"in stock|availab\w*|release date|version|versions|changelog|roadmap|"
    r"deprecat\w*|retired|end of life|eol)\b",
    # evaluation and comparison
    r"\b(best\b(?!\s+(?:to|for)\b)|better than|worst|worth it|vs\.?|versus|compare|comparison|"
    r"review|reviews|benchmark|rating|recommend|alternative|pros and cons)\b",
    # an explicit request to go and find something, or a link to go and read
    r"(\b(look (?:it |this |that )?up|looking for|find out|search (?:for|online|the web)|"
    r"can you (?:find|look|check|search|see if)|research|sources? for)\b|https?://)",
    # how-to and where-to, which usually has a current official answer
    r"\b(how do i|how to|how does|where can i|where do i|what is the|"
    r"what are the|who is|does .* support|is it possible)\b",
    # domains where the answer moves and a stale answer is costly
    r"\b(news|weather|forecast|score|election|(?<!in )law|laws|legal|illegal|regulation|"
    r"deadline|tax|interest rate|tariff|outbreak|recall|docs|documentation|api reference)\b",
    # games and modpacks: the case that started this plugin
    r"\b(mods?|modpack|modded|minecraft|atm ?10|atm star|ender dragon|recipe|quest ?book|wiki)\b",
    # asking for a guide at all is asking for an external artifact
    r"\b(guide|guides|progression|walkthrough|tutorial|checklist|where to start|"
    r"getting started|what order)\b",
]


QUESTION_SHAPE = re.compile(r"\?|\b(what|which|who|when|where|why|how|is|are|does|do|can|"
                             r"could|should|would|compare|recommend|research|need|find)\b|"
                             r"\b(?:give|show|find|get|send|list|bring|pull)\s+me\b",
                             re.IGNORECASE)


@dataclass(frozen=True)
class Verdict:
    research: bool
    reason: str


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


def classify(message: str, extra_trigger_phrases=None, extra_skip_phrases=None) -> Verdict:
    """Decide whether this message should be researched before it is answered.

    ``extra_*_phrases`` come from the plugin's own settings, so a user can teach it a domain
    without editing this file. Skip wins over trigger: "never leave the machine for this" is
    the safer override.
    """
    text = _normalise(message)
    if not text:
        return Verdict(False, "empty")

    for pattern in _user_phrases(extra_skip_phrases) + SKIP_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return Verdict(False, f"local-or-personal:{pattern[:24]}")

    # A phrase the user taught the plugin is an explicit opt-in, so it does not have to pass
    # the built-in shape test: "kubernetes pod stuck" is a fragment, but the user said this
    # domain is researchable and that judgment outranks the heuristic.
    for pattern in _user_phrases(extra_trigger_phrases):
        if re.search(pattern, text, re.IGNORECASE):
            return Verdict(True, "user-phrase:" + pattern[:24])

    if not QUESTION_SHAPE.search(text):
        return Verdict(False, "no-question-shape")

    hits = []
    for pattern in TRIGGER_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            hits.append(m.group(0).strip())

    if not hits:
        return Verdict(False, "no-external-trigger")

    return Verdict(True, "external:" + ",".join(sorted(set(hits))[:4]))


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
