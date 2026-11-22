"""Schematic checks on the design model: what a reviewer looks for and ERC doesn't.

Each check returns findings: dict(check, severity, anchor, message, rule). Severity follows the reviewer's scale:
BLOCKER (respin or damage), MAJOR (likely malfunction), MINOR (margin, DFM), NOTE (observation, can't verify).
`rule` points to the skill section that owns the rule, and through it to the primary source.

  decoupling       an IC power-input net with no capacitor to ground; with positions, a power pin with no
                   decoupling capacitor within DECAP_MM
  pullups          I2C nets with no pull-up resistor to a supply; open-collector outputs with none (may be internal)
  mcu_pins         BOOT pins floating; VCAP pins without a capacitor to ground; power-input pins on no net
  ratings          capacitors rated below the voltage across them (and class-II MLCCs below 2x, a screening default);
                   TVS diodes whose standoff is below their net's voltage
  orientation      diodes and polarized capacitors forward-biased or reversed across a supply
  connector_esd    connector pins on nets with no ESD or TVS part, directly or through series parts (fuses, ferrites,
                   inductors, FET drain-source paths, up to SERIES_HOPS); half-bridge outputs count as clamped
  dividers         a resistor divider whose output, into an IC pin, exceeds that IC's supply
  test_points      supply and ground nets with no test point
  unknown          supply-like nets whose voltage is unknown (the voltage checks skip them)
"""

import math
import re

import design as D

DECAP_MM = 6.0       # Microchip's limit for a decoupling trace through a via [mcu-circuit-design §2, MCHP-DEC]
ESD_PART = re.compile(r"ESD|TVS|PESD|USBLC|SMBJ|SMAJ|SMCJ|SM712|TPD\d|PRTR|ESDA|SP0\d|SRV05|D_TVS|ECMF|RCLAMP|NUP\d", re.I)
CLASS_II = re.compile(r"X5R|X7R|X6S|X7S|X8R|Y5V|Z5U", re.I)
CLASS_I = re.compile(r"C0G|NP0|COG", re.I)
TVS_PN = re.compile(r"\bSM[ABCDLF]?J?(\d+(?:\.\d+)?)(C?)A\b|\b(?:P6|1\.5)KE?(\d+(?:\.\d+)?)(C?)A\b", re.I)
I2C = re.compile(r"(^|[_\-])I2C\d*[_\-]?(SCL|SDA)\b|(^|[_\-])(SCL|SDA)\d*($|[_\-])", re.I)
SWITCH_NODE = re.compile(r"LX|(^|_)(SW|PH|PHASE)\d*($|_)", re.I)   # converter switch nodes: no decoupling there
POLARIZED_CAP = re.compile(r"CP_|C_Polarized|CP$|Elec|Tantal", re.I)
FET_DS = re.compile(r"^(D|S|DRAIN|SOURCE)(\b|_|\d)", re.I)     # a FET's drain / source pins (not the gate)
SERIES_HOPS = 4      # a TVS behind a fuse and back-to-back reverse-polarity FETs still protects the connector


def f(check, severity, anchor, message, rule):
    return dict(check=check, severity=severity, anchor=anchor, message=message, rule=rule)


def caps_between(d, net_a, ground_only=True):
    """Capacitors with one pin on net_a and the other on ground."""
    out = []
    for p in d.nets.get(net_a, []):
        part = d.parts[p["ref"]]
        if d.kind(p["ref"]) != "C" or part["dnp"]:
            continue
        nets = d.two_pin(part)
        if nets and net_a in nets and any(D.is_ground(n) for n in nets if n != net_a):
            out.append(part)
    return out


def ics(d):
    return [p for r, p in d.parts.items() if d.kind(r) in ("U", "IC") and not p["dnp"]]


# ------------------------------------------------------------------------------------------------ checks
def decoupling(d):
    out = []
    if not d.has_types():
        return [f("decoupling", "NOTE", "", "no pin types: decoupling not checked (give the schematic or a netlist)",
                  "mcu-circuit-design §2")]
    positions = d.has_positions()
    for part in ics(d):
        pwr = [p for p in part["pins"].values() if p["type"] == "power_in" and p["net"] and not D.is_ground(p["net"])
               and not SWITCH_NODE.search(p["name"] or "") and not SWITCH_NODE.search(D.base(p["net"]))]
        for net in sorted({p["net"] for p in pwr}):
            if not caps_between(d, net):
                out.append(f("decoupling", "MAJOR", f"{part['ref']} / {D.base(net)}",
                             f"{part['ref']} ({part['value']}) supply {D.base(net)} has no capacitor to ground on its net",
                             "mcu-circuit-design §2; analog-circuit-design §8"))
        if not positions:
            continue
        far = []
        for p in pwr:
            caps = caps_between(d, p["net"])
            pads = [q for c in caps for q in c["pins"].values() if q["net"] == p["net"] and q["x"] is not None]
            if caps and pads and p["x"] is not None:
                dist = min(math.dist((p["x"], p["y"]), (q["x"], q["y"])) for q in pads)
                if dist > DECAP_MM:
                    far.append(f"{p['num']}{('/' + p['name']) if p['name'] else ''} {dist:.1f} mm")
        if far:
            out.append(f("decoupling", "MINOR", part["ref"],
                         f"{part['ref']} power pins with no decoupling capacitor within {DECAP_MM:g} mm: {', '.join(far[:8])}"
                         + (" …" if len(far) > 8 else ""), "mcu-circuit-design §2 [MCHP-DEC]"))
    return out


def has_pullup(d, net):
    for p in d.nets.get(net, []):
        part = d.parts[p["ref"]]
        if d.kind(p["ref"]) != "R" or part["dnp"]:
            continue
        nets = d.two_pin(part)
        other = [n for n in (nets or ()) if n != net]
        if other and not D.is_ground(other[0]):
            v = d.voltage(other[0])
            if (v or 0) > 0 or any(q["type"] in ("power_out", "power_in") for q in d.nets.get(other[0], [])):
                return True
    return False


def pullups(d):
    out = []
    for net, pins in sorted(d.nets.items()):
        named = I2C.search(D.base(net)) or any(I2C.search(p["name"] or "") for p in pins)
        oc = [p for p in pins if p["type"] in ("open_collector", "open_emitter") and d.kind(p["ref"]) in ("U", "IC")]
        if not (named or oc) or has_pullup(d, net):
            continue
        if named:
            out.append(f("pullups", "MAJOR", D.base(net), f"I2C net {D.base(net)} has no pull-up resistor to a supply",
                         "mcu-circuit-design §9 [SLVA689A]"))
        else:
            out.append(f("pullups", "MINOR", D.base(net),
                         f"open-collector output {', '.join(p['ref'] + '.' + p['num'] for p in oc)} on {D.base(net)} has "
                         "no external pull-up: confirm the receiver enables an internal one", "mcu-circuit-design §6"))
    return out


def mcu_pins(d):
    out = []
    for part in ics(d):
        for p in part["pins"].values():
            name = (p["name"] or "").upper()
            if re.search(r"BOOT\d?\b|BOOT0", name):
                if not p["net"] or len(d.nets.get(p["net"], [])) < 2:
                    out.append(f("mcu_pins", "MAJOR", f"{part['ref']}.{p['num']}",
                                 f"{part['ref']} pin {p['num']} ({p['name']}) floats: a boot pin must be tied",
                                 "mcu-circuit-design §3 [AN4488][AN5093]"))
            if re.match(r"^VCAP", name) and not (p["net"] and caps_between(d, p["net"])):
                out.append(f("mcu_pins", "MAJOR", f"{part['ref']}.{p['num']}",
                             f"{part['ref']} pin {p['num']} ({p['name']}) has no capacitor to ground: the core regulator "
                             "needs the datasheet's capacitance and ESR", "mcu-circuit-design §2 [AN4488]"))
            if p["type"] == "power_in" and not p["net"]:
                out.append(f("mcu_pins", "BLOCKER", f"{part['ref']}.{p['num']}",
                             f"{part['ref']} power pin {p['num']} ({p['name']}) is on no net", "mcu-circuit-design §2"))
    return out


def ratings(d):
    out, unknown = [], []
    for ref, part in sorted(d.parts.items()):
        nets = d.two_pin(part)
        if part["dnp"] or not nets:
            continue
        va, vb = d.voltage(nets[0]), d.voltage(nets[1])
        if va is None or vb is None:
            continue
        across = abs(va - vb)
        if d.kind(ref) == "C" and across > 0:
            rated = D.rated_voltage(part)
            if rated is None:
                unknown.append(ref)
                continue
            text = part["value"] + " " + " ".join(part["fields"].values())
            ceramic2 = CLASS_II.search(text) or (not CLASS_I.search(text) and not POLARIZED_CAP.search(part["footprint"] + part["lib_id"]))
            if rated < across:
                out.append(f("ratings", "BLOCKER", ref, f"{ref} ({part['value']}) rated {rated:g} V with {across:g} V across it",
                             "power-circuit-design §9"))
            elif ceramic2 and rated < 2 * across:
                out.append(f("ratings", "MINOR", ref,
                             f"{ref} ({part['value']}) rated {rated:g} V at {across:g} V: check its DC-bias curve "
                             "(2x is a screening default, not a rule)", "power-circuit-design §9 [SLUA887A][VISHAY-BIAS]"))
        if d.kind(ref) == "D":
            m = TVS_PN.search(part["value"] + " " + part["fields"].get("MPN", ""))
            if m:
                standoff = float(m.group(1) or m.group(3))
                if across > standoff:
                    out.append(f("ratings", "BLOCKER", ref,
                                 f"{ref} ({part['value']}) standoff {standoff:g} V below the {across:g} V across it: it "
                                 "conducts in normal operation", "power-circuit-design §3 [LF-SMBJ]"))
    if unknown:
        out.append(f("ratings", "NOTE", ", ".join(unknown[:20]),
                     f"{len(unknown)} capacitor(s) on known voltages state no rating in their value or fields: "
                     "add a Voltage field to check them", "power-circuit-design §9"))
    return out


def _anode_cathode(part):
    pins = list(part["pins"].values())
    by = {(p["name"] or "").upper(): p for p in pins}
    if "A" in by and "K" in by:
        return by["A"], by["K"], "pin names"
    if len(pins) == 2 and not any(p["name"] for p in pins):
        k = part["pins"].get("1")
        a = part["pins"].get("2")
        if a and k:
            return a, k, "pad 1 = cathode (KiCad footprint convention, no pin names)"
    return None


def orientation(d):
    out = []
    for ref, part in sorted(d.parts.items()):
        if part["dnp"]:
            continue
        lib = part["lib_id"] + " " + part["footprint"] + " " + part["value"]
        if d.kind(ref) == "D" and not re.search(r"LED|bidir|_Bi|CA\b", lib, re.I):
            ak = _anode_cathode(part)
            if not ak:
                continue
            a, k, how = ak
            va, vk = d.voltage(a["net"]), d.voltage(k["net"])
            if va is not None and vk is not None and va > vk:
                out.append(f("orientation", "BLOCKER", ref,
                             f"{ref} ({part['value']}) is forward-biased from {D.base(a['net'])} ({va:g} V) to "
                             f"{D.base(k['net'])} ({vk:g} V): a short across the supply ({how})", "power-circuit-design §3"))
        if d.kind(ref) == "C" and POLARIZED_CAP.search(part["lib_id"] + " " + part["footprint"]):
            plus = next((p for p in part["pins"].values() if (p["name"] or "") == "+"), part["pins"].get("1"))
            minus = next((p for p in part["pins"].values() if p is not plus), None)
            if plus and minus:
                vp, vm = d.voltage(plus["net"]), d.voltage(minus["net"])
                if vp is not None and vm is not None and vp < vm:
                    out.append(f("orientation", "BLOCKER", ref,
                                 f"{ref} ({part['value']}) polarized capacitor reversed: + on {D.base(plus['net'])} "
                                 f"({vp:g} V), - on {D.base(minus['net'])} ({vm:g} V)", "power-circuit-design §9"))
    return out


def _series_links(d):
    """net -> nets reached through one series part: a fuse, ferrite or inductor (two pins), or a FET's drain-source
    path. These pass a surge through to the TVS on the far side, so they don't isolate a connector from it."""
    links = {}
    for ref, part in d.parts.items():
        if part["dnp"]:
            continue
        kind = d.kind(ref)
        if kind in ("F", "FB", "L"):
            nets = [p["net"] for p in part["pins"].values() if p["net"]]
        elif kind == "Q":
            nets = [p["net"] for p in part["pins"].values() if p["net"] and FET_DS.match(p["name"] or "")]
        else:
            continue
        nets = [n for n in set(nets) if not D.is_ground(n)]
        for a in nets:
            links.setdefault(a, set()).update(n for n in nets if n != a)
    return links


def _half_bridge_outputs(d):
    """Nets on one FET's source and another FET pin's drain (a half-bridge midpoint): the body diodes clamp them to
    the rail and ground, so a motor or coil terminal there needs no separate ESD part."""
    out = set()
    for net, pins in d.nets.items():
        names = [(p["ref"], (p["name"] or "").upper()) for p in pins if d.kind(p["ref"]) == "Q"]
        if any(n.startswith("S") for _, n in names) and any(n.startswith("D") for _, n in names):
            out.add(net)
    return out


def connector_esd(d):
    out = []
    direct = {n for n, pins in d.nets.items()
              if any(ESD_PART.search(d.parts[p["ref"]]["value"] + " " + d.parts[p["ref"]]["lib_id"] + " "
                                     + d.parts[p["ref"]]["fields"].get("MPN", "")) for p in pins)}
    links = _series_links(d)
    protected, frontier = set(direct), set(direct)
    for _ in range(SERIES_HOPS):
        frontier = {m for n in frontier for m in links.get(n, ())} - protected
        protected |= frontier
    clamped = _half_bridge_outputs(d)
    for ref, part in sorted(d.parts.items()):
        if d.kind(ref) not in ("J", "P", "CN", "USB", "X") or part["dnp"] or d.kind(ref) == "X" and "conn" not in part["footprint"].lower():
            continue
        bare = sorted({D.base(p["net"]) for p in part["pins"].values()
                       if p["net"] and not D.is_ground(p["net"]) and p["net"] not in protected | clamped})
        if bare:
            out.append(f("connector_esd", "MINOR", ref,
                         f"{ref} ({part['value']}): {len(bare)} net(s) leave the board with no ESD/TVS part: "
                         f"{', '.join(bare[:10])}{' …' if len(bare) > 10 else ''} (fine for an internal connector)",
                         "interface-layout §2; mcu-circuit-design §6–§7; power-circuit-design §3"))
    return out


def dividers(d):
    out = []
    for net, pins in sorted(d.nets.items()):
        if d.voltage(net) is not None:
            continue
        tops, bottoms = [], []
        for p in pins:
            part = d.parts[p["ref"]]
            if d.kind(p["ref"]) != "R" or part["dnp"]:
                continue
            nets = d.two_pin(part)
            other = next((n for n in nets if n != net), None) if nets else None
            r = D.parse_value(part["value"], "Ω|ohm")
            if other is None or not r:
                continue
            v = d.voltage(other)
            if v == 0.0:
                bottoms.append(r)
            elif v:
                tops.append((r, v))
        if not tops or not bottoms:
            continue
        g_top = sum(1 / r for r, _ in tops)
        v_top = max(v for _, v in tops)
        r_bot = 1 / sum(1 / r for r in bottoms)
        vout = v_top * r_bot / (r_bot + 1 / g_top)
        for p in pins:
            if d.kind(p["ref"]) not in ("U", "IC"):
                continue
            ic = d.parts[p["ref"]]
            sup = [d.voltage(q["net"]) for q in ic["pins"].values() if q["type"] == "power_in" and q["net"]]
            sup = [v for v in sup if v]
            if sup and vout > max(sup) + 1e-6:
                out.append(f("dividers", "MAJOR", f"{p['ref']}.{p['num']} / {D.base(net)}",
                             f"divider on {D.base(net)} gives {vout:.2f} V from {v_top:g} V into {p['ref']} pin {p['num']}"
                             f" ({p['name']}), above its {max(sup):g} V supply", "analog-circuit-design §5–§6"))
    return out


def test_points(d):
    tps = {p["net"] for r, part in d.parts.items() if d.kind(r) == "TP" for p in part["pins"].values() if p["net"]}
    supplies = sorted({n for n in d.nets if (d.voltage(n) or 0) > 0 or D.is_ground(n)} - tps)
    if not supplies:
        return []
    return [f("test_points", "NOTE", ", ".join(D.base(n) for n in supplies[:12]),
              f"{len(supplies)} supply or ground net(s) without a test point: {', '.join(D.base(n) for n in supplies[:12])}",
              "hardware-project requirements (test access; IPC-2221C §3.6, §10.2.3)")]


def unknown_supplies(d):
    sup = sorted({n for n, pins in d.nets.items() if d.voltage(n) is None and not SWITCH_NODE.search(D.base(n))
                  and not any(SWITCH_NODE.search(p["name"] or "") for p in pins)
                  and any(p["type"] in ("power_in", "power_out") for p in pins)})
    if not sup:
        return []
    return [f("unknown", "NOTE", ", ".join(D.base(n) for n in sup[:12]),
              f"{len(sup)} supply net(s) have no known voltage, so the rating, orientation and divider checks skip "
              f"them: {', '.join(D.base(n) for n in sup[:12])}. Give them with --voltage NET=V", "design-review §3")]


ALL = [decoupling, pullups, mcu_pins, ratings, orientation, connector_esd, dividers, test_points, unknown_supplies]


def run(d, only=None):
    out = []
    for check in ALL:
        if only and check.__name__ not in only:
            continue
        out += check(d)
    return out
