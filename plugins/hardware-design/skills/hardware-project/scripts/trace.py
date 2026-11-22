#!/usr/bin/env python3
"""trace.py: requirements traceability for a board repo (docs/requirements.md, docs/decisions.md).

    trace.py [--root .] [--firmware <path to the firmware repo>] [--allow-empty] [--json out.json]

Reads the Markdown tables:
  docs/requirements.md   | HW-<AREA>-<NNN> | requirement | source | verify |
  docs/decisions.md      | D-<NNN> | decision | rejected | rationale |   ("Superseded by D-xxx" in the row)
and checks:
  errors    a duplicate requirement or decision ID; a requirement with no source or no verification method; a
            verification that is not R (review), S[n] (simulation), B (bring-up) or T (test); a D-xxx cited that
            decisions.md does not have; with --firmware, a REQ-* cited that the firmware repo does not contain
  warnings  a requirement that cites a superseded decision (cite the decision in force); a decision that no
            requirement cites (fine for many decisions, listed so they can be looked at)
  inputs    the resolved paths are printed. A missing root or file is an error, and so is a requirements file
            with no recognized requirement: table rows with another ID (named), or empty tables (pass
            --allow-empty for a scaffold that has none yet). Rows with an unrecognized ID beside recognized ones
            are warnings. Zero requirements checked never passes by accident (a wrong --root or CI folder).
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


TABLE_ROW = re.compile(r"^\|(.*)\|\s*$")
SEPARATOR = re.compile(r"^\|[\s:|-]+\|\s*$")


def read(path, rx, other=None):
    """The table rows whose first cell matches rx. Table rows that don't (not headers, not separators) go to
    `other` as (first cell, line) when given: an ID typo there is otherwise invisible."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            m = rx.match(line)
            if m:
                rows.append((m.group(1), cells(m.group(2)), n))
            elif other is not None and TABLE_ROW.match(line) and not SEPARATOR.match(line):
                first = cells(TABLE_ROW.match(line).group(1))[0]
                if first and first.upper() != "ID":
                    other.append((first, n))
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


def check(root, firmware=None, allow_empty=False):
    """A missing root or file, or a requirements file with no recognized requirement, is an error: zero
    requirements checked must never read as a pass. allow_empty accepts a scaffold whose tables are empty."""
    root = os.path.abspath(root)
    req_path = os.path.join(root, "docs", "requirements.md")
    dec_path = os.path.join(root, "docs", "decisions.md")
    errors, warnings = [], []
    base = dict(root=root, requirements_file=req_path, decisions_file=dec_path, requirements=0, decisions=0,
                superseded=0, errors=errors, warnings=warnings)
    if not os.path.isdir(root):
        errors.append(f"root not found: {root}")
        return base
    for path in (req_path, dec_path):
        if not os.path.isfile(path):
            errors.append(f"{os.path.basename(path)}: missing ({path})")
    if errors:
        return base
    other = []
    reqs = read(req_path, REQ_ROW, other)
    decs = read(dec_path, DEC_ROW)
    if not reqs:
        if other:
            errors.append(f"requirements.md: no recognized requirement; {len(other)} table row(s) don't start with "
                          "an HW-<AREA>-<NNN> ID: " + ", ".join(f"'{c}' (line {n})" for c, n in other[:5]))
        elif allow_empty:
            warnings.append("requirements.md: no requirements yet (--allow-empty)")
        else:
            errors.append("requirements.md: no requirements (empty tables). A gate needs at least one; "
                          "--allow-empty for a fresh scaffold")
    else:
        for c, n in other:
            warnings.append(f"requirements.md:{n}: row '{c}' is not an HW-<AREA>-<NNN> ID and is not checked")
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
    return dict(base, requirements=len(reqs), decisions=len(decs), superseded=len(superseded))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--firmware", help="firmware repo checkout, to confirm cited REQ-* IDs exist")
    ap.add_argument("--allow-empty", action="store_true",
                    help="pass a requirements file whose tables have no rows yet (a fresh scaffold)")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    r = check(a.root, a.firmware, a.allow_empty)
    print(f"requirements: {r['requirements_file']}\ndecisions:    {r['decisions_file']}")
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
