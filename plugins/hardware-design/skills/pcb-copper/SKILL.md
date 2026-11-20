---
name: pcb-copper
description: Give every net of a KiCad 10 board a class from one standard set, declared on the schematic's net-class directive labels (PWR_4A, GND, SIGNAL, CLK, DIFF_90, RF_50, ..._48V), size each class from its name (IPC-2221 width per layer's copper for the current, IPC-2221 clearance for the voltage, pours above 3 A), and gate the board on nets left in Default, tracks narrower than their class and high-current nets without a pour.
---

# PCB copper: net classes (KiCad 10+)

Use this skill when you set up a board's net classes, before routing, and when you check that the copper matches them. It sits between the schematic and `pcb-design-rules`: the fab profile sets what can be built, this skill sets what each net needs.

The script is `scripts/netclasses.py`. It shares the board parser and class resolver of `pcb-design-rules` (`../pcb-design-rules/scripts`), so install the whole plugin, not this folder alone. KiCad 10 or later only.

## 1. The class set

A net's class name says what sizes it. Put the name on a **net-class directive label** in the schematic. KiCad resolves each label to its net and writes the assignment into the project (`netclass_assignments` in the `.kicad_pro`), so no netlisting is needed here.

| Class | For | Track width | Clearance |
|---|---|---|---|
| `PWR_<I>A` | power nets carrying I amps (`PWR_4A`, `PWR_0p5A`, `PWR_2.5A`) | IPC-2221 for I at ΔT 10 °C on each layer's copper (§2); at or above the width of 3 A on 1 oz outer copper, the net must be a pour | fab design value |
| `GND`, `GND_<I>A` | ground; with a current, sized like `PWR` | signal value, or as `PWR` | fab design value |
| `SIGNAL`, `ANALOG`, `SENSE`, `CLK` | everything else, by role | fab design value | fab design value |
| `DIFF_90`, `DIFF_100`, `RF_50` | impedance-controlled | from the fab's impedance calculator for your stack-up (JLCPCB: jlcpcb.com/impedance); set it in *Board Setup → Net Classes* | fab design value |
| any of the above `+ _<V>V` | nets at V volts DC or peak (`PWR_2A_48V`, `SIGNAL_100V`) | as above | IPC-2221 Table 6-1, external uncoated (B2), at least the fab design value |

- **Every net gets a class.** Default is an error, not a fallback: a net in Default was never looked at. Label buses and signal groups, or add a deliberate pattern in *Board Setup → Net Classes* (e.g. `/MCU/*` → `SIGNAL`).
- Fab design values come from the `pcb-design-rules` profile the board was set up with (`pcb_rules.py apply` records it; default JLCPCB): track 0.15 mm, clearance 0.15 mm, via 0.3/0.6 mm.
- Above 500 V the class is refused: clearance and creepage then come from the safety standard (IEC 62368-1 / IEC 60664-1), see `power-pcb-layout` §3.8.
- `SENSE` is for Kelvin sense lines; route them as a pair from the inner edges of the shunt pads (`power-pcb-layout` §3.6).
- Other class names are reported and left alone. Rename them, or accept them with `--allow NAME`.

## 2. Sizing

- **Width:** IPC-2221's external fit, $I = 0.048 \cdot \Delta T^{0.44} \cdot A^{0.725}$, A in mil² (`power-pcb-layout` §3.5), on **each layer's own copper thickness** from the board's stack-up (thinnest outer, thinnest inner; 35 µm / 17.5 µm when the board has none). The same fit serves inner layers: IPC-2152's tests found internal and external conductors reach close to the same temperature rise, and IPC-2221's internal chart (k = 0.024, half the current) was never based on tests of internal conductors [PCDF-2152]. Inner widths still come out wider, because inner copper is usually thinner (JLCPCB: 15.2 µm finished).
- **ΔT = 10 °C** by default (D21); `--dt` changes it for the whole board.
- **Pours:** a class whose outer width reaches that of 3 A on 1 oz (1.37 mm at 10 °C) must be a pour on the board (D21; `power-pcb-layout` §3.5: pours, not tracks).
- **Vias:** about 1 A per 0.3 mm via, at least I/1 A vias at each layer change (`power-pcb-layout` §3.5). `size` prints the count.
- IPC-2152 itself is published as charts; this skill uses the IPC-2221 fit because it can be computed and cited. It errs wide on outer layers.

| Current | Outer, 35 µm | Inner, 15.2 µm | Pour |
|---|---|---|---|
| 0.5 A | 0.15 (fab design value; 0.12 computed) | 0.27 | |
| 1 A | 0.30 | 0.69 | |
| 2 A | 0.78 | 1.80 | |
| 3 A | 1.37 | 3.15 | yes |
| 5 A | 2.77 | 6.37 | yes |

*(derived, ΔT 10 °C)*

## 3. Workflow

1. **Schematic:** put a net-class directive label on every power and ground net with its `PWR_<I>A` / `GND` class, on impedance nets, and on the signal groups. The current is the continuous worst case you designed for (fuse, current limit or the load's maximum), not the typical.
2. **KiCad:** *Tools → Update PCB from Schematic*. KiCad writes the assignments into the project.
3. **You:**
   ```bash
   python3 scripts/netclasses.py apply hardware/board/board.kicad_pro
   ```
   It adds or updates each standard class in use (width, clearance, vias) and prints the table, flagging pours and impedance classes. Re-run it after adding a label or changing the stack-up. Then set the impedance classes' width and gap from the fab's calculator.
4. **Route** (`pcb-design-rules` §1, `power-pcb-layout`). Route each net at its class width; on inner layers use the inner width from the table. Power nets marked "POUR required" become zones.
5. **Check** before review, next to `pcb_rules.py check`:
   ```bash
   python3 scripts/netclasses.py check hardware/board/board.kicad_pcb --report netclasses.md
   ```

`pcb_rules.py check`'s `zone_necks` gate measures pours against these class widths, so the two agree once `apply` has run.

## 4. Gates (`check`)

| Gate | Kind | Meaning |
|---|---|---|
| `nets_in_default` | hard | nets with two or more pads left in the Default class |
| `unknown_classes` | hard | classes in use that are not in the set (accept with `--allow`) |
| `class_values_stale` | hard | a standard class whose width, clearance or vias differ from what `apply` writes, or that is not defined |
| `tracks_below_class_width` | hard | a track narrower than its class on its layer (inner width on inner layers). A track that necks into a pad narrower than the class is allowed if it is at least as wide as the pad; the report counts them |
| `required_pours_missing` | hard | a net whose class must be a pour has no copper zone |
| `impedance_unset` | soft | a `DIFF_*` / `RF_50` class still at the Default width |

Exit status 1 when a hard gate fails. `--gate NAME=LIMIT` overrides a limit; write the reason in the PR.

## 5. Pitfalls

- A net matching several patterns gets a composite class in KiCad; the script takes the assignment, else the first matching pattern. Keep one class per net.
- The class width is what KiCad's router starts with on **every** layer. On inner layers widen power tracks to the inner width yourself, or pour them; `check` catches the narrow ones.
- KiCad's DRC does not enforce a net class's track width as a minimum. That is why `check` exists.
- Changing the stack-up's copper weight changes every power width. Re-run `apply` and `check`.

## 6. Checklist

- [ ] Every power and ground net labelled with its class and current; impedance and signal groups labelled.
- [ ] `apply` run after *Update PCB from Schematic*; impedance classes set from the fab's calculator.
- [ ] Power nets marked "POUR required" are zones; via count per layer change ≥ I/1 A.
- [ ] `check` exits 0.

## 7. References

- [PCDF-2152] M. Jouppi, *The New IPC-2152*, Printed Circuit Design & Fab (2009): internal and external conductors reach close to the same temperature rise; IPC-2221's internal chart was not based on tests. pcdandf.com/pcdesign/index.php/2009-archive-articles/5305-the-new-ipc-2152.
- IPC-2221B, *Generic Standard on Printed Board Design*: current fit and Table 6-1 (via `power-pcb-layout` §3.5 and §3.8).
- IPC-2152, *Standard for Determining Current-Carrying Capacity in Printed Board Design* (2009).
- KiCad 10: net-class directive labels resolve to `netclass_assignments` in the `.kicad_pro` (read from the e-foc project, 2026-11-20).
- D9 and D21 in `docs/design.md`.
