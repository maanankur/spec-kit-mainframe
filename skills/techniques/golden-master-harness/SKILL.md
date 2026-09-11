---
name: golden-master-harness
description: Build and run the legacy-vs-target equivalence harness — execute the legacy batch chain under GnuCOBOL in Docker, export the target's fixed-width images at the same points, compare typed field-by-field, and turn the result into gate evidence. Load when building the equivalence harness (phase 7) or when a golden-master row is red.
---

# Golden-master harness

The strongest equivalence evidence the pipeline produces, and the reason phase 1
pushes for sample datasets. Three scripts, one config each, no hand-typed layouts.

## 1. Run the legacy side — `legacy_harness.py`

```bash
python scripts/legacy_harness.py --workspace <out> --propose     # once: writes target/legacy/harness.json from JCL + store-map
python scripts/legacy_harness.py --workspace <out>               # compile, load, run every job, unload -> target/legacy/out/
```

The proposal is complete only where the deterministic plane could see:

| You must supply | Where it comes from |
|---|---|
| `load_from` per indexed file | the ASCII fixed-width image of the sample master (one record per line). The proposer finds `data/ASCII/*` by name; check every entry |
| `stubs/*.cbl` | COBOL stand-ins for CALLed modules not in the repository (assembler date routines, `CEE3ABD`, IMS/MQ services). Behaviour per the specification rule; cite the rule in the stub's comment. A stub that does more than the rule says contaminates the golden master |
| `parm` where the program has `PROCEDURE DIVISION USING` | the JCL `PARM=`; the driver program is generated |
| `host_sort` for a `PGM=SORT` step | `key` [offset, length] and `include` from the SORT control cards; fixed-width only |
| `fixed_to_lines` for report outputs | record width from the FD (`RECORD CONTAINS`) so the report is one line per record |
| `delete_before` for files a job creates | otherwise a second run appends |

Jobs with `runnable_offline: false` need DB2/IMS/MQ; either stub the access (and say so
in the evidence) or leave them out and record the gap. Online (CICS) programs never run
here — their equivalence needs a request/response corpus (evidence row "Online screens").

Compiler flags matter: `-std=ibm -fsign=EBCDIC` keeps IBM semantics and the EBCDIC
overpunch letters the ASCII samples carry; `COB_LS_FIXED=1` keeps line-sequential
records fixed width. Change them only with a written reason in `harness.json`.

## 2. Export the target side at the same points

The target must write **the legacy fixed-width image** of each store after each job
(`/api/batch/export?suffix=after-<job>` or equivalent), plus each job's listing/report
as text. Layouts come from `5-data/mapping.json` (offset, length, PIC) — the export
code reads the mapping, never a copybook. Files go to `target/ops/out/java/`.

Run the same chain in the same order on the same seed data (`run_java_pipeline` style:
compose up → wait healthy → jobs → exports → `java-run.json`). Different seed data
produces a comparison that is unexplained by construction.

## 3. Compare — `golden_master.py`

```bash
python scripts/golden_master.py --workspace <out>      # config: target/ops/golden-master.json (templates/golden-master.json)
```

Each pair is `records` (keyed by the store's primary key from mapping.json; numeric
DISPLAY fields compared as decimals so `+`/overpunch differences vanish) or `text`
(line by line after `noise_patterns`). Every field difference is one of:

- **identical** — bytes equal, or equal as a decimal, or equal after trailing blanks;
- **explained** — a declared `runtime_fields` column whose both sides match the declared
  pattern (processing timestamps set from the clock), or a labelled listing value equal as
  a decimal;
- **unexplained** — everything else. Zero is the threshold. "Close enough" is not a category.

Write the explanation categories into the config (`explanations`) with the rule id that
makes them legitimate. A category without a rule is a guess.

## 4. What a red row means

| Symptom | Usual cause | Where to look |
|---|---|---|
| whole records only on one side | different seed data, or a job not run on one side | `java-run.json` vs `legacy/out/manifest.json` |
| one numeric field off by a factor of 10 or 100 | scale from the PIC not applied, or a worked example in a rule was wrong | the rule's `arithmetic`, `mapping.json` field |
| sign differs | `-fsign` flag, or the target writes `-` where the legacy writes an overpunch | export code uses `LegacyFormat.zoned` |
| last record / total missing | a legacy defect preserved on one side only | `legacy-defects` flags; the G1 preserve/fix decision |
| timestamps differ | not declared in `runtime_fields` | the pair config |
| a `FILLER` differs | the legacy carries data in a FILLER the schema dropped | `fidelity-report.md` FILLER row |

## 5. Into the evidence

`golden_master.py` writes `target/ops/out/golden-master-report.{md,json}`; each pair's
`use_cases` feed `use_case_coverage.py`; `evidence_pack.py --gate G6` reads the report.
Nothing is copied by hand. A pair that is `missing` on either side is red, not absent.
