#!/usr/bin/env python3
"""Self-test for place.py. Run: python3 test_place.py (no KiCad needed; a few seconds)."""
import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boardgeo as G  # noqa: E402
import place as P  # noqa: E402

HEAD = '(kicad_pcb\n\t(version 20260206)\n\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t)\n'
EDGE = '\t(gr_rect\n\t\t(start 0 0)\n\t\t(end 40 20)\n\t\t(layer "Edge.Cuts")\n\t)\n'


def fp(ref, x, y, nets, locked=False, half=1.0):
    lk = "\t\t(locked yes)\n" if locked else ""
    pads = "".join(f'\t\t(pad "{i + 1}" smd rect\n\t\t\t(at {px} 0)\n\t\t\t(size 0.6 0.6)\n\t\t\t(layers "F.Cu")\n'
                   f'\t\t\t(net "{n}")\n\t\t)\n' for i, (n, px) in enumerate(zip(nets, (-0.5, 0.5))))
    return (f'\t(footprint "X"\n{lk}\t\t(layer "F.Cu")\n\t\t(uuid "u-{ref}")\n\t\t(at {x} {y})\n'
            f'\t\t(property "Reference" "{ref}"\n\t\t)\n'
            f'\t\t(fp_rect\n\t\t\t(start {-half} -0.8)\n\t\t\t(end {half} 0.8)\n\t\t\t(layer "F.CrtYd")\n\t\t)\n{pads}\t)\n')


KEEPOUT = ('\t(zone\n\t\t(net "")\n\t\t(layers "F.Cu")\n\t\t(uuid "k")\n\t\t(keepout\n\t\t\t(tracks allowed)\n'
           '\t\t\t(vias allowed)\n\t\t\t(pads allowed)\n\t\t\t(copperpour allowed)\n\t\t\t(footprints not_allowed)\n\t\t)\n'
           '\t\t(polygon\n\t\t\t(pts (xy 20 0) (xy 40 0) (xy 40 20) (xy 20 20))\n\t\t)\n\t)\n')


def board(*items):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "b.kicad_pcb")
    with open(path, "w") as f:
        f.write(HEAD + EDGE + "".join(items) + ")\n")
    return path


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = P.main(list(argv))
    return code, out.getvalue()


# J1 is the locked anchor at the left; R1..R4 are a chain parked right of the board, C1 decouples U1.
PARTS = [fp("J1", 3, 10, ["A", "GND"], locked=True), fp("R1", 60, 5, ["A", "B"]), fp("R2", 65, 5, ["B", "C"]),
         fp("R3", 70, 5, ["C", "D"]), fp("U1", 75, 5, ["D", "VDD"]), fp("C1", 80, 5, ["VDD", "GND"])]


class Optimize(unittest.TestCase):
    def test_parked_parts_end_up_placed_and_legal(self):
        path = board(*PARTS)
        before = P.measure(path)
        self.assertFalse(before["valid"])
        code, out = run("optimize", path, "--effort", "2", "--seed", "3")
        self.assertEqual(code, 0, out)
        after = P.measure(path)
        self.assertTrue(after["valid"], after["detail"])
        self.assertLess(after["ratsnest_mm"], before["ratsnest_mm"])
        j1 = G.Board(path).by_ref()["J1"]
        self.assertEqual((j1["x"], j1["y"], j1["locked"]), (3.0, 10.0, True))            # the anchor never moves
        for f in G.Board(path).footprints:                                                 # on the 0.05 mm grid
            self.assertAlmostEqual(round(f["x"] / 0.05) * 0.05, f["x"], places=6)

    def test_keepout_is_respected(self):
        path = board(*PARTS, KEEPOUT)
        run("optimize", path, "--effort", "2")
        m = P.measure(path)
        self.assertTrue(m["valid"], m["detail"])
        for f in G.Board(path).footprints:
            self.assertLess(f["x"], 20)

    def test_only_moves_the_named_parts(self):
        path = board(*PARTS)
        run("optimize", path, "--effort", "1", "--only", "R1,R2")
        refs = G.Board(path).by_ref()
        self.assertEqual((refs["R3"]["x"], refs["R3"]["y"]), (70.0, 5.0))
        self.assertLess(refs["R1"]["x"], 40)

    def test_refine_never_writes_a_worse_board(self):
        path = board(*PARTS)
        run("optimize", path, "--effort", "2")
        before = P.measure(path)
        run("optimize", path, "--refine", "--effort", "1", "--seed", "9")
        after = P.measure(path)
        self.assertTrue(after["valid"])
        self.assertLessEqual(after["ratsnest_mm"], before["ratsnest_mm"])
        self.assertLessEqual(after["crossings"], before["crossings"])

    def test_refine_keeps_parts_near_where_they_were(self):
        path = board(*PARTS)
        run("optimize", path, "--effort", "2")
        start = {p["ref"]: (p["x"], p["y"]) for p in P.Layout(path).parts}
        run("optimize", path, "--refine", "--effort", "1", "--seed", "3", "--max-move", "1.0")
        for p in P.Layout(path).parts:
            self.assertLessEqual(math.dist((p["x"], p["y"]), start[p["ref"]]), 1.0 + 1e-6, p["ref"])

    def test_propose_writes_nothing(self):
        path = board(*PARTS)
        with open(path) as f:
            text = f.read()
        run("propose", path, "--effort", "1")
        with open(path) as f:
            self.assertEqual(f.read(), text)


class Gate(unittest.TestCase):
    def test_enforce_and_baseline(self):
        path = board(*PARTS)
        self.assertEqual(run("gate", path)[0], 0)                       # report-only by default (D25)
        self.assertEqual(run("gate", path, "--enforce")[0], 1)          # parked parts are off the board
        run("optimize", path, "--effort", "2")
        base = os.path.join(os.path.dirname(path), "base.json")
        with open(base, "w") as f:
            json.dump(P.measure(path), f)
        code, out = run("gate", path, "--baseline", base, "--enforce")
        self.assertEqual(code, 0, out)
        self.assertIn("| 1.000 |", out)

    def test_render(self):
        path = board(*PARTS)
        png = os.path.join(os.path.dirname(path), "b.png")
        run("render", path, png)
        self.assertGreater(os.path.getsize(png), 1000)



class KiCad11(unittest.TestCase):
    def test_move_a_transformed_footprint(self):
        block = ('(footprint "R"\n\t\t(layer "F.Cu")\n\t\t(transform\n\t\t\t(translate 10 20)\n\t\t\t(rotate 90)\n'
                 '\t\t\t(scale 1 1)\n\t\t)\n\t)')
        out = G.footprint_text(block, 12.5, 7)
        self.assertIn("(translate 12.5 7)", out)
        self.assertIn("(rotate 90)", out)


if __name__ == "__main__":
    unittest.main()
