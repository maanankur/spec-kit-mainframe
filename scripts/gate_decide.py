#!/usr/bin/env python3
"""
gate_decide.py -- record a gate decision in the ledger and advance state.json.

The one way a gate changes status. Rules enforced here, not by convention:
  * the decision binds to the manifest hash the pack was proposed with; if the
    artifacts changed since, the decision is refused;
  * a judgement gate takes approved / approved-with-conditions / rejected;
  * an evidence gate with red rows cannot be approved -- only waived, and every red
    row needs an owner, a compensating control and an expiry (a waiver file each);
  * every required role signs (quorum from modernization.config.yaml);
  * --auto records the approver's standing instruction (blanket authorization) so
    an unattended run is still an audited run -- red rows are still waived, never
    approved, and the record says so.

Usage:
  gate_decide.py --workspace W --gate G1 --decision approved-with-conditions --by alice@x --condition "C1 ..." [--condition ...]
  gate_decide.py --workspace W --gate G4 --decision waived --by alice@x --control "Production extracts=re-run fidelity on extracts before wave 1" --expires 2026-12-31
  gate_decide.py --workspace W --gate G5 --auto --by alice@x --authorization "proceed on all gates without asking"   (approve if green, else waive with default controls)
  gate_decide.py --workspace W --check            (verify every approved gate's artifacts still hash to their manifest)
"""
import argparse, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import WS, NOW, jload, jdump, write, sha, GATE_KIND

DEFAULT_CONTROLS = {"SAST": "run SAST/SCA/secret scanning in the CI pipeline before any non-dev deployment", "Production": "re-run on production extracts and attach before the first migration wave",
                    "Online": "capture a request/response corpus from the legacy online region and replay it against the API before the wave cuts over", "readiness": "qa/prod profiles with a secrets manager, TLS, OIDC and a CI/CD pipeline before any environment beyond dev"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--gate"); ap.add_argument("--decision", choices=["approved", "approved-with-conditions", "rejected", "waived"])
    ap.add_argument("--by", help="approver id (email); signs every required role unless --role is given"); ap.add_argument("--role", action="append", default=[], help="role=id, repeatable")
    ap.add_argument("--condition", action="append", default=[]); ap.add_argument("--reason", default=""); ap.add_argument("--control", action="append", default=[], help="'<red check substring>=<compensating control>'")
    ap.add_argument("--expires", help="waiver expiry YYYY-MM-DD (default +30 days)"); ap.add_argument("--auto", action="store_true", help="unattended: approve green, waive red, under --authorization")
    ap.add_argument("--authorization", default=""); ap.add_argument("--check", action="store_true"); a = ap.parse_args(); ws = WS(a.workspace); st = ws.state()
    if a.check:
        bad = 0
        for g, e in sorted(st.get("gates", {}).items()):
            if not str(e.get("status", "")).startswith(("approved", "waived")): continue
            m = jload(os.path.join(ws.gate_dir(g), "manifest.json"), {})
            changed = [x["path"] for x in m.get("artifacts", []) if not os.path.exists(os.path.join(ws.ROOT, x["path"])) or sha(os.path.join(ws.ROOT, x["path"])) != x["sha256"]]
            print("%s %-25s manifest %s %s" % (g, e["status"], (m.get("manifest_hash") or "")[:16], "OK" if not changed and m.get("manifest_hash") == e.get("manifest_hash") else "CHANGED: " + ", ".join(changed)))
            bad += bool(changed)
        return 1 if bad else 0
    if not a.gate or not a.by: ap.error("--gate and --by are required")
    g = a.gate; mani = jload(os.path.join(ws.gate_dir(g), "manifest.json"))
    if not mani: print("REFUSED: %s has no manifest.json -- the phase generator proposes the gate first" % g); return 1
    entry = st.get("gates", {}).get(g, {})
    if entry.get("status") not in ("proposed", "invalidated", "rejected"): print("REFUSED: %s is %r, not proposed" % (g, entry.get("status"))); return 1
    changed = [x["path"] for x in mani["artifacts"] if not os.path.exists(os.path.join(ws.ROOT, x["path"])) or sha(os.path.join(ws.ROOT, x["path"])) != x["sha256"]]
    if changed: print("REFUSED: artifacts changed since the pack was proposed: %s -- regenerate the pack" % ", ".join(changed)); return 1
    reds = [e for e in mani.get("evidence", []) if e.get("green") is False]; kind = GATE_KIND[g]
    decision = a.decision
    if a.auto:
        decision = decision or ("waived" if reds else "approved-with-conditions")
        if not a.authorization: print("REFUSED: --auto needs --authorization <the approver's instruction, quoted>"); return 1
    if reds and kind == "judgement" and decision == "approved": print("REFUSED: %s has %d red check(s) (%s); approve with conditions that track them, or reject" % (g, len(reds), "; ".join(e["check"] for e in reds))); return 1
    if reds and kind == "judgement" and decision == "approved-with-conditions" and not a.condition: print("REFUSED: %s has red checks; --condition must name how each is tracked to closure" % g); return 1
    if reds and kind != "judgement" and decision in ("approved", "approved-with-conditions"): print("REFUSED: %s has %d red evidence row(s); a red row cannot be approved, only waived (--decision waived --control ...)" % (g, len(reds))); return 1
    if kind == "judgement" and decision == "waived": print("REFUSED: %s is a judgement gate; waivers apply to evidence rows only" % g); return 1
    roles = ws.approvers(g); signed = {r.split("=", 1)[0]: r.split("=", 1)[1] for r in a.role if "=" in r}
    if not signed: signed = {r: a.by for r in roles}
    missing = [r for r in roles if r not in signed]
    if missing and ws.cfg.get("governance", {}).get("quorum", "all") == "all": print("REFUSED: quorum 'all' -- roles not signed: %s" % ", ".join(missing)); return 1
    expires = a.expires or (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    controls = {c.split("=", 1)[0]: c.split("=", 1)[1] for c in a.control if "=" in c}
    waivers = []
    if decision == "waived":
        existing = [f for f in os.listdir(ws.WAIVERS) if f.startswith("WV-%s-" % g)] if os.path.isdir(ws.WAIVERS) else []
        for i, e in enumerate(reds, 1):
            ctl = next((v for k, v in controls.items() if k.lower() in e["check"].lower()), None) or (next((v for k, v in DEFAULT_CONTROLS.items() if k.lower() in e["check"].lower()), None) if a.auto else None)
            if not ctl and a.auto: ctl = "attach green evidence for '%s' (observed: %s; threshold: %s) before the next gate; the owner re-runs the pack and the waiver lapses" % (e["check"], e["result"], e["threshold"])
            if not ctl: print("REFUSED: red row %r has no compensating control (--control '<substring>=<control>')" % e["check"]); return 1
            wid = "WV-%s-%02d" % (g, len(existing) + i)
            wv = dict(waiver_id=wid, gate=g, red_item=e["check"], observed=e["result"], threshold=e["threshold"], risk="Evidence for '%s' is absent or red; the gate is passed on the remaining evidence." % e["check"], compensating_control=ctl, owner=a.by, expires=expires, created_at=NOW)
            jdump(os.path.join(ws.WAIVERS, wid + ".json"), wv); waivers.append(wv)
    sig = ("unsigned - recorded under the approver's standing instruction: %r" % a.authorization) if a.auto else "recorded by gate_decide.py on the approver's instruction"
    rec = dict(gate=g, title=mani.get("title", g), project=ws.project, kind=kind, artifact_manifest=mani["artifacts"], manifest_hash=mani["manifest_hash"], decision=decision, conditions=a.condition, reason=a.reason,
               evidence=mani.get("evidence", []), waivers=waivers, approvers=[dict(role=r, id=i, at=NOW, signature=sig) for r, i in signed.items()], proposed_by="pipeline:mainframe-modernization plugin", quorum=ws.cfg.get("governance", {}).get("quorum", "all"),
               quorum_met=not missing, blanket_authorization=(dict(granted_by=a.by, at=NOW, text=a.authorization, note="gates are still evidenced and recorded individually; red evidence is waived, not approved") if a.auto else None), created_at=NOW)
    jdump(os.path.join(ws.gate_dir(g), "decision-record.json"), rec)
    st.setdefault("gates", {})[g] = dict(status=decision, kind=kind, manifest_hash=mani["manifest_hash"], decision_record="modernization/governance/gates/%s/decision-record.json" % g, decided_at=NOW, open_conditions=len(a.condition), red_items=len(reds), waivers=[w["waiver_id"] for w in waivers])
    if a.auto: st["blanket_authorization"] = dict(granted_by=a.by, at=st.get("blanket_authorization", {}).get("at", NOW), text=a.authorization, applied_to=sorted(set(st.get("blanket_authorization", {}).get("applied_to", [])) | {g}))
    nxt = {"G1": "decompose", "G2": "architect", "G3": "data", "G4": "build", "G5": "verify", "G6": "cutover", "G7": "done"}
    if decision != "rejected":
        st["current_phase"] = nxt.get(g, st.get("current_phase")); st["phases_complete"] = sorted(set(st.get("phases_complete", [])) | {{"G1": "specification", "G2": "decomposition", "G3": "architecture", "G4": "data", "G5": "build", "G6": "verify", "G7": "cutover"}[g]})
    ws.save_state(st)
    print("%s %s | roles %s | conditions %d | red %d waived %d | next phase %s" % (g, decision, ", ".join(signed), len(a.condition), len(reds), len(waivers), st["current_phase"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
