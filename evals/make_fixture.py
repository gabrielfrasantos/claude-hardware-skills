#!/usr/bin/env python3
"""Build a placement fixture from a board repo's own history: anchors kept and locked, the rest parked, no copper.

    python3 evals/make_fixture.py <board-repo>/evals/cases/<case>.json [--out DIR]

The case (it lives in the board repo, not here) names the source board and commit and its anchors:
    "source":  {"commit": "<sha>", "board": "hardware/<name>/<name>.kicad_pcb"}
    "anchors": {"locked": true, "prefixes": ["J", "MH"], "refs": ["U301"]}
`locked` takes the footprints the owner locked; `prefixes` and `refs` add parts by reference.

The board, project and rules are read with `git show <commit>:<path>` from the repo the case file is in, so nothing is
copied into any repo. The fixture board
  - keeps the anchors where they are, locked;
  - unlocks every other footprint and parks it right of the board outline, packed in rows by schematic sheet (the
    reference's hundreds), rotation and side unchanged;
  - drops tracks, arcs, vias, groups and copper zones (teardrops included); rule areas (keep-outs) stay.
The output directory gets the board, its .kicad_pro and .kicad_dru (if any), manifest.json (source, anchors with their
positions, plane nets = the nets the source board pours) and baseline.json (the source board's own metrics: the owner's
placement, the human baseline). Default output: <board-repo>/evals/work/fixture-<case id>/ (open it in KiCad to check).
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

import boardgeo as G
import metrics as M

DROP = {"segment", "arc", "via", "group"}
GAP = 1.0          # mm between parked parts
ROW_WIDTH = 100.0  # mm of a staging row
MARGIN = 10.0      # mm from the outline to the staging area


def repo_root(path):
    out = subprocess.run(["git", "-C", str(pathlib.Path(path).resolve().parent), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"{path} is not inside a git repo")
    return pathlib.Path(out.stdout.strip())


def git_show(root, commit, path, required=True):
    out = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{path}"], capture_output=True)
    if out.returncode:
        if required:
            sys.exit(f"git show {commit}:{path} failed in {root}: {out.stderr.decode().strip()}\n"
                     f"(a shallow clone may lack the commit: git -C {root} fetch --depth 1 origin {commit})")
        return None
    return out.stdout.decode("utf-8")


def read_source(case, root):
    src = case["source"]
    board = pathlib.PurePosixPath(src["board"])
    return {"name": board.stem,
            "board": git_show(root, src["commit"], str(board)),
            "pro": git_show(root, src["commit"], str(board.with_suffix(".kicad_pro")), required=False),
            "dru": git_show(root, src["commit"], str(board.with_suffix(".kicad_dru")), required=False)}


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


def anchor_refs(case, board):
    want = case.get("anchors", {})
    prefixes = tuple(want.get("prefixes", []))
    refs = {f["ref"] for f in board.footprints}
    missing = sorted(set(want.get("refs", [])) - refs)
    if missing:
        sys.exit(f"anchors not on the board: {missing}")
    return {f["ref"] for f in board.footprints
            if (want.get("locked") and f["locked"]) or f["ref"] in want.get("refs", [])
            or (prefixes and re.match(rf"^({'|'.join(prefixes)})\d", f["ref"]))}


def make(case, sources, out):
    text = sources["board"]
    board = G.Board(text=text)
    root_blocks = G.blocks(text)
    anchors = anchor_refs(case, board)
    if not anchors:
        sys.exit("no anchors: lock the fixed parts in KiCad or list them in the case")

    # staging slots, packed in rows right of the outline
    _, y0, x1, _ = G.bbox(board.outline)
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

    edits = []
    fps = iter(board.footprints)
    for kind, s, e in root_blocks:
        if kind in DROP or (kind == "zone" and "(keepout" not in text[s:e]):
            edits.append((text.rfind("\n", 0, s), e, ""))
        elif kind == "footprint":
            f = next(fps)
            block = text[s:e]
            if f["ref"] in anchors:
                edits.append((s, e, G.footprint_text(block, locked=True)))
            else:
                edits.append((s, e, G.footprint_text(block, *slots[f["uuid"]], locked=False)))

    name = sources["name"]
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.kicad_pcb").write_text(G.rewrite(text, edits), encoding="utf-8")
    if sources.get("pro"):
        (out / f"{name}.kicad_pro").write_text(sources["pro"], encoding="utf-8")
    if sources.get("dru"):
        (out / f"{name}.kicad_dru").write_text(sources["dru"], encoding="utf-8")

    manifest = {
        "name": name,
        "case": case.get("id", ""),
        "source": case["source"],
        "plane_nets": plane_nets(text, root_blocks),
        "anchors": {f["ref"]: {"x": f["x"], "y": f["y"], "rot": f["rot"], "side": f["side"]}
                    for f in sorted(board.footprints, key=lambda f: sort_key(f["ref"])) if f["ref"] in anchors},
        "parked": len(parked),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    baseline = M.measure(board, manifest)
    (out / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    return out, manifest, baseline


def load_case(case_path):
    case_path = pathlib.Path(case_path).resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case.setdefault("id", case_path.stem)
    case["_path"] = case_path
    case["_evals"] = case_path.parents[1]          # <board-repo>/evals
    case["_root"] = repo_root(case_path)
    return case


def build(case, out=None):
    out = out or case["_evals"] / "work" / f"fixture-{case['id']}"
    return make(case, read_source(case, case["_root"]), out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", help="<board-repo>/evals/cases/<case>.json")
    ap.add_argument("--out", type=pathlib.Path)
    a = ap.parse_args(argv)
    out, manifest, base = build(load_case(a.case), a.out)
    print(f"{out}: {len(manifest['anchors'])} anchors, {manifest['parked']} parked, "
          f"{len(manifest['plane_nets'])} plane nets; baseline ratsnest {base['ratsnest_mm']} mm, "
          f"crossings {base['crossings']}, valid {base['valid']}")


if __name__ == "__main__":
    main()
