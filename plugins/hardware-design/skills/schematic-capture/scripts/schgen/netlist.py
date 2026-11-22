"""KiCad netlists: export with kicad-cli, read, and compare (two schematics, or a schematic with schgen's intent).

compare()           same parts, fields and pin-to-net partition, net names included: use it after a drawing-only
                    change to prove the circuit did not change (reference: a .net file or a git revision).
compare_expected()  KiCad's nets against the connectivity schgen recorded (expected.json): same nets, same names,
                    no extra pins.
Part of the schematic-capture skill.
"""

import io
import pathlib
import shutil
import subprocess
import tarfile

from sexpr import find, find_all, parse

IGNORED_FIELDS = {"Footprint", "Datasheet", "Description"}
FLAGS = {"dnp", "exclude_from_bom", "exclude_from_board"}


def kicad_cli():
    cli = shutil.which("kicad-cli")
    if not cli:
        raise SystemExit("kicad-cli (KiCad 10) is needed for netlists: install KiCad or put kicad-cli on PATH")
    return cli


def export_netlist(schematic, out):
    subprocess.run([kicad_cli(), "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(schematic)],
                   check=True, capture_output=True)
    return out


def netlist_from_rev(repo_root, schematic, rev, workdir):
    """Export the netlist of `schematic` (a path inside repo_root) as it was at git revision `rev`."""
    rel = pathlib.Path(schematic).resolve().relative_to(pathlib.Path(repo_root).resolve())
    folder = rel.parent.as_posix()
    result = subprocess.run(["git", "-C", str(repo_root), "archive", rev, folder], capture_output=True)
    if result.returncode != 0:
        raise SystemExit(f"no {folder} at {rev}: {result.stderr.decode().strip()}")
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(workdir, filter="data")
    return export_netlist(pathlib.Path(workdir) / rel, pathlib.Path(workdir) / "reference.net")


def read(path):
    tree = parse(pathlib.Path(path).read_text(encoding="utf-8"))
    parts = {}
    for comp in find_all(find(tree, "components"), "comp"):
        ref = str(find(comp, "ref")[1])
        fields = {}
        node = find(comp, "fields")
        for field in find_all(node, "field") if node else []:
            name = str(find(field, "name")[1])
            if name not in IGNORED_FIELDS:
                fields[name] = str(field[2]) if len(field) > 2 else ""
        flags = {str(find(p, "name")[1]) for p in find_all(comp, "property")} & FLAGS
        lib = find(comp, "libsource")
        footprint = find(comp, "footprint")
        parts[ref] = {"value": str(find(comp, "value")[1]), "footprint": str(footprint[1]) if footprint else "",
                      "fields": fields, "flags": sorted(flags),
                      "symbol": f"{find(lib, 'lib')[1]}:{find(lib, 'part')[1]}"}
    nets = {}
    for net in find_all(find(tree, "nets"), "net"):
        name = str(find(net, "name")[1])
        nodes = frozenset((str(find(n, "ref")[1]), str(find(n, "pin")[1])) for n in find_all(net, "node"))
        nets[name] = nodes
    return parts, nets


def compare(reference, current, allow_renames=False):
    (ref_parts, ref_nets), (cur_parts, cur_nets) = reference, current
    problems, renames = [], []
    for ref in sorted(set(ref_parts) | set(cur_parts)):
        if ref not in cur_parts:
            problems.append(f"{ref}: missing")
            continue
        if ref not in ref_parts:
            problems.append(f"{ref}: added")
            continue
        for key in ("value", "footprint", "symbol", "flags", "fields"):
            if ref_parts[ref][key] != cur_parts[ref][key]:
                problems.append(f"{ref}: {key} {ref_parts[ref][key]!r} -> {cur_parts[ref][key]!r}")

    def connected(nets):
        return {name: nodes for name, nodes in nets.items() if not name.startswith("unconnected-")}

    ref_conn, cur_conn = connected(ref_nets), connected(cur_nets)
    by_nodes = {nodes: name for name, nodes in cur_conn.items()}
    matched = set()
    for name, nodes in sorted(ref_conn.items()):
        other = by_nodes.get(nodes)
        if other is None:
            node_net = {n: nm for nm, ns in cur_conn.items() for n in ns}
            split = sorted({node_net.get(n, "unconnected") for n in nodes})
            problems.append(f"net {name}: {len(nodes)} pins now on {split}")
            continue
        matched.add(other)
        if other != name:
            renames.append(f"net {name} -> {other}")
    for name in sorted(set(cur_conn) - matched):
        problems.append(f"net {name}: new connection {sorted(cur_conn[name])}")
    if not allow_renames:
        problems += renames
    return problems, renames


def compare_expected(expected, nets):
    """expected: {net name: {(ref, pin)}} from schgen; nets: from read(). Problems as text lines."""
    node_net = {node: name for name, nodes in nets.items() for node in nodes}
    problems = []
    for name, nodes in sorted(expected.items()):
        got = {node_net.get(node) for node in nodes}
        if None in got:
            problems.append(f"{name}: pins missing from the netlist {sorted(n for n in nodes if n not in node_net)}")
            got.discard(None)
        if len(got) > 1:
            problems.append(f"{name}: split across {sorted(got)}")
        for kicad_name in got:
            if kicad_name != name:
                problems.append(f"{name}: KiCad names it {kicad_name}")
            extra = {n for n in nets[kicad_name] - nodes if not n[0].startswith("#")}
            if extra:
                problems.append(f"{name}: unexpected pins {sorted(extra)}")
    return problems
