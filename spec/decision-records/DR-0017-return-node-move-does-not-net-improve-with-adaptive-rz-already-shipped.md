# DR-0017: With `Mrza`/`Rza` already shipped, `Cc` -> `BG` plus a `Cf` step is a wash, not a win -- and the `Cf` floor is numerically prohibitive to reach

- **Status**: proposed -- ratification is the operator's, the same process
  DR-0001, DR-0008, DR-0012 through DR-0016 went through. **Nothing in this
  record is in force until an operator ratifies it.** What is not
  conditional on ratification is the evidence: every number below is a run
  of a committed, unmodified testbench against a stated one-variable edit of
  `design/error_amp.sch`, and the commands are given so each is
  reproducible.
- **Date**: 2026-08-21
- **Decided by**: Builder agent, issue #51 (recommendation only)
- **Relates to**: DR-0014 (`f_2`'s ceiling is `Cc`'s return node), DR-0015
  (the adaptive `Rz` shunt, `Mrza`/`Rza`, shipped in `design/error_amp.sch`
  at the time this record was written), DR-0012 (the shelf is `Cc/Cf` wide).
  It supersedes none of them, corrects one implicit assumption in DR-0014's
  Decision section (see "What this corrects" below), and does **not**
  change `design/`.
- **Ships no circuit change.** `design/` is unchanged by the PR that adds
  this record, for the reason DR-0013/DR-0014 used the same sentence for: a
  wash is not a result to ship silently, and issue #51's own Acceptance
  Criteria were written specifically to stop that.

## Context

DR-0015 shipped `Mrza`/`Rza`, an adaptive shunt across `Rz` gated by `BG`,
and measured the current head record
(`sim/loop-stability/records/20260807-103351-64249c6.md`): **2930/4536
(64.6%)**, worst point `res_ss_-40c_2.97v` at 50 mA / 0.33 uF / 1 mOhm, PM
**-6.81 deg**, GM **-1.47 dB**. Its own "ways out" section, item 0, named the
next increment as free: move `Cc`'s return node from `OUT` to `BG`
(DR-0014's finding, measured in isolation on the **pre-adaptive-Rz**,
fixed-`Rz` topology at `c628c15`), then re-measure `Cf`'s floor, "because it
is free and it un-binds the knob this record had to leave on the table."
Issue #51 was un-parked to execute exactly that.

This record is the result of actually running that increment against the
**shipped** topology (`Mrza`/`Rza` already in the loop, not the fixed-`Rz`
topology DR-0014 measured `Cc` -> `BG` against) and it does not reproduce
DR-0014's isolated result: combined with the adaptive shunt already in
place, the return-node move is a wash on the full matrix, a further `Cf`
step barely moves it, and reaching the `Cf` floor DR-0014/DR-0015 predicted
would matter is numerically prohibitive to verify on this deck.

## What was measured

All three variants below are `design/error_amp.sch` at `5f71155` (the head
commit at the time of this record) with **one and only the stated edit**,
re-netlisted via `design/netlist.py`, run through
`sim/loop-stability/testbench/sweep.py` (full ratified 4536-point matrix,
`dec 400`, unmodified) and, for the `Rza`/`Cf` screens, through
`python3 sim/run_corners.py amp-openloop --corner-set tt`.

**1. `Cc` -> `BG` alone (`Rza` = 600 kOhm, `Cf1`/`Cf2` = 7x7 um MIM, both
unchanged from the committed design):**

| | head (`20260807-103351-64249c6`) | `Cc` -> `BG` alone |
|---|---|---|
| DR-0001 points passing | 2930/4536 (64.6%) | **2821/4536 (62.2%)** |
| worst PM | -6.81 deg | **-4.37 deg** |
| worst GM | -1.47 dB | **-1.17 dB** |
| worst point | `res_ss_-40c_2.97v` 50 mA/0.33 uF/1 mOhm | `res_ss_-40c_3.63v` 50 mA/0.33 uF/1 mOhm |
| DR-0008 resurgence | 0/4536 | 0/4536 (clean) |

By load column (points passing / 756, from the matrix CSV):

| `I_load` | head | `Cc` -> `BG` alone |
|---|---|---|
| 0 mA | 0 | 0 |
| 0.1 mA | 675 | 669 |
| 1 mA | 714 | 694 |
| 10 mA | 567 | 531 |
| 25 mA | 513 | 490 |
| 50 mA | 461 | 437 |

**Every load column from 0.1 mA up loses points.** The single worst PVT
corner's margin improves by 2.44 deg / 0.30 dB, and the aggregate count
falls by 109 points. Read against DR-0001's actual bar (every point must
pass, not a percentage), the worst-point improvement is real progress
toward closing the matrix; read against "no silent regression," the
aggregate fall is a real cost. Neither reading alone settles whether to
ship it, which is why the next two measurements matter.

**2. `Cc` -> `BG` plus a `Cf` step (`Rza` unchanged at 600 kOhm, `Cf1`/`Cf2`
7x7 um -> 6x6 um MIM, a 27% area cut -- roughly DR-0014's own "one step of
`Cf`"):**

| | head | `Cc` -> `BG` + `Cf` = 6x6 um |
|---|---|---|
| DR-0001 points passing | 2930/4536 | **2843/4536 (62.7%)** |
| worst PM | -6.81 deg | **-4.33 deg** |
| worst GM | -1.47 dB | **-1.15 dB** |

Against variant 1 (`Cc` -> `BG` alone): +22 points, +0.04 deg of worst-case
margin. **A full step of `Cf` moved the matrix by 0.5 percentage points and
the worst corner by four hundredths of a degree.** This is the measurement
that does not reproduce DR-0014/DR-0015's prediction: DR-0014 estimated the
residual gap at "1.5-2x of `Cc/Cf`, one step of `Cf`" against DR-0012's
measured 98x (needing roughly 900x). One step bought essentially nothing.
The likely reason, consistent with DR-0015's own "What is still not
reached" section: `Rza` already relieves most of the pressure a wider shelf
would otherwise buy, so the two levers are not additive -- `Cf` widens the
shelf's *top* corner (`f_2`), but the binding constraint at the worst
corner (per DR-0015 section "The obstruction, at 50 mA") is `f_hi`, the
output stage's own forward-path phase cliff, which neither `Cc`'s return
node nor `Cf` touches at all.

**3. `Cf` toward its process floor (5x5 um, the narrowest MIM width the
model's own width branch supports per the comment at
`design/error_amp.sch` line ~51): not fully measured -- numerically
prohibitive on this deck.**

At `Cf1`/`Cf2` = 5x5 um (`Rza` = 600 kOhm, `Cc` -> `BG`), a single-PVT-point
screen (`sweep.py --explore`, tt/27 C/3.30 V, 72 load/cap/ESR points inside
one ngspice invocation) still completes in the expected ~30-40 s. The full
63-PVT-point matrix does not: at `-j8` the first 8-corner batch (all `tt`
process, one temperature/supply axis) did not complete a single corner in
45 minutes of wall-clock time before this record's author killed it (CPU
time was climbing steadily throughout, i.e. genuinely computing, not
hung). At `-j1` -- which turned out to matter independently, see
"Reproduction note" below -- most corners complete in 30-100 s as expected,
but a handful of specific PVT corners (`ss`/125 C/3.30 V measured directly;
`fs`/27 C/2.97 V inferred from the same pattern at `Cf` = 6x6 um, see
below) took 24-40 minutes **each** before converging, an 30-80x slowdown
against this same deck's baseline per-corner time. The full 4536-point
matrix at `Cf` = 5x5 um was not completed in this session.

The same slow-corner pattern, less extreme, reproduces at `Cf` = 6x6 um:
of 63 corners, two (`ss`/125 C/3.30 V and `fs`/27 C/2.97 V) each took
20-40 minutes at `-j1` against a ~30-100 s baseline for the other 61, before
eventually converging. This is evidence that the slowdown is a property of
narrowing `Cf` on this topology -- almost certainly a resonance in the
`Rz`/`Cc`/`Cf` local loop moving into a frequency range where the AC
sweep's Newton iteration needs many more steps per decade to track it --
and not solely a host-contention artifact, though host contention
(observed load average 40-70 on an 8-core host throughout this session,
unrelated tenants) made it far worse at high `-j`.

**A second, independent constraint appeared during the `Rza` screen below
`Cf` = 5x5 um**: at `Rza` = 100 kOhm (`Cc` -> `BG`, `Cf1`/`Cf2` = 7x7 um
still), `sim/amp-openloop --corner-set tt` fails outright on `pm_deg` --
the amplifier's **own** open-loop phase margin, a check this record's other
variants never touched -- at 5 of 9 corners, as low as **2.76 deg**
against the ratified 45 deg bar (`tt_-40c_3.63v`). This is a different
failure from DR-0008's resurgence check and from `peak_excess_db` (both of
which stayed clean or improved as `Rza` fell): it is the amplifier's local
loop losing stability outright, not merely its shelf shape moving. `Rza` =
150 kOhm still passes (`pm_deg` >= 118 deg, `peak_excess_db` -0.16 to
-0.30 dB), so the floor sits between 100 and 150 kOhm on this screen --
well above the "no floor at all" framing DR-0015's own theory would
suggest for a DC-currentless shunt, and worth noting as a bound nobody had
measured before this record.

## The `Rza` re-tuning screen (why the committed 600 kOhm was not
   improved on)

With `Cc` -> `BG` already applied, `Rza` was swept (`Cf1`/`Cf2` held at
7x7 um) and screened two ways: `sim/loop-stability --explore`
(tt/27 C/3.30 V, 72 points, ~30-40 s/run) and `sim/amp-openloop
--corner-set tt` (~90-125 s/run):

| `Rza` | loop-stability `--explore` failing/72 | amp-openloop `peak_excess_db` | amp-openloop `pm_deg` |
|---|---|---|---|
| 600 kOhm (committed) | 24 | -0.10 to -0.16 dB | PASS |
| 550 kOhm | 23 | -- | -- |
| 500 kOhm | 24 | -- | -- |
| 450 kOhm | 24 | -0.10 to -0.16 dB | PASS |
| 300 kOhm | -- | -0.10 to -0.16 dB | PASS |
| 200 kOhm | 32 | -0.13 to -0.24 dB | PASS |
| 150 kOhm | 38 | -0.16 to -0.30 dB | PASS (min 118 deg) |
| 100 kOhm | -- | -0.20 to -0.38 dB | **FAIL**, min 2.76 deg |

`peak_excess_db` -- the check DR-0015 itself used to reject 450 kOhm in
favour of 600 kOhm on the committed (`Cc` -> `OUT`) topology -- stays
comfortably clear of its +1 dB bar all the way down to 100 kOhm once `Cc`
is on `BG`, exactly as DR-0014 predicted (the buffer/pass-gate poles are
out of that local loop). But the loop-stability screen gets **worse**, not
better, as `Rza` falls below the committed 600 kOhm: 24 -> 32 -> 38 failing
on the same 72-point tt/27 C/3.30 V grid. The committed value was already
close to a local optimum for this specific screen on the `Cc` -> `BG`
topology; the lever `peak_excess_db` used to bind DR-0015's choice is not
the lever binding this one. (This screen is single-PVT and does not by
itself establish a global optimum -- see "What this does not establish"
below.)

## What this corrects

DR-0014's Decision section reads "the next increment is: `Cc` -> `BG`,
then re-open the shelf width, then adaptive `Rz` -- in that order," and
measured `Cc` -> `BG` in isolation against the **pre-`Mrza`** fixed-`Rz`
topology at `c628c15`. By the time this issue was un-parked, `Mrza`/`Rza`
(item 3 in that ordering) had already shipped via DR-0015 -- so the actual
next increment available to a Builder was "`Cc` -> `BG` on top of an
already-adaptive `Rz`," not the clean, isolated case DR-0014 measured. This
record's variant 1 is that actual next increment, and it does not
reproduce DR-0014's per-net improvement once the adaptive shunt is already
absorbing most of the same slack. DR-0014's own numbers (81/81
`amp-openloop` PASS, `f_2` ceiling >= 8x higher) are not wrong -- they are
correct for the topology they were measured against, and DR-0009's Iq-cost
figures they superseded have the same scoping caveat this record now adds
one layer deeper.

## Decision

**1. `design/` is left unchanged.** None of the three variants above is an
unambiguous net improvement over the shipped head record
(`20260807-103351-64249c6`, 2930/4536): variant 1 and variant 2 both trade
aggregate pass count for single-worst-point margin, and variant 3 (the one
DR-0014/DR-0015 predicted would matter) could not be verified to
completion in this session for reasons that are about verification cost,
not about the circuit being wrong -- so it is withheld rather than shipped
on a partial or dirty-tree measurement, per issue #51's own Acceptance
Criteria ("a silent partial-pass record ... is not sufficient").

**2. The remaining 1-50 mA/0.33 uF gap is confirmed, not newly found, to
require `f_hi` (buffer bandwidth), not further compensation-network
tuning.** This record's `Cf`-step measurement (variant 2, +22 points for a
full step) is an independent, fresh data point that corroborates DR-0015's
own closed-form bound (the `Rz_eff` window needed to fit the cap axis and
the window needed to stay under the `f_hi` cliff are 9.4x apart, and no
`Rz_eff` sits between them) rather than contradicting it. DR-0015's "ways
out" item 1 -- buying `f_hi` via buffer standing current, budgeted at
approximately 5-7 uA against the ratified `Iq < 30 uA` row's measured
headroom -- remains the highest-value lever this issue has identified and
not yet attempted.

**3. `Cf` below approximately 6x6 um is not a practical lever on this
testbench as currently structured**, independent of whether it would help
the margin: the AC-sweep convergence cost at specific PVT corners rises
30-80x as `Cf` approaches the process's minimum MIM width, which is a
testbench/numerics finding worth recording for whoever next varies `Cf`,
not a claim about the circuit's stability.

**4. `Rza` stays at its committed 600 kOhm.** The screen above found no
value in [100, 600] kOhm that improves the tt/27 C/3.30 V loop-stability
screen over the committed value once `Cc` is on `BG`, and found a new
floor (`pm_deg` failing below ~100-150 kOhm) that had not been measured
before. This is informational for the next increment, not a change.

**5. This record relaxes no bar.** DR-0001's 45 deg / 10 dB, its `C_eff`
and ESR windows and its load axis are untouched.

## Alternatives considered

- **Ship variant 2 anyway, on the strength of the worst-point
  improvement.** Rejected: aggregate regression across every load column
  from 0.1 mA up, for +22 points and four hundredths of a degree, does not
  clear the bar issue #51's Acceptance Criteria set after #42's and #56's
  partial-pass closures -- a "the worst point got better" argument without
  a matching "and nothing else got worse" argument is exactly the pattern
  those criteria exist to catch.
- **Push through to `Cf` = 5x5 um regardless of runtime.** Attempted;
  abandoned after 45 minutes of wall-clock time produced zero completed
  corners at `-j8` (an oversubscription artifact, see "Reproduction note")
  and a subsequent `-j1` attempt, while more tractable, still hit
  individual corners taking 20-40 minutes each with no guarantee the
  remaining ~30 unmeasured corners would not include worse outliers. Given
  variant 2's measurement that a full `Cf` step buys next to nothing once
  `Rza` is already shipped, the expected value of finishing this run inside
  one session did not justify the remaining compute.
- **Retune `Rza` downward to compensate for the `Cf` step.** Screened
  (the `Rza` table above) and found to make the single-PVT loop-stability
  screen worse, not better, below the committed 600 kOhm -- rejected on
  measurement, not by assumption.

## Consequences

1. **No `design/` change, no re-verification burden.** `sim/amp-openloop`,
   `sim/psrr-dc`, `sim/enable-shutdown`, `sim/amp-selfosc`,
   `sim/quiescent-current` and `sim/loop-stability`'s own head record are
   all unaffected; nothing here supersedes
   `sim/loop-stability/records/20260807-103351-64249c6.md`.
2. **DR-0009's Candidate 2, buffer-bandwidth half, is now the single
   remaining engineering path this issue's own decision-record chain has
   not attempted**, with a quantified target (roughly triple `f_hi`, per
   DR-0015) and a quantified budget (order 5-7 uA against the ratified
   `Iq < 30 uA` row). It is a different part of the amplifier (the buffer,
   not the compensation network) with its own PSRR and `amp-selfosc`
   exposure, consistent with DR-0015's own recommendation that it be
   scoped and verified as its own increment.
3. **A testbench-cost finding, not a stability finding**: narrowing
   `Cf1`/`Cf2` toward the process's minimum MIM width makes
   `sim/loop-stability`'s full-matrix run 30-80x slower at specific PVT
   corners on this deck. Whoever next tunes `Cf` should budget for this
   (screen with `sim/amp-openloop --corner-set tt`, which stayed fast
   throughout this session, before committing to a full matrix run) rather
   than rediscover it.
4. **A new, previously-unmeasured floor on `Rza`**: below approximately
   100-150 kOhm (with `Cc` -> `BG`), the amplifier's own open-loop phase
   margin fails outright, a different and more fundamental bound than the
   `peak_excess_db`/DR-0008-resurgence checks DR-0015 tuned against. Worth
   knowing before any future record pushes `Rza` lower to chase the
   loop-stability screen.

## What this does not establish

- **Not a global optimum search.** The `Rza` and `Cf` screens above are
  single-PVT (tt/27 C/3.30 V) or, for the two full-matrix runs, single
  points in a two-parameter space. A joint `Rza` x `Cf` sweep, or a sweep
  at the corners this issue's own records repeatedly name as binding
  (`ss`/`res_ss` at -40 C), was not attempted and might find a better
  combination than either committed value; this record's claim is narrower
  -- the two combinations actually tried (variants 1 and 2) are washes, not
  that no combination could ever help.
- **Not evidence against DR-0014's own measurements.** DR-0014's 81/81
  `amp-openloop` PASS and >= 8x `f_2` headroom figures are for the
  fixed-`Rz`, pre-`Mrza` topology and are not disputed here.

## Reproduction note

`sim/loop-stability/testbench/sweep.py`'s `ngspice` invocations are
internally multi-threaded (observed ~500-700% CPU per single-corner
process, `ngspice -46` with the KLU direct solver); running the sweep at
`-j8` on an 8-core host oversubscribes by roughly 5-8x and was measured to
make the full matrix dramatically slower (a batch of 8 `tt`-process
corners that should complete in a few minutes took 45+ minutes and was
abandoned) than running at `-j1`, where the same 63-corner matrix completed
in this session. Anyone re-running this sweep on a similarly-sized host
should default to a low `-j` (1-2) rather than one job per core, and treat
`-j` as tuned to the *host's* core count divided by ngspice's own internal
thread count, not to the corner count.

Commands used for every figure above:

```
python3 design/netlist.py                      # after each one-line .sch edit
./sim/loop-stability/testbench/sweep.py --explore                  # 72-point, single-PVT screen
./sim/loop-stability/testbench/sweep.py --no-write -j1             # full 4536-point matrix, no record minted
python3 sim/run_corners.py amp-openloop --no-write --corner-set tt -j4
```

No testbench, threshold or matrix definition was modified anywhere in this
work.
