---
description: "Phases 7-8 — legacy harness under GnuCOBOL, golden-master comparison, use-case coverage from executed evidence, evidence packs and Gates G5/G6/G7"
---


# Phases 7-8 — verification and cutover evidence

Arguments: `$ARGUMENTS` — `[--wave N] [--gate G5|G6|G7]`.

Before acting:

1. Read `mainframe-config.yml` in `.specify/extensions/mainframe/` (source path, output path, profile, industry, approvers, `auto_approve`). Command arguments override it.
2. Read `<output>/modernization/state.json`. If it is absent, run __SPECKIT_COMMAND_MAINFRAME_MODERNIZE__ first.
3. Run `python .specify/extensions/mainframe/scripts/verify_source_readonly.py --workspace <output>` — the legacy source tree is read-only, always.
4. Verify the preceding gate is approved and its artifact hashes still match: `python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <output> --check`. If not, stop and report which approval is void.
5. The phase skill text is in `.specify/extensions/mainframe/skills/phases/` — read the one for this phase; load a technique from `.specify/extensions/mainframe/skills/techniques/` only when its trigger appears.


## Procedure

Read `.specify/extensions/mainframe/skills/phases/07-verification-and-cutover/SKILL.md` (the four levels, honest reporting) and `.specify/extensions/mainframe/skills/techniques/golden-master-harness/SKILL.md`, then:

## 8. Mechanics — the scripts that run this phase

| Step | Script | Produces |
|---|---|---|
| Legacy chain under GnuCOBOL | `legacy_harness.py --propose`, then complete `target/legacy/harness.json` (stubs, PARM, SORT keys, `load_from`), then `legacy_harness.py` | `target/legacy/out/**`, `manifest.json` with return codes |
| Target chain + exports | the wave's `run_java_pipeline`-style runner (compose up → jobs → `/api/batch/export`) | `target/ops/out/java/*`, `java-run.json` |
| Golden master | `golden_master.py` with `target/ops/golden-master.json` (`.specify/extensions/mainframe/templates/golden-master.json`; layouts from `5-data/mapping.json`) | `golden-master-report.{md,json}` |
| Use-case coverage | `use_case_coverage.py` | `use-case-coverage.{json,md}` |
| Evidence packs | `evidence_pack.py --gate G5`, `--gate G6`, `--gate G7` | `governance/gates/G*/{review-pack.md,manifest.json}`; state = proposed |
| Decision | `gate_decide.py --gate G6 --decision waived --control "Production=…"` (red rows) or `--auto --by <id> --authorization "…"` | `decision-record.json`, `governance/waivers/WV-*.json`, state advanced |

Load `.specify/extensions/mainframe/skills/techniques/golden-master-harness` when building the harness or when a
golden-master row is red. Scanner results (SAST/SCA/secrets) are read from
`target/ops/out/scans/summary.json` `{sast:{critical,high}, sca:{critical,high},
secrets:{count}}`; without it the row is red and must be waived, never approved.
`8-deploy/cutover-plan.md` and `runbook.md` come from `.specify/extensions/mainframe/templates/`; G7 reads them.
