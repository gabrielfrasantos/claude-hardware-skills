#!/usr/bin/env python3
"""review.py: review a KiCad 10 project's schematic and board with every check of the plugin, into one findings file.

    review.py <project dir | .kicad_pro | .kicad_pcb | .kicad_sch> [--out DIR] [--voltage NET=V ...]
              [--voltages volts.json] [--netlist file.net] [--kicad-cli PATH] [--fab jlcpcb] [--assembly jlcpcb]
              [--blocks 'pcb/reference/*.block.json'] [--bom bom/bom.csv] [--skip NAME,...] [--fail-on MAJOR]
              [--require NAME,...|all] [--allow-unrouted]

Runs, each when its inputs exist. Each step ends with a status, kept apart from the findings' severities:
completed, partial (a part could not run: DRC without kicad-cli, assembly), failed (its tool broke),
missing_inputs (nothing to run it on) or skipped (--skip, or stock without --bom). Failed and missing_inputs also
add a NOTE with the reason. Zero findings from a step that did not complete is not a pass.
  schematic   this skill's checks on the design model (checks.py): decoupling, pull-ups, MCU pins, ratings,
              orientation, connector ESD, dividers, test points
  erc         KiCad ERC (kicad-cli)
  library     symbol pins against footprint pads, BOM fields (schematic-capture/library_check.py)
  rules       shorts, clearance, fab floor, geometry and copper gates (pcb-design-rules/pcb_rules.py check;
              DRC when kicad-cli is there)
  netclasses  net classes against current and voltage (pcb-copper/netclasses.py check)
  placement   validity, ratsnest and assembly (pcb-placement/place.py gate, dfa.py)
  blocks      copied vendor blocks still where the vendor has them (reference-block/refblock.py check)
  stock       stock, packages, lifecycle (hardware-project/jlc_stock.py; network; only with --bom)

Writes DIR/findings.json (every finding: id, severity, area, check, anchor, message, rule, tool; "checks": each
step's status and reason; "steps": the completed ones) and DIR/review.md, and DIR/netlist.net when kicad-cli can
export one. The reviewer agent starts from these. Default DIR: review_exports/<board>/review/. The steps run in an
empty folder and their reports then replace the last run's, so a stale report never stands in for a failed step.
Report-only: exit 0 unless --fail-on BLOCKER|MAJOR|MINOR finds one at that level or above, or a step named in
--require (a release gate; 'all' = every step not skipped with --skip) did not complete.

The model comes from the board plus the schematics' symbols when there is a board (pin positions, no KiCad
needed), else from a netlist (--netlist, or exported with kicad-cli), so a schematic can be reviewed before layout.
"""

import argparse
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import checks as C  # noqa: E402
import design as D  # noqa: E402

SEVERITY = ["BLOCKER", "MAJOR", "MINOR", "NOTE"]
STEPS = ["schematic", "erc", "library", "rules", "netclasses", "placement", "blocks", "stock"]
STATUS = ["completed", "partial", "failed", "missing_inputs", "skipped"]
# Reports the steps write into the output folder: removed at the start of each run's hand-over, so none is stale.
ARTIFACTS = ["netlist.net", "erc.json", "library.json", "rules.json", "netclasses.json", "placement.json",
             "assembly.json", "stock.json"]
SAFETY = {"shorts", "clearance_violations", "below_fab_minimum"}
HOUSE_STYLE = {"any_angle_segments", "right_angle_corners", "track_junctions", "jogs", "diagonal_length_pct",
               "long_diagonals", "short_segment_pct", "segments_per_connection_p90", "detour_p90"}
# Yield measures, not fab requirements: a hard gate in pcb_rules (house practice), MINOR in a review. JLCPCB doesn't ask
# for teardrops; they reduce pad cracking and drill breakout (pcb-copper §3).
YIELD = {"teardrops_disabled", "teardrops_disabled_smd", "teardrops_missing"}


def script(skill, name):
    return os.path.join(SKILLS, skill, "scripts", name)


def find_project(path):
    """(pro, board, schematic) from a project folder or any of its files; missing ones are None."""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        pros = sorted(glob.glob(os.path.join(path, "*.kicad_pro"))) or \
            sorted(glob.glob(os.path.join(path, "hardware", "*", "*.kicad_pro"))) or \
            sorted(glob.glob(os.path.join(path, "**", "*.kicad_pro"), recursive=True))
        if not pros:
            sys.exit(f"no .kicad_pro under {path}")
        if len(pros) > 1:
            sys.exit("several projects: " + ", ".join(os.path.relpath(p, path) for p in pros) + " (give one)")
        stem = pros[0][:-len(".kicad_pro")]
    else:
        stem = os.path.splitext(path)[0]

    def have(ext):
        return stem + ext if os.path.exists(stem + ext) else None
    return have(".kicad_pro"), have(".kicad_pcb"), have(".kicad_sch")


def run(cmd, cwd=None):
    r = subprocess.run([sys.executable] + cmd, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout + r.stderr


def finding(severity, area, check, anchor, message, rule, tool):
    return dict(severity=severity, area=area, check=check, anchor=anchor, message=message, rule=rule, tool=tool)


def not_run(step, why):
    """A NOTE for a part of a step that could not run (DRC within rules, assembly within placement): the step is
    then 'partial'. A whole step that can't run raises NotRun instead."""
    f = finding("NOTE", "review", step, "", f"{step} not run: {why}", "design-review §2", step)
    f["_partial"] = True
    return f


class NotRun(Exception):
    """A step that did not complete: 'failed' (its tool broke), 'missing_inputs' (nothing to run it on) or
    'skipped' (not asked for)."""
    def __init__(self, status, why):
        super().__init__(why)
        self.status, self.why = status, why


def _tail(text, default):
    return (text or "").strip()[-200:] or default


# ------------------------------------------------------------------------------------------------ steps
def step_schematic(model):
    if not model:
        raise NotRun("missing_inputs", "no board, schematic netlist or kicad-cli")
    return [finding(x["severity"], "schematic", x["check"], x["anchor"], x["message"], x["rule"], "checks.py")
            for x in C.run(model)]


def step_erc(cli, sch, out):
    if not cli or not sch:
        raise NotRun("missing_inputs", "needs kicad-cli and a schematic")
    path = os.path.join(out, "erc.json")
    try:
        r = subprocess.run([cli, "sch", "erc", "--format", "json", "--severity-all", "-o", path, sch],
                           capture_output=True, text=True)
    except OSError as e:
        raise NotRun("failed", f"kicad-cli not runnable: {e}")
    # Without --exit-code-violations, kicad-cli exits 0 whatever ERC finds: any other code is the tool failing.
    if r.returncode != 0 or not os.path.exists(path):
        raise NotRun("failed", f"kicad-cli exit {r.returncode}: " + _tail(r.stdout + r.stderr, "no report written"))
    try:
        with open(path) as f:
            data = json.load(f)
    except ValueError as e:
        raise NotRun("failed", f"unreadable ERC report: {e}")
    found = []
    for sheet in data.get("sheets", []):
        for v in sheet.get("violations", []):
            sev = {"error": "MAJOR", "warning": "MINOR"}.get(v.get("severity"), "NOTE")
            items = "; ".join(i.get("description", "") for i in v.get("items", []))[:200]
            found.append(finding(sev, "schematic", f"erc:{v.get('type', '')}", sheet.get("path", ""),
                                 f"{v.get('description', '')}: {items}", "KiCad ERC", "kicad-cli sch erc"))
    return found


def step_library(board, sch, out):
    if not (board and sch):
        raise NotRun("missing_inputs", "needs a board and a schematic")
    path = os.path.join(out, "library.json")
    code, text = run([script("schematic-capture", "library_check.py"), board, "--schematic", sch, "--json", path])
    if not os.path.exists(path):
        raise NotRun("failed", _tail(text, "library_check.py wrote no report"))
    with open(path) as f:
        data = json.load(f)
    sev = {"pins_without_pad": "MAJOR", "pads_without_pin": "MAJOR", "not_on_board": "MAJOR", "missing_fields": "MINOR"}
    return [finding(sev.get(k, "MINOR"), "library", k, row.split(" ")[0], row, "schematic-capture §5–§6",
                    "library_check.py") for k, rows in data.items() for row in rows]


def _gate_findings(data, tool, area, rule, kinds):
    found = []
    examples = data.get("examples", {})
    for kind, rows in (("hard", data.get("failures", [])), ("soft", data.get("warnings", []))):
        for row in rows:
            name = row.split(" ")[0]
            if name in SAFETY or name == "DRC":
                sev = "BLOCKER" if name in SAFETY else "MAJOR"
            elif name in HOUSE_STYLE or name in YIELD:
                sev = "MINOR"
            else:
                sev = "MAJOR" if kind == "hard" else "MINOR"
            ex = examples.get(name) or []
            detail = "; ".join(str(e) for e in ex[:5])
            label = " (house style)" if name in HOUSE_STYLE else " (yield, not a fab requirement)" if name in YIELD else ""
            found.append(finding(sev, area, name, detail[:200], f"{row}{label}" + (f": {detail}" if detail else ""),
                                 rule, tool))
    return found


def step_rules(board, cli, fab, out, allow_unrouted=False):
    if not board:
        raise NotRun("missing_inputs", "no board")
    path = os.path.join(out, "rules.json")
    cmd = [script("pcb-design-rules", "pcb_rules.py"), "check", board, "--json", path]
    if allow_unrouted:
        cmd.append("--allow-unrouted")
    if not cli:
        cmd.append("--no-drc")
    else:
        cmd += ["--kicad-cli", cli]
    if fab:
        cmd += ["--fab", fab]
    code, text = run(cmd)
    if not os.path.exists(path):
        raise NotRun("failed", _tail(text, "pcb_rules.py wrote no report"))
    with open(path) as f:
        data = json.load(f)
    found = _gate_findings(data, "pcb_rules.py check", "layout", "pcb-design-rules §2", None)
    if not cli:
        found.append(not_run("drc", "kicad-cli not found: geometry, copper and the script's own short/clearance check "
                                    "ran; KiCad DRC and schematic parity did not"))
    return found


def step_netclasses(board, out):
    if not board:
        raise NotRun("missing_inputs", "no board")
    if not os.path.exists(os.path.splitext(board)[0] + ".kicad_pro"):
        raise NotRun("missing_inputs", "no .kicad_pro next to the board (the net classes live there)")
    path = os.path.join(out, "netclasses.json")
    code, text = run([script("pcb-copper", "netclasses.py"), "check", board, "--json", path])
    if not os.path.exists(path):
        raise NotRun("failed", _tail(text, "netclasses.py wrote no report"))
    with open(path) as f:
        data = json.load(f)
    return _gate_findings(data, "netclasses.py check", "copper", "pcb-copper §4", None)


def step_placement(board, assembly, out):
    if not board:
        raise NotRun("missing_inputs", "no board")
    found = []
    path = os.path.join(out, "placement.json")
    code, text = run([script("pcb-placement", "place.py"), "gate", board, "--json", path, "--assembly", "none"])
    if os.path.exists(path):
        with open(path) as f:
            m = json.load(f)
        for k in ("parts_off_board", "overlaps", "keepout_violations"):
            for item in (m.get("detail", {}).get(k) or [])[:30]:
                if k == "parts_off_board":       # its pads and holes still go into the Gerbers and the drill file
                    found.append(finding("BLOCKER", "placement", k, str(item),
                                         f"{item} has pads outside the board outline: its copper and holes are exported "
                                         "into the Gerbers and the drill file outside the board (the fab will query or "
                                         "drop them). Place it, or delete it and record why", "pcb-placement §4",
                                         "place.py gate"))
                    continue
                found.append(finding("MAJOR", "placement", k, str(item), f"{k}: {item}", "pcb-placement §4",
                                     "place.py gate"))
    else:
        raise NotRun("failed", _tail(text, "place.py gate wrote no report"))
    if assembly == "none":
        return found
    path = os.path.join(out, "assembly.json")
    code, text = run([script("pcb-placement", "dfa.py"), board, "--assembly", assembly, "--json", path])
    if not os.path.exists(path):
        return found + [not_run("assembly", _tail(text, "dfa.py wrote no report"))]
    with open(path) as f:
        dd = json.load(f)["detail"]
    source = json.load(open(path)).get("spacing_source", assembly)
    for a, b, gap, lim, cls in dd.get("assembly_spacing", []):
        found.append(finding("MAJOR", "assembly", "assembly_spacing", f"{a} / {b}",
                             f"{a} and {b} {gap} mm apart, below {lim} mm for {cls} ({source})", "pcb-placement §4.1",
                             "dfa.py"))
    for a, b, gap, lim, cls in dd.get("decoupling_exceptions", []):
        found.append(finding("NOTE", "assembly", "decoupling_exception", f"{a} / {b}",
                             f"{a} and {b} {gap} mm apart (< {lim} mm for {cls}): decoupling kept close on purpose; "
                             "accept or move", "pcb-placement §4.1", "dfa.py"))
    for ref, dist in dd.get("edge_keepout", []):
        found.append(finding("MINOR", "assembly", "edge_keepout", ref,
                             f"{ref} is {dist} mm from the board edge (brittle part: keep 3–5 mm)", "pcb-placement §4.1",
                             "dfa.py"))
    for side, v in dd.get("fiducials", {}).items():
        if not v["ok"]:
            found.append(finding("MINOR", "assembly", "fiducials", f"{side}.Cu",
                                 f"{v['count']} fiducial(s) on {side}.Cu"
                                 + (f", too close to the edge: {', '.join(v['too_close'])}" if v["too_close"] else "")
                                 + ": add 3 or order edge rails with fiducials", "pcb-placement §4.1", "dfa.py"))
    if dd.get("orientation_mixed"):
        rows = dd["orientation_mixed"]
        found.append(finding("NOTE", "assembly", "orientation_mixed", ", ".join(r[0] for r in rows[:10]),
                             f"{len(rows)} part(s) off their class's usual orientation: "
                             + ", ".join(f"{r[0]} {r[1]}°" for r in rows[:10])
                             + ". Deliberate rotations (rings, arrays, a part turned to its pins) are fine; check the "
                             "polarity marks in the assembler's CPL preview", "pcb-placement §4.1", "dfa.py"))
    return found


def step_blocks(board, pattern, root):
    if not board:
        raise NotRun("missing_inputs", "no board")
    paths = sorted(glob.glob(pattern if os.path.isabs(pattern) else os.path.join(root, pattern), recursive=True))
    found = []
    for p in paths:
        code, text = run([script("reference-block", "refblock.py"), "check", p, board])
        if code:
            found.append(finding("MAJOR", "layout", "reference_block", os.path.basename(p),
                                 f"copied block no longer matches the vendor's: {text.strip()[-300:]}",
                                 "reference-block §5", "refblock.py check"))
    return found


def step_stock(bom, out):
    if not bom:
        raise NotRun("skipped", "not requested (no --bom)")
    path = os.path.join(out, "stock.json")
    code, text = run([script("hardware-project", "jlc_stock.py"), bom, "--json", path])
    if not os.path.exists(path):
        raise NotRun("failed", _tail(text, "jlc_stock.py wrote no report"))
    with open(path) as f:
        data = json.load(f)
    found = [finding("MAJOR", "bom", "stock", r["lcsc"], f"{r['lcsc']} {r.get('mpn', '')}: {r['status']}",
                     "hardware-project §5", "jlc_stock.py") for r in data["lines"] if r["status"] != "ok"]
    found += [finding("NOTE", "bom", "stock", n.split(":")[0], n, "hardware-project §5", "jlc_stock.py")
              for n in data.get("notes", [])]
    return found


# ------------------------------------------------------------------------------------------------ report
def report_md(meta, findings):
    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in SEVERITY}
    lines = [f"# Design review: {meta['board_name']}", "",
             f"Generated {meta['generated']} from {meta['model']}. Checks completed: "
             f"{', '.join(meta['steps']) or 'none'}.", ""]
    checks = meta.get("checks", {})
    not_done = [(s, c) for s, c in checks.items() if c["status"] != "completed"]
    if meta.get("incomplete_required"):
        lines += [f"**Incomplete: required check(s) {', '.join(meta['incomplete_required'])} did not complete. "
                  "Zero findings from a check that did not run is not a pass.**", ""]
    if not_done:
        lines += ["Checks that did not complete (no finding from them means nothing):", ""]
        lines += [f"- {s}: {c['status']}" + (f": {c['reason'][:300]}" if c.get("reason") else "") for s, c in not_done]
        lines += [""]
    lines += ["| Severity | Count |", "|---|---|"] + [f"| {s} | {counts[s]} |" for s in SEVERITY] + [""]
    lines += ["| # | Severity | Area | Check | Anchor | Finding | Rule |", "|---|---|---|---|---|---|---|"]
    for x in findings:
        msg = x["message"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {x['id']} | {x['severity']} | {x['area']} | {x['check']} | {x['anchor'][:60].replace('|', '/')} "
                     f"| {msg[:400]} | {x['rule']} |")
    lines += ["", "Findings from scripts are evidence, not verdicts: the reviewer confirms each against the datasheets "
              "and the design intent, and adds what the scripts can't see (design-review §4)."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--out")
    ap.add_argument("--voltage", action="append", default=[], metavar="NET=V", help="a net's voltage (max, DC or peak)")
    ap.add_argument("--voltages", help="JSON {net: volts}")
    ap.add_argument("--netlist", help="a KiCad netlist (.net, S-expression) instead of reading the board")
    ap.add_argument("--kicad-cli")
    ap.add_argument("--fab")
    ap.add_argument("--assembly", default="jlcpcb")
    ap.add_argument("--blocks", default="**/*.block.json", help="glob of reference-block blocks to check")
    ap.add_argument("--bom", help="BOM CSV for the stock check (network)")
    ap.add_argument("--skip", default="", help="steps to skip: " + ",".join(STEPS))
    ap.add_argument("--fail-on", choices=SEVERITY[:3])
    ap.add_argument("--require", metavar="STEP,...|all",
                    help="exit 1 unless these steps completed (a release gate); 'all' = every step not --skip'ped")
    ap.add_argument("--allow-unrouted", action="store_true",
                    help="a placed board not yet routed: unconnected items are not findings (pcb_rules.py)")
    a = ap.parse_args(argv)

    pro, board, sch = find_project(a.project)
    if not (board or sch or a.netlist):
        sys.exit("nothing to review: no .kicad_pcb, .kicad_sch or --netlist")
    name = os.path.basename((board or sch or a.netlist).rsplit(".", 1)[0])
    root = os.path.dirname(pro or board or sch or a.netlist)
    out = os.path.abspath(a.out or os.path.join(os.getcwd(), "review_exports", name, "review"))
    os.makedirs(out, exist_ok=True)
    cli = None
    for c in (a.kicad_cli, os.environ.get("KICAD_CLI"), shutil.which("kicad-cli")):
        if c:
            cli = c
            break
    skip = {s.strip() for s in a.skip.split(",") if s.strip()}
    require = set(STEPS) - skip if a.require == "all" else {s.strip() for s in (a.require or "").split(",") if s.strip()}
    unknown = (skip | require) - set(STEPS)
    if unknown:
        sys.exit(f"unknown step(s): {', '.join(sorted(unknown))} (steps: {', '.join(STEPS)})")
    # Every run starts in an empty folder, so a report left by an earlier run can never stand in for this one's.
    work = tempfile.mkdtemp(prefix=".run-", dir=out)
    try:
        return _review(a, name, root, out, work, pro, board, sch, cli, skip, require)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _review(a, name, root, out, work, pro, board, sch, cli, skip, require):
    netlist = a.netlist
    if not netlist and cli and sch:
        tmp = os.path.join(work, "netlist.net")
        try:
            r = subprocess.run([cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", tmp, sch],
                               capture_output=True, text=True)
            netlist = tmp if r.returncode == 0 and os.path.exists(tmp) else None
        except OSError:
            netlist = None
    if board:
        model = D.from_board(board, sch, pro)
    elif netlist:
        model = D.from_netlist(netlist)
    else:
        model = None
    if model:
        if a.voltages:
            with open(a.voltages) as f:
                model.overrides.update({k: float(v) for k, v in json.load(f).items()})
        for kv in a.voltage:
            k, v = kv.split("=", 1)
            model.overrides[k] = float(v)

    findings, checks = [], {}
    plan = [("schematic", lambda: step_schematic(model)),
            ("erc", lambda: step_erc(cli, sch, work)),
            ("library", lambda: step_library(board, sch, work)),
            ("rules", lambda: step_rules(board, cli, a.fab, work, a.allow_unrouted)),
            ("netclasses", lambda: step_netclasses(board, work)),
            ("placement", lambda: step_placement(board, a.assembly, work)),
            ("blocks", lambda: step_blocks(board, a.blocks, root)),
            ("stock", lambda: step_stock(a.bom, work))]
    for step, fn in plan:
        if step in skip:
            checks[step] = dict(status="skipped", reason="--skip")
            continue
        try:
            got = fn()
            partial = [x["message"] for x in got if x.pop("_partial", False)]
            checks[step] = dict(status="partial", reason="; ".join(partial)) if partial else dict(status="completed")
            findings += got
        except NotRun as e:
            checks[step] = dict(status=e.status, reason=e.why)
        except Exception as e:                       # a broken step must not hide the others
            checks[step] = dict(status="failed", reason=f"{type(e).__name__}: {e}")
        if checks[step]["status"] in ("failed", "missing_inputs"):
            findings.append(finding("NOTE", "review", step, "", f"{step} not run ({checks[step]['status']}): "
                                    f"{checks[step]['reason']}", "design-review §2", step))
    ran = [s for s in STEPS if checks[s]["status"] == "completed"]
    incomplete = [s for s in STEPS if s in require and checks[s]["status"] != "completed"]
    for f in ARTIFACTS:                          # this run's reports replace the last run's; stale ones go
        if os.path.exists(os.path.join(out, f)):
            os.unlink(os.path.join(out, f))
    for f in os.listdir(work):
        os.replace(os.path.join(work, f), os.path.join(out, f))
    if netlist and os.path.dirname(netlist) == work:
        netlist = os.path.join(out, "netlist.net")
    findings.sort(key=lambda x: (SEVERITY.index(x["severity"]), x["area"], x["check"], x["anchor"]))
    for i, x in enumerate(findings, 1):
        x["id"] = f"F{i}"
    meta = dict(board_name=name, generated=datetime.datetime.now().isoformat(timespec="seconds"),
                model=model.source if model else "no model", steps=ran, checks=checks,
                required=sorted(require, key=STEPS.index), incomplete_required=incomplete,
                inputs=dict(project=pro, board=board, schematic=sch, netlist=netlist, kicad_cli=cli),
                voltages=model.overrides if model else {})
    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in SEVERITY}
    with open(os.path.join(out, "findings.json"), "w") as f:
        json.dump(dict(meta, counts=counts, findings=findings), f, indent=2)
    with open(os.path.join(out, "review.md"), "w") as f:
        f.write(report_md(meta, findings))
    print(f"{name}: " + ", ".join(f"{counts[s]} {s}" for s in SEVERITY) + f" -> {out}/review.md, findings.json")
    for x in findings:
        if x["severity"] in ("BLOCKER", "MAJOR"):
            print(f"  {x['id']} {x['severity']} {x['area']}/{x['check']}: {x['message'][:160]}")
    for s in incomplete:
        print(f"  required check incomplete: {s} ({checks[s]['status']}: {checks[s].get('reason', '')[:160]})")
    if incomplete:
        return 1
    if a.fail_on and any(SEVERITY.index(x["severity"]) <= SEVERITY.index(a.fail_on) for x in findings):
        return 1
    return 0


if __name__ == "__main__":
    tempfile.tempdir = None
    sys.exit(main())
