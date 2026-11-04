---
name: power-pcb-layout
description: Lay out, route or review KiCad PCBs with power stages (switching converters, half-bridges, linear pass FETs, high-current copper, shunts, thermal, isolation), following the parts the user has placed.
---

# Power PCB layout (KiCad)

Use this skill to place, route or review boards that carry power: buck/boost converters, half-bridges and motor drives, linear pass elements, high-current paths, shunt measurement, relays and isolated sections. It covers:
- the **workflow**: the user places the main parts and you follow;
- the **layout rules** for power devices;
- the **KiCad mechanics**;
- the **quality bar** the result must meet.

The goal is a board a senior layout engineer would sign, not one that merely passes DRC.

## 1. Working agreement: the user places, you follow

1. **The user's placement is the anchor set.**
   - Read anchors from the board: locked footprints (`fp.IsLocked()`), or a list the user gives. If neither exists, ask which parts are fixed before touching anything.
   - **Never move, rotate or flip an anchor.** If a rule cannot be met with the anchors as placed (a hot loop that can't close, a shunt facing the wrong way, a heatsink part away from the edge), stop. Report the conflict with the specific move that would fix it and why, and wait.
2. **The board outline, mounting holes, connector positions and keepouts are the user's.** Do not change them.
3. **Tell the user what to anchor.** When asked what to pre-place, list:
   - connectors and terminals;
   - parts on heatsinks or at the board edge;
   - power switches, inductors and transformers;
   - bulk and input/output capacitors;
   - shunts;
   - isolation parts (isolators, isolated DC/DCs, optocouplers, relays);
   - the MCU and anything mechanical (buttons, LEDs, displays).
   
   Everything else you place.
4. **Deliver in phases and show each one** as per-layer renders (§6.4), so the user can redirect early:
   1. support-part placement;
   2. power copper;
   3. critical routes;
   4. remaining routing;
   5. final fills and DRC.
5. **Ask before starting if any of these are unknown:**
   - current per power path (continuous and peak);
   - voltage between nets and between domains;
   - stackup and copper weights (outer/inner);
   - fab house and its tier;
   - assembly sides;
   - heatsink and mechanical constraints;
   - the switching frequency of each converter.

## 2. Intake: turn the netlist into a power map

Before placing anything, build a table and keep it in the work notes:

| Net / group | Kind | I cont / peak | V max | Rule |
|---|---|---|---|---|
| e.g. VIN→Q1.D | high current | 10 A / 15 A | 30 V | pour, 3 layers, ≥ N vias per transition |
| SW_BUCK | switch node | 3 A | 30 V | minimal copper, keep away from sense |
| R1 Kelvin taps | sense | µA | 30 V cm | differential pair from the inner pad edges |
| GND_ISO vs GND | isolation | — | 60 V | gap ≥ X mm on every layer |

Classify every net as one of: **high-current, switch node, hot-loop member, gate drive, sense/Kelvin, feedback, analog reference, digital, isolation boundary**. Derive the net classes from this table, never the other way round.

## 3. Rules for power devices

### 3.1 Hot loops: the first thing to get right
Identify each converter's **high-di/dt loop** and make it the smallest physical loop on the board. Put its HF capacitor (100 nF–1 µF, 0402/0603) **closest to the switch pins**, before the bulk caps.

| Topology | Hot loop |
|---|---|
| Buck | input cap → high-side switch → low-side switch/diode → input cap GND |
| Boost | output cap → diode/high-side → low-side switch → output cap GND |
| Half-bridge / motor phase | bus HF cap → HS FET → LS FET → (shunt) → cap GND |
| Flyback | primary: bulk cap → transformer → switch → (sense R) → cap; secondary: winding → diode → cap |

- On 4+ layers, put an unbroken GND plane **directly under** the loop (layer 2). The return then images under the top-layer path, giving a "vertical loop" of minimal area.
- **Switch node:** use only the copper the current needs. It is an antenna, so keep sense, feedback and analog traces away from it on every layer, and never route them underneath it.
- Follow the regulator datasheet's **layout section exactly**: pin-out driven cap placement, exposed-pad via pattern, AGND/PGND tie. It overrides generic rules.

### 3.2 Gate drive
- Place the driver within a few mm of the FET.
- **Gate loop:** driver out → R_gate → gate → source → driver return. Keep it small, and route it as a pair with the return.
- Use the **Kelvin source** pin when the package has one.
- Put the gate resistor at the FET and the gate-source pull-down at the FET.
- Put bootstrap capacitors next to BOOT/SW, and the bootstrap diode next to the VCC cap.

### 3.3 Feedback and compensation
- Place the FB divider and compensation network **at the IC pins**. Route only the high-impedance node short.
- Take the sense line from the regulation point (output cap or load), not from the inductor pad.
- Return the divider to quiet AGND.

### 3.4 Grounding
- Prefer **one solid ground plane**. Split AGND/PGND only when the datasheet asks, and tie them at the single point it names (usually the exposed pad).
- **Never cut a plane under a trace that carries return current.** Return current follows the path of least inductance, directly under the trace.
- Each isolated domain gets its own plane. Signals stay over their own domain's plane.

### 3.5 High-current copper
- Use **pours, not tracks**. Duplicate them on several layers and stitch them with via arrays at every transition and along the length.
- Size them with IPC-2152 (more realistic) or IPC-2221 (conservative). IPC-2221: $I = k \cdot \Delta T^{0.44} \cdot A^{0.725}$, with A in mil² and k = 0.048 external, 0.024 internal. 1 oz = 35 µm = 1.378 mil.

  ```python
  def width_mm(I, dT=10, oz=1.0, internal=False):
      k = 0.024 if internal else 0.048
      area_mil2 = (I / (k * dT ** 0.44)) ** (1 / 0.725)
      return area_mil2 / (1.378 * oz) * 0.0254
  # 10 A, 1 oz, 10 °C: external ≈ 7.2 mm, internal ≈ 18.7 mm
  ```

- **Vias:** budget about 1 A continuous per 0.3 mm drill via (25 µm plating) and use at least I/1 A vias at each layer change. More vias cut both resistance and heat.
- **Necks.** The narrowest point sets the rating: check pad entries, spoke connections and gaps between pours. Connect SMD power pads **solid**. Thermal reliefs on THT pins must have spoke width × count ≥ the required width.
- **Specify inner copper weight** to the fab; many default to 0.5 oz inner.
- High-current connectors should have copper on all layers and multiple vias per pin.

### 3.6 Current sensing
- **Kelvin sense.** Take the sense traces from the **inner edges** of the shunt pads (or the dedicated sense pads of 4-terminal shunts). Route them as a tight differential pair to the amplifier, with the filter at the amplifier. No load current may flow in them.
- Orient the shunt so the current flows straight through it with no bend at the pads. Keep the amplifier out of the shunt's heat.
- For high-ohm ranges, keep guard spacing around the high-impedance node, and keep leakage paths (flux, nearby high-voltage copper) away.

### 3.7 Linear pass elements and thermal
- Put heatsink-mounted parts at the board edge, with the tab toward the heatsink, and leave mounting-hardware clearance. A live tab needs an insulator or a clearance note.
- **Exposed pads:** use the datasheet via pattern. Otherwise use 0.3 mm vias at 1.0–1.2 mm pitch, connected solid to planes on every layer. Make sure the paste pattern (windowpane) suits the via treatment.
- SMD dissipation needs copper area on several layers. Estimate $R_{\theta JA}$ from the datasheet's copper-area curves, and never assume the 25 °C rating.
- Keep electrolytics, voltage references, precision dividers and crystals away from hot parts.

### 3.8 Isolation and clearance
- **Functional clearance**, IPC-2221 Table 6-1, in mm:

  | V (DC/peak) | Internal (B1) | External, uncoated (B2) | External, coated (B4) |
  |---|---|---|---|
  | 0–30 | 0.05 | 0.1 | 0.13 |
  | 31–100 | 0.1 | 0.6 | 0.13 |
  | 101–150 | 0.2 | 0.6 | 0.4 |
  | 151–300 | 0.2 | 1.25 | 0.4 |
  | 301–500 | 0.25 | 2.5 | 0.8 |
- **Safety isolation** (mains, user-touchable) follows IEC 62368-1 / IEC 60664-1 creepage and clearance, plus the isolator's datasheet. That is a separate, larger requirement. Use slots to gain creepage.
- **Nothing crosses an isolation gap on any layer**, inner planes and pours included. Only the isolator, the isolated converter, optocouplers and an intended Y-cap may straddle it. Mark the gap on silkscreen.

### 3.9 Decoupling and support parts (what you place)
- Put each decoupling cap on the **same side** as its IC, next to the pin it serves, with its own via to the plane at the pad, ordered smallest value nearest the pin.
- Snubbers (RC across the switch node or FET) go at the device. Input filters go at the connector, before the converter.
- Pull-ups and pull-downs that set a safe state (gate holds, enables) go near the device they hold.

## 4. Routing order

1. **Power copper:** zones with explicit priorities, stitching vias, the solid-vs-relief choice per net.
2. **Hot loops and switch nodes:** if they aren't already closed by placement, close them now.
3. **Critical routes, by hand or by script:**
   - Kelvin pairs;
   - gate loops;
   - feedback;
   - crystal;
   - USB or other differential pairs;
   - reference and ADC lines.
4. **Fine-pitch fan-out:** short escapes in a regular pattern, with vias on a grid.
5. **Everything else.** An autorouter is acceptable **only** for non-critical nets, and only with:
   - every pour and critical route locked;
   - keepouts protecting the pours (Freerouting treats pours as routable conduction areas and will cross them);
   - a clean-up pass afterwards (§5).
   
   For a board that must look professional, prefer to route these by script with layer-direction discipline, or leave them to the user in KiCad's interactive router, and say so.
6. **Fills, GND stitching** (about every 5 mm along plane edges and around RF/switching areas), **then DRC**.

## 5. Quality bar: "it passes DRC" is not done

Check each item, and fix or report every miss:
- **Layer-direction discipline.** On 2-layer and outer layers, mostly horizontal on one side and vertical on the other. Use 45° corners only; no acute angles and no random diagonals.
- **Directness.** Routed length / Manhattan distance ≤ 1.3 for most nets. Flag any net above 1.6.
- **Via economy.** At most 2 vias per signal connection unless justified. No via left in a pad without a reason, and no via-in-pad without filled/capped vias.
- **Few segments.** No staircase or jagged segments: merge collinear segments, remove sub-0.5 mm jogs, no stubs or dangling ends.
- **Grouping.** Buses and pairs routed together with consistent spacing; parallel runs aligned.
- **Pour quality.** No slivers under 0.5 mm, no isolated islands, no starved thermals. Pour edges follow the parts, not a raster.
- **Silkscreen.** References readable, on the side and orientation of their part, not on pads, not hidden by default. Polarity and pin-1 marks visible. Connector labels and the isolation-gap outline present.

A script can measure the metrics: per net, the segment count, vias, length/Manhattan ratio and acute angles. Report the worst ten.

## 6. KiCad mechanics

### 6.1 Versions and APIs
- **SWIG `pcbnew` Python** (KiCad 7–10) is deprecated since KiCad 9 and planned for removal in KiCad 11. The **IPC API** (`kicad-python`, KiCad 9+) talks to a running KiCad. Check what is installed (`python3 -c "import pcbnew"`, `kicad-cli version`) before choosing.
- **`kicad-cli`:**
  - `sch erc` and `pcb drc` exist from KiCad 8. On KiCad 7, run DRC through `pcbnew.WriteDRCReport`; there is no ERC.
  - `pcb export gerbers/drill/pos/svg/pdf` work from KiCad 7.
- Newer KiCad reads older files, but saving upgrades them, so keep the project's format unless the user asks.

### 6.2 Gotchas
- **Saving a board from SWIG Python (KiCad 7) rewrites the `.kicad_pro` and drops net-class patterns.** Re-write the net classes after each save. Run DRC in a **fresh process**, because KiCad caches the project in memory.
- **Refill zones before DRC and before plotting:** `pcbnew.ZONE_FILLER(board).Fill(board.Zones())`.
- Never delete items while iterating connectivity. Collect them first, dedupe by `m_Uuid.AsString()`, then call `board.Delete()`.
- Some vendor footprints set pads to "no zone connection" (e.g., SO-8FL drain pads), so pours silently skip them. Check `pad.GetZoneConnection()` and set INHERITED.
- Check footprint drills, annular rings and pad-to-pad gaps against the fab before routing (e.g., thermal vias drawn at 0.25 mm drill on a 0.3 mm process).
- Zone priority (`SetAssignedPriority`) decides which pour wins where they overlap. Set it explicitly.

### 6.3 Reading the user's placement
```python
import pcbnew
b = pcbnew.LoadBoard(path)
anchors = {f.GetReference(): (pcbnew.ToMM(f.GetPosition().x), pcbnew.ToMM(f.GetPosition().y),
                              f.GetOrientationDegrees(), f.IsFlipped())
           for f in b.GetFootprints() if f.IsLocked()}
```
Lock every footprint you place yourself only after the user approves that phase.

### 6.4 Look at the result
Render **every copper layer separately**, plus a composite of each side, after each phase, and actually view them:
- `kicad-cli pcb export svg -l <layer>,Edge.Cuts --exclude-drawing-sheet --page-size-mode 2`;
- rasterize with cairosvg or PyMuPDF.

Zoom crops on the hot loops, the shunts and the fine-pitch parts. Most layout defects are obvious in a picture and invisible in a DRC report.

## 7. Done checklist

- [ ] Anchors untouched; every conflict reported to the user with a proposed move.
- [ ] Power map table complete; net classes derived from it.
- [ ] Hot loops minimal, with the HF cap closest; switch-node copper minimal; GND plane unbroken under the loops.
- [ ] Gate loops short, with gate R and pull-down at the FET; bootstrap parts at the pins.
- [ ] FB divider and compensation at the IC; sense taken at the regulation point.
- [ ] High-current pours sized (IPC-2152/2221) per layer; via count per transition ≥ I/1 A; no necks; inner copper weight stated.
- [ ] Kelvin taps from the inner pad edges, routed as pairs; amplifier filter at the amplifier.
- [ ] Exposed-pad via arrays per datasheet; hot parts at the edge or heatsink; sensitive parts away from heat.
- [ ] Isolation gaps ≥ the requirement on every layer; nothing crosses; gap marked on silk.
- [ ] Quality bar (§5) met; metrics report attached.
- [ ] Zones refilled; DRC clean with schematic parity (KiCad 8+); ERC clean.
- [ ] Per-layer renders delivered to the user.

## 8. References

- IPC-2152 (current capacity) and IPC-2221 (Table 6-1 spacing, current formula).
- TI SLYT614, *Five steps to a great PCB layout for a step-down converter*.
- TI SNVA021, *AN-1149 Layout Guidelines for Switching Power Supplies*.
- Analog Devices AN-136, *PCB Layout Considerations for Non-Isolated Switching Power Supplies*.
- TI SLUP169, *Design and Application Guide for High Speed MOSFET Gate Drive Circuits* (gate-loop layout).
- The datasheet layout section of every regulator, driver and current-sense amplifier on the board. It takes precedence over this skill.
- KiCad Python API status: dev-docs.kicad.org/en/apis-and-binding/pcbnew/ (SWIG deprecated in 9.0, removal planned for 11.0).
