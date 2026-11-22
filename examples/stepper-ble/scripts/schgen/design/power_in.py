"""Sheet 1: power input. Connector, fuse, reverse-polarity N-FET in the return, surge clamp (power-circuit-design §2-§5)."""
from sch import Sheet
from parts import part


def build(project, values):
    sh = Sheet(project, 1, "power_in", "Power input", paper="A4")
    sh.desc = ["J101 24 V input, F101 3 A fuse", "Q101 reverse-polarity N-FET (return)", "D101 SMAJ33A clamp -> VM"]
    sh.box(15.24, 20.32, 165.1, 132.08, "Input: connector -> fuse -> reverse blocking -> clamp (power-circuit-design §2)")

    j = part(sh, "J_IN", "J101", (27.94, 60.96), mirror="y")
    f = part(sh, "FUSE", "F101", (50.8, 60.96), rot=90)
    sh.link(j["1"], f["1"], "VIN_RAW")

    r = part(sh, "R100k", "R101", (71.12, 76.2))
    d_tvs = part(sh, "SMAJ33A", "D101", (101.6, 71.12), rot=270)
    flag = sh.flag("VM", (116.84, 60.96), label=False)
    r_top = part(sh, "R100k", "R102", (132.08, 68.58))
    r_bot = part(sh, "R10k", "R103", (132.08, 83.82))
    sh.rail("VM", 60.96, [f["2"], r["1"], d_tvs["1"], flag["1"], r_top["1"]], label="right", ext=7.62)
    sh.path("VM_SENSE", [r_top["2"], r_bot["1"]])
    sh.path("VM_SENSE", [(132.08, 76.2), (137.16, 76.2)])
    sh.label("VM_SENSE", (137.16, 76.2), (1, 0))
    sh.net(r_bot["2"], "GND")
    sh.net(d_tvs["2"], "GND")

    q = part(sh, "FET", "Q101", (71.12, 104.14), rot=270, mirror="y")
    sh.path("VIN_N", [j["2"], (38.1, 63.5), (38.1, 106.68), q["5"]])
    z = part(sh, "BZT52C15", "D102", (86.36, 99.06), rot=270)
    sh.link(r["2"], q["4"], "RP_GATE")
    sh.path("RP_GATE", [z["1"], (86.36, 91.44), (71.12, 91.44)])
    sh.path("GND", [q["1"], (86.36, 106.68)])
    sh.path("GND", [z["2"], (86.36, 114.3)])
    sh.label("GND", (86.36, 114.3), (0, 1))
    g = sh.flag("GND", (96.52, 106.68), label=False)
    sh.path("GND", [(86.36, 106.68), g["1"]])

    sh.note(22.86, 137.16, [
        "Order per power-circuit-design §2: connector -> fuse -> reverse-polarity element -> clamp and bulk -> loads.",
        "F101 0451003.MRL: 3 A fast, 125 V; breaking capacity per Littelfuse 451 datasheet; HW-PWR-002.",
        "Q101 CSD18543Q3A in the return (low-side N-FET, SLVA139 option 3, D-003): VDS 60 V, RDS(on) 8.1 mOhm at 10 V",
        "  (SLPS532 Table). Body diode conducts first, then R101 lifts the gate; D102 15 V Zener holds VGS <= 15 V",
        "  (abs max +-20 V) at 30 V in: (30-15)/100k = 0.15 mA. At 8 V in VGS = 8 V > 4.5 V RDS(on) point.",
        "  Reversed input: gate below source, Q101 off. Conducts both ways when on, so regeneration returns to the source.",
        "D101 SMAJ33A: VRWM 33 V >= 30 V max input; VC 53.3 V at IPP 7.5 A (Littelfuse SMAJ table, HW-PWR-003).",
        "  Ladder under VC: DRV8711 VM 60 V, CSD18543Q3A 60 V, LMR36510 VIN 70 V abs; 50 V capacitors are the weak",
        "  rung (C201, C301, C303-C305): accepted deviation D-004, checked by simulation S1 before release.",
        "VM_SENSE (R102/R103, placed at the ADC pin): 30 V reads 2.73 V; at the 53.3 V clamp 4.85 V through 100k is",
        "  12 uA into the pin, inside the -5/+5 mA injection limit (AN4899). 9.1 kOhm source: long ADC sample time.",
        "VM bulk (C301 100u) and HF bypass sit at the bridges, sheet 3 (power-pcb-layout §3.9).",
        "Caveat (D-003): board GND joins the USB host's ground; a reversed 24 V supply sharing that ground is not blocked.",
    ])

    for n, c in (("VIN_RAW", "PWR_3A"), ("VIN_N", "PWR_3A"), ("VM", "PWR_3A"), ("RP_GATE", "SIGNAL"), ("VM_SENSE", "ANALOG"),
                 ("GND", "GND")):
        sh.netclass(n, c)
    sh.class_table(205.74, 20.32)
