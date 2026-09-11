# Changelog

## 1.0.1 — 2026-09-11

**Behavior change:** `modernize.py` (and `speckit.mainframe.modernize`/`assess`) now default the
output workspace to `./<app-name>-modernized` in the **current working directory** — the Spec
Kit project you ran the command from — instead of a sibling of the COBOL source. The source
path can still point anywhere and is still opened read-only; only the default *destination*
changed. Explicit `[output-path]`/`--out` are unaffected (still resolved relative to cwd). The
read-only guard now also refuses (with a clearer message) if the resolved output would nest
inside the source — e.g. running the command from inside the COBOL application itself.
Also fixed: `extension.yml`/`README.md` pointed at the wrong GitHub owner (`ankurmaan` instead
of `maanankur`).

## 1.0.0 — 2026-09-11

First release as a Spec Kit extension. Packaged from the Claude Code plugin
`mainframe-modernization` after two runs on AWS CardDemo: 12 commands, 4 optional hooks,
15 Python tools with sh/ps wrappers, 14 templates, one target profile, five compliance-pack
stubs, the phase and technique skills, 15 agent contracts.
