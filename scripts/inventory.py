#!/usr/bin/env python3
"""
inventory.py -- deterministic inventory and classification of a mainframe codebase.

Phase 1 of the modernization pipeline. Produces the single authoritative census
of what exists, how big it is, how tangled it is, and what each program talks to.
depgraph.py consumes this file rather than re-parsing the source, so the two can
never disagree.

Re-runnable and stable: the same source tree yields byte-identical output. That
property is what makes the audit trail defensible.

Three things here matter more than the counting:

  * Symbolic constant resolution. Real COBOL rarely writes
    EXEC CICS READ FILE('ACCTDAT'). It writes DATASET(LIT-ACCTFILENAME) where
    LIT-ACCTFILENAME is 05 ... PIC X(8) VALUE 'ACCTDAT '. Analysis that does not
    resolve that indirection sees no data coupling at all, invents one domain per
    program, and produces a decomposition that is confidently wrong.
  * DATASET and FILE are CICS synonyms. Matching only one loses half the graph.
  * XCTL/LINK targets are control flow. In a CICS pseudo-conversational app the
    screen-to-screen navigation lives entirely in XCTL, so ignoring it means
    ignoring the application's actual structure.

Usage:
  inventory.py <source-root> [--out modernization/1-discovery/inventory.json]
                             [--print] [--csv FILE]

Classification of COBOL programs:
  cics-online  EXEC CICS with SEND/RECEIVE MAP  -> becomes REST + screen
  cics-utility EXEC CICS but paints no map      -> becomes a service
  batch        FILE-CONTROL / SORT, no CICS     -> becomes a Spring Batch job
  subroutine   PROCEDURE DIVISION USING, no I/O -> becomes a bean method
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

COBOL_EXT = {".cbl", ".cob", ".cobol"}
COPY_EXT = {".cpy", ".copy"}
JCL_EXT = {".jcl", ".prc", ".proc"}
BMS_EXT = {".bms"}
DDL_EXT = {".ddl", ".sql", ".dcl"}
ASM_EXT = {".asm", ".mac", ".maclib"}
CSD_EXT = {".csd"}
SCHED_EXT = {".ca7", ".controlm", ".ctm", ".tws", ".zeke", ".opc"}

RE_PROGRAM_ID = re.compile(r"\bPROGRAM-ID\s*\.\s*([A-Z0-9\-_]+)", re.I)
RE_COPY = re.compile(r"\bCOPY\s+([A-Z0-9\-_]+)", re.I)
RE_SELECT = re.compile(r"\bSELECT\s+([A-Z0-9\-_]+)\s+ASSIGN\s+TO\s+([A-Z0-9\-_]+)",
                       re.I)
RE_EXEC_CICS = re.compile(r"\bEXEC\s+CICS\b", re.I)
RE_EXEC_SQL = re.compile(r"\bEXEC\s+SQL\b", re.I)
RE_SQL_TABLE = re.compile(
    r"\b(?:FROM|INTO|UPDATE|JOIN|DELETE\s+FROM)\s+([A-Z][A-Z0-9_\.]*)", re.I)
RE_MQ = re.compile(r"\bMQ(?:OPEN|CLOSE|GET|PUT|PUT1|CONN|DISC)\b", re.I)
RE_IMS = re.compile(r"\b(?:CBLTDLI|AIBTDLI)\b", re.I)
RE_PROC_USING = re.compile(r"\bPROCEDURE\s+DIVISION\s+USING\b", re.I)
RE_PARA = re.compile(r"^\s{0,4}([A-Z0-9][A-Z0-9\-_]*)\s*\.\s*$", re.I)
RE_SEND_MAP = re.compile(r"\bEXEC\s+CICS\s+(?:SEND|RECEIVE)\s+MAP\b", re.I)

# 05  LIT-ACCTFILENAME  PIC X(8)  VALUE 'ACCTDAT '.
RE_CONST = re.compile(
    r"^\s*\d\d\s+([A-Z0-9\-_]+)\s+.*?\bVALUE\s+(?:IS\s+)?'([^']*)'", re.I)

RE_DECISION = re.compile(
    r"\b(IF|EVALUATE|WHEN|UNTIL|VARYING|AND|OR|GO\s+TO|WHEN\s+OTHER)\b", re.I)

# CALL operands that are COBOL keywords or obvious prose, not program names.
CALL_NOISE = {
    "TO", "IF", "AND", "OR", "THE", "A", "AN", "IS", "WAS", "FAIL", "FAILED",
    "ERROR", "USING", "RETURNING", "BY", "REFERENCE", "CONTENT", "VALUE",
    "END-CALL", "ASSEMBLER", "PROGRAM", "ROUTINE", "SUB", "SUBROUTINE",
    "MENU", "CARD", "THIS", "THAT", "NOT", "WITH", "FROM", "INTO", "IN",
    "STATEMENT", "ABOVE", "BELOW", "HERE", "MODULE", "SECTION",
    "THRU", "THROUGH", "END-IF", "ELSE", "WHEN", "PERFORM", "PARA",
}

HAZARDS = {
    "ALTER": re.compile(r"\bALTER\b", re.I),
    "GO TO DEPENDING ON": re.compile(r"\bGO\s+TO\b.*\bDEPENDING\s+ON\b", re.I),
    "SORT procedure": re.compile(r"\b(?:INPUT|OUTPUT)\s+PROCEDURE\b", re.I),
    "ENTRY point": re.compile(r"\bENTRY\s+'", re.I),
    "pointer/ADDRESS OF": re.compile(r"\bADDRESS\s+OF\b|\bSET\s+ADDRESS\b", re.I),
    "COMP-1/COMP-2 float": re.compile(r"\bCOMP-[12]\b", re.I),
    "ACCEPT FROM": re.compile(r"\bACCEPT\b.*\bFROM\b", re.I),
    "EXEC CICS LINK": re.compile(r"\bEXEC\s+CICS\s+LINK\b", re.I),
}


# ---------------------------------------------------------------- source prep

def strip_fixed_form(text: str) -> str:
    """Drop sequence area, comment lines and identification area."""
    out = []
    for line in text.splitlines():
        if len(line) >= 7 and line[6] in ("*", "/"):
            continue
        out.append(line[7:72] if len(line) > 7 else "")
    return "\n".join(out)


RE_DIVISION_HDR = re.compile(r"\b(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION", re.I)
RE_PARA_LINE = re.compile(r"^([A-Z0-9][A-Z0-9\-_]*)\s*\.\s*$", re.I)
NOT_PARAGRAPHS = {"SECTION", "DIVISION", "END-EXEC", "EXIT", "GOBACK", "STOP",
                  "DECLARATIVES", "FILE-CONTROL", "TODAY"}


def procedure_paragraphs(raw: str) -> list:
    """Paragraph names in the PROCEDURE DIVISION, area A only.

    The earlier whole-file pattern counted PROGRAM-ID, DATE-WRITTEN, END-IF,
    GOBACK and FILE-CONTROL as paragraphs and overstated CardDemo by 19%
    (1,033 vs 870). Mirrors trace_coverage.py so the two agree.
    """
    paras, in_proc = [], False
    for line in raw.splitlines():
        if len(line) >= 7 and line[6] in ("*", "/"):
            continue
        code = line[6:72] if len(line) > 6 else ""
        if not code.strip():
            continue
        if RE_DIVISION_HDR.search(code):
            in_proc = bool(re.search(r"\bPROCEDURE\s+DIVISION", code, re.I))
            continue
        if not in_proc:
            continue
        area_a = code[1:5]
        if not area_a.strip() or area_a[0] == " ":
            continue
        m = RE_PARA_LINE.match(code[1:].strip())
        if m:
            nm = m.group(1).upper()
            if nm not in NOT_PARAGRAPHS and not nm.startswith("END-"):
                paras.append(nm)
    return paras


def strip_literals(text: str) -> str:
    """Blank out quoted literals, keeping length so offsets stay usable.

    Prose inside DISPLAY 'CALL TO XYZ FAILED' otherwise registers as a dynamic
    CALL to a program named TO.
    """
    return re.sub(r"'[^'\n]*'|\"[^\"\n]*\"",
                  lambda m: "'" + " " * max(0, len(m.group(0)) - 2) + "'", text)


def join_statements(src: str) -> list:
    """Collapse continuation lines into period-terminated statements.

    Required for constant resolution: a PIC clause and its VALUE routinely sit on
    different physical lines.
    """
    stmts, buf = [], []
    for line in src.splitlines():
        buf.append(line.strip())
        joined = " ".join(buf)
        while "." in joined:
            head, _, tail = joined.partition(".")
            if head.strip():
                stmts.append(" ".join(head.split()))
            joined = tail
        buf = [joined] if joined.strip() else []
    if " ".join(buf).strip():
        stmts.append(" ".join(" ".join(buf).split()))
    return stmts


def build_constants(stmts: list) -> dict:
    """name -> literal value, for figurative-constant resolution."""
    consts = {}
    for s in stmts:
        m = RE_CONST.match(s)
        if m:
            consts.setdefault(m.group(1).upper(), m.group(2).strip())
    return consts


def resolve(operand: str, consts: dict) -> str:
    """Resolve a CICS operand to its literal value where it is a known constant."""
    op = operand.strip().strip("'\"").upper()
    if op in consts and consts[op]:
        return consts[op].upper()
    return op


def _dedupe(seq):
    """Order-preserving dedupe -- keeps output stable across runs."""
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ---------------------------------------------------------------- CICS / data

CICS_FILE_OPS = {"READ": "R", "READNEXT": "R", "READPREV": "R", "STARTBR": "R",
                 "WRITE": "C", "REWRITE": "U", "DELETE": "D"}


def cics_file_access(src: str, consts: dict) -> list:
    """[(resolved_store, op)] for CICS file control. FILE and DATASET are synonyms."""
    hits = []
    for verb, op in CICS_FILE_OPS.items():
        for m in re.finditer(
                r"\bEXEC\s+CICS\s+%s\b([\s\S]{0,2500}?)\bEND-EXEC\b" % verb,
                src, re.I):
            # 2500, not 500: a READ with RIDFLD/KEYLENGTH(LENGTH OF)/INTO/LENGTH/
            # RESP/RESP2 over indented lines runs past 500 and the DATASET()
            # operand was never seen (CardDemo COACCT01 -> ACCTDAT missing).
            body = m.group(1)
            fm = re.search(r"\b(?:FILE|DATASET)\s*\(\s*'?([A-Z0-9\-_]+)",
                           body, re.I)
            if fm:
                hits.append((resolve(fm.group(1), consts), op))
    return hits


def cics_transfers(src: str, consts: dict) -> list:
    """[(verb, resolved_program)] for XCTL / LINK -- the online navigation graph."""
    out = []
    for verb in ("XCTL", "LINK"):
        for m in re.finditer(
                r"\bEXEC\s+CICS\s+%s\b([\s\S]{0,400}?)\bEND-EXEC\b" % verb,
                src, re.I):
            pm = re.search(r"\bPROGRAM\s*\(\s*'?([A-Z0-9\-_]+)", m.group(1), re.I)
            if pm:
                out.append((verb, resolve(pm.group(1), consts)))
    return out


def extract_data_access(src: str, selects: list, consts: dict) -> list:
    """Per-store CRUD footprint. Shared stores are the coupling signal that
    drives domain decomposition in Phase 3, so this feeds the CRUD matrix.

    Approximate by construction and deliberately so: COBOL WRITE names a record,
    not a file, and OPEN mode is often the only reliable intent signal. Over-
    reporting is the safe direction -- it makes two components look MORE coupled
    than they are, biasing Phase 3 toward keeping them together rather than
    toward an unsafe split.
    """
    acc = {}

    def note(store, kind, *ops):
        if not store:
            return
        e = acc.setdefault(store, {"store": store, "kind": kind, "ops": set()})
        e["ops"].update(ops)

    for s in selects:
        name = s["logical"]
        esc = re.escape(name)
        for mode, ops in (("INPUT", "R"), ("OUTPUT", "C"),
                          ("EXTEND", "C"), ("I\\-O", "RUD")):
            if re.search(r"\bOPEN\s+(?:\w+\s+)*%s\b[^.]{0,200}?\b%s\b"
                         % (mode, esc), src, re.I | re.S):
                note(name, "file", *ops)
        if re.search(r"\bREAD\s+%s\b" % esc, src, re.I):
            note(name, "file", "R")
        if re.search(r"\bREWRITE\b[^.]{0,120}?%s\b" % esc, src, re.I | re.S):
            note(name, "file", "U")
        if re.search(r"\bDELETE\s+%s\b" % esc, src, re.I):
            note(name, "file", "D")
        if re.search(r"\bWRITE\b[^.]{0,120}?%s\b" % esc, src, re.I | re.S):
            note(name, "file", "C")

    for store, op in cics_file_access(src, consts):
        note(store, "vsam", op)

    sql_ops = ((r"\bSELECT\b[\s\S]{0,600}?\bFROM\s+([A-Z][A-Z0-9_\.]*)", "R"),
               (r"\bINSERT\s+INTO\s+([A-Z][A-Z0-9_\.]*)", "C"),
               (r"\bUPDATE\s+([A-Z][A-Z0-9_\.]*)\s+SET", "U"),
               (r"\bDELETE\s+FROM\s+([A-Z][A-Z0-9_\.]*)", "D"))
    for m in re.finditer(r"\bEXEC\s+SQL\b([\s\S]*?)\bEND-EXEC\b", src, re.I):
        stmt = m.group(1)
        for rx, op in sql_ops:
            for t in re.finditer(rx, stmt, re.I):
                note(t.group(1).upper(), "db2", op)

    return sorted(
        [{"store": e["store"], "kind": e["kind"],
          "ops": "".join(sorted(e["ops"], key="CRUD".index))}
         for e in acc.values()],
        key=lambda x: x["store"])


# ---------------------------------------------------------------- analysers

def analyse_cobol(path: str) -> dict:
    raw = open(path, "r", encoding="utf-8", errors="replace").read()
    src = strip_fixed_form(raw)
    nolit = strip_literals(src)
    stmts = join_statements(src)
    consts = build_constants(stmts)

    pid = RE_PROGRAM_ID.search(src)
    name = (pid.group(1) if pid
            else os.path.splitext(os.path.basename(path))[0]).upper()

    static_calls = _dedupe(m.group(1).upper() for m in
                           re.finditer(r"\bCALL\s+['\"]([A-Z0-9\-_]+)['\"]",
                                       src, re.I))
    dynamic_calls = []
    for m in re.finditer(r"\bCALL\s+([A-Z][A-Z0-9\-_]*)", nolit, re.I):
        cand = m.group(1).upper()
        if cand in CALL_NOISE:
            continue
        dynamic_calls.append(resolve(cand, consts) if cand in consts else cand)
    dynamic_calls = _dedupe(dynamic_calls)

    transfers = cics_transfers(src, consts)
    # COPY X REPLACING ... / COPY X IN Y: filter clause keywords out of the
    # copybook name position.
    COPY_NOISE = {"REPLACING", "IN", "OF", "SUPPRESS", "PERFORM", "BY"}
    copies = _dedupe(m.group(1).upper() for m in RE_COPY.finditer(nolit)
                     if m.group(1).upper() not in COPY_NOISE)
    selects = [{"logical": m.group(1).upper(), "assign": m.group(2).upper()}
               for m in RE_SELECT.finditer(src)]

    has_cics = bool(RE_EXEC_CICS.search(src))
    has_sql = bool(RE_EXEC_SQL.search(src))
    paints_map = bool(RE_SEND_MAP.search(src))

    sql_tables = _dedupe(
        m.group(1).upper() for m in RE_SQL_TABLE.finditer(src)
        if not m.group(1).startswith(":")) if has_sql else []

    code_lines = [l for l in src.splitlines() if l.strip()]
    paragraphs = _dedupe(procedure_paragraphs(raw))
    # McCabe-style approximation; adequate for RANKING programs, not as a metric
    complexity = len(RE_DECISION.findall(nolit.upper())) + 1
    hazards = sorted(k for k, rx in HAZARDS.items() if rx.search(nolit))
    if dynamic_calls:
        hazards.append("dynamic CALL")

    if has_cics and paints_map:
        kind = "cics-online"
    elif has_cics:
        kind = "cics-utility"
    elif RE_PROC_USING.search(src) and not selects:
        kind = "subroutine"
    else:
        kind = "batch"

    return {
        "name": name, "path": path.replace("\\", "/"), "type": "cobol",
        "kind": kind, "lines": len(code_lines), "paragraphs": len(paragraphs),
        "complexity": complexity,
        "calls": _dedupe(static_calls + dynamic_calls),
        "static_calls": static_calls, "dynamic_calls": dynamic_calls,
        "cics_transfers": [{"verb": v, "program": p} for v, p in transfers],
        "copies": copies, "files": selects,
        "constants": consts,
        "data_access": extract_data_access(src, selects, consts),
        "cics": {"used": has_cics, "paints_map": paints_map,
                 "files": _dedupe(s for s, _ in cics_file_access(src, consts))},
        "db2": {"used": has_sql, "tables": sql_tables},
        # MQ and IMS are reached through CALL 'MQOPEN' / CALL 'CBLTDLI' -- the
        # module name lives INSIDE the literal, so these must be detected on the
        # original source, never on the literal-stripped copy.
        "mq": bool(RE_MQ.search(src)), "ims": bool(RE_IMS.search(src)),
        "hazards": sorted(set(hazards)),
    }


def analyse_jcl(path: str) -> dict:
    raw = open(path, "r", encoding="utf-8", errors="replace").read()
    lines = [l for l in raw.splitlines()
             if l.startswith("//") and not l.startswith("//*")]
    body = "\n".join(lines)
    steps = [{"step": m.group(1).upper(), "pgm": m.group(2).upper()}
             for m in re.finditer(
                 r"^//(\S+)\s+EXEC\s+(?:PGM=)?([A-Z0-9\-_#@$]+)",
                 body, re.I | re.M)]
    # The IMS region controller and DB2 TSO batch name the real program in
    # PARM= / SYSTSIN, not on the EXEC card. Without this, CardDemo reported
    # five scheduled programs (one of them a purge) as unreachable dead code.
    exec_re = re.compile(r"^//(\S+)\s+EXEC\s+(?:PGM=)?([A-Z0-9\-_#@$]+)", re.I | re.M)
    hits = list(exec_re.finditer(raw))
    for i, m in enumerate(hits):
        chunk = raw[m.start(): hits[i + 1].start() if i + 1 < len(hits) else len(raw)]
        util = m.group(2).upper()
        target = None
        if util == "DFSRRC00":
            pm = re.search(r"PARM=\(?'?\s*(?:BMP|DLI|DBB|ULU|MPP|IFP)\s*,\s*([A-Z0-9#@$]+)", chunk, re.I)
            target = pm.group(1).upper() if pm else None
        elif util in ("IKJEFT01", "IKJEFT1A", "IKJEFT1B"):
            pm = re.search(r"RUN\s+PROG(?:RAM)?\s*\(\s*([A-Z0-9#@$]+)\s*\)", chunk, re.I)
            target = pm.group(1).upper() if pm else None
        if target:
            for st in steps:
                if st["step"] == m.group(1).upper() and st["pgm"] == util:
                    st["utility"] = util
                    st["pgm"] = target
                    break
    dsns = _dedupe(m.group(1).upper()
                   for m in re.finditer(r"\bDSN=([A-Z0-9\.\-#@$]+)", body, re.I))
    # DD -> DSN per step, continuation-aware (DSN= is usually on the line after
    # "//ACCTFILE DD DISP=SHR,"). This is what lets depgraph resolve a batch
    # FD name and a CICS file name to the same physical dataset (SG-08).
    dd_dsn, step, dd, block = [], None, None, ""

    def flush():
        if dd:
            dm = re.search(r"\bDSN=([A-Z0-9\.\-#@$]+)", block, re.I)
            if dm:
                dd_dsn.append({"step": step, "dd": dd, "dsn": dm.group(1).upper()})
    for ln in raw.splitlines():
        if not ln.startswith("//") or ln.startswith("//*"):
            continue
        m = re.match(r"^//(\S+)\s+EXEC\b", ln, re.I)
        if m:
            flush(); dd, block = None, ""
            step = m.group(1).upper(); continue
        m = re.match(r"^//(\S+)\s+DD\b(.*)$", ln, re.I)
        if m:
            flush(); dd, block = m.group(1).upper(), m.group(2); continue
        if dd and re.match(r"^//\s", ln):
            block += " " + ln[2:]
    flush()
    return {"name": os.path.splitext(os.path.basename(path))[0].upper(),
            "path": path.replace("\\", "/"), "type": "jcl",
            "steps": steps, "datasets": dsns, "dd_dsn": dd_dsn, "lines": len(lines)}


def analyse_bms(path: str) -> dict:
    raw = open(path, "r", encoding="utf-8", errors="replace").read()
    return {
        "name": os.path.splitext(os.path.basename(path))[0].upper(),
        "path": path.replace("\\", "/"), "type": "bms",
        "mapsets": _dedupe(m.group(1).upper() for m in
                           re.finditer(r"^(\S+)\s+DFHMSD", raw, re.I | re.M)),
        "maps": _dedupe(m.group(1).upper() for m in
                        re.finditer(r"^(\S+)\s+DFHMDI", raw, re.I | re.M)),
        "field_count": len(re.findall(r"^(\S+)\s+DFHMDF", raw, re.I | re.M)),
    }


def analyse_csd(path: str) -> dict:
    """Extract TRANSACTION->PROGRAM bindings, the entry points of the online system.

    A CSD DEFINE spans several lines, so split into per-DEFINE blocks and search
    within each; a regex spanning newlines would pair one transaction with a
    later block's program.
    """
    raw = open(path, "r", encoding="utf-8", errors="replace").read()
    blocks = re.split(r"(?im)^\s*DEFINE\s+", raw)[1:]
    txns, progs, files = [], [], []
    for b in blocks:
        head = b.split("(", 1)[0].strip().upper()
        nm = re.match(r"\s*[A-Z]+\s*\(\s*([^)\s]+)", b, re.I)
        if not nm:
            continue
        name = nm.group(1).upper()
        if head == "TRANSACTION":
            pm = re.search(r"\bPROGRAM\s*\(\s*([^)\s]+)", b, re.I)
            txns.append({"txn": name,
                         "program": pm.group(1).upper() if pm else None})
        elif head == "PROGRAM":
            progs.append(name)
        elif head == "FILE":
            dm = re.search(r"\bDSNAME\s*\(\s*([^)\s]+)", b, re.I)
            files.append({"file": name,
                          "dsname": dm.group(1).upper() if dm else None})
    return {"name": os.path.basename(path), "path": path.replace("\\", "/"),
            "type": "csd", "transactions": txns, "programs": progs,
            "files": files}


# ---------------------------------------------------------------- walk

def walk(root: str):
    items = {"cobol": [], "copybook": [], "jcl": [], "bms": [], "ddl": [],
             "asm": [], "csd": [], "scheduler": []}
    errors = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in (".git", "node_modules", "target",
                                          ".venv", "__pycache__"))
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            try:
                if ext in COBOL_EXT:
                    items["cobol"].append(analyse_cobol(p))
                elif ext in COPY_EXT:
                    items["copybook"].append({
                        "name": os.path.splitext(fn)[0].upper(),
                        "path": p.replace("\\", "/"), "type": "copybook",
                        "lines": sum(1 for _ in open(p, errors="replace"))})
                elif ext in JCL_EXT:
                    items["jcl"].append(analyse_jcl(p))
                elif ext in BMS_EXT:
                    items["bms"].append(analyse_bms(p))
                elif ext in CSD_EXT:
                    items["csd"].append(analyse_csd(p))
                elif ext in DDL_EXT:
                    items["ddl"].append({"name": os.path.splitext(fn)[0].upper(),
                                         "path": p.replace("\\", "/"),
                                         "type": "ddl"})
                elif ext in SCHED_EXT:
                    items["scheduler"].append({
                        "name": os.path.splitext(fn)[0].upper(),
                        "path": p.replace("\\", "/"), "type": "scheduler",
                        "flavour": {".ca7": "ca7", ".controlm": "control-m",
                                    ".ctm": "control-m", ".tws": "tws",
                                    ".zeke": "zeke", ".opc": "opc"}[ext],
                        "lines": sum(1 for _ in open(p, errors="replace"))})
                elif ext in ASM_EXT:
                    items["asm"].append({"name": os.path.splitext(fn)[0].upper(),
                                         "path": p.replace("\\", "/"),
                                         "type": "asm"})
            except Exception as e:
                errors.append("%s: %s" % (p, e))
    return items, errors


def summarise(items: dict) -> dict:
    cob = items["cobol"]
    by_kind = {}
    for c in cob:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    return {
        "programs": len(cob),
        "program_kinds": dict(sorted(by_kind.items())),
        "cobol_lines": sum(c["lines"] for c in cob),
        "copybooks": len(items["copybook"]),
        "jcl_members": len(items["jcl"]),
        "bms_mapsets": sum(len(b["mapsets"]) for b in items["bms"]),
        "screens": sum(len(b["maps"]) for b in items["bms"]),
        "cics_transactions": sum(len(c["transactions"]) for c in items["csd"]),
        "distinct_data_stores": len({a["store"] for c in cob
                                     for a in c["data_access"]}),
        "db2_programs": sum(1 for c in cob if c["db2"]["used"]),
        "mq_programs": sum(1 for c in cob if c["mq"]),
        "ims_programs": sum(1 for c in cob if c["ims"]),
        "assembler_members": len(items["asm"]),
        "programs_with_hazards": sum(1 for c in cob if c["hazards"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--out", default="modernization/1-discovery/inventory.json")
    ap.add_argument("--csv", help="also write a flat per-program CSV")
    ap.add_argument("--print", dest="show", action="store_true")
    a = ap.parse_args()

    if not os.path.isdir(a.root):
        print("not a directory: %s" % a.root, file=sys.stderr)
        return 2

    items, errors = walk(a.root)
    summary = summarise(items)
    doc = {"root": a.root.replace("\\", "/"), "summary": summary,
           "items": items, "errors": errors}

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(doc, open(a.out, "w", encoding="utf-8"), indent=2)

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["program", "kind", "lines", "paragraphs", "complexity",
                        "calls", "copybooks", "stores", "db2", "mq", "ims",
                        "hazards"])
            for c in items["cobol"]:
                w.writerow([c["name"], c["kind"], c["lines"], c["paragraphs"],
                            c["complexity"], len(c["calls"]), len(c["copies"]),
                            len(c["data_access"]),
                            "Y" if c["db2"]["used"] else "",
                            "Y" if c["mq"] else "", "Y" if c["ims"] else "",
                            "; ".join(c["hazards"])])

    print("inventory -> %s" % a.out)
    for k, v in summary.items():
        print("  %-24s %s" % (k, v))
    if errors:
        print("\n  %d file(s) could not be parsed:" % len(errors),
              file=sys.stderr)
        for e in errors[:10]:
            print("    %s" % e, file=sys.stderr)

    if a.show:
        print("\n  %-10s %-13s %6s %5s %5s %6s  %s"
              % ("PROGRAM", "KIND", "LINES", "PARA", "CPLX", "STORES",
                 "HAZARDS"))
        for c in sorted(items["cobol"], key=lambda x: -x["complexity"]):
            print("  %-10s %-13s %6d %5d %5d %6d  %s"
                  % (c["name"], c["kind"], c["lines"], c["paragraphs"],
                     c["complexity"], len(c["data_access"]),
                     "; ".join(c["hazards"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
