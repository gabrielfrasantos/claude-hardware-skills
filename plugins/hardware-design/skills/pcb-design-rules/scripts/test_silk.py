import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import silk as S  # noqa: E402

BOARD = """(kicad_pcb
\t(version 20241229)
\t(generator "pcbnew")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(2 "B.Cu" signal)
\t\t(5 "F.SilkS" user)
\t\t(25 "Edge.Cuts" user)
\t\t(39 "User.1" user)
\t\t(41 "Cmts.User" user)
\t)
\t(footprint "R_0402"
\t\t(layer "F.Cu")
\t\t(at 10 10 0)
\t\t(property "Reference" "R1"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.SilkS")
\t\t\t(effects (font (size 0.5 0.5) (thickness 0.08)))
\t\t)
\t\t(property "Value" "10k"
\t\t\t(at 0 1 0)
\t\t\t(layer "F.SilkS")
\t\t\t(effects (font (size 1 1) (thickness 0.15)))
\t\t)
\t\t(fp_text user "${REFERENCE}"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.Fab")
\t\t\t(effects (font (size 0.5 0.5) (thickness 0.08)))
\t\t)
\t\t(fp_line (start -1.2 -0.6) (end 1.2 -0.6) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
\t\t(pad "1" smd rect (at -0.5 0) (size 0.6 0.6) (layers "F.Cu"))
\t\t(pad "2" smd rect (at 0.5 0) (size 0.6 0.6) (layers "F.Cu"))
\t)
\t(footprint "R_0402"
\t\t(layer "F.Cu")
\t\t(at 13 10 90)
\t\t(property "Reference" "R2"
\t\t\t(at 0 0 90)
\t\t\t(layer "F.SilkS")
\t\t\t(effects (font (size 1 1) (thickness 0.15)))
\t\t)
\t\t(pad "1" smd rect (at -0.5 0 90) (size 0.6 0.6) (layers "F.Cu"))
\t\t(pad "2" smd rect (at 0.5 0 90) (size 0.6 0.6) (layers "F.Cu"))
\t)
\t(gr_rect (start 0 0) (end 30 20) (layer "Edge.Cuts"))
)
"""


class Silk(unittest.TestCase):
    def test_text_box_contains_kicads_text(self):
        measured = [                                            # pcbnew 10.0.8 GetEffectiveTextShape().BBox()
            ("C408", 1, 0.15, 0, (-1.813, -0.668, 1.813, 0.530)),
            ("SW701", 1, 0.15, 90, (-0.620, -2.361, 0.530, 2.361)),
            ("FID702", 0.8, 0.12, 0, (-1.946, -0.496, 1.984, 0.424)),
            ("Q304", 1, 0.15, 270, (-0.625, -1.837, 0.668, 1.885)),
        ]
        for s, size, thick, ang, k in measured:
            o = S.text_box(0, 0, s, size, thick, ang)
            slack = (k[0] - o[0], k[1] - o[1], o[2] - k[2], o[3] - k[3])
            self.assertTrue(all(0 <= d <= 0.03 for d in slack), (s, ang, slack))

    def test_check_finds_the_problems(self):
        rows = S.check(BOARD, 1.0, 0.15, 0.15)
        self.assertIn("R1: '10k'", rows["other_silk_text"])
        self.assertTrue(any(r.startswith("R1 ") for r in rows["refs_small"]))
        self.assertIn("R1", rows["refs_on_pads"])
        self.assertIn("R2", rows["refs_on_pads"])

    def test_apply_leaves_only_clear_references(self):
        text, pos, failed, removed = S.apply(BOARD, 1.0, 0.15, 0.15)
        self.assertEqual(failed, [])
        self.assertEqual(sorted(pos), ["R1", "R2"])
        self.assertEqual(removed, ["User.1", "Cmts.User"])
        rows = S.check(text, 1.0, 0.15, 0.15)
        self.assertEqual({k: v for k, v in rows.items() if v}, {})
        self.assertIn('(property "Value" "10k"', text)
        value = text[text.index('(property "Value" "10k"'):]
        self.assertIn("(hide yes)", value[:value.index("\n\t\t)")])
        fab = text[text.index('(fp_text user "${REFERENCE}"'):]
        self.assertIn("(hide yes)", fab[:fab.index("\n\t\t)")])
        self.assertIn("(size 1 1)", text[text.index('(property "Reference" "R1"'):text.index('(property "Value"')])

    def test_apply_is_stable(self):
        once = S.apply(BOARD, 1.0, 0.15, 0.15)[0]
        twice = S.apply(once, 1.0, 0.15, 0.15)[0]
        self.assertEqual(S.check(twice, 1.0, 0.15, 0.15), S.check(once, 1.0, 0.15, 0.15))


if __name__ == "__main__":
    unittest.main()
