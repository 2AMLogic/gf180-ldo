# sim/soft-start — the ratified Startup row

This experiment owns the **Startup** row of `README.md`'s ratified target
specification, and nothing else:

> monotonic into any load 0–50 mA and any C_eff in the stability window;
> controlled ramp ≤ 1 V/ms, so inrush ≤ 5 mA at C_eff = 4.7 µF and startup at
> full rated load stays ≥ 10 mA below the current limit; inside ±2% within
> 3 ms of enable; overshoot ≤ +2% of the final value

It exists because issue #38 found that row failing on two of its clauses at
almost every corner (`sim/enable-shutdown/records/20260801-013308-164ab42.md`:
153–289 mA of peak supply current, up to +6.5% overshoot at 62 of 63 corners),
and because the design change that answers it — `design/ldo_softstart.sch` —
needs measurements that the pre-existing enable/shutdown bench was not built
to take.

```bash
./sim/soft-start/testbench/run.sh                      # full matrix, writes evidence
NO_RECORD=1 CORNERS=tt TEMPS=27 SUPPLIES=3.30 \
  CAPS=1u/0.1/36 EXTRA_CORNERS=tt EXTRA_TEMPS=27 \
  EXTRA_SUPPLIES=3.30 EXTRA_CAPS=4.7u/0.5/36 \
  ./sim/soft-start/testbench/run.sh                    # one point, writes nothing
```

## What it measures, and why each measurement is the one the row asks for

| Measurement | Clause it substantiates |
| --- | --- |
| `slope_vpms` | The **steady ramp rate**, taken as 1.0 V / (t(V_out = 1.4 V) − t(V_out = 0.4 V)). Two fixed output voltages well inside the ramp, so the number is the ramp itself and not either end transient. |
| `dvout_max` / `dvout_min` | The largest and smallest **instantaneous** dV_out/dt anywhere in the enable window. `dvout_max` is deliberately a harsher reading of "controlled ramp ≤ 1 V/ms" than `slope_vpms`: it also catches the loop acquiring at the bottom of the ramp and the hand-over to the main loop at the top. `dvout_min` going negative is a **non-monotonic** startup. |
| `icap_peak_ma` | **Inrush**, measured with a 0 V ammeter *in series with C_out*. |
| `isup_peak_ma` | Peak **supply** current, for the "stays ≥ 10 mA below the current limit" clause, against the 62.0 mA worst-corner limit measured in `sim/current-limit/records/`. |
| `t_startup_ms` | Enable edge → V_out = 1.764 V, i.e. the **±2% within 3 ms** clause. |
| `vout_max_en` | **Overshoot**, against the ratified +2% = 1.836 V. |
| `ssr_end` / `hg_end` | Hand-over sanity: the soft-start ramp node must finish **above** V_REF and the block's hold gate must finish at V_IN, or the soft-start block is still fighting the main loop after startup. Both halves are adjudicated in `summarize.py` — `ssr_end < 1.2 V`, and `hg_end` more than 0.2 V below V_IN. The 0.2 V is a *reporting* threshold, not a ratified bound (no spec line names this node); it sits well under the \|V_tp\| range in `sim/devchar/CONCLUSIONS.md` so that any point where the hold PMOS `Mhold_ss` is meaningfully out of cutoff gets named. The probe was `clg_end` (`Mclamp_ss`'s gate) up to and including record `20260906-125202-f1096c9`; issue #189 replaced the clamp comparator with FB injection, so the node is now `hg_end` (`Mhold_ss`/`Mhold_bg_ss`'s gate). Same invariant, same threshold, renamed node. |
| `ssr_off_tran` | The ramp capacitor must be **reset** by disable, or the next enable does not ramp. |

### Inrush is the capacitor current, not the supply current

The ratified row bounds inrush at 5 mA, and it is verified at the full rated
50 mA load. Total supply current at that load is ten times the bound by
construction, so reading "inrush" off `i(vin)` makes the clause unmeasurable
rather than merely hard. What the row is bounding is `C_eff · dV_out/dt` — the
charge the regulator has to push into the output capacitor to move the output —
so this bench meters exactly that, with `Vcmeas`, a 0 V source in series with
`Cout`. `isup_peak_ma` is reported alongside it and is what the *other* clause
in the same row (stay clear of the current limit) is written against.

## Axes

The full **7 × 3 × 3 = 63-point** PVT matrix (process × temperature × supply,
same corner set as `sim/enable-shutdown` and `sim/current-limit`, `bjt_ff` /
`bjt_ss` omitted because the design has no bipolar device) is run at the
nominal 1 µF / 100 mΩ output into the full rated 50 mA load.

DR-0001's **capacitor window** is then swept separately, because inrush and
overshoot are both capacitor-conditioned and the ratified inrush number is
quoted *at the top of that window*:

| C_eff | ESR | Load |
| --- | --- | --- |
| 0.33 µF | 1 mΩ | 50 mA |
| 0.33 µF | 500 mΩ | 50 mA |
| 4.7 µF | 1 mΩ | 50 mA |
| 4.7 µF | 500 mΩ | 50 mA |
| 1 µF | 100 mΩ | 0 mA (no external load) |

over the corner subset {tt, ff, ss, res_ff, res_ss} × {−40, 125 °C} ×
{2.97, 3.63 V} — the combinations that bracket the ramp rate, since the ramp
rate is what conditions everything else in the row. The ramp is set by
`V_REF / (R_ss_bias · C_ss)`, so its process spread is the `ppolyf_u_3k`
sheet corner (±25%) times the `cap_mim` corner (±10%); `res_ff` / `res_ss`
and the `ff` / `ss` corners (which move the resistor *and* the capacitor
together) are therefore the axis that matters, and both ends of it are in
the subset.

## Three drivers, one bench (issue #246)

`testbench/run.sh` is the PVT transient matrix and the only one that mints a
`netlist-snapshots/` entry. Two smaller drivers answer questions that are
adjudicated against the **same** Startup row but are not transient sweeps:

| driver | what it runs | what it is for |
|---|---|---|
| `testbench/run.sh` | the 163-point transient matrix | every clause of the ratified/proposed Startup row |
| `testbench/handover_t15.py` | the 63-corner DC hand-over transfer | targets **T1–T5** of `design/softstart_injection_compensation.md` §3 — the FB-injection element's own transfer |
| `testbench/ramp_ab.py` + `tb_ss_ramp_ab.spice.in` | a two-arm transient A/B, `V(SSR)` internal vs. forced by an ideal PWL on the promoted `SSR` port | the experiment `design/softstart_injection_compensation.md` §4 names: separating the injection element's transfer from the ramp node's own dynamics |

Neither of the two re-implements anything. `handover_t15.py` imports
`sim/soft-start-loop-gain/testbench/sweep.py`'s own hand-over deck and metric
code, and `ramp_ab.py` imports that experiment's `promote_ssr_port()`
(issue #196), so there is exactly one definition of "what `I_inj` is at this
ramp state" and one implementation of the `SSR` port promotion in this repo.
Both write under `corners/<record-id>-handover/` and
`corners/<record-id>-rampab/`, and both leave the record markdown to be
written by hand like every other bench here.

### Comparing two DUT netlists on one binary

`run.sh` accepts an `LDO_NETLIST` override so a same-host, same-session A/B
against a frozen `netlist-snapshots/<record-id>.spice` is reproducible.
Cross-record comparison is *not* a safe substitute: this bench's numbers are
large-signal transient peaks and records minted weeks apart can carry
different ngspice binaries. The override is **refused unless `NO_RECORD=1`**,
so an evidence record is still always the committed export:

```bash
NO_RECORD=1 LDO_NETLIST=sim/soft-start/netlist-snapshots/<id>.spice \
  CORNERS=tt TEMPS=27 SUPPLIES=3.30 CAPS=1u/0.1/36 \
  EXTRA_CORNERS= EXTRA_TEMPS= EXTRA_SUPPLIES= EXTRA_CAPS= \
  ./sim/soft-start/testbench/run.sh
```

An explicitly **empty** `EXTRA_*` means "no extra points" (the four use
`${VAR-default}`, not `${VAR:-default}`, precisely so that works), and two
invocations that land in the same second on the same commit are refused
rather than silently merged into one `corners/` directory.
`corners/20260918-190207-8a59d23-ab/` is a worked example, with its own
`README.md`.

`handover_t15.py` takes the same capability as `--dut-netlist PATH` (issue
#339), so an FB-injection candidate gets a **T1–T5** column in the same A/B
rather than only the transient one — the asymmetry `DR-0035` (measured
entirely through `sim/run_corners.py --dut-netlist`, so no T1–T5 column) and
`DR-0036` §4 (a T1–T5 column for the one candidate that happened to be
committed) both ran into. It takes an `ldo_core.spice`-shaped netlist and
applies the same `SSR` instrumentation `--variant device` applies to the
committed export, so the candidate is an edit of the *design* netlist, not of
a generated artefact. `--dut-netlist` is mutually exclusive with `--variant`
and is **refused unless `--no-write`** is also given, on the same reasoning as
`run.sh`'s `NO_RECORD=1`; under `--no-write` the per-corner logs, the DUT
netlist and both CSVs go to `sim/.work/soft-start/<record-id>-handover/out/`
instead of `corners/`, so an overridden run cannot leave anything behind that
looks like evidence:

```bash
mkdir -p sim/.work/candidate
cp design/netlist/ldo_core.spice sim/.work/candidate/ldo_core.spice
$EDITOR sim/.work/candidate/ldo_core.spice   # the candidate injection element

./sim/soft-start/testbench/handover_t15.py --no-write \
  --dut-netlist sim/.work/candidate/ldo_core.spice \
  --corners tt --temps 27 --supply-tol 0     # one point; omit for all 63
```

## Relationship to sim/enable-shutdown

`sim/enable-shutdown` owns the **Enable / shutdown** row — settled disabled
state, shutdown Iq, Vin→Vout leakage — which are DC operating points and are
unaffected by anything here. Issue #38 widened that bench's *transient* window
(400 µs → 8 ms) because the soft start moved the enable→active transition from
tens of microseconds to milliseconds, but left its `op` sections alone, so its
Iq and leakage numbers stay directly comparable across the change. The
per-clause Startup measurements and the capacitor-window axis live here.

## The known gap

The measured records under `records/` state, per corner, which clauses pass and
which do not. The short version, and the reason
`spec/decision-records/DR-0006` exists: the **steady ramp rate**, **inrush at
the top of the capacitor window**, **monotonicity** and the **current-limit
clearance** clauses are met; the **3 ms settling window** is not, at the slow
end of the ramp's own PVT spread, and **peak** dV_out/dt (as opposed to the
steady ramp rate) exceeds 1 V/ms in two short transients per startup. DR-0006
records what changes and what does not, with these measurements as its basis.

## One `corners/` directory here is a control arm, not a characterization

`corners/20260906-021024-2a7caec/` and `netlist-snapshots/20260906-021024-2a7caec.spice`
have **no matching file under `records/`**, and that is deliberate. They are the
**pre-DR-0015 control arm** of the bisection written up in
`records/20260906-012405-2a7caec.md` (issue #177): the same 163-point grid run
against `main`'s netlist with `Mrza`/`Rza` removed, so that the record can
attribute this bench's inrush / overshoot / peak-supply / settled-ripple
improvement to that device pair rather than infer it. That snapshot is
therefore **not** the current DUT and must not be read as a stale
characterization of the shipped design — the record that owns it says so, and
`sim/build_characterization_report.py` never looks at a snapshot whose
record-id has no record file.

## Bias acquisition of the DR-0037 servos (issue #352)

`testbench/bias_acq.py` characterizes how both DR-0037 self-biased V-to-I
servos acquire their bias: `ldo_ilimit` (`PB`/`VG`/`VX`, startup branch
`Msx`/`Msd`/`Mst`) and `ldo_softstart` (`PB_SS`/`VG_SS`/`VX_SS`,
`Msx_ss`/`Msd_ss`/`Mst_ss`). Both sit inside every `ldo_core` instance, so
each run measures both. It exists because the DC solve of the DR-0037
netlist needs gmin stepping, and a self-biased loop can have a zero-current
state that a converged operating point does not rule out.

```bash
# full matrix (7 scenarios x 63 corners) through klt sim -> batch fleet
KLT_CMD='uvx --from git+https://github.com/2AMLogic/klayout-tools.git@<sha> klt' \
  python3 sim/soft-start/testbench/bias_acq.py --record-id <id>
# one scenario, one corner, locally (debug; writes to --dest)
python3 sim/soft-start/testbench/bias_acq.py --record-id x --scenario forced \
  --only tt,27,3.30 --backend local --dest /tmp/bias-acq
# waveform reference corners (rawfiles -> decimated internal-node CSVs)
python3 sim/soft-start/testbench/bias_acq.py --record-id <id>-wave --waveforms \
  --axes tt+ss,27+-40,3.30+2.97 --scenario encycle,powerup,forced,vreflate,negctl
```

`KLT_CMD` is optional. It points the harness at a pinned klt client in a
throwaway environment and leaves the host install alone. Use it when the
host client is older than a fix you need. Issue #352 needed it because only
a client with klayout-tools#2827 reports *why* a fleet job failed.

### Scenarios

Each scenario is a separate `klt sim` job with a single `ldo_core`
instance. A solver diagnostic on a corner therefore belongs to that scenario
alone.

| scenario | stimulus | how the start state is imposed |
|---|---|---|
| `op` | DC, EN = VIN | `.meas dc` at the first point of a sweep of a dummy source that is not connected to the circuit (the fleet runner rejects `measurements[].expr`). The first DC point is the same initial solve as `op`. |
| `op_nodeset` | as `op`, with `.nodeset` PB = 3.0 V, VG = VX = 0 in both servos | a solver **hint** only. It shows which root Newton lands on from that guess. It is not evidence of physical startup. |
| `encycle` | VIN steady. EN low from t = 0, high at 20 us, then off for 100 us, 1 us and 10 us | the t = 0 operating point is the *disabled* circuit, not the intended enabled root |
| `powerup` | VIN 0 -> VIN over 100 us, EN tied to VIN | the t = 0 point is the unpowered, all-zero circuit |
| `forced` | EN = VIN throughout. Ideal switches clamp PB -> VIN, VG -> VSS and VX -> VSS in both servos until 20 us, then open in 10 ns | the t = 0 point is **pinned** to the physically motivated inactive state: PMOS mirror off, no conveyor drive, no `Rbias` current. After release only the circuit itself can leave that state. Switch Ron = 10 ohm, Roff = 1e13 ohm (<= 0.4 pA at 3.63 V). |
| `vreflate` | VIN and EN up. VREF = 0 until 20 us, then a 100 us ramp to 1.2 V | `Msx` (the startup inverter's PMOS) is supplied from VREF |
| `negctl` | `forced`, with `Mst`/`Mst_ss` gates tied to VSS | **negative control**: with the startup devices disabled, the test must report `INACTIVE`. If it did not, the `forced` result would mean nothing. |

Instrumentation is applied to a *copy* of the committed netlist. It inserts
0 V ammeters in series with each servo's `Mconv` drain, its `Mst` drain and
the top of `Rbias`/`Rss_bias`, plus the hold switches for `forced`/`negctl`.
Each edit must match exactly once, or the driver refuses to run. The copy
and its sha256 are kept beside the results.

### What is measured, and the declared tolerances

These values were fixed in `bias_acq.py` (`TOL`) before any matrix result
was read. **None of them is a spec limit.**

- **Acquisition time** `t_acq_us`: from the window edge to the first rising
  crossing of `VX = 0.99 * VREF`. A measurement-only guard source steps
  +10 V at the window end, so the `.meas` card always resolves. A crossing
  at the step means the servo was *not acquired*. It does not mean the
  measurement failed. If `VX` never leaves the 1 % band, `t_acq_us` is 0.
- **Settled error**: `VX` must stay within +/-1 % of `VREF` over the last
  40 us of the window.
- **Bias relative to `VREF/R`**: `(VX - BB) / VREF` at the window end. This
  equals `I(Mconv) / (VREF/R)` with R the same corner's own resistance,
  because the `Rbias` ammeter carries the `Mconv` current. It must be within
  1 %.
- **Startup turn-off**: `I(Mst)` at the window end must be <= 1 % of the
  servo's own bias current. The peak `I(Mst)` in the window is reported to
  show whether the branch engaged.
- **Intended EN = 0 shutdown versus enabled-inactive**: before each EN edge
  that follows a >= 100 us off-time, `I(Mconv)` must be <= 1 % of the bias
  acquired later in the same window. After a 1 us or 10 us off-time the
  pre-edge current is reported but not graded, because the servo is still
  discharging.
- **Time resolution**: `tran` maximum step 50 ns. Every stimulus edge is a
  PWL breakpoint, and the shortest event (the 1 us EN-off pulse) spans >= 20
  steps.

Verdicts per (corner, scenario, window, servo): `ACQUIRED`, `STARTUP_ON`
(bias acquired, startup branch still conducting), `UNSETTLED` (active but
outside tolerance), `INACTIVE` (bias < 10 % of `VREF/R` at the window end)
and `INVALID`. `INVALID` covers an errored corner or a missing or non-finite
value, and **never counts as acquired**. The solver path of the initial DC
solve (`direct` / `dyn_gmin` / `true_gmin` / `src_step` / `failed`) is read
from each corner's ngspice log and reported separately from the electrical
verdict. A gmin fallback is a property of the solve. It does not by itself
say anything about which state the circuit is in.

A finite sweep of corners and stimuli supports *observed* robustness under
the tested conditions. It does not prove that the operating point is
mathematically unique.
