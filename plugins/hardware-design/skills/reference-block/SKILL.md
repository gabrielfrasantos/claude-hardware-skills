---
name: reference-block
description: Copy a vendor's proven layout block (RF corner, NFC coil, motor-driver or converter power stage) from its design files onto a KiCad 10 board - import Altium or other formats with kicad-cli, cut the block out, map the vendor's parts and nets to ours, paste its parts, tracks, vias, pours and rule areas, and check it stays intact. Says when copying beats designing.
---

# Reference block: copy a vendor's layout (KiCad 10+)

Use this skill when a board needs a block that a vendor has already laid out and proven on an evaluation board, and the owner wants that layout rather than our own. Typical cases: the RF path of a wireless MCU, an NFC coil and its tag, a gate driver with its FETs and shunts.

The script is `scripts/refblock.py`. It shares the board parser of `pcb-design-rules` (`../pcb-design-rules/scripts`), so install the whole plugin, not this folder alone. KiCad 10 or later only (D4). The vendor's files never enter a repository (D18): they stay in the board repo's gitignored `reference/` folder, and only the extracted block and its land patterns are committed.

Companion skills: `rf-layout`, `power-pcb-layout` and `interface-layout` (the rules the copied block still has to meet), `schematic-capture` (the parts, values and land patterns), `pcb-placement` (our parts around the block), `pcb-design-rules` and `pcb-copper` (DRC and net classes after the paste), `hardware-project` (the decision record).

## 1. When copying beats designing

Copy where the layout itself is the design and the vendor measured it:

| Block | Why copy |
|---|---|
| RF path: balun or IPD, match, antenna, the MCU's RF and SMPS parts, crystals | the match values only hold for that copper, that stack-up and that antenna; the vendor tuned and often certified it. ST: copy the reference design exactly, with the same stack-up [AN5165 §6.9] (`rf-layout`) |
| NFC or wireless-charging coil with its tuning | inductance and resonance come from the copper geometry |
| Fast power loops: gate driver, FETs, shunts and HF bypass | loop inductance, Kelvin taps and thermal copper are layout (`power-pcb-layout` §3) |
| A converter whose datasheet layout is the only one the vendor supports | the vendor's validation covers that layout only |

Don't copy where our constraints dominate or the vendor's layout is incidental: connectors and their routing, digital fan-out, LEDs, headers, test points. Leave out the vendor's host-side parts (eval-board headers, jumpers, LEDs, logos): map only the parts we keep.

**A copy is not the vendor's tested board.** It keeps the vendor's work only as far as the stack-up, the reference planes and the neighbourhood match theirs (§5). Record what differs.

## 2. Licence and files

- **Read the vendor's licence before anything is committed**, and record what it allows in the decision. Two common cases (not legal advice):
  - **ST, Open Platform License** [OPLA]: allows use, modification, copying and distribution of the reference material, but only for application boards based on ST products, not for sale as such, and without ST's name or logo to promote the result.
  - **TI, Important Notice** [TI-NOTICE]: allows use only to develop an application with the TI products the resource describes. Other reproduction and display is prohibited, and no further licence is granted.
- **Default: anything derived from TI files stays in the gitignored `reference/`**: the block JSON and the exported land patterns. Commit it only after the owner has recorded a licence decision (ideally with legal advice), and never in a public repository without one. The copper on the board itself is the application TI's terms allow, but whether a public board repository counts as "display" is the owner's call.
- For other vendors, find the licence that ships with the design files. With no licence, treat the files as all rights reserved: use them, don't commit what is derived from them.
- `extract --files` records the sha256 of each original file in the block, so a later re-extract shows whether the vendor's files changed.
- Every derived file carries the attribution line from the map's `source` (block JSON, exported land patterns' `descr`). Put the same line in the decision (`docs/decisions.md`, `hardware-project`) that records the copy, what was left out and every deviation.

## 3. Workflow

1. **Get the files** from the vendor (layout, schematic, BOM, stack-up) into `reference/<name>/`. Check that `reference/` is gitignored.
2. **Import** the layout:
   ```
   refblock.py import reference/<name>/<file>.PcbDoc -o reference/<name>/<name>.kicad_pcb
   ```
   This runs `kicad-cli pcb import`, which converts PADS, Altium, Eagle, CADSTAR, Fabmaster, P-CAD and SOLIDWORKS PCB boards and maps their layers automatically [KICAD-CLI]. Its import report is written next to the output. A vendor `.kicad_pcb` needs no import.
3. **Find the block.** Render the imported board (`kicad-cli pcb export svg`) or open it in KiCad, and note a box around the block in its coordinates. List what is inside:
   ```
   refblock.py list reference/<name>/<name>.kicad_pcb --box X1 Y1 X2 Y2
   ```
4. **Write the map**, `pcb/reference/<name>.map.json` in the board repo (§4).
5. **Capture the parts** in our schematic with the vendor's values, and with land patterns that match the vendor's pads: export them with `extract --footprints` (step 6), or check the library footprint's pads against the vendor's. Update the PCB from the schematic so every mapped part is on the board, on the vendor's side (flip back-side parts in KiCad).
6. **Extract** the block:
   ```
   refblock.py extract reference/<name>/<name>.kicad_pcb pcb/reference/<name>.map.json \
       -o pcb/reference/<name>.block.json --board <board>.kicad_pcb --files reference/<name>/<original files> \
       [--footprints <lib>.pretty --prefix <VENDOR>_]
   ```
   - `--board` maps every vendor net on a copied pad to our net on the same pad.
   - A vendor net that would land on two of our nets is an error: our schematic wires the part differently from the vendor (a mirrored FET pair, a swapped crystal pin). Fix the schematic, or decide the copy differs, before going on.
7. **Place** it where the owner wants it, turned in steps of 90°:
   ```
   refblock.py place pcb/reference/<name>.block.json <board>.kicad_pcb --at X Y --rot 90 --fab jlcpcb
   ```
8. **Check the board:** `pcb_rules.py check` (DRC with zone refill) and `netclasses.py check`. Then deal with what the copy brings (§5), place our extra parts around it (`place.py optimize --only ...`), and log the decision.

Re-run `refblock.py check` whenever the board changes near the block. It is the gate that the copy is still the vendor's.

## 4. The map

```json
{
  "name": "BOOST-DRV8711 drive",
  "source": "Derived from Texas Instruments BOOST-DRV8711 design files (SLVC575B)",
  "box": [125.5, 86.0, 163.6, 123.0],
  "parts": {"U1": "U501", "Q1": "Q501", "R1": "R509", "C2": "C508"},
  "nets": {"VM": "VBAT"},
  "drop_nets": ["LED1_K"],
  "layers": {"In1.Cu": "In2.Cu"},
  "not_copied": "LaunchPad headers J1 / J2, LEDs, logo"
}
```

| Key | Meaning |
|---|---|
| `name` | the block's name: the KiCad group, the zone names, the uuids |
| `source` | the attribution line every derived file carries (§2) |
| `box` | the block in the vendor's frame (mm, y down, as imported). Default: the mapped parts' pads plus `--margin` (1 mm) |
| `parts` | vendor reference → ours. Only these parts are copied |
| `nets` | vendor net → ours, for copper on no copied pad (a pour, stitching) or to name a net `--board` cannot derive. Our hierarchical names may be given by their last part (`VBAT` for `/power/VBAT`) |
| `drop_nets` | vendor nets whose copper is not copied |
| `layers` | vendor copper layer → ours, where they differ |

Copper on a net that is neither mapped nor on a copied pad is dropped with a note.

## 5. What extract and place do, and what they leave to you

`extract` keeps the vendor's own KiCad text for each item. It copies:
- the tracks, arcs and vias wholly inside the box;
- the pours and rule areas, cut to the box;
- the copper graphics (an antenna drawn as polygons).

It prunes:
- a track that ends on nothing copied (no copied pad, track, via or pour of its net);
- a via that connects to nothing of its net. Stitching vias in a copied pour stay.

Exported land patterns are re-centred on their pads at orientation 0, without 3D models and nets.

`place` moves and turns each mapped part so that its pads land on the vendor's pads by pad number (least squares; pads sharing a number count as their centroid). It then adds the copper with our nets and layers and groups everything under the block's name. It writes nothing when:
- a part is missing, or on the other side;
- a part is locked and would have to move (the owner's anchors never move: place the block on the anchor instead);
- a land differs from the vendor's by more than `--tol` (0.02 mm);
- a pad's net differs from the map;
- copper of this block is already on the board outside its group.

Re-running is a no-op while the group exists. `--replace` removes the group's copper and pastes again where the parts are now, so the owner can move the group in KiCad first.

**Left to you after the paste:**

- **Stack-up.** Compare the vendor's dielectric under each copied controlled-impedance line with ours, and recompute it (`rf-layout` §2). A two-layer vendor block on our four layers gets L2 under it. That shortens the reference distance, so the vendor's RF line widths no longer give 50 Ω. Either cut L2 under the line (an exception to "L2 solid", recorded) or re-width it.
- **Fab rules.** `--fab` compares the block's narrowest track, smallest via, drill and annular ring with the fab's minimum. DRC finds the rest: the vendor's clearances, via hole-to-copper. Fix each in the copy (nudge a via, widen a gap) and list the changes in the decision.
- **Geometry gate.** Vendor routing often has bends that aren't exactly 45°, which `pcb_rules.py check` flags. Either make the bends exact, or record DRC exclusions on those exact items so anything drawn later is still checked.
- **Assembly spacing.** The vendor may have parts closer than our assembler allows. JLCPCB's minimum depends on the pair of packages, from 0.15 mm between small chips to 2 mm between BGAs [JLC-SPACING]; the placement gate checks it (`pcb-placement`). Nudge the parts, keep the copied tracks on the moved pads, and record it.
- **Pours.** The vendor's pour priorities and connection styles come along. Check they fit our pours (`pcb-copper`). Holes in a vendor pour outline are reported, not kept.
- **Our extras.** Protection, bulk capacitors and test points the vendor's board didn't have go around the block afterwards. `place` lists our parts that sit inside the block's box.
- **Teardrops:** `pcb_rules.py apply` adds them to the copied pads and vias.
- **Hand-over.** Locking and ungrouping are the owner's. Once ungrouped, `--replace` can't find the copy (delete it in KiCad first), but `check` still works: it fits the block to where its parts are.

## 6. Limits

- **Gerber-only sources** (no layout files) are not supported. Gerbers carry no nets and no parts, and KiCad 10.0's CLI does not import them into a board. The route is the e-inverted-pendulum's `scripts/nfc_reference.py`:
  - read the Gerbers, drill and pick-and-place;
  - take nets from copper connectivity, named from the vendor's schematic;
  - fail if an island would need two names.
- **Back-side parts:** `place` handles them, already on the back. `--footprints` exports front-side lands only: export back-side ones in KiCad's footprint editor.
- **No mirroring** of a block to the other side, and turns are in steps of 90° only.
- **Written as text, not through KiCad.** Open the board in KiCad 10 after the first paste and run DRC. The round trip has been checked against the e-inverted-pendulum's TI stage:
  - every footprint and copied track came back byte-identical;
  - KiCad itself has not loaded a pasted board in this repository's tests.

## 7. Checklist

- [ ] The licence allows what is committed (recorded in the decision). Vendor files, and anything TI-derived without a licence decision, are only in the gitignored `reference/`; the sha256s are recorded.
- [ ] The map names only the parts we keep. `extract --board` ran without net conflicts, or each conflict is a recorded decision.
- [ ] The lands match the vendor's (exported, or checked within `--tol`).
- [ ] Placed with the owner's position and turn. `refblock.py check` passes.
- [ ] Stack-up difference assessed, and impedance recomputed for copied controlled-impedance lines.
- [ ] DRC clean or with recorded exclusions. `--fab` warnings resolved.
- [ ] Our extra parts placed around the block, and nothing of ours left inside it by accident.
- [ ] Decision logged: source, licence, what was copied, what was left out, every deviation.

## 8. References

- [KICAD-CLI] KiCad 10.0 Command-Line Interface manual, *PCB import*: `kicad-cli pcb import [--format auto|pads|altium|eagle|cadstar|fabmaster|pcad|solidworks] [--report-format none|json|text] [-o OUTPUT] INPUT_FILE`, layers mapped automatically. https://docs.kicad.org/10.0/en/cli/cli.html
- KiCad board file format (S-expressions): https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/. As KiCad 10 writes it: nets by name on every item; groups as `(group "name" (uuid ...) (members ...))`; pad and text angles absolute, in [0, 360), a pad omitting 0.
- [AN5165] ST, AN5165 *How to develop RF hardware using STM32WB MCUs*, §6.9 checklist: the stack-up must match the reference design; copy it exactly. https://www.st.com/resource/en/application_note/an5165-how-to-develop-rf-hardware-using-stm32wb-mcus-stmicroelectronics.pdf
- [OPLA] ST, Open Platform License Agreement, LICENSE and RESTRICTIONS clauses. https://www.st.com/opla
- [TI-NOTICE] TI, *Important Notice and Disclaimer* (published with TI documents and design files). https://software-dl.ti.com/C2000/docs/software_guide/notice.html
- [JLC-SPACING] JLCPCB, *Minimum spacing for SMD components* (package-pair table). https://jlcpcb.com/help/article/minimum-spacing-for-smd-components
- Worked examples, embedded-pro/e-inverted-pendulum-hardware `docs/decisions.md`:
  - D-037: ST MB1355 RF corner;
  - D-039: ST MB1163 NFC coil, from Gerbers;
  - D-040: TI BOOST-DRV8711 stage;
  - D-046: hand-over;
  - D-052 / D-053: assembly nudges, pours and bends.
