"""Sheet 5: 2.4 GHz path: MLPF-WB55-01E3 (match + harmonic filter), pi network for antenna tuning, PCB antenna."""
from sch import Sheet

from parts import classes, series, shunt


def g(n):
    return round(n * 2.54, 2)


def build(project, values):
    sh = Sheet(project, 5, "rf", "Radio")
    sh.desc = ["RF1 -> MLPF-WB55-01E3 -> 50 ohm line -> pi tuning network -> TI SWRA117D inverted-F antenna"]

    sh.box(g(6), g(6), g(100), g(60), "2.4 GHz path (rf-layout skill; ST DS12804, TI SWRA117D)")
    fl = sh.part("stepper-ble:MLPF-WB55-01E3", "FL501", "MLPF-WB55-01E3", (g(30), g(22)),
                 fp="stepper-ble:ST_MLPF-WB55-01E3_CSP-6", lcsc="C2651048", mpn="MLPF-WB55-01E3")
    fl.fpos = (-5.08, 3.81, "right")
    y = fl["A3"].y
    sh.path("RF1", [fl["A3"], (g(18), y)])
    sh.label("RF1", (g(18), y), (-1, 0))
    sh.net(fl["A2"], "GND")
    sh.rail("GND", g(26), [fl["B3"], fl["B2"], fl["B1"]], tap=(g(30), (0, 1)))
    c501 = shunt(sh, "C501", "100p", g(42), y, DNP_reason="antenna tuning, fit at bring-up")
    r501 = series(sh, "R501", "0", g(50), y)
    c502 = shunt(sh, "C502", "100p", g(64), y, DNP_reason="antenna tuning, fit at bring-up")
    c501.dnp = c502.dnp = True
    ant = sh.part("Device:Antenna_Shield", "AE501", "IFA 2.4GHz", (g(74), y - 5.08),
                  fp="stepper-ble:Texas_SWRA117D_2.4GHz_Left_D0.2", in_bom=False)
    sh.net(ant["2"], "GND")
    sh.rail("RF_50R", y, [fl["A1"], c501["1"], r501["1"]])
    sh.rail("RF_ANT", y, [r501["2"], c502["1"], ant["1"]])
    sh.note(g(8), g(36), [
        "MLPF-WB55-01E3: impedance match to STM32WB55Cx plus harmonic filter, 50 ohm on the antenna side (DS12804 p.1).",
        "Place it at RF1 with short tracks; >= 2 ground vias per GND pad, straight to L2 (rf-layout 3).",
        "R501 (0 ohm) and C501/C502 (not fitted): pi network to tune the antenna on the finished board with a VNA.",
        "Antenna: TI SWRA117D inverted-F, designed for a 50 ohm feed; copper only. Keep all layers clear under it.",
        "ASSUMPTION: the board's stack-up detunes it; retune with C501/C502 and the antenna length (SWRA117D).",
        "RF_50R, RF_ANT: grounded coplanar 50 ohm on L1 over solid L2 (class RF_50; width from JLCPCB's calculator).",
    ])

    sh.class_table(g(102), g(6), rows=6)
    classes(sh, {"RF_50R": "RF_50", "RF_ANT": "RF_50"})
