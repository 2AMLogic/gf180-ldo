# gf180-ldo — agent instructions

Public, open-source repository: a low-dropout regulator on the gf180mcu
open PDK, designed by agents. Licensed Apache-2.0 (see `LICENSE`).

- **PDK**: gf180mcu (open PDK). Open-source flow: xschem + ngspice for
  design/sim, klayout-tools (`klt`) for layout work.
- **Friction protocol (the tool forcing-function)**: every time
  klayout-tools is awkward, missing a capability, or wrong for what you
  need, file an issue at `2AMLogic/klayout-tools` describing the need
  generically — describe the tool gap, not this design. Tool issues should
  be useful to anyone hitting the same gap, so keep them free of
  block-specific detail that only makes sense here.
- **Verification is the product**: no claim without a testbench. PVT
  corners on every recorded result. `sim/` results are append-only
  evidence.
- **Everything here is published**: this repo, its specs, its simulation
  evidence, and its issue tracker are public. Write commits, issues, and
  documents accordingly — no credentials, no third-party confidential
  material, and nothing you would not want read by someone outside the
  project.
- Spec changes go through `spec/` with a decision record; agents do not
  relax the ratified spec to make results pass.
- Harness bootstrap: copy the sim-harness pattern from
  `2AMLogic/gf180-bandgap` once it lands there rather than reinventing.

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.
<!-- END LOOM ORCHESTRATION -->
<!-- BEGIN REPO-SKILLS -->
This repository has [Repo Skills](https://github.com/rjwalters/repo) v0.7.0 installed —
general repository hygiene and environment commands invoked as `/repo:<command>`. Run
`/repo:help` for the command list, or see `.claude/skills/repo/SKILL.md` for the full
guide. Hygiene commands apply safe, reversible fixes by default and report each
change; run with `--ask` to review first, and `--prune` to allow irreversible
removals. Managed by `install.sh` — edit outside the markers only.
<!-- END REPO-SKILLS -->
