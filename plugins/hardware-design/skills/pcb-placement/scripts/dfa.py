#!/usr/bin/env python3
"""dfa.py: assembly checks of a placed KiCad 10 board against an assembler's profile (JLCPCB by default).

    dfa.py <board.kicad_pcb> [--assembly jlcpcb] [--json out.json]

Also run by `place.py gate`. Checks, from the board file alone:
  assembly_spacing   pairs of parts on the same side closer than the assembler's minimum for their two package
                     classes (JLCPCB: 0.15 mm between small chips up to 2 mm between BGAs), measured pad copper to
                     pad copper. Pairs of two locked parts are the owner's and not counted. A decoupling
                     capacitor next to the IC it decouples (one pad on ground, the other on a net of that IC) is
                     reported as an exception, not a violation: the vendor's "as close to the pins as possible"
                     is an electrical requirement and wins over the assembler's inspection spacing.
  edge_keepout       brittle parts (MLCCs, crystals, BGAs) with copper closer to the board edge than the profile's
                     keep-out (JLCPCB: 3-5 mm is safe from depaneling stress; 3 mm used)
  fiducials_missing  populated sides with fewer fiducials than the profile asks (JLCPCB: 3, at least 3.35 mm from
                     the edge), unless the order adds edge rails with fiducials
  orientation_mixed  polarized two-terminal parts (D*, polarized C*) outside their two most common orientations,
                     and ICs (U*) outside their most common one: inspection is easier when they agree
  unclassified       parts whose package is not in the spacing table (listed, not checked)

The profile is pcb-design-rules/profiles/assembly/<name>.json, with its sources.
"""
import argparse
import json
import math
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import boardgeo as G  # noqa: E402
import placement_metrics as M  # noqa: E402

from shapely.geometry import LineString, Polygon  # noqa: E402

R = G.R
PROFILE_DIR = os.path.join(HERE, "..", "..", "pcb-design-rules", "profiles", "assembly")
CHIPS = ["0201", "0402", "0603", "0805", "1206"]
CHIP = re.compile(r"(?<![0-9])(0201|0402|0603|0805|1206|1210|1812|2010|2512|2220|2225)(?![0-9])")
FIDUCIAL = re.compile(r"FIDUCIAL", re.I)


def load_profile(name):
    path = os.path.join(PROFILE_DIR, name + ".json")
    if not os.path.exists(path):
        names = sorted(f[:-5] for f in os.listdir(PROFILE_DIR) if f.endswith(".json"))
        sys.exit(f"unknown assembly profile '{name}'; available: {', '.join(names)}")
    with open(path) as f:
        return json.load(f)


def package_class(lib, npads):
    """The spacing-table class of a footprint, from its library name; None when it is not in the table."""
    name = lib.split(":")[-1].upper()
    if FIDUCIAL.search(name):
        return None
    if "BGA" in name or "WLCSP" in name:
        return "BGA"
    if re.search(r"QFN|DFN|(?<![A-Z])SON(?![A-Z])|LGA", name):
        return "QFN"
    if "QFP" in name:
        return "QFP"
    if re.search(r"SOIC|SSOP|MSOP|PDSO|(?<![A-Z])SOP|(?<![A-Z])SO-\d", name):
        return "SOP"
    if re.search(r"SOT-?\d|SC-?70|SC-?88", name):
        return "SOT"
    m = CHIP.search(name)
    if m and npads <= 3:
        size = m.group(1)
        return size if size in CHIPS else "1206"     # the table stops at 1206: larger chips use its row
    return None


def _pad_poly(p):
    c, s = math.cos(math.radians(p["rot"])), math.sin(math.radians(p["rot"]))
    hw, hh = p["w"] / 2, p["h"] / 2
    return Polygon([(p["x"] + dx * c + dy * s, p["y"] - dx * s + dy * c)
                    for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))])


def parts_of(path):
    """Footprints with library name, side, rotation, lock and pads (with shapes), from the board file."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    root = R.parse_sexpr(text)
    pads = {}
    for p in R.Board(text=text).pads:
        pads.setdefault(p["ref"], []).append(p)
    out = []
    for fp in R.children(root, "footprint"):
        ref = next((str(q[2]) for q in R.children(fp, "property") if len(q) > 2 and q[1] == "Reference"), "")
        at = R.child(fp, "at")
        lay = str(R.child(fp, "layer")[1])
        ps = pads.get(ref, [])
        out.append(dict(ref=ref, lib=str(fp[1]), side=lay[0], x=float(at[1]), y=float(at[2]),
                        rot=float(at[3]) if len(at) > 3 else 0.0, locked=R.is_locked(fp), pads=ps,
                        smd=any(p["kind"] == "smd" for p in ps),
                        cls=package_class(str(fp[1]), len({p["num"] for p in ps if p["num"]}))))
    return out, G.Board(text=text).outline


def decouples(cap, ic):
    """cap is a capacitor with one pad on ground and another on a net of ic."""
    if not cap["ref"].startswith("C"):
        return False
    nets = {p["net"] for p in cap["pads"] if p["net"]}
    gnd = {n for n in nets if M.is_ground(n)}
    return bool(gnd) and bool((nets - gnd) & {p["net"] for p in ic["pads"]})


def spacing(parts, table):
    """([(ref a, ref b, gap mm, limit mm, classes)] for pairs closer than the table allows,
    the same list for decoupling pairs, which are exceptions)."""
    def limit(a, b):
        return table.get(f"{a}|{b}", table.get(f"{b}|{a}"))
    reach = max(table.values()) if table else 0.0
    shapes = {}
    for f in parts:
        if f["cls"] and f["pads"]:
            polys = [_pad_poly(p) for p in f["pads"]]
            xs = [c[0] for q in polys for c in q.exterior.coords]
            ys = [c[1] for q in polys for c in q.exterior.coords]
            shapes[f["ref"]] = (polys, (min(xs), min(ys), max(xs), max(ys)))
    found, exceptions = [], []
    cand = [f for f in parts if f["ref"] in shapes]
    for i, a in enumerate(cand):
        pa, ba = shapes[a["ref"]]
        for b in cand[i + 1:]:
            if a["side"] != b["side"] or (a["locked"] and b["locked"]):
                continue
            pb, bb = shapes[b["ref"]]
            if ba[0] - reach > bb[2] or bb[0] - reach > ba[2] or ba[1] - reach > bb[3] or bb[1] - reach > ba[3]:
                continue
            lim = limit(a["cls"], b["cls"])
            if lim is None:
                continue
            gap = min(x.distance(y) for x in pa for y in pb)
            if gap < lim - 1e-6:
                row = (a["ref"], b["ref"], round(gap, 3), lim, f"{a['cls']}|{b['cls']}")
                (exceptions if decouples(a, b) or decouples(b, a) else found).append(row)
    return found, exceptions


def brittle(f):
    ref, lib = f["ref"], f["lib"].upper()
    if f["cls"] == "BGA":
        return True
    if ref.startswith("Y") or "CRYSTAL" in lib or "RESONATOR" in lib:
        return True
    return ref.startswith("C") and f["cls"] in CHIPS and not re.search(r"CP_|ELEC|TANTAL", lib)


def edge_keepout(parts, outline, mm):
    if len(outline) < 3:
        return []
    edge = LineString(list(outline) + [outline[0]])
    out = []
    for f in parts:
        if f["pads"] and brittle(f):
            d = min(edge.distance(_pad_poly(p)) for p in f["pads"])
            if d < mm - 1e-6:
                out.append((f["ref"], round(d, 2)))
    return out


def fiducials(parts, outline, spec):
    edge = LineString(list(outline) + [outline[0]]) if len(outline) >= 3 else None
    report = {}
    for side in ("F", "B"):
        if not any(f["smd"] and f["side"] == side and not FIDUCIAL.search(f["lib"]) for f in parts):
            continue
        fids = [f for f in parts if f["side"] == side and (FIDUCIAL.search(f["lib"]) or f["ref"].startswith("FID"))]
        near = [f["ref"] for f in fids if edge is not None and edge.distance(_pt(f)) < spec["edge_min_mm"] - 1e-6]
        report[side] = dict(count=len(fids), too_close=near, ok=len(fids) >= spec["count_min"] and not near)
    return report


def _pt(f):
    from shapely.geometry import Point
    return Point(f["x"], f["y"])


def orientation(parts):
    """[(ref, rotation, expected)] for parts outside their class's usual orientations, per side."""
    groups = {}
    for f in parts:
        lib = f["lib"].upper()
        if f["ref"].startswith("D") or re.search(r"LED", lib):
            kind, keep = "polarized", 2
        elif f["ref"].startswith("C") and re.search(r"CP_|ELEC|TANTAL", lib):
            kind, keep = "polarized", 2
        elif f["ref"].startswith("U"):
            kind, keep = "ic", 1
        else:
            continue
        groups.setdefault((kind, f["side"], keep), []).append(f)
    out = []
    for (kind, side, keep), fs in groups.items():
        rot = lambda f: round(f["rot"]) % 360  # noqa: E731
        common = [r for r, _ in Counter(rot(f) for f in fs).most_common(keep)]
        out += [(f["ref"], rot(f), common) for f in fs if rot(f) not in common]
    return out


def check(path, profile_name="jlcpcb"):
    prof = load_profile(profile_name)
    parts, outline = parts_of(path)
    sp, sp_ex = spacing(parts, prof["spacing_mm"])
    ek = edge_keepout(parts, outline, prof["edge_keepout_mm"])
    fd = fiducials(parts, outline, prof["fiducial"])
    orient = orientation(parts)
    uncl = sorted(f["ref"] for f in parts if f["pads"] and f["smd"] and not f["cls"] and not FIDUCIAL.search(f["lib"]))
    m = dict(assembly_spacing=len(sp), edge_keepout=len(ek), fiducials_missing=sum(not v["ok"] for v in fd.values()),
             orientation_mixed=len(orient), unclassified=len(uncl))
    detail = dict(assembly_spacing=sp, decoupling_exceptions=sp_ex, edge_keepout=ek, fiducials=fd, orientation_mixed=orient, unclassified=uncl)
    return m, detail, prof


def report(m, detail, prof):
    lines = [f"## Assembly ({prof['name']}, checked {prof['fetched']})", "",
             "| Check | Value | Kind |", "|---|---|---|",
             f"| assembly_spacing | {m['assembly_spacing']} | hard with --enforce |",
             f"| decoupling exceptions (cap at its IC, closer than the table) | {len(detail['decoupling_exceptions'])} | info |",
             f"| edge_keepout ({prof['edge_keepout_mm']:g} mm, MLCC / crystal / BGA) | {m['edge_keepout']} | soft |",
             f"| fiducials_missing (sides) | {m['fiducials_missing']} | soft |",
             f"| orientation_mixed | {m['orientation_mixed']} | soft |",
             f"| unclassified (spacing not checked) | {m['unclassified']} | info |", ""]
    for a, b, gap, lim, cls in detail["assembly_spacing"][:20]:
        lines.append(f"- spacing: {a} / {b}: {gap} mm < {lim} mm ({cls})")
    for a, b, gap, lim, cls in detail["decoupling_exceptions"][:20]:
        lines.append(f"- decoupling exception: {a} / {b}: {gap} mm < {lim} mm ({cls}); keep it close, check AOI/rework")
    for ref, d in detail["edge_keepout"][:20]:
        lines.append(f"- edge keep-out: {ref} at {d} mm from the edge")
    for side, v in detail["fiducials"].items():
        if not v["ok"]:
            lines.append(f"- fiducials on {side}.Cu: {v['count']} (need {prof['fiducial']['count_min']}"
                         + (f"; closer than {prof['fiducial']['edge_min_mm']} mm to the edge: {', '.join(v['too_close'])}"
                            if v["too_close"] else "")
                         + f"), or order edge rails (at least {prof['rail_min_mm']:g} mm) with fiducials")
    for ref, rot, common in detail["orientation_mixed"][:20]:
        lines.append(f"- orientation: {ref} at {rot}° (others at {', '.join(f'{c}°' for c in common)})")
    if detail["unclassified"]:
        u = detail["unclassified"]
        lines.append(f"- not in the spacing table: {', '.join(u[:30])}{' …' if len(u) > 30 else ''}")
    lines.append("")
    lines.append("Spacing is measured pad copper to pad copper; the assembler's page does not say which edges its "
                 "table uses. Sources: " + ", ".join(prof["sources"]))
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--assembly", default="jlcpcb")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    m, detail, prof = check(a.board, a.assembly)
    print(report(m, detail, prof))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(dict(metrics=m, detail=detail), f, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
