"""Sheet 3: DRV8711 stepper pre-driver, two external N-FET H-bridges, sense resistors, motor connector."""
from sch import Sheet

from parts import classes, row

FET = dict(fp="Package_SON:VSON-8_3.3x3.3mm_P0.65mm_NexFET", lcsc="C840100", mpn="CSD18543Q3A")


def fet(sh, ref, at, drain, source, gate):
    q = sh.part("Transistor_FET:CSD18543Q3A", ref, "CSD18543Q3A", at, **FET)
    sh.nets(q, {"1": source, "2": source, "3": source, "4": gate, "5": drain})
    return q


def build(project, values):
    sh = Sheet(project, 3, "motor", "Stepper driver")
    sh.desc = ["DRV8711 (SPI, indexer, stall detect)", "Two H-bridges of CSD18543Q3A, 0.1 ohm sense", "Motor terminal"]

    sh.box(15.24, 15.24, 200.66, 215.9, "DRV8711 (TI SLVSC40H)")
    u = sh.part("stepper-ble:DRV8711", "U301", "DRV8711", (101.6, 106.68),
                fp="Package_SO:HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm_ThermalVias",
                lcsc="C60013", mpn="DRV8711DCPR")
    sh.nets(u, {
        "4": "VM", "1": "DRV_CP1", "2": "DRV_CP2", "3": "DRV_VCP", "6": "DRV_V5", "7": "DRV_VINT",
        "8": "DRV_SLEEPn", "9": "DRV_RESET", "10": "DRV_STEP", "11": "DRV_DIR", "12": "GND", "13": "GND",
        "14": "DRV_SCLK", "15": "DRV_SDATI", "16": "DRV_SCS", "17": "DRV_SDATO", "18": "DRV_FAULTn",
        "19": "DRV_STALLn", "20": "DRV_BEMF",
        "36": "A1HS", "37": "AOUT1", "35": "A1LS", "31": "A2HS", "30": "AOUT2", "32": "A2LS", "34": "ISENA", "33": "GND",
        "27": "B1HS", "28": "BOUT1", "26": "B1LS", "22": "B2HS", "21": "BOUT2", "23": "B2LS", "25": "ISENB", "24": "GND",
        "5": "GND", "29": "GND", "38": "GND", "39": "GND"})
    row(sh, "C", 25.4, 185.42, [
        ("C301", "100n 50V", "DRV_CP1", "DRV_CP2"), ("C302", "1u 50V", "DRV_VCP", "VM"), ("C303", "100n", "DRV_V5", "GND"),
        ("C304", "1u", "DRV_VINT", "GND"), ("C305", "10n 50V", "VM", "GND"), ("C308", "1n", "DRV_BEMF", "GND")])
    row(sh, "R", 99.06, 185.42, [
        ("R303", "10k", "+3V3", "DRV_SDATO"), ("R304", "10k", "+3V3", "DRV_FAULTn"), ("R305", "10k", "+3V3", "DRV_STALLn"),
        ("R306", "100k", "DRV_SLEEPn", "GND"), ("R307", "10k", "DRV_BEMF", "BEMF_ADC"), ("R308", "20k", "BEMF_ADC", "GND")])
    sh.note(20.32, 22.86, [
        "Pin Functions (SLVSC40H 5): CP1-CP2 0.1 uF rated > VM; VCP 1 uF to VM; V5 0.1 uF; VINT 1 uF;",
        "VM 0.01 uF + bulk (sheet 2); BEMF 1 nF low-leakage; SDATO, FAULTn, STALLn open drain: pull-ups.",
        "Logic VIH 1.5 V (6.5): 3.3 V MCU drives it directly. BIN1/BIN2 unused in indexer mode: tied to GND.",
        "R306 holds SLEEPn low (outputs off) until the MCU drives it.",
        "BEMF -> ADC through 10k/20k: 5 V -> 3.33 V (derived); ASSUMPTION: BEMF output <= V5 and drives 30 kohm.",
    ])

    sh.box(210.82, 15.24, 405.13, 215.9, "H-bridges and current sense")
    fet(sh, "Q301", (236.22, 50.8), "VM", "AOUT1", "A1HS")
    fet(sh, "Q302", (236.22, 101.6), "AOUT1", "ISENA", "A1LS")
    fet(sh, "Q303", (271.78, 50.8), "VM", "AOUT2", "A2HS")
    fet(sh, "Q304", (271.78, 101.6), "AOUT2", "ISENA", "A2LS")
    fet(sh, "Q305", (312.42, 50.8), "VM", "BOUT1", "B1HS")
    fet(sh, "Q306", (312.42, 101.6), "BOUT1", "ISENB", "B1LS")
    fet(sh, "Q307", (347.98, 50.8), "VM", "BOUT2", "B2HS")
    fet(sh, "Q308", (347.98, 101.6), "BOUT2", "ISENB", "B2LS")
    row(sh, "R", 236.22, 147.32, [("R301", "0.1R 1W", "ISENA", "GND")])
    row(sh, "R", 312.42, 147.32, [("R302", "0.1R 1W", "ISENB", "GND")])
    row(sh, "C", 271.78, 147.32, [("C306", "4.7u 50V", "VM", "GND")])
    row(sh, "C", 347.98, 147.32, [("C307", "4.7u 50V", "VM", "GND")])
    j = sh.part("Connector:Screw_Terminal_01x04", "J301", "MOTOR", (386.08, 76.2),
                fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal",
                lcsc="C5443561", mpn="1715747")
    sh.nets(j, {"1": "AOUT1", "2": "AOUT2", "3": "BOUT1", "4": "BOUT2"})
    nt = sh.part("Device:Thermistor_NTC", "RT301", "10k B3380", (386.08, 147.32), fp="Resistor_SMD:R_0402_1005Metric",
                 lcsc="C77131", mpn="NCP15XH103F03RC")
    sh.nets(nt, {"1": "NTC_ADC", "2": "GND"})
    row(sh, "R", 365.76, 177.8, [("R309", "10k", "+3V3", "NTC_ADC")])
    row(sh, "C", 386.08, 177.8, [("C309", "100n", "NTC_ADC", "GND")])
    sh.note(215.9, 177.8, [
        "ICHOP = 2.75 V * TORQUE / (256 * ISGAIN * RSENSE) (SLVSC40H eq. 1).",
        "ISGAIN 10, RSENSE 0.1 ohm, TORQUE 186: 2.00 A per phase (derived);",
        "TORQUE 255 gives 2.74 A, the ceiling. Firmware limits TORQUE to 186 (HW-MOT-002).",
        "VSENSE 0.2 V at 2 A, under the 0.7 V xISENx rating (6.1). P = 0.2 W rms in a 1 W 2512.",
        "CSD18543Q3A: 60 V, Qg 11.1 nC (SLPS633). C306/C307 at each bridge's high side.",
        "RT301 sits next to the FETs: 10k NTC from +3V3 / 10k, read by the ADC.",
    ])

    classes(sh, {
        "AOUT1": "PWR_2A_30V", "AOUT2": "PWR_2A_30V", "BOUT1": "PWR_2A_30V", "BOUT2": "PWR_2A_30V",
        "ISENA": "PWR_2A", "ISENB": "PWR_2A", "BEMF_ADC": "ANALOG", "NTC_ADC": "ANALOG", "DRV_BEMF": "ANALOG",
    })
