"""Read a KiCad 10 board into the geometry the eval metrics need, and edit footprints in its text.

Reading uses the S-expression parser of the pcb-design-rules skill (the shared core, docs/design.md D13). Editing works
on the file text: top-level blocks are found by paren matching (quoted strings skipped) and replaced, so everything
not touched stays byte-identical.
"""

import math
import pathlib
import re
import sys

from shapely.geometry import MultiPoint, Polygon
from shapely.ops import polygonize, unary_union

CORE = pathlib.Path(__file__).resolve().parents[1] / "plugins/hardware-design/skills/pcb-design-rules/scripts"
sys.path.insert(0, str(CORE))
import pcb_rules as R  # noqa: E402

COURTYARD = ("F.CrtYd", "B.CrtYd")


# ------------------------------------------------------------------------------------------------- reading
def _xy(node):
    return float(node[1]), float(node[2])


def to_board(fx, fy, rot, dx, dy):
    """Footprint frame -> board, as KiCad does: rotation counter-clockwise on a y-down board."""
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    return fx + dx * c + dy * s, fy - dx * s + dy * c


def _shape_points(node):
    """Points of a graphic item (line, rect, poly, circle, arc), in its own frame."""
    kind = node[0]
    if kind.endswith("_line"):
        return [_xy(R.child(node, "start")), _xy(R.child(node, "end"))]
    if kind.endswith("_rect"):
        (x1, y1), (x2, y2) = _xy(R.child(node, "start")), _xy(R.child(node, "end"))
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    if kind.endswith("_poly"):
        pts = R.child(node, "pts")
        return [_xy(p) for p in R.children(pts, "xy")] if pts else []
    if kind.endswith("_circle"):
        (cx, cy), (ex, ey) = _xy(R.child(node, "center")), _xy(R.child(node, "end"))
        r = math.hypot(ex - cx, ey - cy)
        return [(cx + r * math.cos(a * math.pi / 8), cy + r * math.sin(a * math.pi / 8)) for a in range(16)]
    if kind.endswith("_arc"):
        return [_xy(R.child(node, k)) for k in ("start", "mid", "end")]
    return []


def _layer(node):
    lay = R.child(node, "layer")
    return lay[1] if lay else ""


def convex_hull(points):
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class Board:
    """Footprints (reference, position, lock, side, pads with nets, courtyard hull) and the board outline."""

    def __init__(self, path=None, text=None):
        if text is None:
            text = pathlib.Path(path).read_text(encoding="utf-8")
        self.text = text
        root = R.parse_sexpr(text)
        self.net_names = {n[1]: n[2] for n in R.children(root, "net") if len(n) >= 3}
        self.footprints = [self._footprint(fp) for fp in R.children(root, "footprint")]
        self.outline = self._outline(root)
        self.vias = len(R.children(root, "via"))
        self.segments = len(R.children(root, "segment")) + len(R.children(root, "arc"))

    def _net(self, node):
        n = R.child(node, "net")
        if not n or len(n) < 2:
            return ""
        name = n[2] if len(n) >= 3 else self.net_names.get(n[1], n[1])
        return name.replace("{slash}", "/")

    def _footprint(self, fp):
        at = R.child(fp, "at")
        fx, fy = _xy(at)
        rot = float(at[3]) if len(at) > 3 else 0.0
        ref = ""
        for p in R.children(fp, "property"):
            if len(p) > 2 and p[1] == "Reference":
                ref = p[2]
        uuid = R.child(fp, "uuid")
        pads = []
        for pad in R.children(fp, "pad"):
            px, py = _xy(R.child(pad, "at"))
            x, y = to_board(fx, fy, rot, px, py)
            pads.append(dict(num=pad[1], x=x, y=y, net=self._net(pad)))
        lines, closed = {}, {}
        for g in fp:
            if isinstance(g, list) and g and str(g[0]).startswith("fp_") and _layer(g) in COURTYARD:
                pts = [to_board(fx, fy, rot, x, y) for x, y in _shape_points(g)]
                if g[0] in ("fp_line", "fp_arc"):
                    lines.setdefault(_layer(g), []).extend(zip(pts, pts[1:]))
                elif len(pts) >= 3:
                    closed.setdefault(_layer(g), []).append(Polygon(pts).buffer(0))
        courts, hulls = {}, {}
        for lay in set(lines) | set(closed):
            polys = closed.get(lay, []) + list(polygonize(lines.get(lay, [])))
            pts = [p for s in lines.get(lay, []) for p in s] + [p for q in closed.get(lay, []) for p in q.exterior.coords]
            courts[lay] = unary_union(polys) if polys else MultiPoint(pts).convex_hull   # open outline: its hull
            hulls[lay] = convex_hull(pts)
        if not courts and pads:                  # no courtyard: the pads' hull stands in
            lay = "F.CrtYd" if _layer(fp) == "F.Cu" else "B.CrtYd"
            hulls[lay] = convex_hull([(p["x"], p["y"]) for p in pads])
            courts[lay] = MultiPoint([(p["x"], p["y"]) for p in pads]).convex_hull
        return dict(ref=ref, uuid=uuid[1] if uuid else "", x=fx, y=fy, rot=rot, side=_layer(fp),
                    locked=R.is_locked(fp), pads=pads, hulls=hulls, courts=courts)

    def _outline(self, root):
        segs = []
        for g in root:
            if not (isinstance(g, list) and g and str(g[0]).startswith("gr_") and _layer(g) == "Edge.Cuts"):
                continue
            pts = _shape_points(g)
            if g[0] in ("gr_rect", "gr_poly", "gr_circle"):
                pts = pts + pts[:1]
            segs.extend(zip(pts, pts[1:]))
        return chain(segs)

    def by_ref(self):
        return {f["ref"]: f for f in self.footprints}


def chain(segs, tol=1e-3):
    """Join outline segments into one closed polygon. Falls back to the bounding box if they don't close."""
    if not segs:
        return []
    left = list(segs)
    poly = [left[0][0], left[0][1]]
    left.pop(0)
    while left:
        end = poly[-1]
        for i, (a, b) in enumerate(left):
            if math.dist(a, end) < tol:
                poly.append(b)
                break
            if math.dist(b, end) < tol:
                poly.append(a)
                break
        else:
            break
        left.pop(i)
    if left or math.dist(poly[0], poly[-1]) > tol:
        xs = [p[0] for s in segs for p in s]
        ys = [p[1] for s in segs for p in s]
        return [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]
    return poly[:-1]


def inside(poly, x, y):
    hit = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


# ------------------------------------------------------------------------------------------------- editing
def blocks(text, start=0, end=None):
    """(kind, start, end) of each child list of the list that opens at text[start]. end is exclusive."""
    end = len(text) if end is None else end
    out, depth, i, child_start = [], 0, start, None
    while i < end:
        ch = text[i]
        if ch == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "(":
            depth += 1
            if depth == 2:
                child_start = i
        elif ch == ")":
            if depth == 2:
                m = re.match(r"\(([^\s()\"]+)", text[child_start:child_start + 64])
                out.append((m.group(1) if m else "", child_start, i + 1))
            depth -= 1
            if depth == 0:
                break
        i += 1
    return out


def rewrite(text, edits):
    """Apply (start, end, replacement) edits, which must not overlap."""
    out, pos = [], 0
    for s, e, rep in sorted(edits):
        out.append(text[pos:s])
        out.append(rep)
        pos = e
    out.append(text[pos:])
    return "".join(out)


def footprint_text(block, x=None, y=None, locked=None):
    """A footprint block with its position and/or lock changed. Rotation and everything else are kept."""
    kids = blocks(block)
    edits = []
    for kind, s, e in kids:
        if kind == "at" and x is not None:
            parts = block[s + 1:e - 1].split()
            parts[1], parts[2] = f"{x:.4f}".rstrip("0").rstrip("."), f"{y:.4f}".rstrip("0").rstrip(".")
            edits.append((s, e, "(" + " ".join(parts) + ")"))
            break
    if locked is not None:
        lk = [(s, e) for kind, s, e in kids if kind == "locked"]
        if lk and not locked:
            s, e = lk[0]
            ls = block.rfind("\n", 0, s)
            edits.append((ls, e, ""))
        elif not lk and locked:
            first = kids[0][1]
            indent = block[block.rfind("\n", 0, first):first]
            edits.append((first, first, "(locked yes)" + indent))
    return rewrite(block, edits)
