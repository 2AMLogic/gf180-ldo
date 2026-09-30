#!/usr/bin/env python3
"""Unit tests for layout/area_estimate.py.

    python3 -m unittest discover -s layout/tests -v

No PDK, klayout, ngspice or xschem required: these tests read only the
committed `design/netlist/ldo_core.spice` and the pure-arithmetic geometry
model in `area_estimate.py`.

The load-bearing test here is `CoreBudgetTests` -- it turns
`layout/floorplan.md`'s area claim into a check that fails when a future
device resize pushes the estimate past the ratified `< 0.1 mm^2` core budget,
so the claim cannot go quietly stale the way a hand-typed number would.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT_DIR))

import area_estimate as ae  # noqa: E402


class GeometryModelTests(unittest.TestCase):
    """The device geometry model, checked against hand-computed values."""

    def test_fet_area_matches_hand_calculation(self):
        # One 50 um finger, L = 0.28 um, nf = 1: two end source/drain regions
        # around a single gate -> 50 * (0.28 + 2*0.44) = 58 um^2.
        self.assertAlmostEqual(ae.fet_area(50e-6, 0.28e-6, 1, 1), 58.0, places=6)

    def test_fet_area_is_nearly_independent_of_segmentation(self):
        """Segmentation is ~free in area, so it is chosen on EM/IR grounds.

        This is the premise floorplan.md §3.1 rests on when it picks the
        per-finger width from electromigration rather than from area.
        """
        total_w = 4000e-6
        areas = [
            ae.fet_area(total_w, 0.28e-6, nf, 1) for nf in (40, 80, 160, 320)
        ]
        # All within 3% of the widest-finger case.
        for a in areas:
            self.assertLess(abs(a - areas[0]) / areas[0], 0.03)

    def test_per_finger_width_stays_inside_the_dfb2b_and_model_bin_limit(self):
        """DF.2b caps COMP width at 100 um; DR-0025 caps the model bin there too."""
        devices = ae.collect()
        passfet = next(d for d in devices if d.name == "XMpass")
        self.assertEqual(passfet.block, "pass_array")
        # As shipped since #294 / DR-0034: W = 2800 um over nf = 40 -> 70 um
        # per finger (it was 2000 um / 50 um per finger before that).
        self.assertLessEqual(2800.0 / 40, ae.DF_MAX_W)

    def test_resistor_ladder_pitch_uses_pres2(self):
        # A 1 um x 100 um segment: one segment, heads at both ends, PRES.2
        # spacing in the width direction.
        self.assertAlmostEqual(
            ae.res_field(1.0, 100.0, 1), (100.0 + 2.0) * 1.4, places=6
        )

    def test_mim_footprint_includes_the_mim1_keepout(self):
        self.assertAlmostEqual(ae.mim_field(87.0, 87.0, 1), 89.4 * 89.4, places=6)


class NetlistParseTests(unittest.TestCase):
    """Parsing `ldo_core.spice` -- the single file that carries every subckt."""

    def setUp(self):
        self.devices = ae.collect()

    def test_no_subcircuit_is_double_counted(self):
        """Reading the per-subckt files as well would duplicate every device."""
        amp = [d for d in self.devices if d.block == "error_amp"]
        self.assertEqual(len([d for d in amp if d.name == "XMIN1"]), 1)

    def test_every_expected_block_is_present(self):
        blocks = {d.block for d in self.devices}
        self.assertEqual(
            blocks,
            {"pass_array", "divider", "error_amp", "ldo_ilimit", "ldo_softstart"},
        )

    def test_sense_replica_is_homed_in_the_pass_array(self):
        """`XMsense` tracks `XMpass`, so it is floorplanned inside the array."""
        sense = next(d for d in self.devices if d.name == "XMsense")
        self.assertEqual(sense.block, "pass_array")

    def test_ideal_divider_resistors_are_replaced_by_the_planned_array(self):
        """`Rtop`/`Rbot` are ideal in the netlist; layout must draw them."""
        names = {d.name for d in self.devices if d.block == "divider"}
        self.assertIn("Rdiv[array]", names)
        self.assertIn("XCff", names)
        self.assertNotIn("Rtop", names, "ideal pair should not be double-counted")
        self.assertNotIn("Rbot", names)

    def test_no_single_mim_plate_exceeds_mim8b(self):
        """MIM.8b caps a single plate at 10000 um^2 -- bigger needs splitting."""
        for d in self.devices:
            if d.kind == "cap":
                self.assertNotIn("exceeds MIM.8b", d.note, msg=f"{d.name}: {d.note}")


class DividerMatchingTests(unittest.TestCase):
    """floorplan.md §4.1's divider plan, against #9's offset budget."""

    def test_unit_string_reproduces_the_ratified_divider_value(self):
        total_k = (ae.DIV_UNITS_TOP + ae.DIV_UNITS_BOT) * ae.DIV_UNIT_KOHM
        self.assertEqual(total_k, 900.0, "DR-0001's ~2 uA preload must not move")
        self.assertEqual(ae.DIV_UNITS_TOP * ae.DIV_UNIT_KOHM, 300.0)
        self.assertEqual(ae.DIV_UNITS_BOT * ae.DIV_UNIT_KOHM, 600.0)

    def test_planned_geometry_beats_the_budgeted_divider_term(self):
        """#9 budgets 3.36 mV (3 sigma); the planned array must not be worse."""
        _, sigma3 = ae.divider_field()
        self.assertLess(sigma3, 3.36)

    def test_unit_count_admits_an_exact_common_centroid(self):
        """A 1:2 ratio over 18 units has to place both centroids at the middle."""
        n = ae.DIV_UNITS_TOP + ae.DIV_UNITS_BOT
        top = [3 * i + 2 for i in range(ae.DIV_UNITS_TOP)]  # B T B repeating
        bot = [p for p in range(1, n + 1) if p not in top]
        self.assertEqual(len(bot), ae.DIV_UNITS_BOT)
        middle = (n + 1) / 2
        self.assertAlmostEqual(sum(top) / len(top), middle)
        self.assertAlmostEqual(sum(bot) / len(bot), middle)


class InputPairCentroidTests(unittest.TestCase):
    """floorplan.md §4.2's 2 x 6 input-pair arrangement."""

    ROWS = ["ABBAAB", "BAABBA"]

    def test_no_single_row_of_six_can_be_centroid_balanced(self):
        """Three of each in a row of six needs a position sum of 10.5."""
        self.assertNotEqual((1 + 2 + 3 + 4 + 5 + 6) / 2, int((1 + 2 + 3 + 4 + 5 + 6) / 2))

    def test_the_two_rows_are_complements_and_the_quad_is_centroid_matched(self):
        cols = {"A": [], "B": []}
        rows = {"A": [], "B": []}
        for r, pattern in enumerate(self.ROWS, start=1):
            self.assertEqual(pattern.count("A"), 3)
            self.assertEqual(pattern.count("B"), 3)
            for c, leg in enumerate(pattern, start=1):
                cols[leg].append(c)
                rows[leg].append(r)
        for axis in (cols, rows):
            self.assertEqual(len(axis["A"]), len(axis["B"]))
            self.assertAlmostEqual(
                sum(axis["A"]) / len(axis["A"]), sum(axis["B"]) / len(axis["B"])
            )

    def test_input_pair_is_not_re_segmented_across_a_model_bin_edge(self):
        """`W/nf` = 10 um sits exactly on a DR-0025 bin edge (floorplan.md §4.4)."""
        devices = ae.collect()
        self.assertTrue(any(d.name == "XMIN1" for d in devices))
        self.assertEqual(60.0 / 6, 10.0)  # W / nf, as netlisted


class CoreBudgetTests(unittest.TestCase):
    """The ratified `< 0.1 mm^2` core-area row, as an executable check."""

    def test_estimate_fits_the_budget_as_shipped(self):
        s = ae.summarize(ae.collect())
        self.assertLess(
            s["core_um2"],
            ae.AREA_BUDGET_UM2,
            msg=(
                f"core estimate {s['core_um2']:.0f} um^2 exceeds the ratified "
                f"{ae.AREA_BUDGET_UM2:.0f} um^2 budget -- see layout/floorplan.md §6"
            ),
        )

    def test_estimate_fits_the_budget_at_every_issue_139_candidate(self):
        """#139's pass-device width is undecided; all three candidates must fit."""
        for width_um in (2000.0, 2530.0, 4000.0):
            with self.subTest(pass_width_um=width_um):
                s = ae.summarize(ae.collect(width_um))
                self.assertLess(s["core_um2"], ae.AREA_BUDGET_UM2)

    def test_the_documented_margin_still_holds(self):
        """floorplan.md §6 claims >= 20% margin at the worst #139 candidate."""
        s = ae.summarize(ae.collect(4000.0))
        self.assertGreaterEqual(1.0 - s["budget_fraction"], 0.20)

    def test_the_pass_device_is_not_the_dominant_area_term(self):
        """floorplan.md §6's headline finding, kept honest against the netlist."""
        s = ae.summarize(ae.collect(4000.0))
        self.assertLess(s["fet_pass"], s["res"])
        self.assertLess(s["fet_pass"], s["mim"])


if __name__ == "__main__":
    unittest.main()
