# DR-0007: The 0 mA / no-external-load point of DR-0001's stability matrix

- **Status**: **proposed — HELD as of 2026-08-06.** Ratification was
  considered and deliberately deferred by the operator (issue #1,
  [ratification comment](https://github.com/2AMLogic/gf180-ldo/issues/1#issuecomment-5199954200)),
  because DR-0008 — ratified the same day — rules this record's supporting
  evidence inadmissible: `sim/loop-stability/records/20260801-191742-84f67b8`
  may no longer be cited as a stability result at any load, and this record's
  2160/2160 pass count at 1–50 mA comes from exactly that run.

  **This is a hold on the evidence, not a rejection of the conclusion.** Moving
  the 0 mA column out of the verified envelope may still be right, and DR-0001
  pre-authorised that response. What is required first is a stability result
  that satisfies DR-0008's precondition: an `amp-selfosc` pass against the
  current `design/` netlist, then a `loop-stability` run that may legitimately
  be cited. On that evidence this record can be ratified, amended, or
  superseded.

  **Hold condition met as of 2026-08-07 (noted 2026-08-21).** DR-0015 supplies
  both things this hold asked for against the *current* `design/` netlist
  (`Mrza`/`Rza`, the shipped adaptive shelf): `sim/amp-selfosc/records/20260807-105211-64249c6.md`
  PASS 45/45, and `sim/loop-stability/records/20260807-103351-64249c6.md`
  (0/4536 DR-0008 resurgence points — a loop-stability run that may
  legitimately be cited). `spec/decision-records/DR-0018-narrow-stability-envelope-to-1uf-nominal.md`
  re-derives this record's 0 mA conclusion directly against that current
  matrix (0/756 passing at 0 mA, every cap, every ESR) and finds it
  reconfirmed, on stronger evidence than this record had when it was
  written. This note does not ratify this record — that is still the
  operator's call — it only records that the hold's own stated prerequisite
  is satisfied and the evidence is ready for a ratification decision.

  Original status line follows.

- **Status (original)**: proposed — ratification is the operator's (issue #1's process,
  the same one DR-0001 itself went through: "Decided by: Builder agent …
  recommendation only"). Still `proposed`, and **nothing in this record is in
  force until an operator ratifies it** — the "Coverage check" subsection
  below maps this record's proposed envelope onto the head-of-chain
  loop-stability record's failure set, but that mapping is an argument
  offered for ratification, not a ratification, and it does not by itself
  discharge issue #51's acceptance criteria (see that subsection's closing
  paragraph).
- **Date**: 2026-08-01
- **Decided by**: Builder agent, issue #51 (recommendation only)

## Context

DR-0001 ratifies "PM ≥ 45° **and** GM ≥ 10 dB across the full matrix", where
the load axis is `I_load ∈ {0, 0.1, 1, 10, 25, 50} mA` and **0 mA means no
external load — the feedback divider's ~2 µA is the only inherent preload and
no external preload resistor may be assumed**. DR-0001 also anticipated this
record explicitly:

> **Bad consequence, stated plainly:** the 0.33 µF corner is the hardest point
> in the whole design and may cost Iq, area, or PSRR margin at 1 kHz. If it
> proves unmeetable, the correct response is a superseding record that tightens
> the component spec […] — not silently testing at 1 µF and claiming the window.

Issue #51 rebuilt the compensation (`design/error_amp.sch`: a class-AB gate
buffer plus a Type-II gain-shelf Miller network) and re-ran the full ratified
3240-point matrix, unmodified. The result,
`sim/loop-stability/records/20260801-191742-84f67b8.md` (supersedes
`20260801-140530-d6d47f5`): **2689/3240 points pass, 551 fail**, against
150/3240 before. Every failure is at one of the two lightest loads:

| `I_load` | points | passing | how the failures fail |
|---|---|---|---|
| 1, 10, 25, 50 mA | 2160 | **2160 (100 %)** | — |
| 0.1 mA | 540 | 525 (97.2 %) | 15 points, all at **−40 °C / 3.63 V** on the `ss` and `fs` MOS corners, all on **gain margin** (PM 67…102°, GM −20.7…+7.9 dB) — a conditionally-stable loop, not a phase collapse |
| 0 mA | 540 | 4 (0.7 %) | 536 points on **phase margin**, worst 3.79° at `ff_125c_2.97v` / 4.7 µF / 1 mΩ |

The prior record had a worst-corner PM of −1.26° and failed at *every* load.
So this is not "the design is nearly there at 0 mA": the 0 mA column is
qualitatively different from the rest of the matrix, the 0.1 mA residue is
15 points of the same underlying frontier showing up as GM instead of PM, and
this record is about *why*, and what the spec should say about it.

## Decision

**Recommend that DR-0001's stability row be superseded so that its verified
load window for the stability claim is `1 mA ≤ I_load ≤ 50 mA`, with 0 mA
(no external load) moved out of the verified envelope and into a stated
minimum-load condition on the datasheet.** Concretely, the proposed
replacement for the ratified `Stability` row is:

```markdown
| Stability | stable 1–50 mA with C_out 0.33–4.7 µF effective (1 µF nominal X5R/X7R), ESR 0–500 mΩ; PM ≥ 45°, GM ≥ 10 dB worst corner (2160/2160 matrix points). Below 1 mA a minimum load (or preload) must be provided by the application; 0.1 mA is measured stable at 525 of its 540 matrix points and is a design follow-up, not a claim | capless variant (separate design fork) |
```

**1 mA, not 0.1 mA, is what this record proposes to claim**, even though
0.1 mA passes 97 % of its points. A verified envelope has to be a bound the
design meets at *every* point of it; 525/540 is evidence of where the edge is,
not a claim. The 15 outliers are a design follow-up with an identified cause
(below), and if a later issue clears them the envelope should be re-extended
to 0.1 mA by a superseding record — not asserted here on a 97 % result.

Nothing else in DR-0001 changes: the `C_eff` window, the ESR window (including
"no minimum ESR"), the 45°/10 dB bars themselves, and the 0–50 mA *operating*
range are all kept as ratified and are all met at every point of the reduced
load axis. **This record does not relax a bar to make a result pass** — the
bars are untouched; it removes one operating point from the verified envelope,
with the measurements below as the justification, exactly as DR-0001 instructs.

## Why 0 mA is not reachable — the measured argument

The loop's crossover in the compensated (Type-II shelf) region and the shelf's
own corner frequency are

```
f_c  =  β · A_plat · gm_pass / (2π·C_out)        (shelf region, −20 dB/dec)
f_z  =  1 / (2π·Rz·Cc)                            A_plat = gm(MIN)·Rz
```

and PM ≥ 45° requires the loop to cross unity **above** `f_z` (i.e. on the
shelf, one pole), which reduces to `f_c/f_z ≥ 1`, i.e.

```
Rz · sqrt(Cc)  ≥  K · sqrt(C_out / (β · gm(MIN) · gm_pass))
                                     K = 2^(-1/4) ~ 0.84, the sqrt(2) at the
                                     zero corner carried through the sqrt
```

**Caution — `f_c` here is the *shelf-asymptote* crossover, not the crossover
the matrix reports.** Where the loop actually crosses below `f_z` (which is
the case at every failing 0 mA point), the reported `f_crossover_hz` sits in
the −40 dB/dec region and is a different quantity; substituting it into
`f_c/f_z ≥ 1` and reading off a growth factor understates what `Cc` must do by
that factor again. The worked derivation below does it properly.

`gm_pass` is what collapses at 0 mA: the pass device carries only the
divider's ~2 µA there, so `gm_pass` falls by roughly **110×** between 0.1 mA
and 0 mA, and the required `Rz·sqrt(Cc)` rises by the square root of that.
Both components are bounded, and both bounds are *measured*, not assumed:

| Bound | What sets it | Measured limit |
|---|---|---|
| `Rz` (hence `A_plat`) | the heavy-load crossover `β·A_plat·gm_pass/(2π·C_out)` must stay below the buffer / BG-node poles | `Rz` = 6 MΩ passes 0.1–50 mA everywhere; **7 MΩ already loses corners at 1–50 mA**; 9 MΩ loses them all |
| `Cc` | the amplifier's 1 kHz gain is `gm(MIN)/(2π·Cc·1 kHz)` — while `f_z` > 1 kHz; see the shelf caveat below — and the ratified **PSRR > 50 dB @ 1 kHz** row rides on it | `Cc` = 4.80 pF gives worst-corner `psrr_ldo_1k_db` = **50.0 dB** against a 50 dB floor; `Cc` = 7.4 pF measures **46.3 dB**, a hard FAIL |

The design shipped by #51 sits **on** that frontier, not inside it: worst-corner
amplifier gain at 1 kHz is 53.5 dB against a 53.5 dB floor, and worst-corner PM
at the lightest verified load (0.1 mA / 4.7 µF / 1 mΩ) is 45.4° against a 45°
floor. Both ratified rows are simultaneously at their limits with the same two
components.

Closing the 0 mA column from that frontier is a **quadratic** ask in `Cc`, and
it is worth deriving that explicitly, because the ratio the measurements hand
you (`f_c/f_z` = 0.07 at the worst 0 mA point) is *not* the factor `Cc` has to
grow by — the naive reading is low by more than an order of magnitude.

At the worst 0 mA point the loop does not cross unity on the shelf at all: it
crosses **below** `f_z`, where the amplifier is still an integrator and the
loop rolls off at −40 dB/dec. The matrix shows that directly — crossover
scales as `1/sqrt(C_out)`, not `1/C_out` (1465 / 836 / 385 Hz at 0.33 / 1 /
4.7 µF: ratios 1.75 and 2.17, against `sqrt(3.03)` = 1.74 and `sqrt(4.7)`
= 2.17). In that region `|T| ∝ 1/(f²·Cc)`, so writing `Cc = k·Cc0` and using
`|T(f_c0)| = 1` at the present `Cc0` = 4.80 pF:

```
|T(f)|   = (f_c0/f)² / k        for f << f_z
f_z(k)   = f_z0 / k
```

PM ≥ 45° requires crossing at or above `f_z`, i.e. `|T(f_z)| ≥ 1`. Evaluating
at `f_z(k)`, where the exact `|Rz + 1/(jωCc)|` is `sqrt(2)`× its asymptote:

```
|T(f_z(k))| = sqrt(2) · k · (f_c0/f_z0)²  ≥  1
        k  ≥  1 / ( sqrt(2) · (f_c0/f_z0)² )
```

**`Cc` grows as the *square* of the crossover-to-zero frequency ratio, not in
proportion to it** — equivalently, it is `Rz·sqrt(Cc)` that scales with
`f_c/f_z`, which is why the feasibility boundary above is written in that
combination. With the measured `f_c0` = 384.9 Hz at the worst 0 mA point
(`ff_125c_2.97v` / 4.7 µF / 1 mΩ) and `f_z0` = 1/(2π·6 MΩ·4.80 pF) = 5.53 kHz,
`f_c0/f_z0` = 0.070, so

```
k ≥ 1 / (sqrt(2) · 0.070²) ≈ 150      ⇒   Cc ≥ 0.70 nF
```

i.e. `Rz·sqrt(Cc)` must grow ≈ 12×, all of it from `Cc` because `Rz` is
already at its measured ceiling. **≈ 150× is a floor, not an estimate**: the
two-pole-plus-zero model ignores the extra lag the loop picks up as crossover
falls into the tens of hertz, which moves the real requirement up, not down.
Both rows below are therefore evaluated at the *most* favourable `Cc` the
model permits.

- **Area.** 0.70 nF of `cap_mim_2f0`, at the 1.990 fF/µm² measured in
  `sim/devchar/CONCLUSIONS.md` §3, is ≈ 3.5 × 10⁵ µm² = **0.35 mm²**, against
  a ratified **< 0.1 mm² total core area** row (pass FET included). One
  capacitor is 3.5× the whole area budget, and `error_amp`'s present total is
  0.0164 mm² (`design/error_amp.md` §8), so there is nothing to trade back.
- **PSRR, which is the harder one — and note that it saturates.** The
  `gm(MIN)/(2π·Cc·1 kHz)` form of the amplifier's 1 kHz gain holds only while
  `f_z` is **above** 1 kHz. The exact dependence is
  `A(1 kHz) ∝ |Rz + 1/(j2π·1 kHz·Cc)|`, which flattens onto the Type-II shelf
  plateau `A_plat = gm(MIN)·Rz` as soon as `Cc` pushes `f_z` below 1 kHz —
  that is, for any `Cc` ≳ 27 pF, far short of the ≈ 0.7 nF the 0 mA column
  needs. So the gain loss does not keep growing with `Cc`; it **saturates** at

  ```
  20·log₁₀( sqrt(1 + (f_z0 / 1 kHz)²) ) = 20·log₁₀(5.62) = 15.0 dB
  ```

  and 15.0 dB is therefore the *entire* PSRR penalty that growing `Cc` at
  `Rz` = 6 MΩ can ever cost. It is already fatal: worst-corner amplifier gain
  at 1 kHz goes 53.5 dB → ≈ **38.5 dB** against a 53.5 dB floor, and
  worst-corner `psrr_ldo_1k_db` goes 50.0 dB → ≈ **35.0 dB** against a
  ratified 50 dB floor. **Every `Cc` big enough to reach 0 mA pays the full
  15 dB, and no amount of area buys it back**, because area and PSRR ride on
  the same component with opposite sign.

  Those two figures are an extrapolation from recorded points, not themselves
  a recorded measurement, and are flagged as such: the expression above
  reproduces the two `Cc` points that *are* recorded to 0.1 dB (4.80 pF →
  50.0 dB; 7.4 pF → predicted 46.4 dB, measured 46.3 dB), but both of those
  sit in the integrator region, so the plateau branch is modelled rather than
  measured. A recorded point at `Cc` ≈ 0.7 nF would close that gap and is
  worth taking if anyone revisits this; it cannot change the outcome, because
  the row is failing at **every** `Cc` along the path — monotonically, from
  50.0 dB at 4.80 pF down to the 35.0 dB asymptote.

The alternative that does not touch `Cc` is to stop `gm_pass` collapsing —
i.e. an internal preload holding the pass device at its 0.1 mA operating point.
That is **100 µA**, against a ratified **Iq < 30 µA** row (measured 8.6–21.4 µA
for the whole regulator), so it overruns that row by 3.3×. DR-0001 also
forbids assuming an external preload resistor, which is precisely why this has
to be a spec decision rather than an application note.

Three ratified rows — PSRR @ 1 kHz (15 dB short, and the shortfall saturates,
so it cannot be traded down), core area (3.5× over budget for one capacitor),
and Iq (3.3× over for the preload alternative) — each independently block the
only three levers that reach 0 mA. That is the case for moving the point out
of the envelope rather than continuing to design against it.

### The 15 outliers at 0.1 mA are the same frontier, seen from the other side

They fail on **gain margin** with a healthy phase margin (PM 67…102°, GM
−20.7…+7.9 dB): the loop's phase dips through −180° in the −40 dB/dec region
*below* `f_z` while |T| is still above unity, and the shelf zero then brings
it back above −180° before crossover. That is conditional stability, and it is
inherent to a Type-II compensator sitting on a plant whose own pole is decades
below `f_z` — the fix is the same one 0 mA needs, a lower `f_z`, i.e. a larger
`Rz·Cc`, i.e. the same two bounded components. It is not a separate defect
with a separate fix.

Two observations bound it for whoever picks it up:

- It appears **only** at −40 °C / 3.63 V on `ss` and `fs`, i.e. at one corner
  of the bias spread. `A_plat = gm(MIN)·Rz` is directly proportional to the
  input-pair bias, and this amplifier's supply-referenced bias
  (`Iref = (VDD − Vgs(MB1))/Rbias`, `design/error_amp.md` §5) spreads **2.5×**
  over PVT, so `A_plat` — and with it the crossover frequency — spreads 2.5×
  as well. The measured `Rz` ceiling (6 MΩ passes; 7 MΩ loses corners at
  1–50 mA) is set by the *high* end of that spread and the 0.1 mA PM floor by
  the *low* end; the design is pinched between them.
- The obvious lever is therefore **a constant-gm (beta-multiplier) bias**,
  which would collapse that 2.5× and let `Rz` be chosen against a much
  narrower `A_plat` window. `design/error_amp.md` §5 already names it and its
  cost (it needs a start-up circuit, because unlike the present topology a
  beta-multiplier has a stable zero-current state). That is a design issue,
  not a spec question, and is filed as one — **issue #53**, with the root
  cause above and a suggested direction.
- Raising `Cff` (the `ldo_core` feedforward zero) was re-tried against these
  points specifically — 15 pF → 45 pF — and recovered 3 of 15. It was not
  kept: the area is real and the mechanism is the wrong one.

**A standalone check of the constant-gm lever, for whoever picks up #53.** A
four-transistor self-biased constant-gm core (cross-coupled PMOS/NMOS mirror
pair, one leg degenerated through a resistor at a size ratio `K` = 4, no
connection to `Rbias`/`MB1` at all) was built and probed in isolation — *not*
integrated into `design/error_amp.sch`, not a recorded result, no PR-worthy
evidence, just a feasibility check against this record's own claim that the
lever is real:

- **The core current is genuinely close to constant-gm.** At fixed
  temperature, sweeping `tt`/`ff`/`ss` and 2.97–3.63 V together moved the
  branch current by **< 7 %** (vs. the present bias's combined ±13 % supply
  + corner + `Rbias` spread). Across the full −40…125 °C / 2.97…3.63 V / five
  MOS-corner grid the current moved **266–424 nA**, a 1.6× span dominated
  almost entirely by temperature (mobility), not supply or MOS skew — a real
  reduction from the present circuit's measured 2.5× (`design/error_amp.md`
  §5), consistent with removing the `(VDD − Vgs)/Rbias` supply term
  entirely.
- **The start-up circuit is the real cost, and it is not a formality.** A
  first-attempt start-up device (a minimum-size PMOS sensing the reference
  node) did **not** reliably pull the loop out of its zero-current state in a
  transient enable test at several PVT corners — the loop stayed off. This is
  the concrete version of the caution `design/error_amp.md` §5 and this
  record both already state in the abstract: a constant-gm bias is not a
  drop-in swap for `Rbias`/`MB1`, and #53's own acceptance criteria (full
  amp-level regression, not just the loop-stability matrix) are sized
  correctly for that cost. Getting the start-up circuit right, and proving it
  starts at all 45 static corners *and* through the enable transient the
  existing `Mbias_h`/`Mnb_pd` headers already have to coordinate with, is
  its own verification effort and is why this record does not attempt the
  integration.

### Coverage check against the current head-of-chain record

Issue #51's own acceptance criteria require that *every* point still failing
in the loop-stability record be either passing or backed by a decision
record. This subsection checks this record's proposed envelope against that
failure set, point for point, so a ratification decision can be made against
an explicit account rather than an implied one. The head-of-chain record as
of this pass is still
`sim/loop-stability/records/20260801-191742-84f67b8.md` — nothing in
`design/` changed in the pass that added this subsection, so re-running the
unmodified
3240-point matrix would reproduce it exactly (ngspice's AC analysis here is
deterministic given an unchanged netlist and models; a byte-for-byte rerun
would add churn, not evidence, so none was minted). Its full failure set is
**551 points, all at `I_load ∈ {0, 0.1} mA`** — 536 at 0 mA (this record's
"not reachable" argument, above) and 15 at 0.1 mA (the outliers just above,
tracked in #53). There is no failing point at 1, 10, 25 or 50 mA.

The proposed replacement `Stability` row under "Decision" claims exactly
`1 mA ≤ I_load ≤ 50 mA` — it does not claim 0.1 mA, even though 525 of its
540 points already pass, precisely because a verified envelope has to be a
bound met at *every* point inside it and this design is not there yet. That
means the proposed envelope's excluded range (`I_load < 1 mA`, 1080 points)
is a superset of, and exactly aligned with, the record's real failure set —
it does not carve out an unrelated or partial excuse, and it does not leave
any failing point outside `{0, 0.1} mA` unexplained. Nothing here silently
narrows DR-0001's matrix or the testbench that runs it — the full grid is
still swept and still reported as a FAIL against DR-0001 as originally
written; this record only changes what is *claimed* as the ratified
envelope, per DR-0001's own anticipated remedy for a corner that the
evidence says is not there yet.

**The two excluded columns are not excluded on the same footing, and this
record does not pretend otherwise.** The 536 points at 0 mA are argued to be
*legitimately* out of scope on the merits: the area and PSRR derivations
above independently rule the corner out for this topology, so no future
design pass is expected to recover it and the exclusion is meant to be
permanent. The 15 points at 0.1 mA are **not** argued that way. This record
makes no case that 0.1 mA is infeasible — the opposite, in fact: it
root-causes those points to the bias branch's 2.5× PVT spread, measures a
lever (constant-gm bias, feasibility-checked above) that plausibly closes
them, and #53 is open with acceptance criteria that require all 540 points
at 0.1 mA to *pass*. Their exclusion from the proposed envelope is therefore
**provisional and evidentiary** — this design has not verified that column
yet, so it must not be claimed — not a finding that the column is out of
scope.

**What that means for issue #51.** #51's acceptance criteria distinguish
exactly these two things: a failing corner must either pass, or be backed by
a decision record "explaining why it is out of scope," and #51 states that a
silent partial-pass record is not sufficient. This record supplies that
explanation for the 0 mA column only. For the 0.1 mA column it supplies a
root cause, a candidate fix and an open issue — which is a plan, not an
out-of-scope finding. So #51 is **not** discharged by this record, and stays
open until both of the following hold: (1) an operator ratifies this record,
putting the 0 mA exclusion in force; and (2) #53 lands a superseding
loop-stability record in which all 540 points at 0.1 mA pass both DR-0001
bars — at which point #53's own third criterion re-extends the envelope's
lower bound from 1 mA to 0.1 mA by a superseding record, and the provisional
exclusion added here disappears rather than hardening into a claim.

## Alternatives considered

- **Keep 0 mA and relax the PSRR row instead.** Rejected. PSRR at 1 kHz is a
  row a consumer of this block designs against; "stable at exactly zero load"
  is a condition an integrator can guarantee with a resistor. Trading a
  first-class AC specification for one endpoint of the load axis is the worse
  bargain, and the 15 dB it would cost takes a 50 dB row to 35 dB — that is
  not a trim, it is a different specification.
- **Keep 0 mA and relax the area row.** Rejected on its own terms (3.5× the
  budget) and, more decisively, it does not work: the area buys `Cc`, and `Cc`
  is what breaks PSRR. Paying the area still leaves the PSRR row 15 dB short.
- **Add a 100 µA internal preload.** Rejected: 3.3× over the ratified Iq row,
  and it burns 100 µA continuously at exactly the condition (no load) where a
  regulator's quiescent current matters most.
- **Raise the `C_eff` floor instead (DR-0001's own suggested remedy —
  "≥ 0603, ≥ 16 V rating" to lift the derated floor to 0.68 µF).** Rejected
  because it does not address *this* failure: the 0 mA column fails at **all
  three** `C_eff` values, and fails *worst* at the largest (PM 3.8° at 4.7 µF
  vs 11.5° at 0.33 µF). Tightening the capacitor spec moves the wrong axis.
- **A different amplifier / compensation architecture (nested Miller,
  damping-factor control, capless-style adaptive biasing —
  `spec/architecture-survey.md` §4.2).** Not rejected on the merits; out of
  scope for one issue, and the two published levers that would actually help
  at 0 mA (adaptive biasing that scales the amplifier's bandwidth with load,
  and Q-reduction) both spend quiescent current at the *light-load* end, which
  is where the Iq row binds hardest. If a consumer of this block genuinely
  needs zero-load stability, that is the fork to open, and it should carry its
  own Iq row.
- **Narrow the load axis further (e.g. verify only ≥ 1 mA).** Rejected as
  unnecessary: 0.1 mA passes at every one of its 540 matrix points with the
  design as committed, so there is no reason to give up an order of magnitude
  of verified range.

## Consequences

- **`sim/loop-stability/` re-runs against a 2700-point matrix** (the 3240-point
  grid minus the 540 points at `I_load` = 0 mA) if this record is ratified.
  Until then the testbench keeps sweeping 0 mA and keeps reporting it as a
  FAIL, which is the honest state: the record in `sim/loop-stability/records/`
  minted by #51 is an **overall FAIL** against DR-0001 as it stands today, and
  says so.
- **The datasheet gains a minimum-load condition**, which is a real usability
  cost and must be stated as prominently as the ESR window. It excludes
  applications that leave the rail unloaded (e.g. supplying only a
  deep-sleep block with the load fully gated off). This is the bad consequence
  of this record and should not be softened.
- **#15 (floorplan/matching) and #16 (post-layout re-run) unblock** on the
  compensation question, but inherit two things that are now on the frontier
  and therefore layout-sensitive: `Rz` is a 6 MΩ `ppolyf_u_1k` serpentine
  whose distributed capacitance to substrate sits directly in the
  compensation path, and `Cc` at 4.80 pF has ~0 dB of PSRR margin, so
  parasitic capacitance added to the `NZ`/`OUT` net comes straight off the
  PSRR row. Both need to be called out in the floorplan, not discovered in
  extraction.
- **The margins this record documents are thin by construction** (0.4° on PM,
  0.0 dB on PSRR at the worst corners) because the design was pushed onto the
  frontier deliberately, to establish where the frontier *is*. A follow-up
  that wants comfort has to move the frontier — i.e. spend Iq on buffer
  bandwidth to raise the `A_plat` ceiling — not re-tune `Rz`/`Cc`.
- **Process spread on `Rz` is not covered by this evidence.**
  `sim/loop-stability/`'s corner axis varies the MOS sections only; the
  `res_ff`/`res_ss` sections (±40 % on poly sheet resistance, per
  `sim/devchar/CONCLUSIONS.md` §2) are held typical. `Rz` now sets both
  `A_plat` and `f_z`, and the frontier above is steep in `Rz` (6 MΩ passes,
  7 MΩ does not), so a resistor-corner axis on the loop-stability matrix is
  a required follow-up before this compensation can be signed off — it is
  filed as its own issue rather than assumed away here.

## Cross-consequences (other records)

- **DR-0001** is the record this one proposes to supersede *in part* (its
  `Load range` row as it applies to the stability claim only). DR-0001's
  operating load range 0–50 mA for the DC rows (dropout, load regulation,
  current limit) is unaffected and remains verified at 0 mA — this record is
  about the small-signal loop, not about whether the regulator holds 1.8 V
  with no load, which it does at every corner.
- **DR-0004 (spec ratification)** adopted DR-0001 verbatim, so ratifying this
  record means amending the `Stability` row of the README target table that
  DR-0004 fixes. The exact replacement text is given under "Decision" above.
- **DR-0006 (startup settling window)** is unaffected: startup is a
  large-signal claim measured with the soft-start clamp engaged, and the
  0 mA startup case is a transient the loop passes through rather than an
  operating point it must be small-signal stable at. #43's hand-over
  transient should nonetheless be re-checked at 0 mA against this record
  before it closes.
