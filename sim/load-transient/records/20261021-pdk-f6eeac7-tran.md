# Record 20261021-pdk-f6eeac7-tran

- **Record ID**: 20261021-pdk-f6eeac7-tran
- **Supersedes**: none (append-only). Re-qualifies `20260905-202554-3093ea1` (the head record, measured at open_pdks `c6d73a3…` by the local `run_corners.py` on the earlier DUT, sha256 `f32ebdd0…`, commit `2a7caecb`) under the revision this repo now pins. That record is left untouched and stays valid evidence for `c6d73a3…`; it is superseded only as evidence for `f6eeac7…`, per `sim/README.md`.
- **Claim**: README.md Target specification, 'Load transient' row (DR-0004 amendment A4): 1<->50 mA step, 1us edges, C_eff=0.33uF (DR-0001's hardest stability-window corner) + 0-500 mOhm ESR: peak excursion <=150 mV (100 mV stretch), recovery to within +/-1% (18 mV) in <=20 us. This deck reports peak excursion (both directions); a precise .meas-based recovery-time number is intentionally NOT emitted here to keep this record's scope to fixing the convergence artifact below -- adding one is a follow-up refinement, not required here. (A prior claim on this field asserted the excursion 'never leaves the +/-1% band', reasoning that the amp landed by #35 was a near-ideal, effectively-infinite-bandwidth source; this record's own Result below falsifies that for several corners -- see the non-physical-solution paragraph -- so that reasoning is retracted rather than repeated.) The deck also runs a supplementary Vin step (+/-10% around this PVT point's own vdd_val) after the load step settles, exercising dynamic line response -- this is NOT a distinct ratified spec row (the ratified 'Line reg' row is DC-only, see sim/line-regulation/); reported for completeness per the original issue #12 body's 'load-transient and line-transient response' wording, and excluded from this record's pass/fail checks so it cannot be mistaken for a ratified verdict. This record supersedes 20260801-002806-b64d60e -- a stale record from an earlier design state (commit b64d60e, before #39's current-limit/shutdown path and #44's soft-start landed) whose own stored per-corner values are physically sane; the append-only rule means that record is not itself in error and is left untouched. Re-running this SAME testbench topology against the CURRENT (post-#39/#44) ldo_core.spice with a cold, all-zero-guess Newton-Raphson start does not reproduce those sane numbers: #40's investigation found non-physical excursions at most PVT points for the t=0 operating point -- root-caused in #40 and fixed here. The deck's ideal current sink had a second, unphysical solution for the t=0 operating point in which the pass device is off and the sink holds VOUT tens of volts BELOW ground, drawing its current through forward-biased substrate junctions in the PDK device models; a cold Newton-Raphson start reached that solution at most corners and poisoned the whole transient. The sink is now compliance-limited (see tb_load_transient.spice and sim/harness/README.md, 'Compliance-limited load sinks'): it draws its commanded current for VOUT well above ground and nothing at or below ground, which is what any real load does, and which deletes the sink-sustained unphysical solution rather than biasing the solver away from it. iload_err_max_ua below takes the worst deviation of the delivered load current from the commanded load current over EVERY timepoint of the 400 us run and checks it under 1 uA, so 'the compliance bound never engaged' is a directly measured per-corner fact here rather than an assumption or a voltage-envelope proxy. vout_min_global_v reports how deep the excursion actually went; its 0.5 V floor is derived from the compliance factor itself (1 - f = 6.2e-6 there, i.e. 0.31 uA at 50 mA), not picked as a round number. For scale, the deepest point any corner reaches is 0.984 V at ss_-40c_2.97v, where the sink is still ideal to 2.4e-14 (1.2e-9 uA at 50 mA), and iload_plateau_ma below measures the actually-delivered current in the 50 mA window so that claim is checked at every corner instead of assumed. No ratified threshold was changed. With the convergence artifact fixed, the numbers below are physical -- and they are mostly FAILs: 41 of 45 PVT points fail the ratified 150 mV peak-excursion clause (39 on undershoot, worst 448.3 mV at fs_-40c_2.97v; 24 on overshoot, worst 1152.9 mV at ss_-40c_3.30v). Only tt_27c_3.63v, ff_-40c_3.63v, fs_-40c_3.63v and sf_-40c_3.63v pass. This is a real design finding, not a harness artifact: it tracks the main-loop compensation marginality at the DR-0001 0.33 uF stability-window floor this deck deliberately runs at, already recorded in sim/loop-stability/ (near-zero or negative phase margin at many of the same corners) and tracked by the still-open #42. No loop change is attempted here, per #46's own non-goal against folding a design change in silently; this record is the load-transient evidence #42 will be measured against. Update (#98, 2026-08-16): PR #78 (DR-0015) landed the Mrza/Rza adaptive-compensation shelf in design/error_amp.sch on 2026-08-08, changing exactly the AC/transient behavior this deck measures -- Mrza/Rza carries no DC current, so it can move AC/transient response without moving DC operating points. The record above (20260802-081748-298f357) is now stale: its DUT netlist sha256 (15f70738b1a1b9234770a3b92034b3c7bb85b2904e86ec0ccd53237377470f1a) predates that change and no longer matches design/netlist/ldo_core.spice's current hash. Re-running this SAME testbench topology, unchanged, against the current (post-Mrza/Rza) netlist flips the verdict: every corner now passes. The two corners #95's freshness audit named as the stale record's worst (fs_-40c_2.97v undershoot, ss_-40c_3.30v overshoot) now measure undershoot_mv=43.915 / overshoot_mv=45.311 at fs_-40c_2.97v and undershoot_mv=47.768 / overshoot_mv=53.459 at ss_-40c_3.30v -- both comfortably inside the 150 mV bound with over 3x margin. For the record: the stale record's own per-corner Result table shows those two corners at undershoot_mv=650.111/overshoot_mv=218.098 (fs_-40c_2.97v) and undershoot_mv=382.002/overshoot_mv=211.967 (ss_-40c_3.30v) -- FAIL under the pre-Mrza/Rza design, consistent with #98's framing. Note the exact 448.3 mV / 1152.9 mV figures #95/#98 quote as 'worst' at those two named corners do not appear anywhere in the stale record's own per-corner table for those corners; its own global-spread section instead attributes the grid's worst undershoot (1111.51 mV) to sf_125c_2.97v and worst overshoot (436.74 mV) to ss_27c_3.30v. Flagged here for transparency, not re-litigated -- the stale record is append-only and stays as written. This re-run's corner-set is 'full' (81 points: the base tt/ff/ss/fs/sf process corners plus res_ff/res_ss/bjt_ff/bjt_ss device-level corners, each x3 temperature x3 supply), a superset of the stale record's 45-point base grid; the base 45-point subgrid alone is also 45/45 PASS. No ratified threshold changed, and the testbench/checks/compliance-limited sink are unchanged from the stale record -- this is a physical improvement traceable to the adaptive shelf, not a harness or methodology change. Per #98's own scope, no loop/compensation change is made here; this record is the fresh load-transient evidence #98 was opened to produce. Update (#174, 2026-09-05, spec/decision-records/DR-0021): ldo_core's VREF was promoted from an internal net -- driven by Vref1, an ideal 1.2 V vsource instantiated INSIDE the subcircuit -- to a seventh top-level port, and the identical ideal source moved into this deck. No device was added, removed or resized, so this is an electrical no-op by construction: an ideal vsource is an ideal vsource wherever it is declared, its return was already the cell's VSS port, and it is an AC short to ground in both placements. It is not asserted on that argument alone -- origin/main at ec9e530 was extracted to a scratch tree and this bench was run on BOTH trees back to back, on the same host with the same ngspice and the same pinned PDK, and the per-corner measurement lines compared field by field; DR-0021's 'Evidence' section tabulates the result. Records minted from this deck before 2026-09-05 carry the pre-#174 six-port DUT netlist sha and are superseded on that ground alone, not because any number in them was wrong; per sim/README.md's append-only rule they are left untouched. Update (#325, 2026-09-24, carrying #304's measurement across from sim/psrr-vs-freq): the 'deletes' sentence above is scoped deliberately -- the compliance bound deletes the SINK-SUSTAINED sub-ground root and nothing else. Below the knee the sink is exactly 0 A and 0 S (f(VOUT) underflows to 0.0 in IEEE double for every VOUT <= -0.7530773732699249 V), so the load network is absent from the DC equations there: a sub-ground output voltage reported together with ZERO delivered current is outside the bound's reach by construction, and no knee or softness value can delete it because the sink has no term left in the equations to remove. That is why the pair of checks matters rather than either one alone: vout_min_global_v and iload_plateau_ma / iload_err_max_ua read the same run, and together they discriminate the cases -- a sub-ground reading alongside the COMMANDED current is the sink-sustained root the bound deletes, alongside ZERO delivered current it is a state the bound was never in a position to delete. The deck is deliberately unchanged on that account: #304 measured that knee tuning is coin-flipping (a strictly LOOSER bound 'fixes' the same corner, so the knee is not the mechanism) and that a load-side sub-ground clamp is worse still (it adds a genuine root at VOUT = -0.4994 V that a cold start reaches). See sim/harness/README.md, 'What the bound cannot reach', for the evidence and for the reltol-ladder recipe that tells a false convergence from a genuine second root. Measurement definitions and bounds are `sim/load-transient/testbench/tb.json`'s, unchanged.
- **Netlist provenance**: schematic (`design/netlist/ldo_core.spice`, sha256 `4f99a1a9dcf681be3b470b7f11c8cff1a7a3bc63b276f0aa909fe88dfef5e4e1`), driven by `sim/load-transient/testbench/tb_load_transient.spice` through `sim/harness/tb_adapter.py` (circuit bodies and requests: `sim/load-transient/corners/20261021-pdk-f6eeac7-tran/klt-*/new/`); taken on a clean tree at the adapter commit named by the record ID suffix.
- **Driver**: `python3 sim/load-transient/testbench/klt_run.py --record-id 20261021-pdk-f6eeac7-tran`
- **Backend**: `klt sim` batch fleet, 3 requests (one per supply point: the deck's supply is a `{vdd_val}` PWL that `klt` cannot `alter`, so `vdd_val` is written into each request's body; see the driver docstring): `2.97v` job `klt-sim-882698f92b02` (m7i.4xlarge, done); `3.30v` job `klt-sim-6aa4878fce29` (m7i.4xlarge, done); `3.63v` job `klt-sim-1dc4fd0aff40` (m7i.4xlarge, done). `environment.remote` in each `klt-report.json`. No local `ngspice -b` grid.
- **PDK**: open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (`PINNED_OPEN_PDKS_REVISION`), model files staged with every job (`options.stage_model_inputs`; `worker_environment.pdk.models_staged: true`). The batch image's own PDK stamp reads `open_pdks c6d73a35f524070e85faff4a6a9eef49553ebc2b`, so the `pdk_stamp_comparison: mismatch` in each report is expected and is the reason for staging.
- **Links**:
  - `sim/load-transient/corners/20261021-pdk-f6eeac7-tran/` (`summary.csv`; `klt-<vin>v/new/` = per-corner logs, `body.spice`, `request.json`, `klt-report.json`)
  - `sim/load-transient/netlist-snapshots/20261021-pdk-f6eeac7-tran.spice`
- **Corner matrix run**:
  - Process: tt, ff, ss, fs, sf, res_ff, res_ss, bjt_ff, bjt_ss
  - Temperature: -40 C, 27 C, 125 C
  - Supply: 2.97 V, 3.30 V, 3.63 V
  - 81 point full-factorial grid (process x temperature x supply), 81 completed
- **Operating conditions**:
  - Load current: 1 mA <-> 50 mA step at t=50us (1us edges); held between 51-150us then reverted. Commanded through a compliance-limited sink (Vilc/Bload/Vlmeas) and verified by iload_plateau_ma
  - Output cap: 0.33 uF (DR-0001 stability-window floor, the hardest corner for this row) + 100 mOhm ESR
  - Enable state: enabled (EN tied to VIN at instantiation)
  - Supplementary line step: Vin steps to 0.9x/1.1x this PVT point's own vdd_val at t=200us/300us (Iload held at 1mA) -- NOT a ratified spec row, see Claim
- **Statistical convention**: N/A (corner-matrix claim, not a distribution claim)
- **Result**:

  | corner-id | undershoot_mv | overshoot_mv | line_step_dev_lo_mv | line_step_dev_hi_mv | iload_plateau_ma | vout_min_global_v | iload_err_max_ua | pass/fail |
  |---|---|---|---|---|---|---|---|---|
  | `tt_-40c_2.97v` | 35.5291 | 38.2783 | 3.13878 | -0.565373 | 50 | 1.59593 | 6.938894e-12 | PASS |
  | `tt_-40c_3.30v` | 29.3117 | 30.076 | 2.68733 | -0.648742 | 50 | 1.76948 | 6.938894e-12 | PASS |
  | `tt_-40c_3.63v` | 24.4591 | 23.1753 | 2.97121 | -0.866084 | 50 | 1.77336 | 6.938894e-12 | PASS |
  | `tt_27c_2.97v` | 46.224 | 44.7728 | 4.0159 | -0.656056 | 50 | 1.75378 | 6.938894e-12 | PASS |
  | `tt_27c_3.30v` | 40.0224 | 36.0508 | 2.76442 | -0.761717 | 50 | 1.75998 | 6.938894e-12 | PASS |
  | `tt_27c_3.63v` | 35.0315 | 29.3096 | 2.15759 | -1.05746 | 50 | 1.76495 | 6.938894e-12 | PASS |
  | `tt_125c_2.97v` | 61.5004 | 54.4633 | 5.70906 | -0.814972 | 50 | 1.7385 | 6.938894e-12 | PASS |
  | `tt_125c_3.30v` | 54.3407 | 45.3797 | 4.04548 | -1.16144 | 50 | 1.74566 | 6.938894e-12 | PASS |
  | `tt_125c_3.63v` | 48.7278 | 38.1912 | 3.05309 | -3.82846 | 50 | 1.75127 | 6.938894e-12 | PASS |
  | `ff_-40c_2.97v` | 27.9162 | 22.3216 | 1.24524 | -0.588276 | 50 | 1.77155 | 6.938894e-12 | PASS |
  | `ff_-40c_3.30v` | 23.353 | 16.9453 | 1.47025 | -0.679677 | 50 | 1.77562 | 6.938894e-12 | PASS |
  | `ff_-40c_3.63v` | 20.1171 | 13.7834 | 1.6618 | -0.929035 | 50 | 1.77867 | 6.938894e-12 | PASS |
  | `ff_27c_2.97v` | 37.8532 | 28.3466 | 1.08089 | -0.697361 | 50 | 1.76215 | 6.938894e-12 | PASS |
  | `ff_27c_3.30v` | 32.8385 | 22.5804 | 1.2173 | -0.862399 | 50 | 1.76716 | 6.938894e-12 | PASS |
  | `ff_27c_3.63v` | 28.9148 | 18.5071 | 1.41345 | -3.12224 | 50 | 1.77108 | 6.938894e-12 | PASS |
  | `ff_125c_2.97v` | 51.7545 | 36.9474 | 1.61976 | -2.08738 | 50 | 1.74825 | 6.938894e-12 | PASS |
  | `ff_125c_3.30v` | 46.4098 | 30.1334 | 1.77216 | -6.52806 | 50 | 1.75359 | 6.938894e-12 | PASS |
  | `ff_125c_3.63v` | 46.462 | 20.6605 | 4.79835 | -7.08436 | 50 | 1.69599 | 6.938894e-12 | PASS |
  | `ss_-40c_2.97v` | 233.27 | 38.3062 | 4.29092 | -0.557433 | 50 | 1.55424 | 6.938894e-12 | FAIL — undershoot_mv max=150 (got 233.27) |
  | `ss_-40c_3.30v` | 213.674 | 38.2205 | 4.81664 | -0.628775 | 50 | 1.5592 | 6.938894e-12 | FAIL — undershoot_mv max=150 (got 213.674) |
  | `ss_-40c_3.63v` | 196.814 | -0.871924 | 4.38682 | -0.821902 | 50 | 1.50756 | 6.938894e-12 | FAIL — undershoot_mv max=150 (got 196.814) |
  | `ss_27c_2.97v` | 56.381 | 64.7929 | 8.44445 | -0.636183 | 50 | 1.5782 | 6.938894e-12 | PASS |
  | `ss_27c_3.30v` | 48.941 | 54.1446 | 6.61131 | -0.736664 | 50 | 1.60499 | 6.938894e-12 | PASS |
  | `ss_27c_3.63v` | 43.0835 | 45.0478 | 5.71082 | -1.00112 | 50 | 1.60791 | 6.938894e-12 | PASS |
  | `ss_125c_2.97v` | 73.0848 | 76.6326 | 13.3022 | -0.770594 | 50 | 1.72692 | 6.938894e-12 | PASS |
  | `ss_125c_3.30v` | 64.5342 | 64.5235 | 8.89618 | -0.907068 | 50 | 1.73547 | 6.938894e-12 | PASS |
  | `ss_125c_3.63v` | 57.7821 | 54.9783 | 6.71426 | -1.30914 | 50 | 1.74222 | 6.938894e-12 | PASS |
  | `fs_-40c_2.97v` | 35.2345 | 41.7765 | 3.94664 | -0.5726 | 50 | 1.76449 | 6.938894e-12 | PASS |
  | `fs_-40c_3.30v` | 29.2749 | 30.7525 | 2.8237 | -0.624478 | 50 | 1.76952 | 6.938894e-12 | PASS |
  | `fs_-40c_3.63v` | 24.568 | 24.2484 | 2.90258 | -0.771296 | 50 | 1.77328 | 6.938894e-12 | PASS |
  | `fs_27c_2.97v` | 45.8878 | 45.6705 | 4.15784 | -0.654539 | 50 | 1.75411 | 6.938894e-12 | PASS |
  | `fs_27c_3.30v` | 39.9215 | 37.0177 | 2.90705 | -0.725122 | 50 | 1.76008 | 6.938894e-12 | PASS |
  | `fs_27c_3.63v` | 35.0897 | 30.3337 | 2.38425 | -0.923243 | 50 | 1.76489 | 6.938894e-12 | PASS |
  | `fs_125c_2.97v` | 61.109 | 55.3402 | 5.94944 | -0.803578 | 50 | 1.73889 | 6.938894e-12 | PASS |
  | `fs_125c_3.30v` | 54.196 | 46.3467 | 4.22838 | -0.893158 | 50 | 1.7458 | 6.938894e-12 | PASS |
  | `fs_125c_3.63v` | 48.6561 | 39.2948 | 3.15372 | -1.28881 | 50 | 1.75134 | 6.938894e-12 | PASS |
  | `sf_-40c_2.97v` | 35.9185 | 37.2537 | 2.96845 | -0.568725 | 50 | 1.60273 | 6.938894e-12 | PASS |
  | `sf_-40c_3.30v` | 29.4406 | 476.051 | -260.62 | 17.8478 | 50 | 1.69036 | 6.938894e-12 | FAIL — overshoot_mv max=150 (got 476.051) |
  | `sf_-40c_3.63v` | 24.4173 | 22.1825 | 2.8488 | -0.997205 | 50 | 1.77343 | 6.938894e-12 | PASS |
  | `sf_27c_2.97v` | 46.5881 | 44.0009 | 3.88723 | -0.669697 | 50 | 1.75341 | 6.938894e-12 | PASS |
  | `sf_27c_3.30v` | 40.1505 | 35.1825 | 2.63244 | -0.829613 | 50 | 1.75985 | 6.938894e-12 | PASS |
  | `sf_27c_3.63v` | 35.0323 | 28.3491 | 2.23431 | -1.67735 | 50 | 1.76495 | 6.938894e-12 | PASS |
  | `sf_125c_2.97v` | 61.9852 | 53.674 | 5.54438 | -1.18246 | 50 | 1.73801 | 6.938894e-12 | PASS |
  | `sf_125c_3.30v` | 54.7157 | 44.2942 | 4.01214 | -5.05221 | 50 | 1.74528 | 6.938894e-12 | PASS |
  | `sf_125c_3.63v` | 50.3711 | 35.5546 | 3.88154 | -6.60035 | 50 | 1.74963 | 6.938894e-12 | PASS |
  | `res_ff_-40c_2.97v` | 32.7669 | 28.707 | 1.35485 | -0.604641 | 50 | 1.7672 | 6.938894e-12 | PASS |
  | `res_ff_-40c_3.30v` | 27.5419 | 21.9055 | 1.58252 | -0.692973 | 50 | 1.77208 | 6.938894e-12 | PASS |
  | `res_ff_-40c_3.63v` | 23.6392 | 17.1274 | 1.912 | -0.927828 | 50 | 1.77565 | 6.938894e-12 | PASS |
  | `res_ff_27c_2.97v` | 43.1304 | 35.0756 | 1.59992 | -0.70313 | 50 | 1.75687 | 6.938894e-12 | PASS |
  | `res_ff_27c_3.30v` | 37.4795 | 28.06 | 1.29247 | -0.814858 | 50 | 1.76252 | 6.938894e-12 | PASS |
  | `res_ff_27c_3.63v` | 33.0792 | 22.864 | 1.35724 | -1.13208 | 50 | 1.76692 | 6.938894e-12 | PASS |
  | `res_ff_125c_2.97v` | 57.9773 | 44.3712 | 2.8555 | -0.88856 | 50 | 1.74202 | 6.938894e-12 | PASS |
  | `res_ff_125c_3.30v` | 51.3188 | 36.9492 | 1.85073 | -1.2163 | 50 | 1.74868 | 6.938894e-12 | PASS |
  | `res_ff_125c_3.63v` | 46.1713 | 31.1979 | 1.60764 | -3.41182 | 50 | 1.75383 | 6.938894e-12 | PASS |
  | `res_ss_-40c_2.97v` | 223.359 | 85.4293 | 13.0882 | -0.538383 | 50 | 1.55309 | 6.938894e-12 | FAIL — undershoot_mv max=150 (got 223.359) |
  | `res_ss_-40c_3.30v` | 269.181 | 38.2016 | 4.33946 | -0.617937 | 50 | 1.53082 | 6.938894e-12 | FAIL — undershoot_mv max=150 (got 269.181) |
  | `res_ss_-40c_3.63v` | 172.459 | 31.0359 | 4.45317 | -0.822062 | 50 | 1.50283 | 6.938894e-12 | FAIL — undershoot_mv max=150 (got 172.459) |
  | `res_ss_27c_2.97v` | 184.678 | 55.3838 | 6.08871 | -0.622708 | 50 | 1.599 | 6.938894e-12 | FAIL — undershoot_mv max=150 (got 184.678) |
  | `res_ss_27c_3.30v` | 130.53 | 41.1422 | 4.18183 | -0.724217 | 50 | 1.59946 | 6.938894e-12 | PASS |
  | `res_ss_27c_3.63v` | 82.5071 | 36.716 | 3.88678 | -1.00405 | 50 | 1.63084 | 6.938894e-12 | PASS |
  | `res_ss_125c_2.97v` | 65.8162 | 65.2736 | 8.77074 | -0.759764 | 50 | 1.73418 | 6.938894e-12 | PASS |
  | `res_ss_125c_3.30v` | 58.1676 | 54.7756 | 6.30824 | -1.11869 | 50 | 1.74183 | 6.938894e-12 | PASS |
  | `res_ss_125c_3.63v` | 52.1233 | 46.4052 | 5.11611 | -4.1944 | 50 | 1.74788 | 6.938894e-12 | PASS |
  | `bjt_ff_-40c_2.97v` | 35.5291 | 38.2783 | 3.13878 | -0.565373 | 50 | 1.59593 | 6.938894e-12 | PASS |
  | `bjt_ff_-40c_3.30v` | 29.3117 | 30.076 | 2.68733 | -0.648742 | 50 | 1.76948 | 6.938894e-12 | PASS |
  | `bjt_ff_-40c_3.63v` | 24.4591 | 23.1753 | 2.97121 | -0.866084 | 50 | 1.77336 | 6.938894e-12 | PASS |
  | `bjt_ff_27c_2.97v` | 46.224 | 44.7728 | 4.0159 | -0.656056 | 50 | 1.75378 | 6.938894e-12 | PASS |
  | `bjt_ff_27c_3.30v` | 40.0224 | 36.0508 | 2.76442 | -0.761717 | 50 | 1.75998 | 6.938894e-12 | PASS |
  | `bjt_ff_27c_3.63v` | 35.0315 | 29.3096 | 2.15759 | -1.05746 | 50 | 1.76495 | 6.938894e-12 | PASS |
  | `bjt_ff_125c_2.97v` | 61.5004 | 54.4633 | 5.70906 | -0.814972 | 50 | 1.7385 | 6.938894e-12 | PASS |
  | `bjt_ff_125c_3.30v` | 54.3407 | 45.3797 | 4.04548 | -1.16144 | 50 | 1.74566 | 6.938894e-12 | PASS |
  | `bjt_ff_125c_3.63v` | 48.7278 | 38.1912 | 3.05309 | -3.82846 | 50 | 1.75127 | 6.938894e-12 | PASS |
  | `bjt_ss_-40c_2.97v` | 35.5291 | 38.2783 | 3.13878 | -0.565373 | 50 | 1.59593 | 6.938894e-12 | PASS |
  | `bjt_ss_-40c_3.30v` | 29.3117 | 30.076 | 2.68733 | -0.648742 | 50 | 1.76948 | 6.938894e-12 | PASS |
  | `bjt_ss_-40c_3.63v` | 24.4591 | 23.1753 | 2.97121 | -0.866084 | 50 | 1.77336 | 6.938894e-12 | PASS |
  | `bjt_ss_27c_2.97v` | 46.224 | 44.7728 | 4.0159 | -0.656056 | 50 | 1.75378 | 6.938894e-12 | PASS |
  | `bjt_ss_27c_3.30v` | 40.0224 | 36.0508 | 2.76442 | -0.761717 | 50 | 1.75998 | 6.938894e-12 | PASS |
  | `bjt_ss_27c_3.63v` | 35.0315 | 29.3096 | 2.15759 | -1.05746 | 50 | 1.76495 | 6.938894e-12 | PASS |
  | `bjt_ss_125c_2.97v` | 61.5004 | 54.4633 | 5.70906 | -0.814972 | 50 | 1.7385 | 6.938894e-12 | PASS |
  | `bjt_ss_125c_3.30v` | 54.3407 | 45.3797 | 4.04548 | -1.16144 | 50 | 1.74566 | 6.938894e-12 | PASS |
  | `bjt_ss_125c_3.63v` | 48.7278 | 38.1912 | 3.05309 | -3.82846 | 50 | 1.75127 | 6.938894e-12 | PASS |

  Spread across the grid:

  | measurement | min | max | mean | spread % | limits |
  |---|---|---|---|---|---|
  | `undershoot_mv` | 20.1171 (`ff_-40c_3.63v`) | 269.181 (`res_ss_-40c_3.30v`) | 58.9272 | 422.664 | max=150 |
  | `overshoot_mv` | -0.871924 (`ss_-40c_3.63v`) | 476.051 (`sf_-40c_3.30v`) | 43.3708 | 1099.64 | max=150 |
  | `line_step_dev_lo_mv` | -260.62 (`sf_-40c_3.30v`) | 13.3022 (`ss_125c_2.97v`) | 0.525561 | 52119.9 | — |
  | `line_step_dev_hi_mv` | -7.08436 (`ff_125c_3.63v`) | 17.8478 (`sf_-40c_3.30v`) | -1.09642 | 2273.97 | — |
  | `iload_plateau_ma` | 50 (`tt_-40c_2.97v`) | 50 (`tt_-40c_2.97v`) | 50 | 0 | min=49.95, max=50.05 |
  | `vout_min_global_v` | 1.50283 (`res_ss_-40c_3.63v`) | 1.77867 (`ff_-40c_3.63v`) | 1.71957 | 16.0413 | min=0.5 |
  | `iload_err_max_ua` | 6.938894e-12 (`tt_-40c_2.97v`) | 6.938894e-12 (`tt_-40c_2.97v`) | 6.938894e-12 | 0 | max=1 |

**Overall: FAIL** (73/81 points meet every `tb.json` bound).

## Old-vs-new

Earlier record: `20260905-202554-3093ea1`. DUT `4f99a1a9…` is **not** the DUT that record cites, so there is no same-DUT comparison; the two differ in DUT, backend and PDK revision together.

81 corners appear in both records; the earlier table is printed to 6 significant digits, so a difference below 1e-5 relative is rounding.

| measurement | corners differing beyond rounding | max abs diff | at |
|---|---|---|---|
| `undershoot_mv` | 81 | 226.814 | `res_ss_-40c_3.30v` |
| `overshoot_mv` | 81 | 441.517 | `sf_-40c_3.30v` |
| `line_step_dev_lo_mv` | 81 | 280.136 | `sf_-40c_3.30v` |
| `line_step_dev_hi_mv` | 81 | 18.6198 | `sf_-40c_3.30v` |
| `iload_plateau_ma` | 0 | 0 | — |
| `vout_min_global_v` | 81 | 0.260244 | `res_ss_-40c_3.63v` |
| `iload_err_max_ua` | 0 | 9.610000e-20 | `bjt_ff_-40c_2.97v` |

## Reading

**8 of 81 points fail the ratified peak-excursion clause (<= 150 mV); the other 73 pass every bound.**
The failures are slow-process, -40 C (and `res_ss` at 27 C / 2.97 V) undershoot of 172-269 mV, and one
`sf_-40c_3.30v` overshoot of 476 mV. Harness integrity holds at all 81 points: the delivered load current
stays within 7e-12 uA of the commanded current (`iload_err_max_ua`), the 50 mA plateau reads 50.000 mA, and
the deepest VOUT is 1.50 V, so the compliance-limited sink was ideal throughout and these are real
excursions of the DUT, not solver artifacts.

**Where the movement comes from.** No earlier record of this bench measured this DUT (the old-vs-new table
above compares across a DUT change and a backend change at once, and every measurement moves). Same-DUT
attribution was therefore run separately, one point at a time, with the earlier DUT (`2a7caecb`, sha256
`f32ebdd0…`) on the same driver at `f6eeac7`: `ss_-40c_2.97v` 55.34 / 65.63 mV, `sf_-40c_3.30v`
38.09 / 34.53 mV (undershoot / overshoot) — equal to `20260905-202554-3093ea1` at those points, which
passed 81/81 — against 233.27 / 38.31 and 29.44 / 476.05 mV for the current DUT. The re-pin from
`c6d73a3` to `f6eeac7` does not move this bench; the DUT change since `2a7caecb` (the DR-0037
VREF-forcing bias servo, `3ef4fe42`) does. Filed as #483. No bound was relaxed and the DUT was not edited.
