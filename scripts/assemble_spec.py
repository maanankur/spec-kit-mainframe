#!/usr/bin/env python3
"""
assemble_spec.py -- stitch the phase-2 artifacts into spec.md, coverage-report.md
and the Gate 1 review pack, and propose G1 in state.json.

Inputs (all produced earlier; this script computes nothing about the COBOL):
  2-specification/business-rules.jsonl, traceability.json, merge-report.json   (merge_fragments.py --write)
  2-specification/_fragments/plan.json, WP*/spec-section.md, WP*/notes.md
  2-specification/spec-front-matter.md    written by the agent from templates/spec-front-matter.md
  2-specification/*.md                    optional cross-cutting recoveries (screen-flow, batch-topology, discovery-corrections)
  1-discovery/inventory.json, 0-intake/gap-list.md, modernization.config.yaml

Outputs: 2-specification/spec.md, coverage-report.md; governance/gates/G1/{review-pack.md,manifest.json}; state.json G1 = proposed.

Usage: assemble_spec.py --workspace <out-dir> [--allow-incomplete]
Refuses to propose G1 unless trace coverage meets thresholds.trace_coverage with zero errors.
"""
import argparse, glob, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import WS, NOW, read, write, jload, jsonl, manifest, md, render_pack, propose_gate

HERE = os.path.dirname(os.path.abspath(__file__))
CROSS = [("screen-flow.md", "transaction → program → next program, from the dispatch tables and BMS maps"), ("batch-topology.md", "the real job graph from the JCL and scheduler exports"),
         ("discovery-corrections.md", "defects found in the phase-1 deterministic outputs and how they were fixed; read it to understand why numbers changed"), ("use-cases.jsonl", "one row per use case (id, name, context, rules) — the basis of the use-case coverage gate at G5")]


def section(front, title):
    m = re.search(r"^##\s+\d*\.?\s*%s\s*\n(.*?)(?=^## |\Z)" % re.escape(title), front, re.S | re.M)
    return m.group(1).strip() if m and m.group(1).strip() else None


def ev(e):
    if e.get("file"): return "`%s` %s" % (e["file"], e.get("lines", ""))
    return "%s:%s:%s" % (e.get("program", "?"), e.get("paragraph", "?"), "-".join(str(x) for x in (e.get("lines") or [])))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--allow-incomplete", action="store_true")
    a = ap.parse_args(); ws = WS(a.workspace)
    rules = jsonl(os.path.join(ws.SPEC, "business-rules.jsonl")); merge = jload(os.path.join(ws.SPEC, "merge-report.json"), {})
    plan = jload(os.path.join(ws.FRAG, "plan.json"), {"packages": []}); wps = [p["id"] for p in plan["packages"]] or sorted(os.path.basename(d) for d in glob.glob(os.path.join(ws.FRAG, "WP*")))
    inv = jload(os.path.join(ws.DISC, "inventory.json"), {"summary": {}, "items": {}}); S = inv.get("summary", {})
    tc = subprocess.run([sys.executable, os.path.join(HERE, "trace_coverage.py"), "--source", ws.source, "--traceability", os.path.join(ws.SPEC, "traceability.json"),
                         "--rules", os.path.join(ws.SPEC, "business-rules.jsonl"), "--json"], capture_output=True, text=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"), encoding="utf-8")
    out = tc.stdout
    if "{" not in out: print("trace_coverage.py produced no JSON (rc %d): %s %s" % (tc.returncode, out[-400:], tc.stderr[-800:])); return 1
    trace = json.loads(out[out.index("{"):])
    threshold = float(ws.cfg.get("thresholds", {}).get("trace_coverage", 100))
    conf = {c: sum(1 for r in rules if r.get("confidence") == c) for c in ("high", "medium", "low")}
    questions = [r for r in rules if r.get("open_question")]; defects = [r for r in rules if r.get("suspected_defect")]
    by = {}
    for p in trace["per_program"]:
        for k in ("implemented", "not_applicable", "delegated", "dropped"): by[k] = by.get(k, 0) + p.get(k, 0)
    errors = [f for f in trace["findings"] if f["severity"] == "error"]; complete = trace["coverage_pct"] >= threshold and not errors
    if not complete and not a.allow_incomplete:
        print("REFUSED: trace coverage %.2f%% (threshold %.0f%%), %d error(s). Fix them or pass --allow-incomplete for a draft." % (trace["coverage_pct"], threshold, len(errors))); return 1
    front = read(os.path.join(ws.SPEC, "spec-front-matter.md"))
    purpose, nfr, oos = section(front, "Purpose"), section(front, "Non-functional requirements"), section(front, "Explicitly out of scope")
    kinds = ", ".join("%d %s" % (v, k) for k, v in sorted(S.get("program_kinds", {}).items()))
    scope = "%s COBOL programs (%s), %s copybooks, %s JCL members, %s BMS mapsets, %s data stores" % (S.get("programs", "?"), kinds, S.get("copybooks", "?"), S.get("jcl_members", "?"), S.get("bms_mapsets", "?"), S.get("distinct_data_stores", "?"))
    reg = jload(os.path.join(ws.INTAKE, "artifact-register.json"), {"artifacts": []})
    present_cross = [(f, d) for f, d in CROSS if os.path.exists(os.path.join(ws.SPEC, f))]

    L = ["# Specification — %s\n" % ws.project, "> Recovered from legacy source. Proposed for **Gate 1** (business understanding) — %s." % ", ".join(ws.approvers("G1")),
         "> **Read Part III (Decisions needed) first** — that is what needs your decision.\n", "| | |\n|---|---|",
         "| Source | `%s` — %d registered artifacts, SHA-256 in `0-intake/artifact-register.json` |" % (ws.source, len(reg["artifacts"])), "| Scope | %s |" % scope,
         "| Traceability | **%d/%d paragraphs accounted for (%.2f%%)** — implemented %d · not-applicable %d · delegated %d · dropped %d |" % (trace["accounted"], trace["paragraphs"], trace["coverage_pct"], by.get("implemented", 0), by.get("not_applicable", 0), by.get("delegated", 0), by.get("dropped", 0)),
         "| Rules recovered | **%d** (high %d / medium %d / low %d confidence) |" % (len(rules), conf["high"], conf["medium"], conf["low"]), "| Open questions | **%d** |" % len(questions), "| Suspected legacy defects | **%d** |" % len(defects),
         "| Assembled | %s by `assemble_spec.py` from %d work-package fragments |\n" % (NOW, len(wps)), "---\n", "## 1. Purpose\n", (purpose or "_spec-front-matter.md has no Purpose section — write it before G1_") + "\n",
         "## 2. How to read this document\n", "Part II holds one section per business domain, each with its own vocabulary, data, processes, rules, screens and batch. Cross-cutting recoveries are separate files and are part of this specification:\n"]
    L += ["- `%s` — %s." % (f, d) for f, d in present_cross]
    L += ["- `coverage-report.md` — the paragraph-level accounting behind the traceability figure above.", "- `business-rules.jsonl` / `traceability.json` — the machine-readable record; every rule below is a row there.\n", "---\n\n# Part II — Domains\n"]
    for wp in wps:
        sec = read(os.path.join(ws.FRAG, wp, "spec-section.md"))
        L.append(("<!-- %s -->\n\n" % wp) + sec.strip() + "\n" if sec.strip() else "## _%s — section missing_\n" % wp)
    L += ["---\n\n# Part III — Decisions needed\n", "## Open questions — DECISIONS NEEDED AT G1\n", "Each question is genuine: the source is ambiguous, or the intent is unrecoverable, or it is a business decision. Nothing here was answered by guessing.\n",
          "| # | Rule | Domain | Question | Confidence | Evidence | Answer |\n|---|---|---|---|---|---|---|"]
    L += ["| Q%d | %s | %s | %s | %s | %s | |" % (i, r["id"], md(r.get("domain", "")), md(r["open_question"]), r.get("confidence", ""), "; ".join(ev(e) for e in r["evidence"][:2])) for i, r in enumerate(sorted(questions, key=lambda x: x["id"]), 1)]
    L += ["\n### Suspected legacy defects — PRESERVE OR FIX?\n", "Each is specified **as it behaves** in the rule cited. Fixing one is a specified change with its own test, decided here — never a quiet correction, because the golden-master comparison depends on the legacy output.\n",
          "| # | Rule | Domain | Behaviour as specified | Why it looks wrong | Evidence | Preserve / fix |\n|---|---|---|---|---|---|---|"]
    L += ["| D%d | %s | %s | %s | %s | %s | |" % (i, r["id"], md(r.get("domain", "")), md(r["statement"]), md(r["suspected_defect"]), "; ".join(ev(e) for e in r["evidence"][:2])) for i, r in enumerate(sorted(defects, key=lambda x: x["id"]), 1)]
    L += ["\n### Hazards, dead-code candidates and parser gaps (from the work-package notes)\n"]
    for wp in wps:
        n = read(os.path.join(ws.FRAG, wp, "notes.md"))
        if n.strip(): L.append("<details><summary><b>%s notes</b></summary>\n\n%s\n\n</details>\n" % (wp, n.strip()))
    L += ["## Non-functional requirements\n", (nfr or "_spec-front-matter.md has no NFR section — state what is known and what is assumed_") + "\n", "## Explicitly out of scope\n", (oos or "_spec-front-matter.md has no out-of-scope section_") + "\n"]
    write(os.path.join(ws.SPEC, "spec.md"), "\n".join(L))

    C = ["# Traceability coverage report\n", "Computed %s by `trace_coverage.py` (re-derives paragraph names from the COBOL; does not trust inventory.json).\n" % NOW,
         "**Coverage: %.2f%% — %d/%d paragraphs accounted for. %d error(s). Threshold %.0f%%.**\n" % (trace["coverage_pct"], trace["accounted"], trace["paragraphs"], len(errors), threshold),
         "The identity enforced: every paragraph == implemented + not-applicable + delegated + dropped. `implemented` cites ≥1 rule; `not-applicable`/`delegated` carry a reason; `dropped` requires a named approver.\n",
         "| Program | Paragraphs | Accounted | Coverage | Implemented | N/A | Delegated | Dropped | Rules citing |", "|---|---|---|---|---|---|---|---|---|"]
    cite = {}
    for r in rules:
        for e in r["evidence"]: cite[e.get("program", "").upper()] = cite.get(e.get("program", "").upper(), 0) + 1
    C += ["| %s | %d | %d | %.1f%% | %s | %s | %s | %s | %d |" % (p["program"], p["paragraphs"], p["accounted"], p["coverage"], p.get("implemented", "-"), p.get("not_applicable", "-"), p.get("delegated", "-"), p.get("dropped", "-"), cite.get(p["program"], 0)) for p in sorted(trace["per_program"], key=lambda x: x["program"])]
    for title, sev in (("Errors", "error"), ("Warnings", "warning")):
        fs = [f for f in trace["findings"] if f["severity"] == sev]
        if fs: C += ["\n## %s\n" % title] + ["- %s %s — %s" % (f.get("program", ""), f.get("paragraph", ""), f["message"]) for f in fs]
    mw = [f for f in merge.get("findings", []) if f["severity"] == "warning"]
    if mw: C += ["\n## Merge-validator warnings (%d)\n" % len(mw)] + ["- [%s] %s" % (f.get("work_package", "-"), f["message"]) for f in mw[:80]]
    write(os.path.join(ws.SPEC, "coverage-report.md"), "\n".join(C) + "\n")

    arts = [os.path.join(ws.SPEC, f) for f in ["spec.md", "business-rules.jsonl", "traceability.json", "coverage-report.md"] + [f for f, _ in present_cross]]
    mani, mh = manifest(ws, arts); low_med = [r for r in rules if r.get("confidence") in ("low", "medium")]
    gap = [l for l in read(os.path.join(ws.INTAKE, "gap-list.md")).splitlines() if l.startswith("|") and "Missing input" not in l and "---" not in l]
    least = [("%s — %s" % (r["id"], r["statement"][:90]), r["confidence"], r.get("open_question") or "ambiguous source; see rule", "BA / SME confirmation; " + "; ".join(ev(e) for e in r["evidence"][:1])) for r in low_med[:25]]
    if len(low_med) > 25: least.append(("… and %d more medium/low-confidence rules" % (len(low_med) - 25), "", "see spec.md Part III", ""))
    could_not = ["**%d open questions** (spec.md Part III) — each names who can answer it." % len(questions), "**Client inputs still missing** — from the intake gap list; Gate 1 is weaker without them:"] + ["  " + l for l in gap]
    if os.path.exists(os.path.join(ws.SPEC, "discovery-corrections.md")): could_not.append("**Deterministic-plane corrections** — phase-1 outputs found wrong during this phase are listed in `discovery-corrections.md`; the numbers in this pack come from the corrected run.")
    could_not.append("**Static reachability only** unless execution telemetry was supplied — dead-code candidates in the notes are unproven.")
    evid = [("Traceability coverage", "%.2f%% (%d/%d), %d errors" % (trace["coverage_pct"], trace["accounted"], trace["paragraphs"], len(errors)), "%.0f%%, 0 errors" % threshold, complete),
            ("Unsourced rules", "0 (every rule carries evidence; validated by merge_fragments.py)", "0", True), ("Rules with an open question", str(len(questions)), "reported", None),
            ("Suspected defects flagged, not fixed", str(len(defects)), "all flagged", None), ("Source tree integrity", "run verify_source_readonly.py before deciding", "byte-identical", None),
            ("Paragraphs dropped", str(by.get("dropped", 0)), "0 without a named approver", by.get("dropped", 0) == 0)]
    pack = render_pack(ws, "G1", "confirm that `spec.md` describes what %s actually does — every rule, every edge case, in the business's words — well enough to build a new system from it without consulting the COBOL." % ws.project,
                       "Three questions. **Business Analyst:** are the %d rules right, is the vocabulary right, do the edge cases match how the business works? **Product Owner:** for each of the %d suspected legacy defects, preserve or fix; are the %d open questions answered; is anything the business cares about missing? **Architect:** is the traceability genuinely complete (%d/%d paragraphs, %.2f%%), are the non-functional numbers real or assumed, does every hazard have an owner?" % (len(rules), len(defects), len(questions), trace["accounted"], trace["paragraphs"], trace["coverage_pct"]),
                       "Everything downstream is generated from this document. A rule approved wrongly here is generated into the Java in Phase 6, and the golden-master tests in Phase 7 will then confirm — correctly — that the Java faithfully implements the wrong rule. A paragraph misclassified as housekeeping is logic that silently disappears. This is the most expensive gate to get wrong and the cheapest to get right.",
                       least, could_not, evid, mani, mh, "`spec.md`: the specification, Part II per domain, Part III decisions. `business-rules.jsonl`: %d rules. `traceability.json`: every paragraph classified. `coverage-report.md`: the accounting.%s" % (len(rules), "".join(" `%s`: %s." % (f, d) for f, d in present_cross)))
    write(os.path.join(ws.gate_dir("G1"), "review-pack.md"), pack)
    status = propose_gate(ws, "G1", mh, mani, evid) if complete else "DRAFT (state.json untouched)"
    print("rules %d | questions %d | defects %d | coverage %.2f%% | G1 %s %s" % (len(rules), len(questions), len(defects), trace["coverage_pct"], status, mh[:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
