#!/usr/bin/env python3
"""Driver-level tests for sim/soft-start/testbench/klt_peak_run.py: DR-0044,
issue #647 -- the peak-event driver stages into ``sim/.work/.stage/`` instead
of committing under ``sim/soft-start/corners/``, an unavailable store refuses
the run before any fleet time, a committed record id is never rewritten, both
``--part`` halves accumulate into one staged record minted once, and minting
commits only the manifest, the summary and the ``klt-report.json`` envelopes.
No PDK, ngspice, klt or fleet required; ``run_ab`` is faked.

    python3 -m unittest sim/tests/test_klt_peak_run.py -v
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import shutil
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
REPO = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))
_spec = importlib.util.spec_from_file_location(
    "ss_klt_peak_run", SIM_DIR / "soft-start" / "testbench" / "klt_peak_run.py")
kpr = importlib.util.module_from_spec(_spec)
# klt_peak_run imports its sibling by bare name (`import klt_run`), and under
# discovery another bench's klt_run may already own sys.modules["klt_run"]
# (loop-stability's sweep.py imports its own sibling the same way). Load ours
# with the cache cleared and put the previous occupant back afterwards.
_saved_klt_run = sys.modules.pop("klt_run", None)
try:
    _spec.loader.exec_module(kpr)
finally:
    if _saved_klt_run is not None:
        sys.modules["klt_run"] = _saved_klt_run
    else:
        sys.modules.pop("klt_run", None)

from harness import evidence_store as es  # noqa: E402
from harness import tb_adapter as ta  # noqa: E402
import driver_routing as drt  # noqa: E402


class PeakDriverRouting(unittest.TestCase):
    def setUp(self):
        self.rid = "20261117-zz-peak-driver-test"
        self.addCleanup(shutil.rmtree, ta.stage_corner_dir(REPO, "soft-start", self.rid),
                        ignore_errors=True)
        self.dests: list[Path] = []
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def _run_ab(self, factory, dut, baseline_ref, dest, repo, **kw):
        self.dests.append(Path(dest))
        out = {}
        for tag in ("new", "baseline"):
            sub = Path(dest) / tag
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "klt-report.json").write_text('{"corners": []}\n')
            (sub / "tt_27c_3.30v.log").write_text("m_x = 1.0\n")
            out[tag] = {"tt_27c_3.30v": {"icap_peak_a_1": 1e-3, "t_icap_peak_1": 1e-5,
                                         "isup_peak_a_1": 2e-3, "vout_at_end_1": 1.8,
                                         "dvout_max_vpms_1": 5.0,
                                         "_status": "pass", "_diagnostics": ""}}
        return out

    def _main(self, argv, preflight):
        real = kpr.run_ab
        kpr.run_ab = self._run_ab
        self.addCleanup(lambda: setattr(kpr, "run_ab", real))
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return kpr.main(argv, preflight=preflight)

    def _staged(self) -> Path:
        return ta.stage_corner_dir(REPO, "soft-start", self.rid)

    def _committed(self) -> Path:
        return SIM_DIR / "soft-start" / "corners" / self.rid

    def test_a_run_stages_under_sim_work_not_into_corners(self):
        seen = []
        rc = self._main(["--record-id", self.rid, "--baseline-ref", "origin/main"],
                        lambda repo: seen.append(repo))
        self.assertEqual(rc, 0)
        self.assertEqual(len(seen), 1, "the store is probed once, before any fleet time")
        staged = self._staged()
        self.assertTrue(staged.is_dir())
        self.assertTrue(self.dests and all(staged == d or staged in d.parents for d in self.dests),
                        self.dests)
        self.assertTrue((staged / "summary.csv").is_file())
        self.assertFalse(self._committed().exists())
        out = self.stdout.getvalue()
        self.assertIn(f"staged  : {staged} (not evidence yet)", out)
        self.assertIn("run_store_evidence.py", out)
        self.assertIn("--kind corners", out)
        self.assertIn(self.rid, out)

    def test_an_unstorable_run_exits_10_before_simulating(self):
        def refuse(repo):
            raise es.StoreError("no artifact broker configured ($KLT_ARTIFACT_BROKER is unset)")

        rc = self._main(["--record-id", self.rid, "--baseline-ref", "origin/main"], refuse)
        self.assertEqual(rc, ta.EXIT_NOT_STORED)
        self.assertEqual(self.dests, [], "the fleet was never asked to run anything")
        self.assertFalse(self._staged().exists())
        self.assertFalse(self._committed().exists())
        self.assertIn("EVIDENCE STORE UNAVAILABLE", self.stderr.getvalue())

    def test_an_only_debug_point_needs_no_store(self):
        def explode(repo):
            raise AssertionError("--only must not probe the store")

        rc = self._main(["--record-id", self.rid, "--baseline-ref", "origin/main",
                         "--only", "tt,27,3.30"], explode)
        self.assertEqual(rc, 0)
        self.assertTrue(self._staged().is_dir())

    def test_a_record_id_already_committed_is_refused(self):
        existing = sorted(p for p in (SIM_DIR / "soft-start" / "corners").iterdir()
                          if p.is_dir())[0].name
        with self.assertRaises(SystemExit) as cm:
            self._main(["--record-id", existing, "--baseline-ref", "origin/main"],
                       lambda repo: None)
        self.assertIn("append-only", str(cm.exception))
        self.assertEqual(self.dests, [])

    def test_one_part_names_the_other_and_mints_once_after_both(self):
        rc = self._main(["--record-id", self.rid, "--baseline-ref", "origin/main",
                         "--part", "main"], lambda repo: None)
        self.assertEqual(rc, 0)
        staged = self._staged()
        self.assertTrue((staged / "main" / "new" / "klt-report.json").is_file())
        out = self.stdout.getvalue()
        self.assertIn("--part extra", out)  # the part still owed
        self.assertIn("after the last part", out)
        self.stdout = io.StringIO()
        rc = self._main(["--record-id", self.rid, "--baseline-ref", "origin/main",
                         "--part", "extra"], lambda repo: None)
        self.assertEqual(rc, 0)
        # Both parts live in the same staged record; one mint commits both.
        self.assertTrue((staged / "main" / "new" / "klt-report.json").is_file())
        self.assertTrue((staged / "extra" / "new" / "klt-report.json").is_file())
        rc2, root, committed = drt.mint("soft-start", self.rid, staged)
        self.assertEqual(rc2, 0)
        self.assertEqual(committed, sorted([
            f"manifests/artifacts/soft-start-{self.rid}.manifest.json",
            f"sim/soft-start/corners/{self.rid}.md",
            f"sim/soft-start/corners/{self.rid}/extra/baseline/klt-report.json",
            f"sim/soft-start/corners/{self.rid}/extra/new/klt-report.json",
            f"sim/soft-start/corners/{self.rid}/main/baseline/klt-report.json",
            f"sim/soft-start/corners/{self.rid}/main/new/klt-report.json",
        ]))
        self.assertEqual(drt.check_manifests(root), 0)


if __name__ == "__main__":
    unittest.main()
