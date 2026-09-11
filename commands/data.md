---
description: "Phase 5 — schema and field mapping from copybooks/IDCAMS/DDL, byte-level fidelity proof, migration kit; propose Gate G4 (evidence gate)"
---


# Phase 5 — data modernization

Arguments: `$ARGUMENTS`

Before acting:

1. Read `mainframe-config.yml` in `.specify/extensions/mainframe/` (source path, output path, profile, industry, approvers, `auto_approve`). Command arguments override it.
2. Read `<output>/modernization/state.json`. If it is absent, run __SPECKIT_COMMAND_MAINFRAME_MODERNIZE__ first.
3. Run `python .specify/extensions/mainframe/scripts/verify_source_readonly.py --workspace <output>` — the legacy source tree is read-only, always.
4. Verify the preceding gate is approved and its artifact hashes still match: `python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <output> --check`. If not, stop and report which approval is void.
5. The phase skill text is in `.specify/extensions/mainframe/skills/phases/` — read the one for this phase; load a technique from `.specify/extensions/mainframe/skills/techniques/` only when its trigger appears.


## Procedure

Read `.specify/extensions/mainframe/skills/phases/05-data-modernization/SKILL.md` §1-7 (a dataset is a blob with a copybook; REDEFINES; VSAM → relational; DB2 → target; the three checks), then:

## 8. Mechanics — the scripts that run this phase

```bash
python .specify/extensions/mainframe/scripts/store_map.py --workspace <out>        # proposes 5-data/store-map.json (never overwrites; --force)
# confirm it: one copybook per store, owner/schema, sample, migrate, redefines_when
python .specify/extensions/mainframe/scripts/datamod.py --workspace <out>          # schema.sql, mapping.json, fidelity-report.md, migration/*, G4 proposed
python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <out> --gate G4 --decision waived --by <id> --control "Production extracts=…"
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
