# Lessons learned — and where each one now lives in the plugin

The framework's own rule is that a skill without a failing case behind it is a
folder of prompts. This file is the record of the failing cases: what the model
could not do autonomously on the CardDemo corpus, what a human had to supply,
and the exact file where that answer is now encoded so the next run does not
need the human.

Two sources: the first forward-engineering runs (Sonnet 5, build/verify
phases) and the first governed run of `/modernize` (2026-09-09/10, phases 0–2).

---

## A. Build and verification phases — from the first Spring Boot runs

| # | What went wrong | What the human had to say | Now encoded in |
|---|---|---|---|
| A1 | Target Spring Boot architecture was faulty in the first run; services did not match the approved decomposition and were reworked | "Generate the module skeleton first, enforce it, then implement" | `skills/phases/06-forward-engineering` §7.1 (skeleton + ArchUnit before any rule); `profiles/*.yaml` `code_structure.skeleton_first`; `agents/code-generation-agent.md` exit criteria; `workflows/full-modernization.yaml` build steps |
| A2 | Application had defects and not every identified use case was covered by JUnit / integration tests | "Every use case needs an integration test; every rule a unit test" | `06` §7.4 coverage table; `07` §7 Level 4b **use-case coverage is a hard gate**; `agents/test-generation-agent.md`, `agents/validation-agent.md` exit criteria; profile `testing.coverage_targets`; workflow `tests.exit` |
| A3 | Tests were executed serially; verification became the long pole | "Run them in parallel" | `06` §7.4 (JUnit 5 parallel, Surefire `forkCount=1C`, Failsafe partitions); `07` §7 run command; profile `testing.parallel`; validation-agent forbidden list |
| A4 | Could not start Spring Boot in the agent sandbox; retried many `mvn spring-boot:run` variants | "Dockerise the services and start them under compose" | `06` §7.3 (Dockerfile + compose + wait-for-healthy, **never** in-process JVM); `07` §7; profile `local_runtime`; `rules/07-generated-code-standards.md`; code-gen and validation agents forbidden lists |
| A5 | Left decisions open — transaction management in particular — and reported "cannot decide" | "Use standard Spring choices: `@Transactional`" | `skills/phases/04-target-architecture` §6 **ADR-000 platform defaults** (decided at G3, applied without asking); `rules/06-gate-discipline.md` ("cannot decide" on a defaulted decision is a rule violation); profile `transactions`; architecture-agent and code-gen-agent contracts |
| A6 | Credentials and environment config | "Env variables selected by Spring profile; a `dev` profile with default credentials so QA can start and test unattended" | profile `configuration.profiles`; `04` §6; `06` §7.2; `rules/07` |
| A7 | Integration style and test data | "Use Spring Integration; every suite creates and destroys its own data" | profile `integration`, `testing.integration.data_lifecycle`; `06` §7.4; `07` §7 test-data hygiene check (run suites in reverse order); test-gen agent forbidden: shared fixtures |
| A8 | UI technology stack had to be suggested by the human | "Decide it once" | profile `ui_detail` (bundler, routing, server state, forms, components); `04` §6; `06` §7.5; ui-generation-agent forbidden: asking which stack |

The common shape of A1–A8: **the model stopped to ask about things that have a
standard answer, and did not stop about things that needed a human** (use-case
coverage was found by a person reading code). The fix is the same in every
row: move the standard answers into the profile and ADR-000, and move the
machine-checkable gaps into exit criteria a script enforces.

---

## B. Governed run of `/modernize` on CardDemo — phases 0–2

| # | What went wrong | Found how | Now encoded in |
|---|---|---|---|
| B1 | `trace_coverage.py` resolved `PROGRAM-ID` over raw text and captured **sequence numbers** on two card-image members (`COTRTLIC`→`002600`, `COTRTUPC`→`00220000`). The 100%-coverage gate would have demanded two fictional programs and left 119 real paragraphs unexamined | Baseline run of the gate before writing any traceability | `scripts/trace_coverage.py` resolves from cols 7–72 only |
| B2 | `inventory.py` counted `PROGRAM-ID`, `DATE-WRITTEN`, `END-IF`, `GOBACK`, `FILE-CONTROL` as paragraphs — 1,033 reported, 870 real (+19%) | Two parsers disagreed; set-difference per program | `scripts/inventory.py` `procedure_paragraphs()` — PROCEDURE DIVISION, area A, scope terminators excluded; mirrors the gate parser |
| B3 | `depgraph` declared 6 programs unreachable; **5 are scheduled**, one is a destructive IMS purge. Cause: only `EXEC PGM=` was matched; IMS (`DFSRRC00 PARM=`) and DB2 TSO (`IKJEFT01` + `SYSTSIN RUN PROGRAM(...)`) invocations were invisible | Grepping every JCL for the "dead" names | `scripts/inventory.py` `analyse_jcl` resolves the real program through PARM / SYSTSIN; `depgraph.py` inherits it |
| B4 | Config said `scheduler: none`; the repo has CA-7 and Control-M exports (`app/scheduler/`), unregistered and unhashed | Source-integrity check listed unregistered files | `scripts/modernize.py` `SOURCE_EXT["scheduler"]`, `detect_platform()`, config and census; `inventory.py` `SCHED_EXT` |
| B5 | CA-7 export timings are template placeholders (identical `CPUTM`/`ELAPTM=2359` on every job) and could have been read as a batch-window baseline | Read the export | `02-specification` batch guidance via work-package briefing; recorded in `discovery-corrections.md` SG-04 |
| B6 | **Every L1 phase skill disagreed with the L0 router**: phase numbers off by one, wrong gate ids (02 said G2; 06 said "no gate"; 07 said G4/G5), wrong approvers, wrong output directories (`5-build`, `6-verify`) | Reading the skills against the router | All seven `skills/phases/*/SKILL.md` headers reconciled to the router, `state.schema.json` and `modernize.py` workspace layout |
| B7 | `03-domain-decomposition/SKILL.md` was a **copy of the architecture skill** — the phase had no guidance | Diffing the two files | Rewritten: `skills/phases/03-domain-decomposition/SKILL.md` |
| B8 | `reverse-engineering-agent` has no `Write`/`Bash` tool, so it structurally cannot produce `spec.md`, `rules.jsonl` or `traceability.json`; its MCP tools (`mcp__cobol__*`, `mcp__knowledge_graph__*`) have no server behind them | Dispatch attempt | Worked around with general-purpose agents under a written briefing (`modernization/tools/wp-briefing.md`) and a validating merge script; **agent tool grants still need fixing** — see STATUS.md |
| B9 | Long-running reverse-engineering agents held all output in memory; two full rounds (18 agent runs) were lost to API rate limits with nothing on disk | Empty fragment directories after failures | Briefing "Write incrementally" section: append per program, rewrite traceability per program, never cite a rule before writing it. Candidate for `rules/` as a general agent rule |
| B10 | Nine agents dispatched at once exhausted the session budget twice | Rate-limit terminations | Operational: batch dispatch, incremental writes; a `conductor` budget check is designed (DESIGN.md §6.5) but not implemented |
| B11 | Merge validation found traceability citing rule ids that were never written (`BR-0080`, `BR-0081`) | `merge_fragments.py` | Briefing rule; `merge_fragments.py` check ("cites rule which does not exist") |
| B12 | `copybook_parse.py` gave **offset 0 to every field** of a copybook with no `01` level — six of them, including the IMS segment layouts (`CIPAUSMY`, `CIPAUDTY`) and the MQ request/reply (`CCPAURQY`, `CCPAURLY`) | WP9 recomputed offsets by hand and they disagreed with the field map | `copybook_parse.py` wraps a top level > 01 in an implicit record (warning emitted); six maps regenerated, 56 byte-identical |
| B13 | CRUD matrix dropped **9 CICS file accesses in 5 programs**; four programs appeared as singleton clusters. Cause was not name resolution but a **500-character cap** on the `EXEC CICS … END-EXEC` body — a `READ` with `RIDFLD/KEYLENGTH(LENGTH OF)/INTO/LENGTH/RESP/RESP2` runs past it | WP9 reported one miss; regeneration diff showed the rest | `inventory.py` window 500 → 2,500; clusters 22 → 18 |
| B14 | `COACTVWC` declares `0000-MAIN-EXIT` twice; two parsers reported 870 vs 869 | Parser disagreement, again | `inventory.py` de-duplicates; gate parser lists both. Duplicate paragraph names added to the hazard list for the JOBOL lint |
| B15 | Two of the four patch scripts written as shell heredocs silently mangled `\\` → `\` and failed on their first anchor | Patch-script asserts | Plugin patches are files run by the interpreter, never heredocs; every replacement asserts its anchor |
| B16 | The CRUD matrix kept batch FD names and CICS file names of the **same dataset** apart: 53 "stores" for 37 datasets; the online and batch halves of one domain landed in different clusters | Phase 3 decomposition needed a hand-written alias table | `inventory.py` records DD → DSN per step; `depgraph.py` resolves FD → ASSIGN → DD → DSN and CICS file → CSD DSNAME, folds AIX paths, inherits a CALLer's DDs; 50/53 resolved on CardDemo |
| B18 | A fidelity pass over a REDEFINES file decoded with the base layout produced 2,328 "unexplained" byte differences — every one a customer/transaction record read through the account overlay. `decode_record.py` warns but accepts only one `--redefines-when` per run, so a multi-type file needs one pass per discriminator value | Round-trip diff on `CVEXPORT` | `tools/datamod.py` decodes per record type and merges; `decode_record.py` should accept several `--redefines-when` specs (open) |
| B19 | Hibernate `ddl-auto: validate` rejects the `CHAR(n)` key columns the legacy layouts require (`card_num CHAR(16)` → "expecting varchar"); the app failed to start | First compose start | Flyway owns the schema; `ddl-auto: none`. Encode in the profile / phase-6 skill: never rely on Hibernate validation when keys are `CHAR` |
| B20 | Spring Data does not scan repository interfaces nested in a holder class unless `@EnableJpaRepositories(considerNestedRepositories = true)` is set; the app failed to start on the second attempt | compose start | Annotation added; phase-6 skill: one repository per top-level interface, or the flag |
| B21 | A rule's own worked example was off by a factor of ten (BR-0567: "1940.00 prints as 00000001940{" — the sample decodes to 194.00). A unit test written from the example failed against a correct implementation | `LegacyFormatTest` | Worked examples in rules must quote a real sample value verified by the decoder; the test was corrected, the rule flagged for the BA |
| B22 | GnuCOBOL `DISPLAY` of a signed zoned field prints a trailing `+`/`-` where IBM prints an overpunch letter — the golden master from GnuCOBOL differs textually from what the rule describes for z/OS | Listing comparison | `compare_golden.py` compares zoned fields as decimals (typed comparison, Phase 7 §2); golden-master-harness technique skill must say: compare by type, never by string |
| B23 | Spring Batch's schema initializer ignores a schema-qualified `table-prefix` (`batch.BATCH_`), so the job repository tables were missing at the first job launch (HTTP 500) | first batch run | plain `BATCH_` prefix; note in the phase-6 skill's Spring Batch section |
| B24 | The fidelity report said "FILLER carries data — kept" for `TCATBALF`, but the generated schema and entity dropped it; the golden master caught it (the legacy echoes the record, zeros and all) | golden master, INTCALC sysout | `mapping.json` decisions must drive schema generation mechanically; the filler column is now carried |
| B25 | Golden-master comparison needs three explanation categories to be honest: run-time clock fields (BR-0598/BR-0593), sign representation (GnuCOBOL vs IBM), and runtime noise (`libcob:` warnings). Everything else was a real defect and was fixed | 155 → 0 unexplained across two comparison runs | `compare_golden.py`; golden-master-harness technique skill (still to write) |
| B17 | `modernize.py --force` **reset `state.json`** to `current_phase: specification` and dropped later phases when re-run mid-programme to regenerate phase 0–1 outputs; a phase-3 generator re-run also overwrote an *approved* gate with `proposed` | Two gate statuses regressed after a legitimate regeneration | Driver must preserve `current_phase`, `phases_complete` and `gates` on re-run (fix below); phase generators must refuse to overwrite an approved gate and instead mark it `invalidated` with the reason |

---

## C. Repeating error patterns (the ones to design against)

1. **Regex parsing of card-image COBOL/JCL.** B1, B2, B3 are all the same class:
   a pattern run over the wrong text (raw instead of code area; whole file
   instead of a division; EXEC card instead of the step). The design already
   says "ProLeap or GnuCOBOL, not regex" (DESIGN.md §9.2); until that lands,
   every regex parser needs a second, independent parser to disagree with.
2. **Documentation drift between layers.** Router, phase skills, config,
   workflow and DESIGN.md were written at different times and never reconciled
   (B6, B7). Add an eval that asserts phase ids, gate ids, approvers and output
   directories match across router, skills, schema and `modernize.py`.
3. **Agents that cannot write their own outputs** (B8) and **agents that write
   only at the end** (B9). Both are contract defects: every agent that owns an
   artifact needs the tool to write it and the instruction to write it
   incrementally.
4. **Standard decisions surfaced as escalations** (A5, A6, A8) while
   **machine-checkable gaps were left to humans** (A2). Defaults belong in the
   profile; gaps belong in exit criteria.
5. **Static analysis presented as fact.** "Unreachable" (B3) and "no scheduler"
   (B4) were absence-of-evidence read as evidence-of-absence. Every negative
   finding from the deterministic plane should name what it searched.
6. **Silent truncation windows.** B13's 500-character cap and B1's raw-text
   regex are the same defect class as a `PIC X(8)` receiving a 9-character
   value: the parser kept going and reported less than it saw, with no warning.
   Every bounded scan in the deterministic plane should emit a warning when the
   bound is hit, and the field-map parser now does exactly that for the implicit
   record case (B12).
7. **Agents are a second parser.** B12 and B13 were both found because a
   specification agent recomputed a fact by hand and disagreed with the
   deterministic artifact. That disagreement is the most valuable signal the
   judgement plane produces; the work-package briefing now requires agents to
   report every such disagreement as a "parser gap" rather than quietly using
   their own number.

## D. Generalising the plugin (second pass, 2026-09-10)

The first run's generators lived in the workspace (`modernization/tools/*.py`,
`target/legacy/run_legacy.py`, `target/ops/compare_golden.py`) with CardDemo's
contexts, scores, waves, store list, record layouts and job chain hard-coded. Moving
them into `plugin/scripts/` forced one design rule: **every phase = one JSON judgement
file the agent writes + one generator that computes everything else and validates the
judgement against the facts.** What that surfaced:

- **D1 — copybook-to-store is the most consequential data decision and was a table
  in someone's head.** `store_map.py` now derives it from IDCAMS `DEFINE` (parsed from
  in-stream SYSIN with continuation removed — the first regex saw nothing), `REPRO`,
  `FD … COPY`, and field-name overlap with the inline FD record; anything guessed is
  `confirm: true`. A wrong pick (the test fixture chose `CVACT03Y` for `DISCGRP`) shows
  up as 101 unexplained byte round-trip differences — the proof works, but confirm first.
- **D2 — dataset names need a majority prefix, not unanimity.** One oddly named demo
  cluster (`AWS.CUSTDATA.CLUSTER`) defeated the common-prefix cut and every store
  became `AWS`. Store tokens are cut after the qualifiers that most DSNs share.
- **D3 — a judgement gate with a red check is approved *with conditions*, an evidence
  gate only waived.** `gate_decide.py` enforces both; the first run had only the second
  rule and would have blocked G3 on a missing NFR allocation.
- **D4 — in unattended mode a red row without a matching control still needs a
  recorded control.** The default is generic and honest ("attach green evidence for X
  before the next gate"); it is never an approval.
- **D5 — the compiler image's ENTRYPOINT ate the harness command.** `docker run
  --entrypoint sh … -c` is independent of the image. Output directories must exist
  before GnuCOBOL opens a file: `OPEN OUTPUT` into a missing directory fails silently
  and the unload reports `records=50` with no file.
- **D6 — executed evidence.** `use_case_coverage.py` counts a use case covered only by
  a test method that both cites the id and appears as a passed testcase in
  surefire/failsafe XML, or by a green golden-master pair naming it. Written-but-not-
  executed tests are reported as such.
- **D7 — Bash heredocs mangle backslashes** (`\\b` became a backspace character inside
  a regex, `\\n` became a real newline). Patch scripts are written with the file tool
  and executed, never pasted through a heredoc.
- **D8 — the generic chain reproduced the first run exactly** on the fixture: same
  440 rules / 870 paragraphs, 11 contexts, same verdicts, same wave scores, byte-
  identical legacy outputs except the run-time timestamps, and the same 302
  golden-master differences the stale Java listings had acquired after the demo re-ran
  READACCT on posted data — which the report now states instead of hiding.
