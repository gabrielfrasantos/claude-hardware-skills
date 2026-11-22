# Design: from rules library to workflow and generation

Status: agreed 2026-11-20 (design session, decisions D1–D30 below; D31–D36 since, §8; what is missing, §9). This file is the plan the skills and tools are built
against. Change it with a new decision, not silently.

## 1. Goal

Today the plugin is a **rules library**: eight skills that say what is right. The boards that use it
(board A, a battery-powered robot controller with two H-bridges, and board B, a 50 V three-phase motor driver;
board C, a power supply, came before them) carry the rest themselves: requirements, decisions,
phase gates, a schematic generator, about 10k lines of PCB scripts, reviewer agents and exporters, much of it copied
between repos. The goal is all three layers, in order:

1. **Rules** — what is right (the existing skills, extended).
2. **Workflow** — a repeatable path from requirements to fab files, with gates.
3. **Generation** — tools that capture the schematic, assign pins, place, pour and route the simple parts.

Measured, not felt: every step is scored by the evals in `evals/` (D5, D30).

## 2. Scope

| | Decision |
|---|---|
| D3 Users | The owner's boards first; public from v0.1. |
| D4 Tools | KiCad 10 and later only. No KiCad 8/9 support code. Fabs as open profiles (`profiles/*.json`). |
| D6 Where code lives | Scripts stay in each skill's `scripts/` for now. Target: one shared package (`hwkit`). No claude.ai single-skill zip compatibility. |
| D13 Shared code | Skills may import from `pcb-design-rules/scripts` (parser, geometry, `kicad-cli` calls). It is the core that becomes `hwkit`. Nothing else is shared across skill folders. |
| D22 KiCad engine | Read and write `.kicad_pcb` / `.kicad_sch` as S-expressions; `kicad-cli` for DRC, ERC, zone fill and exports. No new `pcbnew` (SWIG) code: it is deprecated since KiCad 9 and goes away. Revisit the IPC API once KiCad 11 runs it headless. Ported board-repo scripts are rewritten to this, not copied. |
| D28 Dependencies | External packages are allowed (numpy, scipy, ...). |
| D29 Versioning | Tagged releases (release-please). Board repos' CI pins a tag; interactive sessions use `main`. As built: `.github/workflows/release.yml` writes the version into the plugin and marketplace manifests; MIT licence; CI runs the tests, a lint and the plugin validator. |

## 3. Skills

| Skill | State | Content |
|---|---|---|
| `pcb-design-rules` | extend | D11: teardrops (`apply` sets KiCad 10 teardrops on vias and PTH/SMD pads; `check` fails where they are missing), pour checks (necks below minimum width, islands, unstitched ground pieces, reference-plane cuts under signal classes), stack-up templates per layer count (4L: SIG / solid GND / PWR / SIG). KiCad 10+ only. |
| `pcb-copper` | new | D9, D21: a standard net-class set declared on the schematic's net-class directive labels, **the current in the class name** (`PWR_4A`, D9 as built: KiCad resolves labels to nets in the project, custom label fields are not carried); widths at ΔT 10 °C per layer's copper from IPC-2221's external fit, used for inner layers too (IPC-2152 found internal and external conductors close in temperature rise; IPC-2152 itself is charts); nets at or above the width of 3 A on 1 oz become required pours; a net left in Default is an error. Kelvin `SENSE` pairs with a net-tie check: later. D17: fan-out, stitching, power copper, pours, simple routes and tidy are scripted; Claude or the router does short nets; the owner routes the critical ones. |
| `pcb-placement` | new | D7, D15, D25: the owner places and locks the anchors, which never move. Claude places the rest: an optimizer (ratsnest length and crossings under courtyard, keep-out and assembly-spacing limits), then Claude refines. Optional `propose` mode for anchors (report only). A placement gate runs before any routing; report-only until the evals set its limits (no worse than the human baseline + 10 % on ratsnest and estimated vias), then it fails. Includes pin assignment (D8, D16). |
| `schematic-capture` | new | D10: schgen (Python design files → `.kicad_sch`) generalised from boards A and C: titled block boxes, function nets with pin TBD, `expected.json` netlist check and equivalence check. Hand-drawn schematics get the checks only. D19: KiCad standard libraries first; missing parts from LCSC/EasyEDA (`easyeda2kicad`) with a footprint-vs-LCSC-package check; hand transcription only as a fallback. D9: net-class directives with current. |
| `reference-block` | new | D18: import a vendor layout (KiCad 10 opens Altium PcbDoc), select a region, map references and nets to ours, paste it with its copper and zones. Vendor files stay gitignored. Says when copying beats designing (RF, NFC, fast power loops). |
| `hardware-project` | new | D12: project scaffold; `requirements.md` traced to firmware `REQ-*`; `decisions.md` (D-xxx); `plan.md` with phase gates signed by the owner; `PROJECT_CONTEXT.md`; a CLAUDE.md skill table; a generic reviewer agent with a per-board rubric; the export package (review, JLCPCB, release, visual diff); BOM and JLC stock; datasheet fetch. Replaces the scripts copied between board repos. |
| `power-circuit-design` | new | D24: the schematic side of power stages (gate drivers, bootstrap, dead time, bucks, reverse polarity, hot plug, inrush, TVS, shunt amplifiers), distilled from the design guides of boards A and B, every number sourced. The board guides shrink to what is board-specific. |

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
- First case: board A placement, with its anchors taken from its decisions (the board locks nothing). Board B's case
  comes with its migration branch (D27). Later: a schematic case with known defects reintroduced, and a
  pin-assignment case. Review tasks are graded by hand.
- Run by hand before each release tag, not in CI (cost).

## 6. Build order (D26)

1. Eval harness (generic, here) and the board A placement case (in its repo). Done.
2. Extend `pcb-design-rules` (teardrops, pours, KiCad 10+ only). Done.
3. `pcb-copper` net classes. Done; the scripted copper of D17 follows after placement.
4. `pcb-placement` with its gate and optimizer (done: beats the owner's placement of board A on ratsnest, crossings and decoupling distance, but not on intent the board does not encode, so the owner's review stays), then pin assignment (done: `pins.py`, Hungarian assignment over peripheral instances; the firmware's needs as text, the pin map as text).
5. `schematic-capture` (done: schgen ported, byte-identical on board A; pin-map and net-class helpers; library check), then `hardware-project` (done: scaffold, `trace.py`, the board repos' export scripts shared), `reference-block` (done: `refblock.py` import/list/extract/place/check; round trip byte-identical on board A's TI stage; Gerber-only sources left to the board's own reader), `power-circuit-design` (done: distilled from the board B and board A guides, every number sourced or marked).

## 7. Board repos (D27)

- **Board A** is the first consumer. Its copied scripts are deleted as the plugin takes each one
  over.
- **Board B** stays frozen as the human baseline for the evals. A migration branch comes later.

## 8. Decisions after the best-practices audit (2026-11-20)

The audit (`docs/research/best-practices-audit.md`) checked the skills against primary sources. The owner decided:

| | Decision |
|---|---|
| D31 House style | The geometry gates for octilinear angles, 90° corners, tees and jogs stay **hard**, labelled as the owner's house style, not as IPC or fab rules (none sets a corner angle). Acute angles stay the manufacturing rule. New, soft: **most tracks horizontal or vertical, diagonals short** (`diagonal_length_pct` ≤ 20 %, `long_diagonals` > 2 mm), an instruction more than a measurement. |
| D32 Stack-up | The 4-layer default becomes **SIG / GND / GND / SIG** (ADI's preferred option; no signal over a power plane, TI SPRAAR7J §2.4). SIG / GND / PWR / SIG stays as an alternative with a stated reason. Existing boards keep their recorded roles. |
| D33 Teardrops | Hard on vias and plated-hole pads, soft on SMD pads; off by default for the `DIFF_*` and `RF_*` classes. |
| D34 Standards | Clearance by voltage takes the larger of IPC-2221C Table 6-1 B2 and A7 (pads are terminations). The current fit is cited as the historical IPC-2221 chart fit, superseded by IPC-2152, one fit for every layer. Vias at 18 µm plating. |
| D35 Vendor licences | Data derived from TI design files stays in the gitignored `reference/` by default; ST's OPLA allows distribution for ST-based boards. Board A's committed TI-derived copper is the owner's decision. |
| D36 Review | Reviewing is a skill of its own (`design-review`): `review.py` runs every scripted check on any KiCad 10 project into one findings file, the schematic checks run on the netlist (board + schematic symbols offline, or KiCad's netlist), and a plugin-level `board-reviewer` agent triages the findings and reviews against the datasheets from the netlist, not from PDF pictures. Review quality is measured by seeding defects into real boards (`evals/review_defects.py`). |

Built from the audit's gaps, in a separate PR: JLCPCB package-pair assembly spacing, edge keep-outs, fiducials and orientation in the placement gate; a footprint-vs-LCSC-package check; BOM lifecycle in `jlc_stock.py`.

## 9. What is missing (2026-11-20, after v0.1 scope)

Every skill in §3 is built, and 123 tests pass on synthetic KiCad 10 files and parsed real boards. Three things are
still missing before the plugin can be called done:

1. **It has never run against KiCad itself.** The environment it was built in has no KiCad 10.
2. **It has never been measured** against the goal in §1 ("measured, not felt").
3. **Part of goal 3 (generation, D17) isn't built.**

The phases below close them in order. Each ends at a gate the owner signs off, as for a board.

### Phase A: housekeeping (owner, ~10 min)

| # | Item | Why | Done when |
|---|---|---|---|
| A1 | *Settings → Actions → General → Workflow permissions*: allow GitHub Actions to create pull requests | release-please fails without it (run on 5d3e907: "not permitted to create or approve pull requests") | the release PR for v0.1.0 exists |
| A2 | Merge the release PR | D29: CI pins tags; the plugin version is set from them | tag `v0.1.0`, CHANGELOG on `main` |
| A3 | Repo description and topics (About panel) | the API proxy refuses settings writes | description no longer reads "harware" |

### Phase B: KiCad 10 validation (Claude prepares, the owner runs on a machine with KiCad 10)

Every script that writes a KiCad file has only been checked by re-parsing its output. A kit
(`evals/validate_kicad.py`, #14) runs each step on a **copy** of board A, then `kicad-cli` loads, DRCs
and ERCs every result and collects one report. If the owner links this conversation to the computer (Claude
desktop app, "Add folder"), Claude can run it there.

| # | Step | Pass criterion |
|---|---|---|
| B1 | `pcb_rules.py apply` | prints `loads OK`; KiCad opens the board; the teardrop flags show in *Board Setup*; *Edit Teardrops* draws them |
| B2 | `pcb_rules.py check` with KiCad (DRC, fab floor, `--save-board` refill) | runs; counts match the GUI's DRC on the same file |
| B3 | `netclasses.py apply` | the classes appear in *Board Setup → Net Classes* with the computed widths |
| B4 | `place.py optimize`, `pins.py assign` | the board opens, parts where the report says; the pin map rebuilds the schematic (`schgen`) |
| B5 | `schgen.py build / check / equivalence` | ERC clean; `check` passes; byte-identical rebuild |
| B6 | `refblock.py import` (TI PcbDoc in board A's `reference/`), `extract`, `place` | the import opens; the pasted board opens with the group; DRC shows only the expected vendor findings |
| B7 | `review.py` with `kicad-cli` | the netlist export parses, and its nets equal the board model's; ERC findings parsed |
| B8 | `export_review / export_jlcpcb / export_release / visual_diff` | packages complete; JLCPCB's viewer accepts Gerbers, BOM and CPL rotations |
| B9 | Network: `jlc_stock.py` (packages, lifecycle) on board A's BOM, `fetch_datasheet.py`, `easyeda2kicad` | real responses parsed; package check: no false mismatch on board A BOM |

Gate B: every row passes or has an issue filed with the fix; the KiCad version is recorded.

**Status (2026-11-22).** KiCad 10.0.3 on Windows (Python 3.14), board A at 49b38c1, then
51a4bcf / f3e1fbb for C2. B0–B9 all PASS after four fixes the runs found: kicad-cli not reaching the BOM step on a PC
without it on PATH (#17), SSOP/MSOP/TSSOP compared by name (#17), pins.py refusing a debug pin to the debug function
(#18), and evidence the kit didn't record (#16). The board findings the kit surfaced (AE801 short, an RF_50 trace
0.18 mm from a via hole on 49b38c1, gone on 51a4bcf) went to board A (C3). Open: the five checks in the KiCad
window, and B6's Altium import (needs TI's PcbDoc). A1/A2 done (v0.1.0); A3 (repo description) open.

### Phase C: first real user, board A (D27)

| # | Item | Owner decision needed |
|---|---|---|
| C1 | Replace board A's copied scripts with the plugin's (`scripts/pcb/*`, export scripts) | which copied scripts may go |
| C2 | Standard net classes on the schematic (`PWR_<I>A`, `GND`, ...), `netclasses.py apply`; `pcb_rules.py apply` with its stack-up recorded | board A's own classes (SUPPLY, PWR_BUS, GATE, SWITCH, CRYSTAL, ...) map to which standard ones |
| C3 | `review.py` on it; findings triaged into its issue tracker. Known so far: R701 0.68 mm from a QFN, no fiducials, In2.Cu ground in 5 pieces, four 25 V capacitors on the 12.6 V bus | each finding: fix or accepted deviation |
| C4 | TI-derived `scripts/pcb/boost_drv8711.json` | licence decision (D35): keep committed, or move to `reference/` |

Gate C: board A's CI runs the plugin's gates at a pinned tag; no copied script left that the plugin replaces.

**Status (2026-11-22).** C2 and C4 merged in board A (its PR 4: D-062 standard
classes, every multi-pin net classed, DRC unchanged on KiCad 10.0.3; D-063 TI's JSON in `reference/`). C1 and the gate
in #5: the seven copied scripts are wrappers around the plugin at `v0.1.0`, and a `plugin-gates` CI job runs
netclasses / pcb_rules (`--no-drc`) / review with ratchet limits at today's counts (D-064); D-065 keeps 0.15 mm on the
24 V gate nets (A7 can't be met at the DRV8711's 0.2 mm pad gaps). C3: full review of f3e1fbb under way; findings go
to board A's tracker for the owner's fix-or-accept.

### Phase D: measure (paid model runs, run by hand)

| # | Eval | Pass criterion |
|---|---|---|
| D1 | Placement: `evals/run.py` on the board A case, with and without the plugin, 3 runs each | D25: no worse than the owner's placement +10 % on ratsnest and crossings; then the placement gate's limits are set and it can fail |
| D2 | Review: `review_defects.py seed` on board A, the board-reviewer agent reviews the seeded copy, `score --report` | recall of the seeded defects at MINOR or above; target to be set from the first run (proposal: ≥ 80 %) and each miss turned into a rule or method fix |
| D3 | Review without the plugin (same seeded board, plain Claude) | the gap D2 − D3 is the plugin's value for review |

Gate D: the numbers are in `docs/` with their dates and costs; the gates' limits come from them.

### Phase E: generation (D17), decided with the numbers from D

Not built: scripted fan-out, stitching vias, power copper and pours, simple routes, tidy. Placement, pins and
schematics are generated; copper isn't. Options: build it (biggest remaining piece; needs B to have passed),
build only stitching and pours (lowest risk, measurable by the copper gates), or drop it and leave routing to the
owner and KiCad's router. **Owner decision.**

### Phase F: backlog (when a board needs it)

| Item | Note |
|---|---|
| Board B migration branch (D27) | after C proves the path |
| Gerber-only vendor references | board A's `nfc_reference.py` approach as a tool |
| Back-side land export, mirrored blocks | `reference-block` §6 |
| Kelvin `SENSE` net-tie check | promised in D9 as "later" |
| IPC-2221C, IPC-2152, IPC-9592B bought | replace the secondary transcriptions (clearance table, derating) with the standards' own values |
| KiCad bug report | custom rule overrides the Board Setup minimum (`pcb-design-rules` §4), against the manual |
| Altium schematics, KiCad < 10 boards in review | `design-review` §6 |
| Board B's `Vdrive` voltage | 12 V was an assumption for the review eval |
| Headless netlist to board | `kicad-cli` 10 has no *Update PCB from Schematic*; the example (`examples/stepper-ble/scripts/make_board.py`) uses `pcbnew`. A text-based equivalent in the plugin would close the headless flow (D22) |
| Attach placement in the plugin | the example's `make_board.py place` (parts at the pins they serve, one decoupling capacitor per supply pin, a lane for the reference) as a text-based `place.py attach`, so any board gets it without `pcbnew` |
| Bulk capacitors in the decoupling metric | `decap_p90` measures every capacitor to the nearest IC on its net; a bridge's bulk capacitor is right at its stage and still counts as far |
| Assembly spacing in the optimizer | `place.py optimize` avoids overlaps but not the assembler's package-pair spacing; on the example it put two 0402s 0.4 mm from the QFN, which only the gate caught |
| kicad-bot on unrouted boards | it counts unconnected items as DRC errors; an "allow unrouted" option would let the example gate DRC there too |

### Decisions the owner owns in this plan

A1–A3 (settings), C2 (class mapping), C4 (TI licence), D budget (D1 caps each run at the harness default of
25 USD, so 3 runs × 2 configurations is at most 150 USD; D2/D3 are one review each), E (generation scope), and
buying the IPC standards.

### Public example board (2026-11-22)

`examples/stepper-ble` replaces "trust the owner's boards" with a board anyone can open: designed with the plugin from
scaffold to placed board, every gate run on it in CI with KiCad 10 (kicad-bot installs it). Building it fixed three
tool defects: `netclasses.py` had no headless way to read the schematic's net-class directives (now `assign`), a
class at exactly 3 A was not flagged as a pour (rounding), and `jlc_stock.py` reported Diodes Inc's SOT25 as a
mismatch for SOT-23-5. It also found a KiCad library footprint below JLCPCB's annular ring (the example's D-006).
