"""stepper-ble part helpers: every BOM line from the component list (docs/decisions.md D-002), with its footprint,
LCSC number, MPN and voltage rating, so a sheet names a part by its key and gets all fields."""

BOM = {
    "C100u50": ("100u", "Device:C_Polarized", "Capacitor_SMD:CP_Elec_8x10", "C72480", "RVT1H101M0810", "50V"),
    "C4u7_50": ("4.7u", "Device:C", "Capacitor_SMD:C_1206_3216Metric", "C51205", "CL31B475KBHNNNE", "50V"),
    "C100n": ("100n", "Device:C", "Capacitor_SMD:C_0402_1005Metric", "C1525", "CL05B104KO5NNNC", "16V"),
    "C1u": ("1u", "Device:C", "Capacitor_SMD:C_0402_1005Metric", "C16193167", "CL05A105KA5NNNC", "25V"),
    "C220n50": ("220n", "Device:C", "Capacitor_SMD:C_0603_1608Metric", "C64705", "CL10B224KB8NNNC", "50V"),
    "C22u": ("22u", "Device:C", "Capacitor_SMD:C_0805_2012Metric", "C5674", "CL21A226MQQNNNE", "6.3V"),
    "C4u7": ("4.7u", "Device:C", "Capacitor_SMD:C_0402_1005Metric", "C23733", "CL05A475MP5NRNC", "10V"),
    "C100n50": ("100n", "Device:C", "Capacitor_SMD:C_0603_1608Metric", "C1591", "CL10B104KB8NNNC", "50V"),
    "C1u50": ("1u", "Device:C", "Capacitor_SMD:C_0603_1608Metric", "C15849", "CL10A105KB8NNNC", "50V"),
    "C10n50": ("10n", "Device:C", "Capacitor_SMD:C_0402_1005Metric", "C15195", "CL05B103KB5NNNC", "50V"),
    "C1n": ("1n", "Device:C", "Capacitor_SMD:C_0402_1005Metric", "C14442", "CL05B102KB5NNNC", "50V"),
    "C100p": ("100p", "Device:C", "Capacitor_SMD:C_0402_1005Metric", "C1546", "0402CG101J500NT", "50V"),
    "C18p": ("18p", "Device:C", "Capacitor_SMD:C_0402_1005Metric", "C1549", "0402CG180J500NT", "50V"),
    "CDNP": ("DNP", "Device:C", "Capacitor_SMD:C_0402_1005Metric", "", "", ""),
    "SMAJ33A": ("SMAJ33A", "Diode:SMAJ33A", "Diode_SMD:D_SMA", "C353454", "SMAJ33A", ""),
    "BZT52C15": ("BZT52C15", "Device:D_Zener", "Diode_SMD:D_SOD-123", "C173427", "BZT52C15", ""),
    "SS34": ("SS34", "Diode:SS34", "Diode_SMD:D_SMA", "C8678", "SS34", ""),
    "LEDG": ("green", "Device:LED", "LED_SMD:LED_0603_1608Metric", "C12624", "KT-0603G", ""),
    "LEDR": ("red", "Device:LED", "LED_SMD:LED_0603_1608Metric", "C2286", "KT-0603R", ""),
    "FUSE": ("3A fast", "Device:Fuse", "Fuse:Fuse_Littelfuse-NANO2-451_453", "C13982", "0451003.MRL", "125V"),
    "MLPF": ("MLPF-WB55-01E3", "stepper-ble:MLPF-WB55-01E3", "stepper-ble:MLPF-WB55-01E3_CSP-6_1.0x1.6mm",
             "C2651048", "MLPF-WB55-01E3", ""),
    "J_IN": ("24V IN", "Connector:Screw_Terminal_01x02",
             "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
             "C480516", "1715721", ""),
    "J_MOT": ("MOTOR", "Connector:Screw_Terminal_01x04",
              "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal",
              "C5443561", "1715747", ""),
    "USBC": ("USB-C", "Connector:USB_C_Receptacle_USB2.0_16P",
             "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", "C165948", "TYPE-C-31-M-12", ""),
    "L22u": ("22u", "Device:L", "Inductor_SMD:L_Sunlord_SWPA4030S", "C83472", "SWPA4030S220MT", ""),
    "L2u2": ("2.2u", "Device:L", "Inductor_SMD:L_0805_2012Metric", "C98033", "LQM21PN2R2MC0D", ""),
    "L10n": ("10n", "Device:L", "Inductor_SMD:L_0402_1005Metric", "C3911026", "LQG15WZ10NJ02D", ""),
    "FET": ("CSD18543Q3A", "Transistor_FET:CSD18543Q3A", "stepper-ble:VSON-8_3.3x3.3mm_P0.65mm_NexFET_TI-land",
            "C840100", "CSD18543Q3A", "60V"),
    "R100k": ("100k", "Device:R", "Resistor_SMD:R_0402_1005Metric", "C25741", "0402WGF1003TCE", ""),
    "R10k": ("10k", "Device:R", "Resistor_SMD:R_0402_1005Metric", "C25744", "0402WGF1002TCE", ""),
    "R24k9": ("24.9k", "Device:R", "Resistor_SMD:R_0402_1005Metric", "C25874", "0402WGF2492TCE", ""),
    "R0R1": ("0.1", "Device:R", "Resistor_SMD:R_2512_6332Metric", "C25466", "25121WF100LT4E", ""),
    "R20k": ("20k", "Device:R", "Resistor_SMD:R_0402_1005Metric", "C25765", "0402WGF2002TCE", ""),
    "R0": ("0", "Device:R", "Resistor_SMD:R_0402_1005Metric", "C17168", "0402WGF0000TCE", ""),
    "R5k1": ("5.1k", "Device:R", "Resistor_SMD:R_0402_1005Metric", "C25905", "0402WGF5101TCE", ""),
    "R1k": ("1k", "Device:R", "Resistor_SMD:R_0402_1005Metric", "C11702", "0402WGF1001TCE", ""),
    "NTC": ("10k B3380", "Device:Thermistor_NTC", "Resistor_SMD:R_0402_1005Metric", "C77131", "NCP15XH103F03RC", ""),
    "BUTTON": ("BUTTON", "Switch:SW_Push", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "C318884",
               "TS-1187A-B-A-B", ""),
    "BUCK": ("LMR36510ADDA", "Regulator_Switching:LMR36510ADDA",
             "Package_SO:Texas_HTSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.4x3.1mm_ThermalVias",
             "C1858393", "LMR36510ADDAR", ""),
    "LDO": ("AP2112K-3.3", "Regulator_Linear:AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5", "C51118",
            "AP2112K-3.3TRG1", ""),
    "DRV8711": ("DRV8711", "stepper-ble:DRV8711",
                "Package_SO:HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm_ThermalVias", "C60013", "DRV8711DCPR", ""),
    "MCU": ("STM32WB55CGU6", "MCU_ST_STM32WB:STM32WB55CGUx",
            "Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.6x5.6mm_ThermalVias", "C404023", "STM32WB55CGU6", ""),
    "ESD": ("USBLC6-2SC6", "Power_Protection:USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", "C7519", "USBLC6-2SC6", ""),
    "X32M": ("32MHz", "Device:Crystal_GND24", "Crystal:Crystal_SMD_2016-4Pin_2.0x1.6mm", "C1986260",
             "NX2016SA-32M-EXS00A-CS06465", ""),
    "X32k": ("32.768kHz", "Device:Crystal", "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm", "C32346", "Q13FC13500004", ""),
}


def part(sh, key, ref, at, rot=0, value=None, mirror=None, **fields):
    """Place BOM line `key` as `ref` at `at` (schgen coordinates, mm)."""
    v, lib, fp, lcsc, mpn, volts = BOM[key]
    if volts:
        fields.setdefault("Voltage", volts)
    dnp = key == "CDNP"
    return sh.part(lib, ref, value or v, at, rot=rot, fp=fp, lcsc=lcsc, mpn=mpn, dnp=dnp, in_bom=not dnp,
                   mirror=mirror, **fields)


def special(sh, lib, ref, value, at, fp, rot=0, **fields):
    """A part with no BOM line: copper-only or mechanical (antenna, Tag-Connect land, holes, fiducials, net ties)."""
    return sh.part(lib, ref, value, at, rot=rot, fp=fp, in_bom=False, **fields)


def shunt(sh, p, top, bottom="GND"):
    """A vertical two-pin part between `top` (pin 1) and `bottom` (pin 2), each as a stub with a power symbol or
    label."""
    sh.net(p["1"], top)
    sh.net(p["2"], bottom)
    return p
