#!/usr/bin/env python3
"""Unit tests for the soft-start loop-gain sweep driver. No PDK, no ngspice.

    python3 -m unittest discover -s sim/tests -v

Same contract and same shape as ``test_loop_stability.py``: these cover the
parts of ``sim/soft-start-loop-gain/testbench/`` that decide whether a number
becomes a claim in an evidence record -- the landing rule, the derived
injection current, the netlist transforms, the deck template's substitution,
and the fact that the margin semantics are *imported* from
``sim/loop-stability/`` rather than re-implemented. The simulation itself is
validated against closed-form answers by
``sim/soft-start-loop-gain/testbench/selftest.py``, which delegates that job
to ``sim/loop-stability/testbench/selftest.py``.
"""

from __future__ import annotations

import importlib.util
import math
import re
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))

_TB = SIM_DIR / "soft-start-loop-gain" / "testbench"
sys.path.insert(0, str(_TB))
import netlist_variants as nv  # noqa: E402

_spec = importlib.util.spec_from_file_location("ss_loop_gain_sweep", _TB / "sweep.py")
sweep = importlib.util.module_from_spec(_spec)
sys.modules["ss_loop_gain_sweep"] = sweep
_spec.loader.exec_module(sweep)

CORE = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()


def row(**kw) -> "sweep.Row":
    base = dict(
        corner_id="tt_27c_3.30v", corner="tt", temp_c=27.0, vin_v=3.3,
        iload_a=0.0, ceff_f=1e-6, esr_ohm=0.1, vout_v=0.9, dcgain_db=100.0,
        f0_hz=1e5, phase_at_f0_deg=-120.0, f180_hz=None, gain_at_f180_db=None,
        f0_rising_hz=None, resurgence_db=None, variant="device", phase="ramp",
        ssr_cmd="0.6", ssr_v=0.6, fb_v=1.2, isup_a=1e-3,
        load_model="resistive-36ohm", rload_ohm=36.0,
    )
    base.update(kw)
    return sweep.Row(**base)


class TestMarginSemanticsAreNotForked(unittest.TestCase):
    """The whole comparability claim of this experiment rests on this."""

    def test_the_bars_are_loop_stabilitys_own_objects(self):
        self.assertIs(sweep.PM_MIN_DEG, sweep.ls.PM_MIN_DEG)
        self.assertIs(sweep.GM_MIN_DB, sweep.ls.GM_MIN_DB)
        self.assertIs(sweep.RESURGENCE_MAX_DB, sweep.ls.RESURGENCE_MAX_DB)

    def test_the_ac_band_and_resolution_are_loop_stabilitys_own(self):
        self.assertIs(sweep.AC_DEC, sweep.ls.AC_DEC)
        self.assertIs(sweep.F_START, sweep.ls.F_START)
        self.assertIs(sweep.F_STOP, sweep.ls.F_STOP)
        self.assertEqual(sweep.AC_DEC, "400")

    def test_row_inherits_rather_than_restates_the_margin_definitions(self):
        self.assertTrue(issubclass(sweep.Row, sweep.ls.Row))
        for name in ("pm_deg", "gm_db", "passes", "resurges"):
            self.assertIs(getattr(sweep.Row, name), getattr(sweep.ls.Row, name),
                          f"{name} is redefined here instead of inherited")

    def test_the_pvt_grid_is_loop_stabilitys_own(self):
        self.assertIs(sweep.PROCESS_CORNERS, sweep.ls.PROCESS_CORNERS)
        self.assertIs(sweep.TEMPS_C, sweep.ls.TEMPS_C)
        self.assertEqual(sweep.SUPPLY_TOL, 0.10)


class TestLandingRule(unittest.TestCase):
    """A margin about the wrong DC branch is noise dressed up as a number."""

    def test_a_mid_ramp_point_with_fb_at_the_reference_is_accepted(self):
        self.assertEqual(row(vout_v=0.9, fb_v=1.2).landed, "")

    def test_vout_alone_cannot_discriminate_at_the_bottom_of_the_ramp(self):
        # Same VOUT; only FB says which branch this is.
        self.assertEqual(row(ssr_cmd="0", ssr_v=0.0, vout_v=2e-4, fb_v=1.2).landed, "")
        self.assertNotEqual(
            row(ssr_cmd="0", ssr_v=0.0, vout_v=2e-4, fb_v=1.3e-4).landed, "")

    def test_the_unbounded_vout_branch_is_refused(self):
        self.assertNotEqual(row(vout_v=-29.0).landed, "")

    def test_a_runaway_output_is_refused(self):
        self.assertNotEqual(row(vout_v=3.0, fb_v=2.0).landed, "")

    def test_an_unparsable_operating_point_is_refused_not_trusted(self):
        self.assertNotEqual(row(vout_v=float("nan")).landed, "")
        self.assertNotEqual(row(fb_v=float("nan")).landed, "")

    def test_the_anchor_phase_also_holds_loop_stabilitys_settled_rule(self):
        self.assertEqual(row(phase="ramp", vout_v=1.5, fb_v=1.2).landed, "")
        self.assertNotEqual(
            row(phase="anchor", ssr_cmd="free", vout_v=1.5, fb_v=1.2).landed, "")
        self.assertEqual(
            row(phase="anchor", ssr_cmd="free", vout_v=1.799, fb_v=1.2).landed, "")

    def test_the_fb_window_is_a_branch_check_not_an_accuracy_check(self):
        # 10 mV of feedback error is an accuracy question for other benches.
        self.assertEqual(row(fb_v=1.21).landed, "")


class TestDerivedInjectionCurrent(unittest.TestCase):
    def test_it_is_kcl_at_the_feedback_node(self):
        r = row(vout_v=0.9, fb_v=1.2)
        self.assertAlmostEqual(r.iinj_a, 1.2 / 600e3 + 0.3 / 300e3, places=15)

    def test_it_is_zero_when_the_divider_alone_balances(self):
        # VOUT = 1.5*FB is the no-injection condition of a 300k/600k divider.
        self.assertAlmostEqual(row(vout_v=1.8, fb_v=1.2).iinj_a, 0.0, places=15)

    def test_it_matches_the_designs_own_divider_values(self):
        self.assertIn("Rtop VOUT FB 300k", CORE)
        self.assertIn("Rbot FB VSS 600k", CORE)


class TestNetlistTransforms(unittest.TestCase):
    def test_ssr_promotion_adds_one_port_to_two_subckts_and_one_instance(self):
        out = nv.instrument_core(CORE)
        self.assertIn(nv.CORE_PORTS + " SSR", out)
        self.assertIn(nv.SS_PORTS + " SSR", out)
        self.assertIn(nv.SS_INSTANCE.replace(" ldo_softstart",
                                             " SSR ldo_softstart"), out)
        # ... and changes nothing else.
        self.assertEqual(len(out.splitlines()), len(CORE.splitlines()))

    def test_ssr_promotion_is_refused_if_the_port_list_is_not_what_it_expects(self):
        with self.assertRaises(nv.TransformError):
            nv.instrument_core(CORE.replace(nv.CORE_PORTS, ".subckt ldo_core A B"))

    def test_a_missing_softstart_block_is_an_error_not_a_silent_passthrough(self):
        with self.assertRaises(nv.TransformError):
            nv.instrument_core(nv.SS_BLOCK_RE.sub("", CORE))

    def test_ac_open_moves_one_terminal_and_adds_one_inductor(self):
        base = nv.instrument_core(CORE)
        out = nv.ac_open(base, "XMgmo_ss", "FB", "t")
        self.assertIn("Lt FB_t FB " + nv.AC_OPEN_H, out)
        self.assertRegex(out, r"(?m)^XMgmo_ss FB_t GMSUM VIN VIN ")
        self.assertEqual(len(out.splitlines()), len(base.splitlines()) + 1)

    def test_ac_open_puts_the_inductor_after_the_continuation_lines(self):
        # Inserting it between an instance and its `+` continuation truncates
        # the instance's parameter list. This was a real bug.
        base = nv.instrument_core(CORE)
        out = nv.ac_open(base, "XMgmo_ss", "FB", "t").splitlines()
        i = next(k for k, ln in enumerate(out) if ln.startswith("Lt "))
        self.assertFalse(out[i + 1].startswith("+"))
        self.assertTrue(out[i - 1].startswith("+"))

    def test_ac_open_refuses_an_ambiguous_terminal(self):
        base = nv.instrument_core(CORE)
        with self.assertRaises(nv.TransformError):
            nv.ac_open(base, "XMgmo_ss", "VIN", "t")   # VIN appears twice

    def test_ac_open_refuses_an_absent_instance(self):
        with self.assertRaises(nv.TransformError):
            nv.ac_open(nv.instrument_core(CORE), "XNope", "FB", "t")

    def test_ac_short_adds_one_capacitor_inside_the_softstart_subckt(self):
        base = nv.instrument_core(CORE)
        out = nv.ac_short(base, "GMSUM", "VIN", "t")
        self.assertIn("Ct GMSUM VIN " + nv.AC_SHORT_F, out)
        self.assertEqual(len(out.splitlines()), len(base.splitlines()) + 1)
        block = nv.SS_BLOCK_RE.search(out).group(0)
        self.assertIn("Ct GMSUM VIN", block)

    def test_the_attribution_transforms_all_apply_to_the_real_netlist(self):
        base = nv.instrument_core(CORE)
        for tag, _desc, fn in sweep.ATTRIBUTIONS:
            with self.subTest(tag=tag):
                fn(base)   # must not raise


class TestDeckTemplate(unittest.TestCase):
    TEXT = (_TB / "tb_ss_loop_gain.spice.in").read_text()

    def test_the_template_breaks_the_loop_at_the_ports_ldo_core_exposes(self):
        self.assertIn("Xdut VIN VOUT EN 0 AINJ BINJ VREF SSRPIN ldo_core",
                      self.TEXT)
        self.assertIn("Vinj AINJ BINJ DC 0 AC 0", self.TEXT)
        self.assertIn("Iinj 0 BINJ DC 0 AC 0", self.TEXT)

    def test_the_template_uses_the_same_tian_arithmetic_as_loop_stability(self):
        ls_text = (SIM_DIR / "loop-stability" / "testbench"
                   / "tb_loop_stability.spice.in").read_text()
        for idiom in (
            "let tv = -v(ainj)/v(binj)",
            "let ti = -i(vinj)/(i(vinj)+1)",
            "let t = (tvv*ti - 1)/(tvv + ti + 2)",
            "let tdb = db(t)",
            "let tph = 180*cph(t)/pi",
            "meas ac f0 when tdb=0 fall=1",
            "meas ac phx find tph when tdb=0 fall=1",
            "meas ac f180 when tph=-180 fall=1",
            "meas ac gmx find tdb when tph=-180 fall=1",
            "let fres = f0*1.05",
        ):
            with self.subTest(idiom=idiom):
                self.assertIn(idiom, ls_text)
                self.assertIn(idiom, self.TEXT)

    def test_the_template_pins_the_model_binning_flag(self):
        # Without it the W=2000u pass device has no model bin on an ngspice
        # that is not in HSPICE compatibility mode, and no deck in this repo
        # parses. Recorded in the record's Environment section too.
        self.assertIn(".options wnflag=1", self.TEXT)

    def test_every_placeholder_is_substituted_by_the_driver(self):
        tokens = set(sweep.TOKEN_RE.findall(self.TEXT))
        # Mirror render_deck()'s substitution dict without running ngspice.
        provided = {
            "DESIGN_INCLUDE", "MODEL_LIB", "LDO_NETLIST", "MOS_CORNER",
            "RES_CORNER", "BJT_CORNER", "DIODE_CORNER", "MOSCAP_CORNER",
            "MIMCAP_CORNER", "TEMP_C", "VIN_V", "CORNER_ID", "CORNER_NAME",
            "AC_DEC", "F_START", "F_STOP", "CEFF_LIST", "ESR_LIST", "ILOAD",
            "RLOAD", "PHASE", "VARIANT", "SSR_SOURCE", "SSR_ALTER", "SSR_LIST",
            "DC_SEED",
        }
        self.assertEqual(tokens - provided, set())

    def test_the_row_field_list_matches_the_decks_own_echo(self):
        m = re.search(r'echo "ROW ([^"]+)"', self.TEXT)
        self.assertIsNotNone(m)
        keys = [tok.split("=")[0] for tok in m.group(1).split()]
        self.assertEqual(keys, list(sweep.ROW_FIELDS))


class TestRowParsing(unittest.TestCase):
    GOOD = ("ROW ssr_cmd=0.6 ssr_v=0.6 fb_v=1.2 vout_v=0.9 isup_a=1e-3 "
            "ceff_f=1e-06 esr_ohm=0.1 dcgain_db=100 f0_hz=1e5 "
            "phase_at_f0_deg=-120 f180_hz= gain_at_f180_db= f0_rising_hz= "
            "resurgence_db=-0.5")

    def test_all_fields_present(self):
        f = sweep.parse_row_fields(self.GOOD)
        self.assertEqual(f["vout_v"], "0.9")
        self.assertEqual(f["f180_hz"], "")

    def test_a_missing_field_is_an_error_not_a_default(self):
        with self.assertRaises(ValueError):
            sweep.parse_row_fields(self.GOOD.replace(" fb_v=1.2", ""))

    def test_a_positional_field_is_rejected(self):
        with self.assertRaises(ValueError):
            sweep.parse_row_fields(self.GOOD + " 1.234")

    def test_an_unknown_field_is_rejected(self):
        with self.assertRaises(ValueError):
            sweep.parse_row_fields(self.GOOD + " surprise=1")


class TestOperatingPoints(unittest.TestCase):
    def test_the_three_points_issue_196_names_are_all_run(self):
        ramp = sweep.PHASES["ramp"]["ssr"]
        self.assertIn(0.0, ramp)               # (a) ramp start
        self.assertIn(1.15, ramp)              # (b) VREF - 50 mV
        self.assertIn(1.25, ramp)              # (c) VREF + 50 mV
        self.assertAlmostEqual(sweep.VREF_V - 0.05, 1.15)
        self.assertAlmostEqual(sweep.VREF_V + 0.05, 1.25)

    def test_the_anchor_phase_leaves_ssr_unpinned(self):
        self.assertIsNone(sweep.PHASES["anchor"]["ssr"])

    def test_the_sink_phases_use_loop_stabilitys_own_load_model(self):
        for phase in ("sink", "anchor"):
            self.assertEqual(sweep.PHASES[phase]["iload_a"], 0.05)
            self.assertGreater(sweep.PHASES[phase]["rload_ohm"], 1e9)

    def test_the_ramp_phase_uses_a_resistive_load(self):
        self.assertEqual(sweep.PHASES["ramp"]["iload_a"], 0.0)
        self.assertAlmostEqual(sweep.PHASES["ramp"]["rload_ohm"], 36.0)
        # 36 ohm is 1.8 V / 50 mA, i.e. the rated load, not a round number.
        self.assertAlmostEqual(sweep.VOUT_NOM_V / 36.0, 0.05, places=3)

    def test_the_output_network_covers_soft_starts_own_points(self):
        # 1 uF / 100 mOhm main matrix, plus its two 4.7 uF groups.
        self.assertIn(1.0e-6, sweep.CEFFS_F)
        self.assertIn(4.7e-6, sweep.CEFFS_F)
        for esr in (0.1, 0.001, 0.5):
            self.assertIn(esr, sweep.ESRS_OHM)

    def test_all_but_one_config_is_also_a_loop_stability_grid_point(self):
        shared = [(c, e) for c in sweep.CEFFS_F for e in sweep.ESRS_OHM
                  if c in sweep.ls.CEFFS_F and e in sweep.ls.ESRS_OHM]
        total = len(sweep.CEFFS_F) * len(sweep.ESRS_OHM)
        self.assertEqual(len(shared), total - len(sweep.CEFFS_F))  # the 0.1 col


class TestDcSeed(unittest.TestCase):
    def test_the_seed_targets_the_ramp_state_not_the_settled_one(self):
        class P:
            vdd = 3.3
        self.assertIn("v(VOUT)=0.9", sweep.dc_seed_lines(P(), "0.6"))
        self.assertIn("v(VOUT)=1.8", sweep.dc_seed_lines(P(), "free"))
        self.assertIn("v(XDUT.FB)=1.2", sweep.dc_seed_lines(P(), "0.6"))

    def test_the_seed_does_not_reference_the_node_issue_189_deleted(self):
        class P:
            vdd = 3.3
        self.assertNotIn("Xsoftstart.CLG", sweep.dc_seed_lines(P(), "0.6"))
        self.assertNotIn("CLG", nv.SS_BLOCK_RE.search(CORE).group(0))


class TestCrossCheckTolerance(unittest.TestCase):
    def test_it_is_the_movement_class_issues_182_185_established(self):
        self.assertEqual(sweep.XCHECK_PM_TOL_DEG, 2.0)
        self.assertEqual(sweep.XCHECK_GM_TOL_DB, 1.0)

    def test_the_committed_loop_stability_matrix_it_compares_against_exists(self):
        self.assertTrue(sweep.LS_MATRIX_CSV.exists(), sweep.LS_MATRIX_CSV)

    def test_a_delta_inside_the_budget_agrees_and_outside_it_does_not(self):
        def d(pm):
            return (None, {"pm_deg": 0.0}, pm, 0.0, 0.0)
        self.assertTrue(sweep.xcheck_verdict([d(1.9)])[0])
        self.assertFalse(sweep.xcheck_verdict([d(2.1)])[0])
        self.assertFalse(sweep.xcheck_verdict([])[0])


class TestPoleZeroFit(unittest.TestCase):
    """The attribution's arithmetic, against a known answer."""

    @staticmethod
    def synth(fz: float, fp: float, k_db: float = 0.0):
        num, den = [], []
        for i in range(0, 900):
            f = 10 ** (-2 + i / 100.0)
            h = complex(1, f / fz) / complex(1, f / fp)
            m = k_db + 20 * math.log10(abs(h))
            ph = math.degrees(math.atan2(h.imag, h.real))
            num.append((f, m, ph))
            den.append((f, 0.0, 0.0))
        return num, den

    def test_it_recovers_a_known_pole_and_zero(self):
        num, den = self.synth(2e5, 5e4, k_db=0.0)
        k_db, fz, fp, resid = sweep.fit_pole_zero(num, den)
        self.assertLess(abs(math.log10(fz / 2e5)), 0.06)
        self.assertLess(abs(math.log10(fp / 5e4)), 0.06)
        self.assertLess(resid, 0.5)

    def test_curve_extremes_finds_the_largest_deviation(self):
        num, den = self.synth(2e5, 5e4)
        dm, f_dm, dp, f_dp = sweep.curve_extremes(num, den)
        # H = (1+jf/fz)/(1+jf/fp) tends to fp/fz = 0.25 at high frequency,
        # i.e. -12.04 dB; the extremum is signed, and the check is on its size.
        self.assertLess(abs(abs(dm) - 20 * math.log10(2e5 / 5e4)), 0.5)
        self.assertGreater(f_dm, 1e6)
        self.assertGreater(abs(dp), 5.0)

    def test_mismatched_axes_are_refused_not_interpolated(self):
        num, den = self.synth(2e5, 5e4)
        self.assertIsNone(sweep.curve_extremes(num, den[:-1]))
        self.assertIsNone(sweep.fit_pole_zero(num, den[:-1]))


class TestRecordIsAppendOnly(unittest.TestCase):
    def test_the_sweep_writes_through_the_guarded_helper(self):
        src = (_TB / "sweep.py").read_text()
        self.assertIn("write_markdown_record(record_id, md, records_dir)", src)
        self.assertNotIn(".write_text(md)", src)


if __name__ == "__main__":
    unittest.main()
