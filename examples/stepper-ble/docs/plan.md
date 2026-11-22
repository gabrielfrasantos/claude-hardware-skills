# Plan: stepper-ble

stepper-ble: 24 V stepper driver with Bluetooth LE. Firmware: none. Each phase ends at a gate the **owner** signs off; the next phase does not start
before. Record each sign-off (date, conditions) in this file.

## Phase 0: requirements, sizing, mechanics
1. `docs/requirements.md`: one row per firmware requirement that constrains the hardware, plus the open items this
   board closes. `trace.py` passes.
2. Sizing in `simulation/` (`circuit-simulation`): the numbers the architecture rests on (currents, power, margins).
3. Architecture and key parts in `docs/decisions.md`; JLC stock checked for the key parts.
4. Mechanics: outline, holes, connectors, keep-outs.
5. Firmware pin needs in `pin-data/pin-needs.txt`.

Gate: requirements traced; sizing reported; key decisions logged; owner review.

## Phase 1: schematic (`schematic-capture`, one sheet per block)
Rules: `mcu-circuit-design`, `analog-circuit-design`, `power-circuit-design`, `interface-layout`, `rf-layout`.
The datasheets win. Plan test points now: every supply, ground, reset, debug and key signal reachable by a probe or
fixture (IPC-2221C §3.6, §10.2.3).

Gate:
- `schgen.py build` with no problems or lint; `schgen.py check` passes; ERC clean;
- `library_check.py` passes (every BOM part with LCSC and MPN);
- every power net has its `PWR_<I>A` / `GND` class (`pcb-copper`);
- the skills' checklists completed in `docs/checklists/phase1.md`;
- `jlc_stock.py` green for the build quantity; owner review.

## Phase 2: simulation (`circuit-simulation`)
| ID | Circuit / question | Pass criterion |
|---|---|---|
| S1 | Power entry: hot plug, inrush into C301, reverse polarity, surge into the SMAJ33A | VM below 50 V at the clamp energy the requirement sets, or a part change (D-004) |
| S2 | Current regulation and phase-node swing at 24 V, 2 A | IFS 2.0 A +-10 %; AOUTx >= -0.6 V (D-013) |

Gate: every check passes as drawn, or the proposed changes are moved into the schematic; REPORT.md lists the
firmware constraints.

## Phase 3: layout
1. Owner places and locks the anchors; footprint keep-outs fence the free areas (`pcb-placement` §1).
2. `pcb_rules.py apply --fab jlcpcb --netclasses`; `netclasses.py apply`.
3. Placement (`place.py optimize`, render, refine, owner review), then pin assignment (`pins.py assign`), pin map
   written back to the schematic and frozen by a decision.
   - **Mini-gate after the pin-map freeze** (the schematic changed after the Phase 1 gate): `schgen.py build` and
     `check`, ERC, `library_check.py`, `trace.py`, all clean again; firmware told the new pin map.
4. Routing in phases: power copper, critical routes, the rest, fills; teardrops drawn.

Gate: `pcb_rules.py check` and `netclasses.py check` exit 0; `place.py gate` reported (assembly spacing, edge
keep-outs); test points placed and reachable; the reviewer agent's verdict; owner review.

## Phase 4: fab and bring-up
- `export_jlcpcb.py`; check rotations in the fab's viewer.
- Assembly pre-flight: `place.py gate` assembly checks (part spacing, edge keep-outs, fiducials or the fab's edge
  rails, orientation); `jlc_stock.py` (stock, packages, lifecycle, alternates).
- The fab's own DFM analysis of the Gerbers reviewed; options ordered as designed (impedance control, via-in-pad,
  inner copper weight, acceptance class).
- EMC: a pre-compliance scan planned for the first boards when the product needs certification (radiated and
  conducted emissions, ESD on connectors).
- Order.
- `docs/bringup.md`, in order; every B requirement closed or logged.

## Status (2026-11-22)

| Phase | State | Evidence |
|---|---|---|
| 0 | done, not signed off | requirements traced (`trace.py` PASS, 26 requirements, 27 decisions); parts from the owner's list |
| 1 | done, not signed off | 7 sheets, `schgen.py build` lint 0, `check` PASS (77 nets), ERC 0, `library_check.py` PASS; stock and `jlc_stock.py` not run |
| 2 | not started | S1, S2 open (OI-2) |
| 3 | placement done, not routed | `place.py gate --enforce` PASS, `pins.py check` PASS, `pcb_rules.py check --allow-unrouted` PASS, `netclasses.py check` PASS, `silk.py check` PASS; pin map frozen (D-014) |
| 4 | not started | |

No gate has the owner's sign-off. The Phase 1 checklists are folded into the schematic notes and `docs/decisions.md`.
