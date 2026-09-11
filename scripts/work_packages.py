#!/usr/bin/env python3
"""
work_packages.py -- plan the specification-recovery work packages from phase-1 facts.

Programs are grouped by data cluster and sub-application directory, then packed to a
target paragraph count per package, so nine parallel agents get balanced,
data-coherent slices. Each package receives a disjoint business-rule id range and a
written brief rendered from templates/work-package-brief.md. Nothing here is specific
to one application: everything comes from inventory.json, dependencies.json and the
paragraph skeleton.

Outputs: modernization/2-specification/_fragments/plan.json and WPn/brief.md

Usage: work_packages.py --workspace <out-dir> [--target-paragraphs 120] [--range-size 100]
"""
import argparse, json, os, re, sys


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--target-paragraphs", type=int, default=120)
    ap.add_argument("--range-size", type=int, default=100); ap.add_argument("--plugin-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    M = os.path.join(a.workspace, "modernization")
    inv = json.load(open(os.path.join(M, "1-discovery", "inventory.json"), encoding="utf-8"))
    dep = json.load(open(os.path.join(M, "1-discovery", "dependencies.json"), encoding="utf-8"))
    skel = json.load(open(os.path.join(M, "tools", "paragraph-skeleton.json"), encoding="utf-8"))
    cfg = open(os.path.join(M, "modernization.config.yaml"), encoding="utf-8").read()
    src = re.search(r"^\s*source_path:\s*(.+)$", cfg, re.M).group(1).strip()
    progs = {c["name"]: c for c in inv["items"]["cobol"]}
    cluster_of = {p: c["id"] for c in dep["clusters"] for p in c["programs"]}
    # group key: (sub-application directory, cluster) -- keeps a sub-app's programs together
    groups = {}
    for n, c in progs.items():
        subapp = os.path.relpath(os.path.dirname(os.path.dirname(c["path"])), src).replace("\\", "/")
        groups.setdefault((subapp, cluster_of.get(n, "C?")), []).append(n)
    # pack: fill packages up to the target; split a big group into its own packages by program size
    units = []
    for (subapp, cl), names in sorted(groups.items()):
        names.sort(key=lambda n: -skel.get(n, {}).get("paragraph_count", 0))
        cur, size = [], 0
        for n in names:
            pc = skel.get(n, {}).get("paragraph_count", 0)
            if cur and size + pc > a.target_paragraphs:
                units.append((subapp, cl, cur, size)); cur, size = [], 0
            cur.append(n); size += pc
        if cur: units.append((subapp, cl, cur, size))
    # merge small units (same sub-app) to avoid one-program packages
    merged = []
    for u in sorted(units, key=lambda x: (x[0], -x[3])):
        if merged and merged[-1][0] == u[0] and merged[-1][3] + u[3] <= a.target_paragraphs:
            m = merged.pop(); merged.append((m[0], m[1] + "+" + u[1], m[2] + u[2], m[3] + u[3]))
        else: merged.append(u)
    plan = {"generated_from": ["inventory.json", "dependencies.json", "paragraph-skeleton.json"], "target_paragraphs": a.target_paragraphs, "packages": []}
    lo = 1
    tpl = open(os.path.join(a.plugin_root, "templates", "work-package-brief.md"), encoding="utf-8").read()
    for i, (subapp, cl, names, size) in enumerate(merged, 1):
        wp = "WP%d" % i; hi = lo + a.range_size - 1
        stores = sorted({dep["store_identity"].get(x["store"], {}).get("resolved_to", x["store"]) for n in names for x in progs[n]["data_access"]})
        rows = "\n".join("| %s | %d | %d | %s | %s |" % (n, skel[n]["paragraph_count"], progs[n]["lines"], progs[n]["kind"], ", ".join(progs[n]["hazards"]) or "—") for n in names)
        copies = sorted({c for n in names for c in progs[n]["copies"]})
        plan["packages"].append({"id": wp, "sub_application": subapp, "clusters": cl, "programs": names, "paragraphs": size, "rule_range": [lo, hi], "stores": stores, "copybooks": copies})
        os.makedirs(os.path.join(M, "2-specification", "_fragments", wp), exist_ok=True)
        brief = (tpl.replace("{{WP}}", wp).replace("{{SUBAPP}}", subapp).replace("{{PROGRAM_ROWS}}", rows).replace("{{RANGE_LO}}", "BR-%04d" % lo).replace("{{RANGE_HI}}", "BR-%04d" % hi)
                 .replace("{{STORES}}", ", ".join(stores) or "—").replace("{{COPYBOOKS}}", ", ".join(copies) or "—").replace("{{SOURCE}}", src).replace("{{WORKSPACE}}", os.path.abspath(a.workspace).replace("\\", "/"))
                 .replace("{{PARAGRAPHS}}", str(size)))
        open(os.path.join(M, "2-specification", "_fragments", wp, "brief.md"), "w", encoding="utf-8", newline="\n").write(brief)
        lo = hi + 1
    json.dump(plan, open(os.path.join(M, "2-specification", "_fragments", "plan.json"), "w", encoding="utf-8"), indent=1)
    for p in plan["packages"]: print("%-5s %-38s %4d paras  %s  %s" % (p["id"], p["sub_application"][:38], p["paragraphs"], "BR-%04d..%04d" % tuple(p["rule_range"]), ", ".join(p["programs"])))
    print("%d packages, %d programs, %d paragraphs" % (len(plan["packages"]), sum(len(p["programs"]) for p in plan["packages"]), sum(p["paragraphs"] for p in plan["packages"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
