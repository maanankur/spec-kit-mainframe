#!/usr/bin/env python3
"""
trace_coverage.py -- traceability completeness gate. "Not accounted for" = 0.

This is the single most important control in the pipeline. Business logic does
not get lost in modernization through dramatic failures; it gets lost quietly,
in a paragraph nobody noticed, and surfaces months later as a wrong number on a
statement. The defence is not more review -- it is an accounting identity:

    every paragraph in the legacy source
      == implemented + not-applicable + delegated + dropped

Anything left over is unexamined logic, and the gate fails.

Deliberately re-derives paragraph names from the COBOL source rather than
trusting inventory.json. A checker that shares its input with the thing it
checks cannot detect that the input was wrong.

Traceability file (modernization/2-specification/traceability.json):

  {"programs": [
     {"program": "CBACT04C",
      "units": [
        {"paragraph": "1000-ACCTFILE-GET-NEXT", "status": "implemented",
         "rules": ["BR-0042"], "target": "AccountReader.read"},
        {"paragraph": "9999-ABEND-PROGRAM", "status": "not-applicable",
         "reason": "abend plumbing; replaced by exception handling"},
        {"paragraph": "0000-HOUSEKEEPING", "status": "delegated",
         "reason": "Spring Batch step lifecycle"},
        {"paragraph": "8000-LEGACY-FAX", "status": "dropped",
         "reason": "fax channel retired 2019", "approved_by": "R. Kapoor 2026-03-04"}
      ]}]}

Rules enforced:
  * every source paragraph appears exactly once
  * no paragraph is claimed that does not exist in the source
  * status is one of the four known values
  * "implemented" cites at least one business rule id
  * "dropped" carries an approved_by -- dropping logic is a human decision
  * "not-applicable"/"delegated" carry a reason

Usage:
  trace_coverage.py --source SRC_ROOT
                    [--traceability modernization/2-specification/traceability.json]
                    [--rules modernization/2-specification/business-rules.jsonl]
                    [--programs P1,P2] [--json] [--min-coverage 100]

Exit 0 only when coverage is complete and no violations remain.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

VALID = {"implemented", "not-applicable", "delegated", "dropped"}
COBOL_EXT = {".cbl", ".cob", ".cobol"}

RE_PROGRAM_ID = re.compile(r"\bPROGRAM-ID\s*\.\s*([A-Z0-9\-_]+)", re.I)
# A paragraph name sits alone on a line in area A, followed by a period.
RE_PARA = re.compile(r"^([A-Z0-9][A-Z0-9\-_]*)\s*\.\s*$", re.I)
RE_DIVISION = re.compile(r"\b(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION",
                         re.I)
SECTION_WORDS = {"SECTION", "DIVISION", "END-EXEC", "EXIT"}


def procedure_paragraphs(path: str) -> tuple:
    """(program_name, [paragraph names in PROCEDURE DIVISION])."""
    raw = open(path, "r", encoding="utf-8", errors="replace").read()
    name = os.path.splitext(os.path.basename(path))[0].upper()
    # Resolve PROGRAM-ID from the code area (cols 7-72) only. Run over the raw
    # text, the regex crossed a newline on members that carry sequence numbers
    # and put the name on the line after PROGRAM-ID., capturing a sequence
    # number instead (CardDemo COTRTLIC -> "002600", COTRTUPC -> "00220000").
    code_only = chr(10).join(
        (ln[6:72] if len(ln) > 6 else "") for ln in raw.splitlines())
    m = RE_PROGRAM_ID.search(code_only)
    if m:
        name = m.group(1).upper()

    paras, in_proc = [], False
    for line in raw.splitlines():
        if len(line) >= 7 and line[6] in ("*", "/"):
            continue
        code = line[6:72] if len(line) > 6 else ""
        if not code.strip():
            continue
        if RE_DIVISION.search(code):
            in_proc = bool(re.search(r"\bPROCEDURE\s+DIVISION", code, re.I))
            continue
        if not in_proc:
            continue
        # area A begins at col 8 -- a paragraph name starts there, statements
        # are indented into area B.
        areaA = code[1:5]
        if not areaA.strip() or areaA[0] == " ":
            continue
        pm = RE_PARA.match(code[1:].strip())
        if pm:
            nm = pm.group(1).upper()
            if nm not in SECTION_WORDS and not nm.startswith("END-"):
                paras.append(nm)
    # a paragraph may legitimately appear once; duplicates mean a parse problem
    return name, paras


def collect_source(root: str) -> dict:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", "target", ".venv")]
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1].lower() in COBOL_EXT:
                p = os.path.join(dirpath, fn)
                try:
                    name, paras = procedure_paragraphs(p)
                    out[name] = {"path": p.replace("\\", "/"),
                                 "paragraphs": paras}
                except Exception as e:
                    print("WARN could not parse %s: %s" % (p, e), file=sys.stderr)
    return out


def load_rules(path: str) -> set:
    ids = set()
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ids.add(json.loads(line)["id"])
                except Exception:
                    pass
    return ids


def check(source: dict, trace: dict, rule_ids: set, scope: list) -> dict:
    by_prog = {p["program"].upper(): p for p in trace.get("programs", [])}
    findings, per_program = [], []
    tot_paras = tot_covered = 0

    targets = scope or sorted(source)
    for prog in targets:
        if prog not in source:
            findings.append({"program": prog, "severity": "error",
                             "message": "in scope but no source found"})
            continue
        paras = source[prog]["paragraphs"]
        entry = by_prog.get(prog)
        if entry is None:
            findings.append({
                "program": prog, "severity": "error",
                "message": "no traceability entry: %d paragraph(s) unaccounted for"
                           % len(paras)})
            per_program.append({"program": prog, "paragraphs": len(paras),
                                "accounted": 0, "coverage": 0.0})
            tot_paras += len(paras)
            continue

        seen, units = {}, entry.get("units", [])
        for u in units:
            nm = (u.get("paragraph") or "").upper()
            st = u.get("status")
            if nm in seen:
                findings.append({"program": prog, "paragraph": nm,
                                 "severity": "error",
                                 "message": "listed more than once"})
            seen[nm] = u
            if st not in VALID:
                findings.append({
                    "program": prog, "paragraph": nm, "severity": "error",
                    "message": "invalid status %r (want one of %s)"
                               % (st, ", ".join(sorted(VALID)))})
            if st == "implemented":
                refs = u.get("rules") or []
                if not refs:
                    findings.append({
                        "program": prog, "paragraph": nm, "severity": "error",
                        "message": "implemented but cites no business rule -- "
                                   "without a rule id there is nothing to test "
                                   "against"})
                unknown = [r for r in refs if rule_ids and r not in rule_ids]
                if unknown:
                    findings.append({
                        "program": prog, "paragraph": nm, "severity": "error",
                        "message": "cites unknown rule id(s): %s"
                                   % ", ".join(unknown)})
            if st == "dropped" and not u.get("approved_by"):
                findings.append({
                    "program": prog, "paragraph": nm, "severity": "error",
                    "message": "dropped without approved_by -- discarding "
                               "behaviour is a human decision, not the "
                               "pipeline's"})
            if st in ("not-applicable", "delegated") and not u.get("reason"):
                findings.append({
                    "program": prog, "paragraph": nm, "severity": "error",
                    "message": "%s without a reason" % st})

        missing = [p for p in paras if p not in seen]
        phantom = [n for n in seen if n not in set(paras)]
        for p in missing:
            findings.append({"program": prog, "paragraph": p,
                             "severity": "error",
                             "message": "UNACCOUNTED FOR -- present in source, "
                                        "absent from traceability"})
        for p in phantom:
            findings.append({"program": prog, "paragraph": p,
                             "severity": "warning",
                             "message": "claimed but not found in source "
                                        "(renamed or stale entry?)"})

        covered = len(paras) - len(missing)
        tot_paras += len(paras)
        tot_covered += covered
        per_program.append({
            "program": prog, "paragraphs": len(paras), "accounted": covered,
            "coverage": round(100.0 * covered / len(paras), 1) if paras else 100.0,
            "implemented": sum(1 for u in units if u.get("status") == "implemented"),
            "not_applicable": sum(1 for u in units
                                  if u.get("status") == "not-applicable"),
            "delegated": sum(1 for u in units if u.get("status") == "delegated"),
            "dropped": sum(1 for u in units if u.get("status") == "dropped"),
        })

    coverage = round(100.0 * tot_covered / tot_paras, 2) if tot_paras else 100.0
    return {"coverage_pct": coverage, "paragraphs": tot_paras,
            "accounted": tot_covered, "per_program": per_program,
            "findings": findings}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True)
    ap.add_argument("--traceability",
                    default="modernization/2-specification/traceability.json")
    ap.add_argument("--rules",
                    default="modernization/2-specification/business-rules.jsonl")
    ap.add_argument("--programs", help="comma-separated scope (default: all)")
    ap.add_argument("--min-coverage", type=float, default=100.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    source = collect_source(a.source)
    if not source:
        print("no COBOL found under %s" % a.source, file=sys.stderr)
        return 2
    trace = {"programs": []}
    if os.path.exists(a.traceability):
        trace = json.load(open(a.traceability, encoding="utf-8"))
    else:
        print("no traceability file at %s -- reporting full exposure"
              % a.traceability, file=sys.stderr)
    scope = [p.strip().upper() for p in a.programs.split(",")] if a.programs else []

    res = check(source, trace, load_rules(a.rules), scope)

    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print("traceability coverage: %.2f%%  (%d/%d paragraphs accounted for)"
              % (res["coverage_pct"], res["accounted"], res["paragraphs"]))
        print("\n  %-12s %6s %9s %6s %5s %5s %5s"
              % ("PROGRAM", "PARAS", "ACCOUNTED", "COV%", "IMPL", "N/A", "DROP"))
        for p in sorted(res["per_program"], key=lambda x: x["coverage"]):
            print("  %-12s %6d %9d %5.1f%% %5s %5s %5s"
                  % (p["program"], p["paragraphs"], p["accounted"],
                     p["coverage"], p.get("implemented", "-"),
                     p.get("not_applicable", "-"), p.get("dropped", "-")))
        errs = [f for f in res["findings"] if f["severity"] == "error"]
        warns = [f for f in res["findings"] if f["severity"] == "warning"]
        if errs:
            print("\n  %d error(s):" % len(errs))
            for f in errs[:40]:
                print("    %-12s %-28s %s"
                      % (f.get("program", ""), f.get("paragraph", ""),
                         f["message"]))
            if len(errs) > 40:
                print("    ... and %d more" % (len(errs) - 40))
        if warns:
            print("\n  %d warning(s):" % len(warns))
            for f in warns[:15]:
                print("    %-12s %-28s %s"
                      % (f.get("program", ""), f.get("paragraph", ""),
                         f["message"]))

    ok = (res["coverage_pct"] >= a.min_coverage
          and not any(f["severity"] == "error" for f in res["findings"]))
    if not a.json:
        print("\nGATE %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
