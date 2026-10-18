"""Same-backend A/B of two DUT netlists through ``klt sim`` (issue #320).

``run_ab(job_factory, dut, baseline_ref, dest, repo)`` builds one
:class:`harness.klt_batch.Job` for the DUT under test and, when
``baseline_ref`` is given, one for ``design/netlist/ldo_core.spice`` as it
stands at that git ref; submits both concurrently on the same backend (so a
batch run puts both on the same fleet image -- the only comparison
``sim/README.md`` lets a record draw conclusions from); and collects each
into ``dest/<tag>/`` (``new`` / ``baseline``) with a frozen copy of the
netlist it measured, ``dut.spice``, beside its logs.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import klt_batch as kb


def add_ab_args(ap, repo: Path) -> None:
    """The flags every ``klt_run.py`` wrapper takes ahead of its own."""
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--dut", default=str(repo / "design/netlist/ldo_core.spice"))
    ap.add_argument("--baseline-ref", default=None)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--only", default=None, help="one point, e.g. tt,27,3.30 (debug; runs locally)")


def write_summary_csv(rows: list[dict], path: Path, keys: list[str] | None = None) -> None:
    """Write ``rows`` to ``path``; default columns are the sorted union, ``dut`` and ``corner`` first."""
    if keys is None:
        keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("dut", "corner"), k))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}")


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_ab(job_factory, dut: Path, baseline_ref: str | None, dest: Path, repo: Path,
           backend: str | None = None, log=print) -> dict[str, dict]:
    dest.mkdir(parents=True, exist_ok=True)
    duts = {"new": Path(dut)}
    if baseline_ref:
        base = dest / "baseline-dut.spice"
        base.write_bytes(subprocess.run(
            ["git", "-C", str(repo), "show", f"{baseline_ref}:design/netlist/ldo_core.spice"],
            check=True, capture_output=True).stdout)
        duts["baseline"] = base
    with tempfile.TemporaryDirectory(prefix="klt-ab-") as tmp:
        staged = {}
        for tag, path in duts.items():
            job = job_factory(tag, path)
            staged[tag] = (job, kb.stage(job, Path(tmp) / tag))
            log(f"{tag}: DUT sha256 {_sha256(path)}")

        def go(tag):
            job, req = staged[tag]
            report = kb.run(req, Path(tmp) / f"{tag}-out", backend=backend, log=log)
            sub = dest / tag
            vals = kb.collect(report, job, sub)
            shutil.copyfile(path_of(tag), sub / "dut.spice")
            shutil.copyfile(req.parent / "body.spice", sub / "body.spice")
            shutil.copyfile(req, sub / "request.json")
            return tag, vals

        def path_of(tag):
            return duts[tag]

        # Off-host: submit both jobs at once. Local (a single-point debug run):
        # one ngspice at a time, never a local fan-out.
        workers = 1 if backend in ("local",) else len(staged)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = dict(pool.map(go, list(staged)))
    if "baseline" in duts:
        duts["baseline"].unlink()
    return results
