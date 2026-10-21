#!/usr/bin/env python3
"""Quiescent-current grid through ``klt sim`` (issue #320).

    python3 sim/quiescent-current/testbench/klt_run.py --record-id <id> \\
        [--dut design/netlist/ldo_core.spice] [--baseline-ref origin/main] [--only tt,27,3.30]

The 81-point grid tb.json declares (tt ff ss fs sf res_ff res_ss bjt_ff bjt_ss
x -40/27/125 C x 2.97/3.30/3.63 V), same measurements and same bounds, plus
the VREF-port current of each instance (see klt_body.spice). With
``--baseline-ref`` the DUT at that ref is run as a second job on the same
backend. Output: ``sim/quiescent-current/corners/<record-id>/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import klt_batch as kb  # noqa: E402
from harness.klt_ab import add_ab_args, run_ab, write_summary_csv  # noqa: E402

PROCESS = kb.LDO_PROCESS + ("bjt_ff", "bjt_ss")
TB = json.loads((HERE / "tb.json").read_text())

MEASUREMENTS = (
    [{"name": k, "expr": v} for k, v in TB["measure"].items()]
    + [
        {"name": "iref_en_na", "expr": "-i(vref_en)*1e9"},
        {"name": "iref_dis_na", "expr": "-i(vref_dis)*1e9"},
        {"name": "iref_full_na", "expr": "-i(vref_full)*1e9"},
    ]
)


def job(name: str, dut: Path, only=None) -> kb.Job:
    body = "\n".join([kb.DESIGN_PARAMS, kb.WNFLAG, (HERE / "klt_body.spice").read_text()])
    axes = {"process": PROCESS, **kb.only_axes(only)}
    return kb.Job(name=name, body=body, dut_netlist=dut, analysis={"kind": "op", "args": ""},
                  measurements=MEASUREMENTS, supply_key="vsup", timeout_s=900, stage_model_inputs=True, **axes)


def grade(v: dict) -> bool:
    for k, lim in TB["checks"].items():
        x = v.get(k)
        if x is None or ("max" in lim and x > lim["max"]) or ("min" in lim and x < lim["min"]):
            return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_ab_args(ap, REPO)
    args = ap.parse_args(argv)
    dest = HERE.parent / "corners" / args.record_id
    results = run_ab(lambda n, d: job(n, d, args.only), Path(args.dut), args.baseline_ref, dest, REPO,
                     backend=args.backend)
    rows = []
    for tag, vals in results.items():
        for cid, v in sorted(vals.items()):
            rows.append({"dut": tag, "corner": cid, **{k: v[k] for k in v if not k.startswith("_")},
                         "status": v.get("_status"), "diagnostics": v.get("_diagnostics"),
                         "pass": grade(v)})
    write_summary_csv(rows, dest / "summary.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
