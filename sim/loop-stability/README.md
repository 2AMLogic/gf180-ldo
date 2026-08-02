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
    tb_tian_selftest.spice       a loop with an analytically known gain
    selftest.py                  asserts the extraction against that loop
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
```

`--explore` is DR-0001's recommended first pass: sweep `I_load × C_eff × ESR`
at `tt/27 °C/3.3 V` to find the worst triple before committing to the full
grid. The full run is 45 ngspice invocations covering 3240 loop-gain points
(the load/cap/ESR axes are swept *inside* each deck) — about 18 minutes at
`-j 10` on an M-series laptop against the transistor-level amplifier. Use
`-j` to match your core count.

Exit codes match `sim/run_corners.py`: `0` pass, `1` a stability check
failed, `2` a simulation failed, `3` an environment/usage problem. A run is
also refused outright (exit `2`) if any point's DC output is not within 10 %
of the regulation target: the ideal current-source load admits a second,
non-regulating DC solution, and a loop margin measured about it would be a
meaningless number that looks like a meaningful one. See the deck's
*"removing the non-physical DC branch"* comment.

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

The scan starts one AC-grid step (`10^(1/50)`) above the crossing, so the
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

`selftest.py` validates the extraction against two loops with closed-form
answers: the monotonic one it has always used (which must **not** flag —
measured `−3.97 dB`), and a second loop built with a lightly damped resonance
above its first crossing, whose `+14.04 dB` analytic peak the metric must
recover within 0.25 dB.

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

**Measured, it does not currently hold** (issue #53): the amplifier
oscillates at ≈ 500 kHz at every PVT corner, and where the resulting
right-half-plane pole pair rotates the phase by ≈ +180°, this deck's
`180 + phase` reports a large positive "phase margin" at a crossing that
sits *above* a resonance where `|T|` had already climbed back over unity.
The evidence and the argument are
`sim/amp-selfosc/records/` and
`spec/decision-records/DR-0008-loop-gain-rhp-pole-precondition.md`.

**So: do not cite a record here as evidence for DR-0001's stability row
unless the `sim/amp-selfosc/` record taken against the same `design/`
netlist passes.** Everything in "Where this stands" below is preserved as
written, but its verdicts are subject to this precondition — including the
"2160/2160 at 1–50 mA" reading of the head-of-chain record, which DR-0008
argues is not a stability result.

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
