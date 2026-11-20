# Hardware requirements

Every requirement traces to a firmware requirement (`REQ-*` in {{FIRMWARE}}), a firmware design fact (file:line in
that repo), a skill section, or a decision in `docs/decisions.md`. `trace.py` checks the table.

Verification methods:
- **R**: design review against the schematic or layout;
- **S**: simulation in `simulation/` (S0, S1, ... in `docs/plan.md`);
- **B**: bring-up test in `docs/bringup.md`;
- **T**: a test on the assembled board beyond bring-up.

## Power

| ID | Requirement | Source | Verify |
|---|---|---|---|
| HW-PWR-001 | ASSUMPTION: input range and the abnormal voltage it must survive. | D-001 | R, S1 |

## Interfaces

| ID | Requirement | Source | Verify |
|---|---|---|---|

## Mechanics

| ID | Requirement | Source | Verify |
|---|---|---|---|

## Open items

- ASSUMPTION rows above are placeholders: replace them from the firmware's requirements at Phase 0.
