# DR-0035: reference the soft-start ramp ceiling to `VIN`, not to `VREF` — the ratified PSRR row closes with 9.6 dB of margin, and the Iq the branches burn after hand-over comes back with it

- **Status**: proposed 2026-09-23 (issue #302 / this pull request) — per the
  2026-08-19 ratification-via-PR policy (2AMLogic/2am#357, the mechanism used
  for DR-0005/PR #137, DR-0006/PR #127, DR-0018/PR #199, DR-0023/PR #217,
  DR-0024/PR #228, DR-0026/PR #258 and DR-0031/PR #305), the operator's review
  and approval **of this pull request** is the ratification act itself; no
  separate ratification comment is expected. The word above stays **proposed**
  because that is what this record is as written; the follow-on implementation
  pull request flips it to `ratified <merge date>` as its first hunk, so a
  reader of `main` is never left guessing which side of the gate the record is
  on.
  **This record changes no `design/` file** — not `design/ldo_softstart.sch`,
  and not `design/softstart_injection_compensation.md`, whose §3 must gain T8
  (DR-0031 §5). Issue #302's first acceptance criterion is that ratification
  precede any `design/` change, so both edits belong to a separate, later pull
  request that this one does not open. Every number below was measured on a
  prototype netlist built as a `--dut-netlist` swap under `sim/.work/`
  (git-ignored) against the **unmodified committed** testbenches;
  `git diff origin/main...HEAD -- design/` is empty.
  **No ratified threshold is changed, proposed to be changed, or waived.**
- **Date**: 2026-09-23
- **Decided by**: agent-builder (issue #302) — **proposing**; the ratified spec
  is a human gate.
- **Answers**: `DR-0031` §6 direction **1**, the one its own arithmetic points
  at.
- **Builds on**: `DR-0031` (the defect, the mechanism, and T8), `DR-0023`
  (the ratified cascoded mirror, kept unchanged), `DR-0026` (proposed; its E1
  term is untouched and its E2 clause is answered here), `DR-0033` (the
  poly-resistor flavour rule the new resistor has to satisfy), `DR-0006`
  (the ramp-rate clause the ceiling must not bend).

## Context

`DR-0031` (issue #289, merged 2026-09-23) measured why `sim/psrr-vs-freq`
fails `README.md`'s ratified PSRR row (`> 50 dB @ 1 kHz`, DR-0004 amendment
A7) at 3 of 45 corners, bisected it to the DR-0023 injection element, and
closed the arithmetic:

- the element's **settled** residual into `FB` is 17.568 nA at
  `ff_125c_3.63v` — *inside* the 50 nA T1 bound — but its **supply slope** is
  109.9 nA/V, and `Rtop` = 300 kΩ turns that into 33 mV/V at `VOUT`;
- the slope is supply-referenced because `Mtop_ss` clamps the ramp node `SSR`
  to a ceiling referenced to **`VREF`**, so the forward bias left standing
  across the mirror's reference stack, `VIN − V(SSR) − |V_sg,A|` ≈ 0.779 V,
  grows one-for-one with `VIN` on a two-high weak-inversion `pfet_03v3` stack
  whose current is exponential in it (`2·n·V_T` = 0.1061 V at 125 °C,
  DR-0031 §2.3);
- the one sizing lever the cell names for this defect — `Mtop_ss`'s own
  geometry — is **exhausted at the PDK's model-bin extremes** and still lands
  4.115 dB short (DR-0031 §4), and three further sizing levers are closed
  there by derivation;
- with the element's AC path to `FB` cut and nothing else changed the grid
  passes 45/45, so the deficit is this one element's admittance and nothing
  else (DR-0031 §2.1).

DR-0031 named three directions and declined to choose between them. **This
record chooses direction 1 and measures it.**

## Decision (proposed)

**Move `Mtop_ss`'s gate off `VREF` and onto a new internal node `VCEIL` held a
fixed drop `Δ` below `VIN`, with `Δ` generated as the soft-start cell's own
existing bias current dropped across a second poly resistor of the same
flavour as the one that sets that current.**

```
Iref_ss   = VREF / Rss_bias                       (exists today, Vbsense_ss senses it)
V(VCEIL)  = VIN − Iref_ss · Rceil_ss
          = VIN − VREF · (Rceil_ss / Rss_bias)    ← a RESISTOR RATIO, not a resistance
```

so the settled ramp ceiling becomes

```
V(SSR)|settled  ≈  VIN − Δ + |V_tp|,     Δ = VREF · (Rceil_ss / Rss_bias)
```

and the forward bias standing across the mirror's reference stack,
`VIN − V(SSR) − |V_sg,A|` ≈ `Δ − |V_tp| − |V_sg,A|`, **stops containing
`VIN`**. That is DR-0031 §2.3's defect removed by construction rather than by
margin, which is the property DR-0031 §6.1 asked for.

Expressing `Δ` as `VREF` times a resistor **ratio** — rather than as a
voltage, a threshold stack or an absolute resistance — is the same discipline
`design/ldo_softstart.sch` already applies to the injection transconductance
(*"the 5.0e-6 coefficient is 1.5/`Rtop`, i.e. it is a RATIO to the feedback
divider, not an absolute transconductance … the ratio, not the absolute
value, is the property being preserved"*). Measured, it holds to **74 µV**:
`VIN − V(VCEIL)` spans **1.449443 … 1.449517 V** across all 45 PVT corners
(§2, `t8-proto.csv`).

Everything `DR-0023` ratified is **kept unchanged**: the cascoded mirror
(`Mgmr_ss`/`Mgmrc_ss` against `Mgmo_ss`/`Mgmc_ss`), rectification by mirror
cut-off rather than by a comparator, and the element's single point of contact
with the main loop (`Mgmc_ss`'s drain on `FB`). No device is added to, removed
from or resized in the injection path itself. **This record ratifies the
topology, not the sizing**; `Rceil_ss`'s drawn length is the implementation's
to centre inside the window §3 measures.

### The prototype, in full

Three lines against `design/netlist/ldo_core.spice`, with `Mtop_ss`'s gate
node the only edit to an existing card:

```spice
* VIN-referenced ramp ceiling (issue #302 prototype, DR-0031 s6.1 direction 1)
XRceil_ss VIN VCEIL VSS ppolyf_u_3k r_width=1u r_length=1208u m=1
Fceil_ss  VCEIL VSS Vbsense_ss 1.0
-XMtop_ss VSS VREF  SSR VIN pfet_03v3 L=2u W=1u nf=1 ...
+XMtop_ss VSS VCEIL SSR VIN pfet_03v3 L=2u W=1u nf=1 ...
```

`Rss_bias` is 1 µm × 1000 µm `ppolyf_u_3k`, so `Rceil_ss/Rss_bias` = 1.208 and
`Δ` = 1.2 × 1.208 = **1.4496 V** nominal. `Fceil_ss` is a 1:1 tap of the same
`Vbsense_ss` ammeter `Fss_ramp` already reads — see "What this costs" for the
idealization that carries and how sensitive the result is to it.

## 1. Why a `VIN`-referenced node had to be built rather than found

DR-0031 §6.1 closes with *"no such `VIN`-referenced node exists in the cell
today; creating one is the work."* It is worth recording why the cell cannot
supply one, so the next reader does not go looking.

The cell's bias branch is `VREF` → `Vbsense_ss` → `Rss_bias` → `Mben_ss` →
`VSS`: every node on it is **ground- or `VREF`-referenced by construction**,
which is exactly the property DR-0006 wanted (it is what makes the resistor's
±25 % corner spread show up in the measured ramp rate instead of being hidden).
The only `VIN`-referenced nodes in the cell are the tops of `Rgma_ss`/`Rgmb_ss`
and the mirror's sources — all of which are the thing being fixed. A
`VIN`-referenced *level* therefore requires one new element between `VIN` and
a defined current. `Rceil_ss` is that element, and re-using `Iref_ss` for the
current is what keeps the level a ratio rather than a new absolute.

## 2. What it buys, measured

All numbers below are from runs made for **this** record on this host
(ngspice-46, pinned `gf180mcuD @ c6d73a3`), `main` at `c404305c`, the
committed testbenches unmodified, the prototype swapped in with
`--dut-netlist`. The `main` column is the same grid run back-to-back on the
committed netlist, not quoted from DR-0031 — it reproduces DR-0031's numbers
to four decimals, which is the cross-check that the comparison is like-for-like
across DR-0033's and DR-0034's intervening design changes.

### 2.1 The ratified row

| grid (45 corners each) | `main` @ `c404305c` | prototype | ratified bar |
|---|---|---|---|
| `sim/psrr-vs-freq` (1 mA, binding) `psrr_1k_db` | **FAIL**, worst **29.4286 dB** | **PASS 45/45**, worst **59.5967 dB** | ≥ 50 dB |
| `sim/psrr-vs-freq` `psrr_100k_db` | worst 39.4199 dB | worst 43.8050 dB | ≥ 20 dB |
| `sim/psrr-vs-freq-50ma` `psrr_1k_db` | **FAIL**, worst **29.4310 dB** | **PASS 45/45**, worst **59.5512 dB** | ≥ 50 dB |
| `sim/psrr-vs-freq-50ma` `psrr_100k_db` | worst 37.6661 dB | worst 39.9994 dB | ≥ 20 dB |

Margin at the binding clause: **+9.597 dB** (1 mA) and **+9.551 dB** (50 mA).

The three corners issue #302 names, plus the two that were nearest the bar:

| corner | 1 mA `main` | 1 mA proto | 50 mA `main` | 50 mA proto |
|---|---|---|---|---|
| `ff_125c_3.63v` | 29.4286 | **61.8942** | 29.4310 | **61.8350** |
| `sf_125c_3.63v` | 38.5728 | **59.5967** | 38.5734 | **59.5512** |
| `ff_125c_3.30v` | 47.0896 | **69.9777** | 47.0903 | **70.0804** |
| `sf_125c_3.30v` | 55.7608 | 67.9279 | 55.7618 | 68.0236 |
| `tt_125c_3.63v` | 58.7661 | 63.4762 | 58.7525 | 63.4652 |

### 2.2 T8 and T1, at the settled operating point

Measured with DR-0031 §2.2's own instrument — a 0 V ammeter in `Mgmc_ss`'s
drain lead, read out of `sim/psrr-vs-freq`'s deck so the operating point is
exactly the one the ratified row is graded at, with the supply slope taken
from the `.ac` at 1 kHz (the probe's header records why a `.dc` sweep of `VIN`
is the wrong instrument here: `SSR` is a capacitor node, so at pure DC the
circuit has a second, unstarted-ramp root and 9/45 corners land on it).

| target | bound | `main` worst | prototype worst | margin |
|---|---|---|---|---|
| **T8** `|dI_inj/dVIN|` at settled | ≤ 10.5 nA/V | **109.9004 nA/V** @ `ff_125c_3.63v` (10.5× over) | **0.0328 nA/V** @ `ff_125c_3.63v` | **320×** inside |
| **T1** `|I_inj|` at settled | ≤ 50 nA | 17.5706 nA @ `ff_125c_3.63v` (2.8× inside) | **0.0366 nA** @ `ff_125c_3.63v` | **1366×** inside |
| settled `V(VOUT)` error | ±36 mV (±2 % row) | −5.27 mV @ `ff_125c_3.63v` | **−0.16 mV** | 225× inside |

The T8 improvement is **3350×** and the row it gates passes with 9.6 dB. Note
that T1 was already passing on `main` while the ratified row failed — which is
DR-0031 §5's central finding, and the reason T8 exists.

### 2.3 The Iq the branches burn after hand-over comes back

`sim/quiescent-current`, 45 corners, both PASS; the binding corner is
`ff_125c_3.63v` and the binding clause is full load (DR-0026):

| clause | `main` | prototype | headroom to the ratified < 30 µA |
|---|---|---|---|
| `iq_en_ua` (no load) | 27.3882 µA | **22.2402 µA** | 2.612 → **7.760 µA** |
| `iq_full_ua` (full load) | **28.7153 µA** | **23.4456 µA** | **1.285 → 6.554 µA** |

**−5.270 µA at the binding clause, a 5.1× increase in headroom.** The
mechanism is visible in the branch node: `Mgma_ss`'s degeneration current at
the settled point, `(VIN − V(GMSA))/200 kΩ`, goes from **3.4812 µA** to
**0.6372 µA** worst-case over the grid (and is 0 to the printed digit at 21 of
45 corners in both). Raising the ceiling raises both gate references toward
`VIN`, so the branches starve themselves once the element has released.

This is **the same ~5 µA issue #259 is open for** and that PR #267 / `DR-0028`
proposes to recover by gating the branch supply — a mechanism DR-0031 §7
measured at **−5.2 dB / −7.1 dB of PSRR** at the two binding corners. Here the
same current comes back while PSRR *improves* by 32.5 dB. See
"Cross-consequences".

## 3. Where `Δ` has to sit, and how wide the window is

`Δ` is the one number this topology introduces, so it is swept to both edges
rather than argued. Each row is a full 45-corner run of the T8 probe (whose
`psrr_1k_db` reproduces `sim/psrr-vs-freq`'s own measurement to four decimals
— 59.5967 dB at `sf_125c_3.63v`, both instruments):

| `Rceil_ss` | `Δ` = 1.2·(L/1000) | worst `psrr_1k_db` | worst `|dI/dVIN|` | min settled `V(SSR)` | max settled `V(SSR)` |
|---|---|---|---|---|---|
| 800 µm | 0.960 V | 59.610 dB | 0.019 nA/V | 2.585 V | **3.569 V** (61 mV under `VIN`) |
| 1000 µm | 1.200 V | 59.609 dB | 0.019 nA/V | 2.411 V | 3.407 V |
| **1208 µm** | **1.4496 V** | **59.597 dB** | **0.033 nA/V** | **2.228 V** | **3.235 V** |
| 1500 µm | 1.800 V | 59.471 dB | 0.285 nA/V | 1.965 V | 2.986 V |
| 1800 µm | 2.160 V | 56.976 dB | 2.966 nA/V | **1.689 V** | 2.724 V |
| 2200 µm | 2.640 V | **20.784 dB** — FAIL | 304.8 nA/V | **1.315 V** | 2.365 V |

Both edges are real and both are physical:

- **`Δ` too large** — the ceiling at minimum supply falls back toward `VREF`,
  the mirror's reference stack recovers its forward bias, and the defect
  returns. At `Δ` = 2.64 V the settled `V(SSR)` at `ff_125c_2.97v` is 1.315 V,
  only **115 mV above the `VREF` = 1.2 V hand-over point**, and the row fails
  by 29 dB. This edge is `VIN_min`-binding and is the one that matters.
- **`Δ` too small** — the ceiling approaches the rail. At `Δ` = 0.96 V the
  settled `V(SSR)` reaches 3.569 V at `VIN` = 3.63 V, 61 mV under the supply;
  below that `Mtop_ss` stops being able to clamp at all and the ramp node is
  left to the leakage balance `design/ldo_softstart.sch` built the clamp to
  avoid.

The proposed `Δ` = 1.4496 V sits **≥ 1.0275 V above `VREF`** (worst
`ff_125c_2.97v`) and **≥ 0.3949 V below `VIN`** (worst `ss_-40c_3.63v`) — i.e.
roughly centred, with a window that is **−34 % / +49 %** wide in `Δ`, against
a `Δ` whose measured PVT spread is 74 µV (0.005 %). The implementation should
not read 1208 µm as a tuned value; it is a round-ish point near the middle of
a wide window.

### 3.1 DR-0031 §6.1's three named constraints, checked

| constraint (DR-0031 §6.1) | measured on the prototype |
|---|---|
| the ceiling must stay **above `VREF`** at every corner (DR-0023's rectification event is `V(SSR)` crossing `VREF`) | min settled `V(SSR)` = **2.2275 V** at `ff_125c_2.97v`, **1.0275 V** of clearance (on `main` the same clearance is 0.787 V — this is *more* clearance, not less) |
| the ceiling must stay **below `VIN`** so nothing floats | min `VIN − V(SSR)` = **0.3949 V** at `ss_-40c_3.63v`. Under a `VIN`-referenced ceiling the constraint's *old* wording ("below `VIN_min`") no longer says what it meant: a fixed level below `VIN_min` was how a `VREF`-referenced ceiling stayed under the rail at every supply, whereas this ceiling is under the rail **by construction at every supply**. The clause is restated above, not relaxed |
| `Mtop_ss` must stay a **cut-off device below `VREF`**, so it does not bend the part of the ramp `T3`/`T4` and DR-0006's ramp-rate clause grade | `Mtop_ss`'s source is `SSR` and its gate is now `V(VCEIL)` ≥ **1.5205 V** (at `VIN_min`), so it cannot conduct until `V(SSR)` ≳ 2.2 V — **1.0 V above** the `V(SSR)` = `VREF` hand-over point. On `main` the same device turns on at ≈ 2.0 V, 0.8 V above hand-over. Below hand-over the two netlists are electrically identical in this device, so **nothing on the graded part of the ramp can move by this change except through second-order loading of `VIN`** |

## 4. What this costs, stated rather than discovered later

- **A second behavioural current tap, and a sentence in
  `design/ldo_softstart.sch` that stops being true.** `Fceil_ss` is an ideal
  1:1 CCCS off `Vbsense_ss` — the same *"ideal large-ratio mirror standing in
  for the bandgap-referenced bias generator this repo has not designed"*
  idealization `Fss_ramp` and `ldo_ilimit`'s `Fbias` already carry, at the
  same node and off the same ammeter. But the cell's "WHAT IS IDEALIZED HERE"
  section currently reads *"`Fss_ramp` … is now the ONLY idealization left in
  this cell's injection path"*, and this change makes that false. The
  implementing pull request must correct that sentence rather than leave it
  standing. The implementation is free to realise the tap as a real mirror
  leg instead; the next bullet is why that choice is not load-bearing for the
  result.
- **…and the result is insensitive to how that tap is built.** A real mirror
  leg has finite output resistance where the CCCS has infinite. Measured by
  shunting `VCEIL` to AC ground through `r_o` (DC-preserving: the shunt
  returns through a 1 F capacitor, so the operating point is untouched), full
  45-corner grids at each value:

  | `r_o` on `VCEIL` | ∞ (CCCS) | 1 GΩ | 300 MΩ | 100 MΩ | 30 MΩ | 10 MΩ | 3 MΩ |
  |---|---|---|---|---|---|---|---|
  | worst `psrr_1k_db` | 59.597 | 59.596 | 59.595 | 59.592 | 59.582 | 59.561 | 59.521 |

  **0.076 dB from ∞ to 3 MΩ**, against 9.6 dB of margin. A single `pfet_03v3`
  mirror leg at 400 nA is comfortably above 3 MΩ, so this is a bounded, not an
  open, implementation risk.
- **Area.** `Rceil_ss` at 1 µm × 1208 µm is ≈ 1208 µm² of drawn poly plus
  ladder overhead — **≈ 1.2 % of the ratified < 0.1 mm² core-area row**,
  against the 43.6 % of margin `DR-0033` has just delivered. It is 21 % larger
  than the `Rss_bias` the cell already carries and in the same flavour, so it
  adds no new resistor module and no new layout idiom.
- **Flavour is not free to choose, and it couples to issue #292.** `Δ` is a
  *ratio* `Rceil_ss : Rss_bias`; the ratio cancels sheet resistance only if
  both resistors are the **same flavour**. By `DR-0033`'s rule, `Rceil_ss`
  itself is a ratio-setting element with no DC current of its own to define
  (the current is `Iref_ss`, set by `Rss_bias`), so `ppolyf_u_3k` is
  admissible — but the binding constraint is the *match*, not the rule.
  `DR-0033`'s own Consequences flag `Rss_bias` as a candidate to move to
  `ppolyf_u_1k` (filed as **issue #292**); if that happens, **`Rceil_ss` must
  move with it**, and #292 must be told so. This is recorded here rather than
  left to be discovered when the ceiling drifts.
- **Resistor local mismatch is not simulable against these models** — the same
  declaration `DR-0026` and `README.md` note 3 make (`sim/devchar/CONCLUSIONS.md`
  §2: this PDK hard-codes local mismatch to zero for `ppolyf_u_3k`). So the
  ratio term is carried as a stated assumption, not as a simulated result.
  Unlike DR-0026's servo — where the ratio *is* the accuracy — here the ratio
  only has to land `Δ` inside a −34 %/+49 % window, so a few per cent of ratio
  error is three orders of magnitude from binding. Stated so that the
  assumption is on the record, not because it is close.
- **The settled ramp node sits higher, and for longer.** Settled `V(SSR)` goes
  from 1.987 … 2.523 V to 2.228 … 3.235 V, so `Css` keeps integrating for
  longer after hand-over before the clamp catches it. No ratified row grades
  the ramp *above* hand-over — DR-0006's rate clause and `T3`/`T4` are all
  below it, where §3.1 shows the two netlists are electrically identical in
  this device — but "no row grades it" is an argument, not a measurement, and
  §5 is the measurement.
- **`T2`, `T3` and DR-0026's `E1` are untouched.** This record fixes `E2`
  (soft rectification at the settled point). The hand-over acquisition step
  `1.8 V × delta_eff` that `DR-0026` addresses is a *finite degeneration loop
  gain* term, it is worst at **minimum** supply, and nothing here moves it.
  Ratifying this record does **not** close issue #249, and must not be cited
  as if it did.

## 5. Evidence for the benches that grade the rest of the element

Same discipline as §2: `main` @ `c404305c` and the prototype, back to back,
this host, committed testbenches unmodified, prototype as the DUT swap under
`sim/.work/`. None of it is committed evidence — the harness refuses to mint
a record over an overridden DUT (`sim/soft-start/testbench/run.sh`'s
`LDO_NETLIST` guard refuses unless `NO_RECORD` is set), correctly — so the
scratch grids live under `sim/.work/dr0035v/` and the implementing PR re-runs
every bench on the committed export and mints the records (Consequences).

### 5.1 `sim/soft-start` — the Startup row's own bench, 163 points, both netlists

The full matrix, both sides, one `summarize.py` adjudication:

| `summarize.py` flag class | `main` | prototype | corner sets |
|---|---|---|---|
| steady ramp rate above 5 V/ms | 0/163 | 0/163 | — |
| peak dV/dt above 5 V/ms (incl. transients) | 162 | 162 | identical |
| non-monotonic ramp (dV/dt went negative) | 131 | 131 | 4 corners swap names, 4 ↔ 4 |
| inrush above 5 mA at `C_eff` = 1 µF | 82 | 82 | identical |
| supply within 10 mA of the 62 mA limit, at 1 µF | 81 | 81 | identical |
| overshoot above +2 % | 10 | 10 | identical |
| failed to settle within 1.8 ms | 0 | 0 | — |
| settled output outside ±2 % | 2 | 2 | same 0.33 µF / 1 mΩ family, names differ |
| still ringing at end of enable window | 10 | 10 | identical |
| ramp not finished above `VREF` | 0 | 0 | — |
| hold gate > 0.2 V below `VIN` | 0 | 0 | — |
| disabled output above 10 mV | 20 | 20 | identical |
| ramp capacitor not reset by disable | 0 | 0 | — |

Every count is equal, 6 of the 8 nonempty classes flag **byte-identical
corner sets**, and the two that move shuffle corner names *inside the same
already-failing family*. The four FAIL classes are `main`'s own committed
state — the standing record (`sim/soft-start/records/20260918-190207-8a59d23.md`)
already reads FAIL on inrush, current-limit clearance, monotonicity and peak
dV/dt — so the prototype neither adds nor removes a failure, and the clauses
this record could have broken (ramp rate, settling, hand-over, hold-gate,
cap reset) pass at 163/163 on both sides.

Where the numbers do move:

- settled `V(SSR)` spans **1.987 … 2.523 V → 2.228 … 3.235 V** — §3's
  prediction, measured on both instruments.
- `t_startup` extremes are identical to the corner at both ends of the range
  (0.5467 ms / 1.2872 ms, both sides) — the graded settling clause does not
  move at its own worst corners.
- the worst settled-output excursion deepens: `main`'s two ±2 % flags
  (`ss_-40c_2.97v`, 1.7638 V, and `ss_-40c_3.63v`, 1.8849 V) **pass** on the
  prototype (1.7917 / 1.7918 V), while the prototype flags two corners of
  the same 0.33 µF / 1 mΩ family `main` passes (`res_ss_-40c_2.97v` 1.7888 →
  1.6959 V; `res_ss_125c_3.63v` 1.7835 → 1.7411 V). All four corners sit in
  the family whose enable window ends **mid-oscillation** — `vout_pp_late`
  reaches 1.37 V pp on `main` and 1.35 V pp on the prototype, and the
  ringing-flagged 10/10 byte-identical set lives in the same family — so the
  ±2 % flag there samples a ringing waveform, not a DC operating point, on
  both netlists. The DC settled accuracy at the graded 1 µF points is §2.2's
  −0.16 mV. The accuracy allocation itself is DR-0023 R4's open item (the
  300 kΩ transimpedance), untouched by this record.
- the 100–700 mA transient peaks (`icap`/`isup`/`dvout_*`) move per corner in
  both directions inside classes both sides fail (`icap` worst 492.1 →
  501.6 mA; `dvout_min` worst −8392 → −12129 V/ms at
  `res_ss_-40c_3.63v_4.7u_0.5`).

### 5.2 `sim/quiescent-current` — 45 corners, both netlists

Carried by §2.3: PASS on both sides, and the binding clause's headroom goes
1.285 µA → 6.554 µA at `ff_125c_3.63v` full load.

### 5.3 `sim/startup` — like-for-like where runnable; the full A/B is the implementing PR's

This bench's own header documents the hazard (issue #232): the harness's
`-j 8 --timeout 300 s` defaults produce **mass false timeouts from CPU
contention on a shared multi-core host**, and recommend `-j 3 --timeout 900`.
This host was carrying external fleet load throughout (load average ≈ 30 on
8 cores; a *single `main` point*, `tt_-40c_3.63v`, exceeded 850 s at `-j 1`),
so a full 81 × 2 grid was not runnable to the bench's own standard here. The
corners that do complete, on both netlists, back to back:

| measurement | `ff_-40c_3.63v`: `main` → proto | `ff_125c_3.63v`: `main` → proto |
|---|---|---|
| `tsettle_full_ms` | 0.74646 → 0.74645 | 0.81457 → 0.81434 |
| `tsettle_min_ms` | 0.74612 → 0.74610 | 0.81387 → 0.81386 |
| `overshoot_full_mv` | −36.67 → −36.67 | −42.43 → −37.17 |
| `vfinal_short_v` | 0.0933742 → 0.0933742 | 0.0948708 → 0.0948708 |
| `ipeak_short_ma` | 204.9 → 205.7 | 112.0 → 112.0 |

Both sides PASS both corners; settling agrees to < 0.03 %, and the protected
near-short branch — the branch that grades the current limiter, untouched by
this record — is identical to six decimals. The remaining 79 corners time out
on this host on **both** netlists (where `main` completes it is, if anything,
the slower of the two), i.e. a host-load property, not a prototype property;
they are re-run on the committed export by the implementing PR, and this
rail's transient coverage is meanwhile carried by §5.1's 163-point
both-sides grid (71 of its points are at 2.97 V).

### 5.4 `sim/soft-start-loop-gain` (T6) — not measured on the prototype here, and why

That bench freezes its DUT variants from `design/netlist/ldo_core.spice`
**as committed** (`netlist_variants.py`), so measuring the prototype through
it would require writing the prototype into a committed `design/` file — the
one thing this record exists to avoid doing before ratification. T6's
re-measurement is therefore part of the implementing PR's scope
(Consequences), where the change *is* the committed export. The small-signal
story this record can already tell without it: §4's `r_o` table (the
element's loading of `FB` is insensitive to the tap's output resistance over
three decades, against 9.6 dB of margin) and §6's AC-open control (59.610 dB
against the prototype's 59.597 dB — within 0.013 dB of the element-removed
bound). T7 is a schematic-estimate clause and unchanged by construction: no
device is added to `FB`'s node.

## 6. Alternatives considered

- **DR-0031 §6.2 — hard-disconnect `Mgmc_ss`'s drain from `FB` after
  hand-over.** Measured upper bound, and the reason it is not proposed, are
  both DR-0031's: it needs a gating signal that does not exist, because the
  release point `V(SSR)` spans 1.200 – 2.025 V over PVT (DR-0026 T4) while the
  settled ceiling on `main` is as low as 1.53 V, so no fixed `V(SSR)`
  threshold separates the two states, and `HG` resolves an order of magnitude
  too early. Not reconsidered here. **Worth noting as a second-order
  consequence of this record**: a `VIN`-referenced ceiling *widens* that
  separation (settled `V(SSR)` ≥ 2.2275 V against the same 2.025 V release
  ceiling), so if §6.2 is ever wanted it is less blocked than it was — but it
  is not needed, because the disconnect's own measured bound (DR-0031 §2.1)
  is now within 0.013 dB of what this record achieves without it (§2.1's
  AC-open control on the prototype reads 59.610 dB against the prototype's
  59.597 dB).
- **DR-0031 §6.3 — fold T8 into DR-0026's local servo.** Rejected as the
  *primary* lever on cost and on ordering, not on feasibility. DR-0026's servo
  is a **new amplifier, a new loop and a new standing branch** that has to fit
  inside 1.285 µA of full-load Iq headroom and be stable across a decade of
  branch bias at every corner — DR-0026 calls that "the hard part of the
  design". This record closes the same ratified row with **one resistor and
  one bias tap**, adds no loop, and *increases* the headroom that servo would
  have to fit into, from 1.285 µA to 6.554 µA. DR-0031 §6.3 also notes that
  DR-0026's E2 clause as literally worded (*"`GMSUM` stays below
  `VREF` + |V_tp|"*) pushes `V(GMSUM)` **down**, which §2.3's exponential law
  says makes the residual **worse**; this record supplies the correct form of
  that requirement — **the quantity to bound is `VIN − V(GMSUM)`, and it must
  be bounded from *above*, not `V(GMSUM)` from above**. The two records
  compose: DR-0026 keeps E1/T2/T3, this one takes E2/T1/T8, and DR-0026's E2
  clause should be struck when DR-0026 is implemented.
- **Sizing `Mtop_ss` instead.** Closed by `DR-0031` §4 at the PDK's own
  model-bin extremes (`L` = 50 µm = `lmax`, `W` = 0.22 µm = `wmin`),
  4.115 dB short with no lever left. Not re-swept.
- **A resistive divider from `VIN` to `VSS` for `VCEIL`.** Rejected on two
  counts. (a) It makes the ceiling *proportional* to `VIN` rather than offset
  from it: `Δ` = (1 − k)·`VIN` still carries a supply term, so the forward
  bias on the mirror stack keeps a slope of (1 − k) instead of 1 — an
  improvement by a factor, which is precisely the kind of margin-based fix
  DR-0031 §6.1 asks to be replaced by a structural one. (b) It is a **new
  standing current from `VIN` to ground**, charged against the same Iq row
  this record is otherwise giving 5.27 µA back to.
- **Define `Δ` with a diode-connected device stack instead of a resistor
  ratio.** Two `pfet_03v3` diodes from `VIN` would land `Δ` = 2·|V_tp| ≈
  1.12 … 1.8 V, inside the measured window of §3 — so it is not obviously
  unworkable, and it is recorded here so it is not re-derived. Rejected
  because the stack's spread is the **threshold's** spread (hundreds of mV
  over PVT, and it moves the wrong way with temperature) against a measured
  74 µV for the ratio, and because it still needs a current to define the
  drop, so it saves no element. A resistor ratio off a current that already
  exists is strictly cheaper and 3 orders of magnitude tighter.
- **Relaxing the row.** `CLAUDE.md` forbids it, and DR-0031 §2.1 already
  removed the premise for it.

## Consequences

- **The follow-on implementation PR's scope, gated on ratification of this
  record**: this record's Status line flipped to `ratified <merge date>`;
  `design/ldo_softstart.sch` gains `Rceil_ss`/`Fceil_ss` and moves
  `Mtop_ss`'s gate, with its "WHAT IS IDEALIZED HERE" and "SIZING AS BUILT"
  sections corrected; `design/softstart_injection_compensation.md` §3 gains
  **T8** with its per-corner measurement (DR-0031 §5 assigns that edit to the
  implementing PR, and issue #302 requires it); fresh committed records for
  `sim/psrr-vs-freq`, `sim/psrr-vs-freq-50ma`, `sim/soft-start` (163 points),
  `sim/startup`, `sim/quiescent-current` and `sim/soft-start-loop-gain`
  (T6/T7); and `sim/CHARACTERIZATION.md` regenerated. **No `design/` change
  lands with this record.**
- **The ratified PSRR row goes FAIL → PASS**, on both load conditions, with
  9.55 dB of margin at the worse of the two — but only once the implementing
  PR lands. `sim/CHARACTERIZATION.md` correctly reports FAIL until then, and
  this record does not change it.
- **The Iq row's binding headroom goes 1.285 µA → 6.554 µA** at
  `ff_125c_3.63v` full load. That is a real change in what later decisions can
  afford, and DR-0026's servo is the first beneficiary.
- **`sim/psrr-vs-freq` stays on the list of benches any PR touching this
  injection path must re-run** (DR-0031's Consequences). This record adds
  nothing to that list and removes nothing from it.
- **The `fs_125c_3.63v` sub-ground DC root does not appear on the prototype**
  at any of the 45 × 2 PSRR points (worst `dc_vout_v` 1.79883 V). That is a
  symptom disappearing, **not** issue #304 being fixed: #304 is a
  harness-robustness question about a deck admitting a second root, and a DUT
  that no longer reaches it does not answer it. #304 stays open.

## Cross-consequences (other records and open work)

- **`DR-0031`**: answered, not superseded. Its measurements stand, its T8
  stands, and this record is the direction-1 branch it declined to choose.
  DR-0031 §4's "the lever is exhausted" conclusion is unaffected — this record
  does not use that lever.
- **`DR-0023`**: unaffected and stands in full. Nothing in the cascoded mirror
  changes; what changes is the bias the mirror's reference stack is left
  standing at.
- **`DR-0026` (proposed)**: **not superseded, and not closed.** Its E1 term,
  its T2/T3 targets and its inrush motivation are untouched. Two things change
  for it: its **E2 clause is answered here** and should be struck rather than
  implemented as worded (which §6 shows is wrong-signed), and the Iq budget it
  has to fit inside goes from 1.285 µA to 6.554 µA.
- **`DR-0028` (proposed, PR #267) and issue #259**: this record recovers the
  same ~5 µA that #259 is open for and DR-0028 proposes a mechanism for, at
  the same binding corner, **without** the −5.2 dB / −7.1 dB PSRR cost
  DR-0031 §7 measured on PR #267's own head. If this record is ratified and
  implemented, DR-0028's branch-gating mechanism is not needed. **That is a
  recommendation to #259/#303 and their operator decision, not a decision this
  record makes** — #303 is already `loom:operator-decision` and this record
  does not pre-empt it.
- **`DR-0033`**: unaffected as a decision; its rule is applied above, and its
  open follow-up **issue #292** gains a constraint (`Rss_bias` and `Rceil_ss`
  are a ratio pair and must not be given different flavours).
- **`DR-0006`**: unaffected. The ramp-rate clause is graded below hand-over,
  where §3.1 shows this change is electrically inert.
- **`DR-0004` (amendments A6 Iq / A7 PSRR)**: unaffected as decisions. Neither
  number is proposed to change; A7 goes from failing to met, and A6 from met
  with 1.285 µA to met with 6.554 µA.
