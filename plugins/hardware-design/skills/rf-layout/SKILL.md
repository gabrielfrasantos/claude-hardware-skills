---
name: rf-layout
description: Design or review the schematic and PCB layout of 2.4 GHz radios (BLE, 802.15.4/Thread/Zigbee, Wi-Fi) on any wireless MCU or module, covering 50 Ω lines, matching, antennas, supplies, crystals, coexistence, certification and their pitfalls.
---

# RF layout for 2.4 GHz radios (BLE, 802.15.4, Wi-Fi)

Use this skill for any board with a 2.4 GHz radio, either chip-down or a pre-certified module, and for any vendor. The examples come from:
- ST STM32WB/STM32WBA;
- Silicon Labs EFR32;
- TI CC13xx/CC26xx;
- Nordic nRF52;
- Espressif ESP32;
- Infineon (Cypress);
- antenna makers (Johanson, Ignion).

The **radio vendor's reference design and RF hardware app note win**. In RF, copying the reference exactly is usually the right engineering choice. Values marked *(derived)* are arithmetic from cited data. Where sources disagree, both are given (§10).

Companions: `mcu-circuit-design` (crystal maths, decoupling), `high-speed-digital-layout` (stitching vias, return paths), `power-pcb-layout` (switching regulators).

## 0. First decision: module or chip-down

- **Certified module.** Integration only (§7): keep-out, ground, antenna placement and host emissions. A module's grant can be reused only if the modular conditions are met:
  - shielded RF;
  - buffered inputs;
  - on-module regulation;
  - a permanent or unique antenna connector;
  - stand-alone compliance;
  - labelling;
  - integration instructions;
  - SAR independent of the host.
  
  The host still needs unintentional-radiator testing, and co-location may need a permissive change [EZ-FCC]. **Another antenna voids the module certification** [AN5165].
- **Chip-down.** You own the match, harmonics, antenna, crystal accuracy and full certification. Any stack-up or layout change requires retuning and re-checking the harmonics [AN930.2]. Budget for VNA tuning, a pre-compliance scan and at least one board spin.

## 1. Workflow

1. Get the reference design (schematic, **layout files**, stack-up, BOM with exact part numbers and sizes) and the vendor's RF layout and matching notes.
2. Fix the **stack-up first**: copy the reference board thickness and top-to-L2 distance (§2).
3. Placement order:
   1. antenna at the board edge or corner (§4);
   2. radio IC;
   3. match/filter (shortest possible run between them);
   4. crystal;
   5. SMPS/DC-DC parts;
   6. decoupling;
   7. everything else, away from the RF section.
4. Copy the RF section (pin → match → filter → antenna feed) **geometrically**, including pad sizes and component sizes.
5. Add a **DNP tuning footprint** at the antenna and a **conducted test port** (§3, §9).
6. Ground: solid L2, stitching, an exposed pad full of vias (§5).
7. Review against §11 (pitfalls) and §12 (checklist). Plan VNA tuning **in the final enclosure** and a pre-compliance harmonic scan.

## 2. Stack-up and the 50 Ω line

- **Line type.**
  - Use 50 Ω wherever the RF trace is longer than λ/16 [AN928.2]: about 7.7 mm in free space at 2.45 GHz, less in FR-4 *(derived)*.
  - Grounded coplanar waveguide (GCPW) is preferred: it is less sensitive to thickness variation and isolates better [AN928.2][AN5948][AN91445]. Microstrip and stripline are also acceptable [AN5165].
  - **GCPW rule:** keep the gap to the top-layer ground smaller than the substrate height, the ground pour wider than the gap, and the width and gap constant [AN91445].
- **2-layer boards:**
  - ST recommends a 0.8–1.0 mm board, so a 50 Ω line has a reasonable width [AN5165].
  - On 2 layers the 50 Ω trace is wide, typically over 20 mil [ESP-PCB]. Infineon tabulates widths from 65 mil on a 60 mil board down to 33 mil on a 20 mil board [AN91445].
- **4-layer boards:**
  - The matching values assume the reference top-to-L2 distance, e.g. 0.3 mm with 0.25–0.4 mm traces for 47–53 Ω [AN928.2]. Keep it ≤ 800 µm [AN928.2].
  - Match the reference's top-to-ground distance [SWRA640].
  - On BGA/WLCSP parts, the match may assume about 100 µm [AN930.2].
- **Reference plane.**
  - L2 is solid ground with no signal traces under the RF path [ESP-PCB][AN5165][SWRA640].
  - Nordic puts a keep-out on the *inner* layers under the antenna match on multilayer boards, to reduce stray capacitance [NRF52840-PS]. Silicon Labs wants continuous L2 ground under the chip and the match [AN928.2]. **Follow your radio vendor.**
- **Geometry:**
  - RF on the outer layer, **no vias, no stubs, no branches, no test points** on the line [ESP-PCB][AN91445].
  - Bends at 135° or curved [ESP-PCB][AN91445].
  - Interconnects between matching parts the same width as the pads; taper between different widths; no long thin lines or loops [AN928.2].
  - Short. The run from the filter to a 50 Ω connector may be longer, as long as it stays 50 Ω [AN5165].
  - Espressif deliberately adds a 15 mil stub on the first shunt capacitor's ground pad with 0201 parts [ESP-PCB]. Copy reference details like this, don't "clean them up".
- **Via fences and stitching:**
  - λ/10 [AN5165][AN5948]; λ/20 [AN91445]; λ/10 *of the 10th harmonic*, i.e. 1.0–1.27 mm on Silicon Labs boards [AN928.2].
  - **Use about 1–1.3 mm along RF lines and board edges**; it satisfies all three.
- **Solder mask.** Leave RF tracks unmasked where possible [AN5948], but a PCB antenna stays under mask [AN1088]. Silkscreen near the antenna slightly shifts its dielectric [AN928.2].
- **Isolation.** Better than about −45 dB between RF lines is impractical on small boards [AN5165][AN5948].

## 3. Matching network and harmonic filter

- **The chip-side network is both match and low-pass filter.** A wrong match puts RED/FCC compliance at risk [AN5948]. Shunt capacitors are chosen to self-resonate near the harmonics [AN930.2].
- **Vendor topologies:**

  | Vendor | Topology |
  |---|---|
  | ST STM32WB | Match + filter [AN5165] |
  | ST STM32WBA | 5-element network; the 3-element version needs strong optimisation [AN5948] |
  | Silicon Labs | 3–5 element ladders; a T is preferred over a pi on some parts [AN930.2] |
  | Espressif | CLC network [ESP-SCH] |
  | TI | Balun + LC filter, with a pi before the antenna [SWRA640] |

- **Integrated passive devices.** IPDs (e.g. ST MLPF-WB family) replace the discrete network. Pick the variant for your package. A QFN IPD may still need an antenna-side filter, and asymmetric filters have a **direction mark** [AN5165][AN5948].
- **Balanced designs.** Keep the balun symmetric and close to the pins (≤ 1.5 dB amplitude and ≤ 10° phase imbalance), or the 2nd and 4th harmonics rise. Lay out so the parasitic inductance adds to the series L, not the shunt C [SWRA640].
- **Placement.**
  - Put the network right at the RF pin, with short tracks [AN5165][AN928.2].
  - Give each shunt part ≥ 2 ground vias [AN5165][AN5948], straight to L2, not into the top pour [AN928.2].
  - Keep the top pour about 0.3–0.6 mm away from the match [AN928.2].
- **The trace from the pin is part of the match.** Copy its dimensions; spacing or stack-up changes retune it [AN930.2][AN5165].
- **Antenna-side tuning footprint (always provide one):**
  - a pi (shunt–series–shunt) with 0 Ω in series and the shunts DNP [AN91445][AN1088][NWP-017][ESP-PCB];
  - Johanson recommends a T for its chip antenna [JOH-2450AT18].
  - Fit at most two parts in the end [AN1088].
- **Parts.**
  - High-Q, C0G/NP0, self-resonance ≥ 2 × the operating frequency [AN91445]; tight tolerance (±0.05 pF / ±0.1 nH) [AN930.2].
  - Changing 0201 ↔ 0402 or the vendor changes the values, because smaller parts have different parasitics [NWP-017][AN930.2].
  - Pick capacitors slightly below the calculated value, since the pads add capacitance [NWP-017].
- **VNA tuning:**
  - calibrate the VNA;
  - short cable, coax screen soldered to good ground, short centre conductor;
  - start with 0 Ω in series (≈ 1 nH) and the shunts empty;
  - target SWR ≤ 2 [NWP-017].
  
  Moving the coax solder point shifts results by 5–10 MHz and 3–4 dB [SWRA117]. ESP32's pass criterion for the chip-side filter: S21 < −35 dB at 4.8 and 7.2 GHz [ESP-SCH].

## 4. Antenna

- **Types** (Infineon comparison) [AN91445]:

  | Type | Size | Gain |
  |---|---|---|
  | MIFA | 7.2 × 11.1 mm | 1.6 dBi |
  | IFA | 4 × 20.5 mm | 1.1 dBi |
  | Chip | 3.2 × 1.6 mm | 0.5 dBi (needs matching) |
  | Wire | 6 × 30 mm | 2 dBi |

  A well-made PCB antenna performs about as well as a chip antenna [AN1088]. TI's meandered IFA fits in 15.2 × 5.7 mm [SWRA117].
- **The ground plane is the other half of the antenna** [NWP-017]. Its size and edge currents set the tuning [AN1088]; a larger ground lowers the resonance [AN91445]. A rule of thumb is ≥ λ/4 (about 3 cm) of ground [EZ-GND]. On a USB dongle, the host laptop changed bandwidth from about 250 to about 100 MHz and power by about 2 dB [SWRA117].
- **Keep-out on all layers:** no copper, traces, parts or screws in the antenna area [AN91445]. **No ground under the antenna** unless its maker says so [AN5165][AN5948][AN1088]. Keep all layers clear under a U.FL [ESP-PCB].
- **Placement:**
  - In a corner [AN91445][JOH-2450AT18], or on an edge [IGNION-NN02].
  - Module antennas sit at the PCB edge, preferably mid-edge, **not mid-board** [AN6305]. ESP modules go outside the base board, or have the board cut away around them, never a hollow cut-out [ESP-PCB].
  - Silicon Labs IFA: shorting arm ≥ 1.0 mm and radiating trace ≥ 0.5 mm from the board edge [AN1088].
- **Copying a reference antenna:**
  - Make an exact copy, with the same thickness and εr. Thicker board → shorten it; thinner → lengthen it [SWRA117].
  - Some vendors publish variants per thickness, e.g. 1.6 mm and 0.8 mm, tolerant to εr 4.3–4.8 [AN1088].
  - "Cut-and-paste" without retuning is not recommended [NWP-017]; matching values depend on layout, thickness and material [JOH-2450AT18].
  - Remove trimmed copper completely [NWP-017].
- **Clearance examples:**

  | Item | Clearance |
  |---|---|
  | Enclosure (ESP) | ≥ 15 mm [ESP-PCB] |
  | Body (ST module) | ≥ 7 mm one axis, ≥ 5 mm others; about 5 mm to plastic [AN6305] |
  | Ignion NN02-101 | 5 × 5 mm clearance area [IGNION-NN02] |
  | Johanson chip | ≥ 0.8 mm ground clearance, 2–3 mm better; the near field needs about 4 mm [AN91445] |

- **Detuning:**
  - **A plastic enclosure lowers the resonance by about 100–200 MHz** [AN91445]. Tune slightly high on the bare board, then **tune in the final enclosure** [SWRA640][SWRA117].
  - No metal in the near field [AN91445]. Metallic inks degrade performance [AN6305].
  - A battery under the antenna acts as ground [AN5165]. Battery and mic cables must not cross it [AN91445].
  - The human body changes the input impedance [AN5165], though one measurement found a hand on plastic had minimal effect [AN91445]. Test in the real use position.

## 5. Supplies, ground and noise

- **Integrated SMPS/DC-DC: the most common sensitivity killer.**
  - A poor DC-DC layout can cost **> 5 dB of sensitivity**. Diagnose by turning the DC-DC off [SWRA640].
  - Put the inductor and capacitors at the switch pin, with a short return over solid ground [SWRA640]; small copper area; inductor orthogonal to RF lines [AN5165].
  - Keep RF parts, especially the antenna, far from the DC-DC [AN928.2].
  - ST STM32WB example: 4/8 MHz, 10 µH/2.2 µH. VDDSMPS capacitor ESL < 2.0 nH (QFN) / 2.5 nH (BGA) / 3.0 nH (WLCSP) [AN5165].
  - STM32WBA: 3 MHz plus a 10 nH series inductor and a ferrite + C filter [AN5948]. Its note gives both 10 µH and 2.2 µH; check the datasheet.
  - Nordic: fit the DC-DC parts only if DC-DC mode is used [NRF52840-PS].
- **Decoupling:**
  - Same layer as the IC; power enters the capacitor first; **one ground via per capacitor, never shared** [SWRA640][AN91445].
  - **Topology differs:** ST uses a star (4.7–10 µF at the root, 100 nF at the pins) [AN5165]; Silicon Labs says avoid a star and put the pF capacitor nearest the pin [AN928.2]. Follow your vendor's reference.
  - Ripple limits exist: e.g. ST 5–15 mVpp depending on frequency [AN5165]; ESP32 < 80–120 mV depending on the Wi-Fi mode [ESP-PCB].
- **Ground:**
  - Fill and stitch unused areas [AN5165][AN91445]. Put stitching along the board edges, and keep supply lines away from the edge [AN928.2].
  - Exposed pad: as many vias as the rules allow (e.g. ≥ 9 on ESP32) [AN5165][ESP-PCB]; ≥ 1 via per VSS pin [NRF52840-PS].
  - No ground splits, except where the vendor shows them [AN928.2][AN91445]. Use a solid return from the capacitor grounds to the chip, otherwise spurious emissions rise [SWRA640].
- **Digital lines.**
  - Keep GPIOs away from and never under the RF lines, antenna and crystal [AN928.2]. Keep fast digital lines off the crystal and supplies [NRF52840-PS].
  - Guard UART with ground and add series R (e.g. 499 Ω on ESP32 TX) [ESP-PCB][ESP-SCH].
  - At 20 dBm, long header pins radiate the 2nd harmonic [SWRA640].

## 6. Crystals and clocks

- **Accuracy budget:**
  - **BLE ±50 ppm; 802.15.4 ±40 ppm.**
  - Total = initial + temperature + ageing + **pulling**; estimate pulling with about 10 % C_L deviation [AN5042][TI-BLE5].
  - Wi-Fi SoCs can be stricter: ESP32's 40 MHz crystal must be within ±10 ppm [ESP-SCH].
- **Sleep clock (BLE): ±500 ppm** [TI-BLE5][SL-LFRCO].
  - An internal RC is possible but has conditions: TI needs SCA = 500 ppm, peripheral/broadcaster roles only, periodic recalibration, and slow temperature change [TI-BLE5].
  - Silicon Labs' LFRCO precision mode costs current, blocks the deepest sleep mode, and widens RX windows [SL-LFRCO].
  - Make sure the stack's configured sleep-clock accuracy (SCA) matches the hardware [SWRA640].
- **Trimming:**
  - Many wireless MCUs have an on-chip load-cap trim (e.g. STM32WB HSETUNE ≈ 1 ppm/step).
  - Tune a sample of boards and apply the median to the batch. Store it in OTP; it can't be erased.
  - Measure with a counter better than 0.1 ppm, **not an oscilloscope**.
  - The trim range is centred on a nominal C_L, so a 6 pF crystal may not reach 0 ppm on an 8 pF-centred trim [AN5042].
  - TI: trim in CCFG, and **never probe the 24/48 MHz crystal pins**; it can brick the device [SWRA640].
- **Layout:**
  - Top layer, at the pins, away from the SMPS and RF, with no GPIO nearby unless a ground layer separates them [AN5165].
  - Crystal ground and case go straight to L2 with vias; put isolating ground between the crystal and the RF supply [AN928.2].
  - Short, symmetric crystal–C_L loop [SWRA640]; no vias on clock traces [ESP-PCB].
  - Keep the 32 MHz lines away from the antenna and its ground [NRF52840-PS].
- **Clock harmonics land in the band.**
  - Any clock below 83.5 MHz has at least one harmonic inside 2400–2483.5 MHz *(derived)*. What matters is its amplitude and which channel it hits.

    | Clock | Harmonics in band *(derived)* |
    |---|---|
    | 32 MHz | 2432, 2464 MHz |
    | 38.4 MHz | 2419.2, 2457.6 MHz |
    | 40 MHz | 2440 and **2480 MHz (BLE advertising channel 39)** |
    | 48 MHz | 2448 MHz |
    | USB HS 480 MHz | 5th harmonic = 2400 MHz |

  - Filter the crystal and its harmonics [AN928.2]. TI reduced the largest spur by about 5 dB by zeroing its crystal tuning caps [SWRA640]. Watch SMPS and GPIO spurs too [AN5165].

## 7. Using a module

- **Follow the module's integration guide literally:** ground and keep-out, antenna edge on the PCB edge, no ground above or below the antenna clearance. Board size along the clearance axis matters most [AN6305][ESP-PCB].
- **Keep the certified antenna** [AN5165]. Design the host ground and enclosure to the module maker's clearances (§4).
- The host still needs emissions testing, and adding another transmitter may need a permissive change [EZ-FCC].

## 8. Coexistence (Wi-Fi + BLE/802.15.4, cellular)

- **Antenna isolation.**
  - Example: for 802.15.4 to receive at −96 dBm, the Wi-Fi power at its input must be ≤ −30 dBm. With Wi-Fi at +10 dBm that needs **≥ 40 dB isolation**.
  - Isolation grows with distance (1/R² in the far field), and with antenna nulls pointed at each other [SL-COEX-03]. Use polarisation and directivity [AN5165].
  - Keep diversity connectors ≥ λ/4 apart [AN928.2]. Two RF ports on one chip can detune each other [AN928.2].
- **Channel and PTA.**
  - Far channels tolerate about 20 dB more Wi-Fi power than adjacent ones. Set the Wi-Fi 40 MHz-intolerant bit, and bypass the front-end LNA when Wi-Fi is strong.
  - **Never run co-channel against 100 % Wi-Fi duty cycle** [SL-COEX-03].
  - PTA (REQUEST/GRANT/PRIORITY) needs 1–4 GPIOs. **The unmanaged measures are still needed even with PTA**, and 802.15.4 broadcasts aren't retried [SL-COEX-05].
- **LTE.** Bands 40/41 sit next to ISM with almost no guard band, so use a coexistence SAW filter (> 30 dB rejection for about 1.1 dB loss) [ABR-COEX].

## 9. Regulatory and test

- **FCC §15.247 (2400–2483.5 MHz):**
  - 6 dB bandwidth ≥ 500 kHz;
  - ≤ 1 W conducted, reduced by the antenna gain above 6 dBi;
  - out-of-band emissions ≥ 20 dB below in-band;
  - PSD ≤ 8 dBm/3 kHz;
  - emissions in restricted bands must meet §15.209 [CFR-15.247].
- **Restricted bands** (§15.205) include 2310–2390, 2483.5–2500, 4500–5150 and 7250–7750 MHz [CFR-15.205].
  - The 2nd harmonic of the whole band (4800–4967 MHz) falls entirely in a restricted band, and part of the 3rd does too *(derived)*. That's why the match/filter matters.
  - The 5th harmonic can be marginal on some parts [AN928.2].
- **ETSI EN 300 328 spurious emissions:** −30 dBm/MHz from 1 to 12.75 GHz; −36/−54 dBm below 1 GHz by band. Conducted at the antenna port if there is a connector, otherwise radiated [SWRA670].
- **Conducted test port.** Fit a U.FL/MMCX/SMA, DNP in production [AN91445][AN928.2]. Or use a 0 Ω loop that can be re-routed to a DNP connector [AN6305]. **Never run a Wi-Fi SoC without an antenna or load** [ESP-SCH].
- **DTM** (BLE Direct Test Mode) for physical-layer tests: TX power, sensitivity, frequency offset and drift, PER [NRF-DTM].
- **Bring-up.**
  - Check that the 32 kHz crystal runs, and measure the background noise before range tests [SWRA640].
  - Start with all GPIO disabled, then enable pins one at a time to find a desense source [TI-BLE5].
  - Trim the crystal per batch [AN5042], and test throughput and range on the final product [ESP-PCB].

## 10. Where sources disagree

| Topic | Positions |
|---|---|
| Via fence pitch | λ/10 (ST), λ/20 (Infineon), λ/10 of the 10th harmonic ≈ 1–1.3 mm (Silicon Labs). Use about 1–1.3 mm. |
| Ground under the match on multilayer boards | Inner-layer keep-out (Nordic) vs continuous L2 (Silicon Labs) |
| Decoupling topology | Star (ST) vs no star, smallest cap nearest the pin (Silicon Labs) |
| Antenna tuning network | Pi (most) vs T (Johanson chip antenna) |
| Solder mask | Off RF tracks (ST) vs on the PCB antenna (Silicon Labs). Different features, not a conflict. |
| Hand effect | Significant (ST) vs minimal on plastic (Infineon). Test it. |
| Crystal tolerance | BLE ±50 ppm, 802.15.4 ±40 ppm, ESP32 Wi-Fi ±10 ppm |

## 11. Pitfalls and corner cases

1. **Board thickness or top-to-L2 distance differs from the reference.** Both the chip match and the antenna shift.
2. **Ground plane changed or too small**, or a module's antenna placed mid-board. A USB dongle detunes when plugged into a laptop.
3. **Anything in the antenna keep-out on any layer:** ground, traces, screws, parts, a battery, cables, a display or flex, metallic paint.
4. **No DNP tuning footprint at the antenna.** No conducted test port.
5. **RF trace problems:** thin, long, branched, with vias, test points or connector stubs; RF routed over splits or traces.
6. **Via fence too coarse for the harmonics.**
7. **Part changes without retuning:** 0201 ↔ 0402, another vendor, another antenna. A balun laid out asymmetrically. The IPD or filter fitted backwards.
8. **SMPS/DC-DC layout** with high ESL, a large loop or a badly oriented inductor costs > 5 dB of sensitivity. DC-DC parts close to the antenna.
9. **Shared ground vias between decoupling capacitors;** weak returns raising spurious emissions.
10. **Crystal outside the ppm budget** once temperature, ageing and pulling are added. Wrong C_L for the trim range. Measuring with an oscilloscope. Probing TI crystal pins. Sleep clock or SCA mis-set.
11. **Clock harmonics on used channels** (§6), including advertising channel 39 at 2480 MHz from a 40 MHz clock and USB HS's 5th harmonic. Digital lines and header pins near the RF section.
12. **TX power above the reference setting** raises harmonics. The 2nd and 3rd harmonics fall in restricted bands; the 5th can be marginal.
13. **Tuned on the bench, not in the enclosure.** Plastic shifts the resonance down by 100–200 MHz.
14. **Measurement setup errors:** the coax solder point moves the result 5–10 MHz; trimmed copper left behind.
15. **Coexistence:** co-channel Wi-Fi; the front-end LNA desensitised; PTA relied on without unmanaged measures; LTE B40/B41 with no filter.
16. **Changing the antenna on a certified module** voids its grant.
17. **Running a Wi-Fi radio without an antenna or load.**
18. **Typos in vendor notes** (e.g. conflicting inductor values in one ST note). Cross-check against the datasheet and reference BOM.

## 12. Done checklist

- [ ] Module vs chip-down decided; certification path and test budget known.
- [ ] Stack-up copies the reference thickness and top-to-L2 distance; 50 Ω GCPW verified with the fab's calculator.
- [ ] RF path copied geometrically: pad and part sizes, trace from the pin, ground vias per shunt part, direction marks.
- [ ] RF line: outer layer, no vias, stubs or test points, smooth bends, 1–1.3 mm via fence, nothing underneath.
- [ ] Antenna: corner or edge per the maker, keep-out on all layers, ground size per the maker, DNP pi/T at the feed, enclosure clearances.
- [ ] DC-DC per the vendor layout, away from RF and antenna; decoupling per the vendor topology with unshared vias.
- [ ] Crystal ppm budget calculated (including pulling); sleep clock and SCA consistent; trim plan; clock harmonics checked against used channels.
- [ ] Conducted test port; DTM/test firmware plan; pre-compliance harmonic scan (2nd/3rd in restricted bands).
- [ ] Coexistence isolation budget (if Wi-Fi, cellular or a second radio is present).
- [ ] Tuning and range test in the final enclosure, in the use position.

## 13. References

- **[AN5165]** ST, *How to develop RF hardware using STM32WB MCUs*.
- **[AN5948]** ST, *How to develop RF hardware using STM32WBA MCUs*.
- **[AN6305]** ST, *Guidelines for PCB design on STM32WBA5MMG*.
- **[AN5042]** ST, *How to calibrate the HSE clock for RF applications on STM32 wireless MCUs*.
- **[AN928.2]** Silicon Labs, *EFR32 Series 2 Layout Design Guide*.
- **[AN930.2]** Silicon Labs, *EFR32 Series 2 2.4 GHz Matching Guide*.
- **[AN1088]** Silicon Labs, *Designing with an Inverted-F 2.4 GHz PCB Antenna*.
- **[SL-LFRCO]** Silicon Labs, *Using the LFRCO as Low-Frequency Clock Source* (Bluetooth docs).
- **[SL-COEX-03] / [SL-COEX-05]** Silicon Labs, *Wi-Fi Coexistence Fundamentals*, chapters 03 (Unmanaged Coexistence) and 05 (Conclusions).
- **[SWRA640]** TI, *CC13xx/CC26xx Hardware Configuration and PCB Design Considerations*.
- **[SWRA117]** TI, *AN043 Small Size 2.4 GHz PCB antenna*.
- **[SWRA670]** TI, *CE Regulations for SRDs Operating in License-Free 2.4 GHz/5 GHz Bands*.
- **[TI-BLE5]** TI, *SimpleLink BLE5-Stack User's Guide*, "Clock accuracies and Bluetooth LE".
- **[NRF52840-PS]** Nordic, *nRF52840 Product Specification*, "Reference circuitry".
- **[NWP-017]** Nordic, *nWP-017 Antenna tuning*.
- **[NRF-DTM]** Nordic, nRF5 SDK, *Direct Test Mode*.
- **[ESP-PCB]** Espressif, *ESP Hardware Design Guidelines: PCB Layout Design (ESP32)*.
- **[ESP-SCH]** Espressif, *ESP Hardware Design Guidelines: Schematic Checklist (ESP32)*.
- **[AN91445]** Infineon (Cypress), *Antenna Design and RF Layout Guidelines*.
- **[JOH-2450AT18]** Johanson Technology, *2450AT18A0100001E 2.45 GHz chip antenna* datasheet.
- **[IGNION-NN02]** Ignion, NN02-101 NANO mXTEND product information.
- **[EZ-FCC]** Ezurio, *FCC Guidance for Incorporating Transmitter Modules* (KDB 996369).
- **[EZ-GND]** Ezurio FAQ, ground-plane size for module antennas.
- **[ABR-COEX]** Abracon, 2.4 GHz Wi-Fi/Bluetooth/LTE coexistence filter.
- **[CFR-15.247] / [CFR-15.205]** 47 CFR §15.247 and §15.205.
