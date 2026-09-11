# spec-kit-mainframe

A [Spec Kit](https://github.com/github/spec-kit) extension that takes a COBOL mainframe
application to a Java ecosystem through a gated, evidence-driven lifecycle. It is not a
transpiler: humans approve intent (the recovered specification, the architecture); machines
verify fidelity (paragraph-level traceability, a byte-level data proof, a golden-master
comparison of the real COBOL running under GnuCOBOL against the generated Java).

## Install

```bash
specify extension add mainframe --from https://github.com/ankurmaan/spec-kit-mainframe/archive/refs/tags/v1.0.0.zip
# or, for development:
specify extension add --dev /path/to/spec-kit-mainframe
specify extension list
```

Requires Python ≥ 3.10 on the PATH; Docker for the GnuCOBOL legacy harness and the compose stack.

## Use

```
/speckit.mainframe.modernize /path/to/cobol-app                # phases 0-1, work-package plan; stops at the gap list
/speckit.mainframe.spec          # phase 2 -> Gate G1     /speckit.mainframe.decompose  # phase 3 -> G2
/speckit.mainframe.architect     # phase 4 -> G3         /speckit.mainframe.data       # phase 5 -> G4
/speckit.mainframe.build         # phase 6 -> G5         /speckit.mainframe.verify     # phases 7-8 -> G6/G7
/speckit.mainframe.gate --gate G1 --decision approved-with-conditions --by alice@x --condition "C1 ..."
/speckit.mainframe.status
```

`/speckit.mainframe.modernize <app> --auto-approve alice@x` runs unattended: gates are decided
in the approver's name, red evidence is waived (owner, control, expiry), never approved.

Hooks (all optional, offered by Spec Kit): after `/speckit.constitution` → add the
non-negotiables; before `/speckit.specify` → recover the legacy specification; before
`/speckit.plan` → derive the plan from the approved architecture; after `/speckit.tasks` →
attach evidence-gate criteria.

## How it works

| Phase | Judgement input (agent writes) | Generator (`scripts/`) | Gate |
|---|---|---|---|
| 0-1 intake, discovery | — | `modernize.py` → inventory, dependency graph, CRUD matrix, field maps, paragraph skeleton, work-package briefs | — |
| 2 specification recovery | `_fragments/WPn/{rules.jsonl,traceability.json,…}`, `use-cases.jsonl` | `merge_fragments.py`, `assemble_spec.py` | G1 |
| 3 domain decomposition | `3-domain/contexts.json` | `decompose.py` | G2 |
| 4 target architecture | `scores.json`, `waves.json`, ADRs | `architect.py` | G3 |
| 5 data modernization | `5-data/store-map.json` (proposed by `store_map.py`) | `datamod.py` — schema, mapping, byte round-trip proof, migration kit | G4 |
| 6 forward engineering | the code, tests citing `UC-`/`BR-` ids | `use_case_coverage.py`, `evidence_pack.py` | G5 |
| 7-8 verification, cutover | `target/legacy/harness.json`, `target/ops/golden-master.json` | `legacy_harness.py`, `golden_master.py`, `evidence_pack.py` | G6, G7 |
| any gate | — | `gate_decide.py` (approve / waive / `--auto` / `--check`) | |

Every generator refuses to produce an artifact it cannot validate and proposes its gate bound
to a SHA-256 manifest of the artifacts; a changed artifact voids the approval.

## Layout

`commands/` Spec Kit command templates · `scripts/` Python tools with `bash/` and `powershell/`
wrappers · `templates/` judgement-input templates · `profiles/` target stacks ·
`compliance-packs/` · `rules/` the invariants · `skills/` the phase and technique guidance the
commands reference · `agents/` sub-agent contracts (Claude Code hosts, via
`/speckit.mainframe.install-agents`) · `docs/` status, limitations, lessons learned.

## Status

Exercised end to end on AWS CardDemo (44 programs, 870 paragraphs): 440 rules traced 100 %,
11 contexts, Java + React stack deployed under Docker Compose, COBOL batch chain run under
GnuCOBOL, golden master 0 unexplained differences on the sample data. See `docs/STATUS.md` for
what is implemented versus designed, and `docs/LIMITATIONS.md` for what it deliberately does
not do.

## License

MIT
