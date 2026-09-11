# Specification front matter — <project>

Written by the reverse-engineering agent after the work packages are merged. `assemble_spec.py`
lifts the three sections below into `spec.md`; everything else in `spec.md` is generated.
Keep the `##` headings exactly as they are.

## 1. Purpose

<What the system is for, in the business's words: who uses it, what it decides, what money
or obligations it moves. Two to five paragraphs. Cite `README.md` in the source root if one
exists; say when the purpose was inferred from the code rather than stated anywhere.>

## 9. Non-functional requirements

| Requirement | Value | Source | Status |
|---|---|---|---|
| Online response time | <value or "unknown"> | <SMF / CICS statistics / none supplied> | measured / **assumed** |
| Batch window | <value or "unknown"> | <scheduler export / job accounting / none> | measured / **assumed** |
| Peak transaction volume | | | |
| Data volumes (per master) | | <production extract / sample only> | |
| Availability during batch | | <CLOSEFIL/OPENFIL pattern, runbooks> | |
| Retention | | <compliance pack> | |
| Regulatory | | <industry pack: PCI, SOX, GDPR …> | |

State plainly which numbers are assumed. An assumed NFR is a G3 question, not a fact.

## 10. Explicitly out of scope

- <Sub-systems, programs or datasets deliberately excluded, each with the reason and who decided>
- <Behaviour that exists only outside the repository (e.g. RACF rules, scheduler calendars)>
- <UI redesign, if the programme reproduces screen flow first>
