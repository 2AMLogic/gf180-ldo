#!/usr/bin/env python3
"""Unit tests for sim/build_characterization_report.py's verdict extraction.

    python3 -m unittest discover -s sim/tests -v

``sim/CHARACTERIZATION.md`` is regenerated from the committed records and
diffed in CI, but that diff cannot catch a *faithfulness* defect: the
generator is deterministic, so its output always matches whatever it last
produced regardless of whether the extracted verdict actually reflects the
record's own prose. These tests cover exactly that gap (issue #251): a
record that states one verdict as several bold runs separated by unbolded
prose must render every one of those clauses, not just the first.

No PDK, no ngspice, no network -- these read committed text only.
"""

from __future__ import annotations

import csv
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
_REPORT_PATH = SIM_DIR / "build_characterization_report.py"
_spec = importlib.util.spec_from_file_location(
    "build_characterization_report", _REPORT_PATH
)
bcr = importlib.util.module_from_spec(_spec)
sys.modules["build_characterization_report"] = bcr
_spec.loader.exec_module(bcr)

# The pre-#251 extractor: one bold run per `**Overall...**`, terminated by
# the next `*`. Kept here as the regression oracle -- every verdict it finds
# must still be found, and must still be the *prefix* of what the current
# extractor renders for the same verdict, so no landed record's rendering is
# silently rewritten or dropped by a change to the grouping rules.
LEGACY_OVERALL_RE = re.compile(r"\*\*Overall[^*]*\*\*")

RECORDS = sorted((SIM_DIR).glob("*/records/*.md"))

# The record that surfaced #251 (soft-start, DR-0023 cascode, PR #250): its
# section 7 states four verdicts, each as several bold runs separated by
# unbolded prose.
MULTI_RUN_RECORD = SIM_DIR / "soft-start" / "records" / "20260918-190207-8a59d23.md"
# Its superseded predecessor states each verdict as one contiguous bold run.
SINGLE_RUN_RECORD = SIM_DIR / "soft-start" / "records" / "20260915-103035-18f664f.md"


class TestMultiBoldRunVerdicts(unittest.TestCase):
    """A verdict split across several bold runs renders every clause."""

    FIXTURE = """## 7. Overall verdicts

**Overall (Startup, ratified row, DR-0006): FAIL on ramp rate** (163/163
points exceed the bound) **and FAIL on inrush and current-limit clearance**
(0/83 and 2/83 at C_eff = 1 uF).
**PASS on the ratified <= 6 ms settling clause at 163/163** (worst 1.28 ms).

**Overall (DR-0024 proposed bounds, not yet ratified): PASS on ramp
rate** and **FAIL on inrush, current-limit clearance, monotonicity**, all
for the reason section 3 measures.

## 8. Next
"""

    def test_every_bold_clause_of_a_split_verdict_is_captured(self):
        snippets = bcr.extract_verdict_snippets(self.FIXTURE, None)
        self.assertEqual(len(snippets), 2, snippets)
        self.assertIn("FAIL on ramp rate", snippets[0])
        self.assertIn("and FAIL on inrush and current-limit clearance", snippets[0])
        self.assertIn("PASS on the ratified <= 6 ms settling clause", snippets[0])
        self.assertIn("PASS on ramp rate", snippets[1])
        self.assertIn(
            "FAIL on inrush, current-limit clearance, monotonicity", snippets[1]
        )

    def test_unbolded_prose_between_clauses_is_not_rendered_as_verdict(self):
        snippets = bcr.extract_verdict_snippets(self.FIXTURE, None)
        self.assertNotIn("points exceed the bound", snippets[0])
        self.assertNotIn("worst 1.28 ms", snippets[0])

    def test_split_verdict_classifies_as_mixed(self):
        snippets = bcr.extract_verdict_snippets(self.FIXTURE, None)
        self.assertEqual(bcr.classify(snippets), "MIXED")

    def test_a_blank_line_ends_a_verdict_statement(self):
        text = "**Overall: PASS** on everything.\n\n**Note**: unrelated bold run.\n"
        snippets = bcr.extract_verdict_snippets(text, None)
        self.assertEqual(snippets, ["Overall: PASS"])

    def test_a_sibling_list_item_ends_a_verdict_statement(self):
        text = (
            "- **Overall (current limit, ratified window): FAIL** - 36/63\n"
            "  corners outside the window, **and FAIL at 125 C**.\n"
            "- **Links**:\n"
            "  - Testbench: `sim/current-limit/testbench/tb.json`\n"
        )
        snippets = bcr.extract_verdict_snippets(text, None)
        self.assertEqual(len(snippets), 1, snippets)
        self.assertIn("Overall (current limit, ratified window): FAIL", snippets[0])
        self.assertIn("and FAIL at 125 C", snippets[0])
        self.assertNotIn("Links", snippets[0])

    def test_prose_emphasis_after_the_opener_is_not_a_verdict_clause(self):
        text = (
            "**Overall (the §4 experiment): conclusive.** The A/B moves the "
            "peak by -9.0%, ruling the ramp node **out** as the mechanism.\n"
        )
        self.assertEqual(
            bcr.extract_verdict_snippets(text, None),
            ["Overall (the §4 experiment): conclusive."],
        )

    def test_a_second_overall_opener_starts_a_new_verdict(self):
        text = (
            "**Overall (a): PASS** because of x, **and PASS on y**. "
            "**Overall (b): FAIL** because of z.\n"
        )
        snippets = bcr.extract_verdict_snippets(text, None)
        self.assertEqual(len(snippets), 2, snippets)
        self.assertIn("and PASS on y", snippets[0])
        self.assertNotIn("Overall (b)", snippets[0])
        self.assertIn("Overall (b): FAIL", snippets[1])


class TestLandedRecordRendering(unittest.TestCase):
    """Against the real, append-only records committed under sim/."""

    def test_the_record_that_surfaced_251_renders_its_dropped_clauses(self):
        text = MULTI_RUN_RECORD.read_text()
        rendered = " / ".join(bcr.extract_verdict_snippets(text, None))
        for clause in (
            "FAIL on inrush and current-limit clearance",
            "FAIL on inrush, current-limit clearance, monotonicity and peak",
            "T1, T2, T3 and T4 FAIL",
            "PASS on the ratified",
        ):
            self.assertIn(clause, rendered)
        # ... and its §4 verdict does not pick up the "ruling the ramp node
        # **out**" emphasis run that follows it in the same paragraph.
        self.assertTrue(
            rendered.endswith("§4 experiment): conclusive."), rendered
        )

    def test_superseded_single_run_record_renders_byte_identically(self):
        text = SINGLE_RUN_RECORD.read_text()
        legacy = [
            bcr._clean(m) for m in LEGACY_OVERALL_RE.findall(text)
        ]
        self.assertTrue(legacy, "oracle found no verdicts in the fixture record")
        self.assertEqual(bcr.extract_verdict_snippets(text, None), legacy)

    def test_no_landed_record_loses_or_rewrites_a_verdict(self):
        """Corpus-wide invariant against every committed record.

        For each record: the same number of `**Overall...**` verdicts as the
        pre-#251 extractor found, each rendered snippet starting with exactly
        the text that extractor produced. Records that stated a verdict as a
        single bold run therefore render byte-identically; the only permitted
        change is extra clauses appended to a verdict that was split.
        """
        self.assertGreater(len(RECORDS), 50, "record corpus not found")
        for record in RECORDS:
            text = record.read_text()
            legacy = [bcr._clean(m) for m in LEGACY_OVERALL_RE.findall(text)]
            if not legacy:
                continue
            with self.subTest(record=str(record.relative_to(SIM_DIR.parent))):
                current = bcr.extract_verdict_snippets(text, None)
                self.assertEqual(len(current), len(legacy))
                for now, before in zip(current, legacy):
                    self.assertTrue(
                        now.startswith(before),
                        f"verdict rewritten:\n  was: {before!r}\n  now: {now!r}",
                    )


class TestKeywordFilterAndFallback(unittest.TestCase):
    def test_keyword_still_selects_one_sub_claim(self):
        text = (
            "- **Overall (current limit, ratified 65-80 mA window): FAIL** - 36/63\n"
            "  corners outside the window.\n"
            "- **Overall (thermal, ratified <= 290 mW into a short): FAIL** -\n"
            "  worst-case 345.2 mW.\n"
        )
        cl = bcr.extract_verdict_snippets(text, "current limit")
        th = bcr.extract_verdict_snippets(text, "thermal")
        self.assertEqual(len(cl), 1, cl)
        self.assertEqual(len(th), 1, th)
        self.assertIn("current limit", cl[0])
        self.assertIn("thermal", th[0])
        self.assertNotIn("thermal", cl[0])
        self.assertNotIn("65-80 mA", th[0])

    def test_result_heading_fallback_for_records_without_an_overall_span(self):
        text = "# Record\n\n## Result: PASS\n\nSome prose.\n"
        self.assertEqual(bcr.extract_verdict_snippets(text, None), ["Result: PASS"])
        self.assertEqual(
            bcr.extract_verdict_snippets(text, "thermal"), ["Result: PASS"]
        )

    def test_a_record_with_no_verdict_at_all_is_unknown(self):
        self.assertEqual(bcr.extract_verdict_snippets("nothing here\n", None), [])
        self.assertEqual(bcr.classify([]), "UNKNOWN")


class TestUnmappedSlugCoverage(unittest.TestCase):
    """Every sim/<slug>/records/ directory reaches the rollup (issue #257).

    The rollup is only "the single file tying every row to its evidence" if
    an experiment cannot exist under sim/ without appearing in it. Before
    #257 an unmapped slug produced a stderr-only warning and exit 0, so
    `sim/soft-start-loop-gain/` -- real committed evidence -- appeared in
    neither the row table nor the appendix and CI (which diffs stdout only)
    stayed green.
    """

    def test_the_committed_tree_has_no_unmapped_slug(self):
        self.assertEqual(
            bcr.unmapped_slugs(),
            [],
            "a sim/<slug>/records/ directory reaches neither a ROWS entry "
            "nor SUPPORTING_SLUGS_NOTE -- map it before committing",
        )

    def test_soft_start_loop_gain_reaches_the_rendered_appendix(self):
        self.assertIn("soft-start-loop-gain", bcr.SUPPORTING_SLUGS_NOTE)
        self.assertIn("| `soft-start-loop-gain` |", bcr.render())

    def _run_generator(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_REPORT_PATH)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_an_unmapped_slug_makes_the_generator_exit_non_zero(self):
        """End-to-end against the real script, via a synthetic slug.

        Asserted through a subprocess rather than by calling main() so the
        exit status CI actually observes is the thing under test.
        """
        scratch = Path(
            tempfile.mkdtemp(prefix="zz-unmapped-selftest-", dir=SIM_DIR)
        )
        try:
            (scratch / "records").mkdir()
            (scratch / "records" / "20260101-000000-0000000.md").write_text(
                "# synthetic record\n\n**Overall: PASS**\n"
            )
            self.assertIn(scratch.name, bcr.unmapped_slugs())

            done = self._run_generator()
            self.assertNotEqual(
                done.returncode, 0, "unmapped slug did not fail the generator"
            )
            self.assertIn(scratch.name, done.stderr)
            # The report is still emitted, so regenerating into the committed
            # file does not truncate it -- the failure is the exit status.
            self.assertTrue(
                done.stdout.startswith("# Characterization report"), done.stdout[:200]
            )
        finally:
            shutil.rmtree(scratch)

    def test_the_generator_exits_zero_on_the_committed_tree(self):
        done = self._run_generator()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")


class TestClassify(unittest.TestCase):
    def test_pass_fail_mixed_unknown(self):
        self.assertEqual(bcr.classify(["Overall: PASS"]), "PASS")
        self.assertEqual(bcr.classify(["Overall: FAIL"]), "FAIL")
        self.assertEqual(bcr.classify(["Overall: PASS", "Overall: FAIL"]), "MIXED")
        self.assertEqual(bcr.classify(["Overall: PASS … and FAIL on x"]), "MIXED")
        self.assertEqual(bcr.classify(["Overall: conclusive"]), "UNKNOWN")


_MATRIX_FIELDS = [
    "corner_id",
    "process",
    "temp_c",
    "vin_v",
    "iload_ma",
    "ceff_uf",
    "esr_ohm",
    "vout_v",
    "dc_loop_gain_db",
    "f_crossover_hz",
    "phase_margin_deg",
    "f_180_hz",
    "gain_margin_db",
    "result",
    "resurgence_db",
    "resurgence_result",
]


def _matrix_row(
    iload_ma,
    ceff_uf,
    esr_ohm,
    result,
    pm=60.0,
    gm=20.0,
    resurgence_result="PASS",
):
    return {
        "corner_id": "tt_27c_3.30v",
        "process": "tt",
        "temp_c": "27",
        "vin_v": "3.30",
        "iload_ma": str(iload_ma),
        "ceff_uf": str(ceff_uf),
        "esr_ohm": str(esr_ohm),
        "vout_v": "1.8",
        "dc_loop_gain_db": "80",
        "f_crossover_hz": "1000",
        "phase_margin_deg": str(pm),
        "f_180_hz": "2000",
        "gain_margin_db": str(gm),
        "result": result,
        "resurgence_db": "-1.0",
        "resurgence_result": resurgence_result,
    }


class _EnvelopeFixture:
    """A scratch record + companion ``-matrix.csv`` under a tempdir, in the
    exact layout ``envelope_verdict()`` reads: ``<stem>.md`` next to
    ``<stem>-matrix.csv`` under a single ``records/`` directory.
    """

    def __init__(self, tmpdir: Path, rows: list[dict], overall: str = "PASS"):
        self.dir = tmpdir / "records"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.record = self.dir / "20260101-000000-0000000.md"
        self.record.write_text(f"# Fixture record\n\n**Overall: {overall}**\n")
        csv_path = self.dir / "20260101-000000-0000000-matrix.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_MATRIX_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)


class TestEnvelopeVerdict(unittest.TestCase):
    """``envelope_verdict()`` grades a record from its own ``-matrix.csv``
    subset, not from the record's top-level prose verdict (issue #276).
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = Path(self._tmp.name)

    def test_envelope_passes_when_every_in_envelope_point_passes(self):
        rows = [
            _matrix_row(0.1, 1.0, 0.2, "PASS"),
            _matrix_row(50, 1.0, 0.5, "PASS"),
            # Outside the envelope (0.33 uF) and FAILing -- must not affect
            # the envelope verdict, only the full-matrix count below.
            _matrix_row(50, 0.33, 0.001, "FAIL"),
        ]
        fixture = _EnvelopeFixture(self.tmpdir, rows, overall="PASS")
        env = bcr.envelope_verdict(fixture.record, bcr.DR0018_STABILITY_ENVELOPE)
        self.assertEqual(env["verdict"], "PASS")
        self.assertEqual(env["n_pass"], 2)
        self.assertEqual(env["n_total"], 2)
        self.assertEqual(env["n_pass_full"], 2)
        self.assertEqual(env["n_total_full"], 3)

    def test_a_failing_point_inside_the_envelope_fails_the_row_even_when_the_records_own_prose_says_pass(self):
        """The core case the issue's Acceptance Criteria calls out: a point
        *inside* the ratified envelope fails, so the row must go FAIL --
        proving the filter drives the outcome, not the record's own
        top-level prose verdict.
        """
        rows = [
            _matrix_row(0.1, 1.0, 0.2, "PASS"),
            # Inside the envelope (1 uF, 0.5 ohm, 25 mA) and FAILing.
            _matrix_row(25, 1.0, 0.5, "FAIL", pm=10.0, gm=1.0),
        ]
        fixture = _EnvelopeFixture(self.tmpdir, rows, overall="PASS")

        # The record's own prose verdict (what the old extractor used) says
        # PASS -- confirm that channel still reads PASS, to prove the two
        # disagree and it is the envelope filter, not the prose, that wins.
        prose_snippets = bcr.extract_verdict_snippets(fixture.record.read_text(), None)
        self.assertEqual(bcr.classify(prose_snippets), "PASS")

        env = bcr.envelope_verdict(fixture.record, bcr.DR0018_STABILITY_ENVELOPE)
        self.assertEqual(env["verdict"], "FAIL")
        self.assertEqual(env["n_pass"], 1)
        self.assertEqual(env["n_total"], 2)

    def test_a_resurgence_flag_inside_the_envelope_fails_the_row_even_if_the_margin_result_column_passes(self):
        rows = [
            _matrix_row(10, 1.0, 0.2, "PASS", resurgence_result="FAIL"),
        ]
        fixture = _EnvelopeFixture(self.tmpdir, rows, overall="PASS")
        env = bcr.envelope_verdict(fixture.record, bcr.DR0018_STABILITY_ENVELOPE)
        self.assertEqual(env["verdict"], "FAIL")
        self.assertEqual(env["n_resurge_flagged"], 1)

    def test_no_matrix_csv_is_unknown_not_a_crash(self):
        records_dir = self.tmpdir / "records"
        records_dir.mkdir()
        record = records_dir / "20260101-000000-0000000.md"
        record.write_text("# Fixture record\n\n**Overall: PASS**\n")
        env = bcr.envelope_verdict(record, bcr.DR0018_STABILITY_ENVELOPE)
        self.assertEqual(env, {"available": False, "verdict": "UNKNOWN"})

    def test_no_point_inside_the_envelope_is_unknown(self):
        rows = [_matrix_row(50, 0.33, 0.001, "FAIL")]  # all outside the envelope
        fixture = _EnvelopeFixture(self.tmpdir, rows, overall="FAIL")
        env = bcr.envelope_verdict(fixture.record, bcr.DR0018_STABILITY_ENVELOPE)
        self.assertEqual(env["verdict"], "UNKNOWN")
        self.assertEqual(env["n_total"], 0)
        self.assertEqual(env["n_total_full"], 1)

    def test_rendered_snippet_names_the_decision_record_and_shows_the_full_matrix_count(self):
        rows = [
            _matrix_row(0.1, 1.0, 0.2, "PASS", pm=55.0, gm=12.0),
            _matrix_row(50, 0.33, 0.001, "FAIL"),
        ]
        fixture = _EnvelopeFixture(self.tmpdir, rows, overall="PASS")
        env = bcr.envelope_verdict(fixture.record, bcr.DR0018_STABILITY_ENVELOPE)
        snippet = bcr._render_envelope_snippet(env, bcr.DR0018_STABILITY_ENVELOPE)
        self.assertIn("DR-0018", snippet)
        self.assertIn("PASS", snippet)
        self.assertIn("1/1", snippet)
        # The wider-matrix result must stay visible alongside the envelope
        # verdict, not be dropped (issue #276 acceptance criteria).
        self.assertIn("1/2 passing", snippet)


class TestStabilityRowUsesEnvelopeVerdict(unittest.TestCase):
    """End-to-end against the real committed head record (issue #276): the
    rendered Stability row must grade against DR-0018's ratified envelope,
    not DR-0001's original full matrix, while still showing the full-matrix
    result.
    """

    def test_stability_row_is_defined_with_the_dr0018_envelope(self):
        stability = next(r for r in bcr.ROWS if r.name == "Stability")
        self.assertEqual(len(stability.sources), 1)
        self.assertIs(stability.sources[0].envelope, bcr.DR0018_STABILITY_ENVELOPE)

    def test_rendered_report_shows_the_ratified_envelope_verdict_and_the_full_matrix_count(self):
        report = bcr.render()
        self.assertIn("| Stability | PASS | fresh |", report)
        stability_section = report.split("### Stability")[1].split("###")[0]
        self.assertIn("DR-0018", stability_section)
        self.assertIn("630/630", stability_section)
        self.assertIn("2974/4536", stability_section)


if __name__ == "__main__":
    unittest.main()
