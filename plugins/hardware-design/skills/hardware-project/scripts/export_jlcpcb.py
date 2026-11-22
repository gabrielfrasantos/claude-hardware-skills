#!/usr/bin/env python3
"""
Export a JLCPCB fabrication + assembly package for a KiCad 10 board (hardware/<board>/<board>.*).

Produces, under ./manufacturing/<board>/ (default board: the only one under hardware/):

  Fabrication
    - gerbers/                       one Gerber file per layer + Excellon drill files
    - <board>-gerbers-<date>.zip     the gerbers/ folder zipped -> upload to JLCPCB
                                     "Add gerber file" (fabrication step)

  Assembly (SMT / PCBA)
    - bom.csv                  JLCPCB BOM   (Comment, Designator, Footprint,
                               "LCSC Part #")   -> "Add BOM file"
    - cpl.csv                  JLCPCB placement (Designator, Val, Package,
                               Mid X, Mid Y, Rotation, Layer) -> "Add CPL file"
    - stock_check.json         only with --stock-check: scripts/jlc_stock.py result

Gerbers, drill files and the CPL all use the board's drill/place file origin, so
their coordinates line up.

The BOM comes from scripts/export_bom.py (grouped by LCSC number, DNP parts and
parts without an LCSC number left out, the latter listed by reference). Its output
is redirected here; the tracked bom/ files are not touched. The BOM and CPL are then
checked against the board (assembly.py): a fitted part missing from either, a BOM
line for a part that is not fitted, or a malformed file is named and makes the
script exit non-zero. Parts marked Assembly = hand may be absent.

Usage:
    python3 scripts/export_jlcpcb.py
    python3 scripts/export_jlcpcb.py --stock-check --boards 5   # also check JLCPCB stock
    python3 scripts/export_jlcpcb.py --no-assembly              # gerbers + zip only
    python3 scripts/export_jlcpcb.py --kicad-cli "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"
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
import assembly  # noqa: E402  (BOM/CPL against the board)
import project  # noqa: E402  (repo root and board, hardware-project skill)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = project.root()
HW_DIR = PROJECT_ROOT / "hardware"

DEFAULT_BOARD = project.default_board(PROJECT_ROOT)

PROJECT_NAME = DEFAULT_BOARD
SCH_FILE = HW_DIR / DEFAULT_BOARD / f"{DEFAULT_BOARD}.kicad_sch"
PCB_FILE = HW_DIR / DEFAULT_BOARD / f"{DEFAULT_BOARD}.kicad_pcb"

OUT_DIR = PROJECT_ROOT / "manufacturing" / DEFAULT_BOARD
GERBER_DIR = OUT_DIR / "gerbers"

# Non-copper (technical) layers JLCPCB expects. Copper layers are detected from
# the board at runtime, see detect_copper_layers().
TECH_LAYERS = [
    "F.Paste", "B.Paste",
    "F.Silkscreen", "B.Silkscreen",
    "F.Mask", "B.Mask",
    "Edge.Cuts",
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


def _stamp() -> str:
    return _dt.date.today().isoformat()


def run_export_bom(sch: Path, work: Path, cli: str = "kicad-cli") -> bool:
    """Run scripts/export_bom.py on `sch` with its output in work/bom/
    (bom.csv: stock-check format, bom_jlc.csv: JLCPCB format). export_bom.py
    writes under its ROOT; pointing ROOT at `work` keeps the tracked bom/ files
    untouched."""
    sys.path.insert(0, str(SCRIPT_DIR))
    import export_bom

    (work / "bom").mkdir(parents=True, exist_ok=True)
    saved_root, saved_argv = export_bom.ROOT, sys.argv
    export_bom.ROOT, sys.argv = work, [str(SCRIPT_DIR / "export_bom.py"), str(sch), "--kicad-cli", cli]
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            export_bom.main()
    except subprocess.CalledProcessError as e:
        print(f"    [FAIL exit {e.returncode}] {(e.stderr or b'').decode(errors='replace').strip()}")
        return False
    except OSError as e:                     # kicad-cli not runnable
        print(f"    [FAIL] {cli}: {e}")
        return False
    finally:
        export_bom.ROOT, sys.argv = saved_root, saved_argv
    for line in log.getvalue().strip().splitlines():
        print("    " + line.split(" -> ")[0].strip())
    return True


# ---------------------------------------------------------------------------
# Fabrication: gerbers + drill + zip
# ---------------------------------------------------------------------------

def export_gerbers(cli: str) -> None:
    GERBER_DIR.mkdir(parents=True, exist_ok=True)

    # Wipe every stale plot output so a previous run's layers can't linger
    # and mislead the fab.
    for f in GERBER_DIR.glob("*"):
        if f.is_file():
            f.unlink()

    copper = detect_copper_layers(PCB_FILE)
    gerber_layers = copper + TECH_LAYERS
    print(f"\n    detected copper layers: {', '.join(copper)}")

    # Protel filename extensions (.GTL/.GBL/...), the kicad-cli default, are
    # what JLCPCB's parser recognises most reliably. --subtract-soldermask
    # keeps silkscreen off exposed pads.
    run(cli, ["pcb", "export", "gerbers",
              "-o", str(GERBER_DIR) + os.sep,
              "--layers", ",".join(gerber_layers),
              "--subtract-soldermask",
              "--use-drill-file-origin",
              str(PCB_FILE)],
        "Gerbers (layer by layer)")

    run(cli, ["pcb", "export", "drill",
              "-o", str(GERBER_DIR) + os.sep,
              "--format", "excellon",
              "--drill-origin", "plot",
              "--excellon-separate-th",
              "--generate-map", "--map-format", "gerberx2",
              str(PCB_FILE)],
        "Drill files (Excellon, PTH/NPTH separate)")


def zip_gerbers() -> Path:
    zip_path = OUT_DIR / f"{PROJECT_NAME}-gerbers-{_stamp()}.zip"
    for old in OUT_DIR.glob(f"{PROJECT_NAME}-gerbers-*.zip"):
        old.unlink()
    files = sorted(p for p in GERBER_DIR.iterdir() if p.is_file())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            # Flat archive (no gerbers/ prefix): JLCPCB expects files at root.
            zf.write(f, arcname=f.name)
    print(f"\n>>> Gerber zip\n    [OK] {zip_path.name}  ({len(files)} files)")
    return zip_path


# ---------------------------------------------------------------------------
# Assembly: BOM + CPL in JLCPCB column format
# ---------------------------------------------------------------------------

def export_bom(work: Path, cli: str) -> bool:
    """JLCPCB BOM (Comment, Designator, Footprint, LCSC Part #) from
    scripts/export_bom.py. The stock-check BOM stays in work/bom/bom.csv."""
    print("\n>>> JLCPCB BOM (scripts/export_bom.py)")
    if not run_export_bom(SCH_FILE, work, cli):
        return False
    shutil.copyfile(work / "bom" / "bom_jlc.csv", OUT_DIR / "bom.csv")
    print("    [OK] -> bom.csv")
    return True


def export_cpl(cli: str) -> bool:
    """JLCPCB CPL (component placement list). kicad-cli emits Ref/Val/Package/
    PosX/PosY/Rot/Side; rewrite the header + Side values to JLCPCB's schema.
    The drill-file origin matches the gerbers and drill files."""
    raw = OUT_DIR / "_pos_raw.csv"
    ok = run(cli, ["pcb", "export", "pos",
                   "-o", str(raw),
                   "--format", "csv",
                   "--units", "mm",
                   "--side", "both",
                   "--use-drill-file-origin",
                   "--exclude-dnp",
                   str(PCB_FILE)],
             "Placement (raw, kicad columns)")
    if not ok:
        return False
    if not raw.exists():
        print(f"    [FAIL] kicad-cli exited 0 but wrote no {raw.name}")
        return False

    cpl = OUT_DIR / "cpl.csv"
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
    print("\n>>> JLCPCB CPL\n    [OK] -> cpl.csv")
    return True


def check_bom_vs_cpl() -> list[str]:
    """Every fitted part in the BOM and the CPL, both files well-formed (assembly.py). Returns the errors."""
    print("\n>>> BOM and CPL against the board")
    res = assembly.check_package(PCB_FILE, OUT_DIR / "bom.csv", OUT_DIR / "cpl.csv")
    for n in res["notes"]:
        print(f"    note: {n}")
    for e in res["errors"]:
        print(f"    [FAIL] {e}")
    if not res["errors"]:
        print("    [OK] every fitted part is in the BOM and the CPL")
    return res["errors"]


def stock_check(work: Path, boards: int) -> None:
    """Check the BOM against JLCPCB stock with scripts/jlc_stock.py."""
    print(f"\n>>> JLCPCB stock check (scripts/jlc_stock.py, {boards} boards)")
    res = subprocess.run([sys.executable, str(SCRIPT_DIR / "jlc_stock.py"),
                          str(work / "bom" / "bom.csv"), "--boards", str(boards),
                          "--json", str(OUT_DIR / "stock_check.json")],
                         capture_output=True, text=True)
    if res.stdout.strip():
        print("    " + res.stdout.strip().replace("\n", "\n    "))
    if res.returncode != 0:
        print(f"    [FAIL exit {res.returncode}] {res.stderr.strip()}")
    else:
        print("    [OK] -> stock_check.json")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _resolve_project(name: str | None, pcb: str | None) -> None:
    """Point path globals at the chosen project. Every board lives under
    hardware/<name>/<name>.* and writes to manufacturing/<name>/. The default
    board is the only one under hardware/. --name <basename> selects another board;
    --pcb gives an explicit .kicad_pcb."""
    global PROJECT_NAME, SCH_FILE, PCB_FILE, OUT_DIR, GERBER_DIR

    if pcb:
        stem = Path(pcb).with_suffix("")
        PCB_FILE = Path(pcb)
        SCH_FILE = stem.with_suffix(".kicad_sch")
        PROJECT_NAME = name or stem.name
        OUT_DIR = PROJECT_ROOT / "manufacturing" / PROJECT_NAME
    else:
        name = name or DEFAULT_BOARD
        base = HW_DIR / name / name
        SCH_FILE = base.with_suffix(".kicad_sch")
        PCB_FILE = base.with_suffix(".kicad_pcb")
        PROJECT_NAME = name
        OUT_DIR = PROJECT_ROOT / "manufacturing" / name

    GERBER_DIR = OUT_DIR / "gerbers"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Export a JLCPCB fabrication + assembly package.")
    ap.add_argument("--kicad-cli", help="Path to kicad-cli")
    ap.add_argument("--name", help="Project basename under hardware/<name>/ "
                    f"(default: {DEFAULT_BOARD})")
    ap.add_argument("--pcb", help="Explicit path to a .kicad_pcb (overrides --name)")
    ap.add_argument("--no-assembly", action="store_true",
                    help="Gerbers + zip only; skip BOM/CPL (e.g. hand-soldered boards)")
    ap.add_argument("--stock-check", action="store_true",
                    help="Check the BOM against JLCPCB stock (scripts/jlc_stock.py, needs network)")
    ap.add_argument("--boards", type=int, default=5,
                    help="Board count for --stock-check (default: 5)")
    args = ap.parse_args()

    _resolve_project(args.name, args.pcb)

    needed = (PCB_FILE,) if args.no_assembly else (SCH_FILE, PCB_FILE)
    for f in needed:
        if not f.exists():
            sys.exit(f"Missing project file: {f}")

    cli = find_cli(args.kicad_cli)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"kicad-cli : {cli}")
    print(f"project   : {PCB_FILE.parent}")
    print(f"output    : {OUT_DIR}")

    export_gerbers(cli)
    zip_path = zip_gerbers()

    problems: list[str] = []
    if not args.no_assembly:
        for stale in ("stock_check.json", "bom.csv", "cpl.csv"):   # a failed step must not leave the last run's file
            (OUT_DIR / stale).unlink(missing_ok=True)
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            bom_ok = export_bom(work, cli)
            cpl_ok = export_cpl(cli)
            problems += [] if bom_ok else ["BOM export failed"]
            problems += [] if cpl_ok else ["CPL export failed"]
            if bom_ok and cpl_ok:
                problems += check_bom_vs_cpl()
            if args.stock_check and bom_ok:
                stock_check(work, args.boards)

    print("\nDone.")
    print(f"  Fabrication : upload {zip_path.name}")
    if not args.no_assembly:
        if problems:
            sys.exit("  Assembly    : NOT ready, do not upload:\n    " + "\n    ".join(problems))
        print("  Assembly    : upload bom.csv (BOM) and cpl.csv (CPL)")


if __name__ == "__main__":
    main()
