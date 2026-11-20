#!/usr/bin/env python3
"""Run a board repo's eval cases through headless Claude Code, with and without the plugin, and score the results.

    python3 evals/run.py <board-repo>/evals                       every case, both configurations, the case's runs
    python3 evals/run.py <board-repo>/evals --case placement --runs 1 --config with-plugin
    python3 evals/run.py <board-repo>/evals --dry-run             print the commands, run nothing
    python3 evals/run.py <board-repo>/evals --rescore <board-repo>/evals/work/<stamp>

The cases live in the board repo (`evals/cases/*.json`); this repo holds only the harness. For each case, the fixture
is built from the board repo's git history (make_fixture.py) into <board-repo>/evals/work/<stamp>/<case>/fixture/.
Each run then gets a fresh copy of the fixture's KiCad files (the manifest and baseline stay hidden) in
.../<case>/<config>-<n>/, and Claude runs there with:
  - `--setting-sources project`, so the user's settings and installed plugins do not load (the work directory has no
    project settings), and `--strict-mcp-config`, so no MCP servers load;
  - `--plugin-dir plugins/hardware-design` for the `with-plugin` configuration only;
  - `--permission-mode bypassPermissions` (the copy is disposable), `--max-budget-usd` from the case.
The transcript (stream-json) is kept beside the board; the skills Claude loaded, its cost and turns are read from it.
Scores come from the files only (metrics.py), against the fixture's baseline (the owner's placement). The summary is
written to <board-repo>/evals/results/<stamp>-<case>.json. `evals/work/` should be gitignored in the board repo.

Run it by hand before a release tag, not in CI: a placement case costs real money and up to an hour per run.
"""

import argparse
import datetime
import json
import pathlib
import shutil
import statistics
import subprocess
import sys

import boardgeo as G
import make_fixture as F
import metrics as M

HERE = pathlib.Path(__file__).resolve().parent
PLUGIN = HERE.parent / "plugins" / "hardware-design"
CONFIGS = ("with-plugin", "without-plugin")
LIMIT = 1.10     # docs/design.md D25: no worse than the human baseline + 10 %
KICAD_SUFFIXES = (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".kicad_sch", ".kicad_sym")


def prompt_text(case, name):
    """`prompt` is a built-in prompt (evals/prompts/<prompt>.md here) or a path relative to the case file."""
    p = case.get("prompt", case.get("kind", "placement"))
    path = HERE / "prompts" / f"{p}.md"
    if not path.exists():
        path = case["_path"].parent / p
    return path.read_text(encoding="utf-8").format(name=name)


def attach_fixture(case, fixture_dir):
    case["_fixture"] = pathlib.Path(fixture_dir)
    case["_manifest"] = json.loads((case["_fixture"] / "manifest.json").read_text(encoding="utf-8"))
    case["_baseline"] = json.loads((case["_fixture"] / "baseline.json").read_text(encoding="utf-8"))
    case["_prompt"] = prompt_text(case, case["_manifest"]["name"])
    return case


def command(case, config, claude="claude", model=None):
    cmd = [claude, "-p", case["_prompt"], "--output-format", "stream-json", "--verbose",
           "--permission-mode", "bypassPermissions", "--setting-sources", "project", "--strict-mcp-config",
           "--max-budget-usd", str(case.get("max_budget_usd", 25))]
    if config == "with-plugin":
        cmd += ["--plugin-dir", str(PLUGIN)]
    if model:
        cmd += ["--model", model]
    return cmd


def prepare(case, workdir):
    workdir.mkdir(parents=True, exist_ok=False)
    for f in case["_fixture"].iterdir():
        if f.suffix in KICAD_SUFFIXES:
            shutil.copy(f, workdir / f.name)


def transcript_facts(path):
    facts = {"skills": [], "cost_usd": None, "turns": None, "duration_s": None, "result": None, "error": None}
    if not path.exists():
        return facts
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Skill":
                    facts["skills"].append(block.get("input", {}).get("skill"))
        elif ev.get("type") == "result":
            facts.update(cost_usd=ev.get("total_cost_usd"), turns=ev.get("num_turns"),
                         duration_s=round((ev.get("duration_ms") or 0) / 1000), result=ev.get("result"),
                         error=ev.get("subtype") if ev.get("is_error") else None)
    return facts


def score(case, workdir):
    board = workdir / f"{case['_manifest']['name']}.kicad_pcb"
    out = {"workdir": str(workdir)}
    out.update(transcript_facts(workdir / "transcript.jsonl"))
    try:
        m = M.measure(G.Board(board), case["_manifest"])
    except Exception as e:                       # an unreadable board is a failed run, not a crash
        out.update(valid=False, parse_error=f"{type(e).__name__}: {e}")
        return out
    added_copper = m["vias"] > 0 or m["track_segments"] > 0
    m["valid"] = m["valid"] and not added_copper
    m["added_copper"] = added_copper
    out.update(m)
    return out


def summarise(case, runs):
    base = case["_baseline"]
    summary = {}
    for config in CONFIGS:
        rs = [r for r in runs if r["config"] == config]
        if not rs:
            continue
        ok = [r for r in rs if r.get("valid")]
        s = {"runs": len(rs), "valid": len(ok),
             "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rs), 2),
             "skills": sorted({k for r in rs for k in r.get("skills", []) if k})}
        for key in ("ratsnest_mm", "crossings", "decap_p90_mm"):
            vals = [r[key] for r in ok if r.get(key) is not None]
            if vals:
                s[key] = statistics.median(vals)
                if base.get(key):
                    s[key + "_vs_baseline"] = round(s[key] / base[key], 3)
        s["within_limit"] = bool(ok) and all(s.get(k + "_vs_baseline", 9) <= LIMIT for k in ("ratsnest_mm", "crossings"))
        summary[config] = s
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("evals", type=pathlib.Path, help="the board repo's evals/ folder (holds cases/)")
    ap.add_argument("--case", action="append", help="case id (repeatable); default: all")
    ap.add_argument("--config", action="append", choices=CONFIGS, help="default: both")
    ap.add_argument("--runs", type=int, help="override the case's run count")
    ap.add_argument("--claude", default="claude", help="Claude Code executable")
    ap.add_argument("--model")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rescore", type=pathlib.Path, help="a <board-repo>/evals/work/<stamp> directory to score again")
    a = ap.parse_args(argv)

    cases = [F.load_case(p) for p in sorted((a.evals / "cases").glob("*.json"))]
    if a.case:
        cases = [c for c in cases if c["id"] in a.case]
    if not cases:
        sys.exit(f"no cases in {a.evals / 'cases'}")
    configs = a.config or list(CONFIGS)
    stamp = a.rescore.name if a.rescore else datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    work = a.rescore or a.evals.resolve() / "work" / stamp

    for case in cases:
        fixture = work / case["id"] / "fixture"
        if not a.rescore:
            F.build(case, fixture)
        attach_fixture(case, fixture)
        runs = []
        for config in configs:
            for n in range(1, (a.runs or case.get("runs", 3)) + 1):
                wd = work / case["id"] / f"{config}-{n}"
                cmd = command(case, config, a.claude, a.model)
                if a.dry_run:
                    print(f"[{case['id']} {config}-{n}] cd {wd} &&",
                          " ".join(cmd[:1] + ["-p", "<prompt>"] + cmd[3:]))
                    continue
                if not a.rescore:
                    prepare(case, wd)
                    print(f"[{case['id']} {config}-{n}] running in {wd}", flush=True)
                    with open(wd / "transcript.jsonl", "w", encoding="utf-8") as log:
                        try:
                            subprocess.run(cmd, cwd=wd, stdout=log, stderr=subprocess.STDOUT,
                                           timeout=60 * case.get("timeout_min", 60))
                        except subprocess.TimeoutExpired:
                            log.write(json.dumps({"type": "result", "is_error": True, "subtype": "timeout"}) + "\n")
                elif not wd.exists():
                    continue
                r = score(case, wd)
                r["config"], r["run"] = config, n
                runs.append(r)
                print(f"  valid={r.get('valid')} ratsnest={r.get('ratsnest_mm')} crossings={r.get('crossings')} "
                      f"skills={r.get('skills')} cost={r.get('cost_usd')}", flush=True)
        if a.dry_run or not runs:
            continue
        result = {"case": case["id"], "date": stamp, "source": case["_manifest"]["source"],
                  "baseline": {k: v for k, v in case["_baseline"].items() if k != "detail"},
                  "summary": summarise(case, runs),
                  "runs": [{k: v for k, v in r.items() if k != "detail"} for r in runs]}
        out = a.evals / "results" / f"{stamp}-{case['id']}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result["summary"], indent=2))
        print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
