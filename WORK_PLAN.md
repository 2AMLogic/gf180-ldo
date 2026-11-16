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
- **#465**: sim: re-qualify loop-stability and soft-start reference records at open_pdks f6eeac7 (part of #430)
- **#623**: signoff/check.sh: name the stale pinned artifact and offer re-attest, not --write
- **#635**: Remove .loom/manifest.json.tmp: a tracked, truncated atomic-write leftover that .gitignore:95 already covers
- **#639**: sim: the three remaining os.environ.setdefault("PDK_ROOT", ...) sites can leave klt staging an un-pin-checked tree

## In Progress

Issues currently being built (`loom:building`).

- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8)
- **#483**: load-transient: 8 of 81 PVT points exceed the ratified 150 mV excursion on the DR-0037 DUT (old DUT passes 81/81 at the same pin)
- **#603**: Remove the per-file copies of the gf180mcu DRC rule minimums: define each rule once, as #588 did for the layer table
- **#609**: Render the record Environment block once: three copies have already drifted, one cites a sim/README.md section that does not exist
- **#613**: Remove six dead function parameters in sim/ that the correctness-only lint gate cannot see
- **#618**: Mint the record id once: handover_t15.py and ramp_ab.py hand-roll it from git rev-parse --short (8 chars at HEAD, vs the ratified 7) and drop the dirty-tree flag
- **#619**: Remove NgspiceRoot.matches_pin: dead property left behind by DR-0043's floor rewrite
- **#621**: Define the two loop sweeps' local-grid CLI block once in klt_grid.py: the help text drifted in 4 places and #366's -j cap reached 2 of 5 drivers
- **#625**: Define the path-loading idiom once: 21 hand-rolled importlib.util copies, and 10 of them skip the sys.modules step the other 11 take
- **#631**: Stop offering --param on the four klt_run.py benches that never read it: add_ab_args declares it for every wrapper, only tb_adapter consumes it

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#620**: refactor(sim): drop six parameters no caller supplies and no body reads
- **#624**: refactor: mint the sim record id through the harness in all four drivers
- **#636**: refactor: load path-imported scripts through one harness.load_script helper
- **#640**: fix: declare --param only in tb_adapter, the wrapper that reads it
- **#643**: refactor: transcribe the gf180mcu DRC rule minimums once, in layout/drc_rules.py
- **#650**: refactor: drop dead NgspiceRoot.matches_pin; docstring now states floor semantics

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

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
- **#612**: klt_record's old-vs-new section asserts a hard-coded backend/PDK delta that is now false on every record *(curated)*
- **#617**: signoff/README.md: the per-item table and item 8 notes contradict the verdict of record on item 5 *(curated)*
- **#622**: DR-0044 item 5 justifies keeping the netlist snapshot committed with a defect (#597) that is now fixed *(curated)*
- **#623**: signoff/check.sh: name the stale pinned artifact and offer re-attest, not --write *(curated)*
- **#634**: bug: loop-stability --backend local fails with 'could not find a valid modelname' on the pass device *(curated)*
- **#635**: Remove .loom/manifest.json.tmp: a tracked, truncated atomic-write leftover that .gitignore:95 already covers *(curated)*
- **#639**: sim: the three remaining os.environ.setdefault("PDK_ROOT", ...) sites can leave klt staging an un-pin-checked tree *(curated)*
- **#645**: sim: give run_store_evidence.py DR-0044's kept-file split so a tb.json-free batch run can be stored *(curated)*

## Proposed (Architect / Hermit)

- **#170**: [Epic #542] 3A — gf180-ldo maturation + Challenge #5 brief *(architect)*
- **#595**: Remove the bash run.sh drivers and .control decks for current-limit and enable-shutdown: superseded by klt_run.py since October *(hermit)*
- **#607**: Define the deck preamble once: 8 byte-identical copies in the .spice.in templates, and DR-0025's wnflag=1 pin reached only 3 of them *(hermit)*
- **#608**: Split sim/soft-start-loop-gain/testbench/sweep.py: 34% of it is self-contained report rendering *(hermit)*
- **#610**: Remove the hand-rolled fleet-capacity retry loop in klt_batch.py: klt sim covers that refusal, and 89 of 98 committed requests set no capacity wait at all *(hermit)*
- **#630**: Give loop-stability's borrowed testbench surface a home in sim/harness/: 40 symbols reached by filesystem path, and the shim shadows this bench's own modules *(hermit)*
- **#637**: Define the compliance-limited load sink once: 10 hand copies in 9 decks, and #478's supply gate reached 1 of them *(hermit)*
- **#638**: Remove ab_loop_stability.py's hand-rolled ROW parser: reuse loop-stability sweep.py's own parse_row_fields() *(hermit)*
- **#649**: Relocate divider-specific record note out of generic drclvs.py (import-time cost, ~165 LOC) *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 2 |
| Ready (`loom:issue`) | 6 |
| In Progress (`loom:building`) | 10 |
| PRs awaiting review | 6 |
| Approved PRs awaiting merge | 0 |
| Curated | 22 |
| Architect / Hermit proposals | 9 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
