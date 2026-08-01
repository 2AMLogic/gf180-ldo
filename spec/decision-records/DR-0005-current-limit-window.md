# DR-0005: the untrimmed current-limit window cannot be ±10 % on this PDK

- **Status**: proposed
- **Date**: 2026-08-01
- **Decided by**: agent-builder (issue #11) — **proposing**; the ratified spec
  is a human gate, and nothing in this record changes the table until it is
  ratified. Until then, `README.md`'s Current limit and Thermal rows stand as
  written and issue #11's evidence records them as **failing**.

## Context

DR-0004 ratified `Current limit: 65–80 mA over PVT` provisionally, with an
explicit revisit trigger: *"#11's sense-path error budget cannot fit inside
the 15 mA window between the two bounds."* Issue #11 built the limit and
measured it over the full 63-point PVT matrix
(`sim/current-limit/records/20260801-012857-164ab42.md`). The trigger has
fired, and the measurement says the cause is not the sense path:

| corner group | resistor sections | I_lim (mA) |
|---|---|---|
| tt | typical | 73.91 … 75.61 |
| fs, sf — **FET skew only** | typical | 73.85 … 75.66 |
| ff / res_ff | `res_ff` | 91.33 … 93.80 |
| ss / res_ss | `res_ss` | 62.01 … 63.39 |

Everything the *circuit* contributes — sense-ratio error, comparator
behaviour, −40…125 °C, ±10 % supply — is **under ±1.2 %**. Change only the
resistor model section and the limit moves **±20.4 %**. The reason is
structural, not a design deficiency: a current threshold is a voltage over a
resistance. The as-built threshold is `41 · VREF · (Rref/Rbias) / Rsns`, whose
`Rref/Rbias` ratio cancels exactly (same flavour, and this PDK's global
resistor spread is perfectly common-mode — `sim/devchar/CONCLUSIONS.md` §2),
leaving **one un-cancelled absolute on-chip resistance**. gf180mcu's tightest
resistor flavour still moves 38.7 % ff-to-ss (`npolyf_u`); the flavour used
here, `ppolyf_u`, moves 40 %. No untrimmed topology avoids this, because every
on-chip current reference — including the bandgap-referenced one this block
currently idealizes — sets its current with a resistor.

Two ratified rows then bound the *same* ±20 % distribution from opposite
sides and cannot both be satisfied:

- **Lower bounds.** "Never engages for `I_load` ≤ 50 mA at any corner"
  (Current limit) and "startup at full rated load stays ≥ 10 mA below the
  current limit" (Startup) ⇒ `I_lim,min` ≥ 60 mA.
- **Upper bound.** "≤ 290 mW into a Vout = 0 short at the 80 mA limit ceiling"
  (Thermal), at `Vin_max` = 3.63 V ⇒ `I_lim,max` ≤ 79.9 mA.

That demands `I_lim,max / I_lim,min ≤ 1.33`; the PDK delivers 1.50. The
65–80 mA row itself demands 1.23. **Both are infeasible untrimmed**, by
measurement, at any centering. The as-built design is centered at the lowest
value that satisfies the two lower bounds at the worst corner (74.9 mA
nominal, 62.0 mA worst case), which is also the centering that minimizes the
Thermal overage — 345 mW measured against 290 mW ratified.

## Decision (proposed)

Replace two rows of the ratified table, and add one note:

- **Current limit** — *62–95 mA over PVT untrimmed, constant-current
  (brickwall) clamp; never engages for `I_load` ≤ 50 mA at any corner;
  survives a continuous Vout = 0 short at Vin_max.* The window is the
  measured 62.0–93.8 mA plus rounding headroom, not a target: it is what an
  untrimmed threshold on this PDK is. A **±10 % window remains the stretch
  goal, explicitly conditional on trim** (see Alternatives).
- **Thermal** — *≤ 345 mW into a Vout = 0 short at the untrimmed 95 mA limit
  ceiling* (was ≤ 290 mW at an 80 mA ceiling). The continuous-operation
  92 mW figure is unchanged; only the short-circuit ceiling moves, and it
  moves as an arithmetic consequence of the row above, not as an independent
  relaxation.
- **New note** — *the current limit's spread is set by the absolute
  poly-resistor sheet corner (±20 %), not by the limit circuit (±1.2 %
  measured). Any tightening is a trim decision, not a design decision.*

## Alternatives considered

- **Keep 65–80 mA and re-center the design** — rejected: impossible, not
  merely hard. No centering of a ±20 % distribution fits inside a ±10.3 %
  window; the record's per-corner table is the proof.
- **Keep 65–80 mA and add trim** (a laser/e-fuse/metal-mask-selectable
  `Rsns` bank). This is the only way to *meet* the ratified row, and it is
  technically straightforward — `Rsns` is already drawn as 10 unit cells, so
  a ±3-step mask option covers the corner spread. Not proposed as the
  decision because trim is a product/flow commitment (test time, mask
  options, a trim spec) far outside this block's charter. **Recommended as
  the stretch path**, and the reason the ±10 % goal is retained above rather
  than deleted.
- **Lower the centering to clear 290 mW** — rejected. It puts the worst-corner
  onset at ≈ 53 mA, 6 % above the rated load, i.e. inside the sense path's own
  unmodelled comparator mismatch. A limit that nuisance-trips inside the rated
  range is a worse failure than a short that dissipates 55 mW more than
  budgeted: the first breaks the regulator in normal use, the second is an
  integration constraint the Thermal row already delegates to the package.
- **Drop the short-circuit power number entirely** — rejected. An unquantified
  row cannot be verified (DR-0004's own argument against qualitative rows).
- **Use a tighter resistor flavour** — rejected on measurement: the whole
  gf180mcu menu spans 38.7–50 % ff-to-ss corner spread
  (`sim/devchar/CONCLUSIONS.md` §2). The best available buys 1.3 points of
  the 10 needed.

## Consequences

- **The limit block needs no redesign if this is ratified.** The as-built
  design already meets the proposed rows with margin (62.0 mA worst-case onset
  vs. a 50 mA rated load; 345 mW vs. the proposed ceiling).
- **If this is *not* ratified**, the block is not shippable as-is against the
  Current limit and Thermal rows, and the resolution is trim — a new issue,
  not a re-tune. Nothing in `design/` should be quietly re-centered to make
  the table look satisfied.
- **The reported spread is a lower bound.** Comparator offset from device
  mismatch is not in it (this PDK's resistor models carry no local mismatch at
  all — `sim/devchar/CONCLUSIONS.md` §2 — and no Monte Carlo was run on the
  comparator pair), and the bias generator is still idealized as a CCCS off
  the ideal `VREF`. A real bandgap-referenced `Iref` adds its own error on
  top. Both push the same direction, so the case for widening only gets
  stronger, but the numbers above should be re-measured once a bandgap block
  exists.
- **Unrelated rows are untouched.** This record proposes nothing about the
  Startup row's overshoot/inrush numbers, which issue #11's evidence also
  shows failing (62 of 63 corners overshoot, inrush 153–289 mA). Those fail
  because **the design has no soft-start at all**, which is a missing design
  element rather than an unmeetable spec — it needs an issue, not a
  superseding record.
- **DR-0004 stays ratified**; if this record is ratified it supersedes only
  the two rows named above, and DR-0004's Status line should point here for
  them.
