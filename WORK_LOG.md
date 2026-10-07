# Work Log

Merged PRs and closed issues from the initial 30-day Guide review window.

### 2026-10-07

- **PR #354**: sim(soft-start): explain 2x lower startup peak Icap with DR-0037 servo (#351)
- **PR #350**: design: VREF-forcing V-to-I servo replaces Fbias/Fss_ramp (#320) [partial: single-point verification]

### 2026-10-06

- **PR #343**: fix(sim/loop-stability): drop dead Xsoftstart.CLG nodeset from dc_seed_lines
- **Issue #307** (closed): sim(loop-stability): dc_seed_lines() seeds Xsoftstart.CLG, a node ldo_softstart no longer has (it is HG now)

### 2026-10-03

- **PR #342**: layout: make testcell gen_gds.py assertions audible via _fail()
- **Issue #296** (closed): layout: testcell's gen_gds.py assertions are silent — klayout -b -r swallows SystemExit

### 2026-10-02

- **PR #341**: spec: ratify DR-0026 per operator review, correct header (#261)
- **Issue #303** (closed): PR #267 / DR-0028's branch-supply gating costs 5-7 dB of PSRR at the two corners the ratified row already fails
- **Issue #261** (closed): process: PR #258 (DR-0026 proposal) merged without the loom:operator human-approval gate every prior DR-ratification PR received

### 2026-09-30

- **PR #340**: feat: let handover_t15.py grade an arbitrary --dut-netlist, gated on --no-write
- **PR #338**: spec: the soft-start branch standing current comes back at the ramp ceiling, not at the branches (DR-0036)
- **PR #297**: layout: draw the feedback divider, and make an inapplicable LVS negative control a hard error
- **PR #171**: fix(ratification): remove unwrapped private-repo reference from market-key/SKILL.md
- **Issue #339** (closed): sim harness: soft-start's hand-over and transient drivers have no --dut-netlist override, so an A/B of the injection element needs a dirty design/ tree
- **Issue #287** (closed): [Parent #173] Lay out the current-limit and soft-start blocks as DRC/LVS-clean cells
- **Issue #286** (closed): [Parent #173] Lay out the feedback divider, and give drclvs.py LVS negative controls that work on an all-passive cell

### 2026-09-25

- **PR #337**: layout(#335): align floorplan §8.3 to DR-0030's updated margin
- **PR #336**: layout(#333): dedupe _fail/_rd/_load_pdk_pcells/_label into gen_gds_common.py
- **PR #334**: docs: restate DR-0030's contact EM margin at the shipped 2.8 mm device
- **Issue #335** (closed): floorplan §8.3's 'DR-0030 still quotes 25.0 µA / 5.2×' note goes stale once #332 lands
- **Issue #333** (closed): Remove duplicate _fail/_rd/_load_pdk_pcells/_label helpers in passives and pass_array gen_gds.py
- **Issue #332** (closed): DR-0030's contact-layer margin (25.0 µA / 5.2×) is stated at the superseded 2 mm device

### 2026-09-24

- **PR #331**: layout(#330): floorplan §3 re-keyed to the shipped 70 µm unit, and its IR split replaced by the measured one
- **PR #329**: layout(#285): the pass array and its Msense replica, as one DRC/LVS-clean cell
- **PR #328**: sim: scope the compliance-sink guarantee in five sibling decks and gate the missing vout half
- **PR #326**: sim(#304): the compliance sink never had a root to delete at fs_125c_3.63v -- it is a false convergence, and the claims now say so
- **Issue #330** (closed): floorplan §3 still describes the superseded 50 µm unit cell, and its IR split is 3.3 mΩ optimistic against the as-drawn array
- **Issue #325** (closed): sim: five sibling decks still assert the unscoped compliance-sink guarantee #304 disproved
- **Issue #304** (closed): sim/psrr-vs-freq lands on the sub-ground DC root at fs_125c_3.63v -- the compliance-limited sink does not delete it under FB injection
- **Issue #285** (closed): [Parent #173] Lay out the pass-device array and its Msense replica as one DRC/LVS-clean cell

### 2026-09-23

- **PR #323**: spec: propose a VIN-referenced soft-start ramp ceiling (DR-0035)
- **PR #322**: sim(standalone benches): propagate #310's pseudo-transient op gate to run_point.sh
- **PR #321**: fix: render the PDK's lvs_format-less passives as primitive R/C so LVS can read them
- **PR #319**: fix: prefer the newest evidence record matching the current DUT
- **PR #318**: sim(harness): make the pseudo-transient op rung fatal for DC benches
- **PR #316**: spec: the < 200 mV dropout stretch unlocks on margin DR-0033 already delivered — pass device to 2.8 mm (DR-0034)
- **PR #315**: design(error_amp): fix stale rejected-variant phase margin in §6.14's cost/benefit table
- **PR #314**: sim(harness): record which DC continuation rung each PVT corner's op solved on
- **PR #306**: design: a poly resistor's flavour follows its DC-current duty (DR-0033) — Rz/Rza/Rbufb go ppolyf_u_3k, Rbias cannot, and 17% of the core-area budget comes back
- **PR #305**: sim: the ratified PSRR row fails on main -- bisected to the soft-start injection element's settled residual, and why no sizing lever closes it (DR-0031)
- **PR #299**: refactor: share one sha256_of() helper instead of three copies
- **PR #295**: spec: keep the pass device at 2 mm — the 200 mV dropout stretch is capped by DR-0018's ratified gain margin, not by area
- **Issue #317** (closed): sim(standalone benches): the shared run_point.sh driver lacks the pseudo-transient op gate #310 added to the harness
- **Issue #313** (closed): drclvs.py cannot netlist any cell with a passive: the PDK's resistor/MIM-cap xschem symbols have no lvs_format
- **Issue #311** (closed): quiescent-current's #301 DC seed inverts on the post-DR-0033 DUT: it now CREATES the pseudo-transient corner the unseeded deck no longer has
- **Issue #310** (closed): sim(harness): a pseudo-transient `op` fallback is recorded as a converged DC point — FATAL_LOG_PATTERNS does not catch it
- **Issue #309** (closed): sim: quiescent-current's head record lost its res_ff/res_ss corners in DR-0033's swap, and error_amp.md §6.14 cites the rejected variant's phase margin
- **Issue #301** (closed): sim(quiescent-current): the ss/-40C/2.97V corner lands on the non-regulating DC branch, so the Iq row's verdict depends on the Newton path rather than on Iq
- **Issue #300** (closed): bug: the ratified PSRR row fails at three corners on current main (29.4 dB at ff/125C/3.63V against a > 50 dB floor), hidden behind a STALE record
- **Issue #298** (closed): Remove duplicate sha256_of() in toolchain-portability: reuse a shared helper
- **Issue #294** (closed): Unlock the < 200 mV dropout stretch: it needs ~1.9 dB more gain margin at 50 mA / 1 uF / 500 mOhm, not a wider pass device
- **Issue #289** (closed): sim/psrr-vs-freq FAILS 3/45 corners on current main (worst 29.4 dB vs the ratified 50 dB row) while its committed record still reads PASS — a stale-record regression, likely from the soft-start series
- **Issue #279** (closed): The amplifier's ppolyf_u_1k serpentines are 24% of the core area budget; ppolyf_u_3k would recover ~16% of it at a wider corner spread on a steep stability frontier
- **Issue #139** (closed): Pass device ships at W = 2 mm, half the sizing DR-0004's spec review assumed — now measurable, and it costs the < 200 mV dropout stretch at 9/27 corners

### 2026-09-22

- **PR #283**: layout: make the DRC/LVS flow drive any registered cell, on any host
- **PR #282**: spec: derive the tech LEF EM unit convention and book the CON contact gap as DR-0030
- **PR #281**: fix: grade Stability against DR-0018's ratified envelope, not DR-0001's original matrix
- **PR #280**: layout: add the floorplan, matching plan and a re-derivable core-area estimate
- **PR #277**: sim: re-verify DR-0018's ratified stability envelope on the current design (630/630)
- **PR #275**: chore: resync installed Loom surfaces
- **PR #274**: 2am: add reuse.lock.json in_tree entry for error_amp vs gf180-opamp
- **Issue #278** (closed): Electromigration limits are not published in the open gf180mcu PDK, so the 50 mA power-path metal sizing rests on a stated placeholder
- **Issue #276** (closed): Characterization rollup grades Stability against DR-0001's original matrix, not the ratified DR-0018 envelope
- **Issue #272** (closed): 2am: reuse rule 9 — in-tree error amplifier duplicates sibling canary gf180-opamp — add reuse.lock.json in_tree entry (evaluate), then adopt or record
- **Issue #51** (closed): LDO loop stability: close the 1-50 mA phase-margin gap via DR-0012's Candidate 2 (adaptive pass-device-replica bias)
- **Issue #15** (closed): Floorplan and matching plan (pass array, sense matching, Kelvin sensing)

### 2026-09-20

- **PR #271**: signoff: grade this block's T1 state from a klt manifest instead of hand-reading it
- **Issue #270** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read

### 2026-09-19

- **PR #269**: spec: renumber the soft-start branch-gating negative result DR-0027 -> DR-0029
- **PR #266**: Remove duplicate load() in soft-start-loop-gain: reuse loop-stability's
- **PR #264**: spec: propose DR-0027, a negative/partial result on gating soft-start's degeneration branches
- **PR #263**: spec: DR-0025's wnflag facts reproduce on ngspice-42/47 (DR-0027)
- **PR #262**: sim: list soft-start-loop-gain in the rollup and fail on any unmapped slug
- **PR #260**: sim: waive grid-level spread checks on a grid too small to define a spread (#253)
- **Issue #268** (closed): DR-0027 numbering collision: two decision records both landed as DR-0027 (PR #263, PR #264)
- **Issue #265** (closed): Remove duplicate load() in soft-start-loop-gain/testbench/compare_records.py: reuse loop-stability's
- **Issue #257** (closed): sim: build_characterization_report.py leaves sim/soft-start-loop-gain unmapped — its records appear in neither the rollup nor the appendix
- **Issue #254** (closed): spec: revisit DR-0025's `wnflag` bin-pin validation on ngspice majors other than 46 (#221's un-performed scope)
- **Issue #253** (closed): sim: `selftest.sh --quick` always FAILs stage 3 on a spread check a single point cannot satisfy

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
