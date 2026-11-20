"""Where the board repo is and which board to work on, for the hardware-project scripts.

The scripts run from anywhere inside a board repo laid out as hardware/<board>/<board>.kicad_pro (the e-psu /
e-foc / e-inverted-pendulum layout). The repo root is the git top level of the working directory, or
$HW_PROJECT_ROOT; the default board is the only one under hardware/, or $HW_BOARD. Outputs go to fixed folders
at the root (review_exports/, manufacturing/, release/, bom/, datasheets/), which the scaffold's .gitignore lists.
"""
import os
import subprocess
from pathlib import Path


def root():
    env = os.environ.get("HW_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else Path.cwd().resolve()


def boards(at=None):
    hw = (at or root()) / "hardware"
    return sorted(p.parent.name for p in hw.glob("*/*.kicad_pro") if p.stem == p.parent.name) if hw.is_dir() else []


def default_board(at=None):
    """$HW_BOARD, else the only board under hardware/, else the first (pass --name to choose)."""
    env = os.environ.get("HW_BOARD")
    if env:
        return env
    found = boards(at)
    return found[0] if found else "board"
