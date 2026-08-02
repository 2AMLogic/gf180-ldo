# sim/loop-stability — loop gain, phase margin, gain margin

The stability evidence for the LDO loop (issue #10). This experiment
substantiates one claim and only one:

> **`spec/decision-records/DR-0001-output-cap-strategy.md`** — worst-corner
> phase margin ≥ 45° **and** gain margin ≥ 10 dB across the full
> `I_load × C_eff × ESR × PVT` matrix.

Per #10's scope note this is *the* phase-margin record for the block: #12's
spec-line testbench suite (dropout, load/line regulation, transient, PSRR,
Iq, startup) should reference records here rather than grow a second
phase-margin testbench under its own umbrella. Capless operation is **not**
covered — DR-0001 scopes it out of the primary design as a separate fork.

```
sim/loop-stability/
  testbench/
    tb_loop_stability.spice.in   the Tian dual-injection deck (a template)
    sweep.py                     PVT + load/cap/ESR driver; writes the record
    tb_tian_selftest.spice       three loops with analytically known gains
    selftest.py                  asserts the extraction against those loops
    compare_records.py           point-by-point diff of two matrix records
    run.sh                       selftest, then sweep
  netlist-snapshots/<record-id>.spice
  corners/<record-id>/<corner-id>.log
  records/<record-id>.md          + <record-id>-matrix.csv
```

## Running it

```bash
./sim/loop-stability/testbench/run.sh --explore   # tt/27 °C/3.3 V, writes nothing
./sim/loop-stability/testbench/run.sh             # full matrix, mints a record
./sim/loop-stability/testbench/selftest.py        # method check only (no PDK needed)
./sim/loop-stability/testbench/compare_records.py A B   # diff two records, no sim
```

`--explore` is DR-0001's recommended first pass: sweep `I_load × C_eff × ESR`
at `tt/27 °C/3.3 V` to find the worst triple before committing to the full
grid. The full run is 63 ngspice invocations covering 4536 loop-gain points
(the load/cap/ESR axes are swept *inside* each deck) — see *Sweep resolution*
below for the measured runtime, which issue #58's `dec 50` → `dec 400` change
moved. Use `-j` to match your core count. The process
axis is `tt ff ss fs sf res_ff res_ss`: issue #54 added `res_ff`/`res_ss`
because `Rz` (`ppolyf_u_1k`, since #51/#56's Type-II gain-shelf
recompensation) sets both the shelf gain and the shelf corner frequency, so
its ~40% process spread (`sim/devchar/CONCLUSIONS.md` §2) is a first-order
input to the result, not a second-order one.

Exit codes match `sim/run_corners.py`: `0` pass, `1` a stability check
failed, `2` a simulation failed, `3` an environment/usage problem. A run is
also refused outright (exit `2`) if any point's DC output is not within 10 %
of the regulation target: the ideal current-source load admits a second,
non-regulating DC solution, and a loop margin measured about it would be a
meaningless number that looks like a meaningful one. See the deck's
*"removing the non-physical DC branch"* comment.

## Sweep resolution — `AC_DEC`, and why it is 400 (issue #58)

Every record through `20260802-171044-db620a6` ran its AC sweep at `dec 50`
(≈ 4.7 % frequency steps). That is fine for a smooth, low-Q Bode response and
blind to a sharp one — and the blindness is not graceful. A resonance narrow
enough to fall between two grid points is not merely reported inaccurately;
it can be **invisible**. `resurgence_db` above is computed off this same
grid, so the DR-0008 detector inherits the blindness of the sample it is
computed from: a detector built on an under-resolved sweep can under-report
the very thing it exists to catch.

### The bound

Sampling a resonance of quality factor `Q` on a log grid of `dec` points per
decade, the worst case is the peak landing exactly midway between two
samples — a relative detuning of `d = 10^(1/(2·dec)) − 1`. A second-order
resonance detuned by `d` reads

```
miss(Q, dec) = 20·log10( sqrt( (2·Q·d)² + 1 ) )      dB below its true peak
Qmax(E, dec) = sqrt(10^(E/10) − 1) / (2·d)           largest Q held to E dB
```

| `dec` | step | worst-case miss at Q = 80 | `Qmax` at 1 dB | `Qmax` at 0.1 dB |
|---|---|---|---|---|
| 50 | 4.713 % | 11.73 dB | 10.9 | 3.3 |
| 100 | 2.329 % | 6.47 dB | 22.0 | 6.6 |
| 200 | 1.158 % | 2.68 dB | 44.1 | 13.2 |
| **400** | **0.577 %** | **0.84 dB** | **88.3** | **26.5** |
| 800 | 0.288 % | 0.22 dB | 176.7 | 53.0 |

**Policy: `AC_DEC` = 400** — the smallest ×2 step up from the old default
that holds the worst-case miss under **1 dB**, a tenth of DR-0001's 10 dB
gain-margin bar, out to `Q ≈ 88`. `dec 50` held that only out to `Q ≈ 11`.

This is a **stated capability, not a proof of sufficiency**. No finite grid
resolves an arbitrarily sharp feature, and the honest claim is that there is
now a bound where before there was none. `--ac-dec` exposes the knob, and
running *below* the default needs a written `--subset-reason` exactly as a
narrowed PVT grid does: the resolution is part of the measurement, not a
performance setting.

### The self-test that exercises it

`selftest.py`'s third reference loop is a Q = 80 resonance placed at the
worst-case sampling offset **for `dec 400` itself** (the geometric midpoint
of two `dec 400` grid points — which is also 87.5 % of worst case for
`dec 50`). Placing it at the `dec 50` midpoint instead would have landed it
exactly *on* a `dec 400` grid point and flattered the new policy by testing
it at its best case.

| | measured |
|---|---|
| true continuous peak above the first 0 dB crossing | **+3.90 dB** (a real resurgence — DR-0008 would flag it) |
| `resurgence_db` reported at `dec 50` | **−0.40 dB** — a clean, confident **false PASS** |
| `resurgence_db` reported at `dec 400` | **+3.11 dB** — correctly **FAIL** |

The 0.79 dB residual at `dec 400` is the 0.84 dB analytic worst case above,
measured. The old default is not slightly off on this loop; it is 4.30 dB
off, on the wrong side of a bar that has no slack in it.

### `cph()`'s phase unwrap is *not* the problem

Issue #58 also asked whether `cph()` picks the wrong 360° branch across an
under-sampled resonance. The same self-test answers it directly: the
unwrapped phase far above the resonance reads **−269.97°** against a −270°
analytic asymptote at **both** `dec 50` and `dec 400`. The reason is
structural — a minimum-phase pole *pair* has 180° of total phase variation,
so no sampling of one can produce the > 180° sample-to-sample step `cph()`
unwraps on. The resolution-sensitive quantity here is the **magnitude**, not
the branch. (A pole pair adjacent to a zero pair could exceed 180° in a step;
nothing in this loop's measured response does.)

### Why not a two-pass coarse-then-refine sweep

Issue #58's other option was to keep `dec 50` for the bulk and re-sweep a
narrow window around each point's crossover at high resolution. Rejected for
two reasons, in this order of importance:

1. **It cannot fix this failure mode.** A refine pass re-sweeps a window
   centred on the coarse pass's *own answer*, so it inherits whatever the
   coarse pass missed. On the self-test loop above there is nothing to centre
   on — at `dec 50` the resonance does not appear at all. Two-pass sharpens a
   feature you have already found; the problem is the one you have not.
2. **It optimises a cost that is not being paid.** The saving assumes runtime
   scales with AC point count. It does not — see below.

### Runtime

Measured on this design, one PVT corner (72 load/cap/ESR configurations, so
144 AC analyses plus 72 DC operating-point solves) at `-j 1`:

| `dec` | AC points per analysis | CPU time | vs `dec 50` |
|---|---|---|---|
| 50 | 551 | 72.1 s | 1.00× |
| 100 | 1101 | 79.5 s | 1.10× |
| 200 | 2201 | 84.1 s | 1.17× |
| **400** | **4401** | **92.3 s** | **1.28×** |

**8× the frequency points costs 1.28× the CPU**, because the cost is
dominated by the 72 DC operating-point solves and the model setup around
them, not by the AC points swept. That is what makes a global bump the cheap
option, and it is what makes the two-pass design's premise false.

CPU time rather than wall time because it is the load-independent quantity —
these measurements were taken on a machine shared with other simulation jobs,
where the same `dec 50` corner varied between 198 s and 390 s of *wall* time
for 72 s of CPU. The full 4536-point matrix at `dec 400` took
**`<FULL_RUN>`**.

## How the loop is measured

`design/ldo_core.sch` exposes `ERRAMP_OUT` and `PASS_GATE` as two separate,
internally-unconnected ports precisely so the loop can be broken there from a
testbench without editing the core. The deck instantiates the core with those
ports on distinct nodes and inserts a **Tian/Middlebrook dual injection**
network between them: a series voltage source (DC 0, so the operating point
stays the true closed-loop one) and a shunt current source.

```
Tv = -V(ERRAMP_OUT)/V(PASS_GATE)      voltage injection
Ti = -I_driver/I_load                 current injection
T  = (Tv*Ti - 1)/(Tv + Ti + 2)        the loop gain
```

Dual injection rather than plain series-voltage injection because the break
sits between a high-impedance driver — the error amp's class-A output stage,
`1/(gds_p+gds_n)` ≈ 9.3 MΩ at tt / 27 °C / 3.3 V / 25 mA — and a few pF of
pass-gate capacitance, so `Z_load ≫ Z_source`, the condition single-injection
accuracy depends on, fails from a few kHz upward: decades below where
crossover actually sits. `selftest.py`
demonstrates this quantitatively on a reference loop with a closed-form
answer: dual injection reproduces the analytic loop gain to < 1e-6 dB, while
single-injection is wrong by up to ~256 dB in the same band.

`T` so defined is positive real at DC for this negative-feedback loop, so
phase margin = `180° + ∠T` at the 0 dB crossing and gain margin = `-|T|dB` at
the first −180° crossing. Where the phase never reaches −180° in
0.01 Hz – 1 GHz, the gain margin is reported as `inf`: a loop that approaches
−180° from above never inverts, so no finite gain multiplier drives it to
`T = -1`.

## `resurgence_db` — the precondition on reading a Bode margin at all

A phase/gain margin read off a Bode plot is a stability test **only when
`T(s)` has no right-half-plane poles** — the standard precondition on the
Bode form of the Nyquist criterion. That is not a formality here:
`design/error_amp.sch` closes a *local* feedback loop inside the amplifier
(the `Rz`/`Cc` Miller network around the stage-2 driver and the class-AB gate
buffer) which stays closed when the LDO loop is broken at
`ERRAMP_OUT`/`PASS_GATE`, and
[`DR-0008`](../../spec/decision-records/DR-0008-loop-gain-rhp-pole-precondition.md)
records that the precondition did **not** hold for the amplifier as committed
at `b304bd5` — three loop-stability records were minted against a loop that
oscillates.

So every point of this sweep also reports:

| metric | definition | bar |
|---|---|---|
| `resurgence_db` | the largest `\|T\|` in dB **anywhere above the first (falling) 0 dB crossing** | **≤ 0 dB** |

The scan starts one AC-grid step (`10^(1/AC_DEC)`, see *Sweep resolution*
above) above the crossing, so the
crossing itself — where `|T|` is 0 dB by definition — is never reported as its
own resurgence. For a loop that rolls off monotonically through crossover
every remaining point is below unity, so the metric is negative *by
construction*; that is why the bar is `≤ 0 dB` with no engineering slack in
it, and why a value above it means the gain genuinely climbed back over unity
after having crossed down. Where that happens, the phase margin above is read
at a crossing that is not the last one.

This bar is reported and failed **separately** from the DR-0001 PM/GM
verdict — it appears as its own `resurgence_db` / `resurgence_result` column
pair in the matrix CSV and as its own section of the record, and it is
deliberately not folded into the `passes` property, because it is a different
claim against a criterion that is not yet ratified.

**It is necessary-but-not-sufficient evidence of a right-half-plane pole
pair**, and it does **not** replace [`sim/amp-selfosc/`](../amp-selfosc/),
which measures the oscillation directly in the time domain and remains the
load-bearing check per DR-0008:

- A well-damped but under-margined loop could in principle resurge above
  unity without any RHP pole pair, so a flagged point is a *prompt to run the
  time-domain bench*, not a verdict about pole locations.
- Equally, a clean `resurgence_db` does not license the PM/GM verdict on its
  own. It removes the signature DR-0008 traced (a crossover taken on the far
  side of a resonance the RHP pair has already rotated ≈ +180° through), not
  every way the precondition can break. A phase margin above 180°, for
  instance — the phase *leading* at crossover — is a separate tell that this
  bar does not flag.

The point of measuring it here is cost: it falls out of the AC sweep this
bench already runs, on every future compensation iteration, for free, whereas
`sim/amp-selfosc/` costs ~6 CPU-minutes **per PVT point**.

`selftest.py` validates the extraction against **three** loops with
closed-form answers: the monotonic one it has always used (which must **not**
flag — measured `−3.97 dB`); a second loop built with a lightly damped
Q = 20 resonance above its first crossing, placed *on* a grid point, whose
`+14.04 dB` analytic peak the metric must recover within 0.25 dB (this checks
the extraction's **arithmetic**); and a third, Q = 80, placed at the
worst-case sampling **offset**, which checks the extraction's **resolution** —
see *Sweep resolution* above.

## Load and output-network model

`I_load` is an **ideal DC current source** — the conservative LDO stability
model. A resistive load would put `1/g_load` in parallel with the output
pole and flatter the result. `0 mA` means no external load at all (only the
feedback divider's ~6 µA), per DR-0001. `C_eff` and `ESR` are the **derated
effective** values at the output pin, not nominal component values.

## Evidence

Records are append-only (`sim/README.md`): never edit or delete anything
under `records/`, `corners/` or `netlist-snapshots/`. A re-run mints a new
record-id; a correction references the record it supersedes via the record's
**Supersedes** field (`sweep.py --supersedes <record-id>`).

Each `corners/<record-id>/<corner-id>.log` carries one `ROW` line per
(load, cap, ESR) configuration; `records/<record-id>-matrix.csv` is the
machine-readable rollup of all points, and `records/<record-id>.md` is the
summary record with the worst point called out explicitly.

`ROW` lines are written `key=value`, not as bare positional fields, because a
failed `meas` (no such crossing in band) leaves its value **empty** — and an
empty positional field vanishes into the whitespace, so every field after it
is read as the wrong quantity. Records up to and including
`20260801-191742-84f67b8` were parsed positionally and 387 of their 3240 rows
had `f0_rising_hz` recorded as `f_180_hz` for exactly that reason, which is
why that record's multiple-0 dB-crossing note reports 14 points instead of
401. The driver now refuses a `ROW` line whose field list does not match the
deck's rather than absorbing it as a plausible number.

### PRECONDITION: this experiment's numbers are only a stability test when
### the loop gain has no right-half-plane poles

A Bode phase margin and gain margin are a valid stability test **only when
`T(s)` has no right-half-plane poles**, i.e. only when the forward path is
stable with the loop broken. This deck breaks the loop at
`ERRAMP_OUT`/`PASS_GATE`, which leaves the amplifier's **own** `Rz`/`Cc`
Miller loop (around `M2P` and the class-AB gate buffer) closed — so that
precondition is a property of `design/error_amp.sch`, not something this
deck can assume.

**It did not hold for records up to and including the design state
issue #55 (`BG`-steer, PR #62) landed** (issue #53): the amplifier oscillated
at ≈ 500 kHz at every PVT corner, and where the resulting right-half-plane
pole pair rotates the phase by ≈ +180°, this deck's `180 + phase` reports a
large positive "phase margin" at a crossing that sits *above* a resonance
where `|T|` had already climbed back over unity. The evidence and the
argument are `sim/amp-selfosc/records/` and
`spec/decision-records/DR-0008-loop-gain-rhp-pole-precondition.md`.

**It holds from `20260802-095235-c828e73` onward.** `design/error_amp.sch`
gained `Cf1`/`Cf2`, a Miller cap around `M2P` that splits the local loop's
two low poles (issue #53, `design/error_amp.md` §6.7). Measured on that
record: `resurgence_db` is negative at **all 3240 points** (worst −0.17 dB,
against a large fraction of the matrix resurging before), `sim/amp-openloop/`'s
`peak_excess_db` passes at 81 of 81, and `sim/amp-selfosc/`'s light rows sit
at 0.13–0.43 µV pk-pk at 45 of 45 (`sim/amp-selfosc/records/20260802-101239-c828e73.md`
— note this record required a testbench fix of its own: issue #55 exported
`error_amp`'s `BG` node as a port, which changed the hierarchical node name
this bench probes from `xdut.xerramp.bg` to `xdut.bg`; the stale probe was
silently returning "no such vector" at every corner until
`sim/amp-selfosc/testbench/tb.json` was updated). `sim/amp-selfosc/`'s
*heavy* rows still fail — but that is this deck's own 50 mA / 0.33 µF result
(worst PM −94.6°) showing up in the time domain, i.e. the two experiments
agree, rather than the amplifier's local loop hiding one from the other.

**So: do not cite a record here as evidence for DR-0001's stability row
unless the `sim/amp-selfosc/` record taken against the same `design/`
netlist shows a quiet loop at the load in question.** Everything in "Where
this stands" below is preserved as written, but the verdicts of records
before `20260802-095235-c828e73` are subject to this precondition —
including the "2160/2160 at 1–50 mA" reading of the pre-#53 head-of-chain
record, which DR-0008 argues is not a stability result, and which the first
record taken with the precondition satisfied reads as **293/2160 at 1–50 mA
(and 492/540 at 0.1 mA), 785/3240 overall**
(`spec/decision-records/DR-0009-shelf-corner-vs-crossover-frontier.md`).

### `res_ff`/`res_ss` — the resistor-corner axis (issue #54)

Every record through `20260802-095235-c828e73` held the `res_*` `.lib`
sections at typical throughout, varying only the MOS skew
(`tt`/`ff`/`ss`/`fs`/`sf`). That was a reasonable scope when the compensation
was a MIM cap and a nulling resistor whose absolute value barely entered the
result, but #51/#56's Type-II gain-shelf compensation made `Rz` — a
`ppolyf_u_1k` resistor — set both the shelf gain `A_plat = gm(MIN)·Rz` and the
shelf corner `f_z = 1/(2π·Rz·Cc)`, i.e. a first-order parameter of the
result. `sim/devchar/CONCLUSIONS.md` §2 puts `ppolyf_u_1k` process spread at
~40%, so leaving it at typical left that spread unverified.

`20260802-151515-2a08fce` closes that gap: `res_ff`/`res_ss` added to the
process axis (5 → 7 corners, 3240 → 4536 points), the same
`CORNERS="tt ff ss fs sf res_ff res_ss"` pattern
`sim/enable-shutdown/testbench/run.sh` already used. **Measured: the
resistor-corner axis introduces zero new failures** — grouped by the 648
non-process operating points, the 136 that pass at all 5 MOS corners also
pass at both `res_ff` and `res_ss`, and the MOS-only vs. resistor-corner pass
rates are identical to 4 significant figures (785/3240 = 314/1296 =
24.2284%). `res_ff`/`res_ss` do widen the matrix's already-failing tail
modestly (the single worst point in the matrix moves from a MOS corner,
`sf_-40c_2.97v` at PM −94.57°, to a resistor corner, `res_ss_-40c_2.97v` at
PM −97.29°, same 50 mA/0.33 µF/0.001 Ω configuration that fails regardless of
process corner) — see the record's *"Issue #54: does the resistor-corner axis
introduce a new failure?"* section for the full comparison, including the
caveat that this null result is conditional on the current 24%-passing
baseline and should be re-checked once the DR-0009-recommended architecture
change lands and the passing region is larger.

### The 0.1 mA column closes (issue #53)

`20260802-171044-db620a6` is the head record: the same 4536-point matrix,
measured against `design/error_amp.sch` with its Type-II gain shelf widened
(`Cf1`/`Cf2` 12 × 12 µm → 7 × 7 µm, with `M2P`/`Mbuf`/`Mbufb` gate areas cut
to keep the local loop's Miller-split pole above the raised shelf corner, and
`MTAIL` 6 µm → 6.6 µm). The shelf's upper corner turns out to be
`f_2 = 1/(2π·Rz·Cf)`, the same form as its lower corner
`f_z = 1/(2π·Rz·Cc)`, so the shelf is `Cc/Cf` wide and independent of every
bias current in the cell — which is what DR-0009's "`f_2` is set by Iq"
subsection got wrong, and what
`spec/decision-records/DR-0012-shelf-width-is-cc-over-cf.md` corrects.

| `I_load` | 0.33 µF | 1 µF | 4.7 µF | row | `…-2a08fce` |
|---|---|---|---|---|---|
| 0 mA | 13/252 | 0/252 | 0/252 | 13/756 | 0/756 |
| **0.1 mA** | **252/252** | **252/252** | **252/252** | **756/756** | 686/756 |
| 1 mA | 0/252 | 158/252 | 249/252 | 407/756 | 331/756 |
| 10 mA | 0/252 | 0/252 | 87/252 | 87/756 | 74/756 |
| 25 mA | 0/252 | 0/252 | 57/252 | 57/756 | 8/756 |
| 50 mA | 0/252 | 0/252 | 12/252 | 12/756 | 0/756 |
| **total** | | | | **1332/4536** | 1099/4536 |

The whole 0.1 mA column now clears both DR-0001 bars at all seven process
corners, worst PM 45.98° and worst GM 13.27 dB. The matrix as a whole is still
a **FAIL** (1332/4536) — 1–50 mA needs roughly another factor of nine in
`Cc/Cf`, which neither `Cf` (bounded below by the local loop's own
non-dominant pole) nor `Cc` (bounded above by the ratified PSRR row) can
supply, so that remains DR-0009's architecture change. Read the record's
*"Issue #53: the 0.1 mA column closes, and what it traded to close"* section
before reading the totals: 77 points outside the 0.1 mA column trade
PASS → FAIL against 310 the other way, 63 of them on gain margin alone, which
is the direct consequence of holding `|T|` up over a wider band.

Note that #54's null result on the resistor-corner axis was explicitly
recorded as *conditional on the then-current 24 %-passing baseline*. It
survives this record: the 0.1 mA column passes at `res_ff` and `res_ss` as
well as at the five MOS corners, and the matrix's worst point is still
`res_ss_27c_2.97v` at 50 mA / 0.33 µF / 1 mΩ.

### Where this stands

The current record is **`20260801-140530-d6d47f5`**, a **FAIL** against
DR-0001, but a substantially narrower one than the previous record: adding a
feedforward compensation zero (`Cff`, `design/ldo_core.sch`, issue #42)
improves the worst-corner phase margin from **−12.89°** to **−1.26°** and gain
margin from **−28.87 dB** to **−2.50 dB**, and raises passing points from
64/3240 to **150/3240**. It still does not clear the ≥ 45° / ≥ 10 dB bar. This
is the **real** loop — transistor-level `design/error_amp.sch` (untouched by
`Cff`) and the real `design/ldo_ilimit.sch` — so it is a property of this
compensation, not of a stand-in.

That does not contradict the amplifier's own records: the amplifier was sized
against the offset, PSRR and Iq budgets, and closing the LDO loop around it is
a separate requirement nothing has yet been sized against. Read the record's
*"Structure of the result"* and *"What this record asks of the next design
step"* before touching the compensation further — it documents, with the
empirical rescaling experiments that ruled other levers out, why a
feedforward-only fix cannot close the remaining gap: the amplifier's own
Miller-set pole and the load-dependent output pole are structurally many
decades below crossover at the DC loop gain the load-regulation/PSRR rows
require, for any on-chip-scale `XCc`/`XRz` in `design/error_amp.sch`.

It supersedes `20260801-050406-65416d2` (issue #10's original measurement,
worst PM −12.89°/GM −28.87 dB, 64/3240 passing), which in turn superseded
`20260801-002833-b8ce7d0`, measured against the *placeholder* error amplifier
PR #35 deleted. Both older records stay on disk — evidence here is
append-only — but the placeholder-amp record's numbers should never be cited:
the amplifier it describes no longer exists.

The failure is still broad rather than concentrated at one load point: the
a-priori worst configuration (light load, minimum C_eff, no ESR zero) fails
too, at 1.18°. See the record's *"Structure of the result"* for which axis
actually drives the verdict.
