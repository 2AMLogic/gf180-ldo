#!/usr/bin/env python3
"""Compare two loop-stability matrix records point by point (issue #58).

Two records of this experiment are only comparable point-to-point because
every run sweeps the same ratified matrix and writes it to
``records/<record-id>-matrix.csv`` with a stable key. This script does the
join and reports what moved -- the comparison that acceptance criteria keep
asking for and that neither record contains on its own
(``records/20260802-085331-8a1a9e8.md`` is the precedent, computed by hand).

It runs no simulation. Every number it prints is derived from two already
committed matrix CSVs, so it is reproducible from the repository alone::

    ./sim/loop-stability/testbench/compare_records.py BASELINE_ID HEAD_ID
    ./sim/loop-stability/testbench/compare_records.py A B --write-delta OUT_ID

The join key is ``(corner_id, iload_ma, ceff_uf, esr_ohm)``. Points present
on one side only are reported and excluded from the deltas rather than
silently dropped: two records taken over different matrices are a fact worth
seeing, not an error to paper over.

Exit codes: 0 the comparison ran (whatever it found), 1 the two records do
not share a common matrix, 3 a usage/environment problem.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPDIR = HERE.parent
RECORDS = EXPDIR / "records"

KEY_FIELDS = ("corner_id", "iload_ma", "ceff_uf", "esr_ohm")


def _num(tok: str) -> float | None:
    """Parse a matrix-CSV numeric cell, including the sentinels it uses.

    ``inf`` is a real, meaningful value in the gain-margin column (the loop
    phase never reaches -180 deg in band), not a parse failure. ``n/a`` and
    empty are genuinely absent quantities and come back as ``None`` so a
    delta against them is never computed.
    """
    tok = tok.strip()
    if tok in ("", "n/a"):
        return None
    if tok == "inf":
        return math.inf
    try:
        return float(tok)
    except ValueError:
        return None


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


def delta(a: float | None, b: float | None) -> float | None:
    """b - a, with ``inf`` handled as the value it actually is.

    ``inf - inf`` is 0 here (both records say "no -180 deg crossing in band",
    which is agreement, not an indeterminate form), while a finite-vs-infinite
    pair is genuinely unbounded and comes back as ``None`` -- the flip itself
    is reported separately as a verdict change.
    """
    if a is None or b is None:
        return None
    if math.isinf(a) and math.isinf(b):
        return 0.0
    if math.isinf(a) or math.isinf(b):
        return None
    return b - a


def fmt(v: float | None, nd: int = 2) -> str:
    if v is None:
        return ""
    if math.isinf(v):
        return "inf"
    return f"{v:.{nd}f}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("baseline", help="record-id of the baseline run")
    ap.add_argument("head", help="record-id of the run being compared to it")
    ap.add_argument("--write-delta", default="",
                    help="record-id to write records/<id>-delta.csv under")
    ap.add_argument("--pm-report-deg", type=float, default=1.0,
                    help="list points whose phase margin moved by more than "
                         "this (default 1.0 deg)")
    args = ap.parse_args()

    base = load(args.baseline)
    head = load(args.head)

    only_base = sorted(set(base) - set(head))
    only_head = sorted(set(head) - set(base))
    common = sorted(set(base) & set(head))
    if not common:
        print("FATAL: the two records share no matrix points", file=sys.stderr)
        return 1

    print(f"baseline : {args.baseline}  ({len(base)} points)")
    print(f"head     : {args.head}  ({len(head)} points)")
    print(f"common   : {len(common)} points"
          f"{'' if not (only_base or only_head) else f' ; baseline-only {len(only_base)}, head-only {len(only_head)}'}")
    print()

    rows = []
    pass_to_fail, fail_to_pass = [], []
    res_pass_to_fail, res_fail_to_pass = [], []
    for key in common:
        b, h = base[key], head[key]
        pm_b, pm_h = _num(b["phase_margin_deg"]), _num(h["phase_margin_deg"])
        gm_b, gm_h = _num(b["gain_margin_db"]), _num(h["gain_margin_db"])
        f0_b, f0_h = _num(b["f_crossover_hz"]), _num(h["f_crossover_hz"])
        rs_b, rs_h = _num(b["resurgence_db"]), _num(h["resurgence_db"])
        d_pm, d_gm = delta(pm_b, pm_h), delta(gm_b, gm_h)
        d_rs = delta(rs_b, rs_h)
        d_f0_pct = (
            None if f0_b in (None, 0) or f0_h is None
            else 100.0 * (f0_h - f0_b) / f0_b
        )
        if b["result"] == "PASS" and h["result"] == "FAIL":
            pass_to_fail.append(key)
        if b["result"] == "FAIL" and h["result"] == "PASS":
            fail_to_pass.append(key)
        if b["resurgence_result"] == "PASS" and h["resurgence_result"] == "FAIL":
            res_pass_to_fail.append(key)
        if b["resurgence_result"] == "FAIL" and h["resurgence_result"] == "PASS":
            res_fail_to_pass.append(key)
        rows.append(
            dict(
                corner_id=key[0], process=b["process"], temp_c=b["temp_c"],
                vin_v=b["vin_v"], iload_ma=key[1], ceff_uf=key[2],
                esr_ohm=key[3],
                pm_base=pm_b, pm_head=pm_h, d_pm=d_pm,
                gm_base=gm_b, gm_head=gm_h, d_gm=d_gm,
                f0_base=f0_b, f0_head=f0_h, d_f0_pct=d_f0_pct,
                res_base=rs_b, res_head=rs_h, d_res=d_rs,
                result_base=b["result"], result_head=h["result"],
                res_result_base=b["resurgence_result"],
                res_result_head=h["resurgence_result"],
            )
        )

    n_pass_b = sum(1 for k in common if base[k]["result"] == "PASS")
    n_pass_h = sum(1 for k in common if head[k]["result"] == "PASS")
    n_res_b = sum(1 for k in common if base[k]["resurgence_result"] == "FAIL")
    n_res_h = sum(1 for k in common if head[k]["resurgence_result"] == "FAIL")

    print("DR-0001 verdict (PM >= 45 deg and GM >= 10 dB):")
    print(f"  PASS  baseline {n_pass_b}/{len(common)}   head {n_pass_h}/{len(common)}"
          f"   delta {n_pass_h - n_pass_b:+d}")
    print(f"  PASS -> FAIL : {len(pass_to_fail)}")
    print(f"  FAIL -> PASS : {len(fail_to_pass)}")
    print()
    print("DR-0008 precondition (resurgence_db <= 0 dB):")
    print(f"  flagged  baseline {n_res_b}/{len(common)}   head {n_res_h}/{len(common)}")
    print(f"  PASS -> FAIL : {len(res_pass_to_fail)}")
    print(f"  FAIL -> PASS : {len(res_fail_to_pass)}")
    print()

    def spread(field: str, label: str, unit: str, nd: int = 3) -> None:
        vals = [(abs(r[field]), r) for r in rows if r[field] is not None]
        n_none = len(rows) - len(vals)
        if not vals:
            print(f"  {label}: no comparable points")
            return
        vals.sort(key=lambda t: t[0])
        worst = vals[-1][1]
        med = vals[len(vals) // 2][0]
        p99 = vals[int(0.99 * (len(vals) - 1))][0]
        print(f"  {label}: median {med:.{nd}f} {unit}, p99 {p99:.{nd}f} {unit}, "
              f"max {vals[-1][0]:.{nd}f} {unit} at {worst['corner_id']} / "
              f"{worst['iload_ma']}mA / {worst['ceff_uf']}uF / {worst['esr_ohm']}ohm"
              f"{'' if not n_none else f'  ({n_none} points not comparable)'}")

    print("Per-point movement (head - baseline), over the common matrix:")
    spread("d_pm", "|delta phase margin|", "deg")
    spread("d_gm", "|delta gain margin| ", "dB")
    spread("d_f0_pct", "|delta crossover|   ", "%")
    spread("d_res", "|delta resurgence|  ", "dB")
    print()

    big = sorted(
        (r for r in rows if r["d_pm"] is not None
         and abs(r["d_pm"]) > args.pm_report_deg),
        key=lambda r: -abs(r["d_pm"]),
    )
    print(f"points whose phase margin moved by more than "
          f"{args.pm_report_deg:g} deg: {len(big)}")
    for r in big[:20]:
        print(f"  {r['corner_id']:<20} {r['iload_ma']:>5}mA {r['ceff_uf']:>5}uF "
              f"{r['esr_ohm']:>6}ohm   PM {fmt(r['pm_base'])} -> {fmt(r['pm_head'])} "
              f"({r['d_pm']:+.2f})   {r['result_base']} -> {r['result_head']}")
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
