"""Sheet 6: USB-C full-speed device (sink), ESD at the connector (interface-layout §2-§4, mcu-circuit-design §8)."""
from sch import Sheet
from parts import part


def build(project, values):
    sh = Sheet(project, 6, "usb", "USB", paper="A4")
    sh.desc = ["J601 USB-C receptacle (sink, Rd 5.1k)", "U601 USBLC6-2SC6 ESD on D+/D- and VBUS", "VBUS -> sheet 2"]
    sh.box(15.24, 40.64, 132.08, 106.68, "Connector -> ESD (pass-through) -> MCU (interface-layout §2, §3)")
    j = part(sh, "USBC", "J601", (40.64, 76.2))
    u = part(sh, "ESD", "U601", (73.66, 73.66))
    u.fpos = (7.62, -7.62, "left")
    c = part(sh, "C4u7", "C601", (99.06, 64.77))
    cv = part(sh, "C100n", "C602", (111.76, 64.77))
    sh.rail("VBUS", 60.96, [j["A4"], u["5"], c["1"], cv["1"]], label="right", ext=7.62)
    sh.net(c["2"], "GND")
    sh.net(cv["2"], "GND")
    sh.link(j["A7"], j["B7"], "USB_C_DM")
    sh.link(j["A7"], u["1"], "USB_C_DM")
    sh.link(j["A6"], j["B6"], "USB_C_DP")
    sh.path("USB_C_DP", [j["A6"], (63.5, 78.74), (63.5, 76.2), u["3"]])
    sh.label("USB_C_DM", (66.04, 73.66), (0, -1))
    sh.label("USB_C_DP", (60.96, 78.74), (0, 1))
    sh.net(u["6"], "USB_DM")
    sh.net(u["4"], "USB_DP")
    sh.net(u["2"], "GND")
    sh.net(j["A5"], "CC1")
    sh.net(j["B5"], "CC2")
    sh.nc(j["A8"])
    sh.nc(j["B8"])
    sh.nets(j, {"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND"})
    sh.net(j["SH"], "GND")

    sh.box(15.24, 111.76, 132.08, 142.24, "Sink: Rd on each CC line (mcu-circuit-design §8)")
    for ref, net, x in (("R601", "CC1", 40.64), ("R602", "CC2", 66.04)):
        r = part(sh, "R5k1", ref, (x, 127.0))
        sh.net(r["1"], net)
        sh.net(r["2"], "GND")

    sh.note(137.16, 45.72, [
        "USB 2.0 full-speed device on PA11/PA12 (fixed USB pins);",
        "  STM32WB has the series R and the D+ pull-up inside.",
        "A6/B6 and A7/B7 are joined at the receptacle; the stub",
        "  stays < 3.5 mm and the ESD part is not on it",
        "  (interface-layout §4, AN4871).",
        "U601 USBLC6-2SC6 at the connector, routed through its",
        "  pins (connector -> I/O pin -> MCU), no via before it;",
        "  channel 1 on D-, channel 2 on D+ (symmetric part).",
        "  VBUS pin to VBUS with C602 100 nF at the pin.",
        "D+/D- class DIFF_90: 90 ohm differential (USB 2.0;",
        "  interface-layout §3); FS is tolerant of mismatch.",
        "VBUS: C601 4.7 uF (1-10 uF for a device, AN26.2);",
        "  D202 (sheet 2) blocks back-feed from 24 V.",
        "CC1/CC2: Rd 5.1k to GND (sink, default USB power).",
        "  No CC ESD part in the parts list: deviation D-008.",
        "Shield to GND directly (no metal enclosure, D-008).",
    ])
    for n, cl in (("USB_C_DM", "DIFF_90"), ("USB_C_DP", "DIFF_90"), ("USB_DM", "DIFF_90"), ("USB_DP", "DIFF_90"),
                  ("VBUS", "PWR_1A"), ("CC1", "SIGNAL"), ("CC2", "SIGNAL"), ("GND", "GND")):
        sh.netclass(n, cl)
    sh.class_table(137.16, 111.76, rows=8)
