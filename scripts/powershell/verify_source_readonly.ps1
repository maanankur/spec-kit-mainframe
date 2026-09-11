# Thin wrapper: Spec Kit scripts are sh/ps entry points; the tool itself is Python.
$env:PYTHONIOENCODING = "utf-8"
& python (Join-Path $PSScriptRoot "..\verify_source_readonly.py") @args
exit $LASTEXITCODE
