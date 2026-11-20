# Plan: {{NAME}}

{{TITLE}}. Firmware: {{FIRMWARE}}. Each phase ends at a gate the **owner** signs off; the next phase does not start
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
Rules: `mcu-circuit-design`, `analog-circuit-design`, `power-pcb-layout` (schematic side), `interface-layout`,
`rf-layout`. The datasheets win.

Gate:
- `schgen.py build` with no problems or lint; `schgen.py check` passes; ERC clean;
- `library_check.py` passes (every BOM part with LCSC and MPN);
- every power net has its `PWR_<I>A` / `GND` class (`pcb-copper`);
- the skills' checklists completed in `docs/checklists/phase1.md`;
- `jlc_stock.py` green for the build quantity; owner review.

## Phase 2: simulation (`circuit-simulation`)
| ID | Circuit / question | Pass criterion |
|---|---|---|
| S1 | ASSUMPTION: power entry (hot plug, inrush, reverse polarity) | ASSUMPTION |

Gate: every check passes as drawn, or the proposed changes are moved into the schematic; REPORT.md lists the
firmware constraints.

## Phase 3: layout
1. Owner places and locks the anchors; footprint keep-outs fence the free areas (`pcb-placement` §1).
2. `pcb_rules.py apply --fab {{FAB}} --netclasses`; `netclasses.py apply`.
3. Placement (`place.py optimize`, render, refine, owner review), then pin assignment (`pins.py assign`), pin map
   written back to the schematic and frozen by a decision.
4. Routing in phases: power copper, critical routes, the rest, fills; teardrops drawn.

Gate: `pcb_rules.py check` and `netclasses.py check` exit 0; `place.py gate` reported; the reviewer agent's
verdict; owner review.

## Phase 4: fab and bring-up
- `export_jlcpcb.py`; check rotations in the fab's viewer; order.
- `docs/bringup.md`, in order; every B requirement closed or logged.
