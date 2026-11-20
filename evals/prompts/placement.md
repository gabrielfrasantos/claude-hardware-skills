This folder holds a KiCad 10 project: `{name}.kicad_pro` and its board `{name}.kicad_pcb`.

The locked footprints are the owner's anchors. Do not move, rotate or flip them, and do not change the board outline,
the rule areas or the project settings.

Every unlocked footprint sits in a staging area to the right of the board outline. Place every one of them inside the
board outline, on its current side, so the board is easy to route:

- short connections and few ratsnest crossings;
- decoupling capacitors at the pins they decouple;
- each functional block together, near the anchors it connects to;
- no courtyard overlaps, and the fab's assembly spacing (JLCPCB).

Placement only: do not add tracks, vias or zones, and do not lock anything. Edit `{name}.kicad_pcb` in place and
leave a valid KiCad 10 file. `kicad-cli` may not be installed. When done, reply with one paragraph on how you placed
the parts.
