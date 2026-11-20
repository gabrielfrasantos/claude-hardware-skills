---
name: pcb-placement
description: Place the unlocked footprints of a KiCad 10 board around the owner's locked anchors with a simulated-annealing optimizer (ratsnest length, decoupling distance, no overlaps, keep-outs respected), refine it, render it, and gate the result on validity and ratsnest length and crossings against a baseline; propose anchor moves for the owner without applying them.
---

# PCB placement (KiCad 10+)

Use this skill after *Update PCB from Schematic*, when the owner has placed and locked the anchors and the rest of the parts wait in a staging area, and whenever a placement needs judging before routing. Bad placement is what makes routing need too many vias; fix it here, not in the router.

The script is `scripts/place.py` (needs `pip install shapely numpy matplotlib`). It reads and writes the `.kicad_pcb` directly, shares the board parser of `pcb-design-rules`, and never moves a locked footprint.

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

## 5. Pin assignment

Choosing MCU pins from the side that faces each cluster (docs/design.md §4) builds on this placement. It is the next part of this skill.

## 6. Checklist

- [ ] Anchors and intent locked; free areas fenced with footprint keep-outs.
- [ ] `render` read before and after; seeds compared; the domain skills' placement rules checked by eye.
- [ ] `gate` valid; ratios against the last accepted placement reported.
- [ ] Owner reviewed the renders; the accepted placement's JSON kept as the next baseline.

## 7. References

- docs/design.md D7, D15, D25 (working agreement, optimizer then refinement, report-only gate).
- `power-pcb-layout` §1 (anchors), `pcb-design-rules` §5 (0.05 mm grid), `mcu-circuit-design` §2 (decoupling).
- Measurements in §4: `place.py` on the evals fixture of embedded-pro/e-inverted-pendulum-hardware at 51a4bcf, 2026-11-20.
