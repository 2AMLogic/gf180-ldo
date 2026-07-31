# Device characterization conclusions

Recommendations drawn from the measured tables in this directory. Every number
below is a cell in a committed CSV — the referenced file and the corner it was
taken at are named so any claim can be traced back to the run that produced it.

Nothing here is a spec pass/fail record. When one of these rows is later used to
substantiate a ratified spec line, that claim gets its own record under its own
experiment slug per [`sim/README.md`](../README.md).

---

## 1. Pass device

### Recommendation

**`pfet_03v3`, L = 0.28 µm (model minimum), W ≈ 4 mm** (40 unit cells of
`w=100u nf=10`).

| Claim | Worst case measured | Corner | Source |
|---|---|---|---|
| Dropout at 50 mA | **121 mV** (Rds 2.41 Ω) | ss, 125 °C, Vin = 2.10 V | `fets/results/summary_pass_fet.csv` |
| Dropout at 100 mA | **259 mV** (Rds 2.59 Ω) | ss, 125 °C, Vin = 2.10 V | same |
| Gate capacitance Cgg | **6.14 pF** | ss, −40 °C, Vin = 2.10 V | `fets/results/summary_cgg_pmos.csv` |
| Gate-drain capacitance Cgd | **3.02 pF** | ss, −40 °C | same |
| Off-state leakage at 125 °C | **0.417 µA** (1.4 % of the 30 µA Iq budget, 4.2 % of the 10 µA stretch) | ff, 3.63 V | `fets/results/summary_leak_pmos.csv` |

That single size clears the base target **and** both stretch targets: 300 mV @
50 mA (2.5× margin), 200 mV @ 50 mA (1.7× margin), and 300 mV @ 100 mA (1.16×
margin), all at the worst corner of the full matrix.

If only the base 300 mV @ 50 mA target has to hold, **W ≈ 1.8 mm** is the
measured minimum (`fets/results/summary_sizing.csv`, `rds_target_ohm = 6.0`,
`supply_class = dropout_testpoint`), and W = 2 mm measures 259 mV at the worst
corner — 14 % margin, which is thin for a first silicon spin. W = 4 mm buys the
100 mA stretch for 2× the gate area and 2× the gate capacitance.

Width required, worst case over the whole matrix, `pfet_03v3` at L = 0.28 µm,
Vin = 2.10 V (all at ss / 125 °C):

| Target | Meaning | W required |
|---|---|---|
| Rds ≤ 6 Ω | 300 mV @ 50 mA | 1.79 mm |
| Rds ≤ 4 Ω | 200 mV @ 50 mA | 2.53 mm |
| Rds ≤ 3 Ω | 300 mV @ 100 mA | 3.58 mm |

### Length matters more than anything else here

At the same target and corner, going from L = 0.28 µm to 0.50 µm costs 1.8× the
width, and 1.00 µm costs 3.7× (1.79 / 3.26 / 6.65 mm for the 6 Ω target). The
pass device should be drawn at minimum length; its Rds(on) is not a matching- or
noise-critical parameter that would justify a longer channel.

### Test-point correction — read this before reusing older numbers

The dropout spec is defined at **Vin = Vout + dropout ≈ 2.10 V**, not at the
2.97 V supply floor (`spec/architecture-survey.md` §3.1). A PMOS pass device
driven gate-to-ground has Vsg = Vin, so it has ~0.9 V less overdrive at the real
test point. Sizing from the 2.97 V rows alone **undersizes the device by ~50 %**:

| Target | W from Vin = 2.97 V rows | W from Vin = 2.10 V rows |
|---|---|---|
| Rds ≤ 6 Ω | 1.20 mm | **1.79 mm** |
| Rds ≤ 4 Ω | 1.74 mm | **2.53 mm** |
| Rds ≤ 3 Ω | 2.40 mm | **3.58 mm** |

Both supply classes are kept in the tables (`supply_class` column). Use the
`dropout_testpoint` rows for sizing and the `lv` rows for normal-operation
questions such as Iq and headroom at 3.3 V.

### NMOS is not viable without a charge pump — confirmed with margin to spare

`fets/results/summary_nmos_headroom.csv`. With the gate at Vin (the highest a
ground-referenced error amp can drive), an `nfet_03v3` source follower delivers
**sub-microamp** currents, not milliamps, at every dropout up to 300 mV and
every width up to 4 mm. At W = 2 mm, L = 0.28 µm and a 300 mV dropout at the
2.10 V test point, the *best* corner in the whole matrix (ff, 125 °C) manages
663 nA; at the worst corner the drain current is down at leakage level (tens of
pA, sign-indeterminate). The device is not "marginal", it is off: Vgs equals the
dropout itself (0.1–0.3 V) against a measured Vtn of 0.61–0.82 V at Vsb = 0
(`fets/results/summary_vth.csv`), rising to 0.74–1.15 V once the source sits 1 V
above the substrate.

What a charge pump would have to deliver, at W = 2 mm / L = 0.28 µm, 300 mV
dropout, Vin = 2.10 V, worst corner over the matrix:

| Gate above Vin | Worst-case Id | Meets 50 mA at all corners |
|---|---|---|
| +0.5 V | 0.35 µA | no |
| +1.0 V | 31.9 mA | no |
| +1.5 V | 95.8 mA | yes |
| +2.0 V | 144 mA | yes (and 100 mA) |

So the gate rail needs to sit **≥ 1.5 V above Vin** — i.e. a charge pump
producing ≥ 3.6 V from a 2.10 V input, on top of its own quiescent cost. This
confirms the survey's qualitative conclusion and puts a number on it.

### Mid-voltage flavours, for #7's input-range decision

`pfet_05v0` and `pfet_06v0` are the *same* model card (`pfet_06v0`); only the
allowed minimum length differs (0.50 µm vs 0.55 µm). At the 3.3 V dropout test
point and the 6 Ω target, worst case:

| Device | L | W required |
|---|---|---|
| `pfet_03v3` | 0.28 µm | 1.79 mm |
| `pfet_05v0` | 0.50 µm | 5.08 mm |
| `pfet_06v0` | 0.55 µm | 5.64 mm |

**A mid-voltage pass device costs ~2.8× the width.** That is the pass-device half
of #7's cost — a real but not prohibitive penalty, before counting the
amplifier-side complications the survey raises in §3.3.

Note that widening the *input range* does not move the dropout test point: Vin at
dropout is Vout + dropout regardless of how high the input may go, so the 2.8×
penalty applies even if the part is specified to 5.5 V. The high-input rows show
the MV device is comfortable when there is supply to spare — 1.98 mm at 4.50 V
for `pfet_05v0` at the 6 Ω target (`summary_sizing.csv`,
`supply_class = mv`) — but dropout is by definition measured at low Vin, so the
2.10 V rows are what size the device.

### Assumptions the architecture survey flagged for this issue (§3.4)

| Survey assumption | Measured (typical, 27 °C) | Full PVT range | Verdict |
|---|---|---|---|
| Vtn (`nfet_03v3`) ≈ 0.7 V | **0.644 V** at L = 1.0 µm, 0.609 V at L = 0.28 µm | 0.437 V (ff, 125 °C) … 0.824 V (ss, −40 °C) | **refuted, in the survey's favour** — Vtn is lower than assumed, which only widens the gap the survey relies on |
| \|Vtp\| (`pfet_03v3`) ≈ 0.7 V | **0.843 V** at L = 1.0 µm, 0.787 V at L = 0.28 µm | 0.622 V (ff, 125 °C) … 1.031 V (ss, −40 °C) | **refuted, against the survey** — \|Vtp\| is 0.14 V higher typical, 0.33 V higher worst case |
| PMOS overdrive ≈ 1.4 V at the 2.10 V test point | 2.10 − 1.031 = **1.07 V worst case** | — | qualitatively **confirmed**: 24 % less overdrive than assumed, still ample; the sizing table above already reflects the real device |
| NMOS available Vgs ≈ 0.30 V vs a Vtn it must exceed | 0.30 V available vs 0.82 V needed at Vsb = 0, 1.15 V with body effect | — | **confirmed and strengthened** |
| Cgate of the sized pass device (input to the survey's UGBW argument) | **6.14 pF** Cgg / 3.02 pF Cgd at W = 4 mm, L = 0.28 µm | 5.98–6.14 pF over PVT | now measured; hand this to #10 |

Body effect is worth flagging separately for whoever designs the amplifier:
1 V of Vsb moves Vtn by +0.31 V and \|Vtp\| by +0.39 V
(`fets/results/summary_vth.csv`, `vsb_v` column). Stacked devices in the
amplifier tail will feel this.

---

## 2. Feedback-divider resistor

### Recommendation

**`ppolyf_u_3k`** (3 kΩ/sq unsilicided high-sheet p+ poly) for the divider body,
with **`ppolyf_u`** (350 Ω/sq) reserved for anything that needs absolute
accuracy or a low temperature coefficient.

Measured menu at `res_typical`, 27 °C (`resistors/results/summary_rsheet.csv`,
`summary_tempco.csv`, `summary_corner_spread.csv`):

| Flavour | Sheet (extracted, w = 1 µm) | Area per kΩ | TC 27→125 °C | R spread −40→125 °C | Corner spread (ff→ss) |
|---|---|---|---|---|---|
| `ppolyf_u_3k` | 3131 Ω/sq | **0.318 µm²** | −1293 ppm/°C | 25.5 % | 50 % |
| `ppolyf_u_2k` | 2088 Ω/sq | 0.477 µm² | −1293 ppm/°C | 25.5 % | 40 % |
| `ppolyf_u_1k` | 1029 Ω/sq | 0.969 µm² | −694 ppm/°C | 14.4 % | 40 % |
| `ppolyf_u` | 369 Ω/sq | 2.69 µm² | **−27.9 ppm/°C** | **1.24 %** | 40 % |
| `npolyf_u` | 326 Ω/sq | 3.05 µm² | −1178 ppm/°C | 21.8 % | 39 % |
| `ppolyf_s` (silicided) | 7.46 Ω/sq | 131 µm² | +3206 ppm/°C | 52.5 % | **192 %** |
| `nplus_u` (diffusion) | 54.7 Ω/sq | 18.1 µm² | +1418 ppm/°C | 22.7 % | 50 % |
| `pplus_u` (diffusion) | 196 Ω/sq | 5.04 µm² | +1442 ppm/°C | 22.7 % | 43 % |
| `nwell` | 1807 Ω/sq | 0.548 µm² | +3262 ppm/°C | 43.1 % | 40 % |

Reasoning:

* **Area is the binding constraint.** A low-Iq divider has to be resistive: at
  1 µA of divider current from a 1.8 V output the string is ~1.8 MΩ, which is
  572 µm² in `ppolyf_u_3k` but 4840 µm² in `ppolyf_u` — an 8.5× area difference
  for the same current.
* **The high-sheet TC does not hurt a ratio.** Both legs are the same flavour on
  the same die at the same temperature, so the −1293 ppm/°C cancels to first
  order. The same is true of the ±25 % process corner spread: the *ratio* is
  what sets the output, and it is corner-invariant (see the mismatch finding
  below). This is why `ppolyf_u`'s excellent 1.24 % total temperature spread is
  not worth 8.5× the area *for the divider* — it is worth it for a bias-current
  setting resistor, where absolute value matters.
* **Rule out the rest.** Silicided poly (`ppolyf_s`) has a 192 % corner spread
  and +3206 ppm/°C — unusable for anything precision, fine only for
  interconnect-like ballast. Both diffusion flavours carry a junction to the
  substrate/well (extra parasitic capacitance on the sense node and a leakage
  path competing with the Iq budget) and have +1400 ppm/°C. `nwell` is dense but
  has the worst TC in the menu.
* **No bias dependence to worry about.** Every flavour measured 0 ppm change
  between 1 µA and 50 µA drive (`dr_over_r_1ua_to_50ua_ppm` in
  `summary_rsheet.csv`); the only non-zero entry is `pplus_u` at −8 ppm, from its
  body-junction leakage. Every gf180mcu resistor card carries
  `r_vc1 = r_vc2 = 0`, so this is a property of the models rather than a
  measurement of the silicon's voltage coefficient.
* **Draw wide.** The extracted sheet exceeds the card value by an amount set by
  the model's width bias: 1.043× for `ppolyf_u_3k` at w = 1 µm and 1.81× for
  `nwell`. Narrow strips are not just worse for matching, they are quantitatively
  more resistive per drawn square than the card suggests.

### Finding: the PDK's ngspice resistor models carry **no local mismatch**

`resistors/results/summary_matching.csv`. With `sw_stat_mismatch = 1`, a matched
pair of any resistor flavour at any of three areas (10 / 80 / 500 µm²) returns
**bit-identical** values over 200 Monte Carlo runs — σ(ΔR/R) = 0 exactly, at all
three temperatures. This is not a deck error:

* The same deck carries diode-connected `nfet_03v3` / `pfet_03v3` pairs through
  the same switch, and **they do move**: σ(ΔVgs) = 5.21 / 2.36 / 1.14 mV at
  WL = 2.5 / 10 / 40 µm², i.e. a clean 1/√area trend giving a Pelgrom
  A_VT ≈ **7.2–8.4 mV·µm** for both polarities. So `sw_stat_mismatch` is wired
  through and effective.
* The model file confirms the cause: the resistor subcircuits hard-code
  `mis_r = 0` with the `agauss()` line commented out, and the high-sheet
  `ppolyf_u_1k/2k/3k` cards have no mismatch term at all.

**Consequence for #9's output-accuracy budget: divider mismatch cannot be
obtained from these models.** It must come from the foundry matching data or
from silicon, and #9 should carry it as an explicit assumption rather than
citing a Monte Carlo run against this PDK. What the models *do* give:

* **Global (die-to-die) spread**, via `sw_stat_global = 1` with the
  `res_statistical` section: σ(R) ≈ **4.8 %** for `ppolyf_u`/`ppolyf_u_1k`,
  4.8 % for `2k`, **5.9 %** for `ppolyf_u_3k`.
* **That global spread is perfectly common-mode**: the pair delta is identically
  zero in global mode too, so the divider *ratio* is exactly invariant to process
  corner and to global Monte Carlo. Any output-accuracy error from the divider is
  therefore entirely local mismatch — the one thing these models do not carry.
* The disabled mismatch coefficients the PDK authors left in the file, for
  hand-budgeting only (**read from the model card, not simulated**):
  `ppolyf_u` `par_r = 0.021`, `npolyf_u` `par_r = 0.05808`, `nplus_u`
  `par_r = 0.012608`, `pplus_u` `par_r = 0.0126`, in the same
  `σ = 0.7071·par_r·1 µm/√area` form the FET cards use. Nothing is published this
  way for the high-sheet `ppolyf_u_*k` flavours.

---

## 3. Compensation capacitor

### Recommendation

**`cap_mim_2f0`** for anything in the compensation path. Use a MOSCAP only for
fixed-bias bulk decoupling, and then the well-mode (`_b`) variant.

`caps/results/summary_mim.csv`, `summary_mim_pvt.csv`, at `mimcap_typical`,
27 °C, 10 × 10 µm:

| Device | Area density | Fringe | TC 27→125 °C | PVT spread | Voltage coefficient (measured) |
|---|---|---|---|---|---|
| `cap_mim_2f0` | **1.990 fF/µm²** | 0.238 fF/µm | **+8.95 ppm/°C** | **20.2 %** | 0 |
| `cap_mim_1f0` | 0.987 fF/µm² | 0.330 fF/µm | +12.5 ppm/°C | 20.2 % | 0 |
| `cap_mim_1f5` | 1.470 fF/µm² | 0.379 fF/µm | +33.6 ppm/°C | 31.6 % | 0 |

`cap_mim_2f0` wins on all three axes at once: 2× the density of `1f0`, the
lowest temperature coefficient, and the tightest corner spread (`1f5`'s corners
are ±15.5 % against ±10 % for the other two). Its model carries an explicit
parallel leakage resistor, which works out to ~5 × 10¹⁵ Ω for a 100 µm² plate —
irrelevant at any compensation impedance.

The metal-stack option (m2m3 / m3m4 / m4m5 / m5m6) does **not** change the
density: all four measured identical to six digits. Pick the stack on routing
grounds.

### Two model limitations #10 must not read as physical results

1. **MIM voltage coefficient is not simulated.** Every MIM measured exactly
   0 ppm/V from 0 to 3.3 V, because the behavioural line that would apply
   `c_vcr1`/`c_vcr2` is commented out in the model file; the `.MODEL C` used
   instead is linear. The coefficients are still in the card, and evaluating them
   by hand over the full 3.3 V range gives **+34 ppm (`1f0`), −43 ppm (`1f5`),
   +129 ppm (`2f0` for plates > 5 µm), −86 ppm (`2f0` for plates ≤ 5 µm)**. All
   are small enough not to matter for compensation — but they are *card values*,
   not measurements, and are labelled as such here.
2. **MOSCAP capacitance has no temperature dependence at all** in these models:
   `cap_nmos_03v3` measured bit-identical at −40, 27 and 125 °C
   (`caps/results/summary_moscap.csv`). The `moscap_*` corner sections are pure
   ±10 % scale factors. Do not read the zero TC as a measured property.

### MOSCAP C-V behaviour, including the low-bias region

At `moscap_typical`, 27 °C:

| Device | Max density | Min density | C at 0 V | Max/min | Half-swing knee | Bias for ≥ 90 % of max |
|---|---|---|---|---|---|---|
| `cap_nmos_03v3` | 3.983 fF/µm² | 0.023 fF/µm² | 0.025 fF/µm² | **173×** | +0.634 V | +0.9 … +3.3 V |
| `cap_pmos_03v3` | 3.958 fF/µm² | 0.038 fF/µm² | 0.038 fF/µm² | 104× | −0.794 V | −3.3 … −1.05 V |
| `cap_nmos_03v3_b` | 3.991 fF/µm² | 0.925 fF/µm² | **3.237 fF/µm²** | **4.3×** | −0.370 V | +0.3 … +3.3 V |
| `cap_pmos_03v3_b` | 3.975 fF/µm² | 0.895 fF/µm² | 3.315 fF/µm² | 4.4× | +0.390 V | −3.3 … −0.3 V |
| `cap_nmos_06v0` | 2.177 fF/µm² | 0.037 fF/µm² | 0.037 fF/µm² | 59× | +0.671 V | +0.9 … +3.3 V |
| `cap_pmos_06v0` | 2.177 fF/µm² | 0.037 fF/µm² | 0.037 fF/µm² | 59× | −0.923 V | −3.3 … −1.2 V |

The inversion-mode devices are the trap: `cap_nmos_03v3` collapses by 173× below
~0.6 V of bias, and at 0 V it holds **0.6 %** of its nominal capacitance. A
compensation cap whose value depends on a node that swings through that knee
(a gate node during startup or a load transient, for instance) would change the
loop's pole location by two orders of magnitude exactly when the loop is being
stressed. If a MOSCAP is used anywhere, use the well-mode `_b` variants: they
hold 3.2 fF/µm² at 0 V and vary only 4.3× across the whole ±3.3 V range, at the
same peak density.

MOSCAP peak density is 2× the best MIM (3.98 vs 1.99 fF/µm²), which is the only
reason to consider one — and it comes at the cost of bias dependence, a
gate-oxide reliability constraint, and (in these models) no temperature
behaviour to check the design against.

---

## 4. Handoffs

| Issue | What to take from here |
|---|---|
| #8 schematic entry | `pfet_03v3`, L = 0.28 µm, W = 4 mm (40 × `w=100u nf=10`) — sized at the real dropout test point |
| #9 error amplifier | Cgg = 6.14 pF as the amp's load; divider mismatch **is not available from these models** (§2) and must be budgeted from foundry data; FET A_VT ≈ 7.2–8.4 mV·µm if the input pair budget needs it |
| #10 stability / compensation | Cgg = 6.14 pF, Cgd = 3.02 pF at the pass device; `cap_mim_2f0` at 1.99 fF/µm²; the MOSCAP C-V knee and the two model limitations in §3 |
| #7 input-range decision | A mid-voltage pass device costs 2.8× the width at the dropout test point, and that penalty does not shrink as the input range widens (§1) |
| #3 architecture survey | §1's "assumptions flagged" table confirms the PMOS/NMOS conclusion and corrects \|Vtp\| upward by 0.14 V typical / 0.33 V worst case |
