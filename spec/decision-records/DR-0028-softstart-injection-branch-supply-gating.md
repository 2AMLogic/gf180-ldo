# DR-0028: gate the soft-start injection transconductor's branch supply off the mirror's own reference node, bounded by a bleed

- **Status**: ratified 2026-09-19 (issue #259 / this pull request) --
  **pending**: this status line states what this record's ratifying pull
  request proposes; per the 2026-08-19 ratification-via-PR policy
  (2AMLogic/2am#357, the mechanism used for DR-0005/PR #137, DR-0006/PR #127,
  DR-0018/PR #199, DR-0023/PR #217, DR-0024/PR #228, DR-0026/PR #258 and
  DR-0027/PR #264), the operator's review and approval **of that pull
  request** is the ratification act itself. Until it merges, this line is a
  proposal, not yet true of `main`.
  **Unlike DR-0023/DR-0026/DR-0027, this record's pull request DOES change
  `design/`, and that ordering is deliberate rather than an oversight.**
  Issue #259's acceptance criteria require the mechanism's Iq recovery,
  T1-T7 and 163-point transient behaviour to be measured on the full grids
  and *recorded*, and this repo's harness will not mint a record against an
  uncommitted netlist: `sim/soft-start/testbench/run.sh` refuses an
  `LDO_NETLIST` override unless `NO_RECORD=1`, and `sim/run_corners.py`
  stamps every record with the committed export's own provenance. A
  four-corner `--no-write` spot check was the most DR-0027 could offer for
  exactly this reason, and DR-0027's own "Decision" section asks the next
  attempt to go to the full grids. The only way to satisfy that is to commit
  the two devices on the branch and run the benches against them, which is
  what the first commit of this pull request does. If the operator declines
  the topology, reverting is one commit and the evidence records stay as
  characterization of a rejected variant.
- **Date**: 2026-09-19
- **Decided by**: agent-builder (issue #259) -- **proposing**. Supersedes
  nothing; **continues** `DR-0027-softstart-injection-branch-gating-negative-
  result.md`, which proposed this same gate without a bleed, measured a
  blocking DC-convergence failure at `ss_-40c_2.97v`, and named the bleed as
  one of two untested alternatives. That record stays as filed (it is not
  wrong; it is the negative result this one builds on).

## Context

`design/ldo_softstart.sch`'s FB-injection element is a device-level
transconductor (#191) whose output mirror is cascoded (#246, DR-0023). The
cascode rectifies what the element **sources**: once `V(SSR)` passes `VREF`
the `Mgmr_ss`/`Mgmrc_ss` reference stack goes into cutoff and nothing is
delivered into `FB`. It does not rectify what the element **burns**. Both
degeneration branches carried `(VIN - |Vsg| - V(gate))/200 kohm` forever,
because rectification happens one node downstream of them.

Measured, `sim/quiescent-current/records/20260918-190801-8a59d23.md` against
`20260915-234352-077e15b.md` (the ideal-`Binj_ss` baseline, same 81-point
grid): the element's whole Iq adder is **+0.004...+7.18 uA**, worst at
`ff_125c_3.63v`, and the branches dominate it (the cascode's own share is
about +2.7 uA). In the settled state this is pure overhead -- the mirror is
off, and the -1.78...-0.50 mV settled output error is 1.7...5.9 nA through
`Rtop`.

Issue #249 established that the ratified `< 30 uA` row (DR-0004 amendment A6)
binds tighter than it was being quoted: at `ff_125c_3.63v` the **full-load**
clause reads `iq_full_ua` = 28.71 uA, i.e. **1.29 uA** of headroom, not the
1.96 uA the no-load clause (`iq_en_ua` = 28.0411 uA) alone suggests. DR-0026
names this adder as the "second budget" its proposed servo amplifier falls
back to if it cannot fit in 1.29 uA. Issue #259 asks for the adder back,
subject to three constraints it states up front: do not break DR-0023's
rectification-by-cutoff (no comparator, no timer, nothing new on `FB`); do
not disturb T1-T7; and do not key the gating to a fixed `V(SSR)` threshold,
because T4's release point is itself PVT-dependent (1.200...2.025 V).

## Decision

Add two devices to `design/ldo_softstart.sch`:

```
XMgmg_ss VING GMRM VIN VIN pfet_03v3 L=0.5u W=10u nf=1 ...
XRgmg_ss VING VIN  VSS      ppolyf_u_3k r_width=1u r_length=150u m=1
```

and move both degeneration resistors' supply-side terminal from `VIN` to the
new shared node `VING` (`Rgma_ss VING GMSA 200k`, `Rgmb_ss VING GMSB 200k`).
Nothing else in the cell changes: no port, no other device, no sizing.

**`Mgmg_ss`'s gate is `GMRM`** -- the mirror's own reference-leg diode node,
an existing internal node, not a new signal:

- *Pre-release* (`Ia > Ib`, the stack conducting) `GMRM` sits a full
  `|Vgs(Mgmr_ss)|` below `VIN`, deepest at the start of the ramp where the
  branch currents are largest. `Mgmg_ss` sees that as its `Vsg`, is in deep
  triode at these single-digit-microamp currents, and passes `VIN` through
  with a drop of tens of millivolts. That drop is **common-mode** on both
  branches, and the element's output is their difference, so it perturbs the
  branches' `Vsg` mismatch (second order), not the `(VREF - V(SSR))/R` law.
- *Post-release* (`Ia < Ib`) the stack goes into cutoff -- **DR-0023's own
  ratified rectification event, unchanged and not reimplemented** -- its
  reference current collapses, `GMRM` rises toward `VIN`, and `Mgmg_ss`'s
  `Vsg` collapses with it. The branches lose their low-impedance supply as a
  *side effect* of the same "the argument went through zero" event, so there
  is no new threshold to inherit T4's spread, no comparator, no timer, and
  nothing added to `FB`.

**`Rgmg_ss` is what makes it safe, and it is not optional.** The loop just
described is regenerative: starving the branches lowers `Ia`, which lowers
the stack's reference current, which raises `GMRM`, which starves the
branches harder. DR-0027 prototyped exactly this gate *without* a bleed and
measured the consequence -- at `ss_-40c_2.97v` (slow process, cold, minimum
supply, where the branch currents are already smallest) ngspice's dynamic-
gmin, true-gmin and source-stepping continuations all failed and the
pseudo-transient fallback landed on a non-physical `VOUT` = -0.075 V. A
450 kohm bleed permanently across `Mgmg_ss` bounds the loop by construction:
however hard `Mgmg_ss` is off, the branches are still fed through 450 kohm,
so `GMIA`/`GMRM`/`GMSUM` can never become undetermined. That corner, and all
80 others, converge cleanly here.

The price of the bleed is that the recovery is **partial by design**:
post-release the branches see 450 kohm in series with their own 200 kohm
degeneration, about a 2.8x throttle rather than a switch-off. That is why
the measured recovery below is about 5 uA of the 7.18 uA adder at the binding
corner and not all of it.

## Evidence

Every number below is from this pull request's own records, minted on this
branch against the committed export (`python3 design/netlist.py --check`
clean at run time, no tracked-file modification in the tree; the records'
"dirty working tree" provenance note reflects *untracked evidence output from
a concurrently running bench*, not a modified DUT -- the same annotation the
baseline record `20260918-190801-8a59d23.md` carries).

### 1. Quiescent current, 81-point grid (`sim/quiescent-current`)

`sim/quiescent-current/records/20260919-080719-de8b468.md` (this build)
against `20260918-190801-8a59d23.md` (the ungated cascoded element) and
`20260915-234352-077e15b.md` (the ideal `Binj_ss` element that paid no
branch current at all). Same 81-point full-factorial grid, same deck, same
host, same ngspice-46, same pinned PDK. **81/81 PASS.**

| corner | `iq_en_ua` ungated -> gated | `iq_full_ua` ungated -> gated | `vout_full_v` ungated -> gated |
|---|---|---|---|
| `ff_125c_3.63v` (binding) | 28.0411 -> **22.9725** (-5.069) | 28.7100 -> **23.7275** (-4.983) | 1.79357 -> 1.78833 (-5.24 mV) |
| `res_ff_125c_3.63v` | 25.788 -> **22.1746** (-3.613) | 25.6661 -> **22.0528** (-3.613) | 1.79889 -> 1.7988 |
| `sf_125c_3.63v` | 23.3693 -> **18.3544** (-5.015) | 23.2712 -> **18.2571** (-5.014) | 1.79721 -> 1.79474 |
| `ff_125c_3.30v` | 23.7709 -> **20.2214** (-3.549) | 24.1733 -> **20.6307** (-3.543) | 1.79839 -> 1.79767 |
| `tt_27c_3.30v` (nominal) | 15.3622 -> **14.0056** (-1.357) | 15.2568 -> **13.9002** (-1.357) | 1.79934 -> 1.79934 |
| `ss_-40c_2.97v` (DR-0027's failure) | 8.8988 -> **8.89883** (+0.00003) | 8.80826 -> **8.80829** | 1.79948 -> 1.79948 |

- **Iq falls at 80 of 81 points and rises at none.** The one non-negative
  delta is `ss_-40c_2.97v` at **+0.00003 uA** (30 pA, the printed
  resolution). Per-point `iq_en` delta: **-5.0686 ... +0.00003 uA**, mean
  **-1.68 uA**; `iq_full`: **-5.0141 ... +0.00003 uA**.
- **The adder this issue exists to recover.** Against the ideal-`Binj_ss`
  baseline over the 80 grid points that baseline itself solves physically
  (its own `ss_-40c_2.97v` row is a recorded FAIL with `vout_full` =
  -0.048 V -- see "the same corner keeps being the hard one" below), the
  element's Iq adder goes from **+0.0001...+7.1766 uA** to
  **+0.0001...+2.1080 uA**. At the binding corner that is **70.6 % of the
  adder recovered**.
- **Headroom against the ratified `< 30 uA` row**, at its binding
  `ff_125c_3.63v` corner: no-load clause **1.96 -> 7.03 uA**, full-load
  clause (the binding one, #249) **1.29 -> 6.27 uA**.
- **The price is settled accuracy, and it is small.** Worst-corner settled
  output moves 1.79357 -> 1.78833 V at `ff_125c_3.63v`: error **-6.43 mV ->
  -11.67 mV**, i.e. 32 % of the +-36 mV ratified allocation, up from 18 %.
  At the nominal corner it is bit-identical to five figures. The mechanism
  is T1/T4 at the hot, high-supply corners (evidence section 2).
- **The same corner keeps being the hard one, and that is informative.**
  `ss_-40c_2.97v` is where DR-0027's un-bled prototype had no physical DC
  solution -- and it is also the single row the *ideal-source* baseline
  record `20260915-234352-077e15b.md` itself failed to solve physically,
  months before any of this. That corner's difficulty is a property of this
  deck at slow/cold/minimum-supply, not something the gate introduced; what
  the gate must not do is make it worse, and with `Rgmg_ss` in place it does
  not -- the corner solves cleanly and its Iq is unchanged to 30 pA.

### 2. Hand-over transfer T1-T5, 63 corners (`sim/soft-start`)

`sim/soft-start/records/20260919-073737-de8b468.md` §2, against
`20260918-190207-8a59d23.md`'s own 63-corner run.

| # | target | gated (this) | ungated (prior) |
|---|---|---|---|
| **T1** | `I_inj` <= 50 nA above VREF | +16.8...+1473.8 nA, **12/63** pass | +35.3...+1433.0 nA, 1/63 |
| **T2** | `I_inj(0)` = 6.00 +- 0.10 uA | +4.970...+5.792 uA, 0/63 | +4.985...+5.807 uA, 0/63 |
| **T3** | gm = -5.00 uA/V +- 5 % | -4.622...-3.455 uA/V, 0/63 | -4.530...-3.522 uA/V, 0/63 |
| **T4** | release at `V(SSR)` = 1.200 V | 1.200...2.100 V, **12/63** pass | 1.200...2.025 V, 1/63 |
| **T5** | loop in regulation at every ramp state | **63/63 pass** | 63/63 pass |

- **T5, the target DR-0023 was ratified to fix, is untouched at 63/63.**
- **T1 improves at 54/63 corners** and its pass count goes 1 -> 12. **T4
  releases earlier-or-equal at 40/63** and 25-100 mV later at the other 23,
  all of them 125 C or 3.63 V points; its pass count also goes 1 -> 12. The
  worst release moves 2.025 -> 2.100 V and the worst residual 1433.0 ->
  1473.8 nA (+2.9 %), both at `ff_125c_3.63v`.
- **T2 and T3 do not move**: `I_inj(0)` shifts by at most 0.015 uA (0.3 %).
  That is the predicted magnitude -- `Mgmg_ss`'s triode drop is common-mode
  on both branches and the element's output is their difference. **The
  gating neither fixes nor worsens the R4 lever**, which stays the open
  question `design/softstart_injection_compensation.md` §3 (R4) names.
- Settled output error over the grid: **-0.50...-2.47 mV** (was
  -0.50...-1.78 mV), i.e. 6.9 % of the +-36 mV allocation.

### 3. T6 and T7

Re-measured, not carried over, at `tt_27c_3.30v` / `device` / 1 uF / 100 mOhm
via `sim/soft-start-loop-gain/testbench/sweep.py --no-write`, the same
driver, corner and `acopen-fb-inj` attribution (`XMgmc_ss`'s drain
AC-opened from `FB`) the prior record's §5 used.

| case | PM | GM | landed `VOUT` | `I_inj` |
|---|---|---|---|---|
| as committed | 55.82 deg | 16.77 dB | 1.71152 V | +0.2927 uA |
| `acopen-fb-inj` | 55.82 deg | 16.77 dB | 1.71152 V | +0.2927 uA |

- **T6 PASS**: dPM = 0.00 deg, dGM = 0.00 dB; worst movement anywhere in
  0.01 Hz - 1 GHz is 0.0016 dB / 0.0030 deg, below the 0.02 dB numerical
  floor (the prior record measured 0.0015 dB / 0.0030 deg -- the same answer
  to the resolution of the measurement). Bar: 2 deg / 1 dB.
- **T7 PASS**: the same run's `FB`-capacitance ladder gives **10 pF** at the
  `sink` state and **3 pF** at the `ramp` (`ssr=0.05`) state before either
  margin moves by the #182/#185 cross-invocation class -- **identical** to
  the prior record's ladder. Both new devices are on `VIN`/`VING`; nothing
  is added to `FB`, so the element still hangs the same two PMOS drain
  junctions (tens of fF) on it against a 1 pF bar.
- Absolute margins at all nine measured ramp states are within 0.02 deg /
  0.01 dB of the prior record's.

### 4. The 163-point transient matrix (`sim/soft-start`)

163/163 points converged with every named measurement present. Clause pass
counts against DR-0024's proposed bounds, this build vs the prior record:

| clause | gated | ungated |
|---|---|---|
| steady ramp <= 5 V/ms | 163/163 | 163/163 |
| settling <= 1.8 ms | 163/163 | 163/163 |
| settled accuracy in [1.764, 1.836] V | 161/163 | 161/163 |
| overshoot <= +2 % | 159/163 | 159/163 |
| inrush <= 5 mA at 1 uF | 0/83 | 0/83 |
| clearance >= 10 mA below 62.0 mA at 1 uF | **1/83** | 2/83 |
| peak dV_out/dt <= 5 V/ms | 0/163 | 0/163 |
| monotonic (dV_out/dt >= -5 V/ms) | **29/163** | 33/163 |
| ramp finishes above VREF / reset by disable | 163/163 | 163/163 |

**Two clauses lose points and this record names them rather than rounding
them off.** Clearance loses one of 83 (`ff_125c_2.97v_1u_0.1_1e9`, peak
supply 46.098 -> 55.595 mA, crossing the 52.0 mA bar); monotonicity loses a
net four of 163 (six points cross the -5 V/ms bar, two cross back), and the
worst excursion deepens from -6956.86 to -9427.43 V/ms. Both clauses were
already failing at 81/83 and 130/163 respectively. Every point that changed
membership is a `1u_0.1` point in the hold-release acquisition transient the
prior record's §3 isolates and attributes to T2's shortfall -- which this
change does not move (evidence section 2). **The honest statement is that the
movement is inside that failing mechanism's own variation, not that it is
zero**; the per-point list is in the record's §1 so the reading can be
checked.

## What this record does NOT claim

- **Not that the adder is eliminated.** 70.6 % of it at the binding corner;
  +0.0001...+2.1080 uA remains over the ideal-source baseline.
- **Not that T1-T4 are met.** They are not, before or after. T2/T3 are
  unchanged in class and remain `design/softstart_injection_
  compensation.md` §3 (R4)'s problem.
- **Not that the transient matrix is untouched.** Two already-failing
  clauses lose a point and a net four points respectively (evidence
  section 4).
- **Not that 450 kohm is optimal.** It is the first value tried and it
  converges everywhere measured. See "Alternatives considered".
- **Not a layout claim.** `Rgmg_ss` is a real `ppolyf_u_3k` and its 150 um2
  is budgeted below, but nothing here is extracted.

## Alternatives considered

- **A larger bleed** (or none at all). The recovery scales with the bleed:
  450 kohm throttles the post-release branch current about 2.8x, and a
  larger value recovers more. DR-0027's zero-bleed limit is the extreme case
  and does not converge at `ss_-40c_2.97v`. Where between 450 kohm and
  infinity the DC solution stops being well determined is **not measured
  here** -- 450 kohm is the first value tried and it converges at 81/81
  Iq points and 63/63 hand-over corners, so it is what this record proposes.
  A follow-on that wants the remaining ~2 uA should sweep the bleed with the
  `ss_-40c_2.97v` convergence check as its bound, not assume it is free.
- **Gate the branches' return path instead of the supply side**, mirroring
  `Mgme_ss`'s existing NMOS-on-the-return idiom (DR-0027's first untested
  alternative). Still untested. It was not pursued because the branches'
  returns are *already* gated by `Mgme_ss` for enable, so a second series
  NMOS there stacks two devices' `Vds` under `GMIA`, which is the headroom
  the cell's "THE HEADROOM TRAP THIS AVOIDS" note says it cannot spend. The
  supply side has a full `VIN` of headroom and does not.
- **Do nothing and leave the adder as a documented cost.** Always available.
  Not preferred: 1.29 uA was the tightest this row has ever been, and
  DR-0026's servo amplifier is already named as wanting part of it.

## Consequences

- `design/ldo_softstart.sch` gains `Mgmg_ss` and `Rgmg_ss` and the `VING`
  node; `design/netlist/ldo_softstart.spice` and `ldo_core.spice` are
  re-exported. No port changes, so no testbench or symbol changes.
- **Area**: +5 um2 of transistor (`Mgmg_ss`, 10 x 0.5 um) and +150 um2 of
  `ppolyf_u_3k` (`Rgmg_ss`, 150 squares at W = 1 um). Against the ratified
  < 0.1 mm2 core-area row, +0.16 %.
- **The Iq budget DR-0026 was told to fit inside changes.** DR-0026's servo
  amplifier was given 1.29 uA at the binding corner's full-load clause; with
  this change that clause reads 23.7275 uA, i.e. **6.27 uA** of headroom
  (and the no-load clause 7.03 uA). DR-0026 is unratified and unimplemented,
  so nothing in it needs editing today -- but its "second budget" fallback is
  now spent, and a future implementation PR of DR-0026 should cite the
  headroom from `20260919-080719-de8b468.md` rather than the 1.29 uA figure.
- T1-T5 remain **unmet** and the R4 lever (the 300 kohm feedback
  transimpedance) remains the next decision, exactly as DR-0023's
  Consequences and `design/softstart_injection_compensation.md` §3 (R4)
  state. This record does not touch it.
- `spec/decision-records/DR-0027-...` stays filed as the negative result it
  is; its "Alternatives considered" second bullet is the one this record
  takes.

## Related

- Issue #259 -- this record's origin.
- DR-0027 -- the same gate without a bleed, and the convergence failure that
  made the bleed necessary.
- DR-0023 -- ratified the cascoded mirror whose cutoff event this mechanism
  piggybacks on; its rectification-by-cutoff property is unchanged.
- DR-0026 (proposed) -- the servo loop whose Iq budget this widens.
- DR-0004 amendment A6 -- the `< 30 uA` row all of this is measured against.
- `design/softstart_injection_compensation.md` §3 -- the T1-T7 targets.
