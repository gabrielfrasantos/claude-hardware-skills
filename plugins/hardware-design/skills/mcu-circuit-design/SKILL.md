---
name: mcu-circuit-design
description: Design or review the schematic around a microcontroller (supplies, decoupling, reset/boot, clocks, debug, GPIO and connector protection, ESD/TVS, USB, I2C, SPI, CAN, RS-485, relays) using vendor-verified rules.
---

# MCU circuit design (schematic level)

Use this skill when you design or review everything around a microcontroller:
- power pins and decoupling;
- reset and boot;
- oscillators;
- the debug port;
- GPIO and connector protection;
- ESD/EMC;
- the usual interfaces (USB, I2C, SPI, CAN, RS-485);
- inductive loads and the board's input protection.

Every rule is traced to a vendor app note or datasheet in §13, with its key in [brackets]. **The MCU's own datasheet and its family "getting started with hardware development" app note win over this skill.** Read them first for pin-specific values (VCAP, VDDA, BOOT, internal pull-ups).

## 1. Workflow

1. **Collect the documents:**
   - MCU datasheet;
   - reference manual (boot and option bytes);
   - the family's hardware-development app note (e.g. ST AN4488 for F4, AN5093 for G4; TI SPMA059 for TM4C123);
   - the oscillator guide (ST AN2867);
   - the errata.
2. **Draw the power-pin map:** every VDD/VSS, VDDA/VSSA, VREF+, VBAT, VCAP/VDDC and VDDUSB pin, with its capacitors (§2).
3. **Define the reset/boot/debug path** (§3, §5) and the clocks (§4).
4. **For every pin that leaves the board**, decide its protection (§6, §7) and its EMC class from the environment (§7).
5. **Add the interfaces** (§8–§10) and the board input protection (§11).
6. **Run the checklist** (§12).

## 2. Supplies and decoupling

- **One 100 nF ceramic at every VDD pin**, placed at the pin [AN4488][AN5093]. TM4C uses 0.1 µF per VDD/GND pair, with at least one on each side of the package [SPMA059].
- **Bulk per package:** STM32F4 min 4.7 µF, typ 10 µF [AN4488]. The G4 app note is inconsistent: its text says about 10 µF and its table says 4.7 µF [AN5093]. TM4C uses 2–22 µF total, X5R/X7R, not Z5U [SPMA059]. At board level: 10–100 µF electrolytics plus 0.1–1 µF ceramics very close to the supply pins [AN1709].
- **VDDA:** 100 nF + 1 µF. It may be fed from VDD through a ferrite bead for EMC, or connected directly [AN4488][AN5093]. TM4C uses 0.01 µF + 1 µF when VDDA is the ADC reference [SPMA059].
- **VREF+:** 100 nF + 1 µF to VSSA [AN4488][AN5093].
- **VCAP / core-regulator pins** have strict values and ESR. Example, F4: 2 × 2.2 µF with ESR < 2 Ω, or 1 × 4.7 µF with ESR < 1 Ω on single-VCAP packages [AN4488]. TM4C VDDC: about 3.3 µF total within the datasheet's maximum ESR, including vias and traces [SPMA059]. **Always take these from the datasheet.**
- **VBAT** without a battery: tie it to VDD with 100 nF [AN4488][AN5093]. TM4C shows a 51 Ω / 0.1 µF RC to meet its VBAT ramp limit [SPMA059].
- **AVR:** one cap per supply pin pair; 100 nF on AVCC/AREF; AGND joined to GND at a single point [AN2519].
- **Ferrite beads lose most of their impedance under DC bias.** At 50 % of rated current the inductance can drop by up to 90 %. Design to about 20 % of the rated current, check the DC-bias curves, and damp the bead–capacitor resonance with a series R or a damped bulk capacitor [ADI-FB].

## 3. Reset, boot, brown-out

- **STM32 NRST:** only a capacitor to GND is recommended, 100 nF, which can be reduced to 10 nF. The pull-up is internal; take its value from the datasheet. Bring NRST to the debug header [AN4488][AN5093].
- **TM4C RST:** never floating. Use a pull-up to VDD, and put 100 Ω in series with a reset button [SPMA059].
- **AVR RESET:**
  - pull-up ≥ 4.7 kΩ (≥ 10 kΩ with debugWIRE);
  - **no capacitor with debugWIRE/PDI**;
  - no internal ESD diode to VCC (because of HV programming), so add an external diode if HVPP is unused, and a Zener in noisy environments [AN2519].
- **Boot pins must never float.** Use an STM32 BOOT0 pull-down (10 kΩ in the G4 reference). On G4, the option bits nBOOT0/nSWBOOT0 can override the pin, and the pin is resampled on wake from Standby [AN4488][AN5093].
- **Brown-out.**
  - The internal BOR lets many parts run without an external reset circuit [AN1709].
  - G4 has five option-byte thresholds and the BOR can't be disabled [AN5093].
  - On F4, an external supervisor goes on PDR_ON, with BOR disabled [AN4488].

## 4. Oscillators

- **Load capacitance:** C_L = (C_L1·C_L2)/(C_L1 + C_L2) + C_s [AN2867]. With equal caps, C_L1 = C_L2 = 2·(C_L − C_s) *(derived)*. The sources differ on whether C_s is counted as a total or per pin (typically 2–7 pF) [AN2519][AN5093][SPMA059]. Measure or estimate the stray capacitance of your layout, and state which convention you used.
- **Gain margin** = g_m / g_mcrit, with g_mcrit = 4·ESR·(2πF)²·(C0 + C_L)².
  - Target **> 5 for HSE** and **> 3 for LSE** [AN2867, Rev 25].
  - The same revision also says "bigger than 5" without the split. Use 5 when in doubt.
  - Use the crystal's maximum ESR.
- **Drive level** DL = ESR·I_Q,rms² must not exceed the crystal's rating. If it would, add R_ext ≈ 1/(2πF·C_L2), then recheck the gain margin [AN2867]. G4 reference: 24 MHz with 390 Ω and 20 pF [AN5093].
- **32.768 kHz LSE:**
  - Prefer low-C_L crystals. On F4, use C_L ≤ 7 pF and never 12.5 pF [AN4488].
  - 12.5 pF needs more drive. Start-up takes 1–5 s. A probe on the LSE pins disturbs it.
  - Choose from the vendor's approved-crystal table [AN2867].
  - TM4C considers crystals with C_L ≥ 18 pF, or a max drive below 200 µW, not robust enough [SPMA059].
- **Placement.**
  - Put the crystal and its caps as close to the pins as possible, with no signal traces near the crystal circuit [AN5093][AN1709][AN4747].
  - TM4C: oscillator traces ideally < 6 mm, never > 18 mm [SPMA059].
  - Never use unbalanced load caps [AN2519].

## 5. Debug port

- **Arm Cortex 10-pin 1.27 mm connector** (pin 7 removed as the key):

  | Pin | Signal |
  |---|---|
  | 1 | VTref |
  | 2 | SWDIO/TMS |
  | 3 | GND |
  | 4 | SWCLK/TCK |
  | 5 | GND |
  | 6 | SWO/TDO |
  | 8 | NC/TDI |
  | 9 | NC/TRST |
  | 10 | nRESET |

  The 20-pin Debug+ETM connector shares the first 10 pins [SEGGER][Keil].
- **No series resistor on VTref.** Pull SWDIO up, and hold SWCLK in a defined state [SEGGER]. STM32 has internal pull-up on SWDIO and pull-down on SWCLK, and JTAG inputs must not float [AN4488][AN5093]. TM4C: for long traces (> 51 mm), use a TCK pull-up ≥ 10 kΩ or pull-down ≤ 1 kΩ [SPMA059].
- No verified source requires series resistors on SWD lines. SWO is optional (F4: PB3) [SEGGER][AN4488].

## 6. GPIO and connector protection

- **Injection current (STM32):**
  - −5 mA maximum per pin;
  - positive injection not allowed on TT/FT pins;
  - about 25 mA total per device.
  
  Check the datasheet [AN4899].
- **5 V-tolerant (FT) pins** are tolerant only in input mode, with V_IN ≤ VDD + 3.6 V and ≤ 5.5 V. **With VDD = 0, they take ≤ 3.6 V.** They are not tolerant with the analog function enabled [AN4899]. A pin driven while the MCU is unpowered back-powers it through the clamp diode [AN1709].
- **Series resistors.**
  - TM4C: 10–33 Ω between boards and 50–150 Ω on cable/connector lines for ESD.
  - 0–33 Ω source termination on fast outputs, within 12.7 mm of the pin [SPMA059].
  - Input RC filter: 100 Ω–1 kΩ plus 1 nF–0.1 µF [AN4747].
- **Clamps.** Low-pass filters plus clamp diodes are usually enough [AN1709]. For signals above the rail, use a series R with a Schottky to the rail, or a Zener [AN4899].
- **Unused pins.** Never leave them floating. Options: analog mode (lowest current), push-pull low, or 10 kΩ pull-downs; don't tie them straight to a rail [AN4899][AN1709][AN4747][AN4488]. Unused AVR XTAL pins go to GND [AN2519]. Read the errata for pins that can't be GPIO (e.g. TM4C TCK/PC0) [SPMA059].
- **Every signal on a connector gets ESD protection** [SPMA059]. Put it as close to the connector as possible [AN4879][SPMA059].

## 7. ESD/EMC levels and TVS selection

- **IEC 61000-4-2 levels 1–4:** contact 2/4/6/8 kV, air 2/4/8/15 kV [SLVA711].
- **IEC 61000-4-4 EFT:** power ports 0.5/1/2/4 kV, I/O ports 0.25/0.5/1/2 kV [SLVA711].
- **IEC 61000-4-5 surge:** 1.2/50 µs open-circuit voltage, 8/20 µs short-circuit current, 2/12/42 Ω source. At 2 kV that is 1000 A into 2 Ω, or 48 A into 42 Ω [SLVA711].
- **TVS selection:**
  - **working voltage** ≥ the signal's swing in both directions;
  - **clamp voltage** below what the protected pin tolerates;
  - **I_PP** above the test level;
  - unidirectional for signals that never go negative, bidirectional otherwise [SSZB130][SLVA711].
  
  An 8 kV IEC strike corresponds to about 16 A TLP for comparing clamp curves [SSZB130].
- **Capacitance budget:** USB 2.0 needs "low-capacitance" parts; high-speed lines need sub-pF to a few pF (LVDS < 3 pF) [SSZB130]. Example classes: 12 pF for slow lines, 0.45 pF for fast ones [SPMA059].

## 8. USB full-speed device

- **ESD:** a 2-line array on D+/D− and a TVS on VBUS, at the connector (e.g. USBLC6-2SC6 and ESDA7P60-1U1M) [AN4879].
- **No series resistors on STM32 USB FS**; the impedance is managed internally. D+ needs 1.5 kΩ, internal on most parts [AN4879].
- **VBUS sensing is mandatory when self-powered.** STM32 divider: 33 kΩ to VBUS, 82 kΩ to GND, keeping the pin < 4 V and inside the VDD = 0 limit [AN4879][AN4899]. TM4C feeds VBUS to a 5 V fail-safe pin through 100 Ω [SPMA059]. That works only on such a pin.
- **VBUS capacitance:** ≤ 4.7 µF (OTG) [AN4879]; Type-C reference designs use 2.2 µF [AN5225]. VDDUSB takes 100 nF + 1 µF [AN4879].
- **USB-C sink:** Rd = 5.1 kΩ on **each** CC pin. Use the dead-battery pins where present, add CC protection (e.g. TCPP01-M12), and put 390 pF on each CC line in ST's reference design [AN5225].
- **Routing:** D+/D− as a 90 Ω ±10 % differential pair, length-matched, ≤ 30 cm [SPMA059][AN4879].

## 9. I2C and SPI

- **I2C pull-ups:**
  - R_p,min = (V_CC − V_OL,max)/I_OL, with V_OL = 0.4 V at 3 mA.
  - R_p,max = t_r / (0.8473·C_b), with t_r = 1000/300/120 ns for Standard/Fast/Fast+ and C_b ≤ 400/400/550 pF.
  - Example: Fast mode, 200 pF, 3.3 V → 967 Ω … 1.77 kΩ [SLVA689A].
- **SPI:** series termination at the source, 0–33 Ω [SPMA059], 30–50 Ω on long fast lines [AN1709]. For AVR ISP sharing, use about 330 Ω to limit contention current [AN2519].

## 10. CAN and RS-485

- **CAN:**
  - 120 Ω at both ends. Or split termination: 2 × 60 Ω ±1 % plus C_L = 4.7 nF to GND, with the resistors sized for a short to the battery voltage [SLLA270].
  - Stubs ≤ 0.3 m at 1 Mbps. A common-mode choke is optional [SLLA270].
  - Pick a CAN-rated TVS against the transceiver's bus-fault rating.
- **RS-485:**
  - 120 Ω at each end; common-mode range −7…+12 V; ≤ 32 unit loads [SLLA272D].
  - **Fail-safe biasing:** keep V_AB > 200 mV plus noise when idle. Example: 5 V, 120 Ω → bias resistors ≈ 523 Ω. Transceivers with internal fail-safe leave only about 10 mV of noise margin [SLLA272D].
  - **TVS:** asymmetric −7/+12 V parts such as SM712 (clamp 19/31 V at 19 A). Their 75 pF counts as bus loading [SM712].

## 11. Loads, user interface, board input

- **Relay and solenoid coils.** A 12 V coil can produce 1,000–1,500 V at turn-off. A plain diode is safe but slows the release, and can cause contact tack-welding in some relays. Diode + Zener, or a bidirectional TVS, releases fast. RC snubbers aren't recommended [TE-13C3311]. Choose by contact-life needs.
- **Buttons and reset switches:** put a series resistor in the line (100 Ω on TM4C) and an input RC (§6) [AN2519][SPMA059][AN4747]. Every front-panel part on a connector or user surface gets ESD protection. Keep traces and mounting holes off the board edge [SPMA059][AN4747].
- **Reverse polarity** on the board input, in order of increasing efficiency [SLVA139]:
  1. series diode (≈ 0.6 V drop) or Schottky (lower drop);
  2. high-side PMOS with its body diode in the forward direction;
  3. low-side NMOS.
  
  The FETs drop only I·R_DS(on). Clamp V_GS per the FET's rating.
- **Sequencing:** no I/O may be driven while the MCU is unpowered beyond the VDD = 0 limits. Otherwise it is back-powered through the clamps [AN1709][AN4899].

## 12. Review checklist

- [ ] Every power pin listed with its capacitors; VCAP/VDDC values and ESR from the datasheet; VBAT handled.
- [ ] VDDA/VREF+ filtered; ferrites sized at ≤ 20 % of rated current with DC-bias curves checked; resonance damped.
- [ ] NRST/RST per family (cap or no cap), on the debug header; BOOT pins defined; brown-out strategy chosen.
- [ ] Crystal: C_L math with a stated stray convention; gain margin > 5 (HSE) / > 3 (LSE) at max ESR; drive level within rating (R_ext if needed); approved LSE crystal.
- [ ] Debug: Cortex 10-pin pinout, VTref with no series R, SWDIO pulled up, SWCLK defined.
- [ ] Every off-board signal: series R and/or RC, clamp or TVS at the connector, injection current within limits, no back-powering, unused pins defined.
- [ ] TVS parts: working voltage, clamp vs pin max, I_PP vs the IEC level, capacitance vs signal speed, polarity.
- [ ] USB: ESD at the connector, VBUS divider/sensing, Rd 5.1 kΩ on both CC, VBUS capacitance limit, 90 Ω pair.
- [ ] I2C pull-ups computed for bus capacitance and mode; SPI source termination on fast lines.
- [ ] CAN/RS-485 termination, fail-safe bias and TVS per bus; stub length.
- [ ] Inductive loads suppressed; switches series-protected; reverse-polarity protection on the board input.

## 13. References

- **[AN4488]** ST, *Getting started with STM32F4xxxx MCU hardware development* (Rev 7).
- **[AN5093]** ST, *Getting started with STM32G4 Series hardware development boards* (Rev 2).
- **[AN2867]** ST, *Guidelines for oscillator design on STM8AF/AL/S and STM32 MCUs/MPUs* (Rev 25).
- **[AN1709]** ST, *EMC design guide for STM8, STM32 and legacy MCUs* (Rev 5).
- **[AN4879]** ST, *Introduction to USB hardware and PCB guidelines using STM32 MCUs* (Rev 12).
- **[AN4899]** ST, *Guidelines for GPIO hardware settings and low-power consumption on STM32 MCUs* (Rev 4).
- **[AN5225]** ST, *Introduction to USB Type-C Power Delivery for STM32 MCUs and MPUs* (Rev 7).
- **[SPMA059]** TI, *System Design Guidelines for the TM4C123x Family of Tiva C Series Microcontrollers*.
- **[SSZB130]** TI, *System-Level ESD Protection Guide*.
- **[SLVA711]** TI, *IEC 61000-4-x Tests for TI's Protection Devices*.
- **[SLVA689A]** TI, *I2C Bus Pullup Resistor Calculation*.
- **[SLLA270]** TI, *Controller Area Network Physical Layer Requirements*.
- **[SLLA272D]** TI, *The RS-485 Design Guide*.
- **[SLVA139]** TI, *Reverse Current/Battery Protection Circuits*.
- **[AN2519]** Microchip, *AVR Microcontroller Hardware Design Considerations*.
- **[AN4747]** NXP, *EMC Design Tips for Kinetis L Family*.
- **[ADI-FB]** ADI Analog Dialogue 50-1, *Ferrite Beads Demystified*.
- **[TE-13C3311]** TE Connectivity, *The Application of Relay Coil Suppression with DC Relays*.
- **[SM712]** Littelfuse, SM712 datasheet.
- **[SEGGER]** SEGGER Knowledge Base, *9-pin JTAG/SWD connector*.
- **[Keil]** Arm Keil, *ULINKpro User's Guide: Connectors*.
