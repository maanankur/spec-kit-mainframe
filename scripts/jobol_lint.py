#!/usr/bin/env python3
"""
jobol_lint.py -- structural lint that detects COBOL transliterated into Java.

"JOBOL" is Java that is really COBOL wearing Java syntax: one enormous method
per program, paragraph-numbered method names, working-storage held as mutable
fields, flags as single-character strings, money as double. It compiles, it may
even pass its tests, and it is unmaintainable -- which defeats the entire
business case for modernizing, because the reason to leave COBOL was never that
COBOL runs badly.

Two categories, and the difference matters:

  CORRECTNESS  numeric and encoding defects that produce wrong output. These are
               bugs. Non-negotiable.
  STRUCTURE    transliteration smells. These cost maintainability, not accuracy.

Usage:
  jobol_lint.py <path...> [--json] [--max-method-lines 60] [--max-class-lines 600]
                          [--severity error|warning|all] [--baseline FILE]

Exit 1 if any error-severity finding is present.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

MONEY_HINTS = ("amount", "amt", "balance", "bal", "credit", "debit", "limit",
               "rate", "interest", "price", "total", "fee", "payment", "cost",
               "tax", "discount", "principal", "premium")

# ---------------------------------------------------------------- correctness

CORRECTNESS = [
    ("money-as-binary-float",
     re.compile(r"\b(?:double|float|Double|Float)\s+(\w*(?:%s)\w*)\b"
                % "|".join(MONEY_HINTS), re.I),
     "monetary value held as binary floating point. COBOL is exact base-10; "
     "double is not. Use BigDecimal."),

    ("bigdecimal-from-double",
     re.compile(r"new\s+BigDecimal\s*\(\s*(?!\s*\")[^)\"]*?\b(?:\d+\.\d+|"
                r"[a-z]\w*(?:Amount|Amt|Balance|Rate|Total))\b[^)]*\)"),
     "new BigDecimal(double) captures the binary rounding error it was meant "
     "to avoid. Use new BigDecimal(String) or BigDecimal.valueOf."),

    ("setscale-without-rounding",
     re.compile(r"\.setScale\s*\(\s*\d+\s*\)"),
     "setScale without a RoundingMode throws on any inexact value. State the "
     "rounding COBOL actually used -- usually truncation (RoundingMode.DOWN), "
     "not HALF_UP."),

    ("divide-without-scale",
     re.compile(r"\.divide\s*\(\s*[^,)]+\s*\)"),
     "BigDecimal.divide without scale and RoundingMode throws "
     "ArithmeticException on non-terminating results. Specify both."),

    ("double-equality-on-money",
     re.compile(r"\b\w*(?:%s)\w*\s*==\s*" % "|".join(MONEY_HINTS), re.I),
     "== on a monetary value. For BigDecimal use compareTo() == 0; equals() "
     "also compares scale, so 1.0 != 1.00."),

    ("mainframe-read-without-charset",
     re.compile(r"new\s+(?:FileReader|InputStreamReader)\s*\(\s*[^,)]+\)"),
     "reading a byte stream without an explicit charset uses the platform "
     "default. Mainframe data is EBCDIC -- name the charset (Cp037/IBM037)."),

    ("string-getbytes-no-charset",
     re.compile(r"\.getBytes\s*\(\s*\)"),
     "getBytes() without a charset is platform-dependent; fixed-width output "
     "written this way will not match the mainframe byte for byte."),

    ("swallowed-exception",
     re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}"),
     "empty catch block. COBOL signals failure through file status codes that "
     "are easy to drop; silently swallowing the Java equivalent turns a failed "
     "write into a success."),
]

# ---------------------------------------------------------------- structure

STRUCTURE = [
    ("paragraph-named-method",
     re.compile(r"\b(?:public|private|protected)\s+\S+\s+"
                r"((?:p|para|proc)?_?\d{3,4}[A-Za-z_]\w*|\w*_\d{3,4}\w*)\s*\("),
     "method named after a COBOL paragraph number. Name it for what it does."),

    ("working-storage-field",
     re.compile(r"^\s*(?:private|protected|public)?\s*(?:static\s+)?"
                r"(?!final\b)\w+(?:<[^>]*>)?\s+(ws[A-Z_]\w*|WS_\w+)\s*[;=]",
                re.M),
     "working-storage carried as mutable object state. Pass values as "
     "parameters and return results; that is what makes the logic testable."),

    ("cobol-screaming-field",
     re.compile(r"^\s*(?:private|protected|public)\s+(?!static\s+final)"
                r"[\w<>\[\]]+\s+([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\s*[;=]", re.M),
     "COBOL data name kept verbatim as a non-constant field."),

    ("single-char-flag",
     re.compile(r"\.equals\s*\(\s*\"[YN]\"\s*\)|==\s*'[YN]'"),
     "single-character Y/N flag comparison. Use boolean or an enum -- the "
     "88-level condition names in the copybook tell you what the values mean."),

    ("level88-string-constant",
     re.compile(r"static\s+final\s+String\s+\w+\s*=\s*\"[A-Z0-9]{1,2}\"\s*;"),
     "88-level condition rendered as a String constant. Model it as an enum."),

    ("goto-style-label",
     re.compile(r"^\s*(?:[A-Z][A-Z0-9_]{3,})\s*:\s*(?:for|while|do|\{)", re.M),
     "labelled block used to emulate COBOL GO TO."),

    ("untrimmed-fixed-width-compare",
     re.compile(r"\.equals\s*\(\s*\"[^\"]*\s\"\s*\)"),
     "comparing against a space-padded literal. Trim fixed-width text at the "
     "boundary instead of padding comparisons throughout the code."),

    ("perform-comment",
     re.compile(r"//.*\b(?:PERFORM|MOVE\s+\w+\s+TO|GO\s+TO|EXEC\s+CICS)\b", re.I),
     "comment still describing the COBOL statement. The Java should be "
     "readable without reference to the original."),
]


# Rules whose whole purpose is to inspect a string literal. Blanking literals
# before matching would silently disable them -- worse than not having them,
# because the gate would then report PASS.
LITERAL_SENSITIVE = {"single-char-flag", "level88-string-constant",
                     "untrimmed-fixed-width-compare"}


def strip_comments(src: str) -> str:
    """Remove comments, preserving line numbering. String literals are kept."""
    src = re.sub(r"/\*[\s\S]*?\*/", lambda m: "\n" * m.group(0).count("\n"), src)
    return re.sub(r"//[^\n]*", "", src)


def strip_java_noise(src: str) -> str:
    """Remove comments AND string literals so patterns match code, not prose."""
    return re.sub(r'"(?:\\.|[^"\\\n])*"', '""', strip_comments(src))


def method_spans(src: str) -> list:
    """[(name, start_line, line_count)] by brace matching from each signature."""
    out = []
    sig = re.compile(
        r"^[ \t]*(?:@\w+[^\n]*\n[ \t]*)*"
        r"(?:public|private|protected|static|final|synchronized|abstract|\s)+"
        r"[\w<>\[\],\s?]+\s+(\w+)\s*\([^;{]*\)\s*(?:throws [\w,\s.]+)?\{", re.M)
    for m in sig.finditer(src):
        name = m.group(1)
        if name in ("if", "for", "while", "switch", "catch", "try", "do",
                    "synchronized", "new", "return"):
            continue
        i, depth = m.end() - 1, 0
        while i < len(src):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        start_line = src.count("\n", 0, m.start()) + 1
        end_line = src.count("\n", 0, i) + 1
        out.append((name, start_line, end_line - start_line + 1))
    return out


def lint_file(path: str, max_method: int, max_class: int) -> list:
    raw = open(path, "r", encoding="utf-8", errors="replace").read()
    code = strip_java_noise(raw)
    code_lit = strip_comments(raw)
    findings = []

    def view(rule):
        return code_lit if rule in LITERAL_SENSITIVE else code

    def add(rule, sev, line, message, detail=""):
        findings.append({"file": path.replace("\\", "/"), "line": line,
                         "rule": rule, "severity": sev, "message": message,
                         "detail": detail})

    for rule, rx, msg in CORRECTNESS:
        target = view(rule)
        for m in rx.finditer(target):
            add(rule, "error", target.count("\n", 0, m.start()) + 1, msg,
                m.group(0)[:90].strip())

    for rule, rx, msg in STRUCTURE:
        target = raw if rule == "perform-comment" else view(rule)
        for m in rx.finditer(target):
            add(rule, "warning", target.count("\n", 0, m.start()) + 1, msg,
                m.group(0)[:90].strip())

    for name, line, count in method_spans(code):
        if count > max_method:
            add("oversized-method", "warning", line,
                "method %s() is %d lines (limit %d). A COBOL paragraph chain "
                "translated whole becomes one giant method; decompose along the "
                "business rules instead." % (name, count, max_method))

    body_lines = len([l for l in code.splitlines() if l.strip()])
    if body_lines > max_class:
        add("oversized-class", "warning", 1,
            "%d code lines (limit %d) -- likely one Java class per COBOL "
            "program rather than per responsibility." % (body_lines, max_class))

    # a file that does monetary arithmetic and never mentions BigDecimal
    if re.search(r"\b\w*(?:%s)\w*\b" % "|".join(MONEY_HINTS), code, re.I) \
            and "BigDecimal" not in code \
            and re.search(r"[+\-*/]=|\b(?:add|subtract|multiply)\b", code):
        add("money-without-bigdecimal", "error", 1,
            "file computes on monetary fields but never uses BigDecimal.")
    return findings


def collect(paths: list) -> list:
    out = []
    for p in paths:
        if os.path.isfile(p) and p.endswith(".java"):
            out.append(p)
        for dirpath, dirnames, filenames in os.walk(p):
            dirnames[:] = [d for d in dirnames
                           if d not in ("target", "build", ".git", "node_modules")]
            for fn in sorted(filenames):
                if fn.endswith(".java"):
                    out.append(os.path.join(dirpath, fn))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--max-method-lines", type=int, default=60)
    ap.add_argument("--max-class-lines", type=int, default=600)
    ap.add_argument("--severity", default="all",
                    choices=("error", "warning", "all"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--baseline", help="JSON list of rule names to suppress")
    a = ap.parse_args()

    files = collect(a.paths)
    if not files:
        print("no .java files under %s" % ", ".join(a.paths), file=sys.stderr)
        return 2
    suppress = set(json.load(open(a.baseline))) if a.baseline else set()

    findings = []
    for f in files:
        findings.extend(x for x in lint_file(f, a.max_method_lines,
                                             a.max_class_lines)
                        if x["rule"] not in suppress)
    if a.severity != "all":
        findings = [f for f in findings if f["severity"] == a.severity]

    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]

    if a.json:
        print(json.dumps({"files": len(files), "errors": len(errors),
                          "warnings": len(warnings), "findings": findings},
                         indent=2))
    else:
        print("jobol-lint: %d file(s), %d error(s), %d warning(s)"
              % (len(files), len(errors), len(warnings)))
        by_rule = {}
        for f in findings:
            by_rule.setdefault((f["severity"], f["rule"]), []).append(f)
        for (sev, rule), items in sorted(by_rule.items(),
                                         key=lambda kv: (kv[0][0] != "error",
                                                         -len(kv[1]))):
            print("\n  [%s] %s  x%d" % (sev.upper(), rule, len(items)))
            print("      %s" % items[0]["message"])
            for it in items[:6]:
                loc = "%s:%d" % (os.path.basename(it["file"]), it["line"])
                print("      %-40s %s" % (loc, it.get("detail", "")))
            if len(items) > 6:
                print("      ... %d more" % (len(items) - 6))
        print("\nGATE %s" % ("FAIL" if errors else "PASS"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
