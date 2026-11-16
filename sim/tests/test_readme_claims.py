#!/usr/bin/env python3
"""Unit tests for signoff/readme_claims.py (issue #398). Tool-free."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "readme_claims", REPO / "signoff" / "readme_claims.py")
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)

REC = {"tier": None, "t1_met_count": 1, "t1_item_count": 11}
ROOT = "Today it reads **`tier: null`, T1 1 of 11 items met**. See"
SIGN = "**Today: `tier: null`, T1 1/11 items met** (item 8 only)."


def table(items):
    """Render a per-item table from (id, status, reason) triples."""
    header = "| # | Status | Reading |\n|---|---|---|\n"
    rows = []
    for item_id, status, reason in items:
        cell = f"`{status}`" if reason is None else f"`{status}` / `{reason}`"
        rows.append(f"| {item_id} | {cell} | analysis prose |")
    return header + "\n".join(rows)


def record(items):
    """Build a record dict from (id, status, reason) triples."""
    return {"tier": None, "t1_met_count": 1, "t1_item_count": 11,
            "items": [{"tier": "T1", "id": i, "status": s, "reason": r}
                      for i, s, r in items]}


GOOD = [
    (1, "met", None), (2, "unmet", "no_evidence"), (5, "unmet", "partial_coverage"),
]


class FindClaimsTests(unittest.TestCase):
    def test_both_phrasings(self):
        self.assertEqual(rc.find_claims(ROOT), [("null", 1, 11)])
        self.assertEqual(rc.find_claims(SIGN), [("null", 1, 11)])

    def test_line_wrapped(self):
        self.assertEqual(
            rc.find_claims("Today it reads `tier: null`,\nT1 1 of\n11 items met"),
            [("null", 1, 11)])

    def test_non_null_tier(self):
        self.assertEqual(
            rc.find_claims("Today: `tier: T1`, T1 11/11 items met"),
            [("T1", 11, 11)])

    def test_no_claim(self):
        self.assertEqual(rc.find_claims("nothing here"), [])


class CheckTests(unittest.TestCase):
    def test_current_passes(self):
        self.assertEqual(rc.check(REC, {"a": ROOT, "b": SIGN}), [])

    def test_count_drift_fails(self):
        rec = dict(REC, t1_met_count=2)
        errs = rc.check(rec, {"a": ROOT, "b": SIGN})
        self.assertEqual(len(errs), 2)
        self.assertIn("a:", errs[0])

    def test_total_drift_fails(self):
        errs = rc.check(dict(REC, t1_item_count=12), {"a": ROOT})
        self.assertEqual(len(errs), 1)

    def test_tier_drift_fails(self):
        errs = rc.check(dict(REC, tier="T1"), {"a": ROOT})
        self.assertEqual(len(errs), 1)

    def test_missing_sentence_in_one_file_fails(self):
        errs = rc.check(REC, {"a": ROOT, "b": "no claim"})
        self.assertEqual(len(errs), 1)
        self.assertIn("b:", errs[0])

    def test_real_tree_is_consistent(self):
        import json
        rec = json.load(open(REPO / "signoff/records/t1-tier-report.json"))
        texts = {p: (REPO / p).read_text() for p in ("README.md", "signoff/README.md")}
        self.assertEqual(rc.check(rec, texts), [])


class TableRowsTests(unittest.TestCase):
    def test_plain_cells(self):
        rows = rc.table_rows(table(GOOD))
        self.assertEqual(rows, [(1, "met"), (2, "unmet / no_evidence"),
                                (5, "unmet / partial_coverage")])

    def test_header_and_separator_ignored(self):
        self.assertEqual(rc.table_rows("| # | Status | Reading |\n"
                                       "|---|---|---|"), [])

    def test_no_table(self):
        self.assertEqual(rc.table_rows(ROOT + "\nno table here"), [])


class CheckTablesTests(unittest.TestCase):
    def test_no_table_file_passes(self):
        # The top-level README.md has no per-item table; it must not be
        # forced to grow one (issue #617, Out of Scope).
        self.assertEqual(rc.check_tables(record(GOOD), {"a": ROOT}), [])

    def test_matching_table_passes(self):
        self.assertEqual(rc.check_tables(record(GOOD), {"a": table(GOOD)}), [])

    def test_met_row_null_reason_passes(self):
        self.assertEqual(rc.check_tables(record([(1, "met", None)]),
                                         {"a": table([(1, "met", None)])}), [])

    def test_item5_reason_drift_is_the_ac3_failing_case(self):
        # Built from the real pre-fix cell at signoff/README.md (item 5 said
        # `no_evidence` while the record grades `partial_coverage`).
        rec = record([(5, "unmet", "partial_coverage")])
        text = {"signoff/README.md": table([(5, "unmet", "no_evidence")])}
        errs = rc.check_tables(rec, text)
        self.assertEqual(len(errs), 1)
        self.assertIn("signoff/README.md", errs[0])
        self.assertIn("item 5", errs[0])
        self.assertIn("unmet / no_evidence", errs[0])
        self.assertIn("unmet / partial_coverage", errs[0])

    def test_says_met_but_record_unmet_fails(self):
        errs = rc.check_tables(record([(2, "unmet", "no_evidence")]),
                               {"a": table([(2, "met", None)])})
        self.assertEqual(len(errs), 1)
        self.assertIn("item 2", errs[0])
        self.assertIn("but the record says unmet / no_evidence", errs[0])

    def test_wrong_reason_fails(self):
        errs = rc.check_tables(record([(5, "unmet", "no_evidence")]),
                               {"a": table([(5, "unmet", "partial_coverage")])})
        self.assertEqual(len(errs), 1)
        self.assertIn("unmet / partial_coverage", errs[0])
        self.assertIn("unmet / no_evidence", errs[0])

    def test_unparseable_cell_fails(self):
        errs = rc.check_tables(record([(3, "unmet", "no_evidence")]),
                               {"a": table([(3, "partly", None)])})
        self.assertEqual(len(errs), 1)
        self.assertIn("neither 'met' nor 'unmet / <reason>'", errs[0])

    def test_missing_row_fails(self):
        errs = rc.check_tables(record(GOOD), {"a": table(GOOD[:2])})
        self.assertEqual(len(errs), 1)
        self.assertIn("no row for item(s) 5", errs[0])

    def test_duplicate_row_fails(self):
        text = table(GOOD) + "\n" + table(GOOD[:1]).splitlines()[-1]
        errs = rc.check_tables(record(GOOD), {"a": text})
        self.assertEqual(len(errs), 1)
        self.assertIn("item 1 has more than one table row", errs[0])

    def test_unknown_id_fails(self):
        text = table(GOOD) + "\n| 12 | `met` | analysis prose |"
        errs = rc.check_tables(record(GOOD), {"a": text})
        self.assertEqual(len(errs), 1)
        self.assertIn("row for item 12 but the record has no such item", errs[0])

    def test_real_tree_tables_match_record(self):
        # Fails against the pre-fix tree (the item 5 row said no_evidence);
        # the regression fence keeping the prose fix honest (#617).
        import json
        rec = json.load(open(REPO / "signoff/records/t1-tier-report.json"))
        texts = {p: (REPO / p).read_text() for p in ("README.md", "signoff/README.md")}
        self.assertEqual(rc.check_tables(rec, texts), [])


if __name__ == "__main__":
    unittest.main()
