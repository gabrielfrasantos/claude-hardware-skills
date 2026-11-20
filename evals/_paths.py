"""The placement geometry and metrics live in the pcb-placement skill; the evals measure with the same code."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "plugins" / "hardware-design" / "skills"
                       / "pcb-placement" / "scripts"))
