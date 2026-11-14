# gf180-ldo roadmap

A low-dropout regulator on the gf180mcu open PDK, built on xschem, ngspice and
klayout-tools, with every claim backed by a committed testbench.

Status as of 2026-11-13, `main` @ `488b6b0a`.

This file says what comes next and why. The generated `WORK_PLAN.md` and the
graded [`signoff/records/t1-tier-report.json`](../signoff/records/t1-tier-report.json)
win where they disagree with it.

## Where it stands

The verdict of record reads **`tier: null`, T1 4 of 11 items met** against
klayout-tools' design-evidence ladder. Item by item:

| # | Item | Status | What is behind it |
|---|---|---|---|
| 1 | Design sources | met | four xschem schematics and their derived netlists, attested (`signoff/inventory-item1.json`) |
| 2 | Layout | unmet | only `layout/pass_array/` and `layout/divider/` are drawn; no top-level cell |
| 3 | DRC clean | unmet | waits on item 2 |
| 4 | LVS clean | unmet | waits on item 2 |
| 5 | Corner verification | unmet, partial coverage | 4 of 16 ratified rows cited from limit-checked `klt sim` envelopes (#538, PR #556) |
| 6 | Monte Carlo evidence | unmet | `sim/mc-output-accuracy/` exists but is not a `klt yield` report (#449) |
| 7 | Post-layout verification | unmet | waits on item 2 (#16) |
| 8 | Characterization report | met | `sim/CHARACTERIZATION.md`, generated and CI-checked |
| 9 | Testbenches shipped | met | attested (`signoff/inventory-item9.json`) |
| 10 | Repo hygiene | met | attested (`signoff/inventory-item10.json`) |
| 11 | Power delivery | unmet | waits on items 2 and 4 (#524) |

Item 5, row by row, from `signoff/block-manifest.json` and
`sim/CHARACTERIZATION.md`:

- **Cited and passing (4):** Current limit, Dropout @ 50 mA, Load reg,
  Enable / shutdown.
- **Passing but not citable yet (2):** Thermal (no envelope carries a
  `Thermal` spec row) and Stability (PASS but STALE; re-run under #465, #327).
- **Failing or mixed (6):** PSRR, Line reg and Output (soft-start injection
  residual, DR-0031 and DR-0039, #302; Output also #484), Load transient
  (#483, #501), Iq (MIXED, #346), Startup (MIXED and STALE, #43, #345).
- **Not corner-simulable (4):** Input, Load, Output noise (waived by the
  spec), Area (a layout figure, #173).

Recent merges are harness consolidation (PRs #558, #582, #589, #598), not
design movement.

## Now

1. **Finish the three harness PRs in review.** Evidence bytes from the shared
   batch adapters go to the artifact store (#594, PR #602); the
   characterization report grades store-backed records (#597, PR #605); one
   deck-template renderer and netlist preflight for the hand-rolled drivers
   (#592, PR #599). Done when each PR merges with CI green.
2. **Make the loop-stability sweep runnable on the batch backend at the pinned
   PDK revision.** `sim/loop-stability/testbench/sweep.py` sends each request
   as one 63-unit job, above the whole-job ceiling, and does not stage model
   files (builder note on #465, 2026-11-13). Done when `run_grid_klt` sets
   `stage_model_inputs` and a `batch` split, with a unit test. No issue yet.
3. **Give the Thermal row a citable envelope.** `klt_run.py` in
   `sim/current-limit/testbench/` computes short-circuit power but tags only
   `Current limit`. Done when a limit-checked measurement tagged `Thermal`
   is minted and cited in `signoff/block-manifest.json` (item 5: 4 to 5
   cited rows). No issue yet.
4. **Bring `signoff/README.md`'s per-item table in line with the record.** Its
   item 5 row still says `no_evidence` and "nothing here is gradeable yet";
   the record says `partial_coverage` with four rows cited. No issue yet.
5. **Define each gf180mcu DRC rule minimum once in the layout code** (#603,
   proposed, not yet promoted). Done when the per-file copies read one table
   in `layout/gen_gds_common.py` and the layout unit tests pass.

## Next

- **Route the hand-rolled `klt_run.py` drivers through the artifact store**
  (#596) and **replace `klt_record.py`'s frozen provenance narrative** (#604):
  both after #594, which settles the layout they build on.
- **Re-qualify loop-stability and soft-start at open_pdks `f6eeac7`** (#465,
  then #430 and #428 close): after Now item 2, and a decision on how to run
  the 1512-shard grid. Done when new records supersede the stale Stability
  record and `sim/CHARACTERIZATION.md` reads Stability fresh.
- **Re-land the VIN-referenced soft-start ramp ceiling on the current DUT**
  (#302, DR-0035 and DR-0039; PR #344 is parked and conflicting). Done when
  `sim/psrr-vs-freq` and `sim/psrr-vs-freq-50ma` pass 45/45 and clean-tree
  startup, quiescent-current and loop-stability runs exist on the changed DUT.
  Targets PSRR and Line reg; releases #327, #345 and #346.
- **One H-Res poly flavour per die** (#312, PR #347 parked): `error_amp` still
  mixes `ppolyf_u_1k` and `ppolyf_u_3k` on `main`. Releases the error
  amplifier layout (#284), the LVS flavour check (#324) and the `klt yield`
  campaign for item 6 (#449).
- **Sub-block layouts**: error amplifier (#284, after #312), current limit
  (#290) and soft start (#291), both after #320. Each is done when its cell is
  registered in `layout/drclvs.py` and its `--cell` run reads DRC clean and
  LVS MATCH.

## Later

- **Top-level assembly** (#288, epic #173): needs #284, #290 and #291. Answers
  whether the as-built core area meets the < 0.1 mm2 Area row. Delivers items
  2, 3, 4 and 11 (#524).
- **Post-layout re-verification** (#16): needs #288. Which rows regress on the
  extracted netlist, and does each go back to layout or to a decision record.
- **Low-ESR recompensation** (#501): can the 50 mA loop be stable with a bare
  ceramic output capacitor at the DR-0034 pass width without a new topology.
- **Startup speed and standing current** (#212, #259, #43): what startup
  current budget at 1 uF the Startup row should state.
- **Challenge #5 maturation** (#170): follows #173.

## Blocked and waiting

- **Load-transient row** (#483, PR #502): narrowing the test condition to
  ESR >= 200 mOhm is a ratification PR, not mergeable on review alone; the
  1 uF evidence it asked for landed in PR #564.
- **Bias generator evidence** (#320): held since 2026-10-17 until the batch
  submission path exposes job state and retains results; a probe on 2026-11-05
  still returned nothing. The upstream issues it cites (klayout-tools#2847,
  #2851, #3065) are closed, so the hold needs a fresh reading.
- **PR #344** (#302) is held until the runs listed under Next exist on a
  clean tree; removing the bash drivers (#595) waits on an operator decision.
- **Decision records**: DR-0027 onward all read `proposed` in
  `spec/decision-records/README.md`, including ones the current DUT already
  embodies (DR-0033, DR-0034, DR-0037).

The design-critical path (PSRR, load transient, layout) is not dispatchable
today: each step sits behind a ruling or a parked PR above. Only harness and
evidence work is, Now items 2 to 5.

## Not planned

- On-chip thermal shutdown or foldback (README notes 5 and 9), and an
  output-noise bound (waived, README note 7).
- Replacing `error_amp` or the pass-array generator with a sibling block's
  (DR-0038, DR-0040).
- Relaxing a ratified row to make a result pass; that takes a decision record.
