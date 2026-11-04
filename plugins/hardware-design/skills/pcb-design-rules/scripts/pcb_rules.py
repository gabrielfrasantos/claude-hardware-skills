#!/usr/bin/env python3
"""pcb_rules.py: fab design rules and a layout-quality gate for KiCad boards.

    pcb_rules.py profiles
    pcb_rules.py apply  <board.kicad_pcb | project.kicad_pro> --fab jlcpcb[,seeed] [--layers N] [--netclasses]
    pcb_rules.py check  <board.kicad_pcb> [--fab ...] [--allow-unrouted] [--no-drc] [--no-floor]
                        [--gate NAME=LIMIT] [--report r.md] [--json r.json]

apply   writes the fab's minimums into the project's Board Setup constraints, a managed block of custom
        rules into <project>.kicad_dru (fab rules Board Setup has no field for, plus the 45-degree corner
        rule), forces the copper-safety checks to error severity, optionally raises the Default net class
        to the design values, and sets the solder-mask minimum web in the board's setup. It then proves
        KiCad loads the rules file (KiCad silently ignores a rules file it cannot parse).

check   shorts and clearance: KiCad DRC on a temporary copy of the project with every copper-safety check
        forced to error, DRC exclusions of those checks removed, and all errors per track reported; then a
        fab-floor pass that flags copper and holes below the fab's absolute minimum whatever the project's
        rules say. Plus the geometry checks DRC cannot do: off-grid angles, 90-degree corners, junctions,
        jogs, segments and vias per connection, detours, layer direction.
        Exit status 1 when a hard gate fails, so it can gate CI.

KiCad 8+ kicad-cli is needed for DRC (--kicad-cli or $KICAD_CLI). With --no-drc the script parses the
.kicad_pcb itself (KiCad 7-10 formats): geometry gates plus a copper short/clearance check between tracks,
vias and pads (zones and custom-shaped pads need KiCad). Python 3 standard library only.
"""
import argparse
import fnmatch
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

# DRC checks that protect against shorts and unbuildable copper. check forces them to error severity.
COPPER_SAFETY = ["shorting_items", "tracks_crossing", "clearance", "hole_clearance", "hole_to_hole",
                 "copper_edge_clearance", "zones_intersect", "solder_mask_bridge", "creepage",
                 "annular_width", "track_width", "drill_out_of_range"]
SHORT_TYPES = {"shorting_items", "tracks_crossing"}
MIN_CORNER = 135   # degrees between connected segments: 180 = straight, 135 = 45-degree bend, 90 = right angle

# Hard gates fail the check; soft gates are reported as warnings.
GATES = {
    "shorts": ("hard", 0),                    # copper of different nets touching
    "clearance_violations": ("hard", 0),      # other copper-safety violations (gaps, holes, edge, mask)
    "below_fab_minimum": ("hard", 0),         # anything under the fab's absolute minimum, whatever the rules say
    "dangling": ("hard", 0),                  # tracks/vias connected at one end only (KiCad re-nets floating copper)
    "any_angle_segments": ("hard", 0),        # segments not on a 0/45/90/135 degree direction
    "acute_corners": ("hard", 0),             # tracks meeting at < 90 degrees
    "right_angle_corners": ("hard", 0),       # two segments meeting at < 135 degrees (90-degree corners)
    "track_junctions": ("hard", 0),           # three or more tracks meeting off a pad (tees, Y-branches, branches at vias)
    "jogs": ("hard", 0),                      # zero-length segments and short offsets between parallel runs
    "short_segment_pct": ("soft", 10.0),      # % of interior segments shorter than SHORT_MM
    "segments_per_connection_p90": ("soft", 8.0),
    "vias_per_connection_max": ("soft", 4.0),
    "detour_p90": ("soft", 1.6),
}
ANGLE_TOL = 0.5     # degrees
DRC_EPSILON = 0.0005  # mm; gaps this close to the limit pass, as in KiCad's DRC (matched on e-psu)
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


# ----------------------------------------------------------------------------------------------- shapes
# A copper shape is a "core" (a point, a segment or a convex polygon) inflated by a radius r. Tracks are
# segments + w/2, vias points + d/2, round/oval/roundrect pads exact, other pads their bounding rectangle.
def _bbox(pts, r):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r)


def shape_point(x, y, r):
    return dict(segs=[(x, y, x, y)], poly=None, r=r, bbox=(x - r, y - r, x + r, y + r))


def shape_seg(x1, y1, x2, y2, r):
    return dict(segs=[(x1, y1, x2, y2)], poly=None, r=r, bbox=_bbox([(x1, y1), (x2, y2)], r))


def shape_poly(pts, r):
    segs = [(pts[i][0], pts[i][1], pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1]) for i in range(len(pts))]
    return dict(segs=segs, poly=pts, r=r, bbox=_bbox(pts, r))


def _pt_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - x1 - t * dx, py - y1 - t * dy)


def _orient(ax, ay, bx, by, cx, cy):
    v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)


def _seg_seg(a, b):
    x1, y1, x2, y2 = a
    x3, y3, x4, y4 = b
    o1, o2 = _orient(x1, y1, x2, y2, x3, y3), _orient(x1, y1, x2, y2, x4, y4)
    o3, o4 = _orient(x3, y3, x4, y4, x1, y1), _orient(x3, y3, x4, y4, x2, y2)
    if o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4):
        return 0.0
    return min(_pt_seg(x1, y1, *b), _pt_seg(x2, y2, *b), _pt_seg(x3, y3, *a), _pt_seg(x4, y4, *a))


def _in_poly(x, y, poly):
    inside = False
    for i in range(len(poly)):
        (xa, ya), (xb, yb) = poly[i], poly[(i + 1) % len(poly)]
        if (ya > y) != (yb > y) and x < xa + (y - ya) * (xb - xa) / (yb - ya):
            inside = not inside
    return inside


def shape_gap(A, B):
    """Copper-to-copper gap in mm; <= 0 means the shapes touch or overlap."""
    if A["poly"] and any(_in_poly(s[0], s[1], A["poly"]) for s in B["segs"]):
        d = 0.0
    elif B["poly"] and any(_in_poly(s[0], s[1], B["poly"]) for s in A["segs"]):
        d = 0.0
    else:
        d = min(_seg_seg(s, t) for s in A["segs"] for t in B["segs"])
    return d - A["r"] - B["r"]


def pad_shape(x, y, rot, w, h, kind, rratio):
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))

    def tf(dx, dy):   # KiCad rotation: counter-clockwise on a y-down board
        return (x + dx * c + dy * s, y - dx * s + dy * c)

    if kind == "circle":
        return shape_point(x, y, w / 2)
    if kind == "oval":
        if abs(w - h) < 1e-9:
            return shape_point(x, y, w / 2)
        if w > h:
            (ax, ay), (bx, by) = tf(-(w - h) / 2, 0), tf((w - h) / 2, 0)
            return shape_seg(ax, ay, bx, by, h / 2)
        (ax, ay), (bx, by) = tf(0, -(h - w) / 2), tf(0, (h - w) / 2)
        return shape_seg(ax, ay, bx, by, w / 2)
    r = rratio * min(w, h) if kind == "roundrect" else 0.0
    iw, ih = w / 2 - r, h / 2 - r
    return shape_poly([tf(-iw, -ih), tf(iw, -ih), tf(iw, ih), tf(-iw, ih)], r)


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
                                      xm=float(m[1]), ym=float(m[2]), w=float(child(node, "width")[1]),
                                      layer=child(node, "layer")[1], net=self._net(node)))
            elif kind == "via":
                at, lays = child(node, "at"), child(node, "layers")
                self.vias.append(dict(x=float(at[1]), y=float(at[2]), net=self._net(node),
                                      d=float(child(node, "size")[1]),
                                      layers=self._span(lays[1:] if lays else ["F.Cu", "B.Cu"])))
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
            name = n[2]
        else:
            name = self.net_names.get(n[1], n[1])   # (net 12) -> table, (net "name") KiCad 10
        return name.replace("{slash}", "/")

    def _span(self, ends):
        idx = [self.copper_layers.index(l) for l in ends if l in self.copper_layers]
        if len(idx) < 2:
            return set(self.copper_layers)
        return set(self.copper_layers[min(idx):max(idx) + 1])

    def _pad_layers(self, names):
        out = set()
        for n in names:
            if n == "*.Cu":
                out |= set(self.copper_layers)
            elif n == "F&B.Cu":
                out |= {"F.Cu", "B.Cu"}
            elif n in self.copper_layers:
                out.add(n)
        return out

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
            prot = float(pat[3]) if len(pat) > 3 else 0.0     # pad angle in the file is absolute
            size = child(pad, "size")
            w, h = (float(size[1]), float(size[2])) if size else (1.0, 1.0)
            rr = child(pad, "roundrect_rratio")
            lays = child(pad, "layers")
            # pad offsets are in the footprint frame; rotation is counter-clockwise on a y-down board
            x = fx + dx * c + dy * s
            y = fy - dx * s + dy * c
            self.pads.append(dict(x=x, y=y, r=max(w, h) / 2, w=w, h=h, rot=prot, shape=pad[3] if len(pad) > 3 else "rect",
                                  rratio=float(rr[1]) if rr else 0.25, net=self._net(pad), ref=ref, num=pad[1],
                                  kind=pad[2], layers=self._pad_layers(lays[1:] if lays else [])))


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
    dist, total = {i: abs(pts[i][0] - pts[0][0]) + abs(pts[i][1] - pts[0][1]) for i in range(1, len(pts))}, 0.0
    while dist:
        j = min(dist, key=dist.get)
        total += dist.pop(j)
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


def _arc_chords(a, n=8):
    """Split an arc track into n straight chords (enough for clearance checks)."""
    (x1, y1), (xm, ym), (x2, y2) = (a["x1"], a["y1"]), (a["xm"], a["ym"]), (a["x2"], a["y2"])
    d = 2 * (x1 * (ym - y2) + xm * (y2 - y1) + x2 * (y1 - ym))
    if abs(d) < 1e-12:
        return [(x1, y1, x2, y2)]
    ux = ((x1 ** 2 + y1 ** 2) * (ym - y2) + (xm ** 2 + ym ** 2) * (y2 - y1) + (x2 ** 2 + y2 ** 2) * (y1 - ym)) / d
    uy = ((x1 ** 2 + y1 ** 2) * (x2 - xm) + (xm ** 2 + ym ** 2) * (x1 - x2) + (x2 ** 2 + y2 ** 2) * (xm - x1)) / d
    R = math.hypot(x1 - ux, y1 - uy)
    t1, tm, t2 = (math.atan2(y - uy, x - ux) for x, y in ((x1, y1), (xm, ym), (x2, y2)))
    sweep = (t2 - t1) % (2 * math.pi)
    if (tm - t1) % (2 * math.pi) > sweep:      # mid point not on the counter-clockwise path: go the other way
        sweep -= 2 * math.pi
    pts = [(ux + R * math.cos(t1 + sweep * i / n), uy + R * math.sin(t1 + sweep * i / n)) for i in range(n + 1)]
    return [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) for i in range(n)]


def copper_check(board, limit):
    """Shorts and gaps below `limit` between tracks, arcs, vias and pads of different nets (no zones)."""
    items = []
    for s in board.segments:
        items.append((s["net"], {s["layer"]}, shape_seg(s["x1"], s["y1"], s["x2"], s["y2"], s["w"] / 2),
                      f"track {s['net']} {s['layer']}"))
    for a in board.arcs:
        for c in _arc_chords(a):
            items.append((a["net"], {a["layer"]}, shape_seg(*c, a["w"] / 2), f"arc {a['net']} {a['layer']}"))
    for v in board.vias:
        items.append((v["net"], v["layers"], shape_point(v["x"], v["y"], v["d"] / 2), f"via {v['net']}"))
    for p in board.pads:
        if p["kind"] == "np_thru_hole" or not p["layers"]:
            continue
        items.append((p["net"], p["layers"], pad_shape(p["x"], p["y"], p["rot"], p["w"], p["h"], p["shape"], p["rratio"]),
                      f"pad {p['ref']}.{p['num']} {p['net']}"))
    nets = [n if n else f"<no net {i}>" for i, (n, *_rest) in enumerate(items)]
    cell = 1.0
    grid = defaultdict(list)
    for i, (_, _, sh, _) in enumerate(items):
        x0, y0, x1, y1 = sh["bbox"]
        for gx in range(int(math.floor((x0 - limit) / cell)), int(math.floor((x1 + limit) / cell)) + 1):
            for gy in range(int(math.floor((y0 - limit) / cell)), int(math.floor((y1 + limit) / cell)) + 1):
                grid[(gx, gy)].append(i)
    shorts, gaps, seen = [], [], set()
    for ids in grid.values():
        for ai in range(len(ids)):
            i = ids[ai]
            for j in ids[ai + 1:]:
                if nets[i] == nets[j] or (i, j) in seen:
                    continue
                seen.add((i, j))
                (_, li, A, di), (_, lj, B, dj) = items[i], items[j]
                common = li & lj
                if not common:
                    continue
                ax0, ay0, ax1, ay1 = A["bbox"]
                bx0, by0, bx1, by1 = B["bbox"]
                if ax0 - limit > bx1 or bx0 - limit > ax1 or ay0 - limit > by1 or by0 - limit > ay1:
                    continue
                g = shape_gap(A, B)
                if g < limit - DRC_EPSILON:
                    row = dict(a=di, b=dj, net_a=items[i][0], net_b=items[j][0], layer=sorted(common)[0],
                               gap=round(g, 4), near=(round(A["segs"][0][0], 3), round(A["segs"][0][1], 3)))
                    (shorts if g <= 1e-6 else gaps).append(row)
    return shorts, gaps


def geometry_report(board):
    segs = [s for s in board.segments if _seg_len(s) > 1e-6]
    pad_grid, via_grid = defaultdict(list), defaultdict(list)
    for p in board.pads:
        if p["layers"]:
            sh = pad_shape(p["x"], p["y"], p["rot"], p["w"], p["h"], p["shape"], p["rratio"])
            for gx in range(int(math.floor(sh["bbox"][0])), int(math.floor(sh["bbox"][2])) + 1):
                for gy in range(int(math.floor(sh["bbox"][1])), int(math.floor(sh["bbox"][3])) + 1):
                    pad_grid[(gx, gy)].append((sh, p["layers"]))
    for v in board.vias:
        via_grid[(int(math.floor(v["x"])), int(math.floor(v["y"])))].append((v["x"], v["y"], v["d"] / 2))

    def on_pad(x, y, layer=None):
        pt = shape_point(x, y, 0.0)
        for sh, lays in pad_grid.get((int(math.floor(x)), int(math.floor(y))), ()):
            if (layer is None or layer in lays) and shape_gap(sh, pt) <= 0.001:
                return True
        return False

    def on_via(x, y):
        gx, gy = int(math.floor(x)), int(math.floor(y))
        for ix in (gx - 1, gx, gx + 1):
            for iy in (gy - 1, gy, gy + 1):
                for vx, vy, r in via_grid.get((ix, iy), ()):
                    if math.hypot(vx - x, vy - y) <= r + 0.001:
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
        terminal = any(on_pad(x, y, s["layer"]) or on_via(x, y) for x, y in ((s["x1"], s["y1"]), (s["x2"], s["y2"])))
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

    # Corners and junctions, classified like KiCad's track_angle check: tracks meeting at a pad are exempt,
    # tracks meeting at a via are not.
    acute, right, junctions = [], [], []
    for (layer, net, k), ends in nodes.items():
        x, y = k[0] / 1000, k[1] / 1000
        if len(ends) < 2 or on_pad(x, y, layer):
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
        entry = (layer, net, x, y, round(worst, 1))
        if worst < 90.0 - ANGLE_TOL:
            acute.append(entry)
        elif len(vecs) >= 3 and worst < MIN_CORNER - ANGLE_TOL:
            junctions.append(entry)
        elif worst < MIN_CORNER - ANGLE_TOL:
            right.append(entry)

    per_net = defaultdict(lambda: dict(segments=0, vias=0, length=0.0, pads=[]))
    for s in segs:
        per_net[s["net"]]["segments"] += 1
        per_net[s["net"]]["length"] += _seg_len(s)
    for a in board.arcs:
        per_net[a["net"]]["length"] += sum(math.hypot(c[2] - c[0], c[3] - c[1]) for c in _arc_chords(a))
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
        "any_angle_segments": len(any_angle), "acute_corners": len(acute), "right_angle_corners": len(right),
        "track_junctions": len(junctions), "jogs": len(jogs),
        "short_segment_pct": (100.0 * short / interior) if interior else 0.0,
        "segments_per_connection_p90": _percentile([r["seg_per_conn"] for r in rows], 90),
        "vias_per_connection_max": max([r["via_per_conn"] for r in rows], default=0.0),
        "detour_p90": _percentile([r["detour"] for r in rows if r["detour"]], 90),
    }
    examples = {
        "any_angle_segments": [(s["layer"], s["net"], round(s["x1"], 3), round(s["y1"], 3), round(_octilinear_dev(s), 1)) for s in any_angle[:15]],
        "acute_corners": acute[:15],
        "right_angle_corners": right[:15],
        "track_junctions": junctions[:15],
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
    # --all-track-errors: by default KiCad reports only the first error on each track, so a short can hide
    # behind any other violation on the same track.
    args = [cli, "pcb", "drc", "--format", "json", "--severity-all", "--all-track-errors", "-o", out]
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


def project_copy(board):
    """Copy the board, project, rules and schematic files to a temp dir; returns (tmpdir, board copy)."""
    src = os.path.dirname(os.path.abspath(board))
    tmp = tempfile.mkdtemp(prefix="pcb_rules_")
    keep = ("*.kicad_pcb", "*.kicad_pro", "*.kicad_dru", "*.kicad_sch", "*.kicad_prl", "sym-lib-table", "fp-lib-table")
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not d.endswith("-backups") and not d.startswith(".") and not d.endswith(".pretty")]
        for f in files:
            if any(fnmatch.fnmatch(f, k) for k in keep):
                rel = os.path.relpath(os.path.join(root, f), src)
                os.makedirs(os.path.join(tmp, os.path.dirname(rel)), exist_ok=True)
                shutil.copy2(os.path.join(root, f), os.path.join(tmp, rel))
    return tmp, os.path.join(tmp, os.path.basename(board))


def force_copper_safety(pro_path):
    """In a project copy: copper-safety checks to error, their DRC exclusions removed. Returns exclusions removed."""
    if not os.path.exists(pro_path):
        return 0
    with open(pro_path) as f:
        pj = json.load(f)
    ds = pj.setdefault("board", {}).setdefault("design_settings", {})
    sev = ds.setdefault("rule_severities", {})
    for k in COPPER_SAFETY:
        sev[k] = "error"
    sev["items_not_allowed"] = "error"        # used by the fab-floor canary
    excl = ds.get("drc_exclusions", []) or []
    kept = [e for e in excl if (e if isinstance(e, str) else (e[0] if e else "")).split("|")[0] not in COPPER_SAFETY]
    ds["drc_exclusions"] = kept
    with open(pro_path, "w") as f:
        json.dump(pj, f, indent=2)
    return len(excl) - len(kept)


def floor_rules(fab_min):
    mm = lambda v: f"{v:g}mm"
    return "\n".join([
        "(version 1)",
        '(rule "pcb_rules canary"',
        "  (constraint disallow footprint track))",
        f'(rule "fab floor: copper clearance"\n  (constraint clearance (min {mm(fab_min["clearance"])})))',
        f'(rule "fab floor: track width"\n  (constraint track_width (min {mm(fab_min["track"])})))',
        f'(rule "fab floor: hole to copper"\n  (constraint hole_clearance (min {mm(fab_min["hole_clearance"])})))',
        f'(rule "fab floor: hole to hole"\n  (constraint hole_to_hole (min {mm(fab_min["hole_to_hole"])})))',
        f'(rule "fab floor: copper to edge"\n  (constraint edge_clearance (min {mm(fab_min["edge_clearance"])})))',
        f'(rule "fab floor: drill"\n  (constraint hole_size (min {mm(fab_min["min_drill"])})))',
        f'(rule "fab floor: via annular ring"\n  (condition "A.Type == \'Via\'")\n  (constraint annular_width (min {mm(fab_min["via_annular"])})))',
    ]) + "\n"


def managed_fabs(dru_path):
    """Fabs recorded by `apply` in the managed block header, or []."""
    if not os.path.exists(dru_path):
        return []
    with open(dru_path) as f:
        m = re.search(re.escape(BEGIN) + r" \(([^,]+),", f.read())
    return m.group(1).split("+") if m else []


def _violation_row(v):
    items = "; ".join(f"{i.get('description', '')} @ ({i['pos']['x']:.3f}, {i['pos']['y']:.3f})" for i in v.get("items", []))
    return f"`{v.get('type')}`: {v.get('description', '')} — {items}"


# ----------------------------------------------------------------------------------------------- apply
def project_paths(path):
    base = os.path.splitext(os.path.abspath(path))[0]
    return base + ".kicad_pro", base + ".kicad_pcb", base + ".kicad_dru"


def dru_block(fab_min, fabs, layers, low_classes):
    """Custom rules for fab limits that Board Setup has no field for, plus the corner rule.

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
    # 180 = straight, 135 = 45-degree bend, 90 = right angle. KiCad also flags tees, Y-branches and turns at
    # vias with this rule, but not tracks meeting at a pad. Write (min 135), never (min 135deg): the unit
    # makes KiCad drop the whole file without an error.
    lines += ['(rule "quality: 45-degree corners only (no 90-degree or acute corners, no mid-track branches)"',
              f"  (constraint track_angle (min {MIN_CORNER})))",
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
    for k in COPPER_SAFETY + ["track_angle"]:
        sev[k] = "error"
    for k in ("silk_overlap", "silk_over_copper", "text_height", "text_thickness"):
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
    print(f"  copper-safety checks set to error: {', '.join(COPPER_SAFETY)}; corners: track_angle min {MIN_CORNER}")
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
    pro, _, dru = project_paths(board)
    b = Board(board)
    metrics, examples, worst, direction = geometry_report(b)
    fabs = a.fab.split(",") if a.fab else managed_fabs(dru)
    fab_min = combined_rules(fabs, len(b.copper_layers))[0] if fabs else None
    lines = [f"# PCB rules check: {os.path.basename(board)}", ""]
    failures, warnings, drc_info, copper = [], [], None, {}

    if not a.no_drc:
        cli = find_cli(a.kicad_cli)
        if not cli:
            sys.exit("kicad-cli not found (set --kicad-cli or $KICAD_CLI), or use --no-drc")
        tmp, copy = project_copy(board)
        try:
            removed = force_copper_safety(os.path.splitext(copy)[0] + ".kicad_pro")
            data = run_drc(cli, copy, refill=not a.no_refill)
            floor = None
            if fab_min and not a.no_floor:
                with open(os.path.splitext(copy)[0] + ".kicad_dru", "w") as f:
                    f.write(floor_rules(fab_min))
                fdata = run_drc(cli, copy, refill=not a.no_refill, parity=False)
                vs = fdata.get("violations", [])
                if not any("pcb_rules canary" in v.get("description", "") for v in vs) and (b.pads or b.segments):
                    sys.exit("fab-floor rules were not loaded by KiCad (canary missing); use --no-floor and report this")
                floor = [v for v in vs if "fab floor" in v.get("description", "")]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        viol = data.get("violations", [])
        by = Counter((v.get("severity", "error"), v.get("type", "?")) for v in viol)
        parity = Counter(v.get("severity", "error") for v in data.get("schematic_parity", []))
        unconnected = len(data.get("unconnected_items", []))
        errors = sum(n for (sev, _), n in by.items() if sev == "error")
        shorts = [v for v in viol if v.get("type") in SHORT_TYPES]
        clear = [v for v in viol if v.get("type") in COPPER_SAFETY and v.get("type") not in SHORT_TYPES]
        dangling = sum(1 for v in viol if v.get("type") in ("track_dangling", "via_dangling"))
        metrics.update(shorts=len(shorts), clearance_violations=len(clear),
                       below_fab_minimum=None if floor is None else len(floor), dangling=dangling)
        if a.allow_unrouted:
            GATES["dangling"] = ("soft", GATES["dangling"][1])
        drc_info = dict(version=data.get("kicad_version", "?"), errors=errors, unconnected=unconnected,
                        parity_errors=parity.get("error", 0), parity_warnings=parity.get("warning", 0),
                        by_type={f"{s}:{t}": n for (s, t), n in by.items()}, exclusions_removed=removed)
        lines += ["## Shorts and clearance", "",
                  f"KiCad DRC on a copy of the project: {', '.join(COPPER_SAFETY)} forced to error, all errors per track reported"
                  + (f", {removed} DRC exclusion(s) of these checks ignored" if removed else "") + ".",
                  (f"Fab floor ({'+'.join(fabs)}): every copper gap, track, hole and edge distance checked against the fab's absolute "
                   f"minimum (clearance {fab_min['clearance']:g} mm, track {fab_min['track']:g} mm, hole to copper {fab_min['hole_clearance']:g} mm), "
                   "whatever the project's rules say." if floor is not None else
                   "Fab floor: not run (no fab known: run `apply` or pass `--fab`)."), "",
                  f"- shorts: **{len(shorts)}**", f"- clearance and copper-safety violations: **{len(clear)}**",
                  f"- below the fab minimum: **{'n/a' if floor is None else len(floor)}**", ""]
        for title, vs in (("Shorts", shorts), ("Clearance", clear), ("Below fab minimum", floor or [])):
            if vs:
                lines.append(f"**{title}** (first {min(len(vs), 15)} of {len(vs)})")
                lines += [f"- {_violation_row(v)}" for v in vs[:15]]
                lines.append("")
        errs = errors + parity.get("error", 0) + (0 if a.allow_unrouted else unconnected)
        lines += [f"## KiCad DRC ({drc_info['version']})", "",
                  f"- errors: **{errors}**, unconnected: **{unconnected}**"
                  f"{' (allowed)' if a.allow_unrouted else ''}, schematic parity: {parity.get('error', 0)} errors / {parity.get('warning', 0)} warnings", ""]
        for (sev, typ), n in sorted(by.items(), key=lambda kv: (kv[0][0] != "error", -kv[1])):
            lines.append(f"  - {sev} `{typ}`: {n}")
        lines.append("")
        if errs:
            failures.append(f"DRC: {errs} error(s)")
    else:
        limit = fab_min["clearance"] if fab_min else 0.0
        sh, gp = copper_check(b, limit if fab_min else 0.0)
        metrics.update(shorts=len(sh), clearance_violations=len(gp) if fab_min else None, below_fab_minimum=None, dangling=None)
        lines += ["## Shorts and clearance (geometry only, no KiCad)", "",
                  f"Tracks, arcs, vias and pads of different nets on a shared copper layer: touching = short; gap below "
                  + (f"the {'+'.join(fabs)} minimum {limit:g} mm = violation." if fab_min else "nothing checked (no fab known: pass `--fab`).")
                  + " Zones, net-class clearances and custom-shaped pads need KiCad DRC.", "",
                  f"- shorts: **{len(sh)}**", f"- gaps below the fab minimum: **{len(gp) if fab_min else 'n/a'}**", ""]
        for title, vs in (("Shorts", sh), ("Gaps", gp)):
            if vs:
                lines.append(f"**{title}** (first {min(len(vs), 15)} of {len(vs)})")
                lines += [f"- {v['a']} / {v['b']} on {v['layer']}: gap {v['gap']:g} mm near {v['near']}" for v in vs[:15]]
                lines.append("")

    lines += ["## Gates", "", "| Metric | Value | Gate | Result |", "|---|---|---|---|"]
    for k, (kind, limit) in GATES.items():
        val = metrics.get(k)
        if val is None:
            lines.append(f"| {k} | not run | ≤ {limit:g} ({kind}) | – |")
            continue
        ok = val <= limit
        shown = f"{val:.2f}" if isinstance(val, float) else str(val)
        lines.append(f"| {k} | {shown} | ≤ {limit:g} ({kind}) | {'pass' if ok else ('FAIL' if kind == 'hard' else 'warn')} |")
        if not ok:
            (failures if kind == "hard" else warnings).append(f"{k} = {shown} (limit {limit:g})")
    lines += ["", f"{metrics['segments']} track segments, {metrics['vias']} vias. On-grid = within ±{ANGLE_TOL}° of 0/45/90/135°. "
              f"Corners must be ≥ {MIN_CORNER}° (45° bends); branches belong on pads, not mid-track or on vias. "
              f"Jogs: interior segments < {JOG_MM} mm between parallel runs; short: interior segments < {SHORT_MM} mm.", ""]
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
            json.dump(dict(metrics=metrics, examples=examples, direction=direction, failures=failures,
                           warnings=warnings, fabs=fabs, drc=drc_info), f, indent=2)
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
    c = sub.add_parser("check", help="shorts/clearance + DRC + layout-quality gate")
    c.add_argument("board")
    c.add_argument("--fab", help="fab profile(s) for the fab-floor check (default: the ones `apply` recorded)")
    c.add_argument("--kicad-cli")
    c.add_argument("--no-drc", action="store_true", help="geometry checks only (no KiCad needed)")
    c.add_argument("--no-floor", action="store_true", help="skip the fab-floor DRC pass")
    c.add_argument("--no-refill", action="store_true")
    c.add_argument("--allow-unrouted", action="store_true", help="do not fail on unconnected items (layout in progress)")
    c.add_argument("--gate", action="append", metavar="NAME=LIMIT", help="override a gate limit, e.g. --gate track_junctions=4")
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
