#!/usr/bin/env python3
"""pins.py: MCU pin assignment from the placement (hardware picks the pins, within what the firmware needs).

    pins.py assign <board.kicad_pcb> --mcu U301 --needs pin-needs.txt [--out pinmap.txt] [--pin-data pins.csv]
    pins.py check  <board.kicad_pcb> --mcu U301 --needs pin-needs.txt [--pin-data pins.csv]

The needs file (from the firmware's requirements; one function per line, # comments):

    # function       signals                          group
    MOTOR_A_IN1      TIM1_CH1|TIM1_CH1N
    IMU_SCK          SPI{n}_SCK                       imu
    IMU_MISO         SPI{n}_MISO                      imu
    IMU_MOSI         SPI{n}_MOSI                      imu
    ENC_L_A          TIM{t}_CH1|LPTIM{t}_IN1          enc_l
    VBAT_SENSE       ADC1_IN*
    STATUS_LED       GPIO
    SWDIO            PA13

  signals  alternatives separated by |. Each is an alternate-function name with * wildcards and {x} placeholders,
           GPIO (any I/O pin), EXTI (any I/O pin, its external-interrupt line = the pin number, so two EXTI
           functions never share a line), or an exact pin name (PA13). A placeholder takes one value across its
           group (the same SPI or timer instance for a whole bus); without a group it is local to the line.
           In a group, alternatives line up by position: every line takes the same one, so
           ENC_A TIM{t}_CH1|LPTIM{t}_IN1 with ENC_B TIM{t}_CH2|LPTIM{t}_IN2 is a TIM pair or an LPTIM pair,
           never one of each. A line with a single alternative fits every position.
  The function is also the net name the schematic gives that connection (a function net, pin TBD); a sheet path
  in the board's net name is ignored. A net on two pins is two functions: NET and NET~2.

Pin data: the MCU's symbol embedded in the project's schematic (KiCad's STM32 symbols list every alternate
function, generated from ST's STM32_open_pin_data), or --pin-data, a CSV with columns number,name,alternates
(space-separated). Pin positions: the MCU footprint's pads on the board.

assign  For every function, the target is the centroid of its net's other pads on the placed board. Functions are
        assigned to free I/O pads (no net, or a net that is itself a function) by minimum total distance (Hungarian),
        over every choice of peripheral instances, with each alternate-function signal used on one pin only. Pads
        on other nets (supplies, crystal, debug not in the needs) are never used, and neither are reserved pins:
        boot-strap pins (BOOT in the name or an alternate) and the SWD pins (SWDIO, SWCLK), whose state at reset
        matters, unless a need names the pin exactly or --allow-reserved is given. Writes the pin map as text:
        function, pin, pad, signal, package side, distance; and compares with the board's current assignment.
check   The board's current assignment (MCU pads carrying function nets) against the needs: every function on a
        pin that offers one of its signals, placeholders consistent per group, no signal on two pins. Exit 1 on
        a violation.
"""
import argparse
import csv
import glob
import itertools
import math
import os
import re
import sys

import numpy as np
from scipy.optimize import linear_sum_assignment

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import boardgeo as G  # noqa: E402

R = G.R
IO = re.compile(r"^P[A-Z]\d{1,2}$")
RESERVED = re.compile(r"BOOT|SWDIO|SWCLK", re.I)   # strap and debug pins: their level at reset matters
INF = 1e9
EXHAUSTIVE = 5000      # instance combinations searched exhaustively; above this, coordinate descent


# ------------------------------------------------------------------------------------------------- inputs
def read_needs(path):
    needs = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) not in (2, 3):
                sys.exit(f"{path}:{n}: want 'function signals [group]', got: {line}")
            needs.append(dict(function=parts[0], spec=parts[1].split("|"),
                              group=parts[2] if len(parts) == 3 else f"_line{n}"))
    size = {}
    for x in needs:
        size[x["group"]] = size.get(x["group"], 0) + 1
    for x in needs:
        x["aligned"] = size[x["group"]] > 1 and len(x["spec"]) > 1
    names = [x["function"] for x in needs]
    dup = {x for x in names if names.count(x) > 1}
    if dup:
        sys.exit(f"{path}: functions listed twice: {', '.join(sorted(dup))}")
    return needs


def pins_from_csv(path):
    with open(path, encoding="utf-8") as f:
        return {r["number"]: dict(name=r["name"], alternates=(r.get("alternates") or "").split())
                for r in csv.DictReader(f)}


def pins_from_schematic(board_path, ref):
    """{pad number: {name, alternates}} from the symbol of `ref` embedded in the project's schematics."""
    folder = os.path.dirname(os.path.abspath(board_path))
    for sch in sorted(glob.glob(os.path.join(folder, "**", "*.kicad_sch"), recursive=True)):
        with open(sch, encoding="utf-8") as f:
            text = f.read()
        if f'"{ref}"' not in text:
            continue
        root = R.parse_sexpr(text)
        lib_id = None
        for s in R.children(root, "symbol"):
            props = {p[1]: p[2] for p in R.children(s, "property") if len(p) > 2}
            insts = [r[1] for inst in R.children(s, "instances") for proj in R.children(inst, "project")
                     for path in R.children(proj, "path") for r in R.children(path, "reference")]
            if props.get("Reference") == ref or ref in insts:
                lib_id = R.child(s, "lib_id")[1]
                break
        if not lib_id:
            continue
        libs = R.child(root, "lib_symbols")
        sym = next((s for s in R.children(libs, "symbol") if s[1] == lib_id), None) if libs else None
        if sym is None:
            continue
        pins = {}

        def walk(node):
            for c in node:
                if isinstance(c, list) and c and c[0] == "symbol":
                    walk(c)
                elif isinstance(c, list) and c and c[0] == "pin":
                    name, num = R.child(c, "name"), R.child(c, "number")
                    if name and num:
                        pins[num[1]] = dict(name=name[1], alternates=[a[1] for a in R.children(c, "alternate")])
        walk(sym)
        return pins, f"{os.path.relpath(sch, folder)} ({lib_id})"
    sys.exit(f"no symbol with reference {ref} found in the schematics next to {board_path}; pass --pin-data")


# ------------------------------------------------------------------------------------------------- matching
def compile_alt(alt):
    """An alternative -> (kind, regex or pin name, placeholder names)."""
    if alt in ("GPIO", "EXTI"):
        return (alt.lower(), None, [])
    if IO.match(alt):
        return ("pin", alt, [])
    names = re.findall(r"\{(\w+)\}", alt)
    rx = re.escape(alt).replace(r"\*", ".*")
    for nm in names:
        rx = rx.replace(re.escape("{" + nm + "}"), f"(?P<{nm}>[A-Za-z0-9]+?)", 1)
        rx = rx.replace(re.escape("{" + nm + "}"), f"(?P={nm})")
    return ("signal", re.compile("^" + rx + "$"), names)


def matches(need, pin):
    """[(signal, {placeholder: value})] that this pin offers for this need."""
    out = []
    for pos, alt in enumerate(need["spec"]):
        kind, rx, _ = compile_alt(alt)
        tag = {"_alt": str(pos)} if need.get("aligned") else {}
        if kind == "gpio":
            if IO.match(pin["name"]):
                out.append(("GPIO", dict(tag)))
        elif kind == "exti":
            if IO.match(pin["name"]):
                out.append(("EXTI" + re.sub(r"\D", "", pin["name"]), dict(tag)))
        elif kind == "pin":
            if pin["name"] == rx:
                out.append((pin["name"], dict(tag)))
        else:
            for sig in pin["alternates"]:
                m = rx.match(sig)
                if m:
                    out.append((sig, dict(m.groupdict(), **tag)))
    return out


def net_of(function):
    return function.split("~", 1)[0]


def base(net):
    return (net or "").rsplit("/", 1)[-1]


def side_of(dx, dy):
    a = math.degrees(math.atan2(-dy, dx)) % 360          # y-down board: up is north
    return "E" if a < 45 or a >= 315 else "N" if a < 135 else "W" if a < 225 else "S"


# ------------------------------------------------------------------------------------------------- model
def reserved(pad):
    return bool(RESERVED.search(pad["name"]) or any(RESERVED.search(a) for a in pad["alternates"]))


def load(board_path, ref, needs_path, pin_data=None, allow_reserved=False):
    b = G.Board(board_path)
    mcu = b.by_ref().get(ref)
    if mcu is None:
        sys.exit(f"{ref} is not on the board")
    pins, source = (pins_from_csv(pin_data), pin_data) if pin_data else pins_from_schematic(board_path, ref)
    needs = read_needs(needs_path)
    nets = {net_of(x["function"]) for x in needs}
    pads = {}
    for p in mcu["pads"]:
        if p["num"] in pins:
            pads[p["num"]] = dict(pins[p["num"]], num=p["num"], x=p["x"], y=p["y"], net=base(p["net"]),
                                  side=side_of(p["x"] - mcu["x"], p["y"] - mcu["y"]))
    exact = {alt for x in needs for alt in x["spec"] if IO.match(alt)}
    free = [p for p in pads.values() if (not p["net"] or p["net"].startswith("unconnected-") or p["net"] in nets)
            and (IO.match(p["name"]) or p["alternates"])
            and (allow_reserved or not reserved(p) or p["name"] in exact)]
    pts = {}
    for f in b.footprints:
        if f["ref"] == ref:
            continue
        for p in f["pads"]:
            if base(p["net"]) in nets:
                pts.setdefault(base(p["net"]), []).append((p["x"], p["y"]))
    targets = {x["function"]: (float(np.mean([q[0] for q in pts[n]])), float(np.mean([q[1] for q in pts[n]])))
               for x in needs for n in [net_of(x["function"])] if n in pts}
    on_net = {}
    for p in sorted(pads.values(), key=lambda q: int(q["num"]) if q["num"].isdigit() else 0):
        if p["net"] in nets:
            on_net.setdefault(p["net"], []).append(p)
    current = {}
    for x in needs:                                          # NET, NET~2, ... take the net's pins in pad order
        lst = on_net.get(net_of(x["function"]), [])
        k = int(x["function"].split("~", 1)[1]) - 1 if "~" in x["function"] else 0
        if k < len(lst):
            current[x["function"]] = lst[k]
    return dict(board=b, mcu=mcu, pads=pads, free=free, needs=needs, targets=targets, current=current, source=source)


def group_options(model):
    """{group: [binding dict]}: placeholder values for which every line of the group has a free pin."""
    opts = {}
    groups = {}
    for need in model["needs"]:
        groups.setdefault(need["group"], []).append(need)
    for g, lines in groups.items():
        values = {}
        for need in lines:
            for pad in model["free"]:
                for _, bind in matches(need, pad):
                    for k, v in bind.items():
                        values.setdefault(k, set()).add(v)
        keys = sorted(values)
        combos = [dict(zip(keys, c)) for c in itertools.product(*(sorted(values[k]) for k in keys))] if keys else [{}]
        ok = []
        for bind in combos:
            if all(any(all(b2.get(k) == v for k, v in bind.items() if k in b2) for pad in model["free"]
                       for _, b2 in matches(need, pad)) for need in lines):
                ok.append(bind)
        if not ok:
            sys.exit(f"group {g}: no free pins offer {', '.join(n['function'] for n in lines)} together")
        opts[g] = ok
    return opts


def solve_with(model, binding):
    """Hungarian assignment for one choice of group bindings; returns (cost, rows) or (INF, None)."""
    needs, free = model["needs"], model["free"]
    cost = np.full((len(needs), len(free)), INF)
    signal = {}
    banned = set()
    for _ in range(len(needs) + 1):                          # repeat while one signal lands on two pins
        for i, need in enumerate(needs):
            bind = binding[need["group"]]
            t = model["targets"].get(need["function"])
            for j, pad in enumerate(free):
                cands = [s for s, b2 in matches(need, pad) if all(bind.get(k) == v for k, v in b2.items())
                         and (s, need["function"]) not in banned]
                if cands:
                    cost[i, j] = math.dist((pad["x"], pad["y"]), t) if t else 0.0
                    signal[(i, j)] = cands[0]
                else:
                    cost[i, j] = INF
        if len(needs) > len(free):
            return INF, None
        r, c = linear_sum_assignment(cost)
        if cost[r, c].max() >= INF:
            return INF, None
        used = {}
        clash = None
        for i, j in zip(r, c):
            s = signal[(i, j)]
            if s != "GPIO" and not IO.match(s) and s in used:
                clash = (s, needs[i]["function"])
                break
            used[s] = i
        if not clash:
            rows = [dict(function=needs[i]["function"], pad=free[j], signal=signal[(i, j)], dist=cost[i, j])
                    for i, j in zip(r, c)]
            return float(cost[r, c].sum()), rows
        banned.add(clash)
    return INF, None


def assign(model, log=print):
    opts = group_options(model)
    groups = sorted(opts)
    total = math.prod(len(opts[g]) for g in groups)
    best = (INF, None, None)
    if total <= EXHAUSTIVE:
        for combo in itertools.product(*(opts[g] for g in groups)):
            binding = dict(zip(groups, combo))
            c, rows = solve_with(model, binding)
            if c < best[0]:
                best = (c, rows, binding)
    else:                                                    # coordinate descent over the groups
        binding = {g: opts[g][0] for g in groups}
        best = (*solve_with(model, binding), dict(binding))
        for _ in range(5):
            improved = False
            for g in groups:
                for o in opts[g]:
                    trial = dict(best[2], **{g: o})
                    c, rows = solve_with(model, trial)
                    if c < best[0] - 1e-9:
                        best, improved = (c, rows, trial), True
            if not improved:
                break
    if log:
        log(f"searched all {total} instance combinations" if total <= EXHAUSTIVE else
            f"{total} instance combinations: searched by coordinate descent")
    return best


def violations(model):
    """Problems with the board's current assignment."""
    out, used, binds = [], {}, {}
    for need in model["needs"]:
        pad = model["current"].get(need["function"])
        if pad is None:
            out.append(f"{need['function']}: not on any {model['mcu']['ref']} pin")
            continue
        m = matches(need, pad)
        if not m:
            out.append(f"{need['function']}: {pad['name']} offers none of {'|'.join(need['spec'])}")
            continue
        g = binds.setdefault(need["group"], {})
        ok = [(s, b2) for s, b2 in m if all(g.get(k, v) == v for k, v in b2.items())]
        if not ok:
            out.append(f"{need['function']}: {pad['name']} breaks group {need['group']} ({g})")
            continue
        s, b2 = ok[0]
        g.update(b2)
        if s != "GPIO" and not IO.match(s):
            if s in used:
                out.append(f"{need['function']}: {s} on {pad['name']} is already used by {used[s]}")
            used[s] = need["function"]
    return out


def current_cost(model):
    return sum(math.dist((p["x"], p["y"]), model["targets"][f]) for f, p in model["current"].items()
               if f in model["targets"])


# ------------------------------------------------------------------------------------------------- commands
def cmd_assign(a):
    model = load(a.board, a.mcu, a.needs, a.pin_data, getattr(a, "allow_reserved", False))
    print(f"{a.mcu}: {len(model['pads'])} pads with pin data ({model['source']}), {len(model['free'])} free I/O pads, "
          f"{len(model['needs'])} functions, {len(model['targets'])} with a target on the board")
    cost, rows, binding = assign(model)
    if rows is None:
        print("no assignment satisfies the needs with the free pins. Candidates per function:")
        for need in model["needs"]:
            c = sorted({pad["name"] for pad in model["free"] if matches(need, pad)})
            print(f"  {need['function']:16} {len(c):3}  {' '.join(c[:12])}{' …' if len(c) > 12 else ''}")
        return 1
    lines = ["# pin map: function, pin, pad, signal, side, distance to its parts (mm)",
             f"# {a.mcu} on {os.path.basename(a.board)}; pin data: {model['source']}; needs: {os.path.basename(a.needs)}",
             f"# total distance {cost:.1f} mm" + (f" (current assignment {current_cost(model):.1f} mm)"
                                                 if model["current"] else "")]
    groups = {k: v for k, v in binding.items() if v and not k.startswith("_line")}
    if groups:
        lines.append("# instances: " + ", ".join(f"{g}: " + " ".join(f"{k}={v}" for k, v in b.items())
                                                 for g, b in sorted(groups.items())))
    width = max(len(r["function"]) for r in rows)
    for r in sorted(rows, key=lambda r: r["function"]):
        p = r["pad"]
        lines.append(f"{r['function']:{width}}  {p['name']:5} {p['num']:>4}  {r['signal']:16} {p['side']}  {r['dist']:6.1f}")
    text = "\n".join(lines) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {a.out}")
    print(text)
    return 0


def cmd_check(a):
    model = load(a.board, a.mcu, a.needs, a.pin_data)
    bad = violations(model)
    print(f"{a.mcu}: {len(model['current'])} of {len(model['needs'])} functions on pins; "
          f"distance {current_cost(model):.1f} mm")
    for v in bad:
        print("  " + v)
    print("PASS" if not bad else f"FAIL: {len(bad)} problem(s)")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("assign", "check"):
        p = sub.add_parser(name)
        p.add_argument("board")
        p.add_argument("--mcu", required=True, help="the MCU's reference, e.g. U301")
        p.add_argument("--needs", required=True, help="the firmware's pin needs (text, see above)")
        p.add_argument("--pin-data", help="CSV number,name,alternates instead of the schematic's symbol")
        if name == "assign":
            p.add_argument("--out", help="write the pin map here")
            p.add_argument("--allow-reserved", action="store_true",
                           help="also use boot-strap and SWD pins (BOOT, SWDIO, SWCLK) for other functions")
    a = ap.parse_args(argv)
    return cmd_assign(a) if a.cmd == "assign" else cmd_check(a)


if __name__ == "__main__":
    sys.exit(main())
