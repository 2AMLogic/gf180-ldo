#!/usr/bin/env python3
"""Unit tests for the PVT harness. No PDK and no ngspice required.

    python3 -m unittest discover -s sim/tests -v
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import cli, corners, deck, klt_grid, report, runner, testbench  # noqa: E402
from harness import evidence_store as store_mod  # noqa: E402
from harness import klt_record as kr  # noqa: E402
from harness import load_sink  # noqa: E402
from harness import tb_adapter as ta  # noqa: E402
from harness.pdk import Pdk  # noqa: E402
from harness.pvt_log import (  # noqa: E402
    read_measurements,
    report_flag,
    report_minmax,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_evidence_store import fake_klt  # noqa: E402


def fake_pdk(root: Path) -> Pdk:
    (root / "libs.tech" / "ngspice").mkdir(parents=True, exist_ok=True)
    (root / "libs.tech" / "ngspice" / "sm141064.ngspice").write_text("* fake\n")
    (root / "libs.tech" / "ngspice" / "design.ngspice").write_text("* fake\n")
    (root / "SOURCES").write_text("open_pdks deadbeef\n")
    return Pdk(path=root, variant=root.name, source="test")


class CornerTests(unittest.TestCase):
    def test_pvt_axes_match_the_mandated_grid(self):
        self.assertEqual(corners.DEFAULT_TEMPERATURES_C, (-40.0, 27.0, 125.0))
        self.assertAlmostEqual(corners.DEFAULT_SUPPLY_TOLERANCE, 0.10)

    def test_nominal_supply_matches_dr_0002(self):
        """spec/decision-records/DR-0002-input-flavor.md: 3.3 V +/-10% (2.97-3.63 V)."""
        self.assertAlmostEqual(corners.DEFAULT_NOMINAL_SUPPLY_V, 3.3)

    def test_supply_points_are_nominal_plus_minus_ten_percent(self):
        self.assertEqual(corners.supply_points(3.3, 0.10), [2.97, 3.3, 3.63])

    def test_zero_tolerance_collapses_the_voltage_axis(self):
        self.assertEqual(corners.supply_points(3.3, 0.0), [3.3])

    def test_every_corner_names_one_section_per_device_family(self):
        for name, corner in corners.CORNERS.items():
            with self.subTest(corner=name):
                self.assertEqual(len(corner.sections), 6, corner.sections)
                self.assertEqual(len(set(corner.sections)), 6, corner.sections)

    def test_corner_sets_expand_and_deduplicate(self):
        resolved = corners.resolve_corners(["mos", "tt"])
        self.assertEqual([c.name for c in resolved], ["tt", "ff", "ss", "fs", "sf"])

    def test_unknown_corner_is_rejected(self):
        with self.assertRaises(KeyError):
            corners.resolve_corners(["nope"])

    def test_grid_is_full_factorial_and_ordered(self):
        grid = corners.build_grid(corners.resolve_corners(["mos"]), (-40, 27, 125), [2.97, 3.3, 3.63])
        self.assertEqual(len(grid), 5 * 3 * 3)
        self.assertEqual(len({p.corner_id for p in grid}), 45)

    def test_corner_id_matches_the_ratified_naming(self):
        """sim/README.md: <corner-id> is <process>_<temp>c_<supply>v."""
        grid = corners.build_grid(
            corners.resolve_corners(["tt", "ss", "ff"]), (-40, 27, 125), [2.97, 3.3, 3.63]
        )
        ids = {p.corner_id for p in grid}
        self.assertIn("tt_27c_3.30v", ids)
        self.assertIn("ss_-40c_2.97v", ids)
        self.assertIn("ff_125c_3.63v", ids)

    def test_corner_id_preserves_fractional_temperature_precision(self):
        """issue #780: six significant digits truncated ``27.123456`` to
        ``27.1235`` on the grid side while the klt report reader kept the full
        value, so the join that matches a report row to its grid point found
        nothing. One formatter means one spelling."""
        p = corners.PvtPoint(corner=corners.CORNERS["tt"], temp_c=27.123456, vdd=3.3)
        self.assertEqual(p.corner_id, "tt_27.123456c_3.30v")

    def test_corner_id_normalizes_signed_zero(self):
        """issue #780: ``:g`` spelled ``-0.0`` as ``-0c`` while the report
        reader's integer conversion produced ``0c`` -- a third silent miss."""
        p = corners.PvtPoint(corner=corners.CORNERS["tt"], temp_c=-0.0, vdd=3.3)
        self.assertEqual(p.corner_id, "tt_0c_3.30v")


class TestbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _write(self, netlist: str, manifest: dict | None = None) -> Path:
        """Lay out sim/<slug>/testbench/ the way sim/README.md specifies."""
        tb_dir = self.dir / "an-experiment" / "testbench"
        tb_dir.mkdir(parents=True, exist_ok=True)
        (tb_dir / "x.spice").write_text(netlist)
        base = {"name": "x", "netlist": "x.spice", "measure": {"vout": "v(out)"}}
        base.update(manifest or {})
        (tb_dir / "tb.json").write_text(json.dumps(base))
        return tb_dir

    def test_loads_a_valid_manifest(self):
        tb = testbench.load(self._write("v1 out 0 dc {vdd_val}\n"))
        self.assertEqual(tb.name, "x")
        self.assertEqual(tb.measure, {"vout": "v(out)"})
        self.assertEqual(tb.temperatures_c, (-40.0, 27.0, 125.0))
        self.assertEqual(tb.operating_conditions, {})

    def test_operating_conditions_are_loaded_from_the_manifest(self):
        """LDO-specific extension to sim/README.md's record (bandgap has none)."""
        tb = testbench.load(
            self._write(
                "v1 out 0 dc {vdd_val}\n",
                {
                    "operating_conditions": {
                        "load_current": "50mA",
                        "output_cap": "1.0uF, ESR=100mOhm",
                        "enable_state": "enabled (EN = VIN)",
                    }
                },
            )
        )
        self.assertEqual(
            tb.operating_conditions,
            {
                "load_current": "50mA",
                "output_cap": "1.0uF, ESR=100mOhm",
                "enable_state": "enabled (EN = VIN)",
            },
        )

    def test_nodeset_is_loaded_from_the_manifest(self):
        """#40: bias hints for a closed-loop DUT's initial op-point guess."""
        tb = testbench.load(
            self._write(
                "v1 out 0 dc {vdd_val}\n",
                {"nodeset": {"vout": "1.8", "loop": "0.7"}},
            )
        )
        self.assertEqual(tb.nodeset, {"vout": "1.8", "loop": "0.7"})

    def test_nodeset_defaults_to_empty(self):
        tb = testbench.load(self._write("v1 out 0 dc {vdd_val}\n"))
        self.assertEqual(tb.nodeset, {})

    def test_experiment_slug_comes_from_the_directory_layout(self):
        tb_dir = self._write("v1 out 0 dc {vdd_val}\n")
        # Loadable by testbench dir *and* by experiment dir.
        for target in (tb_dir, tb_dir.parent):
            with self.subTest(target=target.name):
                tb = testbench.load(target)
                self.assertEqual(tb.experiment, "an-experiment")
                self.assertEqual(tb.experiment_dir.name, "an-experiment")

    def test_discover_finds_experiments_not_bare_manifest_dirs(self):
        self._write("v1 out 0 dc {vdd_val}\n")
        found = testbench.discover(self.dir)
        self.assertEqual([p.name for p in found], ["an-experiment"])

    def test_rejects_netlists_that_pin_the_temperature(self):
        with self.assertRaises(ValueError) as ctx:
            testbench.load(self._write("v1 out 0 dc 3.3\n.temp 27\n"))
        self.assertIn(".temp", str(ctx.exception))

    def test_rejects_netlists_that_include_models_themselves(self):
        with self.assertRaises(ValueError):
            testbench.load(self._write('.lib "models" typical\nv1 out 0 dc 3.3\n'))

    def test_rejects_a_manifest_without_measurements(self):
        with self.assertRaises(ValueError):
            testbench.load(self._write("v1 out 0 dc 3.3\n", {"measure": {}}))

    def _write_design(self, text: str, name: str = "cell.spice") -> Path:
        design = self.dir / "design"
        design.mkdir(parents=True, exist_ok=True)
        (design / name).write_text(text)
        return design / name

    def test_includes_are_resolved_relative_to_the_testbench_directory(self):
        self._write_design(".subckt cell a b\nr1 a b 1k\n.ends\n")
        tb = testbench.load(
            self._write(
                "x1 in out cell\n",
                {"includes": ["../../design/cell.spice"]},
            )
        )
        self.assertEqual([p.name for p in tb.includes], ["cell.spice"])
        self.assertTrue(tb.includes[0].is_file())

    def test_a_missing_include_is_rejected_with_the_resolved_path(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            testbench.load(self._write("x1 in out cell\n", {"includes": ["../../design/nope.spice"]}))
        self.assertIn("nope.spice", str(ctx.exception))

    def test_an_included_design_netlist_may_not_carry_end(self):
        """A trailing `.end` inside an include truncates the whole deck."""
        self._write_design(".subckt cell a b\nr1 a b 1k\n.ends\n.end\n")
        with self.assertRaises(ValueError) as ctx:
            testbench.load(self._write("x1 in out cell\n", {"includes": ["../../design/cell.spice"]}))
        self.assertIn("included design netlist", str(ctx.exception))

    def test_include_provenance_carries_a_sha256_per_file(self):
        self._write_design(".subckt cell a b\nr1 a b 1k\n.ends\n")
        tb = testbench.load(
            self._write("x1 in out cell\n", {"includes": ["../../design/cell.spice"]})
        )
        entries = tb.include_provenance(self.dir.resolve())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], "design/cell.spice")
        self.assertEqual(len(entries[0]["sha256"]), 64)

    def test_dut_netlist_is_absent_by_default(self):
        tb = testbench.load(self._write("v1 out 0 dc {vdd_val}\n"))
        self.assertIsNone(tb.dut_netlist)
        self.assertEqual(tb.dut_netlist_rel, "")
        self.assertIsNone(tb.dut_netlist_sha256)
        self.assertIsNone(tb.provenance()["dut_netlist"])

    def test_dut_netlist_resolves_repo_relative_paths(self):
        """#12: parameterizes a testbench over its DUT netlist source."""
        tb = testbench.load(
            self._write(
                "v1 vin 0 dc {vdd_val}\n",
                {"dut_netlist": "sim/smoke-bias/testbench/smoke_bias.spice"},
            )
        )
        self.assertIsNotNone(tb.dut_netlist)
        self.assertTrue(tb.dut_netlist.is_file())
        self.assertEqual(tb.dut_netlist_rel, "sim/smoke-bias/testbench/smoke_bias.spice")
        self.assertIsNotNone(tb.dut_netlist_sha256)
        self.assertEqual(tb.provenance()["dut_netlist"], tb.dut_netlist_rel)

    def test_missing_dut_netlist_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            testbench.load(
                self._write(
                    "v1 vin 0 dc {vdd_val}\n", {"dut_netlist": "design/does-not-exist.spice"}
                )
            )

    def test_dut_netlist_and_includes_coexist_as_one_ordered_list(self):
        """#12's DUT designation rides on #35's include mechanism, DUT first."""
        self._write_design(".subckt cell a b\nr1 a b 1k\n.ends\n")
        tb = testbench.load(
            self._write(
                "x1 in out cell\n",
                {
                    "includes": ["../../design/cell.spice"],
                    "dut_netlist": "sim/smoke-bias/testbench/smoke_bias.spice",
                },
            )
        )
        self.assertEqual(
            [p.name for p in tb.design_netlists], ["smoke_bias.spice", "cell.spice"]
        )
        entries = tb.include_provenance(self.dir.resolve())
        self.assertEqual(
            [e["path"] for e in entries],
            ["sim/smoke-bias/testbench/smoke_bias.spice", "design/cell.spice"],
        )
        prov = tb.provenance(self.dir.resolve())
        # The record can still tell which of the includes is the DUT, and the
        # DUT's own entry is the first of the include list (not a duplicate).
        self.assertEqual(prov["dut_netlist"], "sim/smoke-bias/testbench/smoke_bias.spice")
        self.assertEqual(prov["includes"][0]["path"], prov["dut_netlist"])
        self.assertEqual(prov["includes"][0]["sha256"], tb.dut_netlist_sha256)
        self.assertEqual(len(prov["includes"]), 2)

    def test_a_file_named_as_both_dut_and_include_is_included_once(self):
        tb = testbench.load(
            self._write(
                "x1 in out cell\n",
                {
                    "includes": [str(SIM_DIR / "smoke-bias" / "testbench" / "smoke_bias.spice")],
                    "dut_netlist": "sim/smoke-bias/testbench/smoke_bias.spice",
                },
            )
        )
        self.assertEqual(len(tb.design_netlists), 1)
        self.assertEqual(tb.design_netlists[0], tb.dut_netlist)

    def test_a_dut_netlist_carrying_end_is_rejected_like_any_include(self):
        """#35's forbidden-directive check applies to the DUT too."""
        design = self.dir / "design"
        design.mkdir(parents=True, exist_ok=True)
        (design / "bad_dut.spice").write_text(".subckt dut a b\nr1 a b 1k\n.ends\n.end\n")
        with self.assertRaises(ValueError) as ctx:
            testbench.load(
                self._write(
                    "x1 in out dut\n",
                    {"dut_netlist": str((design / "bad_dut.spice").resolve())},
                )
            )
        self.assertIn("included design netlist", str(ctx.exception))

    def _rejects(self, checks, *needles):
        tb_dir = self._write("v1 out 0 dc {vdd_val}\n", {"checks": checks})
        with self.assertRaises(ValueError) as ctx:
            testbench.load(tb_dir)
        msg = str(ctx.exception)
        self.assertIn("tb.json", msg)
        for needle in needles:
            self.assertIn(needle, msg)

    def test_check_with_unknown_target_is_rejected(self):
        self._rejects({"typo": {"max": 1}}, "typo")

    def test_check_with_unknown_operator_is_rejected(self):
        self._rejects({"vout": {"maximum": 1}}, "vout", "maximum")

    def test_check_with_malformed_definition_is_rejected(self):
        self._rejects({"vout": 1.0}, "vout")
        self._rejects({"vout": [1.0]}, "vout")

    def test_check_with_no_bound_is_rejected(self):
        self._rejects({"vout": {}}, "vout")
        self._rejects({"vout": {"description": "only prose"}}, "vout")

    def test_check_with_non_finite_or_non_numeric_limit_is_rejected(self):
        for bad in (float("nan"), float("inf"), "1.0", None, True):
            with self.subTest(bad=bad):
                self._rejects({"vout": {"max": bad}}, "vout", "max")

    def test_valid_checks_load_unchanged(self):
        checks = {
            "vout": {
                "min": 1.0,
                "max": 2,
                "max_spread_pct": 5.0,
                "min_spread_pct": 0.0,
                "description": "note",
            }
        }
        tb = testbench.load(self._write("v1 out 0 dc {vdd_val}\n", {"checks": checks}))
        self.assertEqual(tb.checks, checks)
        tb = testbench.load(self._write("v1 out 0 dc {vdd_val}\n", {"checks": {}}))
        self.assertEqual(tb.checks, {})

    def test_every_repo_manifest_loads(self):
        for exp in testbench.discover(SIM_DIR):
            with self.subTest(exp=exp.name):
                testbench.load(exp)

    def test_evaluate_checks_rejects_unknown_keys_on_direct_testbenches(self):
        with self.assertRaises(ValueError):
            report.evaluate_checks({"v": {"maximum": 1}}, [], {})

    def test_the_repo_smoke_testbench_is_valid(self):
        tb = testbench.load(SIM_DIR / "smoke-bias")
        self.assertEqual(tb.nominal_supply_v, 3.3)
        self.assertEqual(tb.experiment, "smoke-bias")
        self.assertIn("vbe", tb.measure)
        self.assertIn("vbe", tb.checks)
        # The smoke test is harness self-verification, not a load-dependent
        # claim -- sim/README.md requires it to say so, not just omit the field.
        self.assertIn("note", tb.operating_conditions)
        self.assertIn("N/A", tb.operating_conditions["note"])


class DeckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "tb").mkdir()
        (root / "tb" / "x.spice").write_text("v1 out 0 dc {vdd_val}\n")
        (root / "tb" / "tb.json").write_text(
            json.dumps(
                {
                    "name": "x",
                    "netlist": "x.spice",
                    "measure": {"vout": "v(out)", "iq": "-i(v1)"},
                    "params": {"cload": "1p"},
                    "options": ["reltol=1e-5"],
                }
            )
        )
        self.tb = testbench.load(root / "tb")
        self.pdk = fake_pdk(root / "gf180mcuD")
        self.point = corners.build_grid(corners.resolve_corners(["ss"]), (125,), [3.63])[0]
        self.deck = runner.compose_deck(self.tb, self.pdk, self.point)

    def test_deck_sets_the_pvt_point(self):
        self.assertIn(".param vdd_val=3.63", self.deck)
        self.assertIn(".param vdd_nom=3.3", self.deck)
        self.assertIn(".temp 125", self.deck)

    def test_deck_includes_design_switches_before_model_sections(self):
        design_at = self.deck.index("design.ngspice")
        lib_at = self.deck.index("sm141064.ngspice")
        self.assertLess(design_at, lib_at)

    def test_deck_selects_every_section_of_the_corner(self):
        for section in self.point.corner.sections:
            self.assertIn(f'sm141064.ngspice" {section}', self.deck)

    def test_deck_carries_manifest_params_and_options(self):
        self.assertIn(".param cload=1p", self.deck)
        self.assertIn(".options reltol=1e-5", self.deck)

    def test_deck_pins_model_bin_selection(self):
        """#214 / DR-0025: bin selection must not be a host property.

        gf180mcu bins on the per-finger width; the pass device (`W=2800u
        nf=40`) resolves to a declared bin only when ngspice divides W by NF,
        which is `wnflag`, which is off by default. Without the card in the
        deck the setting comes from whichever host's `~/.spiceinit` is in
        play -- and a host that does not have it cannot run any deck in this
        repo that instantiates the pass device at all.
        """
        self.assertIn(".options wnflag=1", self.deck)

    def test_model_bin_pin_precedes_every_design_include(self):
        """The card has to be parsed before the devices it governs."""
        self.assertLess(
            self.deck.index(".options wnflag=1"), self.deck.index("x.spice")
        )

    def test_model_bin_pin_is_the_first_options_card(self):
        """Earliest-wins: the pin has to precede every manifest `.options`.

        ngspice keeps the FIRST card for a duplicate `.options` key and
        silently discards later ones (measured on ngspice-46 -- pinned by
        `sim/tests/test_ngspice_options_precedence.py`). Emitting the
        harness pin first is therefore what makes it authoritative, not a
        cosmetic choice: this ordering is load-bearing.
        """
        pin_at = self.deck.index(f".options {runner.MODEL_BINNING_OPTION}")
        for option in self.tb.options:
            self.assertLess(pin_at, self.deck.index(f".options {option}"))

    def test_manifest_cannot_silently_redefine_the_model_bin_pin(self):
        """A manifest `wnflag=` card is rejected, not silently ignored.

        Because ngspice keeps the first card, a manifest `.options wnflag=0`
        placed after the harness pin would have no effect at all and print no
        warning -- the "silently wrong" outcome DR-0025 exists to remove. The
        harness fails loud at deck composition instead.
        """
        for bad in ("wnflag=0", "WNFLAG = 0", "wnflag=1"):
            with self.subTest(option=bad):
                tb = dataclasses.replace(self.tb, options=(bad, "reltol=1e-5"))
                with self.assertRaises(ValueError) as ctx:
                    runner.compose_deck(tb, self.pdk, self.point)
                self.assertIn("wnflag", str(ctx.exception))
                self.assertIn(".spiceinit", str(ctx.exception))

    def test_deck_emits_one_measurement_vector_per_measure_entry(self):
        self.assertIn("let m_vout = v(out)", self.deck)
        self.assertIn("let m_iq = -i(v1)", self.deck)
        self.assertIn("print m_vout", self.deck)
        self.assertTrue(self.deck.rstrip().endswith(".end"))

    def test_deck_omits_nodeset_when_manifest_has_none(self):
        self.assertNotIn(".nodeset", self.deck)


class DeckNodesetTests(unittest.TestCase):
    """#40: ``.nodeset`` bias hints for a closed-loop DUT's initial guess."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "tb").mkdir()
        (root / "tb" / "x.spice").write_text("v1 out 0 dc {vdd_val}\n")
        (root / "tb" / "tb.json").write_text(
            json.dumps(
                {
                    "name": "x",
                    "netlist": "x.spice",
                    "measure": {"vout": "v(out)"},
                    "nodeset": {"vout": "1.8", "loop": "0.7"},
                }
            )
        )
        tb = testbench.load(root / "tb")
        pdk = fake_pdk(root / "gf180mcuD")
        point = corners.build_grid(corners.resolve_corners(["tt"]), (27,), [3.3])[0]
        self.deck = runner.compose_deck(tb, pdk, point)

    def test_deck_renders_one_nodeset_directive_with_every_hint(self):
        self.assertIn(".nodeset v(vout)=1.8 v(loop)=0.7", self.deck)

    def test_nodeset_precedes_the_design_includes(self):
        nodeset_at = self.deck.index(".nodeset")
        fragment_at = self.deck.index("x.spice")
        self.assertLess(nodeset_at, fragment_at)


class DeckIncludeTests(unittest.TestCase):
    """`dut_netlist` (#12) + `includes` (#35) in one deck.

    The manifest here names both: a DUT (the cell under test) and a
    supporting design cell it instantiates. Both must reach the deck as
    harness-owned ``.include`` lines ahead of the stimulus fragment, and both
    must be frozen into the record's single netlist snapshot.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "design").mkdir()
        self.cell = (root / "design" / "cell.spice").resolve()
        self.cell.write_text(".subckt cell a b\nr1 a b 1k\n.ends\n")
        self.dut = (root / "dut.spice").resolve()
        self.dut.write_text(".subckt dut_sub a b\nXc a b cell\n.ends\n")
        (root / "tb").mkdir()
        (root / "tb" / "stim.spice").write_text(
            "Vin vin 0 dc {vdd_val}\nXdut vin out dut_sub\n"
        )
        (root / "tb" / "tb.json").write_text(
            json.dumps(
                {
                    "name": "x",
                    "netlist": "stim.spice",
                    "includes": ["../design/cell.spice"],
                    "dut_netlist": str(self.dut),
                    "measure": {"vout": "v(out)"},
                }
            )
        )
        self.root = root
        self.tb = testbench.load(root / "tb")
        self.pdk = fake_pdk(root / "gf180mcuD")
        self.point = corners.build_grid(corners.resolve_corners(["tt"]), (27,), [3.3])[0]

    def test_dut_and_design_cell_are_both_included_before_the_fragment(self):
        deck = runner.compose_deck(self.tb, self.pdk, self.point)
        self.assertIn(f'.include "{self.dut}"', deck)
        self.assertIn(f'.include "{self.cell}"', deck)
        frag_at = deck.index("stim.spice")
        self.assertLess(deck.index(str(self.dut)), frag_at)
        self.assertLess(deck.index(str(self.cell)), frag_at)
        # DUT first, then the supporting design cells, in include order.
        self.assertLess(deck.index(str(self.dut)), deck.index(str(self.cell)))

    def test_snapshot_freezes_the_dut_the_design_cell_and_the_fragment(self):
        experiment_dir = self.root / "tb"  # stands in for sim/<slug>/
        path = report.write_netlist_snapshot(self.tb, experiment_dir, "20260731-000000-abc1234")
        text = path.read_text()
        self.assertIn(".subckt dut_sub", text)     # the DUT
        self.assertIn("r1 a b 1k", text)           # the design cell
        self.assertIn("Xdut vin out dut_sub", text)  # the testbench fragment
        self.assertLess(text.index(".subckt dut_sub"), text.index("r1 a b 1k"))
        self.assertLess(text.index("r1 a b 1k"), text.index("Xdut vin out dut_sub"))
        self.assertIn("DUT netlist", text)
        self.assertIn("included design cell", text)
        self.assertIn(self.tb.dut_netlist_sha256, text)
        self.assertIn(self.tb.netlist_sha256, text)

    def _fragment_chunk(self, text):
        marker = "* testbench fragment   :"
        rule = "* " + "=" * 70 + "\n"
        start = text.index(marker)
        body_at = text.index(rule, start) + len(rule)
        return text[start:body_at], text[body_at:]

    def _check_snapshot_hashes(self, stim):
        import hashlib
        (self.root / "tb" / "stim.spice").write_text(stim)
        tb = testbench.load(self.root / "tb")
        path = report.write_netlist_snapshot(tb, self.root / "tb", "20260731-000001-abc1234")
        header, body = self._fragment_chunk(path.read_text())
        self.assertIn(f"* sha256 (committed)   : {tb.netlist_sha256}", header)
        rendered = re.search(r"\* sha256 \(rendered\)    : (\w+)", header).group(1)
        self.assertEqual(rendered, hashlib.sha256(body.encode()).hexdigest())
        self.assertNotIn("verbatim", path.read_text())
        return tb.netlist_sha256, rendered

    def test_snapshot_rendered_sha_matches_body_with_sink_token(self):
        committed, rendered = self._check_snapshot_hashes(
            "Vin vin 0 dc {vdd_val}\n@BLOAD@\nXdut vin out dut_sub\n"
        )
        self.assertNotEqual(committed, rendered)

    def test_snapshot_rendered_sha_equals_committed_without_token(self):
        committed, rendered = self._check_snapshot_hashes(
            "Vin vin 0 dc {vdd_val}\nXdut vin out dut_sub\n"
        )
        self.assertEqual(committed, rendered)


class TokenGuardTests(unittest.TestCase):
    """#827: every simulator boundary rejects a surviving @TOKEN@."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_compose_deck_rejects_unrendered_fragment(self):
        (self.root / "tb").mkdir()
        (self.root / "tb" / "stim.spice").write_text("Bload out 0 @BLOAD@\n")
        (self.root / "tb" / "tb.json").write_text(
            json.dumps({"name": "x", "netlist": "stim.spice", "measure": {"v": "v(out)"}})
        )
        tb = testbench.load(self.root / "tb")
        pdk = fake_pdk(self.root / "gf180mcuD")
        point = corners.build_grid(corners.resolve_corners(["tt"]), (27,), [3.3])[0]
        raw = tb.netlist.read_text()
        with unittest.mock.patch.object(testbench.Testbench, "fragment_text", return_value=raw):
            with self.assertRaises(SystemExit) as cm:
                runner.compose_deck(tb, pdk, point)
        self.assertIn("BLOAD", str(cm.exception))

    def test_run_ngspice_deck_rejects_before_spawning(self):
        deck_path = self.root / "d.spice"
        deck_path.write_text("Bload out 0 @BLOAD@\n.end\n")
        with unittest.mock.patch("subprocess.run") as run:
            with self.assertRaises(SystemExit):
                runner.run_ngspice_deck(deck_path, self.root / "d.log", self.root)
        run.assert_not_called()

    def test_print_curve_log_rejects_before_writing_or_spawning(self):
        from harness import loop_margin
        deck_path = self.root / "c.spice"
        with unittest.mock.patch("subprocess.run") as run:
            with self.assertRaises(SystemExit):
                loop_margin.print_curve_log("Bload out 0 @BLOAD@\n", "h", self.root / "c.log", deck_path)
        run.assert_not_called()
        self.assertFalse(deck_path.exists())

    def test_bare_at_syntax_passes_print_curve_log(self):
        from harness import loop_margin
        proc = unittest.mock.Mock(returncode=0, stdout="", stderr="")
        with unittest.mock.patch("subprocess.run", return_value=proc):
            loop_margin.print_curve_log("alter @Vinj[acmag] = 1\n", "h", self.root / "c.log",
                                        self.root / "c.spice")
        self.assertTrue((self.root / "c.spice").exists())


class ParseTests(unittest.TestCase):
    def test_parses_print_output(self):
        text = "\n".join(
            [
                "Circuit: * x",
                "m_vout = 1.2003456789e+00",
                "m_iq = -4.5e-05",
                "v(other) = 9.9",
                "m_bad = not_a_number",
            ]
        )
        self.assertEqual(
            runner.parse_measurements_checked(text)[0],
            {"vout": 1.2003456789, "iq": -4.5e-05},
        )


#: Header ngspice prints ahead of the analysis, reused by the fixtures below
#: so they look like a real log rather than a bare phrase list.
_NGSPICE_PREAMBLE = "\n".join(
    [
        "",
        "Note: Compatibility modes selected: hs a",
        "",
        "Circuit: * quiescent-current @ ss_-40c_2.97v -- generated by sim/harness",
        "",
        "Doing analysis at TEMP = -40.000000 and TNOM = 27.000000",
        "",
        "Using SPARSE 1.3 as Direct Linear Solver",
        " Reference value :  0.00000e+00",
        "No. of Data Rows : 1",
        "m_vout_full_v = 1.7994810807e+00",
        "Note: Simulation executed from .control section ",
        "",
    ]
)


class DcPathClassificationTests(unittest.TestCase):
    """#301: which rung of ngspice's DC continuation ladder a corner used.

    No ngspice and no PDK: every case is a canned log. The phrases these
    assert on are ngspice's own, and ``test_the_committed_corpus_still_...``
    below pins them against real committed evidence so a phrase change in a
    future ngspice cannot rot the classifier silently.
    """

    def _log(self, *ladder_lines: str) -> str:
        return _NGSPICE_PREAMBLE + "\n".join(ladder_lines) + "\n"

    def test_no_ladder_phrases_is_the_first_guess_newton_solve(self):
        path = runner.classify_dc_path(self._log())
        self.assertEqual(runner.RUNG_DIRECT, path.rung)
        self.assertEqual({}, path.completions)
        self.assertEqual(0, path.ladder_entries)

    def test_dynamic_gmin_stepping(self):
        path = runner.classify_dc_path(
            self._log(
                "Note: Starting dynamic gmin stepping",
                "Note: Dynamic gmin stepping completed",
            )
        )
        self.assertEqual("dynamic-gmin", path.rung)
        self.assertEqual({"dynamic-gmin": 1}, path.completions)
        self.assertEqual(1, path.ladder_entries)

    def test_true_gmin_stepping(self):
        path = runner.classify_dc_path(
            self._log(
                "Note: Starting dynamic gmin stepping",
                "Warning: Dynamic gmin stepping failed",
                "Note: Starting true gmin stepping",
                "Note: True gmin stepping completed",
            )
        )
        self.assertEqual("true-gmin", path.rung)

    def test_source_stepping(self):
        path = runner.classify_dc_path(
            self._log(
                "Note: Starting dynamic gmin stepping",
                "Warning: Dynamic gmin stepping failed",
                "Note: Starting true gmin stepping",
                "Warning: True gmin stepping failed",
                "Note: Starting source stepping",
                "Note: Source stepping completed",
            )
        )
        self.assertEqual("source-stepping", path.rung)

    def test_last_resort_pseudo_transient_op(self):
        path = runner.classify_dc_path(
            self._log(
                "Note: Starting dynamic gmin stepping",
                "Warning: Dynamic gmin stepping failed",
                "Note: Starting true gmin stepping",
                "Warning: True gmin stepping failed",
                "Note: Starting source stepping",
                "Warning: source stepping failed",
                "Note: Transient op started",
                "Note: Transient op finished successfully",
            )
        )
        self.assertEqual("pseudo-transient", path.rung)

    def test_every_rung_failing_is_not_reported_as_a_rung(self):
        """The ladder ran out: that is 'no DC solution', not 'direct'."""
        path = runner.classify_dc_path(
            self._log(
                "Note: Starting dynamic gmin stepping",
                "Warning: Dynamic gmin stepping failed",
                "Note: Starting true gmin stepping",
                "Warning: True gmin stepping failed",
                "Note: Starting source stepping",
                "Warning: source stepping failed",
            )
        )
        self.assertEqual(runner.RUNG_NO_SOLUTION, path.rung)
        self.assertEqual({}, path.completions)
        self.assertEqual(1, path.ladder_entries)

    def test_missing_output_is_unknown_not_direct(self):
        """A timeout leaves no log; 'we never looked' must not read as 'clean'."""
        for missing in (None, ""):
            with self.subTest(text=missing):
                self.assertEqual(
                    runner.RUNG_UNKNOWN, runner.classify_dc_path(missing).rung
                )

    def test_notes_glued_onto_a_stdout_line_are_still_seen(self):
        """ngspice writes these notes to stderr and the analysis to stdout.

        The two interleave mid-line in the real corpus -- e.g.
        ``" Reference value :  0.00000e+00Note: Starting dynamic gmin
        stepping"`` -- so the classifier must match on substrings, never on
        line-anchored patterns.
        """
        glued = (
            " Reference value :  0.00000e+00Note: Starting dynamic gmin stepping\n"
            "Note: Dynamic gmin stepping completed\n"
        )
        self.assertEqual("dynamic-gmin", runner.classify_dc_path(glued).rung)

    def test_a_sweep_with_many_solves_reports_the_deepest_rung(self):
        """One `dc` sweep log holds one ladder per swept point.

        A corner that needs source stepping at a single swept point is as
        numerically marginal as one that needs it everywhere, so the deepest
        rung is the summary -- but the per-rung tally is kept so the two are
        still distinguishable.
        """
        text = self._log(
            "Note: Starting dynamic gmin stepping",
            "Note: Dynamic gmin stepping completed",
            "Note: Starting dynamic gmin stepping",
            "Note: Dynamic gmin stepping completed",
            "Note: Starting dynamic gmin stepping",
            "Warning: Dynamic gmin stepping failed",
            "Note: Starting true gmin stepping",
            "Warning: True gmin stepping failed",
            "Note: Starting source stepping",
            "Note: Source stepping completed",
        )
        path = runner.classify_dc_path(text)
        self.assertEqual("source-stepping", path.rung)
        self.assertEqual({"dynamic-gmin": 2, "source-stepping": 1}, path.completions)
        self.assertEqual(3, path.ladder_entries)

    def test_as_dict_is_record_shaped(self):
        path = runner.classify_dc_path(
            self._log(
                "Note: Starting dynamic gmin stepping",
                "Note: Dynamic gmin stepping completed",
            )
        )
        self.assertEqual(
            {
                "rung": "dynamic-gmin",
                "completions": {"dynamic-gmin": 1},
                "ladder_entries": 1,
            },
            path.as_dict(),
        )

    def test_the_committed_corpus_still_matches_these_phrases(self):
        """Pin the phrase list against real, already-committed ngspice output.

        Every phrase in ``CONTINUATION_LADDER`` is asserted to occur in at
        least one committed corner log under ``sim/*/corners/``. If a future
        ngspice reworded one, this fails loudly instead of quietly
        reclassifying every corner as ``direct``.
        """
        corpus = list((SIM_DIR).glob("*/corners/*/*.log"))
        self.assertTrue(corpus, "no committed corner logs to pin against")
        blob = "\n".join(p.read_text(errors="replace") for p in corpus).lower()
        for name, phrase in runner.CONTINUATION_LADDER:
            with self.subTest(rung=name):
                self.assertIn(phrase.lower(), blob)
        self.assertIn(runner.LADDER_ENTRY_PHRASE.lower(), blob)

    def test_two_committed_logs_classify_as_the_rungs_they_show(self):
        """End-to-end over real evidence, not a fixture the test wrote itself.

        ``20260918-190801-8a59d23`` is a committed ``quiescent-current``
        record whose ``ss_-40c_2.97v`` log shows the full descent to source
        stepping while its ``tt_27c_3.30v`` log stops at dynamic gmin -- the
        exact asymmetry issue #301 is about.
        """
        base = SIM_DIR / "quiescent-current" / "corners" / "20260918-190801-8a59d23"
        cases = {
            "ss_-40c_2.97v.log": "source-stepping",
            "tt_27c_3.30v.log": "dynamic-gmin",
        }
        for name, expected in cases.items():
            log = base / name
            if not log.is_file():  # pragma: no cover - record removed upstream
                self.skipTest(f"{log} is not committed any more")
            with self.subTest(log=name):
                self.assertEqual(
                    expected, runner.classify_dc_path(log.read_text()).rung
                )


class DcPathCensusAndRenderingTests(unittest.TestCase):
    """#301: the grid-level census and its per-corner record column."""

    def _results(self, rungs: list[str]) -> list:
        points = corners.build_grid(
            corners.resolve_corners(["tt"]), (-40, 27, 125), [3.3]
        )
        # One point per requested rung; the grid above supplies the ids.
        self.assertLessEqual(len(rungs), len(points))
        return [
            runner.PointResult(
                point=point,
                status="ok",
                measurements={"vout": 1.0},
                dc_path=runner.DcPath(rung, {rung: 1} if rung != "direct" else {}, 0),
            )
            for point, rung in zip(points, rungs)
        ]

    def test_census_counts_by_rung_in_ladder_order(self):
        census = report.dc_path_census(
            self._results(["source-stepping", "direct", "direct"])
        )
        self.assertEqual(
            ["direct", "source-stepping"], list(census["by_rung"])
        )
        self.assertEqual({"direct": 2, "source-stepping": 1}, census["by_rung"])
        self.assertEqual("source-stepping", census["deepest"])

    def test_census_of_an_all_direct_grid(self):
        census = report.dc_path_census(self._results(["direct", "direct"]))
        self.assertEqual({"direct": 2}, census["by_rung"])
        self.assertEqual("direct", census["deepest"])

    def test_census_of_an_empty_grid_is_unknown_not_a_crash(self):
        census = report.dc_path_census([])
        self.assertEqual({}, census["by_rung"])
        self.assertEqual(runner.RUNG_UNKNOWN, census["deepest"])

    def _render(self, rungs: list[str]) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        tb_dir = root / "smoke-bias" / "testbench"
        tb_dir.mkdir(parents=True)
        (tb_dir / "x.spice").write_text("* stub\n")
        (tb_dir / "tb.json").write_text(
            json.dumps(
                {
                    "name": "smoke-bias",
                    "netlist": "x.spice",
                    "measure": {"vout": "v(out)"},
                }
            )
        )
        tb = testbench.load(tb_dir)
        results = self._results(rungs)
        record = report.build_record(
            tb=tb,
            pdk=fake_pdk(root / "gf180mcuD"),
            points=[r.point for r in results],
            results=results,
            ngspice="ngspice-46",
            repo_root=SIM_DIR,
            record_id="20260923-120000-abc1234",
            started_utc="2026-09-23T12:00:00+00:00",
            wall_seconds=1.0,
            subset_reason="unit test",
        )
        return report.render_record(record, "smoke-bias")

    def test_every_corner_row_carries_a_dc_path_cell(self):
        text = self._render(["direct", "true-gmin", "pseudo-transient"])
        header = next(
            ln for ln in text.splitlines() if ln.strip().startswith("| corner-id |")
        )
        cols = [c.strip() for c in header.strip().strip("|").split("|")]
        self.assertIn("dc path", cols)
        idx = cols.index("dc path")

        seen = []
        corner_id = re.compile(r"^`[a-z0-9_]+_-?\d+c_[\d.]+v`$")
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("| `"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) != len(cols) or not corner_id.match(cells[0]):
                continue
            seen.append(cells[idx])
        self.assertEqual(["direct", "true-gmin", "pseudo-transient"], seen)

    def test_the_census_block_is_rendered_with_the_deepest_rung(self):
        text = self._render(["direct", "direct", "source-stepping"])
        self.assertIn("DC solve path (ngspice continuation ladder, issue #301)", text)
        self.assertIn("`direct`: 2 corner(s)", text)
        self.assertIn("`source-stepping`: 1 corner(s)", text)
        self.assertIn("Deepest rung used anywhere on this grid: `source-stepping`", text)

    def test_an_all_direct_grid_says_so_explicitly(self):
        text = self._render(["direct", "direct"])
        self.assertIn("Every corner converged on the first-guess Newton pass", text)

    def test_a_multi_solve_corner_shows_its_ladder_entry_count(self):
        """A `dc` sweep's cell distinguishes one marginal point from many."""
        self.assertEqual(
            "source-stepping (x47)",
            report._dc_path_cell(
                {"rung": "source-stepping", "completions": {}, "ladder_entries": 47}
            ),
        )
        self.assertEqual(
            "direct", report._dc_path_cell({"rung": "direct", "ladder_entries": 0})
        )
        self.assertEqual(runner.RUNG_UNKNOWN, report._dc_path_cell(None))


#: The exact ladder-exhaustion tail of the committed evidence log issue #310
#: cites (sim/quiescent-current/corners/20260915-234352-077e15b/
#: ss_-40c_2.97v.log), reused by the gate tests below so their fixtures are
#: ngspice's own phrasing, not a paraphrase.
_LADDER_EXHAUSTION_TAIL = "\n".join(
    [
        "Note: Starting dynamic gmin stepping",
        "Warning: Dynamic gmin stepping failed",
        "Note: Starting true gmin stepping",
        "Warning: True gmin stepping failed",
        "Note: Starting source stepping",
        "Warning: source stepping failed",
        "Note: Transient op started",
        "Note: Transient op finished successfully",
    ]
)


def _gate_log(extra: str = "") -> str:
    """A log that parses as a successful corner AND exhausted the ladder.

    The point of the fixture is that both facts hold at once: ngspice
    exited 0, the measurement line is present and well-formed, and the
    operating point it came from is still not a DC solution -- the exact
    silent-failure shape issue #310 is about.
    """
    return _NGSPICE_PREAMBLE + _LADDER_EXHAUSTION_TAIL + f"\n{extra}\n"


class LadderExhaustionGateTests(unittest.TestCase):
    """#310: the pseudo-transient `op` rung fails a DC-solve corner loudly,
    and the same phrases in a legitimate `.tran` bench's log do not.

    Both affected code paths are covered in both directions:
    :func:`runner.run_ngspice_deck` (the sweep benches) and
    :func:`runner.run_point` (the generic corner-grid path). No ngspice and
    no PDK -- the gate is pure log parsing, so the ngspice invocation is
    mocked with canned output shaped like the committed evidence.
    """

    def test_transient_analysis_detection_spells(self):
        runs = [
            "tran 1u 9m",
            "  tran 20n 400u uic",
            ".tran 1u 6m",
            "  .tran 20n 400u",
        ]
        for text in runs:
            with self.subTest(line=text.strip()):
                self.assertTrue(runner._runs_transient_analysis(text))

    def test_non_transient_statements_are_not_transient_analyses(self):
        """`.meas tran ...` begins with the meas keyword, not `tran` -- the
        one spelling a naive `tran` substring search would trip on."""
        not_runs = [
            "op",
            "  op",
            "dc Vsup 2.97 3.63 0.66",
            "ac dec 20 10 10meg",
            "meas tran vmin_load MIN v(vout) FROM=51u TO=71u",
            "  meas tran bg_pp_light PP v(xdut_light.bg) FROM=0.2m TO=0.3m",
            ".meas tran vpeak_full MAX v(vout_full) FROM=1u TO=6m",
            "set units=degrees",
            "",
        ]
        for text in not_runs:
            with self.subTest(line=text.strip() or "(empty)"):
                self.assertFalse(runner._runs_transient_analysis(text))

    def test_detection_scans_every_source_not_just_the_first(self):
        """run_point passes one line per source; a tran buried mid-manifest
        must still exempt the bench."""
        self.assertTrue(
            runner._runs_transient_analysis("op", "ac dec 20 10 10meg", "tran 1u 1m")
        )


class RunNgspiceDeckLadderGateTests(unittest.TestCase):
    """#310, code path 1: the shared sweep-deck wrapper."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workdir = Path(self.tmp.name)

    def _deck(self, analysis_lines: list[str]) -> Path:
        deck = self.workdir / "deck.spice"
        deck.write_text(
            "\n".join(
                [
                    "* issue #310 gate fixture",
                    "r1 a 0 1k",
                    "v1 a 0 dc 1",
                    ".control",
                    *analysis_lines,
                    'echo "SWEEP COMPLETE"',
                    ".endc",
                    ".end",
                ]
            )
            + "\n"
        )
        return deck

    def _run(self, deck: Path, stdout: str):
        proc = unittest.mock.Mock(returncode=0, stdout=stdout, stderr="")
        log = self.workdir / "deck.log"
        with unittest.mock.patch("subprocess.run", return_value=proc):
            return runner.run_ngspice_deck(deck, log, self.workdir)

    def test_an_op_deck_with_the_phrases_raises(self):
        deck = self._deck(["op", "print v(a)"])
        with self.assertRaises(RuntimeError) as ctx:
            self._run(deck, _gate_log() + 'echo "SWEEP COMPLETE"\n')
        self.assertIn("pseudo-transient", str(ctx.exception))

    def test_a_dc_sweep_deck_with_the_phrases_raises(self):
        """A `dc` sweep solves an operating point per swept point; a
        pseudo-transient rung at any of them poisons the record the same
        way (three of the four benches named in issue #310's corpus sweep
        are `dc` benches)."""
        deck = self._deck(["dc Vsup 2.97 3.63 0.66"])
        with self.assertRaises(RuntimeError):
            self._run(deck, _gate_log() + 'echo "SWEEP COMPLETE"\n')

    def test_a_tran_deck_with_the_same_phrases_does_not_raise(self):
        """The analysis-kind gate: a `.tran` bench's initial-time-point
        solve walks the same ladder legitimately."""
        deck = self._deck(["tran 1u 9m", "meas tran vpp PP v(a) FROM=1u TO=9m"])
        text = self._run(deck, _gate_log() + 'echo "SWEEP COMPLETE"\n')
        self.assertIn("Transient op finished successfully", text)

    def test_an_op_deck_without_the_phrases_does_not_raise(self):
        """Negative control: a ladder that stopped at source stepping (or
        never entered) is not fatal -- that is #301's marginality signal,
        not #310's broken-evidence one."""
        deck = self._deck(["op", "print v(a)"])
        clean = _NGSPICE_PREAMBLE + "\n".join(
            [
                "Note: Starting dynamic gmin stepping",
                "Warning: Dynamic gmin stepping failed",
                "Note: Starting true gmin stepping",
                "Warning: True gmin stepping failed",
                "Note: Starting source stepping",
                "Note: Source stepping completed",
            ]
        )
        text = self._run(deck, clean + '\necho "SWEEP COMPLETE"\n')
        self.assertIn("Source stepping completed", text)


class RunPointLadderGateTests(unittest.TestCase):
    """#310, code path 2: the generic corner-grid path quiescent-current
    uses -- the bench that had no fatal-log check of any kind before."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.pdk = fake_pdk(self.dir / "pdk-variant")
        self.workdir = self.dir / "work"

    def _tb(self, analyses: list[str]) -> "testbench.Testbench":
        tb_dir = self.dir / "gate-experiment" / "testbench"
        tb_dir.mkdir(parents=True, exist_ok=True)
        (tb_dir / "x.spice").write_text("v1 out 0 dc {vdd_val}\n")
        (tb_dir / "tb.json").write_text(
            json.dumps(
                {
                    "name": "x",
                    "netlist": "x.spice",
                    "analyses": analyses,
                    "measure": {"vout": "v(out)"},
                }
            )
        )
        return testbench.load(tb_dir)

    def _point(self):
        return corners.build_grid(
            corners.resolve_corners(["tt"]), (-40.0,), [3.3]
        )[0]

    def _run(self, tb, stdout: str) -> "runner.PointResult":
        proc = unittest.mock.Mock(returncode=0, stdout=stdout, stderr="")
        with unittest.mock.patch("subprocess.run", return_value=proc):
            return runner.run_point(tb, self.pdk, self._point(), self.workdir)

    def test_an_op_corner_whose_measurements_parsed_still_fails(self):
        """The core #310 repro: exit 0, `m_vout` present and well-formed,
        and an operating point that is not a DC solution. The old code
        recorded this as status=ok; the gate must fail it."""
        result = self._run(self._tb(["op"]), _gate_log("m_vout = 1.234e+00"))
        self.assertEqual("failed", result.status)
        self.assertIn("pseudo-transient", result.message)
        # The measurement is still reported for diagnosis, and the #301
        # attribution agrees the corner sat on the pseudo-transient rung.
        self.assertEqual(1.234, result.measurements["vout"])
        self.assertEqual([], result.missing)
        self.assertEqual("pseudo-transient", result.dc_path.rung)

    def test_a_tran_corner_with_the_same_phrases_stays_ok(self):
        result = self._run(
            self._tb(["tran 1u 9m", "meas tran vpp PP v(out) FROM=1u TO=9m"]),
            _gate_log("m_vout = 1.234e+00"),
        )
        self.assertEqual("ok", result.status)
        self.assertEqual([], result.missing)

    def test_the_gate_fires_before_the_missing_measurement_check(self):
        """When both defects hold, the diagnosis must name the root cause
        (a non-DC snapshot), not the symptom (nothing parsed)."""
        result = self._run(self._tb(["op"]), _gate_log())
        self.assertEqual("failed", result.status)
        self.assertIn("pseudo-transient", result.message)

    def test_420_overflowed_required_measurement_fails_the_point(self):
        """`m_vout = 1e999` parses to inf; the point must not be ok."""
        result = self._run(
            self._tb(["tran 1u 9m", "meas tran vpp PP v(out) FROM=1u TO=9m"]),
            _gate_log("m_vout = 1e999"),
        )
        self.assertEqual("failed", result.status)
        self.assertIn("non-finite", result.message)
        self.assertIn("vout", result.message)
        self.assertIn(result.log, result.message)
        self.assertNotIn("vout", result.measurements)

    def _run_proc(self, tb, stdout, stderr="", returncode=0):
        proc = unittest.mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)
        with unittest.mock.patch("subprocess.run", return_value=proc):
            return runner.run_point(tb, self.pdk, self._point(), self.workdir)

    def test_409_timeout_stays_error_and_keeps_partial_output(self):
        """A timeout is ERROR (never ok), parses no measurements even if the
        partial output contains a well-formed `m_` line, and the partial
        ngspice output survives in the log for diagnosis (issue #409)."""
        import subprocess

        exc = subprocess.TimeoutExpired(
            cmd="ngspice",
            timeout=7,
            output=b"m_vout = 1.8\nPartial transient noise\n",
            stderr="Note: Starting dynamic gmin stepping",
        )
        with unittest.mock.patch("subprocess.run", side_effect=exc):
            result = runner.run_point(
                self._tb(["op"]), self.pdk, self._point(), self.workdir, timeout_s=7
            )
        self.assertEqual("error", result.status)
        self.assertEqual({}, result.measurements)
        self.assertIn("timed out after 7s", result.message)
        log = (self.workdir / result.log).read_text()
        self.assertTrue(log.startswith("TIMEOUT after 7s\n"))
        self.assertIn("Partial transient noise", log)
        self.assertIn("dynamic gmin stepping", log)

    def test_409_timeout_without_partial_output_is_bare_marker(self):
        import subprocess

        exc = subprocess.TimeoutExpired(cmd="ngspice", timeout=7)
        with unittest.mock.patch("subprocess.run", side_effect=exc):
            result = runner.run_point(
                self._tb(["op"]), self.pdk, self._point(), self.workdir, timeout_s=7
            )
        self.assertEqual("error", result.status)
        self.assertEqual("TIMEOUT after 7s\n", (self.workdir / result.log).read_text())

    def test_406_clean_control_stays_ok(self):
        result = self._run_proc(self._tb(["op"]), "m_vout = 1.8\n")
        self.assertEqual("ok", result.status)

    def test_406_nonzero_exit_with_complete_measurements_fails(self):
        result = self._run_proc(self._tb(["op"]), "m_vout = 1.8\n", returncode=1)
        self.assertEqual("failed", result.status)
        self.assertIn("exited 1", result.message)
        self.assertEqual(1.8, result.measurements["vout"])
        self.assertEqual([], result.missing)
        self.assertIsNotNone(result.dc_path)
        self.assertTrue((self.workdir / result.log).is_file())

    def test_406_fatal_log_with_complete_measurements_fails(self):
        result = self._run_proc(
            self._tb(["op"]),
            "m_vout = 1.8\nFatal error: Simulation interrupted\n",
        )
        self.assertEqual("failed", result.status)
        self.assertIn("fatal", result.message)
        self.assertEqual(1.8, result.measurements["vout"])

    def test_406_undefined_vector_on_stdout_fails(self):
        result = self._run_proc(
            self._tb(["op"]), 'm_vout = 1.8\nError: RHS "v(missing)" invalid\n'
        )
        self.assertEqual("failed", result.status)
        self.assertIn("does not exist", result.message)

    def test_406_diagnostics_on_stderr_fail(self):
        tb = self._tb(["op"])
        for err in (
            'Error: RHS "v(missing)" invalid\n',
            "Fatal error: Simulation interrupted\n",
        ):
            with self.subTest(err=err):
                result = self._run_proc(tb, "m_vout = 1.8\n", stderr=err)
                self.assertEqual("failed", result.status)

    def test_406_tran_bench_still_checked_for_exit_status(self):
        tb = self._tb(["tran 1u 9m", "meas tran vpp PP v(out) FROM=1u TO=9m"])
        result = self._run_proc(tb, "m_vout = 1.8\n", returncode=2)
        self.assertEqual("failed", result.status)

    def test_406_generic_deck_needs_no_sweep_marker(self):
        result = self._run_proc(self._tb(["op"]), "m_vout = 1.8\n")
        self.assertEqual("ok", result.status)
        self.assertNotIn("SWEEP COMPLETE", "m_vout = 1.8\n")

    def test_the_committed_evidence_log_now_fails_loudly(self):
        """Issue #310's own manual-verification step, replayed: the exact
        committed log the issue cites must trip the gate. Read in isolation
        -- the record itself is append-only evidence and is not touched."""
        log = (
            SIM_DIR
            / "quiescent-current"
            / "corners"
            / "20260915-234352-077e15b"
            / "ss_-40c_2.97v.log"
        )
        if not log.is_file():  # pragma: no cover - record removed upstream
            self.skipTest(f"{log} is not committed any more")
        offenders = runner._ladder_exhaustion_lines(log.read_text(errors="replace"))
        self.assertTrue(
            offenders, "the committed #310 evidence log no longer shows the rung"
        )

    def test_the_committed_corpus_still_matches_these_phrases(self):
        """Pin the gate's phrases against real committed ngspice output, the
        same way DcPathClassificationTests pins the ladder's -- if a future
        ngspice reworded one, this fails loudly instead of quietly passing
        every pseudo-transient corner."""
        corpus = list(SIM_DIR.glob("*/corners/*/*.log"))
        self.assertTrue(corpus, "no committed corner logs to pin against")
        blob = "\n".join(p.read_text(errors="replace") for p in corpus).lower()
        for phrase in ("transient op", "source stepping failed"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, blob)


class PvtLogTests(unittest.TestCase):
    """#161: the shared read_measurements/report_minmax/report_flag helpers
    consolidated out of current-limit/enable-shutdown/soft-start's three
    independently-drifted summarize.py copies."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        log = self.dir / name
        log.write_text(text)
        return log

    def test_parses_the_ngspice_print_line_shape(self):
        log = self._write("a.log", "m_vout = 1.799202e+00\nm_iq = -4.5e-05\n")
        self.assertEqual(
            read_measurements(log, ["m_vout", "m_iq"]),
            {"m_vout": 1.799202e00, "m_iq": -4.5e-05},
        )

    def test_ignores_trailing_targ_trig_at_context_on_a_meas_line(self):
        """soft-start's .meas TRIG/TARG lines print extra tokens after the
        first `=`-delimited value on the same line; only that first token is
        the measurement."""
        log = self._write(
            "a.log", "m_t_startup         =  4.24466e-03 targ=  4.34504e-03 trig=  1.00386e-04\n"
        )
        self.assertEqual(read_measurements(log, ["m_t_startup"]), {"m_t_startup": 4.24466e-03})

    def test_missing_scalar_is_a_fatal_systemexit(self):
        log = self._write("a.log", "m_vout = 1.8\n")
        with self.assertRaises(SystemExit) as ctx:
            read_measurements(log, ["m_vout", "m_iq"])
        self.assertIn("is missing measurements", str(ctx.exception))
        self.assertIn("m_iq", str(ctx.exception))

    def test_a_malformed_value_fails_loud_not_silently(self):
        """current-limit's pre-#161 parser raised an uncaught traceback on a
        malformed value; enable-shutdown/soft-start's pre-#161 parser
        silently dropped it (surfacing only as a misleading "missing
        measurement"). The shared helper does neither: it raises a named,
        catchable SystemExit identifying the bad value."""
        log = self._write("a.log", "m_vout = 1.-e+3\n")
        with self.assertRaises(SystemExit) as ctx:
            read_measurements(log, ["m_vout"])
        self.assertIn("unparsable value", str(ctx.exception))
        self.assertIn("m_vout", str(ctx.exception))
        self.assertIn("1.-e+3", str(ctx.exception))

    def test_report_minmax_prints_the_extremes_with_the_requested_width(self):
        rows = [("a", {"m_x": 1.0}), ("b", {"m_x": 3.0}), ("c", {"m_x": 2.0})]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report_minmax(rows, "m_x", val_width=6, val_prec=2)
        out = buf.getvalue()
        self.assertIn("min", out)
        self.assertIn("1.00", out)
        self.assertIn("@ a", out)
        self.assertIn("max", out)
        self.assertIn("3.00", out)
        self.assertIn("@ b", out)

    def test_report_minmax_applies_scale_and_unit(self):
        rows = [("a", {"m_t": 1e-3}), ("b", {"m_t": 2e-3})]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report_minmax(rows, "m_t", scale=1e3, unit="ms")
        out = buf.getvalue()
        self.assertIn("1.0000ms", out)
        self.assertIn("2.0000ms", out)

    def test_report_flag_lists_only_the_matching_corners(self):
        rows = [("a", {"m_v": 1.0}), ("b", {"m_v": 5.0}), ("c", {"m_v": 9.0})]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report_flag(rows, "over 4:", lambda v: v["m_v"] > 4.0)
        out = buf.getvalue()
        self.assertIn("'b'", out)
        self.assertIn("'c'", out)
        self.assertNotIn("'a'", out)

    def test_report_flag_reports_none_when_nothing_matches(self):
        rows = [("a", {"m_v": 1.0})]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report_flag(rows, "never:", lambda v: v["m_v"] > 4.0)
        self.assertIn("none", buf.getvalue())

    def test_report_flag_truncates_past_max_shown(self):
        """soft-start's already-generalized flag() truncates past 6; #161
        applies that uniformly (enable-shutdown's pre-#161 copy lacked it)."""
        rows = [(f"c{i}", {"m_v": 9.0}) for i in range(9)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report_flag(rows, "all bad:", lambda v: True, max_shown=6)
        out = buf.getvalue()
        self.assertIn("+3 more", out)
        self.assertNotIn("'c8'", out)


class TestComplianceLimitedLoadSinks(unittest.TestCase):
    """#46: every deck that replaced its ideal current sink with a
    compliance-limited behavioural sink must also *check* that the sink
    actually delivered the commanded current.

    The compliance bound is what deletes the unphysical sub-ground DC root
    (see sim/harness/README.md, "Compliance-limited load sinks"). It is only
    sound while the bound never engages on a real operating point -- and the
    only thing that turns "it never engages" from an assumption into evidence
    is a per-corner check on the delivered current. These assertions exist so
    a future edit cannot quietly drop that check and leave the records
    asserting an unverified property.
    """

    SIM = SIM_DIR

    # A behavioural current source (B-element) whose expression contains the
    # tanh() compliance factor -- i.e. the sink documented in
    # sim/harness/README.md, "Compliance-limited load sinks".
    COMPLIANCE_SINK = re.compile(r"(?mi)^B\w+\s+.*\bI\s*=.*tanh\(")

    def _decks_with_compliance_sinks(self):
        for manifest in sorted(self.SIM.glob("*/testbench/tb.json")):
            tb = json.loads(manifest.read_text())
            # The sink card is a rendered hole in the deck (#637), not typed text.
            text = load_sink.render((manifest.parent / tb["netlist"]).read_text())
            if self.COMPLIANCE_SINK.search(text):
                yield manifest, tb, text

    def test_at_least_the_five_known_decks_use_a_compliance_limited_sink(self):
        slugs = {m.parents[1].name for m, _, _ in self._decks_with_compliance_sinks()}
        self.assertLessEqual(
            {
                "load-regulation",
                "line-regulation",
                "load-transient",
                "psrr-vs-freq",
                "quiescent-current",
            },
            slugs,
        )

    def test_every_compliance_sink_deck_measures_the_delivered_current(self):
        for manifest, tb, _ in self._decks_with_compliance_sinks():
            with self.subTest(manifest.parents[1].name):
                measured = {
                    name
                    for name, expr in tb.get("measure", {}).items()
                    if "vlmeas" in expr.lower() or "iload_plateau" in expr.lower()
                }
                self.assertTrue(
                    measured,
                    "no measure reads the ammeter in series with the compliance-limited sink",
                )

    def test_every_compliance_sink_deck_checks_the_delivered_current(self):
        for manifest, tb, _ in self._decks_with_compliance_sinks():
            with self.subTest(manifest.parents[1].name):
                measure = tb.get("measure", {})
                checked = {
                    name
                    for name in tb.get("checks", {})
                    if "vlmeas" in measure.get(name, "").lower()
                    or "iload_plateau" in measure.get(name, "").lower()
                }
                self.assertTrue(
                    checked,
                    "the delivered load current is measured but never checked -- the "
                    "record would assert the sink stayed ideal without evidence",
                )

    def test_no_compliance_sink_deck_still_carries_an_ideal_sink(self):
        for manifest, _, text in self._decks_with_compliance_sinks():
            with self.subTest(manifest.parents[1].name):
                stray = [
                    line
                    for line in text.splitlines()
                    if line[:1].upper() == "I" and not line.startswith("*")
                ]
                self.assertEqual([], stray, "an ideal current-source load survived the fix")

    def test_dropout_vs_load_keeps_its_nodeset_hint(self):
        """#40's single-instance .op deck is deliberately NOT converted."""
        tb = json.loads((self.SIM / "dropout-vs-load" / "testbench" / "tb.json").read_text())
        self.assertIn("nodeset", tb)
        self.assertIn("vout", {k.lower() for k in tb["nodeset"]})


class TestDropoutMeasuresTheRegulationKnee(unittest.TestCase):
    """#138 / DR-0020: dropout is the headroom at the regulation knee.

    The original manifest measured ``vdrop_mv = (v(vin) - v(vout))*1e3`` at a
    single fixed supply, Vin = 2.10 V. Because 2.10 V *is* 1.800 V + 300 mV,
    that expression is identically ``300 mV + (1.800 V - Vout)`` whenever the
    regulator is still in regulation -- so it reports the DC regulation error
    offset by exactly the bound, never the dropout voltage, and it can only
    read below 300 mV if Vout sits *above* its own setpoint. A negative
    feedback loop with finite DC gain cannot do that, which is why the metric
    FAILed 27/27 corners by 0.476-1.014 mV and why no pass-device resize can
    fix it (widening XMpass 4x moves the reading to a 300.574 mV asymptote --
    still above the bound; see DR-0020 for the numbers).

    These assertions pin the corrected methodology so a future edit cannot
    silently regress to a fixed-headroom subtraction -- and, just as
    importantly, they pin the ratified < 300 mV bound itself so the metric
    cannot be "fixed" by relaxing the number instead (CLAUDE.md: agents do not
    relax the ratified spec to make results pass).
    """

    MANIFEST = SIM_DIR / "dropout-vs-load" / "testbench" / "tb.json"

    #: README.md "Output" row: 1.8 V +/-2%. The -2% edge, 1.764 V, is the
    #: out-of-regulation threshold the knee search keys on.
    VOUT_NOM_V = 1.8
    VOUT_MINUS_2PCT_V = 1.764

    def setUp(self):
        self.tb = json.loads(self.MANIFEST.read_text())

    def test_supply_is_swept_rather_than_pinned_at_the_test_point(self):
        analyses = " ".join(self.tb["analyses"]).lower()
        self.assertRegex(
            analyses,
            r"\bdc\s+vsup\b",
            "dropout must be found by sweeping the supply through the "
            "regulation knee, not solved at one pinned headroom",
        )

    def test_vdrop_is_not_a_fixed_headroom_subtraction(self):
        expr = self.tb["measure"]["vdrop_mv"].lower().replace(" ", "")
        self.assertNotIn(
            "v(vin)-v(vout)",
            expr,
            "vdrop_mv = v(vin)-v(vout) at a pinned Vin measures regulation "
            "error offset by the bound, not dropout (#138)",
        )

    def test_knee_threshold_is_the_ratified_minus_two_percent_edge(self):
        analyses = " ".join(self.tb["analyses"]).lower().replace(" ", "")
        self.assertIn(
            f"v(vout)={self.VOUT_MINUS_2PCT_V}",
            analyses,
            "the knee search must key on the ratified -2% accuracy edge "
            f"({self.VOUT_NOM_V} V - 2% = {self.VOUT_MINUS_2PCT_V} V)",
        )
        self.assertAlmostEqual(
            self.VOUT_MINUS_2PCT_V, self.VOUT_NOM_V * 0.98, places=6
        )

    def test_the_ratified_300_mv_bound_is_unchanged(self):
        """The measurement is corrected; the spec number is NOT relaxed."""
        self.assertEqual(300.0, self.tb["checks"]["vdrop_mv"]["max"])

    def test_regulation_at_the_ratified_binding_test_point_is_still_gated(self):
        """DR-0004 note 4's Vin = 2.10 V point survives as its own check.

        Dropout <= 300 mV *means* the part still regulates with 300 mV of
        headroom, so the corrected deck keeps a direct check of that at the
        ratified binding test point rather than dropping it.
        """
        name = "vout_at_210_mv"
        self.assertIn(name, self.tb["measure"])
        self.assertIn("at=2.10", self.tb["measure"][name].lower() + " ".join(
            self.tb["analyses"]
        ).lower().replace(" ", ""))
        check = self.tb["checks"][name]
        self.assertAlmostEqual(1764.0, check["min"], places=3)
        self.assertAlmostEqual(1836.0, check["max"], places=3)

    def test_the_knee_crossing_is_gated_as_unique(self):
        """#138: a swept knee is only as good as the sweep is well-behaved.

        A single sweep point that lands on the #40 non-physical fixed point
        (pass device off, Vout collapsed) inserts a spurious pair of 1.764 V
        crossings above the real knee, and ``FALL=1`` then interpolates a
        knee at the artifact instead of at the regulation knee. Measured:
        widening ``XMpass`` to ``W=8000u nf=160`` makes exactly one point
        (Vin = 2.09 V, tt / 27 C) do this, and the reading becomes
        330.901 mV instead of the true 49.1 mV.

        So the deck locates the crossing twice -- first and last -- and gates
        the difference at zero. Every corner of the shipped netlist crosses
        exactly once (knee_uniqueness_mv = 0.000 at 27/27), and the guard
        reads 281.84 mV on the 4x netlist above.
        """
        analyses = " ".join(self.tb["analyses"]).lower().replace(" ", "")
        # The sweep direction is #472's: rising from deep dropout, so the
        # knee is the RISE crossing; FALL is accepted for a falling sweep.
        direction = "rise" if "rise=1" in analyses else "fall"
        self.assertIn(
            f"{direction}=1",
            analyses,
            "the knee must be located at the FIRST crossing",
        )
        self.assertIn(
            f"{direction}=last",
            analyses,
            "the knee must ALSO be located at the LAST crossing, so "
            "a spurious crossing pair is detectable (#138)",
        )

        name = "knee_uniqueness_mv"
        self.assertIn(
            name,
            self.tb["measure"],
            "the first-vs-last knee difference must be a reported "
            "measurement, not an unrecorded internal",
        )
        check = self.tb["checks"][name]
        # Zero-width window: any second crossing at all is a failure. The
        # sweep step is 5 mV, so a real artifact shows up as tens or
        # hundreds of mV, never as float noise.
        self.assertLessEqual(check["max"], 0.001)
        self.assertGreaterEqual(check["min"], -0.001)

    def test_the_recorded_evidence_passes_the_uniqueness_guard(self):
        """The live record must actually exercise the guard, not just declare it.

        Guards that never appear in a record are guards nobody has run. Parse
        the newest dropout record and require a ``knee_uniqueness_mv`` column
        in which every corner either reads zero or is graded FAIL -- otherwise
        the recorded dropout numbers could be artifact interpolations and no
        test would notice. (A corner that trips the guard is evidence the
        guard works, as long as the record does not let it pass; #467.)
        """
        records = sorted((SIM_DIR / "dropout-vs-load" / "records").glob("*.md"))
        self.assertTrue(records, "no dropout-vs-load records committed")
        text = records[-1].read_text()

        header = next(
            (ln for ln in text.splitlines() if ln.strip().startswith("| corner-id |")),
            None,
        )
        self.assertIsNotNone(header, f"no result table in {records[-1].name}")
        cols = [c.strip() for c in header.strip().strip("|").split("|")]
        self.assertIn(
            "knee_uniqueness_mv",
            cols,
            f"{records[-1].name} predates the #138 uniqueness guard",
        )
        idx = cols.index("knee_uniqueness_mv")
        self.assertIn("pass/fail", cols, f"{records[-1].name} has no pass/fail column")
        verdict_idx = cols.index("pass/fail")

        # Only the per-corner rows of the result table: the spread table that
        # follows has the same column count and also quotes corner-ids, so key
        # on the first cell being nothing but a corner-id.
        corner_id = re.compile(r"^`[a-z0-9_]+_-?\d+c_[\d.]+v`$")
        rows = 0
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("| `"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) != len(cols) or not corner_id.match(cells[0]):
                continue
            rows += 1
            if float(cells[idx]) != 0.0:
                self.assertTrue(
                    cells[verdict_idx].startswith("FAIL"),
                    f"{records[-1].name}: {cells[0]} crossed the -2% edge more "
                    "than once -- its dropout number may be an artifact, and "
                    f"the record grades it {cells[verdict_idx]!r}, not FAIL",
                )
        self.assertGreaterEqual(rows, 27, "expected the 27-point PVT grid")


class TestStartupDeckStaysResistivelyLoaded(unittest.TestCase):
    """#46: sim/startup/ is immune to the artifact because it loads
    resistively and starts genuinely disabled. Guard both properties."""

    def test_startup_loads_are_resistors_not_current_sinks(self):
        text = (SIM_DIR / "startup" / "testbench" / "tb_startup.spice").read_text()
        body = [ln for ln in text.splitlines() if ln and not ln.startswith("*")]
        self.assertTrue([ln for ln in body if ln.startswith("Rload_")])
        self.assertEqual([], [ln for ln in body if ln[:1].upper() == "I"])

    def test_startup_enable_ramps_from_a_disabled_state(self):
        text = (SIM_DIR / "startup" / "testbench" / "tb_startup.spice").read_text()
        self.assertRegex(text, r"(?m)^Ven EN 0 PULSE\(0 ")


class KltGridTests(unittest.TestCase):
    """Retry policy shared by the loop-sweep klt drivers (issue #492)."""

    MISS = "no DC branch"

    def drive(self, outcomes, retry_outcomes, bad=(), void_on_miss=False):
        events, retried = [], []

        def parse(key, results, suffix):
            table = retry_outcomes if suffix else outcomes
            err = table[key]
            return ([] if err else [f"row-{key}{suffix}"]), err

        def run_retry(key):
            retried.append(key)
            return None, ["boom"] if key in retry_problem_keys else []

        retry_problem_keys = {k for k, v in retry_outcomes.items() if v == "PROB"}
        out = klt_grid.run_retry_grid(
            list(outcomes), None, set(bad), parse=parse, run_retry=run_retry,
            miss_marker=self.MISS, name=str, bad_key=lambda k: k, bad_message="bad",
            retry_problem=lambda err, probs: err or "; ".join(probs),
            say=lambda k, ev, d: events.append((k, ev, d)),
            report=lambda k, rows, note: events.append((k, "ok", note)),
            void_on_miss=void_on_miss)
        return out, events, retried

    def test_clean_miss_error_bad_and_seeded_paths(self):
        (rows, failures, seeded, voided), events, retried = self.drive(
            {"a": None, "b": self.MISS, "c": "other", "d": None},
            {"b": None}, bad={"d"})
        self.assertEqual(rows, ["row-a", "row-b_dcseed"])
        self.assertEqual(failures, ["c: other", "d: bad"])
        self.assertEqual(seeded, ["b"])
        self.assertEqual(voided, [])
        self.assertEqual(retried, ["b"])
        self.assertEqual(events, [
            ("a", "ok", ""), ("b", "retry", ""), ("c", "error", "other"),
            ("d", "error", "bad"), ("b", "ok", "  [DC seed]")])

    def test_bad_unit_is_never_retried_even_on_a_miss_message(self):
        (_, failures, _, _), _, retried = self.drive({"a": self.MISS}, {}, bad={"a"})
        self.assertEqual(failures, ["a: bad"])
        self.assertEqual(retried, [])

    def test_seeded_miss_is_voided_only_when_enabled(self):
        outs, retry = {"a": self.MISS}, {"a": self.MISS}
        (_, failures, _, voided), _, _ = self.drive(outs, retry, void_on_miss=True)
        self.assertEqual((failures, voided), ([], [f"a: {self.MISS}"]))
        (_, failures, _, voided), _, _ = self.drive(outs, retry)
        self.assertEqual((failures, voided), ([f"a (with DC seed): {self.MISS}"], []))

    def test_retry_problem_overrides_a_clean_parse(self):
        (rows, failures, seeded, _), _, _ = self.drive(
            {"a": self.MISS}, {"a": "PROB"})
        self.assertEqual((rows, seeded), ([], []))
        self.assertEqual(failures, ["a (with DC seed): PROB"])

    def test_select_backend(self):
        self.assertEqual(klt_grid.select_backend(None, 1), ("local", False))
        self.assertEqual(klt_grid.select_backend(None, 4), ("batch", True))
        self.assertEqual(klt_grid.select_backend("klt-local", 1), ("klt-local", True))
        self.assertEqual(klt_grid.select_backend("local", 4), ("local", False))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(klt_grid.select_backend("klt-local", 4))
        self.assertIn("FATAL: --backend klt-local", err.getvalue())


class LocalGridCliTests(unittest.TestCase):
    """One definition of the local-grid CLI block and the #366 cap (issue #621).

    ``--backend``/``--in-flight``/``-j``/``--no-write``/``--subset-reason``/
    ``--supersedes`` were registered in both loop sweeps, and their help text
    had drifted apart in four places; ``DEFAULT_JOBS`` was a per-file constant,
    so #366's cap reached two of the five drivers that fan ngspice out locally
    and left the other three at 4 and 8. These assertions are what keeps both
    halves single-definition: a sixth driver (or a re-copied block) fails here
    rather than quietly running wide on a shared dispatch worker.
    """

    #: Every driver that fans ngspice out on this host itself, or passes ``-j``
    #: straight through to one that does. ``harness/cli.py`` is
    #: ``run_corners.py`` (issue #626): its effective default used to live at
    #: the resolution site rather than the registration site, so it also
    #: needs the resolution-site assertions below.
    LOCAL_DRIVERS = (
        "loop-stability/testbench/sweep.py",
        "soft-start-loop-gain/testbench/sweep.py",
        "soft-start/testbench/handover_t15.py",
        "soft-start/testbench/ramp_ab.py",
        "toolchain-portability/testbench/ab_loop_stability.py",
        "harness/cli.py",
    )

    #: A ``-j`` registration ends where the driver's next argument begins:
    #: the testbench drivers add theirs on ``ap``, ``run_corners.py`` on
    #: ``parser`` (issue #626). Accept both followers, or the guard goes
    #: vacuous for ``harness/cli.py`` again.
    JOBS_RE = re.compile(
        r"""add_argument\(\s*["']-j["']\s*,\s*["']--jobs["'](.*?)\n\s*(?:ap|parser)\.""",
        re.S)

    GRID_FLAGS = ("--backend", "--in-flight", "--jobs", "--no-write",
                  "--subset-reason", "--supersedes")

    def test_default_jobs_is_capped_for_shared_dispatch_workers(self):
        self.assertEqual(klt_grid.DEFAULT_JOBS, min(2, os.cpu_count() or 2))
        self.assertLessEqual(klt_grid.DEFAULT_JOBS, 2)
        # ``or 2`` guards a None cpu_count and a 1-core host caps at its own
        # count: the default is never below 1 (issue #626 edge case).
        self.assertGreaterEqual(klt_grid.DEFAULT_JOBS, 1)

    def test_add_grid_args_registers_the_whole_shared_block(self):
        ap = argparse.ArgumentParser()
        klt_grid.add_grid_args(ap, batch_unit="(load, C_eff, ESR) configuration")
        args = ap.parse_args([])
        self.assertEqual(
            (args.backend, args.in_flight, args.jobs, args.no_write,
             args.subset_reason, args.supersedes),
            (None, 6, klt_grid.DEFAULT_JOBS, False, "", ""))
        for flag in self.GRID_FLAGS:
            self.assertIn(flag, ap.format_help())
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                ap.parse_args(["--backend", "nonesuch"])

    def test_the_four_drifted_help_strings_have_one_wording(self):
        ap = argparse.ArgumentParser()
        klt_grid.add_grid_args(ap, batch_unit="(load, C_eff, ESR) configuration")
        text = " ".join(ap.format_help().split())
        # --backend keeps the superset attribution, not either file's half.
        self.assertIn("where the grid runs (issues #366, #451)", text)
        self.assertIn("how many configuration requests are submitted at once", text)
        self.assertIn("if the PVT grid is narrower than the CLAUDE.md-mandated "
                      "matrix", text)
        # --supersedes was a bare `default=""` with no help in one copy.
        self.assertIn("record-id this run supersedes", text)

    def test_batch_unit_and_extra_are_the_only_per_bench_clauses(self):
        ap = argparse.ArgumentParser()
        klt_grid.add_grid_args(
            ap, batch_unit="(variant, phase, C_eff, ESR) configuration",
            batch_extra=", and the DC hand-over transfer is one `op` request "
                        "per variant")
        text = " ".join(ap.format_help().split())
        self.assertIn("each (variant, phase, C_eff, ESR) configuration is a "
                      "`klt sim` request", text)
        self.assertIn("(klt_run.py), and the DC hand-over transfer is one `op` "
                      "request per variant -- the default", text)

    def test_the_loop_sweeps_register_the_block_through_the_harness(self):
        for rel in self.LOCAL_DRIVERS[:2]:
            with self.subTest(driver=rel):
                src = (SIM_DIR / rel).read_text()
                self.assertIn("klt_grid.add_grid_args(", src)
                for flag in self.GRID_FLAGS:
                    self.assertNotIn(f'ap.add_argument("{flag}"', src)

    def test_every_local_driver_takes_its_jobs_default_from_klt_grid(self):
        for rel in self.LOCAL_DRIVERS:
            with self.subTest(driver=rel):
                src = (SIM_DIR / rel).read_text()
                self.assertNotRegex(src, r"(?m)^DEFAULT_JOBS\s*=")
                if "klt_grid.add_grid_args(" in src:
                    # Registers the whole shared block through the harness;
                    # its ``-j`` default is asserted behaviorally in
                    # test_add_grid_args_registers_the_whole_shared_block.
                    continue
                # Issue #626: a self-registering driver whose registration
                # JOBS_RE cannot see would pass this guard vacuously -- and
                # it did, for harness/cli.py. Require the match.
                registrations = self.JOBS_RE.findall(src)
                self.assertTrue(
                    registrations, f"JOBS_RE matched no -j registration in {rel}")
                for registration in registrations:
                    self.assertIn("default=klt_grid.DEFAULT_JOBS", registration)
                    self.assertIn("type=int", registration)

    def test_run_corners_default_lives_at_registration_not_resolution(self):
        """``harness/cli.py`` registered ``-j`` with a ``default=0`` sentinel
        and picked the effective value at the resolution site
        (``args.jobs or min(8, ...)``, issue #626) -- invisible to a
        registration-only guard. Both halves must stay gone."""
        src = (SIM_DIR / "harness/cli.py").read_text()
        self.assertNotRegex(src, r"min\(8,")
        self.assertNotIn("args.jobs or", src)

    def test_run_corners_jobs_semantics_after_the_cap(self):
        """``-j 0`` was the pre-#626 "unset" sentinel (``default=0`` plus an
        ``or`` fallback made it mean 8-wide). It now reaches
        ``runner.run_grid``, which runs serially for ``jobs <= 1`` -- a safe
        landing, asserted deliberately rather than left incidental."""
        ap = cli.build_parser()
        self.assertEqual(
            ap.parse_args(["smoke-bias"]).jobs, klt_grid.DEFAULT_JOBS)
        self.assertEqual(ap.parse_args(["smoke-bias", "-j", "8"]).jobs, 8)
        self.assertEqual(ap.parse_args(["smoke-bias", "-j", "0"]).jobs, 0)


class LocalCliRecordScratchCleanupTests(unittest.TestCase):
    """Issue #802: a stored record consumes only its own staged scratch.

    ``sim/.work/.stage/<slug>/`` is shared by every record id of a bench.
    ``cli.run`` used to rmtree the whole bench tree after storing one record,
    which erased a sibling staged run's only copy -- including a batch run
    left pending for a later mint. End to end over ``cli.run`` with the grid
    stubbed and the store faked, per this file's no-PDK/no-ngspice contract.
    """

    SLUG = "line-regulation"
    SIB = "20261121-zz-sibl-0bedeca"

    #: Stubbed measurements, one per ``tb.json`` measure name and inside every
    #: check bound, so the record passes and ``run`` reaches the store and
    #: cleanup path with ``EXIT_OK``.
    MEAS = {
        "vout_1ma_lo": 1.8, "vout_1ma_hi": 1.8, "vout_50ma_lo": 1.8,
        "vout_50ma_hi": 1.8, "line_reg_1ma_mvpv": 1.0, "line_reg_50ma_mvpv": 1.0,
        "iload_err_max_ua": 0.1,
    }

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        # Cleanups run in reverse order: the caller's cwd is restored before
        # the temp repo is deleted, including on failure. Entering the fixture
        # keeps the bare-slug argument resolving against this repo instead of
        # a real bench that happens to sit under the process cwd (#805).
        self.addCleanup(os.chdir, Path.cwd())
        self.repo = Path(td.name).resolve()
        os.chdir(self.repo)
        shutil.copytree(SIM_DIR / self.SLUG / "testbench",
                        self.repo / "sim" / self.SLUG / "testbench")
        self.exp = self.repo / "sim" / self.SLUG
        self.put_objects: dict = {}
        self._patch(cli, "REPO_ROOT", self.repo)
        self._patch(cli, "SIM_DIR", self.repo / "sim")
        self._patch(cli, "WORK_DIR", self.repo / "sim" / ".work")
        self._patch(cli, "STAGE_DIR", self.repo / "sim" / ".work" / ".stage")
        self._patch(cli, "find_pdk", lambda: fake_pdk(self.repo / "pdk"))
        self._patch(runner, "ngspice_version", lambda: "ngspice-46 (stubbed)")
        self._patch(runner, "ngspice_binary_sha256", lambda: "a" * 64)
        self._patch(store_mod, "preflight", lambda *_a, **_k: None)
        self._real_put = store_mod.put_files
        self._patch(store_mod, "put_files", self._fake_store_put)
        self._patch(kr, "REPO", self.repo)
        self._stage_sibling()

    def _patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(lambda: setattr(obj, name, old))

    def _fake_store_put(self, files, root, **_kw):
        return self._real_put(files, root, run=fake_klt(self.put_objects))

    def _stage_sibling(self):
        """A second, batch-run record id staged for the same bench, in the
        layout ``klt_run.py`` leaves behind (same bytes as
        ``test_klt_record.StoreRun._stage``)."""
        corner = ta.stage_corner_dir(self.repo, self.SLUG, self.SIB)
        (corner / "new").mkdir(parents=True, exist_ok=True)
        (corner / "new" / "klt-report.json").write_text(json.dumps(
            {"corner_count": 1, "environment": {"remote": {
                "job_id": "klt-sim-1", "instance_type": "c7i.8xlarge", "state": "done",
                "worker_environment": {"pdk": {"models_staged": True,
                                               "stamp_text": "open_pdks c6d73a3"}}}}}))
        (corner / "new" / "tt_27c_3.30v.log").write_text("ngspice log bytes\n")
        (corner / "summary.csv").write_text(
            "dut,corner,line_reg_pct_per_v,status,diagnostics,pass\n"
            "new,tt_27c_3.30v,0.01,pass,,True\n")

    def _stub_grid(self):
        def grid(tb, pdk, points, workdir, jobs=1, timeout_s=None,
                 on_result=None, log_dir=None):
            log_dir.mkdir(parents=True, exist_ok=True)
            results = []
            for point in points:
                (log_dir / f"{point.corner_id}.log").write_text("stubbed ngspice log\n")
                result = runner.PointResult(
                    point=point, status="ok", measurements=dict(self.MEAS))
                results.append(result)
                if on_result is not None:
                    on_result(result)
            return results
        return grid

    def test_a_stored_record_consumes_only_its_own_scratch(self):
        args = cli.build_parser().parse_args(
            [self.SLUG, "--subset-reason", "two-record staging-cleanup test",
             "-j", "1"])
        with unittest.mock.patch.object(runner, "run_grid", self._stub_grid()), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.run(args), cli.EXIT_OK)
        (rid_md,) = (self.exp / "records").glob("*.md")
        rid = rid_md.stem
        self.assertTrue(
            (self.repo / "manifests/artifacts" / f"{self.SLUG}-{rid}.manifest.json").is_file(),
            "the run never reached the store: the cleanup path was not exercised")
        stage_exp = ta.stage_experiment_dir(self.repo, self.SLUG)
        # The stored record's own scratch is consumed: its corner logs, its
        # netlist snapshot and its staged Markdown record.
        self.assertFalse((stage_exp / report.CORNERS_DIR / rid).exists())
        self.assertFalse((stage_exp / report.SNAPSHOT_DIR / f"{rid}.spice").exists())
        self.assertFalse((stage_exp / report.RECORDS_DIR / f"{rid}.md").exists())
        # The sibling staged batch run survived, and still mints.
        sibling = ta.stage_corner_dir(self.repo, self.SLUG, self.SIB)
        self.assertTrue((sibling / "summary.csv").is_file())
        self.assertTrue((sibling / "new" / "tt_27c_3.30v.log").is_file())
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(kr.main([self.SLUG, "--record-id", self.SIB]), 0)
        self.assertTrue((self.exp / "records" / f"{self.SIB}.md").is_file())


class DeckTemplateTests(unittest.TestCase):
    """`harness.deck` -- the one @TOKEN@ renderer and its guard (issue #592)."""

    def test_every_token_is_substituted(self):
        text = "Vin VIN 0 DC @VIN_V@\n.temp @TEMP_C@\n"
        self.assertEqual(
            deck.render(text, {"VIN_V": "2.97", "TEMP_C": "-40"}),
            "Vin VIN 0 DC 2.97\n.temp -40\n",
        )

    def test_a_token_with_no_substitution_is_fatal(self):
        """The guard this module exists for.

        Eight hand-rolled copies had drifted to three strengths; the two
        narrowest (`@[A-Z_]+@`, `@[A-Z]+@`) would have let `@X1@` -- and in
        one case `@A_B@` -- through to ngspice as literal deck text. One
        pattern, at the strictest strength, catches both.
        """
        with self.assertRaises(SystemExit) as ctx:
            deck.render("Rload @A_B@ @X1@ @ESR@\n", {"ESR": "0.1"})
        self.assertIn("['A_B', 'X1']", str(ctx.exception))
        self.assertNotIn("ESR", str(ctx.exception))

    def test_the_failure_names_the_template_it_came_from(self):
        with self.assertRaisesRegex(SystemExit, "hand-over template has unsub"):
            deck.render("@NOPE@", {}, source="hand-over template")

    def test_it_raises_rather_than_asserts(self):
        """`assert` vanishes under `python -O`; a silently unguarded deck is
        exactly the evidence defect this guard is for."""
        src = Path(deck.__file__).read_text()
        self.assertNotIn("assert ", src)

    def test_a_bare_at_sign_survives(self):
        # ngspice's own syntax: `alter @Vinj[acmag] = 1` is not an @TOKEN@.
        text = "      alter @Vinj[acmag] = 1\n      alter @Iinj[acmag] = 0\n"
        self.assertEqual(deck.render(text, {}), text)
        self.assertEqual(deck.require_substituted(text), text)

    def test_substitution_is_single_pass(self):
        """A substituted *value* is emitted verbatim, never re-scanned --
        so a value cannot smuggle in a token the guard already cleared."""
        self.assertEqual(deck.render("@A@", {"A": "@B@", "B": "x"}), "@B@")

    def test_require_substituted_guards_text_the_driver_assembled(self):
        self.assertEqual(deck.require_substituted("* done\n"), "* done\n")
        with self.assertRaisesRegex(SystemExit, r"\['K'\]"):
            deck.require_substituted("Xi@K@ VOUT 0\n")

    def test_render_file_reads_the_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpl = Path(tmp) / "tb.spice.in"
            tmpl.write_text(".temp @TEMP_C@\n")
            self.assertEqual(deck.render_file(tmpl, {"TEMP_C": "125"}), ".temp 125\n")

    def test_pvt_subs_is_the_block_every_template_shares(self):
        class FakePdk:
            design_include = "/pdk/design.ngspice"
            model_lib = "/pdk/sm141064.ngspice"

        subs = deck.pvt_subs(FakePdk(), corners.CORNERS["ss"], -40.0, 2.97,
                             "design/netlist/ldo_core.spice")
        self.assertEqual(subs, {
            "DESIGN_INCLUDE": "/pdk/design.ngspice",
            "MODEL_LIB": "/pdk/sm141064.ngspice",
            "LDO_NETLIST": "design/netlist/ldo_core.spice",
            "MOS_CORNER": "ss", "RES_CORNER": "res_ss", "BJT_CORNER": "bjt_ss",
            "DIODE_CORNER": "diode_ss", "MOSCAP_CORNER": "moscap_ss",
            "MIMCAP_CORNER": "mimcap_ss",
            "TEMP_C": "-40", "VIN_V": "2.97",
        })
        # Section order is corners.Corner.sections' order, not alphabetical:
        # mixing the six up would silently simulate the wrong corner.
        self.assertEqual(
            tuple(subs[k] for k in ("MOS_CORNER", "RES_CORNER", "BJT_CORNER",
                                    "DIODE_CORNER", "MOSCAP_CORNER", "MIMCAP_CORNER")),
            corners.CORNERS["ss"].sections,
        )


class NetlistFreshnessPreflightTests(unittest.TestCase):
    """`deck.require_fresh_netlists` -- one preflight for four drivers (#592)."""

    def _run(self, returncode, stdout="", stderr=""):
        proc = unittest.mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)
        with unittest.mock.patch("subprocess.run", return_value=proc) as run:
            return deck.require_fresh_netlists(), run

    def test_current_netlists_pass_silently(self):
        result, run = self._run(0)
        self.assertIsNone(result)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(argv[1].endswith("design/netlist.py"))
        self.assertEqual(argv[2], "--check")

    def test_a_stale_netlist_returns_the_whole_diagnostic(self):
        result, _ = self._run(1, stdout="error_amp.spice differs\n", stderr="erc\n")
        self.assertIn("design/netlist.py --check failed", result)
        self.assertIn("error_amp.spice differs", result)
        self.assertIn("erc", result)

    def test_the_message_is_not_scoped_to_one_cell(self):
        """`design/netlist.py --check` verifies every `design/*.sch` cell, so
        naming `ldo_core` alone reported a stale sub-cell under the wrong
        file (the drift this consolidation fixes)."""
        result, _ = self._run(1, stdout="error_amp.spice differs\n")
        self.assertIn("design/netlist/*.spice", result)
        self.assertIn("design/*.sch", result)
        self.assertNotIn("design/ldo_core.sch", result)


if __name__ == "__main__":
    unittest.main()
