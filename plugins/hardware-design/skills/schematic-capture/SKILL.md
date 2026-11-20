---
name: schematic-capture
description: Draw or change a KiCad 10 schematic as code with schgen (Python sheet descriptions to .kicad_sch, deterministic, one titled block per function, intended netlist recorded), with function nets whose MCU pin is chosen later, net-class directive labels, and checks (netlist against intent, equivalence after drawing-only changes, symbol pins against footprint pads and BOM fields).
---

# Schematic capture (KiCad 10+)

Use this skill to create or change a board's schematic. The default is **schematic as code**: each sheet is a Python module that places parts and wires them, and `schgen.py build` writes the `.kicad_sch` files. A hand-drawn schematic (eeschema) is still supported, but it gets the checks (§5) only.

Why code: every connection is recorded as it is made, so the tools can prove the drawn netlist is the intended one. A rebuild is byte-identical, so a diff shows exactly what changed. And a change of pin map or value is a one-line edit.

The tools are in `scripts/`: `schgen.py` (build, check, equivalence), the `schgen/` library (`sch.py`, `library.py`, `netlist.py`, `sexpr.py`) and `library_check.py`. schgen comes from embedded-pro's e-psu-hardware and e-inverted-pendulum-hardware. Ported here, it rebuilds e-inverted-pendulum's 8 sheets, 231 parts and intended netlist **byte-identical** to that project's own generator (2026-11-20).

## 1. Board repo layout

```
scripts/schgen/
  config.py         NAME, TITLE, OUT, MODULES, ... (see `schgen.py --help`)
  design/<sheet>.py one module per sheet: build(project, values)
  values.json       component values from the design calculations (optional)
  parts.py          the board's own part helpers (passives from its BOM, LCSC/MPN fields), optional
  expected.json     the intended netlist, written by build: commit it
hardware/<board>/   the generated .kicad_sch files, the project library (.kicad_sym, .pretty)
```

## 2. Drawing conventions

These are the e-psu / e-inverted-pendulum conventions:

- **One sheet per functional block**, numbered. References on sheet n are n01–n99 (U301, C305): a block numbering scheme. Class letters (U, C, R, J, Q, D, L, Y, ...) follow ASME Y14.44, the current US reference-designation standard (IEEE 200 is withdrawn) [ASME-Y14.44].
- On each sheet, **titled boxes** (`sh.box`) group circuits, and each box has a **design note** (`sh.note`) that gives the numbers' sources: datasheet section, app note, design calc, decision.
- The **root page** describes every sheet (`sh.desc`) and carries the board's notes (`ROOT_NOTES`: power flow, grounding, numbering). Following IPC-2612's schematic-documentation contents [IPC-2612], the notes also carry:
  - a **power and ground table**: each supply net, its voltage, source and class, and every ground net with where it joins the others;
  - **spare and unused parts**: unused gates and op-amp sections with how they are tied off, and not-fitted parts (`DNP`) with why.
- **Every named net has a label**, so net names (and the PCB's nets and net classes) don't depend on the drawing. Nets used on several sheets become global labels by themselves. Power nets listed in `POWER_SYMBOLS` are drawn as power symbols.
- **Every pin has a net or a no-connect.** `build` refuses anything else, and duplicate references too.
- The build fails on **layout lint**: a wire crossing a part, or a pin touching a wire mid-span.

## 3. The API (`schgen/sch.py`)

```python
from sch import Sheet, load_pinmap

def build(project, values):
    sh = Sheet(project, 3, "mcu", "MCU, clocks, debug")            # index, file name, title
    sh.desc = ["STM32WB55 with SMPS", "SWD + VCP on STDC14"]
    sh.box(15.24, 20.32, 200.66, 165.1, "MCU supplies (AN5165)")
    u = sh.part("MCU_ST_STM32WB:STM32WB55RGVx", "U301", "STM32WB55RGV6", (127.0, 101.6),
                fp="Package_DFN_QFN:QFN-68-1EP_8x8mm_P0.4mm", lcsc="C401505", mpn="STM32WB55RGV6",
                Purpose="D-001")                                   # any extra field
    sh.nets(u, {"1": "+3V3", "33": "GND", "7": None})              # pin -> net (None: no-connect)
    sh.rail("+3V3", 33.02, [c1["1"], c2["1"]], tap=(22.86, (0, -1)))   # a bus wire joining pins
    sh.vrail("GND", 106.68, [u["18"], u["20"]])
    sh.link(r1["2"], u["12"], "IMU_INT")                           # pin to pin
    sh.path("SPI1_SCK", [r5["1"], (150.0, 80.0), u["24"]])         # a polyline
    sh.netclass("VBAT", "PWR_4A")                                  # net-class directive (pcb-copper)
    sh.assign_pins(u, load_pinmap("pinmap.txt"))                   # MCU pins from the pin map (§4)
    sh.nc_unused(u, r"^P[A-Z][0-9]+$")                             # remaining I/O pins: no-connect
    sh.note(20.32, 132.08, ["Decoupling per DS13252 s6.1.6: ...", "..."])
```

Symbols come from KiCad's libraries (found automatically, or `SYMBOL_DIR` / `$KICAD10_SYMBOL_DIR`) and the project's own libraries (`PROJECT_LIBRARIES`).

## 4. Function nets and the pin map

Hardware picks the MCU pins after placement (docs/design.md §4):

1. **Draw function nets.** Each peripheral side labels its connection with the function's name (`IMU_SCK`, `ENC_L_A`). On the MCU sheet, `sh.assign_pins(u, load_pinmap(path))` connects the MCU pins that the pin map has. With no map yet, it connects nothing, so the function exists only on the peripheral side. `sh.nc_unused(u, io_regex)` closes the rest. `build` then passes.
2. *Update PCB from Schematic*, place (`pcb-placement`), then `pins.py assign … --out pinmap.txt`.
3. Rebuild: the same `assign_pins` call now wires the pins. Run `schgen.py check`, then *Update PCB from Schematic*. Log the pin-map freeze as a decision.

`NET~2` in a pin map is a second pin on `NET`.

## 5. Checks

| Command | Needs | What it proves |
|---|---|---|
| `schgen.py build config.py` | symbols | every pin decided, no duplicate references, no layout lint; writes `expected.json` |
| `schgen.py check config.py` | kicad-cli | KiCad's netlist has exactly the intended nets, names and pins |
| `schgen.py equivalence config.py <rev\|file.net>` | kicad-cli, git | after a drawing-only change: same parts, fields and pin-to-net partition as before (`--allow-renames` reports net renames instead of failing) |
| `library_check.py board.kicad_pcb` | nothing | every placed symbol's pins have pads on its footprint, and the reverse; every BOM part has a footprint, LCSC and MPN (`--fields`); no part missing from the board |

`library_check.py` reads the symbols embedded in the schematics and the footprints embedded in the board, so it also works on hand-drawn schematics and without KiCad. On e-inverted-pendulum it passes (231 parts). On e-foc it finds plated mounting holes whose symbol has no pin, and 167 parts without LCSC/MPN fields.

Run `build` and `check` in CI next to ERC.

## 6. Library policy (D19)

1. **KiCad's standard libraries first** (symbols and footprints). Their STM32 symbols carry every alternate function, which `pins.py` uses.
2. **A part they lack:** take its symbol and footprint from LCSC/EasyEDA into the project library, e.g. `easyeda2kicad --full --lcsc_id C2040 --output hardware/<board>/<board>` (pip package `easyeda2kicad`). Treat the footprint as unverified: KiCad's library is generated to its conventions (KLC), which follow IPC-7351 [KLC], and EasyEDA's footprints follow no stated standard. Check it against the LCSC part's package drawing and the datasheet's recommended land pattern before using it. `jlc_stock.py` (`hardware-project`) then compares every BOM footprint with JLCPCB's package for the part (chip size, family, pin count, body), the D19 check; pad geometry still needs the eye.
3. **Hand transcription** from the datasheet, with the table cited in the symbol's description, only when neither has the part.
4. After any library change: `library_check.py`. A symbol pin without a pad, or a pad without a pin, is a wrong footprint until proven otherwise.
5. **Hand-made land patterns** follow the datasheet's recommended land first, then IPC-7352 (2023, the newest IPC land-pattern guideline, successor to the IPC-7351 series) for pad sizes, courtyard and **zero orientation** (pin 1 placement) [IPC-7352]. A footprint whose zero orientation differs from the library's makes the assembly file's rotations wrong (`hardware-project` export).

The easyeda2kicad step was not run in the build environment of this skill (no network to EasyEDA).

## 7. Checklist

- [ ] One module per sheet; references n01–n99; titled boxes with sourced design notes; root page describes every sheet.
- [ ] `build` passes with no lint; `expected.json` committed; `check` passes.
- [ ] Power nets carry their `PWR_<I>A` / `GND` class (`sh.netclass`); every net has a class (`pcb-copper`).
- [ ] Function nets drawn; pin map applied after placement; freeze logged.
- [ ] `library_check.py` passes; every BOM part has LCSC and MPN.
- [ ] Drawing-only changes proven with `equivalence`.

## 8. References

- schgen: embedded-pro/e-psu-hardware and embedded-pro/e-inverted-pendulum-hardware `scripts/schgen` (D-020, D-033 there).
- KiCad 10 schematic format: net-class directive labels (`netclass_flag`) as KiCad 10.0 writes them (read from e-foc, 2026-11-20).
- docs/design.md D10, D16, D19.
- [ASME-Y14.44] ASME Y14.44-2008 (reaffirmed 2024), *Reference Designations for Electrical and Electronics Parts and Equipment* (contents: class letters, App. A block numbering). https://webstore.ansi.org/standards/asme/asmey14442008r2024 ; IEEE 200-1975 status withdrawn: https://standards.ieee.org/standard/200-1975.html
- [IPC-2612] IPC-2612 (2010), *Sectional Requirements for Electronic Diagramming Documentation* (contents: net naming, spares, power and ground table, bypass capacitors). Preview: https://webstore.ansi.org/preview-pages/IPC/preview_IPC+2612-2010.pdf
- [IPC-7352] IPC-7352 (May 2023), *Generic Guideline for Land Pattern Design* (contents: courtyard, naming, zero orientation). https://www.electronics.org/TOC/IPC-7352-TOC.pdf
- [KLC] KiCad Library Conventions, F5.3 courtyard (IPC-7351 based). https://klc.kicad.org/footprint/f5/f5.3/
