"""Sheet 2: logic supplies. 5 V buck from VM, OR-ed with USB VBUS, then the 3.3 V LDO (power-circuit-design §6)."""
from sch import Sheet
from parts import part


def build(project, values):
    sh = Sheet(project, 2, "supplies", "Logic supplies", paper="A4")
    sh.desc = ["U201 LMR36510 5 V buck from VM", "D201/D202 OR 5V_BUCK with VBUS -> +5V", "U202 AP2112K -> +3V3"]
    sh.box(15.24, 33.02, 146.05, 96.52, "5 V buck (LMR36510, SNVSBD7B §8.2)")
    sh.box(148.59, 33.02, 228.6, 96.52, "OR-ing and 3.3 V LDO")

    c_in = part(sh, "C4u7_50", "C201", (30.48, 53.34))
    c_hf = part(sh, "C220n50", "C202", (43.18, 53.34))
    r_ent = part(sh, "R100k", "R201", (55.88, 53.34))
    r_enb = part(sh, "R20k", "R202", (55.88, 68.58))
    u = part(sh, "BUCK", "U201", (83.82, 60.96))
    sh.rail("VM", 45.72, [c_in["1"], c_hf["1"], r_ent["1"], u["2"]], label="left", ext=7.62)
    sh.net(c_in["2"], "GND")
    sh.net(c_hf["2"], "GND")
    sh.path("EN_BUCK", [r_ent["2"], r_enb["1"]])
    sh.path("EN_BUCK", [u["3"], (55.88, 60.96)])
    sh.net(r_enb["2"], "GND")

    c_vcc = part(sh, "C1u", "C203", (68.58, 78.74))
    sh.path("BUCK_VCC_5V", [u["6"], (68.58, 66.04), c_vcc["1"]])
    sh.net(c_vcc["2"], "GND")
    sh.rail("GND", 73.66, [u["1"], u["9"]], tap=(83.82, (0, 1)))

    c_boot = part(sh, "C100n", "C204", (101.6, 54.61))
    sh.path("BOOT_BUCK", [u["7"], (96.52, 55.88), (96.52, 50.8), c_boot["1"]])
    lsw = part(sh, "L22u", "L201", (114.3, 58.42), rot=90)
    sh.path("SW_BUCK", [u["8"], c_boot["2"]])
    sh.path("SW_BUCK", [c_boot["2"], lsw["1"]])
    sh.nc(u["4"])
    sh.label("BUCK_VCC_5V", (71.12, 66.04), (-1, 0))
    sh.label("BOOT_BUCK", (96.52, 50.8), (0, -1))
    sh.label("SW_BUCK", (106.68, 58.42), (0, 1))
    sh.label("5V_BUCK", (121.92, 58.42), (0, 1))

    r_fbb = part(sh, "R24k9", "R204", (99.06, 82.55))
    r_fbt = part(sh, "R100k", "R203", (111.76, 73.66), rot=90)
    sh.path("FB_BUCK", [u["5"], (99.06, 63.5), r_fbb["1"]])
    sh.path("FB_BUCK", [r_fbt["1"], (99.06, 73.66)])
    sh.net(r_fbb["2"], "GND")
    c_o1 = part(sh, "C22u", "C205", (129.54, 62.23))
    c_o2 = part(sh, "C22u", "C206", (142.24, 62.23))
    sh.path("5V_BUCK", [r_fbt["2"], (124.46, 73.66), (124.46, 58.42)])

    d_buck = part(sh, "SS34", "D201", (160.02, 58.42), rot=180)
    d_usb = part(sh, "SS34", "D202", (160.02, 45.72), rot=180)
    sh.rail("5V_BUCK", 58.42, [lsw["2"], (124.46, 58.42), c_o1["1"], c_o2["1"], d_buck["2"]])
    sh.net(c_o1["2"], "GND")
    sh.net(c_o2["2"], "GND")
    sh.net(d_usb["2"], "VBUS")

    ldo = part(sh, "LDO", "U202", (209.55, 60.96))
    c5 = part(sh, "C4u7", "C209", (172.72, 62.23))
    c_li = part(sh, "C1u", "C207", (185.42, 62.23))
    flag = sh.flag("+5V", (194.31, 58.42), label=False)
    sh.path("+5V", [d_usb["1"], (167.64, 45.72), (167.64, 58.42)])
    sh.rail("+5V", 58.42, [d_buck["1"], (167.64, 58.42), c5["1"], c_li["1"], flag["1"], (199.39, 58.42), ldo["1"]],
            tap=(179.07, (0, -1)))
    sh.path("+5V", [ldo["3"], (199.39, 60.96), (199.39, 58.42)])
    sh.net(c5["2"], "GND")
    sh.net(c_li["2"], "GND")
    sh.net(ldo["2"], "GND")
    c_lo = part(sh, "C1u", "C208", (222.25, 62.23))
    sh.rail("+3V3", 58.42, [ldo["5"], c_lo["1"]], tap=(217.17, (0, -1)))
    sh.net(c_lo["2"], "GND")

    sh.note(91.44, 104.14, [
        "U201 LMR36510ADDA, 400 kHz, SNVSBD7B Table 8-1 (5 V row): L 22 uH, COUT 2 x 22 uF, RFBT 100k, RFBB 24.9k,",
        "  CIN 2.2 uF + 220 nF; here C201 4.7u 50 V X7R + C202 220n 50 V. VOUT = 1.0 V x (1 + 100k/24.9k) = 5.02 V (Eq. 3).",
        "  VIN abs max 70 V, recommended 65 V: above VC 53.3 V of D101. CBOOT 100n >= 16 V (§8.2.1.2.6); VCC 1u (§8.2.1.2.7).",
        "  EN UVLO (Eq. 10): VON = 1.231 V x (1 + 100k/20k) = 7.4 V, VOFF = 7.4 x (1 - 0.110/1.231) = 6.7 V (HW-PWR-004).",
        "  Ripple (Eq. 4): (24 - 5)/(400k x 22u) x 5/24 = 0.45 A pp (45 % of 1 A); LMIN = 0.625 x 5/400k = 7.8 uH (Eq. 5).",
        "  L201 Isat must be >= ILIMIT 1.6 A max (§8.2.1.2.3): not read from the Sunlord datasheet, open item OI-3.",
        "  C205/C206 are 6.3 V X5R at 5 V: effective capacitance under DC bias is an ASSUMPTION (OI-4).",
        "D201/D202 SS34 (40 V, 3 A) OR 5V_BUCK and VBUS: each blocks back-feed into the other source (HW-PWR-005).",
        "U202 AP2112K-3.3: 600 mA, dropout 250 mV typ at 600 mA; CIN = COUT = 1 uF ceramic (Diodes AP2112 datasheet).",
        "  +5V >= 4.5 V after the Schottky, so >= 1 V headroom. P = (4.6 - 3.3) V x 0.15 A = 0.2 W at the expected load.",
        "C209 4.7u is the +5V bulk; VBUS capacitance seen by the host stays C601 only (D202 blocks C209).",
    ])

    for n, c in (("VM", "PWR_3A"), ("EN_BUCK", "SIGNAL"), ("BUCK_VCC_5V", "PWR_0p5A"), ("BOOT_BUCK", "PWR_1A"),
                 ("SW_BUCK", "PWR_1A"), ("FB_BUCK", "SIGNAL"), ("5V_BUCK", "PWR_1A"), ("+5V", "PWR_1A"),
                 ("+3V3", "PWR_0p5A"), ("GND", "GND")):
        sh.netclass(n, c)
    sh.class_table(15.24, 101.6, rows=10)
