# Changelog

## [0.2.0](https://github.com/gabrielfrasantos/hardware-design-skills/compare/v0.1.0...v0.2.0) (2026-11-22)


### Features

* **examples:** agent-neutral scaffold, headless net classes, and an example board gated in CI ([#26](https://github.com/gabrielfrasantos/hardware-design-skills/issues/26)) ([ceb8151](https://github.com/gabrielfrasantos/hardware-design-skills/commit/ceb8151296a1391ca48618546a43fc8e333f1985))
* **examples:** rebuild stepper-ble from the skills alone ([#28](https://github.com/gabrielfrasantos/hardware-design-skills/issues/28)) ([91a62e4](https://github.com/gabrielfrasantos/hardware-design-skills/commit/91a62e47ef61eeeacb62ffb99b1ac48a99035473))
* **examples:** redraw stepper-ble's schematic and re-place its board ([#27](https://github.com/gabrielfrasantos/hardware-design-skills/issues/27)) ([cce86ac](https://github.com/gabrielfrasantos/hardware-design-skills/commit/cce86ac501750ced59682f6ea4b0770052a93c3f))
* **pcb-design-rules:** net-integrity gates and a KiCad nightly canary ([#31](https://github.com/gabrielfrasantos/hardware-design-skills/issues/31)) ([2de1b8c](https://github.com/gabrielfrasantos/hardware-design-skills/commit/2de1b8c7e109843752d437ab373c44e775280ebe))
* **pcb-placement:** update the board from the schematic without KiCad's window ([#30](https://github.com/gabrielfrasantos/hardware-design-skills/issues/30)) ([4fc7a6f](https://github.com/gabrielfrasantos/hardware-design-skills/commit/4fc7a6f625edcca6bf87022ebbbe58b2081a5d56))
* **pcb-routing:** autoroute with Freerouting from a text-based DSN ([#32](https://github.com/gabrielfrasantos/hardware-design-skills/issues/32)) ([eda001c](https://github.com/gabrielfrasantos/hardware-design-skills/commit/eda001c1eca62bb8c7736dd83dba24ad4f036432))


### Bug Fixes

* **plugin:** close the gaps the skills-only rebuild found ([#29](https://github.com/gabrielfrasantos/hardware-design-skills/issues/29)) ([34a8cb9](https://github.com/gabrielfrasantos/hardware-design-skills/commit/34a8cb9a5e9d154d6e03f1f950e862d213c169db))
* **review:** calibration from the first real board review ([#21](https://github.com/gabrielfrasantos/hardware-design-skills/issues/21)) ([#22](https://github.com/gabrielfrasantos/hardware-design-skills/issues/22)) ([8458677](https://github.com/gabrielfrasantos/hardware-design-skills/commit/8458677b15fa4569b3cccd82b0169103f89ceefc))
* **rules:** JLCPCB PTH pad hole to inner-layer copper is 0.3 mm ([#23](https://github.com/gabrielfrasantos/hardware-design-skills/issues/23)) ([069aa8e](https://github.com/gabrielfrasantos/hardware-design-skills/commit/069aa8e80e2ef05dd6c3839de898dae84db4eb90))
* sync identity and atomic writes, review check status, assembly reconciliation, trace inputs ([#33](https://github.com/gabrielfrasantos/hardware-design-skills/issues/33)) ([0f908b2](https://github.com/gabrielfrasantos/hardware-design-skills/commit/0f908b225cba66cb342f727473c6af2a07150034))


### Documentation

* **design:** phase A-C status after the KiCad 10 runs ([#19](https://github.com/gabrielfrasantos/hardware-design-skills/issues/19)) ([5bd4b2e](https://github.com/gabrielfrasantos/hardware-design-skills/commit/5bd4b2ecb4d6419f3f152579fab5998ef4fa721e))
* rename to hardware-design-skills, project-agnostic wording, new README ([#24](https://github.com/gabrielfrasantos/hardware-design-skills/issues/24)) ([67ea1bd](https://github.com/gabrielfrasantos/hardware-design-skills/commit/67ea1bd6d42dcecec305a0cc08860ee5f895b155))

## 0.1.0 (2026-11-22)


### Features

* add analog-circuit-design skill ([e93f9c5](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/e93f9c52d66a71a5355694d7825a374a9f613f9d))
* add circuit-simulation skill ([ce936d3](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/ce936d3c40c2c9707d170bcafa3173702799e2e4))
* add hardware-skills marketplace with the power-pcb-layout skill ([3304935](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/3304935a64ad0e4eb06d52e9da0990005fbbdf6e))
* add high-speed-digital-layout skill ([277490b](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/277490b03f7ad37becce20df919f0527d3346639))
* add interface-layout skill ([21b8785](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/21b8785f6486933d7acdc97747349ed835ddf4d7))
* add mcu-circuit-design skill ([eff4404](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/eff4404f79eb6039ec9155356a7fe02174808e90))
* add pcb-design-rules skill with fab profiles and layout-quality gate ([348892f](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/348892f2907631f1e010cf8a6710151584c06fb5))
* add rf-layout skill ([be98cf8](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/be98cf8696f752a518e26c06e1a6ef4a68bb1768))
* assembly, footprint-package and lifecycle checks (audit gaps) ([ae06cea](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/ae06ceafee1fee6336d76b3fb67a6351bceebbc0))
* assembly, footprint-package and lifecycle checks (audit gaps) ([019f961](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/019f96147fad5dfbdd467889a0ef12d8ac3b7d2d))
* **design-review:** scripted schematic and PCB review, reviewer agent, seeded-defect eval ([5d3e907](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/5d3e907fedd217fd866abccfdf29c7b0bd33c75e))
* **design-review:** scripted schematic and PCB review, reviewer agent, seeded-defect eval ([486cfee](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/486cfee09d530df2403130aea595857a23fc5026))
* **evals:** design plan and a generic placement eval harness ([c7d4880](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/c7d488024b6008b888a6ffe4a905f6703f18fd2e))
* **evals:** design plan and placement eval harness ([9e300d8](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/9e300d85d5e1bbd4c4beac395b4406d8e24870c3))
* **evals:** KiCad 10 validation kit for every file-writing script (Phase B) ([762a0fe](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/762a0fef7c4f4a87a5f022d2cdab786e56dea446))
* **evals:** KiCad 10 validation kit for every file-writing script (Phase B) ([01a389c](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/01a389cc1a68d6f020a1921f1565ce8a618ed9ab))
* **hardware-project:** scaffold, traceability and shared export scripts ([7eba039](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/7eba039e6d9e024c5c1825a5ec21525286ffd35a))
* **hardware-project:** scaffold, traceability and shared export scripts ([95fe4b6](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/95fe4b63f1763fecfdc074abf82a431895eee252))
* **pcb-copper:** standard net classes sized from their names ([6dc3e1d](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/6dc3e1d2a7b96d837a0b150c2461377abdf837af))
* **pcb-design-rules:** 45-degree corners only and a hard short/clearance gate ([d4dbd7d](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/d4dbd7d93573e5c4666e852d46d9d65272cfb078))
* **pcb-design-rules:** teardrops, pour and plane checks, KiCad 10+ only ([fd4a9be](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/fd4a9bebdd70e6b1c6b9fe5aae8c7fc607567c66))
* **pcb-design-rules:** teardrops, pour and plane checks, KiCad 10+ only ([2bc5db1](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/2bc5db1269f08780df015e7b36d3e01838bf0df1))
* **pcb-placement:** MCU pin assignment from the placement ([bac6c50](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/bac6c503fa255bb977a63f7d55e7941066f394dd))
* **pcb-placement:** placement optimizer, gate and render ([eaaac64](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/eaaac64fecc995c337584a24ff9b91a83992a64b))
* **pcb-placement:** placement optimizer, gate and render ([f1bfe7d](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/f1bfe7db85e89e46d3a8129a61659c8cecfa7bc7))
* **power-circuit-design:** schematic-level power skill ([e40955f](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/e40955f96f3db1fbc90b16166ec372e944ba1660))
* **power-circuit-design:** schematic-level power skill ([34a0803](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/34a0803c21ae6578cd38b39cc3e550c390bea361))
* **reference-block:** copy a vendor's layout block onto a KiCad 10 board ([f608694](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/f608694147e60ffc3b870ba920ffff7b230f0b22))
* **reference-block:** copy a vendor's layout block onto a KiCad 10 board ([d34e9b3](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/d34e9b3a259b9e8408ff2f4c7de0e9a6040c2439))
* **schematic-capture:** schgen as a skill (and land pcb-copper, pcb-placement on main) ([f143ae7](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/f143ae7ced76814e98fb61ba79690b53bd10ee4b))
* **schematic-capture:** schgen as a skill, pin-map and net-class helpers ([90f34bf](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/90f34bf94944fe9d1185fd01d94943645da1f59c))


### Bug Fixes

* apply the best-practices audit (corrections and documented gaps) ([d852599](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/d85259952f77eff14527dcc5ed907ab9dedc764a))
* apply the best-practices audit (corrections and documented gaps) ([d6b3627](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/d6b362710ff2f155db0b5d812336f2f675d3c890))
* **evals:** validation kit reports its own evidence (B2, B6, B9) ([628fdc9](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/628fdc977f05284454eecccb5b94bc58274eb175))
* **evals:** validation kit reports its own evidence (B2, B6, B9) ([1f230c0](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/1f230c01b284b115e716c53cc33cf33d6b4e0cfb))
* **placement:** pins.py lets a need that names a debug/strap function use its pin ([#18](https://github.com/gabrielfrasantos/claude-hardware-skills/issues/18)) ([d38f45d](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/d38f45d3dc26bd3c009de91644a3b3b0f0df18ee))
* **project:** jlc_stock compares SSOP/MSOP/TSSOP by body size, not name ([82e6910](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/82e69101bb6eb9ab24b49c1698a15d7d4f30f913))
* **project:** pass the given kicad-cli to the BOM step of export_jlcpcb/export_release ([5cd0a7c](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/5cd0a7c0a1151eef92f1736337f3851875b47b33))
* **project:** Windows BOM export without kicad-cli on PATH; SSOP/MSOP package names ([8da3aec](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/8da3aecf970fe610b7c6520ef456e692d25c7fac))


### Documentation

* **design:** the Phase B kit is [#14](https://github.com/gabrielfrasantos/claude-hardware-skills/issues/14) ([c36af98](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/c36af982171905c098604f07c2b8aad9c696bdd1))
* **design:** what is missing after v0.1, as phases with gates ([e9763e6](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/e9763e60a1b313803c480427eea1f0d2ee572844))
* **design:** what is missing after v0.1, as phases with gates (§9) ([ec92d1f](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/ec92d1fb8481e8708e3e50ecd4ca2ba637277f69))
* **pcb-design-rules:** say where to get the script when only SKILL.md is installed ([c244a63](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/c244a63a568b08769cea6eaee9c1d8a9096aaa39))
* **reference-block:** licence terms, package-pair spacing, AN5165 ([a36685c](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/a36685c29697b0364dfd98c6083f6f51389e957c))


### Miscellaneous Chores

* make the repository GitHub-ready (README, MIT licence, CI, releases) ([81a315c](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/81a315cfae6a322de597c16acdec3e8d498e049a))
* make the repository GitHub-ready (README, MIT licence, CI, releases) ([c11744e](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/c11744e119ee1562c1fb6897b12e91df3dbb5698))


### Code Refactoring

* **evals:** keep the harness generic; cases live in board repos ([9223bcd](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/9223bcd66d28a0d2e4d46e81becb122a6fadec79))
* make mcu-circuit-design vendor-neutral ([19e3347](https://github.com/gabrielfrasantos/claude-hardware-skills/commit/19e3347a94e2d6652e0f2597f5d72e2d4d6241a6))
