# DR-0040: the pass-array generator stays its own -- `gf180-gate-driver`'s `power_array_folded` solves a different problem (a row fold this array does not need), and neither generator subsumes the other

- **Status**: proposed
- **Date**: 2026-10-22
- **Decided by**: Builder (issue #498) -- a recommendation; the operator rules

## Context

Two generators exist for a large multi-finger gf180mcu power transistor, and
`REUSE.md` (in `2AMLogic/2am`, not this repo) requires a second design of the
same block to be a written decision. #483 may change the pass width (its open
options include capping it at <= 2.4 mm, i.e. reopening DR-0034), so the
question is worth settling before the pass array is reworked. This record
**does not pre-empt #483's option choice**; where the comparison depends on
the final width it says so. Nothing in `layout/` or the ratified spec changes.

Evidence is by reading committed files only; nothing was run, no GDS was
generated, no DRC/LVS was executed. Sibling state read:
`2AMLogic/gf180-gate-driver` at commit `a3fb3afcd48d` (2026-10-22), file
`layout/common/power_array_folded.py` (727 lines) and its
`test_power_array_folded.py`. This repo read at `cb0cc8c6`.

## Decision

**Record** (not adopt, not upstream). `layout/pass_array/gen_gds.py` remains
the generator of this regulator's pass array, and `power_array_folded.py`
stays where it is. `reuse.lock.json` gains an `in_tree` entry for
`pass_array` against `2AMLogic/gf180-gate-driver`, `status: recorded`,
pointing at this record. gate-driver#317's operator ruling ("keep" the
sibling generator) is respected: this record proposes no removal there.

### Comparison

| Axis | This repo, `layout/pass_array/` | `gf180-gate-driver`, `layout/common/power_array_folded.py` |
|---|---|---|
| Problem solved | One row of N abutted copies of a `W=70 um L=0.28 um nf=1` PCell plus an in-array Msense replica (`gen_gds.py:14-38`, `:124-135`) | Fold one very-high-`m` device across two physical rows so its single-row strip does not dominate the long axis, and tie the rows into one S/G/D net each (module docstring, `power_array_folded.py:1-60`) |
| Fold / tie scheme | None: single row. Gates share one poly bus; S/D regions are M1 straps stitched up through M2 (along the finger) to M3/M4/M5 rows (`gen_gds.py:40-68`) | Two rows only: alternate row Y-mirrored (`klt gen-compose` `orientation: mirror_y`) so gate pads face and tie by a plain box; S/D tied in side trunk columns on the same single metal role. `fold_rows` raises for `rows > 2` (`:160-185`) |
| EM-budget handling | `em_budget.py` measures strap widths / cut counts from the geometry just drawn and fails the build over a LEF `DCCURRENTDENSITY` limit; `test_pass_array.py` re-checks it. Binding row: via2 ISNS strap, 2.3x (`layout/records/20260924-213542-3ec8f89.md`) | None found: a grep of the file for `EM`/`budget`/`electromigr` returns no hit. One metal role carries S/G/D ties, so a 50 mA array could not be EM-checked with it as written (not traced beyond that grep) |
| DRC / LVS evidence | `layout/drclvs.py --cell pass_array`; committed record 20260924-213542-3ec8f89: DRC clean on both decks, LVS MATCH (`layout/floorplan.md` §3.3), plus LVS negative controls | Connectivity only: `fold_connectivity_verdict` over `klt extract` (`:545`), unit-tested with tied / untied / partially-tied cases. No DRC or LVS record for a folded array was found in the sibling's `layout/drc`, `layout/lvs` file lists (those cover `gate_driver_core`); its README states the module has no caller yet |
| Replica / sensing | Msense = `M_SENSE` cells of the same unit cell at the centroid, drain on `ISNS` isolated by a diffusion break, ratio `N_UNITS / M_SENSE` asserted (`gen_gds.py:346-352`) | None; no notion of a sense replica |
| Guard ring | Drawn here: one n-well ring tied to VIN (`gen_gds.py:413`) | Not drawn (`dummy: 0`; bulk handling is the caller's) |
| Parameters | Constants `N_UNITS`, `M_SENSE`, `REPLICA_RATIO`, `UNIT_PARAMS` edited in the file; no CLI for width | CLI/kwargs: `w_um`, `l_um`, `fingers`, `rows` in {1,2}, flavor, voltage flavor, `gap_um`, `trunk_margin_um` |
| Runtime | Raw KLayout script (`klayout -b -r`), PDK `pfet` PCell, no `klt` | `klt gen mos_array` + `klt gen-compose` from Python, generic over nfet/pfet |

### Is the width reachable by `N_UNITS` alone?

Mostly, but not by that constant alone. `Mpass` width is `N_UNITS * 70 um`
(40 -> 2800 um), so any even `N_UNITS` moves it in 140 um steps; the drawn
array is 36.6 x 72.96 um (`layout/records/20260924-213542-3ec8f89.md`), whose
long axis is the 70 um finger, not the finger count. At the widths #483 is
discussing (<= 2.8 mm), a single row is not too wide on any axis, so a fold
buys nothing. Two couplings stop `N_UNITS` being a one-line change:
`N_UNITS / M_SENSE` must equal `REPLICA_RATIO` (`gen_gds.py:348`), which is
asserted against the 40:1 replica ratio in `design/ldo_ilimit.sch`, and
`test_pass_array.py` pins `N_UNITS`, `REPLICA_RATIO` and the frozen EM
geometry to 40 (`:129-146`, `:237`). So a width change is a deliberate edit of
those pinned values together with the schematic's `W=`, not a parameter. A
width that is not a multiple of 40 units would also move the replica ratio
and is a design decision for #483, not for this record. The recommendation
holds for every option #483 lists.

### Assessment of the three outcomes

- **Adopt** `power_array_folded` as the pass array: no. It has no sense
  replica, no guard ring, no EM check and no DRC/LVS record, so adopting it
  would mean re-adding exactly the parts this repo's evidence was spent on
  (#285); and its one distinctive feature, the two-row fold, solves a
  floorplan problem this array does not have.
- **Upstream** (move the LDO scheme into `2AMLogic/klayout-tools`): not
  yet. The reusable part of this generator is the in-array replica plus the
  EM-gated metal stack, but it is a raw KLayout script bound to one PCell and
  one `floorplan.md`; generalising it is a tool design effort with a single
  caller. If a second block needs a replica-in-array or an EM-gated array, file
  the gap then, generically. No friction issue is filed from this record.
- **Record**: yes. The two are complementary, not rival, and the lock file
  should say so. Confirmed from the code: the LDO cell carries the replica,
  EM proof and guard ring that the folded generator lacks; the folded
  generator carries a fold/tie scheme this array never needs.

## Alternatives considered

- **Build a merged generator now** -- the ratified layout is out of scope for
  this issue and #483 is unresolved; a merge written before the width settles
  would be re-written.
- **Leave unrecorded** -- the question resurfaces at every reuse sweep, as
  `error_amp` did before DR-0038.

## Consequences

- `reuse.lock.json` gets one more `in_tree` entry; nothing in `layout/`,
  `design/` or the spec table changes, and no testbench or corner set changes.
- #483 proceeds on `layout/pass_array/` regardless of which of its options the
  operator picks; this record neither constrains nor depends on that choice.
- **Revisit trigger**: if the pass device ever needs a second physical row
  (e.g. a width or aspect-ratio change far beyond today's 36.6 x 72.96 um
  footprint), or if `power_array_folded` gains an EM check and a DRC/LVS
  record, supersede this record with a new one.
- The sibling's `layout/README.md` carries its own "kept on purpose" text
  (gate-driver#317); this record adds the LDO-side reason and is cross-posted
  there as a comment. The sibling repo is not edited from here.
- Bad consequence: two generators for a multi-finger power array stay
  maintained; accepted until the revisit trigger fires.
