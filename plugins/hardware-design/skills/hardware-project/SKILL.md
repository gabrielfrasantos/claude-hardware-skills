---
name: hardware-project
description: Run a KiCad 10 board project the embedded-pro way - scaffold the repo (CLAUDE.md, requirements traced to firmware, decisions log, phase-gated plan, reviewer agent with a per-board rubric, schgen config, pin needs), check requirement traceability, and produce the review, BOM, JLC stock, JLCPCB and release packages and visual diffs with shared scripts instead of per-repo copies.
---

# Hardware project (KiCad 10+)

Use this skill to start a board repo, to keep its requirements, decisions and gates in order, and to export what reviewers, the fab and a release need. The other skills say how to design. This one says how the project runs, and it holds the scripts that each board repo used to copy.

Scripts are in `scripts/` (Python 3). The exports need KiCad 10's `kicad-cli` (and PyMuPDF for PNG views and visual diffs). The stock and datasheet scripts need network access to JLCPCB/LCSC. `scaffold.py` and `trace.py` need nothing.

## 1. Repo layout

Every script runs from anywhere inside a board repo laid out like e-psu, e-foc and e-inverted-pendulum:

```
hardware/<board>/<board>.kicad_pro   the KiCad project (several boards: one folder each)
scripts/schgen/                      the schematic as code (schematic-capture)
docs/                                requirements.md, decisions.md, plan.md, design-guide.md, bringup.md
pin-data/                            pin-needs.txt (firmware), pinmap.txt (after placement)
simulation/                          SPICE suite and REPORT.md (circuit-simulation)
bom/                                 bom.csv, bom_jlc.csv, stock check
evals/cases/                         eval cases for the plugin (optional)
.claude/                             settings.json (the plugin), agents/<board>-board-reviewer.md
```

The root is the git top level (or `$HW_PROJECT_ROOT`). The board is the only one under `hardware/` (or `$HW_BOARD`, or `--name`). Outputs go to `review_exports/`, `manufacturing/`, `release/`, `bom/` and `datasheets/`; the scaffold's `.gitignore` covers the generated ones.

## 2. Start a board

```bash
python3 scripts/scaffold.py ../my-board --name my-board --title "my-board: what it is" \
        --firmware owner/my-firmware --fab jlcpcb --layers 4 --owner "my org"
```

It writes the files above and **never overwrites** one that exists, so it also fills the gaps of an existing repo. Then:
1. Create the KiCad project at `hardware/<board>/<board>.kicad_pro` (*File → New Project*).
2. Commit `.claude/settings.json`, so teammates get the plugin.
3. Start Phase 0 in `docs/plan.md`.

## 3. Requirements, decisions, gates

- **Requirements** (`docs/requirements.md`): one table row per hardware requirement, `| HW-<AREA>-<NNN> | requirement | source | verify |`.
  - **Source:** a firmware `REQ-*`, a firmware file:line, a skill section, or a `D-xxx`.
  - **Verify:** R (review), S[n] (simulation), B (bring-up) or T (test). Notes go in parentheses: `B (VNA, RSSI)`.
- **Decisions** (`docs/decisions.md`): `| D-<NNN> | decision | rejected | rationale |`. A changed decision gets a new row, and the old one is marked **Superseded by D-xxx (date)**; it is never edited away.
- **Phases and gates** (`docs/plan.md`): Phase 0 (requirements, sizing), 1 (schematic), 2 (simulation), 3 (layout), 4 (fab, bring-up). Each gate lists the commands that must pass and ends with the **owner's sign-off**; the next phase does not start before it. Two checks sit between gates: after the pin-map freeze in Phase 3, the Phase 1 checks run again (the schematic changed); before ordering, the fab's own DFM report is reviewed and the order options (impedance control, via-in-pad, inner copper, IPC class) match the design. `requirements.md` has a Manufacturing section for the fab, the IPC acceptance class, test access and the EMC and safety standards.
- **`trace.py`** checks traceability at every gate:
  ```bash
  python3 scripts/trace.py --firmware ../my-firmware
  ```
  - **Errors (exit 1):** duplicate IDs; a requirement without a source or a verification method; an unknown verification method; a cited `D-xxx` that doesn't exist; with `--firmware`, a cited `REQ-*` the firmware repo doesn't contain.
  - **Warnings:** a requirement citing a superseded decision; decisions no requirement cites.

  On e-inverted-pendulum it passes (33 requirements, 61 decisions), with 7 requirements that still cite a superseded decision.
- **`PROJECT_CONTEXT.md`**: the short state of the project, to paste into a new conversation. Update it at every gate.

## 4. Review

The scaffold writes `.claude/agents/<board>-board-reviewer.md`. It is read-only and reviews only the exported package (`export_review.py` → `review_exports/<board>/`: schematic PDF, BOM, ERC, DRC, design rules, Gerbers, PCB images, and `review/` from `design-review`: the scripted checks' `findings.json` and the netlist, which it triages first). Pass the supply voltages the net names don't state: `export_review.py --voltage VBAT=12.6`:
- **Contract:** `docs/requirements.md`.
- **Evidence:** `simulation/REPORT.md`.
- **Intent:** `docs/decisions.md`.
- **Rubric:** `docs/design-guide.md`.

Write the board-specific part of the rubric in the design guide (its risks, operating points and go/no-go list), and cite the skills for the generic rules instead of copying them. The agent checks the package's freshness and the phase, and never moves the owner's parts. It reports BLOCKER / MAJOR / MINOR / NOTE findings with anchors, and gives a go / conditional-go / no-go verdict that the owner signs off.

## 5. Exports and checks

| Script | Output | Needs |
|---|---|---|
| `export_review.py [--name B]` | `review_exports/<board>/`: schematic PDF, BOM, ERC, DRC (with parity), Gerbers, board stats, design rules, PCB views | kicad-cli, PyMuPDF |
| `export_bom.py` | `bom/bom.csv` (stock check), `bom/bom_jlc.csv` (JLC assembly), grouped by LCSC number, DNP left out | kicad-cli |
| `jlc_stock.py bom/bom.csv --boards 5` | stock, Basic/Extended, price per line; fails on short stock, an MPN that doesn't match the LCSC number, a footprint that doesn't fit JLCPCB's package for the part (chip size, family, pin count; the D19 check), or a BOM `lifecycle` of NRND/EOL/obsolete/LTB. Checks the stock of `alt_lcsc` second sources and lists extended parts with none. JLCPCB's endpoint has no lifecycle field: record it in the BOM from the manufacturer or distributor | network |
| `fetch_datasheet.py <LCSC…>` or `--bom` | datasheets into `datasheets/` (gitignored) | network |
| `export_jlcpcb.py [--stock-check]` | `manufacturing/<board>/`: Gerber zip, JLC BOM and CPL | kicad-cli |
| `export_release.py [--version v1.0]` | `release/<board>-<version>.zip`: schematic PDF, board-view PDFs, Gerbers and drill, JLC BOM and CPL, for a GitHub Release | kicad-cli |
| `visual_diff.py --old-root ../base --new-root .` | `diff/`: rendered before/after/overlay of the schematic and layers, for a PR | kicad-cli, PyMuPDF |

These are the scripts e-foc and e-inverted-pendulum carried as copies, taken from the newer pendulum versions. The only change is how they find the repo root and the board (`project.py`), so they run from the plugin unchanged. A board repo deletes its copies and calls these.

## 6. Checklist

- [ ] Repo scaffolded; KiCad project created; `.claude/settings.json` committed.
- [ ] Every gate: `trace.py` passes; superseded citations fixed; `PROJECT_CONTEXT.md` updated; sign-off recorded in `docs/plan.md`.
- [ ] Before a review: `export_review.py` run after the last board edit; the design guide's go/no-go list current.
- [ ] Before an order: `export_bom.py`, `jlc_stock.py` green for the build quantity (packages, lifecycle, alternates), `place.py gate` assembly checks clean, `export_jlcpcb.py`, rotations checked in the fab's viewer, the fab's DFM report reviewed; `export_release.py` for the tag.

## 7. References

- The project pattern of embedded-pro/e-psu-hardware, e-foc-hardware and e-inverted-pendulum-hardware (plan, decisions, requirements traced to firmware, reviewer agents, export scripts).
- docs/design.md D12, D27.
- Not run in this skill's build environment (no KiCad 10, no network): the kicad-cli exports, the JLC stock lookup and the datasheet fetch. Their logic is unchanged from the board repos where they ran.
