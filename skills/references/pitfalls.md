# Pitfalls

Failure modes that reach production. Ordered by how expensive they are, not how
likely — the cheap-and-likely ones are caught by the lint and the golden master;
these are the ones that survive.

---

## Money

**1. `double` for a monetary amount.** The defect of record in COBOL
conversions. COBOL is exact base-10 and truncates; IEEE 754 is neither. The
error is a fraction of a cent per operation, which passes every happy-path test
and shows up as an unreconcilable ledger six months later. `BigDecimal`,
always. Caught by `jobol_lint.py`.

**2. `new BigDecimal(0.1)`.** Captures the exact binary rounding error you
switched to `BigDecimal` to avoid: `0.1000000000000000055511151231257827…`. Use
the `String` constructor or `BigDecimal.valueOf`.

**3. Rounding where COBOL truncates.** `COMPUTE` without `ROUNDED` **truncates**.
`RoundingMode.HALF_UP` is the intuitive default and it is wrong roughly half the
time on fractional results. Read the `arithmetic` block on the rule.

**4. Truncating each step instead of once.** A chain of operations truncated at
every step gives a different total than one truncated at the end. COBOL's
intermediate precision follows compiler rules; the spec must state which
behaviour applies.

**5. Silent high-order truncation on `MOVE`.** `MOVE` of a 9(7) into a 9(5)
discards the top two digits with no error and no warning. If the legacy code
relied on this — deliberately or not — Java that throws or keeps the full value
does not match.

---

## Data representation

**6. Reading EBCDIC as ASCII, or with the platform default.** Digits often
survive, text does not, so the corruption is partial and passes inspection.
Always name the charset (`Cp037`). Caught by `jobol_lint.py`.

**7. Guessing field offsets.** COMP-3 sizing is `⌈(digits+1)/2⌉`; `V` and `S`
consume no bytes; `REDEFINES` does not advance the offset; a group's `USAGE`
propagates to its children. Every one of these is a place a manual calculation
goes wrong by one byte, which shifts every field after it. Run
`copybook_parse.py`.

**8. Treating `OCCURS DEPENDING ON` as fixed-length.** The record length varies
per row and every offset after the ODO group is only valid at the maximum
occurrence. A fixed-length reader mis-parses every short record.

**9. Modelling `REDEFINES` as independent columns.** Discards the invariant that
exactly one overlay is valid. Someone will read the wrong one. Model it as a
discriminated union.

**10. Dropping `FILLER` without looking.** Systems of this age hide real data in
filler — a field added without updating the copybook. Verify the bytes are
actually spaces across a real sample before discarding them.

**11. Trimming the wrong end.** COBOL pads text on the **right**. Trailing
spaces are padding; **leading spaces can be significant** in codes and keys.
`trim()` on both ends corrupts left-padded values.

**12. Sentinels read as data.** `HIGH-VALUES` in a key usually means "end of
range", `LOW-VALUES` means "not set", spaces in a numeric mean "never
populated". Loading them as literal values produces nonsense maxima and skewed
aggregates.

**13. EBCDIC collation.** In EBCDIC, digits sort **above** letters; in ASCII,
**below**. Any comparison or sort of mixed alphanumeric text changes order.
Reports come out differently, and key-sequenced processing can change results.
Only the golden master reliably catches this.

---

## Control flow and error handling

**14. `SQLCODE +100` and `FILE STATUS '23'` turned into exceptions.** Both are
ordinary "not found" branches. Converting them into thrown exceptions turns
normal control flow into error handling — commonly turning a designed skip into
a failed batch.

**15. Swallowed failures.** COBOL signals I/O failure through a status code that
the program must check. Programs that check it and continue are common. An empty
`catch` in the Java equivalent turns a failed write into a silent success.
Caught by `jobol_lint.py`.

**16. `ON SIZE ERROR` dropped.** It is a real branch taken on overflow. Losing it
loses behaviour.

**17. Recovering screen flow from `XCTL` sites.** In pseudo-conversational CICS
the navigation is dynamic dispatch through a menu table. The `XCTL` operand is a
variable. Read the table.

---

## Architecture

**18. Splitting on program-name prefixes.** `CO*` versus `CB*` is a naming
convention, not a domain boundary. Split on data ownership.

**19. Splitting a shared write.** Two components writing the same store, put in
different services, buys a distributed transaction and a new class of incident.
The data-ownership override in `03-architecture.md` exists to prevent this.

**20. Microservices as the default.** Produces a distributed monolith: the
coupling of a monolith plus network latency, partial failure and much harder
debugging. Modular monolith first; extract on evidence.

**21. Porting the COMMAREA into a session object.** Reproduces the coupling in a
less visible place. Classify the fields, design the contract.

**22. `OFFSET` pagination for a `READNEXT` browse.** Wrong under concurrent
modification — rows shift between pages — and slow. Use keyset pagination.

**23. Assuming JPA optimistic locking equals a VSAM record lock.** It does not:
one waits, the other fails at commit. COBOL code frequently relies on
serialisation it never mentions, because it never had to.

---

## Process

**24. Reviewing generated Java for behavioural correctness.** Nobody can do this
at volume. It feels like diligence and it approves defects. Use the golden
master; give the human the specification instead.

**25. Skipping the specification and converting directly.** Produces JOBOL:
Java shaped like COBOL, maintainable only by COBOL programmers. It removes the
mainframe and keeps every reason the mainframe was a problem.

**26. Silently fixing a legacy defect.** Downstream consumers may depend on the
wrong behaviour, and the change breaks the golden master — your only equivalence
evidence. Record it, flag it, let the Product Owner decide at G2.

**27. Traceability retrofitted at the end.** Produces traceability-shaped
documentation nobody verified. Build it while writing the rules.

**28. Treating 98% traceability coverage as nearly done.** The figure tells you
nothing about whether the missing 2% is housekeeping or the fee calculation. The
gate is an accounting identity or it is nothing.

**29. Converting dead code.** 15–40% of a codebase this age is typically
unreachable. Confirm with a human at G1 — unreachable in the source you were
given is not the same as dead in production.

**30. Sample-volume performance testing.** The batch window is a hard
constraint. A job that takes 12 minutes on 50 records tells you nothing about
48 million.

**31. Claiming everything was verified.** An evidence pack that reports no gaps
is not credible and destroys the trust that makes the pack useful. Name what was
not covered.
