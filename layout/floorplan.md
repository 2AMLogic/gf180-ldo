# Floorplan and matching plan

Issue #15. **This is a plan, not a layout** — no GDS exists yet. Its job is to
fix the physical commitments that are expensive to revisit once drawing starts:
how the pass array is segmented and strapped, which devices have to be
common-centroid and how well, where the output is sensed, and whether the whole
block fits the ratified area budget.

Every number below is either measured evidence already committed to this repo
(cited by file), a gf180mcu design rule (cited by rule name as it appears in the
PDK's own KLayout deck, `libs.tech/klayout/drc/rule_decks/`, `gf180mcuD`), or a
stated assumption called out as one in [§8](#8-where-the-em-limits-come-from-and-what-is-still-an-assumption).
The area arithmetic is produced by
[`layout/area_estimate.py`](area_estimate.py) from the committed
`design/netlist/ldo_core.spice`, so it re-derives against the current design
rather than going stale; `layout/tests/test_area_estimate.py` turns the budget
claim into a check CI runs.

**Contents**

- [1. What this is sized against](#1-what-this-is-sized-against)
- [2. Summary of the commitments](#2-summary-of-the-commitments)
- [3. Pass-device array](#3-pass-device-array)
- [4. Matching plan](#4-matching-plan)
- [5. Kelvin sensing](#5-kelvin-sensing)
- [6. Area estimate](#6-area-estimate)
- [7. Zone plan](#7-zone-plan)
- [8. Where the EM limits come from, and what is still an assumption](#8-where-the-em-limits-come-from-and-what-is-still-an-assumption)
- [9. Design-review checklist](#9-design-review-checklist)

---

## 1. What this is sized against

| Input | Value used here | Source |
| --- | --- | --- |
| Core area budget | **< 0.1 mm² total core, pass FET included, excluding pads and sealring** | `README.md` Area row (ratified). Note this is *stricter* than #15's original framing of "excluding the pass-FET pad ring" — the pass device counts. |
| Load / thermal | 50 mA; **92 mW** continuous worst case (3.63 V in, 1.8 V out); **≤ 346 mW** into a sustained short at the 95 mA limit ceiling | `README.md` Thermal row |
| Dropout | < 300 mV, binding at ss / 125 °C / Vin = 2.10 V; measured **267.383 mV** at the shipped W = 2 mm → **32.6 mV of margin** (caveat below) | `sim/dropout-vs-load/records/20260905-202233-3093ea1.md`, the head record (same value as the `20260821-091219-4fcc251` record #139 cites) |
| Stability envelope | DR-0018's **narrowed** envelope: 0.1–50 mA, C_eff = 1 µF nominal, **ESR ≥ 200 mΩ** — not DR-0001's wider window | `README.md` Stability row; DR-0018 |
| Offset budget | Amp pair + mirror **2.33 mV (3σ) input-referred** on **360 µm²** of input-pair area; divider **3.36 mV (3σ)** output-referred; 18 mV one-sided available, used 7.40 mV | `design/error_amp.md` §3 (#9) |
| Divider mismatch is unsimulable | PDK resistor subcircuits hard-code `mis_r = 0`; the high-sheet `ppolyf_u_*k` cards carry no mismatch term at all | `sim/devchar/CONCLUSIONS.md` §2; `README.md` note 3 |
| Pass-device width | **Not final.** #139 is **open** as of 2026-09-22 with three candidates on the table: hold at 2 mm, 2.53 mm for the < 200 mV stretch, or devchar's recommended 4 mm | issue #139; `sim/devchar/CONCLUSIONS.md` §1 |
| Model binning | `pfet_03v3`/`nfet_03v3` bins are selected on **W/NF**, with W edges 0.22 / 0.5 / 1.2 / 10 / 100.001 µm and L edges 0.28 / 0.5 / 1.2 / 10 / 50.001 µm | DR-0025 (ratified 2026-09-18) |
| Vth temperature coefficient | **−1.0 mV/°C**, both polarities (−1.044 nFET, −1.078 pFET at L = 0.28 µm, typical corner) | computed from `sim/devchar/fets/results/vth.csv` |
| Divider resistor TC | **−1293 ppm/°C** (`ppolyf_u_3k`), and it cancels *only* to the extent both legs are at the same temperature | `sim/devchar/CONCLUSIONS.md` §2 |
| Metal stack | `gf180mcuD` = 5 routing layers. Thickness **0.54 µm** (Metal1–Metal4), **1.19 µm** (Metal5). Sheet resistance min / **nom** / max = 0.076 / **0.090** / 0.104 Ω/sq (M1–M4) and 0.050 / **0.060** / 0.070 Ω/sq (M5). Via1–Via4 0.0 / **4.5** / 15.0 Ω per cut. Contact 5.2 Ω (p+). | `libs.ref/gf180mcu_fd_sc_mcu{7,9}t5v0/techlef/*.tlef`; `libs.tech/magic/gf180mcuD.tech` `resist`/`contact` (agrees at nom) |
| EM current density | **DC AVERAGE 0.67 mA/µm** of drawn width (Metal1–Metal4), **1.5 mA/µm** (Metal5), **0.18 mA per cut** (Via1–Via4) — unit convention derived in §8.1, not assumed. **No limit published for the `CON` contact layer**: 129 µA/cut placeholder per DR-0030 (§8.3) | `libs.ref/*/techlef/*.tlef` `DCCURRENTDENSITY`; DR-0030 (proposed) |

**Because #139 is open, nothing here hard-codes a pass-device width.** §3 defines
the array as *N identical unit cells* and every EM, IR, thermal and area number
is given at all three candidate widths. The floorplan holds at any of them; §6
shows the area budget closes at all three.

**Caveat on the 32.6 mV dropout margin that §3.4's IR budget is carved out of.**
`sim/CHARACTERIZATION.md` marks the Dropout row **PASS / STALE**: stale because
the DUT netlist hash has moved since the record was taken (soft-start work, not
a pass-device change), and PASS *conditional on DR-0020* — the
regulation-knee measurement definition, which is `Status: proposed`, not
ratified. If DR-0020 is rejected the row reverts to FAIL on the superseded
fixed-headroom metric and there is no positive margin to spend at all. §3.4
therefore treats 32.6 mV as the **best case** and spends only 12 % of it at
nominal metal (25 % at the max-metal corner); the same 80 mΩ budget is what
this plan would ask for regardless, so the conclusion does not move with
DR-0020 — but the *stated margin ratio* does, and this document should not be
cited as independent evidence that the dropout row passes.

---

## 2. Summary of the commitments

1. **Pass array is N unit cells of `pfet_03v3 L=0.28u W=50u nf=1`**, `N = W_total / 50`.
   Re-sizing per #139 is a change to N alone — no geometry, no model bin, no
   metal-strategy change (§3.1).
2. **`Xilimit`'s `Msense` is M of the *same* unit cell**, placed inside the
   array, with M chosen so `N/M = 40`. That makes the replica ratio exact by
   construction instead of by two independently maintained W values (§3.2).
3. **Feedback divider is an 18-unit interdigitated string of 50 kΩ units drawn
   2 µm wide**, 6 up / 12 down, exact 1-D common centroid, dummy strip at each
   end. This halves the unsimulable divider-mismatch term from 3.36 mV to
   **1.68 mV (3σ)** for 1.6 % of the area budget, and it satisfies DR-0003's
   unit-string/metal-mask-option requirement (§4.1).
4. **Amp input pair keeps its 360 µm² and its `nf = 6` segmentation**, drawn
   2-D common centroid with 2 dummy fingers per row end. The `nf` is *not* a
   free layout choice: `W/nf = 10 µm` sits exactly on a model-bin edge (§4.4).
5. **Output is sensed at the VOUT pad landing**, on a dedicated `VOUT_S` net
   that carries only the divider's ~2 µA. `Xilimit`'s `Rsns` and `Rref` tie to
   the *force* net, not the sense net — they carry up to 1.25 mA (§5).
6. **Core estimate 0.0735 – 0.0761 mm²** across #139's three candidates, i.e.
   **23.9 % margin at the worst of them** (§6).
7. **Dominant area term is the poly-resistor field, not the pass device.** The
   pass array is 2.5–4.8 kµm²; the resistors are 49 kµm² (§6). This contradicts
   #139's stated premise that "the pass device is the single largest
   contributor" to the area budget, and it means #139 can pick its width on
   dropout and thermal grounds without an area veto.

---

## 3. Pass-device array

### 3.1 Unit cell and segmentation

The array is a single interdigitated finger stack built from one repeated unit:

```
unit cell U  =  pfet_03v3  L = 0.28 um  W = 50 um  nf = 1
Mpass        =  N x U in parallel      N = W_total / 50 um
```

| #139 candidate | N | stack dimension | active area | drain regions | current per drain region |
| --- | --- | --- | --- | --- | --- |
| 2.00 mm (shipped) | 40 | 32.4 µm | 1618 µm² | 20 | 2.50 mA |
| 2.53 mm (stretch) | 51 | 41.2 µm | 2058 µm² | 25 | 2.00 mA |
| 4.00 mm (devchar) | 80 | 64.4 µm | 3218 µm² | 40 | 1.25 mA |

The stack dimension is `N·(L + 0.52) + 0.36`, where 0.52 µm is a shared
contacted source/drain region (CO.7 + CO.1 + CO.7 = 0.15 + 0.22 + 0.15) and the
two outer regions are 0.44 µm (CO.7 + CO.1 + CO.4). Both exceed `DF.6_LV`'s
0.24 µm minimum COMP extension beyond the gate (the 3.3 V variant; `DF.6_MV` is
0.4 µm and does not apply), so the contacted pitch — not DF.6 — sets the stack.

**Why 50 µm per finger, and what is actually free here.** To first order the
active area is `W_total × (L + 0.52) = 0.8 × W_total` *regardless of how the
width is segmented* — halving the finger width doubles the finger count and the
number of source/drain regions stays proportional. Segmentation is therefore
close to free in area (`test_fet_area_is_nearly_independent_of_segmentation`
holds this to within 3 % over an 8× range of `nf`), and is chosen on other
grounds:

- **Upper bound, hard:** DF.2b caps COMP width at **100 µm**, and DR-0025's
  widest `pfet_03v3` model bin stops at **100.001 µm** of `W/NF`. Those two
  independent limits coincide, so 100 µm is a wall in both silicon and
  simulation.
- **Lower bound, practical:** below `W/NF = 10 µm` the device drops out of bin
  `.12` into the `W [1.2, 10)` bin — a *different model card*, which would make
  the layout's device no longer the one every `sim/` record was taken against
  (§4.4).
- **50 µm** sits mid-decade inside `[10, 100]`, keeps EM comfortable at the
  strap pitch chosen in §3.3, and is what `design/ldo_core.sch` and
  `design/ldo_ilimit.sch` already ship — so adopting it costs no schematic
  change and no re-simulation. If post-layout EM analysis against real foundry
  limits (§8) demands more headroom, the unit may be halved to `W = 50 µm,
  nf = 2` (25 µm per finger) **without leaving the bin**.

### 3.2 The current-limit replica belongs inside the array

`design/ldo_core.sch` records that `Xilimit`'s `Msense` is a 1/40 replica of
`Mpass` at equal `L` and equal per-finger width, and #139's coupling #1 is
precisely that re-sizing one without the other moves the current-limit window —
a row that is *already* FAIL in `sim/CHARACTERIZATION.md`.

**Floorplan rule: draw `Msense` as M copies of the same unit cell U, physically
inside the pass array, and set M so that `N / M = 40`.**

| #139 candidate | N | M | ratio |
| --- | --- | --- | --- |
| 2.00 mm | 40 | 1 | 40 |
| 2.53 mm | 51 | — | 51 is not divisible by 40; use N = 40 or 80 (see below) |
| 4.00 mm | 80 | 2 | 40 |

This makes the replica ratio a property of the drawn geometry rather than of two
independently edited `W=` strings. It also pushes back on 2.53 mm as a candidate:
2.53 mm is the *minimum* width for the < 200 mV stretch, not a preferred value,
and it does not give an integer replica ratio at a 50 µm unit. **4 mm (N = 80,
M = 2) is the only candidate that keeps the ratio exact at the shipped unit
size** — a layout-side argument for #139 that its own analysis does not contain.

Placement, so that `Msense` tracks:

- Put `Msense`'s M cells **symmetrically about the array centroid**, not at an
  edge — the replica must see the same temperature and the same VIN metal drop
  as the average of the array.
- `Msense`'s drain is `ISNS`, not `VOUT`, so its drain region needs its own M1
  strap and must **not** be merged into the VOUT drain comb. Give the cells
  either side of it a source region (`VIN`) so the break in the comb is
  symmetric.
- Its gate is `PASS_GATE`, common with the array — tap it from the same gate
  bus, at the same point in the bus, not from the end.
- `Men` (`W = 50 µm, nf = 2`, the enable pull-up on `PASS_GATE`) is not matched
  to anything and can sit outside the comb, but keep it in the same n-well so
  its well potential is the same VIN.

### 3.3 Metal strategy — electromigration

Current path: channel → contacts → M1 finger straps → M2 orthogonal
interdigitated straps → M3/M4/M5 interdigitated VIN/VOUT plates → bus → pad.

**The limits below are the PDK's own**, from the `DCCURRENTDENSITY AVERAGE`
entries in the standard-cell tech LEFs
(`libs.ref/gf180mcu_fd_sc_mcu{7,9}t5v0/techlef/*.tlef`) — the only place in a
`gf180mcuD` install that publishes machine-readable EM data. All six files in
this install agree. Those entries are in **mA per µm of drawn width** for the
routing layers and **mA per cut** for the cut layers — the file settles that
ambiguity against itself, and [§8.1](#81-what-the-raw-tech-lef-entries-mean)
shows the derivation. The one exception is the `CON` contact layer, which
carries no current-density entry at all; [§8.3](#83-the-contact-layer--the-one-remaining-assumption)
and DR-0030 cover it.

| Level | Geometry | Peak, W = 2 mm | Peak, W = 4 mm | Published DC limit | Margin (2 mm) |
| --- | --- | --- | --- | --- | --- |
| Drain contacts | 0.22 µm, 0.50 µm pitch (CO.1 / CO.2b), 100 per region | 25.0 µA each | 12.5 µA | **not published** — DR-0030's 129 µA placeholder, by cut-area scaling from Via1 (§8.3) | 5.2× |
| M1 finger strap | 0.44 µm wide, tapped by via1 + M2 every 5 µm | 0.284 mA/µm | 0.142 mA/µm | 0.67 mA/µm | **2.4×** |
| Via1 | 0.26 µm (V1.1), 0.52 µm pitch, ~96 per strap | 26.0 µA each | 13.0 µA | 180 µA per cut | 6.9× |
| M2 strap | 2.2 µm wide on a 5 µm D/S period, **stitched to M3 every 5 µm** | 0.178 mA/µm | 0.089 mA/µm | 0.67 mA/µm | 3.8× |
| Array exit, M3+M4+M5 | 50 µm exit edge; capacity 50 µm × (0.67 + 0.67 + 1.5) = 142 mA | 50 mA | 50 mA | — | **2.8×** |

The binding row is **M1 at 2.4×** on the shipped 2 mm device; every other level
has ≥ 2.8×, and at 4 mm the whole table doubles. Nothing here needs the device
to be re-segmented.

Two of those rows are load-bearing rather than decorative:

- **The M1 strap only works because it is tapped, not because it is wide.** A
  0.44 µm strap carrying a whole drain region's 2.5 mA end-to-end would be
  5.7 mA/µm — **8.5× over the published 0.67 mA/µm limit**. Tapping it with a
  via1 column and an M2 strap every 5 µm cuts the peak to 0.284 mA/µm.
  **Via1 must be a full column along every source and drain strap, not a via
  per strap.**
- **The M2 strap only works because M3 is stitched to it.** Without an M3
  plate, each M2 strap has to carry its whole 5 mA slice to the array edge:
  1.14 mA/µm, **1.7× over the limit — a fail, not a thin margin**. With M3
  stitched at a 5 µm pitch the peak falls to 0.178 mA/µm. **M3 over the array
  is not optional.**

M2/M3/M4/M5 alternate VIN and VOUT with ≥ 40 % coverage each; M2.2b / M3.2b /
M4.2b / M5.2b require 0.3 µm (not 0.28 µm) of space once a shape exceeds 10 µm
in both directions, which every one of these plates does.

### 3.4 Metal strategy — IR drop, and why it is a dropout budget

Series metal resistance between the VIN pad and the pass source, and between the
pass drain and the Kelvin tap, adds **directly** to dropout at 50 mA. The
binding case is the shipped 2 mm device, which has 32.6 mV of dropout margin.

The tech LEFs give this a corner spread the magic tech file's single value
hides: M1–M4 sheet is **0.076 / 0.090 / 0.104 Ω/sq** and a via cut is
**0.0 / 4.5 / 15.0 Ω** across the min / nom / max views. A max-corner via is
**3.3×** a nominal one, so the budget is stated at both corners:

- **Nominal metal: ≤ 80 mΩ total = 4.0 mV at 50 mA** — 12 % of the 2 mm
  dropout margin. Split 40 mΩ per side.
- **Max-corner metal: ≤ 160 mΩ total = 8.0 mV** — 25 % of the 2 mm margin.
  This is the joint worst case of an ss / 125 °C *device* corner (where the
  267.4 mV was measured) with max-corner *metal*, which are independent axes.

| Term, one side | W = 2 mm, nom | W = 2 mm, max | W = 4 mm, nom | W = 4 mm, max |
| --- | --- | --- | --- | --- |
| Drain contacts (2000 / 4000 at 5.2 Ω) | 2.60 mΩ | 2.60 mΩ | 1.30 mΩ | 1.30 mΩ |
| Via1 column (1920 / 3840 cuts) | 2.34 mΩ | 7.81 mΩ | 1.17 mΩ | 3.91 mΩ |
| Via2–Via4 seas at 0.52 µm pitch (2958 / 5917 cuts per level) | 4.56 mΩ | 15.21 mΩ | 2.28 mΩ | 7.61 mΩ |
| M1/M2/M3 distributed, tapped as in §3.3 | 2.00 mΩ | 2.31 mΩ | 2.00 mΩ | 2.31 mΩ |
| **Array subtotal** | **11.5 mΩ** | **27.9 mΩ** | **6.8 mΩ** | **15.1 mΩ** |
| **Remaining for the bus run** | **28.5 mΩ** | **52.1 mΩ** | **33.2 mΩ** | **64.9 mΩ** |

The bus is the term that drives the floorplan, because it is the only one that
scales with *distance*:

> **M4 ‖ M5 = 36.0 mΩ per square nominal (41.8 mΩ max) = 1.80 mV (2.09 mV) of
> dropout per square at 50 mA.** The remaining allowance buys **0.79 squares**
> at the shipped 2 mm device (0.92 at 4 mm) — and the *nominal* corner binds,
> not the max one, because the max-corner budget doubles faster than the
> max-corner resistance rises. Design rule: **≤ 0.75 squares of M4 ‖ M5 per
> side.** A 60 µm-wide bus may therefore run **~45 µm**, a 100 µm-wide bus
> **~75 µm**.

Note the via seas, not the metal, are the array's dominant internal term at the
max corner (15.2 of 27.9 mΩ at 2 mm). They are already at maximum density —
V1.2a's 0.26 µm cut spacing puts the sea at a 0.52 µm pitch and there is no
further lever except array area, which is why widening the pass device per #139
halves this term for free.

That is the reason §7 puts the pass array hard against the pad edge with nothing
between it and the VIN/VOUT landings. It is not a preference: a pass array
placed 200 µm inboard on a 60 µm-wide bus is 3.33 squares per side, 240 mΩ,
**12 mV of dropout — more than a third of the 2 mm margin — spent on metal.**

**The amplifier's VDD is VIN.** Tap it *upstream* of the array's VIN bus drop,
at the pad, so the amp's supply does not move with load current. The cost of
getting this wrong is small (2 mV of supply movement against ≥ 50 dB of PSRR is
~6 µV at the output), so it is a preference rather than a constraint — but it is
free to get right.

**VSS carries no load current in this topology.** The pass device is a PMOS from
VIN to VOUT; the load return is external. On-chip VSS carries only Iq (< 30 µA)
plus the current-limit and soft-start branches, so ground IR drop is not a
regulation-accuracy term here and the only Kelvin requirement is on VOUT (§5).
A star connection for the analog reference returns is still worth drawing, for
transient coupling rather than for DC.

### 3.5 Thermal spreading

On-die spreading resistance for the array treated as an isothermal source of
equivalent radius `a` on a silicon half-space, `R = 1/(4·k·a)` with
`k ≈ 100 W/(m·K)` at 125 °C:

| #139 candidate | active area | a_eq | R_spread | ΔT at 92 mW | ΔT at 346 mW (sustained short) |
| --- | --- | --- | --- | --- | --- |
| 2.00 mm | 1618 µm² | 22.7 µm | 110.2 K/W | **10.1 K** | **38.0 K** |
| 2.53 mm | 2058 µm² | 25.6 µm | 97.7 K/W | 8.9 K | 33.7 K |
| 4.00 mm | 3218 µm² | 32.0 µm | 78.1 K/W | **7.1 K** | **26.9 K** |

Consequences:

- **At continuous rating the array is fine**: 7–10 K of local rise above the
  die. Keep it as **one block** rather than splitting it — splitting buys a few
  kelvin and costs the short bus run §3.4 depends on.
- **Under a sustained short the on-die spreading term alone is 27–38 K**, on top
  of whatever θJA the package contributes. `README.md`'s Thermal row delegates
  θJA and sustained-short survivability to the package/integration spec; this
  is the on-die half of that number, and it is a further (secondary) argument
  for #139 widening the device — 4 mm removes 11 K of it.
- **The array is a heat source that every matched pair in the block sits in.**
  That is the subject of §4.

---

## 4. Matching plan

The pass array's far field is `ΔT(r) = P / (2πkr)` = **145.6 K·µm / r** at
continuous rating (P = 1.83 V × 50 mA = 91.5 mW exactly, which `README.md`'s
Thermal row quotes rounded to 92 mW; k = 100 W/(m·K), §8). That is the gradient
every matched device has to survive:

| distance from array centroid | ΔT | pair mis-tracking if **not** common-centroid (halves 30 µm apart) | residual **with** common centroid (unit pitch 10 µm) |
| --- | --- | --- | --- |
| 60 µm | 2.43 K | 1.294 K → **1.29 mV** of input offset | 0.290 K → 0.29 mV |
| 100 µm | 1.46 K | 0.447 K → 0.45 mV | 0.060 K → 0.06 mV |
| 150 µm | 0.97 K | 0.196 K → 0.20 mV | 0.018 K → **0.02 mV** |
| 200 µm | 0.73 K | 0.117 K → 0.12 mV | 0.007 K → 0.01 mV |

(at −1.0 mV/°C of Vth tempco, measured; the "not common-centroid" column is the
first difference of the field across the pair, the "with" column is the second
difference an ABBA arrangement leaves behind.)

**Read the 60 µm row.** A non-common-centroid input pair placed next to the pass
array picks up **1.29 mV of deterministic offset** — more than half of #9's
entire 2.33 mV *3σ statistical* allocation, and it would add linearly to the
deterministic terms rather than in RSS. Common-centroid layout is not a
best-practice gesture here; it is the difference between the offset budget
closing and not.

**Therefore, two requirements, both needed:** every matched pair is
common-centroid **and** its centroid sits **≥ 150 µm** from the pass-array
centroid. That combination lands at ≈ 0.02 mV of gradient-induced offset, which
is negligible against the 0.61 mV measured systematic term. Common centroid
alone at 60 µm (0.29 mV) is not good enough; distance alone at 150 µm (0.20 mV)
is not good enough either.

### 4.1 Feedback divider — the term simulation cannot see

`sim/devchar/CONCLUSIONS.md` §2 is unambiguous: a matched resistor pair returns
**bit-identical** values over 200 Monte Carlo runs at every area and temperature,
because the subcircuits hard-code `mis_r = 0` and the high-sheet `ppolyf_u_*k`
cards carry no mismatch term at all. `#13`'s Monte Carlo cannot verify this row
and a "pass" from it is not evidence. **Layout discipline is the only mitigation
this project has for divider mismatch.** That is what this section spends area
on.

The divider is also constrained by two other ratified decisions: DR-0001 makes
the divider's **~2 µA the only inherent preload** (so its 900 kΩ total must not
move), and DR-0003's Output row requires it to be drawn as **"a unit-resistor
string for metal-mask-option derivatives"** — a string of identical units with
the tap made on a single metal mask.

**Plan:**

```
unit           50 kOhm  ppolyf_u_3k,  w = 2 um,  l = 31.8 um   (63.6 um^2 of body)
string         18 units in series  =  900 kOhm   (unchanged)
tap            after 12 units from VSS   ->  Rbot = 600k, Rtop = 300k
arrangement    one row of 20 strips at 2.4 um pitch (PRES.2 = 0.4 um space)
               positions 1..18 active, B T B B T B B T B B T B B T B B T B
               plus one dummy strip at each end
```

- **Exact common centroid, verified arithmetically.** With the top-leg units at
  positions {2, 5, 8, 11, 14, 17}, the top-leg centroid is 9.5 and the
  bottom-leg centroid is 9.5 — the middle of a 1..18 row.
  `test_unit_count_admits_an_exact_common_centroid` re-checks it.
  One-dimensional common centroid is sufficient *here* because every strip is
  the same length and aligned, so there is no top-leg/bottom-leg separation in
  the orthogonal direction to cancel.
- **Drawn 2 µm wide, not the 1 µm #9's budget assumed.** Area per unit goes
  4× and the mismatch term halves:

  ```
  sigma(unit)/R = 0.7071 * 0.021 / sqrt(63.6)  = 0.186 %      (par_r proxy, as #9 sanctions)
  sigma(Rtop)   = 0.186 % / sqrt(6)            = 0.0760 %
  sigma(Rbot)   = 0.186 % / sqrt(12)           = 0.0538 %
  dVout/Vout    = (1/3) * sqrt(.0760^2+.0538^2) = 0.0310 % (1 sigma)
                                                = 1.68 mV (3 sigma) at 1.8 V
  ```

  That is **half** #9's budgeted 3.36 mV, and it takes the statistical RSS from
  4.84 mV to 3.87 mV and the total static error from 7.40 mV to 6.43 mV against
  18 mV — margin 2.4× → 2.8×. The cost is **~1.6 % of the area budget**. Buying
  2× on a term that *cannot be measured in simulation and whose coefficient is
  an admitted proxy* is the best use of 1.6 % of the budget
  available in this block. (Footprint 1622 µm²; net cost over a 1 µm-wide
  string with no dummies is +1618 µm² of occupied area.)
- **Escape hatch, if layout runs tight**: draw at 1.5 µm (2.23 mV, 3σ) or fall
  back to 1 µm (3.36 mV, #9's assumed value). The budget closes at all three;
  this is margin, not necessity. Do **not** reach for the low-sheet `ppolyf_u`
  flavour instead — `sim/devchar/CONCLUSIONS.md` §2 prices that at 8.5× the area.
- **Heads are the same width as the body.** A contact on poly needs only
  0.07 µm of poly enclosure (CO.3), so a 2 µm strip needs no dogbone; the ladder
  pitch is set by PRES.2 alone (0.4 µm) and the strip stays a clean rectangle.
- **Link the units in metal, not in poly.** A poly bend is a non-uniform-current
  region and a matching hazard; the 18 units are 18 straight rectangles joined
  on M1.
- **Own guard ring**, own n-well/substrate tap ring, and a routing keep-out over
  the string in M1 (the string's own links live there). Nothing that switches —
  `PASS_GATE`, `EN`, `ENB` — may cross over it.
- **Thermal**: centroid ≥ 150 µm from the pass array (§4, and §7 places it).
  At 150 µm the residual ratio error is 254 ppm → 0.15 mV if the interdigitation
  were absent; with it, ~0.02 mV.
- The tap between unit 12 and unit 13 is the metal-mask option DR-0003 asks
  for: re-tapping it is a single-layer change.

### 4.2 Error-amp input pair and mirror load

From `design/error_amp.md` §3.1, both areas are already *design levers chosen
for the budget*, and #9 explicitly hands this issue the requirement: "**360 µm²
of input-pair area, common-centroid with dummies, as the budgeted requirement**".

| Device | Netlist geometry | Area | Contribution to σ(Vos) |
| --- | --- | --- | --- |
| `MIN1`/`MIN2` (input pair) | `nfet_03v3 W=60u L=6u nf=6` → 10 µm/finger | 360 µm² each | 0.626 mV (1σ) |
| `MLD1`/`MLD2` (mirror load) | `pfet_03v3 W=8u L=8u nf=1` | 64 µm² each | 1.485 mV, referred in at ×0.308 → 0.458 mV |
| | | | **σ(Vos) = 0.776 mV → 2.33 mV (3σ)** |

**Input pair.** 12 signal fingers (6 + 6), two rows of 6, 2-D common centroid:

```
row 1:   d  d   A  B  B  A  A  B   d  d
row 2:   d  d   B  A  A  B  B  A   d  d
```

**Neither row is centroid-balanced on its own, and cannot be**: three fingers of
each in a row of six would need a position sum of 10.5, which is not an integer.
The two rows are *complements* instead, so the quad's A-centroid and B-centroid
both land at column 3.5, row 1.5 — matched in both axes. (A occupies columns
{1,4,5} in row 1 and {2,3,6} in row 2; both legs sum to 21 over 6 fingers.)
Two dummy fingers `d` per row end (4 per row, 8 total) give every signal finger
an identical lateral etch neighbour; dummy gates tie to VSS and their
source/drains tie to the local `TAIL` node so they are off and see the pair's
own environment.
One guard ring around the whole quad; `INP`/`INN` enter from the same side,
symmetrically, with equal M1 run lengths.

**Mirror load.** Split each of `MLD1`/`MLD2` into two half-width units
(`W = 8 µm, nf = 2` drawn, i.e. 4 µm per finger) and cross-couple ABBA in a
2 × 2. `W/nf` moves from 8 µm to 4 µm, which stays inside the same
`W [1.2, 10)` bin — checked, because that is exactly the trap §4.4 describes.
Shared n-well tied to VDD, well tap ring inside the guard ring, 2 dummy fingers
flanking.

**Orientation.** All matched devices in the same orientation, gates parallel,
same current direction. The pair's axis should run **perpendicular to the
dominant gradient direction** (i.e. parallel to the pass array's long edge) so
that what the common centroid has to cancel is second-order in the first place.

### 4.3 The other pairs that matter

| Pair | Why it matters | Requirement |
| --- | --- | --- |
| `MB1` / `MTAIL` (`nfet` 6 µm/4 µm vs 6.6 µm/4 µm) | sets the amplifier's tail current, hence `gm(MIN)` — which §4 of `error_amp.md` shows *is* the PSRR budget | interdigitated ABBA, shared dummy row, same orientation; do not re-segment (§4.4) |
| `Mpd` / `Mrefp` (`pfet` 10 µm/2 µm, `ldo_ilimit`) | the current-limit threshold reference pair | cross-quad with dummies; same n-well as each other, **not** shared with the pass array's well |
| `Mna` / `Mnb`, `Mca` / `Mcb` (`ldo_ilimit` comparator) | current-limit window (62–95 mA, a wide spec) | ABBA interdigitation is sufficient; no dummy ring needed |
| `Mgma_ss` / `Mgmb_ss` (soft-start injection transconductor) | DR-0023 / DR-0026 territory — injection accuracy | ABBA with dummies; keep out of the pass array's gradient (≥ 150 µm) like the amp pair |
| `Msense` / `Mpass` | §3.2 | same unit cell, inside the array |

### 4.4 The model-bin trap: re-segmentation is not a free layout choice

DR-0025 (ratified 2026-09-18) establishes that gf180mcu's `pfet_03v3` /
`nfet_03v3` cards are **binned on `W/NF`**, with W edges at
0.22 / 0.5 / 1.2 / 10 / 100.001 µm. A layout engineer re-segmenting a device —
the single most natural thing to do when fitting a pair into a common-centroid
array — can move `W/NF` across a bin edge and silently substitute a *different
model card* for the one every committed `sim/` record was taken against.

**Rule: any layout-time change to `nf` must keep `W/nf` inside the same bin
interval. If it cannot, the change belongs in `design/*.sch` and the affected
testbenches must be re-run — it is not a layout-only edit.**

Checked for every device this plan re-segments or is tempted to:

| Device | `W/nf` as drawn | Bin | Re-segmentation verdict |
| --- | --- | --- | --- |
| `Mpass` | 50 µm | `[10, 100.001]` | free to move anywhere in 10–100 µm; 25 µm and 100 µm both stay in bin |
| `Msense` | 50 µm | `[10, 100.001]` | same — M unit cells of 50 µm each is safe |
| `MIN1`/`MIN2` | **10 µm — exactly on the edge** | `[10, 100.001]` (edges are lower-inclusive) | **do not re-segment.** `nf = 12` gives 5 µm and drops into `[1.2, 10)`, a different card |
| `MLD1`/`MLD2` | 8 µm | `[1.2, 10)` | splitting to `nf = 2` (4 µm) stays in bin — safe, and this plan does it |
| `MB1` / `MTAIL` | 6 / 6.6 µm | `[1.2, 10)` | splitting to `nf = 2` (3 / 3.3 µm) stays in bin |
| `Mclamp`, `Men` | 50 / 25 µm | `[10, 100.001]` | not matched; free |

---

## 5. Kelvin sensing

The regulation loop must sense the output where the load sees it, not where the
pass device delivers it. Concretely, two separate nets that meet at exactly one
point:

```
  VOUT_F  (force)   pass drain comb -> M3/M4/M5 plates -> wide bus -> VOUT pad
  VOUT_S  (sense)   VOUT pad landing -> thin dedicated route -> divider top,
                                                             -> Cff bottom plate
  Kelvin tap        the VOUT pad landing, where the external 1 uF and the load
                    connect.  This is the ONLY place VOUT_S touches VOUT_F.
```

**Everything that belongs on each net, explicitly** — this is where a Kelvin
scheme is usually got wrong, by connecting something with real current to the
sense net:

| Net | Connects | Current it carries |
| --- | --- | --- |
| `VOUT_S` | divider top (`Rtop`'s free end), `Cff`'s VOUT plate | ~2 µA DC + a few µA of `Cff` transient |
| `VOUT_F` | `Mpass` drain comb, `Xilimit`'s **`Rsns`**, `Xilimit`'s **`Rref`**, the output pad | up to 50 mA, plus `Rsns`'s **1.25 mA** at full load |

- **`Rsns` must not touch the sense net.** `Xilimit` sources `Msense`'s replica
  current from VIN through `Rsns` into VOUT — **1.25 mA at a 50 mA load**, 1/40
  of the load. Landing that on `VOUT_S` would inject 625× the divider's own
  current into the sense line and corrupt regulation directly.
- **`Rref` goes to the force net too, at the same point as `Rsns`.** The
  current-limit comparator compares `VTH` (= VOUT + a `Rref` drop) against
  `ISNS` (= VOUT + a `Rsns` drop). Referencing both to the *same* node makes
  any IR drop at that node common-mode and cancels it out of the comparison;
  referencing one to the force net and the other to the sense net would inject
  the full power-path drop straight into the current-limit threshold.
- **`Cff`'s plate assignment is load-bearing.** The MIM's large Metal2 bottom
  plate shields whatever is beneath it. Put **`VOUT_S` (the low-impedance side)
  on the bottom plate** and `FB` (the high-impedance sense node) on the top
  plate, so the capacitor shields `FB` from the resistor field §7 places under
  it rather than exposing it.

**Sense-route sizing.** `VOUT_S` carries the divider's 1.8 V / 900 kΩ = **2.0 µA**.
Drawn ≥ 1 µm wide on M2, a 200 µm run is 18 Ω → **0.036 mV** of error. Budget:
**≤ 50 Ω end to end (≤ 0.1 mV)**. Route it:

- on a **different layer and a different track** from the M3/M4/M5 power
  plates, never underneath or between them;
- with a grounded M1 (or M3) shield strip alongside where it passes the pass
  gate bus or the enable net — `PASS_GATE` swings the full supply during
  startup and a load transient;
- as a single trunk from the pad landing, not a tee off the power comb.

**`FB` is the other sensitive node** and gets the same treatment: the divider
tap → amp `INP` route is short, shielded, and does not cross `PASS_GATE`, `EN`,
`ENB`, or either power plate. `Xsoftstart` also injects onto `FB`
(`Mgmc_ss`) — that injection point should be adjacent to the divider tap so the
two share a node rather than a route.

---

## 6. Area estimate

Against `README.md`'s ratified row: **< 0.1 mm² total core, pass FET included,
excluding pads and sealring**.

Produced by `python3 layout/area_estimate.py` from
`design/netlist/ldo_core.spice`. The model is: drawn device footprint (COMP for
FETs from the contacted-pitch geometry, ladder field for poly resistors at
PRES.2 pitch, plate + MIM.1 keep-out for MIMs), then a packing efficiency per
device kind for guard rings / dummies / local routing, then a credit for MIM
plates stacked over resistor fields, then a 15 % allowance for inter-block
channels and the core ring.

```
block                  FET       res       MIM   footprint
----------------------------------------------------------
divider                  0      1622      7992        9615
error_amp             1530     17993      2717       22240
ldo_ilimit             401      1510       614        2524
ldo_softstart          197     15522      3273       18993
pass_array            1725         0         0        1725
----------------------------------------------------------
device footprint                                     55097

kind               footprint   packing    occupied
--------------------------------------------------
fet_small               2129      0.35        6082
fet_pass                1725      0.70        2464
res                    36647      0.75       48863
mim                    14596      0.90       16218
--------------------------------------------------
occupied                                     73626
MIM stacked                                  -9731  (60% of MIM)
subtotal                                     63896
routing x1.15                                 9584
==================================================
CORE ESTIMATE                                73480  um^2 = 0.0735 mm^2
                                              73.5  % of the 0.1 mm^2 budget
                                              26.5  % margin
```

**Across #139's three candidates** (`--pass-width 2000 | 2530 | 4000`):

| pass-device width | pass array occupied | core estimate | margin |
| --- | --- | --- | --- |
| 2.00 mm (shipped) | 2 464 µm² | **0.0735 mm²** | **26.5 %** |
| 2.53 mm (stretch) | 3 070 µm² | **0.0742 mm²** | **25.8 %** |
| 4.00 mm (devchar) | 4 750 µm² | **0.0761 mm²** | **23.9 %** |

**The budget closes at every candidate.** Doubling the pass device from 2 mm to
4 mm costs **2 286 µm², 2.3 % of the area budget** — it moves the margin from
26.5 % to 23.9 %. `test_estimate_fits_the_budget_at_every_issue_139_candidate`
keeps this true as the design changes.

### What actually consumes the area

| Rank | Item | Occupied | Share of the budget |
| --- | --- | --- | --- |
| 1 | `Rz` — the 6 MΩ `ppolyf_u_1k` compensation serpentine | 11 424 µm² | 11.4 % |
| 2 | `Rbufb` — 5 MΩ buffer-bias serpentine | 9 520 µm² | 9.5 % |
| 3 | `Rh_ss`, `Rr_ss` — 4870-square `ppolyf_u_3k` soft-start timing resistors (×2, ~15 MΩ each) | 9 274 µm² each | 18.5 % together |
| 4 | `Cff` — 15.1 pF, 87 × 87 µm MIM | 8 880 µm² | 8.9 % |
| 5 | `Cc` (amp) — 4.6 pF MIM | 2 822 µm² | 2.8 % |
| … | **`Mpass` at 4 mm** | **4 598 µm²** | **4.6 %** |

**This contradicts #139's premise.** #139's coupling #3 states that "the pass
device is the single largest contributor" to the `< 0.1 mm²` budget. It is not:
at the *widest* candidate it is 4.6 % of the budget and sixth on the list. The
poly-resistor field is **49 % of the budget** and the MIM capacitors are another
**16 %**. #139 should pick its width on dropout, current-limit-replica and
thermal grounds; the area coupling it lists is real but an order of magnitude
smaller than it assumes. *(Filed back to #139 as a comment; see §10.)*

Two consequences for whoever draws this:

- **MIM stacking is worth real money.** MIM option A puts the plates on
  Metal2/Metal3 and connects them through Via2 only (MIM.10), so poly and
  diffusion beneath a plate are free. Stacking 60 % of the MIM area over the
  resistor field recovers **9 731 µm² — 9.7 % of the whole budget**. The
  conditions are in §7. `Cff` at 7 569 µm² of plate is also close to MIM.8b's
  10 000 µm² single-plate ceiling; `test_no_single_mim_plate_exceeds_mim8b`
  watches that edge.
- **The resistor flavours are the only large area lever left**, and pulling it
  is a *schematic* change with a stability cost, not a layout choice. Redrawing
  `Rz`/`Rbufb`/`Rza`/`Rbias` in `ppolyf_u_3k` instead of `ppolyf_u_1k` is a
  3.04× sheet-resistance gain on 23 990 µm² of occupied area — **~16 kµm², 16 %
  of the whole budget** — but `error_amp.md` §"`Rz` and `Cc` are pinned" records
  that the measured frontier is steep (6 MΩ passes, 7 MΩ does not) and
  `ppolyf_u_3k` has a **50 % corner spread against `ppolyf_u_1k`'s 40 %**. That
  trade needs a loop-stability re-run, so it is filed rather than taken (§10).

### Caveats on this estimate

- It is a **pre-layout model**, not an extraction. The packing factors (0.35
  small-signal FET, 0.70 pass array, 0.75 resistor field, 0.90 MIM) and the
  1.15 routing allowance are engineering judgement; they are named constants at
  the top of `area_estimate.py` so a reviewer can disagree with a specific
  number rather than with the total.
- `Rtop`/`Rbot` and the soft-start's `Rgma_ss`/`Rgmb_ss` are still **ideal
  resistors** in `design/netlist/`. They must become real devices at layout and
  are budgeted here as such (`Rtop`/`Rbot` via §4.1's planned array, the
  soft-start pair as `ppolyf_u_3k` at 1 µm).
- The estimate excludes pads, the sealring, and any ESD structure, per the
  ratified row's own exclusions.

---

## 7. Zone plan

Core rectangle: **300 µm × 250 µm = 75 000 µm² (0.075 mm²)**, which covers the
worst #139 candidate (76 108 µm² — see the note below) and sits 25 % under the
budget. VIN and VOUT pads on the south edge.

```
             <------------------------ 300 um ------------------------>
      +----------------------------------------------------------------+
      |  A: error-amp small-signal core     |  D: feedback divider      |
  55  |     MIN pair (2x6 + 8 dummies),     |     18 x 50k units,       |
  um  |     MLD cross-quad, MB1/MTAIL,      |     1 dummy each end,     |
      |     buffer, CC network              |     own guard ring        |
      +-------------------------------------+---------------------------+
      |                                                                |
      |  R: poly-resistor field  --  Rz, Rbufb, Rza, Rbias, Rh_ss,     |
 140  |     Rr_ss, Rss_bias, Rtail, Rl2, Rref, Rsns, Rgm*_ss           |
  um  |     MIM plates (Cff, Cc x2, Css, Ch_ss, Cr_ss) stacked         |
      |     ABOVE this field on Metal2/Metal3                          |
      |                          +---------------+--------------------+|
      |                          | I: ilimit     | S: soft-start      ||
      |                          |    comparator |    small-signal    ||
      +----------------------------------------------------------------+
  55  |  P: pass array (N unit cells + Msense + Men)                   |
  um  |     M3/M4/M5 VIN/VOUT plates; wide M4+M5 bus to the pads       |
      +----------------------------------------------------------------+
            ^ VIN pad                                    ^ VOUT pad
                                                           = Kelvin tap
```

Why the zones sit where they do:

| Zone | Placement rule | Driven by |
| --- | --- | --- |
| **P** — pass array | Hard against the pad edge, nothing between it and the VIN/VOUT landings; long axis parallel to the pad edge so the 50 µm exit edge faces the bus | §3.4 — 1.80 mV of dropout per square of M4‖M5 bus |
| **A** — amp core | Opposite edge from P. Centroid ~195 µm from P's centroid, comfortably past the 150 µm rule | §4's gradient table |
| **D** — divider | Beside A, also ≥ 150 µm from P; short `FB` route to A's `INP`; `VOUT_S` arrives as its own trunk from the south-east corner | §4.1, §5 |
| **R** — resistor field | The middle band, because it is 49 % of the area, is thermally insensitive (both legs of any ratio are inside it), and is the only block big enough to host the MIM plates above it | §6 |
| **I**, **S** | Tucked into the resistor field's lower corners, near the nets they serve (`I` near the pass array for `Msense`/`ISNS`; `S` near `FB`) | routing length |
| MIM plates | On M2/M3 over **R**, never over **A**, **D**, or the `VOUT_S`/`FB` routes | MIM.10 + the shielding rule below |

**Conditions on stacking MIM over the resistor field** (all four, or do not
stack):

1. The resistor beneath exits in **Metal1 only**, at the plate edge — MIM.10
   forbids a Via1 touching the bottom plate's Metal2.
2. The capacitor's **low-impedance node is on the bottom plate**, so the plate
   shields the resistor field rather than coupling to it (`cap_mim_2f0_*_noshield`
   has no separate shield).
3. MIM.1's **1.2 µm** bottom-plate-to-other-Metal2 keep-out is respected — this
   is already in the footprint the estimate uses.
4. **No plate over the divider (`D`) or over the `VOUT_S`/`FB` routes.** The
   divider is the one resistor whose ratio is the output accuracy, and it gets
   a clear field above it.

**Note on the rectangle.** The 4 mm candidate estimates at 76 108 µm², slightly
over the 75 000 µm² rectangle drawn above. That is 1.5 % and lands inside the
25 % budget margin either way; if #139 lands on 4 mm, grow the core to
300 × 260 µm (78 000 µm², 22 % margin) rather than compressing the resistor
field.

---

## 8. Where the EM limits come from, and what is still an assumption

**Where the EM limits come from, and the one layer that has none.** The
`gf180mcuD` install's *only* machine-readable current-density data is the
`DCCURRENTDENSITY` / `ACCURRENTDENSITY` entries in the standard-cell tech LEFs,
`libs.ref/gf180mcu_fd_sc_mcu{7,9}t5v0/techlef/*.tlef`. Nothing else in the
install carries EM data — not the DRC decks (geometry-only across all 41 rule
tables / 642 rule categories), not the ngspice models, not `libs.tech/magic`,
not `libs.tech/openlane`. Two consequences:

1. **The metal and via limits §3.3 uses are real PDK data, not assumptions.**
   All six tech LEFs in this install agree: Metal1–Metal4 0.67 mA/µm DC
   (1.00 AC), Metal5 1.5 mA/µm DC (2.2 AC), Via1–Via4 0.18 mA per cut DC
   (0.28 AC). (2AMLogic/klayout-tools#1215 reports a 24 % top-metal
   disagreement between the `fd_sc` and `osu_sc` views — *this* install ships
   only the two `fd_sc` libraries, so that disagreement does not arise here.
   An install that also carries `gf180mcu_osu_sc_*` would need the
   conservative 1.21 mA/µm for Metal5 instead of 1.5.)
2. **The `CON` diffusion/poly contact layer carries no current-density entry at
   all** — verified by reading the layer block directly; it declares
   `TYPE CUT ;` and nothing else. For a 50 mA power device the device-to-Metal1
   contact array is normally the tightest constraint in the whole stack, so
   this is the one number this design most needs and the one the PDK does not
   give.

### 8.1 What the raw tech LEF entries mean

The file does not state its own units beyond `UNITS … CURRENT MILLIAMPS 1 ;`.
A bare `DCCURRENTDENSITY AVERAGE 0.67 ;` on a routing layer is therefore
ambiguous on its face between **mA per µm of drawn width** and **mA per µm² of
cross-section** — the two readings differ by a factor of the layer thickness,
1.85× on Metal1–Metal4 and 1.19× on Metal5, straight into the metal strategy,
and the wrong reading is permissive on Metal5. The file settles the ambiguity
against itself; no external spec text is needed.

**Routing layers — the entries track thickness, so they are per unit width.**
The tech LEFs declare `THICKNESS` for every routing layer. Divide each entry by
its layer's thickness and see whether the result is constant:

| Quantity | Metal1–Metal4 | Metal5 | Ratio (M5 / M1–M4) |
| --- | --- | --- | --- |
| `THICKNESS` | 0.54 µm | 1.19 µm | 2.204 |
| `DCCURRENTDENSITY AVERAGE` | 0.67 | 1.5 | **2.239** |
| `ACCURRENTDENSITY AVERAGE` | 1.00 | 2.2 | **2.200** |
| entry ÷ thickness, DC | 1.241 | 1.261 | agree to **1.6 %** |
| entry ÷ thickness, AC | 1.852 | 1.849 | agree to **0.17 %** |

Read as **mA/µm of width**, the file is one volumetric limit — ≈ 1.24 mA/µm²
DC, ≈ 1.85 mA/µm² AC — applied to two declared thicknesses, self-consistent to
1.6 % on the DC pair and 0.17 % on the AC pair. Read as **mA/µm² of
cross-section**, the entry would already be thickness-normalised and would have
no reason to track thickness at all; it would instead be asserting that the same
aluminium metallisation is 2.2× stronger volumetrically on Metal5 than on
Metal1. The AC pair tracking thickness to within 0.17 % is not a coincidence
that survives that reading. **Verdict: mA per µm of drawn width.**

**Cut layers — the entries are per cut, not per µm² of cut area.** A Via1–Via4
cut is 0.26 µm square (V1.1), i.e. 0.0676 µm². Cross-check each reading against
the metal it lands on, which §8.1's first half has already pinned down:

| Reading | DC per Via1 cut | vs. 0.26 µm of Metal1 (= 0.26 × 0.67 = 0.174 mA) |
| --- | --- | --- |
| **0.18 mA per cut** | 180 µA | **+3.3 %** — a cut carries what its own width of metal carries |
| 0.18 mA/µm² of cut area | 12.2 µA | 14.3× *less* than the metal feeding it |

The AC pair agrees: 0.28 mA per cut vs. 0.26 × 1.00 = 0.26 mA of Metal1, within
7.7 %. The per-cut-area reading would require ~14 cuts under every
minimum-width wire just to break even with the wire, which is not what the
PDK's own via rules (V1.2a, a 0.26 µm cut spacing giving a 0.52 µm array pitch)
are built around. **Verdict: mA per cut.**

Both verdicts are re-derivable from the pinned install alone
(`c6d73a35f524070e85faff4a6a9eef49553ebc2b`) — `THICKNESS`, `WIDTH` and the
density entries are all in the same six files.

**What is still not established by any of this**: the tech LEFs state no
temperature, no target lifetime, and no array-derating factor for *any* of
their current-density entries. §3.3's operating point is Tj = 125 °C; the
published limits carry no stated Tj of their own. That caveat applies to the
metal and via rows too, not only to the contact row, and it is the reason §3.3
is sized with ≥ 2.4× margin everywhere rather than to the limit.

### 8.2 Reconciliation with the figures this document assumed before the tech LEFs were found

An earlier revision of this plan (and issue #278 as originally filed) sized the
power path against *assumed* limits, on the premise that the open PDK published
none. Four of those rows now have a published counterpart. Recording the
comparison rather than quietly dropping it, because two of the four assumptions
were **optimistic**, not conservative:

| Layer | Previously assumed | Published (tech LEF) | Verdict |
| --- | --- | --- | --- |
| Metal1–Metal4 | 1.0 mA/µm | **0.67 mA/µm** | **corrected** — the assumption was optimistic by **1.49×** |
| Metal5 | 1.5 mA/µm | **1.5 mA/µm** | **confirmed exactly** |
| Via1–Via4 | 200 µA per cut | **180 µA per cut** | **corrected** — optimistic by **1.11×** |
| Contact (0.22 µm) | 150 µA per cut | *none published* | **still an assumption** — now DR-0030's 129 µA, 1.16× more conservative than the old figure |

§3.3's table is already computed against the published column, so no margin
claim in this document rests on the superseded assumptions. The point of
recording it is that the old "a ≥ 3× margin protects us against the magnitude
being wrong" argument was doing real work: on Metal1–Metal4 the assumption *was*
wrong, by 1.49×, in the unsafe direction.

### 8.3 The contact layer — the one remaining assumption

**The only assumption in §3.3 is therefore the contact limit**, taken as
**129 µA per cut** by scaling Via1's published 0.18 mA by cut area
(`0.18 mA × (0.22 / 0.26)² = 0.129 mA`). Area scaling is the conservative
choice — width scaling would give 0.152 mA. At 25.0 µA per contact the plan has
5.2× margin against it, so it survives a contact limit up to 5× more
restrictive than this proxy.

That placeholder is no longer a note inside this document: it is
[`DR-0030`](../spec/decision-records/DR-0030-contact-layer-em-placeholder.md)
(`Status: proposed` — ratification is the operator's act per DR-0004), which
records the derivation, the conditions it does *not* establish, and four
falsifiable revisit triggers. The two that bear on this plan directly:

- **the margin trigger** — if any change pushes the worst-case per-contact
  current above **43 µA** (= 129/3), the placeholder stops being survivable on
  margin alone. At 2 mm the worst case is 25.0 µA, and #139's wider candidates
  move *away* from the trigger, not toward it;
- **the mechanism caveat** — a contact lands on silicide over diffusion, a via
  on aluminium, so scaling one to the other is a proxy whose *mechanism* may be
  wrong and not merely whose magnitude may be off. Margin cannot buy that back.

Until DR-0030 is superseded by a real published number, **any EM claim this repo
makes about the contact layer must carry this caveat** — a claim of "the contact
array is EM-clean at 50 mA" is only ever "…against DR-0030's 129 µA placeholder,
with 5.2× margin". The metal and via rows carry no such caveat: they may be
cited as PDK data.

### 8.4 Two further assumptions, unrelated to EM

Both inherited rather than introduced here:

- **Divider mismatch** uses `ppolyf_u`'s disabled `par_r = 0.021` card
  coefficient as a proxy for the 3k flavour — `README.md` note 3 sanctions
  exactly this proxy, and `sim/devchar/CONCLUSIONS.md` §2 notes nothing is
  published for the high-sheet flavours. It is not, and cannot become, a
  simulated result against this PDK.
- **Silicon thermal conductivity** is taken as 100 W/(m·K) at 125 °C for §3.5
  and §4's spreading arithmetic. The half-space constriction formula also
  ignores the package, which is exactly what `README.md`'s Thermal row delegates
  to the integration spec.

---

## 9. Design-review checklist

This issue's deliverable is a plan, so its verification is a review, not a
testbench. The area arithmetic *is* automated
(`layout/tests/test_area_estimate.py`, run by CI); everything else below is a
manual check to run against the first real GDS.

**Pass array**

- [ ] Array is N identical unit cells; N is the *only* thing that changed if the
      pass device was re-sized (§3.1).
- [ ] `W/nf` of every FET in the block is inside the same DR-0025 bin interval
      as its schematic value (§4.4).
- [ ] `Msense` is M unit cells of the same drawn geometry, inside the array,
      symmetric about its centroid, with `N/M = 40` (§3.2).
- [ ] Via1 is a **full column** along every source and drain M1 strap, not a via
      per strap (§3.3).
- [ ] M3 is stitched to M2 across the whole array at ≤ 5 µm pitch (§3.3).
- [ ] **Metal1–Metal5 and Via1–Via4** (*not provisional — PDK data*): worst-case
      current density on every level is computed against the tech LEFs'
      published `DCCURRENTDENSITY`, in the units §8.1 derives (mA/µm of drawn
      width for routing, mA per cut for cuts), and recorded with its margin —
      at 50 mA, not at a typical load.
- [ ] **`CON` contacts** (*provisional — DR-0030 placeholder, not PDK data*):
      worst-case per-contact current computed and recorded against DR-0030's
      129 µA, **and** checked against DR-0030's margin trigger — if it exceeds
      **43 µA** the placeholder is no longer survivable on margin and a real
      published number is required before the change lands.
- [ ] DR-0030's PDK trigger re-run against whatever install the GDS is built
      against, not just the pinned one: `awk '/^LAYER CON/,/^END CON/'` over
      every `libs.ref/*/techlef/*.tlef`, checking for a `DCCURRENTDENSITY` entry
      that would supersede the placeholder.
- [ ] If the install used carries `gf180mcu_osu_sc_*` libraries as well, Metal5
      is re-checked against the conservative 1.21 mA/µm view (§8), and DR-0030's
      contact placeholder is re-derived from that install's conservative Via1
      view (DR-0030 trigger 4).
- [ ] On-chip power-path resistance measured (extracted) ≤ 80 mΩ total, and the
      resulting dropout adder is re-checked against the *then-current*
      `sim/dropout-vs-load` margin (§3.4).

**Matching**

- [ ] Divider is 18 identical units, interdigitated with both centroids at the
      row middle, dummy at each end, linked in metal not poly (§4.1).
- [ ] Divider total is still 900 kΩ — DR-0001's ~2 µA preload has not moved.
- [ ] Divider tap is a single-metal-layer change (DR-0003's mask option).
- [ ] Input pair is 360 µm² per side, 2-D common centroid, ≥ 2 dummy fingers per
      row end (#9's stated requirement).
- [ ] Every matched pair's centroid is ≥ 150 µm from the pass-array centroid,
      **and** the pair is common-centroid — both, not either (§4).
- [ ] All matched devices share orientation and current direction.

**Kelvin sensing**

- [ ] `VOUT_S` and `VOUT_F` are separate nets meeting at exactly one point, and
      that point is the VOUT pad landing (§5).
- [ ] `Rsns` **and** `Rref` land on `VOUT_F`, at the same node (§5).
- [ ] `VOUT_S` is ≥ 1 µm wide, ≤ 50 Ω end to end, on its own track, shielded
      where it passes `PASS_GATE`/`EN`/`ENB`.
- [ ] `Cff`'s low-impedance (`VOUT_S`) node is on the MIM **bottom** plate.
- [ ] `FB` does not cross a power plate or a switching net.

**Area**

- [ ] `python3 layout/area_estimate.py` re-run against the then-current netlist,
      and the real block rectangles compared to its per-kind occupied areas.
- [ ] No single MIM plate exceeds MIM.8b's 10 000 µm².
- [ ] Every stacked MIM meets all four conditions in §7.

---

## 10. Follow-ups filed

- **#278** — the `CON` contact layer has no published current-density limit, so
  §3.3's contact row rests on a cut-area proxy. **Resolved** by promoting that
  proxy out of this document into
  [`DR-0030`](../spec/decision-records/DR-0030-contact-layer-em-placeholder.md)
  (`Status: proposed`), which carries four falsifiable revisit triggers, and by
  §8.1's derivation of the tech LEF unit convention / §8.2's reconciliation
  against the figures this plan assumed before the tech LEFs were found. The gap
  itself is **not** closed — the PDK still publishes nothing for `CON`, and
  DR-0030 books that as a stated residual risk of building a 50 mA power device
  against an open PDK. (The metal and via rows are not affected: they are PDK
  data, from the tech LEFs.)
- **#279** — resistor-flavour area lever: `Rz`/`Rbufb`/`Rza`/`Rbias` in
  `ppolyf_u_3k` would recover ~16 % of the area budget but changes the corner
  spread on a steep stability frontier; needs a loop-stability re-run, so it is
  a separate issue, not a layout choice.
- **#139** — commented with §3.2's exact-replica-ratio argument (which favours
  4 mm), §6's finding that the pass device is 4.6 %, not the largest
  contributor, of the area budget, and §3.4's observation that widening halves
  the array's max-corner via-sea resistance.
- **[klayout-tools#2308](https://github.com/2AMLogic/klayout-tools/issues/2308)**
  — per CLAUDE.md's friction protocol. Every geometric constant in
  `area_estimate.py` (CO.1, CO.3, CO.4, CO.7, `DF.6_LV`, DF.2b, PRES.1, PRES.2,
  PRES.7, MIM.1, MIM.8b, V1.1, V1.2a) had to be transcribed by hand out of
  *Ruby comment strings* in the PDK's rule decks, because no verb reports a
  deck's rule values — `klt deck info` gives a content hash and device classes,
  `klt drc` needs a stream and reports violations, and neither exposes the rule
  table. A hard-coded copy does not move when the PDK revision does, and the
  `DF.6_LV` / `DF.6_MV` variant split is exactly the kind of ambiguity prose
  citation hides.
