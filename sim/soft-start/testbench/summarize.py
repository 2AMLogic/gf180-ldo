#!/usr/bin/env python3
"""Roll the soft-start corner logs up into one CSV plus a pass/fail report.

    python3 sim/soft-start/testbench/summarize.py <log-dir> <csv-out>

Kept separate from run.sh (unlike the older sim/enable-shutdown runner, which
inlines its rollup as a heredoc) because this experiment's per-clause verdicts
are the part a reader is most likely to want to re-derive from the committed
logs without re-running ngspice.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness.pvt_log import read_measurements, report_flag, report_minmax  # noqa: E402

# Scalars every log must carry; a missing one is a bench error, not a result.
SCALARS = [
    "m_t_v04", "m_t_v14",
    "m_t_startup", "m_vout_max_en", "m_vout_settled",
    "m_icap_peak_ma", "m_isup_peak_ma",
    "m_dvout_max", "m_dvout_min",
    "m_ssr_end", "m_clg_end", "m_vout_pp_late",
    "m_vout_off_tran", "m_pg_off_tran",
    "m_ssr_off_tran", "m_clg_off_tran",
]

# Ratified bounds (README.md "Startup" row) plus the two measured references
# the row is written against.
VOUT_LO = 1.764          # -2%
VOUT_HI = 1.836          # +2%
RAMP_MAX_VPMS = 1.0      # ratified controlled-ramp bound
INRUSH_MAX_MA = 5.0      # ratified inrush bound (at C_eff = 4.7 uF)
ILIMIT_MIN_MA = 62.0     # worst-corner measured limit, sim/current-limit/records/
SETTLE_MAX_S = 3e-3      # ratified "+/-2% within 3 ms of enable"

# Hand-over invariant, per tb_soft_start.spice.in's own comment: CLG must
# finish at VIN, or Mclamp_ss is still carrying a Vsg and the soft-start clamp
# has not fully let go of PASS_GATE. The bench measured m_clg_end from the
# start and nothing adjudicated it; this is the missing predicate. 0.2 V is a
# reporting threshold, not a ratified bound -- there is no spec line on this
# node -- chosen well below the |Vtp| range measured in
# sim/devchar/CONCLUSIONS.md (0.622 V at ff/125 C .. 1.031 V at ss/-40 C) so
# that any point where the clamp is meaningfully out of cutoff is named.
CLG_END_BELOW_VIN_MAX = 0.2

CORNER_RE = re.compile(
    r"^(?P<corner>tt|ff|ss|fs|sf|res_ff|res_ss)_"
    r"(?P<temp>-?\d+)c_(?P<vin>[\d.]+)v_"
    r"(?P<cout>[\d.]+u)_(?P<esr>[\d.]+)_(?P<rload>[\deE.+]+)$"
)


def read_log(log: pathlib.Path) -> dict[str, float]:
    return read_measurements(log, SCALARS)


def main() -> None:
    log_dir = pathlib.Path(sys.argv[1])
    csv_path = pathlib.Path(sys.argv[2])

    rows = []
    for log in sorted(log_dir.glob("*.log")):
        cid = log.stem
        m = CORNER_RE.match(cid)
        if not m:
            raise SystemExit(f"FATAL: cannot parse corner id {cid}")
        v = read_log(log)
        dt = v["m_t_v14"] - v["m_t_v04"]
        v["m_slope_vpms"] = 1.0 / (dt * 1e3) if dt > 0 else float("nan")
        v["m_t_startup_ms"] = v["m_t_startup"] * 1e3
        # Vsg(Mclamp_ss) at the end of the enable window. Derived for the
        # hand-over predicate only, and deliberately NOT a CSV column: the
        # committed summary.csv is evidence and its schema does not move.
        v["m_clg_end_below_vin"] = float(m.group("vin")) - v["m_clg_end"]
        rows.append((cid, m.groupdict(), v))

    cols = SCALARS + ["m_slope_vpms", "m_t_startup_ms"]
    with csv_path.open("w") as fh:
        fh.write("corner_id,corner,temp_c,vin_v,cout,esr_ohm,rload_ohm,"
                 + ",".join(c[2:] for c in cols) + "\n")
        for cid, g, v in rows:
            fh.write(
                f"{cid},{g['corner']},{g['temp']},{g['vin']},"
                f"{g['cout']},{g['esr']},{g['rload']},"
                + ",".join(f"{v[k]:.6g}" for k in cols) + "\n")

    def rep(name: str, scale: float = 1.0, unit: str = "") -> None:
        report_minmax(rows, name, scale=scale, unit=unit, name_width=16, cid_width=34)

    print(f"\n{len(rows)} points")
    for name in ("m_slope_vpms", "m_dvout_max", "m_dvout_min",
                 "m_t_startup_ms", "m_vout_max_en", "m_vout_settled",
                 "m_icap_peak_ma", "m_isup_peak_ma", "m_vout_pp_late",
                 "m_ssr_end", "m_clg_end",
                 "m_vout_off_tran", "m_ssr_off_tran"):
        rep(name)

    def flag(label: str, pred) -> None:
        report_flag(rows, label, pred)

    print()
    flag(f"steady ramp rate above the ratified {RAMP_MAX_VPMS} V/ms:",
         lambda v: v["m_slope_vpms"] > RAMP_MAX_VPMS)
    flag("peak dVout/dt above the same bound (incl. transients):",
         lambda v: v["m_dvout_max"] > RAMP_MAX_VPMS)
    flag("non-monotonic ramp (dVout/dt went negative):",
         lambda v: v["m_dvout_min"] < -RAMP_MAX_VPMS)
    flag(f"inrush (capacitor current) above {INRUSH_MAX_MA} mA:",
         lambda v: v["m_icap_peak_ma"] > INRUSH_MAX_MA)
    flag(f"peak supply current within 10 mA of the {ILIMIT_MIN_MA} mA limit:",
         lambda v: v["m_isup_peak_ma"] > ILIMIT_MIN_MA - 10.0)
    flag(f"startup overshoot above +2% ({VOUT_HI} V):",
         lambda v: v["m_vout_max_en"] > VOUT_HI)
    flag(f"failed to reach {VOUT_LO} V within the ratified 3 ms:",
         lambda v: not (0 < v["m_t_startup"] < SETTLE_MAX_S))
    flag("failed to reach 1.764 V at all inside the enable window:",
         lambda v: not (v["m_t_startup"] > 0))
    flag("settled output outside +/-2% while enabled:",
         lambda v: not (VOUT_LO <= v["m_vout_settled"] <= VOUT_HI))
    flag("still ringing at the end of the enable window (>18 mV pp):",
         lambda v: v["m_vout_pp_late"] > 0.018)
    flag("soft-start ramp did not finish above VREF (clamp still engaged):",
         lambda v: v["m_ssr_end"] < 1.2)
    flag(f"clamp gate ended >{CLG_END_BELOW_VIN_MAX} V below VIN "
         "(Mclamp_ss not fully off):",
         lambda v: v["m_clg_end_below_vin"] > CLG_END_BELOW_VIN_MAX)
    flag("disabled output above 10 mV at the end of the tail:",
         lambda v: v["m_vout_off_tran"] > 0.010)
    flag("soft-start ramp capacitor not reset by disable (>10 mV):",
         lambda v: v["m_ssr_off_tran"] > 0.010)


if __name__ == "__main__":
    main()
