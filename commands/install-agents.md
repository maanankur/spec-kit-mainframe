---
description: "For Claude Code hosts: install the plugin's sub-agent contracts and skills into .claude/ so the phase commands can delegate"
---


# Install agents and skills (Claude Code only)

Arguments: `$ARGUMENTS`

Spec Kit registers commands for any agent; sub-agents and skills are a Claude Code concept. If the host is Claude Code:

1. Copy `.specify/extensions/mainframe/agents/*.md` → `.claude/agents/` and `.specify/extensions/mainframe/skills/**` → `.claude/skills/` (overwrite; these are the extension's versions).
2. Tell the user which agents are now available (`reverse-engineering-agent`, `domain-modeling-agent`, `architecture-agent`, `data-modernization-agent`, `code-generation-agent`, `test-generation-agent`, `validation-agent`, …) and that `code-generation-agent` / `ui-generation-agent` have no read path to COBOL by contract.

On any other host, say so and do nothing — the phase commands already carry the instructions the agents would have loaded.
