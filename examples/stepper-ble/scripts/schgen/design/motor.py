"""Sheet 3: motor driver. DRV8711 with two external N-FET H-bridges, low-side sense, NTC at the FETs
(power-circuit-design §7-§12, DRV8711 SLVSC40H)."""
from sch import Sheet
from parts import part, special

HALF_BRIDGES = [  # (high-side ref, low-side ref, phase, high gate, low gate, x of the FET symbols)
    ("Q301", "Q302", "AOUT1", "A1HS", "A1LS", 152.4),
    ("Q303", "Q304", "AOUT2", "A2HS", "A2LS", 193.04),
    ("Q305", "Q306", "BOUT1", "B1HS", "B1LS", 241.3),
    ("Q307", "Q308", "BOUT2", "B2HS", "B2LS", 281.94),
]
Y_VM, Y_HS, Y_LS, Y_ISEN = 53.34, 73.66, 93.98, 104.14


def bridges(sh):
    sh.box(121.92, 35.56, 345.44, 137.16, "Bridges A and B, low-side sense (DRV8711 Fig. 20; power-circuit-design §7)")
    bulk = part(sh, "C100u50", "C301", (134.62, 60.96))
    vm_pins = [bulk["1"]]
    lows = {}
    for hs_ref, ls_ref, phase, g_hs, g_ls, x in HALF_BRIDGES:
        hs = part(sh, "FET", hs_ref, (x, Y_HS))
        ls = part(sh, "FET", ls_ref, (x, Y_LS))
        for q in (hs, ls):
            q.hide_value = True
            q.fpos = (5.08, 0.0, "left")
        vm_pins.append(hs["5"])
        sh.link(hs["1"], ls["5"], phase)
        sh.label(phase, (x + 2.54, (Y_HS + Y_LS) / 2), (1, 0))
        sh.net(hs["4"], g_hs)
        sh.net(ls["4"], g_ls)
        lows[phase] = ls
    hf = [part(sh, "C4u7_50", ref, (x, 60.96)) for ref, x in (("C303", 172.72), ("C304", 220.98), ("C305", 261.62))]
    vm_pins += [c["1"] for c in hf]
    sh.rail("VM", Y_VM, vm_pins, label="left", ext=5.08)
    sh.net(bulk["2"], "GND")
    for c in hf:
        sh.net(c["2"], "GND")

    for bridge, (pa, pb), r_ref, nt_p, nt_n, xs, kp, kn in (
            ("ISEN_A", ("AOUT1", "AOUT2"), "R301", "NT301", "NT302", 172.72, "AISENP", "AISENN"),
            ("ISEN_B", ("BOUT1", "BOUT2"), "R302", "NT303", "NT304", 261.62, "BISENP", "BISENN")):
        rs = part(sh, "R0R1", r_ref, (xs, 111.76))
        sh.rail(bridge, Y_ISEN, [lows[pa]["1"], lows[pb]["1"], rs["1"]])
        tp = special(sh, "Device:NetTie_2", nt_p, "NetTie", (xs + 15.24, 107.95), "NetTie:NetTie-2_SMD_Pad0.5mm")
        tn = special(sh, "Device:NetTie_2", nt_n, "NetTie", (xs + 15.24, 115.57), "NetTie:NetTie-2_SMD_Pad0.5mm")
        tp.hide_value = tn.hide_value = True
        tp.fpos = tn.fpos = (-3.81, -2.54, "left")
        sh.link(rs["1"], tp["1"], bridge)
        sh.link(rs["2"], tn["1"], "GND")
        sh.net(rs["2"], "GND")
        sh.net(tp["2"], kp)
        sh.net(tn["2"], kn)
        sh.label(bridge, (xs - 7.62, Y_ISEN), (0, -1))

    ntc = part(sh, "NTC", "TH301", (312.42, 116.84))
    sh.net(ntc["1"], "NTC_SENSE")
    sh.net(ntc["2"], "GND")

    j = part(sh, "J_MOT", "J301", (332.74, 63.5))
    for pin, net in zip("1234", ("AOUT1", "AOUT2", "BOUT1", "BOUT2")):
        sh.net(j[pin], net)


def driver(sh):
    sh.box(20.32, 99.06, 116.84, 180.34, "DRV8711 (SLVSC40H §5, §8.2)")
    u = part(sh, "DRV8711", "U301", (76.2, 142.24))
    u.fpos = (-20.32, -29.21, "right")
    sh.nets(u, {"4": "VM", "3": "VCP", "1": "CP1", "2": "CP2", "6": "DRV_5V", "7": "DRV_1V8",
                "8": "DRV_SLEEPN", "9": "DRV_RESET", "10": "DRV_STEP", "11": "DRV_DIR", "12": "GND", "13": "GND",
                "14": "DRV_SCLK", "15": "DRV_MOSI", "16": "DRV_SCS", "17": "DRV_MISO", "18": "DRV_FAULTN",
                "19": "DRV_STALLN", "20": "DRV_BEMF",
                "37": "AOUT1", "36": "A1HS", "35": "A1LS", "30": "AOUT2", "31": "A2HS", "32": "A2LS",
                "34": "AISENP", "33": "AISENN", "28": "BOUT1", "27": "B1HS", "26": "B1LS", "21": "BOUT2",
                "22": "B2HS", "23": "B2LS", "25": "BISENP", "24": "BISENN"})
    sh.rail("GND", 172.72, [u["5"], u["29"], u["38"], u["39"]], tap=(76.2, (0, 1)))

    sh.box(20.32, 35.56, 116.84, 93.98, "DRV8711 supply pins (SLVSC40H §10.1)")
    c_vm = part(sh, "C10n50", "C302", (30.48, 58.42))
    c_vcp = part(sh, "C1u50", "C306", (45.72, 58.42))
    sh.rail("VM", 50.8, [c_vm["1"], c_vcp["1"]], label="left", ext=5.08)
    sh.net(c_vm["2"], "GND")
    sh.net(c_vcp["2"], "VCP")
    c_cp = part(sh, "C100n50", "C307", (63.5, 58.42))
    sh.net(c_cp["1"], "CP1")
    sh.net(c_cp["2"], "CP2")
    c_v5 = part(sh, "C100n", "C308", (81.28, 58.42))
    sh.net(c_v5["1"], "DRV_5V")
    sh.net(c_v5["2"], "GND")
    c_vint = part(sh, "C1u", "C309", (99.06, 58.42))
    sh.net(c_vint["1"], "DRV_1V8")
    sh.net(c_vint["2"], "GND")

    sh.box(20.32, 182.88, 116.84, 254.0, "Safe state, open-drain pull-ups, BEMF")
    r_sleep = part(sh, "R100k", "R303", (30.48, 213.36))
    sh.net(r_sleep["1"], "DRV_SLEEPN")
    sh.net(r_sleep["2"], "GND")
    pullups = [("R304", "DRV_RESET", 45.72), ("R305", "DRV_MISO", 60.96), ("R306", "DRV_FAULTN", 76.2),
               ("R307", "DRV_STALLN", 91.44)]
    rs = []
    for ref, net, x in pullups:
        r = part(sh, "R10k", ref, (x, 218.44))
        sh.net(r["2"], net)
        rs.append(r)
    sh.rail("+3V3", 208.28, [r["1"] for r in rs], tap=(68.58, (0, -1)))
    c_bemf = part(sh, "C1n", "C310", (106.68, 213.36))
    sh.net(c_bemf["1"], "DRV_BEMF")
    sh.net(c_bemf["2"], "GND")


def build(project, values):
    sh = Sheet(project, 3, "motor", "Motor driver")
    sh.desc = ["U301 DRV8711, SPI + STEP/DIR (indexer)", "Q301-Q308 CSD18543Q3A, two H-bridges",
               "R301/R302 0.1 ohm sense, TH301 NTC", "J301 motor terminal"]
    bridges(sh)
    driver(sh)
    sh.note(124.46, 142.24, [
        "U301 DRV8711 per SLVSC40H Fig. 20 and §10.1: VM 0.01 uF (C302) at the pin + 100 uF bulk (C301) at the bridges;",
        "  VCP-VM 1 uF >= 16 V (C306, 50 V part); CP1-CP2 0.1 uF rated above VM (C307 100n 50 V); VINT 1 uF >= 6.3 V (C309);",
        "  V5 0.1 uF 10 V per the pin table (C308; §10.1 says 1 uF: the pin table is followed, OI-5); BEMF 1 nF (C310).",
        "Current (Eq. 7): IFS = 2.75 V x TORQUE / (256 x ISGAIN x RSENSE). RSENSE 0.1 ohm, ISGAIN 10: TORQUE 186 -> 2.0 A",
        "  (HW-MOT-002, D-021). Sense 0.2 V < ISENSE abs max 0.7 V. R301/R302 2512 1 W: 2.0^2 x 0.1 = 0.4 W at full-step peak.",
        "Q301-Q308 CSD18543Q3A (SLPS532): VDS 60 V >= VC 53.3 V; 30 V max bus = 50 % of VDS; RDS(on) 8.1 mOhm at 10 V,",
        "  Qg 11.1 nC. Conduction per FET at 1.41 A rms, x1.5 hot: 1.41^2 x 12 mOhm = 24 mW (power-circuit-design §7).",
        "HF bypass: C303-C305 4.7u 50 V, one beside each pair of half-bridges, VM to GND (the shunt is in the loop); D-002.",
        "No gate resistors: DRV8711 sets gate current by register (IDRIVE), TI marks series R optional; deviation D-022.",
        "Phase pins AOUTx abs min -0.6 V vs body-diode VF in dead time: no Schottky clamps in the parts list (D-013, B6).",
        "Kelvin sense: NT301-NT304 net ties keep AISENP/N, BISENP/N apart from ISEN_x and GND (power-circuit-design §10).",
        "Safe state (D-018): R303 holds SLEEPn low, R304 holds RESET high until the MCU drives them; digital pins 5.5 V max.",
        "TH301 NCP15XH103 sits between the FETs (power-circuit-design §11); its bias R is at the ADC pin, sheet 4.",
    ])
    classes = [("VM", "PWR_3A"), ("AOUT1", "PWR_2A"), ("AOUT2", "PWR_2A"), ("BOUT1", "PWR_2A"),
               ("BOUT2", "PWR_2A"), ("ISEN_A", "PWR_2A"), ("ISEN_B", "PWR_2A"), ("AISENP", "SENSE"),
               ("AISENN", "SENSE"), ("BISENP", "SENSE"), ("BISENN", "SENSE"), ("VCP", "PWR_0p5A")]
    classes += [(n, "SIGNAL") for n in ("A1HS", "A1LS", "A2HS", "A2LS", "B1HS", "B1LS", "B2HS", "B2LS", "CP1", "CP2")]
    classes += [("DRV_5V", "PWR_0p5A"), ("DRV_1V8", "PWR_0p5A")]
    classes += [(n, "SIGNAL") for n in ("DRV_SLEEPN", "DRV_RESET", "DRV_STEP", "DRV_DIR", "DRV_SCLK", "DRV_MOSI",
                                        "DRV_SCS", "DRV_MISO", "DRV_FAULTN", "DRV_STALLN")]
    classes += [("DRV_BEMF", "ANALOG"), ("NTC_SENSE", "ANALOG"), ("+3V3", "PWR_0p5A"), ("GND", "GND")]
    for n, c in classes:
        sh.netclass(n, c)
    sh.class_table(124.46, 182.88, rows=12)
