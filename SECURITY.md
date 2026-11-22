# Security policy

## Reporting a vulnerability

Report it privately through GitHub's **Report a vulnerability** button on the repository's *Security* tab. Don't
open a public issue. Fixes ship in a patch release, which the changelog notes.

## What is in scope

- The Python scripts under `plugins/` and `evals/`. They parse KiCad, Altium and vendor files that may come from
  third parties, and some make network calls (JLCPCB/LCSC parts data, datasheet downloads).
- The GitHub workflows, and the settings and agent files the `hardware-project` scaffold writes into board repos.

A wrong design rule is not a security issue: open a **rule correction** issue with its primary source instead.

## Supported versions

Only the latest release gets fixes.
