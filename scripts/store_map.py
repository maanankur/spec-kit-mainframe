#!/usr/bin/env python3
"""
store_map.py -- propose 5-data/store-map.json: which copybook describes each data
store, with what key, from what sample file, into which schema.

Deterministic where it can be: cluster names, KEYS(len off), RECORDSIZE and
alternate indexes from IDCAMS DEFINE statements in the JCL; the flat sample DSN
from REPRO; the store's canonical name from dependencies.json store_identity; the
owning context (=> schema) from 3-domain/decomposition.json; copybook candidates
= copybooks COPYd by the store's programs whose field-map record length equals
RECORDSIZE. Every entry that needed a guess carries `confirm: true` and the
candidates it chose between; the data-modernization agent confirms or edits, then
datamod.py consumes the file. Re-running never overwrites an existing store-map.json
unless --force.

Usage: store_map.py --workspace <out-dir> [--force]
"""
import argparse, glob, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import WS, NOW, read, jload, jdump

RE_CLUSTER = re.compile(r"DEFINE\s+CLUSTER\s*\((.*?)\)\s*(?:DATA\b|INDEX\b|DEFINE\b|IF\b|$)", re.I | re.M)
RE_AIX = re.compile(r"DEFINE\s+(?:ALTERNATEINDEX|AIX)\s*\((.*?)\)\s*(?:DATA\b|INDEX\b|DEFINE\b|IF\b|$)", re.I | re.M)


def instream(txt):
    """IDCAMS control statements: in-stream lines (not //), 72 columns, ' -' continuation removed, joined on one line per statement group."""
    out = []; nl = chr(10)
    for l in txt.splitlines():
        if l.startswith("//"): out.append(nl); continue
        l = l[:72].rstrip()
        if l.endswith("-"): out.append(l[:-1] + " ")
        else: out.append(l + nl)
    return re.sub(r"[ \t]+", " ", "".join(out))


def kv(block, key):
    m = re.search(r"\b%s\s*\(\s*([^)]*)\)" % key, block, re.I)
    return [x for x in re.split(r"[\s,]+", m.group(1).strip()) if x] if m else None


def snake(s): return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


QUALIFIERS = {"PS", "VSAM", "KSDS", "ESDS", "RRDS", "AIX", "PATH", "INIT", "DATA", "INDEX", "IMPORT", "PSCOMP", "VBPS", "ARRYPS", "BKUP", "BACKUP", "CLUSTER", "GDG", "G0001V00"}


def common_dsn_prefix(dsns):
    """The high-level qualifiers most datasets share (e.g. 'AWS.M2.CARDDEMO.'), so a store token can be cut from a DSN. Majority (>50%%) per position, not unanimity: one oddly named demo dataset must not defeat the prefix."""
    parts = [d.split(".") for d in dsns if d]
    if not parts: return ""
    pre = []
    for i in range(max(len(p) for p in parts)):
        col = {}
        for p in parts:
            if len(p) > i + 1: col[p[i]] = col.get(p[i], 0) + 1
        if not col: break
        q, n = max(col.items(), key=lambda kv: kv[1])
        if n * 2 > len(parts) and q.upper() not in QUALIFIERS: pre.append(q)
        else: break
    return ".".join(pre) + ("." if pre else "")


def fd_copybooks(path, logicals):
    """Copybooks COPYd inside the FD of the given logical file names -- the deterministic answer to 'which layout describes this file'."""
    src = read(path); found = set()
    for lg in logicals:
        for m in re.finditer(r"\n\s*FD\s+%s\b(.*?)(?=\n\s*(?:FD|SD)\s|\n\s*WORKING-STORAGE|\n\s*LINKAGE|\n\s*PROCEDURE)" % re.escape(lg), src, re.S | re.I):
            found |= {c.upper() for c in re.findall(r"\bCOPY\s+([A-Za-z0-9-]+)", m.group(1))}
    return found


def dsn_token(dsn, prefix):
    """Store token from a DSN: strip the shared prefix and the organisation/lifecycle qualifiers; keep the first meaningful qualifier(s)."""
    rest = dsn[len(prefix):] if prefix and dsn.startswith(prefix) else dsn
    pre_parts = {q.upper() for q in prefix.split(".") if q}
    parts = [p for p in rest.split(".") if p.upper() not in QUALIFIERS and p.upper() not in pre_parts and not re.fullmatch(r"[GV]\d{4,}", p)]
    return parts[0] if parts else dsn.split(".")[-1]


def fd_field_names(path, logicals):
    """Field names declared inline under the FD of the given logical files (level 02-49 entries), for matching against copybook field maps."""
    src = read(path); names = set()
    for lg in logicals:
        for m in re.finditer(r"\n\s*FD\s+%s\b(.*?)(?=\n\s*(?:FD|SD)\s|\n\s*WORKING-STORAGE|\n\s*LINKAGE|\n\s*PROCEDURE)" % re.escape(lg), src, re.S | re.I):
            names |= {n.upper() for n in re.findall(r"\n\s*(?:0[2-9]|[1-4]\d)\s+([A-Za-z0-9-]+)", m.group(1))}
    return names


def name_core(n):
    """Strip the group prefix so FD-TRAN-CAT-BAL and TRAN-CAT-BAL compare equal: drop leading 2-3 letter qualifier tokens."""
    parts = n.split("-")
    while len(parts) > 2 and len(parts[0]) <= 3: parts = parts[1:]
    return "-".join(parts)


def rank_by_fields(cands, fd_names, ws):
    """Order copybook candidates by Jaccard overlap between their field names and the FD's inline field names."""
    if not fd_names or len(cands) < 2: return cands, None
    fd_core = {name_core(n) for n in fd_names if n != "FILLER"}; scored = []
    for cb in cands:
        fm = jload(os.path.join(ws.FM, cb + ".fieldmap.json"), {})
        cb_names = {name_core(f["name"]) for r in fm.get("records", []) for f in r["fields"] if f["name"] != "FILLER"}
        inter = len(fd_core & cb_names); union = len(fd_core | cb_names) or 1; scored.append((inter / union, cb))
    scored.sort(reverse=True)
    return [cb for _, cb in scored], scored


def is_fd_style(name):
    return bool(re.search(r"-(FILE|INPUT|OUTPUT|IN|OUT|REC|RECORD)$", name or ""))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--force", action="store_true"); a = ap.parse_args(); ws = WS(a.workspace)
    out = os.path.join(ws.D5, "store-map.json")
    if os.path.exists(out) and not a.force: print("store-map.json exists; not overwriting (use --force)"); return 0
    inv = jload(os.path.join(ws.DISC, "inventory.json")); dep = jload(os.path.join(ws.DISC, "dependencies.json")); dec = jload(os.path.join(ws.D3, "decomposition.json"), {"contexts": []})
    ds = jload(os.path.join(ws.DISC, "datasets.json"), {"datasets": []})["datasets"]
    by_dsn = {}
    for name, ident in dep.get("store_identity", {}).items():
        if ident.get("dsn"): by_dsn.setdefault(ident["dsn"], ident.get("resolved_to") or name)
    for name, s in dep.get("stores", {}).items():
        if s.get("dsn"): by_dsn.setdefault(s["dsn"], name)
    owner = {s: c["id"] for c in dec["contexts"] for s in c.get("owned_stores_canonical", c.get("owned_stores", []))}
    cname = {c["id"]: c["name"] for c in dec["contexts"]}
    progs = {c["name"]: c for c in inv["items"]["cobol"]}
    fm_len = {}
    for f in glob.glob(os.path.join(ws.FM, "*.fieldmap.json")):
        j = jload(f); fm_len[os.path.splitext(os.path.basename(j["copybook"]))[0]] = j["records"][0]["length"] if j.get("records") else None
    clusters, aixes, repro = {}, [], {}
    prefix = common_dsn_prefix([d for j in inv["items"]["jcl"] for d in j.get("datasets", [])])
    def find_ascii(token):
        hits = [p for p in glob.glob(os.path.join(ws.source, "**", "*"), recursive=True) if os.path.isfile(p) and "ascii" in p.lower().replace(ws.source.lower(), "") and snake(token) and snake(token) in snake(os.path.basename(p))]
        return os.path.relpath(hits[0], ws.source).replace("\\", "/") if hits else None
    for j in inv["items"]["jcl"]:
        raw = read(j["path"]); txt = instream(raw); dd = {d["dd"]: d["dsn"] for d in j.get("dd_dsn", [])}
        for m in RE_CLUSTER.finditer(txt):
            b = m.group(1); name = (kv(b, "NAME") or ["?"])[0]; keys = kv(b, "KEYS"); rs = kv(b, "RECORDSIZE")
            clusters[name] = dict(dsn=name, jcl=j["name"], key=[int(keys[0]), int(keys[1])] if keys else None, record_length=int(rs[0]) if rs else None, max_record_length=int(rs[1]) if rs and len(rs) > 1 else None,
                                  organization="ksds" if re.search(r"\bINDEXED\b", b, re.I) or keys else ("rrds" if re.search(r"\bNUMBERED\b", b, re.I) else "esds"))
        for m in RE_AIX.finditer(txt):
            b = m.group(1); keys = kv(b, "KEYS"); aixes.append(dict(name=(kv(b, "NAME") or ["?"])[0], relate=(kv(b, "RELATE") or ["?"])[0], key=[int(keys[0]), int(keys[1])] if keys else None, unique=not re.search(r"NONUNIQUEKEY", b, re.I)))
        for m in re.finditer(r"REPRO\s+INFILE\s*\(\s*(\w+)\s*\)\s+OUTFILE\s*\(\s*(\w+)\s*\)", txt, re.I):
            if m.group(1) in dd and m.group(2) in dd: repro[dd[m.group(2)]] = dd[m.group(1)]
        for m in re.finditer(r"REPRO\s+INDATASET\s*\(\s*([\w.]+)\s*\)\s+OUTDATASET\s*\(\s*([\w.]+)\s*\)", txt, re.I): repro[m.group(2)] = m.group(1)
    def find_sample(*tokens):
        hits = [d["path"] for d in ds for t in tokens if t and os.path.basename(d["path"]).upper() == t.upper()]
        return hits[0] if hits else None
    def ascii_companion(token):
        hits = [d["path"] for d in ds if token and snake(token) in snake(os.path.basename(d["path"])) and d["path"].lower().endswith((".txt", ".csv", ".dat")) and "ascii" in d["path"].lower()]
        return hits[0] if hits else None
    entries = []; seen = {}
    ident = dep.get("store_identity", {})
    for dsn, c in sorted(clusters.items(), key=lambda kv: (dsn_token(kv[0], prefix), kv[1]["organization"] != "ksds", kv[0])):
        canon = by_dsn.get(dsn); token = dsn_token(dsn, prefix)
        store = canon if canon and not is_fd_style(canon) else token
        logicals = sorted({n for n, v in ident.items() if v.get("dsn") == dsn or (canon and v.get("resolved_to") == canon)} | set(dep.get("stores", {}).get(canon or "", {}).get("aliases", [])) | ({canon} if canon else set()))
        aliases = sorted(set(logicals) - {store})
        users = sorted({p for n in logicals + [store] for p in dep.get("stores", {}).get(n, {}).get("programs", {})})
        fdc = set()
        for p in users: fdc |= fd_copybooks(progs[p]["path"], logicals) if p in progs else set()
        fdc = {cb for cb in fdc if fm_len.get(cb) in (None, c["record_length"])}
        cands = sorted(fdc) if fdc else sorted({cb for p in users for cb in progs.get(p, {}).get("copies", []) if fm_len.get(cb) == c["record_length"]})
        fdn = set()
        for p in users: fdn |= fd_field_names(progs[p]["path"], logicals) if p in progs else set()
        cands, scored = rank_by_fields(cands, fdn, ws)
        if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > 2 * (scored[1][0] or 0.0001)): cands, fdc = cands[:1], fdc or {"field-name match"}
        ctx = owner.get(canon) or owner.get(store); sample = find_sample(repro.get(dsn), dsn) or find_sample(re.sub(r"\.VSAM.*$", ".PS", dsn))
        if store in seen:   # the same store defined more than once (e.g. KSDS and an ESDS/RRDS demo variant): keep the first (KSDS preferred), record the other
            seen[store]["note"] += " also defined as %s in %s (%s)." % (c["organization"].upper(), c["jcl"], dsn); continue
        e = dict(store=store, aliases=aliases, kind="vsam-" + c["organization"], dsn=dsn, defined_in=c["jcl"], record_length=c["record_length"], key=c["key"],
                 alternate_indexes=[dict(name=x["name"], key=x["key"], unique=x["unique"]) for x in aixes if x["relate"] == dsn],
                 copybook=cands[0] if len(cands) == 1 else None, copybook_candidates=cands, copybook_source=("field-name match (%.2f)" % scored[0][0]) if scored else ("FD COPY" if fdc else "record-length match"), programs=users, owner_context=ctx,
                 schema=snake(cname.get(ctx, ctx or "unassigned")), table=snake(store), sample=sample, ascii_sample=find_ascii(store) or find_ascii(token),
                 encoding=str(ws.cfg.get("source", {}).get("charset", "cp037")), migrate=bool(users), redefines_when={},
                 note="" if users else "defined in JCL but no program references this DSN -- proposed not migrated.", confirm=len(cands) != 1 or ctx is None or sample is None)
        seen[store] = e; entries.append(e)
    cl_stores = {e["store"] for e in entries} | {a for e in entries for a in e["aliases"]}
    for name, s in sorted(dep.get("stores", {}).items()):
        canon = dep.get("store_identity", {}).get(name, {}).get("resolved_to") or name
        if canon in cl_stores or s.get("kind") != "file" or not s.get("dsn"): continue
        users = sorted(s.get("programs", {})); fdc = set()
        for p in users: fdc |= fd_copybooks(progs[p]["path"], [name, canon]) if p in progs else set()
        cands = sorted(fdc) if fdc else sorted({cb for p in users for cb in progs.get(p, {}).get("copies", []) if fm_len.get(cb)})
        ctx = owner.get(canon); cl_stores.add(canon); token = dsn_token(s["dsn"], prefix); store = canon if not is_fd_style(canon) else token
        entries.append(dict(store=store, aliases=sorted({canon, name} - {store}), kind="sequential", dsn=s["dsn"], record_length=fm_len.get(cands[0]) if len(cands) == 1 else None, key=None, alternate_indexes=[], copybook=cands[0] if len(cands) == 1 else None, copybook_candidates=cands, copybook_source="FD COPY" if fdc else "candidates", programs=users, owner_context=ctx,
                            schema=snake(cname.get(ctx, ctx or "unassigned")), table=snake(store), sample=find_sample(s["dsn"]), ascii_sample=find_ascii(store) or find_ascii(token), encoding=str(ws.cfg.get("source", {}).get("charset", "cp037")),
                            migrate=any("C" in ops or "U" in ops for ops in s.get("programs", {}).values()) is False, redefines_when={}, note="sequential dataset: input staging or regenerated output -- decide migrate", confirm=True))
    for d in inv["items"].get("ddl", []):
        entries.append(dict(store="DB2." + d["name"], kind="db2", ddl=d["path"], schema=None, table=None, migrate=True, note="DDL is the truth for types, nullability and keys; set schema from the owning context", confirm=True))
    dbds = [p for p in glob.glob(os.path.join(ws.source, "**", "*.dbd"), recursive=True)]
    for p in dbds:
        entries.append(dict(store="IMS." + os.path.splitext(os.path.basename(p))[0], kind="ims", dbd=p, segments=[dict(segment="<SEGM NAME>", copybook="<copybook>", table="<table>", primary_key=["<cols>"], parent_key_columns=[])], schema=None, migrate=True,
                            note="hierarchy -> parent/child tables with the parent key materialised; fill segments from the DBD and the unload copybooks", confirm=True))
    doc = dict(_readme=["Proposed %s by store_map.py from IDCAMS definitions, JCL REPRO, dependencies.json and the field maps." % NOW,
                        "Confirm or edit every entry with confirm=true: copybook (exactly one), owner/schema, sample, migrate. datamod.py refuses entries that still lack a copybook.",
                        "redefines_when: {\"DISCRIMINATOR-FIELD\": {\"value\": \"OVERLAY-RECORD-NAME\"}} for files whose layout REDEFINES by record type.",
                        "production_extracts_supplied: set true only when the fidelity run below was executed on production extracts, not samples."],
               generated_at=NOW, source=ws.source, dsn_prefix=prefix, production_extracts_supplied=False, stores=entries)
    jdump(out, doc)
    print("stores proposed %d (clusters %d, sequential %d, db2 %d, ims %d) | needing confirmation %d -> %s" % (len(entries), len(clusters), sum(1 for e in entries if e["kind"] == "sequential"), len(inv["items"].get("ddl", [])), len(dbds), sum(1 for e in entries if e.get("confirm")), ws.rel(out)))
    for e in entries:
        if e.get("kind", "").startswith("vsam"): print("  %-10s %-9s len %-4s key %-9s cb %-9s ctx %-6s sample %-34s ascii %s" % (e["store"], e["kind"], e["record_length"], e["key"], e["copybook"] or "?%s" % e["copybook_candidates"], e["owner_context"], os.path.basename(e["sample"] or "-"), os.path.basename(e["ascii_sample"] or "-")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
