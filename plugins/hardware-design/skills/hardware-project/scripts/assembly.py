#!/usr/bin/env python3
"""assembly.py: check an assembly package (JLCPCB BOM + CPL) against the board before it is published.

    assembly.py <board.kicad_pcb> <bom.csv> <cpl.csv> [--json out.json]

Every fitted part on the board must be in the BOM and in the CPL, and every BOM line must be a fitted part:
  fitted        a footprint with pads that is not DNP, not excluded from the BOM and not board-only;
  hand-fitted   a fitted part whose symbol has the field Assembly = hand (house convention): soldered by hand
                after assembly, so it is expected in neither file and listed as a note.
A fitted part missing from the BOM (e.g. no LCSC number) or the CPL would come back from the assembler without it;
a BOM line for a part that is DNP or not on the board would be fitted when it shouldn't. Each is an error naming the
reference. The files are also checked: required columns, at least one row, an LCSC number on every BOM line,
numeric positions and rotations, and a Top/Bottom layer on every CPL line.

Exit 1 on any error. Used by export_release.py (blocks the zip) and export_jlcpcb.py.
"""

import argparse
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "pcb-design-rules", "scripts"))
import pcb_rules as R  # noqa: E402

BOM_COLUMNS = ("Comment", "Designator", "Footprint", "LCSC Part #")
CPL_COLUMNS = ("Designator", "Val", "Package", "Mid X", "Mid Y", "Rotation", "Layer")
HAND = {"hand", "hand-fitted", "hand fitted", "manual"}


def ref_key(ref):
    m = re.match(r"([A-Za-z#_]*)(\d*)", ref)
    return (m.group(1), int(m.group(2) or 0), ref)


def refs_text(refs):
    return ", ".join(sorted(refs, key=ref_key))


def board_parts(pcb):
    """{ref: {fitted, hand}} for every footprint on the board."""
    with open(pcb, encoding="utf-8") as f:
        root = R.parse_sexpr(f.read())
    parts = {}
    for fp in R.children(root, "footprint"):
        props = {p[1]: (p[2] if len(p) > 2 and isinstance(p[2], str) else "") for p in R.children(fp, "property")}
        ref = props.get("Reference", "")
        if not ref or ref.startswith("#"):
            continue
        attr = set((R.child(fp, "attr") or [])[1:])
        for flag in ("dnp", "exclude_from_bom", "board_only"):          # (dnp yes) as well as (attr ... dnp)
            c = R.child(fp, flag)
            if c and c[1:2] == ["yes"]:
                attr.add(flag)
        fitted = bool(R.children(fp, "pad")) and not attr & {"dnp", "exclude_from_bom", "board_only"}
        parts[ref] = dict(fitted=fitted, hand=props.get("Assembly", "").strip().lower() in HAND)
    return parts


def _read(path, columns, errors):
    name = os.path.basename(str(path))
    if not os.path.exists(path):
        errors.append(f"{name}: missing ({path})")
        return None
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            errors.append(f"{name}: no column {', '.join(missing)} (has: {', '.join(reader.fieldnames or [])})")
            return None
        rows = list(reader)
    if not rows:
        errors.append(f"{name}: no rows")
    return rows


def _num(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def read_bom(path, errors):
    rows = _read(path, BOM_COLUMNS, errors)
    refs = {}
    for n, r in enumerate(rows or [], 2):
        line = [x.strip() for x in (r["Designator"] or "").split(",") if x.strip()]
        if not line:
            errors.append(f"bom.csv line {n}: no designator")
        if not (r["LCSC Part #"] or "").strip():
            errors.append(f"bom.csv line {n}: no LCSC number for {refs_text(line)}")
        for ref in line:
            if ref in refs:
                errors.append(f"bom.csv: {ref} on line {refs[ref]} and line {n}")
            refs.setdefault(ref, n)
    return None if rows is None else set(refs)


def read_cpl(path, errors):
    rows = _read(path, CPL_COLUMNS, errors)
    refs = set()
    for n, r in enumerate(rows or [], 2):
        ref = (r["Designator"] or "").strip()
        if not ref:
            errors.append(f"cpl.csv line {n}: no designator")
            continue
        if ref in refs:
            errors.append(f"cpl.csv: {ref} placed twice (line {n})")
        refs.add(ref)
        bad = [c for c in ("Mid X", "Mid Y", "Rotation") if not _num(r[c])]
        if bad:
            errors.append(f"cpl.csv line {n}: {ref} has a non-numeric {', '.join(bad)}")
        if (r["Layer"] or "").strip() not in ("Top", "Bottom"):
            errors.append(f"cpl.csv line {n}: {ref} has Layer {r['Layer']!r}, not Top or Bottom")
    return None if rows is None else refs


def reconcile(parts, bom, cpl):
    """(errors, notes): the fitted parts against the BOM's and the CPL's designators."""
    errors, notes = [], []
    assembled = {r for r, p in parts.items() if p["fitted"] and not p["hand"]}
    hand = {r for r, p in parts.items() if p["fitted"] and p["hand"]}
    if bom is not None:
        if assembled - bom:
            errors.append(f"fitted but not in the BOM (no LCSC number? mark it DNP, or Assembly = hand if soldered "
                          f"by hand): {refs_text(assembled - bom)}")
        stray = bom - assembled - hand
        if stray:
            on_board = {r for r in stray if r in parts}
            errors.append("in the BOM but not a fitted part on the board (DNP, excluded or missing: the assembler "
                          f"would fit it): {refs_text(stray)}" + (f" ({len(on_board)} on the board)" if on_board else ""))
        if hand & bom:
            errors.append(f"hand-fitted (Assembly = hand) but in the BOM: {refs_text(hand & bom)}")
    if cpl is not None:
        if assembled - cpl:
            errors.append(f"fitted but not in the CPL (the assembler can't place it): {refs_text(assembled - cpl)}")
        extra = cpl - assembled - hand
        if extra:
            notes.append(f"in the CPL with no BOM line (the assembler ignores them): {refs_text(extra)}")
    if hand:
        notes.append(f"hand-fitted, not in the assembly package: {refs_text(hand)}")
    return errors, notes


def check_package(pcb, bom_path, cpl_path):
    errors = []
    bom = read_bom(bom_path, errors)
    cpl = read_cpl(cpl_path, errors)
    rec_errors, notes = reconcile(board_parts(pcb), bom, cpl)
    return dict(errors=errors + rec_errors, notes=notes)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("bom")
    ap.add_argument("cpl")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    res = check_package(a.board, a.bom, a.cpl)
    for e in res["errors"]:
        print(f"ERROR {e}")
    for n in res["notes"]:
        print(f"note: {n}")
    print("PASS" if not res["errors"] else f"FAIL: {len(res['errors'])} error(s)")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(res, f, indent=2)
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
