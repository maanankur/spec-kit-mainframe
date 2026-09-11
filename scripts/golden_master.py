#!/usr/bin/env python3
"""
golden_master.py -- golden-master equivalence: legacy outputs vs target exports,
typed field-by-field.

Record layouts come from 5-data/mapping.json (never re-typed here): a numeric
DISPLAY field is compared as a decimal, so a GnuCOBOL trailing sign and an IBM
overpunch are the same value; a field declared `runtime_fields` in the pair (set
from the run's clock) is an *explained* difference when both sides match the
declared pattern; text is compared byte for byte after trailing-blank strip.
Every difference is identical, explained, or unexplained -- 'close enough' is not a
category. Exit 0 only when nothing is unexplained and nothing is missing.

Config: target/ops/golden-master.json (templates/golden-master.json).
Outputs: target/ops/out/golden-master-report.{md,json}

Usage: golden_master.py --workspace <out-dir> [--config target/ops/golden-master.json]
"""
import argparse, io, os, re, sys
from decimal import Decimal, InvalidOperation
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import WS, NOW, write, jload, jdump

POS = "{ABCDEFGHI"; NEG = "}JKLMNOPQR"


def zoned(s):
    s = s.strip()
    if not s: return None
    last = s[-1]
    if last in "+-": neg, digits = last == "-", s[:-1]
    elif last in POS: neg, digits = False, s[:-1] + str(POS.index(last))
    elif last in NEG: neg, digits = True, s[:-1] + str(NEG.index(last))
    elif last.isdigit(): neg, digits = False, s
    else: return s
    try: v = Decimal(digits)
    except InvalidOperation: return s
    return -v if neg else v


def layout_from_mapping(mapping, store):
    m = next((s for s in mapping["stores"] if s["legacy"] == store or s.get("table") == store), None)
    if not m or not isinstance(m.get("fields"), list): return None, None
    lay = [(f["column"] or f["cobol"], f["offset"], f["length"], "zoned" if f["usage"] == "DISPLAY" and str(f["type"]).startswith(("NUMERIC", "BIGINT", "INTEGER", "SMALLINT")) else "text") for f in m["fields"]]
    return lay, m.get("primary_key") or []


def lines(p, width=None, raw=False):
    if not os.path.exists(p): return None
    if raw:
        b = io.open(p, "rb").read().decode("latin-1"); return [b[i:i + width] for i in range(0, len(b), width)]
    L = [l.rstrip("\r\n") for l in io.open(p, encoding="latin-1")]
    if width: L = [l.ljust(width)[:width] for l in L if l.strip()]
    return L


def compare_records(name, a, b, layout, keycols, runtime, patterns):
    res = dict(file=name, legacy_records=len(a), java_records=len(b), identical=0, explained=0, unexplained=0, details=[])
    keyf = [f for f in layout if f[0] in keycols] or layout[:1]
    key = lambda r: "".join(r[f[1]:f[1] + f[2]] for f in keyf)
    ka = {key(r): r for r in a}; kb = {key(r): r for r in b}
    for k in sorted(set(ka) | set(kb)):
        if k not in ka or k not in kb: res["unexplained"] += 1; res["details"].append("%s key %s only in %s" % (name, k.strip(), "legacy" if k in ka else "java")); continue
        for fname, off, ln, kind in layout:
            x, y = ka[k][off:off + ln], kb[k][off:off + ln]
            if x == y or (kind == "text" and x.rstrip() == y.rstrip()): res["identical"] += 1
            elif kind == "zoned" and zoned(x) == zoned(y) and not isinstance(zoned(x), str): res["identical"] += 1
            elif fname in runtime:
                pat = patterns.get(fname) or patterns.get("*")
                if (pat and re.fullmatch(pat, x.strip() or "?") and re.fullmatch(pat, y.strip() or "?")) or (not pat and x.strip() and y.strip()): res["explained"] += 1
                else: res["unexplained"] += 1; res["details"].append("%s %s.%s: runtime field shape differs: legacy %r != java %r" % (name, k.strip(), fname, x, y))
            else:
                res["unexplained"] += 1
                if len(res["details"]) < 25: res["details"].append("%s %s.%s: legacy %r != java %r" % (name, k.strip(), fname, x, y))
    return res


def compare_text(name, a, b, labelled, label_width):
    res = dict(file=name, legacy_lines=len(a), java_lines=len(b), identical=0, explained=0, unexplained=0, details=[])
    for i in range(max(len(a), len(b))):
        x = a[i].rstrip() if i < len(a) else None; y = b[i].rstrip() if i < len(b) else None
        if x == y: res["identical"] += 1; continue
        if labelled and x is not None and y is not None:
            mx = re.match(r"^(.{%d})(\S+)\s*$" % label_width, x); my = re.match(r"^(.{%d})(\S+)\s*$" % label_width, y)
            if mx and my and mx.group(1) == my.group(1) and not isinstance(zoned(mx.group(2)), (str, type(None))) and zoned(mx.group(2)) == zoned(my.group(2)): res["explained"] += 1; continue
        res["unexplained"] += 1
        if len(res["details"]) < 25: res["details"].append("%s line %d: legacy %r != java %r" % (name, i + 1, (x or "")[:110], (y or "")[:110]))
    return res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--config"); a = ap.parse_args(); ws = WS(a.workspace)
    cfg = jload(a.config or os.path.join(ws.T, "ops", "golden-master.json"))
    if not cfg: print("REFUSED: target/ops/golden-master.json missing (templates/golden-master.json)"); return 1
    mapping = jload(os.path.join(ws.D5, "mapping.json"), {"stores": []}); LEG = os.path.join(ws.ROOT, cfg.get("legacy_out", "target/legacy/out")); JAV = os.path.join(ws.ROOT, cfg.get("java_out", "target/ops/out/java"))
    noise = [re.compile(p) for p in cfg.get("noise_patterns", [r"^RC=\d+", r"^--- stderr", r"^libcob:"])]; out = []
    for p in cfg["pairs"]:
        lp, jp = os.path.join(LEG, p["legacy"]), os.path.join(JAV, p["java"])
        if p.get("kind", "records") == "records":
            lay, pk = layout_from_mapping(mapping, p["store"]) if p.get("store") else (None, None)
            if p.get("layout"): lay = [tuple(x) for x in p["layout"]]
            if not lay: out.append(dict(file=p["label"], missing="layout for store %r not in mapping.json" % p.get("store"), use_cases=p.get("use_cases", []))); continue
            width = p.get("width") or (max(f[1] + f[2] for f in lay)); a_ = lines(lp, width, raw=p.get("legacy_raw", False)); b_ = lines(jp, width, raw=p.get("java_raw", False))
            if a_ is None or b_ is None: out.append(dict(file=p["label"], missing="legacy" if a_ is None else "java", use_cases=p.get("use_cases", []))); continue
            r = compare_records(p["label"], a_, b_, lay, p.get("key") or pk, set(p.get("runtime_fields", [])), cfg.get("runtime_patterns", {}))
        else:
            a_ = lines(lp); b_ = lines(jp)
            if a_ is None or b_ is None: out.append(dict(file=p["label"], missing="legacy" if a_ is None else "java", use_cases=p.get("use_cases", []))); continue
            a_ = [l for l in a_ if not any(n.match(l) for n in noise)]; b_ = [l for l in b_ if not any(n.match(l) for n in noise)]
            while a_ and not a_[-1].strip(): a_.pop()
            while b_ and not b_[-1].strip(): b_.pop()
            r = compare_text(p["label"], a_, b_, p.get("labelled_values", False), p.get("label_width", 25))
        r["use_cases"] = p.get("use_cases", []); out.append(r)
    ti = sum(r.get("identical", 0) for r in out); te = sum(r.get("explained", 0) for r in out); tu = sum(r.get("unexplained", 0) for r in out); missing = [r for r in out if "missing" in r]
    R = ["# Golden-master equivalence — legacy vs target\n", "Run %s by `golden_master.py`. Typed comparison: numeric DISPLAY fields as decimals (layouts from `5-data/mapping.json`), declared run-time fields masked and counted as explained, text byte-for-byte after trailing-blank strip.\n" % NOW,
         "| Artifact | Legacy | Java | Identical | Explained | **Unexplained** | Use cases |", "|---|---|---|---|---|---|---|"]
    for r in out:
        if "missing" in r: R.append("| %s | — | — | — | — | **missing: %s** | %s |" % (r["file"], r["missing"], ", ".join(r.get("use_cases", [])))); continue
        R.append("| %s | %s | %s | %d | %d | **%d** | %s |" % (r["file"], r.get("legacy_records", r.get("legacy_lines")), r.get("java_records", r.get("java_lines")), r["identical"], r["explained"], r["unexplained"], ", ".join(r.get("use_cases", []))))
    R.append("\n**Totals:** %d identical · %d explained · **%d unexplained** · %d missing\n" % (ti, te, tu, len(missing)))
    det = [d for r in out for d in r.get("details", [])]
    if det: R += ["## Unexplained differences (first %d)\n" % len(det)] + ["- " + d for d in det]
    R += ["\n## Explanation categories\n"] + ["- **%s** — %s" % kv for kv in cfg.get("explanations", {"runtime field": "value set from the run's clock; the shape is compared and identical", "sign representation": "GnuCOBOL prints a trailing sign where IBM prints an overpunch; both decode to the same decimal"}).items()]
    os.makedirs(os.path.join(ws.T, "ops", "out"), exist_ok=True); write(os.path.join(ws.T, "ops", "out", "golden-master-report.md"), "\n".join(R) + "\n"); jdump(os.path.join(ws.T, "ops", "out", "golden-master-report.json"), out)
    print("identical %d | explained %d | UNEXPLAINED %d | missing %d" % (ti, te, tu, len(missing)))
    for d in det[:15]: print("  ", d)
    return 0 if tu == 0 and not missing else 1


if __name__ == "__main__":
    sys.exit(main())
