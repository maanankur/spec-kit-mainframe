# Non-negotiable rules

These are enforced by hooks, not by good intentions. A run that cannot satisfy them stops.

1. **Humans approve intent, machines verify fidelity.** No human is ever asked to certify
   generated code correct by reading it.
2. **The specification firewall.** Java is generated from the approved specification, never
   transliterated from COBOL.
3. **Deterministic before generative.** The judgement plane may not assert a fact the
   deterministic plane can compute.
4. **The knowledge graph is the system of record.** Every artifact is a projection of it.
5. **Nothing is "not accounted for".** Every COBOL paragraph ends up classified.
6. **Money is `BigDecimal`.** Always.
7. **Never guess an offset.** Run the parser.
8. **A wave is not done until its evidence pack is green** - not when it compiles, not when
   it looks right.
