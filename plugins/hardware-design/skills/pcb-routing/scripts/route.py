#!/usr/bin/env python3
"""route.py: autoroute a KiCad 10 board with Freerouting, headless and without pcbnew.

    route.py dsn    <board.kicad_pcb> [--out board.dsn] [--nets REGEX] [--skip-nets REGEX]
    route.py import <board.kicad_pcb> <board.ses>
    route.py run    <board.kicad_pcb> [--nets REGEX] [--skip-nets REGEX] [--passes 20] [--threads N]
                    [--freerouting JAR] [--java JAVA] [--fetch] [--keep DIR]
    route.py fetch  [--version 2.5.0]

dsn     writes the board as a Specctra DSN, the format Freerouting reads (kicad-cli 10 has no DSN export): the
        outline, copper layers, pours as planes, rule areas as keepouts, each footprint's pads as padstacks, the
        nets, and one class per KiCad net class with its track width, clearance and via. Existing tracks and vias
        go in as fixed wiring, so the router keeps them. --nets / --skip-nets choose the nets to route; the pads
        of the others stay obstacles.
import  adds the session's (.ses) new tracks and vias to the board; the tracks and vias already there are kept.
run     dsn, Freerouting (java -jar, no GUI), import. Then run pcb_rules.py apply (teardrops on the new vias),
        refill the zones and run the gates: the router knows clearances and widths, not the house style.
fetch   downloads Freerouting's executable jar from Maven Central into ~/.cache/hardware-design/ and checks its
        SHA-1. Freerouting is GPL-3.0 and runs as a separate program; 2.5.0 needs Java 25.

Front-side footprints only: a footprint on the back side stops dsn with an error.
"""
import argparse
import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polygonize, unary_union
from shapely import affinity

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pcb-design-rules", "scripts"))
import pcb_rules as R  # noqa: E402

UM = 1000.0
FREEROUTING_VERSION = "2.5.0"
MAVEN = "https://repo1.maven.org/maven2/app/freerouting/freerouting/{v}/freerouting-{v}-executable.jar"
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "hardware-design")
NS = uuid.UUID("0b6d2b0e-8f0e-4a51-9bd3-7d3c1c4f2a11")


# ------------------------------------------------------------------------------------------------- helpers
def child(n, k):
    return R.child(n, k)


def children(n, k):
    return R.children(n, k)


def fnum(v):
    return float(v)


def q(s):
    return '"' + str(s).replace('"', '""') + '"' if re.search(r'[\s()"]', str(s)) or s == "" else str(s)


def um(v):
    r = round(v * UM, 1) + 0.0
    return f"{r:g}"


def dsn_xy(x, y):
    return f"{um(x)} {um(-y)}"


def rot(x, y, deg):
    """KiCad's rotation on a y-down board (counter-clockwise on screen)."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return x * c + y * s, -x * s + y * c


def layer_list(node, copper):
    lays = []
    for name in (child(node, "layers") or ["layers"])[1:] + (child(node, "layer") or ["layer"])[1:]:
        if name in ("*.Cu", "F&B.Cu"):
            lays += copper if name == "*.Cu" else ["F.Cu", "B.Cu"]
        elif name in copper:
            lays.append(name)
    return list(dict.fromkeys(lays))


# ------------------------------------------------------------------------------------------------ the board
class Board:
    def __init__(self, path):
        self.path = path
        with open(path, encoding="utf-8") as f:
            self.text = f.read()
        self.root = R.parse_sexpr(self.text)
        self.copper = [e[1] for e in (child(self.root, "layers") or [])[1:]
                       if isinstance(e, list) and len(e) > 1 and str(e[1]).endswith(".Cu")]
        order = {"F.Cu": 0, "B.Cu": 99}
        self.copper.sort(key=lambda n: order.get(n, int(re.sub(r"\D", "", n) or 50)))
        self.footprints = children(self.root, "footprint")
        self.pro = os.path.splitext(path)[0] + ".kicad_pro"

    def outline(self):
        lines = []
        for kind in ("gr_line", "gr_rect", "gr_arc", "gr_poly", "gr_circle"):
            for g in children(self.root, kind):
                if (child(g, "layer") or [None, None])[1] != "Edge.Cuts":
                    continue
                if kind == "gr_line":
                    s, e = child(g, "start"), child(g, "end")
                    lines.append(LineString([(fnum(s[1]), fnum(s[2])), (fnum(e[1]), fnum(e[2]))]))
                elif kind == "gr_rect":
                    s, e = child(g, "start"), child(g, "end")
                    return box(min(fnum(s[1]), fnum(e[1])), min(fnum(s[2]), fnum(e[2])),
                               max(fnum(s[1]), fnum(e[1])), max(fnum(s[2]), fnum(e[2])))
                elif kind == "gr_arc":
                    s, m, e = (child(g, k) for k in ("start", "mid", "end"))
                    lines.append(LineString(arc_points((fnum(s[1]), fnum(s[2])), (fnum(m[1]), fnum(m[2])),
                                                       (fnum(e[1]), fnum(e[2])))))
                elif kind == "gr_poly":
                    return Polygon([(fnum(p[1]), fnum(p[2])) for p in children(child(g, "pts"), "xy")])
                elif kind == "gr_circle":
                    c, e = child(g, "center"), child(g, "end")
                    r = math.dist((fnum(c[1]), fnum(c[2])), (fnum(e[1]), fnum(e[2])))
                    return Point(fnum(c[1]), fnum(c[2])).buffer(r, 32)
        polys = list(polygonize(unary_union(lines))) if lines else []
        if not polys:
            sys.exit("no board outline on Edge.Cuts")
        return max(polys, key=lambda p: p.area)

    def classes(self):
        """{net: (class name)}, {class: dict(width, clearance, via_d, via_drill)}"""
        try:
            with open(self.pro, encoding="utf-8") as f:
                ns = json.load(f).get("net_settings", {})
        except FileNotFoundError:
            ns = {}
        rules = {}
        for c in ns.get("classes", []):
            rules[c["name"]] = dict(width=c.get("track_width", 0.2), clearance=c.get("clearance", 0.2),
                                    via_d=c.get("via_diameter", 0.6), via_drill=c.get("via_drill", 0.3))
        rules.setdefault("Default", dict(width=0.2, clearance=0.2, via_d=0.6, via_drill=0.3))
        assign = {n: (v[0] if isinstance(v, list) else v) for n, v in ns.get("netclass_assignments", {}).items()}
        patterns = [(p.get("pattern", ""), p.get("netclass", "")) for p in ns.get("netclass_patterns") or []]

        def lookup(net):
            if net in assign and assign[net] in rules:
                return assign[net]
            for pat, cls in patterns:
                if cls in rules and (fnmatch.fnmatchcase(net, pat) or re.fullmatch(pat, net or "") if pat else False):
                    return cls
            return "Default"
        return lookup, rules


def arc_points(a, m, b, n=16):
    ax, ay = a
    bx, by = b
    mx, my = m
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < 1e-12:
        return [a, b]
    ux = ((ax * ax + ay * ay) * (my - by) + (mx * mx + my * my) * (by - ay) + (bx * bx + by * by) * (ay - my)) / d
    uy = ((ax * ax + ay * ay) * (bx - mx) + (mx * mx + my * my) * (ax - bx) + (bx * bx + by * by) * (mx - ax)) / d
    r = math.dist((ux, uy), a)
    t0, tm, t1 = (math.atan2(p[1] - uy, p[0] - ux) for p in (a, m, b))

    def between(t, s, e):
        return (t - s) % (2 * math.pi) <= (e - s) % (2 * math.pi)
    if not between(tm, t0, t1):
        t0, t1 = t1, t0
    span = (t1 - t0) % (2 * math.pi)
    pts = [(ux + r * math.cos(t0 + span * i / n), uy + r * math.sin(t0 + span * i / n)) for i in range(n + 1)]
    return pts if pts and math.dist(pts[0], a) < math.dist(pts[0], b) else pts[::-1]


# ----------------------------------------------------------------------------------------------- padstacks
def pad_shape(pad):
    """The pad's copper as a shapely geometry in the pad's own frame (unrotated, y down), or ('circle', d)."""
    kind = pad[3] if len(pad) > 3 else "rect"
    sz = child(pad, "size")
    w, h = fnum(sz[1]), fnum(sz[2])
    if kind == "circle":
        return ("circle", w)
    if kind == "oval":
        if abs(w - h) < 1e-9:
            return ("circle", w)
        r = min(w, h) / 2
        return LineString([(-(w / 2 - r), 0), (w / 2 - r, 0)] if w > h else [(0, -(h / 2 - r)), (0, h / 2 - r)]) \
            .buffer(r, 8)
    if kind == "roundrect":
        rr = fnum((child(pad, "roundrect_rratio") or [0, 0.25])[1])
        r = min(w, h) * rr
        return box(-w / 2 + r, -h / 2 + r, w / 2 - r, h / 2 - r).buffer(r, 4) if r > 0 else box(-w / 2, -h / 2, w / 2, h / 2)
    if kind == "custom":
        shapes = [box(-w / 2, -h / 2, w / 2, h / 2) if (child(child(pad, "options") or [], "anchor") or [0, "rect"])[1] == "rect"
                  else Point(0, 0).buffer(w / 2, 16)]
        for prim in (child(pad, "primitives") or [])[1:]:
            width = fnum((child(prim, "width") or [0, 0])[1])
            if prim[0] == "gr_poly":
                g = Polygon([(fnum(p[1]), fnum(p[2])) for p in children(child(prim, "pts"), "xy")])
            elif prim[0] == "gr_rect":
                s, e = child(prim, "start"), child(prim, "end")
                g = box(min(fnum(s[1]), fnum(e[1])), min(fnum(s[2]), fnum(e[2])),
                        max(fnum(s[1]), fnum(e[1])), max(fnum(s[2]), fnum(e[2])))
            elif prim[0] == "gr_circle":
                c, e = child(prim, "center"), child(prim, "end")
                g = Point(fnum(c[1]), fnum(c[2])).buffer(math.dist((fnum(c[1]), fnum(c[2])), (fnum(e[1]), fnum(e[2]))), 16)
            elif prim[0] == "gr_line":
                s, e = child(prim, "start"), child(prim, "end")
                g = LineString([(fnum(s[1]), fnum(s[2])), (fnum(e[1]), fnum(e[2]))])
            else:
                continue
            shapes.append(g.buffer(width / 2, 8) if width else g)
        return unary_union(shapes)
    if kind == "trapezoid":
        return box(-w / 2, -h / 2, w / 2, h / 2)
    return box(-w / 2, -h / 2, w / 2, h / 2)


def shape_text(shape, angle, layer):
    """One DSN (shape ...) for a pad shape turned by angle (degrees, KiCad's sense), y flipped to DSN's."""
    if isinstance(shape, tuple):
        return f"(circle {layer} {um(shape[1])})"
    g = affinity.rotate(shape, -angle, origin=(0, 0)) if angle else shape
    g = g.simplify(0.0005)
    poly = g if g.geom_type == "Polygon" else max(g.geoms, key=lambda p: p.area)
    pts = list(poly.exterior.coords)
    return f"(polygon {layer} 0 " + " ".join(dsn_xy(x, y) for x, y in pts) + ")"


# -------------------------------------------------------------------------------------------------- export
def export_dsn(b, keep=lambda n: True):
    lookup, rules = b.classes()
    copper = b.copper
    out = ['(pcb "board.dsn"', "  (parser", '    (string_quote ")', "    (space_in_quoted_tokens on)",
           '    (host_cad "hardware-design route.py")', '    (host_version "1")', "  )",
           "  (resolution um 10)", "  (unit um)", "  (structure"]
    for i, lay in enumerate(copper):
        out.append(f"    (layer {q(lay)} (type signal) (property (index {i})))")
    outline = b.outline()
    out.append("    (boundary (path pcb 0 " + " ".join(dsn_xy(x, y) for x, y in outline.exterior.coords) + "))")
    zones = children(b.root, "zone") + [z for fp in b.footprints for z in children(fp, "zone")]
    for z in zones:
        pts = [(fnum(p[1]), fnum(p[2])) for poly in children(z, "polygon") for p in children(child(poly, "pts"), "xy")]
        if len(pts) < 3:
            continue
        net = (child(z, "net") or [None, ""])[1]
        ko = child(z, "keepout")
        attr = child(z, "attr")
        if attr and child(attr, "teardrop"):
            continue
        ring = " ".join(dsn_xy(x, y) for x, y in pts + pts[:1])
        for lay in layer_list(z, copper):
            if ko is not None:
                tracks = (child(ko, "tracks") or [0, "allowed"])[1] == "not_allowed"
                vias = (child(ko, "vias") or [0, "allowed"])[1] == "not_allowed"
                if tracks:
                    out.append(f'    (keepout "" (polygon {q(lay)} 0 {ring}))')
                elif vias:
                    out.append(f'    (via_keepout "" (polygon {q(lay)} 0 {ring}))')
            elif net:
                out.append(f"    (plane {q(net)} (polygon {q(lay)} 0 {ring}))")
    vias = {}
    for cls, r in rules.items():
        vias.setdefault((r["via_d"], r["via_drill"]), f"Via[0-{len(copper) - 1}]_{um(r['via_d'])}:{um(r['via_drill'])}_um")
    default = rules["Default"]
    out.append(f'    (via {q(vias[(default["via_d"], default["via_drill"])])})')
    out.append("    (snap_angle fortyfive_degree)")
    out += [f"    (rule (width {um(default['width'])}) (clearance {um(default['clearance'])}))", "  )"]

    images, padstacks, places, nets, problems = {}, {}, {}, {}, []
    for fp in b.footprints:
        ref = next((p[2] for p in children(fp, "property") if p[1] == "Reference"), None)
        if not ref:
            continue
        side = (child(fp, "layer") or [0, "F.Cu"])[1]
        at = child(fp, "at")
        fx, fy, frot = fnum(at[1]), fnum(at[2]), fnum(at[3]) if len(at) > 3 else 0.0
        pads = children(fp, "pad")
        if side == "B.Cu" and pads:
            problems.append(f"{ref}: on the back side (not supported yet)")
            continue
        pins, keepouts, seen = [], [], {}
        for pad in pads:
            num, kind = pad[1], pad[2]
            pat = child(pad, "at")
            px, py = fnum(pat[1]), fnum(pat[2])
            pang = (fnum(pat[3]) if len(pat) > 3 else 0.0) - frot
            if kind == "np_thru_hole":
                drill = fnum((child(pad, "drill") or [0, 0])[1])
                for lay in copper:
                    keepouts.append(f'(keepout "" (circle {q(lay)} {um(drill + 0.4)} {dsn_xy(px, py)}))')
                continue
            lays = layer_list(pad, copper)
            if not lays:
                continue
            shape = pad_shape(pad)
            tag = "A" if len(lays) == len(copper) else ("T" if lays == ["F.Cu"] else "_".join(lays))
            key = (tag, repr(shape) if isinstance(shape, tuple) else shape.wkt, round(pang % 360, 3))
            name = padstacks.get(key, (None,))[0]
            if name is None:
                name = f"P{len(padstacks)}[{tag}]"
                body = "\n".join(f"      (shape {shape_text(shape, pang, q(lay))})" for lay in lays)
                padstacks[key] = (name, f"    (padstack {q(name)}\n{body}\n      (attach off)\n    )")
            pin = num or "~"
            seen[pin] = seen.get(pin, -1) + 1
            pin_id = pin if seen[pin] == 0 else f"{pin}@{seen[pin]}"
            pins.append(f"(pin {q(name)} {q(pin_id)} {dsn_xy(px, py)})")
            net = (child(pad, "net") or [None, ""])[1]
            if net and keep(net):
                nets.setdefault(net, []).append(f"{ref}-{pin_id}")
        body = "\n".join("      " + p for p in pins + keepouts)
        sig = body
        img = images.get(sig)
        if img is None:
            img = f"IMG{len(images)}"
            images[sig] = img
        places.setdefault(img, []).append(f"      (place {q(ref)} {dsn_xy(fx, fy)} front {frot:g})")
    if problems:
        return None, problems
    out.append("  (placement")
    for img, pl in places.items():
        out.append(f"    (component {img}")
        out += pl
        out.append("    )")
    out.append("  )")
    out.append("  (library")
    for sig, img in images.items():
        out.append(f"    (image {img}\n{sig}\n    )")
    for name, text in padstacks.values():
        out.append(text)
    for (d, drill), name in vias.items():
        out.append(f"    (padstack {q(name)}\n" + "\n".join(f"      (shape (circle {q(l)} {um(d)}))" for l in copper)
                   + "\n      (attach off)\n    )")
    out.append("  )")
    out.append("  (network")
    by_class = {}
    for net, pins in sorted(nets.items()):
        out.append(f"    (net {q(net)} (pins {' '.join(q(p) for p in pins)}))")
        by_class.setdefault(lookup(net), []).append(net)
    for cls, members in by_class.items():
        r = rules[cls]
        out.append(f"    (class {q(cls)} {' '.join(q(n) for n in members)}\n"
                   f"      (circuit (use_via {q(vias[(r['via_d'], r['via_drill'])])}))\n"
                   f"      (rule (width {um(r['width'])}) (clearance {um(r['clearance'])}))\n    )")
    out.append("  )")
    out.append("  (wiring")
    for s in children(b.root, "segment"):
        st, en = child(s, "start"), child(s, "end")
        net = (child(s, "net") or [None, ""])[1]
        out.append(f"    (wire (path {q(child(s, 'layer')[1])} {um(fnum(child(s, 'width')[1]))} "
                   f"{dsn_xy(fnum(st[1]), fnum(st[2]))} {dsn_xy(fnum(en[1]), fnum(en[2]))}) (net {q(net)}) (type protect))")
    for v in children(b.root, "via"):
        a = child(v, "at")
        d, drill = fnum(child(v, "size")[1]), fnum((child(v, "drill") or [0, 0.3])[1])
        name = vias.get((d, drill))
        if name is None:
            name = vias[(d, drill)] = f"Via[0-{len(copper) - 1}]_{um(d)}:{um(drill)}_um"
        net = (child(v, "net") or [None, ""])[1]
        out.append(f"    (via {q(name)} {dsn_xy(fnum(a[1]), fnum(a[2]))} (net {q(net)}) (type protect))")
    out += ["  )", ")"]
    return "\n".join(out) + "\n", []


# -------------------------------------------------------------------------------------------------- import
def _tok(text):
    return re.findall(r'"(?:[^"]|"")*"|[()]|[^\s()"]+', text)


def parse_ses(text):
    stack, cur = [], []
    for t in _tok(text):
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1].replace('""', '"') if t.startswith('"') else t)
    return cur[0] if cur else []


def session_items(ses_text):
    """(segments [(layer, width, x1, y1, x2, y2, net)], vias [(padstack, x, y, net)]) in mm, KiCad's y down."""
    root = parse_ses(ses_text)
    routes = child(root, "routes") or []
    res = child(routes, "resolution")
    scale = {"um": 1000.0, "mm": 1.0, "mil": 39.37007874, "inch": 0.03937007874}[res[1]] * float(res[2]) if res else 10000.0
    segs, vias = [], []
    for net in children(child(routes, "network_out") or [], "net"):
        name = net[1]
        for w in children(net, "wire"):
            p = child(w, "path")
            if not p:
                continue
            layer, width = p[1], float(p[2]) / scale
            coords = [float(v) / scale for v in p[3:] if not isinstance(v, list)]
            pts = list(zip(coords[0::2], [-c for c in coords[1::2]]))
            for a, c in zip(pts, pts[1:]):
                if a != c:
                    segs.append((layer, width, a[0], a[1], c[0], c[1], name))
        for v in children(net, "via"):
            vias.append((v[1], float(v[2]) / scale, -float(v[3]) / scale, name))
    return segs, vias


def import_session(board_path, ses_text):
    b = Board(board_path)
    have_s = {(child(s, "layer")[1], round(fnum(child(s, "start")[1]), 3), round(fnum(child(s, "start")[2]), 3),
               round(fnum(child(s, "end")[1]), 3), round(fnum(child(s, "end")[2]), 3)) for s in children(b.root, "segment")}
    have_s |= {(k[0], k[3], k[4], k[1], k[2]) for k in have_s}
    have_v = {(round(fnum(child(v, "at")[1]), 3), round(fnum(child(v, "at")[2]), 3)) for v in children(b.root, "via")}
    segs, vias = session_items(ses_text)
    blocks, n_s, n_v = [], 0, 0
    for layer, w, x1, y1, x2, y2, net in segs:
        key = (layer, round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3))
        if key in have_s:
            continue
        have_s.add(key)
        n_s += 1
        uid = uuid.uuid5(NS, f"seg/{key}/{net}")
        blocks.append(f'\t(segment\n\t\t(start {x1:g} {y1:g})\n\t\t(end {x2:g} {y2:g})\n\t\t(width {w:g})\n'
                      f'\t\t(layer "{layer}")\n\t\t(net "{_esc(net)}")\n\t\t(uuid "{uid}")\n\t)')
    for name, x, y, net in vias:
        key = (round(x, 3), round(y, 3))
        if key in have_v:
            continue
        have_v.add(key)
        n_v += 1
        m = re.search(r"_([\d.]+):([\d.]+)_um", name)
        d, drill = (float(m.group(1)) / UM, float(m.group(2)) / UM) if m else (0.6, 0.3)
        lays = (b.copper[0], b.copper[-1])
        uid = uuid.uuid5(NS, f"via/{key}/{net}")
        blocks.append(f'\t(via\n\t\t(at {x:g} {y:g})\n\t\t(size {d:g})\n\t\t(drill {drill:g})\n'
                      f'\t\t(layers "{lays[0]}" "{lays[1]}")\n\t\t(net "{_esc(net)}")\n\t\t(uuid "{uid}")\n\t)')
    if blocks:
        text = b.text.rstrip()
        assert text.endswith(")")
        text = text[:-1].rstrip() + "\n" + "\n".join(blocks) + "\n)\n"
        with open(board_path, "w", encoding="utf-8") as f:
            f.write(text)
    return n_s, n_v


def _esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ------------------------------------------------------------------------------------------------- running
def fetch(version=FREEROUTING_VERSION):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"freerouting-{version}.jar")
    if os.path.exists(path):
        return path
    url = MAVEN.format(v=version)
    with urllib.request.urlopen(url + ".sha1", timeout=60) as r:
        want = r.read().decode().split()[0].strip()
    tmp = path + ".part"
    with urllib.request.urlopen(url, timeout=600) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    with open(tmp, "rb") as f:
        got = hashlib.sha1(f.read()).hexdigest()
    if got != want:
        os.remove(tmp)
        sys.exit(f"Freerouting download: SHA-1 {got} does not match Maven Central's {want}")
    os.replace(tmp, path)
    return path


def find_java(arg=None):
    for c in (arg, os.environ.get("JAVA"), shutil.which("java")):
        if c:
            return c
    sys.exit("java not found (Freerouting 2.5 needs Java 25): pass --java or set $JAVA")


def selector(a):
    inc = re.compile(a.nets) if getattr(a, "nets", None) else None
    exc = re.compile(a.skip_nets) if getattr(a, "skip_nets", None) else None
    return lambda n: (inc is None or inc.search(n)) and not (exc and exc.search(n))


def cmd_dsn(a):
    b = Board(a.board)
    text, problems = export_dsn(b, selector(a))
    if problems:
        for p in problems:
            print("ERROR", p)
        return 1
    out = a.out or os.path.splitext(a.board)[0] + ".dsn"
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {out}")
    return 0


def cmd_import(a):
    with open(a.ses, encoding="utf-8") as f:
        n_s, n_v = import_session(a.board, f.read())
    print(f"{os.path.basename(a.board)}: added {n_s} track segments and {n_v} vias")
    return 0


def cmd_run(a):
    jar = a.freerouting or os.environ.get("FREEROUTING_JAR") or (fetch() if a.fetch else None)
    if not jar:
        cached = os.path.join(CACHE, f"freerouting-{FREEROUTING_VERSION}.jar")
        jar = cached if os.path.exists(cached) else None
    if not jar:
        sys.exit("Freerouting jar not found: pass --freerouting JAR, set $FREEROUTING_JAR, or add --fetch")
    java = find_java(a.java)
    b = Board(a.board)
    text, problems = export_dsn(b, selector(a))
    if problems:
        for p in problems:
            print("ERROR", p)
        return 1
    work = a.keep or tempfile.mkdtemp(prefix="route-")
    os.makedirs(work, exist_ok=True)
    dsn, ses = os.path.join(work, "board.dsn"), os.path.join(work, "board.ses")
    with open(dsn, "w", encoding="utf-8") as f:
        f.write(text)
    cmd = [java, "-Djava.awt.headless=true", "-jar", jar, "-de", dsn, "-do", ses, "-mp", str(a.passes),
           "--gui.enabled=false"] + (["-mt", str(a.threads)] if a.threads else [])
    print("running:", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout)
    log = os.path.join(work, "freerouting.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write(r.stdout + r.stderr)
    if not os.path.exists(ses):
        print((r.stdout + r.stderr)[-1500:])
        sys.exit(f"Freerouting wrote no session (log: {log})")
    with open(ses, encoding="utf-8") as f:
        n_s, n_v = import_session(a.board, f.read())
    unrouted = re.findall(r"(\d+) unrouted", r.stdout + r.stderr)
    print(f"{os.path.basename(a.board)}: added {n_s} track segments and {n_v} vias"
          + (f"; Freerouting reports {unrouted[-1]} unrouted" if unrouted else "") + f" (work files: {work})")
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dsn")
    d.add_argument("board")
    d.add_argument("--out")
    i = sub.add_parser("import")
    i.add_argument("board")
    i.add_argument("ses")
    r = sub.add_parser("run")
    r.add_argument("board")
    for p in (d, r):
        p.add_argument("--nets", help="route only nets matching this regular expression")
        p.add_argument("--skip-nets", help="leave nets matching this regular expression unrouted")
    r.add_argument("--passes", type=int, default=20)
    r.add_argument("--threads", type=int)
    r.add_argument("--timeout", type=int, default=3600)
    r.add_argument("--freerouting")
    r.add_argument("--java")
    r.add_argument("--fetch", action="store_true", help="download Freerouting from Maven Central if needed")
    r.add_argument("--keep", metavar="DIR", help="keep the DSN, session and log in DIR")
    f = sub.add_parser("fetch")
    f.add_argument("--version", default=FREEROUTING_VERSION)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        print(fetch(a.version))
        return 0
    return {"dsn": cmd_dsn, "import": cmd_import, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
