"""Mint an evidence record from a ``klt_run.py`` grid (issue #468).

    PYTHONPATH=sim python3 -m harness.klt_record <slug> --record-id <id>

``tb_adapter.main`` leaves ``sim/<slug>/corners/<record-id>/summary.csv`` and
the per-request ``klt-*/new/klt-report.json`` behind. This turns them into
``records/<record-id>.md`` and ``netlist-snapshots/<record-id>.spice`` in the
form of the #467 records: the grid graded against ``tb.json``'s own bounds
(``report.evaluate_checks`` / ``report.summarize``, the functions the local
harness grades with), the fleet job ids and the PDK-staging flag read from the
reports, and an old-vs-new section against the newest earlier record.

The old-vs-new section only claims a same-DUT comparison when the earlier
record's recorded DUT sha256 equals the current DUT's; otherwise it says so and
reports the movement as DUT + backend + PDK together. It never edits an earlier
record. The record's *Reading* is not generated: a person reads the result and
writes it.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from . import pdk, report
from . import testbench as tbmod

REPO = Path(__file__).resolve().parents[2]
_ROW = re.compile(r"^\s*\|\s*`([^`]+)`\s*\|(.*)\|\s*$")


def _num(x: str):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_grid(corner_dir: Path, tb: tbmod.Testbench):
    """summary.csv -> [point] in the report module's duck type, plus raw rows."""
    with open(corner_dir / "summary.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["dut"] == "new"]
    canon = ["tt", "ff", "ss", "fs", "sf", "res_ff", "res_ss", "bjt_ff", "bjt_ss"]

    def order(r):    # the order the earlier records print: process, then temperature, then supply
        proc, t, v = r["corner"].rsplit("_", 2)
        return canon.index(proc), float(t.removesuffix("c")), float(v.removesuffix("v"))

    points = []
    for r in sorted(rows, key=order):
        ok = r["status"] == "pass"
        points.append(SimpleNamespace(
            status="ok" if ok else "error",
            measurements={k: v for k in tb.measure if (v := _num(r.get(k))) is not None},
            point=SimpleNamespace(corner_id=r["corner"]),
            message=r["status"], diagnostics=r["diagnostics"]))
    return points


def jobs(corner_dir: Path) -> list[dict]:
    out = []
    for p in sorted(corner_dir.glob("klt-*/new/klt-report.json")):
        rep = json.loads(p.read_text())
        env = rep.get("environment", {})
        rem = env.get("remote") or {}
        wpdk = (rem.get("worker_environment") or {}).get("pdk") or {}
        out.append({"request": p.parent.parent.name.removeprefix("klt-"), "job": rem.get("job_id"),
                    "instance": rem.get("instance_type"), "state": rem.get("state"),
                    "staged": wpdk.get("models_staged"), "stamp": wpdk.get("stamp_text"),
                    "corners": rep.get("corner_count")})
    return out


def parse_prior(path: Path) -> tuple[list[str], dict[str, dict], set[str]]:
    """(columns, {corner-id: {column: float}}, every sha256 the record cites)."""
    text = path.read_text()
    cols: list[str] = []
    grid: dict[str, dict] = {}
    for line in text.splitlines():
        if re.match(r"^\s*\|\s*corner-id\s*\|", line):
            if cols:
                break
            cols = [c.strip() for c in line.strip().strip("|").split("|")][1:]
            continue
        m = _ROW.match(line)
        if m and cols:
            cells = [c.strip() for c in m.group(2).split("|")]
            if len(cells) == len(cols):
                grid[m.group(1)] = {c: _num(v) for c, v in zip(cols, cells)}
        elif cols and grid and not line.strip().startswith("|"):
            break                                  # the Result table ended
    return cols, grid, set(re.findall(r"\b[0-9a-f]{64}\b", text))


def compare(tb, points, prior: Path | None, dut_sha: str) -> list[str]:
    if prior is None:
        return ["No earlier record of this bench exists."]
    cols, old, shas = parse_prior(prior)
    same = dut_sha in shas
    new = {p.point.corner_id: p.measurements for p in points}
    names = [c for c in tb.measure if c in cols]
    lines = [f"Earlier record: `{prior.stem}`. DUT `{dut_sha[:8]}…` "
             + ("**is the DUT that record measured**, so the two differ in backend (local `ngspice -b` "
                "vs the batch fleet) and open_pdks revision (`c6d73a3` vs `f6eeac7`) only."
                if same else "is **not** the DUT that record cites, so there is no same-DUT comparison; "
                "the two differ in DUT, backend and PDK revision together."), ""]
    both = sorted(set(old) & set(new))
    lines.append(f"{len(both)} corners appear in both records; the earlier table is printed to 6 "
                 "significant digits, so a difference below 1e-5 relative is rounding.")
    lines += ["", "| measurement | corners differing beyond rounding | max abs diff | at |", "|---|---|---|---|"]
    for n in names:
        worst, at, moved = 0.0, "", 0
        for cid in both:
            a, b = old[cid].get(n), new[cid].get(n)
            if a is None or b is None:
                continue
            d = abs(a - b)
            if d > 1e-5 * abs(a) + 1e-9:
                moved += 1
            if d > worst:
                worst, at = d, cid
        lines.append(f"| `{n}` | {moved} | {report._fmt(worst)} | {('`' + at + '`') if at else '—'} |")
    gone = sorted(set(old) - set(new))
    if gone:
        axes = sorted({c.rsplit("_", 2)[0] for c in gone})
        lines += ["", f"{len(gone)} corners are in the earlier record only (process axes "
                  f"{', '.join(f'`{a}`' for a in axes)}, which this `tb.json` does not declare)."]
    return lines


def render(tb, rid, points, grid_jobs, prior, dut_rel, dut_sha, driver) -> str:
    slug = tb.experiment
    names = list(tb.measure)
    summary = report.summarize(points, names)
    failures = report.evaluate_checks(tb.checks, points, summary)
    at: dict[str, list[str]] = {}
    for f in failures:
        at.setdefault(f["at"], []).append(f"{f['measurement']} {f['kind']}={report._fmt(f['limit'])} "
                                          f"(got {report._fmt(f['value'])})")
    n_ok = sum(1 for p in points if p.status == "ok" and p.point.corner_id not in at)
    errors = [p for p in points if p.status != "ok"]
    canon = ["tt", "ff", "ss", "fs", "sf", "res_ff", "res_ss", "bjt_ff", "bjt_ss"]
    procs = sorted({p.point.corner_id.rsplit("_", 2)[0] for p in points}, key=canon.index)
    temps = sorted({p.point.corner_id.split("_")[-2] for p in points})
    vins = sorted({p.point.corner_id.split("_")[-1] for p in points})
    staged = all(j["staged"] for j in grid_jobs)
    stamps = sorted({j["stamp"] for j in grid_jobs if j["stamp"]})
    out = [
        f"# Record {rid}", "",
        f"- **Record ID**: {rid}",
        "- **Supersedes**: none (append-only). First record for this bench measured through `klt sim` on the "
        "batch fleet against the pinned open_pdks revision; earlier records (local `run_corners.py`) are left "
        "untouched.",
        f"- **Claim**: {tb.claim} Measurement definitions and bounds are `sim/{slug}/testbench/tb.json`'s, unchanged.",
        f"- **Netlist provenance**: schematic (`{dut_rel}`, sha256 `{dut_sha}`), driven by "
        f"`sim/{slug}/testbench/{tb.netlist.name}` through `sim/harness/tb_adapter.py` (circuit bodies and "
        f"requests: `sim/{slug}/corners/{rid}/klt-*/new/`); taken on a clean tree at the adapter commit named by "
        "the record ID suffix.",
        f"- **Driver**: `{driver}`",
        f"- **Backend**: `klt sim` batch fleet, {len(grid_jobs)} requests (one per analysis state and supply "
        "point, see the driver docstring): "
        + "; ".join(f"`{j['request']}` job `{j['job']}` ({j['instance']}, {j['state']})" for j in grid_jobs)
        + ". `environment.remote` in each `klt-report.json`. No local `ngspice -b` grid.",
        f"- **PDK**: open_pdks `{pdk.PINNED_OPEN_PDKS_REVISION}` (`PINNED_OPEN_PDKS_REVISION`), model files "
        f"staged with every job (`options.stage_model_inputs`; `worker_environment.pdk.models_staged: "
        f"{str(staged).lower()}`). The batch image's own PDK stamp reads {', '.join(f'`{s}`' for s in stamps)}, "
        "so the `pdk_stamp_comparison: mismatch` in each report is expected and is the reason for staging.",
        "- **Links**:",
        f"  - `sim/{slug}/corners/{rid}/` (`summary.csv`; `klt-<state>-<vin>v/new/` = per-corner logs, "
        "`body.spice`, `request.json`, `klt-report.json`)",
        f"  - `sim/{slug}/netlist-snapshots/{rid}.spice`",
        "- **Corner matrix run**:",
        f"  - Process: {', '.join(procs)}",
        f"  - Temperature: {', '.join(t.removesuffix('c') + ' C' for t in sorted(temps, key=lambda t: float(t.removesuffix('c'))))}",
        f"  - Supply: {', '.join(v.removesuffix('v') + ' V' for v in vins)}",
        f"  - {len(points)} point full-factorial grid (process x temperature x supply), "
        f"{len(points) - len(errors)} completed",
        "- **Operating conditions**:",
    ]
    for k, v in tb.operating_conditions.items():
        out.append(f"  - {k.replace('_', ' ').capitalize()}: {v}")
    out += ["- **Statistical convention**: N/A (corner-matrix claim, not a distribution claim)",
            "- **Result**:", "",
            "  | corner-id | " + " | ".join(names) + " | pass/fail |",
            "  |---|" + "---|" * (len(names) + 1)]
    for p in points:
        cid = p.point.corner_id
        verdict = (f"ERROR — {p.message}" if p.status != "ok"
                   else "FAIL — " + "; ".join(at[cid]) if cid in at else "PASS")
        out.append(f"  | `{cid}` | " + " | ".join(report._fmt(p.measurements.get(n)) for n in names)
                   + f" | {verdict} |")
    if at.get("grid"):
        out += ["", "  Grid-level check failures: " + "; ".join(at["grid"]) + "."]
    out += ["", "  Spread across the grid:", "", "  | measurement | min | max | mean | spread % | limits |",
            "  |---|---|---|---|---|---|"]
    for n, s in summary.items():
        spec = tb.checks.get(n, {})
        limits = ", ".join(f"{k}={report._fmt(spec[k])}" for k in
                           ("min", "max", "max_spread_pct", "min_spread_pct") if k in spec) or "—"
        if not s.get("n"):
            out.append(f"  | `{n}` | no data | | | | {limits} |")
        else:
            out.append(f"  | `{n}` | {report._fmt(s['min'])} (`{s['min_at']}`) | {report._fmt(s['max'])} "
                       f"(`{s['max_at']}`) | {report._fmt(s['mean'])} | {report._fmt(s['spread_pct'])} | {limits} |")
    overall = "ERROR" if errors else ("FAIL" if failures else "PASS")
    out += ["", f"**Overall: {overall}** ({n_ok}/{len(points)} points meet every `tb.json` bound).", "",
            "## Old-vs-new", ""] + compare(tb, points, prior, dut_sha)
    out += ["", "## Reading", "", "(to be written)", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--dut", help="repo-relative DUT netlist (default: the manifest's)")
    args = ap.parse_args(argv)
    exp = REPO / "sim" / args.slug
    tb = tbmod.load(exp / "testbench")
    corner_dir = exp / "corners" / args.record_id
    dut = tb.design_netlists[0]
    dut_rel = tb.dut_netlist_rel or str(dut.relative_to(REPO))
    dut_sha = tb.include_provenance(REPO)[0]["sha256"]
    priors = sorted(p for p in (exp / "records").glob("*.md") if p.stem != args.record_id)
    text = render(tb, args.record_id, load_grid(corner_dir, tb), jobs(corner_dir), priors[-1] if priors else None,
                  dut_rel, dut_sha, f"python3 sim/{args.slug}/testbench/klt_run.py --record-id {args.record_id}")
    report.write_netlist_snapshot(tb, exp, args.record_id)
    report.write_markdown_record(args.record_id, text, exp / "records")
    print(f"wrote sim/{args.slug}/records/{args.record_id}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
