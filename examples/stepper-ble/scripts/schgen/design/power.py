"""Sheet 2: input protection, motor supply, 5 V buck, 3.3 V LDO."""
from sch import Sheet

from parts import classes, series, shunt


def g(n):
    return round(n * 2.54, 2)


def build(project, values):
    sh = Sheet(project, 2, "power", "Power")
    sh.desc = ["24 V input: fuse, reverse-polarity N-FET, TVS, bulk", "LMR36510 buck to 5 V, OR-ed with USB VBUS",
               "AP2112K LDO to 3.3 V", "VM sense divider for the ADC"]

    sh.box(g(6), g(6), g(78), g(44), "Input protection and motor supply (VM)")
    j = sh.part("Connector:Screw_Terminal_01x02", "J201", "24V IN", (g(13), g(19)), mirror="y",
                fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
                lcsc="C480516", mpn="1715721")
    f = series(sh, "F201", "3A fast", g(21), g(19))
    sh.link(j["1"], f["1"], "VIN_RAW")
    tvs = sh.part("Diode:SMAJ33A", "D201", "SMAJ33A", (g(27), g(19) + 3.81), rot=270,
                  fp="Diode_SMD:D_SMA", lcsc="C353454", mpn="SMAJ33A")
    sh.net(tvs["2"], "GND")
    bulk = shunt(sh, "C201", "100u 50V", g(34), g(19))
    c202 = shunt(sh, "C202", "4.7u 50V", g(41), g(19))
    r202 = shunt(sh, "R202", "100k", g(48), g(19), bottom=None)
    r203 = shunt(sh, "R203", "10k", g(48), g(23))
    c203 = shunt(sh, "C203", "100n", g(54), g(22))
    sh.rail("VM", g(19), [f["2"], tvs["1"], bulk["1"], c202["1"], r202["1"]], tap=(g(60), (0, -1)))
    sh.path("VM_SENSE", [r202["2"], r203["1"]])
    sh.rail("VM_SENSE", g(22), [(g(48), g(22)), c203["1"]], label="right")

    q = sh.part("Transistor_FET:CSD18543Q3A", "Q201", "CSD18543Q3A", (g(14), g(30)),
                fp="Package_SON:VSON-8_3.3x3.3mm_P0.65mm_NexFET", lcsc="C840100", mpn="CSD18543Q3A")
    sh.nets(q, {"1": "GND", "2": "GND", "3": "GND"})
    q.fpos = (5.08, -1.27, "left")
    sh.path("GND_IN", [j["2"], q["5"]])
    r201 = shunt(sh, "R201", "100k", g(9), g(24), bottom=None)
    sh.net(r201["1"], "VM")
    z = sh.part("Diode:BZT52Bxx", "D202", "BZT52C15", (g(9), g(31) + 3.81), rot=270,
                fp="Diode_SMD:D_SOD-123", lcsc="C173427", mpn="BZT52C15")
    sh.net(z["2"], "GND")
    sh.path("Q201_G", [r201["2"], (g(9), g(30)), z["1"]])
    sh.path("Q201_G", [(g(9), g(30)), q["4"]])
    sh.note(g(24), g(31), [
        "Input 24 V nominal, 30 V max (HW-PWR-001). Parts on VM rated >= 52 V:",
        "DRV8711 8-52 V (SLVSC40H 6.3), LMR36510 4.2-65 V (SNVSBD7B 1), CSD18543Q3A 60 V.",
        "F201 3 A fast sets VM's class PWR_3A.",
        "Q201 in the return leg: body diode first, then R201 enhances it; D202 clamps",
        "VGS to 15 V (max +-20 V). D201: VRWM 33 V over 30 V, VC 53.3 V under 60 V",
        "(ASSUMPTION: VC at 7.5 A). C201/C202: DRV8711 bulk (SLVSC40H 9.1).",
        "VM_SENSE = VM x 10k/110k: 30 V -> 2.73 V; fc 175 Hz (derived).",
    ])

    sh.box(g(80), g(6), g(160), g(44), "5 V buck (LMR36510, SNVSBD7B 8.2 Design 1)")
    u = sh.part("Regulator_Switching:LMR36510ADDA", "U201", "LMR36510ADDA", (g(106), g(22)),
                fp="Package_SO:Texas_HTSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.4x3.1mm_ThermalVias",
                lcsc="C1858393", mpn="LMR36510ADDAR")
    c206 = shunt(sh, "C206", "4.7u 50V", g(87), g(14))
    c207 = shunt(sh, "C207", "220n 50V", g(94), g(14))
    sh.rail("VM", g(14), [c206["1"], c207["1"], (g(99), g(14))], tap=(g(84), (0, -1)))
    sh.vrail("VM", g(99), [u["2"], u["3"], (g(99), g(14))])
    c204 = shunt(sh, "C204", "1u", g(96), g(24))
    sh.link(u["6"], c204["1"], "BUCK_VCC")
    sh.rail("GND", g(27), [u["1"], u["9"]], tap=(g(106), (0, 1)))
    c205 = shunt(sh, "C205", "100n", g(117), g(16), bottom=None)
    sh.path("BUCK_BOOT", [u["7"], (g(111), g(20)), (g(111), g(16)), c205["1"]])
    l201 = series(sh, "L201", "22u L", g(120), g(21))
    sh.rail("BUCK_SW", g(21), [u["8"], c205["2"], l201["1"]])
    r204 = shunt(sh, "R204", "100k", g(126), g(21), bottom=None)
    r205 = shunt(sh, "R205", "24.9k", g(126), g(25))
    sh.path("BUCK_FB", [r204["2"], r205["1"]])
    sh.path("BUCK_FB", [u["5"], (g(116), g(23)), (g(116), g(24)), (g(126), g(24))])
    c208 = shunt(sh, "C208", "22u", g(131), g(21))
    c209 = shunt(sh, "C209", "22u", g(137), g(21))
    d203 = sh.part("Diode:SS34", "D203", "SS34", (g(143) + 3.81, g(21)), rot=180, fp="Diode_SMD:D_SMA",
                   lcsc="C8678", mpn="SS34")
    sh.rail("+5V_BUCK", g(21), [l201["2"], r204["1"], c208["1"], c209["1"], d203["2"]])
    d204 = sh.part("Diode:SS34", "D204", "SS34", (g(143) + 3.81, g(26)), rot=180, fp="Diode_SMD:D_SMA",
                   lcsc="C8678", mpn="SS34")
    sh.net(d204["2"], "VBUS")
    sh.rail("+5V", g(21), [d203["1"], (g(151), g(21))], tap=(g(153), (0, -1)))
    sh.path("+5V", [d204["1"], (g(151), g(26)), (g(151), g(21))])
    r206 = shunt(sh, "R206", "100k", g(112), g(27), bottom=None)
    sh.net(r206["1"], "+3V3")
    sh.path("PG_5V", [u["4"], (g(110), g(24)), (g(110), g(30)), r206["2"]])
    sh.rail("PG_5V", g(30), [r206["2"], (g(116), g(30))], label="right")
    sh.note(g(118), g(34), [
        "Table 8-1, 400 kHz, 5 V: L 22 uH, COUT 2 x 22 uF,",
        "RFBT 100k / RFBB 24.9k: VOUT = 1.0 V x (1 + 100/24.9)",
        "= 5.02 V. CIN 2.2 uF + 220 nF (4.7 uF used, 50 V).",
        "EN tied to VIN; PG open drain, pulled to +3V3.",
        "D203/D204 OR the buck with USB VBUS (~0.4 V drop).",
        "ASSUMPTION: L201 Isat >= 1 A (SWPA4030S).",
    ])

    sh.box(g(6), g(46), g(78), g(70), "3.3 V LDO (AP2112K-3.3)")
    ldo = sh.part("Regulator_Linear:AP2112K-3.3", "U202", "AP2112K-3.3", (g(26), g(56)),
                  fp="Package_TO_SOT_SMD:SOT-23-5", lcsc="C51118", mpn="AP2112K-3.3TRG1")
    c210 = shunt(sh, "C210", "1u", g(18), g(55))
    sh.rail("+5V", g(55), [c210["1"], ldo["1"]], tap=(g(15), (0, -1)))
    sh.path("+5V", [ldo["3"], (g(22), g(56)), (g(22), g(55))])
    sh.nc(ldo["4"])
    sh.net(ldo["2"], "GND")
    c211 = shunt(sh, "C211", "1u", g(34), g(55))
    c212 = shunt(sh, "C212", "4.7u", g(39), g(55))
    sh.rail("+3V3", g(55), [ldo["5"], c211["1"], c212["1"]], tap=(g(43), (0, -1)))
    sh.note(g(46), g(52), [
        "AP2112K: 600 mA; 1 uF in and out (Diodes datasheet).",
        "+5V minus one Schottky >= 4.5 V: above 3.3 V + 400 mV",
        "dropout (ASSUMPTION: at 600 mA). Load < 100 mA.",
        "C212: the 4.7 uF bulk on VDD (DS11929 Fig. 16).",
    ])

    for i, net in enumerate(("VM", "GND", "+5V")):
        sh.flag(net, (g(140 + 6 * i), g(48)))
    sh.class_table(g(84), g(46), rows=10)
    classes(sh, {
        "VIN_RAW": "PWR_3A_30V", "VM": "PWR_3A_30V", "GND_IN": "GND_3A", "GND": "GND",
        "BUCK_SW": "PWR_1A_30V", "BUCK_BOOT": "SIGNAL_30V", "+5V_BUCK": "PWR_0p5A", "+5V": "PWR_0p5A",
        "VBUS": "PWR_0p5A", "+3V3": "PWR_0p5A", "VM_SENSE": "ANALOG", "Q201_G": "SIGNAL",
    })
