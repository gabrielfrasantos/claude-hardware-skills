"""Sheet 4: MCU. STM32WB55CGU6 in SMPS mode, clocks, reset/boot, analog inputs (mcu-circuit-design, DS11929)."""
import os

from sch import Sheet, load_pinmap
from parts import part

PINMAP = os.path.join(os.path.dirname(__file__), "..", "..", "..", "pin-data", "pinmap.txt")


def decoupling(sh):
    sh.box(20.32, 30.48, 144.78, 66.04, "Supply-pin decoupling, one per pin (DS11929 Fig. 16, mcu-circuit-design §2)")
    caps = [("C401", "C100n", "VDD pin 20"), ("C402", "C100n", "VDD pin 35"), ("C403", "C100n", "VDD pin 48"),
            ("C404", "C4u7", "VDD bulk"), ("C405", "C100n", "VBAT pin 1"), ("C406", "C100n", "VDDUSB pin 40"),
            ("C407", "C100n", "VDDRF pin 23"), ("C408", "C100p", "VDDRF pin 23"), ("C409", "C4u7", "VDDSMPS 34")]
    parts = []
    for i, (ref, key, _) in enumerate(caps):
        c = part(sh, key, ref, (33.02 + i * 12.7, 53.34))
        sh.net(c["2"], "GND")
        parts.append(c)
    sh.rail("+3V3", 45.72, [c["1"] for c in parts], tap=(27.94, (0, -1)))

    sh.box(147.32, 30.48, 205.74, 66.04, "VDDA filter (DS11929 Fig. 16)")
    r = part(sh, "R0", "R401", (160.02, 45.72), rot=90)
    sh.path("+3V3", [(151.13, 45.72), r["1"]])
    sh.label("+3V3", (151.13, 45.72), (0, -1))
    c1 = part(sh, "C1u", "C410", (172.72, 49.53))
    c2 = part(sh, "C10n50", "C411", (185.42, 49.53))
    fl = sh.flag("VDDA", (167.64, 45.72), label=False)
    sh.rail("VDDA", 45.72, [r["2"], fl["1"], c1["1"], c2["1"]], tap=(195.58, (0, -1)))
    sh.net(c1["2"], "GND")
    sh.net(c2["2"], "GND")


def smps_and_clocks(sh):
    sh.box(20.32, 71.12, 99.06, 101.6, "SMPS, 8 MHz (DS11929 Table 6)")
    l1 = part(sh, "L2u2", "L401", (43.18, 83.82), rot=90)
    l2 = part(sh, "L10n", "L402", (63.5, 83.82), rot=90)
    c = part(sh, "C4u7", "C412", (78.74, 87.63))
    fl = sh.flag("SMPS_LX", (35.56, 83.82), label=False)
    sh.path("SMPS_LX", [(30.48, 83.82), fl["1"], l1["1"]])
    sh.label("SMPS_LX", (30.48, 83.82), (-1, 0))
    sh.link(l1["2"], l2["1"], "SMPS_MID")
    sh.label("SMPS_MID", (53.34, 83.82), (0, 1))
    sh.rail("VFBSMPS", 83.82, [l2["2"], c["1"]], label="right", ext=10.16)
    sh.net(c["2"], "GND")

    sh.box(104.14, 71.12, 160.02, 101.6, "HSE 32 MHz (DS11929 6.3.10)")
    y = part(sh, "X32M", "Y401", (132.08, 83.82))
    sh.net(y["1"], "HSE_IN")
    sh.net(y["3"], "HSE_OUT")
    sh.nets(y, {"2": "GND", "4": "GND"})

    sh.box(20.32, 106.68, 160.02, 142.24, "LSE 32.768 kHz (DS11929 Table 57, AN2867)")
    y2 = part(sh, "X32k", "Y402", (91.44, 116.84))
    c1 = part(sh, "C18p", "C413", (73.66, 121.92))
    c2 = part(sh, "C18p", "C414", (109.22, 121.92))
    sh.rail("LSE_IN", 116.84, [c1["1"], y2["1"]], label="left", ext=7.62)
    sh.rail("LSE_OUT", 116.84, [y2["2"], c2["1"]], label="right", ext=7.62)
    sh.net(c1["2"], "GND")
    sh.net(c2["2"], "GND")


def reset_boot_analog(sh):
    sh.box(20.32, 147.32, 160.02, 180.34, "Reset and boot (mcu-circuit-design §3)")
    c = part(sh, "C100n", "C415", (40.64, 167.64))
    sh.net(c["1"], "NRST")
    sh.net(c["2"], "GND")
    r = part(sh, "R10k", "R402", (71.12, 167.64))
    sh.net(r["1"], "BOOT0")
    sh.net(r["2"], "GND")

    sh.box(20.32, 182.88, 160.02, 233.68, "Analog inputs: bias at the ADC pin (pcb-placement §1)")
    rn = part(sh, "R10k", "R403", (40.64, 200.66))
    sh.net(rn["1"], "VDDA")
    sh.net(rn["2"], "NTC_SENSE")


def build(project, values):
    sh = Sheet(project, 4, "mcu", "MCU")
    sh.desc = ["U401 STM32WB55CGU6, SMPS mode", "HSE 32 MHz, LSE 32.768 kHz", "Reset, BOOT0, ADC inputs",
               "I/O by pin map (pin-data/pinmap.txt)"]
    decoupling(sh)
    smps_and_clocks(sh)
    reset_boot_analog(sh)

    u = part(sh, "MCU", "U401", (203.2, 142.24))
    sh.box(161.29, 78.74, 248.92, 195.58, "STM32WB55CGU6 (UFQFPN48)")
    sh.rail("+3V3", 96.52, [u["1"], u["20"], u["35"], u["48"]], tap=(199.39, (0, -1)))
    sh.rail("+3V3", 96.52, [u["23"], u["34"], u["40"]], tap=(212.09, (0, -1)))
    sh.net(u["8"], "VDDA")
    sh.rail("GND", 187.96, [u["49"], u["22"], u["32"]], tap=(203.2, (0, 1)))
    sh.nets(u, {"7": "NRST", "33": "SMPS_LX", "25": "HSE_IN", "24": "HSE_OUT", "31": "VFBSMPS", "21": "RF_IN",
                "4": "BOOT0", "2": "LSE_IN", "3": "LSE_OUT"})
    pinmap = load_pinmap(PINMAP) if os.path.exists(PINMAP) else {}
    sh.assign_pins(u, pinmap)
    sh.nc_unused(u, r"^P[A-Z][0-9]+$")

    sh.note(254.0, 35.56, [
        "U401 STM32WB55CGU6, DS11929 Rev 11. Supplies (§3.7.2, Fig. 16): VDD, VDDRF, VDDSMPS wired together",
        "  to +3V3; n x 100 nF + 4.7 uF on VDD; VDDRF 100 nF + 100 pF; VDDA 10 nF + 1 uF; VDDUSB 100 nF;",
        "  VBAT tied to VDD with 100 nF (no battery, mcu-circuit-design §2). Each capacitor at its own pin.",
        "SMPS mode, 8 MHz (Table 6): L1 2.2 uH (L401) + 10 nH in series (L402, LQG15WZ10NJ02D, note 2),",
        "  C 4.7 uF on VFBSMPS (C412); VDDSMPS 4.7 uF (C409). AN5165: inductor orthogonal to RF lines.",
        "HSE (Table 54): NX2016SA 32 MHz, ESR 50 ohm <= 100 ohm; its CL 10 pF is above the WB's 6-8 pF,",
        "  pulling 8.41 ppm/pF -> ~+17 ppm, inside the XOTUNE range +-20..40 ppm: trim per AN5042 at",
        "  bring-up with a counter (D-006, B4). Budget: +-10 initial, +-30 temp (-40..85), +-3 aging, trimmed.",
        "LSE: FC-135 CL 12.5 pF, ESR 70 kOhm, C0 1 pF. C = 2 x (CL - Cs) = 2 x (12.5 - 3.5) = 18 pF, with",
        "  Cs 3.5 pF total stray (ASSUMPTION, AN2867 convention: total, both pins). gmcrit =",
        "  4 x 70k x (2 pi 32768)^2 x (1 + 12.5 pF)^2 = 2.16 uA/V: needs LSEDRV = 11 (Gmcritmax 2.7 uA/V).",
        "NRST: internal pull-up, 100 nF only (mcu-circuit-design §3). BOOT0 (PH3) 10k to GND: boots from flash;",
        "  the bootloader is reached over SWD (option bytes) or USB DFU by firmware.",
        "VM_SENSE: divider R102/R103 on sheet 1, placed at its ADC pin (pcb-placement §1).",
        "NTC_SENSE: R403 10k from VDDA (the ADC reference) to TH301: ratiometric, 1.65 V at 25 C.",
        "I/O: each function net gets its pin from pins.py after placement (pin-data/pinmap.txt, D-014).",
    ])
    for n, c in (("SMPS_LX", "PWR_0p5A"), ("SMPS_MID", "PWR_0p5A"), ("VFBSMPS", "PWR_0p5A"), ("VDDA", "PWR_0p5A"),
                 ("HSE_IN", "CLK"), ("HSE_OUT", "CLK"), ("LSE_IN", "CLK"), ("LSE_OUT", "CLK"),
                 ("NRST", "SIGNAL"), ("BOOT0", "SIGNAL"), ("+3V3", "PWR_0p5A"),
                 ("GND", "GND")):
        sh.netclass(n, c)
    sh.class_table(254.0, 182.88, rows=7)
