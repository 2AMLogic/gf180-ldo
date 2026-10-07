#!/usr/bin/env python3
"""Peak-event convergence check through ``klt sim`` (issue #351).

    python3 sim/soft-start/testbench/klt_peak_run.py --record-id <id> --baseline-ref <ref> \\
        [--dut design/netlist/ldo_core.spice] [--only tt,27,3.30] [--tmax 2n] [--tstop 400u] [--part main|extra|both]

klt_run.py's ``tran 1u 9m`` leaves the ~2 us pass-gate event that sets the
startup peak under-resolved (the peak value depends on the solver's step
there; see record 20261007-ss-351-peak-event). This driver reuses klt_run's
body and DUT A/B plumbing but runs a short, fine-step transient
(default ``tran 2n 400u``) that covers the enable edge and the event, and
reports only the quantities that event sets: peak Icap, its time, peak supply
current and peak dV/dt. Multi-corner requests go to the batch fleet exactly as
klt_run.py's do; ``--only`` runs one point locally.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import klt_run as kr  # noqa: E402

kb, run_ab = kr.kb, kr.run_ab
REPO = kr.REPO


def measurements(n: int, tstop: str) -> list:
    out = []
    for k in range(1, n + 1):
        vo = f"v(vout{k})"
        for name, spec in {
            "icap_peak_a": f"MAX i(vcmeas{k}) FROM=100u TO={tstop}",
            "t_icap_peak": f"MAX_AT i(vcmeas{k}) FROM=100u TO={tstop}",
            "isup_peak_a": f"MAX i(vamm{k}) FROM=100u TO={tstop}",
            "vout_at_end": f"FIND {vo} AT={tstop}",
        }.items():
            out.append({"name": f"{name}_{k}", "spice": f".meas tran {name}_{k} {spec}"})
        out.append({"name": f"dvout_max_vpms_{k}", "expr": f"vecmax(deriv({vo}))*1e-3"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--dut", default=str(REPO / "design/netlist/ldo_core.spice"))
    ap.add_argument("--baseline-ref", required=True)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--part", choices=("main", "extra", "both"), default="both")
    ap.add_argument("--tmax", default="2n")
    ap.add_argument("--tstop", default="400u")
    args = ap.parse_args(argv)
    dest = HERE.parent / "corners" / args.record_id
    parts = [p for p in (("main", kr.MAIN, {}), ("extra", kr.EXTRA, kr.EXTRA_AXES)) if args.part in (p[0], "both")]
    rows = []
    for part, configs, axes in parts:
        ax = kb.only_axes(args.only) or axes

        def factory(name, dut, c=configs, a=ax):
            return kb.Job(name=name, body=kr.body(c), dut_netlist=dut,
                          analysis={"kind": "tran", "args": f"{args.tmax} {args.tstop}"},
                          measurements=measurements(len(c), args.tstop), timeout_s=7200, **a)

        res = run_ab(factory, Path(args.dut), args.baseline_ref, dest / part, REPO, backend=args.backend)
        for tag, vals in res.items():
            for cid, v in sorted(vals.items()):
                for k, (cout, esr, rload) in enumerate(configs, 1):
                    g = lambda n: v.get(f"{n}_{k}")  # noqa: E731
                    rows.append({"dut": tag, "corner": cid, "cout": cout, "esr": esr, "rload": rload,
                                 "icap_peak_ma": None if g("icap_peak_a") is None else g("icap_peak_a") * 1e3,
                                 "t_icap_peak_us": None if g("t_icap_peak") is None else g("t_icap_peak") * 1e6,
                                 "isup_peak_ma": None if g("isup_peak_a") is None else g("isup_peak_a") * 1e3,
                                 "dvout_max_vpms": g("dvout_max_vpms"),
                                 "status": v.get("_status"), "diagnostics": v.get("_diagnostics")})
    with open(dest / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else [])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {dest / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
