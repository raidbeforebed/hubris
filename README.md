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
| `nag_on_explicit` | switch | off | Warn even on a turn you explicitly asked to be researched. |
| `disabled_subjects` | text | empty | Mute one subject (`money.prices`) or a whole topic (`money`), comma separated. |
| `exempt_patterns` | text | empty | Never research these, comma separated or one per line. Wins over everything. |
| `extra_trigger_phrases` | text | empty | Always research these, for a domain the taxonomy does not cover. |
| `quiet_platforms` | text | empty | Platforms that get neither directive nor footer, comma separated. |

Sixteen rows: ten topic switches and six controls. Nineteen subject switches were tried and
removed — the taxonomy is the classifier's structure, not a configuration surface, and nobody
turns off `money.prices` while leaving `money` on. Per-subject control survives as one text field,
and **the footer teaches the syntax**: a warning naming `money.prices` is telling you exactly what
to type.

```bash
hermes config set plugins.entries.hubris.settings.topic_games false
hermes config set plugins.entries.hubris.settings.disabled_subjects "money.prices, hardware.stock"
```

Unknown ids in `disabled_subjects` are logged and ignored rather than failing a hook, so a typo
costs a warning, not a broken turn.

The two phrase fields are the escape hatch: a domain the taxonomy does not cover, and a word the
built-in rules misread. Both accept comma-separated text, one phrase per line, a JSON array, or a
real YAML list, so a setting written by hand is never silently dropped.

### Directive and nag are separate

A turn that fires because *you asked* ("look this up") gets the search directive but no footer: you
already said what you wanted, and a warning about a promise the plugin kept is just nagging. Set
`nag_on_explicit` if you want it anyway. A turn that fires because the *taxonomy* matched gets the
footer, because nobody asked.

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

## Measuring it

The numbers below are reproducible, not asserted. `corpus/cases.jsonl` holds 57 labelled turns
and `eval.py` scores the classifier against them:

```bash
python3 eval.py                      # summary, every miss, per-subject tally
python3 eval.py --show               # every case, pass or fail
python3 eval.py --min-precision 1.0  # exit 1 below the floor, for CI
```

The corpus is **paraphrased, not collected**. Each case reproduces the *shape* of a failure that
actually happened — a pasted traceback, a mechanical explainer, a statement that mentions an
election — without shipping anyone's messages. Cases marked `known_miss` are counted and reported
but do not fail the run.

Current: **precision 1.000, recall 1.000** over 57 cases.

On 225 replayed real messages from a live install (not my corpus): **17 fired, 7.6%**, and I judge
all 17 to be genuine research turns. Before these fixes it was 20 fired with 3 wrong: a local TTS
error matching "available", a mechanic's explainer matching "cost", and a statement about a past
election matching "vote".

Those three were fixed at their actual sites, not with a bigger word list:

| Failure | Cause | Fix |
|---|---|---|
| TTS error | the classifier read pasted logs as prose | **scrub** fenced blocks, inline code and log lines before matching. Costs nothing in recall |
| gas explainer | "explain ... cost ..." is not a request | **clause-scoped gate**: some clause must be a question or an ask. "explain" is not one |
| mayor statement | "which" counted as a question word | **`which` is a determiner**, not an opener, unless it starts a real question ("which modpack version") |

A wrong fire is invisible to a benchmark and expensive in real life, so precision is the number I
optimise for. Recall is held by the escapes the gate allows: a "?" anywhere, a question word
opening a clause, a question embedded mid-sentence ("... who won the mayor race"), a statement of
need ("I just need a checklist"), or any explicit "go and look".

### The test that changed the design

A corpus you wrote yourself can only confirm what you already believe. So the second test uses
real messages the author actually typed, filtered to the 77 where he **explicitly asked for a
search** — "did you check online whether other users hit this?", "research how X works", "web
search: Y". Those are ground truth positives that no paraphrase can argue with.

The first run caught **41.6%**. Fifty-five percent of the times a user said "go and look", the
plugin stayed quiet — because the local-domain skip list ran *before* the request check, and words
like `hermes`, `repo`, `gpu`, `school` and even an IP address in an OAuth question swallowed the
request whole. Twenty-one of the 45 misses died on the word "hermes" alone.

The fix was ordering, not vocabulary:

```
bare acknowledgement -> quiet
user phrase lists    -> win
complaint            -> quiet      ("you never search online" is not a request to search)
explicit request     -> FIRE       (outranks the skip list)
local/personal       -> quiet
question shape       -> gate
taxonomy             -> fire or quiet
```

That took explicit-directive recall from **41.6% to 94.8%**, with general traffic unchanged at 8%
and no new false positives on 226 messages. The four remaining misses are complaints and
statements that mention searching, which is the correct answer.

The lesson is in the code as a comment, because it is the kind of thing a later refactor undoes in
one line: *an explicit request outranks everything except a bare acknowledgement and the user's own
never-list.*

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

84 checks, no pytest, no network: the plugin is deterministic, so the test is a table. It covers the
classification table (including every phrase that used to misfire), the taxonomy switches
(topic-off, subject-off, everything-off, and the manifest never drifting from the code), which tools
count as research, directive and footer behaviour, per-session ledger isolation, the settings form
path, quiet platforms, and both user phrase fields.

## History

Named `source-first` up to 1.1.0, renamed **HUBRIS** in 1.2.0. In 1.2.1 the list settings became
plain comma-separated text, because a JSON editor is a miserable way to type one platform name and
an empty JSON box reads as a broken form. In 1.4.0 the flat trigger list became the topic and
subject taxonomy. In 1.6.0 an explicit request was made to outrank the local-domain skip list, after
replaying 77 real messages in which the author asked for a search showed recall at 41.6%. In 1.7.0
the nineteen subject switches became one `disabled_subjects` field: sixteen settings rows, and the
footer names the id to type.

## License

MIT. See `LICENSE`.
