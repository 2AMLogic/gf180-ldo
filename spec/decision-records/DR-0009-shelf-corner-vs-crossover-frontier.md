# DR-0009: With the amplifier no longer oscillating, the gain-shelf compensation reaches ~0.1 mA, not 50 mA

- **Status**: proposed — ratification is the operator's, the same process
  DR-0001, DR-0007 and DR-0008 went through. **Nothing in this record is in
  force until an operator ratifies it.** What is *not* conditional on
  ratification is the evidence it rests on, which is recorded in
  `sim/amp-selfosc/records/`, `sim/amp-openloop/records/` and
  `sim/loop-stability/records/` and stands on its own.
- **Date**: 2026-08-02
- **Decided by**: Builder agent, issue #53 (recommendation only)

## Context

DR-0008 measured that `design/error_amp.sch`'s `Rz`/`Cc` network is itself a
feedback loop — from `N1` around the stage-2 driver `M2P` and the class-AB
gate buffer, back to `OUT` — that stays closed when the LDO loop is broken
for `sim/loop-stability/`'s Tian extraction, and that it had right-half-plane
poles. While that held, no Bode PM/GM read off that extraction was a
stability claim at any load, and the head record's "2689/3240 passing" was
not a stability result. Issue #55 (`BG`-steer, PR #62) landed independently
in the meantime and re-verified `sim/loop-stability/` against its own change
(2632/3240) — still with the RHP-pole precondition unmet, so that count was
not a stability result either.

Issue #53 fixed it. `Cf1`/`Cf2` (two 12 × 12 µm MIM in series, ≈ 149 fF,
`N1` → `BG`) is a Miller capacitor around `M2P` alone; it splits the two
poles that sat below the local loop's crossover, so that loop now has one.
The precondition holds, at every corner and in both domains:

| Evidence | Before (`3668aca`, issue #55's state) | After (this issue, `c828e73`) |
|---|---|---|
| `sim/amp-openloop/` `peak_excess_db` (gain climbing back above its 200 kHz value anywhere in 200 kHz – 5 MHz), 81 PVT points, bar ≤ 1 dB | FAIL at **81 of 81** | **−0.36 … −0.13 dB at 81 of 81** — monotone everywhere |
| `sim/amp-selfosc/` settled, undriven transient at the **light** operating point, bar ≤ 1 mV pk-pk | `BG` in the hundreds-of-mV to low-V range, FAIL at 45 of 45 | `BG` **0.13 … 0.43 µV** — PASS at **45 of 45** |
| `sim/loop-stability/` gain resurgence above the first 0 dB crossing (DR-0008's frequency-domain signature) | resurging at a large fraction of the matrix | **0 of 3240**, worst −0.17 dB |

`sim/amp-selfosc/`'s *heavy* rows still fail (`BG` in the low-V pk-pk range at
50 mA / 0.33 µF, so the head record is still an overall FAIL) — but that is
now a different defect and one this record's own matrix reports
independently: at 50 mA / 0.33 µF the **LDO** loop has PM ≈ −94.6°. Before,
the light branch rang too, at points the loop-stability record called
passing; that was the local loop, and it is gone.

**So for the first time the loop-stability matrix is a stability
measurement.** This record is about what it measures, which is
`sim/loop-stability/records/20260802-095235-c828e73.md` (supersedes
`20260802-071154-166834d`, issue #55's own re-verification, still taken
without the precondition satisfied): **785 of 3240 points pass**, and they
are not the ones the project has been assuming.

| `I_load` | 0.33 µF | 1 µF | 4.7 µF | row |
|---|---|---|---|---|
| 0 mA | 0/180 | 0/180 | 0/180 | 0/540 — out of scope per DR-0007 |
| **0.1 mA** | 136/180 | **180/180** | 176/180 | **492/540** |
| 1 mA | 0/180 | 56/180 | **180/180** | 236/540 |
| 10 mA | 0/180 | 0/180 | 51/180 | 51/540 |
| 25 mA | 0/180 | 0/180 | 6/180 | 6/540 |
| 50 mA | 0/180 | 0/180 | 0/180 | 0/540 |

The pre-#53 head record read 2689/3240 (issue #55's own re-verification:
2632/3240), taken through a resonance; this one is not.

## The frontier, in the two quantities that set it

The compensation is a Type-II gain shelf: above `f_z = 1/(2π·Rz·Cc)` the
amplifier's gain shelves at `A_plat = gm(MIN)·Rz`, so the LDO loop crosses
unity on the output pole alone. Two quantities decide whether a given
`(I_load, C_eff)` point works, and they are measured, not assumed:

- **The LDO's crossover**, `f_c = β·A_plat·gm_pass/(2π·C_eff)`. `gm_pass`
  rises with load current (measured: crossover spans 144 kHz at
  0.1 mA / 0.33 µF, worst corner, up into the low-MHz range at
  50 mA / 0.33 µF).
- **The shelf's upper corner**, `f_2` — which *is* the local loop's own
  crossover, because the shelf only holds while that loop's gain is large.
  Measured here: **≈ 180 kHz**.

A point passes when `f_c` lands between `f_z` and `f_2`. `f_z` and `A_plat`
trade against each other through `Rz` and `Cc`, so the load axis this
compensation can cover is `f_2/f_z` wide — and **`f_2` is the quantity that
cannot be bought.**

### `f_2` is set by Iq, and it does not scale

`f_2` is the local loop's crossover, so it is capped by that loop's
non-dominant poles: the buffer's `gm(Mbuf)/(2π·C_gate)` and, after the
Miller split, `gm(M2P)/(2π·Cgs(Mbuf))`. Both are bias currents against fixed
capacitance. Measured — `sim/amp-openloop/`'s committed testbench run
`--no-write` (exploration runs, not minted records), reading the largest
shelf corner at which `peak_excess_db` is still non-positive at
tt / 27 °C / 3.30 V:

| Device currents | amp Iq at tt/27 °C/3.30 V | largest stable `f_2` |
|---|---|---|
| as committed | 8.6 µA | 131 kHz |
| buffer 3× (`Mbufb` 200 → 600 µm, `Mbuf` 150 → 300 µm) | 12.9 µA | 248 kHz |
| buffer 3× **and** stage 2 3× (`M2N` 4 → 12 µm) | 16.4 µA | 393 kHz |

Reaching 50 mA / 0.33 µF needs `f_2` in the low-MHz range, i.e. an order of
magnitude further on a curve that has just spent 1.9× the amplifier's whole
Iq to buy 3×. The extrapolation is hundreds of microamps against a ratified
**< 30 µA** whole-regulator row and a 10–15 µA amplifier allocation. This is
not a tuning gap.

### `A_plat` cannot be lowered to meet it either

The obvious counter-move is to shrink `A_plat` until `f_c` at 50 mA falls
below `f_2`. It is blocked from the other end:

```
light load needs   f_c(0.1 mA, 4.7 µF) >= f_z
                   =>  A_plat^2  >=  gm(MIN)·C_eff,max / (Cc·beta·gm_pass,light)
PSRR row needs     A_amp(1 kHz) = gm(MIN)/(2*pi*1 kHz*Cc) >= 50 dB (linear 316x)
                   =>  gm(MIN)/Cc >= 2.0e6
together           A_plat >= ~98
```

and `A_plat` ≥ 98 with `f_2` = 180 kHz already fails at 1 mA / 0.33 µF.
Driving `A_plat` down to what 50 mA / 0.33 µF would need at this `f_2` puts
`Cc` in the nanofarad range — millimeters² of MIM — to keep the light-load
end. The box does not close from either side.

## Decision

**Recommend three things, none of which is a tuning change.**

1. **`spec/decision-records/DR-0007`'s proposed `Stability` row must not be
   ratified as written.** It proposes an envelope of **1–50 mA** verified,
   0 mA excluded, on the strength of `20260801-191742-84f67b8`. With the
   DR-0008 precondition now satisfied, the measured envelope is the
   *opposite end of the same axis*: the loads that pass are the light ones,
   and even 0.1 mA is not fully clean (492/540 — see "Consequences" below).
   Issue #53's own third acceptance criterion — "amend DR-0007 to re-extend
   the envelope from 1–50 mA to 0.1–50 mA" — is therefore not exercisable,
   and the correct amendment is a narrowing, not a widening.
2. **The next compensation increment is an architecture change, not another
   `Rz`/`Cc`/`Cf` iteration.** The measured lever is the buffer's output
   impedance per microamp, and a plain source follower's `1/gm(Mbuf)` is the
   worst available. Named candidates, in the order this record would try
   them: a **super source follower** (local feedback around `Mbuf`, which
   buys `gm·ro` of output impedance for roughly one extra bias branch rather
   than for 30× the current), and **adaptive biasing** of the buffer from a
   sense replica of the pass device, which is the standard answer to
   `f_c ∝ gm_pass` in a wide-load-range LDO and makes `f_2` track `f_c`
   instead of standing still.
3. **`#15` (floorplan) and `#16` (post-layout re-run) stay parked.**
   DR-0008 already said this; this record removes the remaining reason to
   doubt it. `Rz`, `Cc` and the buffer are all still moving, and the buffer
   is now known to have to move *a lot*.

**This record does not relax any bar.** DR-0001's 45°/10 dB, its `C_eff` and
ESR windows and its load axis are untouched, as are the PSRR and Iq rows. It
states which of them are in conflict and by how much.

## Alternatives considered

- **Re-cut the PSRR budget instead.** `design/error_amp.md` §4 budgets the
  whole 50 dB row to amplifier gain, forcing `|1 − G|` to 1 — deliberately
  conservative. The closed-loop measurement is better than the proxy by a
  small margin (`sim/psrr-dc/records/20260802-095514-c828e73.md`:
  `psrr_ldo_1k_db` 50.08 dB worst corner against the ratified 50 dB, i.e.
  0.08 dB the proxy does not credit). Re-cutting that budget line with the
  closed-loop record as its evidence is defensible and would let `Cc` grow
  and `A_plat` fall. Rejected **as a solution**, not as an idea: the
  arithmetic above shows `A_plat` would have to fall by roughly an order of
  magnitude, and the closed-loop PSRR measurement does not buy anywhere near
  that. It is worth doing on its own merits; it does not close this gap.
- **Shrink DR-0001's `I_load × C_eff` box to what is measurable.** The
  honest minimal version of this record. Rejected as the *first* move
  because the box is a ratified product requirement and the design has not
  yet tried the architecture in point 2 — narrowing the spec before
  exhausting the design is the wrong order. It stays available if point 2
  fails, and DR-0001 anticipated exactly that ("the correct response is a
  superseding record that tightens the component spec").
- **Leave the amplifier oscillating and keep the wider "passing" record.**
  Rejected on DR-0008's grounds, restated: `sim/amp-selfosc/` measured
  hundreds of millivolts to volts of peak-to-peak on the amplifier's own
  nodes at points that record calls passing. The narrower envelope in this
  record is worse on paper and better in silicon.

## Consequences

- **The head loop-stability record's pass count drops sharply, and that is
  the correction landing, not a regression.** The pre-#53 count (both the
  original 2689/3240 and issue #55's own 2632/3240 re-verification) was
  taken through a resonance; this one is not.
- **The defect issue #53 was opened about is gone; the issue is not.** #53
  is "clear the 15 residual **gain-margin** failures at 0.1 mA". Measured on
  the new record: **0 of 540 points at 0.1 mA fail on gain margin** — the
  whole column now clears GM ≥ 10 dB. But 48 of them fail on **phase**
  margin, which the pre-#53 records could not have reported because their
  phase readings were being taken on the far side of a resonance. So #53's
  first acceptance criterion (all 540 passing both bars) is still not met,
  for a different and now-visible reason.
- **The 0.1 mA column is pinched from both ends of the same axis**, which is
  the frontier above, localised: 44 of the 48 failures are at 0.33 µF and
  cold (worst PM 32.4° at `ss`/−40 °C/3.63 V, crossover 144 kHz — `f_c`
  running into `f_2`), and the other 4 are at 4.7 µF at `ff`/125 °C/2.97 V
  (PM 42.5°, crossover 6.9 kHz — `f_c` falling back toward `f_z`). Raising
  `A_plat` fixes one group and breaks the other.
- **`sim/amp-selfosc/` becomes cheap.** Its head record notes the bench cost
  minutes of CPU per point because an oscillating loop forces the timestep
  down; a settling loop does not, which is why this record's run covers the
  full 45-point grid where earlier partial runs covered fewer.
- **Nothing in the DC rows moved**, because no device current changed:
  `sim/quiescent-current/records/20260802-095514-c828e73.md` (PASS, 45/45,
  bit-identical to 5 significant figures against the pre-#53 baseline),
  `sim/dropout-vs-load/records/20260802-100041-c828e73.md` (same
  pre-existing 300.5–301.0 mV marginal FAIL, unrelated to this issue),
  `sim/current-limit/records/20260802-105338-c828e73.md` (bit-identical).
- **`sim/enable-shutdown/`'s large-signal 50 mA startup transient shifts at
  cold corners** (`sim/enable-shutdown/records/20260802-095233-c828e73.md`):
  the four ratified DC rows (shutdown Iq, enabled Iq, Vin→Vout leakage,
  disabled-output behaviour) are unchanged, but the peak startup current and
  post-settling ripple move at the coldest corners (`ff`/`fs`/`res_ff` at
  −40 °C). This is evidence *for* this record's diagnosis rather than a new
  defect: the corners that shift are exactly the ones
  `sim/loop-stability/` reports as its tightest phase-margin failures, and
  the shift is the same 0.6–0.9 MHz resonance being damped, showing up in a
  large-signal transient that rings through that band. `sim/startup/` and
  `sim/current-limit/` — the benches that actually own the ratified
  startup-overshoot and current-limit-onset rows — are unmoved.
