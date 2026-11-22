"""Sheet 3: DRV8711 stepper pre-driver, two external N-FET H-bridges, sense resistors, motor connector."""
from sch import Sheet

from parts import classes, shunt

FET = dict(fp="Package_SON:VSON-8_3.3x3.3mm_P0.65mm_NexFET", lcsc="C840100", mpn="CSD18543Q3A")


def g(n):
    return round(n * 2.54, 2)


def fet(sh, ref, x, y, gate):
    q = sh.part("Transistor_FET:CSD18543Q3A", ref, "CSD18543Q3A", (g(x), g(y)), **FET)
    q.fpos = (5.08, -1.27, "left")
    q.hide_value = True
    sh.net(q["4"], gate)
    return q


def build(project, values):
    sh = Sheet(project, 3, "motor", "Stepper driver")
    sh.global_all = True
    sh.desc = ["DRV8711 (SPI, indexer, stall detect)", "Two H-bridges of CSD18543Q3A, 0.1 ohm sense", "Motor terminal"]

    sh.box(g(6), g(6), g(46), g(100), "DRV8711 (TI SLVSC40H)")
    u = sh.part("stepper-ble:DRV8711", "U301", "DRV8711", (g(26), g(30)),
                fp="Package_SO:HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm_ThermalVias",
                lcsc="C60013", mpn="DRV8711DCPR")
    u.fpos = (2.54, -31.75, "left")
    sh.nets(u, {
        "4": "VM", "1": "DRV_CP1", "2": "DRV_CP2", "3": "DRV_VCP", "6": "DRV_V5", "7": "DRV_VINT",
        "8": "DRV_SLEEPn", "9": "DRV_RESET", "10": "DRV_STEP", "11": "DRV_DIR", "12": "GND", "13": "GND",
        "14": "DRV_SCLK", "15": "DRV_SDATI", "16": "DRV_SCS", "17": "DRV_SDATO", "18": "DRV_FAULTn",
        "19": "DRV_STALLn", "20": "DRV_BEMF",
        "36": "A1HS", "37": "AOUT1", "35": "A1LS", "31": "A2HS", "30": "AOUT2", "32": "A2LS", "34": "ISENA",
        "27": "B1HS", "28": "BOUT1", "26": "B1LS", "22": "B2HS", "21": "BOUT2", "23": "B2LS", "25": "ISENB"})
    sh.rail("GND", g(43), [u[n] for n in ("5", "29", "38", "39", "33", "24")], tap=(g(24), (0, 1)))

    caps = [("C305", "10n 50V", "VM", "GND"), ("C302", "1u 50V", "VM", "DRV_VCP", True),
            ("C301", "100n 50V", "DRV_CP1", "DRV_CP2"), ("C303", "100n", "DRV_V5", "GND"),
            ("C304", "1u", "DRV_VINT", "GND"), ("C308", "1n", "DRV_BEMF", "GND")]
    for i, (ref, value, top, bottom, *flip) in enumerate(caps):
        c = shunt(sh, ref, value, g(8 + 7 * i), g(52), bottom=bottom, flip=bool(flip))
        sh.net(c.top, top)
    pulls = [("R303", "10k", "DRV_SDATO"), ("R304", "10k", "DRV_FAULTn"), ("R305", "10k", "DRV_STALLn")]
    for i, (ref, value, net) in enumerate(pulls):
        r = shunt(sh, ref, value, g(10 + 6 * i), g(66), bottom=net)
        sh.net(r["1"], "+3V3")
    r306 = shunt(sh, "R306", "100k", g(28), g(66))
    sh.net(r306["1"], "DRV_SLEEPn")
    r307 = shunt(sh, "R307", "10k", g(34), g(66), bottom=None)
    sh.net(r307["1"], "DRV_BEMF")
    r308 = shunt(sh, "R308", "20k", g(34), g(70))
    sh.path("BEMF_ADC", [r307["2"], r308["1"]])
    sh.rail("BEMF_ADC", g(69), [(g(34), g(69)), (g(38), g(69))], label="right")
    sh.note(g(8), g(80), [
        "Pin Functions (SLVSC40H 5): CP1-CP2 0.1 uF rated > VM; VCP 1 uF to VM;",
        "V5 0.1 uF; VINT 1 uF; VM 0.01 uF + bulk (sheet 2); BEMF 1 nF low leakage.",
        "SDATO, FAULTn, STALLn open drain: 10k pull-ups to +3V3.",
        "Logic VIH 1.5 V (6.5): the 3.3 V MCU drives it directly. BIN1/BIN2 unused",
        "in indexer mode: tied to GND. R306 holds SLEEPn low until the MCU drives it.",
        "BEMF to the ADC through 10k/20k: 5 V -> 3.33 V (derived);",
        "ASSUMPTION: BEMF <= V5 and drives 30 kohm.",
    ])

    sh.box(g(48), g(6), g(160), g(56), "H-bridges and current sense")
    bridges = [("A", 54, "Q301", "Q302", "AOUT1", "A1HS", "A1LS"), ("A", 67, "Q303", "Q304", "AOUT2", "A2HS", "A2LS"),
               ("B", 87, "Q305", "Q306", "BOUT1", "B1HS", "B1LS"), ("B", 100, "Q307", "Q308", "BOUT2", "B2HS", "B2LS")]
    drains, sources = [], {"A": [], "B": []}
    for side, x, hs_ref, ls_ref, phase, hs_gate, ls_gate in bridges:
        hs = fet(sh, hs_ref, x, 20, hs_gate)
        ls = fet(sh, ls_ref, x, 30, ls_gate)
        drains.append(hs["5"])
        sources[side] += [ls["1"], ls["2"], ls["3"]]
        sh.path(phase, [hs["1"], ls["5"]])
        sh.path(phase, [(g(x + 1), g(25)), (g(x + 4), g(25))])
        sh.label(phase, (g(x + 4), g(25)), (1, 0))
        for pin in ("2", "3"):
            sh.path(phase, [hs[pin], hs["1"]])
    c306 = shunt(sh, "C306", "4.7u 50V", g(77), g(14))
    c307 = shunt(sh, "C307", "4.7u 50V", g(110), g(14))
    sh.rail("VM", g(14), drains + [c306["1"], c307["1"]], tap=(g(50), (0, -1)))
    r301 = shunt(sh, "R301", "0.1R 1W", g(77), g(37))
    r302 = shunt(sh, "R302", "0.1R 1W", g(110), g(37))
    sh.rail("ISENA", g(37), sources["A"][::3] + [r301["1"]], label="left")
    sh.rail("ISENB", g(37), sources["B"][::3] + [r302["1"]], label="right")
    for side in ("A", "B"):
        pins = sources[side]
        for i in range(0, len(pins), 3):
            sh.path("ISEN" + side, [pins[i + 1], pins[i]])
            sh.path("ISEN" + side, [pins[i + 2], pins[i]])

    j = sh.part("Connector:Screw_Terminal_01x04", "J301", "MOTOR", (g(150), g(24)),
                fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal",
                lcsc="C5443561", mpn="1715747")
    for pin, net in (("1", "AOUT1"), ("2", "AOUT2"), ("3", "BOUT1"), ("4", "BOUT2")):
        sh.path(net, [j[pin], (g(146), j[pin].y)])
        sh.label(net, (g(146), j[pin].y), (-1, 0))
    sh.note(g(116), g(14), [
        "ICHOP = 2.75 V x TORQUE / (256 x ISGAIN x RSENSE)",
        "(SLVSC40H eq. 1). ISGAIN 10, RSENSE 0.1 ohm,",
        "TORQUE 186: 2.00 A per phase (derived); TORQUE 255",
        "gives 2.74 A. Firmware limits TORQUE to 186 (HW-MOT-002).",
        "VSENSE 0.2 V at 2 A, under the 0.7 V xISENx rating.",
        "P = 0.2 W rms in a 1 W 2512.",
        "Q301-Q308: CSD18543Q3A, 60 V, Qg 11.1 nC (SLPS633).",
        "C306/C307: 4.7 uF at each bridge's high side.",
    ])

    sh.box(g(48), g(58), g(100), g(80), "FET temperature")
    nt = shunt(sh, "RT301", "10k B3380", g(62), g(68))
    r309 = shunt(sh, "R309", "10k", g(62), g(62), bottom=None)
    sh.net(r309["1"], "+3V3")
    c309 = shunt(sh, "C309", "100n", g(70), g(68))
    sh.path("NTC_ADC", [r309["2"], nt["1"]])
    sh.rail("NTC_ADC", g(68), [(g(62), g(68)), c309["1"], (g(76), g(68))], label="right")
    sh.note(g(80), g(62), ["RT301 sits between the bridges;", "10k NTC under a 10k pull-up."])

    sh.class_table(g(48), g(82), rows=10, col_w=g(19))
    classes(sh, {
        "AOUT1": "PWR_2A_30V", "AOUT2": "PWR_2A_30V", "BOUT1": "PWR_2A_30V", "BOUT2": "PWR_2A_30V",
        "ISENA": "PWR_2A", "ISENB": "PWR_2A", "BEMF_ADC": "ANALOG", "NTC_ADC": "ANALOG", "DRV_BEMF": "ANALOG",
    })
