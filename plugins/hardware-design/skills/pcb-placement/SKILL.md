---
name: pcb-placement
description: Place the unlocked footprints of a KiCad 10 board around the owner's locked anchors with a simulated-annealing optimizer (ratsnest length, decoupling distance, no overlaps, keep-outs respected), refine it, render it, and gate the result against a baseline; then assign the MCU's pins from the placement within what the firmware needs (alternate functions, peripheral instances, EXTI lines) and write the pin map.
---

# PCB placement (KiCad 10+)

Use this skill after *Update PCB from Schematic*, when the owner has placed and locked the anchors and the rest of the parts wait in a staging area, and whenever a placement needs judging before routing. Bad placement is what makes routing need too many vias; fix it here, not in the router.

The scripts are `scripts/place.py` (placement) and `scripts/pins.py` (pin assignment); they need `pip install shapely numpy scipy matplotlib`. It reads and writes the `.kicad_pcb` directly, shares the board parser of `pcb-design-rules`, and never moves a locked footprint.

## 1. Working agreement

- **The owner places and locks the anchors** (`power-pcb-layout` §1): connectors, mechanical parts, the power stage, heatsinked parts, the MCU, vendor reference copies. Locked means locked: the optimizer never moves them.
- **Intent the metrics cannot see must be written into the board before optimizing**, or the optimizer will undo it:
  - arrangements (an LED ring, a row of test pads, a connector's ESD chain in signal order) → place and **lock** them, or move only other parts with `--only`;
  - areas that must stay free (a bracket strip, the battery's footprint, an antenna's clearance) → a **rule area that forbids footprints** (*Place → Rule Area*, *Footprints* not allowed). DRC custom rules are not seen by the optimizer.
- **You (Claude) place the rest**: optimizer first, then your own refinement following the domain skills, then the owner's review of the rendered result. The gate's numbers alone never approve a placement.

## 2. Workflow

1. **Look first.** `place.py render board.kicad_pcb before.png` and read the image: what is locked, where the free area is, which keep-outs exist. Ask the owner to lock or fence any intent that is missing (§1).
2. **Optimize.**
   ```bash
   python3 scripts/place.py optimize hardware/board/board.kicad_pcb            # all unlocked parts, ~40 s per 160
   python3 scripts/place.py optimize board.kicad_pcb --only C301,C302,R305     # just these
   ```
   Parked parts start at the centre of their connections; annealing moves and swaps them; each part still in conflict then goes to the nearest legal spot on a 0.05 mm grid. Try two or three `--seed` values and keep the best gate result. `--effort 10` searches longer (about 2 min per 160 parts).
3. **Render again and look.** Check what the cost does not see (§3): decoupling capacitors on the IC's side and at its pins (`mcu-circuit-design` §2), hot loops closed tight (`power-pcb-layout` §3), crystal next to its pins, ESD at the connector (`interface-layout` §2), RF and vendor copies untouched (`rf-layout`), rotation for short escapes. Fix those by hand in KiCad or with `--only`.
4. **Refine** what you changed: `place.py optimize board.kicad_pcb --refine`. It improves locally and writes only if ratsnest and crossings both get no worse.
5. **Gate** before routing:
   ```bash
   python3 scripts/place.py gate board.kicad_pcb --baseline accepted.json --report placement.md
   ```
   Keep the JSON (`--json`) of each placement the owner accepts as the next baseline.
6. **Owner review** with the before/after renders and the gate report. Optionally `place.py propose board.kicad_pcb`: it frees the anchors too, refines, and lists anchor moves that would help, or says to keep them. It writes nothing.

## 3. What the optimizer sees and what it does not

| Sees | Does not see |
|---|---|
| ratsnest length of every signal net (Manhattan MST of its pads; ground and poured nets are planes and left out) | rotation and side: both are kept; rotate parts yourself, then `--refine` |
| decoupling capacitor to the nearest IC pad on its supply, weighted × 2 | which IC pin a capacitor belongs to beyond "nearest on its net" |
| courtyard overlaps, the board outline inset by `--edge-mm` (0.5), footprint keep-outs | assembly spacing beyond courtyards; DRC custom rules; thermal, mechanical, RF or hot-loop intent |
| | ratsnest crossings (the gate measures them; the cost does not) |

## 4. Gate

| Metric | Meaning |
|---|---|
| `parts_off_board` | unlocked parts with a pad outside the outline (locked parts parked off the board are the owner's) |
| `overlaps` | courtyard pairs that overlap, real outlines (pairs of two locked parts are the owner's) |
| `keepout_violations` | footprints in a rule area that forbids footprints |
| `ratsnest_mm` | sum of the Manhattan MST of each signal net's pads |
| `crossings` | crossings between straight ratsnest edges of different nets: an estimate of the vias routing will need |
| `decap_p90_mm` | 90th percentile of the decoupling-capacitor distances |

Valid = the first three are 0. With `--baseline`, ratios for the last three. The gate is **report-only** until the evals set its limits (docs/design.md D25: no worse than the human baseline + 10 % on ratsnest and crossings); `--enforce` exits 1 when invalid or above `--limit`.

**Measured** on the e-inverted-pendulum board (161 parts parked, 84 anchors: connectors, holes, the three vendor copies; evals fixture), against the owner's placement:

| | Ratsnest | Crossings | Decoupling p90 | Time |
|---|---|---|---|---|
| Owner | 3541 mm | 735 | 24.7 mm | |
| `optimize` (seeds 1, 2) | 3257, 3231 mm | 568, 704 | 6.5, 8.5 mm | ~40 s |
| `optimize --effort 10` | 3101, 3021 mm | 578, 495 | 6.0, 6.2 mm | ~2 min |

Better on every number, and still not acceptable as it stands: it scattered the owner's LED rings and put parts in the motor-bracket strip, which that board protects with a DRC rule, not a footprint keep-out. That is §1 in practice.

## 5. Pin assignment (`pins.py`)

Hardware is hard to change and firmware is easy, so **the hardware picks the pins**, within what the firmware needs (docs/design.md D8, §4). The order:

1. The schematic connects the MCU through **function nets** (`IMU_SCK`, `ENC_L_A`) whose MCU pin is still open, or through the current pins if the board already has them.
2. Place the anchors and the clusters (§2). The MCU is usually an anchor.
3. Write the firmware's needs as text, one function per line, named like its net:
   ```
   # function     signals                               group
   DRV_AIN1       TIM1_CH1|TIM1_CH2|TIM1_CH3|TIM1_CH4    any free TIM1 channel
   IMU_SCK        SPI{n}_SCK                            imu   one SPI instance for the bus
   IMU_MISO       SPI{n}_MISO                           imu
   IMU_MOSI       SPI{n}_MOSI                           imu
   ENC_L_A        TIM{t}_CH1|LPTIM{t}_IN1               enc_l a TIM pair or an LPTIM pair
   ENC_L_B        TIM{t}_CH2|LPTIM{t}_IN2               enc_l
   IMU_INT        EXTI                                  any pin; its interrupt line must be free
   VBAT_SENSE     ADC1_IN*
   DRV_NFAULT~2   EXTI                                  a second pin on the same net
   SWDIO          SYS_JTMS-SWDIO
   BOOT0          PH3                                   an exact pin
   ```
   The `pins.py` docstring has the full syntax. Signal names are the MCU symbol's alternate functions: KiCad's STM32 symbols carry all of them (from ST's STM32_open_pin_data), and `pins.py` reads them from the symbol embedded in the project's schematic. For other vendors, pass `--pin-data` with a CSV of `number,name,alternates`, extracted once from the datasheet with its page cited.
4. **Assign:**
   ```bash
   python3 scripts/pins.py assign hardware/board/board.kicad_pcb --mcu U301 --needs pin-needs.txt --out pinmap.txt
   ```
   Each function's target is the centroid of its net's other pads. Functions go to free I/O pads by minimum total distance (Hungarian assignment), over every choice of peripheral instances, with each signal and each EXTI line used once. Pads on other nets (supplies, crystal, debug not in the needs) are never used. The pin map is plain text (function, pin, pad, signal, package side, distance) and states the instances chosen and the current assignment's distance. When nothing fits, it lists each function's candidate pins, which usually shows the conflict (e.g. two encoders needing the only free timer).
5. **Write it back:** connect the MCU pins in the schematic as the map says (with schgen, edit the design file), rebuild, *Update PCB from Schematic*, and log the pin-map freeze as a decision. Give `pinmap.txt` to the firmware.
6. **Check** any assignment against the needs: `pins.py check board.kicad_pcb --mcu U301 --needs pin-needs.txt` exits 1 if a function sits on a pin without its signal, a group mixes instances, or a signal is on two pins.

Measured on e-inverted-pendulum (37 functions, STM32WB55 VFQFPN68, 47 free I/O pads): `check` passes the board's pin map. With the needs stated as capabilities, `assign` finds a map with 1378 mm total distance against 1465 mm for the current one (−6 %), in under 2 s. The gain is small because that board was placed around its pins. The tool's value is on a new board, where the clusters are placed first.

**Limits:**
- Distance is straight-line pad to cluster centroid. It does not order pins to avoid crossings within a bus.
- It does not know which peripherals clash in use: a timer used for PWM is still offered for an encoder on its other channels. Say so in the needs with exact signals.
- Clock trees, DMA channels and analog domains are the firmware's to confirm.

## 6. Checklist

- [ ] Anchors and intent locked; free areas fenced with footprint keep-outs.
- [ ] `render` read before and after; seeds compared; the domain skills' placement rules checked by eye.
- [ ] `gate` valid; ratios against the last accepted placement reported.
- [ ] Owner reviewed the renders; the accepted placement's JSON kept as the next baseline.
- [ ] Pin needs written from the firmware; `assign` run after placement; map written back to the schematic and logged as a decision; `check` passes.

## 7. References

- docs/design.md D7, D15, D25 (working agreement, optimizer then refinement, report-only gate).
- `power-pcb-layout` §1 (anchors), `pcb-design-rules` §5 (0.05 mm grid), `mcu-circuit-design` §2 (decoupling).
- Measurements in §4 and §5: `place.py` and `pins.py` on embedded-pro/e-inverted-pendulum-hardware at 51a4bcf (the evals fixture for placement), 2026-11-20.
- ST, STM32_open_pin_data (github.com/STMicroelectronics/STM32_open_pin_data): the source of KiCad's STM32 symbols' alternate functions.
