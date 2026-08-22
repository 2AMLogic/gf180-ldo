#!/usr/bin/env python3
"""Unit tests for the PVT harness. No PDK and no ngspice required.

    python3 -m unittest discover -s sim/tests -v
"""

from __future__ import annotations

import datetime
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import corners, report, runner, testbench  # noqa: E402
from harness.pdk import Pdk  # noqa: E402


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

    def test_passing_checks_produce_no_failures(self):
        self.assertEqual(
            report.evaluate_checks(
                {"v": {"min": 0.5, "max": 1.5, "max_spread_pct": 50.0}},
                self.results,
                self.summary,
            ),
            [],
        )


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


if __name__ == "__main__":
    unittest.main()
