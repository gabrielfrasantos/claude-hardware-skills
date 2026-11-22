#!/usr/bin/env python3
"""Write the stepper-ble project library: the parts KiCad 10's standard libraries lack (schematic-capture §6).

    python3 scripts/make_library.py

Writes, deterministically (a rerun is byte-identical):
    hardware/stepper-ble/stepper-ble.kicad_sym           symbols DRV8711 and MLPF-WB55-01E3
    hardware/stepper-ble/stepper-ble.pretty/*.kicad_mod   footprints: MLPF-WB55-01E3 (bumpless CSP, 6 lands), and
                                                          two KiCad library footprints adapted (below)
    hardware/stepper-ble/sym-lib-table, fp-lib-table      the project library tables

Sources (D-016 in docs/decisions.md):
    DRV8711   TI SLVSC40H §5 Pin Configuration and Functions (DCP, 38-pin HTSSOP + PowerPAD = pin 39).
              Footprint from KiCad's library: Package_SO:HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm_ThermalVias,
              compared with TI's DCP0038A example board layout (38 x 1.5 x 0.3 mm lands, 0.5 mm pitch, 2.9 x 4.7 mm pad).
    MLPF      ST DS12804 Rev 2 Table 6 (pad names) and Figure 13 (land pattern: 200 um square lands, 500 um x pitch,
              587 um y pitch, 300 um solder-mask opening). The EasyEDA footprint for C2651048 was read as a cross-check
              and not used: 0.3 mm lands and pads numbered 1-6.
    CSD18543Q3A  KiCad's Package_SON:VSON-8_3.3x3.3mm_P0.65mm_NexFET with pads 1-4 set to TI's land, 0.6 x 0.3 mm
              (SLPS633 §7.2 Q3A Recommended PCB Pattern); KiCad's 0.63 x 0.5 mm pads leave 0.14 mm between gate and
              source, under the board's 0.15 mm design clearance. Pad positions and the drain pad are KiCad's.
    SWRA117D  KiCad's RF_Antenna:Texas_SWRA117D_2.4GHz_Left with the shorting via drilled 0.2 mm instead of 0.3 mm:
              its 0.5 mm pad then has the 0.15 mm annular ring JLCPCB needs on plated holes (pcb-design-rules §3);
              the antenna copper is unchanged.
Pin numbers of both symbols were cross-checked against easyeda2kicad's output for C60013 and C2651048 (2026-11-22).
"""
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware" / "stepper-ble"
LIB = "stepper-ble"
KICAD_FP = pathlib.Path(os.environ.get("KICAD10_FOOTPRINT_DIR", "/usr/share/kicad/footprints"))

DRV8711 = dict(
    name="DRV8711", ref="U", footprint="Package_SO:HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm_ThermalVias",
    datasheet="https://www.ti.com/lit/ds/symlink/drv8711.pdf",
    description="Stepper motor pre-driver, 8-52 V, external N-FET H-bridges, SPI, stall detect, HTSSOP-38 PowerPAD "
                "(pins: TI SLVSC40H section 5)",
    body=(-15.24, -25.4, 15.24, 25.4),
    pins=[
        ("4", "VM", "power_in", -12.7, 27.94, 270), ("3", "VCP", "passive", -7.62, 27.94, 270),
        ("1", "CP1", "passive", -2.54, 27.94, 270), ("2", "CP2", "passive", 2.54, 27.94, 270),
        ("6", "V5", "power_out", 7.62, 27.94, 270), ("7", "VINT", "power_out", 12.7, 27.94, 270),
        ("5", "GND", "power_in", -3.81, -27.94, 90), ("29", "GND", "power_in", -1.27, -27.94, 90),
        ("38", "GND", "power_in", 1.27, -27.94, 90), ("39", "PAD", "power_in", 3.81, -27.94, 90),
        ("8", "SLEEPn", "input", -17.78, 17.78, 0), ("9", "RESET", "input", -17.78, 15.24, 0),
        ("10", "STEP/AIN1", "input", -17.78, 10.16, 0), ("11", "DIR/AIN2", "input", -17.78, 7.62, 0),
        ("12", "BIN1", "input", -17.78, 5.08, 0), ("13", "BIN2", "input", -17.78, 2.54, 0),
        ("14", "SCLK", "input", -17.78, -2.54, 0), ("15", "SDATI", "input", -17.78, -5.08, 0),
        ("16", "SCS", "input", -17.78, -7.62, 0), ("17", "SDATO", "open_collector", -17.78, -10.16, 0),
        ("18", "FAULTn", "open_collector", -17.78, -15.24, 0),
        ("19", "STALLn/BEMFVn", "open_collector", -17.78, -17.78, 0),
        ("20", "BEMF", "output", -17.78, -20.32, 0),
        ("37", "AOUT1", "input", 17.78, 20.32, 180), ("36", "A1HS", "output", 17.78, 17.78, 180),
        ("35", "A1LS", "output", 17.78, 15.24, 180), ("30", "AOUT2", "input", 17.78, 12.7, 180),
        ("31", "A2HS", "output", 17.78, 10.16, 180), ("32", "A2LS", "output", 17.78, 7.62, 180),
        ("34", "AISENP", "input", 17.78, 5.08, 180), ("33", "AISENN", "input", 17.78, 2.54, 180),
        ("28", "BOUT1", "input", 17.78, -2.54, 180), ("27", "B1HS", "output", 17.78, -5.08, 180),
        ("26", "B1LS", "output", 17.78, -7.62, 180), ("21", "BOUT2", "input", 17.78, -10.16, 180),
        ("22", "B2HS", "output", 17.78, -12.7, 180), ("23", "B2LS", "output", 17.78, -15.24, 180),
        ("25", "BISENP", "input", 17.78, -17.78, 180), ("24", "BISENN", "input", 17.78, -20.32, 180),
    ],
    hide_names=False,
)

MLPF = dict(
    name="MLPF-WB55-01E3", ref="FL", footprint=f"{LIB}:MLPF-WB55-01E3_CSP-6_1.0x1.6mm",
    datasheet="https://www.st.com/resource/en/datasheet/mlpf-wb55-01e3.pdf",
    description="2.4 GHz matched low-pass filter (IPD) for STM32WB55 UFQFPN48, bumpless CSP 1.0 x 1.6 mm "
                "(pads: ST DS12804 Table 6)",
    body=(-5.08, -2.54, 5.08, 2.54),
    pins=[
        ("A3", "IN", "passive", -7.62, 0.0, 0), ("A1", "OUT", "passive", 7.62, 0.0, 180),
        ("A2", "GND4", "passive", -2.54, -5.08, 90), ("B1", "GND3", "passive", 0.0, -5.08, 90),
        ("B2", "GND2", "passive", 2.54, -5.08, 90), ("B3", "GND1", "passive", 5.08, -5.08, 90),
    ],
    hide_names=True,
)


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def font(hide=False, justify=None):
    j = f" (justify {justify})" if justify else ""
    h = " (hide yes)" if hide else ""
    return f"(effects (font (size 1.27 1.27)){j}{h})"


def symbol(d):
    x0, y0, x1, y1 = d["body"]
    lines = [f"\t(symbol {q(d['name'])}",
             "\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)",
             *(["\t\t(pin_names (hide yes))"] if d["hide_names"] else []),
             f"\t\t(property \"Reference\" {q(d['ref'])} (at {x0} {y1 + 1.27} 0) {font(justify='left')})",
             f"\t\t(property \"Value\" {q(d['name'])} (at {x0} {y0 - 1.27} 0) {font(justify='left')})",
             f"\t\t(property \"Footprint\" {q(d['footprint'])} (at 0 0 0) {font(hide=True)})",
             f"\t\t(property \"Datasheet\" {q(d['datasheet'])} (at 0 0 0) {font(hide=True)})",
             f"\t\t(property \"Description\" {q(d['description'])} (at 0 0 0) {font(hide=True)})",
             f"\t\t(symbol {q(d['name'] + '_0_1')}",
             f"\t\t\t(rectangle (start {x0} {y1}) (end {x1} {y0}) (stroke (width 0.254) (type default)) "
             f"(fill (type background)))",
             "\t\t)",
             f"\t\t(symbol {q(d['name'] + '_1_1')}"]
    for num, name, kind, x, y, ang in d["pins"]:
        lines.append(f"\t\t\t(pin {kind} line (at {x} {y} {ang}) (length 2.54) (name {q(name)} {font()}) "
                     f"(number {q(num)} {font()}))")
    lines += ["\t\t)", "\t\t(embedded_fonts no)", "\t)"]
    return "\n".join(lines)


def symbol_library():
    return ("(kicad_symbol_lib\n\t(version 20251024)\n\t(generator \"stepper_ble_make_library\")\n"
            "\t(generator_version \"10.0\")\n" + symbol(DRV8711) + "\n" + symbol(MLPF) + "\n)\n")


def mlpf_footprint():
    """ST DS12804 Fig. 13: 200 um square lands at x +-0.25 mm (column A left, B right, top view) and y 0, +-0.587 mm
    (row 1 top), 300 um mask openings (0.05 mm expansion), stencil aligned with the lands (Fig. 15)."""
    pads = []
    for col, x in (("A", -0.25), ("B", 0.25)):
        for row, y in ((1, -0.587), (2, 0.0), (3, 0.587)):
            pads.append(f"\t(pad \"{col}{row}\" smd rect (at {x} {y}) (size 0.2 0.2) "
                        "(layers \"F.Cu\" \"F.Mask\" \"F.Paste\") (solder_mask_margin 0.05))")
    lines = [
        "(footprint \"MLPF-WB55-01E3_CSP-6_1.0x1.6mm\"",
        "\t(version 20260206)",
        "\t(generator \"stepper_ble_make_library\")",
        "\t(layer \"F.Cu\")",
        "\t(descr \"ST MLPF-WB55-01E3 bumpless CSP, 1.0 x 1.6 mm, 6 lands 0.2 mm, pitch 0.5 x 0.587 mm "
        "(DS12804 Rev 2 Fig. 13)\")",
        "\t(tags \"MLPF IPD CSP STM32WB\")",
        "\t(property \"Reference\" \"REF**\" (at 0 -1.6 0) (layer \"F.SilkS\") "
        "(effects (font (size 1 1) (thickness 0.15))))",
        "\t(property \"Value\" \"MLPF-WB55-01E3\" (at 0 1.6 0) (layer \"F.Fab\") "
        "(effects (font (size 0.5 0.5) (thickness 0.08))))",
        "\t(property \"Footprint\" \"\" (at 0 0 0) (layer \"F.Fab\") (hide yes) (effects (font (size 1 1))))",
        "\t(property \"Datasheet\" \"https://www.st.com/resource/en/datasheet/mlpf-wb55-01e3.pdf\" (at 0 0 0) "
        "(layer \"F.Fab\") (hide yes) (effects (font (size 1 1))))",
        "\t(property \"Description\" \"\" (at 0 0 0) (layer \"F.Fab\") (hide yes) (effects (font (size 1 1))))",
        "\t(attr smd)",
        "\t(fp_rect (start -0.5 -0.8) (end 0.5 0.8) (stroke (width 0.1) (type solid)) (fill no) (layer \"F.Fab\"))",
        "\t(fp_circle (center -0.3 -0.6) (end -0.25 -0.6) (stroke (width 0.05) (type solid)) (fill yes) "
        "(layer \"F.Fab\"))",
        "\t(fp_line (start -0.75 -1.05) (end -0.45 -1.05) (stroke (width 0.12) (type solid)) (layer \"F.SilkS\"))",
        "\t(fp_rect (start -0.65 -0.95) (end 0.65 0.95) (stroke (width 0.05) (type solid)) (fill no) "
        "(layer \"F.CrtYd\"))",
    ] + pads + ["\t(embedded_fonts no)", ")"]
    return "\n".join(lines) + "\n"


def adapted(lib, name, new_name, note, edit):
    """A KiCad library footprint with one documented edit, renamed for the project library."""
    text = (KICAD_FP / f"{lib}.pretty" / f"{name}.kicad_mod").read_text(encoding="utf-8")
    text = text.replace(f'(footprint "{name}"', f'(footprint "{new_name}"', 1)
    text = re.sub(r'\(descr "([^"]*)"\)', lambda m: f'(descr "{m.group(1)}; {note}")', text, count=1)
    out = edit(text)
    if out == text:
        raise SystemExit(f"{name}: the edit changed nothing; KiCad's footprint differs from the one this was written for")
    return out


def nexfet_ti_land(text):
    return re.sub(r'(\(pad "[1-4]" smd roundrect\s*\(at -1\.44 [-0-9.]+\)\s*)\(size 0\.63 0\.5\)', r'\1(size 0.6 0.3)', text)


def antenna_via(text):
    return re.sub(r'(\(pad "2" thru_hole rect\s*\(at 2\.1 0\)\s*\(size 0\.9 0\.5\)\s*)\(drill 0\.3\)', r'\1(drill 0.2)', text)


ADAPTED = [
    ("Package_SON", "VSON-8_3.3x3.3mm_P0.65mm_NexFET", "VSON-8_3.3x3.3mm_P0.65mm_NexFET_TI-land",
     "pads 1-4 0.6 x 0.3 mm per TI SLPS633 7.2 (stepper-ble make_library.py)", nexfet_ti_land),
    ("RF_Antenna", "Texas_SWRA117D_2.4GHz_Left", "Texas_SWRA117D_2.4GHz_Left_Drill0.2",
     "shorting via drilled 0.2 mm for a 0.15 mm annular ring (stepper-ble make_library.py)", antenna_via),
]


SYM_TABLE = f"""(sym_lib_table
\t(version 7)
\t(lib (name "{LIB}") (type "KiCad") (uri "${{KIPRJMOD}}/{LIB}.kicad_sym") (options "") (descr "project library"))
)
"""
FP_TABLE = f"""(fp_lib_table
\t(version 7)
\t(lib (name "{LIB}") (type "KiCad") (uri "${{KIPRJMOD}}/{LIB}.pretty") (options "") (descr "project library"))
)
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old != text:
        path.write_text(text, encoding="utf-8")
    return path


def main():
    files = [write(OUT / f"{LIB}.kicad_sym", symbol_library()),
             write(OUT / f"{LIB}.pretty" / "MLPF-WB55-01E3_CSP-6_1.0x1.6mm.kicad_mod", mlpf_footprint()),
             *[write(OUT / f"{LIB}.pretty" / f"{new}.kicad_mod", adapted(lib, name, new, note, edit))
               for lib, name, new, note, edit in ADAPTED],
             write(OUT / "sym-lib-table", SYM_TABLE),
             write(OUT / "fp-lib-table", FP_TABLE)]
    for f in files:
        print("wrote", f.relative_to(ROOT))


if __name__ == "__main__":
    main()
