#!/usr/bin/env python3
"""Unit tests for sim/check_append_only.py (issue #371). Tool-free."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_append_only", REPO / "sim" / "check_append_only.py")
cao = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cao)

REC = "sim/psrr-dc/records/20260101-000000-abc1234.md"
LOG = "sim/psrr-dc/corners/20260101-000000-abc1234/tt_27c_3.3v.log"


class ClassifyTests(unittest.TestCase):
    def v(self, text, allow=None):
        return cao.classify(text, allow)[0]

    def test_added_ok(self):
        self.assertEqual(self.v(f"A\t{REC}\nA\t{LOG}\n"), [])

    def test_modified_deleted_fail(self):
        self.assertEqual(len(self.v(f"M\t{REC}\nD\t{LOG}\n")), 2)

    def test_type_change_fails(self):
        self.assertEqual(len(self.v(f"T\t{REC}\n")), 1)

    def test_rename_out_of_protected_fails(self):
        self.assertEqual(len(self.v(f"R100\t{REC}\tdocs/x.md\n")), 1)

    def test_rename_within_protected_fails(self):
        self.assertEqual(len(self.v(f"R090\t{REC}\tsim/a/records/x.md\n")), 1)

    def test_rename_into_protected_ok(self):
        self.assertEqual(self.v(f"R100\tdocs/x.md\t{REC}\n"), [])

    def test_copy_ok(self):
        self.assertEqual(self.v(f"C100\t{REC}\tsim/a/records/x.md\n"), [])

    def test_unprotected_paths_ignored(self):
        self.assertEqual(self.v("M\tsim/README.md\nD\tsim/psrr-dc/testbench/a.sp\n"
                                "M\tsignoff/records/t1-tier-report.json\n"), [])

    def test_layout_records_protected(self):
        self.assertEqual(len(self.v("M\tlayout/records/x.md\n")), 1)

    def test_blank_lines(self):
        self.assertEqual(self.v("\n\n"), [])

    def test_allowlist(self):
        viol, ok = cao.classify(f"M\t{REC}\n", {REC: "DR-0001"})
        self.assertEqual(viol, [])
        self.assertIn("DR-0001", ok[0])

    def test_allowlist_is_exact_path(self):
        viol, _ = cao.classify(f"M\t{LOG}\n", {REC: "DR-0001"})
        self.assertEqual(len(viol), 1)


class AllowlistParseTests(unittest.TestCase):
    def test_parse(self):
        got = cao.parse_allowlist("# c\n\nsim/a/records/x.md DR-0042  # why\n")
        self.assertEqual(got, {"sim/a/records/x.md": "DR-0042"})

    def test_missing_dr_rejected(self):
        with self.assertRaises(ValueError):
            cao.parse_allowlist("sim/a/records/x.md\n")

    def test_bad_dr_rejected(self):
        with self.assertRaises(ValueError):
            cao.parse_allowlist("sim/a/records/x.md DR-42\n")

    def test_committed_allowlist_parses(self):
        p = cao.DEFAULT_ALLOWLIST
        if p.exists():
            cao.parse_allowlist(p.read_text())


if __name__ == "__main__":
    unittest.main()
