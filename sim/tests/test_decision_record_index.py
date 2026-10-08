#!/usr/bin/env python3
"""Unit tests for spec/decision-records/build_index.py (issue #362).

    python3 -m unittest discover -s sim/tests -v

Parser behaviour on fixture text, plus a check that every committed record
classifies. No PDK, no ngspice, no network.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_PATH = REPO / "spec" / "decision-records" / "build_index.py"
_spec = importlib.util.spec_from_file_location("dr_build_index", _PATH)
bi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bi)


class StatusBlockTests(unittest.TestCase):
    def test_single_line(self):
        self.assertEqual(bi.status_block("# t\n\n- **Status**: proposed\n- **Date**: x\n"), "proposed")

    def test_continuation_lines_joined_until_blank(self):
        text = "- **Status**: **ratified 2026-09-15** by\n  the operator\n\nbody\n"
        self.assertEqual(bi.status_block(text), "**ratified 2026-09-15** by the operator")

    def test_missing(self):
        self.assertIsNone(bi.status_block("# t\n\nno status\n"))


class ClassifyTests(unittest.TestCase):
    def test_plain_words(self):
        self.assertEqual(bi.classify(1, "ratified"), ("ratified", ""))
        self.assertEqual(bi.classify(1, "proposed -- ratification is the operator's"), ("proposed", ""))

    def test_bold_markup_and_case(self):
        self.assertEqual(bi.classify(1, "**Ratified 2026-08-06** by x")[0], "ratified")

    def test_superseded_by(self):
        self.assertEqual(bi.classify(1, "superseded by DR-0042"), ("superseded", "DR-0042"))
        self.assertEqual(bi.classify(1, "superseded by `DR-0042`")[1], "DR-0042")

    def test_superseded_without_target_fails(self):
        with self.assertRaises(bi.ClassifyError):
            bi.classify(1, "superseded")

    def test_unclassifiable_fails(self):
        with self.assertRaises(bi.ClassifyError):
            bi.classify(99, "HELD pending review")
        with self.assertRaises(bi.ClassifyError):
            bi.classify(99, None)

    def test_override_table(self):
        self.assertEqual(bi.classify(7, "**proposed -- HELD**")[0], "held")


class RenderTests(unittest.TestCase):
    def _write(self, d, name, body):
        (Path(d) / name).write_text(body, encoding="utf-8")

    def test_build_counts_and_order(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "DR-0002-b.md", "# DR-0002: B | pipe\n\n- **Status**: proposed\n")
            self._write(d, "DR-0001-a.md", "# DR-0001: A\n\n- **Status**: ratified\n")
            self._write(d, "TEMPLATE.md", "# DR-0000: template\n")
            out = bi.build(Path(d))
        self.assertIn("2 records: 1 ratified, 1 proposed, 0 held, 0 superseded.", out)
        self.assertLess(out.index("DR-0001"), out.index("DR-0002"))
        self.assertIn("B \\| pipe", out)
        self.assertNotIn("DR-0000", out)

    def test_title_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "DR-0001-a.md", "# DR-0009: A\n\n- **Status**: ratified\n")
            with self.assertRaises(bi.ClassifyError):
                bi.build(Path(d))


class CommittedRecordsTests(unittest.TestCase):
    def test_all_committed_records_classify(self):
        out = bi.build()
        self.assertIn("DR-0001", out)

    def test_committed_readme_is_current(self):
        readme = (REPO / "spec" / "decision-records" / "README.md").read_text(encoding="utf-8")
        self.assertEqual(readme, bi.build())


if __name__ == "__main__":
    unittest.main()
