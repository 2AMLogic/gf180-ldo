# gf180-ldo

A low-dropout linear regulator (LDO) targeting the **gf180mcu** open PDK,
built entirely on the open-source analog flow: [xschem](https://xschem.sourceforge.io/)
for schematic capture, [ngspice](https://ngspice.sourceforge.io/) for
simulation, and [klayout-tools](https://github.com/2AMLogic/klayout-tools)
for layout, DRC, and LVS.

**Status: early. Nothing here has been fabricated.** As of today the repo
holds a ratified specification, an architecture survey, device characterization
data extracted from the PDK models, decision records, a reproducible PVT
corner-running simulation harness, four xschem schematics covering the full
LDO hierarchy (core, error amplifier, current limit, soft start) with
corner-swept simulation evidence behind them, and a DRC/LVS-clean physical
verification flow proven end to end on a one-transistor test cell (see
[`layout/README.md`](layout/README.md)) — but no layout of the LDO block
itself yet, and no silicon. Read every number here as a simulation result
against an open PDK's models, with the corner and testbench that produced it
recorded alongside it.

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

## Target specification (RATIFIED 2026-07-31)

Ratified by the operator on issue #1 with the amendments recorded in
[`spec/decision-records/DR-0004-spec-ratification.md`](spec/decision-records/DR-0004-spec-ratification.md),
which also ratifies DR-0001 (output capacitor and ESR window), DR-0002 (input
flavor) and DR-0003 (output programmability). Changing a line below requires a
new decision record; it may not be relaxed to make a result pass. The
Current limit and Thermal rows are amended by
[`spec/decision-records/DR-0005-current-limit-window.md`](spec/decision-records/DR-0005-current-limit-window.md)
(note 8) — **pending** the operator's approval of the pull request that
carries that record's `Status` flip (2026-08-19 ratification-via-PR policy,
2AMLogic/2am#357); the rows below already reflect DR-0005's proposed
62–95 mA / ≤ 346 mW window.

| Parameter | Target | Stretch |
|---|---|---|
| Input | 3.3 V ±10% (2.97–3.63 V) | 5 V flavor — separate follow-on variant, not this design (see DR-0002) |
| Output | 1.8 V ±2% (fixed; divider laid out as a unit-resistor string for metal-mask-option derivatives) | programmable 1.2–3.0 V — deferred; needs a sub-1.2 V reference, and > ~2.5 V needs the 5 V variant (see DR-0003) |
| Load | 0–50 mA, where 0 mA means no external load — the feedback divider's ~2 µA is the only inherent preload and no external preload resistor may be assumed (DR-0001) | 100 mA |
| Dropout @ 50 mA | < 300 mV — binds ss / 125 °C / Vin = 2.10 V (measured, note 4) | < 200 mV |
| Line reg | < 5 mV/V over Vin 2.97–3.63 V, at 1 mA and at 50 mA | — |
| Load reg (0–50 mA) | < 1% (18 mV), counted inside the ±2% accuracy window rather than in addition to it | — |
| Load transient | 1 ↔ 50 mA step, 1 µs edges, at C_eff = 0.33 µF and ESR 0–500 mΩ: peak excursion ≤ 150 mV, recovery to within ±1% (18 mV) of the settled value in ≤ 20 µs | peak excursion ≤ 100 mV |
| PSRR | > 50 dB @ 1 kHz and > 20 dB @ 100 kHz, at I_load = 1 mA (binding — light load) and at 50 mA, C_eff = 1 µF nominal, verified across the stability window | > 60 dB @ 1 kHz, > 30 dB @ 100 kHz, 1 MHz point characterized |
| Iq (excluding load current) | < 30 µA at no load **and** at full load — binds ff / 125 °C / 3.63 V | < 10 µA — subordinate to DR-0001's ESR window; not to be bought back by reintroducing a minimum ESR |
| Current limit | 62–95 mA over PVT untrimmed, constant-current (brickwall) clamp; never engages for I_load ≤ 50 mA at any corner (binds ff / −40 °C, strongest pass drive); survives a continuous Vout = 0 short at Vin_max (note 5, note 8) | — |
| Startup | monotonic into any load 0–50 mA and any C_eff in the stability window; controlled ramp ≤ 1 V/ms, so inrush ≤ 5 mA at C_eff = 4.7 µF and startup at full rated load stays ≥ 10 mA below the current limit; inside ±2% within 3 ms of enable; overshoot ≤ +2% of the final value | — |
| Enable / shutdown | shutdown Iq < 3 µA at ff / 125 °C / 3.63 V; disabled output state is pass device fully off with no internal active discharge; Vin→Vout leakage ≤ 1 µA at the same corner | — |
| Thermal | 92 mW continuous worst case (Vin 3.63 V at 50 mA); ≤ 346 mW into a Vout = 0 short at the untrimmed 95 mA limit ceiling (note 8); specified to Tj ≤ 125 °C — θJA and sustained-short survivability delegated to the package/integration spec | — |
| Output noise | not specified — explicitly waived (note 7) | 10 Hz–100 kHz µVrms row if a consumer asks for one |
| Area | < 0.1 mm² total core area, pass FET included, excluding pads and sealring | — |
| Stability | stable 0–50 mA with C_out 0.33–4.7 µF effective (1 µF nominal X5R/X7R), ESR 0–500 mΩ; PM ≥ 45°, GM ≥ 10 dB worst corner | capless variant (separate design fork) |

Notes — these are part of the ratified spec, not commentary:

1. **Verification corners.** Unless a row names a binding corner, every row is
   verified across the full matrix: process {tt, ff, ss, fs, sf} × T {−40, 27,
   125} °C × Vin {2.97, 3.3, 3.63} V, and across the DR-0001 output-capacitor
   window. Named bindings: dropout at ss/125 °C/Vin = 2.10 V (measured), Iq at
   ff/125 °C/3.63 V, current limit at ff/−40 °C, stability and PSRR at light
   load at the worst corner of DR-0001's matrix.
2. **Output-accuracy conditions.** ±2% means ±36 mV, 3σ, over line (2.97–3.63 V),
   load (0–50 mA) and temperature (−40…125 °C). **The ±2% window is the
   regulator's own error and excludes the voltage reference's own error** — the
   reference is a separate block with its own budget, and any total-accuracy
   claim (datasheet or otherwise) must state the sum of the two, not this row
   alone. See DR-0004 for why the window is stated this way and what would
   change it.
3. **Divider mismatch is an assumption, not a simulated result.** This PDK's
   resistor models hard-code local mismatch to zero and publish no mismatch
   coefficient for `ppolyf_u_3k` (`sim/devchar/CONCLUSIONS.md` §2), so the
   divider-mismatch term of the accuracy budget cannot be obtained from
   simulation against these models. It is carried as a stated assumption
   (e.g. `ppolyf_u`'s `par_r = 0.021` card value as a proxy); a Monte Carlo
   "pass" against this PDK is not evidence for that term.
4. **Dropout test point.** Dropout is measured at Vin = Vout + dropout ≈ 2.10 V,
   not at the 2.97 V supply floor; sizing from the 2.97 V rows undersizes the
   pass device by ~50% (`sim/devchar/CONCLUSIONS.md` §1).
5. **Current-limit behaviour.** The limit is a constant-current clamp; foldback
   is deliberately not required, so a folded-back limit can never prevent
   startup into a loaded output. The cost is that a sustained short dissipates
   the full ≤ 346 mW of the Thermal row, which is an integration constraint —
   if an integration cannot absorb it, adding foldback or thermal shutdown is a
   superseding decision record, not an implementation choice.
6. **Provisional rows.** The line-regulation, load-transient, PSRR 100 kHz,
   current-limit, startup and enable/shutdown numbers were set at ratification
   from measured device data plus the architecture survey's loop budget, before
   any loop-level simulation exists. Each carries a falsifiable revisit trigger
   in DR-0004; a row that proves unmeetable is superseded by a new record, never
   silently relaxed. The current-limit row's ±10% window trigger fired and is
   discharged by DR-0005 (note 8); the row's other clauses (never-engages
   floor, brickwall behaviour, short-circuit survivability) remain as
   originally ratified and passing.
7. **Output-noise waiver.** No consumer of this block has stated a noise
   requirement, and no reference or amplifier design exists yet against which a
   µVrms number could be substantiated — so a number here would be a claim
   without a testbench. The row is waived explicitly rather than left blank; a
   consumer requirement makes it a superseding record.
8. **Current-limit window and thermal ceiling, amended by DR-0005.** The
   ±10% current-limit window (65–80 mA) and its ≤ 290 mW thermal consequence
   were originally ratified before issue #11's full PVT sweep existed;
   measured evidence showed both bounds are structurally unreachable
   untrimmed on this PDK — the current threshold is a voltage over one
   uncancelled absolute on-chip resistance, and gf180mcu's poly-resistor
   sheet spread alone moves the limit ±20% (`ppolyf_u`, 40% ff-to-ss),
   against everything the circuit itself contributes (under ±1.2%).
   [`DR-0005`](spec/decision-records/DR-0005-current-limit-window.md) amends
   the window to 62–95 mA (the measured 62.0–93.8 mA plus rounding
   headroom) and the thermal ceiling to 346 mW (the measured worst-case
   short-circuit dissipation, 345.215 mW at `ff_125c_3.63v`
   (`sim/current-limit/records/20260816-080440-8e105a0.md`), rounded up to
   the next whole milliwatt), leaving every other clause of both rows
   untouched. A ±10% window remains a stretch goal, explicitly conditional
   on adding a trim option — not proposed here, as trim is a product/flow
   commitment outside this block's charter. **Pending** operator approval
   of DR-0005's ratifying pull request (issue #105) per the 2026-08-19
   ratification-via-PR policy (2AMLogic/2am#357) — the rows above reflect
   the proposed window in advance of that merge, per that policy's own
   drafting convention.

**Current verdict per row**: this table states the ratified target, not the
current pass/fail state of the evidence behind it — for that, see
[`sim/CHARACTERIZATION.md`](sim/CHARACTERIZATION.md), a generated (not
hand-maintained) rollup that cites the exact `sim/<slug>/records/` record
behind every row's current verdict and flags whether that record is fresh
against the netlist committed at `design/netlist/`. Regenerate it with
`python3 sim/build_characterization_report.py > sim/CHARACTERIZATION.md`
after any `sim/` record lands or `design/netlist/*.spice` changes; this
table (the ratified spec + notes above) stays the authority on what is
required, `sim/CHARACTERIZATION.md` on what the evidence currently shows.

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

## Physical verification (DRC / LVS)

The DRC/LVS flow is up, on a one-transistor test cell — **there is no LDO
layout yet**. It needs KLayout and `klt` on top of the simulation tools:

```bash
python3 layout/drclvs.py --check-env   # are klayout / klt / xschem / the PDK visible?
python3 layout/drclvs.py               # DRC (two decks) + LVS + negative controls
```

See [`layout/README.md`](layout/README.md) for what each stage establishes, what
"DRC clean" does and does not mean here, and the tool caveats worth knowing
before believing a result.

## License

Licensed under the Apache License, Version 2.0 — see [`LICENSE`](LICENSE).

The gf180mcu PDK itself is not distributed here; it is fetched separately and
carries its own license from GlobalFoundries and Efabless.
