#!/usr/bin/env python3
"""Unit tests for the feedback divider's arrangement and reference netlist.

    python3 -m unittest discover -s layout/tests -v

No PDK, klayout or xschem required: these read only `layout/divider/plan.py`
(the arrangement, as numbers) and the committed LVS reference netlist. What
they hold is that the drawn array is still the one `layout/floorplan.md` §4.1
plans -- the same unit, the same 18-unit string, the same 1:2 tap, and above
all the same **common centroid**, which is the divider's only mitigation for
a mismatch term this PDK cannot simulate at all (`sim/devchar/CONCLUSIONS.md`
§2: the resistor cards hard-code `mis_r = 0`).

`layout/drclvs.py --cell divider` is what proves the *layout* implements this
netlist; these tests are what prove the netlist is still the *plan*.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parents[1]
DIVIDER_DIR = LAYOUT_DIR / "divider"
sys.path.insert(0, str(LAYOUT_DIR))
sys.path.insert(0, str(DIVIDER_DIR))

import plan  # noqa: E402

import drclvs  # noqa: E402

NETLIST = DIVIDER_DIR / "netlist" / "fb_divider.spice"

# floorplan.md §4.1's own numeric targets, transcribed here so a failure
# names the document's number rather than re-deriving it from the plan.
FLOORPLAN_CENTROID = 9.5  # "the top-leg centroid is 9.5 and the bottom-leg
#                            centroid is 9.5 -- the middle of a 1..18 row"
FLOORPLAN_UNIT_LEN_UM = 31.8
FLOORPLAN_UNIT_W_UM = 2.0
FLOORPLAN_PITCH_UM = 2.4
PRES2_MIN_SPACE_UM = 0.4  # PRES.2, the rule the pitch is set by


class ArrangementTests(unittest.TestCase):
    """floorplan.md §4.1's `B T B B T B B T B B T B B T B B T B` row."""

    def test_the_row_is_18_units_plus_one_dummy_at_each_end(self):
        self.assertEqual(plan.N_POSITIONS, 20)
        self.assertEqual(plan.DUMMY_POSITIONS, (0, 19))
        self.assertEqual(len(plan.ACTIVE_POSITIONS), 18)
        self.assertEqual(
            sorted(plan.TOP_POSITIONS + plan.BOT_POSITIONS),
            list(plan.ACTIVE_POSITIONS),
            "every active position must belong to exactly one leg",
        )

    def test_the_pattern_is_the_one_the_floorplan_writes_out(self):
        pattern = "".join(
            "T" if p in plan.TOP_POSITIONS else "B" for p in plan.ACTIVE_POSITIONS
        )
        self.assertEqual(pattern, "BTBBTBBTBBTBBTBBTB")

    def test_both_legs_land_on_the_floorplans_centroid(self):
        """The whole point of the interdigitation: an exact 1-D centroid."""
        self.assertAlmostEqual(plan.centroid(plan.TOP_POSITIONS), FLOORPLAN_CENTROID)
        self.assertAlmostEqual(plan.centroid(plan.BOT_POSITIONS), FLOORPLAN_CENTROID)
        self.assertAlmostEqual(
            plan.centroid(plan.ACTIVE_POSITIONS), FLOORPLAN_CENTROID
        )

    def test_the_ratio_is_the_ratified_one(self):
        top_k = len(plan.TOP_POSITIONS) * plan.UNIT_KOHM
        bot_k = len(plan.BOT_POSITIONS) * plan.UNIT_KOHM
        self.assertEqual(top_k, 300.0)
        self.assertEqual(bot_k, 600.0)
        self.assertEqual(top_k + bot_k, 900.0, "DR-0001's ~2 uA preload")
        # The feedback factor the error amp's VREF is compared against:
        # 1.8 V x 600k/900k = 1.2 V at FB.
        self.assertAlmostEqual(1.8 * bot_k / (top_k + bot_k), 1.2)
        # ... and the ~2 uA preload DR-0001 leans on.
        self.assertAlmostEqual(1.8 / (top_k + bot_k) * 1e3, 2.0, places=6)

    def test_the_unit_geometry_is_the_floorplans(self):
        self.assertAlmostEqual(plan.UNIT_W_UM, FLOORPLAN_UNIT_W_UM)
        self.assertAlmostEqual(plan.UNIT_L_UM, FLOORPLAN_UNIT_LEN_UM)
        # 50 kOhm at w = 2 um, from devchar's measured effective sheet.
        self.assertAlmostEqual(
            plan.UNIT_KOHM * plan.UM_PER_KOHM_AT_1UM * plan.UNIT_W_UM,
            FLOORPLAN_UNIT_LEN_UM,
            places=6,
        )

    def test_the_pitch_is_the_strip_plus_pres2(self):
        self.assertAlmostEqual(plan.PITCH_UM, FLOORPLAN_PITCH_UM)
        self.assertAlmostEqual(
            plan.PITCH_UM - plan.UNIT_W_UM, PRES2_MIN_SPACE_UM, places=9
        )


class LinkRoutabilityTests(unittest.TestCase):
    """Why gen_gds.py gives the two legs different Metal1 channels.

    A series chain must alternate sides at every unit, so each side of the
    row carries half of each leg's links. These tests hold the two facts
    that dictate the routing: each leg's own links never interleave (so one
    track per side is enough for it), but the two legs' do (so they cannot
    share one).
    """

    def _side_spans(self, order, side):
        return [
            (a, b) for a, b, s in plan.chain_links(order) if s == side
        ]

    def test_each_leg_alternates_sides(self):
        for order in (plan.BOT_ORDER, plan.TOP_ORDER):
            with self.subTest(order=order):
                sides = [s for _a, _b, s in plan.chain_links(order)]
                for first, second in zip(sides, sides[1:]):
                    self.assertNotEqual(
                        first, second,
                        "consecutive links share a unit, so they must use its "
                        "two different terminals -- i.e. opposite sides",
                    )

    def test_a_legs_own_links_never_interleave(self):
        for order in (plan.BOT_ORDER, plan.TOP_ORDER):
            for side in ("L", "R"):
                spans = self._side_spans(order, side)
                for i, a in enumerate(spans):
                    for b in spans[i + 1:]:
                        with self.subTest(order=order, side=side, a=a, b=b):
                            self.assertFalse(
                                plan.spans_overlap(a, b),
                                f"{a} and {b} would need two tracks on one side",
                            )

    def test_the_two_legs_links_do_interleave(self):
        """The reason the top leg is routed over the bodies, not beside them."""
        clashes = [
            (a, b)
            for side in ("L", "R")
            for a in self._side_spans(plan.BOT_ORDER, side)
            for b in self._side_spans(plan.TOP_ORDER, side)
            if plan.spans_overlap(a, b)
        ]
        self.assertTrue(
            clashes,
            "if the legs' links stopped interleaving, gen_gds.py's split into "
            "a side channel and an over-the-body track would be unnecessary",
        )

    def test_the_tap_joins_two_adjacent_positions_on_one_side(self):
        """FB is a single-metal-layer change, per DR-0003's mask option."""
        bot_free = (
            plan.BOT_ORDER[-1],
            plan.leg_terminal_side(len(plan.BOT_ORDER) - 1, end=True),
        )
        top_free = (plan.TOP_ORDER[0], plan.leg_terminal_side(0, end=False))
        self.assertEqual(bot_free[1], top_free[1])
        self.assertEqual(abs(bot_free[0] - top_free[0]), 1)


class ReferenceNetlistTests(unittest.TestCase):
    """The committed LVS reference netlist really is the planned string."""

    ELEMENT = re.compile(
        r"^(R\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+W=(\S+)\s+L=(\S+)\s+m=(\S+)$"
    )

    @classmethod
    def setUpClass(cls):
        cls.text = NETLIST.read_text()
        cls.elements = [
            m.groups()
            for m in (cls.ELEMENT.match(line) for line in cls.text.splitlines())
            if m
        ]

    def test_the_committed_netlist_exists_and_is_in_lvs_form(self):
        self.assertTrue(NETLIST.is_file(), NETLIST)
        self.assertIn(".subckt fb_divider VOUT_S FB VSS", self.text)
        self.assertIsNone(
            drclvs.SIM_FORM_RE.search(self.text),
            "the committed netlist is in xschem's simulation form, which "
            "KLayout's SPICE reader cannot read",
        )

    def test_every_unit_is_the_same_drawn_device(self):
        self.assertEqual(len(self.elements), plan.N_POSITIONS)
        for name, _a, _b, bulk, model, w, length, mult in self.elements:
            with self.subTest(device=name):
                self.assertEqual(model, "ppolyf_u_3k")
                self.assertEqual(bulk, "VSS")
                self.assertEqual(w, "2u")
                self.assertEqual(length, "31.8u")
                self.assertEqual(mult, "1")

    def test_the_string_is_a_series_chain_with_the_tap_after_12_units(self):
        chain = {
            name: (a, b)
            for name, a, b, _bulk, _model, _w, _l, _m in self.elements
            if not name.startswith("Rdum")
        }
        self.assertEqual(len(chain), 18)

        def walk(first, start):
            """Follow the chain from ``start``, returning the nodes visited."""
            node, nodes = start, [start]
            for index in range(1, 19):
                name = f"{first}{index}"
                if name not in chain:
                    break
                ends = chain[name]
                self.assertIn(node, ends, f"{name} does not continue the chain")
                node = ends[1] if ends[0] == node else ends[0]
                nodes.append(node)
            return nodes

        bottom = walk("Rb", "VSS")
        self.assertEqual(len(bottom) - 1, len(plan.BOT_POSITIONS))
        self.assertEqual(bottom[-1], "FB", "the tap is after 12 units from VSS")
        top = walk("Rt", "FB")
        self.assertEqual(len(top) - 1, len(plan.TOP_POSITIONS))
        self.assertEqual(top[-1], "VOUT_S")
        # Every internal node is used by exactly two units and nothing else.
        internal = set(bottom[1:-1]) | set(top[1:-1])
        self.assertEqual(len(internal), 16)
        self.assertFalse(internal & {"VSS", "FB", "VOUT_S"})

    def test_both_dummies_are_tied_off_to_vss(self):
        dummies = [e for e in self.elements if e[0].startswith("Rdum")]
        self.assertEqual(len(dummies), len(plan.DUMMY_POSITIONS))
        for name, a, b, bulk, *_rest in dummies:
            with self.subTest(device=name):
                self.assertEqual((a, b, bulk), ("VSS", "VSS", "VSS"))


class CellSpecTests(unittest.TestCase):
    """The divider's registration in layout/drclvs.py's `--cell` registry."""

    def test_divider_is_registered_and_points_at_files_that_exist(self):
        spec = drclvs.CELLS["divider"]
        self.assertIs(spec, drclvs.DIVIDER_SPEC)
        self.assertTrue(spec.gen_gds.is_file(), spec.gen_gds)
        self.assertTrue(spec.schematic.is_file(), spec.schematic)
        self.assertEqual(spec.top_cell, "FB_DIVIDER")

    def test_the_deck_is_told_which_resistor_flavour_to_extract(self):
        """`case POLY_RES` means the default 1k deck would not see these."""
        self.assertEqual(drclvs.DIVIDER_SPEC.poly_res, "3k")

    def test_the_extracted_netlist_is_not_collapsed_before_comparing(self):
        """Otherwise the compare cannot tell 18 units from one long strip."""
        self.assertFalse(drclvs.DIVIDER_SPEC.simplify_extracted)

    def test_the_run_record_states_the_matching_against_the_floorplan(self):
        """A record must carry the claim, not just the DRC/LVS verdicts."""
        note = drclvs.DIVIDER_SPEC.record_notes
        self.assertIn("Matching, as drawn", note)
        self.assertIn("floorplan.md", note)
        self.assertEqual(
            note.count(f"**{FLOORPLAN_CENTROID:g}**"),
            4,
            "both legs' centroids, each against §4.1's target, must be stated",
        )
        # And the caveat that keeps the verdict honest.
        self.assertIn("Resistance is not a compared parameter", note)


if __name__ == "__main__":
    unittest.main()
