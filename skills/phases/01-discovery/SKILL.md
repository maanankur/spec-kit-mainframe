---
name: 01-discovery
description: Inventory, classify and graph a mainframe codebase: dependency graph, CRUD matrix, copybook field maps, transaction and batch inventory, data lineage. Use on entering phase 1 of a modernization, or for a standalone legacy assessment.
---

# Phase 1 — Discovery & Inventory

**Input:** the legacy source tree (and whatever else the client can find)
**Output:** `inventory.json`, `dependencies.json`, `crud-matrix.csv`,
`fieldmaps/*.fieldmap.json`, `discovery-report.md`
**Exit gate:** none — discovery is deterministic and needs no approval. Gate 1 (business understanding) follows Phase 2.

The purpose of this phase is a census, not an interpretation. Nothing here
requires judgement about what the code *means* — that is Phase 2. Resist the
urge to start explaining the business logic; you will do it better after the
graph is in front of you.

---

## 1. Collect inputs

Source code is necessary and not sufficient. Ask for all of these, and record
which ones you did not get — a missing input is a known unknown that belongs in
the report, not a gap to paper over.

| Input | Why it matters | If missing |
|-------|----------------|------------|
| COBOL programs, copybooks | The system | Blocker. Stop. |
| JCL, PROCs | Batch entry points, job ordering, dataset wiring | Batch topology must be reconstructed from the scheduler |
| CICS CSD | Transaction → program bindings, i.e. online entry points | Entry points must come from the menu programs |
| BMS maps | Screen layouts and field semantics | Screens must be inferred from the COMMAREA copybooks |
| **DDL / DBD / DCLGEN** | Real column types, keys, constraints | Types must come from copybooks, which lose nullability and keys |
| **Sample datasets** | The only way to verify decoding and build golden masters | Verification is severely weakened — flag as a risk at G1 |
| **Release notes / change history** | Change frequency for the Phase 3 scoring; where the churn is | Score axis 3 becomes an assumption |
| **Test cases, UAT scripts** | Expected behaviour, edge cases, and the acceptance bar | Tests must be derived from the spec alone |
| Help text, user guides, run books | Business vocabulary and intent — often the only place a rule is written down | Naming will be worse; ambiguities go to G2 |
| SMF / CICS stats / job accounting | Real volumes for Phase 3 axes 1–2, and proof of what actually runs | Load scoring becomes an assumption |
| Scheduler definitions | True job dependencies and windows | Job order must come from JCL alone |

Two of these are worth pushing hard for, because they change the quality of the
outcome more than anything else on the list:

- **Sample production-shaped data.** Without it there is no golden master, and
  equivalence becomes an opinion. Masked or synthetic data is fine; it needs to
  be *shaped* like production, not real.
- **SMF or equivalent runtime data.** It tells you what actually executes.
  Codebases of this age typically carry 15–40% dead code, and paying to convert
  and verify it is pure waste.

---

## 2. Run the deterministic pass

```bash
python scripts/inventory.py <source-root> \
    --out modernization/1-discovery/inventory.json \
    --csv modernization/1-discovery/programs.csv --print

python scripts/depgraph.py \
    --inventory modernization/1-discovery/inventory.json \
    --out-dir modernization/1-discovery \
    --mermaid modernization/1-discovery/callgraph.mmd --print

python scripts/copybook_parse.py <copybook-dir>/*.cpy \
    --out modernization/1-discovery/fieldmaps --strict
```

Do not hand-derive anything these produce. If a number in your report disagrees
with the JSON, the report is wrong.

### Verify the field maps against something external

Copybook parsing is the foundation of the whole data path, so check it before
trusting it. Record lengths are usually documented somewhere — a comment in the
copybook (`RECLN 300`), a dataset table in a README, the JCL `LRECL`, or an
`FD` block. Compare and reconcile every mismatch before Phase 4.

```bash
# does the field map's record length match the dataset's actual size?
python -c "import json;d=json.load(open('fieldmaps/CVACT01Y.fieldmap.json'));\
print(d['records'][0]['length'])"
ls -l data/ACCTDATA.PS      # size should be an exact multiple
```

A record length that does not divide the file evenly means the layout is wrong,
the file is variable-length (RECFM=VB, needs `--rdw`), or there is a header. Find
out which. Do not proceed on a guess.

---

## 3. Read the graph and write down what surprised you

The scripts produce facts. Your job is to notice which facts are load-bearing.
Look specifically for:

**Dynamic dispatch.** `depgraph.py` reports `dynamic_dispatch` — CALL or XCTL
through a variable. In a CICS pseudo-conversational application this is normal
and it means *the screen flow cannot be recovered from call sites*. It lives in a
navigation table instead, usually a copybook of menu options mapping an option
number to a program name. Find that table and read it; otherwise the navigation
model in Phase 2 will be fiction. In CardDemo the tables are `COMEN02Y` (user
menu) and `COADM02Y` (admin menu), dispatched through `CDEMO-TO-PROGRAM`.

**Unreachable programs.** Reported as `unreachable_programs`. These are *dead
code candidates*, not dead code. A program can be unreachable from the source
you were given and still run in production — triggered by a scheduler you were
not shown, an operator-submitted job, or a CSD group in another region. **Only a
human can confirm a program is dead**, which is most of what G1 is for.

**Shared stores.** In `crud-matrix.csv`, a store with several writers across
different clusters is where a naive decomposition will break. Note each one now;
Phase 3 has to resolve them.

**Hazards.** Per-program in `inventory.json`: `ALTER`, `GO TO DEPENDING ON`,
sort input/output procedures, `ENTRY` points, pointer arithmetic, `COMP-1`/`COMP-2`
floats. Each needs a named human owner and a decision before its wave starts —
they are not auto-convertible and finding that out mid-wave is expensive.

**Missing copybooks.** `missing_copybooks` (as distinct from `vendor_copybooks`,
which are IBM-supplied and expected to be absent) is a hard blocker: a missing
copybook is an unknown record layout, and every field derived from it is a guess.
Get the file.

---

## 4. Complexity ranking

`inventory.json` carries a McCabe-style `complexity` per program. Use it for
**ranking only** — it is an approximation over comment-stripped source, adequate
for deciding what to tackle when, and not a metric to report to management as if
it were measured.

The distribution matters more than any single value. A codebase with one
3,000-line program at complexity 700 and forty programs under 150 needs a very
different plan from one with uniform 500-line programs: the first has a single
concentrated risk you can schedule around, the second has diffuse risk you
cannot.

---

## 5. The G1 gate

Write `discovery-report.md` for a tech lead who knows the system and has twenty
minutes. Lead with the four things only they can answer:

1. **Is this the whole system?** Show the inventory counts and the entry points.
   Ask directly what is missing.
2. **Are these programs actually dead?** List the unreachable ones with their
   size, and ask for a yes/no on each. Every confirmed-dead program is work you
   never have to do; every wrongly-declared-dead program is a production
   incident.
3. **Are these the real entry points?** Transactions and jobs found, plus the
   dynamic dispatch tables.
4. **Who owns each hazard?** Name a person per item.

Also state your own confidence honestly. Where a record layout is unverified,
where a dataset would not decode, where the CRUD matrix is inferred from OPEN
mode rather than explicit verbs — say so. The report's value is that a reader can
tell which parts are counted and which parts are inferred.

Then stop. Phase 2 depends on the scope being right, and re-doing Phase 2 is
much more expensive than one more conversation now.
