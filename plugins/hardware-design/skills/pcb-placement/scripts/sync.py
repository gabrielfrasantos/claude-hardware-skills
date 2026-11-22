#!/usr/bin/env python3
"""sync.py: update a KiCad 10 board from its schematic without KiCad's window (Tools > Update PCB from Schematic).

    sync.py <board.kicad_pcb> [--schematic board.kicad_sch | --netlist board.net] [--kicad-cli PATH]
            [--layers 2|4|6] [--park X,Y] [--dry-run | --check]

Libraries: the board folder's fp-lib-table, then the newest global one (~/.config/kicad/<version>/, or
$KICAD_CONFIG_HOME); ${KICAD<n>_FOOTPRINT_DIR} resolves from the environment or KiCad's install folder.

Reads KiCad's netlist (exported with kicad-cli from the schematic next to the board, or --netlist) and, on the board:
  adds    a footprint for every symbol that has none, from the project's and the global fp-lib-table, parked in a
          grid below the board outline (or at --park);
  updates every footprint's reference, value, fields (LCSC, MPN, Datasheet, ...), schematic link (path, sheet),
          DNP and BOM flags (a part left out of the BOM or not fitted is left out of the position file too), and
          the net, pin function and pin type of every pad;
  replaces a footprint whose library footprint changed, at the same position, rotation and lock;
  removes footprints whose symbol is gone. Footprints the schematic never placed (no path) stay.
Only the footprints that change are rewritten; the rest of the file is kept byte for byte. With no board, it writes
an empty KiCad 10 board with --layers copper layers (default 4) first. Outline, stack-up, zones and net classes are
not its job (pcb-design-rules, pcb-copper).
Exit 1 when a footprint can't be found or a pad number in the netlist has no pad; with --check (writes nothing),
also when any footprint would change: the board is not in step with its schematic.
"""
import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

NS = uuid.UUID("6f1c2f9e-3b0e-4c55-9a51-2a7c6c1d0b10")
_TOK = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+')
KEEP_PROPS = ("Reference", "Value", "Footprint")
PARK_GAP = 1.0
ATTR_ORDER = ("smd", "through_hole", "board_only", "exclude_from_pos_files", "exclude_from_bom",
              "allow_missing_courtyard", "dnp")
DEFAULT_FP_DIRS = ("/usr/share/kicad/footprints", "/usr/local/share/kicad/footprints",
                   "/usr/share/kicad-nightly/footprints",
                   "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
                   r"C:\Program Files\KiCad\10.0\share\kicad\footprints")


# --------------------------------------------------------------------------------------------- S-expressions
def parse(text):
    """Nested lists of raw tokens; a quoted string keeps its quotes, so nothing is lost on the way back."""
    stack, cur = [], []
    for m in _TOK.finditer(text):
        t = m.group(0)
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(t)
    return cur[0] if cur else []


def top_spans(text):
    """(start, end, head) of each direct child of the file's root list."""
    out, depth, start, i, n = [], 0, None, 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "(":
            depth += 1
            if depth == 2:
                start = i
        elif ch == ")":
            if depth == 2:
                m = re.match(r"\(([^\s()\"]+)", text[start:start + 64])
                out.append((start, i + 1, m.group(1) if m else ""))
            depth -= 1
        i += 1
    return out


def dump(node, depth=1):
    lead = []
    i = 0
    while i < len(node) and not isinstance(node[i], list):
        lead.append(node[i])
        i += 1
    if i == len(node):
        return "(" + " ".join(lead) + ")"
    if node[0] == "pts":
        return "(pts\n" + "\t" * (depth + 1) + " ".join(dump(c, depth + 1) for c in node[1:]) + "\n" + "\t" * depth + ")"
    pad = "\t" * (depth + 1)
    body = "".join("\n" + pad + (dump(c, depth + 1) if isinstance(c, list) else c) for c in node[i:])
    return "(" + " ".join(lead) + body + "\n" + "\t" * depth + ")"


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def uq(t):
    return t[1:-1].replace('\\"', '"').replace("\\\\", "\\") if t.startswith('"') else t


def child(node, key):
    return next((c for c in node if isinstance(c, list) and c and c[0] == key), None)


def children(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def val(node, key, default=""):
    c = child(node, key)
    return uq(c[1]) if c and len(c) > 1 else default


# --------------------------------------------------------------------------------------------------- netlist
def read_netlist(text):
    root = parse(text)
    comps = {}
    for c in children(child(root, "components") or [], "comp"):
        props = {val(p, "name"): val(p, "value") for p in children(c, "property")}
        if "exclude_from_board" in props:
            continue
        fields = {}
        for f in children(child(c, "fields") or [], "field"):
            name = val(f, "name")
            fields[name] = uq(f[2]) if len(f) > 2 and not isinstance(f[2], list) else ""
        sp = child(c, "sheetpath") or []
        ref = val(c, "ref")
        comps[ref] = dict(ref=ref, value=val(c, "value"), footprint=val(c, "footprint"), fields=fields,
                          path=val(sp, "tstamps", "/") + val(c, "tstamps"), sheetname=val(sp, "names", "/"),
                          sheetfile=props.get("Sheetfile", ""), dnp="dnp" in props,
                          exclude_from_bom="exclude_from_bom" in props, pads={})
    for n in children(child(root, "nets") or [], "net"):
        name = val(n, "name")
        for d in children(n, "node"):
            c = comps.get(val(d, "ref"))
            if c is not None:
                c["pads"][val(d, "pin")] = (name, val(d, "pinfunction"), val(d, "pintype"))
    return comps


def export_netlist(cli, sch):
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "board.net")
        r = subprocess.run([cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, sch],
                           capture_output=True, text=True)
        if not os.path.exists(out):
            sys.exit(f"kicad-cli could not export the netlist of {sch}: {(r.stdout + r.stderr).strip()[-300:]}")
        with open(out, encoding="utf-8") as f:
            return f.read()


# ------------------------------------------------------------------------------------------------ libraries
def _expand(uri, env):
    def sub(m):
        k = m.group(1)
        if re.fullmatch(r"KICAD\d+_FOOTPRINT_DIR", k):
            return os.environ.get(k) or env["KICAD_FOOTPRINT_DIR"] or m.group(0)
        return env.get(k) or os.environ.get(k) or m.group(0)
    return re.sub(r"\$\{([^}]+)\}", sub, uri)


def _version(name):
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return ()


def global_table():
    """The fp-lib-table of the newest KiCad configuration folder (kicad/10.0, kicad/11.0, kicadnightly/...)."""
    base = os.environ.get("KICAD_CONFIG_HOME")
    roots = [base] if base else [os.path.join(os.path.expanduser("~"), ".config", d) for d in ("kicad", "kicadnightly")]
    found = []
    for r in roots:
        if os.path.isdir(r):
            for v in os.listdir(r):
                t = os.path.join(r, v, "fp-lib-table")
                if os.path.exists(t):
                    found.append((_version(v), t))
    return max(found)[1] if found else None


def lib_tables(board_dir):
    """{nickname: folder}: the project's fp-lib-table first, then the global one."""
    fp_dir = next((os.environ[k] for k in sorted(os.environ, reverse=True) if re.fullmatch(r"KICAD\d+_FOOTPRINT_DIR", k)),
                  None) or next((d for d in DEFAULT_FP_DIRS if os.path.isdir(d)), "")
    env = {"KIPRJMOD": board_dir, "KICAD_FOOTPRINT_DIR": fp_dir}
    tables = [os.path.join(board_dir, "fp-lib-table"), global_table()]
    libs = {}
    for t in tables:
        if t and os.path.exists(t):
            with open(t, encoding="utf-8") as f:
                for lib in children(parse(f.read()), "lib"):
                    libs.setdefault(val(lib, "name"), _expand(val(lib, "uri"), env))
    return libs, fp_dir


def load_footprint(fpid, libs, fp_dir):
    nick, _, name = fpid.partition(":")
    folder = libs.get(nick) or (os.path.join(fp_dir, nick + ".pretty") if fp_dir else "")
    path = os.path.join(folder, name + ".kicad_mod")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return parse(f.read())


# --------------------------------------------------------------------------------------------- footprints
def _uuids(node, ref, counter):
    for c in node:
        if isinstance(c, list):
            _uuids(c, ref, counter)
    if node and node[0] in ("property", "fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_curve",
                            "fp_text", "fp_text_box", "pad", "zone", "group", "dimension", "image") \
            and child(node, "uuid") is None and not (node[0] == "property" and not str(node[1:2] and node[1]).startswith('"')):
        counter[0] += 1
        node.append(["uuid", q(str(uuid.uuid5(NS, f"{ref}/{counter[0]}")))])


def _turn(node, rot):
    """Add the footprint's rotation to the angle of its pads and texts, as KiCad stores them on a board."""
    if not rot:
        return
    for c in node:
        if isinstance(c, list) and c and c[0] in ("pad", "property", "fp_text"):
            at = child(c, "at")
            if at:
                a = (float(at[3]) if len(at) > 3 else 0.0) + rot
                a = (a + 180) % 360 - 180
                at[3:] = [f"{a:g}"]


def _drop_uuids(node):
    node[:] = [c for c in node if not (isinstance(c, list) and c and c[0] == "uuid")]
    for c in node:
        if isinstance(c, list):
            _drop_uuids(c)


def _place_zones(node, x, y, rot):
    """Zones inside a footprint are stored in board coordinates."""
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    for z in children(node, "zone"):
        for poly in children(z, "polygon") + children(z, "filled_polygon"):
            for xy in children(child(poly, "pts") or [], "xy"):
                px, py = float(xy[1]), float(xy[2])
                xy[1:3] = [f"{round(x + px * c + py * s, 6):g}", f"{round(y - px * s + py * c, 6):g}"]


def from_library(lib, fpid, ref, x, y, rot=0.0, locked=False):
    lib = parse(dump(lib))
    _drop_uuids(lib)
    fp = ["footprint", q(fpid)]
    if locked:
        fp.append(["locked", "yes"])
    for c in lib[2:]:
        if isinstance(c, list) and c[0] in ("version", "generator", "generator_version"):
            continue
        fp.append(c)
        if isinstance(c, list) and c[0] == "layer":
            fp.append(["uuid", q(str(uuid.uuid5(NS, f"{ref}/footprint")))])
            fp.append(["at", f"{x:g}", f"{y:g}"] + ([f"{rot:g}"] if rot else []))
    _uuids(fp, ref, [0])
    _turn(fp, rot)
    _place_zones(fp, x, y, rot)
    return fp


def _set_prop(fp, name, value):
    for p in children(fp, "property"):
        if uq(p[1]) == name:
            p[2] = q(value)
            return
    back = (val(fp, "layer") == "B.Cu")
    prop = ["property", q(name), q(value), ["at", "0", "0", "0"], ["layer", q("B.Fab" if back else "F.Fab")],
            ["hide", "yes"], ["uuid", q(str(uuid.uuid5(NS, f"{_ref(fp)}/property/{name}")))],
            ["effects", ["font", ["size", "1.27", "1.27"], ["thickness", "0.15"]]]
            + ([["justify", "mirror"]] if back else [])]
    last = max((i for i, c in enumerate(fp) if isinstance(c, list) and c[0] == "property"), default=len(fp) - 1)
    fp.insert(last + 1, prop)


def _ref(fp):
    return next((uq(p[2]) for p in children(fp, "property") if uq(p[1]) == "Reference"), "")


def _set_after(fp, key, value_list, after=("property",)):
    c = child(fp, key)
    if c is not None:
        c[1:] = value_list
        return
    idx = max((i for i, c in enumerate(fp) if isinstance(c, list) and c[0] in after), default=len(fp) - 1)
    fp.insert(idx + 1, [key] + value_list)


def update(fp, comp):
    """Apply the netlist's data to one footprint. Returns the pad numbers the netlist has but the footprint lacks."""
    _set_prop(fp, "Reference", comp["ref"])
    _set_prop(fp, "Value", comp["value"])
    for k, v in comp["fields"].items():
        if k not in KEEP_PROPS:
            _set_prop(fp, k, v)
    _set_after(fp, "path", [q(comp["path"])])
    _set_after(fp, "sheetname", [q(comp["sheetname"])], ("property", "path"))
    _set_after(fp, "sheetfile", [q(comp["sheetfile"])], ("property", "path", "sheetname"))
    attr = child(fp, "attr")
    flags = {t for t in (attr[1:] if attr else []) if t in ATTR_ORDER and t not in ("exclude_from_bom", "dnp")}
    flags |= {t for t, on in (("exclude_from_bom", comp["exclude_from_bom"]), ("dnp", comp["dnp"])) if on}
    if comp["exclude_from_bom"] or comp["dnp"]:
        flags.add("exclude_from_pos_files")
    kinds = [t for t in ATTR_ORDER if t in flags]
    if attr is not None:
        attr[1:] = kinds
    elif kinds:
        _set_after(fp, "attr", kinds, ("property", "path", "sheetname", "sheetfile"))
    numbers = set()
    for pad in children(fp, "pad"):
        num = uq(pad[1])
        numbers.add(num)
        for key in ("net", "pinfunction", "pintype"):
            c = child(pad, key)
            if c is not None:
                pad.remove(c)
        if num in comp["pads"]:
            net, function, ptype = comp["pads"][num]
            at = next(i for i, c in enumerate(pad) if isinstance(c, list) and c[0] == "layers") + 1
            extra = [["net", q(net)]] + ([["pinfunction", q(function)]] if function else []) + \
                ([["pintype", q(ptype)]] if ptype else [])
            while at < len(pad) and isinstance(pad[at], list) and pad[at][0] in ("roundrect_rratio", "chamfer_ratio",
                                                                                  "chamfer", "remove_unused_layers",
                                                                                  "keep_end_layers"):
                at += 1
            pad[at:at] = extra
    return sorted(set(comp["pads"]) - numbers)


# --------------------------------------------------------------------------------------------------- board
LAYERS = {
    2: ['(0 "F.Cu" signal)', '(2 "B.Cu" signal)'],
    4: ['(0 "F.Cu" signal)', '(4 "In1.Cu" signal)', '(6 "In2.Cu" signal)', '(2 "B.Cu" signal)'],
    6: ['(0 "F.Cu" signal)', '(4 "In1.Cu" signal)', '(6 "In2.Cu" signal)', '(8 "In3.Cu" signal)',
        '(10 "In4.Cu" signal)', '(2 "B.Cu" signal)'],
}
USER_LAYERS = ['(9 "F.Adhes" user "F.Adhesive")', '(11 "B.Adhes" user "B.Adhesive")', '(13 "F.Paste" user)',
               '(15 "B.Paste" user)', '(5 "F.SilkS" user "F.Silkscreen")', '(7 "B.SilkS" user "B.Silkscreen")',
               '(1 "F.Mask" user)', '(3 "B.Mask" user)', '(25 "Edge.Cuts" user)', '(27 "Margin" user)',
               '(31 "F.CrtYd" user "F.Courtyard")', '(29 "B.CrtYd" user "B.Courtyard")', '(35 "F.Fab" user)',
               '(33 "B.Fab" user)']


def empty_board(layers):
    rows = "\n".join("\t\t" + r for r in LAYERS[layers] + USER_LAYERS)
    return ('(kicad_pcb\n\t(version 20260206)\n\t(generator "pcbnew")\n\t(generator_version "10.0")\n'
            '\t(general\n\t\t(thickness 1.6)\n\t\t(legacy_teardrops no)\n\t)\n\t(paper "A4")\n'
            f'\t(layers\n{rows}\n\t)\n\t(setup\n\t\t(pad_to_mask_clearance 0)\n\t)\n\t(embedded_fonts no)\n)\n')


def outline_box(text):
    xs, ys = [], []
    for m in re.finditer(r'\(gr_(?:line|rect|arc|circle|poly)\b(?:[^()]|\((?:[^()]|\([^()]*\))*\))*?'
                         r'\(layer "Edge\.Cuts"\)', text):
        for x, y in re.findall(r"\((?:start|end|mid|center|xy) ([-\d.]+) ([-\d.]+)\)", m.group(0)):
            xs.append(float(x))
            ys.append(float(y))
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def extent(lib):
    """Local box of a library footprint: its courtyard, else its pads."""
    pts = []
    for c in lib:
        if isinstance(c, list) and c[0].startswith("fp_") and val(c, "layer").endswith("CrtYd"):
            for k in ("start", "end", "mid", "center"):
                p = child(c, k)
                if p:
                    pts.append((float(p[1]), float(p[2])))
            for xy in children(child(c, "pts") or [], "xy"):
                pts.append((float(xy[1]), float(xy[2])))
            if c[0] == "fp_circle" and child(c, "center") and child(c, "end"):
                cx, cy = float(child(c, "center")[1]), float(child(c, "center")[2])
                r = math.dist((cx, cy), (float(child(c, "end")[1]), float(child(c, "end")[2])))
                pts += [(cx - r, cy - r), (cx + r, cy + r)]
    if not pts:
        for p in children(lib, "pad"):
            at, size = child(p, "at"), child(p, "size")
            if at and size:
                x, y, w, h = float(at[1]), float(at[2]), float(size[1]), float(size[2])
                pts += [(x - w / 2, y - h / 2), (x + w / 2, y + h / 2)]
    if not pts:
        return (-0.5, -0.5, 0.5, 0.5)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def sort_key(ref):
    m = re.match(r"([A-Za-z#_]*)(\d*)", ref)
    return (m.group(1), int(m.group(2) or 0), ref)


def sync(text, comps, libs, fp_dir, park=None):
    """Returns (new text, report dict)."""
    spans = top_spans(text)
    rep = dict(added=[], updated=[], replaced=[], removed=[], kept_board_only=[], missing_footprints=[],
               missing_pads=[], back_side_replace=[])
    pieces, seen = [], set()
    pos = 0
    box = outline_box(text)
    row_w = max(60.0, box[2] - box[0]) if box else 100.0
    if park is None:
        park = (box[0], box[3] + 6.0) if box else (0.0, 0.0)
    for start, end, head in spans:
        if head != "footprint":
            continue
        block = text[start:end]
        fp = parse(block)
        ref = _ref(fp)
        comp = comps.get(ref)
        pieces.append(text[pos:start])
        pos = end
        if comp is None:
            if child(fp, "path") is None:
                rep["kept_board_only"].append(ref)
                pieces.append(block)
            else:
                rep["removed"].append(ref)
            continue
        seen.add(ref)
        new = fp
        if uq(fp[1]) != comp["footprint"]:
            if val(fp, "layer") == "B.Cu":
                rep["back_side_replace"].append(ref)
            else:
                lib = load_footprint(comp["footprint"], libs, fp_dir)
                if lib is None:
                    rep["missing_footprints"].append(f"{ref}: {comp['footprint']}")
                else:
                    at = child(fp, "at")
                    new = from_library(lib, comp["footprint"], ref, float(at[1]), float(at[2]),
                                       float(at[3]) if len(at) > 3 else 0.0, child(fp, "locked") is not None
                                       or "locked" in fp[2:3])
                    rep["replaced"].append(ref)
        before = repr(fp) if new is fp else None
        missing = update(new, comp)
        rep["missing_pads"] += [f"{ref}.{p}" for p in missing]
        if new is fp and repr(fp) == before:
            pieces.append(block)
        else:
            if new is fp:
                rep["updated"].append(ref)
            pieces.append(dump(new))
    pieces.append(text[pos:])
    out = "".join(pieces)
    out = re.sub(r"\n[ \t]*\n", "\n", out)
    added, cx, cy, row_h = [], park[0], park[1], 0.0
    for ref in sorted((r for r in comps if r not in seen), key=sort_key):
        comp = comps[ref]
        if not comp["footprint"]:
            rep["missing_footprints"].append(f"{ref}: no footprint assigned")
            continue
        lib = load_footprint(comp["footprint"], libs, fp_dir)
        if lib is None:
            rep["missing_footprints"].append(f"{ref}: {comp['footprint']}")
            continue
        x0, y0, x1, y1 = extent(lib)
        if cx > park[0] and cx + (x1 - x0) > park[0] + row_w:
            cx, cy, row_h = park[0], cy + row_h + PARK_GAP, 0.0
        x, y = cx - x0, cy - y0
        cx += (x1 - x0) + PARK_GAP
        row_h = max(row_h, y1 - y0)
        fp = from_library(lib, comp["footprint"], ref, round(x, 3), round(y, 3))
        rep["missing_pads"] += [f"{ref}.{p}" for p in update(fp, comp)]
        added.append("\t" + dump(fp))
        rep["added"].append(ref)
    if added:
        spans = top_spans(out)
        fps = [s for s in spans if s[2] == "footprint"]
        anchor = fps[-1][1] if fps else (spans[-1][1] if spans else out.rindex(")"))
        out = out[:anchor] + "".join("\n" + a for a in added) + out[anchor:]
    return out, rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--schematic")
    src.add_argument("--netlist")
    ap.add_argument("--kicad-cli")
    ap.add_argument("--layers", type=int, choices=sorted(LAYERS), default=4)
    ap.add_argument("--park", help="X,Y in mm where new footprints start (default: below the board outline)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if the board would change")
    a = ap.parse_args(argv)
    board = os.path.abspath(a.board)
    if a.netlist:
        with open(a.netlist, encoding="utf-8") as f:
            net_text = f.read()
    else:
        sch = a.schematic or os.path.splitext(board)[0] + ".kicad_sch"
        cli = a.kicad_cli or os.environ.get("KICAD_CLI") or shutil.which("kicad-cli")
        if not cli:
            sys.exit("kicad-cli not found: pass --kicad-cli, or export the netlist and pass --netlist")
        net_text = export_netlist(cli, sch)
    comps = read_netlist(net_text)
    if os.path.exists(board):
        with open(board, encoding="utf-8") as f:
            text = f.read()
    else:
        text = empty_board(a.layers)
    libs, fp_dir = lib_tables(os.path.dirname(board))
    park = tuple(float(v) for v in a.park.split(",")) if a.park else None
    out, rep = sync(text, comps, libs, fp_dir, park)
    for k in ("added", "replaced", "updated", "removed", "kept_board_only"):
        if rep[k]:
            print(f"{k.replace('_', ' ')} ({len(rep[k])}): {', '.join(sorted(rep[k], key=sort_key))}")
    problems = rep["missing_footprints"] + rep["missing_pads"] + rep["back_side_replace"]
    for k, msg in (("missing_footprints", "footprint not found"), ("missing_pads", "netlist pin with no pad"),
                   ("back_side_replace", "footprint changed on the back side: replace it in KiCad")):
        for item in rep[k]:
            print(f"ERROR {msg}: {item}")
    if not (a.dry_run or a.check) and out != text:
        with open(board, "w", encoding="utf-8") as f:
            f.write(out)
    total = sum(len(rep[k]) for k in ("added", "replaced", "updated", "removed"))
    print(f"{os.path.basename(board)}: {len(comps)} symbols; {total} footprints changed"
          + (" (nothing written)" if a.dry_run or a.check else ""))
    return 1 if problems or (a.check and total) else 0


if __name__ == "__main__":
    sys.exit(main())
