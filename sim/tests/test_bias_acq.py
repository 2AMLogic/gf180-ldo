#!/usr/bin/env python3
"""Unit tests for the issue-352 bias-acquisition driver. No PDK, no ngspice.

    python3 -m unittest sim.tests.test_bias_acq   # or: discover -s sim/tests

Covers the parts of ``sim/soft-start/testbench/bias_acq.py`` that decide what
a result *means*: the netlist instrumentation (it must fail loudly rather
than silently measure nothing), the solver-path classifier read from the
ngspice log, and the per-window grading -- in particular that an errored
corner, a missing or non-finite value, or an unreachable acquisition can
never grade as ``ACQUIRED``.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
REPO = SIM_DIR.parent
DRIVER = SIM_DIR / "soft-start" / "testbench" / "bias_acq.py"
sys.path.insert(0, str(SIM_DIR))
_spec = importlib.util.spec_from_file_location("ss_bias_acq", DRIVER)
ba = importlib.util.module_from_spec(_spec)
sys.modules["ss_bias_acq"] = ba
_spec.loader.exec_module(ba)

CORE = (REPO / "design" / "netlist" / "ldo_core.spice").read_text()

EDGE, END = 20e-6, 170e-6


def window_vals(k="il", w=1, **over):
    """A healthy acquired window for servo ``k``; override any quantity."""
    v = {
        f"w{w}_vref_end": 1.2,
        f"w{w}_{k}_vx_end": 1.199993, f"w{w}_{k}_bb_end": 1.2e-4,
        f"w{w}_{k}_icv_end": 1.0638e-6, f"w{w}_{k}_irb_end": 1.0638e-6,
        f"w{w}_{k}_ist_end": 2e-12, f"w{w}_{k}_vx_setmax": 1.199995,
        f"w{w}_{k}_vx_setmin": 1.199990, f"w{w}_{k}_vx_winmin": 1e-9,
        f"w{w}_{k}_ist_peak": 2.1e-6, f"w{w}_{k}_t99": 36.4e-6,
    }
    v.update({f"w{w}_{k}_{q}": x for q, x in over.items()})
    return v


class TestInstrument(unittest.TestCase):
    def test_adds_ammeters_to_both_servos_only(self):
        out = ba.instrument(CORE)
        for name in ("Vacq_cv PB PB_ACQCV 0", "Vacq_st PB PB_ACQST 0", "Vacq_rb VX VX_ACQRB 0",
                     "Vacq_cv PB_SS PB_SS_ACQCV 0", "Vacq_rb VX_SS VX_SS_ACQRB 0"):
            self.assertIn(name, out)
        # error_amp has its own XRbias; it must be untouched
        self.assertIn("XRbias NBIAS RBT VSS", out)
        self.assertNotIn("HOLD_ACQ", out)

    def test_hold_and_startup_disable(self):
        out = ba.instrument(CORE, hold=True, startup_disable=True)
        self.assertIn(".global HOLD_ACQ", out)
        self.assertEqual(out.count(" HOLD_ACQ 0 swacq"), 6)
        self.assertRegex(out, r"(?m)^XMst PB_ACQST VSS BB ")
        self.assertRegex(out, r"(?m)^XMst_ss PB_SS_ACQST VSS BB ")

    def test_renamed_device_fails_loudly(self):
        broken = CORE.replace("XMconv PB VG VX", "XMconvX PB VG VX")
        with self.assertRaises(ba.InstrumentError):
            ba.instrument(broken)

    def test_missing_subckt_fails_loudly(self):
        broken = CORE.replace(".subckt ldo_softstart", ".subckt ldo_softstartX")
        with self.assertRaises(ba.InstrumentError):
            ba.instrument(broken)


class TestSolverPath(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(ba.solver_path(None), "missing")
        self.assertEqual(ba.solver_path("Doing analysis\nNo. of Data Rows : 1"), "direct")
        self.assertEqual(ba.solver_path("Note: Starting dynamic gmin stepping\n"
                                        "Note: Dynamic gmin stepping completed"), "dyn_gmin")
        self.assertEqual(ba.solver_path("Warning: Dynamic gmin stepping failed\n"
                                        "Note: True gmin stepping completed"), "true_gmin")
        self.assertEqual(ba.solver_path("Warning: True gmin stepping failed\n"
                                        "Note: Source Stepping completed"), "src_step")
        self.assertEqual(ba.solver_path("gmin stepping failed\nsource stepping failed\n"
                                        "simulation(s) aborted"), "failed")

    def test_tran_trouble(self):
        self.assertEqual(ba.tran_trouble(None), [])
        self.assertEqual(ba.tran_trouble("doAnalyses: TRAN:  Timestep too small"), ["timestep_too_small"])


class TestClassify(unittest.TestCase):
    def test_acquired(self):
        r = ba.classify(window_vals(), 1, "il", EDGE, END, "pass")
        self.assertEqual(r["verdict"], "ACQUIRED")
        self.assertAlmostEqual(r["t_acq_us"], 16.4, places=6)
        self.assertLess(abs(r["ibias_rel"] - 1), 1e-3)

    def test_inactive(self):
        v = window_vals(vx_end=1.3e-7, bb_end=1e-11, icv_end=1e-12, irb_end=1e-13,
                        vx_setmax=1.4e-7, vx_setmin=1.2e-7, vx_winmin=1e-13, t99=168.9e-6)
        r = ba.classify(v, 1, "il", EDGE, END, "pass", negctl=True)
        self.assertEqual(r["verdict"], "INACTIVE")
        self.assertIsNone(r["t_acq_us"])  # guard crossing at the window end is not an acquisition
        self.assertTrue(r["control_detects_inactive"])

    def test_negctl_that_starts_is_reported(self):
        r = ba.classify(window_vals(), 1, "il", EDGE, END, "pass", negctl=True)
        self.assertFalse(r["control_detects_inactive"])

    def test_errored_corner_is_invalid_even_with_values(self):
        r = ba.classify(window_vals(), 1, "il", EDGE, END, "error")
        self.assertEqual(r["verdict"], "INVALID")

    def test_missing_value_is_invalid(self):
        v = window_vals()
        del v["w1_il_ist_end"]
        self.assertEqual(ba.classify(v, 1, "il", EDGE, END, "pass")["verdict"], "INVALID")

    def test_none_and_nonfinite_are_invalid(self):
        for bad in (None, math.nan, math.inf, "1.2", True):
            v = window_vals(vx_end=bad)
            self.assertEqual(ba.classify(v, 1, "il", EDGE, END, "pass")["verdict"], "INVALID", repr(bad))

    def test_unsettled(self):
        v = window_vals(vx_setmin=1.17)  # 30 mV dip inside the settled sub-window
        self.assertEqual(ba.classify(v, 1, "il", EDGE, END, "pass")["verdict"], "UNSETTLED")

    def test_partial_bias_is_unsettled_not_inactive(self):
        v = window_vals(vx_end=0.6, vx_setmax=0.6, vx_setmin=0.59)
        self.assertEqual(ba.classify(v, 1, "il", EDGE, END, "pass")["verdict"], "UNSETTLED")

    def test_startup_still_on(self):
        v = window_vals(ist_end=0.5e-6)
        self.assertEqual(ba.classify(v, 1, "il", EDGE, END, "pass")["verdict"], "STARTUP_ON")

    def test_no_excursion_means_zero_acquisition_time(self):
        v = window_vals(vx_winmin=1.195, t99=168.95e-6)
        r = ba.classify(v, 1, "il", EDGE, END, "pass")
        self.assertEqual(r["t_acq_us"], 0.0)
        self.assertEqual(r["verdict"], "ACQUIRED")

    def test_shutdown_graded_only_after_long_off(self):
        v = window_vals(icv_pre=5e-12, vx_pre=1.19)
        r = ba.classify(v, 1, "il", EDGE, END, "pass", pre="en0")
        self.assertTrue(r["en0_shutdown_ok"])
        v = window_vals(icv_pre=4e-8, vx_pre=1.19)
        self.assertFalse(ba.classify(v, 1, "il", EDGE, END, "pass", pre="en0")["en0_shutdown_ok"])
        r = ba.classify(v, 1, "il", EDGE, END, "pass", pre="en0_short")
        self.assertNotIn("en0_shutdown_ok", r)
        self.assertAlmostEqual(r["en0_icv_na"], 40.0)

    def test_missing_pre_edge_is_invalid(self):
        r = ba.classify(window_vals(), 1, "il", EDGE, END, "pass", pre="en0")
        self.assertEqual(r["verdict"], "INVALID")


class TestClassifyOp(unittest.TestCase):
    def vals(self, **over):
        v = {"vref": 1.2, "il_vx": 1.199993, "il_bb": 1.2e-4, "il_icv": 1.0638e-6, "il_ist": 2.4e-12}
        v.update(over)
        return v

    def test_acquired_and_invalid(self):
        self.assertEqual(ba.classify_op(self.vals(), "il", "pass")["verdict"], "ACQUIRED")
        self.assertEqual(ba.classify_op(self.vals(), "il", "error")["verdict"], "INVALID")
        self.assertEqual(ba.classify_op(self.vals(il_vx=None), "il", "pass")["verdict"], "INVALID")

    def test_inactive_root(self):
        r = ba.classify_op(self.vals(il_vx=1e-7, il_bb=0.0, il_icv=1e-13), "il", "pass")
        self.assertEqual(r["verdict"], "INACTIVE")


class TestScenarioDecks(unittest.TestCase):
    def test_every_tran_window_has_a_guard_and_cards(self):
        for name, s in ba.SCENARIOS.items():
            body = ba.body(name)
            meas = ba.measurements(name)
            self.assertNotIn("expr", {k for m in meas for k in m}, name)  # fleet runner rejects expr
            if s["kind"] != "tran":
                self.assertIn("Vdum", body)
                continue
            for w, (_l, edge, end, _p) in enumerate(s["windows"], 1):
                self.assertLessEqual(end, s["tstop"] + 1e-12)
                for k in ba.SERVOS:
                    self.assertIn(f"Bacq_{k}_w{w} ", body)
                    self.assertIn(f"w{w}_{k}_t99", {m["name"] for m in meas})


class TestHarnessHelpers(unittest.TestCase):
    def test_redact_hides_bucket_keeps_job_identity(self):
        from harness import klt_batch as kb
        rep = {"environment": {"remote": {"bucket": "some-bucket-123", "job_id": "klt-sim-1", "state": "failed"}}}
        out = kb.redact(rep)
        self.assertEqual(out["environment"]["remote"]["bucket"], "<redacted>")
        self.assertEqual(out["environment"]["remote"]["job_id"], "klt-sim-1")
        self.assertEqual(rep["environment"]["remote"]["bucket"], "some-bucket-123")  # input untouched
        self.assertEqual(kb.redact({"corners": []}), {"corners": []})

    def test_klt_cmd_override(self):
        import os
        from unittest import mock
        from harness import klt_batch as kb
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KLT_CMD", None)
            self.assertEqual(kb.klt_cmd(), ["klt"])
        with mock.patch.dict(os.environ, {"KLT_CMD": "uvx --from 'x @ y' klt"}):
            self.assertEqual(kb.klt_cmd(), ["uvx", "--from", "x @ y", "klt"])


if __name__ == "__main__":
    unittest.main()
