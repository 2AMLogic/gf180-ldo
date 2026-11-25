#!/usr/bin/env python3
"""Current-limit PVT matrix through ``klt sim`` (issue #320).

    python3 sim/current-limit/testbench/klt_run.py --record-id <id> \\
        [--dut design/netlist/ldo_core.spice] [--baseline-ref origin/main]

Submits ``klt_body.spice`` over the 63-point PVT matrix (7 process x
3 temperatures x 3 supplies), for the committed DUT and -- with
``--baseline-ref`` -- for the DUT at that git ref too, as two jobs on the same
backend, so the comparison is same-binary by construction. Logs, the klt
reports, a frozen copy of each DUT netlist and ``summary.csv`` land in the
git-ignored staging tree ``sim/.work/.stage/current-limit/`` (DR-0044, issue
#646), never under ``sim/current-limit/corners/``: a run becomes evidence only
when ``sim/run_store_evidence.py --kind corners`` mints it, committing the
manifest, the hand-written Markdown record and the ``klt-report.json``
envelopes; an unminted run leaves the tree clean. Grading imports
summarize.py's ratified DR-0005 bounds
(``ILIM_WINDOW_MA`` / ``PSHORT_MAX_MW``) rather than restating them, so this
grader and summarize.py's ``checks()`` -- still the rollup for the committed
bash-era logs under ``corners/`` -- cannot disagree on the same spec rows.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import evidence_store as store  # noqa: E402
from harness import klt_batch as kb  # noqa: E402
from harness import pdk  # noqa: E402
from harness import tb_adapter  # noqa: E402
from harness.klt_ab import add_ab_args, run_ab, write_summary_csv  # noqa: E402
from harness.loader import load_script  # noqa: E402
# summarize.py is loaded by path under a unique name, never a bare
# ``from summarize import ...``: the bare name is ambiguous (current-limit,
# enable-shutdown and soft-start each ship a summarize.py), so it binds
# whichever bench's file resolved first in the interpreter (issue #700,
# enforced by sim/tests/test_sibling_import_names.py; same rule as the
# klt_run loads in sim/loop-stability/testbench/sweep.py).
summarize = load_script("current_limit_summarize", HERE / "summarize.py")
ILIM_WINDOW_MA, PSHORT_MAX_MW = summarize.ILIM_WINDOW_MA, summarize.PSHORT_MAX_MW

ILIM_MIN_MA, ILIM_MAX_MA = ILIM_WINDOW_MA

# index of each read point in `dc Vforce 0 1.764 0.012`
IDX = {"1764": 147, "1500": 125, "0900": 75, "0300": 25, "0000": 0}

MEASUREMENTS = (
    [{"name": "vf_1764", "expr": "v(vf)[147]", "unit": "V"}]
    + [{"name": f"ilim_{k}_ma", "expr": f"i(vforce)[{i}]*1e3", "unit": "mA",
        # Ratified Current limit row (DR-0005), from summarize.py; the 1.764 V
        # read point is the on-limit value summarize/grade() windows too.
        **({"limits": {"min": ILIM_MIN_MA, "max": ILIM_MAX_MA},
            "spec_row": "Current limit"} if k == "1764" else {})}
       for k, i in IDX.items()]
    + [
        {"name": "vout_50ma", "expr": "v(vout_r)[0]", "unit": "V"},
        {"name": "iload_50ma", "expr": "i(vlmeas_r)[0]*1e3", "unit": "mA"},
        {"name": "clg_50ma", "expr": "v(xreg.xilimit.clg)[0]", "unit": "V"},
        {"name": "isns_mv_50ma", "expr": "(v(xreg.xilimit.isns)[0]-v(vout_r)[0])*1e3", "unit": "mV"},
        {"name": "vth_mv_50ma", "expr": "(v(xreg.xilimit.vth)[0]-v(vout_r)[0])*1e3", "unit": "mV"},
        {"name": "vref_port_ua", "expr": "-i(vref)[0]*1e6", "unit": "uA"},
        {"name": "pshort_mw", "expr": "i(vforce)[0]*v(vin)[0]*1e3", "unit": "mW",
         # Ratified Thermal row's short-circuit clause (DR-0005), from
         # summarize.py: I into the Vout = 0 short (sweep index 0) times the
         # solved supply node at that same index. Named pshort_mw, not
         # p_short_mw, so grade()'s post-processed value stays distinct.
         "limits": {"max": PSHORT_MAX_MW}, "spec_row": "Thermal"},
    ]
)


def job(name: str, dut: Path, only=None) -> kb.Job:
    body = "\n".join([kb.DESIGN_PARAMS, kb.WNFLAG, (HERE / "klt_body.spice").read_text()])
    return kb.Job(name=name, body=body, dut_netlist=dut,
                  analysis={"kind": "dc", "args": "Vforce 0 1.764 0.012"},
                  measurements=MEASUREMENTS, timeout_s=900, stage_model_inputs=True,
                  **kb.only_axes(only))


def grade(v: dict, vin: float) -> dict:
    out = {}
    on = v.get("ilim_1764_ma")
    short = v.get("ilim_0000_ma")
    out["p_short_mw"] = None if short is None else short * vin
    out["in_window"] = on is not None and ILIM_MIN_MA <= on <= ILIM_MAX_MA
    # Finiteness guard (issue #823): the bound is one-sided, so without it a
    # non-finite p_short_mw (from ilim_0000_ma = -inf) passes and the staged
    # column would report thermal_ok for a garbage measurement, unlike the
    # two-sided in_window/reg_ok, which fail closed on NaN and both infinities.
    out["thermal_ok"] = (out["p_short_mw"] is not None and math.isfinite(out["p_short_mw"])
                         and out["p_short_mw"] <= PSHORT_MAX_MW)
    vo = v.get("vout_50ma")
    out["reg_ok"] = vo is not None and 1.764 <= vo <= 1.836
    if v.get("ilim_1500_ma") and short is not None:
        out["flat_pct"] = (short - v["ilim_1500_ma"]) / v["ilim_1500_ma"] * 100
    if v.get("vth_mv_50ma"):
        out["sense_margin_pct"] = (v["vth_mv_50ma"] - v["isns_mv_50ma"]) / v["vth_mv_50ma"] * 100
    return out


def main(argv=None, *, preflight=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_ab_args(ap, REPO)
    args = ap.parse_args(argv)
    dest = tb_adapter.stage_corner_dir(REPO, "current-limit", args.record_id)
    if (HERE.parent / "corners" / args.record_id).exists():
        raise SystemExit(f"sim/current-limit/corners/{args.record_id}/ already exists; "
                         "append-only evidence is never rewritten -- choose another --record-id")
    # An evidence run must be storable before any fleet time is spent (DR-0044):
    # no broker, no `klt artifact` verb, or an unreachable broker refuses now.
    # There is no commit-the-bytes fallback. An `--only` debug point is not
    # evidence and needs no store.
    if args.only is None:
        try:
            (preflight or store.preflight)(REPO)
        except store.StoreError as exc:
            print(f"EVIDENCE STORE UNAVAILABLE -- refusing to simulate: {exc}. "
                  "Evidence bytes go to the artifact store only (sim/README.md, "
                  '"Stored evidence"); an --only debug point needs no store.',
                  file=sys.stderr)
            return tb_adapter.EXIT_NOT_STORED
    # stage_model_inputs=True below stages model files: point klt's own PDK
    # search at the pin-checked tree before the first submit (issue #639).
    pdk.pin_klt_pdk_root()
    results = run_ab(lambda n, d: job(n, d, args.only), Path(args.dut), args.baseline_ref, dest, REPO, backend=args.backend)

    rows = []
    for tag, vals in results.items():
        for cid, v in sorted(vals.items()):
            vin = float(cid.rsplit("_", 1)[1].rstrip("v"))
            rows.append({"dut": tag or "new", "corner": cid, **{k: v.get(k) for k in v if not k.startswith("_")},
                         "status": v.get("_status"), "diagnostics": v.get("_diagnostics"), **grade(v, vin)})
    write_summary_csv(rows, dest / "summary.csv")
    print(f"staged  : {dest} (not evidence yet)")
    print(f"mint it : python3 sim/run_store_evidence.py current-limit {args.record_id} "
          f"{dest} --summary <summary.md> --kind corners")
    print("         (<summary.md> is the run's hand-written Markdown record, not summary.csv; "
          f"the store commits it as sim/current-limit/corners/{args.record_id}.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
