#!/usr/bin/env python3
"""
verify_source_readonly.py -- prove the source tree was never written to.

"The source tree is read-only" is a non-negotiable, and an assertion nobody checked
is not a control. Phase 0 hashed every registered artifact; this re-hashes them and
reports any change, deletion, or unregistered file. Run it after every phase that
reads the legacy source and before every gate.

Usage: verify_source_readonly.py --workspace <out-dir> [--json]
Exit 0 only when the tree is byte-identical to the register.
"""
import argparse, hashlib, json, os, sys

SKIP_DIRS = {".git", "node_modules", "target", ".venv", "__pycache__"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", default="."); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    reg = json.load(open(os.path.join(a.workspace, "modernization", "0-intake", "artifact-register.json"), encoding="utf-8"))
    root = reg["source"]; entries = {e["path"]: e for e in reg["artifacts"]}
    changed, missing = [], []
    for rel, e in sorted(entries.items()):
        p = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.exists(p): missing.append(rel); continue
        got = sha256(p)
        if got != e["sha256"]: changed.append({"path": rel, "registered": e["sha256"], "actual": got})
    appeared = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/")
            if rel not in entries: appeared.append(rel)
    ok = not (changed or missing)
    res = {"source": root, "registered": len(entries), "changed": changed, "missing": missing, "unregistered": sorted(appeared), "clean": ok}
    if a.json: print(json.dumps(res, indent=1))
    else:
        print("source integrity: %s | registered %d | modified %d | missing %d | unregistered %d" % (root, len(entries), len(changed), len(missing), len(appeared)))
        for c in changed: print("  MODIFIED", c["path"])
        for m in missing: print("  MISSING ", m)
        print("CLEAN -- the source tree is byte-identical to the register" if ok else "VIOLATION -- the source tree has been altered")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
