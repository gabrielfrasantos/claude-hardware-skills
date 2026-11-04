---
name: circuit-simulation
description: Build and run SPICE (ngspice + Python) simulations of analog and power circuits from a KiCad schematic, covering loop stability, corners, transients, protection, noise and PSRR, with a reproducible report.
---

# Circuit simulation (ngspice + Python, values from KiCad)

Use this skill to verify an analog or power design before layout or bring-up. Typical cases:
- regulation-loop stability;
- load and line transients;
- short circuit and protection timing;
- range switching;
- noise and PSRR;
- the effect of tolerances.

The deliverable is a **reproducible simulation suite** in the repo, next to the KiCad project, plus a **report** that states pass/fail against the spec and proposes concrete value changes.

## 1. Principles

1. **The schematic is the single source of truth.** Read every R, C and L value from the KiCad schematic files; never retype them. Keep proposed changes in one override dict (`PROPOSED = {"C304": 5.6e-9, ...}`) so "as drawn" and "proposed" run side by side. Once a change is accepted, it moves into the schematic and leaves the dict.
2. **Model only what the question needs, and say what is ideal.** For example:
   - an upstream converter as an ideal source with an optional ripple;
   - relays and switches as datasheet resistances;
   - a DAC as an ideal source.
   
   List every simplification at the top of the netlist builder and in the report.
3. **Use real models for the parts that set the answer:** the op amps in the loop, the pass/switch FETs, the sense amplifiers, the diodes that clamp. Use vendor SPICE models, run in the right compatibility mode (§4). Vendor models are usually **typical** values [NEXPERIA-IAN50012]. When a part has several models (typical vs weak FET), keep both and treat the choice as a corner.
4. **Every number in the report is reproducible** from one command, and is written to `results/` (CSV/JSON) with the plots in `plots/`. Raw simulator output goes to `work/` (gitignored).
5. **Check simulations against hand calculations.** Before trusting a sweep, check one operating point and one transfer function by hand: divider ratios, DC gain, a pole frequency. A simulation that disagrees with arithmetic is wrong until explained.

## 2. Suite layout

```
simulation/
├── README.md            # requirements, how to run, file table
├── REPORT.md            # findings, proposed changes, plots (the deliverable)
├── kicad_values.py      # parse *.kicad_sch -> {ref: value}, skips DNP, parses 4k7 / 2.2u 50V / 15m 1%
├── <design>_netlist.py  # builds the netlist from values + PROPOSED + keyword options (load, Cload, mode)
├── spice.py             # ngspice batch driver, wrdata reader, loop-gain + margin helpers, op-point check
├── loop.py              # loop gain at the chosen break point
├── corners.py           # corner list + parallel evaluation
├── sweep.py             # full stability matrices (as drawn vs proposed) -> results/*.csv
├── transients.py        # load step, line step, short, range switching, setpoint steps, PSRR, Zout
├── make_plots.py        # all plots + results/summary.json
├── models/              # vendor models (check their licence before committing)
├── results/  plots/     # committed outputs
└── work/                # raw output, gitignored
```

## 3. Workflow

1. **Scope.** From the spec, write the questions as testable statements, for example:
   - "CV phase margin ≥ 45° at every corner";
   - "a dead short is limited to < X A within Y µs";
   - "range-up dip < Z mV".
   
   Each statement becomes a check with pass/fail.
2. **Netlist builder.** One function with keyword arguments for every condition you will sweep: setpoint, load (R, I or open), output capacitance and ESR, range/mode, model variant, and the loop-probe insertion.
3. **Operating point first, and verified.** `.op` can converge to a solution the real circuit never reaches: a latched state, the wrong side of a diode-OR, or an unstable equilibrium. Run a **power-up transient of a DC-identical, heavily damped copy** of the circuit (extra capacitance on the slow nodes, sources ramped from 0). Use its end state as `.nodeset` and confirm `.op` agrees within a tolerance before any AC analysis. If they disagree, report it; that is a finding.
4. **Loop gain** at the point where the loop is closed through a single path, usually the controller output or gate-drive node:
   - Use a method that accounts for loading in both directions: **Tian's** (two AC runs, voltage and current injection) or **Middlebrook's** double injection [Tian][Middlebrook].
   - For a single loop with no parallel path around the injection point, the result doesn't depend on where you inject [Wiedmann].
   - Compute crossover, phase margin and gain margin from the complex loop gain T, with closed loop = 1/(1+T).
   - Target **≥ 45°** phase margin at the worst corner [SLYT858]. Use a stricter target if the spec asks for low overshoot.
   - Breaking the loop with a huge L and C fixes the DC point but not the impedances at the break, so it is error-prone [Wiedmann]. Use it only as a quick look.
5. **Corners.** Build an explicit list:
   - load: none, light, nominal, full;
   - output capacitance: none, typical, maximum allowed, with realistic ESR;
   - setpoint: min, mid, max;
   - mode/range;
   - model variant;
   - temperature (where models support it);
   - tolerance extremes for the compensation parts.
   
   Run in parallel; the corners are independent. Report the **worst case and the median**, not just a typical case.
6. **Monte Carlo** for tolerance-driven questions (offset, gain, ratio accuracy, phase-margin spread [SLYT858]). Use per-instance statistical functions on the component values, with a fixed seed so results are reproducible (§4). Report the distribution and the 3σ or worst value.
7. **Transients** that match how the circuit is used and abused:
   - load steps in each range;
   - line steps and ripple on the input;
   - setpoint up and down steps, with and without load (down-programming);
   - mode hand-over (e.g. CV→CC);
   - **short circuit from regulation, with and without the hardware protection**;
   - range switching under a load step;
   - start-up and shut-down.
8. **Frequency-domain extras:** PSRR (AC on the supply node), output impedance (1 A AC into the output), and noise (`.noise`, output and input-referred, integrated over the spec bandwidth).
9. **Fix and confirm.** Change values in `PROPOSED`, rerun the full corner matrix and the transients, and confirm that no other check got worse. Prefer the fewest changes, and keep standard E-series values and C0G/thin-film parts where they matter.
10. **Report** (§6).

## 4. ngspice practicalities

Section numbers refer to the ngspice User's Manual (v45/v46). The current release is **ngspice-47** (2026); some pages on the website lag behind [NG-DL].

- **Batch runs.** Run `ngspice -b -o run.log circuit.cir`. Put the analyses in a `.control … .endc` block: `run`, then `wrdata`/`write`, then `quit` [NG §12.3–12.4].
  - `.meas` can't be combined with `-b -r rawfile`, because the data is streamed to the file. Use the control-language `meas` instead; it also stores each result as a vector [NG §11.4, §13.5.50].
- **`wrdata file vecs`** writes ASCII columns in (scale, value) pairs; complex vectors give (scale, re, im).
  - `set wr_singlescale` prints the scale column once.
  - `set wr_vecnames` adds a header row.
  - All vectors must come from the same plot [NG §13.5.106].
- **No `.step`.** Sweep with a control script: `foreach`/`while` + `alter dev param = value` + `run` [NG §12.14.4.3, §13.5.3]. After `alterparam`, a `reset` is required before the change takes effect [NG §13.5.5].
  - For corner matrices it is simpler and faster to generate one netlist per case from Python and run the cases in parallel processes.
- **`.noise v(out) src dec N f1 f2`** gives `onoise_spectrum`/`inoise_spectrum` (plot `noise1`) and `onoise_total`/`inoise_total` (plot `noise2`). `set sqrnoise` gives power densities. The KLU solver can't run `.noise` [NG §11.3.4].
- **Temperature.** The default is 27 °C. `.temp` overrides `.options temp`; `tnom` sets the nominal temperature. Per-device `temp`/`dtemp` are supported, and `.dc temp …` sweeps temperature [NG §1.3.2, §2.14].
- **Vendor models need a compatibility mode,** set in `.spiceinit` [NG §12.11]:

  | Setting | Use |
  |---|---|
  | `set ngbehavior=psa` | PSpice/TINA libraries, whole netlist translated |
  | `set ngbehavior=ps` | PSpice, only `.include`d files translated |
  | `set ngbehavior=lta` | LTspice syntax, including 4K7 notation |
  | `set ngbehavior=ltpsa` | both PSpice and LTspice |
  | `ki` (flag) | KiCad's "/" vector names |

  - In ps mode, `.lib` behaves like `.include`.
  - **KiCad's simulator sends `ltpsa` by default** [KICAD-SRC].
  - **Encrypted vendor models don't run in ngspice**; ask the vendor for an unencrypted PSpice model or pick another part [NG-MODELS].
- **Convergence.**
  - Defaults: GMIN 1e-12, RELTOL 1e-3, ITL1 100, ITL4 10.
  - When DC fails, ngspice tries gmin stepping, then source stepping (`gminsteps`, `srcsteps`). `method=gear` damps trapezoidal ringing; over-damping (e.g. a large `xmu`) can hide a real oscillation.
  - `rshunt` (needs XSPICE) fixes "no DC path" errors [NG §11.1.2–11.1.4].
  - `.nodeset` helps only the DC solution. `.ic` *without* `uic` is the preferred way to set initial conditions [NG §11.2].
  - Most DC failures are connection or value errors; check those first. `set ngdebug` dumps the processed netlist [NG §1.4.3, §12.16].
- **Monte Carlo.**
  - Set `option SEED=n` in `.spiceinit` for reproducible runs [NG §18.1].
  - `gauss(nom, rel, sigma)` and `agauss(nom, abs, sigma)` are Gaussian; `unif` and `aunif` are uniform; `limit(nom, abs)` gives ± corners.
  - A `.param` is evaluated once, while a function on a device line is drawn per instance. A function on a shared model gives every user of that model the same value [NG §18].
  - The manual's control-language examples (`MonteCarlo.sp`, `MC_ring.sp`) loop `alter` + `run` [NG §18.5.2].
- **From KiCad.** `kicad-cli sch export netlist --format spice` exports a full SPICE netlist [KICAD-CLI]. KiCad's own simulator reads the `Sim.Device`, `Sim.Params`, `Sim.Pins` and `Sim.Library` symbol fields [KICAD-SRC]. A Python netlist builder that reads only the values is still the better fit for parametric sweeps (§1).
- **Python.**
  - Running ngspice as a subprocess is the simplest and parallelizes well.
  - The shared library (`libngspice`) allows in-process control [NG Ch. 15].
  - **spicelib** is maintained: `RawRead` and `SimRunner` support ngspice. **PySpice** has had no release since 2021; **InSpice** is its maintained successor [PYPI].
- **Power-MOSFET models.**
  - Infineon models come in levels 0–3; level 3 is electro-thermal, with Tj/Tcase pins, and Tcase must be connected. Infineon recommends Gear integration [IFX-AN].
  - Nexperia electrothermal models give **typical** values, not process limits [NEXPERIA-IAN50012].
  - For SOA questions, either way, run a weak/strong variant as a corner.

## 5. Pitfalls seen in practice

- **Integrator wind-up hides in steady state.** An error amplifier that is not in control (e.g. the CC amp while in CV) sits at its rail, so a mode change takes its full recovery time. Simulate the hand-over, not just each mode alone.
- **Capacitors on sensitive nodes can create new loops.** A capacitor on an op amp's inverting input can make the op amp's local feedback ring even when the main loop is fine. Check the op-amp output node in transients, not only the regulated output.
- **Ideal sources hide interactions.** If a result depends on the upstream converter's output impedance or response time (e.g. a short with a tracking pre-regulator), model at least a first-order version of it, or state the result as an optimistic bound.
- **Slew-limited amplifiers dominate fast events.** Sense and range amplifiers often slew at under 1 V/µs. Use the real model, never an ideal gain block, for timing questions.
- **Over-tight tolerances aren't free.** If the margins depend on a 1 % capacitor, make that a corner rather than assuming it.

## 6. The report (REPORT.md)

1. **One paragraph of scope:** what was simulated, what is ideal, and the command that reproduces everything.
2. **Numbered findings, most important first.** Each has the number, the condition and why it matters. For example: "CV phase margin −92° worst case, 52 of 150 cases below 0°; sustained oscillation at 12 V / 1 A (plot)".
3. **Proposed changes table:** Ref | As drawn | Proposed | Why. Parts added or removed are included.
4. **Before/after** stability summary: worst case, median, crossover range.
5. **Plots:** Bode of the worst corners, the key transients, and protection timing with vs without the hardware path.
6. **Constraints for firmware and other blocks** that the simulation revealed, e.g. a DAC code that must be clamped, or a protection that must stay armed.
7. **Limits of the model:** what was not simulated, and what to verify on the bench.

## 7. Done checklist

- [ ] All values read from the schematic; proposed changes isolated in one dict and listed in the report.
- [ ] Simplifications listed; vendor models used for loop-critical parts; model variants run as corners.
- [ ] Operating point verified against a power-up transient.
- [ ] Loop gain with a loading-aware method; worst case and median margins over the full corner list.
- [ ] Transients include abuse cases (short, mode hand-over, range switch), with and without protection.
- [ ] Results reproducible from one command; outputs in `results/` and `plots/`; raw data gitignored.
- [ ] Hand-calculation cross-check recorded.
- [ ] Report gives pass/fail per spec statement, proposed changes and firmware constraints.

## 8. References

- **[NG]** ngspice User's Manual (v45/v46), ngspice.sourceforge.io/docs.html. Sections cited inline.
- **[NG-DL]** ngspice releases (ngspice-47), sourceforge.net/projects/ngspice/files/ng-spice-rework/.
- **[NG-MODELS]** ngspice, *Models for ngspice*, ngspice.sourceforge.io/modelparams.html (vendor and encrypted models).
- **[KICAD-CLI]** KiCad 9.0 documentation, *Command-Line Interface* (`sch export netlist --format spice`).
- **[KICAD-SRC]** KiCad 9.0 source, `eeschema/sim/` (Sim.* fields; default `ngbehavior=ltpsa`).
- **[PYPI]** PyPI project pages for spicelib, PySpice, InSpice and PyLTSpice.
- **Middlebrook**, R. D., *Measurement of Loop Gain in Feedback Systems*, Int. J. Electronics 38(4):485–512, 1975; and *The General Feedback Theorem: A Final Solution for Feedback Systems*, IEEE Microwave Magazine 7(2):50–63, 2006.
- **Tian**, M., Visvanathan, V., Hantgan, J., Kundert, K., *Striving for Small-Signal Stability*, IEEE Circuits and Devices Magazine 17(1):31–41, 2001. DOI 10.1109/101.900125.
- **Wiedmann**, F., *Loop gain simulation* (comparison of the methods; why breaking the loop with L/C is error-prone), sites.google.com/site/frankwiedmann/loopgain.
- **[SLYT858]** TI, Analog Design Journal 3Q 2024: phase-margin targets (45° recommended), Monte Carlo of phase margin.
- **[IFX-AN]** Infineon, *Introduction to Infineon's Simulation Models* (Power MOSFET model levels 0–3).
- **[NEXPERIA-IAN50012]** Nexperia, *Precision Electrothermal models for Power MOSFETs*.
