#!/usr/bin/env python3
"""
modernize.py -- single entry point for the mainframe-modernization plugin.

One command takes a COBOL application and produces a modernization workspace
with Phase 0 (intake) and Phase 1 (discovery) already complete, then hands off
to the agent pipeline at the first point that actually needs human judgement.

    python modernize.py <cobol-app-path> [--out DIR] [options]

Output location
---------------
--out DIR   explicit destination.
default     a sibling of the COBOL application, in the SAME PARENT DIRECTORY,
            named "<app-name>-modernized".

              D:/Projects/carddemo            <- input  (never written to)
              D:/Projects/carddemo-modernized <- output (everything lands here)

The source tree is opened read-only. Nothing is ever written into it. That is
what makes this safe to point at a repository you do not own.

Layout created
--------------
    <out>/
      modernization/          the governed workspace (all phases, all gates)
      target/                 the delivered Java application
      MODERNIZE.md            what happened, and what to do next

Resumability
------------
Re-running against the same --out is safe and idempotent. Completed phases are
skipped unless --force is given; state.json is the resume point. The
deterministic phases produce byte-identical output on an unchanged source tree,
which is what makes the audit trail defensible.

Exit codes: 0 ok, 1 pipeline error, 2 usage error.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent

SOURCE_EXT = {
    "cobol": {".cbl", ".cob", ".cobol"},
    "copybook": {".cpy", ".copy"},
    "jcl": {".jcl", ".prc", ".proc"},
    "bms": {".bms"},
    "ddl": {".ddl", ".sql", ".dcl"},
    "ims": {".dbd", ".psb"},
    "assembler": {".asm", ".mac", ".maclib"},
    "csd": {".csd"},
    "scheduler": {".ca7", ".controlm", ".ctm", ".tws", ".zeke", ".opc"},
    "doc": {".md", ".txt", ".pdf", ".docx"},
}

PHASES = ["intake", "discovery", "specification", "domain", "architecture",
          "data", "build", "verify", "cutover", "done"]

# ---------------------------------------------------------------- utilities


# Windows consoles default to cp1252 and will crash on anything else. Console
# output stays ASCII; files are always written UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, OSError):
    pass


def log(msg: str = "") -> None:
    print(msg, flush=True)


def rule(title: str = "") -> None:
    log()
    log(f"-- {title} " + "-" * max(0, 62 - len(title)) if title else "-" * 66)


def die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[valid-type]
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_script(name: str, args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """Run one of the plugin's deterministic scripts."""
    script = HERE / name
    if not script.exists():
        return 127, f"missing script: {script}"
    cmd = [sys.executable, str(script), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# ---------------------------------------------------------------- detection


def classify_tree(src: Path) -> dict:
    """Read-only census of the source tree, by extension."""
    counts: dict[str, int] = {k: 0 for k in SOURCE_EXT}
    counts["other"] = 0
    files: dict[str, list[Path]] = {k: [] for k in SOURCE_EXT}
    datasets: list[Path] = []
    total_bytes = 0

    for root, dirs, names in os.walk(src):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__",
                                                "modernization", "target", ".venv"}]
        rootp = Path(root)
        in_data_dir = any(part.lower() in {"data", "datasets", "testdata"}
                          for part in rootp.parts)
        for n in names:
            p = rootp / n
            try:
                total_bytes += p.stat().st_size
            except OSError:
                continue
            ext = p.suffix.lower()
            placed = False
            for kind, exts in SOURCE_EXT.items():
                if ext in exts:
                    counts[kind] += 1
                    files[kind].append(p)
                    placed = True
                    break
            if not placed:
                counts["other"] += 1
                # datasets: no useful extension, sitting in a data directory,
                # or a classic MVS-style dotted dataset name
                if in_data_dir or re.match(r"^[A-Z0-9]+(\.[A-Z0-9#@$]+){2,}$", n):
                    datasets.append(p)
    return {"counts": counts, "files": files, "datasets": datasets,
            "total_bytes": total_bytes}


def detect_platform(files: dict[str, list[Path]], datasets: list[Path]) -> dict:
    """Infer source-platform characteristics so the config is pre-filled."""
    facts = {"tp_monitor": "none", "databases": [], "messaging": "none",
             "scheduler": "none",
             "charset": "cp037", "dialect": "ibm-enterprise-cobol",
             "has_ebcdic_datasets": False}

    sample = files["cobol"][:200]
    blob = ""
    for p in sample:
        try:
            blob += p.read_text(errors="ignore")[:120_000].upper()
        except OSError:
            continue

    if "EXEC CICS" in blob:
        facts["tp_monitor"] = "cics"
    if "EXEC SQL" in blob or files["ddl"]:
        facts["databases"].append("db2")
    if "CBLTDLI" in blob or files["ims"]:
        facts["databases"].append("ims")
    if re.search(r"\bSELECT\b[^.]{0,200}\bORGANIZATION\s+IS\s+INDEXED", blob) or \
       re.search(r"\bVSAM\b", blob):
        facts["databases"].append("vsam")
    if "MQPUT" in blob or "MQGET" in blob or "MQOPEN" in blob:
        facts["messaging"] = "ibm-mq"

    sched = files.get("scheduler", [])
    if sched:
        exts = {p.suffix.lower() for p in sched}
        names = []
        if ".ca7" in exts: names.append("ca7")
        if exts & {".controlm", ".ctm"}: names.append("control-m")
        if ".tws" in exts: names.append("tws")
        if ".zeke" in exts: names.append("zeke")
        if ".opc" in exts: names.append("opc")
        facts["scheduler"] = ", ".join(names) or "unknown"

    for d in datasets:
        if "EBCDIC" in str(d).upper():
            facts["has_ebcdic_datasets"] = True
            break
    if not facts["has_ebcdic_datasets"] and datasets:
        facts["charset"] = "ascii"
    return facts


# ---------------------------------------------------------------- workspace


WORKSPACE_DIRS = [
    "modernization/graph",
    "modernization/0-intake",
    "modernization/1-discovery/fieldmaps",
    "modernization/2-specification/use-cases",
    "modernization/3-domain",
    "modernization/4-architecture/adr",
    "modernization/5-data/migration",
    "modernization/6-build/waves",
    "modernization/7-verify/waves",
    "modernization/8-deploy",
    "modernization/governance/gates",
    "modernization/governance/waivers",
    "modernization/governance/audit",
    "target",
]


def make_workspace(out: Path) -> None:
    for d in WORKSPACE_DIRS:
        (out / d).mkdir(parents=True, exist_ok=True)
    for g in range(1, 8):
        (out / f"modernization/governance/gates/G{g}").mkdir(parents=True, exist_ok=True)


def write_config(out: Path, src: Path, args, facts: dict) -> Path:
    cfg = out / "modernization" / "modernization.config.yaml"
    if cfg.exists() and not args.force:
        return cfg
    dbs = facts["databases"] or ["none"]
    cfg.write_text(f"""# Generated by modernize.py on {now()}
# Review before Gate 1. Detected values are a starting point, not a verdict.
project:
  name: {src.name}
  industry: {args.industry}
  source_path: {src.as_posix()}
  output_path: {out.as_posix()}

source:
  dialect: {facts['dialect']}
  charset: {facts['charset']}
  tp_monitor: {facts['tp_monitor']}
  databases: [{', '.join(dbs)}]
  messaging: {facts['messaging']}
  scheduler: {facts.get('scheduler', 'none')}

target:
  profile: {args.profile}
  java: "21"
  framework: spring-boot-3
  database: {args.database}
  ui: {args.ui}
  cloud: {args.cloud}

governance:
  gates: [G1, G2, G3, G4, G5, G6, G7]
  quorum: all
  approvers:
    G1: [business-analyst, architect, product-owner]
    G2: [architect, product-owner, domain-sme]
    G3: [chief-architect, product-owner, ops-lead]
    G4: [data-architect, dba, compliance]
    G5: [tech-lead, security]
    G6: [product-owner, qa-lead, business-analyst]
    G7: [change-advisory-board, ops, business-owner]

thresholds:
  trace_coverage: 100
  equivalence_confidence: 0.85
  max_concurrent_waves: 3
  confidence_floor: {{ spec: 0.7, architecture: 0.8 }}

strategy:
  behaviour_preserving: strict
  coexistence: strangler
""", encoding="utf-8")
    return cfg


def load_state(out: Path) -> dict:
    p = out / "modernization" / "state.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_state(out: Path, state: dict) -> None:
    state["last_checkpoint"] = now()
    (out / "modernization" / "state.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- phases


def phase_intake(src: Path, out: Path, census: dict, facts: dict) -> dict:
    """Phase 0 -- artifact register with checksums, and the gap list."""
    register = []
    for kind, paths in census["files"].items():
        for p in paths:
            try:
                register.append({
                    "path": p.relative_to(src).as_posix(),
                    "kind": kind,
                    "bytes": p.stat().st_size,
                    "sha256": sha256_file(p),
                })
            except (OSError, ValueError):
                continue
    for p in census["datasets"]:
        try:
            register.append({
                "path": p.relative_to(src).as_posix(),
                "kind": "dataset",
                "bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            })
        except (OSError, ValueError):
            continue

    reg_path = out / "modernization/0-intake/artifact-register.json"
    reg_path.write_text(json.dumps(
        {"generated_at": now(), "source": src.as_posix(),
         "detected": facts, "artifacts": register}, indent=2), encoding="utf-8")

    # The gap list is the most useful thing this phase produces: it names the
    # inputs the repository does not contain but the programme cannot succeed
    # without. Absence is a finding, not a silence.
    gaps = []
    if not census["datasets"]:
        gaps.append(("production datasets (masked)", "critical",
                     "no golden master is possible; equivalence becomes an opinion"))
    if not census["files"]["doc"]:
        gaps.append(("release notes / user manuals / functional specs", "high",
                     "spec recovery loses its corroborating sources"))
    gaps.append(("SMF / CICS execution statistics", "high",
                 "the only way to know what actually runs; dead code is 20-40% typically"))
    gaps.append(("batch window timings", "high",
                 "your performance baseline - capture it before anything changes"))
    gaps.append(("RACF / ACF2 / CSD exports", "medium",
                 "the real authorization model; inventing one is a compliance finding"))
    gaps.append(("abend and restart runbooks", "medium",
                 "the operational behaviour nobody documented and everybody depends on"))

    lines = ["# Intake gap list", "",
             f"Generated {now()} from `{src.as_posix()}`.", "",
             "These inputs are not in the repository. Chase them now - they have the",
             "longest lead time, and Gate 1 is weaker without them.", "",
             "| Missing input | Severity | Consequence |",
             "|---------------|----------|-------------|"]
    for name, sev, why in gaps:
        lines.append(f"| {name} | **{sev}** | {why} |")
    (out / "modernization/0-intake/gap-list.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    return {"artifacts": len(register), "gaps": len(gaps)}


def phase_discovery(src: Path, out: Path, census: dict) -> dict:
    """Phase 1 -- deterministic inventory, dependency graph, field maps."""
    disc = out / "modernization/1-discovery"
    results: dict = {}

    rc, o = run_script("inventory.py", [str(src), "--out", str(disc / "inventory.json"), "--print"])
    results["inventory"] = {"rc": rc, "output": o}
    if rc != 0:
        return results
    log(o.rstrip())

    rc, o = run_script("depgraph.py", ["--inventory", str(disc / "inventory.json"),
                                       "--out-dir", str(disc), "--print"])
    results["depgraph"] = {"rc": rc, "output": o}
    log(o.rstrip())

    copybooks = [str(p) for p in census["files"]["copybook"]]
    if copybooks:
        rc, o = run_script("copybook_parse.py", copybooks + ["--out", str(disc / "fieldmaps")])
        parsed = len(list((disc / "fieldmaps").glob("*.fieldmap.json")))
        results["copybooks"] = {"rc": rc, "parsed": parsed, "requested": len(copybooks)}
        log(f"  field maps parsed        {parsed}/{len(copybooks)}")

    if census["datasets"]:
        ds = [{"path": str(p.relative_to(src).as_posix()), "bytes": p.stat().st_size}
              for p in census["datasets"]]
        (disc / "datasets.json").write_text(json.dumps(
            {"generated_at": now(), "count": len(ds), "datasets": ds}, indent=2),
            encoding="utf-8")
        log(f"  datasets registered      {len(ds)}  (golden-master candidates)")
        results["datasets"] = len(ds)

    # Prepare phase 2: the authoritative paragraph list (same parser as the
    # traceability gate) and the work-package plan with per-package briefs.
    # Deterministic and agent-free, so it belongs here, not in the agent loop.
    rc, o = run_script("paragraph_skeleton.py", ["--source", str(src), "--out", str(out / "modernization/tools/paragraph-skeleton.json")])
    results["skeleton"] = {"rc": rc, "output": o}
    log("  " + o.strip().splitlines()[-1] if o.strip() else "  paragraph skeleton: no output")
    rc, o = run_script("work_packages.py", ["--workspace", str(out)])
    results["work_packages"] = {"rc": rc, "output": o}
    if rc == 0 and o.strip():
        log("  " + o.strip().splitlines()[-1] + "  (briefs in 2-specification/_fragments/WP*/brief.md)")
    else:
        log("  work-package planning failed:\n" + o[-1500:])
    return results


def write_handoff(out: Path, src: Path, census: dict, facts: dict,
                  intake: dict, disc: dict, args) -> None:
    inv = {}
    p = out / "modernization/1-discovery/inventory.json"
    if p.exists():
        try:
            inv = json.loads(p.read_text(encoding="utf-8")).get("summary", {})
        except (json.JSONDecodeError, OSError):
            pass

    c = census["counts"]
    md = f"""# Modernization workspace — {src.name}

Created {now()} by `modernize.py`.

| | |
|---|---|
| Source (read-only) | `{src.as_posix()}` |
| Output | `{out.as_posix()}` |
| Target profile | {args.profile} |
| Compliance pack | {args.industry} |
| Detected platform | {facts['tp_monitor']} · {', '.join(facts['databases']) or 'no database'} · {facts['messaging']} · {facts['charset']} |

## What is already done

Phases 0 and 1 ran deterministically — no model was involved, and re-running on
an unchanged source tree produces byte-identical output.

| Artifact | Location |
|----------|----------|
| Artifact register ({intake['artifacts']} files, hashed) | `modernization/0-intake/artifact-register.json` |
| **Gap list — read this first** | `modernization/0-intake/gap-list.md` |
| Inventory | `modernization/1-discovery/inventory.json` |
| Dependency graph + CRUD matrix | `modernization/1-discovery/dependencies.json`, `crud-matrix.csv` |
| Copybook field maps | `modernization/1-discovery/fieldmaps/` |
| Dataset register | `modernization/1-discovery/datasets.json` |

Source census: {c['cobol']} COBOL · {c['copybook']} copybooks · {c['jcl']} JCL ·
{c['bms']} BMS · {c['ddl']} DDL/DCL · {c['ims']} IMS · {c['assembler']} assembler ·
{c.get('scheduler', 0)} scheduler exports ·
{len(census['datasets'])} datasets.

## What happens next

Phase 2 is specification recovery, and it needs judgement. Open Claude Code in
this directory and run:

```
/modernize
```

It reads `modernization/state.json`, resumes at Phase 2, and stops at **Gate 1**
with a review pack for the Business Analyst, Architect and Product Owner.

Nothing past a gate happens without a recorded human decision.

## Ground rules in force

1. The source tree is never written to.
2. Java is generated from the approved specification, never transliterated from COBOL.
3. Facts a parser can compute are never inferred.
4. Every business rule links to its source paragraphs, or it cannot be written.
5. A red evidence gate cannot be approved — only waived, with an expiry.
"""
    (out / "MODERNIZE.md").write_text(md, encoding="utf-8")


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="modernize.py",
        description="One command: COBOL application in, governed modernization workspace out.")
    ap.add_argument("source", help="path to the COBOL application (read-only)")
    ap.add_argument("out_positional", nargs="?", default=None, metavar="output-path",
                    help="output directory (same as --out)")
    ap.add_argument("--out", "-o", default=None,
                    help="output directory (default: <source>-modernized, "
                         "as a sibling in the same parent directory)")
    ap.add_argument("--profile", default="spring-postgres-react-aws")
    ap.add_argument("--industry", default="banking",
                    choices=["banking", "insurance", "telecom", "retail", "government", "none"])
    ap.add_argument("--database", default="postgresql",
                    choices=["postgresql", "oracle", "sqlserver", "mysql"])
    ap.add_argument("--ui", default="react", choices=["react", "angular", "none"])
    ap.add_argument("--cloud", default="aws", choices=["aws", "azure", "gcp", "onprem"])
    ap.add_argument("--assess", action="store_true",
                    help="read-only assessment: census, inventory, gaps. No workspace phases beyond 1")
    ap.add_argument("--force", action="store_true", help="redo completed phases")
    ap.add_argument("--auto-approve", metavar="APPROVER_ID", default=None,
                    help="record a standing authorization from this approver so the agent loop decides gates "
                         "unattended (green -> approved-with-conditions, red -> waived). Still evidenced and audited.")
    ap.add_argument("--authorization", default="proceed on all gates without asking for external approval",
                    help="the approver's instruction, quoted verbatim into every auto decision")
    args = ap.parse_args(argv)

    src = Path(args.source).expanduser().resolve()
    if not src.is_dir():
        die(f"source is not a directory: {src}")

    chosen_out = args.out or args.out_positional
    out = (Path(chosen_out).expanduser().resolve() if chosen_out
           else src.parent / f"{src.name}-modernized")
    if out == src or src in out.parents:
        die("output must not be inside the source tree - the source is opened read-only")

    rule("intake")
    log(f"  source   {src}")
    log(f"  output   {out}")

    census = classify_tree(src)
    facts = detect_platform(census["files"], census["datasets"])
    c = census["counts"]
    if c["cobol"] == 0:
        die(f"no COBOL source found under {src} "
            f"(looked for {', '.join(sorted(SOURCE_EXT['cobol']))})", 1)

    log(f"  detected {facts['tp_monitor']} · "
        f"{', '.join(facts['databases']) or 'no database'} · "
        f"{facts['messaging']} · {facts['charset']}")

    out.mkdir(parents=True, exist_ok=True)
    make_workspace(out)
    write_config(out, src, args, facts)

    state = load_state(out)
    if not state:
        state = {"project": src.name, "profile": args.profile, "industry": args.industry,
                 "source_path": src.as_posix(), "output_path": out.as_posix(),
                 "current_phase": "intake",
                 "gates": {f"G{i}": {"status": "not-reached"} for i in range(1, 8)},
                 "waves": []}

    done = state.get("phases_complete", [])
    if "intake" in done and not args.force:
        log("  intake already complete (use --force to redo)")
        intake = {"artifacts": 0, "gaps": 0}
    else:
        intake = phase_intake(src, out, census, facts)
        log(f"  registered {intake['artifacts']} artifacts, {intake['gaps']} known gaps")
        done = sorted(set(done) | {"intake"})

    rule("discovery")
    if "discovery" in done and not args.force:
        log("  discovery already complete (use --force to redo)")
        disc = {}
    else:
        disc = phase_discovery(src, out, census)
        if disc.get("inventory", {}).get("rc", 1) != 0:
            log(disc["inventory"]["output"])
            die("inventory failed", 1)
        done = sorted(set(done) | {"discovery"})

    state["phases_complete"] = done
    # Re-running phases 0-1 (e.g. --force after a parser fix) must never regress
    # the programme: keep current_phase, later phases_complete and every gate.
    # Found on CardDemo when a regeneration reset an architecture-phase workspace
    # to "specification" (plugin/docs/LESSONS-LEARNED.md B17).
    if state.get("current_phase") in (None, "intake", "discovery"):
        state["current_phase"] = "specification"
    if args.auto_approve:
        state["blanket_authorization"] = {"granted_by": args.auto_approve, "at": now(), "text": args.authorization,
                                          "scope": "all gates; each is still evidenced and recorded individually; red evidence is waived, never approved",
                                          "applied_to": state.get("blanket_authorization", {}).get("applied_to", [])}
        log(f"  auto-approve: gates will be decided unattended in {args.auto_approve}'s name (red rows waived, not approved)")
    save_state(out, state)
    write_handoff(out, src, census, facts, intake, disc, args)

    rule("gaps")
    gap_file = out / "modernization/0-intake/gap-list.md"
    log(f"  {gap_file}")
    log("  the repository does not contain production datasets, execution")
    log("  telemetry, batch timings or security exports. Chase them now -")
    log("  they have the longest lead time and Gate 1 is weaker without them.")

    if args.assess:
        rule("assessment complete")
        log(f"  read {out / 'MODERNIZE.md'}")
        log("  no further phases run in --assess mode.")
        return 0

    rule("next")
    log(f"  cd {out}")
    log("  claude          then run:  /modernize")
    log()
    log("  Phase 2 (specification recovery) needs judgement, so it runs in the")
    log("  agent pipeline and stops at Gate 1 for BA + Architect + Product Owner.")
    log()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
