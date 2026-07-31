# gf180-ldo

**PRIVATE — 2AM Logic proprietary IP. Canary block (wave 1).**

Low-dropout regulator on gf180mcu (open PDK), designed by agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source analog flow. Dual purpose, per the canary model: catalog
inventory (eventually silicon-measured) and tool forcing-function
(friction issues go to the public klayout-tools tracker).

Selection rationale: PMU-kit companion to the bandgap; Vidatronic-validated 180nm category, uncontested node, cheapest silicon path (matrix row 3).

## Target specification (DRAFT — engineering to ratify, see issue #1)

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

## Layout

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
