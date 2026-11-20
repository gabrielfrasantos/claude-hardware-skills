# Evals

Do the skills make Claude's hardware work better, and by how much? Each case runs the same task through headless
Claude Code **with** and **without** the plugin on a copy of a real board, and scores the result from the files against
the human baseline (the owner's own placement). See `docs/design.md` §5.

```bash
pip install -r evals/requirements.txt
python3 evals/test_evals.py                               # self-test, no KiCad or Claude needed
python3 evals/run.py --dry-run                            # the commands it would run
python3 evals/run.py --case pendulum-placement --runs 1   # one run per configuration
python3 evals/run.py                                      # everything, before a release tag
```

A placement run costs real money and can take up to an hour (`max_budget_usd` and `timeout_min` in each case).
Run it by hand, not in CI. Work directories go to `evals/work/` (gitignored); summaries to `evals/results/`.

## Cases

| Case | Fixture | Task | Baseline (owner's placement) |
|---|---|---|---|
| `pendulum-placement` | `fixtures/pendulum-anchors`: 84 anchors (connectors, switch, mounting/bracket holes, the ST RF and NFC copies with the MCU, the TI drive copy), 161 parts parked | place the parked parts | ratsnest 3540.9 mm, 735 crossings |
| `efoc-placement` | `fixtures/efoc-anchors`: the 9 parts the owner locked, 177 parked | place the parked parts | ratsnest 2191.6 mm, 221 crossings |

## Scores (`metrics.py`)

A run is **valid** when no anchor moved, every parked part is inside the outline, no courtyards overlap (real
outlines, so notches count), and no copper was added. For valid runs, lower is better:

- `ratsnest_mm`: sum over signal nets of the Manhattan minimum spanning tree of their pads;
- `crossings`: crossings between straight ratsnest edges of different nets, an estimate of vias and layer changes;
- `decap_p90_mm`: 90th percentile of the distance from a decoupling capacitor to the nearest IC pad on its net.

Ground and the nets the source board pours (`plane_nets` in the manifest) are left out: they are planes, not routes.
The summary gives each metric's median over valid runs and its ratio to the baseline. `within_limit` is the
placement gate's target (D25): ratsnest and crossings no worse than baseline × 1.10.

## Isolation

`run.py` starts Claude with `--setting-sources project` (the work directory has no project settings, so your user
settings and installed plugins don't load), `--strict-mcp-config` (no MCP servers) and, for `with-plugin` only,
`--plugin-dir plugins/hardware-design`. It keeps the stream-json transcript, and the results list the skills Claude
loaded, so a `without-plugin` run that loaded one of ours shows up. Flags checked against `claude --help` on
2026-11-20.

## Adding a fixture

Write a spec in `fixtures/specs/` (source repo, commit, board path, anchors) and generate it from a checkout of the
source at that commit:

```bash
python3 evals/make_fixture.py evals/fixtures/specs/<name>.json --source-root <checkout>
```

The fixture keeps the anchors (locked), parks every other footprint right of the outline, grouped by schematic
sheet, and drops tracks, vias, groups and copper zones (teardrops included); rule areas stay. `baseline.json` is
the source board's own score.
