---
name: 04-target-architecture
description: Design the target architecture: monolith-vs-microservices decision per bounded context, C4 models, ADRs, NFR allocation and the wave plan. Use on entering phase 4, before Gate 3.
---

# Phase 4 — Target Architecture

**Input:** the approved specification (G1), the approved domain decomposition (G2), `dependencies.json`, `crud-matrix.csv`
**Output:** `architecture.md`, `decomposition.json`, `wave-plan.md`, `adr/ADR-*.md`
**Exit gate:** G3 — Chief Architect + Product Owner + Ops Lead

Phase 2 said *what the system does*. This phase decides *what shape the new one
takes*, and it is the last cheap decision in the programme. After G3, changing
the decomposition means rewriting code.

---

## 1. Start from the clusters, not from the org chart

`depgraph.py` has already grouped programs by **shared-write data coupling**.
That grouping is the honest starting point for domain boundaries, because it
reflects what the code actually does rather than what the team is called.

Then correct it with domain knowledge, which the graph cannot have:

- **Split a cluster** when the graph joined two genuinely different business
  capabilities that happen to touch one table. Common with a "master" file that
  everything writes a status flag into.
- **Merge clusters** when a business transaction spans both and must be atomic.
- **Extract a shared reference store** (rate tables, transaction-type codes,
  disclosure groups) into read-mostly reference data. It is not a domain; it is
  a lookup that many domains read. Replicate it or expose it as a query API.

Record every deviation from the computed clusters as an ADR. If a boundary
cannot be justified in two sentences, it is wrong.

---

## 2. Monolith or microservice — decide per domain, with a score

**This is not one decision for the system. It is one decision per domain**, and
the answer is usually mixed. A banking platform where loan origination is a
module and EMI posting is a service is not inconsistent; it is correct.

### Default posture

> **Modular monolith first. Extract a service only where the score demands it.**

A modular monolith with clean internal boundaries can be split later at
manageable cost. A premature split cannot be undone cheaply, and the usual
result is a distributed monolith: the coupling of a monolith plus the latency,
partial failure and debugging cost of a distributed system. Starting monolithic
is the reversible choice, and reversibility is worth a lot when the
specification was reverse-engineered.

### Scoring model

Score each domain on seven axes, **0–3**. Sum is 0–21.

| # | Axis | 0 | 1 | 2 | 3 |
|---|------|---|---|---|---|
| 1 | **Throughput / peak load** | rare, batch-only | thousands/day | steady online | high volume, spiky |
| 2 | **Independent scaling** | load tracks everything else | mild difference | clearly different curve | own curve, own peaks |
| 3 | **Change frequency** | stable for years | occasional | quarterly | frequent / regulatory churn |
| 4 | **Data ownership** | writes stores others write | mostly shared | mostly exclusive | fully exclusive |
| 5 | **Transactional independence** | needs ACID with others | some cross-domain writes | eventual consistency acceptable | fully self-contained |
| 6 | **Availability / blast radius** | same SLO as the rest | slightly different | distinct SLO | must survive others failing |
| 7 | **Team ownership** | one team owns everything | shared ownership | a team could own it | a team already does |

**Reading the score:**

| Score | Verdict |
|-------|---------|
| 0–7 | **Module** in the monolith. Do not discuss further. |
| 8–13 | **Module now, extraction candidate.** Enforce the boundary in code — own package, own schema, no cross-domain joins, interaction only through an interface — so extraction later is mechanical. |
| 14–21 | **Service.** Only if axes 4 and 5 both score ≥ 2. |

### The override that prevents most bad splits

> **If axis 4 (data ownership) or axis 5 (transactional independence) scores 0,
> the domain stays a module regardless of total score.**

A high total driven by load and change frequency is tempting, but a domain that
cannot own its data cannot own its transactions. Splitting it buys a distributed
transaction — a saga, compensating actions, reconciliation, and a new class of
production incident — in exchange for scaling you could have got by running more
instances of the monolith. Scale the deployment, not the diagram.

### Worked example — the loan / EMI case

| Axis | Loan origination | EMI schedule & posting |
|------|------------------|------------------------|
| 1 Throughput | 1 — applications are low volume | 3 — every active loan, every cycle, in a batch window |
| 2 Independent scaling | 1 — tracks branch hours | 3 — spikes hard at month end, idle otherwise |
| 3 Change frequency | 2 — product and policy changes | 1 — the amortization formula is stable |
| 4 Data ownership | 1 — reads customer, credit, collateral, product | 3 — owns schedule and instalment rows |
| 5 Transactional independence | 0 — disbursal must be atomic with account and ledger | 2 — posting can be eventually consistent, then reconciled |
| 6 Availability | 1 — branch-hours availability is enough | 2 — the cycle must not be missed |
| 7 Team | 1 | 2 |
| **Total** | **7 → Module** | **16 → Service** |

Loan origination scores 0 on transactional independence, so the override applies
and it would remain a module even at a higher total. EMI posting scores ≥2 on
both gating axes and has a genuinely different load curve, so it earns its own
service. This reproduces the intended answer — and shows *why*, which is what
makes the model reusable on the next domain.

Record each domain's scores in `decomposition.json`:

```json
{"domains": [
  {"id": "D03", "name": "EMI Scheduling",
   "clusters": ["C02"], "programs": ["CBTRN02C", "CBTRN03C"],
   "scores": {"throughput": 3, "independent_scaling": 3, "change_frequency": 1,
              "data_ownership": 3, "transactional_independence": 2,
              "availability": 2, "team": 2},
   "total": 16, "verdict": "service",
   "owned_stores": ["INSTALMENT", "SCHEDULE"],
   "rationale": "Month-end spike, exclusive ownership of schedule rows.",
   "adr": "ADR-004"}]}
```

Do not fill these in by inference where evidence exists. Axes 1 and 2 come from
runtime data (SMF records, CICS statistics, job accounting, scheduler history)
if the client can supply it; axis 3 comes from release notes and change history.
Where there is no evidence, **write "assumed" next to the score** and raise it at
G3. An unmarked guess in this table becomes an unexamined architectural
commitment.

---

## 3. Target technology

Fixed unless the client mandates otherwise:

| Layer | Choice | Notes |
|-------|--------|-------|
| Backend | Java 21 LTS, Spring Boot 3.x | Records for DTOs, virtual threads for I/O-bound batch |
| API | REST, JSON | See `cics-jcl-mapping.md` for the screen→endpoint derivation |
| Batch | Spring Batch | One job per JCL job, one step per JCL step |
| Frontend | React (TypeScript) or Angular | One choice for the whole programme; do not mix |
| Database | PostgreSQL | DB2-compatible enough; see `04-data-modernization.md` |
| Migration | Strangler fig | Route by transaction, not by screen |

### Frontend: React or Angular

Ask once, at G3, and record it. If the client has no preference:

- **Angular** if the team is Java-heavy and new to frontend work. Opinionated
  structure, DI and typing that will feel familiar, batteries included. Mainframe
  screens are dense forms, which is Angular's strongest suit.
- **React** if there is existing frontend capability or the UI will be
  substantially redesigned rather than reproduced.

Either way, **do not reproduce BMS screens one-for-one in the long run.** A 3270
map is shaped by a 24×80 character grid, PF-key navigation and pseudo-conversational
state. Reproducing it faithfully gives users a worse version of what they had.
The pragmatic route: reproduce the *screen flow and field semantics* first so the
existing users can work and UAT can compare like with like, and treat UI redesign
as a separate, later, funded piece of work. Say this explicitly at G3 so nobody
expects a redesign that is not in scope.

---

## 4. Wave plan — least complex first

Order the waves. This is a sequencing problem with real constraints, and getting
it wrong front-loads all the risk.

**Sequencing score** per domain — lower goes first:

```
wave_score = complexity_rank
            + 2 x (number of domains it depends on)
            + 2 x (1 if it has an unresolved hazard)
            - 2 x (1 if it exclusively owns all its stores)
```

Then apply the hard constraints, which override the score:

1. **Reference data first.** Nothing works without transaction types, rate
   tables and code lookups. These are usually trivial and unblock everything.
2. **A read-only domain before a read-write one.** A view/inquiry screen proves
   the data migration, the field mappings and the encoding end to end, with no
   risk of corrupting anything. This is the cheapest possible validation of the
   riskiest assumption.
3. **Never split a cluster across waves** unless both halves keep working
   throughout. A half-migrated write path is a data-integrity incident.
4. **The monster program goes in the middle.** Not first — the team is still
   learning the pipeline and the tooling. Not last — if it forces an
   architectural change, you need time to absorb it. In CardDemo that is
   `COACTUPC` (3,368 lines, complexity 701).

**Wave 1 should be deliberately boring**: one read-only domain, its reference
data, one screen, one batch job. Its purpose is to prove the pipeline, the
verification harness and the deployment path — not to deliver business value.
Say that out loud at G3, because a stakeholder who expects wave 1 to be
impressive will read a successful wave 1 as a failure.

---

## 5. What goes to the G3 gate

Use `templates/architecture-decision.md`. The reviewers must be able to answer
four questions without reading code:

1. What are the domains, and why these boundaries?
2. Which are services, which are modules, and what score justifies each?
3. In what order, and what does wave 1 prove?
4. What did we assume because evidence was unavailable?

State plainly what each approver is being asked to decide, and what it costs if
they are wrong:

- **Architect** owns the boundaries and the monolith/service verdicts. A wrong
  boundary is found in wave 3 and costs a rewrite of everything built on it.
- **Product Owner** owns the wave order and the "reproduce, don't redesign"
  decision on the UI. A wrong order means the business value arrives late.

Then stop. Do not begin Phase 5 until G3 is recorded.

---

## 6. Close the platform decisions here — never leave them to the build

*Added after the first CardDemo build run. The generator reported "cannot decide"
on transaction management, configuration, runtime and UI stack, stopped, and
waited for a human. Every one of those has a standard answer. Decide them once,
at G3, as **ADR-000 — Platform defaults**, and the build phase applies them
without asking.*

| Decision | Default (from the profile) | Escalate only when |
|---|---|---|
| Transaction management | Spring declarative `@Transactional` on application-service methods; Spring Batch chunk transactions for jobs; no hand-rolled transaction managers | the spec identifies a unit of work spanning two resource managers (e.g. IMS + DB2 + MQ) — that is a real architecture decision; record it as its own ADR |
| Configuration and credentials | Every environment-specific value and every credential comes from environment variables, selected by Spring profile. A committed `dev` profile carries default local credentials and seeded data so verification can start the system unattended. `qa` and `prod` read from the environment only; `prod` binds to the secrets manager | never |
| Integration | Spring Integration for queue, file and adapter boundaries; explicit channels | never |
| Local runtime | Every wave ships a `Dockerfile` and a `docker-compose.yml` (application + database + broker) with a health endpoint. The agent sandbox cannot host a Spring Boot JVM directly — **build the image and run it under compose**; do not iterate on `mvn spring-boot:run` variants | never |
| UI stack | Exactly the profile's `ui` and `ui_detail` blocks. Decided once for the programme | never |
| Code structure | Package by bounded context; inside each: `api` / `application` / `domain` / `infrastructure`; ArchUnit tests enforce it. The skeleton is generated and compiled **before** any rule is implemented | never |
| Test strategy | Unit test per business rule; integration test per use case; suites create and destroy their own data; parallel execution on by default | never |

Write ADR-000 into `4-architecture/adr/ADR-000-platform-defaults.md` with the
table above filled from the profile. The Code Generation agent is **forbidden**
from reporting an open decision that ADR-000 answers. If a decision is genuinely
missing from ADR-000, the fix is to add it to ADR-000 and re-approve the delta,
not to stop the build.

---

## 7. Mechanics — the scripts that run this phase

Two judgement inputs, then one generator:

- `4-architecture/scores.json` (`templates/scores.json`) — the seven-axis score per
  context, every axis scored without runtime evidence listed in `assumed`, one note
  per context saying why.
- `4-architecture/waves.json` (`templates/waves.json`) — the waves, what each proves,
  scope; `retired` (with the ADR), `merged`, the `constraints` you applied over the
  computed score, `uncertainties`, `assumptions`. Run `architect.py` once with a
  first draft to see the computed `wave_score` per context, then order the waves.
- `4-architecture/adr/ADR-001.md …` — your decisions (style, service splits, batch
  chains, coexistence, UI posture, retirements). `ADR-000.md` (platform defaults) is
  generated from the profile if absent; do not write it by hand.
- `4-architecture/nfr-allocation.md` — every NFR in `spec.md` §9 → component,
  measured/assumed. Missing = red check at G3.

```bash
python scripts/architect.py --workspace <out>
```

computes the verdicts (§2 scoring model, override included), the wave-order inputs,
deployables and the C4 container diagram, writes `style-decision.md`, `wave-plan.md`,
`architecture.md`, `c4/containers.mmd`, and proposes G3. It exits non-zero when a
service/retired/merged context has no ADR mentioning it, a context is in no wave, or
a scored context is missing. Decide with `gate_decide.py --gate G3 …` — red checks
need a `--condition` each.
