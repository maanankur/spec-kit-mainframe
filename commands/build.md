---
description: "Phase 6 — forward-engineer a wave from the approved specification (never from COBOL) under the profile's platform defaults; propose Gate G5"
---


# Phase 6 — forward engineering (per wave)

Arguments: `$ARGUMENTS` — `[--wave N]`.

Before acting:

1. Read `mainframe-config.yml` in `.specify/extensions/mainframe/` (source path, output path, profile, industry, approvers, `auto_approve`). Command arguments override it.
2. Read `<output>/modernization/state.json`. If it is absent, run __SPECKIT_COMMAND_MAINFRAME_MODERNIZE__ first.
3. Run `python .specify/extensions/mainframe/scripts/verify_source_readonly.py --workspace <output>` — the legacy source tree is read-only, always.
4. Verify the preceding gate is approved and its artifact hashes still match: `python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <output> --check`. If not, stop and report which approval is void.
5. The phase skill text is in `.specify/extensions/mainframe/skills/phases/` — read the one for this phase; load a technique from `.specify/extensions/mainframe/skills/techniques/` only when its trigger appears.


## The specification firewall

The build reads `2-specification/spec.md`, `business-rules.jsonl`, `use-cases.jsonl`, `3-domain/decomposition.json`, `4-architecture/**`, `5-data/{schema.sql,mapping.json}` and the profile. It does **not** read COBOL, copybooks, JCL or BMS. If a rule is unclear, the answer is an open question against the specification, not a look at the source.

## Procedure

Read `.specify/extensions/mainframe/skills/phases/06-forward-engineering/SKILL.md` in full (arithmetic, CICS → REST, batch → Spring Batch, per-wave order, lessons §7), apply ADR-000 platform defaults without asking, skeleton first (modules per context, ArchUnit, Flyway from `schema.sql`, compose stack on the `dev` profile), then rules, then tests. Every implementing method cites its `BR-` id; every test cites its `UC-`/`BR-` ids; run the suites inside the Maven container against the compose database so surefire **and** failsafe reports exist.

## 8. Mechanics — what the build must leave behind for the evidence

The G5 pack is generated from artifacts, not from the build report. Leave these:

| Artifact | Read by |
|---|---|
| `target/backend/target/surefire-reports/TEST-*.xml` **and** `failsafe-reports/TEST-*.xml` | `evidence_pack.py --gate G5` — ITs that did not run are a red row |
| Every test method cites its use case (`/** UC-… */` above `@Test`, or `@UseCase("UC-…")`) and the rule ids it proves (`BR-…`) | `use_case_coverage.py` |
| `BR-nnnn` in the Javadoc of every method that implements a rule | `evidence_pack.py` ("rules of covered use cases cited in Java") |
| `application.yml` with profiles, `${ENV:default}` credentials, `legacy-defects` flags; `docker-compose.yml`; `ArchitectureTest` | platform-defaults row |
| `target/ops/out/scans/summary.json` `{sast:{critical,high}, sca:{critical,high}, secrets:{count}}` | SAST/SCA/secrets row — absent = red, waived not approved |
| A legacy-image export endpoint (`/api/batch/export?suffix=`) writing fixed-width files per `5-data/mapping.json` to `target/ops/out/java/` | `golden_master.py` |
| `target/ops/golden-master.json` (`.specify/extensions/mainframe/templates/golden-master.json`) with `use_cases` per pair | `golden_master.py`, `use_case_coverage.py` |

```bash
python .specify/extensions/mainframe/scripts/use_case_coverage.py --workspace <out>
python .specify/extensions/mainframe/scripts/evidence_pack.py --workspace <out> --gate G5 --wave "wave N"
python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <out> --gate G5 …
```
