# Work Log Archive — 2026-09

Sections moved byte-for-byte from [WORK_LOG.md](../WORK_LOG.md) by `loom-daemon work-docs archive`.

### 2026-09-10

- **PR #197**: sim: soft-start hand-over loop-gain characterization, and the compensation recommendation for #191
- **Issue #196** (closed): sim: small-signal loop-gain / phase-margin characterization of the soft-start hand-over state with the device-level FB-injection element in the loop — the compensation analysis #191's Builder asked for and nobody filed

### 2026-09-06

- **PR #195**: soft-start(#191): device-level FB transconductor replaces Binj_ss, but destabilizes the hold-release transient at most of the PVT matrix
- **PR #194**: sim(harness): dedup run_point() across current-limit/enable-shutdown/soft-start
- **PR #192**: sim(soft-start): FB injection replaces the clamp comparator; the 4.7 uF inrush clause closes (#189)
- **PR #190**: spec(soft-start): DR-0022 — current-limit-clearance narrows above 1 µF; inrush split to #189
- **PR #188**: sim(soft-start): damp the clamp loop's acquisition transient with a nulling resistor (Rz_ss) (#43)
- **PR #186**: fix: enforce ngspice toolchain identity in --check-env, not just presence
- **PR #185**: fix: root-cause the loop-stability cross-invocation PM/GM drift as a toolchain-identity gap
- **PR #183**: sim(loop-stability): full 4536-point re-run against the seven-port ldo_core (post-#174/DR-0021)
- **PR #181**: sim(vref-transfer): VREF-to-VOUT transfer evidence and the reference accuracy-class budget
- **PR #180**: sim(soft-start): bisect the DR-0015 shelf and mint fresh Startup evidence
- **PR #179**: feat(design): promote VREF to a top-level ldo_core port, re-run PVT suite (DR-0021)
- **Issue #193** (closed): Dedup identical run_point() bash function across current-limit/enable-shutdown/soft-start run.sh
- **Issue #189** (closed): Soft-start: FB-injection redesign to close the 4.7 uF inrush clause (DR-0022's sibling circuit work)
- **Issue #184** (closed): docs/environment-setup.md: ngspice toolchain is not uniformly provisioned across builder hosts (found via #182)
- **Issue #182** (closed): sim/loop-stability: cross-invocation drift (~1-2 deg PM) at marginal points, same netlist, same PDK/ngspice hash
- **Issue #178** (closed): Reference-referred characterization: VREF-to-VOUT transfer and the tempco/noise/PSRR budget a real reference must meet
- **Issue #177** (closed): sim/soft-start's last recorded baseline predates the Mrza/Rza shelf (DR-0015) and looks obsolete-FAIL
- **Issue #176** (closed): Full 4536-point loop-stability re-run against the seven-port ldo_core (post-#174/DR-0021)
- **Issue #174** (closed): VREF is an internal ideal source, not a top-level port — needed for Chipalooza harness bandgap integration
