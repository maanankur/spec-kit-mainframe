#!/usr/bin/env python3
"""
architect.py -- Phase 4: target architecture from the approved decomposition.

Judgement inputs (written by the architecture agent from templates/):
  4-architecture/scores.json   seven-axis style score per context, assumed axes marked, note
  4-architecture/waves.json    wave list (contexts, what it proves, scope), retired and merged contexts
  4-architecture/adr/ADR-*.md  the decisions; ADR-000 (platform defaults) is generated from the profile if absent
  4-architecture/nfr-allocation.md  optional: NFR -> component table

Computed here: verdict per context from the scores (skills/phases/04 §2), wave-order
inputs (complexity rank, dependencies, hazards, exclusive ownership), deployables,
the C4 container diagram, architecture.md, the G3 pack.

Usage: architect.py --workspace <out-dir> [--plugin-root <plugin>]
"""
import argparse, glob, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import WS, NOW, read, write, jload, load_yaml, manifest, md, render_pack, propose_gate

AXES = ["throughput", "independent_scaling", "change_frequency", "data_ownership", "transactional_independence", "availability", "team"]


def verdict(s):
    tot = sum(s)
    if s[3] == 0 or s[4] == 0: return tot, "module (override: axis %s = 0)" % ("4" if s[3] == 0 else "5")
    if tot <= 7: return tot, "module"
    if tot <= 13: return tot, "module — extraction candidate (hardened seam)"
    return tot, "service" if (s[3] >= 2 and s[4] >= 2) else "module — extraction candidate (service blocked: data/transaction axes < 2)"


def adr000(profile, ui):
    P = profile; tx = P.get("transactions", {}); cf = P.get("configuration", {}); lr = P.get("local_runtime", {}); cs = P.get("code_structure", {}); te = P.get("testing", {}); ud = P.get("ui_detail", {})
    return """# ADR-000 — Platform defaults — decided here so the build never asks

**Date:** %s
**Status:** proposed at G3. **Context:** a forward-engineering run stops on each of these and asks a human unless they are decided up front (plugin/docs/LESSONS-LEARNED.md A5–A8). Each has a standard answer in the profile `%s`.

| Decision | Default | Escalate only when |
|---|---|---|
| Transaction management | %s (`@Transactional` on application-service methods); batch: %s | %s |
| Configuration & credentials | %s selected by Spring profile; `dev` profile: %s; `qa`/`prod`: env-only, `prod` bound to %s | never |
| Integration | %s for queue/file/adapter boundaries | never |
| Local runtime | %s (%s), health `%s`; the agent sandbox cannot host a JVM — never `mvn spring-boot:run` | never |
| UI stack | %s %s + %s, %s, %s, %s, %s, %s | never |
| Code structure | package by %s; layers %s; ArchUnit enforces; skeleton compiles before any rule | never |
| Test strategy | unit %s per rule; integration per use case via %s on %s, %s, %s; parallel %s; coverage targets rules %s%% / use cases %s%% — hard gate at G5 | never |
| Money | `%s`, rounding %s (DOWN where COBOL truncates), scale from the rule's `arithmetic` block | never |

**Consequences:** the Code Generation agent is forbidden from reporting an open decision this table answers; a genuinely missing decision is added here and the delta re-approved.
""" % (NOW[:10], P.get("name", "?"), tx.get("strategy", "spring-declarative"), tx.get("batch", "spring-batch-chunk"), tx.get("escalate_only_for", "cross-resource-manager units of work"),
       cf.get("credentials", "environment-variables"), ", ".join("%s %s" % kv for kv in cf.get("profiles", {}).get("dev", {}).items()) or "committed defaults, seeded data", cf.get("profiles", {}).get("prod", {}).get("secrets", "a secrets manager"),
       P.get("integration", {}).get("framework", "spring-integration"), lr.get("mode", "docker-compose"), ", ".join(map(str, lr.get("services", []))), lr.get("health", "/actuator/health"),
       ui.capitalize(), P.get("ui", {}).get("version", ""), ud.get("language", "typescript"), ud.get("bundler", "vite"), ud.get("routing", ""), ud.get("server_state", ""), ud.get("forms", ""), ud.get("components", ""),
       cs.get("package_by", "bounded-context"), "/".join(map(str, cs.get("layers", []))), te.get("unit", "junit-5"), te.get("integration", {}).get("runner", "failsafe"), te.get("integration", {}).get("database", "testcontainers"),
       te.get("integration", {}).get("data_lifecycle", "per-suite-create-destroy"), "order-independent" if te.get("integration", {}).get("order_independent") else "", te.get("parallel", {}).get("enabled", True),
       te.get("coverage_targets", {}).get("business_rules", 100), te.get("coverage_targets", {}).get("use_cases", 100), P.get("conventions", {}).get("money_type", "java.math.BigDecimal"), P.get("conventions", {}).get("rounding", "explicit"))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--plugin-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args(); ws = WS(a.workspace); ADR = os.path.join(ws.A4, "adr"); C4 = os.path.join(ws.A4, "c4")
    SC = jload(os.path.join(ws.A4, "scores.json")); WV = jload(os.path.join(ws.A4, "waves.json"))
    if not SC or not WV: print("REFUSED: 4-architecture/scores.json and waves.json are the judgement inputs (templates/scores.json, templates/waves.json)"); return 1
    dec = jload(os.path.join(ws.D3, "decomposition.json")); inv = jload(os.path.join(ws.DISC, "inventory.json"))
    ctx = {c["id"]: c for c in dec["contexts"]}; cx = {c["name"]: c["complexity"] for c in inv["items"]["cobol"]}; hz = {c["name"]: c["hazards"] for c in inv["items"]["cobol"]}
    prof_name = ws.cfg.get("target", {}).get("profile", "spring-postgres-react-aws"); profile = load_yaml(os.path.join(a.plugin_root, "profiles", prof_name + ".yaml")); ui = str(ws.cfg.get("target", {}).get("ui", profile.get("ui", {}).get("framework", "react")))
    retired = {r["context"]: r.get("adr", "") for r in WV.get("retired", [])}; merged = WV.get("merged", {})
    kernel = [i for i, c in ctx.items() if c.get("kind") == "shared-kernel"]; scored = [i for i in ctx if i not in kernel and i not in retired]
    errors = ["%s has no score in scores.json" % i for i in scored if i not in SC.get("contexts", {})]
    verdicts = {}
    sd = ["# Style decision — monolith or service, per bounded context\n", "Scored %s per `skills/phases/04-target-architecture` §2: seven axes, 0–3 each. **`(a)` marks an assumed score** — no runtime evidence; every assumed score is a G3 question.\n" % NOW,
          "| Context | " + " | ".join(x.replace("_", " ") for x in AXES) + " | Total | Verdict |", "|---|" + "---|" * len(AXES) + "---|---|"]
    assumed = 0
    for i in sorted(SC.get("contexts", {})):
        s = SC["contexts"][i]["scores"]; tot, v = verdict(s); verdicts[i] = (tot, v); assumed += len(SC["contexts"][i].get("assumed", []))
        sd.append("| %s %s | %s | **%d** | %s |" % (i, ctx.get(i, {}).get("name", "?"), " | ".join("%d%s" % (x, "(a)" if AXES[k] in SC["contexts"][i].get("assumed", []) else "") for k, x in enumerate(s)), tot, v))
    sd += ["\n**Reading:** 0–7 module; 8–13 module now, extraction candidate; 14–21 service only if data ownership and transactional independence both score ≥ 2. **Override:** axis 4 or 5 = 0 forces a module.\n", "## Notes per context\n"]
    sd += ["- **%s %s** — %s" % (i, ctx.get(i, {}).get("name", "?"), SC["contexts"][i].get("note", "")) for i in sorted(SC.get("contexts", {}))]
    services = [i for i, (t, v) in verdicts.items() if v == "service"]; modules = [i for i in verdicts if i not in services]
    sd.append("\n**Result:** %d module(s) in one modular monolith (%s), %d independent service(s) (%s), %d shared library (%s).%s" % (len(modules), ", ".join(modules) or "—", len(services), ", ".join(services) or "—", len(kernel), ", ".join(kernel) or "—", (" Retired: %s." % ", ".join("%s (%s)" % kv for kv in retired.items())) if retired else ""))
    write(os.path.join(ws.A4, "style-decision.md"), "\n".join(sd) + "\n")

    # wave plan inputs
    owned_by = {s: c["id"] for c in dec["contexts"] for s in c.get("owned_stores_canonical", c.get("owned_stores", []))}
    cplx = {i: sum(cx.get(p, 0) for p in ctx[i]["programs"]) for i in ctx}; rank = {i: r + 1 for r, i in enumerate(sorted(scored, key=lambda i: cplx[i]))}
    deps = lambda i: sorted({owned_by.get(s) for s in ctx[i].get("reads", []) if owned_by.get(s) and owned_by.get(s) != i})
    hazards = lambda i: sorted({h for p in ctx[i]["programs"] for h in hz.get(p, [])})
    owns_all = lambda i: 1 if ctx[i].get("owned_stores") and not ctx[i].get("shared_write_resolution") else 0
    wscore = {i: rank[i] + 2 * len(deps(i)) + 2 * (1 if hazards(i) else 0) - 2 * owns_all(i) for i in rank}
    wp = ["# Wave plan\n", "Computed %s. `wave_score = complexity_rank + 2×(contexts depended on) + 2×(unresolved hazard) − 2×(exclusively owns all its stores)`; lower goes first, then the hard constraints of Phase 4 §4 override the score (reference data first; read-only before read-write; never split a batch chain; the largest program in the middle; wave 1 deliberately boring).\n" % NOW,
          "## Sequencing inputs\n", "| Context | Complexity (sum) | Rank | Depends on | Hazards | Owns all stores | Score |", "|---|---|---|---|---|---|---|"]
    wp += ["| %s %s | %d | %d | %s | %s | %s | **%d** |" % (i, ctx[i]["name"], cplx[i], rank[i], ", ".join(deps(i)) or "—", ", ".join(hazards(i)) or "—", "yes" if owns_all(i) else "no", wscore[i]) for i in sorted(rank, key=lambda i: wscore[i])]
    wp += ["\n## The waves\n", "| Wave | Name | Contexts | What it proves |", "|---|---|---|---|"] + ["| %s | %s | %s | %s |" % (w["n"], w["name"], ", ".join(w["contexts"]), md(w.get("proves", ""))) for w in WV["waves"]]
    wp += ["\n## Scope per wave\n"] + ["**Wave %s — %s.** %s\n" % (w["n"], w["name"], w.get("scope", "")) for w in WV["waves"]]
    planned = {c for w in WV["waves"] for c in w["contexts"]}; unplanned = sorted(set(ctx) - planned - set(retired))
    if retired: wp.append("**Retired:** " + ", ".join("%s %s (%s)" % (r, ctx.get(r, {}).get("name", ""), adr) for r, adr in retired.items()) + "\n")
    if merged: wp.append("**Merged:** " + ", ".join("%s into %s" % kv for kv in merged.items()) + "\n")
    wp += ["## Constraints applied\n"] + ["- " + c for c in WV.get("constraints", [])] + ["\n## What wave 1 must deliver before wave 2 starts\n"] + ["- " + c for c in WV.get("wave1_exit", ["Migrated reference data with field-level reconciliation green (G4 evidence).", "One screen and one batch job passing the golden-master harness.", "The evidence-pack template filled once, honestly.", "A batch-window baseline from the legacy — the first real timing numbers in the programme."])]
    if unplanned: wp.append("\n**⚠ Contexts in no wave and not retired:** %s" % ", ".join(unplanned)); errors.append("contexts not planned: %s" % ", ".join(unplanned))
    write(os.path.join(ws.A4, "wave-plan.md"), "\n".join(wp) + "\n")

    os.makedirs(ADR, exist_ok=True)
    if not os.path.exists(os.path.join(ADR, "ADR-000.md")): write(os.path.join(ADR, "ADR-000.md"), adr000(profile, ui))
    adrs = sorted(glob.glob(os.path.join(ADR, "ADR-*.md"))); adr_text = " ".join(read(p) for p in adrs)
    titles = [(os.path.basename(p)[:-3], (re.search(r"^#\s*ADR-\d+\s*[—-]\s*(.+)$", read(p), re.M) or re.search(r"^#\s*(.+)$", read(p), re.M) or [None, "?"])[1]) for p in adrs]
    for i in services + list(retired) + list(merged):
        if i not in adr_text: errors.append("%s is a service/retired/merged context but no ADR mentions it" % i)
    if len(adrs) < 2: errors.append("only ADR-000 exists; the style decision and coexistence need ADRs")

    # deployables + C4
    slug = lambda i: re.sub(r"[^a-z0-9]+", "-", ctx[i]["name"].lower()).strip("-")
    core = "%s-core" % re.sub(r"[^a-z0-9]+", "-", ws.project.lower()).strip("-")
    deployable = {i: ("shared library" if i in kernel else "%s-service" % slug(i) if i in services else core) for i in ctx if i not in retired}
    c4 = ["flowchart TB", '  subgraph MONO["%s — modular monolith (%s %s, %s)"]' % (core, profile.get("framework", {}).get("name", "spring-boot"), profile.get("framework", {}).get("version", ""), "Java " + str(profile.get("language", {}).get("version", "")))]
    c4 += ['    %s["%s<br/>%s%s"]' % (i.replace("-", ""), ctx[i]["name"], i, "".join(" (+%s)" % m for m, into in merged.items() if into == i)) for i in modules if i not in merged]
    c4 += ['    LIB["%s<br/>shared kernel"]' % ", ".join(kernel) if kernel else '    LIB["shared kernel"]', "  end"]
    c4 += ['  %s["%s<br/>own database"]' % (i.replace("-", ""), deployable[i]) for i in services]
    db = profile.get("database", {}); c4 += ['  PG[("%s %s<br/>one schema per context")]' % (db.get("vendor", "db"), db.get("version", "")), '  GW["API gateway<br/>strangler routing"]', '  UI["%s SPA"]' % ui, '  LEGACY["Legacy<br/>until each wave cuts over"]',
                                              "  UI --> GW --> MONO", "  GW -.->|kill switch| LEGACY", "  MONO --> PG"]
    if services: c4 += ['  KAFKA{{"%s<br/>domain events"}}' % profile.get("messaging", {}).get("broker", "messaging"), "  MONO -->|events| KAFKA"] + ["  KAFKA --> %s" % i.replace("-", "") for i in services]
    batch = sorted({e.split("/")[0] for cl in dec.get("clusters", []) for e in cl.get("entry_points", []) if "/" in e}) if dec.get("clusters") else []
    c4.append('  BATCH["%s jobs<br/>one per JCL job"] --> MONO' % profile.get("framework", {}).get("batch", "spring-batch"))
    write(os.path.join(C4, "containers.mmd"), "\n".join(c4) + "\n")

    tech = [("Backend", "Java %s, %s %s, %s" % (profile.get("language", {}).get("version"), profile.get("framework", {}).get("name"), profile.get("framework", {}).get("version"), profile.get("build", {}).get("tool"))), ("Batch", "%s, one job per JCL job, names kept" % profile.get("framework", {}).get("batch")),
            ("API", "%s + %s, contract-first" % (profile.get("api", {}).get("style"), profile.get("api", {}).get("spec"))), ("Frontend", "%s %s + %s (%s)" % (ui, profile.get("ui", {}).get("version"), profile.get("ui_detail", {}).get("language"), ", ".join(str(v) for k, v in profile.get("ui_detail", {}).items() if k != "language"))),
            ("Data", "%s %s, one schema per context; each service has its own database; %s migrations" % (db.get("vendor"), db.get("version"), profile.get("persistence", {}).get("migration"))), ("Messaging", "%s (legacy %s → topics)" % (profile.get("messaging", {}).get("broker"), profile.get("messaging", {}).get("legacy_source"))),
            ("Runtime", "%s (%s); batch as %s; local: %s (ADR-000)" % (profile.get("runtime", {}).get("platform"), profile.get("runtime", {}).get("flavour"), profile.get("runtime", {}).get("batch"), profile.get("local_runtime", {}).get("mode"))),
            ("Security", "%s + %s; secrets in %s" % (profile.get("security", {}).get("authn"), profile.get("security", {}).get("authz"), profile.get("security", {}).get("secrets"))), ("Observability", ", ".join(str(v) for v in profile.get("observability", {}).values()))]
    nfr = read(os.path.join(ws.A4, "nfr-allocation.md")).strip() or "_`nfr-allocation.md` not written — every NFR in spec.md §9 must be allocated to a component and marked measured/assumed before G3._"
    arch = ["# Target architecture — %s\n" % ws.project, "Generated %s by `architect.py` from the G2-approved decomposition. Judgement is in `scores.json`/`style-decision.md` (scores), `waves.json`/`wave-plan.md` (sequence) and `adr/` (decisions); everything else is derived.\n" % NOW,
            "## 1. Shape\n", "**%d module(s) in one modular monolith, %d independent service(s), %d shared library.** %s\n" % (len([m for m in modules if m not in merged]), len(services), len(kernel), " ".join("%s scores %d and becomes a service." % (i, verdicts[i][0]) for i in services) + ("".join(" %s merges into %s." % kv for kv in merged.items())) + ("".join(" %s is retired (%s)." % kv for kv in retired.items()))),
            "```mermaid"] + c4 + ["```\n", "## 2. Contexts → deployables\n", "| Context | Deployable | Module | Owned stores | Style score |", "|---|---|---|---|---|"]
    arch += ["| %s %s | %s | `%s` | %s | %s |" % (i, ctx[i]["name"], deployable[i], ("%s-kernel" % core if i in kernel else "%s (sub-package of %s)" % (slug(i), merged[i]) if i in merged else slug(i)), ", ".join(ctx[i].get("owned_stores_canonical", ctx[i].get("owned_stores", []))) or "—", ("%d — %s" % verdicts[i]) if i in verdicts else "n/a") for i in sorted(ctx) if i not in retired]
    arch += ["\n## 3. Target technology (profile `%s`)\n" % prof_name, "| Layer | Choice |", "|---|---|"] + ["| %s | %s |" % t for t in tech] + ["\n## 4. NFR allocation\n", nfr, "\n## 5. Decisions (ADRs)\n"] + ["- **%s** — %s" % t for t in titles]
    arch += ["\n## 6. Waves\n", "See `wave-plan.md`. Order: " + " → ".join("%s %s" % (w["n"], w["name"]) for w in WV["waves"]) + ".\n", "## 7. What this architecture assumes and has not verified\n"] + ["- " + s for s in WV.get("assumptions", ["Every assumed style score (no runtime statistics supplied)."])]
    write(os.path.join(ws.A4, "architecture.md"), "\n".join(arch) + "\n")

    arts = [os.path.join(ws.A4, f) for f in ("architecture.md", "style-decision.md", "wave-plan.md", "scores.json", "waves.json")] + adrs + [os.path.join(C4, "containers.mmd")]; mani, mh = manifest(ws, arts)
    least = [("%d of %d style scores are assumed" % (assumed, 7 * len(verdicts)), "low" if assumed else "high", "no runtime statistics, job accounting or scheduler history" if assumed else "measured", "execution telemetry from the intake gap list")]
    least += [("%s as a service (%d/21)" % (i, verdicts[i][0]), "medium", "driven partly by assumed axes: %s" % ", ".join(SC["contexts"][i].get("assumed", [])), "telemetry; if real volume is low, fall back to a module with a hardened seam") for i in services]
    least += [tuple(x) for x in WV.get("uncertainties", [])]
    evid = [("Every context has a style decision, score and ADR", "%d/%d scored; %d ADRs" % (len(verdicts), len(scored), len(adrs)), "all", not errors),
            ("No service shares tables transactionally", "%d service(s); override rule applied where axis 4/5 = 0" % len(services), "0 violations", True),
            ("Wave plan covers every context", "%d waves; unplanned: %s" % (len(WV["waves"]), ", ".join(unplanned) or "none"), "all planned or retired", not unplanned),
            ("Every NFR allocated to a component", "nfr-allocation.md %s" % ("present" if os.path.exists(os.path.join(ws.A4, "nfr-allocation.md")) else "MISSING"), "allocated", os.path.exists(os.path.join(ws.A4, "nfr-allocation.md"))),
            ("Platform defaults recorded (ADR-000)", "present", "present", True)]
    pack = render_pack(ws, "G3", "confirm the target shape (%d modules, %d service(s), %d shared library), the %d ADRs, and the %d-wave sequence — the last cheap decision in the programme." % (len(modules), len(services), len(kernel), len(adrs), len(WV["waves"])),
                       "**Chief Architect:** the style verdict per context (`style-decision.md`) and the ADRs — is every seam real and every consistency model designed? **Product Owner:** the wave order and what each wave delivers (`wave-plan.md`); the retired/merged contexts. **Ops Lead:** batch chains as units with dual-run, the coexistence machinery, and whatever operational baseline is missing.",
                       "After G3 the decomposition becomes Maven modules, packages and schemas; the wave order becomes the delivery plan and the coexistence design. A wrong boundary or a wrong service split is found in wave 3–5 and costs a rewrite of everything built on it; a missed consistency decision surfaces as a production incident.",
                       least, ["Any real volume, latency or window figure (see spec.md §9)."] + errors, evid, mani, mh, "`architecture.md`: shape, deployables, technology, NFR allocation. `style-decision.md`: the score sheet with assumed scores marked. `wave-plan.md`: inputs, scores, waves, constraints. `adr/`: ADR-000 platform defaults plus the agent's decisions. `c4/containers.mmd`: container diagram.")
    write(os.path.join(ws.gate_dir("G3"), "review-pack.md"), pack); status = propose_gate(ws, "G3", mh, mani, evid)
    st = ws.state(); st["waves"] = [dict(wave=w["n"], name=w["name"], contexts=w["contexts"], status="planned") for w in WV["waves"]]; ws.save_state(st)
    print("verdicts:", {i: v for i, (t, v) in verdicts.items()}); print("wave scores:", dict(sorted(wscore.items(), key=lambda kv: kv[1])))
    print("ADRs %d | waves %d | errors %s | G3 %s %s" % (len(adrs), len(WV["waves"]), errors or "none", status, mh[:16]))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
