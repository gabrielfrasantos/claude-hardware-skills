#!/usr/bin/env python3
"""Build and keep the example board in step with the schematic, headless, with KiCad 10's pcbnew Python module.

    python3 scripts/make_board.py create     a new board from KiCad's netlist: outline, the anchors placed and
                                             locked, every other part parked to the right for place.py optimize
    python3 scripts/make_board.py update     after a schematic change: nets, values and fields from the netlist;
                                             new parts are parked, removed ones deleted, nothing placed moves
    python3 scripts/make_board.py anchors    (re)place and lock every anchor below on an existing board
    python3 scripts/make_board.py zones      ground planes on In1/In2, pours for the PWR_3A / GND_3A nets around
                                             their pads, the antenna keep-outs; then kicad-cli refills them

This stands in for KiCad's *Tools > Update PCB from Schematic*, which kicad-cli 10 does not offer. It is example
tooling, not plugin code: the plugin reads and writes KiCad files as text (docs/design.md D22) and never imports
pcbnew. The anchors below are the owner's decisions (pcb-placement §1), recorded in docs/decisions.md.
"""
import json
import pathlib
import re
import subprocess
import sys

import pcbnew

ROOT = pathlib.Path(__file__).resolve().parent.parent
HW = ROOT / "hardware" / "stepper-ble"
SCH, PCB, PRO = HW / "stepper-ble.kicad_sch", HW / "stepper-ble.kicad_pcb", HW / "stepper-ble.kicad_pro"
FP_DIRS = {"stepper-ble": HW / "stepper-ble.pretty"}
SYSTEM_FP = pathlib.Path("/usr/share/kicad/footprints")

X0, Y0, W, H = 100.0, 100.0, 80.0, 60.0
ANCHORS = {
    "J201": (112.0, 106.5, 0, "F"),
    "J301": (127.0, 154.0, 180, "F"),
    "J601": (163.0, 155.2, 0, "F"),
    "AE501": (171.0, 106.5, 0, "F"),
    "U401": (165.0, 124.0, 180, "F"),
    "U301": (137.0, 136.0, 180, "F"),
    "Q301": (127.5, 134.0, 0, "F"), "Q302": (127.5, 140.5, 0, "F"),
    "Q303": (121.5, 134.0, 0, "F"), "Q304": (121.5, 140.5, 0, "F"),
    "Q305": (115.5, 134.0, 0, "F"), "Q306": (115.5, 140.5, 0, "F"),
    "Q307": (109.5, 134.0, 0, "F"), "Q308": (109.5, 140.5, 0, "F"),
    "R301": (124.5, 145.8, 0, "F"), "R302": (112.5, 145.8, 0, "F"),
    "C306": (124.5, 129.5, 0, "F"), "C307": (112.5, 129.5, 0, "F"),
    "RT301": (118.5, 137.25, 90, "F"),
    "U201": (146.0, 119.0, 0, "F"), "L201": (152.5, 119.0, 0, "F"),
    "F201": (125.5, 104.0, 0, "F"), "D201": (125.5, 109.0, 0, "F"), "C201": (138.0, 108.0, 0, "F"),
    "C202": (146.5, 108.0, 90, "F"),
    "Q201": (117.0, 116.5, 0, "F"), "D202": (111.5, 116.5, 0, "F"), "R201": (111.5, 119.5, 0, "F"),
    "H601": (104.0, 104.0, 0, "F"), "H602": (104.0, 156.0, 0, "F"),
    "H603": (176.0, 156.0, 0, "F"), "H604": (176.0, 114.0, 0, "F"),
    "FID601": (104.0, 128.0, 0, "F"), "FID602": (150.0, 104.0, 0, "F"), "FID603": (176.0, 140.0, 0, "F"),
}
ANTENNA_KEEPOUT = (157.0, 100.0, 168.6, 110.0)
ANTENNA_NO_PARTS = (155.0, 107.5, 170.0, 111.0)
POUR_CLASSES = re.compile(r"^(PWR|GND)_(\d+(?:[.p]\d+)?)A")
PARK_X = X0 + W + 10.0


def mm(v):
    return pcbnew.FromMM(v)


def sexpr(text):
    """Parse an S-expression into nested lists of strings."""
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()]+', text)
    stack, cur = [], []
    for tok in tokens:
        if tok == "(":
            stack.append(cur)
            cur = []
        elif tok == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(tok[1:-1].replace('\\"', '"') if tok.startswith('"') else tok)
    return cur[0]


def kids(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def val(node, key, default=""):
    k = kids(node, key)
    return k[0][1] if k and len(k[0]) > 1 else default


def netlist():
    """Components and nets from `kicad-cli sch export netlist` (KiCad's S-expression netlist)."""
    out = HW / "stepper-ble.net"
    subprocess.run(["kicad-cli", "sch", "export", "netlist", str(SCH), "-o", str(out)], check=True,
                   capture_output=True)
    tree = sexpr(out.read_text(encoding="utf-8"))
    out.unlink()
    comps = {}
    for comp in kids(kids(tree, "components")[0], "comp"):
        fields = {val(f, "name"): (f[2] if len(f) > 2 and isinstance(f[2], str) else "")
                  for f in kids(kids(comp, "fields")[0], "field")} if kids(comp, "fields") else {}
        props = {val(p, "name"): val(p, "value") for p in kids(comp, "property")}
        sheet = kids(comp, "sheetpath")
        comps[val(comp, "ref")] = dict(
            value=val(comp, "value"), footprint=val(comp, "footprint"), fields=fields,
            path=(val(sheet[0], "tstamps") if sheet else "/") + val(comp, "tstamps"),
            dnp="dnp" in props, in_bom="exclude_from_bom" not in props)
    nets = {}
    for net in kids(kids(tree, "nets")[0], "net"):
        for node in kids(net, "node"):
            nets[(val(node, "ref"), val(node, "pin"))] = val(net, "name")
    return comps, nets


def load_fp(fpid):
    lib, name = fpid.split(":", 1)
    d = FP_DIRS.get(lib, SYSTEM_FP / f"{lib}.pretty")
    fp = pcbnew.FootprintLoad(str(d), name)
    if fp is None:
        sys.exit(f"footprint {fpid} not found in {d}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def net_of(board, name, cache):
    if name not in cache:
        n = board.FindNet(name)
        if n is None:
            n = pcbnew.NETINFO_ITEM(board, name)
            board.Add(n)
        cache[name] = n
    return cache[name]


def sync(board, comps, nets, fp, ref):
    c = comps[ref]
    fp.SetReference(ref)
    fp.SetValue(c["value"])
    fp.SetPath(pcbnew.KIID_PATH(c["path"]))
    for k, v in c["fields"].items():
        if k not in ("Footprint", "Datasheet", "Description"):
            fp.SetField(k, v)
    fp.SetDNP(c["dnp"])
    attrs = fp.GetAttributes()
    attrs = attrs & ~pcbnew.FP_EXCLUDE_FROM_BOM if c["in_bom"] else attrs | pcbnew.FP_EXCLUDE_FROM_BOM
    fp.SetAttributes(attrs)
    cache = {}
    for pad in fp.Pads():
        name = nets.get((ref, pad.GetNumber()))
        if name:
            pad.SetNet(net_of(board, name, cache))
        else:
            pad.SetNetCode(0)


def place(fp, x, y, rot, side, board):
    if side == "B":
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))


def park(fp, i):
    fp.SetPosition(pcbnew.VECTOR2I(mm(PARK_X + (i % 8) * 8.0), mm(Y0 + (i // 8) * 8.0)))


def outline(board):
    pts = [(X0, Y0), (X0 + W, Y0), (X0 + W, Y0 + H), (X0, Y0 + H)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        s.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1])))
        s.SetEnd(pcbnew.VECTOR2I(mm(b[0]), mm(b[1])))
        board.Add(s)


def cmd_create():
    if PCB.exists():
        sys.exit(f"{PCB} exists: use update, or delete it first")
    comps, nets = netlist()
    board = pcbnew.NewBoard(str(PCB))
    board.SetCopperLayerCount(4)
    outline(board)
    parked = 0
    for ref in sorted(comps, key=lambda r: (re.sub(r"\d+$", "", r), int(re.search(r"\d+$", r).group()))):
        fp = load_fp(comps[ref]["footprint"])
        board.Add(fp)
        sync(board, comps, nets, fp, ref)
        if ref in ANCHORS:
            place(fp, *ANCHORS[ref], board)
            fp.SetLocked(True)
        else:
            park(fp, parked)
            parked += 1
    board.Save(str(PCB))
    print(f"created {PCB.name}: {len(comps)} parts, {len(ANCHORS)} anchors locked, {parked} parked")


def cmd_update():
    comps, nets = netlist()
    board = pcbnew.LoadBoard(str(PCB))
    have = {fp.GetReference(): fp for fp in board.GetFootprints()}
    added, removed = [], []
    for ref, fp in have.items():
        if ref not in comps:
            board.Remove(fp)
            removed.append(ref)
    parked = 0
    for ref in comps:
        fp = have.get(ref)
        if fp is None or str(fp.GetFPID().GetUniStringLibId()) != comps[ref]["footprint"]:
            new = load_fp(comps[ref]["footprint"])
            if fp is not None:
                new.SetPosition(fp.GetPosition())
                new.SetOrientation(fp.GetOrientation())
                new.SetLocked(fp.IsLocked())
                board.Remove(fp)
            else:
                park(new, parked)
                parked += 1
                added.append(ref)
            board.Add(new)
            fp = new
        sync(board, comps, nets, fp, ref)
    board.Save(str(PCB))
    print(f"updated {PCB.name}: {len(comps)} parts; added {added or 'none'}; removed {removed or 'none'}")


def cmd_anchors():
    board = pcbnew.LoadBoard(str(PCB))
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for ref, at in ANCHORS.items():
        fps[ref].SetLocked(False)
        place(fps[ref], *at, board)
        fps[ref].SetLocked(True)
    board.Save(str(PCB))
    print(f"anchors: {len(ANCHORS)} placed and locked")


ZONE_NS = __import__("uuid").UUID("0d6c5b8e-7b1f-4e43-9a55-1c8f3a8a2f10")
COPPER = '"F.Cu" "B.Cu" "In1.Cu" "In2.Cu"'


def zone_text(name, rect, net=None, layer=None, priority=0, keepout=None):
    """A KiCad 10 zone as text (the format pcbnew writes). keepout: None, or True to also forbid footprints."""
    import uuid
    x0, y0, x1, y1 = (round(v, 3) for v in rect)
    head = (f'\t\t(net "{net}")\n\t\t(layer "{layer}")\n' if net else f'\t\t(layers {COPPER})\n')
    body = (f'\t\t(uuid "{uuid.uuid5(ZONE_NS, name)}")\n' + (f'\t\t(name "{name}")\n' if keepout is not None else "")
            + '\t\t(hatch edge 0.5)\n' + (f'\t\t(priority {priority})\n' if priority else ""))
    if keepout is not None:
        rules = ('\t\t(connect_pads\n\t\t\t(clearance 0)\n\t\t)\n\t\t(min_thickness 0.25)\n\t\t(keepout\n'
                 '\t\t\t(tracks not_allowed)\n\t\t\t(vias not_allowed)\n\t\t\t(pads allowed)\n'
                 '\t\t\t(copperpour not_allowed)\n'
                 f'\t\t\t(footprints {"not_allowed" if keepout else "allowed"})\n\t\t)\n'
                 '\t\t(fill\n\t\t\t(thermal_gap 0.5)\n\t\t\t(thermal_bridge_width 0.5)\n\t\t)\n')
    else:
        rules = ('\t\t(connect_pads\n\t\t\t(clearance 0.25)\n\t\t)\n\t\t(min_thickness 0.2)\n'
                 '\t\t(fill yes\n\t\t\t(thermal_gap 0.5)\n\t\t\t(thermal_bridge_width 0.5)\n\t\t)\n')
    pts = f"(xy {x0} {y0}) (xy {x1} {y0}) (xy {x1} {y1}) (xy {x0} {y1})"
    return f"\t(zone\n{head}{body}{rules}\t\t(polygon\n\t\t\t(pts\n\t\t\t\t{pts}\n\t\t\t)\n\t\t)\n\t)\n"


def strip_zones(path):
    """Remove every top-level (zone ...) block from the board file, as text."""
    text = path.read_text(encoding="utf-8")
    out, i = [], 0
    while (j := text.find("\n\t(zone\n", i - 1 if i else 0)) >= 0:
        out.append(text[i:j + 1])
        depth, k, in_str = 0, j + 1, False
        while True:
            ch = text[k]
            if in_str:
                in_str = not (ch == '"' and text[k - 1] != "\\")
            elif ch == '"':
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        i = k + 2
    out.append(text[i:])
    path.write_text("".join(out), encoding="utf-8")


def cmd_zones():
    """Zones as text (pcbnew's zone calls crash from Python in KiCad 10.0.8), filled by kicad-cli."""
    board = pcbnew.LoadBoard(str(PCB))
    classes = json.loads(PRO.read_text())["net_settings"].get("netclass_assignments", {})
    inner = (X0 + 0.3, Y0 + 0.3, X0 + W - 0.3, Y0 + H - 0.3)
    zones = [zone_text("GND In1", inner, net="GND", layer="In1.Cu"),
             zone_text("GND In2", inner, net="GND", layer="In2.Cu"),
             zone_text("antenna keep-out", ANTENNA_KEEPOUT, keepout=False),
             zone_text("antenna: no parts", ANTENNA_NO_PARTS, keepout=True)]
    poured = []
    for net, cls in sorted(classes.items()):
        cls = cls[0] if isinstance(cls, list) else cls
        m = POUR_CLASSES.match(cls)
        if not m or float(m.group(2).replace("p", ".")) < 3.0:
            continue
        pads = [p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname() == net]
        if not pads:
            continue
        bb = pads[0].GetBoundingBox()
        for p in pads[1:]:
            bb.Merge(p.GetBoundingBox())
        r = (max(pcbnew.ToMM(bb.GetLeft()) - 1.0, inner[0]), max(pcbnew.ToMM(bb.GetTop()) - 1.0, inner[1]),
             min(pcbnew.ToMM(bb.GetRight()) + 1.0, inner[2]), min(pcbnew.ToMM(bb.GetBottom()) + 1.0, inner[3]))
        zones.append(zone_text(f"pour {net}", r, net=net, layer="B.Cu", priority=1))
        poured.append(net)
    strip_zones(PCB)
    text = PCB.read_text(encoding="utf-8").rstrip()
    assert text.endswith(")")
    PCB.write_text(text[:-1] + "".join(zones) + ")\n", encoding="utf-8")
    r = subprocess.run(["kicad-cli", "pcb", "drc", "--refill-zones", "--save-board", str(PCB), "-o", str(HW / "drc.rpt")],
                       capture_output=True, text=True)
    (HW / "drc.rpt").unlink(missing_ok=True)
    print(f"zones: GND on In1/In2, antenna keep-outs, B.Cu pours for {', '.join(poured) or 'none'}; "
          f"filled by kicad-cli (exit {r.returncode})")


if __name__ == "__main__":
    cmds = {"create": cmd_create, "update": cmd_update, "anchors": cmd_anchors, "zones": cmd_zones}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
