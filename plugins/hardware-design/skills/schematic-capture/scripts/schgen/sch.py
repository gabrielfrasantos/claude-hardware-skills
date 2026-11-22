"""Generate the KiCad 10 hierarchical schematic from Python sheet descriptions.

Part of the schematic-capture skill (hardware-design-skills). Generalised from the schgen of earlier board repos;
board-specific settings (power symbols, company, libraries) are
parameters. Each sheet is drawn as titled boxes of wired
circuits: `rail` / `vrail` join pins with a bus wire, `link` wires pin to pin, `path` draws a polyline, and `net`
puts a short stub with a label (local or global) or a power symbol on a pin. Every connection is recorded, so
`expected.json` states the intended netlist and `check.py` compares KiCad's export with it.

Differences from the original schgen:
  - KiCad 10 file format, our symbol loader (`library.py`) and the project library;
  - deterministic UUIDs (uuid5), so a rebuild is byte-identical and CI can diff it;
  - every named net carries at least one label, so net names (and the PCB's nets) do not depend on the drawing;
  - every pin must be connected or marked no-connect (`Project.problems`).
"""

import json
import math
import re
import uuid

from library import load
from sexpr import Str, Sym, dump, find, find_all

VERSION, GENERATOR_VERSION = 20260306, "10.0"
GRID = 1.27
STUB = 2.54
FONT = 1.27
NAMESPACE = uuid.UUID("6b7d1c38-0d55-4c4c-9a77-3f0a1e5e2b11")

# Defaults for Project(power_symbols=..., power_natural=...): net name -> KiCad power symbol, and the direction a
# power symbol's pin points (ground symbols point down).
POWER_SYMS = {"GND": "power:GND", "+3V3": "power:+3V3", "+5V": "power:+5V", "VBAT": "power:VCC",
              "VDDA": "power:VDDA"}
POWER_NATURAL = {"GND": (0, 1)}


def uid(*parts):
    return Str(str(uuid.uuid5(NAMESPACE, "/".join(map(str, parts)))))


TEXT_W = 0.9
TEXT_GAP = 0.3
PAPER = {"A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0)}


def text_box(x, y, s, size, ang, justify, bottom, width=None):
    """Approximate (x0, y0, x1, y1) of a one-line text: anchored at (x, y), justified left / right / centred,
    vertically centred unless `bottom` (a label sits on its anchor). ang 90 runs bottom to top. `size` is the
    box height; `width` the font size the characters are measured with (default `size`)."""
    w, h = len(s) * (width or size) * TEXT_W, size
    j = "left" if "left" in justify else "right" if "right" in justify else "center"
    a0 = 0 if j == "left" else -w if j == "right" else -w / 2
    c0, c1 = (-h, 0) if bottom else (-h / 2, h / 2)
    if ang in (90, 270):
        return (x + c0, y - a0 - w, x + c1, y - a0)
    return (x + a0, y + c0, x + a0 + w, y + c1)


def overlap(a, b, gap=0.1):
    return a[0] < b[2] - gap and b[0] < a[2] - gap and a[1] < b[3] - gap and b[1] < a[3] - gap


def snap(v):
    return round(round(v / GRID) * GRID, 4)


def rot_vec(dx, dy, ang):
    a = math.radians(ang)
    return (dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a))


def r3(v):
    return round(v, 3)


def body_bbox(symbol, unit):
    """Body bounding box in library coordinates (Y up) from rectangles, polylines, circles, arcs and pin roots."""
    xs, ys = [], []
    for sub in find_all(symbol.node, "symbol"):
        u = int(sub[1].rsplit("_", 2)[-2])
        if u not in (0, unit):
            continue
        for g in sub[2:]:
            if not isinstance(g, list) or not g:
                continue
            if g[0] == "rectangle":
                for k in ("start", "end"):
                    p = find(g, k)
                    xs.append(float(p[1])); ys.append(float(p[2]))
            elif g[0] in ("polyline", "bezier"):
                for p in find_all(find(g, "pts"), "xy"):
                    xs.append(float(p[1])); ys.append(float(p[2]))
            elif g[0] == "circle":
                c, r = find(g, "center"), float(find(g, "radius")[1])
                xs += [float(c[1]) - r, float(c[1]) + r]; ys += [float(c[2]) - r, float(c[2]) + r]
            elif g[0] == "arc":
                for k in ("start", "mid", "end"):
                    p = find(g, k)
                    xs.append(float(p[1])); ys.append(float(p[2]))
            elif g[0] == "pin":
                at = find(g, "at")
                xs.append(float(at[1])); ys.append(float(at[2]))
    if not xs:
        return (-1.0, -1.0, 1.0, 1.0)
    return (min(xs), min(ys), max(xs), max(ys))


class PinRef:
    def __init__(self, part, number, x, y, out, info):
        self.part, self.number, self.x, self.y, self.out, self.info = part, number, x, y, out, info

    @property
    def pos(self):
        return (self.x, self.y)

    def __repr__(self):
        return f"{self.part.ref}.{self.number}"


class Part:
    def __init__(self, sheet, lib_id, ref, value, at, rot, unit, fields, dnp, in_bom=True, mirror=None):
        self.sheet, self.lib_id, self.ref, self.value = sheet, lib_id, ref, value
        self.x, self.y = snap(at[0]), snap(at[1])
        self.rot, self.unit, self.fields, self.dnp = rot % 360, unit, fields, dnp
        self.mirror = mirror
        assert mirror in (None, "x", "y")
        self.sym = load(lib_id)
        self.is_power = self.sym.is_power
        self.in_bom = in_bom and not self.is_power and not ref.startswith("#")
        self.on_board = not self.is_power and not ref.startswith("#")
        self.uuid = uid(sheet.name, ref, unit)
        self.fpos = None
        self.hide_value = False

    def _xf(self, x, y):
        rx, ry = rot_vec(x, y, self.rot)
        if self.mirror == "y":
            rx = -rx
        elif self.mirror == "x":
            ry = -ry
        return (round(self.x + rx, 4), round(self.y - ry, 4))

    def unit_pins(self):
        return [p for p in self.sym.pins if p.unit in (0, self.unit)]

    def pin(self, number):
        number = str(number)
        cands = [p for p in self.unit_pins() if p.number == number]
        if not cands:
            cands = [p for p in self.unit_pins() if p.name == number]
            if len(cands) != 1:
                raise KeyError(f"{self.ref}: pin {number} not found or ambiguous")
        p = cands[0]
        x, y = self._xf(p.x, p.y)
        a = math.radians(p.angle + 180)
        dx, dy = rot_vec(math.cos(a), math.sin(a), self.rot)
        if self.mirror == "y":
            dx = -dx
        elif self.mirror == "x":
            dy = -dy
        return PinRef(self, p.number, x, y, (round(dx), round(-dy)), p)

    def __getitem__(self, k):
        return self.pin(k)

    def screen_bbox(self):
        x0, y0, x1, y1 = body_bbox(self.sym, self.unit)
        pts = [self._xf(x, y) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))


class Sheet:
    def __init__(self, project, index, name, title, paper="A3"):
        self.project, self.index, self.name, self.title, self.paper = project, index, name, title, paper
        self.sheetname = f"{index} {title}"
        self.filename = f"{name}.kicad_sch"
        self.uuid = uid("sheet", name)
        self.parts, self.texts, self.rects, self.ncs = [], [], [], []
        self.conns = []
        self.rails, self.links, self.paths, self.labels = [], [], [], []
        self.desc = []
        self.netclasses = []
        self.class_box = None
        self.global_all = False
        project.sheets.append(self)

    def part(self, lib_id, ref, value, at, rot=0, unit=1, fp="", lcsc="", mpn="", dnp=False, in_bom=True,
             mirror=None, **fields):
        f = {"Footprint": fp, "Datasheet": "", "LCSC": lcsc, "MPN": mpn}
        f.update(fields)
        p = Part(self, lib_id, ref, value, at, rot, unit, f, dnp, in_bom, mirror)
        self.parts.append(p)
        return p

    def net(self, pinref, net, label=True):
        self.conns.append((pinref, net, label))
        return pinref

    def nets(self, part, mapping):
        for k, v in mapping.items():
            if v is None:
                self.nc(part[k])
            else:
                self.net(part[k], v)

    def link(self, a, b, net, via=None):
        """Wire pin a to pin b (straight or one corner). `via` forces the corner: 'h' or 'v' first."""
        self.links.append((a, b, net, via))
        self._wired(a, net)
        self._wired(b, net)

    def _same(self, c, pr):
        return c[0].part is pr.part and c[0].number == pr.number

    def _wired(self, pr, net):
        for c in self.conns:
            if self._same(c, pr) and c[1] != net:
                raise ValueError(f"{pr} wired to {net} but already on {c[1]}")
        self.conns = [c for c in self.conns if not self._same(c, pr)]
        self.conns.append((pr, net, False))
        for q in pr.part.unit_pins():
            if q.number != pr.number:
                o = pr.part.pin(q.number)
                if abs(o.x - pr.x) < 1e-3 and abs(o.y - pr.y) < 1e-3:
                    self.conns = [c for c in self.conns if not self._same(c, o)]
                    self.conns.append((o, net, False))

    def nc(self, pinref):
        self.ncs.append(pinref)

    def netclass(self, net, cls):
        """A net-class directive label for `net` (e.g. "PWR_4A", see the pcb-copper skill), placed on one of the
        net's label points on this sheet. KiCad resolves it to the net and writes the assignment into the project."""
        self.netclasses.append((net, cls))

    def class_table(self, x, y, rows=12, col_w=60.96, pitch=5.08, title="Net classes"):
        """Draw this sheet's net-class directives as a table at (x, y) instead of on the circuit's label points:
        one row per net, its label (or power symbol) wired to its class flag, `rows` rows per column. Keeps the
        class names off the circuit, where they overlap pins and labels."""
        self.class_box = (snap(x), snap(y), rows, col_w, pitch, title)

    def decided(self, part):
        """Pin numbers of `part` that already have a net or a no-connect on this sheet."""
        return ({c[0].number for c in self.conns if c[0].part is part} |
                {pr.number for pr in self.ncs if pr.part is part})

    def assign_pins(self, part, pinmap, functions=None):
        """Connect `part`'s pins to function nets from a pin map ({function: pad number}, e.g. load_pinmap()).
        `functions` limits it to these. Functions whose pin is still TBD (not in the map) are left out: they exist
        on the other side only, which is what pin assignment (pcb-placement pins.py) expects. NET~2 is the second
        pin of NET."""
        done = []
        for function, pad in pinmap.items():
            if functions is not None and function not in functions:
                continue
            self.net(part[pad], function.split("~", 1)[0])
            done.append(function)
        return done

    def nc_unused(self, part, names=None):
        """No-connect every pin of `part` not yet decided on this sheet (call it last). `names`, a regex, limits it
        to matching pin names, e.g. r"^P[A-Z][0-9]+$" for the I/O pins of an MCU."""
        rx = re.compile(names) if names else None
        taken = self.decided(part)
        for q in part.unit_pins():
            if q.number not in taken and q.kind != "no_connect" and (rx is None or rx.match(q.name)):
                self.nc(part[q.number])


    def label(self, net, at, out=(1, 0)):
        """Put the net's label at `at`, which must lie on a wire of that net drawn on this sheet."""
        self.labels.append((net, snap(at[0]), snap(at[1]), out))

    def rail(self, net, y, pins, label=None, ext=2.54, tap=None):
        """Horizontal wire at y joining `pins` (vertical drops from pins off the rail). label 'left' / 'right'
        ends the rail in a label or power symbol; tap=(x, (dx, dy)) puts one on a stub leaving the rail at x."""
        y = snap(y)
        for pr in pins:
            if isinstance(pr, PinRef):
                self._wired(pr, net)
        self.rails.append((net, "h", y, list(pins), label, ext, tap))

    def vrail(self, net, x, pins, label=None, ext=2.54, tap=None):
        """Vertical wire at x joining `pins` (horizontal drops). label 'top' / 'bottom'; tap=(y, (dx, dy))."""
        x = snap(x)
        for pr in pins:
            if isinstance(pr, PinRef):
                self._wired(pr, net)
        self.rails.append((net, "v", x, list(pins), label, ext, tap))

    def path(self, net, items):
        """Polyline through PinRefs and (x, y) points; every corner must be given."""
        for it in items:
            if isinstance(it, PinRef):
                self._wired(it, net)
        self.paths.append((net, list(items)))

    def flag(self, net, at, label=True):
        """PWR_FLAG on `net` (marks it driven for ERC). label=False: the caller wires it."""
        self.project.flag_count += 1
        f = self.part("power:PWR_FLAG", "#FLG%03d" % self.project.flag_count, "PWR_FLAG", at)
        f.fields = {"Footprint": "", "Datasheet": ""}
        if label:
            self.net(f["1"], net)
        return f

    def text(self, s, at, size=FONT, bold=False):
        self.texts.append((s, snap(at[0]), snap(at[1]), size, bold))

    def note(self, x, y_top, lines, size=FONT):
        """Multi-line design note whose first line starts at y_top (KiCad anchors the block at its last line)."""
        self.text("\n".join(lines), (x, y_top + size + (len(lines) - 1) * size * 1.65), size=size)

    def box(self, x0, y0, x1, y1, title=None):
        self.rects.append((snap(x0), snap(y0), snap(x1), snap(y1)))
        if title:
            self.text(title, (x0 + 1.27, y0 + 3.81), size=1.8, bold=True)


class Project:
    def __init__(self, name, title, date, rev="A", company="", comments=(), power_symbols=None, power_natural=None):
        self.name, self.title, self.date, self.rev, self.company = name, title, date, rev, company
        self.power_syms = dict(POWER_SYMS if power_symbols is None else power_symbols)
        self.power_natural = dict(POWER_NATURAL if power_natural is None else power_natural)
        self.comments = list(comments)
        self.sheets = []
        self.root_uuid = uid("root")
        self.expected = {}
        self.lint = []
        self.flag_count = 0
        self.pwr_count = 0
        self._tb, self._owner, self._owner_rot = None, None, 0

    def problems(self):
        out, refs = [], {}
        for sh in self.sheets:
            decided = {(c[0].part.ref, c[0].part.unit, c[0].number) for c in sh.conns}
            decided |= {(pr.part.ref, pr.part.unit, pr.number) for pr in sh.ncs}
            for p in sh.parts:
                if p.is_power:
                    continue
                key = (p.ref, p.unit)
                if key in refs:
                    out.append(f"duplicate reference {p.ref} unit {p.unit}")
                refs[key] = sh.name
                for q in p.unit_pins():
                    if q.kind != "no_connect" and (p.ref, p.unit, q.number) not in decided:
                        out.append(f"{sh.name}: {p.ref}.{q.number} ({q.name}) has no net and no no-connect")
        return out

    def net_name(self, sh, net):
        return net if (net in self.global_nets or net in self.power_syms) else f"/{sh.sheetname}/{net}"

    def build(self, outdir, root_texts=()):
        outdir.mkdir(parents=True, exist_ok=True)
        use = {}
        for sh in self.sheets:
            for pr, n, _ in sh.conns:
                use.setdefault(n, set()).add(sh.name)
        self.global_nets = {n for n, s in use.items() if len(s) > 1 and n not in self.power_syms}
        for sh in self.sheets:
            if sh.global_all:
                self.global_nets |= {n for pr, n, _ in sh.conns if n not in self.power_syms}
        for sh in self.sheets:
            for pr, n, _ in sh.conns:
                if not pr.part.ref.startswith("#"):
                    self.expected.setdefault(self.net_name(sh, n), set()).add((pr.part.ref, pr.number))
        for i, sh in enumerate(self.sheets):
            sh.page = str(i + 2)
            tree = self._sheet_tree(sh)
            (outdir / sh.filename).write_text(dump(tree) + "\n", encoding="utf-8")
        (outdir / f"{self.name}.kicad_sch").write_text(dump(self._root_tree(root_texts)) + "\n", encoding="utf-8")

    def expected_json(self):
        return json.dumps({k: sorted(map(list, v)) for k, v in sorted(self.expected.items())}, indent=0) + "\n"

    def _title_block(self, title, comments):
        tb = [Sym("title_block"), [Sym("title"), Str(title)], [Sym("date"), Str(self.date)],
              [Sym("rev"), Str(self.rev)], [Sym("company"), Str(self.company)]]
        for i, c in enumerate(comments):
            tb.append([Sym("comment"), i + 1, Str(c)])
        return tb

    @staticmethod
    def _effects(size=FONT, justify=None, hide=False, bold=False):
        font = [Sym("font"), [Sym("size"), size, size]]
        if bold:
            font.append([Sym("bold"), True])
        e = [Sym("effects"), font]
        if justify:
            e.append([Sym("justify")] + [Sym(j) for j in justify.split()])
        if hide:
            e.append([Sym("hide"), True])
        return e

    def _prop(self, key, val, x, y, ang=0, justify=None, hide=False):
        if not hide and self._tb is not None:
            screen = (ang - self._owner_rot) % 180
            j = justify or ""
            if (ang + self._owner_rot) % 360 == 180:
                j = j.replace("left", "@").replace("right", "left").replace("@", "right")
            self._tb.append((text_box(x, y, val, FONT, 90 if screen else 0, j, False), self._owner, val))
        return [Sym("property"), Str(key), Str(val), [Sym("at"), r3(x), r3(y), ang],
                self._effects(FONT, justify, hide)]

    def _symbol_inst(self, sh, p):
        self._owner, self._owner_rot = p.ref, p.rot
        node = [Sym("symbol"), [Sym("lib_id"), Str(p.lib_id)], [Sym("at"), p.x, p.y, p.rot]]
        if p.mirror:
            node.append([Sym("mirror"), Sym(p.mirror)])
        node += [[Sym("unit"), p.unit], [Sym("exclude_from_sim"), False], [Sym("in_bom"), p.in_bom],
                 [Sym("on_board"), p.on_board], [Sym("dnp"), p.dnp], [Sym("uuid"), p.uuid]]
        bx0, by0, bx1, by1 = p.screen_bbox()
        npins = len(p.unit_pins())
        fa = 90 if p.rot in (90, 270) else 0
        if p.fpos and not p.is_power:
            dx, dy, jj = p.fpos
            if (p.rot + fa) % 360 == 180:
                jj = {"left": "right", "right": "left"}.get(jj, jj)
            node.append(self._prop("Reference", p.ref, p.x + dx, p.y + dy, fa, jj))
            node.append(self._prop("Value", p.value, p.x + dx, p.y + dy + 2.54, fa, jj, hide=p.hide_value))
        elif p.is_power:
            o = (0, 1) if p.value.startswith("GND") else (0, -1)
            rx, ry = rot_vec(o[0], -o[1], p.rot)
            o = (round(rx), round(-ry))
            vx, vy = p.x + o[0] * 3.81, p.y + o[1] * 3.81
            if o[0] != 0:
                vx, vy = p.x + o[0] * 4.6, p.y
            node.append(self._prop("Reference", p.ref, p.x, p.y, fa, hide=True))
            node.append(self._prop("Value", p.value, vx, vy, fa))
        elif npins <= 3 and (bx1 - bx0) < (by1 - by0) and (bx1 - bx0) <= 5.2:
            xr = snap(bx1 + 1.27)
            j = "left" if (p.rot + fa) % 360 == 0 else "right"
            node.append(self._prop("Reference", p.ref, xr, p.y - 1.27, fa, j))
            node.append(self._prop("Value", p.value, xr, p.y + 1.27, fa, j, hide=p.hide_value))
        elif npins <= 3 and (by1 - by0) <= 5.2:
            node.append(self._prop("Reference", p.ref, p.x, by0 - 1.27, fa))
            node.append(self._prop("Value", p.value, p.x, by1 + 2.2, fa, hide=p.hide_value))
        elif p.rot != 0:
            cx = (bx0 + bx1) / 2
            node.append(self._prop("Reference", p.ref, cx, by0 - 1.9, fa))
            node.append(self._prop("Value", p.value, cx, by1 + 2.5, fa, hide=p.hide_value))
        else:
            pins = [p.pin(q.number) for q in p.unit_pins()]
            top = any(q.out == (0, -1) for q in pins)
            bottom = any(q.out == (0, 1) for q in pins)
            if bottom and not top:
                node.append(self._prop("Reference", p.ref, bx0, by0 - 3.81, 0, "left"))
                node.append(self._prop("Value", p.value, bx0, by0 - 1.27, 0, "left", hide=p.hide_value))
            elif top and not bottom:
                node.append(self._prop("Reference", p.ref, bx0, by1 + 1.9, 0, "left"))
                node.append(self._prop("Value", p.value, bx0, by1 + 4.45, 0, "left", hide=p.hide_value))
            else:
                node.append(self._prop("Reference", p.ref, bx0, by0 - 1.27, 0, "left"))
                node.append(self._prop("Value", p.value, bx0, by1 + 1.9, 0, "left", hide=p.hide_value))
        for k, v in p.fields.items():
            node.append(self._prop(k, v, p.x, p.y, 0, hide=True))
        for number in dict.fromkeys(q.number for q in p.sym.pins):
            node.append([Sym("pin"), Str(number), [Sym("uuid"), uid(sh.name, p.ref, "pin", number, p.unit)]])
        node.append([Sym("instances"), [Sym("project"), Str(self.name),
                     [Sym("path"), Str(f"/{self.root_uuid}/{sh.uuid}"), [Sym("reference"), Str(p.ref)],
                      [Sym("unit"), p.unit]]]])
        return node

    def _text_lint(self, sh, bboxes):
        """Report text that overlaps other text or another part's body: references, values, labels, notes."""
        tb = self._tb
        w, h = PAPER.get(sh.paper, (420.0, 297.0))
        for a, oa, sa in tb:
            if a[0] < 10 or a[1] < 10 or a[2] > w - 10 or a[3] > h - 10:
                self.lint.append(f"{sh.name}: text '{sa}' runs past the sheet border")
        for i, (a, oa, sa) in enumerate(tb):
            for b, ob, sb in tb[i + 1:]:
                labels = isinstance(oa, tuple) and isinstance(ob, tuple) and oa[0] == ob[0] == "label"
                if oa != ob and overlap(a, b, 0.0 if labels else -TEXT_GAP):
                    self.lint.append(f"{sh.name}: text '{sa}' overlaps '{sb}'")
            for part, body in bboxes:
                if part.ref != oa and overlap(a, body, -TEXT_GAP):
                    self.lint.append(f"{sh.name}: text '{sa}' overlaps {part.ref}")
                    continue
                for q in ([] if str(oa).startswith("#") else part.unit_pins()):
                    pr = part.pin(q.number)
                    x0, y0 = pr.x - pr.out[0] * 2.54, pr.y - pr.out[1] * 2.54
                    pin = (min(pr.x, x0) - 0.8, min(pr.y, y0) - 0.8, max(pr.x, x0) + 0.8, max(pr.y, y0) + 0.8)
                    if overlap(a, pin, 0.1):
                        self.lint.append(f"{sh.name}: text '{sa}' overlaps pin {part.ref}.{q.number}")
                        break

    def _box_lint(self, name, rects, bboxes):
        """Report a block outline that runs through a part's body or a text."""
        items = [(body, part.ref) for part, body in bboxes if not part.ref.startswith("#")]
        items += [(b, f"text '{t}'") for b, _, t in self._tb]
        for r in rects:
            for b, what in items:
                inside = r[0] <= b[0] and r[1] <= b[1] and b[2] <= r[2] and b[3] <= r[3]
                if overlap(r, b, 0.0) and not inside:
                    self.lint.append(f"{name}: box outline at ({r[0]:g}, {r[1]:g}) crosses {what}")

    def _root_lint(self, sheet_rects, texts):
        """Root page: notes against the sheet symbols, each other and the border."""
        w, h = PAPER["A3"]
        boxes = [(b, f"sheet {n}") for b, n in sheet_rects]
        for s, x, y, size, bold in texts:
            lines = s.split("\n")
            tw = max(len(ln) for ln in lines) * size * TEXT_W
            boxes.append(((x, y - len(lines) * size * 1.65, x + tw, y), f"text '{lines[0]}'"))
        for i, (a, na) in enumerate(boxes):
            if a[0] < 10 or a[1] < 10 or a[2] > w - 10 or a[3] > h - 10:
                self.lint.append(f"root: {na} runs past the sheet border")
            for b, nb in boxes[i + 1:]:
                if overlap(a, b, -TEXT_GAP):
                    self.lint.append(f"root: {na} overlaps {nb}")

    def _power_part(self, sh, net, x, y, out):
        lib_id = self.power_syms[net]
        natural = self.power_natural.get(net, (0, -1))
        ang_nat = math.degrees(math.atan2(-natural[1], natural[0]))
        ang_out = math.degrees(math.atan2(-out[1], out[0]))
        rot = round(ang_out - ang_nat) % 360
        self.pwr_count += 1
        return Part(sh, lib_id, "#PWR%04d" % self.pwr_count, net, (x, y), rot, 1,
                    {"Footprint": "", "Datasheet": ""}, False)

    def _sheet_tree(self, sh):
        self._tb, self._owner, self._owner_rot = [], None, 0
        counter = [0]

        def nid(kind):
            counter[0] += 1
            return uid(sh.name, kind, counter[0])

        items, extra_parts = [], []
        segs, seg_net = [], []
        pin_pts, bboxes = [], []
        label_pts = []
        for p in sh.parts:
            bboxes.append((p, p.screen_bbox()))
            for q in p.unit_pins():
                pr = p.pin(q.number)
                pin_pts.append((r3(pr.x), r3(pr.y)))
        pinset = set(pin_pts)

        def seg(p1, p2, net):
            p1, p2 = (r3(p1[0]), r3(p1[1])), (r3(p2[0]), r3(p2[1]))
            if p1 != p2:
                segs.append(p1 + p2)
                seg_net.append(net)

        def put_label(net, x, y, out):
            x, y = r3(x), r3(y)
            label_pts.append((net, x, y))
            if net not in self.power_syms:
                ang_ = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[out]
                glob = net in self.global_nets
                gl = 1.27 if glob else 0.0
                bx = text_box(x + out[0] * gl, y + out[1] * gl, (net + "  ") if glob else net,
                              FONT * 1.5 if glob else FONT * 1.2, 90 if ang_ in (90, 270) else 0,
                              "left" if ang_ in (0, 90) else "right", not glob, width=FONT)
                self._tb.append((bx, ("label", net, x, y), net))
            if net in self.power_syms:
                extra_parts.append(self._power_part(sh, net, x, y, out))
                return
            ang = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[out]
            if net in self.global_nets:
                just = "left" if ang in (0, 90) else "right"
                items.append([Sym("global_label"), Str(net), [Sym("shape"), Sym("bidirectional")],
                              [Sym("at"), x, y, ang], [Sym("fields_autoplaced"), True],
                              self._effects(FONT, just), [Sym("uuid"), nid("glabel")],
                              [Sym("property"), Str("Intersheetrefs"), Str("${INTERSHEET_REFS}"),
                               [Sym("at"), x, y, 0], self._effects(FONT, None, hide=True)]])
            else:
                just = ("left" if ang in (0, 90) else "right") + " bottom"
                items.append([Sym("label"), Str(net), [Sym("at"), x, y, ang], [Sym("fields_autoplaced"), True],
                              self._effects(FONT, just), [Sym("uuid"), nid("label")]])

        linked = set()
        for a_, b_, net, via in sh.links:
            pts = [a_.pos]
            if a_.x != b_.x and a_.y != b_.y:
                if via == "v" or (via is None and a_.out[0] == 0):
                    pts.append((a_.x, b_.y))
                else:
                    pts.append((b_.x, a_.y))
            pts.append(b_.pos)
            for p1, p2 in zip(pts, pts[1:]):
                seg(p1, p2, net)
            linked.add((r3(a_.x), r3(a_.y)))
            linked.add((r3(b_.x), r3(b_.y)))

        for net, orient, c, pins, label, ext, tap in sh.rails:
            def P(u, v):
                return (u, v) if orient == "h" else (v, u)
            us = []
            for pr in pins:
                pos = pr.pos if isinstance(pr, PinRef) else (r3(pr[0]), r3(pr[1]))
                pu, pv = pos if orient == "h" else (pos[1], pos[0])
                if abs(pv - c) > 1e-3:
                    if not isinstance(pr, PinRef):
                        raise ValueError(f"{sh.name}: rail {net}: point {pr} not on the rail")
                    seg(pos, P(pu, c), net)
                us.append(r3(pu))
            pts = sorted(set(us))
            if label in ("left", "top"):
                pts = [r3(pts[0] - ext)] + pts
            elif label in ("right", "bottom"):
                pts = pts + [r3(pts[-1] + ext)]
            if tap:
                pts = sorted(set(pts + [r3(tap[0])]))
            for a_u, b_u in zip(pts, pts[1:]):
                seg(P(a_u, c), P(b_u, c), net)
            if tap:
                tu, td = tap
                tp = P(tu, c)
                te = (r3(tp[0] + td[0] * STUB), r3(tp[1] + td[1] * STUB))
                seg(tp, te, net)
                put_label(net, te[0], te[1], td)
            if label in ("left", "top"):
                put_label(net, *P(pts[0], c), (-1, 0) if orient == "h" else (0, -1))
            elif label in ("right", "bottom"):
                put_label(net, *P(pts[-1], c), (1, 0) if orient == "h" else (0, 1))
            for pr in pins:
                if isinstance(pr, PinRef):
                    linked.add((r3(pr.x), r3(pr.y)))

        for net, pitems in sh.paths:
            pts = [it.pos if isinstance(it, PinRef) else it for it in pitems]
            for p1, p2 in zip(pts, pts[1:]):
                if abs(p1[0] - p2[0]) > 1e-3 and abs(p1[1] - p2[1]) > 1e-3:
                    raise ValueError(f"{sh.name}: path {net}: diagonal segment {p1} -> {p2}")
                seg(p1, p2, net)
            for it in pitems:
                if isinstance(it, PinRef):
                    linked.add((r3(it.x), r3(it.y)))

        for net, x, y, out in sh.labels:
            put_label(net, x, y, out)

        reqs, seen = [], set()
        for pr, net, label in sh.conns:
            key = (r3(pr.x), r3(pr.y))
            if not label or (key, net) in seen:
                continue
            seen.add((key, net))
            reqs.append((pr, net))
        stub_end = {id(r[0]): (r[0].x + r[0].out[0] * STUB, r[0].y + r[0].out[1] * STUB) for r in reqs}

        def clear(p1, p2, skip_parts, own_pts=()):
            x1, y1, x2, y2 = min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])
            for part, (bx0, by0, bx1, by1) in bboxes:
                if part in skip_parts:
                    continue
                if x1 == x2:
                    if bx0 - 0.3 < x1 < bx1 + 0.3 and max(y1, by0) < min(y2, by1):
                        return False
                elif by0 - 0.3 < y1 < by1 + 0.3 and max(x1, bx0) < min(x2, bx1):
                    return False
            for (sx1, sy1, sx2, sy2) in segs:
                if x1 == x2 and sx1 == sx2 == x1 and max(y1, min(sy1, sy2)) < min(y2, max(sy1, sy2)):
                    return False
                if y1 == y2 and sy1 == sy2 == y1 and max(x1, min(sx1, sx2)) < min(x2, max(sx1, sx2)):
                    return False
            own = {(r3(p[0]), r3(p[1])) for p in own_pts}
            for (px, py) in pin_pts + [(r3(e[0]), r3(e[1])) for e in stub_end.values()]:
                if (px, py) in own:
                    continue
                if x1 - 0.01 <= px <= x2 + 0.01 and y1 - 0.01 <= py <= y2 + 0.01:
                    return False
            return True

        used = set()
        cands = []
        for i, (pa, na) in enumerate(reqs):
            if na in self.power_syms:
                continue
            for j, (pb, nb) in enumerate(reqs):
                if i == j or na != nb or pa.part is pb.part:
                    continue
                if pa.out == (0, 1) and pb.out == (0, -1) and abs(pa.x - pb.x) < 1e-3 and pb.y > pa.y:
                    d = pb.y - pa.y
                elif pa.out == (1, 0) and pb.out == (-1, 0) and abs(pa.y - pb.y) < 1e-3 and pb.x > pa.x:
                    d = pb.x - pa.x
                else:
                    continue
                own = [pa.pos, pb.pos, stub_end[id(pa)], stub_end[id(pb)]]
                if 2.5 <= d <= 30 and clear(pa.pos, pb.pos, {pa.part, pb.part}, own):
                    cands.append((d, i, j))
        cands.sort()
        for d, i, j in cands:
            if i in used or j in used:
                continue
            used.add(i)
            used.add(j)
            pa, net = reqs[i]
            pb, _ = reqs[j]
            seg(pa.pos, pb.pos, net)

        rest = [k for k in range(len(reqs)) if k not in used]
        groups = {}
        for k in rest:
            pr, net = reqs[k]
            line = r3(pr.y) if pr.out[0] == 0 else r3(pr.x)
            groups.setdefault((net, pr.out, line), []).append(k)
        combed = set()
        for (net, out, line), ks in groups.items():
            if len(ks) < 2:
                continue
            along = 0 if out[0] == 0 else 1
            ks.sort(key=lambda k: reqs[k][0].pos[along])
            runs, cur = [], [ks[0]]
            for k in ks[1:]:
                prev = reqs[cur[-1]][0].pos[along]
                here = reqs[k][0].pos[along]
                between = [r for r in reqs if r[1] != net and abs(r[0].pos[1 - along] - line) < 1e-3
                           and r[0].out == out and prev < r[0].pos[along] < here]
                if here - prev <= 5.09 and not between:
                    cur.append(k)
                else:
                    runs.append(cur)
                    cur = [k]
            runs.append(cur)
            for run in runs:
                if len(run) < 2:
                    continue
                ends = []
                for k in run:
                    pr = reqs[k][0]
                    e = (r3(pr.x + out[0] * STUB), r3(pr.y + out[1] * STUB))
                    seg(pr.pos, e, net)
                    ends.append(e)
                    combed.add(k)
                for e1, e2 in zip(ends, ends[1:]):
                    seg(e1, e2, net)
                m = ends[len(ends) // 2]
                put_label(net, m[0], m[1], out)

        for k in rest:
            if k in combed:
                continue
            pr, net = reqs[k]
            e = (r3(pr.x + pr.out[0] * STUB), r3(pr.y + pr.out[1] * STUB))
            seg(pr.pos, e, net)
            put_label(net, e[0], e[1], pr.out)

        def on_seg(pt, sg):
            x1, y1, x2, y2 = sg
            return (min(x1, x2) - 1e-3 <= pt[0] <= max(x1, x2) + 1e-3 and
                    min(y1, y2) - 1e-3 <= pt[1] <= max(y1, y2) + 1e-3)

        for net in dict.fromkeys(seg_net):
            mine = [sg for sg, n in zip(segs, seg_net) if n == net]
            group = list(range(len(mine)))

            def root(i):
                while group[i] != i:
                    group[i] = group[group[i]]
                    i = group[i]
                return i
            for i, a in enumerate(mine):
                for j in range(i + 1, len(mine)):
                    b = mine[j]
                    if any(on_seg(pt, b) for pt in (a[:2], a[2:])) or any(on_seg(pt, a) for pt in (b[:2], b[2:])):
                        group[root(i)] = root(j)
            components = {}
            for i, sg in enumerate(mine):
                components.setdefault(root(i), []).append(sg)
            for comp in components.values():
                if any(n == net and any(on_seg((x, y), sg) for sg in comp) for n, x, y in label_pts):
                    continue
                need = len(net) * FONT * TEXT_W + 1.27 + 4.0
                flat = [sg for sg in comp if sg[1] == sg[3]]
                fits = [sg for sg in flat if abs(sg[2] - sg[0]) >= need]
                if fits or flat:
                    x1, y1, x2, y2 = max(fits or flat, key=lambda sg: abs(sg[2] - sg[0]))
                    span = abs(x2 - x1)
                    x = min(x1, x2) + (2.54 + snap((span - need) / 2) if span > need else 0)
                    put_label(net, x, y1, (1, 0))
                else:
                    x1, y1, x2, y2 = max(comp, key=lambda sg: abs(sg[3] - sg[1]))
                    span = abs(y2 - y1)
                    y = max(y1, y2) - (snap((span - need) / 2) if span > need else 0)
                    put_label(net, x1, y, (0, -1))

        for (x1, y1, x2, y2) in segs:
            lx0, ly0, lx1, ly1 = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
            for part, (bx0, by0, bx1, by1) in bboxes:
                if part.lib_id == "power:PWR_FLAG":
                    continue
                own = {(r3(q.x), r3(q.y)) for q in (part.pin(pp.number) for pp in part.unit_pins())}
                if (x1, y1) in own or (x2, y2) in own:
                    continue
                m = 0.6
                if max(lx0, bx0 + m) < min(lx1, bx1 - m) + (1e-6 if lx0 == lx1 else 0) and \
                        max(ly0, by0 + m) < min(ly1, by1 - m) + (1e-6 if ly0 == ly1 else 0):
                    if (bx0 + m) <= lx0 <= (bx1 - m) or (by0 + m) <= ly0 <= (by1 - m):
                        self.lint.append(f"{sh.name}: wire ({x1},{y1})-({x2},{y2}) crosses {part.ref}")
            for (px, py) in pin_pts:
                if (px, py) in ((x1, y1), (x2, y2)):
                    continue
                if lx0 - 1e-3 <= px <= lx1 + 1e-3 and ly0 - 1e-3 <= py <= ly1 + 1e-3:
                    self.lint.append(f"{sh.name}: pin at ({px},{py}) touches wire ({x1},{y1})-({x2},{y2}) mid-span")

        for (x1, y1, x2, y2) in segs:
            items.append([Sym("wire"), [Sym("pts"), [Sym("xy"), x1, y1], [Sym("xy"), x2, y2]],
                          [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]], [Sym("uuid"), nid("wire")]])
        cnt = {}
        for (x1, y1, x2, y2) in segs:
            for pt in ((x1, y1), (x2, y2)):
                cnt[pt] = cnt.get(pt, 0) + 1
        for (x1, y1, x2, y2) in segs:
            for pt in list(cnt):
                if pt in ((x1, y1), (x2, y2)):
                    continue
                if (x1 == x2 == pt[0] and min(y1, y2) < pt[1] < max(y1, y2)) or \
                        (y1 == y2 == pt[1] and min(x1, x2) < pt[0] < max(x1, x2)):
                    cnt[pt] += 2
        for pt in pinset:
            if pt in cnt:
                cnt[pt] += 1
        for pp in extra_parts:
            k = (r3(pp.x), r3(pp.y))
            if k in cnt:
                cnt[k] += 1
        for k, n in sorted(cnt.items()):
            if n >= 3:
                items.append([Sym("junction"), [Sym("at"), k[0], k[1]], [Sym("diameter"), 0],
                              [Sym("color"), 0, 0, 0, 0], [Sym("uuid"), nid("junction")]])
        for pr in sh.ncs:
            items.append([Sym("no_connect"), [Sym("at"), pr.x, pr.y], [Sym("uuid"), nid("nc")]])
        flag_at, table_rects, table_texts = {}, [], []
        if sh.class_box and sh.netclasses:
            bx, by, rows, col_w, pitch, title = sh.class_box
            ncols = (len(sh.netclasses) + rows - 1) // rows
            shown = min(rows, len(sh.netclasses))
            table_rects = [(r3(bx), r3(by), r3(bx + ncols * col_w), r3(by + 5.08 + shown * pitch + 2.54))]
            table_texts = [(title, r3(bx + 1.27), r3(by + 3.81), 1.8, True)]
            for i, (net, cls) in enumerate(sh.netclasses):
                cx = bx + (i // rows) * col_w + col_w * 0.5
                cy = r3(by + 5.08 + (i % rows) * pitch + pitch * 0.5)
                a, b = (r3(snap(cx - 7.62)), cy), (r3(snap(cx + 2.54)), cy)
                items.append([Sym("wire"), [Sym("pts"), [Sym("xy"), a[0], a[1]], [Sym("xy"), b[0], b[1]]],
                              [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]],
                              [Sym("uuid"), nid("wire")]])
                put_label(net, a[0], a[1], (-1, 0))
                flag_at[net] = b
        for net, cls in sh.netclasses:
            at = flag_at.get(net) or next(((x, y) for n, x, y in label_pts if n == net), None)
            if at is None:
                raise ValueError(f"{sh.name}: net class {cls} for {net}, which has no label on this sheet")
            ang, tx, ty = (270, r3(at[0] + 3.81), r3(at[1])) if net in flag_at else (0, r3(at[0] + 1.27), r3(at[1] - 2.54))
            self._tb.append((text_box(tx, ty, cls, FONT, 0, "left", False), ("class", net), cls))
            items.append([Sym("netclass_flag"), Str(""), [Sym("length"), 2.54], [Sym("shape"), Sym("round")],
                          [Sym("at"), at[0], at[1], ang], [Sym("fields_autoplaced"), True],
                          self._effects(FONT, "left bottom"), [Sym("uuid"), nid("netclass")],
                          [Sym("property"), Str("Net Class"), Str(cls), [Sym("at"), tx, ty, 0],
                           [Sym("show_name"), False], [Sym("do_not_autoplace"), False], self._effects(FONT, "left")]])
        for (s, x, y, size, bold) in sh.texts + table_texts:
            items.append([Sym("text"), Str(s), [Sym("exclude_from_sim"), False], [Sym("at"), x, y, 0],
                          self._effects(size, "left bottom", bold=bold), [Sym("uuid"), nid("text")]])
        for (x0, y0, x1, y1) in sh.rects + table_rects:
            items.append([Sym("rectangle"), [Sym("start"), x0, y0], [Sym("end"), x1, y1],
                          [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("dash")]],
                          [Sym("fill"), [Sym("type"), Sym("none")]], [Sym("uuid"), nid("rect")]])
        allparts = sh.parts + extra_parts
        lib_symbols = {}
        for p in allparts:
            lib_symbols.setdefault(p.lib_id, p.sym.embedded())
        syms = [self._symbol_inst(sh, p) for p in allparts]
        for (s, x, y, size, bold) in sh.texts + table_texts:
            lines = s.split("\n")
            w = max(len(ln) for ln in lines) * size * TEXT_W
            self._tb.append(((x, y - len(lines) * size * 1.65, x + w, y), ("text", x, y), lines[0]))
        self._text_lint(sh, bboxes)
        self._box_lint(sh.name, sh.rects + table_rects, bboxes)
        self._tb = None
        comments = [self.title] + self.comments
        tree = [Sym("kicad_sch"), [Sym("version"), VERSION], [Sym("generator"), Str("eeschema")],
                [Sym("generator_version"), Str(GENERATOR_VERSION)], [Sym("uuid"), uid("file", sh.name)],
                [Sym("paper"), Str(sh.paper)], self._title_block(sh.sheetname, comments),
                [Sym("lib_symbols")] + list(lib_symbols.values())]
        tree += items + syms
        tree.append([Sym("embedded_fonts"), False])
        return tree

    def _root_tree(self, texts):
        items, sheet_rects = [], []
        x0, y0, w, h = 30.48, 63.5, 83.82, 33.02
        for i, sh in enumerate(self.sheets):
            col, row = i % 4, i // 4
            x, y = x0 + col * (w + 12.7), y0 + row * (h + 22.86)
            x, y = r3(x), r3(y)
            items.append([Sym("sheet"), [Sym("at"), x, y], [Sym("size"), w, h], [Sym("exclude_from_sim"), False],
                          [Sym("in_bom"), True], [Sym("on_board"), True], [Sym("dnp"), False],
                          [Sym("fields_autoplaced"), True],
                          [Sym("stroke"), [Sym("width"), 0.1524], [Sym("type"), Sym("solid")]],
                          [Sym("fill"), [Sym("color"), 0, 0, 0, 0.0]], [Sym("uuid"), sh.uuid],
                          [Sym("property"), Str("Sheetname"), Str(sh.sheetname), [Sym("at"), x, r3(y - 0.7), 0],
                           self._effects(FONT, "left bottom")],
                          [Sym("property"), Str("Sheetfile"), Str(sh.filename), [Sym("at"), x, r3(y + h + 0.6), 0],
                           self._effects(FONT, "left top")],
                          [Sym("instances"), [Sym("project"), Str(self.name),
                                              [Sym("path"), Str(f"/{self.root_uuid}"), [Sym("page"), Str(sh.page)]]]]])
            sheet_rects.append(((x, y - 2.5, x + w, y + h + 2.5), sh.sheetname))
            if sh.desc:
                dw = max(len(d) for d in sh.desc) * FONT * TEXT_W
                if x + 2.54 + dw > x + w - 1.27:
                    self.lint.append(f"root: description of {sh.sheetname} runs past its sheet symbol")
                items.append([Sym("text"), Str("\n".join(sh.desc)), [Sym("exclude_from_sim"), False],
                              [Sym("at"), r3(x + 2.54), snap(y + 5.08 + (len(sh.desc) - 1) * 2.1), 0],
                              self._effects(FONT, "left bottom"), [Sym("uuid"), uid("root", "desc", sh.name)]])
        for i, (s, x, y, size, bold) in enumerate(texts):
            items.append([Sym("text"), Str(s), [Sym("exclude_from_sim"), False], [Sym("at"), x, y, 0],
                          self._effects(size, "left bottom", bold=bold), [Sym("uuid"), uid("root", "text", i)]])
        self._root_lint(sheet_rects, texts)
        return [Sym("kicad_sch"), [Sym("version"), VERSION], [Sym("generator"), Str("eeschema")],
                [Sym("generator_version"), Str(GENERATOR_VERSION)], [Sym("uuid"), self.root_uuid],
                [Sym("paper"), Str("A3")], self._title_block(self.title, self.comments), [Sym("lib_symbols")]] + \
            items + [[Sym("sheet_instances"), [Sym("path"), Str("/"), [Sym("page"), Str("1")]]],
                     [Sym("embedded_fonts"), False]]


def load_pinmap(path):
    """{function: pad number} from a pin map written by pcb-placement's pins.py (comment lines start with #)."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                cols = line.split()
                out[cols[0]] = cols[2]
    return out
