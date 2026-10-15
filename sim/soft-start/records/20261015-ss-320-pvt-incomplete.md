# Soft-start PVT run for the DR-0037 bias servo (#320) -- INCOMPLETE, no verdict

Record id `20261015-ss-320-pvt`; evidence in `sim/soft-start/corners/20261015-ss-320-pvt/`.
Driver: `sim/soft-start/testbench/klt_run.py --record-id 20261015-ss-320-pvt --baseline-ref c13465762a4ce81c52c02401db9a11f30fe43876`
(batch fleet, runner klt 0.7.0, ~2 h wall clock).

## What happened

| Request | DUT | Units | Result |
|---|---|---|---|
| main (1 uF / 100 mohm / 36 ohm, 63-point matrix) | baseline `Fss_ramp` | 63 | 63/63 `pass` |
| main | new (servo) | 63 | 63/63 `batch_job_timeout` |
| extra (5 cap configs, 20-point subset) | baseline | 20 | `batch_job_timeout` |
| extra | new | 20 | `batch_job_timeout` |

klt's own `job_ceiling` warning on the new-DUT main job: `max_job_seconds` = 3600 s
(fleet config); one request carrying 63 units exceeded it and the whole job was
killed (`elapsed_seconds` 3632, exit 124), so every unit was reported
`batch_job_timeout` and no measurements were recovered. The servo DUT simulates
slower than the `Fss_ramp` DUT, which finished under the ceiling.

## What this does and does not show

* **No DR-0006 verdict for the new topology.** There are no new-DUT soft-start
  measurements here; nothing in this record supports or refutes the servo.
* The 63 baseline main points are valid: `slope_vpms` 1.30-3.41 V/ms, peak Icap
  up to 415.6 mA across the matrix (pre-change `Fss_ramp`). They are context only.
* The quiescent-current matrix and the EN=0 exact-zero check were not attempted
  (see PR #425: the fleet refused the quiescent-current submit at its vCPU cap).

## To finish

Shard each request below the 3600 s ceiling (e.g. one job per process corner,
`timeout_s` <= 3480) and re-run main + extra for the new DUT; then the
quiescent-current matrix and EN=0 check. The driver fix in this change
(`summary.csv` header from the union of row keys) removes the crash that
followed the failed jobs (this `summary.csv` was rebuilt from the saved `klt-report.json` files, with an added `part` column the driver does not emit). Remaining acceptance items on #320 stay open.
