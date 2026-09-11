# Gate {{gate_id}} - {{gate_title}}

**Decision requested:** {{one sentence, in plain language}}
**Approvers required:** {{roles}} (quorum: {{quorum}})
**Artifacts under review:** {{count}} files, manifest hash `{{manifest_hash}}`

---

## 1. What you are being asked to decide

{{Plain language. No jargon. One paragraph.}}

## 2. What happens if this decision is wrong

{{Concrete consequence, cost and the phase at which it would surface.
This section is mandatory and must not be softened.}}

## 3. What we are least sure about

| Item | Confidence | Why it is uncertain | What would resolve it |
|------|-----------|---------------------|----------------------|

## 4. What we could not determine

{{Open questions, unparsed constructs, missing artifacts, absent SMEs.
An empty section here is a warning sign, not a good sign.}}

## 5. Evidence

{{For evidence gates: the red/green table, with every red item and its waiver
status. A red item cannot be approved - it can only be waived below.}}

## 6. Summary of the artifacts

{{Links plus a 3-line summary each. Never a substitute for reading them.}}

---

## Decision

- [ ] Approved
- [ ] Approved with conditions (list below, tracked to closure)
- [ ] Rejected (reason below, injected into the re-run)
- [ ] Waiver required (red evidence - complete the waiver template)

Conditions / reason:

Signatures are recorded in `governance/gates/{{gate_id}}/decision-record.json`
and bound to the artifact manifest hash above. If any artifact changes, this
approval is automatically void.
