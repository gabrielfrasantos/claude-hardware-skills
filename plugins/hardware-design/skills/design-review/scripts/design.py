"""The design under review as one model: parts, pins (number, name, electrical type, net, position) and nets.

Two sources, same model:
  from_board(board, schematic=None)  the .kicad_pcb (connectivity, positions, footprint properties) plus, when given,
                                     the schematic sheets' embedded symbols for pin names and types the board lacks
                                     and for DNP flags. No KiCad needed.
  from_netlist(net_file)             a KiCad netlist (`kicad-cli sch export netlist --format kicadsexpr`): every pin
                                     with its name and type, before there is a board. No positions.

Net voltages come from the net's name (+3V3, 5V, 12V_IN, VBUS), from a `_<V>V` net-class suffix, or from the
caller's overrides; ground nets are 0 V.
"""

import glob
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pcb-design-rules", "scripts"))
import pcb_rules as R  # noqa: E402

GROUND = re.compile(r"^(GND|AGND|DGND|PGND|SGND|GNDA|GNDD|GNDPWR|GNDREF|VSS|VSSA|GND_\w+|\w+_GND|EARTH|0V)$", re.I)
VOLT_NAME = re.compile(r"(?<![0-9A-Z.])\+?(\d{1,3})V(\d{1,2})?(?![0-9A-Z])", re.I)
VOLT_DEC = re.compile(r"(?<![0-9A-Z.])\+?(\d{1,3}\.\d{1,3})V(?![0-9A-Z])", re.I)
SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "R": 1.0}


def base(net):
    return (net or "").rsplit("/", 1)[-1]


def is_ground(net):
    return bool(net) and bool(GROUND.match(base(net)))


def parse_value(text, unit=""):
    """'4k7' -> 4700, '100nF' -> 1e-7, '2.2uF' -> 2.2e-6, '0R' -> 0, '10' -> 10. None when not a value."""
    if not text:
        return None
    t = str(text).strip().replace(" ", "")
    if unit:
        t = re.sub(unit + r"$", "", t, flags=re.I)
    m = re.match(r"^(\d+)([pnuµmkKMGR])(\d+)$", t)              # 4k7, 2u2, 0R1
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * SI[m.group(2)]
    m = re.match(r"^(\d+(?:\.\d+)?)([pnuµmkKMGR]?)", t)
    if not m:
        return None
    return float(m.group(1)) * (SI[m.group(2)] if m.group(2) else 1.0)


def rated_voltage(part):
    """A voltage rating from the value or a rating field ('100nF 50V', Voltage=25V); None if not stated."""
    texts = [part["value"]] + [v for k, v in part["fields"].items()
                               if re.search(r"volt|rating|^v(r|rated|max)?$", k, re.I)]
    for t in texts:
        m = re.search(r"(?<![0-9A-Z])(\d+(?:\.\d+)?)\s*V(?:DC)?(?![A-Z0-9])", str(t), re.I)
        if m:
            return float(m.group(1))
    return None


def name_voltage(net):
    """Voltage implied by a power net's name: +3V3 -> 3.3, 5V -> 5, 12V_IN -> 12, +1.8V -> 1.8, VBUS -> 5."""
    b = base(net).upper()
    if is_ground(net):
        return 0.0
    if b in ("VBUS", "USB_VBUS"):
        return 5.0
    m = VOLT_DEC.search(b)
    if m:
        return float(m.group(1))
    m = VOLT_NAME.search(b)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}") if m.group(2) else float(m.group(1))
    return None


class Design:
    def __init__(self, source):
        self.source = source
        self.parts = {}
        self.nets = {}
        self.overrides = {}
        self.classes = None            # net -> net-class name (from the project), when known

    # -------------------------------------------------------------------------------------------- building
    def add_part(self, ref, value="", footprint="", lib_id="", fields=None, dnp=False, x=None, y=None, side="F"):
        self.parts[ref] = dict(ref=ref, value=value or "", footprint=footprint or "", lib_id=lib_id or "",
                               fields=dict(fields or {}), dnp=dnp, x=x, y=y, side=side, pins={})
        return self.parts[ref]

    def add_pin(self, ref, num, net="", name="", ptype="", x=None, y=None):
        part = self.parts[ref]
        net = "" if (not net or net.startswith("unconnected-")) else net
        pin = part["pins"].get(num)
        if pin is None:
            pin = part["pins"][num] = dict(ref=ref, num=num, name=name or "", type=ptype or "", net=net, x=x, y=y)
            if net:
                self.nets.setdefault(net, []).append(pin)
        else:                                            # a pad number used twice (exposed pad + thermal vias)
            pin["name"] = pin["name"] or name or ""
            pin["type"] = pin["type"] or ptype or ""
        return pin

    # -------------------------------------------------------------------------------------------- queries
    def has_types(self):
        return any(p["type"] for part in self.parts.values() for p in part["pins"].values())

    def has_positions(self):
        return any(p["x"] is not None for part in self.parts.values() for p in part["pins"].values())

    def voltage(self, net):
        if not net:
            return None
        if net in self.overrides:
            return self.overrides[net]
        if base(net) in self.overrides:
            return self.overrides[base(net)]
        if is_ground(net):
            return 0.0
        if self.classes:
            m = re.search(r"_(\d+(?:[.p]\d+)?)V$", self.classes(net) or "")
            if m:
                return float(m.group(1).replace("p", "."))
        return name_voltage(net)

    def kind(self, ref):
        m = re.match(r"^([A-Z]+)", ref)
        return m.group(1) if m else ""

    def others(self, pin):
        """The other pins on pin's net."""
        return [p for p in self.nets.get(pin["net"], []) if p is not pin] if pin["net"] else []

    def two_pin(self, part):
        """(net a, net b) of a two-terminal part, or None."""
        pins = [p for p in part["pins"].values()]
        return (pins[0]["net"], pins[1]["net"]) if len(pins) == 2 else None


# ------------------------------------------------------------------------------------------------ board
def _schematic_symbols(sch_root):
    """{ref: dict(pins={num: (name, type)}, fields, dnp)} from the symbols embedded in every sheet of the project."""
    folder = os.path.dirname(os.path.abspath(sch_root))
    libs, out = {}, {}
    for path in sorted(glob.glob(os.path.join(folder, "**", "*.kicad_sch"), recursive=True)):
        with open(path, encoding="utf-8") as f:
            root = R.parse_sexpr(f.read())
        ls = R.child(root, "lib_symbols")
        for sym in R.children(ls, "symbol") if ls else []:
            units = libs.setdefault(str(sym[1]), {})
            for sub in [sym] + R.children(sym, "symbol"):
                try:
                    unit = int(str(sub[1]).rsplit("_", 2)[-2]) if sub is not sym else 0
                except (ValueError, IndexError):
                    unit = 0
                for pin in R.children(sub, "pin"):
                    num, nm = R.child(pin, "number"), R.child(pin, "name")
                    if num and num[1]:
                        units.setdefault(unit, {})[str(num[1])] = (str(nm[1]) if nm else "", str(pin[1]))
        for s in R.children(root, "symbol"):
            lib_id = R.child(s, "lib_id")
            if not lib_id:
                continue
            props = {str(p[1]): str(p[2]) for p in R.children(s, "property") if len(p) > 2}
            refs = [str(r[1]) for inst in R.children(s, "instances") for proj in R.children(inst, "project")
                    for pth in R.children(proj, "path") for r in R.children(pth, "reference")] or [props.get("Reference", "")]
            unit = R.child(s, "unit")
            dnp = R.child(s, "dnp")
            for ref in refs:
                if not ref or ref.startswith("#"):
                    continue
                e = out.setdefault(ref, dict(lib_id=str(lib_id[1]), units=set(), fields=props,
                                             dnp=bool(dnp and dnp[1] == "yes")))
                e["units"].add(int(unit[1]) if unit else 1)
    for ref, e in out.items():
        units = libs.get(e["lib_id"], {})
        pins = dict(units.get(0, {}))
        for u in (e["units"] if len(units) > 1 else units):
            pins.update(units.get(u, {}))
        e["pins"] = pins
    return out


def from_board(board_path, schematic=None, pro=None):
    with open(board_path, encoding="utf-8") as f:
        text = f.read()
    root = R.parse_sexpr(text)
    d = Design(f"board {os.path.basename(board_path)}" + (f" + schematic {os.path.basename(schematic)}" if schematic else ""))
    syms = _schematic_symbols(schematic) if schematic else {}
    for fp in R.children(root, "footprint"):
        props = {str(p[1]): str(p[2]) for p in R.children(fp, "property") if len(p) > 2}
        ref = props.get("Reference", "")
        if not ref:
            continue
        fx, fy, rot = R.footprint_place(fp)
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        sym = syms.get(ref, {})
        attr = R.child(fp, "attr")
        dnp = sym.get("dnp", False) or bool(attr and "dnp" in [str(a) for a in attr[1:]])
        fields = {k: v for k, v in props.items() if k not in ("Reference", "Value", "Footprint")}
        for k, v in sym.get("fields", {}).items():
            fields.setdefault(k, v)
        d.add_part(ref, props.get("Value", ""), str(fp[1]), sym.get("lib_id", ""), fields, dnp, fx, fy,
                   str(R.child(fp, "layer")[1])[0])
        for pad in R.children(fp, "pad"):
            num = str(pad[1])
            if not num or (len(pad) > 2 and pad[2] == "np_thru_hole"):
                continue
            pat = R.child(pad, "at")
            dx, dy = float(pat[1]), float(pat[2])
            net = R.child(pad, "net")
            pf, pt = R.child(pad, "pinfunction"), R.child(pad, "pintype")
            name, ptype = (str(pf[1]) if pf else ""), (str(pt[1]) if pt else "")
            if num in sym.get("pins", {}):
                name = name or sym["pins"][num][0]
                ptype = ptype or sym["pins"][num][1]
            ptype = ptype.split("+")[0]                      # "passive+no_connect" -> passive
            d.add_pin(ref, num, str(net[1]) if net and len(net) > 1 else "", name, ptype,
                      fx + dx * c + dy * s, fy - dx * s + dy * c)
    if pro and os.path.exists(pro):
        sys.path.insert(0, os.path.join(HERE, "..", "..", "pcb-design-rules", "scripts"))
        import copper
        lookup, _ = copper.class_resolver(pro)
        d.classes = lookup
    return d


# ------------------------------------------------------------------------------------------------ netlist
def from_netlist(net_path):
    """A KiCad netlist in the S-expression format (kicad-cli sch export netlist --format kicadsexpr)."""
    with open(net_path, encoding="utf-8") as f:
        root = R.parse_sexpr(f.read())
    d = Design(f"netlist {os.path.basename(net_path)}")
    libparts = {}
    lp = R.child(root, "libparts")
    for part in R.children(lp, "libpart") if lp else []:
        lib, name = R.child(part, "lib"), R.child(part, "part")
        pins = R.child(part, "pins")
        libparts[(str(lib[1]) if lib else "", str(name[1]) if name else "")] = {
            str(R.child(p, "num")[1]): (str((R.child(p, "name") or ["", ""])[1]), str((R.child(p, "type") or ["", ""])[1]))
            for p in (R.children(pins, "pin") if pins else [])}
    comps = R.child(root, "components")
    pins_of = {}
    for comp in R.children(comps, "comp") if comps else []:
        ref = str(R.child(comp, "ref")[1])
        val = R.child(comp, "value")
        fpn = R.child(comp, "footprint")
        fields = {}
        fl = R.child(comp, "fields")
        for fld in R.children(fl, "field") if fl else []:
            nm = R.child(fld, "name")
            if nm and len(fld) > 2:
                fields[str(nm[1])] = str(fld[-1]) if not isinstance(fld[-1], list) else ""
        src = R.child(comp, "libsource")
        key = (str(R.child(src, "lib")[1]), str(R.child(src, "part")[1])) if src else ("", "")
        dnp = any(str((R.child(p, "name") or ["", ""])[1]) == "dnp" for p in R.children(comp, "property"))
        d.add_part(ref, str(val[1]) if val else "", str(fpn[1]) if fpn and len(fpn) > 1 else "",
                   f"{key[0]}:{key[1]}", fields, dnp)
        pins_of[ref] = libparts.get(key, {})
    nets = R.child(root, "nets")
    for net in R.children(nets, "net") if nets else []:
        name = str(R.child(net, "name")[1])
        for node in R.children(net, "node"):
            ref, num = str(R.child(node, "ref")[1]), str(R.child(node, "pin")[1])
            if ref not in d.parts:
                continue
            pf, pt = R.child(node, "pinfunction"), R.child(node, "pintype")
            lib_name, lib_type = pins_of.get(ref, {}).get(num, ("", ""))
            ptype = (str(pt[1]) if pt else "") or lib_type
            d.add_pin(ref, num, name, (str(pf[1]) if pf else "") or lib_name, ptype.split("+")[0])
    for ref, pins in pins_of.items():                  # pins on no net at all
        for num, (nm, ty) in pins.items():
            if num not in d.parts[ref]["pins"]:
                d.add_pin(ref, num, "", nm, ty)
    return d
