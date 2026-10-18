#!/usr/bin/env python3
"""Enable/shutdown PVT matrix through ``klt sim`` (issue #366).

    python3 sim/enable-shutdown/testbench/klt_run.py --record-id <id> \\
        [--dut design/netlist/ldo_core.spice] [--baseline-ref origin/main] [--only tt,27,3.30]

The same 63-point grid run.sh sweeps (7 process x -40/27/125 C x 2.97/3.30/3.63 V).
tb_enable_shutdown.spice.in chains four analyses in one ``.control`` block;
``klt sim`` runs one analysis per corner, so each analysis state is its own
request over the same grid (klt_body.spice.in is the shared circuit):

* ``enabled``  -- op, full rated load;
* ``disabled`` -- op, output free;
* ``leakage``  -- op, disabled, output forced to 0 V through 1 mohm;
* ``tran``     -- 1 us .. 9 ms enable/disable transitions at the rated load.

The returned values are merged per corner into ``<corner-id>.log`` files of
``m_<name> = <value>`` lines -- the names run.sh's ngspice logs carry -- so
summarize.py rolls them up unchanged into ``summary.csv`` and its report.
The deck's ``let`` / ``meas`` lines are expressed as ``klt`` ``expr`` /
top-level ``.meas`` measurements of the same definitions. Nothing is dropped
or approximated; the one structural difference is that EN is a behavioural
source (``v(vin) * v(enctl)``) instead of a source set to the supply value,
which is the same voltage. With ``--baseline-ref`` both DUTs run on the same
backend (baseline logs go to ``baseline/``). Raw per-state reports and logs:
``klt-<state>/<new|baseline>/``. Output: ``sim/enable-shutdown/corners/<record-id>/``.
A failed submit raises; this driver never falls back to a local grid.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import klt_batch as kb  # noqa: E402
from harness.klt_ab import add_ab_args, run_ab  # noqa: E402

TRAN_ENCTL = "DC 0 PWL(0 0 100u 0 101u 1 8m 1 8.001m 0)"
IQ_SUM = "-i(vin)*1e6 - i(vref)*1e6"  # supply + reference delivery, uA


def expr(name, e):
    return {"name": name, "expr": e}


def meas(name, spec):
    return {"name": name, "spice": f".meas tran {name} {spec}"}


#: state -> (ENCTL source value, Rload, Rforce, analysis, measurements, timeout_s)
STATES = {
    "enabled": ("DC 1", "36", "1G", {"kind": "op", "args": ""}, [
        expr("vout_en", "v(vout)"),
        expr("iload_en_ma", "i(vlmeas)*1e3"),
        expr("isup_en_ua", "-i(vin)*1e6"),
        expr("iref_en_ua", "-i(vref)*1e6"),
        # quiescent = everything delivered that does not reach the load
        expr("iq_en_ua", f"{IQ_SUM} - i(vlmeas)*1e6"),
    ], 900),
    "disabled": ("DC 0", "1G", "1G", {"kind": "op", "args": ""}, [
        expr("vout_off", "v(vout)"),
        expr("isup_off_ua", "-i(vin)*1e6"),
        expr("iref_off_ua", "-i(vref)*1e6"),
        expr("iloop_off_ua", "i(vloop)*1e6"),
        expr("pg_off", "v(pg)"),
        expr("clg_off", "v(xdut.xilimit.clg)"),
        expr("nbias_off", "v(xdut.xerramp.nbias)"),
        expr("iq_off_ua", IQ_SUM),
    ], 900),
    "leakage": ("DC 0", "1G", "1m", {"kind": "op", "args": ""}, [
        expr("ileak_vin_vout_ua", "i(vforce)*1e6"),
    ], 900),
    "tran": (TRAN_ENCTL, "36", "1G", {"kind": "tran", "args": "1u 9m"}, [
        meas("t_startup", "TRIG v(en) VAL=1.4 RISE=1 TARG v(vout) VAL=1.764 RISE=1"),
        meas("vout_settled", "FIND v(vout) AT=7.9m"),
        meas("vout_max_en", "MAX v(vout) FROM=101u TO=8m"),
        meas("vout_min_reg", "MIN v(vout) FROM=7m TO=8m"),
        meas("isup_peak_ma", "MAX v(ivin) FROM=100u TO=8m"),
        meas("clg_min_reg", "MIN v(xdut.xilimit.clg) FROM=7m TO=8m"),
        meas("isup_peak_reg_ma", "MAX v(ivin) FROM=7m TO=8m"),
        meas("vout_pp_late", "PP v(vout) FROM=7.5m TO=7.9m"),
        meas("vout_off_tran", "FIND v(vout) AT=8.9m"),
        meas("vout_max_off", "MAX v(vout) FROM=8.5m TO=9m"),
        meas("pg_off_tran", "FIND v(pg) AT=8.9m"),
    ], 1800),
}


def body(enctl: str, rload: str, rforce: str) -> str:
    text = (HERE / "klt_body.spice.in").read_text()
    for tok, val in (("@ENCTL@", enctl), ("@RLOAD@", rload), ("@RFORCE@", rforce)):
        text = text.replace(tok, val)
    assert not re.search(r"@[A-Z]+@", text), "unsubstituted token"
    return "\n".join([kb.DESIGN_PARAMS, kb.WNFLAG, text])


def job(state: str, tag: str, dut: Path, axes: dict) -> kb.Job:
    enctl, rload, rforce, analysis, measurements, timeout_s = STATES[state]
    return kb.Job(name=f"{state}-{tag}", body=body(enctl, rload, rforce), dut_netlist=dut,
                  analysis=analysis, measurements=measurements, timeout_s=timeout_s, **axes)


def write_logs(per_state: dict, dest: Path) -> list[str]:
    """Merge the states' values per corner into run.sh-style ``m_<name> = <value>`` logs.

    Returns problems (non-ok corner, missing measurement) for the caller to print;
    a measurement with no value is omitted so summarize.py fails loud on it.
    """
    dest.mkdir(parents=True, exist_ok=True)
    problems = []
    cids = sorted({cid for vals in per_state.values() for cid in vals})
    for cid in cids:
        lines = []
        for state, vals in per_state.items():
            v = vals.get(cid)
            if v is None:
                problems.append(f"{cid}: state {state} returned no corner")
                continue
            if v.get("_diagnostics"):
                problems.append(f"{cid}: state {state} diagnostics {v['_diagnostics']}")
            for m in STATES[state][4]:
                x = v.get(m["name"])
                if x is None:
                    problems.append(f"{cid}: state {state} has no value for {m['name']}")
                else:
                    lines.append(f"m_{m['name']} = {x:.9e}")
        (dest / f"{cid}.log").write_text("\n".join(lines) + "\n")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_ab_args(ap, REPO)
    args = ap.parse_args(argv)
    dest = HERE.parent / "corners" / args.record_id
    axes = kb.only_axes(args.only)

    def go(state):
        return state, run_ab(lambda n, d, s=state: job(s, n, d, axes), Path(args.dut), args.baseline_ref,
                             dest / f"klt-{state}", REPO, backend=args.backend)

    # Off-host: the four requests are submitted at once. Local (--only, or an
    # explicit --backend local): one state at a time, never a local fan-out.
    workers = 1 if (args.only or args.backend == "local") else len(STATES)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = dict(pool.map(go, STATES))

    proc = " ".join(axes.get("process", kb.LDO_PROCESS))
    temps = " ".join(f"{int(t)}" if float(t).is_integer() else f"{t}" for t in axes.get("temps", kb.TEMPS))
    supplies = " ".join(f"{s:.2f}" for s in axes.get("supplies", kb.SUPPLIES))
    status = 0
    for tag in next(iter(results.values())):
        out = dest if tag == "new" else dest / tag
        problems = write_logs({s: results[s][tag] for s in STATES}, out)
        for p in problems:
            print(f"WARNING [{tag}] {p}", file=sys.stderr)
        print(f"== {tag}: {out}")
        rc = subprocess.run([sys.executable, str(HERE / "summarize.py"), str(out), str(out / "summary.csv"),
                             proc, temps, supplies]).returncode
        status = status or rc
    return status


if __name__ == "__main__":
    sys.exit(main())
