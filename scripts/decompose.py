#!/usr/bin/env python3
"""
decompose.py -- Phase 3: bounded contexts from the computed clusters, the CRUD
matrix, the rules' evidence and the recovered vocabulary.

The boundaries are judgement and live in 3-domain/contexts.json (written by the
domain-modeling agent from templates/contexts.json). Everything else -- which rules
fall into each context, cross-context reads, shared-write resolutions, unowned
stores, the glossary, the map -- is computed from the phase-1/2 artifacts so it
cannot drift from them. Store identity comes from dependencies.json
(store_identity, resolved from JCL DSNs); contexts.json may add aliases.

Outputs: 3-domain/decomposition.json, context-map.md, glossary.md;
         governance/gates/G2/{review-pack.md,manifest.json}; state.json G2 = proposed.

Usage: decompose.py --workspace <out-dir>
"""
import argparse, collections, csv, glob, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import WS, NOW, read, write, jload, jdump, jsonl, manifest, md, render_pack, propose_gate


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); a = ap.parse_args(); ws = WS(a.workspace)
    J = jload(os.path.join(ws.D3, "contexts.json"))
    if not J: print("REFUSED: 3-domain/contexts.json missing -- the domain-modeling agent writes it from templates/contexts.json"); return 1
    CX = J["contexts"]; inv = jload(os.path.join(ws.DISC, "inventory.json")); dep = jload(os.path.join(ws.DISC, "dependencies.json"))
    rules = jsonl(os.path.join(ws.SPEC, "business-rules.jsonl")); programs = [c["name"] for c in inv["items"]["cobol"]]
    alias = {k: v["resolved_to"] for k, v in dep.get("store_identity", {}).items() if v.get("resolved_to")}; alias.update(J.get("store_aliases", {}))
    canon = lambda s: alias.get(s, s)
    prog2bc = {}
    errors = []
    for c in CX:
        for p in c["programs"]:
            if p not in programs: errors.append("%s lists unknown program %s" % (c["id"], p))
            if p in prog2bc: errors.append("%s assigned to both %s and %s" % (p, prog2bc[p], c["id"]))
            prog2bc[p] = c["id"]
    unassigned = sorted(set(programs) - set(prog2bc))
    rows = list(csv.reader(open(os.path.join(ws.DISC, "crud-matrix.csv"), encoding="utf-8"))); hdr = rows[0]
    writers, readers = collections.defaultdict(set), collections.defaultdict(set)
    for r in rows[1:]:
        st = canon(r[0])
        for j in range(4, len(r)):
            if r[j]:
                if any(ch in r[j] for ch in "CUD"): writers[st].add(hdr[j])
                if "R" in r[j] or not any(ch in r[j] for ch in "CUD"): readers[st].add(hdr[j])
    for r in rules:
        votes = collections.Counter(prog2bc.get(e.get("program", "")) for e in r["evidence"]); votes.pop(None, None)
        r["_bc"] = votes.most_common(1)[0][0] if votes else None
    unassigned_rules = [r["id"] for r in rules if not r["_bc"]]
    for c in CX:
        mine = [r for r in rules if r["_bc"] == c["id"]]
        c["rules"] = sorted(r["id"] for r in mine); c["rule_domains"] = sorted({r.get("domain", "") for r in mine})
        c["open_questions"] = sum(1 for r in mine if r.get("open_question")); c["suspected_defects"] = sum(1 for r in mine if r.get("suspected_defect"))
        owned = {canon(s) for s in c.get("owned_stores", [])}; c["owned_stores_canonical"] = sorted(owned)
        c["reads"] = sorted({st for st, ps in readers.items() if ps & set(c["programs"]) and st not in owned})
        c["writes_not_owned"] = sorted({st for st, ps in writers.items() if ps & set(c["programs"]) and st not in owned})
        c["shared_write_resolution"] = []
        for st in sorted(owned):
            for o in sorted({prog2bc.get(p, p) for p in writers.get(st, set())} - {c["id"]}):
                res = next((x.get("resolution") for x in J.get("shared_write_resolutions", []) if canon(x.get("store")) == st and x.get("writer") == o), None)
                c["shared_write_resolution"].append(dict(store=st, also_written_by=o, resolution=res or "%s owns %s; %s must issue a command through %s's interface instead of writing the store -- RESOLUTION NOT WRITTEN, decide at G2" % (c["id"], st, o, c["id"])))
    all_owned = {s for c in CX for s in c["owned_stores_canonical"]}
    unowned = sorted(st for st in set(writers) | set(readers) if st not in all_owned)
    owner_of = {s: c["id"] for c in CX for s in c["owned_stores_canonical"]}

    # glossary from the vocabulary tables
    terms = collections.OrderedDict(); prog_re = re.compile(r"\b(%s)\b" % "|".join(map(re.escape, sorted(programs, key=len, reverse=True)))) if programs else None
    for f in sorted(glob.glob(os.path.join(ws.FRAG, "WP*", "spec-section.md"))):
        wp = os.path.basename(os.path.dirname(f)); txt = read(f)
        for sec in re.finditer(r"### Vocabulary\n(.*?)(?=\n###|\n## |\Z)", txt, re.S):
            ctxt = txt[max(0, sec.start() - 4000):sec.end() + 4000]
            bc = collections.Counter(prog2bc.get(p) for p in (prog_re.findall(ctxt) if prog_re else [])); bc.pop(None, None)
            bc = bc.most_common(1)[0][0] if bc else "?"
            for line in sec.group(1).splitlines():
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 3 or cells[0].lower().startswith(("business term", "term", "---", ":--")) or set(cells[0]) <= set("-: "): continue
                term, legacy, meaning = cells[0], cells[1], cells[2]; key = term.lower()
                if key in terms:
                    if terms[key]["legacy"] != legacy: terms[key]["conflicts"].append((wp, legacy))
                    terms[key]["contexts"].add(bc)
                else: terms[key] = dict(term=term, legacy=legacy, meaning=meaning, contexts={bc}, source=wp, conflicts=[])
    names = {c["id"]: c["name"] for c in CX}; conflicts = sum(1 for t in terms.values() if t["conflicts"])
    G = ["# Glossary — ubiquitous language\n", "Built %s from the vocabulary tables of the specification work packages (%d distinct terms). Owning context = the context whose programs the source section describes. A term with **conflicts** is used for different legacy names in different places — findings for the domain SMEs at G2.\n" % (NOW, len(terms)),
         "| Business term | Legacy data name(s) | Meaning | Owning context |", "|---|---|---|---|"]
    for t in sorted(terms.values(), key=lambda x: x["term"].lower()):
        extra = (" **conflicts:** " + "; ".join("%s uses `%s`" % (w, l.strip("`")) for w, l in t["conflicts"])) if t["conflicts"] else ""
        G.append("| %s | `%s` | %s%s | %s |" % (md(t["term"]), md(t["legacy"]).strip("`"), md(t["meaning"]), extra, ", ".join(sorted(names.get(b, b) for b in t["contexts"]))))
    write(os.path.join(ws.D3, "glossary.md"), "\n".join(G) + "\n")

    dec = dict(generated_at=NOW, method="clusters + CRUD matrix + rule evidence; boundaries by judgement in contexts.json (rationale per context)", store_aliases=alias,
               contexts=CX, programs_unassigned=unassigned, rules_unassigned=unassigned_rules, stores_without_owner=unowned, validation_errors=errors,
               cross_context_reads=[dict(context=c["id"], reads=c["reads"]) for c in CX if c["reads"]], relationships=J.get("relationships", []), decisions=J.get("decisions", []))
    jdump(os.path.join(ws.D3, "decomposition.json"), dec)

    # context map
    nid = lambda i: i.replace("-", "")
    C = ["# Context map — %s\n" % ws.project, "Generated %s by `decompose.py`. Boundaries are judgement over the computed clusters (%d), the CRUD matrix (%d stores) and the %d rules' evidence; each context carries its confidence and rationale in `decomposition.json`.\n" % (NOW, len(dep.get("clusters", [])), len(rows) - 1, len(rules)),
         "## The contexts\n", "```mermaid", "flowchart LR"] + ['  %s["%s<br/>%s"]' % (nid(c["id"]), c["name"], c["id"]) for c in CX]
    edges = set()
    for c in CX:
        if c.get("kind") == "shared-kernel":
            for o in CX:
                if o is not c and o.get("kind") != "shared-kernel": edges.add('  %s -. shared kernel .-> %s' % (nid(c["id"]), nid(o["id"])))
        for st in c["reads"]:
            o = owner_of.get(st)
            if o and o != c["id"]: edges.add('  %s -->|"reads %s"| %s' % (nid(c["id"]), st, nid(o)))
        for s in c["shared_write_resolution"]: edges.add('  %s -->|"command on %s"| %s' % (nid(s["also_written_by"]), s["store"], nid(c["id"])))
    C += sorted(edges) + ["```\n", "Solid arrows: downstream depends on upstream (reads or commands). Dotted: shared kernel.\n", "## Relationship types\n", "| Upstream → downstream | Type | Mechanism today | Mechanism in target |", "|---|---|---|---|"]
    C += ["| %s | %s | %s | %s |" % (md(r.get("pair", "")), md(r.get("type", "")), md(r.get("today", "")), md(r.get("target", ""))) for r in J.get("relationships", [])] or ["| _none written in contexts.json_ | | | |"]
    C.append("\n## Per context\n")
    for c in CX:
        C += ["### %s — %s (%s, confidence **%s**)\n" % (c["id"], c["name"], c.get("kind", "domain"), c.get("confidence", "?")), c.get("purpose", "") + "\n", "- **Programs:** %s" % ", ".join(c["programs"]),
              "- **Owned stores:** %s" % (", ".join(c["owned_stores_canonical"]) or "—"), "- **Reads (other contexts' stores):** %s" % (", ".join(c["reads"]) or "—"),
              "- **Aggregates:** %s" % ("; ".join("%s [%s]" % (x.get("root"), x.get("identity")) for x in c.get("aggregates", [])) or "—"),
              "- **Rules:** %d (%s) · open questions %d · suspected defects %d" % (len(c["rules"]), ", ".join(c["rule_domains"]), c["open_questions"], c["suspected_defects"]),
              "- **Events out / in:** %s / %s" % (", ".join(c.get("events_out", [])) or "—", ", ".join(c.get("events_in", [])) or "—")]
        C += ["- **Shared write resolved:** `%s` also written by %s → %s" % (s["store"], s["also_written_by"], s["resolution"]) for s in c["shared_write_resolution"]]
        if c["writes_not_owned"]: C.append("- **Writes stores it does not own:** %s (each needs a resolution on the owner's side)" % ", ".join(c["writes_not_owned"]))
        C.append("- **Why this boundary:** %s\n" % c.get("rationale", "_no rationale written_"))
    C += ["## Stores with no owning context\n", ("None." if not unowned else "\n".join("- `%s`" % u for u in unowned)) + "\n", "## Programs not assigned to any context\n", ("None." if not unassigned else ", ".join(unassigned)) + "\n",
          "## Decisions for G2\n"] + ["%d. %s" % (i, d) for i, d in enumerate(J.get("decisions", []), 1)] + ["%d. **Glossary conflicts** — %d terms used for different legacy names across packages; the SMEs pick the name." % (len(J.get("decisions", [])) + 1, conflicts)]
    write(os.path.join(ws.D3, "context-map.md"), "\n".join(C) + "\n")

    arts = [os.path.join(ws.D3, f) for f in ("contexts.json", "decomposition.json", "context-map.md", "glossary.md")]; mani, mh = manifest(ws, arts)
    unresolved = sum(1 for c in CX for s in c["shared_write_resolution"] if "NOT WRITTEN" in s["resolution"])
    least = [("%s %s" % (c["id"], c["name"]), c.get("confidence", "?"), c.get("rationale", ""), "SME/PO decision at this gate") for c in CX if c.get("confidence") != "high"]
    evid = [("Every program in exactly one context", "%d/%d assigned%s" % (len(prog2bc), len(programs), ("; unassigned: " + ", ".join(unassigned)) if unassigned else ""), "all", not unassigned and not errors),
            ("Every rule in exactly one context", "%d/%d" % (len(rules) - len(unassigned_rules), len(rules)), "all", not unassigned_rules),
            ("Owned stores with a second writer", "%d, %d without a written resolution" % (sum(len(c["shared_write_resolution"]) for c in CX), unresolved), "0 unresolved", unresolved == 0),
            ("Stores without an owner", str(len(unowned)), "0", not unowned), ("Glossary terms / conflicts", "%d / %d" % (len(terms), conflicts), "conflicts resolved by SMEs", None)]
    pack = render_pack(ws, "G2", "confirm that these %d bounded contexts are the right seams — every store has one owner, every rule and use case has a home, and the boundaries are how the business thinks — before they become module and package boundaries at G3." % len(CX),
                       "**Domain SMEs:** are these contexts how the business actually thinks, and is the glossary right (%d terms, %d with conflicting legacy names)? **Product Owner:** does every use case have a home, and do you agree with the decisions listed at the end of `context-map.md`? **Architect:** does every store have exactly one owner (stores without owner: %s), is every cross-context interaction named, and is this buildable as modules with enforced seams?" % (len(terms), conflicts, ", ".join(unowned) or "none"),
                       "A boundary approved here becomes a module or service boundary at G3 and a package boundary in every wave's code. Moving it after wave 2 is a rewrite of everything on both sides of it, plus a data-ownership migration. This is the last cheap decision in the programme.",
                       least, ["Use-case homes were assigned by rule evidence and program; G3 needs `2-specification/use-cases.jsonl` to derive endpoints.", "All G1 conditions remain open; this gate does not close them."] + errors, evid, mani, mh,
                       "`contexts.json`: the judgement (boundaries, rationale, decisions). `decomposition.json`: computed assignment of programs, rules, stores; shared-write resolutions; alias table. `context-map.md`: the map and per-context rationale. `glossary.md`: ubiquitous language with owning context.")
    write(os.path.join(ws.gate_dir("G2"), "review-pack.md"), pack); status = propose_gate(ws, "G2", mh, mani, evid)
    print("contexts %d | programs %d/%d | rules %d/%d | unowned stores %s | glossary %d terms (%d conflicts) | errors %d | G2 %s %s" % (len(CX), len(prog2bc), len(programs), len(rules) - len(unassigned_rules), len(rules), unowned or "none", len(terms), conflicts, len(errors), status, mh[:16]))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
