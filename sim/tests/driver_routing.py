#!/usr/bin/env python3
"""Shared DR-0044 routing-test helpers (issues #646/#647, #861).

The driver tests in ``test_klt_run_drivers.py``, ``test_mc_klt_run.py``,
``test_bias_acq.py`` and ``test_klt_peak_run.py`` all need the same two
out-of-band steps: minting a staged run through
``sim/run_store_evidence.py --kind corners`` with the store's
``klt artifact put`` calls faked, and grading the result with
``scripts/check_artifact_manifests.py``. One module, not four copies of the
same dance. Not a test module (the name keeps unittest discovery away).

    python3 -m unittest discover -s sim/tests -t sim/tests
"""

from __future__ import annotations

import atexit
import contextlib
import io
import json
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

# Loaded once here, not per mint()/check_manifests() call: neither script
# keeps state between main() invocations -- run_store_evidence's REPO_ROOT is
# the one mutable global, and mint() re-aims it at each scratch root before
# main() runs.
_store_cli = load_script(
    "run_store_evidence_routing", SIM_DIR / "run_store_evidence.py")
_chk = load_script(
    "check_artifact_manifests_routing", REPO / "scripts" / "check_artifact_manifests.py")

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}


def mint(bench: str, rid: str, staged: Path, cleanup=atexit.register):
    """Mint ``staged`` into a scratch repo root, ``klt`` faked.

    Runs ``sim/run_store_evidence.py <bench> <rid> <staged> --summary ...
    --kind corners`` against a throwaway repo root with the store's puts
    faked, exactly the command the drivers print. Returns
    ``(rc, root, committed)`` where ``committed`` is the sorted list of
    repo-relative paths the scratch root gained.

    ``cleanup`` receives the scratch directory's teardown: the default
    parks the directory until interpreter exit, since the caller inspects
    ``root`` after mint returns; a ``TestCase`` passes ``self.addCleanup``
    for per-test teardown instead.
    """
    td = tempfile.TemporaryDirectory()
    cleanup(td.cleanup)
    base = Path(td.name).resolve()
    root = base / "repo"
    (root / "sim" / bench).mkdir(parents=True)
    _store_cli.REPO_ROOT = root
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
        rc = _store_cli.main([bench, rid, str(staged),
                              "--summary", str(summary), "--kind", "corners"])
    committed = sorted(p.relative_to(root).as_posix()
                       for p in root.rglob("*") if p.is_file())
    return rc, root, committed


def check_manifests(root: Path) -> int:
    """``check_artifact_manifests.py check`` over the minted scratch repo."""
    for cmd in (["git", "-C", str(root), "init", "-q", "-b", "main"],
                ["git", "-C", str(root), "add", "-A"],
                ["git", "-C", str(root), "commit", "-q", "-m", "t"]):
        subprocess.run(cmd, env=GIT_ENV, check=True, capture_output=True)
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        return _chk.main(["check", "--repo", str(root), "--tree", "HEAD"])


def assert_corners_mint(case, bench: str, rid: str, staged: Path):
    """Mint ``staged`` and assert the whole DR-0044 ``--kind corners`` split.

    One call runs ``mint(..., cleanup=case.addCleanup)`` and checks the four
    parts every routing test shares: a zero exit code; the exact committed
    path set; each kept ``klt-report.json`` envelope byte-identical to its
    staged original; and the non-empty set of non-envelope staged files
    matching ``manifest["entries"]`` with ``check_manifests(root) == 0``.
    Assertions run on *case*, so failures attribute to the calling test.

    Returns ``(committed, manifest)`` so multi-part and multi-scenario
    tests can keep their specific file assertions -- which envelopes of
    which parts were committed, which names the entries must include.
    """
    rc, root, committed = mint(bench, rid, staged, cleanup=case.addCleanup)
    case.assertEqual(rc, 0)
    # The file count, not an eyeball: exactly the manifest, the summary,
    # and one committed envelope per staged klt-report.json.
    envelopes = sorted(p.relative_to(staged).as_posix()
                       for p in staged.rglob("klt-report.json"))
    case.assertEqual(committed, sorted(
        [f"manifests/artifacts/{bench}-{rid}.manifest.json",
         f"sim/{bench}/corners/{rid}.md"]
        + [f"sim/{bench}/corners/{rid}/{e}" for e in envelopes]))
    for env in staged.rglob("klt-report.json"):
        dst = root / "sim" / bench / "corners" / rid / env.relative_to(staged)
        case.assertEqual(dst.read_bytes(), env.read_bytes())
    # Everything else went to the store: every staged file that is not an
    # envelope is a manifest entry, and no entry names a committed path.
    staged_files = sorted(p.relative_to(staged).as_posix()
                          for p in staged.rglob("*") if p.is_file())
    m = json.loads((root / "manifests" / "artifacts"
                    / f"{bench}-{rid}.manifest.json").read_text())
    stored = [f for f in staged_files if not f.endswith("klt-report.json")]
    case.assertTrue(stored,
                    "a corners mint must store at least one non-envelope file")
    case.assertEqual(sorted(e["name"] for e in m["entries"]),
                     [f"sim/{bench}/corners/{rid}/{f}" for f in stored])
    case.assertEqual(check_manifests(root), 0)
    return committed, m
