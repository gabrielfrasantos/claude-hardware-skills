---
name: mcu-circuit-design
description: Design or review the schematic around any microcontroller (STM32, TI Tiva/MSP, NXP LPC/Kinetis/i.MX RT, Microchip AVR/SAM and others), covering supplies, reset/boot, clocks, debug, GPIO protection, ESD and common interfaces.
---

# MCU circuit design (schematic level, any vendor)

Use this skill when you design or review everything around a microcontroller:
- power pins and decoupling;
- reset and boot selection;
- oscillators;
- the debug port;
- GPIO and connector protection;
- ESD/EMC;
- USB, I2C, SPI, CAN and RS-485;
- inductive loads and the board's input protection.

**The skill is vendor-neutral.** Each section gives the generic rule, the **parameter to look up** for your part, and **examples from several families** (STM32, TI TM4C/Tiva, NXP LPC55/Kinetis/i.MX RT, Microchip AVR). The examples are there to show what the documents contain and how much the values differ. **Never copy one family's values to another.** The MCU's own datasheet and hardware design guide always win.

Every fact is traced to a document in §13, with its key in [brackets].

## 0. Find the part's documents first

Every vendor publishes a hardware design guide per family. Find it before drawing anything, together with:
- the datasheet (absolute maximum ratings, pin tables, oscillator specs);
- the reference manual (boot and option bytes/fuses);
- the errata;
- the evaluation-board schematic.

| Family | Hardware design guide (examples) |
|---|---|
| ST STM32 | *Getting started with STM32xx hardware development*, e.g. AN4488 (F4), AN5093 (G4). Oscillators: AN2867. EMC: AN1709. GPIO: AN4899. USB: AN4879. |
| TI TM4C (Tiva C) | *System Design Guidelines for the TM4C123x / TM4C129x Family*: SPMA059 / SPMA056 |
| NXP LPC55 | AN13033, *Hardware Design Guidelines for LPC55(S)xx Microcontrollers* |
| NXP i.MX RT | *Hardware Development Guide for the MIMXRT1050/MIMXRT1060 Processor* (MIMXRT105060HDUG); other RT parts have their own HDG |
| NXP Kinetis | Family reference manual and datasheet. EMC: AN4747 (Kinetis L). |
| Microchip AVR | AN2519, *AVR Microcontroller Hardware Design Considerations* |

For other families, search the vendor's site for "hardware design guidelines", "hardware development guide" or "getting started with hardware development" plus the family name.

## 1. Workflow

1. **Collect the documents** (§0).
2. **Draw the power-pin map.** List every supply, analog-supply, reference, backup and core-regulator pin, with its capacitors (§2).
3. **Define how the part resets and how it decides what to boot** (§3). Then the clocks (§4) and the debug path (§5).
4. **For every pin that leaves the board,** decide its protection (§6, §7). Use the absolute-maximum table: injection current, and voltage tolerance when powered and unpowered.
5. **Add the interfaces** (§8–§10) and the board input protection (§11).
6. **Run the checklist** (§12).

## 2. Supplies and decoupling

**Generic rule.** One ceramic of about 100 nF (X5R/X7R) at every supply pin, as close as possible, plus bulk capacitance per package. The analog supply and reference get their own filtered decoupling. Internal core-regulator pins get *exactly* the capacitance and ESR the datasheet specifies.

**Look up:** decoupling per pin; bulk; analog-supply filtering; core-regulator capacitor value, ESR and type; backup-domain (VBAT) handling.

| | STM32 (F4/G4) | TI TM4C | NXP LPC55 | NXP i.MX RT1050/60 |
|---|---|---|---|---|
| Per-pin | 100 nF per VDD [AN4488][AN5093] | 0.1 µF per supply pin [SPMA059][SPMA056] | 0.1 µF X7R per pin [AN13033] | e.g. VDD_SOC_IN 5 × 0.22 µF (0402) [RT-HDG] |
| Bulk | F4: ≥ 4.7 µF, typ 10 µF [AN4488] | 2–22 µF total for VDD + VDDA, X5R/X7R, not Z5U [SPMA059][SPMA056] | 10 µF [AN13033] | VDD_SOC_IN + 4.7 µF + 22 µF [RT-HDG] |
| Analog | VDDA 100 nF + 1 µF, optional ferrite from VDD; VREF+ 100 nF + 1 µF [AN4488][AN5093] | VDDA 0.01 µF + 1 µF when it is the ADC reference [SPMA059] | VDDA and VREFP each with bulk + 0.1 µF [AN13033] | VDDA_ADC_3P3 0.22 µF + 1 µF [RT-HDG] |
| Core regulator | F4 VCAP: 2 × 2.2 µF with ESR < 2 Ω (or 1 × 4.7 µF, < 1 Ω) [AN4488] | VDDC: two or more caps totalling 3.3–3.4 µF within the datasheet's max ESR [SPMA059][SPMA056] | VDD_PMU/VBAT_PMU: 22 µF + 100 nF + 47 pF [AN13033] | DC-DC: 4.7–10 µH inductor, about 33 µF total on DCDC_OUT + VDD_SOC_IN [RT-HDG] |

- **Backup domain.** STM32 VBAT without a battery: tie it to VDD with 100 nF [AN4488][AN5093]. TM4C123 shows a 51 Ω / 0.1 µF RC to meet its VBAT ramp limit [SPMA059].
- **AVR:** one cap per supply-pin pair; 100 nF on AVCC/AREF; AGND joined to GND at one point [AN2519].
- **Board level:** 10–100 µF electrolytic plus 0.1–1 µF ceramics near the MCU [AN1709].
- **Ferrite beads** (any vendor) lose most of their impedance under DC bias: up to 90 % of the inductance at 50 % of rated current. Design to about 20 % of the rated current, check the DC-bias curve, and damp the bead–capacitor resonance [ADI-FB].

## 3. Reset and boot selection

**Generic rule.**
1. Find out whether the reset pin is a plain input, or a **bidirectional open-drain** that the MCU itself pulls low on internal resets (POR, watchdog, faults). Never drive it with a push-pull output.
2. Add only the parts the vendor recommends; some families want a capacitor, others don't.
3. Bring reset to the debug header.
4. Find the **boot-selection mechanism**: a pin sampled at reset, option bytes or fuses. Give every boot pin a defined level, and make the bootloader-entry condition reachable on the board (test point or button).

**Look up:** reset pin type and internal pull-up; recommended capacitor (or "none"); POR/BOR thresholds; boot pins, option bytes and fuses.

- **Reset pin:**

  | Family | Reset recommendation |
  |---|---|
  | STM32 | Internal pull-up. Only a capacitor is recommended: 100 nF, can be reduced to 10 nF [AN4488][AN5093]. |
  | TI TM4C | RST must never float. Use a 0–100 kΩ pull-up to VDD or an RC; put 100 Ω in series with a reset switch [SPMA059][SPMA056]. |
  | NXP LPC55 | RESET has an internal pull-up and can be left unconnected if unused [AN13033]. |
  | NXP Kinetis | RESET_b is open-drain with an internal pull-up. It drives low during power-up (between V_POR and V_LVR) and on fault resets. NXP's Kinetis FAQ advises no external pull-up or capacitor on KL02 [NXP-KRST]. That is a community FAQ, so confirm in the part's reference manual. |
  | NXP i.MX RT | POR_B has an internal 100 kΩ pull-up to the SNVS domain. Any external pull-up goes to VDD_SNVS_IN, and an external reset IC must trip above 2.6 V [RT-HDG]. |
  | Microchip AVR | Pull-up ≥ 4.7 kΩ (≥ 10 kΩ with debugWIRE). **No capacitor with debugWIRE/PDI.** No internal ESD diode to VCC, so add one if HV programming is unused [AN2519]. |

- **Boot selection:**

  | Family | Boot selection |
  |---|---|
  | STM32 | BOOT0 must not float (10 kΩ pull-down in the G4 reference). On G4, the option bits nBOOT0/nSWBOOT0 can override the pin [AN4488][AN5093]. |
  | NXP LPC55 | ISP0 = PIO0_5: low at reset enters ISP. It has an internal pull-up by default [AN13033]. |
  | NXP i.MX RT | BOOT_MODE[1:0]: logic 1 through 10 kΩ (4.7 kΩ in noisy environments), with internal 100 kΩ pull-downs. BOOT_CFG pins must not float unless the boot fuses are programmed [RT-HDG]. |
  | TI TM4C, AVR | Boot behaviour is set by registers or fuses. See the datasheet or reference manual. |

- **Brown-out.** Many parts have an internal BOR that removes the need for an external supervisor [AN1709]. Check whether yours can be disabled. G4's can't [AN5093]. F4 uses PDR_ON with an external supervisor [AN4488].

## 4. Oscillators

**Generic rule (any Pierce crystal oscillator):**
- C_L = (C_L1·C_L2)/(C_L1 + C_L2) + C_stray. With equal capacitors, C_L1 = C_L2 = 2·(C_L − C_stray) *(derived)* [AN2867].
- Stray capacitance is typically a few pF. LPC55 quotes about 3 pF per pin [AN13033]. Sources differ on whether stray is counted as a total or per pin [AN2519][AN5093][SPMA059], so state your convention.
- Check **oscillation margin**: gain margin = g_m / g_mcrit, with g_mcrit = 4·ESR·(2πF)²·(C0 + C_L)². ST asks for > 5 (HSE) and > 3 (LSE) [AN2867]. Use the datasheet's g_m, or its maximum crystal ESR/C_L, for other vendors.
- Check **drive level**: DL = ESR·I²_rms ≤ the crystal's rating. Add a series resistor if needed, then recheck the margin [AN2867].
- **Placement.** Crystal and capacitors as close to the pins as possible, and no signal traces near or under the crystal [AN5093][AN1709][AN4747][AN13033]. Ask the crystal maker to evaluate the circuit on your PCB [AN13033].

**Look up:** the supported crystal frequency range, maximum ESR, recommended C_L, maximum drive level, whether a bias resistor is internal, and any approved-crystal list.

- **Crystal recommendations by family:**

  | Family | Crystal guidance |
  |---|---|
  | STM32 32 kHz LSE | Prefer low-C_L crystals: on F4 ≤ 7 pF, never 12.5 pF. Start-up takes 1–5 s. A probe disturbs it. Use ST's approved-crystal table [AN4488][AN2867]. |
  | TI TM4C | Crystals with C_L ≥ 18 pF, or a maximum drive below 200 µW, are not robust enough. Traces < 6 mm, never > 18 mm [SPMA059][SPMA056]. |
  | NXP i.MX RT 24 MHz | A crystal of about 80 Ω ESR rated for 250 µW is acceptable; bias XTALI with 2.2 MΩ to GND. |
  | NXP i.MX RT 32 kHz | No external bias resistor; reduce the load capacitors to account for parasitics [RT-HDG]. |
  | Microchip AVR | Never use unbalanced load capacitors. Tie unused XTAL pins to GND [AN2519]. |

## 5. Debug port

**Generic rule.** For Arm Cortex-M parts, use the standard 10-pin 1.27 mm connector:

| Pin | Signal |
|---|---|
| 1 | VTref |
| 2 | SWDIO/TMS |
| 3 | GND |
| 4 | SWCLK/TCK |
| 5 | GND |
| 6 | SWO/TDO |
| 7 | key (no pin) |
| 8 | NC/TDI |
| 9 | NC/TRST |
| 10 | nRESET |

The 20-pin Debug+ETM connector shares the first 10 pins [SEGGER][Keil].
- No series resistor on VTref.
- SWDIO pulled up and SWCLK in a defined state [SEGGER].
- Route reset to pin 10.

**Look up:** the internal pulls on the debug pins, the JTAG/SWD selection, and any debug pin that must not get external pulls.

| Family | Debug-pin notes |
|---|---|
| STM32 | Internal pull-up on SWDIO and pull-down on SWCLK [AN4488][AN5093]. |
| NXP LPC55 | Same internal pulls. Optional external 10 kΩ pulls for robustness [AN13033]. |
| NXP i.MX RT | SWD by default. JTAG_MOD to GND through 4.7 kΩ. **No external pulls on JTAG_TDO** [RT-HDG]. |
| TI TM4C | On debug traces longer than 51 mm, add a TCK pull-up ≥ 10 kΩ or pull-down ≤ 1 kΩ [SPMA059]. |

## 6. GPIO and connector protection

**Generic rule.** Every pin that leaves the board needs, as appropriate:
- a series resistor and/or RC;
- a clamp or TVS at the connector;
- a check that a fault can't push more than the datasheet's **injection current** into the pin;
- a check that nothing drives the pin while the MCU is unpowered (back-powering through the clamp diodes) [AN1709].

**Look up:** absolute max V_IN (powered and unpowered); injected current per pin and in total; which pins are 5 V tolerant and under what conditions; the pin types; the errata for pins that can't be GPIO.

- **Injection and tolerance:**

  | Family | Limits |
  |---|---|
  | STM32 | −5 mA per pin; no positive injection on 5 V-tolerant pins; about 25 mA total. FT pins are 5 V tolerant only as inputs (≤ VDD + 3.6 V, ≤ 5.5 V), take **≤ 3.6 V when VDD = 0**, and are not tolerant in analog mode [AN4899]. |
  | TI TM4C129 | GPIOs are **not** 5 V tolerant, except PB1 (USB0VBUS) [SPMA056]. |

- **Series resistors (TM4C guidance, generally applicable):**
  - 10–33 Ω between boards;
  - 50–150 Ω on cable/connector lines;
  - output termination 0/10/22/33 Ω within 12.7 mm of the pin [SPMA059][SPMA056].
- **Input RC:** 100 Ω–1 kΩ plus 1 nF–0.1 µF [AN4747].
- **Clamps.** Low-pass filters plus clamp diodes are usually enough [AN1709]. For signals above the rail, use a series R with a Schottky to the rail, or a Zener [AN4899].
- **Unused pins never float.** Use the vendor's preferred state:

  | Family | Unused-pin state |
  |---|---|
  | STM32 | Analog mode (lowest current) or push-pull low [AN4899][AN4488] |
  | NXP LPC55 | GPIO output low with the pull disabled [AN13033] |
  | NXP Kinetis L | Output low [AN4747] |
  | TI TM4C | Per pin, from the datasheet's signal tables [SPMA056] |
  | Microchip AVR | Unused XTAL pins to GND [AN2519] |

  Don't tie unused pins straight to a rail [AN4747].
- **ESD on every connector signal,** placed at the connector [SPMA059][AN4879].

## 7. ESD/EMC levels and TVS selection

- **IEC 61000-4-2 levels 1–4:** contact 2/4/6/8 kV, air 2/4/8/15 kV.
- **IEC 61000-4-4 EFT:** power 0.5/1/2/4 kV; I/O 0.25/0.5/1/2 kV.
- **IEC 61000-4-5 surge:** 1.2/50 µs voltage, 8/20 µs current, 2/12/42 Ω source. At 2 kV that is 1000 A into 2 Ω [SLVA711].
- **TVS selection:**
  - working voltage ≥ the signal swing in both directions;
  - clamp voltage below the protected pin's limit;
  - I_PP above the test level;
  - unidirectional for signals that never go negative, bidirectional otherwise.
  
  8 kV IEC ≈ 16 A TLP for comparing clamp curves [SSZB130][SLVA711].
- **Capacitance budget.** USB 2.0 needs low-capacitance parts; LVDS < 3 pF [SSZB130]. Example classes: about 12 pF for slow I/O, 0.45 pF for fast I/O [SPMA059].

## 8. USB full-speed device

**Generic rule:**
- ESD array at the connector (D+/D−, and VBUS);
- D+/D− as a 90 Ω differential pair [SPMA056][AN4879][RT-HDG];
- VBUS sensing that respects the pin's tolerance, also when the MCU is unpowered;
- VBUS capacitance within the spec limit;
- check whether the PHY integrates the series resistors and the D+ pull-up.

**Look up:** integrated series resistors and pull-up; the VBUS pin's voltage rating; the reference schematic.

| Family | USB notes |
|---|---|
| STM32 | Series resistors and the 1.5 kΩ pull-up are internal on most parts. VBUS divider: 33 kΩ to VBUS, 82 kΩ to GND [AN4879]. VBUS ≤ 4.7 µF (OTG) [AN4879]. |
| TI TM4C | VBUS goes to the 5 V-tolerant PB1 through 100 Ω [SPMA059][SPMA056]. |
| NXP i.MX RT | VBUS is a 4.4–5.5 V input with 1 µF / 10 V decoupling. Leave unused USB pads unconnected [RT-HDG]. |

- **USB-C sink:**
  - Rd = 5.1 kΩ on each CC pin;
  - CC protection;
  - VBUS capacitance about 2.2 µF in ST's reference [AN5225].

## 9. I2C and SPI

- **I2C pull-ups:**
  - R_p,min = (V_CC − 0.4 V)/3 mA.
  - R_p,max = t_r/(0.8473·C_b), with t_r = 1000/300/120 ns (Standard/Fast/Fast+) and C_b ≤ 400/400/550 pF.
  - Example: Fast mode, 200 pF, 3.3 V → 967 Ω … 1.77 kΩ [SLVA689A].
- **SPI:** source series termination, 0–33 Ω [SPMA059]; 30–50 Ω on long fast lines [AN1709].

## 10. CAN and RS-485

- **CAN:**
  - 120 Ω at both ends, or split termination: 2 × 60 Ω ±1 % plus 4.7 nF.
  - Stubs ≤ 0.3 m at 1 Mbps [SLLA270].
  - Choose the TVS against the transceiver's bus-fault rating.
- **RS-485:**
  - 120 Ω at each end; −7…+12 V common mode; ≤ 32 unit loads.
  - Fail-safe bias for V_AB > 200 mV when idle (≈ 523 Ω at 5 V with 120 Ω termination) [SLLA272D].
  - Asymmetric TVS such as SM712. Its 75 pF counts as bus load [SM712].

## 11. Loads, user interface, board input

- **Relay and solenoid coils.** A 12 V coil can produce 1,000–1,500 V at turn-off. A diode alone slows the release; diode + Zener, or a bidirectional TVS, releases fast. RC snubbers aren't recommended [TE-13C3311].
- **Buttons and reset switches:** series resistor (e.g. 100 Ω) plus an input RC. ESD on every user-touchable or connector part. Keep traces and mounting holes off the board edge [SPMA059][AN4747][AN2519].
- **Reverse polarity,** in order of increasing efficiency [SLVA139]:
  1. series diode or Schottky;
  2. high-side PMOS;
  3. low-side NMOS.
  
  The FETs drop only I·R_DS(on). Clamp V_GS per the FET's rating.
- **Sequencing.** No I/O is driven while the MCU is unpowered beyond its unpowered limits [AN1709][AN4899].

## 12. Review checklist

- [ ] Family hardware design guide, datasheet, errata and eval-board schematic in hand (§0).
- [ ] Every power pin with its capacitors; core-regulator parts exactly per datasheet (value, ESR, inductor); analog supply and reference filtered; backup domain handled.
- [ ] Reset: pin type known (input vs open-drain bidirectional); vendor-recommended parts only; on the debug header. Boot selection defined; bootloader entry reachable.
- [ ] Crystal: C_L math with a stated stray convention; margin and drive level vs the datasheet; bias resistor only if the part needs one.
- [ ] Debug: standard connector; pulls per vendor (and none where forbidden).
- [ ] Every off-board signal: series R/RC, clamp/TVS at the connector, injection and unpowered limits respected; unused pins in the vendor's preferred state.
- [ ] TVS: working voltage, clamp vs pin limit, I_PP vs the IEC level, capacitance, polarity.
- [ ] USB: ESD, 90 Ω pair, VBUS sensing within the pin rating, integrated vs external series R, VBUS capacitance.
- [ ] I2C, SPI, CAN and RS-485 per §9–§10. Coils suppressed; reverse-polarity protection on the board input.

## 13. References

**Vendor hardware design guides**
- **[AN4488]** ST, *Getting started with STM32F4xxxx MCU hardware development*.
- **[AN5093]** ST, *Getting started with STM32G4 Series hardware development boards*.
- **[AN2867]** ST, *Guidelines for oscillator design on STM8AF/AL/S and STM32 MCUs/MPUs*.
- **[AN1709]** ST, *EMC design guide for STM8, STM32 and legacy MCUs*.
- **[AN4879]** ST, *Introduction to USB hardware and PCB guidelines using STM32 MCUs*.
- **[AN4899]** ST, *Guidelines for GPIO hardware settings and low-power consumption on STM32 MCUs*.
- **[AN5225]** ST, *Introduction to USB Type-C Power Delivery for STM32 MCUs and MPUs*.
- **[SPMA059]** TI, *System Design Guidelines for the TM4C123x Family of Tiva C Series Microcontrollers*.
- **[SPMA056]** TI, *System Design Guidelines for the TM4C129x Family of Tiva C Series Microcontrollers*.
- **[AN13033]** NXP, *Hardware Design Guidelines for LPC55(S)xx Microcontrollers*.
- **[RT-HDG]** NXP, *Hardware Development Guide for the MIMXRT1050/MIMXRT1060 Processor* (MIMXRT105060HDUG).
- **[AN4747]** NXP, *EMC Design Tips for Kinetis L Family*.
- **[NXP-KRST]** NXP Community, Kinetis Systems Engineering FAQ, *Reset pin recommendations for Kinetis devices*.
- **[AN2519]** Microchip, *AVR Microcontroller Hardware Design Considerations*.

**Interfaces, ESD and components**
- **[SSZB130]** TI, *System-Level ESD Protection Guide*.
- **[SLVA711]** TI, *IEC 61000-4-x Tests for TI's Protection Devices*.
- **[SLVA689A]** TI, *I2C Bus Pullup Resistor Calculation*.
- **[SLLA270]** TI, *Controller Area Network Physical Layer Requirements*.
- **[SLLA272D]** TI, *The RS-485 Design Guide*.
- **[SLVA139]** TI, *Reverse Current/Battery Protection Circuits*.
- **[ADI-FB]** ADI Analog Dialogue 50-1, *Ferrite Beads Demystified*.
- **[TE-13C3311]** TE Connectivity, *The Application of Relay Coil Suppression with DC Relays*.
- **[SM712]** Littelfuse, SM712 datasheet.
- **[SEGGER]** SEGGER Knowledge Base, *9-pin JTAG/SWD connector*.
- **[Keil]** Arm Keil, *ULINKpro User's Guide: Connectors*.
