# stepper-ble: project context

Paste or attach this file at the start of a new conversation to restore the context. Keep it short and current:
update it at every gate.

## What it is

stepper-ble: 24 V stepper driver with Bluetooth LE (DRV8711 + STM32WB55CG), the repository's worked example. Firmware: none (example board). Built at jlcpcb, 4 layers.

## State

- Phase: 0 (requirements and sizing). Gate: not signed off.
- Open items: see `docs/plan.md` and each doc's open-items section.

## Architecture

ASSUMPTION: fill in at the Phase 0 gate (power flow, MCU, key parts, interfaces), with the decision IDs.

## Where things are

- `docs/requirements.md` (contract), `docs/decisions.md` (intent), `docs/plan.md` (phases, gates)
- `scripts/schgen/` (schematic), `hardware/stepper-ble/` (KiCad project), `simulation/` (SPICE, REPORT.md)
- `pin-data/` (firmware pin needs, pin map), `bom/` (BOM, stock check)
