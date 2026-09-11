---
description: "Phase 3 — bounded contexts from clusters, CRUD and rule evidence; propose Gate G2"
---


# Phase 3 — domain decomposition

Arguments: `$ARGUMENTS`

Before acting:

1. Read `mainframe-config.yml` in `.specify/extensions/mainframe/` (source path, output path, profile, industry, approvers, `auto_approve`). Command arguments override it.
2. Read `<output>/modernization/state.json`. If it is absent, run __SPECKIT_COMMAND_MAINFRAME_MODERNIZE__ first.
3. Run `python .specify/extensions/mainframe/scripts/verify_source_readonly.py --workspace <output>` — the legacy source tree is read-only, always.
4. Verify the preceding gate is approved and its artifact hashes still match: `python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <output> --check`. If not, stop and report which approval is void.
5. The phase skill text is in `.specify/extensions/mainframe/skills/phases/` — read the one for this phase; load a technique from `.specify/extensions/mainframe/skills/techniques/` only when its trigger appears.


## Procedure

Read the phase skill `.specify/extensions/mainframe/skills/phases/03-domain-decomposition/SKILL.md` §1-6 for how a boundary is justified, then:

## 7. Mechanics — the scripts that run this phase

The boundaries are judgement and are written to `3-domain/contexts.json`
(`.specify/extensions/mainframe/templates/contexts.json`): id, name, kind, programs, owned stores, purpose,
aggregates, events, confidence, rationale; plus `shared_write_resolutions`,
`relationships` and the `decisions` the approvers must make. Store names are the
canonical names from `1-discovery/dependencies.json` (`store_identity.resolved_to`);
add `store_aliases` only for names the deterministic plane could not resolve, and say
why in `decisions`. Every program in `inventory.json` must be in exactly one context.

Everything else is computed so it cannot drift from the phase-1/2 facts:

```bash
python .specify/extensions/mainframe/scripts/decompose.py --workspace <out>
```

writes `decomposition.json` (rules per context by evidence, cross-context reads,
shared-write resolutions, unowned stores, validation errors), `context-map.md`
(mermaid map with computed edges, relationship table, per-context rationale, the
decisions) and `glossary.md` (from the work packages' vocabulary tables, conflicts
flagged), then proposes G2. It exits non-zero on unassigned programs or a program in
two contexts — fix `contexts.json`, do not edit the outputs. Decide with
`gate_decide.py --gate G2 …`.
