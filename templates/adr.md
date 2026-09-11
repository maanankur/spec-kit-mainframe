# Target Architecture — <System Name>

> Approved at G3 by Architect and Product Owner.
> Four questions this document must answer: what are the domains, which are
> services, in what order, and what did we assume.

## 1. Domains
| ID | Domain | Programs | Owned stores | Shared stores | Verdict |
|---|---|---|---|---|---|
| D01 | | | | | module / service |

Deviations from the computed clusters in `dependencies.json`, each with an ADR:
| Cluster | Change | Reason | ADR |
|---|---|---|---|

## 2. Monolith / microservice scores
0–3 per axis. Score 0 on **data ownership** or **transactional independence**
forces `module` regardless of total.

| Domain | Load | Ind. scale | Change freq | Data own | Txn indep | Avail | Team | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| D01 | | | | | | | | | |

Assumed scores (no evidence available) — **raise these at the gate**:
| Domain | Axis | Assumed value | What evidence would settle it |
|---|---|---|---|

## 3. Technology
| Layer | Choice | Rationale |
|---|---|---|
| Backend | Java 21 / Spring Boot 3.x | |
| API | REST / JSON | |
| Batch | Spring Batch | |
| Frontend | React / Angular — **choose one** | |
| Database | PostgreSQL | |
| Migration pattern | Strangler fig, routed by transaction | |

**UI scope:** reproduce screen flow and field semantics; redesign is separate,
later, funded work. Confirm the Product Owner understands this.

## 4. Wave plan
| Wave | Domains | Screens | Jobs | Rationale | Proves |
|---|---|---|---|---|---|
| 1 | | | | deliberately low-risk | the pipeline, harness and deploy path |

Wave 1 is not meant to be impressive. State that here.

## 5. Cross-cutting decisions
| Concern | Decision | ADR |
|---|---|---|
| Authn / authz (replacing RACF) | | |
| Locking strategy (replacing VSAM record locks) | | |
| Reference data (shared read-mostly stores) | | |
| Transaction boundaries | | |
| Error contract | | |
| Observability | | |

## 6. Risks
| Risk | Impact | Likelihood | Mitigation | Owner |
|---|---|---|---|---|

## 7. Decisions requested
| Approver | Decision | Cost if wrong |
|---|---|---|
| Architect | Domain boundaries and module/service verdicts | Found in a later wave; rewrite of everything built on it |
| Product Owner | Wave order; reproduce-not-redesign UI scope | Business value arrives late; UI expectations unmet |
