# Contributing

Thanks for helping. This repository is a Claude Code plugin of hardware-design skills. A skill is followed literally
by an agent designing a real board, so a wrong rule costs a respin. The bar is: **every rule traceable, every
script tested.**

## Ground rules

1. **Every number needs a source.** Cite the datasheet, app note or standard by document ID, section and title in
   the skill's References section, or mark the number *(derived)* and show the arithmetic, or call it a
   *rule of thumb* and list it with what would close it. A rule you can't trace doesn't go in.
2. **Primary sources win.** Vendors' own documents, standards bodies and fab capability pages, not blog posts.
   Where only a secondary source exists, say so next to the citation.
3. **Generic and vendor-neutral.** State the rule, say which datasheet parameter to look up, and give examples
   from several vendors. Never state one family's value as the rule. A board's part numbers appear only as
   labelled examples.
4. **House style is labelled as house style.** Where a rule is the project's choice rather than a standard's
   (e.g. 45° corners), the skill says so (`docs/design.md` D31).
5. **KiCad 10 and later only.** Scripts read and write `.kicad_pcb` / `.kicad_sch` as S-expressions and call
   `kicad-cli`; no new `pcbnew` (SWIG) code (D22).
6. **Board-specific files live in the board repos**, not here: eval cases, pin needs, vendor-derived blocks.
7. **Change the plan with a decision.** `docs/design.md` records the decisions (D1, D2, ...). A change of
   direction adds one.

## Layout

```
plugins/hardware-design/skills/<skill-name>/
├── SKILL.md             # front matter: name (= folder), description (when to use it)
├── scripts/             # optional: tools the skill calls, with test_*.py next to them
└── profiles/            # optional: data with sources and a checked date
```

Skills may import from `pcb-design-rules/scripts` (the shared core: parser, geometry, `kicad-cli` calls) and from
nothing else outside their own folder (D13).

## Before you open a pull request

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest ruff
.venv/bin/python -m pytest -q                       # every skill's self-tests; no KiCad needed
.venv/bin/ruff check --select F plugins evals       # pyflakes rules
claude plugin validate .                            # marketplace and plugin manifests
```

Tests build small synthetic KiCad 10 files, so they run without KiCad. If a change was also checked on a real
board or in KiCad itself, say which and how in the pull request; if it couldn't be, say that too.

## Commits and releases

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) with the skill as the scope,
e.g. `feat(pcb-placement): ...`, `fix(pcb-copper): ...`, `docs(rf-layout): ...`. release-please turns them into
the changelog and the next version: `feat` bumps the minor, `fix` the patch, `!` or `BREAKING CHANGE:` the major
(pre-1.0: the minor).

Pull request titles follow the same format (`feat(examples): ...`, `fix(pcb-copper): ...`, `chore: ...`): a
squash merge makes the title the commit on `main`, and that is what release-please reads.

## Reporting a wrong or missing rule

Open an issue with the *Rule correction* form and the source that disagrees. Corrections backed by a primary
source are the most valuable contribution there is.
