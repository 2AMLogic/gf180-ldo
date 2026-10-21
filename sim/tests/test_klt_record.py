#!/usr/bin/env python3
"""Unit tests for sim/harness/klt_record.py. No PDK, ngspice or klt required.

    python3 -m unittest sim/tests/test_klt_record.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import klt_record as kr  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
