#!/usr/bin/env python3
"""
evidence_pack.py -- assemble the G5 (build), G6 (equivalence) and G7 (go-live)
evidence from what actually ran, and propose the gate.

Evidence is read, never typed in: surefire AND failsafe XML (a test that was
written but never executed is not evidence), the generated use-case coverage
matrix, the golden-master report, the target run log, the legacy run manifest,
scanner summaries, compose state and the health endpoint. Red rows stay red; the
decision (approve / waive) is gate_decide.py's job.

Optional overrides: target/ops/evidence.json {health_url, ui_url, compose_dir, scans, online_replay}
Usage: evidence_pack.py --workspace W --gate G5|G6|G7 [--wave "wave 1"]
"""
import argparse, glob, os, re, subprocess, sys, xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import WS, NOW, read, write, jload, load_yaml, manifest, render_pack, propose_gate

HERE = os.path.dirname(os.path.abspath(__file__))


def tests(d):
    t = dict(run=0, fail=0, err=0, skip=0, classes=[])
    for f in glob.glob(os.path.join(d, "TEST-*.xml")):
        r = ET.parse(f).getroot(); t["run"] += int(r.get("tests", 0)); t["fail"] += int(r.get("failures", 0)); t["err"] += int(r.get("errors", 0)); t["skip"] += int(r.get("skipped", 0)); t["classes"].append(r.get("name", "").split(".")[-1])
    return t


def sh(c, cwd):
    r = subprocess.run(c, shell=True, capture_output=True, text=True, env=dict(os.environ, MSYS_NO_PATHCONV="1"), cwd=cwd); return (r.stdout + r.stderr).strip()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--gate", required=True, choices=["G5", "G6", "G7"]); ap.add_argument("--wave", default="current wave"); a = ap.parse_args(); ws = WS(a.workspace)
    T = ws.T; B = os.path.join(T, "backend"); O = os.path.join(T, "ops", "out"); EV = jload(os.path.join(T, "ops", "evidence.json"), {})
    prof = load_yaml(os.path.join(os.path.dirname(HERE), "profiles", str(ws.cfg.get("target", {}).get("profile", "spring-postgres-react-aws")) + ".yaml")); targets = prof.get("testing", {}).get("coverage_targets", {})
    unit = tests(os.path.join(B, "target", "surefire-reports")); it = tests(os.path.join(B, "target", "failsafe-reports")); ucc = jload(os.path.join(O, "use-case-coverage.json"), {"coverage": {"pct": 0, "use_cases": 0, "covered": 0, "written_but_not_executed": 0}, "rules": {"total": 0, "cited_in_tests": 0}})
    gm = jload(os.path.join(O, "golden-master-report.json"), []) or []; gi = sum(r.get("identical", 0) for r in gm); ge = sum(r.get("explained", 0) for r in gm); gu = sum(r.get("unexplained", 0) for r in gm); gmiss = [r["file"] for r in gm if "missing" in r]
    jrun = jload(os.path.join(O, "java-run.json"), {"steps": []}); lrun = jload(os.path.join(T, "legacy", "out", "manifest.json"), {"return_codes": {}})
    java = glob.glob(os.path.join(B, "src", "main", "java", "**", "*.java"), recursive=True); jsrc = " ".join(read(f) for f in java); rules = [l for l in read(os.path.join(ws.SPEC, "business-rules.jsonl")).splitlines() if l.strip()]
    cited = set(re.findall(r"BR-\d{4}", jsrc)); ucs_rules = {r for u in (ucc.get("use_cases") or []) if u.get("covered") for r in u.get("rules", [])}
    appyml = read(os.path.join(B, "src", "main", "resources", "application.yml")) + read(os.path.join(B, "src", "main", "resources", "application.yaml"))
    scans = EV.get("scans") or jload(os.path.join(O, "scans", "summary.json"))
    if a.gate == "G5":
        jobol = sh('python "%s" "%s" 2>&1 | tail -3' % (os.path.join(HERE, "jobol_lint.py"), os.path.join(B, "src", "main", "java")), T)
        jar = glob.glob(os.path.join(B, "target", "*.jar")); images = sh("docker compose images 2>/dev/null | tail -n +2", T)
        rows = [("Compiles and packages", "%s; compose images: %s" % ("jar built" if jar else "no jar under backend/target", images.replace("\n", "; ")[:120] or "none"), "built", bool(jar) or bool(images)),
                ("Unit + architecture tests EXECUTED", "%d run, %d failures, %d errors, %d skipped (%s)" % (unit["run"], unit["fail"], unit["err"], unit["skip"], ", ".join(unit["classes"])), "> 0 run, 0 failures", unit["run"] > 0 and unit["fail"] + unit["err"] == 0),
                ("Integration tests EXECUTED (failsafe)", "%d run, %d failures, %d errors (%s)" % (it["run"], it["fail"], it["err"], ", ".join(it["classes"]) or "no failsafe report — ITs were not run"), "> 0 run, 0 failures", it["run"] > 0 and it["fail"] + it["err"] == 0),
                ("ArchUnit: seams enforced, kernel depends on no context, no floating-point money", "ArchitectureTest %s" % ("executed green" if "ArchitectureTest" in unit["classes"] and unit["fail"] + unit["err"] == 0 else "not executed"), "green", "ArchitectureTest" in unit["classes"] and unit["fail"] + unit["err"] == 0),
                ("JOBOL structural lint", jobol.replace("\n", " ")[:160] or "lint not run", "0 errors", bool(re.search(r"\b0 error|no findings|\bOK\b", jobol))),
                ("Rules of covered use cases cited in Java", "%d/%d rule ids cited across %d sources (%d rules in total)" % (len(ucs_rules & cited), len(ucs_rules), len(java), len(rules)), "all rules of covered use cases", bool(ucs_rules) and ucs_rules <= cited),
                ("Use-case coverage (executed evidence)", "%s/%s (%s%%); written-but-not-executed tests: %s" % (ucc["coverage"].get("covered"), ucc["coverage"].get("use_cases"), ucc["coverage"].get("pct"), ucc["coverage"].get("written_but_not_executed")), "%s%%" % targets.get("use_cases", 100), ucc["coverage"].get("pct", 0) >= float(targets.get("use_cases", 100)) and ucc["coverage"].get("use_cases", 0) > 0),
                ("Platform defaults applied (ADR-000)", "%s" % ", ".join(k for k, v in (("@Transactional", "@Transactional" in jsrc), ("spring profiles", bool(re.search(r"profiles|on-profile", appyml))), ("env-var credentials", "${" in appyml), ("docker-compose", os.path.exists(os.path.join(T, "docker-compose.yml"))), ("ArchitectureTest", "ArchitectureTest" in unit["classes"])) if v), "all five", all(("@Transactional" in jsrc, bool(re.search(r"profiles|on-profile", appyml)), "${" in appyml, os.path.exists(os.path.join(T, "docker-compose.yml")), "ArchitectureTest" in unit["classes"]))),
                ("Specification firewall", "code-generation agent has no COBOL read path (agent tool denial); layouts for golden-master exports come from mapping.json", "no COBOL read", None),
                ("SAST / SCA / secrets scan", ("sast critical %s high %s; sca critical %s high %s; secrets %s" % (scans.get("sast", {}).get("critical"), scans.get("sast", {}).get("high"), scans.get("sca", {}).get("critical"), scans.get("sca", {}).get("high"), scans.get("secrets", {}).get("count"))) if scans else "not run (no target/ops/out/scans/summary.json)", "0 critical/high, 0 secrets",
                 bool(scans) and not any(int(scans.get(k, {}).get(s, 0) or 0) for k in ("sast", "sca") for s in ("critical", "high")) and not int(scans.get("secrets", {}).get("count", 0) or 0))]
        arts = [os.path.join(B, "pom.xml"), os.path.join(O, "use-case-coverage.json"), os.path.join(T, "docker-compose.yml")] + sorted(java) + sorted(glob.glob(os.path.join(B, "target", "surefire-reports", "TEST-*.xml"))) + sorted(glob.glob(os.path.join(B, "target", "failsafe-reports", "TEST-*.xml")))
        pack = render_pack(ws, "G5", "accept the generated code for %s as a faithful, idiomatic implementation of the approved specification slice: compiles, seams enforced, rules cited, every use case proven by an executed test." % a.wave,
                           "**Tech Lead:** does the code implement the rules it cites, are the ArchUnit seams the G3 seams, did every test actually execute (surefire *and* failsafe reports present)? **Security:** scanner results, secrets handling (env-var credentials, committed `dev` defaults only), dependency vulnerabilities.",
                           "Code that compiles and looks right but violates a rule reaches verification as a false failure or, worse, a false pass on a rule the tests did not cover. Tests that were written but never run are the most expensive kind of false green.",
                           [("Rule coverage of the slice", "medium", "%d of %d rules cited" % (len(cited & {r for r in re.findall(r'"id": "(BR-\d{4})"', "\n".join(rules))}), len(rules)), "traceability update per wave")],
                           ["Whether Spring Batch restart semantics match operational runbooks (none supplied)."] + ([] if scans else ["SAST/SCA/secret scanning — no scanner summary in the environment."]), rows, *manifest(ws, arts), "`pom.xml`, Java sources, test reports (surefire + failsafe), `use-case-coverage.json`, `docker-compose.yml`.")
    elif a.gate == "G6":
        flags = re.findall(r"legacy-defects:\n((?:\s+.+\n)+)", appyml); sm = jload(os.path.join(ws.D5, "store-map.json"), {}); replay = EV.get("online_replay") or jload(os.path.join(O, "online-replay.json"))
        rows = [("Golden master: legacy vs target, typed field-by-field", "%d identical · %d explained · %d unexplained%s" % (gi, ge, gu, ("; missing: " + ", ".join(gmiss)) if gmiss else ""), "0 unexplained, nothing missing", bool(gm) and gu == 0 and not gmiss),
                ("Batch chain executed on both sides with identical inputs", "legacy RCs %s; target steps %d" % (lrun.get("return_codes"), len(jrun.get("steps", []))), "same sequence, RC 0/4", bool(lrun.get("return_codes")) and all(v in (0, 4) for v in lrun.get("return_codes", {}).values()) and len(jrun.get("steps", [])) > 0),
                ("Every difference explained", "categories listed in golden-master-report.md", "all", gu == 0),
                ("Rule-derived tests executed", "unit %d + integration %d run, %d failures" % (unit["run"], it["run"], unit["fail"] + unit["err"] + it["fail"] + it["err"]), "green", unit["run"] + it["run"] > 0 and unit["fail"] + unit["err"] + it["fail"] + it["err"] == 0),
                ("Use-case coverage (executed evidence)", "%s%% of %s use cases" % (ucc["coverage"].get("pct"), ucc["coverage"].get("use_cases")), "%s%%" % targets.get("use_cases", 100), ucc["coverage"].get("pct", 0) >= float(targets.get("use_cases", 100)) and ucc["coverage"].get("use_cases", 0) > 0),
                ("Legacy defects preserved by default until the PO decides", ("%d flags in application.yml" % len(flags[0].strip().splitlines())) if flags else "no legacy-defects flags found", "preserve unless decided at G1", None),
                ("Production-volume equivalence", "production extracts %s" % ("supplied" if sm.get("production_extracts_supplied") else "NOT supplied — sample data only"), "production extract", bool(sm.get("production_extracts_supplied"))),
                ("Online screens equivalence", ("replay corpus: %s requests, %s mismatches" % (replay.get("requests"), replay.get("mismatches"))) if replay else "no request/response corpus (no transaction monitor available); verified via rules and API tests only", "request/response corpus replayed, 0 mismatches", bool(replay) and int(replay.get("mismatches", 1) or 0) == 0)]
        arts = [os.path.join(O, "golden-master-report.md"), os.path.join(O, "golden-master-report.json"), os.path.join(O, "java-run.json"), os.path.join(O, "use-case-coverage.json"), os.path.join(T, "legacy", "out", "manifest.json")] + sorted(glob.glob(os.path.join(O, "java", "*")))
        pack = render_pack(ws, "G6", "accept that the target behaves as the legacy does for %s on the data it ran on: %d fields identical, %d explained, %d unexplained." % (a.wave, gi, ge, gu),
                           "**Product Owner:** are the explained differences acceptable and are the preserved defects your intent? **QA Lead:** did both chains run on identical inputs, is every difference categorised, did every test execute? **Business Analyst:** do the golden-master pairs cover the use cases that matter?",
                           "A behavioural difference approved here becomes production behaviour. The golden master proves equivalence only on the data it ran on; anything it did not exercise is residual risk.",
                           [("Equivalence on production data", "low" if not sm.get("production_extracts_supplied") else "high", "sample data only" if not sm.get("production_extracts_supplied") else "production extracts used", "production extracts"), ("Online behaviour", "low" if not replay else "medium", "no transaction monitor to replay against" if not replay else "corpus replayed", "request/response corpus")],
                           ["Batch-window and response-time baselines unless captured in wave 1.", "Restart/rerun behaviour under failure (no runbooks supplied)."], rows, *manifest(ws, arts), "`golden-master-report.{md,json}`: the comparison. `java-run.json` / `legacy/out/manifest.json`: what ran on each side. `use-case-coverage.json`: the executed-evidence matrix. `ops/out/java/*`: the target's fixed-width exports.")
    else:
        health_url = EV.get("health_url", "http://localhost:8080/actuator/health"); ui_url = EV.get("ui_url", "http://localhost:3000/")
        ps = sh("docker compose ps --format '{{.Service}} {{.Status}}'", EV.get("compose_dir", T)); health = sh("curl -fsS %s" % health_url, T); ui = sh("curl -s -o /dev/null -w '%%{http_code}' %s" % ui_url, T)
        rb = read(os.path.join(ws.M, "8-deploy", "runbook.md")); cp = read(os.path.join(ws.M, "8-deploy", "cutover-plan.md")); ready = EV.get("production_readiness") or jload(os.path.join(O, "prod-readiness.json"))
        rows = [("Stack deployed under compose", ps.replace("\n", "; ") or "not running", "all services Up", bool(ps) and "Up" in ps and "Exit" not in ps),
                ("Application health", health[:80] or "no response", '"status":"UP"', '"UP"' in health), ("UI reachable", "HTTP %s on %s" % (ui or "-", ui_url), "200", ui == "200"),
                ("Rollback documented", "runbook.md %s a Rollback section" % ("has" if re.search(r"rollback", rb, re.I) else "LACKS"), "documented", bool(re.search(r"rollback", rb, re.I))),
                ("Cutover plan / runbook present", "%s / %s" % ("cutover-plan.md" if cp else "MISSING", "runbook.md" if rb else "MISSING"), "present", bool(cp and rb)),
                ("Production readiness", ("qa/prod profiles %s, secrets manager %s, TLS %s, OIDC %s, CI/CD %s" % tuple(ready.get(k, "?") for k in ("profiles", "secrets", "tls", "oidc", "cicd"))) if ready else "dev profile only; no prod-readiness.json — this is a development deployment", "prod profile + IaC + pipeline + scans", bool(ready) and all(ready.get(k) in (True, "yes", "present") for k in ("profiles", "secrets", "tls", "oidc", "cicd")))]
        arts = [os.path.join(T, "docker-compose.yml"), os.path.join(ws.M, "8-deploy", "cutover-plan.md"), os.path.join(ws.M, "8-deploy", "runbook.md")]
        pack = render_pack(ws, "G7", "record that the %s stack is deployed, healthy and demonstrable in this environment%s." % (a.wave, "" if ready else " — explicitly not a production go-live"),
                           "**CAB:** is the rollback real and rehearsed? **Ops:** health, alerts, runbook, batch schedule. **Business Owner:** is the coexistence position (which side is the system of record for which context) what you agreed?",
                           "A go-live on a development deployment is not a go-live. This gate records that the stack runs and can be demonstrated; it must not be read as production readiness unless the readiness row is green.",
                           [("Production readiness", "none" if not ready else "medium", "dev profile only" if not ready else "see prod-readiness.json", "qa/prod profiles, IaC, pipeline, scans"), ("Operational behaviour under failure", "low", "no runbooks supplied from the legacy", "Ops design")],
                           ["Real batch window and response-time figures."], rows, *manifest(ws, arts), "`docker-compose.yml`, `8-deploy/cutover-plan.md`, `8-deploy/runbook.md`.")
    write(os.path.join(ws.gate_dir(a.gate), "review-pack.md"), pack)
    # propose_gate needs the same rows and manifest; recompute quickly
    mani, mh = manifest(ws, arts); status = propose_gate(ws, a.gate, mh, mani, rows, extra=dict(scope=a.wave))
    print("%s %s %s | red rows %d | %s" % (a.gate, status, mh[:16], sum(1 for r in rows if r[3] is False), "; ".join("%s=%s" % (r[0][:28], "🟢" if r[3] else ("🔴" if r[3] is False else "—")) for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
