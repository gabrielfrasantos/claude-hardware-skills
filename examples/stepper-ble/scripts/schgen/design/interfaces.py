"""Sheet 6: USB-C (full speed device), SWD (Tag-Connect), LEDs, button, mechanical parts."""
from sch import Sheet

from parts import classes, series, shunt


def g(n):
    return round(n * 2.54, 2)


def build(project, values):
    sh = Sheet(project, 6, "interfaces", "USB, debug and user IO")
    sh.desc = ["USB-C receptacle, USB 2.0 FS device, 5.1k CC pull-downs, USBLC6 ESD", "Tag-Connect TC2030 SWD",
               "Status and fault LEDs, user button"]

    sh.box(g(6), g(6), g(66), g(56), "USB-C (interface-layout skill)")
    j = sh.part("Connector:USB_C_Receptacle_USB2.0_16P", "J601", "USB-C", (g(20), g(30)),
                fp="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", lcsc="C165948", mpn="TYPE-C-31-M-12")
    for pin in ("A9", "B4", "B9"):
        sh.path("VBUS", [j[pin], j["A4"]])
    for pin in ("A12", "B1", "B12"):
        sh.path("GND", [j[pin], j["A1"]])
    sh.net(j["A1"], "GND")
    sh.nc(j["A8"])
    sh.nc(j["B8"])
    esd = sh.part("Power_Protection:USBLC6-2SC6", "U601", "USBLC6-2SC6", (g(40), g(30)),
                  fp="Package_TO_SOT_SMD:SOT-23-6", lcsc="C7519", mpn="USBLC6-2SC6")
    esd.fpos = (-6.35, -6.35, "right")
    sh.net(esd["2"], "GND")
    c601 = shunt(sh, "C601", "4.7u", g(48), g(24))
    sh.rail("VBUS", g(24), [j["A4"], (g(40), g(24)), c601["1"]], tap=(g(34), (0, -1)))
    sh.path("VBUS", [esd["5"], (g(40), g(24))])
    sh.path("USB_DM", [j["A7"], (g(28), g(29)), (g(28), g(30))])
    sh.rail("USB_DM", g(30), [j["B7"], esd["1"]])
    sh.path("USB_DP", [j["B6"], (g(27), g(32)), (g(27), g(31))])
    sh.rail("USB_DP", g(31), [j["A6"], esd["3"]])
    sh.rail("USB_DM", g(30), [esd["6"], (g(54), g(30))], label="right")
    sh.rail("USB_DP", g(31), [esd["4"], (g(54), g(31))], label="right")
    sh.net(j["A5"], "USB_CC1")
    sh.net(j["B5"], "USB_CC2")
    r603 = shunt(sh, "R603", "0", g(17), g(44))
    sh.path("USB_SHIELD", [j["SH"], r603["1"]])
    sh.label("USB_SHIELD", (g(17), g(42)), (-1, 0))
    for i, (ref, net) in enumerate((("R601", "USB_CC1"), ("R602", "USB_CC2"))):
        r = shunt(sh, ref, "5.1k", g(36 + 6 * i), g(40))
        sh.net(r["1"], net)
    sh.flag("VBUS", (g(60), g(12)))
    sh.note(g(24), g(48), [
        "Sink: 5.1 kohm Rd on CC1 and CC2 (USB Type-C spec 4.11). D+/D- joined across both rows",
        "(either plug orientation). USBLC6-2SC6 at the connector; D+/D- 90 ohm differential.",
        "Shield to GND through R603 (0 ohm; an RC if EMC needs). VBUS -> D204 (sheet 2).",
    ])

    sh.box(g(68), g(6), g(156), g(56), "Debug and user IO")
    tc = sh.part("Connector:Conn_ARM_SWD_TagConnect_TC2030", "J602", "TC2030", (g(76), g(22)),
                 fp="Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical", in_bom=False)
    tc.fpos = (-7.62, -1.27, "right")
    sh.nets(tc, {"1": "+3V3", "5": "GND", "3": "NRST", "4": "SWCLK", "2": "SWDIO", "6": "SWO"})
    for i, (net, rref, led, colour, lcsc, mpn) in enumerate((
            ("LED_STATUS", "R604", "D601", "green", "C12624", "KT-0603G"),
            ("LED_FAULT", "R605", "D602", "red", "C2286", "KT-0603R"))):
        yy = g(14 + 10 * i)
        r = series(sh, rref, "1k", g(98), yy)
        sh.path(net, [r["1"], (g(94), yy)])
        sh.label(net, (g(94), yy), (-1, 0))
        d = sh.part("Device:LED", led, colour, (g(118), yy + 3.81), rot=90, fp="LED_SMD:LED_0603_1608Metric",
                    lcsc=lcsc, mpn=mpn)
        sh.link(r["2"], d["2"], net + "_A")
        sh.net(d["1"], "GND")
    sw = sh.part("Switch:SW_Push", "SW601", "BUTTON", (g(122), g(42)), fp="Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2",
                 lcsc="C318884", mpn="TS-1187A-B-A-B")
    r606 = shunt(sh, "R606", "10k", g(104), g(39), bottom=None)
    sh.net(r606["1"], "+3V3")
    c602 = shunt(sh, "C602", "100n", g(110), g(42))
    sh.rail("BUTTON", g(42), [(g(96), g(42)), r606["2"], c602["1"], sw["1"]], label="left")
    sh.rail("GND", g(42), [sw["2"], (g(128), g(42))], tap=(g(128), (0, 1)))
    sh.note(g(70), g(50), [
        "TC2030 (no part on the board): SWD, NRST, SWO. LEDs: (3.3 V - 2.0 V) / 1 kohm = 1.3 mA (derived).",
        "Button: 10 kohm pull-up, 100 nF = 1 ms RC debounce.",
    ])

    sh.box(g(6), g(58), g(156), g(70), "Mechanical")
    for i in range(4):
        sh.part("Mechanical:MountingHole", f"H60{i + 1}", "M3", (g(12 + 10 * i), g(64)),
                fp="MountingHole:MountingHole_3.2mm_M3", in_bom=False)
    for i in range(3):
        sh.part("Mechanical:Fiducial", f"FID60{i + 1}", "Fiducial", (g(56 + 10 * i), g(64)),
                fp="Fiducial:Fiducial_1mm_Mask2mm", in_bom=False)
    sh.note(g(90), g(62), ["Four M3 holes, not plated, not on a net.", "Three fiducials for assembly (JLCPCB)."])

    sh.class_table(g(6), g(72), rows=6, col_w=g(25))
    classes(sh, {"USB_CC1": "SIGNAL", "USB_SHIELD": "GND"})
