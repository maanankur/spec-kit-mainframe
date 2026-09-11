---
name: 06-forward-engineering
description: Generate Spring Boot services, REST contracts and React/Angular screens from the approved specification. Use on entering phase 6, before Gate 5. Never read COBOL in this phase.
---

# Phase 6 — Forward Engineering

**Input:** approved spec, approved architecture, `mapping.json`, migrated data
**Output:** working Java per wave, under `6-build/waves/wave-N/`
**Exit gate:** G5 (evidence gate) — Tech Lead + Security countersign the build evidence. Behavioural equivalence is proven in Phase 7 (G6).

---

## 1. The specification firewall

> **Generate Java from the specification. Not from the COBOL.**

Read `spec.md` and `business-rules.jsonl`. Write Java that implements those
rules. The COBOL is consulted only to answer a specific question the spec left
open — and when that happens, **update the spec too**, because the spec is
supposed to be sufficient and you have just proved it was not.

This is a process constraint, not a style preference. Working from the COBOL
produces code shaped like COBOL, because that is the path of least resistance
when the source is in front of you: paragraphs become methods, working-storage
becomes fields, `PERFORM` chains become call chains, and the result is a Java
program that only a COBOL programmer can maintain. That outcome removes the
mainframe and keeps every reason the mainframe was a problem.

Practically, when implementing a rule:

- Open the rule, its `edge_cases` and its `arithmetic` block.
- Open the field map for the data it touches.
- Write the Java.
- Only if something is genuinely undetermined, open the COBOL at the cited
  evidence lines — then fix the spec.

### What "shaped like COBOL" looks like

`scripts/jobol_lint.py` checks these mechanically. Run it before handing to Phase 7.

| Smell | Instead |
|-------|---------|
| One class per COBOL program | Classes per responsibility: controller, service, repository, domain object |
| One method per paragraph | Methods per business rule, named for the rule |
| `p1000_processAccounts()` | `accrueMonthlyInterest()` |
| Mutable `wsFoo` fields as scratch space | Parameters in, values out |
| `if (status.equals("Y"))` | `if (account.isActive())` — an enum or boolean |
| `static final String STAT_A = "A"` | `enum AccountStatus { ACTIVE, CLOSED }` |
| A 900-line `process()` method | Decompose along the rules |
| Comments quoting the COBOL statement | Comments citing the rule id and stating intent |

Keep one link back: cite the rule id in the Javadoc (`BR-0042`). That is the
traceability chain — source → rule → code — and it is what lets someone answer
"why does it do this?" in two years. Do not cite COBOL line numbers; the COBOL
will be gone.

---

## 2. Arithmetic — the part that must be exactly right

COBOL arithmetic is exact base-10 with defined truncation. Java's default
numeric types are neither. This is the most common source of real defects in
COBOL conversions, and the defects are small, systematic, and invisible until
someone reconciles a total.

**Rules, without exception:**

1. Every scaled decimal is `BigDecimal`. Every monetary value is `BigDecimal`.
2. Construct from `String` or `BigDecimal.valueOf`, never `new BigDecimal(double)`.
3. Every `divide` states scale *and* `RoundingMode`. Unspecified division throws
   on non-terminating decimals.
4. **`COMPUTE` without `ROUNDED` truncates.** That is `RoundingMode.DOWN`, not
   `HALF_UP`. Defaulting to `HALF_UP` because it feels correct will change
   results on roughly half of all fractional outcomes.
5. `COMPUTE ... ROUNDED` is half-up away from zero — `RoundingMode.HALF_UP`.
6. Compare with `compareTo(...) == 0`. `equals` also compares scale, so
   `1.0` and `1.00` are not equal.
7. Intermediate scale matters. COBOL computes intermediates at a precision the
   compiler derives from the operands; a chain of operations truncated at each
   step gives a different answer than one truncated at the end. The spec's
   `arithmetic` block should say which — if it does not, that is a spec gap.
8. `ON SIZE ERROR` is a real branch. A truncating overflow in COBOL takes that
   path; in Java, decide explicitly and test it.

```java
/** BR-0042: monthly interest, truncated to cents (COMPUTE without ROUNDED). */
public BigDecimal monthlyInterest(BigDecimal balance, BigDecimal annualRate) {
    if (balance.signum() <= 0) {
        return BigDecimal.ZERO;          // BR-0042 edge case: no accrual
    }
    return balance.multiply(annualRate)
                  .divide(TWELVE, 2, RoundingMode.DOWN);
}
```

---

## 3. CICS online → REST + screen

See `cics-jcl-mapping.md` for the full construct table. The design decisions
that matter more than the mechanics:

**One endpoint per business operation, not per screen event.** A BMS screen
handled ENTER, PF3, PF7, PF8 and a dozen field edits in one program. That is not
five endpoints and it is not one — it is the set of *operations* the screen
performs: fetch, validate, save, next page, previous page.

**Kill the COMMAREA.** Pseudo-conversational state passed between screen
interactions becomes an explicit request/response contract. Where state must
survive across calls, use a token or server-side session — deliberately, and
written down. Do not port the COMMAREA into a session object field-for-field;
that reproduces the coupling in a place where it is now invisible.

**Validation moves to the API.** The 3270 screen enforced some rules through
field attributes — numeric-only, length, protected fields. A JSON API has none of
that, so every implicit screen constraint must become an explicit validation.
Phase 2 should have captured these as rules; if a field edit is missing from
`business-rules.jsonl`, that is a spec gap to fix.

**Frontend reproduces flow and semantics first.** Same fields, same validation,
same navigation, so UAT can compare like with like. Redesign is separate, later,
funded work — as agreed at G3.

## 4. Batch → Spring Batch

One JCL job → one `Job`. One JCL step → one `Step`. Keep the names; operations
staff know them, and a job called `POSTTRAN` is findable in a runbook.

| COBOL / JCL | Spring Batch |
|-------------|--------------|
| `OPEN`/`READ`/`AT END` loop | `ItemReader` |
| Per-record processing | `ItemProcessor` |
| `WRITE` | `ItemWriter` |
| `PERFORM UNTIL` over a file | chunk-oriented step |
| `SORT` utility step | `Sort` step or a DB `ORDER BY` |
| Return code / `COND` | step exit status and flow |
| Checkpoint / restart | `JobRepository` restart semantics |

**Restartability must be deliberate.** A COBOL batch job that abends is usually
restarted from a checkpoint or from the top after a manual cleanup, and the
operational procedure for that is often the only place the semantics are
documented. Get it from the runbook. A job that is not idempotent, restarted
because it looked stuck, is one of the more expensive ways to corrupt financial
data.

**Commit intervals change behaviour.** COBOL may commit per record, per N
records, or once at the end. Chunk size in Spring Batch is not just a
performance knob — it determines what is visible to concurrent readers and what
survives a failure. Match the original unless there is a reason not to, and
record the reason.

---

## 5. Per-wave working order

1. Re-read the wave's slice of `spec.md` and its rules.
2. Domain objects and enums from the field maps — types first, so everything
   after is type-checked.
3. Repositories against the migrated schema.
4. Services implementing the rules, one rule at a time, each with its unit test
   derived from the rule's `edge_cases`.
5. Controllers and DTOs.
6. Batch jobs.
7. Frontend screens.
8. `python scripts/jobol_lint.py 6-build/waves/wave-N` — fix every error.
9. Update `traceability.json` with the `target` for each implemented paragraph,
   and re-run `trace_coverage.py`.
10. Hand to Phase 7.

Write the test from the **rule**, not from your implementation. A test written by
reading the code you just wrote confirms the code does what it does.

---

## 6. Things that need a human, not a generator

Do not silently auto-convert these. They were flagged as hazards in Phase 1 and
each should already have a named owner:

- `ALTER` and `GO TO DEPENDING ON` — computed control flow with no clean Java
  equivalent. Needs redesign against the rules, not translation.
- `ENTRY` points — a program with several entry points is several units.
- Pointer arithmetic, `SET ADDRESS OF` — usually a performance hack or a variable
  layout. Re-derive the intent.
- `COMP-1`/`COMP-2` — host floating point. Determine whether the precision was
  ever load-bearing; converting to `BigDecimal` may *change* results, and
  keeping `double` may too. This is a business decision.
- Assembler modules — reimplement from the specification of what they do, or keep
  them behind a service boundary if that is cheaper.
- Sort input/output procedures — logic embedded in a sort exit.

Flag each in the wave's output with the owner and the decision taken.

---

## 7. Lessons from the first build run — now requirements

*Each of these was a stop, a retry loop, or a defect in the first CardDemo
forward-engineering run. They are written here so the next run does not repeat
them.*

### 7.1 Architecture skeleton first, rules second

The first run produced services whose structure did not match the approved
architecture and had to be reworked. Order of work is therefore:

1. Generate the module skeleton from `decomposition.json` and ADR-000: one
   package per bounded context, `api` / `application` / `domain` /
   `infrastructure` inside each, Maven modules per deployable.
2. Generate the ArchUnit tests that enforce that skeleton **and run them** on
   the empty skeleton. Green.
3. Only then implement rules, one at a time, each with its unit test.

A skeleton that compiles and passes ArchUnit is the first checkpoint of every
wave. Do not write a service class before it exists.

### 7.2 Decisions are already made — apply ADR-000

Transaction management (`@Transactional`), configuration (environment variables
via Spring profiles, committed `dev` profile with default credentials and seed
data), integration (Spring Integration), runtime (Docker + compose), UI stack
(profile). See Phase 4 §6. **Do not report "cannot decide"** for anything ADR-000
answers. If it is genuinely absent from ADR-000, add it there and flag the
delta — do not stop.

### 7.3 Dockerise before you try to run anything

The agent sandbox cannot host a long-running Spring Boot JVM. The first run
spent a long time trying variations of `mvn spring-boot:run`, background
processes and port tricks. None of them work and none of them will.

For every wave, generate and use:

- `Dockerfile` (multi-stage: Maven build → JRE runtime image);
- `docker-compose.yml` with the application, PostgreSQL, the broker and any
  stub for a not-yet-migrated dependency, all on the `dev` profile;
- `scripts/wait-for-healthy.sh` polling `/actuator/health`.

Start-up for verification is `docker compose up -d --build && wait-for-healthy`.
If compose is unavailable in the environment, say so and stop — do not fall back
to launching the JVM in-process.

### 7.4 Tests: every rule, every use case, own data, in parallel

The first run left use cases without integration tests and had suites that
depended on each other's data. Requirements:

| Requirement | How |
|---|---|
| Every business rule has ≥1 unit test derived from its `statement` and `edge_cases` | JUnit 5; test class per service, test method per rule, method name cites the rule id |
| Every use case in the wave's spec has ≥1 integration test | `@SpringBootTest` against the compose stack (or Testcontainers PostgreSQL); one test class per use case; write `tests/use-case-coverage.json` mapping use case → test class, checked in Phase 7 |
| Suites create and destroy their own data | `@Sql` setup/teardown or `@Transactional` test rollback; per-suite schema or unique key prefixes; no shared fixtures across suites; every suite passes alone and in any order |
| Parallel by default | JUnit 5 `junit.jupiter.execution.parallel.enabled=true` (`same_thread` for suites that hold a compose resource); Surefire `forkCount=1C`; Failsafe partitioned by use-case group |

A wave with a use case that has no integration test is not ready for Phase 7.

### 7.5 Frontend

The UI stack is the profile's `ui` / `ui_detail` block — do not ask again.
Screens are generated against the OpenAPI contract, with the same field
validation the API enforces, and every screen is wired to a real endpoint before
it is counted.

---

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
| `target/ops/golden-master.json` (`templates/golden-master.json`) with `use_cases` per pair | `golden_master.py`, `use_case_coverage.py` |

```bash
python scripts/use_case_coverage.py --workspace <out>
python scripts/evidence_pack.py --workspace <out> --gate G5 --wave "wave N"
python scripts/gate_decide.py --workspace <out> --gate G5 …
```
