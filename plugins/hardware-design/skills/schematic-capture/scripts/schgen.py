#!/usr/bin/env python3
"""schgen.py: build a KiCad 10 schematic from Python sheet descriptions, and check it (schematic-capture skill).

    schgen.py build        <config.py> [--no-upgrade]
    schgen.py check        <config.py>                         KiCad's netlist == the intended connectivity
    schgen.py equivalence  <config.py> <git-rev | file.net> [--allow-renames]    same circuit as a reference

The board repo keeps a config.py (next to its sheet modules) with:
    NAME = "my-board"                         project name: <OUT>/<NAME>.kicad_sch is the root sheet
    TITLE = "my-board: what it is"
    OUT = "../../hardware/my-board"           where the .kicad_sch files go (relative to config.py)
    MODULES = ["power", "mcu", ...]           sheet modules in DESIGN, in sheet order; each has build(project, values)
    DESIGN = "design"                         (optional, default "design")
    VALUES = "values.json"                    (optional) component values passed to every build()
    EXPECTED = "expected.json"                (optional) where the intended connectivity is written
    DATE, REV, COMPANY, COMMENTS              (optional) title block
    ROOT_NOTES = [(text, x, y, size, bold)]   (optional) the root page's text
    POWER_SYMBOLS = {"GND": "power:GND", "+3V3": "power:+3V3"}   (optional) nets drawn as power symbols
    PROJECT_LIBRARIES = {"my-board": "../../hardware/my-board/my-board.kicad_sym"}   (optional)
    SYMBOL_DIR = None                         (optional) KiCad's symbols folder; default: found, or $KICAD10_SYMBOL_DIR

build   runs every module's build(), refuses pins with neither a net nor a no-connect and duplicate references,
        writes the sheets and the root page (deterministic UUIDs: a rebuild is byte-identical), writes expected.json,
        normalises the files with `kicad-cli sch upgrade` when KiCad is installed, and prints the layout lint.
        Exit 1 on a problem or any lint.
check   exports KiCad's netlist and compares it with expected.json: same nets, same names, no extra pins.
equivalence  after a drawing-only change: same parts, fields and pin-to-net partition as a git revision or netlist.
"""
import argparse
import importlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "schgen"))
import library  # noqa: E402
import netlist  # noqa: E402
from sch import Project  # noqa: E402


def load_config(path):
    path = pathlib.Path(path).resolve()
    spec = importlib.util.spec_from_file_location("schgen_config", path)
    cfg = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(cfg)
    base = path.parent
    c = dict(
        name=cfg.NAME, title=cfg.TITLE, out=(base / cfg.OUT).resolve(), modules=list(cfg.MODULES),
        design=(base / getattr(cfg, "DESIGN", "design")).resolve(),
        values=(base / cfg.VALUES) if getattr(cfg, "VALUES", None) else None,
        expected=base / getattr(cfg, "EXPECTED", "expected.json"),
        date=getattr(cfg, "DATE", ""), rev=getattr(cfg, "REV", "A"), company=getattr(cfg, "COMPANY", ""),
        comments=list(getattr(cfg, "COMMENTS", [])), root_notes=list(getattr(cfg, "ROOT_NOTES", [])),
        power=getattr(cfg, "POWER_SYMBOLS", None), power_natural=getattr(cfg, "POWER_NATURAL", None),
        libraries={k: (base / v).resolve() for k, v in getattr(cfg, "PROJECT_LIBRARIES", {}).items()},
        symbol_dir=getattr(cfg, "SYMBOL_DIR", None), base=base)
    c["schematic"] = c["out"] / f"{c['name']}.kicad_sch"
    library.configure(c["symbol_dir"], c["libraries"])
    sys.path.insert(0, str(c["design"]))
    return c


def build(c, upgrade=True, log=print):
    values = json.loads(c["values"].read_text(encoding="utf-8")) if c["values"] else {}
    project = Project(c["name"], c["title"], date=c["date"], rev=c["rev"], company=c["company"],
                      comments=c["comments"], power_symbols=c["power"], power_natural=c["power_natural"])
    for name in c["modules"]:
        importlib.import_module(name).build(project, values)
    problems = project.problems()
    for p in problems:
        log("PROBLEM", p)
    if problems:
        return 1, project
    project.build(c["out"], c["root_notes"])
    c["expected"].write_text(project.expected_json(), encoding="utf-8")
    cli = shutil.which("kicad-cli")
    if upgrade and cli:
        for path in sorted(c["out"].glob("*.kicad_sch")):
            subprocess.run([cli, "sch", "upgrade", "--force", str(path)], check=True, capture_output=True)
    elif upgrade:
        log("kicad-cli not found: files not normalised by `kicad-cli sch upgrade` (KiCad rewrites them on save)")
    for line in project.lint:
        log("LINT", line)
    count = len({p.ref for s in project.sheets for p in s.parts if not p.ref.startswith("#")})
    log(f"wrote {len(project.sheets)} sheets, {count} parts to {c['out']}; layout lint {len(project.lint)}")
    return (1 if project.lint else 0), project


def check(c, log=print):
    expected = {k: {tuple(n) for n in v} for k, v in json.loads(c["expected"].read_text()).items()}
    with tempfile.TemporaryDirectory() as tmp:
        out = netlist.export_netlist(c["schematic"], pathlib.Path(tmp) / "check.net")
        _, nets = netlist.read(out)
    problems = netlist.compare_expected(expected, nets)
    log("\n".join(problems) if problems else f"netlist matches intent ({len(expected)} nets)")
    return 1 if problems else 0


def equivalence(c, reference, allow_renames=False, log=print):
    root = subprocess.run(["git", "-C", str(c["base"]), "rev-parse", "--show-toplevel"], capture_output=True,
                          text=True).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        ref = pathlib.Path(reference)
        ref_net = ref if ref.suffix == ".net" and ref.exists() else netlist.netlist_from_rev(root, c["schematic"],
                                                                                              reference, tmp)
        cur_net = netlist.export_netlist(c["schematic"], tmp / "current.net")
        ref_data, cur_data = netlist.read(ref_net), netlist.read(cur_net)
    problems, renames = netlist.compare(ref_data, cur_data, allow_renames)
    for line in renames if allow_renames else []:
        log("RENAME", line)
    for line in problems:
        log("DIFF", line)
    parts, nets = len(cur_data[0]), len([n for n in cur_data[1] if not n.startswith("unconnected-")])
    log(f"{'EQUIVALENT' if not problems else 'DIFFERENT'}: {parts} parts, {nets} connected nets compared with {reference}")
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("config")
    b.add_argument("--no-upgrade", action="store_true", help="skip `kicad-cli sch upgrade`")
    k = sub.add_parser("check")
    k.add_argument("config")
    e = sub.add_parser("equivalence")
    e.add_argument("config")
    e.add_argument("reference", help="git revision or .net file")
    e.add_argument("--allow-renames", action="store_true")
    a = ap.parse_args(argv)
    c = load_config(a.config)
    if a.cmd == "build":
        return build(c, upgrade=not a.no_upgrade)[0]
    if a.cmd == "check":
        return check(c)
    return equivalence(c, a.reference, a.allow_renames)


if __name__ == "__main__":
    sys.exit(main())
