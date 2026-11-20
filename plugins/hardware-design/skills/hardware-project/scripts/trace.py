#!/usr/bin/env python3
"""trace.py: requirements traceability for a board repo (docs/requirements.md, docs/decisions.md).

    trace.py [--root .] [--firmware <path to the firmware repo>] [--json out.json]

Reads the Markdown tables:
  docs/requirements.md   | HW-<AREA>-<NNN> | requirement | source | verify |
  docs/decisions.md      | D-<NNN> | decision | rejected | rationale |   ("Superseded by D-xxx" in the row)
and checks:
  errors    a duplicate requirement or decision ID; a requirement with no source or no verification method; a
            verification that is not R (review), S[n] (simulation), B (bring-up) or T (test); a D-xxx cited that
            decisions.md does not have; with --firmware, a REQ-* cited that the firmware repo does not contain
  warnings  a requirement that cites a superseded decision (cite the decision in force); a decision that no
            requirement cites (fine for many decisions, listed so they can be looked at)
Exit 1 on an error. Run it at every phase gate.
"""
import argparse
import json
import os
import re
import sys

REQ_ROW = re.compile(r"^\|\s*(HW-[A-Z0-9]+-\d+)\s*\|(.*)\|\s*$")
DEC_ROW = re.compile(r"^\|\s*(D-\d+)\s*\|(.*)\|\s*$")
VERIFY = re.compile(r"^(R|B|T|S\d*)\b")


def cells(rest):
    return [c.strip() for c in rest.split("|")]


def read(path, rx):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            m = rx.match(line.strip())
            if m:
                rows.append((m.group(1), cells(m.group(2)), n))
    return rows


def firmware_ids(path):
    ids = set()
    for base, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("build", "node_modules")]
        for name in files:
            if name.endswith((".md", ".yaml", ".yml", ".json", ".txt", ".hpp", ".cpp", ".h", ".c")):
                try:
                    with open(os.path.join(base, name), encoding="utf-8", errors="ignore") as f:
                        ids.update(re.findall(r"\bREQ-[A-Z0-9]+-\d+\b", f.read()))
                except OSError:
                    pass
    return ids


def check(root, firmware=None):
    reqs = read(os.path.join(root, "docs", "requirements.md"), REQ_ROW)
    decs = read(os.path.join(root, "docs", "decisions.md"), DEC_ROW)
    errors, warnings = [], []
    seen = {}
    for rid, _, n in reqs:
        if rid in seen:
            errors.append(f"requirements.md:{n}: {rid} also on line {seen[rid]}")
        seen.setdefault(rid, n)
    dseen, superseded = {}, {}
    for did, c, n in decs:
        if did in dseen:
            errors.append(f"decisions.md:{n}: {did} also on line {dseen[did]}")
        dseen.setdefault(did, n)
        m = re.search(r"Superseded by (D-\d+)", " ".join(c))
        if m:
            superseded[did] = m.group(1)
    fw = firmware_ids(firmware) if firmware else None
    cited = set()
    for rid, c, n in reqs:
        if len(c) < 3:
            errors.append(f"requirements.md:{n}: {rid} needs | requirement | source | verify |")
            continue
        source, verify = c[-2], c[-1]
        if not source:
            errors.append(f"requirements.md:{n}: {rid} has no source")
        if not verify:
            errors.append(f"requirements.md:{n}: {rid} has no verification method")
        else:
            plain = re.sub(r"\([^)]*\)", "", verify)          # notes in parentheses: "B (VNA, RSSI)"
            for token in [t.strip() for t in plain.split(",") if t.strip()]:
                if not VERIFY.match(token):
                    errors.append(f"requirements.md:{n}: {rid} verification '{token}' is not R, S[n], B or T")
        for did in re.findall(r"\bD-\d+\b", source):
            cited.add(did)
            if did not in dseen:
                errors.append(f"requirements.md:{n}: {rid} cites {did}, which decisions.md does not have")
            elif did in superseded:
                warnings.append(f"requirements.md:{n}: {rid} cites {did}, superseded by {superseded[did]}")
        if fw is not None:
            for req in re.findall(r"\bREQ-[A-Z0-9]+-\d+\b", source):
                if req not in fw:
                    errors.append(f"requirements.md:{n}: {rid} cites {req}, not found in the firmware repo")
    for did in dseen:
        if did not in cited and did not in superseded:
            warnings.append(f"{did} is cited by no requirement")
    return dict(requirements=len(reqs), decisions=len(decs), superseded=len(superseded),
                errors=errors, warnings=warnings)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--firmware", help="firmware repo checkout, to confirm cited REQ-* IDs exist")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    r = check(a.root, a.firmware)
    print(f"{r['requirements']} requirements, {r['decisions']} decisions ({r['superseded']} superseded)")
    for e in r["errors"]:
        print("ERROR  ", e)
    for w in r["warnings"][:40]:
        print("warning", w)
    if len(r["warnings"]) > 40:
        print(f"warning … {len(r['warnings']) - 40} more")
    print("PASS" if not r["errors"] else f"FAIL: {len(r['errors'])} error(s)")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(r, f, indent=2)
    return 1 if r["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
