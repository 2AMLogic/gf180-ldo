# DR-0019: Buying `f_hi` via `Mbuf`/`Mbufb` standing current is blocked by the amplifier's own (already-exhausted) `iq_ua` allocation, and too low-leverage to reach the target even without it

- **Status**: proposed -- ratification is the operator's, the same process
  DR-0001, DR-0008, DR-0012 through DR-0018 went through. **Nothing in this
  record is in force until an operator ratifies it.** What is not
  conditional on ratification is the evidence: every number below is a run
  of a committed, unmodified testbench against a stated one-variable edit of
  `design/error_amp.sch`, and the commands are given so each is
  reproducible.
- **Date**: 2026-08-21
- **Decided by**: Builder agent, issue #147 (recommendation only)
- **Relates to**: DR-0015 ("ways out" item 1, "Buy `f_hi`"), DR-0016
  (Candidate 2's buffer-bandwidth half, un-attempted before this issue),
  DR-0017 (confirms compensation-network tuning is exhausted once `Mrza`/
  `Rza` is shipped), DR-0018 (proposes a spec-narrowing alternative,
  independent of this record). Supersedes none of them, and does **not**
  change `design/`.
- **Ships no circuit change.** `design/` is unchanged by the PR that adds
  this record, for the reason DR-0013/DR-0014/DR-0017 used the same
  sentence for: a wash -- or here, a lever that cannot be pulled at all
  within an existing regression suite's own bound -- is not a result to
  ship silently.

## Context

DR-0015 measured the LDO loop's crossover pass band as bounded above by
`f_hi`, the output stage's own forward-path phase cliff (measured 0.31 MHz),
and computed that closing DR-0001's full cap window at heavy load needs
`f_hi` roughly tripled, to 0.76-0.95 MHz. Its "ways out" item 1 named the
lever directly: raise the class-AB buffer's (`Mbuf`/`Mbufb`, possibly `M2N`)
standing current. DR-0016 (issue #90) and DR-0017 (issue #51) both
independently re-confirmed this is the one remaining in-silicon lever once
`Mrza`/`Rza` is already shipped and compensation-network tuning is
exhausted. Both quoted the same Iq budget: **7.40 µA** of headroom against
the ratified whole-regulator `sim/quiescent-current` row (`Iq < 30 µA`,
worst corner `ff`/125 °C/3.63 V, measured 22.60 µA). Issue #147 was filed to
actually build and measure this lever, since neither DR-0015 nor DR-0016
built it -- both explicitly deferred it as "its own issue and its own
record."

This record is the result of building it. It finds a **tighter, separate**
Iq constraint neither DR-0015 nor DR-0016 identified -- `sim/amp-openloop`'s
own `iq_ua <= 15 µA` row, not the 30 µA whole-regulator row -- already has
essentially zero headroom in the currently-shipped design, and forecloses
the lever before the whole-regulator row ever becomes binding. Independent
of that, the lever is also measured to be far lower-leverage on `f_hi`
specifically than the historical `f_2` data point (DR-0009, DR-0016
"Direction and rough scale") implied.

## What was measured

All three variants below are `design/error_amp.sch` at `4572a0e` (the head
commit at the time of this record) with **one and only the stated edit**,
re-netlisted via `design/netlist.py --check` (clean tree, byte-for-byte
reproducible), screened with `sim/run_corners.py amp-openloop` and
`sim/loop-stability/testbench/sweep.py`'s own `run_point()` called directly
against the full load x cap x ESR grid at a single PVT point (the same
computation `--explore` runs, printed per-cell instead of summarized, since
locating `f_hi`'s crossing needs the individual cells DR-0015's own method
used).

**1. The blocking row, found before any sizing choice mattered.**
`sim/amp-openloop`'s `iq_ua` row (`sim/amp-openloop/testbench/tb.json`:
`"max": 15.0`, described there as "error-amp bias allocation from
`spec/architecture-survey.md` S5 (10-15 µA of the 30 µA whole-regulator
budget)") is a **different, and far tighter, row** than the ratified
whole-regulator `sim/quiescent-current` row DR-0015/DR-0016/DR-0018 quoted
headroom against. The current, shipped baseline's own head record
(`sim/amp-openloop/records/20260807-105147-64249c6.md`) already reports it
at **14.9784 µA at `ff`/125 °C/3.63 V against the 15.0 µA cap -- 0.0216 µA
of headroom**, reproduced here bit-for-bit at the same corner:

```
python3 sim/run_corners.py amp-openloop --corners ff --temps 125 --supply 3.63 --supply-tol 0 --no-write
  -> iq_ua = 14.9784  (matches the head record exactly)
```

This row's own description in `design/error_amp.md` §"CURRENT BUDGET" and
§6.11's table calls it "soft" -- it traces to `spec/architecture-survey.md`
§5's early "rough primary-design allocation" (10-15 µA), written before the
class-AB buffer (#51) or the `Mrza`/`Rza` adaptive shelf (DR-0015) existed,
and it is not itself ratified by any `spec/decision-records/` entry. But it
**is** wired into `sim/amp-openloop/testbench/tb.json` as a hard bound, the
harness enforces it exactly like every other row (`CHECK FAIL` / overall
`status: FAIL` when exceeded, no "soft" exemption exists anywhere in
`sim/harness/` or `sim/run_corners.py`), and issue #147's own Acceptance
Criteria require `sim/amp-openloop` to **re-run and PASS**. This record
therefore treats it as binding, consistent with CLAUDE.md's "agents do not
relax the ratified spec to make results pass" -- `tb.json` was not touched
to attempt this lever.

**2. Even the smallest sizing step tried blows through the row by ~40x its
available margin.** Candidate A: `Mbuf` `L=0.5u W=60u nf=6` ->
`W=70u nf=7` (+16.7 % gate width), `Mbufb` `L=1u W=100u nf=10` ->
`W=120u nf=12` (+20 % gate width), `M2N` unchanged -- the smallest step that
could plausibly move `f_hi` at all, roughly a fifth more standing current
through the class-AB output devices `design/error_amp.sch` names as
"`1/gm(Mbuf)` sets the pass-gate node impedance."

| | baseline (`ff`/125 °C/3.63 V) | Candidate A |
|---|---|---|
| `iq_ua` | 14.9784 | **15.833** |
| margin to 15.0 µA cap | +0.0216 | **-0.833** |
| `sim/amp-openloop` status | PASS | **FAIL** |

The overrun (0.833 µA) is roughly **38.6x** the baseline's own margin
(0.0216 µA). At the milder `tt` corner set (9 points, `--corner-set tt`),
the same edit moves `iq_ua` from a baseline 10.57-11.62 µA
(`tt_27c_3.63v`/`tt_125c_3.63v`) to 11.17-12.28 µA -- a +0.60 to +0.66 µA
cost even at typical process, confirming the `ff`/125 °C/3.63 V number is
not a corner-specific artifact.

**3. A much larger step (2.5x) confirms the same row fails harder, and
quantifies how little `f_hi` moves for it.** Candidate B: `Mbuf` `W=60u
nf=6` -> `W=150u nf=15`, `Mbufb` `W=100u nf=10` -> `W=250u nf=25` (2.5x gate
width on both), `M2N` unchanged.

| corner | baseline `iq_ua` | Candidate B `iq_ua` |
|---|---|---|
| `tt_27c_3.63v` | 10.57 | **15.048** |
| `tt_125c_3.63v` | 11.6191 | **16.5853** |

Both already exceed the 15.0 µA cap at the mild `tt` corner set alone, well
before reaching `ff`/125 °C/3.63 V (which is always the record's worst
corner on this row, per every prior `sim/amp-openloop` record) -- this
variant was not re-measured at that single corner because Candidate A
already establishes the row is blocking, and this variant fails it more
severely at a milder corner.

**4. `f_hi` itself, measured directly (not assumed from `f_2`) -- and the
leverage is far short of what DR-0009's `f_2` data point implied.** Per
DR-0015's own method: at `tt`/27 °C/3.30 V/1 mΩ, sweep load x cap and find
where PM crosses 45° in the 0.33 µF column (the "above" edge of the pass
band, `f_hi`), by log-linear interpolation between the last passing and
first failing load step:

| variant | `1 mA/0.33 µF` (PASS) | `10 mA/0.33 µF` (FAIL) | interpolated `f_hi` | vs. baseline |
|---|---|---|---|---|
| baseline | 259694 Hz / 48.95° | 503033 Hz / 28.61° | **295.3 kHz** | -- |
| Candidate A (+16.7-20 % W) | 254003 Hz / 50.53° | 495702 Hz / 30.63° | **305.9 kHz** | **+3.6 %** |
| Candidate B (2.5x W) | 246948 Hz / 52.49° | 480466 Hz / 34.75° | **327.1 kHz** | **+10.8 %** |

(The baseline's interpolated 295.3 kHz cross-checks DR-0015's own directly-
measured 309 kHz, taken at the exact `50 mA/1 µF/1 mΩ` boundary cell rather
than by interpolation -- a ~4.5 % difference consistent with the two being
different, if related, measurement methods on the same quantity.)

DR-0015's target is `f_hi` >= 0.76-0.95 MHz, i.e. **2.58x-3.22x** the
baseline. Candidate B -- a 2.5x gate-width increase that is *already*
roughly 19x over its own corner's Iq margin on the blocking row above, and
whose absolute device area (`Mbuf` 30 -> 75 µm², `Mbufb` 100 -> 250 µm²)
is itself a meaningful layout-area cost -- bought only **10.8 %** of `f_hi`.
Fitting a power law between the two measured points (`W` scale 1.167 -> 2.5,
`f_hi` ratio 1.036 -> 1.108) gives an effective exponent of roughly
**0.11-0.23** for `f_hi` against `Mbuf`/`Mbufb` width alone -- reaching
2.58x-3.22x at that exponent would need a further **20x-100x** width
increase on top of Candidate B, which is both physically absurd (matching,
routing, the buffer would dwarf every other device in the cell) and
enormously over every Iq row in play, several times over.

This is the measurement DR-0015 flagged as the open question: "This is
evidence about `f_2` ... not directly about `f_hi` -- the two are related
but not shown to be numerically identical, and this issue's first job is to
establish that relationship, not assume it." Measured: they are not
numerically close. DR-0009's historical (`--no-write`, unminted) result
tripled `f_2` for roughly a 1.9x total-Iq increase by scaling the buffer
*and* stage-2 driver (`M2P`/`M2N`) together, which changes the local loop's
*other* pole (`gm(M2P)/Cgs(Mbuf)`, per `design/error_amp.md` line 729) at
the same time. Scaling `Mbuf`/`Mbufb` alone -- the sizing this record
tried, and the one issue #147's own "possibly `M2N`" phrasing treats as the
fallback rather than the primary lever -- raises `Cgs(Mbuf)` in step with
`gm(Mbuf)`, which plausibly explains why it is a much weaker lever on this
specific quantity than the `f_2` data point suggested. A joint `M2P`/`M2N`/
`Mbuf`/`Mbufb` scale, closer to DR-0009's own regime, was not measured here
-- see "What this does not establish" -- but it would add `M2P`/`M2N`
branch current on top of the buffer branch's, which only makes the
already-blocking `iq_ua` row bind *harder*, not less.

**5. What did *not* block this lever.** The two other rows issue #147's
Acceptance Criteria named as at-risk stayed comfortably clear at both
candidate sizes: `gain_1k_db` (ratified floor 53.5 dB) measured 56.3-59.8 dB
at Candidate A/B (all corners, `tt` set) -- *improved* over baseline, not
degraded, since more buffer `gm` only helps this row; `peak_excess_db`
(DR-0008's precondition, bar <= 1 dB) measured -0.02 to -0.07 dB at both
candidates, clean. The finding here is specifically about `iq_ua`, not
about PSRR or the local-loop resonance check.

## Decision

**1. `design/` is left unchanged.** The lever DR-0015/DR-0016/DR-0018 named
as the last remaining in-silicon path to closing DR-0001's wide-cap/
heavy-load cells cannot be built at any size that both (a) re-passes
`sim/amp-openloop` -- specifically its `iq_ua <= 15 µA` row, which the
shipped baseline already occupies to within 0.0216 µA -- and (b) moves
`f_hi` by a measurable fraction of the 2.58x-3.22x this issue's own
Acceptance Criteria cite as the target. Every size tried fails (a); the
largest size tried, which already fails (a) by a wide margin, still falls
roughly two orders of magnitude short of (b).

**2. The binding constraint is `sim/amp-openloop`'s internal `iq_ua`
allocation, not the ratified whole-regulator `Iq < 30 µA` row.** DR-0015 and
DR-0016 both budgeted this lever against the 30 µA row's 7.40 µA of
headroom. That headroom is real and mostly unspent -- Candidate A's whole-
regulator cost was not separately re-measured here, but Candidate A/B's
`amp-openloop`-scope cost (+0.6 to +5.0 µA depending on size) is well inside
it. The lever dies against a different, narrower internal sub-budget
(`spec/architecture-survey.md` §5's "10-15 µA error-amp allocation," wired
into `sim/amp-openloop/testbench/tb.json` as `iq_ua <= 15 µA`) that neither
prior record checked, and that the shipped baseline already spends to
99.86 % of.

**3. This record relaxes no bar.** DR-0001's 45°/10 dB, its `C_eff` and ESR
windows, and `sim/amp-openloop/testbench/tb.json`'s `iq_ua` row are all
untouched.

## Alternatives considered

- **Loosen or remove `sim/amp-openloop`'s `iq_ua <= 15 µA` row**, since it
  is documented as "soft" and not itself ratified by any decision record --
  only `spec/architecture-survey.md` §5's early, pre-buffer, pre-`Mrza`/
  `Rza` "rough allocation." **Not done here.** It is wired into a ratified
  regression suite's automated PASS/FAIL gate today, and CLAUDE.md is
  explicit that agents do not relax the spec to make results pass -- that
  call is an operator's, not this record's, exactly as DR-0018 routes its
  own spec-narrowing proposal to an operator rather than landing it as a
  circuit or testbench change. If an operator judges this allocation stale
  (a defensible reading, given it predates two major topology additions and
  the whole-regulator row already gives 7.40 µA of headroom this
  sub-allocation does not honor), re-deriving it and ratifying the new
  bound via its own decision record would reopen this lever -- worth a
  follow-up issue, not a decision this record makes unilaterally.
- **Scale `M2P`/`M2N` together with `Mbuf`/`Mbufb`**, matching DR-0009's own
  regime more closely, in case the joint scaling is more `f_hi`-efficient
  per microamp than `Mbuf`/`Mbufb` alone. Not measured here -- see "What
  this does not establish" -- but it spends the already-exhausted `iq_ua`
  row *faster* (adds the stage-2 branch's cost on top of the buffer's), so
  it does not escape Decision 1 regardless of its `f_hi` efficiency.
- **Reduce Iq elsewhere in the amplifier to make room** (input pair,
  stage-1 tail, bias generator) so a buffer increase nets to zero on
  `iq_ua`. Not attempted: those branches are sized against offset, noise
  and PSRR budgets `design/error_amp.md` documents in detail, and trading
  them against a buffer-bandwidth increase is a materially larger, riskier
  redesign than "resize `Mbuf`/`Mbufb`" -- outside this issue's scope as
  written, and not a change to make inside a single builder session without
  its own dedicated verification pass.
- **Push a full 4536-point `sim/loop-stability` matrix run anyway**, on the
  chance the `iq_ua` row is judged non-blocking by a later reviewer despite
  failing the harness's automated check. Rejected: `sim/amp-openloop`
  failing is itself one of issue #147's own Acceptance Criteria items, and
  the fast screens above (`amp-openloop --corner-set tt`, ~90 s;
  `sweep.py`'s per-point grid at one PVT corner, ~34 s) already show neither
  candidate is admissible before spending the 30+ minute full-matrix budget
  the issue's own verification-cost warning asks builders to conserve.

## Consequences

1. **No `design/` change, no re-verification burden.** `sim/amp-openloop`,
   `sim/psrr-dc`, `sim/amp-selfosc`, `sim/quiescent-current` and
   `sim/loop-stability`'s own head records are all unaffected; nothing here
   supersedes `sim/loop-stability/records/20260807-103351-64249c6.md`.
2. **DR-0016 Candidate 2's buffer-bandwidth half, and DR-0015's "ways out"
   item 1, are now measured and found not viable as scoped** (`Mbuf`/
   `Mbufb` resizing within `sim/amp-openloop`'s current `iq_ua` bound). The
   wide-cap/heavy-load and wide-cap/light-load cells DR-0018 proposes to
   give up via a spec-narrowing route, rather than close via a further
   circuit change, are consistent with that route being the remaining
   practical path -- this record does not itself argue for DR-0018 (a
   separate, independently-filed proposal) but removes the one alternative
   circuit-side lever DR-0018's own "Files no circuit change" note left
   open.
3. **A previously-unmeasured internal budget row is now flagged as
   effectively exhausted.** `sim/amp-openloop`'s `iq_ua <= 15 µA` allocation
   sits at 99.86 % spent in the shipped baseline (14.9784/15.0 µA at
   `ff`/125 °C/3.63 V). Any future amplifier-side change that adds standing
   current anywhere in the cell -- not just the buffer -- should check this
   row first; it will bind before the whole-regulator 30 µA row does for
   any change smaller than roughly 7 µA that is concentrated in the
   amplifier rather than spread across the whole regulator (reference,
   divider, pass-gate bias) the 30 µA row also covers.

## What this does not establish

- **Not a global search over buffer topology.** Only `Mbuf`/`Mbufb` gate
  width was varied, at two points (1.167-1.2x and 2.5x), with `M2N`/`M2P`
  held fixed. A joint scale of the whole stage-2/buffer bias chain
  (`M2P`/`M2N`/`Mbuf`/`Mbufb` together, closer to DR-0009's own regime) was
  not measured, and per "Alternatives considered" above would not escape
  the `iq_ua` blocker even if it proved more `f_hi`-efficient per microamp.
- **Not evidence that `iq_ua <= 15 µA` is the correct allocation.** It is
  measured to be binding as currently specified, not judged here as right
  or wrong -- that is the operator call flagged in "Alternatives
  considered."
- **Not evidence against DR-0009's `f_2` measurement.** DR-0009's tripling
  of `f_2` for a joint buffer-and-stage-2 current increase is not disputed;
  this record's finding is that `f_hi` (a different, though related,
  quantity DR-0015 itself flagged as unestablished against `f_2`) responds
  far more weakly to a `Mbuf`/`Mbufb`-only version of the same kind of
  change.

## Reproduction note

`design/netlist.py --check` confirms clean-tree byte-for-byte
reproducibility for every variant before it was measured, and again after
reverting to baseline for this record. `sweep.py`'s per-cell grid (variant
4's table) was obtained by calling `run_point()` directly against the same
`tt`/27 °C/3.30 V single-PVT corner `--explore` uses, printing every
`(iload, ceff, esr)` cell instead of only the worst point -- `--explore`
itself only prints a one-line summary, not the per-cell table DR-0015's own
method needs to locate `f_hi`'s crossing. No testbench, threshold or matrix
definition was modified anywhere in this work.

Commands used for every figure above:

```
python3 design/netlist.py                                    # after each one-line .sch edit
python3 design/netlist.py --check                             # confirm clean tree before measuring
python3 sim/run_corners.py amp-openloop --corner-set tt --no-write
python3 sim/run_corners.py amp-openloop --corners ff --temps 125 --supply 3.63 --supply-tol 0 --no-write
./sim/loop-stability/testbench/run.sh --explore -j2            # fast single-PVT screen (34 s, this host)
```

The per-cell `f_hi` table (variant 4) used a short ad hoc driver script that
imports `sim/loop-stability/testbench/sweep.py` and calls its own
`find_pdk()` / `resolve_corners()` / `build_grid()` / `run_point()`
functions directly against the `tt`/27 °C/3.30 V grid -- the same
computation `--explore` performs, with the per-cell rows printed instead of
summarized. The script is not part of this PR (it duplicates no logic
worth committing -- it is a thin wrapper that calls the existing, unmodified
`sweep.py` functions and prints their result); anyone reproducing this
record can write an equivalent five-line script or add per-cell `-v`
output to `sweep.py --explore` as a follow-up if this becomes a routine
need.
