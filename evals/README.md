# Evals

Do the skills make Claude's hardware work better, and by how much? Each case runs the same task through headless
Claude Code **with** and **without** the plugin on a copy of a real board, and scores the result from the files against
the human baseline (the owner's own placement). See `docs/design.md` §5.

This folder is the **generic harness**. The **cases live in each board repo** (`<board-repo>/evals/cases/*.json`),
because the anchors and the commit to test belong to that board. Fixtures are built on demand from the board repo's
git history, so no board files are copied anywhere.

```bash
pip install -r evals/requirements.txt
python3 evals/test_evals.py                                          # self-test, no KiCad or Claude needed
python3 evals/make_fixture.py <board-repo>/evals/cases/placement.json # fixture only, to open in KiCad
python3 evals/run.py <board-repo>/evals --dry-run                    # the commands it would run
python3 evals/run.py <board-repo>/evals --case placement --runs 1    # one run per configuration
python3 evals/run.py <board-repo>/evals                              # everything, before a release tag
```

A placement run costs real money and can take up to an hour (`max_budget_usd` and `timeout_min` in each case).
Run it by hand, not in CI. Work directories go to `<board-repo>/evals/work/` (gitignore it there); summaries to
`<board-repo>/evals/results/`.

## Review: seeded defects

`review_defects.py` measures a design review on a real board, with no Claude run needed for the scripted part:

```bash
python3 evals/review_defects.py run <board.kicad_pcb> [--schematic root.kicad_sch] --voltage VBAT=12.6 --out <dir>
python3 evals/review_defects.py score <dir>/manifest.json --report <agent-review.md>   # score any review
python3 evals/test_review_defects.py                                                   # self-test
```

`run` plants one defect of each kind it finds a target for in a copy of the board and scores the scripted checks
on it. `score` grades any review (the board-reviewer agent's report, a human's) against the planted defects. See
`design-review` §5 for the defect kinds and the first measurements.

## A case

```json
{
  "kind": "placement",
  "source": {"commit": "<sha>", "board": "hardware/<name>/<name>.kicad_pcb"},
  "anchors": {"locked": true, "prefixes": ["J", "MH"], "refs": ["U301"]},
  "runs": 3, "timeout_min": 60, "max_budget_usd": 25
}
```

- `source`: the board at a pinned commit of the repo the case is in. Its `.kicad_pro` and `.kicad_dru` come along
  if they exist.
- `anchors`: `locked` takes the footprints the owner locked; `prefixes` and `refs` add parts by reference.
- `prompt` (optional): a built-in prompt (`prompts/<name>.md`, default: the `kind`) or a path relative to the case.

The fixture keeps the anchors (locked), parks every other footprint right of the outline, grouped by schematic
sheet, and drops tracks, vias, groups and copper zones (teardrops included); rule areas stay. `baseline.json` is the
source board's own score.

## Scores (`placement_metrics.py`, in the pcb-placement skill)

A run is **valid** when no anchor moved, every parked part is inside the outline, no courtyards overlap (real
outlines, so notches count) and no copper was added. For valid runs, lower is better:

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
