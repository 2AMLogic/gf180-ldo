# DR-0008: DR-0001's phase/gain margin is only a stability test when the loop gain has no right-half-plane poles

- **Status**: proposed — ratification is the operator's, the same process
  DR-0001 and DR-0007 went through. **Nothing in this record is in force
  until an operator ratifies it.** What is *not* conditional on
  ratification is the measurement it rests on: that is recorded in
  `sim/amp-selfosc/records/` and stands on its own.
- **Date**: 2026-08-01
- **Decided by**: Builder agent, issue #53 (recommendation only)

## Context

DR-0001 ratifies the stability row as "PM ≥ 45° **and** GM ≥ 10 dB across
the full `I_load × C_eff × ESR × PVT` matrix", and `sim/loop-stability/`
measures exactly that with a Tian dual-injection extraction of the loop gain
`T(s)`.

Phase margin and gain margin read off a Bode plot are a valid stability test
**only when `T(s)` has no right-half-plane poles** — that is, only when the
forward path is itself stable with the loop broken. This is the standard
precondition on the Bode form of the Nyquist criterion, and it is not a
formality here: `design/error_amp.sch` closes a **local** feedback loop
inside the amplifier — the `Rz`/`Cc` Miller network from `N1` around the
stage-2 driver `M2P` and the class-AB gate buffer, back to `OUT` — and that
local loop stays closed when the LDO loop is broken at
`ERRAMP_OUT`/`PASS_GATE`. Nothing in the repository checks it.

Issue #53 checked it, and it does not hold. Measured on `design/` as
committed at `b304bd5` (the amplifier PR #56 landed), with the *unmodified*
`sim/loop-stability/` deck and testbench:

| What was measured | Result |
|---|---|
| `T(f)` at `tt`/125 °C/3.63 V, 50 mA, 1 µF, 50 mΩ — a point the head-of-chain record reports as **PASS** | `|T|` falls to 19.3 dB at 398 kHz with phase −103°, then **rises back** to 23.9 dB at 692 kHz while the continuous phase advances to −19°, and crosses 0 dB at ≈ 1.05 MHz with the phase at **+33°** |
| `T(f)` at `ss`/−40 °C/3.63 V, 0.1 mA, 0.33 µF, 1 mΩ — one of the 15 points #53 was opened about | crossover 276 kHz, then `|T|` climbs to **+24.4 dB** at 640 kHz |
| `|T|` above its first 0 dB crossing, 720 points at 1 and 50 mA (5 MOS corners × −40/125 °C × 3 supplies × 3 caps × 4 ESRs) | **684 of 720 climb back above 0 dB**, worst **+52.5 dB** |
| Amplifier alone, `sim/amp-openloop/`'s own servo structure, 6.14 pF load | a gain peak of **20.7…58.7 dB** at 420…750 kHz at every corner tried, with the phase **advancing** ≈ +150° through it |

A resonant peak with a **+180° phase advance** is the signature of a
right-half-plane complex pole pair. The time domain confirms it directly,
which is what `sim/amp-selfosc/` was added to record: with `EN` held high, no
stimulus, and the regulator settled on its regulating DC solution, the
amplifier's `BG` node and the pass gate carry **volts** of peak-to-peak
periodic activity — 3.31 V and 2.14 V respectively at `tt`/27 °C/3.30 V and
50 mA, with 372 mV of ripple on `VOUT`, at a point DR-0001's matrix reports
as passing with margin. The regulator is oscillating.

Both readings are conservative rather than favourable: the transient is run
under Gear/BDF integration, which is numerically **damping**, and the AC
extraction is the repository's own ratified one, unmodified.

## Decision

**Recommend that DR-0001's stability criterion be amended to state its own
precondition, and that the precondition be a checked row rather than an
assumption.** Concretely, three changes:

1. **DR-0001's stability row gains a precondition clause**: "PM ≥ 45° and
   GM ≥ 10 dB … *evaluated on a loop gain `T(s)` with no right-half-plane
   poles*. Where the forward path is not stable with the loop broken, a
   Bode PM/GM reading is not a stability claim and must not be recorded as
   one."
2. **`sim/amp-selfosc/` becomes the experiment that substantiates that
   precondition**, and a `sim/loop-stability/` record may only be cited as
   evidence for the stability row when the `amp-selfosc` record taken
   against the same `design/` netlist passes. It is a gate on the older
   experiment's *interpretation*, not a replacement for it.
3. **`sim/loop-stability/records/20260801-191742-84f67b8` must not be cited
   as a stability result** for any load. Its 2689 "passing" points are
   PM/GM numbers extracted from a loop gain with RHP poles; at the 2160
   points at 1–50 mA the crossover sits *above* the resonance, where the RHP
   pair has already rotated the phase by ≈ +180°, so `180 + phase` returns a
   large positive number that clears a "≥ 45°" bar while the amplifier
   rings. The record's *measurements* stay on disk — evidence here is
   append-only — but the verdict column is not meaningful.

**This record does not relax any bar.** DR-0001's 45°/10 dB numbers, its
`C_eff` and ESR windows and its load axis are all untouched. It states the
condition under which those numbers mean what they say, and it makes the
current design's status **worse**, not better: what was recorded as
2689/3240 passing is, on this reading, not a stability claim at any load.

## What this says about issue #53's own question

#53 asked for the 15 residual gain-margin failures at 0.1 mA to be cleared,
and root-caused them (via DR-0007) to the 2.5× PVT spread of the
supply-referenced bias, with a constant-gm (beta-multiplier) bias as the
suggested lever. On this evidence that root cause is not the mechanism. The
15 points are the small subset of the resonance's footprint where the phase
happens to fall through −180° *below* the crossover instead of leading
through it above — which is why they show up as a gain-margin failure with a
healthy 67…102° phase margin, and why they cluster at one corner of the bias
spread without the bias being the cause.

Two levers were measured against it, and both are recorded here as negative
results so the next attempt does not repeat them:

- **Constant-gm (beta-multiplier) bias**, #53's suggested direction, built
  as a four-transistor self-biased core with an always-on weak-PMOS start-up
  injector into `NBIAS`. It makes all 15 points **report** a pass — and
  leaves the resonance in place, with `|T|` still climbing to **+15.3 dB**
  above crossover at 38 of the same 72 points. It would have shipped a
  false pass. Separately, it does not deliver the property it was added
  for: the start-up injector supplies 0.23…0.91 µA into `NBIAS`, 18–27 % of
  the branch current and itself supply-referenced, so the measured branch
  current still spreads **2.6×** (1.27…3.31 µA) against the present bias's
  2.5×.
- **A small capacitor across `Rz`** (`Cf`, `N1`→`OUT`, 50…200 fF), which
  restores the local loop's pole-splitting above the shelf. It **works** at
  light load: the RHP pair becomes a damped left-half-plane pair, all 72
  points at 0.1 mA/−40 °C/`ss`,`fs` pass with **no** gain resurgence at all
  (worst `|T|` above crossover −4.2 dB, against +26.1 dB before), and a
  transient at `ss`/−40 °C/3.63 V goes from 0.95 V of peak-to-peak ringing
  on `BG` to **150 nV**. It is not shippable as it stands because it ends
  the gain shelf at `1/(2π·Rz·Cf)`, and the heavy-load crossover — 1.2…1.6 MHz
  at 50 mA — is *above* that corner: 616 of 720 points at 1 and 50 mA then
  fail on phase margin. Holding `Cc + Cf` constant at #51's 4.825 pF makes
  the change PSRR-neutral by construction (worst-corner `psrr_ldo_1k_db`
  50.03 dB vs 50.0 dB, amp gain at 1 kHz 53.55 dB vs 53.54 dB), so PSRR is
  not what blocks it.

Read together those two results bound the next design step: the resonance
**can** be damped cheaply and without spending PSRR, but not while the loop
also needs a flat 43 dB gain shelf out past 1.6 MHz. The shelf's upper
corner and the heavy-load crossover are the two quantities that have to be
separated, and neither `Rz`/`Cc` alone nor the bias branch is the lever that
separates them.

## Alternatives considered

- **Treat the 15 gain-margin failures as the whole defect and close them.**
  Rejected: measured, the levers that close those 15 points leave 38–58 of
  the same 72 points with `|T|` above unity after crossover, and leave the
  amplifier oscillating at the *other* 2160 matrix points that already
  "pass". Closing the reported failures without the precondition would make
  the record look better and the design no better.
- **Add the precondition as a note in `sim/loop-stability/README.md` and
  leave the criterion alone.** Rejected as the superficial version of the
  same fix: the reason this went unnoticed for three loop-stability records
  is precisely that nothing *measured* it. A note is not a gate. The
  measurement (`sim/amp-selfosc/`) is the load-bearing part of this record
  and the README/design-doc updates are downstream of it.
- **Make `sim/loop-stability/` itself reject an RHP loop gain** (e.g. by
  counting `|T| > 0 dB` above the first crossover and voiding the run).
  Not rejected on the merits and worth doing later, but it is a weaker
  test than the time-domain one — gain resurgence above crossover is
  necessary for a Bode misreading, not sufficient to prove RHP poles — and
  it would have to be added to the deck that mints the ratified record,
  which is a change to the ratified experiment rather than a new,
  independent one. Filed as a follow-up instead.
- **Widen the amplifier's buffer until the local loop is stable at its
  present bandwidth.** The local loop's second pole is
  `gm(Mbuf)/(2π·6.14 pF)`; putting it far enough above a 1.6 MHz crossover
  needs `gm(Mbuf)` ≈ 230 µS, i.e. ≈ 6 µA in the buffer alone against a
  measured whole-amplifier 5.4…13.7 µA and a 10–15 µA block allocation.
  Not rejected outright — it is a real option if the Iq row is re-opened —
  but it is a spec question, not a tuning one, so it does not belong in
  this record.

## Consequences

- **The LDO has no verified stability claim at any load right now.** That is
  the honest state and it is worse than the state DR-0007 describes. DR-0007
  argues the 0 mA column out of the envelope on area/PSRR grounds and treats
  1–50 mA as verified at 2160/2160 points; on this record's reading that
  2160/2160 is not a stability result. **DR-0007's own status is `proposed`,
  so nothing has been ratified on that basis yet** — but if it is ratified,
  it should be ratified with this record in hand, not before.
- **Issue #53 cannot be closed by clearing the 15 points**, and its third
  acceptance criterion (re-extending DR-0007's envelope to 0.1–50 mA) must
  not be exercised until the precondition holds. #53 stays open.
- **A new experiment directory appears under `sim/`** with a **failing**
  head record, which is the same pattern `sim/loop-stability/` has carried
  since #10: a recorded FAIL that says so is the point, not a defect in the
  bench.
- **`sim/amp-selfosc/` costs about 6 minutes of CPU per PVT point** on the
  hardware this was run on (two `ldo_core` instances, 0.6 ms of Gear
  integration at a 200 ns ceiling), i.e. it is the most expensive
  experiment in the repository per point. That is a real cost on every
  future compensation iteration and it is the reason the check window is
  0.2 ms rather than the several milliseconds a settling measurement would
  want. The bench is a stability *gate*, not a settling measurement, and
  should stay that cheap.
- **#15 (floorplan) and #16 (post-layout re-run) should not start from the
  present compensation.** Both were unblocked on the strength of #51's
  record. `Rz`, `Cc` and the buffer are all likely to move, and the two
  layout-sensitivity notes DR-0007 hands them (6 MΩ serpentine in the
  compensation path, ~0 dB of PSRR margin on `Cc`) are notes about
  components whose values are not settled.
- **The gap this record closes is a *verification* gap, not only a design
  one.** Three loop-stability records, five ratified regression benches and
  two decision records were written against an amplifier that oscillates,
  and every one of them passed or failed for reasons unrelated to it: the
  DC benches average over the oscillation (`VOUT` still regulates to
  1.787 V at the corner where the pass gate swings 2.14 V), and
  `sim/amp-openloop/`'s `pm_deg` = `180 + vp(...)` is computed from a
  **wrapped** phase, so a forward path with 288° of lag reports as 252° of
  phase margin and clears its own `≥ 45°` check. Any future block in this
  repository that closes a local loop inside a cell needs a check of this
  kind, not just a Bode margin.
