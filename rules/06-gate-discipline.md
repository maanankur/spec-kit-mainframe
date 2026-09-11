# Rule 6 - Gate discipline

- Between gates, work without asking permission. The pipeline concentrates the questions
  worth a human's attention at the gates; asking elsewhere defeats the point.
- At a gate: produce the review pack, state what is being decided and what happens if the
  approver is wrong, then **stop**.
- Approvals are bound to artifact hashes. Change an approved artifact and the approval is
  void; the state machine reverts.
- The identity that proposes a gate cannot approve it.
- **A red evidence gate cannot be approved.** It can only be waived, with a named risk
  owner, a compensating control and a mandatory expiry date.
- **Platform decisions are closed at G3, in ADR-000.** Transaction management, configuration
  and credentials, integration framework, local runtime, UI stack, module structure and test
  strategy are decided from the profile before any code is generated. A build-phase agent that
  reports "cannot decide" on one of them is violating this rule, not escalating.
