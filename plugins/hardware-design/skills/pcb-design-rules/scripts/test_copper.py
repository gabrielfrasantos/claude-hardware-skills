#!/usr/bin/env python3
"""Self-test for copper.py (teardrops, pours, planes). Run: python3 test_copper.py (no KiCad needed)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import copper  # noqa: E402
import pcb_rules  # noqa: E402

L2 = '(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t)'
L4 = '(layers\n\t\t(0 "F.Cu" signal)\n\t\t(4 "In1.Cu" signal)\n\t\t(6 "In2.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t)'
TD_ON = "(teardrops (best_length_ratio 0.5) (max_length 1) (filter_ratio 0.9) (enabled yes))"
TD_OFF = "(teardrops (best_length_ratio 0.5) (max_length 1) (filter_ratio 0.9) (enabled no))"


def board_text(*items, layers=L2):
    return f'(kicad_pcb\n\t(version 20260206)\n\t{layers}\n' + "".join(items) + ")\n"


def pad_fp(ref, x, y, net, td="", kind="smd", size=1.0, layers='"F.Cu"'):
    return (f'\t(footprint "X"\n\t\t(layer "F.Cu")\n\t\t(uuid "u-{ref}")\n\t\t(at {x} {y})\n'
            f'\t\t(property "Reference" "{ref}"\n\t\t)\n'
            f'\t\t(pad "1" {kind} rect\n\t\t\t(at 0 0)\n\t\t\t(size {size} {size})\n\t\t\t(layers {layers})\n'
            f'\t\t\t(net "{net}")\n\t\t\t{td}\n\t\t\t(uuid "p-{ref}")\n\t\t)\n\t)\n')


def via(x, y, net, td=""):
    return (f'\t(via\n\t\t(at {x} {y})\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n\t\t{td}\n'
            f'\t\t(net "{net}")\n\t\t(uuid "v-{x}-{y}")\n\t)\n')


def seg(x1, y1, x2, y2, net, layer="F.Cu", w=0.25):
    return f'\t(segment (start {x1} {y1}) (end {x2} {y2}) (width {w}) (layer "{layer}") (net "{net}"))\n'


def zone(net, layer, *polys, teardrop=False, name=""):
    attr = "(attr (teardrop (type padvia)))" if teardrop else ""
    fills = "".join(f'(filled_polygon (layer "{layer}") (pts {" ".join(f"(xy {x} {y})" for x, y in p)}))' for p in polys)
    return f'\t(zone (net "{net}") (layer "{layer}") (uuid "z") (name "{name}") {attr} (min_thickness 0.2) {fills})\n'


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def report(*items, layers=L2, pro=None, **kw):
    return copper.report(pcb_rules.Board(text=board_text(*items, layers=layers)), pro, **kw)[0]


class Teardrops(unittest.TestCase):
    def test_set_teardrops(self):
        text = board_text(pad_fp("R1", 0, 0, "A"), pad_fp("R2", 5, 0, "B", td=TD_OFF), pad_fp("R3", 9, 0, "RF_OUT"),
                          pad_fp("H1", 20, 0, "", kind="np_thru_hole"), pad_fp("R4", 30, 0, ""), via(40, 0, "A"))
        out, n = copper.set_teardrops(text, exclude="^RF")
        self.assertEqual(n, 4)                     # R1 inserted, R2 flipped, RF_OUT inserted (off), via inserted
        b = pcb_rules.Board(text=out)
        td = {p["ref"]: p["td"]["enabled"] for p in b.pads}
        self.assertEqual(td, {"R1": True, "R2": True, "R3": False, "H1": False, "R4": False})
        self.assertTrue(b.vias[0]["td"]["enabled"])
        self.assertEqual(copper.set_teardrops(out, exclude="^RF")[1], 0)     # idempotent
        self.assertIn("\t\t\t(teardrops\n\t\t\t\t(best_length_ratio 0.5)", out)  # KiCad's layout and indentation

    def test_disabled_missing_present(self):
        track = seg(0, 0, 3, 0, "A")
        self.assertEqual(report(pad_fp("R1", 0, 0, "A"), track)["teardrops_disabled"], 1)
        m = report(pad_fp("R1", 0, 0, "A", td=TD_ON), track)
        self.assertEqual((m["teardrops_disabled"], m["teardrops_missing"]), (0, 1))
        drop = zone("A", "F.Cu", [(0.5, -0.5), (1.2, -0.1), (1.2, 0.1), (0.5, 0.5)], teardrop=True)
        self.assertEqual(report(pad_fp("R1", 0, 0, "A", td=TD_ON), track, drop)["teardrops_missing"], 0)
        # a pad in a pour of its own net: KiCad prefers the zone connection and draws no teardrop
        pour = zone("A", "F.Cu", rect(-2, -2, 2, 2))
        self.assertEqual(report(pad_fp("R1", 0, 0, "A", td=TD_ON), track, pour)["teardrops_missing"], 0)
        # a track as wide as the pad (above filter_ratio) gets none either
        self.assertEqual(report(pad_fp("R1", 0, 0, "A", td=TD_ON), seg(0, 0, 3, 0, "A", w=1.0))["teardrops_missing"], 0)
        # not measured when apply recorded teardrops off
        self.assertIsNone(report(pad_fp("R1", 0, 0, "A"), track, teardrops=False)["teardrops_disabled"])


class Pours(unittest.TestCase):
    def test_island(self):
        m = report(pad_fp("R1", 0, 0, "A"), zone("A", "F.Cu", rect(-1, -1, 1, 1), rect(10, 10, 12, 12)))
        self.assertEqual(m["zone_islands"], 1)

    def test_unfilled(self):
        self.assertEqual(report(zone("A", "F.Cu"))["zone_unfilled"], 1)

    def test_neck_uses_the_net_class_width(self):
        bridge = [(0, 0), (4, 0), (4, 1.9), (6, 1.9), (6, 0), (10, 0), (10, 4), (6, 4), (6, 2.1), (4, 2.1), (4, 4), (0, 4)]
        items = (pad_fp("R1", 2, 2, "VBUS"), pad_fp("R2", 8, 2, "VBUS"), zone("VBUS", "F.Cu", bridge))
        with tempfile.TemporaryDirectory() as d:
            pro = os.path.join(d, "b.kicad_pro")
            with open(pro, "w") as f:
                json.dump({"net_settings": {"classes": [{"name": "Default", "track_width": 0.15},
                                                        {"name": "PWR", "track_width": 1.0}],
                                            "netclass_patterns": [{"netclass": "PWR", "pattern": "VBUS"}]}}, f)
            self.assertEqual(report(*items, pro=pro)["zone_necks"], 1)      # 0.2 mm bridge < 1.0 mm
        self.assertEqual(report(*items)["zone_necks"], 0)                   # no classes: 0.2 mm min_thickness

    def test_ground_neck_with_its_own_via_is_fine(self):
        bridge = [(0, 0), (4, 0), (4, 1.9), (6, 1.9), (6, 0), (10, 0), (10, 4), (6, 4), (6, 2.1), (4, 2.1), (4, 4), (0, 4)]
        items = [pad_fp("R1", 2, 2, "GND"), pad_fp("R2", 8, 2, "GND"), zone("GND", "F.Cu", bridge)]
        with tempfile.TemporaryDirectory() as d:
            pro = os.path.join(d, "b.kicad_pro")
            with open(pro, "w") as f:
                json.dump({"net_settings": {"classes": [{"name": "Default", "track_width": 1.0}]}}, f)
            self.assertEqual(report(*items, pro=pro)["zone_necks"], 1)
            self.assertEqual(report(*items, via(9, 3, "GND"), pro=pro)["zone_necks"], 0)

    def test_unstitched_ground(self):
        fill = zone("GND", "F.Cu", rect(0, 0, 5, 5))
        self.assertEqual(report(pad_fp("C1", 1, 1, "GND"), fill)["unstitched_ground"], 1)
        self.assertEqual(report(pad_fp("C1", 1, 1, "GND"), fill, via(4, 4, "GND"))["unstitched_ground"], 0)

    def test_stitching_distance(self):
        m = report(via(0, 0, "GND"), zone("GND", "B.Cu", rect(0, 0, 10, 10)))
        self.assertAlmostEqual(m["gnd_via_max_distance_mm"], 14.14, places=1)


class Planes(unittest.TestCase):
    def test_reference_layer(self):
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        roles = copper.roles_for(layers)
        self.assertEqual(roles, {"F.Cu": "SIG", "In1.Cu": "GND", "In2.Cu": "PWR", "B.Cu": "SIG"})
        self.assertEqual(copper.reference_layer("F.Cu", layers, roles), "In1.Cu")
        self.assertEqual(copper.reference_layer("B.Cu", layers, roles), "In2.Cu")   # the adjacent plane

    def test_plane_split(self):
        v = via(1, 1, "GND") + via(9, 1, "GND")
        split = zone("GND", "In1.Cu", rect(0, 0, 4, 4), rect(6, 0, 10, 4))
        self.assertEqual(report(v, split, layers=L4)["gnd_plane_splits"], 1)
        # a second ground net beside the main one is a partition, not a split
        part = zone("GND", "In1.Cu", rect(0, 0, 4, 4)) + zone("PGND", "In1.Cu", rect(6, 0, 7, 4))
        self.assertEqual(report(v, via(6.5, 1, "PGND"), part, layers=L4)["gnd_plane_splits"], 0)
        self.assertEqual(report(v, layers=L4)["gnd_plane_splits"], 1)                # no plane at all

    def test_signal_over_gap(self):
        plane = zone("GND", "In1.Cu", rect(0, -5, 4, 5), rect(6, -5, 10, 5))
        m = report(via(1, 4, "GND"), plane, seg(1, 0, 9, 0, "CLK"), layers=L4)
        self.assertAlmostEqual(m["signal_over_plane_gap_mm"], 2.0, places=2)


class Managed(unittest.TestCase):
    def test_roles_and_teardrops_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            dru = os.path.join(d, "b.kicad_dru")
            fab = pcb_rules.combined_rules(["jlcpcb"], 4)[0]
            roles = {"F.Cu": "SIG", "In1.Cu": "GND", "In2.Cu": "PWR", "B.Cu": "SIG"}
            pcb_rules.write_dru(dru, pcb_rules.dru_block(fab, ["jlcpcb"], 4, [], roles, "on, off for nets matching ^RF"))
            self.assertEqual(pcb_rules.managed_roles(dru), roles)
            self.assertEqual(pcb_rules.managed_teardrops(dru), (True, "^RF"))
            self.assertEqual(pcb_rules.managed_fabs(dru), ["jlcpcb"])
            pcb_rules.write_dru(dru, pcb_rules.dru_block(fab, ["jlcpcb"], 4, [], None, "off"))
            self.assertEqual(pcb_rules.managed_teardrops(dru), (False, None))
            self.assertIsNone(pcb_rules.managed_roles(dru))


if __name__ == "__main__":
    unittest.main()
