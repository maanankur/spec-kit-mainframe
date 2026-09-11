# Specification — <System Name>

> Recovered from legacy source. Approved at G1 by Business Analyst, Architect and Product Owner.
> **Read section 8 (Open Questions) first** — that is what needs your decision.

| | |
|---|---|
| Source | <repo / library, commit or version> |
| Scope | <programs and jobs covered> |
| Traceability | <N>/<N> paragraphs accounted for (100% required) |
| Rules recovered | <count> (high <n> / medium <n> / low <n> confidence) |
| Open questions | <count> |
| Suspected legacy defects | <count> |

---

## 1. Purpose
<Two or three sentences a Product Owner would recognise as their system.>

## 2. Vocabulary
| Business term | Legacy data name | Meaning |
|---|---|---|
| | | |

## 3. Data owned
| Entity | Identity | Meaning | Lifecycle | Legacy store |
|---|---|---|---|---|
| | | | | |

## 4. Processes
### 4.1 <Process name>
- **Trigger:** <transaction / job / schedule>
- **Inputs:** <…>
- **Steps:** <numbered, each citing rule ids>
- **Outputs:** <…>
- **Failure behaviour:** <what happens when it goes wrong>
- **Volumes:** <records/day, peak>

## 5. Business rules
| ID | Statement | Confidence | Evidence |
|---|---|---|---|
| BR-0001 | | | <program>:<paragraph>:<lines> |

## 6. Screens
### 6.1 <Screen> (<transaction>)
- **Purpose:**
- **Fields:** name, type, length, required, validation, source
- **Actions / PF keys:**
- **Navigation:** <from> → <to>

## 7. Batch
| Job | Steps | Schedule | Depends on | Restart behaviour | Volume |
|---|---|---|---|---|---|

## 8. Open questions — DECISIONS NEEDED AT G1
| # | Question | Why it matters | Asked of | Answer |
|---|---|---|---|---|
| Q1 | | | BA / PO | |

### 8.1 Suspected legacy defects
| # | Behaviour observed | Why it looks wrong | Evidence | Preserve or fix? |
|---|---|---|---|---|
| D1 | | | | |

## 9. Non-functional requirements
| Aspect | Requirement | Source | Assumed? |
|---|---|---|---|
| Peak throughput | | | |
| Batch window | | | |
| Online response | | | |
| Retention | | | |
| Regulatory | | | |

## 10. Explicitly out of scope
| Item | Reason | Approved by |
|---|---|---|
