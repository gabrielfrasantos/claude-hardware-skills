#!/usr/bin/env python3
"""Self-test for netclasses.py. Run: python3 test_netclasses.py (no KiCad needed)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netclasses as N  # noqa: E402

LAYERS = '(layers (0 "F.Cu" signal) (4 "In1.Cu" signal) (6 "In2.Cu" signal) (2 "B.Cu" signal))'
STACKUP = ('(setup (stackup (layer "F.Cu" (type "copper") (thickness 0.035)) (layer "In1.Cu" (type "copper") '
           '(thickness 0.0152)) (layer "In2.Cu" (type "copper") (thickness 0.0152)) (layer "B.Cu" (type "copper") '
           '(thickness 0.035))))')


def fp(ref, x, y, net, size=1.0):
    return (f'(footprint "X" (layer "F.Cu") (at {x} {y}) (property "Reference" "{ref}") '
            f'(pad "1" smd rect (at 0 0) (size {size} {size}) (layers "F.Cu") (net "{net}")))\n')


def seg(x1, y1, x2, y2, net, w, layer="F.Cu"):
    return f'(segment (start {x1} {y1}) (end {x2} {y2}) (width {w}) (layer "{layer}") (net "{net}"))\n'


def zone(net):
    return f'(zone (net "{net}") (layer "F.Cu") (uuid "z") (min_thickness 0.2))\n'


class Project:
    def __init__(self, assignments, items, patterns=()):
        self.dir = tempfile.mkdtemp()
        self.pro = os.path.join(self.dir, "b.kicad_pro")
        self.pcb = os.path.join(self.dir, "b.kicad_pcb")
        default = {"name": "Default", "track_width": 0.2, "clearance": 0.2, "via_diameter": 0.6, "via_drill": 0.3,
                   "priority": 2147483647, "diff_pair_width": 0.2, "diff_pair_gap": 0.25}
        with open(self.pro, "w") as f:
            json.dump({"net_settings": {"classes": [default], "netclass_assignments": assignments,
                                        "netclass_patterns": list(patterns)}}, f)
        self.write(items)

    def write(self, items):
        with open(self.pcb, "w") as f:
            f.write(f"(kicad_pcb (version 20260206) {LAYERS} {STACKUP}\n" + "".join(items) + ")\n")

    def classes(self):
        with open(self.pro) as f:
            return {c["name"]: c for c in json.load(f)["net_settings"]["classes"]}

    def run(self, cmd, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = N.main([cmd, self.pro if cmd == "apply" else self.pcb, *extra] +
                          (["--json", os.path.join(self.dir, "r.json")] if cmd == "check" else []))
        m = None
        if cmd == "check":
            with open(os.path.join(self.dir, "r.json")) as f:
                m = json.load(f)["metrics"]
        return code, m, out.getvalue()


class Sizing(unittest.TestCase):
    def test_ipc2221_reference_values(self):
        self.assertAlmostEqual(N.width_mm(10, 10, 0.035), 7.2, places=1)    # power-pcb-layout §3.5
        self.assertAlmostEqual(N.width_mm(1, 10, 0.035), 0.30, places=2)

    def test_names(self):
        self.assertEqual(N.parse("PWR_2p5A_48V"), {"kind": "PWR", "amps": 2.5, "volts": 48.0})
        self.assertEqual(N.parse("GND")["amps"], None)
        self.assertEqual(N.parse("DIFF_90")["kind"], "DIFF_90")
        for bad in ("PWR", "SIGNAL_2A", "MOTOR", "PWR_2X", "Default"):
            self.assertIsNone(N.parse(bad), bad)

    def test_spec(self):
        design = {"track": 0.15, "clearance": 0.15, "via_drill": 0.3, "via_diameter": 0.6}
        s = N.spec("PWR_4A_48V", design, 0.035, 0.0152, 10)
        self.assertAlmostEqual(s["track_width"], N.width_mm(4, 10, 0.035), places=3)
        self.assertGreater(s["inner_width"], s["track_width"])                # thinner inner copper
        self.assertTrue(s["pour"])                                            # above 3 A on 1 oz (D21)
        self.assertEqual(s["clearance"], 0.6)                                 # IPC-2221 B2, 31-100 V
        self.assertFalse(N.spec("PWR_1A", design, 0.035, 0.0152, 10)["pour"])
        self.assertEqual(N.spec("SIGNAL", design, 0.035, 0.0152, 10)["track_width"], 0.15)
        with self.assertRaises(SystemExit):
            N.spec("PWR_1A_600V", design, 0.035, 0.0152, 10)


class Flow(unittest.TestCase):
    def test_apply_then_check(self):
        p = Project({"VBUS": ["PWR_4A"], "CLK": ["CLK"], "USB_P": ["DIFF_90"]},
                    [fp("J1", 0, 0, "VBUS", 3), fp("U1", 20, 0, "VBUS", 3), fp("U2", 0, 10, "CLK"),
                     fp("U3", 20, 10, "CLK"), fp("R1", 0, 20, "SDA"), fp("R2", 20, 20, "SDA"),
                     seg(0, 0, 20, 0, "VBUS", 0.5), seg(0, 10, 20, 10, "CLK", 0.15)])
        self.assertEqual(p.run("apply")[0], 0)
        c = p.classes()
        self.assertAlmostEqual(c["PWR_4A"]["track_width"], round(N.width_mm(4, 10, 0.035), 3))
        self.assertEqual(c["DIFF_90"]["track_width"], 0.2)                    # impedance class left to the user
        code, m, _ = p.run("check")
        self.assertEqual(code, 1)
        self.assertEqual(m["nets_in_default"], 1)                             # SDA
        self.assertEqual(m["tracks_below_class_width"], 1)                    # VBUS at 0.5 mm
        self.assertEqual(m["required_pours_missing"], 1)                      # VBUS, 4 A
        self.assertEqual(m["class_values_stale"], 0)
        self.assertEqual(m["impedance_unset"], 0)                             # USB_P has no pads on this board

    def test_passes_when_done(self):
        items = [fp("J1", 0, 0, "VBUS", 3), fp("U1", 20, 0, "VBUS", 3), seg(0, 0, 20, 0, "VBUS", 2.5), zone("VBUS"),
                 fp("U2", 0, 10, "SDA"), fp("U3", 20, 10, "SDA"), seg(0, 10, 20, 10, "SDA", 0.15)]
        p = Project({"VBUS": ["PWR_4A"]}, items, patterns=[{"netclass": "SIGNAL", "pattern": "SDA"}])
        p.run("apply")
        code, m, out = p.run("check")
        self.assertEqual(code, 0, out)

    def test_neck_into_a_small_pad_is_allowed(self):
        items = [fp("J1", 0, 0, "VBUS", 3), fp("U1", 20, 0, "VBUS", 0.4), zone("VBUS"),
                 seg(0, 0, 18, 0, "VBUS", 2.5), seg(18, 0, 20, 0, "VBUS", 0.4)]
        p = Project({"VBUS": ["PWR_4A"]}, items)
        p.run("apply")
        self.assertEqual(p.run("check")[1]["tracks_below_class_width"], 0)
        p.write([i.replace("(width 0.4)", "(width 0.3)") for i in items])   # narrower than the pad: not a neck-in
        self.assertEqual(p.run("check")[1]["tracks_below_class_width"], 1)

    def test_inner_layers_use_inner_copper(self):
        items = [fp("J1", 0, 0, "VBUS", 3), fp("U1", 20, 0, "VBUS", 3), zone("VBUS"),
                 seg(0, 0, 20, 0, "VBUS", 2.5, layer="In2.Cu")]
        p = Project({"VBUS": ["PWR_4A"]}, items)
        p.run("apply")
        self.assertEqual(p.run("check")[1]["tracks_below_class_width"], 1)  # 2.5 mm is enough outside, not inside

    def test_unknown_stale_and_impedance(self):
        p = Project({"M": ["MOTOR"], "USB_P": ["DIFF_90"], "VBUS": ["PWR_1A"]},
                    [fp("A", 0, 0, "M"), fp("B", 5, 0, "M"), fp("C", 0, 5, "USB_P"), fp("D", 5, 5, "USB_P"),
                     fp("E", 0, 9, "VBUS"), fp("F", 5, 9, "VBUS")])
        p.run("apply")
        m = p.run("check")[1]
        self.assertEqual((m["unknown_classes"], m["impedance_unset"]), (1, 1))
        self.assertEqual(p.run("check", "--allow", "MOTOR")[1]["unknown_classes"], 0)
        with open(p.pro) as f:
            pj = json.load(f)
        for c in pj["net_settings"]["classes"]:
            if c["name"] == "PWR_1A":
                c["track_width"] = 0.2
        with open(p.pro, "w") as f:
            json.dump(pj, f)
        self.assertEqual(p.run("check")[1]["class_values_stale"], 1)


if __name__ == "__main__":
    unittest.main()
