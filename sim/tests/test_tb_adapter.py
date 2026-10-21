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


class ParamExpr(unittest.TestCase):
    def test_db_becomes_log10(self):
        self.assertEqual(ta.param_expr("a + db(2.0/3.0)"), "a + (20*log10(abs(2.0/3.0)))")

    def test_nested_and_vdb_untouched(self):
        self.assertEqual(ta.param_expr("db(abs(x)) - db(y)"),
                         "(20*log10(abs(abs(x)))) - (20*log10(abs(y)))")
        self.assertEqual(ta.param_expr("vdb(vg1)"), "vdb(vg1)")


class States(unittest.TestCase):
    """Benches that chain ``op`` / ``ac`` in one ``.control`` block (#468)."""

    def _by_state(self, slug):
        sts, init = ta.states(_tb(slug))
        return {s.name: s for s in sts}, init

    def test_amp_openloop_splits_into_op_and_ac(self):
        sts, init = self._by_state("amp-openloop")
        self.assertEqual(list(sts), ["op1", "ac1"])   # the trailing `ac lin 1 1k 1k` measures nothing
        self.assertEqual(init, ["set units=degrees"])
        self.assertEqual(sts["ac1"].analysis, {"kind": "ac", "args": "dec 40 0.1 1e9"})
        by = {m["name"]: m for m in sts["op1"].specs}
        self.assertEqual(by["iq_ua"], {"name": "iq_ua", "expr": "-i(vsup1)*1e6"})
        by = {m["name"]: m for m in sts["ac1"].specs}
        self.assertEqual(by["pm_deg"]["spice"], ".meas ac pm_deg param='180 + ph_ugbw'")
        # `a0_db: ac1.a0_db` is the card itself, not a second measurement of that name
        self.assertEqual([m["name"] for m in sts["ac1"].specs].count("a0_db"), 1)

    def test_psrr_dc_unqualified_vector_reads_go_to_the_last_analysis(self):
        sts, _ = self._by_state("psrr-dc")
        self.assertEqual(list(sts), ["ac1", "ac2"])
        self.assertEqual(sts["ac2"].names, ["gpsr_1k_vv", "psrr_ldo_1k_tracking_db"])
        self.assertEqual(sts["ac2"].analysis["args"], "lin 1 1k 1k")
        by = {m["name"]: m for m in sts["ac1"].specs}
        self.assertEqual(by["psrr_ldo_1k_db"]["spice"],
                         ".meas ac psrr_ldo_1k_db param='adiff1k_db + (20*log10(abs(2.0/3.0)))'")

    def test_psrr_vs_freq_card_results_follow_their_analysis(self):
        for slug in ("psrr-vs-freq", "psrr-vs-freq-50ma"):
            sts, _ = self._by_state(slug)
            self.assertEqual(sts["op1"].names, ["dc_vout_v", "dc_iload_ma"], slug)
            self.assertEqual(sts["ac1"].names, ["psrr_1k_db", "psrr_100k_db"], slug)

    def test_every_manifest_measure_lands_in_exactly_one_state(self):
        for slug in ("amp-openloop", "psrr-dc", "psrr-vs-freq", "psrr-vs-freq-50ma"):
            tb = _tb(slug)
            sts, _ = ta.states(tb)
            got = sorted(n for s in sts for n in s.names)
            self.assertEqual(got, sorted(tb.measure), slug)
            for s in sts:
                self.assertTrue(set(s.names) <= {m["name"] for m in s.specs}, (slug, s.name))

    def test_an_entry_reading_two_analyses_is_refused(self):
        tb = dataclasses.replace(_tb("amp-openloop"), measure={"bad": "op1.v(a) - ac1.a0_db"})
        with self.assertRaises(ta.UnsupportedTb):
            ta.states(tb)

    def test_a_plot_the_deck_never_runs_is_refused(self):
        tb = dataclasses.replace(_tb("amp-openloop"), measure={"bad": "tran1.v(a)"})
        with self.assertRaises(ta.UnsupportedTb):
            ta.states(tb)


class MultiStateJobs(unittest.TestCase):
    def test_grid_follows_the_manifests_corner_set(self):
        # full = 9 process, mos = 5; x 3 T x 3 supplies
        for slug, n in (("amp-openloop", 81), ("psrr-dc", 81),
                        ("psrr-vs-freq", 45), ("psrr-vs-freq-50ma", 45)):
            tb = _tb(slug)
            js = ta.jobs(tb, "new", tb.design_netlists[0])
            self.assertTrue(js, slug)
            for j in js.values():
                self.assertEqual(_grid(j), n, slug)

    def test_supply_is_the_param_the_fragment_reads(self):
        tb = _tb("amp-openloop")
        req = ta.jobs(tb, "new", tb.design_netlists[0])["ac1"].request()
        self.assertEqual(req["corners"]["params"], {"vdd_val": [2.97, 3.3, 3.63]})
        self.assertNotIn("supply_v", req["corners"])
        self.assertEqual(req["analysis"]["kind"], "ac")
        self.assertIs(req["options"]["stage_model_inputs"], True)
        self.assertEqual(req["options"]["ngspice_init"][0], "set units=degrees")

    def test_only_collapses_every_state_to_one_point(self):
        tb = _tb("psrr-dc")
        for j in ta.jobs(tb, "new", tb.design_netlists[0], "tt,27,3.30").values():
            self.assertEqual(_grid(j), 1)


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
