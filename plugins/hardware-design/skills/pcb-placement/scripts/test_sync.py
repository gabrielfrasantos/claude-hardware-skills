#!/usr/bin/env python3
"""Self-test for sync.py (no KiCad needed): a netlist and a footprint library in a temporary project."""
import contextlib
import io
import os
import pathlib
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sync as S  # noqa: E402

R = '''(footprint "R_0402"
	(version 20260206)
	(generator "test")
	(layer "F.Cu")
	(property "Reference" "REF**" (at 0 -1.2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
	(property "Value" "R_0402" (at 0 1.2 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
	(attr smd)
	(fp_rect (start -0.9 -0.5) (end 0.9 0.5) (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
	(pad "1" smd roundrect (at -0.5 0) (size 0.5 0.6) (layers "F.Cu" "F.Mask" "F.Paste") (roundrect_rratio 0.25))
	(pad "2" smd roundrect (at 0.5 0) (size 0.5 0.6) (layers "F.Cu" "F.Mask" "F.Paste") (roundrect_rratio 0.25))
	(embedded_fonts no)
)
'''
R_KEEPOUT = R.replace('"R_0402"\n', '"R_0603"\n', 1).replace(
    "\t(embedded_fonts no)", '\t(zone (layer "F.Cu") (hatch full 0.5) (keepout (tracks not_allowed))\n'
    "\t\t(polygon (pts (xy 1 0) (xy 2 0) (xy 2 1))))\n\t(embedded_fonts no)")


def comp(ref, value, fp, extra=""):
    return (f'(comp (ref "{ref}") (value "{value}") (footprint "{fp}") '
            f'(fields (field (name "LCSC") "C{ref[1:]}") (field (name "Footprint") "{fp}") (field (name "Datasheet")))'
            f'{extra} (property (name "Sheetfile") (value "main.kicad_sch")) '
            f'(sheetpath (names "/") (tstamps "/")) (tstamps "{ref}-uuid"))')


def netlist(comps, nets):
    body = " ".join(f'(net (code "{i}") (name "{n}") ' + " ".join(
        f'(node (ref "{r}") (pin "{p}") (pintype "passive"))' for r, p in nodes) + ")"
        for i, (n, nodes) in enumerate(nets.items(), 1))
    return f'(export (version "E") (components {" ".join(comps)}) (nets {body}))'


class Project:
    def __init__(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        lib = self.dir / "lib.pretty"
        lib.mkdir()
        (lib / "R_0402.kicad_mod").write_text(R)
        (lib / "R_0603.kicad_mod").write_text(R_KEEPOUT)
        (self.dir / "fp-lib-table").write_text('(fp_lib_table (version 7) (lib (name "lib") (type "KiCad") '
                                               '(uri "${KIPRJMOD}/lib.pretty") (options "") (descr "")))')
        self.board = self.dir / "b.kicad_pcb"
        self.net = self.dir / "b.net"

    def run(self, net_text, *args):
        self.net.write_text(net_text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = S.main([str(self.board), "--netlist", str(self.net), *args])
        return code, out.getvalue()

    def fp(self, ref):
        root = S.parse(self.board.read_text())
        return next(f for f in S.children(root, "footprint") if S._ref(f) == ref)


TWO = netlist([comp("R1", "10k", "lib:R_0402"), comp("R2", "1k", "lib:R_0402")],
              {"VIN": [("R1", "1")], "MID": [("R1", "2"), ("R2", "1")], "GND": [("R2", "2")]})


class Sync(unittest.TestCase):
    def test_new_board_then_nothing_to_do(self):
        p = Project()
        code, out = p.run(TWO)
        self.assertEqual(code, 0, out)
        self.assertIn("added (2): R1, R2", out)
        r1 = p.fp("R1")
        self.assertEqual(S.val(r1, "path"), "/R1-uuid")
        nets = {S.uq(pad[1]): S.val(pad, "net") for pad in S.children(r1, "pad")}
        self.assertEqual(nets, {"1": "VIN", "2": "MID"})
        self.assertIn('(property "LCSC" "C1"', p.board.read_text())
        before = p.board.read_bytes()
        self.assertEqual(p.run(TWO, "--check")[0], 0)
        self.assertEqual(p.board.read_bytes(), before)

    def test_change_rewrites_only_that_footprint(self):
        p = Project()
        p.run(TWO)
        r2_before = S.dump(p.fp("R2"))
        changed = TWO.replace('(value "10k")', '(value "22k")').replace('(name "VIN")', '(name "VBAT")')
        self.assertEqual(p.run(changed, "--check")[0], 1)
        code, out = p.run(changed)
        self.assertIn("updated (1): R1", out)
        self.assertIn('(property "Value" "22k"', p.board.read_text())
        self.assertEqual(S.dump(p.fp("R2")), r2_before)

    def test_removed_symbol_and_board_only_footprint(self):
        p = Project()
        p.run(TWO)
        text = p.board.read_text()
        logo = '\t(footprint "lib:Logo"\n\t\t(layer "F.Cu")\n\t\t(uuid "logo")\n\t\t(at 5 5)\n' \
               '\t\t(property "Reference" "G1"\n\t\t\t(at 0 0 0)\n\t\t)\n\t)\n'
        p.board.write_text(text[:text.rindex(")")] + logo + ")\n")
        one = netlist([comp("R1", "10k", "lib:R_0402")], {"VIN": [("R1", "1")], "MID": [("R1", "2")]})
        code, out = p.run(one)
        self.assertIn("removed (1): R2", out)
        self.assertIn("kept board only (1): G1", out)
        self.assertNotIn('"R2"', p.board.read_text())

    def test_replaced_footprint_keeps_place_rotation_and_lock(self):
        p = Project()
        p.run(TWO)
        text = p.board.read_text()
        i = text.index('(property "Reference" "R1"')
        head = text.rindex("(footprint", 0, i)
        at = text.index("(at ", head)
        text = text[:head] + text[head:at].replace('(layer "F.Cu")', '(locked yes)\n\t\t(layer "F.Cu")') + \
            "(at 10 20 90)" + text[text.index(")", at) + 1:]
        p.board.write_text(text)
        code, out = p.run(TWO.replace('(footprint "lib:R_0402") (fields (field (name "LCSC") "C1")',
                                      '(footprint "lib:R_0603") (fields (field (name "LCSC") "C1")'))
        self.assertIn("replaced (1): R1", out)
        r1 = p.fp("R1")
        self.assertEqual(S.uq(r1[1]), "lib:R_0603")
        self.assertEqual(S.child(r1, "at")[1:], ["10", "20", "90"])
        self.assertIsNotNone(S.child(r1, "locked"))
        self.assertEqual(S.child(S.children(r1, "pad")[0], "at")[1:], ["-0.5", "0", "90"])
        pts = [xy[1:] for xy in S.children(S.child(S.child(S.child(r1, "zone"), "polygon"), "pts"), "xy")]
        self.assertEqual(pts, [["10", "19"], ["10", "18"], ["11", "18"]])
        self.assertEqual(S.val(S.children(r1, "pad")[1], "net"), "MID")

    def test_missing_footprint_fails(self):
        p = Project()
        code, out = p.run(netlist([comp("U1", "X", "lib:Nope")], {}))
        self.assertEqual(code, 1)
        self.assertIn("footprint not found: U1: lib:Nope", out)

    def test_dnp_and_bom(self):
        p = Project()
        p.run(netlist([comp("R1", "10k", "lib:R_0402", extra=' (property (name "dnp")) (property (name "exclude_from_bom"))')],
                      {}))
        self.assertEqual(S.child(p.fp("R1"), "attr")[1:], ["smd", "exclude_from_pos_files", "exclude_from_bom", "dnp"])


if __name__ == "__main__":
    unittest.main()
