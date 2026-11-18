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

import contextlib
import csv
import hashlib
import json
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


def parse_params(pairs: list[str]) -> dict[str, str]:
    """``["esr_val=0.2", ...]`` -> ``{"esr_val": "0.2"}``; a malformed pair is an error."""
    out = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name.strip().isidentifier() or not value.strip():
            raise SystemExit(f"--param {pair!r}: expected NAME=VALUE")
        out[name.strip()] = value.strip()
    return out


def driver_args(params: dict[str, str]) -> str:
    """The `` --param`` flags that reproduce ``params``, for a record's Driver line."""
    return "".join(f" --param {k}={v}" for k, v in params.items())


def write_summary_csv(rows: list[dict], path: Path, keys: list[str] | None = None,
                      merge_key: tuple[str, ...] | None = None) -> None:
    """Write ``rows`` to ``path``; default columns are the sorted union, ``dut`` and ``corner`` first.

    With ``merge_key`` (the tuple of columns identifying a row), rows already
    in ``path`` whose key matches one of this run's rows are replaced instead
    of clobbered -- split-part/shard invocations accumulate into one staged
    record (issue #687, #704). Headers union across invocations (a point
    missing a crossing lacks derived keys); a cell a row lacks is written
    blank. Without ``merge_key`` the write truncates as before. Every
    ``merge_key`` cell in an incoming row must be a ``str``: CSV keys compare
    as strings, so a non-``str`` cell (or a row missing the column, reading
    as ``None``) can never match and would silently duplicate the row --
    that is refused loudly instead (issue #710).
    """
    if keys is None:
        keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("dut", "corner"), k))
    if merge_key is not None and path.exists():
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            old_fields = list(reader.fieldnames or [])
            old_rows = list(reader)
        for r in rows:
            for k in merge_key:
                v = r.get(k)
                if not isinstance(v, str):
                    raise SystemExit(
                        f"write_summary_csv: merge_key column {k!r} must hold a str "
                        f"in every row (got {type(v).__name__}: {v!r}); a non-str "
                        "key can never match the strings a CSV round-trip wrote "
                        "and would silently duplicate the row")
        produced = {tuple(r.get(k) for k in merge_key) for r in rows}
        rows = [r for r in old_rows if tuple(r.get(k) for k in merge_key) not in produced] + rows
        keys = list(dict.fromkeys(list(keys) + old_fields))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}")


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_ab(job_factory, dut: Path, baseline_ref: str | None, dest: Path, repo: Path,
           backend: str | None = None, log=print,
           dut_rel: str = "design/netlist/ldo_core.spice",
           run_root: Path | None = None) -> dict[str, dict]:
    """Run each DUT variant's request; ``{tag: {corner_id: fields}}``.

    ``run_root``: when set (a persistent, git-ignored path -- never under
    ``dest``, whose bytes the evidence store stages wholesale), the staged
    request and the ``klt sim`` run dir live there instead of a session-local
    tempdir, each batch request is submitted with klt's ``--resume``, and a
    tag whose ``klt-report.json`` is already under ``dest`` from an earlier
    invocation -- with an identical request -- is not re-submitted at all.
    Together these make a sharded record resumable across sessions: re-run
    the same command and only what is still missing runs (issue #465).
    """
    dest.mkdir(parents=True, exist_ok=True)
    duts = {"new": Path(dut)}
    if baseline_ref:
        base = dest / "baseline-dut.spice"
        base.write_bytes(subprocess.run(
            ["git", "-C", str(repo), "show", f"{baseline_ref}:{dut_rel}"],
            check=True, capture_output=True).stdout)
        duts["baseline"] = base
    with tempfile.TemporaryDirectory(prefix="klt-ab-") if run_root is None else contextlib.nullcontext(run_root) as tmp:
        tmp = Path(tmp)
        staged = {}
        for tag, path in duts.items():
            job = job_factory(tag, path)
            stage_dir = (tmp / tag / "stage") if run_root is not None else (tmp / tag)
            staged[tag] = (job, kb.stage(job, stage_dir))
            log(f"{tag}: DUT sha256 {_sha256(path)}")

        def go(tag):
            job, req = staged[tag]
            sub = dest / tag
            saved = sub / "klt-report.json"
            req_saved = sub / "request.json"
            if run_root is not None and saved.is_file() \
                    and req_saved.is_file() \
                    and req_saved.read_bytes() == req.read_bytes():
                return tag, kb.values(json.loads(saved.read_text()), job)
            out = (tmp / tag / "out") if run_root is not None else (tmp / f"{tag}-out")
            report = kb.run(req, out, backend=backend, log=log,
                            resume=run_root is not None and backend == "batch")
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
