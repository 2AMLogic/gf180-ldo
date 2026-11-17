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
same backend. Those bytes land in the git-ignored staging tree
``sim/.work/.stage/soft-start/`` (DR-0044, issue #646), never under
``sim/soft-start/corners/``: a run becomes evidence only when
``sim/run_store_evidence.py --kind corners`` mints it, committing the
manifest, the hand-written Markdown record and the ``klt-report.json``
envelopes; an unminted run leaves the tree clean. A record sharded with
``--process`` spans several invocations: every shard accumulates into the
same staged record, and the mint runs once, after the last shard (the store
refuses a second mint of the same record id).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import deck  # noqa: E402
from harness import evidence_store as store  # noqa: E402
from harness import klt_batch as kb  # noqa: E402
from harness import tb_adapter  # noqa: E402
from harness.klt_ab import add_ab_args, run_ab, write_summary_csv  # noqa: E402

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
        blocks.append(deck.render(inst, {
            "K": str(k), "COUT": cout, "ESR": esr, "RLOAD": rload,
        }, source="klt_body.spice.in instance block"))
    return deck.require_substituted(
        "\n".join([kb.DESIGN_PARAMS, kb.WNFLAG, head + "".join(blocks) + tail]),
        source="klt_body.spice.in")


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
                  measurements=measurements(len(configs)), timeout_s=3480, **axes)


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


def main(argv=None, *, preflight=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_ab_args(ap, REPO)
    ap.add_argument("--part", choices=("main", "extra", "both"), default="both")
    ap.add_argument("--process", default=None,
                    help="shard: run one process corner only (e.g. tt); output goes to <part>-<process>/ "
                         "so each batch job stays under the fleet's 3600 s whole-job ceiling")
    args = ap.parse_args(argv)
    dest = tb_adapter.stage_corner_dir(REPO, "soft-start", args.record_id)
    if (HERE.parent / "corners" / args.record_id).exists():
        raise SystemExit(f"sim/soft-start/corners/{args.record_id}/ already exists; "
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
    parts = [("main", MAIN, {}), ("extra", EXTRA, EXTRA_AXES)]
    parts = [p for p in parts if args.part in (p[0], "both")]
    # Wrinkle 1 (issue #646): a sharded record is complete only when every
    # shard of every part has run. Each shard accumulates into the same staged
    # record below, so the mint runs once, after the last one -- name the
    # shards this invocation still owes.
    remaining = []
    if args.process:
        for part, _, axes in parts:
            remaining += [f"--part {part} --process {p}"
                          for p in axes.get("process", kb.LDO_PROCESS) if p != args.process]

    rows = []
    for part, configs, axes in parts:
        ax = kb.only_axes(args.only) or dict(axes)
        sub = part
        if args.process:
            ax["process"] = (args.process,)
            sub = f"{part}-{args.process}"
        res = run_ab(lambda n, d, c=configs, a=ax: job(n, d, c, a), Path(args.dut), args.baseline_ref,
                     dest / sub, REPO, backend=args.backend)
        for tag, vals in res.items():
            for cid, v in sorted(vals.items()):
                for k, (cout, esr, rload) in enumerate(configs, 1):
                    rows.append({"dut": tag, "corner": cid, "cout": cout, "esr": esr, "rload": rload,
                                 **derive(v, k), "status": v.get("_status"),
                                 "diagnostics": v.get("_diagnostics")})
    keys = list(dict.fromkeys(k for r in rows for k in r))  # union: a point missing a crossing lacks derived keys
    out = dest / (f"summary-{args.process}.csv" if args.process else "summary.csv")
    # Split-part/shard invocations accumulate into one staged record (#646):
    # merge with any summary a previous one wrote instead of clobbering it (#704).
    write_summary_csv(rows, out, keys, merge_key=("dut", "corner", "cout", "esr", "rload"))
    print(f"staged  : {dest} (not evidence yet)")
    if remaining:
        print("shards  : still to run for this record -- " + "; ".join(remaining))
        print("          mint only once, after the last shard (the store refuses a "
              "second mint of the same record id)")
    print(f"mint it : python3 sim/run_store_evidence.py soft-start {args.record_id} "
          f"{dest} --summary <summary.md> --kind corners")
    print("         (<summary.md> is the run's hand-written Markdown record, not "
          f"summary{'-' + args.process if args.process else ''}.csv; the store commits "
          f"it as sim/soft-start/corners/{args.record_id}.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
