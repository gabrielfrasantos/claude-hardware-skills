#!/usr/bin/env python3
"""Copy a vendor's proven layout block (an RF corner, an NFC coil, a motor-driver stage) onto a KiCad 10 board (D18).

    refblock.py import  VENDOR_FILE -o reference/<name>/<name>.kicad_pcb
    refblock.py list    VENDOR.kicad_pcb [--box X1 Y1 X2 Y2]
    refblock.py extract VENDOR.kicad_pcb MAP.json -o BLOCK.json [--board OURS.kicad_pcb] [--files F ...]
                        [--footprints DIR.pretty --prefix P_]
    refblock.py place   BLOCK.json BOARD.kicad_pcb [--at X Y] [--rot 0|90|180|270] [--replace] [--fab jlcpcb]
    refblock.py check   BLOCK.json BOARD.kicad_pcb [--tol MM]

import   runs `kicad-cli pcb import` (Altium, PADS, Eagle, CADSTAR, Fabmaster, P-CAD, SOLIDWORKS PCB) into the
         gitignored reference/ folder and prints the input's sha256.
list     prints the vendor board's parts and copper nets (inside a box), to write the map.
extract  cuts the block out of the vendor board into BLOCK.json, which the board repo keeps (vendor files stay out):
         the mapped parts with their pads, and the tracks, arcs, vias, pours, rule areas and copper graphics inside
         the box, as the vendor's own KiCad text. Copper on dropped nets and copper that ends on nothing copied is
         pruned; pours and rule areas are cut to the box. With --board, every vendor net touching a mapped part's pad
         is mapped to the net on the same pad of our part, and a vendor net that would need two of ours (the
         schematic disagrees with the copy) is an error. --footprints writes the vendor's land patterns of the
         front-side parts as library footprints, re-centred on their pads.
place    puts the block on our board: each mapped part is moved and turned so its pads land on the vendor's pads (by
         pad number, least squares), the copper is added with our nets, and everything is grouped under the block's
         name. Errors, nothing written: a part missing, on the other side, locked where it must move, a land that
         differs from the vendor's beyond --tol, or a pad whose net differs from the map. Re-running is a no-op while
         the group exists; --replace removes the group's copper and pastes again, where the parts are now (or --at).
check    fits the block to where our parts are now and reports, per part, how far its pads are from the vendor's
         and whether its nets agree. Fails on a net mismatch or a pad off by more than --tol.

The block frame is the vendor's board frame (KiCad, mm, y down). --at puts the centre of the block's box at X Y,
--rot turns it counter-clockwise (KiCad's sense) about that centre. Mirroring a block to the other side is not
supported. Reading and writing is S-expression text (docs/design.md D22): items not touched stay byte-identical.
"""

import argparse
import hashlib
import json
import math
import pathlib
import re
import subprocess
import sys
import uuid as uuidlib

from shapely.geometry import Point, Polygon, box as shp_box

CORE = pathlib.Path(__file__).resolve().parents[2] / "pcb-design-rules" / "scripts"
sys.path.insert(0, str(CORE))
import pcb_rules as R  # noqa: E402

FORMAT = "refblock/1"
EPS = 1e-4          # mm: copper ends this close are connected
NS = uuidlib.UUID("6b1f0c52-6e3a-4a43-9a65-0d5f2c6a1e10")
COPPER_ITEMS = ("segment", "arc", "via", "zone", "gr_line", "gr_arc", "gr_poly", "gr_rect", "gr_circle")
POINT_HEADS = {"at", "start", "end", "mid", "center", "xy"}
ANGLE_PARENTS = {"pad", "property", "fp_text", "fp_text_box"}   # their `at` angle is absolute in a board file
OPAQUE = {"primitives", "model"}                                 # coordinates in another frame: left alone


# ------------------------------------------------------------------------------------------------- text
_TOK = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


def tree(text, start=0):
    """The list opening at text[start] as {"s", "e", "items"}; atoms are (token, start, end)."""
    stack = []
    for m in _TOK.finditer(text, start):
        t = m.group(0)
        if t == "(":
            n = {"s": m.start(), "items": []}
            if stack:
                stack[-1]["items"].append(n)
            stack.append(n)
        elif t == ")":
            n = stack.pop()
            n["e"] = m.end()
            if not stack:
                return n
        else:
            stack[-1]["items"].append((t, m.start(), m.end()))
    raise ValueError("unbalanced S-expression")


def head(n):
    it = n["items"]
    return it[0][0] if it and isinstance(it[0], tuple) else ""


def top_level(text):
    """[(kind, start, end)] of the board's top-level items. end is exclusive."""
    out, depth, start = [], 0, None
    for m in _TOK.finditer(text):
        t = m.group(0)
        if t == "(":
            depth += 1
            if depth == 2:
                start = m.start()
        elif t == ")":
            if depth == 2:
                k = _TOK.match(text, start + 1)
                out.append((k.group(0) if k else "", start, m.end()))
            depth -= 1
    return out


def splice(text, edits):
    out, pos = [], 0
    for s, e, rep in sorted(edits, key=lambda x: (x[0], x[1])):
        out.append(text[pos:s])
        out.append(rep)
        pos = e
    out.append(text[pos:])
    return "".join(out)


def fmt(v):
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def quote(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def unquote(t):
    return t[1:-1].replace('\\"', '"').replace("\\\\", "\\") if t.startswith('"') else t


def norm_angle(a):
    a = math.fmod(a, 360.0)
    if a <= -180.0:
        a += 360.0
    elif a > 180.0:
        a -= 360.0
    return 0.0 if abs(a) < 1e-9 else a


def norm360(a):
    """Pad and text angles as KiCad writes them inside a footprint: [0, 360)."""
    a = math.fmod(a, 360.0)
    a = a + 360.0 if a < 0 else a
    return 0.0 if abs(a) < 1e-9 or abs(a - 360.0) < 1e-9 else a


def rewrite(text, point=None, angle=None, net=None, layer=None, new_uuid=None, drop=(), name=None, strip_nets=False):
    """Rewrite one item's S-expression text.

    point(x, y) -> (x, y) applies to every at/start/end/mid/center/xy list outside pad primitives and 3D models;
    angle(a) -> a to the angle of `at` lists of the item itself and of its pads and texts (absolute in KiCad files);
    net(name) -> name and layer(name) -> name rename; new_uuid replaces the item's own uuid; lists whose head is in
    drop are removed; name replaces a zone's name; strip_nets removes (net ...) lists.
    """
    root = tree(text)
    edits = []

    def visit(n, parents):
        h = head(n)
        if h in drop or (strip_nets and h == "net"):
            edits.append((n["s"], n["e"], ""))
            return
        if h in OPAQUE:
            return
        atoms = [a for a in n["items"][1:] if isinstance(a, tuple)]
        parent = parents[-1] if parents else None
        if h in POINT_HEADS and point is not None and len(atoms) >= 2:
            x, y = point(float(atoms[0][0]), float(atoms[1][0]))
            edits.append((atoms[0][1], atoms[0][2], fmt(x)))
            edits.append((atoms[1][1], atoms[1][2], fmt(y)))
        if h == "at" and angle is not None and (parent is None or parent in ANGLE_PARENTS):
            # KiCad writes an item's angle in (-180, 180], pad and text angles in [0, 360); a pad leaves out 0,
            # a text always writes it
            norm = norm_angle if parent is None else norm360
            keep_zero = parent not in (None, "pad")
            a = norm(angle(float(atoms[2][0]) if len(atoms) >= 3 else 0.0))
            if len(atoms) >= 3:
                edits.append((atoms[1][2], atoms[2][2], f" {fmt(a)}" if a or keep_zero else ""))
            elif len(atoms) == 2 and (a or keep_zero):
                edits.append((atoms[1][2], atoms[1][2], " " + fmt(a)))
        if h == "net" and net is not None and atoms:
            edits.append((atoms[0][1], atoms[0][2], quote(net(unquote(atoms[0][0])))))
        if h in ("layer", "layers") and layer is not None:
            for a in atoms:
                if a[0].startswith('"'):
                    edits.append((a[1], a[2], quote(layer(unquote(a[0])))))
        if h == "uuid" and new_uuid is not None and not parents[1:] and atoms:
            edits.append((atoms[0][1], atoms[0][2], quote(new_uuid)))
        if h == "name" and name is not None and parent == "zone" and atoms:
            edits.append((atoms[0][1], atoms[0][2], quote(name)))
        for c in n["items"]:
            if isinstance(c, dict):
                visit(c, parents + [h])

    visit(root, [])
    return splice(text, edits)


# ------------------------------------------------------------------------------------------------- geometry
def turn(dx, dy, deg):
    """KiCad rotation: counter-clockwise on a y-down board."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return dx * c + dy * s, -dx * s + dy * c


def fit_angle(src, dst):
    """Angle (KiCad sense) that best turns the centred src points onto the centred dst points."""
    sx, sy = sum(p[0] for p in src) / len(src), sum(p[1] for p in src) / len(src)
    tx, ty = sum(p[0] for p in dst) / len(dst), sum(p[1] for p in dst) / len(dst)
    a = b = 0.0
    for (px, py), (qx, qy) in zip(src, dst):
        px, py, qx, qy = px - sx, py - sy, qx - tx, qy - ty
        a += px * qx + py * qy
        b += py * qx - px * qy
    return math.degrees(math.atan2(b, a)), (sx, sy), (tx, ty)


def snap(a, step, tol):
    k = round(a / step) * step
    return k if abs(a - k) <= tol else a


class Frame:
    """Block frame -> board: turn by rot about the box centre c, then move c to at."""

    def __init__(self, c, at, rot):
        self.c, self.at, self.rot = c, at, rot

    def point(self, x, y):
        dx, dy = turn(x - self.c[0], y - self.c[1], self.rot)
        return self.at[0] + dx, self.at[1] + dy

    def angle(self, a):
        return a + self.rot


def pad_groups(pads):
    """{number: (x, y, net)}: pads sharing a number (exposed pad and its thermal vias) count as their centroid."""
    acc = {}
    for p in pads:
        if not p["num"]:
            continue
        acc.setdefault(p["num"], []).append(p)
    out = {}
    for num, ps in acc.items():
        nets = {p["net"] for p in ps if p["net"]}
        out[num] = (sum(p["x"] for p in ps) / len(ps), sum(p["y"] for p in ps) / len(ps), sorted(nets)[0] if nets else "")
    return out


# ------------------------------------------------------------------------------------------------- reading
def _layer_names(node):
    lay = R.child(node, "layers") or R.child(node, "layer")
    return [str(x) for x in lay[1:]] if lay else []


def _poly_points(pts):
    xy = []
    for q in pts[1:] if pts else []:
        if q[0] == "xy":
            xy.append((float(q[1]), float(q[2])))
        elif q[0] == "arc":
            xy += [(float(R.child(q, k)[1]), float(R.child(q, k)[2])) for k in ("start", "mid", "end")]
    return xy


def _net(node):
    n = R.child(node, "net")
    return str(n[1]) if n and len(n) > 1 else ""


class PCB:
    """A KiCad 10 board: footprints (pads with local and board positions), copper items and groups, with text spans."""

    def __init__(self, path, check_version=True):
        self.path = pathlib.Path(path)
        self.text = self.path.read_text(encoding="utf-8")
        tops = top_level(self.text)
        ver = re.search(r"\(version\s+(\d+)\)", self.text[:500])
        if check_version and (not ver or int(ver.group(1)) < R.MIN_FILE_VERSION):
            sys.exit(f"{path}: older than KiCad 10. Open it in KiCad 10 and save it (D4).")
        self.copper = []
        self.footprints, self.items, self.groups = [], [], []
        for kind, s, e in tops:
            if kind == "layers":
                for entry in R.parse_sexpr(self.text[s:e])[1:]:
                    if isinstance(entry, list) and len(entry) >= 2 and str(entry[1]).endswith(".Cu"):
                        self.copper.append(str(entry[1]))
            elif kind == "footprint":
                self.footprints.append(self._footprint(s, e))
            elif kind in COPPER_ITEMS:
                it = self._item(kind, s, e)
                if it:
                    self.items.append(it)
            elif kind == "group":
                g = R.parse_sexpr(self.text[s:e])
                mem = R.child(g, "members")
                u = R.child(g, "uuid") or R.child(g, "id")
                self.groups.append(dict(name=str(g[1]) if len(g) > 1 and not isinstance(g[1], list) else "",
                                        uuid=str(u[1]) if u else "", members=[str(m) for m in mem[1:]] if mem else [],
                                        s=s, e=e))
        self.nets = sorted({p["net"] for f in self.footprints for p in f["pads"] if p["net"]}
                           | {i["net"] for i in self.items if i["net"]})

    def _footprint(self, s, e):
        fp = R.parse_sexpr(self.text[s:e])
        fx, fy, rot = R.footprint_place(fp)
        ref = value = ""
        for p in R.children(fp, "property"):
            if len(p) > 2 and p[1] == "Reference":
                ref = str(p[2])
            if len(p) > 2 and p[1] == "Value":
                value = str(p[2])
        pads = []
        for pad in R.children(fp, "pad"):
            pat = R.child(pad, "at")
            dx, dy = float(pat[1]), float(pat[2])
            x, y = fx + turn(dx, dy, rot)[0], fy + turn(dx, dy, rot)[1]
            size = R.child(pad, "size")
            w, h = (float(size[1]), float(size[2])) if size else (0.0, 0.0)
            rr = R.child(pad, "roundrect_rratio")
            pads.append(dict(num=str(pad[1]), dx=dx, dy=dy, x=x, y=y, net=_net(pad), w=w, h=h,
                             rot=float(pat[3]) if len(pat) > 3 else 0.0, shape=str(pad[3]) if len(pad) > 3 else "rect",
                             rratio=float(rr[1]) if rr else 0.25, layers=_layer_names(pad)))
        u = R.child(fp, "uuid")
        return dict(ref=ref, value=value, lib=str(fp[1]), side=str(R.child(fp, "layer")[1])[0], x=fx, y=fy,
                    rot=rot, locked=R.is_locked(fp), pads=pads, uuid=str(u[1]) if u else "", s=s, e=e)

    def _item(self, kind, s, e):
        node = R.parse_sexpr(self.text[s:e])
        u = R.child(node, "uuid")
        it = dict(kind=kind, s=s, e=e, uuid=str(u[1]) if u else "", net=_net(node), layers=_layer_names(node))
        if kind == "zone":
            attr = R.child(node, "attr")
            if attr and R.child(attr, "teardrop"):
                return None
            it["keepout"] = bool(R.child(node, "keepout"))
            it["polys"] = [_poly_points(R.child(p, "pts")) for p in R.children(node, "polygon")]
        elif kind in ("segment", "arc"):
            it["pts"] = [(float(R.child(node, k)[1]), float(R.child(node, k)[2]))
                         for k in (("start", "mid", "end") if kind == "arc" else ("start", "end"))]
            it["w"] = float(R.child(node, "width")[1])
        elif kind == "via":
            at = R.child(node, "at")
            it["pts"] = [(float(at[1]), float(at[2]))]
            it["d"] = float(R.child(node, "size")[1])
            it["drill"] = float(R.child(node, "drill")[1])
        else:
            pts = []
            for k in ("start", "mid", "end", "center"):
                c = R.child(node, k)
                if c:
                    pts.append((float(c[1]), float(c[2])))
            pts += _poly_points(R.child(node, "pts"))
            it["pts"] = pts
        if not any(l.endswith(".Cu") for l in it["layers"]):
            return None
        return it

    def by_ref(self):
        return {f["ref"]: f for f in self.footprints}

    def span_layers(self, layers):
        """Copper layers an item reaches: a via's pair spans everything between."""
        if "*.Cu" in layers or "F&B.Cu" in layers:
            return set(self.copper)
        idx = sorted(self.copper.index(l) for l in layers if l in self.copper)
        return set(self.copper[idx[0]:idx[-1] + 1]) if len(idx) >= 2 else set(l for l in layers if l in self.copper)


# ------------------------------------------------------------------------------------------------- import / list
def cmd_import(a):
    cli = R.find_cli(a.kicad_cli)
    if not cli:
        sys.exit("kicad-cli not found: install KiCad 10 or pass --kicad-cli")
    out = pathlib.Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = out.with_suffix(".import.txt")
    cmd = [cli, "pcb", "import", "--format", a.format, "--report-format", "text", "--report-file", str(report),
           "-o", str(out), a.input]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"kicad-cli pcb import failed ({r.returncode}):\n{r.stdout}{r.stderr}")
    print(f"{a.input}: sha256 {sha256(a.input)}")
    print(f"-> {out} (import report: {report})")
    ign = subprocess.run(["git", "-C", str(out.parent), "check-ignore", "-q", str(out.resolve())], capture_output=True)
    if ign.returncode == 1:
        print(f"warning: {out} is not gitignored. Vendor files stay out of the repository (keep them in reference/).")
    return 0


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inside_box(pts, b, tol=1e-6):
    return all(b[0] - tol <= x <= b[2] + tol and b[1] - tol <= y <= b[3] + tol for x, y in pts)


def cmd_list(a):
    src = PCB(a.vendor, check_version=False)
    b = a.box
    print(f"{src.path.name}: copper {', '.join(src.copper)}")
    print("parts:")
    for f in sorted(src.footprints, key=lambda f: f["ref"]):
        if b and not inside_box([(f["x"], f["y"])], b):
            continue
        print(f"  {f['ref']:8} {f['value'][:24]:24} {f['lib'][:40]:40} {f['side']} at {fmt(f['x'])} {fmt(f['y'])} "
              f"rot {fmt(f['rot'])}")
    counts = {}
    for it in src.items:
        if b and not inside_box(it.get("pts") or [p for poly in it.get("polys", []) for p in poly][:1], b):
            continue
        if not it.get("keepout"):
            counts.setdefault(it["net"] or "(no net)", {}).setdefault(it["kind"], 0)
            counts[it["net"] or "(no net)"][it["kind"]] += 1
    print("copper nets:")
    for net in sorted(counts):
        print(f"  {net:24} " + ", ".join(f"{k} {v}" for k, v in sorted(counts[net].items())))
    return 0


# ------------------------------------------------------------------------------------------------- extract
def derive_nets(src, ours, parts):
    """Vendor net -> our net, from the pads of mapped parts. Returns (map, conflicts, notes)."""
    vend, mine = src.by_ref(), ours.by_ref()
    seen, notes = {}, []
    for vref, oref in parts.items():
        if oref not in mine:
            notes.append(f"{oref} (for {vref}) is not on {ours.path.name}: its nets are not derived")
            continue
        vg, og = pad_groups(vend[vref]["pads"]), pad_groups(mine[oref]["pads"])
        for num, (_, _, vnet) in vg.items():
            if not vnet:
                continue
            if num not in og:
                notes.append(f"{oref} has no pad {num} (vendor {vref} has, net {vnet})")
                continue
            onet = og[num][2]
            if onet:
                seen.setdefault(vnet, {}).setdefault(onet, []).append(f"{oref}.{num}")
    derived, conflicts = {}, []
    for vnet, targets in sorted(seen.items()):
        if len(targets) == 1:
            derived[vnet] = next(iter(targets))
        else:
            conflicts.append(f"vendor net {vnet} lands on " +
                             "; ".join(f"{o} ({', '.join(p[:4])})" for o, p in sorted(targets.items())))
    return derived, conflicts, notes


def _hits_pad(x, y, net, layer, pads):
    for p in pads:
        if p["net"] == net and (layer in p["layers"] or "*.Cu" in p["layers"] or layer == "*"):
            shape = R.pad_shape(p["x"], p["y"], p["rot"], p["w"], p["h"], p["shape"], p["rratio"])
            if R.shape_gap(R.shape_point(x, y, 0.0), shape) <= EPS:
                return True
    return False


def _dist_seg(px, py, a, b):
    (x1, y1), (x2, y2) = a, b
    dx, dy = x2 - x1, y2 - y1
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L))
    return math.hypot(px - x1 - t * dx, py - y1 - t * dy)


def prune(tracks, vias, zones, pads, span):
    """Drop tracks with an end on nothing of their net, and vias that connect to nothing of their net, until stable."""
    alive_t, alive_v = set(range(len(tracks))), set(range(len(vias)))
    zpolys = [(z["net"], set(z["layers"]), [Polygon(p).buffer(0) for p in z["polys"] if len(p) >= 3]) for z in zones]

    def on_zone(x, y, net, layers):
        pt = Point(x, y)
        return any(zn == net and zl & layers and any(p.buffer(EPS).contains(pt) for p in ps) for zn, zl, ps in zpolys)

    def end_ok(i, x, y):
        t = tracks[i]
        lay = t["layers"][0]
        if _hits_pad(x, y, t["net"], lay, pads) or on_zone(x, y, t["net"], {lay}):
            return True
        for j in alive_v:
            v = vias[j]
            if v["net"] == t["net"] and lay in span(v["layers"]) and \
                    math.hypot(x - v["pts"][0][0], y - v["pts"][0][1]) <= v["d"] / 2 + EPS:
                return True
        for j in alive_t:
            if j == i:
                continue
            o = tracks[j]
            if o["net"] != t["net"] or o["layers"][0] != lay:
                continue
            if any(_dist_seg(x, y, a, b) <= o["w"] / 2 + EPS for a, b in zip(o["pts"], o["pts"][1:])):
                return True
        return False

    def via_ok(j):
        v = vias[j]
        (x, y), r, lays = v["pts"][0], v["d"] / 2, span(v["layers"])
        for i in alive_t:
            t = tracks[i]
            if t["net"] == v["net"] and t["layers"][0] in lays and \
                    any(math.hypot(x - px, y - py) <= r + EPS for px, py in (t["pts"][0], t["pts"][-1])):
                return True
        if any(_hits_pad(x, y, v["net"], lay, pads) for lay in lays):
            return True
        return on_zone(x, y, v["net"], lays)

    changed = True
    while changed:
        changed = False
        for i in sorted(alive_t):
            t = tracks[i]
            if not (end_ok(i, *t["pts"][0]) and end_ok(i, *t["pts"][-1])):
                alive_t.discard(i)
                changed = True
        for j in sorted(alive_v):
            if not via_ok(j):
                alive_v.discard(j)
                changed = True
    return alive_t, alive_v


def clip_zone(src, it, bx):
    """The zone's text cut to the box: one text per resulting piece, without fills. Holes are reported, not kept."""
    out, holes = [], 0
    for poly in it["polys"]:
        if len(poly) < 3:
            continue
        cut = Polygon(poly).buffer(0).intersection(bx)
        for g in getattr(cut, "geoms", [cut]):
            if g.is_empty or g.geom_type != "Polygon" or g.area < 1e-6:
                continue
            holes += len(g.interiors)
            out.append([(round(x, 6), round(y, 6)) for x, y in list(g.exterior.coords)[:-1]])
    text = rewrite(src.text[it["s"]:it["e"]], drop=("polygon", "filled_polygon", "fill_segments"))
    return [(text, pts) for pts in out], holes


def with_polygon(text, pts):
    body = " ".join(f"(xy {fmt(x)} {fmt(y)})" for x, y in pts)
    i = text.rstrip().rfind(")")
    return text[:i].rstrip() + f"\n\t\t(polygon\n\t\t\t(pts\n\t\t\t\t{body}\n\t\t\t)\n\t\t)\n\t)"


def export_footprint(src, f, prefix, source):
    """The vendor's land pattern as a library footprint, origin at the centre of its pads, orientation 0."""
    xs, ys = [p["dx"] for p in f["pads"]], [p["dy"] for p in f["pads"]]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    name = prefix + re.sub(r"[^A-Za-z0-9_.+-]", "_", f["lib"].split(":")[-1])
    text = src.text[f["s"]:f["e"]]
    root = tree(text)
    edits, named = [], False
    for c in root["items"][1:]:
        if isinstance(c, tuple):
            if not named:
                edits.append((c[1], c[2], quote(name)))      # the footprint's lib id
                named = True
        elif head(c) in ("at", "path", "sheetname", "sheetfile", "locked", "model"):
            edits.append((c["s"], c["e"], ""))
    text = splice(text, edits)
    text = rewrite(text, point=lambda x, y: (x - cx, y - cy), angle=lambda a: a - f["rot"], strip_nets=True,
                   drop=("pinfunction", "pintype"))
    text = re.sub(r'\(property "Reference" "[^"]*"', '(property "Reference" "REF**"', text, count=1)
    descr = f"Vendor land pattern of {f['ref']} ({f['lib']}), origin at the centre of its pads. {source}"
    if re.search(r"\(descr ", text):
        text = re.sub(r'\(descr "(?:[^"\\]|\\.)*"\)', "(descr " + quote(descr).replace("\\", "\\\\") + ")", text, count=1)
    else:
        text = text.replace(quote(name), quote(name) + "\n\t(descr " + quote(descr) + ")", 1)
    text = text.replace(quote(name), quote(name) + '\n\t(version 20260206)\n\t(generator "refblock")', 1)
    text = re.sub(r"\n\s*\n", "\n", text)
    return name, (cx, cy), text + "\n"


def cmd_extract(a):
    src = PCB(a.vendor, check_version=False)
    m = json.loads(pathlib.Path(a.map).read_text(encoding="utf-8"))
    for k in ("name", "source", "parts"):
        if not m.get(k):
            sys.exit(f"{a.map}: '{k}' is required (name of the block, licence/attribution line, vendor -> our refs)")
    vend = src.by_ref()
    missing = [r for r in m["parts"] if r not in vend]
    if missing:
        sys.exit(f"not on {src.path.name}: {', '.join(missing)}")
    parts = {r: vend[r] for r in m["parts"]}
    if m.get("box"):
        b = tuple(float(v) for v in m["box"])
    else:
        pts = [(p["x"], p["y"]) for f in parts.values() for p in f["pads"]]
        b = (min(x for x, _ in pts) - a.margin, min(y for _, y in pts) - a.margin,
             max(x for x, _ in pts) + a.margin, max(y for _, y in pts) + a.margin)
    bx = shp_box(*b)
    layer_map = {l: l for l in src.copper}
    layer_map.update(m.get("layers", {}))
    drop = set(m.get("drop_nets", []))

    nets = dict(m.get("nets", {}))
    errors, notes = [], []
    if a.board:
        ours = PCB(a.board)
        derived, conflicts, n2 = derive_nets(src, ours, m["parts"])
        errors += conflicts
        notes += n2
        for vnet, onet in derived.items():
            if vnet in nets and resolve(ours, nets[vnet], errors) not in (onet, None):
                errors.append(f"map says {vnet} -> {nets[vnet]}, but our pads put it on {onet}")
            nets.setdefault(vnet, onet)

    # copper inside the box, on nets we keep
    pads = [p for f in parts.values() for p in f["pads"]]
    tracks, vias, zones, keepouts, graphics, unmapped, nonet = [], [], [], [], [], {}, 0
    for it in src.items:
        if it["kind"] == "zone":
            if not any(len(p) >= 3 and Polygon(p).buffer(0).intersects(bx) for p in it["polys"]):
                continue
        elif not it["pts"] or not inside_box(it["pts"], b):
            continue
        if it["net"] in drop:
            continue
        if it["kind"] == "zone" and it["keepout"]:
            keepouts.append(it)
            continue
        if not it["net"]:
            if it["kind"].startswith("gr_"):
                graphics.append(it)
            else:
                nonet += 1
            continue
        if it["net"] not in nets:
            unmapped.setdefault(it["net"], 0)
            unmapped[it["net"]] += 1
            continue
        {"segment": tracks, "arc": tracks, "via": vias, "zone": zones}.get(it["kind"], graphics).append(it)
    pad_nets = {p["net"] for p in pads if p["net"]}
    for net, n in sorted(unmapped.items()):
        if net in pad_nets:
            errors.append(f"vendor net {net}: on a copied pad and {n} copper item(s), not mapped "
                          "(add it to 'nets', or pass --board to derive it)")
        else:
            notes.append(f"dropped vendor net {net}: {n} copper item(s), on no copied pad (map it in 'nets' to keep it)")
    if errors:
        for e in notes + errors:
            print(("error: " if e in errors else "note: ") + e)
        return 1

    alive_t, alive_v = prune(tracks, vias, zones, pads, src.span_layers)
    zone_texts, holes = [], 0
    for z in zones:
        pieces, h = clip_zone(src, z, bx)
        holes += h
        zone_texts += [(z, t, p) for t, p in pieces]
    ko_texts = []
    for z in keepouts:
        pieces, _ = clip_zone(src, z, bx)
        ko_texts += [(z, t, p) for t, p in pieces]

    def item(it, text=None, polygon=None):
        d = dict(kind=it["kind"], net=it["net"], layers=it["layers"], sexpr=text or src.text[it["s"]:it["e"]])
        if polygon is not None:
            d["polygon"] = polygon
        return d

    kept_t = [tracks[i] for i in sorted(alive_t)]
    kept_v = [vias[i] for i in sorted(alive_v)]
    block = dict(
        format=FORMAT, name=m["name"], source=m["source"], vendor_board=src.path.name,
        files={pathlib.Path(f).name: sha256(f) for f in (a.files or [])},
        frame="vendor board frame (KiCad import), mm, y down", box=[round(v, 6) for v in b],
        layers=layer_map, net_map=dict(sorted(nets.items())),
        parts=[dict(ref=r, ours=m["parts"][r], value=f["value"], footprint=f["lib"], side=f["side"],
                    at=[f["x"], f["y"]], rot=f["rot"],
                    pads=[[p["num"], round(p["x"], 6), round(p["y"], 6), p["net"]] for p in f["pads"]])
               for r, f in parts.items()],
        items=[item(t) for t in kept_t] + [item(v) for v in kept_v] +
              [item(z, t, p) for z, t, p in zone_texts] + [item(z, t, p) for z, t, p in ko_texts] +
              [item(g) for g in graphics],
        stats=dict(min_track=min((t["w"] for t in kept_t), default=None),
                   min_via=min((v["d"] for v in kept_v), default=None),
                   min_drill=min((v["drill"] for v in kept_v), default=None),
                   min_via_annular=min(((v["d"] - v["drill"]) / 2 for v in kept_v), default=None)),
        pruned=dict(tracks=len(tracks) - len(kept_t), vias=len(vias) - len(kept_v), no_net=nonet, zone_holes=holes),
        not_copied=m.get("not_copied", ""),
    )
    if a.footprints:
        lib = pathlib.Path(a.footprints)
        lib.mkdir(parents=True, exist_ok=True)
        for r, f in parts.items():
            if f["side"] != "F":
                notes.append(f"{r} is on the back: export its land in KiCad (Footprint Editor), not here")
                continue
            name, c, text = export_footprint(src, f, a.prefix, m["source"])
            (lib / f"{name}.kicad_mod").write_text(text, encoding="utf-8")
            notes.append(f"{r}: {lib.name}/{name}.kicad_mod (origin moved {fmt(c[0])}, {fmt(c[1])} from the vendor's)")
    pathlib.Path(a.output).write_text(json.dumps(block, indent=1) + "\n", encoding="utf-8")
    for n in notes:
        print("note:", n)
    k = {}
    for it in block["items"]:
        k[it["kind"]] = k.get(it["kind"], 0) + 1
    print(f"{a.output}: {len(parts)} parts, " + ", ".join(f"{v} {n}" for n, v in sorted(k.items())) +
          f"; pruned {block['pruned']['tracks']} tracks, {block['pruned']['vias']} vias")
    if holes:
        print(f"warning: {holes} hole(s) in the vendor's pour outlines were not kept: redraw them as cut-outs")
    return 0


# ------------------------------------------------------------------------------------------------- place
def resolve(ours, name, errors):
    """A map value as our board's net name: exact, or the one hierarchical net ending in /name."""
    if name in ours.nets:
        return name
    cands = [n for n in ours.nets if n.rsplit("/", 1)[-1] == name]
    if len(cands) == 1:
        return cands[0]
    errors.append(f"net {name}: " + ("not on our board" if not cands else "ambiguous: " + ", ".join(cands)))
    return None


def fit_block(block, ours):
    """Where the block sits on our board now: (Frame, worst pad distance) from our parts' pads, rot snapped to 90."""
    mine = ours.by_ref()
    src, dst = [], []
    for p in block["parts"]:
        f = mine.get(p["ours"])
        if not f:
            continue
        vg = pad_groups([dict(num=n, x=x, y=y, net=net) for n, x, y, net in p["pads"]])
        og = pad_groups(f["pads"])
        for num in vg:
            if num in og:
                src.append(vg[num][:2])
                dst.append(og[num][:2])
    if len(src) < 2:
        return None
    rot, (sx, sy), (tx, ty) = fit_angle(src, dst)
    rot = norm_angle(round(rot / 90.0) * 90.0)
    c = ((block["box"][0] + block["box"][2]) / 2, (block["box"][1] + block["box"][3]) / 2)
    dx, dy = turn(sx - c[0], sy - c[1], rot)
    return Frame(c, (tx - dx, ty - dy), rot)


def plan_parts(block, ours, frame, net_of, tol):
    """Each part's new position and angle, or errors."""
    mine = ours.by_ref()
    moves, errors, report = [], [], []
    for p in block["parts"]:
        f = mine.get(p["ours"])
        if not f:
            errors.append(f"{p['ours']} (vendor {p['ref']}) is not on the board: update the PCB from the schematic first")
            continue
        if f["side"] != p["side"]:
            errors.append(f"{p['ours']} is on {f['side']}.Cu, the vendor's {p['ref']} on {p['side']}.Cu: flip it in KiCad first")
            continue
        vg = pad_groups([dict(num=n, x=x, y=y, net=net) for n, x, y, net in p["pads"]])
        og = {}
        for q in f["pads"]:
            if q["num"]:
                og.setdefault(q["num"], []).append(q)
        nums = [n for n in vg if n in og]
        miss = sorted(set(vg) ^ set(og))
        if miss:
            errors.append(f"{p['ours']}: pad numbers differ from the vendor's {p['ref']} ({', '.join(miss[:8])})")
            continue
        for n in nums:
            vnet = vg[n][2]
            want = net_of(vnet) if vnet else None
            have = {q["net"] for q in og[n]}
            if want and have != {want}:
                errors.append(f"{p['ours']}.{n} is on {', '.join(sorted(have)) or 'no net'}, the copy puts {vnet} "
                              f"-> {want} there (the schematic disagrees with the vendor's wiring)")
        targets = [frame.point(*vg[n][:2]) for n in nums]
        locals_ = [(sum(q["dx"] for q in og[n]) / len(og[n]), sum(q["dy"] for q in og[n]) / len(og[n])) for n in nums]
        if len(nums) >= 2:
            theta, (sx, sy), (tx, ty) = fit_angle(locals_, targets)
            theta = norm_angle(snap(round(theta, 4), 90.0, 0.01))
        else:
            theta = norm_angle(frame.angle(p["rot"]))   # one pad: assume our land's 0 is the vendor's
            (sx, sy), (tx, ty) = locals_[0], targets[0]
        ox, oy = turn(sx, sy, theta)
        x, y = tx - ox, ty - oy
        worst = max(math.hypot(x + turn(dx, dy, theta)[0] - X, y + turn(dx, dy, theta)[1] - Y)
                    for (dx, dy), (X, Y) in zip(locals_, targets))
        if worst > tol:
            errors.append(f"{p['ours']}: its land differs from the vendor's {p['ref']} by {worst:.3f} mm "
                          f"(--tol {tol}): use the vendor's land (extract --footprints) or raise --tol")
            continue
        moved = math.hypot(x - f["x"], y - f["y"]) > 1e-4 or abs(norm_angle(theta - f["rot"])) > 1e-3
        if moved and f["locked"]:
            errors.append(f"{p['ours']} is locked: the owner's anchors never move. Unlock it or place the block on it")
            continue
        moves.append((f, x, y, theta))
        report.append(f"  {p['ref']:6} -> {p['ours']:8} at {fmt(round(x, 4))} {fmt(round(y, 4))} rot {fmt(theta)}"
                      f"  (pads within {worst * 1000:.1f} um){'' if moved else '  unchanged'}")
    return moves, errors, report


def footprint_moved(ours, f, x, y, theta):
    text = ours.text[f["s"]:f["e"]]
    root = tree(text)
    edits = []
    d = norm_angle(theta - f["rot"])
    for c in root["items"][1:]:
        if not isinstance(c, dict):
            continue
        h = head(c)
        if h == "at":
            new = f"(at {fmt(round(x, 6))} {fmt(round(y, 6))}" + (f" {fmt(theta)})" if theta else ")")
            edits.append((c["s"] - root["s"], c["e"] - root["s"], new))
        elif h == "transform":
            sub = text[c["s"] - root["s"]:c["e"] - root["s"]]
            sub = re.sub(r"\(translate\s+[^()]*\)", f"(translate {fmt(round(x, 6))} {fmt(round(y, 6))})", sub)
            sub = re.sub(r"\(rotate\s+[^()]*\)", f"(rotate {fmt(theta)})", sub)
            edits.append((c["s"] - root["s"], c["e"] - root["s"], sub))
        elif h in ANGLE_PARENTS and d:
            sub = text[c["s"] - root["s"]:c["e"] - root["s"]]
            at = next((g for g in c["items"] if isinstance(g, dict) and head(g) == "at"), None)
            if at:
                a_txt = sub[at["s"] - c["s"]:at["e"] - c["s"]]
                a_new = rewrite(f"({h} {a_txt})", angle=lambda a: a + d)[len(h) + 2:-1]   # as its parent writes it
                edits.append((at["s"] - root["s"], at["e"] - root["s"], a_new))
    return splice(text, edits)


def new_uuid(name, kind, i):
    return str(uuidlib.uuid5(NS, f"{name}/{kind}/{i}"))


def fab_report(block, ours, fab):
    prof = R.load_profile(fab)
    key = "2" if len(ours.copper) <= 2 else "4+"
    lim = prof["layers"].get(key, prof["layers"].get("4+", {})).get("fab_min", {})
    s, out = block["stats"], []
    for stat, rule in (("min_track", "track"), ("min_via", "via_diameter"), ("min_drill", "via_drill"),
                       ("min_via_annular", "via_annular")):
        if s.get(stat) is not None and rule in lim and s[stat] < lim[rule] - 1e-6:
            out.append(f"{stat.replace('_', ' ')} {s[stat]:.3f} mm is below {fab}'s {lim[rule]:.3f} mm ({rule})")
    return out


def cmd_place(a):
    block = json.loads(pathlib.Path(a.block).read_text(encoding="utf-8"))
    if block.get("format") != FORMAT:
        sys.exit(f"{a.block}: not a {FORMAT} block")
    ours = PCB(a.board)
    name = block["name"]
    group = next((g for g in ours.groups if g["name"] == name), None)
    if group and not a.replace:
        print(f"'{name}' is already on {ours.path.name} (group): nothing done. --replace pastes it again.")
        return 0
    errors = []
    net_of_raw = {v: resolve(ours, n, errors) for v, n in block["net_map"].items()}
    for v, lay in block["layers"].items():
        if lay not in ours.copper and any(lay in it["layers"] for it in block["items"]):
            errors.append(f"layer {lay} (vendor {v}) is not on our board: map it in the map's 'layers'")
    if a.at:
        c = ((block["box"][0] + block["box"][2]) / 2, (block["box"][1] + block["box"][3]) / 2)
        frame = Frame(c, tuple(a.at), float(a.rot))
    else:
        frame = fit_block(block, ours)
        if frame is None:
            sys.exit("give --at X Y (and --rot): the block's parts are not on the board yet to fit to")
        if not group:
            errors.append("no --at given and the block is not placed yet: give --at X Y (and --rot)")
    moves, e2, report = plan_parts(block, ours, frame, lambda v: net_of_raw.get(v), a.tol)
    errors += e2
    if errors:
        for e in errors:
            print("error:", e)
        print("nothing written")
        return 1

    def line(s, e):           # the item with the line it starts on
        return ours.text.rfind("\n", 0, s), e

    edits, removed = [], set()
    if group:
        members = set(group["members"])
        for it in ours.items:
            if it["uuid"] in members:
                edits.append((*line(it["s"], it["e"]), ""))
                removed.add(it["uuid"])
        edits.append((*line(group["s"], group["e"]), ""))
    stale = {new_uuid(name, it["kind"], i) for i, it in enumerate(block["items"])} & \
        ({it["uuid"] for it in ours.items} - removed)
    if stale:
        print(f"error: {len(stale)} copper item(s) of '{name}' are on the board outside its group (handed over?): "
              "delete them in KiCad before pasting again\nnothing written")
        return 1
    moved_uuids = []
    in_other = {m for g in ours.groups if g is not group for m in g["members"]}
    for f, x, y, theta in moves:
        edits.append((f["s"], f["e"], footprint_moved(ours, f, x, y, theta)))
        if f["uuid"] not in in_other:
            moved_uuids.append(f["uuid"])

    lay_of = block["layers"]
    pasted, counts = [], {}
    for i, it in enumerate(block["items"]):
        u = new_uuid(name, it["kind"], i)
        kind = it["kind"]
        text = it["sexpr"]
        zname = None
        if kind == "zone":
            pieces = sum(1 for j in block["items"][:i] if j["kind"] == "zone")
            label = net_of_raw.get(it["net"]) or it["net"] or "rule area"
            zname = f"{name} {'/'.join(lay_of.get(l, l) for l in it['layers'])} {label} {pieces + 1}"
            text = with_polygon(text, it["polygon"])
            if not any(isinstance(c, dict) and head(c) == "name" for c in tree(text)["items"]):
                text = text.replace("(zone", "(zone\n\t\t(name " + quote(zname) + ")", 1)
        text = rewrite(text, point=frame.point, angle=frame.angle if kind not in ("segment", "arc", "via") else None,
                       net=lambda n: net_of_raw.get(n, n), layer=lambda l: lay_of.get(l, l), new_uuid=u,
                       drop=("filled_polygon", "fill_segments"), name=zname)
        pasted.append(text.strip())
        moved_uuids.append(u)
        counts[kind] = counts.get(kind, 0) + 1
    gid = new_uuid(name, "group", 0)
    members = " ".join(quote(m) for m in moved_uuids)
    pasted.append(f"(group {quote(name)}\n\t\t(uuid {quote(gid)})\n\t\t(members {members})\n\t)")
    fonts = next((s for k, s, _ in top_level(ours.text) if k == "embedded_fonts"), None)
    if fonts is not None:             # before (embedded_fonts no), which follows "\n\t"
        edits.append((fonts, fonts, "".join(x + "\n\t" for x in pasted)))
    else:
        tail = ours.text.rstrip().rfind(")")
        edits.append((tail, tail, "".join("\t" + x + "\n" for x in pasted)))
    out = splice(ours.text, edits)

    print(f"'{name}' on {ours.path.name}: centre at {fmt(round(frame.at[0], 4))} {fmt(round(frame.at[1], 4))}, "
          f"rot {fmt(frame.rot)}")
    print("\n".join(report))
    print("  copper: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) + f"; grouped as '{name}'")
    for w in fab_report(block, ours, a.fab) if a.fab else []:
        print("warning:", w)
    refs = {p["ours"] for p in block["parts"]}
    corners = [frame.point(block["box"][0], block["box"][1]), frame.point(block["box"][2], block["box"][3])]
    xs, ys = sorted(p[0] for p in corners), sorted(p[1] for p in corners)
    crowd = sorted(f["ref"] for f in ours.footprints
                   if f["ref"] not in refs and xs[0] <= f["x"] <= xs[1] and ys[0] <= f["y"] <= ys[1])
    if crowd:
        print(f"warning: inside the block's box, not part of it: {', '.join(crowd)} "
              "(move them: pcb-placement optimize --only)")
    if a.dry_run:
        print("dry run: nothing written")
        return 0
    ours.path.write_text(out, encoding="utf-8")
    print("next: pcb_rules.py check (DRC with zone refill); the vendor's bends and clearances may need exclusions")
    return 0


# ------------------------------------------------------------------------------------------------- check
def cmd_check(a):
    block = json.loads(pathlib.Path(a.block).read_text(encoding="utf-8"))
    ours = PCB(a.board)
    errors = []
    net_of_raw = {v: resolve(ours, n, errors) for v, n in block["net_map"].items()}
    frame = fit_block(block, ours)
    if frame is None:
        print(f"'{block['name']}': fewer than two of its pads are on the board")
        return 1
    mine = ours.by_ref()
    print(f"'{block['name']}' fitted at {fmt(round(frame.at[0], 4))} {fmt(round(frame.at[1], 4))}, rot {fmt(frame.rot)}")
    bad = 0
    for p in block["parts"]:
        f = mine.get(p["ours"])
        if not f:
            print(f"  {p['ours']:8} missing")
            bad += 1
            continue
        vg = pad_groups([dict(num=n, x=x, y=y, net=net) for n, x, y, net in p["pads"]])
        og = pad_groups(f["pads"])
        dists = [math.dist(frame.point(*vg[n][:2]), og[n][:2]) for n in vg if n in og]
        worst = max(dists) if dists else float("inf")
        wrong = [n for n in vg if n in og and vg[n][2] and net_of_raw.get(vg[n][2]) and
                 og[n][2] != net_of_raw[vg[n][2]]]
        flag = "ok" if worst <= a.tol and not wrong else "FAIL"
        bad += flag == "FAIL"
        print(f"  {p['ours']:8} pads off by up to {worst:.3f} mm" +
              (f"; net differs on pad {', '.join(wrong)}" if wrong else "") + f"  {flag}")
    group = next((g for g in ours.groups if g["name"] == block["name"]), None)
    if group:
        members = set(group["members"])
        have = sum(1 for it in ours.items if it["uuid"] in members)
        print(f"  group '{block['name']}': {have} of {len(block['items'])} copper items still in it")
    else:
        print(f"  no group '{block['name']}' (handed over to the owner, or not placed)")
    for e in errors:
        print("error:", e)
    return 1 if bad or errors else 0


# ------------------------------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import", help="vendor board -> .kicad_pcb with kicad-cli")
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--format", default="auto")
    p.add_argument("--kicad-cli")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("list", help="parts and copper nets of the vendor board")
    p.add_argument("vendor")
    p.add_argument("--box", type=float, nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("extract", help="vendor board + map -> block JSON")
    p.add_argument("vendor")
    p.add_argument("map")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--board", help="our board: derive the net map from our parts' pads")
    p.add_argument("--files", nargs="*", help="the vendor's original files, to record their sha256")
    p.add_argument("--margin", type=float, default=1.0, help="mm around the parts' pads when the map has no box")
    p.add_argument("--footprints", help="write the vendor's land patterns into this .pretty folder")
    p.add_argument("--prefix", default="REF_", help="footprint name prefix for --footprints")
    p.set_defaults(func=cmd_extract)
    p = sub.add_parser("place", help="block JSON -> our board")
    p.add_argument("block")
    p.add_argument("board")
    p.add_argument("--at", type=float, nargs=2, metavar=("X", "Y"))
    p.add_argument("--rot", type=int, default=0, choices=(0, 90, 180, 270))
    p.add_argument("--replace", action="store_true")
    p.add_argument("--tol", type=float, default=0.02, help="mm a pad may sit from the vendor's (default 0.02)")
    p.add_argument("--fab", help="fab profile to compare the block's tracks and vias with (e.g. jlcpcb)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_place)
    p = sub.add_parser("check", help="is the block still where the vendor has it, relative to its parts?")
    p.add_argument("block")
    p.add_argument("board")
    p.add_argument("--tol", type=float, default=0.02)
    p.set_defaults(func=cmd_check)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
