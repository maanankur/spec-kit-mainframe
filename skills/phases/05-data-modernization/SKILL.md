---
name: 05-data-modernization
description: Convert copybook, VSAM, DB2 and IMS structures to the target SQL schema with type fidelity, migration scripts and reconciliation. Use on entering phase 5, before Gate 4.
---

# Phase 5 — Data Modernization

**Input:** field maps, DDL/DCLGEN, `crud-matrix.csv`, approved architecture
**Output:** `schema.sql`, `mapping.json`, migration jobs, `fidelity-report.md`
**Exit gate:** G4 (evidence gate) — Data Architect + DBA + Compliance countersign the machine-produced fidelity evidence; a red result cannot be approved, only waived. The phase itself is fully machine-verifiable, and a judgement gate here
would add delay without adding safety. It is verified instead by round-trip
proof (§6).

Data is where modernization projects actually fail. The logic can be re-derived
from the spec; corrupted data cannot be re-derived from anything.

---

## 1. The governing fact: a dataset is a blob with a copybook

There is no schema in a mainframe sequential file or VSAM dataset. There are
bytes. The copybook is the only description of what those bytes mean, and it is
not stored with the data — which is why the field map from
`scripts/copybook_parse.py` is the single source of truth for this entire phase.

Three consequences that drive everything below:

1. **The same bytes can have several meanings.** `REDEFINES` overlays a record
   with alternative layouts chosen by a discriminator field at runtime.
2. **Numbers are not text.** COMP-3 packs two digits per byte with a sign
   nibble; DISPLAY numerics carry the sign overpunched into the last byte's
   zone; COMP is big-endian binary. None of these survive a naive text read.
3. **Characters are EBCDIC.** Byte 0xC1 is `A`, not `Á`. Reading with the
   platform default charset produces mojibake that *sometimes looks fine* for
   digits, which is worse than failing outright.

---

## 2. Derive the schema from the field map, never by hand

```bash
python scripts/copybook_parse.py app/cpy/*.cpy \
    --out modernization/1-discovery/fieldmaps --strict
```

Each field carries a `sql_type` computed from its PIC and USAGE. Use it, then
apply judgement on top:

| Copybook says | Column | Why |
|---------------|--------|-----|
| `PIC S9(10)V99` (any usage) | `NUMERIC(12,2)` | Exact decimal. Never `FLOAT`/`DOUBLE`. |
| `PIC 9(11)` used as a key | `BIGINT` or `CHAR(11)` | If leading zeros are significant, keep it text |
| `PIC X(10)` holding `YYYY-MM-DD` | `DATE` | Convert, but keep the original in a staging column until verified |
| `PIC X(n)` | `VARCHAR(n)` | Trailing spaces are padding; trim on load. **Leading spaces may be data** |
| `FILLER` | omit | Unless it is undocumented data — check for non-space bytes before dropping it |
| 88-level condition names | `CHECK` constraint or enum | The 88s document the legal domain of the field; keep them |
| `OCCURS n` | child table, or array column | Child table if rows are addressed individually; array if the group is atomic |
| `OCCURS DEPENDING ON` | child table | Always. Variable cardinality is a relation. |
| `REDEFINES` | see §3 | Never two independent columns |

### Two things the copybook cannot tell you

- **Nullability.** COBOL has no NULL. Spaces, zeros, low-values and `HIGH-VALUES`
  all serve as "no value" in different fields, inconsistently. Decide per field
  and record it in `mapping.json`. Getting this wrong turns "unknown" into
  "zero", which silently changes sums.
- **Keys and referential integrity.** Copybooks have no keys. Get them from the
  VSAM cluster definitions (KSDS key offset/length), alternate index definitions,
  DB2 DDL, or the CSD `FILE` definitions. Do not infer a primary key from a field
  called `-ID` without checking uniqueness in the actual data.

If DDL or DCLGEN exists for a store, **it wins over the copybook** for types,
nullability and keys. The copybook is the program's view; the DDL is the data's.

---

## 3. REDEFINES becomes a discriminated union, never parallel columns

A record with overlays is a sum type. Modelling it as two nullable column sets
throws away the invariant that exactly one is valid, and someone will eventually
read the wrong one.

Options, in order of preference:

1. **Separate tables per record type**, keyed by the discriminator. Correct and
   queryable. Use this when the overlays are genuinely different entities — which
   they usually are, as in CardDemo's `CVEXPORT` where one 500-byte record can be
   a customer, an account, a transaction, a card or a cross-reference.
2. **Single table + `record_type` + a JSON column** for the variant payload.
   Reasonable when overlays are numerous, similar and rarely queried.
3. **Sealed interface / record hierarchy in Java** regardless of the storage
   choice, so the type system enforces what the bytes only implied.

When overlays are unequal in size the larger one runs past the redefined field
and into following data. `copybook_parse.py` warns about this. Resolve it before
migrating — it means the record's true layout depends on the discriminator, and a
fixed offset map is wrong for at least one variant.

---

## 4. VSAM → relational

| VSAM | Relational |
|------|------------|
| KSDS | Table with a primary key on the cluster key fields |
| Alternate index (AIX) | Secondary index; `UNIQUE` only if the AIX is |
| ESDS | Table with a surrogate key; RBA becomes a sequence |
| RRDS | Table keyed by relative record number |
| `STARTBR` / `READNEXT` browse | Keyset pagination — `WHERE key > :last ORDER BY key LIMIT n` |
| GDG generations | Partition by run date, or a versioned table |

**Browse semantics deserve care.** `STARTBR`/`READNEXT` is a stateful cursor
positioned at or after a key, and screens page through it. The naive translation
is `OFFSET`/`LIMIT`, which is both slow and *wrong* under concurrent
modification — rows shift between pages. Use keyset pagination and carry the last
key in the API response.

## 5. DB2 → PostgreSQL

Mostly mechanical. The parts that are not:

| DB2 | PostgreSQL | Watch for |
|-----|------------|-----------|
| `DECIMAL(p,s)` | `NUMERIC(p,s)` | Direct |
| `CHAR(n)` | `CHAR(n)` or `VARCHAR(n)` | DB2 `CHAR` is blank-padded and comparisons ignore trailing blanks; Postgres `VARCHAR` does not. Changing this changes `=` results |
| `TIMESTAMP` | `TIMESTAMP` | DB2 supports up to 12 fractional digits, Postgres 6. Check precision use |
| `WITH UR` (dirty read) | — | No equivalent. Decide per query: `READ COMMITTED` or an explicit snapshot |
| `FETCH FIRST n ROWS ONLY` | `LIMIT n` | Direct |
| `VALUE()` | `COALESCE()` | Direct |
| Cursors with `FOR UPDATE` | `SELECT ... FOR UPDATE` | Lock scope and duration differ; re-check the transaction boundaries |
| `SQLCODE` checks | SQLState / exceptions | `+100` (not found) is a normal control-flow value in COBOL, not an error |

That last row causes real bugs. COBOL routinely uses `SQLCODE = +100` as an
ordinary "no more rows" branch. Translating it into an exception turns normal
flow into error handling and changes behaviour.

---

## 6. Migration and the fidelity proof

Decode with the field map, never with an ad-hoc reader:

```bash
python scripts/decode_record.py \
    --fieldmap modernization/1-discovery/fieldmaps/CVACT01Y.fieldmap.json \
    --data data/EBCDIC/ACCTDATA.PS \
    --encoding cp037 --format csv --out staging/account.csv
```

For records with overlays, select the variant explicitly:

```bash
python scripts/decode_record.py --fieldmap fieldmaps/CVEXPORT.fieldmap.json \
    --data data/EXPORT.PS --encoding cp037 \
    --redefines-when EXPORT-REC-TYPE=C:EXPORT-CUSTOMER-DATA
```

### The three checks that must pass before the data is trusted

1. **Round trip.** Decode → load → read back → re-encode → compare bytes with
   the original file. Byte-identical, or the difference is explained in writing
   (trailing-space normalisation is a legitimate explanation; a changed amount is
   not). This is the strongest single proof available and it is cheap.

2. **Aggregate reconciliation.** For every numeric column: row count, sum, min,
   max, count of negatives, count of nulls — computed on the source file and on
   the loaded table, compared. A sum that matches to the cent across a million
   rows is very strong evidence that decoding, sign handling and scale are all
   correct. A mismatch localises the problem immediately.

3. **Edge-case sweep.** Explicitly find and check: negative values, zero,
   maximum-precision values, uninitialised fields (spaces or low-values in a
   numeric), `HIGH-VALUES` keys (often a sentinel meaning "end"), and every
   distinct value of each discriminator. These are where decoders break.

Write the results into `fidelity-report.md`. If any check fails, stop — a data
defect that reaches Phase 5 will be reported by the golden-master tests as a
logic defect and you will debug the wrong thing.

### Encoding: name it, always

`cp037` is US EBCDIC and the usual answer for z/OS. Other codepages exist and
differ in exactly the characters that matter (`[`, `]`, `!`, `#`, and every
national character). Confirm the codepage rather than assuming; a wrong codepage
corrupts text while leaving digits intact, so the errors are subtle and survive
casual inspection.

In Java, name the charset at every boundary — `Charset.forName("Cp037")` — and
never rely on the platform default. `scripts/jobol_lint.py` fails the build on
`new FileReader(f)` and `getBytes()` for exactly this reason.

---

## 7. `mapping.json`

The record of every decision made here, so that Phase 5 generates code from it
and the fidelity harness checks against it:

```json
{"stores": [
  {"legacy": "ACCTDAT", "kind": "vsam-ksds", "copybook": "CVACT01Y",
   "table": "account", "primary_key": ["acct_id"],
   "record_length": 300, "encoding": "cp037",
   "fields": [
     {"cobol": "ACCT-ID", "offset": 0, "length": 11,
      "column": "acct_id", "type": "BIGINT", "nullable": false},
     {"cobol": "ACCT-CURR-BAL", "offset": 12, "length": 12,
      "column": "curr_bal", "type": "NUMERIC(12,2)", "nullable": false,
      "note": "zoned decimal, sign overpunched on the trailing byte"},
     {"cobol": "FILLER", "offset": 122, "length": 178, "column": null,
      "note": "verified all-spaces across 50 sample records; dropped"}]}]}
```

Note the FILLER entry. Dropping filler is right, but *verify it is empty first* —
undocumented data hiding in filler is common in systems of this age, and it is
usually something someone still depends on.

---

## 8. Mechanics — the scripts that run this phase

```bash
python scripts/store_map.py --workspace <out>        # proposes 5-data/store-map.json (never overwrites; --force)
# confirm it: one copybook per store, owner/schema, sample, migrate, redefines_when
python scripts/datamod.py --workspace <out>          # schema.sql, mapping.json, fidelity-report.md, migration/*, G4 proposed
python scripts/gate_decide.py --workspace <out> --gate G4 --decision waived --by <id> --control "Production extracts=…"
```

`store_map.py` is deterministic where it can be: cluster names, `KEYS(len off)`,
`RECORDSIZE` and alternate indexes from the IDCAMS `DEFINE` statements in the JCL; the
flat sample DSN from `REPRO`; the canonical store name from `dependencies.json`; the
owning context (→ schema) from `decomposition.json`; the copybook from the program's
`FD … COPY`, else by field-name overlap between the inline FD record and the candidate
copybooks of matching record length. Every entry it had to guess carries
`confirm: true` and its candidates. **Confirm every one of them** — the byte round trip
in `fidelity-report.md` will expose a wrong copybook (sign nibbles, offsets) but only
after you have spent a run. Set `production_extracts_supplied` to true only when the
fidelity run was executed on production extracts; otherwise that row is red and is
waived, never approved.

`datamod.py` refuses a migrated store without a copybook; a store you do not migrate
needs `migrate: false` and a note, not a copybook. DB2 entries take `schema`,
`ddl_schema_prefix`; IMS entries list `segments` (copybook, table, primary key,
materialised parent key columns).
