#!/usr/bin/env python3
"""place.py: placement gate and optimizer for KiCad 10 boards. The owner's locked footprints never move.

    place.py gate     <board.kicad_pcb> [--baseline baseline.json] [--limit 1.10] [--enforce]
                      [--report r.md] [--json r.json]
    place.py optimize <board.kicad_pcb> [--out other.kicad_pcb] [--only REF,...] [--seed 1] [--effort 1.0]
                      [--edge-mm 0.5] [--report r.md]
    place.py propose  <board.kicad_pcb> [--seed 1] [--effort 3.0]      anchors may move too; report only
    place.py render   <board.kicad_pcb> <out.png> [--manifest m.json] [--side F|B]

gate      validity: parts with a pad off the board, courtyard overlaps (pairs of two locked parts are the owner's),
          footprints in keep-outs; quality: ratsnest length (Manhattan MST of each signal net's pads), ratsnest
          crossings (a via estimate), decoupling distance (capacitor to nearest IC pad on its supply, 90th pct).
          With --baseline (a JSON of the same metrics, e.g. the owner's earlier placement) it gives the ratios.
          Report-only until the evals set limits (docs/design.md D25); --enforce exits 1 when invalid or a ratio
          is above --limit.
optimize  simulated annealing over the unlocked footprints (or --only), translation only: rotation and side are
          kept. Cost = ratsnest length + 2 x decoupling distance, with overlaps, area outside the board (inset by
          --edge-mm) and keep-out area as penalties. Then each part still in conflict goes to the nearest legal
          spot on a 0.05 mm grid. Writes the board (or --out) and prints the gate before and after.
          --refine improves an existing placement locally and writes it only if the ratsnest and the crossings
          both get no worse.
propose   refine with the locked parts movable too; writes nothing and lists how far each anchor would move and
          what it would gain, for the owner to decide (or says to keep them).
render    a PNG of one side: outline, keep-outs, courtyards (locked grey, the rest coloured by schematic sheet,
          i.e. the reference's hundreds) and the ratsnest; look at it before and after optimizing.

Ground and the nets the board pours are left out of the ratsnest: they are planes. Needs shapely and numpy.
"""
import argparse
import json
import math
import os
import random
import sys

import numpy as np
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import boardgeo as G  # noqa: E402
import placement_metrics as M  # noqa: E402

R = G.R
W_OVERLAP = 200.0     # cost per mm² of overlap, outside area or keep-out area
W_DECAP = 2.0         # weight of a decoupling capacitor's distance to its IC
GRID = 0.05           # mm, the metric pin-pitch grid (pcb-design-rules §5)
CELL = 5.0            # mm, spatial hash cell
OUT_PULL = 1.0        # per mm of distance outside the board, in units of the part's area


# ------------------------------------------------------------------------------------------------- model
class Layout:
    def __init__(self, path, movable=None, include_locked=False, edge_mm=0.5, plane=()):
        self.path = path
        self.board = G.Board(path)
        self.plane = R.Board(text=self.board.text).zone_nets | set(plane)
        outline = Polygon(self.board.outline) if len(self.board.outline) >= 3 else None
        self.inner = outline.buffer(-edge_mm) if outline is not None else None
        self.keepouts = self.board.keepouts
        self.parts = []
        for f in self.board.footprints:
            side = "F" if f["side"] == "F.Cu" else "B"
            court = f["courts"].get(f"{side}.CrtYd") or f["courts"].get("F.CrtYd") or f["courts"].get("B.CrtYd")
            court = court if court is not None and court.area > 0 else Point(f["x"], f["y"]).buffer(0.2)
            mov = bool(f["pads"]) and (include_locked or not f["locked"]) and (movable is None or f["ref"] in movable)
            self.parts.append(dict(ref=f["ref"], uuid=f["uuid"], x=f["x"], y=f["y"], x0=f["x"], y0=f["y"], side=side,
                                   locked=f["locked"], movable=mov, shape=affinity.translate(court, -f["x"], -f["y"]),
                                   pads=[(p["x"] - f["x"], p["y"] - f["y"], p["net"]) for p in f["pads"]]))
        # signal nets: (part index, dx, dy) per pad
        self.nets = {}
        for i, p in enumerate(self.parts):
            for dx, dy, net in p["pads"]:
                if net and not net.startswith("unconnected-") and not M.is_ground(net) and net not in self.plane:
                    self.nets.setdefault(net, []).append((i, dx, dy))
        self.nets = {n: v for n, v in self.nets.items() if len(v) >= 2}
        # decoupling capacitors: (cap index, dx, dy) per supply net, and the IC pads on it
        self.decaps, self.ic_pads = {}, {}
        for i, p in enumerate(self.parts):
            if p["ref"][:1] == "U":
                for dx, dy, net in p["pads"]:
                    self.ic_pads.setdefault(net, []).append((i, dx, dy))
        for i, p in enumerate(self.parts):
            pads = [q for q in p["pads"] if q[2]]
            if p["ref"][:1] == "C" and p["ref"][1:2].isdigit() and len(pads) == 2:
                g = [q for q in pads if M.is_ground(q[2])]
                s = [q for q in pads if not M.is_ground(q[2])]
                if len(g) == 1 and len(s) == 1 and s[0][2] in self.ic_pads:
                    self.decaps.setdefault(s[0][2], []).append((i, s[0][0], s[0][1]))
        self.part_nets = [set() for _ in self.parts]
        for n, pads in list(self.nets.items()) + list(self.decaps.items()):
            for i, _, _ in pads:
                self.part_nets[i].add(n)
        for n in self.decaps:
            for i, _, _ in self.ic_pads[n]:
                self.part_nets[i].add(n)
        self.w_overlap = W_OVERLAP
        self.grid = {}
        self.geom = [None] * len(self.parts)
        for i in range(len(self.parts)):
            self._place(i)
        self.net_cost = {n: self._net_cost(n) for n in set(self.nets) | set(self.decaps)}

    # geometry
    def _cells(self, g):
        x0, y0, x1, y1 = g.bounds
        return [(cx, cy) for cx in range(int(x0 // CELL), int(x1 // CELL) + 1)
                for cy in range(int(y0 // CELL), int(y1 // CELL) + 1)]

    def _place(self, i):
        p = self.parts[i]
        g = affinity.translate(p["shape"], p["x"], p["y"])
        self.geom[i] = g
        for c in self._cells(g):
            self.grid.setdefault(c, set()).add(i)

    def _unplace(self, i):
        for c in self._cells(self.geom[i]):
            self.grid.get(c, set()).discard(i)

    def penalty(self, i, g=None):
        """Overlap with other parts on the same side, area outside the board and keep-out area (mm²)."""
        p = self.parts[i]
        g = g if g is not None else self.geom[i]
        seen, pen = set(), 0.0
        for c in self._cells(g):
            for j in self.grid.get(c, ()):
                if j != i and j not in seen and self.parts[j]["side"] == p["side"]:
                    seen.add(j)
                    if g.intersects(self.geom[j]):
                        pen += g.intersection(self.geom[j]).area
        if self.inner is not None and p["movable"]:
            out = g.area - g.intersection(self.inner).area
            if out > 1e-9:                       # the distance term pulls a part that is wholly outside back in
                pen += out + OUT_PULL * g.distance(self.inner) * g.area
        for sides, ko in self.keepouts:
            if p["side"] in sides and g.intersects(ko):
                pen += g.intersection(ko).area
        return pen

    def _pos(self, i, dx, dy):
        return self.parts[i]["x"] + dx, self.parts[i]["y"] + dy

    def _net_cost(self, n):
        cost = 0.0
        if n in self.nets:
            cost += R._mst_manhattan([self._pos(i, dx, dy) for i, dx, dy in self.nets[n]])
        if n in self.decaps:
            ics = [self._pos(i, dx, dy) for i, dx, dy in self.ic_pads[n]]
            for i, dx, dy in self.decaps[n]:
                cost += W_DECAP * min(math.dist(self._pos(i, dx, dy), q) for q in ics)
        return cost

    def overlap(self):
        return sum(self.penalty(i) for i, p in enumerate(self.parts) if p["movable"])

    def total(self):
        pen = sum(self.penalty(i) for i, p in enumerate(self.parts) if p["movable"])
        return sum(self.net_cost.values()) + self.w_overlap * pen

    # moves
    def try_move(self, moves, temperature, rng):
        """moves: [(i, x, y)]. Applies them if the Metropolis test passes; returns the cost change or None."""
        idx = [i for i, _, _ in moves]
        nets = set().union(*(self.part_nets[i] for i in idx))
        before = sum(self.net_cost[n] for n in nets) + self.w_overlap * sum(self.penalty(i) for i in idx)
        old = [(i, self.parts[i]["x"], self.parts[i]["y"]) for i in idx]
        for i in idx:
            self._unplace(i)
        for i, x, y in moves:
            self.parts[i]["x"], self.parts[i]["y"] = x, y
        for i in idx:
            self._place(i)
        new_costs = {n: self._net_cost(n) for n in nets}
        after = sum(new_costs.values()) + self.w_overlap * sum(self.penalty(i) for i in idx)
        delta = after - before
        if delta <= 0 or (temperature > 0 and rng.random() < math.exp(-delta / temperature)):
            self.net_cost.update(new_costs)
            return delta
        for i in idx:
            self._unplace(i)
        for i, x, y in old:
            self.parts[i]["x"], self.parts[i]["y"] = x, y
        for i in idx:
            self._place(i)
        return None


# ------------------------------------------------------------------------------------------------- optimize
def attraction(lay, i, placed):
    pts = []
    for n in lay.part_nets[i]:
        for j, dx, dy in lay.nets.get(n, []) + lay.ic_pads.get(n, []):
            if j != i and j in placed:
                pts.append(lay._pos(j, dx, dy))
    c = lay.inner.centroid if lay.inner is not None else Point(0, 0)
    x, y = (float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts]))) if pts else (c.x, c.y)
    if lay.inner is not None and not lay.inner.contains(Point(x, y)):     # anchors parked off the board pull outward
        from shapely.ops import nearest_points
        q = nearest_points(lay.inner.buffer(-2.0) if not lay.inner.buffer(-2.0).is_empty else lay.inner, Point(x, y))[0]
        x, y = q.x, q.y
    return x, y


def anneal(lay, seed=1, effort=1.0, log=print, refine=False):
    """Simulated annealing. refine: start from the current placement at the temperature of 1 mm moves (x 0.1),
    with steps of at most 2 mm, so a good placement is improved locally instead of scrambled."""
    rng = random.Random(seed)
    mov = [i for i, p in enumerate(lay.parts) if p["movable"]]
    if not mov:
        return
    inside = {i for i, p in enumerate(lay.parts) if lay.inner is None or lay.inner.buffer(1.0).contains(lay.geom[i])}
    placed = set(inside) | {i for i, p in enumerate(lay.parts) if not p["movable"]}
    for i in sorted(mov, key=lambda k: -lay.geom[k].area):                    # parked parts start at their nets
        if i not in inside:
            x, y = attraction(lay, i, placed)
            lay.try_move([(i, x, y)], float("inf"), rng)
            placed.add(i)
    span = math.dist(*[(b[0], b[1]) for b in (lay.inner.bounds[:2], lay.inner.bounds[2:])]) if lay.inner else 50.0
    sizes = {}
    for i in mov:
        b = lay.parts[i]["shape"].bounds
        sizes.setdefault((round(b[2] - b[0], 1), round(b[3] - b[1], 1)), []).append(i)
    # starting temperature: the mean uphill step of a few random moves
    ups = []
    for _ in range(min(200, 20 * len(mov))):
        i = rng.choice(mov)
        p = lay.parts[i]
        x, y = p["x"], p["y"]
        probe = 1.0 if refine else span / 10
        d = lay.try_move([(i, x + rng.gauss(0, probe), y + rng.gauss(0, probe))], float("inf"), rng)
        if d and d > 0:
            ups.append(d)
        lay.try_move([(i, x, y)], float("inf"), rng)                           # probe only: put it back
    t0 = float(np.mean(ups)) if ups else 1.0
    if refine:
        t0 *= 0.1
    steps = max(2000, int(effort * 400 * len(mov)))
    t_end = t0 * 1e-4
    alpha = (t_end / t0) ** (1 / steps)
    t, accepted = t0, 0
    for k in range(steps):
        frac = t / t0
        # the overlap weight grows as the temperature falls: parts may pass through each other early, not late
        lay.w_overlap = W_OVERLAP * (0.05 + 20 * (k / steps) ** 2)
        i = rng.choice(mov)
        p = lay.parts[i]
        b = p["shape"].bounds
        twins = sizes.get((round(b[2] - b[0], 1), round(b[3] - b[1], 1)), [])
        if len(twins) > 1 and rng.random() < (0.02 if refine else 0.15):                               # swap with a same-size part
            j = rng.choice([q for q in twins if q != i])
            q = lay.parts[j]
            d = lay.try_move([(i, q["x"], q["y"]), (j, p["x"], p["y"])], t, rng)
        else:
            sigma = max(0.25, (2.0 if refine else span * 0.3) * math.sqrt(frac))
            d = lay.try_move([(i, p["x"] + rng.gauss(0, sigma), p["y"] + rng.gauss(0, sigma))], t, rng)
        accepted += d is not None
        t *= alpha
        if log and (k + 1) % max(1, steps // 5) == 0:
            log(f"  annealing {100 * (k + 1) // steps:3d}%  wire {sum(lay.net_cost.values()):8.1f}  "
                f"overlap {lay.overlap():7.2f} mm²  accepted {accepted}")


def legalize(lay, radius=60.0, log=print):
    """Snap every movable part to the grid, then move each one still in conflict to the nearest legal grid spot
    (largest first), choosing the cheapest of the legal spots in the first ring that has any."""
    rng = random.Random(0)
    mov = [i for i, p in enumerate(lay.parts) if p["movable"]]
    for i in mov:
        p = lay.parts[i]
        lay.try_move([(i, round(p["x"] / GRID) * GRID, round(p["y"] / GRID) * GRID)], float("inf"), rng)
    stuck = []
    for i in sorted(mov, key=lambda k: -lay.geom[k].area):
        if lay.penalty(i) < 1e-6:
            continue
        p = lay.parts[i]
        x0, y0 = p["x"], p["y"]
        best = None
        r = 0.25
        while r <= radius and best is None:
            n = max(8, int(2 * math.pi * r / 0.25))
            for a in range(n):
                x = round((x0 + r * math.cos(2 * math.pi * a / n)) / GRID) * GRID
                y = round((y0 + r * math.sin(2 * math.pi * a / n)) / GRID) * GRID
                g = affinity.translate(p["shape"], x, y)
                lay._unplace(i)
                legal = lay.penalty(i, g) < 1e-6
                lay._place(i)
                if legal:
                    old = (p["x"], p["y"])
                    p["x"], p["y"] = x, y
                    cost = sum(lay._net_cost(nn) for nn in lay.part_nets[i])
                    p["x"], p["y"] = old
                    if best is None or cost < best[0]:
                        best = (cost, x, y)
            r += 0.25
        if best:
            lay.try_move([(i, best[1], best[2])], float("inf"), rng)
        else:
            stuck.append(lay.parts[i]["ref"])
    if stuck and log:
        log(f"  no legal spot within {radius:g} mm for: {', '.join(stuck)}")
    return stuck


def write(lay, out):
    text = lay.board.text
    edits = []
    fps = [b for b in G.blocks(text) if b[0] == "footprint"]
    for (_, s, e), p in zip(fps, lay.parts):
        if p["movable"] and (abs(p["x"] - p["x0"]) > 1e-6 or abs(p["y"] - p["y0"]) > 1e-6):
            edits.append((s, e, G.footprint_text(text[s:e], x=p["x"], y=p["y"])))
    with open(out, "w", encoding="utf-8") as f:
        f.write(G.rewrite(text, edits))
    return len(edits)


# ------------------------------------------------------------------------------------------------- gate
def plane_nets(a):
    """Nets to treat as planes besides the board's own pours: --manifest's plane_nets (an eval fixture)."""
    if getattr(a, "manifest", None):
        with open(a.manifest) as f:
            return json.load(f).get("plane_nets", [])
    return []


def measure(path, plane=()):
    b = G.Board(path)
    anchors = {f["ref"]: dict(x=f["x"], y=f["y"], rot=f["rot"], side=f["side"]) for f in b.footprints if f["locked"]}
    m = M.measure(b, {"anchors": anchors, "plane_nets": sorted(R.Board(text=b.text).zone_nets | set(plane))})
    ko = []
    for f in b.footprints:
        side = "F" if f["side"] == "F.Cu" else "B"
        for lay, g in f["courts"].items():
            for sides, poly in b.keepouts:
                if side in sides and g.intersects(poly) and g.intersection(poly).area > 1e-3:
                    ko.append(f["ref"])
    m["keepout_violations"] = len(set(ko))
    m["detail"]["keepout_violations"] = sorted(set(ko))
    m["valid"] = m["valid"] and not ko
    return m


def gate_report(m, base=None, limit=1.10, title=""):
    keys = ("ratsnest_mm", "crossings", "decap_p90_mm")
    lines = [f"# Placement gate{': ' + title if title else ''}", "",
             "| Check | Value |" + (" Baseline | Ratio |" if base else ""), "|---|---|" + ("---|---|" if base else "")]
    ratios = {}
    for k in ("parts_off_board", "overlaps", "keepout_violations") + keys:
        row = f"| {k} | {m.get(k)} |"
        if base:
            bv = base.get(k)
            r = (m[k] / bv) if (k in keys and bv and m.get(k) is not None) else None
            if r is not None:
                ratios[k] = r
            row += f" {bv} | {'' if r is None else f'{r:.3f}'} |"
        lines.append(row)
    lines += ["", f"Valid: **{m['valid']}** (no part off the board, no overlap, nothing in a keep-out). "
              f"{m['footprints']} footprints, {m['signal_nets']} signal nets, {m['decap_count']} decoupling caps."]
    for k in ("parts_off_board", "overlaps", "keepout_violations"):
        d = m["detail"].get(k)
        if d:
            lines.append(f"- {k}: {', '.join(map(str, d[:20]))}{' …' if len(d) > 20 else ''}")
    over = {k: r for k, r in ratios.items() if k in ("ratsnest_mm", "crossings") and r > limit}
    if base:
        lines.append(f"Against the baseline (limit × {limit:g} on ratsnest and crossings): "
                     + ("within" if not over else "above on " + ", ".join(over)))
    return "\n".join(lines) + "\n", (m["valid"] and not over)


def cmd_gate(a):
    m = measure(a.board, plane_nets(a))
    base = None
    if a.baseline:
        with open(a.baseline) as f:
            base = json.load(f)
    text, ok = gate_report(m, base, a.limit, os.path.basename(a.board))
    print(text)
    if a.report:
        with open(a.report, "w") as f:
            f.write(text)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(m, f, indent=2)
    return 1 if (a.enforce and not ok) else 0


def cmd_optimize(a, propose=False):
    only = set(a.only.split(",")) if getattr(a, "only", None) else None
    plane = plane_nets(a)
    lay = Layout(a.board, movable=only, include_locked=propose, edge_mm=a.edge_mm, plane=plane)
    n = sum(p["movable"] for p in lay.parts)
    print(f"{'proposing' if propose else 'optimizing'} {n} footprints of {len(lay.parts)} "
          f"({len(lay.nets)} signal nets, {sum(len(v) for v in lay.decaps.values())} decoupling caps)")
    before = measure(a.board, plane)
    anneal(lay, a.seed, a.effort, refine=propose or getattr(a, "refine", False))
    stuck = legalize(lay)
    if propose:
        rows = sorted(((math.dist((p["x"], p["y"]), (p["x0"], p["y0"])), p["ref"], p["x"] - p["x0"], p["y"] - p["y0"])
                       for p in lay.parts if p["locked"]), reverse=True)
        tmp = a.board + ".propose.kicad_pcb"
        write(lay, tmp)
        after = measure(tmp, plane)
        os.remove(tmp)
        better = after["valid"] and after["ratsnest_mm"] < before["ratsnest_mm"] and after["crossings"] <= before["crossings"]
        if not better:
            print(f"no better placement found with the anchors free (ratsnest {before['ratsnest_mm']} -> "
                  f"{after['ratsnest_mm']} mm, crossings {before['crossings']} -> {after['crossings']}): keep them")
            return 0
        print("anchor moves that refine the placement (the owner decides; nothing written):")
        for d, ref, dx, dy in rows[:20]:
            if d > 0.5:
                print(f"  {ref:8} {d:6.1f} mm  (dx {dx:+.1f}, dy {dy:+.1f})")
        print(f"ratsnest {before['ratsnest_mm']} -> {after['ratsnest_mm']} mm, crossings {before['crossings']} -> "
              f"{after['crossings']} (all parts free)")
        return 0
    out = a.out or a.board
    if getattr(a, "refine", False):
        tmp = out + ".refine.kicad_pcb"
        write(lay, tmp)
        trial = measure(tmp, plane)
        os.remove(tmp)
        if not (trial["valid"] and trial["ratsnest_mm"] <= before["ratsnest_mm"] and trial["crossings"] <= before["crossings"]):
            print(f"refine found nothing better (ratsnest {before['ratsnest_mm']} -> {trial['ratsnest_mm']} mm, crossings "
                  f"{before['crossings']} -> {trial['crossings']}, valid {trial['valid']}): board left as it was")
            return 0
    moved = write(lay, out)
    after = measure(out, plane)
    text, _ = gate_report(after, before, title=f"{os.path.basename(out)} after optimize (baseline: before)")
    print(f"moved {moved} footprints; written to {out}" + (f"; stuck: {', '.join(stuck)}" if stuck else ""))
    print(text)
    if a.report:
        with open(a.report, "w") as f:
            f.write(text)
    return 0


def cmd_render(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lay = Layout(a.board, plane=plane_nets(a))
    fig, ax = plt.subplots(figsize=(10, 10))
    if lay.board.outline:
        xs, ys = zip(*(lay.board.outline + lay.board.outline[:1]))
        ax.plot(xs, ys, color="black", lw=1.2)
    for sides, ko in lay.keepouts:
        if a.side in sides:
            ax.fill(*ko.exterior.xy, color="red", alpha=0.12, lw=0)
    cmap = plt.get_cmap("tab10")
    for i, p in enumerate(lay.parts):
        if p["side"] != a.side:
            continue
        g = lay.geom[i]
        for poly in getattr(g, "geoms", [g]):
            if not hasattr(poly, "exterior"):
                continue
            digits = "".join(ch for ch in p["ref"] if ch.isdigit())
            sheet = int(digits) // 100 if digits and int(digits) >= 100 else 0
            color = "0.6" if p["locked"] else cmap(sheet % 10)
            ax.fill(*poly.exterior.xy, color=color, alpha=0.35 if p["locked"] else 0.55, lw=0.4, ec="0.2")
        if g.area > 4:
            c = g.centroid
            ax.text(c.x, c.y, p["ref"], fontsize=4, ha="center", va="center")
    for n, pads in lay.nets.items():
        pts = [lay._pos(i, dx, dy) for i, dx, dy in pads if lay.parts[i]["side"] == a.side]
        for (x1, y1), (x2, y2) in M.mst_edges(pts):
            ax.plot([x1, x2], [y1, y2], color="tab:blue", lw=0.3, alpha=0.5)
    m = measure(a.board, plane_nets(a))
    ax.set_title(f"{os.path.basename(a.board)} ({a.side}): ratsnest {m['ratsnest_mm']} mm, crossings {m['crossings']}, "
                 f"valid {m['valid']}", fontsize=9)
    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.axis("off")
    fig.savefig(a.out, dpi=200, bbox_inches="tight")
    print(f"wrote {a.out}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    g.add_argument("board")
    g.add_argument("--baseline")
    g.add_argument("--manifest", help="an eval fixture's manifest: its plane nets are left out of the ratsnest")
    g.add_argument("--limit", type=float, default=1.10, help="ratio to the baseline (D25: +10 %%)")
    g.add_argument("--enforce", action="store_true", help="exit 1 when invalid or above the limit")
    g.add_argument("--report")
    g.add_argument("--json")
    for name in ("optimize", "propose"):
        p = sub.add_parser(name)
        p.add_argument("board")
        p.add_argument("--seed", type=int, default=1)
        p.add_argument("--effort", type=float, default=3.0, help="annealing steps, x 400 per movable part (3: about 40 s for 160 parts)")
        p.add_argument("--edge-mm", type=float, default=0.5, help="courtyards stay this far inside the outline")
        p.add_argument("--manifest", help="an eval fixture's manifest: its plane nets are left out of the ratsnest")
        if name == "optimize":
            p.add_argument("--out")
            p.add_argument("--only", help="move only these references (comma-separated)")
            p.add_argument("--refine", action="store_true", help="improve an existing placement locally (no global search)")
            p.add_argument("--report")
    r = sub.add_parser("render")
    r.add_argument("board")
    r.add_argument("out")
    r.add_argument("--side", default="F", choices=("F", "B"))
    r.add_argument("--manifest")
    a = ap.parse_args(argv)
    if a.cmd == "gate":
        return cmd_gate(a)
    if a.cmd == "render":
        return cmd_render(a)
    return cmd_optimize(a, propose=a.cmd == "propose")


if __name__ == "__main__":
    sys.exit(main())
