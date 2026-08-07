# DR-0013: The gain shelf can be made to track the load — a triode replica across `Rz`, gated by the pass device's own drive

- **Status**: proposed — ratification is the operator's, the same process
  DR-0001, DR-0007 and DR-0008 went through. **Nothing in this record is in
  force until an operator ratifies it.** What is *not* conditional on
  ratification is the evidence, which is recorded in
  `sim/loop-stability/records/`, `sim/amp-openloop/records/`,
  `sim/amp-selfosc/records/`, `sim/psrr-dc/records/`,
  `sim/quiescent-current/records/` and `sim/enable-shutdown/records/` and
  stands on its own.
- **Date**: 2026-08-06
- **Decided by**: Builder agent, issue #51 (recommendation only)
- **Builds on**: DR-0012 (the shelf's width is `Cc/Cf`), DR-0009 (the
  frontier equations and the naming of Candidate 2), DR-0008 (the RHP-pole
  precondition, ratified 2026-08-06). It does not supersede any of them.

## Context

DR-0012 closed the 0.1 mA column (756/756) and stated, in its Decision §4,
exactly what the 1–50 mA columns still need: `Cc/Cf ≳ 900` against the 98 it
landed, and — since both ends of that ratio are now measured rather than
assumed — an architecture change rather than another resize. It named
DR-0009's **Candidate 2, "adaptive biasing of the buffer from a pass-device
sense replica"**, as the only remaining lever, and narrowed its brief to the
1–50 mA columns because it is a load-proportional mechanism.

This record takes that lever, and finds that DR-0012's own correction changes
*where it has to be applied*. DR-0009 proposed adaptive **bias** because it
believed `f_2` was a bias-current quantity. DR-0012 proved it is not:

```
f_2 = 1/(2*pi*Rz*Cf)          f_z = 1/(2*pi*Rz*Cc)      A_plat = gm(MIN)*Rz
```

Bias current sets only the *ceiling* on `f_2`. So a buffer whose bias tracks
the load raises the ceiling and moves nothing else — while `Rz`, which is not
a bias quantity at all, moves **all three** of the numbers above, and moves
them in the directions the heavy-load corners want simultaneously. The
load-tracking idea is Candidate 2's; the quantity it should track is `Rz`,
and that is this record's finding.

## The mechanism, and why it is exactly load-invariant

The LDO's crossover in the shelf region is

```
f_c = beta * A_plat * gm_pass / (2*pi*C_eff)
```

and `gm_pass` is the only load-dependent factor. Measured on the committed
design at `tt`/27 °C/3.30 V/0.33 µF/1 mΩ, `f_c` = 161 kHz at 0.1 mA and
1.874 MHz at 50 mA — a **63×** span, of which the loop can afford roughly
2× before the fixed −180° crossing at ≈ 685 kHz overtakes it.

The two `T(f)` curves are worth stating precisely, because they are what makes
the fix a translation rather than a redesign. Above ≈ 30 kHz the 0.1 mA and
50 mA loop-gain curves are **the same curve, offset by 36 dB**: at 42 kHz the
phase is −90.3° and −91.0°, at 178 kHz −115.4° and −114.5°, at 562 kHz
−165.5° and −167.0°. Nothing about the shape fails at heavy load. What fails
is only that `f_c` has walked past a phase cliff that stayed put.

Scale `Rz` by `1/a` and every frequency in that shape scales by `a`
(`f_z`, `f_2`, and the −180° crossing with them), while `f_c` scales by
`1/a` — so `f_c` measured *in units of the shelf* scales by `a²/gm_pass`
… i.e.

```
Rz  proportional to  1/sqrt(gm_pass)    =>    f_c/f_z  and  f_c/f_2  are
                                              BOTH load-invariant,
                                              and so is the phase margin.
```

That is the design target, and it is falsifiable. Measured — the best *fixed*
`Rz` per load column, from a sweep of `Rz` ∈ {6, 3, 2, 1, 0.9, 0.8, 0.7, 0.6,
0.5, 0.4, 0.25} MΩ at `tt`/27 °C/3.30 V:

| `I_load` | best fixed `Rz` | worst PM there | (`Rz` = 6 MΩ, committed) |
|---|---|---|---|
| 0.1 mA | 6 MΩ | 64.8–77 ° | 64.8–77 ° |
| 1 mA | ≈ 1–2 MΩ | 62–77 ° | −4.3 ° |
| 10 mA | ≈ 0.6–0.8 MΩ | 54–70 ° | −65.5 ° |
| 50 mA | ≈ 0.25–0.5 MΩ | 62–67 ° | −90.7 ° |

A 24× range of `Rz` against a 500× range of load current: `Rz ∝ I_load^-1/2`,
which is `1/sqrt(gm_pass)` for a pass device whose `gm ∝ sqrt(I)`. The
prediction and the measurement are the same law.

## What was built

Two devices in `design/error_amp.sch`. No port change, no new bias branch,
**no quiescent current at all**.

| device | value | what it is |
|---|---|---|
| `Mrza` | `pfet_03v3`, 12 µm/9 µm, S = `N1`, D = `NRZA`, B = `N1`, **G = `BG`** | a triode replica in parallel with `Rz` |
| `Rza` | `ppolyf_u_1k`, 1 µm × 600 µm (600 kΩ), `NRZA` → `NZ` | the series floor that shapes the law |

Three things make this cheap, and each is a measured property rather than an
assertion:

**1. It is a resistor and only a resistor.** The `Rz`/`Cc` branch carries no
DC current — measured, `V(N1) = V(NZ) = 2.551086 V` to every printed digit —
so `Mrza` sits at `Vds = 0` exactly, where a MOSFET's `gm = dId/dVgs` is
identically zero. Its gate injects no signal current into the compensation
node. There is no feedforward path to isolate and no isolation resistor to
pay for, which is the difference between this and `Mbufb` (whose gate needs
`Rbufb`'s 5 MΩ precisely because that device *does* carry current).

**2. `BG` is the pass-device replica bias, and it is free.** `BG` is the
class-AB buffer's gate, i.e. the pass device's own gate drive one `Vsg(Mbuf)`
up. Measured at `tt`/27 °C/3.30 V, `V(N1) − V(BG)`:

| `I_load` | 0 mA | 0.1 mA | 1 mA | 10 mA | 25 mA | 50 mA |
|---|---|---|---|---|---|---|
| `Vsg(Mrza)` | 0.415 V | 0.607 V | 0.724 V | 0.924 V | 1.086 V | 1.285 V |

against a `|Vtp|` near 0.72 V — off below ≈ 1 mA, progressively deeper in
triode above it. DR-0009's Candidate 2 asks for "a sense replica of the pass
device"; a device whose gate is the pass gate *is* that replica, and taking
the sense from a node the cell already drives costs no bias branch, no sense
resistor and no microamps. That matters more than it looks: the ratified Iq
row is `< 30 µA` **at full load as well as at no load**
(`sim/quiescent-current/testbench/tb_quiescent.spice`), and the committed
design already measures 24.81 µA at its binding corner — ≈ 5 µA of headroom,
which is less than the buffer boost DR-0009's literal formulation would need.

**3. `Mrza`'s own gate capacitance is an adaptive `Cf`, and it is
load-bearing.** `Cgg(Mrza)` is a capacitance from `BG` to `N1` — the same two
nodes `Cf1`/`Cf2` connect — and it only exists when the channel does, i.e. at
heavy load. That is exactly when the local loop needs it: the local-loop
margin goes as `Rz·Cf²` (DR-0012 §2), so a falling `Rz` has to be paid for
with a rising `Cf` or DR-0008's precondition breaks. Measured, on the 48-point
`tt`/27 °C/3.30 V screen (loads 0.1/1/10/50 mA × caps 0.33/1/4.7 µF × all four
ESRs), changing **nothing but** inserting a 2 MΩ isolation resistor in
`Mrza`'s gate — which removes that coupling and nothing else:

| `Mrza` gate | DR-0001 PASS | DR-0008 resurging |
|---|---|---|
| tied to `BG` (committed) | 37–38 / 48 | **0** |
| through 2 MΩ to `BG` | 23–29 / 48 | **6–19** |

The adaptive resistor and the adaptive `Cf` are the same device. That is not
a coincidence: both are the channel.

**Why `Rza` is there.** A square-law device's `1/(Vgs−Vt)` is far sharper than
the gentle 12× law the loop wants across a 500× load range. `Rza` is the floor
that flattens the heavy end: the branch is `Rza + Ron(Mrza)`, so `Rz_eff`
saturates at `Rz‖Rza` instead of running away. Measured on the same 48-point
screen, `Mrza` = 8 µm/6 µm:

| `Rza` | 0 (no floor) | 200 kΩ | 300 kΩ | 400 kΩ | 500 kΩ | 600 kΩ | 800 kΩ | 1.0 MΩ | 1.4 MΩ |
|---|---|---|---|---|---|---|---|---|---|
| PASS / 48 | — | 36 | 37 | 37 | 38 | **38** | 37 | 36 | 35 |
| resurging | — | 0 | 0 | 0 | 0 | **0** | 0 | 0 | 0 |

against **19 / 48** for the committed design on the same screen. The optimum
is broad.

**`Mrza`'s gate area is what spends the PSRR budget; `Rza` is not.** More
gate area means more adaptive `Cf`, which the local loop wants — but the same
capacitance is a Miller load on `N1`, so it costs amplifier gain at 1 kHz,
which is the line `design/error_amp.md` §4 budgets the ratified PSRR row
against (`gain_1k_db` ≥ 53.5 dB). Measured on the *full* 81-point
`sim/amp-openloop/` grid:

| `Mrza` | `Rza` | `peak_excess_db` worst (bar ≤ 1) | `gain_1k_db` worst (line ≥ 53.5) |
|---|---|---|---|
| 8 µm/6 µm | 600 kΩ | **+2.11**, 14 of 81 over | — |
| 16 µm/12 µm | 600 kΩ | −0.04 | **53.36**, FAIL |
| **12 µm/9 µm** | **600 kΩ** | **+0.41** | **53.7736** |

12 µm/9 µm is the one geometry that clears both bars: too little area and the
amplifier's own local loop rings, too much and its 1 kHz gain falls under the
PSRR budget line. On the 1296-point loop screen the larger geometries also
fall off on their own account (20 µm/15 µm → 26/48 and 24 µm/18 µm → 18/48 on
the earlier 48-point `tt` screen, as `f_2` is dragged back down).

**`Rza` is the two-sided one, and the bar that binds it is DR-0008's, not the
PSRR row's.** `Rza` sets `Rz_eff`'s heavy-load floor, `Rz‖Rza`. Lower moves
the heavy-load 0.33 µF rows into the pass band and the 4.7 µF rows out of it,
and — before either of those becomes the limit — it un-damps the amplifier's
own local loop. Measured on the 1296-point `tt`+`res_ss` × 3 temperatures ×
3 supplies loop screen and on the 81-point `sim/amp-openloop/` grid, at
`Mrza` = 12 µm/9 µm:

| `Rza` | loop screen | `peak_excess_db` (bar ≤ 1) | `gain_1k_db` (line ≥ 53.5) |
|---|---|---|---|
| 450 kΩ | 837/1296 | **+1.034 FAIL** | 53.7727 |
| **600 kΩ** | **828/1296** | **+0.408** | **53.7736** |
| 800 kΩ | 767/1296 | +0.031 | 53.7751 |
| 1.0 MΩ | 720/1296 | −0.019 | 53.7767 |
| 1.6 MΩ | 644/1296 | — | — |

450 kΩ is the best value on PM/GM alone and is **rejected on DR-0008's
precondition**, not on the margin — which is the whole reason DR-0008 is
ratified. 600 kΩ is taken. Note the last column: `gain_1k_db` moves by
0.003 dB across a 2.2× range of `Rza`, so `Rza` does not touch the PSRR
budget at all. (An earlier revision of this record set `Rza` = 1.0 MΩ on the
belief that it did; that was wrong, and correcting it is worth ≈ 108 of the
1296 screen points.)

**The base `Rz` stays at 6 MΩ, and that is measured, not inherited.** With
`Mrza` clamping the heavy end, `Rz` is nearly free at the amplifier level
(`gain_1k_db` 53.770–53.777 dB, `peak_excess_db` +0.39…+0.46, all PASS across
6/12/18/24 MΩ) and raising it does open the 0 mA column — 0 mA/0.33 µF goes
0/72 → 72/72 at 18 MΩ, 0 mA/1 µF → 68/72 at 24 MΩ. It buys nothing net,
because it slides the pass band rather than widening it: 0.1 mA/0.33 µF goes
71/72 → 20/72 → 0/72 over the same range and the screen total falls
828 → 814 (12 MΩ) → 791 (18 MΩ) → 779 (24 MΩ). The closed form of why is the
"What is still not reached" section below, and this is its most direct
measurement.

## Result

`sim/loop-stability/records/20260807-103351-64249c6.md` — the full ratified
4536-point matrix, `dec 400`, superseding `20260802-204343-e912fbd`:

| | before (`20260802-204343-e912fbd`) | **after (`20260807-103351-64249c6`)** |
|---|---|---|
| DR-0001 points passing | 1332 / 4536 (29.4 %) | **2930 / 4536 (64.6 %)** |
| worst phase margin | −98.86° | **−6.81°** |
| worst gain margin | −21.15 dB | **−1.47 dB** |
| DR-0008 resurgence points | 0 / 4536 | **0 / 4536** |
| worst point | `res_ss_27c_2.97v` 50 mA / 0.33 µF / 1 mΩ | `res_ss_-40c_2.97v` 50 mA / 0.33 µF / 1 mΩ |

Per load column, points passing and worst phase margin:

| `I_load` | 0 mA | 0.1 mA | 1 mA | 10 mA | 25 mA | 50 mA |
|---|---|---|---|---|---|---|
| before | 13/756, +3.71° | **756/756**, +45.98° | 407/756, −19.07° | 87/756, −75.06° | 57/756, −89.97° | 12/756, −98.86° |
| after | 0/756, +3.55° | 675/756, +35.70° | 714/756, +37.98° | 567/756, +14.68° | 513/756, +2.21° | 461/756, −6.81° |

The 1–50 mA columns this record was written for go from **1319/3780 to
2930/3780**, and the worst phase margin anywhere in the matrix moves 92°. Two
columns move the other way and both are accounted for below: 0 mA loses its
13 passing points (they were all in its 0.33 µF cell at −40 °C on the
high-`Rz` `ss`/`res_ss` corners, i.e. the four points that were nearest the
band's lower edge to begin with), and 0.1 mA loses the 756/756 DR-0012 had
won, almost entirely inside its 4.7 µF cell (173/252 there, against 250/252 at
0.33 µF and 252/252 at 1 µF).

**It is free on every other ratified row, re-measured in full rather than
argued:**

| bench | record | result |
|---|---|---|
| `sim/amp-openloop/` | `20260807-105147-64249c6` | **PASS 81/81**; `gain_1k_db` ≥ 53.7736 dB (line 53.5), `peak_excess_db` ≤ +0.408 (bar 1.0) |
| `sim/psrr-dc/` | `20260807-105159-64249c6` | **PASS 81/81**; `psrr_ldo_1k_db` ≥ 50.2518 dB (ratified 50 dB) |
| `sim/quiescent-current/` | `20260807-105203-64249c6` | **PASS 45/45**; `iq_full_ua` ≤ 22.60 µA (ratified < 30 µA) |
| `sim/amp-selfosc/` | `20260807-105211-64249c6` | **PASS 45/45**; `BG` peak-to-peak ≤ 0.19 µV light load, ≤ 0.11 µV heavy — DR-0008's load-bearing time-domain check |
| `sim/enable-shutdown/` | `20260807-105239-64249c6` | **PASS 63/63**; every DC row identical to the superseded record to all printed digits |

The Iq rows are identical to the digit at all 63 enable-shutdown corners,
which is the prediction this record's §1 makes: a device at `Vds` = 0 in every
DC solution draws nothing.

**The time domain agrees, and by a wider margin than the frequency domain.**
`sim/enable-shutdown/` is the only bench in `sim/` that drives the loop
large-signal, at 50 mA, through enable. It has no ratified bar on output
ringing, so these columns were reported and never compared — they are not a
missed regression, they are an un-compared measurement, and they move like
this:

| quantity, worst of 63 corners | superseded `b90b2ba` | **this design** |
|---|---|---|
| `vout_pp_late` (settled output pk-pk, long after startup) | **197.6 mV** | **4.07 nV** |
| `isup_peak_ma` (supply peak on a 50 mA load) | **279.6 mA** | **50.92 mA** |
| `vout_max_en` (startup overshoot) | 1.9278 V (+7.1 %) | 1.8120 V (+0.67 %) |
| `clg_min_reg` (limit-clamp gate while settled; `VIN` = off) | `VIN` − 1.02 V | `VIN` − 0.0001 V |

The superseded netlist was oscillating by 53–198 mV at every one of the 63
corners in a window sampled long after startup, drawing up to 5.6× the load
current from the supply, and dragging `ldo_ilimit`'s clamp a volt below `VIN`
in response. On this netlist the settled output is numerically still and the
clamp is off. That is an independent, large-signal corroboration of the
frequency-domain result at the one operating point it covers (50 mA / 1 µF /
100 mΩ), and it is not evidence about the parts of DR-0001's box the
loop-stability record still reports as failing.

**One PVT corner needed a DC convergence seed, and the harness now says so.**
`sf`/−40 °C/3.63 V/0.1 mA has a second DC solution — `ldo_softstart` and
`ldo_ilimit` both clamp `PASS_GATE` to `VIN` while the feedback node is below
the reference, and "FB low, so clamp on, so FB stays low" is self-consistent
at VOUT ≈ +0.52 V, above the −0.7 V floor the deck's existing `Dclamp` denies.
Every AC analysis in the deck cold-starts its own operating-point solve, so
each one is an independent chance to land there, and at that corner it did, on
11 of 72 points. It is **not** caused by this record's devices — they carry no
DC current in any solution, so they cannot change the DC solution *set*, only
which one Newton walks to — and the harness caught it and voided the run
rather than recording margins about it, exactly as `sweep.py`'s `nonregulating`
check is written to. `sweep.py` now retries such a corner once with `.nodeset`
cards that start Newton with those clamps released, holds the retry to the
same VOUT check, and names the corner in the record; all 62 other corners ran
unseeded and are therefore directly comparable with every earlier record.

## What is still not reached, and the closed form of it

1606 points still fail, and they are not scattered. They are three faces of
one number.

**The verdict is decided by the crossover frequency, and the pass band in it
is 38.6 : 1.** At `tt`/27 °C/3.30 V/1 mΩ — one PVT point, one ESR, so nothing
else is varying — all eighteen (load × cap) cells sort by `f_c` alone:

| `f_c` | 693 Hz | 1.53 kHz | 2.77 kHz | 8.02 kHz | … | 309 kHz | 504 kHz | 619 kHz | 712 kHz |
|---|---|---|---|---|---|---|---|---|---|
| PM | 7.7° | 16.2° | 27.7° | 47.3° | 45–73° | 45.1° | 28.7° | 15.0° | 5.1° |
| | FAIL | FAIL | FAIL | PASS | PASS | PASS | FAIL | FAIL | FAIL |

Every one of the twelve points with **8.0 kHz ≤ `f_c` ≤ 309 kHz** passes and
every one of the six outside it fails. The matrix asks `f_c` to cover
693 Hz … 712 kHz, a span of **1029 : 1**, against a pass band of **38.6 : 1**.

**Both edges of that band are design quantities, and their ratio is one
formula.** The lower edge is the compensation zero: `PM ≈ atan(f_c/f_z)` while
the two poles are below crossover (measured: 0.125 → 7.7°, 0.276 → 16.2°,
0.50 → 27.7°, against `atan` of 7.1°, 15.4°, 26.6°), so 45° needs
`f_c ≳ 1.45·f_z` — and `1.45/(2π·6 MΩ·4.8 pF)` = **8.0 kHz**, against the
8.02 kHz measured. The upper edge is `f_hi`, the frequency by which the output
stage's own poles have eaten the rest of the phase; measured, **309 kHz**. So

```
pass band  W  =  f_hi / (1.45 · f_z)  =  2π · f_hi · Rz_eff · Cc / 1.45
```

which evaluates to 38.6 on the numbers above — i.e. the formula is the
measurement, not a model of it.

**The obstruction, at 50 mA.** Adaptation removes the *load* axis from the
span, because `Rz_eff` tracks it. It cannot remove the *cap* axis: at one
load, `Rz_eff` is one number and the 14.2 : 1 cap window must fit inside `W`.

```
fit the cap window:   Rz_eff  ≥  14.2 · 1.45 / (2π · f_hi · Cc)  =  2.21 MΩ
stay under the cliff: Rz_eff  ≤  545 kΩ · (309 kHz / 712 kHz)    =  236 kΩ
```

(the second from the measured `f_c` = 712 kHz at 50 mA / 0.33 µF, where
`Rz_eff` = `Rz‖Rza` = 545 kΩ). **The two are 9.4× apart, and there is no
`Rz_eff` between them.** No Type-II shelf — fixed, adaptive, or otherwise —
covers DR-0001's cap window at 50 mA on this output stage.

**What it costs to close, in one variable.** The two bounds move as `1/f_hi`
and `f_hi`, so the gap closes as `f_hi²`:

```
f_hi  ≥  309 kHz · sqrt(9.4)  =  0.95 MHz          against 0.31 MHz measured
```

Scaling `Cc` does not help: the lower bound falls as `1/Cc`, but the ratified
PSRR row pins `gm(MIN) ≥ K·Cc`, and the upper bound falls as `1/gm(MIN)` — the
two cancel exactly. The only slack there is the 1.55× by which the design's
own `gm(MIN)/Cc` (3.07e6) exceeds the ratified floor `K` (1.99e6), worth
`sqrt(1.55)` = 1.24× and taking the requirement to **0.76 MHz** if the PSRR
row is spent to its last dB. **`f_hi` has to roughly triple.** That is the
whole remaining gap, in one measurable number.

**The other two clusters are the same number.** The 1606 failures split
exactly as the band does:

| cluster | points | which edge |
|---|---|---|
| 0 mA, all caps | 756 | below: `f_c` = 693 Hz … 2.77 kHz vs 8.0 kHz |
| 1–50 mA at 0.33 µF | 681 | above: `f_c` = 504 … 712 kHz vs 309 kHz |
| remainder (79 at 0.1 mA/4.7 µF, 43 at 50 mA/1 µF/low-ESR, 47 others) | 169 | the same two edges, over PVT |

The 0 mA column is below the band because the pass-device replica cannot act
there: `V(N1) − V(BG)` is 0.415 V at 0 mA and 0.607 V at 0.1 mA, both under
`|Vtp|` ≈ 0.72 V, so `Rz_eff` is the same 6 MΩ at both and the 0 → 0.1 mA load
step (136 : 1 in `f_c`, from 693 Hz to 94.5 kHz) has to fit in the same
38.6 : 1 band. Raising `Rz` to fit it needs 6 MΩ × 136/38.6 = **21 MΩ** — and
then `f_c` at 0.1 mA/0.33 µF is 94.5 kHz × 21/6 = **332 kHz**, back over the
309 kHz cliff. Measured, and this is the point of the `Rz` = 18/24 MΩ screens
in "What was built": the 0 mA column opens and the 0.1 mA/0.33 µF cell closes,
for no net gain. Same wall, same number.

## The three ways out, in the order this record would take them

1. **Buy `f_hi`** — DR-0009's *literal* Candidate 2, the buffer-bandwidth
   boost, which this record's `Rz` lever deliberately did not attempt. The
   ratified Iq row leaves 30 − 24.81 = **5.19 µA** at full load, against a
   buffer that runs at ≈ 2 µA, so a 3× is not obviously out of reach — but it
   is a different change to a different part of the amplifier, with its own
   PSRR and `amp-selfosc` exposure, and it should be its own issue and its own
   record rather than an amendment here.
2. **Re-cut the PSRR budget against the closed-loop measurement.**
   `design/error_amp.md` §4 assigns the whole 50 dB row to amplifier gain,
   forcing `|1 − G|` to 1, while the measured `psrr_ldo_1k_tracking_db` is
   59–71 dB. Recovering the 1.55× of `gm(MIN)/Cc` that already exists, plus
   whatever a re-cut adds, is worth `sqrt` of it against the requirement
   above. Cheapest lever, no silicon.
3. **Narrow DR-0001's box.** DR-0001 anticipates this — "the correct response
   is a superseding record that tightens the component spec" — and the bound
   above says precisely which combination is unreachable rather than asking
   for the load axis as a whole: the **0.33 µF end at ≥ 10 mA**, and the
   **no-load point**. Neither is the ESR axis. This is a product decision, not
   a Builder's, and this record does not take it.

**What this record does not do is relax anything.** DR-0001's bars are
unchanged, the matrix is unchanged, and the record it produced reports FAIL.

## Alternatives considered

- **Adaptive tail current (`gm(MIN)`) instead of adaptive `Rz`.** It reduces
  `A_plat` without moving `f_z` or `f_2`, which looks strictly better. It is
  not: `gm(MIN)` *is* the amplifier's 1 kHz gain, so a load-tracking
  `gm(MIN)` is a load-tracking PSRR, and the ratified PSRR row is specified
  **at 50 mA** (`README.md`, PSRR row). A 30× reduction at heavy load — what
  the 0.33 µF column needs — takes `psrr_ldo_1k_db` from 51 dB to ≈ 21 dB.
  Rejected on the ratified row, not on measurement.
- **Adaptive `Cc` (a switched MIM in the compensation branch).** Holds `f_z`
  fixed while `A_plat` falls, which is the ideal shape. Rejected on two
  grounds: the capacitance needed to hold `f_z` across a 12× `Rz` swing is
  ≈ 53 pF (≈ 26 000 µm² of MIM, a quarter of the whole core-area row), and
  more decisively, at 1 kHz the branch's impedance is `1/(2π·1 kHz·Cc_total)`
  regardless of which branch it sits in — so the added capacitance spends the
  PSRR row exactly as a bigger `Cc` would.
- **Shrinking `Rz` globally instead of adaptively.** Measured over the whole
  range (the table in "The mechanism" above): every value that helps 1–50 mA
  breaks the 0.1 mA column DR-0012 just closed. `Rz` = 1 MΩ takes
  0.1 mA/4.7 µF from PM 64.8° to 14.8°. There is no fixed value; that is the
  point of the record.
- **Isolating `Mrza`'s gate from `BG` with a series resistor**, the way
  `Rbufb` isolates `Mbufb`. Built and measured (the table in §3 above): it is
  strictly worse, because `Mrza`'s gate capacitance is the adaptive `Cf` the
  local loop needs. Recorded because the reflex to isolate any gate hanging
  off a signal node is a good one, and here it is wrong for a reason that is
  specific and checkable (`gm = 0` at `Vds = 0`).
- **Doing nothing and recording a fourth negative result.** DR-0010 and
  DR-0011 are negative results for Candidate 1; DR-0012 expected Candidate 2
  to be expensive. It is not, once the lever moves from bias to `Rz`.

## Consequences

1. **`design/error_amp.sch` gains two devices and no quiescent current.**
   `Mrza` (`pfet_03v3` 12 µm/9 µm, gate on `BG`, body on its own source `N1`)
   and `Rza` (600 kΩ of `ppolyf_u_1k`). ≈ 700 µm² of area between them, taking
   the amplifier to ≈ 17 100 µm², ≈ 17 % of the core budget. No port change,
   no new bias branch, no Iq — measured identical to the digit on all 63
   `sim/enable-shutdown/` corners.
2. **Two of the three numbers in this compensation are now compensation
   values, not layout conveniences,** and `design/error_amp.md` §6.5 says so:
   `Mrza`'s **gate area** is the adaptive `Cf` and sets `gain_1k_db` (the PSRR
   budget line), and `Rza` sets `Rz_eff`'s heavy-load floor and therefore both
   the 0.33 µF/4.7 µF trade and the amplifier's own local-loop damping. A
   layout that lands `Rza` low re-opens DR-0008's precondition; one that lands
   it high gives back the 1–50 mA columns. `Mrza`'s n-well must be tied to
   `N1`, not `VDD`.
3. **DR-0001 is still not met, and this record does not ask for it to be
   changed.** 2930/4536. What it replaces is an open architecture question
   with a single measured number — the output stage's `f_hi`, 0.31 MHz against
   the ≈ 0.76–0.95 MHz the ratified rows demand — and a named next step for
   each of the three ways to move it.
4. **DR-0009's Candidate 2 is answered, and only half-spent.** The
   *load-tracking replica* half is built, is free, and is worth 1598 points of
   the matrix. The *buffer-bandwidth* half — what DR-0009 literally proposed —
   is untried and is now the single highest-value remaining lever, with a
   quantified target (3× on `f_hi`) and a quantified budget (5.19 µA) instead
   of a hope.
5. **`sim/loop-stability/`'s harness learned that its `Dclamp` is necessary
   and not sufficient.** The deck's non-regulating-branch defence now has a
   second half: a `.nodeset` seed applied *only* to a corner that has already
   failed the VOUT check, verified by that same check, and named in the
   record. The default path is unchanged, so every corner that does not need
   it stays byte-comparable with earlier records.
6. **Nothing here is in force until an operator ratifies it.** The evidence
   stands on its own; the recommendation to take `Rz` rather than bias as
   Candidate 2's lever, and to spend the next effort on `f_hi`, does not.
