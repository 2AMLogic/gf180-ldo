# DR-0010: A direct super-source-follower sense device around `Mbuf` plateaus below the PM bar and spends PSRR margin

- **Status**: proposed — a negative-result record, in the same spirit as
  DR-0008's "two levers measured against it" section. Nothing here is a
  spec change; it narrows the search space DR-0009 opened, so the next
  attempt does not repeat this exploration. **No `design/` netlist changed**
  — see "Consequences" for what that means for re-verification.
- **Date**: 2026-08-02
- **Decided by**: Builder agent, issue #53 (recommendation only)

## Context

DR-0009's Decision §2 names the next compensation increment as an
architecture change to the class-AB gate buffer, not another `Rz`/`Cc`/`Cf`
value iteration, and names the **super source follower** — local feedback
around `Mbuf` that buys `gm·ro` of output impedance for roughly one extra
bias branch — as the first candidate to try, ahead of adaptive biasing. This
record is that attempt, on `design/error_amp.sch` as committed at `0c04069`
(issue #53's Miller-split fix, PR #63).

## What was built and measured

**Variant A — direct-DC sense device.** `Msfb`, a single NMOS: gate tied
directly to `OUT`, source to `VSS`, drain to `BG` (`Mbuf`'s own gate node,
in parallel with the existing `M2N` sink). No other component changed. This
is the smallest device that can implement "sense `OUT`, pull `BG`" — the
sign is correct by inspection: `OUT` rising raises `Msfb`'s `Vgs`, pulling
`BG` down, which drives `Mbuf` to sink `OUT` harder — negative feedback
around `Mbuf` alone, not routed back through `N1`/`Rz`/`Cc`.

Because `OUT` sits at a fixed ≈1.8 V (deep strong inversion for an
`nfet_03v3` gate, `Vov` ≈ 1.0 V against `Vtn` ≈ 0.7–0.8 V), `Msfb`'s current
at a given `W/L` is **not a free choice independently of its own gm** —
`gm = 2·Id/Vov`, and `Vov` is pinned by `OUT`'s DC level, so more gm can only
be bought with more `Id`, at the same rate a plain source-follower burns it.
Sized `L=45u/W=0.22u` (long-channel, minimum width, the smallest `Id` the
`nfet_03v3` model bins reach without exceeding their `L` range) through
`L=15u/W=0.4u` (largest tried), swept against `sim/loop-stability/`'s
worst-corner triple (`ss`/−40 °C/3.63 V, 0.1 mA, 0.33 µF, 1 mΩ — the same
point DR-0009 names, `f_c` ≈ 144 kHz) and the amplifier's own Iq check
(`sim/amp-openloop/`, ≤ 15 µA):

| `Msfb` size | amp Iq, worst PVT corner (µA) | worst PM at the target point | worst GM |
|---|---|---|---|
| none (`0c04069` baseline) | 13.7 (measured, `design/error_amp.md` §6.3) | **32.37°** | 12.13 dB |
| `L=45u/W=0.22u` | ≈ 10.8 (`tt`/27 °C only; not swept to the worst PVT corner) | 35.86° | 17.62 dB |
| `L=20u/W=0.5u` | 15.92 (`ff`/125 °C/3.63 V) | 37.52° | 23.03 dB |
| `L=15u/W=0.4u` | 19.28 (`ff`/125 °C/3.63 V) | 37.55° | — |
| `L=25u/W=0.35u` (final tried) | 16.72 (`ff`/125 °C/3.63 V) | 37.09° | 21.17 dB |

**The mechanism plateaus, it does not scale.** Between the smallest and
largest devices tried, amp Iq at the worst PVT corner rose by roughly
8–9 µA — a 60–70 % increase over the 10–15 µA block allocation — for **1.7°**
of additional phase margin (35.86° → 37.55°). Gain margin has large headroom
throughout (17–23 dB against a 10 dB floor); phase margin is the binding
constraint and it does not respond to more current past roughly the
`L=20–25u` point. Combining `L=25u/W=0.35u` with a 1.5× upsize of
`Mbuf`/`Mbufb` (`Mbuf` 150→225 µm, `Mbufb` 200→300 µm, the "raw upsizing"
DR-0009 already measured as a bad exchange rate on its own) confirms the
plateau is structural rather than a property of this one device: amp Iq at
the worst corner rose to 18.7–22.0 µA and worst-case PM moved only to
37.79° — within noise of the `Msfb`-alone number, for roughly 3–5 µA more.

**On the acceptance-criteria subset directly** (`ss`,`fs` × −40 °C × 2.97/
3.30/3.63 V × 0.33 µF × {1, 50, 200, 500 mΩ} — 24 of the 48 points DR-0009's
"Consequences" section names as the cold/0.33 µF cluster), the `L=25u/W=
0.35u` variant moves 21/24 failing → 18/24 failing — a real, measured, but
partial reduction, and the closest point (`fs`/−40 °C/2.97 V) reaches 43.69°,
1.31° short of the bar. No point in the 24-point subset flips to a full
pass; DR-0001's PM ≥ 45° bar is never reached by this lever alone.

**And it is not free of cost against a bar that already had none to give.**
The 15 µA amp-level Iq check (a soft internal allocation, not itself a
ratified spec line — the ratified line is the whole-regulator < 30 µA row)
is exceeded at the single worst PVT corner from `L=20u` upward. More
seriously, the **full 81-point** `sim/amp-openloop/` grid (not just the
`tt`/27 °C and `ff`/125 °C spot checks used while sizing `Msfb`) surfaces a
regression the spot checks missed: `gain_1k_db` — the amplifier's 1 kHz gain
that budgets the ratified PSRR row (`design/error_amp.md` §4, floor
53.5 dB) — measures **53.13 dB at `ss`/125 °C/2.97 V** with `L=25u/W=0.35u`
in place, against a committed baseline that already sits at the floor with
essentially no margin (`design/error_amp.md` §4: "the margin is now
0.04 dB at the worst corner"). `Msfb`'s DC loading of `BG` (shared with
`M2N`, the existing PSRR-critical stage-2 sink) shaves the little margin
that budget had left, at a corner outside the cold/light-load cluster this
lever targets. `iq_ua` also exceeds 15 µA at 8 of 81 points (every `ff` and
`res_ff` corner across all three temperatures, not only the `ff`/125 °C
point the narrower sweep checked).

**Variant B — AC-only sense, DC-referenced off `NBIAS`.** To keep `a0_db`
(the amplifier's own low-frequency gain, which Variant A's DC path measurably
suppresses — 115 dB baseline down to 80–92 dB depending on `Msfb` size,
still clearing the 60 dB floor but a large, unexplained-at-DC swing) from
moving at all, `Msfb`'s gate was isolated from `OUT`'s DC level: gate = `GX`,
a new node biased at DC through `Rsense` (2 MΩ, `ppolyf_u_1k`) from `NBIAS`
— the same low-`Vov`, good-`gm`/`Id` bias point `Mpgn` already uses — with
`OUT`'s AC content coupled in through `Csense` (12×12 µm MIM, ≈ 300 fF,
`OUT`→`GX`), the same series-MIM idiom `Cf1`/`Cf2` already use. `Msfb`'s
drain still ties directly to `BG` (no intermediate high-impedance node, to
avoid adding a fresh pole the way a drain-side AC-coupling attempt — tried
and discarded before this one, not tabulated — did).

This **worked** at the one thing it targeted: `a0_db` held at 114–115 dB, on
top of the 113.997–115.311 dB the baseline itself measures — no detectable
DC-gain interaction. **It made phase margin far worse, not better**: at the
same worst-corner target point, PM measured **12.64°**, against the 32.37°
baseline — a 20° regression, worse than not touching the buffer at all. The
mechanism: `Rsense` ties `GX` to `NBIAS`, and `NBIAS` is not a quiet node —
it is the diode-connected gate `MB1` sets and every other bias-referenced
device in the cell (`MTAIL`, `M2N`, `Mpgn`) mirrors from. `Csense` couples
`OUT`'s own AC content onto `GX`, and `Rsense`'s finite impedance (2 MΩ, not
infinite) leaks a fraction of that signal straight back into `NBIAS` — so
`OUT`'s own motion perturbs the whole amplifier's bias network, not just
`Msfb`, an unintended feedback path this record did not set out to build and
does not recommend anyone rely on.

## Decision

**Neither variant is recommended for `design/error_amp.sch`, and neither is
committed there.** Variant A is a real but small, cost-bearing, and now
PSRR-regressing lever, not a fix; Variant B is worse than the baseline it
was meant to improve. `design/error_amp.sch` is unchanged from `0c04069`.

**For the next attempt at DR-0009's Candidate 1 (super source follower):**
the sensing device's own bias reference is the part that needs to be
right, and this record rules out the two simplest choices:

- Referencing the sense gate to `OUT` itself (Variant A) pins `Vov` at
  `OUT`'s own level (≈ 1.0 V, deep strong inversion), which fixes
  `gm`/`Id` at a mediocre point no device sizing can improve — more gm can
  only be bought at the same rate a plain follower burns current, which is
  exactly the inefficiency DR-0009 asked this candidate to avoid.
- Referencing the sense gate to `NBIAS` through a resistor (Variant B) gets
  the efficient bias point but leaks the sensed signal back into the one
  node every other bias-referenced device in the cell shares, corrupting
  the whole amplifier's dynamics rather than adding a local loop around
  `Mbuf` alone.

A working version needs a bias reference that is (a) near-threshold for good
`gm`/`Id`, like `NBIAS`, but (b) **not shared** with any other device's
small-signal path — i.e. a dedicated diode-connected reference of its own,
not a resistor tap off an existing one. That costs closer to DR-0009's
"roughly one extra bias branch" than either variant tried here, and is
untried.

**DR-0009's Candidate 2 (adaptive biasing from a pass-device sense replica)
is now the less-explored and arguably more promising remaining direction**,
since it does not route through `BG`/`NBIAS` at all and directly targets
`f_c ∝ gm_pass`, the actual mechanism DR-0009 names. It is a materially
larger circuit addition (a sense replica of the 4 mm pass device, scaled and
biased across the load range) and was not attempted in this session.

## Alternatives considered

- **Ship Variant A anyway, as partial progress.** Rejected: it converts zero
  of the 48 residual failures to a pass (closest miss 1.31°), and the
  full-grid check it was not sized against (`sim/amp-openloop/`'s 81-point
  `gain_1k_db` row) shows it spends the PSRR budget's last sliver of margin
  at a corner outside the cluster it targets. A change that adds Iq and
  area while moving no point across the bar, and puts a second ratified row
  at risk, is not net progress against issue #53's acceptance criteria.
- **Iterate Variant A with a dedicated (non-`NBIAS`) diode-connected bias
  branch**, as this record's own "Decision" section recommends for the next
  attempt. Not done here: correctly sizing and biasing a fresh reference
  branch, then re-checking the full PVT grid (not just the worst-corner spot
  checks that missed Variant A's PSRR regression), is real remaining work,
  and this record's evidence is more valuable landed now than held for a
  larger, still-uncertain follow-up in the same session.
- **Pursue Candidate 2 (adaptive biasing) directly in this session.**
  Considered and not attempted: it is architecturally a bigger addition (a
  scaled sense replica of the pass device, its own bias network across the
  load range) than the remaining session budget supports doing carefully,
  and DR-0009 itself ranks it second. Recording Candidate 1's negative
  result first is the smaller, well-bounded contribution.

## Consequences

- **No `design/` netlist changed.** `git diff origin/main -- design/` is
  empty for this record — every number above comes from `--no-write`
  exploratory sweeps against uncommitted, since-reverted schematic edits
  (the same evidentiary status DR-0008's two rejected levers have). None of
  issue #53's five named regression benches can have regressed, because
  nothing they exercise changed; they were not re-run for this reason (the
  same reasoning PR #60, DR-0008's originating PR, used).
- **Issue #53 stays open**, with the same acceptance criteria and the same
  48/540-point gap DR-0009 measured. This record narrows the *next*
  attempt's search space rather than the gap itself: candidate 1 needs an
  isolated dedicated bias branch (untried) or should be deprioritized under
  candidate 2 (adaptive biasing, also untried).
- **DR-0009's own numbers, frontier equations and recommendation ordering
  are unchanged** — this record does not supersede it, only adds evidence
  against its first-choice candidate as directly (and, in Variant A's case,
  naively) implemented.
- **The 53.5 dB `gain_1k_db` PSRR floor is confirmed to have effectively no
  slack left** (baseline: 0.04 dB at the worst corner; Variant A: a genuine
  miss at a corner the narrower sizing sweep did not check). Any future
  change touching `BG`, `M2N`, or the buffer must be checked against the
  **full** 81-point `sim/amp-openloop/` grid before judging it by a
  worst-corner spot check alone — this record's own process error, caught
  only because the full grid was eventually run.
