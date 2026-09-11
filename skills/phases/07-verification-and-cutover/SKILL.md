---
name: 07-verification-and-cutover
description: Run the five validation layers, build the golden-master harness, compute the equivalence confidence score and assemble evidence packs. Use on entering phase 7, before Gate 6.
---

# Phase 7 — Verification & Evidence

**Input:** the wave's Java, the spec, the migrated data, the legacy datasets
**Output:** `7-verify/waves/wave-N/evidence-pack.md`
**Exit gates:** G6 (equivalence accepted, per wave) and G7 (go-live)

A wave is done when its evidence pack is green. Not when the code compiles, not
when it looks right, not when a developer says it works.

---

## 1. Why a human does not review the code for correctness

Because they cannot, at this volume, and pretending otherwise is how defects get
approved. Nobody reads 20,000 lines of generated Java against 23,000 lines of
COBOL and reliably notices that one interest calculation truncates where it
should round.

Machines can check that. So the gate reviews *evidence that the checks passed*,
and the human attention goes to the things only judgement can settle: whether
the behaviour that was verified is the behaviour the business wants.

---

## 2. The four levels

Independent, and each catches what the others miss. Run all four.

### Level 1 — Traceability completeness (hard gate)

```bash
python scripts/trace_coverage.py --source <src> \
  --traceability modernization/2-specification/traceability.json \
  --rules modernization/2-specification/business-rules.jsonl \
  --programs <wave programs>
```

Must be 100% with zero errors. Catches: **logic silently omitted**. This is the
only check that can find something that is *not there*, which is why it is a hard
gate rather than a metric.

### Level 2 — Golden master / characterization (the strongest evidence)

The core of equivalence verification, and the reason Phase 1 pushes so hard for
sample data.

For each batch program:

1. Take the real input datasets and the real output datasets from a legacy run.
2. Decode both with `scripts/decode_record.py` and the field maps.
3. Run the Java against the same inputs.
4. Compare outputs **field by field**, using the field map so that a mismatch
   names a business field rather than a byte offset.

```bash
python scripts/decode_record.py --fieldmap fieldmaps/CVTRA05Y.fieldmap.json \
    --data legacy-run/TRANSACT.OUT --encoding cp037 \
    --format csv --out expected/transact.csv
# run the Java, export the same shape, then diff on business keys
```

Catches: **any behavioural difference in aggregate** — arithmetic, rounding,
sequencing, edge-case handling, sort order. It requires no human judgement, which
is exactly why it is the backbone.

For online transactions the equivalent is a request/response corpus: capture
COMMAREA in/out pairs from the legacy system where possible, otherwise
BA-authored scenarios per screen operation.

**Its limits, stated honestly.** A golden master proves equivalence *on the data
you have*. It cannot prove equivalence on paths that data never exercised.
Measure and report coverage: which rules were exercised by the corpus, and which
were not. The unexercised ones are your residual risk, and Level 4 exists to
attack them.

### Level 3 — Data fidelity

The round trip, aggregate reconciliation, and edge-case sweep from
`05-data-modernization` §6. Re-run per wave, not once — each wave touches new
stores.

Catches: **encoding, sign, scale and offset defects**. These masquerade as logic
defects, so finding them here saves debugging the wrong layer.

### Level 4 — Rule-derived tests

For every rule in the wave, a test derived from the rule's `statement` and
`edge_cases` — written from the rule, never from the implementation.

Report **rule coverage**: rules with at least one test / rules in the wave.
Target 100%, and treat any rule whose edge cases are untested as a gap. Pay
particular attention to the rules the golden master did *not* exercise; that
intersection is where undetected defects live.

Catches: **specified behaviour that the data never exercised**, and it documents
intent for maintainers.

---

## 3. Structural quality

```bash
python scripts/jobol_lint.py 6-build/waves/wave-N
```

Zero errors required. Warnings are a judgement call — record the count and the
decision. Correctness findings (money as `double`, missing charset, swallowed
exceptions) are bugs and block the gate. Structural findings cost maintainability;
a deliberate, written exception is acceptable, silence is not.

---

## 4. Non-functional verification

Easy to skip and expensive to skip. The mainframe had characteristics that were
never written down because nobody had to write them down.

| Check | Why |
|-------|-----|
| Batch window | The job ran in 40 minutes at 3am. Does the new one? Under production volume, not sample volume |
| Online response time | 3270 transactions returned in well under a second. Users will notice |
| Throughput at peak | Use the Phase 3 axis-1 numbers, or say they were assumed |
| Restart / idempotency | Kill the job midway and restart it. Does the data end up correct? |
| Concurrency | Two users updating the same account. CICS serialised in ways your JPA code may not |

That last one is worth dwelling on. CICS and VSAM provided record-level
serialisation that COBOL programs relied on implicitly and never mentioned.
Optimistic locking in JPA is not the same thing. Test concurrent updates
explicitly, because this class of defect appears only under production load and
corrupts data when it does.

---

## 5. The evidence pack

Use `templates/evidence-pack.md`. It must be readable in ten minutes and must
lead with the summary table:

| Level | Check | Result | Threshold |
|-------|-------|--------|-----------|
| 1 | Traceability | 100% (312/312) | 100% |
| 2 | Golden master | 48,120/48,120 records, 0 field mismatches | 0 |
| 2 | Rules exercised by corpus | 34/41 | reported |
| 3 | Round trip | byte-identical | identical |
| 3 | Aggregate reconciliation | all sums match to the cent | exact |
| 4 | Rule coverage | 41/41 | 100% |
| — | jobol-lint | 0 errors, 6 warnings (accepted, see §4) | 0 errors |
| — | Batch window | 12 min vs 40 min legacy | ≤ legacy |

Then, and this is the part that makes the pack trustworthy:

- **Every difference found, and its resolution.** Including the ones that turned
  out to be legacy defects.
- **What was not verified, and why.** The 7 rules the corpus did not exercise.
  The concurrency scenario you could not reproduce. The volume you could not
  generate. A pack that claims everything was verified is not credible.

### G6 — wave accepted (equivalence)

Product Owner, QA Lead and Business Analyst. They are confirming: the evidence is sufficient, the
residual risks are acceptable, and the differences found were resolved
correctly. They are not reviewing code.

### G7 — cutover ready (go-live)

Additionally requires:

- Parallel run results — legacy and new on the same live inputs, outputs
  compared, for at least one full business cycle. For anything financial this is
  not optional; it is the only test that runs on real production data.
- Rollback plan, tested. Including how to reverse data written by the new system.
- Reconciliation procedure for the cutover window.
- Ops runbook: how to restart, what alerts mean, who to call.
- Sign-off that the legacy system stays available for a defined fallback period.

---

## 6. Reporting outcomes honestly

If a check fails, the pack says so, with the output. If a check was skipped, the
pack says which and why. If a wave is accepted with known gaps, the gaps are
listed and the acceptance records who accepted them.

The temptation at this point in a programme is to present a green summary
because the schedule wants one. Resist it. The evidence pack's only value is
that a reader can trust it — and its whole purpose is to be the thing that
someone re-reads after a production incident.

---

## 7. Running the system under test (added after the first CardDemo run)

The sandbox cannot host a Spring Boot JVM directly. Do not try. Bring the wave
up with its compose stack on the `dev` profile:

```bash
cd 6-build/waves/wave-N && docker compose up -d --build
scripts/wait-for-healthy.sh http://localhost:8080/actuator/health 120
```

Then run the suites **in parallel** — the first run executed them serially and
verification became the long pole:

```bash
mvn -T 1C verify -Dsurefire.forkCount=1C -Dfailsafe.parallel=classes
```

Collect JUnit XML from every module; the evidence pack cites the files.

### Level 4b — use-case coverage (hard gate, generated, executed evidence only)

Every use case in `2-specification/use-cases.jsonl` has at least one **executed,
passed** test method that cites its id, or a green golden-master pair that lists it.
The matrix is generated, never hand-written:

```bash
python scripts/use_case_coverage.py --workspace <out>     # -> target/ops/out/use-case-coverage.{json,md}
```

It reads the test sources for the id (Javadoc above `@Test`, `@UseCase("UC-…")`,
a trailing comment) **and** the surefire/failsafe XML for the executed, passed
testcase. A test that exists but did not run covers nothing. The first run wrote
integration tests, never executed them, and reported the use cases covered; a human
found it by asking. `evidence_pack.py` reads this file; anything below the profile's
`coverage_targets.use_cases` is a red row.

### Test-data hygiene check

Run the integration suites twice: once in the default order, once with
`-Dsurefire.runOrder=reversealphabetical`. A suite that passes only in one order
is sharing data with another suite; that is a defect in the tests, and it blocks
the gate until fixed.

### Running the integration tests from the sandbox

The ITs need the database the compose stack runs. From the sandbox the JVM runs
inside the Maven container, so point the tests at the compose database through
the Docker host, mount the sample data read-only, and reuse the shared `.m2` volume:

```bash
docker run --rm -v "$PWD/backend:/w" -v "<source>/app/data:/data:ro" -v <project>-m2:/root/.m2 -w /w \
  -e DB_URL=jdbc:postgresql://host.docker.internal:5432/<db> -e DB_USER=<dev user> -e DB_PASSWORD=<dev pw> \
  maven:3.9-eclipse-temurin-21 mvn -q -T 1C verify -Dsurefire.forkCount=1C
```

`failsafe-reports/TEST-*.xml` must exist afterwards; if the directory is empty the
ITs did not run, whatever the console said.

---

## 8. Mechanics — the scripts that run this phase

| Step | Script | Produces |
|---|---|---|
| Legacy chain under GnuCOBOL | `legacy_harness.py --propose`, then complete `target/legacy/harness.json` (stubs, PARM, SORT keys, `load_from`), then `legacy_harness.py` | `target/legacy/out/**`, `manifest.json` with return codes |
| Target chain + exports | the wave's `run_java_pipeline`-style runner (compose up → jobs → `/api/batch/export`) | `target/ops/out/java/*`, `java-run.json` |
| Golden master | `golden_master.py` with `target/ops/golden-master.json` (`templates/golden-master.json`; layouts from `5-data/mapping.json`) | `golden-master-report.{md,json}` |
| Use-case coverage | `use_case_coverage.py` | `use-case-coverage.{json,md}` |
| Evidence packs | `evidence_pack.py --gate G5`, `--gate G6`, `--gate G7` | `governance/gates/G*/{review-pack.md,manifest.json}`; state = proposed |
| Decision | `gate_decide.py --gate G6 --decision waived --control "Production=…"` (red rows) or `--auto --by <id> --authorization "…"` | `decision-record.json`, `governance/waivers/WV-*.json`, state advanced |

Load `techniques/golden-master-harness` when building the harness or when a
golden-master row is red. Scanner results (SAST/SCA/secrets) are read from
`target/ops/out/scans/summary.json` `{sast:{critical,high}, sca:{critical,high},
secrets:{count}}`; without it the row is red and must be waived, never approved.
`8-deploy/cutover-plan.md` and `runbook.md` come from `templates/`; G7 reads them.
