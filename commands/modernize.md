---
description: "Bootstrap phases 0-1 on a COBOL application (read-only), plan the work packages, then drive the gated lifecycle to Java"
scripts:
  sh: scripts/bash/modernize.sh
  ps: scripts/powershell/modernize.ps1
---


# Modernize a COBOL application

Arguments: `$ARGUMENTS` — `<cobol-app-path> [output-path] [--assess] [--until G3] [--auto-approve <id>] [--profile …] [--industry …] [--database …] [--ui …] [--force]`.
With no arguments, resume from `<output>/modernization/state.json` (default output: a sibling of the source named `<app>-modernized`).

## Step 1 — bootstrap (deterministic, always safe to re-run)

```
{SCRIPT} $ARGUMENTS
```

This creates the workspace, writes `modernization.config.yaml` and `state.json`, completes phase 0 (intake: artifact register with SHA-256, gap list) and phase 1 (discovery: inventory, dependency graph, CRUD matrix, copybook field maps, dataset register), then prepares phase 2 (`tools/paragraph-skeleton.json`, `2-specification/_fragments/plan.json` + one `WPn/brief.md` per work package). It never writes to the source tree.

Report its summary. Then read `<output>/modernization/0-intake/gap-list.md` aloud in your own words — the missing inputs it names (production datasets, execution telemetry, batch timings, security exports) have the longest lead time in the programme. If `--assess` was given, stop here.

## Step 2 — the lifecycle

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

Operating procedure per phase: read `state.json`; verify the preceding gate and its hashes (`python .specify/extensions/mainframe/scripts/gate_decide.py --check`); read the phase skill in `.specify/extensions/mainframe/skills/phases/`; write the phase's judgement input; run the phase generator; at the gate, stop and report — or, under a recorded `--auto-approve`, run `gate_decide.py --auto` and continue. Between gates, work without asking permission.

## Scripts per phase — the deterministic plane, and where judgement enters

Every phase has a generator in `.specify/extensions/mainframe/scripts/`. It computes what can be computed, reads
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
| 8 | `8-deploy/{cutover-plan.md,runbook.md}` from `.specify/extensions/mainframe/templates/` | `evidence_pack.py --gate G7` | `--gate G7` |

`verify_source_readonly.py` runs before every gate. `gate_decide.py --check` proves
every approved gate's artifacts still hash to their manifest.

## Unattended mode

`__SPECKIT_COMMAND_MAINFRAME_MODERNIZE__ … --auto-approve <approver-id>` records a standing authorization in
`state.json`. The loop then runs `gate_decide.py --auto --by <id> --authorization "…"`
at each gate: green evidence → approved-with-conditions, red evidence → **waived**
with an owner, a compensating control and a 30-day expiry, never approved. Judgement
gates (G1–G3) are approved with the open questions carried as conditions. Every
decision record says it was made under the standing instruction. Use it for a first
run, a demo, or CI; never for a cutover.

## Phase commands (each also usable on its own)

- Phase 2 — __SPECKIT_COMMAND_MAINFRAME_SPEC__ · Phase 3 — __SPECKIT_COMMAND_MAINFRAME_DECOMPOSE__ · Phase 4 — __SPECKIT_COMMAND_MAINFRAME_ARCHITECT__ · Phase 5 — __SPECKIT_COMMAND_MAINFRAME_DATA__ · Phase 6 — __SPECKIT_COMMAND_MAINFRAME_BUILD__ · Phases 7-8 — __SPECKIT_COMMAND_MAINFRAME_VERIFY__ · Gates — __SPECKIT_COMMAND_MAINFRAME_GATE__ · __SPECKIT_COMMAND_MAINFRAME_STATUS__

## Non-negotiables

- Never write to the source tree (`verify_source_readonly.py` before every gate).
- Target code comes from the approved specification, never from COBOL. The build step has no read path to COBOL — do not work around it.
- Facts a parser can compute are never inferred. Run the script.
- Every business rule links to its source paragraphs or it is not written.
- A red evidence row cannot be approved, only waived with an owner, a compensating control and an expiry.

## Scope honesty

State early what this does not do: it does not replace mainframe runtime testing at
production volume; it cannot recover intent that exists only in a retiring
engineer's head (ambiguity becomes an open question at G1, never an invented
answer); assembler, `ALTER` and `GO TO DEPENDING ON` are flagged for manual
treatment; and generated tests prove equivalence with *observed behaviour*, not
correctness - a faithfully converted bug is still a bug, and belongs on the G1
discovered-defect list rather than being silently fixed.
