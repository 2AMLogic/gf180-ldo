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
