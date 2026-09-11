# Rule 4 - Numeric fidelity

COBOL is exact base-10 and truncates by default. `double` is neither.

- Monetary and quantity fields: `BigDecimal` with an explicit scale and `RoundingMode`.
- `PIC S9(n)V99 COMP-3` round-trips through the field map, never through a string.
- Sign nibbles, overpunch signs and zoned decimal are parser territory, not inference.
- Property-based tests cover arithmetic at the boundaries: maximum values, negatives, zero,
  and the exact rounding behaviour the legacy `COMPUTE` produced.
