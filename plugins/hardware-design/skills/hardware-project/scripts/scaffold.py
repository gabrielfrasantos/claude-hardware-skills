#!/usr/bin/env python3
"""scaffold.py: start a board repo the way the hardware-design plugin expects (or fill in what an existing one lacks).

    scaffold.py <repo dir> --name my-board --title "my-board: what it is" --firmware owner/repo
                [--fab jlcpcb] [--layers 4] [--owner NAME] [--date YYYY-MM-DD] [--dry-run]

Writes, never overwriting a file that exists (it lists the ones it skips):
    CLAUDE.md, PROJECT_CONTEXT.md, README.md, .gitignore
    .claude/settings.json                      the plugin's marketplace, enabled for the project
    .claude/agents/<name>-board-reviewer.md    the read-only reviewer agent, rubric = docs/design-guide.md
    docs/requirements.md, decisions.md, plan.md, design-guide.md, bringup.md
    pin-data/pin-needs.txt                     the firmware's pin needs (pcb-placement pins.py)
    scripts/schgen/config.py, design/          the schematic as code (schematic-capture)
    hardware/<name>/, simulation/, bom/        empty folders
Then: create the KiCad project in hardware/<name>/ (File > New Project, <name>.kicad_pro), fill in Phase 0.
"""
import argparse
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "..", "templates")
PROFILES = os.path.join(HERE, "..", "..", "pcb-design-rules", "profiles")
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def target(rel, name):
    rel = rel.replace(os.sep, "/")
    if rel == "gitignore":
        return ".gitignore"
    if rel == "claude/agents/board-reviewer.md":
        return f".claude/agents/{name}-board-reviewer.md"
    if rel.startswith("claude/"):
        return "." + rel
    return rel


def render(text, values):
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if left:
        raise SystemExit(f"template placeholders without a value: {sorted(set(left))}")
    return text


def scaffold(repo, values, dry_run=False):
    written, skipped = [], []
    for base, _, files in os.walk(TEMPLATES):
        for f in sorted(files):
            src = os.path.join(base, f)
            rel = os.path.relpath(src, TEMPLATES)
            dst = os.path.join(repo, target(rel, values["NAME"]))
            if os.path.exists(dst):
                skipped.append(os.path.relpath(dst, repo))
                continue
            with open(src, encoding="utf-8") as fh:
                text = render(fh.read(), values) if not f.endswith(".gitkeep") else ""
            if not dry_run:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "w", encoding="utf-8") as fh:
                    fh.write(text)
            written.append(os.path.relpath(dst, repo))
    for d in (f"hardware/{values['NAME']}", "simulation", "bom"):
        path = os.path.join(repo, d)
        if not os.path.isdir(path):
            if not dry_run:
                os.makedirs(path, exist_ok=True)
            written.append(d + "/")
    return sorted(written), sorted(skipped)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo")
    ap.add_argument("--name", required=True, help="board name, kebab-case: hardware/<name>/<name>.kicad_pro")
    ap.add_argument("--title", required=True)
    ap.add_argument("--firmware", required=True, help="the firmware repo (owner/repo), the requirement source")
    ap.add_argument("--fab", default="jlcpcb", help="a pcb-design-rules profile (jlcpcb, seeed, or several: jlcpcb,seeed)")
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--owner", default="")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not NAME.match(a.name):
        sys.exit(f"--name must be kebab-case (lowercase letters, digits, dashes): {a.name}")
    known = {f[:-5] for f in os.listdir(PROFILES) if f.endswith(".json") and f != "stackups.json"}
    unknown = [f for f in a.fab.split(",") if f not in known]
    if unknown:
        sys.exit(f"--fab: no pcb-design-rules profile {unknown}; known: {sorted(known)}")
    values = dict(NAME=a.name, TITLE=a.title, FIRMWARE=a.firmware, FAB=a.fab, LAYERS=str(a.layers),
                  OWNER=a.owner, DATE=a.date)
    written, skipped = scaffold(a.repo, values, a.dry_run)
    print(f"{'would write' if a.dry_run else 'wrote'} {len(written)} in {a.repo}:")
    for w in written:
        print("  +", w)
    for s in skipped:
        print("  = kept", s)
    print(f"next: KiCad > File > New Project at hardware/{a.name}/{a.name}.kicad_pro; then Phase 0 in docs/plan.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
