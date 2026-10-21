# Record 20261020-pdk-f6eeac7-ilim

- **Record ID**: 20261020-pdk-f6eeac7-ilim
- **Supersedes**: none (append-only). Re-qualifies `20261015-ilim-320-pvt` (the
  `new` DUT) under the open_pdks revision this repo now pins. That record and
  the reference record `20260923-141325-33035d79` (an older DUT) were measured
  with the fleet worker's `open_pdks c6d73a35…` tree and are **superseded as
  PDK-revision evidence** by this one; neither is edited.
- **Claim**: `README.md` target-spec **"Current limit"** row as ratified by
  `spec/decision-records/DR-0005-current-limit-window.md` — 62–95 mA over PVT
  untrimmed, constant-current clamp, never engaging for I_load <= 50 mA — plus
  the **Thermal** row, <= 346 mW into a Vout = 0 short at the 95 mA ceiling.
  Same bench and grading (`testbench/klt_run.py`, mirroring `summarize.py`,
  DR-0005) as the records above.
- **Why this re-run exists**: issue #430 (phase 2 of #428). The reference
  records were measured at open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b`;
  `PINNED_OPEN_PDKS_REVISION` in `sim/harness/pdk.py` is now
  `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`.
- **PDK revision**: open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`
  (`gf180mcuD`), the submitting host's `~/.ciel` tree. The fleet worker's own
  `/opt/pdk` is still `c6d73a35…`, so the job was submitted with
  `options.stage_model_inputs: true` (added to `sim/harness/klt_batch.py` by
  this change); the report's `worker_environment.models_staged` is `true` and
  its `model_inputs` digests name the staged closure the worker simulated
  against. `worker_environment.pdk.stamp_text` still prints the worker's
  `/opt/pdk` stamp, which is the unused tree. See
  `sim/quiescent-current/records/20261020-pdk-f6eeac7-iq.md` for the local
  single-point cross-check of the staging route.
- **Netlist provenance**: schematic — `design/netlist/ldo_core.spice` (contains
  `ldo_ilimit`), sha256
  `4f99a1a9dcf681be3b470b7f11c8cff1a7a3bc63b276f0aa909fe88dfef5e4e1`, frozen at
  `netlist-snapshots/20261020-pdk-f6eeac7-ilim.spice`; the DUT of
  `20261015-ilim-320-pvt`'s `new` run, byte for byte.
- **Corner matrix run**: 63 points, full factorial — process {tt, ff, ss, fs,
  sf, res_ff, res_ss} x T {-40, 27, 125 C} x Vin {2.97, 3.30, 3.63 V}; 63
  completed. `bjt_ff`/`bjt_ss` omitted (no bipolar device), per this bench's
  convention. One `klt sim` job on the batch fleet (`klt-sim-f9b1dce9db27`,
  448 s, ngspice-46 sha256 `c874869b…`).
- **Operating conditions**: as the prior records — regulation mode and V-I mode
  (Vout forced to 1.764, 1.5, 0.9, 0.3, 0.0 V), no output cap (DC claim),
  enabled, VREF from an ideal 1.2 V source in the deck.
- **Statistical convention**: N/A (corner-matrix claim).
- **Links**: `sim/current-limit/corners/20261020-pdk-f6eeac7-ilim/`
  (`summary.csv`, `new/` deck, request and klt report with per-corner logs).

## Result

| Quantity | this record | ratified bound |
|---|---|---|
| onset at Vout = 1.764 V, min…max | 62.025 … 93.776 mA | 62–95 mA |
| corners outside the 62–95 mA window | 0 / 63 | — |
| onset into a dead short, min…max | 62.646 … 95.206 mA | — |
| dissipation into a short, worst corner | 345.598 mW @ `ff_125c_3.63v` | <= 346 mW |
| corners exceeding 346 mW | 0 / 63 | — |
| limit engaged at or below 50 mA | none | never |
| regulation within +/-2 % at 50 mA | 63 / 63 | +/-2 % |
| flatness, 0 V vs 1.5 V | +0.38 … +2.35 % | brickwall (README note 5) |
| sense-domain margin at 50 mA | >= 18.78 % | — |

Window floor margin 0.025 mA at `ss_-40c_2.97v`; thermal margin 0.402 mW at
`ff_125c_3.63v` (0.12 %). Both rows were already thin by construction
(`20260923-141325-33035d79`).

## Old vs new (same DUT, same bench; `c6d73a35…` -> `f6eeac7d…`)

Compared against `20261015-ilim-320-pvt` (`new`), all 63 points and the
columns ilim_1764_ma, ilim_0000_ma, p_short_mw, flat_pct, sense_margin_pct and
iload_50ma: **identical to the printed precision** (largest absolute
difference 0). Every grade (`in_window`, `reg_ok`, `thermal_ok`) is unchanged,
63 / 63 true. The open_pdks re-pin does not move this bench. (Same worker ngspice
banner, creation date 2026-10-01, in both reports; the older report predates
the `engine_build` field and records no binary sha256, and ran on `m7i.4xlarge`
rather than `c7i.8xlarge`, so the binary equality is not fingerprint-checked.)

**Overall (current limit, ratified 62–95 mA window): PASS** — 63/63 corners
inside the window (62.025 … 93.776 mA), never engaging at or below the 50 mA
rated load.

**Overall (thermal, ratified <= 346 mW into a short): PASS** — worst case
345.598 mW at `ff_125c_3.63v`, 0/63 corners over the bound.

**Overall (brickwall flatness / +/-2 % window at a 50 mA load): PASS.**
