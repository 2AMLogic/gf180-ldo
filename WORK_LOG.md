# Work Log

Merged PRs and closed issues from the initial 30-day Guide review window.

## Archives

- [2026-09](work_log/WORK_LOG_2026-09.md)

### 2026-11-17

- **Issue #721** (closed): Two live `.spice.in` deck templates still quote the pre-DR-0034 pass-device width W=2000u (#714's grep was py/md-only)
- **PR #725**: fix: quote post-DR-0034 pass width W=2800u in soft-start deck templates
- **Issue #723** (closed): test_load_script_sites: a locally-deleted tracked .py reports as a UTF-8 failure (and a null-byte file reports line `None`)
- **PR #724**: fix: give read_calls per-failure reasons; drop a None line number
- **Issue #716** (closed): test_load_script_sites guard: scope enumeration to tracked files and handle unparseable ones
- **PR #722**: fix: scope load-script-sites guard to tracked files, guarded parse
- **Issue #714** (closed): Record prose still quotes the pre-DR-0034 pass-device width W=2000u; the netlist is W=2800u
- **PR #718**: fix: quote the DR-0034 pass-device width W=2800u in record prose and probes
- **Issue #710** (closed): sim/harness: write_summary_csv's merge_key silently duplicates rows when a key column is not a string
- **PR #720**: fix(sim): refuse a non-str merge_key cell instead of silently duplicating rows
- **Issue #717** (closed): Cite CO.6a/CO.6b, not CO.6, for the 0.06 um Metal1 overlap of contact
- **PR #719**: docs(layout): cite CO.6a/CO.6b for the 0.06 um Metal1 contact overlap
- **PR #711**: chore(loom): resync installed Loom to v0.19.1306
- **Issue #603** (closed): Remove the per-file copies of the gf180mcu DRC rule minimums: define each rule once, as #588 did for the layer table
- **PR #643**: refactor: transcribe the gf180mcu DRC rule minimums once, in layout/drc_rules.py
- **Issue #695** (closed): sim: apply tb_adapter.refuse_protected_out to the three remaining caller-chosen output paths
- **PR #715**: fix(sim): refuse caller-chosen output paths inside append-only trees in three drivers
- **Issue #706** (closed): Re-consolidate 16 path-load sites that regrew after #625, and add the anti-regrowth guard
- **PR #712**: fix: route path loads through load_script and guard the idiom tree-wide
- **Issue #697** (closed): gen_gds.py's resistor docstring still cites a `lvs_sub` deck switch that does not exist
- **PR #713**: docs: cite the deck's hardcoded substrate net, not the dead lvs_sub switch
- **Issue #704** (closed): sim: klt_run.py's summary.csv is clobbered per --part, same bug #687 fixed in klt_peak_run.py
- **PR #708**: fix(sim): merge split-part rows in soft-start klt_run's summary.csv
- **Issue #649** (closed): Relocate divider-specific record note out of generic drclvs.py (import-time cost, 60 LOC)
- **PR #709**: refactor(layout): move the divider's --record note into layout/divider/, rendered lazily
- **Issue #655** (closed): record_diff.py: scrub status-derived 'tier' so a stale-evidence-only diff is not reported as a residual
- **PR #705**: fix(signoff): scrub derived top-level tier so a stale-evidence-only diff is not a residual
- **PR #703**: fix(sim): accumulate split-part rows in klt_peak_run's summary.csv
- **PR #701**: test(sim): enforce the unique-name sibling-load rule across testbench drivers
- **PR #636**: refactor: load path-imported scripts through one harness.load_script helper
- **Issue #700** (closed): sim: no structural test enforces the unique-name sibling-load rule across the 16 klt_run.py benches
- **Issue #687** (closed): sim: klt_peak_run.py's summary.csv is overwritten per --part, so a split-part record stores only the last part's rows
- **Issue #625** (closed): Define the path-loading idiom once: 21 hand-rolled importlib.util copies, and 10 of them skip the sys.modules step the other 11 take
- **PR #699**: fix(sim): load ss-loop-gain's klt_run under its unique name, dropping the last bare import
- **Issue #693** (closed): sim: ss-loop-gain sweep.py's bare `import klt_run` still leaks the name — soft-start's klt_peak_run wins the race, so the driver silently gets the wrong bench's klt_run
- **PR #692**: sim: hoist the append-only output refusal into tb_adapter and guard bias_acq's explicit --dest
- **Issue #686** (closed): sim: hoist the probe's append-only --out refusal into tb_adapter and apply it to bias_acq's explicit --dest
- **Issue #596** (closed): Route the hand-rolled klt_run.py drivers' batch evidence through the artifact store (605 of 913 post-DR-0041 files)
- **PR #696**: refactor(lvs): extract lvs_switches() and drop four switches the deck never reads
- **Issue #691** (closed): LVS switch dict passes four globals the pinned deck never reads (lvs_sub, scale, schematic_simplify, thr)
- **PR #690**: refactor(sim): home the shared loop-margin surface in sim/harness
- **PR #689**: fix(lvs): gate the MIM renderer to the flavour the run registers
- **PR #688**: docs: name klt_grid.DEFAULT_JOBS as the -j default in tb_startup.spice header
- **Issue #685** (closed): tb_startup.spice's -j advisory still names min(8, cpu_count) as the harness default after #626
- **PR #684**: fix(harness): take run_corners' -j default from klt_grid.DEFAULT_JOBS
- **PR #683**: sim: stage mc-output-accuracy and soft-start peak/bias drivers instead of committing
- **Issue #680** (closed): LVS: mapped MIM flavour is not cross-checked against the run's mim_cap switch, and CellSpec.simplify_extracted's comment still describes the pre-bump deck
- **PR #677**: sim: stage current-limit, enable-shutdown and soft-start klt runs instead of committing
- **PR #675**: fix(loop-stability): pin .options wnflag=1 so --backend local runs on any host
- **Issue #647** (closed): sim: route the four latent hand-rolled batch drivers (mc-output-accuracy, soft-start peak/bias_acq) through the store
- **Issue #646** (closed): sim: stage the current-limit, enable-shutdown and soft-start klt_run.py runs instead of committing them (all 673 hand-rolled-driver files as of 2026-11-15)
- **Issue #634** (closed): bug: loop-stability --backend local fails with 'could not find a valid modelname' on the pass device
- **Issue #630** (closed): Give loop-stability's borrowed testbench surface a home in sim/harness/: 40 symbols reached by filesystem path, and the shim shadows this bench's own modules
- **Issue #626** (closed): run_corners.py is the sixth local driver #366's -j cap never reached: sim/harness/cli.py still resolves -j to min(8, cpu_count())

### 2026-11-16

- **PR #656**: chore(loom): resync installed Loom to v0.19.1302
- **PR #679**: fix: pass the pinned LVS runset's switches explicitly and emit its MIM-cap device class
- **Issue #642** (closed): LVS mismatches on pass_array and passives with current toolchain (klayout 0.30.12 + pinned PDK), pre-existing on main
- **PR #676**: fix: refuse kept-envelope collisions before klt_record commits anything
- **Issue #662** (closed): sim: klt_record.main commits the record before install_kept's collision check can refuse
- **PR #672**: fix: soft-start record says ngspice/host bullets are above the Backend bullet
- **PR #671**: fix: signoff drift message renders the cell's own status instead of 'met'
- **Issue #668** (closed): signoff/readme_claims.py: _fmt() renders a reason-less 'unmet' table cell as 'met' in the drift message
- **Issue #667** (closed): soft-start record prose: the klt Backend bullet says the ngspice/host bullets are "below" it; they are above
- **PR #627**: refactor: define the loop sweeps' local-grid CLI block once in klt_grid.py
- **Issue #621** (closed): Define the two loop sweeps' local-grid CLI block once in klt_grid.py: the help text drifted in 4 places and #366's -j cap reached 2 of 5 drivers
- **PR #666**: refactor: read A/B driver ROW lines through the deck's strict parser
- **PR #665**: test: smoke-cover both drivers' render_record with structural environment assertions
- **PR #664**: docs: restate DR-0044's netlist-snapshot rationale on stronger-check grounds (#622)
- **PR #663**: feat: give run_store_evidence.py --kind corners DR-0044's kept-file split
- **PR #659**: fix: signoff README prose now matches the record; per-item table check added
- **PR #657**: Remove tracked .loom/manifest.json.tmp atomic-write leftover
- **PR #624**: refactor: mint the sim record id through the harness in all four drivers
- **Issue #658** (closed): Neither sweep driver's render_record is covered by any test: 0 call sites in both driver suites vs 14 for the harness path
- **Issue #645** (closed): sim: give run_store_evidence.py DR-0044's kept-file split so a tb.json-free batch run can be stored
- **Issue #638** (closed): Remove ab_loop_stability.py's hand-rolled ROW parser: reuse loop-stability sweep.py's own parse_row_fields()
- **Issue #635** (closed): Remove .loom/manifest.json.tmp: a tracked, truncated atomic-write leftover that .gitignore:95 already covers
- **Issue #622** (closed): DR-0044 item 5 justifies keeping the netlist snapshot committed with a defect (#597) that is now fixed
- **Issue #618** (closed): Mint the record id once: handover_t15.py and ramp_ab.py hand-roll it from git rev-parse --short (8 chars at HEAD, vs the ratified 7) and drop the dirty-tree flag
- **Issue #617** (closed): signoff/README.md: the per-item table and item 8 notes contradict the verdict of record on item 5
- **PR #654**: fix: drive the PDK's deck driver, whose layout replaced the old decks
- **PR #652**: fix: diagnose stale attested evidence as a re-attest case in check.sh
- **PR #650**: refactor: drop dead NgspiceRoot.matches_pin; docstring now states floor semantics
- **Issue #641** (closed): layout/drclvs.py stage 4 (PDK DRC deck) cannot run against the pinned open_pdks revision: the deck layout changed
- **Issue #623** (closed): signoff/check.sh: name the stale pinned artifact and offer re-attest, not --write
- **Issue #619** (closed): Remove NgspiceRoot.matches_pin: dead property left behind by DR-0043's floor rewrite
- **Issue #612** (closed): klt_record's old-vs-new section asserts a hard-coded backend/PDK delta that is now false on every record

### 2026-11-15

- **PR #653**: feat: limit-check short-circuit power as spec_row Thermal, cite it for T1 item 5
- **PR #640**: fix: declare --param only in tb_adapter, the wrapper that reads it
- **PR #620**: refactor(sim): drop six parameters no caller supplies and no body reads
- **Issue #631** (closed): Stop offering --param on the four klt_run.py benches that never read it: add_ab_args declares it for every wrapper, only tb_adapter consumes it
- **Issue #616** (closed): current-limit: tag the short-circuit power measurement with spec_row Thermal and cite it for T1 item 5
- **Issue #613** (closed): Remove six dead function parameters in sim/ that the correctness-only lint gate cannot see
- **PR #644**: fix: derive klt_record's provenance claims from run data, not frozen prose
- **PR #614**: docs: roadmap as of 2026-11-13
- **PR #602**: feat(sim): route klt-batch adapter runs through the artifact store
- **Issue #604** (closed): Replace klt_record.py's frozen provenance narrative with the report data it already reads
- **Issue #594** (closed): Remove the klt-batch adapters' commit-the-bytes path: every evidence run since DR-0041 bypassed the artifact store (913 files in git, 0 manifests)

### 2026-11-14

- **PR #633**: fix: stage models and split the loop-stability klt grid under the job ceiling
- **PR #632**: refactor: parse README's spec table through the ratified-spec gate's parser
- **PR #611**: ci: reject added records that still carry klt_record's "(to be written)"
- **Issue #628** (closed): Remove the second README spec-table parser: build_characterization_report.py forks the ratified parse_table
- **Issue #615** (closed): loop-stability sweep.py: stage model files and split each klt batch request under the whole-job ceiling
- **Issue #606** (closed): CI does not reject an added evidence record that still carries klt_record's `(to be written)` placeholder
- **PR #605**: fix: grade a store-backed record from its own committed netlist hashes
- **PR #599**: refactor(sim): one harness @TOKEN@ renderer and netlist preflight for eight drivers
- **Issue #597** (closed): build_characterization_report.py skips store-backed records: latest_record() needs a committed netlist snapshot
- **Issue #592** (closed): Remove the per-driver copies of the @TOKEN@ deck-template renderer and netlist-freshness preflight: one harness helper each (3 drifted guard regexes)

### 2026-11-13

- **PR #600**: test: move soft-start-loop-gain's selftest part 2 into the unit tests
- **PR #598**: refactor: define PDK_OPTION, DBU_UM and the GDS layer table once in gen_gds_common
- **PR #591**: fix: grade the current-limit bench against DR-0005's ratified window once
- **PR #590**: docs: grade soft-start against DR-0024 as ratified, not proposed
- **PR #589**: refactor: parse HOV lines with the shared strict parser, hoist the FB-node KCL
- **PR #583**: refactor: read the divider's geometry from plan.py in area_estimate
- **PR #582**: refactor: share delta-CSV writer and spread() between the two compare_records
- **Issue #593** (closed): Remove the duplicated simulator-free checks from soft-start-loop-gain selftest.py: delegate to the unit tests, and move its CI-invisible klt_run checks there
- **Issue #588** (closed): Remove the four per-generator copies of PDK_OPTION, DBU_UM and the GDS layer table: define once in gen_gds_common.py
- **Issue #587** (closed): Remove the expired "proposed, not yet ratified" wording from soft-start summarize.py and README: DR-0024 was ratified 2026-09-15
- **Issue #585** (closed): Remove the superseded 65-80 mA window from current-limit summarize.py: one ratified (DR-0005) bound shared with klt_run.grade()
- **Issue #584** (closed): Remove parse_hov_fields()'s hand-copied parser body in soft-start-loop-gain sweep.py: reuse harness.report.parse_row_fields()
- **Issue #581** (closed): Remove duplicate delta-CSV writer and spread() in soft-start-loop-gain/testbench/compare_records.py: reuse loop-stability's
- **Issue #580** (closed): Remove area_estimate.py's duplicate divider constants: read layout/divider/plan.py instead
- **PR #578**: refactor: drop three unread module constants and the parse_measurements wrapper
- **Issue #577** (closed): Remove three dead module constants and a test-only parse_measurements() wrapper

### 2026-11-12

- **PR #573**: chore: regenerate DR index and T1 tier report
- **PR #571**: Bump Repo Skills 0.25.10 -> 0.26.1
- **Issue #572** (closed): main CI red: decision README and T1 verdict of record are stale

### 2026-11-11

- **PR #569**: feat(sim): treat the ngspice pin as a major-version floor
- **Issue #568** (closed): runner: accept ngspice >= floor instead of exact ngspice-46 identity

### 2026-11-08

- **Issue #519** (closed): load-transient: 81-point run at C_eff = 1 uF, ESR 200 and 500 mOhm, with a measured recovery time (evidence for DR-0042)
- **PR #564**: feat: add 1 uF load-transient PVT records with recovery time

### 2026-11-07

- **PR #562**: Bump Repo Skills 0.25.1 -> 0.25.10

### 2026-11-06

- **PR #557**: feat: report files and bytes added per sim slug on PRs (non-blocking)
- **Issue #388** (closed): ci: report sim/ evidence growth per PR and cap runaway additions (append-only evidence can only grow)
- **PR #558**: refactor(layout): share one guard_ring in gen_gds_common
- **Issue #555** (closed): Deduplicate the two _guard_ring implementations into gen_gds_common
- **PR #553**: refactor: collapse quiescent-current klt_run onto tb_adapter
- **Issue #476** (closed): Collapse quiescent-current klt_run.py onto tb_adapter (duplicate grade/main/PDK pin gap)
- **PR #556**: feat: cite limit-checked sim envelopes as T1 item 5 evidence
- **Issue #552** (closed): T1 item 5: cite #538's limit-checked envelopes for Current limit, Dropout, Load reg, Enable/shutdown

### 2026-11-05

- **PR #550**: refactor: run xschem netlist export through klt netlist with a bounded timeout
- **Issue #549** (closed): Simplify: replace hand-rolled xschem subprocess in xschem_export.py with klt netlist (also adds missing timeout)
- **PR #546**: sim: soft-start startup peak is equal in both DUTs across the full PVT and EXTRA_CAPS matrix
- **Issue #351** (closed): Explain the 2x lower peak Icap / dV/dt at soft-start with the DR-0037 bias servo (142 vs 282 mA at tt/27C)

### 2026-11-04

- **PR #543**: sim(enable-shutdown): add 63-corner batch envelope with ratified limits
- **Issue #538** (closed): sim: declare limits and spec_row in klt_run front ends and re-mint envelopes for the passing T1 item-5 rows (current limit, enable/shutdown, dropout, load reg)
- **PR #541**: feat(sim): declare ratified limits and spec_row in klt envelopes
- **PR #539**: signoff: declare all ratified item-5 rows as gaps and grade against a klt git rev
- **Issue #523** (closed): T1 item 5 (corner verification): declare the ratified row set and cite klt sim corner envelopes per row in the block manifest

### 2026-11-02

- **Issue #366** (closed): sim: route the remaining ratified-row PVT grid drivers (loop-stability, current-limit, enable-shutdown, soft-start) through klt_batch instead of local fan-out

### 2026-10-31

- **PR #534**: Bump Repo Skills 0.24.7 -> 0.25.1

### 2026-10-27

- **PR #527**: chore(signoff): pin klayout-tools to PyPI 0.8.0 and regenerate T1 record
- **Issue #526** (closed): Bump klayout-tools pin dc136150a49e → 0.8.0

### 2026-10-25

- **PR #520**: sim: parameterise load-transient output network, add --param override and recovery measures

### 2026-10-24

- **PR #517**: refactor: restore helper names and wrap long line in gen_gds
- **Issue #510** (closed): pass_array/gen_gds.py: revert over-broad renames from #509 (_insert_merged_region, _contacts_per_merged_region)
- **PR #509**: refactor: hoist PCell-instantiate and merged-region helpers into gen_gds_common
- **Issue #508** (closed): Hoist repeated PCell-instantiate and merged-layer-region helpers into gen_gds_common.py

### 2026-10-23

- **PR #512**: feat: store new sim evidence via the artifact store, commit manifests only
- **Issue #511** (closed): Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact)

### 2026-10-22

- **PR #505**: feat(signoff): attest T1 items 1, 9 and 10 via klt signoff --attest
- **Issue #448** (closed): signoff: attest T1 items 1, 9 and 10 with klt signoff --attest envelopes
- **PR #490**: sim: attribute load-transient excursions to the DR-0034 pass width and the out-of-envelope output network
- **PR #499**: docs: record pass-array generator stays its own vs gate-driver power_array_folded (DR-0040)
- **Issue #498** (closed): Adopt or record: pass-device array generator vs gf180-gate-driver's folded power array (REUSE.md)

### 2026-10-21

- **PR #494**: refactor(sim): share klt grid retry driver between loop sweeps
- **Issue #492** (closed): Dedup run_grid_klt() DC-seed retry driver and backend selection between loop sweeps
- **PR #491**: refactor(sim): share ROW coercion and curve capture between loop sweeps
- **Issue #489** (closed): Dedup run_curve() and ROW coercion between loop-stability and soft-start-loop-gain sweep.py (falsy-zero NaN drift)
- **PR #487**: sim(mc-output-accuracy): attribute the divider-identity residual to the soft-start FB injection element
- **PR #481**: Bump Repo Skills 0.24.3 -> 0.24.7
- **PR #486**: sim: re-qualify load-transient, startup and mc-output-accuracy at f6eeac7 via klt sim
- **Issue #464** (closed): sim: add klt sim front ends and re-qualify the tb.json reference benches at open_pdks f6eeac7 (part of #430)
- **Issue #469** (closed): sim: re-qualify transient and Monte Carlo benches load-transient, startup, mc-output-accuracy at f6eeac7 via klt sim (part of #464)
- **PR #480**: sim: gate the psrr-vs-freq-50ma sink on the supply so ss/-40C/2.97V reaches 50 mA physically
- **PR #479**: fix(sim): reach DC bench operating points by continuation so the sweeps stay off the pass-device-off root
- **PR #477**: sim: re-qualify amp-openloop and the PSRR benches at open_pdks f6eeac7 on the batch fleet
- **PR #475**: spec: DR-0039 attributes the ff/125C line-regulation failure to the soft-start injection residual
- **PR #474**: sim: shared tb.json klt adapter and fleet re-qualification of three DC-sweep benches at open_pdks f6eeac7
- **PR #471**: refactor: share one ngspice measurement-line parser across harness consumers
- **PR #466**: sim: re-qualify iq, current-limit, enable-shutdown at open_pdks f6eeac7 via staged models
- **Issue #478** (closed): sim: psrr-vs-freq-50ma ss_-40c_2.97v converges to the pass-device-off state (Vout 0.145 V, 5.0 mA)
- **Issue #473** (closed): line-regulation: ff_125c_3.30v reads ~8.2 mV/V against the ratified 5 mV/V bound (design or spec decision; split from #472)
- **Issue #472** (closed): sim: three DC-sweep benches regress on the DR-0037 DUT (dropout knee guard x5, ss/-40C false convergence x2)
- **Issue #470** (closed): Consolidate three drifting ngspice measurement parsers into one
- **Issue #468** (closed): sim: re-qualify AC benches amp-openloop, psrr-dc, psrr-vs-freq, psrr-vs-freq-50ma at f6eeac7 via klt sim (part of #464)
- **Issue #467** (closed): sim: shared tb.json klt adapter + re-qualify dropout-vs-load, line-regulation, load-regulation at f6eeac7 (part of #464)
- **PR #462**: refactor: hoist grid rollup and CSV writer into harness.pvt_log
- **Issue #461** (closed): Dedup rollup/write_csv between enable-shutdown and current-limit summarize.py

### 2026-10-20

- **PR #431**: feat(sim): pin PDK to open_pdks f6eeac7 via ciel and refuse mismatched trees
- **Issue #429** (closed): Re-pin open_pdks to f6eeac7: ciel install, PDK search + revision check (phase 1 of #428)

### 2026-10-18

- **PR #458**: refactor(sim): share klt_run argparse prologue and summary.csv writer
- **Issue #456** (closed): Dedupe klt_run.py wrappers: shared argparse prologue and summary.csv writer

### 2026-10-17

- **PR #455**: sim(soft-start-loop-gain): add klt sim batch front end for the margin and hand-over decks
- **Issue #451** (closed): sim: batch front end for the soft-start-loop-gain Tian bench (follow-up to #366)
- **PR #452**: sim(loop-stability): add klt sim batch front end for the Tian loop-gain grid
- **PR #450**: sim: add klt sim batch front end for enable-shutdown PVT grid
- **PR #446**: sim: cap local jobs at 2 and require explicit backend for remaining grid drivers

### 2026-10-16

- **PR #442**: sim(soft-start): cap per-unit batch timeout at 3480 s to fit the fleet job ceiling (#320, partial)
- **PR #439**: sim(soft-start): complete the 63-point PVT matrix for the DR-0037 servo via per-process batch shards
- **PR #434**: Bump Repo Skills 0.24.1 -> 0.24.3

### 2026-10-15

- **PR #432**: sim(quiescent-current): 81-point PVT record for the DR-0037 bias servo (#320, partial)
- **PR #427**: test: disable git auto-maintenance in temp-repo test fixtures
- **PR #425**: sim(current-limit): full PVT record for the DR-0037 bias servo (#320, partial)
- **PR #424**: Bump Repo Skills 0.19.5 -> 0.24.1
- **PR #419**: fix(harness): validate manifest checks at load (#418)
- **PR #380**: fix(sim): protect frozen netlist snapshots with the append-only guard
- **Issue #426** (closed): test flake: test_lock_note_text_tamper_fails errors on temp-dir cleanup (Directory not empty)
- **Issue #418** (closed): sim: reject malformed check definitions before a PVT run
- **Issue #378** (closed): Protect frozen DUT netlist snapshots with the append-only evidence guard
- **Issue #374** (closed): sim: phase 2 of #366 - route current-limit, enable-shutdown, soft-start, soft-start-loop-gain grid drivers through klt_batch

### 2026-10-14

- **Issue #293** (closed): README: embed the fleet burndown chart (one line)

### 2026-10-13

- **PR #400**: ci: fail when README T1 tier/count prose disagrees with the verdict of record
- **Issue #398** (closed): ci: fail when README T1 tier/count prose disagrees with signoff/records/t1-tier-report.json

### 2026-10-12

- **PR #423**: sim: make append-only record writes atomic under concurrent writers
- **PR #421**: fix(sim): fail closed on non-finite measurements and statistics (#420)
- **PR #417**: spec: extend the amendment guard to ratified README notes
- **PR #415**: fix(ci): size nightly startup smoke budget from measurement (#409)
- **PR #414**: fix(ci): cover top-level layout/records in host-path guard (#413)
- **PR #412**: fix(sim): require complete unique stability-matrix coverage before row PASS
- **Issue #422** (closed): sim: make append-only record writes atomic under concurrent writers
- **Issue #420** (closed): sim: prevent measurement overflow from silently passing spread checks
- **Issue #416** (closed): spec: extend the amendment guard to ratified README notes
- **Issue #413** (closed): ci: include top-level layout records in the host-path evidence guard
- **Issue #411** (closed): Auditor: CI reader counts superseded cancelled checks as failures
- **Issue #410** (closed): Require complete, unique stability-matrix coverage before the characterization row can PASS
- **Issue #409** (closed): Build/runtime failure on main: nightly startup smoke times out after 300 seconds

### 2026-10-10

- **PR #407**: sim: reject failed ngspice runs even when all generic PVT measurements parse
- **Issue #406** (closed): sim: reject failed ngspice runs even when all generic PVT measurements parse

### 2026-10-09

- **PR #404**: ci: pin the ratified README spec table behind a lock and DR amendments
- **PR #403**: ci: harden ci.yml (permissions, concurrency, timeouts, pin uv/volare)
- **Issue #397** (closed): ci: pin the ratified README spec table so a row cannot change without a decision record
- **Issue #402** (closed): ci: harden ci.yml (least-privilege permissions, concurrency, timeouts, pin uv/volare)

### 2026-10-08

- **PR #394**: Bind characterization freshness to the designated DUT
- **PR #392**: spec: index design citations of unratified decision records (#387)
- **PR #389**: spec: DR-0038 resolves error_amp reuse 'evaluate' (keep own)
- **PR #386**: test: golden-record unit tests for the sim rollup scripts
- **PR #385**: docs: README repository layout lists every tracked top-level path (#383)
- **PR #382**: ci: adopt correctness-only ruff (F+E9) lint gate
- **PR #379**: Dedupe gen_gds helpers: route divider and testcell through gen_gds_common (#370)
- **PR #375**: sim(loop-stability): cap local jobs at 2, require explicit --backend local (Part of #366)
- **PR #373**: fix(sim): stop embedding absolute host paths in records (#365)
- **PR #372**: ci: enforce append-only evidence rule at PR level
- **PR #369**: Generate status index for spec/decision-records (#362)
- **PR #368**: docs(signoff): README reflects the two drawn layout cells (Part of #79)
- **PR #364**: Enforce pinned xschem 3.4.7 in netlist export (#361)
- **PR #360**: sim(soft-start): bias-acquisition characterization of both DR-0037 servos (#352)
- **Issue #393** (closed): Bind characterization freshness to the designated DUT
- **Issue #387** (closed): Cross-check design/ schematic DR citations against decision-record status (surface load-bearing unratified records)
- **Issue #384** (closed): Resolve reuse.lock.json 'evaluate' for error_amp vs gf180-opamp with a decision record
- **Issue #381** (closed): Unit-test the sim rollup scripts (summarize.py / peak_analyze.py) against committed raw logs
- **Issue #383** (closed): README: Repository layout block omits signoff/, ratification/, docs/, reuse.lock.json
- **Issue #377** (closed): ci: adopt a correctness-only Python lint gate (ruff F+E9) in place of the no-op lint script
- **Issue #370** (closed): Dedupe gen_gds helpers: route divider and testcell through gen_gds_common.py
- **Issue #365** (closed): sim harness: records embed absolute host paths (home dirs, worktree paths) into public append-only evidence
- **Issue #371** (closed): ci: enforce sim/ append-only evidence rule at PR level (no modify/delete/rename of committed records)
- **Issue #362** (closed): Generate a status index for spec/decision-records (23 of 36 records are still 'proposed')
- **Issue #361** (closed): design/netlist.py --check is unwired and cannot distinguish a stale netlist from a different xschem build (pin: 3.4.7)
- **Issue #357** (closed): Auditor Capability Request: Python runtime missing on audit host
- **Issue #352** (closed): Investigate the gmin-stepping 'nonconvergence' diagnostic on the DR-0037 self-biased servo (possible zero-current operating point)

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

