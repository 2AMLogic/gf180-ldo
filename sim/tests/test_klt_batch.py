#!/usr/bin/env python3
"""Unit tests for ``sim/harness/klt_batch.py``'s request builder. No PDK, no klt."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import klt_batch as kb  # noqa: E402


class RequestOptions(unittest.TestCase):
    def test_model_inputs_are_staged_when_requested(self):
        """The fleet worker's /opt/pdk can lag PINNED_OPEN_PDKS_REVISION (#430):
        a job that claims the pin sets stage_model_inputs so it carries this
        host's model files, not the worker's."""
        job = kb.Job(name="t", body="", dut_netlist=Path("dut.spice"),
                     analysis={"kind": "op", "args": ""}, measurements=[],
                     stage_model_inputs=True)
        opts = job.request()["options"]
        self.assertIs(opts["stage_model_inputs"], True)
        self.assertIs(opts["keep_artifacts"], True)

    def _job(self, **kw):
        return kb.Job(name="t", body="", dut_netlist=Path("dut.spice"),
                      analysis={"kind": "op", "args": ""}, measurements=[], **kw)

    def test_monte_carlo_form_is_emitted_only_when_asked(self):
        """mc-output-accuracy takes its redraws from request.monte_carlo, not a .control loop (#469)."""
        mc = {"n": 40, "seed": 469, "vary": "mismatch"}
        self.assertEqual(self._job(monte_carlo=mc).request()["monte_carlo"], mc)
        self.assertNotIn("monte_carlo", self._job().request())

    def test_unit_cap_per_job_is_emitted_only_when_asked(self):
        """A slow-unit bench splits into fleet jobs so none reaches the 3600 s whole-job ceiling (#469)."""
        self.assertEqual(self._job(max_units_per_job=2, timeout_s=1700).request()["batch"],
                         {"max_units_per_job": 2})
        self.assertNotIn("batch", self._job().request())


if __name__ == "__main__":
    unittest.main()
