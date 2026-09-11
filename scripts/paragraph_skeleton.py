#!/usr/bin/env python3
"""
paragraph_skeleton.py -- the authoritative paragraph list per program, produced by
the same parser the traceability gate uses (trace_coverage.py).

Why a separate artifact: work packages must classify exactly the paragraphs the
gate will count. Any other parser (inventory.py's count was 19% high on the first
corpus) produces a list that looks right and fails the gate.

Usage: paragraph_skeleton.py --source SRC_ROOT --out modernization/tools/paragraph-skeleton.json
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trace_coverage as tc


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--source", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    src = tc.collect_source(a.source)
    skel = {k: {"path": v["path"], "paragraph_count": len(v["paragraphs"]), "paragraphs": v["paragraphs"],
                "duplicates": sorted({p for p in v["paragraphs"] if v["paragraphs"].count(p) > 1})} for k, v in sorted(src.items())}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(skel, open(a.out, "w", encoding="utf-8"), indent=1)
    dups = {k: v["duplicates"] for k, v in skel.items() if v["duplicates"]}
    print("programs %d | paragraphs %d | duplicate paragraph names: %s" % (len(skel), sum(v["paragraph_count"] for v in skel.values()), dups or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
