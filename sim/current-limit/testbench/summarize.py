#!/usr/bin/env python3
"""Roll the current-limit corner logs up into one CSV plus a summary report.

    python3 sim/current-limit/testbench/summarize.py \\
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
from harness.pvt_log import grid_rollup, report_minmax, write_corner_csv  # noqa: E402

# The ratified bounds for the two spec rows this bench grades, as amended by
# DR-0005 (ratified 2026-09-15): README.md's "Current limit" row (62-95 mA
# over PVT untrimmed) and its "Thermal" row (<= 346 mW into a Vout = 0 short
# at the untrimmed ceiling). DR-0005 superseded the 65-80 mA / <= 290 mW
# window these checks were originally written against.
#
# klt_run.py's grade() and its declared `limits` import these, so this bench's
# two graders for the same row cannot drift apart again (they had: the script
# kept printing the superseded window while grade() applied the ratified one).
#
# Committed records under sim/current-limit/records/ are append-only evidence:
# a record written before DR-0005 states the window it was graded against in
# its own text and keeps being read against that window, not against these.
ILIM_WINDOW_MA = (62.0, 95.0)
PSHORT_MAX_MW = 346.0

SCALARS = ["m_vout_0ma", "m_vout_25ma", "m_vout_50ma", "m_ivin_0ma_ua",
           "m_iload_25ma", "m_iload_50ma",
           "m_isns_mv_50ma", "m_vth_mv_50ma", "m_sense_margin_pct",
           "m_ilim_1764_ma", "m_ilim_1500_ma", "m_ilim_0900_ma",
           "m_ilim_0300_ma", "m_ilim_0000_ma", "m_pshort_mw"]


def derive(vals: dict) -> None:
    # Brickwall test: a constant-current clamp holds the same current
    # as the output collapses. Positive = short-circuit current is
    # HIGHER than at Vout = 1.5 V (inverse foldback, the bad direction
    # for short-circuit power); negative = it folds back.
    vals["m_flat_0_vs_1500_pct"] = (
        (vals["m_ilim_0000_ma"] - vals["m_ilim_1500_ma"])
        / vals["m_ilim_1500_ma"] * 100)


def rollup(log_dir: pathlib.Path, corners: str, temps: str, supplies: str) -> list[tuple]:
    """Full-factorial grid rows, with the derived flatness column added."""
    return grid_rollup(log_dir, corners, temps, supplies, SCALARS, derive)


CSV_COLS = SCALARS + ["m_flat_0_vs_1500_pct"]


def write_csv(rows, csv_path) -> None:
    write_corner_csv(rows, csv_path, CSV_COLS)


def checks(rows) -> dict:
    """The summary lines' numbers: the onset range at Vout = 1.764 V and the
    corner lists each check names."""
    lim = [vals["m_ilim_1764_ma"] for *_, vals in rows]
    lo, hi = ILIM_WINDOW_MA
    return {
        "lim_min": min(lim),
        "lim_max": max(lim),
        "engages_at_or_below_50ma": [cid for cid, *_, vals in rows
                                     if vals["m_ilim_1764_ma"] <= 50.0],
        "outside_window_at_50ma": [cid for cid, *_, vals in rows
                                   if not (1.764 <= vals["m_vout_50ma"] <= 1.836)],
        "outside_ratified_window": [cid for cid, *_, vals in rows
                                    if not (lo <= vals["m_ilim_1764_ma"] <= hi)],
        "above_thermal_ceiling": [cid for cid, *_, vals in rows
                                  if vals["m_pshort_mw"] > PSHORT_MAX_MW],
    }


def main() -> None:
    log_dir, csv_path, corners, temps, supplies = sys.argv[1:6]
    rows = rollup(pathlib.Path(log_dir), corners, temps, supplies)
    write_csv(rows, csv_path)

    print(f"\n{len(rows)} PVT points")
    for m in ("m_vout_0ma", "m_vout_50ma", "m_ivin_0ma_ua", "m_sense_margin_pct",
              "m_ilim_1764_ma", "m_ilim_0000_ma", "m_flat_0_vs_1500_pct",
              "m_pshort_mw"):
        report_minmax(rows, m, val_width=10, val_prec=4)

    ck = checks(rows)
    lo, hi = ck["lim_min"], ck["lim_max"]
    mid = (hi + lo) / 2
    print(f"\n  limit at the edge of the +/-2% window (Vout = 1.764 V):"
          f" {lo:.2f} .. {hi:.2f} mA"
          f"  = {mid:.2f} mA +/-{(hi-lo)/2/mid*100:.1f}%")
    bad = ck["engages_at_or_below_50ma"]
    print(f"  corners where the limit engages at or below 50 mA: {bad or 'none'}")
    oos = ck["outside_window_at_50ma"]
    print(f"  corners outside the +/-2% window at 50 mA load:     {oos or 'none'}")
    lo_w, hi_w = ILIM_WINDOW_MA
    ratified = ck["outside_ratified_window"]
    label = f"corners outside the ratified {lo_w:g}-{hi_w:g} mA window:"
    print(f"  {label:<52}{len(ratified)}/{len(rows)}")
    hot = ck["above_thermal_ceiling"]
    label = f"corners above the ratified {PSHORT_MAX_MW:g} mW short ceiling:"
    print(f"  {label:<52}{len(hot)}/{len(rows)}")


if __name__ == "__main__":
    main()
