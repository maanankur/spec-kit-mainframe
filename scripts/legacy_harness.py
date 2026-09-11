#!/usr/bin/env python3
"""
legacy_harness.py -- run the legacy batch chain under GnuCOBOL (Docker) and capture
every output as the golden master for the equivalence comparison.

Data-driven: target/legacy/harness.json names the compiler image, the indexed files
to build from sample data (record length, key, alternate key), the sequential
inputs, the stub programs that stand in for assembler/LE services, and the jobs in
JCL order with their DD -> file mapping, PARM, host SORT emulation and the unloads to
take before/after. `--propose` writes a first harness.json from inventory.json,
dependencies.json and 5-data/store-map.json; the validation agent completes it
(stubs, PARM values, SORT keys) and then runs it.

Legacy-execution tooling only. Nothing here is target architecture; the Java side
never reads any of it except the *outputs* in target/legacy/out/.

Usage: legacy_harness.py --workspace W --propose
       legacy_harness.py --workspace W [--config target/legacy/harness.json] [--skip-compile]
"""
import argparse, io, json, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import WS, NOW, read, write, jload, jdump
from store_map import common_dsn_prefix, dsn_token, is_fd_style

SKIP_DD = {"STEPLIB", "SYSPRINT", "SYSOUT", "SYSIN", "SYSUDUMP", "SYSABEND", "SYSDBOUT", "CEEDUMP", "SYSTSIN", "SYSTSPRT", "SYSMDUMP", "JOBLIB", "SORTWK01", "SORTWK02", "SORTWK03"}


def loader(name, reclen, klen, alt, unload=False):
    if alt:
        aoff, alen = alt
        rec = "           05 %s-KEY   PIC X(%d).\n           05 FILLER    PIC X(%d).\n           05 %s-ALT   PIC X(%d).\n           05 FILLER    PIC X(%d).\n" % ("IN" if unload else "OUT", klen, aoff - klen, "IN" if unload else "OUT", alen, reclen - aoff - alen)
    else: rec = "           05 %s-KEY   PIC X(%d).\n           05 FILLER    PIC X(%d).\n" % ("IN" if unload else "OUT", klen, reclen - klen)
    p = "IN" if unload else "OUT"; altsel = ("               ALTERNATE RECORD KEY IS %s-ALT\n" % p) if alt else ""
    if not unload:
        return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOAD{name}.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE
               ORGANIZATION IS LINE SEQUENTIAL FILE STATUS IS IN-ST.
           SELECT OUT-FILE ASSIGN TO OUTIDX
               ORGANIZATION IS INDEXED ACCESS MODE IS RANDOM
               RECORD KEY IS OUT-KEY
{altsel}               FILE STATUS IS OUT-ST.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X({reclen}).
       FD  OUT-FILE.
       01  OUT-REC.
{rec}       WORKING-STORAGE SECTION.
       01  IN-ST  PIC XX.
       01  OUT-ST PIC XX.
       01  WS-EOF PIC X VALUE 'N'.
       01  CNT    PIC 9(7) VALUE 0.
       01  ERRS   PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE
           OPEN OUTPUT OUT-FILE
           IF OUT-ST NOT = '00'
               DISPLAY 'OPEN OUT ' OUT-ST
               STOP RUN
           END-IF
           PERFORM UNTIL WS-EOF = 'Y'
               READ IN-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       MOVE IN-REC TO OUT-REC
                       WRITE OUT-REC
                           INVALID KEY ADD 1 TO ERRS
                               DISPLAY 'WRITE ' OUT-ST ' KEY=' OUT-KEY
                       END-WRITE
                       ADD 1 TO CNT
               END-READ
           END-PERFORM
           CLOSE IN-FILE OUT-FILE
           DISPLAY 'LOAD{name} records=' CNT ' errors=' ERRS
           STOP RUN.
"""
    return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNLD{name}.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INIDX
               ORGANIZATION IS INDEXED ACCESS MODE IS SEQUENTIAL
               RECORD KEY IS IN-KEY
{altsel}               FILE STATUS IS IN-ST.
           SELECT OUT-FILE ASSIGN TO OUTFILE
               ORGANIZATION IS LINE SEQUENTIAL FILE STATUS IS OUT-ST.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
{rec}       FD  OUT-FILE.
       01  OUT-REC PIC X({reclen}).
       WORKING-STORAGE SECTION.
       01  IN-ST  PIC XX.
       01  OUT-ST PIC XX.
       01  WS-EOF PIC X VALUE 'N'.
       01  CNT    PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE
           IF IN-ST NOT = '00'
               DISPLAY 'OPEN IN ' IN-ST
               STOP RUN
           END-IF
           OPEN OUTPUT OUT-FILE
           IF OUT-ST NOT = '00'
               DISPLAY 'OPEN OUT ' OUT-ST
               STOP RUN
           END-IF
           PERFORM UNTIL WS-EOF = 'Y'
               READ IN-FILE NEXT
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       MOVE IN-REC TO OUT-REC
                       WRITE OUT-REC
                       ADD 1 TO CNT
               END-READ
           END-PERFORM
           CLOSE IN-FILE OUT-FILE
           DISPLAY 'UNLD{name} records=' CNT
           STOP RUN.
"""


def driver(pgm, parmlen):
    return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. RUN{pgm[:5]}.
      * JCL PARM= driver: passes the command line as the LINKAGE parm
      * (halfword length + data), the way the JCL EXEC PARM= does.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CMD PIC X(200).
       01  EXTERNAL-PARMS.
           05  PARM-LENGTH PIC S9(04) COMP.
           05  PARM-DATA   PIC X({parmlen}).
       PROCEDURE DIVISION.
           ACCEPT CMD FROM COMMAND-LINE
           MOVE {parmlen} TO PARM-LENGTH
           MOVE CMD(1:{parmlen}) TO PARM-DATA
           CALL '{pgm}' USING EXTERNAL-PARMS
           STOP RUN.
"""


def propose(ws):
    inv = jload(os.path.join(ws.DISC, "inventory.json")); dep = jload(os.path.join(ws.DISC, "dependencies.json")); sm = jload(os.path.join(ws.D5, "store-map.json"), {"stores": []})
    progs = {c["name"]: c for c in inv["items"]["cobol"]}; by_dsn = {}
    for e in sm["stores"]:
        if e.get("dsn"): by_dsn[e["dsn"]] = e
    prefix = common_dsn_prefix([d for j in inv["items"]["jcl"] for d in j.get("datasets", [])])
    for e in sm["stores"]:
        for al in e.get("aliases", []): by_dsn.setdefault(dep.get("store_identity", {}).get(al, {}).get("dsn") or "", e)
    for n, s in list(dep.get("stores", {}).items()) + [(n, dict(dsn=v.get("dsn"))) for n, v in dep.get("store_identity", {}).items()]:
        if s.get("dsn") and s["dsn"] not in by_dsn:
            canon = dep.get("store_identity", {}).get(n, {}).get("resolved_to") or n
            by_dsn[s["dsn"]] = dict(store=canon if not is_fd_style(canon) else dsn_token(s["dsn"], prefix), kind="sequential")
    indexed = {}
    for e in sm["stores"]:
        if str(e.get("kind", "")).startswith("vsam") and e.get("record_length") and e.get("key"):
            indexed[e["store"]] = dict(record=e["record_length"], key=[e["key"][1], e["key"][0]], alt=None, load_from=e.get("ascii_sample"), note="key = [offset, length]; load_from must be an ASCII fixed-width image (one record per line)")
            for i, x in enumerate(e.get("alternate_indexes", [])):
                if x.get("key"): indexed[e["store"] + "A" * (i + 1)] = dict(record=e["record_length"], key=[e["key"][1], e["key"][0]], alt=[x["key"][1], x["key"][0]], load_from=e.get("ascii_sample"), note="variant with the alternate key for programs that read via the AIX path")
    cpy = sorted({os.path.dirname(c["path"]) for c in inv["items"]["copybook"]}); root = ws.source.replace("\\", "/")
    jobs, stubs, sorts = [], set(), []
    for j in inv["items"]["jcl"]:
        txt = read(j["path"])
        for st in j.get("steps", []):
            pgm = st["pgm"]
            if pgm in ("SORT", "ICEMAN", "DFSORT", "SYNCSORT"): sorts.append(dict(jcl=j["name"], step=st["step"], sysin=re.findall(r"(?:SORT|INCLUDE|OMIT|INREC|OUTREC)\s+[^\n]+", txt)[:6])); continue
            if pgm not in progs or progs[pgm]["kind"] != "batch": continue
            dds = {}
            for d in j.get("dd_dsn", []):
                if d["step"] != st["step"] or d["dd"] in SKIP_DD: continue
                e = by_dsn.get(d["dsn"]); store = e["store"] if e else dsn_token(d["dsn"], prefix)
                dds[d["dd"]] = ("idx/%s" % store) if e and str(e.get("kind", "")).startswith("vsam") else "data/%s.dat" % store
            parm = re.search(r"EXEC\s+PGM=%s\s*,\s*PARM=['\"]?([^'\",\n]+)" % re.escape(pgm), txt)
            uses_parm = bool(re.search(r"PROCEDURE\s+DIVISION\s+USING", read(progs[pgm]["path"]), re.I))
            needs = [k for k, v in (("db2", progs[pgm].get("db2", {}).get("used")), ("ims", progs[pgm].get("ims")), ("mq", progs[pgm].get("mq"))) if v]
            jobs.append(dict(name=j["name"], step=st["step"], program=pgm, runnable_offline=not needs, requires=needs, dds=dds, parm=(parm.group(1).strip() if parm else ("<REQUIRED: program has PROCEDURE DIVISION USING>" if uses_parm else None)),
                             delete_before=[p for dd, p in dds.items() if p.startswith("idx/") and progs[pgm]["data_access"] and any(x["store"] in (dd,) or "C" in x["ops"] for x in progs[pgm]["data_access"]) and False],
                             pre_unload=[], post_unload=[[p[4:], "post/%s.txt" % p[4:]] for p in dds.values() if p.startswith("idx/")], copy_out=[[p[5:], "post/%s" % p[5:]] for p in dds.values() if p.startswith("data/")],
                             fixed_to_lines=[], host_sort=None, note="review DDs against the JCL; add fixed_to_lines for report outputs (name, width, out) and host_sort for a preceding SORT step"))
            for c in progs[pgm].get("calls", []):
                if c not in progs: stubs.add(c)
    seq_inputs = [dict(name="%s.dat" % e["store"], **{"from": e.get("ascii_sample") or "<ASCII image of %s>" % e["store"]}, width=e.get("record_length") or "<record length>") for e in sm["stores"] if e.get("kind") == "sequential" and any(("R" in x["ops"] and x["store"] and dep.get("store_identity", {}).get(x["store"], {}).get("resolved_to") == e["store"]) for p in progs.values() for x in p["data_access"])]
    cfg = dict(_readme=["Proposed %s by legacy_harness.py --propose. Complete every <...> placeholder, write the stubs, confirm DDs and unloads, then run legacy_harness.py." % NOW,
                        "Paths are relative to target/legacy/ (work/ is created there). idx/<STORE> are GnuCOBOL indexed files built by generated LOAD programs; data/*.dat are fixed-width sequential inputs.",
                        "stubs: COBOL stand-ins for CALLed modules that are not in the repository (assembler, LE services). Behaviour per the specification rule; say which in the stub's comment."],
               image="legacy/gnucobol:3", dockerfile="../ops/Dockerfile.gnucobol", source=root, copybook_dirs=[os.path.relpath(c, root).replace("\\", "/") for c in cpy], cobc_flags="-std=ibm -fsign=EBCDIC", cobc_env={"COB_LS_FIXED": "1", "COB_LS_NULLS": "0"},
               indexed=indexed, sequential_inputs=seq_inputs, literal_inputs=[dict(name="<PARMFILE>.dat", text="<content>", width=80)], stubs=["stubs/%s.cbl" % s for s in sorted(stubs)], sort_steps_found=sorts, jobs=jobs)
    p = os.path.join(ws.T, "legacy", "harness.json"); jdump(p, cfg)
    print("proposed %s: %d indexed variants, %d jobs, %d stubs to write (%s), %d SORT steps to emulate" % (ws.rel(p), len(indexed), len(jobs), len(stubs), ", ".join(sorted(stubs)) or "-", len(sorts)))
    return 0


def run(ws, cfg_path, skip_compile):
    C = jload(cfg_path); H = os.path.dirname(os.path.abspath(cfg_path)); WORK = os.path.join(H, "work"); OUT = os.path.join(H, "out"); SRC = C["source"]
    for d in ("src", "data", "idx", "bin", "pre", "post"): os.makedirs(os.path.join(WORK, d), exist_ok=True)
    for d in ("pre", "post", "sysout"): os.makedirs(os.path.join(OUT, d), exist_ok=True)
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    produced = set(); problems = []
    for j in C["jobs"]:
        for dd, p in j["dds"].items():
            if p.startswith("idx/"):
                n = p[4:]
                if n not in C["indexed"]: problems.append("%s DD %s -> %s: not in `indexed`" % (j["name"], dd, p))
                elif not C["indexed"][n].get("load_from") and n not in produced and p not in j.get("delete_before", []): problems.append("%s DD %s -> %s: indexed file has no load_from and no earlier job produces it (add load_from, or delete_before if the job creates it)" % (j["name"], dd, p))
                produced.add(n)
        for n, t in j.get("pre_unload", []) + j.get("post_unload", []):
            if n not in C["indexed"]: problems.append("%s unload %s: not in `indexed`" % (j["name"], n))
        if j.get("parm") and str(j["parm"]).startswith("<"): problems.append("%s: PARM placeholder not filled" % j["name"])
    for st in C.get("stubs", []):
        if not os.path.exists(os.path.join(H, st)): problems.append("stub %s missing" % st)
    for n, ix in C["indexed"].items():
        if ix.get("load_from") and not os.path.exists(os.path.join(SRC, ix["load_from"])): problems.append("indexed %s: load_from %s not found under source" % (n, ix["load_from"]))
    if problems:
        print("HARNESS CONFIG INCOMPLETE:"); [print("  -", p) for p in problems]; return 2
    for j in C["jobs"]:
        for p in list(j["dds"].values()) + [t for _, t in j.get("pre_unload", []) + j.get("post_unload", [])] + [d for _, d in j.get("copy_out", [])] + [o for _, _, o in j.get("fixed_to_lines", [])] + ([j["host_sort"]["output"]] if j.get("host_sort") else []):
            os.makedirs(os.path.dirname(os.path.join(WORK, p)) or WORK, exist_ok=True); os.makedirs(os.path.dirname(os.path.join(OUT, p)) or OUT, exist_ok=True)
    def docker(cmd, envs=None, check=True):
        e = " ".join("-e %s=%s" % kv for kv in (envs or {}).items()) + " " + " ".join("-e %s=%s" % kv for kv in C.get("cobc_env", {}).items())
        # --entrypoint sh: independent of whatever ENTRYPOINT the compiler image declares
        full = 'docker run --rm --entrypoint sh %s -v "%s:/src:ro" -v "%s:/work" -w /work %s -c "%s"' % (e, SRC, WORK.replace("\\", "/"), C["image"], cmd.replace('"', '\\"'))
        r = subprocess.run(full, shell=True, capture_output=True, text=True, env=env)
        if check and r.returncode not in (0, 4): print("STEP FAILED rc=%d\n%s\n%s" % (r.returncode, r.stdout[-2000:], r.stderr[-2000:])); sys.exit(1)
        return r
    if subprocess.run("docker image inspect %s" % C["image"], shell=True, capture_output=True, env=env).returncode != 0:
        df = os.path.join(H, C.get("dockerfile", "")); print("building %s from %s" % (C["image"], df))
        subprocess.run('docker build -t %s -f "%s" "%s"' % (C["image"], df, os.path.dirname(df)), shell=True, check=True, env=env)
    # prepare inputs
    for n, ix in C["indexed"].items():
        write(os.path.join(WORK, "src", "LOAD%s.cbl" % n), loader(n, ix["record"], ix["key"][1], (ix["alt"][0], ix["alt"][1]) if ix.get("alt") else None))
        write(os.path.join(WORK, "src", "UNLD%s.cbl" % n), loader(n, ix["record"], ix["key"][1], (ix["alt"][0], ix["alt"][1]) if ix.get("alt") else None, unload=True))
        if ix.get("load_from"): shutil.copyfile(os.path.join(SRC, ix["load_from"]), os.path.join(WORK, "data", "%s.txt" % n))
    for s in C.get("sequential_inputs", []):
        rows = [l.rstrip("\r\n").ljust(s["width"])[:s["width"]] for l in io.open(os.path.join(SRC, s["from"]), encoding="latin-1")]
        io.open(os.path.join(WORK, "data", s["name"]), "wb").write("".join(rows).encode("latin-1"))
    for s in C.get("literal_inputs", []): io.open(os.path.join(WORK, "data", s["name"]), "wb").write(s["text"].ljust(s["width"]).encode("latin-1"))
    for s in C.get("stubs", []): shutil.copyfile(os.path.join(H, s), os.path.join(WORK, "src", os.path.basename(s)))
    stubs = " ".join("src/" + os.path.basename(s) for s in C.get("stubs", [])); inc = " ".join("-I /src/%s" % d for d in C["copybook_dirs"]); cobc = "cobc -x %s %s -ext cpy -ext CPY" % (C["cobc_flags"], inc)
    progs = {}
    for j in C["jobs"]:
        p = j["program"]; src = j.get("source") or next((os.path.relpath(c["path"], SRC).replace("\\", "/") for c in jload(os.path.join(ws.DISC, "inventory.json"))["items"]["cobol"] if c["name"] == p), None)
        progs.setdefault(p, dict(source=src, parm=j.get("parm")))
    if not skip_compile:
        steps = ["cd /work && set -e"] + ["cobc -x -o bin/%s%s src/%s%s.cbl" % (k, n, k, n) for n in C["indexed"] for k in ("LOAD", "UNLD")]
        for p, meta in progs.items():
            if meta["parm"]:
                write(os.path.join(WORK, "src", "RUN%s.cbl" % p[:5]), driver(p, len(meta["parm"]))); steps.append("%s -o bin/RUN%s src/RUN%s.cbl /src/%s %s" % (cobc, p[:5], p[:5], meta["source"], stubs))
            else: steps.append("%s -o bin/%s /src/%s %s" % (cobc, p, meta["source"], stubs))
        steps.append("echo COMPILED"); r = docker(" && ".join(steps))
        if "COMPILED" not in r.stdout: print("COMPILE DID NOT FINISH\n%s\n%s" % (r.stdout[-2000:], r.stderr[-2000:])); sys.exit(1)
        print("compiled %d program(s), %d loader/unloader pairs, %d stub(s)" % (len(progs), len(C["indexed"]), len(C.get("stubs", []))))
        for n, ix in C["indexed"].items():
            if ix.get("load_from"):
                r = docker("bin/LOAD%s" % n, {"DD_INFILE": "/work/data/%s.txt" % n, "DD_OUTIDX": "/work/idx/%s" % n}); print("  ", r.stdout.strip())
                if "OPEN OUT" in r.stdout or "errors=0" not in r.stdout: print("LOAD FAILED for %s" % n); sys.exit(1)
    def unload(n, target):
        r = docker("bin/UNLD%s" % n, {"DD_INIDX": "/work/idx/%s" % n, "DD_OUTFILE": "/work/%s" % target})
        if "OPEN IN" in r.stdout or "OPEN OUT" in r.stdout or not os.path.exists(os.path.join(WORK, target)): print("UNLOAD FAILED %s -> %s: %s %s" % (n, target, r.stdout.strip()[-300:], r.stderr.strip()[-300:])); sys.exit(1)
        os.makedirs(os.path.dirname(os.path.join(OUT, target)), exist_ok=True); shutil.copyfile(os.path.join(WORK, target), os.path.join(OUT, target))
    rcs = {}
    for j in C["jobs"]:
        for p in j.get("delete_before", []):
            if os.path.exists(os.path.join(WORK, p)): os.remove(os.path.join(WORK, p))
        for n, t in j.get("pre_unload", []): unload(n, t)
        hs = j.get("host_sort")
        if hs:   # SORT step emulation: fixed-width records, one key, optional inclusive range filter on a field
            rows = [l.rstrip("\r\n").ljust(hs["width"])[:hs["width"]] for l in io.open(os.path.join(OUT if hs["input"].startswith(("pre/", "post/")) else WORK, hs["input"]), encoding="latin-1") if l.strip()]
            inc_ = hs.get("include")
            if inc_: lo, hi = inc_["between"]; rows = [r for r in rows if lo <= r[inc_["field"][0]:inc_["field"][0] + inc_["field"][1]] <= hi]
            rows.sort(key=lambda r: r[hs["key"][0]:hs["key"][0] + hs["key"][1]]); io.open(os.path.join(WORK, hs["output"]), "wb").write("".join(rows).encode("latin-1")); print("  SORT emulation: %d records -> %s" % (len(rows), hs["output"]))
        binary = ("RUN%s" % j["program"][:5]) if j.get("parm") else j["program"]; dds = {"DD_%s" % dd: "/work/%s" % p for dd, p in j["dds"].items()}
        r = docker("bin/%s %s; echo RC=$?" % (binary, j.get("parm") or ""), dds, check=False)
        write(os.path.join(OUT, "sysout", "%s.sysout.txt" % j["name"]), r.stdout + ("\n--- stderr ---\n" + r.stderr if r.stderr.strip() else ""))
        m = re.search(r"RC=(\d+)", r.stdout); rcs[j["name"]] = int(m.group(1)) if m else -1; print("  %-9s %-8s rc=%s  (%d sysout lines)" % (j["name"], j["program"], rcs[j["name"]], len(r.stdout.splitlines())))
        for n, t in j.get("post_unload", []): unload(n, t)
        for src_, dst in j.get("copy_out", []):
            if os.path.exists(os.path.join(WORK, src_)): os.makedirs(os.path.dirname(os.path.join(OUT, dst)), exist_ok=True); shutil.copyfile(os.path.join(WORK, src_), os.path.join(OUT, dst))
        for name, width, out in j.get("fixed_to_lines", []):
            if os.path.exists(os.path.join(WORK, name)):
                b = io.open(os.path.join(WORK, name), "rb").read().decode("latin-1"); write(os.path.join(OUT, out), "\n".join(b[i:i + width].rstrip() for i in range(0, len(b), width)) + "\n")
    jdump(os.path.join(OUT, "manifest.json"), dict(run_at=NOW, compiler=C["image"], return_codes=rcs, jobs=[dict(name=j["name"], program=j["program"], parm=j.get("parm")) for j in C["jobs"]], stubs=C.get("stubs", []),
                                                    notes=["SORT steps emulated on the host where host_sort is configured", "online (CICS/IMS-DC) programs are not executed: no transaction monitor -- their behaviour is verified via the specification rules and API tests"]))
    print("return codes:", rcs); return 0 if all(v in (0, 4) for v in rcs.values()) else 1


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--propose", action="store_true"); ap.add_argument("--config"); ap.add_argument("--skip-compile", action="store_true"); a = ap.parse_args(); ws = WS(a.workspace)
    if a.propose: return propose(ws)
    return run(ws, a.config or os.path.join(ws.T, "legacy", "harness.json"), a.skip_compile)


if __name__ == "__main__":
    sys.exit(main())
