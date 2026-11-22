# stepper-ble

A 24 V bipolar stepper driver with Bluetooth LE, designed from scratch with the `hardware-design` skills of this
repository and nothing else: the worked example. It is **placed, not routed** (D-027).

| | |
|---|---|
| Input | 24 V nominal, 30 V max, 2-pin terminal; 3 A fast fuse, reverse-polarity N-FET, SMAJ33A clamp |
| Motor | one bipolar stepper, 2.0 A peak per phase: DRV8711 + 8 x CSD18543Q3A, 0.1 ohm low-side sense, stall detection, NTC on the FETs |
| Logic | LMR36510 5 V buck OR-ed with USB VBUS, AP2112K 3.3 V |
| MCU, radio | STM32WB55CGU6 (SMPS mode, 32 MHz HSE, 32.768 kHz LSE), MLPF-WB55-01E3, TI SWRA117D PCB antenna with a DNP tuning pi |
| Interfaces | USB-C 2.0 full-speed sink with USBLC6, SWD on a Tag-Connect TC2030 land, two LEDs, a button |
| Board | 80 x 60 mm, 4 layers SIG/GND/GND/SIG (JLC04161H-7628, 1.6 mm), JLCPCB fab and assembly, IPC Class 2, 106 parts |

Contract: `docs/requirements.md` (26 requirements); intent: `docs/decisions.md` (27 decisions); status:
`docs/plan.md`. Every value on the schematic carries its source in a note on its sheet.

## Layout of this folder

```
scripts/make_library.py     project library: DRV8711 and MLPF symbols, MLPF land, two adapted KiCad footprints (D-016)
scripts/schgen/             the schematic as code: config.py, design/<sheet>.py, parts.py (the BOM), expected.json
scripts/make_board.py       board from KiCad's netlist with pcbnew: build/update, outline, stack-up, zones, placement
pin-data/                   pin-needs.txt (from the requirements, D-017) and pinmap.txt (pins.py, frozen D-014)
hardware/stepper-ble/       KiCad 10 project; placement-baseline.json is the accepted placement's gate metrics
bom/                        bom.csv, bom_jlc.csv (export_bom.py)
```

## Reproduce

From this folder, with KiCad 10 (`kicad-cli` and its `pcbnew` Python module) and `pip install -r ../../requirements.txt`:

```bash
HW=../../plugins/hardware-design/skills
export HW_PROJECT_ROOT=$PWD                    # the hardware-project scripts otherwise take the repository root
python3 scripts/make_library.py
python3 $HW/schematic-capture/scripts/schgen.py build scripts/schgen/config.py
python3 $HW/schematic-capture/scripts/schgen.py check scripts/schgen/config.py
python3 $HW/pcb-copper/scripts/netclasses.py assign hardware/stepper-ble/stepper-ble.kicad_pro
/usr/bin/python3 scripts/make_board.py build   # needs pcbnew: system Python
/usr/bin/python3 scripts/make_board.py place
python3 $HW/pcb-design-rules/scripts/pcb_rules.py apply hardware/stepper-ble/stepper-ble.kicad_pro --fab jlcpcb --netclasses
python3 $HW/pcb-copper/scripts/netclasses.py apply hardware/stepper-ble/stepper-ble.kicad_pro
python3 $HW/pcb-design-rules/scripts/silk.py apply hardware/stepper-ble/stepper-ble.kicad_pcb
```

The pin map was found with `pins.py assign ... --out pin-data/pinmap.txt` after a first placement; the schematic
reads it, so a second `build` / `make_board.py build` / `place` closes the loop (pcb-placement §5). The impedance
classes' widths (D-025) were written into the `.kicad_pro` by hand after `netclasses.py apply`.

## Gates

The CI job `example-board` runs these. Results on 2026-11-22, KiCad 10.0.8:

| Gate | Result |
|---|---|
| `schgen.py build` | 7 sheets, 106 parts, layout lint 0 |
| `schgen.py check` | netlist matches intent, 77 nets |
| KiCad ERC | 0 violations |
| `sync.py --check` | the board is in step with the schematic (no footprint would change) |
| `library_check.py` | PASS (no pin without pad, no pad without pin, every BOM part with LCSC and MPN) |
| `pcb_rules.py check --allow-unrouted --gate zone_islands=2` | PASS: 0 shorts, 0 clearance, 0 below fab minimum, 0 DRC errors, schematic parity 0 errors; soft: `gnd_via_max_distance_mm` (no vias yet) |
| `netclasses.py check` | PASS |
| `silk.py check` | PASS; KiCad DRC reports no silkscreen findings |
| `place.py gate --enforce --baseline` | valid, ratios 1.00; assembly spacing 0; ratsnest 1475 mm, 231 crossings |
| `pins.py check --mcu U401` | PASS, 21 of 21 functions |
| `trace.py` | PASS, 26 requirements, 27 decisions |
| `review.py --allow-unrouted --voltage VM=30 --voltage VIN_RAW=30` | 0 BLOCKER, 0 MAJOR, 12 MINOR, 3 NOTE |
| `jlc_stock.py bom/bom.csv --boards 5` (not in CI) | 0 problems; 44 lines, 28 extended parts |

The board is not routed, so `--allow-unrouted` leaves KiCad's unconnected items out. The MINORs are DC-bias screening on the 50 V and 6.3 V MLCCs (D-004, OI-4) and connector nets
without an ESD part (VIN_N, CC1/CC2, the TC2030 land: D-003, D-008, D-009).

## What was not checked

- **Nothing is routed**: no hot loop, Kelvin pair, RF line, USB pair or stitching exists yet; the layout rules that
  need copper (power-pcb-layout §3-§5, rf-layout §2, interface-layout §3-§4) are only prepared by the placement.
- **No simulation** (S1 input transients, S2 current regulation): D-004 (50 V capacitors under the 53.3 V clamp) and
  D-013 (phase-pin negative swing, no clamps) are open risks.
- **Impedance widths** are derived from closed forms, not JLCPCB's calculator (D-025, OI-1).
- **Footprint checks by eye**: the MLPF land against DS12804 Fig. 13 and the adapted NexFET land against SLPS633 §7.2
  were written from the drawings; neither was compared on a printed board. `jlc_stock.py` could not compare 13
  package names automatically (listed as "check by hand").
- **Terminal-block orientation**: the wire entry is taken to be the footprint's +y side (from its fab drawing); the
  3D models were not installed, so no render confirmed it.
- **L201 saturation current** (OI-3) and the DRV8711 V5 capacitor value (OI-5) are unresolved datasheet questions.
- **The reviewer agent** (`.claude/agents/stepper-ble-board-reviewer.md`) has not reviewed the board; `review.py`'s
  scripted checks have.
- **Reversed 24 V with USB connected** is not protected (D-003).
- No gate is signed off by an owner (`docs/plan.md`).
