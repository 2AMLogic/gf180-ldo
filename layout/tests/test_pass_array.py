#!/usr/bin/env python3
"""Unit tests for the pass-device array's two committed claims (issue #285).

    python3 -m unittest discover -s layout/tests -v

No PDK, klayout or xschem required. Three things are checked here that a
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

3. **A committed bench DUT is the pinned export it claims to come from.**
   ``sim/pass-array-pex/testbench/pass_array_dut.spice`` (whenever that bench
   is present) restates ``ldo_core/XMpass`` and ``ldo_ilimit/XMsense`` for
   ``klt pex``'s DUT swap, and its header claims every device line is
   byte-identical to the export. PR #791 committed it with both cards'
   source-perimeter expression typo'd and every CI job stayed green, so here
   every card is compared against the design export on committed text alone
   (issue #792).
"""

from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = LAYOUT_DIR.parent
PASS_ARRAY_DIR = LAYOUT_DIR / "pass_array"
BENCH_DIR = REPO_ROOT / "sim" / "pass-array-pex"
BENCH_DUT = BENCH_DIR / "testbench" / "pass_array_dut.spice"

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


# The bench DUT exactly as #791 should have committed it: both device cards
# byte-identical to their counterparts in design/netlist/ldo_core.spice, PEX
# pin order intact. Pinned by the SHA-256 #793 reported for the corrected
# deck, so this fixture cannot drift from the deck its corner rerun cites.
CORRECTED_BENCH_DUT = """\
** sch_path: layout/pass_array/pass_array.sch
* pass_array -- ngspice-form DUT for the klt pex array bench (issue #786).
*
* Source of truth: layout/pass_array/pass_array.sch, exported through the
* repo's pinned-xschem path (sim/harness/xschem_export.py + design/xschemrc,
* xschem 3.4.7, ERC on) -- the same export design/netlist.py performs, not a
* hand transcription. One mechanical edit versus that export, forced by klt
* pex's DUT-swap contract (klayout-tools docs/cli/pex.md, "Pin order must
* match"): this .subckt header declares the pins in klt extract's
* deterministic order (ports alphabetical) rather than the symbol's order, so
* the bench's single instantiation line is valid for both the schematic leg
* and the extracted leg. Every device line below is byte-identical to the
* export; the LVS-form netlist (layout/pass_array/netlist/pass_array.spice)
* remains the LVS reference and is untouched.
.subckt pass_array ISNS PASS_GATE VIN VOUT
*.PININFO ISNS:B PASS_GATE:I VIN:B VOUT:B
XMpass VOUT PASS_GATE VIN VIN pfet_03v3 L=0.28u W=2800u nf=40 ad='int((nf+1)/2) * W/nf * 0.18u' as='int((nf+2)/2) * W/nf * 0.18u' pd='2*int((nf+1)/2) * (W/nf + 0.18u)'
+ ps='2*int((nf+2)/2) * (W/nf + 0.18u)' nrd='0.18u / W' nrs='0.18u / W' sa=0 sb=0 sd=0 m=1
XMsense ISNS PASS_GATE VIN VIN pfet_03v3 L=0.28u W=70u nf=1 ad='int((nf+1)/2) * W/nf * 0.18u' as='int((nf+2)/2) * W/nf * 0.18u' pd='2*int((nf+1)/2) * (W/nf + 0.18u)'
+ ps='2*int((nf+2)/2) * (W/nf + 0.18u)' nrd='0.18u / W' nrs='0.18u / W' sa=0 sb=0 sd=0 m=1
.ends
"""

# The deck PR #791 actually committed: the same file with both source
# perimeters hand-typo'd from a sum into a product -- an area where ngspice
# takes a perimeter.
REVIEWED_791_DUT = CORRECTED_BENCH_DUT.replace(
    "ps='2*int((nf+2)/2) * (W/nf + 0.18u)'",
    "ps='2*int((nf+2)/2) * W/nf * 0.18u'",
)

# Bench instance -> where its card lives in the design export.
BENCH_DEVICE_SOURCES = {
    "XMPASS": ("ldo_core", "XMpass"),
    "XMSENSE": ("ldo_ilimit", "XMsense"),
}


def subckt_device_cards(text: str, subckt: str) -> dict[str, str]:
    """Every device card inside ``.subckt <subckt>`` .. ``.ends``, keyed by
    its uppercased instance name.  Continuation lines (leading ``+``) are
    joined onto their card and whitespace runs collapsed, so a card matches
    its counterpart however the export wrapped it.  Comment lines are
    ignored; a duplicated instance name is an error, never a silent
    overwrite.
    """
    body: list[str] = []
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if not inside and line.lower().startswith(".subckt"):
            if line.split()[1].lower() == subckt.lower():
                inside = True
            continue
        if inside and line.lower().startswith(".ends"):
            break
        if inside:
            body.append(line)
    if not inside:
        raise AssertionError(f"no .subckt {subckt} in the netlist")

    cards: dict[str, str] = {}
    card: list[str] = []

    def flush() -> None:
        if not card:
            return
        name = card[0].split()[0].upper()
        if name in cards:
            raise AssertionError(
                f"duplicated device {name} inside .subckt {subckt}"
            )
        cards[name] = " ".join(" ".join(card).split())

    for line in body:
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if not card:
                raise AssertionError(
                    f"continuation line before any device inside "
                    f".subckt {subckt}: {line!r}"
                )
            card.append(line[1:])
            continue
        flush()
        card = [line]
    flush()
    return cards


def first_card_difference(bench_card: str, design_card: str) -> str:
    """Where two canonical cards first disagree, token by token."""
    bench = bench_card.split()
    design = design_card.split()
    for position, (bench_token, design_token) in enumerate(zip(bench, design), 1):
        if bench_token != design_token:
            return (
                f"token {position}: bench says {bench_token!r}, "
                f"design export says {design_token!r}"
            )
    if len(bench) != len(design):
        short = "the bench card ends early" if len(bench) < len(design) \
            else "the design card ends early"
        return f"{short} after {min(len(bench), len(design))} shared tokens"
    return "the cards differ only in whitespace"


def bench_card_mismatches(dut_text: str, design_text: str, source: str) -> list[str]:
    """Compare the bench DUT's ``pass_array`` cards against the design export.

    Returns one human-readable line per problem, each naming ``source`` and,
    where applicable, the offending instance; an empty list means the DUT is
    the export, card for card.
    """
    try:
        actual = subckt_device_cards(dut_text, "pass_array")
    except AssertionError as malformed:
        return [f"{source}: {malformed}"]
    expected = {
        bench_name: subckt_device_cards(design_text, subckt)[instance.upper()]
        for bench_name, (subckt, instance) in BENCH_DEVICE_SOURCES.items()
    }
    wanted = " and ".join(expected)
    problems: list[str] = []
    for bench_name in expected:
        if bench_name not in actual:
            problems.append(
                f"{source}: missing device {bench_name} -- the DUT must "
                f"carry exactly {wanted} from the design export"
            )
    for bench_name in actual:
        if bench_name not in expected:
            problems.append(
                f"{source}: extra device {bench_name} -- the DUT must "
                f"carry exactly {wanted} from the design export"
            )
    for bench_name, design_card in expected.items():
        if bench_name in actual and actual[bench_name] != design_card:
            problems.append(
                f"{source}: {bench_name} is not the design export's card "
                f"({first_card_difference(actual[bench_name], design_card)})"
            )
    return problems


def bench_card_span(deck: str, device: str) -> tuple[int, int, list[str]]:
    """``(start, end, lines)`` covering device's card, '+' lines included."""
    lines = deck.splitlines()
    for i, line in enumerate(lines):
        if line.split()[:1] == [device]:
            end = i
            while end + 1 < len(lines) and lines[end + 1].startswith("+"):
                end += 1
            return i, end, lines
    raise AssertionError(f"no {device} card in the deck")


def rewrite_bench_card(deck: str, device: str, replacement: list[str]) -> str:
    start, end, lines = bench_card_span(deck, device)
    return "\n".join(lines[:start] + replacement + lines[end + 1:]) + "\n"


def reintroduce_791_typo_on(deck: str, device: str) -> str:
    """The #791 perimeter typo back on one card's continuation line only."""
    start, end, lines = bench_card_span(deck, device)
    card = lines[start:end + 1]
    typoed = card[1].replace("(W/nf + 0.18u)", "W/nf * 0.18u")
    if typoed == card[1]:
        raise AssertionError(f"{device}'s continuation has no perimeter sum to typo")
    return rewrite_bench_card(deck, device, [card[0], typoed])


def drop_bench_card(deck: str, device: str) -> str:
    return rewrite_bench_card(deck, device, [])


def duplicate_bench_card(deck: str, device: str) -> str:
    start, end, lines = bench_card_span(deck, device)
    card = lines[start:end + 1]
    return rewrite_bench_card(deck, device, card + card)


def add_extra_bench_card(deck: str, device: str, name: str) -> str:
    start, end, lines = bench_card_span(deck, device)
    card = lines[start:end + 1]
    extra = [name + card[0][len(device):]] + card[1:]
    return rewrite_bench_card(deck, device, card + extra)


class BenchDutIsTheDesignExport(unittest.TestCase):
    """The pass-array bench DUT must be the design export, card for card.

    Controlled examples below run on any tree (main has no bench yet); the
    committed-bench check activates as soon as ``sim/pass-array-pex/`` lands.
    """

    @classmethod
    def setUpClass(cls):
        cls.core = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()

    def test_the_corrected_fixture_is_the_deck_793_reran(self):
        self.assertEqual(
            hashlib.sha256(CORRECTED_BENCH_DUT.encode()).hexdigest(),
            "2aa8d2bd3ee13f2bbdd924b59055cb16019fab2c4cd046ddb29c17328e380c73",
            "the controlled example is no longer the corrected deck #793 "
            "reported its corner rerun for",
        )

    def test_the_corrected_deck_is_accepted(self):
        self.assertEqual(
            bench_card_mismatches(
                CORRECTED_BENCH_DUT, self.core, "<corrected deck fixture>"
            ),
            [],
        )

    def test_the_reviewed_791_deck_is_rejected_on_both_devices(self):
        problems = bench_card_mismatches(
            REVIEWED_791_DUT, self.core, "<PR #791 deck fixture>"
        )
        self.assertEqual(len(problems), 2, "\n".join(problems))
        for bench_name in BENCH_DEVICE_SOURCES:
            named = [p for p in problems if bench_name in p]
            self.assertEqual(len(named), 1, "\n".join(problems))
        self.assertIn(
            "bench says 'W/nf', design export says '(W/nf'",
            "\n".join(problems),
            "the report must point at the typo'd perimeter expression itself",
        )

    def test_the_typo_on_either_continuation_line_alone_is_rejected(self):
        for device in ("XMpass", "XMsense"):
            with self.subTest(device=device):
                problems = bench_card_mismatches(
                    reintroduce_791_typo_on(CORRECTED_BENCH_DUT, device),
                    self.core,
                    "<fixture>",
                )
                self.assertEqual(len(problems), 1, "\n".join(problems))
                self.assertIn(device.upper(), problems[0])

    def test_a_missing_device_is_rejected(self):
        for device in ("XMpass", "XMsense"):
            with self.subTest(device=device):
                problems = bench_card_mismatches(
                    drop_bench_card(CORRECTED_BENCH_DUT, device),
                    self.core,
                    "<fixture>",
                )
                self.assertEqual(len(problems), 1, "\n".join(problems))
                self.assertIn(f"missing device {device.upper()}", problems[0])

    def test_a_duplicated_device_is_rejected(self):
        problems = bench_card_mismatches(
            duplicate_bench_card(CORRECTED_BENCH_DUT, "XMsense"),
            self.core,
            "<fixture>",
        )
        self.assertEqual(len(problems), 1, "\n".join(problems))
        self.assertIn("duplicated device XMSENSE", problems[0])

    def test_an_extra_device_is_rejected(self):
        problems = bench_card_mismatches(
            add_extra_bench_card(CORRECTED_BENCH_DUT, "XMsense", "XMshadow"),
            self.core,
            "<fixture>",
        )
        self.assertEqual(len(problems), 1, "\n".join(problems))
        self.assertIn("extra device XMSHADOW", problems[0])

    def test_the_committed_bench_dut_is_checked_whenever_the_bench_exists(self):
        if not BENCH_DIR.is_dir():
            self.skipTest("sim/pass-array-pex/ is not on this tree yet (issue #786)")
        self.assertTrue(
            BENCH_DUT.is_file(),
            f"{BENCH_DUT.relative_to(REPO_ROOT)}: the bench directory is "
            "committed, so its DUT must be committed too",
        )
        problems = bench_card_mismatches(
            BENCH_DUT.read_text(),
            self.core,
            str(BENCH_DUT.relative_to(REPO_ROOT)),
        )
        self.assertEqual(problems, [], "\n".join(problems))


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
