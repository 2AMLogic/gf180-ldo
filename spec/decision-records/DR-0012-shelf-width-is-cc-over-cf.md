# DR-0012: The gain shelf's width is `Cc/Cf`, not an Iq budget — and that closes the 0.1 mA column

- **Status**: proposed — ratification is the operator's, the same process
  DR-0001, DR-0007, DR-0008 and DR-0009 went through. **Nothing in this
  record is in force until an operator ratifies it.** What is not conditional
  on ratification is the evidence, which is recorded in
  `sim/loop-stability/records/`, `sim/amp-openloop/records/`,
  `sim/amp-selfosc/records/`, `sim/psrr-dc/records/`,
  `sim/quiescent-current/records/`, `sim/dropout-vs-load/records/` and
  `sim/enable-shutdown/records/` and stands on its own.
- **Date**: 2026-08-02
- **Decided by**: Builder agent, issue #53 (recommendation only)
- **Corrects**: DR-0009's "`f_2` is set by Iq, and it does not scale"
  subsection. It does not supersede DR-0009 — the frontier equations, the
  measured envelope and the `A_plat` bound are all still right, and so is the
  conclusion that 1–50 mA is out of reach. What is wrong is the identification
  of *which* quantity sets `f_2`.

## Context

DR-0009 established, with DR-0008's precondition finally satisfied, that the
Type-II gain shelf covers `(I_load, C_eff)` points whose LDO crossover `f_c`
lands between the shelf's lower corner `f_z` and its upper corner `f_2`, and
that the head loop-stability record read 785/3240 with a residual **48-point
phase-margin gap inside the 0.1 mA column** — 44 at 0.33 µF and cold, where
`f_c` (107–190 kHz) runs up into `f_2`, and 4 at 4.7 µF and hot, where `f_c`
(6.9–7.5 kHz) falls back down into `f_z`. Issue #53's first acceptance
criterion is closing exactly those 48 points.

Issue #54 then widened the ratified matrix from 3240 to 4536 points (PR #66:
`res_ff`/`res_ss` added to the process axis, since `Rz` is a `ppolyf_u_1k`
resistor with ~40 % process spread and is a first-order compensation
parameter). On that wider matrix the same design reads **1099/4536**, and the
0.1 mA gap is **70 of 756** — 62 at 0.33 µF and cold and 8 at 4.7 µF and hot,
i.e. the same two clusters with the resistor corners' share of them included
(`sim/loop-stability/records/20260802-151515-2a08fce.md`). This record is
measured against that 4536-point matrix throughout, so its "before" column is
`2a08fce` rather than the 3240-point `c828e73` DR-0009 wrote against.

DR-0009 then wrote off the obvious move — raise `f_2` — on the grounds that
`f_2` is a bias-current quantity:

> `f_2` is the local loop's crossover, so it is capped by that loop's
> non-dominant poles: the buffer's `gm(Mbuf)/(2π·C_gate)` and, after the
> Miller split, `gm(M2P)/(2π·Cgs(Mbuf))`. Both are bias currents against fixed
> capacitance. […] Reaching 50 mA / 0.33 µF needs `f_2` in the low-MHz range,
> i.e. an order of magnitude further on a curve that has just spent 1.9× the
> amplifier's whole Iq to buy 3×.

On that reading the only remaining levers were architectural, and DR-0010 and
DR-0011 spent two sessions on the first of them (a super source follower
around `Mbuf`, with three different bias schemes) and rejected all three.

## What the algebra actually says

Above `f_z` the `Rz`/`Cc` branch presents `Rz` from `OUT` back to `N1`, and
`Cf1`/`Cf2` (call it `Cf`) is a Miller capacitor from `N1` to `BG` across the
stage-2 driver `M2P`. Break the local loop at `N1`, with `A(s) = gm(M2P)·Z_BG`
the forward gain of that stage and the buffer a unity follower:

```
T_local(s) = A(s) · Z_N1(s) / (Z_N1(s) + Rz)

in the band where the Miller term dominates Z_N1:
Z_N1(s) ≈ 1/(s·Cf·A(s))        and   |Z_N1| << Rz

=> T_local(s) ≈ A(s)/(s·Cf·A(s)·Rz) = 1/(s·Rz·Cf)
```

`A(s)` cancels. So the local loop's crossover — which *is* the shelf's upper
corner — is

```
f_2 = 1/(2π·Rz·Cf)          exactly the form of      f_z = 1/(2π·Rz·Cc)
```

and therefore

```
shelf width  =  f_2/f_z  =  Cc/Cf
```

independent of `Rz` and of every bias current in the cell. At the values on
`origin/main` before this record, `Cc` = 4.80 pF and `Cf` = 149 fF give
`Cc/Cf` = 32, `f_z` = 5.4 kHz and `f_2` = 178 kHz — which are the numbers
DR-0009 measured, arrived at from the other direction.

**And 32 is the whole problem.** Across the 0.1 mA column the measured
crossover spans 6.9 kHz (4.7 µF, `ff`/125 °C) to 190 kHz (0.33 µF,
`ff`/−40 °C) — a **27× span inside a 32× shelf**. There is no margin at
either end by construction, and the 48 failures are the two ends of that
span poking out. Nothing about that is a bias-current statement.

## What was built and measured

### 1. `Cf` moves `f_2`, and it moves the failures with it

`sim/loop-stability/`, `--no-write`, `design/error_amp.sch` otherwise exactly
as committed at `931ec19`, at the two points DR-0009 names as the ends of the
column (`ss`/−40 °C/3.63 V, 0.1 mA, 0.33 µF, 1 mΩ; and `ff`/125 °C/2.97 V,
0.1 mA, 4.7 µF, 1 mΩ):

| `Cf` (2 × MIM in series) | `f_2` = 1/(2π·Rz·Cf) | cold PM / GM | hot PM |
|---|---|---|---|
| 149 fF (12 × 12 µm, committed) | 178 kHz | 32.37° / 12.13 dB | 42.48° |
| 100 fF (10 × 10 µm) | 265 kHz | 35.88° / 11.32 dB | 43.13° |
| 81 fF (9 × 9 µm) | 327 kHz | 38.04° / 10.80 dB | 43.42° |
| 64 fF (8 × 8 µm) | 414 kHz | 40.55° / 10.15 dB | 43.68° |
| 49 fF (7 × 7 µm) | 541 kHz | 43.43° / **9.32 dB** | 43.92° |
| 36 fF (6 × 6 µm) | 736 kHz | 46.74° / **8.23 dB** | 44.12° |

Eleven degrees of phase margin at the cold end, for a *smaller* capacitor.
This is the lever DR-0009 ruled out, and it is free.

It is also not sufficient on its own, in two independent ways, and both are
visible in the table:

- **Gain margin trades against phase margin.** Extending the shelf keeps `|T|`
  high for longer, so `|T|` at the −180° crossing rises. `Cf` alone crosses
  DR-0001's 45° phase bar and its 10 dB gain bar in opposite directions and
  never satisfies both.
- **The hot/4.7 µF end barely responds** (42.48° → 44.12° across a 4× change
  in `Cf`, never reaching 45°). Of course it does not: that group fails
  because `f_c` is close to `f_z`, and `Cf` does not touch `f_z`.

### 2. The ceiling on `Cf` is real, and it is capacitance, not current

Shrinking `Cf` raises `f_2` but *lowers* the local loop's own non-dominant
pole, because that pole is the Miller split of the `M2P` stage:

```
p2 ≈ gm(M2P)·Cf / (C_N1·C_BG + Cf·(C_N1 + C_BG))
```

so `f_2 ∝ 1/Cf` and `p2 ∝ Cf` converge from both sides, and past some `Cf`
the local loop rings — which is DR-0008's defect returning. Measured on the
**full 81-point** `sim/amp-openloop/` grid, `peak_excess_db` (bar ≤ 1 dB):

| `Cf` | worst `peak_excess_db` | verdict |
|---|---|---|
| 36 fF | **+2.30 dB** (`ff`/125 °C/2.97 V), > 1 dB at 16 of 81 points | FAIL |
| 43.6 fF | +0.40 dB | PASS |
| 49 fF | **+0.17 dB** | PASS |
| 149 fF (committed) | −0.13 dB | PASS |

But `p2`'s denominator is `C_N1·C_BG`, and both are dominated by gate area:
`C_N1` by `Cgs(M2P)` (150 µm × 2 µm = 300 µm² of gate) and `C_BG` by
`Cgg(Mbuf)` (150 µm × 1 µm). Both devices sit in weak inversion at their
bias currents — `M2P` at 1.6 µA over `W/L` = 75 is ≈ 22 nA per square, `Mbuf`
at 1.8 µA over `W/L` = 150 is ≈ 12 nA per square — so **their widths and
lengths can be cut several-fold with `gm` essentially unchanged**, and the
only thing that moves is the capacitance in `p2`'s denominator. Measured, at
`Cf` = 36 fF and everything else held, `sim/loop-stability/` at
`ss`/−40 °C/3.63 V / 0.1 mA / 0.33 µF / 1 mΩ:

| `M2P` / `Mbufb` / `Mbuf` | cold PM / GM |
|---|---|
| 150 µm/2 µm, 200 µm/2 µm, 150 µm/1 µm (committed) | 37.09° / 8.26 dB |
| 60 µm/1 µm, 80 µm/1 µm, 60 µm/0.5 µm | **43.50° / 9.84 dB** |

+6.4° of phase margin **and** +1.6 dB of gain margin, for zero microamps and
less area. Cutting further (`M2P` 40 µm, `Mbuf` 40 µm) bought nothing more —
at that point `C_N1`/`C_BG` are no longer gate-dominated — so the useful range
of this lever is one step wide, and this record took the step.

### 3. The hot/4.7 µF end needs `A_plat`, and it pays for itself in PSRR

The remaining four failures sit where `f_c/f_z` ≈ 1.3, and the only quantity
that moves them is `A_plat = gm(MIN)·Rz`, which scales `f_c` at every point.
`Rz` is pinned (raising it lowers `f_2` by the same factor, and DR-0009's
measured ceiling stands), so the lever is `gm(MIN)`, i.e. the input pair's
tail current. It is a genuinely two-sided knob — every microamp of tail helps
the 4.7 µF/hot end and hurts the 0.33 µF/cold end — so it was swept rather
than assumed, at the reduced gate areas above and `Cf` = 36 fF:

| `MTAIL` W (was 6 µm) | cold PM / GM | hot PM |
|---|---|---|
| 7.0 µm | 50.76° / 11.60 dB | 47.29° |
| 7.5 µm | 48.79° / 11.11 dB | 48.51° |
| 8.0 µm | 46.93° / 10.66 dB | 49.67° |
| 9.0 µm | 43.50° / 9.84 dB | 51.80° |

The balance point is shallow and sits low; combined with `Cf` = 49 fF (which
the local-loop ceiling above requires) and the 0.16 µA that `Mbufb`'s wider
replica ratio spends on the buffer, **`MTAIL` = 6.6 µm** — a 10 % tail
increase — is what keeps `iq_ua` inside its 15 µA block allocation while
clearing both ends.

The tail increase is the only current in the cell that moves, and it lands on
the right side of the row it touches. `A_amp(1 kHz) = gm(MIN)/(2π·Cc·1 kHz)`
**is** §4's PSRR budget line, so raising `gm(MIN)` raises it:

| row | bar | before (`c828e73`) | after |
|---|---|---|---|
| `gain_1k_db` (amp, `sim/amp-openloop/`) | ≥ 53.5 dB | 53.50 dB (0.04 dB margin) | **54.57 dB** |
| `psrr_ldo_1k_db` (`sim/psrr-dc/`) | ≥ 50 dB (ratified) | 50.08 dB | **51.04 dB** |

DR-0010 rejected its own candidate partly for pushing `gain_1k_db` to
53.13 dB against that floor. This record moves it the other way.

### 4. One device that looked free and is not: `Mpgn`

`Mpgn` (the small always-on sink at `OUT`) was trimmed 2 µm → 1.2 µm to
recover ≈ 0.16 µA, and it passed every AC bench — `sim/amp-openloop/` 81/81,
and the 0.1 mA column clean on a `--no-write` screen. It then **voided a
full-matrix run**: at `sf`/−40 °C/3.63 V, 9 of 72 points settled on the
non-regulating DC branch (`VOUT` = −0.70 V, i.e. against the testbench's own
diode clamp) instead of the regulating one, all at 1 mA and ESR ≥ 50 mΩ.
Restoring `Mpgn` to 2 µm removes it, reproducibly. `design/error_amp.sch`'s
own note on that device — "it is also what makes the node non-floating for
the operating-point solve" — is load-bearing: with the clamp inside
`ldo_ilimit` able to hold `PASS_GATE` at `VIN`, `Mpgn` is the only thing
arbitrating for the regulating branch, and 0.16 µA of it matters.
`Mpgn` is therefore **unchanged** in the committed design.

## Decision

**1. Land the change.** Five device edits in `design/error_amp.sch`, no new
devices and no port change:

| device | before | after | why |
|---|---|---|---|
| `Cf1`/`Cf2` | 12 × 12 µm MIM (149 fF) | **7 × 7 µm (49 fF)** | `f_2` 178 → 541 kHz; shelf 32× → 98× |
| `M2P` | 150 µm/2 µm | **60 µm/1 µm** | ⅕ the gate area on `N1`, so `p2` survives the smaller `Cf` |
| `Mbuf` | 150 µm/1 µm | **60 µm/0.5 µm** | ⅕ the gate area on `BG`, same reason |
| `Mbufb` | 200 µm/2 µm | **100 µm/1 µm** | tracks `M2P`'s `W/L` at 1.67× (was 1.33×): buffer bias +25% |
| `MTAIL` | 6 µm/4 µm | **6.6 µm/4 µm** | +10 % tail: `A_plat` for the 4.7 µF/hot end, and PSRR margin |

**2. Issue #53's first acceptance criterion is met.**
`sim/loop-stability/records/20260802-171044-db620a6.md` (supersedes
`20260802-151515-2a08fce`), full **4536-point** matrix with the `res_ff`/
`res_ss` corners, unmodified thresholds, clean working tree:

| `I_load` | 0.33 µF | 1 µF | 4.7 µF | row | was |
|---|---|---|---|---|---|
| 0 mA | 13/252 | 0/252 | 0/252 | 13/756 | 0/756 |
| **0.1 mA** | **252/252** | **252/252** | **252/252** | **756/756** | 686/756 |
| 1 mA | 0/252 | 158/252 | 249/252 | 407/756 | 331/756 |
| 10 mA | 0/252 | 0/252 | 87/252 | 87/756 | 74/756 |
| 25 mA | 0/252 | 0/252 | 57/252 | 57/756 | 8/756 |
| 50 mA | 0/252 | 0/252 | 12/252 | 12/756 | 0/756 |
| **total** | | | | **1332/4536** | 1099/4536 |

Worst point in the 0.1 mA column is PM **45.98°** (`ff`/125 °C/2.97 V,
4.7 µF, 1 mΩ) and GM **13.27 dB** (`res_ss`/−40 °C/2.97 V, 0.33 µF, 1 mΩ),
against DR-0001's 45° / 10 dB — 0.98° and 3.27 dB of margin at the two ends
the shelf now has to reach. DR-0008's precondition holds at **0 of 4536**
resurging points, worst −0.07 dB.

**The point-level trade, reported as-is.** Against `2a08fce`, 310 points turn
FAIL → PASS and **77 turn PASS → FAIL** (net +233). None of the 77 is in the
0.1 mA column: 53 are at 10 mA/4.7 µF/200 mΩ, 18 at 1 mA/1 µF/500 mΩ, 3 at
1 mA/4.7 µF/500 mΩ and 3 at 25 mA/4.7 µF/200 mΩ, and **63 of the 77 still
clear the 45° phase bar and fail only on gain margin**. This is §1's
gain-margin/phase-margin trade showing up on the full matrix rather than at a
probe point: a wider shelf holds `|T|` up over a wider band, so `|T|` at the
−180° crossing rises. Every column still improves on net, and the columns the
77 land in were already failing overwhelmingly (10 mA was 74/756, 25 mA was
8/756). It is recorded rather than tuned away because tuning it away costs the
0.1 mA column, which is the criterion this record exists to meet.

**3. Amend `DR-0007`'s proposed `Stability` row to claim one load point,
0.1 mA — not the `0.1–50 mA` widening issue #53 was opened expecting.**
DR-0007 proposed `1–50 mA` on pre-DR-0008
data; DR-0009 showed that data was taken through a resonance and argued the
correct amendment is a narrowing. This record does not restore the old
envelope — it verifies **one** load decade of it, properly. The measured,
DR-0008-precondition-satisfying envelope is:

```markdown
| Stability | verified at I_load = 0.1 mA with C_eff 0.33–4.7 µF, ESR 0–500 mΩ, over the full 63-point PVT grid including the res_ff/res_ss resistor corners: PM ≥ 45°, GM ≥ 10 dB worst corner (756/756 matrix points, worst 45.98° / 13.27 dB). 1–50 mA is NOT verified: 563 of its 3024 points pass and the shortfall is structural (see DR-0012), not a tuning residue. 0 mA (no external load) remains outside the envelope per DR-0007. | capless variant (separate design fork) |
```

That is a **narrower** claim than either DR-0007's proposal or DR-0009's, and
it is deliberately the only one the evidence supports. Ratifying it means
accepting that the part, as it stands today, is a light-load regulator — which
is a product decision an operator has to take, not a Builder. **The
alternative to ratifying it is to keep DR-0001's row open and treat 1–50 mA as
unfinished design work**, which is this record's own recommendation (point 4).

**4. The next increment is the 1–50 mA columns, and the shelf-width equation
now says exactly what they cost.** 50 mA / 0.33 µF needs `f_c` ≈ 1.2–1.7 MHz
inside the shelf, i.e. `f_2` ≳ 5 MHz with `f_z` unchanged, i.e.
`Cc/Cf` ≳ 900 against the 98 this record lands. Both ends are now bounded by
things that are *measured* rather than assumed:

- `Cf` cannot fall below ≈ 45 fF at these gate areas without `peak_excess_db`
  going positive (the table in §2), and the gate-area lever that would let it
  is one step wide and has been taken.
- `Cc` cannot rise without spending §4's PSRR budget — but it now has 1.07 dB
  of margin where it had 0.04 dB, which is ≈ 1.13× of `Cc`, i.e. ≈ 10 % more
  shelf. Not the missing factor of 9.

So the missing factor is still an architecture change, and DR-0009's
Candidate 2 (adaptive biasing of the buffer from a pass-device sense replica)
is still the named one — **but this record narrows what it must do**. It is a
load-proportional lever, so it cannot help the 0.1 mA column at all (both of
that column's failure clusters were at the *same* load, 20× apart in `f_c`
because of `C_eff`, and no load-sensing scheme distinguishes them). Its
target is precisely the 1–50 mA columns, where `f_c ∝ gm_pass` really is the
mechanism. That is a cleaner brief than DR-0009 could give it.

## Alternatives considered

- **Grow `Cc` instead of shrinking `Cf`.** Same effect on `Cc/Cf`, and it also
  lowers `f_z`, which is what the 4.7 µF/hot cluster wants. Rejected as the
  primary lever: `Cc` is `A_amp(1 kHz)`, i.e. the ratified PSRR row, and at
  `c828e73` that row had 0.08 dB of margin — there was nothing to spend. It
  becomes available *after* this record (1.04 dB now), which is noted in
  Decision §4 as ≈ 10 % more shelf, not as a solution.
- **A nulling resistor in series with `Cf`** (`Rf` from `N1` to `Cf`, to put a
  zero at the local loop's crossover and buy back the phase `p2` costs).
  Built and measured: `Rf` = 3 MΩ with `Cf` = 36 fF takes `peak_excess_db`
  from ≤ +2 dB to **+11.3…+24.3 dB at every one of the 81 points** — far worse
  than no `Rf` at all. Above `1/(2π·Rf·Cf)` the Miller branch is resistive and
  the compensation simply stops, which lands below where it is needed. Not
  pursued further; a much smaller `Rf` would be safe but buys a proportionally
  negligible amount of lead.
- **Raise the buffer's bias current to lift `p2`, instead of shrinking gate
  area.** Measured: `Mbufb` 80 µm → 120 µm (buffer bias ×1.6, amp Iq worst
  corner 14.7 → 16.4 µA, over the 15 µA allocation) moves `peak_excess_db`
  at `Cf` = 36 fF only from +2.30 to +1.28 dB — still failing. The exchange
  rate is poor for the same reason DR-0009 measured a poor one, and the gate-
  area lever in §2 is strictly better: it moves the same pole further, for
  nothing.
- **Trim `Mpgn` to fund the tail increase.** Tried; see §4 above. It breaks
  the DC operating-point solve at one corner and was reverted.
- **Do nothing and record a third negative result.** This was the expected
  outcome going in, given DR-0010 and DR-0011. It is not what the measurements
  said.

## Consequences

- **The 0.1 mA column is closed and every other column improves on net**, but
  the head loop-stability record is still an overall **FAIL** against
  DR-0001's full-matrix criterion (1332/4536). Issue #53's first criterion is
  met; the matrix as a whole is not, and this record does not claim otherwise.
  The net improvement is not uniform — 77 points outside the 0.1 mA column
  trade PASS → FAIL against 310 the other way, 63 of them on gain margin
  alone (Decision §2).
- **DR-0009 is corrected, not superseded.** Its frontier equations, its
  `A_plat ≥ 98` bound, its measured envelope and its judgement that 1–50 mA
  is out of reach for this compensation all stand. The subsection "`f_2` is
  set by Iq, and it does not scale" is wrong about the mechanism: what that
  subsection measured (tripling the buffer and stage-2 currents moves the
  largest *stable* shelf corner 131 → 393 kHz) is the **ceiling** on `f_2`,
  which is indeed current-bound; `f_2` itself is `1/(2π·Rz·Cf)`, and the
  committed design was sitting a factor of three below its own ceiling.
- **DR-0010 and DR-0011 remain correct as negative results**, and the family
  they close out (a super source follower around `Mbuf`) is still closed.
  DR-0011's general lesson — that a local loop can be individually stable and
  still cost the enclosing LDO loop margin — is what makes §2's
  `peak_excess_db` table the binding constraint here rather than a formality.
- **Regression rows, every one re-measured against the same bench and cited
  by record:**
  - `sim/amp-openloop/records/20260802-163812-deb3dbd.md` — PASS 81/81
    (`gain_1k_db` 54.57 dB worst, `iq_ua` 14.98 µA worst, `peak_excess_db`
    +0.17 dB worst).
  - `sim/psrr-dc/records/20260802-164053-c999cb4.md` — PASS 81/81
    (`psrr_ldo_1k_db` 51.04 dB worst against the ratified 50 dB).
  - `sim/quiescent-current/records/20260802-164119-56dae34.md` — PASS 45/45
    (9.12–22.00 µA enabled, 0.20 µA disabled, against < 30 µA).
  - `sim/amp-selfosc/records/20260802-164210-7c2ff06.md` — light rows PASS
    45/45 (0.028–0.44 µV pk-pk on `BG`); the heavy rows carry the same
    pre-existing failure DR-0009 attributes to the LDO loop.
  - `sim/dropout-vs-load/records/20260802-164148-de1161d.md` — unchanged to
    within 32 µV, including its pre-existing 1 mV miss of the 300 mV row.
  - `sim/enable-shutdown/records/20260802-172454-b90b2ba.md` — all four
    ratified clauses PASS at 63/63 corners (shutdown Iq 0.204 µA,
    Vin→Vout leakage 0.214 µA, disabled-`VOUT` tail ≤ 7.7 µV, enabled Iq
    24.81 µA at the binding corner against < 30 µA, up from 23.58 µA). Its
    informational large-signal window measurements improve across the board
    (post-settling ripple 0.095–0.301 → 0.053–0.198 V; corners engaging
    `ldo_ilimit`'s clamp while settled at 50 mA 57 → 39), with
    `isup_peak_ma` the single quantity that got worse (248.4 → 279.6 mA
    worst corner — `sim/startup/`'s ratified claim, not this bench's).
- **`a0_db` falls ≈ 2 dB** (109.0–115.7 → 105.9–113.1) because `M2P`'s channel
  length halves. It is 46 dB clear of its 60 dB floor and no DC row moves; it
  is recorded here because it is the one measured quantity that got worse and
  is not otherwise flagged anywhere.
- **Area falls.** `Cf1`/`Cf2` go 2 × 144 µm² → 2 × 49 µm², and the three
  resized transistors give up ≈ 465 µm² of gate area between them. Nothing in
  the cell grew. §6.5's layout note on `Cf` still applies and matters more: at
  49 fF the two MIM devices' bottom-plate parasitic is a larger fraction of
  the value than it was at 149 fF, and `Cf` now sets a compensation corner the
  0.1 mA claim depends on directly.
