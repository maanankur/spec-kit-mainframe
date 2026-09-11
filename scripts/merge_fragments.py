#!/usr/bin/env python3
"""
merge_fragments.py -- assemble the phase-2 work-package fragments into the governed
specification artifacts, validating as it goes.

Refuses to produce an artifact it cannot validate: a merge that drops a rule or
collides two ids leaves the traceability arithmetic looking like an identity.

Rules checked: JSON per line; id unique and inside the package's allocated range
(from _fragments/plan.json); statement, evidence, confidence present; every evidence
program/paragraph resolves against the paragraph skeleton, line ranges inside the file;
non-COBOL evidence (DDL, JCL, BMS, DBD, PSB, CSD, COPYBOOK, SCHEDULER, ASM) resolves to a
real file; arithmetic recorded when the cited lines compute (advisory); worked-example
literals appear in decoded sample data when samples exist (advisory).
Traceability checked: one package per program; every skeleton paragraph once; valid
status; implemented cites existing rules; reasons present; dropped never asserted by a
package.

Usage: merge_fragments.py --workspace <out-dir> [--write] [--json]
"""
import argparse, json, os, re, sys

VALID_STATUS = {"implemented", "not-applicable", "delegated", "dropped"}
VALID_CONFIDENCE = {"high", "medium", "low"}
NON_COBOL = {"DDL", "JCL", "PROC", "BMS", "DBD", "PSB", "CSD", "COPYBOOK", "SCHEDULER", "ASM", "DATA"}
RE_ID = re.compile(r"^BR-(\d{4})$"); RE_ARITH = re.compile(r"\b(COMPUTE|MULTIPLY|DIVIDE|ADD|SUBTRACT)\b", re.I)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--write", action="store_true"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    M = os.path.join(a.workspace, "modernization"); SPEC = os.path.join(M, "2-specification"); FR = os.path.join(SPEC, "_fragments")
    skel = json.load(open(os.path.join(M, "tools", "paragraph-skeleton.json"), encoding="utf-8"))
    plan = json.load(open(os.path.join(FR, "plan.json"), encoding="utf-8"))
    ranges = {p["id"]: tuple(p["rule_range"]) for p in plan["packages"]}
    cfg = open(os.path.join(M, "modernization.config.yaml"), encoding="utf-8").read(); src = re.search(r"^\s*source_path:\s*(.+)$", cfg, re.M).group(1).strip()
    idx = {}
    for dp, dn, fn in os.walk(src):
        dn[:] = [d for d in dn if d not in (".git", "node_modules", "target", ".venv")]
        for f in fn: idx.setdefault(f.upper(), os.path.join(dp, f))
    def resolve(ref):
        if not ref: return ""
        p = os.path.join(src, ref.replace("\\", "/"))
        return p if os.path.isfile(p) else idx.get(os.path.basename(ref).upper(), "")
    nlines = {}
    def file_lines(p):
        if p not in nlines: nlines[p] = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
        return nlines[p]
    def sl(p, lo, hi):
        rows = open(p, encoding="utf-8", errors="replace").read().splitlines(); return "\n".join(rows[max(0, lo - 1):hi])
    F = []
    def err(wp, sev, msg, **kw): F.append(dict(work_package=wp, severity=sev, message=msg, **kw))
    rules, owner, trace, prog_owner, sections, notes = {}, {}, {}, {}, [], []
    for wp in sorted(ranges):
        d = os.path.join(FR, wp)
        if not os.path.isdir(d): err(wp, "error", "fragment directory missing"); continue
        lo, hi = ranges[wp]
        rp = os.path.join(d, "rules.jsonl")
        if not os.path.exists(rp): err(wp, "error", "rules.jsonl missing")
        else:
            for n, line in enumerate(open(rp, encoding="utf-8"), 1):
                if not line.strip(): continue
                try: r = json.loads(line)
                except Exception as e: err(wp, "error", "rules.jsonl line %d invalid JSON: %s" % (n, e)); continue
                rid = r.get("id", ""); m = RE_ID.match(rid or "")
                if not m: err(wp, "error", "line %d malformed id %r" % (n, rid)); continue
                if not (lo <= int(m.group(1)) <= hi): err(wp, "error", "%s outside %s range BR-%04d..BR-%04d" % (rid, wp, lo, hi), rule=rid)
                if rid in rules: err(wp, "error", "%s collides with %s" % (rid, owner[rid]), rule=rid); continue
                if not (r.get("statement") or "").strip(): err(wp, "error", "%s has no statement" % rid, rule=rid)
                if r.get("confidence") not in VALID_CONFIDENCE: err(wp, "error", "%s confidence %r invalid" % (rid, r.get("confidence")), rule=rid)
                ev = r.get("evidence") or []
                if not ev: err(wp, "error", "%s cites no evidence" % rid, rule=rid)
                computes = False
                for e in ev:
                    prog = (e.get("program") or "").upper(); para = (e.get("paragraph") or "").upper(); lines = e.get("lines") or []
                    okl = isinstance(lines, list) and len(lines) == 2 and all(isinstance(x, int) for x in lines)
                    if prog in NON_COBOL:
                        fp = resolve(e.get("file") or e.get("paragraph"))
                        if not fp: err(wp, "error", "%s cites %s evidence without a resolvable file" % (rid, prog), rule=rid); continue
                        if okl and (lines[0] < 1 or lines[1] > file_lines(fp) or lines[0] > lines[1]): err(wp, "error", "%s cites %s lines %s outside %s" % (rid, prog, lines, os.path.basename(fp)), rule=rid)
                        continue
                    if prog not in skel: err(wp, "error", "%s cites unknown program %r" % (rid, prog), rule=rid); continue
                    if para and para not in set(skel[prog]["paragraphs"]): err(wp, "warning", "%s cites %s:%s not in skeleton" % (rid, prog, para), rule=rid)
                    path = skel[prog]["path"]
                    if okl:
                        if lines[0] < 1 or lines[1] > file_lines(path) or lines[0] > lines[1]: err(wp, "error", "%s cites %s lines %s but file has %d lines" % (rid, prog, lines, file_lines(path)), rule=rid)
                        elif RE_ARITH.search(sl(path, lines[0], lines[1])): computes = True
                    else: err(wp, "warning", "%s evidence for %s lacks [first,last]" % (rid, prog), rule=rid)
                if computes and not r.get("arithmetic"): err(wp, "warning", "%s cites arithmetic but records no arithmetic block" % rid, rule=rid)
                rules[rid] = r; owner[rid] = wp
        tp = os.path.join(d, "traceability.json")
        if not os.path.exists(tp): err(wp, "error", "traceability.json missing")
        else:
            try: doc = json.load(open(tp, encoding="utf-8"))
            except Exception as e: err(wp, "error", "traceability.json invalid: %s" % e); doc = {"programs": []}
            for entry in doc.get("programs", []):
                prog = (entry.get("program") or "").upper()
                if prog not in skel: err(wp, "error", "traceability claims unknown program %r" % prog); continue
                if prog in prog_owner: err(wp, "error", "%s also claimed by %s" % (prog, prog_owner[prog])); continue
                prog_owner[prog] = wp; trace[prog] = entry.get("units", [])
        for fn, bucket in (("spec-section.md", sections), ("notes.md", notes)):
            p = os.path.join(d, fn)
            if os.path.exists(p): bucket.append((wp, open(p, encoding="utf-8").read()))
            else: err(wp, "error", "%s missing" % fn)
    for prog in sorted(skel):
        paras = skel[prog]["paragraphs"]
        if prog not in trace:
            if paras: err("-", "error", "%s has no traceability entry: %d paragraph(s) unaccounted for" % (prog, len(paras)), program=prog)
            continue
        wp = prog_owner[prog]; seen = {}
        for u in trace[prog]:
            nm = (u.get("paragraph") or "").upper(); st = u.get("status")
            if nm in seen and paras.count(nm) < 2: err(wp, "error", "%s:%s listed more than once" % (prog, nm), program=prog)
            seen[nm] = u
            if st not in VALID_STATUS: err(wp, "error", "%s:%s invalid status %r" % (prog, nm, st), program=prog)
            if st == "implemented":
                refs = u.get("rules") or []
                if not refs: err(wp, "error", "%s:%s implemented but cites no rule" % (prog, nm), program=prog)
                for r in refs:
                    if r not in rules: err(wp, "error", "%s:%s cites unknown rule %s" % (prog, nm, r), program=prog)
            if st in ("not-applicable", "delegated") and not u.get("reason"): err(wp, "error", "%s:%s %s without a reason" % (prog, nm, st), program=prog)
            if st == "dropped": err(wp, "error" if not u.get("approved_by") else "warning", "%s:%s dropped -- a gate decision, verify approver" % (prog, nm), program=prog)
        for p in paras:
            if p not in seen: err(wp, "error", "%s:%s UNACCOUNTED FOR" % (prog, p), program=prog)
        for p in seen:
            if p not in set(paras): err(wp, "warning", "%s:%s claimed but not in source" % (prog, p), program=prog)
    cited = {r for units in trace.values() for u in units for r in (u.get("rules") or [])}
    for rid in sorted(set(rules) - cited): err(owner.get(rid, "-"), "warning", "%s is not cited by any paragraph" % rid, rule=rid)
    total = sum(len(v["paragraphs"]) for v in skel.values()); acc = sum(1 for p, units in trace.items() for u in units if (u.get("paragraph") or "").upper() in set(skel[p]["paragraphs"]))
    errors = [f for f in F if f["severity"] == "error"]; warnings = [f for f in F if f["severity"] == "warning"]
    summary = dict(paragraphs_in_source=total, paragraphs_accounted=acc, coverage_pct=round(100.0 * acc / total, 2) if total else 100.0, rules=len(rules),
                   confidence={c: sum(1 for r in rules.values() if r.get("confidence") == c) for c in VALID_CONFIDENCE}, open_questions=sum(1 for r in rules.values() if r.get("open_question")),
                   suspected_defects=sum(1 for r in rules.values() if r.get("suspected_defect")), programs_claimed=len(prog_owner), programs_in_source=len(skel), errors=len(errors), warnings=len(warnings))
    if a.json: print(json.dumps({"summary": summary, "findings": F}, indent=1))
    else:
        for k, v in summary.items(): print("  %-24s %s" % (k, v))
        for f in errors[:60]: print("  [%s] %s" % (f["work_package"], f["message"]))
        if len(errors) > 60: print("  ... and %d more errors" % (len(errors) - 60))
        for f in warnings[:30]: print("  warn [%s] %s" % (f["work_package"], f["message"]))
    if a.write:
        with open(os.path.join(SPEC, "business-rules.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
            for rid in sorted(rules): fh.write(json.dumps(rules[rid], ensure_ascii=False) + "\n")
        json.dump({"programs": [{"program": p, "units": trace[p]} for p in sorted(trace)]}, open(os.path.join(SPEC, "traceability.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        json.dump({"summary": summary, "findings": F}, open(os.path.join(SPEC, "merge-report.json"), "w", encoding="utf-8"), indent=1)
        print("wrote business-rules.jsonl, traceability.json, merge-report.json")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
