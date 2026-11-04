---
name: high-speed-digital-layout
description: Lay out or review PCBs with fast digital interfaces (QSPI/OctoSPI/HyperBus, SDRAM, DDR/LPDDR, SD/eMMC, parallel RGB, MIPI DSI/CSI-2, LVDS, cameras, clocks) on any MCU/MPU, using vendor-verified signal-integrity rules.
---

# High-speed digital layout (memories, displays, cameras, clocks)

Use this skill to place and route the fast parallel and serial buses around an MCU or MPU:
- external flash and RAM;
- SDRAM, DDR and LPDDR;
- SD cards and eMMC;
- displays, cameras and clock distribution.

It is **vendor-neutral**. Each topic gives the rule, what to look up, and examples from several vendors (ST, NXP, TI, Infineon/Cypress, Micron, Swissbit), so you can see how much the numbers differ.

**The part's own hardware design guide wins.** Sources disagree on many numbers, and §11 lists the disagreements. Values marked *(derived)* are arithmetic from the cited data.

Companion skills: `power-pcb-layout` for power stages; `interface-layout` for USB, CAN, Ethernet and ESD; `rf-layout` for radios.

## 1. Workflow

1. **Find the routing rules for your exact part.** Look in its hardware design guide (HDG), the memory or display vendor's layout note, and the eval-board layout. In ST's case the routing numbers are in the "getting started with hardware development" notes (e.g. AN4661, AN4938) and the DDR guide AN5122. The peripheral notes (AN4760 Quad-SPI, AN5050 OctoSPI, AN4861 LTDC, AN4860 DSI, AN5020 DCMI, AN5200 SDMMC) explain the peripheral but give no PCB numbers.
2. **Write a constraint table per interface:**
   - clock frequency;
   - SDR or DDR;
   - single-ended and differential impedance;
   - matching groups and tolerances;
   - maximum length;
   - via budget;
   - spacing;
   - termination;
   - reference plane.
   
   Turn it into KiCad net classes and length-tuning groups.
3. **Choose the stackup from the most demanding interface** (§3) before placing anything.
4. **Placement:** memory and display connectors close to the controller pins. Keep switching regulators, crystals and the board edge away from the fast nets [SPRAAR7].
5. **Route in this order:** clocks/strobes, then matched groups, then everything else. Match on **delay, not length** (§2.7).
6. **Verify:** length report per group (including vias/package where the vendor counts them), reference-plane check per layer, DRC.

## 2. Signal-integrity rules every interface uses

1. **Electrically long.** A trace needs transmission-line treatment once its propagation delay exceeds about half the edge time [AP24026]. That is about 70 mm per ns of rise time in FR-4 *(derived)*. Published fractions range from 1/2 to 1/20 of the rise time [ALTIUM-CL]. Assume anything above a few cm with sub-ns edges is a transmission line.
2. **Return path.**
   - Route fast signals over solid GND, not power planes, and never across a split or void [SPRAAR7][RT-HDG].
   - Keep traces ≥ 1.5 W from voids and ≥ 90 mil from plane edges [SPRAAR7].
   - If a reference change can't be avoided, put a stitching capacitor (≤ 1 µF) next to the crossing [SPRAAR7]. When the reference changes from GND to a power plane, use about 100 nF GND↔power next to the via [AN5122].
3. **Layer changes.** Put a GND return via next to each signal via. The distance differs by source: within 200 mil [SPRAAR7], 100 mil [RT1170-HDG] or 50 mil [IMX8MP-HDG]. Use the tightest one that fits.
4. **Impedance.**
   - Common targets: 50 Ω ±10 % single-ended for SDMMC/FMC/QSPI [AN4661][AN4938][RT-HDG]; 90 Ω differential for USB; 100 Ω ±10 % differential for MIPI/LVDS [IMX8MP-HDG].
   - DDR has its own values (§6).
   - Get the trace geometry from the fab's impedance calculator for *their* stackup.
5. **Series source termination.**
   - R_driver + R_s = Z0, placed **at the driver** [TN-46-06].
   - Typical: 22 Ω on fast SPI clocks [SPRAD21]; 0–22 Ω on SD CLK [AN2111]; a 0 Ω placeholder on MMC/OSPI clocks for tuning [SPRAD21].
   - **Never on DDR4** [SPRAD06].
6. **Crosstalk spacing.** No universal number:
   - 2 W [SCAA082][AP24026];
   - 2.5 × height [IMX6-HDG];
   - 3 W, or 3 × trace width from clocks [AN4661];
   - 3 × height to the plane [AN5122];
   - 5 W between pairs, 50 mil from clocks [SPRAAR7].
   
   Use the interface's own rule, and give clocks the most room.
7. **Match on delay.** Microstrip and stripline have different speeds (≈ 148–151 ps/in vs ≈ 182 ps/in [SCAA082]). Matching in mm across mixed layers is wrong. TI scales microstrip lengths by 1/1.1 [SPRAD06]. Include via and package delay where the vendor says so [IMX8MP-HDG][AN5122]. Put serpentines near the mismatched end, and bend > 135° or use two 45° corners [SPRAAR7].
8. **Via stubs.** Keep stubs < 15 mil or back-drill [SPRAAR7]. On a 1.6 mm 4-layer board, an L1→L2 transition through a through-via leaves about 55 mil of stub, while L1→L4 leaves none *(derived)*. Prefer outer-to-outer transitions for the fastest nets, and use the same via count on both legs of a pair [SPRAAR7].

## 3. Stackup and layer count

| Interface class | Typical minimum (vendor examples) |
|---|---|
| QSPI, SDRAM, SD, RGB at MCU speeds | 4 layers with a solid GND under the bus [RT-HDG][AN4661] |
| Dense MCU + SDRAM + display | 4–6 layers; 8 for dense boards [AN4661] |
| DDR3L (STM32MP1 class) | 4 layers possible following AN5122 *exactly* [AN5122] |
| DDR4/LPDDR4 (i.MX 8M, AM62x class) | ≥ 6 layers, stripline, no plane cuts [SPRAD06][IMX8MP-HDG] |

## 4. QSPI, OctoSPI, HyperBus

- **Example rules from three vendors:**

  | Source | Rules |
  |---|---|
  | **ST Quad-SPI** [AN4661][AN4938] | 50 Ω ±10 %. ≤ 120 mm, otherwise add termination. Data group matched within ±10 mm. Clock ≥ 3 W from others, few vias, **no serpentine on the clock**. Keep the group on one layer. |
  | **HyperBus 166 MHz** [AN211622] | 50 Ω, CK/CK# 100 Ω differential. Load < 20 pF (about 6 in max *(derived)*). Matching including vias: CK–CK# ±10 mil; RWDS–DQ ±25 mil; DQ–DQ ±50 mil; CK–DQ ±500 mil; CK–CS# ±1500 mil. DQ+RWDS on one layer, with a GND guard on the clock. Decoupling ≥ 2 × 1 µF + 4 × 0.1 µF, ≥ 2 vias per supply ball. |
  | **NXP FlexSPI** [RT-HDG][RT1170-HDG] | DQS **floating** for QSPI loop-back up to 133 MHz SDR. DQS connected to the flash's DQS only for 166 MHz DDR. |

- **Firmware-visible layout effects.**
  - ST: sample-shift (SSHIFT) absorbs PCB delay, but not in DDR mode. A CS pull-up is needed [AN4760].
  - OctoSPI/HyperBus need DQS, and the delay block must be retuned after voltage or temperature changes [AN5050].
- **Note:** ST's ±10 mm and HyperBus's ±50 mil differ by about 8×, because the clock rates and edges differ. Use the rule for your speed.

## 5. Parallel SDRAM (FMC / SEMC / EMC)

- **ST FMC** [AN4661][AN4938]:
  - 50 Ω ±10 %, ≤ 120 mm. Data group ±10 mm; clock to address/command ±10 mm (≤ 20 mm maximum).
  - **SDCLK on an inner layer**, ≥ 3 W spacing, no serpentine.
  - Data and address/control on different layers, or ≥ 5 mm apart.
  - Load capacitance ≤ 20 pF trace / 30 pF total at 3.3 V; ≤ 15 / 20 pF at 1.8 V.
- **NXP SEMC** [RT-HDG][RT1170-HDG]:
  - 50 Ω; **all signals within ±50 mil**.
  - Two groups: data+DM, and address+control. One group on top, one on bottom, each over its adjacent GND.
  - SEMC_DQS left **floating**.
- Neither vendor gives a topology or termination for SDR SDRAM. Keep a single device point-to-point and short.

## 6. DDR3L, LPDDR2, DDR4, LPDDR4 (MPUs)

**Rule zero: follow the SoC vendor's DDR routing guide line by line.** The numbers below differ between SoCs and are not interchangeable.

| | ST STM32MP1 DDR3L, 4-layer [AN5122] | NXP i.MX6 DDR3 [IMX6-HDG] | TI AM62x DDR4/LPDDR4 [SPRAD06] | NXP i.MX 8M Plus LPDDR4 [IMX8MP-HDG] |
|---|---|---|---|---|
| Z0 SE / diff | 55 / 100 Ω ±10 % | 50 / 100 Ω | 40 / 80 Ω ±10 % | 50 / 85 Ω |
| Topology | Fly-by with 56 Ω to VTT (or point-to-point with 33 Ω series on A/C) | T up to 4 chips unterminated; fly-by for 8 chips, with termination | DDR4 fly-by only, Rtt = Z0 ±5 Ω, **no series termination**. LPDDR4 point-to-point, no VTT/VREF. | Point-to-point |
| Matching | DQ/DM–DQS ±40 mil. DQS 0–590 mil **shorter** than CLK. A/C 0–40 mil **shorter**. CLK is the longest, ≤ 12 cm. | CK ±5 mil, DQS ±10 mil, data ±25 mil, A/C ±25 mil, ctrl ±50 mil. CK ≤ 3 in. | DDR4 byte ≤ 500 ps, DQS–DQ ≤ 2 ps. LPDDR4 ≤ 450 ps. | CK/DQS intra-pair ≤ 1 ps; DQ–DQS ±50 ps; DQS–CK ±75 ps; CA–CK ±50 ps |
| Vias / spacing | Spacing by height (3 × S) | 2.5 × height for clocks/strobes | ≤ 3 vias CK/ADDR, ≤ 2 data. Spacing 3 w in group, 4–5 w to others. | ≤ 2 vias. 2 W (3–4 W preferred), 5 W for CLK/DQS. |
| Reference | VDD_DDR plane allowed, with layer-change capacitors | — | **VSS only**, no cuts | GND or the I/O's own supply |

- **VREF/VTT:**
  - ST: VREF from a 2 kΩ 1 % divider + 100 nF per device; one HF capacitor per two VTT resistors; ZQ 240 Ω 1 % [AN5122].
  - i.MX6: VTT 1–2 × 0.1 µF per RPACK + 10–22 µF bulk; VREF 0.22 µF distributed + 1 µF at the source, with a 30 mil trace and 25 mil clearance [IMX6-HDG].
- **Pin swapping.** LPDDR4 CA bit swapping is not allowed; DQ may swap only within a byte [IMX8MP-HDG].

## 7. SD card, SDIO, eMMC

- **ST SDMMC** [AN4661][AN4938]:
  - 50 Ω ±10 %, ≤ 120 mm, mismatch < 10 mm, the same via count on all lines.
  - Capacitance ≤ 20 pF at 3.3 V (≤ 15 pF at 1.8 V); inductance < 16 nH.
  - A power-plane reference is allowed only with 10 nF to GND.
  - The note also says "skew below 250 ps @ 10 mm". 10 mm is only about 60–70 ps *(derived)*, so treat these as two separate limits.
- **Card side** [AN2111]:
  - pull-ups 10–100 kΩ on CMD/DAT **from the switched card supply**;
  - 0–22 Ω series on CLK for longer runs, plus 100 kΩ pull-down on CLK;
  - ≤ 4.7 pF added capacitance, equal on all lines, ≤ 2 vias per line;
  - ESD as fast diodes with series R rather than RC filters.
- **Clock length.** CLK slightly longer than the longest DATA/CMD (+5 mil) [IMX6-HDG]. TI provisions a 0 Ω series resistor and a pull-down at the clock, with an optional DNP 8–10 pF [SPRAD21].
- **Speed modes:**
  - DS 25 MHz and HS 50 MHz at 3.3 V.
  - **SDR50/SDR104/DDR50 need 1.8 V I/O** [SD-PHY]. Without a separate VDDMMC, add a level translator [AN5200].
- **Card behaviour** [SD-PHY][AN2111]:
  - The card's internal 50 kΩ pull-up on CD/DAT3 is active until ACMD42.
  - DAT3 low during CMD0 selects SPI mode, which is a trap with level shifters.
  - The UHS voltage switch (CMD11) needs the clock stopped ≥ 5 ms.

## 8. Displays

- **Parallel RGB (LTDC/LCDIF).**
  - Pixel clock = total width × total height × refresh rate [AN4861].
  - Treat the pixel clock like an SDRAM clock: a series R at the source, short, over solid GND, no gaps [RT-HDG].
  - Put the frame buffer in its own SDRAM bank [AN4861].
- **MIPI DSI / CSI-2.**
  - 100 Ω ±10 % differential. Intra-pair within 1 ps, and each DSI data trace ≤ 10 pF (≤ 60 pF total) for compliance [IMX8MP-HDG].
  - TI CSI rules: 85–115 Ω, lane-to-lane skew 40 ps, ≤ 10 in, ≤ 2 vias, **no stubs and no test points** [SPRAAR7].
  - The FPC connector and any ESD part count against the capacitance budget.
- **LVDS (FPD-Link etc.).**
  - 100 Ω; termination 90–130 Ω, **within 10 mm (12 mm max) of the receiver**; stubs < 10 mm; few vias; LVDS and TTL separated by a plane [DS90LV028A][SNLA187].
  - "Tightly coupled" means S < 2 W [SNLA187].
- **SPI displays.** Use a series R (≈ 22 Ω) on the clock [SPRAD21] and keep the run short.
- **Backlight boost converters and other switchers** stay away from fast traces [SPRAAR7]. Lay out their hot loop per the `power-pcb-layout` skill.

## 9. Cameras

- **Parallel DCMI.** Max PIXCLK depends on the part (e.g. 54 / 100 / 110 MHz on different STM32s), and the bus clock must be ≥ 2.5 × PIXCLK. PIXCLK/HSYNC/VSYNC polarities must match the sensor [AN5020]. Route PIXCLK as a clock (§2), with the data group near it.
- **MIPI CSI-2:** as DSI (§8).

## 10. Clocks and crystals

- **Distribution.** No branches on a clock net: use a clock buffer (star), or a properly terminated daisy chain. Make the clock routes equal length. A 100 MHz clock has energy up to about 500 MHz [SCAA082].
- **Noisy clocks.** Route them as stripline between grounds, away from edges and I/O. Use the lowest crystal frequency with a PLL [AP24026].
- **Crystal ground — two schools:**
  - a solid GND plane directly under the crystal and its parts [RT-HDG];
  - an isolated GND island tied at one point [AP24026].
  
  Follow the MCU vendor's HDG and eval board.
- **Load capacitors and drive level:** see the `mcu-circuit-design` skill. Crystal and caps go as close to the pins as possible [AN4661].

## 11. Where sources disagree

| Topic | Range found |
|---|---|
| Stitching-via distance | 200 / 100 / 50 mil |
| Crosstalk spacing | 2 W … 5 W, or height-based 2.5–3 H |
| DDR single-ended impedance | 40 / 50 / 55 Ω (differential 80 / 85 / 100 Ω) |
| DDR reference plane | VSS only, or the DDR supply plane with stitching caps |
| SDRAM matching | ±10 mm (ST) vs ±50 mil (NXP) |
| Series termination | 20–200 Ω generic; 0–22 Ω for SD; forbidden on DDR4 |
| Crystal ground | solid plane vs single-point island |
| Propagation delay | ≈ 148–200 ps/in depending on layer and εr |

**When in doubt, take the stricter rule.** But the vendor guide for the actual silicon is the reference, and its eval-board layout shows what is proven.

## 12. Pitfalls and corner cases

1. Matching in mm across microstrip and stripline (§2.7).
2. Ignoring via and package delay where the vendor counts them.
3. One-sided DDR rules read as ± (AN5122: DQS and A/C must be *shorter* than CLK).
4. A serpentine on a clock that the vendor says must be straight (ST QSPI and FMC clocks).
5. NXP SEMC_DQS / FlexSPI_DQS wired when they must float, or floating when DDR mode needs them.
6. DDR3 fly-by without VTT; LPDDR4 with a VREF/VTT that it doesn't have; CA bits swapped on LPDDR4.
7. L1→L2 via transitions leaving long stubs on fast nets (§2.8).
8. Routing over a plane split or along a plane edge; a reference change with no stitching via or capacitor.
9. SD pull-ups from an always-on rail (back-powering a removed or powered-down card); UHS modes on a 3.3 V-only I/O; SPI mode entered by accident through DAT3.
10. MIPI capacitance budget eaten by the connector and the ESD part; test points on CSI/DSI lanes.
11. LVDS termination placed far from the receiver.
12. Switching regulators, backlight boost or crystals next to the memory or display bus.

## 13. Done checklist

- [ ] Constraint table per interface, from the exact part's HDG; net classes and tuning groups set up.
- [ ] Stackup chosen for the most demanding bus; fab impedance calculation for 50 Ω SE and 90/100 Ω differential (and DDR values).
- [ ] Every fast net over solid GND; no splits; reference changes have stitching vias or caps.
- [ ] Matching done on delay, including vias/package where required; one-sided rules respected.
- [ ] Via budget and stub limits met; clocks without serpentines where forbidden; spacing per interface.
- [ ] Termination per vendor (at the driver; none on DDR4; VTT/VREF as specified).
- [ ] SD/eMMC: pull-ups from the switched supply; voltage mode matches the I/O; card-detect behaviour understood.
- [ ] MIPI/LVDS: impedance, skew, capacitance budget, termination at the receiver, no stubs or test points.
- [ ] Length/delay report saved with the design.

## 14. References

- **[SPRAAR7]** TI, *High-Speed Interface Layout Guidelines* (SPRAAR7J).
- **[SCAA082]** TI, *High-Speed Layout Guidelines* (SCAA082A).
- **[SPRAD06]** TI, *AM62x, AM62Lx DDR Board Design and Layout Guidelines* (SPRAD06C).
- **[SPRAD21]** TI, *AM62x … Schematic Design Guidelines* (SPRAD21J).
- **[SNLA187]** TI, *LVDS Owner's Manual*, 4th ed.
- **[DS90LV028A]** TI, DS90LV028A datasheet, layout section (SNLS013F).
- **[AN4661]** ST, *Getting started with STM32F7 Series MCU hardware development*.
- **[AN4938]** ST, *Getting started with STM32H74xI/G and STM32H75xI/G MCU hardware development*.
- **[AN5122]** ST, *STM32MP1 Series DDR memory routing guidelines*.
- **[AN4760]** ST, *Introduction to Quad-SPI interface for STM32 MCUs and MPUs*.
- **[AN5050]** ST, *Getting started with Octo-SPI, Hexadeca-SPI, and XSPI interfaces on STM32 MCUs*.
- **[AN4861]** ST, *Introduction to LCD-TFT display controller (LTDC) for STM32 MCUs*.
- **[AN5020]** ST, *Introduction to digital camera interface (DCMI) for STM32 MCUs*.
- **[AN5200]** ST, *Getting started with the STM32H7 MCU SDMMC host controller*.
- **[RT-HDG]** NXP, *Hardware Development Guide for the MIMXRT1050/MIMXRT1060 Processor*.
- **[RT1170-HDG]** NXP, *Hardware Development Guide for the MIMXRT1160/1170 Processor*.
- **[IMX6-HDG]** NXP, *Hardware Development Guide for i.MX 6DualPlus/6QuadPlus, 6Dual/6Quad and 6Solo/6DualLite*.
- **[IMX8MP-HDG]** NXP, *i.MX 8M Plus Hardware Developer's Guide*.
- **[AN211622]** Infineon (Cypress), *HyperFlash and HyperRAM Layout Guide*.
- **[AP24026]** Infineon, *EMC Design Guidelines for Microcontroller Board Layout*.
- **[TN-46-06]** Micron, *Termination for Point-to-Point Systems*.
- **[AN2111]** Swissbit, *SD Memory Card Design-in*.
- **[SD-PHY]** SD Association, *Physical Layer Simplified Specification* v4.10.
- **[ALTIUM-CL]** Altium, *Why is There a Transmission Line Critical Length?*
