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
    "m_ssr_end", "m_hg_end", "m_vout_pp_late",
    "m_vout_off_tran", "m_pg_off_tran",
    "m_ssr_off_tran", "m_hg_off_tran",
]

# Bounds (README.md "Startup" row) plus the two measured references the row
# is written against.
#
# issue #212 / DR-0024 (proposed, not yet ratified): restates the ramp,
# inrush and current-limit-clearance clauses as a startup-current BUDGET AT
# C_eff = 1 uF, not at DR-0001's 4.7 uF ceiling -- the same move DR-0022
# already made for the clearance sub-clause alone. RAMP_MAX_VPMS moves
# 1.0 -> 5.0 V/ms and SETTLE_MAX_S moves 3 ms -> DR-0024's measured-envelope
# figure (see the record this constant is committed alongside). INRUSH_MAX_MA
# and the current-limit-clearance flag below are now checked ONLY at the
# C_eff = 1 uF corners -- above 1 uF both are characterized, not bound, per
# DR-0022/DR-0024's shared "characterized, not bound" posture. Until DR-0024
# is ratified (human merge, per CLAUDE.md's spec-change policy) these
# constants describe the PROPOSED budget, not the ratified one; the ratified
# README.md Startup row is still the ≤ 1 V/ms / 3 ms row until that PR lands.
VOUT_LO = 1.764          # -2%
VOUT_HI = 1.836          # +2%
RAMP_MAX_VPMS = 5.0      # DR-0024 proposed controlled-ramp bound (was 1.0)
INRUSH_MAX_MA = 5.0      # DR-0024 proposed inrush bound, at C_eff = 1 uF only
                         # (was 4.7 uF; see COUT_BOUND_UF below)
ILIMIT_MIN_MA = 62.0     # worst-corner measured limit, sim/current-limit/records/
SETTLE_MAX_S = 1.8e-3    # DR-0024 proposed settling bound (was 3e-3, then
                         # DR-0006's 6e-3; 1.8 ms is the record's own
                         # measured-worst-point (1.72525 ms) plus ~4%
                         # headroom -- NOT the 1.2 ms issue #212 guessed
                         # before the sweep existed to check it, see
                         # DR-0024 "Why 1.8 ms, not 1.2 ms")
COUT_BOUND_UF = "1u"     # cout token (CORNER_RE's group) the inrush and
                         # current-limit-clearance clauses are bound at;
                         # every other C_eff in DR-0001's window is
                         # characterized only, per DR-0022/DR-0024.

# Hand-over invariant, per tb_soft_start.spice.in's own comment: the node that
# gates the soft-start block's PMOS onto PASS_GATE must finish at VIN, or that
# device is still carrying a Vsg and soft start has not fully let go of the
# pass gate. 0.2 V is a reporting threshold, not a ratified bound -- there is
# no spec line on this node -- chosen well below the |Vtp| range measured in
# sim/devchar/CONCLUSIONS.md (0.622 V at ff/125 C .. 1.031 V at ss/-40 C) so
# that any point where the hold is meaningfully out of cutoff is named.
#
# The node was CLG (Mclamp_ss's gate) while soft start was a clamp comparator
# on PASS_GATE (#38/#43); it is HG (Mhold_ss/Mhold_bg_ss's gate) since #189
# replaced that comparator with FB injection. Same invariant, same threshold,
# renamed probe.
HG_END_BELOW_VIN_MAX = 0.2

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
        # Vsg(Mhold_ss) at the end of the enable window. Derived for the
        # hand-over predicate only, and deliberately NOT a CSV column.
        v["m_hg_end_below_vin"] = float(m.group("vin")) - v["m_hg_end"]
        # 1.0 at the C_eff = 1 uF corners the inrush/clearance clauses are
        # bound at (COUT_BOUND_UF), 0.0 elsewhere (DR-0022/DR-0024:
        # characterized, not bound, above 1 uF). Derived for the flag
        # predicates only, and deliberately NOT a CSV column.
        v["m_cout_is_bound"] = 1.0 if m.group("cout") == COUT_BOUND_UF else 0.0
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
                 "m_ssr_end", "m_hg_end",
                 "m_vout_off_tran", "m_ssr_off_tran"):
        rep(name)

    def flag(label: str, pred) -> None:
        report_flag(rows, label, pred)

    print()
    flag(f"steady ramp rate above the proposed {RAMP_MAX_VPMS} V/ms (DR-0024):",
         lambda v: v["m_slope_vpms"] > RAMP_MAX_VPMS)
    flag("peak dVout/dt above the same bound (incl. transients):",
         lambda v: v["m_dvout_max"] > RAMP_MAX_VPMS)
    flag("non-monotonic ramp (dVout/dt went negative):",
         lambda v: v["m_dvout_min"] < -RAMP_MAX_VPMS)
    flag(f"inrush above {INRUSH_MAX_MA} mA at C_eff = {COUT_BOUND_UF} "
         "(characterized only above that, DR-0022/DR-0024):",
         lambda v: v["m_cout_is_bound"] and v["m_icap_peak_ma"] > INRUSH_MAX_MA)
    flag(f"peak supply current within 10 mA of the {ILIMIT_MIN_MA} mA limit, "
         f"at C_eff = {COUT_BOUND_UF} (characterized only above that):",
         lambda v: v["m_cout_is_bound"] and v["m_isup_peak_ma"] > ILIMIT_MIN_MA - 10.0)
    flag(f"startup overshoot above +2% ({VOUT_HI} V):",
         lambda v: v["m_vout_max_en"] > VOUT_HI)
    flag(f"failed to reach {VOUT_LO} V within the proposed {SETTLE_MAX_S * 1e3:g} ms "
         "(DR-0024):",
         lambda v: not (0 < v["m_t_startup"] < SETTLE_MAX_S))
    flag("failed to reach 1.764 V at all inside the enable window:",
         lambda v: not (v["m_t_startup"] > 0))
    flag("settled output outside +/-2% while enabled:",
         lambda v: not (VOUT_LO <= v["m_vout_settled"] <= VOUT_HI))
    flag("still ringing at the end of the enable window (>18 mV pp):",
         lambda v: v["m_vout_pp_late"] > 0.018)
    flag("soft-start ramp did not finish above VREF (clamp still engaged):",
         lambda v: v["m_ssr_end"] < 1.2)
    flag(f"hold gate ended >{HG_END_BELOW_VIN_MAX} V below VIN "
         "(Mhold_ss not fully off):",
         lambda v: v["m_hg_end_below_vin"] > HG_END_BELOW_VIN_MAX)
    flag("disabled output above 10 mV at the end of the tail:",
         lambda v: v["m_vout_off_tran"] > 0.010)
    flag("soft-start ramp capacitor not reset by disable (>10 mV):",
         lambda v: v["m_ssr_off_tran"] > 0.010)


if __name__ == "__main__":
    main()
