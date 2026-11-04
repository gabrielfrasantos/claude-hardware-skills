---
name: analog-circuit-design
description: Design or review analog schematics (op amps, references, ADC drivers, filters, in-amps, current sense) for protection, noise, stability, accuracy and component choice, using vendor-verified rules.
---

# Analog circuit design (schematic level)

Use this skill when you design or review the analog part of a schematic:
- op-amp stages;
- voltage references;
- ADC drivers;
- filters;
- instrumentation, difference and current-sense amplifiers;
- input protection;
- the error and noise budget.

Every rule below is traced to a vendor tutorial, app note or datasheet in §11, with its key in [brackets]. When a part's datasheet says otherwise, **the datasheet wins**. Values marked *(derived)* are arithmetic from the cited formulas.

## 1. Workflow

1. **Write the requirement as numbers:**
   - signal range;
   - source impedance;
   - bandwidth;
   - accuracy (offset, gain, drift over temperature);
   - noise (rms over a stated bandwidth, or p-p in 0.1–10 Hz);
   - load;
   - supply rails;
   - fault voltages the input must survive.
2. **Pick the topology and the gain/noise-gain split.** Noise and bandwidth follow noise gain (1 + R2/R1), not signal gain [MT-033].
3. **Select parts against the checklist** (§2), then budget the errors (§9).
4. **Add protection** (§5), filtering (§6) and decoupling (§8).
5. **Check stability** for every stage that drives a capacitance or sees one at its input (§3). Confirm in SPICE (see the `circuit-simulation` skill).
6. **Record the budget table** (§9) in the design notes.

## 2. Op-amp selection checklist

- **Input common-mode range.** PNP, PMOS and N-JFET inputs typically work from about 200 mV below the negative rail to 1–2 V below the positive rail [MT-035].
- **Rail-to-rail input crossover.** At the NPN/PNP handover (e.g. about 1 V below V+ in some parts), offset becomes the average of the two pairs and bias current can change polarity and magnitude. Keep the signal out of that region, especially in non-inverting stages, or pick a part without crossover [MT-035].
- **Output swing depends on load.** Bipolar rail-to-rail outputs reach 5–10 mV from the rail at light load, but several hundred mV at tens of mA (500 mV at 50 mA in the example). Emitter-follower outputs on 5 V may only reach +1…+4 V. Check the swing at *your* load [MT-035][SLOA030A].
- **Bandwidth.** Closed-loop bandwidth = GBW / noise gain, with a margin of at least 5× [MT-033]. For large signals, check the **full-power bandwidth** FPBW = SR / (2π·A_peak). A 153 MHz part with 25 V/µs has only 4 MHz FPBW at 1 V peak [MT-056].
- **Offset and bias current.** The error is I_B × source resistance. Any series protection resistor adds the same way, and clamp-diode leakage adds to I_B [MT-036].
- **Phase reversal.** Some inputs reverse the output when driven past their range, most likely in a unity-gain follower. A series R_LIMIT often prevents it; check the datasheet [MT-036].
- **Differential input limits.** Bipolar inputs break down at about 7 V differential. Parts with back-to-back input diodes typically have an absolute maximum of ±0.7 V differential, which matters for comparators-in-disguise and for the slewing inputs of followers [MT-036].
- **Decompensated parts** are stable only above their specified minimum gain (e.g. OP37: G ≥ 5) [MT-033][AAE-32].

## 3. Stability

- A capacitive load forms a pole with the op amp's open-loop output resistance [AAE-32]. Aim for **≥ 45° phase margin**, 60° preferred (about 23 % and 9 % overshoot) [TIDU032C].
- **Isolation resistor (out of loop).** 5–50 Ω is usually enough, with its zero at least a decade below the crossover [AAE-32]. TI's method puts the Riso–CL zero where the open-loop gain is 20 dB: Riso = 1/(2π·fz·CL), e.g. 23.7 Ω for 0.1 µF. Smaller Riso means less phase margin, and the DC drop across Riso is a load-dependent error [TIDU032C].
- **In-loop compensation.** A small Rx in series to the load, plus Cf from the output pin back to the inverting input, removes the DC error of an out-of-loop Riso (e.g. Rx = 2 Ω, Cf = 2 pF for 1 nF at G = 10) [AAE-32].
- **Input capacitance** (photodiode/transimpedance stages, large feedback R). For about 45° use C_f = √(C_in / (2π·R_f·f_u)); doubling C_f gives about 65° [MT-059]. In a general inverting stage, C_f = (R1/R2)·C_in gives 90° [AAE-32].
- **Output snubber** for a fixed large CL: C_s = 3/(2π·f_p·R_s) at the peaking frequency [AAE-32].
- An **ADC driver** with its charge-bucket RC needs > 40° margin, checked in SPICE [SBAS788A].

## 4. Voltage references

- **Series vs shunt.** A series reference draws a fixed supply current and needs no resistor. A shunt (2-terminal) reference suits negative or very high supply voltages, but its resistor must keep the current in range over the supply and load extremes [ADI-VREF][MT-087].
- **Error terms to budget:**
  - initial accuracy;
  - tempco: the box method gives min/max voltage only, so budget TC × span [ADI-VREF];
  - **long-term drift**, which grows with √t: 1 year ≈ 3 × the 1000 h figure, 10 years ≈ 9 × [MT-087];
  - **thermal hysteresis**, which is independent of TC and limits the value of a one-time calibration [ADI-VREF];
  - load regulation (≤ 70 ppm/mA is good) and line regulation (typically 25 ppm/V) [MT-087].
- **Noise.** 0.1–10 Hz noise is specified in µV p-p or rms. A noise-reduction pin capacitor forms a filter with an internal resistor (e.g. 1 µF → 40 Hz), but that doesn't filter the output buffer's noise [MT-087].
- **Capacitors.** Some references *need* an output capacitor for stability, and some are unstable with one; follow the datasheet. Always decouple the input. Decouple converter reference pins with ≥ 0.1 µF, plus 5–50 µF if the supply has low-frequency ripple [MT-087].
- **Buffering.** Buffer the reference when it drives a dynamic load (ADC/DAC reference pins). For the best precision, use Kelvin sensing at the load [MT-087].
- **Mechanical stress.** The mounting method matters more than the package; smaller footprints see less board-bending stress [ADI-VREF].

## 5. Input protection and EMI

- **Limit fault current.** Unless the datasheet says otherwise, limit op-amp input fault current to **≤ 5 mA**: R_LIMIT ≥ (V_fault − V_rail)/5 mA, e.g. ≥ 20 kΩ for 100 V. R_LIMIT adds Johnson noise and an I_B × R offset [MT-036].
- **External clamps** to the rails, typically Schottky for their lower forward voltage, take the fault current instead of the internal diodes. Their leakage adds to I_B, so choose low-leakage parts for high-impedance inputs. Make sure the rail can absorb the injected current [MT-036].
- **RF rectification.** Out-of-band RF shifts the op amp's offset, and the shift grows with the square of the RF amplitude (doubling RF quadruples ΔVos). Compare parts by their **EMIRR** (dB, 10 MHz–6 GHz) [SBOA128A].
- **In-amp input RC filter.**
  - Common-mode corner = 1/(2π·R·C_cm); differential corner ≈ 1/(4π·R·C_diff).
  - Make C_diff ≥ 10 × C_cm, match the C_cm capacitors within 5 %, and use 1 % metal-film resistors. Mismatch turns common-mode noise into differential.
  - Example: 4.02 kΩ, 1 nF, 47 nF ≈ 400 Hz differential.
  - In-amps have almost no CMRR above about 20 kHz, so the filter is what rejects RF [MT-070].

## 6. ADC drivers and filters

- **Charge-bucket capacitor** at the SAR input: C_FLT ≥ 20 × the ADC sampling capacitance, C0G/NP0 [SBAS788A].
- **R_FLT.** A larger value is more stable but adds distortion. Verify stability (> 40°) and settling [SBAS788A].
- **Settling to ½ LSB:** A(t) ≥ 1 − 1/2^(N+1) [SBAA173A]. For a single pole, t ≥ (N+1)·ln2·τ: 12 bit ≈ 9.0 τ, 16 bit ≈ 11.8 τ, 18 bit ≈ 13.2 τ *(derived)*. It must fit in the acquisition time.
- **Driver noise** should be below 20 % of the ADC's input-referred noise [SBAS788A].
- **Active filters.**
  - MFB is less sensitive to component variation and behaves better at high frequency.
  - Unity-gain Sallen-Key has no gain sensitivity, but its stopband is limited by the op amp's output impedance; an output RC helps.
  - Use C0G capacitors, 1 % resistors in the hundreds of Ω to few kΩ range, and no capacitor below 10 pF [SLOA049D].

## 7. Difference, instrumentation and current-sense amplifiers

- **Discrete difference-amp CMRR** is set by resistor matching: about 34 dB with 1 % parts and 54 dB with 0.1 % at unity gain. A 0.5 pF imbalance costs 6 dB of CMR at 10 kHz. Monolithic difference amps do far better [ADI-DIFF].
- **In-amp common-mode range is not a single number.** Check the operating point (V_CM, V_DIFF·G, V_REF, the rails) inside the part's **diamond plot**. Use the vendor tool where one exists [AN-1401].
- **Current-sense amplifier input filters** cause gain error through bias-current mismatch: INA240 example 0.17 % at 5 Ω, 3.2 % at 100 Ω. Keep the series resistors ≤ 10 Ω or omit the filter, as the datasheet recommends. Use Kelvin connections to the shunt [SBOS662C].

## 8. Components, single supply, grounding, decoupling

- **Capacitors in the signal path:** C0G/NP0. High-K ceramics (X7R etc.) lose 50 % or more of their capacitance at rated voltage and add distortion [BLD-10][SLYT796A].
  - Dielectric absorption: polypropylene/polystyrene 0.001–0.02 %, NP0 < 0.1 %, high-K about 0.2 %, polyester about 0.5 %, tantalum/mica 1–5 % [BLD-10]. This matters for integrators and sample-and-holds.
- **Resistors for ratios:**
  - Ratio accuracy follows TC *mismatch*: 25 ppm/°C of mismatch gives 250 ppm over 10 °C. Use a **resistor network on one substrate** for gain-setting pairs.
  - Watch self-heating: a ¼ W part at 125 °C/W with 10 mW rises 1.2 °C.
  - Watch voltage coefficient: up to over 200 ppm/V in high-MΩ types.
  - Watch thermocouple EMFs: about 20 µV/°C for metal film [BLD-10].
  - Excess noise is worst in carbon composition and better in metal film [BLD-10].
- **Single supply:**
  - A mid-supply divider needs a bypass capacitor with its pole at 1/10 of the signal's low corner. Without it, PSRR is gone and motorboating is possible.
  - A buffered or regulated mid-rail is better [AN-581].
  - Never use the raw supply as a reference; its noise is multiplied by the gain [SLOA030A].
- **Grounding with data converters.** Tie the converter's AGND **and** DGND pins to the analog ground plane at the part, never DGND to the digital plane. Decouple each converter supply pin to the analog plane with 0.01–0.1 µF [MT-031]. Whether to split the planes is design-dependent. The source suggests starting with analog and digital planes joined at the mixed-signal part, with optional jumpers. It doesn't recommend this for multi-card systems whose converters draw little digital current [MT-031].
- **Decoupling:** 0.01–0.1 µF ceramic as close to the supply pins as possible, plus 10–100 µF bulk within about 5 cm. A ferrite bead is optional, but check that it never saturates [MT-101].

## 9. Noise and error budget

- **Johnson noise** √(4kTR·B): 4 nV/√Hz for 1 kΩ at 25 °C; 12.8 nV/√Hz for 10 kΩ *(derived)* [MT-047][SLVA043B].
- **Input-referred noise density** √(e_n² + (i_n·R_s)² + 4kT·R_s), combined root-sum-square. A source 3–5× larger than the others dominates, and at high impedance the current noise dominates [MT-047].
- **Output noise** = input-referred noise × **noise gain** [MT-033][SLVA043B].
- **Noise bandwidth.** Integrate the density over the noise bandwidth: 1.57 × f_c for a single pole. For Butterworth filters use 1.11 (2nd order), 1.05 (3rd) and 1.025 (4th) [SLVA043B]. Two cascaded real poles give about 1.2 [MT-048]. Use the factor for the actual filter.
- **1/f region.** The corner is typically 2 Hz–2 kHz. Total noise V_rms = e_nw·√(f_c·ln(f_c/f_L) + (f_H − f_c)). Peak-to-peak ≈ 6.6 × rms [MT-048].
- **Budget table.** One row per error source, in the same unit (µV or ppm, referred to the input):

  | Source | Typ | Max | Over temp | Calibratable? |
  |---|---|---|---|---|
  | Offset | | | | |
  | I_B × R | | | | |
  | Gain/ratio | | | | |
  | Reference | | | | |
  | Noise | | | | |
  | Leakage | | | | |

  Root-sum-square independent random terms, add worst-case systematic ones, and state which.

## 10. Review checklist

- [ ] Requirements as numbers; topology and noise gain chosen.
- [ ] Every op amp: CM range, crossover, output swing at load, GBW/FPBW margin, I_B·R, phase reversal, differential limit, minimum stable gain.
- [ ] Every capacitive load or input capacitance: compensation chosen, PM ≥ 45° (SPICE).
- [ ] Reference: initial, TC, drift (√t), hysteresis, load/line, noise, required output cap, buffer, stress-aware placement.
- [ ] Inputs from outside the board: fault current ≤ 5 mA (or datasheet), clamps, EMI filter with matched C_cm.
- [ ] ADC: charge bucket ≥ 20 × C_sample (C0G), settling ≤ acquisition time, driver noise < 20 % of the ADC's.
- [ ] Signal-path capacitors C0G; ratio resistors in a network; self-heating and voltage coefficient checked.
- [ ] Converter AGND/DGND to the analog plane; decoupling per pin; ferrites checked for saturation.
- [ ] Error and noise budget table complete and meets the requirement.

## 11. References

- **[MT-031]** ADI, *Grounding Data Converters and Solving the Mystery of "AGND" and "DGND"*.
- **[MT-033]** ADI, *Voltage Feedback Op Amp Gain and Bandwidth*.
- **[MT-035]** ADI, *Op Amp Inputs, Outputs, Single-Supply, and Rail-to-Rail Issues*.
- **[MT-036]** ADI, *Op Amp Output Phase-Reversal and Input Over-Voltage Protection*.
- **[MT-047]** ADI, *Op Amp Noise*.
- **[MT-048]** ADI, *Op Amp Noise Relationships: 1/f Noise, RMS Noise, and Equivalent Noise Bandwidth*.
- **[MT-056]** ADI, *High Speed Voltage Feedback Op Amps*.
- **[MT-059]** ADI, *Compensating for the Effects of Input Capacitance on VFB and CFB Op Amps Used in Current-to-Voltage Converters*.
- **[MT-070]** ADI, *In-Amp Input RFI Protection*.
- **[MT-087]** ADI, *Voltage References*.
- **[MT-101]** ADI, *Decoupling Techniques*.
- **[AN-581]** ADI, *Biasing and Decoupling Op Amps in Single Supply Applications*.
- **[AN-1401]** ADI, *Instrumentation Amplifier Common-Mode Range: The Diamond Plot*.
- **[AAE-32]** ADI Analog Dialogue, *Ask The Application Engineer—32: Practical Techniques to Avoid Instability Due to Capacitive Loading*.
- **[ADI-DIFF]** ADI Analog Dialogue 48-1, *A Deeper Look into Difference Amplifiers*.
- **[ADI-VREF]** ADI, *How to Choose a Voltage Reference*.
- **[BLD-10]** ADI, *Basic Linear Design*, Chapter 10, *Passive Components*.
- **[SBOA128A]** TI, *EMI Rejection Ratio of Operational Amplifiers*.
- **[SLVA043B]** TI, *Noise Analysis in Operational Amplifier Circuits*.
- **[TIDU032C]** TI, *Capacitive Load Drive Solution using an Isolation Resistor*.
- **[SBAA173A]** TI, *Determining Minimum Acquisition Times for SAR ADCs*.
- **[SBAS788A]** TI, ADS7039-Q1 datasheet, *Detailed Design Procedure* (ADC driver/charge bucket).
- **[SBOS662C]** TI, INA240 datasheet, *Input Filtering*.
- **[SLOA030A]** TI, *Single-Supply Op Amp Design Techniques*.
- **[SLOA049D]** TI, *Active Low-Pass Filter Design*.
- **[SLYT796A]** TI, *Selecting Capacitors to Minimize Distortion in Audio Applications*.
