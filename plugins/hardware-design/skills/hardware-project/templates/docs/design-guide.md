# {{NAME}}: design guide (the reviewer's rubric)

The engineering rationale behind every check the `{{NAME}}-board-reviewer` agent makes. Generic rules live in the
`hardware-design` skills; cite their sections instead of copying them. Keep here only what is specific to this
board: its risks, its operating points, its accepted deviations. Every number with its source.

## 1. Power entry and protection
## 2. Rails and the MCU
## 3. ASSUMPTION: one section per functional block of this board
## 4. Layout priorities
## 5. Manufacturing ({{FAB}})

## Go / no-go checklist

The reviewer marks every line ✅ / ❌ / ⚠️ / CANNOT-VERIFY / NOT-YET.

- [ ] Every HW-* requirement has evidence (review, simulation or a planned bring-up step).
- [ ] No part above its absolute maximum at any operating point in the requirements.
- [ ] Footprints match the real packages of the LCSC parts.
- [ ] Manufacturer layout guidance followed for every key part.
- [ ] ERC and DRC clean, or every violation explained.
- [ ] `pcb_rules.py check` and `netclasses.py check` pass.
- [ ] The board reaches a safe state through reset and brown-out.
- [ ] Every BOM line in stock for the build quantity.
