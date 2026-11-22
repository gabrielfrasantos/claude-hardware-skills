"""Sheet 2: input protection, motor supply, 5 V buck, 3.3 V LDO."""
from sch import Sheet

from parts import classes, row


def build(project, values):
    sh = Sheet(project, 2, "power", "Power")
    sh.desc = ["24 V input: fuse, reverse-polarity N-FET, TVS, bulk", "LMR36510 buck to 5 V, OR-ed with USB VBUS",
               "AP2112K LDO to 3.3 V", "VM sense divider for the ADC"]

    # --- input protection -------------------------------------------------------------------------------------
    sh.box(15.24, 15.24, 200.66, 135.89, "Input protection and motor supply (VM)")
    j = sh.part("Connector:Screw_Terminal_01x02", "J201", "24V IN", (30.48, 60.96),
                fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
                lcsc="C480516", mpn="1715721")
    sh.nets(j, {"1": "VIN_RAW", "2": "GND_IN"})
    f = sh.part("Device:Fuse", "F201", "3A fast", (60.96, 45.72), fp="Fuse:Fuse_Littelfuse-NANO2-451_453",
                lcsc="C13982", mpn="0451003.MRL")
    sh.nets(f, {"1": "VIN_RAW", "2": "VM"})
    q = sh.part("Transistor_FET:CSD18543Q3A", "Q201", "CSD18543Q3A", (88.9, 81.28),
                fp="Package_SON:VSON-8_3.3x3.3mm_P0.65mm_NexFET", lcsc="C840100", mpn="CSD18543Q3A")
    sh.nets(q, {"1": "GND", "2": "GND", "3": "GND", "4": "Q201_G", "5": "GND_IN"})
    d = sh.part("Diode:BZT52Bxx", "D202", "BZT52C15", (114.3, 81.28), rot=90,
                fp="Diode_SMD:D_SOD-123", lcsc="C173427", mpn="BZT52C15")
    sh.nets(d, {"1": "Q201_G", "2": "GND"})
    tvs = sh.part("Diode:SMAJ33A", "D201", "SMAJ33A", (139.7, 50.8), rot=90,
                  fp="Diode_SMD:D_SMA", lcsc="C353454", mpn="SMAJ33A")
    sh.nets(tvs, {"1": "VM", "2": "GND"})
    bulk = sh.part("Device:C_Polarized", "C201", "100u 50V", (165.1, 50.8), fp="Capacitor_SMD:CP_Elec_8x10",
                   lcsc="C72480", mpn="RVT1H101M0810")
    sh.nets(bulk, {"1": "VM", "2": "GND"})
    row(sh, "R", 30.48, 106.68, [("R201", "100k", "VM", "Q201_G")])
    row(sh, "C", 50.8, 106.68, [("C202", "4.7u 50V", "VM", "GND")])
    row(sh, "R", 139.7, 106.68, [("R202", "100k", "VM", "VM_SENSE"), ("R203", "10k", "VM_SENSE", "GND")])
    row(sh, "C", 160.02, 106.68, [("C203", "100n", "VM_SENSE", "GND")])
    sh.flag("VM", (185.42, 30.48))
    sh.flag("GND", (185.42, 76.2))
    sh.note(20.32, 116.84, [
        "Input 24 V nominal, 30 V max (HW-PWR-001). Every part on VM is rated >= 52 V: DRV8711 VM 8-52 V (SLVSC40H 6.3),",
        "LMR36510 4.2-65 V (SNVSBD7B 1), CSD18543Q3A 60 V (SLPS633 1).",
        "F201 3 A fast (Littelfuse 451): the motor supply's design current, sets VM's class PWR_3A.",
        "Q201: reverse polarity in the return leg; body diode conducts first, R201/D202 then enhance it; D202 clamps",
        "VGS to 15 V (CSD18543Q3A VGS max +-20 V). Reversed input: body diode blocks, VGS < 0.",
        "D201 SMAJ33A: VRWM 33 V above the 30 V max input, VC 53.3 V below the 60 V FET rating (ASSUMPTION: VC at 7.5 A).",
        "C201 100 uF + C202 4.7 uF: DRV8711 bulk, SLVSC40H 9.1 and Pin Functions (VM: 0.01 uF + 100 uF).",
        "VM_SENSE = VM * 10k / 110k: 30 V -> 2.73 V, under VDDA 3.3 V (derived). C203 with R202||R203 = 9.1 kohm: fc 175 Hz.",
    ])

    # --- 5 V buck -----------------------------------------------------------------------------------------------
    sh.box(210.82, 15.24, 405.13, 135.89, "5 V buck (LMR36510, SNVSBD7B 8.2 Design 1)")
    u = sh.part("Regulator_Switching:LMR36510ADDA", "U201", "LMR36510ADDA", (271.78, 60.96),
                fp="Package_SO:Texas_HTSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.4x3.1mm_ThermalVias",
                lcsc="C1858393", mpn="LMR36510ADDAR")
    sh.nets(u, {"1": "GND", "2": "VM", "3": "VM", "4": "PG_5V", "5": "BUCK_FB", "6": "BUCK_VCC", "7": "BUCK_BOOT",
                "8": "BUCK_SW", "9": "GND"})
    l = sh.part("Device:L", "L201", "22u", (340.36, 45.72), fp="Inductor_SMD:L_Sunlord_SWPA4030S",
                lcsc="C83472", mpn="SWPA4030S220MT")
    sh.nets(l, {"1": "BUCK_SW", "2": "+5V_BUCK"})
    d3 = sh.part("Diode:SS34", "D203", "SS34", (370.84, 45.72), rot=90, fp="Diode_SMD:D_SMA",
                 lcsc="C8678", mpn="SS34")
    sh.nets(d3, {"2": "+5V_BUCK", "1": "+5V"})
    d4 = sh.part("Diode:SS34", "D204", "SS34", (370.84, 76.2), rot=90, fp="Diode_SMD:D_SMA",
                 lcsc="C8678", mpn="SS34")
    sh.nets(d4, {"2": "VBUS", "1": "+5V"})
    row(sh, "C", 226.06, 106.68, [("C206", "4.7u 50V", "VM", "GND"), ("C207", "220n 50V", "VM", "GND"),
                                  ("C204", "1u", "BUCK_VCC", "GND"), ("C205", "100n", "BUCK_BOOT", "BUCK_SW")])
    row(sh, "R", 270.51, 106.68, [("R204", "100k", "+5V_BUCK", "BUCK_FB"), ("R205", "24.9k", "BUCK_FB", "GND"),
                                  ("R206", "100k", "+3V3", "PG_5V")])
    row(sh, "C", 304.8, 106.68, [("C208", "22u", "+5V_BUCK", "GND"), ("C209", "22u", "+5V_BUCK", "GND")])
    sh.note(332.74, 96.52, [
        "Table 8-1, 400 kHz, VOUT 5 V: L 22 uH,",
        "COUT 2 x 22 uF, RFBT 100k, RFBB 24.9k,",
        "CIN 2.2 uF + 220 nF (4.7 uF used, 50 V).",
        "VOUT = 1.0 V * (1 + 100k/24.9k) = 5.02 V.",
        "EN tied to VIN (Pin Functions, EN).",
        "PG open drain to +3V3 (MCU input).",
        "D203/D204: OR with USB VBUS; ~0.4 V drop.",
        "ASSUMPTION: L201 Isat >= 1 A (SWPA4030).",
    ])

    # --- 3.3 V LDO ----------------------------------------------------------------------------------------------
    sh.box(15.24, 146.05, 200.66, 280.67, "3.3 V LDO (AP2112K-3.3)")
    ldo = sh.part("Regulator_Linear:AP2112K-3.3", "U202", "AP2112K-3.3", (76.2, 190.5),
                  fp="Package_TO_SOT_SMD:SOT-23-5", lcsc="C51118", mpn="AP2112K-3.3TRG1")
    sh.nets(ldo, {"1": "+5V", "2": "GND", "3": "+5V", "4": None, "5": "+3V3"})
    row(sh, "C", 30.48, 236.22, [("C210", "1u", "+5V", "GND"), ("C211", "1u", "+3V3", "GND"),
                                 ("C212", "4.7u", "+3V3", "GND")])
    sh.flag("+5V", (139.7, 170.18))
    sh.note(101.6, 228.6, [
        "AP2112K: 600 mA, 1 uF in and out (Diodes AP2112 datasheet).",
        "Input +5V minus one Schottky: >= 4.5 V,",
        "above 3.3 V + 400 mV dropout (ASSUMPTION: at 600 mA).",
        "Load: STM32WB55 + LEDs, under 100 mA (ASSUMPTION).",
        "C212: the 4.7 uF bulk of DS11929 Fig. 16 (VDD).",
    ])

    classes(sh, {
        "VIN_RAW": "PWR_3A_30V", "VM": "PWR_3A_30V", "GND_IN": "GND_3A", "GND": "GND",
        "BUCK_SW": "PWR_1A_30V", "BUCK_BOOT": "SIGNAL_30V", "+5V_BUCK": "PWR_0p5A", "+5V": "PWR_0p5A",
        "VBUS": "PWR_0p5A", "+3V3": "PWR_0p5A", "VM_SENSE": "ANALOG", "Q201_G": "SIGNAL",
    })
