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
verification flow proven end to end on a one-transistor test cell and on the
first real block cell, the feedback divider (see
[`layout/README.md`](layout/README.md)) — but no layout of the LDO block as a
whole yet, and no silicon. Read every number here as a simulation result
against an open PDK's models, with the corner and testbench that produced it
recorded alongside it.

**How far that is from T1 is graded, not asserted.**
[`signoff/records/t1-tier-report.json`](signoff/records/t1-tier-report.json)
is the verdict of record — `klt signoff --manifest`'s mechanical grading of
this block against klayout-tools' design-evidence ladder, re-run by CI on
every push. Today it reads **`tier: null`, T1 1 of 11 items met**. See
[`signoff/README.md`](signoff/README.md) for the per-item reading and the
disclosures the grader structurally cannot make on this repo's behalf.

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
`Dropout @ 50 mA` row's **measurement definition** (note 4) is amended by
[`spec/decision-records/DR-0020-dropout-measurement-definition.md`](spec/decision-records/DR-0020-dropout-measurement-definition.md)
— **pending** the operator's approval of the pull request that carries that
record's `Status` flip (2026-08-19 ratification-via-PR policy,
2AMLogic/2am#357); note 4 below already reflects DR-0020's proposed wording.
The row's **numbers are not touched** by that record: the < 300 mV target and
< 200 mV stretch stand exactly as ratified, and only the quantity the
testbench computes when it claims to have measured "dropout" changes.
Startup row's settling clause is amended by
[`spec/decision-records/DR-0006-startup-settling-window.md`](spec/decision-records/DR-0006-startup-settling-window.md)
(note 8) — **ratified 2026-09-14** by the operator's approval of pull request
#127 (2026-08-19 ratification-via-PR policy, 2AMLogic/2am#357); the row below
reflects DR-0006's 6 ms window.
The Current limit and Thermal rows are amended by
[`spec/decision-records/DR-0005-current-limit-window.md`](spec/decision-records/DR-0005-current-limit-window.md)
(note 9) — **ratified 2026-09-15** by the operator's approval of pull request
#137 (issue #105) per the 2026-08-19 ratification-via-PR policy
(2AMLogic/2am#357); the rows below reflect DR-0005's 62–95 mA / ≤ 346 mW
untrimmed window.
The Startup row's ramp, inrush/clearance anchor and settling clauses are
further amended by
[`spec/decision-records/DR-0024-startup-current-budget-at-1uf.md`](spec/decision-records/DR-0024-startup-current-budget-at-1uf.md)
(notes 5a, 8) — **ratified 2026-09-15** by the operator's approval of pull
request #228 (issue #212) per the 2026-08-19 ratification-via-PR policy
(2AMLogic/2am#357); the row below reflects DR-0024's ≤ 5 V/ms ramp, C_eff =
1 µF inrush/clearance anchor, and 1.8 ms settling window. **This
ratification does not certify the inrush, current-limit-clearance or
monotonicity sub-clauses as passing** — they remain failing at the majority
of C_eff = 1 µF points today, attributed entirely to the pre-existing,
separately-tracked issue #191 acquisition-transient/settled-leakage
regression (see notes 5a, 8).

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
| Current limit | 62–95 mA over PVT untrimmed, constant-current (brickwall) clamp; never engages for I_load ≤ 50 mA at any corner (binds ff / −40 °C, strongest pass drive); survives a continuous Vout = 0 short at Vin_max (note 5, note 9) | — |
| Startup | monotonic into any load 0–50 mA and any C_eff in the stability window; controlled ramp ≤ 5 V/ms, so inrush ≤ 5 mA and startup at full rated load stays ≥ 10 mA below the current limit, both at C_eff = 1 µF (nominal) — above 1 µF both clauses are characterized, not bound, up to DR-0001's 4.7 µF ceiling (note 5a); inside ±2% within 1.8 ms of enable (note 8); overshoot ≤ +2% of the final value | — |
| Enable / shutdown | shutdown Iq < 3 µA at ff / 125 °C / 3.63 V; disabled output state is pass device fully off with no internal active discharge; Vin→Vout leakage ≤ 1 µA at the same corner | — |
| Thermal | 92 mW continuous worst case (Vin 3.63 V at 50 mA); ≤ 346 mW into a Vout = 0 short at the untrimmed 95 mA limit ceiling (note 9); specified to Tj ≤ 125 °C — θJA and sustained-short survivability delegated to the package/integration spec | — |
| Output noise | not specified — explicitly waived (note 7) | 10 Hz–100 kHz µVrms row if a consumer asks for one |
| Area | < 0.1 mm² total core area, pass FET included, excluding pads and sealring | — |
| Stability | stable 0.1-50 mA at C_eff = 1 uF nominal (X5R/X7R), ESR >= 200 mOhm; PM >= 45 deg, GM >= 10 dB worst corner (630/630 matrix points, worst 55.45 deg / 14.17 dB, DR-0008 resurgence clean 0/630). The full 0.33-4.7 uF / no-minimum-ESR window is NOT verified: 1640/1890 of its 0.1-50 mA points pass and the shortfall is structural (DR-0015, DR-0017), needing f_hi (buffer bandwidth) to close -- see DR-0016 Candidate 2 and DR-0019, which measures that lever foreclosed by the amplifier's own iq_ua allocation (issue #147). 0 mA (no external load) remains outside the envelope per DR-0007. | capless variant (separate design fork) |

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
4. **Dropout test point and measurement.** Dropout is the `Vin − Vout` headroom
   at which the regulator leaves regulation at full load: `Vin` is swept down at
   `I_load` = 50 mA and dropout is read at the point where `Vout` falls to the
   −2% edge of the Output row (1.764 V). It is anchored at
   Vin = Vout + dropout ≈ 2.10 V, not at the 2.97 V supply floor — sizing from
   the 2.97 V rows undersizes the pass device by ~50%
   (`sim/devchar/CONCLUSIONS.md` §1) — and the regulator must still be inside
   the Output row's ±2% window at that 2.10 V anchor, which is the direct
   statement of dropout ≤ 300 mV. Reporting `Vin − Vout` at the 2.10 V anchor is
   **not** a dropout measurement: because 2.10 V is 1.800 V + 300 mV exactly,
   that quantity is identically 300 mV + (1.800 V − Vout), i.e. the DC
   regulation error offset by the bound. The measurement clause of this note is
   **pending** operator approval of DR-0020's ratifying pull request (issue
   #138) per the 2026-08-19 ratification-via-PR policy (2AMLogic/2am#357); the
   ratified anchor and the row's numbers are unchanged by it. See
   [`DR-0020`](spec/decision-records/DR-0020-dropout-measurement-definition.md).
5. **Current-limit behaviour.** The limit is a constant-current clamp; foldback
   is deliberately not required, so a folded-back limit can never prevent
   startup into a loaded output. The cost is that a sustained short dissipates
   the full ≤ 346 mW of the Thermal row, which is an integration constraint —
   if an integration cannot absorb it, adding foldback or thermal shutdown is a
   superseding decision record, not an implementation choice.
5a. **Current-limit-clearance and inrush bound only to C_eff = 1 µF.** The
    Startup row's inrush (≤ 5 mA) and current-limit-clearance (≥ 10 mA below
    the limit) sub-clauses are verified only up to C_eff = 1 µF (DR-0001's
    nominal value), not to its 4.7 µF ceiling: the ramp's steady dV/dt is a
    process/temperature quantity, not a C_eff-conditioned one (measured — the
    same 1.24–2.95 V/ms spread recurs at every capacitor value), so one fixed
    ramp rate cannot hold a current-headroom bound at the wide end of
    DR-0001's 14.2:1 capacitor window and a rate bound at the narrow end at
    once.
    [`DR-0022`](spec/decision-records/DR-0022-startup-clearance-narrows-above-1uf.md)
    first proposed this move for the clearance sub-clause alone, against the
    pre-resize (≤ 1 V/ms) ramp; DR-0022 itself remains `proposed`, not
    ratified, and its own "passes cleanly at 1 µF" measurement (63/63 main
    matrix, 20/20 at 0 mA,
    `sim/soft-start/records/20260906-125202-f1096c9.md`) is superseded for
    this purpose by the fresher evidence below, not cited here as current
    fact.
    [`DR-0024`](spec/decision-records/DR-0024-startup-current-budget-at-1uf.md)
    extends the C_eff = 1 µF anchor to inrush as well and is the record this
    note ratifies, against
    `sim/soft-start/records/20260915-103035-18f664f.md`'s 155-point sweep:
    inrush and clearance both **fail** at the majority of 1 µF points today
    (18/79 and 46/79 respectively), entirely attributable to the
    pre-existing, separately-tracked issue #191 acquisition-transient/
    settled-leakage regression (same-corner A/B confirmed against the
    pre-DR-0024 netlist) — not a new circuit debt this anchor move
    introduces, and not evidence that the bound itself is arithmetically
    wrong. **Ratified 2026-09-15** by the operator's approval of pull request
    #228 (issue #212) per the 2026-08-19 ratification-via-PR policy
    (2AMLogic/2am#357). Above 1 µF, both sub-clauses remain characterized,
    not bound, up to DR-0001's 4.7 µF ceiling.
6. **Provisional rows.** The line-regulation, load-transient, PSRR 100 kHz,
   current-limit, startup and enable/shutdown numbers were set at ratification
   from measured device data plus the architecture survey's loop budget, before
   any loop-level simulation exists. Each carries a falsifiable revisit trigger
   in DR-0004; a row that proves unmeetable is superseded by a new record, never
   silently relaxed. The startup row's settling-clause trigger fired and is
   discharged by DR-0006, further superseded by DR-0024 (note 8); DR-0024
   also discharges the ramp-rate clause and moves the inrush/clearance anchor
   to C_eff = 1 µF (note 5a); the current-limit row's ±10% window trigger
   fired and is discharged by DR-0005 (note 9). The startup row's inrush,
   current-limit-clearance, monotonicity and overshoot clauses remain
   provisional in this sense — currently failing at the majority of C_eff =
   1 µF points, tracked by issue #191, not by this note's own trigger
   mechanism — and the current-limit row's other clauses (never-engages
   floor, brickwall behaviour, short-circuit survivability) remain as
   originally ratified and passing.
7. **Output-noise waiver.** No consumer of this block has stated a noise
   requirement, and no reference or amplifier design exists yet against which a
   µVrms number could be substantiated — so a number here would be a claim
   without a testbench. The row is waived explicitly rather than left blank; a
   consumer requirement makes it a superseding record.
8. **Startup settling window, amended by DR-0006.** The ±2% settling bound
   was originally ratified at 3 ms (DR-0004 amendment A9); measured evidence
   showed that bound cannot coexist with the row's own ≤ 1 V/ms ramp bound
   on this PDK's untrimmed on-chip `R · C` soft-start (2.93 : 1 measured
   process/temperature spread against a 1.70 : 1 window that both clauses
   jointly admit). [`DR-0006`](spec/decision-records/DR-0006-startup-settling-window.md)
   amends the settling bound to 6 ms, the slowest measured point
   (5.82788 ms, `ss_-40c_3.63v`,
   `sim/startup/records/20260816-100018-af4d1f9.md`) plus ~3% headroom,
   leaving every other clause of the row untouched. **Ratified 2026-09-14**
   by the operator's approval of pull request #127 (issue #106) per the
   2026-08-19 ratification-via-PR policy (2AMLogic/2am#357). The market key
   escalated this relaxation as not competitive on startup time against
   public comps (TI TLV700 starts ~60× faster); the operator ruled that the
   3 ms bound was internally inconsistent with the row's own ≤ 1 V/ms ramp
   clause, so 6 ms corrects a spec error rather than papering over a design
   shortfall — the startup-time gap versus public parts is disclosed here,
   not claimed away. See DR-0006 §Market-key finding.
   [`DR-0024`](spec/decision-records/DR-0024-startup-current-budget-at-1uf.md)
   supersedes DR-0006's 6 ms figure and re-centres the ramp bound itself,
   ≤ 1 V/ms → ≤ 5 V/ms: the settling bound moves to **1.8 ms**, the slowest
   measured point among the 155/163 points that converged (1.72525 ms,
   `res_ss_-40c_3.63v`,
   `sim/soft-start/records/20260915-103035-18f664f.md`) plus ~4% headroom,
   and the ramp-rate bound's own measured evidence (1.24–2.95 V/ms, 0/155
   over 5 V/ms) replaces DR-0006's original ≤ 1 V/ms sizing rather than
   merely amending it. This is a joint move with the inrush/clearance anchor
   (note 5a), not an independent one — a 5× faster global ramp rate cannot
   hold the old 4.7 µF-anchored inrush bound at all, by the same C×dV/dt
   arithmetic DR-0022 first raised for the clearance sub-clause alone.
   **Ratified 2026-09-15** by the operator's approval of pull request
   #228 (issue #212) per the 2026-08-19 ratification-via-PR policy
   (2AMLogic/2am#357). **Unlike DR-0006's ratification, this one does not
   leave every other clause of the row passing**: inrush, current-limit-
   clearance and monotonicity remain failing at the majority of 1 µF points,
   and 4/155 overshoot points remain failing — all attributed to the
   pre-existing, separately-tracked issue #191 acquisition-transient/
   settled-leakage regression (same-corner A/B confirmed against the
   pre-DR-0024 netlist, not introduced or worsened by this resize), not to
   this record's ramp/delay-RC resize. TI's TLV774/TLV700 typicals remain
   4–18× faster depending on which figure is compared (down from the ~60×
   DR-0006 disclosed) — see DR-0024 §Against TI's TLV774/TLV700 typicals, a
   gap this record narrows, not closes.
9. **Current-limit window and thermal ceiling, amended by DR-0005.** The
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
   commitment outside this block's charter. **Ratified 2026-09-15** by the
   operator's approval of pull request #137 (issue #105) per the 2026-08-19
   ratification-via-PR policy (2AMLogic/2am#357). The market key found the
   untrimmed 62–95 mA window proportionally tighter than every public
   untrimmed comp it checked (the only tighter listed part reaches ±10% via
   an external trim resistor — the same mechanism this note names as the
   only route to ±10%), and the thermal row adequate-for-catalog with its
   no-on-chip-thermal-shutdown gap disclosed in note 5 rather than claimed
   away. See DR-0005 §Operator ruling.

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

The DRC/LVS flow is up, on a one-transistor test cell and on the feedback
divider — **there is no top-level LDO layout yet**. It needs KLayout and `klt`
on top of the simulation tools:

```bash
python3 layout/drclvs.py --check-env   # are klayout / klt / xschem / the PDK visible?
python3 layout/drclvs.py               # DRC (two decks) + LVS + negative controls
python3 layout/drclvs.py --cell divider  # ... the same, on the feedback divider
```

See [`layout/README.md`](layout/README.md) for what each stage establishes, what
"DRC clean" does and does not mean here, and the tool caveats worth knowing
before believing a result.

What *does* exist ahead of the rest of the layout is the plan for it:
[`layout/floorplan.md`](layout/floorplan.md) fixes the pass-array segmentation
and 50 mA metal strategy, the common-centroid matching plan, the
Kelvin-sense scheme, and the core-area estimate against the Area row. Its §4.1
is no longer only a plan: the feedback divider — whose mismatch this PDK's
models cannot simulate at all (note 3), making the drawn common centroid the
only mitigation available — is drawn and LVS-verified against that section's
own numbers.

```bash
python3 layout/area_estimate.py        # core-area estimate from design/netlist/
```

## Chipalooza

This block's proposal for Open Circuit Design's Chipalooza Challenge #5
(GF180MCU / Wafer.Space) is at
[`docs/chipalooza/challenge-5-proposal.md`](docs/chipalooza/challenge-5-proposal.md) —
block type, I/O mapped to the slot budget, functional description, a target
spec table re-derived from `sim/`, and a bench test plan, all stated honestly
against this repository's current maturity (no top-level GDS yet).

## License

Licensed under the Apache License, Version 2.0 — see [`LICENSE`](LICENSE).

The gf180mcu PDK itself is not distributed here; it is fetched separately and
carries its own license from GlobalFoundries and Efabless.
