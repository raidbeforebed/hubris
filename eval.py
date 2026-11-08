#!/usr/bin/env python3
"""Score the classifier against a labelled corpus.

    python3 eval.py                 # summary + every miss
    python3 eval.py --show          # every case, pass or fail
    python3 eval.py --min-precision 0.95 --min-recall 0.80   # exit 1 below the floor

The corpus in `corpus/cases.jsonl` is paraphrased, not collected: it reproduces the *shapes*
of real failures (a pasted traceback, a mechanical explainer, a statement that mentions an
election) without shipping anyone's messages. Each case is

    {"id": str, "text": str, "expect": bool, "subjects": [str], "note": str}

`subjects` is checked only when `expect` is true, and `"core"` means "an explicit request
fired, no taxonomy subject required". A case marked `"known_miss": true` is counted and
reported but does not fail the run: a heuristic without a documented list of known misses is
a heuristic pretending to be a spec.

The headline numbers are precision and recall over the fire / do-not-fire decision, because
that is what the user experiences: a wrong fire is a footer on a good answer, a wrong miss is
the silent failure the plugin exists to prevent.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "hubris", HERE / "__init__.py", submodule_search_locations=[str(HERE)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["hubris"] = module
    spec.loader.exec_module(module)
    return module


hubris = _load()
classify = hubris.classify
taxonomy = sys.modules["hubris.taxonomy"]


def load_cases(path: Path) -> list[dict]:
    cases = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(HERE / "corpus" / "cases.jsonl"))
    parser.add_argument("--show", action="store_true", help="print every case, not just misses")
    parser.add_argument("--min-precision", type=float, default=None)
    parser.add_argument("--min-recall", type=float, default=None)
    args = parser.parse_args()

    cases = load_cases(Path(args.corpus))
    live = taxonomy.all_subject_keys()

    rows = []
    for case in cases:
        verdict = classify(case["text"], live_subjects=live)
        expected = bool(case["expect"])
        ok = verdict.research == expected
        missing_subject = []
        if ok and expected and case.get("subjects") and "core" not in case["subjects"]:
            missing_subject = [s for s in case["subjects"] if s not in verdict.subjects]
            ok = not missing_subject
        rows.append({"case": case, "verdict": verdict, "ok": ok, "expected": expected,
                     "missing_subject": missing_subject})

    scored = [r for r in rows if not r["case"].get("known_miss")]
    known = [r for r in rows if r["case"].get("known_miss")]

    tp = [r for r in scored if r["expected"] and r["verdict"].research]
    fp = [r for r in scored if not r["expected"] and r["verdict"].research]
    fn = [r for r in scored if r["expected"] and not r["verdict"].research]
    tn = [r for r in scored if not r["expected"] and not r["verdict"].research]
    bad_subject = [r for r in scored if r["expected"] and r["verdict"].research and r["missing_subject"]]

    precision = len(tp) / (len(tp) + len(fp)) if (tp or fp) else 1.0
    recall = len(tp) / (len(tp) + len(fn)) if (tp or fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(f"corpus {len(cases)} cases  ({len(scored)} scored, {len(known)} known-miss)")
    print(f"  fire {len(tp) + len(fp):3d}   correct {len(tp):3d}   wrong {len(fp):3d}")
    print(f"  quiet {len(tn) + len(fn):3d}  correct {len(tn):3d}   wrong {len(fn):3d}")
    print(f"  precision {precision:.3f}   recall {recall:.3f}   f1 {f1:.3f}")

    def show(title, items, render):
        if not items:
            return
        print(f"\n{title}")
        for row in items:
            print("  " + render(row))

    show("FALSE POSITIVES - a footer on an answer that needed no research", fp,
         lambda r: f"{r['case']['id']}: {r['verdict'].reason}  <- {r['case']['note']}")
    show("FALSE NEGATIVES - research that never got asked for", fn,
         lambda r: f"{r['case']['id']}: {r['verdict'].reason}  <- {r['case']['note']}")
    show("WRONG SUBJECT - fired, but named the wrong thing", bad_subject,
         lambda r: f"{r['case']['id']}: missing {r['missing_subject']}  got {list(r['verdict'].subjects)}")
    show("KNOWN MISSES - documented, not scored", known,
         lambda r: f"{r['case']['id']}: {'fired' if r['verdict'].research else 'missed'}  <- {r['case']['note']}")

    if args.show:
        print("\nALL CASES")
        for row in rows:
            mark = "ok  " if row["ok"] else "FAIL"
            want = "fire" if row["expected"] else "quiet"
            print(f"  {mark} {row['case']['id']:24} want={want:5} got={row['verdict'].reason}")

    # Per-subject tally: which subjects actually earn their switch.
    print("\nSUBJECTS SEEN")
    tally: dict[str, int] = {}
    for row in rows:
        for subject in row["verdict"].subjects:
            tally[subject] = tally.get(subject, 0) + 1
    for subject, count in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {subject:24} {count}")
    unseen = sorted(set(live) - set(tally))
    if unseen:
        print(f"  never matched in this corpus: {', '.join(unseen)}")

    failed = bool(fp or fn or bad_subject)
    if args.min_precision is not None and precision < args.min_precision:
        print(f"\nFAIL: precision {precision:.3f} below floor {args.min_precision}")
        failed = True
    if args.min_recall is not None and recall < args.min_recall:
        print(f"\nFAIL: recall {recall:.3f} below floor {args.min_recall}")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
