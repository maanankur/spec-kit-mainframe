---
name: 03-domain-decomposition
description: Derive bounded contexts, aggregates and ownership from business rules and the CRUD matrix. Use on entering phase 3, before Gate 2. Read only the decomposition sections.
---

# Phase 3 — Domain Decomposition

**Input:** the G1-approved specification (`spec.md`, `business-rules.jsonl`,
`use-cases/`), `dependencies.json` (clusters), `crud-matrix.csv`
**Output:** `3-domain/context-map.md`, `3-domain/decomposition.json`,
`3-domain/glossary.md`
**Exit gate:** G2 (boundaries) — Architect + Product Owner + Domain SMEs

> Until 2026-09-10 this file was a copy of the target-architecture skill, so the
> phase had no guidance of its own. Found during the first CardDemo run.

Phase 2 said *what the system does*. This phase decides *where the seams are*.
It comes **before** architecture on purpose: monolith-vs-microservice is a
per-context decision, and you cannot make it before the contexts exist.

---

## 1. Start from evidence, not from the org chart

`dependencies.json` already groups programs by shared-write data coupling
(`clusters`). `crud-matrix.csv` says who reads and writes every store. The
business rules carry a `domain` each. Those three are the raw material; the
domain SMEs supply what none of them can — which capabilities the business
actually thinks of as one thing.

Procedure:

1. Lay the clusters out. Each is a **candidate** context.
2. Overlay the rules' `domain` labels. Where one cluster carries rules from two
   business domains, it is probably two contexts sharing a table — note the table.
3. Overlay the use cases. A use case that spans two candidate contexts is either
   a cross-context process (fine — it becomes a saga or an orchestrating
   application service) or a sign the boundary is wrong. Decide which and say why.
4. Extract **reference data** (transaction types, disclosure groups, code
   tables) into a read-mostly reference context. It is not a domain; everything
   reads it.
5. Extract **shared utilities** (date validation, common commarea handling)
   into a platform/shared-kernel context. They are wave 0, not a domain.

Record every departure from the computed clusters with a reason. If a boundary
cannot be justified in two sentences to a domain SME, it is wrong.

## 2. What a bounded context needs before it is one

| Element | Test |
|---|---|
| **Name in the business's vocabulary** | A Product Owner recognises it without explanation |
| **Owned data** | Every store it writes is written by no other context; shared writes are listed and resolved (owner chosen, others become readers or events) |
| **Aggregates** | Each cluster of entities changed together in one legacy transaction is one aggregate with one root; identity and invariants named |
| **Rules** | Every `BR-nnnn` belongs to exactly one context |
| **Use cases** | Every use case has a home context (the one whose aggregate it changes) |
| **Domain events** | Every point where one context's change is consumed by another — today usually a shared file or a batch step — is named as an event or a query |
| **Ubiquitous language** | Its terms are in `glossary.md` with the legacy data name beside each |

Nothing is "shared". A store with two writers has an owner and a migration note,
or the two contexts are one.

## 3. `decomposition.json`

```json
{"contexts": [
  {"id": "BC-03", "name": "Transaction Posting",
   "clusters": ["C03"], "programs": ["CBTRN02C", "CBTRN03C"],
   "owned_stores": ["TRANSACT", "TCATBALF", "DALYREJS"],
   "reads": ["ACCTDAT", "CCXREF", "TRANTYPE", "TRANCATG"],
   "aggregates": [{"root": "PostedTransaction", "entities": ["TransactionCategoryBalance"],
                   "identity": "TRAN-ID"}],
   "rules": ["BR-0560", "BR-0561"], "use_cases": ["UC-14", "UC-15"],
   "events_out": ["TransactionPosted", "TransactionRejected"],
   "events_in": ["AccountBalanceChanged"],
   "shared_write_resolution": [{"store": "ACCTDAT", "owner": "BC-02",
     "note": "posting updates balances via BC-02 command, not direct write"}],
   "confidence": "high", "adr": null}]}
```

Confidence is honest: `low` where the SMEs disagreed or the legacy coupling is
so dense that any cut is a judgement.

## 4. `context-map.md`

A diagram (Mermaid) of contexts and the relationships between them — upstream /
downstream, customer-supplier, conformist, shared kernel, anti-corruption layer
— plus one paragraph per context: purpose, owned data, main use cases, biggest
uncertainty. This is the document the G2 reviewers actually read.

## 5. Glossary

`glossary.md`: business term → legacy data names → meaning → owning context.
Built from Phase 2's per-domain vocabulary tables, de-duplicated and reconciled.
Two contexts using one word for two things is a finding; fix the names now.

## 6. The G2 gate

Three approvers, three questions:

| Approver | Asked to confirm |
|---|---|
| **Domain SMEs** | The contexts are how the business actually thinks; the glossary is right |
| **Product Owner** | Every use case has a home; nothing the business cares about fell between contexts |
| **Architect** | Every store has one owner; every cross-context interaction is named; the decomposition is buildable |

State the cost of being wrong: a boundary approved here becomes a module or
service boundary at G3 and a package boundary in the code. Moving it after wave
2 is a rewrite of everything on both sides.

Lead with the `low`-confidence contexts and the shared-write resolutions. Then
stop. Do not begin Phase 4 until G2 is recorded.

---

## 7. Mechanics — the scripts that run this phase

The boundaries are judgement and are written to `3-domain/contexts.json`
(`templates/contexts.json`): id, name, kind, programs, owned stores, purpose,
aggregates, events, confidence, rationale; plus `shared_write_resolutions`,
`relationships` and the `decisions` the approvers must make. Store names are the
canonical names from `1-discovery/dependencies.json` (`store_identity.resolved_to`);
add `store_aliases` only for names the deterministic plane could not resolve, and say
why in `decisions`. Every program in `inventory.json` must be in exactly one context.

Everything else is computed so it cannot drift from the phase-1/2 facts:

```bash
python scripts/decompose.py --workspace <out>
```

writes `decomposition.json` (rules per context by evidence, cross-context reads,
shared-write resolutions, unowned stores, validation errors), `context-map.md`
(mermaid map with computed edges, relationship table, per-context rationale, the
decisions) and `glossary.md` (from the work packages' vocabulary tables, conflicts
flagged), then proposes G2. It exits non-zero on unassigned programs or a program in
two contexts — fix `contexts.json`, do not edit the outputs. Decide with
`gate_decide.py --gate G2 …`.
