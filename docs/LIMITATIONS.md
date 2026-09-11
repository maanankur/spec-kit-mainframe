# Limitations

Stated plainly, because a modernization framework that oversells is dangerous.

- **It does not replace mainframe runtime testing at production volume.** The
  golden-master harness runs on stratified extracts, not on a full production day.
- **It cannot recover intent that exists only in a person's head.** Where the COBOL
  is ambiguous, the specification records an open question. It does not guess.
- **Assembler and exotic constructs are flagged, not converted.** `ALTER`,
  `GO TO DEPENDING ON`, self-modifying paragraph tables and third-party mainframe
  utilities become manual-treatment scope with an effort estimate at G1.
- **Equivalence is not correctness.** Generated tests prove equivalence with
  *observed behaviour*. A faithfully converted bug is still a bug; those appear on
  the G1 discovered-defect list for a business decision, never silently fixed.
- **The equivalence confidence score is a coverage measure, not a probability.** It
  says what fraction of observed behaviour has evidence behind it. It is reported
  unrounded and it is not a substitute for UAT.
- **Gates only work if they are read.** Hash binding stops documents drifting; it
  cannot stop an approver signing without reading. Waiver count and approval
  turnaround are tracked precisely because gate theatre is the failure mode.
- **The plugin governs itself no better than its evals.** A technique skill without
  a passing eval is not published, and that discipline has to be maintained.
