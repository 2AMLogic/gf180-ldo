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

## Model binning — `.options wnflag=1`, and why this deck pins it

gf180mcu's device models are binned, and the widest declared bin stops at
`wmax=100.001 µm` (`sm141064.ngspice`). This deck's pass device `XMpass` is
`W=2800u nf=40` — 70 µm per finger — so the bin it belongs in exists only if
ngspice divides `W` by `NF` when selecting a bin. Whether it does is not a
property of the netlist or the PDK: it is ngspice's `wnflag`, which defaults
to 1 only in HSPICE/Spectre compatibility mode and to 0 otherwise. On a host
without `wnflag=1` in `spinit`/`.spiceinit` — which includes every
fleet-provisioned builder host — this deck dies at parse time with
`could not find a valid modelname` (`--backend local`, issue #634); the
`klt`-built decks already pinned it (DR-0025 reached `compose_deck` and
`klt_batch.py`), which is why only this path broke.

The deck template therefore pins `.options wnflag=1` itself, right after
`.temp` and before the `.include` of the DUT netlist
(spec/decision-records/DR-0025-model-bin-selection-binds-on-per-finger-width.md,
issue #214). On a host that already sets the flag the card is inert — no
numeric change — so records taken before the card exist on `wnflag=1` hosts
remain valid (DR-0025 § Decision 4). The card is deliberately the deck's
first `.options` card: duplicates resolve earliest-wins, silently. The same
convention is documented at length in
`sim/soft-start-loop-gain/README.md`'s "Model binning" section; the other
four `tb_*.spice.in` decks are tracked in issue #607.

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

### What it changed on this design: nothing, and one thing

[`records/20260802-204343-e912fbd.md`](records/20260802-204343-e912fbd.md) is
the controlled A/B — same netlist, same grid, same deck, `AC_DEC` the only
variable — between the last `dec 50` record and the first `dec 400` one.

**No point of 4536 changes verdict**, on the DR-0001 bars or on the DR-0008
resurgence bar. Phase margin moves by at most 0.040° and crossover by at most
0.055 % anywhere in the matrix. The loop as compensated today has no feature
sharp enough for `dec 50` to have mangled — which was not knowable without
running it.

**One point of 4536 moves a gain margin**, and it is exactly the mechanism
this issue is about: at `ss_-40c_3.63v` / 0.1 mA / 4.7 µF / 1 mΩ, `dec 400`
finds a −180° crossing at **871 kHz** that `dec 50` stepped over completely,
reporting the next one at 2.42 MHz instead (GM 45.68 → 42.38 dB). A `dec 4000`
re-probe confirms the 871 kHz crossing to the printed digit, so `dec 400` is
converged and `dec 50` was wrong. Both readings clear the 10 dB bar by more
than 30 dB, so nothing about the verdict moves — but the mechanism is present
in this loop, not only in the constructed reference loop, and there is no
argument that it must always land somewhere this harmless.

One caveat that comparison also surfaced (**since fixed, issue #69 — see
*`resurgence_db`* below**): as originally defined, `resurgence_db` was not
comparable across records taken at different `AC_DEC`. Its scan started one
*grid step* above the crossing, so a finer grid sampled `|T|` closer to `f_0`
and reported a larger number for the same loop — it moved positive at all
4536 points, worst-in-matrix from −0.075 dB to −0.009 dB, with no physical
change whatever. The direction was safe (a monotone roll-off can never push
it above the bar at any resolution) and the finer grid was the better
estimator of the `sup |T|` it is trying to report, but the value was **not a
margin** and could not be read as one. This record and
`records/20260802-204343-e912fbd.md` §4 are left as written — they document
real, measured evidence of the bug the fix below removes — but the scan-start
definition they describe is no longer what the deck runs.

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
| `resurgence_db` reported at `dec 50` | **−0.79 dB** — a clean, confident **false PASS** |
| `resurgence_db` reported at `dec 400` | **+3.11 dB** — correctly **FAIL** |

(Figures measured with the fixed-5%-offset scan start, issue #69; the
resonance sits far enough above crossover that the offset's exact value does
not change which grid point dominates the max, so these numbers are within
noise of what the old grid-tied offset also reported here.)

The 0.79 dB residual at `dec 400` is the 0.84 dB analytic worst case above,
measured. The old default is not slightly off on this loop; it is 4.69 dB
off, on the wrong side of a bar that has no slack in it.

### `cph()`'s phase unwrap is *not* the problem

Issue #58 also asked whether `cph()` picks the wrong 360° branch across an
under-sampled resonance. The same self-test answers it directly: the
unwrapped phase far above the resonance reads **−269.97°** against a −270°
analytic asymptote at **both** `dec 50` and `dec 400`. The reason is
structural — a minimum-phase pole *pair* has 180° of total phase variation,
so no sampling of one can produce the > 180° sample-to-sample step `cph()`
unwraps on. (A pole pair adjacent to a *zero* pair could; that is a different
shape, and nothing in this loop's measured response has it.)

The design agrees. A mis-unwrap on one grid and not the other would show up
in `records/20260802-204343-e912fbd.md`'s `dec 50` → `dec 400` comparison as
a ≈ 360° phase-margin discrepancy; the largest discrepancy over all 4536
points is **0.040°**, and no point's phase margin lies outside ±180°. The
resolution-sensitive quantity in this extraction is the **magnitude**, not
the branch.

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
for 72 s of CPU.

**The full 4536-point matrix at `dec 400` costs ≈ 87 CPU-minutes**, measured
twice on `20260802-201346-e912fbd`'s branch: 5224 s and 5337 s of CPU for
1762 s and 2463 s of wall time respectively at `-j 14`, the wall-time spread
being other jobs on the same machine. Budget **≈ 30 minutes of wall time at
`-j 14` on an otherwise idle machine**, against the `~30 minutes at -j 28`
this README quoted for `dec 50` — i.e. the resolution change costs about a
factor of two in cores, not a factor of eight.

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

The scan starts a **fixed 5 % above the crossing** (`f_0 × 1.05`) rather than
one AC-grid step above it, so the crossing itself — where `|T|` is 0 dB by
definition — is never reported as its own resurgence. For a loop that rolls
off monotonically through crossover every remaining point is below unity, so
the metric is negative *by construction*; that is why the bar is `≤ 0 dB`
with no engineering slack in it, and why a value above it means the gain
genuinely climbed back over unity after having crossed down. Where that
happens, the phase margin above is read at a crossing that is not the last
one.

### Comparability across `AC_DEC` (issue #69)

The scan-start offset used to be one AC-grid step (`10^(1/AC_DEC)`), which
tied `resurgence_db`'s *value* to the sweep resolution even though the
quantity it reports — `sup |T|` over `(f_0, F_STOP]` — does not depend on
resolution at all: the *Sweep resolution* section's `dec 50` → `dec 400` A/B
moved `resurgence_db` at all 4536 matrix points by **+0.061…+2.362 dB**, with
phase margin and crossover essentially unmoved. The fixed 5 % offset above
removes that dependency: the threshold no longer moves with `AC_DEC`, only
which already-sampled grid point happens to sit just above it does. **5 %**
is chosen because it is close to the *old* `dec 50` grid step (`10^(1/50) ≈
4.71 %`, the resolution every historical record through
`20260802-171044-db620a6` was taken at — so this redefinition does not
retroactively widen or narrow the scan those records represent) and
comfortably above the *current* `dec 400` grid step (`10^(1/400) ≈ 0.577 %`),
so neither resolution this deck runs at today changes which points the scan
considers.

This does **not** make `resurgence_db` exactly resolution-independent — no
discrete sample of a continuous quantity can be — but it replaces a
*systematic* bias that scales with `AC_DEC` (the old formula) with a
*quantization* residual bounded by the grid step near a fixed threshold.
Measured on the real design (`tt`/27 °C/3.3 V, the full load × cap × ESR
axis, 72 points, `dec 50` vs `dec 400`, same netlist): **median 0.21 dB, max
0.95 dB** residual, `dec 400` reading less negative (closer to the bar) than
`dec 50` at every point compared, same direction as before but now bounded by
grid quantization rather than by `AC_DEC` itself — down from the old
formula's measured **+0.061…+2.362 dB**, a range taken over the full
4536-point matrix rather than this 72-point subset, but the same order of
magnitude smaller than that range's maximum. `selftest.py`'s monotonic
reference loop exercises the property directly: measured at both `dec 20` and
`dec 400`, `resurgence_db` must agree within a stated 1.75 dB budget (a
loop-specific number derived from that loop's own analytic near-crossing
slope, printed alongside the check).

**The DR-0008 verdict for the head record does not change.** The redefinition
moves the scan's start offset *later* on every point currently in a record at
`dec 400` (`10^(1/400) ≈ 0.577 %` → a fixed `5 %`), which can only make
`resurgence_db` more negative for a loop whose gain is still decaying in that
excluded band — the case for every point measured on this design so far
(worst-case phase margin there is ≈ 140°, decades from a resonance). The
single point closest to the bar in the current head record
(`20260802-201346-e912fbd`, `ff_125c_3.30v` / 1 mA / 4.7 µF / 0.5 Ω, the exact
point issue #69's "measured, not hypothetical" evidence cites) was
re-measured directly against this redefinition: `resurgence_db` moves from
`−0.0086 dB` to `−0.0712 dB` — still comfortably `≤ 0 dB`, with *more*
margin than before, not less. The head record's DR-0008 verdict was already
0 FAIL / 4536 (every point PASS on that bar); it stays 0 FAIL / 4536 under
the redefinition, and the mechanism above rules out any point flipping
PASS → FAIL for the same reason it does not flip at the worst one. A full
4536-point re-run under the new definition is future work for whoever next
runs the sweep (`resurgence_db` is a free byproduct of every sweep, same as
before) rather than a prerequisite of this fix.

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
see *Sweep resolution* above. The monotonic loop is also re-measured at a
**second** `AC_DEC` (400, alongside its historical dec 20) and the two
`resurgence_db` readings are asserted to agree within the stated tolerance —
the direct check of *Comparability across `AC_DEC`* above.

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

### The `f6eeac7` re-qualification: 7 borderline flips, none in the envelope (#737)

[`records/20261119-155956-0076e52.md`](records/20261119-155956-0076e52.md)
(issue #465) supersedes
[`records/20260923-132038-a992b52.md`](records/20260923-132038-a992b52.md),
and the point-by-point old-vs-new comparison lives in
[`records/20261119-155956-0076e52-delta.csv`](records/20261119-155956-0076e52-delta.csv)
(the record itself does not link it). Read that delta with one caveat the
records cannot state themselves: **this is not a same-DUT pair.** Three
things differ at once, and no run isolates any one of them:

- **DUT**: `a992b52` predates issue #320 / DR-0037 — its `ldo_ilimit`
  snapshot still biases through the idealized `Fbias` CCCS; `0076e52`'s
  carries the real VREF-forcing V-to-I servo (`XMconv`…`XMst`; no `Fbias`
  anywhere in the snapshot). This bench was not re-minted at #320, so **no
  post-servo baseline exists at `c6d73a3`**. `0076e52`'s provenance
  paragraph still names `Fbias` inside `ldo_ilimit` as a standing
  idealization — prose carried over from the record it supersedes; its own
  committed snapshot is the servo DUT. Both records stay as written
  (append-only); this note is the correction's home.
- **PDK**: `c6d73a3…` → `f6eeac7…` (models staged with every fleet job).
- **Toolchain/host**: one builder host's local ngspice-46 → the fleet's
  ngspice-47.

The amp-openloop re-qualification (#430,
`sim/amp-openloop/records/20261021-023703-7d3b2a0.md`) measured the same
class of residual on a pair whose DUT *was* identical — `pm_deg` up to
1.18° — and ran a single-corner PDK control that returned identical
crossings at `c6d73a3` and `f6eeac7`, leaving the ngspice build as the
likeliest source. That attribution does **not** transfer cleanly to this
pair: here the DUT moved too, so the residual below cannot be split between
the servo swap and the environment from this evidence alone.

**The movement**: over the common 4536-point matrix, |ΔPM| median 0.000°,
p99 1.28°, max 1.88° (`sf_125c_2.97v` / 1 mA / 0.33 µF / 0.5 Ω); |ΔGM| p99
0.51 dB, max 0.85 dB. DR-0008 resurgence is flagged at 0 points in both
records, worst movement 0.089 dB — inside the 1.75 dB comparability budget
(issue #69), so the resurgence verdicts are comparable, not drifted.

**Seven points change verdict — 4 PASS→FAIL, 3 FAIL→PASS (net −1:
2790 → 2789 of 4536).** Every one is a borderline crossing within 1.4° of
the 45° bar on both readings:

| corner | I_load | C_eff | ESR | PM old | PM new | flip |
|---|---|---|---|---|---|---|
| `ff_27c_3.30v` | 0.1 mA | 4.7 µF | 1 mΩ | 45.23 | 44.92 | PASS→FAIL |
| `fs_27c_3.30v` | 1 mA | 0.33 µF | 50 mΩ | 45.05 | 44.00 | PASS→FAIL |
| `sf_27c_2.97v` | 1 mA | 0.33 µF | 1 mΩ | 45.42 | 44.30 | PASS→FAIL |
| `ss_125c_3.63v` | 1 mA | 0.33 µF | 50 mΩ | 46.18 | 44.85 | PASS→FAIL |
| `ff_125c_3.30v` | 1 mA | 0.33 µF | 1 mΩ | 44.85 | 46.21 | FAIL→PASS |
| `ff_27c_2.97v` | 1 mA | 0.33 µF | 1 mΩ | 44.79 | 45.94 | FAIL→PASS |
| `sf_125c_3.30v` | 1 mA | 0.33 µF | 1 mΩ | 44.49 | 45.87 | FAIL→PASS |

All seven sit **outside** the DR-0018 envelope the CHARACTERIZATION
Stability row grades (0.1–50 mA, C_eff = 1 µF, ESR ≥ 200 mΩ) — six are
0.33 µF caps (four at 1 mΩ, two at 50 mΩ), one is 4.7 µF / 1 mΩ — and the
envelope verdict is unchanged at **630/630 pass** in both records (worst
PM 48.65° → 48.68°, worst GM 11.21 → 11.20 dB). The wider DR-0001 matrix
was FAIL before and after (1746 → 1747 failing of 4536); its res_ss
corners fail hard (PM down to −17°) and are untouched by this movement. So
nothing the Stability row grades moved, and no bar was moved to re-pass
anything — the flips are recorded here rather than chased as a regression.
The open question they do leave is the DUT-vs-environment split above,
which only a controlled A/B (servo DUT at `c6d73a3`, or `Fbias` DUT at
`f6eeac7`) could answer.

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
netlist shows a quiet loop at the load in question.** The verdicts of records
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
`CORNERS="tt ff ss fs sf res_ff res_ss"` seven-process set the harness's
PVT grid uses (`sim/harness/klt_batch.py`'s `LDO_PROCESS`, from
`sim/harness/corners.py`'s `CORNERS`). **Measured: the
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

`20260802-171044-db620a6` was the head record when this section was written.
It is now superseded by **`20260802-201346-e912fbd`**, which re-runs the same
4536-point matrix against the **same netlist** at `dec 400` (issue #58, see
*Sweep resolution* above). Every number in this section survives that
re-measurement unchanged — 1332/4536 overall, the whole 0.1 mA column
passing, the same worst point — so it is left as written; the per-point
comparison is `records/20260802-204343-e912fbd.md`.

`20260802-171044-db620a6`: the same 4536-point matrix,
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

This section deliberately does not name a "current record": name an id here
and it goes stale on the next re-run (that is exactly how it read before
issue #769 — three generations superseded). The head record is the **newest
record under `records/`**; walk each record's **Supersedes** field to trace
the chain back, and see § *Evidence* above for the latest re-qualification's
point-by-point comparison. Every sweep record in that chain to date is a
**FAIL** against DR-0001. The compensation steps each moved the matrix —
the `Cff` feedforward zero (issue #42, record `20260801-140530-d6d47f5`:
worst PM −1.26° / GM −2.50 dB, 150/3240 passing, up from −12.89° /
−28.87 dB and 64/3240 at `20260801-050406-65416d2`), then the Type-II
gain-shelf recompensation that closed the 0.1 mA column (above) — but none
has cleared the ≥ 45° / ≥ 10 dB bar at every point of its matrix. (Verdicts
from before `20260802-095235-c828e73` carry the DR-0008 precondition above.)

What every record from `20260801-050406-65416d2` onward measures is the
**real** loop — transistor-level `design/error_amp.sch` and the real
`design/ldo_ilimit.sch`, whose one standing idealization, the `Fbias` CCCS,
the #320 / DR-0037 servo swap removed from the newest records (§ *Evidence*
above) — so no behavioural amplifier stands in for anything: the failure is
a property of this compensation as designed, not of a stand-in. That does
not contradict the amplifier's own records: the amplifier was sized against
the offset, PSRR and Iq budgets, and closing the LDO loop around it is a
separate requirement nothing has yet been sized against. Before touching
the compensation further, read the head record's *"Structure of the
result"* and *"What this record asks of the next design step"* — that is
where each record hands its measured requirement to the compensation step,
and the earlier versions of it (e.g. `20260801-140530-d6d47f5`) document
the empirical rescaling experiments that ruled a feedforward-only fix out.

One citation rule is permanent: `20260801-002833-b8ce7d0` was measured
against the *placeholder* error amplifier PR #35 deleted, and its numbers
should never be cited — the amplifier it describes no longer exists. The
record itself stays on disk: evidence here is append-only.
