# DR-0022: the Startup row's current-limit-clearance clause is a bound only up to C_eff = 1 µF, not to DR-0001's 4.7 µF ceiling

- **Status**: proposed
- **Date**: 2026-09-06
- **Decided by**: agent-builder (issue #187) — **proposing**; the ratified
  spec is a human gate, and nothing in this record changes the table until
  it is ratified. Until then `README.md`'s Startup row stands as written and
  `sim/soft-start/records/20260906-125202-f1096c9.md` records the
  current-limit-clearance sub-clause as **failing** at the top of DR-0001's
  capacitor window.

## Context

DR-0006 already found one arithmetic conflict inside the Startup row (the
3 ms settling window vs. the ≤ 1 V/ms ramp bound) and proposed resolving it
without touching the row's other four clauses — explicitly declining to
relax *"inrush ≤ 5 mA at C_eff = 4.7 µF"* or *"startup at full rated load
stays ≥ 10 mA below the current limit"*, on the reasoning that the ramp's own
steady contribution to each (3.9 mA of capacitor current at the fastest
measured corner) already satisfies both, and that the excess measured at the
time (12.7–22.3 mA peak) was two short transients — a circuit defect, not a
spec defect. Issue #43 built the fix for one of those two transients
(`Rz_ss`, a nulling resistor damping the clamp loop's acquisition) and closed
inrush everywhere in DR-0001's capacitor × ESR window except its 4.7 µF end.
Issue #187 measured what is left there
(`sim/soft-start/records/20260906-125202-f1096c9.md`, 163 points):

| group | inrush (`icap_peak_ma`, ≤ 5 mA) | peak supply (`isup_peak_ma`, ≤ 52 mA) |
|---|---|---|
| 4.7 µF / 500 mΩ / 50 mA (20 pts) | 8.78 … 14.86 mA, 0/20 | 51.75 … 53.82 mA, **2/20** |
| 4.7 µF / 1 mΩ / 50 mA (20 pts) | 9.54 … 16.50 mA, 0/20 | 51.75 … 53.81 mA, **2/20** |

This record is about the **second column only** — the current-limit-clearance
sub-clause, whose 52 mA ceiling is `62.0 mA − 10 mA`, where 62.0 mA is the
worst-corner current limit measured in
`sim/current-limit/records/20260905-230521-3093ea1.md` (DR-0005; unratified,
but the physical value a real part exhibits regardless of what number is
ratified as the target window). The first column (inrush) is left exactly
where DR-0006 put it — open circuit debt, tracked by issue #189 (FB-injection
soft-start redesign, filed alongside this record) — because, unlike the clearance clause,
nothing in this record shows it to be arithmetically unmeetable.

### The clearance clause is arithmetic, not dynamics, and independently reproducible from the committed data

`isup_peak_ma` is not measured at the same instant as `icap_peak_ma`. The
capacitor's peak (the acquisition transient, DR-0006's circuit debt) happens
220–570 µs after enable, while the output is still well below its final
value and the resistive load is drawing far less than 50 mA. The supply
current's peak happens later, near the **end** of the ramp, when the load has
reached its full 50 mA **and** the ramp is still charging `C_eff` at its
steady rate. A linear regression of the 4.7 µF/500 mΩ group's own committed
`sim/soft-start/corners/20260906-125202-f1096c9/summary.csv` (20 points,
`isup_peak_ma` against `slope_vpms`) confirms this directly:
`isup_peak_ma ≈ 50.56 mA + 4.00 × slope_vpms`, with every point within
0.32 mA of that line (`R² ≈ 0.95`) — i.e. **the corner-to-corner variation in
this clause's measured value is explained almost entirely by the ramp's own
steady rate, with no transient contribution needed.**

The ramp's steady rate (`slope_vpms`) is set once, on-chip, by
`VREF / (R_ss_bias · C_ss)` (`design/netlist/ldo_softstart.sch`'s
`Fss_ramp`/`XCss`), and once the main loop has handed over it holds `V_out =
1.5 × V_SSR` regardless of `C_eff` — the external output capacitor is a load
on that servo, not an input to its rate. So `dV_out/dt` is a process/temperature
quantity, not a `C_eff`-conditioned one, and the committed record's own
163-point `slope_vpms` column (0.3163 … 0.8357 V/ms, all corners, all
capacitor values) is the direct evidence: it is the *same* spread at 0.33 µF,
1 µF and 4.7 µF, and only the product `C_eff × slope_vpms` changes with the
capacitor.

### No single ramp rate closes this while also respecting the settling window

Solving the fit above for the clearance ceiling (`isup_peak_ma ≤ 52.0 mA`)
gives `slope_vpms ≤ (52.0 − 50.56) / 4.00 ≈ 0.36 V/ms` — **at every corner**,
including this design's own fastest measured corner, `0.836 V/ms` (4.7 µF
group) / `0.867 V/ms` (DR-0006's broader 163-point measurement). Clearing
0.36 V/ms there needs the whole ramp re-centred down by a factor of
`0.867 / 0.36 ≈ 2.41×`.

The ramp's corner-to-corner spread is not independently tunable — it is set
by the same `R_ss_bias`/`C_ss` sizing at every corner, so a global re-centring
scales the *slowest* corner down by the same factor as the fastest. DR-0006's
own measured slowest point, `ss / −40 °C / 3.63 V` at 0 mA load
(`slope_vpms = 0.296 V/ms`), is also the corner that sets DR-0006's own
proposed 6 ms settling window (`t_startup = 5.88 ms` there — the number the
6 ms figure is built from, plus ~2 %). Scaled down by the same 2.41× needed to
clear the clearance clause, that corner's rate falls to `≈ 0.123 V/ms`, and
its `t_startup` rises to `≈ 1.764 V / 0.123 V/ms ≈ 14.3 ms` — more than **double
DR-0006's own proposed 6 ms window**, not merely short of the ratified 3 ms
one. **No re-centring of this design's single global ramp rate satisfies the
clearance clause at 4.7 µF without pushing `t_startup`'s worst corner outside
any settling window this design has proposed, ratified or not.** This is the
same shape of conflict DR-0005 and DR-0006 already found on this block — one
absolute on-chip `R·C`/resistor quantity, with a PDK-set spread, pinned
between two ratified numbers that together demand more range than a single
untrimmed sizing can deliver — and it is why this is a decision record rather
than a circuit-tuning task.

A structurally different ramp (e.g. current-mode: charge `C_eff` at a fixed
current instead of a fixed voltage rate) does not sidestep this either — it
trades the failure for the opposite one. A fixed charge current sized to
leave the clearance clause's roughly 2 mA of headroom free at 4.7 µF produces
`dV/dt ≈ 2 mA / 0.33 µF ≈ 6 V/ms` at the *bottom* of DR-0001's capacitor
window — 6× over the ratified ≤ 1 V/ms ramp bound there. The wide
(0.33–4.7 µF, a 14.2:1 span) capacitor window is itself why a single fixed
soft-start law, of either kind, cannot hold a current headroom bound at one
end and a rate bound at the other.

`#187`'s own FB-injection proposal (Direction 2 — inject a decaying current
into `FB` so `error_amp`'s inputs stay pinned at `VREF`) does not change any
of this arithmetic: it forces `V_out = 1.5 × V_SSR` through the main loop
instead of through the clamp, but `V_SSR`'s rate is set by the same `R·C`
timebase either way, so `dV_out/dt` is exactly as `C_eff`-independent as
before. That proposal is a genuine fix for the *acquisition* transient
(inrush), left open by this record — not for the clearance clause decided
here.

## Decision (proposed)

**Restate the current-limit-clearance sub-clause of the Startup row as a
bound at `C_eff = 1 µF` (DR-0001's nominal value), not at the 4.7 µF ceiling
of DR-0001's verified window.** Above 1 µF, the clause is **characterized,
not bound** — same posture DR-0001 itself already takes for operation above
its own 4.7 µF ceiling ("unverified, not known-bad"), applied here one step
earlier because the arithmetic, not merely the absence of a measurement, is
what changes above 1 µF.

Concretely, replace the Startup row's text:

```markdown
| Startup | monotonic into any load 0–50 mA and any C_eff in the stability window; controlled ramp ≤ 1 V/ms, so inrush ≤ 5 mA at C_eff = 4.7 µF and startup at full rated load stays ≥ 10 mA below the current limit; inside ±2% within 3 ms of enable; overshoot ≤ +2% of the final value | — |
```

with:

```markdown
| Startup | monotonic into any load 0–50 mA and any C_eff in the stability window; controlled ramp ≤ 1 V/ms, so inrush ≤ 5 mA at C_eff = 4.7 µF; startup at full rated load stays ≥ 10 mA below the current limit at C_eff = 1 µF (nominal) — the clearance narrows above 1 µF as the ramp's own C_eff × dV/dt rides on top of the rated load, and is characterized rather than bound up to the 4.7 µF ceiling (note 5a); inside ±2% within 3 ms of enable; overshoot ≤ +2% of the final value | — |
```

and add note 5a: *"the current-limit-clearance sub-clause is arithmetic, not
a circuit property, above 1 µF — see DR-0022. Measured envelope at the
4.7 µF ceiling: 51.7–53.8 mA against the 52.0 mA target (`sim/soft-start/
records/`)."*

The inrush sub-clause's own C_eff = 4.7 µF binding point is **untouched** —
this record does not reopen DR-0006's classification of it as circuit debt.

## Alternatives considered

- **Re-center the ramp rate to close the clause at 4.7 µF** — rejected,
  quantitatively, above: a 2.41× downward re-centring closes the clearance
  clause at the fastest corner but pushes the slowest corner's `t_startup` to
  roughly 14.3 ms, over double DR-0006's own proposed 6 ms settling window.
  Not merely hard — infeasible with a single global rate, regardless of which
  specific corner it is centred on.
- **Raise the current-limit-clearance margin's ceiling by tightening
  `DR-0005`'s window (trim `Rsns`)** — rejected here for the same reason
  DR-0005 itself declined to trim: a mask/test-time commitment outside this
  block's charter, not a decision this record can make unilaterally. If
  DR-0005's stretch (±10 % trimmed) is ever pursued, it raises `I_lim,min`
  and this record's arithmetic should be revisited then, as its own
  "Consequences" section below notes.
- **Reduce the ratified 10 mA clearance margin** — rejected. The margin
  exists to keep the current limit from nuisance-engaging under the sense
  path's own uncharacterized mismatch (DR-0005's own concern for the limit
  circuit itself); narrowing it to buy back the ~2 mA of headroom needed at
  4.7 µF moves risk from "the Startup row's peak-supply report" to "the
  current-limit sense path under process variation," which is a worse place
  to spend margin.
- **Adopt a current-mode (fixed-charge-current) ramp instead of the current
  fixed-rate ramp** — rejected, quantitatively, above: it trades the 4.7 µF
  failure for a roughly 6× overage of the ≤ 1 V/ms bound at 0.33 µF. The
  14.2:1 capacitor window is what makes both fixed laws fail at opposite
  ends; neither is a free substitution for the other.
- **Leave the clause bound at 4.7 µF and record the design as failing** —
  rejected as the only action, for the same reason DR-0005 and DR-0006 gave:
  it leaves a ratified line that no untrimmed implementation on this PDK, of
  any topology tried or proposed so far, can satisfy.

## Consequences

- **The Startup row's current-limit-clearance clause becomes verifiable.**
  With the bound restated at 1 µF, the design passes it there (63/63 main
  matrix, 20/20 at 0 mA) and the remainder of DR-0001's window is
  characterized rather than silently claimed.
- **Inrush at 4.7 µF remains open circuit debt**, exactly as DR-0006 already
  classified it, and is tracked by issue #189 rather than by this record.
  Getting it under 5 mA needs the acquisition lag itself to
  shrink (issue #187's Direction 2/3, issue #189's scope), which this record's arithmetic shows
  is orthogonal to — and cannot be substituted for — the clearance clause
  decided here.
- **If DR-0005's trimmed stretch (±10 %, raising `I_lim,min` well above
  62.0 mA) is ever pursued, this record's arithmetic should be redone**: a
  higher `I_lim,min` widens the 10 mA-clearance ceiling and may push the
  1 µF binding point back out toward 4.7 µF on its own, without any change
  to the ramp. This record does not assume that will happen.
- **DR-0006's own Consequences section already flagged** that the Startup
  row's remaining failures "need a follow-on issue against `ldo_softstart`'s
  two transients" — this record discharges the clearance half of that
  warning as a spec matter and leaves the transient half exactly where
  DR-0006 put it.
- Any future widening of DR-0001's capacitor window ceiling above 4.7 µF
  must redo this record's arithmetic too — the 1 µF binding point was
  derived against the current 4.7 µF ceiling and the current measured ramp
  spread, not against some larger headroom.

## Cross-consequences (other records)

- **DR-0001**: unaffected as a decision — its capacitor window is verified
  for stability (PM/GM) independently of this record, which only concerns
  the Startup row's clearance sub-clause. This record borrows DR-0001's own
  "characterized, not bound, above the verified point" posture and applies
  it one step earlier for this one sub-clause.
- **DR-0005**: this record's 52 mA ceiling is derived from DR-0005's
  measured 62.0 mA worst-corner current limit, not from the still-unratified
  65–80 mA target window — consistent with how `sim/soft-start`'s own
  testbench has always computed the clearance bound.
- **DR-0006**: this record narrows the *scope* of one clause DR-0006 already
  discussed (current-limit clearance) without touching DR-0006's own decision
  (the settling window) or its classification of the inrush clause as circuit
  debt. The two records address different sub-clauses of the same row and
  are independent proposals — either can be ratified without the other.
