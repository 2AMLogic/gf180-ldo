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


if __name__ == "__main__":
    unittest.main()
