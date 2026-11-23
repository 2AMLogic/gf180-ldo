# DR-0045: The amplifier slot's committed answers for `gf180-opamp` — offset share, divider ratio and VCM, noise position

- **Status**: proposed — a report of already-committed positions, not a spec
  change. No row, note, bound or lock entry changes with this record; the
  answers below hold through their cited sources, each labelled **ratified
  here**, **committed but descriptive**, or **new proposal, pending
  ratification**.
- **Date**: 2026-11-20
- **Decided by**: Builder agent, issue #790
- **Sources read at**: `9206133ec27f` (main, 2026-11-20) — every citation
  below resolves at that commit.

## Context

`2AMLogic/gf180-opamp` cannot set its input-offset and noise spec rows: its
DR-0007 (§3.3) requires limits derived from consumer allocations, and its
issue #62 is blocked on exactly that. This record transcribes this repo's
committed position for the `error_amp` slot, quoting the figures from the
cited files at the commit above. It answers Q1 (the accuracy window and the
amplifier's offset share), Q2 (divider ratio and input common mode) and Q3
(output noise). Deriving the amplifier's own limits from these answers is
`gf180-opamp`'s next record (its DR-0007 §4), not this one.

## Decision

### Q1 — accuracy window and the amplifier's offset share

- **Window.** 1.8 V ±2 % = **±36 mV, 3σ**, over line (2.97–3.63 V), load
  (0–50 mA) and temperature (−40…125 °C), and it is **regulator-only: VREF's
  own error is excluded**; load regulation (<1 %, 18 mV) is counted inside
  the window (README spec table "Output" and "Load reg" rows; README note 2).
  **[ratified here: Output row via DR-0004, note 2]**. Reference error flows
  to VOUT at 1.5× and is outside every ratified row (DR-0021, proposed;
  README note 2).
- **Combination rule.** Statistical terms add in RSS at a common 3σ;
  deterministic terms add linearly on top; every term is referred to the
  output through 1/β = 1.5 (`design/error_amp.md` §3).
  **[committed but descriptive]**
- **In-tree amplifier budget.** Input-pair + mirror mismatch **2.33 mV
  input-referred (3σ) → 3.49 mV output-referred**; systematic offset
  **0.61 mV worst corner input-referred → 0.91 mV output-referred**
  (`design/error_amp.md` §3 table; §3.1 derives the mismatch figure and names
  2.33 mV / 3.49 mV as issue #13's Monte Carlo verification target; §3.3
  measures the systematic term at +280…+610 µV over 81 PVT points against a
  2 mV bench allocation, and §6.3's post-#53 re-measure reports 332–771 µV).
  **[committed but descriptive]**
- **Budget totals.** Static 7.40 mV against the 18 mV one-sided static
  allowance (2.4× margin); 25.4 mV including load regulation against the
  ±36 mV window (29 % margin) (`design/error_amp.md` §3).
  **[committed but descriptive]**
- **Budgeted contribution, not a ceiling.** The §3 amplifier figures are the
  *budgeted contribution of the in-tree amplifier*, not a ceiling allocated
  to any amplifier occupying the slot. **No separate amplifier offset ceiling
  is allocated**: the ratified Output row sets none, and a replacement
  amplifier must be judged against the ±36 mV window the way §3 does it.
  **[ratified here for the window; "no ceiling" is a report of absence, not a
  new allocation]**

### Q2 — divider ratio and input common mode

- **Rtop = 300 kΩ** (VOUT→FB), **Rbot = 600 kΩ** (FB→VSS), installed values
  in `design/ldo_core.sch`; **β = 2/3**; offset gain **1 + Rf1/Rf2 = 1/β =
  Vout/Vref = 1.5**; amplifier-input common mode at the tap = VREF =
  **1.2 V**; divider standing current 1.8 V / 900 kΩ = 2.00 µA
  (`design/error_amp.md` §2, `design/ldo_core.sch`). **[the 1.5 gain-up and
  the ~900 kΩ total: ratified here in DR-0003's budget against a 1.2 V
  reference; the exact 300 k/600 k split and VREF = 1.2 V: committed but
  descriptive — DR-0021 (proposed) makes VREF a top-level port and would
  ratify the reference-side interface]**

### Q3 — output noise

- **Not budgeted.** The Output-noise row is explicitly waived: "not
  specified — explicitly waived (note 7)" (README spec table), ratified by
  DR-0004 amendment A11 with note 7's rationale: no consumer requirement
  exists and no reference or amplifier design exists against which a µVrms
  number could be substantiated, so a number would be a claim without a
  testbench. **[ratified here: DR-0004 A11, README note 7]**
- **What a consumer ask would add.** The README's stretch column names a
  "10 Hz–100 kHz µVrms row if a consumer asks for one" — band 10 Hz–100 kHz,
  unweighted µVrms. No numerical allowance, weighting or amplifier share is
  stated anywhere; any such number would be a **new proposal, pending
  ratification** here, and per note 7 a consumer requirement is the waiver's
  superseding trigger. **[the conditional stretch entry: ratified as part of
  the table; any number on it: new proposal, pending ratification]**

### Reuse status

`reuse.lock.json` records `error_amp` against `2AMLogic/gf180-opamp` as
**`kept`**, by DR-0038 (proposed): `design/error_amp.sch` remains this
regulator's amplifier and the block does not instantiate the sibling's. These
answers therefore describe the requirement of the **slot**, while the block
keeps its own in-tree amplifier.

## Alternatives considered

- **Allocating an explicit amplifier offset ceiling here** — not chosen: no
  committed source fixes one, and inventing a number would present a proposal
  as an allocation. The record states the absence and the committed budget
  with its margin instead, which is what `gf180-opamp` needs to derive its
  own limits.
- **Answering only on `gf180-opamp`'s tracker** — not chosen as the primary
  artifact: this repo owns the committed sources; a citable record here,
  linked from a comment on 2AMLogic/gf180-opamp#62, is the durable evidence
  its DR-0007 asks for.

## Consequences

- `gf180-opamp` can set its input-offset rows against the reported window and
  combination rule, and its noise row as "not budgeted by the consumer".
- Nothing in this repo's spec changes: no row, note or lock entry is touched
  and `spec/spec-table-lock.json` is unmodified.
- If this repo later allocates an explicit amplifier offset ceiling or a
  noise allowance, that is a superseding record; DR-0004 A11's waiver already
  names a consumer requirement as its superseding trigger.
