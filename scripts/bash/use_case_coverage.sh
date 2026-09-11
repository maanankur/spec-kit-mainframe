#!/usr/bin/env bash
# Thin wrapper: Spec Kit scripts are sh/ps entry points; the tool itself is Python.
# `pwd -W` yields a Windows path under Git Bash/MSYS so a Windows python.exe can open it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && (pwd -W 2>/dev/null || pwd))"
export PYTHONIOENCODING=utf-8
exec python "$HERE/../use_case_coverage.py" "$@"
