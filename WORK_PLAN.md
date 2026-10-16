# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#431**: feat(sim): pin PDK to open_pdks f6eeac7 via ciel and refuse mismatched trees
- **#434**: Bump Repo Skills 0.24.1 -> 0.24.3

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8)

## Important

`loom:important`; taken before unlabelled work.

- **#312**: error_amp mixes ppolyf_u_1k and ppolyf_u_3k, which gf180mcu cannot build on one die — DR-0033 needs amending (blocks #284)
- **#320**: ldo_ilimit's Fbias / ldo_softstart's Fss_ramp: replace the idealized VREF-derived bias-current mirror with a real device (blocks #290, #291)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#302**: soft-start: make the FB-injection element's settled residual supply-independent, so the ratified 50 dB PSRR row closes (DR-0031 / T8)
- **#312**: error_amp mixes ppolyf_u_1k and ppolyf_u_3k, which gf180mcu cannot build on one die — DR-0033 needs amending (blocks #284)

## In Progress

Issues currently being built (`loom:building`).

- **#429**: Re-pin open_pdks to f6eeac7: ciel install, PDK search + revision check (phase 1 of #428)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#431**: feat(sim): pin PDK to open_pdks f6eeac7 via ciel and refuse mismatched trees
- **#434**: Bump Repo Skills 0.24.1 -> 0.24.3

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
- **#429**: Re-pin open_pdks to f6eeac7: ciel install, PDK search + revision check (phase 1 of #428) *(curated)*

## Proposed (Architect / Hermit)

- **#170**: [Epic #542] 3A — gf180-ldo maturation + Challenge #5 brief *(architect)*
- **#388**: ci: report sim/ evidence growth per PR and cap runaway additions (append-only evidence can only grow) *(architect)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 2 |
| Very important | 1 |
| Important | 2 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 2 |
| Curated | 11 |
| Architect / Hermit proposals | 2 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
