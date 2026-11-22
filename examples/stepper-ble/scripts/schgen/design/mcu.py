"""Sheet 4: STM32WB55CG with its supplies, SMPS, clocks, reset and boot. Function pins come from the pin map."""
import pathlib

from sch import Sheet, load_pinmap

from parts import classes, series, shunt

PINMAP = pathlib.Path(__file__).resolve().parents[3] / "pin-data" / "pinmap.txt"


def g(n):
    return round(n * 2.54, 2)


def build(project, values):
    sh = Sheet(project, 4, "mcu", "MCU")
    sh.desc = ["STM32WB55CGU6, SMPS mode (2.2 uH + 10 nH)", "32 MHz HSE, 32.768 kHz LSE", "Function pins from pin-data/pinmap.txt"]

    sh.box(g(6), g(6), g(96), g(108), "STM32WB55CGU6 (ST DS11929 Rev 11)")
    u = sh.part("MCU_ST_STM32WB:STM32WB55CGUx", "U401", "STM32WB55CGU6", (g(60), g(56)),
                fp="Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.6x5.6mm", lcsc="C404023", mpn="STM32WB55CGU6")
    supply = [u[n] for n in ("1", "20", "35", "48", "8", "23", "34", "40")]
    decap = [("C401", "4.7u"), ("C402", "100n"), ("C403", "100n"), ("C404", "100n"), ("C405", "1u"),
             ("C407", "100n"), ("C408", "100p"), ("C409", "4.7u"), ("C406", "10n 50V")]
    caps = [shunt(sh, ref, value, g(10 + 5 * i), g(32)) for i, (ref, value) in enumerate(decap)]
    sh.rail("+3V3", g(32), [c["1"] for c in caps] + supply, tap=(g(8), (0, -1)))
    sh.rail("GND", g(74), [u["49"], u["22"], u["32"]], tap=(g(60), (0, 1)))

    l401 = series(sh, "L401", "2.2u L", g(42), g(45), flip=True)
    l402 = series(sh, "L402", "10n L", g(34), g(45), flip=True)
    sh.link(u["33"], l401["1"], "SMPS_LX")
    sh.link(l401["2"], l402["1"], "SMPS_L")
    c410 = shunt(sh, "C410", "4.7u", g(38), g(50))
    sh.path("SMPS_FB", [l402["2"], (g(32), g(45)), (g(32), g(50))])
    sh.rail("SMPS_FB", g(50), [(g(32), g(50)), c410["1"], u["31"]])
    flag = sh.flag("SMPS_LX", (g(49), g(42)), label=False)
    sh.path("SMPS_LX", [flag["1"], (flag["1"].x, g(45))])

    sh.nets(u, {"7": "NRST", "4": "BOOT0", "25": "HSE_IN", "24": "HSE_OUT", "2": "LSE_IN", "3": "LSE_OUT",
                "21": "RF1", "26": None, "27": None,
                "37": "USB_DM", "38": "USB_DP", "39": "SWDIO", "41": "SWCLK", "43": "SWO"})
    if PINMAP.exists():
        sh.assign_pins(u, load_pinmap(PINMAP))
    sh.nc_unused(u, r"^P[A-Z][0-9]+$")

    y401 = sh.part("Device:Crystal_GND24", "Y401", "32MHz", (g(20), g(84)), fp="Crystal:Crystal_SMD_2016-4Pin_2.0x1.6mm",
                   lcsc="C1986260", mpn="NX2016SA-32M-EXS00A-CS06465")
    sh.nets(y401, {"1": "HSE_IN", "3": "HSE_OUT", "2": "GND", "4": "GND"})
    y402 = sh.part("Device:Crystal", "Y402", "32.768kHz", (g(42), g(84)), fp="Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm",
                   lcsc="C32346", mpn="Q13FC13500004")
    c412 = shunt(sh, "C412", "18p", g(35), g(84))
    c413 = shunt(sh, "C413", "18p", g(49), g(84))
    sh.rail("LSE_IN", g(84), [c412["1"], y402["1"]], label="left")
    sh.rail("LSE_OUT", g(84), [y402["2"], c413["1"]], label="right")
    c411 = shunt(sh, "C411", "100n", g(62), g(84))
    sh.net(c411["1"], "NRST")
    r401 = shunt(sh, "R401", "10k", g(70), g(84))
    sh.net(r401["1"], "BOOT0")

    sh.note(g(8), g(96), [
        "Supplies per DS11929 Fig. 16: VDD n x 100 nF + 4.7 uF (C401-C404); VDDA 10 nF + 1 uF (C405, C406);",
        "VDDRF 100 nF + 100 pF (C407, C408); VDDSMPS 4.7 uF (C409); VFBSMPS 4.7 uF (C410); VBAT, VDDUSB on +3V3.",
        "SMPS at 8 MHz: 2.2 uH (Table 6) plus the 10 nH series inductor of its note 2 (LQG15WZ10NJ02D).",
        "AT0/AT1 reserved, kept unconnected (pin table note 7). BOOT0 pulled down: boot from flash.",
        "HSE: NX2016SA 32 MHz (Table 5), load caps on-chip (HSETUNE); ASSUMPTION: CS06465 (CL 10 pF), not CS06654.",
        "LSE: FC-135, CL 12.5 pF: C = 2 (CL - Cstray) = 18 pF (derived; Cstray 3.5 pF ASSUMPTION).",
        "NRST 100 nF (ASSUMPTION: ST's usual value; internal pull-up).",
    ])

    sh.class_table(g(98), g(6), rows=14)
    classes(sh, {"SMPS_LX": "PWR_0p5A", "SMPS_L": "PWR_0p5A", "SMPS_FB": "PWR_0p5A",
                 "HSE_IN": "CLK", "HSE_OUT": "CLK", "LSE_IN": "CLK", "LSE_OUT": "CLK", "RF1": "RF_50",
                 "USB_DP": "DIFF_90", "USB_DM": "DIFF_90"})
