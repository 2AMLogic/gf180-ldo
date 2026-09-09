#!/usr/bin/env python3
"""Compare two soft-start-loop-gain matrix records point by point (issue #196).

Same job, same semantics and -- where it matters -- the same code as
``sim/loop-stability/testbench/compare_records.py``: the numeric parsing
(``inf`` in the gain-margin column is a *value*, "no -180 deg crossing in
band", not a parse failure), the ``inf - inf == 0`` delta rule, and the
``resurgence_db`` AC_DEC-comparability tolerance issue #69 established are all
imported from it rather than restated, so the two experiments cannot disagree
about what a delta means.

What is different is the join key. A point of this experiment is not
(corner, load, cap, ESR) but

    (variant, phase, ssr_cmd, corner_id, ceff_uf, esr_ohm)

because the ramp state and the DUT variant are axes here. Points present on
one side only are reported and excluded from the deltas rather than silently
dropped.

It runs no simulation: every number it prints comes from two already-committed
matrix CSVs, so it is reproducible from the repository alone::

    ./sim/soft-start-loop-gain/testbench/compare_records.py BASELINE_ID HEAD_ID
    ./sim/soft-start-loop-gain/testbench/compare_records.py A B --write-delta OUT_ID

Exit codes: 0 the comparison ran (whatever it found), 1 the two records share
no common matrix, 3 a usage/environment problem.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPDIR = HERE.parent
REPO_ROOT = EXPDIR.parent.parent
RECORDS = EXPDIR / "records"

_LS = REPO_ROOT / "sim" / "loop-stability" / "testbench" / "compare_records.py"
_spec = importlib.util.spec_from_file_location("loop_stability_compare", _LS)
lsc = importlib.util.module_from_spec(_spec)
sys.modules["loop_stability_compare"] = lsc
_spec.loader.exec_module(lsc)

_num, delta, fmt = lsc._num, lsc.delta, lsc.fmt
RESURGENCE_AC_DEC_TOLERANCE_DB = lsc.RESURGENCE_AC_DEC_TOLERANCE_DB

KEY_FIELDS = ("variant", "phase", "ssr_cmd", "corner_id", "ceff_uf", "esr_ohm")


def load(record_id: str) -> dict[tuple, dict]:
    path = RECORDS / f"{record_id}-matrix.csv"
    if not path.exists():
        raise SystemExit(f"FATAL: no such matrix CSV: {path}")
    out: dict[tuple, dict] = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            key = tuple(row[f] for f in KEY_FIELDS)
            if key in out:
                raise SystemExit(f"FATAL: duplicate key {key} in {path}")
            out[key] = row
    if not out:
        raise SystemExit(f"FATAL: {path} has no rows")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("baseline", help="record-id of the baseline run")
    ap.add_argument("head", help="record-id of the run being compared to it")
    ap.add_argument("--pm-report-deg", type=float, default=1.0,
                    help="list every point whose phase margin moved by more "
                         "than this (default 1.0 deg)")
    ap.add_argument("--write-delta", default="",
                    help="also write records/<OUT_ID>-delta.csv")
    args = ap.parse_args()

    base, head = load(args.baseline), load(args.head)
    common = sorted(set(base) & set(head))
    only_base = sorted(set(base) - set(head))
    only_head = sorted(set(head) - set(base))
    if not common:
        print("FATAL: the two records share no (variant, phase, ssr, corner, "
              "cap, ESR) point", file=sys.stderr)
        return 1

    print(f"baseline : {args.baseline}  ({len(base)} points)")
    print(f"head     : {args.head}  ({len(head)} points)")
    print(f"common   : {len(common)} points"
          + ("" if not (only_base or only_head)
             else f"  (baseline-only {len(only_base)}, head-only {len(only_head)})"))
    print()

    rows = []
    for key in common:
        b, h = base[key], head[key]
        pm_b, pm_h = _num(b["phase_margin_deg"]), _num(h["phase_margin_deg"])
        gm_b, gm_h = _num(b["gain_margin_db"]), _num(h["gain_margin_db"])
        f0_b, f0_h = _num(b["f_crossover_hz"]), _num(h["f_crossover_hz"])
        rs_b, rs_h = _num(b["resurgence_db"]), _num(h["resurgence_db"])
        vo_b, vo_h = _num(b["vout_v"]), _num(h["vout_v"])
        ii_b, ii_h = _num(b["iinj_ua"]), _num(h["iinj_ua"])
        rows.append(dict(
            variant=key[0], phase=key[1], ssr_cmd=key[2], corner_id=key[3],
            ceff_uf=key[4], esr_ohm=key[5],
            pm_base=pm_b, pm_head=pm_h, d_pm=delta(pm_b, pm_h),
            gm_base=gm_b, gm_head=gm_h, d_gm=delta(gm_b, gm_h),
            f0_base=f0_b, f0_head=f0_h,
            d_f0_pct=(None if f0_b in (None, 0) or f0_h is None
                      else 100.0 * (f0_h - f0_b) / f0_b),
            res_base=rs_b, res_head=rs_h, d_res=delta(rs_b, rs_h),
            vout_base=vo_b, vout_head=vo_h, d_vout=delta(vo_b, vo_h),
            iinj_base=ii_b, iinj_head=ii_h, d_iinj=delta(ii_b, ii_h),
            margin_base=b["margin_vs_dr0001"], margin_head=h["margin_vs_dr0001"],
        ))

    flips = [r for r in rows if r["margin_base"] != r["margin_head"]]
    print("margin_vs_dr0001 column (the DR-0001 bars as a REFERENCE line -- "
          "this experiment makes no DR-0001 verdict):")
    print(f"  points whose column changed: {len(flips)}")
    for r in flips[:10]:
        print(f"    {r['variant']:<8} {r['phase']:<7} ssr={r['ssr_cmd']:<5} "
              f"{r['corner_id']:<20} {r['ceff_uf']}uF {r['esr_ohm']}ohm  "
              f"{r['margin_base']} -> {r['margin_head']}")
    if len(flips) > 10:
        print(f"    ... and {len(flips) - 10} more")
    print()

    def spread(field: str, label: str, unit: str, nd: int = 3) -> None:
        vals = [(abs(r[field]), r) for r in rows if r[field] is not None]
        n_none = len(rows) - len(vals)
        if not vals:
            print(f"  {label}: no comparable points")
            return
        vals.sort(key=lambda t: t[0])
        worst = vals[-1][1]
        print(f"  {label}: median {vals[len(vals) // 2][0]:.{nd}f} {unit}, "
              f"p99 {vals[int(0.99 * (len(vals) - 1))][0]:.{nd}f} {unit}, "
              f"max {vals[-1][0]:.{nd}f} {unit} at {worst['variant']}/"
              f"{worst['phase']}/ssr={worst['ssr_cmd']} {worst['corner_id']} / "
              f"{worst['ceff_uf']}uF / {worst['esr_ohm']}ohm"
              + ("" if not n_none else f"  ({n_none} points not comparable)"))

    print("Per-point movement (head - baseline), over the common matrix:")
    spread("d_pm", "|delta phase margin| ", "deg")
    spread("d_gm", "|delta gain margin|  ", "dB")
    spread("d_f0_pct", "|delta crossover|    ", "%")
    spread("d_res", "|delta resurgence|   ", "dB")
    spread("d_vout", "|delta landed VOUT|  ", "V", nd=5)
    spread("d_iinj", "|delta injection I|  ", "uA", nd=4)

    res_deltas = [abs(r["d_res"]) for r in rows if r["d_res"] is not None]
    if res_deltas:
        worst = max(res_deltas)
        ok = worst <= RESURGENCE_AC_DEC_TOLERANCE_DB
        print(f"  resurgence_db comparability (issue #69): "
              f"{'COMPARABLE' if ok else 'NOT COMPARABLE'} -- worst movement "
              f"{worst:.3f} dB is {'within' if ok else 'beyond'} the "
              f"{RESURGENCE_AC_DEC_TOLERANCE_DB:g} dB AC_DEC-invariance "
              f"tolerance.")
    print()

    big = sorted((r for r in rows if r["d_pm"] is not None
                  and abs(r["d_pm"]) > args.pm_report_deg),
                 key=lambda r: -abs(r["d_pm"]))
    print(f"points whose phase margin moved by more than "
          f"{args.pm_report_deg:g} deg: {len(big)}")
    for r in big[:20]:
        print(f"  {r['variant']:<8} {r['phase']:<7} ssr={r['ssr_cmd']:<5} "
              f"{r['corner_id']:<20} {r['ceff_uf']:>4}uF {r['esr_ohm']:>6}ohm  "
              f"PM {fmt(r['pm_base'])} -> {fmt(r['pm_head'])} "
              f"({r['d_pm']:+.2f})")
    if len(big) > 20:
        print(f"  ... and {len(big) - 20} more (see the delta CSV)")

    if args.write_delta:
        out = RECORDS / f"{args.write_delta}-delta.csv"
        cols = list(rows[0].keys())
        with out.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for r in rows:
                w.writerow([
                    "" if r[c] is None
                    else ("inf" if isinstance(r[c], float) and math.isinf(r[c])
                          else (f"{r[c]:.6g}" if isinstance(r[c], float) else r[c]))
                    for c in cols
                ])
        print(f"\ndelta csv : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
