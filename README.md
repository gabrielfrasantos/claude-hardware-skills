# claude-hardware-skills

Claude skills for electronics hardware design in KiCad. The rules come from vendor app notes and standards, and the workflows come from real boards ([e-psu](https://github.com/embedded-pro/e-psu-hardware), [e-foc](https://github.com/embedded-pro/e-foc-hardware)).

The repo is a Claude Code **plugin marketplace** (`hardware-skills`) with one plugin (`hardware-design`) that bundles the skills.

## Skills

| Skill | Use it to | Status |
|---|---|---|
| [`power-pcb-layout`](plugins/hardware-design/skills/power-pcb-layout/SKILL.md) | Lay out, route or review PCBs with power stages: hot loops, gate drive, high-current copper, Kelvin sensing, thermal, isolation. It follows the parts you place. | ready |
| `mcu-circuit-design` | Design the circuitry around a microcontroller: supplies and decoupling, reset/boot, clocks, debug, GPIO/connector protection, ESD, interfaces | in progress |
| `analog-circuit-design` | Design op-amp, reference, ADC-drive and sensor circuits: protection, noise, stability, component choice | in progress |
| `circuit-simulation` | Build an ngspice + Python simulation suite from a KiCad schematic, covering loop stability, corners, transients, protection, noise and a report | in progress |

## Install

### Claude Code

In a Claude Code session:

```
/plugin marketplace add gabrielfrasantos/claude-hardware-skills
/plugin install hardware-design@hardware-skills
```

Skills load automatically when a task matches their description. You can also call one by name, e.g. `/hardware-design:power-pcb-layout`.

To get updates, run `/plugin marketplace update hardware-skills`. You can also turn on auto-update for the marketplace under **Marketplaces** in `/plugin`. The plugin has no `version` field, so every commit to `main` is a new version.

### For everyone working in a hardware repo

Run this once from the hardware repo's root, then commit the `.claude/settings.json` it writes:

```bash
claude plugin marketplace add gabrielfrasantos/claude-hardware-skills --scope project
```

Teammates who trust the folder get the marketplace registered automatically.

### claude.ai

Each skill is a self-contained folder with a `SKILL.md`. Zip a skill folder (e.g. `plugins/hardware-design/skills/power-pcb-layout/`) and upload it as a skill in your claude.ai settings.

## Layout

```
.claude-plugin/marketplace.json           # marketplace "hardware-skills"
plugins/hardware-design/
├── .claude-plugin/plugin.json            # plugin "hardware-design"
└── skills/
    └── <skill-name>/SKILL.md             # one folder per skill
```

## Adding or changing a skill

1. Create `plugins/hardware-design/skills/<skill-name>/SKILL.md`. Give it front matter with `name` (kebab-case, same as the folder) and a one-sentence `description` that says *when* to use it.
2. **Every number needs a source.** Cite the app note or standard by document ID and title in the skill's References section. Don't add a rule you can't trace.
3. Keep skills **generic**: no project-specific part numbers except as labelled examples.
4. Validate before pushing:
   ```bash
   claude plugin validate .
   ```
