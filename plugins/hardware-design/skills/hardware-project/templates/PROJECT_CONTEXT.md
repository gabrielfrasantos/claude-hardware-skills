# {{NAME}}: project context

Paste or attach this file at the start of a new conversation to restore the context. Keep it short and current:
update it at every gate.

## What it is

{{TITLE}}. Firmware: {{FIRMWARE}}. Built at {{FAB}}, {{LAYERS}} layers.

## State

- Phase: 0 (requirements and sizing). Gate: not signed off.
- Open items: see `docs/plan.md` and each doc's open-items section.

## Architecture

ASSUMPTION: fill in at the Phase 0 gate (power flow, MCU, key parts, interfaces), with the decision IDs.

## Where things are

- `docs/requirements.md` (contract), `docs/decisions.md` (intent), `docs/plan.md` (phases, gates)
- `scripts/schgen/` (schematic), `hardware/{{NAME}}/` (KiCad project), `simulation/` (SPICE, REPORT.md)
- `pin-data/` (firmware pin needs, pin map), `bom/` (BOM, stock check)
