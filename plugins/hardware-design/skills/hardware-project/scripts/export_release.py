#!/usr/bin/env python3
"""
Build a release bundle for a board: ONE zip per project containing everything a
consumer of the GitHub Release needs.

Per board, stages ./release/<board>/ and zips it to ./release/<board>-<version>.zip with:

  - schematic.pdf            full schematic, all sheets
  - pcb_copper_top.pdf       board views (one PDF each)
  - pcb_copper_bottom.pdf
  - pcb_copper_in<N>_cu.pdf  one per inner copper layer
  - pcb_silk_top.pdf
  - pcb_silk_bottom.pdf
  - gerbers/                 Gerber files + Excellon drill (PTH/NPTH separate)
  - bom.csv                  JLCPCB BOM   (Comment, Designator, Footprint, LCSC Part #)
  - cpl.csv                  JLCPCB CPL   (Designator, Val, Package, Mid X/Y, Rotation, Layer)

Gerbers, drill files and the CPL all use the board's drill/place file origin. The
BOM comes from scripts/export_bom.py (its output is redirected here; the tracked
bom/ files are not touched).

Every board lives under hardware/<board>/<board>.* (default board: the only one under hardware/).
If any export step fails, no zip is written and the script exits non-zero.

Usage:
    python3 scripts/export_release.py                       # version = today's date
    python3 scripts/export_release.py --version v1.2.3
    python3 scripts/export_release.py --kicad-cli "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as _dt
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project  # noqa: E402  (repo root and board, hardware-project skill)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = project.root()
HW_DIR = PROJECT_ROOT / "hardware"
RELEASE_DIR = PROJECT_ROOT / "release"

DEFAULT_BOARD = project.default_board(PROJECT_ROOT)

# Set per board by _resolve_project().
PROJECT_NAME = DEFAULT_BOARD
SCH_FILE = HW_DIR / DEFAULT_BOARD / f"{DEFAULT_BOARD}.kicad_sch"
PCB_FILE = HW_DIR / DEFAULT_BOARD / f"{DEFAULT_BOARD}.kicad_pcb"
STAGE_DIR = RELEASE_DIR / DEFAULT_BOARD
GERBER_DIR = STAGE_DIR / "gerbers"

TECH_LAYERS = [
    "F.Paste", "B.Paste",
    "F.Silkscreen", "B.Silkscreen",
    "F.Mask", "B.Mask",
    "Edge.Cuts",
]

# Board views rendered to PDF (kept as PDF). Edge.Cuts is added to each for
# outline context. Inner copper views are added at runtime.
PCB_VIEWS = [
    ("pcb_copper_top.pdf",    ["F.Cu", "Edge.Cuts"]),
    ("pcb_copper_bottom.pdf", ["B.Cu", "Edge.Cuts"]),
    ("pcb_silk_top.pdf",      ["F.Silkscreen", "Edge.Cuts"]),
    ("pcb_silk_bottom.pdf",   ["B.Silkscreen", "Edge.Cuts"]),
]

CLI_CANDIDATES = [
    r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
]

# Labels of the steps that failed; any entry blocks the zip.
FAILED: list[str] = []


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
    fallback = ["F.Cu", "B.Cu"]
    try:
        text = pcb_path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return fallback
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
    found = re.findall(r'\(\s*(\d+)\s+"([^"]+\.Cu)"\s+\w+', block)
    if not found:
        return fallback
    layers = [name for _, name in sorted(found, key=lambda t: int(t[0]))]
    if "B.Cu" in layers:
        layers = [l for l in layers if l != "B.Cu"] + ["B.Cu"]
    return layers


def run(cli: str, args: list[str], label: str) -> bool:
    cmd = [cli] + args
    print(f"\n>>> {label}")
    print("    " + " ".join(f'"{a}"' if " " in a else a for a in cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.stdout.strip():
        print("    " + res.stdout.strip().replace("\n", "\n    "))
    if res.returncode != 0:
        print(f"    [FAIL exit {res.returncode}] {res.stderr.strip()}")
        FAILED.append(label)
        return False
    print("    [OK]")
    return True


def _stamp() -> str:
    return _dt.date.today().isoformat()


def run_export_bom(sch: Path, work: Path) -> bool:
    """Run scripts/export_bom.py on `sch` with its output in work/bom/
    (bom_jlc.csv: JLCPCB format). export_bom.py writes under its ROOT;
    pointing ROOT at `work` keeps the tracked bom/ files untouched."""
    sys.path.insert(0, str(SCRIPT_DIR))
    import export_bom

    (work / "bom").mkdir(parents=True, exist_ok=True)
    saved_root, saved_argv = export_bom.ROOT, sys.argv
    export_bom.ROOT, sys.argv = work, [str(SCRIPT_DIR / "export_bom.py"), str(sch)]
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            export_bom.main()
    except subprocess.CalledProcessError as e:
        print(f"    [FAIL exit {e.returncode}] {(e.stderr or b'').decode(errors='replace').strip()}")
        return False
    finally:
        export_bom.ROOT, sys.argv = saved_root, saved_argv
    print("    " + log.getvalue().split(" -> ")[0].strip())
    return True


# ---------------------------------------------------------------------------
# Build steps
# ---------------------------------------------------------------------------

def export_schematic_pdf(cli: str) -> None:
    run(cli, ["sch", "export", "pdf",
              "-o", str(STAGE_DIR / "schematic.pdf"),
              str(SCH_FILE)],
        "Schematic PDF")


def export_board_pdfs(cli: str) -> None:
    copper = detect_copper_layers(PCB_FILE)
    inner = [l for l in copper if l not in ("F.Cu", "B.Cu")]
    views = list(PCB_VIEWS)
    for layer in inner:
        fname = "pcb_copper_" + layer.replace(".", "_").lower() + ".pdf"
        views.append((fname, [layer, "Edge.Cuts"]))
    for fname, layers in views:
        run(cli, ["pcb", "export", "pdf",
                  "-o", str(STAGE_DIR / fname),
                  "--layers", ",".join(layers),
                  "--mode-single", "--scale", "0",
                  str(PCB_FILE)],
            f"Board PDF: {fname}")


def export_gerbers(cli: str) -> None:
    GERBER_DIR.mkdir(parents=True, exist_ok=True)
    for f in GERBER_DIR.glob("*"):
        if f.is_file():
            f.unlink()
    copper = detect_copper_layers(PCB_FILE)
    gerber_layers = copper + TECH_LAYERS
    print(f"\n    detected copper layers: {', '.join(copper)}")
    run(cli, ["pcb", "export", "gerbers",
              "-o", str(GERBER_DIR) + os.sep,
              "--layers", ",".join(gerber_layers),
              "--subtract-soldermask",
              "--use-drill-file-origin",
              str(PCB_FILE)],
        "Gerbers")
    run(cli, ["pcb", "export", "drill",
              "-o", str(GERBER_DIR) + os.sep,
              "--format", "excellon",
              "--drill-origin", "plot",
              "--excellon-separate-th",
              "--generate-map", "--map-format", "gerberx2",
              str(PCB_FILE)],
        "Drill files (Excellon, PTH/NPTH separate)")


def export_bom() -> None:
    label = "BOM (scripts/export_bom.py, JLCPCB columns)"
    print(f"\n>>> {label}")
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        if not run_export_bom(SCH_FILE, work):
            FAILED.append(label)
            return
        shutil.copyfile(work / "bom" / "bom_jlc.csv", STAGE_DIR / "bom.csv")
    print("    [OK] -> bom.csv")


def export_cpl(cli: str) -> None:
    raw = STAGE_DIR / "_pos_raw.csv"
    ok = run(cli, ["pcb", "export", "pos",
                   "-o", str(raw),
                   "--format", "csv", "--units", "mm",
                   "--side", "both",
                   "--use-drill-file-origin",
                   "--exclude-dnp",
                   str(PCB_FILE)],
             "Placement (raw)")
    if not ok or not raw.exists():
        return
    cpl = STAGE_DIR / "cpl.csv"
    with raw.open(newline="", encoding="utf-8") as fin, \
         cpl.open("w", newline="", encoding="utf-8") as fout:
        reader = csv.DictReader(fin)
        writer = csv.writer(fout)
        writer.writerow(["Designator", "Val", "Package",
                         "Mid X", "Mid Y", "Rotation", "Layer"])
        for r in reader:
            side = (r.get("Side") or "").strip().lower()
            layer = "Top" if side.startswith("t") else "Bottom"
            writer.writerow([
                r.get("Ref", ""), r.get("Val", ""), r.get("Package", ""),
                r.get("PosX", ""), r.get("PosY", ""), r.get("Rot", ""),
                layer,
            ])
    raw.unlink()
    print("\n>>> CPL\n    [OK] -> cpl.csv")


def zip_bundle(version: str) -> Path:
    zip_path = RELEASE_DIR / f"{PROJECT_NAME}-{version}.zip"
    if zip_path.exists():
        zip_path.unlink()
    files = sorted(p for p in STAGE_DIR.rglob("*") if p.is_file())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=str(f.relative_to(STAGE_DIR)))
    print(f"\n>>> Release zip\n    [OK] {zip_path.name}  ({len(files)} files)")
    return zip_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _resolve_project(name: str | None, pcb: str | None) -> None:
    global PROJECT_NAME, SCH_FILE, PCB_FILE, STAGE_DIR, GERBER_DIR
    if pcb:
        stem = Path(pcb).with_suffix("")
        PCB_FILE = Path(pcb)
        SCH_FILE = stem.with_suffix(".kicad_sch")
        PROJECT_NAME = name or stem.name
    else:
        name = name or DEFAULT_BOARD
        base = HW_DIR / name / name
        SCH_FILE = base.with_suffix(".kicad_sch")
        PCB_FILE = base.with_suffix(".kicad_pcb")
        PROJECT_NAME = name
    STAGE_DIR = RELEASE_DIR / PROJECT_NAME
    GERBER_DIR = STAGE_DIR / "gerbers"


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a per-board release bundle.")
    ap.add_argument("--kicad-cli", help="Path to kicad-cli")
    ap.add_argument("--name", help=f"Board basename under hardware/<name>/ (default: {DEFAULT_BOARD})")
    ap.add_argument("--pcb", help="Explicit path to a .kicad_pcb (overrides --name)")
    ap.add_argument("--version", help="Version label for the zip name (default: today's date)")
    args = ap.parse_args()

    _resolve_project(args.name, args.pcb)
    version = args.version or _stamp()

    for f in (SCH_FILE, PCB_FILE):
        if not f.exists():
            sys.exit(f"Missing project file: {f}")

    cli = find_cli(args.kicad_cli)

    # Fresh staging dir so a stale file can't leak into the bundle.
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)
    STAGE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"kicad-cli : {cli}")
    print(f"project   : {PCB_FILE.parent}")
    print(f"bundle    : {PROJECT_NAME}-{version}.zip")

    export_schematic_pdf(cli)
    export_board_pdfs(cli)
    export_gerbers(cli)
    export_bom()
    export_cpl(cli)

    if FAILED:
        sys.exit("\nRelease bundle NOT built; failed steps:\n  " + "\n  ".join(FAILED))

    zip_path = zip_bundle(version)
    print(f"\nDone. Release bundle: {zip_path}")


if __name__ == "__main__":
    main()
