#!/usr/bin/env python3
"""Check every LCSC part in a BOM CSV against JLCPCB's live parts library.

For each line it reports stock, basic/extended library type and unit price. It fails when stock
can't cover qty * boards * (1 + attrition), or when the LCSC number resolves to a different
manufacturer part number than the BOM states.

Usage: jlc_stock.py bom/parts.csv [--boards 5] [--attrition 0.1] [--json out.json]
"""

import argparse
import csv
import json
import math
import sys
import time
import urllib.request

URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bom")
    parser.add_argument("--boards", type=int, default=5)
    parser.add_argument("--attrition", type=float, default=0.1)
    parser.add_argument("--json")
    args = parser.parse_args()

    with open(args.bom, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    report, failures = [], 0
    print(f"{'LCSC':>9} {'MPN':30} {'need':>5} {'stock':>8} {'lib':8} {'unit $':>7}  status")
    for row in rows:
        need = math.ceil(int(row["qty"]) * args.boards * (1 + args.attrition))
        item = lookup(row["lcsc"])
        if item is None:
            status, stock, library, price, found = "NOT FOUND", 0, "-", None, ""
        else:
            stock = item["stockCount"]
            library = {"base": "basic"}.get(item["componentLibraryType"], item["componentLibraryType"])
            prices = item.get("componentPrices") or [{}]
            price = prices[0].get("productPrice")
            found = item["componentModelEn"]
            status = "ok"
            if normalise(row["mpn"])[:8] not in normalise(found):
                status = f"MPN MISMATCH ({found})"
            elif stock < need:
                status = "LOW STOCK"
        if status != "ok":
            failures += 1
        report.append({**row, "need": need, "stock": stock, "library": library, "unit_price": price,
                       "jlc_mpn": found, "status": status})
        price_text = f"{price:7.3f}" if price is not None else "      -"
        print(f"{row['lcsc']:>9} {row['mpn'][:30]:30} {need:5d} {stock:8d} {library:8} {price_text}  {status}")

    total = sum((r["unit_price"] or 0) * int(r["qty"]) for r in report)
    extended = sum(1 for r in report if r["library"] == "expand")
    print(f"\n{len(report)} lines, {extended} extended parts, about ${total:.2f} per board (1-off prices), "
          f"{failures} problem(s) for {args.boards} boards")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"checked": time.strftime("%Y-%m-%d"), "boards": args.boards, "lines": report}, handle, indent=2)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
