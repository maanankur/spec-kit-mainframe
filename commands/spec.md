---
description: "Phase 2 — recover the specification from the legacy source (rules with evidence, paragraph-level traceability, use cases) and propose Gate G1"
---


# Phase 2 — specification recovery

Arguments: `$ARGUMENTS` — `[output-path] [--packages WP1,WP3] [--merge-only]`.

Before acting:

1. Read `mainframe-config.yml` in `.specify/extensions/mainframe/` (source path, output path, profile, industry, approvers, `auto_approve`). Command arguments override it.
2. Read `<output>/modernization/state.json`. If it is absent, run __SPECKIT_COMMAND_MAINFRAME_MODERNIZE__ first.
3. Run `python .specify/extensions/mainframe/scripts/verify_source_readonly.py --workspace <output>` — the legacy source tree is read-only, always.
4. Verify the preceding gate is approved and its artifact hashes still match: `python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <output> --check`. If not, stop and report which approval is void.
5. The phase skill text is in `.specify/extensions/mainframe/skills/phases/` — read the one for this phase; load a technique from `.specify/extensions/mainframe/skills/techniques/` only when its trigger appears.


## Procedure

## 7. Mechanics — the scripts that run this phase

Phase 1 already produced two things this phase depends on:
`modernization/tools/paragraph-skeleton.json` (the gate's own paragraph list — the
only list agents may classify against) and
`2-specification/_fragments/plan.json` with one `WPn/brief.md` per work package
(`work_packages.py`: programs grouped by sub-application and data cluster, ~120
paragraphs each, disjoint rule-id ranges, the brief rendered from
`.specify/extensions/mainframe/templates/work-package-brief.md`).

1. **Dispatch one agent per package** with its `brief.md` as the whole instruction.
   Batch the dispatches (three or four at a time); each agent writes incrementally, so
   a killed run resumes from what is already in its fragment directory. Do not write
   your own briefing — the template carries the nine absolute rules, including *worked
   examples quote real decoded values* and *never cite a rule id you have not written*.
2. **Merge and validate** — refuses to produce artifacts it cannot validate:
   ```bash
   python .specify/extensions/mainframe/scripts/merge_fragments.py --workspace <out> --write
   ```
   Errors (id collisions, out-of-range ids, evidence that does not resolve, a paragraph
   unaccounted for) go back to the owning package's agent with the message verbatim.
3. **Cross-cutting recoveries** the packages cannot see whole: write
   `screen-flow.md`, `batch-topology.md`, `discovery-corrections.md` (what phase 1 got
   wrong — every fix is also a parser fix in `.specify/extensions/mainframe/scripts/`), and `use-cases.jsonl` from
   the `### Processes` sections (`.specify/extensions/mainframe/templates/use-cases.jsonl`; every use case lists its
   rule ids — the use-case coverage gate at G5 reads this file).
4. **Front matter** — `spec-front-matter.md` from `.specify/extensions/mainframe/templates/spec-front-matter.md`:
   Purpose, NFRs (say which numbers are assumed), out of scope.
5. **Assemble and propose G1:**
   ```bash
   python .specify/extensions/mainframe/scripts/verify_source_readonly.py --workspace <out>
   python .specify/extensions/mainframe/scripts/assemble_spec.py --workspace <out>
   ```
   `spec.md`, `coverage-report.md`, `governance/gates/G1/{review-pack.md,manifest.json}`;
   `state.json` G1 = proposed, bound to the manifest hash. It refuses below 100 %
   traceability.
6. **Decide** — the approvers (or the operator under a recorded blanket authorization):
   ```bash
   python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <out> --gate G1 --decision approved-with-conditions --by <id> --condition "C1 ..."
   ```
   A changed artifact voids the decision; `gate_decide.py --check` proves it has not.

## The gate

G1 approvers (from `modernization.config.yaml`): Business Analyst, Architect, Product Owner — three different questions (rules right? open questions answered and defects decided? traceability genuinely 100 %?). Lead the review with the open questions and suspected defects. Then stop — unless `auto_approve` is set, in which case:

```
python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <output> --gate G1 --auto --by <approver> --authorization "<the recorded instruction>"
```
