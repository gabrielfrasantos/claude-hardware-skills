#!/usr/bin/env python3
"""library_check.py: every placed symbol against its footprint, and the BOM fields, from the files (no KiCad needed).

    library_check.py <board.kicad_pcb> [--schematic root.kicad_sch] [--fields LCSC,MPN] [--json r.json]

Reads the symbols embedded in the project's schematics (every sheet next to the root) and the footprints embedded
in the board, so it checks exactly what was placed.
  pins_without_pad   a symbol pin number (of the units placed) that the footprint has no pad for
  pads_without_pin   a numbered copper pad that no symbol pin uses (unnumbered and NPTH pads are mechanical)
  missing_fields     a part in the BOM (not DNP, not excluded) without a footprint or one of --fields
  not_on_board       a part in the schematic with a footprint that is not on the board (run Update PCB)
Exit 1 when any is found. Run it after Update PCB from Schematic and before layout review.
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pcb-design-rules", "scripts"))
import pcb_rules as R  # noqa: E402


def _yes(node, key, default=True):
    c = R.child(node, key)
    return default if c is None or len(c) < 2 else c[1] == "yes"


def schematic_parts(root_sch):
    """{ref: {lib_id, units, fields, in_bom, dnp, on_board}} and {lib_id: {unit: {pin numbers}}} over every sheet."""
    folder = os.path.dirname(os.path.abspath(root_sch))
    parts, libs = {}, {}
    for path in sorted(glob.glob(os.path.join(folder, "**", "*.kicad_sch"), recursive=True)):
        with open(path, encoding="utf-8") as f:
            root = R.parse_sexpr(f.read())
        ls = R.child(root, "lib_symbols")
        for sym in R.children(ls, "symbol") if ls else []:
            units = libs.setdefault(sym[1], {})
            for sub in R.children(sym, "symbol"):
                unit = int(str(sub[1]).rsplit("_", 2)[-2])
                for pin in R.children(sub, "pin"):
                    num = R.child(pin, "number")
                    if num and num[1]:
                        units.setdefault(unit, set()).add(num[1])
        for s in R.children(root, "symbol"):
            lib_id = R.child(s, "lib_id")
            if not lib_id:
                continue
            props = {p[1]: p[2] for p in R.children(s, "property") if len(p) > 2}
            refs = [r[1] for inst in R.children(s, "instances") for proj in R.children(inst, "project")
                    for pth in R.children(proj, "path") for r in R.children(pth, "reference")] or [props.get("Reference", "")]
            unit = R.child(s, "unit")
            for ref in refs:
                if not ref or ref.startswith("#"):
                    continue
                p = parts.setdefault(ref, dict(lib_id=lib_id[1], units=set(), fields=props, in_bom=_yes(s, "in_bom"),
                                               dnp=_yes(s, "dnp", False), on_board=_yes(s, "on_board")))
                p["units"].add(int(unit[1]) if unit else 1)
    return parts, libs


def board_pads(board_path):
    b = R.Board(board_path)
    pads = {}
    for p in b.pads:
        if p["ref"]:
            pads.setdefault(p["ref"], set())
            if p["num"] and p["kind"] != "np_thru_hole" and p["layers"]:
                pads[p["ref"]].add(p["num"])
    # footprints with no pads at all (logos, holes) still exist on the board
    for fp in R.children(b.root, "footprint"):
        ref = next((q[2] for q in R.children(fp, "property") if len(q) > 2 and q[1] == "Reference"), "")
        pads.setdefault(ref, set())
    return pads


def check(board_path, root_sch, fields=("LCSC", "MPN")):
    parts, libs = schematic_parts(root_sch)
    pads = board_pads(board_path)
    out = {"pins_without_pad": [], "pads_without_pin": [], "missing_fields": [], "not_on_board": []}
    for ref, p in sorted(parts.items()):
        fp = p["fields"].get("Footprint", "")
        in_bom = p["in_bom"] and not p["dnp"]
        if in_bom:
            missing = [k for k in ("Footprint",) + tuple(fields) if not p["fields"].get(k)]
            if missing:
                out["missing_fields"].append(f"{ref} ({p['fields'].get('Value', '')}): no {', '.join(missing)}")
        if not fp or not p["on_board"]:
            continue
        if ref not in pads:
            out["not_on_board"].append(f"{ref} ({fp})")
            continue
        units = libs.get(p["lib_id"], {})
        pins = set(units.get(0, set()))
        for u in p["units"]:
            pins |= units.get(u, set())
        if len(p["units"]) < len([u for u in units if u > 0]):          # not every unit placed yet: pads may be spare
            pins_all = set().union(*units.values()) if units else set()
        else:
            pins_all = pins
        lost = sorted(pins - pads[ref], key=lambda s: (len(s), s))
        spare = sorted(pads[ref] - pins_all, key=lambda s: (len(s), s))
        if lost:
            out["pins_without_pad"].append(f"{ref} {p['lib_id']} on {fp}: pins {', '.join(lost)}")
        if spare:
            out["pads_without_pin"].append(f"{ref} {p['lib_id']} on {fp}: pads {', '.join(spare)}")
    return out, len(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--schematic", help="root schematic (default: <board>.kicad_sch)")
    ap.add_argument("--fields", default="LCSC,MPN", help="fields every BOM part must have (comma-separated)")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    sch = a.schematic or os.path.splitext(a.board)[0] + ".kicad_sch"
    out, n = check(a.board, sch, tuple(f for f in a.fields.split(",") if f))
    bad = sum(len(v) for v in out.values())
    print(f"{n} parts checked against {os.path.basename(a.board)}")
    for k, rows in out.items():
        print(f"  {k}: {len(rows)}")
        for r in rows[:25]:
            print(f"    - {r}")
    print("PASS" if not bad else "FAIL")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=2)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
