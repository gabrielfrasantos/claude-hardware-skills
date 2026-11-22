#!/usr/bin/env python3
"""Self-test for design-review (design.py, checks.py, review.py). Run: python3 test_review.py (no KiCad needed)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checks as C  # noqa: E402
import design as D  # noqa: E402
import review  # noqa: E402

HEAD = ('(kicad_pcb\n\t(version 20260206)\n\t(generator "pcbnew")\n\t(layers\n\t\t(0 "F.Cu" signal)\n'
        '\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n\t)\n'
        '\t(gr_rect\n\t\t(start 0 0)\n\t\t(end 60 40)\n\t\t(layer "Edge.Cuts")\n\t)\n')


def fp(ref, lib, value, x, y, pads, fields=None):
    """pads: [(number, dx, dy, net, name, type)]"""
    props = "".join(f'\t\t(property "{k}" "{v}"\n\t\t)\n' for k, v in (fields or {}).items())
    ps = ""
    for num, dx, dy, net, name, ptype in pads:
        ps += (f'\t\t(pad "{num}" smd rect\n\t\t\t(at {dx} {dy})\n\t\t\t(size 0.6 0.6)\n\t\t\t(layers "F.Cu")\n'
               + (f'\t\t\t(net "{net}")\n' if net else "")
               + (f'\t\t\t(pinfunction "{name}")\n' if name else "") + (f'\t\t\t(pintype "{ptype}")\n' if ptype else "")
               + "\t\t)\n")
    return (f'\t(footprint "{lib}"\n\t\t(layer "F.Cu")\n\t\t(at {x} {y})\n\t\t(property "Reference" "{ref}"\n\t\t)\n'
            f'\t\t(property "Value" "{value}"\n\t\t)\n{props}{ps}\t)\n')


def two(ref, lib, value, x, y, a, b, names=("", ""), fields=None):
    return fp(ref, lib, value, x, y, [("1", -0.5, 0, a, names[0], "passive"), ("2", 0.5, 0, b, names[1], "passive")], fields)


def mcu(x=30, y=20, boot="", vcap="VCAP_NET", adc="ADC_IN", scl="I2C1_SCL"):
    return fp("U1", "Package_DFN_QFN:QFN-16", "STM32", x, y, [
        ("1", -2, -1, "+3V3", "VDD", "power_in"), ("2", -2, 1, "GND", "VSS", "power_in"),
        ("3", 2, -1, boot, "BOOT0", "input"), ("4", 2, 1, vcap, "VCAP1", "power_in"),
        ("5", 0, -2, adc, "PA0", "bidirectional"), ("6", 0, 2, scl, "PB8", "bidirectional")])


CLEAN = [mcu(), two("C1", "Capacitor_SMD:C_0402", "100nF 16V X7R", 27, 19, "+3V3", "GND"),
         two("C2", "Capacitor_SMD:C_0402", "2.2uF 10V", 32, 21, "VCAP_NET", "GND"),
         two("R1", "Resistor_SMD:R_0402", "10k", 33, 19, "BOOT_NET", "GND"),
         two("R2", "Resistor_SMD:R_0402", "100k", 30, 25, "+12V", "ADC_IN"),
         two("R3", "Resistor_SMD:R_0402", "10k", 30, 27, "ADC_IN", "GND"),
         two("R4", "Resistor_SMD:R_0402", "4k7", 30, 15, "+3V3", "I2C1_SCL"),
         two("C3", "Capacitor_SMD:C_1206", "10uF 50V X7R", 10, 10, "+12V", "GND"),
         two("D1", "Diode_SMD:D_SMA", "SMBJ15A", 12, 10, "+12V", "GND", names=("K", "A")),
         two("TP1", "TestPoint:TestPoint_Pad", "TP", 40, 30, "+3V3", "+3V3"),
         fp("J1", "Connector:Conn_01x02", "PWR", 5, 10, [("1", 0, 0, "+12V", "", "passive"), ("2", 0, 2, "GND", "", "passive")])]


def board(items, boot="BOOT_NET", **kw):
    items = [mcu(boot=boot, **kw)] + items[1:]
    d = tempfile.mkdtemp()
    path = os.path.join(d, "b.kicad_pcb")
    with open(path, "w") as f:
        f.write(HEAD + "".join(items) + ")\n")
    return path


def found(path, check, severity=None, **over):
    d = D.from_board(path)
    d.overrides = over
    return [x for x in C.run(d, {check}) if severity is None or x["severity"] == severity]


class Model(unittest.TestCase):
    def test_values_and_voltages(self):
        self.assertEqual(D.parse_value("4k7"), 4700)
        self.assertAlmostEqual(D.parse_value("100nF", "F"), 1e-7)
        self.assertAlmostEqual(D.parse_value("2u2"), 2.2e-6)
        self.assertEqual(D.parse_value("0R"), 0)
        for net, v in (("+3V3", 3.3), ("/power/5V", 5), ("12V_IN", 12), ("+1.8V", 1.8), ("VBUS", 5), ("GND", 0),
                       ("SPI1_MOSI", None), ("DRV_V5", None)):
            self.assertEqual(D.name_voltage(net), v, net)
        self.assertEqual(D.rated_voltage(dict(value="10uF", fields={"Voltage": "25V"})), 25)

    def test_board_model(self):
        d = D.from_board(board(CLEAN))
        self.assertEqual(d.parts["U1"]["pins"]["1"]["type"], "power_in")
        self.assertEqual(d.parts["U1"]["pins"]["3"]["net"], "BOOT_NET")
        self.assertTrue(d.has_types() and d.has_positions())

    def test_netlist_model(self):
        net = '''(export (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "QFN") (libsource (lib "MCU") (part "M") (description "")))
    (comp (ref "C1") (value "100n") (footprint "C_0402") (fields (field (name "Voltage") "16V"))
      (libsource (lib "Device") (part "C") (description ""))))
  (libparts
    (libpart (lib "MCU") (part "M") (pins (pin (num "1") (name "VDD") (type "power_in")) (pin (num "2") (name "BOOT0") (type "input"))))
    (libpart (lib "Device") (part "C") (pins (pin (num "1") (name "~") (type "passive")) (pin (num "2") (name "~") (type "passive")))))
  (nets
    (net (code "1") (name "+3V3") (class "Default") (node (ref "U1") (pin "1") (pinfunction "VDD") (pintype "power_in")))
    (net (code "2") (name "GND") (class "Default") (node (ref "C1") (pin "2") (pintype "passive")))
    (net (code "3") (name "unconnected-(U1-BOOT0-Pad2)") (class "Default") (node (ref "U1") (pin "2") (pinfunction "BOOT0") (pintype "input")))))
'''
        path = os.path.join(tempfile.mkdtemp(), "x.net")
        with open(path, "w") as f:
            f.write(net)
        d = D.from_netlist(path)
        self.assertEqual(d.parts["U1"]["pins"]["2"]["name"], "BOOT0")
        self.assertEqual(d.parts["U1"]["pins"]["2"]["net"], "")               # unconnected
        self.assertEqual(d.parts["C1"]["pins"]["1"]["net"], "")               # on no net at all
        self.assertEqual(D.rated_voltage(d.parts["C1"]), 16)
        checks = {x["check"]: x["severity"] for x in C.run(d)}
        self.assertEqual(checks.get("mcu_pins"), "MAJOR")                     # BOOT0 floats
        self.assertEqual(checks.get("decoupling"), "MAJOR")                   # C1 isn't on +3V3


class Checks(unittest.TestCase):
    def test_clean_design_has_no_major(self):
        d = D.from_board(board(CLEAN))
        bad = [x for x in C.run(d) if x["severity"] in ("BLOCKER", "MAJOR")]
        self.assertEqual(bad, [])

    def test_decoupling(self):
        self.assertEqual(found(board([CLEAN[0]] + CLEAN[2:]), "decoupling", "MAJOR")[0]["anchor"], "U1 / +3V3")
        far = [CLEAN[0], two("C1", "Capacitor_SMD:C_0402", "100nF 16V", 50, 35, "+3V3", "GND")] + CLEAN[2:]
        self.assertEqual(len(found(board(far), "decoupling", "MINOR")), 1)

    def test_switch_node_is_not_decoupled(self):
        items = CLEAN + [fp("U2", "Package_TO_SOT_SMD:SOT-23-6", "BUCK", 45, 10,
                            [("1", 0, 0, "BUCK_LX", "SW", "power_in"), ("2", 1, 0, "+12V", "VIN", "power_in"),
                             ("3", 2, 0, "GND", "GND", "power_in")])]
        self.assertEqual(found(board(items), "decoupling", "MAJOR"), [])          # BUCK_LX is a switch node; +12V has C3

    def test_pullups(self):
        no_pull = [x for x in CLEAN if '"R4"' not in x]
        self.assertEqual(found(board(no_pull), "pullups", "MAJOR")[0]["anchor"], "I2C1_SCL")

    def test_mcu_pins(self):
        self.assertEqual(found(board(CLEAN, boot=""), "mcu_pins", "MAJOR")[0]["anchor"], "U1.3")
        no_vcap = [x for x in CLEAN if '"C2"' not in x]
        self.assertEqual(found(board(no_vcap), "mcu_pins", "MAJOR")[0]["anchor"], "U1.4")

    def test_ratings(self):
        low = [x.replace("10uF 50V X7R", "10uF 10V X7R") for x in CLEAN]
        self.assertEqual(found(board(low), "ratings", "BLOCKER")[0]["anchor"], "C3")
        marginal = [x.replace("10uF 50V X7R", "10uF 16V X7R") for x in CLEAN]
        self.assertEqual(found(board(marginal), "ratings", "MINOR")[0]["anchor"], "C3")
        tvs = [x.replace("SMBJ15A", "SMBJ5.0A") for x in CLEAN]
        self.assertEqual(found(board(tvs), "ratings", "BLOCKER")[0]["anchor"], "D1")

    def test_orientation(self):
        rev = [x.replace('(pinfunction "K")', '(pinfunction "X")').replace('(pinfunction "A")', '(pinfunction "K")')
               .replace('(pinfunction "X")', '(pinfunction "A")') for x in CLEAN]
        self.assertEqual(found(board(rev), "orientation", "BLOCKER")[0]["anchor"], "D1")
        cp = CLEAN + [two("C9", "Capacitor_THT:CP_Radial_D8.0mm", "220uF 25V", 20, 30, "GND", "+12V")]
        self.assertEqual(found(board(cp), "orientation", "BLOCKER")[0]["anchor"], "C9")

    def test_divider_into_an_ic(self):
        bad = [x.replace('"100k"', '"10k"') for x in CLEAN]                     # 12 V -> 6 V into a 3.3 V MCU
        self.assertIn("6.00 V", found(board(bad), "dividers", "MAJOR")[0]["message"])

    def test_connector_esd_and_test_points(self):
        esd = found(board(CLEAN), "connector_esd")
        self.assertEqual(esd, [])                                                # the TVS protects +12V
        no_tvs = [x for x in CLEAN if '"D1"' not in x]
        self.assertEqual(found(board(no_tvs), "connector_esd")[0]["anchor"], "J1")
        # behind a fuse and a reverse-polarity FET the TVS on +12V still protects the battery pin
        fet = fp("Q1", "Package_SO:SOIC-8", "AO4805", 8, 14, [("1", 0, 0, "PP_S", "S_1", "passive"),
                                                              ("2", 0, 1, "PP_G", "G_2", "input"),
                                                              ("7", 2, 0, "BAT_F", "D_7", "passive"),
                                                              ("5", 2, 1, "+12V", "D_5", "passive")])
        fuse = two("F1", "Fuse:Fuse_1206", "4A", 4, 14, "BAT_P", "BAT_F")
        batt = fp("J2", "Connector:XT30", "battery", 2, 14, [("1", 0, 0, "BAT_P", "", "passive"),
                                                              ("2", 0, 2, "GND", "", "passive")])
        self.assertEqual(found(board(CLEAN + [fet, fuse, batt]), "connector_esd"), [])
        # a half-bridge output (one FET's source, the other's drain) is clamped by the body diodes
        bridge = fp("Q2", "Package_SO:SOIC-8", "CSD88537ND", 20, 30, [("1", 0, 0, "MOT_P", "S_1", "passive"),
                                                                        ("5", 0, 1, "MOT_P", "D_5", "passive"),
                                                                        ("3", 1, 0, "GND", "S_3", "passive"),
                                                                        ("7", 1, 1, "+12V", "D_7", "passive")])
        motor = fp("J3", "Connector:Conn_01x01", "motor", 25, 35, [("1", 0, 0, "MOT_P", "", "passive")])
        self.assertEqual(found(board(no_tvs + [bridge, motor]), "connector_esd")[0]["anchor"], "J1")   # J3 is clamped
        self.assertEqual(len(found(board(no_tvs + [bridge, motor]), "connector_esd")), 1)
        tp = found(board(CLEAN), "test_points")
        self.assertIn("+12V", tp[0]["message"])
        self.assertNotIn("+3V3", tp[0]["message"])


class Severities(unittest.TestCase):
    def test_gate_severities(self):
        data = {"failures": ["shorts = 1 (limit 0)", "teardrops_disabled = 9 (limit 0)", "zone_necks = 1 (limit 0)",
                             "jogs = 1 (limit 0)"], "warnings": []}
        sev = {x["check"]: x["severity"] for x in review._gate_findings(data, "t", "layout", "r", None)}
        self.assertEqual(sev, {"shorts": "BLOCKER", "teardrops_disabled": "MINOR", "zone_necks": "MAJOR", "jogs": "MINOR"})


class Review(unittest.TestCase):
    def test_end_to_end(self):
        path = board([x.replace("10uF 50V X7R", "10uF 10V X7R") for x in CLEAN])
        out = os.path.join(os.path.dirname(path), "rv")
        with contextlib.redirect_stdout(io.StringIO()):
            code = review.main([path, "--out", out, "--skip", "erc,stock", "--fail-on", "MAJOR"])
        self.assertEqual(code, 1)
        data = json.load(open(os.path.join(out, "findings.json")))
        self.assertEqual(data["findings"][0]["severity"], "BLOCKER")
        self.assertTrue(all(k in data["findings"][0] for k in ("id", "area", "check", "anchor", "message", "rule", "tool")))
        self.assertIn("library", {x["check"] for x in data["findings"] if x["severity"] == "NOTE"})   # no schematic
        self.assertTrue(os.path.exists(os.path.join(out, "review.md")))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(review.main([path, "--out", out, "--skip", "erc,stock"]), 0)   # report-only by default


if __name__ == "__main__":
    unittest.main()
