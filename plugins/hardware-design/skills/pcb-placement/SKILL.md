---
name: pcb-placement
description: Build or update a KiCad 10 board from its schematic without KiCad's window (footprints, fields, nets), then place the unlocked footprints around the owner's locked anchors with a simulated-annealing optimizer (ratsnest length, decoupling distance, no overlaps, keep-outs respected), refine it, render it, and gate the result against a baseline and the assembler's rules (JLCPCB package-pair spacing, edge keep-outs, fiducials, orientation); then assign the MCU's pins from the placement within what the firmware needs (alternate functions, peripheral instances, EXTI lines; boot and SWD pins reserved) and write the pin map.
---

# PCB placement (KiCad 10+)

Use this skill to bring the schematic onto the board (§0), then when the owner has placed and locked the anchors and the rest of the parts wait in a staging area, and whenever a placement needs judging before routing. Bad placement is what makes routing need too many vias; fix it here, not in the router.

The scripts are `scripts/sync.py` (schematic to board), `scripts/place.py` (placement) and `scripts/pins.py` (pin assignment); `sync.py` needs only Python and `kicad-cli`, the others they need `pip install shapely numpy scipy matplotlib`. It reads and writes the `.kicad_pcb` directly, shares the board parser of `pcb-design-rules`, and never moves a locked footprint.

## 0. Board from the schematic (`sync.py`)

KiCad's *Tools → Update PCB from Schematic* without KiCad's window, for CI and headless agents. `kicad-cli` 10 has no such command:

```bash
python3 scripts/sync.py hardware/board/board.kicad_pcb            # schematic next to it: board.kicad_sch
python3 scripts/sync.py hardware/board/board.kicad_pcb --check    # CI: exit 1 if the board is behind the schematic
```

- It exports KiCad's netlist with `kicad-cli` (or reads `--netlist`). Footprints come from the project's `fp-lib-table` (`${KIPRJMOD}`) and then the global one (`~/.config/kicad/10.0/fp-lib-table`, `${KICAD10_FOOTPRINT_DIR}`).
- **Adds** a footprint for each new symbol. New parts are parked in rows below the board outline, packed by courtyard, so they don't overlap.
- **Updates** each footprint from the schematic:
  - reference, value and fields (LCSC, MPN, Datasheet, …), and the link back to the symbol (path, sheet);
  - DNP and BOM flags. A part left out of the BOM or not fitted is also left out of the position file;
  - each pad's net, pin function and pin type.
- **Replaces** a footprint whose library footprint changed, at the same position, rotation and lock. It refuses on the back side; replace those in KiCad.
- **Removes** footprints whose symbol is gone. Footprints the schematic never placed (no path), such as a logo or a board-only fiducial, stay.
- It rewrites only the footprints that change; every other byte of the file is kept. With no board file, it starts an empty KiCad 10 board (`--layers`, default 4).
- Outline, stack-up, zones and net classes are not its job: `pcb-design-rules`, `pcb-copper`, or KiCad.
- **Checked against KiCad 10.0.8 on the example (106 parts, 2026-11-22):**
  - On the example's own board (built with pcbnew), the result is byte for byte the same.
  - A board built from nothing has 0 schematic-parity errors in KiCad's DRC.
  - Against pcbnew's board, footprint by footprint, it gives the same footprints, pad nets, pin functions and types, fields, paths, sheets and attributes. The only difference is a fab-layer `${REFERENCE}` text: the fresh board keeps the library's text item, while pcbnew's board holds a field (likely made when `silk.py apply` hid it).

## 1. Working agreement

- **The owner places and locks the anchors** (`power-pcb-layout` §1): connectors, mechanical parts, the power stage, heatsinked parts, the MCU, vendor reference copies. Locked means locked: the optimizer never moves them.
- **Intent the metrics cannot see must be written into the board before optimizing**, or the optimizer will undo it:
  - arrangements (an LED ring, a row of test pads, a connector's ESD chain in signal order) → place and **lock** them, or move only other parts with `--only`;
  - areas that must stay free (a bracket strip, the battery's footprint, an antenna's clearance) → a **rule area that forbids footprints** (*Place → Rule Area*, *Footprints* not allowed). DRC custom rules are not seen by the optimizer.
- **You (Claude) place the rest**: optimizer first, then your own refinement following the domain skills, then the owner's review of the rendered result. The gate's numbers alone never approve a placement.
- **What a good placement looks like** (the owner's review checks these; the metrics don't):
  - Each **support part sits at the pin it serves**: next to that pin, pointing straight out from the IC with the shared pad toward the pin, lined up with the pin.
  - **One decoupling capacitor per supply pin.** Spread the capacitors over the IC's supply pins; don't stack them all at the one nearest the IC's centre.
  - **Bulk capacitors sit at the stage they feed**: a motor driver's bulk at its bridges, a buck's input capacitors at its VIN pin. The input connector is the wrong place.
  - **Parts that measure something sit at what they measure** (an NTC between the FETs), however their nets pull. Their bias and filter parts sit at the ADC pin.
  - **Leave a lane for the reference**: about 0.9 mm between neighbouring 0402s, so a 1 mm reference fits beside them. Then run `pcb-design-rules` `silk.py apply`. A reference it can't place means a part has no lane.
  - The worked example (`examples/stepper-ble/scripts/make_board.py place`) applies these rules automatically to every two- to four-pad part, around the owner's anchors.

## 2. Workflow

1. **Look first.** `place.py render board.kicad_pcb before.png` and read the image: what is locked, where the free area is, which keep-outs exist. Ask the owner to lock or fence any intent that is missing (§1).
2. **Optimize.**
   ```bash
   python3 scripts/place.py optimize hardware/board/board.kicad_pcb            # all unlocked parts, ~40 s per 160
   python3 scripts/place.py optimize board.kicad_pcb --only C301,C302,R305     # just these
   ```
   Parked parts start at the centre of their connections; annealing moves and swaps them; each part still in conflict then goes to the nearest legal spot on a 0.05 mm grid. Try two or three `--seed` values and keep the best gate result. `--effort 10` searches longer (about 2 min per 160 parts).
3. **Render again and look.** Check what the cost does not see (§3): decoupling capacitors on the IC's side and at its pins (`mcu-circuit-design` §2), hot loops closed tight (`power-pcb-layout` §3), crystal next to its pins, ESD at the connector (`interface-layout` §2), RF and vendor copies untouched (`rf-layout`), rotation for short escapes. Fix those by hand in KiCad or with `--only`.
4. **Refine** what you changed: `place.py optimize board.kicad_pcb --refine`. It improves locally: no part moves more than `--max-move` (2 mm) from where it was, and parts are never swapped. It writes only if ratsnest, crossings and the assembler's spacing violations all get no worse. A larger `--max-move` lets it undo intent the cost doesn't see (a capacitor at the FET it serves, a TVS at the connector), so render and look again after it.
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
| decoupling capacitor to the nearest load pad on its supply (an IC, U, or a transistor, Q, so a bridge's capacitors count at its FETs), weighted × 2 | which pin a capacitor belongs to beyond "nearest on its net"; a bulk capacitor that belongs at a stage with no U or Q (a connector, a fuse); room for references |
| courtyard overlaps, the board outline inset by `--edge-mm` (0.5), footprint keep-outs | the assembler's package-pair spacing and edge keep-outs (the gate checks them, §4.1; fix with `--refine` or by hand); DRC custom rules; thermal, mechanical, RF or hot-loop intent |
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

Valid = the first three are 0. With `--baseline`, ratios for the last three. The gate is **report-only** until the evals set its limits (docs/design.md D25: no worse than the human baseline + 10 % on ratsnest and crossings); `--enforce` exits 1 when invalid, above `--limit`, or on assembly spacing.

### 4.1 Assembly checks (`dfa.py`, also run by `gate`)

From the assembler's profile, `pcb-design-rules/profiles/assembly/<name>.json` (`--assembly jlcpcb` by default, `none` to skip):

| Check | Kind | Meaning |
|---|---|---|
| `assembly_spacing` | hard with `--enforce` | parts on the same side closer than the minimum for their two package classes. JLCPCB's table goes from 0.15 mm (0201/0402 pairs) to 1 mm for any chip next to a QFN and 2 mm between BGAs [JLC-SPACING]. Measured pad copper to pad copper: JLCPCB doesn't say which edges its table uses, and copper is at least as strict as bodies for chips and leaded parts. Pairs of two locked parts are the owner's. A project with its own documented spacing rule puts it in `<board>.assembly.json` next to the board (`{"source": "...", "spacing_cap_mm": 0.5, "spacing_mm": {"0603\|QFN": 0.4}}`): the cap applies to every pair, then single pairs; findings name the source |
| decoupling exceptions | info | a capacitor with one pad on ground and the other on a net of the IC it sits next to, closer than the table. The MCU vendor's "as close to the pins as possible" is electrical and wins over inspection spacing (`mcu-circuit-design` §2); the report lists them so the owner sees the trade |
| `edge_keepout` | soft | MLCCs, crystals and BGAs with copper less than 3 mm from the board edge: depaneling stress cracks them; JLCPCB calls 3–5 mm safe, more near V-cuts [JLC-SMT] |
| `fiducials_missing` | soft | populated sides with fewer than 3 fiducials (1 mm pad, 2 mm mask opening, at least 3.35 mm from the edge). JLCPCB requires edge rails (≥ 5 mm) and fiducials for standard assembly [JLC-RAILS]: put them on the board or on rails |
| `orientation_mixed` | soft | polarized parts (diodes, LEDs, polarized capacitors) outside their two most common orientations, and ICs outside their most common one: one orientation per class makes inspection easier [JLC-SMT] |
| unclassified | info | parts whose package isn't in the table (connectors, SOD, electrolytics, custom lands): not spacing-checked |

Measured 2026-11-20: on a robot-controller board, 1 spacing violation (R701 0.68 mm from a QFN), 6 decoupling exceptions at the two QFNs, no fiducials, 14 orientation outliers; on a motor-driver board, no spacing violation, no fiducials, 6 orientation outliers.

**Measured** on a real robot-controller board (161 parts parked, 84 anchors: connectors, holes, the three vendor copies; evals fixture), against the owner's placement:

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
   Each function's target is the centroid of its net's other pads. Functions go to free I/O pads by minimum total distance (Hungarian assignment), over every choice of peripheral instances, with each signal and each EXTI line used once. Pads on other nets (supplies, crystal, debug not in the needs) are never used, and neither are **reserved pins**: boot-strap pins (BOOT in the pin's name or alternates) and the SWD pins (SWDIO, SWCLK), whose level at reset and during debug matters. Name one exactly in the needs (`PA13`) or pass `--allow-reserved` to use it. Check the other pins with special reset states yourself (JTAG pins with pull-ups, pins sampled at reset): the MCU's safe-state table in `mcu-circuit-design` lists them. The pin map is plain text (function, pin, pad, signal, package side, distance) and states the instances chosen and the current assignment's distance. When nothing fits, it lists each function's candidate pins, which usually shows the conflict (e.g. two encoders needing the only free timer).
5. **Write it back:** connect the MCU pins in the schematic as the map says (with schgen, edit the design file), rebuild, *Update PCB from Schematic*, and log the pin-map freeze as a decision. Give `pinmap.txt` to the firmware.
6. **Check** any assignment against the needs: `pins.py check board.kicad_pcb --mcu U301 --needs pin-needs.txt` exits 1 if a function sits on a pin without its signal, a group mixes instances, or a signal is on two pins.

Measured on the same board (37 functions, STM32WB55 VFQFPN68, 47 free I/O pads): `check` passes the board's pin map. With the needs stated as capabilities, `assign` finds a map with 1378 mm total distance against 1465 mm for the current one (−6 %), in under 2 s. The gain is small because that board was placed around its pins. The tool's value is on a new board, where the clusters are placed first.

**Limits:**
- Distance is straight-line pad to cluster centroid. It does not order pins to avoid crossings within a bus.
- It does not know which peripherals clash in use: a timer used for PWM is still offered for an encoder on its other channels. Say so in the needs with exact signals.
- Clock trees, DMA channels and analog domains are the firmware's to confirm.

## 6. Checklist

- [ ] Anchors and intent locked; free areas fenced with footprint keep-outs.
- [ ] `render` read before and after; seeds compared; the domain skills' placement rules checked by eye.
- [ ] `gate` valid; ratios against the last accepted placement reported.
- [ ] Assembly: no spacing violation; decoupling exceptions accepted by the owner; brittle parts away from edges; fiducials on the board or rails ordered; polarized parts and ICs oriented consistently.
- [ ] Owner reviewed the renders; the accepted placement's JSON kept as the next baseline.
- [ ] Pin needs written from the firmware; `assign` run after placement; map written back to the schematic and logged as a decision; `check` passes.

## 7. References

- docs/design.md D7, D15, D25 (working agreement, optimizer then refinement, report-only gate).
- `power-pcb-layout` §1 (anchors), `pcb-design-rules` §5 (0.05 mm grid), `mcu-circuit-design` §2 (decoupling).
- Measurements in §4 and §5: `place.py` and `pins.py` on the robot-controller board (the evals fixture for placement), 2026-11-20.
- [JLC-SPACING] JLCPCB, *Minimum spacing for SMD components* (package-pair table). https://jlcpcb.com/help/article/minimum-spacing-for-smd-components
- [JLC-RAILS] JLCPCB, *How to add edge rails/fiducials for PCB assembly order*. https://jlcpcb.com/help/article/how-to-add-edge-rails-fiducials-for-pcb-assembly-order
- [JLC-SMT] JLCPCB, *Top 10 PCB Design Tips for High-Quality SMT Soldering* (orientation, edge keep-outs, thermal reliefs). https://jlcpcb.com/blog/pcb-design-tips-to-improve-smt-soldering-quality
- ST, STM32_open_pin_data (github.com/STMicroelectronics/STM32_open_pin_data): the source of KiCad's STM32 symbols' alternate functions.
