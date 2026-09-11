---
description: "Phase 4 — target architecture: style score per context, ADRs, wave plan; propose Gate G3"
---


# Phase 4 — target architecture

Arguments: `$ARGUMENTS`

Before acting:

1. Read `mainframe-config.yml` in `.specify/extensions/mainframe/` (source path, output path, profile, industry, approvers, `auto_approve`). Command arguments override it.
2. Read `<output>/modernization/state.json`. If it is absent, run __SPECKIT_COMMAND_MAINFRAME_MODERNIZE__ first.
3. Run `python .specify/extensions/mainframe/scripts/verify_source_readonly.py --workspace <output>` — the legacy source tree is read-only, always.
4. Verify the preceding gate is approved and its artifact hashes still match: `python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <output> --check`. If not, stop and report which approval is void.
5. The phase skill text is in `.specify/extensions/mainframe/skills/phases/` — read the one for this phase; load a technique from `.specify/extensions/mainframe/skills/techniques/` only when its trigger appears.


## Procedure

Read `.specify/extensions/mainframe/skills/phases/04-target-architecture/SKILL.md` §2 (scoring model and override) and §4 (wave constraints) and `.specify/extensions/mainframe/skills/techniques/monolith-vs-microservices/` if present, then:

## 7. Mechanics — the scripts that run this phase

Two judgement inputs, then one generator:

- `4-architecture/scores.json` (`.specify/extensions/mainframe/templates/scores.json`) — the seven-axis score per
  context, every axis scored without runtime evidence listed in `assumed`, one note
  per context saying why.
- `4-architecture/waves.json` (`.specify/extensions/mainframe/templates/waves.json`) — the waves, what each proves,
  scope; `retired` (with the ADR), `merged`, the `constraints` you applied over the
  computed score, `uncertainties`, `assumptions`. Run `architect.py` once with a
  first draft to see the computed `wave_score` per context, then order the waves.
- `4-architecture/adr/ADR-001.md …` — your decisions (style, service splits, batch
  chains, coexistence, UI posture, retirements). `ADR-000.md` (platform defaults) is
  generated from the profile if absent; do not write it by hand.
- `4-architecture/nfr-allocation.md` — every NFR in `spec.md` §9 → component,
  measured/assumed. Missing = red check at G3.

```bash
python .specify/extensions/mainframe/scripts/architect.py --workspace <out>
```

computes the verdicts (§2 scoring model, override included), the wave-order inputs,
deployables and the C4 container diagram, writes `style-decision.md`, `wave-plan.md`,
`architecture.md`, `c4/containers.mmd`, and proposes G3. It exits non-zero when a
service/retired/merged context has no ADR mentioning it, a context is in no wave, or
a scored context is missing. Decide with `gate_decide.py --gate G3 …` — red checks
need a `--condition` each.
