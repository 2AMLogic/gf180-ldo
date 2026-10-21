# DR-0039: the `ff_125c_3.30v` line-regulation failure is the soft-start injection element's settled residual, not loop gain — the 5 mV/V bound stays and DR-0035's VIN-referenced ceiling has to be re-landed over DR-0037

- **Status**: proposed
- **Date**: 2026-10-21
- **Decided by**: Builder (issue #473)

## Context

`sim/line-regulation` fails the ratified `Line reg < 5 mV/V` row at exactly one
of 27 points, `ff_125c_3.30v`: 8.28 / 8.28 mV/V at 1 mA / 50 mA, on a sane
physical branch (`iload_err_max_ua` ~ 7e-12), same in kind as the 8.23 mV/V of
`sim/line-regulation/records/20260924-055124-b88285c.md`. The slope is negative
(Vout falls 5.46 mV as Vin rises 2.97 -> 3.63 V) and identical at 1 mA and
50 mA, which rules out a pass-device output-impedance cause (that would scale
with load) and points at a load-independent term that appears only at the
lowest-Vt, hottest corner. Issue #473, split from #472.

## Diagnosis

All probes below are single-corner local `ngspice -b` runs of the harness-generated
`ff_125c_3.30v` deck with one edit each (current `main`, `98b2a46`); the
27-point grid was not re-run and no `sim/` record was minted.

1. **Removal bisection.** Vout at Vin = 2.97 / 3.63 V (1 mA):

   | DUT edit | Vout lo (V) | Vout hi (V) | slope |
   |---|---|---|---|
   | none | 1.799013 | 1.793549 | 8.28 mV/V |
   | `Xilimit` removed | 1.799013 | 1.793549 | 8.28 mV/V |
   | `XMpre_a_ss` or `XMpre_b_ss` removed | 1.799014 | 1.793550 | 8.28 mV/V |
   | `Xsoftstart` removed | 1.799086 | 1.798853 | 0.35 mV/V |
   | `XMgmo_ss` or `XMgmc_ss` removed | 1.799084 | 1.798850 | 0.35 mV/V |

   The error amplifier, current limit and pre-charge are innocent. The whole
   excess is the soft-start block's FB-injection output stage (`Mgmo_ss` ->
   `Mgmc_ss`, which sources into `FB`).
2. **The injected current.** `Mgmc_ss` drain current at Vin = 2.97 / 3.19 /
   3.41 / 3.63 V is 0.235 / 1.00 / 4.29 / 17.7 nA at ff/125 C (x4 per 0.22 V),
   against 0.002 / 0.012 / 0.052 / 0.235 nA at tt/125 C. FB is fed through
   `Rtop` = 300 kohm, so 17.7 nA is 5.3 mV of the observed 5.46 mV. Nothing
   else moves.
3. **Why it grows.** At ff/125 C and Vin = 2.97 / 3.63 V, `Mgmb_ss` supplies
   1.598 / 3.744 uA and the `Mgmm_ss` mirror of the A leg sinks 1.594 / 3.743 uA;
   the diode stack `Mgmr_ss`/`Mgmrc_ss` (and so `Mgmo_ss`/`Mgmc_ss`) carries
   the 0.24 / 17.7 nA difference. That stack sees `VIN - V(GMSUM)` =
   0.336 / 0.780 V across two diode-connected PMOS devices, i.e. 0.17 / 0.39 V
   each, in subthreshold at the lowest |Vtp| of the grid, so its current is
   exponential in Vin. `V(GMSUM)` tracks `V(GMSA)` = `V(SSR)` + |Vgs|, and
   `V(SSR)` is the ramp ceiling, which rises only 0.152 V (1.986 -> 2.138 V)
   while Vin rises 0.66 V. The hand-over residual is therefore a function of
   `VIN - V(SSR)`, and that is the term that grows.
4. **This is the quantity DR-0035 already targets.** DR-0035 (ratified, PR
   #323) references the ramp ceiling to `VIN` so the settled residual no longer
   carries a supply-referenced forward bias; its T8 gate measures exactly this
   (worst 109.9 -> 0.0328 nA/V). Applying open PR #344's version of the change
   to the pre-DR-0037 core and running the same probe gives Vout
   1.799074 -> 1.798839 V at ff/125 C, i.e. 0.36 mV/V (PASS).
5. **#344 cannot land as-is.** It is `CONFLICTING` with `main`: its
   `Fceil_ss` is a CCCS controlled by `Vbsense_ss`, which DR-0037 deleted
   (the patched netlist aborts: `unknown controlling source v.xdut.xsoftstart.vbsense_ss`).
   A real-device replacement for `Fceil_ss` is needed; DR-0037 is what forbids
   the idealised source.

## Alternatives measured and rejected

Each is the same ff/125 C, 1 mA, 2.97 -> 3.63 V probe; the soft-start check is
`sim/soft-start/testbench/run.sh` (single point, 1 uF / 100 mohm / 36 ohm,
`slope_vpms`, ff/125 C/3.63 V and tt/27 C/3.30 V; baseline 2.69 and 2.04).

- **Longer `Mgmm_ss`/`Mgmd_ss` (mirror CLM)**: L = 2 u (W = 8 u) 4.89 mV, L = 4 u
  (W = 16 u) 4.29 mV drop, from 5.46 mV. Not the mechanism.
- **Shrink the mirror ratio, `Mgmm_ss` W = 4 -> 3 u / 2 u**: line regulation
  passes (1.2 mV, 0.38 mV drop) but the ramp is lost: `slope_vpms` 3.61 / 3.56
  at W = 3 u and 51.8 / 75.9 at W = 2 u (`t_startup_ms` 0.07 at tt/27 C), inrush
  up from 287 to 394-410 mA. W = 5 u makes line regulation 23.6 mV worse. A
  ratio change moves the hand-over release point, so this is not a line-reg-only
  lever.
- **Widen the bound to 8.5 mV/V**: not available to an agent, and the failing
  corner is a defect of one cell rather than a property of the loop.

## Decision

1. **The `Line reg < 5 mV/V` bound is unchanged.** Nothing in the spec moves.
2. **The fix is DR-0035's VIN-referenced ramp ceiling, re-implemented over
   DR-0037's servo** (a real-device current copy of the servo branch current in
   place of `Fceil_ss`), not a new topology. A follow-on design issue carries it;
   it supersedes the conflicting #344 diff and must re-run `sim/line-regulation`
   (27 points), `sim/soft-start`, `sim/psrr-vs-freq` and the T1-T8 element gates.
3. This record is the evidence for why `sim/line-regulation` stays red at
   `ff_125c_3.30v` until then. `sim/` records are not edited.

## Consequences

- Issue #473 stays open until the follow-on lands and a 27-point
  `line-regulation` record shows `ff_125c_3.30v` under 5 mV/V at both loads.
- `sf_125c_3.30v` (2.92 mV/V, passing) has the same mechanism and the same
  fix; expect it to improve too. Re-check at 3.63 V, where headroom is smaller.
- #344 needs a rebase onto DR-0037 (or closing in favour of the follow-on); it
  is not mergeable today.
- Risk: the real-device ceiling reference adds a current-copy branch to a cell
  whose standing current is already budgeted (DR-0036); the follow-on has to show
  Iq is unchanged.
- Not done here: the full 27-point grid on any modified DUT (no `design/` change
  is made), and no soft-start grid; the probes above are single-corner evidence
  only.
