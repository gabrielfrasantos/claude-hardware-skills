#!/usr/bin/env python3
"""Check every LCSC part in a BOM CSV against JLCPCB's live parts library.

For each line it reports stock, basic/extended library type and unit price. It fails when:
  - stock can't cover qty * boards * (1 + attrition);
  - the LCSC number resolves to a different manufacturer part number than the BOM states;
  - the BOM's footprint doesn't fit the package JLCPCB lists for the part (chip size or pin count differ);
  - the BOM marks the part NRND, EOL, obsolete or last-time-buy.

Optional BOM columns:
  footprint   KiCad footprint name (export_bom.py writes it). Compared with JLCPCB's package field
              (componentSpecificationEn): chip size (0402, 0603, ...), family and pin count. What can't be parsed
              is listed as "check by hand", not failed.
  lifecycle   from the manufacturer or distributor: Active, NRND, EOL, Obsolete, LTB. JLCPCB's endpoint has no
              lifecycle field, so it has to come from the BOM.
  alt_lcsc    second sources (LCSC numbers, separated by spaces or ;): their stock is checked too. Extended parts
              with no alternate are counted as single-sourced.

Usage: jlc_stock.py bom/bom.csv [--boards 5] [--attrition 0.1] [--json out.json]
"""

import argparse
import csv
import json
import math
import re
import sys
import time
import urllib.request

URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
CHIP = re.compile(r"(?<![0-9])(01005|0201|0402|0603|0805|1206|1210|1812|2010|2512|2220|2225)(?![0-9])")
PIN_FAMILIES = ("LQFP", "TQFP", "QFP", "VFQFPN", "UFQFPN", "VQFN", "WQFN", "UQFN", "QFN", "DFN", "HTSSOP", "TSSOP", "SSOP", "MSOP",
                "VSSOP", "SOIC", "SOP", "SO", "BGA", "LGA", "DIP", "SIP")
SAME = {"SOIC": "SO", "SOP": "SO", "SO": "SO", "VFQFPN": "QFN", "UFQFPN": "QFN", "VQFN": "QFN", "WQFN": "QFN", "UQFN": "QFN", "QFN": "QFN",
        "TQFP": "QFP", "LQFP": "QFP", "QFP": "QFP", "VSSOP": "MSOP", "MSOP": "MSOP"}
CODED = re.compile(r"(?<![A-Z])(SOT|SOD|SC|TO)-?(\d+)(?:-(\d+))?")   # the number is a package code, not pins
DEFAULT_PINS = {"SOT-23": 3}
BAD_LIFECYCLE = re.compile(r"NRND|EOL|OBSOLETE|LTB|LAST.TIME|DISCONTINU", re.I)


def lookup(lcsc):
    body = json.dumps({"keyword": lcsc, "currentPage": 1, "pageSize": 5}).encode()
    request = urllib.request.Request(URL, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "claude-hardware-skills/jlc_stock"})
    for attempt in range(4):
        try:
            data = json.load(urllib.request.urlopen(request, timeout=30))
            for item in data["data"]["componentPageInfo"]["list"] or []:
                if item["componentCode"] == lcsc:
                    return item
            return None
        except OSError:
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"JLC API unreachable for {lcsc}")


def normalise(mpn):
    return "".join(ch for ch in mpn.upper() if ch.isalnum())


def _shape(text):
    """(chip size, family, pin count, body (a, b)) parsed from a package or footprint name; None where unknown."""
    t = text.split(":")[-1].upper().replace("_", " ")
    chip = CHIP.search(t)
    fam = pins = None
    coded = CODED.search(t)
    if coded:
        fam = f"{coded.group(1)}-{coded.group(2)}"
        pins = int(coded.group(3)) if coded.group(3) else DEFAULT_PINS.get(fam)
        return None, fam, pins, None
    for f in PIN_FAMILIES:
        m = re.search(rf"(?<![A-Z]){f}-?(\d+)", t)
        if m:
            fam, pins = SAME.get(f, f), int(m.group(1))
            break
    body = re.search(r"(\d+(?:\.\d+)?)\s*[X*]\s*(\d+(?:\.\d+)?)", t)
    size = tuple(sorted(float(v) for v in body.groups())) if body else None
    return chip.group(1) if chip and not fam else None, fam, pins, size


def package_check(footprint, package):
    """('ok' | 'mismatch' | 'unverified', note): does a KiCad footprint fit JLCPCB's package for the part?"""
    if not footprint or not package:
        return "unverified", "no footprint or package to compare"
    fc, ff, fp, fs = _shape(footprint)
    pc, pf, pp, ps = _shape(package)
    def name(f, n):
        return f if n is None or f.endswith(f"-{n}") else f"{f}-{n}"
    if fc and pc:
        return ("ok", f"chip {fc}") if fc == pc else ("mismatch", f"chip {fc} vs {pc}")
    if (fc and pf) or (pc and ff):
        return "mismatch", f"{fc or name(ff, fp)} vs {pc or name(pf, pp)}"
    if ff and pf:
        if ff != pf or (fp is not None and pp is not None and fp != pp):
            return "mismatch", f"{name(ff, fp)} vs {name(pf, pp)}"
        if fs and ps and any(abs(a - b) > 0.15 for a, b in zip(fs, ps)):
            return "mismatch", f"body {fs} vs {ps}"
        return "ok", name(ff, fp if fp is not None else pp)
    return "unverified", f"can't compare '{footprint}' with '{package}': check by hand"


def check_rows(rows, boards=5, attrition=0.1, find=lookup):
    report, problems, notes = [], 0, []
    for row in rows:
        need = math.ceil(int(row["qty"]) * boards * (1 + attrition))
        item = find(row["lcsc"])
        flags = []
        if item is None:
            stock, library, price, found, package = 0, "-", None, "", ""
            flags.append("NOT FOUND")
        else:
            stock = item["stockCount"]
            library = {"base": "basic"}.get(item["componentLibraryType"], item["componentLibraryType"])
            prices = item.get("componentPrices") or [{}]
            price = prices[0].get("productPrice")
            found = item["componentModelEn"]
            package = item.get("componentSpecificationEn") or ""
            if row.get("mpn") and normalise(row["mpn"])[:8] not in normalise(found):
                flags.append(f"MPN MISMATCH ({found})")
            elif stock < need:
                flags.append("LOW STOCK")
        fp = row.get("footprint") or row.get("Footprint") or ""
        verdict, pnote = package_check(fp, package) if item else ("unverified", "")
        if verdict == "mismatch":
            flags.append(f"PACKAGE MISMATCH ({pnote})")
        elif verdict == "unverified" and fp and item:
            notes.append(f"{row['lcsc']}: {pnote}")
        life = (row.get("lifecycle") or "").strip()
        if BAD_LIFECYCLE.search(life):
            flags.append(f"LIFECYCLE {life}")
        alts = [a for a in re.split(r"[\s;,]+", row.get("alt_lcsc") or "") if a]
        alt_stock = {}
        for alt in alts:
            hit = find(alt)
            alt_stock[alt] = hit["stockCount"] if hit else None
        if library == "expand" and not alts:
            notes.append(f"{row['lcsc']} ({found or row.get('mpn', '')}): extended part with no alternate (alt_lcsc)")
        status = "; ".join(flags) or "ok"
        problems += bool(flags)
        report.append({**row, "need": need, "stock": stock, "library": library, "unit_price": price,
                       "jlc_mpn": found, "package": package, "package_check": verdict, "alternates": alt_stock,
                       "status": status})
    return report, problems, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bom")
    parser.add_argument("--boards", type=int, default=5)
    parser.add_argument("--attrition", type=float, default=0.1)
    parser.add_argument("--json")
    args = parser.parse_args()

    with open(args.bom, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    report, failures, notes = check_rows(rows, args.boards, args.attrition)
    print(f"{'LCSC':>9} {'MPN':30} {'need':>5} {'stock':>8} {'lib':8} {'unit $':>7} {'package':14}  status")
    for r in report:
        price_text = f"{r['unit_price']:7.3f}" if r["unit_price"] is not None else "      -"
        print(f"{r['lcsc']:>9} {(r.get('mpn') or '')[:30]:30} {r['need']:5d} {r['stock']:8d} {r['library']:8} "
              f"{price_text} {r['package'][:14]:14}  {r['status']}")
        for alt, s in r["alternates"].items():
            print(f"{'':>9}   alternate {alt}: {'not found' if s is None else f'stock {s}'}")
    for n in notes:
        print("note:", n)
    total = sum((r["unit_price"] or 0) * int(r["qty"]) for r in report)
    extended = sum(1 for r in report if r["library"] == "expand")
    print(f"\n{len(report)} lines, {extended} extended parts, about ${total:.2f} per board (1-off prices), "
          f"{failures} problem(s) for {args.boards} boards. Lifecycle comes from the BOM's lifecycle column "
          "(JLCPCB's parts endpoint has none).")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"checked": time.strftime("%Y-%m-%d"), "boards": args.boards, "lines": report, "notes": notes},
                      handle, indent=2)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
