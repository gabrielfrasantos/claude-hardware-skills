#!/usr/bin/env python3
"""silk.py: silkscreen that carries the references and nothing else, placed where they can be read (KiCad 10+).

    silk.py apply <board.kicad_pcb> [--fab jlcpcb[,seeed]] [--keep-layers NAME,...]
    silk.py check <board.kicad_pcb> [--fab ...] [--report r.md] [--json r.json]

apply   on every footprint: the Value, every free text (the fab layer's ${REFERENCE} copy included) and any
        other property on a silkscreen layer hidden (footprint outlines and polarity marks stay); the Reference visible on the footprint's silkscreen side at the fab's minimum text
        height and stroke; each Reference moved to the first clear spot around its part: inside the board, clear of
        every pad by the fab's silk-to-pad distance, of every silkscreen line and of the references already
        placed, preferably not over another part's courtyard. Parts are placed largest first. Optional layers no
        item uses (User.*, Eco*, Dwgs, Cmts) are removed from the board's layer list.
check   gates: visible silkscreen text other than references, references hidden, overlapping a pad, a silkscreen
        line or another reference, outside the board, or below the fab's text height and stroke.
        Exit 1 when a gate fails.
"""
import argparse
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pcb_rules as PR  # noqa: E402

# KiCad 10 stroke font at size 1, pen centreline: advance, ink left, ink right, height above and depth below the
# centre line of a centre-justified text. Measured with pcbnew 10.0.8 (PCB_TEXT.GetEffectiveTextShape), 2026-11-22.
GLYPHS = {
    "A": (0.857, 0.161, 0.828, 0.543, 0.457), "B": (1.000, 0.304, 0.875, 0.543, 0.457),
    "C": (1.000, 0.256, 0.875, 0.543, 0.457), "D": (1.000, 0.304, 0.875, 0.543, 0.457),
    "E": (0.905, 0.304, 0.780, 0.543, 0.457), "F": (0.857, 0.304, 0.780, 0.543, 0.457),
    "G": (1.000, 0.256, 0.875, 0.543, 0.457), "H": (1.048, 0.304, 0.875, 0.543, 0.457),
    "I": (0.476, 0.304, 0.304, 0.543, 0.457), "J": (0.762, 0.209, 0.590, 0.543, 0.457),
    "K": (1.000, 0.304, 0.875, 0.543, 0.457), "L": (0.809, 0.304, 0.780, 0.543, 0.457),
    "M": (1.143, 0.304, 0.971, 0.543, 0.457), "N": (1.048, 0.304, 0.875, 0.543, 0.457),
    "O": (1.048, 0.256, 0.923, 0.543, 0.457), "P": (1.000, 0.304, 0.875, 0.543, 0.457),
    "Q": (1.048, 0.256, 0.971, 0.543, 0.553), "R": (1.000, 0.304, 0.875, 0.543, 0.457),
    "S": (0.952, 0.256, 0.828, 0.543, 0.457), "T": (0.762, 0.161, 0.733, 0.543, 0.457),
    "U": (1.048, 0.304, 0.875, 0.543, 0.457), "V": (0.857, 0.161, 0.828, 0.543, 0.457),
    "W": (1.143, 0.209, 1.066, 0.543, 0.457), "X": (0.952, 0.209, 0.875, 0.543, 0.457),
    "Y": (0.857, 0.161, 0.828, 0.543, 0.457), "Z": (0.952, 0.209, 0.875, 0.543, 0.457),
    "0": (0.952, 0.256, 0.828, 0.543, 0.457), "1": (0.952, 0.256, 0.828, 0.543, 0.457),
    "2": (0.952, 0.209, 0.828, 0.543, 0.457), "3": (0.952, 0.209, 0.828, 0.543, 0.457),
    "4": (0.952, 0.256, 0.875, 0.590, 0.457), "5": (0.952, 0.256, 0.828, 0.543, 0.457),
    "6": (0.952, 0.256, 0.828, 0.543, 0.457), "7": (0.952, 0.209, 0.875, 0.543, 0.457),
    "8": (0.952, 0.256, 0.828, 0.543, 0.457), "9": (0.952, 0.256, 0.828, 0.543, 0.457),
    "a": (0.905, 0.256, 0.733, 0.209, 0.457), "b": (0.905, 0.304, 0.780, 0.543, 0.457),
    "c": (0.857, 0.256, 0.733, 0.209, 0.457), "d": (0.905, 0.256, 0.733, 0.543, 0.457),
    "e": (0.857, 0.256, 0.733, 0.209, 0.457), "f": (0.571, 0.161, 0.542, 0.543, 0.457),
    "g": (0.905, 0.256, 0.733, 0.209, 0.791), "h": (0.905, 0.304, 0.733, 0.543, 0.457),
    "i": (0.476, 0.256, 0.351, 0.543, 0.457), "j": (0.476, 0.113, 0.351, 0.543, 0.791),
    "k": (0.809, 0.304, 0.685, 0.543, 0.457), "l": (0.524, 0.304, 0.447, 0.543, 0.457),
    "m": (1.333, 0.304, 1.161, 0.209, 0.457), "n": (0.905, 0.304, 0.733, 0.209, 0.457),
    "o": (0.905, 0.256, 0.780, 0.209, 0.457), "p": (0.905, 0.304, 0.780, 0.209, 0.791),
    "q": (0.905, 0.256, 0.733, 0.209, 0.791), "r": (0.619, 0.304, 0.590, 0.209, 0.457),
    "s": (0.809, 0.256, 0.685, 0.209, 0.457), "t": (0.571, 0.161, 0.542, 0.543, 0.457),
    "u": (0.905, 0.304, 0.733, 0.209, 0.457), "v": (0.762, 0.209, 0.685, 0.209, 0.457),
    "w": (1.048, 0.209, 0.971, 0.209, 0.457), "x": (0.809, 0.209, 0.733, 0.209, 0.457),
    "y": (0.762, 0.209, 0.685, 0.209, 0.791), "z": (0.809, 0.209, 0.733, 0.209, 0.457),
    "_": (0.762, 0.066, 0.828, -0.553, 0.553), "-": (1.238, 0.304, 1.066, -0.076, 0.076),
    "+": (1.238, 0.304, 1.066, 0.304, 0.457), ".": (0.476, 0.256, 0.351, -0.362, 0.457),
    "~": (0.714, 0.161, 0.637, 0.019, 0.076), "/": (1.048, 0.161, 1.018, 0.590, 0.696),
    "#": (1.000, 0.161, 0.971, 0.638, 0.648),
}
GLYPH_DEFAULT = (1.0, 0.256, 0.875, 0.543, 0.457)
GLYPH_ORIGIN = 0.0658    # the table's left/right include this offset (0.658 x the 0.1 pen it was measured with)
TEXT_MARGIN = 0.02
SILK_CLEAR = 0.15
OPTIONAL_LAYERS = re.compile(r"^(User\.\d+|User\.(Drawings|Comments|Eco1|Eco2)|Eco[12]\.User|Dwgs\.User|Cmts\.User)$")
SILK = ("F.SilkS", "B.SilkS")


def blocks(text, start=0, end=None):
    """(kind, start, end) of each child list of the list that opens at text[start]; end exclusive."""
    end = len(text) if end is None else end
    out, depth, i, child = [], 0, start, None
    while i < end:
        ch = text[i]
        if ch == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "(":
            depth += 1
            if depth == 2:
                child = i
        elif ch == ")":
            if depth == 2:
                m = re.match(r"\(([^\s()\"]+)", text[child:child + 64])
                out.append((m.group(1) if m else "", child, i + 1))
            depth -= 1
            if depth == 0:
                break
        i += 1
    return out


def to_board(fx, fy, rot, dx, dy):
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    return fx + dx * c + dy * s, fy - dx * s + dy * c


def to_local(fx, fy, rot, bx, by):
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    x, y = bx - fx, by - fy
    return x * c - y * s, x * s + y * c


def grow(b, d):
    return (b[0] - d, b[1] - d, b[2] + d, b[3] + d)


def hits(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def gap(a, b):
    """Euclidean distance between two boxes, 0 when they touch or overlap."""
    return math.hypot(max(0.0, b[0] - a[2], a[0] - b[2]), max(0.0, b[1] - a[3], a[1] - b[3]))


def union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def text_span(s, size, thick):
    """(u0, u1, v0, v1): ink of a centre-justified one-line text in KiCad's stroke font, u along the text from
    its anchor, v down from it, at angle 0."""
    g = [GLYPHS.get(c, GLYPH_DEFAULT) for c in s] or [GLYPH_DEFAULT]
    half = sum(a for a, *_ in g) / 2
    u0 = (g[0][1] - GLYPH_ORIGIN - half) * size
    u1 = (sum(a for a, *_ in g[:-1]) + g[-1][2] - GLYPH_ORIGIN - half) * size
    v0, v1 = -max(x[3] for x in g) * size, max(x[4] for x in g) * size
    e = thick / 2 + TEXT_MARGIN
    return u0 - e, u1 + e, v0 - e, v1 + e


def text_extent(s, size, thick):
    u0, u1, v0, v1 = text_span(s, size, thick)
    return u1 - u0, v1 - v0


def _place(cx, cy, ang, u0, u1, v0, v1):
    a = round(ang) % 360
    if a == 90:
        return (cx + v0, cy - u1, cx + v1, cy - u0)
    if a == 180:
        return (cx - u1, cy - v1, cx - u0, cy - v0)
    if a == 270:
        return (cx - v1, cy + u0, cx - v0, cy + u1)
    return (cx + u0, cy + v0, cx + u1, cy + v1)


def text_box(cx, cy, s, size, thick, ang=0):
    return _place(cx, cy, ang, *text_span(s, size, thick))


def glyph_boxes(cx, cy, s, size, thick, ang=0):
    """One box per character: closer to KiCad's stroke-level clearance than the text's box."""
    g = [GLYPHS.get(c, GLYPH_DEFAULT) for c in s] or [GLYPH_DEFAULT]
    x = -sum(a for a, *_ in g) / 2 - GLYPH_ORIGIN
    e = thick / 2 + TEXT_MARGIN
    out = []
    for adv, left, right, up, down in g:
        out.append(_place(cx, cy, ang, (x + left) * size - e, (x + right) * size + e, -up * size - e, down * size + e))
        x += adv
    return out


def _f(node, key, n=2):
    c = PR.child(node, key)
    return [float(v) for v in c[1:1 + n] if not isinstance(v, list)] if c else None


def parse(text):
    """Footprints with what placement needs, and the board's outline box."""
    root = PR.parse_sexpr(text)
    fps = []
    for fp in PR.children(root, "footprint"):
        at = PR.child(fp, "at")
        fx, fy = float(at[1]), float(at[2])
        rot = float(at[3]) if len(at) > 3 else 0.0
        side = "B" if (PR.child(fp, "layer") or [None, "F.Cu"])[1] == "B.Cu" else "F"
        ref, ref_size, ref_thick, ref_at, ref_hidden, ref_layer = "", None, None, None, False, None
        silk_texts = []
        for p in PR.children(fp, "property") + PR.children(fp, "fp_text"):
            layer = (PR.child(p, "layer") or [None, ""])[1]
            hidden = bool(PR.child(p, "hide")) and PR.child(p, "hide")[1:2] != ["no"]
            eff = PR.child(p, "effects")
            if eff and PR.child(eff, "hide"):
                hidden = True
            font = PR.child(eff, "font") if eff else None
            size = _f(font, "size") if font else None
            thick = _f(font, "thickness", 1) if font else None
            if p[0] == "property" and p[1] == "Reference":
                ref, ref_at, ref_hidden, ref_layer = p[2], _f(p, "at", 3), hidden, layer
                ref_size, ref_thick = (size[1] if size else 1.0), (thick[0] if thick else 0.15)
            elif layer in SILK and not hidden:
                silk_texts.append(p[2])
        pads = []
        for pad in PR.children(fp, "pad"):
            pa = PR.child(pad, "at")
            px, py = float(pa[1]), float(pa[2])
            pang = float(pa[3]) if len(pa) > 3 else 0.0
            sz = _f(pad, "size") or [0.0, 0.0]
            x, y = to_board(fx, fy, rot, px, py)
            w, h = sz
            if round(pang) % 180 == 90:
                w, h = h, w
            elif round(pang) % 90:
                w = h = max(w, h)
            pads.append((x - w / 2, y - h / 2, x + w / 2, y + h / 2))
        lines, court = [], []
        for g in fp:
            if not (isinstance(g, list) and g and str(g[0]).startswith("fp_") and g[0] != "fp_text"):
                continue
            layer = (PR.child(g, "layer") or [None, ""])[1]
            pts = []
            for k in ("start", "end", "mid", "center"):
                c = PR.child(g, k)
                if c:
                    pts.append(to_board(fx, fy, rot, float(c[1]), float(c[2])))
            ptsn = PR.child(g, "pts")
            for q in (ptsn[1:] if ptsn else []):
                if q[0] == "xy":
                    pts.append(to_board(fx, fy, rot, float(q[1]), float(q[2])))
            if g[0] == "fp_circle" and PR.child(g, "center") and PR.child(g, "end"):
                cx, cy = to_board(fx, fy, rot, *[float(v) for v in PR.child(g, "center")[1:3]])
                ex, ey = to_board(fx, fy, rot, *[float(v) for v in PR.child(g, "end")[1:3]])
                r = math.hypot(ex - cx, ey - cy)
                pts += [(cx - r, cy - r), (cx + r, cy + r)]
            if not pts:
                continue
            stroke = PR.child(g, "stroke")
            sw = float(PR.child(stroke, "width")[1]) if stroke and PR.child(stroke, "width") else 0.12
            b = grow((min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)),
                     sw / 2)
            if layer in SILK and layer[0] == side:
                lines.append(b)
            elif layer in ("F.CrtYd", "B.CrtYd") and layer[0] == side:
                court.append(b)
        body = union(court) if court else (union(pads) if pads else (fx - 0.5, fy - 0.5, fx + 0.5, fy + 0.5))
        fps.append(dict(ref=ref, x=fx, y=fy, rot=rot, side=side, pads=pads, lines=lines, body=body,
                        ref_at=ref_at, ref_size=ref_size, ref_thick=ref_thick, ref_hidden=ref_hidden,
                        ref_layer=ref_layer, silk_texts=silk_texts))
    edge = []
    for g in root:
        if isinstance(g, list) and g and str(g[0]).startswith("gr_") and (PR.child(g, "layer") or [None, ""])[1] == "Edge.Cuts":
            for k in ("start", "end", "mid", "center"):
                c = PR.child(g, k)
                if c:
                    edge.append((float(c[1]), float(c[2])))
    board = (min(p[0] for p in edge), min(p[1] for p in edge), max(p[0] for p in edge), max(p[1] for p in edge)) \
        if edge else None
    return fps, board


def candidates(body, w, h, gap):
    """Text centres around a part's body: above, below, right, left, then the corners, then further out."""
    x0, y0, x1, y1 = body
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for d in (gap, gap + 0.4, gap + 0.9, gap + 1.5, gap + 2.2, gap + 3.0, gap + 4.0, gap + 5.0, gap + 6.0):
        yield cx, y0 - d - h / 2
        yield cx, y1 + d + h / 2
        yield x1 + d + w / 2, cy
        yield x0 - d - w / 2, cy
        for sx in (-1, 1):
            for sy in (-1, 1):
                yield (cx + sx * ((x1 - x0) / 2 + d + w / 2), cy + sy * ((y1 - y0) / 2 + d + h / 2))


def place_all(fps, board, size, thick, to_pad):
    """{ref: (x, y)} board positions for the references, and the refs that found no clear spot."""
    pads = [(f["ref"], f["side"], grow(p, to_pad)) for f in fps for p in f["pads"]]
    lines = [(f["ref"], f["side"], grow(b, SILK_CLEAR + 0.02)) for f in fps for b in f["lines"]]
    placed, result, failed = [], {}, []
    inner = grow(board, -0.3) if board else None
    order = sorted((f for f in fps if f["ref"] and not f["ref"].startswith("#")),
                   key=lambda f: -(f["body"][2] - f["body"][0]) * (f["body"][3] - f["body"][1]))
    for f in order:
        w, h = text_extent(f["ref"], size, thick)
        others = [(f2["side"], f2["body"]) for f2 in fps if f2 is not f]
        best = None
        tries = [(strict, ang, c) for strict in (True, False) for ang in (0, 90)
                 for c in candidates(f["body"], w if ang == 0 else h, h if ang == 0 else w, 0.25)]
        for strict, ang, (cx, cy) in tries:
            if True:
                tb = text_box(cx, cy, f["ref"], size, thick, ang)
                if inner and not (inner[0] <= tb[0] and tb[2] <= inner[2] and inner[1] <= tb[1] and tb[3] <= inner[3]):
                    continue
                if any(side == f["side"] and hits(tb, b) for _, side, b in pads):
                    continue
                if any(side == f["side"] and hits(tb, b) for _, side, b in lines):
                    continue
                if any(side == f["side"] and hits(tb, grow(b, SILK_CLEAR + 0.05)) for side, b in placed):
                    continue
                if strict and any(side == f["side"] and hits(tb, b) for side, b in others):
                    continue
                best = (cx, cy, ang, tb)
                break
        if best is None:
            failed.append(f["ref"])
            continue
        placed.append((f["side"], best[3]))
        result[f["ref"]] = best[:3]
    return result, failed


def _num(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


def edit_property(block, size, thick, at=None, hide=None, layer=None):
    """A footprint property / fp_text block with its position, font, visibility or layer changed."""
    edits = []
    kids = blocks(block)
    for kind, s, e in kids:
        if kind == "at" and at is not None:
            edits.append((s, e, f"(at {_num(at[0])} {_num(at[1])} {_num(at[2])})"))
        elif kind == "layer" and layer is not None:
            edits.append((s, e, f'(layer "{layer}")'))
        elif kind == "hide" and hide is not None:
            edits.append((s, e, f"(hide {'yes' if hide else 'no'})"))
        elif kind == "effects" and (size is not None or hide is not None):
            eff = block[s:e]
            if size is not None:
                eff = re.sub(r"\(size [\d.]+ [\d.]+\)", f"(size {_num(size)} {_num(size)})", eff)
                eff = re.sub(r"\(thickness [\d.]+\)", f"(thickness {_num(thick)})", eff)
            if hide is not None:
                eff = re.sub(r"\s*\(hide (yes|no)\)", "", eff)
            edits.append((s, e, eff))
    if hide is not None and not any(k == "hide" for k, _, _ in kids):
        first = kids[0][1]
        indent = block[block.rfind("\n", 0, first):first]
        edits.append((first, first, f"(hide {'yes' if hide else 'no'})" + indent))
    out, pos = [], 0
    for s, e, rep in sorted(edits):
        out.append(block[pos:s])
        out.append(rep)
        pos = e
    out.append(block[pos:])
    return "".join(out)


def apply(text, size, thick, to_pad, keep_layers=()):
    fps, board = parse(text)
    pos, failed = place_all(fps, board, size, thick, to_pad)
    by_ref = {f["ref"]: f for f in fps}
    edits = []
    for kind, s, e in blocks(text):
        if kind != "footprint":
            continue
        fpb = text[s:e]
        m = re.search(r'\(property "Reference" "((?:[^"\\]|\\.)*)"', fpb)
        f = by_ref.get(m.group(1)) if m else None
        if f is None:
            continue
        sub = []
        for k2, s2, e2 in blocks(fpb):
            part = fpb[s2:e2]
            if k2 == "property" and part.startswith('(property "Reference"'):
                layer = "B.SilkS" if f["side"] == "B" else "F.SilkS"
                at = None
                if f["ref"] in pos:
                    bx, by, ang = pos[f["ref"]]
                    lx, ly = to_local(f["x"], f["y"], f["rot"], bx, by)
                    at = (lx, ly, ang)
                sub.append((s2, e2, edit_property(part, size, thick, at=at, hide=False, layer=layer)))
            elif k2 == "property" and part.startswith('(property "Value"'):
                sub.append((s2, e2, edit_property(part, None, None, hide=True)))
            elif k2 == "fp_text" or (k2 == "property" and re.search(r'\(layer "[FB]\.SilkS"\)', part)):
                sub.append((s2, e2, edit_property(part, None, None, hide=True)))
        out, p0 = [], 0
        for a, b, rep in sorted(sub):
            out.append(fpb[p0:a])
            out.append(rep)
            p0 = b
        out.append(fpb[p0:])
        edits.append((s, e, "".join(out)))
    out, p0 = [], 0
    for a, b, rep in sorted(edits):
        out.append(text[p0:a])
        out.append(rep)
        p0 = b
    out.append(text[p0:])
    text = "".join(out)
    removed = []
    m = re.search(r"\n\t\(layers\n(.*?)\n\t\)", text, re.S)
    if m:
        keep = []
        for line in m.group(1).split("\n"):
            name = re.search(r'\(\d+ "([^"]+)"', line)
            nm = name.group(1) if name else ""
            used = text.count(f'"{nm}"') > 1
            if nm and OPTIONAL_LAYERS.match(nm) and not used and nm not in keep_layers:
                removed.append(nm)
                continue
            keep.append(line)
        text = text[:m.start(1)] + "\n".join(keep) + text[m.end(1):]
    return text, pos, failed, removed


def check(text, size, thick, to_pad):
    fps, board = parse(text)
    rows = {k: [] for k in ("other_silk_text", "refs_hidden", "refs_small", "refs_on_pads", "refs_on_lines",
                            "refs_overlapping", "refs_outside")}
    boxes = []
    for f in fps:
        if not f["ref"] or f["ref"].startswith("#"):
            continue
        for s in f["silk_texts"]:
            rows["other_silk_text"].append(f"{f['ref']}: '{s}'")
        if f["ref_hidden"] or f["ref_layer"] not in SILK:
            rows["refs_hidden"].append(f["ref"])
            continue
        if f["ref_size"] < size - 1e-6 or f["ref_thick"] < thick - 1e-6:
            rows["refs_small"].append(f"{f['ref']} {f['ref_size']} / {f['ref_thick']} mm")
        cx, cy = to_board(f["x"], f["y"], f["rot"], f["ref_at"][0], f["ref_at"][1])
        tb = text_box(cx, cy, f["ref"], f["ref_size"], f["ref_thick"], f["ref_at"][2] if len(f["ref_at"]) > 2 else 0)
        boxes.append((f, tb, glyph_boxes(cx, cy, f["ref"], f["ref_size"], f["ref_thick"],
                                         f["ref_at"][2] if len(f["ref_at"]) > 2 else 0)))
    for f, tb, gb in boxes:
        if board and not (board[0] <= tb[0] and tb[2] <= board[2] and board[1] <= tb[1] and tb[3] <= board[3]):
            rows["refs_outside"].append(f["ref"])
        if any(f2["side"] == f["side"] and hits(tb, grow(p, to_pad - 0.02)) for f2 in fps for p in f2["pads"]):
            rows["refs_on_pads"].append(f["ref"])
        if any(f2["side"] == f["side"] and gap(g, b) < SILK_CLEAR for f2 in fps for b in f2["lines"] for g in gb):
            rows["refs_on_lines"].append(f["ref"])
    for i, (f, _, ga) in enumerate(boxes):
        for g, _, gb in boxes[i + 1:]:
            if f["side"] == g["side"] and min(gap(a, b) for a in ga for b in gb) < SILK_CLEAR:
                rows["refs_overlapping"].append(f"{f['ref']} / {g['ref']}")
    return rows


def fab_silk(fabs, board_path):
    layers = len(PR.Board(board_path).copper_layers)
    fab_min, _, _ = PR.combined_rules(fabs, layers)
    return fab_min.get("silk_text_height", 1.0), fab_min.get("silk_line", 0.15), fab_min.get("silk_to_pad", 0.15)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("apply", "check"):
        p = sub.add_parser(name)
        p.add_argument("board")
        p.add_argument("--fab", help="fab profile(s) for the silkscreen minimums (default: the ones pcb_rules apply "
                                     "recorded, else jlcpcb)")
        if name == "apply":
            p.add_argument("--keep-layers", default="", help="optional layers to keep even when unused")
        else:
            p.add_argument("--report")
            p.add_argument("--json")
    a = ap.parse_args(argv)
    dru = os.path.splitext(a.board)[0] + ".kicad_dru"
    fabs = a.fab.split(",") if a.fab else (PR.managed_fabs(dru) or ["jlcpcb"])
    size, thick, to_pad = fab_silk(fabs, a.board)
    with open(a.board, encoding="utf-8") as f:
        text = f.read()
    if a.cmd == "apply":
        text, pos, failed, removed = apply(text, size, thick, to_pad, set(a.keep_layers.split(",")) - {""})
        with open(a.board, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"silkscreen on {os.path.basename(a.board)} ({'+'.join(fabs)}: text {size} mm, stroke {thick} mm, "
              f"{to_pad} mm to pads): {len(pos)} references placed, values and other silk text hidden")
        if removed:
            print("  unused optional layers removed: " + ", ".join(removed))
        if failed:
            print("  no clear spot (left where they were, move by hand): " + ", ".join(failed))
        return 0
    rows = check(text, size, thick, to_pad)
    lines = [f"# Silkscreen check: {os.path.basename(a.board)}", "",
             f"References only, at least {size} mm high and {thick} mm stroke, {to_pad} mm from pads "
             f"({'+'.join(fabs)}).", "", "| Gate | Count |", "|---|---|"]
    lines += [f"| {k} | {len(v)} |" for k, v in rows.items()]
    for k, v in rows.items():
        if v:
            lines += ["", f"**{k}**: " + ", ".join(v[:30]) + (" ..." if len(v) > 30 else "")]
    fail = any(rows.values())
    lines += ["", f"**{'FAIL' if fail else 'PASS'}**"]
    report = "\n".join(lines) + "\n"
    print(report)
    if a.report:
        with open(a.report, "w") as f:
            f.write(report)
    if a.json:
        with open(a.json, "w") as f:
            json.dump({k: v for k, v in rows.items()}, f, indent=1)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
