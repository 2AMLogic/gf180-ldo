# DR-0011: An isolated-bias-reference super-source-follower still fails — it collapses margin instead of merely plateauing

- **Status**: proposed — a negative-result record, in the same spirit as
  DR-0010's two variants. Nothing here is a spec change; it closes out the
  specific gap DR-0010 left open (a dedicated, non-shared bias reference for
  the sense device) and redirects the next attempt toward DR-0009's
  Candidate 2. **No `design/` netlist changed** — see "Consequences" for
  what that means for re-verification.
- **Date**: 2026-08-02
- **Decided by**: Builder agent, issue #53 (recommendation only)

## Context

DR-0010 tried two variants of a super-source-follower sense device around
`Mbuf` (DR-0009's Candidate 1) and rejected both: Variant A (sense gate tied
directly to `OUT`) pins the sense device's `Vov` at `OUT`'s own DC level, a
mediocre `gm`/`Id` point that plateaus; Variant B (sense gate AC-coupled from
`OUT`, DC-referenced off `NBIAS` through a resistor) gets a good `Vov` but
leaks the sensed signal back into `NBIAS`, the node every other bias-referenced
device in the cell shares. DR-0010's own "Decision" section named the fix
that neither variant tried: *"a bias reference that is (a) near-threshold for
good `gm`/`Id`, like `NBIAS`, but (b) not shared with any other device's
small-signal path — i.e. a dedicated diode-connected reference of its own."*
This record is that attempt, on `design/error_amp.sch` as committed at
`97789aa` (DR-0010's own landing commit, PR #64).

## What was built and measured

**The circuit.** Six new devices, all internal to `error_amp` (no port
change):

- `Mref` — a small diode-connected NMOS (`L=4µ/W=2µ`, gate tied to its own
  drain `SFB`), fed by `Rref` (`ppolyf_u_1k`, `6 MΩ`) from `VDD`. This is a
  self-biased reference in the same family as the cell's own `Rbias`/`MB1`
  branch, but a separate, smaller one — so its DC operating point cannot be
  perturbed by anything else in the cell, and nothing else's DC operating
  point can be perturbed by it (the isolation DR-0010 asked for).
- `Rsfg` (`ppolyf_u_1k`, `1 MΩ`) from `SFB` to a second node `SFG` — carries
  no DC current (the sense device's gate draws none), so `SFG` sits at the
  same DC level as `SFB` and `Rsfg`'s only job is setting the AC coupling
  corner together with `Csfb`.
- `Csfb` (`cap_mim_2f0fF`, 16×16 µm ≈ 533 fF) from `OUT` to `SFG` — the AC
  coupling path, same series-MIM idiom `Cf1`/`Cf2` and DR-0010's Variant B
  already use.
- `Msfb` (`L=1µ/W=4µ`), gate `SFG`, drain `BG`, source `VSS` — the sense
  device itself, in parallel with `M2N`, same connectivity DR-0010's two
  variants used.
- `Msfg_pd` (`L=0.5µ/W=4µ`), gate `ENB`, drain `SFG`, source `VSS` — a
  disable-state pulldown. Without it, `EN=0` leaves `Mref` off (`NBIAS`
  pulled to `VSS` does not touch this branch at all, since `Mref`'s own gate
  is `SFB`, not `NBIAS`) but `Rref` still pulls `SFB`/`SFG` toward `VDD`,
  turning `Msfb` on hard and fighting `Mbg_pu`'s pull-up on `BG` — a static
  contention path when disabled that is not present at `Mref`.

**First attempt (not the isolated design, a control that failed loudly).**
Before landing on the diode-connected `Mref` above, `Mref`'s gate was tied to
`NBIAS` (mirroring the main bias branch's current) with a floating drain
`SFB` pulled up by `Rref` (3 MΩ) — the same idea as DR-0010's Variant B but
one mirror stage removed from `NBIAS` instead of a direct resistor tap. This
does not work either, for a different reason than Variant B's signal leak:
`Mref` at this size conducts far less current at `NBIAS`'s voltage than
`Rref` needs to establish a near-threshold `SFB`, so `SFB` settles close to
`VDD` instead — overdriving `Msfb` (`W=20µ` in this attempt) into
**136.9–184.6 µA** of amplifier Iq (`sim/amp-openloop/`, `--no-write`,
`ss`/−40 °C only), roughly an order of magnitude over the whole regulator's
< 30 µA ratified row from one device. Diode-connecting `Mref` (self-limiting,
the same principle `Rbias`/`MB1` already relies on) and shrinking `Msfb` to
`W=4µ` fixes this specific failure — `iq_ua` measures **9.29–12.35 µA** at
`ss`/−40 °C with the isolated design in place, inside the 5.4–13.7 µA
baseline band — but the circuit below is what that fix produces, not a
description of the naive first attempt.

**The isolated design does not blow up Iq, and does not reintroduce the
local-loop instability DR-0008 fixed.** `sim/amp-openloop/`, `ss`/−40 °C,
3 points, `--no-write`:

| Measurement | Baseline (`97789aa`) | With the isolated sense device |
|---|---|---|
| `iq_ua` | 5.8–14.3 (full 81-pt grid; 9.3–12.5 restricted to this 3-pt slice, not directly comparable) | **9.29–12.35** |
| `peak_excess_db` (bar ≤ 1 dB) | −0.36…−0.13 (full grid) | **−0.664…−0.659** |
| status | — | **PASS** on all per-point checks in this restricted slice |

`peak_excess_db` staying well inside the bar means the `M2P`/`Mbuf`/`Rz`/`Cc`
local loop DR-0008 stabilized is untouched — this is not a repeat of that
defect.

**And yet it collapses the exact metric it was meant to fix, far past where
either DR-0010 variant landed.** `sim/loop-stability/`, `--no-write`, the
6-point cold/`0.33 µF` corner set (`ss`/`fs` × 2.97/3.30/3.63 V, −40 °C,
0.1 mA, 0.33 µF, 1 mΩ — the same worst-corner family DR-0009 and DR-0010 both
target):

| Corner | Baseline PM / GM (`sim/loop-stability/records/20260802-095235-c828e73.md`) | With the isolated sense device |
|---|---|---|
| `ss_-40c_3.63v` | 32.37° / 12.13 dB | **−1.13° / −0.58 dB** |
| `ss_-40c_3.30v` | 34.23° / 12.06 dB | **0.42° / 0.20 dB** |
| `ss_-40c_2.97v` | 36.47° / 11.96 dB | **2.53° / 1.16 dB** |
| `fs_-40c_3.63v` | (not in the 15-point set; measured here) | **−1.52° / −0.67 dB** |
| `fs_-40c_3.30v` | " | **0.17° / 0.07 dB** |
| `fs_-40c_2.97v` | " | **2.38° / 0.97 dB** |

Both DR-0010 variants moved this same point in one direction or the other
(Variant A: 32.37° → 37.09–37.55°, a small gain; Variant B: 32.37° → 12.64°,
a 20° loss). This record's isolated-bias variant is worse than either — three
of six points go **negative** on both bars simultaneously, i.e. the extracted
loop gain no longer has a clean 0 dB crossing with positive phase margin at
all at this corner family.

**Isolating the cause: it is `Msfb`'s connection to `BG`, not the bias
branch or the coupling capacitor.** A control run with everything else
identical but `Msfb`'s drain moved from `BG` to `VSS` (i.e. `Msfb` present,
biased, but disconnected from the signal path it was built to drive) recovers
the baseline almost exactly:

| Corner | Baseline | Isolated design, `Msfb` drain → `VSS` (control) |
|---|---|---|
| `ss_-40c_3.63v` | 32.37° / 12.13 dB | 31.88° / 11.92 dB |
| `ss_-40c_3.30v` | 34.23° / 12.06 dB | 33.69° / 11.85 dB |
| `ss_-40c_2.97v` | 36.47° / 11.96 dB | 35.88° / 11.73 dB |

The small residual shift (≈0.5° across the three points) is consistent with
`Csfb`'s ≈533 fF of added loading on `OUT` and is not the effect under test.
This rules out `Mref`/`Rref`/`Rsfg`/`Csfb` as the cause and isolates it to
`Msfb`'s presence on `BG` specifically — the same connectivity both DR-0010
variants used, now with a materially stronger local loop gain around it
(properly biased near threshold, unlike Variant A; not leaking into `NBIAS`,
unlike Variant B) and a materially worse outcome.

**The mechanism, best understood from the evidence rather than asserted.**
`peak_excess_db` says the *local* `M2P`/`Mbuf`/`Rz`/`Cc` loop (the one
`sim/amp-openloop/`'s servo'd bench and `sim/amp-selfosc/` characterize) is
still individually well-behaved. But `Msfb` opens a **second**, independent
local loop around the same node — `OUT → Csfb → SFG → Msfb → BG → Mbuf →
OUT` — with its own pole/zero pattern (`Rsfg`/`Csfb`'s high-pass corner,
`Msfb`'s own `Cgs`, the same `BG` pole `Cf1`/`Cf2` already tuned). A local
loop can be individually stable by the single-loop metrics this cell's other
benches check (`peak_excess_db`, `amp-selfosc`) while still degrading the
**enclosing** LDO loop's phase margin at its crossover, because the
`sim/loop-stability/` Tian extraction sees the composite of both local loops
plus the LDO loop, not either local loop in isolation. This is a genuinely
different failure mode from DR-0010's — DR-0010's Variant B failure was a
DC-level signal leak into a shared node; this failure survives fixing that
exact defect, so it is evidence about the *connectivity* (sensing `OUT`,
returning to `BG`, in parallel with `M2N`), not about the specific bias
scheme feeding it.

## Decision

**Not recommended for `design/error_amp.sch`, and not committed there.**
`design/error_amp.sch` is unchanged from `97789aa`.

**DR-0010's own open item — "a dedicated, non-shared bias reference for the
sense device" — is now also closed out, negatively.** Fixing exactly the
defect DR-0010 diagnosed (bias isolation) does not produce a working super
source follower; it produces a materially worse one. Between this record and
DR-0010, the super-source-follower-around-`Mbuf` family (DR-0009's
Candidate 1) has now been tried with all three bias schemes that were ever
on the table — direct `OUT` reference, shared-`NBIAS` reference, and an
isolated dedicated reference — and none of them clears the bar; two make it
worse and one plateaus short of it. **This record recommends the family be
considered exhausted rather than iterated further** (a fourth bias variant is
not an obviously different experiment from the three already run), and
**DR-0009's Candidate 2 (adaptive biasing from a pass-device sense replica)
should be the next attempt** — it does not add a second local loop around
`BG` at all, and targets `f_c ∝ gm_pass` directly, the mechanism DR-0009's
own frontier equations name.

## Alternatives considered

- **Retune `Msfb`/`Csfb`/`Rsfg` sizes within the same isolated-bias
  topology**, on the theory that this record's particular values simply
  overshot into positive-feedback-adjacent territory and a smaller `Csfb`
  or `Msfb` would land in a working middle ground. Not pursued as a next
  step: the control experiment already shows the effect is binary in kind
  (present at `BG` = large negative shift, absent = baseline), not merely a
  matter of degree that a smaller value would proportionally shrink back to
  zero and then to positive — DR-0010's Variant A (a *much* weaker,
  DC-pinned version of the same connectivity) only reached +5° of
  improvement at its largest sizing before plateauing, so the achievable
  upside within this family is small even in its best-case variant, and this
  record's worst-case shows the downside is not similarly bounded. Further
  size sweeps inside the same three-times-tried family are a worse use of
  the next session than starting Candidate 2.
- **Ship the `Msfb`-disconnected control as a real change** (i.e. just the
  isolated bias branch, wired to nothing). Rejected: it is a no-op by
  construction (confirmed by the control measurement matching baseline to
  within noise) and adds Iq, area and two new nodes for zero benefit.
- **Investigate exactly which of `Rsfg`/`Csfb`'s corner frequency or
  `Msfb`'s bias point is driving the sign of the effect**, to characterize
  the second local loop's own stability margin directly (e.g. break it at
  `SFG` and measure its own Bode response) rather than only its effect on
  the enclosing LDO loop. Worth doing if this family is revisited, but not
  done here: it would explain *why* more precisely without changing this
  record's recommendation, which does not depend on the finer mechanism.

## Consequences

- **No `design/` netlist changed.** `git diff origin/main -- design/` is
  empty for this record — every number above comes from `--no-write`
  exploratory sweeps against uncommitted, since-reverted schematic edits
  (the same evidentiary status DR-0008's two rejected levers and DR-0010's
  two variants have). None of issue #53's five named regression benches can
  have regressed, because nothing they exercise changed; the full 81-point
  `sim/amp-openloop/` grid and the full 3240-point `sim/loop-stability/`
  matrix were not re-run against this variant for the same reason DR-0010
  did not run them against its own rejected variants — a design that already
  fails the targeted worst-corner subset by a wide margin does not need the
  full grid to be ruled out.
- **Issue #53 stays open**, with the same acceptance criteria and the same
  48/540-point gap DR-0009 measured, unmoved by this record.
- **DR-0009's Decision §2 candidate ordering is amended in effect, not in
  text**: DR-0009 itself already ranked adaptive biasing (Candidate 2) below
  the super source follower (Candidate 1) only because Candidate 1 looked
  cheaper, not because it looked more likely to work. This record and
  DR-0010 together are the evidence that the cheap candidate does not work
  across every bias variant tried; DR-0009's own text is left as written
  (it correctly named both candidates and did not rule either out), and this
  record supplies the missing evidence rather than superseding it.
- **A general lesson for the next attempt, beyond this specific family**: a
  local feedback path judged individually stable by this repo's existing
  single-loop metrics (`peak_excess_db`, `amp-selfosc`) is not thereby proven
  safe for the enclosing LDO loop `sim/loop-stability/` measures. Any future
  local-loop addition around `BG`/`OUT` should be checked against
  `sim/loop-stability/`'s targeted worst-corner subset early — before, not
  after, tuning device sizes against the local-loop metrics alone — which is
  the order this record itself followed only after the first (Iq-blowup)
  attempt forced it.
