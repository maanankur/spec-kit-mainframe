#!/usr/bin/env python3
"""
datamod.py -- Phase 5: data modernization from the confirmed store map, the field
maps, the DB2 DDL and the IMS segment layouts, with the fidelity proof run on the
sample datasets that ship with the source.

Everything type-shaped comes from the field maps (copybook_parse.py); keys from the
store map (IDCAMS KEYS, DDL, DBD). Judgement is confined to 5-data/store-map.json
(store_map.py proposes it, the data-modernization agent confirms it).

Outputs (5-data/): schema.sql, mapping.json, fidelity-report.md,
migration/{plan.md,decode_all.sh,load.sql,reconcile.sql};
governance/gates/G4/{review-pack.md,manifest.json}; state.json G4 = proposed.

Usage: datamod.py --workspace <out-dir>
"""
import argparse, collections, decimal, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import WS, NOW, read, write, jload, jdump, manifest, md, render_pack, propose_gate

HERE = os.path.dirname(os.path.abspath(__file__))


def snake(s, prefix=""):
    n = s[len(prefix):] if prefix and s.startswith(prefix) else s
    return re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_")

def common_prefix(names):
    names = [n for n in names if n != "FILLER"]
    p = os.path.commonprefix(names) if names else ""
    return p[:p.rfind("-") + 1] if "-" in p else ""

def leaf_fields(rec):
    fs = rec["fields"]; return [f for f in fs if not any(o["path"].startswith(f["path"] + ".") for o in fs) and f["length"] > 0]

def encode_field(f, val, enc):
    ln = f["length"]
    if f["kind"] != "numeric":
        b = (val or "").encode(enc, errors="replace"); return (b + b"\x40" * ln)[:ln]
    if val in (None, ""): return None
    d = decimal.Decimal(val); neg = d < 0; digits = str(abs(d).scaleb(f["scale"]).to_integral_value()).rjust(f["digits"], "0")
    if f["usage"] == "COMP-3":
        nib = digits + ("D" if neg else "C" if f["signed"] else "F")
        if len(nib) % 2: nib = "0" + nib
        return bytes.fromhex(nib).rjust(ln, b"\x00")
    if f["usage"] in ("COMP", "COMP-4", "COMP-5", "BINARY"): return int(d.scaleb(f["scale"])).to_bytes(ln, "big", signed=f["signed"])
    b = bytearray(0xF0 | int(c) for c in digits[-ln:].rjust(ln, "0"))
    if f["signed"]: b[-1] = ((0xD0 if neg else 0xC0) | (b[-1] & 0x0F))
    return bytes(b)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); a = ap.parse_args(); ws = WS(a.workspace)
    SM = jload(os.path.join(ws.D5, "store-map.json"))
    if not SM: print("REFUSED: 5-data/store-map.json missing -- run store_map.py, then confirm it"); return 1
    MIG = os.path.join(ws.D5, "migration"); os.makedirs(MIG, exist_ok=True)
    def decode(cb, path, enc, extra=()):
        r = subprocess.run([sys.executable, os.path.join(HERE, "decode_record.py"), "--fieldmap", os.path.join(ws.FM, cb + ".fieldmap.json"), "--data", path, "--encoding", enc, "--format", "jsonl", *extra], capture_output=True, text=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"), encoding="utf-8")
        return [json.loads(l) for l in r.stdout.splitlines() if l.startswith("{")], (r.stderr or "").strip()
    schemas = sorted({e.get("schema") for e in SM["stores"] if e.get("schema") and e.get("migrate")} | {"migration_staging"})
    parts = ["-- %s target schema (%s) -- generated %s by datamod.py from 5-data/store-map.json and the copybook field maps.\n-- Money is NUMERIC, never FLOAT. Dates decoded from X(10) YYYY-MM-DD keep a *_raw staging column until the fidelity round trip is green.\n" % (ws.project, ws.cfg.get("target", {}).get("database", "postgresql"), NOW)]
    parts += ["CREATE SCHEMA IF NOT EXISTS %s;" % s for s in schemas] + [""]
    mapping = dict(generated_at=NOW, stores=[], not_migrated=[]); fidelity = []; problems = []; xchecks = []
    for e in SM["stores"]:
        kind = e.get("kind", "")
        if kind == "db2":
            if e.get("ddl") and os.path.exists(e["ddl"]):
                s = re.sub(r"--.*", "", read(e["ddl"])); s = re.sub(r"\bDECIMAL\b", "NUMERIC", s, flags=re.I); s = re.sub(r"FOREIGN KEY\s+\w+\s*\(", "FOREIGN KEY (", s)
                if e.get("schema"): s = re.sub(r"\b%s\." % re.escape(e.get("ddl_schema_prefix", "").rstrip(".") or "__none__"), e["schema"] + ".", s)
                parts.append("-- %s <- %s (DDL is the truth for types, nullability, keys; CHAR stays CHAR: blank-padded, trailing-blank-insensitive compare)\n%s\n" % (e["store"], os.path.basename(e["ddl"]), re.sub(r"\n\s*\n", "\n", s).strip()))
            mapping["stores"].append(dict(legacy=e["store"], kind="db2", schema=e.get("schema"), table=e.get("table"), migrate=e.get("migrate", True), note=e.get("note", ""), ddl=e.get("ddl"))); continue
        if kind == "ims":
            for seg in e.get("segments", []):
                fmp = os.path.join(ws.FM, str(seg.get("copybook")) + ".fieldmap.json")
                if not os.path.exists(fmp): problems.append("%s segment %s: copybook %s has no field map" % (e["store"], seg.get("segment"), seg.get("copybook"))); continue
                rec = jload(fmp)["records"][0]; leaves = leaf_fields(rec); pre = common_prefix([f["name"] for f in leaves]); body = []; cols = []
                for pk in seg.get("parent_key_columns", []): body.append("    %-32s %-14s NOT NULL" % (pk["column"], pk["type"]) + (" REFERENCES %s.%s(%s)" % (e.get("schema"), pk["references_table"], pk["references_column"]) if pk.get("references_table") else ""))
                for f in leaves:
                    if f["name"] == "FILLER": continue
                    col = snake(f["name"], pre); t = f["sql_type"] + ("[]" if f.get("occurs", 1) > 1 else "")
                    body.append("    %-32s %-14s%s" % (col, t, " NOT NULL" if col in seg.get("primary_key", []) else "")); cols.append(dict(cobol=f["name"], column=col, type=t, offset=f["offset"], length=f["length"]))
                body.append("    PRIMARY KEY (%s)" % ", ".join(seg.get("primary_key", [])))
                parts.append("-- IMS %s segment %s (%d bytes) <- %s; parent key materialised as column(s) %s\nCREATE TABLE %s.%s (\n%s\n);\n" % (e["store"], seg.get("segment"), rec["length"], seg["copybook"], ", ".join(p["column"] for p in seg.get("parent_key_columns", [])) or "—", e.get("schema"), seg["table"], ",\n".join(body)))
                mapping["stores"].append(dict(legacy=e["store"] + "/" + str(seg.get("segment")), kind="ims-segment", copybook=seg["copybook"], schema=e.get("schema"), table=seg["table"], migrate=e.get("migrate", True), record_length=rec["length"], primary_key=seg.get("primary_key"), fields=cols, note=e.get("note", "")))
            continue
        cb = e.get("copybook"); enc = e.get("encoding", "cp037")
        if not cb and not e.get("migrate", True):
            mapping["not_migrated"].append("%s (%s)" % (e["store"], e.get("note") or "not migrated")); continue
        if not cb:
            problems.append("%s: no copybook confirmed (candidates %s)" % (e["store"], e.get("copybook_candidates"))); mapping["not_migrated"].append("%s (no copybook)" % e["store"]); continue
        fmp = os.path.join(ws.FM, cb + ".fieldmap.json")
        if not os.path.exists(fmp): problems.append("%s: field map for %s missing" % (e["store"], cb)); continue
        rec = jload(fmp)["records"][0]; leaves = leaf_fields(rec); pre = common_prefix([f["name"] for f in leaves])
        sample = os.path.join(ws.source, e["sample"]) if e.get("sample") and not os.path.isabs(e["sample"]) else e.get("sample")
        rows, err = [], ""
        if sample and os.path.exists(sample):
            if e.get("redefines_when"):
                disc, overlays = next(iter(e["redefines_when"].items())); by_type = {}
                for v, ov in overlays.items(): by_type[v], err = decode(cb, sample, enc, ["--redefines-when", "%s=%s:%s" % (disc, v, ov)])
                first = next(iter(by_type.values()), []); dpath = next((f["path"] for f in leaves if f["name"] == disc), None)
                rows = [by_type.get(r.get(dpath), first)[i] for i, r in enumerate(first)]
            else: rows, err = decode(cb, sample, enc)
        size = os.path.getsize(sample) if sample and os.path.exists(sample) else None; fit = size is not None and rec["length"] and size % rec["length"] == 0
        klen, koff = (e.get("key") or [0, 0]); cols = []; blank_filler = True
        for f in leaves:
            vals = [r.get(f["path"]) for r in rows]; is_key = bool(klen) and f["offset"] >= koff and f["offset"] + f["length"] <= koff + klen; nulls = sum(1 for v in vals if v in (None, ""))
            if f["kind"] == "numeric":
                nums = [decimal.Decimal(v) for v in vals if v not in (None, "")]
                obs = dict(count=len(nums), sum=str(sum(nums)), min=str(min(nums)), max=str(max(nums)), negatives=sum(1 for x in nums if x < 0), zeros=sum(1 for x in nums if x == 0), nulls=nulls) if nums else {}
                sqlt = f["sql_type"]
            else:
                texts = [v for v in vals if v not in (None, "")]; isdate = f["length"] == 10 and texts and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in texts)
                obs = dict(count=len(vals), blank=nulls, distinct=len(set(texts)), max_len=max((len(v) for v in texts), default=0), date_pattern=bool(isdate)); sqlt = "DATE" if isdate else f["sql_type"]
                if f["name"] == "FILLER" and texts: blank_filler = False
            col = None if f["name"] == "FILLER" and blank_filler and rows else snake(f["name"], pre) if f["name"] != "FILLER" else "filler_%d" % f["offset"]
            cols.append(dict(cobol=f["name"], path=f["path"], offset=f["offset"], length=f["length"], pic=f["pic"], usage=f["usage"], column=col, type=sqlt, nullable=bool(nulls > 0 and not is_key), key=bool(is_key), occurs=f.get("occurs", 1), observed=obs,
                             note="verified all-spaces across %d sample records; dropped" % len(rows) if col is None else ("FILLER carries data -- KEPT" if f["name"] == "FILLER" else ("X(10) YYYY-MM-DD in every sample row; DATE + _raw staging" if sqlt == "DATE" else None))))
        pk = [c["column"] for c in cols if c["key"] and c["column"]]
        aix = [dict(key_length=x["key"][0], key_offset=x["key"][1], unique=x.get("unique", False), name=x.get("name")) for x in e.get("alternate_indexes", []) if x.get("key")]
        mapping["stores"].append(dict(legacy=e["store"], copybook=cb, kind=kind, dsn=e.get("dsn"), schema=e.get("schema"), table=e.get("table"), migrate=e.get("migrate", True), note=e.get("note", ""), record_length=rec["length"], encoding=enc, primary_key=pk,
                                      sample=dict(file=e.get("sample"), bytes=size, lrecl_fit=fit, records=len(rows), decoder_messages=err[:300]) if sample else None, alternate_indexes=aix, fields=cols))
        if not e.get("migrate", True): mapping["not_migrated"].append("%s (%s)" % (e["store"], e.get("note") or "not migrated"))
        elif e.get("table"):
            body = ["    %-32s %-14s%s" % (c["column"], c["type"] + ("[]" if c["occurs"] > 1 else ""), "" if c["nullable"] else " NOT NULL") for c in cols if c["column"]]
            body += ["    %-32s CHAR(10)" % (c["column"] + "_raw") for c in cols if c["column"] and c["type"] == "DATE"]
            if pk: body.append("    PRIMARY KEY (%s)" % ", ".join(pk))
            lines = ["-- %s <- %s (%s), %d bytes/record; %s" % (e["table"], e["store"], cb, rec["length"], e.get("note", "")), "CREATE TABLE %s.%s (\n%s\n);" % (e["schema"], e["table"], ",\n".join(body))]
            for i, x in enumerate(aix, 1):
                ix = [c["column"] for c in cols if c["column"] and c["offset"] >= x["key_offset"] and c["offset"] + c["length"] <= x["key_offset"] + x["key_length"]]
                lines.append("CREATE %sINDEX ix_%s_%d ON %s.%s (%s); -- AIX %s" % ("UNIQUE " if x["unique"] else "", e["table"], i, e["schema"], e["table"], ", ".join(ix) or "/* unresolved key range */", x.get("name") or ""))
            for f in leaves:
                c = next((c for c in cols if c["cobol"] == f["name"] and c["column"]), None); conds = f.get("conditions") or []
                if c and conds:
                    vals = sorted({v.strip().strip("'").strip('"') for k in conds for v in (k.get("values") or "").split(",") if v.strip()})
                    if vals and all(len(v) <= 4 for v in vals): lines.append("ALTER TABLE %s.%s ADD CONSTRAINT ck_%s_%s CHECK (%s IN (%s)); -- 88-levels: %s" % (e["schema"], e["table"], e["table"], c["column"], c["column"], ", ".join("'%s'" % v for v in vals), ", ".join(k["name"] for k in conds)))
            parts.append("\n".join(lines) + "\n")
        # fidelity: byte round trip + edge cases
        fd = dict(store=e["store"], cb=cb, sample=e.get("sample"), size=size, lrecl=rec["length"], fit=fit, records=len(rows), err=err, filler_blank=blank_filler, migrate=e.get("migrate", True), cols=cols, edges=[], rt=None)
        if rows:
            raw = open(sample, "rb").read(); ok = expl = bad = 0; details = []
            for i, row in enumerate(rows):
                buf = raw[i * rec["length"]:(i + 1) * rec["length"]]
                for f in leaves:
                    if f["path"] not in row: continue
                    orig = buf[f["offset"]:f["offset"] + f["length"]]; encd = encode_field(f, row.get(f["path"]), enc)
                    if encd is None: (ok if orig.strip(b"\x00\x40") == b"" else None); ok += 1 if orig.strip(b"\x00\x40") == b"" else 0; bad += 0 if orig.strip(b"\x00\x40") == b"" else 1; continue
                    if encd == orig: ok += 1
                    elif f["kind"] == "numeric" and f["usage"] == "DISPLAY" and f["signed"] and encd[:-1] == orig[:-1] and (encd[-1] & 0x0F) == (orig[-1] & 0x0F) and (orig[-1] >> 4) in (0xF, 0xC): expl += 1
                    elif f["kind"] != "numeric" and orig.rstrip(b"\x00\x40") == encd.rstrip(b"\x40"): expl += 1
                    else:
                        bad += 1
                        if len(details) < 8: details.append("%s %s rec %d: file %s != re-encoded %s" % (e["store"], f["name"], i, orig.hex(), encd.hex()))
            fd["rt"] = (ok, expl, bad, details)
            for c in cols:
                o = c["observed"]
                if o and "negatives" in o and o["negatives"]: fd["edges"].append("%s has %d negative values" % (c["cobol"], o["negatives"]))
                if o and o.get("nulls"): fd["edges"].append("%s uninitialised (spaces/low-values) in %d records — decodes to NULL, not 0" % (c["cobol"], o["nulls"]))
            for f in leaves:
                if any(isinstance(v, str) and v and set(v) <= {"9"} and len(v) == f["length"] for v in (r.get(f["path"]) for r in rows)): fd["edges"].append("%s contains an all-9s sentinel" % f["name"])
            if e.get("ascii_sample"):
                p = os.path.join(ws.source, e["ascii_sample"]); n_asc = sum(1 for l in open(p, errors="replace") if l.strip()) if os.path.exists(p) else None
                fd["ascii"] = (e["ascii_sample"], n_asc); xchecks.append(n_asc == len(rows))
        fidelity.append(fd)
    write(os.path.join(ws.D5, "schema.sql"), "\n".join(parts) + "\n"); jdump(os.path.join(ws.D5, "mapping.json"), mapping)

    rt_mig = [0, 0, 0]; bad_details = []
    R = ["# Data fidelity report\n", "Run %s by `datamod.py` on the sample datasets named in `store-map.json`, decoded with `decode_record.py` and the field maps. **%s.** Every check is re-runnable on the real extracts.\n" % (NOW, "Production extracts" if SM.get("production_extracts_supplied") else "Sample data only — production volumes unknown")]
    for fd in fidelity:
        R.append("## %s ← `%s`%s\n" % (fd["store"], fd["cb"], "" if fd["migrate"] else " (not migrated — evidence only)"))
        if not fd["sample"]: R.append("**No sample dataset supplied.** Decode and reconciliation must run on the production extract before G4 can be green for this store.\n"); continue
        R += ["| Check | Result |", "|---|---|", "| Record length fits file | %s — %s bytes / %s = %s records |" % ("✅" if fd["fit"] else "❌", fd["size"], fd["lrecl"], (fd["size"] // fd["lrecl"]) if fd["size"] is not None and fd["lrecl"] else "?"),
              "| Strict decode | %s — %d records; %s |" % ("✅" if fd["records"] and "error" not in fd["err"].lower() else "❌", fd["records"], md(fd["err"].splitlines()[0]) if fd["err"] else "no decoder messages"),
              "| FILLER | %s |" % ("all spaces/low-values — dropped" if fd["filler_blank"] else "❌ **carries data** — kept as a column, investigate")]
        if fd["rt"]:
            ok, expl, bad, det = fd["rt"]; R.append("| Byte round trip (decode → re-encode → compare) | %s — %d identical, %d explained (sign zone F/C, trailing low-values), **%d unexplained** |" % ("✅" if bad == 0 else "❌", ok, expl, bad))
            if fd["migrate"]: rt_mig[0] += ok; rt_mig[1] += expl; rt_mig[2] += bad; bad_details += det
        if fd.get("ascii"): R.append("| ASCII companion `%s` | %s lines vs %d EBCDIC records — %s |" % (os.path.basename(fd["ascii"][0]), fd["ascii"][1], fd["records"], "✅ match" if fd["ascii"][1] == fd["records"] else "❌ MISMATCH"))
        nums = [c for c in fd["cols"] if c["observed"] and "sum" in c["observed"]]
        if nums:
            R += ["\n**Numeric reconciliation values** (recompute on the loaded table; every figure must match exactly):\n", "| Field | PIC | Count | Sum | Min | Max | Negatives | Zeros | Uninitialised |", "|---|---|---|---|---|---|---|---|---|"]
            R += ["| %s | %s | %d | %s | %s | %s | %d | %d | %d |" % (c["cobol"], c["pic"], c["observed"]["count"], c["observed"]["sum"], c["observed"]["min"], c["observed"]["max"], c["observed"]["negatives"], c["observed"]["zeros"], c["observed"]["nulls"]) for c in nums]
        R.append("\n**Edge cases:** " + ("; ".join(fd["edges"]) if fd["edges"] else "none observed in the sample (negatives, sentinels, uninitialised numerics absent — the production extract must be swept)") + "\n")
    sampled = [f for f in fidelity if f["sample"]]
    R.insert(2, "## Summary\n\n| Check | Result |\n|---|---|\n| Stores with sample data decoded | %d of %d |\n| Record-length fit | %s |\n| Byte round trip — migrated stores | %d identical, %d explained, **%d unexplained** |\n| ASCII/EBCDIC record-count cross-checks | %d/%d match |\n| Store-map problems | %d |\n" % (
        len(sampled), len(fidelity), "all fit" if all(f["fit"] for f in sampled) else "❌ a file does not divide by its record length", rt_mig[0], rt_mig[1], rt_mig[2], sum(1 for x in xchecks if x), len(xchecks), len(problems)))
    if bad_details: R.append("## Unexplained round-trip differences\n" + "\n".join("- " + b for b in bad_details) + "\n")
    if problems: R.append("## Store-map problems\n" + "\n".join("- " + p for p in problems) + "\n")
    R.append("## What this proves and does not prove\n- Decoding, sign handling, scale and offsets are correct for every field that appears in the samples (the round trip is byte-level).\n- It does **not** prove production data unless `production_extracts_supplied` is true. G4 is green for the *method*; the same checks must be re-run on the production extracts before the first migration wave.\n- Nullability decisions in `mapping.json` are inferred from where the sample has spaces/low-values; the DBA should confirm each `nullable: true`.\n")
    write(os.path.join(ws.D5, "fidelity-report.md"), "\n".join(R) + "\n")

    # migration scripts
    sh = ["#!/usr/bin/env bash", "# Decode every migrated store with its field map. SRC = extract directory (EBCDIC, RECFM=FB).", "set -euo pipefail", 'SRC="${1:-%s}"' % ws.source.replace("\\", "/"), 'OUT="${2:-./staging}"', 'FM="%s"' % ws.FM.replace("\\", "/"), 'DEC="%s/decode_record.py"' % HERE.replace("\\", "/"), 'mkdir -p "$OUT"']
    sh += ['python "$DEC" --fieldmap "$FM/%s.fieldmap.json" --data "$SRC/%s" --encoding %s --strict --format csv --out "$OUT/%s.csv"' % (s["copybook"], s["sample"]["file"], s["encoding"], s["table"]) for s in mapping["stores"] if s.get("migrate") and s.get("copybook") and s.get("sample") and s["sample"].get("file") and s.get("table")]
    sh += ["# %s: no sample -- production extract required" % s["legacy"] for s in mapping["stores"] if s.get("migrate") and s.get("copybook") and not s.get("sample")]
    write(os.path.join(MIG, "decode_all.sh"), "\n".join(sh) + "\n")
    ld = ["-- Load decoded CSVs into staging, then promote. Run after decode_all.sh. psql -v ON_ERROR_STOP=1"]
    rc = ["-- Aggregate reconciliation: compare with the 'Numeric reconciliation values' tables in fidelity-report.md. Every figure must match exactly."]
    for s in mapping["stores"]:
        if s.get("migrate") and s.get("table") and isinstance(s.get("fields"), list) and s.get("schema"):
            cols = [c["column"] for c in s["fields"] if c["column"]]
            ld += ["CREATE TABLE IF NOT EXISTS migration_staging.%s (LIKE %s.%s INCLUDING ALL);" % (s["table"], s["schema"], s["table"]), "\\copy migration_staging.%s (%s) FROM 'staging/%s.csv' WITH (FORMAT csv, HEADER true, NULL '')" % (s["table"], ", ".join(cols), s["table"]), "INSERT INTO %s.%s SELECT * FROM migration_staging.%s;" % (s["schema"], s["table"], s["table"])]
            nums = [c["column"] for c in s["fields"] if c["column"] and str(c["type"]).startswith(("NUMERIC", "BIGINT", "INTEGER"))]
            if nums: rc.append("SELECT '%s' AS tbl, COUNT(*) AS rows, %s FROM %s.%s;" % (s["table"], ", ".join("SUM(%s) AS sum_%s, MIN(%s) AS min_%s, MAX(%s) AS max_%s" % (c, c, c, c, c, c) for c in nums[:4]), s["schema"], s["table"]))
    write(os.path.join(MIG, "load.sql"), "\n".join(ld) + "\n"); write(os.path.join(MIG, "reconcile.sql"), "\n".join(rc) + "\n")
    waves = ws.state().get("waves", []); dec = jload(os.path.join(ws.D3, "decomposition.json"), {"contexts": []}); owner = {s: c["id"] for c in dec["contexts"] for s in c.get("owned_stores_canonical", [])}
    wave_of = {c: w["wave"] for w in waves for c in w["contexts"]}
    plan = ["# Migration plan\n", "Generated %s. Each store migrates in the wave of its owning context (4-architecture/wave-plan.md); the legacy copy is retained until that wave's G6.\n" % NOW, "| Wave | Store | Target | Method | Reconciliation |", "|---|---|---|---|---|"]
    for s in sorted(mapping["stores"], key=lambda s: (wave_of.get(owner.get(s["legacy"].split("/")[0]), 99), s["legacy"])):
        if not s.get("migrate"): continue
        plan.append("| %s | %s | %s.%s | %s | counts, PK/AIX uniqueness, numeric sums to the cent (`reconcile.sql` vs `fidelity-report.md`) |" % (wave_of.get(owner.get(s["legacy"].split("/")[0]), "?"), s["legacy"], s.get("schema"), s.get("table"), "DDL converted; unload → COPY" if s["kind"] == "db2" else "decode_record → COPY"))
    plan.append("\n## Rules\n- Decode with the field map, never an ad-hoc reader; `--strict` fails on any undecodable byte.\n- Load into `migration_staging` first; promote only when `reconcile.sql` matches `fidelity-report.md` exactly.\n- Every transformation that is not identity is a logged row in the migration audit table with before/after bytes.\n- The legacy store is the system of record for a context until its wave passes G6; reconciliation runs nightly during coexistence.\n")
    write(os.path.join(MIG, "plan.md"), "\n".join(plan))

    migrated = [s for s in mapping["stores"] if s.get("migrate")]; decoded = sum(1 for f in sampled if f["records"])
    evid = [("Field-mapping coverage", "%d/%d migrated stores mapped field-by-field; problems: %d" % (sum(1 for s in migrated if s.get("fields") or s["kind"] == "db2"), len(migrated), len(problems)), "100%, 0 problems", not problems),
            ("Record-length fit on sample files", "%d/%d sample files divide exactly" % (sum(1 for f in sampled if f["fit"]), len(sampled)), "all", all(f["fit"] for f in sampled)),
            ("Strict decode of sample data", "%d/%d sampled stores decode" % (decoded, len(sampled)), "all", decoded == len(sampled)),
            ("Byte round trip (migrated stores)", "%d identical, %d explained, %d unexplained" % tuple(rt_mig), "0 unexplained", rt_mig[2] == 0),
            ("ASCII/EBCDIC count cross-check", "%d/%d matching" % (sum(1 for x in xchecks if x), len(xchecks)), "all match", all(xchecks) if xchecks else None),
            ("Type fidelity", "money NUMERIC(p,s) from PIC; no FLOAT; CHAR semantics preserved from DDL", "no float", "FLOAT" not in "\n".join(parts).upper()),
            ("Keys from definitions, not inference", "IDCAMS KEYS / DDL PKs / DBD sequence fields via store-map.json", "all keyed", all(s.get("primary_key") for s in migrated if s["kind"].startswith("vsam-ksds"))),
            ("Production extracts", "supplied" if SM.get("production_extracts_supplied") else "**not supplied** — sample data only", "present before the first migration wave", bool(SM.get("production_extracts_supplied")))]
    arts = [os.path.join(ws.D5, f) for f in ("store-map.json", "schema.sql", "mapping.json", "fidelity-report.md")] + [os.path.join(MIG, f) for f in ("plan.md", "decode_all.sh", "load.sql", "reconcile.sql")]; mani, mh = manifest(ws, arts)
    least = [("Nullability of %d columns marked nullable" % sum(1 for s in mapping["stores"] if isinstance(s.get("fields"), list) for c in s["fields"] if c.get("nullable")), "medium", "inferred from blanks in sample rows", "DBA review against business meaning")]
    least += [("%s layout" % f["store"], "medium", "no sample data", "production extract") for f in fidelity if not f["sample"]]
    pack = render_pack(ws, "G4", "countersign that the target schema, the field-level mapping and the migration/reconciliation method are sound, on the evidence below.",
                       "**Data Architect:** the schema shape — one schema per context, VSAM → tables with IDCAMS keys, IMS hierarchy → parent/child with the parent key materialised, DB2 DDL converted with CHAR semantics kept. **DBA:** the nullability inferences in `mapping.json`, DATE conversions with `_raw` staging, the index set, the load/promote procedure. **Compliance:** sensitive columns (credentials, PANs, national ids) and retention of the migration audit table.",
                       "A decoding, sign or scale error approved here reaches Phase 7 as a *logic* defect and the team debugs the Java instead of the data. A wrong nullability turns 'unknown' into zero and changes every sum. A missed key makes the golden master compare the wrong rows. Data cannot be re-derived from the specification.",
                       least, ["Production volumes and content — %s." % ("supplied" if SM.get("production_extracts_supplied") else "only samples were available"), "Whether any FILLER carries data in production."] + problems, evid, mani, mh,
                       "`store-map.json`: the confirmed store → copybook/key/schema map. `schema.sql`: %d CREATE TABLE statements across %d schemas. `mapping.json`: every migrated store field-by-field with offsets, types, nullability and sample observations. `fidelity-report.md`: the proof on the samples. `migration/`: decode, load, reconcile, plan." % (sum(1 for p in parts if "CREATE TABLE" in p), len(schemas)))
    write(os.path.join(ws.gate_dir("G4"), "review-pack.md"), pack); status = propose_gate(ws, "G4", mh, mani, evid)
    print("stores mapped %d (migrated %d) | sampled %d | round trip %d/%d/%d | problems %d | red rows %d | G4 %s %s" % (len(mapping["stores"]), len(migrated), len(sampled), rt_mig[0], rt_mig[1], rt_mig[2], len(problems), sum(1 for e in evid if e[3] is False), status, mh[:16]))
    for p in problems: print("  PROBLEM", p)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
