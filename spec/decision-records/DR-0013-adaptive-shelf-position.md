# DR-0013: The shelf does not need to be wider, it needs to move — and moving it hits the same `p2` ceiling. Candidate 2, measured and rejected at the committed operating point

- **Status**: proposed — a **negative result**, in the same spirit as DR-0010
  and DR-0011. Nothing here is a spec change and nothing here is in force
  until an operator ratifies it. What is *not* conditional on ratification is
  the evidence, which is minted in `sim/amp-openloop/records/` and stands on
  its own.
- **Date**: 2026-08-07
- **Decided by**: Builder agent, issue #51 (recommendation only)
- **`design/` netlist**: **unchanged.** The circuit described here was built,
  netlisted, measured against the amp-level bench, and then reverted — see
  "Decision". The commit it was measured at (`225aba8` on `feature/issue-51`)
  is retained in this branch's history so the record below resolves against a
  real tree.
- **Corrects**: DR-0012's Decision §4, on one point of framing (§1 below).
  **Confirms**: DR-0012's Consequences, on the point that matters (§3).
  It supersedes neither DR-0012 nor DR-0009.

## Context

DR-0012 left issue #51 with exactly one named lever — DR-0009's Candidate 2,
adaptive biasing of the pass-gate buffer from a pass-device sense replica —
and a quantitative brief for it: the 1–50 mA columns need the Type-II gain
shelf about 9× wider than the `Cc/Cf` = 98 the committed design achieves, and
neither end of `Cc/Cf` can move that far (`Cf` cannot fall below ≈ 45 fF
without the local `Rz`/`Cc` loop resurging; `Cc` cannot rise without spending
the ratified PSRR row).

Head record at the start of this work,
`sim/loop-stability/records/20260802-204343-e912fbd.md`: **1332 of 4536**
points pass DR-0001's PM ≥ 45° / GM ≥ 10 dB bars; worst point `res_ss`/27 °C/
2.97 V at 50 mA / 0.33 µF / 1 mΩ reads PM −98.86°, GM −21.15 dB; DR-0008
resurgence clean at 0 of 4536. Worst PM by load column: 0 mA +3.71°,
0.1 mA +45.98° (the only passing column), 1 mA −19.07°, 10 mA −75.06°,
25 mA −89.97°, 50 mA −98.86°.

This record reports what happened when Candidate 2 was actually built.

## 1. The framing correction: `Rz` moves the shelf, and position is an `Rz²` lever

DR-0012 measured the load axis against a shelf held still and asked how much
*wider* it must get. But `Rz` sets **both** shelf corners *and* the plateau
gain, so all three of the quantities that decide whether a point passes move
together with it:

```
f_z = 1/(2*pi*Rz*Cc)     f_2 = 1/(2*pi*Rz*Cf)     A_plat = gm(MIN)*Rz
f_c = beta*A_plat*gm_pass/(2*pi*C_eff)

  =>   f_c/f_2  =  beta*gm(MIN)*Cf*Rz^2*gm_pass/C_eff
       f_c/f_z  =  beta*gm(MIN)*Cc*Rz^2*gm_pass/C_eff
```

Both ratios go as **`Rz²`**. Reducing `Rz` by `k` raises the whole shelf by `k`
*and* pulls the crossover down by `k`, so it buys `k²` of load range where
widening the shelf by `k` buys `k`. DR-0012's missing factor of 9 is a factor
of **3 in `Rz`** — which is a much smaller ask than `Cc/Cf` ≳ 900, and it is
not blocked by either of the two bounds DR-0012 identified.

**Measured**, with `Rz` swept as a plain fixed resistor and every other device
exactly as committed at `c628c15` (`sim/loop-stability/`, `--no-write`
exploration runs — not minted records), `res_ss`/27 °C/3.30 V, 1 mΩ ESR:

| `Rz` | 50 mA / 0.33 µF | 50 mA / 4.7 µF | 1 mA / 0.33 µF | 0.1 mA / 4.7 µF |
|---|---|---|---|---|
| 6.0 MΩ (committed) | PM −95.4° / GM −21.2 dB | +9.3° / +2.0 dB | −11.0° / −2.4 dB | +68.5° / +45.5 dB |
| 1.5 MΩ | −87.5° / −9.0 dB | **+77.9° / +14.2 dB** | **+69.4° / +10.0 dB** | **+22.2°** / +44.0 dB |
| 0.5 MΩ | +56.1° / −3.6 dB | — | +67.9° / +15.7 dB | — |

One 4× change in one resistor takes 50 mA / 4.7 µF from a hard fail to a
comfortable pass, and does the same for 1 mA / 0.33 µF. It also breaks the
0.1 mA / 4.7 µF point DR-0012 closed (+68.5° → +22.2°), because `f_c`
(6.5 kHz) has fallen below `f_z` (22 kHz) and the loop is back on the
integrator's −40 dB/dec. So `Rz` has to be a **function of the load** — which
is Candidate 2, arriving at the compensation network rather than at the
buffer.

**The sense costs nothing to obtain.** `OUT` *is* the pass device's gate, so
`V(N1) − V(OUT) = Vsg(Mpass) − Vsg(M2P)`: a load-proportional signal with one
pfet gate-source voltage already differenced out of it, no replica branch, no
microamp of bias. Measured pass-gate swing over 0.1 → 50 mA at
`tt`/27 °C/3.30 V: 2.664 V → 1.990 V, i.e. **674 mV** of sense for 500× of
load, and a further 145 mV of it between 0.1 mA and 1 mA.

## 2. What was built

Seven devices in `design/error_amp.sch`, no port change, no existing device
resized:

| device | what it is |
|---|---|
| `Mlvl` (pfet 1 µm/1 µm, source `OUT`, diode) + `Mlvlb` (nfet 8 µm/0.8 µm off `NBIAS`, ≈ 0.15 µA) | one-`Vsg` level shift below `OUT`, so `Vsg(Mrz) = Vsg(Mpass) − Vsg(M2P) + Vsg(Mlvl)` — the sense is referenced through pfet gate-source voltages that track over process rather than against an absolute threshold |
| `Rsg` (2 MΩ) + `Csg` (32 × 32 µm MIM, 2.05 pF) | 39 kHz pole, so the schedule is slower than the loop it schedules |
| `Mrz` (pfet 1 µm/18 µm, source `NRM`, drain `NZ`, gate `NRZ`, body `VDD`) | the shunt across `Rz`. Its `Vds` is **exactly zero** at every operating point — `Cc` blocks DC, so the `Rz` branch carries none — making it a pure gate-controlled conductance with `gm = 0`: no quiescent current at any load, and no signal injected into the compensation branch |
| `Rmin` (1.2 MΩ, in series with `Mrz`) | floors the shunt branch, so the adapted value cannot fall below `6 MΩ ∥ 1.2 MΩ` = 1.0 MΩ however hard `Mrz` turns on |
| `Mbufa` (pfet 1 µm/0.22 µm, `VDD` → `OUT`, gate `NRZ`) | the literal "adaptive biasing of the pass-gate buffer" half of Candidate 2 |
| `Mrz_pu` (pfet 0.5 µm/4 µm, gate `EN`) | disabled-state pull-up, same job as `Mbg_pu`/`Mn1_pu` |

Measured schedule (read in-situ from the loop crossover, which is proportional
to `Rz_eff` while the loop crosses in the shelf; calibrated against the
fixed-`Rz` sweeps at 0.222–0.233 Hz/Ω), `res_ss`/27 °C/3.30 V: `Rz_eff` ≈
6.0 MΩ at 0.1 mA, ≈ 2.4 MΩ at 1 mA, `Rmin`-floored at ≈ 1.0 MΩ from 10 mA up.

And in closed-loop Bode terms **it works**, dramatically. Measured
(`--no-write`) at `res_ss`/27 °C/3.30 V, 1 mΩ ESR, against the head record's
own numbers at the same points:

| point | before (PM / GM) | after (PM / GM) |
|---|---|---|
| 1 mA / 1 µF | +32.0° / +7.3 dB | +56.1° / +12.7 dB |
| 10 mA / 1 µF | −26.8° / −5.8 dB | **+76.3° / +12.7 dB** |
| 25 mA / 1 µF | −43.4° / −9.3 dB | **+74.9° / +12.3 dB** |
| 50 mA / 1 µF | −54.2° / −11.6 dB | **+73.7° / +11.6 dB** |
| 10 mA / 4.7 µF | +34.9° / +7.9 dB | **+59.4° / +25.2 dB** |
| 25 mA / 4.7 µF | +19.6° / +4.3 dB | **+62.7° / +25.1 dB** |
| 50 mA / 4.7 µF | +9.3° / +2.0 dB | **+66.5° / +24.8 dB** |
| 50 mA / 0.33 µF | −95.4° / −21.2 dB | +50.8° / +1.9 dB |
| 0.1 mA / 0.33 µF | +63.0° / +15.7 dB | +64.4° / +17.7 dB |
| 0.1 mA / 4.7 µF | +68.5° / +45.5 dB | +67.7° / +42.8 dB |

Nine of ten points improve, six of them from a hard fail to a clear pass, and
the 0.1 mA column is untouched. `sim/loop-stability/`'s own DR-0008 gain
resurgence detector reads clean (worst −0.35 dB) over all fifteen configs
probed at that corner.

**None of that is admissible, and §3 is why.**

## 3. Why it is rejected: the amp-level bench, at 81 of 81 corners

`sim/amp-openloop/records/20260807-074343-225aba8.md` — full 81-point PVT
grid, unmodified bench, clean tree at `225aba8`. **FAIL at 81 of 81 corners**,
on three independent rows.

### 3a. `peak_excess_db`: DR-0008's precondition, violated — 72 of 81 corners

| | bar | committed (`20260802-163812-deb3dbd`) | this circuit |
|---|---|---|---|
| `peak_excess_db` | ≤ 1 dB | −0.10 … **+0.17** dB | −0.12 … **+19.05 dB** (`ff`/125 °C/2.97 V) |
| `peak_excess_lightload_db` | ≤ 1 dB | ≤ 0 | −0.11 … **+9.37 dB**, 6 corners |

That row is not a style preference. Its own definition in
`sim/amp-openloop/testbench/tb.json` says it: *"A positive value is resonance
in the amplifier's OWN local feedback loop … If it rings, the LDO loop gain
`T(s)` has right-half-plane poles and DR-0001's Bode PM/GM criterion does not
apply to it (DR-0008)."* DR-0008 was **ratified on 2026-08-06**. So every
number in §2's table is a PM/GM reading taken on a loop whose precondition
does not hold — precisely the class of result DR-0008 exists to reject, and
precisely issue #51's own Acceptance Criterion 4.

**Why `sim/loop-stability/`'s resurgence detector missed it, which matters for
anyone reading these two benches side by side.** That detector reports how far
`|T|` climbs back above **0 dB** after the LDO loop's first 0 dB crossing. The
local-loop resonance here sits at 3–5 MHz, where `|T_LDO|` is already tens of
dB negative, so it never crosses 0 dB and never registers. `peak_excess_db`
measures the amplifier's own response against its own 200 kHz value and does
not care where the LDO loop is. **The two are not redundant, and the cheaper
one is not a substitute** — a point worth carrying forward, since DR-0008's
consequences section offered the loop-stability check as the cheap successor
to `sim/amp-selfosc/`.

**And the mechanism is the one DR-0012 already named.** `f_2 = 1/(2π·Rz·Cf)`
does not care which of its two factors moved. The local loop's non-dominant
pole `p2 ≈ gm(M2P)·Cf/(C_N1·C_BG + …)` does not move with `Rz` at all, so
scheduling `Rz` down drives `f_2` straight into the same ceiling `Cf` hits.
Measured from the `Rz` side, at 50 mA / 0.33 µF / 1 mΩ
(`sim/loop-stability/` resurgence, `--no-write`):

| `Rz_eff` | `f_2` | `res_ss`/27 °C | `res_ss`/125 °C | `ff`/125 °C |
|---|---|---|---|---|
| 0.8–1.5 MΩ | 2.2–4.1 MHz | clean (−0.20 … −2.04 dB) | — | — |
| 0.6 MΩ | 5.4 MHz | **+2.70 dB** (at 25 mA) | — | — |
| 0.56 MΩ | 5.8 MHz | clean (−0.35 dB) | **+2.88 dB** | **+13.15 dB** |
| 0.5 MΩ | 6.5 MHz | **+6.29 dB** | — | — |

DR-0012 measured the largest stable `f_2` at ≈ 600 kHz at the committed bias.
Holding `peak_excess_db` ≤ 1 dB therefore needs `Rz` ≳ 5.8 MΩ — i.e. **no
useful adaptation at all**. There is no value of `Rmin` that both helps and
passes.

### 3b. `vg_pulldown_mv`: the adaptive buffer pull-up costs the dropout row — 81 of 81 corners

| | bar | committed | this circuit |
|---|---|---|---|
| `vg_pulldown_mv` | ≤ 50 mV | passing at 81/81 | **522 … 968 mV**, all 81 |

`Mbufa` is a pfet from `VDD` to `OUT` whose gate is `NRZ ≈ OUT − Vsg(Mlvl)`.
When the loop drives `OUT` toward `VSS` — which is exactly what the dropout
test point asks of it — `NRZ` follows it down, so `Mbufa`'s
`Vsg = VDD − NRZ` **grows**, and the device turns *harder on* precisely when
the amplifier needs the pass gate at ground.

This is the failure `design/error_amp.sch`'s own BUFFER section documents and
`Mbufb` was designed around: *"A plain follower with a fixed bias source
cannot pull `OUT` below `Vgs(Mbuf)` — its bias current has nowhere else to go
— which costs a whole `|Vtp|` of gate drive … the regulator loses regulation
entirely at Vin = 2.10 V / 50 mA at 8 of 15 dropout corners."* `Mbufb` avoids
it by referencing its gate to `N1`, so it turns fully **off** when the loop
demands maximum drive. Any pass-gate pull-up referenced to `OUT` instead —
which is what "adaptive biasing from the load" *means* if the load is sensed
at the pass gate — has the opposite sign by construction. **This is a
structural objection to the buffer half of Candidate 2, not a sizing
problem.**

### 3c. `iq_ua`: over the amplifier's allocation at 44 of 81 corners

| | bar | committed | this circuit |
|---|---|---|---|
| `iq_ua` (amp) | ≤ 15 µA (soft allocation) | 5.88 … 14.98 µA | 9.51 … **25.84 µA** |

Rows that did **not** regress: `a0_db` 105.4–112.7 dB (floor 60), `gain_1k_db`
54.24–63.42 dB (floor 53.5), `gain_1k_lightload_db`, `vos_sys_uv`,
`tail_hdr_mv`, `vg_pullup_hdr_mv`, `ugbw_khz` — all pass at 81/81.

## 4. What the residual gap actually costs, measured

Because §3a's ceiling is `p2`, and `p2` is a bias current, the wall has a
price. Measured at `res_ss`/27 °C/3.30 V, 50 mA / 0.33 µF / 1 mΩ with `Rz`
pinned at 0.5 MΩ, sweeping the stage-2 sink `M2N` and the buffer pull-up
`Mbufb` as **fixed** devices (the static form of the same change — no `Mbufa`,
so §3b does not arise), with the assembled regulator's supply current at the
binding `ff`/125 °C/3.63 V corner at full load alongside:

| `M2N` / `Mbufb` | buffer current | PM | GM | loop resurgence | `isup` at `ff`/125 °C, 50 mA |
|---|---|---|---|---|---|
| 4 µm / 100 µm (committed) | 2.3 µA | +56.1° | −3.6 dB | **+6.29 dB** | 22.60 µA |
| 4 µm / 200 µm | 4.9 µA | +59.3° | +3.1 dB | clean | 26.86 µA |
| 8 µm / 130 µm | 6.5 µA | +61.4° | +8.8 dB | clean | ≈ 31 µA |
| 12 µm / 200 µm | 15.6 µA | +62.5° | **+13.4 dB** | clean | 49.36 µA |

**Roughly 20 dB of gain margin per decade of buffer current**, and the
resurgence in §3a clears at the second row. The ratified row is
`Iq < 30 µA` **at no load and at full load** (README), whose binding corner
already reads 24.81 µA
(`sim/enable-shutdown/records/20260802-172454-b90b2ba.md`). Clearing
DR-0001's bars at 50 mA / 0.33 µF costs **≈ 9 µA at that corner**, against
≈ 5 µA of headroom.

**The residual 1–50 mA gap is a quiescent-current statement, not a
compensation-topology statement.** That is the substantive result of this
record, and it is what DR-0012's `Cc/Cf` ≳ 900 framing obscured: the topology
to close those columns exists, is small, and is already in the cell — it is
simply not affordable inside a ratified 30 µA at full load.

## Decision

**1. Do not land the circuit. `design/error_amp.sch` is unchanged**, on the
DR-0010/DR-0011 precedent: it fails a ratified precondition (§3a) at 72 of 81
corners and a ratified spec row's amp-level proxy (§3b) at 81 of 81. A design
that fails `peak_excess_db` cannot produce an admissible `sim/loop-stability/`
record, so no such record was minted — §2's numbers are `--no-write`
exploration and are labelled as such throughout.

**2. Candidate 2 is now closed at the committed operating point, both halves.**
DR-0009 named two candidate families; DR-0010 and DR-0011 exhausted
Candidate 1 (the super-source-follower sense buffer, all three bias schemes).
This record exhausts Candidate 2 as it can be built today:

- Its **compensation half** (schedule `Rz` on the load) is a real, large,
  `Rz²` lever — §1 and §2 measure it — but it drives `f_2` into the same `p2`
  ceiling that bounds `Cf`, so at the committed bias it buys nothing that
  DR-0008 will admit (§3a).
- Its **buffer half** (adaptive pull-up at `OUT`) is structurally
  incompatible with the pass-gate pull-down the dropout row needs, for a
  reason that does not depend on sizing (§3b).

**Issue #51 should not be handed a fourth compensation topology to try.** The
measured answer is that no compensation change closes 1–50 mA at this bias.

**3. What the next increment is, and it is an operator's call.** ≈ 9 µA at
`ff`/125 °C/3.63 V at full load, spent on `M2N` and `Mbufb`, raises `p2` far
enough that `Rz` can be scheduled to ≈ 0.5 MΩ with `peak_excess_db` in bounds
— at which point §2's Bode numbers become admissible and §4's fourth row says
they clear both DR-0001 bars at the worst point in the head record. There are
three ways to find that 9 µA and all three are outside Builder authority:

- **Split or amend the ratified `Iq < 30 µA` row.** It is currently ratified
  at *no load and at full load*. A load-scheduled bias costs almost nothing at
  no load, and 9 µA at 50 mA is 0.018 % of the load current. This is the
  cheapest option by a wide margin and the one this record would put in front
  of an operator first — but CLAUDE.md is explicit that agents do not relax
  ratified rows to make results pass, so it is stated, not taken.
- **Find the 9 µA elsewhere in the budget.** `design/error_amp.md` §5 reserves
  3–5 µA for a reference block that does not exist yet and ≈ 3.6 µA for
  `ldo_ilimit`. Both are real; neither is this issue's to spend.
- **Narrow DR-0001's `I_load × C_eff × ESR` box**, per DR-0001's own
  instruction that a corner which "proves unmeetable" gets a superseding
  record rather than a silently narrowed matrix. Note §2 measures the
  supportable envelope as materially wider than DR-0007 or DR-0012 could
  claim, so this would be a much smaller narrowing than either previously
  contemplated.

**4. This record relaxes no bar.** DR-0001's 45°/10 dB, its `C_eff` and ESR
windows and its load axis are untouched, as are the PSRR, Iq and accuracy
rows. It states which of them are in conflict, by how much, and at what
exchange rate.

## Alternatives considered

- **A smaller `Rz` schedule that stays inside `peak_excess_db`.** Arithmetic
  and measurement agree there is none: the bar needs `f_2` ≲ 600 kHz, i.e.
  `Rz` ≳ 5.8 MΩ against the committed 6 MΩ. `Rmin` can only bound how far the
  shunt goes; it cannot make the first useful step legal.
- **Keep the `Rz` schedule, drop `Mbufa`.** Removes §3b but not §3a, which is
  the disqualifying one. Also removes the only thing that was raising `p2`,
  making §3a worse.
- **Keep `Mbufa`, drop the `Rz` schedule.** Buys nothing on its own — the
  shelf still does not move — and costs both §3b and ≈ 3.9 µA at the binding
  corner.
- **Reference the adaptive pull-up to `N1` instead of to `OUT`**, so it turns
  off on maximum drive the way `Mbufb` does. That is not an adaptive device
  at all: `N1` sits at `VDD − Vsg(M2P)` and moves by under 2 mV across the
  whole 0.1 → 50 mA column (measured: 3.10248 → 3.10434 V at `ff`/125 °C/
  3.63 V). It carries no load information, which is precisely why `Mbufb`'s
  gate is safe there.
- **A pass-device current replica rather than a gate-voltage sense** (the
  textbook Candidate 2). Rejected before building, on Iq and geometry: a
  same-`L` replica of the 2000 µm/0.28 µm pass device delivers 1.25 mA at
  `ldo_ilimit`'s 1/40 ratio and needs a sub-0.1 µm width to reach the ≈ 1 µA a
  bias branch can afford, while a longer-`L` replica stops tracking the pass
  device's threshold. It would also not have changed §3a, which is about where
  `f_2` lands, not about how the load is sensed.
- **A current-mirror-referenced MOS resistor** (bias `Mrz`'s gate from a
  diode-connected replica carrying a load-proportional current, making the
  shunt conductance ratiometric and independent of threshold and mobility).
  Rejected on a hard circuit constraint: the reference device's source must
  sit at `N1` for the mirror to work, and `N1` is the amplifier's ≈ 9 MΩ
  output node — any device carrying DC current there presents `1/gm`
  (≈ 130 kΩ at 0.2 µA) and collapses `A_plat` and `a0`. Every balanced variant
  (matched legs on `ND` and `N1`, an `MLD` replica to recreate `N1`'s level, a
  compensating nfet sink) costs two or three bias branches to remove an offset
  it creates itself. Again: it would not have changed §3a.
- **Widen the shelf instead, per DR-0012.** Re-measured from the `Rz` side and
  rejected on its own terms: at `Rz` = 0.5 MΩ, taking `Cf` from 49 fF back up
  to 149 fF removes the resurgence but costs phase margin (50 mA / 0.33 µF:
  +56.1° → +26.9°) and leaves gain margin where it was (−3.6 → −2.3 dB),
  because raising `Cf` lowers `f_2` by the same factor it raises `p2`. At
  400 fF, PM falls to +11.7°.
- **Mint the `sim/loop-stability/` record anyway** and report §2's pass count.
  Rejected. It is the exact failure mode DR-0008 was ratified to prevent and
  the one issue #51's Acceptance Criterion 3 calls out by name ("a silent
  partial-pass record … is not sufficient"). A record whose PM/GM verdicts are
  inadmissible is worse than no record, because `sim/` is append-only and the
  number would outlive the caveat.

## Consequences

- **`design/` is byte-identical to `c628c15`.** No re-verification of
  `sim/psrr-dc/`, `sim/enable-shutdown/`, `sim/quiescent-current/` or
  `sim/loop-stability/` is needed or was minted, because the netlist those
  records were taken against is the netlist that is still committed. The one
  new record, `sim/amp-openloop/records/20260807-074343-225aba8.md`, is
  evidence *about the rejected circuit* and is marked FAIL; it does not
  supersede `20260802-163812-deb3dbd`, which remains the record for the
  committed design.
- **The head loop-stability record is unchanged**:
  `20260802-204343-e912fbd`, 1332/4536, worst PM −98.86° / GM −21.15 dB.
  Issue #51's Acceptance Criteria 2 and 3 are **not** met by this record and
  it does not claim otherwise.
- **DR-0012 is corrected on framing and confirmed on substance.** Its
  shelf-width equation, `Cf` floor, `Cc` PSRR ceiling and 0.1 mA closure all
  stand. What was wrong is the implicit premise that the shelf must stay put,
  and hence that the missing factor had nowhere to come from; what was right,
  and is now confirmed from an independent direction, is that the binding
  constraint is the local loop's `p2` — and this record adds the price tag.
- **`sim/loop-stability/`'s resurgence detector and
  `sim/amp-openloop/`'s `peak_excess_db` are not interchangeable** (§3a). Any
  future compensation work should read both; the loop-level detector is blind
  to a local-loop resonance that sits below the LDO loop's 0 dB crossing.
- **Runtime, recorded because it shaped this work.** On the host this was run
  on, one `sim/loop-stability/` PVT corner costs ≈ 68 minutes of wall time at
  `-j 6` (≈ 57 s per loop-gain point), against the ≈ 1.3 s per point
  `sim/loop-stability/README.md` records for the machine the earlier records
  were taken on — a ~40× discrepancy that makes the full 4536-point matrix a
  ~12-hour run rather than the ~30 minutes the README budgets. Since `sweep.py`
  writes its record only at completion, a partial run mints nothing. Whoever
  next needs a full-matrix record should budget for that or investigate the
  discrepancy (ngspice solver build is the obvious suspect); it is a real
  constraint on how many full-matrix iterations this project can afford.
