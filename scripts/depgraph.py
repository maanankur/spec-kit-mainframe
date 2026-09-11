#!/usr/bin/env python3
"""
depgraph.py -- dependency graph, CRUD matrix, reachability and domain clusters.

Consumes inventory.json (never re-parses source, so the two cannot disagree) and
answers the four Phase-1/Phase-3 questions that decide the whole programme:

  1. What calls what?              -> conversion ordering
  2. Who touches which data store? -> the CRUD matrix
  3. What is unreachable?          -> dead code you must not pay to convert
  4. What clusters together?       -> candidate domains, via SHARED DATA STORES

(4) is the important one. Domains are discovered from data coupling, not from
program-name prefixes or JCL job names. Two programs that write the same store
belong in the same transactional boundary until proven otherwise; splitting them
across services is how a distributed monolith gets built.

Usage:
  depgraph.py [--inventory modernization/1-discovery/inventory.json]
              [--out-dir modernization/1-discovery] [--print]
              [--mermaid FILE]

Writes dependencies.json, crud-matrix.csv, and optionally a Mermaid diagram.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

CRUD_ORDER = "CRUD"


def build(inv: dict) -> dict:
    programs = {p["name"]: p for p in inv["items"]["cobol"]}
    jcls = inv["items"]["jcl"]
    csds = inv["items"]["csd"]
    copybooks = {c["name"] for c in inv["items"]["copybook"]}

    # ---------------------------------------------------------------- edges
    calls, missing_calls = [], []
    for name, p in programs.items():
        for target in p["calls"]:
            if target in programs:
                calls.append({"from": name, "to": target, "via": "CALL"})
            elif target in {a["name"] for a in inv["items"]["asm"]}:
                calls.append({"from": name, "to": target, "via": "CALL-ASM"})
            else:
                missing_calls.append({"from": name, "to": target})

    # CICS XCTL / LINK are control transfers too. In a pseudo-conversational
    # app the entire screen-to-screen navigation lives here, so dropping these
    # edges would hide the application's real structure.
    for name, p in programs.items():
        for t in p.get("cics_transfers", []):
            target = t["program"]
            if target in programs:
                calls.append({"from": name, "to": target,
                              "via": "CICS-" + t["verb"]})
            elif target:
                missing_calls.append({"from": name, "to": target})

    # DFHAID / DFHBMSCA / CMQ* are IBM-supplied copybooks that live in system
    # libraries, not in the application repo. Reporting them as "missing" buries
    # the copybooks that are genuinely absent -- and those are a hard blocker,
    # because a missing copybook means an unknown record layout.
    VENDOR_CB = ("DFH", "CMQ", "CEE", "IGZ", "SQLCA", "SQLDA")
    copies, missing_copies, vendor_copies = [], [], set()
    for name, p in programs.items():
        for cb in p["copies"]:
            if cb in copybooks:
                copies.append({"from": name, "to": cb})
            elif cb.startswith(VENDOR_CB):
                vendor_copies.add(cb)
            else:
                missing_copies.append({"from": name, "to": cb})

    # ---------------------------------------------------------------- entry points
    entry = {}
    for c in csds:
        for t in c["transactions"]:
            if t["program"]:
                entry.setdefault(t["program"], []).append(
                    {"kind": "cics-transaction", "id": t["txn"]})
    jcl_steps = []
    for j in jcls:
        for s in j["steps"]:
            jcl_steps.append({"job": j["name"], "step": s["step"],
                              "pgm": s["pgm"]})
            if s["pgm"] in programs:
                entry.setdefault(s["pgm"], []).append(
                    {"kind": "jcl-step", "id": "%s/%s" % (j["name"], s["step"])})

    # ---------------------------------------------------------------- reachability
    adj = {}
    for e in calls:
        if e["to"] != "?":
            adj.setdefault(e["from"], set()).add(e["to"])
    reachable, stack = set(entry), list(entry)
    while stack:
        n = stack.pop()
        for m in adj.get(n, ()):
            if m not in reachable:
                reachable.add(m)
                stack.append(m)
    unreachable = sorted(set(programs) - reachable)

    # ---------------------------------------------------------------- CRUD matrix
    stores = {}
    # ---------------------------------------------------------- store identity
    # A batch program names a dataset by its FD (ACCOUNT-FILE); an online
    # program names the same dataset by its CICS file (ACCTDAT). Left apart,
    # one dataset becomes two "stores" and the online and batch halves of a
    # domain land in different clusters (CardDemo: 53 stores for ~30 datasets,
    # SG-08). Resolve every name to a DSN -- FD -> ASSIGN -> JCL DD -> DSN, and
    # CICS file -> CSD DSNAME -- and merge names that meet at the same dataset.
    csd_dsn = {}
    for c in csds:
        for f in c.get("files", []):
            if f.get("dsname"):
                csd_dsn[f["file"]] = f["dsname"]
    step_dd = {}
    for j in jcls:
        for s in j["steps"]:
            for e in j.get("dd_dsn", []):
                if e["step"] == s["step"]:
                    step_dd.setdefault(s["pgm"], {}).setdefault(e["dd"], e["dsn"])
    # a CALLed subroutine opens files under the DD names of the step that runs
    # its caller (CardDemo: CBSTM03B does the I/O for CBSTM03A) -- inherit
    for e in calls:
        if e["via"] == "CALL" and e["to"] not in step_dd and e["from"] in step_dd:
            step_dd[e["to"]] = dict(step_dd[e["from"]])

    def strip_gdg(d):
        return d.split("(")[0]

    def dsn_for(prog, a):
        if a["kind"] == "db2":
            return "DB2:" + a["store"]
        if a["kind"] == "vsam":
            return csd_dsn.get(a["store"])
        if a["kind"] == "file":
            assign = next((f["assign"] for f in programs[prog].get("files", [])
                           if f["logical"] == a["store"]), None)
            if assign:
                d = step_dd.get(prog, {}).get(assign)
                return strip_gdg(d) if d else None
        return None

    # alternate-index PATH datasets resolve to their base cluster
    known = set(csd_dsn.values())
    def base_of(d):
        if d and ".AIX" in d:
            pre = d.split(".AIX")[0]
            cands = [k for k in known if k.startswith(pre) and ".AIX" not in k]
            if cands:
                return sorted(cands, key=len)[0]
        return d

    dsn_to_key = {}
    # CICS names win as display keys; the base cluster's name beats its
    # alternate-index path name (CARDDAT, not CARDAIX)
    for f, d in sorted(csd_dsn.items(), key=lambda kv: (".AIX" in kv[1], kv[0])):
        dsn_to_key.setdefault(base_of(d), f)
    identity = {}
    for name, p in programs.items():
        for a in p.get("data_access", []):
            d = base_of(dsn_for(name, a))
            key = dsn_to_key.setdefault(d, a["store"]) if d else a["store"]
            if d and identity.get(a["store"], {}).get("via") == "unresolved":
                del identity[a["store"]]      # a resolved sighting beats an unresolved one
            identity.setdefault(a["store"], {"resolved_to": key, "dsn": d,
                                             "via": ({"vsam": "csd", "db2": "db2"}.get(a["kind"], "jcl")) if d else "unresolved"})
            s = stores.setdefault(key, {"store": key, "kind": a["kind"],
                                        "dsn": d, "aliases": set(), "programs": {}})
            if a["store"] != key:
                s["aliases"].add(a["store"])
            if a["kind"] == "vsam":
                s["kind"] = "vsam"
            prev = s["programs"].get(name, "")
            s["programs"][name] = "".join(ch for ch in CRUD_ORDER if ch in prev + a["ops"])
    for s in stores.values():
        s["aliases"] = sorted(s["aliases"])

    # ---------------------------------------------------------------- clustering
    # Union-find over programs, joined when they share a store that at least one
    # of them WRITES. Read-only sharing is a much weaker signal -- a read-only
    # reference table can safely be replicated or exposed as a query API, so
    # joining on it would collapse everything into one blob.
    parent = {n: n for n in programs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for s in stores.values():
        writers = [n for n, ops in s["programs"].items()
                   if set(ops) & {"C", "U", "D"}]
        if not writers:
            continue
        members = list(s["programs"])
        for m in members[1:]:
            union(members[0], m)
    # control-flow coupling also binds
    for e in calls:
        if e["to"] in parent and e["from"] in parent:
            union(e["from"], e["to"])

    clusters = {}
    for n in programs:
        clusters.setdefault(find(n), []).append(n)
    cluster_list = []
    for i, (root, members) in enumerate(
            sorted(clusters.items(), key=lambda kv: (-len(kv[1]), kv[0])), 1):
        members = sorted(members)
        cl_stores = sorted({identity[a["store"]]["resolved_to"] for m in members
                            for a in programs[m].get("data_access", [])})
        owned = sorted({s for s in cl_stores
                        if all(m in members for m in stores[s]["programs"])})
        cluster_list.append({
            "id": "C%02d" % i,
            "programs": members,
            "program_count": len(members),
            "lines": sum(programs[m]["lines"] for m in members),
            "complexity": sum(programs[m]["complexity"] for m in members),
            "stores": cl_stores,
            "exclusively_owned_stores": owned,
            "shared_stores": sorted(set(cl_stores) - set(owned)),
            "screens": sorted({m for m in members
                               if programs[m]["kind"] == "cics-online"}),
            "entry_points": sorted({e["id"] for m in members
                                    for e in entry.get(m, [])}),
        })

    # Not all unresolved targets mean the same thing, and conflating them hides
    # the one that matters. A name that is a DATA ITEM in the caller is dynamic
    # dispatch: the screen flow is decided at runtime through the COMMAREA, so it
    # cannot be recovered statically and must be read out of the menu/option
    # tables instead. Phase 2 has to do that explicitly or the navigation model
    # will be wrong.
    external = ("CBLTDLI", "AIBTDLI", "CEE", "MQ", "DFH", "IGZ", "ILBO", "SORT")
    dynamic, ext, truly_missing = {}, set(), set()
    for m in missing_calls:
        tgt, src_pgm = m["to"], m["from"]
        if tgt in programs.get(src_pgm, {}).get("constants", {}):
            truly_missing.add(tgt)
        elif any(tgt.startswith(p) for p in external):
            ext.add(tgt)
        elif "-" in tgt:  # COBOL data-name shape: dispatch through a variable
            dynamic.setdefault(tgt, []).append(src_pgm)
        else:
            truly_missing.add(tgt)

    return {
        "calls": calls,
        "unresolved_calls": sorted({m["to"] for m in missing_calls}),
        "external_module_calls": sorted(ext),
        "dynamic_dispatch": {k: sorted(set(v)) for k, v in sorted(dynamic.items())},
        "missing_programs": sorted(truly_missing),
        "copies": copies,
        "missing_copybooks": sorted({m["to"] for m in missing_copies}),
        "vendor_copybooks": sorted(vendor_copies),
        "entry_points": entry,
        "jcl_steps": jcl_steps,
        "unreachable_programs": unreachable,
        "stores": {k: {"kind": v["kind"], "dsn": v.get("dsn"),
                       "aliases": v.get("aliases", []), "programs": v["programs"]}
                   for k, v in sorted(stores.items())},
        "store_identity": dict(sorted(identity.items())),
        "clusters": cluster_list,
    }


def write_crud_csv(g: dict, inv: dict, path: str) -> None:
    progs = sorted(p["name"] for p in inv["items"]["cobol"])
    stores = sorted(g["stores"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["store", "kind", "readers", "writers"] + progs)
        for s in stores:
            row = g["stores"][s]["programs"]
            readers = sum(1 for o in row.values() if "R" in o)
            writers = sum(1 for o in row.values() if set(o) & {"C", "U", "D"})
            w.writerow([s, g["stores"][s]["kind"], readers, writers]
                       + [row.get(p, "") for p in progs])


def write_mermaid(g: dict, path: str) -> None:
    lines = ["graph LR"]
    for c in g["clusters"][:12]:
        lines.append('  subgraph %s["%s (%d pgm)"]'
                     % (c["id"], c["id"], c["program_count"]))
        for p in c["programs"][:25]:
            lines.append("    %s" % p)
        lines.append("  end")
    seen = set()
    for e in g["calls"]:
        if e["to"] == "?":
            continue
        k = (e["from"], e["to"])
        if k in seen:
            continue
        seen.add(k)
        lines.append("  %s --> %s" % (e["from"], e["to"]))
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory",
                    default="modernization/1-discovery/inventory.json")
    ap.add_argument("--out-dir", default="modernization/1-discovery")
    ap.add_argument("--mermaid")
    ap.add_argument("--print", dest="show", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.inventory):
        print("no inventory at %s -- run inventory.py first" % a.inventory,
              file=sys.stderr)
        return 2
    inv = json.load(open(a.inventory, encoding="utf-8"))
    g = build(inv)

    os.makedirs(a.out_dir, exist_ok=True)
    dep_path = os.path.join(a.out_dir, "dependencies.json")
    json.dump(g, open(dep_path, "w", encoding="utf-8"), indent=2)
    crud_path = os.path.join(a.out_dir, "crud-matrix.csv")
    write_crud_csv(g, inv, crud_path)
    if a.mermaid:
        write_mermaid(g, a.mermaid)

    print("dependencies -> %s" % dep_path)
    print("crud matrix  -> %s" % crud_path)
    print("  %-26s %d" % ("call edges", len(g["calls"])))
    print("  %-26s %d" % ("data stores", len(g["stores"])))
    print("  %-26s %d" % ("entry points", len(g["entry_points"])))
    print("  %-26s %d" % ("candidate domains", len(g["clusters"])))
    print("  %-26s %d %s" % ("unreachable programs",
                             len(g["unreachable_programs"]),
                             g["unreachable_programs"][:8] or ""))
    if g["external_module_calls"]:
        print("  %-26s %s" % ("external modules",
                              ", ".join(g["external_module_calls"][:8])))
    if g["dynamic_dispatch"]:
        print("  %-26s %d  <- screen flow is RUNTIME-decided; recover it from"
              % ("dynamic dispatch vars", len(g["dynamic_dispatch"])))
        print("  %-26s    the menu/option tables, not from CALL sites" % "")
        for k, v in list(g["dynamic_dispatch"].items())[:5]:
            print("      %-28s used by %s" % (k, ", ".join(v[:4])))
    if g["missing_programs"]:
        print("  %-26s %s" % ("MISSING from source",
                              ", ".join(g["missing_programs"][:8])))
    if g["missing_copybooks"]:
        print("  %-26s %s" % ("missing copybooks",
                              ", ".join(g["missing_copybooks"][:8])))

    if a.show:
        print("\n  candidate domains (from shared-write coupling):")
        for c in g["clusters"]:
            print("  %s  %2d pgm  %5d lines  cplx %4d  %d screens"
                  % (c["id"], c["program_count"], c["lines"], c["complexity"],
                     len(c["screens"])))
            print("      programs: %s" % ", ".join(c["programs"][:10])
                  + (" ..." if len(c["programs"]) > 10 else ""))
            if c["exclusively_owned_stores"]:
                print("      owns:   %s"
                      % ", ".join(c["exclusively_owned_stores"][:8]))
            if c["shared_stores"]:
                print("      SHARED: %s   <- split risk"
                      % ", ".join(c["shared_stores"][:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
