# HUBRIS

**H**euristic **U**nverified-**B**elief **R**esearch **I**njection **S**ignal

A Hermes Agent plugin that makes live web research the default before a factual answer, and marks
the reply when it does not happen.

## The problem

A model is confident about things that stopped being true. Everything it learned was true when it
learned it, and none of it carries a date. Prices move, versions ship, laws change, modpacks update.
Past the training cutoff that knowledge is undated at best and overtaken by events at worst. The
answer arrives in the same voice either way, which is why a stale fact reads like a current one.

People call that hubris: confidence outrunning its evidence.

A line in a profile does not fix it. An instruction loses to whatever habit is closest at hand. A
hook does not negotiate.

## What it does

| Hook | Behaviour |
|---|---|
| `pre_llm_call` | Classifies the turn. When the question turns on current facts, it tells the model to search first, label anything from a fallback, and cite the URLs it read. |
| `post_tool_call` | Records whether a live web tool actually fired, per session. |
| `transform_llm_output` | When the turn needed research and no search ran, appends a footer naming the subject that fired. |

Deterministic. Standard library only. **No LLM calls and no network of its own**, so it cannot slow
a turn or spend tokens.

The footer names its own cause, which is what makes the plugin teachable:

> **hubris:** this turn turned on `money.prices, freshness.recency` and no live web search ran. Treat
> the answer above as potentially OBE (overtaken by events): undated background knowledge, not
> verified current fact.

If that warning is wrong, it has just told you which switch to reach for.

## The taxonomy

The first version held one flat regex list. That was the design flaw, because it encoded one
author's idea of what deserves research. A trader wants prices. Someone debugging a kernel does not.

The vocabulary is data now, and you own it. Eleven topics, twenty-two subjects:

| Topic | Subjects |
|---|---|
| **AI, models and harnesses** | models and versions, coding harnesses, agents and protocols |
| **Freshness** | recency wording |
| **Comparisons and picks** | comparisons and picks |
| **Money and markets** | prices and deals, rates and crypto |
| **Software and versions** | releases and versions, documentation |
| **Hardware and gear** | specs and reviews, availability |
| **Law, policy and benefits** | rules and legality, deadlines and entitlements |
| **Health and medicine** | guidance, recalls and outbreaks |
| **Local and logistics** | weather, places and roads |
| **Games and modpacks** | packs and versions, guides and progression, recipes and wikis |
| **News and current events** | headlines and officials, world events |

Two rules make the switches mean what they say.

1. **A subject fires only when its topic is on.** One topic switch silences everything inside it.
2. **A disabled topic goes quiet.** Nothing outside the taxonomy fires on vocabulary. "latest" and
   "best" are subjects too, so turning Money off is not quietly overridden by the word "current".

One thing outranks every switch: an explicit request. A search verb, a pasted URL, or "how do I"
always goes and looks, because you asked.

## Settings

The manifest declares a `config_schema`, so the Desktop app renders the whole thing as a form at
Settings, Plugins, hubris. Every default is a visible control, and every control is editable.
Values live at `plugins.entries.hubris.settings.*` in `config.yaml`:

```bash
hermes config set plugins.entries.hubris.settings.topic_games false
hermes config set plugins.entries.hubris.settings.disabled_subjects "money.prices, hardware.stock"
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | switch | on | Off without uninstalling. |
| `topic_<name>` | switch | on | One per topic. Off silences every subject inside it. |
| `nag_on_explicit` | switch | off | Warn even on a turn you asked to be researched. |
| `disabled_subjects` | text | empty | Mute one subject (`money.prices`) or a whole topic, comma separated. |
| `exempt_patterns` | text | empty | Never research these, comma separated or one per line. Wins over everything. |
| `extra_trigger_phrases` | text | empty | Always research these, for a domain the topics miss. |
| `quiet_platforms` | text | empty | Platforms that get no search request and no warning, comma separated. |

Seventeen rows: eleven topic switches and six controls.

Nineteen subject switches existed in an earlier version and came out. The taxonomy is the
classifier's structure, not a configuration surface, and nobody turns off `money.prices` while
leaving `money` on. Per-subject control survives as one text field, and the footer teaches the
syntax: a warning naming `money.prices` is telling you what to type.

Unknown ids in `disabled_subjects` get logged and ignored, so a typo costs a warning and not a
broken turn. The text fields show an example in grey until you type.

The two phrase fields are the escape hatch: a domain the topics miss, and a word the rules misread.
Both accept comma-separated text, one phrase per line, a JSON array, or a YAML list.

### The warning and the search request are separate

A turn that fires because you asked ("look this up") gets the search request and no warning, since
you already said what you wanted. A turn that fires because the taxonomy matched gets both. Set
`nag_on_explicit` if you want the warning anyway.

## Install

```bash
git clone https://github.com/raidbeforebed/hubris ~/.hermes/plugins/hubris
hermes plugins validate ~/.hermes/plugins/hubris   # manifest, load, hooks, scan
hermes plugins doctor hubris                       # must report 3 hooks registered
hermes plugins enable hubris                       # hot-reloads hooks into the gateway
```

Once the catalog lists it, the short form is `hermes plugins install hubris --enable`.

Check it end to end rather than assuming:

```
Which All the Mods 10 modpack version is current right now?
```

The answer should cite pages it actually read. If it does not, the reply carries the footer.

## Why a footer and not a block

Blocking the reply turns a misclassification into a stuck turn, and this classifier is a heuristic.
The footer is unmissable to the person reading the reply, costs nothing when the guess is right, and
cannot loop.

The search request changes behaviour. The footer is the tripwire that says whether it worked, and
which switch to reach for when the tripwire was wrong.

## Measuring it

The numbers are reproducible. `corpus/cases.jsonl` holds 71 labelled turns and `eval.py` scores the
classifier against them:

```bash
python3 eval.py                      # summary, every miss, per-subject tally
python3 eval.py --show               # every case, pass or fail
python3 eval.py --min-precision 1.0  # exit 1 below the floor, for CI
```

The corpus is paraphrased, not collected. Each case reproduces the shape of a failure that actually
happened, such as a pasted traceback or a statement that mentions an election, without shipping
anyone's messages. Cases marked `known_miss` are counted and reported but do not fail the run.

Current: **precision 1.000, recall 1.000** over 71 cases.

Three false positives were fixed at their own site rather than with a longer word list:

| Failure | Cause | Fix |
|---|---|---|
| a pasted service error matched "available" | the classifier read logs as prose | scrub fenced blocks, inline code and log lines before matching. No recall cost |
| a mechanic's explainer matched "cost" | "explain X cost" is not a request | a clause-scoped gate: some clause must be a question or an ask |
| a statement about a past election matched "vote" | "which" counted as a question word | `which` opens a question only when it is not a determiner |

### The test that changed the design

A corpus you write yourself confirms what you already believe. The second test uses real messages
the author typed, filtered to the 77 where he explicitly asked for a search: "did you check online
whether other users hit this?", "research how X works", "web search: Y". Those are ground-truth
positives that no paraphrase can argue with.

The first run caught **41.6%**. More than half the times a user said "go and look", the plugin
stayed quiet, because the local-domain skip list ran before the request check. Words like `hermes`,
`repo`, `gpu`, `school`, and an IP address inside an OAuth question swallowed the request whole.
Twenty-one of the 45 misses died on the word "hermes" alone.

The fix was ordering, not vocabulary:

```
bare acknowledgement -> quiet
your phrase lists    -> win
complaint            -> quiet      ("you never search online" is not a request to search)
explicit request     -> FIRE       (outranks the skip list)
local or personal    -> quiet
question shape       -> gate
taxonomy             -> fire or quiet
```

Explicit-directive recall went from **41.6% to 94.8%**. General traffic stayed at 8% with no new
false positives across 226 messages. The four remaining misses are complaints and statements that
mention searching, which is the right answer.

That order carries a comment in the code, because a later refactor can undo a 53-point recall gain
in one line.

## Compatibility

- Uses only public hooks. Patches nothing in core, reads no core module, registers no tools.
- **Works on stock Hermes.** Everything above is plugin code: the classification, the hooks, the
  taxonomy, all seventeen settings rows. Verified against an unpatched checkout, where the suite
  passes 84 checks and the corpus scores 1.000 / 1.000, and `hermes plugins validate` reports
  "config schema: shape valid".
- `placeholder` in the manifest is optional polish. A backend that passes it through shows an
  example in grey while a field is empty; one that does not ignores the key and renders an empty
  field. Nothing else changes, and no setting depends on it.
- `pre_llm_call` is the seam `research-guard` also uses. Do not run both; they inject competing
  instructions.
- `transform_llm_output` takes the first non-empty string any plugin returns, so do not run two
  plugins that rewrite replies. If you also use a citation checker, run one of them.
- Local search is not web research. `search_files` and `session_search` deliberately do not satisfy
  the check, or the footer would go quiet on turns that never left the machine.

## Prior art

- [`Cesarus85/hermes-research-guard`](https://github.com/Cesarus85/hermes-research-guard): a
  `pre_llm_call` injector with a rich trigger taxonomy, gated to local and small models.
- [`citation-guard`](https://github.com/ChienNguyen23/hermes-citation-guard): verifies whether the
  references in a reply are real. Same seam, different job.
- [`search-sources`](https://github.com/ShowUNow/hermes-search-sources): shows the pages a turn did
  search. This plugin complains when the turn searched nothing.

## Tests

```bash
python3 test_hubris.py     # exits 1 on failure
python3 eval.py            # precision and recall over the corpus
```

84 unit checks, no pytest and no network, because the plugin is deterministic and the test is a
table. It covers the classification table, the taxonomy switches, manifest drift, which tools count
as research, the directive and footer rules, per-session ledger isolation, the settings path, quiet
platforms, and both phrase fields.

## History

Named `source-first` up to 1.1.0, renamed **HUBRIS** in 1.2.0. In 1.2.1 the list settings became
comma-separated text, because a JSON editor is a poor way to type one platform name and an empty
JSON box reads as a broken form. In 1.4.0 the flat trigger list became the taxonomy. In 1.6.0 an
explicit request was made to outrank the skip list, after the 77-message replay. In 1.7.0 nineteen
subject switches became one `disabled_subjects` field. In 1.8.0 the taxonomy gained the AI topic,
the text fields gained examples, and the form fields got a visible edge in dark mode.

## License

MIT. See `LICENSE`.
