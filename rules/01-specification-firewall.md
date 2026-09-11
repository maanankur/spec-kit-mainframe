# Rule 1 - The specification firewall

Read the COBOL to *write the specification*. Read the *specification* to write the Java.

The Code Generation and UI Generation agents have no read path to COBOL source. This is a
filesystem and MCP permission, enforced by `hooks/scripts/firewall_guard.py`, not a
convention. If the specification is ambiguous on a numeric or edge-case behaviour, the fix
is to amend the specification - which means going back through Reverse Engineering and, if
the change is material, back through G1.

Code that mirrors COBOL paragraph structure is a defect. `jobol_lint.py` fails the build on
it. Removing the mainframe while keeping every reason it was a problem is not modernization.
