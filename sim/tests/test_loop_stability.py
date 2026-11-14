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

import contextlib
import importlib.util
import io
import math
import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))

from harness import report  # noqa: E402
from harness.deck import TOKEN_RE  # noqa: E402
from harness.pdk import Pdk  # noqa: E402

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

    def test_every_rejection_still_names_the_ROW_line(self):
        """`harness.report.parse_row_fields()` takes a `tag` naming the line
        kind (the soft-start deck's hand-over lines are `HOV`). This deck does
        not pass one, so every message it raises must still *begin* with
        `ROW`. Assert on the prefix, not containment: every message ends with
        the echoed line, which itself starts with `ROW`, so `assertIn` would
        hold for any tag at all and could not catch the default being
        changed or dropped."""
        for bad in ("ROW 0.0001 3.3e-07 0.5",                    # positional
                    self.FULL.replace(" resurgence_db=24.4", ""),  # missing
                    self.FULL + " nonsense=1",                   # unknown
                    self.FULL + " f0_hz=1"):                     # repeated
            with self.subTest(line=bad):
                with self.assertRaises(ValueError) as cm:
                    sweep.parse_row_fields(bad)
                msg = str(cm.exception)
                self.assertTrue(msg.startswith("ROW "), msg)

    def test_a_zero_vout_or_dcgain_is_kept_not_turned_into_nan(self):
        # `_f(tok) or nan` treated a legitimate 0.0 as missing.
        line = self.FULL.replace("vout_v=1.7994", "vout_v=0").replace(
            "dcgain_db=147.821", "dcgain_db=0.0")
        kw = sweep.base_row_kwargs(sweep.parse_row_fields(line))
        self.assertEqual(kw["vout_v"], 0.0)
        self.assertEqual(kw["dcgain_db"], 0.0)

    def test_an_unparsable_vout_or_dcgain_is_nan(self):
        line = self.FULL.replace("vout_v=1.7994", "vout_v=").replace(
            "dcgain_db=147.821", "dcgain_db=")
        kw = sweep.base_row_kwargs(sweep.parse_row_fields(line))
        self.assertTrue(math.isnan(kw["vout_v"]))
        self.assertTrue(math.isnan(kw["dcgain_db"]))

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
            pvt, FakePdk(), [0.0, 50e-3], [0.33e-6], [0.001, 0.5],
            int(sweep.AC_DEC),
        )
        # Bare '@' survives legitimately (ngspice's `alter @Vinj[acmag]`);
        # what must not survive is an unsubstituted @PLACEHOLDER@.
        self.assertEqual([], TOKEN_RE.findall(deck))
        self.assertIn(".temp -40", deck)
        self.assertIn('.lib "/pdk/sm141064.ngspice" ss', deck)
        self.assertIn("Vin VIN 0 DC 2.97", deck)
        self.assertIn("foreach il 0 0.05", deck)
        self.assertIn("foreach es 0.001 0.5", deck)
        # The AC resolution is threaded through, not hard-coded in the deck:
        # issue #58 made it a parameter of the measurement. The resurgence
        # scan's start offset is deliberately NOT a function of AC_DEC
        # (issue #69, so resurgence_db stays comparable across records taken
        # at different resolutions) -- a fixed fraction of f0 instead.
        self.assertIn(f"ac dec {sweep.AC_DEC} 0.01 1e9", deck)
        self.assertIn("let fres = f0*1.05", deck)

    def test_ac_resolution_resolves_the_q_the_policy_claims(self):
        """`AC_DEC` must deliver the bound issue #58's policy states.

        The worst case for sampling a resonance of quality factor Q on a log
        grid is the peak landing midway between two samples, a relative
        detuning of d = 10^(1/(2*dec)) - 1, which reads
        20*log10(sqrt((2*Q*d)^2 + 1)) dB low. The policy is "worst-case miss
        under 1 dB out to Q ~ 88" -- a tenth of DR-0001's 10 dB gain-margin
        bar. This test is the arithmetic half of that claim; selftest.py's
        third reference loop is the measured half.
        """
        import math

        dec = int(sweep.AC_DEC)
        d = 10 ** (1 / (2 * dec)) - 1
        miss = lambda q: 20 * math.log10(math.sqrt((2 * q * d) ** 2 + 1))  # noqa: E731
        self.assertLess(miss(88.0), 1.0)
        # ... and the resolution the repository ran before #58 did not.
        d50 = 10 ** (1 / 100.0) - 1
        self.assertGreater(20 * math.log10(math.sqrt((2 * 88.0 * d50) ** 2 + 1)),
                           1.0)

    def test_template_breaks_the_loop_at_the_ports_ldo_core_exposes(self):
        text = (REPO_ROOT / "sim" / "loop-stability" / "testbench"
                / "tb_loop_stability.spice.in").read_text()
        # ldo_core's port order; the last two ports must land on DIFFERENT
        # nodes or there is no loop break at all and every margin is garbage.
        self.assertIn("Xdut VIN VOUT EN 0 AINJ BINJ VREF ldo_core", text)
        self.assertIn("Vinj AINJ BINJ DC 0", text)
        self.assertIn("Iinj 0 BINJ DC 0", text)
        # and the DUT must be the committed export of the schematic
        netlist = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()
        self.assertIn(
            ".subckt ldo_core VIN VOUT EN VSS ERRAMP_OUT PASS_GATE VREF",
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
        # stale silently -- so derive the target from the netlist and the
        # deck. Since issue #174 / DR-0021 the reference is no longer inside
        # ldo_core (it was `Vref1 VREF VSS 1.2` there); VREF is a top-level
        # port and this deck drives it, so the reference half of the target
        # is now derived from the deck that actually supplies it.
        netlist = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()
        rtop = float(re.search(r"^Rtop VOUT FB (\S+)k", netlist, re.M).group(1))
        rbot = float(re.search(r"^Rbot FB VSS (\S+)k", netlist, re.M).group(1))
        self.assertNotIn("Vref1", netlist,
                         "ldo_core must not generate its own reference")
        deck = (REPO_ROOT / "sim" / "loop-stability" / "testbench"
                / "tb_loop_stability.spice.in").read_text()
        vref = float(re.search(r"^Vref VREF 0 DC (\S+)", deck, re.M).group(1))
        self.assertAlmostEqual(sweep.VOUT_NOM_V, vref * (rtop + rbot) / rbot,
                               places=6)


class TestDcSeed(unittest.TestCase):
    """Issue #307: the retry seed must name only nodes the netlist has."""

    class P:
        vdd = 2.97

    CORE = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()

    def _block(self, name):
        m = re.search(rf"(?ims)^\.subckt\s+{name}\b.*?^\.ends", self.CORE)
        self.assertIsNotNone(m, name)
        return m.group(0)

    def test_the_seed_does_not_reference_the_node_issue_189_deleted(self):
        seed = sweep.dc_seed_lines(self.P())
        self.assertNotIn("Xsoftstart.CLG", seed)
        self.assertNotIn("CLG", self._block("ldo_softstart"))

    def test_the_seed_does_not_seed_softstart_at_all(self):
        # HG is tied to the fixed EN source through a resistor at DC, so it
        # has only one DC value; see dc_seed_lines()'s docstring.
        self.assertNotIn("Xsoftstart", sweep.dc_seed_lines(self.P()))

    def test_the_ilimit_clamp_gate_is_still_seeded_and_still_exists(self):
        seed = sweep.dc_seed_lines(self.P())
        self.assertIn("v(XDUT.Xilimit.CLG)=2.97", seed)
        self.assertIn("CLG", self._block("ldo_ilimit"))

    def test_the_output_targets_are_seeded(self):
        seed = sweep.dc_seed_lines(self.P())
        self.assertIn("v(VOUT)=1.8", seed)
        self.assertIn("v(XDUT.FB)=1.2", seed)


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


class TestRecordWriteIsAppendOnly(unittest.TestCase):
    """CLAUDE.md: ``sim/`` results are append-only evidence.

    sweep.py mints its record-id before a ~63-point ngspice sweep and only
    spends it at the end, so ``allocate_record_id()``'s at-allocation-time
    check is not enough: two runs racing on the same commit would both see
    the id as free. The write itself has to refuse a collision.
    """

    def test_the_sweep_writes_through_the_guarded_helper(self):
        self.assertIs(sweep.write_markdown_record, report.write_markdown_record)

    def test_a_second_write_of_the_same_record_id_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = Path(tmp) / "records"
            path = sweep.write_markdown_record(
                "20260729-153000-abc1234", "# first\n", records
            )
            self.assertEqual(path, records / "20260729-153000-abc1234.md")
            self.assertEqual("# first\n", path.read_text())
            with self.assertRaises(report.RecordExists):
                sweep.write_markdown_record(
                    "20260729-153000-abc1234", "# second\n", records
                )
            # the first run's evidence survived intact
            self.assertEqual("# first\n", path.read_text())



class TestKltRequestShape(unittest.TestCase):
    """The ``klt sim`` request the batch grid submits (issue #615).

    Two defects made a batch grid unable to produce a record that claims the
    PDK pin, and these are the offline guards against their return:

    * the request did not set ``options.stage_model_inputs``, so a fleet worker
      simulated whatever open_pdks revision its image carried;
    * it submitted all 63 PVT units as one job, which klt rates above the
      fleet's 3600 s whole-job ceiling -- and a job that reaches that ceiling
      reports EVERY unit of itself ``batch_job_timeout``.

    Everything here builds request dictionaries. No simulator, no ``klt``
    client, no network, no PDK install.
    """

    #: One (I_load, C_eff, ESR) configuration; the request shape does not
    #: depend on which, so any point of the DR-0001 matrix will do.
    CFG = (1e-3, 1.0e-6, 0.05)

    def _request(self, axes: dict, dc_seed: str = "") -> dict:
        """The request ``klt_run.py`` would submit for one configuration."""
        return sweep.klt_run.job(
            "test", self.CFG, sweep.LDO_NETLIST, int(sweep.AC_DEC),
            sweep.F_START, sweep.F_STOP, axes, dc_seed=dc_seed,
        ).request()

    def _grid_axes(self) -> dict:
        """The axes ``run_grid_klt`` builds for the full ratified matrix."""
        corners = sweep.resolve_corners(list(sweep.PROCESS_CORNERS))
        supplies = sweep.supply_points(sweep.NOMINAL_SUPPLY_V, sweep.SUPPLY_TOL)
        grid = sweep.build_grid(corners, list(sweep.TEMPS_C), list(supplies))
        return sweep.klt_axes((c.name for c in corners), sweep.TEMPS_C,
                              sorted({p.vdd for p in grid}))

    @staticmethod
    def _units(req: dict) -> int:
        """The unit count klt derives from the request's own corner axes."""
        corners = req["corners"]
        supplies = corners["params"][sweep.klt_run.SUPPLY_PARAM]
        return len(corners["process"]) * len(supplies) * len(corners["temperature_c"])

    def test_the_grid_request_stages_the_submitters_model_files(self):
        req = self._request(self._grid_axes())
        self.assertIs(req["options"]["stage_model_inputs"], True)

    def test_the_grid_request_is_the_63_unit_ratified_matrix(self):
        # The split below is sized against this count, so a change to the
        # matrix must be read together with KLT_MAX_UNITS_PER_JOB.
        self.assertEqual(63, self._units(self._request(self._grid_axes())))

    def test_the_grid_request_is_split_into_jobs_the_fleet_can_finish(self):
        batch = self._request(self._grid_axes())["batch"]
        self.assertEqual(sweep.KLT_MAX_UNITS_PER_JOB, batch["max_units_per_job"])
        # Once a request is split, these two stop being optional: shards the
        # fleet's instance cap refuses come back `lost_shard` and are not
        # retried, and `capacity_wait_s` is the request-level form of the
        # `--wait-for-capacity 600` the dispatch hosts require.
        self.assertEqual(sweep.KLT_MAX_CONCURRENT_JOBS, batch["max_concurrent_jobs"])
        self.assertEqual(sweep.KLT_CAPACITY_WAIT_S, batch["capacity_wait_s"])

    def test_the_split_keeps_every_job_under_the_whole_job_ceiling(self):
        """klt's own bound, read off the request rather than restated as literals.

        ``timeout_s`` is set by ``klt_run.job()``, not by ``sweep.py``, so a
        bump there raises the per-job bound with nothing in ``sweep.py``
        changing. And klt *honors* an explicit cap whose bound exceeds the
        ceiling (klayout-tools#4982: the bound is a serial upper bound, so it
        only warns) -- the fleet then kills the job for real and reports every
        unit of it ``batch_job_timeout``. Nothing else fails loudly, so this is
        the assertion that has to, and it reads both sides from the built
        request to do it.
        """
        req = self._request(self._grid_axes())
        timeout_s = req["options"]["timeout_s"]
        units = req["batch"]["max_units_per_job"]
        bound = timeout_s * units + sweep.KLT_JOB_OVERHEAD_S
        self.assertLessEqual(
            bound, sweep.KLT_JOB_CEILING_S,
            f"a fleet job of {units} units at timeout_s={timeout_s} is bounded at "
            f"{bound}s, past the {sweep.KLT_JOB_CEILING_S}s whole-job ceiling: the fleet "
            f"would kill such a job and report EVERY unit of it batch_job_timeout, the "
            f"finished ones included. Lower KLT_MAX_UNITS_PER_JOB to "
            f"{(sweep.KLT_JOB_CEILING_S - sweep.KLT_JOB_OVERHEAD_S) // timeout_s}, or "
            f"lower timeout_s in klt_run.job()",
        )

    def test_the_cap_is_the_largest_klts_own_auto_sizing_would_pick(self):
        """N is derived, not chosen: it is `job_ceiling_check: "split"`'s formula.

        Asserted as `==` rather than `<=` so that lowering `timeout_s` without
        revisiting the cap shows up as a test to update (the grid would then be
        split into more, smaller jobs than it needs -- 1512 fleet jobs is
        already the capacity problem issue #465 is parked on).
        """
        req = self._request(self._grid_axes())
        largest = ((sweep.KLT_JOB_CEILING_S - sweep.KLT_JOB_OVERHEAD_S)
                   // req["options"]["timeout_s"])
        self.assertEqual(largest, req["batch"]["max_units_per_job"])

    def test_the_dc_seed_retry_request_stages_its_models_too(self):
        """The retry mints rows for the same record, so it must claim the same pin."""
        one = self._request(sweep.klt_axes(("tt",), (27.0,), (3.3,), split=False),
                            dc_seed="* seed\n")
        self.assertIs(one["options"]["stage_model_inputs"], True)

    def test_the_single_point_retry_request_has_nothing_to_split(self):
        one = self._request(sweep.klt_axes(("tt",), (27.0,), (3.3,), split=False))
        self.assertEqual(1, self._units(one))
        # One unit is one job: a unit cap and a concurrency bound would both be
        # noise, but a capacity refusal can still happen to any submit.
        self.assertEqual({"capacity_wait_s": sweep.KLT_CAPACITY_WAIT_S}, one["batch"])


class TestKltClientPdkPin(unittest.TestCase):
    """``stage_model_inputs`` alone cannot make a record claim the pin (issue #615).

    ``klt`` resolves *which* local install to stage from itself, first-match-wins
    across the install prefixes, and merely warns when several provide the
    variant. On a host carrying both the pinned tree and a stale one, the models
    shipped with the job are then chosen by sort order. ``$PDK_ROOT`` is the only
    client-side pin the ``batch`` backend accepts, so the sweep must set it from
    the install ``find_pdk()`` already pin-checked.
    """

    PINNED = Pdk(path=Path("/pinned/root/gf180mcuD"), variant="gf180mcuD",
                 source="search_root:/pinned/root")

    def test_the_client_is_pinned_to_the_pin_checked_installs_parent(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PDK_ROOT", None)
            self.assertEqual("/pinned/root", sweep.pin_klt_pdk_root(self.PINNED))
            self.assertEqual("/pinned/root", os.environ["PDK_ROOT"])

    def test_an_ambient_pdk_root_naming_another_tree_does_not_survive(self):
        """The ambient value is not the pin-checked one -- `find_pdk()` resolves
        `$GF180_PDK_PATH` ahead of `$PDK_ROOT`, so the two can name different
        trees and only the returned `Pdk` has been through `check_pin()`."""
        with unittest.mock.patch.dict(os.environ, {"PDK_ROOT": "/stale/root"}):
            self.assertEqual("/pinned/root", sweep.pin_klt_pdk_root(self.PINNED))
            self.assertEqual("/pinned/root", os.environ["PDK_ROOT"])


class TestRunGridKltWiring(unittest.TestCase):
    """``run_grid_klt`` actually submits the staged, split, pinned request.

    The two classes above test the helpers; this tests that the sweep uses
    them, which is the regression that would otherwise pass unnoticed.
    ``klt_run.run_configs`` is replaced, so nothing is submitted anywhere.
    """

    def _capture(self, tmp: Path) -> dict:
        seen: dict = {}

        def fake_run_configs(configs, dut, ac_dec, f_start, f_stop, axes, workdir,
                             outdir, backend, in_flight, dc_seed="", log=print):
            seen["axes"] = axes
            seen["backend"] = backend
            seen["configs"] = list(configs)
            # Read at submit time: the pin must already be in place by now.
            seen["pdk_root"] = os.environ.get("PDK_ROOT")
            return {}, [], set()

        corners = sweep.resolve_corners(["tt"])
        grid = sweep.build_grid(corners, [27.0], [3.3])
        args = unittest.mock.Mock(temps=[27.0], ac_dec=int(sweep.AC_DEC), in_flight=1)
        pdk = Pdk(path=tmp / "root" / "gf180mcuD", variant="gf180mcuD", source="test")
        logdir = tmp / "logs"
        logdir.mkdir()  # main() makes these; run_grid_klt only writes into them
        with unittest.mock.patch.dict(os.environ, {"PDK_ROOT": "/stale/root"}), \
                unittest.mock.patch.object(sweep.klt_run, "run_configs", fake_run_configs), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            # The grid comes back empty, so every corner is reported as a
            # failure; only what was submitted is under test here.
            sweep.run_grid_klt(grid, corners, args, pdk, [1e-3], [1.0e-6], [0.05],
                               logdir, tmp / "work", "batch")
        seen["expected_pdk_root"] = str(pdk.path.parent)
        return seen

    def test_the_submitted_request_is_staged_split_and_pdk_pinned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            seen = self._capture(Path(tmpdir))
        self.assertIs(seen["axes"]["stage_model_inputs"], True)
        self.assertEqual(sweep.KLT_MAX_UNITS_PER_JOB,
                         seen["axes"]["batch"]["max_units_per_job"])
        self.assertEqual(seen["expected_pdk_root"], seen["pdk_root"])


if __name__ == "__main__":
    unittest.main()
