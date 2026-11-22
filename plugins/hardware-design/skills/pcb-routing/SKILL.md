---
name: pcb-routing
description: Autoroute the non-critical nets of a KiCad 10 board with Freerouting, headless and without pcbnew - write the board as a Specctra DSN from the .kicad_pcb text (outline, pours as planes, rule areas as keepouts, pads, nets, one class per KiCad net class with its width, clearance and via), run Freerouting with no GUI, and add the session's tracks and vias back to the board - after the critical nets are routed by hand and locked, then gate the result with pcb-design-rules.
---

# PCB routing with Freerouting (KiCad 10+)

Use this skill after placement (`pcb-placement`) and after the critical nets are routed, to route the rest. The router knows clearances, widths and vias. It doesn't know the design intent:
- hot loops;
- Kelvin sense pairs;
- impedance;
- return paths;
- the house style.

So it never gets those nets (D17: the owner routes the critical ones; the router does the rest).

The script is `scripts/route.py`. It shares the board parser of `pcb-design-rules` (`../pcb-design-rules/scripts`), so install the whole plugin. It needs `shapely`, Java and the Freerouting jar:
- **Freerouting:** 2.5.0, GPL-3.0. It runs as a separate program and isn't part of this plugin.
- **Java:** 2.5.0 needs Java 25.
- **Getting the jar:** `route.py fetch` downloads it from Maven Central and checks its SHA-1.

## 1. Why a DSN writer of our own

`kicad-cli` 10 has no Specctra export: KiCad's *File → Export → Specctra DSN* exists only in the GUI and the deprecated pcbnew module (D22). `route.py dsn` writes the same structure from the board text:
- **layers** and the **outline** (`Edge.Cuts`);
- **pours with a net** as **planes**: the router connects their pads with vias instead of tracks;
- **rule areas** as keepouts. A rule area forbidding tracks becomes a keepout; one forbidding only vias becomes a `via_keepout`;
- each footprint's **pads** as padstacks in the footprint's frame, turned by the pad's own angle. Round, oval, rect, roundrect and custom pads are supported; NPTH holes become keepouts;
- **nets**, and **one class per KiCad net class**, with its track width, clearance and via from the `.kicad_pro`;
- **existing tracks and vias** as fixed (`protect`) wiring, so the router routes around them and never moves them;
- **`snap_angle fortyfive_degree`**: traces stay on 0°, 45° and 90° directions.

Front-side footprints only for now: a footprint on the back stops `dsn` with an error.

## 2. Workflow

1. **Route the critical nets yourself** and lock them, following the domain skills:
   - power loops and high-current copper (`power-pcb-layout`);
   - Kelvin sense lines (`pcb-copper` `SENSE`);
   - RF and impedance-controlled nets (`rf-layout`, `DIFF_*`, `RF_50`);
   - crystals and clocks; USB and other interfaces (`interface-layout`, `high-speed-digital-layout`).
   Nets that must be pours (`pcb-copper`) are zones before routing.
2. **Route the rest:**
   ```bash
   python3 scripts/route.py fetch                                    # once: Freerouting into ~/.cache/hardware-design/
   python3 scripts/route.py run hardware/board/board.kicad_pcb --java /path/to/java25 \
           --skip-nets '^(VM|GND|/3 Motor driver/(ISEN|AOUT|BOUT|A[12]|B[12])|RF)' --passes 20 --keep route-work
   ```
   - `--nets REGEX` routes only matching nets. `--skip-nets REGEX` leaves matching nets out; their pads stay obstacles.
   - `--passes` caps Freerouting's routing passes. Its optimiser runs only when every connection is routed.
   - `--keep DIR` keeps the DSN, the session and Freerouting's log.
   - `dsn` and `import` run the two halves separately, for example to route in Freerouting's GUI in between.
3. **After routing:**
   ```bash
   python3 ../pcb-design-rules/scripts/pcb_rules.py apply hardware/board/board.kicad_pro --fab jlcpcb    # teardrops on the new vias
   python3 ../pcb-design-rules/scripts/pcb_rules.py check hardware/board/board.kicad_pcb --report pcb-quality.md
   python3 ../pcb-copper/scripts/netclasses.py check hardware/board/board.kicad_pcb
   ```
   `check` refills the zones on a copy and runs KiCad's DRC. Expect house-style findings (`right_angle_corners`, `jogs`, `track_junctions`): the router follows clearance and width, not the style. Fix them in KiCad, or rip up a net and route it by hand.
4. **Look at it.** Render the copper (`kicad-cli pcb export svg`) and check what no gate sees:
   - vias in pads;
   - long detours;
   - signals crossing split planes;
   - a supply routed as a thin track where a pour was meant.

## 3. Checks

| Check | What it shows |
|---|---|
| KiCad DRC after `import` (`pcb_rules.py check`) | shorts and clearance. The DSN carries every net class's clearance, so the router's tracks meet them |
| `orphan_copper_nets`, `via_net_changes` (`pcb_rules.py`) | copper on the wrong net after routing |
| Freerouting's log (`--keep`) | connections left unrouted. Route them by hand, or add passes |

## 4. Pitfalls

- **The router routes what it's given.** A power net left in the DSN becomes a minimum-width track if its class has no width set. Put the classes in place first (`pcb-copper` `apply`), and skip what must be copper pours.
- **Planes need fills.** A pour becomes a plane in the DSN from its outline. After import, refill the zones (`pcb_rules.py check` does it on a copy; *Edit → Fill All Zones* in KiCad), or the planes' connections show as unconnected.
- **Freerouting 2.5.0 needs Java 25.** Older Java fails with `UnsupportedClassVersionError`.
- **Back-side footprints** aren't exported yet.

## 5. References

- Freerouting 2.5.0 (GPL-3.0): command line `-de board.dsn -do board.ses -mp N`, `--gui.enabled=false`. `snap_angle` is read by its Specctra parser (`app/freerouting/io/specctra/parser/Structure`). Maven Central `app.freerouting:freerouting`.
- Specctra DSN as KiCad 10.0.8 writes it (`pcbnew.ExportSpecctraDSN`): structure, placement, library, network and wiring. It was used as the reference for `route.py dsn`.
- D17 and D22 in `docs/design.md`.
