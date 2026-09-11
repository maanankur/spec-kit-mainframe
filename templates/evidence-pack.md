# Evidence Pack — Wave <N>

> Reviewed at G4 by Product Owner and Ops. You are confirming the evidence is
> sufficient and the residual risks are acceptable — **not** reviewing code.

| | |
|---|---|
| Wave | <N> |
| Domains | |
| Programs replaced | |
| Verified on | <date, build> |

## 1. Summary
| Level | Check | Result | Threshold | Pass |
|---|---|---|---|---|
| 1 | Traceability completeness | /  | 100% | |
| 2 | Golden master — records compared | | 0 mismatches | |
| 2 | Rules exercised by the corpus | / | reported | — |
| 3 | Round trip | | byte-identical | |
| 3 | Aggregate reconciliation | | exact | |
| 4 | Rule coverage | / | 100% | |
| — | jobol-lint | <e> errors, <w> warnings | 0 errors | |
| — | Batch window | <new> vs <legacy> | ≤ legacy | |
| — | Online p95 | | | |
| — | Restart / idempotency | | correct | |
| — | Concurrency | | no lost updates | |

## 2. Differences found and resolved
| # | Difference | Root cause | Resolution | Rule / spec change |
|---|---|---|---|---|

## 3. NOT verified — residual risk
> A pack claiming full verification is not credible. Be specific.

| Item | Why not verified | Risk | Accepted by |
|---|---|---|---|
| Rules not exercised by the golden-master corpus: <ids> | no sample data on that path | | |

## 4. Accepted lint warnings
| Rule | Count | Why accepted |
|---|---|---|

## 5. Acceptance
| Approver | Role | Decision | Date |
|---|---|---|---|
| | Product Owner | accept / reject | |
| | Ops | accept / reject | |
