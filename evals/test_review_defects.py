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
        md = (f"| 1 | MAJOR | power | {first['ref']} | missing |\n"
              f"| 2 | MINOR | x | {second['ref']} | FALSE-POSITIVE: fine |\n")
        r = RD.score(m, report=md)
        self.assertEqual([x["found"] for x in r["rows"][:2]], [True, False])
        self.assertEqual(r["found"], 1)


if __name__ == "__main__":
    unittest.main()
