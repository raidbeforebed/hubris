"""The subject taxonomy: what counts as an external-facts question, and whose call it is.

The flat trigger list this replaced had one flaw no amount of tuning could fix: it encoded
*my* idea of what is worth researching, and every user's idea is different. A trader wants
prices; someone debugging a kernel wants nothing to do with them. So every trigger moved
here, as data, and the settings surface exposes a switch for each one.

The split that matters is this:

  CORE (classifier.py)   an explicit request to go and look: a search verb, a URL, "how do
                         I". These always fire, because the user literally asked.
  TOPICS (this file)     everything else, including recency words and comparisons. Nothing
                         fires unless a live subject matches, so turning a topic off really
                         does silence that domain instead of leaving a "latest" to fire
                         behind your back.

Ten topics, nineteen subjects. Recency and comparison are topics like any other ("Freshness",
"Choices") rather than hidden always-on rules, because a user who is tired of being nagged
about "the latest" should be able to switch it off without editing regex.

A subject's patterns are matched against the normalised lower-case message. Two rules hold
across every pattern here:

  - it must be an external-facts shape, never an everyday word that merely co-occurs with a
    question ("still", "now", "today" were the bugs that taught us this);
  - it belongs to exactly one subject, so switching a subject off has an effect a user can
    predict and a test can assert.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Subject:
    topic: str
    key: str
    label: str
    patterns: tuple[str, ...]

    @property
    def setting_key(self) -> str:
        """The config_schema key for this subject's switch: `subject_money_prices`."""
        return f"subject_{self.topic}_{self.key}"

    @property
    def full_key(self) -> str:
        """`money.prices` -- how a match is reported in the log and the footer."""
        return f"{self.topic}.{self.key}"


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    blurb: str
    subjects: tuple[Subject, ...]

    @property
    def setting_key(self) -> str:
        return f"topic_{self.key}"


def _subject(topic: str, key: str, label: str, *patterns: str) -> Subject:
    return Subject(topic=topic, key=key, label=label, patterns=tuple(patterns))


TOPICS: tuple[Topic, ...] = (
    Topic(
        key="freshness",
        label="Freshness",
        blurb="Wording that means the answer may have moved since the model learned it.",
        subjects=(
            _subject(
                "freshness", "recency", "Freshness: recency wording",
                r"\b(latest|newest|current|currently|up to date|up-to-date|as of|"
                r"this (?:year|month|week)|newly|anymore|new (?:release|version|model)|"
                r"still (?:supported|available|made|sold|maintained|in print))\b",
            ),
        ),
    ),
    Topic(
        key="choices",
        label="Comparisons and picks",
        blurb="Asking which one, which usually means someone has already compared them.",
        subjects=(
            _subject(
                "choices", "comparison", "Choices: comparisons and picks",
                r"\b(best\b(?!\s+(?:to|for)\b)|better than|worst|worth it|vs\.?|versus|"
                r"compare|comparison|recommend|alternative|pros and cons)\b",
            ),
        ),
    ),
    Topic(
        key="money",
        label="Money and markets",
        blurb="Prices, deals and rates, where last month's number is wrong this month.",
        subjects=(
            _subject(
                "money", "prices", "Money: prices and deals",
                r"\b(price|prices|pricing|cost|costs|how much|msrp|cheap(?:est)?|deal|deals|"
                r"discount|on sale|for sale|budget|quote)\b",
            ),
            _subject(
                "money", "rates", "Money: rates and crypto",
                r"\b(bitcoin|btc|ethereum|eth|crypto|stablecoin|gas fee|market cap|"
                r"interest rate|apr|apy|mortgage rate|yield|inflation|cpi)\b",
            ),
        ),
    ),
    Topic(
        key="software",
        label="Software and versions",
        blurb="Releases, deprecations and docs: the fastest-moving facts an agent can be wrong about.",
        subjects=(
            _subject(
                "software", "releases", "Software: releases and versions",
                r"\b(version|versions|changelog|roadmap|deprecat\w*|end of life|eol|retired|"
                r"sunset|breaking change|release date|supported|compatible)\b",
            ),
            _subject(
                "software", "docs", "Software: documentation",
                r"\b(docs|documentation|api reference|sdk|reference manual|man page)\b",
            ),
        ),
    ),
    Topic(
        key="hardware",
        label="Hardware and gear",
        blurb="Specs, benchmarks and whether the thing is actually in stock.",
        subjects=(
            _subject(
                "hardware", "specs", "Hardware: specs and reviews",
                r"\b(specs?|specifications?|benchmark|benchmarks|review|reviews|rating|"
                r"spec sheet|thermals?|wattage)\b",
            ),
            _subject(
                "hardware", "stock", "Hardware: availability",
                r"\b(in stock|availab\w*|backorder|back order|sold out|shipping date|"
                r"compatibility|works with)\b",
            ),
        ),
    ),
    Topic(
        key="law",
        label="Law, policy and benefits",
        blurb="Rules, deadlines and entitlements, all of which move on someone else's schedule.",
        subjects=(
            _subject(
                "law", "statutes", "Law: rules and legality",
                r"\b((?<!in )law|laws|legal|illegal|lawful|regulation|regulations|statute|"
                r"ordinance|permit|license required)\b",
            ),
            _subject(
                "law", "deadlines", "Law: deadlines and entitlements",
                r"\b(deadline|due date|filing|tax|taxes|open enrollment|cutoff|"
                r"va (?:claim|rating|disability)|fehb|fedvip|medicare|medicaid|"
                r"social security|cola)\b",
            ),
        ),
    ),
    Topic(
        key="health",
        label="Health and medicine",
        blurb="Guidance and alerts, where a stale answer is the expensive kind of wrong.",
        subjects=(
            _subject(
                "health", "guidance", "Health: guidance",
                r"\b(dosage|dose|side effects?|treatment|guidelines?|symptoms?|"
                r"diagnos\w*|medication)\b",
            ),
            _subject(
                "health", "alerts", "Health: recalls and outbreaks",
                r"\b(outbreak|fda|recall|cdc|epidemic|pandemic)\b",
            ),
        ),
    ),
    Topic(
        key="local",
        label="Local and logistics",
        blurb="Weather, hours and roads: true only near you, and only right now.",
        subjects=(
            _subject(
                "local", "weather", "Local: weather",
                r"\b(weather|forecast|hurricane|storm|tornado|rain chance)\b",
            ),
            _subject(
                "local", "places", "Local: places and roads",
                r"\b(opening hours|store hours|still open|traffic|road closure|"
                r"construction|detour)\b",
            ),
        ),
    ),
    Topic(
        key="games",
        label="Games and modpacks",
        blurb="The case that started this: a modpack's progression changes every release.",
        subjects=(
            _subject(
                "games", "versions", "Games: packs and versions",
                r"\b(modpack|mods?|modded|minecraft|atm ?10|atm star|ender dragon|"
                r"pack version)\b",
            ),
            _subject(
                "games", "guides", "Games: guides and progression",
                r"\b(guide|guides|progression|walkthrough|tutorial|checklist|"
                r"where to start|getting started|what order)\b",
            ),
            _subject(
                "games", "recipes", "Games and food: recipes, crafting and wikis",
                r"\b(recipe|recipes|crafting|quest ?book|wiki)\b",
            ),
        ),
    ),
    Topic(
        key="news",
        label="News and current events",
        blurb="Elections, conflicts and headlines, where the answer changes by the hour.",
        subjects=(
            _subject(
                "news", "politics", "News: headlines, elections and officials",
                r"\b(news|headlines?|election|elections|ballot|vote|voting|mayor|governor|"
                r"senator|congress|bill passed|primary)\b",
            ),
            _subject(
                "news", "world", "News: world events",
                r"\b(war|conflict|sanctions|treaty|summit|ceasefire|protest)\b",
            ),
        ),
    ),
)


def topic_map() -> dict[str, Topic]:
    return {topic.key: topic for topic in TOPICS}


def subject_map() -> dict[str, Subject]:
    """Every subject keyed by `topic.subject`, which is how reasons are reported."""
    return {s.full_key: s for t in TOPICS for s in t.subjects}


def all_subject_keys() -> set[str]:
    return {s.full_key for t in TOPICS for s in t.subjects}


def setting_keys() -> list[str]:
    """The config_schema keys this taxonomy owns, topics first then their subjects."""
    keys: list[str] = []
    for topic in TOPICS:
        keys.append(topic.setting_key)
        keys.extend(s.setting_key for s in topic.subjects)
    return keys


def enabled_subjects(topic_flags: dict[str, bool], subject_flags: dict[str, bool]) -> set[str]:
    """Resolve the two switch layers into the set of live `topic.subject` keys.

    A subject is live when its own switch is on AND its topic's switch is on, so turning a
    topic off is a single, obvious action that overrides every subject inside it rather than
    a set of nineteen.
    """
    live: set[str] = set()
    for topic in TOPICS:
        if not topic_flags.get(topic.key, True):
            continue
        for subject in topic.subjects:
            if subject_flags.get(subject.full_key, True):
                live.add(subject.full_key)
    return live
