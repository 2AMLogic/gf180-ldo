#!/usr/bin/env python3
"""Current-limit PVT matrix through ``klt sim`` (issue #320).

    python3 sim/current-limit/testbench/klt_run.py --record-id <id> \\
        [--dut design/netlist/ldo_core.spice] [--baseline-ref origin/main]

Submits ``klt_body.spice`` over the 63-point matrix run.sh sweeps (7 process x
3 temperatures x 3 supplies), for the committed DUT and -- with
``--baseline-ref`` -- for the DUT at that git ref too, as two jobs on the same
backend, so the comparison is same-binary by construction. Logs, the klt
reports, a frozen copy of each DUT netlist and ``summary.csv`` land under
``sim/current-limit/corners/<record-id>/``. The record markdown is written by
hand, as for run.sh. Grading mirrors summarize.py's bounds (DR-0005).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import klt_batch as kb  # noqa: E402
from harness.klt_ab import run_ab  # noqa: E402

# index of each read point in `dc Vforce 0 1.764 0.012`
IDX = {"1764": 147, "1500": 125, "0900": 75, "0300": 25, "0000": 0}

MEASUREMENTS = (
    [{"name": "vf_1764", "expr": "v(vf)[147]", "unit": "V"}]
    + [{"name": f"ilim_{k}_ma", "expr": f"i(vforce)[{i}]*1e3", "unit": "mA"} for k, i in IDX.items()]
    + [
        {"name": "vout_50ma", "expr": "v(vout_r)[0]", "unit": "V"},
        {"name": "iload_50ma", "expr": "i(vlmeas_r)[0]*1e3", "unit": "mA"},
        {"name": "clg_50ma", "expr": "v(xreg.xilimit.clg)[0]", "unit": "V"},
        {"name": "isns_mv_50ma", "expr": "(v(xreg.xilimit.isns)[0]-v(vout_r)[0])*1e3", "unit": "mV"},
        {"name": "vth_mv_50ma", "expr": "(v(xreg.xilimit.vth)[0]-v(vout_r)[0])*1e3", "unit": "mV"},
        {"name": "vref_port_ua", "expr": "-i(vref)[0]*1e6", "unit": "uA"},
    ]
)


def job(name: str, dut: Path, only=None) -> kb.Job:
    body = "\n".join([kb.DESIGN_PARAMS, kb.WNFLAG, (HERE / "klt_body.spice").read_text()])
    return kb.Job(name=name, body=body, dut_netlist=dut,
                  analysis={"kind": "dc", "args": "Vforce 0 1.764 0.012"},
                  measurements=MEASUREMENTS, timeout_s=900, **kb.only_axes(only))


def grade(v: dict, vin: float) -> dict:
    out = {}
    on = v.get("ilim_1764_ma")
    short = v.get("ilim_0000_ma")
    out["p_short_mw"] = None if short is None else short * vin
    out["in_window"] = on is not None and 62.0 <= on <= 95.0
    out["thermal_ok"] = out["p_short_mw"] is not None and out["p_short_mw"] <= 346.0
    vo = v.get("vout_50ma")
    out["reg_ok"] = vo is not None and 1.764 <= vo <= 1.836
    if v.get("ilim_1500_ma") and short is not None:
        out["flat_pct"] = (short - v["ilim_1500_ma"]) / v["ilim_1500_ma"] * 100
    if v.get("vth_mv_50ma"):
        out["sense_margin_pct"] = (v["vth_mv_50ma"] - v["isns_mv_50ma"]) / v["vth_mv_50ma"] * 100
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--dut", default=str(REPO / "design/netlist/ldo_core.spice"))
    ap.add_argument("--baseline-ref", default=None)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--only", default=None, help="one point, e.g. tt,27,3.30 (debug; runs locally)")
    args = ap.parse_args(argv)
    dest = HERE.parent / "corners" / args.record_id
    results = run_ab(lambda n, d: job(n, d, args.only), Path(args.dut), args.baseline_ref, dest, REPO, backend=args.backend)

    rows = []
    for tag, vals in results.items():
        for cid, v in sorted(vals.items()):
            vin = float(cid.rsplit("_", 1)[1].rstrip("v"))
            rows.append({"dut": tag or "new", "corner": cid, **{k: v.get(k) for k in v if not k.startswith("_")},
                         "status": v.get("_status"), "diagnostics": v.get("_diagnostics"), **grade(v, vin)})
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("dut", "corner"), k))
    with open(dest / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {dest / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
