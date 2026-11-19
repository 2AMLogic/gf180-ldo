# Work Plan

<!-- guide:plan-body:start -->
_Generated: 2026-11-19T21:10:00Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8)

## Important

`loom:important`; taken before unlabelled work.

- **#312**: error_amp mixes ppolyf_u_1k and ppolyf_u_3k, which gf180mcu cannot build on one die — DR-0033 needs amending (blocks #284)
- **#320**: ldo_ilimit's Fbias / ldo_softstart's Fss_ramp: replace the idealized VREF-derived bias-current mirror with a real device (blocks #290, #291) *(held)*
- **#465**: sim: re-qualify loop-stability and soft-start reference records at open_pdks f6eeac7 (part of #430)

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

- **#79**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#312**: error_amp mixes ppolyf_u_1k and ppolyf_u_3k, which gf180mcu cannot build on one die — DR-0033 needs amending (blocks #284)
- **#465**: sim: re-qualify loop-stability and soft-start reference records at open_pdks f6eeac7 (part of #430)

## In Progress

Issues currently being built (`loom:building`).

- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8)
- **#483**: load-transient: 8 of 81 PVT points exceed the ratified 150 mV excursion on the DR-0037 DUT (old DUT passes 81/81 at the same pin)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#16**: Post-layout extracted re-run of the full verification suite *(curated)* *(held)*
- **#43**: Soft-start: two per-startup transients (loop acquisition and hand-over) still break the inrush and overshoot clauses *(curated)* *(held)*
- **#168**: Champion: Merge-Risk Hold Digest *(curated)* *(held)*
- **#173**: [Epic #542 follow-on] Layout the gf180-ldo LDO block (DRC/LVS-clean GDS) + post-layout PVT re-verification *(curated)* *(held)*
- **#212**: Startup is 60× slower than TLV7xx because of the ramp bound, not the process — restate the Startup row as a startup-current budget at 1 µF and re-centre the soft-start ~5× faster *(curated)* *(held)*
- **#259**: soft-start: recover the ~7.18 uA the FB-injection transconductor's degeneration branches burn after hand-over (Iq row binds at 1.29 uA, not 1.96 uA) *(curated)* *(held)*
- **#284**: [Parent #173] Lay out the error amplifier as a DRC/LVS-clean cell registered in drclvs.py's CELLS *(curated)* *(held)*
- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8) *(curated)*
- **#312**: error_amp mixes ppolyf_u_1k and ppolyf_u_3k, which gf180mcu cannot build on one die — DR-0033 needs amending (blocks #284) *(curated)*
- **#320**: ldo_ilimit's Fbias / ldo_softstart's Fss_ramp: replace the idealized VREF-derived bias-current mirror with a real device (blocks #290, #291) *(curated)* *(held)*
- **#465**: sim: re-qualify loop-stability and soft-start reference records at open_pdks f6eeac7 (part of #430) *(curated)*
- **#483**: load-transient: 8 of 81 PVT points exceed the ratified 150 mV excursion on the DR-0037 DUT (old DUT passes 81/81 at the same pin) *(curated)*
- **#484**: mc-output-accuracy: divider-identity residual is ~2 uV (bound 1 uV) at all 45 points, and ff/sf 125C 3.63V leave the mean and sigma bounds, on the DR-0037 DUT *(curated)* *(held)*
- **#501**: Recompensate the 50 mA loop for ceramic (low-ESR) output caps so the full Load-transient row can be restored (follow-up to #483) *(curated)* *(held)*
- **#743**: Merge queue: add the merge_group trigger and adapt the PR-metadata gates *(curated)* *(held)*
- **#746**: soft-start inrush-peak and peak-dV/dt per-corner values move at the f6eeac7 re-pin (envelope intact) *(curated)* *(held)*

## Proposed (Architect / Hermit)

- **#170**: [Epic #542] 3A — gf180-ldo maturation + Challenge #5 brief *(architect)* *(held)*
- **#595**: Remove the bash run.sh drivers and .control decks for current-limit and enable-shutdown: superseded by klt_run.py since October *(hermit)* *(held)*
- **#607**: Define the deck preamble once: 8 byte-identical copies in the .spice.in templates, and DR-0025's wnflag=1 pin reached only 3 of them *(hermit)* *(held)*
- **#610**: Remove the hand-rolled fleet-capacity retry loop in klt_batch.py: klt sim covers that refusal, and 89 of 98 committed requests set no capacity wait at all *(hermit)* *(held)*
- **#637**: Define the compliance-limited load sink once: 10 hand copies in 9 decks, and #478's supply gate reached 1 of them *(hermit)* *(held)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 3 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 3 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 0 |
| Curated | 16 |
| Architect / Hermit proposals | 5 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
