#!/usr/bin/env python3
"""Soft-start transient matrix through ``klt sim`` (issue #320).

    python3 sim/soft-start/testbench/klt_run.py --record-id <id> \\
        [--dut design/netlist/ldo_core.spice] [--baseline-ref origin/main] [--only tt,27,3.30]

Two requests per DUT, covering the same 163 points run.sh does:

* ``main``  -- 1 uF / 100 mohm / 36 ohm over the 63-point matrix;
* ``extra`` -- the five run.sh EXTRA_CAPS configurations, as five independent
  instances in one transient (klt_body.spice.in), over the 20-point
  bracketing subset {tt ff ss res_ff res_ss} x {-40, 125 C} x {2.97, 3.63 V}.

Measurement definitions are tb_soft_start.spice.in's own ``meas`` lines,
moved to top-level ``.meas`` cards; ``slope_vpms`` is 1.0 V over
t(1.4 V) - t(0.4 V) exactly as summarize.py computes it. Not ported:
``dvout_min`` (its 105 us .. 8 ms window cannot be expressed as one scalar
expression in klt's single .control block without also catching the disable
edge) -- ``dvout_max`` is taken over the whole 9 ms window, which for a rising
startup is the same maximum. With ``--baseline-ref`` both DUTs run on the
same backend. Output: ``sim/soft-start/corners/<record-id>/``.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import klt_batch as kb  # noqa: E402
from harness.klt_ab import run_ab  # noqa: E402

MAIN = [("1u", "0.1", "36")]
EXTRA = [("0.33u", "0.001", "36"), ("0.33u", "0.5", "36"), ("4.7u", "0.001", "36"),
         ("4.7u", "0.5", "36"), ("1u", "0.1", "1e9")]
EXTRA_AXES = {"process": ("tt", "ff", "ss", "res_ff", "res_ss"), "temps": (-40, 125), "supplies": (2.97, 3.63)}


def body(configs) -> str:
    tmpl = (HERE / "klt_body.spice.in").read_text()
    head, rest = tmpl.split("*BEGIN-INSTANCE\n")
    inst, tail = rest.split("*END-INSTANCE\n")
    blocks = []
    for k, (cout, esr, rload) in enumerate(configs, 1):
        blocks.append(inst.replace("@K@", str(k)).replace("@COUT@", cout)
                      .replace("@ESR@", esr).replace("@RLOAD@", rload))
    text = "\n".join([kb.DESIGN_PARAMS, kb.WNFLAG, head + "".join(blocks) + tail])
    assert not re.search(r"@[A-Z]+@", text), "unsubstituted token"
    return text


def measurements(n: int) -> list:
    out = []
    for k in range(1, n + 1):
        vo, x = f"v(vout{k})", f"xdut{k}.xsoftstart"
        cards = {
            "t_v04": f"WHEN {vo}=0.4 RISE=1",
            "t_v14": f"WHEN {vo}=1.4 RISE=1",
            "t_startup": f"TRIG v(en) VAL=1.4 RISE=1 TARG {vo} VAL=1.764 RISE=1",
            "vout_max_en": f"MAX {vo} FROM=101u TO=8m",
            "vout_settled": f"FIND {vo} AT=7.9m",
            "icap_peak_a": f"MAX i(vcmeas{k}) FROM=100u TO=8m",
            "isup_peak_a": f"MAX i(vamm{k}) FROM=100u TO=8m",
            "ssr_end": f"FIND v({x}.ssr) AT=7.9m",
            "hg_end": f"FIND v({x}.hg) AT=7.9m",
            "vout_pp_late": f"PP {vo} FROM=7.5m TO=7.9m",
            "vout_off_tran": f"FIND {vo} AT=8.9m",
            "ssr_off_tran": f"FIND v({x}.ssr) AT=8.9m",
        }
        for name, spec in cards.items():
            out.append({"name": f"{name}_{k}", "spice": f".meas tran {name}_{k} {spec}"})
        out.append({"name": f"dvout_max_vpms_{k}", "expr": f"vecmax(deriv({vo}))*1e-3"})
    return out


def job(name, dut, configs, axes) -> kb.Job:
    return kb.Job(name=name, body=body(configs), dut_netlist=dut,
                  analysis={"kind": "tran", "args": "1u 9m"},
                  measurements=measurements(len(configs)), timeout_s=7200, **axes)


def derive(v: dict, k: int) -> dict:
    g = lambda n: v.get(f"{n}_{k}")  # noqa: E731
    d = {}
    if g("t_v04") is not None and g("t_v14") is not None:
        d["slope_vpms"] = 1.0 / ((g("t_v14") - g("t_v04")) * 1e3)
    for n in ("t_startup",):
        d[f"{n}_ms"] = None if g(n) is None else g(n) * 1e3
    d["icap_peak_ma"] = None if g("icap_peak_a") is None else g("icap_peak_a") * 1e3
    d["isup_peak_ma"] = None if g("isup_peak_a") is None else g("isup_peak_a") * 1e3
    for n in ("vout_max_en", "vout_settled", "ssr_end", "hg_end", "vout_pp_late",
              "vout_off_tran", "ssr_off_tran", "dvout_max_vpms"):
        d[n] = g(n)
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--dut", default=str(REPO / "design/netlist/ldo_core.spice"))
    ap.add_argument("--baseline-ref", default=None)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--only", default=None, help="one point, e.g. tt,27,3.30 (debug; runs locally)")
    ap.add_argument("--part", choices=("main", "extra", "both"), default="both")
    args = ap.parse_args(argv)
    dest = HERE.parent / "corners" / args.record_id
    parts = [("main", MAIN, {}), ("extra", EXTRA, EXTRA_AXES)]
    parts = [p for p in parts if args.part in (p[0], "both")]

    rows = []
    for part, configs, axes in parts:
        ax = kb.only_axes(args.only) or axes
        res = run_ab(lambda n, d, c=configs, a=ax: job(n, d, c, a), Path(args.dut), args.baseline_ref,
                     dest / part, REPO, backend=args.backend)
        for tag, vals in res.items():
            for cid, v in sorted(vals.items()):
                for k, (cout, esr, rload) in enumerate(configs, 1):
                    rows.append({"dut": tag, "corner": cid, "cout": cout, "esr": esr, "rload": rload,
                                 **derive(v, k), "status": v.get("_status"),
                                 "diagnostics": v.get("_diagnostics")})
    keys = list(rows[0]) if rows else []
    with open(dest / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {dest / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
