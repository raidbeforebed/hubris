# HUBRIS

**H**euristic **U**nverified-**B**elief **R**esearch **I**njection **S**ignal

A Hermes Agent plugin that makes **live web research the default before a factual answer**, and
makes the failure visible when it does not happen.

> It knows what it knew.

## The problem the name is pointing at

A model is not usually wrong about the world. It is wrong about *when* it is right. Everything it
learned was true when it was learned, and none of it carries a date. Past the training cutoff that
knowledge is at best **undated** and at worst **OBE — overtaken by events**: the price moved, the
version shipped, the law changed, the pack updated. The answer still arrives in the same confident
voice, which is why it reads exactly like a current fact.

That is hubris in the original sense: not ignorance, but confidence outrunning its evidence.

An instruction in a profile does not fix it, because an instruction loses to whatever skill or habit
is closest at hand. A hook does, because a hook does not negotiate.

## What it does

| Hook | Behaviour |
|---|---|
| `pre_llm_call` | Classifies the turn. When it turns on current external facts, injects a directive: search first, label anything from a fallback, cite the URLs read. |
| `post_tool_call` | Records whether a live web tool actually fired, per session. |
| `transform_llm_output` | If the turn needed research and none ran, appends a footer naming the subject that fired and marking the answer as potentially OBE. |

Deterministic. Standard library only. **No LLM calls, no network of its own**, so it cannot slow a
turn or spend tokens.

The footer names its own cause, which is the part that makes the plugin teachable:

> **hubris:** this turn turned on `money.prices, freshness.recency` and no live web search ran. Treat
> the answer above as potentially OBE (overtaken by events): undated background knowledge, not
> verified current fact.

If that footer is wrong for you, you now know exactly which switch to turn off.

## The taxonomy: you own the judgement

The first version of this plugin had one flat regex list, and that was the design flaw: it encoded
*my* idea of what deserves research, and every user's idea is different. A trader wants prices;
someone debugging a kernel wants nothing to do with them.

So the vocabulary is data now, and every part of it is a switch in the settings form:

| Topic | Subjects |
|---|---|
| **Freshness** | recency wording ("latest", "up to date", "still supported") |
| **Comparisons and picks** | comparisons ("best", "vs", "worth it", "recommend") |
| **Money and markets** | prices and deals; rates and crypto |
| **Software and versions** | releases and versions; documentation |
| **Hardware and gear** | specs and reviews; availability |
| **Law, policy and benefits** | rules and legality; deadlines and entitlements |
| **Health and medicine** | guidance; recalls and outbreaks |
| **Local and logistics** | weather; places and roads |
| **Games and modpacks** | packs and versions; guides and progression; recipes and wikis |
| **News and current events** | headlines, elections and officials; world events |

Ten topics, nineteen subjects, and two rules that make the switches mean what they say:

1. **A subject fires only when its own switch and its topic's switch are both on**, so a topic switch
   is a one-click "all of this".
2. **A disabled topic really is silent.** Nothing outside the taxonomy fires on domain vocabulary —
   "latest" and "best" are subjects too, not hidden always-on rules — so switching off Money is not
   quietly overridden by the word "current".

The one thing a switch cannot silence is an explicit request: a search verb, a pasted URL, or
"how do I". If you say *"go and look this up"*, it looks, whatever the switches say.

## Settings

The manifest declares a `config_schema`, so the **Desktop app renders the whole thing as a form**
at Settings, Plugins, hubris. Every default is visible as a switch position, and every one is
editable. Values are written to `plugins.entries.hubris.settings.*` in `config.yaml`, so the same
settings are reachable from a terminal:

```bash
hermes config set plugins.entries.hubris.settings.topic_games false
hermes config set plugins.entries.hubris.settings.subject_money_prices false
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | switch | on | Off without uninstalling. |
| `topic_<name>` | switch | on | One per topic. Off silences every subject inside it. |
| `subject_<topic>_<name>` | switch | on | One per subject. Off silences just that one. |
| `extra_trigger_phrases` | text | empty | Always research these, comma separated. Bypasses the taxonomy and the question-shape test. |
| `extra_skip_phrases` | text | empty | Never research these, comma separated. Wins over everything. |
| `quiet_platforms` | text | empty | Platforms that get neither directive nor footer, comma separated. |

The two phrase fields are the escape hatch: a domain the taxonomy does not cover, and a word the
built-in rules misread. Both accept comma-separated text, one phrase per line, a JSON array, or a
real YAML list, so a setting written by hand is never silently dropped.

## Install

```bash
git clone https://github.com/raidbeforebed/hubris ~/.hermes/plugins/hubris
hermes plugins validate ~/.hermes/plugins/hubris   # manifest, load, hooks, scan
hermes plugins doctor hubris                       # must report 3 hooks registered
hermes plugins enable hubris                       # hot-reloads hooks into the gateway
```

Once it is listed in the catalog, the short form is `hermes plugins install hubris --enable`.

Verify it end to end, do not assume:

```
Which All the Mods 10 modpack version is current right now?
```

The answer should cite URLs it actually read. If it does not, the reply carries the footer.

## Why a footer, and not a block

A block on the final answer is the obvious design and the wrong one: it turns a classification
mistake into a stuck turn, and the classifier is a heuristic. The footer is unmissable to the person
reading the reply, costs nothing when the classifier is right, and cannot loop.

The directive is what changes behaviour; the footer is the tripwire that tells you the directive
was ignored, and which switch to reach for if the tripwire was wrong.

## Measured

Replayed over 225 unique user messages from a live install's session database: **20 turns fired
(8.9%)**. Hand-adjudicated, 17 were genuinely research turns and 3 were not: a local TTS error
matching "available", a mechanical explainer matching "cost", and a statement about a past election
matching "election".

Under the earlier flat-list design, the same 3 misses were unfixable without editing source. They
are now three switches, and the footer says which one.

This is not a benchmark. It is the evidence that the trigger list is precise enough to leave on, and
the shape of the remaining error.

## Compatibility

- Uses only public hooks. Patches nothing in core, reads no core module, registers no tools.
- `pre_llm_call` is the same seam `research-guard` uses: do not run both, they inject competing
  directives.
- `transform_llm_output` takes the **first non-empty string** any plugin returns, so do not run two
  plugins that both rewrite replies. If you also use a citation checker, prefer a version that
  appends through this plugin, or run only one of them.
- Local search is not web research: `search_files` and `session_search` deliberately do not satisfy
  the check, or the footer would go quiet on turns that never left the machine.

## Prior art

- [`Cesarus85/hermes-research-guard`](https://github.com/Cesarus85/hermes-research-guard): a
  `pre_llm_call` research injector with a rich trigger taxonomy, gated to local and small models.
- [`citation-guard`](https://github.com/ChienNguyen23/hermes-citation-guard) in the Hermes catalog:
  a reply guard that verifies fabricated references. Adjacent seam, different job.
- [`search-sources`](https://github.com/ShowUNow/hermes-search-sources) in the Hermes catalog: shows
  the pages a turn *did* search. This plugin is the complement: it complains when the turn searched
  nothing.

## Tests

```bash
python3 test_hubris.py     # exits 1 on failure
```

76 checks, no pytest, no network: the plugin is deterministic, so the test is a table. It covers the
classification table (including every phrase that used to misfire), the taxonomy switches
(topic-off, subject-off, everything-off, and the manifest never drifting from the code), which tools
count as research, directive and footer behaviour, per-session ledger isolation, the settings form
path, quiet platforms, and both user phrase fields.

## History

Named `source-first` up to 1.1.0, renamed **HUBRIS** in 1.2.0. In 1.2.1 the list settings became
plain comma-separated text, because a JSON editor is a miserable way to type one platform name and
an empty JSON box reads as a broken form. In 1.4.0 the flat trigger list became the topic and
subject taxonomy, so what counts as current external facts is a decision the user makes with
switches rather than one the code makes for them.

## License

MIT. See `LICENSE`.
