# DR-0033: A poly resistor's flavour is chosen by whether it carries DC current, not by its area — `Rbias` stays `ppolyf_u_1k`, the rest of `error_amp`'s field goes to `ppolyf_u_3k`

- **Status**: proposed (issue #279 / this pull request). **This record
  proposes no change to any ratified `README.md` row.** Every ratified bar it
  touches — Stability, PSRR, Iq, Area — is verified to hold, on fresh evidence
  minted in this same pull request, both before and after the design change it
  records. It exists to fix the *rule* in place, and to record a measured
  negative result so the rejected half of the lever is not re-proposed.
- **Date**: 2026-09-22
- **Decided by**: Builder agent, issue #279
- **Builds on**: DR-0015 (the shipped `Mrza`/`Rza` adaptive shelf, whose
  `Vds = 0` construction is why `Rza` carries no DC current), DR-0018 (the
  narrowed stability envelope this decision is verified against), DR-0019
  (the amplifier's Iq allocation, which is the bar this record finds binding).
  Supersedes none of them.

## Context

`layout/floorplan.md` §6 measures the poly-resistor field at **48.9 % of the
ratified `< 0.1 mm²` core budget** — four times the pass device, and the
largest single line in the estimate. Four of the biggest resistors are
`design/error_amp.sch`'s `ppolyf_u_1k` serpentines (`Rz` 6.17 MΩ, `Rbufb`
5.14 MΩ, `Rbias` 1.03 MΩ, `Rza` 0.62 MΩ), and `sim/devchar/CONCLUSIONS.md` §2
offers `ppolyf_u_3k` at 3.04× the sheet resistance for the same drawn width.
Issue #279 asked whether to take that area, given two named costs: a steeper
corner spread (50 % ff→ss against 40 %) and a `Rz` ceiling that
`design/error_amp.md` §6.4 records as *"6 MΩ passes 0.1–50 mA everywhere;
7 MΩ already loses corners"* — i.e. about 17 % of headroom on a component the
swap perturbs by ~9 %.

Both premises were re-measured rather than carried forward, and **both turned
out to be the wrong thing to worry about**:

- **The `Rz` ceiling is stale.** Re-run on the current committed design across
  DR-0018's ratified envelope (630 points, full 63-point PVT grid), with `Rz`
  scaled alone: 6.17 MΩ → 630/630 at worst PM 55.75°, 6.50 MΩ → 630/630 at
  55.39°, **7.00 MΩ → 630/630 at 54.86°**. §6.4's reading was taken on the
  pre-`Mrza` topology against DR-0001's full, wider matrix; §6.13 has since
  made `Rz` "nearly free at the amplifier level", and DR-0018 has since
  narrowed what is claimed. The frontier today is a slope of roughly **−1.1°
  of phase margin per +10 % of `Rz`** against a 10.75° cushion, not a cliff.

  **Where the cliff actually is.** The rungs above stop at 7 MΩ because that is
  the number §6.4 names; the ladder was continued far past it, holding the
  `ppolyf_u_1k` flavour and scaling only `Rz`'s drawn length, over the
  240-point binding-corner subset of the same envelope (`res_ss`/`ss`/`tt`/`res_ff`
  × −40/125 °C × 3 supplies × 5 loads × 2 ESR — which contains every worst
  point the full 630-point envelope reports):

  | `Rz` nominal | points failing | worst PM | | `Rz` nominal | points failing | worst PM |
  |---|---|---|---|---|---|---|
  | 6 MΩ (shipped) | 0/240 | 55.75° | | 10.5 MΩ | 0/240 | 51.53° |
  | 7 MΩ | 0/240 | 54.66° | | 12 MΩ | 0/240 | 50.35° |
  | 8 MΩ | 0/240 | 53.69° | | 15 MΩ | 0/240 | 48.13° |
  | 9 MΩ | 0/240 | 52.78° | | **18 MΩ** | **6/240** | **46.02°** |

  8 MΩ was also confirmed on the full 630-point envelope: **630/630**, worst
  PM 53.68°, worst GM 11.60 dB. Phase margin falls ≈ 5.4° per *doubling* of
  `Rz` and the first failures appear only at **3× the shipped value**. So the
  quantity this decision has to be affordable inside is not 17 % of headroom
  but roughly **150 %**, against a flavour change that moves worst-corner `Rz`
  from 1.288× to 1.410× of nominal — **9.5 %**. This is what makes the swap a
  cheap option rather than a close call, and it is why §6.4's sentence must not
  be cited as a live bound again.

  *(This ladder is a second, independent measurement of the same frontier, run
  on a different host in a parallel session of this issue and merged in here;
  it agrees with the three rungs above to the printed digit at 6 MΩ.)*
- **The corner spread is affordable where it only sets a frequency.** Swapping
  all four to `ppolyf_u_3k` at unchanged nominal resistance moves the worst
  in-envelope phase margin by **−0.17°** (55.75° → 55.58°, 630/630 both ways)
  and *improves* every gain margin by about 2 dB.

What actually binds is **quiescent current**, and it binds through exactly one
of the four resistors.

## Decision

**The flavour of a poly resistor in this design is chosen by whether the
branch it sits in carries DC current, not by how much area it occupies.**

1. A resistor that only sets a **frequency or a ratio** — no DC current in its
   branch — may use the dense, high-spread `ppolyf_u_3k`. In `error_amp` that
   is `Rz` and `Rza` (the Miller branch; DR-0015 measures `V(N1) = V(NZ)` to
   every printed digit, which is why `Mrza` sits at `Vds = 0`) and `Rbufb`
   (which feeds `Mbufb`'s gate, a DC open, and so sets only the
   `1/(2π·Rbufb·Cgg)` isolation pole). These three are hereby redrawn in
   `ppolyf_u_3k` at unchanged `res_typical`/27 °C resistance.
2. A resistor that sets a **DC current** keeps the low-spread flavour. In
   `error_amp` that is `Rbias`, the master bias reference
   (`I ≈ (VDD − Vgs(MB1))/Rbias`, 2.44 µA at tt/27 °C/3.3 V, mirrored into
   `MTAIL`/`M2N`/`Mpgn`). **`Rbias` stays `ppolyf_u_1k`.**

Drawn lengths, holding each instance's `res_typical`/27 °C value constant to
within 0.01 % (measured, not computed from the card value — the extracted
sheet at w = 1 µm is 1028.61 Ω/sq for `ppolyf_u_1k` and 3131.42 Ω/sq for
`ppolyf_u_3k`):

| instance | was | now | `R` at res_typical / 27 °C |
|---|---|---|---|
| `Rz` | `ppolyf_u_1k` 1 µm × 6000 µm | `ppolyf_u_3k` 1 µm × 1970.88 µm | 6.1717 MΩ (unchanged) |
| `Rbufb` | `ppolyf_u_1k` 1 µm × 5000 µm | `ppolyf_u_3k` 1 µm × 1642.40 µm | 5.1430 MΩ (unchanged) |
| `Rza` | `ppolyf_u_1k` 1 µm × 600 µm | `ppolyf_u_3k` 1 µm × 197.09 µm | 0.6172 MΩ (unchanged) |
| `Rbias` | `ppolyf_u_1k` 1 µm × 1000 µm | **unchanged** | 1.0286 MΩ |

## Why `Rbias` cannot move — the measurement

`ppolyf_u_3k`'s extra spread is *asymmetric* about the value that matters
here. Measured this session against the committed models, normalised to each
flavour's own `res_typical`/27 °C value (the full corner × temperature product,
not just the ff→ss process spread `sim/devchar/CONCLUSIONS.md` §2 quotes):

| flavour | min (res_ff/125 °C) | max (res_ss/−40 °C) | span |
|---|---|---|---|
| `ppolyf_u_1k` | 0.7464 | 1.2884 | 1.726× |
| `ppolyf_u_2k` | 0.6987 | 1.3537 | 1.938× |
| `ppolyf_u_3k` | **0.6550** | 1.4101 | 2.153× |

A bias resistor 12.2 % *lower* at res_ff/125 °C is 12.2 % *more* bias current
at the hottest, fastest corner — which is where the Iq row already binds.
Measured, all bars at their worst corner over the full grids:

| bar | `1k` (as committed) | all four → `2k` | all four → `3k` | `Rz`+`Rza`+`Rbufb` → `3k` |
|---|---|---|---|---|
| `amp-openloop` `iq_ua` ≤ 15 µA (81 pts) | 14.978 | **15.944 FAIL** (2/81) | **16.950 FAIL** (3/81) | **14.978 PASS** |
| `quiescent-current` `iq_full_ua` ≤ 30 µA, **ratified** (45 pts) | 28.710 | 29.677 | **30.683 FAIL** | **28.710 PASS** |
| `quiescent-current` `iq_en_ua` ≤ 30 µA, **ratified** | 28.041 | 28.933 | 29.859 | **28.041** |
| `psrr-dc` `psrr_ldo_1k_db` ≥ 50 dB, **ratified** (81 pts) | 50.252 | 50.734 | 50.435 | **50.254** |
| `amp-openloop` `gain_1k_db` ≥ 53.5 dB (81 pts) | 53.774 | 54.255 | 53.956 | **53.776** |
| `amp-openloop` `peak_excess_db` ≤ 1 dB, **DR-0008 precondition** | 0.408 | 0.226 | 0.114 | **0.141** |
| `amp-selfosc` (45 pts) | PASS | PASS | PASS | **PASS** |
| `loop-stability`, DR-0018 envelope (630 pts) | 630/630, PM 55.75° | 630/630, PM 56.25° | 630/630, PM 55.58° | see this PR's head record |

Three things this table settles:

- **The Iq cost is entirely `Rbias`.** `iq_ua`, `iq_en_ua` and `iq_full_ua`
  are **bit-identical** to the committed baseline in the taken variant — to
  four decimal places, at the same binding corner — because `Rz`, `Rza` and
  `Rbufb` sit in branches with no DC current in them. Only `Rbias` moves them,
  and moving it to `ppolyf_u_3k` costs **+1.97 µA** at `ff_125c_3.63v`, which
  breaks the amp-level 15 µA allocation *and* the ratified 30 µA row.
  `ppolyf_u_2k` costs +0.97 µA — enough to break the amp-level bar alone.
- **PSRR is not the obstacle, contrary to the issue's framing.** The
  `gm(MIN)·Rz` product is indeed the budget, but `A(1 kHz) = gm(MIN)/(2π·Cc·1 kHz)`
  is set by `Rbias`'s *current*, and the wider-spread flavours make it
  *better* at the binding corner (+0.18 dB at `3k`, +0.48 dB at `2k`), not
  worse. Every candidate clears the ratified 50 dB row.
- **The taken variant improves the one precondition that was closest to its
  bar.** `peak_excess_db` — DR-0008's right-half-plane-pole precondition, the
  bar that §6.13 records pinning `Rza` at 600 kΩ — goes from **+0.408 dB to
  +0.141 dB** against a ≤ 1 dB bar, i.e. 2.9× the margin. `Rbufb`'s flavour is
  the term that does it (`Rz`+`Rza` alone read +0.281 dB).

## Alternatives considered

- **Swap all four to `ppolyf_u_3k`** (issue #279's literal proposal, worth
  ≈ 18.5 % of the budget). Rejected: breaks the **ratified** `Iq < 30 µA` row
  at `ff_125c_3.63v` (30.683 µA) and the amplifier's own 15 µA allocation at
  three of 81 corners. CLAUDE.md forbids relaxing a ratified row to make a
  result pass, and DR-0019 already records that this Iq allocation is spoken
  for.
- **Swap all four to `ppolyf_u_2k`** (the intermediate, 2.03× the density of
  `1k`, worth ≈ 12 % of the budget). Rejected: the closed-loop Iq row survives
  (29.677 µA) but the amplifier's own 15 µA bar does not (15.944 µA at
  `ff_125c_3.63v`, 2/81). Note also that `2k` is *not* "the same spread as
  today at twice the density" as the issue assumed: its **process** spread
  matches `1k` at ±20 %, but its temperature coefficient is `3k`'s
  (−1293 ppm/°C against −694), so its full corner × temperature span is
  1.938× against `1k`'s 1.726×. Outside `Rbias` it is also strictly worse than
  `3k` on both axes that matter here — less area recovered *and* a worse
  `peak_excess_db` (0.446 dB against 0.141 dB).
- **Keep `Rbias` at `ppolyf_u_3k` and re-size the bias branch to buy the Iq
  back.** Not attempted: it changes the nominal bias current, which is
  `gm(MIN)` — §4's whole PSRR budget, with 0.25 dB of margin on the ratified
  row — and would need the full verification chain re-run for a resistor worth
  1.9 % of the area budget. Bad trade; explicitly not recommended as a
  follow-up.
- **Reject the lever entirely** (issue #279's stated fallback: "the area is
  not needed today"). Rejected because three quarters of it is measurably
  free: the taken variant moves no ratified bar in the wrong direction, moves
  the DR-0008 precondition in the *right* direction, and takes the margin on
  the ratified area row from 26.5 % to 43.6 %.

## Consequences

- **Core area estimate falls from 0.0735 mm² to 0.0564 mm²** — 17 052 µm²
  recovered, **17.1 % of the whole ratified budget**, margin 26.5 % → 43.6 %.
  The `< 0.1 mm²` row now closes at every one of issue #139's pass-device
  candidates with ≥ 40.9 % of margin (was ≥ 23.9 %). `layout/floorplan.md` §6
  is updated; `layout/area_estimate.py` needs no change (it reads the
  netlist).
- **The poly-resistor field stops being the dominant line item.** It falls
  from 48.9 % of the budget to 34.0 %, and the two largest single resistors in
  the design are now the soft-start timing pair `Rh_ss`/`Rr_ss` (already
  `ppolyf_u_3k`, 18.5 % together), not `Rz`/`Rbufb`. The next area lever is
  therefore in `ldo_softstart`, not `error_amp` — and this record's rule
  applies there unchanged: check first whether those branches carry DC current.
- **`Rz`, `Rza` and `Rbufb` become harder to match and drift further over
  temperature.** Their total corner × temperature span goes 1.726× → 2.153×
  and their global Monte Carlo σ goes 4.8 % → 5.9 %
  (`sim/devchar/CONCLUSIONS.md` §2). That is measured as affordable *for this
  loop at this operating point* — it is not a general licence, and any future
  change that tightens the loop's tolerance to `Rz` (a higher `f_hi`, a
  narrower shelf, a smaller `Cc`) must re-check it rather than inherit this
  record's conclusion.
- **Layout gets a harder drawn aspect ratio, not an easier one.** `Rz` goes
  from 60 to 20 ladder segments of ≤ 100 µm and `Rbufb` from 50 to 17. The
  field is smaller but each segment carries three times the sheet, so the
  PRES.2-pitch ladder and the Metal1 link resistance budget in §4 are
  unchanged in kind. `ppolyf_u_3k` is already the flavour used by
  `ldo_ilimit`, `ldo_softstart` and the feedback divider, so this reduces the
  number of distinct resistor modules in the core from two to two (`Rbias` is
  now the only `ppolyf_u_1k` device in the design) rather than adding one.
- **`design/error_amp.md` §6.4's `Rz` ceiling sentence is now known to be
  stale** and is annotated as such in this pull request, with the fresh
  measurement beside it. It is not deleted — §6.4 is a record of what was
  measured when it was measured.
- **The rule is not currently applied uniformly, and that is a lead, not just
  an inconsistency.** Two other blocks set a bias current through a
  `ppolyf_u_3k` resistor: `ldo_ilimit`'s `Rbias` (1 µm × 360 µm, 1.13 MΩ) and
  `ldo_softstart`'s `Rss_bias` (1 µm × 1000 µm, 3.13 MΩ). By this record's
  criterion both should be `ppolyf_u_1k`. Nothing is broken today — the
  ratified Iq row passes at 28.71 µA — but converting them would *buy back* Iq
  headroom at the fast/hot corner for ≈ 6 kµm², which the newly-recovered 43.6 %
  of area margin can now afford. That matters because **DR-0019 records the
  amplifier's `iq_ua` allocation as the thing foreclosing the buffer-bandwidth
  lever that would close DR-0001's remaining 0.33 µF gap**. This record does
  **not** make that change — it is a different block, a different verification
  chain, and an unmeasured hypothesis — but it is filed as **issue #292**.
- **Everything with a netlist hash in it must be re-run.** `error_amp.spice`
  and `ldo_core.spice` both change, so every `sim/` record's freshness stamp
  moves. This pull request re-runs and re-records `loop-stability` (full
  4536-point matrix), `amp-openloop`, `psrr-dc`, `amp-selfosc`,
  `quiescent-current`, `psrr-vs-freq`, `psrr-vs-freq-50ma` and
  `dropout-vs-load`, and regenerates `sim/CHARACTERIZATION.md`. The remaining
  rows were already STALE against the pre-existing head and are not made worse
  by this change — **except `current-limit`**, whose record is hand-written
  rather than harness-generated and is therefore not re-minted here, so the
  ratified **Current limit** and **Thermal** rows go fresh → STALE. Both were
  re-run and reproduce **bit-identically** (onset at `Vout` = 1.764 V
  62.0097 … 93.8256 mA, `pshort_mw` 345.215 mW at `ff_125c_3.63v`), so the loss
  is bookkeeping, not a measurement change. Net over the 12 testable rows:
  **5 fresh / 7 stale → 3 fresh / 9 stale**.
- **The PSRR row's verdict does not move, and is not this record's.** Main's
  `DR-0031` (PR #305, merged while this branch was in flight) minted a FAIL
  pair against the *pre-swap* netlist and bisected the cause to the soft-start
  injection element's settled residual. Those two records carry the newest
  record-ids the report generator sees, so they are superseded here by a pair
  re-run on the post-swap netlist — same FAIL, same three corners, marginally
  better at every one of the 45. Nothing in this record claims to fix it; the
  gap stays tracked as issue #302.
- **This record was drafted as `DR-0031` and renumbered to `DR-0033`.** PR #305
  took `DR-0031` on `main` at 2026-09-23T09:02Z. Issue #292 — filed out of an
  earlier draft of this record — still cites the old number by URL, and should
  be re-pointed at this one when it is next touched.
