---
name: 02-specification
description: Recover a natural-language specification from COBOL and supporting documents: sourced business rules, use cases, domain glossary, NFRs and open questions. Use on entering phase 2, before Gate 1.
---

# Phase 2 — Specification Recovery

**Input:** discovery outputs — `inventory.json`, `dependencies.json`, field maps
**Output:** `spec.md`, `business-rules.jsonl`, `traceability.json`,
`coverage-report.md`
**Exit gate:** G1 (business understanding) — Business Analyst **+ Architect + Product Owner**

This is the phase that determines whether the programme succeeds. Everything
downstream is generated from the artifact produced here, so an error in the spec
becomes an error in the Java, the tests, and the tests that "prove" the Java is
right.

It is also the only phase where three different people must approve, because the
spec is the one artifact that is simultaneously a technical description, a
business description, and a scope commitment.

---

## 1. What a recovered specification is

Not a translation of the code. Not a flowchart. It is **a description of the
business behaviour, written so that someone who has never seen the COBOL could
implement it and get the same answers.**

The test: hand `spec.md` to a Java developer with no mainframe background. If
they have to ask "but what does the original do here?", the spec is incomplete
at that point. Fix the spec, not the conversation.

Write it in the business's vocabulary, not the code's. `ACCT-CURR-CYC-CREDIT`
becomes "credits posted in the current billing cycle". Recovering that language
is much of the value — it is what makes the new system maintainable by people who
never learn COBOL. Mine the help text, user guides, screen literals and BMS field
labels for it; they are usually the only place the business words are written
down.

---

## 2. Business rules carry evidence

Every rule is a row in `business-rules.jsonl` and every rule cites the source
lines it came from. A rule without evidence cannot be reviewed, cannot be
verified, and cannot be defended to an auditor.

```json
{"id": "BR-0042",
 "domain": "Interest Accrual",
 "statement": "Monthly interest on a revolving balance is the current balance multiplied by the disclosure group's annual rate, divided by twelve, truncated to whole cents.",
 "evidence": [{"program": "CBACT04C", "paragraph": "1050-COMPUTE-INTEREST", "lines": [412, 419]}],
 "inputs": ["ACCT-CURR-BAL", "DIS-INT-RATE"],
 "outputs": ["WS-MONTHLY-INT"],
 "edge_cases": ["negative balance accrues no interest",
                "rate not found falls back to the DEFAULT disclosure group"],
 "arithmetic": {"rounding": "truncate", "scale": 2,
                "note": "COMPUTE without ROUNDED truncates"},
 "confidence": "high",
 "open_question": null}
```

Field notes that matter:

- **`statement`** is one sentence, in business language, stating a rule — not
  describing code. "Reads the disclosure group file" is not a rule; "the rate
  applied is the one on the account's disclosure group" is.
- **`arithmetic`** is mandatory for any rule that computes. Record rounding,
  scale and overflow behaviour explicitly. This is where money is silently lost;
  see `cobol-java-mapping.md`.
- **`edge_cases`** is where the real value is. The happy path is easy to
  recover and easy to test. The `AT END`, the `INVALID KEY`, the negative case,
  the not-found fallback, the "what if the field is spaces" — those are the ones
  that reach production as defects.
- **`confidence`** — `high` / `medium` / `low`. Be honest. A `low` with an
  `open_question` is a useful artifact; a confident guess is a liability.
- **`open_question`** — when the COBOL is genuinely ambiguous, or when the
  behaviour looks like a bug, **write the question, do not invent an answer.**
  These become the agenda for G1. This is the single most valuable thing the
  pipeline produces, because these questions are exactly what only the BA and
  the retiring engineer can settle.

### When the legacy behaviour looks wrong

Sometimes it is wrong. A rate applied to the wrong field, a boundary condition
off by one, an error path that silently continues. **Record it as the rule it
actually is, then flag it separately** as a `suspected_defect` with the evidence.

Do not silently fix it. Downstream consumers may depend on the wrong behaviour,
and a "fix" that changes output breaks the golden-master comparison — which is
the only equivalence evidence you have. Fixing it is a business decision for the
Product Owner at G1, and if they choose to fix it, it becomes a specified change
with its own test, not a quiet correction.

---

## 3. Traceability is built here, not retrofitted

Fill in `traceability.json` **as you write the rules**, not afterwards.
Retrofitting traceability produces traceability-shaped documentation that nobody
checked.

Every paragraph of every in-scope program gets exactly one classification:

| Status | Meaning | Requires |
|--------|---------|----------|
| `implemented` | Carries business logic that the new system must reproduce | ≥1 rule id |
| `not-applicable` | Housekeeping: screen paint, abend plumbing, IO status display, cursor positioning | `reason` |
| `delegated` | The framework now does it: file open/close, commit, paging, session state | `reason` |
| `dropped` | Deliberately not carried forward | `reason` **and** `approved_by` |

`dropped` is the only one that needs a human name attached, because it is the
only one that discards behaviour. Never mark something `dropped` on your own
judgement — surface it at G1 and record who agreed.

Check it continuously:

```bash
python scripts/trace_coverage.py \
    --source <source-root> \
    --traceability modernization/2-specification/traceability.json \
    --rules modernization/2-specification/business-rules.jsonl
```

The gate is 100%. Not 98%. The whole control depends on the arithmetic being an
identity — a 98% coverage figure tells you nothing about whether the missing 2%
was housekeeping or the entire fee calculation.

---

## 4. Recovering the things that are not in the code

**Screen flow.** In a pseudo-conversational CICS app, navigation is dynamic
dispatch through a menu table (Phase 1 found it). Read the table, not the XCTL
sites. Produce a screen-flow diagram: transaction → program → options → next
program. This becomes the frontend routing model in Phase 5.

**Batch topology.** JCL gives you steps and datasets; the *scheduler* gives you
the real dependencies, windows and restart points. If you only have JCL, say so
— the resulting job graph is a lower bound on the real constraints.

**Pseudo-conversational state.** COMMAREA content between screen interactions is
application state. Map it explicitly: what is carried, what is re-read, what is
re-derived. In the target this becomes request/response payloads plus server-side
session or a token — and getting it wrong produces subtle "the screen forgot my
selection" defects that are miserable to debug later.

**Data validation rules.** Scattered through the online programs as field edits.
These are business rules and belong in `business-rules.jsonl`, because the new
API must enforce them — the 3270 screen used to enforce some of them implicitly
through field attributes, and a JSON API has no such protection.

---

## 5. Structure of `spec.md`

Use `templates/specification.md`. Per domain:

1. **Purpose** — two or three sentences a Product Owner would recognise.
2. **Vocabulary** — the business terms, mapped to legacy data names. Put this
   early; it makes everything after it readable.
3. **Data owned** — entities, their meaning, their identity, their lifecycle.
4. **Processes** — one section per business process, with its trigger, inputs,
   steps (referencing rule ids), outputs, and failure behaviour.
5. **Business rules** — the rules table for this domain.
6. **Screens** — purpose, fields, validation, navigation.
7. **Batch** — jobs, schedule, dependencies, restart behaviour, volumes.
8. **Open questions** — every `open_question` and `suspected_defect`, collected.
9. **Non-functional** — volumes, windows, SLAs, retention, regulatory
   constraints. Usually the thinnest section and usually the one that causes
   trouble later; push for real numbers.

---

## 6. The G1 gate

Three approvers, three different questions. Say explicitly which is which —
reviewers who do not know what they are being asked to check will read the whole
document badly instead of their part well.

| Approver | Owns | Asked to confirm |
|----------|------|------------------|
| **BA** | Business correctness | Every rule is right, the vocabulary is right, the edge cases match how the business actually works |
| **Product Owner** | Scope and priority | Everything `dropped` should be dropped, every `suspected_defect` gets a fix-or-preserve decision, the open questions are answered |
| **Architect** | Technical completeness | The traceability is genuinely 100%, the NFRs are real numbers, the hazards have owners |

Lead the review pack with the **open questions and suspected defects**, not with
the spec. Those are the only parts that need the humans in the room; the rest
they can read. Concentrating their attention there is the difference between a
gate that catches errors and a gate that rubber-stamps.

State the cost of being wrong plainly: an error approved here is generated into
the Java, and the golden-master tests will then confirm that the Java faithfully
implements the wrong rule.

Then stop.

---

## 7. Mechanics — the scripts that run this phase

Phase 1 already produced two things this phase depends on:
`modernization/tools/paragraph-skeleton.json` (the gate's own paragraph list — the
only list agents may classify against) and
`2-specification/_fragments/plan.json` with one `WPn/brief.md` per work package
(`work_packages.py`: programs grouped by sub-application and data cluster, ~120
paragraphs each, disjoint rule-id ranges, the brief rendered from
`templates/work-package-brief.md`).

1. **Dispatch one agent per package** with its `brief.md` as the whole instruction.
   Batch the dispatches (three or four at a time); each agent writes incrementally, so
   a killed run resumes from what is already in its fragment directory. Do not write
   your own briefing — the template carries the nine absolute rules, including *worked
   examples quote real decoded values* and *never cite a rule id you have not written*.
2. **Merge and validate** — refuses to produce artifacts it cannot validate:
   ```bash
   python scripts/merge_fragments.py --workspace <out> --write
   ```
   Errors (id collisions, out-of-range ids, evidence that does not resolve, a paragraph
   unaccounted for) go back to the owning package's agent with the message verbatim.
3. **Cross-cutting recoveries** the packages cannot see whole: write
   `screen-flow.md`, `batch-topology.md`, `discovery-corrections.md` (what phase 1 got
   wrong — every fix is also a parser fix in `scripts/`), and `use-cases.jsonl` from
   the `### Processes` sections (`templates/use-cases.jsonl`; every use case lists its
   rule ids — the use-case coverage gate at G5 reads this file).
4. **Front matter** — `spec-front-matter.md` from `templates/spec-front-matter.md`:
   Purpose, NFRs (say which numbers are assumed), out of scope.
5. **Assemble and propose G1:**
   ```bash
   python scripts/verify_source_readonly.py --workspace <out>
   python scripts/assemble_spec.py --workspace <out>
   ```
   `spec.md`, `coverage-report.md`, `governance/gates/G1/{review-pack.md,manifest.json}`;
   `state.json` G1 = proposed, bound to the manifest hash. It refuses below 100 %
   traceability.
6. **Decide** — the approvers (or the operator under a recorded blanket authorization):
   ```bash
   python scripts/gate_decide.py --workspace <out> --gate G1 --decision approved-with-conditions --by <id> --condition "C1 ..."
   ```
   A changed artifact voids the decision; `gate_decide.py --check` proves it has not.
