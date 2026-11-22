"""Sheet 5: 2.4 GHz path: MLPF-WB55-01E3 (match + harmonic filter), pi network for antenna tuning, PCB antenna."""
from sch import Sheet

from parts import C, R, classes


def build(project, values):
    sh = Sheet(project, 5, "rf", "Radio")
    sh.desc = ["RF1 -> MLPF-WB55-01E3 -> 50 ohm line -> pi tuning network -> TI SWRA117D inverted-F antenna"]

    sh.box(15.24, 15.24, 300.99, 160.02, "2.4 GHz path (rf-layout skill; ST DS12804, TI SWRA117D)")
    fl = sh.part("stepper-ble:MLPF-WB55-01E3", "FL501", "MLPF-WB55-01E3", (63.5, 76.2),
                 fp="stepper-ble:ST_MLPF-WB55-01E3_CSP-6", lcsc="C2651048", mpn="MLPF-WB55-01E3")
    sh.nets(fl, {"A3": "RF1", "A1": "RF_50R", "A2": "GND", "B1": "GND", "B2": "GND", "B3": "GND"})
    R(sh, "R501", "0", (129.54, 76.2), "RF_50R", "RF_ANT")
    C(sh, "C501", "100p", (114.3, 104.14), "RF_50R", "GND", DNP_reason="antenna tuning, fit at bring-up")
    C(sh, "C502", "100p", (144.78, 104.14), "RF_ANT", "GND", DNP_reason="antenna tuning, fit at bring-up")
    for ref in ("C501", "C502"):
        next(p for p in sh.parts if p.ref == ref).dnp = True
    ant = sh.part("Device:Antenna_Shield", "AE501", "IFA 2.4GHz", (205.74, 63.5),
                  fp="stepper-ble:Texas_SWRA117D_2.4GHz_Left_D0.2", in_bom=False)
    sh.nets(ant, {"1": "RF_ANT", "2": "GND"})
    sh.note(20.32, 121.92, [
        "MLPF-WB55-01E3: impedance match to STM32WB55Cx plus harmonic filter, 50 ohm on the antenna side (DS12804 p.1).",
        "Place it at RF1 with short tracks; >= 2 ground vias per GND pad, straight to L2 (rf-layout 3).",
        "R501 (0 ohm) and C501/C502 (not fitted): pi network to tune the antenna on the finished board with a VNA.",
        "Antenna: TI SWRA117D inverted-F, designed for a 50 ohm feed; copper only, no part to buy. Keep all layers clear",
        "under it. ASSUMPTION: the board's stack-up detunes it; retune with C501/C502 and the antenna length (SWRA117D).",
        "RF_50R and RF_ANT: grounded coplanar 50 ohm on L1 over solid L2 (class RF_50; width from JLCPCB's calculator).",
    ])

    classes(sh, {"RF_50R": "RF_50", "RF_ANT": "RF_50"})
