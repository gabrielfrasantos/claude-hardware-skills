"""Tests for refblock.py on small synthetic KiCad 10 boards: a vendor board and ours."""

import json
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import refblock as RB  # noqa: E402

_n = [0]


def uid():
    _n[0] += 1
    return f"00000000-0000-4000-8000-{_n[0]:012d}"


def footprint(ref, lib, x, y, rot, pads, side="F", locked=False):
    cu = f"{side}.Cu"
    lines = [f'\t(footprint "{lib}"']
    if locked:
        lines.append("\t\t(locked yes)")
    lines += [f'\t\t(layer "{cu}")', f'\t\t(uuid "{uid()}")', f"\t\t(at {x} {y}" + (f" {rot})" if rot else ")"),
              f'\t\t(property "Reference" "{ref}"\n\t\t\t(at 0 -2 {rot})\n\t\t\t(layer "{side}.SilkS")\n'
              f'\t\t\t(uuid "{uid()}")\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)',
              f'\t\t(property "Value" "V"\n\t\t\t(at 0 2 {rot})\n\t\t\t(layer "{side}.Fab")\n\t\t\t(uuid "{uid()}")\n\t\t)',
              f'\t\t(fp_line\n\t\t\t(start -2 -2)\n\t\t\t(end 2 -2)\n\t\t\t(stroke\n\t\t\t\t(width 0.05)\n'
              f'\t\t\t\t(type solid)\n\t\t\t)\n\t\t\t(layer "{side}.CrtYd")\n\t\t\t(uuid "{uid()}")\n\t\t)']
    for num, dx, dy, net, w, h in pads:
        lines.append(f'\t\t(pad "{num}" smd roundrect\n\t\t\t(at {dx} {dy}' + (f" {rot})" if rot else ")") +
                     f'\n\t\t\t(size {w} {h})\n\t\t\t(layers "{cu}" "{side}.Mask" "{side}.Paste")\n'
                     f'\t\t\t(roundrect_rratio 0.25)\n' + (f'\t\t\t(net "{net}")\n' if net else "") +
                     f'\t\t\t(uuid "{uid()}")\n\t\t)')
    lines.append("\t)")
    return "\n".join(lines)


def seg(x1, y1, x2, y2, net, w=0.25, layer="F.Cu"):
    return (f'\t(segment\n\t\t(start {x1} {y1})\n\t\t(end {x2} {y2})\n\t\t(width {w})\n\t\t(layer "{layer}")\n'
            f'\t\t(net "{net}")\n\t\t(uuid "{uid()}")\n\t)')


def via(x, y, net, size=0.6, drill=0.3):
    return (f'\t(via\n\t\t(at {x} {y})\n\t\t(size {size})\n\t\t(drill {drill})\n\t\t(layers "F.Cu" "B.Cu")\n'
            f'\t\t(net "{net}")\n\t\t(uuid "{uid()}")\n\t)')


def zone(net, layer, pts, keepout=False):
    body = " ".join(f"(xy {x} {y})" for x, y in pts)
    ko = ("\t\t(keepout\n\t\t\t(tracks not_allowed)\n\t\t\t(vias not_allowed)\n\t\t\t(pads allowed)\n"
          "\t\t\t(copperpour not_allowed)\n\t\t\t(footprints allowed)\n\t\t)\n") if keepout else ""
    return ("\t(zone\n" + (f'\t\t(net "{net}")\n' if net else "") + f'\t\t(layer "{layer}")\n\t\t(uuid "{uid()}")\n'
            f"\t\t(hatch edge 0.5)\n\t\t(connect_pads\n\t\t\t(clearance 0.3)\n\t\t)\n\t\t(min_thickness 0.25)\n{ko}"
            f"\t\t(fill yes\n\t\t\t(thermal_gap 0.5)\n\t\t\t(thermal_bridge_width 0.5)\n\t\t)\n"
            f"\t\t(polygon\n\t\t\t(pts\n\t\t\t\t{body}\n\t\t\t)\n\t\t)\n"
            f'\t\t(filled_polygon\n\t\t\t(layer "{layer}")\n\t\t\t(pts\n\t\t\t\t{body}\n\t\t\t)\n\t\t)\n\t)')


def board(items, fonts=True):
    head = ('(kicad_pcb\n\t(version 20260206)\n\t(generator "pcbnew")\n\t(generator_version "10.0")\n'
            '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n\t)\n')
    return head + "\n".join(items) + ("\n\t(embedded_fonts no)\n)\n" if fonts else "\n)\n")


# U1's land is off-centre on purpose (centre of its pads at local x 0.3), turned 90 degrees on the vendor board.
U1_PADS = [("1", -0.7, -0.5, "IN"), ("2", -0.7, 0.5, "GND"), ("3", 1.3, 0.5, "OUT"), ("4", 1.3, -0.5, "VM")]
R1_PADS = [("1", -0.8, 0, "OUT"), ("2", 0.8, 0, "GND")]


def pads(spec, nets=None, size=(0.6, 0.6)):
    return [(n, dx, dy, (nets or {}).get(net, net), *size) for n, dx, dy, net in spec]


def vendor_text(noise=True, gnd_width=0.25):
    u1 = [(n, 100 + RB.turn(dx, dy, 90)[0], 50 + RB.turn(dx, dy, 90)[1]) for n, dx, dy, _ in U1_PADS]
    p3 = next((x, y) for n, x, y in u1 if n == "3")
    items = [
        footprint("U1", "Vendor:SO4", 100, 50, 90, pads(U1_PADS)),
        footprint("R1", "Vendor:R0603", 104, 50, 0, pads(R1_PADS)),
        footprint("J1", "Vendor:Conn", 130, 50, 0, pads([("1", 0, 0, "OUT")])),
        seg(p3[0], p3[1], 103.2, p3[1], "OUT"), seg(103.2, p3[1], 103.2, 50, "OUT"),     # U1.3 -> R1.1
        seg(103.2, p3[1], 103.2, 46.0, "OUT"),                                             # stub: pruned
        seg(103.2, 50, 130, 50, "OUT"),                                                    # leaves the box
        seg(104.8, 50, 104.8, 52, "GND", w=gnd_width), via(104.8, 52, "GND"),              # R1.2 -> via -> pour
        via(97, 46, "GND"),                                                                # stitching: kept
        via(98, 53, "IN"),                                                                 # orphan: pruned
        zone("GND", "B.Cu", [(90, 40), (115, 40), (115, 60), (90, 60)]),                   # cut to the box
        zone("", "F.Cu", [(96, 54), (98, 54), (98, 54.5), (96, 54.5)], keepout=True),
    ]
    if noise:
        items.append(seg(96, 47, 97, 47, "NOISE"))
    return board(items)


def ours_text(r_nets=None, r_pads=None, locked=False, fonts=True):
    on = {"IN": "/drv/IN", "OUT": "/drv/OUT", "VM": "VBAT", "GND": "GND"}
    return board([
        footprint("U501", "Ours:SO4", 20, 20, 0, pads(U1_PADS, on), locked=locked),
        footprint("R501", "Ours:R0603", 30, 20, 0, pads(r_pads or R1_PADS, r_nets or on)),
        footprint("C9", "Ours:C0402", 61, 41, 0, pads([("1", -0.5, 0, "GND"), ("2", 0.5, 0, "VBAT")])),
    ], fonts=fonts)


MAP = {"name": "Vendor drive", "source": "Derived from Vendor EVM design files (test)",
       "box": [95, 45, 108, 55], "parts": {"U1": "U501", "R1": "R501"}}


@pytest.fixture
def work(tmp_path):
    (tmp_path / "vendor.kicad_pcb").write_text(vendor_text())
    (tmp_path / "ours.kicad_pcb").write_text(ours_text())
    (tmp_path / "map.json").write_text(json.dumps(dict(MAP, drop_nets=["NOISE"])))
    return tmp_path


def extract(w, *extra):
    return RB.main(["extract", str(w / "vendor.kicad_pcb"), str(w / "map.json"), "-o", str(w / "block.json"),
                    "--board", str(w / "ours.kicad_pcb"), *extra])


def place(w, *extra):
    return RB.main(["place", str(w / "block.json"), str(w / "ours.kicad_pcb"), *extra])


# ------------------------------------------------------------------------------------------------- unit
def test_turn_matches_kicad_sense():
    # KiCad turns counter-clockwise on a y-down board: +x goes to -y at 90 degrees
    x, y = RB.turn(1, 0, 90)
    assert (round(x, 9), round(y, 9)) == (0, -1)


def test_fit_angle_recovers_a_turn():
    src = [(0, 0), (2, 0), (2, 1)]
    dst = [RB.turn(x, y, 37) for x, y in src]
    a, _, _ = RB.fit_angle(src, dst)
    assert a == pytest.approx(37)


def test_rewrite_moves_points_and_angles_but_not_primitives():
    t = ('(pad "1" custom (at 1 2 90) (size 1 1) (primitives (gr_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)))) '
         '(net "A") (uuid "u"))')
    out = RB.rewrite(t, point=lambda x, y: (x + 10, y), angle=lambda a: a + 90, net=lambda n: "B")
    assert "(at 11 2 180)" in out          # a pad's angle: [0, 360)
    assert "(xy 1 0)" in out and "(xy 11" not in out
    assert '(net "B")' in out


# ------------------------------------------------------------------------------------------------- extract
def test_net_on_no_copied_pad_is_dropped_with_a_note(tmp_path, capsys):
    (tmp_path / "vendor.kicad_pcb").write_text(vendor_text())
    (tmp_path / "ours.kicad_pcb").write_text(ours_text())
    (tmp_path / "map.json").write_text(json.dumps(MAP))
    assert extract(tmp_path) == 0
    assert "dropped vendor net NOISE" in capsys.readouterr().out
    assert all(i["net"] != "NOISE" for i in json.loads((tmp_path / "block.json").read_text())["items"])


def test_unmapped_net_on_a_copied_pad_is_an_error(tmp_path, capsys):
    (tmp_path / "vendor.kicad_pcb").write_text(vendor_text())
    (tmp_path / "map.json").write_text(json.dumps(dict(MAP, nets={"GND": "GND"})))
    assert RB.main(["extract", str(tmp_path / "vendor.kicad_pcb"), str(tmp_path / "map.json"),
                    "-o", str(tmp_path / "block.json")]) == 1
    assert "vendor net OUT: on a copied pad" in capsys.readouterr().out
    assert not (tmp_path / "block.json").exists()


def test_extract_derives_nets_prunes_and_cuts(work):
    assert extract(work) == 0
    b = json.loads((work / "block.json").read_text())
    assert b["net_map"] == {"GND": "GND", "IN": "/drv/IN", "OUT": "/drv/OUT", "VM": "VBAT"}
    kinds = [i["kind"] for i in b["items"]]
    assert kinds.count("segment") == 3          # U1.3 -> R1.1 (two), R1.2 -> via
    assert kinds.count("via") == 2              # the pour via and the stitching via
    assert b["pruned"]["tracks"] == 1 and b["pruned"]["vias"] == 1
    pours = [i for i in b["items"] if i["kind"] == "zone" and i["net"]]
    assert len(pours) == 1
    xs = [p[0] for p in pours[0]["polygon"]]
    ys = [p[1] for p in pours[0]["polygon"]]
    assert (min(xs), max(xs), min(ys), max(ys)) == (95, 108, 45, 55)
    assert "filled_polygon" not in pours[0]["sexpr"]
    assert sum(1 for i in b["items"] if i["kind"] == "zone" and not i["net"]) == 1   # the keep-out
    assert b["source"].startswith("Derived from")


def test_mirrored_wiring_is_caught_at_extract(work, capsys):
    (work / "ours.kicad_pcb").write_text(ours_text(r_nets={"OUT": "GND", "GND": "/drv/OUT"}))
    assert extract(work) == 1
    assert "vendor net OUT lands on" in capsys.readouterr().out


def test_footprint_export_recentres_and_unturns(work):
    assert extract(work, "--footprints", str(work / "lib.pretty"), "--prefix", "V_") == 0
    text = (work / "lib.pretty" / "V_SO4.kicad_mod").read_text()
    fp = RB.R.parse_sexpr(text)
    assert fp[1] == "V_SO4" and RB.R.child(fp, "at") is None
    got = {p[1]: tuple(float(v) for v in RB.R.child(p, "at")[1:]) for p in RB.R.children(fp, "pad")}
    for num, dx, dy, _ in U1_PADS:
        assert got[num][0] == pytest.approx(dx - 0.3) and got[num][1] == pytest.approx(dy)
        assert len(got[num]) == 2 or got[num][2] == pytest.approx(0)
    assert "(net " not in text and '"REF**"' in text and "Derived from Vendor" in text


# ------------------------------------------------------------------------------------------------- place
def our_pad_positions(path, ref):
    f = RB.PCB(path).by_ref()[ref]
    return {p["num"]: (p["x"], p["y"]) for p in f["pads"]}, f


def test_place_lands_every_pad_on_the_vendors(work):
    assert extract(work) == 0
    assert place(work, "--at", "60", "40", "--rot", "90") == 0
    b = json.loads((work / "block.json").read_text())
    fr = RB.Frame((101.5, 50), (60, 40), 90)
    for part in b["parts"]:
        got, f = our_pad_positions(work / "ours.kicad_pcb", part["ours"])
        for num, x, y, _ in part["pads"]:
            assert math.dist(got[num], fr.point(x, y)) < 1e-5
    # U1 is at 90 on the vendor's board, the block turns 90 more
    _, u = our_pad_positions(work / "ours.kicad_pcb", "U501")
    assert u["rot"] == pytest.approx(180)
    fp = RB.R.parse_sexpr(RB.PCB(work / "ours.kicad_pcb").text[u["s"]:u["e"]])
    assert all(float(RB.R.child(p, "at")[3]) == pytest.approx(180) for p in RB.R.children(fp, "pad"))
    r = RB.PCB(work / "ours.kicad_pcb").by_ref()["R501"]
    assert r["rot"] == pytest.approx(90)


def test_moving_back_to_zero_writes_angles_as_kicad_does(work):
    pcb = RB.PCB(work / "ours.kicad_pcb")
    f = pcb.by_ref()["R501"]
    turned = RB.footprint_moved(pcb, f, f["x"], f["y"], 90)
    text = pcb.text[:f["s"]] + turned + pcb.text[f["e"]:]
    (work / "ours.kicad_pcb").write_text(text)
    pcb2 = RB.PCB(work / "ours.kicad_pcb")
    back = RB.footprint_moved(pcb2, pcb2.by_ref()["R501"], f["x"], f["y"], 0)
    assert back == pcb.text[f["s"]:f["e"]]


def test_angles_are_written_as_kicad_does():
    assert RB.rewrite("(footprint (at 1 2 90) (pad (at 0 0 90)))", angle=lambda a: a + 180) == \
        "(footprint (at 1 2 90) (pad (at 0 0 270)))"         # a footprint's own position is footprint_moved's
    assert RB.rewrite("(at 1 2 90)", angle=lambda a: a + 180) == "(at 1 2 -90)"
    # back to 0: a pad leaves the angle out, a text keeps it
    assert RB.rewrite("(fp (pad (at 1 2 90)) (property (at 0 0 90)))", angle=lambda a: a - 90) == \
        "(fp (pad (at 1 2)) (property (at 0 0 0)))"


def test_place_copper_nets_group_and_shared_parser(work):
    assert extract(work) == 0
    assert place(work, "--at", "60", "40") == 0
    pcb = RB.PCB(work / "ours.kicad_pcb")
    nets = sorted(i["net"] for i in pcb.items if i["kind"] == "segment")
    assert nets == ["/drv/OUT", "/drv/OUT", "GND"]
    g = [g for g in pcb.groups if g["name"] == "Vendor drive"]
    assert len(g) == 1 and len(g[0]["members"]) == len(json.loads((work / "block.json").read_text())["items"]) + 2
    z = [i for i in pcb.items if i["kind"] == "zone" and i["net"] == "GND"][0]
    assert 'name "Vendor drive B.Cu GND' in pcb.text[z["s"]:z["e"]]
    assert pcb.text.rstrip().endswith("(embedded_fonts no)\n)")
    RB.R.Board(text=pcb.text)            # the pcb-design-rules parser reads it


def test_place_is_a_noop_then_replace_does_not_duplicate(work, capsys):
    assert extract(work) == 0
    assert place(work, "--at", "60", "40", "--rot", "180") == 0
    first = (work / "ours.kicad_pcb").read_text()
    assert place(work) == 0
    assert "already on" in capsys.readouterr().out
    assert (work / "ours.kicad_pcb").read_text() == first
    assert place(work, "--replace") == 0          # follows the parts
    again = (work / "ours.kicad_pcb").read_text()
    for kind in ("(segment", "(via", "(zone", "(group"):
        assert again.count(kind) == first.count(kind)
    assert RB.main(["check", str(work / "block.json"), str(work / "ours.kicad_pcb")]) == 0


def test_handed_over_copy_is_not_pasted_twice(work, capsys):
    assert extract(work) == 0
    assert place(work, "--at", "60", "40") == 0
    p = RB.PCB(work / "ours.kicad_pcb")
    g = p.groups[0]
    (work / "ours.kicad_pcb").write_text(p.text[:g["s"]] + p.text[g["e"]:])     # the owner ungroups it
    assert place(work, "--at", "60", "40") == 1
    assert "outside its group" in capsys.readouterr().out


@pytest.mark.parametrize("variant,needle", [
    (dict(r_nets={"OUT": "GND", "GND": "/drv/OUT", "IN": "/drv/IN", "VM": "VBAT"}), "schematic disagrees"),
    (dict(locked=True), "locked"),
    (dict(r_pads=[("1", -0.9, 0, "OUT"), ("2", 0.9, 0, "GND")]), "land differs"),
])
def test_place_refuses(work, capsys, variant, needle):
    assert extract(work) == 0
    (work / "ours.kicad_pcb").write_text(ours_text(**variant))
    before = (work / "ours.kicad_pcb").read_text()
    assert place(work, "--at", "60", "40") == 1
    out = capsys.readouterr().out
    assert needle in out and "nothing written" in out
    assert (work / "ours.kicad_pcb").read_text() == before


def test_place_on_a_locked_part_already_in_place(work):
    """The owner's anchor may be a block part: the block is placed on it."""
    assert extract(work) == 0
    assert place(work, "--at", "60", "40") == 0
    text = (work / "ours.kicad_pcb").read_text()
    u = RB.PCB(work / "ours.kicad_pcb").by_ref()["U501"]
    fp = text[u["s"]:u["e"]].replace('(layer "F.Cu")', '(locked yes)\n\t\t(layer "F.Cu")', 1)
    (work / "ours.kicad_pcb").write_text(text[:u["s"]] + fp + text[u["e"]:])
    assert place(work, "--replace") == 0


def test_check_fails_when_a_part_moves(work, capsys):
    assert extract(work) == 0
    assert place(work, "--at", "60", "40") == 0
    text = (work / "ours.kicad_pcb").read_text()
    r = RB.PCB(work / "ours.kicad_pcb").by_ref()["R501"]
    fp = RB.footprint_moved(RB.PCB(work / "ours.kicad_pcb"), r, r["x"] + 0.2, r["y"], r["rot"])
    (work / "ours.kicad_pcb").write_text(text[:r["s"]] + fp + text[r["e"]:])
    assert RB.main(["check", str(work / "block.json"), str(work / "ours.kicad_pcb")]) == 1
    assert "R501" in capsys.readouterr().out


def test_fab_and_crowding_warnings(tmp_path, capsys):
    (tmp_path / "vendor.kicad_pcb").write_text(vendor_text(gnd_width=0.08))
    (tmp_path / "ours.kicad_pcb").write_text(ours_text(fonts=False))
    (tmp_path / "map.json").write_text(json.dumps(dict(MAP, drop_nets=["NOISE"])))
    assert extract(tmp_path) == 0
    assert place(tmp_path, "--at", "60", "40", "--fab", "jlcpcb") == 0
    out = capsys.readouterr().out
    assert "min track 0.080 mm is below jlcpcb" in out
    assert "C9" in out                                    # sits inside the pasted box
    assert (tmp_path / "ours.kicad_pcb").read_text().rstrip().endswith(")")
    RB.R.Board(text=(tmp_path / "ours.kicad_pcb").read_text())


def test_list_shows_parts_and_nets(work, capsys):
    assert RB.main(["list", str(work / "vendor.kicad_pcb"), "--box", "95", "45", "108", "55"]) == 0
    out = capsys.readouterr().out
    assert "U1" in out and "R1" in out and "J1" not in out and "NOISE" in out


def test_import_calls_kicad_cli_and_warns_when_not_ignored(tmp_path, capsys):
    """kicad-cli is replaced by a stand-in that records its arguments and writes the output board."""
    cli = tmp_path / "kicad-cli"
    cli.write_text("#!/bin/sh\necho \"$@\" > \"$(dirname \"$0\")/args.txt\"\n"
                   "while [ $# -gt 1 ]; do if [ \"$1\" = -o ]; then cp \"$(eval echo \\${$#})\" \"$2\"; fi; shift; done\n")
    cli.chmod(0o755)
    src = tmp_path / "EVM.PcbDoc"
    src.write_text(vendor_text())
    out = tmp_path / "reference" / "evm" / "evm.kicad_pcb"
    assert RB.main(["import", str(src), "-o", str(out), "--kicad-cli", str(cli)]) == 0
    args = (tmp_path / "args.txt").read_text().split()
    assert args[:2] == ["pcb", "import"] and "--format" in args and args[-1] == str(src)
    text = capsys.readouterr().out
    assert RB.sha256(src) in text
    assert out.exists() and RB.PCB(out, check_version=False).by_ref()["U1"]
