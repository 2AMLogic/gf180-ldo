# DR-0005: the untrimmed current-limit window cannot be ±10 % on this PDK

- **Status**: ratified 2026-08-21 (issue #105) — **pending**: this status
  line states the diff this record's ratifying pull request proposes; per
  the 2026-08-19 ratification-via-PR policy (2AMLogic/2am#357), the
  operator's review and approval **of that pull request** is the
  ratification act itself — no separate ratification comment is expected.
  Until the pull request merges, this line is a proposal, not yet true of
  `main`, and `README.md`'s Current limit and Thermal rows keep their
  originally ratified 65–80 mA / ≤ 290 mW values.
- **Date**: 2026-08-01
- **Decided by**: agent-builder (issue #11) — recommendation only;
  ratification is #105 (drafted as a pull request, not a comment), mirroring
  how DR-0001–DR-0003 were ratified by DR-0004's merge onto `main` (and how
  DR-0006/#106 was drafted, PR #127). Issue #11's original evidence
  (`sim/current-limit/records/20260801-012857-164ab42.md`) recorded the row
  as **failing** on the ±10 % window and the Thermal consequence; see
  "Evidence refresh" below for the current, fresher record.

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

### Evidence refresh (issue #105, 2026-08-21)

Issue #100 (closed, merged via PR #115) minted a fresher current-limit /
thermal record after this record was first drafted:
`sim/current-limit/records/20260816-080440-8e105a0.md`, the same 63-point
full-factorial corner matrix (process {tt, ff, ss, fs, sf, res_ff, res_ss} ×
T {−40, 27, 125 °C} × Vin {2.97, 3.30, 3.63 V}), re-run against the current
`design/netlist/ldo_core.spice` (DUT sha256
`3aeb225910549530c8e12875c8065cf645d1ae28e4754e3e638d9a13d067813e`, confirmed
matching, post-PR #78/DR-0015's `Mrza`/`Rza` adaptive-compensation shelf).
It supersedes the record originally cited here
(`sim/current-limit/records/20260801-012857-164ab42.md`, itself since
succeeded on `main` by three intermediate corrections —
`20260802-023438-5ea33e8` → `20260802-085342-8a1a9e8` →
`20260802-105338-c828e73` — that refined some digits before PR #78 landed)
as the evidentiary basis for this decision: it is the record
`sim/CHARACTERIZATION.md` now cites for the Current limit and Thermal rows,
and it is fresh against the current DUT (the original 2026-08-01 citation
predates PR #78 by a week).

**The verdict is unchanged, and the numbers move by noise, not substance.**
Per the fresh record's own corner-by-corner diff against the last
pre-PR-78 record (`c828e73`), zero corners changed classification; the
current-limit / thermal testbench is a DC/quasi-static V-I sweep and PR #78's
change is confined to the error amplifier's AC compensation path, which this
bench does not exercise. Re-measured directly against the fresh record's
`summary.csv` for this PR:

| quantity | DR-0005's original citation (`164ab42`) | fresh record (`8e105a0`) |
|---|---|---|
| onset at `Vout` = 1.764 V, min…max | 62.01 … 93.80 mA | **62.0097 … 93.8256 mA** |
| onset into a dead short, min…max | 62.59 … 95.07 mA | **62.5924 … 95.1005 mA** |
| corners outside the ratified 65–80 mA window | 36 / 63 | **36 / 63** |
| dissipation into a short, worst corner | 345.1 mW @ `ff_125c_3.63v` | **345.215 mW @ `ff_125c_3.63v`** |
| corners exceeding the ratified ≤ 290 mW bound | 12 / 63 (not separately tallied in the original citation, but derivable from its per-corner table) | **12 / 63** |

The floor (62 mA) and the 65–80 mA-window ceiling basis (95 mA, from the
93.8 mA onset-at-1.764 V number) both hold against the fresh data with the
same headroom DR-0005 originally computed (measured max 93.8256 mA vs. a
95 mA ceiling — 1.17 mA / 1.25 % headroom; measured min 62.0097 mA vs. a
62 mA floor — 0.0097 mA headroom, unchanged in direction and in the same
noise band as the original citation).

**The thermal ceiling needs a one-milliwatt correction.** DR-0005's original
345 mW figure is the arithmetic product of the proposed 95 mA current-limit
ceiling and `Vin_max`: 95 mA × 3.63 V ≈ 344.85 mW ≈ 345 mW. But the quantity
the Thermal row actually bounds is the *measured* short-circuit dissipation,
and the physical short-circuit current at the worst corner is not the
95 mA ceiling — it is the dead-short onset itself, which the constant-current
clamp's own small inverse-fold (+0.32…+2.30 % from `Vout` = 1.5 V to a dead
short, README note 5) pushes slightly above the 1.764 V-onset number the
95 mA ceiling is centered on: **95.1005 mA at `ff_125c_3.63v`**, giving
`95.1005 mA × 3.63 V = 345.215 mW` — confirmed exactly against the fresh
record's `pshort_mw` column (`P = I × V` holds to better than 0.01 mW at
every one of the 63 corners; a dead short has `Vout = 0`, so this is exact,
not an approximation). A bare **345 mW** ceiling therefore undershoots its
own supporting evidence by 0.2 mW at the single worst corner — the design
would not actually clear its own proposed row with margin, contrary to this
record's "Consequences" claim. This record corrects the proposed ceiling to
**346 mW**: the measured worst case (345.215 mW) rounded up to the next
whole milliwatt, restoring ~0.8 mW (0.23 %) of headroom in the same spirit
as the mA-row's own rounding-for-headroom convention, rather than silently
re-stating a ceiling the evidence does not clear.

## Decision

Replace two rows of the ratified table, and add one note:

- **Current limit** — *62–95 mA over PVT untrimmed, constant-current
  (brickwall) clamp; never engages for `I_load` ≤ 50 mA at any corner;
  survives a continuous Vout = 0 short at Vin_max.* The window is the
  measured 62.0–93.8 mA plus rounding headroom, not a target: it is what an
  untrimmed threshold on this PDK is. A **±10 % window remains the stretch
  goal, explicitly conditional on trim** (see Alternatives).
- **Thermal** — *≤ 346 mW into a Vout = 0 short at the untrimmed 95 mA limit
  ceiling* (was ≤ 290 mW at an 80 mA ceiling). The continuous-operation
  92 mW figure is unchanged; only the short-circuit ceiling moves. It is
  derived from the measured worst-case short-circuit dissipation
  (345.215 mW, `ff_125c_3.63v` — see "Evidence refresh") rounded up to the
  next whole milliwatt, not from a bare arithmetic product of the current
  ceiling and `Vin_max` (which would be 345 mW and would undershoot the
  measured worst point by 0.2 mW).
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
  design already meets the proposed rows with margin (62.0097 mA worst-case
  onset vs. a 50 mA rated load; 345.215 mW measured worst-case dissipation
  vs. the proposed 346 mW ceiling — see "Evidence refresh" for why the
  ceiling is 346 mW and not the bare arithmetic 345 mW).
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
- **Bad consequence, mechanical:** `sim/current-limit/testbench/run.sh`'s
  own printed summary (`corners outside the ratified 65-80 mA window`) and
  every current-limit/thermal record's hand-written "Overall" verdict text
  are checked against the *ratified* window at the time each record was
  written — this record does not re-run the harness, and evidence records
  are append-only. So `sim/current-limit/records/20260816-080440-8e105a0.md`
  and `sim/CHARACTERIZATION.md`'s generated Current limit / Thermal verdicts
  (which parse a record's own stated "Overall (...)" text, not an
  independent threshold check) keep reading **FAIL** even once this record
  is ratified, judged against the superseded 65–80 mA / 290 mW bounds. The
  raw `ilim_1764_ma` / `pshort_mw` columns in that record's `summary.csv`
  already show every point inside the proposed 62–95 mA / ≤ 346 mW window
  (see "Evidence refresh" above); a fresh record that states its "Overall"
  verdict against the ratified 62–95 mA / 346 mW window is a follow-on step,
  not part of this record.
- **DR-0004 stays ratified**; if this record is ratified it supersedes only
  the two rows named above, and DR-0004's Status line should point here for
  them.
