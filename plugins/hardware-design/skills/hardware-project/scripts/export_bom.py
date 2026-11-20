#!/usr/bin/env python3
"""Export the schematic BOM: bom/bom.csv (stock-check format) and bom/bom_jlc.csv (JLCPCB assembly format).

DNP parts and parts excluded from the BOM (antenna, net ties, test points) are left out.
Lines are grouped by LCSC number.

Usage: export_bom.py [hardware/<board>/<board>.kicad_sch] [--kicad-cli PATH]
"""

import argparse
import csv
import io
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import project  # noqa: E402
ROOT = project.root()
BOARD = project.default_board(ROOT)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("schematic", nargs="?", help="root schematic (default: hardware/<board>/<board>.kicad_sch)")
    ap.add_argument("--kicad-cli", default="kicad-cli")
    a = ap.parse_args()
    schematic = pathlib.Path(a.schematic) if a.schematic else ROOT / "hardware" / BOARD / f"{BOARD}.kicad_sch"
    (ROOT / "bom").mkdir(exist_ok=True)
    out = ROOT / "bom" / "raw_bom.csv"
    subprocess.run([a.kicad_cli, "sch", "export", "bom", "--exclude-dnp", "--fields",
                    "Reference,Value,Footprint,LCSC,MPN,${QUANTITY}", "--labels", "Reference,Value,Footprint,LCSC,MPN,Qty",
                    "--group-by", "LCSC", "--ref-range-delimiter", "", "-o", str(out), str(schematic)],
                   check=True, capture_output=True)
    rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8"))))
    out.unlink()
    rows = [r for r in rows if r["LCSC"]]
    rows.sort(key=lambda r: r["Reference"])
    with open(ROOT / "bom" / "bom.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["group", "function", "mpn", "lcsc", "qty", "notes", "footprint"])
        for row in rows:
            writer.writerow(["schematic", row["Value"], row["MPN"], row["LCSC"], row["Qty"], row["Reference"],
                             row["Footprint"].split(":")[-1]])
    with open(ROOT / "bom" / "bom_jlc.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for row in rows:
            writer.writerow([row["Value"], row["Reference"], row["Footprint"].split(":")[-1], row["LCSC"]])
    print(f"{len(rows)} BOM lines, {sum(int(r['Qty']) for r in rows)} placements -> bom/bom.csv, bom/bom_jlc.csv")


if __name__ == "__main__":
    main()
