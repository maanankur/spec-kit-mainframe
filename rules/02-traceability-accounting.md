# Rule 2 - Traceability is an accounting identity

Every COBOL paragraph must end classified as exactly one of:

| Class | Meaning |
|-------|---------|
| `implemented` | Its behaviour exists in the target |
| `not-applicable` | Housekeeping, I/O plumbing, screen paint |
| `delegated` | Now the framework's job (transactions, paging, security) |
| `dropped` | Deliberately removed, with written human sign-off |

`trace_coverage.py` enforces 100% and blocks G5. This is the only check that can find logic
that is *missing* - every other check can only inspect what was written.

Symmetrically: a `BusinessRule` without `source_refs` cannot be written to the graph. That
is what stops the model inventing rules that sound plausible.
