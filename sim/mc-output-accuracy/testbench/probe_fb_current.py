#!/usr/bin/env python3
"""Single-point FB-node current probe for the divider-identity residual (issue #484).

    python3 sim/mc-output-accuracy/testbench/probe_fb_current.py --out <dir> \\
        [--baseline-ref 2a7caecb] [--points ff,125,3.63 tt,27,3.30]

One ``ldo_core`` copy (no Monte Carlo), one ``op`` per PVT point, run locally
through ``klt sim`` (one unit each, never a grid). It reports, per DUT variant,
the divider's own two branch currents and their difference -- the current that
enters FB from somewhere other than the divider -- because KCL at FB gives
``VOUT - 1.5*FB = -Rtop * (I(Rbot) - I(Rtop))``: the ``divider_exact_uv`` residual
of ``tb.json`` is that difference times 300 kohm.

Variants: ``new`` (design/netlist/ldo_core.spice), ``baseline`` (the same file at
``--baseline-ref``) and ``new-nosoftstart`` (``new`` with the ``Xsoftstart``
instance deleted, a removal bisection).
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import klt_batch as kb  # noqa: E402
from harness import pdk  # noqa: E402

BODY = """\
.param vdd_nom=3.3
.param vdd_val={vin}
""" + kb.DESIGN_PARAMS + "\n" + kb.WNFLAG + """
.include "dut.spice"
Vin  VIN 0 dc {{vdd_val}}
Ven  EN  0 dc {{vdd_val}}
Vref VREF 0 DC 1.2
X1 VIN vo EN 0 loop loop VREF ldo_core
Rload vo 0 1.8k
Resr vo nesr 0.1
Cout nesr 0 1u
"""

MEAS = [
    {"name": "vout", "expr": "v(vo)"},
    {"name": "fb", "expr": "v(x1.fb)"},
    {"name": "i_rtop_na", "expr": "@r.x1.rtop[i]*1e9"},
    {"name": "i_rbot_na", "expr": "@r.x1.rbot[i]*1e9"},
    {"name": "divider_resid_uv", "expr": "(v(vo) - 1.5*v(x1.fb))*1e6"},
]


def variants(baseline_ref: str | None, tmp: Path) -> dict[str, Path]:
    cur = REPO / "design/netlist/ldo_core.spice"
    out = {"new": cur}
    if baseline_ref:
        p = tmp / "baseline.spice"
        p.write_bytes(subprocess.run(["git", "-C", str(REPO), "show", f"{baseline_ref}:design/netlist/ldo_core.spice"],
                                     check=True, capture_output=True).stdout)
        out["baseline"] = p
    text = cur.read_text()
    stripped = re.sub(r"^Xsoftstart .*$", "", text, flags=re.M)
    assert stripped != text, "Xsoftstart instance not found"
    p = tmp / "nosoftstart.spice"
    p.write_text(stripped)
    out["new-nosoftstart"] = p
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--baseline-ref", default=None)
    ap.add_argument("--points", nargs="+", default=["ff,125,3.63", "tt,27,3.30"])
    a = ap.parse_args()
    import os
    os.environ.setdefault("PDK_ROOT", str(pdk.find_pdk().path.parent))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix="fbprobe-") as t:
        tmp = Path(t)
        for tag, dut in variants(a.baseline_ref, tmp).items():
            for pt in a.points:
                axes = kb.only_axes(pt)
                vin = axes["supplies"][0]
                job = kb.Job(name=f"{tag}-{pt}", body=BODY.format(vin=vin), dut_netlist=dut,
                             analysis={"kind": "op", "args": ""}, measurements=MEAS,
                             supply_key="vdd_val", supplies=(vin,), supply_in_body=True,
                             stage_model_inputs=True, timeout_s=300,
                             ngspice_init=("set numdgt=10", "set measureprec=10"),
                             process=axes["process"], temps=axes["temps"])
                sub = out / tag / pt.replace(",", "_")
                req = kb.stage(job, tmp / f"{tag}-{pt}")
                report = kb.run(req, tmp / f"{tag}-{pt}-out", backend="local")
                vals = kb.collect(report, job, sub)
                for cid, v in vals.items():
                    rows.append({"dut": tag, "corner": cid, **v})
                    print(tag, cid, {k: v[k] for k in ("vout", "fb", "i_rtop_na", "i_rbot_na", "divider_resid_uv")})
    keys = ["dut", "corner", "vout", "fb", "i_rtop_na", "i_rbot_na", "divider_resid_uv", "_status", "_diagnostics"]
    with open(out / "probe.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
