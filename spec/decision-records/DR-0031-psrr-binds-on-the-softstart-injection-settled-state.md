# DR-0031: the ratified PSRR row binds on the soft-start injection element's *settled* state, and rectification-by-mirror-cutoff cannot meet it — negative result, plus the target it adds (T8)

- **Status**: proposed 2026-09-23 (issue #289 / this pull request) — per the
  2026-08-19 ratification-via-PR policy (2AMLogic/2am#357, the mechanism used
  for DR-0005/PR #137, DR-0006/PR #127, DR-0018/PR #199, DR-0023/PR #217,
  DR-0024/PR #228 and DR-0026/PR #258), the operator's review and approval of
  a ratifying pull request is the ratification act itself.
  **This record does not propose ratification of any topology.** Like
  DR-0009/DR-0010/DR-0011/DR-0029 it is filed as a **negative result**: it
  measures why the currently-ratified injection topology cannot meet a
  ratified `README.md` row, exhausts the one sizing lever
  `design/ldo_softstart.sch` itself names for this defect, and states the
  numeric target (T8) any replacement must be designed against — so the next
  attempt does not rediscover any of it.
  **This record changes no `design/` file.** Every prototype netlist below was
  built as a `--dut-netlist` swap under `sim/.work/` (git-ignored) and
  measured against the unmodified committed testbench; `git diff
  origin/main...HEAD -- design/` is empty.
  **No ratified threshold is changed, proposed to be changed, or waived.**
- **Date**: 2026-09-23
- **Decided by**: agent-builder (issue #289) — **not decided**; a topology
  with a measured blocking defect and no ratified replacement is not a
  decision for the operator to ratify yet.

## Context

`README.md`'s ratified Target-specification PSRR row (DR-0004 amendment A7)
reads **> 50 dB @ 1 kHz and > 20 dB @ 100 kHz, at `I_load` = 1 mA (binding —
light load) and at 50 mA, `C_eff` = 1 µF nominal**. Two committed records
claimed it PASS 45/45 — `sim/psrr-vs-freq/records/20260905-200801-3093ea1.md`
and `sim/psrr-vs-freq-50ma/records/20260905-200820-3093ea1.md`. Both were
**stale**, not wrong: they were taken on 2026-09-05, against the
`design/netlist/ldo_core.spice` that `2a7caecb` (#179 / DR-0021) left, and the
soft-start injection element has been rebuilt three times since.

Re-run against `main` at `a6c95f8`, the row **fails**:

- `sim/psrr-vs-freq/records/20260923-084323-a6c95f8.md` — **FAIL**,
  `psrr_1k_db` = **29.4268 dB** at `ff_125c_3.63v`, 47.062 dB at
  `ff_125c_3.30v`, 38.562 dB at `sf_125c_3.63v`; `fs_125c_3.63v` additionally
  lands on the sub-ground DC root (`dc_vout_v` = −64.75 V, `dc_iload_ma` = 0).
- `sim/psrr-vs-freq-50ma/records/20260923-084333-a6c95f8.md` — **FAIL**, the
  same three corners, `psrr_1k_db` = 29.4299 / 47.0703 / 38.5658 dB.

The 1 mA and 50 mA numbers agree to **0.004 dB**. The defect is therefore not
a function of load, which is the first clue about what it is.

`sim/CHARACTERIZATION.md` now reports the PSRR row as **FAIL, fresh** on the
strength of these two records; it previously reported PASS on the strength of
the stale pair.

## 1. Which commit introduced it — bisected

Bisected by swapping each historical `design/netlist/ldo_core.spice` into the
**unmodified** committed `sim/psrr-vs-freq` deck
(`python3 sim/run_corners.py psrr-vs-freq --no-write --corners ff sf fs
--temps 125 --supply 3.63 --supply-tol 0 --dut-netlist <path>`), same host,
same ngspice-46, same pinned `gf180mcuD @ c6d73a3`. Every `ldo_core.spice`
revision since the stale record's own netlist is covered — there are only
seven, and the netlist is byte-identical from `659eac2b` to `a6c95f8`.

| `ldo_core.spice` at | what landed | `ff_125c_3.63v` `psrr_1k_db` / `dc_vout_v` | `sf_125c_3.63v` | `fs_125c_3.63v` |
|---|---|---|---|---|
| `2a7caecb` (#179) | the stale record's own netlist | **61.4867** / 1.79885 | 59.1712 / 1.79886 | 65.757 / 1.79911 |
| `42434e41` (#188) | `Rz_ss` nulling resistor | 61.4867 / 1.79885 | 59.1712 / 1.79886 | 65.757 / 1.79911 |
| `d3cb1172` (#192) | FB injection via ideal `Binj_ss` | 61.4655 / 1.79885 | 59.1565 / 1.79886 | 65.7866 / 1.79911 |
| `dce8d731` (#195) | **device-level transconductor, uncascoded** | **2.48909** / 1.56864 | 3.77987 / 1.65875 | 48.6986 / 1.79888 |
| `60785b1d` (#223) | DR-0024 ramp resize | 2.96389 / 1.56864 | 4.57895 / 1.65875 | 49.5306 / 1.79888 |
| `8fff1681` (#233) | **revert to `Binj_ss`** | 61.4705 / 1.79885 | 59.1599 / 1.79886 | 65.7863 / 1.79911 |
| `659eac2b` (#250) | **DR-0023 cascoded mirror** | **29.4268** / 1.79358 | 38.562 / 1.79722 | 0.00126 / −64.75 |
| `a6c95f8` (`main`) | byte-identical to `659eac2b` | 29.4268 / 1.79358 | 38.562 / 1.79722 | 0.00126 / −64.75 |

Read as one line: **the regression was introduced by `dce8d731` (#195), fully
removed by `8fff1681` (#233)'s revert, and reintroduced — 27 dB smaller, but
still 20.6 dB under the ratified row — by `659eac2b` (#250), the PR that
implemented DR-0023.** DR-0023's cascode did exactly what DR-0023 said it
would (the settled output error at this corner goes from −230.2 mV to −5.27 mV);
it did not restore PSRR, because the defect PSRR sees is not the one the
cascode fixes. §3 is why.

## 2. What the defect is, measured

### 2.1 It is the injection element's *small-signal* path into `FB`, and nothing else

The discriminator is a **DC-preserving AC-open** — the same instrument
`design/softstart_injection_compensation.md` §1 used as `acopen-fb-inj`.
`Mgmc_ss`'s drain is moved off `FB` onto a new node and reconnected through a
1 GH inductor: a short at DC (the operating point is bit-identical — see the
`dc_vout_v` column) and an open at 1 kHz.

| variant (full 45-corner grid) | worst `psrr_1k_db` | `dc_vout_v` at `ff_125c_3.63v` | verdict |
|---|---|---|---|
| `main` as committed | **29.4268 dB** | 1.79358 | **FAIL** |
| `Mgmc_ss` drain AC-opened from `FB` | **62.3113 dB** | **1.79358** (unchanged) | **PASS 45/45** |
| `Mgmc_ss` deleted outright | 59.1599 dB | 1.79885 | PASS 45/45 |

Three facts follow, and all three are load-bearing:

1. **The rest of the design meets the ratified row with 12.3 dB of margin.**
   With the injection element's AC path to `FB` cut and *nothing else
   changed*, the 1 mA grid passes 45/45 at ≥ 62.31 dB. The row is not
   unachievable; this one element's admittance is the entire deficit.
2. **The deficit is purely small-signal.** The AC-open leaves the operating
   point bit-identical (1.79358 V, the same −5.27 mV settled error), and PSRR
   still recovers by 32.9 dB. So it is not the settled DC error that costs the
   row — it is the *derivative* of the residual injection with respect to
   `VIN`.
3. **Deleting the element reproduces the pre-injection design exactly.**
   59.1599 / 61.4705 dB matches `8fff1681` and `2a7caecb` to four digits,
   which is the cross-check that the AC-open is not itself an artefact.

The `fs_125c_3.63v` sub-ground root is downstream of the same defect: it
appears only on the committed netlist and disappears (65.23 … 65.79 dB,
`dc_vout_v` = 1.7991) in **every** variant below that reduces the settled
residual. It is nonetheless a second, separable harness-robustness question of
the #40/#46 class and is filed as **issue #304** rather than claimed here.

### 2.2 The mechanism, with the arithmetic closed

Operating point at `ff_125c_3.63v`, read from the committed deck with a 0 V
ammeter inserted in `Mgmc_ss`'s drain (`.op`, `@m...[id]`, `.ac` node
magnitudes at 1 kHz with the deck's own 1 V AC on `VIN`):

| quantity | measured |
|---|---|
| `V(VIN)` / `V(SSR)` / `V(GMSA)` / `V(GMSB)` / `V(GMSUM)` / `V(GMRM)` / `V(GMOD)` / `V(FB)` | 3.63 / 2.13907 / 2.93376 / 2.88175 / 2.85078 / 3.24039 / 3.23780 / 1.19924 V |
| `I(Mgma_ss)` / `I(Mgmb_ss)` (the two degenerated branches) | 3.48119 / 3.74126 µA |
| `I(Mgmr_ss)` = `I(Mgmc_ss)` (settled residual into `FB`) | **17.568 nA** |
| `Mgmc_ss`: \|V_gs\| / \|V_th\| / g_m / g_ds | 0.38702 / 0.56255 V / **0.31608 µS** / 0.378 nS |
| 1 kHz AC, per volt on `VIN`: \|v(GMOD)\| / \|v(GMSUM)\| / \|v(GMOD) − v(GMSUM)\| | 0.65287 / 0.30660 / **0.34692 V/V** |

**DC check.** 17.568 nA × `Rtop` (300 kΩ) = 5.27 mV. The measured settled
error is 1.79885 − 1.79358 = **5.27 mV**. Exact.

**AC check.** `Mgmc_ss` is the mirror's cascode output device, drain on `FB`,
gate on `GMSUM`, source on `GMOD`. `GMOD` rides on `VIN` (0.653 V/V) because
it is `Mgmo_ss`'s drain; `GMSUM` does **not** (0.307 V/V) because it is set by
the ground-referenced comparator on (`SSR`, `VREF`). So a supply ripple
modulates the injection device's own \|V_gs\| by **0.347 V per volt of
`VIN`**, and it is in weak inversion, where that is exponential:

```
di_inj/dVIN = g_m * 0.34692  +  g_ds * 0.65287
            = 109.65 nA/V    +  0.25 nA/V      =  109.9 nA/V
dVOUT/dVIN  = Rtop * di_inj/dVIN = 300 kOhm * 109.9 nA/V = 0.03297
PSRR        = -20*log10(0.03297) = 29.64 dB
```

Measured: **29.4268 dB**. The chain closes to **0.22 dB**. Inverting the
measurement instead of the model gives `di_inj/dVIN` = 10^(−29.4268/20)/300 kΩ
= **112.5 nA/V**.

### 2.3 Why the mirror does not actually cut off, and why it is supply-driven

`design/ldo_softstart.sch` and DR-0023 both describe the element as
"rectifying by construction": for `V(SSR) > VREF`, `Mgma_ss`'s branch falls
below `Mgmb_ss`'s, the reference stack `Mgmr_ss`/`Mgmrc_ss` would have to
source negative current, and cuts off. The measurement says it does not, and
says why:

- `V(GMSUM)` can only rise to the point where the pull-up branch delivers the
  mirrored `I_A`. Measured: `V(GMSB)` = 2.88175 V, `V(GMSUM)` = 2.85078 V —
  `Mgmb_ss` sits with \|V_ds\| = **31 mV**, i.e. deep in triode. The ceiling
  is arithmetic: `I_B`·`Rgm` + \|V_ds,triode\| = 3.74126 µA × 200 kΩ +
  0.031 V = **0.7793 V**, against `VIN` − `V(GMSUM)` = **0.77922 V**.
- So the two-high diode stack `Mgmr_ss`/`Mgmrc_ss` is left standing at
  **0.78 V of forward bias** — under a `pfet_03v3` threshold (0.563 V per
  device would be 1.13 V for the pair), but in weak inversion at 125 °C that
  is 17.6 nA, not zero. **Rectification-by-cutoff rectifies the sign of the
  argument; it does not produce an off state.**
- That 0.78 V is **supply-referenced**: `I_A`·`Rgm` ≈ `VIN` − `V(SSR)` −
  \|V_sg,A\|, and `Mtop_ss` clamps `SSR` to a ceiling referenced to **`VREF`**,
  not to `VIN`. Every volt of supply therefore adds ≈ 0.35 V of forward bias
  to a stack whose current is exponential in it. That is the whole defect, and
  it is why the failing corners are exactly the hot, fast, **high-supply**
  ones and why the failure is invisible to `sim/psrr-dc` (still PASS 81/81 —
  the amplifier's 1 kHz term is intact) and to `sim/soft-start` (which grades
  the *ramp*, not `dPSRR/dVIN` at the settled point).

The same law, confirmed independently by the §4 sweep: raising `V(SSR)` by
0.2619 V (2.13907 → 2.40098 V) takes `VIN` − `V(GMSUM)` from 0.77922 V to
0.55132 V and the residual from 17.568 nA to 2.049 nA. Inverting,
`2·n·V_T` = 0.22790/ln(8.574) = **0.1061 V**, i.e. `n` = **1.55** at 125 °C —
textbook weak inversion, on both legs of the stack, and the constant §4 and
§5 use to convert volts of headroom into decibels of PSRR.

## 3. Why DR-0023's cascode could not have fixed this

DR-0023 diagnosed and fixed a **drain**-voltage mismatch on the output device
(`Mgmo_ss`'s \|V_ds\| = `VIN` − 1.2 V against `Mgmr_ss`'s \|V_ds\| = \|V_gs\|).
It delivered: settled output error −141.26 mV → −1.78 mV worst corner
(DR-0026 §Context), and here −230.2 mV → −5.27 mV at `ff_125c_3.63v`
(§1's `dc_vout_v` column: 1.56864 V → 1.79358 V against a 1.79885 V
no-injection baseline).

The supply modulation PSRR sees arrives on the **gate** side, upstream of
anything a cascode controls: the mirror faithfully copies a *reference current
whose own supply slope is enormous*, because that reference is the residual of
two ≈ 3.7 µA branches that each carry ≈ 1/`Rgm` = 5 µA/V of supply
sensitivity. A cascode improves fidelity of the copy; fidelity is exactly the
wrong property when the thing being copied is the error.

This is consistent with, and sharpens, DR-0026's decomposition: DR-0026's
**E2** ("soft rectification near `VREF`", co-located with T1's residual and
T4's delayed release, growing monotonically with supply) is the same
phenomenon. What this record adds is that **E2 is not only an accuracy
nuisance — it is a ratified-row failure**, and that DR-0026's own premise
under "Against the ratified ±2 % accuracy row" — *"the element rectifies off
in the settled state … so the servo is not conducting when that row is
measured"* — is falsified as a general statement: the element does not rectify
off, and what it leaves behind costs 32.9 dB of PSRR.

## 4. The one sizing lever this file names is exhausted, and still 4.1 dB short

`design/ldo_softstart.sch` already names the lever for exactly this defect —
*"`Mtop_ss`'s ramp ceiling (raising it, via L, to buy the separate
settled-leakage margin below) … `Mtop_ss` only matters near handover, ~ms into
the ramp, so it is orthogonal"*. §2.3 says why it should work: a higher
`V(SSR)` at settled is a smaller `I_A`, a higher `V(GMSUM)`, and exponentially
less residual. It does work, monotonically — and it runs out.

| `Mtop_ss` | `V(SSR)` settled | `I(Mgma_ss)` | residual `I_inj` | `ff_125c_3.63v` `psrr_1k_db` | `sf_125c_3.63v` |
|---|---|---|---|---|---|
| `L=2u W=1u` (as built) | 2.13907 V | 3.4812 µA | 17.568 nA | **29.4268 dB** | 38.562 dB |
| `L=8u W=1u` | — | — | — | 34.2003 dB | 43.155 dB |
| `L=20u W=1u` | — | — | — | 37.1947 dB | 45.7747 dB |
| `L=50u W=1u` | — | — | — | 40.6800 dB | 48.5429 dB |
| `L=50u W=0.22u` (**PDK extreme**) | 2.40098 V | 2.4136 µA | **2.049 nA** | **45.8851 dB** | 52.083 dB |
| ratified row | | | | **≥ 50 dB** | ≥ 50 dB |

`L = 50 µm` and `W = 0.22 µm` are not a sizing preference, they are the
**PDK's own model-bin extremes** for `pfet_03v3` in `gf180mcuD`
(`sm141064.ngspice`: `lmax = 5.0001e-05`, `wmin = 2.2e-07`). `L = 200u` is
outside every bin and ngspice refuses the deck outright — *"could not find a
valid modelname"* — rather than clamping. So the lever cannot be pushed
further **in this PDK at all**, and at its extreme the binding corner still
reads 45.885 dB: **4.115 dB short**, with the whole grid's other 44 corners
already passing.

Expressed as what remains to be found: at the extreme the supply slope is
10^(−45.885/20)/300 kΩ = **16.9 nA/V**, against the 10.5 nA/V §5 derives. A
further factor of 1.61 is 0.106 V × ln(1.61) = **51 mV** more of `V(SSR)`
headroom that this device cannot deliver.

Three further sizing levers were closed by inspection rather than swept, and
the reasoning is recorded so it is not re-derived:

- **`Rgma_ss`/`Rgmb_ss` (200 kΩ)** — sets the ratified transconductance
  target T3 (−5.00 µA/V = 1.5/`Rtop`) directly, and the two must match for
  T2's `VREF`/`Rgm` = 6.00 µA offset to be supply-independent. Not free.
- **Shrinking the four mirror devices** (`Mgmr_ss`/`Mgmrc_ss`/`Mgmo_ss`/
  `Mgmc_ss`, `W=4u L=1u`) scales the residual with `W`, but the on-state must
  still carry 6.00 µA through a **two-high** stack inside `VIN` − `V(FB)` =
  1.77 V at minimum supply, against a measured \|V_gs\| of 0.82 – 0.96 V per
  device (`design/softstart_injection_compensation.md` §2). Halving `W` buys
  ≈ 6 dB and, on a square-law estimate of the overdrive, needs ≈ 1.9 V of the
  1.77 V available — so the lever is headroom-closed at roughly the point it
  first becomes worth having. Not swept; stated as the reason it was not.
- **Scaling the mirror ratio** N:1 requires `Rgm`·N = 200 kΩ to hold T3, i.e.
  N× the branch current — 28 µA per branch at N = 8, against a ratified
  < 30 µA Iq row with 1.29 µA of headroom (DR-0026). Closed on Iq.

## 5. The target this adds: T8

`design/softstart_injection_compensation.md` §3 (R3) defines T1–T7 for any
injection element. **T1 does not imply what PSRR needs, and this is the
central finding of this record.** T1 bounds the settled residual's
*magnitude* at ≤ 50 nA; at `ff_125c_3.63v` the measured residual is
**17.57 nA — inside T1 — and the ratified PSRR row fails by 20.6 dB at the
same operating point**. A magnitude bound says nothing about a weak-inversion
residual's supply slope, because `d(ln I)/dVIN` there is set by the bias
arrangement, not by `I`.

**T8 (proposed addition to `design/softstart_injection_compensation.md` §3,
to be made by the implementing pull request, not by this record):**

> **T8** — `|dI_inj/dVIN| ≤ 10.5 nA/V` at the settled operating point, at
> every PVT corner of `sim/psrr-vs-freq`'s grid.
>
> Derivation: the ratified row is ≥ 50 dB at 1 kHz, i.e.
> `|dVOUT/dVIN| ≤ 10^(-50/20)` = 3.162e-3. The injection residual reaches
> `VOUT` through `Rtop` = 300 kΩ (KCL at `FB` with the loop holding
> `FB` = `VREF`: `VOUT` = 1.8 V − `I_inj`·`Rtop`, in which `Rbot` cancels).
> So `|dI_inj/dVIN| ≤ 3.162e-3 / 300 kΩ` = **10.5 nA/V**.
>
> Where the present element sits: **112.5 nA/V** at `ff_125c_3.63v`
> (10.7× over), **16.9 nA/V** with `Mtop_ss` at the PDK's sizing extreme
> (1.61× over).
>
> The bench that grades it is `sim/psrr-vs-freq` (and its 50 mA sibling),
> **not** `sim/soft-start` or `sim/soft-start-loop-gain` — neither of which
> measures a supply derivative at the settled point, which is why this
> failure survived three rebuilds of the element with all of their evidence
> green.

## 6. What is proposed instead

Stated as directions with their measured constraints, not as a topology for
ratification — none has been prototyped to a full grid, and DR-0029's lesson
is that a soft-start change that looks right at sampled corners can fail at an
unchecked extreme.

1. **Reference the ramp ceiling to `VIN` instead of to `VREF`** (the direction
   §2.3's arithmetic points at). The forward bias left on the mirror stack at
   settled is `VIN` − `V(SSR)` − \|V_sg,A\|; `Mtop_ss` fixes `V(SSR)` a
   constant height *above `VREF`*, so that bias — and therefore the residual
   and its supply slope — grows one-for-one with supply. If `SSR` instead
   settled a fixed headroom *below `VIN`*, `V(GMSUM)` would track `VIN`, the
   stack would sit at a constant small forward bias, and `dI_inj/dVIN` would
   stop being the dominant term by construction rather than by margin.
   **Constraints it must respect**: the ceiling must stay above `VREF` at
   every corner (DR-0023's rectification event is `V(SSR)` crossing `VREF`)
   and below `VIN_min` (`design/ldo_softstart.sch`: "so nothing floats"), and
   `Mtop_ss` must stay a cutoff device below `VREF` so it does not bend the
   part of the ramp T3/T4 grade. No such `VIN`-referenced node exists in the
   cell today; creating one is the work.
2. **Hard-disconnect `Mgmc_ss`'s drain from `FB` after hand-over.** §2.1
   measures the upper bound this would reach: 45/45 at ≥ 62.31 dB. It is
   **blocked on a gating signal that does not exist**: the release point
   `V(SSR)` spans 1.200 – 2.025 V over PVT (DR-0026 T4) while the settled
   ceiling is as low as 1.53 V (`design/ldo_softstart.sch`), so no fixed
   `V(SSR)` threshold separates "released" from "still ramping" — this is
   issue #259's constraint 3, restated from the other side. `HG` is high
   ~100 µs after the enable edge, an order of magnitude before hand-over, so
   it cannot serve either.
3. **DR-0026's local servo, with T8 added to its acceptance set.** DR-0026
   (proposed, not implemented) already names E2 — holding `Mgmb_ss` in
   saturation across PVT — as "a second, separable requirement of the same
   decision". E2 *is* this defect. This record's contribution to that work is
   T8, the bench that grades it, and the arithmetic in §2.2/§2.3 that says
   what the servo has to achieve at the settled point rather than only on the
   ramp. It also flags that DR-0026's E2 requirement as literally worded
   (*"`GMSUM` stays below `VREF` + \|V_tp\|"*) moves `V(GMSUM)` **down**,
   which §2.3's law says increases the residual — so E2's requirement needs
   restating in terms of `VIN` − `V(GMSUM)`, not of `V(GMSUM)` alone, before
   it is implemented.
4. **Not available: reverting to `Binj_ss`.** It measures 61.47 dB
   (§1, `8fff1681`) and is a behavioural source, not a circuit. #233 already
   used that revert once as an interim and #246 replaced it.
5. **Not available: relaxing the row.** `CLAUDE.md` forbids it, and §2.1
   removes the premise for it — the design meets the row at ≥ 62.31 dB with
   this element's AC path cut and nothing else changed.

## 7. Cross-consequence: PR #267 / DR-0028 moves this the wrong way

Open PR #267 proposes `DR-0028`, gating the transconductor's branch supply
through `Mgmg_ss`/`Rgmg_ss` (both degeneration resistors move from `VIN` to a
new `VING` node) to recover ~5 µA of the Iq adder issue #259 targets. Measured
here, on that PR's own `design/netlist/ldo_core.spice`, same deck and same
probe corners:

| | `ff_125c_3.63v` | `sf_125c_3.63v` | `fs_125c_3.63v` |
|---|---|---|---|
| `main` (`a6c95f8`) | 29.4268 dB / 1.79358 V | 38.562 dB / 1.79722 V | (sub-ground root) |
| PR #267 head | **24.2267 dB** / 1.78834 V | **31.4624 dB** / 1.79475 V | 65.2313 dB / 1.7991 V |

**−5.2 dB and −7.1 dB at the two binding corners**, with the settled error
worsening in step (−5.27 mV → −10.51 mV at `ff_125c_3.63v`). §2.3 predicts it: interposing a
device between `VIN` and the branches puts `VING` *below* `VIN`, which adds
(`VIN` − `VING`) to the forward bias already standing across the mirror's
reference stack. This is not an argument against recovering the Iq adder; it
is a constraint on how, and it is stated here because PR #267 predates this
measurement and its own evidence base (`sim/quiescent-current`,
`sim/soft-start`) contains no bench that would have shown it. Filed as
**issue #303** against #259/PR #267 rather than asserted as a decision here.

## Consequences

- **The ratified PSRR row is FAIL on `main`** and `sim/CHARACTERIZATION.md`
  now says so, on two fresh records. Nothing in this record changes that; it
  explains it and bounds it.
- **T8 joins T1–T7** as an acceptance target for any injection element, and
  `sim/psrr-vs-freq` joins `sim/soft-start`/`sim/soft-start-loop-gain`/
  `sim/startup`/`sim/quiescent-current` as a bench that must be re-run by any
  pull request that touches `design/ldo_softstart.sch`'s injection path. The
  `design/softstart_injection_compensation.md` §3 edit that records T8 there
  belongs to the implementing pull request, per DR-0026's own precedent of
  not editing `design/` from a proposing record.
- **Issue #289 closes on this record**, which is the branch its acceptance
  criteria name ("*or a decision record explains why the ratified row cannot
  be met and what is proposed instead*"). The design work §6 names is filed
  as **issue #302**, §7's cross-consequence as **issue #303**, and §2.1's
  sub-ground root as **issue #304**, rather than left implicit.
- **No `design/` file changes** as a result of this record.

## Related

- Issue #289 — this record's origin.
- DR-0023 — ratified the cascoded mirror; §3 is why its fix and this defect
  are orthogonal, not the same thing measured twice.
- DR-0026 (proposed) — E1/E2 decomposition; E2 is this defect, and §6.3 states
  what T8 adds to it and where its E2 wording needs correcting.
- DR-0029 — the branch-gating negative result; §7's measurement is a second,
  independent constraint on the same mechanism DR-0028/PR #267 proposes.
- DR-0021 — the record whose netlist (`2a7caecb`) the stale PASS pair was
  taken against, and the baseline §1's bisect starts from.
- `design/softstart_injection_compensation.md` §1 — the `acopen-fb-inj`
  instrument §2.1 reuses; §2/§3 — the transimpedance arithmetic and T1–T7.
- `sim/psrr-dc/records/20260807-105159-64249c6.md` — the amplifier-level PSRR
  term, still PASS 81/81, which is why this is a closed-loop finding and not
  an `error_amp` one.
