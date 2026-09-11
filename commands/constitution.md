---
description: "Add the mainframe-modernization non-negotiables to the project constitution (.specify/memory/constitution.md)"
---


# Constitution — modernization principles

Arguments: `$ARGUMENTS`

Append the following section to `.specify/memory/constitution.md` if it is not already present (idempotent; keep the file's existing numbering style), then bump the constitution version's MINOR number and record the amendment date.

## Mainframe modernization — non-negotiables

1. **Humans approve intent, machines verify fidelity.** No human is asked to certify generated code correct by reading it; humans approve the specification and the architecture, equivalence is proven by the golden-master harness.
2. **The specification firewall.** Target code is generated from the approved specification, never transliterated from COBOL; the build step has no read path to the legacy source.
3. **Deterministic before generative.** No agent asserts a fact a parser can compute: offsets, paragraph lists, keys, record lengths come from the scripts.
4. **The legacy source tree is read-only.** Verified by hash before every gate.
5. **Nothing is "not accounted for".** Every COBOL paragraph is classified implemented / not-applicable / delegated / dropped; 100 %% is the gate, and `dropped` needs a named approver.
6. **Every business rule cites its evidence** (program, paragraph, lines) or it is not written; ambiguity becomes an open question, never an invented answer; a suspected legacy defect is preserved and flagged, never silently fixed.
7. **Money is `BigDecimal`** with explicit rounding taken from the rule's arithmetic block.
8. **Gates are hash-bound.** A changed artifact voids its approval. Judgement gates (G1-G3) are approved, approved with conditions, or rejected; evidence gates (G4-G7) are countersigned when green and can only be **waived** — owner, compensating control, expiry — when red. Never approved red.
9. **A wave is done when its evidence pack is green** — executed tests (surefire and failsafe), generated use-case coverage, golden master with zero unexplained differences — not when it compiles.
10. **Report outcomes honestly.** A failed check is reported with its output; a skipped check is named; residual risk is listed with an owner.

Then confirm to the user what was added and where.
