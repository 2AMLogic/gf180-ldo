#!/usr/bin/env python3
"""Driver-level tests for the three hand-rolled ``klt_run.py`` benches
(current-limit, enable-shutdown, soft-start): DR-0044, issue #646 -- a run
stages into ``sim/.work/.stage/`` instead of committing under
``sim/<bench>/corners/``, an unavailable store refuses the run before any
fleet time, a committed record id is never rewritten, the driver prints the
``--kind corners`` mint, and minting commits only the manifest, the summary
and the ``klt-report.json`` envelopes. No PDK, ngspice, klt or fleet
required; ``run_ab`` and the store's ``klt`` calls are faked.

    python3 -m unittest sim/tests/test_klt_run_drivers.py -v
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

SIM_DIR = Path(__file__).resolve().parents[1]
REPO = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))

from harness import evidence_store as es  # noqa: E402
from harness import tb_adapter as ta  # noqa: E402
from harness.loader import load_script  # noqa: E402

# fake_klt is shared with the store's own tests rather than duplicated: both
# files fake the same `klt artifact put` contract.
_tes = load_script(
    "test_evidence_store", Path(__file__).resolve().parent / "test_evidence_store.py")
fake_klt = _tes.fake_klt

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}

_DRIVERS: dict[str, object] = {}


def _driver(slug: str):
    """The ``klt_run.py`` of ``sim/<slug>/testbench``, imported by path."""
    if slug not in _DRIVERS:
        _DRIVERS[slug] = load_script(
            f"klt_run_{slug.replace('-', '_')}",
            SIM_DIR / slug / "testbench" / "klt_run.py")
    return _DRIVERS[slug]


class _DriverCase:
    """One driver with ``run_ab`` faked: the fake writes each tag's envelope,
    one log and the frozen DUT into whatever ``dest`` the driver handed it.

    A plain mixin (not a TestCase) so the abstract base is not collected;
    the concrete classes below bind ``SLUG``."""

    SLUG = ""

    def setUp(self):
        self.mod = _driver(self.SLUG)
        self.rid = "20261116-zz-driver-test"
        # The drivers resolve their repo from __file__, so a staged run lands
        # in this repo's own git-ignored sim/.work/. Clear this record's
        # stage afterwards so the tests leave no scratch behind, but nothing
        # wider: a bench's other staged records (a soft-start shard parked
        # mid-workflow, say) must survive the test run.
        self.addCleanup(shutil.rmtree, self._staged(), ignore_errors=True)
        self.dests: list[Path] = []
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def _run_ab(self, job_factory, dut, baseline_ref, dest, repo, **kw):
        self.dests.append(Path(dest))
        out = {}
        for tag in (["new", "baseline"] if baseline_ref else ["new"]):
            sub = Path(dest) / tag
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "klt-report.json").write_text('{"corners": []}\n')
            (sub / "tt_27c_3.30v.log").write_text("m_x = 1.0\n")
            (sub / "dut.spice").write_text("* frozen dut\n")
            out[tag] = {"tt_27c_3.30v": {"m_x": 1.0, "_status": "pass", "_diagnostics": ""}}
        return out

    def _summarize(self, cmd, **kw):
        # enable-shutdown rolls its logs up through summarize.py as a
        # subprocess; summarize takes the directory as argv and so follows
        # dest on its own -- record where it was pointed.
        self.dests.append(Path(cmd[2]))
        return types.SimpleNamespace(returncode=0)

    def _main(self, argv, preflight):
        real = self.mod.run_ab
        self.mod.run_ab = self._run_ab
        self.addCleanup(lambda: setattr(self.mod, "run_ab", real))
        with contextlib.redirect_stdout(self.stdout), \
                contextlib.redirect_stderr(self.stderr), \
                mock.patch("subprocess.run", side_effect=self._summarize):
            return self.mod.main(argv, preflight=preflight)

    def _staged(self) -> Path:
        return ta.stage_corner_dir(REPO, self.SLUG, self.rid)

    def _committed(self) -> Path:
        return SIM_DIR / self.SLUG / "corners" / self.rid

    # -- the DR-0044 contract every driver shares ---------------------------

    def test_a_run_stages_under_sim_work_not_into_corners(self):
        seen = []
        rc = self._main(["--record-id", self.rid], lambda repo: seen.append(repo))
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

        rc = self._main(["--record-id", self.rid], refuse)
        self.assertEqual(rc, ta.EXIT_NOT_STORED)
        self.assertEqual(self.dests, [], "the fleet was never asked to run anything")
        self.assertFalse(self._staged().exists())
        self.assertFalse(self._committed().exists())
        self.assertIn("EVIDENCE STORE UNAVAILABLE", self.stderr.getvalue())

    def test_an_only_debug_point_needs_no_store(self):
        def explode(repo):
            raise AssertionError("--only must not probe the store")

        rc = self._main(["--record-id", self.rid, "--only", "tt,27,3.30"], explode)
        self.assertEqual(rc, 0)
        self.assertTrue(self._staged().is_dir())

    def test_a_record_id_already_committed_is_refused(self):
        existing = sorted(p for p in (SIM_DIR / self.SLUG / "corners").iterdir()
                          if p.is_dir())[0].name
        with self.assertRaises(SystemExit) as cm:
            self._main(["--record-id", existing], lambda repo: None)
        self.assertIn("append-only", str(cm.exception))
        self.assertEqual(self.dests, [])

    def test_a_baseline_ab_run_stages_and_stores_both_tags(self):
        rc = self._main(["--record-id", self.rid, "--baseline-ref", "origin/main"],
                        lambda repo: None)
        self.assertEqual(rc, 0)
        staged = self._staged()
        for tag in ("new", "baseline"):
            self.assertTrue(list(staged.rglob(f"{tag}/klt-report.json")),
                            f"no staged envelope for the {tag} DUT")
        rc, root, committed = self._mint()
        self.assertEqual(rc, 0)
        for env in staged.rglob("klt-report.json"):
            rel = f"sim/{self.SLUG}/corners/{self.rid}/{env.relative_to(staged)}"
            self.assertIn(rel, committed, f"the {rel} envelope was not committed")

    # -- the mint, through run_store_evidence.py --kind corners (#645) ------

    def _mint(self):
        """Mint this run's staged tree into a scratch repo root, with the
        store's ``klt artifact put`` calls faked. Returns (rc, root, the
        sorted list of committed repo-relative paths)."""
        store_cli = load_script(
            "run_store_evidence_drivers", SIM_DIR / "run_store_evidence.py")
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        base = Path(td.name).resolve()
        root = base / "repo"
        root.mkdir()
        (root / "sim" / self.SLUG).mkdir(parents=True)
        store_cli.REPO_ROOT = root
        summary = base / f"{self.SLUG}-{self.rid}.md"
        summary.write_text("# record\n")
        store = {}
        real_put = es.put_files

        def put(files, r):
            return real_put(files, r, run=fake_klt(store))

        with mock.patch.object(es, "preflight", side_effect=None), \
                mock.patch.object(es, "put_files", side_effect=put), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = store_cli.main([self.SLUG, self.rid, str(self._staged()),
                                 "--summary", str(summary), "--kind", "corners"])
        committed = sorted(p.relative_to(root).as_posix()
                           for p in root.rglob("*") if p.is_file())
        return rc, root, committed

    def _check_manifests(self, root: Path) -> int:
        """``check_artifact_manifests.py check`` over the minted scratch repo."""
        chk = load_script(
            "check_artifact_manifests_drivers",
            REPO / "scripts" / "check_artifact_manifests.py")
        for cmd in (["git", "-C", str(root), "init", "-q", "-b", "main"],
                    ["git", "-C", str(root), "add", "-A"],
                    ["git", "-C", str(root), "commit", "-q", "-m", "t"]):
            subprocess.run(cmd, env=_GIT_ENV, check=True, capture_output=True)
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return chk.main(["check", "--repo", str(root), "--tree", "HEAD"])

    def test_a_minted_run_commits_only_manifest_summary_and_envelopes(self):
        self._main(["--record-id", self.rid], lambda repo: None)
        rc, root, committed = self._mint()
        self.assertEqual(rc, 0)
        staged = self._staged()
        # The file count, not an eyeball: exactly the manifest, the summary,
        # and one committed envelope per staged klt-report.json.
        envelopes = sorted(p.relative_to(staged).as_posix()
                           for p in staged.rglob("klt-report.json"))
        self.assertEqual(committed, sorted(
            [f"manifests/artifacts/{self.SLUG}-{self.rid}.manifest.json",
             f"sim/{self.SLUG}/corners/{self.rid}.md"]
            + [f"sim/{self.SLUG}/corners/{self.rid}/{e}" for e in envelopes]))
        for env in staged.rglob("klt-report.json"):
            dst = root / "sim" / self.SLUG / "corners" / self.rid / env.relative_to(staged)
            self.assertEqual(dst.read_bytes(), env.read_bytes())
        # Everything else went to the store: every staged file that is not an
        # envelope is a manifest entry, and no entry names a committed path.
        staged_files = sorted(p.relative_to(staged).as_posix()
                              for p in staged.rglob("*") if p.is_file())
        m = json.loads((root / "manifests" / "artifacts"
                        / f"{self.SLUG}-{self.rid}.manifest.json").read_text())
        self.assertEqual(sorted(e["name"] for e in m["entries"]),
                         [f"sim/{self.SLUG}/corners/{self.rid}/{f}"
                          for f in staged_files if not f.endswith("klt-report.json")])
        self.assertEqual(self._check_manifests(root), 0)


class CurrentLimitDriver(_DriverCase, unittest.TestCase):
    SLUG = "current-limit"


class EnableShutdownDriver(_DriverCase, unittest.TestCase):
    SLUG = "enable-shutdown"


class SoftStartDriver(_DriverCase, unittest.TestCase):
    SLUG = "soft-start"

    def test_shards_accumulate_into_one_record_and_mint_once_after_the_last(self):
        rc = self._main(["--record-id", self.rid, "--part", "main", "--process", "tt"],
                        lambda repo: None)
        self.assertEqual(rc, 0)
        self.assertTrue((self._staged() / "main-tt" / "new" / "klt-report.json").is_file())
        out = self.stdout.getvalue()
        self.assertIn("--part main --process ff", out)  # the shards still owed
        self.assertIn("after the last shard", out)
        self.stdout = io.StringIO()
        rc = self._main(["--record-id", self.rid, "--part", "main", "--process", "ff"],
                        lambda repo: None)
        self.assertEqual(rc, 0)
        # Both shards live in the same staged record; one mint commits both.
        staged = self._staged()
        self.assertTrue((staged / "main-tt" / "new" / "klt-report.json").is_file())
        self.assertTrue((staged / "main-ff" / "new" / "klt-report.json").is_file())
        rc, root, committed = self._mint()
        self.assertEqual(rc, 0)
        self.assertEqual(committed, sorted([
            f"manifests/artifacts/{self.SLUG}-{self.rid}.manifest.json",
            f"sim/{self.SLUG}/corners/{self.rid}.md",
            f"sim/{self.SLUG}/corners/{self.rid}/main-ff/new/klt-report.json",
            f"sim/{self.SLUG}/corners/{self.rid}/main-tt/new/klt-report.json",
        ]))


if __name__ == "__main__":
    unittest.main()
