#!/usr/bin/env python3
"""Unit tests for the pass-device array's two committed claims (issue #285).

    python3 -m unittest discover -s layout/tests -v

No PDK, klayout or xschem required. Two things are checked here that a
DRC/LVS run cannot check for itself:

1. **The array's LVS reference schematic has not drifted from the design.**
   ``layout/pass_array/pass_array.sch`` restates ``Mpass`` and ``Msense`` so the
   array can be LVS'd on its own; ``design/netlist/ldo_core.spice`` is where
   those devices actually live. LVS compares the layout against the copy, so
   nothing in the DRC/LVS flow would notice the copy going stale -- this does.

2. **The as-drawn metal really is checked against the published EM limits.**
   ``layout/pass_array/em_budget.py`` is the arithmetic the generator fails the
   build on; here it is exercised directly, including a deliberately
   under-viad geometry that must come out over the limit, and its published
   constants are re-derived from ``layout/floorplan.md`` §1 rather than
   trusted.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = LAYOUT_DIR.parent
PASS_ARRAY_DIR = LAYOUT_DIR / "pass_array"

sys.path.insert(0, str(LAYOUT_DIR))
sys.path.insert(0, str(PASS_ARRAY_DIR))

import drclvs  # noqa: E402
import em_budget  # noqa: E402

GEN_GDS = (PASS_ARRAY_DIR / "gen_gds.py").read_text()

# The geometry the committed run record was taken against -- every field is a
# number layout/pass_array/gen_gds.py MEASURED from what it had just drawn, so
# the ones that follow from the PDK's own pfet PCell (the 0.38 um strap, its
# 140 contacts, the 134-cut via1 column) cannot be re-derived here without
# KLayout. The ones that DO come from the generator's own constants are
# re-derived below, in test_frozen_geometry_still_matches_the_generator, so a
# constant edited without re-running the flow fails loudly rather than leaving
# this table quietly describing a layout that no longer exists.
AS_DRAWN = em_budget.ArrayGeometry(
    n_units=40,
    m_sense=1,
    finger_w_um=70.0,
    n_drain_regions=20,
    contacts_per_region=140,
    m1_strap_w_um=0.38,
    via1_pitch_um=0.52,
    via1_per_strap=134,
    m2_strap_w_um=0.50,
    m2_tap_pitch_max_um=7.5,
    via2_per_power_strap=48,
    via2_per_sense_strap=16,
    upper_strap_w_um=2.20,
    m5_strap_w_um=2.00,
    n_vout_rows=12,
    n_isns_rows=4,
    via34_per_row=165,
    exits=2,
)


def constant(name: str) -> str:
    """The right-hand side of a top-level assignment in gen_gds.py."""
    match = re.search(rf"^{name}\s*=\s*([^\s#]+)", GEN_GDS, re.M)
    if match is None:
        raise AssertionError(f"gen_gds.py no longer defines {name}")
    return match.group(1)


def device_params(line: str) -> dict[str, str]:
    """``L=0.28u W=2800u nf=40`` -> a dict, lowercased keys."""
    return {
        key.lower(): value
        for key, value in re.findall(r"\b([A-Za-z_]+)=([^\s}]+)", line)
    }


def spice_device(text: str, name: str) -> dict[str, str]:
    for line in text.splitlines():
        tokens = line.split()
        if tokens and tokens[0].upper() in (name.upper(), "X" + name.upper()):
            return device_params(line)
    raise AssertionError(f"no device line for {name} in the netlist")


def schematic_device(text: str, name: str) -> dict[str, str]:
    for line in text.splitlines():
        if re.search(rf"\bname={name}\b", line):
            return device_params(line)
    raise AssertionError(f"no instance named {name} in the schematic")


class ReferenceSchematicMatchesTheDesign(unittest.TestCase):
    """pass_array.sch's devices are ldo_core's, not an independent edit."""

    @classmethod
    def setUpClass(cls):
        cls.core = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()
        cls.sch = (PASS_ARRAY_DIR / "pass_array.sch").read_text()

    def test_mpass_is_the_same_device_as_in_ldo_core(self):
        design = spice_device(self.core, "Mpass")
        reference = schematic_device(self.sch, "Mpass")
        for key in ("l", "w", "nf"):
            self.assertEqual(
                design[key], reference[key],
                f"Mpass {key} drifted: design/netlist/ldo_core.spice says "
                f"{design[key]}, layout/pass_array/pass_array.sch says "
                f"{reference[key]}. The layout is LVS'd against the schematic, "
                "so this drift would not fail DRC/LVS.",
            )

    def test_msense_is_the_same_device_as_in_ldo_core(self):
        design = spice_device(self.core, "Msense")
        reference = schematic_device(self.sch, "Msense")
        for key in ("l", "w", "nf"):
            self.assertEqual(design[key], reference[key], f"Msense {key} drifted")

    def test_the_replica_ratio_is_still_forty(self):
        mpass = schematic_device(self.sch, "Mpass")
        msense = schematic_device(self.sch, "Msense")
        width = float(mpass["w"].rstrip("uU")) / float(msense["w"].rstrip("uU"))
        self.assertEqual(width, 40.0)
        self.assertEqual(int(mpass["nf"]) / int(msense["nf"]), 40.0)
        self.assertEqual(mpass["l"], msense["l"], "the replica must be at equal L")
        # Equal per-finger width is the other half of design/ldo_ilimit.sch's
        # rule, and it is what makes both devices land in the same model bin.
        self.assertEqual(
            float(mpass["w"].rstrip("uU")) / int(mpass["nf"]),
            float(msense["w"].rstrip("uU")) / int(msense["nf"]),
        )

    def test_the_generator_places_that_many_unit_cells(self):
        self.assertEqual(constant("N_UNITS"), "40")
        self.assertEqual(constant("M_SENSE"), "1")
        self.assertEqual(constant("REPLICA_RATIO"), "40")
        mpass = schematic_device(self.sch, "Mpass")
        unit_w = float(re.search(r'"w":\s*([0-9.]+)', GEN_GDS).group(1))
        self.assertAlmostEqual(
            unit_w * int(constant("N_UNITS")),
            float(mpass["w"].rstrip("uU")),
            places=6,
            msg="the unit cell count times the unit width is no longer Mpass's W",
        )

    def test_the_committed_lvs_netlist_agrees_too(self):
        netlist = PASS_ARRAY_DIR / "netlist" / "pass_array.spice"
        self.assertTrue(netlist.is_file(), f"{netlist} has not been exported")
        text = netlist.read_text()
        for name in ("Mpass", "Msense"):
            design = spice_device(self.core, name)
            exported = spice_device(text, name)
            for key in ("l", "w", "nf"):
                self.assertEqual(design[key], exported[key], f"{name} {key} drifted")

    def test_the_cell_is_registered_with_drclvs(self):
        spec = drclvs.CELLS["pass_array"]
        self.assertEqual(spec.top_cell, "PASS_ARRAY")
        self.assertTrue(spec.gen_gds.is_file())
        self.assertTrue(spec.schematic.is_file())
        self.assertTrue((PASS_ARRAY_DIR / "pass_array.sym").is_file())


class PublishedLimitsAreTheFloorplansOwn(unittest.TestCase):
    """em_budget's constants are transcriptions, so check the transcription."""

    @classmethod
    def setUpClass(cls):
        cls.floorplan = (LAYOUT_DIR / "floorplan.md").read_text()

    def test_routing_and_via_limits_match_floorplan_section_1(self):
        row = next(
            line for line in self.floorplan.splitlines()
            if line.startswith("| EM current density")
        )
        self.assertIn(f"{em_budget.J_M1_M4_MA_PER_UM} mA/", row)
        self.assertIn(f"{em_budget.J_M5_MA_PER_UM} mA/", row)
        self.assertIn(f"{em_budget.I_VIA_MA} mA per cut", row)
        self.assertIn(
            f"{int(em_budget.I_CONTACT_MA_PLACEHOLDER * 1e3)} µA/cut placeholder",
            row,
        )

    def test_the_contact_limit_is_still_flagged_as_an_assumption(self):
        row = em_budget.evaluate(AS_DRAWN)[0]
        self.assertIn("CON", row.level)
        self.assertIn("NOT a published limit", row.note)


class TheArrayAsDrawnCarriesFiftyMilliamps(unittest.TestCase):

    def test_every_level_is_inside_its_published_limit(self):
        for row in em_budget.evaluate(AS_DRAWN):
            with self.subTest(level=row.level):
                self.assertTrue(
                    row.ok,
                    f"{row.level} is at {row.density}, over {row.limit}",
                )

    def test_the_binding_margin_is_the_one_the_record_quotes(self):
        worst = min(em_budget.evaluate(AS_DRAWN), key=lambda row: row.margin)
        self.assertLess(worst.margin, 3.0)
        self.assertGreater(worst.margin, 2.0)

    def test_an_under_viad_array_is_reported_as_a_failure(self):
        starved = dataclasses_replace(AS_DRAWN, via1_per_strap=4)
        rows = {row.level: row for row in em_budget.evaluate(starved)}
        self.assertFalse(rows["Via1 column"].ok)

    def test_a_single_sided_landing_is_tighter_but_still_legal(self):
        one_side = dataclasses_replace(AS_DRAWN, exits=1)
        rows = {row.level: row for row in em_budget.evaluate(one_side)}
        self.assertLess(rows["M3 exit row"].margin,
                        dict((r.level, r) for r in em_budget.evaluate(AS_DRAWN))
                        ["M3 exit row"].margin)
        self.assertTrue(rows["M3 exit row"].ok)

    def test_the_array_fits_inside_the_ir_budget(self):
        nominal = em_budget.series_resistance_mohm(AS_DRAWN, 0)
        maximum = em_budget.series_resistance_mohm(AS_DRAWN, 1)
        # floorplan.md §3.4: 40 mOhm per side nominal, 80 mOhm per side max.
        self.assertLess(nominal["total"], 40.0)
        self.assertLess(maximum["total"], 80.0)
        # ...and what is left has to buy a bus run of non-zero length.
        self.assertGreater(em_budget.squares_left_for_the_bus(nominal["total"]), 0.0)

    def test_frozen_geometry_still_matches_the_generator(self):
        """Fields of AS_DRAWN that gen_gds.py fixes as constants."""
        self.assertEqual(AS_DRAWN.n_units, int(constant("N_UNITS")))
        self.assertEqual(AS_DRAWN.m_sense, int(constant("M_SENSE")))
        self.assertEqual(AS_DRAWN.m2_strap_w_um, float(constant("M2_W_UM")))
        self.assertEqual(AS_DRAWN.upper_strap_w_um, float(constant("UPPER_W_UM")))
        self.assertEqual(AS_DRAWN.via1_pitch_um, float(constant("VIA_PITCH_UM")))
        self.assertEqual(AS_DRAWN.exits, int(constant("EXIT_EDGES")))
        self.assertAlmostEqual(
            AS_DRAWN.m5_strap_w_um,
            float(constant("UPPER_W_UM")) - 2 * float(constant("M5_INSET_UM")),
            places=6,
        )
        self.assertAlmostEqual(
            AS_DRAWN.finger_w_um,
            float(re.search(r'"w":\s*([0-9.]+)', GEN_GDS).group(1)),
            places=6,
        )
        # Two halves of N_UNITS fingers each present N_UNITS/2 drain regions.
        self.assertEqual(AS_DRAWN.n_drain_regions, AS_DRAWN.n_units // 2)


def dataclasses_replace(instance, **changes):
    import dataclasses

    return dataclasses.replace(instance, **changes)


if __name__ == "__main__":
    unittest.main()
