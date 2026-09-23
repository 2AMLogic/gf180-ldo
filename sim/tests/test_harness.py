#!/usr/bin/env python3
"""Unit tests for the PVT harness. No PDK and no ngspice required.

    python3 -m unittest discover -s sim/tests -v
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import io
import json
import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import cli, corners, report, runner, testbench  # noqa: E402
from harness.pdk import Pdk, PdkNotFound  # noqa: E402
from harness.pvt_log import (  # noqa: E402
    read_measurements,
    report_flag,
    report_minmax,
)


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
            runner.parse_measurements(text), {"vout": 1.2003456789, "iq": -4.5e-05}
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


class _StubPoint:
    def __init__(self, corner_id):
        self.corner_id = corner_id


class _StubResult:
    def __init__(self, corner_id, measurements, status="ok"):
        self.point = _StubPoint(corner_id)
        self.measurements = measurements
        self.status = status


class ChecksTests(unittest.TestCase):
    def setUp(self):
        self.results = [
            _StubResult("a", {"v": 1.0}),
            _StubResult("b", {"v": 1.2}),
            _StubResult("c", {"v": 0.8}),
        ]
        self.summary = report.summarize(self.results, ["v"])

    def test_summary_finds_the_extremes(self):
        stats = self.summary["v"]
        self.assertEqual((stats["min"], stats["min_at"]), (0.8, "c"))
        self.assertEqual((stats["max"], stats["max_at"]), (1.2, "b"))
        self.assertAlmostEqual(stats["spread_pct"], 40.0)

    def test_min_max_violations_are_reported_with_their_corner(self):
        failures = report.evaluate_checks({"v": {"min": 0.9}}, self.results, self.summary)
        self.assertEqual(len(failures), 1)
        self.assertEqual((failures[0]["kind"], failures[0]["at"]), ("min", "c"))

    def test_max_spread_violation(self):
        failures = report.evaluate_checks(
            {"v": {"max_spread_pct": 10.0}}, self.results, self.summary
        )
        self.assertEqual(failures[0]["kind"], "max_spread_pct")

    def test_min_spread_catches_a_grid_that_never_moved(self):
        flat = [_StubResult("a", {"v": 1.0}), _StubResult("b", {"v": 1.0})]
        summary = report.summarize(flat, ["v"])
        failures = report.evaluate_checks({"v": {"min_spread_pct": 5.0}}, flat, summary)
        self.assertEqual(failures[0]["kind"], "min_spread_pct")
        # ...and the degenerate-grid waiver (issue #253) must NOT swallow it:
        # two samples that happen to be equal is exactly the regression this
        # check exists to catch. The waiver gates on the sample count, never
        # on the observed spread value.
        self.assertEqual(report.waived_checks({"v": {"min_spread_pct": 5.0}}, summary), [])

    def test_a_multi_point_grid_waives_nothing(self):
        self.assertEqual(
            report.waived_checks(
                {"v": {"min_spread_pct": 5.0, "max_spread_pct": 50.0}}, self.summary
            ),
            [],
        )

    def test_passing_checks_produce_no_failures(self):
        self.assertEqual(
            report.evaluate_checks(
                {"v": {"min": 0.5, "max": 1.5, "max_spread_pct": 50.0}},
                self.results,
                self.summary,
            ),
            [],
        )


class DegenerateGridSpreadTests(unittest.TestCase):
    """Issue #253: a spread over a single sample is undefined, not zero.

    ``sim/selftest.sh --quick`` collapses the grid to one tt/27C/nominal
    point. Before this, ``smoke-bias``'s ``min_spread_pct`` floors -- which
    exist to prove ``.temp``/``.lib`` actually move between points -- were
    evaluated against that one point, observed a spread of 0, and failed by
    construction, so ``--quick`` could never pass. A one-point grid must
    instead *waive* grid-level spread checks (and say so), while still
    grading every per-point bound.
    """

    SPEC = {
        "vbe": {"min": 0.35, "max": 0.95, "min_spread_pct": 20.0},
        "vdiv_ratio": {"min": 0.4999, "max": 0.5001, "max_spread_pct": 0.001},
    }

    def setUp(self):
        self.one_point = [_StubResult("tt_27c_3.30v", {"vbe": 0.690436, "vdiv_ratio": 0.5})]
        self.summary = report.summarize(self.one_point, ["vbe", "vdiv_ratio"])

    def test_spread_is_zero_by_construction_on_one_point(self):
        """The precondition: this is why the old evaluation was unsatisfiable."""
        self.assertEqual(self.summary["vbe"]["n"], 1)
        self.assertEqual(self.summary["vbe"]["spread_pct"], 0.0)

    def test_spread_checks_are_not_failed_on_a_one_point_grid(self):
        failures = report.evaluate_checks(self.SPEC, self.one_point, self.summary)
        self.assertEqual(
            [f["kind"] for f in failures],
            [],
            "a one-point grid must not manufacture a min_spread_pct failure",
        )

    def test_spread_checks_are_waived_explicitly_rather_than_silently_passed(self):
        waived = report.waived_checks(self.SPEC, self.summary)
        self.assertEqual(
            {(w["measurement"], w["kind"]) for w in waived},
            {("vbe", "min_spread_pct"), ("vdiv_ratio", "max_spread_pct")},
        )
        for entry in waived:
            self.assertEqual(entry["n"], 1)
            self.assertIn("undefined", entry["reason"])
        # The limits are reported verbatim -- the waiver never relaxes them.
        limits = {w["measurement"]: w["limit"] for w in waived}
        self.assertEqual(limits["vbe"], 20.0)

    def test_per_point_bounds_are_still_graded_on_a_one_point_grid(self):
        """The waiver is scoped to spread only; min/max still fail normally."""
        out_of_band = [_StubResult("tt_27c_3.30v", {"vbe": 1.5, "vdiv_ratio": 0.5})]
        summary = report.summarize(out_of_band, ["vbe", "vdiv_ratio"])
        failures = report.evaluate_checks(self.SPEC, out_of_band, summary)
        self.assertEqual([(f["measurement"], f["kind"]) for f in failures], [("vbe", "max")])

    def test_a_measurement_with_no_spread_spec_is_never_waived(self):
        waived = report.waived_checks({"vbe": {"min": 0.35, "max": 0.95}}, self.summary)
        self.assertEqual(waived, [])


class RecordIdTests(unittest.TestCase):
    def test_record_id_matches_the_ratified_shape(self):
        """sim/README.md: <record-id> is <YYYYMMDD>-<HHMMSS>-<short-git-sha>."""
        when = datetime.datetime(2026, 7, 29, 15, 30, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(report.format_record_id("1a7ef75", when), "20260729-153000-1a7ef75")
        self.assertRegex(
            report.format_record_id("1a7ef75", when), r"^\d{8}-\d{6}-[0-9a-f]{7}$"
        )

    def test_allocation_never_reuses_an_existing_record_id(self):
        when = datetime.datetime(2026, 7, 29, 15, 30, 0, tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            records = Path(tmp)
            first = report.allocate_record_id(SIM_DIR, records, when)
            (records / f"{first}.md").write_text("# first\n")
            second = report.allocate_record_id(SIM_DIR, records, when)
            self.assertNotEqual(first, second)
            self.assertRegex(second, r"^\d{8}-\d{6}-")
            # the existing record was not touched
            self.assertEqual((records / f"{first}.md").read_text(), "# first\n")

    def test_write_record_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "an-experiment"
            (experiment / report.RECORDS_DIR).mkdir(parents=True)
            (experiment / report.RECORDS_DIR / "20260729-153000-abc1234.md").write_text("keep\n")
            with self.assertRaises(report.RecordExists):
                report.write_record(
                    {"record_id": "20260729-153000-abc1234"}, experiment
                )

    def test_write_markdown_record_refuses_to_overwrite(self):
        """The same guard, for drivers that render their own record body."""
        with tempfile.TemporaryDirectory() as tmp:
            records = Path(tmp) / "records"  # created on demand
            path = report.write_markdown_record("20260729-153000-abc1234", "keep\n", records)
            self.assertEqual(path, records / "20260729-153000-abc1234.md")
            with self.assertRaises(report.RecordExists):
                report.write_markdown_record(
                    "20260729-153000-abc1234", "clobber\n", records
                )
            self.assertEqual("keep\n", path.read_text())


class MatrixConformanceTests(unittest.TestCase):
    """sim/README.md requires the full mandated matrix, or a stated reason."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tb_dir = Path(self.tmp.name) / "an-experiment" / "testbench"
        tb_dir.mkdir(parents=True)
        (tb_dir / "x.spice").write_text("v1 out 0 dc {vdd_val}\n")
        (tb_dir / "tb.json").write_text(
            json.dumps({"name": "x", "netlist": "x.spice", "measure": {"vout": "v(out)"}})
        )
        self.tb = testbench.load(tb_dir)

    def _grid(self, corner_names, temps, supplies):
        return corners.build_grid(corners.resolve_corners(corner_names), temps, supplies)

    def test_full_matrix_is_recognised(self):
        grid = self._grid(["mos"], (-40, 27, 125), corners.supply_points(3.3, 0.10))
        self.assertEqual(report.matrix_conformance(self.tb, grid), {"full": True, "missing": []})

    def test_missing_temperature_is_flagged(self):
        grid = self._grid(["mos"], (27,), corners.supply_points(3.3, 0.10))
        result = report.matrix_conformance(self.tb, grid)
        self.assertFalse(result["full"])
        self.assertTrue(any("temperature" in m for m in result["missing"]))

    def test_missing_supply_and_process_are_flagged(self):
        grid = self._grid(["tt"], (-40, 27, 125), [3.3])
        result = report.matrix_conformance(self.tb, grid)
        self.assertFalse(result["full"])
        self.assertTrue(any("supply" in m for m in result["missing"]))
        self.assertTrue(any("process" in m for m in result["missing"]))


class RecordRenderingTests(unittest.TestCase):
    """The rendered record carries exactly the fields sim/README.md lists."""

    RATIFIED_FIELDS = (
        "Record ID",
        "Claim",
        "Netlist provenance",
        "Corner matrix run",
        "Operating conditions",
        "Statistical convention",
        "Result",
        "Links",
        "Timestamp / author",
        "Supersedes",
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        tb_dir = root / "smoke-bias" / "testbench"
        tb_dir.mkdir(parents=True)
        (tb_dir / "x.spice").write_text("v1 out 0 dc {vdd_val}\n")
        (tb_dir / "tb.json").write_text(
            json.dumps(
                {
                    "name": "smoke-bias",
                    "netlist": "x.spice",
                    "measure": {"vout": "v(out)"},
                    "checks": {"vout": {"min": 0.0, "max": 10.0}},
                }
            )
        )
        self.tb = testbench.load(tb_dir)
        self.pdk = fake_pdk(root / "gf180mcuD")
        self.points = corners.build_grid(
            corners.resolve_corners(["mos"]), (-40, 27, 125), corners.supply_points(3.3, 0.10)
        )
        self.results = [
            runner.PointResult(point=p, status="ok", measurements={"vout": 1.0 + i * 0.01})
            for i, p in enumerate(self.points)
        ]
        self.record = report.build_record(
            tb=self.tb,
            pdk=self.pdk,
            points=self.points,
            results=self.results,
            ngspice="ngspice-46",
            repo_root=SIM_DIR,
            record_id="20260729-153000-1a7ef75",
            started_utc="2026-07-29T15:30:00+00:00",
            wall_seconds=9.5,
            claim="spec/ldo.md#example",
        )

    def test_every_ratified_field_is_present_and_in_order(self):
        text = report.render_record(self.record, "smoke-bias")
        positions = []
        for field in self.RATIFIED_FIELDS:
            marker = f"**{field}**"
            self.assertIn(marker, text, f"missing ratified field {field!r}")
            positions.append(text.index(marker))
        self.assertEqual(positions, sorted(positions), "fields are out of ratified order")

    def test_links_point_at_the_ratified_paths(self):
        text = report.render_record(self.record, "smoke-bias")
        self.assertIn("sim/smoke-bias/testbench/x.spice", text)
        self.assertIn("sim/smoke-bias/netlist-snapshots/20260729-153000-1a7ef75.spice", text)
        self.assertIn("sim/smoke-bias/corners/20260729-153000-1a7ef75/", text)

    def test_result_table_uses_corner_ids_and_reports_overall_verdict(self):
        text = report.render_record(self.record, "smoke-bias")
        self.assertIn("`tt_-40c_2.97v`", text)
        self.assertIn("`ff_125c_3.63v`", text)
        self.assertIn("**Overall: PASS**", text)

    def test_a_full_matrix_run_says_so(self):
        text = report.render_record(self.record, "smoke-bias")
        self.assertIn("Full PVT matrix per CLAUDE.md", text)

    def test_environment_section_names_the_real_pdk_provenance(self):
        text = report.render_record(self.record, "smoke-bias")
        provenance = self.pdk.provenance()
        self.assertIn(str(provenance["open_pdks_version"]), text)
        self.assertIn(provenance["variant"], text)
        self.assertNotIn("open_pdks `None`", text)

    def test_git_state_is_taken_from_the_caller_not_resampled(self):
        """The harness dirties the tree by writing logs; provenance is pre-run."""
        pre_run = {"commit": "f" * 40, "short": "fffffff", "branch": "main", "dirty": False}
        env = report.environment(self.pdk, "ngspice-46", SIM_DIR, pre_run)
        self.assertEqual(env["git"], pre_run)

    def test_a_dirty_tree_is_called_out_in_netlist_provenance(self):
        dirty = dict(self.record)
        dirty["environment"] = dict(self.record["environment"])
        dirty["environment"]["git"] = {
            "commit": "f" * 40, "short": "fffffff", "branch": "main", "dirty": True,
        }
        text = report.render_record(dirty, "smoke-bias")
        self.assertIn("dirty working tree", text)

    def test_netlist_snapshot_is_frozen_and_append_only(self):
        experiment = self.tb.experiment_dir
        path = report.write_netlist_snapshot(self.tb, experiment, "20260729-153000-1a7ef75")
        self.assertEqual(path.parent.name, report.SNAPSHOT_DIR)
        self.assertIn("v1 out 0 dc {vdd_val}", path.read_text())
        self.assertIn(self.tb.netlist_sha256, path.read_text())
        with self.assertRaises(report.RecordExists):
            report.write_netlist_snapshot(self.tb, experiment, "20260729-153000-1a7ef75")

    def test_operating_conditions_default_to_an_explicit_not_stated_line(self):
        """sim/README.md: omission is only OK for load-independent claims, and
        the record must say so -- this testbench (no operating_conditions in
        its manifest) exercises the harness default, not smoke-bias's own
        explicit N/A note."""
        text = report.render_record(self.record, "smoke-bias")
        self.assertIn("**Operating conditions**", text)
        self.assertIn("Not stated by the testbench manifest", text)

    def test_operating_conditions_are_rendered_when_present(self):
        record = report.build_record(
            tb=self.tb,
            pdk=self.pdk,
            points=self.points,
            results=self.results,
            ngspice="ngspice-46",
            repo_root=SIM_DIR,
            record_id="20260729-153001-1a7ef75",
            started_utc="2026-07-29T15:30:01+00:00",
            wall_seconds=9.5,
            operating_conditions={
                "load_current": "50mA",
                "output_cap": "1.0uF, ESR=100mOhm",
                "enable_state": "enabled (EN = VIN)",
            },
        )
        text = report.render_record(record, "smoke-bias")
        self.assertIn("Load current: 50mA", text)
        self.assertIn("Output cap: 1.0uF, ESR=100mOhm", text)
        self.assertIn("Enable state: enabled (EN = VIN)", text)

    def test_a_full_grid_record_waives_nothing_and_renders_no_waiver_note(self):
        """Regression guard for issue #253: the full-matrix path is untouched."""
        self.assertEqual(self.record["checks"]["waived"], [])
        self.assertNotIn(
            "NOT evaluated", report.render_record(self.record, "smoke-bias")
        )

    def _one_point_record_with_a_spread_check(self):
        self.tb.checks = {"vout": {"min": 0.0, "max": 10.0, "min_spread_pct": 20.0}}
        points = corners.build_grid(corners.resolve_corners(["tt"]), (27,), (3.3,))
        results = [
            runner.PointResult(point=p, status="ok", measurements={"vout": 1.0})
            for p in points
        ]
        self.assertEqual(len(points), 1)
        return report.build_record(
            tb=self.tb,
            pdk=self.pdk,
            points=points,
            results=results,
            ngspice="ngspice-46",
            repo_root=SIM_DIR,
            record_id="20260729-153002-1a7ef75",
            started_utc="2026-07-29T15:30:02+00:00",
            wall_seconds=0.1,
            subset_reason="single-point harness smoke test, not a spec claim",
        )

    def test_a_one_point_record_passes_instead_of_failing_an_undecidable_spread(self):
        record = self._one_point_record_with_a_spread_check()
        self.assertEqual(record["checks"]["failures"], [])
        self.assertEqual(record["status"], "pass")

    def test_a_one_point_record_states_which_checks_it_could_not_evaluate(self):
        """Not silently passed: the evidence names the ungraded checks."""
        record = self._one_point_record_with_a_spread_check()
        self.assertEqual(
            [(w["measurement"], w["kind"]) for w in record["checks"]["waived"]],
            [("vout", "min_spread_pct")],
        )
        text = report.render_record(record, "smoke-bias")
        self.assertIn("NOT evaluated", text)
        self.assertIn("min_spread_pct", text)
        self.assertIn("not evidence about PVT sensitivity", text)


class DutNetlistProvenanceTests(unittest.TestCase):
    """#12: Netlist provenance reads schematic/extracted from dut_netlist."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "tb").mkdir()
        (self.root / "tb" / "stim.spice").write_text("Vin vin 0 dc {vdd_val}\n")
        self.pdk = fake_pdk(self.root / "gf180mcuD")
        self.points = corners.build_grid(
            corners.resolve_corners(["mos"]), (-40, 27, 125), corners.supply_points(3.3, 0.10)
        )
        self.results = [
            runner.PointResult(point=p, status="ok", measurements={"vout": 1.0})
            for p in self.points
        ]

    def _build(self, dut_netlist_path: Path, dut_rel: str, includes: list[str] | None = None) -> str:
        (self.root / "tb" / "tb.json").write_text(
            json.dumps(
                {
                    "name": "x",
                    "netlist": "stim.spice",
                    "measure": {"vout": "v(out)"},
                    "dut_netlist": str(dut_netlist_path.resolve()),
                    "includes": includes or [],
                }
            )
        )
        tb = testbench.load(self.root / "tb")
        # Swap in the human-facing relative label a real repo-relative
        # manifest value would carry (the test DUT lives outside REPO_ROOT).
        tb.dut_netlist_rel = dut_rel
        record = report.build_record(
            tb=tb,
            pdk=self.pdk,
            points=self.points,
            results=self.results,
            ngspice="ngspice-46",
            repo_root=SIM_DIR,
            record_id="20260801-000000-1234567",
            started_utc="2026-08-01T00:00:00+00:00",
            wall_seconds=1.0,
        )
        return report.render_record(record, "x-experiment")

    def test_a_design_path_reports_schematic(self):
        dut = self.root / "design_dut.spice"
        dut.write_text(".subckt d a b\nRx a b 1k\n.ends\n")
        text = self._build(dut, "design/netlist/ldo_core.spice")
        self.assertIn("schematic (`design/netlist/ldo_core.spice`)", text)
        self.assertIn("DUT netlist: `design/netlist/ldo_core.spice`", text)

    def test_a_layout_path_reports_extracted(self):
        dut = self.root / "layout_dut.spice"
        dut.write_text(".subckt d a b\nRx a b 1k\n.ends\n")
        text = self._build(dut, "layout/extracted/ldo_core.spice")
        self.assertIn("extracted (`layout/extracted/ldo_core.spice`)", text)

    def test_the_dut_and_the_other_design_cells_are_reported_separately(self):
        """#12's DUT line and #35's design-cell lines coexist without dupes."""
        dut = self.root / "design_dut.spice"
        dut.write_text(".subckt d a b\nRx a b 1k\n.ends\n")
        cell = self.root / "cell.spice"
        cell.write_text(".subckt cell a b\nRy a b 2k\n.ends\n")
        text = self._build(dut, "design/netlist/ldo_core.spice", includes=[str(cell)])
        # Provenance names every design netlist frozen into the record ...
        self.assertIn("design/netlist/ldo_core.spice", text)
        self.assertIn("cell.spice", text)
        # ... the Links section calls out which one is the DUT ...
        self.assertIn("DUT netlist: `design/netlist/ldo_core.spice`", text)
        self.assertIn("Design cells: ", text)
        # ... and the DUT is not also listed as a supporting design cell.
        design_cells_line = next(ln for ln in text.splitlines() if "Design cells: " in ln)
        self.assertNotIn("ldo_core.spice", design_cells_line)
        self.assertEqual(text.count("DUT netlist sha256"), 1)
        self.assertEqual(
            len([ln for ln in text.splitlines() if ln.startswith("- Included design netlist")]), 1
        )


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
            text = (manifest.parent / tb["netlist"]).read_text()
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
        self.assertIn(
            "fall=1",
            analyses,
            "the knee must be located at the FIRST falling crossing",
        )
        self.assertIn(
            "fall=last",
            analyses,
            "the knee must ALSO be located at the LAST falling crossing, so "
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
        reading zero at every corner -- otherwise the recorded dropout numbers
        could be artifact interpolations and no test would notice.
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
            self.assertEqual(
                0.0,
                float(cells[idx]),
                f"{records[-1].name}: {cells[0]} crossed the -2% edge more "
                "than once -- its dropout number may be an artifact",
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


class NgspiceBinaryFingerprintTests(unittest.TestCase):
    """Issue #182: the self-reported ``ngspice --version`` banner was found

    insufficient to detect a silent binary content change -- two
    differently-built ``ngspice-46`` binaries on one machine printed the
    identical version string. ``ngspice_binary_sha256()`` fingerprints the
    binary ``ngspice_version()`` resolves via ``PATH``, so a later comparison
    can tell a rebuild from a real change even when the version string does
    not move. Uses a fake executable, not a real ngspice install, per this
    file's own "No PDK and no ngspice required" contract.
    """

    def test_hashes_the_resolved_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_exe = Path(tmp) / "ngspice"
            fake_exe.write_bytes(b"fake ngspice binary content, build A\n")
            with unittest.mock.patch("shutil.which", return_value=str(fake_exe)):
                digest = runner.ngspice_binary_sha256()
            import hashlib
            self.assertEqual(digest, hashlib.sha256(fake_exe.read_bytes()).hexdigest())

    def test_a_content_change_moves_the_hash_even_with_the_same_path(self):
        """The whole point: a rebuild at the same resolved path is detectable."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_exe = Path(tmp) / "ngspice"
            fake_exe.write_bytes(b"fake ngspice binary content, build A\n")
            with unittest.mock.patch("shutil.which", return_value=str(fake_exe)):
                before = runner.ngspice_binary_sha256()
            fake_exe.write_bytes(b"fake ngspice binary content, build B (rebuilt)\n")
            with unittest.mock.patch("shutil.which", return_value=str(fake_exe)):
                after = runner.ngspice_binary_sha256()
            self.assertNotEqual(before, after)

    def test_missing_ngspice_raises_ngspice_missing(self):
        with unittest.mock.patch("shutil.which", return_value=None):
            with self.assertRaises(runner.NgspiceMissing):
                runner.ngspice_binary_sha256()


def fake_ngspice_install(root: Path, version: str = "ngspice-46") -> Path:
    """An executable ``<root>/bin/ngspice`` stub that prints a real banner.

    ``_root_ngspice_version()`` / ``ngspice_version_at()`` (issue #247) decide
    a candidate root's identity by *running* its binary, so a root fixture has
    to be runnable, not just a file on disk.
    """
    exe = root / "bin" / "ngspice"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text(
        "#!/bin/sh\n"
        f"echo '** {version} : Circuit level simulation program'\n"
        "echo '** Compiled with KLU Direct Linear Solver'\n"
    )
    exe.chmod(0o755)
    return exe


class NgspiceProvenanceTests(unittest.TestCase):
    """Issue #184: a version-string match is not enough -- #182 found a
    self-built ``ngspice`` shadowing the Homebrew install
    ``docs/environment-setup.md`` documents, on PATH, ahead of it. These
    cover the identity check that turns that into a loud, actionable
    ``--check-env`` failure instead of a silent "OK".

    Issue #247 extended the check after Homebrew's unversioned ``ngspice``
    formula moved to ngspice-47: the *expected root* can itself drift off the
    pin, and the check must then blame the root rather than the
    correctly-pinned binary it resolved on PATH.
    """

    def _root(self, path: Path, version: str | None = "ngspice-46", source="test"):
        return runner.NgspiceRoot(str(path), source, version)

    def test_resolved_exe_under_expected_root_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew"
            exe = fake_ngspice_install(root)
            # Should not raise.
            runner.verify_ngspice_provenance(str(exe), self._root(root))

    def test_resolved_exe_outside_expected_root_raises_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew"
            shadow_root = Path(tmp) / "local-build"
            fake_ngspice_install(root)
            exe = fake_ngspice_install(shadow_root)
            with self.assertRaises(runner.NgspiceIdentityMismatch) as ctx:
                runner.verify_ngspice_provenance(str(exe), self._root(root))
            message = str(ctx.exception)
            self.assertIn(str(exe), message)
            self.assertIn(str(root), message)
            self.assertIn("GF180_LDO_NGSPICE_ROOT", message)
            # Both sides are the pinned version here: this really IS #182's
            # shadowed-binary case, and must keep saying so.
            self.assertIn("#182 failure mode", message)

    def test_drifted_expected_root_is_blamed_not_the_pinned_binary(self):
        """Issue #247's core repro: Homebrew's unversioned formula moved to
        ngspice-47, so the *root* is off the pin while the binary on PATH is
        the only correctly-pinned ngspice-46 on the host."""
        with tempfile.TemporaryDirectory() as tmp:
            drifted_root = Path(tmp) / "homebrew-47"
            fake_ngspice_install(drifted_root, "ngspice-47")
            pinned_prefix = Path(tmp) / "pinned-46"
            exe = fake_ngspice_install(pinned_prefix, "ngspice-46")
            with self.assertRaises(runner.NgspiceIdentityMismatch) as ctx:
                runner.verify_ngspice_provenance(
                    str(exe),
                    self._root(
                        drifted_root, "ngspice-47", source="brew --prefix ngspice"
                    ),
                )
            message = str(ctx.exception)
            # The diagnosis names the root, not the binary, as the drifted side.
            self.assertIn("ROOT that has drifted", message)
            self.assertNotIn("#182 failure mode", message)
            # And it must not tell the user to adopt the unpinned root.
            self.assertIn("Do NOT 'fix' this by putting that root first", message)
            # The corrective actions it names are the two supported ones.
            self.assertIn(runner.PINNED_HOMEBREW_FORMULA, message)
            # The suggested prefix is symlink-resolved (macOS /var -> /private/var),
            # same as every other path this check prints.
            self.assertIn(
                f"export {runner.NGSPICE_ROOT_ENV}={pinned_prefix.resolve()}", message
            )
            # And it cites why 47 is not simply adoptable.
            self.assertIn("DR-0025", message)
            self.assertIn("DR-0027", message)

    def test_off_pin_binary_fails_even_when_it_lives_under_the_root(self):
        """The other half of #247: a host whose Homebrew ngspice upgraded
        under it resolves an ngspice-47 that really *is* under
        ``brew --prefix ngspice`` -- containment alone would call that OK."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew-47"
            exe = fake_ngspice_install(root, "ngspice-47")
            with self.assertRaises(runner.NgspiceIdentityMismatch) as ctx:
                runner.verify_ngspice_provenance(
                    str(exe), self._root(root, "ngspice-47")
                )
            message = str(ctx.exception)
            self.assertIn("reports ngspice-47", message)
            self.assertIn(f"pins {runner.PINNED_NGSPICE_VERSION}", message)
            self.assertIn("DR-0027", message)

    def test_unrunnable_root_binary_leaves_version_unknown_not_drifted(self):
        """A blessed root we cannot probe (no runnable ``bin/ngspice``) is
        "unknown", never "drifted" -- an unknown version must not fabricate a
        drift diagnosis."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "blessed"
            root.mkdir()
            shadow = Path(tmp) / "elsewhere"
            exe = fake_ngspice_install(shadow)
            candidate = self._root(root, None)
            self.assertFalse(candidate.drifted)
            with self.assertRaises(runner.NgspiceIdentityMismatch) as ctx:
                runner.verify_ngspice_provenance(str(exe), candidate)
            self.assertIn("#182 failure mode", str(ctx.exception))

    def test_ngspice_major_version_extracts_the_pin_token(self):
        self.assertEqual(
            runner.ngspice_major_version(
                "ngspice-46 : Circuit level simulation program"
            ),
            "ngspice-46",
        )
        self.assertEqual(
            runner.ngspice_major_version("** ngspice-47 : Circuit level"), "ngspice-47"
        )
        self.assertIsNone(runner.ngspice_major_version("unknown"))
        self.assertIsNone(runner.ngspice_major_version(None))

    def test_ngspice_version_at_reads_a_specific_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = fake_ngspice_install(Path(tmp) / "root", "ngspice-47")
            self.assertEqual(
                runner.ngspice_major_version(runner.ngspice_version_at(exe)),
                "ngspice-47",
            )

    def test_ngspice_version_at_returns_none_for_a_missing_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(runner.ngspice_version_at(Path(tmp) / "nope"))

    def test_expected_ngspice_root_prefers_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            blessed = Path(tmp) / "blessed"
            fake_ngspice_install(blessed)
            with unittest.mock.patch.dict(
                "os.environ", {runner.NGSPICE_ROOT_ENV: str(blessed)}
            ):
                with unittest.mock.patch.object(
                    runner, "homebrew_prefix", return_value="/opt/homebrew"
                ) as homebrew_prefix:
                    resolved = runner.expected_ngspice_root()
                    homebrew_prefix.assert_not_called()
            self.assertEqual(resolved.path, str(blessed))
            self.assertEqual(resolved.source, runner.NGSPICE_ROOT_ENV)
            self.assertEqual(resolved.version, "ngspice-46")

    def _env_without_ngspice_root_override(self) -> dict:
        env = dict(os.environ)
        env.pop(runner.NGSPICE_ROOT_ENV, None)
        return env

    def test_expected_ngspice_root_prefers_the_versioned_homebrew_formula(self):
        """Issue #247, Option 1: a versioned keg's prefix cannot drift when
        the unversioned formula upgrades, so it wins the probe order."""
        with tempfile.TemporaryDirectory() as tmp:
            pinned = Path(tmp) / "ngspice@46"
            drifted = Path(tmp) / "ngspice"
            fake_ngspice_install(pinned, "ngspice-46")
            fake_ngspice_install(drifted, "ngspice-47")
            prefixes = {
                runner.PINNED_HOMEBREW_FORMULA: str(pinned),
                runner.DRIFTING_HOMEBREW_FORMULA: str(drifted),
            }
            with unittest.mock.patch.dict(
                os.environ, self._env_without_ngspice_root_override(), clear=True
            ):
                with unittest.mock.patch.object(
                    runner, "homebrew_prefix", side_effect=prefixes.get
                ):
                    resolved = runner.expected_ngspice_root()
            self.assertEqual(resolved.path, str(pinned))
            self.assertEqual(
                resolved.source, f"brew --prefix {runner.PINNED_HOMEBREW_FORMULA}"
            )
            self.assertEqual(resolved.version, "ngspice-46")
            self.assertFalse(resolved.drifted)

    def test_expected_ngspice_root_falls_back_to_the_unversioned_formula(self):
        """A host with no versioned keg still gets a root -- but one that
        reports the version it actually holds, so a drifted fallback can be
        recognised as such rather than trusted as the pin."""
        with tempfile.TemporaryDirectory() as tmp:
            drifted = Path(tmp) / "ngspice"
            fake_ngspice_install(drifted, "ngspice-47")
            prefixes = {runner.DRIFTING_HOMEBREW_FORMULA: str(drifted)}
            with unittest.mock.patch.dict(
                os.environ, self._env_without_ngspice_root_override(), clear=True
            ):
                with unittest.mock.patch.object(
                    runner, "homebrew_prefix", side_effect=prefixes.get
                ):
                    resolved = runner.expected_ngspice_root()
            self.assertEqual(resolved.path, str(drifted))
            self.assertEqual(
                resolved.source, f"brew --prefix {runner.DRIFTING_HOMEBREW_FORMULA}"
            )
            self.assertTrue(resolved.drifted)

    def test_expected_ngspice_root_skips_a_prefix_that_is_not_installed(self):
        """``brew --prefix <formula>`` answers for a *known* formula whether
        or not it is installed, so a non-existent prefix must not win."""
        with tempfile.TemporaryDirectory() as tmp:
            drifted = Path(tmp) / "ngspice"
            fake_ngspice_install(drifted, "ngspice-47")
            prefixes = {
                runner.PINNED_HOMEBREW_FORMULA: str(Path(tmp) / "not-installed"),
                runner.DRIFTING_HOMEBREW_FORMULA: str(drifted),
            }
            with unittest.mock.patch.dict(
                os.environ, self._env_without_ngspice_root_override(), clear=True
            ):
                with unittest.mock.patch.object(
                    runner, "homebrew_prefix", side_effect=prefixes.get
                ):
                    resolved = runner.expected_ngspice_root()
            self.assertEqual(resolved.path, str(drifted))

    def test_expected_ngspice_root_is_none_without_homebrew_or_override(self):
        with unittest.mock.patch.dict(
            os.environ, self._env_without_ngspice_root_override(), clear=True
        ):
            with unittest.mock.patch.object(runner, "homebrew_prefix", return_value=None):
                self.assertIsNone(runner.expected_ngspice_root())

    def test_homebrew_prefix_returns_none_when_brew_missing(self):
        with unittest.mock.patch("shutil.which", return_value=None):
            self.assertIsNone(runner.homebrew_prefix("ngspice"))

    def test_homebrew_prefix_returns_none_on_nonzero_exit(self):
        fake_result = unittest.mock.Mock(returncode=1, stdout="")
        with unittest.mock.patch("shutil.which", return_value="/opt/homebrew/bin/brew"):
            with unittest.mock.patch("subprocess.run", return_value=fake_result):
                self.assertIsNone(runner.homebrew_prefix("ngspice"))

    def test_homebrew_prefix_returns_stripped_stdout_on_success(self):
        fake_result = unittest.mock.Mock(returncode=0, stdout="/opt/homebrew/opt/ngspice\n")
        with unittest.mock.patch("shutil.which", return_value="/opt/homebrew/bin/brew"):
            with unittest.mock.patch("subprocess.run", return_value=fake_result):
                self.assertEqual(
                    runner.homebrew_prefix("ngspice"), "/opt/homebrew/opt/ngspice"
                )


class CheckEnvProvenanceTests(unittest.TestCase):
    """Issue #184's own acceptance criterion: ``--check-env`` must exit
    non-zero with an actionable message on a resolved/expected-root
    mismatch, not just when ``ngspice`` is entirely missing, and must stay
    ``OK`` on the happy path.
    """

    def _run_check_env(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            status = cli.cmd_check_env()
        return status, buffer.getvalue()

    def _env_without_ngspice_root_override(self) -> dict:
        # These tests drive `expected_ngspice_root()` entirely through the
        # mocked `homebrew_prefix()` below; strip any ambient
        # GF180_LDO_NGSPICE_ROOT so a developer's/CI's own real environment
        # cannot change which branch a given test exercises (the check this
        # issue adds does not depend on any environment variable or state
        # that isn't reproducible across hosts -- the original #182 defect).
        env = dict(os.environ)
        env.pop(runner.NGSPICE_ROOT_ENV, None)
        return env

    def test_matching_provenance_reports_ok_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew"
            exe = fake_ngspice_install(root)
            with unittest.mock.patch("shutil.which", return_value=str(exe)), \
                unittest.mock.patch.object(runner, "ngspice_version", return_value="ngspice-46"), \
                unittest.mock.patch.object(cli, "find_pdk", side_effect=PdkNotFound("no pdk")), \
                unittest.mock.patch.object(runner, "homebrew_prefix", return_value=str(root)), \
                unittest.mock.patch.dict(
                    os.environ, self._env_without_ngspice_root_override(), clear=True
                ):
                status, out = self._run_check_env()
            self.assertIn("provenance OK", out)
            self.assertNotIn("MISMATCH", out)
            # PDK is deliberately missing in this test env; only ngspice's own
            # branch of the exit status is under test here.
            self.assertIn("ngspice : OK", out)

    def test_shadowing_binary_fails_loudly_not_silently(self):
        """The core #182/#184 repro: a different build resolves first on
        PATH than the one the doc pins, both claiming to be ngspice-46.

        Issue #247's regression guard: this must keep failing for the #182
        reason, and must keep naming the shadowing binary."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew"
            fake_ngspice_install(root)
            shadow_exe = fake_ngspice_install(Path(tmp) / "local-build")
            with unittest.mock.patch("shutil.which", return_value=str(shadow_exe)), \
                unittest.mock.patch.object(runner, "ngspice_version", return_value="ngspice-46"), \
                unittest.mock.patch.object(cli, "find_pdk", side_effect=PdkNotFound("no pdk")), \
                unittest.mock.patch.object(runner, "homebrew_prefix", return_value=str(root)), \
                unittest.mock.patch.dict(
                    os.environ, self._env_without_ngspice_root_override(), clear=True
                ):
                status, out = self._run_check_env()
            self.assertEqual(status, cli.EXIT_ENVIRONMENT)
            self.assertIn("MISMATCH", out)
            self.assertIn(str(shadow_exe), out)
            self.assertIn("#182 failure mode", out)

    def test_drifted_homebrew_root_names_the_real_corrective_action(self):
        """Issue #247 end to end: on a host whose unversioned Homebrew
        ``ngspice`` has moved to 47, ``--check-env`` must stop presenting the
        ngspice-47 Cellar as the root to "fix" towards."""
        with tempfile.TemporaryDirectory() as tmp:
            drifted = Path(tmp) / "homebrew-ngspice-47"
            fake_ngspice_install(drifted, "ngspice-47")
            pinned_prefix = Path(tmp) / "pinned-46"
            exe = fake_ngspice_install(pinned_prefix, "ngspice-46")
            prefixes = {runner.DRIFTING_HOMEBREW_FORMULA: str(drifted)}
            with unittest.mock.patch("shutil.which", return_value=str(exe)), \
                unittest.mock.patch.object(runner, "ngspice_version", return_value="ngspice-46"), \
                unittest.mock.patch.object(cli, "find_pdk", side_effect=PdkNotFound("no pdk")), \
                unittest.mock.patch.object(runner, "homebrew_prefix", side_effect=prefixes.get), \
                unittest.mock.patch.dict(
                    os.environ, self._env_without_ngspice_root_override(), clear=True
                ):
                status, out = self._run_check_env()
            self.assertEqual(status, cli.EXIT_ENVIRONMENT)
            self.assertIn("MISMATCH", out)
            self.assertIn("ROOT that has drifted", out)
            self.assertIn(
                f"export {runner.NGSPICE_ROOT_ENV}={pinned_prefix.resolve()}", out
            )
            self.assertNotIn("#182 failure mode", out)

    def test_blessed_root_env_var_is_a_supported_happy_path(self):
        """Issue #247, Option 2: ``GF180_LDO_NGSPICE_ROOT`` is the documented
        mechanism for a host whose pinned ngspice-46 is not a Homebrew keg --
        it must reach ``provenance OK``, not merely suppress the error."""
        with tempfile.TemporaryDirectory() as tmp:
            blessed = Path(tmp) / "blessed-46"
            exe = fake_ngspice_install(blessed)
            drifted = Path(tmp) / "homebrew-ngspice-47"
            fake_ngspice_install(drifted, "ngspice-47")
            env = self._env_without_ngspice_root_override()
            env[runner.NGSPICE_ROOT_ENV] = str(blessed)
            with unittest.mock.patch("shutil.which", return_value=str(exe)), \
                unittest.mock.patch.object(runner, "ngspice_version", return_value="ngspice-46"), \
                unittest.mock.patch.object(cli, "find_pdk", side_effect=PdkNotFound("no pdk")), \
                unittest.mock.patch.object(runner, "homebrew_prefix", return_value=str(drifted)), \
                unittest.mock.patch.dict(os.environ, env, clear=True):
                status, out = self._run_check_env()
            self.assertIn("provenance OK", out)
            self.assertIn(runner.NGSPICE_ROOT_ENV, out)
            self.assertNotIn("MISMATCH", out)

    def test_no_homebrew_and_no_override_reports_unverified_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "ngspice"
            exe.write_bytes(b"fake\n")
            with unittest.mock.patch("shutil.which", return_value=str(exe)), \
                unittest.mock.patch.object(runner, "ngspice_version", return_value="ngspice-46"), \
                unittest.mock.patch.object(cli, "find_pdk", side_effect=PdkNotFound("no pdk")), \
                unittest.mock.patch.object(runner, "homebrew_prefix", return_value=None), \
                unittest.mock.patch.dict(
                    os.environ, self._env_without_ngspice_root_override(), clear=True
                ):
                status, out = self._run_check_env()
            self.assertIn("provenance not verified", out)
            self.assertNotIn("MISMATCH", out)

    def test_unverifiable_host_off_the_pin_notes_it_without_failing(self):
        """CI's own ``pvt-smoke`` job runs Ubuntu's apt ngspice-42 on purpose
        (a standing model-bin portability check; DR-0027 / issue #254
        confirms its wnflag facts reproduce). #247's version pin must be
        *reported* there, never enforced -- that host has no pinned root to
        check against and is deliberately a different build."""
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "ngspice"
            exe.write_bytes(b"fake\n")
            with unittest.mock.patch("shutil.which", return_value=str(exe)), \
                unittest.mock.patch.object(runner, "ngspice_version", return_value="ngspice-42"), \
                unittest.mock.patch.object(cli, "find_pdk", side_effect=PdkNotFound("no pdk")), \
                unittest.mock.patch.object(runner, "homebrew_prefix", return_value=None), \
                unittest.mock.patch.dict(
                    os.environ, self._env_without_ngspice_root_override(), clear=True
                ):
                status, out = self._run_check_env()
            self.assertIn("provenance not verified", out)
            self.assertIn("ngspice-42", out)
            self.assertIn(runner.PINNED_NGSPICE_VERSION, out)
            self.assertNotIn("MISMATCH", out)


if __name__ == "__main__":
    unittest.main()
