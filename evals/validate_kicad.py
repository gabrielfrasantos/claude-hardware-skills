#!/usr/bin/env python3
"""Phase B of docs/design.md §9: run every script that writes a KiCad file on a copy of a real board and let
KiCad 10 itself load, DRC and ERC the result.

    validate_kicad.py <board repo> [--board NAME] [--kicad-cli PATH] [--out DIR] [--steps B1,B2,...]
                      [--mcu U301 --needs pin-data/pin-needs.txt] [--pcbdoc reference/x.PcbDoc] [--voltage NET=V]

Nothing in the board repo is changed: each step works on its own copy of hardware/<board>/ under DIR (default
./validate-kicad). Writes DIR/validation.md and validation.json: one row per step, PASS / FAIL / SKIP, with the
evidence, and the checks that need the KiCad window (MANUAL) listed with what to look at.

  B0  environment       kicad-cli version, Python, the plugin's commit
  B1  rules apply       pcb_rules.py apply: rules file loads (canary), board loads, teardrop flags set
  B2  rules check       pcb_rules.py check with KiCad DRC: runs, DRC included, KiCad's own DRC count recorded
  B3  net classes       netclasses.py apply: project and board still load
  B4  placement         place.py optimize --refine on a copy: board loads, gate valid; pins.py with --mcu/--needs
  B5  schematic         KiCad ERC loads every sheet; schgen.py check when the repo has scripts/schgen/config.py
  B6  reference block   refblock.py round trip on the board's largest IC and its neighbours (parts moved away,
                        copper stripped, block placed back): the result loads and the parts land back exactly;
                        refblock.py import with --pcbdoc
  B7  review netlist    review.py with kicad-cli: the exported netlist parses and connects the same pins as the board
  B8  exports           export_review.py and export_jlcpcb.py produce their packages
  B9  network           jlc_stock.py on the repo's BOM, fetch_datasheet.py on one part, easyeda2kicad installed
"""

import argparse
import datetime
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "hardware-design" / "skills"
sys.path.insert(0, str(SKILLS / "design-review" / "scripts"))
sys.path.insert(0, str(SKILLS / "reference-block" / "scripts"))

ALL = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9"]
MANUAL = [
    ("B1", "Open the B1 copy in KiCad 10: Edit > Edit Teardrops > Apply, save, then `pcb_rules.py check` on it: "
           "teardrops_missing near 0."),
    ("B3", "In the B1 copy, Board Setup > Net Classes shows the standard classes with the widths netclasses.py printed."),
    ("B4", "Open the B4 copy: parts sit where the gate report says; nothing overlaps on screen."),
    ("B6", "Open the B6 result: the copied block is one group; DRC shows only findings the original board had there."),
    ("B8", "Upload the B8 Gerbers, BOM and CPL to JLCPCB's viewer: layers, drill and part rotations are right."),
]


def script(skill, name):
    return str(SKILLS / skill / "scripts" / name)


def py(args, env=None, cwd=None, timeout=1800):
    e = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", **(env or {}))   # Windows consoles are not UTF-8
    r = subprocess.run([sys.executable] + [str(a) for a in args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=e, cwd=cwd, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def tail(text, n=400):
    return text.strip()[-n:]


def loads(cli, path, out):
    """(ok, detail): KiCad 10 loads the board (DRC) or schematic (ERC) without error."""
    sch = str(path).endswith(".kicad_sch")
    rpt = os.path.join(out, os.path.basename(str(path)) + (".erc.json" if sch else ".drc.json"))
    cmd = [cli, "sch" if sch else "pcb", "erc" if sch else "drc", "--format", "json", "-o", rpt, str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.exists(rpt):
        return False, tail(r.stdout + r.stderr) or f"exit {r.returncode}"
    with open(rpt, encoding="utf-8") as f:
        data = json.load(f)
    n = len(data.get("violations", [])) + sum(len(s.get("violations", [])) for s in data.get("sheets", []))
    return True, f"{'ERC' if sch else 'DRC'} ran, {n} violation(s)"


def row(step, name, status, evidence, artifacts=None):
    return dict(step=step, name=name, status=status, evidence=evidence, artifacts=artifacts or [])


class Kit:
    def __init__(self, a):
        self.repo = pathlib.Path(a.repo).resolve()
        boards = sorted(p.parent.name for p in (self.repo / "hardware").glob("*/*.kicad_pro") if p.stem == p.parent.name)
        self.board = a.board or (boards[0] if len(boards) == 1 else None)
        if not self.board:
            sys.exit(f"pass --board, one of: {', '.join(boards) or 'none found under hardware/'}")
        self.src = self.repo / "hardware" / self.board
        self.out = pathlib.Path(a.out).resolve()
        self.cli = a.kicad_cli or os.environ.get("KICAD_CLI") or shutil.which("kicad-cli")
        self.a = a
        self.out.mkdir(parents=True, exist_ok=True)

    def copy(self, tag):
        """A fresh copy of the repo's hardware/<board>/ (plus bom/) as DIR/<tag>/, laid out like a board repo."""
        root = self.out / tag
        if root.exists():
            shutil.rmtree(root)
        shutil.copytree(self.src, root / "hardware" / self.board)
        if (self.repo / "bom").is_dir():
            shutil.copytree(self.repo / "bom", root / "bom")
        stem = root / "hardware" / self.board / self.board
        return root, stem

    # -------------------------------------------------------------------------------------------- steps
    def B0(self):
        if not self.cli:
            return row("B0", "environment", "FAIL", "kicad-cli not found: install KiCad 10 or pass --kicad-cli")
        r = subprocess.run([self.cli, "version"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        version = (r.stdout or r.stderr).strip()
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
        ok = bool(re.match(r"^(1\d|[2-9]\d)\.", version))
        return row("B0", "environment", "PASS" if ok else "FAIL",
                   f"kicad-cli {version or '?'}; Python {platform.python_version()}; plugin {commit.stdout.strip()}"
                   + ("" if ok else "; KiCad 10 or later is required"))

    def B1(self):
        root, stem = self.copy("B1")
        code, text = py([script("pcb-design-rules", "pcb_rules.py"), "apply", f"{stem}.kicad_pro", "--fab", "jlcpcb",
                         "--netclasses", "--kicad-cli", self.cli])
        ok, detail = loads(self.cli, f"{stem}.kicad_pcb", self.out)
        flags = pathlib.Path(f"{stem}.kicad_pcb").read_text(encoding="utf-8").count("(enabled yes)")
        good = code == 0 and "loads OK" in text and ok and flags > 0
        return row("B1", "rules apply", "PASS" if good else "FAIL",
                   f"apply exit {code}, {'rules load (canary fired)' if 'loads OK' in text else 'rules NOT confirmed'}; "
                   f"board: {detail}; {flags} teardrop flag(s) on" + ("" if good else f"; output: {tail(text, 300)}"),
                   [f"{stem}.kicad_pcb"])

    def B2(self):
        stem = self.out / "B1" / "hardware" / self.board / self.board
        if not pathlib.Path(f"{stem}.kicad_pcb").exists():
            self.B1()
        js = self.out / "B2.rules.json"
        code, text = py([script("pcb-design-rules", "pcb_rules.py"), "check", f"{stem}.kicad_pcb", "--kicad-cli",
                         self.cli, "--json", js])
        if not js.exists():
            return row("B2", "rules check", "FAIL", f"no JSON: {tail(text)}")
        data = json.loads(js.read_text(encoding="utf-8"))
        drc = data.get("drc")
        ok, detail = loads(self.cli, f"{stem}.kicad_pcb", self.out)
        good = drc is not None and ok
        return row("B2", "rules check", "PASS" if good else "FAIL",
                   f"check exit {code} (1 = gates failed, expected on a board not set up this way); "
                   f"DRC inside check: {'yes' if drc is not None else 'NO'}; hard failures: "
                   f"{', '.join(x.split(' ')[0] for x in data.get('failures', [])) or 'none'}; KiCad's own run: {detail}",
                   [str(js)])

    def B3(self):
        stem = self.out / "B1" / "hardware" / self.board / self.board
        if not pathlib.Path(f"{stem}.kicad_pro").exists():
            self.B1()
        code, text = py([script("pcb-copper", "netclasses.py"), "apply", f"{stem}.kicad_pro"])
        ok, detail = loads(self.cli, f"{stem}.kicad_pcb", self.out)
        classes = [c.get("name") for c in json.loads(pathlib.Path(f"{stem}.kicad_pro").read_text(encoding="utf-8"))
                   .get("net_settings", {}).get("classes", [])]
        good = code == 0 and ok
        return row("B3", "net classes", "PASS" if good else "FAIL",
                   f"apply exit {code}; classes now: {', '.join(classes)}; board: {detail}"
                   + ("" if good else f"; output: {tail(text, 300)}"))

    def B4(self):
        root, stem = self.copy("B4")
        code, text = py([script("pcb-placement", "place.py"), "optimize", f"{stem}.kicad_pcb", "--refine", "--effort", "0.3"])
        ok, detail = loads(self.cli, f"{stem}.kicad_pcb", self.out)
        gcode, gate = py([script("pcb-placement", "place.py"), "gate", f"{stem}.kicad_pcb", "--assembly", "none"])
        valid = "Valid: **True**" in gate
        ev = f"optimize --refine exit {code}; board: {detail}; gate valid: {valid}"
        good = code == 0 and ok
        if self.a.mcu and self.a.needs:
            pcode, ptext = py([script("pcb-placement", "pins.py"), "assign", f"{stem}.kicad_pcb", "--mcu", self.a.mcu,
                               "--needs", self.repo / self.a.needs, "--out", self.out / "B4.pinmap.txt"])
            ev += f"; pins.py assign exit {pcode}"
            good = good and pcode == 0
        else:
            ev += "; pins.py not run (no --mcu/--needs)"
        return row("B4", "placement", "PASS" if good else "FAIL", ev + ("" if good else f"; {tail(text, 300)}"),
                   [f"{stem}.kicad_pcb"])

    def B5(self):
        root, stem = self.copy("B5")
        ok, detail = loads(self.cli, f"{stem}.kicad_sch", self.out)
        ev = f"ERC: {detail}"
        good = ok
        cfg = self.repo / "scripts" / "schgen" / "config.py"
        if cfg.exists():
            code, text = py([script("schematic-capture", "schgen.py"), "check", cfg], cwd=self.repo)
            ev += f"; schgen.py check exit {code}: {tail(text, 200)}"
            good = good and code == 0
        else:
            ev += "; schgen.py check not run (no scripts/schgen/config.py: the repo isn't on the plugin's schgen yet)"
        return row("B5", "schematic", "PASS" if good else "FAIL", ev)

    def B6(self):
        import refblock as RB
        from shapely.geometry import Polygon, box as shp_box
        root, stem = self.copy("B6")
        board = f"{stem}.kicad_pcb"
        src = RB.PCB(board)
        ics = sorted(src.footprints, key=lambda f: -len(f["pads"]))
        anchor = ics[0]
        near = [f for f in src.footprints if f["side"] == anchor["side"] and any(
            min(abs(p["x"] - q["x"]) + abs(p["y"] - q["y"]) for q in anchor["pads"]) < 6 for p in f["pads"])]
        refs = sorted({f["ref"] for f in near} | {anchor["ref"]})
        by = src.by_ref()
        pts = [(p["x"], p["y"]) for r in refs for p in by[r]["pads"]]
        b = [min(x for x, _ in pts) - 1, min(y for _, y in pts) - 1, max(x for x, _ in pts) + 1, max(y for _, y in pts) + 1]
        bx = shp_box(*b)
        edits = []
        for it in src.items:
            inside = (it["kind"] == "zone" and any(len(p) >= 3 and Polygon(p).buffer(0).intersects(bx) for p in it["polys"])) \
                or (it["kind"] != "zone" and it["pts"] and RB.inside_box(it["pts"], b))
            if inside:
                edits.append((it["s"], it["e"], ""))
        for r in refs:
            f = by[r]
            if f["locked"]:
                continue
            edits.append((f["s"], f["e"], RB.footprint_moved(src, f, f["x"] + 40, f["y"] + 3, f["rot"] + 90)))
        target = self.out / "B6" / "target.kicad_pcb"
        target.write_text(RB.splice(src.text, edits), encoding="utf-8")
        for ext in (".kicad_pro", ".kicad_dru"):
            if pathlib.Path(stem.as_posix() + ext).exists():
                shutil.copy(stem.as_posix() + ext, self.out / "B6" / ("target" + ext))
        mp = self.out / "B6" / "map.json"
        mp.write_text(json.dumps(dict(name="validation block", source="validation: the board's own copper", box=b,
                                      parts={r: r for r in refs})), encoding="utf-8")
        blk = self.out / "B6" / "block.json"
        c1, t1 = py([script("reference-block", "refblock.py"), "extract", board, mp, "-o", blk, "--board", target])
        c = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        c2, t2 = py([script("reference-block", "refblock.py"), "place", blk, target, "--at", c[0], c[1]])
        ok, detail = loads(self.cli, target, self.out)
        back = RB.PCB(target).by_ref() if c2 == 0 else {}
        same = sum(1 for r in refs if r in back and src.text[by[r]["s"]:by[r]["e"]] ==
                   RB.PCB(target).text[back[r]["s"]:back[r]["e"]])
        ev = (f"block of {len(refs)} parts around {anchor['ref']}; extract exit {c1}, place exit {c2}; "
              f"{same}/{len(refs)} footprints byte-identical after the round trip; result: {detail}")
        good = c1 == 0 and c2 == 0 and ok and same == len(refs)
        if self.a.pcbdoc:
            imp = self.out / "B6" / "imported.kicad_pcb"
            c3, t3 = py([script("reference-block", "refblock.py"), "import", self.repo / self.a.pcbdoc, "-o", imp,
                         "--kicad-cli", self.cli])
            ok3, d3 = loads(self.cli, imp, self.out) if imp.exists() else (False, tail(t3, 200))
            ev += f"; import of {self.a.pcbdoc}: exit {c3}, {d3}"
            good = good and c3 == 0 and ok3
        else:
            ev += "; import not run (no --pcbdoc)"
        return row("B6", "reference block", "PASS" if good else "FAIL",
                   ev + ("" if good else f"; {tail(t1 + t2, 300)}"), [str(target)])

    def B7(self):
        import design as D
        root, stem = self.copy("B7")
        out = self.out / "B7.review"
        args = [script("design-review", "review.py"), f"{stem}.kicad_pro", "--out", out, "--kicad-cli", self.cli,
                "--skip", "stock"]
        for v in self.a.voltage:
            args += ["--voltage", v]
        code, text = py(args)
        net = out / "netlist.net"
        if not net.exists():
            return row("B7", "review netlist", "FAIL", f"no netlist exported: {tail(text, 300)}")
        try:
            n = D.from_netlist(net)
        except Exception as e:                                # the parser is what this step validates
            return row("B7", "review netlist", "FAIL", f"netlist did not parse: {type(e).__name__}: {e}")
        b = D.from_board(f"{stem}.kicad_pcb", f"{stem}.kicad_sch")

        def partition(d):
            groups = {}
            for ref, part in d.parts.items():
                for num, p in part["pins"].items():
                    if p["net"]:
                        groups.setdefault(p["net"], set()).add((ref, num))
            return {frozenset(g) for g in groups.values() if len(g) > 1}
        pn, pb = partition(n), partition(b)
        only_n, only_b = pn - pb, pb - pn
        good = not only_n and not only_b
        return row("B7", "review netlist", "PASS" if good else "FAIL",
                   f"review exit {code}; netlist: {len(n.parts)} parts, {len(pn)} multi-pin nets; board: {len(pb)}; "
                   + ("same connectivity" if good else f"{len(only_n)} net(s) only in the netlist, {len(only_b)} only on "
                      f"the board, e.g. {sorted(next(iter(only_n or only_b)))[:6]}"), [str(out / "findings.json")])

    def B8(self):
        root, stem = self.copy("B8")
        env = dict(HW_PROJECT_ROOT=str(root), HW_BOARD=self.board)
        c1, t1 = py([script("hardware-project", "export_review.py"), "--kicad-cli", self.cli, "--no-review"], env=env)
        rv = root / "review_exports" / self.board
        want = ["schematic.pdf", "erc.json", "drc.json", "bom.csv"]
        miss = [w for w in want if not (rv / w).exists()] + ([] if list(rv.glob("gerbers/*")) else ["gerbers/"])
        c2, t2 = py([script("hardware-project", "export_jlcpcb.py"), "--kicad-cli", self.cli], env=env)
        mf = root / "manufacturing" / self.board
        made = sorted(p.name for p in mf.rglob("*") if p.is_file()) if mf.exists() else []
        good = c1 == 0 and not miss and c2 == 0 and made
        return row("B8", "exports", "PASS" if good else "FAIL",
                   f"export_review exit {c1}, missing: {', '.join(miss) or 'none'}; export_jlcpcb exit {c2}, "
                   f"{len(made)} file(s): {', '.join(made[:8])}" + ("" if good else f"; {tail(t1 + t2, 300)}"),
                   [str(rv), str(mf)])

    def B9(self):
        notes, good = [], True
        bom = next((p for p in (self.repo / "bom" / "bom.csv", self.repo / "bom" / "parts.csv") if p.exists()), None)
        if bom:
            js = self.out / "B9.stock.json"
            code, text = py([script("hardware-project", "jlc_stock.py"), bom, "--boards", "1", "--json", js], timeout=900)
            if js.exists():
                data = json.loads(js.read_text(encoding="utf-8"))
                checked = sum(1 for r in data["lines"] if r.get("package_check") != "unverified")
                mism = [r["lcsc"] for r in data["lines"] if "PACKAGE MISMATCH" in r["status"]]
                notes.append(f"jlc_stock: {len(data['lines'])} lines, {checked} package-checked, mismatches: "
                             f"{', '.join(mism) or 'none'} (each a real error or a parser gap: look)")
            else:
                good = False
                notes.append(f"jlc_stock failed: {tail(text, 200)}")
            lcsc = next((r.get("lcsc") for r in __import__("csv").DictReader(open(bom, encoding="utf-8")) if r.get("lcsc")), None)
            if lcsc:
                code, text = py([script("hardware-project", "fetch_datasheet.py"), lcsc], env=dict(HW_PROJECT_ROOT=str(self.out / "B9")))
                got = list((self.out / "B9").rglob("*.pdf"))
                notes.append(f"fetch_datasheet {lcsc}: exit {code}, {len(got)} PDF(s)")
                good = good and code == 0 and bool(got)
        else:
            notes.append("no bom/bom.csv or bom/parts.csv: stock and datasheet not checked")
        notes.append("easyeda2kicad " + ("installed" if shutil.which("easyeda2kicad") else "NOT installed (pip install easyeda2kicad)"))
        return row("B9", "network", "PASS" if good and bom else ("FAIL" if bom else "SKIP"), "; ".join(notes))


def report(kit, rows):
    lines = [f"# KiCad 10 validation: {kit.board}", "",
             f"{datetime.datetime.now().isoformat(timespec='seconds')}, repo {kit.repo}, copies under {kit.out}. "
             "Nothing in the repo was changed.", "",
             "| Step | What | Result | Evidence |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['step']} | {r['name']} | **{r['status']}** | {r['evidence'].replace('|', '/')} |")
    ran = {r["step"] for r in rows}
    lines += ["", "## In the KiCad window (MANUAL)", ""]
    lines += [f"- [ ] {s}: {text}" for s, text in MANUAL if s in ran]
    lines += ["", "Gate B (docs/design.md §9): every row PASS, or an issue filed with the fix; the manual checks done; "
              "the KiCad version above recorded in the PR."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo")
    ap.add_argument("--board")
    ap.add_argument("--kicad-cli")
    ap.add_argument("--out", default="validate-kicad")
    ap.add_argument("--steps", default=",".join(ALL))
    ap.add_argument("--mcu")
    ap.add_argument("--needs")
    ap.add_argument("--pcbdoc")
    ap.add_argument("--voltage", action="append", default=[])
    a = ap.parse_args(argv)
    kit = Kit(a)
    rows = []
    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    if not kit.cli and steps != ["B0"]:
        rows.append(kit.B0())
        print(report(kit, rows))
        return 1
    for s in steps:
        try:
            r = getattr(kit, s)()
        except Exception as e:                       # one broken step must not hide the others
            r = row(s, s, "FAIL", f"{type(e).__name__}: {e}")
        rows.append(r)
        print(f"{r['step']} {r['name']:16} {r['status']:5} {r['evidence'][:150]}")
    (kit.out / "validation.json").write_text(json.dumps(dict(board=kit.board, rows=rows), indent=2), encoding="utf-8")
    (kit.out / "validation.md").write_text(report(kit, rows), encoding="utf-8")
    print(f"\n-> {kit.out / 'validation.md'}")
    return 0 if all(r["status"] in ("PASS", "SKIP") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
