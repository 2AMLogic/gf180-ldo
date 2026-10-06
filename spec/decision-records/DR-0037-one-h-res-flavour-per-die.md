# DR-0037: A die carries exactly one high-Rs poly flavour — this design's is `ppolyf_u_3k`, and `Rbias` moves to plain `ppolyf_u` (amends DR-0033)

- **Status**: proposed 2026-09-23 (issue #312 / this pull request).
  **Ratification is an operator decision, not an agent one**, and this record
  does not claim it. It amends DR-0033, which is itself still `proposed`, so
  nothing ratified is superseded or relaxed. No ratified `README.md` row
  changes. Every ratified bar this record moves is re-measured on fresh
  evidence in this pull request and still holds. The only thing it gives
  up is area, and that stays inside the ratified area row (§ Consequences).
- **Date**: 2026-09-23
- **Decided by**: Builder agent, issue #312 (proposal); operator (ratification,
  pending)
- **Amends**: DR-0033, Decision item 2 ("`Rbias` stays `ppolyf_u_1k`").
  DR-0033's decision *rule* stands unchanged: flavour follows DC duty. So
  do its item 1 (`Rz`/`Rza`/`Rbufb` → `ppolyf_u_3k`) and every measurement
  in it. What changes is the device that rule assigns to the one DC-current
  resistor.
- **Builds on**: DR-0018 (the stability envelope re-verified here), DR-0019
  (the amplifier's Iq allocation), DR-0031 (the PSRR row's binding term).

## Context

Issue #312 found that DR-0033's `error_amp` cannot be built. It draws `Rbias`
in `ppolyf_u_1k` beside `Rz`/`Rza`/`Rbufb` in `ppolyf_u_3k`. In gf180mcu those
are **not different drawn devices**:

- The PDK's LVS deck derives one layer for all three flavours
  (`rule_decks/res_derivations.lvs`,
  `ppolyf_u_h = poly2 & sab & res_mk & resistor`, less dnwell/dualgate/…).
  `rule_decks/res_extraction.lvs` then extracts that layer as exactly one of
  `ppolyf_u_1k`/`_2k`/`_3k`, chosen by a whole-run deck switch, `poly_res`.
- The KLayout PCell library registers one `ppolyf_u_high_Rs_resistor` and no
  per-flavour cell. The DRC deck has no flavour-dependent rule.
- The flavour is the fab's **H-Res implant option**: a property of the
  wafer, not of the polygons. On a 3 kΩ/sq wafer, DR-0033's
  1 µm × 1000 µm `Rbias` is ≈ 3.1 MΩ, not 1.03 MΩ, and the bias current it
  sets is off by 3×.

The layout-side "manufacturable as drawn" question is re-derived here. It is
not carried forward from the issue. `layout/poly_flavour/` is a
three-strip vehicle: two identical H-Res PCells plus one plain `ppolyf_u`
PCell. It is run against the PDK's own `gf180mcu.lvs`
(gf180mcuD, open_pdks `c6d73a35`, KLayout 0.30.12, `layout/drclvs.py`'s
switches):

| run | reference netlist | `poly_res` | verdict | extracted |
|---|---|---|---|---|
| a | `{3k, 3k, ppolyf_u}` | `3k` | **MATCH** | `ppolyf_u_3k` 30 kΩ ×2, `ppolyf_u` 3.5 kΩ |
| b | `{1k, 1k, ppolyf_u}` | `1k` | **MATCH** | `ppolyf_u_1k` 10 kΩ ×2, `ppolyf_u` 3.5 kΩ |
| c | `{3k, 3k, ppolyf_u}` | `1k` | mismatch | wrong wafer |
| d | `{1k, 3k, ppolyf_u}` (DR-0033's form) | `3k` | **mismatch** | |
| e | `{1k, 3k, ppolyf_u}` (DR-0033's form) | `1k` | **mismatch** | |

Rows d/e are issue #312's finding: the mixed form fails under **both**
settings. Rows a/b are the half this record rests on. Plain `ppolyf_u`
(`pplus & poly2 & sab & res_mk`, **not** interacting the `RESISTOR` mark)
extracts as `ppolyf_u` under either setting, so it coexists with whichever
H-Res flavour the wafer carries. `ldo_ilimit`'s `Rsns` has been a `ppolyf_u`
device beside `ppolyf_u_3k` since #39, so this is not a new device class for
the design.

## Decision

1. **Process option.** This design targets the **3 kΩ/sq H-Res wafer**. Every
   high-Rs poly resistor in every block is `ppolyf_u_3k`. None is
   `ppolyf_u_1k` or `ppolyf_u_2k`. Every LVS run of a cell that contains one
   uses `poly_res=3k`. Mixing flavours is not a trade-off to weigh case by
   case. It is not buildable, and must not be re-proposed.
2. **DR-0033's rule, restated for one flavour per die.** A resistor with no
   DC current (it sets only a frequency or a ratio) uses the dense
   `ppolyf_u_3k`. A resistor that **sets a DC current**, where a wider
   spread moves Iq or gm, uses a narrow-spread device on a **different drawn
   layer**: plain `ppolyf_u` (≈ 369 Ω/sq at w = 1 µm, ±20 % process,
   −28 ppm/°C). It must not use a different H-Res flavour.
3. **`Rbias` becomes `ppolyf_u`, 1 µm × 2606.6 µm**, sized to reproduce the
   old `ppolyf_u_1k` 1 µm × 1000 µm **at 125 °C** rather than at 27 °C:

   | `R` per strip | res_ff / 125 °C | res_typical / 125 °C | res_ss / 125 °C | res_typical / 27 °C | res_ss / −40 °C |
   |---|---|---|---|---|---|
   | `ppolyf_u_1k` 1 × 1000 µm (DR-0033) | 767.80 kΩ | 959.72 kΩ | 1151.64 kΩ | 1028.75 kΩ | 1325.49 kΩ |
   | `ppolyf_u` 1 × 2606.6 µm (**taken**) | 767.82 kΩ | 959.70 kΩ | 1151.58 kΩ | 961.50 kΩ | 1164.13 kΩ |
   | `ppolyf_u` 1 × 2788.93 µm (27 °C match) | 821.52 kΩ | 1026.83 kΩ | 1232.14 kΩ | 1028.75 kΩ | 1245.56 kΩ |

   (Measured per µm with ngspice-46 against the committed models, then scaled.
   The terminal resistance is < 0.01 % at these lengths.)

   The reason is where the bars bind. Iq binds at `ff_125c_3.63v`, where
   `Rbias` is lowest. PSRR and `gain_1k_db` bind at `ss_125c_2.97v`, where it is
   highest. Both are **hot**. `ppolyf_u` and `ppolyf_u_1k` share the same
   ±20 % process card, so their res_ss/res_ff ratio at 125 °C is identical
   (1.4998 against 1.4999). Once one 125 °C corner matches, all three do. The
   two flavours differ only in temperature coefficient (−28 against
   −694 ppm/°C), which moves `R` only at −40/27 °C, where nothing binds.

## Evidence — every bar the change moves

Against each bench's newest record on `main` (the DR-0033/DR-0034 design),
full PVT grid, same host and ngspice binary for the two new columns:

| bar | `main` (`ppolyf_u_1k`) | 27 °C match, **rejected** | 125 °C match, **taken** |
|---|---|---|---|
| `quiescent-current` `iq_full_ua` ≤ 30 µA, **ratified** (45 pts) | 28.7153 | 27.7829 | **28.7182** PASS |
| `quiescent-current` `iq_en_ua` ≤ 30 µA, **ratified** | 27.3882 | 26.5695 | **27.3907** PASS |
| `psrr-dc` `psrr_ldo_1k_db` ≥ 50 dB, **ratified** (81 pts) | 50.2536 | **49.7574 FAIL** | **50.2551** PASS |
| `amp-openloop` `gain_1k_db` ≥ 53.5 dB (81 pts) | 53.7755 | **53.2793 FAIL** | **53.7769** PASS |
| `amp-openloop` `iq_ua` ≤ 15 µA (DR-0019 allocation) | 14.9784 | 14.0470 | **14.9812** PASS |
| `amp-openloop` `peak_excess_db` ≤ 1 dB (DR-0008) | 0.14128 | 0.21955 | **0.14106** PASS |
| `amp-selfosc` (45 pts) | PASS | — | **PASS** |
| `loop-stability`, DR-0018 envelope (630 pts) | 630/630, 48.65° / 11.210 dB | — | **LOOPSTAB_RESULT** |

Every ratified bar lands within **0.003 dB / 0.003 µA** of the committed
design, at the same binding corner. That is the 125 °C match working as
intended, not luck. The price is paid cold, where nothing binds: at −40 °C
`Rbias` is ≈ 12 % lower than before, so the bias current is ≈ 12 % higher.
Amp `iq_ua` at `ff_-40c_3.63v` goes 6.04 → 6.84 µA against a 15 µA bar.
Closed-loop `iq_full_ua` at its coldest corner goes 8.81 → 9.60 µA. At
tt/27 °C the amplifier draws ≈ 6.6 % more (`iq_ua` 5.048 → 5.382 µA).

Records (all minted in this pull request):
`sim/quiescent-current/records/20260923-222715-d5cf9ac.md`,
`sim/psrr-dc/records/20260923-222715-d5cf9ac.md`,
`sim/amp-openloop/records/20260923-222715-d5cf9ac.md`,
`sim/amp-selfosc/records/20260923-222716-d5cf9ac.md`,
LOOPSTAB_RECORDS; the rejected 27 °C-match variant is
`sim/{quiescent-current,psrr-dc}/records/20260923-222409-d5cf9ac.md` and
`sim/amp-openloop/records/20260923-222408-d5cf9ac.md`, kept as the measured
negative result.

## Alternatives considered

1. **Revert `error_amp` to all-`ppolyf_u_1k`** (issue #312's option 1).
   Rejected, because it does not fix the die. `ldo_ilimit` (`Rref`, `Rbias`,
   `Rtail`, `Rl2`), `ldo_softstart` (`Rss_bias`, `Rh_ss`, `Rr_ss`) and the
   drawn feedback divider (PR #297, 18 units) are all `ppolyf_u_3k`. A 1k
   `error_amp` would just move the mix up a level, to `ldo_core`. Making
   the whole die 1k instead was estimated with `layout/area_estimate.py` on a
   scratch netlist, every 3k length scaled by the measured 3.044 sheet ratio.
   The core comes to **0.131 mm², 31 % over the ratified `< 0.1 mm²` row**.
   The soft-start timing pair alone would triple.
2. **All four `error_amp` resistors → `ppolyf_u_3k`** (option 2). Rejected on
   DR-0033's own measurement: `iq_full_ua` 30.683 µA breaks the ratified row
   at `ff_125c_3.63v`, and `iq_ua` 16.95 µA breaks DR-0019's allocation.
   Lengthening a 3k `Rbias` to buy the Iq back does not work either. 3k's
   res_ss/res_ff ratio at 125 °C is **1.667**, against 1k's and `ppolyf_u`'s
   1.500. Holding `R` at `ff_125c` therefore leaves it ≈ 11 % high at
   `ss_125c`. That is ≈ −0.9 dB of `psrr_ldo_1k_db`, on a ratified row with
   0.25 dB of margin.
3. **`Rbias` → `ppolyf_u` at a 27 °C match** (1 µm × 2788.93 µm, issue
   #312's option 3 as literally worded). Measured above and rejected: it
   fails the ratified PSRR row by 0.24 dB and `gain_1k_db` by 0.22 dB at
   `ss_125c_2.97v`. The flat TC removes the extra bias current that
   `ppolyf_u_1k`'s −694 ppm/°C used to supply at 125 °C.
4. **`Rbias` → `nplus_u` / `pplus_u` diffusion.** Not taken. Both carry
   ≈ +1400 ppm/°C, the wrong sign for this node: current falls hot, where PSRR
   binds. They also add a junction and its leakage to the bias node
   (`sim/devchar/CONCLUSIONS.md` §2). `ppolyf_u` matches 1k's process spread
   exactly and is already a device class in the design.
5. **Declare a process option only** (option 4, on its own). Necessary but
   not sufficient. Decision item 1 *is* that declaration, but a declaration
   alone leaves `Rbias` on the wrong wafer.

## Consequences

- **Every other schematic was re-checked** (issue #312's fourth criterion,
  `git grep -l ppolyf -- 'design/*.sch'`):

  | cell | high-Rs flavour(s) | other poly | verdict |
  |---|---|---|---|
  | `error_amp` | `3k` (`Rz`, `Rza`, `Rbufb`) | `ppolyf_u` (`Rbias`) | single — **fixed here** |
  | `ldo_ilimit` | `3k` (`Rref`, `Rbias`, `Rtail`, `Rl2`) | `ppolyf_u` (`Rsns`) | single, as committed |
  | `ldo_softstart` | `3k` (`Rss_bias`, `Rh_ss`, `Rr_ss`) | — | single, as committed |
  | `ldo_core` | none drawn. `Rtop`/`Rbot` are behavioural and inherit `error_amp` via `Xerramp` | — | single |
  | feedback divider (PR #297, `layout/divider/`) | `3k`, all 18 units + 2 dummies | — | single, no straddle |

- **Area: the resolution costs 3 522 µm², 3.5 % of the ratified budget.**
  `layout/area_estimate.py`: 57 529 → **61 051 µm²** (0.0611 mm², margin
  42.5 % → **38.9 %**) at the shipped 2.8 mm pass device. `Rbias` goes from
  1 904 to 4 966 µm² occupied and becomes the third-largest item in the core.
  DR-0033's net recovery falls from 17.1 % to ≈ 13.6 % of the budget. The
  area row still closes at every issue #139 candidate width with ≥ 37.4 % of
  margin. `layout/floorplan.md` §6 is updated.
- **Issue #292 must be re-scoped before it lands.** It proposes moving
  `ldo_ilimit`'s `Rbias` and `ldo_softstart`'s `Rss_bias` to `ppolyf_u_1k`.
  Under Decision item 1 that recreates this defect in two more blocks. Its
  hypothesis (a narrow-spread bias resistor buys back hot Iq) survives, but
  the device has to be `ppolyf_u`, and the area arithmetic changes: ≈ 2.8×
  the length of a 1k strip. A pointer comment is left on #292.
- **LVS must run every design cell at `poly_res=3k`.** `layout/drclvs.py`
  hard-codes `poly_res=1k` on `main` today, and its passives flow vehicle
  uses `ppolyf_u_1k`. PR #297 makes `poly_res` a per-cell `CellSpec` field.
  Under this record it should be one design-level constant. Both are layout
  flow changes outside this record's scope, filed as **issue #324** together
  with a CI check that rejects any netlist mixing `ppolyf_u_{1k,2k,3k}`.
- **Every `sim/` record keyed to the netlist hash goes stale again.** This
  pull request re-mints the four benches the change can move, plus
  `loop-stability`. The others were not re-run. Their verdicts are
  bias-current-at-hot claims (unchanged by construction) or were already
  stale.
- **`ppolyf_u` has no local-mismatch term either** (`mis_r = 0`,
  `sim/devchar/CONCLUSIONS.md` §2). This is not a new unknown: `Rbias` is a
  single device and sets an absolute current, not a ratio.
