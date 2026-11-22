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
        self.assertTrue((d / "hardware" / "motor-ctl").is_dir())
        for f in d.rglob("*"):
            if f.is_file():
                self.assertNotIn("{{", f.read_text(), f)
        self.assertEqual(json.loads((d / ".claude" / "settings.json").read_text())["enabledPlugins"],
                         {"hardware-design@hardware-skills": True})
        self.assertIn("name: motor-ctl-board-reviewer", (d / ".claude/agents/motor-ctl-board-reviewer.md").read_text())
        self.assertEqual((d / "CLAUDE.md").read_text(), "@AGENTS.md\n")
        self.assertEqual(trace.check(d)["errors"], [])

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


if __name__ == "__main__":
    unittest.main()
