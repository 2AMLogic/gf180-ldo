#!/usr/bin/env python3
"""mc-output-accuracy Monte Carlo grid through ``klt sim`` (issue #469).

    python3 sim/mc-output-accuracy/testbench/klt_run.py --record-id <id> \\
        [--dut design/netlist/ldo_core.spice] [--baseline-ref origin/main] \\
        [--only tt,27,3.30] [--samples 40] [--seed 469]

tb.json's 45 PVT points (tt ff ss fs sf x -40/27/125 C x 2.97/3.30/3.63 V), with
the bench's own 25 independent ldo_core copies per solve. The Monte Carlo loop
the local deck runs inside ``.control`` (``let mcit = 40`` redraws of
``mc_source``) is the request's ``monte_carlo`` form instead: ``n`` = 40 samples
per PVT point, ``vary: "mismatch"`` (the deck's ``sw_stat_mismatch = 1``,
``sw_stat_global = 0``), each sample a separate ``op`` with its own derived
``.options seed``. 25 copies x 40 samples = 1000 per point, as before.

The statistics are tb.json's ``measure`` definitions, computed here from the
per-sample values because ``klt`` evaluates a measurement per unit, not across
units: ``mean_mv`` / ``sigma_mv`` over all 25 x n values (n-1 divisor),
``worst_abs_mv`` their maximum |dVOUT|, ``n_bad_solves`` the samples in which
any copy landed more than 100 mV from 1.8 V, ``divider_exact_uv`` the maximum
over samples of |dVOUT1 - 1.5 dFB| in uV. A sample ``klt`` returns no value
for (a failed solve) is not in ``n_samples``, so a corner that lost samples
fails the 1000-sample check instead of reporting a thinner distribution.

Output: sim/mc-output-accuracy/corners/<record-id>/ -- per fleet request
``klt-<vin>v-<process>/<new|baseline>/`` (compact report, request, body, the DUT), one
``<corner>.log`` per PVT point carrying the ``MCSAMPLE <k> <dv1..dv25>`` lines
summarize.py reads, and ``summary.csv``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import klt_batch as kb  # noqa: E402
from harness import pdk, tb_adapter  # noqa: E402
from harness import testbench as tbmod  # noqa: E402
from harness.corners import resolve_corners, supply_points  # noqa: E402
from harness.klt_ab import add_ab_args, run_ab, write_summary_csv  # noqa: E402

COPIES = 25
SAMPLES = 40
SEED = 469
TB = tbmod.load(HERE)

MEASUREMENTS = (
    [{"name": f"dv_{k}", "expr": f"(v(vo{k}) - 1.8)*1e3"} for k in range(1, COPIES + 1)]
    + [{"name": "dfb", "expr": "(v(x1.fb) - 1.2)*1e3"}]
)


def job(name: str, dut: Path, vin: float, proc: str, only: str | None, samples: int, seed: int) -> kb.Job:
    axes = {"process": (proc,), "temps": tuple(TB.temperatures_c),
            **{k: v for k, v in kb.only_axes(only).items() if k != "supplies"}}
    return kb.Job(name=name, body=tb_adapter.body(TB, vin), dut_netlist=dut,
                  analysis={"kind": "op", "args": ""}, measurements=MEASUREMENTS,
                  supply_key="vdd_val", supplies=(vin,), supply_in_body=True,
                  stage_model_inputs=True, timeout_s=300,
                  ngspice_init=(f"set numdgt={tb_adapter.DIGITS}", f"set measureprec={tb_adapter.DIGITS}"),
                  monte_carlo={"n": samples, "seed": seed, "vary": "mismatch"}, **axes)


def sample_rows(report: dict, job_: kb.Job) -> dict[str, dict[int, dict]]:
    """{corner_id: {sample_index: {measurement: value}}} for the units that returned values."""
    out: dict[str, dict[int, dict]] = {}
    for c in report.get("corners", []):
        cid = kb.corner_id(c, job_.supply_key, job_.supplies[0])
        vals = {m["name"]: m.get("value") for m in c.get("measurements", [])}
        if c.get("status") == "error" or any(vals.get(m["name"]) is None for m in MEASUREMENTS):
            continue
        out.setdefault(cid, {})[int(c["monte_carlo"]["sample_index"])] = vals
    return out


def statistics(samples: dict[int, dict], expected_corners: int | None = None) -> dict:
    """tb.json's ``measure`` definitions over one PVT point's per-sample values."""
    dv = [s[f"dv_{k}"] for _, s in sorted(samples.items()) for k in range(1, COPIES + 1)]
    n = len(dv)
    s1, s2 = sum(dv), sum(x * x for x in dv)
    var = (s2 - s1 * s1 / n) / (n - 1) if n > 1 else float("nan")
    sd = math.sqrt(max(var, 0.0))
    bad = sum(1 for s in samples.values()
              if max(abs(s[f"dv_{k}"]) for k in range(1, COPIES + 1)) > 100)
    div = max((abs(s["dv_1"] - 1.5 * s["dfb"]) * 1e3 for s in samples.values()), default=float("nan"))
    return {"n_samples": n, "n_bad_solves": bad, "mean_mv": s1 / n, "sigma_mv": sd,
            "sigma3_mv": 3 * sd, "worst_abs_mv": max(abs(x) for x in dv),
            "vos_in_mean_uv": s1 / n / 1.5 * 1e3, "vos_in_sigma3_mv": 2 * sd,
            "divider_exact_uv": div}


def write_log(path: Path, cid: str, samples: dict[int, dict]) -> None:
    lines = [f"* mc-output-accuracy @ {cid} -- per-sample dVout (mV) of the {COPIES} ldo_core copies,",
             "* written by sim/mc-output-accuracy/testbench/klt_run.py from the klt sim report"]
    for k, (_, s) in enumerate(sorted(samples.items())):
        lines.append(f'"MCSAMPLE {k} ' + " ".join(f"{s[f'dv_{i}']:.6g}" for i in range(1, COPIES + 1)) + '"')
    path.write_text("\n".join(lines) + "\n")


def grade(stats: dict) -> bool:
    for key, lim in TB.checks.items():
        x = stats.get(key)
        if x is None or ("max" in lim and x > lim["max"]) or ("min" in lim and x < lim["min"]):
            return False
    return True


def compact(report: dict) -> dict:
    """The report minus what the per-sample logs already hold.

    ``klt`` returns every sample's measurements, artifact paths and a per-point
    coverage/statistics rollup: ~17 kB per sample, 30 MB for this grid. What a
    reader needs from the committed report is the job identity, the worker and
    PDK stamps, and per sample its status, diagnostics and derived seeds; the
    values are the ``MCSAMPLE`` lines in ``<corner>.log``.
    """
    out = {k: v for k, v in report.items() if k not in ("corners", "coverage", "measurements")}
    out["corners"] = [
        {"corner_id": c["corner_id"], "status": c["status"], "monte_carlo": c.get("monte_carlo"),
         "diagnostics": sorted({d.get("code", "") for d in c.get("diagnostics", [])})}
        for c in report.get("corners", [])]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_ab_args(ap, REPO)
    ap.add_argument("--samples", type=int, default=SAMPLES, help="Monte Carlo samples per PVT point")
    ap.add_argument("--seed", type=int, default=SEED, help="request.monte_carlo.seed (reproducible)")
    args = ap.parse_args(argv)
    os.environ.setdefault("PDK_ROOT", str(pdk.find_pdk().path.parent))
    dest = HERE.parent / "corners" / args.record_id
    only = kb.only_axes(args.only)
    supplies = only.get("supplies") or supply_points(TB.nominal_supply_v, TB.supply_tolerance)
    procs = only.get("process") or tuple(c.name for c in resolve_corners(TB.corners))
    # One request per supply x process (15 x 120 units): each stays well under the
    # fleet's 3600 s whole-job ceiling at ~9 s per 25-copy sample.
    shards = [(v, p) for v in supplies for p in procs]

    def go(shard):
        vin, proc = shard
        sub = dest / f"klt-{vin:.2f}v-{proc}"
        by_tag = run_ab(lambda n, d: job(n, d, vin, proc, args.only, args.samples, args.seed), Path(args.dut),
                        args.baseline_ref, sub, REPO, backend=args.backend)
        out = []
        for tag in by_tag:
            rep_path = sub / tag / "klt-report.json"
            report = json.loads(rep_path.read_text())
            j = job(tag, Path(args.dut), vin, proc, args.only, args.samples, args.seed)
            rows = sample_rows(report, j)
            rep_path.write_text(json.dumps(compact(report), indent=1, sort_keys=True) + "\n")
            for stale in (sub / tag).glob("*.log"):   # one arbitrary sample's raw log per point
                stale.unlink()
            out.append((tag, rows))
        return out

    workers = 1 if (args.only or args.backend == "local") else min(len(shards), tb_adapter.MAX_IN_FLIGHT)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        per_shard = list(pool.map(go, shards))

    rows = []
    for out in per_shard:
        for tag, by_corner in out:
            for cid, samples in sorted(by_corner.items()):
                st = statistics(samples)
                if tag == "new":
                    write_log(dest / f"{cid}.log", cid, samples)
                rows.append({"dut": tag, "corner": cid, **st, "status": "pass" if grade(st) else "fail",
                             "diagnostics": "", "pass": grade(st)})
    write_summary_csv(rows, dest / "summary.csv")
    expected = len(procs) * len(only.get("temps") or TB.temperatures_c) * len(supplies)
    got = sum(1 for r in rows if r["dut"] == "new")
    if got != expected:
        print(f"ERROR: {got} of {expected} PVT points returned samples; the rest lost every sample", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
