#!/usr/bin/env python3
"""Self-test for pcb_rules.py geometry checks. Run: python3 test_pcb_rules.py (no KiCad needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcb_rules  # noqa: E402

HEAD = '(kicad_pcb (version 20260206) (layers (0 "F.Cu" signal) (2 "B.Cu" signal))\n'


def fp(ref, x, y, rot, pads, net):
    p = "".join(f'(pad "{n}" smd rect (at {px} {py}) (size 1 1) (layers "F.Cu") (net "{net}"))' for n, px, py in pads)
    return f'(footprint "R" (layer "F.Cu") (at {x} {y} {rot}) (property "Reference" "{ref}") {p})\n'


def seg(x1, y1, x2, y2, net="N", layer="F.Cu"):
    return f'(segment (start {x1} {y1}) (end {x2} {y2}) (width 0.25) (layer "{layer}") (net "{net}"))\n'


def board(*items):
    return pcb_rules.Board(text=HEAD + "".join(items) + ")")


class Geometry(unittest.TestCase):
    def metrics(self, b):
        return pcb_rules.geometry_report(b)[0]

    def test_clean_route_passes(self):
        # pad -> horizontal -> 45-degree miter -> vertical -> pad
        b = board(fp("R1", 0, 0, 0, [("1", 0, 0)], "N"), fp("R2", 20, 20, 0, [("1", 0, 0)], "N"),
                  seg(0, 0, 10, 0), seg(10, 0, 12, 2), seg(12, 2, 12, 12), seg(12, 12, 20, 20))
        m = self.metrics(b)
        self.assertEqual((m["any_angle_segments"], m["acute_corners"], m["jogs"]), (0, 0, 0))

    def test_any_angle(self):
        b = board(seg(0, 0, 10, 3))
        self.assertEqual(self.metrics(b)["any_angle_segments"], 1)

    def test_jog_between_parallel_runs(self):
        # 0.1 mm sideways step between two horizontal runs
        b = board(seg(0, 0, 5, 0), seg(5, 0, 5, 0.1), seg(5, 0.1, 10, 0.1))
        self.assertEqual(self.metrics(b)["jogs"], 1)

    def test_short_miter_is_not_a_jog(self):
        b = board(seg(0, 0, 5, 0), seg(5, 0, 5.1, 0.1), seg(5.1, 0.1, 5.1, 5))
        self.assertEqual(self.metrics(b)["jogs"], 0)

    def test_zero_length_is_a_jog(self):
        b = board(seg(0, 0, 5, 0), seg(5, 0, 5, 0))
        self.assertEqual(self.metrics(b)["jogs"], 1)

    def test_acute_corner(self):
        b = board(seg(0, 0, 5, 0), seg(5, 0, 1, 1))
        self.assertEqual(self.metrics(b)["acute_corners"], 1)

    def test_right_angle_and_tee_are_not_acute(self):
        b = board(seg(0, 0, 5, 0), seg(5, 0, 5, 5), seg(5, 0, 10, 0))
        self.assertEqual(self.metrics(b)["acute_corners"], 0)

    def test_pad_rotation(self):
        # KiCad rotates counter-clockwise on a y-down board: local (1, 0) at 90 degrees lands at (x, y - 1)
        b = board(fp("R1", 10, 10, 90, [("1", 1, 0)], "N"))
        p = b.pads[0]
        self.assertAlmostEqual(p["x"], 10)
        self.assertAlmostEqual(p["y"], 9)

    def test_kicad7_net_table(self):
        text = ('(kicad_pcb (version 20221018) (net 0 "") (net 1 "VCC") (layers (0 "F.Cu" signal))\n'
                '(segment (start 0 0) (end 1 0) (width 0.2) (layer "F.Cu") (net 1) (tstamp x)))')
        self.assertEqual(pcb_rules.Board(text=text).segments[0]["net"], "VCC")


class Rules(unittest.TestCase):
    def test_strictest_of_two_fabs(self):
        fab_min, design, _ = pcb_rules.combined_rules(["jlcpcb", "seeed"], 4)
        self.assertEqual(fab_min["via_drill"], 0.20)     # Seeed is stricter
        self.assertEqual(fab_min["npth_min_drill"], 0.50)  # JLCPCB is stricter
        self.assertIn("inner_track", fab_min)

    def test_pad_clearance_rule_only_for_low_classes(self):
        fab_min, _, _ = pcb_rules.combined_rules(["jlcpcb"], 2)
        self.assertNotIn("pad to pad", pcb_rules.dru_block(fab_min, ["jlcpcb"], 2, []))
        block = pcb_rules.dru_block(fab_min, ["jlcpcb"], 2, ["Fine"])
        self.assertIn("A.NetClass == 'Fine'", block)
        self.assertIn("track_angle (min 90)", block)   # "90deg" makes KiCad drop the whole file


if __name__ == "__main__":
    unittest.main()
