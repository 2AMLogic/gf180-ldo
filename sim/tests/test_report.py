#!/usr/bin/env python3
"""Unit tests for ``sim/harness/report.py``: grading, provenance and the
append-only record. No PDK and no ngspice required; the PDK is
``test_harness.fake_pdk``.

    python3 -m unittest sim/tests/test_report.py -v
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import corners, paths, report, runner, testbench  # noqa: E402
from harness.pdk import Pdk  # noqa: E402
from harness.pvt_log import parse_meas_lines, read_measurements  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_harness import fake_pdk  # noqa: E402


@dataclasses.dataclass(frozen=True)
class _SmokeBiasRun:
    """One built ``smoke-bias`` record and the inputs that built it."""

    tb: testbench.Testbench
    pdk: Pdk
    points: list[corners.PvtPoint]
    results: list[runner.PointResult]
    record: dict


def _write_minimal_testbench(root: Path, slug: str, manifest: dict | None = None) -> testbench.Testbench:
    """Lay out ``<root>/<slug>/testbench/`` with the smallest manifest the
    harness loads -- one source line ``x.spice`` and one measurement -- and
    return it loaded. ``manifest`` entries override the base, as
    ``test_harness.TestbenchTests._write`` does."""
    tb_dir = root / slug / "testbench"
    tb_dir.mkdir(parents=True, exist_ok=True)
    (tb_dir / "x.spice").write_text("v1 out 0 dc {vdd_val}\n")
    base = {"name": slug, "netlist": "x.spice", "measure": {"vout": "v(out)"}}
    base.update(manifest or {})
    (tb_dir / "tb.json").write_text(json.dumps(base))
    return testbench.load(tb_dir)


def _smoke_bias_run(root: Path) -> _SmokeBiasRun:
    """The record ``RecordRenderingTests`` renders: the minimal smoke-bias
    testbench, the fake PDK, and one synthetic ``vout`` per point of the full
    mandated matrix."""
    tb = _write_minimal_testbench(root, "smoke-bias", {"checks": {"vout": {"min": 0.0, "max": 10.0}}})
    pdk = fake_pdk(root / "gf180mcuD")
    points = corners.build_grid(
        corners.resolve_corners(["mos"]), (-40, 27, 125), corners.supply_points(3.3, 0.10)
    )
    results = [
        runner.PointResult(point=p, status="ok", measurements={"vout": 1.0 + i * 0.01})
        for i, p in enumerate(points)
    ]
    record = report.build_record(
        tb=tb,
        pdk=pdk,
        points=points,
        results=results,
        ngspice="ngspice-46",
        repo_root=SIM_DIR,
        record_id="20260729-153000-1a7ef75",
        started_utc="2026-07-29T15:30:00+00:00",
        wall_seconds=9.5,
        claim="spec/ldo.md#example",
    )
    return _SmokeBiasRun(tb, pdk, points, results, record)


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

    def test_values_exactly_at_a_bound_pass(self):
        results = [_StubResult("a", {"v": 1.0}), _StubResult("b", {"v": 1.2})]
        summary = report.summarize(results, ["v"])
        self.assertEqual(
            [], report.evaluate_checks({"v": {"min": 1.0, "max": 1.2}}, results, summary)
        )

    def test_scalar_bound_failure_is_inclusive_and_fails_closed(self):
        # Issue #798: the one scalar rule behind evaluate_checks and both
        # staging graders.
        f = report.scalar_bound_failure
        self.assertIsNone(f(2.56, {"min": -2.56, "max": 2.56}))
        self.assertIsNone(f(-2.56, {"min": -2.56, "max": 2.56}))
        self.assertEqual("max", f(2.5600001, {"min": -2.56, "max": 2.56}))
        self.assertEqual("min", f(-2.5600001, {"min": -2.56, "max": 2.56}))
        self.assertEqual("nonfinite", f(float("inf"), {"min": 0.05}), "one-sided min")
        self.assertEqual("nonfinite", f(float("-inf"), {"max": 3.49}), "one-sided max")
        self.assertEqual("nonfinite", f(None, {"max": 1.0}), "staging: a missing value")
        self.assertIsNone(f(1.0, {"max_spread_pct": 5}), "spread bounds are grid-level")
        self.assertEqual("nonfinite", f(float("nan"), {"max_spread_pct": 5}))
        self.assertIsNone(f(float("nan"), {}), "no bound constrains nothing")

    def test_inverted_range_reports_both_bounds(self):
        # Review of #800: an accepted-but-unsatisfiable range must keep both
        # record failures (min and max), as before the shared rule.
        spec = {"x": {"min": 2, "max": 0}}
        self.assertEqual(["min", "max"], report.scalar_bound_failures(1, spec["x"]))
        results = [_StubResult("a", {"x": 1})]
        failures = report.evaluate_checks(spec, results, report.summarize(results, ["x"]))
        self.assertEqual([("min", 2), ("max", 0)],
                         [(f["kind"], f["limit"]) for f in failures])
        self.assertEqual([], report.scalar_bound_failures(1, {"min": 0, "max": 2}))

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


class NonFiniteFailClosedTests(unittest.TestCase):
    """Issue #420: overflowed/NaN/inf values and statistics fail closed."""

    def _results(self, values, status="ok"):
        return [
            runner.PointResult(
                corners.PvtPoint(corners.CORNERS[c], 27, 3.3), status, {"x": v}
            )
            for c, v in zip(("tt", "ff", "ss"), values)
        ]

    def test_parse_drops_overflow_token_and_reports_it(self):
        found, bad = runner.parse_measurements_checked("m_x = 1e999\nm_y = 2.5\n")
        self.assertEqual({"y": 2.5}, found)
        self.assertEqual(["x"], bad)

    def test_shared_parser_tolerates_trailing_context_and_reports_failed(self):
        """#470: one definition of a measurement line for all three consumers."""
        text = (
            "  m_t_start = 4.2e-03 targ= 1.0e-03 trig= 2.0e-04\n"
            "m_t_late = failed\n"
            "m_x = 1e999\n"
        )
        parsed = parse_meas_lines(text)
        self.assertEqual({"m_t_start": 4.2e-03}, parsed.values)
        self.assertEqual(["m_t_late"], parsed.failed)
        self.assertEqual(["m_x"], parsed.nonfinite)
        # runner strips the prefix and keeps its non-finite reporting
        found, bad = runner.parse_measurements_checked(text)
        self.assertEqual({"t_start": 4.2e-03}, found)
        self.assertEqual(["x"], bad)

    def test_pvt_log_rejects_overflow_token(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "a.log"
            log.write_text("m_x = 1e999\n")
            with self.assertRaises(SystemExit) as cm:
                read_measurements(log, ["m_x"])
        self.assertIn("non-finite", str(cm.exception))

    def test_nonfinite_constructed_values_never_pass(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            for check in ({"max": 10.0}, {"min": -10.0}, {"max_spread_pct": 1}):
                with self.subTest(bad=bad, check=check):
                    results = self._results([1.0, bad])
                    summary = report.summarize(results, ["x"])
                    failures = report.evaluate_checks({"x": check}, results, summary)
                    self.assertTrue(failures)
                    self.assertIn("nonfinite", {f["kind"] for f in failures})

    def test_all_nonfinite_samples_fail(self):
        results = self._results([float("inf"), float("inf")])
        summary = report.summarize(results, ["x"])
        self.assertIsNone(summary["x"]["spread_pct"])
        self.assertTrue(
            report.evaluate_checks({"x": {"max_spread_pct": 1}}, results, summary)
        )

    def test_huge_finite_samples_give_correct_spread(self):
        results = self._results([1e308, 1.5e308])
        summary = report.summarize(results, ["x"])
        self.assertTrue(summary["x"]["mean"] > 0 and summary["x"]["mean"] < float("inf"))
        self.assertAlmostEqual(summary["x"]["spread_pct"], 40.0)
        failures = report.evaluate_checks({"x": {"max_spread_pct": 1}}, results, summary)
        self.assertEqual("max_spread_pct", failures[0]["kind"])

    def test_huge_opposite_sign_samples_do_not_pass(self):
        results = self._results([-1.5e308, 1.5e308])
        summary = report.summarize(results, ["x"])
        self.assertIsNone(summary["x"]["spread_pct"])  # zero mean: unevaluable
        self.assertTrue(
            report.evaluate_checks({"x": {"max_spread_pct": 1}}, results, summary)
        )

    def test_underflowing_scaled_mean_is_unevaluable_not_a_crash(self):
        # PR #421 review: abs(mean)/scale underflowed to zero and the rescaled
        # spread raised ZeroDivisionError. It must be None and fail closed.
        results = self._results([-1e308, 1e308, 1e-300])
        summary = report.summarize(results, ["x"])
        self.assertTrue(math.isfinite(summary["x"]["mean"]))
        self.assertIsNone(summary["x"]["spread_pct"])
        for check in ({"max_spread_pct": 1}, {"min_spread_pct": 1}):
            with self.subTest(check=check):
                failures = report.evaluate_checks({"x": check}, results, summary)
                self.assertTrue(failures)

    def test_float_max_samples_do_not_overflow_the_mean(self):
        # PR #421 review: fsum(v / n) raised "intermediate overflow in fsum".
        big = sys.float_info.max
        results = self._results([big, big, big])
        summary = report.summarize(results, ["x"])
        self.assertEqual(big, summary["x"]["mean"])
        self.assertEqual(0.0, summary["x"]["spread_pct"])
        self.assertEqual(
            [], report.evaluate_checks({"x": {"max_spread_pct": 1}}, results, summary)
        )
        failures = report.evaluate_checks({"x": {"min_spread_pct": 1}}, results, summary)
        self.assertEqual("min_spread_pct", failures[0]["kind"])

    def test_safe_mean_stays_within_sample_range(self):
        big = sys.float_info.max
        for values in (
            [big, big, big],
            [-big, -big, -big],
            [big, big / 2, big],
            [big, -big, big],
            [-1e308, 1e308, 1e-300],
        ):
            with self.subTest(values=values):
                mean = report._safe_mean(values)
                self.assertTrue(math.isfinite(mean))
                self.assertTrue(min(values) <= mean <= max(values))

    def test_ordinary_grading_and_waivers_unchanged(self):
        results = self._results([1.0, 1.2, 0.8])
        summary = report.summarize(results, ["x"])
        self.assertAlmostEqual(summary["x"]["spread_pct"], 40.0)
        self.assertEqual(
            [], report.evaluate_checks({"x": {"max_spread_pct": 50, "min": 0.5}}, results, summary)
        )
        one = self._results([1.0])
        one_summary = report.summarize(one, ["x"])
        self.assertEqual(1, len(report.waived_checks({"x": {"max_spread_pct": 1}}, one_summary)))
        self.assertEqual([], report.evaluate_checks({"x": {"max_spread_pct": 1}}, one, one_summary))
        zero = self._results([-1.0, 1.0])
        self.assertIsNone(report.summarize(zero, ["x"])["x"]["spread_pct"])


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


#: Every ``sim/`` driver that mints its own ``<record-id>``. Each must do it
#: through ``report.format_record_id`` -- see EveryDriverMintsTheIdOnce below.
_MINTING_DRIVERS = (
    "loop-stability/testbench/sweep.py",
    "soft-start-loop-gain/testbench/sweep.py",
    "soft-start/testbench/handover_t15.py",
    "soft-start/testbench/ramp_ab.py",
)


class EveryDriverMintsTheIdOnce(unittest.TestCase):
    """No driver may hand-roll the record id (issue #618).

    Two of these four drivers used to build the id from ``git rev-parse
    --short HEAD`` inline. That is not a style complaint: ``--short`` emits
    however many characters git currently needs for an unambiguous prefix,
    which is already **eight** at some commits in this repo, whereas
    ``format_record_id`` takes ``commit[:7]`` unconditionally and
    ``sim/README.md`` ratifies the seven-character shape. A hand-rolled mint
    therefore drifts off the ratified shape with no code change at all, the
    first time git needs a wider prefix -- and nothing in the driver notices.

    The same block also dropped ``git_provenance``'s ``dirty`` flag, so a run
    from a dirty working tree produced committed logs whose only provenance
    was a clean-looking commit sha.

    Asserted on source text rather than behaviour because the mint sits
    inline in each driver's ``main()``, which cannot run without a PDK and
    ngspice. A source assertion is what keeps a *future* driver from
    reintroducing the same copy.
    """

    def _read(self, rel: str) -> str:
        return (SIM_DIR / rel).read_text()

    def test_no_driver_builds_the_id_from_git_rev_parse_short(self):
        for rel in _MINTING_DRIVERS:
            with self.subTest(driver=rel):
                self.assertNotIn(
                    '"--short"', self._read(rel),
                    f"{rel} hand-rolls the record id from `git rev-parse "
                    "--short`, whose width git chooses; call "
                    "report.format_record_id instead",
                )

    def test_every_driver_mints_through_the_harness_helpers(self):
        for rel in _MINTING_DRIVERS:
            with self.subTest(driver=rel):
                text = self._read(rel)
                self.assertIn("format_record_id", text)
                self.assertIn("git_provenance", text)

    def test_the_ratified_shape_is_seven_hex_characters(self):
        """The shape the drivers now inherit, re-asserted against a real sha.

        `git_provenance` truncates to 7 regardless of what `--short` would
        have chosen, so an eight-character ambiguity window cannot widen the
        id.
        """
        prov = report.git_provenance(SIM_DIR.parent)
        if prov["commit"] == "unknown":  # pragma: no cover - git is present
            self.skipTest("not a git checkout")
        self.assertEqual(len(prov["short"]), 7)
        minted = report.format_record_id(
            prov["short"], datetime.datetime.now(datetime.timezone.utc))
        self.assertRegex(minted, r"^\d{8}-\d{6}-[0-9a-f]{7}$")

    def test_both_by_hand_record_drivers_warn_on_a_dirty_tree(self):
        """The two drivers whose record body a human writes must say so.

        `sim/loop-stability` and `sim/soft-start-loop-gain` render their own
        record and put the dirty-tree warning in it. These two print "write
        .../records/<id>.md by hand", so the only place the warning can reach
        the person writing that record is stdout.
        """
        for rel in ("soft-start/testbench/handover_t15.py",
                    "soft-start/testbench/ramp_ab.py"):
            with self.subTest(driver=rel):
                text = self._read(rel)
                self.assertIn('prov["dirty"]', text)
                self.assertIn("DIRTY at run time", text)


class GitProvenanceDirtyFlagTests(unittest.TestCase):
    """``dirty`` ignores a not-yet-minted record's staging tree (PR #745).

    A resumed campaign's previous-session output sits untracked under
    ``corners/<record-id>/`` until the record is minted under ``records/``.
    Counting it ``dirty`` either brands the completing record uncitable or
    forces committing half-finished output into append-only evidence space.
    Once a record with the id exists, the same paths are evidence and count
    again. ``netlist-snapshots/`` is not exempt (issue #750): its snapshots
    are flat ``<record-id>.spice`` files written only at mint, beside the
    non-exempt record.
    """

    MINTED = "20260729-153000-1a7ef75"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "user.name", "t")
        bench = self.root / "sim" / "loop-stability"
        (bench / "records").mkdir(parents=True)
        (bench / "records" / f"{self.MINTED}.md").write_text("# record\n")
        (bench / "corners" / self.MINTED).mkdir(parents=True)
        (bench / "corners" / self.MINTED / "tt_27c.log").write_text("log\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root), *args], check=True)

    def stage(self, rel: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("untracked\n")
        return path

    def dirty(self) -> bool:
        return report.git_provenance(self.root)["dirty"]

    def test_unminted_corners_staging_is_not_dirty(self):
        self.stage("sim/loop-stability/corners/20260730-090000-bbb0002/"
                   "klt-reports/il0.json")
        self.assertFalse(self.dirty())

    def test_flat_netlist_snapshot_is_dirty_when_unminted(self):
        self.stage("sim/loop-stability/netlist-snapshots/"
                   "20260730-090000-bbb0002.spice")
        self.assertTrue(self.dirty())

    def test_flat_netlist_snapshot_is_dirty_when_minted(self):
        self.stage(f"sim/loop-stability/netlist-snapshots/{self.MINTED}.spice")
        self.assertTrue(self.dirty())

    def test_flat_file_directly_under_corners_is_dirty(self):
        self.stage("sim/loop-stability/corners/notes.txt")
        self.assertTrue(self.dirty())

    def test_new_files_in_a_minted_records_corners_are_dirty(self):
        self.stage(f"sim/loop-stability/corners/{self.MINTED}/extra.log")
        self.assertTrue(self.dirty())

    def test_untracked_files_elsewhere_are_still_dirty(self):
        self.stage("sim/loop-stability/testbench/scratch.py")
        self.assertTrue(self.dirty())

    def test_edits_to_committed_minted_evidence_are_still_dirty(self):
        log = (self.root / "sim" / "loop-stability" / "corners"
               / self.MINTED / "tt_27c.log")
        log.write_text("edited\n")
        self.assertTrue(self.dirty())

    def test_a_records_artifact_mints_the_id_for_staging_purposes(self):
        (self.root / "sim" / "loop-stability" / "records"
         / "20260730-090000-bbb0002-matrix.csv").write_text("csv\n")
        self.stage("sim/loop-stability/corners/20260730-090000-bbb0002/ff.log")
        self.assertTrue(self.dirty())


class ProvenanceBannerTests(unittest.TestCase):
    """One definition of the banner, one label width (issue #618)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pdk = fake_pdk(Path(self.tmp.name) / "gf180mcuD")
        patches = [
            unittest.mock.patch.object(report, "ngspice_version",
                                       return_value="ngspice-46"),
            unittest.mock.patch.object(report, "ngspice_binary_sha256",
                                       return_value="abc123"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def banner(self, *args, **kwargs) -> list[str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report.print_provenance_banner(*args, **kwargs)
        return buf.getvalue().splitlines()

    def test_every_label_colon_lands_in_the_same_column(self):
        lines = self.banner(self.pdk, "20260729-153000-1a7ef75",
                            host="a-host", dirty=True, note=" (a note)")
        columns = {line.index(":") for line in lines}
        self.assertEqual(len(columns), 1, lines)
        self.assertEqual(columns, {14})

    def test_the_banner_carries_the_four_provenance_facts(self):
        lines = self.banner(self.pdk, "20260729-153000-1a7ef75")
        self.assertEqual(
            lines,
            [
                f"pdk           : {self.pdk.variant} @ {self.pdk.version}",
                "ngspice       : ngspice-46",
                "ngspice sha256: abc123",
                "record id     : 20260729-153000-1a7ef75",
            ],
        )

    def test_host_and_note_are_opt_in(self):
        lines = self.banner(self.pdk, "20260729-153000-1a7ef75",
                            host="a-host", note=" (NOT WRITTEN: --no-write)")
        self.assertIn("host          : a-host", lines)
        self.assertIn(
            "record id     : 20260729-153000-1a7ef75 (NOT WRITTEN: --no-write)",
            lines,
        )

    def test_a_dirty_tree_is_stated_not_implied(self):
        clean = self.banner(self.pdk, "20260729-153000-1a7ef75", dirty=False)
        self.assertNotIn("DIRTY", "\n".join(clean))
        dirty = self.banner(self.pdk, "20260729-153000-1a7ef75", dirty=True)
        self.assertIn(
            "working tree  : DIRTY at run time; "
            "not citable as a clean-tree result",
            dirty,
        )


class MatrixConformanceTests(unittest.TestCase):
    """sim/README.md requires the full mandated matrix, or a stated reason."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tb = _write_minimal_testbench(
            Path(self.tmp.name), "an-experiment", {"name": "x"}
        )

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
        run = _smoke_bias_run(Path(self.tmp.name))
        self.tb, self.pdk = run.tb, run.pdk
        self.points, self.results, self.record = run.points, run.results, run.record

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


class PsrrSpreadWaiverRenderingTests(unittest.TestCase):
    """Issue #860's fixture through the local writer.

    The real ``sim/psrr-dc/testbench/tb.json`` checks over synthetic
    completed points -- every measurement 1, ``adiff_1k_db`` 60 and
    ``psrr_ldo_1k_db`` 56, so every per-point bound holds and only the
    ``adiff_1k_db`` minimum-spread floor distinguishes the verdicts. The
    same fixture ``sim/tests/test_klt_record.py`` runs through the batch
    writer; the two record formats must not disagree about what a
    degenerate grid waived. A rendering fixture -- no claim about silicon.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.pdk = fake_pdk(root / "gf180mcuD")
        self.tb = testbench.load(SIM_DIR / "psrr-dc" / "testbench")

    def _record(self, adiff_by_corner):
        """One completed 27 C / 3.30 V point per named process corner."""
        points = corners.build_grid(
            corners.resolve_corners(list(adiff_by_corner)), (27,), (3.3,)
        )
        results = []
        for point in points:
            measurements = dict.fromkeys(self.tb.measure, 1.0)
            measurements["adiff_1k_db"] = adiff_by_corner[point.corner.name]
            measurements["psrr_ldo_1k_db"] = 56.0
            results.append(
                runner.PointResult(point=point, status="ok", measurements=measurements)
            )
        return report.build_record(
            tb=self.tb,
            pdk=self.pdk,
            points=points,
            results=results,
            ngspice="ngspice-47",
            repo_root=SIM_DIR,
            record_id="20260101-090000-860fix0",
            started_utc="2026-01-01T09:00:00+00:00",
            wall_seconds=1.0,
            subset_reason="rendering fixture for issue #860, not a spec claim",
        )

    def test_a_one_point_psrr_grid_names_the_waived_spread_check(self):
        text = report.render_record(self._record({"tt": 60.0}), "psrr-dc")
        self.assertIn("Grid-level checks NOT evaluated", text)
        self.assertIn(
            "adiff_1k_db min_spread_pct=5 (spread is undefined over "
            "1 completed point; needs at least 2)",
            text,
        )
        self.assertIn("not evidence about PVT sensitivity", text)

    def test_a_second_equal_point_grades_the_floor_instead_of_waiving_it(self):
        text = report.render_record(self._record({"tt": 60.0, "ff": 60.0}), "psrr-dc")
        self.assertIn(
            "Grid-level check failures: adiff_1k_db min_spread_pct=5 (got 0).", text
        )
        self.assertIn("- **Overall: FAIL**", text)
        self.assertNotIn("NOT evaluated", text)

    def test_a_grid_that_spreads_renders_no_waiver_note(self):
        text = report.render_record(self._record({"tt": 60.0, "ff": 64.0}), "psrr-dc")
        self.assertNotIn("NOT evaluated", text)
        self.assertNotIn("Grid-level check failures", text)
        self.assertIn("- **Overall: PASS**", text)


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


class ExclusiveRecordWriteTests(unittest.TestCase):
    """Append-only evidence is enforced by exclusive creation, not check-then-write.

    Deterministic: both writers are held at a barrier placed after their
    collision checks and immediately before publication, so both have
    observed "absent" before either creates the file (issue #422).
    """

    ID = "20260729-153000-abc1234"

    def setUp(self):
        import threading

        self.threading = threading
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _race(self, writers):
        """Run ``writers`` (callables) concurrently, all paused before publish."""
        barrier = self.threading.Barrier(len(writers), timeout=10)
        real = report._publish_exclusive

        def gated(path, text):
            barrier.wait()  # every writer has passed its existence check
            return real(path, text)

        outcomes = [None] * len(writers)

        def run(i, fn):
            try:
                outcomes[i] = ("ok", fn())
            except report.RecordExists as exc:
                outcomes[i] = ("exists", exc)

        with unittest.mock.patch.object(report, "_publish_exclusive", gated):
            threads = [
                self.threading.Thread(target=run, args=(i, fn))
                for i, fn in enumerate(writers)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        return outcomes

    def _assert_one_winner(self, outcomes, path, winners_text):
        kinds = sorted(o[0] for o in outcomes)
        self.assertEqual(kinds, ["exists", "ok"])
        self.assertIn(path.read_text(), winners_text)

    def test_markdown_record_concurrent_writers(self):
        records = self.root / "records"
        outcomes = self._race(
            [lambda t=t: report.write_markdown_record(self.ID, t, records) for t in ("A\n", "B\n")]
        )
        self._assert_one_winner(outcomes, records / f"{self.ID}.md", ("A\n", "B\n"))
        self.assertEqual(len(list(records.iterdir())), 1)

    def test_write_record_concurrent_writers(self):
        experiment = self.root / "exp"
        rec = {"record_id": self.ID}
        with unittest.mock.patch.object(
            report, "render_record", side_effect=["A\n", "B\n"]
        ):
            outcomes = self._race(
                [lambda: report.write_record(rec, experiment) for _ in range(2)]
            )
        self._assert_one_winner(
            outcomes, experiment / report.RECORDS_DIR / f"{self.ID}.md", ("A\n", "B\n")
        )

    def test_netlist_snapshot_concurrent_writers(self):
        tb = _write_minimal_testbench(self.root, "smoke-bias", {"measure": {"v": "v(out)"}})
        outcomes = self._race(
            [lambda: report.write_netlist_snapshot(tb, tb.experiment_dir, self.ID) for _ in range(2)]
        )
        path = tb.experiment_dir / report.SNAPSHOT_DIR / f"{self.ID}.spice"
        self.assertEqual(sorted(o[0] for o in outcomes), ["exists", "ok"])
        self.assertIn("v1 out 0 dc {vdd_val}", path.read_text())

    def test_exclusive_publish_never_overwrites_or_deletes(self):
        path = self.root / "r.md"
        report._publish_exclusive(path, "keep\n")
        with self.assertRaises(report.RecordExists):
            report._publish_exclusive(path, "clobber\n")
        self.assertEqual("keep\n", path.read_text())

    def test_partial_file_is_left_alone_on_retry(self):
        path = self.root / "r.md"
        path.write_text("partial")
        with self.assertRaises(report.RecordExists):
            report.write_markdown_record("r", "full\n", self.root)
        self.assertEqual("partial", path.read_text())

    def test_render_failure_creates_no_destination(self):
        experiment = self.root / "exp"
        with self.assertRaises(KeyError):
            report.write_record({"record_id": self.ID}, experiment)
        self.assertEqual(list((experiment / report.RECORDS_DIR).glob("*")), [])


class HostPathRedactionTests(unittest.TestCase):
    """Issue #365: published records must not embed absolute host paths."""

    FAKE_HOME = "/home/fakeuser"

    def test_rendered_record_has_no_absolute_home_path(self):
        pdk_dir = Path(self.FAKE_HOME) / ".local" / "share" / "pdk" / "gf180mcuD"
        pdk = Pdk(
            path=pdk_dir,
            variant="gf180mcuD",
            source="search_root:" + self.FAKE_HOME + "/.pdk",
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rec = dict(_smoke_bias_run(Path(tmp.name)).record)
        rec["environment"] = dict(rec["environment"], pdk=pdk.provenance())
        rec["environment"]["pdk"]["path"] = str(pdk_dir)  # raw, as old records had it
        rec["environment"]["pdk"]["discovered_via"] = pdk.source
        text = report.render_record(rec, "smoke-bias")
        self.assertNotIn("/home/", text)
        self.assertNotIn("fakeuser", text)
        self.assertIn("gf180mcuD", text)
        self.assertIn("found via search_root:", text)

    def test_pdk_path_forms(self):
        with unittest.mock.patch.dict(os.environ, {"PDK_ROOT": "/opt/pdks"}):
            self.assertEqual(
                paths.display_pdk_path("/opt/pdks/gf180mcuD"), "$PDK_ROOT/gf180mcuD"
            )
        with unittest.mock.patch.dict(os.environ, {"HOME": self.FAKE_HOME}):
            os.environ.pop("PDK_ROOT", None)
            self.assertEqual(
                paths.display_pdk_path(self.FAKE_HOME + "/pdk/gf180mcuD"), "~/pdk/gf180mcuD"
            )
            self.assertEqual(paths.scrub_source("search_root:" + self.FAKE_HOME + "/.pdk"),
                             "search_root:~/.pdk")

    def test_diagnostic_paths_are_repo_relative_or_basename(self):
        inside = paths.REPO_ROOT / "sim" / "x" / "corners" / "r" / "tt.log"
        self.assertEqual(paths.display_path(inside), "sim/x/corners/r/tt.log")
        home = Path(self.FAKE_HOME)
        layouts = (
            ("standalone", home / "repo"),
            ("legacy worktree", home / "loom" / ".loom" / "worktrees" / "issue-1"),
            ("namespaced worktree",
             home / "loom" / ".loom" / "worktrees" / "gf180-ldo" / "pr-761"),
        )
        for layout, checkout in layouts:
            log = checkout / "sim" / "x" / "corners" / "r" / "tt.log"
            with self.subTest(layout=layout), \
                    unittest.mock.patch.object(paths, "REPO_ROOT", checkout):
                self.assertEqual(paths.display_path(log), "sim/x/corners/r/tt.log")
        wt = Path(self.FAKE_HOME) / "repo" / ".loom" / "worktrees" / "issue-1" / "sim" / "a.log"
        self.assertEqual(paths.display_path(wt), "sim/a.log")
        self.assertEqual(paths.display_path("sim/a.log"), "sim/a.log")
        self.assertEqual(paths.display_path(self.FAKE_HOME + "/elsewhere/b.log"), "<abs>/b.log")


if __name__ == "__main__":
    unittest.main()
