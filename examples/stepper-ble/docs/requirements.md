# Hardware requirements

This is an example board with no firmware repo, so every requirement traces to a decision in `docs/decisions.md`
or a skill section. `trace.py` checks the table.

Verification methods:
- **R**: design review against the schematic or layout;
- **S**: simulation in `simulation/` (S0, S1, ... in `docs/plan.md`);
- **B**: bring-up test in `docs/bringup.md`;
- **T**: a test on the assembled board beyond bring-up.

## Power

| ID | Requirement | Source | Verify |
|---|---|---|---|
| HW-PWR-001 | Input 24 V nominal, 30 V maximum; survives reversed input and 33 V transients clamped by the TVS. | D-002 | R, B |
| HW-PWR-002 | Input current limited by a 3 A fast fuse; VM and its return are 3 A pours. | D-002 | R |
| HW-PWR-003 | The logic (5 V, 3.3 V) runs from 24 V or from USB VBUS alone. | D-009 | R, B |

## Motor

| ID | Requirement | Source | Verify |
|---|---|---|---|
| HW-MOT-001 | Drive one bipolar stepper, up to 2.0 A peak per phase, with stall detection. | D-003 | R, T |
| HW-MOT-002 | Firmware sets ISGAIN 10 and TORQUE at most 186 (2.0 A with 0.1 ohm sense). | D-003 | R |
| HW-MOT-003 | The FETs' temperature is measured by an NTC between the bridges. | D-007 | R, B |

## Radio

| ID | Requirement | Source | Verify |
|---|---|---|---|
| HW-RF-001 | Bluetooth LE at 2.4 GHz on a PCB antenna, with a tuning network fitted at bring-up. | D-004 | R, B (VNA) |

## Interfaces

| ID | Requirement | Source | Verify |
|---|---|---|---|
| HW-IF-001 | USB 2.0 full-speed device on USB-C (sink, 5.1 kohm Rd), ESD on D+/D- at the connector. | interface-layout §2 | R, T |
| HW-IF-002 | SWD and reset on a Tag-Connect TC2030 footprint (no connector fitted). | D-004 | R |

## Mechanics

| ID | Requirement | Source | Verify |
|---|---|---|---|
| HW-MEC-001 | 80 x 60 mm, four M3 holes at the corners; power and motor terminals on the left half, USB-C on the bottom edge, antenna at the top edge. | D-007 | R |

## Manufacturing

| ID | Requirement | Source | Verify |
|---|---|---|---|
| HW-MFG-001 | JLCPCB, 4 layers SIG/GND/GND/SIG, 1.6 mm, IPC Class 2, JLCPCB assembly. | D-001 | R |
| HW-MFG-002 | The example stops at placement: the board is not routed. | D-011 | R |

## Open items

- Test points: the review lists 15 supply nets without one (`review.py` F22). Add them when the board is routed.
- EMC and safety standards: not set for an example board.
