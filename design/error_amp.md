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

> **Read §6.6, §6.7 and §6.10 first (issue #53).** §6.2–§6.5 were written as
> though the `Rz`/`Cc` network's own *local* feedback loop were stable. DR-0008
> measured that it was not — the cell oscillated at ≈ 500 kHz at every PVT
> corner (§6.6) — and §6.7 is what happened when that was fixed and the
> matrix re-measured. **§6.4's "2689/3240 passing" is superseded twice over:
> once as not being a stability result at all, and once by the real number,
> 785/3240.** §6.8 and §6.9 record two rounds of negative results against the
> first candidate DR-0009 named to close the 48-point residue that left at
> 0.1 mA — read them before re-trying a super-source-follower sense device
> around `Mbuf` in any form. **§6.10 is what closed it**, and it is neither of
> DR-0009's candidates: the shelf's upper corner is `f_2 = 1/(2π·Rz·Cf)`, so
> the shelf is `Cc/Cf` wide and *`Cf`*, not Iq, is the lever. The 0.1 mA
> column now passes **756/756**; 1–50 mA does not, and remains DR-0009
> Candidate 2's brief.
>
> - `sim/loop-stability/records/20260802-171044-db620a6.md` — **1332/4536** on
>   the ratified matrix at its current size (issue #54's `res_ff`/`res_ss`
>   corners included), of which **756/756 at 0.1 mA** (was 686/756), and
>   **0 of 4536** points show gain resurgence above crossover. 77 points
>   outside the 0.1 mA column trade PASS → FAIL against 310 the other way;
>   see §6.10.
> - `sim/enable-shutdown/records/20260802-172454-b90b2ba.md` — all four
>   ratified clauses PASS at **63 of 63** corners; enabled Iq 24.81 µA at the
>   binding corner against the ratified < 30 µA (was 23.58).
> - `sim/amp-openloop/records/20260802-163812-deb3dbd.md` — `peak_excess_db`
>   −0.10…+0.17 dB at **81 of 81** points (was +5.4…+12.2 before DR-0008's
>   fix, −0.36…−0.13 after it), and `gain_1k_db` 54.57 dB worst corner
>   against a 53.5 dB budget line that had 0.04 dB of margin.
> - `sim/amp-selfosc/records/20260802-164210-7c2ff06.md` — settled, undriven
>   transient at the light operating point: **0.028…0.44 µV** pk-pk on `BG`
>   (was 476…1420 mV before DR-0008's fix). The heavy rows still ring, and
>   that is the LDO loop, not this cell — see §6.7.
> - `sim/psrr-dc/records/20260802-164053-c999cb4.md` — `psrr_ldo_1k_db`
>   **51.04 dB** worst corner against the ratified 50 dB row (was 50.08).
> - `spec/decision-records/DR-0008-loop-gain-rhp-pole-precondition.md`,
>   `DR-0009-shelf-corner-vs-crossover-frontier.md`,
>   `DR-0010-buffer-sense-device-negative-result.md`,
>   `DR-0011-isolated-sense-bias-negative-result.md` and
>   `DR-0012-shelf-width-is-cc-over-cf.md`.

---

> **Issue #51 amendment (2026-08-01).** This document was written for the
> cell as issue #9 shipped it: a two-stage Miller-compensated OTA driving the
> pass gate directly. #51 changed two things in `design/error_amp.sch` to
> close DR-0001's loop-stability row — a **class-AB gate buffer**
> (`Mbuf`/`Mbufb`/`Mpgn`/`Rbufb`) between stage 2 and `OUT`, and a **Type-II
> gain-shelf Miller network** (`Rz` raised from ~30 kΩ to 6 MΩ, `Cc` set to
> 4.80 pF). §6 is rewritten below for the result; §4, §5 and §8 carry their
> re-measured numbers. The rationale for each device is in
> `design/error_amp.sch`'s own header (sections `COMPENSATION` and `BUFFER`),
> and the light-load envelope the change does *not* reach is
> `spec/decision-records/DR-0007-light-load-stability-envelope.md`.

## 1. Topology

Two-stage Miller-compensated OTA — candidate 3 of
`spec/architecture-survey.md` §5 — with #51's class-AB gate buffer on the
output, i.e. candidate 3 *and* candidate 2's low-impedance gate driver.

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

> The device sizes in this table are issue #9's, kept for the historical
> record. #51 rebuilt the compensation and added the buffer, and **§6.10
> (issue #53) resized `M2P` to 60 µm/1 µm, `Mbuf` to 60 µm/0.5 µm, `Mbufb`
> to 100 µm/1 µm, `Cf1`/`Cf2` to 7 × 7 µm and `MTAIL` to 6.6 µm/4 µm**.
> `design/error_amp.sch` is always the authority on sizes.

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

| Budget line | Requirement | Measured (81 points, #9) | Re-measured (81 points, #51) | Re-measured (81 points, #53 §6.10) | Verdict |
|---|---|---|---|---|---|
| Amp gain at 1 kHz, `A(1k)` | ≥ 50 − 20·log₁₀(2/3) = **53.5 dB** | **57.3 … 66.5 dB** | **53.5 … 62.7 dB** | **54.57 … 63.68 dB** | PASS — the margin was 0.04 dB at the worst corner and is now **1.07 dB** |
| Same, light-load operating point (README note 1 binds PSRR at light load) | ≥ 53.5 dB | **57.2 … 66.5 dB** | **53.5 … 62.6 dB** | **54.56 … 63.66 dB** | PASS |
| **Budgeted PSRR = A·β** | ≥ **50 dB** | **53.7 … 63.0 dB** (mean 58.4) | **50.0 … 59.1 dB** (mean 54.6) | **51.04 … 60.16 dB** (mean 55.6) | **PASS at all 81 points**, 1.04 dB at the worst |

**#53 amendment.** §6.10's +10 % input-pair tail current raises `gm(MIN)`,
and `A(1k) = gm(MIN)/(2π·Cc·1 kHz)` is this whole budget — so the row that
had 0.04 dB of margin now has 1.07 dB, and the closed-loop
`psrr_ldo_1k_db` measurement moves 50.08 → **51.04 dB** against the ratified
50 dB (`sim/psrr-dc/records/20260802-164053-c999cb4.md`). The sentence below
about `Cc` still stands, with one change: `Cc` now has ≈ 13 % of headroom
before it re-spends that margin, which DR-0012 counts as ≈ 10 % more gain
shelf and explicitly not as a solution to the 1–50 mA columns.

**Why the margin was spent.** `A(1k)` is `gm(MIN)/(2π·Cc·1 kHz)`, so it is set
by `Cc` — the same component #51's compensation needs *large* to keep light
loads crossing unity on the Type-II shelf. §6.4 states the frontier and
DR-0007 argues it. The number to watch in layout is therefore `Cc`: at 4.80 pF
there is no PSRR margin left to donate to parasitic capacitance on `NZ`/`OUT`.

Superseded rows, for reference — the pre-#51 numbers above are still the
correct reading of `sim/psrr-dc/records/20260801-002908-712cb87.md`; the #51
column is the record that supersedes it.
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
| **Error amp** | **10–15 µA** | **5.4–13.7 µA over PVT** (#51; was 5.8–14.3 µA) | measured, `sim/amp-openloop` |
| Pass-gate bias / misc | 2–3 µA | **≈ 3.6 µA over PVT** | `ldo_ilimit`'s threshold bias + comparator tail, issue #11 (measured: total no-load supply current rises from ≈ 9 µA to 8.8–21.2 µA across PVT with the limit block present, `sim/current-limit/records/`) |
| Pass-device off-state leakage | — | 0.417 µA at ff/125 °C | `sim/devchar/CONCLUSIONS.md` §1 |
| **Total, worst amp corner** | 16–26 µA | **≈ 21.7 µA** (14.3 + 2.0 + 5.0 + 0.4) — **25.3 µA** with #11's limit block | **27 % / 16 % margin under 30 µA** |

Within the amplifier, nominal (tt/27 °C/3.3 V, simulated op point): bias branch
2.44 µA, stage-1 tail 2.43 µA, stage-2 sink 4.18 µA.

Issue #11 measured the *assembled* regulator against this budget rather than
the block allocations: 14.2 µA at tt/27 °C/3.3 V and **22.4 µA at the binding
ff/125 °C/3.63 V corner** with a 50 mA load, i.e. the ratified < 30 µA row is
met with 25 % margin including the current-limit block — and 0.20 µA disabled
(`sim/enable-shutdown/records/`).

**#53 re-measurement (§6.10).** The shelf-widening change spends +10 % of the
input-pair tail and +25 % of the buffer bias, and nothing else: the assembled
regulator measures **9.12–22.00 µA** at the same binding corner
(`sim/quiescent-current/records/20260802-164119-56dae34.md`), i.e. +0.6 µA,
leaving 26 % margin under the ratified < 30 µA row. `sim/enable-shutdown/`
measures the same row on its own 63-corner grid at **24.81 µA** at that
corner, with disabled current unchanged at 0.20 µA and Vin→Vout leakage
unchanged at 0.214 µA
(`sim/enable-shutdown/records/20260802-172454-b90b2ba.md`). The amplifier's
own `iq_ua` reaches 14.98 µA at
`ff`/125 °C/3.63 V against the 15 µA soft block allocation — that allocation,
not the ratified row, is now what bounds this lever.

**#51 re-measurement.** The class-AB gate buffer does **not** cost Iq: the
assembled regulator now measures **8.6–21.4 µA** over the same grid
(`sim/quiescent-current/records/`), i.e. ~1 µA *lower* at the binding corner.
The reason is that stage 2 no longer drives the 6.14 pF pass gate, so `M2N`'s
bias was cut from ~4.1 µA to ~1.6 µA and the difference was spent in the
buffer, where it buys far more pass-gate bandwidth per microamp than it did
in a 9 MΩ-output common-source stage. Disabled current is unchanged at 0.20 µA
(the buffer's three devices are all off with `BG` pulled to VDD by `Mbg_pu`,
`N1` to VDD by `Mn1_pu`, and `NBIAS` to VSS by `Mnb_pd`).

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

## 6. Stability: what #51 built, and what it does not reach

**Superseded content.** §6 previously handed #10 an *unclosed* loop plus a
warning ("this amplifier is already contributing a full 90° by 1 kHz … the
loop is not stable without an ESR-independent zero"). That warning was
correct and #10's record confirmed it: the loop measured a worst-corner phase
margin of −12.89° with **no** compensation change, and −1.26° after #42 added
a feedforward zero. #51 closed it. What follows replaces the projection with
the measurement.

### 6.1 What was wrong, in one line

The loop was a two-pole system everywhere: the amplifier's Miller-set dominant
pole and the load-dependent output pole at `VOUT` both sat far below crossover
at every point of DR-0001's matrix, so the loop rolled off at −40 dB/dec
through unity. For a plain Miller integrator the loop crossover is

```
f_c = sqrt( β · UGBW_amp · gm_pass / (2π·C_out) )
```

and PM ≥ 45° needs `f_c` at or below the output pole — which at 50 mA /
0.33 µF requires `UGBW_amp ≤ 2.3 kHz`, and at 0 mA / 4.7 µF requires
`UGBW_amp ≤ 1 mHz`. Neither is a tuning target; they are why no rescaling of
`Cc` moved the result (#42 measured 3×–100× rescalings and stayed within a
degree of 0°).

### 6.2 The fix

Two changes, and both are needed — either alone measures worse than the
starting point at one end of the load axis:

| Change | What it does | Measured if removed |
|---|---|---|
| `Rz` 30 kΩ → **6 MΩ** (Type-II gain shelf) | above `f_z = 1/(2π·Rz·Cc)` ≈ 5.4 kHz the amplifier's gain shelves at `A_plat = gm(MIN)·Rz` instead of falling, so the loop crosses unity on the output pole **alone** (−20 dB/dec) | the −40 dB/dec loop, i.e. #42's result |
| **Class-AB gate buffer** on `OUT` | stage 2 drives ~0.5 pF instead of the 6.14 pF pass gate, moving the pass-gate pole above the heavy-load crossover | worst PM **−92°** at 50 mA / 0.33 µF |

The buffer's pull-up `Mbufb` is a *replica of `M2P`* rather than a fixed
current source, because a fixed-bias follower cannot pull `OUT` below one
`Vgs` — measured, that costs the whole dropout row (regulation lost at 8 of
15 corners at `Vin` = 2.10 V / 50 mA). `Rbufb` keeps that replica a DC-tracking
source rather than a feedforward path around the compensation (measured
without it: worst PM −167°). Full device-by-device rationale is in
`design/error_amp.sch`'s `BUFFER` section.

### 6.2.1 The interface the buffer broke, and `BG` (#55)

The buffer replaced a class-A output stage whose **sink** was a ~4 µA current
source. Two other cells were sized against exactly that number:
`design/ldo_softstart.sch` and `design/ldo_ilimit.sch` both act on the
regulator by *pulling `PASS_GATE` up*, and both only ever had to out-source a
few microamps to win the node. `Mbuf` is not a current source — it is a
150 µm/1 µm follower that sinks as hard as its Vsg allows — so both clamps
lost the node. Measured, on the same DUT and bench as §6.3:

| | pre-#51 | post-#51 |
|---|---|---|
| enable → 1.764 V | 2289 … 5764 µs | 27.3 … 2015 µs (ramp bypassed) |
| peak supply current, 50 mA startup | 53.2 … 138.9 mA | 141.1 … 366.0 mA |
| corners with startup overshoot > 1.836 V | 9 / 63 | 63 / 63 |
| corners where the limit clamp engages while settled at 50 mA | 6 / 63 | 54 / 63 |

`BG` — the follower's own gate, stage 2's output — is therefore a **port**
(#55). Each clamp cell adds one small PMOS from `VIN` to `BG`, on the same
gate as its existing `PASS_GATE` clamp device, so engaging a clamp *steers*
the buffer instead of fighting it and leaves that clamp arbitrating against
`Mpgn`'s ~0.4 µA — a weaker opponent than the pre-#51 stage. Both added
devices are hard off whenever their clamp is idle, so §6.3's amplifier
properties and the loop result are untouched by construction.

Steering `BG` is **not** a substitute for sourcing into `PASS_GATE`. `Mbufb`
is off in exactly the regime the clamps exist for, so a clamp moved to `BG`
has nothing left to charge the pass gate with and no authority at all
(measured: soft-start ramp bypassed outright, overshoot 2.045 V, limit clamp
saturated and still unable to hold the node). The `PASS_GATE` clamp devices
stay; the `BG` devices are additions.

### 6.3 Measured amplifier properties (81 PVT points, `sim/amp-openloop/`)

| Property | Before (#9) | After (#51) | After (#53 §6.10) |
|---|---|---|---|
| DC gain `A0` | 110.1 … 114.7 dB | 109.0 … 115.7 dB | 105.9 … 113.1 dB |
| Gain at 1 kHz | 57.3 … 66.5 dB | **53.5 … 62.7 dB** (floor: 53.5 dB) | **54.6 … 63.7 dB** |
| Unity-gain bandwidth | 0.65 … 2.16 MHz | 1.82 … 4.31 MHz | 3.07 … 7.80 MHz |
| Systematic offset | 282 … 611 µV | 335 … 764 µV | 332 … 771 µV |
| Amplifier Iq | 5.8 … 14.3 µA | **5.4 … 13.7 µA** | **5.9 … 15.0 µA** |
| Gate drive, low | ≤ 3.8 µV above VSS | ≤ 30 µV above VSS | ≤ 49 µV above VSS |

Whole-regulator numbers moved the same way: Iq **8.6 … 21.4 µA** against the
ratified < 30 µA row (the pre-#51 design measured 22.4 µA — the buffer is
*cheaper* than the stage-2 bias it replaced), and dropout 300.4 … 300.9 mV
against the pre-#51 300.4 … 300.7 mV.

### 6.4 The result, and the frontier it sits on

Against DR-0001's full 3240-point matrix
(`sim/loop-stability/records/20260801-191742-84f67b8.md`, superseding
`20260801-140530-d6d47f5`): **2689/3240 points pass**, against 150/3240
before. Every remaining failure is at one of the two lightest loads —

| `I_load` | passing | how the failures fail |
|---|---|---|
| 1, 10, 25, 50 mA | **2160/2160** | — |
| 0.1 mA | 525/540 | 15 points, all at −40 °C / 3.63 V on `ss`/`fs`, all on **gain margin** (PM 67…102°, GM −20.7…+7.9 dB): conditional stability, not a phase collapse. **§6.6/§6.7 supersede this reading**: the amplifier's own local loop was unstable while this record was taken, so these phase/gain numbers are not a stability result at all — see §6.7 for what the same 0.1 mA column reads once that precondition holds. |
| 0 mA | 4/540 | phase margin, worst **3.79°** at `ff_125c_2.97v` / 4.7 µF / 1 mΩ |

That split is structural, not a tuning residue. `Rz` and `Cc` are pinned
between two ratified rows pulling in opposite directions on the same two
components:

- `Rz·sqrt(Cc)` sets how light a load still crosses unity on the shelf.
  **Measured ceiling on `Rz`**: 6 MΩ passes 0.1–50 mA everywhere; 7 MΩ already
  loses corners at 1–50 mA (the heavy-load crossover climbs past the buffer
  and BG poles); 9 MΩ loses them all.
- `gm(MIN)/Cc` **is** the amplifier's 1 kHz gain, i.e. §4's PSRR budget.
  **Measured ceiling on `Cc`**: 4.80 pF gives worst-corner `psrr_ldo_1k_db`
  = 50.0 dB against the ratified 50 dB floor; 7.4 pF measures 46.3 dB, a hard
  FAIL.

This cell sits **on** that frontier — 53.5 dB against a 53.5 dB gain floor and
45.4° against a 45° PM floor at the same time. Reaching 0 mA from there needs
`Rz·sqrt(Cc)` ≈ 12× larger, and with `Rz` at its ceiling that has to come from
`Cc` alone — which therefore grows as the **square** of that, ≥ 150×, because
the worst 0 mA point crosses unity *below* `f_z` where the loop rolls off at
−40 dB/dec (`|T| ∝ 1/(f²·Cc)`; the measured crossover scales as
`1/sqrt(C_out)`, confirming it). That is `Cc` ≥ 0.70 nF, i.e. ≥ 0.35 mm² of
MIM — 3.5× the whole core-area row for one capacitor — **and** it drops the
amplifier's 1 kHz gain onto the Type-II shelf plateau, ≈ 15 dB down (53.5 dB
→ ≈ 38.5 dB), taking the ratified PSRR row from 50.0 dB to ≈ 35 dB. Note the
`1/Cc` gain law saturates there: past `Cc` ≈ 27 pF the 1 kHz gain sits on the
plateau `gm(MIN)·Rz` and stops falling, so 15 dB is the *whole* PSRR penalty
available — and it is already fatal, and area cannot buy it back. The full
argument, the alternatives (preload, `C_eff` floor, re-topology) and the
proposed spec change are
`spec/decision-records/DR-0007-light-load-stability-envelope.md`.

### 6.5 What this hands to layout (#15/#16)

Two parameters are now on a frontier and therefore layout-sensitive, and both
need to be constraints in the floorplan rather than discoveries in extraction:

- `Rz` is a 6 MΩ `ppolyf_u_1k` serpentine sitting directly in the compensation
  path; its distributed capacitance to substrate is not a parasitic to absorb
  later. Its **process** spread is also not covered by present evidence —
  `sim/loop-stability/`'s corner axis varies the MOS sections only and holds
  `res_*` typical, while the measured frontier is steep in `Rz` (6 MΩ passes,
  7 MΩ does not). A resistor-corner axis on that matrix is a required
  follow-up.
- `Cc` at 4.80 pF has ≈ 0 dB of PSRR margin, so any parasitic capacitance
  added to the `NZ`/`OUT` net comes straight off the ratified PSRR row.
- **(§6.7/§6.10, issue #53)** `Cf1`/`Cf2` is ≈ 49 fF built as two 7 µm MIM in
  series, so its mid-node `NF` floats and its bottom-plate parasitic to
  substrate is *in series with the value*, not a stray to absorb. Extraction
  must report `Cf` as the two-terminal `N1`→`BG` value, and the layout should
  put the two devices' bottom plates on the same net so the parasitic adds
  predictably rather than skewing the series ratio. **This is now the most
  layout-sensitive component in the cell**: §6.10 makes `Cf` the component
  that sets the shelf's upper corner `f_2 = 1/(2π·Rz·Cf)` *and* the one that
  decides whether the cell oscillates at all, and at 49 fF the parasitic is a
  larger fraction of the value than it was at 149 fF. It is the first thing
  #16's post-layout re-run should check. Note the sign of the risk is
  two-sided: extra parasitic in series *reduces* `Cf`, which raises `f_2`
  (good for the shelf) and lowers the local loop's own non-dominant pole
  (bad — `peak_excess_db` has +0.83 dB of headroom, not more).

### 6.6 The local loop this compensation closes is unstable (issue #53)

> **Everything in §6.2–§6.5 above is written as if the numbers in
> `sim/loop-stability/records/20260801-191742-84f67b8.md` were a stability
> result. Issue #53 measured that they are not.** §6.6 is the correction and
> it takes precedence over §6.4's reading; the measurements in §6.3 (gain,
> UGBW, offset, Iq) are unaffected, because they are not stability claims.

`Rz`/`Cc` is not only the LDO loop's compensation: it is itself a **feedback
loop**, from `N1` around the stage-2 driver `M2P` and the class-AB gate
buffer and back to `OUT`. That local loop stays closed when the LDO loop is
broken at `ERRAMP_OUT`/`PASS_GATE`, which is exactly the condition
`sim/loop-stability/` measures in — so its stability is a **precondition**
for reading a Bode phase/gain margin off `T(s)` at all, not a detail.

Above `f_z` the feedback impedance is `Rz` (that is the whole point of the
shelf), so the local loop becomes a **resistively** closed loop around a
forward path with three high-impedance-ish poles — `N1`, `BG`, and the pass
gate at `1/gm(Mbuf)·6.14 pF` — and nothing compensates it. Raising `Rz` from
~30 kΩ to 6 MΩ moved `f_z` from ~1.7 MHz down to ~5.4 kHz, i.e. it took the
local loop's own Miller compensation away across the entire band the LDO
loop uses. Measured consequences, all against `design/` as committed:

| Measurement | Result |
|---|---|
| Amplifier alone (`sim/amp-openloop/`'s servo, 6.14 pF load), `ss`/−40 °C/3.63 V | gain **peaks at 55.9 dB (heavy op point) / 58.7 dB (light)** at 502 kHz, with the continuous phase **advancing** from −15° to +134° through it |
| Same, every corner tried (`tt`/27, `ss`/−40, `ff`/−40, `fs`/−40, `sf`/−40, `ss`/125) | a peak of **21…58 dB** at 420…750 kHz at **all** of them |
| `sim/amp-selfosc/` — settled, undriven, `tt`/27 °C/3.30 V, 50 mA, 0.33 µF | `BG` **3.31 V pk-pk**, pass gate **2.14 V pk-pk**, `VOUT` **372 mV pk-pk**, mean `VOUT` 1.787 V |
| Same bench, 0.1 mA at the same corner | 0.37 µV / 0.34 µV — quiet, which is why the 0.1 mA column looked like the whole problem |

A gain peak with a **+180° phase advance** is a right-half-plane complex
pole pair, and the transient confirms it: the amplifier oscillates. The
`+180°` is also precisely why none of this was visible. `sim/amp-openloop/`'s
`pm_deg` is `180 + vp(...)` and `vp()` **wraps** to (−180, 180], so a forward
path carrying 288° of lag reports **252°** of "phase margin" and clears its
own `≥ 45°` bar — which is the 247.6…256.4° column in
`sim/amp-openloop/records/20260801-193812-84f67b8.md`, against 49.0…69.8° for
the pre-#51 cell. In the LDO loop the same rotation puts the 0 dB crossing
*above* the resonance, so `sim/loop-stability/` reports a large positive
phase margin at 2160 heavy-load points where `|T|` had already climbed back
above unity (684 of 720 sampled points do, worst **+52.5 dB**).

**What this does to §6.4's frontier.** The `Rz` ceiling quoted there
(6 MΩ passes, 7 MΩ loses corners) was measured through this artifact and is
not a reliable bound. So is DR-0007's reading of the 15 outliers at 0.1 mA:
they are the subset of the resonance's footprint where the phase falls
through −180° *below* crossover rather than leading through it above, which
is why they present as a gain-margin failure with a 67…102° phase margin and
why they cluster at one corner of the bias spread without the bias being the
cause.

**Two levers were measured against it** (issue #53; both recorded in
`spec/decision-records/DR-0008-loop-gain-rhp-pole-precondition.md` so the
next attempt does not repeat them):

- A **constant-gm (beta-multiplier) bias** — DR-0007's and #53's suggested
  direction — makes all 15 points *report* a pass while leaving `|T|` above
  unity after crossover at 38 of the same 72 points (worst +15.3 dB). It
  would have shipped a false pass. It also does not deliver what it was
  added for: its start-up injector puts a supply-referenced 0.23…0.91 µA
  into `NBIAS` (18–27 % of the branch current), and the branch current still
  spreads **2.6×** against this bias's 2.5×.
- A **small capacitor across `Rz`** (`Cf`, `N1`→`OUT`, 50…200 fF) restores
  the local loop's pole-splitting above the shelf and **works** at light
  load: no gain resurgence anywhere in the 72 target points (worst `|T|`
  above crossover −4.2 dB vs +26.1 dB), and the `ss`/−40 °C/3.63 V transient
  goes from 0.95 V pk-pk on `BG` to **150 nV**. Holding `Cc + Cf` at #51's
  4.825 pF makes it PSRR-neutral by construction (worst-corner
  `psrr_ldo_1k_db` 50.03 dB, amp gain at 1 kHz 53.55 dB — both a hair
  *better* than the committed cell). It is **not shippable as it stands**:
  it ends the shelf at `1/(2π·Rz·Cf)`, and the 50 mA crossover (1.2…1.6 MHz)
  sits above that corner, so 616 of 720 points at 1–50 mA then fail on phase
  margin.

Those two bound the next design step. The resonance can be damped cheaply
and without spending PSRR — but not while the loop also needs a flat ~43 dB
shelf out past 1.6 MHz. **Separating the shelf's upper corner from the
heavy-load crossover is the problem to solve**, and neither `Rz`/`Cc` alone
nor the bias branch is the lever that separates them.

### 6.7 The local loop is fixed, and the real envelope is 0.1 mA (issue #53)

**The fix.** `Cf1`/`Cf2` — two 12 × 12 µm MIM in **series**, ≈ 149 fF, from
`N1` to `BG` — is a Miller capacitor around the stage-2 driver `M2P` alone.
§6.6's local loop failed because two poles sat below its crossover: `BG` at
≈ 13 kHz (`ro(M2P)‖ro(M2N)` = 24 MΩ against `Cgs(Mbuf)` ≈ 0.5 pF, measured
op point) and `Rz` against `N1`'s ≈ 0.9 pF at ≈ 30 kHz, under a forward gain
of `gm(M2P)·R_BG` = 813. A Miller cap across `M2P` splits exactly that pair:
`N1`'s pole falls by the Miller factor and `BG`'s rises to
`gm(M2P)/(2π·Cgs(Mbuf))` ≈ 10 MHz, leaving one pole below crossover.

Two implementation notes, both measured rather than assumed:

- **To `BG`, not across `Rz`.** §6.6's second lever (a cap `N1`→`OUT` across
  `Rz`) works too, but it encloses *two* gain stages instead of one and so
  needs ≈ 3× more capacitance for the same margin — measured, ≈ 400 fF vs
  149 fF at the same `peak_excess_db`. That capacitance is subtracted from
  the amplifier's 1 kHz gain, i.e. from §4's PSRR budget, which is why the
  cheaper connection matters: `Cc` only had to come down 49 µm → 48 µm to
  keep the gain floor, and the floor came out *better* than before (worst-
  corner `psrr_ldo_1k_db` 50.08 dB vs the committed cell's 50.02 dB, against
  the ratified 50 dB bar).
- **A series pair, not one small MIM.** ≈ 149 fF as a single square MIM is
  about 8 µm on a side; two 12 µm devices in series reach it without drawing
  a MIM below the 5 µm width the `cap_mim_2f0` model's own `c_vcr` branch is
  cut at. The floating mid-node `NF` is defined by the model's leak
  resistors. Layout must treat the mid-node's bottom-plate parasitic as part
  of the value (§6.5).

**What it bought, over the whole PVT grid**, measured against the design
state issue #55 (`BG`-steer, PR #62) landed just before this fix — the
correct baseline, since that is what is on `origin/main` today:

| Row | Before (`3668aca`, issue #55's state) | After (this issue) |
|---|---|---|
| `sim/amp-openloop/` `peak_excess_db` (bar ≤ 1 dB), 81 points | FAIL at **81/81** | **−0.36 … −0.13 dB, PASS at 81/81** |
| `sim/amp-selfosc/` light rows (bar ≤ 1 mV pk-pk) | `BG` in the hundreds-of-mV to low-V range, FAIL | **0.13 … 0.43 µV, PASS at 45/45** |
| `sim/loop-stability/` gain resurgence above crossover, 3240 points | resurging at a large fraction of the matrix | **0 resurging**, worst −0.17 dB |
| PSRR, worst-corner `psrr_ldo_1k_db` (bar ≥ 50 dB) | 50.02 dB | **50.08 dB** |
| Amp Iq | 8.6 … 21.4 µA (whole-regulator) | **unchanged** — no device current moved |

**What it did not buy.** With DR-0001's Bode criterion finally applicable,
`sim/loop-stability/records/20260802-095235-c828e73.md` reads **785/3240**,
and the passing points are the *light* loads, not the heavy ones:

| `I_load` | 0.33 µF | 1 µF | 4.7 µF |
|---|---|---|---|
| 0.1 mA | 136/180 | **180/180** | 176/180 |
| 1 mA | 0/180 | 56/180 | **180/180** |
| 10 mA | 0/180 | 0/180 | 51/180 |
| 25 mA | 0/180 | 0/180 | 6/180 |
| 50 mA | 0/180 | 0/180 | 0/180 |

> **Corrected by §6.10.** The next paragraph is right that the local loop's
> crossover is the shelf's upper corner, and right that its *ceiling* is set
> by Iq. It is wrong that `f_2` itself is: `f_2 = 1/(2π·Rz·Cf)`, and the cell
> was sitting a factor of three below its own ceiling. Read §6.10 before
> acting on the sentence "`f_2` … is set by Iq, and it does not scale".

The mechanism is §6.4's frontier with the artifact removed. The local loop's
crossover **is** the shelf's upper corner `f_2` ≈ 180 kHz, and the LDO's
crossover `f_c = β·A_plat·gm_pass/(2π·C_eff)` reaches into the low-MHz range
at 50 mA / 0.33 µF (`gm_pass` rises with load current; `A_plat` does not).
`f_2` is set by `gm(Mbuf)/C_gate` and `gm(M2P)/Cgs(Mbuf)`, i.e. by Iq, and it
does not scale: tripling both currents (amp Iq 8.6 → 16.4 µA, already past
the 15 µA row) moves `f_2` only 131 → 393 kHz. `A_plat` cannot come down to
meet it either, because §4's PSRR budget pins `gm(MIN)/Cc` and that forces
`A_plat` ≥ ≈ 98. The full argument, the three levers, and what this does to
DR-0007's proposed envelope are
`spec/decision-records/DR-0009-shelf-corner-vs-crossover-frontier.md`.

**On issue #53's own terms**: the 15 residual **gain-margin** failures at
0.1 mA are cleared — **0 of 540** points at 0.1 mA fail on gain margin now.
**48** fail on **phase** margin instead, 44 of them at 0.33 µF and cold
(worst 32.4° at `ss`/−40 °C/3.63 V, crossover 144 kHz) and 4 at 4.7 µF at
`ff`/125 °C/2.97 V (worst 42.5°, crossover 6.9 kHz) — the column is pinched
from both ends of the same axis, `f_c` running into `f_2` from below at
0.33 µF and falling back toward `f_z` from above at 4.7 µF.

**Regression check, against the design state on `origin/main` before this
fix.** `Cf1`/`Cf2` adds no device current, so the DC rows cannot move and
were re-measured to confirm it:
`sim/quiescent-current/records/20260802-095514-c828e73.md` (PASS, 45/45,
bit-identical to 5 significant figures),
`sim/dropout-vs-load/records/20260802-100041-c828e73.md` (same pre-existing
300.5–301.0 mV marginal FAIL at 2.10 V, unrelated to this issue and
unchanged to the mV),
`sim/enable-shutdown/records/20260802-095233-c828e73.md` (the four ratified
DC rows unchanged; the large-signal 50 mA startup transient shifts at cold
corners — evidence *for* this section's diagnosis, since the shift tracks
the same 0.6–0.9 MHz resonance this fix damps, not a new defect — with
`sim/startup/` and `sim/current-limit/` spot-checked and unmoved), and
`sim/current-limit/records/20260802-105338-c828e73.md` (bit-identical).

### 6.8 A direct super-source-follower sense device around `Mbuf` — negative result (issue #53)

DR-0009 named a super source follower around `Mbuf` — local feedback that
buys `gm·ro` of output impedance for roughly one extra bias branch — as the
first candidate to try for §6.7's gap. It was tried, twice, against `design/`
as committed here, and neither variant is in this schematic:

- **Sense gate tied to `OUT` directly** (`Msfb`: NMOS, gate `OUT`, source
  `VSS`, drain `BG`, in parallel with `M2N`) gives real but small phase-
  margin improvement (32.37° → 37.09–37.55° at the worst target point,
  `ss`/−40 °C/3.63 V/0.1 mA/0.33 µF) that **plateaus** — doubling the sense
  device's current past a point buys under 2° more, because `OUT`'s fixed
  ≈1.8 V DC level pins the sense device's `Vov` and therefore its `gm`/`Id`
  efficiency, so more gm can only be bought at the same rate a plain
  follower burns it. It also **measurably spends the PSRR budget's last
  margin**: the full 81-point `sim/amp-openloop/` grid (not just the
  worst-corner spot check used while sizing it) shows `gain_1k_db` — the
  1 kHz amp gain §4's PSRR row rides on — dropping to 53.13 dB at
  `ss`/125 °C/2.97 V against the 53.5 dB floor, a corner outside the cold/
  light-load cluster this lever targets.
- **Sense gate AC-coupled from `OUT`, DC-referenced off `NBIAS`** (to avoid
  the first variant's DC-gain interaction) preserves `a0_db` exactly but
  makes phase margin **worse than the unmodified baseline** — 12.64° against
  32.37° — because the DC reference resistor leaks the sensed `OUT` signal
  back into `NBIAS`, the shared bias node every other device in the cell
  (`MTAIL`, `M2N`, `Mpgn`, `MB1`) mirrors from, corrupting the whole
  amplifier's small-signal behaviour rather than adding a local loop around
  `Mbuf` alone.

Full numbers, sizes, and what the next attempt should do differently (a
dedicated, non-shared bias reference for the sense device, or DR-0009's
Candidate 2 — adaptive biasing from a pass-device sense replica — instead):
`spec/decision-records/DR-0010-buffer-sense-device-negative-result.md`. No
`design/` netlist changed for this section; both variants were built,
measured with `--no-write` sweeps, and reverted.

### 6.9 An isolated, dedicated bias reference for the sense device — also negative, and worse (issue #53)

DR-0010's own recommendation for the next attempt was the one bias scheme it
had not tried: a dedicated, diode-connected reference for `Msfb`'s gate,
isolated from every other node's small-signal path. It was built —
`Mref`/`Rref` (a small self-biased diode-connected NMOS, its own branch, not
mirrored or resistor-tapped off `NBIAS`), `Rsfg`/`Csfb` (the same series-MIM
AC-coupling idiom `Cf1`/`Cf2` use), `Msfb` unchanged in connectivity (gate to
the new isolated node, drain `BG`, source `VSS`, parallel with `M2N`), and
`Msfg_pd` (a disable-state pulldown so the new branch does not fight
`Mbg_pu` when `EN=0`) — and it does not work either, for a third and
different reason than either of §6.8's variants:

- It does not blow up Iq (**9.29–12.35 µA**, `ss`/−40 °C, against the
  5.4–13.7 µA baseline band) or reopen DR-0008's local-loop instability
  (`peak_excess_db` **−0.664…−0.659 dB**, well inside the ≤ 1 dB bar) — the
  isolation DR-0010 asked for is genuinely achieved.
- It still collapses the LDO loop's phase/gain margin at the worst-corner
  family far past either §6.8 variant: at `ss`/−40 °C/3.63 V/0.1 mA/0.33 µF,
  **−1.13° PM / −0.58 dB GM** (baseline 32.37°/12.13 dB; §6.8's better
  variant reached +37.09°). Three of the six points checked in this corner
  family go negative on both bars.
- A control with `Msfb`'s drain moved from `BG` to `VSS` (present and
  biased, but disconnected from the signal path) recovers the baseline to
  within 0.5° — isolating the cause to `Msfb`'s connection to `BG` itself,
  not the bias branch. `peak_excess_db` staying clean shows the *local*
  `M2P`/`Mbuf`/`Rz`/`Cc` loop is unaffected; the second local loop `Msfb`
  opens around the same node degrades the *enclosing* LDO loop's margin
  without registering on either single-loop metric this cell's other
  benches check.

**With this record, the super-source-follower family (DR-0009's Candidate 1)
has now been tried with all three bias schemes ever proposed for it — direct
`OUT` reference, shared-`NBIAS` reference, and an isolated dedicated
reference — and none clears DR-0001's bar.** Full numbers, the failed
naive-mirror attempt that preceded the diode-connected version, and the
recommendation to move to DR-0009's Candidate 2 (adaptive biasing from a
pass-device sense replica) instead:
`spec/decision-records/DR-0011-isolated-sense-bias-negative-result.md`. No
`design/` netlist changed for this section; the circuit was built, measured
with `--no-write` sweeps, and reverted.

### 6.10 The shelf is `Cc/Cf` wide, and that closes the 0.1 mA column (issue #53)

**The correction.** §6.7 and DR-0009 identified the shelf's upper corner
`f_2` as the local loop's own crossover, and DR-0009 then treated it as an Iq
quantity ("`f_2` is set by Iq, and it does not scale"). It is not. Above `f_z`
the local loop's gain is `1/(s·Rz·Cf)` — the forward gain `gm(M2P)·Z_BG`
cancels between the Miller impedance at `N1` and the feedback path through
`Rz` — so

```
f_2 = 1/(2*pi*Rz*Cf)        exactly the form of      f_z = 1/(2*pi*Rz*Cc)
shelf width = f_2/f_z = Cc/Cf
```

with no bias current and no `Rz` in it. At §6.7's values (`Cc` = 4.80 pF,
`Cf` = 149 fF) that is a **32×** shelf — 5.4 kHz to 178 kHz — against a
0.1 mA column whose measured crossover spans 6.9 kHz (4.7 µF, hot) to
190 kHz (0.33 µF, cold), a **27× span**. The 48 residual failures were that
27× poking out of both ends of a 32× shelf, and the fix is to widen the
shelf.

**What changed.** Five devices, no new devices, no port change:

| device | before | after | what it does |
|---|---|---|---|
| `Cf1`/`Cf2` | 12 × 12 µm MIM, 149 fF | **7 × 7 µm, 49 fF** | `f_2` 178 → 541 kHz; shelf 32× → 98× |
| `M2P` | 150 µm/2 µm | **60 µm/1 µm** | ⅕ the gate area on `N1` |
| `Mbuf` | 150 µm/1 µm | **60 µm/0.5 µm** | ⅕ the gate area on `BG` |
| `Mbufb` | 200 µm/2 µm | **100 µm/1 µm** | keeps tracking `M2P`, at 1.67× (was 1.33×) |
| `MTAIL` | 6 µm/4 µm | **6.6 µm/4 µm** | +10 % tail: `A_plat`, and the 1 kHz gain |

The two gate-area changes are what make the smaller `Cf` usable. Shrinking
`Cf` raises `f_2` but lowers the local loop's own non-dominant pole, because
that pole is `M2P`'s Miller split, `p2 ≈ gm(M2P)·Cf/(C_N1·C_BG)` — the two
converge and the loop rings, which is DR-0008's defect returning. `C_N1` is
dominated by `Cgs(M2P)` and `C_BG` by `Cgg(Mbuf)`, and both devices sit in
weak inversion (22 nA and 12 nA per square respectively), so their areas can
be cut several-fold with `gm` unchanged. Measured at `Cf` = 36 fF, at the
worst 0.1 mA point (`ss`/−40 °C/3.63 V / 0.33 µF / 1 mΩ): **37.09° / 8.26 dB
with the old gates, 43.50° / 9.84 dB with the new ones** — +6.4° of phase
margin *and* +1.6 dB of gain margin for zero microamps.

The +10 % tail is the only current that moves. It is what reaches the
4.7 µF/hot end of the column, where the crossover was falling back into `f_z`
and `Cf` has no authority at all (measured: 42.48° → 44.12° across a 4×
change in `Cf`, never reaching the bar). It is a two-sided knob — every
microamp helps that end and hurts the 0.33 µF/cold end — and 6.6 µm is the
measured balance point that also keeps `iq_ua` inside its 15 µA allocation.

**`Mpgn` was NOT trimmed, and that is a measurement.** Cutting it 2 µm →
1.2 µm recovers ≈ 0.16 µA and passes every AC bench, then voids a full-matrix
run: at `sf`/−40 °C/3.63 V, 9 of 72 points settle on the non-regulating DC
branch (`VOUT` = −0.70 V) instead of the regulating one. `Mpgn` is the only
thing arbitrating for the regulating branch against `ldo_ilimit`'s clamp, and
the schematic's own note that it "makes the node non-floating for the
operating-point solve" is load-bearing.

**The result** (`sim/loop-stability/records/20260802-171044-db620a6.md`,
supersedes `20260802-151515-2a08fce`; the ratified matrix is 4536 points since
issue #54 added the `res_ff`/`res_ss` resistor corners in PR #66, and this is
a clean-tree run of it in full):

| `I_load` | 0.33 µF | 1 µF | 4.7 µF | row | was |
|---|---|---|---|---|---|
| 0 mA | 13/252 | 0/252 | 0/252 | 13/756 | 0/756 |
| **0.1 mA** | **252/252** | **252/252** | **252/252** | **756/756** | 686/756 |
| 1 mA | 0/252 | 158/252 | 249/252 | 407/756 | 331/756 |
| 10 mA | 0/252 | 0/252 | 87/252 | 87/756 | 74/756 |
| 25 mA | 0/252 | 0/252 | 57/252 | 57/756 | 8/756 |
| 50 mA | 0/252 | 0/252 | 12/252 | 12/756 | 0/756 |
| **total** | | | | **1332/4536** | 1099/4536 |

Worst 0.1 mA point: PM **45.98°** (`ff`/125 °C/2.97 V, 4.7 µF, 1 mΩ) and GM
**13.27 dB** (`res_ss`/−40 °C/2.97 V, 0.33 µF, 1 mΩ), against DR-0001's 45° /
10 dB — 0.98° and 3.27 dB of margin, i.e. the shelf is *just* wide enough for
this column. **0 of 4536** points resurge above crossover, worst −0.07 dB, so
DR-0008's precondition still holds.

Every column improves on net, and none of the others closes — but the net is
not uniform, and the non-uniformity is the shelf's own trade. Against the
superseded record 310 points turn FAIL → PASS and **77 turn PASS → FAIL**
(53 at 10 mA/4.7 µF/200 mΩ, 18 at 1 mA/1 µF/500 mΩ, 3 at 1 mA/4.7 µF/500 mΩ,
3 at 25 mA/4.7 µF/200 mΩ), none of them in the 0.1 mA column and **63 of the
77 failing on gain margin alone with the phase bar still cleared**. A wider
shelf holds `|T|` up over a wider band, so `|T|` at the −180° crossing rises;
that is the same phase-margin-versus-gain-margin trade DR-0012 §1 tabulates at
a probe point, showing up here on the full matrix.

**What it cost, measured on the full grids** — the one row that got worse is
`a0_db`, and it is the only one:

| row | bar | before | after |
|---|---|---|---|
| `gain_1k_db` (`sim/amp-openloop/`) | ≥ 53.5 dB | 53.50 | **54.57** |
| `psrr_ldo_1k_db` (`sim/psrr-dc/`) | ≥ 50 dB, ratified | 50.08 | **51.04** |
| `iq_ua`, amplifier (`sim/amp-openloop/`) | ≤ 15 µA (soft) | 5.4–13.7 | 5.88–14.98 |
| `iq_en_ua`, regulator (`sim/quiescent-current/`) | < 30 µA, ratified | 8.60–21.44 | 9.12–22.00 |
| `peak_excess_db` (`sim/amp-openloop/`) | ≤ 1 dB | −0.36…−0.13 | −0.10…**+0.17** |
| `bg_pp_light_mv` (`sim/amp-selfosc/`) | ≤ 1 mV | 0.16–0.30 µV | 0.028–0.44 µV |
| `vdrop_mv` (`sim/dropout-vs-load/`) | ≤ 300 mV (pre-existing miss) | 300.48–300.98 | 300.48–301.01 |
| `a0_db` (`sim/amp-openloop/`) | ≥ 60 dB | 109.0–115.7 | **105.9–113.1** |

`a0_db` falls ≈ 2 dB because `M2P`'s channel length halves, halving the
stage-2 output resistance. At 105.9 dB it is 46 dB clear of its floor and no
DC row moves.

**What is still not fixed, and what it would take.** 50 mA / 0.33 µF needs
`f_c` ≈ 1.2–1.7 MHz inside the shelf, i.e. `Cc/Cf` ≳ 900 against the 98 this
lands. `Cf` cannot fall below ≈ 45 fF at these gate areas without
`peak_excess_db` going positive (measured: +0.17 dB at 49 fF, +0.40 dB at
43.6 fF, +2.30 dB at 36 fF), and the gate-area lever that would let it is one
step wide and has been taken. `Cc` can now grow ≈ 13 % on the PSRR margin
this change created, which is ≈ 10 % more shelf, not a factor of 9. So the
1–50 mA columns still need the architecture change DR-0009 named — and
DR-0009's Candidate 2 (adaptive biasing from a pass-device sense replica) is
now precisely scoped to them, because it is a load-proportional lever and
both of the 0.1 mA column's failure clusters were at the *same* load. Full
argument, every sweep, and the proposed DR-0007 amendment:
`spec/decision-records/DR-0012-shelf-width-is-cc-over-cf.md`.

### 6.11 `f_2`'s ceiling is `Cc`'s return node, and adaptive bias cannot be the lever (issue #51)

§6.10 hands the 1–50 mA columns to DR-0009's Candidate 2. Issue #51 built it,
measured it, and the answer is no — for a reason that also locates the
constraint that *does* move. Nothing in this subsection changed the schematic;
the full argument, every sweep and the reproduction commands are in
`spec/decision-records/DR-0013-compensation-return-node.md`.

**The frontier, restated in the one free variable.** `f_c/f_z ∝ Rz²` and
`f_2/f_c ∝ 1/Rz²`, so `Rz` slides the LDO's crossover through the shelf
quadratically and the shelf width `Cc/Cf` is the whole budget it has to slide
inside. Measured (`sim/loop-stability/`, `--no-write`, tt/27 °C/3.30 V/1 mΩ,
sweeping only `Rz`), the range of `Rz` that clears both DR-0001 bars at all
three `C_eff` values is `3.8 MΩ … ∞` at 0.1 mA, `1.3 … 1.75 MΩ` at 1 mA, and
**empty at 10, 25 and 50 mA** — the 0.33 µF *gain*-margin ceiling
(≤ 0.30 MΩ) and the 4.7 µF *phase*-margin floor (≥ 0.37–0.45 MΩ) cross by
1.2–1.5×. The load axis on its own is coverable (0.1 mA wants ≥ 3.8 MΩ, 50 mA
wants ≈ 0.25 MΩ) *if* `Rz` can move with load.

**Adaptive `gm(MIN)` works, and cannot be built here.** Scaling `MTAIL`'s
`W/L` 6.6/4 → 0.22/16 by hand (≈ 120× less tail) and changing nothing else
takes 10 mA to 70.43°/23.57 dB, 77.65°/34.16 dB, 48.82°/46.22 dB and 50 mA to
54.45°/17.66 dB, 78.62°/27.69 dB, 62.98°/46.78 dB across 0.33/1/4.7 µF — both
columns passing both bars. But load can only be observed at the pass gate,
which is **this amplifier's own output**, so any scheme that steers a *bias
current* closes `OUT → sense → tail → V_os → OUT` with gain `A_DC·dV_os/dV_OUT`
— `A_DC` is 106–113 dB, and a loop gain below 1 would need `V_os` to move by
< a few µV over the ≈ 300 mV `Vsg(Mpass)` swings. Measured on a built
three-segment adaptive-tail cell: the Tian extraction's DC loop gain went from
+143.3 dB at phase −0.27° (positive real, as a negative-feedback loop must be)
to phase ≈ ±180° at DC, `dcgain_db` 143.3 → 100.7 dB — a minor loop in positive
feedback with gain > 1, i.e. DR-0008's precondition broken by construction. The
only elements that can be adapted without closing that loop are the ones
carrying **no DC current**: `Rz` and the compensation caps.

**And `f_2`'s ceiling is not Iq — it is where `Cc` returns to.** With `Cc` on
`OUT`, the local loop the shelf rides on is
`N1 → M2P → BG → Mbuf → OUT → Cc/Rz → N1`, so it contains the class-AB buffer
and the 6.14 pF pass gate, and its crossover *is* `f_2`. Changing only `Rz`:

| variant | `Rz` | `f_2` | measurement | verdict |
|---|---|---|---|---|
| `Cc` → `OUT` (committed) | 6 MΩ | 541 kHz | `peak_excess_db` −0.13 dB, 81/81 | PASS |
| `Cc` → `OUT` | 3 MΩ | 1.08 MHz | `sim/amp-openloop`, 81 points: **78 CHECK FAILs**, worst **+3.41 dB** | FAIL |
| `Cc` → `OUT` | 0.6 MΩ | 5.4 MHz | DR-0008 resurgence **+1.31 dB** (25 mA) / **+3.74 dB** (50 mA), 0.33 µF | FAIL |
| **`Cc` → `BG`** | **0.75 MΩ** | **4.3 MHz** | `sim/amp-openloop`, 81 points: **PASS 81/81**, `peak_excess_db` −0.077 … −0.030 dB | **PASS** |

Returning `Cc` to `BG` puts it around `M2P` alone — the nodes `Cf1`/`Cf2`
already span — so the buffer and pass gate leave the local loop while
`A_amp = gm(MIN)/(1/(Rz + 1/sCc) + sCf)`, and therefore `f_z`, `f_2`, `A_plat`
and `Cc/Cf`, are algebraically unchanged. **≥ 8× more `f_2` headroom for one
net and zero microamps**, against DR-0009's measured 1.9× of the whole
amplifier Iq for 3×. The same 81-point run leaves `iq_ua` at 5.88–14.98 µA
(unchanged worst corner) and `gain_1k_db` at 54.31–63.57 dB (0.26 dB of the
1.07 dB PSRR-proxy margin spent).

**Why the schematic is unchanged.** An adaptive-`Rz` ladder built on top of
that reaches 10 of 15 tt load × cap points against the committed 5 of 15 with
resurgence clean, but the return-node move alone costs the 0.1 mA column its
margin at the binding corner — `ss`/−40 °C/3.63 V, 0.1 mA/0.33 µF/1 mΩ:
48.64°/13.64 dB committed, 44.73°/10.79 dB with `Cc` → `BG`, below DR-0001's
45°. §6.10 closed that column and #51 is not entitled to spend it. The next
increment is therefore, in order: `Cc` → `BG`, then **re-measure `Cf`'s floor**
(DR-0012 §2's ≈ 45 fF was set by the race this change removes; the residual is
1.5–2× of `Cc/Cf`, one step of `Cf`), then the adaptive-`Rz` ladder.

## 7. Handoffs

| Issue | What to take |
|---|---|
| **#10 stability — CLOSED by #51** | §6 is now the measurement, not the projection: the compensation is in this cell, `sim/loop-stability/records/` carries the 3240-point result, and the load range it does not reach is DR-0007's |
| **#11 current limit / enable — RESOLVED** | This row asked #11 to make an interface decision: the 5-port contract had no enable pin, so the cell drew ≈ 9 µA whenever VDD was present (9.24 µA measured disabled, `sim/op-point-sanity/records/20260801-002928-712cb87.md`) against a ratified "shutdown Iq < 3 µA" row. **#11 appended `EN` as a sixth pin and gated the bias inside this cell** (`Mbias_h`/`Mnb_pd`/`Mn1_pu`/`Mnd_pu`, and a local EN→ENB inverter). A supply header was rejected: with VDD switched off while `Men` holds OUT at VIN, `M2P`'s drain-body diode forward-biases and re-powers the cell. Disabled current is now 0.20 µA at ff/125 °C/3.63 V (`sim/enable-shutdown/records/`); the enabled-state numbers in §5/§6 below move by < 0.2 % (re-measured, `sim/amp-openloop/records/`) |
| **#12 testbench suite** | PSRR at 100 kHz is a closed-loop claim (§4); load/line regulation ride on the 110 dB DC gain; the falling-slew number above bounds the transient |
| **#13 Monte Carlo mismatch** | §3's split: verify 3σ ≤ 2.33 mV input-referred for the amplifier. Do **not** cite a PDK Monte Carlo for the divider term — §3.2 |
| **#15 floorplan / matching** | 360 µm² of common-centroid input-pair area and 64 µm² mirror devices are budgeted requirements, not suggestions; the divider needs ≥ 95/191 µm² unit-resistor legs for §3.2's number |

## 8. Area

Rough active area, for the < 0.1 mm² core row (excludes routing and the pass
device):

| Item | Area |
|---|---|
| `Rbias` (1 µm × 1000 µm, `ppolyf_u_1k`) | 1000 µm² |
| `Cc` (49 µm × 49 µm MIM, 4.80 pF) | 2401 µm² |
| `Rz` (1 µm × 6000 µm, `ppolyf_u_1k`, 6 MΩ) | ≈ 6000 µm² |
| `Rbufb` (1 µm × 5000 µm, `ppolyf_u_1k`, 5 MΩ) | ≈ 5000 µm² |
| Transistor gate area (all 13 devices) | ≈ 1990 µm² |
| **Total** | **≈ 16 400 µm² ≈ 0.0164 mm²** — 16 % of the core budget |

**#53 §6.10 shrinks this row, it does not grow it.** `Cf1`/`Cf2` go
2 × 144 µm² → 2 × 49 µm², and `M2P` (300 → 60 µm²), `Mbufb` (400 → 100 µm²)
and `Mbuf` (150 → 30 µm²) give up ≈ 660 µm² of gate area between them, against
≈ 2.4 µm² added by `MTAIL`. Nothing in the cell grew. `Cc`, `Rz`, `Rbias` and
`Rbufb` — the four items that dominate the total — are untouched.

#51 moved `Rz` from `ppolyf_u` to `ppolyf_u_1k`. At 6 MΩ the `ppolyf_u`
flavour (369 Ω/sq, 2.69 µm² per square) would be ≈ 43 700 µm² — 44 % of the
whole core-area row for one resistor — against ≈ 6000 µm² for `ppolyf_u_1k`.
The cost of the swap is `ppolyf_u`'s much better temperature coefficient
(−27.9 ppm/°C, 1.24 % total spread, `sim/devchar/CONCLUSIONS.md` §2), but
temperature **is** swept in `sim/loop-stability/`'s matrix, so whatever
tempco `ppolyf_u_1k` has is measured rather than assumed. Process spread on
poly sheet resistance is **not** covered — see the note in §6 and in DR-0007's
Consequences: the loop-stability corner axis holds the `res_*` sections
typical, and `Rz` is now a first-order compensation parameter.
