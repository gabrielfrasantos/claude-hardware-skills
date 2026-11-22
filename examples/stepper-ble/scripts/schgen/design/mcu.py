"""Sheet 4: STM32WB55CG with its supplies, SMPS, clocks, reset and boot. Function pins come from the pin map."""
import pathlib

from sch import Sheet, load_pinmap

from parts import classes, row

PINMAP = pathlib.Path(__file__).resolve().parents[3] / "pin-data" / "pinmap.txt"


def build(project, values):
    sh = Sheet(project, 4, "mcu", "MCU")
    sh.desc = ["STM32WB55CGU6, SMPS mode (2.2 uH + 10 nH)", "32 MHz HSE, 32.768 kHz LSE", "Function pins from pin-data/pinmap.txt"]

    sh.box(15.24, 15.24, 241.3, 200.66, "STM32WB55CGU6 (ST DS11929 Rev 11)")
    u = sh.part("MCU_ST_STM32WB:STM32WB55CGUx", "U401", "STM32WB55CGU6", (127.0, 106.68),
                fp="Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.6x5.6mm", lcsc="C404023", mpn="STM32WB55CGU6")
    sh.nets(u, {
        "1": "+3V3", "8": "+3V3", "20": "+3V3", "35": "+3V3", "48": "+3V3", "40": "+3V3", "23": "+3V3", "34": "+3V3",
        "22": "GND", "32": "GND", "49": "GND",
        "33": "SMPS_LX", "31": "SMPS_FB",
        "7": "NRST", "4": "BOOT0", "24": "HSE_OUT", "25": "HSE_IN", "2": "LSE_IN", "3": "LSE_OUT",
        "21": "RF1", "26": None, "27": None,
        "37": "USB_DM", "38": "USB_DP", "39": "SWDIO", "41": "SWCLK", "43": "SWO",
    })
    if PINMAP.exists():
        sh.assign_pins(u, load_pinmap(PINMAP))
    sh.nc_unused(u, r"^P[A-Z][0-9]+$")
    sh.flag("SMPS_LX", (180.34, 132.08))

    row(sh, "C", 30.48, 172.72, [
        ("C401", "4.7u", "+3V3", "GND"), ("C402", "100n", "+3V3", "GND"), ("C403", "100n", "+3V3", "GND"),
        ("C404", "100n", "+3V3", "GND"), ("C405", "1u", "+3V3", "GND"), ("C406", "10n 50V", "+3V3", "GND"),
        ("C407", "100n", "+3V3", "GND"), ("C408", "100p", "+3V3", "GND"), ("C409", "4.7u", "+3V3", "GND"),
        ("C410", "4.7u", "SMPS_FB", "GND"), ("C411", "100n", "NRST", "GND")])
    row(sh, "R", 147.32, 172.72, [("R401", "10k", "BOOT0", "GND")])
    l1 = sh.part("Device:L", "L401", "2.2u", (198.12, 152.4), fp="Inductor_SMD:L_0805_2012Metric",
                 lcsc="C98033", mpn="LQM21PN2R2MC0D")
    sh.nets(l1, {"1": "SMPS_LX", "2": "SMPS_L"})
    l2 = sh.part("Device:L", "L402", "10n", (218.44, 152.4), fp="Inductor_SMD:L_0402_1005Metric",
                 lcsc="C3911026", mpn="LQG15WZ10NJ02D")
    sh.nets(l2, {"1": "SMPS_L", "2": "SMPS_FB"})
    sh.note(20.32, 22.86, [
        "Supplies per DS11929 Fig. 16: VDD n x 100 nF + 4.7 uF (C401-C404); VDDA 10 nF + 1 uF (C405, C406);",
        "VDDRF 100 nF + 100 pF (C407, C408); VDDSMPS 4.7 uF (C409); VFBSMPS 4.7 uF (C410); VBAT and VDDUSB on +3V3.",
        "SMPS at 8 MHz: L1 2.2 uH (Table 6) plus the 10 nH series inductor of note 2 (LQG15WZ10NJ02D, as named there).",
        "AT0/AT1: reserved, must be kept unconnected (pin table note 7). BOOT0 pulled down: boot from flash.",
        "NRST 100 nF to GND (ASSUMPTION: ST's usual value; the pin has its internal pull-up).",
    ])

    sh.box(251.46, 15.24, 405.13, 120.65, "Clocks")
    y1 = sh.part("Device:Crystal_GND24", "Y401", "32MHz", (294.64, 60.96), fp="Crystal:Crystal_SMD_2016-4Pin_2.0x1.6mm",
                 lcsc="C1986260", mpn="NX2016SA-32M-EXS00A-CS06465")
    sh.nets(y1, {"1": "HSE_IN", "3": "HSE_OUT", "2": "GND", "4": "GND"})
    y2 = sh.part("Device:Crystal", "Y402", "32.768kHz", (350.52, 60.96), fp="Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm",
                 lcsc="C32346", mpn="Q13FC13500004")
    sh.nets(y2, {"1": "LSE_IN", "2": "LSE_OUT"})
    row(sh, "C", 340.36, 91.44, [("C412", "18p", "LSE_IN", "GND"), ("C413", "18p", "LSE_OUT", "GND")])
    sh.note(256.54, 96.52, [
        "HSE: NX2016SA 32 MHz, the crystal DS11929 Table 5 names; load caps are on-chip (HSETUNE).",
        "ASSUMPTION: CS06465 (CL 10 pF) instead of ST's CS06654; trim HSETUNE at bring-up.",
        "LSE: FC-135, CL 12.5 pF: C = 2 (CL - Cstray) = 2 (12.5 - 3.5) = 18 pF (derived; Cstray ASSUMPTION).",
    ])

    classes(sh, {"SMPS_LX": "PWR_0p5A", "SMPS_L": "PWR_0p5A", "SMPS_FB": "PWR_0p5A",
                 "HSE_IN": "CLK", "HSE_OUT": "CLK", "LSE_IN": "CLK", "LSE_OUT": "CLK", "RF1": "RF_50",
                 "USB_DP": "DIFF_90", "USB_DM": "DIFF_90"})
