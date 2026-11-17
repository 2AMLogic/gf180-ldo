#!/usr/bin/env python3
"""Shared DR-0044 routing-test helpers (issues #646/#647).

The driver tests in ``test_mc_klt_run.py``, ``test_bias_acq.py`` and
``test_klt_peak_run.py`` all need the same two out-of-band steps: minting a
staged run through ``sim/run_store_evidence.py --kind corners`` with the
store's ``klt artifact put`` calls faked, and grading the result with
``scripts/check_artifact_manifests.py``. One module, not three copies of the
same dance. Not a test module (the name keeps unittest discovery away).

    python3 -m unittest discover -s sim/tests -t sim/tests
"""

from __future__ import annotations

import atexit
import contextlib
import io
import os
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

SIM_DIR = Path(__file__).resolve().parents[1]
REPO = SIM_DIR.parent

from harness import evidence_store as es  # noqa: E402
from harness.loader import load_script  # noqa: E402

# fake_klt is shared with the store's own tests rather than duplicated: both
# files fake the same `klt artifact put` contract.
_tes = load_script(
    "test_evidence_store", Path(__file__).resolve().parent / "test_evidence_store.py")
fake_klt = _tes.fake_klt

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}


def mint(bench: str, rid: str, staged: Path):
    """Mint ``staged`` into a scratch repo root, ``klt`` faked.

    Runs ``sim/run_store_evidence.py <bench> <rid> <staged> --summary ...
    --kind corners`` against a throwaway repo root with the store's puts
    faked, exactly the command the drivers print. Returns
    ``(rc, root, committed)`` where ``committed`` is the sorted list of
    repo-relative paths the scratch root gained.
    """
    store_cli = load_script(
        f"run_store_evidence_{bench.replace('-', '_')}", SIM_DIR / "run_store_evidence.py")
    td = tempfile.TemporaryDirectory()
    atexit.register(td.cleanup)  # the caller inspects root after mint returns
    base = Path(td.name).resolve()
    root = base / "repo"
    (root / "sim" / bench).mkdir(parents=True)
    store_cli.REPO_ROOT = root
    summary = base / f"{bench}-{rid}.md"
    summary.write_text("# record\n")
    store: dict = {}
    real_put = es.put_files

    def put(files, r):
        return real_put(files, r, run=fake_klt(store))

    with mock.patch.object(es, "preflight", side_effect=None), \
            mock.patch.object(es, "put_files", side_effect=put), \
            contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        rc = store_cli.main([bench, rid, str(staged),
                             "--summary", str(summary), "--kind", "corners"])
    committed = sorted(p.relative_to(root).as_posix()
                       for p in root.rglob("*") if p.is_file())
    return rc, root, committed


def check_manifests(root: Path) -> int:
    """``check_artifact_manifests.py check`` over the minted scratch repo."""
    chk = load_script(
        "check_artifact_manifests_routing", REPO / "scripts" / "check_artifact_manifests.py")
    for cmd in (["git", "-C", str(root), "init", "-q", "-b", "main"],
                ["git", "-C", str(root), "add", "-A"],
                ["git", "-C", str(root), "commit", "-q", "-m", "t"]):
        subprocess.run(cmd, env=GIT_ENV, check=True, capture_output=True)
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        return chk.main(["check", "--repo", str(root), "--tree", "HEAD"])
