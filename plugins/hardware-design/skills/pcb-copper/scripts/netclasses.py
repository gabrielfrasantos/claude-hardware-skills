#!/usr/bin/env python3
"""netclasses.py: the standard net-class set, sized from the class name (KiCad 10+).

    netclasses.py size <amps> [--dt 10] [--outer-mm 0.035] [--inner-mm 0.0175]
    netclasses.py assign <project.kicad_pro>
    netclasses.py apply <project.kicad_pro | board.kicad_pcb> [--dt 10] [--fab jlcpcb] [--allow NAME,...]
    netclasses.py check <board.kicad_pcb> [--dt 10] [--fab ...] [--allow ...] [--gate NAME=LIMIT]
                        [--report r.md] [--json r.json]

Class names go on the schematic's net-class directive labels; KiCad resolves each label to its net and writes
the assignment into the project. The name carries what sizes the class:

  PWR_<I>A[_<V>V]     power. Width from the IPC-2221 external-chart fit for I amps at a dT rise, on the stack-up's
                      outer and inner copper thickness (inner layers too, per IPC-2152's findings); at or above
                      the width of 3 A on 1 oz outer copper the net must be a pour (D21).
  GND[_<I>A][_<V>V]   ground; sized like PWR when a current is given, otherwise the signal values.
  SIGNAL, ANALOG, SENSE, CLK [_<V>V]
                      the fab's design values (pcb-design-rules profile).
  DIFF_90, DIFF_100, RF_50 [_<V>V]
                      impedance classes: set track width and gap from the fab's impedance calculator for the
                      stack-up in Board Setup; apply leaves them alone.
  ..._<V>V            clearance from IPC-2221C Table 6-1 for V volts (DC or peak): the larger of external uncoated
                      conductors (B2) and uncoated component terminations (A7), at least the fab's design value. Above 500 V: a safety standard, not this tool.
Decimals: PWR_2.5A or PWR_2p5A.

assign  what KiCad does when it saves the schematic: resolves each net-class directive label to its net and writes
        netclass_assignments into the project. For headless flows (CI, an agent without KiCad's window); a
        directive that doesn't sit on a label is reported and left to KiCad.
apply   adds or updates each standard class in use (from assignments, patterns or the class list) in the
        project. Other classes are reported, not touched.
check   every net in a standard class (Default is an error); class values as apply would write them; every
        track at least its class width for its layer (inner layers from inner copper), except where it
        necks into a pad narrower than that; nets that must be pours have a copper zone; impedance classes set.
        Exit 1 when a hard gate fails.

Shares the board parser and class resolver of the pcb-design-rules skill (../../pcb-design-rules/scripts).
"""
import argparse
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pcb-design-rules", "scripts"))
import copper as CU  # noqa: E402
import pcb_rules as PR  # noqa: E402

KINDS = ("DIFF_100", "DIFF_90", "RF_50", "PWR", "GND", "SIGNAL", "ANALOG", "SENSE", "CLK")
IMPEDANCE = ("DIFF_90", "DIFF_100", "RF_50")
NAME = re.compile(r"^(" + "|".join(KINDS) + r")((?:_\d+(?:[.p]\d+)?[AV])*)$")
DT = 10.0                     # °C rise (D21)
POUR_AMPS_1OZ = 3.0           # at or above the outer width of this current on 1 oz, a net is a pour (D21)
OZ_MM = 0.035                 # 1 oz copper (power-pcb-layout §3.5: 1 oz = 35 µm)
DEFAULT_OUTER_MM, DEFAULT_INNER_MM = 0.035, 0.0175   # when the board has no stack-up: 1 oz / 0.5 oz
# IPC-2221C Table 6-1, mm, by the top of each voltage band: the larger of B2 (external conductors, uncoated, sea
# level to 3050 m) and A7 (external component leads and terminations, uncoated; A6 in rev B), because a net-class
# clearance also governs the net's pads (power-pcb-layout §3.8; values from a secondary transcription of rev C)
CLEARANCE = [(15, 0.13), (30, 0.25), (100, 0.64), (150, 0.80), (300, 1.25), (500, 2.5)]

GATES = {
    "nets_in_default": ("hard", 0),
    "unknown_classes": ("hard", 0),
    "class_values_stale": ("hard", 0),
    "tracks_below_class_width": ("hard", 0),
    "required_pours_missing": ("hard", 0),
    "impedance_unset": ("soft", 0),
}


# ------------------------------------------------------------------------------------------------- sizing
def width_mm(amps, dt=DT, copper_mm=OZ_MM):
    """The fit to the historical IPC-2221 (IPC-D-275) external chart, I = 0.048 * dT^0.44 * A^0.725 with A in mil²
    (power-pcb-layout §3.5), on the layer's own copper thickness. IPC-2152 replaced those charts; its one chart for
    internal and external conductors is why the same fit serves inner layers: internal and external conductors
    reach close to the same temperature rise, and the old internal chart (k = 0.024) was not based on tests of
    internal conductors [PCDF-2152]."""
    k = 0.048
    area_mil2 = (amps / (k * dt ** 0.44)) ** (1 / 0.725)
    return area_mil2 / (copper_mm / 0.0254) * 0.0254


def clearance_for(volts):
    for top, mm in CLEARANCE:
        if volts <= top:
            return mm
    raise SystemExit(f"{volts:g} V is above IPC-2221 Table 6-1's 500 V band used here: clearance and creepage come "
                     "from the safety standard (IEC 62368-1 / IEC 60664-1), see power-pcb-layout §3.8")


def parse(name):
    """{'kind', 'amps', 'volts'} for a standard class name, else None."""
    m = NAME.match(name or "")
    if not m:
        return None
    out = {"kind": m.group(1), "amps": None, "volts": None}
    for num, unit in re.findall(r"_(\d+(?:[.p]\d+)?)([AV])", m.group(2)):
        out["amps" if unit == "A" else "volts"] = float(num.replace("p", "."))
    if out["kind"] == "PWR" and out["amps"] is None:
        return None                                  # a power class must say its current
    if out["amps"] is not None and out["kind"] not in ("PWR", "GND"):
        return None
    return out


def copper_mm(board_path):
    """(outer, inner) copper thickness in mm from the board's stack-up (thinnest of each), else 1 oz / 0.5 oz."""
    if not board_path or not os.path.exists(board_path):
        return DEFAULT_OUTER_MM, DEFAULT_INNER_MM
    root = PR.Board(board_path).root
    setup = PR.child(root, "setup")
    st = PR.child(setup, "stackup") if setup else None
    outer, inner = [], []
    for lay in PR.children(st, "layer") if st else []:
        typ, th = PR.child(lay, "type"), PR.child(lay, "thickness")
        if typ and typ[1] == "copper" and th:
            (outer if lay[1] in ("F.Cu", "B.Cu") else inner).append(float(th[1]))
    return (min(outer) if outer else DEFAULT_OUTER_MM), (min(inner) if inner else DEFAULT_INNER_MM)


def design_values(fabs, layers):
    return PR.combined_rules(fabs, layers)[1]


def spec(name, design, outer_mm, inner_mm, dt):
    """What a standard class should be: widths outer/inner, clearance, vias, pour, impedance."""
    p = parse(name)
    if p is None:
        return None
    s = {"name": name, "kind": p["kind"], "amps": p["amps"], "volts": p["volts"],
         "clearance": round(max(design["clearance"], clearance_for(p["volts"]) if p["volts"] else 0.0), 4),
         "via_drill": design["via_drill"], "via_diameter": design["via_diameter"],
         "impedance": p["kind"] in IMPEDANCE, "pour": False}
    if p["amps"]:
        outer = max(design["track"], width_mm(p["amps"], dt, outer_mm))
        s["track_width"] = round(outer, 3)
        s["inner_width"] = round(max(design["track"], width_mm(p["amps"], dt, inner_mm)), 3)
        s["pour"] = outer >= width_mm(POUR_AMPS_1OZ, dt, OZ_MM) - 1e-9
    else:
        s["track_width"] = s["inner_width"] = design["track"]
    return s


# ------------------------------------------------------------------------------------------------- project
def classes_in_use(ns):
    used = set()
    for v in (ns.get("netclass_assignments") or {}).values():
        used.update(v if isinstance(v, list) else [v])
    used.update(p.get("netclass") for p in ns.get("netclass_patterns") or [])
    used.update(c.get("name") for c in ns.get("classes") or [])
    used.discard(None)
    used.discard("Default")
    return used


def project_paths(path):
    base = os.path.splitext(os.path.abspath(path))[0]
    return base + ".kicad_pro", base + ".kicad_pcb", base + ".kicad_dru"


def context(path, fab, dt):
    pro, board, dru = project_paths(path)
    if not os.path.exists(pro):
        sys.exit(f"no project file {pro}")
    fabs = fab.split(",") if fab else (PR.managed_fabs(dru) or ["jlcpcb"])
    layers = len(PR.Board(board).copper_layers) if os.path.exists(board) else 2
    outer, inner = copper_mm(board)
    return pro, board, fabs, design_values(fabs, layers), outer, inner


def cmd_apply(a):
    pro, board, fabs, design, outer, inner = context(a.path, a.fab, a.dt)
    with open(pro) as f:
        pj = json.load(f)
    ns = pj.setdefault("net_settings", {})
    classes = ns.setdefault("classes", [])
    by_name = {c.get("name"): c for c in classes}
    template = dict(by_name.get("Default") or {})
    allow = set((a.allow or "").split(",")) - {""}
    rows, unknown = [], []
    for name in sorted(classes_in_use(ns)):
        s = spec(name, design, outer, inner, a.dt)
        if s is None:
            if name not in allow:
                unknown.append(name)
            continue
        c = by_name.get(name)
        if c is None:
            c = dict(template, name=name, priority=0)
            classes.append(c)
        c.update(via_drill=s["via_drill"], via_diameter=s["via_diameter"])
        if not s["impedance"] or (c.get("clearance") or 0) < s["clearance"]:
            c["clearance"] = s["clearance"]
        if not s["impedance"]:
            c["track_width"] = s["track_width"]
        rows.append(s)
    with open(pro, "w") as f:
        json.dump(pj, f, indent=2)
        f.write("\n")
    print(f"net classes for {os.path.basename(pro)}: {'+'.join(fabs)} design values, dT {a.dt:g} °C, "
          f"copper {outer * 1000:.1f} µm outer / {inner * 1000:.1f} µm inner")
    print(f"  {'class':18} {'outer':>7} {'inner':>7} {'clear':>6}  note")
    for s in rows:
        note = ("POUR required" if s["pour"] else "") + \
               ("set width/gap from the fab's impedance calculator" if s["impedance"] else "")
        print(f"  {s['name']:18} {s['track_width']:7.3f} {s['inner_width']:7.3f} {s['clearance']:6.3f}  {note}")
    if unknown:
        print("  not standard (left as they are; rename or pass --allow): " + ", ".join(unknown))
    return 0


# ------------------------------------------------------------------------------------------------- assign
_SHEET = re.compile(r'\(sheet\s.*?\(property\s+"Sheetname"\s+"((?:[^"\\]|\\.)*)".*?\(property\s+"Sheetfile"\s+'
                    r'"((?:[^"\\]|\\.)*)"', re.S)
_LABEL = re.compile(r'\((label|global_label|hierarchical_label)\s+"((?:[^"\\]|\\.)*)".*?\(at\s+([-\d.]+)\s+([-\d.]+)',
                    re.S)
_FLAG = re.compile(r'\(netclass_flag\s.*?\(at\s+([-\d.]+)\s+([-\d.]+).*?\(property\s+"Net ?[Cc]lass"\s+'
                   r'"((?:[^"\\]|\\.)*)"', re.S)


def _blocks(text, head):
    """S-expression blocks that start with `(head` and whitespace: balanced by parentheses, strings respected."""
    out = []
    for m in re.finditer(r"\(" + re.escape(head) + r"\s", text):
        i = m.start()
        depth, j, in_str = 0, i, False
        while j < len(text):
            ch = text[j]
            if in_str:
                in_str = not (ch == '"' and text[j - 1] != "\\")
            elif ch == '"':
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(text[i:j + 1])
    return out


def _on_wire(pt, w):
    (x1, y1), (x2, y2) = w
    return (min(x1, x2) - 0.01 <= pt[0] <= max(x1, x2) + 0.01 and min(y1, y2) - 0.01 <= pt[1] <= max(y1, y2) + 0.01
            and abs((x2 - x1) * (pt[1] - y1) - (y2 - y1) * (pt[0] - x1)) < 0.01)


def _follow(start, labels, wires):
    """The label (or power symbol) a point reaches along the sheet's wires, or None."""
    seen, todo = {start}, [start]
    while todo:
        pt = todo.pop()
        if pt in labels:
            return labels[pt]
        for w in wires:
            if _on_wire(pt, w):
                for end in w:
                    if end not in seen:
                        seen.add(end)
                        todo.append(end)
        for lp in labels:
            if any(_on_wire(lp, w) and _on_wire(pt, w) for w in wires):
                return labels[lp]
    return None


def directive_assignments(root_sch):
    """{net name: class} from the net-class directive labels of a hierarchical KiCad 10 schematic, without KiCad.

    A directive resolves to the label or power symbol it reaches: at its own point, or along the wires from it
    (a class table row: a label wired to its flag). Net names follow KiCad: a global label's name as it is, a local or hierarchical one prefixed with its
    sheet path (/2 Power/VM). Returns (assignments, unresolved directives as (file, x, y, class))."""
    assign, unresolved = {}, []

    def walk(path, prefix, seen):
        if path in seen or not os.path.exists(path):
            return
        seen.add(path)
        text = open(path, encoding="utf-8").read()
        labels = {}
        for kind in ("label", "global_label", "hierarchical_label"):
            for blk in _blocks(text, kind):
                m = _LABEL.match(blk)
                if m:
                    name = m.group(2).replace("/", "{slash}")
                    labels[(round(float(m.group(3)), 2), round(float(m.group(4)), 2))] = \
                        name if kind == "global_label" else prefix + name
        for blk in _blocks(text, "symbol"):
            lib = re.search(r'\(lib_id "power:[^"]*"\)', blk)
            val = re.search(r'\(property "Value" "((?:[^"\\]|\\.)*)"', blk)
            at = re.search(r'\(at\s+([-\d.]+)\s+([-\d.]+)', blk)
            if lib and val and at:
                labels[(round(float(at.group(1)), 2), round(float(at.group(2)), 2))] = val.group(1)
        wires = []
        for blk in _blocks(text, "wire"):
            xy = re.findall(r"\(xy\s+([-\d.]+)\s+([-\d.]+)\)", blk)
            if len(xy) == 2:
                wires.append(tuple((round(float(a), 2), round(float(b), 2)) for a, b in xy))
        for blk in _blocks(text, "netclass_flag"):
            m = _FLAG.match(blk)
            if not m:
                continue
            at = (round(float(m.group(1)), 2), round(float(m.group(2)), 2))
            net = _follow(at, labels, wires)
            if net:
                assign[net] = m.group(3)
            else:
                unresolved.append((os.path.basename(path), at[0], at[1], m.group(3)))
        for blk in _blocks(text, "sheet"):
            m = _SHEET.match(blk)
            if m:
                name = m.group(1).replace("/", "{slash}")
                walk(os.path.join(os.path.dirname(path), m.group(2)), f"{prefix}{name}/", seen)

    walk(os.path.abspath(root_sch), "/", set())
    return assign, unresolved


def cmd_assign(a):
    pro = project_paths(a.path)[0]
    if not os.path.exists(pro):
        sys.exit(f"no project file {pro}")
    root = os.path.splitext(pro)[0] + ".kicad_sch"
    if not os.path.exists(root):
        sys.exit(f"no root schematic {root}")
    assign, unresolved = directive_assignments(root)
    with open(pro) as f:
        pj = json.load(f)
    ns = pj.setdefault("net_settings", {})
    ns["netclass_assignments"] = {net: [cls] for net, cls in sorted(assign.items())}
    with open(pro, "w") as f:
        json.dump(pj, f, indent=2)
        f.write("\n")
    counts = {}
    for cls in assign.values():
        counts[cls] = counts.get(cls, 0) + 1
    print(f"{len(assign)} nets assigned in {os.path.basename(pro)}: " +
          ", ".join(f"{c} {n}" for c, n in sorted(counts.items())))
    for f_, x, y, cls in unresolved:
        print(f"  not on a label, left to KiCad: {cls} at ({x}, {y}) in {f_}")
    return 0


# ------------------------------------------------------------------------------------------------- check
def _on(pad, x, y):
    sh = PR.pad_shape(pad["x"], pad["y"], pad["rot"], pad["w"], pad["h"], pad["shape"], pad["rratio"])
    return PR.shape_gap(sh, PR.shape_point(x, y, 0.0)) <= 0.001


def cmd_check(a):
    for g in a.gate or []:
        k, _, v = g.partition("=")
        if k not in GATES:
            sys.exit(f"unknown gate '{k}'; gates: {', '.join(GATES)}")
        GATES[k] = (GATES[k][0], float(v))
    pro, board, fabs, design, outer, inner = context(a.board, a.fab, a.dt)
    b = PR.Board(board)
    lookup, classes = CU.class_resolver(pro)
    allow = set((a.allow or "").split(",")) - {""}
    nets = sorted({p["net"] for p in b.pads if p["net"]} | {s["net"] for s in b.segments if s["net"]})
    nets = [n for n in nets if not n.startswith("unconnected-")]
    pads_per_net = {}
    for p in b.pads:
        pads_per_net[p["net"]] = pads_per_net.get(p["net"], 0) + 1
    m, ex = {}, {k: [] for k in GATES}
    specs = {}

    for n in nets:
        cls = lookup(n)
        if cls == "Default":
            if pads_per_net.get(n, 0) >= 2:
                ex["nets_in_default"].append(n)
            continue
        if cls not in specs:
            specs[cls] = spec(cls, design, outer, inner, a.dt) if cls not in allow else None
            if specs[cls] is None and cls not in allow:
                ex["unknown_classes"].append(cls)

    for cls, s in specs.items():
        c = classes.get(cls)
        if s is None:
            continue
        if c is None:
            ex["class_values_stale"].append(f"{cls}: not defined in the project (run apply)")
            continue
        want = [("via_drill", s["via_drill"]), ("via_diameter", s["via_diameter"])]
        if s["impedance"]:
            if (c.get("clearance") or 0) < s["clearance"] - 1e-4:
                want.append(("clearance", s["clearance"]))
        else:
            want += [("clearance", s["clearance"]), ("track_width", s["track_width"])]
        bad = [f"{k} {c.get(k)} ≠ {v:g}" for k, v in want if abs((c.get(k) or 0) - v) > 1e-4]
        if bad:
            ex["class_values_stale"].append(f"{cls}: " + ", ".join(bad))
        if s["impedance"] and abs((c.get("track_width") or 0) - ((classes.get("Default") or {}).get("track_width") or 0)) < 1e-9:
            ex["impedance_unset"].append(f"{cls}: track width still the Default's {c.get('track_width')} mm")

    # tracks narrower than their class, allowing a neck into a pad narrower than the class width
    pads_by_net = {}
    for p in b.pads:
        pads_by_net.setdefault(p["net"], []).append(p)
    necks = 0
    for sg in b.segments:
        s = specs.get(lookup(sg["net"]))
        if not s or s["impedance"]:
            continue
        need = s["track_width"] if sg["layer"] in ("F.Cu", "B.Cu") else s["inner_width"]
        if sg["w"] >= need - 1e-4:
            continue
        ends = [(sg["x1"], sg["y1"]), (sg["x2"], sg["y2"])]
        entry = [p for p in pads_by_net.get(sg["net"], []) if sg["layer"] in p["layers"]
                 and min(p["w"], p["h"]) < need and any(_on(p, x, y) for x, y in ends)]
        if entry and sg["w"] >= min(min(p["w"], p["h"]) for p in entry) - 1e-4:
            necks += 1
            continue
        ex["tracks_below_class_width"].append(
            f"{sg['net']} ({lookup(sg['net'])}) on {sg['layer']}: {sg['w']:g} mm < {need:g} mm at "
            f"({sg['x1']:.3f}, {sg['y1']:.3f})")

    zone_nets = b.zone_nets
    for n in nets:
        s = specs.get(lookup(n))
        if s and s["pour"] and n not in zone_nets:
            ex["required_pours_missing"].append(f"{n} ({lookup(n)}): {s['track_width']:g} mm outer, no copper zone")

    m = {"nets_in_default": len(ex["nets_in_default"]), "unknown_classes": len(ex["unknown_classes"]),
         "class_values_stale": len(ex["class_values_stale"]),
         "tracks_below_class_width": len(ex["tracks_below_class_width"]),
         "required_pours_missing": len(ex["required_pours_missing"]), "impedance_unset": len(ex["impedance_unset"])}

    lines = [f"# Net classes: {os.path.basename(board)}", "",
             f"{len(nets)} nets; {'+'.join(fabs)} design values; dT {a.dt:g} °C; copper {outer * 1000:.1f} µm outer / "
             f"{inner * 1000:.1f} µm inner. Tracks necking into a pad narrower than their class: {necks} (allowed).", "",
             "| Class | Nets | Outer | Inner | Clearance | Pour |", "|---|---|---|---|---|---|"]
    count = {}
    for n in nets:
        count[lookup(n)] = count.get(lookup(n), 0) + 1
    for cls in sorted(count):
        s = specs.get(cls)
        lines.append(f"| {cls} | {count[cls]} | " + (f"{s['track_width']:g} | {s['inner_width']:g} | {s['clearance']:g} | "
                                                     f"{'required' if s['pour'] else ''} |" if s else "– | – | – | – |"))
    failures, warnings = [], []
    lines += ["", "## Gates", "", "| Gate | Value | Limit | Result |", "|---|---|---|---|"]
    for k, (kind, limit) in GATES.items():
        ok = m[k] <= limit
        lines.append(f"| {k} | {m[k]} | ≤ {limit:g} ({kind}) | {'pass' if ok else ('FAIL' if kind == 'hard' else 'warn')} |")
        if not ok:
            (failures if kind == "hard" else warnings).append(f"{k} = {m[k]}")
    lines.append("")
    for k, rows in ex.items():
        if rows:
            lines.append(f"**{k}** (first {min(15, len(rows))} of {len(rows)})")
            lines += [f"- {r}" for r in rows[:15]]
            lines.append("")
    lines += ["## Result", "", ("**FAIL**: " + "; ".join(failures)) if failures else "**PASS**"]
    if warnings:
        lines.append("Warnings: " + "; ".join(warnings))
    text = "\n".join(lines) + "\n"
    if a.report:
        with open(a.report, "w") as f:
            f.write(text)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(dict(metrics=m, examples=ex, failures=failures, warnings=warnings), f, indent=2)
    print(text)
    return 1 if failures else 0


def cmd_size(a):
    o = width_mm(a.amps, a.dt, a.outer_mm)
    i = width_mm(a.amps, a.dt, a.inner_mm)
    pour = o >= width_mm(POUR_AMPS_1OZ, a.dt, OZ_MM)
    print(f"{a.amps:g} A, dT {a.dt:g} °C: outer {o:.3f} mm ({a.outer_mm * 1000:.1f} µm), inner {i:.3f} mm "
          f"({a.inner_mm * 1000:.1f} µm){'; a pour (D21)' if pour else ''}; vias per layer change ≥ {math.ceil(a.amps)} "
          "(1 A per 0.3 mm via, power-pcb-layout §3.5)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("size", help="IPC-2221 width for a current")
    s.add_argument("amps", type=float)
    s.add_argument("--dt", type=float, default=DT)
    s.add_argument("--outer-mm", type=float, default=DEFAULT_OUTER_MM)
    s.add_argument("--inner-mm", type=float, default=DEFAULT_INNER_MM)
    s = sub.add_parser("assign", help="write the schematic's net-class directives into the project, without KiCad")
    s.add_argument("path", help="project.kicad_pro (its root schematic sits next to it)")
    for name in ("apply", "check"):
        p = sub.add_parser(name)
        p.add_argument("path" if name == "apply" else "board")
        p.add_argument("--dt", type=float, default=DT, help="temperature rise, °C (default 10, D21)")
        p.add_argument("--fab", help="fab profile(s) for the design values (default: the ones pcb_rules apply recorded, else jlcpcb)")
        p.add_argument("--allow", help="non-standard class names to accept, comma-separated")
        if name == "check":
            p.add_argument("--gate", action="append", metavar="NAME=LIMIT")
            p.add_argument("--report")
            p.add_argument("--json")
    a = ap.parse_args(argv)
    return {"size": cmd_size, "assign": cmd_assign, "apply": cmd_apply, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
