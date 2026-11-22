"""stepper-ble part helpers: passives from one BOM table, placed upright with a net on each pin.

Every LCSC number was looked up in JLCPCB's parts library on 2026-11-22 (jlc_stock.py re-checks stock, MPN and
package). "base" parts are JLCPCB basic-library parts (no feeder fee).
"""

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"

# value -> (footprint, MPN, LCSC)
RES = {
    "0": (R0402, "0402WGF0000TCE", "C17168"),
    "1k": (R0402, "0402WGF1001TCE", "C11702"),
    "2.2k": (R0402, "0402WGF2201TCE", "C25879"),
    "4.7k": (R0402, "0402WGF4701TCE", "C25900"),
    "5.1k": (R0402, "0402WGF5101TCE", "C25905"),
    "10k": (R0402, "0402WGF1002TCE", "C25744"),
    "20k": (R0402, "0402WGF2002TCE", "C25765"),
    "24.9k": (R0402, "0402WGF2492TCE", "C25874"),
    "47k": (R0402, "0402WGF4702TCE", "C25792"),
    "100k": (R0402, "0402WGF1003TCE", "C25741"),
    "0.1R 1W": ("Resistor_SMD:R_2512_6332Metric", "25121WF100LT4E", "C25466"),
}
CAP = {
    "18p": (C0402, "0402CG180J500NT", "C1549"),
    "100p": (C0402, "0402CG101J500NT", "C1546"),
    "1n": (C0402, "CL05B102KB5NNNC", "C14442"),
    "10n 50V": (C0402, "CL05B103KB5NNNC", "C15195"),
    "100n": (C0402, "CL05B104KO5NNNC", "C1525"),
    "1u": (C0402, "CL05A105KA5NNNC", "C16193167"),
    "4.7u": (C0402, "CL05A475MP5NRNC", "C23733"),
    "100n 50V": (C0603, "CL10B104KB8NNNC", "C1591"),
    "220n 50V": (C0603, "CL10B224KB8NNNC", "C64705"),
    "1u 50V": (C0603, "CL10A105KB8NNNC", "C15849"),
    "22u": (C0805, "CL21A226MQQNNNE", "C5674"),
    "4.7u 50V": (C1206, "CL31B475KBHNNNE", "C51205"),
}


def R(sh, ref, value, at, top, bottom, **fields):
    fp, mpn, lcsc = RES[value]
    p = sh.part("Device:R", ref, value.replace(" 1W", ""), at, fp=fp, lcsc=lcsc, mpn=mpn, **fields)
    sh.nets(p, {"1": top, "2": bottom})
    return p


def C(sh, ref, value, at, top, bottom, **fields):
    fp, mpn, lcsc = CAP[value]
    p = sh.part("Device:C", ref, value, at, fp=fp, lcsc=lcsc, mpn=mpn, **fields)
    sh.nets(p, {"1": top, "2": bottom})
    return p


def row(sh, kind, x0, y, items, pitch=10.16):
    """Place [(ref, value, top_net, bottom_net), ...] left to right at y."""
    f = R if kind == "R" else C
    return [f(sh, ref, value, (x0 + i * pitch, y), top, bottom) for i, (ref, value, top, bottom) in enumerate(items)]


def classes(sh, mapping, default="SIGNAL"):
    """Net-class directives: `mapping` {net: class}; every other net drawn on this sheet gets `default`.
    Called last on each sheet, so no net is left in Default (pcb-copper §1). Nets drawn on several sheets are
    classed on the first sheet that names them in `mapping`, or by default on the sheet that draws them first."""
    done = sh.project.__dict__.setdefault("_classed", set())
    for net in dict.fromkeys(n for _, n, _ in sh.conns):
        if net in done:
            continue
        if net in mapping or default:
            sh.netclass(net, mapping.get(net, default))
            done.add(net)
