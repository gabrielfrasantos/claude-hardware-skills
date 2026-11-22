#!/usr/bin/env python3
"""Self-test for review_defects.py on design-review's synthetic board. Run: python3 evals/test_review_defects.py"""
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "plugins" / "hardware-design" / "skills" / "design-review" / "scripts"))
import review_defects as RD  # noqa: E402
import test_review as TR  # noqa: E402


class Seeded(unittest.TestCase):
    def test_seed_run_and_score(self):
        board = TR.board(TR.CLEAN + [TR.two("C4", "Capacitor_SMD:C_0402", "100nF 16V", 34, 22, "+3V3", "GND")])
        out = tempfile.mkdtemp()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(RD.main(["run", board, "--out", out]), 0)
        m = json.load(open(os.path.join(out, "manifest.json")))
        kinds = {x["kind"] for x in m["defects"]}
        self.assertTrue({"decap_removed", "pullup_removed", "tvs_underrated", "cap_underrated",
                         "divider_overrange"} <= kinds, kinds)                  # one IC: it carries decap_removed
        self.assertIn("boot_floating", m["not_seeded"])                          # each defect on a different part
        res = json.load(open(os.path.join(out, "result.json")))["score"]
        self.assertEqual(res["found"], res["seeded"])
        # a markdown review that names two of the parts, one of them marked false positive
        first, second = m["defects"][0], m["defects"][1]
        md = (f"| 1 | MAJOR | {first['expect']} | {first['ref']} | missing |\n"
              f"| 2 | MINOR | {second['expect']} | {second['ref']} | FALSE-POSITIVE: fine |\n")
        r = RD.score(m, report=md)
        self.assertEqual([x["found"] for x in r["rows"][:2]], [True, False])
        self.assertEqual(r["found"], 1)
        # naming the part is not enough: the report must say what is wrong with it
        r = RD.score(m, report=f"| 1 | MAJOR | assembly | {first['ref']} | pin-1 mark hard to see |\n")
        self.assertEqual(r["found"], 0)

    def _manifest(self):
        return dict(seeded="b.kicad_pcb", not_seeded=["boot_floating"],
                    defects=[dict(id="S1", kind="decap_removed", ref="U202", pin="", net="+5V", expect="decoupling",
                                  what="")])

    def test_finding_must_have_the_expected_check(self):
        wrong = [dict(severity="MINOR", check="orientation_mixed", anchor="U202", message="U202 rotated 90°")]
        self.assertEqual(RD.score(self._manifest(), findings=wrong)["found"], 0)
        right = [dict(severity="MAJOR", check="decoupling", anchor="U202", message="no capacitor on +5V near U202")]
        self.assertEqual(RD.score(self._manifest(), findings=right)["found"], 1)
        by_net = [dict(severity="MAJOR", check="decoupling", anchor="+5V", message="+5V has no decoupling")]
        self.assertEqual(RD.score(self._manifest(), findings=by_net)["found"], 1)

    def test_a_finding_already_on_the_clean_board_earns_nothing(self):
        old = dict(severity="MAJOR", check="decoupling", anchor="U202", message="U202 +5V: 1 capacitor, 2 wanted")
        new = dict(severity="MINOR", check="dividers", anchor="R9", message="R9/R10 out of range")
        r = RD.score(self._manifest(), findings=[old, new], baseline=[old])
        self.assertEqual(r["found"], 0)
        self.assertEqual([x["check"] for x in r["unexpected"]], ["dividers"])   # new, and matches no defect
        text = RD.table(r, "t", self._manifest())
        self.assertIn("1 of 8 kinds", text)
        self.assertIn("boot_floating", text)
        self.assertIn("Unexpected", text)


if __name__ == "__main__":
    unittest.main()
