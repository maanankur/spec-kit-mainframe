#!/usr/bin/env python3
"""
use_case_coverage.py -- the use-case coverage matrix, generated, never hand-written.

A use case counts as covered only by EXECUTED evidence: a test method that cites
its id (`UC-nnn` in the method's Javadoc/comment, a `@UseCase("UC-nnn")` annotation,
or the id in the method name) AND appears as a passed testcase in a surefire or
failsafe XML report; or a golden-master pair that lists the use case and has zero
unexplained differences. A test that exists but did not run covers nothing -- that
was the gap on the first corpus (ITs written, never executed, reported as green).

Inputs: 2-specification/use-cases.jsonl (id, name, context, kind, rules[])
        target/backend/src/test/java/**/*.java (or --tests-root), target/backend/target/{surefire,failsafe}-reports/TEST-*.xml
        target/ops/out/golden-master-report.json (pairs carry use_cases)
Outputs: target/ops/out/use-case-coverage.{json,md}

Usage: use_case_coverage.py --workspace <out-dir> [--tests-root DIR] [--reports DIR ...]
"""
import argparse, glob, os, re, sys, xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import WS, NOW, read, write, jload, jdump, jsonl

RE_BR = re.compile(r"\bBR-\d{4}\b")



def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--tests-root"); ap.add_argument("--reports", action="append"); a = ap.parse_args(); ws = WS(a.workspace)
    ucs = jsonl(os.path.join(ws.SPEC, "use-cases.jsonl")); rules = jsonl(os.path.join(ws.SPEC, "business-rules.jsonl"))
    # use-case ids are whatever use-cases.jsonl declares (UC-001 or UC-ACCT-VIEW); match them literally, longest first
    RE_UC = re.compile(r"(?<![\w-])(%s)(?![\w-])" % "|".join(re.escape(u["id"]) for u in sorted(ucs, key=lambda u: -len(u["id"])))) if ucs else re.compile(r"(?!x)x")
    tests_root = a.tests_root or os.path.join(ws.T, "backend", "src", "test", "java")
    reports = a.reports or [os.path.join(ws.T, "backend", "target", "surefire-reports"), os.path.join(ws.T, "backend", "target", "failsafe-reports")]
    # executed testcases
    executed = {}   # (class, method) -> passed
    for d in reports:
        for f in glob.glob(os.path.join(d, "TEST-*.xml")):
            for tc in ET.parse(f).getroot().iter("testcase"):
                ok = not any(ch.tag in ("failure", "error", "skipped") for ch in tc); executed[(tc.get("classname"), tc.get("name"))] = ok
    class_ok = {}
    for (c, m), ok in executed.items(): class_ok[c] = class_ok.get(c, True) and ok
    # tests citing use cases
    cites = {}   # uc -> [(class, method)]
    br_cited = set()
    for f in glob.glob(os.path.join(tests_root, "**", "*.java"), recursive=True):
        src = read(f); pkg = (re.search(r"^\s*package\s+([\w.]+)\s*;", src, re.M) or [None, ""])[1]; cls = (re.search(r"\bclass\s+(\w+)", src) or [None, os.path.basename(f)[:-5]])[1]
        fq = (pkg + "." if pkg else "") + cls; br_cited |= set(RE_BR.findall(src))
        head = src[:src.find("class " + cls)] if "class " + cls in src else ""; class_ucs = set(RE_UC.findall(head)) | set(re.findall(r'@UseCase\s*\(\s*"([^"]+)"', head))
        blocks = re.split(r"(?=@Test\b|@ParameterizedTest\b|@RepeatedTest\b)", src)
        for i, b in enumerate(blocks[1:], 1):
            m = re.search(r"\bvoid\s+(\w+)\s*\(", b); name = m.group(1) if m else None
            prev = blocks[i - 1]; above = prev[max(prev.rfind("}"), prev.rfind(";")) + 1:]   # the comment/Javadoc lines between the previous member and this annotation
            ids = set(RE_UC.findall(above)) | set(RE_UC.findall(b)) | set(re.findall(r'@UseCase\s*\(\s*"([^"]+)"', above + b)) | set(RE_UC.findall(name or ""))
            for uc in ids | class_ucs: cites.setdefault(uc, []).append((fq, name))
    gm = jload(os.path.join(ws.T, "ops", "out", "golden-master-report.json"), []) or []
    gm_cov = {}
    for r in gm:
        for uc in r.get("use_cases", []) or []: gm_cov.setdefault(uc, []).append((r.get("file"), r.get("unexplained", 1) == 0 and "missing" not in r))
    rows = []
    for u in ucs:
        ts = []
        for fq, name in cites.get(u["id"], []):
            ex = (fq, name) in executed if name else fq in class_ok
            passed = executed.get((fq, name)) if name else class_ok.get(fq)
            ts.append(dict(**{"class": fq, "method": name, "executed": bool(ex), "passed": bool(passed)}))
        gms = [dict(pair=p, green=g) for p, g in gm_cov.get(u["id"], [])]
        covered = any(t["executed"] and t["passed"] for t in ts) or any(g["green"] for g in gms)
        rows.append(dict(id=u["id"], name=u.get("name"), context=u.get("context"), kind=u.get("kind"), rules=u.get("rules", []), tests=ts, golden_master=gms, covered=covered,
                         written_but_not_executed=[t for t in ts if not t["executed"]], failing=[t for t in ts if t["executed"] and not t["passed"]]))
    n = len(rows); cov = sum(1 for r in rows if r["covered"]); pct = round(100.0 * cov / n, 1) if n else 0.0
    rule_ids = {r["id"] for r in rules}; uncited = sorted(rule_ids - br_cited)
    out = dict(generated_at=NOW, source=dict(use_cases=ws.rel(os.path.join(ws.SPEC, "use-cases.jsonl")), tests_root=ws.rel(tests_root), reports=[ws.rel(d) for d in reports], testcases_executed=len(executed), testcases_passed=sum(1 for v in executed.values() if v)),
               coverage=dict(use_cases=n, covered=cov, pct=pct, uncovered=[r["id"] for r in rows if not r["covered"]], written_but_not_executed=sum(len(r["written_but_not_executed"]) for r in rows), failing=sum(len(r["failing"]) for r in rows)),
               rules=dict(total=len(rule_ids), cited_in_tests=len(rule_ids & br_cited), uncited=uncited), use_cases=rows)
    os.makedirs(os.path.join(ws.T, "ops", "out"), exist_ok=True); jdump(os.path.join(ws.T, "ops", "out", "use-case-coverage.json"), out)
    L = ["# Use-case coverage\n", "Generated %s by `use_case_coverage.py`. Covered = at least one **executed, passed** test method citing the use case, or a green golden-master pair listing it. Tests that exist but did not run cover nothing.\n" % NOW,
         "**%d/%d use cases covered (%.1f%%)** · testcases executed %d (passed %d) · tests written but not executed %d · failing %d · rules cited in tests %d/%d\n" % (cov, n, pct, len(executed), sum(1 for v in executed.values() if v), out["coverage"]["written_but_not_executed"], out["coverage"]["failing"], len(rule_ids & br_cited), len(rule_ids)),
         "| Use case | Context | Kind | Executed tests (passed) | Golden master | Covered |", "|---|---|---|---|---|---|"]
    L += ["| %s %s | %s | %s | %s | %s | %s |" % (r["id"], r["name"], r["context"], r["kind"], ", ".join("%s#%s%s" % (t["class"].split(".")[-1], t["method"], "" if t["passed"] else " ❌") for t in r["tests"] if t["executed"]) or "—", ", ".join("%s%s" % (g["pair"], "" if g["green"] else " ❌") for g in r["golden_master"]) or "—", "✅" if r["covered"] else "🔴") for r in rows]
    if uncited: L += ["\n## Rules not cited by any test (%d)\n" % len(uncited), ", ".join(uncited)]
    write(os.path.join(ws.T, "ops", "out", "use-case-coverage.md"), "\n".join(L) + "\n")
    print("use cases %d | covered %d (%.1f%%) | executed testcases %d | written-not-executed %d | rules cited %d/%d" % (n, cov, pct, len(executed), out["coverage"]["written_but_not_executed"], len(rule_ids & br_cited), len(rule_ids)))
    return 0 if n and cov == n else 1


if __name__ == "__main__":
    sys.exit(main())
