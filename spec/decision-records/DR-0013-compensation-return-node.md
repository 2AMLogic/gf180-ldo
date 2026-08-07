# DR-0013: `f_2`'s ceiling is the compensation network's return node, not an Iq budget — and adaptive *bias* cannot be the lever

- **Status**: proposed — ratification is the operator's, the same process
  DR-0001, DR-0004 and DR-0008 went through. **Nothing in this record is in
  force until an operator ratifies it.** What is not conditional on
  ratification is the evidence: every number below is a run of a committed,
  unmodified testbench against a stated one-variable edit of
  `design/error_amp.sch`, and the commands are given so each is reproducible.
- **Date**: 2026-08-07
- **Decided by**: Builder agent, issue #51 (recommendation only)
- **Relates to**: DR-0008 (ratified — the RHP-pole precondition, respected
  throughout), DR-0009 (the shelf-corner/crossover frontier, and its
  Candidate 1 / Candidate 2 list), DR-0010 / DR-0011 (Candidate 1, closed),
  DR-0012 (the shelf's width is `Cc/Cf`). It supersedes none of them. It
  **closes DR-0009's Candidate 2** in the form it was named, and it identifies
  a constraint that DR-0009 and DR-0012 both attributed to bias current and
  this record measures to be a **topology choice**.
- **Ships no circuit change.** `design/` is unchanged by the PR that adds this
  record; see "Why nothing is landed" below.

## Context

DR-0012 closed the 0.1 mA column (756/756) and left the 1–50 mA columns needing
a Type-II gain shelf `Cc/Cf ≳ 900` against the 98 it landed, with both ends of
that ratio measured to be pinned — `Cc` by the PSRR row, `Cf` by the local
loop's own non-dominant pole. It named DR-0009's Candidate 2 (adaptive biasing
from a pass-device sense replica) as the only lever left.

Issue #51 built Candidate 2 and measured it. It does not work, for a reason
that generalises. On the way, the same measurements located the constraint that
*does* move, and it is not one anybody had varied.

Head record at the time of writing:
`sim/loop-stability/records/20260802-204343-e912fbd.md` — 1332/4536, worst
point `res_ss`/27 °C/2.97 V at 50 mA / 0.33 µF / 1 mΩ, PM −98.86°,
GM −21.15 dB, DR-0008 resurgence 0/4536.

## 1. The frontier restated in `Rz` — and why a *fixed* `Rz` cannot cover 10–50 mA

DR-0009's two quantities and DR-0012's correction combine into one statement
with a single free variable. With `f_z = 1/(2π·Rz·Cc)`, `f_2 = 1/(2π·Rz·Cf)`
and `f_c = β·gm(MIN)·Rz·gm_pass/(2π·C_eff)`:

```
f_c/f_z ∝ Rz²        f_2/f_c ∝ 1/Rz²        (f_c/f_z)·(f_2/f_c) = Cc/Cf
```

`Rz` slides `f_c` through the shelf quadratically, and the total budget it has
to slide inside is the shelf width. Measured — `sim/loop-stability/`,
`--no-write`, tt/27 °C/3.30 V, 1 mΩ ESR, `design/error_amp.sch` exactly as
committed at `c628c15` except for `Rz`'s length, ten values from 100 kΩ to
6 MΩ — the `Rz` range that clears **both** DR-0001 bars at **each** `C_eff`,
and their intersection:

| `I_load` | 0.33 µF needs | 1 µF needs | 4.7 µF needs | intersection |
|---|---|---|---|---|
| 0.1 mA | ≥ 1.1 MΩ | ≥ 1.6 MΩ | ≥ 3.8 MΩ | **3.8 MΩ … ∞** |
| 1 mA | 0.30 … 1.75 MΩ | 0.43 … 4.5 MΩ | ≥ 1.3 MΩ | **1.3 … 1.75 MΩ** |
| 10 mA | 0.16 … 0.30 MΩ | 0.25 … 1.3 MΩ | ≥ 0.45 MΩ | **empty** |
| 25 mA | 0.15 … 0.30 MΩ | 0.24 … 0.62 MΩ | ≥ 0.41 MΩ | **empty** |
| 50 mA | 0.13 … 0.30 MΩ | 0.20 … 0.30 MΩ | ≥ 0.37 MΩ | **empty** |

(Upper bounds are set by *gain* margin at 0.33/1 µF, lower bounds by *phase*
margin at 4.7 µF — the two bars pull in opposite directions, which is the whole
mechanism.)

Two things follow, and they are the shape of the remaining work:

- **No single `Rz` works at 10–50 mA.** The 0.33 µF gain-margin ceiling and the
  4.7 µF phase-margin floor cross, by a factor of 1.2–1.5 in `Rz`. That is the
  ratified 14.2× `C_eff` window not fitting inside a 98× shelf once the ~10× of
  round-trip margin the two bars need is taken out.
- **The load axis on its own is coverable** — 0.1 mA wants ≥ 3.8 MΩ, 50 mA
  wants ≈ 0.25 MΩ, a 15× ratio — *if* `Rz` can be made to move with load. So
  "adaptive" is right; the question is which element.

## 2. Adaptive *bias* (DR-0009's Candidate 2, as named) — negative result

**The physics is right, and this is worth stating precisely because it is the
first direct confirmation of it.** `f_c ∝ gm(MIN)·Rz`, and `gm(MIN)` is the
only factor in `f_c` that does not also move `f_z` or `f_2`. Scaling the
input-pair tail by hand (`MTAIL` `W/L` 6.6/4 → 0.22/16, ≈ 120× less tail
current) and changing nothing else — `sim/loop-stability/`, `--no-write`,
tt/27 °C/3.30 V, 1 mΩ:

| `I_load` | 0.33 µF PM / GM | 1 µF PM / GM | 4.7 µF PM / GM |
|---|---|---|---|
| 10 mA | 70.43° / 23.57 dB | 77.65° / 34.16 dB | 48.82° / 46.22 dB |
| 50 mA | 54.45° / 17.66 dB | 78.62° / 27.69 dB | 62.98° / 46.78 dB |

Both columns clear both bars at all three capacitors. The committed design at
the same six points reads −65.45°/−13.94 dB, −20.14°/−4.28 dB, +41.62°/+9.41 dB
(10 mA) and −90.70°/−19.72 dB, −48.03°/−10.09 dB, +16.43°/+3.56 dB (50 mA).
**A load-scheduled `gm(MIN)` closes the heavy-load columns outright**, at
tt/27 °C, with margin.

**And it cannot be built in this cell.** The only observable of load current is
the pass device's gate — which is the amplifier's own output node. So any
circuit that senses load and steers an amplifier *bias current* closes the loop

```
OUT → sense replica → tail current → amplifier input-referred offset → OUT
```

whose gain is `A_DC · dV_os/dV_OUT`. `A_DC` is 105.9–113.1 dB measured
(`sim/amp-openloop/`), and `dV_os/dV_OUT` cannot be made small: the 5T stage's
systematic offset is `λ_p·ΔV_ds(MLD1,MLD2)·I/gm(MIN)`, and both `ΔV_ds`
(through `V_ND`) and `gm(MIN)` move by construction when the tail is scheduled.
Loop gain below 1 would need the offset to move by **less than a few
microvolts** over the ≈ 300 mV that `Vsg(Mpass)` swings across the load range.

Measured, on a built three-segment adaptive-tail cell (pass-replica pfet on
`OUT`; nfet diode; two sense-driven pull-downs on two of three tail-segment
gates through 3 MΩ resistors from `NBIAS`): the Tian extraction's DC loop gain
went from **+143.3 dB with phase −0.27° at 0.01 Hz** (committed design —
positive real at DC, as a negative-feedback loop must be) to **phase ≈ ±180° at
DC** at both 0.1 mA and 10 mA, with `dcgain_db` 143.3 → 100.7 dB. A `T(s)` that
is negative real at DC is the signature of a minor loop that is itself in
positive feedback with gain > 1: the operating point the solver settles on is
not a stable one, and DR-0008's precondition is violated by construction rather
than by tuning.

*Scope of that attribution*: the sign flip and the 42.6 dB DC-gain collapse are
measured. The mechanism above is this record's explanation for them; the built
cell also drew its pull-down current out of `NBIAS`, and the two contributions
were **not** separately isolated. The generalisation below does not depend on
which of the two dominates.

**The generalisation, and why this closes the family.** The elements in this
cell that can be adapted *without* closing that loop are exactly the ones that
carry **no DC current** — `Rz` (DC-blocked by `Cc`) and the compensation
capacitors. Every bias current is inside the offset path. DR-0010 and DR-0011
rejected Candidate 1 empirically; this is a reason underneath all three
attempts.

## 3. What actually caps `f_2`: the compensation network's return node

DR-0009 read `f_2`'s ceiling as a bias-current quantity ("131 kHz as committed,
393 kHz for 1.9× the amplifier's whole Iq"). DR-0012 corrected *what sets* `f_2`
(`1/(2π·Rz·Cf)`) and kept the ceiling as measured. Both are describing the same
thing: with `Cc` returned to `OUT`, the local loop the shelf rides on is

```
N1 → M2P → BG → Mbuf → OUT → Cc/Rz → N1
```

so it contains **the class-AB buffer and the 6.14 pF pass gate**. Its crossover
*is* `f_2`, and it cannot exceed that pole. §1 asks for `Rz` = 0.25–1 MΩ at
10–50 mA. Measured, changing only `Rz`:

| `Rz` | `f_2` | evidence (unmodified committed bench) | verdict |
|---|---|---|---|
| 6 MΩ (committed) | 541 kHz | `sim/amp-openloop` `peak_excess_db` −0.13 dB, 81/81 (DR-0012) | PASS |
| **3 MΩ** | 1.08 MHz | `sim/amp-openloop`, full 81-point grid: **78 CHECK FAILs** (40 `peak_excess_db`, 38 `peak_excess_lightload_db`), worst **+3.41 dB** against the ≤ 1 dB bar | **FAIL** |
| **0.6 MΩ** | 5.4 MHz | `sim/loop-stability` DR-0008 resurgence **+1.31 dB** at 25 mA/0.33 µF and **+3.74 dB** at 50 mA/0.33 µF (tt/27 °C/3.30 V/1 mΩ) | **FAIL (DR-0008)** |

**`Rz` was already at its floor in the committed design**: halving it breaks
the amplifier's own local loop at 78 of 162 checks. So on this topology the
adaptive-`Rz` lever does not exist either, and §1's table is unreachable from
both ends.

**Moving `Cc`'s far terminal from `OUT` to `BG` removes the cap.** `Cc` then
spans `M2P` alone — the same two nodes `Cf1`/`Cf2` already span — so the buffer
and the pass gate leave the local loop entirely. The shelf algebra is untouched,
which is the point: the buffer is a unity follower, so `v_OUT` and `v_BG` carry
the same signal and

```
A_amp = gm(MIN) / ( 1/(Rz + 1/(s·Cc)) + s·Cf )
```

is the same expression either way — `f_z`, `f_2`, `A_plat` and the `Cc/Cf`
shelf width are all unchanged. What changes is only which poles the local loop
must live with. Measured, `Cc` → `BG` as the **only** other edit:

| variant | `Rz` | `f_2` | evidence | verdict |
|---|---|---|---|---|
| `Cc` → `OUT` | 3 MΩ | 1.08 MHz | 78 CHECK FAILs, worst +3.41 dB | FAIL |
| **`Cc` → `BG`** | **0.75 MΩ** | **4.3 MHz** | `sim/amp-openloop`, full 81-point grid: **PASS 81/81**, `peak_excess_db` **−0.077 … −0.030 dB**, `peak_excess_lightload_db` −0.077 … −0.030 dB | **PASS** |

and on `sim/loop-stability/`'s 15-point tt/27 °C load × cap grid, worst
`resurgence_db` with `Cc` → `BG`: −0.40 dB at `Rz` = 6 MΩ, −0.42 dB at 1.5 MΩ,
−0.43 dB at 0.75 MΩ, −0.37 dB at 0.4 MΩ.

**That is an ≥ 8× rise in the `f_2` ceiling for one net change and zero
microamps**, against DR-0009's measured exchange rate of 1.9× the amplifier's
entire Iq for 3×. The same 81-point run shows the amplifier's other rows
essentially unmoved: `gain_1k_db` **54.31 … 63.57 dB** (committed: 54.57 …
63.68; the PSRR proxy loses 0.26 dB of its 1.07 dB margin), `iq_ua` **5.88 …
14.98 µA** (committed: 14.98 µA worst — unchanged), `a0_db` 105.9 … 113.1 dB,
`vos_sys_uv` 332 … 771 µV.

## 4. Why nothing is landed

An adaptive-`Rz` cell was built on top of §3 (pass-replica sense, three
current-comparator branches switching three `ppolyf_u_3k` shunt legs across
`Rz`, all DC-currentless by construction per §2). At tt/27 °C/3.30 V/1 mΩ it
reaches **10 of 15** load × cap points against the committed design's **5 of
15**, with DR-0008 resurgence clean (≤ −0.37 dB) at every point. It is not
landed, for two measured reasons:

1. **It regresses the 0.1 mA column, which DR-0012 closed.** At
   `ss`/−40 °C/3.63 V, 0.1 mA / 0.33 µF / 1 mΩ: committed **48.64° /
   13.64 dB**; `Cc` → `BG` alone **44.73° / 10.79 dB** (below DR-0001's 45°);
   with the shunt ladder **40.86° / 9.41 dB**. Most of the loss is intrinsic to
   the return-node move, not to the ladder. Issue #51's own acceptance criteria
   forbid trading the 0.1 mA column for the heavy ones.
2. **It costs an order of magnitude of bench time.** The three
   current-comparator gate nodes are driven by two current sources each and are
   very high impedance, which the DC operating-point solve pays for: a single
   `(corner, load, cap, ESR)` point at `ss`/−40 °C/3.63 V goes from ≈ 1.3 s to
   ≈ 13 s, i.e. the full 4536-point matrix from ≈ 12 min to ≈ 2 h. That is a
   cost the next increment should design out (a weak resistive pull-up on those
   nodes is the obvious fix), not inherit.

A partial-pass record with a regressed 0.1 mA column is exactly what issue #51
exists to prevent, so `design/` is left at `c628c15` and this record ships the
measurements instead. The head loop-stability record is unchanged at
**1332/4536**.

## Decision

**1. DR-0009's Candidate 2 is closed as a negative result in the form it was
named** — adaptive biasing of an *amplifier bias current* from a pass-device
sense replica — for §2's reason, which is structural and not a tuning residue.
What survives of it is adaptive control of a **DC-currentless** element. A
future record should not re-open the bias-current form without first showing
how it breaks the `OUT → bias → offset → OUT` loop; cascoding the stage-1
mirror load is the obvious candidate and is not attempted here.

**2. `f_2`'s ceiling is a topology property, and DR-0009's Iq-vs-`f_2` curve
should not be quoted as a general bound after this record.** It is correct
*for the `Cc` → `OUT` topology*. Returning `Cc` to `BG` raises the same ceiling
≥ 8× for free (§3).

**3. The next increment is: `Cc` → `BG`, then re-open the shelf width, then
adaptive `Rz` — in that order.** With the buffer out of the local loop, the two
quantities DR-0012 measured as pinned are no longer pinned by the same things:

- **`Cf` is the end to re-measure first.** DR-0012 §2's `Cf` floor (≈ 45 fF)
  was set by `p2` racing the buffer pole in one loop. That race is gone. This
  measurement was **not** made here and is the single highest-value follow-up:
  §1's residual is a factor of 1.2–1.5 in `Rz`, i.e. **1.5–2× of `Cc/Cf`**
  against the 98 committed — which is the same order as one step of `Cf`.
- **`Cc` still costs PSRR**, and §3 measures the proxy at 54.31 dB against
  53.5 dB with `Cc` → `BG` at `Rz` = 0.75 MΩ, so that end has ≈ 0.8 dB
  (≈ 10 % of `Cc`) and no more.
- Only once the shelf is wide enough to hold 14.2× of `C_eff` at one load with
  margin does the adaptive-`Rz` ladder become worth building — and it must be
  built with low-impedance control nodes (§4.2).

**4. This record relaxes no bar.** DR-0001's 45° / 10 dB, its `C_eff` and ESR
windows and its load axis are untouched, as are the PSRR, Iq and
output-accuracy rows.

## Alternatives considered

- **Adaptive `Rz` on the committed `Cc` → `OUT` topology.** Measured and
  rejected: §3's table — `Rz` = 3 MΩ already fails `sim/amp-openloop` at 78
  checks, and §1 asks for 0.25–1 MΩ. The lever does not exist before the
  return-node change.
- **Widen the shelf by growing `Cc` and restoring PSRR with a wider input
  pair** (`MIN1`/`MIN2` 60 µm → 240 µm at the same current, `Cc` 48 × 48 µm →
  78 × 78 µm). Built and swept over `Rz` = 0.6–6 MΩ: it does widen the per-load
  `Rz` windows (0.1 mA becomes 2.2–5 MΩ, 1 mA becomes 0.8–1.5 MΩ) but does not
  close 10–50 mA, and at `Rz` = 3 MΩ it fails `sim/amp-openloop`'s
  `peak_excess_lightload_db` at 21 of 81 corners for §3's reason — the buffer
  pole, not the component values. Worth revisiting *on top of* Decision §3.
- **Re-tune `Cff`** (`ldo_core`'s feedforward cap across `Rtop`). Swept
  0.22 × 0.22 µm … 140 × 140 µm at the committed compensation: the committed
  87 × 87 µm is already at the optimum to within a degree or two at every
  load × cap point measured, at every load. No change.
- **A fixed `Rz` at the value the heavy columns want** (1–2.5 MΩ). Roughly
  doubles the tt pass count and takes the 0.1 mA column below 756/756. Rejected
  for the same reason as §4.1.
- **Ship the §4 cell anyway and record the trade.** Rejected: issue #51's
  acceptance criteria were written specifically to stop a partial-pass record
  from closing a ratified stability row, and a 0.1 mA regression is the exact
  trade DR-0012 was careful not to make.

## Consequences

- **DR-0012 §4's "missing factor of 9" is measured down to ~1.5–2×**, but only
  conditionally: on the `Cc` → `BG` topology, and with `Cf`'s new floor still
  unmeasured. The 9× figure remains correct for the committed topology.
- **The 0 mA column is untouched by any of this.** It fails 743 of 756 points
  in the head record for the reason DR-0007 states, and no lever in this record
  reaches it (all of them are load-proportional). DR-0007 stays the right place
  for that decision.
- **`sim/amp-openloop`'s `peak_excess_db` is the cheapest gate on `f_2`.** It
  caught the `Rz` = 3 MΩ case in 9 minutes where a full loop-stability matrix
  would have taken two hours. Any future compensation increment should run it
  first.
- **A reproduction note.** Every `--no-write` figure above comes from
  `sim/loop-stability/testbench/sweep.py --no-write --corners <c> --temps <t>
  --supply-tol 0 --loads-ma ... --caps-uf ... --esrs 0.001`, and every 81-point
  figure from `python3 sim/run_corners.py amp-openloop --no-write -j8`, in each
  case against `design/error_amp.sch` at `c628c15` with the single stated edit
  and `design/netlist.py` re-run. No testbench, threshold or matrix definition
  was modified anywhere in this work.
