#!/usr/bin/env python3
"""Unit tests for sim/harness/tb_adapter.py. No PDK, ngspice or klt required.

    python3 -m unittest sim/tests/test_tb_adapter.py -v
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import tb_adapter as ta  # noqa: E402
from harness import testbench  # noqa: E402

DUT = SIM_DIR.parent / "design" / "netlist" / "ldo_core.spice"


def _tb(slug: str) -> testbench.Testbench:
    return testbench.load(SIM_DIR / slug / "testbench")


def _grid(job) -> int:
    return len(job.process) * len(job.temps) * len(job.supplies)


class SplitAnalyses(unittest.TestCase):
    def test_single_supply_sweep_and_meas_cards(self):
        analysis, cards = ta.split_analyses(
            ["dc Vsup 2.20 1.75 -0.005", "meas dc vin_knee_v WHEN v(vout)=1.764 FALL=1"]
        )
        self.assertEqual(analysis, {"kind": "dc", "args": "Vsup 2.20 1.75 -0.005"})
        self.assertEqual(cards, [{"name": "vin_knee_v",
                                  "spice": ".meas dc vin_knee_v WHEN v(vout)=1.764 FALL=1"}])

    def test_nested_sweep_keeps_both_source_triples(self):
        analysis, cards = ta.split_analyses(["dc Vsup 2.97 3.63 0.66 Vilc 1m 50m 49m"])
        self.assertEqual(analysis["args"], "Vsup 2.97 3.63 0.66 Vilc 1m 50m 49m")
        self.assertEqual(cards, [])

    def test_chained_analyses_are_refused(self):
        with self.assertRaises(ta.UnsupportedTb):
            ta.split_analyses(["op", "ac dec 10 1 1e6"])

    def test_no_analysis_is_refused(self):
        with self.assertRaises(ta.UnsupportedTb):
            ta.split_analyses(["meas dc x FIND v(a) AT=1"])


class MapExpr(unittest.TestCase):
    def test_m_reference_to_a_measurement_is_bare(self):
        self.assertEqual(
            ta.map_expr("abs(m_a - m_b)*1e3", "dc", {"a": "v(x)[0]", "b": "v(x)[1]"}),
            "abs(a - b)*1e3")

    def test_m_prefix_on_a_non_measurement_is_left_alone(self):
        self.assertEqual(ta.map_expr("m_other + 1", "dc", {"a": "1"}), "m_other + 1")

    def test_own_plot_qualifier_is_dropped(self):
        self.assertEqual(ta.map_expr("-op1.i(vsup1)*1e6", "op", {}), "-i(vsup1)*1e6")
        self.assertEqual(ta.map_expr("180 + ac1.ph_ugbw", "ac", {}), "180 + ph_ugbw")

    def test_foreign_plot_qualifier_is_refused(self):
        with self.assertRaises(ta.UnsupportedTb):
            ta.map_expr("op1.v(a) - ac1.v(b)", "ac", {})


class Measurements(unittest.TestCase):
    def test_dropout_derives_from_meas_cards_via_param(self):
        _, specs = ta.measurements(_tb("dropout-vs-load"))
        by = {s["name"]: s for s in specs}
        self.assertEqual(by["vdrop_mv"]["spice"],
                         ".meas dc vdrop_mv param='(vin_knee_v - 1.764)*1e3'")
        self.assertNotIn("expr", by["vdrop_mv"])
        # a later param may read an earlier one
        self.assertIn("vin_knee_last_v", by["knee_uniqueness_mv"]["spice"])

    def test_vector_measure_stays_an_expr(self):
        _, specs = ta.measurements(_tb("line-regulation"))
        by = {s["name"]: s for s in specs}
        self.assertEqual(by["vout_1ma_lo"], {"name": "vout_1ma_lo", "expr": "v(vout)[0]"})
        self.assertEqual(by["line_reg_1ma_mvpv"]["expr"],
                         "abs(vout_1ma_hi - vout_1ma_lo)/0.66*1e3")

    def test_mixing_card_results_with_vector_reads_is_refused(self):
        tb = dataclasses.replace(
            _tb("dropout-vs-load"),
            measure={"bad": "vin_knee_v + v(vout)"},
        )
        with self.assertRaises(ta.UnsupportedTb):
            ta.measurements(tb)

    def test_every_manifest_measure_is_requested(self):
        for slug in ("dropout-vs-load", "line-regulation", "load-regulation"):
            tb = _tb(slug)
            _, specs = ta.measurements(tb)
            self.assertTrue(set(tb.measure) <= {s["name"] for s in specs}, slug)


class JobGrid(unittest.TestCase):
    def test_grid_sizes_match_the_local_records(self):
        # 9 process x 3 T x {1, 1, 3} supplies, as in the run_corners.py records.
        for slug, n in (("dropout-vs-load", 27), ("line-regulation", 27),
                        ("load-regulation", 81)):
            self.assertEqual(_grid(ta.job(_tb(slug), "new", DUT)), n, slug)

    def test_only_collapses_to_one_point(self):
        self.assertEqual(_grid(ta.job(_tb("load-regulation"), "new", DUT, "tt,27,3.30")), 1)

    def test_body_has_dut_include_nodeset_and_no_pdk_lib_or_temp(self):
        body = ta.job(_tb("dropout-vs-load"), "new", DUT).body
        self.assertIn('.include "dut.spice"', body)
        self.assertIn(".nodeset v(vout)=1.8 v(loop)=0.7", body)
        self.assertIn(".options wnflag=1", body)
        self.assertNotIn(".lib", body)
        self.assertNotIn(".temp", body)
        self.assertNotIn(".control", body)

    def test_request_carries_numdgt(self):
        req = ta.job(_tb("line-regulation"), "new", DUT).request()
        self.assertIn("set numdgt=10", req["options"]["ngspice_init"])
        self.assertEqual(req["analysis"]["kind"], "dc")
        self.assertEqual(req["corners"]["supply_v"], {"vsup": [3.3]})

    def test_request_stages_the_submitters_models(self):
        # Without this the batch image's own PDK revision runs, not the pinned one.
        req = ta.job(_tb("load-regulation"), "new", DUT).request()
        self.assertIs(req["options"]["stage_model_inputs"], True)


class Grade(unittest.TestCase):
    def test_bounds_and_missing_values(self):
        tb = _tb("load-regulation")
        ok = {"load_reg_mv": 0.0018, "iload_1ma_ma": 1.0, "iload_50ma_ma": 50.0,
              "vout_1ma": 1.7993, "vout_50ma": 1.7993}
        self.assertTrue(ta.grade(tb, ok))
        self.assertFalse(ta.grade(tb, {**ok, "load_reg_mv": 18.5}))
        self.assertFalse(ta.grade(tb, {**ok, "iload_50ma_ma": 49.0}))
        self.assertFalse(ta.grade(tb, {**ok, "vout_1ma": None}))
        self.assertFalse(ta.grade(tb, {k: v for k, v in ok.items() if k != "vout_50ma"}))


if __name__ == "__main__":
    unittest.main()
