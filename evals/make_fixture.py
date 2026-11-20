#!/usr/bin/env python3
"""Make a placement fixture from a real board: anchors kept and locked, everything else parked, no copper.

    python3 evals/make_fixture.py evals/fixtures/specs/<name>.json --source-root <checkout of the source repo>

The spec names the source board (repo, commit, path) and its anchors: `"locked": true` takes the footprints the owner
locked; `prefixes` and `refs` add parts by reference. The fixture board
  - keeps the anchors where they are, locked;
  - unlocks every other footprint and parks it in a staging area right of the board outline, packed in rows by
    schematic sheet (the reference's hundreds), rotation and side unchanged;
  - drops tracks, arcs, vias, groups and copper zones (teardrops included); rule areas (keep-outs) stay.
It writes evals/fixtures/<name>/: the board, the project (and .kicad_dru if any) renamed to <name>, manifest.json
(source, anchors with positions, plane nets = nets the source board pours) and baseline.json (the metrics of the
source board as its owner placed it: the human baseline).
"""

import argparse
import json
import pathlib
import re
import shutil
import sys

import boardgeo as G
import metrics as M

HERE = pathlib.Path(__file__).resolve().parent
DROP = {"segment", "arc", "via", "group"}
GAP = 1.0          # mm between parked parts
ROW_WIDTH = 100.0  # mm of a staging row
MARGIN = 10.0      # mm from the outline to the staging area


def sort_key(ref):
    m = re.match(r"([A-Za-z]+)(\d+)", ref)
    if not m:
        return (10**9, ref, 0)
    n = int(m.group(2))
    return (n // 100 if n >= 100 else 0, m.group(1), n)


def plane_nets(text, root_blocks):
    nets = set()
    for kind, s, e in root_blocks:
        if kind != "zone" or "(keepout" in text[s:e] or "(teardrop" in text[s:e]:
            continue
        m = re.search(r'\n\t\t\(net "([^"]*)"\)', text[s:e]) or re.search(r'\(net_name "([^"]*)"\)', text[s:e])
        if m and m.group(1) and not M.is_ground(m.group(1)):
            nets.add(m.group(1))
    return sorted(nets)


def make(spec, source_root, out_root=HERE / "fixtures"):
    src_board = pathlib.Path(source_root) / spec["source"]["board"]
    text = src_board.read_text(encoding="utf-8")
    board = G.Board(text=text)
    root_blocks = G.blocks(text)

    want = spec.get("anchors", {})
    prefixes = tuple(want.get("prefixes", []))
    anchors = {f["ref"] for f in board.footprints
               if (want.get("locked") and f["locked"]) or f["ref"] in want.get("refs", [])
               or (prefixes and re.match(rf"^({'|'.join(prefixes)})\d", f["ref"]))}
    missing = sorted(set(want.get("refs", [])) - {f["ref"] for f in board.footprints})
    if missing:
        sys.exit(f"anchors not on the board: {missing}")

    # staging slots, packed in rows right of the outline
    x0, y0, x1, _ = G.bbox(board.outline)
    sx, sy, row_h, slots = x1 + MARGIN, y0, 0.0, {}
    parked = sorted((f for f in board.footprints if f["ref"] not in anchors), key=lambda f: sort_key(f["ref"]))
    for f in parked:
        pts = [p for h in f["hulls"].values() for p in h] or [(f["x"], f["y"])]
        bx0, by0, bx1, by1 = G.bbox(pts)
        w, h = bx1 - bx0, by1 - by0
        if sx + w > x1 + MARGIN + ROW_WIDTH and sx > x1 + MARGIN:
            sx, sy, row_h = x1 + MARGIN, sy + row_h + GAP, 0.0
        slots[f["uuid"]] = (f["x"] + sx - bx0, f["y"] + sy - by0)
        sx += w + GAP
        row_h = max(row_h, h)

    by_uuid = {f["uuid"]: f for f in board.footprints}
    edits = []
    fp_iter = iter(board.footprints)
    for kind, s, e in root_blocks:
        if kind in DROP or (kind == "zone" and "(keepout" not in text[s:e]):
            ls = text.rfind("\n", 0, s)
            edits.append((ls, e, ""))
        elif kind == "footprint":
            f = next(fp_iter)
            assert by_uuid[f["uuid"]] is f
            block = text[s:e]
            if f["ref"] in anchors:
                edits.append((s, e, G.footprint_text(block, locked=True)))
            else:
                x, y = slots[f["uuid"]]
                edits.append((s, e, G.footprint_text(block, x=x, y=y, locked=False)))
    fixture = G.rewrite(text, edits)

    name = spec["name"]
    out = pathlib.Path(out_root) / name
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.kicad_pcb").write_text(fixture, encoding="utf-8")
    pro = src_board.with_suffix(".kicad_pro")
    if pro.exists():
        data = json.loads(pro.read_text(encoding="utf-8"))
        data.setdefault("meta", {})["filename"] = f"{name}.kicad_pro"
        (out / f"{name}.kicad_pro").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    dru = src_board.with_suffix(".kicad_dru")
    if dru.exists():
        shutil.copy(dru, out / f"{name}.kicad_dru")

    manifest = {
        "name": name,
        "source": spec["source"],
        "note": spec.get("note", ""),
        "plane_nets": plane_nets(text, root_blocks),
        "anchors": {f["ref"]: {"x": f["x"], "y": f["y"], "rot": f["rot"], "side": f["side"]}
                    for f in sorted(board.footprints, key=lambda f: sort_key(f["ref"])) if f["ref"] in anchors},
        "parked": len(parked),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    baseline = M.measure(board, manifest)
    (out / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    return out, manifest, baseline


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--source-root", required=True, help="checkout of the spec's source repo at its commit")
    a = ap.parse_args(argv)
    spec = json.loads(pathlib.Path(a.spec).read_text(encoding="utf-8"))
    out, manifest, base = make(spec, a.source_root)
    print(f"{out}: {len(manifest['anchors'])} anchors, {manifest['parked']} parked, "
          f"{len(manifest['plane_nets'])} plane nets; baseline ratsnest {base['ratsnest_mm']} mm, "
          f"crossings {base['crossings']}")


if __name__ == "__main__":
    main()
