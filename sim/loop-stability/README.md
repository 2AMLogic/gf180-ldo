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
(the load/cap/ESR axes are swept *inside* each deck), about a minute on a
laptop.

Exit codes match `sim/run_corners.py`: `0` pass, `1` a stability check
failed, `2` a simulation failed, `3` an environment/usage problem.

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
sits between a ~1 MΩ driver impedance and a few pF of pass-gate capacitance,
so `Z_load ≫ Z_source` — the condition single-injection accuracy depends on —
fails in exactly the decade that decides the margins. `selftest.py`
demonstrates this quantitatively on a reference loop with a closed-form
answer: dual injection reproduces the analytic loop gain to < 1e-6 dB, while
single-injection is wrong by up to ~256 dB in the same band.

`T` so defined is positive real at DC for this negative-feedback loop, so
phase margin = `180° + ∠T` at the 0 dB crossing and gain margin = `-|T|dB` at
the first −180° crossing. Where the phase never reaches −180° in
0.01 Hz – 1 GHz, the gain margin is reported as `inf`: a loop that approaches
−180° from above never inverts, so no finite gain multiplier drives it to
`T = -1`.

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

### Where this stands

The first record, `20260801-002833-b8ce7d0`, is a **FAIL** against DR-0001:
worst-corner phase margin 2.07° (bar: ≥ 45°) at
`ff / −40 °C / 3.63 V`, 50 mA, 0.33 µF, 1 mΩ. That is a measurement of the
core with the *placeholder* error amplifier still in place — the loop's
crossover rises with load current until it walks into the fixed pole formed
by the placeholder's 1 MΩ output resistance and the pass-device gate
capacitance. Per #10's scope, fixing that is #9's (error amplifier) work,
not this testbench's; the record states the crossover frequencies the
amplifier's output pole has to clear. Read the record's *"What this record
asks of the next design step"* section before designing that amplifier.

Notably, the a-priori worst point — light load, minimum C_eff, no ESR zero —
*passes*; see the record's *"Structure of the result"* for why the load axis
reverses here.
