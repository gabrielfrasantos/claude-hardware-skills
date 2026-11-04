---
name: pcb-design-rules
description: Set a KiCad board's design rules from the PCB fab's published capabilities (JLCPCB, Seeed Studio, or the strictest of several) and gate the routed layout on DRC plus geometry quality (45-degree discipline, jogs, acute corners, segments and vias per connection), with a Python script that also runs in CI.
---

# PCB design rules and layout quality gate (KiCad 8–10)

Use this skill when you set up a board's rules for a fab, before routing, and when you check a routed board before review or ordering. It has three layers:

| Layer | What sets it | What it catches |
|---|---|---|
| KiCad defaults | a new project | generic values; several checks are **off** (minimum clearance 0, mask web 0, no PTH annular or pad-hole spacing rule, no angle rule) |
| **Fab profile** | `pcb_rules.py apply` | what the fab can build: track/space, vias, drills, annular rings, hole spacing, edge, mask, silk |
| **Quality gate** | `pcb_rules.py check` | what DRC passes but a reviewer rejects: off-grid angles, staircase jogs, acute corners, too many segments or vias per connection, detours |

DRC-clean is the floor. A board is done when `check` passes too.

The script is `scripts/pcb_rules.py` (Python 3 standard library only). Fab data lives in `profiles/<fab>.json`, each with source URLs and the date it was checked. If `scripts/` is not next to this file (e.g., the skill was installed as a single SKILL.md), get both folders from github.com/gabrielfrasantos/claude-hardware-skills, path `plugins/hardware-design/skills/pcb-design-rules/`.

## 1. Workflow with the user

The user places and locks the main parts and draws the outline. You set the rules, route and check.

1. **User:** in KiCad, *Tools → Update PCB from Schematic*, place and **lock** the parts that set the layout (connectors, power stage, heatsink parts, MCU, mounting holes), draw `Edge.Cuts`, save.
   - If the board was routed before, delete the old tracks and vias first (*Edit → Global Deletions → Tracks, Vias*). Keep zones only if their outlines still fit.
2. **You:** apply the fab rules and net-class design values:
   ```bash
   python3 scripts/pcb_rules.py apply hardware/board/board.kicad_pro --fab jlcpcb --netclasses
   # or the strictest of several fabs, so the board can go to either:
   python3 scripts/pcb_rules.py apply board.kicad_pro --fab jlcpcb,seeed --netclasses
   ```
   `apply` reads the copper-layer count from the board. It ends with `loads OK` only after KiCad has actually parsed the rules file (see §4).
3. **You:** route in phases (power first, then sensitive analog, then digital), following the domain skill (`power-pcb-layout`, `interface-layout`, `high-speed-digital-layout`, `rf-layout`). Run `check --allow-unrouted` after each phase and fix what it reports before moving on.
4. **You:** final `check` with no flags; it must exit 0. Attach the report to the PR or hand it to the user.
5. **Fab order:** re-open the profile's source URLs. Fab capabilities change, and the profile records the date it was checked.

## 2. The script

```bash
python3 scripts/pcb_rules.py profiles                        # list fab profiles
python3 scripts/pcb_rules.py apply <board.kicad_pro|.kicad_pcb> --fab jlcpcb[,seeed] [--layers N] [--netclasses]
python3 scripts/pcb_rules.py check <board.kicad_pcb> [--allow-unrouted] [--no-drc] [--gate NAME=LIMIT] \
        [--report report.md] [--json metrics.json]
python3 scripts/test_pcb_rules.py                            # self-test, no KiCad needed
```
`kicad-cli` (KiCad 8+) is found via `--kicad-cli`, `$KICAD_CLI` or `PATH`. Geometry checks parse the `.kicad_pcb` directly (KiCad 7–10 formats) and work with `--no-drc` and no KiCad installed.

### 2.1 `apply` writes
- **Board Setup → Constraints** (`.kicad_pro`): the fab minimums for clearance, track, via annular/diameter, drill, hole-to-hole, hole clearance, copper-to-edge, silk clearance, text height and thickness. With several fabs it takes the **largest** minimum of each.
- **Solder-mask minimum web** in the board's setup (it is a board property, not a project one).
- **`<project>.kicad_dru`**, a managed block between `# BEGIN pcb_rules` and `# END pcb_rules` markers, placed **first** in the file so rules you add after it win. It holds the fab rules that Board Setup has no field for:
  - PTH-pad annular ring;
  - pad hole to pad hole, different nets only (same-net thermal-via arrays inside a footprint are exempt);
  - PTH-pad hole to copper;
  - NPTH minimum drill;
  - inner-layer track width, where the fab has one (Seeed 4+ layers);
  - SMD pad-to-pad clearance, **only between net classes whose clearance is below it** (see §4);
  - `track_angle (min 90)`: no acute track corners.
- **`--netclasses`**: raises the Default net class to the profile's design values. It only raises, never lowers. Other classes (power, HV, USB) stay yours to set from the domain skill.
- Re-run `apply` after changing net classes or the layer count: the pad-to-pad rule depends on both.

### 2.2 `check` gates

| Gate | Default | Kind | Meaning |
|---|---|---|---|
| DRC errors + schematic-parity errors + unconnected | 0 | hard | KiCad DRC with zones refilled; `--allow-unrouted` drops unconnected items while routing is in progress |
| `any_angle_segments` | 0 | hard | segments (≥ 0.05 mm) not within ±0.5° of 0/45/90/135° |
| `acute_corners` | 0 | hard | track ends meeting off a pad or via at < 90° (acid traps, doubled-back tracks) |
| `jogs` | 0 | hard | zero-length segments, and interior segments < 0.25 mm between **parallel** runs (sideways steps). A short 45° miter between perpendicular runs is not a jog |
| `short_segment_pct` | 10 % | soft | interior segments < 0.5 mm |
| `segments_per_connection_p90` | 8 | soft | segments per pad-to-pad connection, 90th percentile over nets |
| `vias_per_connection_max` | 4 | soft | worst net |
| `detour_p90` | 1.6 | soft | routed length / Manhattan minimum spanning tree of the net's pads; nets with zones are skipped |

The report also lists examples with coordinates, the worst nets, and the H/V/other split of routed length per copper layer (layer-direction discipline). Exit status is 1 when a hard gate fails.

Override a gate only for a stated reason, for example a footprint rotated 30° whose pads force off-grid escapes: `--gate any_angle_segments=4`. Write the reason in the PR.

### 2.3 CI
Run `check` on pull requests next to ERC/DRC. KiCad's PPA has per-version archives (`ppa:kicad/kicad-10.0-releases`, as used by embedded-pro/kicad-bot):
```yaml
- run: |
    sudo add-apt-repository --yes ppa:kicad/kicad-10.0-releases
    sudo apt-get update && sudo apt-get install --yes --no-install-recommends kicad-cli || sudo apt-get install --yes kicad
- uses: actions/checkout@<sha>   # pin the skills repo to a commit, like any action
  with: {repository: gabrielfrasantos/claude-hardware-skills, ref: <sha>, path: .hw-skills}
- run: python3 .hw-skills/plugins/hardware-design/skills/pcb-design-rules/scripts/pcb_rules.py check
       hardware/board/board.kicad_pcb --report pcb-quality.md
```
Expect red CI while routing is in progress: unconnected items and quality gates fail until the layout is finished. Use `--allow-unrouted` on work-in-progress branches if that is what the team wants.

## 3. Fab numbers (mm)

Minimums are the published capability. Design values are what `--netclasses` writes: inside the cheapest tier of both fabs, with margin.

| Rule | JLCPCB 2 L | JLCPCB 4+ L | Seeed | KiCad 10 default | Design value |
|---|---|---|---|---|---|
| Track / space | 0.10 / 0.10 | 0.09 / 0.09 | 0.1016 / 0.1016 (inner 0.15 on 4 L) | 0.2 / **0** | 0.15 / 0.15 |
| Via drill / diameter | 0.15 / 0.25 | 0.15 / 0.25 | 0.20 / 0.40 | 0.3 / 0.5 | 0.30 / 0.60 |
| Via annular ring | 0.05 | 0.05 | 0.10 | 0.1 | 0.15 *(derived)* |
| PTH-pad annular ring | 0.18 | 0.15 | 0.152 | none | — |
| Min drill / NPTH drill | 0.15 / 0.50 | 0.15 / 0.50 | 0.20 / 0.20 | 0.3 / — | — |
| Hole to hole / pad hole to pad hole | 0.20 / 0.45 | 0.20 / 0.45 | 0.30 / 0.45 | 0.25 / — | — |
| Hole to copper / PTH pad to track | 0.20 / 0.28 | 0.20 / 0.28 | 0.3048 / 0.3048 | 0.25 / — | — / 0.35 |
| SMD pad to pad | 0.15 | 0.15 | 0.1016 | — | — |
| Copper to edge | 0.20 | 0.20 | 0.30 | 0.5 | 0.50 *(derived)* |
| Solder-mask web | 0.10 | 0.10 | 0.10 option, default 0.32–0.35 | **0** | — |
| Silk line / text height / to pad | 0.15 / 1.0 / 0.15 | same | 0.1016 / 0.5842 / 0.1524 | 0.08 / 0.8 / 0 | — |

Sources and check dates are in `profiles/*.json`.

### 3.1 Where sources disagree
| Topic | Disagreement | Use |
|---|---|---|
| Via size | JLCPCB builds 0.15/0.25 mm but charges extra below a 0.30 mm hole (and for 0.20–0.25 mm holes below a 0.45 mm diameter); Seeed's standard minimum is 0.20/0.40 | 0.30/0.60 for general vias; smaller only under fine-pitch parts, and check the price |
| NPTH drill | JLCPCB 0.50, Seeed 0.20 | the profile you order from; 0.50 when portable |
| Silk text | JLCPCB 1.0 mm height, Seeed 0.58 mm | 1.0 mm (or 0.8 mm with the JLC warning accepted knowingly) |
| Mask web | both 0.10 mm, but Seeed only as an option; its default dam is 0.32 mm (green) / 0.35 mm (other colours) | 0.10 mm with LDI at JLCPCB (1:1 mask since June 2025); with Seeed, select the option or expect merged openings on fine pitch |
| Copper to edge | JLCPCB 0.20, Seeed 0.30, KiCad default 0.5 | 0.5 mm for routed edges; more near V-score |
| Inner copper | both default to 0.5 oz inner | state 1 oz on the order for inner power planes; it changes the stackup |

## 4. KiCad rule-engine facts (verified on KiCad 10.0.6)

- **A rules file that does not parse is silently ignored.** DRC runs with no custom rules and reports nothing. `apply` therefore runs DRC on a temporary copy with a canary rule and fails unless the canary fires.
  - `(min 90deg)` in `track_angle` makes the whole file invalid. Write `(min 90)`.
  - `track_segment_length` is not in 10.0.6 (it is on KiCad's development branch). Any file containing it is dropped. `check` measures segment lengths instead.
- `track_angle` measures the angle between connected segments: a straight run is 180, a 45° bend 135, a right angle 90. `(min 90)` therefore flags only acute corners. It cannot enforce 45° discipline; `check` does.
- **A custom-rule constraint replaces the net-class value and the Board Setup minimum, even when it is smaller.** Measured: with a 0.3 mm board minimum, a custom pad-to-pad `(min 0.05mm)` removed every board-minimum clearance violation between pads. The KiCad manual says Constraints minimums cannot be overridden by more specific rules; on 10.0.6 they were. So never write a blanket `clearance` rule: it lowers your HV and power classes too. Condition every clearance rule on the classes it is meant for.
- **When several rules match, the later one in the file wins.** That is why the managed block goes first.
- `A.NetClass == 'X'` compares the net's effective class name. A net matching several class patterns has a composite effective class, so a condition on one class name may not match it.
- DRC truncates the violation list per type (a few hundred), so counts above that are lower bounds. Fix and re-run.
- Schematic parity reports nets whose sheet names contain `/`, since KiCad 10 escapes it. Avoid `/` in sheet names, then run *Update PCB from Schematic*.

## 5. Routing so the gate passes

- Use the interactive router with *Free angle mode* off, *Optimize pad connections* and *Remove redundant tracks* on. Do not draw free-angle tracks.
- Set the grid to the pin pitch family (0.05 mm for metric parts, 0.0254/0.127 mm for inch parts) and route on it. Most jogs come from tracks ending off-grid on fine-pitch pads.
- Give each outer layer a preferred direction (for example F.Cu mostly horizontal, B.Cu mostly vertical) and change layer, not direction, for long crossings.
- After each phase, run *Tools → Cleanup Tracks & Vias* (merge co-linear tracks, delete redundant vias, delete tracks unconnected at one end), then `check`.
- Generated or scripted routing must emit only 0/45/90/135° segments and merge collinear ones before writing. Check it with `check --no-drc` before showing the user.

## 6. Pitfalls

- Ordering at the absolute minimum: it is possible, not free. Minimum vias and track/space trigger surcharges or lower yield. Route at the design values; go to the minimum only locally, under a fine-pitch part.
- Footprint libraries ignore your fab: thermal-via arrays at 0.2 mm drill, PTH annular rings below 0.15 mm, mask webs below 0.1 mm. The `apply` rules find them; fix the footprint, not the rule.
- Net-class clearances for mains, HV or isolation come from the safety standard (IPC-2221, IEC 62368-1), never from the fab profile. The fab number is only the floor.
- Copper weight changes the minimums: thicker copper needs wider track/space (Seeed: 2 oz needs 10/10 mil, 3 oz 15/15 mil). Re-check the profile when you order heavy copper.
- `--netclasses` only touches Default; power and HV classes need explicit values from the domain skill.
- Run `check` on the saved board. DRC in a stale KiCad process can use cached project settings.

## 7. Checklist

- [ ] Fab chosen and `apply` run with the right `--fab` and layer count; output ends with `loads OK`.
- [ ] Net classes set: Default from `--netclasses`, power/HV/USB from the domain skills.
- [ ] Profile sources re-checked if the profile date is more than a few months old.
- [ ] Every routing phase followed by Cleanup Tracks & Vias and `check --allow-unrouted`.
- [ ] Final `check` exits 0: DRC and schematic parity clean, no unconnected items, hard geometry gates at 0.
- [ ] Soft-gate warnings explained or fixed; overrides justified in the PR.
- [ ] Report (`--report`) attached to the PR or sent to the user.

## 8. References

- JLCPCB, *PCB Manufacturing & Assembly Capabilities*: jlcpcb.com/capabilities/pcb-capabilities, and *Impedance calculation / stackups*: jlcpcb.com/impedance (checked 2026-11-04).
- Seeed Studio, *Fusion PCB Specification*: support.seeed.cc/portal/en/kb/articles/fusion-pcb-specification (checked 2026-11-04).
- KiCad 10 manual, *PCB Editor → Board Setup → Constraints* and *Custom design rules*: docs.kicad.org/10.0/en/pcbnew/pcbnew.html.
- IPC-2221B, *Generic Standard on Printed Board Design* (electrical clearance, Table 6-1).
- Measurements in §4: KiCad 10.0.6 `kicad-cli pcb drc` on the e-psu board and stripped copies of it, 2026-11-04.
