---
description: "Record a gate decision (approve / approve-with-conditions / reject / waive), or check that approved artifacts are unchanged"
scripts:
  sh: scripts/bash/gate_decide.sh
  ps: scripts/powershell/gate_decide.ps1
---


# Gate decision

Arguments: `$ARGUMENTS` — passed straight through to `gate_decide.py`, e.g.
`--gate G1 --decision approved-with-conditions --by alice@x --condition "C1 …"`,
`--gate G4 --decision waived --by alice@x --control "Production extracts=re-run on extracts before wave 1"`,
`--gate G5 --auto --by alice@x --authorization "…"`, or `--check`.

```
{SCRIPT} --workspace <output> $ARGUMENTS
```

Rules the script enforces (do not argue with them): the decision binds to the manifest hash the pack was proposed with — changed artifacts are refused; judgement gates (G1-G3) with red checks need a `--condition` per check and cannot be plainly approved; evidence gates (G4-G7) with red rows can only be waived, one waiver file per red row with owner, control and expiry; every configured role must sign (quorum); `--auto` records the standing authorization verbatim into the decision record. Report the decision, the waivers written and the next phase.
