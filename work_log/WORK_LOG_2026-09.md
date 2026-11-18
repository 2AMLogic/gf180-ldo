# Work Log Archive — 2026-09

Sections moved byte-for-byte from [WORK_LOG.md](../WORK_LOG.md) by `loom-daemon work-docs archive`.

### 2026-09-18

- **PR #258**: spec: propose DR-0026, make the soft-start injection accurate by local feedback rather than by scaling the divider
- **PR #256**: fix: render every bold clause of a split Overall verdict in the rollup
- **PR #255**: spec: ratify DR-0025's per-finger model-bin convention and deck-level wnflag pin
- **PR #252**: fix: make the ngspice identity check pin-aware, not brew-prefix-aware
- **PR #250**: soft-start: cascode the FB-injection mirror per DR-0023, with full PVT evidence (#246)
- **PR #228**: spec: propose ratifying DR-0024's 1 uF startup-current budget + 1.8 ms settling window
- **PR #217**: spec: propose ratifying DR-0023's cascoded soft-start injection mirror topology
- **Issue #251** (closed): sim: CHARACTERIZATION.md drops every FAIL clause of a record whose Overall verdict spans more than one bold run
- **Issue #249** (closed): spec: decide the R4 lever for the soft-start injection element's absolute accuracy (T1-T4 unreachable by cascoding alone)
- **Issue #248** (closed): sim: the ngspice toolchain-identity check is inverted once Homebrew moves past the pinned 46_1
- **Issue #247** (closed): sim: the ngspice toolchain-identity check is inverted once Homebrew moves past the pinned 46_1
- **Issue #246** (closed): Implement DR-0023's cascoded soft-start injection mirror (Mgmo_ss/Mgmr_ss) and re-run sim/soft-start
- **Issue #219** (closed): spec: propose ratifying DR-0025's per-finger model-bin convention and deck-level wnflag pin
- **Issue #191** (closed): Soft start: replace the idealized FB-injection source (Binj_ss) with a device-level transconductor
- **Issue #187** (closed): Soft-start: inrush and current-limit clearance still fail at the 4.7 uF end of DR-0001's capacitor window

### 2026-09-16

- **PR #245**: sim(startup): re-judge tb.json checks against DR-0006's ratified 6 ms bound
- **PR #244**: fix(sim/harness): catch undefined-vector .let/v(...) as fatal (#242)
- **PR #243**: fix(sim/soft-start-loop-gain): rewrite device/binj narrative as cap-resize A/B, retire has_gmsum
- **PR #241**: fix: widen merge-pr.sh closing-keyword regex for colon-adjacent form
- **PR #240**: fix(sim/soft-start-loop-gain): drop dead acopen-fb-inj/acshort-gmsum attribution rows (#234)
- **PR #238**: sim(startup): re-run full PVT against current main's DUT, confirm DR-0006's 6 ms bound holds
- **PR #236**: docs(sim/harness): document -j/--timeout override for Gear-integration benches
- **PR #233**: fix(soft-start): revert device-level FB transconductor to Binj_ss (issue #231)
- **Issue #242** (closed): sim/harness: run_ngspice_deck()'s FATAL_LOG_PATTERNS misses ngspice's "no such variable" wording
- **Issue #239** (closed): sim/soft-start-loop-gain: device/binj is now a DR-0024 cap-resize A/B, not an injection-element A/B (render_record narrative + hand-over GMSUM bug)
- **Issue #237** (closed): merge-pr.sh champion:hold-state pipefail fix (#224/#230) regressed via resync (64fe646)
- **Issue #235** (closed): merge-pr.sh's closing-keyword detector misses colon-adjacent `fix: #N` — false-close self-heal gap (recurred on #191)
- **Issue #234** (closed): sim/soft-start-loop-gain: acopen-fb-inj and acshort-gmsum no longer measure anything after #231's Binj_ss revert
- **Issue #232** (closed): sim/startup: default -j/--timeout causes mass CPU-contention timeouts on multi-core hosts
- **Issue #231** (closed): sim/startup regresses: ff/sf high-temp/voltage corners no longer settle within 6 ms (blocks #128)
- **Issue #220** (closed): sim: DR-0006's 6 ms startup bound may no longer hold — the post-#195/#197 DUT settles 1.455x slower than the netlist it was measured against
- **Issue #128** (closed): Re-run sim/startup with tb.json's checks at 6 ms once DR-0006 ratifies

### 2026-09-15

- **PR #230**: fix: guard unmatched grep -o in champion:hold-state staleness check (#224)
- **PR #229**: spec: mark DR-0022's clearance-at-1uF pass-count as stale
- **PR #226**: ci: run a pass-device-bearing corner in pvt-smoke (verify wnflag=1 on ngspice-42/47)
- **PR #225**: sim(soft-start): confirm DR-0024's resize is a no-op on Iq and loop-stability
- **PR #223**: spec: propose 1 uF startup-current budget + ~5x soft-start resize (DR-0024)
- **PR #222**: spec: pin gf180mcu model-bin selection in the deck and root-cause it (DR-0025)
- **PR #218**: sim: regenerate CHARACTERIZATION.md and add CI staleness check
- **PR #215**: spec: propose DR-0023, cascode the soft-start injection mirror
- **PR #199**: spec: propose ratifying DR-0018's narrowed Stability envelope (+ DR-0007 hold-condition note)
- **PR #137**: spec: propose ratifying DR-0005's 62-95 mA current-limit window
- **Issue #227** (closed): spec: DR-0022's clearance-at-1uF evidence is stale against issue #191's fresher regression data
- **Issue #224** (closed): merge-pr.sh silently exits 1 on every merge when no champion:hold-state comment exists (pipefail bug)
- **Issue #221** (closed): sim: verify the deck-level '.options wnflag=1' bin pin on ngspice-42 and ngspice-47 (only 46 is covered by DR-0025)
- **Issue #216** (closed): sim/CHARACTERIZATION.md is stale against main's own netlist — regenerate after the DR-0005/DR-0006 ratifications and re-point note references
- **Issue #214** (closed): ngspice model-bin resolution for XMpass (pfet_03v3, W=2000u/nf=40) is unverified and build-dependent; every large-W-device sim/ record may rest on an unpinned bin choice
- **Issue #198** (closed): Cut the DR-0018 ratification PR (narrow Stability envelope to 1 µF nominal + DR-0007 status update)
- **Issue #105** (closed): Operator decision: ratify, reject, or revise DR-0005 (current-limit window)

### 2026-09-14

- **PR #213**: refactor(sim): consolidate current-limit/enable-shutdown run_point() into a shared harness_run_pvt_point
- **PR #127**: spec: propose ratifying DR-0006's 6 ms startup settling window
- **Issue #211** (closed): Remove duplicate run_point() in current-limit/enable-shutdown run.sh: consolidate the PVT-point wrapper
- **Issue #106** (closed): Operator decision: ratify, reject, or revise DR-0006 (startup settling window)

### 2026-09-13

- **PR #210**: refactor: dedup ngspice run+validate logic into run_ngspice_deck()
- **PR #208**: Dedup PDK-discovery and corner_sections() codegen blocks across the four sim testbenches
- **PR #206**: Dedup parse_row_fields() between loop-stability and soft-start-loop-gain sweep.py
- **PR #205**: Dedup op-point-sanity's run_point(): reuse sim/harness/lib/run_point.sh
- **Issue #209** (closed): Dedup ngspice run+validate logic: shared helper for loop-stability and soft-start-loop-gain sweeps
- **Issue #207** (closed): Dedup PDK-discovery and corner_sections() codegen blocks across the four sim testbenches
- **Issue #204** (closed): ngspice 'could not find a valid modelname' on all four .include-based testbenches (current-limit, enable-shutdown, op-point-sanity, likely soft-start)
- **Issue #203** (closed): Dedup parse_row_fields() between loop-stability and soft-start-loop-gain sweep.py
- **Issue #202** (closed): Dedup op-point-sanity's run_point(): reuse sim/harness/lib/run_point.sh

### 2026-09-12

- **PR #201**: Remove unused import: re in soft-start-loop-gain selftest
- **Issue #200** (closed): Remove unused import: re in sim/soft-start-loop-gain/testbench/selftest.py

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
