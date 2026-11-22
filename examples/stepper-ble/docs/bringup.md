# Bring-up: stepper-ble

In order. Each step names the requirement it closes (HW-*), the instrument, the pass criterion and the result. The
board is not routed yet; this is the plan.

| # | Step | Closes | Pass criterion | Result (date) |
|---|---|---|---|---|
| B1 | Bench supply, current-limited to 0.2 A: 24 V, then 30 V, then reversed 24 V | HW-PWR-001, HW-PWR-003 | VM = input - fuse drop; reversed: < 1 mA drawn, nothing warm; Q101 VGS <= 15 V at 30 V | |
| B2 | 5 V and 3.3 V rails from 24 V, then from USB only, then both; sweep the input down | HW-PWR-004, HW-PWR-005, HW-USB-001 | 5V_BUCK 5.0 V +-3 %; buck starts >= 7.2 V, stops <= 6.9 V; +3V3 3.3 V; no back-feed into VBUS (host side); USB enumerates | |
| B3 | SWD connect over TC2030; read VM_SENSE at 12/24/30 V | HW-DBG-001, HW-PWR-006 | SWD and SWO work, NRST resets; ADC within 2 % of a meter | |
| B4 | HSE: measure with a counter (>= 0.1 ppm), trim XOTUNE per AN5042, store; LSE starts with LSEDRV = 11 | HW-MCU-001 | 32 MHz within +-5 ppm after trim; LSE starts in < 2 s at 25 C | |
| B5 | Antenna: VNA at the feed (0 ohm removed, coax to the pad), in the enclosure; fit at most two of R501/C501/C502; RSSI and DTM tests | HW-RF-001 | S11 <= -10 dB (SWR <= 2) over 2402-2480 MHz; 2nd/3rd harmonic scan below FCC 15.209 in the restricted bands | |
| B6 | Motor, 24 V, 0.5 A then 2.0 A: register set (ISGAIN 10, TORQUE 186), STEP/DIR, stall, fault; scope AOUTx at the DRV8711 pin in dead time | HW-MOT-002, HW-MOT-003, HW-MOT-004, HW-MOT-006, HW-MOT-008 | peak phase current 2.0 A +-10 %; STALLn asserts on a held rotor; outputs off during MCU reset; phase pin >= -0.6 V or clamps fitted (D-013) | |
| B7 | Thermal soak at 2 A continuous stepping, 30 min; read NTC_SENSE against a thermocouple on the FETs | HW-MOT-005 | NTC within 3 C of the thermocouple; FETs < 100 C | |
| B8 | LEDs and button | HW-UI-001, HW-UI-002 | green LED visible in room light at ~0.5 mA (else lower R701, D-023); button edge on EXTI | |
