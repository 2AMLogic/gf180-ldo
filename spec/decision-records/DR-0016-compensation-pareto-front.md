# DR-0016: The compensation Pareto front for wide cap × load range — a spec-and-lever trade study, not a new circuit

- **Status**: proposed — ratification is the operator's, the same process
  DR-0001, DR-0007, DR-0008, DR-0009 and DR-0012–DR-0015 went through.
  **Nothing in this record is in force until an operator ratifies it, and it
  proposes no `design/` change and no relaxation of any ratified bar.** It is
  a trade study over four candidate directions, each mapped to what it would
  cost and what it would close, so the operator's #51 decision has an
  explicit account to rule on instead of an implied one.
- **Date**: 2026-08-11
- **Decided by**: Builder agent, issue #90 (recommendation only)
- **Builds on**: DR-0012 (shelf width = `Cc/Cf`), DR-0013 / DR-0014
  (Candidate-2 negative results that rule out the bias and fixed-`Rz` levers),
  DR-0015 (the landed adaptive shelf, 1332 → 2930/4536, and its own "ways
  out" list), DR-0007 (the held 0 mA envelope decision), DR-0008 (the
  ratified RHP-pole precondition that makes every count below admissible).
  Does not supersede any of them — it reads their numbers together and adds
  none of its own beyond what is recomputed directly from the committed
  matrix CSV below.

## Context

DR-0015 landed the adaptive shelf (a triode replica across `Rz`, gated by the
pass gate's own drive) and moved the head loop-stability record from
1332/4536 to **2930/4536**
(`sim/loop-stability/records/20260807-103351-64249c6.md`, superseding
`20260802-204343-e912fbd`). The residual 1606 fails are not scattered; DR-0015
itself closes the form of them (its "What is still not reached" section): the
loop's crossover has to land inside a **38.6:1** pass band, and the design has
to cover a **1029:1** span of it, with the load axis now compressed out by
`Rz_eff` tracking `gm_pass` but the **output-capacitor** axis left
untouched — because `Rz_eff` is one number per load, and the cap window has to
fit inside the band at whatever that number is.

Re-deriving the residual directly from the committed matrix CSV (not
re-simulated — read from the already-recorded 4536-row file, `iload_ma` ×
`ceff_uf` cells, 252 points per cell = 63 PVT corners × 4 ESR values):

| `I_load` \ `C_eff` | 0.33 µF | 1 µF | 4.7 µF |
|---|---|---|---|
| 0 mA | 0/252 | 0/252 | 0/252 |
| 0.1 mA | 250/252 | 252/252 | 173/252 |
| 1 mA | 230/252 | 252/252 | 232/252 |
| 10 mA | 73/252 | 252/252 | 242/252 |
| 25 mA | 24/252 | 241/252 | 248/252 |
| 50 mA | 2/252 | 209/252 | 250/252 |

(source: `sim/loop-stability/records/20260807-103351-64249c6-matrix.csv`,
grouped by `iload_ma`/`ceff_uf`, counting `result == PASS`.) The shape matches
the issue's own coarser single-PVT-point map: heavy load wants more cap
(0.33 µF collapses above 10 mA), light load wants less (4.7 µF is worst at
0.1–1 mA), and 0 mA fails at every cap, unconditionally. No fixed or
load-adaptive-only compensation spans the full ratified 0.33–4.7 µF (14.2×)
window across 0–50 mA, and DR-0015 already proves why: `Rz_eff` is a function
of load alone, so at a single load it is a single number, and the cap window
has to fit inside the 38.6:1 band at that one number
(`sim/loop-stability/records/20260807-103351-64249c6.md`, "The obstruction, at
50 mA").

This record does not re-derive that mechanism — DR-0015 already did, in full,
with the closed-form and the measured `f_hi` gap (0.31 MHz measured against
0.76–0.95 MHz required). What follows is a trade study over what to do about
it: **narrow the requirement, spend a bounded resource to widen the design's
reach, resolve the 0 mA point on its own terms, or add a discrete mode** — with
every quantitative line below traced to a committed `sim/` record, a
`design/` document, or a named external reference.

## The four candidates, mapped to coverage and cost

### 1. Narrow the output-cap spec — zero silicon, available today

`sim/loop-stability/records/20260807-103351-64249c6-matrix.csv`, filtered to
`ceff_uf == 1.0` and `iload_ma > 0`, sorted by ESR:

| ESR floor | points passing (1 µF, 0.1–50 mA) |
|---|---|
| ≥ 1 mΩ (no floor, DR-0001 as ratified) | 274/315 (87.0 %) |
| ≥ 50 mΩ | 302/315 (95.9 %) |
| **≥ 200 mΩ** | **315/315 (100.0 %)** |
| ≥ 500 mΩ | 315/315 (100.0 %) |

At the single measured nominal point `C_eff = 1 µF` with an ESR floor of
**≥ 200 mΩ**, the committed design (DR-0015, no further change) passes **100 %
(630/630)** of every PVT × ESR-above-floor combination from 0.1 mA to 50 mA —
recomputed the same way for both loads and ESR values above 200 mΩ from the
same CSV. 0 mA is unaffected by this candidate (0/252 at 1 µF regardless of
ESR — see Candidate 3): narrowing the cap does not touch the no-load column at
all, because that column already fails at every cap in the ratified window.

- **Coverage**: closes 100 % of 0.1–50 mA at the single point (1 µF, ESR ≥
  200 mΩ); does not touch 0 mA.
- **Area cost**: 0 — no `design/` change.
- **Iq cost**: 0 — unchanged, 22.60 µA worst-corner
  (`sim/quiescent-current/records/20260807-105203-64249c6.md`, ratified
  < 30 µA row).
- **PSRR / other ratified-row spend**: 0 — unchanged, 50.2518 dB worst-corner
  (`sim/psrr-dc/records/20260807-105159-64249c6.md`, ratified 50 dB floor).
- **Required external-cap / ESR spec**: DR-0001's 0.33–4.7 µF (14.2×) window
  collapses to a single nominal value, and the "no minimum ESR" clause DR-0001
  states explicitly is replaced by a ≥ 200 mΩ floor. This is a real usability
  cost, not a free lunch: many ceramic X5R/X7R parts at 1 µF sit well under
  200 mΩ of ESR on their own, so a consumer would need either a
  higher-ESR-class part or a deliberate series resistor — the same kind of
  application note DR-0007's "Alternatives considered" already flags for the
  preload case, applied here to ESR instead of load.

This candidate needs no new evidence — it is a re-reading of the record
already on `main`. Its only cost is the spec's own width.

### 2. Q-reduction / bandwidth boost to close the wide-cap axis at heavy load

DR-0015's own "ways out" list names this move ("Buy `f_hi`") and bounds it
without building it: raising the output stage's phase-cliff frequency `f_hi`
from its measured 0.31 MHz to 0.76–0.95 MHz is what the closed form in
DR-0015's "What is still not reached" section requires to close the
1–50 mA/0.33 µF cluster (the residual's "above" edge). This is the design's
own instance of the published damping-factor-control / `Q`-reduction family —
K. N. Leung and P. K. T. Mok, "A Capacitor-Free CMOS Low-Dropout Regulator
with Damping-Factor-Control Frequency Compensation," *IEEE JSSC*, 2003
(already cited as the canonical reference for this mechanism in
`spec/architecture-survey.md` §4.2/§7) — applied to the output-buffer stage
rather than to a capless pass gate.

What is and is not measured:

- **Direction and rough scale are measured, not modelled**: DR-0009's own
  exploration (explicitly an unminted `sim/amp-openloop/ --no-write` run, not
  a committed record — flagged as such there and repeated here with the same
  flag) found that tripling the buffer's and stage-2's standing current raised
  the amplifier's local-loop crossover `f_2` from 131 kHz to 393 kHz (8.6 µA →
  16.4 µA amplifier Iq) — a super-linear return on the first 3×, which is the
  basis for treating a further ~2–3× as plausible rather than requiring an
  order of magnitude.
- **The Iq ceiling is measured, and it has moved since DR-0009's estimate.**
  DR-0015's own head record puts full-load Iq at **22.60 µA**
  (`sim/quiescent-current/records/20260807-105203-64249c6.md`, worst corner
  `ff`/125 °C/3.63 V) against the ratified < 30 µA row — **7.40 µA** of
  headroom at the current design point, not the 5.19 µA DR-0015 quotes against
  its own pre-change 24.81 µA baseline.
- **What is not measured**: this move's effect on `gain_1k_db` / PSRR (both
  currently at essentially zero margin — `gain_1k_db` 53.7736 dB against a
  53.5 dB floor, `psrr_ldo_1k_db` 50.2518 dB against 50 dB,
  `sim/amp-openloop/records/20260807-105147-64249c6.md` and
  `sim/psrr-dc/records/20260807-105159-64249c6.md`), its effect on
  `sim/amp-selfosc/`'s DR-0008 precondition, and whether it in fact closes the
  0.33 µF/heavy-load cells rather than only narrowing them. DR-0015 says
  exactly this: "it should be its own issue and its own record rather than an
  amendment here."

- **Coverage**: targets the 0.33 µF/1–50 mA cluster specifically (map above:
  73/252 at 10 mA, 24/252 at 25 mA, 2/252 at 50 mA) — the "above" edge of
  DR-0015's band, where `f_c` overruns the output stage's phase cliff. It does
  not reach the "below" edge (0 mA): DR-0015's own closed form for that column
  is a floor on `Rz·sqrt(Cc)` set by the 0 → 0.1 mA step in `gm_pass`, not by
  `f_hi` — raising `Rz` far enough to fit that step reopens the 0.1 mA/0.33 µF
  cliff on the *upper* edge instead ("the 0 mA column opens and the
  0.1 mA/0.33 µF cell closes, for no net gain. Same wall, same number.",
  DR-0015 §"What was built"). `f_hi` is a different, and orthogonal, number —
  see Candidate 3 for the 0 mA corner.
- **Area cost**: unbounded by any committed number; bounded only by the core
  budget's headroom — the amplifier as committed is ≈ 17 100 µm²
  (`design/error_amp.md` §8, ≈ 17 % of the < 0.1 mm² core row), leaving
  ≈ 83 000 µm² (≈ 83 %) unused. No layout estimate exists for this candidate.
- **Iq cost**: bounded at ≤ 7.40 µA under the ratified row at the current
  design point, from a non-record exploration data point suggesting the first
  3× is achievable well inside that budget.
- **PSRR / other ratified-row spend**: unmeasured and flagged as the open
  risk — both `gain_1k_db` and `psrr_ldo_1k_db` are within ≈ 0.25–0.27 dB of
  their ratified floors today, so this candidate has effectively zero slack
  left in those two rows before it needs its own budget re-cut (DR-0015's
  "way out #2" — see below).
- **Required external-cap / ESR spec**: none, if it works — the goal is to
  hold the full ratified 0.33–4.7 µF window rather than narrow it. Unverified.

### 3. The 0 mA / no-external-load corner — a spec decision, not a silicon one, on current evidence

The map above shows 0/756 at 0 mA across every cap and every ESR — worse, in
absolute terms, than the 4/540 (0.7 %) DR-0007 measured against the
pre-DR-0008-compliant record it was written against, but the same conclusion:
**no cap value in the ratified window reaches 0 mA**, because the mechanism is
not a cap-sizing problem. DR-0007 already derives why, and this record does
not repeat the derivation — it cites the two independent, ratified-row-blocking
costs DR-0007 measured for the two ways to close it in silicon:

| Lever | What it would cost | Ratified row it blocks | Measured in |
|---|---|---|---|
| Grow `Cc` to ≈ 0.70 nF (the area+PSRR-blind fix) | ≈ 0.35 mm² of MIM | **3.5×** over the < 0.1 mm² core-area row | DR-0007, `sim/devchar/CONCLUSIONS.md` §3 density |
| Grow `Cc` to ≈ 0.70 nF (the PSRR side of the same fix) | 1 kHz amplifier gain 53.5 dB → ≈ 38.5 dB (saturates, does not grow further) | **15 dB** short of the ratified PSRR floor, at a component whose penalty cannot be traded back by area | DR-0007, extrapolated from two recorded `Cc` points (4.80 pF → 50.0 dB measured, 7.4 pF → 46.3 dB measured) |
| A continuous 100 µA internal preload | 100 µA continuous, at exactly the condition (no load) where Iq matters most | **3.3×** over the ratified < 30 µA row | DR-0007 |

**DR-0007's hold condition is now satisfied by DR-0015's evidence, and this
record treats that as directly relevant to #51.** DR-0007 was held, not
rejected, specifically because its supporting loop-stability run predated
DR-0008's RHP-pole precondition; it named exactly two things needed before it
could be "ratified, amended, or superseded": an `amp-selfosc` pass against the
current netlist, and a loop-stability run that satisfies DR-0008 and may
legitimately be cited. DR-0015 supplies both —
`sim/amp-selfosc/records/20260807-105211-64249c6.md` (PASS 45/45) and
`sim/loop-stability/records/20260807-103351-64249c6.md` (0/4536 resurgence,
DR-0008 satisfied) — and the 0/756 count above is that admissible evidence
reconfirming, on a stronger basis, the same conclusion DR-0007 reached on
weaker evidence: 0 mA is not reachable by any lever this record's Candidate 2
or DR-0015's own adaptation touches, for the same three independently-blocking
reasons.

**What is not measured**: a *switched* (event-detected, non-continuous)
micro-preload — engage a bleed path only when the load current is sensed as
at or near zero, rather than continuously. DR-0007's 3.3× figure is for a
*continuous* 100 µA preload; a low-duty switched version could in principle
land under the Iq budget on average. No testbench, no comparator design, and
no transient-glitch check exists for this in `sim/` today. It would need at
minimum: a load-sense comparator (its own Iq and offset budget), verification
that the switch event does not reopen DR-0008's RHP-pole precondition (a
frequency-domain check, `sim/amp-openloop/`-style), and a transient bench
closer to `sim/enable-shutdown/`'s style than `sim/loop-stability/`'s to
confirm no output glitch at the transition. This record does not build or
estimate it further than naming what evidence it would need — see Candidate 4.

- **Coverage**: the spec-decision path (ratify DR-0007's proposed exclusion)
  closes the 0 mA corner from the verified-envelope side, at zero silicon
  cost, immediately, on evidence that now satisfies DR-0007's own admissibility
  condition. The switched-preload path is unquantified.
- **Area / Iq / PSRR cost**: 0 for the spec-decision path. Unmeasured for the
  switched-preload path (bounded above by the continuous case's 3.3×, bounded
  below by nothing recorded).
- **Required external-cap / ESR spec**: none from the compensation side; the
  cost is a stated minimum-load / preload condition on the datasheet, exactly
  as DR-0007's "Decision" section already proposes.

### 4. Mode-switching / dual-loop — assessed against the other three, not built

A discrete mode switch (sense the operating regime, select a compensation
network) is the textbook alternative to continuous adaptation for a wide
operating range. Assessed honestly against what DR-0015's continuous approach
and Candidates 1–3 already cover:

- **On the cap axis, mode-switching has nothing to sense.** The obstruction in
  DR-0015's closed form is the *external* output capacitor's value, and this
  topology has no pin or scheme to sense it — a consumer's board choice, not a
  state the die can read. Candidate 1 (narrow the spec) and Candidate 2 (raise
  `f_hi`) both act on this axis without needing a sense signal; mode-switching
  would need one it does not have, so it offers **no** advantage here over
  either.
- **On the load axis, DR-0015 already is the continuous version of this idea**,
  and it dominates a discrete load-mode switch on the evidence already
  recorded: DR-0013 built a discrete/level-shifted variant of the same shunt
  device (`Mrz`, gated through `Rsg`/`Csg` rather than tied straight to the
  pass gate) and measured it **failing** `peak_excess_db` at 72 of 81 corners
  (+19.05 dB against a 1 dB bar) — the isolation that a discrete sense/switch
  scheme would need is exactly the change DR-0015 shows removes the adaptive
  `Cf` the local loop depends on (`sim/amp-openloop/` A/B in DR-0015's §"What
  was built" item 3: isolating the same gate through 2 MΩ takes 37–38/48 PASS
  with 0 resurging points to 23–29/48 with 6–19 resurging). A mode switch
  additionally carries a transition/hysteresis-stability question a continuous
  device does not: DR-0015's `Mrza` has "no port change, no new bias branch"
  and no discrete transition to verify at all, which a switched network would
  need its own bench for.
- **The one place mode-switching is not already dominated is the 0 mA
  corner** — because that is the one place DR-0015's continuous mechanism is
  structurally unable to act (`V(N1) − V(BG)` is 0.415 V at 0 mA, 0.607 V at
  0.1 mA, both under `|Vtp|` ≈ 0.72 V — the replica is off by construction,
  DR-0015 §"What is still not reached"). This is exactly Candidate 3's
  unquantified switched-preload idea, restated as a mode switch. It does not
  add a fifth option; it names the one place a discrete scheme could win, and
  that place already has an open, unquantified need for evidence rather than a
  built comparator or a bench.

**Conclusion for this candidate: reject as a general-purpose direction.** It
is dominated by Candidate 1 or 2 on the cap axis (no sense signal available)
and by DR-0015's continuous mechanism on the load axis (measured worse, and
carries transition risk the continuous version does not). Its only
non-dominated niche collapses into Candidate 3's switched-preload idea for the
0 mA corner specifically, which remains unbuilt and unmeasured either way.

## Recommendation

**Take the two zero-cost moves now, and treat the one bounded-cost move as its
own follow-up issue rather than folding it into this record.**

1. **Ratify a narrowed cap spec at `C_eff = 1 µF` nominal (X5R/X7R), ESR
   floor ≥ 200 mΩ, verified `1 mA ≤ I_load ≤ 50 mA`.** This is Candidate 1,
   costs nothing beyond the spec's own width, and is backed by a 100 %
   (630/630) result already sitting in the committed matrix CSV. It should be
   written as a DR-0001-superseding record of its own once ratified, in the
   same form DR-0007's "Decision" section uses for its proposed `Stability`
   row.
2. **Ratify DR-0007's 0 mA exclusion, now on DR-0008-satisfying evidence.**
   Candidate 3's spec-decision path; DR-0007's hold condition is met by
   DR-0015's evidence as argued above, and this record's own re-derivation
   (0/756 at 0 mA, all caps, all ESRs) reconfirms DR-0007's conclusion rather
   than weakening it. No new record is required to ratify DR-0007 as written —
   only an update of its "Status" line against the now-admissible evidence.
3. **If the product genuinely needs the full 0.33–4.7 µF window at heavy
   load (i.e. Candidate 1's narrowing is not acceptable), open Candidate 2 —
   the `f_hi` buffer-bandwidth boost — as its own issue with its own
   `sim/amp-openloop/`, `sim/psrr-dc/`, `sim/amp-selfosc/` and
   `sim/loop-stability/` records**, bounded at ≤ 7.40 µA of Iq headroom and an
   unknown-but-likely-small area cost, with the explicit warning that the two
   rows it would ride closest to (`gain_1k_db`, `psrr_ldo_1k_db`) are
   currently at ≈ 0.25 dB of margin and have no slack left to absorb a
   miscalculation — DR-0015's "way out #2" (re-cutting the PSRR budget against
   the closed-loop measurement rather than the conservative amplifier-gain
   proxy) is the cheapest way to buy that slack back before spending it.
4. **Do not pursue mode-switching as a general direction.** It is dominated on
   both axes by cheaper or already-measured alternatives (Candidates 1/2 on
   the cap axis, DR-0015's continuous mechanism on the load axis). If the
   0 mA corner is later judged to need an in-silicon fix rather than a
   datasheet exclusion, that is a new, separately-scoped research effort (a
   load-sense comparator plus its own frequency- and time-domain benches) —
   not a widening of this record's or DR-0015's mechanism, and not free: it is
   the one place in this trade study with no committed evidence at all.

**Versatility across the full ratified cap window costs a real, currently
unbounded amount of design and verification effort (Candidate 2); precision —
stating the requirement the design already meets — costs nothing and is
available today (Candidates 1 and 3).** Per the issue's own framing, this
record recommends taking the free precision now and scoping the versatility
spend as separate, evidence-gated follow-up work, rather than holding #51 open
for a design change this record cannot yet cost.

## Alternatives considered

- **Re-cut the PSRR budget line first, before any other move.** DR-0009 and
  DR-0015 both flag this as the cheapest lever with no silicon cost. Two
  measured facts support it: DR-0009's "Alternatives considered" reports
  `sim/psrr-dc/records/20260802-095514-c828e73.md` measuring
  `psrr_ldo_1k_db` = 50.08 dB worst corner against the ratified 50 dB floor —
  0.08 dB the design's own gain-proxy budget line does not credit — and
  DR-0015's "The ways out" item 2 reports the closed-loop
  `psrr_ldo_1k_tracking_db` at 59–71 dB against `design/error_amp.md` §4's
  conservative budgeting rule, which forces the proxy `|1 − G| → 1` rather
  than crediting the loop's own feedback; DR-0015's own "What is still not
  reached" section quantifies the recoverable slack directly — the design's
  measured `gm(MIN)/Cc` (3.07e6) already exceeds the ratified PSRR-row floor
  `K` (1.99e6) by 1.55×, worth `sqrt(1.55)` ≈ 1.24× of headroom on the `f_hi`
  requirement if that budget line is re-cut to its last dB. Not ranked above
  Candidates 1/3 in this record because it does not, by itself, close any
  cell of the map above — it only creates headroom for Candidate 2 to spend.
  It is folded into recommendation #3 as a prerequisite, not treated as a
  fifth independent candidate.
- **Do nothing and leave #51 open pending a full-window silicon fix.**
  Rejected: DR-0015 already states the residual gap in closed form and this
  record's own recomputation confirms it; sitting on that evidence without
  offering the operator a cheaper, immediately available point (Candidate 1)
  wastes the two zero-cost moves this record found.
- **Treat the four candidates as a menu the operator picks one from.**
  Rejected in favor of the layered recommendation above — Candidates 1 and 3
  are not mutually exclusive with Candidate 2, and taking them first is
  strictly better than deferring them until a Candidate 2 record lands, since
  they cost nothing and Candidate 2's timeline is unknown.

## Consequences

1. **No `design/` file changes and no ratified bar is relaxed.** This record
   only reads the already-committed matrix CSV differently and reads DR-0007
   against evidence that has since become admissible; every number above
   traces to a record already on `main` or to `design/error_amp.md`'s own
   area table.
2. **If recommendation #1 is ratified**, DR-0001's `Stability` row narrows
   from a 14.2× cap window to a single nominal value plus a new ESR floor,
   and a superseding record for that row is required — this record proposes
   the language but does not write it, per DR-0001's own anticipated remedy
   ("the correct response is a superseding record that tightens the
   component spec").
3. **If recommendation #2 is ratified**, DR-0007's "Status" line updates to
   reflect that its hold condition is met; no new evidence is required to
   take that step, only the operator's sign-off, since DR-0007's own
   "Decision" and "Why 0 mA is not reachable" sections already state the
   full case.
4. **Recommendation #3 does not land anything by itself.** It only scopes a
   follow-up issue with named acceptance criteria (the four benches listed
   above, plus the PSRR-budget prerequisite) so that whoever picks it up is
   not re-deriving DR-0015's own "ways out" list from scratch.
5. **#51 is not discharged by this record.** Issue #51's acceptance criteria
   require every residual failing point to either pass or be backed by a
   decision record explaining why it is out of scope. This record supplies
   the argument for two of the three residual clusters (0 mA via
   recommendation #2, and the 1–50 mA/0.33 µF cluster via a *scoped-but-not-
   landed* follow-up under recommendation #3) and a spec-narrowing path
   (recommendation #1) that, if taken instead of #3, removes the third
   cluster from the claimed envelope entirely rather than closing it in
   silicon. Which of #1 or #3 the operator prefers is exactly the ratification
   decision this record exists to inform.
