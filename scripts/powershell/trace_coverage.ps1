# Thin wrapper: Spec Kit scripts are sh/ps entry points; the tool itself is Python.
$env:PYTHONIOENCODING = "utf-8"
& python (Join-Path $PSScriptRoot "..\trace_coverage.py") @args
exit $LASTEXITCODE
