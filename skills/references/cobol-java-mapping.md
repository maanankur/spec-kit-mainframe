# COBOL → Java Mapping

Lookup tables. Consult from any phase. Sizes and offsets always come from
`scripts/copybook_parse.py`, never from this page.

---

## 1. Data types

`copybook_parse.py` emits `java_type` per field using exactly these rules.

| PIC / USAGE | Bytes | Java | Notes |
|-------------|-------|------|-------|
| `PIC X(n)` | n | `String` | Right-trim on read. **Left spaces may be data** |
| `PIC A(n)` | n | `String` | Alphabetic only |
| `PIC 9(n)` DISPLAY | n | `Integer` n≤9, `Long` n≤18, `BigInteger` n>18 | Zoned decimal |
| `PIC S9(n)` DISPLAY | n | as above | Sign overpunched into the last byte's zone |
| `PIC S9(n)` SIGN SEPARATE | n+1 | as above | Sign in its own byte |
| `PIC 9(n)V9(m)` | n+m | **`BigDecimal`** | `V` is an implied point: no byte |
| `PIC S9(n)V9(m) COMP-3` | ⌈(n+m+1)/2⌉ | **`BigDecimal`** | Packed; sign in the low nibble of the last byte |
| `PIC 9(n) COMP` / `COMP-4` / `BINARY` | 2 (n≤4), 4 (n≤9), 8 (n≤18) | `Integer` / `Long` | Big-endian on z/OS |
| `PIC 9(n) COMP-5` | as COMP | `Integer` / `Long` | Native binary, no digit-count truncation |
| `COMP-1` | 4 | `float` | Host floating point. **Hazard** — see below |
| `COMP-2` | 8 | `double` | Host floating point. **Hazard** |
| `PIC ZZ,ZZ9.99` etc. | positions | `String` | Numeric-**edited**: presentation only. Parse, never compute |
| `PIC 9(8)` holding a date | 8 | `LocalDate` | Convert at the boundary, keep the raw value until verified |
| 88-level | 0 | `enum` / `boolean` | Condition names document the field's legal domain |
| `POINTER` | 4 | — | Hazard: re-derive intent |

**`COMP-1`/`COMP-2` are a business decision, not a conversion.** They are
already binary floating point on the mainframe, so results already carry
rounding error. Converting to `BigDecimal` *changes* the answers; keeping
`double` may also change them, because IBM hex float and IEEE 754 differ. Find
out whether the precision was ever load-bearing and get a decision.

### Scale, precision and the loss of both

| Trap | What happens |
|------|--------------|
| `MOVE` to a shorter numeric | COBOL **truncates high-order digits silently**. No error. Java would need the same truncation to match |
| `MOVE` to fewer decimals | Truncates low-order digits. Not rounding |
| Group `MOVE` | A byte copy, not a field copy. Type-unsafe by design; commonly used for `REDEFINES` reinterpretation |
| `MOVE` spaces to numeric | Legal in COBOL, produces garbage-but-defined behaviour. Real data contains these |
| `HIGH-VALUES` / `LOW-VALUES` | Often sentinels meaning "end" or "not set", not data. Map explicitly |

---

## 2. Arithmetic

The rules here are the difference between a correct conversion and a systematic
money leak. See `05-forward-engineering.md` §2.

| COBOL | Java | Note |
|-------|------|------|
| `COMPUTE x = a * b` | `a.multiply(b)` | |
| `COMPUTE x = a / b` | `a.divide(b, scale, RoundingMode.DOWN)` | **Default COBOL behaviour is truncation** |
| `COMPUTE x = ... ROUNDED` | `RoundingMode.HALF_UP` | Half-up away from zero |
| `ADD a TO b` | `b = b.add(a)` | |
| `SUBTRACT a FROM b` | `b = b.subtract(a)` | |
| `MULTIPLY a BY b GIVING c` | `c = a.multiply(b)` | |
| `DIVIDE a INTO b GIVING c REMAINDER r` | `divideAndRemainder` | |
| `ON SIZE ERROR` | explicit overflow branch | A real code path; test it |
| `IF a = b` on numerics | `a.compareTo(b) == 0` | `equals` compares scale too |

**Intermediate precision.** COBOL derives intermediate result precision from the
operands and the compiler's rules; truncating at each step of a chain gives a
different answer from truncating once at the end. The spec's `arithmetic` block
must say which applies. If it does not, that is a specification gap — go back and
fill it rather than picking one.

---

## 3. Control flow

| COBOL | Java |
|-------|------|
| `PERFORM para` | method call |
| `PERFORM para THRU para2` | one method covering the range — usually a sign the range is a single business step |
| `PERFORM n TIMES` | `for` loop |
| `PERFORM UNTIL cond` | `while (!cond)` |
| `PERFORM VARYING i FROM 1 BY 1 UNTIL i > n` | `for (int i = 1; i <= n; i++)` |
| `PERFORM ... WITH TEST AFTER` | `do { } while` |
| `IF / ELSE / END-IF` | `if / else` |
| `EVALUATE TRUE WHEN ...` | `if / else if` chain, or a guard-clause sequence |
| `EVALUATE var WHEN v1 WHEN v2` | `switch`, or better, an enum with behaviour |
| `GO TO para` | restructure. Never a label |
| `GO TO ... DEPENDING ON` | **hazard** — redesign from the rules |
| `ALTER` | **hazard** — self-modifying flow |
| `STOP RUN` / `GOBACK` | `return`, or an exit code from a batch step |
| `EXIT PARAGRAPH` | `return` |
| `CALL 'SUB' USING a b` | method or injected bean call |
| `CALL var USING ...` | dynamic dispatch — resolve via the navigation table |

`EVALUATE TRUE` is worth a second look each time: it is often a decision table
in disguise, and it usually reads far better in Java as a sequence of guard
clauses or a lookup than as a nested conditional.

---

## 4. Strings

| COBOL | Java | Trap |
|-------|------|------|
| `MOVE a TO b` (X to X) | assignment | COBOL pads right with spaces to the target length |
| `STRING a b DELIMITED BY` | `String.join` / concatenation | |
| `UNSTRING` | `split` | |
| `INSPECT ... TALLYING` | count | |
| `INSPECT ... REPLACING` | `replace` | |
| reference modification `a(2:5)` | `substring(1, 6)` | **1-based, (start:length)** — Java is 0-based, (start, endExclusive) |
| `IF a = 'X'` | `.equals` after trim | Comparing a padded field to an unpadded literal is a common defect |
| `IF a > b` on text | `compareTo` | **COBOL compares in EBCDIC collation order.** Digits sort *below* letters in ASCII but *above* in EBCDIC — so sort order changes. This silently reorders reports and breaks key sequencing |

The EBCDIC collation point deserves emphasis: any logic that depends on
comparing or sorting mixed alphanumeric text will produce a different order in
Java. Golden-master comparison catches it. Nothing else reliably will.

---

## 5. Files and status

| COBOL | Java |
|-------|------|
| `SELECT ... ASSIGN TO` | repository / `ItemReader` |
| `OPEN INPUT` | open a stream / begin a step |
| `READ ... AT END` | iterator exhaustion |
| `READ ... INVALID KEY` | `Optional.empty()` |
| `WRITE` | insert / `ItemWriter` |
| `REWRITE` | update |
| `DELETE` | delete |
| `START` / `READ NEXT` | keyset pagination |
| `FILE STATUS` `'00'` | success |
| `FILE STATUS` `'10'` | end of file — normal control flow |
| `FILE STATUS` `'23'` | not found — `Optional.empty()`, not an exception |
| `FILE STATUS` `'22'` | duplicate key — constraint violation |
| `SQLCODE +100` | no rows — **normal flow, not an error** |
| `SQLCODE` negative | genuine error |

Two status values cause most of the trouble: `'23'` and `SQLCODE +100`. Both are
routine "not found" branches in COBOL. Converting them into thrown exceptions
turns ordinary control flow into error handling and changes behaviour — often
turning a silent skip into a failed batch.
