# stepper-ble: instructions for coding agents

Read by any agent that follows the AGENTS.md convention; `CLAUDE.md` imports this file for Claude Code.

stepper-ble: 24 V stepper driver with Bluetooth LE. Firmware: none. The plan, with its phases and gates, is in `docs/plan.md`: read it before changing
anything.

## 1. Skills

The `hardware-design` skills (github.com/gabrielfrasantos/hardware-design-skills; for Claude Code, the plugin registered in
`.claude/settings.json`) hold the design rules and the tools. Read the matching skill's `SKILL.md` before the work:

| Work | Skill |
|---|---|
| Project files, requirements, decisions, gates, exports, BOM and stock | `hardware-project` |
| Schematic (schgen sheets in `scripts/schgen/`), library, netlist checks | `schematic-capture` |
| MCU support circuitry, decoupling, clocks, debug, GPIO/ESD | `mcu-circuit-design` |
| Op amps, references, ADC drive, sensors | `analog-circuit-design` |
| SPICE suite in `simulation/` | `circuit-simulation` |
| Fab rules, teardrops, pours, layout-quality gate | `pcb-design-rules` |
| Net classes (`PWR_<I>A`, `GND`, `SIGNAL`, ...) | `pcb-copper` |
| Placement, MCU pin assignment | `pcb-placement` |
| Power circuits: input protection, rails, bridges, gate drive, current sense | `power-circuit-design` |
| Power stages, high-current copper | `power-pcb-layout` |
| Copying a vendor's layout block (RF, NFC, power stage) from `reference/` | `reference-block` |
| USB, CAN, RS-485, Ethernet, connector ESD | `interface-layout` |
| Memories, displays, cameras, clocks | `high-speed-digital-layout` |
| 2.4 GHz radios | `rf-layout` |

`$HW` below is the plugin's `skills/` folder (in CI: the pinned checkout, `.hw-skills/plugins/hardware-design/skills`).

## 2. Sources of truth

- **Requirement sources.** This board has no firmware repo (D-017): every row of `docs/requirements.md` traces to a
  decision in `docs/decisions.md` or a skill section. `python3 $HW/hardware-project/scripts/trace.py` checks it.
- **Decisions** live in `docs/decisions.md` (D-xxx). A changed decision gets a new row; the old one is marked
  "Superseded by D-yyy", never edited away.
- **Schematic:** `scripts/schgen/` (`python3 $HW/schematic-capture/scripts/schgen.py build scripts/schgen/config.py`).
  Values come from the design calculations; the schematic is the source for simulation and layout.
- **Pins:** the firmware's needs in `pin-data/pin-needs.txt`; the pin map `pin-data/pinmap.txt` is written by
  `pins.py assign` after placement and frozen by a decision.
- **Parts:** every BOM line has an LCSC number and an MPN (`library_check.py`); stock is checked before a gate.

## 3. Rules

- Every number needs a source: a datasheet (ID and section), an app note, a firmware file and line, or a script in
  `simulation/` that reproduces it. Unsourced numbers are marked **ASSUMPTION** and listed in the doc's open items.
- Fab and assembler: jlcpcb; 4 layers. Design rules: `pcb-design-rules` (`pcb_rules.py apply --fab jlcpcb`).
- Phases have gates (`docs/plan.md`). Do not start a phase before the owner signs off the previous gate.
- Layout: the owner places and locks the anchors; they never move (`power-pcb-layout` §1, `pcb-placement` §1).
- Visuals in docs: Mermaid or ASCII only.

## 4. Commands

```bash
python3 $HW/schematic-capture/scripts/schgen.py build scripts/schgen/config.py     # schematic
python3 $HW/schematic-capture/scripts/schgen.py check scripts/schgen/config.py     # netlist == intent
python3 $HW/schematic-capture/scripts/library_check.py hardware/stepper-ble/stepper-ble.kicad_pcb
python3 $HW/pcb-copper/scripts/netclasses.py apply hardware/stepper-ble/stepper-ble.kicad_pro
python3 $HW/pcb-design-rules/scripts/pcb_rules.py apply hardware/stepper-ble/stepper-ble.kicad_pro --fab jlcpcb --netclasses
python3 $HW/pcb-placement/scripts/place.py gate hardware/stepper-ble/stepper-ble.kicad_pcb
python3 $HW/pcb-placement/scripts/pins.py assign hardware/stepper-ble/stepper-ble.kicad_pcb --mcu U401 --needs pin-data/pin-needs.txt --out pin-data/pinmap.txt
python3 $HW/pcb-design-rules/scripts/pcb_rules.py check hardware/stepper-ble/stepper-ble.kicad_pcb --report pcb-quality.md
python3 $HW/pcb-copper/scripts/netclasses.py check hardware/stepper-ble/stepper-ble.kicad_pcb
python3 $HW/hardware-project/scripts/trace.py
python3 $HW/hardware-project/scripts/export_bom.py && python3 $HW/hardware-project/scripts/jlc_stock.py bom/bom.csv --boards 5
python3 $HW/hardware-project/scripts/export_review.py      # review_exports/stepper-ble/ for the reviewer agent
python3 $HW/hardware-project/scripts/export_jlcpcb.py      # manufacturing/stepper-ble/
```

## 5. Review

Design reviews use the `stepper-ble-board-reviewer` agent (`.claude/agents/`; other agents: follow that file as the reviewer's brief): read-only, works from
`review_exports/stepper-ble/`, with `docs/requirements.md` as the contract, `simulation/REPORT.md` as the evidence,
`docs/decisions.md` as intent and `docs/design-guide.md` as the rubric. CI is a guardrail, not a review.
