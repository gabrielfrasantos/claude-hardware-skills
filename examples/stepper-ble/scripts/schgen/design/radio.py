"""Sheet 5: radio. MLPF-WB55-01E3 IPD at RF1, pi tuning network, TI SWRA117D PCB inverted-F antenna (rf-layout)."""
from sch import Sheet
from parts import part, special


def build(project, values):
    sh = Sheet(project, 5, "radio", "Radio", paper="A4")
    sh.desc = ["FL501 MLPF-WB55-01E3 match + harmonic filter", "R501, C501/C502 (DNP) antenna tuning pi",
               "AE501 TI SWRA117D PCB inverted-F antenna"]
    sh.box(15.24, 33.02, 152.4, 96.52, "RF1 -> IPD -> 50 ohm line -> tuning pi -> antenna (rf-layout §3, §4)")
    fl = part(sh, "MLPF", "FL501", (71.12, 71.12))
    fl.fpos = (-10.16, 12.7, "right")
    sh.net(fl["A3"], "RF_IN")
    sh.rail("GND", 81.28, [fl["A2"], fl["B1"], fl["B2"], fl["B3"]], tap=(71.12, (0, 1)))
    c1 = part(sh, "CDNP", "C501", (88.9, 76.2))
    r = part(sh, "R0", "R501", (101.6, 71.12), rot=90)
    c2 = part(sh, "CDNP", "C502", (114.3, 76.2))
    sh.rail("RF_OUT", 71.12, [fl["A1"], c1["1"], r["1"]])
    sh.rail("ANT_FEED", 71.12, [r["2"], c2["1"], (121.92, 71.12)])
    ant = special(sh, "Device:Antenna_Shield", "AE501", "SWRA117D IFA", (127.0, 55.88),
                  "stepper-ble:Texas_SWRA117D_2.4GHz_Left_Drill0.2")
    sh.path("ANT_FEED", [(121.92, 71.12), (121.92, 63.5), (127.0, 63.5), ant["1"]])
    sh.net(ant["2"], "GND")
    sh.label("RF_OUT", (82.55, 71.12), (0, -1))
    sh.label("ANT_FEED", (119.38, 71.12), (0, -1))
    for c in (c1, c2):
        sh.net(c["2"], "GND")

    sh.note(20.32, 104.14, [
        "Chip-down radio (rf-layout §0): the match and harmonic filter are ST's IPD for this package (MLPF-WB55-01E3,",
        "  DS12804: 50 ohm out, IL 0.9 dB, 2fo 40 dB, 3fo 45 dB); its land per DS12804 Fig. 13 (project library, D-016).",
        "  IN (A3) goes straight to RF1 (pin 21) with the shortest possible track; each GND land gets its own via to L2.",
        "RF_OUT -> antenna: 50 ohm grounded coplanar line on F.Cu over solid In1.Cu ground, no vias, stubs or test",
        "  points (rf-layout §2); width/gap from JLCPCB's calculator for JLC04161H-7628 (open item OI-1).",
        "Tuning pi at the feed (rf-layout §3): R501 0 ohm series (fitted), C501/C502 0402 shunts DNP; fit at most two",
        "  parts after VNA tuning in the enclosure, target SWR <= 2 (NWP-017). C0G parts, 0402 as laid out.",
        "AE501: TI SWRA117D (AN043) meandered IFA, copper only, at the top board edge; keep-out on all layers, no",
        "  ground under it (rf-layout §4). AN043 was designed on a different stack-up: retune (D-007, B5).",
        "No conducted test port: the parts list has no RF connector (deviation from rf-layout §9, D-007).",
    ])
    for n, c in (("RF_IN", "RF_50"), ("RF_OUT", "RF_50"), ("ANT_FEED", "RF_50"), ("GND", "GND")):
        sh.netclass(n, c)
    sh.class_table(185.42, 33.02, rows=6)
