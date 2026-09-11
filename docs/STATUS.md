# Implementation status — what is built, what is scaffolded, what is design

Audited 2026-09-10 against `DESIGN.md` and the plugin tree. A framework that
governs generated code has no standing to overstate its own completeness.

## Built and exercised on CardDemo

| Component | Files | Evidence |
|---|---|---|
| Deterministic backbone | `scripts/` — `modernize.py`, `inventory.py`, `depgraph.py`, `copybook_parse.py`, `decode_record.py`, `trace_coverage.py`, `jobol_lint.py` | Phases 0–1 ran idempotently on 44 programs / 870 paragraphs; four parser defects found and fixed (see LESSONS-LEARNED.md B1–B4) |
| Agent contracts | `agents/` — 15 definitions, seven-part contract each | Used to brief phase-2 work packages |
| L0 router | `skills/mainframe-modernization/SKILL.md` | Drives every session |
| L1 phase skills | `skills/phases/01…07` — 7, now reconciled with the router; 03 rewritten | 02 drove specification recovery |
| L3 references | `skills/references/` — 3 of the 11 designed (`cobol-java-mapping`, `cics-jcl-mapping`, `pitfalls`) | |
| Rules (prose) | `rules/00…07` — 8 files | Enforcement is procedural until hooks exist |
| Commands | `commands/` — `/modernize` + 21 granular | `/modernize` used end to end for phases 0–2 |
| Templates | `templates/` — 14 (5 original + 9 judgement-input/brief templates) | `work-package-brief.md` drives phase 2; JSON templates drive phases 3–7 |
| Compliance pack | `compliance-packs/banking/pack.yaml` (1 of 5) | Controls reference `policy/*.rego` files that do not exist |
| Profile | `profiles/spring-postgres-react-aws.yaml` (1 of 4), extended with platform defaults | |
| Workflow doc | `workflows/full-modernization.yaml` (1 of 6) | Descriptive DAG; not executed by any orchestrator |
| Schema | `schemas/state.schema.json` (1 of 4) | |

## Exercised end to end on CardDemo (2026-09-10)

Phases 0–8 ran to `done` for wave 0/1 + inquiry slices: 440 rules / 870 paragraphs
traced; 11 contexts; 10 ADRs; schema + fidelity proof; Java (Spring Boot 3) built
and deployed under compose; the COBOL batch chain executed under GnuCOBOL; golden
master **7,429 identical / 612 explained / 0 unexplained**. G4–G7 recorded under a
blanket authorization with red rows waived. Phases 3–8 were run inline by the
orchestrating session (the tier agents lack the tools), with generators under the
workspace's `modernization/tools/`.

## Generalised (2026-09-10, second pass)

The workspace generators were moved into `scripts/` as data-driven, application-
agnostic tools and re-verified against the first run's artifacts on a scratch copy
(same rules, contexts, verdicts, wave scores; legacy outputs byte-identical except
run-time timestamps):

| Script | Judgement input | Output / gate |
|---|---|---|
| `paragraph_skeleton.py`, `work_packages.py` (run by `modernize.py`) | — | `tools/paragraph-skeleton.json`, `_fragments/plan.json` + `WPn/brief.md` from `templates/work-package-brief.md` |
| `merge_fragments.py`, `assemble_spec.py` | WP fragments, `spec-front-matter.md`, `use-cases.jsonl` | `business-rules.jsonl`, `traceability.json`, `spec.md`, `coverage-report.md`; G1 proposed |
| `decompose.py` | `3-domain/contexts.json` | `decomposition.json`, `context-map.md`, `glossary.md`; G2 |
| `architect.py` | `scores.json`, `waves.json`, `adr/*.md`, `nfr-allocation.md` | `style-decision.md`, `wave-plan.md`, `architecture.md`, `c4/`, ADR-000 from the profile; G3 |
| `store_map.py` → `datamod.py` | `5-data/store-map.json` (proposed, then confirmed) | `schema.sql`, `mapping.json`, `fidelity-report.md`, `migration/*`; G4 |
| `use_case_coverage.py` | tests citing `UC-…`/`BR-…` + surefire/failsafe XML | `use-case-coverage.{json,md}` — executed evidence only |
| `legacy_harness.py`, `golden_master.py` | `target/legacy/harness.json`, `target/ops/golden-master.json` | legacy outputs under GnuCOBOL; typed comparison with layouts from `mapping.json` |
| `evidence_pack.py` | evidence files only | G5 / G6 / G7 packs |
| `gate_decide.py` | — | the only writer of gate status: approve / approve-with-conditions / reject / waive; `--auto` under a recorded authorization; `--check` re-hashes |
| `verify_source_readonly.py` | — | source-tree integrity against the intake register |

Templates added: `work-package-brief.md`, `spec-front-matter.md`, `contexts.json`,
`scores.json`, `waves.json`, `golden-master.json`, `use-cases.jsonl`,
`cutover-plan.md`, `runbook.md`. First technique skill written:
`techniques/golden-master-harness`. `/modernize --auto-approve <id>` records the
standing authorization that the first run only had as a chat instruction.

## Scaffolded — directory or reference exists, no implementation

| Component | Designed | Actual | Consequence today |
|---|---|---|---|
| MCP servers (Ring 1/2/4) | 9 custom servers with `server.py` | **14 empty directories**; `structurizr` referenced but no directory | Agents' `mcp__cobol__*`, `mcp__knowledge_graph__*`, `mcp__gate_ledger__*` … grants resolve to nothing; no knowledge graph exists; gate ledger and evidence signing are not available |
| Hook scripts | 18 enforcements in `hooks/hooks.json` | **`hooks/scripts/` is empty** | The specification firewall, workspace confinement, gate discipline, BigDecimal check, JOBOL lint-on-write and secret scan are **not mechanically enforced** — only stated in `rules/` and agent contracts |
| L2 technique skills | 24 | **1 written** (`golden-master-harness`), 23 empty directories | The router's load-on-trigger table loads nothing for the other triggers |
| Eval suite | corpora, skill-triggering, end-to-end | **empty** | Nothing guards against regression or layer drift (LESSONS-LEARNED.md C2) |
| Compliance packs | 5 | 1 (`banking`) | `--industry insurance|telecom|retail|government` selects nothing |
| Profiles | 4 | 1 | `--ui angular`, `--database oracle` have no profile behind them |
| Workflows | 6 | 1 | |
| Schemas | 4 | 1 | Graph, decision-record and config schemas absent |
| Docs | 6 | `README`, `LIMITATIONS`, now `STATUS`, `LESSONS-LEARNED` | `ARCHITECTURE`, `OPERATING-MODEL`, `EXTENDING`, `SECURITY` absent |

## Agent-contract defects still open

- `reverse-engineering-agent`, `discovery-agent`, `domain-modeling-agent`,
  `architecture-agent`, `compliance-agent`, `knowledge-graph-curator` have **no
  `Write` tool**, yet each owns artifacts. Until the graph MCP exists they cannot
  produce their outputs; phase 2 was run with general-purpose agents under a
  written briefing instead.
- The `code-generation-agent` firewall (`Read(app/cbl/**)` forbidden) is a
  statement in the contract, not a permission — the `firewall_guard.py` hook
  that would enforce it does not exist.

## What this means for a demonstration

Safe to show live: phases 0–1 output, the four parser corrections, phase-2
specification recovery with sourced rules and paragraph-level traceability, the
gate-review pack. Safe to describe as design: knowledge graph, MCP tool plane,
hook enforcement, technique library, evals, other packs and profiles. Do not
claim mechanical enforcement of any rule until `hooks/scripts/` is populated.
