# Record 20261021-pdk-f6eeac7-startup

- **Record ID**: 20261021-pdk-f6eeac7-startup
- **Supersedes**: none (append-only). First record for this bench measured through `klt sim` on the batch fleet against the pinned open_pdks revision; earlier records (local `run_corners.py`) are left untouched.
- **Claim**: README.md Target specification, 'Startup' row (DR-0004 amendment A9): monotonic into any load 0-50 mA, controlled ramp <=1V/ms, inside +/-2% within 3 ms of enable, overshoot <=+2%. Measured here for full load (~50 mA) and minimum/no external load. The third branch (near-short, 'startup into current limit') is evidence-only: a near-short is outside the ratified 0-50 mA load range and README.md's target table has no short-circuit-current row to check its peak against, so it carries no pass/fail checks. The DUT now instantiates Xilimit (issue #11 / PR #39, closed) and Xsoftstart (issue #38 / PR #44), so this is inrush into a PROTECTED near-short, unlike the unprotected-inrush framing of the pre-#39 record this one supersedes. Integration method: '.options method=gear' (tb_startup.spice header) -- ngspice's default trapezoidal integrator rings across the near-short branch's fast current-limit clamping and collapses the whole deck's global timestep, making this matrix unrunnable against the post-#39/#44 DUT (issue #48); Gear/BDF integration does not ring across that event. Not a tolerance relaxation -- reltol/abstol/vntol/chgtol stay at ngspice defaults -- but disclosed here per the sim/soft-start/ precedent for integrator-choice changes; see tb_startup.spice for the measured CPU cost and a same-corner sanity check against the (unaffected, still-trapezoidal) _full/_min branches. Update (#174, 2026-09-05, spec/decision-records/DR-0021): ldo_core's VREF was promoted from an internal net -- driven by Vref1, an ideal 1.2 V vsource instantiated INSIDE the subcircuit -- to a seventh top-level port, and the identical ideal source moved into this deck. No device was added, removed or resized, so this is an electrical no-op by construction: an ideal vsource is an ideal vsource wherever it is declared, its return was already the cell's VSS port, and it is an AC short to ground in both placements. It is not asserted on that argument alone -- origin/main at ec9e530 was extracted to a scratch tree and this bench was run on BOTH trees back to back, on the same host with the same ngspice and the same pinned PDK, and the per-corner measurement lines compared field by field; DR-0021's 'Evidence' section tabulates the result. Records minted from this deck before 2026-09-05 carry the pre-#174 six-port DUT netlist sha and are superseded on that ground alone, not because any number in them was wrong; per sim/README.md's append-only rule they are left untouched. Measurement definitions and bounds are `sim/startup/testbench/tb.json`'s, unchanged.
- **Netlist provenance**: schematic (`design/netlist/ldo_core.spice`, sha256 `4f99a1a9dcf681be3b470b7f11c8cff1a7a3bc63b276f0aa909fe88dfef5e4e1`), driven by `sim/startup/testbench/tb_startup.spice` through `sim/harness/tb_adapter.py` (circuit bodies and requests: `sim/startup/corners/20261021-pdk-f6eeac7-startup/klt-*/new/`); taken on a clean tree at the adapter commit named by the record ID suffix.
- **Driver**: `python3 sim/startup/testbench/klt_run.py --record-id 20261021-pdk-f6eeac7-startup`
- **Backend**: `klt sim` batch fleet, 3 requests (one per analysis state and supply point, see the driver docstring): `2.97v` job `klt-sim-3901c8d9994e, klt-sim-8653d0f166c4, klt-sim-8b7f4c8d834d, klt-sim-ee16d4a0c2ab, klt-sim-eaf644d6f899, klt-sim-b1bfe3b9d5e3, klt-sim-f2770604e44c, klt-sim-eebf7a64f4ed, klt-sim-d44eebe48bd9, klt-sim-e51851379599, klt-sim-f4ab54e46c84, klt-sim-a3b29925754c, klt-sim-053492acc2a0, klt-sim-1341ef852d14` (c7i.8xlarge, m7i.4xlarge, done); `3.30v` job `klt-sim-b4eaf7834158, klt-sim-8ca6c01db9fe, klt-sim-58700c15541f, klt-sim-04b1c84fe26e, klt-sim-3bbae2b5ed10, klt-sim-e09936a021e8, klt-sim-0ab501ce30d9, klt-sim-3e26a20f9363, klt-sim-5b12cfd6ae91, klt-sim-ac83343d8d8d, klt-sim-0dbc2c01c69a, klt-sim-d5db2177c1c8, klt-sim-1dd5f58b7ac0, klt-sim-b0e7a4af4e8a` (c7i.8xlarge, done); `3.63v` job `klt-sim-b5b5a33ab1a7, klt-sim-8fe8e328aa2a, klt-sim-6f49e86aad06, klt-sim-a3b98fb29fe5, klt-sim-a726afb2bdfa, klt-sim-0aa4e08a85c0, klt-sim-c82b62f4c8da, klt-sim-5d63a846ab37, klt-sim-63767028987b, klt-sim-71742560c7d7, klt-sim-0ecfbb898d9c, klt-sim-738494d0e980, klt-sim-c70edda4e8c2, klt-sim-6ae646838740` (c7i.8xlarge, m7i.4xlarge, done). `environment.remote` in each `klt-report.json`. No local `ngspice -b` grid.
- **PDK**: open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (`PINNED_OPEN_PDKS_REVISION`), model files staged with every job (`options.stage_model_inputs`; `worker_environment.pdk.models_staged: true`). The batch image's own PDK stamp reads `open_pdks c6d73a35f524070e85faff4a6a9eef49553ebc2b`, so the `pdk_stamp_comparison: mismatch` in each report is expected and is the reason for staging.
- **Links**:
  - `sim/startup/corners/20261021-pdk-f6eeac7-startup/` (`summary.csv`; `klt-<state>-<vin>v/new/` = per-corner logs, `body.spice`, `request.json`, `klt-report.json`)
  - `sim/startup/netlist-snapshots/20261021-pdk-f6eeac7-startup.spice`
- **Corner matrix run**:
  - Process: tt, ff, ss, fs, sf, res_ff, res_ss, bjt_ff, bjt_ss
  - Temperature: -40 C, 27 C, 125 C
  - Supply: 2.97 V, 3.30 V, 3.63 V
  - 81 point full-factorial grid (process x temperature x supply), 81 completed
- **Operating conditions**:
  - Load current: ~50 mA (Rload_full=36 Ohm), ~1 uA (Rload_min=1.8 MOhm, minimum/no external load), near-short (Rload_short=1 Ohm, protected by Xilimit -- see Claim)
  - Output cap: 4.7 uF (DR-0001 window's upper bound, the softest/slowest startup corner) + 100 mOhm ESR, all three branches
  - Enable state: EN steps 0 -> VIN at t=1us (1ns edges) for all three branches simultaneously
- **Statistical convention**: N/A (corner-matrix claim, not a distribution claim)
- **Result**:

  | corner-id | tsettle_full_ms | overshoot_full_mv | tsettle_min_ms | overshoot_min_mv | vfinal_short_v | ipeak_short_ma | pass/fail |
  |---|---|---|---|---|---|---|---|
  | `tt_-40c_2.97v` | 0.943752 | -36.5272 | 0.943625 | -34.4927 | 0.0651403 | 347.209 | PASS |
  | `tt_-40c_3.30v` | 0.959586 | -36.5567 | 0.959459 | -34.9402 | 0.0679848 | 475.985 | PASS |
  | `tt_-40c_3.63v` | 0.978714 | -36.6276 | 0.978537 | -36.4709 | 0.0709274 | 548.047 | PASS |
  | `tt_27c_2.97v` | 0.813988 | -36.6129 | 0.813825 | -33.9249 | 0.0618672 | 326.623 | PASS |
  | `tt_27c_3.30v` | 0.864145 | -36.6567 | 0.863956 | -35.9063 | 0.0793122 | 421.328 | PASS |
  | `tt_27c_3.63v` | 0.916054 | -36.75 | 0.915228 | -36.6023 | 0.0596515 | 431.072 | PASS |
  | `tt_125c_2.97v` | 0.762571 | -36.8023 | 0.76225 | -36.7151 | 0.0681936 | 305.319 | PASS |
  | `tt_125c_3.30v` | 0.82265 | -36.8555 | 0.821296 | -36.6469 | 0.0800581 | 314.858 | PASS |
  | `tt_125c_3.63v` | 0.976059 | -37.0538 | 0.97509 | -36.8243 | 0.0568802 | 314.146 | PASS |
  | `ff_-40c_2.97v` | 0.652507 | -36.5503 | 0.652414 | -34.7806 | 0.0624816 | 456.992 | PASS |
  | `ff_-40c_3.30v` | 0.666867 | -36.5838 | 0.666677 | -36.3989 | 0.0612471 | 475.16 | PASS |
  | `ff_-40c_3.63v` | 0.75113 | -36.6668 | 0.750782 | -36.5312 | 0.0933745 | 204.453 | PASS |
  | `ff_27c_2.97v` | 0.588581 | -36.6577 | 0.588424 | -36.305 | 0.0607549 | 374.557 | PASS |
  | `ff_27c_3.30v` | 0.638828 | -36.6998 | 0.638236 | -36.5126 | 0.0674432 | 376.252 | PASS |
  | `ff_27c_3.63v` | 0.764315 | -36.8232 | 0.763863 | -36.65 | 0.057816 | 373.593 | PASS |
  | `ff_125c_2.97v` | 0.583977 | -36.9906 | 0.582995 | -36.6788 | 0.057077 | 282.848 | PASS |
  | `ff_125c_3.30v` | 0.697518 | -37.6089 | 0.696769 | -37.1687 | 0.061581 | 281.196 | PASS |
  | `ff_125c_3.63v` | 0.823848 | -42.4563 | 0.823143 | -41.9097 | 0.0948741 | 112.007 | PASS |
  | `ss_-40c_2.97v` | 1.2722 | -36.4712 | 1.27203 | -34.3254 | 0.0635827 | 241.291 | PASS |
  | `ss_-40c_3.30v` | 1.28952 | -36.5339 | 1.28935 | -34.7581 | 0.0678565 | 346.856 | PASS |
  | `ss_-40c_3.63v` | 1.31006 | -36.6051 | 1.30989 | -35.1638 | 0.0781583 | 470.417 | PASS |
  | `ss_27c_2.97v` | 1.14474 | -36.4983 | 1.14453 | -33.6773 | 0.0568456 | 240.602 | PASS |
  | `ss_27c_3.30v` | 1.1605 | -36.6301 | 1.16028 | -34.2575 | 0.069524 | 334.121 | PASS |
  | `ss_27c_3.63v` | 1.17889 | -36.7198 | 1.17865 | -35.6921 | 0.0713449 | 434.094 | PASS |
  | `ss_125c_2.97v` | 1.02198 | -36.6672 | 1.02168 | -32.82 | 0.0745066 | 245.906 | PASS |
  | `ss_125c_3.30v` | 1.03695 | -36.8064 | 1.03658 | -36.047 | 0.055127 | 316.595 | PASS |
  | `ss_125c_3.63v` | 1.09277 | -36.9229 | 1.09088 | -36.7579 | 0.0593478 | 355.62 | PASS |
  | `fs_-40c_2.97v` | 0.946569 | -36.539 | 0.946445 | -34.5036 | 0.0537188 | 263.183 | PASS |
  | `fs_-40c_3.30v` | 0.961758 | -36.5603 | 0.961634 | -34.8999 | 0.0609239 | 379.287 | PASS |
  | `fs_-40c_3.63v` | 0.979321 | -36.6055 | 0.979194 | -35.3064 | 0.0738028 | 495.11 | PASS |
  | `fs_27c_2.97v` | 0.8536 | -36.5801 | 0.853443 | -33.8882 | 0.0621955 | 260.259 | PASS |
  | `fs_27c_3.30v` | 0.867132 | -36.6526 | 0.866971 | -34.4733 | 0.0543074 | 354.987 | PASS |
  | `fs_27c_3.63v` | 0.883068 | -36.7096 | 0.882848 | -36.5644 | 0.0566517 | 419.389 | PASS |
  | `fs_125c_2.97v` | 0.773049 | -36.79 | 0.772829 | -33.3324 | 0.0489302 | 258.981 | PASS |
  | `fs_125c_3.30v` | 0.786615 | -36.8188 | 0.786158 | -36.5715 | 0.0518114 | 306.228 | PASS |
  | `fs_125c_3.63v` | 0.861891 | -36.8996 | 0.86077 | -36.7248 | 0.048016 | 308.029 | PASS |
  | `sf_-40c_2.97v` | 0.942199 | -36.5207 | 0.942068 | -34.5048 | 0.108173 | 430.409 | PASS |
  | `sf_-40c_3.30v` | 0.959135 | -36.5629 | 0.958986 | -35.9718 | 0.0751609 | 526.002 | PASS |
  | `sf_-40c_3.63v` | 1.03047 | -36.6716 | 1.02993 | -36.5473 | 0.0765769 | 552.24 | PASS |
  | `sf_27c_2.97v` | 0.847669 | -36.6234 | 0.847489 | -34.8222 | 0.0737093 | 390.55 | PASS |
  | `sf_27c_3.30v` | 0.883774 | -36.6773 | 0.882696 | -36.5025 | 0.0713703 | 414.574 | PASS |
  | `sf_27c_3.63v` | 1.04472 | -36.827 | 1.04406 | -36.6837 | 0.069589 | 433.02 | PASS |
  | `sf_125c_2.97v` | 0.79136 | -36.8642 | 0.789627 | -36.6067 | 0.0609955 | 312.569 | PASS |
  | `sf_125c_3.30v` | 0.940544 | -37.1092 | 0.939441 | -36.79 | 0.0626743 | 314.589 | PASS |
  | `sf_125c_3.63v` | 1.12063 | -38.7948 | 1.11966 | -38.3284 | 0.0589188 | 314.215 | PASS |
  | `res_ff_-40c_2.97v` | 0.709429 | -36.5652 | 0.709322 | -34.5657 | 0.0764028 | 346.346 | PASS |
  | `res_ff_-40c_3.30v` | 0.721481 | -36.5972 | 0.721372 | -35.0095 | 0.0774865 | 472.448 | PASS |
  | `res_ff_-40c_3.63v` | 0.736045 | -36.6741 | 0.735892 | -36.4712 | 0.0754728 | 563.587 | PASS |
  | `res_ff_27c_2.97v` | 0.615972 | -36.6629 | 0.615834 | -33.9587 | 0.0683129 | 330.804 | PASS |
  | `res_ff_27c_3.30v` | 0.649561 | -36.7026 | 0.6494 | -35.8134 | 0.107322 | 430.276 | PASS |
  | `res_ff_27c_3.63v` | 0.688759 | -36.803 | 0.688048 | -36.6195 | 0.0729277 | 460.726 | PASS |
  | `res_ff_125c_2.97v` | 0.572512 | -36.855 | 0.572242 | -36.4845 | 0.0768944 | 318.521 | PASS |
  | `res_ff_125c_3.30v` | 0.61776 | -36.9134 | 0.616601 | -36.657 | 0.0819206 | 347.695 | PASS |
  | `res_ff_125c_3.63v` | 0.733038 | -37.114 | 0.732213 | -36.8459 | 0.0832665 | 349.589 | PASS |
  | `res_ss_-40c_2.97v` | 1.17779 | -36.4677 | 1.17764 | -34.4874 | 0.0918479 | 347.524 | PASS |
  | `res_ss_-40c_3.30v` | 1.19733 | -36.5268 | 1.19718 | -34.9329 | 0.0758055 | 476.201 | PASS |
  | `res_ss_-40c_3.63v` | 1.22094 | -36.5931 | 1.22074 | -36.4569 | 0.0637291 | 533.391 | PASS |
  | `res_ss_27c_2.97v` | 1.06079 | -36.55 | 1.0606 | -33.948 | 0.0548167 | 330.078 | PASS |
  | `res_ss_27c_3.30v` | 1.07851 | -36.6237 | 1.0783 | -35.9972 | 0.0840166 | 406.655 | PASS |
  | `res_ss_27c_3.63v` | 1.14305 | -36.7117 | 1.14211 | -36.5881 | 0.0575299 | 412.618 | PASS |
  | `res_ss_125c_2.97v` | 0.952843 | -36.7655 | 0.952467 | -36.6983 | 0.0488316 | 284.279 | PASS |
  | `res_ss_125c_3.30v` | 1.02768 | -36.8155 | 1.02613 | -36.639 | 0.0529729 | 289.387 | PASS |
  | `res_ss_125c_3.63v` | 1.21912 | -37.0128 | 1.21801 | -36.8088 | 0.0500078 | 288.585 | PASS |
  | `bjt_ff_-40c_2.97v` | 0.943752 | -36.5272 | 0.943625 | -34.4927 | 0.0651403 | 347.209 | PASS |
  | `bjt_ff_-40c_3.30v` | 0.959586 | -36.5567 | 0.959459 | -34.9402 | 0.0679848 | 475.985 | PASS |
  | `bjt_ff_-40c_3.63v` | 0.978714 | -36.6276 | 0.978537 | -36.4709 | 0.0709274 | 548.047 | PASS |
  | `bjt_ff_27c_2.97v` | 0.813988 | -36.6129 | 0.813825 | -33.9249 | 0.0618672 | 326.623 | PASS |
  | `bjt_ff_27c_3.30v` | 0.864145 | -36.6567 | 0.863956 | -35.9063 | 0.0793122 | 421.328 | PASS |
  | `bjt_ff_27c_3.63v` | 0.916054 | -36.75 | 0.915228 | -36.6023 | 0.0596515 | 431.072 | PASS |
  | `bjt_ff_125c_2.97v` | 0.762571 | -36.8023 | 0.76225 | -36.7151 | 0.0681936 | 305.319 | PASS |
  | `bjt_ff_125c_3.30v` | 0.82265 | -36.8555 | 0.821296 | -36.6469 | 0.0800581 | 314.858 | PASS |
  | `bjt_ff_125c_3.63v` | 0.976059 | -37.0538 | 0.97509 | -36.8243 | 0.0568802 | 314.146 | PASS |
  | `bjt_ss_-40c_2.97v` | 0.943752 | -36.5272 | 0.943625 | -34.4927 | 0.0651403 | 347.209 | PASS |
  | `bjt_ss_-40c_3.30v` | 0.959586 | -36.5567 | 0.959459 | -34.9402 | 0.0679848 | 475.985 | PASS |
  | `bjt_ss_-40c_3.63v` | 0.978714 | -36.6276 | 0.978537 | -36.4709 | 0.0709274 | 548.047 | PASS |
  | `bjt_ss_27c_2.97v` | 0.813988 | -36.6129 | 0.813825 | -33.9249 | 0.0618672 | 326.623 | PASS |
  | `bjt_ss_27c_3.30v` | 0.864145 | -36.6567 | 0.863956 | -35.9063 | 0.0793122 | 421.328 | PASS |
  | `bjt_ss_27c_3.63v` | 0.916054 | -36.75 | 0.915228 | -36.6023 | 0.0596515 | 431.072 | PASS |
  | `bjt_ss_125c_2.97v` | 0.762571 | -36.8023 | 0.76225 | -36.7151 | 0.0681936 | 305.319 | PASS |
  | `bjt_ss_125c_3.30v` | 0.82265 | -36.8555 | 0.821296 | -36.6469 | 0.0800581 | 314.858 | PASS |
  | `bjt_ss_125c_3.63v` | 0.976059 | -37.0538 | 0.97509 | -36.8243 | 0.0568802 | 314.146 | PASS |

  Spread across the grid:

  | measurement | min | max | mean | spread % | limits |
  |---|---|---|---|---|---|
  | `tsettle_full_ms` | 0.572512 (`res_ff_125c_2.97v`) | 1.31006 (`ss_-40c_3.63v`) | 0.905974 | 81.4093 | max=6 |
  | `overshoot_full_mv` | -42.4563 (`ff_125c_3.63v`) | -36.4677 (`res_ss_-40c_2.97v`) | -36.8146 | 16.2668 | max=0 |
  | `tsettle_min_ms` | 0.572242 (`res_ff_125c_2.97v`) | 1.30989 (`ss_-40c_3.63v`) | 0.905498 | 81.4634 | max=6 |
  | `overshoot_min_mv` | -41.9097 (`ff_125c_3.63v`) | -32.82 (`ss_125c_2.97v`) | -35.8273 | 25.3708 | max=0 |
  | `vfinal_short_v` | 0.048016 (`fs_125c_3.63v`) | 0.108173 (`sf_-40c_2.97v`) | 0.0680257 | 88.4328 | — |
  | `ipeak_short_ma` | 112.007 (`ff_125c_3.63v`) | 563.587 (`res_ff_-40c_3.63v`) | 371.588 | 121.527 | — |

**Overall: PASS** (81/81 points meet every `tb.json` bound).

## Old-vs-new

Earlier record: `20260916-112114-8b551ab`. DUT `4f99a1a9…` is **not** the DUT that record cites, so there is no same-DUT comparison; the two differ in DUT, backend and PDK revision together.

81 corners appear in both records; the earlier table is printed to 6 significant digits, so a difference below 1e-5 relative is rounding.

| measurement | corners differing beyond rounding | max abs diff | at |
|---|---|---|---|
| `tsettle_full_ms` | 81 | 0.391372 | `sf_125c_3.63v` |
| `overshoot_full_mv` | 78 | 6.07331 | `ff_125c_3.63v` |
| `tsettle_min_ms` | 81 | 0.390469 | `sf_125c_3.63v` |
| `overshoot_min_mv` | 81 | 9.32967 | `ff_125c_3.63v` |
| `vfinal_short_v` | 81 | 0.036876 | `ff_125c_2.97v` |
| `ipeak_short_ma` | 81 | 470.907 | `sf_-40c_3.63v` |

## Reading

**All 81 points pass every bound of `tb.json`.** Settling to the +/-2% band takes 0.57-1.31 ms at full and
at minimum load (bound 6 ms; slowest `ss_-40c_3.63v`), and the output stays under the 1.836 V ceiling at
every point (the `overshoot_*_mv` columns are the margin below it, -33 to -42 mV). The near-short branch is
evidence only and carries no bound: its peak current is 112-564 mA across the grid.

**Solver warnings.** 41 of the 81 points carry a `nonconvergence` warning (`Dynamic gmin stepping failed`)
from the operating-point solve of one analysis state; all 41 completed and measured, none is errored or
inconclusive, and every measurement is present. It is a fallback notice, not a failed solve, and it is
recorded here rather than hidden.

**Old-vs-new.** The earlier record cites a different DUT, so the table above compares across a DUT change, a
backend change and a PDK re-pin at once and every measurement moves. No same-DUT comparison was run, so this
record does not attribute the movement to any one of the three. Nothing is out of tolerance, so no issue
or decision record is needed for this bench; no bound was relaxed and the DUT was not edited.
