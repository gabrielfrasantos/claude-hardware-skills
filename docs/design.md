# Design: from rules library to workflow and generation

Status: agreed 2026-11-20 (design session, decisions D1–D30 below). This file is the plan the skills and tools are built
against. Change it with a new decision, not silently.

## 1. Goal

Today the plugin is a **rules library**: eight skills that say what is right. The boards that use it
([e-inverted-pendulum-hardware](https://github.com/embedded-pro/e-inverted-pendulum-hardware),
[e-foc-hardware](https://github.com/embedded-pro/e-foc-hardware)) carry the rest themselves: requirements, decisions,
phase gates, a schematic generator, about 10k lines of PCB scripts, reviewer agents and exporters, much of it copied
between repos. The goal is all three layers, in order:

1. **Rules** — what is right (the existing skills, extended).
2. **Workflow** — a repeatable path from requirements to fab files, with gates.
3. **Generation** — tools that capture the schematic, assign pins, place, pour and route the simple parts.

Measured, not felt: every step is scored by the evals in `evals/` (D5, D30).

## 2. Scope

| | Decision |
|---|---|
| D3 Users | Gabriel and embedded-pro first. Public later. |
| D4 Tools | KiCad 10 and later only. No KiCad 8/9 support code. Fabs as open profiles (`profiles/*.json`). |
| D6 Where code lives | Scripts stay in each skill's `scripts/` for now. Target: one shared package (`hwkit`). No claude.ai single-skill zip compatibility. |
| D13 Shared code | Skills may import from `pcb-design-rules/scripts` (parser, geometry, `kicad-cli` calls). It is the core that becomes `hwkit`. Nothing else is shared across skill folders. |
| D22 KiCad engine | Read and write `.kicad_pcb` / `.kicad_sch` as S-expressions; `kicad-cli` for DRC, ERC, zone fill and exports. No new `pcbnew` (SWIG) code: it is deprecated since KiCad 9 and goes away. Revisit the IPC API once KiCad 11 runs it headless. Ported pendulum scripts are rewritten to this, not copied. |
| D28 Dependencies | External packages are allowed (numpy, scipy, ...). |
| D29 Versioning | Tagged releases (release-please). Board repos' CI pins a tag; interactive sessions use `main`. |

## 3. Skills

| Skill | State | Content |
|---|---|---|
| `pcb-design-rules` | extend | D11: teardrops (`apply` sets KiCad 10 teardrops on vias and PTH/SMD pads; `check` fails where they are missing), pour checks (necks below minimum width, islands, unstitched ground pieces, reference-plane cuts under signal classes), stack-up templates per layer count (4L: SIG / solid GND / PWR / SIG). KiCad 10+ only. |
| `pcb-copper` | new | D9, D21: a standard net-class set declared on the schematic's net-class directive labels, **the current in the class name** (`PWR_4A`, D9 as built: KiCad resolves labels to nets in the project, custom label fields are not carried); widths at ΔT 10 °C per layer's copper from IPC-2221's external fit, used for inner layers too (IPC-2152 found internal and external conductors close in temperature rise; IPC-2152 itself is charts); nets at or above the width of 3 A on 1 oz become required pours; a net left in Default is an error. Kelvin `SENSE` pairs with a net-tie check: later. D17: fan-out, stitching, power copper, pours, simple routes and tidy are scripted; Claude or the router does short nets; the owner routes the critical ones. |
| `pcb-placement` | new | D7, D15, D25: the owner places and locks the anchors, which never move. Claude places the rest: an optimizer (ratsnest length and crossings under courtyard, keep-out and assembly-spacing limits), then Claude refines. Optional `propose` mode for anchors (report only). A placement gate runs before any routing; report-only until the evals set its limits (no worse than the human baseline + 10 % on ratsnest and estimated vias), then it fails. Includes pin assignment (D8, D16). |
| `schematic-capture` | new | D10: schgen (Python design files → `.kicad_sch`) generalised from pendulum/e-psu: titled block boxes, function nets with pin TBD, `expected.json` netlist check and equivalence check. Hand-drawn schematics get the checks only. D19: KiCad standard libraries first; missing parts from LCSC/EasyEDA (`easyeda2kicad`) with a footprint-vs-LCSC-package check; hand transcription only as a fallback. D9: net-class directives with current. |
| `reference-block` | new | D18: import a vendor layout (KiCad 10 opens Altium PcbDoc), select a region, map references and nets to ours, paste it with its copper and zones. Vendor files stay gitignored. Says when copying beats designing (RF, NFC, fast power loops). |
| `hardware-project` | new | D12: project scaffold; `requirements.md` traced to firmware `REQ-*`; `decisions.md` (D-xxx); `plan.md` with phase gates signed by the owner; `PROJECT_CONTEXT.md`; a CLAUDE.md skill table; a generic reviewer agent with a per-board rubric; the export package (review, JLCPCB, release, visual diff); BOM and JLC stock; datasheet fetch. Replaces the scripts copied between board repos. |
| `power-circuit-design` | new | D24: the schematic side of power stages (gate drivers, bootstrap, dead time, bucks, reverse polarity, hot plug, inrush, TVS, shunt amplifiers), distilled from `foc-hardware-design-guide.md` and `robot-hardware-design-guide.md`, every number sourced. The board guides shrink to what is board-specific. |

Existing skills (`power-pcb-layout`, `mcu-circuit-design`, `analog-circuit-design`, `circuit-simulation`,
`high-speed-digital-layout`, `interface-layout`, `rf-layout`) stay as the rules layer.

## 4. Pin assignment and placement loop (D8, D14, D16)

Hardware is hard to change and firmware is easy, so **hardware picks the pins**, within what the firmware needs
(a PWM net gets a PWM-capable pin, an encoder gets a timer with encoder mode, ...).

1. The schematic is drawn with MCU connections as **function nets** (`MOTOR_PWM_A1`), pin numbers TBD.
2. The owner places the anchors; rough placement of the clusters (one schematic sheet = one cluster) around the MCU.
3. Pins are assigned from the package side that faces each cluster, within each function's capabilities
   (pin data: ST from `STM32_open_pin_data` via KiCad's symbols; other families extracted once from the datasheet).
4. The pin map is written as a plain text file for the firmware and back into the schgen design; the schematic is
   rebuilt and the netlist checked. The pin map freezes here, with a decision logged.
5. Final placement, then the placement gate.

## 5. Evals (D5, D20, D30)

- **The harness is generic and lives here** (`evals/`); **cases live in each board repo** (`<board-repo>/evals/cases/`),
  with the anchors and the pinned commit of that board. Fixtures are built on demand from the board repo's git history,
  so no board files are copied into any repo.
- `evals/run.py <board-repo>/evals` runs each case through headless `claude -p` on a fresh copy of its fixture,
  **with** and **without** the plugin, 3 runs each (placement and routing are not deterministic), and scores each
  result. Summaries go to the board repo's `evals/results/`.
- Scores are computed from the files (`evals/metrics.py`), never judged by the model: validity (anchors moved, parts
  off the board, courtyard overlaps, copper added), ratsnest length, ratsnest crossings (a via estimate), decoupling
  distance; later the gate, via count, teardrop and pour checks.
- The baseline is the human placement: the source board as its owner placed it at the pinned commit.
- First case: pendulum placement, with its anchors taken from its decisions (the board locks nothing). e-foc's case
  comes with its migration branch (D27). Later: a schematic case with known defects reintroduced, and a
  pin-assignment case. Review tasks are graded by hand.
- Run by hand before each release tag, not in CI (cost).

## 6. Build order (D26)

1. Eval harness (generic, here) and the pendulum placement case (in its repo). Done.
2. Extend `pcb-design-rules` (teardrops, pours, KiCad 10+ only). Done.
3. `pcb-copper` net classes. Done; the scripted copper of D17 follows after placement.
4. `pcb-placement` with its gate and optimizer (done: beats the owner's pendulum placement on ratsnest, crossings and decoupling distance, but not on intent the board does not encode, so the owner's review stays), then pin assignment (done: `pins.py`, Hungarian assignment over peripheral instances; the firmware's needs as text, the pin map as text).
5. `hardware-project`, `schematic-capture`, `reference-block`, `power-circuit-design`.

## 7. Board repos (D27)

- **e-inverted-pendulum-hardware** is the first consumer. Its copied scripts are deleted as the plugin takes each one
  over.
- **e-foc-hardware** stays frozen as the human baseline for the evals. A migration branch comes later.
