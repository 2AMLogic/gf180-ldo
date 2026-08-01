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
| `ssr_end` / `clg_end` | Hand-over sanity: the soft-start ramp node must finish **above** V_REF and the clamp gate must finish at V_IN, or the soft-start block is still fighting the main loop after startup. |
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
