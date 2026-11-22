# stepper-ble: design guide (the reviewer's rubric)

The engineering rationale behind every check the `stepper-ble-board-reviewer` agent makes. Generic rules live in the
`hardware-design` skills; this file holds only what is specific to this board: its risks, operating points and
accepted deviations. The numbers and their sources are in the schematic's notes (sheets 1-7) and `docs/decisions.md`.

## 1. Power entry and protection
- Operating points: 24 V nominal, 30 V maximum (HW-PWR-001), 3 A fuse, VC 53.3 V at the SMAJ33A's IPP.
- Risk 1: 50 V capacitors on VM under VC (D-004). Until simulation S1 bounds the clamp energy, it is a go/no-go item.
- Risk 2: the reverse FET is in the return; USB ground bypasses it (D-003).
- Layout: VM, VIN_RAW and VIN_N are pours (PWR_3A); bulk C301 at the high-side drains (power-pcb-layout §3.9).

## 2. Rails and the MCU
- LMR36510 per SNVSBD7B Table 8-1 and §8.5 layout: input caps at VIN/PGND, CBOOT and VCC caps at their pins, FB divider
  at FB. L201 Isat unverified (OI-3).
- STM32WB55: decoupling per DS11929 Fig. 16, one capacitor per pin; SMPS 2.2 uH + 10 nH; HSE trim and LSEDRV (D-006).

## 3. Motor stage
- DRV8711 external parts per SLVSC40H Fig. 20 / §10.1; current 2.0 A (D-021); safe state by R303/R304 (D-018).
- Risk 3: phase-pin negative swing with no clamps (D-013), measured at B6.
- Layout: each half-bridge's commutation loop over solid In1 ground, HF capacitors C303-C305 between half-bridges,
  shunts with Kelvin taps through NT301-NT304, NTC TH301 between the FET rows.

## 4. Radio
- IPD at RF1, 50 ohm GCPW (width to be confirmed, OI-1), tuning pi at the feed, keep-out under the antenna on all
  layers, top edge (rf-layout §2-§4). Stack-up differs from the references: VNA tuning in the enclosure (B5).

## 5. Layout priorities (for routing, not done yet)
1. Power copper: VM pour from F101/D101 to the bridge drains, C301 and U201 VIN; ground stitching.
2. Bridges: commutation loops, gate loops from the DRV8711, Kelvin pairs (SENSE class) from the inner pad edges.
3. RF line, crystal, USB pair (DIFF_90, row-short stub < 3.5 mm), SMPS loop of the WB55.
4. The rest; then teardrops, fills, `pcb_rules.py check` with no flags.

## 6. Manufacturing (jlcpcb)
- Stack-up JLC04161H-7628; impedance control ordered for RF_50 and DIFF_90; IPC Class 2; three fiducials on F.Cu.
- Project footprints adapted from KiCad's for JLCPCB and TI lands (D-016): check them in JLCPCB's DFM viewer.

## Go / no-go checklist

The reviewer marks every line ✅ / ❌ / ⚠️ / CANNOT-VERIFY / NOT-YET.

- [ ] Every HW-* requirement has evidence (review, simulation or a planned bring-up step).
- [ ] No part above its absolute maximum at any operating point in the requirements (D-004 open until S1).
- [ ] Footprints match the real packages of the LCSC parts (`jlc_stock.py` package check not yet run).
- [ ] Manufacturer layout guidance followed for every key part (to judge after routing).
- [ ] ERC and DRC clean, or every violation explained (DRC: only unconnected items, unrouted).
- [ ] `pcb_rules.py check` and `netclasses.py check` pass.
- [ ] The board reaches a safe state through reset and brown-out (D-018).
- [ ] Every BOM line in stock for the build quantity.
