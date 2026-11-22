#!/usr/bin/env python3
"""Self-test for route.py (no KiCad, no Java): DSN export and session import on a small board."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import route as RT  # noqa: E402

BOARD = '''(kicad_pcb
	(version 20260206)
	(generator "pcbnew")
	(layers
		(0 "F.Cu" signal)
		(2 "B.Cu" signal)
		(25 "Edge.Cuts" user)
	)
	(footprint "R:R_0402"
		(layer "F.Cu")
		(at 10 10 90)
		(property "Reference" "R1")
		(pad "1" smd rect (at -0.5 0 90) (size 0.5 0.6) (layers "F.Cu" "F.Mask") (net "A"))
		(pad "2" smd roundrect (at 0.5 0 90) (size 0.5 0.6) (layers "F.Cu" "F.Mask") (roundrect_rratio 0.25) (net "B"))
	)
	(footprint "J:Hdr"
		(layer "F.Cu")
		(at 20 10)
		(property "Reference" "J1")
		(pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1) (layers "*.Cu" "*.Mask") (net "A"))
		(pad "2" thru_hole oval (at 2.54 0) (size 1.7 2.2) (drill 1) (layers "*.Cu" "*.Mask") (net "GND"))
		(pad "" np_thru_hole circle (at 1.27 3) (size 1 1) (drill 1) (layers "*.Cu" "*.Mask"))
	)
	(gr_rect (start 0 0) (end 30 20) (layer "Edge.Cuts"))
	(zone (net "GND") (layer "B.Cu") (polygon (pts (xy 1 1) (xy 29 1) (xy 29 19) (xy 1 19))))
	(zone (layers "F.Cu" "B.Cu") (keepout (tracks not_allowed) (vias allowed))
		(polygon (pts (xy 25 15) (xy 28 15) (xy 28 18) (xy 25 18))))
	(segment (start 10 10.5) (end 15 10.5) (width 0.25) (layer "F.Cu") (net "A"))
	(via (at 15 10.5) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "A"))
)
'''

PRO = {"net_settings": {"classes": [{"name": "Default", "track_width": 0.2, "clearance": 0.2, "via_diameter": 0.6,
                                     "via_drill": 0.3},
                                    {"name": "PWR_1A", "track_width": 0.3, "clearance": 0.15, "via_diameter": 0.8,
                                     "via_drill": 0.4}],
                        "netclass_assignments": {"B": ["PWR_1A"]}}}

SES = '''(session board
  (routes
    (resolution um 10)
    (network_out
      (net A
        (wire (path F.Cu 2500 100000 -105000 150000 -105000))
        (wire (path B.Cu 2500 150000 -105000 200000 -105000 200000 -100000))
        (via "Via[0-1]_600:300_um" 150000 -105000)
      )
      (net "B"
        (via "Via[0-1]_800:400_um" 120000 -120000)
      )
    )
  )
)
'''


def project():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "b.kicad_pcb")
    with open(path, "w") as f:
        f.write(BOARD)
    with open(os.path.join(d, "b.kicad_pro"), "w") as f:
        json.dump(PRO, f)
    return path


class Dsn(unittest.TestCase):
    def setUp(self):
        self.text, problems = RT.export_dsn(RT.Board(project()))
        self.assertEqual(problems, [])

    def test_balanced_and_structure(self):
        body = self.text.replace('(string_quote ")', "")
        self.assertEqual(body.count("("), body.count(")"))
        self.assertEqual(RT.parse_ses(body)[0], "pcb")
        self.assertIn("(boundary (path pcb 0 ", self.text)
        self.assertIn("(plane GND (polygon B.Cu 0 1000 -1000", self.text)
        self.assertIn('(keepout "" (polygon F.Cu 0 25000 -15000', self.text)
        self.assertIn("(snap_angle fortyfive_degree)", self.text)

    def test_pins_in_footprint_frame_and_rotation(self):
        self.assertIn("(place R1 10000 -10000 front 90)", self.text)
        self.assertIn("1 -500 0)", self.text)
        r1_rect = [l for l in self.text.splitlines() if "(polygon F.Cu 0 " in l and "250 -300" in l]
        self.assertTrue(r1_rect, "pad rect 0.5 x 0.6 in the footprint frame (pad angle 90 - footprint 90 = 0)")

    def test_through_hole_and_npth(self):
        self.assertIn("(circle F.Cu 1700)", self.text)
        self.assertIn("(circle B.Cu 1700)", self.text)
        self.assertIn('(keepout "" (circle F.Cu 1400 1270 -3000))', self.text)

    def test_network_classes_and_wiring(self):
        self.assertIn("(net A (pins R1-1 J1-1))", self.text)
        self.assertIn("(class PWR_1A B", self.text)
        self.assertIn("(use_via Via[0-1]_800:400_um)", self.text)
        self.assertIn("(rule (width 300) (clearance 150))", self.text)
        self.assertIn("(wire (path F.Cu 250 10000 -10500 15000 -10500) (net A) (type protect))", self.text)
        self.assertIn("(via Via[0-1]_600:300_um 15000 -10500 (net A) (type protect))", self.text)

    def test_net_selection(self):
        text, _ = RT.export_dsn(RT.Board(project()), keep=lambda n: n != "B")
        self.assertNotIn("(net B ", text)
        self.assertIn("(net A ", text)

    def test_back_side_is_refused(self):
        path = project()
        with open(path) as f:
            t = f.read().replace('(layer "F.Cu")\n\t\t(at 20 10)', '(layer "B.Cu")\n\t\t(at 20 10)')
        with open(path, "w") as f:
            f.write(t)
        _, problems = RT.export_dsn(RT.Board(path))
        self.assertEqual(problems, ["J1: on the back side (not supported yet)"])


class Import(unittest.TestCase):
    def test_new_tracks_and_vias_only(self):
        path = project()
        n_s, n_v = RT.import_session(path, SES)
        self.assertEqual((n_s, n_v), (2, 1))
        b = RT.Board(path)
        segs = [(s[0], RT.child(s, "start")[1:], RT.child(s, "end")[1:], RT.child(s, "layer")[1])
                for s in RT.children(b.root, "segment")]
        self.assertIn(("segment", ["15", "10.5"], ["20", "10.5"], "B.Cu"), segs)
        self.assertIn(("segment", ["20", "10.5"], ["20", "10"], "B.Cu"), segs)
        via = [v for v in RT.children(b.root, "via") if RT.child(v, "net")[1] == "B"][0]
        self.assertEqual((RT.child(via, "size")[1], RT.child(via, "drill")[1]), ("0.8", "0.4"))
        self.assertEqual(RT.import_session(path, SES), (0, 0))


if __name__ == "__main__":
    unittest.main()
