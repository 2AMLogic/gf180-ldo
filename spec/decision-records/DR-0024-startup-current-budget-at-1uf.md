# DR-0024: restate the Startup row as a startup-current budget at 1 µF, and re-centre the soft-start ramp ~5x faster

- **Status**: proposed
- **Date**: 2026-09-15
- **Decided by**: agent-builder (issue #212) — proposing; the ratified spec
  is a human gate (2026-08-19 ratification-via-PR policy, 2AMLogic/2am#357),
  and nothing in this record changes `README.md`'s Startup row until a PR
  carrying this record's `Status` flip is human-merged. Until then the row
  stands exactly as DR-0006 left it (≤ 1 V/ms ramp, ±2% within 6 ms,
  inrush/clearance at C_eff = 4.7 µF) and
  `sim/soft-start/records/20260915-103035-18f664f.md` records the design
  against **both** the ratified bound and this record's proposed one.

## Context

Issue #212 is an operator-requested follow-up to PR #127's market-key
escalation on DR-0006: TI's TLV774/TLV700 start up roughly 60x faster than
this design's ratified 6 ms window, and the operator asked for a scoped
design/spec change rather than a catalog disclosure. Issue #212's own
analysis (reproduced there, not restated here) finds the gap is a spec
*choice*, not process or topology: this design bounds inrush at DR-0001's
4.7 µF capacitor-window ceiling and guarantees a **worst-case** PVT corner,
while TI bounds inrush not at all (their datasheets state only that a
soft-start circuit "avoids excessive inrush current," current-limited at
larger C_out) and quotes a **typical** figure at 1 µF. The untrimmed on-chip
ramp's own 2.9:1 PVT spread (DR-0006) then pins the *slowest* corner far
below what the *fastest* corner's headroom would otherwise allow.

Two records already sit on this exact fault line and are not reopened here:

- **DR-0006** (ratified) found the original 3 ms settling window and the
  ≤ 1 V/ms ramp bound cannot jointly hold across the measured 2.93:1 PVT
  spread, and amended settling to 6 ms — the slowest **measured** point
  (5.82788 ms) plus ~3% headroom.
- **DR-0022** (proposed, not yet ratified) found the inrush/current-limit-
  clearance sub-clauses cannot hold at DR-0001's 4.7 µF ceiling either, for
  the same single-global-rate reason, and restated them as bound at
  C_eff = 1 µF only — "characterized, not bound" above that.

This record generalizes DR-0022's move (restate the budget at 1 µF, the
value TI's own comps are quoted against) to the **ramp bound itself**, and
re-sizes the soft-start ramp to use the resulting headroom, closing most of
the 60x gap DR-0006 disclosed rather than declining it.

### What re-centring costs, and what it buys

At V_out = 1.8 V, I = C·dV/dt. The ratified ≤ 1 V/ms bound is sized against
DR-0001's 4.7 µF ceiling (inrush ≤ 4.7 mA there); at 1 µF the same 1 V/ms
ramp only draws 1 mA, ~4 mA of unused headroom under any 5 mA inrush budget.
Spending that headroom (re-centring the ramp ~5x faster, to a ≤ 5 V/ms bound
at 1 µF) keeps inrush at 1 µF inside the same 5 mA figure DR-0004 originally
derived, while cutting worst-corner settling time by roughly the same 5x
factor DR-0006's own arithmetic predicts (`1.764 V / rate`). Issue #212's own
back-of-envelope estimate, assuming the 2.93:1 spread carries over unchanged
and the ramp is the only delay in the loop, put the resulting worst corner at
~1.05 ms. **Measured evidence below corrects that estimate**: a fixed
hold-release delay (the two `Rh_ss·Ch_ss` / `Rr_ss·Cr_ss` RCs that release
`Mhold_ss`/`Mhold_bg_ss` before the ramp is allowed to move `Vout`) adds a
PVT-dependent, non-ramp contribution that becomes a much larger fraction of
a ~1 ms budget than it was of a ~6 ms one — closing it needs scaling those
two RCs by the identical factor, not just the ramp capacitor.

## Decision

**Restate three clauses of the Startup row as a startup-current budget at
C_eff = 1 µF (DR-0001's nominal value), superseding DR-0006's settling
clause and extending DR-0022's C_eff = 1 µF reframing to the ramp bound
itself.** Concretely, once this record and DR-0022 are both ratified,
replace the row's text:

> monotonic into any load 0–50 mA and any C_eff in the stability window;
> controlled ramp ≤ 1 V/ms, so inrush ≤ 5 mA at C_eff = 4.7 µF and startup at
> full rated load stays ≥ 10 mA below the current limit; inside ±2% within
> 6 ms of enable (note 8); overshoot ≤ +2% of the final value

with:

> monotonic into any load 0–50 mA and any C_eff in the stability window;
> controlled ramp ≤ 5 V/ms, so inrush ≤ 5 mA and startup at full rated load
> stays ≥ 10 mA below the current limit, both at C_eff = 1 µF (nominal) —
> above 1 µF both clauses are characterized, not bound, up to DR-0001's
> 4.7 µF ceiling (note 5a, DR-0022); inside ±2% within **1.8 ms** of enable
> (note 8, DR-0024); overshoot ≤ +2% of the final value

- **Ramp bound**: ≤ 1 V/ms → **≤ 5 V/ms**. Measured (below): 1.24–2.95 V/ms
  across 155/163 converged points, 0/155 over the proposed bound.
- **Inrush / clearance anchor**: C_eff = 4.7 µF → **C_eff = 1 µF**, matching
  DR-0022's own move for the clearance clause and extending it to inrush.
- **Settling**: 6 ms (DR-0006) → **1.8 ms**. This is the slowest **measured**
  point among the 155 that converged (1.72525 ms, `res_ss_-40c_3.63v`,
  matching DR-0006's own worst-corner family) plus ~4% headroom — the same
  measured-envelope-plus-margin convention DR-0006 used, not the 1.2 ms
  figure issue #212's own arithmetic estimate proposed before this sweep
  existed to check it against. See "Why 1.8 ms, not 1.2 ms" below.

**Component resize implementing this** (`design/ldo_softstart.sch`,
committed alongside this record): `Css` 60 µm × 60 µm → 60 µm × 12 µm
(~7.2 pF → ~1.44 pF), `Ch_ss`/`Cr_ss` 70 µm × 70 µm → 70 µm × 14 µm each
(~9.75 pF → ~1.95 pF each) — a uniform 5x area cut on all three ramp/delay
capacitors, `Rss_bias`/`Rh_ss`/`Rr_ss` and every other element on the bias
branch **unchanged**. `Ch_ss`/`Cr_ss` move with `Css` because leaving the
hold-release delay fixed while only the ramp speeds up turns a small tax on
a multi-ms ramp into most of the budget on a sub-2-ms one (see the
schematic's own "WHY Ch_ss/Cr_ss MOVE WITH Css" note for the measured A/B:
2.033 ms with only `Css` cut vs. 1.72525 ms with all three cut).

### Evidence: `sim/soft-start/records/20260915-103035-18f664f.md`

163-point PVT sweep (the bench's standing full-factorial grid: 63-point main
matrix at 1 µF/100 mΩ/50 mA, plus DR-0001's capacitor window and the 0 mA
case over a bracketing corner subset), against the resized netlist above.
155/163 points converged to a value for every named clause; the other 8 (all
`ff_125c_3.63v*` and `sf_125c_3.63v_1u_0.1_36`) never reach 1.764 V inside
the transient window at all — this is the **pre-existing, already-tracked**
`#191` acquisition-transient/settled-leakage regression
(`design/ldo_softstart.sch`'s own "KNOWN, UNRESOLVED REGRESSION (#191)"
note), reproduced numerically to five figures against the prior record that
first characterized it
(`vout_settled` = 1.56863 V here vs. 1.569 V in
`sim/soft-start/records/20260906-230703-d3cb117.md`) — not a new finding of
this record, and not this record's scope to fix.

| clause (bound) | pass | worst point |
|---|---|---|
| steady ramp rate ≤ 5 V/ms | **155/155** | 2.9502 V/ms, `ff_125c_2.97v*` family |
| non-monotonic / peak-transient dVout/dt vs. ± 5 V/ms | 109/155, 34/155 | dominated by the #191 transient, see below |
| inrush ≤ 5 mA at C_eff = 1 µF (79 points) | 18/79 | up to 271.9 mA, dominated by #191, see below |
| clearance ≥ 10 mA below 62.0 mA limit, C_eff = 1 µF | 46/79 | up to 274.9 mA supply peak, same cause |
| settling ≤ 1.8 ms | **155/155** | 1.72525 ms, `res_ss_-40c_3.63v*` family |
| settling ≤ 1.2 ms (issue #212's original estimate) | 98/155 | same worst point |
| overshoot ≤ +2% | 151/155 | 4 points at `*_-40c_*_0.33u_0.001_36`, pre-existing (below) |

**The ramp-rate and settling clauses — the two this record actually
changes — pass at every converged point, with margin.** The inrush,
clearance, monotonicity and (4 of the) overshoot failures are the
pre-existing #191 regression, confirmed by a same-corner A/B test against
`origin/main`'s own committed (pre-#212) netlist at
`sf_-40c_2.97v_1u_0.1_36`: 231.1 mA inrush on `main`, 271.9 mA on this
record's resized netlist — both far over the 5 mA budget, same order of
magnitude, on a device this resize does not touch. The same sweep's nominal
corner (`tt_27c_3.30v_1u_0.1_36`) stays clean on both netlists (1.19 mA
pre-resize, 4.76 mA post-resize), matching the #191 note's own "clean at
nominal, not at most other points" characterization. This record does not
claim the inrush/clearance/monotonicity clauses pass — they do not, exactly
as they did not before this issue, for a cause this issue's own component
resize does not touch and is not scoped to fix (tracked by #198).

### Why 1.8 ms, not 1.2 ms

Issue #212's own estimate ("~1.05 ms worst case") assumed the ramp's
2.93:1 PVT spread carries over unchanged and that reaching the 1.764 V
threshold is purely a function of the ramp rate. Measured, the spread
narrows to 2.38:1 (1.24–2.95 V/ms) — because `Ch_ss`/`Cr_ss`'s own
hold-release delay, scaled by the same 5x factor, contributes a PVT term
that does not track the ramp's corner-to-corner ratio one-for-one — and the
worst point (1.72525 ms) is materially higher than the pure-ramp arithmetic
(1.764 V / 1.35 V/ms ≈ 1.31 ms) because of that same fixed delay. **Setting
the bound at 1.2 ms would misclassify 57 of 155 real, converged points as
failing a target this design was never sized to hit** — DR-0006 rejected
exactly this shape of error for the original 3 ms bound, and this record
declines to repeat it against the sweep's own evidence. 1.8 ms retains
~4.3% headroom over the worst measured point, comparable to DR-0006's ~3%.

### Against TI's TLV774/TLV700 typicals

Comparison table, per issue #212's own acceptance criteria. TI's figures are
**typical**, at 1 µF, unbound (see issue #212's own sourcing — TLV774
SBVS456B §6.5, TLV700 SLVSA00E — neither datasheet states a maximum). This
record's figures are **worst-corner, measured, bound** — the two are not the
same statistical quantity, and the gap below is not closed by this record's
own "typ vs. untrimmed worst case" caveat.

| | TLV774 (typ, 1 µF) | TLV700 (typ, 1 µF) | gf180-ldo, pre-DR-0024 (worst, ratified) | gf180-ldo, DR-0024 proposed (worst, measured) |
|---|---|---|---|---|
| t_startup | 400 µs | 100 µs | 5.82788 ms (DR-0006, C_eff = 4.7 µF) | **1.72525 ms** (this record, C_eff = 1 µF) |
| Implied ratio vs. TLV774 typ | 1x | 0.25x | ~14.6x | **~4.3x** |
| Implied ratio vs. TLV700 typ | 4x | 1x | ~58.3x | **~17.3x** |
| Ramp bound | none stated | none stated | ≤ 1 V/ms | ≤ 5 V/ms |
| Inrush bound at 1 µF | none stated | none stated | 1 mA (unused headroom under the old 4.7 µF-anchored bound) | ≤ 5 mA |

This record's resize takes the worst-corner gap from ~58x (against TLV700
typ, using DR-0006's 6 ms figure) to ~17x, and from the ~60x issue #212's
own title cites (a mixed comparison across both parts) to a comparable
single-digit-to-low-teens range depending on which TI part and which of
its own typ/max the reader anchors to. It does not close the gap to 1x:
doing so would need either a typical-not-worst-case claim (which this
design's untrimmed PVT spread does not support making) or a trim
provision (DR-0004/DR-0005/DR-0006 all declined this for the same reason:
a mask/test-time commitment outside this block's charter). The remaining
gap is disclosed here, not claimed away, per the same posture DR-0006's
own market-key finding established.

## Alternatives considered

- **Keep the 1.2 ms figure from issue #212's own estimate.** Rejected: the
  measured 155-point sweep shows it fails at 57/155 real points, for a
  reason (`Ch_ss`/`Cr_ss`'s fixed delay) the pre-sweep arithmetic did not
  model. Proposing a bound the evidence already falsifies is the DR-0006
  mistake this record exists to avoid repeating.
- **Re-centre further (e.g. 8–10x) to push the worst corner under 1.2 ms.**
  Not attempted here: DR-0006's own arithmetic warns that narrowing a
  settling window faster than the ramp's PVT spread allows just relocates
  the failure (a re-centring tight enough to hit 1.2 ms would need the
  fastest corner to sit close enough to the (also-tightening) ramp bound
  that margin on the ramp clause itself starts to erode) — worth a
  follow-up record if a consumer states a harder requirement, not
  speculative work here.
- **Leave the ramp bound at 4.7 µF and only move settling (this record's
  original scope as literally read from issue #212's title).** Rejected:
  DR-0022 already showed the 4.7 µF anchor is arithmetically unmeetable for
  the clearance sub-clause at *any* single global rate; re-centring the ramp
  without also moving its C_eff anchor would reopen that conflict at the
  faster rate, not close it.
- **Fix the #191 regression first, then re-measure.** Rejected as a
  precondition: #191/#198 is tracked separately, is orthogonal to the ramp
  block this record resizes (the regression lives in the FB-injection
  transconductor, not `Css`/`Ch_ss`/`Cr_ss`), and gating this record on it
  would block a real, independently-verifiable improvement on an unrelated
  defect's timeline. The A/B evidence above exists specifically so this
  record's own claim is not contaminated by that defect's numbers.

## Consequences

- **The ramp-rate and settling clauses become meetable at their proposed
  values, with margin, and are evidenced end to end** — every one of the
  155 points that converged passes both.
- **Startup time falls from ≤ 6 ms to ≤ 1.8 ms worst corner** (a ~3.3x
  reduction in the ratified ceiling; the ~5x ramp re-centring itself is
  partly eaten by the fixed hold-release delay, per "Why 1.8 ms" above),
  closing most — not all — of the disclosed 60x gap against TI's TLV774/
  TLV700 typicals (roughly 4–18x remaining, depending on which TI figure is
  compared against, itself a typical-vs-worst-corner comparison this record
  does not resolve).
- **Inrush and clearance above 1 µF remain characterized, not bound**,
  exactly as DR-0022 already established for clearance; this record adds
  inrush to that same posture rather than reopening DR-0022's own scope.
- **The #191 acquisition-transient/settled-leakage regression is untouched
  and unresolved.** It dominates this record's inrush, clearance,
  monotonicity, and 4/155 overshoot pass counts, at C_eff = 1 µF and every
  other capacitor point alike, and is tracked by #198, not this record.
  Anyone reading this record's evidence table as "the Startup row now
  passes" is reading it wrong for those four sub-clauses; the ramp-rate and
  settling clauses are the ones this record's evidence supports.
- **`sim/soft-start/testbench/summarize.py`'s bounds are updated** to this
  record's proposed values (`RAMP_MAX_VPMS = 5.0`, `SETTLE_MAX_S = 1.8e-3`
  — this record's own measured-worst-point-plus-margin figure, not issue
  #212's pre-sweep 1.2 ms estimate) and the inrush/clearance checks anchored
  to C_eff = 1 µF only. These are tooling defaults for the *next* sweep, not
  a spec change themselves — `README.md`'s ratified row is unchanged until
  this record is ratified.
- **`README.md` is not edited by this record.** Per the ratification-via-PR
  policy and the precedent DR-0022/DR-0023 already set (both `proposed`,
  neither referenced in `README.md` yet), the ratified spec table stays
  exactly as DR-0006 left it until a human merges the PR that flips this
  record's `Status`. `sim/CHARACTERIZATION.md` likewise is not regenerated
  by this record — its Startup row already reads FAIL/STALE against the
  ratified spec and stays that way; regenerating it against unratified
  numbers would misstate what is currently required.
- **`sim/startup`'s separate testbench (`tsettle_full_ms`/`tsettle_min_ms`,
  C_eff = 4.7 µF, `tb.json`) is not re-run or updated by this record.** That
  bench's own claim text anchors it at DR-0001's 4.7 µF ceiling — the
  capacitor value this record deliberately moves the settling clause *away*
  from, to 1 µF — so its existing 3 ms-anchored checks are neither
  contradicted nor confirmed by this record's 1 µF evidence. A fresh
  `sim/startup` record at 1 µF, or a decision about what (if anything) the
  4.7 µF settling behavior should be bound to post-resize, is a follow-on,
  not part of this record.

## Cross-consequences (other records)

- **DR-0006**: this record supersedes its settling clause (6 ms → 1.8 ms)
  using the same measured-worst-point-plus-margin method DR-0006 itself
  established; DR-0006's ramp-rate evidence (the original ≤ 1 V/ms sizing)
  is superseded by this record's resize, not merely amended.
- **DR-0022**: this record extends DR-0022's "characterized, not bound above
  1 µF" posture from the clearance sub-clause alone to inrush as well, and
  reuses its C_eff = 1 µF anchor for the ramp bound itself. DR-0022's own
  arithmetic (why no single global rate can satisfy the clearance clause at
  4.7 µF) is unaffected and still the correct reasoning for why 4.7 µF stays
  characterized-only under the new, faster ramp too.
- **DR-0001**: unaffected as a decision; its capacitor window remains the
  axis this record's C_eff = 1 µF anchor sits inside, exactly as DR-0022
  already established.
- **#191 / #198**: this record's evidence corroborates, with a fresh A/B
  data point, that the acquisition-transient/settled-leakage regression
  those issues track is unrelated to the ramp/delay-RC sizing this record
  changes. It does not discharge #198's own scope.
