#!/usr/bin/env python3
"""Write the project's own symbol and footprint library: the two parts KiCad 10's libraries lack.

    python3 scripts/make_library.py          writes hardware/stepper-ble/stepper-ble.kicad_sym, stepper-ble.pretty/
                                             and the project's sym-lib-table and fp-lib-table

Library policy D19 (schematic-capture §6) step 3: hand transcription, with the datasheet table cited in the
symbol's description. Run library_check.py after any change.

  DRV8711       TI SLVSC40H §5 "Pin Configuration and Functions" (DCP, 38-pin HTSSOP, PowerPAD = pin 39).
                Footprint: KiCad's HTSSOP-38 4.4 x 9.7 mm, EP 2.74 x 4.75 mm (TI DCP0038A exposed pad 2.43-2.90 x
                3.94-4.70 mm, SLVSC40H package drawing), so no project footprint is needed.
  MLPF-WB55-01E3  ST DS12804 Rev 2, Table 6 "Pad description" and Figure 13 "PCB land pattern recommendations":
                bumpless CSP, 2 x 3 pads, X pitch 0.500 mm, Y pitch 0.587 mm, 0.200 mm pads.
  Texas_SWRA117D_2.4GHz_Left_D0.2  KiCad's TI SWRA117D antenna with the ground pad's drill 0.3 -> 0.2 mm: the
                pad is 0.5 mm wide (TI's trace width W2), so a 0.3 mm drill leaves a 0.10 mm annular ring, under
                JLCPCB's 0.15 mm; 0.2 mm keeps the copper and gives 0.15 mm (decision D-006).
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware" / "stepper-ble"
NAME = "stepper-ble"


def fx(size=1.27, hide=False):
    return f'(effects (font (size {size} {size})){" (hide yes)" if hide else ""})'


def prop(key, value, x=0.0, y=0.0, hide=False):
    return f'\t\t(property "{key}" "{value}" (at {x} {y} 0) {fx(hide=hide)})\n'


def pin(kind, x, y, angle, name, number):
    return (f'\t\t\t(pin {kind} line (at {x} {y} {angle}) (length 2.54) (name "{name}" {fx()}) '
            f'(number "{number}" {fx()}))\n')


def symbol(name, ref, value, footprint, datasheet, description, width, height, left, right, top=(), bottom=(),
           hide_names=False):
    """A box symbol: left/right are [(number, name, kind)] from top to bottom, top/bottom from left to right."""
    w, h = width / 2, height / 2
    s = f'\t(symbol "{name}"\n' + ("\t\t(pin_names (hide yes))\n" if hide_names else "")
    s += '\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)\n'
    s += prop("Reference", ref, -w, h + 1.27)
    s += prop("Value", value, -w, -h - 1.27)
    s += prop("Footprint", footprint, 0, 0, hide=True)
    s += prop("Datasheet", datasheet, 0, 0, hide=True)
    s += prop("Description", description, 0, 0, hide=True)
    s += f'\t\t(symbol "{name}_0_1"\n\t\t\t(rectangle (start {-w} {h}) (end {w} {-h}) (stroke (width 0.254) (type default)) (fill (type background)))\n\t\t)\n'
    s += f'\t\t(symbol "{name}_1_1"\n'
    for i, (num, pname, kind) in enumerate(left):
        s += pin(kind, -w - 2.54, round(h - 2.54 - i * 2.54, 2), 0, pname, num)
    for i, (num, pname, kind) in enumerate(right):
        s += pin(kind, w + 2.54, round(h - 2.54 - i * 2.54, 2), 180, pname, num)
    x0 = -round((len(top) - 1) / 2) * 2.54
    for i, (num, pname, kind) in enumerate(top):
        s += pin(kind, round(x0 + i * 2.54, 2), h + 2.54, 270, pname, num)
    for i, (num, pname, kind) in enumerate(bottom):
        s += pin(kind, round(-w + 2.54 + i * 2.54, 2), -h - 2.54, 90, pname, num)
    s += '\t\t)\n\t\t(embedded_fonts no)\n\t)\n'
    return s


DRV8711 = symbol(
    "DRV8711", "U", "DRV8711",
    "Package_SO:HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm_ThermalVias",
    "https://www.ti.com/lit/ds/symlink/drv8711.pdf",
    "Stepper pre-driver with SPI, 8-52 V, external N-FETs, HTSSOP-38 (TI SLVSC40H §5 Pin Functions)",
    width=25.4, height=55.88,
    left=[("1", "CP1", "passive"), ("2", "CP2", "passive"), ("3", "VCP", "passive"),
          ("6", "V5", "power_out"), ("7", "VINT", "power_out"), ("8", "SLEEPn", "input"), ("9", "RESET", "input"),
          ("10", "STEP/AIN1", "input"), ("11", "DIR/AIN2", "input"), ("12", "BIN1", "input"), ("13", "BIN2", "input"),
          ("14", "SCLK", "input"), ("15", "SDATI", "input"), ("16", "SCS", "input"), ("17", "SDATO", "open_collector"),
          ("18", "FAULTn", "open_collector"), ("19", "STALLn/BEMFVn", "open_collector"), ("20", "BEMF", "output")],
    right=[("36", "A1HS", "output"), ("37", "AOUT1", "passive"), ("35", "A1LS", "output"), ("31", "A2HS", "output"),
           ("30", "AOUT2", "passive"), ("32", "A2LS", "output"), ("34", "AISENP", "passive"),
           ("27", "B1HS", "output"), ("28", "BOUT1", "passive"), ("26", "B1LS", "output"), ("22", "B2HS", "output"),
           ("21", "BOUT2", "passive"), ("23", "B2LS", "output"), ("25", "BISENP", "passive")],
    top=[("4", "VM", "power_in")],
    bottom=[("5", "GND", "power_in"), ("29", "GND", "passive"), ("38", "GND", "passive"), ("39", "GND", "passive"),
            ("33", "AISENN", "passive"), ("24", "BISENN", "passive")])

MLPF = symbol(
    "MLPF-WB55-01E3", "FL", "MLPF-WB55-01E3",
    f"{NAME}:ST_MLPF-WB55-01E3_CSP-6",
    "https://www.st.com/resource/en/datasheet/mlpf-wb55-01e3.pdf",
    "2.4 GHz matching network and harmonic filter for STM32WB55Cx/Rx, 50 ohm antenna side (ST DS12804 Table 6)",
    width=10.16, height=7.62,
    left=[("A3", "IN", "passive")], right=[("A1", "OUT", "passive")],
    bottom=[("B3", "GND1", "passive"), ("B2", "GND2", "passive"), ("B1", "GND3", "passive")],
    top=[("A2", "GND4", "passive")], hide_names=True)

LIB = ('(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "make_library.py")\n\t(generator_version "10.0")\n'
       + DRV8711 + MLPF + ')\n')


def mlpf_footprint():
    """DS12804 Fig. 13, top view (pads down): column A (OUT, GND4, IN) and column B (GND3, GND2, GND1)."""
    pads = ""
    for col, x in (("A", -0.25), ("B", 0.25)):
        for row, y in ((1, -0.587), (2, 0.0), (3, 0.587)):
            pads += (f'\t(pad "{col}{row}" smd circle (at {x} {y}) (size 0.2 0.2) (layers "F.Cu" "F.Paste" "F.Mask") '
                     f'(solder_mask_margin 0.05))\n')
    return ('(footprint "ST_MLPF-WB55-01E3_CSP-6"\n\t(version 20260206)\n\t(generator "make_library.py")\n'
            '\t(layer "F.Cu")\n'
            '\t(descr "ST MLPF-WB55-01E3 bumpless CSP, 2x3 pads, pitch 0.500 x 0.587 mm, DS12804 Rev 2 Fig. 13")\n'
            '\t(attr smd)\n'
            '\t(property "Reference" "REF**" (at 0 -1.4 0) (layer "F.SilkS") (effects (font (size 0.5 0.5) (thickness 0.08))))\n'
            '\t(property "Value" "MLPF-WB55-01E3" (at 0 1.4 0) (layer "F.Fab") (effects (font (size 0.5 0.5) (thickness 0.08))))\n'
            '\t(fp_rect (start -0.5 -0.8) (end 0.5 0.8) (stroke (width 0.1) (type solid)) (fill no) (layer "F.Fab"))\n'
            '\t(fp_rect (start -0.75 -1.05) (end 0.75 1.05) (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))\n'
            '\t(fp_circle (center -0.7 -0.95) (end -0.65 -0.95) (stroke (width 0.1) (type solid)) (fill yes) (layer "F.SilkS"))\n'
            + pads + '\t(embedded_fonts no)\n)\n')


SYSTEM_FP = pathlib.Path("/usr/share/kicad/footprints")


def antenna_footprint():
    src = (SYSTEM_FP / "RF_Antenna.pretty" / "Texas_SWRA117D_2.4GHz_Left.kicad_mod").read_text(encoding="utf-8")
    old = '(size 0.9 0.5)\n\t\t(drill 0.3)'
    if old not in src:
        raise SystemExit("KiCad's Texas_SWRA117D_2.4GHz_Left changed: re-check the ground pad before patching it")
    out = src.replace(old, '(size 0.9 0.5)\n\t\t(drill 0.2)')
    return out.replace('(footprint "Texas_SWRA117D_2.4GHz_Left"', '(footprint "Texas_SWRA117D_2.4GHz_Left_D0.2"', 1)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{NAME}.kicad_sym").write_text(LIB, encoding="utf-8")
    pretty = OUT / f"{NAME}.pretty"
    pretty.mkdir(exist_ok=True)
    (pretty / "ST_MLPF-WB55-01E3_CSP-6.kicad_mod").write_text(mlpf_footprint(), encoding="utf-8")
    (pretty / "Texas_SWRA117D_2.4GHz_Left_D0.2.kicad_mod").write_text(antenna_footprint(), encoding="utf-8")
    (OUT / "sym-lib-table").write_text(
        f'(sym_lib_table\n\t(version 7)\n\t(lib (name "{NAME}") (type "KiCad") (uri "${{KIPRJMOD}}/{NAME}.kicad_sym") '
        f'(options "") (descr "project library"))\n)\n', encoding="utf-8")
    (OUT / "fp-lib-table").write_text(
        f'(fp_lib_table\n\t(version 7)\n\t(lib (name "{NAME}") (type "KiCad") (uri "${{KIPRJMOD}}/{NAME}.pretty") '
        f'(options "") (descr "project footprints"))\n)\n', encoding="utf-8")
    print(f"wrote {OUT / (NAME + '.kicad_sym')}, {pretty} and the project library tables")


if __name__ == "__main__":
    main()
