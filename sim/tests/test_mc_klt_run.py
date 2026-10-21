#!/usr/bin/env python3
"""Unit tests for sim/mc-output-accuracy/testbench/klt_run.py. No PDK, ngspice or klt required.

    python3 -m unittest sim/tests/test_mc_klt_run.py -v
"""

from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))
_spec = importlib.util.spec_from_file_location(
    "mc_klt_run", SIM_DIR / "mc-output-accuracy" / "testbench" / "klt_run.py")
mc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mc)


def _sample(offset: float, dfb: float | None = None) -> dict:
    s = {f"dv_{k}": offset + 0.01 * k for k in range(1, mc.COPIES + 1)}
    s["dfb"] = s["dv_1"] / 1.5 if dfb is None else dfb
    return s


class Statistics(unittest.TestCase):
    def test_matches_tb_json_definitions(self):
        samples = {i: _sample(0.1 * i) for i in range(4)}
        st = mc.statistics(samples)
        dv = [v for s in samples.values() for k, v in s.items() if k.startswith("dv_")]
        mean = sum(dv) / len(dv)
        sd = math.sqrt(sum((x - mean) ** 2 for x in dv) / (len(dv) - 1))
        self.assertEqual(st["n_samples"], 100)
        self.assertAlmostEqual(st["mean_mv"], mean)
        self.assertAlmostEqual(st["sigma_mv"], sd)
        self.assertAlmostEqual(st["sigma3_mv"], 3 * sd)
        self.assertAlmostEqual(st["vos_in_sigma3_mv"], 2 * sd)
        self.assertAlmostEqual(st["worst_abs_mv"], max(abs(x) for x in dv))
        self.assertAlmostEqual(st["divider_exact_uv"], 0.0, places=6)
        self.assertEqual(st["n_bad_solves"], 0)

    def test_divider_residual_is_in_microvolts(self):
        st = mc.statistics({0: _sample(0.0, dfb=_sample(0.0)["dv_1"] / 1.5 + 0.002)})
        self.assertAlmostEqual(st["divider_exact_uv"], 1.5 * 0.002 * 1e3)

    def test_a_sample_off_regulation_is_a_bad_solve(self):
        samples = {0: _sample(0.0), 1: _sample(150.0)}
        self.assertEqual(mc.statistics(samples)["n_bad_solves"], 1)


class SampleRows(unittest.TestCase):
    def _corner(self, idx, status="pass", missing=False):
        meas = [{"name": m["name"], "value": None if (missing and m["name"] == "dv_3") else 0.1}
                for m in mc.MEASUREMENTS]
        return {"corner_id": f"tt/novdd/27C/mc{idx}", "process": "tt", "temperature_c": 27.0,
                "status": status, "supply_v": {}, "measurements": meas,
                "monte_carlo": {"sample_index": idx}}

    def test_a_lost_sample_is_not_counted(self):
        """A point that loses samples must fail the 1000-sample check, not report a thinner distribution."""
        job = mc.job("new", Path("dut.spice"), 3.30, "tt", None, 3, 1)
        report = {"corners": [self._corner(0), self._corner(1, status="error"), self._corner(2, missing=True)]}
        rows = mc.sample_rows(report, job)
        self.assertEqual({k: sorted(v) for k, v in rows.items()}, {"tt_27c_3.30v": [0]})

    def test_request_is_the_monte_carlo_form(self):
        job = mc.job("new", Path("dut.spice"), 3.63, "ff", None, 40, 469)
        req = job.request()
        self.assertEqual(req["monte_carlo"], {"n": 40, "seed": 469, "vary": "mismatch"})
        self.assertEqual(req["analysis"]["kind"], "op")
        self.assertEqual(len(req["measurements"]), mc.COPIES + 1)
        self.assertEqual(len(job.body.split("X1 ")), 2)
        self.assertIn(".param vdd_val=3.63", job.body)
        self.assertIs(req["options"]["stage_model_inputs"], True)


if __name__ == "__main__":
    unittest.main()
