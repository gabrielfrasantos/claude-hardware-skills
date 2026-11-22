#!/usr/bin/python3
"""Build and update the stepper-ble board from KiCad's netlist, headless (KiCad 10's pcbnew Python module).

    /usr/bin/python3 scripts/make_board.py build     create or update hardware/stepper-ble/stepper-ble.kicad_pcb
    /usr/bin/python3 scripts/make_board.py place     place the parts (anchors locked, support parts at their pins)

Why it exists: kicad-cli 10 has no *Update PCB from Schematic* (README "Status and limits"), and the plugin's tools
are text-based (docs/design.md D22), so this example carries the one pcbnew step itself (D-024).

build   exports the netlist with kicad-cli, then for every component: adds its footprint (KiCad's libraries, or the
        project library stepper-ble.pretty) or keeps the placed one, sets value, fields, schematic path, DNP and BOM
        flags, and the net, pin function and pin type of every pad; removes footprints no longer in the schematic.
        It writes the outline (80 x 60 mm), the M3 holes' positions, the JLC04161H-7628 stack-up, the ground
        planes, the required pours and the antenna keep-outs. Parts new to the board are parked below the outline.
place   puts the anchors (connectors, holes, fiducials, antenna, MCU, driver, FETs, buck, USB) at fixed positions
        and locks them, then places every support part at the pin it serves (pcb-placement §1), see PLACEMENT.
The .kicad_pro is kept byte for byte: pcbnew rewrites it on save, the net classes live there (netclasses.py).
"""
import math
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import pcbnew

ROOT = pathlib.Path(__file__).resolve().parent.parent
HW = ROOT / "hardware" / "stepper-ble"
PCB = HW / "stepper-ble.kicad_pcb"
PRO = HW / "stepper-ble.kicad_pro"
SCH = HW / "stepper-ble.kicad_sch"
FP_DIR = pathlib.Path(os.environ.get("KICAD10_FOOTPRINT_DIR", "/usr/share/kicad/footprints"))
PROJECT_LIB = "stepper-ble"

X0, Y0, W, H = 100.0, 100.0, 80.0, 60.0
mm = pcbnew.FromMM


def sexpr(text):
    tokens = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    stack, cur = [], []
    for t in tokens:
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1].replace('\\"', '"') if t.startswith('"') else t)
    return cur[0]


def kids(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def kid(node, key):
    k = kids(node, key)
    return k[0] if k else None


def val(node, key, default=""):
    k = kid(node, key)
    return k[1] if k and len(k) > 1 else default


def read_netlist():
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "board.net"
        subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(SCH)],
                       check=True, capture_output=True)
        tree = sexpr(out.read_text(encoding="utf-8"))
    comps = {}
    for c in kids(kid(tree, "components"), "comp"):
        props = {val(p, "name"): val(p, "value") for p in kids(c, "property")}
        fields = {f[1][1]: (f[2] if len(f) > 2 else "") for f in kids(kid(c, "fields") or [], "field")}
        sp = kid(c, "sheetpath")
        comps[val(c, "ref")] = dict(
            value=val(c, "value"), footprint=val(c, "footprint"), fields=fields, props=props,
            path=val(sp, "tstamps") + val(c, "tstamps"), sheetname=val(sp, "names"),
            sheetfile=props.get("Sheetfile", ""), dnp="dnp" in props, in_bom="exclude_from_bom" not in props)
    nets = []
    for n in kids(kid(tree, "nets"), "net"):
        nodes = [(val(d, "ref"), val(d, "pin"), val(d, "pinfunction"), val(d, "pintype")) for d in kids(n, "node")]
        nets.append((val(n, "name"), nodes))
    return comps, nets


def load_footprint(fpid):
    lib, name = fpid.split(":", 1)
    folder = HW / f"{PROJECT_LIB}.pretty" if lib == PROJECT_LIB else FP_DIR / f"{lib}.pretty"
    fp = pcbnew.FootprintLoad(str(folder), name)
    if fp is None:
        sys.exit(f"footprint {fpid} not found in {folder}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def fpid_text(fp):
    lib_id = fp.GetFPID()
    return f"{lib_id.GetLibNickname()}:{lib_id.GetLibItemName()}"


def set_field(fp, name, value):
    existed = fp.HasField(name)
    fp.SetField(name, value)
    if not existed:
        f = fp.GetField(name)
        f.SetLayer(pcbnew.F_Fab)
        f.SetVisible(False)


def stackup(board):
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(4)
    board.SetCopperLayerCount(4)
    ds.SetBoardThickness(mm(1.6))


STACKUP = [
    ("F.SilkS", "Top Silk Screen", None), ("F.Paste", "Top Solder Paste", None),
    ("F.Mask", "Top Solder Mask", 0.01), ("F.Cu", "copper", 0.035),
    ("dielectric 1", "prepreg", 0.2104), ("In1.Cu", "copper", 0.0152),
    ("dielectric 2", "core", 1.065), ("In2.Cu", "copper", 0.0152),
    ("dielectric 3", "prepreg", 0.2104), ("B.Cu", "copper", 0.035),
    ("B.Mask", "Bottom Solder Mask", 0.01), ("B.Paste", "Bottom Solder Paste", None),
    ("B.SilkS", "Bottom Silk Screen", None),
]


def write_stackup(path):
    """JLC04161H-7628 (JLCPCB 4-layer, 1.6 mm): 35 um outer and 15.2 um inner copper, 0.2104 mm 7628 prepreg,
    1.065 mm core (pcb-design-rules [JLC-STACK]); layer roles SIG/GND/GND/SIG (D-010). pcbnew's SWIG module does not
    expose the stack-up list, so the block is written into the saved file."""
    rows = []
    for name, kind, t in STACKUP:
        extra = f" (thickness {t})" if t is not None else ""
        if kind in ("prepreg", "core"):
            extra += ' (material "FR4") (epsilon_r 4.4) (loss_tangent 0.02)'
        rows.append(f'\t\t\t(layer "{name}" (type "{kind}"){extra})')
    block = "\t\t(stackup\n" + "\n".join(rows) + '\n\t\t\t(copper_finish "HAL lead-free")\n' \
        "\t\t\t(dielectric_constraints no)\n\t\t)\n"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\t\t\(stackup\n.*?\n\t\t\)\n", "", text, flags=re.S)
    text = text.replace("\t(setup\n", "\t(setup\n" + block, 1)
    path.write_text(text, encoding="utf-8")


def outline(board):
    for d in [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]:
        board.Delete(d)
    r = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_RECT)
    r.SetStart(pcbnew.VECTOR2I(mm(X0), mm(Y0)))
    r.SetEnd(pcbnew.VECTOR2I(mm(X0 + W), mm(Y0 + H)))
    r.SetLayer(pcbnew.Edge_Cuts)
    r.SetWidth(mm(0.1))
    board.Add(r)


def polygon(zone, pts):
    sp = pcbnew.SHAPE_POLY_SET()
    sp.NewOutline()
    for x, y in pts:
        sp.Append(mm(x), mm(y))
    sp.thisown = False
    zone.SetOutline(sp)


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


ANT_KEEPOUT = rect(151.4, 100.0, 169.0, 106.8)


def zones(board, netmap):
    """Ground planes on both inner layers (D-010), the pours pcb-copper requires (PWR_3A nets), the antenna's
    all-layer copper keep-out and the footprint keep-outs beside it (rf-layout §4, pcb-placement §1)."""
    for z in list(board.Zones()):
        board.Delete(z)
    inset = 0.5
    full = rect(X0 + inset, Y0 + inset, X0 + W - inset, Y0 + H - inset)

    def pour(name, layer, pts, net, prio=0, thermal=True):
        z = pcbnew.ZONE(board)
        z.SetZoneName(name)
        z.SetLayer(layer)
        z.SetNet(netmap[net] if net in netmap else next(v for k, v in netmap.items() if k.rsplit("/", 1)[-1] == net))
        z.SetAssignedPriority(prio)
        z.SetMinThickness(mm(0.2))
        z.SetLocalClearance(mm(0.2))
        z.SetThermalReliefGap(mm(0.3))
        z.SetThermalReliefSpokeWidth(mm(0.5))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL if thermal else pcbnew.ZONE_CONNECTION_FULL)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        polygon(z, pts)
        board.Add(z)
        return z

    pour("GND_In1", pcbnew.In1_Cu, full, "GND", thermal=False)
    pour("GND_In2", pcbnew.In2_Cu, full, "GND", thermal=False)
    for name, net, pts in POURS:
        pour(name, pcbnew.F_Cu, pts, net, prio=1, thermal=False)

    def keepout(name, pts, footprints, layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")):
        z = pcbnew.ZONE(board)
        z.SetZoneName(name)
        z.SetIsRuleArea(True)
        ls = pcbnew.LSET()
        for layer in layers:
            ls.AddLayer(board.GetLayerID(layer))
        z.SetLayerSet(ls)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(footprints)
        polygon(z, pts)
        board.Add(z)

    keepout("ANT_copper", ANT_KEEPOUT, False)
    for i, pts in enumerate(ANT_FOOTPRINT_KEEPOUTS):
        keepout(f"ANT_parts_{i}", pts, True, layers=("F.Cu", "B.Cu"))


POURS = [  # PWR_3A nets: pcb-copper requires a pour (D21); polygons follow the placement
    ("VIN_RAW", "VIN_RAW", rect(103.1, 139.0, 115.0, 142.9)),
    ("VIN_N", "VIN_N", rect(103.1, 144.2, 116.8, 148.6)),
    ("VM", "VM", [(112.5, 128.2), (143.5, 128.2), (143.5, 135.2), (124.6, 135.2), (124.6, 142.7), (117.3, 142.7),
                  (117.3, 135.2), (112.5, 135.2)]),
]
ANT_FOOTPRINT_KEEPOUTS = [rect(149.0, 100.5, 152.2, 106.8), rect(168.2, 100.5, 170.5, 106.8)]


def keep_project_file(fn):
    def wrapped(*a, **k):
        saved = PRO.read_bytes() if PRO.exists() else None
        try:
            return fn(*a, **k)
        finally:
            if saved is not None:
                PRO.write_bytes(saved)
    return wrapped


@keep_project_file
def build():
    comps, nets = read_netlist()
    board = pcbnew.LoadBoard(str(PCB)) if PCB.exists() else pcbnew.NewBoard(str(PCB))
    stackup(board)
    outline(board)
    netmap = {"": board.FindNet(0)}
    for name, _ in nets:
        n = board.FindNet(name)
        if n is None:
            n = pcbnew.NETINFO_ITEM(board, name)
            board.Add(n)
        netmap[name] = n
    placed = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for ref, fp in list(placed.items()):
        if ref not in comps:
            del placed[ref]
            board.Delete(fp)
    park = 0
    for ref in sorted(comps, key=lambda r: (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r) or 0))):
        c = comps[ref]
        fp = placed.get(ref)
        if fp is not None and fpid_text(fp) != c["footprint"]:
            pos, rot, locked = fp.GetPosition(), fp.GetOrientationDegrees(), fp.IsLocked()
            board.Delete(fp)
            fp = load_footprint(c["footprint"])
            board.Add(fp)
            fp.SetPosition(pos)
            fp.SetOrientationDegrees(rot)
            fp.SetLocked(locked)
        elif fp is None:
            fp = load_footprint(c["footprint"])
            board.Add(fp)
            fp.SetPosition(pcbnew.VECTOR2I(mm(X0 + 4 + (park % 25) * 3.2), mm(Y0 + H + 8 + (park // 25) * 4)))
            park += 1
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        for k, v in c["fields"].items():
            if k not in ("Footprint", "Reference", "Value"):
                set_field(fp, k, v)
        fp.SetPath(pcbnew.KIID_PATH(c["path"]))
        fp.SetSheetname(c["sheetname"])
        fp.SetSheetfile(c["sheetfile"])
        fp.SetDNP(c["dnp"])
        fp.SetExcludedFromBOM(not c["in_bom"] or c["dnp"])
        fp.SetExcludedFromPosFiles(not c["in_bom"] or c["dnp"])
        for pad in fp.Pads():
            pad.SetNet(netmap[""])
            pad.SetPinFunction("")
            pad.SetPinType("")
        placed[ref] = fp
    for name, nodes in nets:
        for ref, pin, function, ptype in nodes:
            for pad in placed[ref].Pads():
                if pad.GetNumber() == pin:
                    pad.SetNet(netmap[name])
                    pad.SetPinFunction(function)
                    pad.SetPinType(ptype)
    zones(board, netmap)
    pcbnew.SaveBoard(str(PCB), board)
    write_stackup(PCB)
    print(f"{PCB.relative_to(ROOT)}: {len(placed)} footprints, {len(nets)} nets, {park} new parked")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        build()
    elif cmd == "place":
        place()
    else:
        sys.exit(__doc__)


ANCHORS = {
    "H701": (104.0, 104.0, 0), "H702": (176.0, 104.0, 0), "H703": (104.0, 156.0, 0), "H704": (176.0, 156.0, 0),
    "J301": (105.71, 111.5, 270), "J101": (105.71, 140.97, 270),
    "Q301": (116.0, 129.0, 270), "Q302": (116.0, 118.0, 270), "Q303": (124.0, 129.0, 270), "Q304": (124.0, 118.0, 270),
    "Q305": (132.0, 129.0, 270), "Q306": (132.0, 118.0, 270), "Q307": (140.0, 129.0, 270), "Q308": (140.0, 118.0, 270),
    "R301": (120.0, 107.5, 90), "R302": (136.0, 107.5, 90), "C301": (126.0, 139.5, 0),
    "U301": (148.0, 120.0, 180), "U401": (166.0, 125.0, 180), "AE501": (164.75, 106.0, 0),
    "U201": (133.0, 151.0, 0), "L201": (141.5, 151.0, 0), "J601": (160.5, 155.6, 0),
    "FID701": (111.0, 103.5, 0), "FID702": (176.5, 121.0, 0), "FID703": (146.0, 156.4, 0),
}
FIXED = {
    "F101": (116.2, 140.97, 0), "D101": (116.2, 136.9, 180), "Q101": (116.0, 146.6, 180),
    "C303": (120.0, 129.2, 90), "C304": (128.0, 129.2, 90), "C305": (136.0, 129.2, 90),
    "TH301": (128.0, 123.5, 90),
    "FL501": (165.0, 119.6, 0), "R501": (164.75, 110.6, 90), "C501": (166.1, 113.2, 0), "C502": (166.1, 108.4, 0),
    "U601": (160.5, 146.6, 0), "U202": (151.0, 144.6, 0), "D201": (149.2, 151.2, 90), "D202": (155.4, 146.2, 90),
    "C202": (125.6, 150.37, 180), "C201": (124.6, 147.0, 180),
    "C205": (145.6, 149.4, 90), "C206": (145.6, 152.8, 90),
    "D701": (177.2, 138.0, 0), "D702": (177.2, 142.0, 0), "SW701": (172.6, 148.4, 0),
}
ATTACH = [  # (part, IC, IC pad): the part goes radially out from that pad, nearest legal spot first
    ("C408", "U401", "23"), ("C407", "U401", "23"), ("C401", "U401", "20"), ("C402", "U401", "35"),
    ("C409", "U401", "34"), ("C403", "U401", "48"), ("C406", "U401", "40"), ("C405", "U401", "1"),
    ("C404", "U401", "48"), ("C412", "U401", "31"), ("L401", "U401", "33"), ("L402", "L401", "SMPS_MID"),
    ("Y402", "U401", "2"), ("C413", "Y402", "1"), ("C414", "Y402", "2"), ("Y401", "U401", "25"),
    ("C411", "U401", "8"), ("C410", "U401", "8"), ("R401", "C410", "VDDA"), ("C415", "U401", "7"),
    ("R402", "U401", "4"),
    ("C302", "U301", "4"), ("C306", "U301", "3"), ("C307", "U301", "1"), ("C308", "U301", "6"),
    ("C309", "U301", "7"), ("R303", "U301", "8"), ("R304", "U301", "9"), ("R305", "U301", "17"),
    ("R306", "U301", "18"), ("R307", "U301", "19"), ("C310", "U301", "20"),
    ("NT301", "R301", "1"), ("NT302", "R301", "2"), ("NT303", "R302", "1"), ("NT304", "R302", "2"),
    ("R101", "Q101", "4"), ("D102", "Q101", "4"),
    ("R201", "U201", "3"), ("R202", "U201", "3"),
    ("C203", "U201", "6"), ("C204", "U201", "7"), ("R204", "U201", "5"), ("R203", "U201", "5"),
    ("C207", "U202", "1"), ("C208", "U202", "5"), ("C209", "D201", "1"),
    ("C602", "U601", "5"), ("C601", "J601", "A4"), ("R601", "J601", "A5"), ("R602", "J601", "B5"),
    ("R102", "U401", "fn:VM_SENSE:28"), ("R103", "R102", "VM_SENSE"), ("R403", "U401", "fn:NTC_SENSE:29"),
    ("J701", "U401", "fn:SWCLK:41"), ("R703", "SW701", "1"), ("R701", "D701", "2"), ("R702", "D702", "2"),
]
GAP = 1.4           # courtyard to courtyard, mm: leaves the ~0.9 mm lane for a 1 mm reference (pcb-placement §1)


def at(fp, x, y, rot):
    fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    fp.SetOrientationDegrees(rot)


def court(fp):
    c = fp.GetCourtyard(pcbnew.F_CrtYd)
    b = c.BBox() if c.OutlineCount() else fp.GetBoundingBox(False)
    return (pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()), pcbnew.ToMM(b.GetBottom()))


def hit(a, b, gap):
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


def xy(item):
    p = item.GetPosition()
    return pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)


PINMAP = ROOT / "pin-data" / "pinmap.txt"


def pinmap():
    out = {}
    if PINMAP.exists():
        for line in PINMAP.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                cols = line.split()
                out[cols[0]] = cols[2]
    return out


def target(fps, ic, key):
    """The pad of `ic` named by number, by function ("fn:NAME:default pad", from the pin map once it exists), or
    the first pad on the net `key`."""
    if key.startswith("fn:"):
        _, name, default = key.split(":")
        key = pinmap().get(name, default)
    pads = [p for p in fps[ic].Pads() if p.GetNumber() == key] or \
        [p for p in fps[ic].Pads() if p.GetNetname().rsplit("/", 1)[-1] == key]
    return pads[0]


def edge_mm(fp):
    """MLCCs and crystals keep 3 mm from the edge (depaneling stress, pcb-placement §4.1 [JLC-SMT]); others 0.5 mm."""
    return 2.8 if fp.GetReference()[0] in "CY" and not fp.GetReference().startswith("C301") else 0.5


def attach(fp, pad, ic_fp, taken, blocked, gap=None):
    """Put `fp` at `pad` of `ic_fp`: its pad on the same net nearest the pin, axis radial (else tangential),
    the first spot that clears every placed courtyard by GAP, inside the board and outside the keep-outs."""
    px, py = xy(pad)
    cx, cy = xy(ic_fp)
    dx, dy = px - cx, py - cy
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        dx = 1.0
    n = (math.copysign(1, dx), 0.0) if abs(dx) >= abs(dy) else (0.0, math.copysign(1, dy))
    t = (-n[1], n[0])
    net = pad.GetNetname()
    own = [p for p in fp.Pads() if p.GetNetname() == net] or list(fp.Pads())
    if gap is None:
        for g in (GAP, 1.0, 0.6):
            try:
                return attach(fp, pad, ic_fp, taken, blocked, g)
            except LookupError:
                continue
        raise SystemExit(f"{fp.GetReference()}: no spot near {ic_fp.GetReference()} pad {pad.GetNumber()}")
    for dist in [0.8 + 0.25 * i for i in range(40)]:
        for lat in [0.0] + [s * 0.25 * k for k in range(1, 24) for s in (1, -1)]:
            for rot in (0, 90, 180, 270):
                at(fp, 0, 0, rot)
                inner = own[0]
                ix, iy = xy(inner)
                others = [p for p in fp.Pads() if p is not inner and p.GetNumber()]
                if others:
                    ox, oy = xy(others[0])
                    v = (ox - ix, oy - iy)
                    radial = v[0] * n[0] + v[1] * n[1]
                    if radial < -1e-6 or (abs(radial) < 1e-6 and lat == 0.0 and dist < 1.6):
                        continue
                tx = px + n[0] * dist + t[0] * lat - ix
                ty = py + n[1] * dist + t[1] * lat - iy
                at(fp, round(tx * 20) / 20, round(ty * 20) / 20, rot)
                c = court(fp)
                e = edge_mm(fp)
                if c[0] < X0 + e or c[1] < Y0 + e or c[2] > X0 + W - e or c[3] > Y0 + H - e:
                    continue
                if any(hit(c, k, 0.0) for k in blocked) or any(hit(c, k, gap) for k in taken):
                    continue
                return c
    raise LookupError(fp.GetReference())


@keep_project_file
def place():
    board = pcbnew.LoadBoard(str(PCB))
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    taken = []
    for ref, (x, y, rot) in ANCHORS.items():
        fps[ref].SetLocked(False)
        at(fps[ref], x, y, rot)
        fps[ref].SetLocked(True)
        taken.append(court(fps[ref]))
    for ref, (x, y, rot) in FIXED.items():
        fps[ref].SetLocked(False)
        at(fps[ref], x, y, rot)
        taken.append(court(fps[ref]))
    blocked = [(min(p[0] for p in k), min(p[1] for p in k), max(p[0] for p in k), max(p[1] for p in k))
               for k in [ANT_KEEPOUT] + ANT_FOOTPRINT_KEEPOUTS]
    for ref, ic, key in ATTACH:
        fps[ref].SetLocked(False)
        taken.append(attach(fps[ref], target(fps, ic, key), fps[ic], taken, blocked))
    done = set(ANCHORS) | set(FIXED) | {r for r, _, _ in ATTACH}
    left = sorted(set(fps) - done)
    if left:
        print("not placed:", " ".join(left))
    if "--dump" in sys.argv:
        for ref in sys.argv[sys.argv.index("--dump") + 1].split(","):
            for pad in fps[ref].Pads():
                print(ref, pad.GetNumber(), pad.GetNetname(), *[round(v, 2) for v in xy(pad)])
    pcbnew.SaveBoard(str(PCB), board)
    write_stackup(PCB)
    print(f"placed {len(done)} footprints")


if __name__ == "__main__":
    main()
