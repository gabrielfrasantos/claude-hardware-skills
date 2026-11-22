"""stepper-ble part helpers: passives from one BOM table, placed upright with a net on each pin.

Every LCSC number was looked up in JLCPCB's parts library on 2026-11-22 (jlc_stock.py re-checks stock, MPN and
package). "base" parts are JLCPCB basic-library parts (no feeder fee).
"""

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"

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


OTHER = {
    "22u L": ("Device:L", "Inductor_SMD:L_Sunlord_SWPA4030S", "SWPA4030S220MT", "C83472"),
    "2.2u L": ("Device:L", "Inductor_SMD:L_0805_2012Metric", "LQM21PN2R2MC0D", "C98033"),
    "10n L": ("Device:L", "Inductor_SMD:L_0402_1005Metric", "LQG15WZ10NJ02D", "C3911026"),
    "100u 50V": ("Device:C_Polarized", "Capacitor_SMD:CP_Elec_8x10", "RVT1H101M0810", "C72480"),
    "3A fast": ("Device:Fuse", "Fuse:Fuse_Littelfuse-NANO2-451_453", "0451003.MRL", "C13982"),
    "10k B3380": ("Device:Thermistor_NTC", R0402, "NCP15XH103F03RC", "C77131"),
}


def _lookup(value):
    if value in RES:
        fp, mpn, lcsc = RES[value]
        return "Device:R", fp, mpn, lcsc, value.replace(" 1W", "")
    if value in CAP:
        fp, mpn, lcsc = CAP[value]
        return "Device:C", fp, mpn, lcsc, value
    lib, fp, mpn, lcsc = OTHER[value]
    return lib, fp, mpn, lcsc, value.replace(" L", "")


def series(sh, ref, value, x, y, flip=False, **fields):
    """A two-pin part lying horizontally between (x, y) and (x + 7.62, y): pin 1 on the left, or the right when
    `flip`."""
    lib, fp, mpn, lcsc, shown = _lookup(value)
    return sh.part(lib, ref, shown, (x + 3.81, y), rot=90, mirror="y" if flip else None, fp=fp, lcsc=lcsc,
                   mpn=mpn, **fields)


def shunt(sh, ref, value, x, y, bottom="GND", flip=False, **fields):
    """A two-pin part standing between (x, y) and (x, y + 7.62): pin 1 on top, or at the bottom when `flip`.
    The bottom pin goes on `bottom` (a stub and its label or power symbol); None leaves it to the caller."""
    lib, fp, mpn, lcsc, shown = _lookup(value)
    p = sh.part(lib, ref, shown, (x, y + 3.81), mirror="x" if flip else None, fp=fp, lcsc=lcsc, mpn=mpn, **fields)
    p.top, p.bottom = (p["2"], p["1"]) if flip else (p["1"], p["2"])
    if bottom:
        sh.net(p.bottom, bottom)
    return p


def classes(sh, mapping, default="SIGNAL"):
    """Net-class directives for every net drawn on this sheet (`mapping`, else `default`), drawn in the sheet's
    class table. A net drawn on several sheets is classed on the first."""
    done = sh.project.__dict__.setdefault("_classed", set())
    for net in dict.fromkeys(n for _, n, _ in sh.conns):
        if net in done:
            continue
        sh.netclass(net, mapping.get(net, default))
        done.add(net)
