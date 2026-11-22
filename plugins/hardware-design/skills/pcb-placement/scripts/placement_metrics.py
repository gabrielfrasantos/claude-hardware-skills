#!/usr/bin/env python3
"""Placement metrics of a KiCad 10 board, computed from the file alone (no KiCad needed).

    python3 placement_metrics.py board.kicad_pcb [--manifest manifest.json] [--json]

Validity (a placement with any of these is invalid):
  anchors_moved     anchors (manifest) whose position, rotation or side changed, or that are missing
  parts_off_board   non-anchor footprints with a pad outside the Edge.Cuts outline
  overlaps          pairs of footprints on the same side whose courtyards overlap (shapely, real outlines);
                    pairs of two anchors are the owner's and not counted
Quality (lower is better):
  ratsnest_mm       sum over signal nets of the minimum spanning tree of their pads, Manhattan
                    (the measure pcb-design-rules' gate reports detours against)
  crossings         crossings between straight ratsnest edges of different signal nets: an estimate of the vias
                    and layer changes routing will need
  decap_*_mm        for each capacitor with one pad on ground: distance from its other pad to the nearest IC (U*)
                    pad on the same net; median, p90, max
Plane nets (ground by default, plus the manifest's `plane_nets`) are left out of ratsnest and crossings: they are
poured, not routed.
"""

import argparse
import json
import math
import re
import statistics
import sys

import boardgeo as G
from shapely.strtree import STRtree

GROUND = re.compile(r"^(GND|AGND|DGND|PGND|GNDA|GNDD|GNDPWR|VSS|GND_\w+|\w+_GND|EARTH|0V)$", re.I)


def base(net):
    return net.rsplit("/", 1)[-1]


def is_ground(net):
    return bool(GROUND.match(base(net)))


# ------------------------------------------------------------------------------------------------- nets
def nets_of(board):
    nets = {}
    for f in board.footprints:
        for p in f["pads"]:
            if p["net"] and not p["net"].startswith("unconnected-"):
                nets.setdefault(p["net"], []).append((p["x"], p["y"], f["ref"]))
    return nets


def mst_edges(points):
    """Prim's minimum spanning tree, Euclidean; returns the edges as point pairs."""
    pts = list({(round(x, 4), round(y, 4)) for x, y in points})
    if len(pts) < 2:
        return []
    best = {i: (math.dist(pts[i], pts[0]), 0) for i in range(1, len(pts))}
    edges = []
    while best:
        j = min(best, key=lambda k: best[k][0])
        _, i = best.pop(j)
        edges.append((pts[i], pts[j]))
        for k in best:
            d = math.dist(pts[k], pts[j])
            if d < best[k][0]:
                best[k] = (d, j)
    return edges


def _proper_cross(a, b, c, d):
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)

    if a in (c, d) or b in (c, d):
        return False
    return orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0


def crossings(edges_by_net):
    items = []
    for net, edges in edges_by_net.items():
        for a, b in edges:
            items.append((min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]), net, a, b))
    items.sort()
    count = 0
    for i, (x0, x1, y0, y1, net, a, b) in enumerate(items):
        for u0, u1, v0, v1, net2, c, d in items[i + 1:]:
            if u0 > x1:
                break
            if net2 == net or v0 > y1 or v1 < y0:
                continue
            if _proper_cross(a, b, c, d):
                count += 1
    return count


# ------------------------------------------------------------------------------------------------- geometry
MIN_OVERLAP_MM2 = 0.001   # touching courtyards share an edge (area 0); anything above this is an overlap
OVERLAP_TOL_MM = 0.01     # overlaps shallower than this aren't counted: KiCad 10.0.3's DRC passed a 0.007 mm courtyard
                          # overlap (e-inverted-pendulum R515 / R516), so the gate matches it


def overlaps(board):
    """Pairs of footprints whose courtyards on the same side overlap. The real courtyard outline is used (not its
    hull), so a part in a notch of another part's courtyard is not an overlap."""
    shapes = [(lay, f["ref"], geom) for f in board.footprints for lay, geom in f["courts"].items() if geom.area > 0]
    tree = STRtree([g for _, _, g in shapes])
    pairs = set()
    for i, (lay, ref, geom) in enumerate(shapes):
        for j in tree.query(geom):
            lay2, ref2, geom2 = shapes[j]
            if j > i and lay2 == lay and ref2 != ref and (geom.buffer(-OVERLAP_TOL_MM / 2, join_style=2)
                                                          .intersection(geom2.buffer(-OVERLAP_TOL_MM / 2, join_style=2))
                                                          .area > MIN_OVERLAP_MM2):
                pairs.add(tuple(sorted((ref, ref2))))
    return sorted(pairs)


def decap_distances(board):
    ics = {}
    for f in board.footprints:
        if re.match(r"^U\d", f["ref"]):
            for p in f["pads"]:
                if p["net"]:
                    ics.setdefault(p["net"], []).append((p["x"], p["y"]))
    out = {}
    for f in board.footprints:
        pads = [p for p in f["pads"] if p["net"]]
        if not re.match(r"^C\d", f["ref"]) or len(pads) != 2:
            continue
        g = [p for p in pads if is_ground(p["net"])]
        s = [p for p in pads if not is_ground(p["net"])]
        if len(g) != 1 or len(s) != 1 or s[0]["net"] not in ics:
            continue
        out[f["ref"]] = min(math.dist((s[0]["x"], s[0]["y"]), q) for q in ics[s[0]["net"]])
    return out


# ------------------------------------------------------------------------------------------------- report
def measure(board, manifest=None):
    manifest = manifest or {}
    anchors = manifest.get("anchors", {})
    plane = set(manifest.get("plane_nets", []))
    refs = board.by_ref()

    moved = []
    for ref, a in anchors.items():
        f = refs.get(ref)
        if (f is None or math.dist((f["x"], f["y"]), (a["x"], a["y"])) > 1e-3
                or abs((f["rot"] - a["rot"] + 180) % 360 - 180) > 0.01 or f["side"] != a["side"]):
            moved.append(ref)

    off = []
    if board.outline:
        for f in board.footprints:
            if f["ref"] in anchors or not f["pads"]:
                continue
            if any(not G.inside(board.outline, p["x"], p["y"]) for p in f["pads"]):
                off.append(f["ref"])

    signal = {n: pts for n, pts in nets_of(board).items() if not is_ground(n) and base(n) not in plane
              and n not in plane}
    edges = {n: mst_edges([(x, y) for x, y, _ in pts]) for n, pts in signal.items()}
    ratsnest = sum(G.R._mst_manhattan([(x, y) for x, y, _ in pts]) for pts in signal.values())

    dec = decap_distances(board)
    dv = sorted(dec.values())
    ov = [pair for pair in overlaps(board) if not (pair[0] in anchors and pair[1] in anchors)]
    return {
        "valid": not moved and not off and not ov,
        "anchors_moved": len(moved),
        "parts_off_board": len(off),
        "overlaps": len(ov),
        "ratsnest_mm": round(ratsnest, 1),
        "crossings": crossings(edges),
        "decap_count": len(dv),
        "decap_median_mm": round(statistics.median(dv), 2) if dv else None,
        "decap_p90_mm": round(dv[min(len(dv) - 1, int(0.9 * len(dv)))], 2) if dv else None,
        "decap_max_mm": round(dv[-1], 2) if dv else None,
        "footprints": len(board.footprints),
        "signal_nets": len(signal),
        "vias": board.vias,
        "track_segments": board.segments,
        "detail": {"anchors_moved": moved, "parts_off_board": off, "overlaps": [list(p) for p in ov],
                   "decap_mm": {k: round(v, 2) for k, v in sorted(dec.items())}},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--manifest")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args(argv)
    manifest = json.load(open(a.manifest, encoding="utf-8")) if a.manifest else None
    m = measure(G.Board(a.board), manifest)
    if a.json:
        print(json.dumps(m, indent=2))
    else:
        for k, v in m.items():
            if k != "detail":
                print(f"{k:18} {v}")
    return 0 if m["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
