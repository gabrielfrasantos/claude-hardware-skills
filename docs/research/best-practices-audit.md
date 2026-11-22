# Best-practices audit of the hardware-design plugin

Date: 2026-11-20. Branch audited: `feat/reference-block`. Scope: the seven skills built or extended in this session
(priority order), then a spot check of the rules-layer skills. Method: each claim was traced to the source that owns it
(standards body, fab, EDA vendor, semiconductor vendor). IPC and ASME standards are paywalled, so only their official
tables of contents and previews were read. Where only a secondary source was found, the row says so and the confidence
is lowered. Nothing in the skills, scripts or `docs/design.md` was changed.

Legend. **Verdict:** agrees / partly / disagrees / unsourced (the skill gives no primary source and none was found that
settles it). **Confidence:** H = read in the primary source; M = primary table of contents or preview plus a consistent
secondary source; L = secondary source only, or not read.

## Summary

**Overall verdict.** The plugin is unusually careful about sources, and most vendor-derived numbers check out. JLCPCB
fab minimums, the RF copy-the-reference practice, and the IPC-2221 B2 column (rev B) all match their sources. Where the
plugin departs from industry practice, the cause is usually one of three things: a house style presented as a rule, a
standard revision that has moved on, or a citation that does not say what the skill says. The top findings, in priority
order:

1. **The 4-layer stack-up template (SIG / GND / PWR / SIG) has a weak source and works against the plugin's own rules.**
   - Its source is one SATA redriver datasheet. TI's general guide recommends at least six layers for high-speed
     interfaces and gives no 4-layer stack-up [S12]. It also says not to reference high-speed signals to a power plane
     [S11], and on this template the bottom layer does exactly that.
   - ADI's EMI series prefers two inner ground layers on 4-layer boards [S14].
   - On JLC04161H-7628 the GND–PWR core is 1.065 mm [S16]. That gives only about 3.8 pF/cm² *(derived)*, so the stated
     benefit (plane bypass capacitance) is negligible.
2. **Clearance classes use only IPC-2221 column B2, from a superseded revision.**
   - IPC-2221C (Dec 2023) supersedes rev B and restructures clearance into line-of-sight, dielectric and creepage
     categories [S5][S6].
   - Component terminations have their own column: A6 in rev B, A7 in rev C. At 16–30 V it is larger than B2 (0.25 vs
     0.10 mm; secondary source [S9]). So `PWR_*_24V` pads can sit at the 0.15 mm fab value.
   - The "coated (B4)" column in `power-pcb-layout` §3.8 holds the A5 values, not B4.
3. **The RC snubber recipe contradicts its own citation.** Nexperia AN11160 rev 3.1 sets C_S at 1–2 × C_LK and
   R_S ≈ 1.5 × √(L/C_S), with damping ζ = R/(2Z₀) between 0.5 and 1 [S27]. The skill says R = √(L/C) "for damping of 1"
   (ζ = 0.5 by AN11160's definition) and C_S "a few times" C_LK.
4. **The current-capacity citation is wrong, and the plugin contradicts itself.**
   - IPC-2221B has no current-capacity chart: IPC-2152 replaced those charts [S5][S7]. The k = 0.048/0.024 fit belongs
     to the older IPC-2221/IPC-D-275 charts.
   - Using the external fit on inner layers is supported: IPC-2152 has one chart for internal and external conductors,
     and internal traces run cooler [S7][S8][S10].
   - But "it errs wide on outer layers" is unsourced, and `power-pcb-layout` §3.5 still uses k = 0.024 for inner layers.
5. **The "45° corners only, no tees, no jogs" gate is a house style enforced as a hard gate.**
   - Neither IPC-2221C's table of contents nor JLCPCB's capabilities page has a corner-angle rule [S5][S17].
   - The documented manufacturing concern is acute angles (acid traps), not 90° corners or tees [S20][S21].
6. **Teardrops on every pad and via are a hard gate, stricter than practice.**
   - KiCad's stated rationale is mechanical robustness and drill misregistration, which applies to drilled pads and
     vias [S3]. JLCPCB says "consider" them [S18].
   - Teardrops shift the impedance of differential pairs [S19], which are not excluded by default (only an RF regex is
     suggested).
7. **Assembly (DFA) rules are thin and partly wrong.**
   - JLCPCB requires edge rails (≥ 5 mm) and fiducials for standard assembly [S23]. No skill mentions them.
   - JLCPCB's part-to-part spacing depends on the package pair, from 0.15 mm (0402–0402) to 2.0 mm (BGA–BGA) [S22].
     The placement gate checks only courtyard overlap, and `reference-block` quotes a single "JLCPCB 0.5 mm".
   - JLCPCB also asks for consistent orientation, 3–5 mm edge keep-outs for MLCCs and crystals, and thermal reliefs on
     small pads [S24]. None of these is covered, and "connect SMD power pads solid" contradicts the last one when it is
     applied to small passives.
8. **The licence handling in `reference-block` is vague where the terms are strict.** TI's notice limits its resources
   to developing applications that use TI products and prohibits other reproduction and display [S36]. The plugin is
   meant to go public (D3), and one board repo commits TI-derived copper (`scripts/pcb/boost_drv8711.json`, D-040).
   Both need a recorded licence decision, not "TI's own terms".
9. **The promised footprint check does not exist.** D19 promises a footprint-vs-LCSC-package check, but
   `library_check.py` compares only symbol pins with footprint pads and checks the BOM fields. No skill cites the
   land-pattern standard (IPC-7352, May 2023, the successor guideline) [S29][S30].
10. **Power numbers are mostly fine, with these corrections:**
   - Bootstrap: TI's SLUA887A formula has no Qrr term. It adds rules the skill omits: C_BOOT ≥ 10 × C_g,
     C_VDD ≥ 10 × C_BOOT, and MLCCs rated about 2 × VDD [S26].
   - MLCC "2 × bus": vendors give no fixed multiplier and point to the part's DC-bias curve. They also report
     capacitance lost to DC-bias aging [S31][S32].
   - VDS ≤ 80 %: IPC-9592B Table A-3 is the right owner, but it could not be read [S28].

Also missing: test points and testability (IPC-2221C §3.6, §10.2.3, App. C), creepage checks, surge (fault) current in
conductors (IPC-2221C §6.2.1), BOM lifecycle, and ordering impedance control with coupons (§Gaps).

## Status (2026-11-20)

Each finding below was re-checked against its primary source before a skill changed. The owner's decisions are D31–D35 in `docs/design.md` §8.

- **Applied (corrections PR):** 1.2 and 8.1e (labelled house style, D31); 1.3 (teardrop scope, D33); 1.6 (4-layer default, D32); 1.9, 2.1–2.6, 8.1a–8.1d (IPC-2221C, current fit, clearance B2/A7, vias at 18 µm, thermal reliefs); 1.1 and 2.8 (JLCPCB recommendations, impedance ordering); 4.3, 4.4, 4.2 (ASME Y14.44, IPC-2612, IPC-7352 and unverified EasyEDA footprints); 5.1, 5.4 (mini-gate after the pin-map freeze, fab DFM review); 6.2–6.7 (TVS waveform, MLCC bias, snubber per AN11160, bootstrap per SLUA887A, SLVA477, derived H-bridge ripple); mcu-circuit-design decoupling (Microchip 6 mm); doc-only gaps: test points, fault current, creepage, impedance ordering, via-in-pad, EMC pre-compliance, IPC acceptance class.
- **Applied to `reference-block` (PR #8):** 7.1, 7.3 (D35), 7.4.
- **Built in the checks PR:** 3.1, 3.3, 3.4, 5.2 (assembly spacing, orientation, edge keep-outs, fiducials), 4.1 (footprint vs LCSC package), 5.3 (lifecycle).
- **Not changed:** 1.4, 1.5 (KiCad behaviour already documented), 1.8 (JLCPCB stack-up page garbled; not re-read), 3.2 (decoupling gate kept as distance; Microchip's number added to the rules), 3.5, 3.6 (pin assignment of boot and strap pins: documented in the checks PR), 6.1 (IPC-9592B values not read), 6.9.

---

## 1. pcb-design-rules

Files: `plugins/hardware-design/skills/pcb-design-rules/SKILL.md` (lines given as `L<n>`),
`profiles/jlcpcb.json`, `profiles/stackups.json`, `scripts/copper.py`.

| # | Claim (where) | Verdict | What the primary source says | Source | Conf. | Recommended change |
|---|---|---|---|---|---|---|
| 1.1 | JLCPCB minimums: 4L track/space 0.09/0.09, via 0.15/0.25, PTH ring 0.15 (4L) / 0.18 (2L), NPTH 0.50, hole-to-hole 0.20, pad hole 0.45, PTH-to-track 0.28 (0.35 rec.), SMD pad-pad 0.15, edge 0.20, mask 0.10, silk 0.15/1.0/0.15 (L139–149, `jlcpcb.json`) | agrees | Same values on the capabilities page. The page also gives: via diameter preferably 0.15 mm over the hole, preferred via hole 0.2 mm, PTH ring 0.20 mm recommended on multilayer, mask web 0.13 mm for black and white, 0.4 mm copper to a V-cut edge, average hole plating 18 µm | [S17] JLCPCB *PCB Capabilities* | H | Add the recommended values (via ring 0.075, PTH ring 0.20, V-cut edge 0.4, black/white mask 0.13) to `design`, and plating 18 µm to `notes` (it matters for via current, §8.2) |
| 1.2 | "45° corners only": `track_angle (min 135)`; `right_angle_corners`, `track_junctions` (tees) and `jogs` are **hard** gates (L62, L86–89) | disagrees (as an industry rule) / agrees (as house style) | IPC-2221C's table of contents has no section on conductor corners or angles; the nearest are Fig. 10-2/10-3 (neck-down, routing between lands). JLCPCB's capabilities page sets no angle rule. The manufacturing concern in vendor literature is **acute** angles (acid traps). At MCU edge rates, the signal-integrity effect of a 90° corner is minimal (secondary summaries of measurements) | [S5] IPC-2221C TOC §10.1; [S17]; [S20] Cadence blog (secondary); [S21] Hackaday summary (secondary) | M | Keep `acute_corners` hard. Make `right_angle_corners`, `track_junctions` and `jogs` soft, or label them "house style" in the SKILL so they are not presented as fab or IPC requirements |
| 1.3 | Teardrops on every netted pad and via; `teardrops_disabled` is hard (L64, L107; `copper.py set_teardrops`) | partly | KiCad: teardrops add mechanical robustness and protect against drill misregistration on drilled pads and vias. JLCPCB: "consider" them where the annular ring is small, on flex and under BGAs; unnecessary on conductors over 20 mil. Altium: not required for reliability, and they shift the odd-mode impedance of pairs at vias | [S3] KiCad 10 PCB Editor, Teardrops; [S18] JLCPCB blog; [S19] Altium (secondary) | M | Hard gate on vias and PTH pads only. Make SMD-pad teardrops soft. Exclude by **net class** by default (`DIFF_*`, `RF_50`), not only by a user regex |
| 1.4 | KiCad 10 teardrop parameters 0.5 / 1 mm / 1 / 2 mm, curved, filter 0.9, prefer zone (`copper.py` L47–50) | agrees in meaning; values not verified | The manual defines best length/width ratio, maximum length/width, curved edges, the track-width filter, "prefer zone connections" and "allow two segments", but the excerpt read gives no default values | [S3] | L | Keep. Cite the board file the values were read from (the skill does, L235) |
| 1.5 | A custom rule overrides the Board Setup minimum (measured on 10.0.6, L188) | disagrees with the manual (skill's own measurement) | The manual says a Constraints minimum "cannot be overridden with a more specific design rule" | [S3] | H (manual) | Keep the fab-floor pass. File a KiCad bug with the test board, and link it from L188 |
| 1.6 | 4-layer template SIG / GND / PWR / SIG, sourced to the SN75LVCP600S datasheet §11.1 (L160, `stackups.json`) | disagrees (as a general default) | SPRAAR7J §3.12 recommends at least six layers and gives no 4-layer stack-up. §2.4 says TI does not recommend power-plane references for high-speed signals. ADI's EMI series prefers outer signal layers with **both inner layers ground**. On JLC04161H-7628 the L2–L3 core is 1.065 mm, so the interplane capacitance the template cites is about 3.8 pF/cm² *(derived: ε₀·4.6/1.065 mm)* | [S11] SPRAAR7J §2.4; [S12] SPRAAR7J §3.12; [S14] ADI, Niemann, Part 4; [S16] JLCPCB stack-up FAQ | M | Default to SIG / GND / GND / SIG (power as pours on the signal layers or one inner layer), or SIG / GND / PWR / SIG only with a stated reason. Fix the "bypass capacitance" justification for thick-core stack-ups. Make `signal_over_plane_gap_mm` and the reference-plane model treat a PWR reference as a warning |
| 1.7 | Fast signals never across a split or void; stitching caps if they must (L115, `stackups.json` rules) | agrees | SPRAAR7J §2.4: route over solid ground, not across splits or voids; if unavoidable, stitching capacitors of 1 µF or less at the crossing | [S11] | H | None |
| 1.8 | Stack-up numbers JLC04161H-7628: prepreg 0.2104 mm, εr 4.4; inner copper 0.0152 mm (`jlcpcb.json`) | partly | JLCPCB's stack-up FAQ lists the 7628 prepreg at about 0.2 mm and the core at 1.065 mm. Its εr table reads 4.62 for 7628, and inner copper 0.0175 mm (the page text is garbled) | [S16] | L | Re-read both from JLCPCB's impedance calculator, and record which page each number comes from |
| 1.9 | IPC-2221B cited for Table 6-1 (L232) | partly | IPC-2221C (December 2023) supersedes 2221B. It updates minimum electrical clearance and adds creepage and dielectric-spacing subsections | [S5] IPC-2221C TOC; [S6] ANSI listing | M | Cite IPC-2221C and re-check the values (see 2.4) |
| 1.10 | Severity of `creepage` set to error (L53) | partly | KiCad's creepage check only fires with a creepage constraint. IPC-2221C §6.3.3 now covers creepage | [S5] | M | Write creepage rules from the voltage classes (see Gaps), or say that no creepage rule is set |

## 2. pcb-copper

Files: `plugins/hardware-design/skills/pcb-copper/SKILL.md`, `scripts/netclasses.py`.

| # | Claim (where) | Verdict | What the primary source says | Source | Conf. | Recommended change |
|---|---|---|---|---|---|---|
| 2.1 | Width from "IPC-2221's external fit", I = 0.048·ΔT^0.44·A^0.725 (L32; `netclasses.py` L68–73); IPC-2221B cited (L95) | partly | IPC-2221B's table of contents has no current-capacity chart or figure. IPC-2152 "replaces the existing conductor-sizing charts in IPC-2221". The fit belongs to the historical IPC-2221/IPC-D-275 external chart, made for one board type and one copper weight | [S5] IPC-2221B and C TOCs; [S7] Jouppi, PCD&F 2009; [S10] Cadence (secondary) | M | Cite it as "the historical IPC-2221(A) external chart fit, superseded by IPC-2152", not IPC-2221B |
| 2.2 | The same fit for inner layers, because IPC-2152 found internal and external conductors close in temperature rise and IPC-2221's internal chart was not based on tests (L32) | agrees | IPC-2152 §5 has one chart, Fig. 5-1 "Internal and External Conductors (All Environments)". Jouppi: internal and external reach close to the same rise; internal ones run cooler; the historical internal chart was not based on tests. Brooks and Adam: internal traces are cooler everywhere in their IPC-2152 analysis | [S8] IPC-2152 TOC (Fig. 5-1); [S7]; [S10b] Brooks & Adam, SI Journal | M | None for the direction. Note that `power-pcb-layout` §3.5 still uses k = 0.024 internal (8.1) |
| 2.3 | "It errs wide on outer layers" (L36) | unsourced | Jouppi calls IPC-2152's charts conservative in almost all cases. No primary source compares the old external fit with IPC-2152 Fig. 5-1 for the currents used here; Brooks places IPC-2152 data "in between" older data sets without saying which side | [S7b] Jouppi in I-Connect007; [S10c] Brooks, I-Connect007 | L | Remove the claim, or check the 0.5–5 A table against IPC-2152 Fig. 5-1 (buy the standard) and state the margin |
| 2.4 | `_<V>V` clearance from Table 6-1 column B2: 0.1 / 0.6 / 0.6 / 1.25 / 2.5 mm up to 500 V (L22; `netclasses.py` L54) | partly | The B2 values match the commonly reproduced rev-B table. But rev B also has column **A6** (external component lead/termination, uncoated), which KiCad's net-class clearance also governs because it applies to pads. A6 is larger than B2 at 16–30 V (0.25 vs 0.10 mm) and at 0–15 V (0.13 vs 0.10). Rev C renames the categories (A7 is now "External Component Lead, Uncoated"); a secondary transcription of rev C gives B2 = 0.64 mm at 31–150 V and a solder-mask column. JLCPCB's own blog prints a different table, so secondary copies disagree | [S5] IPC-2221B/C TOCs §6.3; [S9] pcb-toolkit transcription of rev C (secondary); [S9b] JLCPCB blog (secondary, inconsistent) | M (structure) / L (rev-C values) | Use max(B2, A6/A7, fab) for classes with a voltage, from a purchased IPC-2221C. Note altitude (B2 is sea level to 3050 m). Cite rev C |
| 2.5 | A net at or above the width of 3 A on 1 oz must be a pour (L34, D21) | unsourced (house rule) | No standard or vendor source sets a pour threshold. `power-pcb-layout` §3.5 "pours, not tracks" is itself unsourced | — | — | Label D21 as a project decision in the SKILL, not as a sourced rule |
| 2.6 | Vias: about 1 A per 0.3 mm via, I/1 A vias per layer change (L35, from `power-pcb-layout` §3.5, which assumes 25 µm plating) | unsourced | JLCPCB's average hole plating is 18 µm. With 18 µm, the old external fit gives about 1.4 A per 0.3 mm via at ΔT 10 °C, and the internal fit about 0.7 A *(derived; wall area π·d·t)*. IPC-2152 Appendix A covers vias | [S17]; [S8] IPC-2152 TOC App. A | M | Compute from the fab's plating (18 µm) and IPC-2152 App. A. State the result as derived, not as a rule |
| 2.7 | Every net needs a class; Default is an error (L24) | unsourced (house rule) | No standard requires it. It is a reasonable review discipline | — | — | Keep, labelled as a project rule |
| 2.8 | Impedance classes: set width from the fab calculator (L21) | partly | JLCPCB offers impedance control on 4+ layers at ±10 %. It has to be ordered; it is not automatic. IPC-2221C App. A has updated test-coupon designs | [S17]; [S6] | M | Add "order impedance control" to the checklist when any `DIFF_*` / `RF_50` class is used |

## 3. pcb-placement

Files: `plugins/hardware-design/skills/pcb-placement/SKILL.md`, `scripts/place.py`, `scripts/pins.py`.

| # | Claim (where) | Verdict | What the primary source says | Source | Conf. | Recommended change |
|---|---|---|---|---|---|---|
| 3.1 | Courtyard overlap is the only spacing constraint; "assembly spacing beyond courtyards" is not seen (L44, L52) | partly | KiCad's library courtyards add 0.25 mm (0.15 mm below 0603, 0.5 mm for connectors and crystals, 1.0 mm for BGA), citing IPC-7351C. So two touching courtyards leave about 0.5 mm. JLCPCB's recommended minimums depend on the package pair: chip–chip 0.15–0.35 mm, chip–QFN 1.0, QFN–QFN 1.0, QFP–QFP 1.25, BGA–BGA 2.0 mm | [S29] KiCad KLC F5.3; [S22] JLCPCB *Minimum spacing for SMD components* | H | Add a package-pair spacing table to the fab profile (`profiles/jlcpcb.json`) and enforce it in `gate`. Courtyards alone pass QFN/QFP neighbours that JLCPCB asks to keep 1 mm or more apart |
| 3.2 | Decoupling: distance to the nearest pad on the net, weighted ×2; measured p90 6.0–8.5 mm (L42, L64–66) | partly | Vendor rules ask for "as close to the pins as possible", on the same side, with the trace no longer than 6 mm where space is tight (Microchip). The metric is straight-line distance to any pad on the net, which is shorter than the trace and blind to side | [S33] Microchip PIC16(L)F18425/45 §2.2.1 | H | Gate on the capacitor-to-assigned-pin distance, with a hard limit from the MCU's datasheet (for example 6 mm), and require the same side |
| 3.3 | Rotation and side are kept; the optimizer ignores orientation (L42) | gap | JLCPCB: standardise orientation (polarised parts one way, pin 1 in the same corner) to simplify inspection | [S24] JLCPCB *Top 10 PCB design tips for SMT soldering* | H | Add an orientation-consistency check to `gate` (soft) |
| 3.4 | Edge inset `--edge-mm` 0.5 (L44) | partly | JLCPCB: keep MLCCs, BGAs and crystals 3–5 mm from edges, especially V-groove lines. Fiducials need 3.35 mm from the board edge, with rails of at least 5 mm | [S24]; [S23] | H | Per-class edge keep-outs (MLCC, crystal, BGA) in the gate. Note that V-scored panels need more |
| 3.5 | The owner places and locks anchors; the optimizer places the rest (L14–18) | agrees with common practice; no primary source checked | Vendor layout guides (TI, ADI, ST) order placement by critical loops and connectors first. No standard was found that defines "anchors" | — | L | None |
| 3.6 | Pin assignment by minimum distance (Hungarian), within alternate functions (L92–106) | agrees (method) / gap | No industry standard covers it. The limits listed (no bus ordering, peripheral clashes) are honest. Not covered: pins with special reset states or boot straps, ADC channel speed classes, 5 V-tolerance, and timer break or complementary outputs | — (ST pin data, cited by the skill) | L | Exclude boot/strap and debug-at-reset pins unless named in the needs. Make `mcu-circuit-design`'s safe-state table an input |

## 4. schematic-capture

Files: `plugins/hardware-design/skills/schematic-capture/SKILL.md`, `scripts/library_check.py`; `docs/design.md` D19.

| # | Claim (where) | Verdict | What the primary source says | Source | Conf. | Recommended change |
|---|---|---|---|---|---|---|
| 4.1 | D19: "a footprint-vs-LCSC-package check" (design.md L39). The SKILL tells the user to check by hand (L88). `library_check.py` checks pin/pad correspondence and LCSC/MPN fields (L79) | disagrees (implementation vs plan) | Code inspection: no package-dimension comparison exists. IPC-7352 (May 2023) is the current land-pattern guideline, with courtyard determination (§3.3), naming (§3.4) and zero orientation (§7) | [S30] IPC-7352 TOC | H (code) / M (IPC) | Implement the check: compare the footprint's pad count, pitch and body size against the LCSC package and JLCPCB's footprint. Cite IPC-7352 for land patterns and zero orientation |
| 4.2 | easyeda2kicad as the second source of footprints (L88) | partly | EasyEDA footprints are not generated to IPC-7352 rules, while KiCad's library is generated to KLC, which cites IPC-7351C | [S29]; [S30] | M | Treat imported footprints as unverified until the 4.1 check and a datasheet land-pattern comparison pass |
| 4.3 | References n01–n99 per sheet (U301) (L30) | agrees (low confidence) | ASME Y14.44-2008 (R2024) is the current US reference-designation standard. Its contents include a "Block Numbering Method" (App. A). IEEE 200-1975 is withdrawn | [S34] ASME Y14.44 preview; [S35] IEEE 200 status | L (titles only) | Cite ASME Y14.44 (class letters, §7) instead of no source |
| 4.4 | Drawing conventions: titled boxes, notes with sources, every pin connected or no-connect, labels on every net (L28–35) | partly | IPC-2612 (2010) sets requirements for schematic documentation: net naming with reserved characters (§7), spares (§8.2), a ground and power table (§8.3), off-page references (§4.4), bypass capacitors (§4.6) and variants (§9.5) | [S37] IPC-2612 preview TOC | M | Add a power/ground table and spare-gate handling to the root page. Follow §7.3 reserved characters (the plugin already avoids `/` in sheet names) |
| 4.5 | Net-class directive labels carry the class (L54) | agrees | KiCad-specific; no standard. Consistent with deriving net classes from a power map (`power-pcb-layout` §2) | — | — | None |
| 4.6 | ERC: "Run build and check in CI next to ERC" (L83); the Phase-1 gate requires ERC clean (template `plan.md`) | agrees | IPC-2612 has no ERC clause. ERC is EDA practice | — | — | None |

## 5. hardware-project

Files: `plugins/hardware-design/skills/hardware-project/SKILL.md`, `templates/docs/plan.md`, `scripts/jlc_stock.py`,
`scripts/export_jlcpcb.py`.

| # | Claim (where) | Verdict | What the primary source says | Source | Conf. | Recommended change |
|---|---|---|---|---|---|---|
| 5.1 | Phases 0–4 with owner-signed gates (L47) | agrees with common practice; not audited against a standard | No primary source was read for stage gates. Note the order problem: the pin map is assigned in Phase 3 (`plan.md` step 3) and changes the schematic after the Phase-1 gate | — | L | After the pin-map freeze, re-run the Phase-1 checks (schgen check, ERC, `library_check`, `trace.py`) as a mini-gate |
| 5.2 | JLC export: Gerbers, BOM, CPL; "rotations checked in the fab's viewer" (L76, L87) | gap | JLCPCB requires edge rails (≥ 5 mm) and fiducials for standard assembly: 1 mm pads, 2 mm mask opening, 3–4 of them, 3.35 mm from the edge | [S23] | H | Add a DFA pre-flight: fiducials present (or JLCPCB-added rails ordered), edge distances, package-pair spacing (3.1) |
| 5.3 | `jlc_stock.py`: stock, Basic/Extended, price, MPN vs LCSC (L74) | partly | Code inspection: no lifecycle (NRND/EOL) or second-source check | — | H (code) | Report lifecycle status where LCSC exposes it, and flag single-source extended parts |
| 5.4 | Reviewer agent on the exported package (L60–67) | agrees | No primary source. There is no explicit DFM step (the fab's DFM analysis on the Gerbers) before the order | — | L | Add "fab DFM report reviewed" to the Phase-4 gate |
| 5.5 | Verify methods R / S / B / T (L45) | agrees (convention) | Not audited against a standard | — | — | None |

## 6. power-circuit-design

File: `plugins/hardware-design/skills/power-circuit-design/SKILL.md`.

| # | Claim (where) | Verdict | What the primary source says | Source | Conf. | Recommended change |
|---|---|---|---|---|---|---|
| 6.1 | Steady bus ≤ 80 % of V(BR)DSS, rule of thumb; "IPC-9592B sets derating" (L102, L195) | unsourced (honestly flagged) | IPC-9592B (Nov 2012) has §4.4 "Derating Guidelines" and Table A-3 "Derating Guidelines for Diodes and Transistors", but the values were not readable. A fab blog gives 80–90 % with no source. NAVSEA SD-18 gives no MOSFET VDS factor on its web page | [S28] IPC-9592B TOC; [S28b] allpcb (secondary); [S28c] NAVSEA SD-18 | L | Buy IPC-9592B and cite Table A-3, or adopt a named derating policy. Until then keep "rule of thumb" |
| 6.2 | TVS: SMBJ15A V_RWM 15 V, V_C 24.4 V at rated pulse current, ratio about 1.6 (L49, L196) | agrees | The Littelfuse SMBJ/SMCJ 15A family lists V_C 24.4 V | [S38] Digi-Key listing of Littelfuse SMCJ15A (same V_C) | M | Say that V_C is at I_PP of the 10/1000 µs waveform, and lower at smaller currents |
| 6.3 | Class-II MLCCs rated about 2 × the bus (L136, L197) | partly | Würth ANP062 gives no multiplier and points to per-part DC-bias data: a 25 V X7R 2.2 µF loses 69 % at rated voltage. Vishay: X7R parts at 40 % of rated voltage lost over 20 % more capacitance in 1000 h under bias (aging), beyond the instant DC-bias loss. TI SLUA887A does give "about 2 × VDD" for bootstrap MLCCs | [S31] Würth ANP062; [S32] Vishay white paper; [S26] TI SLUA887A | M | Rule: effective capacitance from the part's DC-bias curve plus an aging margin. Keep 2 × only as a screening default, citing SLUA887A for the bootstrap case |
| 6.4 | RC snubber: R_S = √(L/C) for damping 1; C_S "a few times" the loop capacitance (L185, L198) | disagrees | AN11160 rev 3.1 (21 Oct 2024): find C_LK and L_LK from the frequency shift with a known C_add. C_S of 1–2 × C_LK is a good starting point. Z₀ = √(L_LK/C_S), ζ = R_S/(2Z₀), target 0.5–1, R_S,opt ≈ 1.5 Z₀. R_S·C_S ≤ one tenth of the on-time. P = C_S·V²·f | [S27] Nexperia AN11160 rev 3.1 | H | Rewrite step 3 to AN11160's numbers, and add the R_S·C_S time-constant limit |
| 6.5 | Bootstrap: C_BOOT ≥ Q_G,total/ΔV_BOOT, with Q_G,total including the diode's Qrr and the leakage over the longest on-time [SLUA887] (L120) | partly | SLUA887A Eq. 3: Q_total = Q_G + I_HBS·D_max/f_sw + I_HB/f_sw, with no Qrr term. ΔV_HB = VDD − V_DH − V_HBL (the HB UVLO). Rules: C_BOOT ≥ 10 × C_g, C_VDD ≥ 10 × C_BOOT, MLCC about 2 × VDD; fast or Schottky diode rated above the DC link | [S26] TI SLUA887A | H | Cite the formula as written, define ΔV from the UVLO, add the 10× rules, and source the Qrr term elsewhere or drop it |
| 6.6 | Inductor ripple 20–40 % [SLVA477B] (L81, L200) | agrees | SLVA477 (now rev C) suggests 20–40 % of output current when the datasheet gives no value | [S25] TI SLVA477C | H | Cite rev C |
| 6.7 | Bulk ripple I_bus·√(D(1−D)) [SLTA055]; three-phase by Kolar & Round (L138–139) | partly | Not re-read. SLTA055's expression is for a buck input capacitor. Applying it to an H-bridge with all ripple in the capacitor is derived | — | L | Mark the H-bridge use *(derived)* |
| 6.8 | Regeneration V₂ = √(V₁² + 2E/C) (L144) | agrees | Energy balance ½C(V₂² − V₁²) = E *(derived)* | — | H | None |
| 6.9 | Fuse breaking capacity, electrolytic life 2× per 10 °C, reverse polarity [SLVA139] | not verified | Not read in this audit | — | L | None, pending a read |

## 7. reference-block

File: `plugins/hardware-design/skills/reference-block/SKILL.md`.

| # | Claim (where) | Verdict | What the primary source says | Source | Conf. | Recommended change |
|---|---|---|---|---|---|---|
| 7.1 | Copy where the layout is the design and the vendor measured it (RF, NFC, fast power loops) (L16–23) | agrees | ST AN5165 §6.9: "Be sure to copy the reference design exactly with the same stack-up." Its checklist adds that stack-up or spacing changes affect the match. Nordic: the RF part "should be a direct copy of our reference design", while one-to-one copies are hard and component tuning is needed | [S39] ST AN5165 §6.9, §5.3.1; [S40] Nordic DevZone nRF52 PCB guidelines (marked unmaintained) | H | Add AN5165 §6.9 and the Nordic guide as primary citations for §1 |
| 7.2 | "A copy is not the vendor's tested board"; stack-up and impedance must be re-checked (L27, L116) | agrees | AN5165: matching values depend on the reference PCB definition. Nordic: tuning is needed for each custom design | [S39]; [S40] | H | None |
| 7.3 | Licence: ST under OPLA; "TI's design files come with TI's own terms"; keep the block in `reference/` if derived data may not be published (L31) | partly | TI's notice allows use only for developing applications that use the TI products, prohibits other reproduction and display, and grants no other IP licence. ST's OPLA text was not read; a related ST limited licence (SLA0058) requires reproducing ST notices and limits use to ST products | [S36] TI *Important Notice and Disclaimer*; [S41] ST SLA0058 | M (TI) / L (ST OPLA) | State TI's terms explicitly. Default to keeping TI-derived block JSON in the gitignored `reference/` for public repos unless counsel agrees otherwise. Read OPLA and quote its distribution clause |
| 7.4 | "Assembly spacing … (JLCPCB 0.5 mm)" (L119) | disagrees | JLCPCB's minimums depend on the package pair (0.15–2.0 mm). Its SMT tips start at about 0.5 mm from small passives and 1–2 mm from larger ICs | [S22]; [S24] | H | Point to the package-pair table (3.1) instead of a single number |
| 7.5 | `kicad-cli pcb import` converts PADS, Altium, Eagle, CADSTAR, Fabmaster, P-CAD, SOLIDWORKS (L42, L150) | not verified | The CLI manual page was not reachable in this session | — | L | None |

## 8. Rules-layer skills (spot check)

Only clear contradictions with primary sources are listed.

### 8.1 power-pcb-layout

| # | Claim (where) | Verdict | What the primary source says | Source | Conf. | Recommended change |
|---|---|---|---|---|---|---|
| 8.1a | IPC-2221 with k = 0.024 internal; "IPC-2152 (more realistic) or IPC-2221 (conservative)" (L95) | disagrees (internally and with IPC-2152) | `pcb-copper` uses 0.048 on inner layers on IPC-2152's evidence (2.2). Jouppi: the historical internal chart is untested and overly conservative; IPC-2152's charts are themselves conservative in almost all cases | [S7]; [S7b] | M | Align with `pcb-copper`: one fit for both, with the IPC-2152 rationale |
| 8.1b | Via budget 1 A per 0.3 mm via at 25 µm plating (L105) | unsourced | JLCPCB plates 18 µm on average (see 2.6) | [S17] | H | Use the fab's plating |
| 8.1c | "Connect SMD power pads solid" (L106) | partly | JLCPCB: connect small pads to large copper with thermal reliefs ("four 10 mils (0.254mm) spokes for most connections") to avoid tombstoning | [S24] | H | Solid for power-device pads and exposed pads. Reliefs for small passives on pours |
| 8.1d | Table 6-1: "External, coated (B4)" column 0.13 / 0.13 / 0.4 / 0.4 / 0.8 (L124–130) | disagrees | In rev B those values are A5 (conformal coating over the assembly). B4 (permanent polymer coating) has 0.05 mm up to 30 V. A6 (uncoated terminations) is missing | [S5] rev B/C category titles; [S9] (secondary values) | M | Relabel the column A5. Add A6/A7. Move to rev C |
| 8.1e | Quality bar: "45° corners only" (L162) | house style | See 1.2 | [S5]; [S17] | M | Label as house style |

### 8.2 rf-layout, high-speed-digital-layout, interface-layout, mcu-circuit-design, analog-circuit-design, circuit-simulation

- **rf-layout** §1–§2 (copy the reference stack-up, solid L2, follow the vendor) agrees with AN5165 §6.9 and Nordic
  [S39][S40]. No contradiction found.
- **high-speed-digital-layout** §2.2 (stitching capacitors ≤ 1 µF at a reference change, no power-plane reference)
  agrees with SPRAAR7J §2.4 [S11]. It is consistent with finding 1.6, which `pcb-design-rules` should adopt.
- **analog-circuit-design** §9: Johnson noise of 4 nV/√Hz at 1 kΩ and 12.8 nV/√Hz at 10 kΩ checks out (√(4kTR) at
  298 K) *(derived)*.
- **mcu-circuit-design** §2: "as close as possible" agrees with vendor wording. It could add Microchip's explicit
  6 mm maximum trace [S33].
- **interface-layout** and **circuit-simulation**: not audited beyond a scan; no contradiction seen.

## Gaps: practice expected but not covered

| Gap | What practice expects | Source | Where it belongs |
|---|---|---|---|
| Test points and testability (DFT) | IPC-2221C §3.6 "Test Requirement Considerations", §10.2.3 "Test Points", test-land free areas (Fig. 3-2) and a testability design checklist (App. C) | [S5] | `pcb-placement` (test-pad keep-outs), `hardware-project` (bring-up) |
| Fiducials, edge rails, panelisation, tooling holes | JLCPCB requires rails ≥ 5 mm and fiducials for standard assembly. IPC-2221C covers fiducial clearance (Fig. 5-11) and array X-out fiducials (Fig. 5-14) | [S23]; [S5] | `hardware-project` export pre-flight; `pcb-design-rules` profile |
| Package-pair assembly spacing, orientation, edge keep-outs | JLCPCB spacing matrix; consistent orientation; 3–5 mm keep-out for MLCC/BGA/crystal | [S22]; [S24] | `pcb-placement` gate, fab profile |
| Thermal relief on small pads | Spokes on small pads tied to large copper (tombstoning). IPC-2221C §9.1.3 covers thermal relief in planes | [S24]; [S5] | `pcb-copper` / `power-pcb-layout` |
| Land-pattern standard | IPC-7352 (2023): courtyard, naming, zero orientation | [S30] | `schematic-capture` library policy |
| Creepage | IPC-2221C §6.3.3 creepage categories; KiCad creepage rules not written by any script | [S5] | `pcb-copper` (voltage classes) |
| Surge or fault current in conductors | IPC-2221C adds §6.2.1 "Surge Current". Traces carry the fault current until the fuse opens, which continuous-current sizing does not cover | [S5] | `pcb-copper`, `power-circuit-design` §5 |
| Impedance ordering and coupons | Order impedance control (JLCPCB ±10 %); coupon designs in IPC-2221C App. A | [S17]; [S6] | `pcb-copper` checklist |
| Via-in-pad process | JLCPCB POFV (filled and capped) is an option, the default on 6+ layers; open vias in pads wick solder | [S17]; [S24] | fab profile notes |
| BOM lifecycle and second source | Not checked (code inspection of `jlc_stock.py`) | — | `hardware-project` |
| EMC pre-compliance plan | Only `rf-layout` mentions a pre-compliance scan. ADI's series treats stack-up and power routing as EMI controls | [S14] | `hardware-project` Phase 4 |
| Acceptance class | No skill states the IPC product class (2 or 3) the board is designed and ordered to (IPC-6012 / IPC-A-610 not read) | — | `hardware-project` requirements |

## Sources

Primary unless marked *(secondary)*. "TOC" means only the publisher's table of contents or preview was read.

- [S3] KiCad, *PCB Editor* manual, 10.0: Board Setup Constraints, Net Classes, Teardrops. https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html
- [S5] IPC-2221C, *Generic Standard on Printed Board Design*, Dec 2023, TOC (supersedes 2221B, Nov 2012): §6.2.1, §6.3, §9.1, §10.1, §3.6, §10.2.3, App. C, Figs 5-8/5-11/5-14. https://www.electronics.org/TOC/IPC-2221C-TOC.pdf ; IPC-2221B TOC (§6.3.1–6.3.7 categories B1–A7; no current-capacity figure): https://www.electronics.org/TOC/IPC-2221B.pdf
- [S6] ANSI Webstore, IPC-2221C-2023 listing (changes: minimum electrical clearance, impedance tolerances, test coupons). https://webstore.ansi.org/standards/ipc/ipc2221c2023
- [S7] M. Jouppi, *The New IPC-2152*, Printed Circuit Design & Fab, 2009. https://pcdandf.com/pcdesign/index.php/2009-archive-articles/5305-the-new-ipc-2152
- [S7b] *Just Ask Happy: Calculating trace temps in a vacuum*, I-Connect007 (Jouppi's answers). https://iconnect007.com/article/123539/just-ask-happy-calculating-trace-temps-in-a-vacuum/123542/design
- [S8] IPC-2152, *Standard for Determining Current-Carrying Capacity in Printed Board Design*, TOC (Fig. 5-1 "Internal and External Conductors (All Environments)"; App. A vias). https://www.electronics.org/TOC/IPC-2152.pdf
- [S9] *(secondary)* pcb-toolkit, `spacing.rs` (transcription of IPC-2221C Table 6-1). https://docs.rs/crate/pcb-toolkit/latest/source/src/spacing.rs
- [S9b] *(secondary)* JLCPCB blog, *PCB voltage clearance guide* (prints values that differ from other transcriptions). https://jlcpcb.com/blog/pcb-voltage-clearance-guide
- [S10] *(secondary)* Cadence, *IPC-2152 vs. IPC-2221*. https://resources.system-analysis.cadence.com/blog/ipc-2152-vs-ipc-2221-which-to-use-for-pcb-thermal-analysis
- [S10b] D. Brooks, J. Adam, *Internal Trace Temperatures: More Complicated Than We Think*, Signal Integrity Journal. https://signalintegrityjournal.com/articles/1596-internal-trace-temperatures-more-complicated-than-we-think
- [S10c] D. Brooks, *Trace Currents and Temperature, Part 2*, I-Connect007. https://iconnect007.com//article/72371/trace-currents-and-temperature-part-2-empirical-results/72374/design
- [S11] TI, SPRAAR7J *High-Speed Interface Layout Guidelines*, §2.4. https://www.ti.com/document-viewer/lit/html/SPRAAR7J/GUID-AD6D2D54-84AC-47F5-A2ED-87883A148A25
- [S12] TI, SPRAAR7J §3.12 *Suggested PCB Stackups*. https://ti.com/document-viewer/lit/html/SPRAAR7J/GUID-2F542943-9F4A-4BB9-B015-CEE6A2B2D111
- [S13] TI, SN75LVCP600S datasheet §11.1 (cited by the skill; body not readable in this session). https://ti.com/document-viewer/SN75LVCP600S/datasheet/layout
- [S14] J. Niemann (ADI), *Passing EMI Compliance Testing the First Time — Part 4: Power Routing and Stack-Up Planning*. https://www.analog.com/en/resources/technical-articles/passing-emi-compliance-testing-first-time-part-4.html
- [S16] JLCPCB, *PCB Stackup* FAQ (7628 4-layer: prepreg ≈ 0.2 mm, core 1.065 mm; text partly garbled). https://jlcpcb.com/quote/pcbOrderFaq/PCB%20Stackup
- [S17] JLCPCB, *PCB Manufacturing Capabilities*. https://jlcpcb.com/capabilities/PCB-capabilities
- [S18] JLCPCB blog, *PCB Teardrop You Should Know*. https://jlcpcb.com/blog/pcb-teardrop-you-should-know
- [S19] *(secondary)* Altium, *Should You Place Teardrops on Differential Pairs?* https://resources.altium.com/p/should-you-place-teardrops-differential-pairs
- [S20] *(secondary)* T. Lockman (Cadence), *Make Acute Angles a Sharp Problem of the Past*, Semiconductor Engineering. https://semiengineering.com/make-acute-angles-a-sharp-problem-of-the-past
- [S21] *(secondary)* Hackaday, *What's the deal with square traces on PCBs*. https://hackaday.com/2019/06/26/whats-the-deal-with-square-traces-on-pcbs
- [S22] JLCPCB Help, *Minimum spacing for SMD components*. https://jlcpcb.com/help/article/minimum-spacing-for-smd-components
- [S23] JLCPCB Help, *How to add edge rails/fiducials for PCB assembly order*. https://jlcpcb.com/help/article/how-to-add-edge-rails-fiducials-for-pcb-assembly-order
- [S24] JLCPCB blog, *Top 10 PCB Design Tips for High-Quality SMT Soldering*. https://jlcpcb.com/blog/pcb-design-tips-to-improve-smt-soldering-quality
- [S25] TI, SLVA477C *Basic Calculation of a Buck Converter's Power Stage*. https://ti.com/lit/pdf/SLVA477
- [S26] TI, SLUA887A *Bootstrap Circuitry Selection for Half-Bridge Configurations*. https://ti.com/lit/SLUA887
- [S27] Nexperia, AN11160 *Designing RC snubbers*, rev 3.1, 21 Oct 2024 (Mouser copy). https://www.mouser.lt/pdfDocs/AN11160.pdf
- [S28] IPC-9592B, *Requirements for Power Conversion Devices…*, Nov 2012, TOC (§4.4; Tables A-1 to A-6). https://www.electronics.org/TOC/IPC-9592B.pdf
- [S28b] *(secondary)* ALLPCB, *Derating guidelines for power supply components*. https://www.allpcb.com/allelectrohub/derating-guidelines-for-power-supply-components
- [S28c] NAVSEA Crane, SD-18 *Discrete Semiconductors: Derating*. https://www.navsea.navy.mil/Home/WarfareCenters/NSWCCrane/Resources/SD-18/Products/DiscreteSemiconductors/Derating/
- [S29] KiCad Library Conventions, F5.3 *Courtyard layer requirements*. https://klc.kicad.org/footprint/f5/f5.3/ ; PCB Libraries forum (T. Hausherr) on IPC courtyard excess *(secondary)*: https://pcblibraries.com/Forum/printer_friendly_posts.asp?TID=3372
- [S30] IPC-7352, *Generic Guideline for Land Pattern Design*, May 2023, TOC. https://www.electronics.org/TOC/IPC-7352-TOC.pdf
- [S31] Würth Elektronik, ANP062 *LC filter design with MLCCs: why the applied voltage matters*. https://community.element14.com/products/manufacturers/wuerth-elektronik/w/documents/3986/anp062-lc-filter-design-with-mlccs-why-the-applied-voltage-matters
- [S32] Vishay, *Time-dependent capacitance drift of X7R MLCCs exposed to constant DC bias voltage*. https://www.vishay.com/docs/45263/timedepcapdrix7rmlccexptoconstdcbiasvolt.pdf
- [S33] Microchip, PIC16(L)F18425/45 datasheet §2.2.1 *Decoupling Capacitors*. https://onlinedocs.microchip.com/oxy/GUID-1D0144A3-6E9C-49D4-850F-2F7000F00CDF-en-US-8/GUID-71E742B2-6F76-4E03-8CBC-F4DB94ED0311.html
- [S34] ASME Y14.44-2008, *Reference Designations for Electrical and Electronics Parts and Equipment*, preview (TOC). https://webstore.ansi.org/preview-pages/ASME/preview_ASME+Y14.44-2008.pdf ; reaffirmed 2024: https://webstore.ansi.org/standards/asme/asmey14442008r2024
- [S35] IEEE 200-1975, status "Inactive-Withdrawn". https://standards.ieee.org/standard/200-1975.html
- [S36] TI, *Important Notice and Disclaimer* (as published with TI documents). https://software-dl.ti.com/C2000/docs/software_guide/notice.html
- [S37] IPC-2612-2010, *Sectional Requirements for Electronic Diagramming Documentation*, preview (TOC). https://webstore.ansi.org/preview-pages/IPC/preview_IPC+2612-2010.pdf
- [S38] Digi-Key, Littelfuse SMCJ15A listing (24.4 V clamp). https://www.digikey.com/en/products/detail/littelfuse-inc/SMCJ15A/762382
- [S39] ST, AN5165 *How to develop RF hardware using STM32WB MCUs*. https://www.st.com/resource/en/application_note/an5165-how-to-develop-rf-hardware-using-stm32wb-mcus-stmicroelectronics.pdf
- [S40] Nordic Semiconductor DevZone, *General PCB design guidelines for nRF52 series* (marked no longer maintained). https://devzone.nordicsemi.com/guides/hardware-design-test-and-measuring/b/nrf5x/posts/general-pcb-design-guidelines-for-nrf52-series
- [S41] ST, *Limited License Agreement for ST Materials* (SLA0058). https://st.com/resource/en/license_agreement/dm00266773.pdf

**Not read** (paywalled, unreachable, or out of time): full texts of IPC-2221B/C, IPC-2152, IPC-9592B, IPC-7352,
IPC-2612, ASME Y14.44; the ST OPLA text; the body of the SN75LVCP600S §11.1; the KiCad 10 CLI manual; Littelfuse
*Fuseology*; Würth SN008; the Cornell Dubilier life model; Kolar & Round (2006); TI SLTA055 and SLVA139; IEC 60664-1 and
IEC 62368-1; IPC-6012 and IPC-A-610; Henry Ott's stack-up paper and Brooks' right-angle-corner appendix (pages
reachable but no body text).
