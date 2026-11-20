#!/usr/bin/env python3
"""Seeded-defect eval for design review: plant known faults in a copy of a real board, then score a review on them.

    review_defects.py seed  <board.kicad_pcb> [--schematic root.kicad_sch] [--voltage NET=V ...] [--out DIR]
    review_defects.py score <DIR/manifest.json> (--findings findings.json | --report review.md)
    review_defects.py run   <board.kicad_pcb> [--schematic ...] [--voltage ...] [--out DIR]

seed   copies the board (with its .kicad_pro and .kicad_dru) to DIR and plants one defect of each kind it can find a
       target for, each on a different part:
         decap_removed     the only capacitors decoupling one IC supply net are taken off it
         pullup_removed    an I2C net's pull-up resistor is taken off it
         diode_reversed    a diode across a supply (cathode on the supply) is turned round
         cap_underrated    a capacitor with a stated rating is marked at half the voltage across it
         tvs_underrated    a TVS on a supply gets a standoff below the supply
         boot_floating     an MCU's BOOT pin is disconnected
         power_pin_open    an IC power-input pin is disconnected
         divider_overrange a divider into an IC gets a top resistor 100x smaller
       It writes DIR/manifest.json: each defect's kind, part, pin, net and the check expected to find it.
score  a defect counts as found when a BLOCKER, MAJOR or MINOR finding names its part (findings.json from
       design-review, or any review in markdown: a table row or line that names the part and isn't marked
       false positive). Reports recall per kind. Use it on the reviewer agent's report too.
run    seed, then design-review's scripted checks on the clean and the seeded board: recall, plus the findings on
       the clean board (each one a real issue or a false positive, for the owner to triage).

Defects go into the board only (pad nets and Value fields); the schematic, if given, supplies pin names and types.
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "hardware-design" / "skills" / "design-review" / "scripts"))
import checks as C  # noqa: E402
import design as D  # noqa: E402

KINDS = ["decap_removed", "pullup_removed", "diode_reversed", "cap_underrated", "tvs_underrated", "boot_floating",
         "power_pin_open", "divider_overrange"]
EXPECT = {"decap_removed": "decoupling", "pullup_removed": "pullups", "diode_reversed": "orientation",
          "cap_underrated": "ratings", "tvs_underrated": "ratings", "boot_floating": "mcu_pins",
          "power_pin_open": "mcu_pins", "divider_overrange": "dividers"}


# ------------------------------------------------------------------------------------------------ text edits
def _block(text, start):
    depth, i = 0, start
    while True:
        ch = text[i]
        if ch == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1


def _footprint_span(text, ref):
    m = re.search(r'\(property "Reference" "' + re.escape(ref) + '"', text)
    if not m:
        raise KeyError(ref)
    s = text.rfind("\n\t(footprint ", 0, m.start()) + 2
    return s, _block(text, s)


def set_pad_net(text, ref, num, net):
    s, e = _footprint_span(text, ref)
    fp = text[s:e]
    m = re.search(r'\(pad "' + re.escape(num) + r'"', fp)
    ps, pe = m.start(), _block(fp, m.start())
    pad = fp[ps:pe]
    if re.search(r'\(net "', pad):
        pad = re.sub(r'\(net "(?:[^"\\]|\\.)*"\)', f'(net "{net}")', pad, count=1) if net else \
            re.sub(r'\s*\(net "(?:[^"\\]|\\.)*"\)', "", pad, count=1)
    elif net:
        pad = pad[:-1].rstrip() + f'\n\t\t\t(net "{net}")\n\t\t)'
    return text[:s] + fp[:ps] + pad + fp[pe:] + text[e:]


def set_value(text, ref, value):
    s, e = _footprint_span(text, ref)
    fp = re.sub(r'\(property "Value" "(?:[^"\\]|\\.)*"', f'(property "Value" "{value}"', text[s:e], count=1)
    return text[:s] + fp + text[e:]


# ------------------------------------------------------------------------------------------------ seeding
def seed(board, schematic=None, voltages=None, out="review-defects"):
    d = D.from_board(board, schematic)
    d.overrides = dict(voltages or {})
    with open(board, encoding="utf-8") as f:
        text = f.read()
    used, defects = set(), []

    def take(ref):
        if ref in used:
            return False
        used.add(ref)
        return True

    def add(kind, ref, num, net, what):
        defects.append(dict(id=f"S{len(defects) + 1}", kind=kind, ref=ref, pin=num, net=D.base(net),
                            expect=EXPECT[kind], what=what))

    ics = C.ics(d)
    # decap_removed: the IC supply net with the fewest capacitors; take them all off it
    cands = []
    for part in ics:
        for net in {p["net"] for p in part["pins"].values() if p["type"] == "power_in" and p["net"]
                    and not D.is_ground(p["net"]) and not C.SWITCH_NODE.search(D.base(p["net"]))
                    and not C.SWITCH_NODE.search(p["name"] or "")}:
            caps = C.caps_between(d, net)
            if caps:
                cands.append((len(caps), part["ref"], net, caps))
    for _, ic_ref, net, caps in sorted(cands, key=lambda c: (c[0], c[1], c[2])):
        if ic_ref in used or any(c["ref"] in used for c in caps):
            continue
        for c in caps:
            take(c["ref"])
            pin = next(p for p in c["pins"].values() if p["net"] == net)
            text = set_pad_net(text, c["ref"], pin["num"], "")
        take(ic_ref)
        add("decap_removed", ic_ref, "", net, f"{', '.join(c['ref'] for c in caps)} taken off {D.base(net)}")
        break
    # pullup_removed
    for net, pins in sorted(d.nets.items()):
        if not C.I2C.search(D.base(net)) and not any(C.I2C.search(p["name"] or "") for p in pins):
            continue
        rs = [p for p in pins if d.kind(p["ref"]) == "R" and p["ref"] not in used]
        pulls = [p for p in rs if C.has_pullup(d, net)]
        if pulls:
            # every pull-up on the net comes off, or the net would still have one
            for p in pins:
                part = d.parts[p["ref"]]
                if d.kind(p["ref"]) == "R":
                    other = [n for n in (d.two_pin(part) or ()) if n != net]
                    if other and not D.is_ground(other[0]):
                        take(p["ref"])
                        text = set_pad_net(text, p["ref"], p["num"], "")
            add("pullup_removed", pulls[0]["ref"], pulls[0]["num"], net, f"pull-up(s) on {D.base(net)} disconnected")
            break
    # diode_reversed, tvs_underrated
    for ref, part in sorted(d.parts.items()):
        if d.kind(ref) != "D" or ref in used or part["dnp"]:
            continue
        ak = C._anode_cathode(part)
        if not ak:
            continue
        a, k, _ = ak
        vk, va = d.voltage(k["net"]), d.voltage(a["net"])
        if vk and va == 0.0:
            if C.TVS_PN.search(part["value"]) and not any(x["kind"] == "tvs_underrated" for x in defects):
                take(ref)
                low = max(1.0, round(vk / 2, 1))
                text = set_value(text, ref, f"SMBJ{low:g}A")
                add("tvs_underrated", ref, "", k["net"], f"value set to SMBJ{low:g}A on a {vk:g} V net")
            elif not any(x["kind"] == "diode_reversed" for x in defects):
                take(ref)
                text = set_pad_net(text, ref, a["num"], k["net"])
                text = set_pad_net(text, ref, k["num"], a["net"])
                add("diode_reversed", ref, "", k["net"], f"anode and cathode nets swapped across {D.base(k['net'])}")
    # cap_underrated
    for ref, part in sorted(d.parts.items()):
        nets = d.two_pin(part)
        if d.kind(ref) != "C" or ref in used or part["dnp"] or not nets:
            continue
        va, vb = d.voltage(nets[0]), d.voltage(nets[1])
        rated = D.rated_voltage(part)
        if va is not None and vb is not None and abs(va - vb) >= 3 and rated and "V" in part["value"]:
            low = max(1, int(abs(va - vb) / 2))
            new = re.sub(r"(\d+(?:\.\d+)?)\s*V(?![A-Z0-9])", f"{low}V", part["value"], count=1)
            if new != part["value"]:
                take(ref)
                text = set_value(text, ref, new)
                add("cap_underrated", ref, "", nets[0] if va else nets[1], f"value {part['value']} -> {new}")
                break
    # boot_floating, power_pin_open
    for part in ics:
        if part["ref"] in used:
            continue
        boot = next((p for p in part["pins"].values() if re.search(r"BOOT\d?\b|BOOT0", (p["name"] or "").upper())
                     and p["net"]), None)
        if boot and not any(x["kind"] == "boot_floating" for x in defects):
            take(part["ref"])
            text = set_pad_net(text, part["ref"], boot["num"], "")
            add("boot_floating", part["ref"], boot["num"], boot["net"], f"{boot['name']} disconnected")
            continue
        pwr = next((p for p in part["pins"].values() if p["type"] == "power_in" and p["net"]
                    and not D.is_ground(p["net"])), None)
        if pwr and not any(x["kind"] == "power_pin_open" for x in defects):
            take(part["ref"])
            text = set_pad_net(text, part["ref"], pwr["num"], "")
            add("power_pin_open", part["ref"], pwr["num"], pwr["net"], f"power pin {pwr['num']} ({pwr['name']}) disconnected")
    # divider_overrange: a divider from a rail above the supply of the IC it feeds; shrink the top resistor
    def supply(ref):
        vs = [d.voltage(q["net"]) for q in d.parts[ref]["pins"].values() if q["type"] == "power_in" and q["net"]]
        vs = [v for v in vs if v]
        return max(vs) if vs else None
    for net, pins in sorted(d.nets.items()):
        ic_sup = [supply(p["ref"]) for p in pins if d.kind(p["ref"]) in ("U", "IC")]
        ic_sup = [v for v in ic_sup if v]
        if d.voltage(net) is not None or not ic_sup:
            continue
        tops = [p for p in pins if d.kind(p["ref"]) == "R" and p["ref"] not in used
                and any((d.voltage(n) or 0) > max(ic_sup) for n in (d.two_pin(d.parts[p["ref"]]) or ()) if n != net)]
        bottoms = [p for p in pins if d.kind(p["ref"]) == "R"
                   and any(D.is_ground(n) for n in (d.two_pin(d.parts[p["ref"]]) or ()) if n != net)]
        if tops and bottoms:
            r = d.parts[tops[0]["ref"]]
            val = D.parse_value(r["value"], "Ω|ohm")
            if val:
                take(r["ref"])
                new = f"{val / 100:g}"
                text = set_value(text, r["ref"], new)
                add("divider_overrange", r["ref"], "", net, f"top resistor {r['value']} -> {new} Ω")
                break

    os.makedirs(out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(board))[0]
    seeded = os.path.join(out, stem + ".kicad_pcb")
    with open(seeded, "w", encoding="utf-8") as f:
        f.write(text)
    for ext in (".kicad_pro", ".kicad_dru"):
        src = os.path.splitext(board)[0] + ext
        if os.path.exists(src):
            shutil.copy(src, os.path.join(out, stem + ext))
    manifest = dict(board=os.path.abspath(board), seeded=os.path.abspath(seeded),
                    schematic=os.path.abspath(schematic) if schematic else None, voltages=d.overrides,
                    defects=defects, not_seeded=[k for k in KINDS if k not in {x["kind"] for x in defects}])
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


# ------------------------------------------------------------------------------------------------ scoring
def _mentions(text, ref):
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(ref) + r"(?![0-9])", text) is not None


def score(manifest, findings=None, report=None):
    rows = []
    if findings is not None:
        items = [x for x in findings if x["severity"] in ("BLOCKER", "MAJOR", "MINOR")]
        for dft in manifest["defects"]:
            hit = [x for x in items if _mentions(x["anchor"] + " " + x["message"], dft["ref"])
                   or (dft["net"] and dft["net"] in x["anchor"] + " " + x["message"] and x["check"] == dft["expect"])]
            rows.append(dict(dft, found=bool(hit), by=[f"{x.get('id', '')} {x['check']} {x['severity']}" for x in hit][:3]))
    else:
        lines = [ln for ln in report.splitlines() if re.search(r"BLOCKER|MAJOR|MINOR", ln)
                 and not re.search(r"FALSE.POSITIVE", ln, re.I)]
        for dft in manifest["defects"]:
            hit = [ln.strip()[:120] for ln in lines if _mentions(ln, dft["ref"])]
            rows.append(dict(dft, found=bool(hit), by=hit[:2]))
    n = len(rows)
    found = sum(r["found"] for r in rows)
    return dict(recall=(found / n) if n else None, found=found, seeded=n, rows=rows)


def table(result, title):
    lines = [f"## {title}", "", f"Recall: {result['found']}/{result['seeded']}"
             + (f" ({100 * result['recall']:.0f} %)" if result["recall"] is not None else ""), "",
             "| Defect | Kind | Part | Net | Found | By |", "|---|---|---|---|---|---|"]
    for r in result["rows"]:
        lines.append(f"| {r['id']} | {r['kind']} | {r['ref']} | {r['net']} | {'yes' if r['found'] else '**no**'} | "
                     f"{'; '.join(r['by'])[:120]} |")
    return "\n".join(lines) + "\n"


def run_checks(board, schematic, voltages):
    d = D.from_board(board, schematic)
    d.overrides = dict(voltages)
    return C.run(d)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("seed", "run"):
        p = sub.add_parser(name)
        p.add_argument("board")
        p.add_argument("--schematic")
        p.add_argument("--voltage", action="append", default=[], metavar="NET=V")
        p.add_argument("--out", default="review-defects")
    p = sub.add_parser("score")
    p.add_argument("manifest")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--findings")
    g.add_argument("--report")
    a = ap.parse_args(argv)

    if a.cmd == "score":
        with open(a.manifest) as f:
            m = json.load(f)
        if a.findings:
            with open(a.findings) as f:
                res = score(m, findings=json.load(f)["findings"])
        else:
            with open(a.report) as f:
                res = score(m, report=f.read())
        print(table(res, f"Seeded defects in {os.path.basename(m['seeded'])}"))
        return 0
    volts = {k: float(v) for k, v in (kv.split("=", 1) for kv in a.voltage)}
    m = seed(a.board, a.schematic, volts, a.out)
    print(f"seeded {len(m['defects'])} defect(s) into {m['seeded']}; no target for: {', '.join(m['not_seeded']) or '-'}")
    for x in m["defects"]:
        print(f"  {x['id']} {x['kind']:18} {x['ref']:8} {x['what']}")
    if a.cmd == "seed":
        return 0
    clean = run_checks(a.board, a.schematic, volts)
    seeded = run_checks(m["seeded"], a.schematic, volts)
    for i, x in enumerate(seeded, 1):
        x["id"] = f"F{i}"
    res = score(m, findings=seeded)
    text = table(res, "Scripted checks (design-review) on the seeded board")
    base = [x for x in clean if x["severity"] in ("BLOCKER", "MAJOR", "MINOR")]
    text += (f"\nOn the clean board the same checks report {len(base)} finding(s) at MINOR or above "
             "(each a real issue or a false positive, for the owner to triage):\n\n"
             + "\n".join(f"- {x['severity']} {x['check']}: {x['message'][:140]}" for x in base) + "\n")
    with open(os.path.join(a.out, "result.md"), "w") as f:
        f.write(text)
    with open(os.path.join(a.out, "result.json"), "w") as f:
        json.dump(dict(score=res, clean_findings=base), f, indent=2)
    print("\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
