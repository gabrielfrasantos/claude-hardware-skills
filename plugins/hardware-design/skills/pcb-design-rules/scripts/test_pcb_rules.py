#!/usr/bin/env python3
"""Self-test for pcb_rules.py geometry checks. Run: python3 test_pcb_rules.py (no KiCad needed)."""
import math
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

    def test_right_angle_corner(self):
        m = self.metrics(board(seg(0, 0, 5, 0), seg(5, 0, 5, 5)))
        self.assertEqual((m["right_angle_corners"], m["acute_corners"]), (1, 0))

    def test_tee_is_a_junction(self):
        m = self.metrics(board(seg(0, 0, 5, 0), seg(5, 0, 10, 0), seg(5, 0, 5, 5)))
        self.assertEqual((m["track_junctions"], m["right_angle_corners"], m["acute_corners"]), (1, 0, 0))

    def test_branch_on_a_pad_is_allowed(self):
        m = self.metrics(board(fp("R1", 5, 0, 0, [("1", 0, 0)], "N"), seg(0, 0, 5, 0), seg(5, 0, 10, 0), seg(5, 0, 5, 5)))
        self.assertEqual((m["track_junctions"], m["right_angle_corners"]), (0, 0))

    def test_right_angle_on_a_via_is_flagged(self):
        via = '(via (at 5 0) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "N"))\n'
        m = self.metrics(board(via, seg(0, 0, 5, 0), seg(5, 0, 5, 5)))
        self.assertEqual(m["right_angle_corners"], 1)


class Copper(unittest.TestCase):
    def test_crossing_nets_short(self):
        sh, gp = pcb_rules.copper_check(board(seg(0, 0, 10, 0, "A"), seg(5, -5, 5, 5, "B")), 0.1)
        self.assertEqual((len(sh), len(gp)), (1, 0))

    def test_gap_below_limit(self):
        # 0.25 mm wide tracks, centres 0.3 mm apart: 0.05 mm gap
        sh, gp = pcb_rules.copper_check(board(seg(0, 0, 10, 0, "A"), seg(0, 0.3, 10, 0.3, "B")), 0.1)
        self.assertEqual((len(sh), len(gp)), (0, 1))
        self.assertAlmostEqual(gp[0]["gap"], 0.05, places=3)

    def test_same_net_and_other_layer_ignored(self):
        sh, gp = pcb_rules.copper_check(board(seg(0, 0, 10, 0, "A"), seg(5, -5, 5, 5, "A"),
                                              seg(0, 0.1, 10, 0.1, "B", "B.Cu")), 0.1)
        self.assertEqual((len(sh), len(gp)), (0, 0))

    def test_roundrect_corner_is_round(self):
        # 1 x 1 mm pad, 25 % corner radius; a 0.6 mm via sits 0.2 mm off the rounded corner, on the diagonal
        r = 0.25
        corner_gap = math.hypot(0.5 - r, 0.5 - r)          # centre to the corner arc centre
        vx = vy = (corner_gap + r + 0.2 + 0.3) / math.sqrt(2)
        b = board('(footprint "X" (layer "F.Cu") (at 0 0 90) (property "Reference" "U1") '
                  '(pad "1" smd roundrect (at 0 0 90) (size 1 1) (layers "F.Cu") (roundrect_rratio 0.25) (net "A")))\n',
                  f'(via (at {vx} {vy}) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "B"))\n')
        sh, gp = pcb_rules.copper_check(b, 0.25)
        self.assertEqual(len(gp), 1)
        self.assertAlmostEqual(gp[0]["gap"], 0.2, places=3)

class Parsing(unittest.TestCase):
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
        self.assertIn("track_angle (min 135)", block)   # "135deg" makes KiCad drop the whole file


if __name__ == "__main__":
    unittest.main()
