# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#682**: chore(loom): resync installed Loom to v0.19.1305

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
- **#655**: record_diff.py: scrub status-derived 'tier' so a stale-evidence-only diff is not reported as a residual
- **#687**: sim: klt_peak_run.py's summary.csv is overwritten per --part, so a split-part record stores only the last part's rows
- **#695**: sim: apply tb_adapter.refuse_protected_out to the three remaining caller-chosen output paths
- **#697**: gen_gds.py's resistor docstring still cites a `lvs_sub` deck switch that does not exist

## In Progress

Issues currently being built (`loom:building`).

- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8)
- **#483**: load-transient: 8 of 81 PVT points exceed the ratified 150 mV excursion on the DR-0037 DUT (old DUT passes 81/81 at the same pin)
- **#603**: Remove the per-file copies of the gf180mcu DRC rule minimums: define each rule once, as #588 did for the layer table
- **#609**: Render the record Environment block once: three copies have already drifted, one cites a sim/README.md section that does not exist
- **#625**: Define the path-loading idiom once: 21 hand-rolled importlib.util copies, and 10 of them skip the sys.modules step the other 11 take
- **#639**: sim: the three remaining os.environ.setdefault("PDK_ROOT", ...) sites can leave klt staging an un-pin-checked tree
- **#700**: sim: no structural test enforces the unique-name sibling-load rule across the 16 klt_run.py benches

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#701**: test(sim): enforce the unique-name sibling-load rule across testbench drivers

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#682**: chore(loom): resync installed Loom to v0.19.1305

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
- **#639**: sim: the three remaining os.environ.setdefault("PDK_ROOT", ...) sites can leave klt staging an un-pin-checked tree *(curated)*
- **#655**: record_diff.py: scrub status-derived 'tier' so a stale-evidence-only diff is not reported as a residual *(curated)*
- **#687**: sim: klt_peak_run.py's summary.csv is overwritten per --part, so a split-part record stores only the last part's rows *(curated)*
- **#695**: sim: apply tb_adapter.refuse_protected_out to the three remaining caller-chosen output paths *(curated)*
- **#697**: gen_gds.py's resistor docstring still cites a `lvs_sub` deck switch that does not exist *(curated)*
- **#700**: sim: no structural test enforces the unique-name sibling-load rule across the 16 klt_run.py benches *(curated)*

## Proposed (Architect / Hermit)

- **#170**: [Epic #542] 3A — gf180-ldo maturation + Challenge #5 brief *(architect)*
- **#595**: Remove the bash run.sh drivers and .control decks for current-limit and enable-shutdown: superseded by klt_run.py since October *(hermit)*
- **#607**: Define the deck preamble once: 8 byte-identical copies in the .spice.in templates, and DR-0025's wnflag=1 pin reached only 3 of them *(hermit)*
- **#608**: Split sim/soft-start-loop-gain/testbench/sweep.py: 34% of it is self-contained report rendering *(hermit)*
- **#610**: Remove the hand-rolled fleet-capacity retry loop in klt_batch.py: klt sim covers that refusal, and 89 of 98 committed requests set no capacity wait at all *(hermit)*
- **#637**: Define the compliance-limited load sink once: 10 hand copies in 9 decks, and #478's supply gate reached 1 of them *(hermit)*
- **#649**: Relocate divider-specific record note out of generic drclvs.py (import-time cost, 60 LOC) *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 1 |
| Important | 2 |
| Ready (`loom:issue`) | 7 |
| In Progress (`loom:building`) | 7 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 1 |
| Curated | 20 |
| Architect / Hermit proposals | 7 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
