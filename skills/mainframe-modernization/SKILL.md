---
name: mainframe-modernization
description: Modernize mainframe COBOL applications into cloud-native Java through a gated, evidence-driven pipeline - discovery, natural-language specification recovery, domain decomposition, target architecture with a monolith-vs-microservices decision, data modernization (copybooks/VSAM/DB2/IMS to SQL), forward engineering to Spring Boot and React/Angular, and golden-master equivalence verification. Use when working with COBOL, copybooks, CICS, BMS maps, JCL, VSAM, DB2, IMS, MQ, or any mainframe/legacy migration, reverse-engineering or assessment task. Triggers on "modernize COBOL", "COBOL to Java", "mainframe migration", "reverse engineer legacy", "convert copybook", "CICS to REST", "legacy assessment".
---

# Mainframe modernization - router

This is the L0 router. It holds the principles, the pipeline, the gates and the
loading table. Everything else loads on demand. **Do not preload phase or
technique skills** - 40 loaded skills produce worse output than 3 relevant ones.

## The four principles

1. **Humans approve intent. Machines verify fidelity.** A human never certifies
   generated code by reading it. They approve the *specification* and the
   *architecture*; equivalence is proven by the golden-master harness.
2. **The specification firewall.** Java is generated from the approved
   specification, never transliterated from COBOL. Enforced by tool denial.
3. **Deterministic before generative.** The judgement plane may not assert a fact
   the deterministic plane can compute. Run the parser; never estimate an offset.
4. **The knowledge graph is the system of record.** Every artifact is a
   projection of it, and carries traceability back to a node.

Read `rules/00-non-negotiables.md` once per session. The rules are hook-enforced;
a run that violates one stops rather than continuing quietly.

## Pipeline

| # | Phase | Agent tier | Gate at exit | Approvers |
|---|-------|-----------|--------------|-----------|
| 0 | Intake | understanding | - | - |
| 1 | Discovery | understanding | - | - |
| 2 | Specification recovery | understanding | **G1** business understanding | BA · Architect · Product Owner |
| 3 | Domain decomposition | understanding | **G2** boundaries | Architect · PO · Domain SMEs |
| 4 | Target architecture | design | **G3** architecture & waves | Chief Architect · PO · Ops |
| 5 | Data modernization | design | **G4** data model & migration | Data Architect · DBA · Compliance |
| 6 | Forward engineering (per wave) | build | **G5** build accepted | Tech Lead · Security |
| 7 | Verification (per wave) | assurance | **G6** equivalence accepted | PO · QA Lead · BA |
| 8 | Deployment & cutover | assurance | **G7** go-live | CAB · Ops · Business Owner |

G1-G4 happen once; G5-G6 repeat per wave. **G1-G3 are judgement gates** (blocking,
a human must read and think). **G4-G6 are evidence gates** (the machine has
already produced green/red; the human countersigns). A red evidence gate cannot be
approved - only waived, with a named owner, a compensating control and an expiry.

## The one command

Everything starts with `/modernize <cobol-app-path> [output-path]`. It bootstraps
the workspace, completes phases 0-1 deterministically via
`scripts/modernize.py`, then drives the lifecycle below, stopping at gates. The
granular commands (`/modernize-spec`, `/gate-approve`, `/trace`, ...) exist for
when someone wants to drive one step by hand; they are not the normal path.

Output defaults to a **sibling of the COBOL application in the same parent
directory**, named `<app>-modernized`. The source tree is opened read-only and is
never written to.

## Operating procedure

1. Read `modernization/state.json`. If absent, run `/modernize <path>`.
2. Verify the preceding gate is approved **and its artifact hashes still match**.
   A changed artifact voids its approval; say so and revert rather than proceeding.
3. Load that phase's L1 skill. Load L2 techniques only when their trigger appears.
4. Do the phase. Run the scripts; never hand-derive what a script computes.
5. Write artifacts, assert to the graph with `source_refs`, update `state.json`.
6. At a gate: produce the review pack, state plainly what the approver is deciding
   and what happens if they are wrong, then **stop**.

Between gates, work without asking permission.

## What to load, and when

| Trigger | Load |
|---------|------|
| Entering phase *n* | `skills/phases/0n-*` |
| `COMP-3`, `PIC S9(n)V99` | `techniques/packed-decimal-and-comp3` |
| `EXEC CICS` | `techniques/cics-to-rest` |
| `OCCURS ... DEPENDING ON`, `REDEFINES` | `techniques/occurs-depending-on-and-redefines` |
| BMS map or 3270 screen | `techniques/bms-to-modern-ui` |
| JCL job or PROC | `techniques/jcl-to-spring-batch` |
| VSAM cluster definition | `techniques/vsam-to-relational` |
| DBD / PSB | `techniques/ims-dli-to-jpa` |
| Any style decision at G3 | `techniques/monolith-vs-microservices` |
| Writing a target schema | `references/db2-to-<target>-types` |
| Building the equivalence harness | `techniques/golden-master-harness` |

## Agents

Dispatch rather than doing everything inline. `conductor` owns sequencing;
`discovery-agent`, `reverse-engineering-agent`, `domain-modeling-agent` and
`knowledge-graph-curator` own understanding; `architecture-agent`,
`data-modernization-agent` and `api-design-agent` own design;
`code-generation-agent`, `ui-generation-agent` and `test-generation-agent` own
build; `validation-agent`, `security-agent`, `compliance-agent` and
`deployment-agent` own assurance.

`code-generation-agent` and `ui-generation-agent` **cannot read COBOL**. That is
the specification firewall, and it is a permission, not a request.

## Workspace

Everything under `modernization/` in the target repo. `state.json` is the resume
point. Never write outside it.

## Scope honesty

State early what this does not do: it does not replace mainframe runtime testing at
production volume; it cannot recover intent that exists only in a retiring
engineer's head (ambiguity becomes an open question at G1, never an invented
answer); assembler, `ALTER` and `GO TO DEPENDING ON` are flagged for manual
treatment; and generated tests prove equivalence with *observed behaviour*, not
correctness - a faithfully converted bug is still a bug, and belongs on the G1
discovered-defect list rather than being silently fixed.

## Scripts per phase — the deterministic plane, and where judgement enters

Every phase has a generator in `scripts/`. It computes what can be computed, reads
the judgement from one named JSON file the agent writes, refuses to produce an
artifact it cannot validate, and proposes the gate bound to a manifest hash. Agents
never write gate packs, `state.json` or the merged artifacts by hand.

| Phase | Judgement input (agent writes) | Generator | Decides |
|---|---|---|---|
| 1 → 2 prep | — | `paragraph_skeleton.py`, `work_packages.py` (run by `modernize.py`) | — |
| 2 | `_fragments/WPn/{rules.jsonl,traceability.json,spec-section.md,notes.md}`, `spec-front-matter.md`, `use-cases.jsonl`, cross-cutting `*.md` | `merge_fragments.py --write`, `assemble_spec.py` | `gate_decide.py --gate G1` |
| 3 | `3-domain/contexts.json` | `decompose.py` | `--gate G2` |
| 4 | `4-architecture/{scores.json,waves.json,adr/ADR-00n.md,nfr-allocation.md}` | `architect.py` | `--gate G3` |
| 5 | `5-data/store-map.json` (proposed by `store_map.py`, confirmed by the agent) | `datamod.py` | `--gate G4` |
| 6 | the code; tests citing `UC-…`/`BR-…`; `target/ops/golden-master.json`; scans summary | `use_case_coverage.py`, `evidence_pack.py --gate G5` | `--gate G5` |
| 7 | `target/legacy/harness.json` (proposed by `legacy_harness.py --propose`, completed by the agent) | `legacy_harness.py`, `golden_master.py`, `evidence_pack.py --gate G6` | `--gate G6` |
| 8 | `8-deploy/{cutover-plan.md,runbook.md}` from `templates/` | `evidence_pack.py --gate G7` | `--gate G7` |

`verify_source_readonly.py` runs before every gate. `gate_decide.py --check` proves
every approved gate's artifacts still hash to their manifest.

## Unattended mode

`/modernize … --auto-approve <approver-id>` records a standing authorization in
`state.json`. The loop then runs `gate_decide.py --auto --by <id> --authorization "…"`
at each gate: green evidence → approved-with-conditions, red evidence → **waived**
with an owner, a compensating control and a 30-day expiry, never approved. Judgement
gates (G1–G3) are approved with the open questions carried as conditions. Every
decision record says it was made under the standing instruction. Use it for a first
run, a demo, or CI; never for a cutover.
