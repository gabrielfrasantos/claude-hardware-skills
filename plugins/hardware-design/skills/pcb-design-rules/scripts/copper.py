"""copper.py: teardrops, pours and reference planes for pcb_rules.py (KiCad 10+). Needs shapely (and scipy).

apply side:  set_teardrops() turns KiCad's per-pad and per-via teardrop flag on, in the board text.
check side:  report() measures, from the zone fills in the board file:
  teardrops_disabled      pads/vias with a track on them whose teardrop flag is off
  teardrops_missing       ... flag on, track narrower than filter_ratio x pad, pad not in a pour of its net (KiCad
                          prefers the zone connection), and no teardrop drawn. KiCad also skips some on its own
                          (a bend too close to the pad), so this one is a warning
  zone_unfilled           copper zones with no fill in the file (fill and save in KiCad, or let check refill)
  zone_islands            fill pieces that touch no pad, via or track of their net
  zone_necks              fill pieces that fall apart into several connected parts when opened at the net's
                          track width: a neck narrower than a track of that net would be. A ground part beyond the
                          neck that has a via of its own is not counted: the plane carries its current
  gnd_plane_splits        ground-plane layers (stack-up role GND) whose main ground net's fill is not one piece
                          (other ground nets on the layer, e.g. a separate PGND, are partitions by design)
  unstitched_ground       ground fill pieces (>= 1 mm²) with no via or through-hole pad of their net (multilayer)
  gnd_via_max_distance_mm largest distance from any point of a ground fill to the nearest ground via or THT pad
  signal_over_plane_gap_mm  routed length of signal tracks with no fill under them on their reference layer
"""
import fnmatch
import json
import math
import os
import re
from collections import defaultdict

try:                                       # the apply side (teardrop flags, stack-up) works without these
    import numpy as np
    from scipy.spatial import cKDTree
    from shapely import contains_xy
    from shapely.geometry import LineString, MultiPolygon, Point, Polygon
    from shapely.ops import nearest_points, unary_union
    from shapely.strtree import STRtree
    MISSING = None
except ImportError as e:                   # pragma: no cover
    MISSING = str(e)

HERE = os.path.dirname(os.path.abspath(__file__))
STACKUPS = os.path.join(HERE, "..", "profiles", "stackups.json")
GROUND = re.compile(r"^(GND|AGND|DGND|PGND|GNDA|GNDD|GNDPWR|VSS|GND_\w+|\w+_GND|EARTH|0V)$", re.I)
MIN_PIECE_MM2 = 0.05     # fill slivers below this are ignored by the island and stitching checks
PLANE_PIECE_MM2 = 1.0    # ground pieces below this do not count as a plane split
GRID_MM = 0.5            # sampling grid for the stitching distance
NECK_TOL_MM = 0.005      # a neck exactly at the width passes (float rounding of the fill outline)
TRACK_STEP_MM = 0.1      # tolerance of the reference-plane coverage (shapely is exact; this only drops slivers)

# KiCad 10.0's own per-item teardrop defaults, as it writes them in a board file.
TD_KEYS = [("best_length_ratio", "0.5"), ("max_length", "1"), ("best_width_ratio", "1"), ("max_width", "2"),
           ("curved_edges", "yes"), ("filter_ratio", "0.9"), ("enabled", "yes"), ("allow_two_segments", "yes"),
           ("prefer_zone_connections", "yes")]


def is_ground(net):
    return bool(GROUND.match(net.rsplit("/", 1)[-1]))


# ================================================================================================ apply
def _blocks(text, start, end):
    """(kind, start, end) of the child lists of the list that opens at text[start]; end exclusive."""
    out, depth, i, cs = [], 0, start, None
    while i < end:
        ch = text[i]
        if ch == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "(":
            depth += 1
            if depth == 2:
                cs = i
        elif ch == ")":
            if depth == 2:
                m = re.match(r"\(([^\s()\"]+)", text[cs:cs + 64])
                out.append((m.group(1) if m else "", cs, i + 1))
            depth -= 1
            if depth == 0:
                break
        i += 1
    return out


def _td_block(indent, enabled):
    inner = indent + "\t"
    rows = [f"{inner}({k} {('yes' if enabled else 'no') if k == 'enabled' else v})" for k, v in TD_KEYS]
    return "(teardrops\n" + "\n".join(rows) + f"\n{indent})"


def _item_edit(text, s, e, enabled):
    """Edit for one pad or via block: set its teardrop flag, inserting KiCad's default block if it has none."""
    kids = _blocks(text, s, e)
    td = [(a, b) for k, a, b in kids if k == "teardrops"]
    if td:
        a, b = td[0]
        want = f"(enabled {'yes' if enabled else 'no'})"
        new = re.sub(r"\(enabled (yes|no)\)", want, text[a:b])
        if "(enabled " not in new:
            new = new[:-1].rstrip() + " " + want + ")"
        return None if new == text[a:b] else (a, b, new)
    # where KiCad 10 writes it: a pad's block just before (uuid), a via's just before (net)
    first = "net" if text[s:s + 4] == "(via" else "uuid"
    at = next((a for k, a, _ in kids if k == first), None)
    if at is None:
        at = next((a for k, a, _ in kids if k == "uuid"), None)
    indent = text[text.rfind("\n", s, kids[0][1]) + 1:kids[0][1]] if kids else "\t\t"
    if at is None:                                    # no uuid: append before the closing paren
        at = e - 1
        return (at, at, "\n" + indent + _td_block(indent, enabled) + "\n" + indent[:-1])
    return (at, at, _td_block(indent, enabled) + "\n" + indent)


def class_skip(pro_path, patterns):
    """net -> True when its net class matches one of the comma-separated wildcard patterns."""
    pats = [p.strip() for p in (patterns or "").split(",") if p.strip()]
    if not pats:
        return None
    lookup, _ = class_resolver(pro_path)
    return lambda net: any(fnmatch.fnmatchcase(lookup(net), p) for p in pats)


def set_teardrops(text, exclude=None, skip=None):
    """Teardrops on for every netted copper pad and every via; off for nets matching `exclude` (a regex) and
    nets for which skip(net) is true (by default the DIFF_* and RF_* classes: teardrops shift a matched line's
    impedance).

    Returns (new text, items changed). KiCad draws the teardrops from these flags (Edit > Edit Teardrops,
    and on later edits); pcb_rules check confirms they exist."""
    rx = re.compile(exclude) if exclude else None
    edits = []

    def wanted(block):
        m = re.search(r'\n\s*\(net "((?:[^"\\]|\\.)*)"\)', block)
        if not m or not m.group(1):
            return None
        net = m.group(1).replace("{slash}", "/")
        return not ((rx and rx.search(m.group(1))) or (skip and skip(net)))

    for kind, s, e in _blocks(text, 0, len(text)):
        if kind == "via":
            w = wanted(text[s:e])
            if w is not None:
                edits.append(_item_edit(text, s, e, w))
        elif kind == "footprint":
            for k, ps, pe in _blocks(text, s, e):
                if k != "pad":
                    continue
                head = text[ps:ps + 80]
                if "np_thru_hole" in head or " connect " in head:
                    continue
                w = wanted(text[ps:pe])
                if w is not None:
                    edits.append(_item_edit(text, ps, pe, w))
    edits = sorted(x for x in edits if x)
    out, pos = [], 0
    for s, e, rep in edits:
        out += [text[pos:s], rep]
        pos = e
    return "".join(out) + text[pos:], len(edits)


def set_teardrop_options(pj):
    """Project defaults for new items (Board Setup > Teardrops): pads, PTH and vias on."""
    ds = pj.setdefault("board", {}).setdefault("design_settings", {})
    opts = (ds.get("teardrop_options") or [{}])[0]
    opts.update(td_onpthpad=True, td_onsmdpad=True, td_onvia=True)
    opts.setdefault("td_onroundshapesonly", False)
    opts.setdefault("td_ontrackend", False)
    ds["teardrop_options"] = [opts]


# ================================================================================================ stack-up
def templates():
    with open(STACKUPS) as f:
        return json.load(f)


def roles_for(copper_layers, recorded=None):
    """{layer: role} from the roles `apply` recorded, else the template for the layer count, else {}."""
    if recorded and set(recorded) == set(copper_layers):
        return recorded
    t = templates()["layers"].get(str(len(copper_layers)))
    return dict(zip(copper_layers, t["roles"])) if t else {}


def reference_layer(layer, layers, roles):
    """The nearest plane layer (GND or PWR) in the stack, GND on a tie; None if there is none.
    With SIG/GND/PWR/SIG the bottom signals reference the power plane (TI advises against it for fast nets)."""
    i = layers.index(layer)
    best = [(abs(j - i), roles[l] != "GND", l) for j, l in enumerate(layers)
            if j != i and roles.get(l) in ("GND", "PWR")]
    return min(best)[2] if best else None


# ================================================================================================ geometry
def _pts(node, child, children):
    pts = []
    for p in node[1:]:
        if isinstance(p, list) and p and p[0] == "xy":
            pts.append((float(p[1]), float(p[2])))
        elif isinstance(p, list) and p and p[0] == "arc":
            for k in ("start", "mid", "end"):
                c = child(p, k)
                pts.append((float(c[1]), float(c[2])))
    return pts


def pad_geom(p):
    c, s = math.cos(math.radians(p["rot"])), math.sin(math.radians(p["rot"]))

    def tf(dx, dy):
        return (p["x"] + dx * c + dy * s, p["y"] - dx * s + dy * c)

    w, h = p["w"], p["h"]
    if p["shape"] == "circle":
        return Point(p["x"], p["y"]).buffer(w / 2, 16)
    if p["shape"] == "oval":
        if abs(w - h) < 1e-9:
            return Point(p["x"], p["y"]).buffer(w / 2, 16)
        a, b = ((tf(-(w - h) / 2, 0), tf((w - h) / 2, 0)) if w > h else (tf(0, -(h - w) / 2), tf(0, (h - w) / 2)))
        return LineString([a, b]).buffer(min(w, h) / 2, 16)
    return Polygon([tf(-w / 2, -h / 2), tf(w / 2, -h / 2), tf(w / 2, h / 2), tf(-w / 2, h / 2)])


def _seg_geom(s):
    return LineString([(s["x1"], s["y1"]), (s["x2"], s["y2"])]).buffer(s["w"] / 2, 8)


def zones(board):
    """Copper zones: net, layers, teardrop flag, min width, fill pieces per layer (shapely polygons)."""
    from pcb_rules import child, children
    out = []
    for node in board.root:
        if not (isinstance(node, list) and node and node[0] == "zone"):
            continue
        if child(node, "keepout"):
            continue
        attr = child(node, "attr")
        lay = child(node, "layers") or child(node, "layer")
        mt = child(node, "min_thickness")
        fills = defaultdict(list)
        for fp in children(node, "filled_polygon"):
            pts = child(fp, "pts")
            poly = Polygon(_pts(pts, child, children)).buffer(0) if pts else None
            if poly is not None and not poly.is_empty:
                fills[child(fp, "layer")[1]].append(poly)
        out.append(dict(net=board._net(node), layers=[l for l in (lay[1:] if lay else [])],
                        teardrop=bool(attr and child(attr, "teardrop")), min_width=float(mt[1]) if mt else 0.0,
                        name=(child(node, "name") or [None, ""])[1],
                        fills={l: unary_union(ps) for l, ps in fills.items()}))
    return out


def pieces(geom):
    if geom is None or geom.is_empty:
        return []
    return list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom] if isinstance(geom, Polygon) else \
        [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


# ================================================================================================ net classes
def class_resolver(pro_path):
    """(net -> class name, {class name: entry}) from the project's net classes, as KiCad resolves them:
    an assignment (written by KiCad from the schematic's net-class directive labels), else the first
    matching pattern (wildcards), else Default. A net matching several patterns gets a composite class in
    KiCad; the first match is used here."""
    if not pro_path or not os.path.exists(pro_path):
        return (lambda net: "Default"), {}
    with open(pro_path) as f:
        ns = json.load(f).get("net_settings", {})
    classes = {c.get("name"): c for c in ns.get("classes", [])}
    assign = ns.get("netclass_assignments") or {}
    patterns = [p for p in (ns.get("netclass_patterns") or []) if p.get("pattern")]

    def lookup(net):
        cls = assign.get(net)
        if isinstance(cls, list):
            cls = cls[0] if cls else None
        if cls is None:
            cls = next((p.get("netclass") for p in patterns if fnmatch.fnmatchcase(net, p["pattern"])), None)
        return cls or "Default"
    return lookup, classes


def class_widths(pro_path):
    """net -> track width of its net class (Default's when it has none)."""
    lookup, classes = class_resolver(pro_path)
    default = (classes.get("Default") or {}).get("track_width") or 0.0
    return lambda net: (classes.get(lookup(net)) or {}).get("track_width") or default


# ================================================================================================ report
def report(board, pro_path=None, recorded_roles=None, td_exclude=None, teardrops=True, td_classes="DIFF_*,RF_*"):
    """Copper metrics and examples. board: a pcb_rules.Board (KiCad 10, with .root).
    teardrops=False (apply --no-teardrops) leaves the teardrop gates unmeasured. Nets matching td_exclude (regex)
    or of a class matching td_classes (comma-separated wildcards) are not expected to have teardrops."""
    if MISSING:
        raise SystemExit(f"copper checks need shapely, numpy and scipy ({MISSING}): pip install shapely scipy, "
                         "or run check with --no-copper")
    layers = board.copper_layers
    roles = roles_for(layers, recorded_roles)
    width_of = class_widths(pro_path)
    rx = re.compile(td_exclude) if td_exclude else None
    skip = class_skip(pro_path, td_classes)
    zs = zones(board)
    tdz = defaultdict(list)                                  # (net, layer) -> teardrop geometries
    fills = [z for z in zs if not z.get("teardrop")]
    pours = defaultdict(list)                                # (net, layer) -> fills of that net
    for z in fills:
        for l, g in z["fills"].items():
            pours[(z["net"], l)].append(g)
    for z in zs:
        if z["teardrop"]:
            for l, g in z["fills"].items():
                tdz[(z["net"], l)].append(g)

    # connection items per (net, layer)
    terms = defaultdict(list)
    stitch = defaultdict(list)                               # net -> points that join layers (vias, THT pads)
    stitch_geoms = defaultdict(list)
    pad_geoms = []
    for p in board.pads:
        if not p["net"] or not p["layers"]:
            continue
        g = pad_geom(p)
        pad_geoms.append((p, g))
        for l in p["layers"]:
            terms[(p["net"], l)].append(g)
        if p["kind"] == "thru_hole":
            stitch[p["net"]].append((p["x"], p["y"]))
            stitch_geoms[p["net"]].append(g)
    via_geoms = []
    for v in board.vias:
        g = Point(v["x"], v["y"]).buffer(v["d"] / 2, 12)
        via_geoms.append((v, g))
        for l in v["layers"]:
            terms[(v["net"], l)].append(g)
        stitch[v["net"]].append((v["x"], v["y"]))
        stitch_geoms[v["net"]].append(g)
    for s in board.segments:
        terms[(s["net"], s["layer"])].append(_seg_geom(s))
    trees = {k: STRtree(v) for k, v in terms.items()}

    def joins_layers(piece, net):
        grown = piece.buffer(1e-3)
        return any(grown.intersects(g) for g in stitch_geoms.get(net, []))

    def touches(net, layer, geom):
        t = trees.get((net, layer))
        return bool(t is not None and len(t.query(geom, predicate="intersects")))

    m, ex = {}, defaultdict(list)

    # ---- teardrops
    ends = defaultdict(list)                                 # (net, layer) -> track ends with widths
    for s in board.segments:
        ends[(s["net"], s["layer"])] += [((s["x1"], s["y1"]), s), ((s["x2"], s["y2"]), s)]
    disabled = disabled_smd = missing = 0
    items = [(p, g, p["td"], min(p["w"], p["h"]), p["layers"]) for p, g in pad_geoms] + \
            [(v, g, v["td"], v["d"], v["layers"]) for v, g in via_geoms]
    for it, g, td, size, its_layers in items:
        if (rx and rx.search(it["net"])) or (skip and skip(it["net"])):
            continue
        for l in its_layers:
            hits = [s for pt, s in ends.get((it["net"], l), ()) if g.buffer(1e-3).contains(Point(pt))]
            if not hits:
                continue
            where = f"{it.get('ref', 'via')}{('.' + str(it['num'])) if 'num' in it else ''} {it['net']} {l} " \
                    f"({it['x']:.3f}, {it['y']:.3f})"
            if not td["enabled"]:
                if it.get("kind") == "smd":                  # recommended on SMD pads, required on drilled ones
                    disabled_smd += 1
                    ex["teardrops_disabled_smd"].append(where)
                else:
                    disabled += 1
                    ex["teardrops_disabled"].append(where)
                break
            if td["prefer_zone"] and any(f.intersects(g) for f in pours.get((it["net"], l), ())):
                continue                                     # KiCad uses the zone connection, no teardrop
            eligible = [s for s in hits if s["w"] < td["filter_ratio"] * size]
            if eligible and not any(t.intersects(g.buffer(0.01)) for t in tdz.get((it["net"], l), ())):
                missing += 1
                ex["teardrops_missing"].append(where)
                break
    m["teardrops_disabled"], m["teardrops_disabled_smd"], m["teardrops_missing"] = \
        (disabled, disabled_smd, missing) if teardrops else (None, None, None)

    # ---- fills: unfilled zones, islands, necks, stitching
    unfilled = [z for z in fills if not z["fills"] and z["net"]]
    m["zone_unfilled"] = len(unfilled)
    ex["zone_unfilled"] = [f"{z['name'] or z['net']} on {','.join(z['layers'])}" for z in unfilled]
    islands = necks = unstitched = 0
    ground_by_layer = defaultdict(list)
    ground_net_pieces = defaultdict(list)
    for z in fills:
        net = z["net"]
        if not net:
            continue
        w = max(width_of(net), z["min_width"])
        for layer, geom in z["fills"].items():
            for piece in pieces(geom):
                if piece.area < MIN_PIECE_MM2:
                    continue
                if is_ground(net):
                    ground_by_layer[layer].append(piece)
                    ground_net_pieces[(layer, net)].append(piece)
                t = trees.get((net, layer))
                hit = [terms[(net, layer)][i] for i in t.query(piece, predicate="intersects")] if t is not None else []
                rp = piece.representative_point()
                if not hit:
                    islands += 1
                    ex["zone_islands"].append(f"{net} on {layer} at ({rp.x:.2f}, {rp.y:.2f}), {piece.area:.2f} mm²")
                    continue
                if is_ground(net) and len(layers) > 1 and piece.area >= PLANE_PIECE_MM2:
                    if not joins_layers(piece, net):
                        unstitched += 1
                        ex["unstitched_ground"].append(f"{net} on {layer} at ({rp.x:.2f}, {rp.y:.2f}), {piece.area:.1f} mm²")
                if len(hit) > 1 and w > 0:
                    r = w / 2 - NECK_TOL_MM
                    opened = piece.buffer(-r, 8).buffer(r, 8)
                    comps = sorted((c for c in pieces(opened) if any(c.intersects(h) for h in hit)),
                                   key=lambda c: -c.area)
                    cut = [c for c in comps[1:] if not (is_ground(net) and joins_layers(c, net))]
                    if cut:
                        necks += len(cut)
                        a, b = nearest_points(comps[0], unary_union(cut))
                        ex["zone_necks"].append(f"{net} on {layer} near ({(a.x + b.x) / 2:.2f}, {(a.y + b.y) / 2:.2f}): "
                                                f"narrower than {w:g} mm, {len(cut) + 1} parts")
    m.update(zone_islands=islands, zone_necks=necks, unstitched_ground=unstitched)

    # ---- ground planes
    splits = 0
    for layer in layers:
        if roles.get(layer) != "GND":
            continue
        nets = {n: ps for (l, n), ps in ground_net_pieces.items() if l == layer}
        main = max(nets, key=lambda n: sum(p.area for p in nets[n]), default=None)
        big = [p for p in nets.get(main, []) if p.area >= PLANE_PIECE_MM2]
        if not big:
            splits += 1
            ex["gnd_plane_splits"].append(f"{layer}: GND role, no ground fill")
        elif len(big) > 1:
            splits += len(big) - 1
            ex["gnd_plane_splits"].append(f"{layer}: {main} fill in {len(big)} pieces "
                                          f"({', '.join(f'{p.area:.0f}' for p in sorted(big, key=lambda q: -q.area)[:6])} mm²)")
    m["gnd_plane_splits"] = splits if roles else None

    # ---- stitching distance
    gpts = [pt for net, pts in stitch.items() if is_ground(net) for pt in pts]
    worst, where = None, None
    if gpts and ground_by_layer:
        tree = cKDTree(np.array(gpts))
        worst = 0.0
        for layer, ps in ground_by_layer.items():
            for piece in ps:
                x0, y0, x1, y1 = piece.bounds
                xs, ys = np.meshgrid(np.arange(x0, x1 + GRID_MM, GRID_MM), np.arange(y0, y1 + GRID_MM, GRID_MM))
                xs, ys = xs.ravel(), ys.ravel()
                inside = contains_xy(piece, xs, ys)
                corners = np.array(piece.exterior.coords)          # the grid alone misses the corners
                sample = np.vstack([np.column_stack([xs[inside], ys[inside]]), corners])
                d, _ = tree.query(sample)
                i = int(np.argmax(d))
                if d[i] > worst:
                    worst, where = float(d[i]), f"{layer} ({sample[i][0]:.1f}, {sample[i][1]:.1f})"
    m["gnd_via_max_distance_mm"] = None if worst is None else round(worst, 2)
    if where:
        ex["gnd_via_max_distance_mm"].append(where)

    # ---- signals over reference-plane gaps
    plane_nets = {z["net"] for z in fills}
    ref_fill = {}
    for layer in layers:
        ref = reference_layer(layer, layers, roles) if roles.get(layer) not in ("GND", "PWR") else None
        if ref:
            ref_fill[layer] = unary_union([g for z in fills for l, g in z["fills"].items() if l == ref] or [Polygon()])
    gap_total, per_net = 0.0, defaultdict(float)
    for s in board.segments:
        if s["layer"] not in ref_fill or s["net"] in plane_nets or is_ground(s["net"]) or not s["net"]:
            continue
        line = LineString([(s["x1"], s["y1"]), (s["x2"], s["y2"])])
        off = line.difference(ref_fill[s["layer"]]).length
        if off > TRACK_STEP_MM:
            gap_total += off
            per_net[s["net"]] += off
    m["signal_over_plane_gap_mm"] = round(gap_total, 2) if ref_fill else None
    ex["signal_over_plane_gap_mm"] = [f"{n}: {v:.2f} mm" for n, v in sorted(per_net.items(), key=lambda kv: -kv[1])[:15]]

    info = dict(roles=roles, references={l: reference_layer(l, layers, roles) for l in layers if l in ref_fill},
                zones=len(fills), teardrop_zones=sum(1 for z in zs if z["teardrop"]))
    return m, {k: v[:15] for k, v in ex.items()}, info
