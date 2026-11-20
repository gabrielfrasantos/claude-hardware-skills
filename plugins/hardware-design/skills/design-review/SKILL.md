---
name: design-review
description: Review a KiCad 10 schematic and/or PCB - any project, scaffolded or not - by running every scripted check of the plugin into one findings file (decoupling, pull-ups, MCU strap and power pins, voltage ratings, diode and capacitor orientation, connector ESD, divider ranges, test points, ERC, library, fab and geometry gates, net classes, placement and assembly, copied vendor blocks), then having the board-reviewer agent triage them and check what scripts can't against the datasheets. Includes a seeded-defect eval to measure a review.
---

# Design review (KiCad 10+)

Use this skill to review a schematic, a PCB or both: your own board before a gate, or someone else's board. It
separates what can be checked mechanically from what needs judgment:

1. **`scripts/review.py`** runs every scripted check of the plugin on the project and writes one findings file,
   with a severity, location, rule and tool for each finding. It also lists every check that could not run.
2. **The `board-reviewer` agent** (in this plugin, or the project's own from `hardware-project`) starts from that
   file. It triages each scripted finding as confirmed, false positive or needs data. Then it reviews what scripts
   can't judge: each IC against its datasheet, ratings against the voltage ladder, protection, layout intent.

Scripts find patterns and miss intent. The agent reads datasheets but tires on 700 pins. Together they cover more
than either alone. The seeded-defect eval (§5) says how much.

The scripts read and write KiCad 10 files only and need the whole plugin installed (they run the other skills'
tools). `review.py` itself needs no KiCad: ERC, DRC and the netlist export are added when `kicad-cli` is found.

## 1. Workflow

```bash
python3 scripts/review.py <project dir | .kicad_pro> --voltage VBAT=12.6 --voltage VMOT=24
#   -> review_exports/<board>/review/{findings.json, review.md, netlist.net, <gate>.json}
```

1. **Give the supply voltages the names don't say.** `+3V3`, `5V`, `12V_IN`, `VBUS` and `_<V>V` net classes are
   read automatically; a battery or motor bus (`VBAT`, `VM`) isn't. The `unknown` note lists supply nets without a
   voltage. Rating, orientation and divider checks skip them. Use the **maximum** voltage (a charged battery, a
   mis-set charger), not the nominal one.
2. **Run `review.py`.** In a `hardware-project` repo, `export_review.py` runs it into the review package.
   `--fail-on MAJOR` turns it into a CI gate; by default it only reports.
3. **Ask for the review**: "review the schematic and PCB" uses the `board-reviewer` agent. The agent reads
   `findings.json` first, then the netlist, then the datasheets, then the images.
4. **Close each finding**: fix it, or record an accepted deviation as a decision (`hardware-project`). A false
   positive you'll see again goes into the issue tracker as a rule correction, so the check improves.

**Before layout**, a schematic alone can be reviewed: with `kicad-cli`, `review.py` exports the netlist and runs the
schematic checks and ERC; or pass a netlist with `--netlist`. Without a board there are no positions, so the
decoupling-distance check is skipped.

## 2. What runs

| Step | Tool | Needs |
|---|---|---|
| schematic | `checks.py` (§3) on the design model | a board (pin types from the board or the schematic's symbols), or a netlist |
| erc | KiCad ERC | `kicad-cli`, schematic |
| library | `schematic-capture/library_check.py`: symbol pins vs footprint pads, BOM fields | board and schematic |
| rules | `pcb-design-rules/pcb_rules.py check`: shorts, clearance, fab floor, geometry, copper; KiCad DRC with `kicad-cli` | board |
| netclasses | `pcb-copper/netclasses.py check` | board |
| placement | `pcb-placement/place.py gate` and `dfa.py`: validity, assembly spacing, edge keep-outs, fiducials, orientation | board |
| blocks | `reference-block/refblock.py check` for every `*.block.json` | board, blocks |
| stock | `hardware-project/jlc_stock.py` | `--bom`, network |

Severity in the findings: shorts, clearance and anything below the fab minimum are BLOCKER. Other hard gates are
MAJOR. House-style geometry (`pcb-design-rules` §2.3) and soft gates are MINOR. A step that couldn't run is a NOTE
with the reason.

**Boards set up outside the plugin's conventions** report the conventions as findings: net classes not in the
standard set, teardrops not turned on, a stack-up template that doesn't match. Run `pcb_rules.py apply` and
`netclasses.py apply`, or read those findings as "not set up this way", not as defects.

## 3. Scripted schematic checks (`checks.py`)

| Check | Severity | Finds | Rule |
|---|---|---|---|
| `decoupling` | MAJOR / MINOR | an IC power-input net with no capacitor to ground; with a board, a power pin with no decoupling capacitor within 6 mm. Converter switch nodes (LX, SW, PHASE) are exempt | `mcu-circuit-design` §2 [MCHP-DEC]; `analog-circuit-design` §8 |
| `pullups` | MAJOR / MINOR | an I2C net (by net or pin name) with no pull-up to a supply; an IC's open-collector output with none (it may be internal: confirm) | `mcu-circuit-design` §9 [SLVA689A], §6 |
| `mcu_pins` | MAJOR / BLOCKER | a BOOT pin floating; a VCAP pin without a capacitor to ground; a power-input pin on no net | `mcu-circuit-design` §2–§3 [AN4488][AN5093] |
| `ratings` | BLOCKER / MINOR / NOTE | a capacitor rated below the voltage across it; a class-II MLCC below 2× (screening default: check the DC-bias curve); a TVS whose standoff is below its net; capacitors with no stated rating | `power-circuit-design` §3, §9 |
| `orientation` | BLOCKER | a diode forward-biased across a supply (pin names A/K, else KiCad's pad 1 = cathode); a polarized capacitor reversed | `power-circuit-design` §3, §9 |
| `connector_esd` | MINOR | connector nets with no ESD or TVS part on them (fine for internal connectors) | `interface-layout` §2; `mcu-circuit-design` §6–§7 |
| `dividers` | MAJOR | a resistor divider whose output, into an IC pin, is above that IC's supply | `analog-circuit-design` §5–§6 |
| `test_points` | NOTE | supply and ground nets without a test point | `hardware-project` (test access; IPC-2221C §3.6, §10.2.3) |
| `unknown` | NOTE | supply nets with no known voltage | §1 |

They rely on names and types the design states: pin electrical types (power_in, open_collector) from the symbols,
net names for I2C and voltages, ratings in the value or a `Voltage` field. A design that doesn't state them gets
fewer findings, not wrong ones; the NOTEs say what was skipped. **Add a `Voltage` field to capacitors and power
parts**: it costs nothing and turns on the rating checks.

## 4. What only the reviewer can check

The agent's method is `agents/board-reviewer.md`; it covers, at least:

- **Each IC against its datasheet**: every pin's net against the pin table, the recommended application circuit
  (values, not just presence), strap pins, unused pins, exposed pads.
- **Absolute maximum ratings against the voltage ladder**, including clamped transients: `power-circuit-design` §1.
- **Protection chains**: input order, TVS clamping vs every bus part, inrush and hot plug, fuse, UVLO, safe state.
- **Interfaces**: termination, series resistors, ESD capacitance on fast lines (`interface-layout`).
- **Analog**: ADC drive impedance, references, filters (`analog-circuit-design`).
- **Layout intent**: hot loops, return paths, sensitive nets near switch nodes, thermal copper, from the images and
  the gates' coordinates (`power-pcb-layout`, `rf-layout`, `high-speed-digital-layout`).

## 5. Measuring a review: seeded defects (`evals/review_defects.py`)

```bash
python3 evals/review_defects.py run <board.kicad_pcb> [--schematic root.kicad_sch] --voltage VBAT=12.6 --out work/rd
python3 evals/review_defects.py score work/rd/manifest.json --report agent-review.md
```

`run` copies the board and plants one defect of each kind it finds a target for, each on a different part:
- decoupling removed;
- pull-up removed;
- diode reversed;
- capacitor or TVS underrated;
- boot pin floating;
- power pin open;
- divider over range.

It runs the scripted checks on the clean board and the seeded one. `score` grades any review against the planted
defects, including the agent's markdown report.

Measured 2026-11-20:

| Board | Seeded | Found by the scripts | Clean board: findings at MINOR or above |
|---|---|---|---|
| e-inverted-pendulum (board + schematic, VBAT 12.6 V) | 6 | 6 | 8: four 25 V capacitors at 12.6 V (DC-bias check), four connectors without ESD parts |
| e-foc (board; Vdrive given as 12 V, an ASSUMPTION for the run) | 5 | 5 | 8: one supply pin 10.4 mm from its capacitor, an open-collector POWER_GOOD without pull-up, six connectors |

The scripted recall is partly circular: the seeds are the kinds of defect the checks look for. It shows the checks
work on real boards, not only on synthetic ones. **The useful number is the agent's**: seed a board, have the
agent review the seeded copy, and `score --report` its output. Its misses show where the method or the rules need
work. That run costs model time and hasn't been done here.

## 6. Limits

- **Patterns, not understanding.** I2C is found by name; supply voltages by name, class or override; dividers by
  topology; diode direction by pin names or the pad-1 convention. Anything named or typed unusually is skipped.
  The NOTEs list what was skipped, and the agent reads past the patterns.
- **Netlist parser**: written to KiCad's S-expression netlist format and tested on a hand-written netlist.
  `kicad-cli`'s own export was not available where this skill was built: check the first real one.
- **One board at a time**, KiCad 10 files only (re-save older ones in KiCad 10). Altium projects: import with
  `kicad-cli pcb import` (`reference-block`); schematics from other tools are not covered.
- **No simulation here**: loop stability, transients and protection timing are `circuit-simulation`'s.

## 7. Checklist

- [ ] Supply voltages given (`--voltage`) for every net in the `unknown` note.
- [ ] `review.py` run after the last edit (in a `hardware-project` repo, via `export_review.py`).
- [ ] Every check that didn't run is understood (NOTEs), or its tool installed.
- [ ] Every BLOCKER/MAJOR/MINOR triaged by the reviewer: confirmed, false positive (with the reason) or needs data.
- [ ] Each IC checked against its datasheet by the reviewer; findings closed or recorded as accepted deviations.
- [ ] False positives that recur reported as rule corrections.

## 8. References

- The rules each check applies are the cited skills' sections, and through them their primary sources:
  - [MCHP-DEC] Microchip, PIC16(L)F18425/45 datasheet §2.2.1 (decoupling, 6 mm);
  - [SLVA689A] TI, *I2C Bus Pullup Resistor Calculation*;
  - [AN4488] / [AN5093] ST, *Getting started with STM32F4 / G4 hardware development* (BOOT0, VCAP);
  - [SLUA887A] TI bootstrap note and [VISHAY-BIAS] (MLCC DC bias);
  - [LF-SMBJ] Littelfuse SMBJ datasheet (TVS standoff).
- KiCad 10 file formats: pads carry `pinfunction` and `pintype` when the board was updated from a schematic (read
  from the e-foc board); the schematic's embedded `lib_symbols` carry pin names and types (read from the
  e-inverted-pendulum schematic).
- Measurements in §5: `review_defects.py run` on embedded-pro/e-inverted-pendulum-hardware (51a4bcf) and
  embedded-pro/e-foc-hardware, 2026-11-20.
