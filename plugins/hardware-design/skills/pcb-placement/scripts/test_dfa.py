#!/usr/bin/env python3
"""Self-test for dfa.py (assembly checks). Run: python3 test_dfa.py (no KiCad needed)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dfa  # noqa: E402

HEAD = '(kicad_pcb\n\t(version 20260206)\n\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t)\n'
EDGE = '\t(gr_rect\n\t\t(start 0 0)\n\t\t(end 40 30)\n\t\t(layer "Edge.Cuts")\n\t)\n'


def fp(ref, lib, x, y, pads, rot=0, side="F", locked=False):
    """pads: [(number, dx, dy, w, h, net)]"""
    lk = "\t\t(locked yes)\n" if locked else ""
    ps = "".join(f'\t\t(pad "{n}" smd rect\n\t\t\t(at {dx} {dy}{f" {rot}" if rot else ""})\n\t\t\t(size {w} {h})\n'
                 f'\t\t\t(layers "{side}.Cu")\n\t\t\t(net "{net}")\n\t\t)\n' for n, dx, dy, w, h, net in pads)
    return (f'\t(footprint "{lib}"\n{lk}\t\t(layer "{side}.Cu")\n\t\t(at {x} {y}{f" {rot}" if rot else ""})\n'
            f'\t\t(property "Reference" "{ref}"\n\t\t)\n{ps}\t)\n')


def chip(ref, size, x, y, nets=("A", "B"), **kw):
    return fp(ref, f"Capacitor_SMD:C_{size}_Metric", x, y,
              [("1", -0.5, 0, 0.5, 0.5, nets[0]), ("2", 0.5, 0, 0.5, 0.5, nets[1])], **kw)


def qfn(ref, x, y, nets=("VDD", "IO"), **kw):
    pads = [(str(i + 1), -1.5, -0.75 + 0.5 * i, 0.6, 0.25, nets[i % 2]) for i in range(4)]
    return fp(ref, "Package_DFN_QFN:QFN-16_3x3mm_P0.5mm", x, y, pads, **kw)


def fiducial(ref, x, y):
    return fp(ref, "Fiducial:Fiducial_1mm_Mask2mm", x, y, [("", 0, 0, 1, 1, "")])


def board(*items):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "b.kicad_pcb")
    with open(path, "w") as f:
        f.write(HEAD + EDGE + "".join(items) + ")\n")
    return path


class Classes(unittest.TestCase):
    def test_package_classes(self):
        cases = {"Capacitor_SMD:C_0603_1608Metric": "0603", "Resistor_SMD:R_2512_6332Metric": "1206",
                 "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm": "SOP", "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm": "SOP",
                 "Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm": "QFN", "Package_QFP:LQFP-64_10x10mm_P0.5mm": "QFP",
                 "Package_TO_SOT_SMD:SOT-23": "SOT", "Package_BGA:BGA-64_9x9mm": "BGA",
                 "Connector_JST:JST_PH_B2B": None, "Fiducial:Fiducial_1mm_Mask2mm": None}
        for lib, cls in cases.items():
            self.assertEqual(dfa.package_class(lib, 2 if cls in dfa.CHIPS or cls == "1206" else 8), cls, lib)


class Checks(unittest.TestCase):
    def test_spacing_by_package_pair(self):
        # 0402 pair: pads 0.10 mm apart (< 0.15) -> violation; 0.20 mm apart -> fine
        close = board(chip("C1", "0402", 10, 10), chip("C2", "0402", 10, 10.6), fiducial("FID1", 5, 5),
                      fiducial("FID2", 35, 5), fiducial("FID3", 35, 25))
        m, d, _ = dfa.check(close)
        self.assertEqual(m["assembly_spacing"], 1)
        far = board(chip("C1", "0402", 10, 10), chip("C2", "0402", 10, 10.7))
        self.assertEqual(dfa.check(far)[0]["assembly_spacing"], 0)

    def test_decoupling_next_to_its_ic_is_an_exception(self):
        b = board(qfn("U1", 20, 15), chip("C1", "0402", 17.6, 15, nets=("VDD", "GND")),     # its decoupling cap
                  chip("R1", "0402", 20, 16.6, nets=("X", "Y")))                             # an unrelated chip
        m, d, _ = dfa.check(b)
        self.assertEqual([r[:2] for r in d["decoupling_exceptions"]], [("U1", "C1")])
        self.assertEqual(m["assembly_spacing"], 1)                       # R1 is 0.6 mm from a QFN (< 1.0)

    def test_locked_pairs_are_the_owners(self):
        b = board(chip("C1", "0402", 10, 10, locked=True), chip("C2", "0402", 10, 10.6, locked=True))
        self.assertEqual(dfa.check(b)[0]["assembly_spacing"], 0)

    def test_edge_keepout_and_fiducials(self):
        b = board(chip("C1", "0603", 1.5, 15), chip("R1", "0603", 20, 1.5).replace("Capacitor_SMD:C_", "Resistor_SMD:R_"),
                  fiducial("FID1", 2, 2))
        m, d, _ = dfa.check(b)
        self.assertEqual([r for r, _ in d["edge_keepout"]], ["C1"])     # an MLCC 0.75 mm from the edge; R1 is not brittle
        self.assertEqual(m["fiducials_missing"], 1)
        self.assertEqual(d["fiducials"]["F"]["too_close"], ["FID1"])

    def test_orientation(self):
        b = board(*[fp(f"D{i}", "Diode_SMD:D_SOD-123", 5 + 5 * i, 10, [("1", -1, 0, 0.6, 0.6, "A"), ("2", 1, 0, 0.6, 0.6, "B")],
                       rot=r) for i, r in enumerate((0, 0, 0, 90, 90, 180))])
        m, d, _ = dfa.check(b)
        self.assertEqual([x[0] for x in d["orientation_mixed"]], ["D5"])   # two orientations allowed for polarized


if __name__ == "__main__":
    unittest.main()
