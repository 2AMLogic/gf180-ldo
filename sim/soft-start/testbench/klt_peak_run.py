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

Those bytes land in the git-ignored staging tree ``sim/.work/.stage/`` (DR-0044,
issue #647), never under ``sim/soft-start/corners/``: a run becomes evidence
only when ``sim/run_store_evidence.py --kind corners`` mints it, committing the
manifest, the hand-written Markdown record and the ``klt-report.json``
envelopes; an unminted run leaves the tree clean. ``--part main`` and
``--part extra`` both accumulate into the same staged record, so the mint runs
once, after the last part (the store refuses a second mint of the same id).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# klt_run.py is loaded by path under a unique name, never a bare
# ``import klt_run``: this driver is itself loaded by filesystem path (tests,
# other drivers), and the bare name is ambiguous across the 16 benches -- it
# binds to whichever bench's sibling resolves first in that interpreter
# (issues #693/#630; enforced by sim/tests/test_sibling_import_names.py,
# issue #700). Same rule and pattern as
# sim/soft-start-loop-gain/testbench/sweep.py.
_klt_run_spec = importlib.util.spec_from_file_location(
    "soft_start_klt_run", HERE / "klt_run.py")
kr = importlib.util.module_from_spec(_klt_run_spec)
sys.modules["soft_start_klt_run"] = kr
_klt_run_spec.loader.exec_module(kr)

kb, run_ab = kr.kb, kr.run_ab
REPO = kr.REPO
from harness import tb_adapter  # noqa: E402


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


def main(argv=None, *, preflight=None) -> int:
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
    dest = tb_adapter.stage_corner_dir(REPO, "soft-start", args.record_id)
    if (HERE.parent / "corners" / args.record_id).exists():
        raise SystemExit(f"sim/soft-start/corners/{args.record_id}/ already exists; "
                         "append-only evidence is never rewritten -- choose another --record-id")
    refused = tb_adapter.refuse_unstorable_run(REPO, args.only, preflight)
    if refused is not None:
        return refused
    parts = [p for p in (("main", kr.MAIN, {}), ("extra", kr.EXTRA, kr.EXTRA_AXES)) if args.part in (p[0], "both")]
    owed = "" if args.part == "both" else f"--part {'extra' if args.part == 'main' else 'main'}"
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
    path = dest / "summary.csv"
    # Split-part runs accumulate into one staged record (issue #687): merge
    # with any summary.csv a previous --part wrote instead of clobbering it.
    # Rows are keyed by (dut, corner, cout, esr, rload), so re-running a part
    # replaces its own rows; a header that disagrees with this run's fields
    # means the staged record follows a different row schema -- refuse rather
    # than write a mixed file.
    key = ("dut", "corner", "cout", "esr", "rload")
    produced = {tuple(r[k] for k in key) for r in rows}
    fields = list(rows[0]) if rows else []
    if path.exists():
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            old_fields = list(reader.fieldnames or [])
            old_rows = list(reader)
        if fields and old_fields and old_fields != fields:
            raise SystemExit(f"{path}: existing header {old_fields} does not match "
                             f"this run's fields {fields} -- refusing to write a "
                             "summary.csv of mixed schemas")
        rows = [r for r in old_rows if tuple(r[k] for k in key) not in produced] + rows
        fields = fields or old_fields
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {dest / 'summary.csv'}")
    print(f"staged  : {dest} (not evidence yet)")
    if owed:
        print(f"parts   : {owed} still to run for this record -- "
              "mint only once, after the last part (the store refuses a second "
              "mint of the same record id)")
    print(f"mint it : python3 sim/run_store_evidence.py soft-start {args.record_id} "
          f"{dest} --summary <summary.md> --kind corners")
    print("         (<summary.md> is the run's hand-written Markdown record, not summary.csv; "
          f"the store commits it as sim/soft-start/corners/{args.record_id}.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
