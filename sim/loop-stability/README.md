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

The current record is **`20260801-050406-65416d2`**, a **FAIL** against
DR-0001: worst-corner phase margin **−12.89°** (bar: ≥ 45°) and gain margin
**−28.87 dB** (bar: ≥ 10 dB) at `ff / 27 °C / 3.30 V`, 50 mA, 0.33 µF, 1 mΩ,
with crossover at 293 kHz. 64 of 3240 points pass. This is the **real** loop —
transistor-level `design/error_amp.sch` and the real `design/ldo_ilimit.sch` —
so it is a property of this compensation, not of a stand-in.

That does not contradict the amplifier's own records: the amplifier was sized
against the offset, PSRR and Iq budgets, and closing the LDO loop around it is
a separate requirement nothing has yet been sized against. This record is the
first measurement of it. Read the record's *"What this record asks of the next
design step"* before touching the compensation.

It supersedes `20260801-002833-b8ce7d0`, which measured the same testbench
against the *placeholder* error amplifier that PR #35 deleted. That record
stays on disk — evidence here is append-only — but nothing should cite its
numbers: the amplifier they describe no longer exists.

The failure is broad rather than concentrated: the a-priori worst point
(light load, minimum C_eff, no ESR zero) fails too, at −0.09°. See the
record's *"Structure of the result"* for which axis actually drives the
verdict — the load axis runs the opposite way to the a-priori expectation.
