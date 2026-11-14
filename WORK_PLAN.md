# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8)

## Important

`loom:important`; taken before unlabelled work.

- **#312**: error_amp mixes ppolyf_u_1k and ppolyf_u_3k, which gf180mcu cannot build on one die — DR-0033 needs amending (blocks #284)
- **#320**: ldo_ilimit's Fbias / ldo_softstart's Fss_ramp: replace the idealized VREF-derived bias-current mirror with a real device (blocks #290, #291)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#79**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#312**: error_amp mixes ppolyf_u_1k and ppolyf_u_3k, which gf180mcu cannot build on one die — DR-0033 needs amending (blocks #284)
- **#603**: Remove the per-file copies of the gf180mcu DRC rule minimums: define each rule once, as #588 did for the layer table
- **#604**: Replace klt_record.py's frozen provenance narrative with the report data it already reads
- **#609**: Render the record Environment block once: three copies have already drifted, one cites a sim/README.md section that does not exist
- **#619**: Remove NgspiceRoot.matches_pin: dead property left behind by DR-0043's floor rewrite

## In Progress

Issues currently being built (`loom:building`).

- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8)
- **#483**: load-transient: 8 of 81 PVT points exceed the ratified 150 mV excursion on the DR-0037 DUT (old DUT passes 81/81 at the same pin)
- **#594**: Remove the klt-batch adapters' commit-the-bytes path: every evidence run since DR-0041 bypassed the artifact store (913 files in git, 0 manifests)
- **#606**: CI does not reject an added evidence record that still carries klt_record's `(to be written)` placeholder
- **#613**: Remove six dead function parameters in sim/ that the correctness-only lint gate cannot see
- **#618**: Mint the record id once: handover_t15.py and ramp_ab.py hand-roll it from git rev-parse --short (8 chars at HEAD, vs the ratified 7) and drop the dirty-tree flag
- **#621**: Define the two loop sweeps' local-grid CLI block once in klt_grid.py: the help text drifted in 4 places and #366's -j cap reached 2 of 5 drivers

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#614**: docs: roadmap as of 2026-11-13
- **#624**: refactor: mint the sim record id through the harness in all four drivers
- **#627**: refactor: define the loop sweeps' local-grid CLI block once in klt_grid.py

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#602**: feat(sim): route klt-batch adapter runs through the artifact store
- **#611**: ci: reject added records that still carry klt_record's "(to be written)"

## Proposed

Issues carrying `loom:curated`.

- **#16**: Post-layout extracted re-run of the full verification suite *(curated)*
- **#43**: Soft-start: two per-startup transients (loop acquisition and hand-over) still break the inrush and overshoot clauses *(curated)*
- **#168**: Champion: Merge-Risk Hold Digest *(curated)*
- **#173**: [Epic #542 follow-on] Layout the gf180-ldo LDO block (DRC/LVS-clean GDS) + post-layout PVT re-verification *(curated)*
- **#212**: Startup is 60× slower than TLV7xx because of the ramp bound, not the process — restate the Startup row as a startup-current budget at 1 µF and re-centre the soft-start ~5× faster *(curated)*
- **#259**: soft-start: recover the ~7.18 uA the FB-injection transconductor's degeneration branches burn after hand-over (Iq row binds at 1.29 uA, not 1.96 uA) *(curated)*
- **#284**: [Parent #173] Lay out the error amplifier as a DRC/LVS-clean cell registered in drclvs.py's CELLS *(curated)*
- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8) *(curated)*
- **#312**: error_amp mixes ppolyf_u_1k and ppolyf_u_3k, which gf180mcu cannot build on one die — DR-0033 needs amending (blocks #284) *(curated)*
- **#320**: ldo_ilimit's Fbias / ldo_softstart's Fss_ramp: replace the idealized VREF-derived bias-current mirror with a real device (blocks #290, #291) *(curated)*
- **#465**: sim: re-qualify loop-stability and soft-start reference records at open_pdks f6eeac7 (part of #430) *(curated)*
- **#483**: load-transient: 8 of 81 PVT points exceed the ratified 150 mV excursion on the DR-0037 DUT (old DUT passes 81/81 at the same pin) *(curated)*
- **#484**: mc-output-accuracy: divider-identity residual is ~2 uV (bound 1 uV) at all 45 points, and ff/sf 125C 3.63V leave the mean and sigma bounds, on the DR-0037 DUT *(curated)*
- **#501**: Recompensate the 50 mA loop for ceramic (low-ESR) output caps so the full Load-transient row can be restored (follow-up to #483) *(curated)*
- **#594**: Remove the klt-batch adapters' commit-the-bytes path: every evidence run since DR-0041 bypassed the artifact store (913 files in git, 0 manifests) *(curated)*
- **#606**: CI does not reject an added evidence record that still carries klt_record's `(to be written)` placeholder *(curated)*
- **#612**: klt_record's old-vs-new section asserts a hard-coded backend/PDK delta that is now false on every record *(curated)*
- **#615**: loop-stability sweep.py: stage model files and split each klt batch request under the whole-job ceiling *(curated)*
- **#616**: current-limit: tag the short-circuit power measurement with spec_row Thermal and cite it for T1 item 5 *(curated)*

## Proposed (Architect / Hermit)

- **#170**: [Epic #542] 3A — gf180-ldo maturation + Challenge #5 brief *(architect)*
- **#595**: Remove the bash run.sh drivers and .control decks for current-limit and enable-shutdown: superseded by klt_run.py since October *(hermit)*
- **#607**: Define the deck preamble once: 8 byte-identical copies in the .spice.in templates, and DR-0025's wnflag=1 pin reached only 3 of them *(hermit)*
- **#608**: Split sim/soft-start-loop-gain/testbench/sweep.py: 34% of it is self-contained report rendering *(hermit)*
- **#610**: Remove the hand-rolled fleet-capacity retry loop in klt_batch.py: klt sim covers that refusal, and 89 of 98 committed requests set no capacity wait at all *(hermit)*
- **#625**: Define the path-loading idiom once: 21 hand-rolled importlib.util copies, and 10 of them skip the sys.modules step the other 11 take *(hermit)*
- **#628**: Remove the second README spec-table parser: build_characterization_report.py forks the ratified parse_table *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 2 |
| Ready (`loom:issue`) | 6 |
| In Progress (`loom:building`) | 7 |
| PRs awaiting review | 3 |
| Approved PRs awaiting merge | 2 |
| Curated | 19 |
| Architect / Hermit proposals | 7 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
