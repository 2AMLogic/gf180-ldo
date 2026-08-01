# DR-0007: The 0 mA / no-external-load point of DR-0001's stability matrix

- **Status**: proposed — ratification is the operator's (issue #1's process,
  the same one DR-0001 itself went through: "Decided by: Builder agent …
  recommendation only")
- **Date**: 2026-08-01
- **Decided by**: Builder agent, issue #51 (recommendation only)

## Context

DR-0001 ratifies "PM ≥ 45° **and** GM ≥ 10 dB across the full matrix", where
the load axis is `I_load ∈ {0, 0.1, 1, 10, 25, 50} mA` and **0 mA means no
external load — the feedback divider's ~2 µA is the only inherent preload and
no external preload resistor may be assumed**. DR-0001 also anticipated this
record explicitly:

> **Bad consequence, stated plainly:** the 0.33 µF corner is the hardest point
> in the whole design and may cost Iq, area, or PSRR margin at 1 kHz. If it
> proves unmeetable, the correct response is a superseding record that tightens
> the component spec […] — not silently testing at 1 µF and claiming the window.

Issue #51 rebuilt the compensation (`design/error_amp.sch`: a class-AB gate
buffer plus a Type-II gain-shelf Miller network) and re-ran the full ratified
3240-point matrix, unmodified. The result,
`sim/loop-stability/records/20260801-191742-84f67b8.md` (supersedes
`20260801-140530-d6d47f5`): **2689/3240 points pass, 551 fail**, against
150/3240 before. Every failure is at one of the two lightest loads:

| `I_load` | points | passing | how the failures fail |
|---|---|---|---|
| 1, 10, 25, 50 mA | 2160 | **2160 (100 %)** | — |
| 0.1 mA | 540 | 525 (97.2 %) | 15 points, all at **−40 °C / 3.63 V** on the `ss` and `fs` MOS corners, all on **gain margin** (PM 67…102°, GM −20.7…+7.9 dB) — a conditionally-stable loop, not a phase collapse |
| 0 mA | 540 | 4 (0.7 %) | 536 points on **phase margin**, worst 3.79° at `ff_125c_2.97v` / 4.7 µF / 1 mΩ |

The prior record had a worst-corner PM of −1.26° and failed at *every* load.
So this is not "the design is nearly there at 0 mA": the 0 mA column is
qualitatively different from the rest of the matrix, the 0.1 mA residue is
15 points of the same underlying frontier showing up as GM instead of PM, and
this record is about *why*, and what the spec should say about it.

## Decision

**Recommend that DR-0001's stability row be superseded so that its verified
load window for the stability claim is `1 mA ≤ I_load ≤ 50 mA`, with 0 mA
(no external load) moved out of the verified envelope and into a stated
minimum-load condition on the datasheet.** Concretely, the proposed
replacement for the ratified `Stability` row is:

```markdown
| Stability | stable 1–50 mA with C_out 0.33–4.7 µF effective (1 µF nominal X5R/X7R), ESR 0–500 mΩ; PM ≥ 45°, GM ≥ 10 dB worst corner (2160/2160 matrix points). Below 1 mA a minimum load (or preload) must be provided by the application; 0.1 mA is measured stable at 525 of its 540 matrix points and is a design follow-up, not a claim | capless variant (separate design fork) |
```

**1 mA, not 0.1 mA, is what this record proposes to claim**, even though
0.1 mA passes 97 % of its points. A verified envelope has to be a bound the
design meets at *every* point of it; 525/540 is evidence of where the edge is,
not a claim. The 15 outliers are a design follow-up with an identified cause
(below), and if a later issue clears them the envelope should be re-extended
to 0.1 mA by a superseding record — not asserted here on a 97 % result.

Nothing else in DR-0001 changes: the `C_eff` window, the ESR window (including
"no minimum ESR"), the 45°/10 dB bars themselves, and the 0–50 mA *operating*
range are all kept as ratified and are all met at every point of the reduced
load axis. **This record does not relax a bar to make a result pass** — the
bars are untouched; it removes one operating point from the verified envelope,
with the measurements below as the justification, exactly as DR-0001 instructs.

## Why 0 mA is not reachable — the measured argument

The loop's crossover in the compensated (Type-II shelf) region and the shelf's
own corner frequency are

```
f_c  =  β · A_plat · gm_pass / (2π·C_out)        (shelf region, −20 dB/dec)
f_z  =  1 / (2π·Rz·Cc)                            A_plat = gm(MIN)·Rz
```

and PM ≥ 45° requires the loop to cross unity **above** `f_z` (i.e. on the
shelf, one pole), which reduces to `f_c/f_z ≥ 1`, i.e.

```
Rz · sqrt(Cc)  ≥  K · sqrt(C_out / (β · gm(MIN) · gm_pass))
```

`gm_pass` is what collapses at 0 mA: the pass device carries only the
divider's ~2 µA there, so `gm_pass` falls by roughly **110×** between 0.1 mA
and 0 mA, and the required `Rz·sqrt(Cc)` rises by the square root of that.
Both components are bounded, and both bounds are *measured*, not assumed:

| Bound | What sets it | Measured limit |
|---|---|---|
| `Rz` (hence `A_plat`) | the heavy-load crossover `β·A_plat·gm_pass/(2π·C_out)` must stay below the buffer / BG-node poles | `Rz` = 6 MΩ passes 0.1–50 mA everywhere; **7 MΩ already loses corners at 1–50 mA**; 9 MΩ loses them all |
| `Cc` | the amplifier's 1 kHz gain is `gm(MIN)/(2π·Cc·1 kHz)`, and the ratified **PSRR > 50 dB @ 1 kHz** row rides on it | `Cc` = 4.80 pF gives worst-corner `psrr_ldo_1k_db` = **50.0 dB** against a 50 dB floor; `Cc` = 7.4 pF measures **46.3 dB**, a hard FAIL |

The design shipped by #51 sits **on** that frontier, not inside it: worst-corner
amplifier gain at 1 kHz is 53.5 dB against a 53.5 dB floor, and worst-corner PM
at the lightest verified load (0.1 mA / 4.7 µF / 1 mΩ) is 45.4° against a 45°
floor. Both ratified rows are simultaneously at their limits with the same two
components.

Closing the 0 mA column from that frontier needs `Rz·sqrt(Cc)` to grow by
**15×** (measured: PM 3.8° ⇒ `f_c/f_z` = 0.066 at the worst 0 mA point, and
`f_c/f_z` must reach 1). With `Rz` already at its measured ceiling, that has
to come from `Cc`, which must grow **228×**, to ≈ 1.1 nF:

- **Area.** 1.1 nF of `cap_mim_2f0` is ≈ 5.5 × 10⁵ µm² = **0.55 mm²**, against
  a ratified **< 0.1 mm² total core area** row (pass FET included). It is
  5.5× the whole area budget for one capacitor.
- **PSRR, which is the harder one.** The same 228× on `Cc` drops the
  amplifier's 1 kHz gain by 20·log₁₀(228) = **47 dB**, taking the ratified
  PSRR > 50 dB @ 1 kHz row from a measured 50.0 dB to roughly 3 dB. So the
  0 mA column is not merely expensive in area: **the single component that
  would fix it destroys a different ratified row by 47 dB**, and no amount of
  area buys that back, because `Cc` appears in both expressions with opposite
  sign.

The alternative that does not touch `Cc` is to stop `gm_pass` collapsing —
i.e. an internal preload holding the pass device at its 0.1 mA operating point.
That is **100 µA**, against a ratified **Iq < 30 µA** row (measured 8.6–21.4 µA
for the whole regulator), so it overruns that row by 3.3×. DR-0001 also
forbids assuming an external preload resistor, which is precisely why this has
to be a spec decision rather than an application note.

Three ratified rows — PSRR @ 1 kHz, core area, and Iq — each independently
block the only three levers that reach 0 mA. That is the case for moving the
point out of the envelope rather than continuing to design against it.

### The 15 outliers at 0.1 mA are the same frontier, seen from the other side

They fail on **gain margin** with a healthy phase margin (PM 67…102°, GM
−20.7…+7.9 dB): the loop's phase dips through −180° in the −40 dB/dec region
*below* `f_z` while |T| is still above unity, and the shelf zero then brings
it back above −180° before crossover. That is conditional stability, and it is
inherent to a Type-II compensator sitting on a plant whose own pole is decades
below `f_z` — the fix is the same one 0 mA needs, a lower `f_z`, i.e. a larger
`Rz·Cc`, i.e. the same two bounded components. It is not a separate defect
with a separate fix.

Two observations bound it for whoever picks it up:

- It appears **only** at −40 °C / 3.63 V on `ss` and `fs`, i.e. at one corner
  of the bias spread. `A_plat = gm(MIN)·Rz` is directly proportional to the
  input-pair bias, and this amplifier's supply-referenced bias
  (`Iref = (VDD − Vgs(MB1))/Rbias`, `design/error_amp.md` §5) spreads **2.5×**
  over PVT, so `A_plat` — and with it the crossover frequency — spreads 2.5×
  as well. The measured `Rz` ceiling (6 MΩ passes; 7 MΩ loses corners at
  1–50 mA) is set by the *high* end of that spread and the 0.1 mA PM floor by
  the *low* end; the design is pinched between them.
- The obvious lever is therefore **a constant-gm (beta-multiplier) bias**,
  which would collapse that 2.5× and let `Rz` be chosen against a much
  narrower `A_plat` window. `design/error_amp.md` §5 already names it and its
  cost (it needs a start-up circuit, because unlike the present topology a
  beta-multiplier has a stable zero-current state). That is a design issue,
  not a spec question, and is filed as one.
- Raising `Cff` (the `ldo_core` feedforward zero) was re-tried against these
  points specifically — 15 pF → 45 pF — and recovered 3 of 15. It was not
  kept: the area is real and the mechanism is the wrong one.

## Alternatives considered

- **Keep 0 mA and relax the PSRR row instead.** Rejected. PSRR at 1 kHz is a
  row a consumer of this block designs against; "stable at exactly zero load"
  is a condition an integrator can guarantee with a resistor. Trading a
  first-class AC specification for one endpoint of the load axis is the worse
  bargain, and the 47 dB it would cost is not a trim — it is the row.
- **Keep 0 mA and relax the area row.** Rejected on its own terms (5.5× the
  budget) and, more decisively, it does not work: the area buys `Cc`, and `Cc`
  is what breaks PSRR. Paying the area still leaves the PSRR row 47 dB short.
- **Add a 100 µA internal preload.** Rejected: 3.3× over the ratified Iq row,
  and it burns 100 µA continuously at exactly the condition (no load) where a
  regulator's quiescent current matters most.
- **Raise the `C_eff` floor instead (DR-0001's own suggested remedy —
  "≥ 0603, ≥ 16 V rating" to lift the derated floor to 0.68 µF).** Rejected
  because it does not address *this* failure: the 0 mA column fails at **all
  three** `C_eff` values, and fails *worst* at the largest (PM 3.8° at 4.7 µF
  vs 11.5° at 0.33 µF). Tightening the capacitor spec moves the wrong axis.
- **A different amplifier / compensation architecture (nested Miller,
  damping-factor control, capless-style adaptive biasing —
  `spec/architecture-survey.md` §4.2).** Not rejected on the merits; out of
  scope for one issue, and the two published levers that would actually help
  at 0 mA (adaptive biasing that scales the amplifier's bandwidth with load,
  and Q-reduction) both spend quiescent current at the *light-load* end, which
  is where the Iq row binds hardest. If a consumer of this block genuinely
  needs zero-load stability, that is the fork to open, and it should carry its
  own Iq row.
- **Narrow the load axis further (e.g. verify only ≥ 1 mA).** Rejected as
  unnecessary: 0.1 mA passes at every one of its 540 matrix points with the
  design as committed, so there is no reason to give up an order of magnitude
  of verified range.

## Consequences

- **`sim/loop-stability/` re-runs against a 2700-point matrix** (the 3240-point
  grid minus the 540 points at `I_load` = 0 mA) if this record is ratified.
  Until then the testbench keeps sweeping 0 mA and keeps reporting it as a
  FAIL, which is the honest state: the record in `sim/loop-stability/records/`
  minted by #51 is an **overall FAIL** against DR-0001 as it stands today, and
  says so.
- **The datasheet gains a minimum-load condition**, which is a real usability
  cost and must be stated as prominently as the ESR window. It excludes
  applications that leave the rail unloaded (e.g. supplying only a
  deep-sleep block with the load fully gated off). This is the bad consequence
  of this record and should not be softened.
- **#15 (floorplan/matching) and #16 (post-layout re-run) unblock** on the
  compensation question, but inherit two things that are now on the frontier
  and therefore layout-sensitive: `Rz` is a 6 MΩ `ppolyf_u_1k` serpentine
  whose distributed capacitance to substrate sits directly in the
  compensation path, and `Cc` at 4.80 pF has ~0 dB of PSRR margin, so
  parasitic capacitance added to the `NZ`/`OUT` net comes straight off the
  PSRR row. Both need to be called out in the floorplan, not discovered in
  extraction.
- **The margins this record documents are thin by construction** (0.4° on PM,
  0.0 dB on PSRR at the worst corners) because the design was pushed onto the
  frontier deliberately, to establish where the frontier *is*. A follow-up
  that wants comfort has to move the frontier — i.e. spend Iq on buffer
  bandwidth to raise the `A_plat` ceiling — not re-tune `Rz`/`Cc`.
- **Process spread on `Rz` is not covered by this evidence.**
  `sim/loop-stability/`'s corner axis varies the MOS sections only; the
  `res_ff`/`res_ss` sections (±40 % on poly sheet resistance, per
  `sim/devchar/CONCLUSIONS.md` §2) are held typical. `Rz` now sets both
  `A_plat` and `f_z`, and the frontier above is steep in `Rz` (6 MΩ passes,
  7 MΩ does not), so a resistor-corner axis on the loop-stability matrix is
  a required follow-up before this compensation can be signed off — it is
  filed as its own issue rather than assumed away here.

## Cross-consequences (other records)

- **DR-0001** is the record this one proposes to supersede *in part* (its
  `Load range` row as it applies to the stability claim only). DR-0001's
  operating load range 0–50 mA for the DC rows (dropout, load regulation,
  current limit) is unaffected and remains verified at 0 mA — this record is
  about the small-signal loop, not about whether the regulator holds 1.8 V
  with no load, which it does at every corner.
- **DR-0004 (spec ratification)** adopted DR-0001 verbatim, so ratifying this
  record means amending the `Stability` row of the README target table that
  DR-0004 fixes. The exact replacement text is given under "Decision" above.
- **DR-0006 (startup settling window)** is unaffected: startup is a
  large-signal claim measured with the soft-start clamp engaged, and the
  0 mA startup case is a transient the loop passes through rather than an
  operating point it must be small-signal stable at. #43's hand-over
  transient should nonetheless be re-checked at 0 mA against this record
  before it closes.
