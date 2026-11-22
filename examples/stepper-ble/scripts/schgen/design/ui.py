"""Sheet 7: user interface, debug and mechanical parts (mcu-circuit-design §5, §11)."""
from sch import Sheet
from parts import part, special


def led(sh, r_ref, d_ref, key, net, x):
    r = part(sh, "R1k", r_ref, (x, 58.42))
    d = part(sh, key, d_ref, (x, 72.39), rot=90)
    sh.net(r["1"], "+3V3")
    sh.link(r["2"], d["2"], net + "_A")
    sh.net(d["1"], net)
    sh.label(net + "_A", (x, 64.77), (1, 0))


def build(project, values):
    sh = Sheet(project, 7, "ui", "User interface and debug", paper="A4")
    sh.desc = ["D701 status (green), D702 fault (red)", "SW701 user button", "J701 Tag-Connect TC2030 SWD",
               "H701-H704 M3 holes, FID701-FID703"]
    sh.box(15.24, 40.64, 129.54, 96.52, "LEDs (active low) and user button")
    led(sh, "R701", "D701", "LEDG", "LED_STATUS", 33.02)
    led(sh, "R702", "D702", "LEDR", "LED_FAULT", 63.5)
    r = part(sh, "R10k", "R703", (99.06, 58.42))
    sw = part(sh, "BUTTON", "SW701", (99.06, 76.2), rot=270)
    sh.net(r["1"], "+3V3")
    sh.path("BTN_USER", [r["2"], sw["1"]])
    sh.label("BTN_USER", (99.06, 66.04), (1, 0))
    sh.net(sw["2"], "GND")

    sh.box(134.62, 40.64, 210.82, 96.52, "SWD on Tag-Connect TC2030-NL (no part)")
    j = special(sh, "Connector:Conn_ARM_SWD_TagConnect_TC2030-NL", "J701", "TC2030-NL", (160.02, 68.58),
                "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical")
    j.fpos = (-10.16, -2.54, "right")
    sh.nets(j, {"1": "+3V3", "5": "GND", "2": "SWDIO", "3": "NRST", "4": "SWCLK", "6": "SWO"})

    sh.box(215.9, 40.64, 281.94, 96.52, "Mechanical")
    for i, x in enumerate((228.6, 243.84, 259.08, 274.32)):
        special(sh, "Mechanical:MountingHole", f"H70{i + 1}", "M3", (x, 58.42), "MountingHole:MountingHole_3.2mm_M3")
    for i, x in enumerate((228.6, 243.84, 259.08)):
        special(sh, "Mechanical:Fiducial", f"FID70{i + 1}", "Fiducial", (x, 81.28), "Fiducial:Fiducial_1mm_Mask2mm")

    sh.note(20.32, 104.14, [
        "D701/D702 KT-0603G/R from +3V3 through 1k, sunk by the MCU (GPIO low = on): green VF 2.6-3.1 V at 5 mA,",
        "  so ~0.5 mA (dim, visible indoors; HW-UI-001, B8); red ~1.3 mA. Pins sink well under 20 mA.",
        "SW701 to GND with R703 10k pull-up; firmware debounces. No series R / RC on the button: the parts list has",
        "  none and the button is on the board, not on a cable (deviation from mcu-circuit-design §11, D-023).",
        "J701 Tag-Connect TC2030-NL footprint (no part fitted): VTref +3V3, SWDIO PA13, SWCLK PA14, SWO PB3, nRESET.",
        "  STM32 has internal pulls on SWDIO/SWCLK (mcu-circuit-design §5). TC2030 pin 3 drives NRST (open drain).",
        "H701-H704 M3 NPTH at the corners; FID701-FID703 1 mm pad / 2 mm mask fiducials for JLCPCB assembly.",
    ])
    for n, c in (("LED_STATUS", "SIGNAL"), ("LED_FAULT", "SIGNAL"), ("LED_STATUS_A", "SIGNAL"),
                 ("LED_FAULT_A", "SIGNAL"), ("BTN_USER", "SIGNAL"), ("SWDIO", "SIGNAL"), ("SWCLK", "SIGNAL"),
                 ("SWO", "SIGNAL"), ("+3V3", "PWR_0p5A"), ("GND", "GND")):
        sh.netclass(n, c)
    sh.class_table(20.32, 127.0, rows=5)
