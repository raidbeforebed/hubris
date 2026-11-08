# source-first

A Hermes Agent plugin that makes **live web research the default before a factual answer**, and
makes the failure visible when it does not happen.

Written because an instruction in a profile loses to whatever skill or habit is closest at hand.
An agent with a large context and a confident voice will answer "what is the best X right now"
from its training data or a local archive, and be wrong in a way that reads exactly like being
right. Making that a preference did not fix it. A hook does, because a hook does not negotiate.

## What it does

| Hook | Behaviour |
|---|---|
| `pre_llm_call` | Classifies the turn. When it turns on current external facts, injects a directive: search first, label anything from a fallback, cite the URLs read. |
| `post_tool_call` | Records whether a live web tool actually fired, per session. |
| `transform_llm_output` | If the turn needed research and none ran, appends a visible footer: *no live web search ran, treat this as background knowledge*. |

Deterministic. Standard library only. **No LLM calls, no network of its own**, so it cannot slow
a turn or spend tokens.

## Why a footer, and not a block

A block on the final answer is the obvious design and the wrong one: it turns a classification
mistake into a stuck turn, and the classifier is a heuristic. The footer is unmissable to the
person reading the reply, costs nothing when the classifier is right, and cannot loop.

The directive is what changes behaviour; the footer is the tripwire that tells you the directive
was ignored.

## Install

From the catalog, once listed:

```bash
hermes plugins install source-first --enable
```

From this repository:

```bash
git clone https://github.com/raidbeforebed/source-first ~/.hermes/plugins/source-first
hermes plugins validate ~/.hermes/plugins/source-first   # manifest, load, hooks, scan
hermes plugins doctor source-first                       # must report 3 hooks registered
hermes plugins enable source-first                       # hot-reloads hooks into the gateway
```

Verify it end to end, do not assume:

```
Which All the Mods 10 modpack version is current right now?
```

The answer should cite URLs it actually read. If it does not, the reply carries the footer.

## Settings

The manifest declares a `config_schema`, so the **Desktop app renders a form automatically** at
Settings, Plugins, source-first (and the gear on its row in Capabilities, Plugins). No Desktop
code is involved. Values are written to `plugins.entries.source-first.settings.*` in
`config.yaml`, so the same settings are reachable from a terminal:

```bash
hermes config set plugins.entries.source-first.settings.enabled false
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `true` | Turn the behaviour off without disabling or removing the plugin. |
| `quiet_platforms` | list | `[]` | Platform names (`discord_voice`, `telegram`) that get neither the directive nor the footer. |
| `extra_trigger_phrases` | list | `[]` | Phrases that mean "check the live web", on top of the built-in rules. |
| `extra_skip_phrases` | list | `[]` | Phrases that must never trigger research. These win over every trigger. |

`list` fields render as a JSON editor, so extending the plugin for your own domain needs no code
change:

```json
["kubernetes", "homelab price", "my thesis"]
```

Extra trigger phrases bypass the built-in question-shape test, because a phrase you taught the
plugin is an explicit opt-in. Extra skip phrases are checked before everything else, so they are
the safe override for a word the built-in rules misread. Matching is case-insensitive plain text,
so there is nothing to escape.

## Classification

Two explicit lists in `classifier.py`: `SKIP_PATTERNS` never research (this installation and its
hosts, IPs, paths, services; personal and family context; coding and repo work; memory and meta
questions about the assistant; bare acknowledgements; standing instructions about how to answer
*later*). `TRIGGER_PATTERNS` do: recency in a phrase that means the world moved, price, version,
availability, comparison and recommendation, an explicit "go and find out", how-to, a pasted URL,
and domains where a stale answer is expensive (news, law, docs, modpacks).

Every trigger is an *external-facts* shape rather than an everyday word. An earlier version fired
on bare "now", "still", "today" and "which is", which put the footer on "are you still working"
and on local device control; those words now only count inside phrases like "still supported" or
"current version". A bare "ok" is skipped, but a substantive turn that merely starts with "ok" is
not.

Asymmetric on purpose: a false positive costs one nudge and at worst one footer, while a false
negative is the failure this plugin exists to prevent.

### Measured

Replayed over 225 unique user messages from a live install's session database: **17 turns fired
(7.6%)**. Hand-adjudicated, 15 of those 17 were genuinely research turns and 2 were not (a local
TTS error report, and a mechanical explainer that matched on "costs"). A false positive is one
line of nudge and, only if the turn ends without a search, one footer.

This is not a benchmark. It is the evidence that the trigger list is precise enough to leave on,
and the shape of the remaining error. Re-run it on your own traffic before trusting the numbers:
the point of the two phrase lists is that you can fix a wrong call without editing this file.

## Compatibility

- Uses only public hooks. Patches nothing in core, reads no core module, registers no tools.
- `pre_llm_call` is the same seam `research-guard` uses: do not run both, they inject competing
  directives.
- `transform_llm_output` takes the **first non-empty string** any plugin returns, so do not run
  two plugins that both rewrite replies. If you also use a citation checker, prefer a version
  that appends through this plugin, or run only one of them.
- Local search is not web research: `search_files` and `session_search` deliberately do not
  satisfy the check, or the footer would go quiet on turns that never left the machine.

## Prior art

Read these before forking:

- [`Cesarus85/hermes-research-guard`](https://github.com/Cesarus85/hermes-research-guard): a
  `pre_llm_call` research injector with a much richer trigger taxonomy, gated to local and small
  models.
- [`citation-guard`](https://github.com/ChienNguyen23/hermes-citation-guard) in the Hermes catalog:
  a reply guard that verifies fabricated references. Adjacent seam, different job.
- [`search-sources`](https://github.com/ShowUNow/hermes-search-sources) in the Hermes catalog:
  shows the pages a turn *did* search. This plugin is the complement: it complains when the turn
  searched nothing.

## Tests

```bash
python3 test_source_first.py     # exits 1 on failure
```

60 checks, no pytest, no network: the plugin is deterministic, so the test is a table. It covers
the classification table (including every phrase that used to misfire), which tools count as
research, directive and footer behaviour, per-session ledger isolation, the settings form path,
quiet platforms, and both user phrase lists.

## License

MIT. See `LICENSE`.
