#!/usr/bin/env python3
"""
Export a complete review package for a KiCad 10 board (hardware/<board>/<board>.*).

Produces, under ./review_exports/<board>/ (default board: the only one under hardware/):

  Schematic
    - schematic.pdf          full schematic, all sheets
    - bom.csv                bill of materials, every placed part including DNP
                             (Refs, Value, Footprint, Qty, DNP, MPN, LCSC)
    - erc.rpt / erc.json     Electrical Rules Check report

  PCB
    - gerbers/               one Gerber file per layer + drill files
    - drc.rpt / drc.json     Design Rules Check report (with schematic parity = "compare")
    - board_stats.txt        board statistics
    - pcb_views/             copper (every layer), silk and assembly views as PNG
                             (PDF if PyMuPDF is not installed)
    - design_rules.txt       net classes / clearances / track widths from the project

The ERC and DRC reports list every violation; the script does not fail on them.
An unrouted board reports many DRC violations (unconnected items, parts off the board).

Usage:
    python3 scripts/export_review.py
    python3 scripts/export_review.py --name <board>      # hardware/<board>/<board>.*
    python3 scripts/export_review.py --kicad-cli "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"

Everything in review_exports/<board>/ can be handed to a reviewer (human or agent).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project  # noqa: E402  (repo root and board, hardware-project skill)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = project.root()
HW_DIR = PROJECT_ROOT / "hardware"

DEFAULT_BOARD = project.default_board(PROJECT_ROOT)

SCH_FILE = HW_DIR / DEFAULT_BOARD / f"{DEFAULT_BOARD}.kicad_sch"
PCB_FILE = HW_DIR / DEFAULT_BOARD / f"{DEFAULT_BOARD}.kicad_pcb"
PRO_FILE = HW_DIR / DEFAULT_BOARD / f"{DEFAULT_BOARD}.kicad_pro"

OUT_DIR = PROJECT_ROOT / "review_exports" / DEFAULT_BOARD
GERBER_DIR = OUT_DIR / "gerbers"
IMAGE_DIR = OUT_DIR / "pcb_views"

# Non-copper (technical) layers to plot as Gerbers. Copper layers are detected
# from the board at runtime, see detect_copper_layers().
TECH_LAYERS = [
    "F.Paste", "B.Paste",
    "F.Silkscreen", "B.Silkscreen",
    "F.Mask", "B.Mask",
    "Edge.Cuts",
    "F.Fab", "B.Fab",
]

# Board views rendered for visual inspection: (filename, [layers plotted
# together]). Inner copper views are added at runtime.
PCB_VIEWS = [
    ("copper_top.pdf",    ["F.Cu", "F.Mask", "Edge.Cuts"]),
    ("copper_bottom.pdf", ["B.Cu", "B.Mask", "Edge.Cuts"]),
    ("silk_top.pdf",      ["F.Silkscreen", "Edge.Cuts"]),
    ("silk_bottom.pdf",   ["B.Silkscreen", "Edge.Cuts"]),
    ("assembly_top.pdf",  ["F.Fab", "F.Silkscreen", "Edge.Cuts"]),
    ("assembly_bottom.pdf", ["B.Fab", "B.Silkscreen", "Edge.Cuts"]),
]

# Common kicad-cli install locations (Windows).
CLI_CANDIDATES = [
    r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_cli(override: str | None) -> str:
    if override:
        if not Path(override).exists():
            sys.exit(f"kicad-cli not found at: {override}")
        return override
    found = shutil.which("kicad-cli")
    if found:
        return found
    for c in CLI_CANDIDATES:
        if Path(c).exists():
            return c
    sys.exit("kicad-cli not found. Pass --kicad-cli <path>.")


def detect_copper_layers(pcb_path: Path) -> list[str]:
    """Read the board's `(layers ...)` block and return the enabled copper
    layers in stack order (F.Cu, In1.Cu, ..., B.Cu). Falls back to a 2-layer
    board if parsing fails."""
    fallback = ["F.Cu", "B.Cu"]
    try:
        text = pcb_path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return fallback

    # The top-level (layers ...) block: balance parens from the opener.
    start = text.find("(layers")
    if start == -1:
        return fallback
    depth, i = 0, start
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    block = text[start:i + 1]

    # Lines look like:  (0 "F.Cu" signal)  /  (4 "In1.Cu" signal)
    found = re.findall(r'\(\s*(\d+)\s+"([^"]+\.Cu)"\s+\w+', block)
    if not found:
        return fallback
    layers = [name for _, name in sorted(found, key=lambda t: int(t[0]))]
    # KiCad numbers B.Cu 2, before the inner layers; move it to the end.
    if "B.Cu" in layers:
        layers = [l for l in layers if l != "B.Cu"] + ["B.Cu"]
    return layers


def run(cli: str, args: list[str], label: str) -> bool:
    """Run a kicad-cli subcommand. Return True on success (exit 0)."""
    cmd = [cli] + args
    print(f"\n>>> {label}")
    print("    " + " ".join(f'"{a}"' if " " in a else a for a in cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.stdout.strip():
        print("    " + res.stdout.strip().replace("\n", "\n    "))
    if res.returncode != 0:
        print(f"    [FAIL exit {res.returncode}] {res.stderr.strip()}")
        return False
    print("    [OK]")
    return True


def summarize_violations(report: Path, label: str) -> None:
    """Print violation counts by type from a kicad-cli ERC/DRC JSON report."""
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"    [warn] cannot read {report.name}: {e}")
        return
    counts: dict[str, int] = {}
    groups = [data.get("violations", []), data.get("unconnected_items", []),
              data.get("schematic_parity", [])]
    groups += [sheet.get("violations", []) for sheet in data.get("sheets", [])]
    for group in groups:
        for v in group:
            key = f"{v.get('severity', '?')}: {v.get('type', '?')}"
            counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    print(f"\n    {label}: {total} violation(s)")
    for key, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"      {n:5d}  {key}")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def export_schematic(cli: str) -> None:
    run(cli, ["sch", "export", "pdf",
              "-o", str(OUT_DIR / "schematic.pdf"),
              str(SCH_FILE)],
        "Schematic PDF")

    # ${DNP} is a group key so fitted and DNP parts never share a line.
    run(cli, ["sch", "export", "bom",
              "-o", str(OUT_DIR / "bom.csv"),
              "--group-by", "Value,Footprint,LCSC,${DNP}",
              "--fields", "Reference,Value,Footprint,${QUANTITY},${DNP},MPN,LCSC",
              "--labels", "Refs,Value,Footprint,Qty,DNP,MPN,LCSC",
              str(SCH_FILE)],
        "Bill of Materials (CSV)")

    run(cli, ["sch", "erc",
              "-o", str(OUT_DIR / "erc.rpt"),
              "--severity-all", "--units", "mm",
              str(SCH_FILE)],
        "ERC report (text)")

    if run(cli, ["sch", "erc",
                 "-o", str(OUT_DIR / "erc.json"),
                 "--format", "json", "--severity-all",
                 str(SCH_FILE)],
           "ERC report (json)"):
        summarize_violations(OUT_DIR / "erc.json", "ERC")


def export_pcb(cli: str) -> None:
    GERBER_DIR.mkdir(parents=True, exist_ok=True)

    # Wipe stale plot outputs so a previous run's layers can't linger.
    for f in GERBER_DIR.glob("*"):
        if f.suffix.lower() in (".gbr", ".gbrjob", ".drl"):
            f.unlink()

    copper = detect_copper_layers(PCB_FILE)
    gerber_layers = copper + TECH_LAYERS
    print(f"\n    detected copper layers: {', '.join(copper)}")

    run(cli, ["pcb", "export", "gerbers",
              "-o", str(GERBER_DIR) + os.sep,
              "--layers", ",".join(gerber_layers),
              "--no-protel-ext",
              str(PCB_FILE)],
        "Gerbers (layer by layer)")

    run(cli, ["pcb", "export", "drill",
              "-o", str(GERBER_DIR) + os.sep,
              "--format", "excellon",
              "--generate-map", "--map-format", "gerberx2",
              str(PCB_FILE)],
        "Drill files")

    # DRC with schematic parity = the schematic/PCB "compare".
    run(cli, ["pcb", "drc",
              "-o", str(OUT_DIR / "drc.rpt"),
              "--schematic-parity", "--all-track-errors",
              "--severity-all", "--units", "mm",
              str(PCB_FILE)],
        "DRC report + schematic parity (text)")

    if run(cli, ["pcb", "drc",
                 "-o", str(OUT_DIR / "drc.json"),
                 "--format", "json", "--schematic-parity",
                 "--all-track-errors", "--severity-all",
                 str(PCB_FILE)],
           "DRC report + schematic parity (json)"):
        summarize_violations(OUT_DIR / "drc.json", "DRC")

    run(cli, ["pcb", "export", "stats",
              "-o", str(OUT_DIR / "board_stats.txt"),
              str(PCB_FILE)],
        "Board statistics")


def _pdf_to_png(pdf: Path, dpi: int = 300) -> bool:
    """Rasterize a single-page PDF to PNG (same stem) with PyMuPDF. Returns
    False (and leaves the PDF) if PyMuPDF isn't installed."""
    try:
        import pymupdf
    except ImportError:
        return False
    doc = pymupdf.open(pdf)
    doc[0].get_pixmap(dpi=dpi).save(pdf.with_suffix(".png"))
    doc.close()
    return True


def export_pcb_images(cli: str) -> None:
    """Render per-view images of the board (copper, silk, assembly) for visual
    inspection. kicad-cli plots each view to PDF, then it is rasterized to PNG
    so a reviewer that only reads images can see it."""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    # Wipe stale views so a previous run's layers can't linger.
    for f in IMAGE_DIR.glob("*"):
        if f.suffix.lower() in (".pdf", ".png"):
            f.unlink()

    views = list(PCB_VIEWS)

    # One copper view per inner layer (only on boards with more than 2 layers).
    copper = detect_copper_layers(PCB_FILE)
    inner = [l for l in copper if l not in ("F.Cu", "B.Cu")]
    for layer in inner:
        fname = "copper_" + layer.replace(".", "_").lower() + ".pdf"
        views.append((fname, [layer, "Edge.Cuts"]))

    png_ok = True
    for fname, layers in views:
        # --mode-single: the output path is the file and every layer goes on
        # one sheet. --scale 0 autoscales to fill the page.
        if not run(cli, ["pcb", "export", "pdf",
                         "-o", str(IMAGE_DIR / fname),
                         "--layers", ",".join(layers),
                         "--mode-single", "--scale", "0",
                         str(PCB_FILE)],
                   f"PCB view: {fname}"):
            continue
        if png_ok and not _pdf_to_png(IMAGE_DIR / fname):
            png_ok = False
            print("    [warn] PyMuPDF not installed -> PNGs skipped, PDFs kept."
                  " Install with: pip install pymupdf")

    if png_ok:
        # PNGs generated: drop the intermediate PDFs.
        for f in IMAGE_DIR.glob("*.pdf"):
            f.unlink()


def dump_design_rules() -> None:
    """Extract net classes / clearances / track widths from the .kicad_pro."""
    out = OUT_DIR / "design_rules.txt"
    try:
        pro = json.loads(PRO_FILE.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"\n>>> Design rules\n    [FAIL] cannot read {PRO_FILE.name}: {e}")
        return

    lines: list[str] = [f"{PRO_FILE.stem.upper()} DESIGN RULES (from project file)", "=" * 40, ""]

    ds = pro.get("board", {}).get("design_settings", {})
    rules = ds.get("rules", {})
    if rules:
        lines.append("Global rules:")
        for k, v in rules.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    netclasses = pro.get("net_settings", {}).get("classes", [])
    if netclasses:
        lines.append("Net classes:")
        for nc in netclasses:
            lines.append(f"  - {nc.get('name', '?')}:")
            for k in ("clearance", "track_width", "via_diameter",
                      "via_drill", "microvia_diameter", "microvia_drill",
                      "diff_pair_width", "diff_pair_gap"):
                if k in nc:
                    lines.append(f"      {k}: {nc[k]}")
        lines.append("")

    # Append the custom design-rules file if present.
    dru = PRO_FILE.with_suffix(".kicad_dru")
    if dru.exists():
        lines.append("Custom .kicad_dru:")
        lines.append(dru.read_text(encoding="utf-8"))

    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n>>> Design rules\n    [OK] -> design_rules.txt")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _resolve_project(name: str | None, pcb: str | None) -> None:
    """Point the module-level path globals at the chosen project. Every board
    lives under hardware/<name>/<name>.* and exports to review_exports/<name>/.
    The default board is the only one under hardware/. --name <basename> selects another
    board; --pcb <path> points at an explicit .kicad_pcb (sibling .kicad_sch
    and .kicad_pro assumed)."""
    global SCH_FILE, PCB_FILE, PRO_FILE, OUT_DIR, GERBER_DIR, IMAGE_DIR

    if pcb:
        stem = Path(pcb).with_suffix("")
        PCB_FILE = Path(pcb)
        SCH_FILE = stem.with_suffix(".kicad_sch")
        PRO_FILE = stem.with_suffix(".kicad_pro")
        label = name or stem.name
        OUT_DIR = PROJECT_ROOT / "review_exports" / label
    else:
        name = name or DEFAULT_BOARD
        base = HW_DIR / name / name
        SCH_FILE = base.with_suffix(".kicad_sch")
        PCB_FILE = base.with_suffix(".kicad_pcb")
        PRO_FILE = base.with_suffix(".kicad_pro")
        OUT_DIR = PROJECT_ROOT / "review_exports" / name

    GERBER_DIR = OUT_DIR / "gerbers"
    IMAGE_DIR = OUT_DIR / "pcb_views"


def main() -> None:
    ap = argparse.ArgumentParser(description="Export a KiCad review package.")
    ap.add_argument("--kicad-cli", help="Path to kicad-cli")
    ap.add_argument("--name", help="Project basename under hardware/<name>/ "
                    f"(default: {DEFAULT_BOARD})")
    ap.add_argument("--pcb", help="Explicit path to a .kicad_pcb (overrides --name)")
    ap.add_argument("--skip-sch", action="store_true", help="Skip schematic exports")
    ap.add_argument("--skip-pcb", action="store_true", help="Skip PCB exports")
    args = ap.parse_args()

    _resolve_project(args.name, args.pcb)

    needed = (PCB_FILE,) if args.skip_sch else (SCH_FILE, PCB_FILE, PRO_FILE)
    for f in needed:
        if not f.exists():
            sys.exit(f"Missing project file: {f}")

    cli = find_cli(args.kicad_cli)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"kicad-cli : {cli}")
    print(f"project   : {PCB_FILE.parent}")
    print(f"output    : {OUT_DIR}")

    if not args.skip_sch:
        export_schematic(cli)
    if not args.skip_pcb:
        export_pcb(cli)
        export_pcb_images(cli)
        dump_design_rules()

    print(f"\nDone. Review files in: {OUT_DIR}")


if __name__ == "__main__":
    main()
