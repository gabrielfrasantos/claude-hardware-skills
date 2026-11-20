"""Load KiCad symbols (system or project libraries), flatten `extends`, and expose pin geometry.

configure() sets where symbols come from: KiCad's system symbol folder (found automatically, or $KICAD10_SYMBOL_DIR)
and the project's own libraries ({library name: path to .kicad_sym}).
"""

import copy
import os
import pathlib
import re

from sexpr import Str, find, find_all, parse

SYSTEM_CANDIDATES = [
    os.environ.get("KICAD10_SYMBOL_DIR", ""),
    os.environ.get("KICAD_SYMBOL_DIR", ""),
    "/usr/share/kicad/symbols",
    "/usr/local/share/kicad/symbols",
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
    r"C:\Program Files\KiCad\10.0\share\kicad\symbols",
]
_config = {"system": None, "project": {}}
_cache = {}


def configure(system_dir=None, project_libraries=None):
    """system_dir: KiCad's symbols folder (default: the first that exists of SYSTEM_CANDIDATES).
    project_libraries: {library name: path to its .kicad_sym}."""
    _config["system"] = pathlib.Path(system_dir) if system_dir else next(
        (pathlib.Path(c) for c in SYSTEM_CANDIDATES if c and pathlib.Path(c).is_dir()), None)
    _config["project"] = {k: pathlib.Path(v) for k, v in (project_libraries or {}).items()}
    _cache.clear()


def _library(name):
    if name not in _cache:
        if name in _config["project"]:
            path = _config["project"][name]
        else:
            if _config["system"] is None:
                configure(project_libraries=_config["project"])
            if _config["system"] is None:
                raise SystemExit(f"symbol library {name}: KiCad's symbol folder not found; set $KICAD10_SYMBOL_DIR")
            path = _config["system"] / f"{name}.kicad_sym"
        tree = parse(path.read_text(encoding="utf-8"))
        _cache[name] = {node[1]: node for node in find_all(tree, "symbol")}
    return _cache[name]


def _rename_units(node, old, new):
    for child in find_all(node, "symbol"):
        child[1] = Str(re.sub(rf"^{re.escape(old)}_", f"{new}_", child[1]))


def load(lib_id):
    library, name = lib_id.split(":", 1)
    symbols = _library(library)
    node = copy.deepcopy(symbols[name])
    parent = find(node, "extends")
    if parent is not None:
        base = copy.deepcopy(symbols[parent[1]])
        _rename_units(base, parent[1], name)
        own = {p[1]: p for p in find_all(node, "property")}
        merged = [Str(name) if i == 1 else c for i, c in enumerate(base)]
        merged = [c for c in merged if not (isinstance(c, list) and c and c[0] == "property" and c[1] in own)]
        insert_at = next(i for i, c in enumerate(merged) if isinstance(c, list) and c and c[0] == "symbol")
        merged[insert_at:insert_at] = list(own.values())
        node = merged
    return Symbol(lib_id, node)


class Pin:
    def __init__(self, number, name, kind, x, y, angle, length, unit, hidden):
        self.number, self.name, self.kind = number, name, kind
        self.x, self.y, self.angle, self.length = x, y, angle, length
        self.unit, self.hidden = unit, hidden

    def outward(self):
        return {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[self.angle]


class Symbol:
    def __init__(self, lib_id, node):
        self.lib_id = lib_id
        self.node = node
        self.name = lib_id.split(":", 1)[1]
        self.is_power = find(node, "power") is not None
        self.pins = []
        for unit_node in find_all(node, "symbol"):
            unit = int(unit_node[1].rsplit("_", 2)[-2])
            for pin in find_all(unit_node, "pin"):
                at = find(pin, "at")
                self.pins.append(Pin(
                    number=str(find(pin, "number")[1]), name=str(find(pin, "name")[1]), kind=str(pin[1]),
                    x=float(at[1]), y=float(at[2]), angle=int(float(at[3])) % 360,
                    length=float(find(pin, "length")[1]), unit=unit,
                    hidden=any(isinstance(c, list) and c[:2] == ["hide", "yes"] for c in pin) or "hide" in pin))
        self.units = sorted({p.unit for p in self.pins if p.unit > 0}) or [1]

    def value_at(self):
        for prop in find_all(self.node, "property"):
            if prop[1] == "Value":
                at = find(prop, "at")
                return float(at[1]), float(at[2])
        return 0.0, 0.0

    def unit_pins(self, unit):
        return [p for p in self.pins if p.unit in (0, unit)]

    def embedded(self):
        node = copy.deepcopy(self.node)
        node[1] = Str(self.lib_id)
        return node

    def bbox(self, unit):
        xs, ys = [], []
        for pin in self.unit_pins(unit):
            xs.append(pin.x)
            ys.append(pin.y)
        for unit_node in find_all(self.node, "symbol"):
            for shape in find_all(unit_node, "rectangle"):
                for key in ("start", "end"):
                    point = find(shape, key)
                    xs.append(float(point[1]))
                    ys.append(float(point[2]))
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), -max(ys), max(xs), -min(ys))
