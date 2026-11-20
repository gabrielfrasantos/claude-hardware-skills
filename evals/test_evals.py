#!/usr/bin/env python3
"""Self-test for the eval harness. Run: python3 evals/test_evals.py (no KiCad, no Claude needed)."""
import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boardgeo as G  # noqa: E402
import make_fixture as F  # noqa: E402
import metrics as M  # noqa: E402
import run as RUN  # noqa: E402

HEAD = '(kicad_pcb\n\t(version 20260206)\n\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t)\n'
OUTLINE = "".join(f'\t(gr_line\n\t\t(start {a} {b})\n\t\t(end {c} {d})\n\t\t(layer "Edge.Cuts")\n\t)\n'
                  for a, b, c, d in [(0, 0, 50, 0), (50, 0, 50, 30), (50, 30, 0, 30), (0, 30, 0, 0)])


def fp(ref, x, y, nets, locked=False, rot=0, half=1.0):
    lk = "\t\t(locked yes)\n" if locked else ""
    pads = "".join(f'\t\t(pad "{i + 1}" smd rect\n\t\t\t(at {px} 0 {rot})\n\t\t\t(size 0.6 0.6)\n'
                   f'\t\t\t(layers "F.Cu")\n\t\t\t(net "{n}")\n\t\t)\n'
                   for i, (n, px) in enumerate(zip(nets, (-0.5, 0.5))))
    court = f'\t\t(fp_rect\n\t\t\t(start {-half} -0.6)\n\t\t\t(end {half} 0.6)\n\t\t\t(layer "F.CrtYd")\n\t\t)\n'
    return (f'\t(footprint "X"\n{lk}\t\t(layer "F.Cu")\n\t\t(uuid "u-{ref}")\n\t\t(at {x} {y} {rot})\n'
            f'\t\t(property "Reference" "{ref}"\n\t\t\t(at 0 -1 0)\n\t\t\t(layer "F.SilkS")\n\t\t)\n{court}{pads}\t)\n')


SEG = '\t(segment\n\t\t(start 1 1)\n\t\t(end 2 1)\n\t\t(width 0.2)\n\t\t(layer "F.Cu")\n\t\t(net "A")\n\t)\n'
VIA = '\t(via\n\t\t(at 3 3)\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "A")\n\t)\n'
ZONE = '\t(zone\n\t\t(net "VBUS")\n\t\t(layer "F.Cu")\n\t\t(uuid "z1")\n\t)\n'
KEEPOUT = '\t(zone\n\t\t(net "")\n\t\t(layer "F.Cu")\n\t\t(uuid "z2")\n\t\t(keepout\n\t\t\t(tracks not_allowed)\n\t\t)\n\t)\n'


def text(*items):
    return HEAD + OUTLINE + "".join(items) + ")\n"


class Geometry(unittest.TestCase):
    def test_pads_follow_rotation(self):
        b = G.Board(text=text(fp("R1", 10, 10, ["A", "B"], rot=90)))
        p1, p2 = b.footprints[0]["pads"]
        self.assertAlmostEqual(p1["x"], 10)
        self.assertAlmostEqual(p1["y"], 10.5)   # -0.5 along x, turned 90° counter-clockwise on a y-down board
        self.assertAlmostEqual(p2["y"], 9.5)

    def test_outline_and_inside(self):
        b = G.Board(text=text())
        self.assertEqual(len(b.outline), 4)
        self.assertTrue(G.inside(b.outline, 25, 15))
        self.assertFalse(G.inside(b.outline, 60, 15))

    def test_overlap_uses_the_real_outline(self):
        notch = ('\t(footprint "L"\n\t\t(layer "F.Cu")\n\t\t(uuid "u-U1")\n\t\t(at 0 0 0)\n'
                 '\t\t(property "Reference" "U1"\n\t\t)\n' +
                 "".join(f'\t\t(fp_line\n\t\t\t(start {a} {b})\n\t\t\t(end {c} {d})\n\t\t\t(layer "F.CrtYd")\n\t\t)\n'
                         for a, b, c, d in [(0, 0, 10, 0), (10, 0, 10, 10), (10, 10, 5, 10), (5, 10, 5, 5),
                                            (5, 5, 0, 5), (0, 5, 0, 0)]) + '\t)\n')
        # an L-shaped courtyard; a part in its notch does not overlap it, one across its arm does
        self.assertEqual(M.overlaps(G.Board(text=text(notch, fp("C1", 2.5, 7.5, ["A", "B"])))), [])
        self.assertEqual(M.overlaps(G.Board(text=text(notch, fp("C1", 2.5, 5.2, ["A", "B"])))), [("C1", "U1")])
        self.assertEqual(M.overlaps(G.Board(text=text(notch, fp("C1", 2.5, 5.6, ["A", "B"])))), [])   # touching

    def test_crossings(self):
        edges = {"A": [((0, 0), (10, 10))], "B": [((0, 10), (10, 0))], "C": [((20, 0), (30, 0))]}
        self.assertEqual(M.crossings(edges), 1)
        self.assertEqual(M.crossings({"A": [((0, 0), (10, 10))], "B": [((10, 10), (20, 0))]}), 0)  # shared end

    def test_mst(self):
        self.assertEqual(len(M.mst_edges([(0, 0), (1, 0), (5, 0)])), 2)
        self.assertEqual(M.mst_edges([(0, 0)]), [])


class Editing(unittest.TestCase):
    def test_move_and_lock_roundtrip(self):
        t = text(fp("R1", 10, 10, ["A", "B"]))
        (_, s, e), = [b for b in G.blocks(t) if b[0] == "footprint"]
        block = G.footprint_text(t[s:e], x=40.25, y=5, locked=True)
        f = G.Board(text=t[:s] + block + t[e:]).footprints[0]
        self.assertEqual((f["x"], f["y"], f["locked"]), (40.25, 5.0, True))
        f = G.Board(text=t[:s] + G.footprint_text(block, locked=False) + t[e:]).footprints[0]
        self.assertFalse(f["locked"])
        self.assertEqual(G.footprint_text(block, locked=False).count("\n"), t[s:e].count("\n"))

    def test_blocks_skip_strings(self):
        t = '(a\n\t(b "x)(y")\n\t(c 1)\n)'
        self.assertEqual([k for k, _, _ in G.blocks(t)], ["b", "c"])


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        src = self.tmp / "src"
        src.mkdir()
        board = text(fp("J1", 5, 15, ["A", "GND"], locked=True), fp("U1", 20, 15, ["A", "VBUS"]),
                     fp("C1", 21, 18, ["VBUS", "GND"]), fp("R1", 30, 15, ["A", "B"]), SEG, VIA, ZONE, KEEPOUT)
        (src / "b.kicad_pcb").write_text(board)
        (src / "b.kicad_pro").write_text('{"meta": {"filename": "b.kicad_pro"}}')
        spec = {"name": "t", "source": {"repo": "x", "commit": "0", "board": "b.kicad_pcb"},
                "anchors": {"locked": True}}
        self.out, self.manifest, self.baseline = F.make(spec, src, self.tmp / "fixtures")

    def test_fixture(self):
        b = G.Board(self.out / "t.kicad_pcb")
        refs = b.by_ref()
        self.assertEqual(list(self.manifest["anchors"]), ["J1"])
        self.assertTrue(refs["J1"]["locked"])
        self.assertEqual((refs["J1"]["x"], refs["J1"]["y"]), (5.0, 15.0))
        for r in ("U1", "C1", "R1"):
            self.assertFalse(refs[r]["locked"])
            self.assertGreater(min(p["x"] for p in refs[r]["pads"]), 50)       # parked right of the outline
        self.assertEqual((b.vias, b.segments), (0, 0))
        self.assertIn("(keepout", (self.out / "t.kicad_pcb").read_text())
        self.assertEqual(self.manifest["plane_nets"], ["VBUS"])
        self.assertTrue(self.baseline["valid"])
        self.assertEqual(json.loads((self.out / "t.kicad_pro").read_text())["meta"]["filename"], "t.kicad_pro")
        m = M.measure(b, self.manifest)
        self.assertEqual((m["parts_off_board"], m["anchors_moved"], m["valid"]), (3, 0, False))

    def test_scoring_a_placement(self):
        case = {"_manifest": self.manifest, "_baseline": self.baseline}
        wd = self.tmp / "work"
        wd.mkdir()
        t = (self.out / "t.kicad_pcb").read_text()
        edits = []
        for (kind, s, e), (x, y) in zip([b for b in G.blocks(t) if b[0] == "footprint"][1:], [(20, 15), (20, 18), (30, 15)]):
            edits.append((s, e, G.footprint_text(t[s:e], x=x, y=y)))
        (wd / "t.kicad_pcb").write_text(G.rewrite(t, edits))
        r = RUN.score(case, wd)
        self.assertTrue(r["valid"], r)
        self.assertEqual(r["overlaps"], 0)
        (wd / "t.kicad_pcb").write_text(G.rewrite(t, edits).replace("(at 20 18", "(at 20 15.5"))
        self.assertGreater(RUN.score(case, wd)["overlaps"], 0)
        (wd / "t.kicad_pcb").write_text("(kicad_pcb (broken")
        self.assertFalse(RUN.score(case, wd)["valid"])

    def test_transcript_facts(self):
        p = self.tmp / "transcript.jsonl"
        p.write_text("\n".join(json.dumps(e) for e in [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill",
                                                           "input": {"skill": "hardware-design:power-pcb-layout"}}]}},
            {"type": "result", "total_cost_usd": 1.5, "num_turns": 12, "duration_ms": 61000, "result": "done"}]))
        f = RUN.transcript_facts(p)
        self.assertEqual((f["skills"], f["cost_usd"], f["turns"], f["duration_s"]),
                         (["hardware-design:power-pcb-layout"], 1.5, 12, 61))


if __name__ == "__main__":
    unittest.main()
