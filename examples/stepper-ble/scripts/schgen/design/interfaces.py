"""Sheet 6: USB-C (full speed device), SWD (Tag-Connect), LEDs, button."""
from sch import Sheet

from parts import classes, row


def build(project, values):
    sh = Sheet(project, 6, "interfaces", "USB, debug and user IO")
    sh.desc = ["USB-C receptacle, USB 2.0 FS device, 5.1k CC pull-downs, USBLC6 ESD", "Tag-Connect TC2030 SWD",
               "Status and fault LEDs, user button"]

    sh.box(15.24, 15.24, 200.66, 165.1, "USB-C (interface-layout skill)")
    j = sh.part("Connector:USB_C_Receptacle_USB2.0_16P", "J601", "USB-C", (50.8, 76.2),
                fp="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", lcsc="C165948", mpn="TYPE-C-31-M-12")
    sh.nets(j, {"A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS", "A1": "GND", "A12": "GND", "B1": "GND",
                "B12": "GND", "A5": "USB_CC1", "B5": "USB_CC2", "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM",
                "B7": "USB_DM", "A8": None, "B8": None, "SH": "USB_SHIELD"})
    esd = sh.part("Power_Protection:USBLC6-2SC6", "U601", "USBLC6-2SC6", (147.32, 76.2),
                  fp="Package_TO_SOT_SMD:SOT-23-6", lcsc="C7519", mpn="USBLC6-2SC6")
    sh.nets(esd, {"1": "USB_DP", "6": "USB_DP", "3": "USB_DM", "4": "USB_DM", "2": "GND", "5": "VBUS"})
    row(sh, "R", 30.48, 137.16, [("R601", "5.1k", "USB_CC1", "GND"), ("R602", "5.1k", "USB_CC2", "GND"),
                                 ("R603", "0", "USB_SHIELD", "GND")])
    row(sh, "C", 60.96 + 20.32, 137.16, [("C601", "4.7u", "VBUS", "GND")])
    sh.note(101.6, 121.92, [
        "Sink: 5.1 kohm Rd on CC1 and CC2 (USB Type-C spec 4.11).",
        "D+/D- joined across the two rows (either plug orientation).",
        "USBLC6-2SC6 at the connector; D+/D- 90 ohm differential (DIFF_90).",
        "Shield to GND through R603 (0 ohm; swap for an RC if EMC needs).",
        "VBUS -> D204 (sheet 2): USB powers the logic without 24 V.",
    ])

    sh.box(210.82, 15.24, 405.13, 165.1, "Debug and user I/O")
    tc = sh.part("Connector:Conn_ARM_SWD_TagConnect_TC2030", "J602", "TC2030", (254.0, 60.96),
                 fp="Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical", in_bom=False)
    sh.nets(tc, {"1": "+3V3", "2": "SWDIO", "3": "NRST", "4": "SWCLK", "5": "GND", "6": "SWO"})
    led1 = sh.part("Device:LED", "D601", "green", (320.04, 50.8), rot=90, fp="LED_SMD:LED_0603_1608Metric",
                   lcsc="C12624", mpn="KT-0603G")
    sh.nets(led1, {"2": "LED_STATUS_A", "1": "GND"})
    led2 = sh.part("Device:LED", "D602", "red", (345.44, 50.8), rot=90, fp="LED_SMD:LED_0603_1608Metric",
                   lcsc="C2286", mpn="KT-0603R")
    sh.nets(led2, {"2": "LED_FAULT_A", "1": "GND"})
    row(sh, "R", 320.04, 86.36, [("R604", "1k", "LED_STATUS", "LED_STATUS_A"), ("R605", "1k", "LED_FAULT", "LED_FAULT_A")],
        pitch=25.4)
    sw = sh.part("Switch:SW_Push", "SW601", "BUTTON", (381.0, 116.84), fp="Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2",
                 lcsc="C318884", mpn="TS-1187A-B-A-B")
    sh.nets(sw, {"1": "BUTTON", "2": "GND"})
    row(sh, "R", 365.76, 147.32, [("R606", "10k", "+3V3", "BUTTON")])
    row(sh, "C", 391.16, 147.32, [("C602", "100n", "BUTTON", "GND")])
    sh.note(215.9, 109.22, [
        "TC2030 (no part on the board): SWD, NRST, SWO.",
        "LEDs: (3.3 V - 2.0 V) / 1 kohm = 1.3 mA (derived).",
        "Button: 10 kohm pull-up, 100 nF = 1 ms RC debounce.",
    ])

    sh.box(15.24, 175.26, 405.13, 254.0, "Mechanical")
    for i in range(4):
        sh.part("Mechanical:MountingHole", f"H60{i + 1}", "M3", (40.64 + i * 25.4, 205.74),
                fp="MountingHole:MountingHole_3.2mm_M3", in_bom=False)
    for i in range(3):
        sh.part("Mechanical:Fiducial", f"FID60{i + 1}", "Fiducial", (172.72 + i * 25.4, 205.74),
                fp="Fiducial:Fiducial_1mm_Mask2mm", in_bom=False)
    sh.note(254.0, 198.12, [
        "Four M3 holes, not plated, not on a net.",
        "Three fiducials for assembly (JLCPCB; pcb-placement dfa.py).",
    ])

    classes(sh, {"USB_CC1": "SIGNAL", "USB_SHIELD": "GND"})
