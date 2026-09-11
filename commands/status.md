---
description: "Where the modernization stands: phase, gates and their hash integrity, waves, coverage, red rows, waivers"
---


# Status

Arguments: `$ARGUMENTS` — `[output-path]`.

1. Read `<output>/modernization/state.json`: `current_phase`, `phases_complete`, `gates` (status, red_items, waivers), `waves`, `blanket_authorization`.
2. Run `python .specify/extensions/mainframe/scripts/gate_decide.py --workspace <output> --check` and report any gate whose artifacts changed since approval.
3. If phase 2 artifacts exist: `python .specify/extensions/mainframe/scripts/trace_coverage.py --source <source> --traceability <output>/modernization/2-specification/traceability.json --rules <output>/modernization/2-specification/business-rules.jsonl` — coverage must be 100 %.
4. If build artifacts exist: read `target/ops/out/use-case-coverage.json` and `golden-master-report.json` totals.
5. List open waivers from `governance/waivers/*.json` with owner and expiry; flag any past expiry.

Report as a short table; name the next command to run.
