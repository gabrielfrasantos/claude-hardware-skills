#!/usr/bin/env python3
"""Self-test for validate_kicad.py with a stand-in kicad-cli (the real run needs KiCad 10). Run: python3 evals/test_validate_kicad.py"""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "plugins" / "hardware-design" / "skills" / "design-review" / "scripts"))
import test_review as TR  # noqa: E402
import validate_kicad as VK  # noqa: E402

FAKE = """#!/bin/sh
if [ "$1" = version ]; then echo 10.0.8; exit 0; fi
out=""; prev=""
for a in "$@"; do if [ "$prev" = "-o" ]; then out="$a"; fi; prev="$a"; done
case "$1 $2" in
  "pcb drc") echo '{"violations": []}' > "$out";;
  "sch erc") echo '{"sheets": [{"violations": []}]}' > "$out";;
esac
exit 0
"""


class Kit(unittest.TestCase):
    def test_steps_report_and_failure_path(self):
        d = pathlib.Path(tempfile.mkdtemp())
        hw = d / "repo" / "hardware" / "demo"
        hw.mkdir(parents=True)
        (hw / "demo.kicad_pcb").write_text(open(TR.board(TR.CLEAN)).read())
        (hw / "demo.kicad_pro").write_text("{}")
        (hw / "demo.kicad_sch").write_text('(kicad_sch (version 20250114) (generator "eeschema"))\n')
        cli = d / "kicad-cli"
        cli.write_text(FAKE)
        cli.chmod(0o755)
        out = d / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = VK.main([str(d / "repo"), "--kicad-cli", str(cli), "--out", str(out), "--steps", "B0,B1,B5,B6"])
        rows = {r["step"]: r for r in json.loads((out / "validation.json").read_text())["rows"]}
        self.assertEqual(rows["B0"]["status"], "PASS")
        self.assertEqual(rows["B1"]["status"], "FAIL")              # a stand-in can't fire the rules canary
        self.assertIn("rules NOT confirmed", rows["B1"]["evidence"])
        self.assertEqual(rows["B5"]["status"], "PASS")
        self.assertEqual(rows["B6"]["status"], "PASS", rows["B6"]["evidence"])
        self.assertIn("byte-identical", rows["B6"]["evidence"])
        self.assertEqual(code, 1)
        md = (out / "validation.md").read_text()
        self.assertIn("MANUAL", md)
        self.assertTrue((d / "repo" / "hardware" / "demo" / "demo.kicad_pcb").read_text().count("(enabled yes)") == 0)


if __name__ == "__main__":
    unittest.main()
