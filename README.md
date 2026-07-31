# gf180-ldo

A low-dropout linear regulator (LDO) targeting the **gf180mcu** open PDK,
built entirely on the open-source analog flow: [xschem](https://xschem.sourceforge.io/)
for schematic capture, [ngspice](https://ngspice.sourceforge.io/) for
simulation, and [klayout-tools](https://github.com/2AMLogic/klayout-tools)
for layout, DRC, and LVS.

**Status: early. Nothing here has been fabricated.** As of today the repo
holds a draft specification, an architecture survey, device characterization
data extracted from the PDK models, decision records, and a reproducible PVT
corner-running simulation harness. There is no schematic, no layout, and no
silicon. Read every number here as a simulation result against an open PDK's
models, with the corner and testbench that produced it recorded alongside it.

## Built by agents

This block is designed by AI agents, on purpose and out in the open. The
agents write the testbenches, run the corners, argue the trade-offs in
decision records, and open the pull requests; the repository's conventions
exist to keep that process honest rather than to dress it up:

- **Verification is the product.** No claim lands without a testbench behind
  it, and every recorded result carries its PVT corners.
- **Evidence is append-only.** Files under `sim/` are never edited or deleted
  after they are written — a later run mints a new record rather than
  overwriting an inconvenient one.
- **The spec is a gate, not a suggestion.** Agents may not relax a ratified
  spec line to make a result pass; changing it requires a decision record in
  `spec/`.

The second reason this block exists is as a forcing function for the tooling.
Every time the open-source flow is awkward, missing a capability, or simply
wrong for the job, that friction is filed as an issue against
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — so the gaps this
design hits get fixed in public.

Design rationale for the target: 180 nm is a mature, well-characterized node
with a fully open PDK, an LDO is a natural companion to a voltage reference in
a power-management block, and the topology is simple enough to verify
exhaustively while still exercising the parts of the flow that matter
(matching, stability across load and capacitor range, PSRR, layout parasitics).

## Target specification (DRAFT — pending ratification, see issue #1)

| Parameter | Target | Stretch |
|---|---|---|
| Input | 3.3 V ±10% | 5 V flavor |
| Output | 1.8 V ±2% (fixed) | programmable 1.2–3.0 V |
| Load | 50 mA | 100 mA |
| Dropout @ 50 mA | < 300 mV | < 200 mV |
| PSRR @ 1 kHz | > 50 dB | > 60 dB |
| Iq | < 30 µA | < 10 µA |
| Load reg (1–50 mA) | < 1% | — |
| Area (ex. pass FET pad ring) | < 0.1 mm² | — |
| Stability | stable 0–50 mA with 1 µF ±ESR range | capless variant |

Maturity ladder: simulation-complete → layout DRC/LVS-clean → shuttle
seat → measured silicon over temperature.

## Repository layout

```
spec/          ratified spec + decision records
design/        schematics / netlists (xschem)
sim/           testbenches + PVT corner results (ngspice)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```

## Environment Setup

Before running xschem/ngspice against the gf180mcu PDK, follow
[`docs/environment-setup.md`](docs/environment-setup.md) — xschem
build-from-source steps (no Homebrew formula exists), the pinned gf180mcu
PDK hash fetched via `volare`, the `PDK_ROOT`/`PDK` env convention, and the
harness's own end-to-end acceptance test.

## Getting set up

```bash
brew install ngspice                          # or apt-get install ngspice
pip install volare
volare enable --pdk gf180mcu <version-hash>   # volare ls-remote --pdk gf180mcu

python3 sim/run_corners.py --check-env        # confirm ngspice + PDK are visible
bash sim/selftest.sh                          # prove the harness runs end to end
python3 sim/run_corners.py smoke-bias         # 81-point PVT sweep, records evidence
```

The harness is stdlib python3 — no virtualenv, no packages. It never hardcodes
a PDK path. See [`sim/README.md`](sim/README.md) for the ratified evidence
record format (directory layout, record ids, the append-only rule), and
[`sim/harness/README.md`](sim/harness/README.md) for PDK resolution, the
corner definitions and how to write a testbench.

## License

Licensed under the Apache License, Version 2.0 — see [`LICENSE`](LICENSE).

The gf180mcu PDK itself is not distributed here; it is fetched separately and
carries its own license from GlobalFoundries and Efabless.
