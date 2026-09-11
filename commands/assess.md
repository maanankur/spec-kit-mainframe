---
description: "Read-only assessment of a COBOL application: census, inventory, dependency graph, hazards, gap list, effort model"
scripts:
  sh: scripts/bash/modernize.sh
  ps: scripts/powershell/modernize.ps1
---


# Assess

Arguments: `$ARGUMENTS` — `<cobol-app-path> [output-path]`.

```
{SCRIPT} $ARGUMENTS --assess
```

Then produce the assessment report from `<output>/modernization/1-discovery/*` and `0-intake/gap-list.md`: program kinds and sizes, complexity ranking, hazards (`ALTER`, `GO TO DEPENDING ON`, dynamic CALL, assembler, MQ, IMS), dead-code candidates (static only — say so), data clusters and shared stores (split risk), missing inputs, and an effort model by cluster. No gates, no generation, nothing written outside `<output>`.
