#!/usr/bin/env python3
"""Self-test for pins.py. Run: python3 test_pins.py (no KiCad needed)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pins as P  # noqa: E402

HEAD = '(kicad_pcb\n\t(version 20260206)\n\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t)\n'
# U1 at (50, 50): pads 1-2 on the west side, 3-4 south, 5-6 east, 7-8 north
PADS = {"1": (-3, -1), "2": (-3, 1), "3": (-1, 3), "4": (1, 3), "5": (3, 1), "6": (3, -1), "7": (1, -3), "8": (-1, -3)}
PIN_DATA = """number,name,alternates
1,PA1,SPI1_SCK USART1_TX
2,PA2,SPI1_MOSI USART1_RX
3,PB3,SPI2_SCK TIM2_CH1
4,PB4,SPI2_MOSI TIM2_CH2
5,PC5,SPI1_SCK LPTIM1_IN1
6,PC6,SPI1_MOSI LPTIM1_IN2
7,PD7,USART1_TX ADC1_IN7
8,VDD,
"""


def mcu(nets):
    pads = "".join(f'\t\t(pad "{n}" smd rect\n\t\t\t(at {x} {y})\n\t\t\t(size 0.3 0.3)\n\t\t\t(layers "F.Cu")\n'
                   + (f'\t\t\t(net "{nets[n]}")\n' if n in nets else "") + "\t\t)\n" for n, (x, y) in PADS.items())
    return f'\t(footprint "QFN"\n\t\t(layer "F.Cu")\n\t\t(uuid "u-U1")\n\t\t(at 50 50)\n\t\t(property "Reference" "U1"\n\t\t)\n{pads}\t)\n'


def part(ref, x, y, net):
    return (f'\t(footprint "R"\n\t\t(layer "F.Cu")\n\t\t(uuid "u-{ref}")\n\t\t(at {x} {y})\n\t\t(property "Reference" "{ref}"\n\t\t)\n'
            f'\t\t(pad "1" smd rect\n\t\t\t(at 0 0)\n\t\t\t(size 0.5 0.5)\n\t\t\t(layers "F.Cu")\n\t\t\t(net "{net}")\n\t\t)\n\t)\n')


class Pins(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.csv = os.path.join(self.dir, "pins.csv")
        with open(self.csv, "w") as f:
            f.write(PIN_DATA)
        self.needs = os.path.join(self.dir, "needs.txt")

    def board(self, nets=None, *parts):
        path = os.path.join(self.dir, "b.kicad_pcb")
        with open(path, "w") as f:
            f.write(HEAD + mcu(nets or {"8": "VDD"}) + "".join(parts) + ")\n")
        return path

    def run_cmd(self, cmd, board, needs):
        with open(self.needs, "w") as f:
            f.write(needs)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = P.main([cmd, board, "--mcu", "U1", "--needs", self.needs, "--pin-data", self.csv,
                           *(["--out", os.path.join(self.dir, "map.txt")] if cmd == "assign" else [])])
        return code, out.getvalue()

    def assigned(self):
        rows = {}
        with open(os.path.join(self.dir, "map.txt")) as f:
            for line in f:
                if not line.startswith("#"):
                    fn, pin, pad, sig = line.split()[:4]
                    rows[fn] = (pin, sig)
        return rows

    def test_bus_goes_to_the_side_facing_its_parts(self):
        # the SPI device sits east of the MCU: SPI1 on PC5/PC6 (east), not SPI1 on PA1/PA2 (west) or SPI2 (south)
        b = self.board(None, part("U2", 70, 50, "SCK"), part("U3", 70, 49, "MOSI"))
        code, out = self.run_cmd("assign", b, "SCK SPI{n}_SCK bus\nMOSI SPI{n}_MOSI bus\n")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.assigned(), {"SCK": ("PC5", "SPI1_SCK"), "MOSI": ("PC6", "SPI1_MOSI")})
        b = self.board(None, part("U2", 50, 70, "SCK"), part("U3", 51, 70, "MOSI"))      # now south
        self.run_cmd("assign", b, "SCK SPI{n}_SCK bus\nMOSI SPI{n}_MOSI bus\n")
        self.assertEqual({k: v[1] for k, v in self.assigned().items()}, {"SCK": "SPI2_SCK", "MOSI": "SPI2_MOSI"})

    def test_aligned_alternatives_never_mix(self):
        # A could be TIM2_CH1 (south) and B LPTIM1_IN2 (east) if alternatives mixed; aligned, they cannot
        b = self.board(None, part("E1", 50, 70, "A"), part("E2", 70, 50, "B"))
        self.run_cmd("assign", b, "A TIM{t}_CH1|LPTIM{t}_IN1 enc\nB TIM{t}_CH2|LPTIM{t}_IN2 enc\n")
        sigs = {v[1] for v in self.assigned().values()}
        self.assertIn(sigs, ({"TIM2_CH1", "TIM2_CH2"}, {"LPTIM1_IN1", "LPTIM1_IN2"}))

    def test_one_signal_one_pin_and_exti_lines(self):
        # USART1_TX exists on PA1 and PD7: two functions cannot both take it
        b = self.board(None, part("X", 50, 30, "T1"), part("Y", 50, 31, "T2"))
        code, out = self.run_cmd("assign", b, "T1 USART1_TX\nT2 USART1_TX\n")
        self.assertEqual(code, 1, out)
        self.assertIn("Candidates per function", out)
        # EXTI: each function gets its own line (the pin number), so two functions never share one
        code, _ = self.run_cmd("assign", b, "T1 EXTI\nT2 EXTI\n")
        self.assertEqual(code, 0)
        lines = [v[1] for v in self.assigned().values()]
        self.assertEqual(len(set(lines)), 2)

    def test_power_pins_and_other_nets_are_never_used(self):
        b = self.board({"8": "VDD", "7": "OSC_IN"}, part("X", 50, 30, "G"))
        self.run_cmd("assign", b, "G GPIO\n")
        self.assertNotIn(self.assigned()["G"][0], ("VDD", "PD7"))

    def test_check(self):
        b = self.board({"5": "SCK", "6": "MOSI", "8": "VDD"}, part("U2", 70, 50, "SCK"), part("U3", 70, 49, "MOSI"))
        self.assertEqual(self.run_cmd("check", b, "SCK SPI{n}_SCK bus\nMOSI SPI{n}_MOSI bus\n")[0], 0)
        b = self.board({"5": "SCK", "4": "MOSI", "8": "VDD"})                            # SPI1 SCK with SPI2 MOSI
        code, out = self.run_cmd("check", b, "SCK SPI{n}_SCK bus\nMOSI SPI{n}_MOSI bus\n")
        self.assertEqual(code, 1)
        self.assertIn("breaks group", out)

    def test_boot_and_swd_pins_are_reserved(self):
        with open(self.csv, "w") as f:
            f.write(PIN_DATA.replace("1,PA1,SPI1_SCK USART1_TX", "1,PA1,SPI1_SCK USART1_TX SYS_JTMS-SWDIO")
                            .replace("7,PD7,USART1_TX ADC1_IN7", "7,PH3-BOOT0,GPIO"))
        b = self.board(None, part("R1", 40, 49, "LED"))
        code, out = self.run_cmd("assign", b, "LED GPIO\n")
        self.assertEqual(code, 0, out)
        self.assertNotIn(self.assigned()["LED"][0], ("PA1", "PH3-BOOT0"))   # PA1 is nearest, but carries SWDIO
        code, out = self.run_cmd("assign", b, "LED PA1\n")                   # named exactly: allowed
        self.assertEqual((code, self.assigned()["LED"][0]), (0, "PA1"), out)

    def test_net_on_two_pins(self):
        b = self.board({"1": "IRQ", "3": "IRQ", "8": "VDD"})
        code, out = self.run_cmd("check", b, "IRQ GPIO\nIRQ~2 GPIO\n")
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
