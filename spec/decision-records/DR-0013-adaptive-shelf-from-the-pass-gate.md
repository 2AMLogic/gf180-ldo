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
| `Mrza` | `pfet_03v3`, 8 µm/6 µm, S = `N1`, D = `NRZA`, B = `N1`, **G = `BG`** | a triode replica in parallel with `Rz` |
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
is broad; 600 kΩ is taken.

## Result

<!-- RESULT-PLACEHOLDER -->

## What is still not reached, in closed form

Two ratified rows now bound the 50 mA corner from opposite sides, and the
bound they leave has no free design variable in it. Both halves are measured
on this design, not asserted.

**The ESR ceiling on `A_plat`.** Above `1/(2π·ESR·C_eff)` the output impedance
is flat at `ESR`, so `|T|` plateaus at `beta·A_plat·gm_pass·ESR` until the
shelf ends. If that plateau is above 0 dB the crossover is pushed past `f_2`
onto the far side of the phase cliff, and — because `|T|` has by then dipped
under 0 dB and come back — DR-0008's resurgence check fires. Measured: this
is the mechanism behind every resurging point in the `Rza` sweep above and in
the fixed-`Rz` sweep at `Rz ≤ 500 kΩ`. So

```
A_plat  <  1/(beta * gm_pass * ESR)
```

**The PSRR floor under `f_c/f_z`.** The 4.7 µF rows need `f_c` above `f_z`
by ≈ 1.6× (measured: the 0.1 mA/4.7 µF points pass at ratio 1.6 with
PM 56–65°, and fail at ratio ≈ 1.0 with PM ≈ 19–32°), and

```
f_c/f_z  =  beta * A_plat^2 * Cc * gm_pass / (gm(MIN) * C_eff)
```

while the ratified PSRR row pins `gm(MIN)/Cc >= 2*pi*1 kHz*316 = K`. Both
`A_plat` and `Cc` cancel when the two are combined:

```
f_c/f_z  <=  1 / (beta * gm_pass * ESR^2 * K * C_eff)
```

At 50 mA (`gm_pass` = 0.193 S, measured), 4.7 µF and ESR = 0.5 Ω that ceiling
is **3.3**, against the **1.6** the same corner needs. A factor of two, at
`tt`/27 °C, before any process or temperature spread — and `Rz` is a
`ppolyf_u_1k` resistor with ≈ 40 % process spread (issue #54's own reason for
adding the `res_ff`/`res_ss` corners). That is why the columns close at `tt`
and do not close over the full matrix.

Nothing in that bound is a property of *this* compensation. It is a property
of the ratified rows: it holds for any Type-II shelf around this pass device,
adaptive or not. The three ways out, in the order this record would take them:

1. **Re-cut the PSRR budget against the closed-loop measurement.**
   `design/error_amp.md` §4 assigns the whole 50 dB row to amplifier gain,
   forcing `|1 − G|` to 1 — deliberately conservative, and DR-0009 already
   flagged re-cutting it as "worth doing on its own merits". `K` falls
   directly, and `f_c/f_z`'s ceiling rises with it. This is the cheapest
   lever and the only one that costs no silicon.
2. **Buy `f_2` headroom with buffer bandwidth**, i.e. DR-0009's literal
   Candidate 2, funded by whatever the Iq row has left at full load. With the
   ≈ 5 µA available, that is a ≈ 2× ceiling on `f_2` — worth having, not
   worth another architecture.
3. **Narrow DR-0001's `ESR × C_eff × I_load` box.** DR-0001 anticipates this
   ("the correct response is a superseding record that tightens the component
   spec"), and the bound above says exactly which combination is
   unreachable — the 0.5 Ω ESR rows at the top of the load and cap ranges,
   not the load axis as a whole. This is a product decision, not a Builder's.

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

<!-- CONSEQUENCES-PLACEHOLDER -->
