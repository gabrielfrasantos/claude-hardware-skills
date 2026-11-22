#!/usr/bin/env python3
"""Self-test for the hardware-project scripts. Run: python3 test_project.py (no KiCad or network needed)."""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jlc_stock  # noqa: E402
import project  # noqa: E402
import scaffold  # noqa: E402
import trace  # noqa: E402

ARGS = ["--name", "motor-ctl", "--title", "motor-ctl: test", "--firmware", "acme/motor-fw", "--owner", "acme"]


def quiet(fn, *a):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fn(*a)
    return code, out.getvalue()


class Project(unittest.TestCase):
    def test_root_and_board(self):
        d = pathlib.Path(tempfile.mkdtemp()).resolve()
        (d / "hardware" / "b1").mkdir(parents=True)
        (d / "hardware" / "b1" / "b1.kicad_pro").write_text("{}")
        (d / "hardware" / "lib").mkdir()
        (d / "hardware" / "lib" / "other.kicad_pro").write_text("{}")      # name does not match its folder
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        cwd = os.getcwd()
        try:
            os.chdir(d / "hardware")
            self.assertEqual(project.root(), d)
            self.assertEqual(project.boards(), ["b1"])
            self.assertEqual(project.default_board(), "b1")
            nested = d / "examples" / "e1"
            (nested / "hardware" / "e1").mkdir(parents=True)
            (nested / "hardware" / "e1" / "e1.kicad_pro").write_text("{}")
            (nested / "docs").mkdir()
            os.chdir(nested / "docs")
            self.assertEqual(project.root(), nested)
            os.chdir(d / "hardware")
            os.environ["HW_BOARD"] = "b2"
            self.assertEqual(project.default_board(), "b2")
        finally:
            os.environ.pop("HW_BOARD", None)
            os.chdir(cwd)


class Trace(unittest.TestCase):
    def repo(self, reqs, decs):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "docs").mkdir()
        (d / "docs" / "requirements.md").write_text("| ID | R | Source | Verify |\n|---|---|---|---|\n" + reqs)
        (d / "docs" / "decisions.md").write_text("| ID | D | Rejected | Why |\n|---|---|---|---|\n" + decs)
        return d

    def test_clean(self):
        d = self.repo("| HW-PWR-001 | 12 V | D-001 | R, S1 |\n| HW-RF-001 | link | REQ-BLE-001 | B (VNA, RSSI) |\n",
                      "| D-001 | 3S | 2S | why |\n")
        r = trace.check(d)
        self.assertEqual((r["requirements"], r["decisions"], r["errors"]), (2, 1, []))

    def test_errors_and_warnings(self):
        d = self.repo("| HW-PWR-001 | a | D-002 | R |\n| HW-PWR-001 | b | D-009 | X |\n| HW-IF-001 | c |  | R |\n",
                      "| D-001 | x | y | z. **Superseded by D-002 (2026-11-13).** |\n| D-002 | x | y | z |\n| D-002 | dup | | |\n")
        r = trace.check(d)
        text = "\n".join(r["errors"])
        for want in ("HW-PWR-001 also on line", "cites D-009", "verification 'X'", "HW-IF-001 has no source",
                     "D-002 also on line"):
            self.assertIn(want, text)
        d = self.repo("| HW-PWR-001 | a | D-001 | R |\n", "| D-001 | x | y | Superseded by D-002 |\n| D-002 | x | y | z |\n")
        self.assertTrue(any("superseded by D-002" in w for w in trace.check(d)["warnings"]))

    def test_missing_inputs_fail(self):
        missing = pathlib.Path(tempfile.mkdtemp()) / "not-a-repo"
        code, out = quiet(trace.main, ["--root", str(missing)])
        self.assertEqual(code, 1)
        self.assertIn(str(missing), out)                                  # the resolved path is printed
        self.assertIn("not found", out)
        self.assertNotIn("PASS", out)
        d = self.repo("| HW-PWR-001 | a | D-001 | R |\n", "| D-001 | x | y | z |\n")
        (d / "docs" / "requirements.md").unlink()
        code, out = quiet(trace.main, ["--root", str(d)])
        self.assertEqual(code, 1)
        self.assertIn(f"requirements.md: missing ({d / 'docs' / 'requirements.md'})", out)

    def test_unrecognized_and_empty_tables(self):
        d = self.repo("| REQ-1 | a | D-001 | R |\n| HW-PWR-1a | b | D-001 | R |\n", "| D-001 | x | y | z |\n")
        r = trace.check(d)
        self.assertEqual(r["requirements"], 0)
        self.assertTrue(any("no recognized requirement" in e and "REQ-1" in e for e in r["errors"]), r["errors"])
        empty = self.repo("", "")
        self.assertTrue(any("no requirements" in e for e in trace.check(empty)["errors"]))
        r = trace.check(empty, allow_empty=True)                          # a fresh scaffold, on purpose
        self.assertEqual(r["errors"], [])
        self.assertTrue(any("no requirements" in w for w in r["warnings"]))
        mixed = self.repo("| HW-PWR-001 | a | D-001 | R |\n| HW-PWR-02b | b | D-001 | R |\n", "| D-001 | x | y | z |\n")
        r = trace.check(mixed)
        self.assertEqual(r["errors"], [])
        self.assertTrue(any("'HW-PWR-02b'" in w for w in r["warnings"]), r["warnings"])

    def test_firmware_ids(self):
        d = self.repo("| HW-DRV-001 | a | REQ-DRIVE-002, REQ-DRIVE-099 | R |\n", "")
        fw = pathlib.Path(tempfile.mkdtemp())
        (fw / "req.yaml").write_text("- id: REQ-DRIVE-002\n")
        errors = trace.check(d, fw)["errors"]
        self.assertEqual(len(errors), 1)
        self.assertIn("REQ-DRIVE-099", errors[0])


class Stock(unittest.TestCase):
    PARTS = {
        "C1": dict(componentCode="C1", stockCount=10000, componentLibraryType="base", componentModelEn="CL10B104KB8NNNC",
                   componentPrices=[{"productPrice": 0.002}], componentSpecificationEn="0603"),
        "C2": dict(componentCode="C2", stockCount=50, componentLibraryType="expand", componentModelEn="TPS54302DDCR",
                   componentPrices=[{"productPrice": 0.4}], componentSpecificationEn="SOT-23-6"),
        "C3": dict(componentCode="C3", stockCount=900, componentLibraryType="expand", componentModelEn="TPS54302DDCR",
                   componentPrices=[{"productPrice": 0.4}], componentSpecificationEn="SOT-23-6"),
    }

    def check(self, *rows):
        return jlc_stock.check_rows(list(rows), boards=5, attrition=0.1, find=self.PARTS.get)

    def test_shrink_packages_compare_by_body(self):
        # TI DCT: KiCad SSOP-8 2.95x2.8, LCSC "MSOP-8-2.8mm" (C18213, SN74LVC3G17DCTR)
        pc = jlc_stock.package_check
        self.assertEqual(pc("Package_SO:SSOP-8_2.95x2.8mm_P0.65mm", "MSOP-8-2.8mm")[0], "ok")
        self.assertEqual(pc("Package_SO:SSOP-8_5.3x6.2mm_P0.65mm", "MSOP-8-2.8mm")[0], "mismatch")
        self.assertEqual(pc("Package_SO:TSSOP-8_4.4x3mm_P0.65mm", "MSOP-8")[0], "unverified")
        self.assertEqual(pc("Package_SO:SSOP-8_2.95x2.8mm_P0.65mm", "SOIC-8")[0], "mismatch")

    def test_vendor_names_for_sot23(self):
        pc = jlc_stock.package_check
        self.assertEqual(pc("Package_TO_SOT_SMD:SOT-23-5", "SOT-25-5")[0], "ok")
        self.assertEqual(pc("Package_TO_SOT_SMD:SOT-23-6", "SOT-26")[0], "ok")
        self.assertEqual(pc("Package_TO_SOT_SMD:SOT-23-6", "SOT-25-5")[0], "mismatch")

    def test_package_lifecycle_and_alternates(self):
        ok = dict(lcsc="C1", mpn="CL10B104KB8NNNC", qty="4", footprint="C_0603_1608Metric")
        report, problems, notes = self.check(ok)
        self.assertEqual((problems, report[0]["status"], report[0]["package_check"]), (0, "ok", "ok"))
        wrong = dict(ok, footprint="C_0402_1005Metric")
        self.assertIn("PACKAGE MISMATCH (chip 0402 vs 0603)", self.check(wrong)[0][0]["status"])
        eol = dict(ok, lifecycle="NRND")
        self.assertIn("LIFECYCLE NRND", self.check(eol)[0][0]["status"])
        single = dict(lcsc="C2", mpn="TPS54302DDCR", qty="1", footprint="SOT-23-6")
        report, problems, notes = self.check(single)
        self.assertEqual(problems, 0)
        self.assertTrue(any("no alternate" in n for n in notes))
        report, _, notes = self.check(dict(single, alt_lcsc="C3; C404"))
        self.assertEqual(report[0]["alternates"], {"C3": 900, "C404": None})
        self.assertFalse(any("no alternate" in n for n in notes))


class Scaffold(unittest.TestCase):
    def test_new_repo(self):
        d = pathlib.Path(tempfile.mkdtemp()) / "repo"
        code, out = quiet(scaffold.main, [str(d)] + ARGS)
        self.assertEqual(code, 0)
        for f in ("AGENTS.md", "CLAUDE.md", ".gitignore", ".claude/settings.json", ".claude/agents/motor-ctl-board-reviewer.md",
                  "docs/requirements.md", "docs/plan.md", "pin-data/pin-needs.txt", "scripts/schgen/config.py"):
            self.assertTrue((d / f).exists(), f)
        self.assertEqual(json.loads((d / "hardware/motor-ctl/motor-ctl.kicad_pro").read_text())["meta"]["filename"],
                         "motor-ctl.kicad_pro")
        for f in d.rglob("*"):
            if f.is_file():
                self.assertNotIn("{{", f.read_text(), f)
        self.assertEqual(json.loads((d / ".claude" / "settings.json").read_text())["enabledPlugins"],
                         {"hardware-design@hardware-skills": True})
        self.assertIn("name: motor-ctl-board-reviewer", (d / ".claude/agents/motor-ctl-board-reviewer.md").read_text())
        self.assertEqual((d / "CLAUDE.md").read_text(), "@AGENTS.md\n")
        self.assertEqual(trace.check(d)["errors"], [])

    def test_without_firmware(self):
        d = pathlib.Path(tempfile.mkdtemp()) / "repo"
        args = [a for a in ARGS if a not in ("--firmware", "acme/motor-fw")]
        self.assertEqual(quiet(scaffold.main, [str(d)] + args)[0], 0)
        self.assertIn("Firmware: none", (d / "PROJECT_CONTEXT.md").read_text())

    def test_never_overwrites(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "CLAUDE.md").write_text("mine")
        code, out = quiet(scaffold.main, [str(d)] + ARGS)
        self.assertEqual((d / "CLAUDE.md").read_text(), "mine")
        self.assertIn("= kept CLAUDE.md", out)

    def test_refuses_bad_input(self):
        with self.assertRaises(SystemExit):
            quiet(scaffold.main, ["/tmp/x", "--name", "Bad_Name", "--title", "t", "--firmware", "f"])
        with self.assertRaises(SystemExit):
            quiet(scaffold.main, ["/tmp/x", "--name", "ok", "--title", "t", "--firmware", "f", "--fab", "nofab"])


class Scripts(unittest.TestCase):
    def test_help_runs_without_kicad(self):
        names = ["export_review", "export_jlcpcb", "export_release", "export_bom", "jlc_stock", "fetch_datasheet"]
        if importlib.util.find_spec("pymupdf"):
            names.append("visual_diff")
        for name in names:
            r = subprocess.run([sys.executable, str(HERE / f"{name}.py"), "--help"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{name}: {r.stderr[-300:]}")

    def test_bom_export_uses_the_given_kicad_cli(self):
        # kicad-cli is often not on PATH on Windows: the BOM step must get the path the export was given
        import export_bom
        import export_jlcpcb
        import export_release
        seen, real = [], export_bom.main
        export_bom.main = lambda: seen.append(list(sys.argv))
        try:
            for mod in (export_jlcpcb, export_release):
                with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
                    self.assertTrue(mod.run_export_bom(pathlib.Path("b.kicad_sch"), pathlib.Path(td), r"C:\KiCad\kicad-cli.exe"))
        finally:
            export_bom.main = real
        self.assertEqual([a[-2:] for a in seen], [["--kicad-cli", r"C:\KiCad\kicad-cli.exe"]] * 2)
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(export_jlcpcb.run_export_bom(pathlib.Path(td) / "b.kicad_sch", pathlib.Path(td),
                                                          str(pathlib.Path(td) / "no-such-kicad-cli")))
        self.assertIn("[FAIL]", out.getvalue())


def fake_cli(td, body):
    """An executable standing in for kicad-cli: `body` is Python run with argv; `out` is the -o path."""
    path = pathlib.Path(td) / "fake-kicad-cli"
    path.write_text(f"#!{sys.executable}\nimport sys\nargv = sys.argv[1:]\n"
                    "out = argv[argv.index('-o') + 1] if '-o' in argv else None\n" + body)
    path.chmod(0o755)
    return str(path)


def fp(ref, attrs="smd", fields=None, pads=True):
    props = "".join(f'\t\t(property "{k}" "{v}")\n' for k, v in (fields or {}).items())
    return (f'\t(footprint "lib:R_0402"\n\t\t(layer "F.Cu")\n\t\t(at 0 0)\n\t\t(property "Reference" "{ref}")\n{props}'
            + (f"\t\t(attr {attrs})\n" if attrs else "")
            + ('\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))\n' if pads else "") + "\t)\n")


ASSEMBLY_BOARD = ('(kicad_pcb\n\t(version 20260206)\n'
                  + fp("R1") + fp("R2") + fp("R3", "smd exclude_from_pos_files exclude_from_bom dnp")
                  + fp("J1", "through_hole", {"Assembly": "hand"})
                  + fp("G1", "board_only exclude_from_pos_files exclude_from_bom", pads=False) + ")\n")
BOM_HEAD = "Comment,Designator,Footprint,LCSC Part #\n"
CPL_HEAD = "Designator,Val,Package,Mid X,Mid Y,Rotation,Layer\n"


@unittest.skipIf(os.name == "nt", "fake kicad-cli is a script with a shebang")
class Assembly(unittest.TestCase):
    def setUp(self):
        import assembly
        self.A = assembly
        self.td = pathlib.Path(tempfile.mkdtemp())
        self.pcb = self.td / "b.kicad_pcb"
        self.pcb.write_text(ASSEMBLY_BOARD)

    def package(self, bom_rows, cpl_rows):
        (self.td / "bom.csv").write_text(BOM_HEAD + "".join(r + "\n" for r in bom_rows))
        (self.td / "cpl.csv").write_text(CPL_HEAD + "".join(r + "\n" for r in cpl_rows))
        return self.A.check_package(self.pcb, self.td / "bom.csv", self.td / "cpl.csv")

    def test_blank_lcsc_is_reported_not_silently_dropped(self):
        cli = fake_cli(self.td, "open(out, 'w').write('Reference,Value,Footprint,LCSC,MPN,Qty\\n"
                                "R1,10k,R_0402,C25744,,1\\nR2,1k,R_0402,,,1\\n')\n")
        import export_release
        with contextlib.redirect_stdout(io.StringIO()) as log:
            self.assertTrue(export_release.run_export_bom(self.td / "b.kicad_sch", self.td, cli))
        self.assertIn("no LCSC number", log.getvalue())
        self.assertIn("R2", log.getvalue())
        self.assertNotIn("R2", (self.td / "bom" / "bom_jlc.csv").read_text())

    def test_every_fitted_part_is_in_the_bom_and_the_cpl(self):
        ok = self.package(["10k,R1,R_0402,C25744", "1k,R2,R_0402,C11702"],
                          ["R1,10k,R_0402,1,2,0,Top", "R2,1k,R_0402,3,4,90,Bottom", "J1,conn,J,5,6,0,Top"])
        self.assertEqual(ok["errors"], [])
        self.assertIn("J1", " ".join(ok["notes"]))                       # hand-fitted: named, not an error
        bad = self.package(["10k,R1,R_0402,C25744"], ["R1,10k,R_0402,1,2,0,Top"])
        self.assertEqual(len(bad["errors"]), 2, bad["errors"])
        self.assertTrue(all("R2" in e for e in bad["errors"]))
        self.assertFalse(any(r in " ".join(bad["errors"]) for r in ("R3", "J1", "G1")))   # DNP, hand, board-only

    def test_bom_line_for_a_part_not_fitted_on_the_board(self):
        res = self.package(["10k,\"R1,R3\",R_0402,C25744", "1k,R2,R_0402,C11702"],
                           ["R1,10k,R_0402,1,2,0,Top", "R2,1k,R_0402,3,4,90,Top"])
        self.assertEqual(len(res["errors"]), 1, res["errors"])
        self.assertIn("R3", res["errors"][0])

    def test_unreadable_files_are_errors(self):
        (self.td / "bom.csv").write_text("Value,Ref\n10k,R1\n")
        res = self.A.check_package(self.pcb, self.td / "bom.csv", self.td / "missing.csv")
        self.assertTrue(any("bom.csv" in e and "LCSC Part #" in e for e in res["errors"]), res["errors"])
        self.assertTrue(any("missing.csv" in e for e in res["errors"]), res["errors"])
        res = self.package(["10k,R1,R_0402,C25744", "1k,R2,R_0402,C11702"],
                           ["R1,10k,R_0402,1,2,0,Top", "R2,1k,R_0402,x,4,90,Side"])
        self.assertTrue(any("R2" in e and "Mid X" in e for e in res["errors"]), res["errors"])
        self.assertTrue(any("R2" in e and "Layer" in e for e in res["errors"]), res["errors"])

    def test_release_fails_when_the_placement_file_is_missing(self):
        import export_release as E
        saved = E.STAGE_DIR, E.PCB_FILE
        E.STAGE_DIR, E.PCB_FILE = self.td, self.pcb
        E.FAILED.clear()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                E.export_cpl(fake_cli(self.td, "pass\n"))                # exit 0, no file
            self.assertEqual(len(E.FAILED), 1)
            self.assertIn("Placement", E.FAILED[0])
            E.FAILED.clear()
            self.package(["10k,R1,R_0402,C25744"], ["R1,10k,R_0402,1,2,0,Top"])
            with contextlib.redirect_stdout(io.StringIO()):
                E.check_assembly()
            self.assertEqual(len(E.FAILED), 2)                          # R2: not in the BOM, not in the CPL
            self.assertTrue(all("R2" in f for f in E.FAILED))
        finally:
            E.STAGE_DIR, E.PCB_FILE = saved
            E.FAILED.clear()


if __name__ == "__main__":
    unittest.main()
