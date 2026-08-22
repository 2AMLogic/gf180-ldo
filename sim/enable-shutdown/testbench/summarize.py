#!/usr/bin/env python3
"""Roll the enable/shutdown corner logs up into one CSV plus a summary report.

    python3 sim/enable-shutdown/testbench/summarize.py \\
        <log-dir> <csv-out> <corners> <temps> <supplies>

Extracted from the inline heredoc previously embedded in this testbench's
run.sh (mirroring sim/soft-start/testbench/summarize.py), so the rollup is
independently runnable against committed logs without re-invoking ngspice,
and so ordinary Python tooling (ruff/black) can see it.
"""

from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness.pvt_log import read_measurements, report_flag, report_minmax  # noqa: E402

SCALARS = ["m_vout_en", "m_iload_en_ma", "m_isup_en_ua", "m_iref_en_ua",
           "m_iq_en_ua",
           "m_vout_off", "m_pg_off", "m_clg_off", "m_isup_off_ua",
           "m_iref_off_ua", "m_iloop_off_ua", "m_nbias_off",
           "m_iq_off_ua", "m_ileak_vin_vout_ua",
           "m_t_startup", "m_vout_settled", "m_vout_max_en",
           "m_vout_min_reg", "m_isup_peak_ma", "m_clg_min_reg",
           "m_isup_peak_reg_ma", "m_vout_pp_late", "m_vout_off_tran",
           "m_vout_max_off", "m_pg_off_tran"]


def read(log):
    return read_measurements(log, SCALARS)


def main() -> None:
    log_dir, csv_path, corners, temps, supplies = sys.argv[1:6]
    log_dir = pathlib.Path(log_dir)

    rows = []
    for c in corners.split():
        for t in temps.split():
            for v in supplies.split():
                cid = "%s_%sc_%.2fv" % (c, t, float(v))
                vals = read(log_dir / f"{cid}.log")
                vals["m_t_startup_us"] = vals["m_t_startup"] * 1e6
                vals["_vin"] = float(v)
                rows.append((cid, c, t, v, vals))

    cols = SCALARS + ["m_t_startup_us"]
    with open(csv_path, "w") as fh:
        fh.write("corner_id,corner,temp_c,vin_v," + ",".join(c[2:] for c in cols) + "\n")
        for cid, c, t, v, vals in rows:
            fh.write(f"{cid},{c},{t},{v}," + ",".join(f"{vals[k]:.6g}" for k in cols) + "\n")

    print(f"\n{len(rows)} PVT points")
    for m in ("m_vout_en", "m_iq_en_ua", "m_vout_off", "m_iloop_off_ua",
              "m_nbias_off", "m_iq_off_ua", "m_ileak_vin_vout_ua",
              "m_t_startup_us", "m_vout_settled", "m_vout_max_en",
              "m_vout_min_reg", "m_isup_peak_ma", "m_clg_min_reg",
              "m_isup_peak_reg_ma", "m_vout_pp_late", "m_vout_off_tran", "m_pg_off_tran"):
        report_minmax(rows, m, val_width=12, val_prec=5)

    def flag(label, pred):
        report_flag(rows, label, pred, label_width=52)

    print()
    flag("shutdown Iq above the ratified 3 uA:", lambda v: v["m_iq_off_ua"] > 3.0)
    flag("enabled Iq above the ratified 30 uA:", lambda v: v["m_iq_en_ua"] > 30.0)
    flag("Vin->Vout leakage above 1 uA:", lambda v: abs(v["m_ileak_vin_vout_ua"]) > 1.0)
    flag("startup failed to reach 1.764 V inside the enable window:",
         lambda v: not (0 < v["m_t_startup"] < 8e-3))
    flag("settled output outside +/-2% while enabled:",
         lambda v: not (1.764 <= v["m_vout_settled"] <= 1.836))
    flag("regulation dipped below 1.764 V after settling:",
         lambda v: v["m_vout_min_reg"] < 1.764)
    flag("startup overshoot above +2% (1.836 V):", lambda v: v["m_vout_max_en"] > 1.836)
    flag("disabled output above 10 mV at the end of the tail:",
         lambda v: v["m_vout_off_tran"] > 0.010)
    flag("limit clamp engaged while settled at 50 mA (CLG < VIN-0.2):",
         lambda v: v["m_clg_min_reg"] < float(v["_vin"]) - 0.2)


if __name__ == "__main__":
    main()
