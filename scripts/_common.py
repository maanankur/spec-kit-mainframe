"""
_common.py -- shared helpers for the plugin's phase generators.

Workspace layout, config access, hashing, gate manifests, the review-pack
skeleton (templates/gate-review.md) and the state.json rules that every
generator must obey:

  * an approved gate whose artifacts change is marked `invalidated`, never
    silently re-proposed or overwritten (rule 6 in rules/00-non-negotiables.md);
  * a gate is `proposed` bound to the manifest hash of its artifacts;
  * evidence gates carry `red_items`; a red row can only be waived (gate_decide.py).
"""
import datetime, hashlib, json, os, re

NOW = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
GATE_TITLES = {"G1": "Business understanding", "G2": "Domain boundaries", "G3": "Architecture & waves", "G4": "Data model & migration",
               "G5": "Build accepted", "G6": "Equivalence accepted", "G7": "Go-live"}
GATE_KIND = {"G1": "judgement", "G2": "judgement", "G3": "judgement", "G4": "evidence", "G5": "evidence", "G6": "evidence", "G7": "operational"}


class WS:
    """Paths of one modernization workspace."""
    def __init__(self, workspace):
        self.ROOT = os.path.abspath(workspace)
        self.M = os.path.join(self.ROOT, "modernization")
        self.INTAKE = os.path.join(self.M, "0-intake"); self.DISC = os.path.join(self.M, "1-discovery"); self.FM = os.path.join(self.DISC, "fieldmaps")
        self.SPEC = os.path.join(self.M, "2-specification"); self.FRAG = os.path.join(self.SPEC, "_fragments")
        self.D3 = os.path.join(self.M, "3-domain"); self.A4 = os.path.join(self.M, "4-architecture"); self.D5 = os.path.join(self.M, "5-data")
        self.GOV = os.path.join(self.M, "governance"); self.GATES = os.path.join(self.GOV, "gates"); self.WAIVERS = os.path.join(self.GOV, "waivers")
        self.TOOLS = os.path.join(self.M, "tools"); self.T = os.path.join(self.ROOT, "target"); self.STATE = os.path.join(self.M, "state.json")
        self.cfg = load_yaml(os.path.join(self.M, "modernization.config.yaml"))
        self.source = self.cfg.get("project", {}).get("source_path") or ""
        self.project = self.cfg.get("project", {}).get("name") or os.path.basename(self.ROOT)

    def gate_dir(self, g): return os.path.join(self.GATES, g)
    def rel(self, p): return os.path.relpath(p, self.ROOT).replace(os.sep, "/")
    def approvers(self, g): return list(self.cfg.get("governance", {}).get("approvers", {}).get(g, []))
    def state(self): return jload(self.STATE, {})
    def save_state(self, st): st["last_checkpoint"] = NOW; write(self.STATE, json.dumps(st, indent=2))


# ------------------------------------------------------------------ io
def read(p, default=""):
    return open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else default

def write(p, s):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    open(p, "w", encoding="utf-8", newline="\n").write(s)

def jload(p, default=None):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default

def jdump(p, obj):
    write(p, json.dumps(obj, indent=1, ensure_ascii=False, default=str))

def jsonl(p):
    return [json.loads(l) for l in read(p).splitlines() if l.strip()]

def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()

def manifest(ws, paths):
    m = [dict(path=ws.rel(p), sha256=sha(p)) for p in paths if os.path.exists(p)]
    return m, hashlib.sha256(json.dumps(m, sort_keys=True).encode()).hexdigest()

def md(s):
    """Escape a value for a markdown table cell."""
    return str(s).replace("|", "/").replace("\n", " ")


# ------------------------------------------------------------------ yaml (the config subset)
def _scalar(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"): return [_scalar(x) for x in v[1:-1].split(",") if x.strip()]
    if v.startswith("{") and v.endswith("}"):
        out = {}
        for part in v[1:-1].split(","):
            if ":" in part: k, x = part.split(":", 1); out[k.strip()] = _scalar(x)
        return out
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"": return v[1:-1]
    if v.lower() in ("true", "false"): return v.lower() == "true"
    if re.fullmatch(r"-?\d+", v): return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v): return float(v)
    return v

def load_yaml(path):
    """Indentation-based reader for the plugin's config/profile files (nested maps, `- item` lists, inline lists/maps, scalars). Not a full YAML parser."""
    lines = []
    for raw in read(path).splitlines():
        if raw.lstrip().startswith("#") or not raw.strip(): continue
        body = raw.split(" #")[0].rstrip(); lines.append((len(raw) - len(raw.lstrip()), body.strip()))
    root = {}; stack = [(-1, root)]
    for i, (ind, body) in enumerate(lines):
        while len(stack) > 1 and stack[-1][0] >= ind: stack.pop()
        parent = stack[-1][1]
        if body.startswith("- "):
            if isinstance(parent, list): parent.append(_scalar(body[2:]))
            continue
        if ":" not in body: continue
        k, v = body.split(":", 1); k = k.strip()
        if v.strip():
            if isinstance(parent, dict): parent[k] = _scalar(v)
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        child = [] if nxt and nxt[0] > ind and nxt[1].startswith("- ") else {}
        if isinstance(parent, dict): parent[k] = child
        stack.append((ind, child))
    return root


# ------------------------------------------------------------------ gates
def render_pack(ws, gate, decision_q, roles_q, wrong, least, could_not, evidence, mani, mh, artifacts_note, kind=None):
    """The review pack in the shape of templates/gate-review.md. `evidence` rows: (check, result, threshold, green|None)."""
    kind = kind or GATE_KIND[gate]; reds = [e for e in evidence if e[3] is False]
    L = ["# Gate %s - %s%s\n" % (gate, GATE_TITLES[gate], " (evidence gate)" if kind == "evidence" else ""),
         "**Decision requested:** %s" % decision_q,
         "**Approvers required:** %s (quorum: %s)" % (", ".join(ws.approvers(gate)), ws.cfg.get("governance", {}).get("quorum", "all")),
         "**Artifacts under review:** %d files, manifest hash `%s`\n" % (len(mani), mh), "---\n",
         "## 1. What you are being asked to decide\n", roles_q + "\n", "## 2. What happens if this decision is wrong\n", wrong + "\n",
         "## 3. What we are least sure about\n", "| Item | Confidence | Why it is uncertain | What would resolve it |", "|------|-----------|---------------------|----------------------|"]
    L += ["| %s | %s | %s | %s |" % tuple(md(x) for x in row) for row in least] or ["| — | | | |"]
    L += ["\n## 4. What we could not determine\n"] + ["- " + c for c in could_not] + ["\n## 5. Evidence\n", "| Check | Result | Threshold | |", "|---|---|---|---|"]
    L += ["| %s | %s | %s | %s |" % (md(c), md(r), md(t), "🟢" if g else ("🔴" if g is False else "—")) for c, r, t, g in evidence]
    if kind in ("evidence", "operational"):
        L.append("\n**Red rows:** %d. %s\n" % (len(reds), "A red evidence row cannot be approved — only waived with a named owner, a compensating control and an expiry (`gate_decide.py --decision waived`)." if reds else "None."))
    L += ["## 6. Summary of the artifacts\n"] + ["- `%s` — `%s`" % (m["path"], m["sha256"][:16]) for m in mani] + ["", artifacts_note, "\n---\n\n## Decision\n",
          "- [ ] Approved%s\n- [ ] Approved with conditions (list below, tracked to closure)\n- [ ] Rejected (reason below, injected into the re-run)%s\n" % (" (only if no red rows)" if kind != "judgement" else "", "\n- [ ] Waiver required (red evidence — owner, compensating control, expiry)" if kind != "judgement" else ""),
          "Conditions / reason:\n", "Signatures are recorded in `governance/gates/%s/decision-record.json` and bound to the manifest hash above. If any artifact changes, this approval is automatically void.\n" % gate]
    return "\n".join(L)


def propose_gate(ws, gate, mh, mani, evidence=None, extra=None):
    """Write manifest.json and move state.json's gate to `proposed` -- or `invalidated` if it was approved on different artifacts."""
    reds = sum(1 for e in (evidence or []) if e[3] is False)
    jdump(os.path.join(ws.gate_dir(gate), "manifest.json"), dict(gate=gate, generated_at=NOW, manifest_hash=mh, artifacts=mani,
          evidence=[dict(check=c, result=r, threshold=t, green=g) for c, r, t, g in (evidence or [])]))
    st = ws.state(); st.setdefault("gates", {}); prev = st["gates"].get(gate, {}); status = prev.get("status", "")
    if status.startswith("approved") or status == "waived":
        if prev.get("manifest_hash") == mh:
            return "unchanged (%s)" % status
        st["gates"][gate] = dict(status="invalidated", previous_decision=status, previous_manifest_hash=prev.get("manifest_hash"), decision_record=prev.get("decision_record"),
                                 invalidated_at=NOW, reason="artifacts regenerated; approval void by rule 6; delta re-proposed", reproposed_manifest_hash=mh, red_items=reds)
        ws.save_state(st); return "INVALIDATED previous %s (artifacts changed) -- re-decide with gate_decide.py" % status
    entry = dict(status="proposed", kind=GATE_KIND[gate], manifest_hash=mh, proposed_at=NOW, review_pack="modernization/governance/gates/%s/review-pack.md" % gate, red_items=reds)
    if extra: entry.update(extra)
    st["gates"][gate] = entry; ws.save_state(st)
    return "proposed"
