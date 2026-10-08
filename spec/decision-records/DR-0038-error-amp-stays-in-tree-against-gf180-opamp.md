# DR-0038: `error_amp` stays in tree -- `gf180-opamp`'s published amplifier is not comparable evidence, and what it does show is not a viable base

- **Status**: proposed
- **Date**: 2026-10-08
- **Decided by**: Builder (issue #384)

## Context

`reuse.lock.json` carried one `in_tree` entry, `error_amp` against sibling
`2AMLogic/gf180-opamp`, at `"status": "evaluate"` (added by PR #274 for issue
#272, whose "adopt or record" step never produced a durable outcome). Open
work on `error_amp` (#312 poly flavour, #284 layout) makes the question live.
This record resolves it from **published, committed evidence only**; nothing
was simulated. Sibling state read: `2AMLogic/gf180-opamp` at commit
`cbf7d024781a` (2026-10-08).

## Decision

**Keep own.** `design/error_amp.sch` remains the amplifier of this regulator;
it is not replaced by, and does not adapt, `gf180-opamp`'s
`design/opamp_two_stage.sch`. `reuse.lock.json` moves from `evaluate` to
`kept`, with a `decision` field pointing at this record (the shape
`2AMLogic/sky130-ldo` uses for the same outcome). No ratified spec row
changes.

### Comparison (all sibling figures are from its committed files)

| Axis | This repo's `error_amp` | `gf180-opamp` published | Comparable? |
|---|---|---|---|
| Open-loop gain / PM into the pass-device load | `A0` 105.9-113.1 dB, UGBW 3.07-7.80 MHz over 81 PVT points, loaded by the buffered 6.14 pF pass gate; loop PM/GM graded by `sim/loop-stability` (DR-0018 envelope); 1 kHz gain >= 53.5 dB is a PSRR-row input (`design/error_amp.md` §6.3) | `sim/gain-gbw-pm/records/20261003-030340-7bd8071.md`: 86.5-90.8 dB, GBW 0.55-0.78 MHz, PM 56.1-57.9 deg, 15 points (5 process x 3 T), **fixed 3.3 V**, into **CL = 2 pF**, with **ideal current sources** for tail and stage-2 bias on a netlist the record calls "provisional, smoke-level" with "no spec pass/fail claim" | **No.** Different load (2 pF lumped vs a 6.14 pF nonlinear pass gate), no supply sweep, ideal bias, and no closed-loop or LDO-loop measurement. It is also 20+ dB lower gain and ~10x lower UGBW, short of this loop's needs (DR-0008 / DR-0018 stability work was needed on a faster, higher-gain cell) |
| Iq | 5.9-15.0 uA measured, inside the ratified Iq < 30 uA row (§5, §6.3) | Design point 80 uA / 264 uW (`design/opamp_sizing.md` §1, §4): a *chosen* point, "a prediction ... not a measured result"; bias is an external 10 uA `ibias` pin | **No measurement exists.** The 80 uA design point alone is 2.7x the whole-regulator 30 uA row |
| Area | ~9310 um² total active (§8, `layout/area_estimate.py`) | Area row `[TBD]`; no layout, no estimate. Sizing has M6 at 72 um x nf=24 and M7 36 um, i.e. a 60 uA output stage this regulator cannot afford | **No evidence.** |
| Poly flavour (DR-0033 / #312) | `Rbias` `ppolyf_u_1k`; `Rz`/`Rbufb`/`Rza` `ppolyf_u_3k`, chosen by whether the resistor carries DC | `RZ` `ppolyf_u_1k`, 2 um x 4 um, ~2.1 kOhm, a fixed nulling resistor sized as `1/gm6` | **Orthogonal.** 2 kOhm vs the 0.6-6 MOhm serpentines that drive the area row; no flavour trade study exists there. Nothing to inherit for #312 |

### Finding

The sibling has no committed evidence on any of the four axes that is
comparable to this regulator's measured, PVT-cornered, loop-loaded numbers.
Its only AC record is explicitly provisional; its Iq, area and PM-into-load
rows are predictions or `[TBD]`; its manifest (`manifests/gf180-opamp.json`)
lists empty `evidence`. That absence is itself the finding. Where it is
comparable (gain, GBW), it is lower than this cell by a margin that rules out
adopting it, and its Iq design point does not fit the 30 uA budget.

## Alternatives considered

- **Adopt** `opamp_two_stage` as-is -- fails on Iq (80 uA design point vs a
  30 uA whole-regulator row) and on gain / UGBW, with no gate-buffer for the
  pass-device load.
- **Adapt** it (take its gm/ID sizing method, retune bias) -- the topology
  differs from the shipped cell in exactly the places this cell's evidence
  was spent (class-AB gate buffer, Type-II shelf, adaptive `Rza`), so an
  adaptation would be a re-derivation, not reuse. Its gm/ID study
  (`sim/gm-id-characterization/`) is real, committed device data and may
  inform a future sizing pass on its own merits; that is a data citation, not
  a design reuse.
- **Leave at `evaluate`** -- the question would resurface every reuse sweep.

## Consequences

- #284 (layout) and #312 (poly flavour) proceed on `design/error_amp.sch`
  with no sibling dependency; nothing is invalidated.
- Revisit trigger: if `gf180-opamp` commits a PVT-cornered record of an
  amplifier driving a pass-gate-like load at <= 15 uA total supply current,
  supersede this record with a new one.
- This is a "not comparable, therefore not adopted" outcome; it makes no
  claim that the sibling's design is poor for its own (2 pF, 80 uA) spec.
- Bad consequence: the two repos keep separately maintained two-stage
  Miller amplifiers; that duplication is accepted until the revisit trigger
  fires.
