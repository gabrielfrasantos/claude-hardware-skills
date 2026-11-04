#!/usr/bin/env python3
"""pcb_rules.py: fab design rules and a layout-quality gate for KiCad boards.

    pcb_rules.py profiles
    pcb_rules.py apply  <board.kicad_pcb | project.kicad_pro> --fab jlcpcb[,seeed] [--layers N] [--netclasses]
    pcb_rules.py check  <board.kicad_pcb> [--fab ...] [--allow-unrouted] [--no-drc] [--report r.md] [--json r.json]

apply   writes the fab's minimums into the project's Board Setup constraints, a managed block of
        custom rules into <project>.kicad_dru (fab rules KiCad has no Board Setup field for, plus the
        acute-angle quality rule), optionally the Default net class (design values), and the solder-mask
        minimum web into the board's setup. It then proves the rules file loads (KiCad silently ignores
        a rules file it cannot parse) by running DRC once with a canary rule.

check   runs KiCad's DRC (zones refilled, schematic parity) and the geometry checks DRC cannot do:
        off-grid track angles, tiny jogs, segments and vias per connection, detours, layer direction.
        Exit status 1 when a hard gate fails, so it can gate CI.

KiCad 8+ kicad-cli is needed for DRC (set --kicad-cli or $KICAD_CLI). The geometry checks parse the
.kicad_pcb directly (KiCad 7-10 formats) and need no KiCad installation. Standard library only.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(HERE, "..", "profiles")
BEGIN = "# BEGIN pcb_rules managed block"
END = "# END pcb_rules managed block"

# Hard gates fail the check; soft gates are reported as warnings.
GATES = {
    "any_angle_segments": ("hard", 0),        # segments not on a 0/45/90/135 degree direction
    "acute_corners": ("hard", 0),             # interior angle < 90 degrees between connected segments
    "jogs": ("hard", 0),                      # zero-length segments and short offsets between parallel runs
    "short_segment_pct": ("soft", 10.0),      # % of interior segments shorter than SHORT_MM
    "segments_per_connection_p90": ("soft", 8.0),
    "vias_per_connection_max": ("soft", 4.0),
    "detour_p90": ("soft", 1.6),
}
ANGLE_TOL = 0.5     # degrees
JOG_MM = 0.25
SHORT_MM = 0.5


# ----------------------------------------------------------------------------------------------- profiles
def list_profiles():
    return sorted(f[:-5] for f in os.listdir(PROFILE_DIR) if f.endswith(".json"))


def load_profile(name):
    path = os.path.join(PROFILE_DIR, name + ".json")
    if not os.path.exists(path):
        sys.exit(f"unknown fab profile '{name}'; available: {', '.join(list_profiles())}")
    with open(path) as f:
        return json.load(f)


def combined_rules(fabs, layers):
    """Fab minimums and design values for one or more fabs: the strictest (largest) value of each."""
    key = "2" if layers <= 2 else "4+"
    fab_min, design, notes = {}, {}, []
    for name in fabs:
        p = load_profile(name)
        lay = p["layers"][key]
        for k, v in lay["fab_min"].items():
            fab_min[k] = max(fab_min.get(k, 0.0), v)
        for k, v in lay["design"].items():
            design[k] = max(design.get(k, 0.0), v)
        notes.append(f"{p['title']} (checked {p['fetched']}): {', '.join(p['sources'])}")
    return fab_min, design, notes


# ----------------------------------------------------------------------------------------------- s-expr
_TOK = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


def parse_sexpr(text):
    stack, cur = [], []
    for m in _TOK.finditer(text):
        t = m.group(0)
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        elif t[0] == '"':
            cur.append(t[1:-1].replace('\\"', '"'))
        else:
            cur.append(t)
    return cur[0]


def child(node, key):
    for c in node:
        if isinstance(c, list) and c and c[0] == key:
            return c
    return None


def children(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def is_locked(node):
    if "locked" in node[1:3]:
        return True
    lk = child(node, "locked")
    return bool(lk and len(lk) > 1 and lk[1] == "yes")


# ----------------------------------------------------------------------------------------------- board
class Board:
    def __init__(self, path=None, text=None):
        if text is None:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        root = parse_sexpr(text)
        self.net_names = {}
        for n in children(root, "net"):
            if len(n) >= 3:
                self.net_names[n[1]] = n[2]
        self.copper_layers = []
        lay = child(root, "layers")
        for entry in lay[1:] if lay else []:
            if isinstance(entry, list) and len(entry) >= 2 and str(entry[1]).endswith(".Cu"):
                self.copper_layers.append(entry[1])
        self.segments, self.arcs, self.vias, self.pads, self.zone_nets = [], [], [], [], set()
        for node in root:
            if not isinstance(node, list) or not node:
                continue
            kind = node[0]
            if kind == "segment":
                s, e = child(node, "start"), child(node, "end")
                self.segments.append(dict(x1=float(s[1]), y1=float(s[2]), x2=float(e[1]), y2=float(e[2]),
                                          w=float(child(node, "width")[1]), layer=child(node, "layer")[1],
                                          net=self._net(node), locked=is_locked(node)))
            elif kind == "arc":
                s, e, m = child(node, "start"), child(node, "end"), child(node, "mid")
                self.arcs.append(dict(x1=float(s[1]), y1=float(s[2]), x2=float(e[1]), y2=float(e[2]),
                                      xm=float(m[1]), ym=float(m[2]), layer=child(node, "layer")[1],
                                      net=self._net(node)))
            elif kind == "via":
                at = child(node, "at")
                self.vias.append(dict(x=float(at[1]), y=float(at[2]), net=self._net(node),
                                      d=float(child(node, "size")[1])))
            elif kind == "zone":
                nn = child(node, "net_name")
                self.zone_nets.add(nn[1] if nn else self._net(node))
            elif kind == "footprint":
                self._footprint(node)

    def _net(self, node):
        n = child(node, "net")
        if not n or len(n) < 2:
            return ""
        if len(n) >= 3:                       # (net 12 "name") in footprints/pads (KiCad 7)
            return n[2]
        v = n[1]
        return self.net_names.get(v, v)       # (net 12) -> table, (net "name") KiCad 10

    def _footprint(self, fp):
        at = child(fp, "at")
        fx, fy = float(at[1]), float(at[2])
        frot = float(at[3]) if len(at) > 3 else 0.0
        c, s = math.cos(math.radians(frot)), math.sin(math.radians(frot))
        ref = ""
        for p in children(fp, "property"):
            if len(p) > 2 and p[1] == "Reference":
                ref = p[2]
        for t in children(fp, "fp_text"):
            if len(t) > 2 and t[1] == "reference":
                ref = t[2]
        for pad in children(fp, "pad"):
            pat = child(pad, "at")
            dx, dy = float(pat[1]), float(pat[2])
            size = child(pad, "size")
            # KiCad stores pad offsets in the footprint frame; rotation is counter-clockwise on a y-down board
            x = fx + dx * c + dy * s
            y = fy - dx * s + dy * c
            self.pads.append(dict(x=x, y=y, r=max(float(size[1]), float(size[2])) / 2 if size else 0.5,
                                  net=self._net(pad), ref=ref, num=pad[1], kind=pad[2]))


# ----------------------------------------------------------------------------------------------- geometry
def _key(x, y):
    return (round(x * 1000), round(y * 1000))   # 1 um


def _seg_len(s):
    return math.hypot(s["x2"] - s["x1"], s["y2"] - s["y1"])


def _octilinear_dev(s):
    a = math.degrees(math.atan2(s["y2"] - s["y1"], s["x2"] - s["x1"])) % 45.0
    return min(a, 45.0 - a)


def _mst_manhattan(points):
    pts = list({(round(x, 3), round(y, 3)) for x, y in points})
    if len(pts) < 2:
        return 0.0
    inside, dist, total = {0}, {i: abs(pts[i][0] - pts[0][0]) + abs(pts[i][1] - pts[0][1]) for i in range(1, len(pts))}, 0.0
    while dist:
        j = min(dist, key=dist.get)
        total += dist.pop(j)
        inside.add(j)
        for i in dist:
            d = abs(pts[i][0] - pts[j][0]) + abs(pts[i][1] - pts[j][1])
            if d < dist[i]:
                dist[i] = d
    return total


def _percentile(vals, q):
    if not vals:
        return 0.0
    v = sorted(vals)
    return v[min(len(v) - 1, int(round(q / 100.0 * (len(v) - 1))))]


def geometry_report(board):
    segs = [s for s in board.segments if _seg_len(s) > 1e-6]
    near_pad = defaultdict(list)                       # coarse 1 mm grid of pads and vias
    for p in board.pads:
        near_pad[(int(p["x"]), int(p["y"]))].append((p["x"], p["y"], p["r"] + 0.05))
    for v in board.vias:
        near_pad[(int(v["x"]), int(v["y"]))].append((v["x"], v["y"], v["d"] / 2 + 0.05))

    def on_pad_or_via(x, y):
        for gx in (int(x) - 1, int(x), int(x) + 1):
            for gy in (int(y) - 1, int(y), int(y) + 1):
                for px, py, r in near_pad.get((gx, gy), ()):
                    if math.hypot(px - x, py - y) <= r:
                        return True
        return False

    nodes = defaultdict(list)                          # segment ends meeting at a point
    for s in segs:
        nodes[(s["layer"], s["net"], _key(s["x1"], s["y1"]))].append((s, 0))
        nodes[(s["layer"], s["net"], _key(s["x2"], s["y2"]))].append((s, 1))

    def neighbour_dir(s, end):
        k = (s["layer"], s["net"], _key(s["x1"], s["y1"]) if end == 0 else _key(s["x2"], s["y2"]))
        others = [(o, e) for o, e in nodes[k] if o is not s]
        if len(others) != 1:
            return None
        o, e = others[0]
        # direction pointing away from the shared point
        return (o["x2"] - o["x1"], o["y2"] - o["y1"]) if e == 0 else (o["x1"] - o["x2"], o["y1"] - o["y2"])

    any_angle, jogs, short, interior = [], [], 0, 0
    jogs += [s for s in board.segments if _seg_len(s) <= 1e-6]   # zero-length leftovers
    for s in segs:
        L = _seg_len(s)
        if L >= 0.05 and _octilinear_dev(s) > ANGLE_TOL:
            any_angle.append(s)
        terminal = on_pad_or_via(s["x1"], s["y1"]) or on_pad_or_via(s["x2"], s["y2"])
        if terminal:
            continue
        interior += 1
        if L < SHORT_MM:
            short += 1
        if L < JOG_MM:
            a, b = neighbour_dir(s, 0), neighbour_dir(s, 1)
            if a and b:
                # a jog: the runs before and after are parallel (a sideways step), not a 45-degree miter
                cross = a[0] * b[1] - a[1] * b[0]
                if abs(cross) <= 1e-3 * math.hypot(*a) * math.hypot(*b):
                    jogs.append(s)
    acute = []                                         # every pair of track ends meeting off a pad or via
    for (layer, net, k), ends in nodes.items():
        if len(ends) < 2 or on_pad_or_via(k[0] / 1000, k[1] / 1000):
            continue
        vecs = []
        for s, end in ends:
            v = (s["x2"] - s["x1"], s["y2"] - s["y1"]) if end == 0 else (s["x1"] - s["x2"], s["y1"] - s["y2"])
            n = math.hypot(*v)
            if n > 0:
                vecs.append((v[0] / n, v[1] / n))
        worst = 180.0
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                dot = vecs[i][0] * vecs[j][0] + vecs[i][1] * vecs[j][1]
                worst = min(worst, math.degrees(math.acos(max(-1.0, min(1.0, dot)))))
        if worst < 90.0 - ANGLE_TOL:
            acute.append((layer, net, k[0] / 1000, k[1] / 1000, worst))

    per_net = defaultdict(lambda: dict(segments=0, vias=0, length=0.0, pads=[]))
    for s in segs:
        per_net[s["net"]]["segments"] += 1
        per_net[s["net"]]["length"] += _seg_len(s)
    for a in board.arcs:
        per_net[a["net"]]["length"] += math.hypot(a["xm"] - a["x1"], a["ym"] - a["y1"]) + math.hypot(a["x2"] - a["xm"], a["y2"] - a["ym"])
    for v in board.vias:
        per_net[v["net"]]["vias"] += 1
    for p in board.pads:
        if p["net"]:
            per_net[p["net"]]["pads"].append((p["x"], p["y"]))
    rows = []
    for net, d in per_net.items():
        if not net or net in board.zone_nets or d["segments"] == 0:
            continue
        conns = max(1, len(set(d["pads"])) - 1)
        mst = _mst_manhattan(d["pads"])
        rows.append(dict(net=net, segments=d["segments"], vias=d["vias"], connections=conns,
                         seg_per_conn=d["segments"] / conns, via_per_conn=d["vias"] / conns,
                         detour=(d["length"] / mst) if mst > 1.0 else None, length=d["length"]))

    direction = {}
    for layer in board.copper_layers:
        h = v = dgl = 0.0
        for s in segs:
            if s["layer"] != layer:
                continue
            L = _seg_len(s)
            a = math.degrees(math.atan2(abs(s["y2"] - s["y1"]), abs(s["x2"] - s["x1"])))
            if a < ANGLE_TOL:
                h += L
            elif a > 90 - ANGLE_TOL:
                v += L
            else:
                dgl += L
        tot = h + v + dgl
        if tot > 0:
            direction[layer] = dict(horizontal=100 * h / tot, vertical=100 * v / tot, diagonal=100 * dgl / tot, length_mm=tot)

    metrics = {
        "segments": len(segs), "vias": len(board.vias),
        "any_angle_segments": len(any_angle), "acute_corners": len(acute), "jogs": len(jogs),
        "short_segment_pct": (100.0 * short / interior) if interior else 0.0,
        "segments_per_connection_p90": _percentile([r["seg_per_conn"] for r in rows], 90),
        "vias_per_connection_max": max([r["via_per_conn"] for r in rows], default=0.0),
        "detour_p90": _percentile([r["detour"] for r in rows if r["detour"]], 90),
    }
    examples = {
        "any_angle_segments": [(s["layer"], s["net"], round(s["x1"], 3), round(s["y1"], 3), round(_octilinear_dev(s), 1)) for s in any_angle[:15]],
        "acute_corners": [(l, n, x, y, round(a, 1)) for l, n, x, y, a in acute[:15]],
        "jogs": [(s["layer"], s["net"], round(s["x1"], 3), round(s["y1"], 3), round(_seg_len(s), 3)) for s in jogs[:15]],
    }
    worst = {
        "segments_per_connection": sorted(rows, key=lambda r: -r["seg_per_conn"])[:10],
        "detour": sorted([r for r in rows if r["detour"]], key=lambda r: -r["detour"])[:10],
        "vias_per_connection": sorted(rows, key=lambda r: -r["via_per_conn"])[:10],
    }
    return metrics, examples, worst, direction


# ----------------------------------------------------------------------------------------------- kicad-cli
def find_cli(arg):
    for c in (arg, os.environ.get("KICAD_CLI"), shutil.which("kicad-cli")):
        if c:
            return c
    return None


def run_drc(cli, board, refill=True, parity=True):
    out = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
    args = [cli, "pcb", "drc", "--format", "json", "--severity-all", "-o", out]
    if refill:
        args.append("--refill-zones")
    sch = os.path.splitext(board)[0] + ".kicad_sch"
    if parity and os.path.exists(sch):
        args.append("--schematic-parity")
    r = subprocess.run(args + [board], capture_output=True, text=True)
    if not os.path.exists(out) or os.path.getsize(out) == 0:
        sys.exit(f"kicad-cli DRC failed:\n{r.stdout}\n{r.stderr}")
    with open(out) as f:
        data = json.load(f)
    os.unlink(out)
    return data


def summarize_drc(data):
    by = Counter()
    for v in data.get("violations", []):
        by[(v.get("severity", "error"), v.get("type", "?"))] += 1
    parity = Counter(v.get("severity", "error") for v in data.get("schematic_parity", []))
    return dict(by_type=by, unconnected=len(data.get("unconnected_items", [])),
                parity_errors=parity.get("error", 0), parity_warnings=parity.get("warning", 0),
                errors=sum(n for (sev, _), n in by.items() if sev == "error"),
                version=data.get("kicad_version", "?"))


# ----------------------------------------------------------------------------------------------- apply
def project_paths(path):
    base = os.path.splitext(os.path.abspath(path))[0]
    return base + ".kicad_pro", base + ".kicad_pcb", base + ".kicad_dru"


def dru_block(fab_min, fabs, layers, low_classes):
    """Custom rules for fab limits that Board Setup has no field for.

    Two KiCad behaviours shape this block (both verified on KiCad 10.0.6):
    - a custom-rule constraint replaces the net-class value and the Board Setup minimum, even when it is
      smaller, so a blanket pad-to-pad clearance rule would lower a high-voltage class's clearance.
      The pad rule therefore only matches pads whose net classes are all below the fab minimum.
    - when several rules match, the one later in the file wins, so this block goes first and any rule
      the user writes after it takes precedence.
    """
    mm = lambda v: f"{v:g}mm"
    pad_pad = max(fab_min["smd_pad_to_pad"], fab_min["clearance"])
    lines = [f"{BEGIN} ({'+'.join(fabs)}, {'2' if layers <= 2 else '4+'} layers). Re-run pcb_rules.py apply to change;",
             "# rules you add below this block override it.",
             '(rule "fab: plated pad annular ring"',
             "  (condition \"A.Type == 'Pad' && A.Pad_Type == 'Through-hole'\")",
             f"  (constraint annular_width (min {mm(fab_min['pth_annular'])})))",
             '(rule "fab: pad hole to pad hole (different nets)"',
             "  (condition \"A.Type == 'Pad' && B.Type == 'Pad' && (A.NetName != B.NetName || A.NetName == '')\")",
             f"  (constraint hole_to_hole (min {mm(fab_min['pad_hole_to_hole'])})))",
             '(rule "fab: plated pad hole to copper"',
             "  (condition \"A.Type == 'Pad' && A.Pad_Type == 'Through-hole'\")",
             f"  (constraint hole_clearance (min {mm(fab_min['pth_to_track'])})))",
             '(rule "fab: NPTH minimum drill"',
             "  (condition \"A.Type == 'Pad' && A.Pad_Type == 'NPTH, mechanical'\")",
             f"  (constraint hole_size (min {mm(fab_min['npth_min_drill'])})))"]
    if low_classes:
        def any_of(side):
            return "(" + " || ".join(f"{side}.NetClass == '{c}'" for c in low_classes) + ")"
        lines += [f'(rule "fab: pad to pad (net classes below {pad_pad:g} mm)"',
                  f"  (condition \"A.Type == 'Pad' && B.Type == 'Pad' && {any_of('A')} && {any_of('B')}\")",
                  f"  (constraint clearance (min {mm(pad_pad)})))"]
    if "inner_track" in fab_min:
        lines += ['(rule "fab: inner-layer track width"', "  (layer inner)",
                  f"  (constraint track_width (min {mm(fab_min['inner_track'])})))"]
    lines += ['(rule "quality: no acute track corners"',
              "  (constraint track_angle (min 90)))",
              END]
    return "\n".join(lines) + "\n"


def write_dru(path, block):
    text = ""
    if os.path.exists(path):
        with open(path) as f:
            text = f.read()
        text = re.sub(r"\n*" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "\n", text, flags=re.S)
    m = re.search(r"\(version\s+\d+\)\s*\n?", text)
    if m:
        head, tail = text[:m.end()], text[m.end():]
    else:
        head, tail = "(version 1)\n", text
    text = head.rstrip("\n") + "\n\n" + block + ("\n" + tail.lstrip("\n") if tail.strip() else "")
    with open(path, "w") as f:
        f.write(text)


def set_mask_web(board_path, web):
    with open(board_path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"\(setup\b", text)
    if not m:
        return False
    if re.search(r"\(solder_mask_min_width [^)]*\)", text[m.start():m.start() + 4000]):
        head, tail = text[:m.start()], text[m.start():]
        tail = re.sub(r"\(solder_mask_min_width [^)]*\)", f"(solder_mask_min_width {web:g})", tail, count=1)
        text = head + tail
    else:
        indent = re.search(r"\n(\s*)\(", text[m.end():m.end() + 200])
        ind = indent.group(1) if indent else "\t\t"
        text = text[:m.end()] + f"\n{ind}(solder_mask_min_width {web:g})" + text[m.end():]
    with open(board_path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def validate_rules(cli, pro, board, dru):
    """KiCad drops a rules file it cannot parse without failing DRC, so prove it loads with a canary rule."""
    tmp = tempfile.mkdtemp()
    base = os.path.join(tmp, "v")
    shutil.copy(pro, base + ".kicad_pro")
    shutil.copy(board, base + ".kicad_pcb")
    with open(dru) as f:
        rules = f.read()
    with open(base + ".kicad_dru", "w") as f:
        f.write(rules + '\n(rule "pcb_rules canary"\n  (constraint edge_clearance (min 1000mm)))\n')
    data = run_drc(cli, base + ".kicad_pcb", refill=False, parity=False)
    shutil.rmtree(tmp, ignore_errors=True)
    return any("canary" in v.get("description", "") for v in data.get("violations", []))


def cmd_apply(a):
    pro, board, dru = project_paths(a.path)
    if not os.path.exists(pro):
        sys.exit(f"no project file {pro}")
    fabs = a.fab.split(",")
    layers = a.layers or (len(Board(board).copper_layers) if os.path.exists(board) else 2)
    fab_min, design, notes = combined_rules(fabs, layers)
    with open(pro) as f:
        pj = json.load(f)
    ds = pj.setdefault("board", {}).setdefault("design_settings", {})
    rules = ds.setdefault("rules", {})
    rules.update({
        "min_clearance": fab_min["clearance"], "min_track_width": fab_min["track"],
        "min_via_annular_width": fab_min["via_annular"], "min_via_diameter": fab_min["via_diameter"],
        "min_through_hole_diameter": fab_min["min_drill"], "min_hole_to_hole": fab_min["hole_to_hole"],
        "min_hole_clearance": fab_min["hole_clearance"], "min_copper_edge_clearance": fab_min["edge_clearance"],
        "min_silk_clearance": fab_min["silk_to_pad"], "min_text_height": fab_min["silk_text_height"],
        "min_text_thickness": fab_min["silk_line"],
    })
    sev = ds.setdefault("rule_severities", {})
    for k in ("track_angle", "silk_overlap", "silk_over_copper", "text_height", "text_thickness"):
        if sev.get(k) == "ignore":
            sev[k] = "warning"
    if a.netclasses:
        for nc in pj.get("net_settings", {}).get("classes", []):
            if nc.get("name") == "Default":
                nc["track_width"] = max(nc.get("track_width", 0), design["track"])
                nc["clearance"] = max(nc.get("clearance", 0), design["clearance"])
                nc["via_drill"] = max(nc.get("via_drill", 0), design["via_drill"])
                nc["via_diameter"] = max(nc.get("via_diameter", 0), design["via_diameter"])
    with open(pro, "w") as f:
        json.dump(pj, f, indent=2)
        f.write("\n")
    pad_pad = max(fab_min["smd_pad_to_pad"], fab_min["clearance"])
    low = [nc["name"] for nc in pj.get("net_settings", {}).get("classes", [])
           if nc.get("clearance") is not None and nc["clearance"] < pad_pad - 1e-9]
    write_dru(dru, dru_block(fab_min, fabs, layers, low))
    web_ok = os.path.exists(board) and set_mask_web(board, fab_min["mask_bridge"])
    print(f"applied {'+'.join(fabs)} ({layers} copper layers) to {os.path.basename(pro)}")
    for n in notes:
        print("  source:", n)
    print(f"  constraints: track {fab_min['track']} / clearance {fab_min['clearance']} / via {fab_min['via_drill']}/{fab_min['via_diameter']} "
          f"/ edge {fab_min['edge_clearance']} mm; mask web {fab_min['mask_bridge']} mm{' (board setup)' if web_ok else ' (set it in Board Setup)'}")
    print(f"  design values for net classes: track {design['track']} / clearance {design['clearance']} / via {design['via_drill']}/{design['via_diameter']} mm"
          + ("" if a.netclasses else "  (use --netclasses to write them to Default)"))
    cli = find_cli(a.kicad_cli)
    if cli and os.path.exists(board) and not a.no_validate:
        ok = validate_rules(cli, pro, board, dru)
        print(f"  {os.path.basename(dru)}: {'loads OK' if ok else 'NOT LOADED by KiCad: check its syntax'}")
        if not ok:
            sys.exit(1)
    elif not cli:
        print("  kicad-cli not found: rules file not validated (set --kicad-cli or $KICAD_CLI)")


# ----------------------------------------------------------------------------------------------- check
def cmd_check(a):
    for g in a.gate or []:
        k, _, v = g.partition("=")
        if k not in GATES:
            sys.exit(f"unknown gate '{k}'; gates: {', '.join(GATES)}")
        GATES[k] = (GATES[k][0], float(v))
    board = os.path.abspath(a.board)
    b = Board(board)
    metrics, examples, worst, direction = geometry_report(b)
    lines = [f"# PCB rules check: {os.path.basename(board)}", ""]
    failures, warnings = [], []
    drc = None
    if not a.no_drc:
        cli = find_cli(a.kicad_cli)
        if not cli:
            sys.exit("kicad-cli not found (set --kicad-cli or $KICAD_CLI), or use --no-drc")
        drc = summarize_drc(run_drc(cli, board, refill=not a.no_refill))
        errs = drc["errors"] + drc["parity_errors"] + (0 if a.allow_unrouted else drc["unconnected"])
        lines += [f"## KiCad DRC ({drc['version']})", "",
                  f"- errors: **{drc['errors']}**, unconnected: **{drc['unconnected']}**"
                  f"{' (allowed)' if a.allow_unrouted else ''}, schematic parity: {drc['parity_errors']} errors / {drc['parity_warnings']} warnings", ""]
        for (sev, typ), n in sorted(drc["by_type"].items(), key=lambda kv: (kv[0][0] != "error", -kv[1])):
            lines.append(f"  - {sev} `{typ}`: {n}")
        lines.append("")
        if errs:
            failures.append(f"DRC: {errs} error(s)")
    lines += ["## Layout quality", "", "| Metric | Value | Gate | Result |", "|---|---|---|---|"]
    for k, (kind, limit) in GATES.items():
        val = metrics[k]
        ok = val <= limit
        shown = f"{val:.2f}" if isinstance(val, float) else str(val)
        lines.append(f"| {k} | {shown} | ≤ {limit} ({kind}) | {'pass' if ok else ('FAIL' if kind == 'hard' else 'warn')} |")
        if not ok:
            (failures if kind == "hard" else warnings).append(f"{k} = {shown} (limit {limit})")
    lines += ["", f"{metrics['segments']} track segments, {metrics['vias']} vias. Angles within ±{ANGLE_TOL}° of 0/45/90/135° count as on-grid; "
              f"jogs are interior segments < {JOG_MM} mm; short = interior segments < {SHORT_MM} mm.", ""]
    for k, ex in examples.items():
        if ex:
            lines.append(f"**{k}** (first {len(ex)}: layer, net, x, y, value)")
            lines += [f"- {e}" for e in ex]
            lines.append("")
    if direction:
        lines += ["## Direction per copper layer (% of routed length)", "", "| Layer | Horizontal | Vertical | Other | Length mm |", "|---|---|---|---|---|"]
        for layer, d in direction.items():
            lines.append(f"| {layer} | {d['horizontal']:.0f} | {d['vertical']:.0f} | {d['diagonal']:.0f} | {d['length_mm']:.0f} |")
        lines.append("")
    lines += ["## Worst nets", "", "| Net | Segments/conn | Vias/conn | Detour |", "|---|---|---|---|"]
    seen = set()
    for r in worst["segments_per_connection"] + worst["detour"] + worst["vias_per_connection"]:
        if r["net"] in seen:
            continue
        seen.add(r["net"])
        lines.append(f"| {r['net']} | {r['seg_per_conn']:.1f} | {r['via_per_conn']:.1f} | {r['detour']:.2f} |" if r["detour"]
                     else f"| {r['net']} | {r['seg_per_conn']:.1f} | {r['via_per_conn']:.1f} | – |")
    lines += ["", "## Result", "", ("**FAIL**: " + "; ".join(failures)) if failures else "**PASS**"]
    if warnings:
        lines.append("Warnings: " + "; ".join(warnings))
    text = "\n".join(lines) + "\n"
    if a.report:
        with open(a.report, "w") as f:
            f.write(text)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(dict(metrics=metrics, examples=examples, direction=direction, failures=failures, warnings=warnings,
                           drc=None if drc is None else dict(drc, by_type={f"{s}:{t}": n for (s, t), n in drc["by_type"].items()})),
                      f, indent=2)
    print(text)
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("profiles", help="list fab profiles")
    p = sub.add_parser("apply", help="write fab rules into a KiCad project")
    p.add_argument("path")
    p.add_argument("--fab", default="jlcpcb", help="profile name(s), comma-separated for the strictest of several")
    p.add_argument("--layers", type=int, help="copper layers (default: read from the board)")
    p.add_argument("--netclasses", action="store_true", help="raise the Default net class to the design values")
    p.add_argument("--kicad-cli")
    p.add_argument("--no-validate", action="store_true")
    c = sub.add_parser("check", help="DRC + layout-quality gate")
    c.add_argument("board")
    c.add_argument("--kicad-cli")
    c.add_argument("--no-drc", action="store_true", help="geometry checks only (no KiCad needed)")
    c.add_argument("--no-refill", action="store_true")
    c.add_argument("--allow-unrouted", action="store_true", help="do not fail on unconnected items (layout in progress)")
    c.add_argument("--gate", action="append", metavar="NAME=LIMIT", help="override a gate limit, e.g. --gate any_angle_segments=4")
    c.add_argument("--report", help="write the Markdown report here")
    c.add_argument("--json", help="write metrics as JSON here")
    a = ap.parse_args()
    if a.cmd == "profiles":
        for n in list_profiles():
            p = load_profile(n)
            print(f"{n:10s} {p['title']} (checked {p['fetched']})")
        return 0
    if a.cmd == "apply":
        cmd_apply(a)
        return 0
    return cmd_check(a)


if __name__ == "__main__":
    sys.exit(main())
