# stepper-ble: project context

Paste or attach this file at the start of a new conversation to restore the context. Keep it short and current:
update it at every gate.

## What it is

stepper-ble: 24 V stepper driver with Bluetooth LE, the hardware-design-skills worked example. No firmware repo
(D-017). Built at JLCPCB, 4 layers.

## State

- Phase 3 (layout): placed, not routed. Pin map frozen (D-014). No gate signed off.
- Open items: OI-1..OI-5 in `docs/requirements.md`; simulation S1/S2 not built.

## Architecture

24 V in (J101) -> F101 3 A -> Q101 reverse N-FET in the return (D-003) -> SMAJ33A -> VM. VM feeds the DRV8711 and eight
CSD18543Q3A in two H-bridges with 0.1 ohm sense (D-002, D-021), and the LMR36510 5 V buck (D-005). 5 V and USB VBUS
are OR-ed by SS34s into +5V; AP2112K makes +3V3 for the STM32WB55CGU6 (SMPS mode, D-006), whose RF goes through
the MLPF-WB55-01E3 to a SWRA117D PCB antenna (D-007). USB-C sink with USBLC6 (D-008). SWD on TC2030 (D-009).

## Where things are

- `docs/requirements.md` (contract), `docs/decisions.md` (intent), `docs/plan.md` (phases, status)
- `scripts/schgen/` (schematic), `scripts/make_library.py` (project library), `scripts/make_board.py` (board)
- `hardware/stepper-ble/` (KiCad project), `pin-data/` (pin needs, pin map)
