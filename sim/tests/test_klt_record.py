#!/usr/bin/env python3
"""Unit tests for sim/harness/klt_record.py. No PDK, ngspice or klt required.

    python3 -m unittest sim/tests/test_klt_record.py -v
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import evidence_store as es  # noqa: E402
from harness import klt_record as kr  # noqa: E402
from harness import tb_adapter as ta  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_evidence_store import fake_klt  # noqa: E402

SLUG = "line-regulation"


class ParsePrior(unittest.TestCase):
    def _newest(self, slug):
        return sorted((SIM_DIR / slug / "records").glob("*.md"))[-1]

    def test_reads_only_the_result_table(self):
        # The spread table that follows quotes measurement names in backticks too.
        cols, grid, shas = kr.parse_prior(self._newest("psrr-vs-freq"))
        self.assertEqual(cols[:2], ["psrr_1k_db", "psrr_100k_db"])
        self.assertEqual(len(grid), 45)
        self.assertTrue(all(c.count("_") >= 2 for c in grid), sorted(grid)[:3])
        self.assertTrue(shas)

    def test_a_cell_that_is_not_a_number_is_none(self):
        _, grid, _ = kr.parse_prior(self._newest("psrr-vs-freq"))
        row = grid["tt_27c_3.30v"]
        self.assertIsInstance(row["psrr_1k_db"], float)
        self.assertIsNone(row["pass/fail"])


class FleetJobs(unittest.TestCase):
    def _jobs(self, remote):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            rep = Path(d) / "klt-3.30v" / "new"
            rep.mkdir(parents=True)
            (rep / "klt-report.json").write_text(json.dumps({"corner_count": 4, "environment": {"remote": remote}}))
            return kr.jobs(Path(d))

    def test_split_request_lists_every_fleet_job(self):
        pdk = {"models_staged": True, "stamp_text": "open_pdks c6d73a3"}
        job = lambda i: {"job_id": f"klt-sim-{i}", "instance_type": "c7i.8xlarge", "state": "done",
                         "worker_environment": {"pdk": pdk}}
        (j,) = self._jobs({"fleet": [job(1), job(2)], "max_concurrent_jobs": 2})
        self.assertEqual(j["job"], "klt-sim-1, klt-sim-2")
        self.assertTrue(j["staged"])
        self.assertEqual(j["stamp"], "open_pdks c6d73a3")

    def test_one_unstaged_fleet_job_unsets_staged(self):
        mk = lambda s: {"job_id": "x", "worker_environment": {"pdk": {"models_staged": s}}}
        (j,) = self._jobs({"fleet": [mk(True), mk(False)]})
        self.assertFalse(j["staged"])

    def test_unsplit_request_keeps_its_single_job(self):
        (j,) = self._jobs({"job_id": "klt-sim-9", "instance_type": "m7i.4xlarge", "state": "done",
                           "worker_environment": {"pdk": {"models_staged": True}}})
        self.assertEqual((j["job"], j["instance"], j["staged"]), ("klt-sim-9", "m7i.4xlarge", True))


class FlatBenchJobs(unittest.TestCase):
    """A single-analysis bench is one request and writes ``new/klt-report.json``
    with no ``klt-*`` level; the old glob listed zero jobs for it (#594)."""

    def test_a_request_with_no_klt_level_is_still_found(self):
        with tempfile.TemporaryDirectory() as d:
            rep = Path(d) / "new"
            rep.mkdir(parents=True)
            (rep / "klt-report.json").write_text(json.dumps(
                {"corner_count": 81, "environment": {"remote": {
                    "job_id": "klt-sim-7", "instance_type": "c7i.8xlarge", "state": "done",
                    "worker_environment": {"pdk": {"models_staged": True,
                                                   "stamp_text": "open_pdks c6d73a3"}}}}}))
            (j,) = kr.jobs(Path(d))
        self.assertEqual((j["request"], j["job"], j["corners"]), ("single", "klt-sim-7", 81))

    def test_the_klt_level_layout_still_wins_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            for sub in ("klt-op1-3.30v", "klt-ac1-3.30v"):
                rep = Path(d) / sub / "new"
                rep.mkdir(parents=True)
                (rep / "klt-report.json").write_text(json.dumps(
                    {"corner_count": 27, "environment": {"remote": {"job_id": sub}}}))
            got = kr.jobs(Path(d))
        self.assertEqual([j["request"] for j in got], ["ac1-3.30v", "op1-3.30v"])


class StoreRun(unittest.TestCase):
    """DR-0044 (#594): minting stores the bytes and commits only the manifest,
    the record, the netlist snapshot and the ``klt-report.json`` envelopes."""

    RID = "20261113-zz-test-0abcdef"

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.repo = Path(td.name).resolve()
        shutil.copytree(SIM_DIR / SLUG / "testbench", self.repo / "sim" / SLUG / "testbench")
        self.exp = self.repo / "sim" / SLUG
        self.stage = ta.stage_corner_dir(self.repo, SLUG, self.RID)
        self.stage.mkdir(parents=True)
        # One request's worth of staged output, in run_ab/collect's own layout.
        (self.stage / "new").mkdir()
        (self.stage / "new" / "klt-report.json").write_text(json.dumps(
            {"corner_count": 1, "environment": {"remote": {
                "job_id": "klt-sim-1", "instance_type": "c7i.8xlarge", "state": "done",
                "worker_environment": {"pdk": {"models_staged": True,
                                               "stamp_text": "open_pdks c6d73a3"}}}}}))
        (self.stage / "new" / "tt_27c_3.30v.log").write_text("ngspice log bytes\n")
        (self.stage / "new" / "dut.spice").write_text("* dut\n")
        (self.stage / "new" / "body.spice").write_text("* body\n")
        (self.stage / "new" / "request.json").write_text('{"engine": "ngspice"}\n')
        (self.stage / "summary.csv").write_text(
            "dut,corner,line_reg_pct_per_v,status,diagnostics,pass\n"
            "new,tt_27c_3.30v,0.01,pass,,True\n")
        self.objects = {}
        self._patch(kr, "REPO", self.repo)

    def _patch(self, mod, name, value):
        old = getattr(mod, name)
        setattr(mod, name, value)
        self.addCleanup(lambda: setattr(mod, name, old))

    def _mint(self, **kw):
        # `store_files` resolves `put_files` from the module at call time, so
        # patching it here routes every put through the shared `fake_klt` stub.
        orig = es.put_files
        self._patch(es, "put_files",
                    lambda files, root, **_: orig(files, root, run=fake_klt(self.objects, **kw)))
        return kr.main([SLUG, "--record-id", self.RID])

    def test_bytes_are_stored_and_only_the_kept_files_are_committed(self):
        self.assertEqual(self._mint(), 0)
        new = sorted(q.relative_to(self.repo).as_posix() for q in self.repo.rglob("*")
                     if q.is_file() and ".work" not in q.parts and "testbench" not in q.parts)
        self.assertEqual(new, [
            f"manifests/artifacts/{SLUG}-{self.RID}.manifest.json",
            f"sim/{SLUG}/corners/{self.RID}/new/klt-report.json",
            f"sim/{SLUG}/netlist-snapshots/{self.RID}.spice",
            f"sim/{SLUG}/records/{self.RID}.md",
        ])

    def test_the_manifest_names_the_stored_files_and_not_the_kept_ones(self):
        self._mint()
        m = json.loads((self.repo / "manifests/artifacts"
                        / f"{SLUG}-{self.RID}.manifest.json").read_text())
        names = [e["name"] for e in m["entries"]]
        prefix = f"sim/{SLUG}/corners/{self.RID}"
        self.assertEqual(names, [f"{prefix}/new/body.spice", f"{prefix}/new/dut.spice",
                                 f"{prefix}/new/request.json", f"{prefix}/new/tt_27c_3.30v.log",
                                 f"{prefix}/summary.csv"])
        # check_artifact_manifests.py fails an entry whose name is a tracked
        # path, so a file that stays in git must never also be an entry.
        self.assertNotIn(f"{prefix}/new/klt-report.json", names)

    def test_the_record_ends_with_the_stored_evidence_table(self):
        self._mint()
        text = (self.exp / "records" / f"{self.RID}.md").read_text()
        self.assertIn("## Stored evidence", text)
        self.assertIn(f"`sim/{SLUG}/corners/{self.RID}/new/tt_27c_3.30v.log`", text)
        self.assertIn("is a **manifest `name`**", text)
        self.assertIn("`klt-sim-1`", text)   # the flat layout's job, via jobs()

    def test_a_store_failure_commits_nothing_and_keeps_the_staged_run(self):
        self.assertEqual(self._mint(fail="broker_unreachable"), kr.EXIT_NOT_STORED)
        self.assertFalse((self.repo / "manifests").exists())
        self.assertFalse((self.exp / "records").exists())
        self.assertFalse((self.exp / "corners").exists())
        self.assertFalse((self.exp / "netlist-snapshots").exists())
        self.assertTrue((self.stage / "new" / "tt_27c_3.30v.log").is_file())

    def test_minting_the_same_record_id_twice_is_refused(self):
        self.assertEqual(self._mint(), 0)
        self.stage.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(SystemExit):
            kr.main([SLUG, "--record-id", self.RID])

    def test_an_unstaged_record_id_is_refused_before_anything_is_written(self):
        with self.assertRaises(SystemExit) as cm:
            kr.main([SLUG, "--record-id", "20261113-absent-0abcdef"])
        self.assertIn("no staged run", str(cm.exception))
        self.assertFalse((self.repo / "manifests").exists())


if __name__ == "__main__":
    unittest.main()
