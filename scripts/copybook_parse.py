#!/usr/bin/env python3
"""
copybook_parse.py -- COBOL copybook -> deterministic field/offset map.

This is the keystone artifact of the modernization pipeline. Record-oriented
mainframe datasets are opaque bytes; the copybook IS the schema. Every
downstream artifact -- Java POJOs, SQL DDL, the data-migration loader, and the
byte-level fidelity harness -- must derive from ONE authoritative field map so
that they cannot drift from each other.

Offsets and sizes are arithmetic. Never let a language model infer them.

Usage:
  copybook_parse.py <copybook...> [--out DIR] [--json] [--free-form]
                                  [--sync] [--strict]

Output (per copybook):
  {"copybook":..., "records":[{"name":..., "length":..., "fields":[
     {path, level, name, offset, length, pic, usage, digits, scale, signed,
      occurs, redefines, odo, kind, java_type, sql_type}]}], "warnings":[...]}

Exit codes: 0 ok, 1 warnings raised under --strict, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------- lexing

_COMMENT_INDICATORS = {"*", "/"}


def read_source_lines(path: str, free_form: bool) -> list:
    """Return [(line_no, code_text)] with sequence/indicator/ident areas removed.

    Fixed-form COBOL reserves cols 1-6 (sequence), col 7 (indicator: '*' or '/'
    means comment, '-' means continuation), cols 8-72 (code), cols 73-80
    (identification). Copybooks in the wild are almost always fixed-form even
    when the compiler runs in free-form mode, so fixed-form is the default and
    must be overridden explicitly rather than guessed.
    """
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for n, raw in enumerate(fh, start=1):
            line = raw.rstrip("\r\n").replace("\t", "    ")
            if free_form:
                stripped = line.lstrip()
                if stripped.startswith("*"):
                    continue
                if stripped:
                    out.append((n, line))
                continue
            if len(line) >= 7 and line[6] in _COMMENT_INDICATORS:
                continue
            code = line[7:72] if len(line) > 7 else ""
            if code.strip():
                out.append((n, code))
    return out


def statements(lines: list) -> list:
    """Join physical lines into period-terminated COBOL data statements."""
    stmts = []
    buf = []
    start = 0
    for n, code in lines:
        if not buf:
            start = n
        buf.append(code.strip())
        joined = " ".join(buf)
        while "." in joined:
            head, _, tail = joined.partition(".")
            if head.strip():
                stmts.append((start, " ".join(head.split())))
            joined = tail
            start = n
        buf = [joined] if joined.strip() else []
    tail_text = " ".join(buf).strip()
    if tail_text:
        stmts.append((start, " ".join(tail_text.split())))
    return stmts


# ---------------------------------------------------------------- PIC sizing

_USAGE_ALIASES = {
    "COMP": "COMP", "COMPUTATIONAL": "COMP", "BINARY": "COMP",
    "COMP-4": "COMP", "COMPUTATIONAL-4": "COMP",
    "COMP-5": "COMP-5", "COMPUTATIONAL-5": "COMP-5", "NATIVE-BINARY": "COMP-5",
    "COMP-3": "COMP-3", "COMPUTATIONAL-3": "COMP-3", "PACKED-DECIMAL": "COMP-3",
    "COMP-1": "COMP-1", "COMPUTATIONAL-1": "COMP-1",
    "COMP-2": "COMP-2", "COMPUTATIONAL-2": "COMP-2",
    "DISPLAY": "DISPLAY", "DISPLAY-1": "DISPLAY-1",
    "NATIONAL": "NATIONAL", "POINTER": "POINTER", "INDEX": "INDEX",
}

_EDIT_CHARS = {"Z", "*", ",", ".", "+", "-", "$", "B", "0", "/", "CR", "DB"}


def expand_pic(pic: str) -> list:
    """'S9(5)V99' -> [('S',1), ('9',5), ('V',1), ('9',2)]."""
    out = []
    i = 0
    up = pic.upper()
    while i < len(up):
        two = up[i:i + 2]
        if two in ("CR", "DB"):
            out.append((two, 1))
            i += 2
            continue
        ch = up[i]
        i += 1
        if i < len(up) and up[i] == "(":
            close = up.find(")", i)
            if close == -1:
                out.append((ch, 1))
                continue
            try:
                rep = int(up[i + 1:close])
            except ValueError:
                rep = 1
            out.append((ch, rep))
            i = close + 1
        else:
            out.append((ch, 1))
    return out


def analyse_pic(pic: str, usage: str, sign_separate: bool) -> dict:
    """Return kind / digits / scale / signed / bytes for a PICTURE clause."""
    sym = expand_pic(pic)
    counts = {}
    for s, r in sym:
        counts[s] = counts.get(s, 0) + r

    signed = "S" in counts
    has_9 = counts.get("9", 0) > 0
    has_alpha = counts.get("X", 0) > 0 or counts.get("A", 0) > 0
    is_edited = bool(_EDIT_CHARS & set(counts))

    digits = counts.get("9", 0)
    scale = 0
    if "V" in counts:
        seen = False
        for s, r in sym:
            if s == "V":
                seen = True
            elif s == "9" and seen:
                scale += r
    elif "." in counts and is_edited:
        seen = False
        for s, r in sym:
            if s == ".":
                seen = True
            elif s in ("9", "Z", "*") and seen:
                scale += r

    if is_edited and not has_alpha:
        kind = "numeric-edited"
        digits = counts.get("9", 0) + counts.get("Z", 0) + counts.get("*", 0)
    elif has_alpha:
        if counts.get("B", 0) or counts.get("0", 0) or counts.get("/", 0):
            kind = "alphanumeric-edited"
        elif counts.get("A", 0) and not counts.get("X", 0):
            kind = "alphabetic"
        else:
            kind = "alphanumeric"
    elif has_9:
        kind = "numeric"
    else:
        kind = "unknown"

    # ---- storage size in bytes
    if usage == "COMP-3":
        # packed decimal: one nibble per digit plus one sign nibble, rounded up
        nbytes = (digits + 2) // 2
    elif usage in ("COMP", "COMP-5"):
        nbytes = 2 if digits <= 4 else (4 if digits <= 9 else 8)
    elif usage == "COMP-1":
        nbytes = 4
    elif usage == "COMP-2":
        nbytes = 8
    elif usage in ("NATIONAL", "DISPLAY-1"):
        nbytes = sum(r for s, r in sym if s not in ("V", "S", "P")) * 2
    elif usage in ("POINTER", "INDEX"):
        nbytes = 4
    else:  # DISPLAY: zoned decimal for numerics, one byte per character position
        nbytes = 0
        for s, r in sym:
            if s in ("V", "S", "P"):
                continue  # implied point / overpunched sign / scaling: no byte
            nbytes += 2 * r if s in ("CR", "DB") else r
        if signed and sign_separate:
            nbytes += 1

    return {"kind": kind, "digits": digits, "scale": scale,
            "signed": signed, "bytes": nbytes, "edited": is_edited}


# ---------------------------------------------------------------- type mapping

def java_type(f: dict) -> str:
    """Map to the Java type that preserves COBOL semantics, not the convenient one.

    Money and any scaled decimal MUST be BigDecimal. COBOL arithmetic is exact
    base-10 and truncates by default; binary floating point is neither exact nor
    truncating. A cent lost per transaction is a production defect that
    happy-path unit tests will not catch.
    """
    kind, usage = f.get("kind"), f.get("usage")
    if kind == "group":
        return "/* nested type */"
    if usage in ("COMP-1", "COMP-2"):
        return "double"  # already binary float on the mainframe; flagged as a smell
    if kind == "numeric":
        if f.get("scale", 0) > 0:
            return "BigDecimal"
        d = f.get("digits", 0)
        if d <= 9:
            return "Integer"
        if d <= 18:
            return "Long"
        return "BigInteger"
    if kind == "numeric-edited":
        return "String"  # presentation format: parse only, never compute on it
    return "String"


def sql_type(f: dict) -> str:
    kind, usage = f.get("kind"), f.get("usage")
    if kind == "group":
        return "-- nested"
    if usage in ("COMP-1", "COMP-2"):
        return "DOUBLE PRECISION"
    if kind == "numeric":
        d, s = f.get("digits", 0), f.get("scale", 0)
        if s:
            return "NUMERIC(%d,%d)" % (d, s)
        return "INTEGER" if d <= 9 else ("BIGINT" if d <= 18 else "NUMERIC(%d,0)" % d)
    return "CHAR(%d)" % f["length"] if f.get("length") else "TEXT"


# ---------------------------------------------------------------- parsing

_LEVEL_RE = re.compile(r"^(\d{1,2})\s+(\S+)(.*)$")
_PIC_RE = re.compile(r"\b(?:PIC|PICTURE)\s+(?:IS\s+)?([^\s.]+)", re.I)
_OCCURS_RE = re.compile(
    r"\bOCCURS\s+(?:(\d+)\s+TO\s+)?(\d+)\s*(?:TIMES)?"
    r"(?:.*?\bDEPENDING\s+(?:ON\s+)?([A-Z0-9\-_]+))?", re.I)
_REDEF_RE = re.compile(r"\bREDEFINES\s+([A-Z0-9\-_]+)", re.I)
_USAGE_RE = re.compile(
    r"\b(?:USAGE\s+(?:IS\s+)?)?("
    + "|".join(sorted(_USAGE_ALIASES, key=len, reverse=True)) + r")\b", re.I)
_SIGN_SEP_RE = re.compile(r"\bSIGN\b.*\bSEPARATE\b", re.I)
_VALUE_RE = re.compile(r"\bVALUE\s+(?:IS\s+)?(.+)$", re.I)


class Node:
    __slots__ = ("level", "name", "clauses", "line", "children", "parent",
                 "pic", "usage", "occurs", "occurs_min", "odo", "redefines",
                 "sign_separate", "value", "offset", "length", "info")

    def __init__(self, level, name, clauses, line):
        self.level, self.name, self.clauses, self.line = level, name, clauses, line
        self.children = []
        self.parent = None
        self.offset = 0
        self.length = 0
        self.pic = None
        self.redefines = None
        self.odo = None
        self.value = None
        self.usage = None
        self.occurs = 1
        self.occurs_min = None
        self.sign_separate = False
        self.info = {}


def parse_copybook(path: str, free_form=False, sync=False) -> dict:
    warnings = []
    stmts = statements(read_source_lines(path, free_form))

    roots = []
    stack = []
    conditions = {}

    for line_no, text in stmts:
        m = _LEVEL_RE.match(text)
        if not m:
            if text.strip():
                warnings.append("%s:%d: unparsed statement: %s"
                                % (path, line_no, text[:70]))
            continue
        level, name, rest = int(m.group(1)), m.group(2).upper(), m.group(3)

        if level == 88:
            owner = stack[-1].name if stack else "?"
            vm = _VALUE_RE.search(rest)
            conditions.setdefault(owner, []).append(
                {"name": name, "values": vm.group(1).strip() if vm else None})
            continue
        if level == 66:
            warnings.append("%s:%d: 66 RENAMES '%s' ignored -- re-express as an "
                            "explicit accessor in Java" % (path, line_no, name))
            continue

        node = Node(level, name, rest, line_no)
        pm = _PIC_RE.search(rest)
        if pm:
            node.pic = pm.group(1).rstrip(".")
        om = _OCCURS_RE.search(rest)
        if om:
            node.occurs = int(om.group(2))
            node.occurs_min = int(om.group(1)) if om.group(1) else None
            node.odo = om.group(3).upper() if om.group(3) else None
        rm = _REDEF_RE.search(rest)
        if rm:
            node.redefines = rm.group(1).upper()
        um = _USAGE_RE.search(rest)
        if um:
            node.usage = _USAGE_ALIASES[um.group(1).upper()]
        node.sign_separate = bool(_SIGN_SEP_RE.search(rest))
        vm = _VALUE_RE.search(rest)
        if vm:
            node.value = vm.group(1).strip()

        if level == 1 or level == 77 or not stack:
            roots.append(node)
            stack = [node]
        else:
            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                node.parent = stack[-1]
                stack[-1].children.append(node)
            else:
                roots.append(node)
            stack.append(node)

    # A copybook with no 01/77 level is a fragment meant to be COPY'd under the
    # caller's record (IMS segment copybooks do this). Parsed as-is, every
    # top-level item became its own "record" at offset 0 -- CardDemo CIPAUSMY
    # and CIPAUDTY reported offset 0 for all 13 and 27 fields. Wrap them in an
    # implicit record so offsets and the record length are real.
    if len(roots) > 1 and all(r.level not in (1, 77) for r in roots):
        wrapper = Node(1, os.path.splitext(os.path.basename(path))[0].upper()
                       + "-RECORD", "", roots[0].line)
        for r in roots:
            r.parent = wrapper
            wrapper.children.append(r)
        warnings.append("%s: no 01 level -- %d top-level items wrapped in the "
                        "implicit record %s" % (path, len(roots), wrapper.name))
        roots = [wrapper]

    for r in roots:
        _inherit_usage(r, "DISPLAY")
        _size(r, warnings, path, sync)
        _assign_offsets(r, 0, warnings, path)

    records = []
    for r in roots:
        fields = []
        _flatten(r, r.name, fields, conditions)
        records.append({"name": r.name, "length": r.length, "fields": fields})
    return {"copybook": os.path.basename(path), "path": path,
            "records": records, "warnings": warnings}


def _inherit_usage(n: Node, inherited: str) -> None:
    """USAGE on a group applies to every subordinate elementary item."""
    eff = n.usage or inherited
    n.usage = eff
    for c in n.children:
        _inherit_usage(c, eff)


def _size(n: Node, warnings, path, sync) -> None:
    if n.children:
        total = 0
        for c in n.children:
            _size(c, warnings, path, sync)
            if c.redefines:
                continue  # occupies existing storage; does not extend the group
            total += c.length
        n.length = total * n.occurs
        n.info = {"kind": "group", "digits": 0, "scale": 0,
                  "signed": False, "bytes": total, "edited": False}
        if n.pic:
            warnings.append("%s:%d: '%s' has both PIC and subordinates -- "
                            "treated as a group" % (path, n.line, n.name))
    else:
        if not n.pic:
            if n.usage in ("POINTER", "INDEX", "COMP-1", "COMP-2"):
                n.info = analyse_pic("9(9)", n.usage, False)
            else:
                n.info = {"kind": "group", "digits": 0, "scale": 0,
                          "signed": False, "bytes": 0, "edited": False}
                warnings.append("%s:%d: elementary item '%s' has no PIC and no "
                                "children -- length 0" % (path, n.line, n.name))
        else:
            n.info = analyse_pic(n.pic, n.usage, n.sign_separate)
        n.length = n.info["bytes"] * n.occurs

    if n.odo:
        warnings.append(
            "%s:%d: '%s' is OCCURS DEPENDING ON %s. Offsets after it are valid "
            "only at the MAXIMUM occurrence (%d). Records are variable-length: "
            "the Java reader must compute length from %s, not assume a fixed "
            "record." % (path, n.line, n.name, n.odo, n.occurs, n.odo))
    if sync:
        warnings.append("%s:%d: --sync requested but SYNCHRONIZED slack-byte "
                        "insertion is not modelled; verify offsets against a "
                        "compiler listing before trusting them."
                        % (path, n.line))


def _assign_offsets(n: Node, base: int, warnings, path) -> None:
    n.offset = base
    cur = base
    by_name = {c.name: c for c in n.children}
    for c in n.children:
        if c.redefines:
            target = by_name.get(c.redefines)
            if target is None:
                warnings.append("%s:%d: REDEFINES %s not found among siblings "
                                "of '%s'" % (path, c.line, c.redefines, c.name))
                _assign_offsets(c, cur, warnings, path)
                continue
            if c.length > target.length:
                warnings.append(
                    "%s:%d: '%s' REDEFINES '%s' but is larger (%d > %d bytes) "
                    "-- it overlays following fields. Model as a discriminated "
                    "union in Java, never as two independent columns."
                    % (path, c.line, c.name, target.name, c.length, target.length))
            _assign_offsets(c, target.offset, warnings, path)
            continue
        _assign_offsets(c, cur, warnings, path)
        cur += c.length


def _flatten(n: Node, path_str: str, out: list, conditions: dict) -> None:
    rec = {
        "path": path_str, "level": n.level, "name": n.name,
        "offset": n.offset, "length": n.length,
        "pic": n.pic, "usage": n.usage,
        "kind": n.info.get("kind"), "digits": n.info.get("digits", 0),
        "scale": n.info.get("scale", 0), "signed": n.info.get("signed", False),
        "occurs": n.occurs, "occurs_min": n.occurs_min, "odo": n.odo,
        "redefines": n.redefines, "value": n.value,
        "conditions": conditions.get(n.name, []),
    }
    rec["java_type"] = java_type(rec)
    rec["sql_type"] = sql_type(rec)
    out.append(rec)
    for c in n.children:
        _flatten(c, "%s.%s" % (path_str, c.name), out, conditions)


# ---------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("copybooks", nargs="+")
    ap.add_argument("--out", help="write <name>.fieldmap.json into this directory")
    ap.add_argument("--json", action="store_true", help="dump JSON to stdout")
    ap.add_argument("--free-form", action="store_true")
    ap.add_argument("--sync", action="store_true",
                    help="source compiled with SYNCHRONIZED (warns: unmodelled)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any warning was raised")
    a = ap.parse_args()

    results = []
    warned = False
    for cb in a.copybooks:
        try:
            r = parse_copybook(cb, a.free_form, a.sync)
        except Exception as e:  # a bad copybook must not abort the batch
            print("ERROR %s: %s" % (cb, e), file=sys.stderr)
            warned = True
            continue
        results.append(r)
        warned = warned or bool(r["warnings"])
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            stem = os.path.splitext(os.path.basename(cb))[0]
            with open(os.path.join(a.out, stem + ".fieldmap.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(r, fh, indent=2)
        if not a.json:
            for rec in r["records"]:
                print("\n%s  record %s  length=%d bytes"
                      % (r["copybook"], rec["name"], rec["length"]))
                print("  %5s %4s  %-58s %-14s %-9s %-11s"
                      % ("OFF", "LEN", "PATH", "PIC", "USAGE", "JAVA"))
                for f in rec["fields"]:
                    print("  %5d %4d  %-44s %-14s %-9s %-11s%s%s"
                          % (f["offset"], f["length"], f["path"][:58],
                             f["pic"] or "", f["usage"] or "", f["java_type"],
                             "  <ODO>" if f["odo"] else "",
                             "  <REDEF>" if f["redefines"] else ""))
            for w in r["warnings"]:
                print("  WARN %s" % w, file=sys.stderr)

    if a.json:
        print(json.dumps(results, indent=2))
    return 1 if (warned and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
