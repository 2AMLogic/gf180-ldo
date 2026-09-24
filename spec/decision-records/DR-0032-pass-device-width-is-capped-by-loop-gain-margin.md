# DR-0032: the pass device stays at W = 2 mm — the < 200 mV dropout stretch is unreachable by widening alone, capped by the ratified loop gain margin

- **Status**: proposed
- **Date**: 2026-09-22
- **Decided by**: agent-builder, issue #139 (recommendation only)

## Context

`design/ldo_core.sch`'s pass device has shipped since issue #8 as
`pfet_03v3 L=0.28u W=2000u nf=40` (2 mm), described in the schematic itself as
a simplification of the ~4 mm sizing `sim/devchar/CONCLUSIONS.md` §1
recommends. Until #138 / `DR-0020` corrected the dropout *measurement* the
simplification had no measurable consequence. With the corrected measurement it
does: at 2 mm the ratified **< 300 mV** Dropout row still passes at every one of
27 PVT corners (worst 267.383 mV at `ss`/125 °C, 32.6 mV of margin), but the
**< 200 mV stretch** column is missed at 9 of them.

Issue #139 asked for a width decision against `devchar` §1's table and three
couplings: the 1/40 `Msense` replica ratio the current limit is built on, the
gate capacitance the pass-gate pole sees, and the `< 0.1 mm²` core-area budget.
Since #139 was filed, two of the three bounds it must be decided against became
*ratified*, and they are what makes this a decision rather than a one-line edit:

- **`DR-0005`** ratified the current-limit window at 62–95 mA and the Thermal
  row at **≤ 346 mW** into a `Vout` = 0 short — a ceiling derived from the
  then-measured worst case (345.215 mW) rounded up, i.e. shipping with
  0.785 mW (0.23 %) of headroom.
- **`DR-0018`** narrowed the Stability envelope to 0.1–50 mA at `C_eff` = 1 µF
  nominal, ESR ≥ 200 mΩ, with **PM ≥ 45°, GM ≥ 10 dB** at every one of its 630
  matrix points — a row the design currently meets 630/630 (worst 55.75° /
  12.08 dB, `sim/loop-stability/records/20260922-012628-ac57c94.md`).

Both of those ratified rows tighten as the pass device widens. That is the
finding this record exists to book.

## Measured: the width is bounded from both sides, and the two bounds do not overlap

Every number below was measured on this repo's own testbenches, on one host
(`gf180mcuD @ c6d73a35f524070e85faff4a6a9eef49553ebc2b`, `ngspice-46`,
sha256 `e60389261cc4138ca8a6c12da307450375ed0ea75b866ef609d1eeabb8523da2`), by
editing only `Mpass`'s `W`/`nf` and `Msense`'s `W`/`nf` (the 1/40 replica ratio
held exact, equal `L`, equal per-finger width) and re-exporting the netlist with
`python3 design/netlist.py`.

| `Mpass` W | dropout, `ss`/125 °C (stretch < 200 mV) | short-circuit dissipation, `ff`/125 °C/3.63 V (ratified ≤ 346 mW) | DR-0018 envelope, worst GM (ratified ≥ 10 dB) | core area (< 0.1 mm²) |
|---|---|---|---|---|
| **2.00 mm (shipped)** | 267.383 mV — misses the stretch (9/27 corners) | 345.215 mW — **PASS** | **12.08 dB**, 630/630 — **PASS** | 0.0735 mm² |
| 2.40 mm | ~222.8 mV (1/W) — misses | ~345.4 mW — pass | 10.47 dB (binding subset) — pass, 0.47 dB left | 0.0740 mm² |
| 2.53 mm (`devchar`'s "200 mV" sizing) | **212.592 mV — misses** (`fs`/125 °C also misses, 200.704 mV) | not run | not run | 0.0742 mm² |
| 2.60 mm | ~205.7 mV (1/W) — misses | not run | **9.76 dB** (3 of 9 binding points < 10 dB) — **FAIL** | 0.0743 mm² |
| 3.00 mm | **180.656 mV — clears, 27/27** | 345.671 mW — pass | **8.49 dB**, 577/630 — **FAIL** | 0.0748 mm² |
| 4.00 mm (`devchar`'s recommendation) | ~133 mV — clears | **346.049 mW — FAIL** | not run (worse than 3 mm by construction) | 0.0761 mm² |

Read off that table:

- **The stretch needs W ≳ 2.7 mm.** Dropout scales as 1/W to within 2 %
  (267.383 mV × 2/W), confirmed at 2.53 mm (predicted 211.4, measured 212.592)
  and at 3.00 mm (predicted 178.3, measured 180.656). 200 mV is reached at
  W ≈ 2.674 mm before margin.
- **The ratified gain-margin bound caps W at ≈ 2.5 mm.** Widening the pass
  device raises `Cgg` and drops the pass-gate pole; the loss lands entirely on
  gain margin at the top of the ratified ESR range. Every one of the 53
  envelope points that fails at 3 mm is at **50 mA / `C_eff` = 1 µF / ESR =
  500 mΩ** — inside DR-0018's envelope, not outside it — and phase margin is
  *not* the binding term (worst PM 45.83°, still over the 45° bar). Measured at
  the binding point over `tt`/`ss`/`res_ss` at −40 °C and all three supplies:
  12.36 dB at 2.0 mm → 10.47 dB at 2.4 mm → 9.76 dB at 2.6 mm → 8.82 dB at
  3.0 mm. (The 3.0 mm figure from the *full* 630-point envelope is worse still,
  8.49 dB at `res_ss_-40c_2.97v`; the nine-point subset is a scan, not a
  substitute for the full run.)
- **The two intervals do not intersect.** There is no pass-device width that
  clears the < 200 mV dropout stretch while keeping DR-0018's ratified
  GM ≥ 10 dB.
- **Area is not the binding coupling, and neither is thermal until 4 mm.**
  `layout/area_estimate.py` puts the whole candidate range at 0.0735–0.0761 mm²
  against the 0.1 mm² budget (§6 of `layout/floorplan.md`); the pass device is
  2.3 % of the budget at the shipped width and 4.6 % even at 4 mm, sixth on the
  list, behind the poly-resistor field's 49 %. DR-0005's Thermal ceiling only
  binds at 4 mm, and then by 0.049 mW.

## Decision

1. **`Mpass` stays at `pfet_03v3 L=0.28u W=2000u nf=40`, and `Xilimit`'s
   `Msense` stays at `W=50u nf=1`.** No `design/` change ships with this
   record. The 1/40 replica ratio is untouched, so DR-0005's ratified
   current-limit window is untouched.
2. **The `< 200 mV` dropout stretch is re-classified as a compensation
   problem, not a device-sizing problem.** It cannot be bought with pass-device
   width at this compensation. Unlocking it requires the loop to tolerate a
   lower pass-gate pole — the same `f_hi` / buffer-bandwidth lever `DR-0016`
   Candidate 2 names and `DR-0019` measures foreclosed by the amplifier's own
   `iq_ua` allocation. Filed as a follow-up issue rather than attempted here.
3. **No ratified row moves.** The Dropout row (< 300 mV) continues to pass with
   32.6 mV of margin at the shipped width; the stretch column was never a gate
   (`README.md`'s Stretch column, and `DR-0020`'s own note).
4. **The pass-array floorplan is settled at N = 40 unit cells of `W=50u nf=1`**
   (`layout/floorplan.md` §3.1/§3.2), with `Msense` as M = 1 of them — the
   integer replica ratio that section asks for, at the width this record keeps.

## Alternatives considered

- **2.53 mm — `devchar` §1's "Rds ≤ 4 Ω / 200 mV @ 50 mA" sizing.** Rejected:
  **it does not clear the stretch**. That row is an open-device DC-resistance
  figure; the ratified dropout measurement (DR-0020) reads the regulation knee
  of the closed loop, which is ~5 % worse. Measured 212.592 mV at `ss`/125 °C
  and 200.704 mV at `fs`/125 °C — two corners still over 200 mV. It also gives
  no integer 1/40 replica ratio at any sensible unit cell
  (`layout/floorplan.md` §3.2).
- **3.00 mm — the smallest width that clears the stretch with margin.**
  Rejected: it fails DR-0018's ratified envelope at 53 of 630 points (worst GM
  8.49 dB against the ratified ≥ 10 dB). Everything else about it is fine —
  dropout 180.656 mV at 27/27 corners, short-circuit dissipation 345.671 mW
  with 0.329 mW of margin, current-limit onset 62.031…93.772 mA (63/63 inside
  the ratified 62–95 mA window, moved by ≤ 0.086 mA by the resize), Iq
  28.7163 µA worst case against < 30 µA, core area 0.0748 mm². **Buying a
  stretch goal by breaking a ratified row is not a trade this repo's spec
  discipline permits** (CLAUDE.md: "agents do not relax the ratified spec to
  make results pass").
- **4.00 mm — `devchar` §1's recommendation.** Rejected on two independent
  ratified rows: short-circuit dissipation 346.049 mW against DR-0005's
  ≤ 346 mW (it exceeds the ceiling by 0.049 mW, because the clamp's own
  inverse-fold grows with pass-device width — dead-short onset 95.1005 mA at
  2 mm, 95.2262 mA at 3 mm, 95.3302 mA at 4 mm), and a gain margin necessarily
  worse than 3 mm's already-failing 8.49 dB.
- **2.40 mm — a partial widening that keeps every ratified row.** Rejected as
  a bad trade rather than as infeasible. It buys ~44 mV of dropout (223 mV,
  still missing the stretch) and some layout-side headroom (IR, EM, thermal
  spreading all improve with width — `layout/floorplan.md` §3.3–3.5), and it
  costs **1.9 dB of the ratified gain margin** (12.36 → 10.47 dB at the binding
  point), leaving 0.47 dB. Spending most of a ratified row's margin on a
  stretch target it does not reach is not worth it; if a later layout-driven
  IR/EM finding makes the extra width genuinely necessary, this is the
  measured shape of that trade.
- **Relaxing DR-0018's GM bound, or the ESR ≥ 200 mΩ envelope edge, to admit
  3 mm.** Not considered further: the bound was ratified a week ago
  (2026-09-15) on this design's own measured margins, and the failing points
  are squarely inside the envelope it claims.

## Consequences

- **The Dropout stretch stays unmet, and now has a named cause.** Before this
  record, "< 200 mV at 9/27 corners" read as an unfinished sizing exercise.
  After it, the stretch is a loop-compensation item with a measured budget:
  ~2.7 mm of pass device is needed and ~2.5 mm is what the ratified gain margin
  affords, so roughly **1.9 dB of extra gain margin at 50 mA / 1 µF / 500 mΩ**
  is what would have to be found before any widening can be spent on dropout.
- **`sim/devchar/CONCLUSIONS.md` §1's "W ≈ 4 mm" recommendation is now
  qualified, not retracted.** Its measurements stand; they are device-level and
  do not see the closed loop's gain margin or the current limit's inverse-fold.
  A note to that effect is added there, pointing here.
- **`layout/floorplan.md` loses its open parameter.** §1's "Pass-device width:
  Not final" row, §3.1/§3.2's candidate tables and §6's candidate area sweep all
  resolve to the 2 mm column; the document no longer has to hold three
  candidates open.
- **Nothing in `sim/` is invalidated.** No `design/` netlist changed, so every
  committed record remains as valid as it was. This record is accompanied by a
  fresh re-run of `dropout-vs-load`, `current-limit` and `quiescent-current`
  against the *current* `design/netlist/ldo_core.spice` (the head records for
  those rows had gone stale against post-#212/#246 soft-start changes), which
  also states the first `current-limit` verdict graded against DR-0005's
  ratified rows rather than the superseded 65–80 mA / ≤ 290 mW ones.
- **The rejected candidates' runs are reproducible, not committed.** Minting
  head records under `sim/<slug>/records/` for a netlist this repo does not
  ship would hijack `sim/CHARACTERIZATION.md`'s per-row head-record selection
  (most recent record wins) and make the rollup describe a design state that
  exists nowhere. Each number in the table above is reproducible in minutes:
  set the two device lines, `python3 design/netlist.py`, then
  - dropout: `python3 sim/run_corners.py dropout-vs-load --corners ss --temps 125 --no-write`
  - thermal / current limit: `NO_RECORD=1 CORNERS=ff TEMPS=125 SUPPLIES=3.63 ./sim/current-limit/testbench/run.sh`
  - gain margin at the binding envelope point:
    `python3 sim/loop-stability/testbench/sweep.py --no-write --corners tt ss res_ss --temps -40 --supply-tol 0.10 --loads-ma 50 --caps-uf 1.0 --esrs 0.5`
  The 3 mm full-matrix figure (577/630, worst PM 45.83° / GM 8.49 dB at
  `res_ss_-40c_2.97v` / 50 mA / 1 µF / 500 mΩ, full matrix 2575/4536) comes from
  a complete 4536-point sweep of the 3 mm candidate run the same way, with
  `--no-write` omitted and the resulting record deliberately not committed.

## References

- Issue #139 — the sizing decision this record answers
- `sim/devchar/CONCLUSIONS.md` §1 — the device-level sizing table
- `spec/decision-records/DR-0004-spec-ratification.md` — the ~4 mm assumption
  in the original spec review
- `spec/decision-records/DR-0005-current-limit-window.md` — the ratified
  62–95 mA / ≤ 346 mW rows this width is bounded by from above
- `spec/decision-records/DR-0018-narrow-stability-envelope-to-1uf-nominal.md` —
  the ratified envelope whose GM ≥ 10 dB bound is the binding constraint
- `spec/decision-records/DR-0020-dropout-measurement-definition.md` — why the
  stretch shortfall became measurable at all
- `spec/decision-records/DR-0016-compensation-pareto-front.md`,
  `spec/decision-records/DR-0019-buffer-standing-current-blocked-by-amp-iq-allocation.md`
  — the `f_hi` lever the stretch now depends on
- `layout/floorplan.md` §§1, 3.1–3.5, 6 — the layout-side half of the same
  decision (unit cell, replica placement, EM/IR, thermal spreading, area)
- Records minted alongside this one:
  `sim/dropout-vs-load/records/`, `sim/current-limit/records/`,
  `sim/quiescent-current/records/` (see the PR for the exact record-ids)
