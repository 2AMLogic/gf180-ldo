#!/usr/bin/env python3
"""Unit tests for ``sim/harness/klt_batch.py``'s request builder. No PDK, no klt."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import corners  # noqa: E402
from harness import klt_batch as kb  # noqa: E402


class CornerId(unittest.TestCase):
    """One corner-id spelling on both sides of the report join (issue #780).

    The sweep keys its grid points by :attr:`harness.corners.PvtPoint.corner_id`
    and looks the klt report's rows up by :func:`klt_batch.corner_id`; when the
    two formatters disagreed (six-significant-digit grid vs full-precision
    report) a measurement the report contained was reported as a missing row.
    """

    def test_report_rows_and_grid_points_agree_across_the_default_axes(self):
        grid = corners.build_grid(
            corners.resolve_corners(["mos"]),
            corners.DEFAULT_TEMPERATURES_C,
            corners.supply_points(),
        )
        for p in grid:
            with self.subTest(corner_id=p.corner_id):
                row = {"process": p.corner.name, "temperature_c": p.temp_c,
                       "supply_v": {"vin": p.vdd}}
                self.assertEqual(kb.corner_id(row, "vin"), p.corner_id)

    def test_report_rows_keep_fractional_temperature_and_normalize_signed_zero(self):
        self.assertEqual(
            kb.corner_id({"process": "tt", "temperature_c": 27.123456,
                          "supply_v": {"vin": 3.3}}, "vin"),
            "tt_27.123456c_3.30v",
        )
        self.assertEqual(
            kb.corner_id({"process": "tt", "temperature_c": -0.0,
                          "supply_v": {"vin": 3.3}}, "vin"),
            "tt_0c_3.30v",
        )

    def test_the_supply_is_still_klts_own_selection(self):
        """The shared formatter changed only the id's spelling; which supply a
        report row names stays klt's: the fixed override, else the
        ``corners.params`` row, else the ``corners.supply_v`` axis."""
        via_params = {"process": "tt", "temperature_c": 27.0,
                      "params": {"vsup": 2.97}, "supply_v": {"vin": 3.63}}
        via_axis = {"process": "tt", "temperature_c": 27.0,
                    "supply_v": {"vin": 3.63}}
        self.assertEqual(kb.corner_id(via_params, "vsup"), "tt_27c_2.97v")
        self.assertEqual(kb.corner_id(via_params, "vin"), "tt_27c_3.63v")
        self.assertEqual(kb.corner_id(via_axis, "vin"), "tt_27c_3.63v")
        self.assertEqual(kb.corner_id(via_axis, "vin", 2.97), "tt_27c_2.97v")


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

    def test_every_request_carries_the_default_capacity_wait(self):
        """Fleet capacity is klt's to wait out (issue #610): the dispatch-host
        rule -- a 600 s ``batch.capacity_wait_s`` on every batch submit -- is
        applied once here, so a driver that sets no ``batch`` (89 of the 98
        committed requests when #610 was filed) still waits out a refusal."""
        for batch in (None, {}):
            with self.subTest(batch=batch):
                self.assertEqual(self._job(batch=batch).request()["batch"],
                                 {"capacity_wait_s": kb.DEFAULT_CAPACITY_WAIT_S})

    def test_driver_keys_merge_over_the_default_capacity_wait(self):
        """A shard-only mapping inherits the default; an explicit
        ``capacity_wait_s`` -- including 0, a deliberate no-wait -- wins, and
        the caller's mapping is left intact. A later default job still emits
        600: the default is rebuilt per request, never a shared mapping a
        driver could mutate."""
        shard_only = {"max_units_per_job": 2, "max_concurrent_jobs": 2}
        self.assertEqual(
            self._job(batch=shard_only).request()["batch"],
            {"max_units_per_job": 2, "max_concurrent_jobs": 2,
             "capacity_wait_s": kb.DEFAULT_CAPACITY_WAIT_S})
        self.assertEqual(shard_only, {"max_units_per_job": 2, "max_concurrent_jobs": 2})
        self.assertEqual(self._job(batch={"capacity_wait_s": 0}).request()["batch"],
                         {"capacity_wait_s": 0})
        batch = {"max_units_per_job": 2, "max_concurrent_jobs": 2, "capacity_wait_s": 7200}
        self.assertEqual(self._job(batch=batch, timeout_s=1700).request()["batch"], batch)
        self.assertEqual(self._job().request()["batch"],
                         {"capacity_wait_s": kb.DEFAULT_CAPACITY_WAIT_S})


class StageTokenGuard(unittest.TestCase):
    """#827: an unrendered @TOKEN@ never reaches the staged deck."""

    def _job(self, body):
        return kb.Job(name="t", body=body, dut_netlist=Path(__file__),
                      analysis={"kind": "op", "args": ""}, measurements=[])

    def test_unfilled_token_raises_and_writes_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wd = Path(d) / "w"
            with self.assertRaises(SystemExit) as cm:
                kb.stage(self._job("Bload out 0 @BLOAD@\n"), wd)
            self.assertIn("BLOAD", str(cm.exception))
            self.assertFalse((wd / "body.spice").exists())

    def test_bare_at_syntax_still_stages(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wd = Path(d) / "w"
            kb.stage(self._job("* bench @ tt_27c\nalter @Vinj[acmag] = 1\n"), wd)
            self.assertTrue((wd / "body.spice").exists())


if __name__ == "__main__":
    unittest.main()
