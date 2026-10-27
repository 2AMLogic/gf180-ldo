# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#502**: spec: propose limiting load-transient test condition to ESR >= 200 mOhm (DR-0041, ratification)

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
- **#366**: sim: route the remaining ratified-row PVT grid drivers (loop-stability, current-limit, enable-shutdown, soft-start) through klt_batch instead of local fan-out

## In Progress

Issues currently being built (`loom:building`).

- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8)
- **#312**: error_amp mixes ppolyf_u_1k and ppolyf_u_3k, which gf180mcu cannot build on one die — DR-0033 needs amending (blocks #284)
- **#483**: load-transient: 8 of 81 PVT points exceed the ratified 150 mV excursion on the DR-0037 DUT (old DUT passes 81/81 at the same pin)
- **#526**: Bump klayout-tools pin dc136150a49e → 0.8.0

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#502**: spec: propose limiting load-transient test condition to ESR >= 200 mOhm (DR-0041, ratification)
- **#527**: chore(signoff): pin klayout-tools to PyPI 0.8.0 and regenerate T1 record

## Proposed

Issues carrying `loom:curated`.

- **#16**: Post-layout extracted re-run of the full verification suite *(curated)*
- **#43**: Soft-start: two per-startup transients (loop acquisition and hand-over) still break the inrush and overshoot clauses *(curated)*
- **#173**: [Epic #542 follow-on] Layout the gf180-ldo LDO block (DRC/LVS-clean GDS) + post-layout PVT re-verification *(curated)*
- **#212**: Startup is 60× slower than TLV7xx because of the ramp bound, not the process — restate the Startup row as a startup-current budget at 1 µF and re-centre the soft-start ~5× faster *(curated)*
- **#259**: soft-start: recover the ~7.18 uA the FB-injection transconductor's degeneration branches burn after hand-over (Iq row binds at 1.29 uA, not 1.96 uA) *(curated)*
- **#284**: [Parent #173] Lay out the error amplifier as a DRC/LVS-clean cell registered in drclvs.py's CELLS *(curated)*
- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8) *(curated)*
- **#312**: error_amp mixes ppolyf_u_1k and ppolyf_u_3k, which gf180mcu cannot build on one die — DR-0033 needs amending (blocks #284) *(curated)*
- **#320**: ldo_ilimit's Fbias / ldo_softstart's Fss_ramp: replace the idealized VREF-derived bias-current mirror with a real device (blocks #290, #291) *(curated)*
- **#351**: Explain the 2x lower peak Icap / dV/dt at soft-start with the DR-0037 bias servo (142 vs 282 mA at tt/27C) *(curated)*
- **#366**: sim: route the remaining ratified-row PVT grid drivers (loop-stability, current-limit, enable-shutdown, soft-start) through klt_batch instead of local fan-out *(curated)*
- **#465**: sim: re-qualify loop-stability and soft-start reference records at open_pdks f6eeac7 (part of #430) *(curated)*
- **#483**: load-transient: 8 of 81 PVT points exceed the ratified 150 mV excursion on the DR-0037 DUT (old DUT passes 81/81 at the same pin) *(curated)*
- **#484**: mc-output-accuracy: divider-identity residual is ~2 uV (bound 1 uV) at all 45 points, and ff/sf 125C 3.63V leave the mean and sigma bounds, on the DR-0037 DUT *(curated)*
- **#501**: Recompensate the 50 mA loop for ceramic (low-ESR) output caps so the full Load-transient row can be restored (follow-up to #483) *(curated)*
- **#519**: load-transient: 81-point run at C_eff = 1 uF, ESR 200 and 500 mOhm, with a measured recovery time (evidence for DR-0042) *(curated)*
- **#523**: T1 item 5 (corner verification): declare the ratified row set and cite klt sim corner envelopes per row in the block manifest *(curated)*
- **#526**: Bump klayout-tools pin dc136150a49e → 0.8.0 *(curated)*

## Proposed (Architect / Hermit)

- **#170**: [Epic #542] 3A — gf180-ldo maturation + Challenge #5 brief *(architect)*
- **#388**: ci: report sim/ evidence growth per PR and cap runaway additions (append-only evidence can only grow) *(architect)*
- **#476**: Collapse quiescent-current klt_run.py onto tb_adapter (duplicate grade/main/PDK pin gap) *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 1 |
| Important | 2 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 4 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 2 |
| Curated | 18 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
