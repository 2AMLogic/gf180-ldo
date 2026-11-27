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
import shutil
import subprocess
import tempfile
import types
from pathlib import Path
from unittest import mock

SIM_DIR = Path(__file__).resolve().parents[1]
REPO = SIM_DIR.parent

from harness import evidence_store as es  # noqa: E402
from harness import tb_adapter as ta  # noqa: E402
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


def stub_pinned_pdk(case, pdk_module, path="/nonexistent-pdk"):
    """Stub ``pdk_module.find_pdk`` and save/restore ``$PDK_ROOT`` for *case*.

    The staging drivers pin ``$PDK_ROOT`` before their first submit
    (issue #639), resolving the tree through ``find_pdk()`` -- a host
    dependency the tests do not require, so the tree is stubbed; the assigned
    variable is restored so it never leaks into a later suite in the same
    process. Both undone through ``case.addCleanup``.
    """
    saved_root = os.environ.get("PDK_ROOT")

    def restore_root():
        if saved_root is None:
            os.environ.pop("PDK_ROOT", None)
        else:
            os.environ["PDK_ROOT"] = saved_root
    case.addCleanup(restore_root)
    patcher = mock.patch.object(
        pdk_module, "find_pdk",
        new=lambda variant=None: types.SimpleNamespace(path=Path(path)))
    patcher.start()
    case.addCleanup(patcher.stop)


class RoutingContract:
    """The four DR-0044 staging/refusal contract tests every driver shares.

    A plain mixin (not a TestCase) so unittest discovery never collects the
    abstract base; concrete suites list it before ``unittest.TestCase`` and
    bind ``SLUG`` / ``RID``, provide ``_main(argv, preflight)`` and record
    every directory the faked run was handed in ``self.dests``.

    ``BASE_ARGS`` go on every invocation (a driver's mandatory flags);
    ``STAGE_EXTRA_ARGS`` / ``ONLY_EXTRA_ARGS`` only on the staging and
    ``--only`` runs.
    """

    SLUG = ""
    RID = ""
    BASE_ARGS: tuple = ()
    STAGE_EXTRA_ARGS: tuple = ()
    ONLY_EXTRA_ARGS: tuple = ()

    def setUp(self):
        self.rid = self.RID
        # The drivers resolve their repo from __file__, so a staged run lands
        # in this repo's own git-ignored sim/.work/. Clear this record's
        # stage afterwards so the tests leave no scratch behind, but nothing
        # wider: a bench's other staged records (a soft-start shard parked
        # mid-workflow, say) must survive the test run.
        self.addCleanup(shutil.rmtree, self._staged(), ignore_errors=True)
        self.dests: list[Path] = []
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def _staged(self) -> Path:
        return ta.stage_corner_dir(REPO, self.SLUG, self.rid)

    def _committed(self) -> Path:
        return SIM_DIR / self.SLUG / "corners" / self.rid

    def _argv(self, rid=None, *extra) -> list:
        return ["--record-id", rid or self.rid, *self.BASE_ARGS, *extra]

    def test_a_run_stages_under_sim_work_not_into_corners(self):
        seen = []
        rc = self._main(self._argv(None, *self.STAGE_EXTRA_ARGS),
                        lambda repo: seen.append(repo))
        self.assertEqual(rc, 0)
        self.assertEqual(len(seen), 1, "the store is probed once, before any fleet time")
        staged = self._staged()
        self.assertTrue(staged.is_dir())
        self.assertTrue(self.dests and all(d == staged or staged in d.parents for d in self.dests),
                        self.dests)
        self.assertFalse(self._committed().exists())
        out = self.stdout.getvalue()
        self.assertIn(f"staged  : {staged} (not evidence yet)", out)
        self.assertIn("run_store_evidence.py", out)
        self.assertIn("--kind corners", out)
        self.assertIn(self.rid, out)

    def test_an_unstorable_run_exits_10_before_simulating(self):
        def refuse(repo):
            raise es.StoreError("no artifact broker configured ($KLT_ARTIFACT_BROKER is unset)")

        rc = self._main(self._argv(), refuse)
        self.assertEqual(rc, ta.EXIT_NOT_STORED)
        self.assertEqual(self.dests, [], "the fleet was never asked to run anything")
        self.assertFalse(self._staged().exists())
        self.assertFalse(self._committed().exists())
        self.assertIn("EVIDENCE STORE UNAVAILABLE", self.stderr.getvalue())

    def test_an_only_debug_point_needs_no_store(self):
        def explode(repo):
            raise AssertionError("--only must not probe the store")

        rc = self._main(self._argv(None, *self.ONLY_EXTRA_ARGS, "--only", "tt,27,3.30"),
                        explode)
        self.assertEqual(rc, 0)
        self.assertTrue(self._staged().is_dir())

    def test_a_record_id_already_committed_is_refused(self):
        existing = sorted(p for p in (SIM_DIR / self.SLUG / "corners").iterdir()
                          if p.is_dir())[0].name
        with self.assertRaises(SystemExit) as cm:
            self._main(self._argv(existing), lambda repo: None)
        self.assertIn("append-only", str(cm.exception))
        self.assertEqual(self.dests, [])
