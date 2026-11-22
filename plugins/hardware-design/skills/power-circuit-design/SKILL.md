---
name: power-circuit-design
description: Design or review the schematic of power circuits (battery and DC-bus input, reverse polarity, power switch, inrush and hot plug, surge clamp, fuse, UVLO, buck and LDO rails, H-bridge and three-phase motor stages, gate drive, bootstrap and charge pump, dead time, bus capacitors, regeneration, shunt current sense, protection and safe state, snubbers, thermal) with sourced rules, vendor-neutral.
---

# Power circuit design (schematic level)

Use this skill when you choose the topology, parts and values of a board's power path and power stages, and when you review them. It covers the schematic side; the copper is in `power-pcb-layout`, the verification in `circuit-simulation`, and the current-sense amplifier chain in `analog-circuit-design`.

It is distilled from two real boards: a three-phase FOC driver on a 50 V bus, and a 3S LiPo robot with two H-bridges. Their parts appear only as labelled examples. **The datasheet of the part you use wins.** Values marked *(derived)* are arithmetic from cited formulas, and *rule of thumb* marks guidance without a primary source (§13 lists them).

Companion skills: `power-pcb-layout` (hot loops, gate loops, Kelvin routing, thermal copper), `mcu-circuit-design` (logic rails, safe state of MCU pins, back-powering), `analog-circuit-design` (sense amplifier, ADC drive), `circuit-simulation` (S-checks below), `pcb-copper` (net classes from currents).

## 1. Workflow

1. **Write the numbers first:**
   - **Voltages:** nominal, minimum, and the abnormal maximum the board must survive, $V_{abs}$ (a mis-set charger, a load dump, a hot plug).
   - **Currents:** continuous, peak, the trip level, stall.
   - **Regeneration:** where energy comes back, and how much.
   - Every number gets a source, or is marked ASSUMPTION.
2. **Build the voltage ladder:** list every part on each bus with its absolute maximum, and put the surge clamp's clamping voltage $V_C$ (§3) under all of them. Most power-stage failures are a part whose absolute maximum sits below $V_C$.
3. **Draw the blocks in power-flow order:** input path (§2–§5), rails (§6), stage (§7–§10), sense and protection (§11–§12).
4. **Simulate what the numbers cannot settle** (`circuit-simulation`):
   - **Power entry:** switch-on, hot plug with the switch on and off, reverse battery, switch-off while regenerating.
   - **Bridge:** shoot-through, switch-node overshoot, the phase pin's negative swing, losses.
   - **Bus:** ripple, sag, UVLO margins, regeneration.
5. **Fill the checklist (§14)** and log the choices in `docs/decisions.md` (`hardware-project`).

## 2. Input path: order, reverse polarity, switch

- **Order:** connector → fuse → reverse-polarity element → switch → surge clamp and bulk → loads.
  - The clamp sits **after** the reverse-polarity element. A unidirectional TVS ahead of it conducts forward into a reversed source and blows the fuse at best. Put it first only if a fuse-blowing crowbar is the intended reverse protection.
  - Anything always-on (dividers, monitors) sits after the switch, or it counts against the off-state budget.
- **Reverse polarity:** series diode, high-side P-FET or low-side N-FET, in order of rising efficiency; a FET drops only $I \cdot R_{DS(on)}$ [SLVA139]. An ideal-diode controller is the FET option with control.
- **Regeneration decides the topology.**
  - A diode or an ideal-diode controller conducts one way only. Energy a decelerating, reversed or back-driven motor returns then has nowhere to go but the bulk capacitance, and the bus pumps (§9).
  - **Back-to-back P-FETs** (common source) block a reversed source, switch the load and conduct both ways when on. Example: AO4805 (dual P-FET) on a 3S LiPo input.
- **Gate voltage at both ends of the input range:**
  - at $V_{min}$, the gate drive reaches the $R_{DS(on)}$ specification point;
  - at $V_{abs}$, it stays inside $V_{GS}$ absolute maximum, with a gate-source Zener as the transient backstop.
  - Example: a 100 k / 100 k divider gives −4.5 V at 9.0 V and −6.8 V at 13.5 V, against ±20 V *(derived)*.
- **Switch the gate, not the current:** a small switch on the gate line needs no rating for the load current.
- **Off-state drain** = FET $I_{DSS}$ + Zener leakage + everything ahead of the switch. Compare it with the requirement.

## 3. Surge clamp (TVS)

- **Standoff** $V_{RWM} ≥ V_{abs}$, so the TVS does not conduct in normal operation.
- **Every part on the bus must survive the clamping voltage** $V_C$ at the expected pulse current, not only the standoff: regulator VIN, driver supply pin, bridge and power-path $V_{DS}$, capacitor ratings.
  - Example: SMBJ15A, $V_{RWM}$ 15 V, $V_C$ 24.4 V at its rated peak pulse current $I_{PP}$ (10/1000 µs waveform) [LF-SMBJ] (ratio about 1.6), against a 30 V lowest absolute maximum on the bus. At smaller currents $V_C$ is lower; at a longer or larger pulse than the rating, the part fails.
  - Read each TVS's own table; the ratio is a *rule of thumb* across families.
- **A bus TVS does not protect the switching FETs from their own ringing.** With $V_{RWM}$ above the bus, $V_C$ usually lands above a tightly rated FET's $V_{(BR)DSS}$. The FET's margin against switching overshoot is held by the commutation loop and the HF bypass (`power-pcb-layout` §3.1), the gate drive (§8) and, if needed, a snubber (§12). Example: a 50 V bus with 60 V FETs and a 51 V-standoff TVS.
- **Energy:** the TVS absorbs what the bulk cannot during regeneration with the input path open (§9). Compare with its pulse rating at the real pulse width.

## 4. Inrush, soft start, hot plug

- **Inrush:** a fully-on switch charging the bulk from a stiff source is limited only by source, lead and switch resistance. Check the peak against the switch's pulse rating and SOA and the fuse's $I^2t$.
- **Soft start by Miller capacitance:** a gate-drain capacitor with a gate resistor sets $dV/dt ≈ I_G / C_{GD,ext}$, so the inrush is $C_{bulk} \cdot dV/dt$ *(derived)*.
  - Example: 0.08 mA into 47 nF ≈ 1.7 V/ms, so ≈ 0.5 A into the bulk for ≈ 7 ms.
  - Soft start also makes turn-off slow. Switching off under load dissipates in the FET during the ramp: size it, and tell the firmware to unload first.
- **Hot plug is a different event from switch-on.**
  - Plugging the source in steps the input FET's source up through its body diode while the gate capacitor still holds the gate low. The gate-drain capacitance couples the edge into $V_{GS}$ and can turn the FET on.
  - **Fix:** a gate-source capacitor, so the step $V_{in} \cdot C_{GD}/(C_{GD}+C_{GS})$ stays below $|V_{th,min}|$ *(derived)*.
  - **Example:** on a 3S LiPo robot board, simulation found a 44.6 A hot-plug spike above the FET's 40 A pulse rating, and the logic powering up with the switch off, before this fix.
  - Simulate hot plug with the lead inductance and source resistance, switch on and off.
- **Mains or bench-supplied buses:** an NTC or a pre-charge resistor bypassed after charge does the same job (*rule of thumb*: choose by energy and restart time).

## 5. Fuse, under-voltage

- **The fuse is the last, non-resettable backstop** behind the electronic limits (§11).
  - **Continuous current:** derate per the fuse datasheet's temperature and derating curves.
  - **Bursts:** check the recovery bursts on its time-current curve.
  - **Breaking capacity:** at least the maximum available fault current at rated voltage [LF-FUSE]. For a battery that is $V_{max}/(R_{int} + R_{leads})$ *(derived)*; LiPo internal resistance is low, so this check matters. Example: 12.6 V / 60 mΩ ≈ 210 A against a 300 A rating, with the 60 mΩ an ASSUMPTION until measured.
  - **Voltage rating** ≥ $V_{abs}$.
- **UVLO:** the regulator's or driver's enable divider (with hysteresis) keeps loads off where they would misbehave. With a battery and no BMS, it also protects the pack. Set any firmware under-voltage action **above** the hardware UVLO, so the firmware acts first.
- **Sag:** $V_{bus} = V_{OCV} − I_{pk}(R_{int} + R_{path})$ for the oldest, coldest source *(derived)*. Check it against every load's minimum and the UVLOs.
- **Bus voltage to the ADC:** the divider, charge bucket, settling and error budget are in `analog-circuit-design`.

## 6. Rails: buck and LDO

- **Buck input:** recommended VIN maximum ≥ $V_{abs}$, absolute maximum ≥ $V_C$ (§3). A regulator that only meets the nominal bus fails at the first clamp event.
- **Inductor:** ripple 20–40 % of the maximum output current as a starting point [SLVA477], unless the converter's datasheet asks otherwise (some need a minimum ripple for slope compensation). Check $I_{sat}$ ≥ the peak, and say what a hard short does.
- **Capacitors:** use the **effective** capacitance at the DC bias, not the nominal, against the datasheet's minimum for loop stability. Input-capacitor ripple per [SLTA055].
- **Near a radio:** a fixed frequency (forced PWM) keeps spurs at known frequencies at every load (`rf-layout`).
- **LDO:**
  - dropout at the lowest input;
  - $P = (V_{in} − V_{out}) \cdot I$, and $T_J = T_A + P \cdot R_{θJA}$ with the board's copper, not the datasheet's reference board;
  - output capacitor type and minimum per the datasheet;
  - PSRR at the buck's and the motor PWM's frequencies.

  Feed it from the buck, not from a high bus *(derived: dissipation)*.
- **Analog rail:** the sense amplifier and ADC reference get a filtered or separate supply (`analog-circuit-design`).
- **Sequencing and back-powering:** logic and gate supply before PWM enable; anything powered from an earlier rail that drives MCU pins can back-power the MCU (`mcu-circuit-design`).
- **Branches leaving the board** (encoder supply, expansion power) go through a current limit (PTC, resistor, load switch), so a shorted cable cannot pull a rail down.

## 7. Bridge: topology, FETs, losses

- **Topology:** a gate driver with external FETs scales current independently of the driver; an integrated-FET driver is simpler where its $R_{DS(on)}$ and thermal limits suffice. **A dual-FET package per half-bridge** keeps the phase node and the commutation loop short.
- **FET selection:**

  | Parameter | Check |
  |---|---|
  | $V_{(BR)DSS}$ | ≥ $V_C$ (§3) plus switch-node overshoot. Steady bus ≤ about 80 % of $V_{(BR)DSS}$ (*rule of thumb*; IPC-9592B sets derating for power conversion devices); otherwise move up a voltage class |
  | $R_{DS(on)}$ | at the **gate voltage the driver gives** and the **junction temperature** you expect, from the datasheet's normalised curve |
  | $V_{GS}$ | absolute maximum above the driver's gate voltage, with margin for ringing |
  | $Q_g$, $Q_{gd}$ | $Q_g \cdot f_{PWM} \cdot$ number of FETs within the driver's gate-supply budget; $Q_{gd}$ sets the edge rate (§8) |
  | Body diode, $Q_{rr}$ | carries the dead-time current; its $V_f$ sets the phase node's negative swing (§8); $Q_{rr}$ adds turn-on loss and ringing |
  | SOA, avalanche | survives the turn-off energy and fault currents until the trip acts |
  | Package | the datasheet's land pattern, exposed pad included: a generic land on a power package breaks the thermal and current path |

- **Losses per FET:**
  - **Conduction:** $I_{rms}^2 \cdot R_{DS(on)}(T_J)$.
  - **Switching:** ≈ $½ \cdot V_{bus} \cdot I \cdot (t_r + t_f) \cdot f_{PWM}$, plus $Q_{rr} \cdot V_{bus} \cdot f_{PWM}$ *(derived, linear transitions)*.
  - Sum them over all FETs and the shunts for the thermal budget (§12).
- **Ripple current:** $ΔI_{pp} = V_{bus} D(1−D)/(L \cdot f_{PWM})$, largest at D = 0.5 *(derived)*. Keep the PWM period well below the motor's $L/R$, and $f_{PWM}$ above the audible band.
- **Decay:** slow decay (both low sides on in the off time) gives torque close to proportional to duty and low ripple; fast decay returns energy to the bus every period (§9).

## 8. Gate drive and dead time

- **High-side supply:**
  - **Bootstrap:** the low side must conduct every period to recharge it, so duty stays below 100 %, and a stalled rotor held in one state can starve it. Size it per [SLUA887A] §3:
    - $C_{BOOT} ≥ 10 \cdot C_g$, with $C_g = Q_g/(V_{DD} − V_{F,boot})$ (Eq. 1–2);
    - and $C_{BOOT} ≥ Q_{total}/ΔV_{HB}$ (Eq. 3), with $Q_{total} = Q_G + I_{HBS} \cdot D_{max}/f_{sw} + I_{HB}/f_{sw}$ (gate charge, HB leakage over the on-time, HB quiescent current) and $ΔV_{HB} = V_{DD} − V_{DH} − V_{HBL}$: the supply minus the diode drop minus the driver's HB UVLO falling threshold;
    - $C_{VDD} ≥ 10 \cdot C_{BOOT}$ (Eq. 5), so the gate supply doesn't sag at each recharge;
    - low-ESR MLCCs rated about $2 \cdot V_{DD}$;
    - a Schottky or fast-recovery diode, low forward drop and junction capacitance, rated above the bus with margin. SLUA887A has no $Q_{rr}$ term; a slow diode's reverse recovery shows up as overshoot and UVLO trips, which is why it asks for a fast one.

    Placement is in `power-pcb-layout` §3.2.
  - **Charge pump:** allows 100 % duty. Its flying and storage capacitors are rated for the bus plus the pump voltage (driver datasheet), and its current budget limits $Q_g \cdot f_{PWM}$.
- **Edge rate:** switching time ≈ $Q_{gd}/I_G$ [SLUP169].
  - Faster edges cut switching loss but ring and couple; at tens of kHz switching loss is small, so drive gently.
  - Put gate-resistor footprints at each FET (0 Ω by default) for bench tuning. Split on/off resistors (a diode across the off one) make turn-off faster than turn-on.
- **Miller turn-on:** the opposite FET's dV/dt couples through $C_{GD}$ into an off gate.
  - Hold it with a low-impedance turn-off path, the driver's Miller clamp, or a gate-source resistor at the FET.
  - A gate-source pull-down also holds the FETs off while the driver is unpowered, if the driver doesn't.
- **Dead time** ≥ turn-off delay + fall time at the configured gate current, with margin across corners. Many drivers set it; verify the value against the FET's timing, and verify no shoot-through in simulation.
- **Negative phase-node swing:** during dead time the load current freewheels through the low-side body diode, so the phase node sits near −$V_f$, plus ringing.
  - Check it against the driver's phase-pin absolute minimum.
  - Fix with a Schottky from GND to each phase node at the pins, FETs with integrated Schottky, or a driver rated for the swing.
  - Example: a 3S LiPo robot board simulated −0.73 V for about 3 µs against a −0.6 V limit; an SS34 clamp brought it to −0.36 V.

## 9. Bus capacitors and regeneration

- **HF bypass at every half-bridge:** 100 nF–1 µF low-ESL MLCC across HS drain and LS source, closest to the FETs. For class-II MLCCs, take the effective capacitance from **the part's own DC-bias curve** at the bus voltage, then allow for further drift: under constant bias, X7R capacitance keeps falling over time, by more than 20 % in 1000 h at 40 % of rated voltage for most parts tested [VISHAY-BIAS]. A rating of about 2× the bus is only a screening default (*rule of thumb*; TI gives 2× for bootstrap capacitors [SLUA887A]); the curve decides.
- **Bulk sized for ripple current**, not only capacitance:
  - **H-bridge, all ripple in the capacitor:** at most $I_{bus}\sqrt{D(1−D)}$ *(derived: SLTA055 gives this form for a buck converter's input capacitor [SLTA055]; an H-bridge drawing the same pulsed current from the bus sees the same RMS)*.
  - **Three-phase inverter:** the RMS capacitor current is a closed form in modulation index, phase-current amplitude and power factor [KOLAR]. Use it, or simulate (`circuit-simulation`).
  - The source and the MLCCs share the ripple, so simulate the split. Compare the result with the capacitor's ripple rating at $f_{PWM}$ and temperature.
- **Electrolytic life** doubles for every 10 °C its temperature drops [WE-SN008]. Use the maker's life model with core temperature and voltage derating [CDE]. Ripple heats it, so keep it away from FETs and shunts.
- **Regeneration:**
  - **When:** whenever back-EMF exceeds the average voltage the bridge applies (deceleration, reversal, back-driving), a synchronous bridge returns current to the bus.
  - **Where it goes:** to the source if the input path conducts both ways (§2); otherwise into the bulk, $V_2 = \sqrt{V_1^2 + 2E/C}$ *(derived)*, then the TVS.
  - **Worst case:** the input open (switch off, fuse blown, connector bouncing) while the load is driven; the body diodes rectify the back-EMF onto the bus.
  - **Pass criteria:** peak bus below the lowest absolute maximum on the bus; TVS energy within rating.
  - **Sustained regeneration** needs a firmware limit or a brake chopper (*rule of thumb*).

## 10. Current sense

| Topology | Use | Watch |
|---|---|---|
| Low-side shunt per leg | cheap, ground-referenced amplifier | valid only while the low side conducts: sample in that window (centre of the PWM period for centre-aligned PWM) and settle before it |
| Inline (phase) shunt | true phase current at any time | the amplifier must reject the full phase common-mode swing and its dV/dt |
| Bus shunt | total current, trip | not per phase |
| Hall / magnetic | isolation, no I²R | offset, drift, bandwidth |

- **Shunt sizing:**
  - **Value:** full-scale current × R inside the amplifier's input range (example: 5 A × 20 mΩ = 100 mV).
  - **Power:** $P = I_{rms}^2 R$ with margin, plus the pulse rating at the trip current (example: 0.5 W at 5 A in 20 mΩ, so a 2 W 2512 part *(derived)*).
  - **Construction:** low tempco, low inductance.
- **Kelvin connection:** sense from the shunt element itself. In the schematic, keep the sense nets distinct from ground with a net tie (`power-pcb-layout` §3.6 for the copper; `pcb-copper` class `SENSE`).
- **Filter** symmetric, at the amplifier, and settled within the sample window. **Blanking** ≥ the sense settling after each edge (driver datasheet).
- **The chopping trip is a peak limit.** A motor's continuous rating is thermal and needs an I²t model in firmware. The motor connector and the shunt are rated for the trip current or covered by that model.
- Offset and gain calibration, and the amplifier choice, are in `analog-circuit-design`.

## 11. Protection and safe state

- **Over-current, fastest first:**
  1. a hardware cycle-by-cycle or fault trip (comparator on the shunt, or the driver's $V_{DS}$ / desaturation monitor) that forces all FETs off within a PWM period;
  2. the driver's fault output to the MCU timer's break input;
  3. the firmware current limit;
  4. the fuse.

  Software alone is too slow for a hard short. Set the trip above the legitimate peak and below the FET, shunt and connector limits, and verify the response time.
- **Over-temperature:** an NTC on the copper at the FETs and shunts, read by the MCU, with fold-back then shutdown in firmware. The parts' own thermal shutdown is a backstop, not the limit.
- **Safe state:** for power-up, brown-out, reset, gate-supply loss and fault, every gate is held off (driver UVLO, pull-downs, enable lines with a defined reset level). Write the table of every control line's level in each state, and check it against the MCU's reset pin states (`mcu-circuit-design`).
- **Cable outputs** (motor phases) are clamped by the bridge itself: body diodes to the bus and GND, with the bus TVS taking the energy. Connector ESD for signal cables is in `interface-layout`.

## 12. Snubbers and thermal

- **RC snubber, when layout and gate drive are not enough** [AN11160 rev 3.1]:
  1. Measure the switch-node ringing frequency $f_0$ without a snubber.
  2. Add a known capacitor $C_{add}$ across the FET and measure the new frequency $f_1$. With $x = f_0/f_1$: loop capacitance $C_{LK} = C_{add}/(x^2 − 1)$ and inductance $L_{LK} = 1/((2\pi f_0)^2 C_{LK})$.
  3. Start with $C_S$ = 1–2 × $C_{LK}$. Damping is $ζ = R_S/(2 Z_0)$ with $Z_0 = \sqrt{L_{LK}/C_S}$; aim for ζ between 0.5 and 1, i.e. $Z_0 ≤ R_S ≤ 2 Z_0$; AN11160's optimum is $R_S ≈ 1.5\,Z_0$.
  4. Keep $R_S C_S$ below a tenth of the shortest on-time, so the snubber discharges every period.
  5. Size the resistor for $P ≈ f_{sw}(½ L_{LK} I_{RM}^2 + ½ C_S V_{bus}^2)$, with $I_{RM}$ the peak reverse-recovery current. The capacitor term grows with $C_S$: that is the trade against peak voltage.

  Leave the footprints; fit the values on the bench.
- **Thermal:** $T_J = T_A + P \cdot R_{θJA}$, with $R_{θJA}$ from the datasheet's copper-area curves for the copper you will actually lay out, and $R_{DS(on)}$ at temperature. Exposed pads need the datasheet's via pattern (`power-pcb-layout` §3.7). Keep electrolytics, references, crystals and the IMU away from heat. Verify with a thermal soak at bring-up.

## 13. Where sources disagree, and rules of thumb

| Item | Status | To close |
|---|---|---|
| Steady bus ≤ 80 % of $V_{(BR)DSS}$ | *rule of thumb*; IPC-9592B §4.4 and Table A-3 set transistor derating (contents seen, values not read) | the project's derating policy, or the purchased IPC-9592B |
| TVS $V_C ≈ 1.6 × V_{RWM}$ | example of one family (SMBJ15A [LF-SMBJ]) | read each TVS's table |
| MLCC bypass rated about 2× the bus | screening default only; 2× is TI's figure for bootstrap capacitors [SLUA887A] | the MLCC's DC-bias curve plus bias-aging drift [VISHAY-BIAS] |
| Sustained regeneration needs a limit or chopper | *rule of thumb* | the source's charge limits |
| Inductor ripple 20–40 % | starting point [SLVA477]; some converters need a minimum | the converter's datasheet |

## 14. Checklist

- [ ] Voltages ($V_{min}$, nominal, $V_{abs}$), currents (continuous, peak, trip, stall) and regeneration written down with sources.
- [ ] Voltage ladder: every part on every bus has an absolute maximum ≥ $V_C$; TVS standoff ≥ $V_{abs}$.
- [ ] Input order right; reverse polarity handled; regeneration path chosen; gate voltages checked at both ends; off-state drain within budget.
- [ ] Inrush, hot plug (switch on and off) and turn-off under load simulated or calculated.
- [ ] Fuse: derating, breaking capacity ≥ prospective fault current, voltage rating.
- [ ] UVLO set; firmware under-voltage above it; sag checked against every minimum.
- [ ] Buck: input ratings vs $V_C$, inductor ripple and $I_{sat}$, effective capacitance; LDO dissipation and dropout.
- [ ] FETs: $V_{(BR)DSS}$, $R_{DS(on)}$ at gate voltage and temperature, $Q_g$ budget, footprint = datasheet land.
- [ ] Gate drive: high-side supply sized; duty limit known; gate-resistor footprints; Miller hold-off; gates off when unpowered; dead time verified.
- [ ] Phase-pin negative swing within the driver's limit.
- [ ] Bus capacitors: HF MLCC per half-bridge, bulk ripple rating, life at temperature; regeneration peak and TVS energy within limits.
- [ ] Current sense: shunt value, power, pulse rating; Kelvin net tie; filter, blanking, sample window agreed with firmware.
- [ ] Protection layers and response times; NTC; safe-state table for every control line.
- [ ] Loss budget and junction temperatures; footprints for snubbers where ringing is a risk.

## 15. References

- [SLVA139] TI, *Reverse Current/Battery Protection Circuits*.
- [SLUA887A] TI, *Bootstrap Circuitry Selection for Half-Bridge Configurations*, rev A (Sep 2023): §3.1 Eq. 1–3, §3.2 Eq. 5, §3.3 diode. https://www.ti.com/lit/SLUA887
- [VISHAY-BIAS] Vishay, *Time-dependent capacitance drift of X7R MLCCs exposed to constant DC bias voltage* (0603 100 nF 50 V, 1000 h, four makers). https://www.vishay.com/docs/45263/timedepcapdrix7rmlccexptoconstdcbiasvolt.pdf
- [SLUP169] TI, *Design and Application Guide for High Speed MOSFET Gate Drive Circuits*.
- [SLTA055] TI, *Input and Output Capacitor Selection*.
- [SLVA477] TI, B. Hauke, *Basic Calculation of a Buck Converter's Power Stage* (rev B, 2015): inductor ripple estimate 20–40 % of the maximum output current. The same starting point appears in TI datasheets, e.g. LM76002 (SNVSAK0A).
- [AN11160] Nexperia (formerly NXP), *Designing RC snubbers*, rev 3.1 (21 Oct 2024): §2 Eq. 4–11 (limits, damping), §3 Eq. 14–19 (finding $C_{LK}$, $L_{LK}$), §4 Eq. 20–27 (worked example). https://www.mouser.lt/pdfDocs/AN11160.pdf
- [KOLAR] J. W. Kolar, S. D. Round, "Analytical calculation of the RMS current stress on the DC-link capacitor of voltage-PWM converter systems", *IEE Proc. Electric Power Applications* 153(4), 535–543, 2006.
- [WE-SN008] Würth Elektronik, SN008, *Expected Lifetime of Aluminum Electrolytic and Aluminum Polymer Capacitor*.
- [CDE] Cornell Dubilier, aluminum electrolytic capacitor application guide and life calculators (life = $L_b \cdot M_v \cdot 2^{(T_{max}−T_{core})/10}$).
- [LF-SMBJ] Littelfuse, SMBJ series TVS datasheet.
- [LF-FUSE] Littelfuse, *Fuseology* selection and design guides: breaking capacity (interrupting rating) and the maximum available fault current.
- IPC-9592B, *Requirements for Power Conversion Devices for the Computer and Telecommunications Industries* (Nov 2012): §4.4 derating guidelines, Table A-3 diodes and transistors (contents only: https://www.electronics.org/TOC/IPC-9592B.pdf).
- Board examples: the design guides and simulation report of the two boards above (not public sources; the numbers are reproduced here with their context).
