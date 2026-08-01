#!/usr/bin/env python3
"""Unit tests for the PVT harness. No PDK and no ngspice required.

    python3 -m unittest discover -s sim/tests -v
"""

from __future__ import annotations

import datetime
import json
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


class DeckIncludeTests(unittest.TestCase):
    """`includes` puts design cells in the deck ahead of the fragment."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "design").mkdir()
        self.cell = (root / "design" / "cell.spice").resolve()
        self.cell.write_text(".subckt cell a b\nr1 a b 1k\n.ends\n")
        (root / "tb").mkdir()
        (root / "tb" / "x.spice").write_text("x1 out 0 cell\n")
        (root / "tb" / "tb.json").write_text(
            json.dumps(
                {
                    "name": "x",
                    "netlist": "x.spice",
                    "includes": ["../design/cell.spice"],
                    "measure": {"vout": "v(out)"},
                }
            )
        )
        self.root = root
        self.tb = testbench.load(root / "tb")
        self.pdk = fake_pdk(root / "gf180mcuD")
        self.point = corners.build_grid(corners.resolve_corners(["tt"]), (27,), [3.3])[0]

    def test_design_cell_is_included_before_the_fragment(self):
        deck = runner.compose_deck(self.tb, self.pdk, self.point)
        cell_at = deck.index(str(self.cell))
        frag_at = deck.index("x.spice")
        self.assertLess(cell_at, frag_at)
        self.assertIn(f'.include "{self.cell}"', deck)

    def test_snapshot_freezes_the_design_cell_and_the_fragment(self):
        experiment_dir = self.root / "tb"  # stands in for sim/<slug>/
        path = report.write_netlist_snapshot(self.tb, experiment_dir, "20260731-000000-abc1234")
        text = path.read_text()
        self.assertIn("r1 a b 1k", text)          # the design cell
        self.assertIn("x1 out 0 cell", text)      # the testbench fragment
        self.assertLess(text.index("r1 a b 1k"), text.index("x1 out 0 cell"))
        self.assertIn("included design cell", text)
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


if __name__ == "__main__":
    unittest.main()
