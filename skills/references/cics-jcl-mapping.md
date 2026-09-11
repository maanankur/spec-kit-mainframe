# CICS / BMS / JCL → Spring, REST and the Frontend

---

## 1. CICS commands

| CICS | Target | Notes |
|------|--------|-------|
| `RECEIVE MAP` | `@RequestBody` DTO | Inbound screen fields |
| `SEND MAP` | `ResponseEntity<DTO>` | Outbound screen fields |
| `SEND MAP ... ERASE` | full page render | |
| `SEND MAP ... DATAONLY` | partial update | Maps naturally to a JSON patch of the view model |
| `READ FILE`/`DATASET` | `repository.findById` | `FILE` and `DATASET` are synonyms — match both |
| `READ ... UPDATE` | `SELECT ... FOR UPDATE` or optimistic lock | Holds a record lock until syncpoint. Semantics differ; see §5 |
| `WRITE FILE` | `repository.save` (insert) | |
| `REWRITE FILE` | `repository.save` (update) | |
| `DELETE FILE` | `repository.delete` | |
| `STARTBR` / `READNEXT` / `ENDBR` | keyset pagination | Never `OFFSET` — see §4 |
| `XCTL PROGRAM(x)` | client-side route change | Transfer with no return: the next screen |
| `LINK PROGRAM(x)` | service method call | Call and return. **Hazard flag** — often a hidden module boundary |
| `RETURN TRANSID(x)` | pseudo-conversational turn end | The response completes the HTTP request |
| `RETURN` | end of request | |
| `SYNCPOINT` | `@Transactional` commit | |
| `SYNCPOINT ROLLBACK` | rollback | |
| `ABEND` | exception → 5xx | |
| `ASKTIME` / `FORMATTIME` | `Clock` — inject it | Never `LocalDate.now()` inline; it makes tests non-deterministic |
| `GETMAIN` | object allocation | Drop it |
| `ADDRESS COMMAREA` | request/response DTO | See §3 |
| `READQ TS` / `WRITEQ TS` | session store or cache | Temporary storage queue: usually scratch state |
| `WRITEQ TD` | message queue or log | Transient data: often a print or audit stream |
| `ENQ` / `DEQ` | distributed lock | Explicit design decision, not a translation |
| `START TRANSID` | async job / message | Deferred work |
| `HANDLE CONDITION` | try/catch | Non-local jump on condition — restructure |

---

## 2. BMS map → screen

A BMS map is a 24×80 character grid. Its structure encodes constraints that a
modern UI expresses differently, so extract the *semantics*, not the geometry.

| BMS | Meaning | Frontend |
|-----|---------|----------|
| `DFHMSD` | mapset | Screen module |
| `DFHMDI` | map | One screen / route |
| `DFHMDF` | field | Form field or label |
| `ATTRB=ASKIP` | not enterable | Static text |
| `ATTRB=PROT` | protected | Read-only field |
| `ATTRB=UNPROT` | enterable | Input |
| `ATTRB=NUM` | numeric only | `type=number` + validation |
| `ATTRB=BRT` | highlighted | Emphasis — often an error indicator |
| `ATTRB=DRK` | non-display | Password / masked |
| `PICIN` / `PICOUT` | edit mask | Format and parse rules |
| `INITIAL=` | literal text | Label — **mine these for business vocabulary** |
| `LENGTH=` | field width | `maxlength`, and the DTO field length |
| `POS=` | grid position | Discard. Lay out for the web |

**PF keys.** `PF3`=back, `PF7`=page up, `PF8`=page down, `PF12`=cancel, `ENTER`
=submit are near-universal conventions. They become buttons and routes. Keep
keyboard shortcuts — the existing users are fast on them and removing them makes
the new system feel slower even when it is faster.

**Field-level error signalling.** The legacy pattern is: set the field to `BRT`,
put a message in the message line, return to the same screen. In REST this is a
validation error response listing field-level errors. Reproduce the *set* of
errors and their text; the message line wording is often what users recognise.

---

## 3. The COMMAREA

Pseudo-conversational CICS holds no session between turns: state travels in the
COMMAREA, passed out on `RETURN TRANSID` and back on the next invocation.

Classify every COMMAREA field before designing the API:

| Kind | Example | Target |
|------|---------|--------|
| Screen data | the account being viewed | Request/response body |
| Navigation | from-program, to-program, selected option | Client-side route state |
| Selection context | the row picked from a list | Path or query parameter |
| Cursor position | last key read for browsing | Pagination token in the response |
| User identity | signed-on user, authority level | Auth token / security context |
| Scratch | work fields that happen to live there | Delete |

**Do not port the COMMAREA as an object.** Copying it field-for-field into a
session bean reproduces exactly the coupling you are paying to remove, and hides
it somewhere less visible than a copybook. Classify, then design the contract.

---

## 4. Browse → pagination

`STARTBR` positions a cursor at or after a key; `READNEXT` walks forward. The
tempting translation is `LIMIT`/`OFFSET`. It is wrong on two counts: `OFFSET`
degrades on large tables, and under concurrent inserts or deletes rows shift
between pages, so a user paging through a list sees duplicates or misses rows.

Use keyset pagination, which is what `READNEXT` actually is:

```sql
SELECT * FROM transaction
 WHERE tran_id > :lastSeenId
 ORDER BY tran_id
 LIMIT :pageSize
```

Return `lastSeenId` in the response and take it back on the next request. This
preserves the original semantics exactly, and is faster.

---

## 5. Locking: the difference that bites

`READ ... UPDATE` takes a VSAM record lock held to syncpoint. Two concurrent
transactions serialise; the second waits. COBOL programs written against this
guarantee often contain read-modify-write sequences with no explicit
concurrency handling, because none was needed.

JPA optimistic locking is not equivalent: the second writer *fails* rather than
waits, at commit time. Naive conversion produces either lost updates (no
locking) or unexpected failures under load (optimistic locking where the legacy
code assumed it would just wait).

Decide per use case and write it down:

- **Pessimistic** (`SELECT ... FOR UPDATE`) reproduces the legacy behaviour most
  closely. Prefer it where the legacy code clearly relied on serialisation.
- **Optimistic** is better for throughput but changes the failure mode, which
  means the API contract and the UI both need to handle a retry.

Test it explicitly with concurrent updates to the same record. This class of
defect only appears under load, and it corrupts data when it does.

---

## 6. JCL → Spring Batch

| JCL | Spring Batch |
|-----|--------------|
| `//JOB` | `Job` — keep the name |
| `//STEP EXEC PGM=` | `Step` — keep the name |
| `//STEP EXEC PROC=` | composed / reusable step |
| `DD DSN=` | `ItemReader` / `ItemWriter` resource |
| `DD SYSIN *` | job parameters |
| `DISP=(NEW,CATLG)` | create output |
| `DISP=MOD` | append |
| `COND=` / `IF THEN ELSE` | step flow on exit status |
| `RESTART=` | `JobRepository` restart |
| `SORT` (DFSORT) | sort step, or `ORDER BY` in the reader |
| `IDCAMS REPRO` | data copy step |
| GDG `(+1)` / `(0)` / `(-1)` | date- or version-partitioned output |
| `IEFBR14` | no-op — usually dataset allocation. Often deletable |
| Internal reader | job submission / message trigger |
| `MVSWAIT`-style timer | scheduler delay, not a sleep in code |

**Two things to get from the runbook, not the JCL:**

- **Real dependencies and windows.** JCL gives step order within a job; the
  scheduler holds the dependencies between jobs, the windows, and the
  restart-from-step procedures.
- **What operators actually do when it fails.** The manual cleanup step that has
  been performed for fifteen years and appears in no code is part of the system's
  behaviour. Find it before you automate around it.

Keep the legacy job and step names. Operations staff will be running this at 3am
and a job called `POSTTRAN` is greppable in a fifteen-year-old runbook;
`transactionPostingJobV2` is not.
