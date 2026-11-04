---
name: interface-layout
description: Lay out or review off-board wired interfaces on any MCU board (USB 2.0 FS/HS, USB-C/PD, CAN/CAN FD, RS-485, Ethernet 10/100 with MII/RMII/RGMII, isolated buses) plus connector ESD, chassis ground and cable shielding, using vendor-verified rules.
---

# Interface layout (USB, USB-C, CAN, RS-485, Ethernet, connector ESD)

Use this skill to place and route everything between a connector and the chip that drives it:
- ESD/TVS parts, chokes and termination;
- the differential pairs;
- isolation barriers;
- chassis and shield grounding.

It is **vendor-neutral**. Rules cite TI, ST, NXP, Microchip, ADI, Würth and others, and the places where they disagree are listed in §9. **The transceiver's or PHY's own datasheet layout section wins.** Values marked *(derived)* are arithmetic from cited data.

Companion skills: `mcu-circuit-design` (schematic side of these interfaces), `high-speed-digital-layout` (impedance, return paths, stitching vias), `power-pcb-layout`, `rf-layout`.

## 1. Workflow

1. Collect the datasheet layout section of every transceiver/PHY/PD controller, the protection-part datasheets, and the eval-board layout.
2. Place connectors first, then protection, chokes and termination **in signal-path order** from the connector inwards (§2), then the transceiver/PHY.
3. Define net classes: 90 Ω differential (USB), 100 Ω differential (Ethernet MDI), 50 Ω single-ended (MII/RMII/RGMII, ULPI), wide copper (VBUS, CC), and isolation keep-outs.
4. Route pairs first, then the rest. Check the constraints in each section below.
5. Check the reference planes, keep-outs and creepage on every layer, then run DRC.

## 2. Connector protection, chassis ground, cables (applies to every interface)

- **TVS placement.**
  - Place the TVS as close to the connector as design rules allow, with the protected IC far away [SLVA680].
  - Route the signal **from the connector straight into the TVS pin, then on to the IC**: pass-through, no stubs, **no via between the connector and the TVS** [SLVA680].
- **Ground connection.**
  - Put a ground via right next to the TVS ground pin, into an unbroken plane, using large or filled vias [SLVA680].
  - 0.25 nH of extra path inductance adds about 10 V at 4 × 10¹⁰ A/s [SLVA680].
- **Keep-out.**
  - The area between the connector and the TVS is a keep-out for unprotected traces.
  - Don't run unprotected traces parallel to protected ones or next to their vias [SLVA680].
  - Keep noisy traces away from connectors [SZZA009].
- **No sharp corners on exposed traces.** Use curves or ≤ 45°; a 90° corner can arc at 8 kV [SLVA680].
- **Chassis.**
  - Connect the earthed chassis right beside the TVS ground [SLVA680].
  - Give I/O its own ground area bonded to the enclosure with a wide, short path (≤ 3:1 length:width) and ≥ 2 screws [SZZA009].
  - I/O filter capacitors < 1000 pF, typically about 470 pF [SZZA009].
  - Shield RC capacitors are 10–620 pF, rated for kV [ARMSTRONG].
- **Cable shields.**
  - Terminate them **360° at both ends**. A shield terminated at one end stops working above about λ/6 [ARMSTRONG].
  - A 25 mm pigtail ruins a 2 m cable's shielding above about 30 MHz [ARMSTRONG].
  - Filter or shield every conductor where it enters the enclosure [ARMSTRONG], and low-pass filter and clamp external signals [AN1709].
- **Ground planes.** Solid; don't split the ground plane between analog and digital [AN1709].

## 3. USB 2.0 full-speed / high-speed

- **Impedance.**
  - 90 Ω differential: ±10 % [SPRAAR7], +5/−10 % [AN26.2].
  - Single-ended 40.5–49.5 Ω [SPRAAR7], or 40–55 Ω [AN26.2].
  - FS designs are forgiving; HS needs controlled impedance from the fab.
- **Intra-pair skew.** Sources range from < 5 mil [RT-HDG][SLVA888] through 50 mil [SPRAAR7][AN26.2] to 150 mil [TUSB1210]. **Target ≤ 5 mil**, with the serpentine near the mismatched end [SPRAAR7].
- **Length.**
  - 10–30 cm [SPRAAR7]; about 15 cm [AN26.2].
  - A 0.5 ns budget (≈ 7.5 cm) for an external PHY to the connector [TUSB1210].
  - Keep it as short as possible [RT-HDG].
- **Vias.** ≤ 4 per trace, the same count on both lines [SPRAAR7]. Better still, no layer change [RT-HDG][TUSB1210]. GND return vias within 50–200 mil of the signal vias [RT-HDG][SPRAAR7].
- **No stubs, no branches, no test points** on HS pairs; via stubs < 15 mil [SPRAAR7][RT-HDG][AN26.2]. Probe at the connector.
- **Spacing.**
  - 30 mil to other signals and pairs, 50 mil to clocks [SPRAAR7]; ≥ 3 × [AN26.2].
  - Never under oscillators or parallel to clocks [RT-HDG].
  - 45° bends, never 90° [RT-HDG][SLVA888].
- **Reference.** Solid GND [SPRAAR7]; NXP also accepts a continuous power plane [RT-HDG]. Stay ≥ 90 mil from plane edges and ≥ 1.5 W from voids [SPRAAR7].
- **ESD array** at the receptacle, pass-through, no stubs [SPRAAR7][AN4879][SLVA888]. Total added capacitance on DP or DM ≤ 4 pF [TUSB1210].
- **Common-mode choke** only if proven necessary [AN26.2]. Provide a 0 Ω (0402) DNP alternative [SPRAAR7]. An ECMF combines the choke and ESD, so no separate TVS is needed [AN4871][AN4879].
- **VBUS.**
  - Wide copper from the receptacle [TUSB1210].
  - A device needs 1–10 µF (2.2 µF typical) [AN26.2]; OTG ≤ 4.7 µF [AN4879].
  - The VBUS sense pin must respect the MCU's voltage rating (see `mcu-circuit-design`).
- **PHY bias resistor** (USB_RBIAS/REXT): value per device (e.g. 3 kΩ ±1 % [AN4879]). Short trace, returned to the nearest ground pad [AN26.2].
- **External ULPI PHY:** 50 Ω single-ended, **≤ 90 mm** (600 ps budget), clock and data length-equalized, ≥ 3 W spacing, solid ground [TUSB1210].

## 4. USB Type-C and Power Delivery

- **D+/D− on both rows.** Short A6↔B6 and A7↔B7 right at the receptacle. The resulting stub must stay **< 3.5 mm** [AN4871]. Don't hang the ESD part off that stub as a further branch.
- **CC lines.**
  - ≥ 8 mil wide (VCONN up to 600 mA) and routed directly, with no series parts [SLVA888].
  - Put the PD controller's capacitor (e.g. 220 pF) near the controller [SLVA888]. Total CC capacitance (receiver + protection + capacitor) must stay inside 200–600 pF [AN4871].
  - CC ESD is unidirectional, rated for the VCONN voltage. Use dedicated short-to-VBUS protection where 20 V PD is possible [AN4871].
- **VBUS power path.**
  - Wide copper; ≥ 1 via per 500 mA if vias are unavoidable [SLVA888].
  - VBUS TVS sized for the highest PD voltage (e.g. 25 V class for 20 V) [AN4871].
  - Hot-plug ringing can reach 2 × the supply [SLVA888].
- **SBU:** no verified layout rule. Protect it like the other connector pins (§2).

## 5. CAN and CAN FD

- **Termination.**
  - 120 Ω at the two cable ends only, never at stub nodes [SLLA270].
  - Split termination: 2 × 60 Ω (or 62 Ω) plus a centre capacitor, 4.7 nF typical (4.7–47 nF per OEM) [SLLA270][AH1308][TR1135].
  - Resistor matching ≤ 1–2 % [SLLA270][AH1308][TR1135].
- **Order from the connector inwards.** TVS/ESD at the connector; the common-mode choke near the transceiver pins [AH1308]. Lay out the protection *in the signal path* direction, with ≥ 2 vias on the protection and bypass parts [TCAN1462]. Modern transceivers often allow the choke to be removed, so make it a DNP option [AH1308].
- **PCB routing.**
  - CANH/CANL close together and symmetric, ≤ 10 cm on the board, with no other off-board lines alongside [AH1308][TR1135].
  - Nothing between TXD/RXD and the MCU for CAN FD [AH1308].
  - VCC decoupling 47–100 nF at the pin [AH1308].
- **Capacitance budget.** CANH/CANL to GND < 100 pF per node at ≥ 500 kbit/s [TR1135]. Optional capacitors at the connector are about 100 pF [AH1308].
- **Stubs.**
  - ≤ 0.3 m at 1 Mbit/s [SLLA270][TR1135].
  - In general, 2·t_pd(stub) ≤ t_r/3 [SLLA486]. No vendor gives a CAN FD number, so compute it from the transceiver's rise time *(derived)*.
  - Bus rate × length ≤ 50 Mbit·m (40 m at 1 Mbit/s) [SLLA270].
- **Isolated CAN.**
  - ≥ 4 layers.
  - **Nothing in the isolation gap on any layer**: no planes, traces, pads or vias.
  - Use the high-voltage land pattern: the IPC nominal pattern cut creepage from 8.1 to 7.3 mm on a DW-16 isolator.
  - 0.1 µF per supply pin plus about 4.7 µF bulk, connected without vias.
  - Slots can add creepage [ISO1042].

## 6. RS-485 / RS-422 / RS-232

- **Termination.** 120 Ω at the two trunk ends only. Put the fail-safe bias at the termination (V_AB ≥ 200 mV + noise; e.g. 2 × 523 Ω at 5 V) [SLLA272].
- **Stub length** ≤ (t_r/10)·v. At 78 % velocity: about 7 ft at 1 Mbit/s and 38 ft at 200 kbit/s [SLLA272]. This is stricter than CAN's 1/3 rule.
- **Bus:** length × rate < 10⁷ m·bit/s [SLLA272]. Board traces add 0.5–0.8 pF/cm, so keep A/B close and equidistant [SLLA272].
- **Ground.** Isolate the node rather than rely on earth for the return [SLLA272].
- **TVS** per §2 (e.g. an asymmetric −7/+12 V part; see `mcu-circuit-design`).
- **Isolated transceivers with integrated DC/DC** radiate across the barrier:
  - **4 layers are required.**
  - The gap's dipole is the main radiator, and needs about 140–250 pF of stitching capacitance. Make it an **inner-layer** plane overlap, so outer-layer creepage is kept.
  - Reinforced insulation needs ≥ 0.4 mm through-insulation distance.
  - Tie fills with vias every 10 mm [AN-0971].
  - Use ferrites (> 2 kΩ, 100 MHz–1 GHz) in series with the isolated supply and its ground, with **no pour under the ferrites**. A discrete 100 pF / 3 kV stitching capacitor is the alternative [AN-1349].
  - Signal-only isolators use 150 pF Y2 stitching up to about 200 MHz, with a via fence at 4 mm. Medical designs limit this to 10–20 pF [AN-1109].

## 7. Ethernet 10/100

- **MDI (PHY ↔ magnetics ↔ RJ45).**
  - 100 Ω differential ±10 %.
  - < 2 in from the PHY to the magnetics.
  - Intra-pair match 50 mil.
  - ≥ 30 mil between pairs (or 5 × the in-pair gap); same-layer ground ≥ 3–5 w away.
  - No vias or stubs [SNLA387][SNLA079][LAN8820].
- **MII/RMII.**
  - 50 Ω single-ended ±10 %, < 6 in [SNLA079][SNLA387].
  - Series termination on MII outputs [SNLA079].
  - Matching is anywhere from 50 mil [SNLA387] to 2 in [SNLA079]; use the stricter value at RMII's 50 MHz.
  - RMII needs a 50 MHz reference: use an oscillator close to the PHY. A crystal may drive only one device [SNLA387].
- **RGMII.**
  - 50–68 Ω, matched to ±400 mil [LAN8820].
  - The 1.5–2 ns clock delay comes from **either** the PHY's internal delay **or** the PCB, never both. Doubling it breaks the 2.6 ns TskewR maximum [SNLA243] *(derived)*.
- **Magnetics.**
  - No metal under discrete magnetics on any layer, with the void edge about 20 mil around the part [SNLA387][SNLA079]. Microchip puts the boundary halfway through the magnetics [LAN8820].
  - Metal under an RJ45 with integrated magnetics is allowed.
  - Keep the ground continuous under the PHY-side MDI [SNLA387].
- **Chassis ground.**
  - Separate it by ≥ 20 mil on all layers.
  - Join it to GND by a capacitor plus ≥ 1 MΩ [SNLA387]. TI's older guide uses two 0 Ω 1206 resistors [SNLA079].
  - Würth treats these options as experimental and stitches the shield ground every 4 mm [WE-ETH].
- **Bob Smith termination is debated.**
  - The TI recipe is 75 Ω + 1000 pF / 2 kV to chassis [SNLA079]. Würth gives a variant [WE-ETH].
  - Würth and a 2023 IEEE study show that the 150 Ω-per-pair assumption doesn't hold and that the optimum depends on the metric [WE-ETH][POLIMI].
  - TI's newer checklist omits it [SNLA387].
  - Provide footprints, and decide by EMC test.
- **Centre taps.** Follow the PHY: voltage-mode PHYs DC-decouple the centre tap to GND with a capacitor [WE-ETH]. The 49.9 Ω + 0.1 µF termination belongs to current-mode PHYs such as DP83848 only [SNLA079].
- **ESD on the MDI** goes on the **PHY side of the magnetics**, in line and bonded directly to GND [SNLA387][WE-ETH].
- **Straps and clock.**
  - Internal straps are 10–20 kΩ; use about 2.2 kΩ for non-default options [SNLA079].
  - RBIAS close to the PHY, with no traces under it [SNLA387][LAN8820].
  - 25 MHz crystal load calculation per the PHY datasheet.

## 8. Isolation barriers (any interface)

- Keep the **gap clear on every layer**, and use the isolator vendor's high-voltage land pattern [ISO1042].
- Stitching capacitance across the gap reduces emissions, but adds to leakage. Put it on **inner layers** so outer-layer creepage is kept [AN-0971][AN-1109].
- Never pour copper under EMI ferrites on the isolated supply [AN-1349].

## 9. Where sources disagree

| Topic | Range found |
|---|---|
| USB intra-pair skew | 5 mil … 150 mil (use ≤ 5 mil) |
| USB length | 7.5 cm (external PHY budget) … 30 cm |
| GND return-via distance | 50–200 mil |
| USB reference plane | GND only (TI) vs GND or continuous power (NXP) |
| CAN split-capacitor value / resistor match | 4.7–47 nF / 1–2 % |
| Stub criterion | t_r/3 (CAN) vs t_r/10 (RS-485) |
| MII/RMII matching | 50 mil vs 2 in |
| Magnetics void boundary | 20 mil around the part vs halfway through it |
| Chassis-to-GND link | C + 1 MΩ vs 0 Ω resistors vs "experimental" |
| Bob Smith | recommended (TI legacy) vs questioned (Würth, IEEE 2023) vs omitted (TI checklist) |

## 10. Pitfalls and corner cases

1. **USB-C:** the stub from shorting D+/D− across the two rows is longer than 3.5 mm, or the ESD part hangs off it.
2. **CC capacitance** outside 200–600 pF once the controller capacitor and ESD part are added.
3. **ESD placed after a via** or with a stub. Unprotected traces run parallel to protected ones in the connector-to-TVS zone.
4. **Test points** on USB HS or MIPI pairs.
5. **Choke/TVS order differs by interface.** For CAN: TVS at the connector, choke at the transceiver. For Ethernet: ESD on the PHY side of the magnetics.
6. **Double RGMII delay** (PCB delay plus the PHY's internal delay).
7. **Copying DP83848-style 49.9 Ω + 0.1 µF MDI termination** onto a voltage-mode PHY.
8. **Copper under discrete magnetics,** or a chassis ground that overlaps signal planes.
9. **Isolator built on the IPC nominal land pattern** (creepage lost). Stitching overlap on outer layers. A pour under the isolated-supply ferrites.
10. **Termination at a stub node** instead of the bus ends. Fail-safe bias missing on RS-485.
11. **Shield pigtails** and shields grounded at one end; connectors spread over several board edges with no common I/O ground.
12. **Citing ST AN4879 (current revision) for USB impedance or skew.** Its PCB section was removed, and it defers to USB-IF guidelines.

## 11. Done checklist

- [ ] Connector → protection → filter → transceiver order per interface; no via or stub before the TVS; TVS ground via at the pin.
- [ ] Chassis/I/O ground strategy defined; shield bonding 360°; filtering at entry.
- [ ] USB: 90 Ω, skew ≤ 5 mil, via count equal and minimal, no stubs or test points, ESD ≤ 4 pF, VBUS copper and capacitance, RBIAS placement.
- [ ] USB-C: row-short stub < 3.5 mm, CC width and capacitance window, VBUS current and vias, TVS voltage for the PD level.
- [ ] CAN/RS-485: termination at the ends only, split capacitor, protection order, stub budget, capacitance budget, fail-safe bias.
- [ ] Ethernet: MDI 100 Ω and lengths, MII/RMII/RGMII per the PHY, delay set once, magnetics void, chassis separation, ESD side, straps and RBIAS.
- [ ] Isolation: gap clear on every layer, HV land pattern, inner-layer stitching, ferrites without pour.

## 12. References

- **[SLVA680]** TI, *ESD Protection Layout Guide* (SLVA680A).
- **[SZZA009]** TI, *PCB Design Guidelines For Reduced EMI*.
- **[AN1709]** ST, *EMC design guide for STM8, STM32 and legacy MCUs*.
- **[ARMSTRONG]** K. Armstrong, *Design Techniques for EMC Part 2: Cables and Connectors*.
- **[SPRAAR7]** TI, *High-Speed Interface Layout Guidelines* (SPRAAR7J).
- **[AN26.2]** Microchip, *Implementation Guidelines for Microchip's USB 2.0 and USB 3.1 Gen 1 and Gen 2 Hub and Hub-Combo Devices*.
- **[RT-HDG]** NXP, *Hardware Development Guide for the MIMXRT1050/MIMXRT1060 Processor*.
- **[TUSB1210]** TI, TUSB1210 datasheet (SLLSE09J), layout section.
- **[AN4879]** ST, *Introduction to USB hardware and PCB guidelines using STM32 MCUs*.
- **[AN4871]** ST, *USB Type-C protection and filtering*.
- **[SLVA888]** TI, *Hardware Design Guideline for TPS65987 and TPS65988 USB Power Delivery Controllers*.
- **[SLLA270]** TI, *Controller Area Network Physical Layer Requirements*.
- **[SLLA486]** TI, *Top Design Questions About Isolated CAN Bus Design*.
- **[AH1308]** NXP, *Application Hints – Standalone high speed CAN transceivers TJA1044/TJA1057/TJA1046*.
- **[TR1135]** NXP, *Rules and recommendations for in-vehicle CAN networks*.
- **[TCAN1462]** TI, TCAN1462-Q1 datasheet, layout section.
- **[ISO1042]** TI, ISO1042 datasheet, layout section.
- **[SLLA272]** TI, *The RS-485 Design Guide*.
- **[AN-0971]** ADI, *Recommendations for Control of Radiated Emissions with isoPower Devices*.
- **[AN-1109]** ADI, *Recommendations for Control of Radiated Emissions with iCoupler Devices*.
- **[AN-1349]** ADI, *PCB Implementation Guidelines to Minimize Radiated Emissions on the ADM2582E/ADM2587E*.
- **[SNLA387]** TI, *Ethernet PHY PCB Design Layout Checklist*.
- **[SNLA079]** TI, *AN-1469 PHYTER Design & Layout Guide*.
- **[SNLA243]** TI, *RGMII Interface Timing Budgets*.
- **[LAN8820]** Microchip (SMSC), *Routing Checklist for the LAN8820*.
- **[WE-ETH]** Würth Elektronik, *Essentials for the Design of a GB Ethernet Front End*.
- **[POLIMI]** Illiano et al., *Influence of Terminal Units on the Radiation Properties on Ethernet Cables*, IEEE 2023.
