#!/usr/bin/env python3
"""Download datasheets for LCSC parts through the JLCPCB parts API and extract their text.

The PDFs land in datasheets/ (gitignored: vendor documents are copyrighted) as
<LCSC>_<MPN>.pdf, with a pdftotext -layout copy next to each for grep-based design work.

Usage: fetch_datasheet.py C60013 C50278 ...   or   fetch_datasheet.py --bom bom/parts.csv
"""

import argparse
import csv
import pathlib
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from jlc_stock import lookup  # noqa: E402

import project  # noqa: E402
ROOT = project.root()
TARGET = ROOT / "datasheets"


def fetch(lcsc):
    item = lookup(lcsc)
    if item is None:
        return f"{lcsc}: not found"
    url = item.get("dataManualFileAccessIdUrl") or item.get("dataManualUrl")
    if not url:
        return f"{lcsc}: no datasheet link"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", item["componentModelEn"])
    pdf = TARGET / f"{lcsc}_{name}.pdf"
    if not pdf.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "hardware-design-skills/fetch_datasheet"})
        pdf.write_bytes(urllib.request.urlopen(request, timeout=120).read())
    if pdf.read_bytes()[:4] != b"%PDF":
        pdf.unlink()
        return f"{lcsc}: download was not a PDF"
    subprocess.run(["pdftotext", "-q", "-layout", str(pdf), str(pdf.with_suffix(".txt"))], check=False)
    return f"{lcsc}: {pdf.name} ({pdf.stat().st_size // 1024} KiB)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lcsc", nargs="*")
    parser.add_argument("--bom")
    args = parser.parse_args()
    codes = list(args.lcsc)
    if args.bom:
        with open(args.bom, encoding="utf-8") as handle:
            codes += [row["lcsc"] for row in csv.DictReader(handle)]
    TARGET.mkdir(exist_ok=True)
    for code in dict.fromkeys(codes):
        try:
            print(fetch(code))
        except OSError as error:
            print(f"{code}: download failed ({error})")


if __name__ == "__main__":
    main()
