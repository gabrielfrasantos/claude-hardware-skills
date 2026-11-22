#!/usr/bin/env python3
"""Self-test for schgen.py, the schgen library and library_check.py. Run: python3 test_schgen.py (no KiCad needed)."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import textwrap
import unittest
import uuid

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "schgen"))
import library_check as LC  # noqa: E402
import netlist  # noqa: E402
import schgen  # noqa: E402
import sch  # noqa: E402

FONT = '(effects (font (size 1.27 1.27)))'


def pin(kind, x, y, ang, name, num):
    return f'(pin {kind} line (at {x} {y} {ang}) (length 2.54) (name "{name}" {FONT}) (number "{num}" {FONT}))'


def symbol(name, ref, body, pins, power=False):
    return (f'(symbol "{name}" {"(power)" if power else ""} (pin_names (offset 0)) (in_bom yes) (on_board yes)\n'
            f'  (property "Reference" "{ref}" (at 0 6 0) {FONT})\n  (property "Value" "{name}" (at 0 -6 0) {FONT})\n'
            f'  (property "Footprint" "" (at 0 0 0) {FONT})\n  (property "Datasheet" "" (at 0 0 0) {FONT})\n'
            f'  (symbol "{name}_0_1" (rectangle (start {body[0]} {body[1]}) (end {body[2]} {body[3]}) '
            f'(stroke (width 0.254) (type default)) (fill (type none))))\n'
            f'  (symbol "{name}_1_1" {" ".join(pins)}))\n')


DEVICE = ("(kicad_symbol_lib (version 20251024) (generator \"test\")\n"
          + symbol("R", "R", (-1.016, -2.54, 1.016, 2.54), [pin("passive", 0, 5.08, 270, "~", 1),
                                                           pin("passive", 0, -5.08, 90, "~", 2)])
          + symbol("MCU", "U", (-7.62, -7.62, 7.62, 7.62),
                   [pin("bidirectional", -10.16, 2.54, 0, "PA1", 1), pin("bidirectional", -10.16, 0, 0, "PA2", 2),
                    pin("bidirectional", 10.16, 2.54, 180, "PB1", 3), pin("bidirectional", 10.16, 0, 180, "PB2", 4),
                    pin("power_in", 0, 10.16, 270, "VDD", 5), pin("power_in", 0, -10.16, 90, "VSS", 6)]) + ")\n")
POWER = ("(kicad_symbol_lib (version 20251024) (generator \"test\")\n"
         + symbol("GND", "#PWR", (-1.27, -1.27, 1.27, 0), [pin("power_in", 0, 0, 270, "GND", 1)], power=True)
         + symbol("+3V3", "#PWR", (-1.27, 0, 1.27, 1.27), [pin("power_in", 0, 0, 90, "+3V3", 1)], power=True) + ")\n")

DESIGN = textwrap.dedent('''
    from sch import Sheet, load_pinmap
    import os

    def build(project, values):
        sh = Sheet(project, 1, "main", "Main")
        sh.desc = ["test sheet"]
        sh.box(15.24, 20.32, 200.66, 120.0, "MCU and a pull-up")
        u = sh.part("Device:MCU", "U1", "MCU", (101.6, 60.96), fp="Package:QFN6", lcsc="C1", mpn="MCU-1")
        sh.nets(u, {"5": "+3V3", "6": "GND"})
        pm = os.path.join(os.path.dirname(__file__), "..", "pinmap.txt")
        sh.assign_pins(u, load_pinmap(pm) if os.path.exists(pm) else {})
        r = sh.part("Device:R", "R1", values["R1"], (50.8, 60.96), fp="Resistor_SMD:R_0402", lcsc="C2", mpn="R-1")
        sh.nets(r, {"1": "+3V3", "2": "LED"})
        sh.nc_unused(u, r"^P[A-Z][0-9]+$")
        if values.get("netclass"):
            sh.netclass("+3V3", "PWR_1A")
        if values.get("table"):
            sh.netclass("LED", "SIGNAL")
            sh.class_table(215.9, 20.32)
        if values.get("hide"):
            u.hide_value = True
        if values.get("boxcut"):
            sh.box(45.72, 50.8, 50.8, 71.12)
        if values.get("crowd"):
            r2 = sh.part("Device:R", "R2", "10k", (53.34, 60.96), fp="Resistor_SMD:R_0402", lcsc="C2", mpn="R-1")
            sh.nets(r2, {"1": "+3V3", "2": "LED"})
''')


class Project:
    def __init__(self, pinmap=None):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.mod = 'main_' + uuid.uuid4().hex[:12]
        (self.dir / "syms").mkdir()
        (self.dir / "syms" / "Device.kicad_sym").write_text(DEVICE)
        (self.dir / "syms" / "power.kicad_sym").write_text(POWER)
        cfg = self.dir / "schgen"
        (cfg / "design").mkdir(parents=True)
        (cfg / "design" / f"{self.mod}.py").write_text(DESIGN)
        (cfg / "values.json").write_text(json.dumps({"R1": "10k"}))
        if pinmap:
            (cfg / "pinmap.txt").write_text(pinmap)
        (cfg / "config.py").write_text(textwrap.dedent(f'''
            NAME = "t"
            TITLE = "t: test board"
            OUT = "../hw"
            MODULES = ["{self.mod}"]
            VALUES = "values.json"
            DATE = "2026-11-20"
            POWER_SYMBOLS = {{"GND": "power:GND", "+3V3": "power:+3V3"}}
            SYMBOL_DIR = "{(self.dir / 'syms').as_posix()}"
            ROOT_NOTES = [("t rev A", 30.48, 30.48, 2.54, True)]
        '''))
        self.config = cfg / "config.py"

    def build(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            c = schgen.load_config(self.config)
            code, project = schgen.build(c, upgrade=False)
        return code, project, out.getvalue()


class Build(unittest.TestCase):
    def test_build_is_deterministic_and_records_intent(self):
        p = Project("# pin map\nLED  PA1  1  GPIO  W  10.0\n")
        code, project, out = p.build()
        self.assertEqual(code, 0, out)
        files = sorted((p.dir / "hw").glob("*.kicad_sch"))
        self.assertEqual([f.name for f in files], ["main.kicad_sch", "t.kicad_sch"])
        first = {f.name: f.read_bytes() for f in files}
        code, _, _ = p.build()
        self.assertEqual({f.name: f.read_bytes() for f in files}, first)               # byte-identical rebuild
        expected = json.loads((p.dir / "schgen" / "expected.json").read_text())
        self.assertEqual(sorted(map(tuple, expected["/1 Main/LED"])), [("R1", "2"), ("U1", "1")])
        self.assertEqual(sorted(map(tuple, expected["+3V3"])), [("R1", "1"), ("U1", "5")])
        text = (p.dir / "hw" / "main.kicad_sch").read_text()
        self.assertEqual(text.count("(no_connect"), 3)                                  # PA2, PB1, PB2

    def test_pin_tbd_leaves_the_function_on_one_side(self):
        p = Project()                                                                   # no pin map yet
        code, _, out = p.build()
        self.assertEqual(code, 0, out)
        expected = json.loads((p.dir / "schgen" / "expected.json").read_text())
        self.assertEqual(sorted(map(tuple, expected["/1 Main/LED"])), [("R1", "2")])
        self.assertEqual((p.dir / "hw" / "main.kicad_sch").read_text().count("(no_connect"), 4)

    def test_problems_refuse_an_open_pin(self):
        p = Project()
        design = next((p.dir / "schgen" / "design").glob("main_*.py"))
        text = design.read_text()
        self.assertIn("sh.nc_unused(", text)
        design.write_text("\n".join(line for line in text.splitlines() if "nc_unused" not in line) + "\n")
        code, _, out = p.build()
        self.assertEqual(code, 1)
        self.assertIn("U1.1 (PA1) has no net and no no-connect", out)

    def test_netclass_directive(self):
        p = Project()
        (p.dir / "schgen" / "values.json").write_text(json.dumps({"R1": "10k", "netclass": True}))
        code, project, out = p.build()
        text = (p.dir / "hw" / "main.kicad_sch").read_text()
        self.assertEqual(text.count("(netclass_flag"), 1)
        self.assertIn('(property "Net Class" "PWR_1A"', text)
        self.assertEqual(code, 1)
        self.assertIn("main: text 'PWR_1A' overlaps '+3V3'", project.lint)

    def test_class_table_keeps_flags_off_the_circuit(self):
        p = Project()
        (p.dir / "schgen" / "values.json").write_text(json.dumps({"R1": "10k", "netclass": True, "table": True}))
        code, _, out = p.build()
        self.assertEqual(code, 0, out)
        text = (p.dir / "hw" / "main.kicad_sch").read_text()
        self.assertEqual(text.count("(netclass_flag"), 2)
        self.assertIn("Net classes", text)
        flags = [line for line in text.split("(netclass_flag")[1:]]
        self.assertTrue(all("(at 2" in f.split("(uuid")[0] for f in flags))               # in the table, x > 200
        self.assertIn('(label "LED"', text)

    def test_overlapping_text_is_lint(self):
        p = Project()
        (p.dir / "schgen" / "values.json").write_text(json.dumps({"R1": "10k", "crowd": True}))
        code, project, out = p.build()
        self.assertEqual(code, 1, out)
        self.assertTrue(any("overlaps" in item for item in project.lint), project.lint)

    def test_hide_value_on_an_ic(self):
        p = Project()
        (p.dir / "schgen" / "values.json").write_text(json.dumps({"R1": "10k", "hide": True}))
        self.assertEqual(p.build()[0], 0)
        text = (p.dir / "hw" / "main.kicad_sch").read_text()
        value = text[text.rindex('(property "Value" "MCU"'):]
        self.assertIn("(hide yes)", value[:value.index("(property", 10)])

    def test_box_through_a_part_is_lint(self):
        p = Project()
        (p.dir / "schgen" / "values.json").write_text(json.dumps({"R1": "10k", "boxcut": True}))
        code, project, _ = p.build()
        self.assertEqual(code, 1)
        self.assertTrue(any("box outline" in item and "R1" in item for item in project.lint), project.lint)

    def test_root_notes_are_lint(self):
        p = Project()
        cfg = p.config.read_text().replace("ROOT_NOTES = [(\"t rev A\", 30.48, 30.48", "ROOT_NOTES = [(\"t rev A\", 40.64, 76.2")
        p.config.write_text(cfg)
        code, project, _ = p.build()
        self.assertEqual(code, 1)
        self.assertTrue(any(item.startswith("root: text 't rev A' overlaps sheet") or
                            ("root:" in item and "t rev A" in item) for item in project.lint), project.lint)

    def test_load_pinmap(self):
        d = pathlib.Path(tempfile.mkdtemp()) / "m.txt"
        d.write_text("# header\nIMU_SCK  PA1  16  SPI1_SCK  E  21.2\nNF~2  PC11  59  EXTI11  S  52.1\n")
        self.assertEqual(sch.load_pinmap(d), {"IMU_SCK": "16", "NF~2": "59"})


class Netlists(unittest.TestCase):
    def test_compare_expected(self):
        nets = {"A": frozenset({("R1", "1"), ("U1", "2")}), "B": frozenset({("R1", "2"), ("C1", "1")})}
        self.assertEqual(netlist.compare_expected({"A": {("R1", "1"), ("U1", "2")}}, nets), [])
        bad = netlist.compare_expected({"B": {("R1", "2")}, "A": {("R1", "1"), ("U1", "3")}}, nets)
        self.assertTrue(any("unexpected pins" in b for b in bad) and any("missing" in b for b in bad))

    def test_compare_two_netlists(self):
        part = {"value": "10k", "footprint": "R", "fields": {}, "flags": [], "symbol": "Device:R"}
        a = ({"R1": part}, {"A": frozenset({("R1", "1")}), "B": frozenset({("R1", "2")})})
        renamed = ({"R1": part}, {"A2": frozenset({("R1", "1")}), "B": frozenset({("R1", "2")})})
        self.assertEqual(netlist.compare(a, a)[0], [])
        self.assertEqual(netlist.compare(a, renamed, allow_renames=True)[0], [])
        self.assertTrue(netlist.compare(a, renamed)[0])


class Library(unittest.TestCase):
    def test_pins_against_pads_and_fields(self):
        p = Project("LED  PA1  1  GPIO  W  10.0\n")
        p.build()
        board = p.dir / "hw" / "t.kicad_pcb"

        def fp(ref, pads):
            body = "".join(f'(pad "{n}" smd rect (at {i} 0) (size 0.5 0.5) (layers "F.Cu") (net "N"))'
                           for i, n in enumerate(pads))
            return f'(footprint "X" (layer "F.Cu") (at 0 0) (property "Reference" "{ref}") {body})\n'
        board.write_text('(kicad_pcb (version 20260206) (layers (0 "F.Cu" signal))\n'
                         + fp("U1", ["1", "2", "3", "4", "5", "6"]) + fp("R1", ["1", "2"]) + ")\n")
        out, n = LC.check(board, p.dir / "hw" / "t.kicad_sch")
        self.assertEqual((n, sum(len(v) for v in out.values())), (2, 0), out)
        board.write_text(board.read_text().replace('(pad "6"', '(pad "7"'))          # wrong footprint for U1
        out, _ = LC.check(board, p.dir / "hw" / "t.kicad_sch")
        self.assertEqual(len(out["pins_without_pad"]), 1)
        self.assertEqual(len(out["pads_without_pin"]), 1)
        out, _ = LC.check(board, p.dir / "hw" / "t.kicad_sch", fields=("LCSC", "Voltage"))
        self.assertEqual(len(out["missing_fields"]), 2)                                 # no Voltage field


if __name__ == "__main__":
    unittest.main()
