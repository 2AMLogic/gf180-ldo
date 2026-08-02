#!/usr/bin/env python3
"""Unit tests for the loop-stability sweep driver. No PDK, no ngspice.

    python3 -m unittest discover -s sim/tests -v

These cover the parts of ``sim/loop-stability/testbench/sweep.py`` that decide
whether a number becomes a PASS or a FAIL in an evidence record -- the margin
semantics, the DR-0001 matrix definition, and the deck template's
substitution -- because a bug there would silently mis-state a spec claim.
The simulation itself is validated separately and against a closed-form
answer by ``sim/loop-stability/testbench/selftest.py``.
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

_SWEEP_PATH = SIM_DIR / "loop-stability" / "testbench" / "sweep.py"
_spec = importlib.util.spec_from_file_location("loop_stability_sweep", _SWEEP_PATH)
sweep = importlib.util.module_from_spec(_spec)
# sweep.py is a script under a hyphenated directory, so it is not importable
# by name; register it before exec so its @dataclass can resolve its module.
sys.modules["loop_stability_sweep"] = sweep
_spec.loader.exec_module(sweep)


def row(**kw) -> "sweep.Row":
    base = dict(
        corner_id="tt_27c_3.30v", corner="tt", temp_c=27.0, vin_v=3.3,
        iload_a=1e-3, ceff_f=1e-6, esr_ohm=0.05, vout_v=1.8,
        dcgain_db=90.0, f0_hz=1e5, phase_at_f0_deg=-120.0,
        f180_hz=None, gain_at_f180_db=None, f0_rising_hz=None,
        resurgence_db=None,
    )
    base.update(kw)
    return sweep.Row(**base)


class TestMarginSemantics(unittest.TestCase):
    def test_phase_margin_is_180_plus_phase_at_crossover(self):
        self.assertAlmostEqual(row(phase_at_f0_deg=-120.0).pm_deg, 60.0)
        self.assertAlmostEqual(row(phase_at_f0_deg=-178.0).pm_deg, 2.0)
        self.assertAlmostEqual(row(phase_at_f0_deg=-190.0).pm_deg, -10.0)

    def test_gain_margin_is_negated_gain_at_the_180_crossing(self):
        self.assertAlmostEqual(
            row(f180_hz=2e6, gain_at_f180_db=-25.0).gm_db, 25.0
        )

    def test_no_180_crossing_means_infinite_gain_margin_not_a_failure(self):
        # A loop whose phase approaches -180 deg from above never inverts, so
        # no finite gain multiplier drives T to -1. Reporting this as a
        # missing measurement (and hence a FAIL) would be wrong.
        r = row(f180_hz=None, gain_at_f180_db=None)
        self.assertTrue(math.isinf(r.gm_db))
        self.assertEqual(sweep.gm_str(r), "inf")

    def test_pass_requires_both_dr0001_bars(self):
        self.assertEqual(sweep.PM_MIN_DEG, 45.0)
        self.assertEqual(sweep.GM_MIN_DB, 10.0)
        self.assertTrue(row(phase_at_f0_deg=-134.0).passes)          # PM 46
        self.assertFalse(row(phase_at_f0_deg=-136.0).passes)         # PM 44
        self.assertFalse(
            row(phase_at_f0_deg=-100.0, f180_hz=2e6, gain_at_f180_db=-9.0).passes
        )
        self.assertTrue(
            row(phase_at_f0_deg=-100.0, f180_hz=2e6, gain_at_f180_db=-11.0).passes
        )

    def test_a_point_with_no_crossover_is_never_silently_a_pass(self):
        r = row(f0_hz=None, phase_at_f0_deg=None)
        self.assertIsNone(r.pm_deg)
        self.assertFalse(r.passes)
        self.assertEqual(sweep.pm_str(r), "n/a")

    def test_worst_of_picks_the_lowest_phase_margin(self):
        rows = [
            row(phase_at_f0_deg=-120.0),                  # PM 60
            row(phase_at_f0_deg=-178.0, iload_a=50e-3),   # PM 2
            row(phase_at_f0_deg=-140.0),                  # PM 40
        ]
        self.assertAlmostEqual(sweep.worst_of(rows).pm_deg, 2.0)
        self.assertEqual(sweep.worst_of(rows).iload_a, 50e-3)

    def test_worst_of_prefers_an_unmeasurable_point_over_a_measured_one(self):
        rows = [row(phase_at_f0_deg=-179.0), row(f0_hz=None, phase_at_f0_deg=None)]
        self.assertIsNone(sweep.worst_of(rows).pm_deg)


class TestResurgenceBar(unittest.TestCase):
    """DR-0008's precondition check (issue #59), a bar of its own.

    A phase/gain margin is only a stability test when T(s) has no
    right-half-plane poles. |T| climbing back above 0 dB above its first 0 dB
    crossing is necessary (not sufficient) for that precondition to be broken,
    and it is cheap to read off the sweep this bench already runs.
    """

    def test_the_bar_has_no_slack_in_it(self):
        # For a loop that rolls off monotonically through crossover every
        # point above the crossing is below unity, so anything above 0 dB is
        # a resurgence. There is no engineering margin to allow here.
        self.assertEqual(sweep.RESURGENCE_MAX_DB, 0.0)

    def test_a_positive_resurgence_is_flagged(self):
        self.assertTrue(row(resurgence_db=24.4).resurges)
        self.assertTrue(row(resurgence_db=0.01).resurges)

    def test_a_gain_that_stays_below_unity_is_not_flagged(self):
        self.assertFalse(row(resurgence_db=-4.2).resurges)
        self.assertFalse(row(resurgence_db=0.0).resurges)

    def test_an_unmeasurable_resurgence_is_not_a_resurgence(self):
        # No 0 dB crossing => no region above one. Such a point already fails
        # the phase-margin bar on its own account, so it is not a silent pass.
        r = row(f0_hz=None, phase_at_f0_deg=None, resurgence_db=None)
        self.assertFalse(r.resurges)
        self.assertFalse(r.passes)
        self.assertEqual(sweep.res_str(r), "n/a")

    def test_the_resurgence_bar_is_orthogonal_to_the_dr0001_verdict(self):
        # The whole point of keeping it out of `passes`: a point can clear
        # DR-0001's two bars and still be a point whose margins are not a
        # legitimate reading (DR-0008's finding), and vice versa.
        r = row(phase_at_f0_deg=-100.0, resurgence_db=52.5)
        self.assertTrue(r.passes)
        self.assertTrue(r.resurges)
        r = row(phase_at_f0_deg=-170.0, resurgence_db=-30.0)
        self.assertFalse(r.passes)
        self.assertFalse(r.resurges)

    def test_worst_resurgence_picks_the_largest_and_survives_unmeasured_points(self):
        rows = [row(resurgence_db=-4.0), row(resurgence_db=15.3, iload_a=50e-3),
                row(resurgence_db=None)]
        self.assertAlmostEqual(sweep.worst_resurgence_of(rows).resurgence_db, 15.3)
        self.assertEqual(sweep.worst_resurgence_of(rows).iload_a, 50e-3)
        self.assertIsNone(sweep.worst_resurgence_of([row(resurgence_db=None)])
                          .resurgence_db)


class TestRowParsing(unittest.TestCase):
    """The deck writes key=value, and the driver refuses anything else.

    A failed ``meas`` leaves its value empty. With bare positional fields an
    empty one vanishes into the whitespace and every later field is read as
    the wrong quantity -- which is exactly what happened to 387 rows of
    record 20260801-191742-84f67b8, whose f0_rising_hz was recorded as
    f_180_hz and whose multiple-crossing self-check therefore reported 14
    points instead of 401.
    """

    FULL = ("ROW iload_a=0.0001 ceff_f=3.3e-07 esr_ohm=0.5 vout_v=1.7994 "
            "dcgain_db=147.821 f0_hz=300220 phase_at_f0_deg=-92.307 "
            "f180_hz=811035 gain_at_f180_db=16.7196 f0_rising_hz=622210 "
            "resurgence_db=24.4")

    def test_all_fields_present(self):
        f = sweep.parse_row_fields(self.FULL)
        self.assertEqual(f["f0_hz"], "300220")
        self.assertEqual(f["gain_at_f180_db"], "16.7196")
        self.assertEqual(f["resurgence_db"], "24.4")

    def test_an_empty_middle_field_does_not_shift_the_later_ones(self):
        line = self.FULL.replace("f180_hz=811035", "f180_hz=").replace(
            "gain_at_f180_db=16.7196", "gain_at_f180_db=")
        f = sweep.parse_row_fields(line)
        self.assertEqual(f["f180_hz"], "")
        self.assertEqual(f["gain_at_f180_db"], "")
        # the two fields AFTER the empty ones must still be themselves
        self.assertEqual(f["f0_rising_hz"], "622210")
        self.assertEqual(f["resurgence_db"], "24.4")

    def test_a_missing_field_is_an_error_not_a_default(self):
        line = self.FULL.replace(" resurgence_db=24.4", "")
        with self.assertRaises(ValueError):
            sweep.parse_row_fields(line)

    def test_a_positional_field_is_rejected(self):
        # i.e. an old-format ROW line is refused rather than misread.
        with self.assertRaises(ValueError):
            sweep.parse_row_fields(
                "ROW 0.0001 3.3e-07 0.5 1.7994 147.821 300220 -92.307"
            )

    def test_the_field_list_matches_the_decks_own_echo(self):
        text = (REPO_ROOT / "sim" / "loop-stability" / "testbench"
                / "tb_loop_stability.spice.in").read_text()
        echo = re.search(r'^\s*echo "ROW (.*)"$', text, re.M).group(1)
        keys = [tok.split("=")[0] for tok in echo.split()]
        self.assertEqual(list(sweep.ROW_FIELDS), keys)


class TestRatifiedMatrix(unittest.TestCase):
    """The matrix is a ratified spec artefact, not a tuning knob."""

    def test_matches_dr0001(self):
        self.assertEqual(sweep.ILOADS_A, (0.0, 0.1e-3, 1e-3, 10e-3, 25e-3, 50e-3))
        self.assertEqual(sweep.CEFFS_F, (0.33e-6, 1.0e-6, 4.7e-6))
        self.assertEqual(sweep.ESRS_OHM, (0.001, 0.05, 0.2, 0.5))
        # tt/ff/ss/fs/sf is DR-0001's original MOS-only process axis; issue #54
        # added res_ff/res_ss because #51/#56's Type-II gain-shelf compensation
        # made Rz (a ppolyf_u_1k resistor) a first-order parameter of the
        # result, not a second-order one.
        self.assertEqual(
            sweep.PROCESS_CORNERS,
            ("tt", "ff", "ss", "fs", "sf", "res_ff", "res_ss"),
        )
        self.assertEqual(sweep.TEMPS_C, (-40.0, 27.0, 125.0))

    def test_default_grid_is_the_4536_points_dr0001_plus_issue54_enumerates(self):
        n = (
            len(sweep.PROCESS_CORNERS) * len(sweep.TEMPS_C) * 3  # 3 supply points
            * len(sweep.ILOADS_A) * len(sweep.CEFFS_F) * len(sweep.ESRS_OHM)
        )
        self.assertEqual(n, 4536)

    def test_the_zero_esr_stand_in_is_present(self):
        # DR-0001 makes the "ESR -> 0" point required, not optional: it is
        # where the ESR zero provides no phase help at all.
        self.assertIn(0.001, sweep.ESRS_OHM)

    def test_no_capless_point_is_swept(self):
        # DR-0001 scopes capless out of the primary design; a 0 F entry here
        # would silently make a claim the spec does not authorise.
        self.assertTrue(all(c > 0 for c in sweep.CEFFS_F))
        self.assertGreaterEqual(min(sweep.CEFFS_F), 0.33e-6)


class TestDeckTemplate(unittest.TestCase):
    def test_template_has_no_unsubstituted_placeholders_after_render(self):
        from harness.corners import CORNERS, PvtPoint

        class FakePdk:
            design_include = "/pdk/design.ngspice"
            model_lib = "/pdk/sm141064.ngspice"

        pvt = PvtPoint(corner=CORNERS["ss"], temp_c=-40.0, vdd=2.97)
        deck = sweep.render_deck(
            pvt, FakePdk(), [0.0, 50e-3], [0.33e-6], [0.001, 0.5]
        )
        # Bare '@' survives legitimately (ngspice's `alter @Vinj[acmag]`);
        # what must not survive is an unsubstituted @PLACEHOLDER@.
        self.assertEqual([], sweep.TOKEN_RE.findall(deck))
        self.assertIn(".temp -40", deck)
        self.assertIn('.lib "/pdk/sm141064.ngspice" ss', deck)
        self.assertIn("Vin VIN 0 DC 2.97", deck)
        self.assertIn("foreach il 0 0.05", deck)
        self.assertIn("foreach es 0.001 0.5", deck)

    def test_template_breaks_the_loop_at_the_ports_ldo_core_exposes(self):
        text = (REPO_ROOT / "sim" / "loop-stability" / "testbench"
                / "tb_loop_stability.spice.in").read_text()
        # ldo_core's port order; the last two ports must land on DIFFERENT
        # nodes or there is no loop break at all and every margin is garbage.
        self.assertIn("Xdut VIN VOUT EN 0 AINJ BINJ ldo_core", text)
        self.assertIn("Vinj AINJ BINJ DC 0", text)
        self.assertIn("Iinj 0 BINJ DC 0", text)
        # and the DUT must be the committed export of the schematic
        netlist = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()
        self.assertIn(".subckt ldo_core VIN VOUT EN VSS ERRAMP_OUT PASS_GATE",
                      netlist)

    def test_template_removes_the_non_physical_dc_branch(self):
        # An ideal current-source load leaves VOUT unbounded below, which opens
        # a second (current-limit latch) DC solution the solver lands on at
        # about a third of the PVT points. The clamp denies it its escape.
        text = (REPO_ROOT / "sim" / "loop-stability" / "testbench"
                / "tb_loop_stability.spice.in").read_text()
        self.assertIn("Dclamp 0 VOUT dclamp", text)
        model = re.search(r"^\.model dclamp d\((.*)\)$", text, re.M).group(1)
        # It must be AC-inert: any junction capacitance would load the output
        # node and quietly move the very phase margin this bench reports.
        self.assertIn("cjo=0", model)
        self.assertIn("tt=0", model)

    def test_the_regulation_target_matches_the_designs_own_divider(self):
        # If the divider or the reference moves, the regulation check goes
        # stale silently -- so derive the target from the netlist.
        netlist = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()
        rtop = float(re.search(r"^Rtop VOUT FB (\S+)k", netlist, re.M).group(1))
        rbot = float(re.search(r"^Rbot FB VSS (\S+)k", netlist, re.M).group(1))
        vref = float(re.search(r"^Vref1 VREF VSS (\S+)", netlist, re.M).group(1))
        self.assertAlmostEqual(sweep.VOUT_NOM_V, vref * (rtop + rbot) / rbot,
                               places=6)


class TestRegulatingBranchGuard(unittest.TestCase):
    """A margin is only meaningful about the regulating operating point."""

    def test_the_regulating_point_is_accepted(self):
        self.assertEqual([], sweep.nonregulating([row(vout_v=1.8),
                                                  row(vout_v=1.79945)]))

    def test_the_current_limit_latch_branch_is_rejected(self):
        # The exact shape seen before the deck seeded the regulating branch:
        # VOUT ~ -29 V with a nonsense "DC loop gain" that still parses fine.
        bad = row(vout_v=-29.1482, dcgain_db=-131.5)
        self.assertEqual([bad], sweep.nonregulating([row(vout_v=1.8), bad]))

    def test_an_unparsable_vout_is_rejected_not_trusted(self):
        self.assertEqual(1, len(sweep.nonregulating([row(vout_v=float("nan"))])))

    def test_the_window_is_a_branch_check_not_an_accuracy_check(self):
        # Regulation accuracy is sim/load-regulation's claim, not this one:
        # a few mV of droop must not void a stability run.
        self.assertEqual([], sweep.nonregulating([row(vout_v=1.78),
                                                  row(vout_v=1.82)]))


if __name__ == "__main__":
    unittest.main()
