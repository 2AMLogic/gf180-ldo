# DR-0017: dropout is the headroom at the regulation knee, not `Vin − Vout` at a pinned `Vin = 2.10 V`

- **Status**: proposed — ratification is the operator's, the same process
  DR-0001 went through ("Decided by: Builder agent … recommendation only —
  ratification is #1"). Nothing in this record changes the ratified
  `README.md` table; the **< 300 mV target and < 200 mV stretch numbers are
  untouched by this record**, and this record must not be read as relaxing
  them. What it changes is which quantity the `dropout-vs-load` testbench
  computes when it claims to have measured "dropout".
- **Date**: 2026-08-21
- **Decided by**: Builder agent, issue #138 (recommendation only)

## Context

`README.md`'s ratified `Dropout @ 50 mA` row reads **< 300 mV — binds
ss / 125 °C / Vin = 2.10 V (measured, note 4)**, and note 4 fixes the test
point: *"Dropout is measured at Vin = Vout + dropout ≈ 2.10 V, not at the
2.97 V supply floor."*

`sim/dropout-vs-load` implemented that by solving one `.op` at `Vin = 2.10 V`
with a 50 mA sink and reporting

    vdrop_mv = (v(vin) − v(vout)) * 1e3

The most recent record against that manifest,
`sim/dropout-vs-load/records/20260816-103644-bea26f6.md` (minted by #102 as a
deliberate post-DR-0015 refresh), reports **FAIL at 27 of 27 PVT points** — by
0.476 mV (`sf_−40c`) to 1.014 mV (`res_ff_125c`), a total spread across the
whole grid of 0.54 mV. #79's T1/bronze tracker carries it as an open gap, and
#138 was filed to close it.

### The metric cannot pass, and no design change can make it pass

The ratified binding test point **is** the nominal output plus the ratified
bound: `2.10 V = 1.800 V + 0.300 V`. So for as long as the loop is in
regulation, that expression is an identity:

    vdrop_mv ≡ 300 mV + (1.800 V − Vout)

It reports the **DC regulation error, offset by exactly the bound** — not the
dropout voltage. It can read below 300 mV only if `Vout` sits *above* its own
setpoint, which a negative-feedback loop with finite DC gain cannot do. The
27/27 FAIL is therefore not evidence about dropout at all; it is a restatement
of a −0.48…−1.01 mV DC error against a threshold placed exactly at zero error.

Measured directly (op-point probe of the shipped netlist at `tt / 27 °C /
2.10 V`, 50 mA): `Vout = 1.799257 V`, and the pass device sits at
`|Vds| = 300.7 mV` against `|Vdsat| = 690 mV` — in triode, with the gate
**still under loop control** (`V(loop) = 0.554 V`, i.e. ~554 mV of unused
gate-drive range remaining down to ground). The part is not in dropout at the
test point; it is comfortably in regulation there.

Widening the pass device — the obvious lever, and the one #138's curation
suggested — confirms this. Sweeping `XMpass` at `tt / 27 °C / 2.10 V`:

| `XMpass` | area vs. shipped | `vdrop_mv` (old metric) | verdict |
|---|---|---|---|
| `W=2000u nf=40` (shipped) | 1× | 300.743 | FAIL |
| `W=4000u nf=80` | 2× | 300.575 | FAIL |
| `W=8000u nf=160` | 4× | 300.574 | FAIL |

The reading **asymptotes at ≈ 300.574 mV**, above the bound. Quadrupling the
pass device — which alone would consume roughly a third of the ratified
< 0.1 mm² core-area budget — buys 0.169 mV of the 0.743 mV needed and then
stops buying anything, because what is left is the amplifier's DC error, not
the pass device's `Rds(on)`. **The old metric is unpassable by any pass-device
sizing.** A "fix" that made it pass would have to move `Vout` above 1.800 V,
i.e. deliberately mis-set the feedback divider — trading a real ratified row
(Output, 1.8 V ±2%) for a measurement artifact.

### What the design's dropout actually is

Sweeping `Vin` down through the regulation knee at a fixed 50 mA load, against
the same shipped netlist, the design leaves regulation between 1.90 V and
2.03 V depending on corner. Taking the headroom at the point where `Vout` has
fallen to **1.764 V** — the ratified −2% edge of the `1.8 V ±2%` Output row,
and already the repo's established in-regulation threshold (`sim/soft-start`
triggers on the same `VAL=1.764` edge; DR-0006 §"The two clauses" reasons from
it) — gives **136.2 mV (`ff / −40 °C`) to 267.4 mV (`ss / 125 °C`)** across
the 27-point grid.

Two things corroborate that this, not the old number, is the quantity the
ratified row is about:

- The worst corner is **`ss / 125 °C`** — exactly the binding corner
  `README.md` note 1 names for this row. Under the old metric the worst corner
  was `res_ff / 125 °C`, a resistor-skew corner with no physical claim on
  dropout, and the ratified binding corner ranked 12th of 27.
- DR-0004 recorded the spec review's finding that *"dropout is measured with
  2.5× margin at the correct test point"* — a statement that only makes sense
  against a dropout number well below the bound, which 136–267 mV is and
  300.5–301.0 mV is not.

The reading is insensitive to where exactly the knee threshold is placed,
because in dropout `Vout` tracks `Vin` with a slowly varying offset. Moving the
threshold across the whole ±2% accuracy window and beyond:

| knee threshold | `ff / −40 °C` | `tt / 27 °C` | `ss / 125 °C` (binding) |
|---|---|---|---|
| 1.746 V (−3%) | 137.7 | 193.2 | 270.6 |
| **1.764 V (−2%, chosen)** | **136.2** | **191.0** | **267.4** |
| 1.782 V (−1%) | 134.7 | 188.7 | 264.3 |
| 1.790 V (−0.55%) | 134.1 | 187.8 | 262.9 |

A 44 mV swing of the threshold moves the binding corner by 7.7 mV, against
32.6 mV of margin to the bound — the verdict does not turn on the choice.

## Decision

**Ratify the following measurement definition for the `Dropout @ 50 mA` row.
The row's numbers do not change.**

1. **Dropout is the `Vin − Vout` headroom at the regulation knee**, measured at
   the ratified 50 mA full-load condition: sweep `Vin` downward at fixed
   `I_load = 50 mA` and report the headroom at the point where `Vout` has
   fallen to the ratified −2% accuracy edge, **1.764 V**. It is **not**
   `Vin − Vout` evaluated at a pinned supply.
2. **`README.md` note 4 is amended** to state the measurement rather than only
   the supply at which it is anchored. Replacement text:

   > 4. **Dropout test point and measurement.** Dropout is the `Vin − Vout`
   >    headroom at which the regulator leaves regulation at full load: `Vin`
   >    is swept down at `I_load` = 50 mA and dropout is read at the point
   >    where `Vout` falls to the −2% edge of the Output row (1.764 V). It is
   >    anchored at `Vin = Vout + dropout ≈ 2.10 V`, not at the 2.97 V supply
   >    floor — sizing from the 2.97 V rows undersizes the pass device by ~50%
   >    (`sim/devchar/CONCLUSIONS.md` §1) — and the regulator must still be
   >    inside the Output row's ±2% window at that 2.10 V anchor, which is the
   >    direct statement of dropout ≤ 300 mV. Reporting `Vin − Vout` at the
   >    2.10 V anchor is **not** a dropout measurement: because 2.10 V is
   >    1.800 V + 300 mV exactly, that quantity is identically
   >    300 mV + (1.800 V − Vout), i.e. the DC regulation error offset by the
   >    bound (see DR-0017).

3. **The ratified `Vin = 2.10 V` anchor keeps a gate of its own.** The
   testbench checks, in the same sweep, that `Vout` at `Vin = 2.10 V` lies
   inside the ratified ±2% window (1764–1836 mV). Dropout ≤ 300 mV *means*
   the part still regulates with 300 mV of headroom, so this is the row's
   original intent stated correctly, and it is what stops the new definition
   from drifting away from note 4's anchor.
4. **Records minted before this change are not numerically comparable to
   records minted after it.** `20260816-103644-bea26f6` and its predecessors
   measured a different quantity under the same measurement name. The first
   record under this definition supersedes it as the row's live evidence (it is
   a correction, which `sim/README.md` requires be minted as a new record
   rather than an edit) and says so explicitly in its Claim field — but the two
   `vdrop_mv` numbers must never be plotted, differenced, or trended against
   each other.

## Alternatives considered

- **Resize the pass device to close the ~0.5–1.0 mV gap** — rejected on
  measurement. The old metric asymptotes at 300.574 mV (table above); 2× and 4×
  pass-device area do not reach the bound, and 4× would spend roughly a third
  of the ratified core-area budget to buy 0.169 mV. The gap is amplifier DC
  error, not `Rds(on)`.
- **Relax the < 300 mV bound to, say, < 302 mV** — rejected, and it is the
  outcome this repo's CLAUDE.md rule exists to forbid ("agents do not relax the
  ratified spec to make results pass"). It is also unnecessary: the design's
  actual dropout clears the existing bound by 32.6 mV at the binding corner. A
  relaxed bound would have enshrined a measurement artifact in the spec.
- **Raise the feedback setpoint slightly (e.g. 1.802 V) so `Vin − Vout` at
  2.10 V falls below 300 mV** — rejected as spec laundering. It would spend
  real Output-row accuracy budget to move a number that measures nothing, and
  it would leave the metric just as unable to report dropout.
- **Keep the old metric and record the row as permanently FAIL** — rejected. A
  gate that cannot be passed by any physically achievable design is not a gate;
  it silently converts one ratified row into noise and, worse, would have
  invited exactly the two rejected "fixes" above from a future agent under
  pressure to turn the row green.
- **Replace the number with a pass/fail regulation check at `Vin = 2.10 V`
  only** — rejected as a *sole* measure, adopted as an *additional* one
  (decision item 3). On its own it cannot evaluate the row's < 200 mV stretch
  column, and it would leave the block with no dropout figure to publish.
- **Measure `I_load × Rds(on)` with the gate forced to ground** — rejected. It
  reports a device parameter rather than a regulator property, requires
  breaking the loop (so it cannot be run on the shipped closed-loop netlist),
  and would not be reproducible against the post-layout extracted netlist that
  #16 re-runs this experiment on.

## Consequences

- **The `Dropout @ 50 mA` row passes, with real margin, on the shipped
  netlist**: 27/27 PVT points, worst case 267.383 mV at `ss / 125 °C` against
  the < 300 mV target (32.6 mV margin), best case 136.208 mV at `ff / −40 °C`.
  The evidence is `sim/dropout-vs-load/records/<RECORD_ID>.md`.
  `sim/CHARACTERIZATION.md` is regenerated accordingly and #79's checklist
  item 5 closes on the dropout clause.
- **The < 200 mV stretch column is now measurable, and is not met**: 18 of 27
  points clear 200 mV, but every 125 °C point plus `ss / 27 °C` and
  `fs / 27 °C` do not. That is a newly visible gap — the old metric could not
  express it at all — and it is a genuine candidate for a pass-device or
  `Rds(on)` improvement, since unlike the old metric this number *does* respond
  to pass-device sizing. It is deliberately left un-gated (the stretch column
  never was a gate) rather than opened as a spec question here.
- **The experiment is ~26× slower**: 8.8 s → 229.9 s wall for the 27-point grid
  at `-j 8`, because each point is now a 91-step DC sweep rather than a single
  `.op`. That is affordable for an experiment re-run on netlist changes, but it
  is a real cost and it lands on #16's post-layout extracted re-run too.
- **This row now genuinely depends on the pass path**, where before it depended
  only on amplifier DC gain. #51's in-flight pass-gate/bias rework (DR-0012 /
  DR-0015 adaptive shelf) will move this number where it previously could not,
  so this experiment must be re-run after #51 lands — noted on both issues.
- **Bad consequence, stated plainly**: this record makes a ratified row flip
  from FAIL to PASS by changing how it is measured, which is structurally the
  same shape as the thing this repo forbids. The defences are that the bound is
  untouched, that the old metric is shown by measurement to be unpassable by
  any design (so it cannot have been the row's intent), that the new binding
  corner matches the one the ratified spec independently names, and that the
  ratified 2.10 V anchor survives as its own gate. If the operator does not
  accept those, the correct disposition is to **reject this record and leave
  the row FAIL** — not to reach for the divider-shift or bound-relaxation
  alternatives above.
- **Bad consequence**: pre-#138 dropout records are stranded. They remain valid
  append-only evidence of what they measured, but the number in them is not
  this row's dropout and must not be quoted as such. Any future comparison
  across that boundary has to say which definition it is using.
- **A regression guard ships with this**:
  `sim/tests/test_harness.py::TestDropoutMeasuresTheRegulationKnee` pins the
  swept-supply measurement, the 1.764 V knee threshold, the surviving 2.10 V
  regulation gate, **and the unchanged 300.0 mV bound** — so a future edit can
  neither regress to the fixed-headroom subtraction nor "fix" a failure by
  moving the ratified number.
