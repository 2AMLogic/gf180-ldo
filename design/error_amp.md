# `error_amp` — error amplifier, with offset, PSRR and current budgets

Issue #9. This document is the *design record* for `design/error_amp.sch`:
what the topology is, why, how the ratified spec's accuracy / PSRR / Iq rows
are split across sub-blocks, and what the corner simulations measured against
each split.

Evidence for every measured number here:

- `sim/amp-openloop/records/20260801-002830-712cb87.md` — gain, UGBW, phase margin, systematic offset,
  Iq, headroom and the pass-gate drive extremes, 81 PVT points.
- `sim/psrr-dc/records/20260801-002908-712cb87.md` — supply-to-output coupling `G`, differential gain
  `A`, and the projected LDO PSRR, 81 PVT points.
- `sim/op-point-sanity/records/20260801-002928-712cb87.md` — `ldo_core` closing the loop at 1.8 V with
  this amplifier in place of #8's behavioral placeholder.

Nothing below is a closed-loop claim. Loop stability is #10, the full
testbench suite is #12, mismatch Monte Carlo is #13.

---

## 1. Topology

Two-stage Miller-compensated OTA — candidate 3 of
`spec/architecture-survey.md` §5.

```
        VDD ──┬────────────┬──────────────┬──────────── VDD
              │            │              │
           Rbias        MLD1 ══ MLD2    M2P (driver)
              │        (PMOS mirror)      │
   NBIAS ─────┴─ MB1      ND     N1 ──────┘ gate
              │            │      │
              │        MIN1 ╲  ╱ MIN2      OUT ─────► pass gate
   INN ───────────────────┘  ╲╱  └──────── INP        │
              │              TAIL                  Rz─Cc (Miller)
              │               │                       │
              └───────────── MTAIL           M2N (current sink)
                              │                       │
        VSS ──────────────────┴───────────────────────┴──── VSS
```

| Block | Devices | Nominal current (tt/27 °C/3.3 V) |
|---|---|---|
| Bias | `Rbias` (`ppolyf_u_1k`, 1 µm × 1000 µm ≈ 1.03 MΩ), `MB1` | 2.44 µA |
| Stage 1 | `MIN1`/`MIN2` (`nfet_03v3` 60 µm/6 µm), `MLD1`/`MLD2` (`pfet_03v3` 8 µm/8 µm), `MTAIL` | 2.43 µA |
| Stage 2 | `M2P` (`pfet_03v3` 150 µm/2 µm), `M2N` (`nfet_03v3` 10 µm/4 µm) | 4.18 µA |
| Comp | `Cc` (`cap_mim_2f0`, 39 µm × 39 µm ≈ 3.06 pF), `Rz` (`ppolyf_u`, 1 µm × 109 µm ≈ 40 kΩ) | — |

**Why two-stage Miller and not folded-cascode** (the survey shortlisted both).
The PSRR row needs 53.5 dB of amplifier gain at 1 kHz (§4), which at a single
dominant pole means UGBW ≳ 0.5 MHz. A single-stage OTA reaches that only by
raising its output impedance — but its output node *is* the 6.14 pF pass gate,
so the same impedance that buys gain puts the gate pole below the loop's
crossover. Splitting gain across two stages decouples the two: stage 1 carries
the impedance (and hence the gain), stage 2 presents a `1/gm`-ish drive to the
gate. The measured result is 110–115 dB of DC gain with the gate pole out at
`gm(M2P)/2πC_L` ≈ 2 MHz.

**Why the second stage is a PMOS driver into an NMOS sink.** The pass device is
a PMOS common-source, so the amplifier output must reach *both* rails: down to
~VSS to turn it on hard at the dropout test point, and up to ~VDD to turn it
off. A PMOS-driver/NMOS-sink stage does both (both devices enter triode);
an NMOS-driver/PMOS-source stage would clamp at `VDD − Vdsat`, leaving residual
`Vsg` on a 4 mm pass device at no load. Measured extremes across all 81 points:
**OUT ≤ 3.8 µV above VSS** driven down, **OUT within 1.7 mV of VDD** driven up.

**Why the input pair is NMOS — and why VREF moved to 1.2 V.** See §2.

**What compensation this amp does *not* do.** `Cc` sets the *amplifier's* own
dominant pole; it is not the LDO loop's compensation. `spec/architecture-
survey.md` §4.1 makes the output pole dominant for the loop, and DR-0001
forbids relying on a minimum-ESR zero. §6 hands #10 the numbers it needs and
states plainly what the loop still has to solve.

---

## 2. Why 1.2 V, not 0.6 V (a change to `ldo_core`)

Issue #8 wired `ldo_core`'s reference to an ideal **0.6 V** source with a
200 k/100 k divider (β = 1/3), calling the value a stand-in and naming the
divider ratio as the thing that changes if a different reference lands. Issue
#9 makes that change: **VREF = 1.2 V, `Rtop` = 300 k, `Rbot` = 600 k,
β = 2/3.** Three independent reasons, in descending order of how load-bearing
they are:

1. **Input-stage headroom at the dropout test point (the hard constraint).**
   The loop must still regulate at Vin = 2.10 V (README note 4), where FB is
   still at VREF. A **PMOS** input pair needs
   `VDD ≥ VCM + |Vsg| + Vdsat(tail)`; at ss/−40 °C `|Vtp|` measures 1.031 V
   (`sim/devchar/CONCLUSIONS.md` §1), so with VCM = 1.2 V that is
   1.2 + 1.03 + 0.18 ≈ 2.41 V — it starves at 2.10 V. An **NMOS** pair
   references its headroom to VCM and ground instead, so it is indifferent to
   VDD — but it then needs `VCM ≥ Vgs + Vdsat ≈ 0.82 + 0.18 = 1.00 V` at the
   same corner, which a 0.6 V reference cannot supply at all. 1.2 V satisfies
   the NMOS pair; 0.6 V satisfies neither pair at 2.10 V without a different
   (e.g. rail-to-rail or folded) input stage costing Iq and area.
   Measured: `TAIL` sits **295–587 mV** above VSS across all 81 points at
   VDD = 3.3 V nominal and **317–606 mV** at VDD = 2.10 V — i.e. it does not
   move with the supply, which is the property being claimed, against
   `Vdsat(MTAIL)` = 138 mV.
2. **It is the reference DR-0003 already budgets against.** DR-0003 (ratified)
   puts the amplifier's offset gain-up at `1/β = Vout/Vref` and states "at
   1.8 V with a 1.2 V reference that factor is **1.5**". At 0.6 V the factor is
   3.0 and every offset term in §3 doubles.
3. **It is the divider DR-0003 already sizes.** DR-0003 requires "~900 kΩ
   total to keep standing current near 2 µA": 300 k + 600 k = 900 kΩ, and
   1.8 V / 900 kΩ = 2.00 µA exactly. #8's 200 k/100 k drew 6 µA — 3× the
   ratified allocation.

The 6 dB of PSRR that β = 2/3 buys over β = 1/3 (§4) is a fourth reason, but
the headroom argument alone decides it.

**This is not a spec change.** The ratified spec fixes Vout = 1.8 V ±2 % and
says nothing about the reference voltage; DR-0003 assumes 1.2 V in its own
reasoning. If a future bandgap block lands at some other voltage, the divider
ratio changes again and §3's gain-up factor moves with it — but a reference
below ~1.0 V would additionally require re-opening the input-stage topology,
so it is not a free change and should carry a decision record.

---

## 3. Output-accuracy (offset) budget

**The window.** The ratified Output row is 1.8 V ±2 % = **±36 mV, 3σ**, over
line, load and temperature, and README note 2 makes it **regulator-only — the
reference's own error is excluded**. The Load-reg row (< 1 %, 18 mV) is
explicitly counted *inside* that window, so the static terms below are budgeted
against the remaining **18 mV one-sided**.

**How the terms are combined.** Statistical terms (device mismatch) add in
RSS at a common 3σ; deterministic terms (systematic offset, line regulation)
add linearly on top. Everything is referred to the output through
`1/β = 1.5`.

| Term | Input-referred | Output-referred (×1.5) | Kind | Source |
|---|---|---|---|---|
| Amp input-pair + mirror mismatch | 2.33 mV (3σ) | **3.49 mV** | 3σ statistical | Pelgrom, calculated below |
| Amp systematic offset | 0.61 mV (worst corner) | **0.91 mV** | deterministic | measured, `sim/amp-openloop` |
| Feedback-divider mismatch | — | **3.36 mV** | 3σ statistical, **assumption** | model card `par_r`, below |
| Line regulation, 2.97–3.63 V | — | **≤ 1.65 mV** | deterministic | ratified allowance 5 mV/V × 0.33 V |
| Voltage reference | — | *excluded* | — | README note 2 |
| **Statistical RSS** | | **4.84 mV** | | |
| **Deterministic sum** | | **2.56 mV** | | |
| **Total static** | | **7.40 mV** | | vs 18 mV available — **2.4× margin** |
| Load regulation (allowance, #12 verifies) | | 18 mV | | |
| **Total against the ±36 mV window** | | **25.4 mV** | | **29 % margin** |

### 3.1 Amplifier random offset (calculated, from measured Pelgrom data)

`sim/devchar/CONCLUSIONS.md` §2 measured diode-connected `nfet_03v3`/
`pfet_03v3` pairs at three areas and extracted **A_VT ≈ 7.2–8.4 mV·µm** for
both polarities, on a clean 1/√area trend. The worst end (8.4) is used here.
That coefficient is a *composite* — it was extracted from measured σ(ΔVgs) of
real pairs at those bias points, so it already carries whatever current-factor
mismatch the models apply; there is no separate β-mismatch term to add (and
none is separately published for this PDK).

```
σ(ΔVT, input pair)  = √2 · A_VT / √(W·L) = √2 · 8.4 / √360  = 0.626 mV
σ(ΔVT, mirror load) = √2 · A_VT / √(W·L) = √2 · 8.4 / √64   = 1.485 mV
                      referred to the input by gm(MLD2)/gm(MIN2)
                      = 7.58 µS / 24.58 µS = 0.308           → 0.458 mV
σ(Vos)              = √(0.626² + 0.458²)                     = 0.776 mV
3σ                                                            = 2.33 mV
```

Both areas are design levers and were chosen for this budget: the input pair is
drawn 60 µm × 6 µm = **360 µm²** (not the minimum that would meet gm), and the
mirror is deliberately run at a *high* overdrive (8 µm × 8 µm, `Vov` ≈ 0.29 V)
so its `gm` — and therefore its contribution — is only 31 % of the input pair's.
`gm` values are the simulated operating point at tt/27 °C/3.3 V.

`#13` (Monte Carlo mismatch) should verify **3σ ≤ 2.33 mV input-referred /
3.49 mV output-referred** for the amplifier term. `#15` (floorplan/matching)
should treat 360 µm² of input-pair area, common-centroid with dummies, as the
budgeted requirement.

### 3.2 Divider mismatch — a stated assumption, not a simulated result

README note 3 and `sim/devchar/CONCLUSIONS.md` §2 are explicit: this PDK's
resistor subcircuits hard-code `mis_r = 0`, and the high-sheet `ppolyf_u_*k`
cards carry no mismatch term at all — a matched pair returns bit-identical
values over 200 Monte Carlo runs at every area and temperature. **A Monte Carlo
"pass" against these models is not evidence for this row and must not be cited
as one.**

The number above is hand-computed from the disabled coefficient the PDK authors
left in the file, `ppolyf_u`'s `par_r = 0.021`, in the card's own
`σ = 0.7071 · par_r · 1 µm / √area` form, applied as a proxy for the 3k flavour
(note 3 sanctions exactly this proxy):

```
divider in ppolyf_u_3k  (0.318 µm²/kΩ):  Rtop 300 k → 95 µm²,  Rbot 600 k → 191 µm²
σ(Rtop)/Rtop = 0.7071·0.021/√95  = 0.152 %
σ(Rbot)/Rbot = 0.7071·0.021/√191 = 0.107 %
δVout/Vout   = (1−β)·√(σt² + σb²) = (1/3)·0.187 %  = 0.0623 %   (1σ)
             → 1.12 mV (1σ) → 3.36 mV (3σ) at 1.8 V
```

The area lever is large and worth stating for #15: drawing the same 900 kΩ in
low-sheet `ppolyf_u` costs **8.5× the area** (2421 µm² vs 286 µm²) and cuts this
term to **1.15 mV (3σ)**. At 3.36 mV the budget already closes with 2.4×
margin, so the dense flavour is the recommendation; the low-sheet option is the
escape hatch if silicon shows the `par_r` proxy to be optimistic.

### 3.3 Systematic offset (measured)

The open-loop bench's DC servo settles at whatever input difference makes
`OUT` sit at the chosen operating point; that residual *is* the systematic
(matched-device) offset. Measured **+280 µV … +610 µV** across all 81 PVT
points — one-sided, and 3–7× under the 2 mV allocation the testbench checks
against. It is deterministic (not a mismatch term), so it adds linearly.

---

## 4. PSRR budget

**The mechanism.** With the pass device's source on VIN and its gate on the
amplifier output, writing `G = ∂V(OUT)/∂VDD` (how well the amp's output rides
the supply) and `A` for the amp's gain from the feedback node:

```
vout/vdd = [gm_p·(1 − G) + 1/ro_p] / [1/Zout + 1/ro_p + gm_p·A·β]
         ≈ (1 − G) / (A·β)                    (loop term dominates)

PSRR(f)  ≈ A(f) · β / |1 − G(f)|
```

`Zout`, `ro_p` and `gm_p` all cancel. **PSRR at 1 kHz is an amplifier property,
not a pass-device property** — which is exactly the survey's §3.2 claim, now
with the algebra attached, and it is why the budget is spent on amp gain and
bandwidth rather than on the pass-device topology.

**The split.** The whole 50 dB is budgeted to the amplifier's gain alone, with
`|1 − G|` forced to 1 (i.e. the pessimistic "gate pinned while VIN moves"
case). Supply tracking is then pure unbudgeted margin:

| Budget line | Requirement | Measured (81 points) | Verdict |
|---|---|---|---|
| Amp gain at 1 kHz, `A(1k)` | ≥ 50 − 20·log₁₀(2/3) = **53.5 dB** | **57.3 … 66.5 dB** | PASS, ≥ 3.8 dB margin |
| Same, light-load operating point (README note 1 binds PSRR at light load) | ≥ 53.5 dB | **57.2 … 66.5 dB** | PASS |
| **Budgeted PSRR = A·β** | ≥ **50 dB** | **53.7 … 63.0 dB** (mean 58.4) | **PASS at all 81 points** |
| Stretch: budgeted PSRR ≥ 60 dB | — | met at 33/81 points, mean 58.4 dB | not claimed |
| Supply-to-output coupling `G` at 1 kHz | must not degrade `|1 − G|` | **0.97 … 1.21 V/V** | tracks the rail — helps |
| PSRR *including* the measured tracking | — | **61.8 … 85.5 dB** | margin, not claimed |

The measured `G ≈ 1` is worth a sentence: the amplifier's output rides the
supply almost exactly, so the pass device's `Vsg` barely moves with VIN. That
is the ideal behaviour for a PMOS pass device and it comes for free from the
supply-referenced bias (§5), but it is **not** budgeted — a record that leaned
on `|1 − G|` would be claiming a first-order cancellation between an amplifier
and a pass device that this bench does not contain.

**100 kHz.** The ratified row also asks for > 20 dB @ 100 kHz. Amp gain at
100 kHz measures 17.2 … 26.5 dB, i.e. a budgeted `A·β` of 13.7 … 23.0 dB —
which does **not** clear 20 dB on gain alone at every corner. That is expected
and is not a miss against the spec: DR-0004's own basis for the 100 kHz row is
that "above crossover, PSRR is carried by the output capacitor rather than loop
gain". The 100 kHz row is therefore a closed-loop claim for #12 to measure with
`C_eff` present; this record states the amplifier's contribution to it and
nothing more.

---

## 5. Current (Iq) budget

Whole-regulator allocation from `spec/architecture-survey.md` §5, against the
ratified `Iq < 30 µA` row (binding corner ff/125 °C/3.63 V):

| Block | Survey allocation | This design | Basis |
|---|---|---|---|
| Feedback divider | 1–3 µA | **2.0 µA** | 1.8 V / 900 kΩ, `ldo_core` (DR-0003's number exactly) |
| Reference (black box, not this issue) | 3–5 µA | 3–5 µA assumed | no bandgap block exists yet |
| **Error amp** | **10–15 µA** | **9.0 µA nominal, 5.8–14.3 µA over PVT** | measured, `sim/amp-openloop` |
| Pass-gate bias / misc | 2–3 µA | 0 µA so far | the amp needs no external bias; current limit is #11 |
| Pass-device off-state leakage | — | 0.417 µA at ff/125 °C | `sim/devchar/CONCLUSIONS.md` §1 |
| **Total, worst amp corner** | 16–26 µA | **≈ 21.7 µA** (14.3 + 2.0 + 5.0 + 0.4) | **27 % margin under 30 µA** |

Within the amplifier, nominal (tt/27 °C/3.3 V, simulated op point): bias branch
2.44 µA, stage-1 tail 2.43 µA, stage-2 sink 4.18 µA.

**Where the 2.5× PVT spread comes from.** The bias is supply-referenced,
`Iref = (VDD − Vgs(MB1))/Rbias`, so it moves with supply (±13 % over
2.97–3.63 V), with `Vgs` (temperature and MOS corner), and with `Rbias` (the
`res_ff`/`res_ss` sections move `ppolyf_u_1k` ±20 %). Those compound to
5.8–14.3 µA. The alternative — a beta-multiplier constant-gm reference — would
cut the supply term but needs a start-up circuit (the beta-multiplier has a
stable zero-current state; this topology has none) whose own leakage branch
costs a comparable fraction of a 9 µA budget. The spread is inside the
allocation, so the simpler bias is kept; **if a later issue needs a tighter
Iq or a supply-independent bias, that is the lever to pull, and it costs a
start-up circuit.**

The **10 µA stretch** row is *not* met by this design: the amplifier alone is
9 µA nominal. Reaching it would mean the survey's fallback (a 5T single-stage
OTA at 3–6 µA), whose 40–50 dB of gain cannot supply the 53.5 dB at 1 kHz the
PSRR row needs — the two stretch goals are in direct conflict, and the ratified
row (< 30 µA) is met with margin.

---

## 6. What this hands to #10 (stability), and the honest warning

Measured amplifier properties across 81 PVT points, driving the measured
6.14 pF pass gate:

| Property | Measured | Note |
|---|---|---|
| DC gain `A0` | 110.1 … 114.7 dB | at the OUT = 2.0 V operating point |
| Unity-gain bandwidth | **650 kHz … 2.16 MHz** | mean 1.22 MHz |
| Amp phase margin | **49.1° … 69.9°** | its own loop, driving 6.14 pF |
| Amp dominant pole | ≈ 2.6 Hz | `UGBW/A0`, Miller-set |
| **Amp phase at 1 kHz** | **−89.7° … −90.0°** | already a full 90° |
| Slew rate, OUT falling | **0.68 V/µs** | `I(M2N)/C_L` = 4.18 µA / 6.14 pF |
| Slew rate, stage-1 limited | 0.79 V/µs | `I(tail)/Cc` = 2.43 µA / 3.06 pF |
| Gate drive, low | ≤ 3.8 µV above VSS | at Vin = 2.10 V, pass device on hard |
| Gate drive, high | within 1.7 mV of VDD | pass device off |

**The warning, stated rather than left for #10 to discover.** The issue asked
for the amplifier's phase contribution at crossover instead of an assumption
that the ESR zero will cover for it. Here it is: by 1 kHz this amplifier is
already contributing a **full 90°** of phase — it is deep in its single-pole
region, two decades above its own dominant pole. Projecting the loop crossover
with `C_out` = 1 µF,

```
f_c ≈ √( UGBW · gm_pass · β / (2π·C_out) )
    ≈ 62 kHz   at I_load = 1 mA   (gm_pass ≈ 30 mS)
    ≈ 175 kHz  at I_load = 50 mA  (gm_pass ≈ 240 mS)
```

both the amplifier's dominant pole (2.6 Hz) and the output pole (0.2 Hz at no
load, 88 Hz at 1 mA, 4.4 kHz at 50 mA) sit **below** crossover. The loop is
therefore rolling off at −40 dB/dec where it crosses unity, and **DR-0001
forbids buying the missing phase back with a minimum-ESR zero**. The loop needs
a zero that does not depend on ESR. The conventional one is a feedforward
capacitor across `Rtop` — `Cff` = 10 pF across 300 kΩ puts a zero at 53 kHz and
its companion pole at 80 kHz, i.e. exactly in the band above — and it costs no
quiescent current. Choosing it (or trading amplifier UGBW down against the
PSRR margin in §4, the other lever) is **#10's decision**, not this issue's;
what #9 owes #10 is the numbers above and the statement that the loop is not
stable without one.

Note also that the amp's *falling* slew rate (0.68 V/µs) is the slower
direction, and falling is the direction a load step demands: a 1 → 50 mA step
needs roughly 0.4 V of gate swing, so ~0.6 µs of slewing precedes linear
settling. Against the ratified 20 µs recovery window that is comfortable, but
it is the number to revisit if #12's transient record comes in tight; the lever
is `M2N`'s current.

---

## 7. Handoffs

| Issue | What to take |
|---|---|
| **#10 stability** | §6 in full: UGBW, PM, phase at 1 kHz, slew, gate load, and the "needs an ESR-independent zero" statement |
| **#11 current limit / enable** | **The 5-port interface has no enable pin.** This cell draws its bias whenever VDD is present (≈ 9 µA); `ldo_core`'s `Men` clamp turns the *pass device* off but not the amplifier. `sim/op-point-sanity/records/20260801-002928-712cb87.md` measures the disabled state directly (9.24 uA). The ratified "shutdown Iq < 3 µA" row therefore cannot be met without either gating this cell's supply or renegotiating the pinout to add EN — an interface decision, so it is flagged here, not made here |
| **#12 testbench suite** | PSRR at 100 kHz is a closed-loop claim (§4); load/line regulation ride on the 110 dB DC gain; the falling-slew number above bounds the transient |
| **#13 Monte Carlo mismatch** | §3's split: verify 3σ ≤ 2.33 mV input-referred for the amplifier. Do **not** cite a PDK Monte Carlo for the divider term — §3.2 |
| **#15 floorplan / matching** | 360 µm² of common-centroid input-pair area and 64 µm² mirror devices are budgeted requirements, not suggestions; the divider needs ≥ 95/191 µm² unit-resistor legs for §3.2's number |

## 8. Area

Rough active area, for the < 0.1 mm² core row (excludes routing and the pass
device):

| Item | Area |
|---|---|
| `Rbias` (1 µm × 1000 µm, `ppolyf_u_1k`) | 1000 µm² |
| `Cc` (39 µm × 39 µm MIM) | 1521 µm² |
| Transistor gate area (all 8 devices) | ≈ 1240 µm² |
| `Rz` | 109 µm² |
| **Total** | **≈ 3870 µm² ≈ 0.0039 mm²** — 3.9 % of the core budget |
