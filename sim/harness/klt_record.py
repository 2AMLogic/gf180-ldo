"""Mint an evidence record from a ``klt_run.py`` grid (issue #468).

    PYTHONPATH=sim python3 -m harness.klt_record <slug> --record-id <id>

``tb_adapter.main`` leaves a staged run under git-ignored
``sim/.work/.stage/<slug>/sim/<slug>/corners/<record-id>/`` -- ``summary.csv``,
the per-corner logs, the decks and the per-request ``klt-report.json``. This
turns it into committed evidence (DR-0044, issue #594):

* the bytes go to the fleet artifact store, and git keeps
  ``manifests/artifacts/<slug>-<record-id>.manifest.json`` (DR-0041);
* ``klt-report.json`` stays committed under ``corners/<record-id>/``, because
  ``signoff/block-manifest.json`` pins those envelopes by hash and CI grades
  them with no broker;
* ``netlist-snapshots/<record-id>.spice`` stays committed, because
  ``sim/build_characterization_report.py`` reads it to judge a row's freshness;
* ``records/<record-id>.md`` is the record itself.

It fails closed: if the store is unreachable nothing is committed, the staged
bytes stay, and it exits 10. There is no option to commit the bytes instead.

The record keeps the form of the #467 records: the grid graded against
``tb.json``'s own bounds
(``report.evaluate_checks`` / ``report.summarize``, the functions the local
harness grades with), the fleet job ids and the PDK-staging flag read from the
reports, and an old-vs-new section against the newest earlier record.

The old-vs-new section only claims a same-DUT comparison when the earlier
record's recorded DUT sha256 equals the current DUT's; otherwise it says so.
The environment axes it names -- backend, open_pdks revision, model library,
ngspice build -- are read from the two runs' own reports (an earlier record
with no reports falls back to the old-format PDK/ngspice lines of its text),
and an axis neither side's data speaks for is reported as **not determined**,
never as a delta. It never edits an earlier record. The record's *Reading*
is not generated: a person reads the result and writes it.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

from . import evidence_store as store
from . import pdk, report
from . import tb_adapter
from . import testbench as tbmod
from .klt_ab import driver_args, parse_params

REPO = Path(__file__).resolve().parents[2]
#: Evidence could not be stored; nothing was committed (``tb_adapter``'s code).
EXIT_NOT_STORED = tb_adapter.EXIT_NOT_STORED
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


def report_paths(corner_dir: Path) -> list[Path]:
    """Every ``klt-report.json`` the run left, in both on-disk layouts.

    A bench split into several requests (one per analysis state and/or supply
    point) writes ``klt-<tag>/new/klt-report.json``. A single-analysis bench
    with a swept supply is **one** request and writes ``new/klt-report.json``
    with no ``klt-*`` level (#594). Empty when the run left no report at all.
    """
    return (sorted(corner_dir.glob("klt-*/new/klt-report.json"))
            or sorted(corner_dir.glob("new/klt-report.json")))


def jobs(corner_dir: Path) -> list[dict]:
    """The fleet and environment facts of each request, from its report.

    A staged run with no ``klt-report.json`` under either layout is refused:
    every record this module mints is a batch-fleet record, and minting one
    with an empty job list would assert staging from no evidence (#604).
    """
    paths = report_paths(corner_dir)
    if not paths:
        raise SystemExit(
            f"no klt-report.json under {corner_dir}/ (looked for `klt-*/new/klt-report.json` "
            "and `new/klt-report.json`): a batch-fleet record cannot be minted without its "
            "fleet job data, and an empty job list would make the staging claim vacuous.")
    out = []
    for p in paths:
        rep = json.loads(p.read_text())
        env = rep.get("environment", {})
        rem = env.get("remote") or {}
        # a request split by ``batch.max_units_per_job`` reports ``remote.fleet``, one entry per job
        fleet = rem.get("fleet") or [rem]
        wpdks = [(f.get("worker_environment") or {}).get("pdk") or {} for f in fleet]
        wenvs = [(f.get("worker_environment") or {}) for f in fleet]
        parts = p.relative_to(corner_dir).parts
        out.append({"request": parts[0].removeprefix("klt-") if len(parts) > 2 else "single",
                    "job": ", ".join(str(f.get("job_id")) for f in fleet),
                    "instance": ", ".join(sorted({str(f.get("instance_type")) for f in fleet})),
                    "state": ", ".join(sorted({str(f.get("state")) for f in fleet})),
                    "staged": all(w.get("models_staged") for w in wpdks),
                    "stamp": next((w["stamp_text"] for w in wpdks if w.get("stamp_text")), None),
                    "stamp_cmp": next(((w.get("pdk_stamp_comparison") or {}).get("status")
                                       for w in wenvs
                                       if (w.get("pdk_stamp_comparison") or {}).get("status")),
                                      None),
                    "backend": (env.get("backend") or {}).get("resolved"),
                    "models_lib": env.get("models_lib_sha256"),
                    "engine_version": env.get("engine_version"),
                    "engine_sha": (env.get("engine_build") or {}).get("binary_sha256"),
                    "corners": rep.get("corner_count")})
    return out


#: the environment axes the old-vs-new section derives, in print order, as
#: (axis name, key in the axes dicts built by ``run_env`` / ``prior_env``)
_AXES = (("backend", "backend"), ("open_pdks revision", "stamp"),
         ("model library", "models_lib"), ("ngspice build", "engine"))


def _env_from_report(rep: dict) -> dict:
    env = rep.get("environment", {})
    ver = env.get("engine_version")
    return {"backend": (env.get("backend") or {}).get("resolved"),
            "models_lib": env.get("models_lib_sha256"),
            "engine": (str(ver), (env.get("engine_build") or {}).get("binary_sha256"))
            if ver is not None else None}


def run_env(grid_jobs: list[dict]) -> dict:
    """This run's environment axes.

    The PDK axis is the pinned revision this run submitted and staged
    (`options.stage_model_inputs`), not the worker image's own stamp: the
    stamp names what the image ships, which is why staging exists, and a
    stage-vs-stamp difference is not a revision delta (#604).
    """
    def first(key):
        return next((j[key] for j in grid_jobs if j.get(key) is not None), None)
    ver, sha = first("engine_version"), first("engine_sha")
    return {"backend": first("backend"),
            "stamp": pdk.PINNED_OPEN_PDKS_REVISION,
            "models_lib": first("models_lib"),
            "engine": (str(ver), sha) if ver is not None else None}


def prior_env(prior: Path) -> dict:
    """The earlier run's environment axes, or None where nothing speaks.

    The backend, model-library and solver-build axes come from the prior
    record's own committed reports under ``sim/<slug>/corners/<prior-stem>/``
    (both layouts), when it has any -- the old-format record text names no
    backend and no hashes. The PDK axis is the revision the record itself
    pins, read from its ``PDK:`` line in both the klt-minted and the
    old-format record. An axis neither source names stays None, so the
    comparison reports it as not determined rather than as a delta.
    """
    corner_dir = prior.parent.parent / "corners" / prior.stem
    paths = report_paths(corner_dir) if corner_dir.is_dir() else []
    if paths:
        axes = _env_from_report(json.loads(paths[0].read_text()))
    else:
        axes = {"backend": None, "models_lib": None, "engine": None}
        ver = re.search(r"-\s*\**ngspice\**:\s*ngspice-(\d+)", prior.read_text())
        if ver:
            axes["engine"] = (ver.group(1), None)
    stamp = re.search(r"open_pdks\s+`?([0-9a-f]{40})`?", prior.read_text())
    axes["stamp"] = stamp.group(1) if stamp else None
    return axes


def _short(hex40: str) -> str:
    return hex40[:8] + "…"


def _eng(v) -> str:
    ver, sha = v
    return f"ngspice-{ver}" + (f" (`{sha[:8]}…`)" if sha else "")


def _and_join(parts: list[str]) -> str:
    return ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]


def _env_lines(cur: dict, old: dict) -> list[str]:
    """Derived sentences on how the two runs' environments compare.

    An axis is claimed as a delta only when both sides' data names a value
    and the values differ; an axis either side cannot speak for is reported
    as not determined, never as a delta (#604, #612).
    """
    diffs, undet = [], []
    for name, key in _AXES:
        a, b = cur.get(key), old.get(key)
        if a is None or b is None:
            side = "the earlier record" if b is None else "this run"
            undet.append(f"{name} (not determined from {side})")
            continue
        if key == "engine":
            (aver, ash), (bver, bsha) = a, b
            if aver != bver or (ash and bsha and ash != bsha):
                diffs.append(f"ngspice build ({_eng(a)} vs {_eng(b)})")
            elif not (ash and bsha):
                undet.append(f"ngspice binary build (both versions are ngspice-{aver})")
            continue
        if a != b:
            show = (lambda v: f"`{_short(v)}`") if key == "stamp" else (lambda v: f"`{v}`")
            diffs.append(f"{name} ({show(a)} vs {show(b)})")
    out = []
    if diffs:
        out.append("The two runs differ in " + _and_join(diffs) + ".")
    if undet:
        out.append("Not determined: " + _and_join(undet) + ".")
    if not diffs and not undet:
        out.append("The two runs match on every environment axis this record can read: "
                   "backend, open_pdks revision, model library and ngspice build.")
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


def compare(tb, points, prior: Path | None, dut_sha: str, grid_jobs: list[dict]) -> list[str]:
    if prior is None:
        return ["No earlier record of this bench exists."]
    cols, old, shas = parse_prior(prior)
    same = dut_sha in shas
    new = {p.point.corner_id: p.measurements for p in points}
    names = [c for c in tb.measure if c in cols]
    lines = [f"Earlier record: `{prior.stem}`. DUT `{dut_sha[:8]}…` "
             + ("**is the DUT that record measured**."
                if same else "is **not** the DUT that record cites, so there is no same-DUT "
                "comparison."), ""]
    lines += _env_lines(run_env(grid_jobs), prior_env(prior))
    both = sorted(set(old) & set(new))
    lines += ["", f"{len(both)} corners appear in both records; the earlier table is printed to "
              "6 significant digits, so a difference below 1e-5 relative is rounding."]
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


def _staging_sentence(grid_jobs: list[dict]) -> str:
    """What the reports say about model staging -- never a vacuous all() (#604)."""
    n = len(grid_jobs)
    if not n:
        return "Model staging is **not determined** (no job data)."
    unstaged = [j["request"] for j in grid_jobs if not j["staged"]]
    if not unstaged:
        return (f"Model files staged with every request (`options.stage_model_inputs`; "
                f"`worker_environment.pdk.models_staged: true` in all {n} report"
                + ("s" if n > 1 else "") + "), so the run executed the pinned revision's models.")
    if len(unstaged) == n:
        return (f"Model files staged with **none** of the {n} requests "
                "(`worker_environment.pdk.models_staged: false` in each report).")
    return (f"Model files staged with {n - len(unstaged)} of the {n} requests "
            f"(`worker_environment.pdk.models_staged: false` in "
            + ", ".join(f"`klt-{r}`" for r in unstaged) + ").")


def _stamp_sentence(grid_jobs: list[dict]) -> str:
    stamps = sorted({j["stamp"] for j in grid_jobs if j["stamp"]})
    if not stamps:
        return ""
    s = ("The worker image's own PDK stamp reads " + ", ".join(f"`{t}`" for t in stamps)
         + " (`worker_environment.pdk.stamp_text`)")
    cmps = {j["request"]: j["stamp_cmp"] for j in grid_jobs if j.get("stamp_cmp")}
    if cmps:
        distinct = sorted(set(cmps.values()))
        if len(distinct) == 1:
            s += f"; each report's `pdk_stamp_comparison` reads `{distinct[0]}`"
        else:
            s += ("; `pdk_stamp_comparison` reads "
                  + ", ".join(f"`{v}` (`klt-{k}`)" for k, v in sorted(cmps.items())))
    return s + "."


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
    staged_sentence = _staging_sentence(grid_jobs)
    stamp_sentence = _stamp_sentence(grid_jobs)
    out = [
        f"# Record {rid}", "",
        f"- **Record ID**: {rid}",
        (f"- **Supersedes**: `{prior.stem}` (append-only; the earlier record is left untouched)."
         if prior is not None else
         "- **Supersedes**: none (append-only; no earlier record of this bench exists)."),
        f"- **Claim**: {tb.claim} Measurement definitions and bounds are `sim/{slug}/testbench/tb.json`'s, unchanged.",
        f"- **Netlist provenance**: schematic (`{dut_rel}`, sha256 `{dut_sha}`), driven by "
        f"`sim/{slug}/testbench/{tb.netlist.name}` through `sim/harness/tb_adapter.py` (circuit bodies and "
        f"requests: stored, manifest names `sim/{slug}/corners/{rid}/.../body.spice` and `request.json`); "
        "taken on a clean tree at the adapter commit named by the record ID suffix.",
        f"- **Driver**: `{driver}`",
        f"- **Backend**: `klt sim` batch fleet, {len(grid_jobs)} "
        + ("request" if len(grid_jobs) == 1 else "requests (one per analysis state and supply "
           "point, see the driver docstring)") + ": "
        + "; ".join(f"`{j['request']}` job `{j['job']}` ({j['instance']}, {j['state']})" for j in grid_jobs)
        + ". `environment.remote` in each `klt-report.json`. No local `ngspice -b` grid.",
        f"- **PDK**: open_pdks `{pdk.PINNED_OPEN_PDKS_REVISION}` (`PINNED_OPEN_PDKS_REVISION`). "
        + staged_sentence + (" " + stamp_sentence if stamp_sentence else ""),
        "- **Links**:",
        f"  - `sim/{slug}/corners/{rid}/.../klt-report.json` -- committed: the redacted `klt sim` request "
        "envelope, which `signoff/block-manifest.json` pins by hash and CI grades offline (DR-0044).",
        f"  - `sim/{slug}/corners/{rid}/` -- every other path under it (`summary.csv`, per-corner "
        "`<corner>.log`, `dut.spice`, `body.spice`, `request.json`) is a **manifest `name`**, not a file in "
        "this repo: the bytes are in the fleet artifact store (DR-0041). The \"Stored evidence\" table below "
        "lists each one with its sha256; fetch one with `klt artifact get <manifest>#<name> -o <out>`.",
        f"  - `sim/{slug}/netlist-snapshots/{rid}.spice` -- committed: "
        "`sim/build_characterization_report.py` reads it to judge this row's freshness against the current "
        "DUT (DR-0044).",
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
            "## Old-vs-new", ""] + compare(tb, points, prior, dut_sha, grid_jobs)
    out += ["", "## Reading", "", "(to be written)", ""]
    return "\n".join(out)


#: DR-0044's kept-file copy, moved beside ``split_batch_run`` in
#: ``evidence_store`` so tb-free callers share it (issue #645); aliased so
#: this module keeps one name and its behaviour does not change.
install_kept = store.install_kept


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--dut", help="repo-relative DUT netlist (default: the manifest's)")
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                    help="the --param overrides the klt_run.py run used (recorded on the Driver line)")
    args = ap.parse_args(argv)
    exp = REPO / "sim" / args.slug
    tb = tbmod.load(exp / "testbench")
    overrides = parse_params(args.param)
    if set(overrides) - set(tb.params):
        raise SystemExit(f"--param {sorted(set(overrides) - set(tb.params))}: not in tb.json params")
    rid = args.record_id
    slug = args.slug
    stage_exp = tb_adapter.stage_experiment_dir(REPO, slug)
    corner_dir = tb_adapter.stage_corner_dir(REPO, slug, rid)
    if not (corner_dir / "summary.csv").is_file():
        raise SystemExit(
            f"no staged run at {corner_dir.relative_to(REPO)}/ (no summary.csv). Run "
            f"`python3 sim/{slug}/testbench/klt_run.py --record-id {rid}` first; DR-0044 mints a "
            "record from the staging tree, not from sim/<slug>/corners/.")
    dut = tb.design_netlists[0]
    dut_rel = tb.dut_netlist_rel or str(dut.relative_to(REPO))
    dut_sha = tb.include_provenance(REPO)[0]["sha256"]
    priors = sorted(p for p in (exp / "records").glob("*.md") if p.stem != rid)
    text = render(tb, rid, load_grid(corner_dir, tb), jobs(corner_dir), priors[-1] if priors else None,
                  dut_rel, dut_sha, f"python3 sim/{slug}/testbench/klt_run.py --record-id {rid}{driver_args(overrides)}")
    # DR-0044: the bytes go to the artifact store and git keeps the manifest,
    # the record, the netlist snapshot and the `klt-report.json` envelopes.
    # Order is fail-closed: stage the snapshot outside sim/, store everything
    # else, and only then copy the kept files in. A StoreError at any point
    # leaves sim/ and manifests/ exactly as they were and keeps the staged
    # bytes, so the run is never lost and never silently committed raw.
    files, kept = store.split_batch_run(corner_dir, f"sim/{slug}/corners/{rid}")
    # The staged snapshot is scratch under sim/.work/, not evidence: clear a
    # copy left by an earlier failed mint so a retry is not refused by
    # `RecordExists` on it. The committed one is still never overwritten --
    # `write_netlist_snapshot` guards `sim/<slug>/netlist-snapshots/`, and
    # `install_kept` and `store_files` guard everything else under `sim/`.
    (stage_exp / report.SNAPSHOT_DIR / f"{rid}.spice").unlink(missing_ok=True)
    try:
        # Refuse a kept-destination collision *before* anything is written:
        # `store_files` installs the manifest and writes the record before
        # returning, so a later refusal from `install_kept` would leave both
        # committed while printing "nothing committed" (issue #662, the
        # window #645 closed for the tb-free caller). `install_kept`'s own
        # check stays as the TOCTOU backstop.
        for dst in store.kept_destinations(kept, corner_dir, exp / report.CORNERS_DIR / rid):
            if dst.exists():
                raise store.StoreError(f"{dst.relative_to(REPO)} already exists; append-only "
                                       "evidence is never rewritten")
        snapshot = report.write_netlist_snapshot(tb, stage_exp, rid, repo_root=REPO)
        mpath = store.store_files(files, repo_root=REPO, bench=slug, rid=rid, summary_text=text,
                                  summary_path=exp / report.RECORDS_DIR / f"{rid}.md")
        installed = install_kept(kept, corner_dir, exp / report.CORNERS_DIR / rid)
        final_snapshot = exp / report.SNAPSHOT_DIR / f"{rid}.spice"
        final_snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(snapshot, final_snapshot)
    except store.StoreError as exc:
        print(f"EVIDENCE NOT STORED -- nothing committed (fail closed): {exc}. The staged run is "
              f"kept, uncommitted, under {corner_dir.relative_to(REPO)}/.", file=sys.stderr)
        return EXIT_NOT_STORED
    shutil.rmtree(REPO / "sim" / ".work" / ".stage" / slug, ignore_errors=True)
    print(f"record   : sim/{slug}/records/{rid}.md")
    print(f"manifest : {mpath.relative_to(REPO)}  ({len(files)} objects stored)")
    print(f"committed: {final_snapshot.relative_to(REPO)}"
          + "".join(f"\n           {q.relative_to(REPO)}" for q in installed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
