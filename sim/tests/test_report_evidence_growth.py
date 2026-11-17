#!/usr/bin/env python3
"""Unit tests for sim/report_evidence_growth.py (issue #388). Tool-free."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness.loader import load_script  # noqa: E402

reg = load_script("report_evidence_growth", REPO / "sim" / "report_evidence_growth.py")

Z = "0" * 40


def raw(status, path, sha, old=None):
    """One `git diff --raw -M --no-abbrev` line."""
    paths = f"{old}\t{path}" if old else path
    return f":100644 100644 {'1' * 40} {sha} {status}\t{paths}\n"


SIZES = {"a" * 40: 1000, "b" * 40: 2048, "c" * 40: 5, "d" * 40: 3 << 20}


def size_of(sha):
    return SIZES[sha]


class SummarizeTests(unittest.TestCase):
    def s(self, text):
        return reg.summarize(text, size_of)

    def test_per_slug_aggregation(self):
        t = (raw("A", "sim/x/corners/1/a.log", "a" * 40)
             + raw("A", "sim/x/corners/1/b.log", "b" * 40)
             + raw("A", "sim/y/records/r.md", "c" * 40))
        self.assertEqual(self.s(t), {"x": (2, 3048), "y": (1, 5)})

    def test_modified_counts_bytes_not_files(self):
        self.assertEqual(self.s(raw("M", "sim/x/README.md", "a" * 40)),
                         {"x": (0, 1000)})

    def test_deleted_adds_nothing(self):
        self.assertEqual(self.s(raw("D", "sim/x/a.log", Z)), {})

    def test_rename_counts_destination(self):
        t = raw("R100", "sim/y/new.log", "a" * 40, old="sim/x/old.log")
        self.assertEqual(self.s(t), {"y": (1, 1000)})

    def test_copy_counts_as_new(self):
        t = raw("C100", "sim/y/copy.log", "b" * 40, old="sim/x/old.log")
        self.assertEqual(self.s(t), {"y": (1, 2048)})

    def test_binary_counted_by_size(self):
        self.assertEqual(self.s(raw("A", "sim/x/plot.png", "d" * 40)),
                         {"x": (1, 3 << 20)})

    def test_non_sim_paths_ignored(self):
        t = raw("A", "docs/a.md", "a" * 40) + raw("A", "simx/a", "a" * 40)
        self.assertEqual(self.s(t), {})

    def test_sim_root_row(self):
        self.assertEqual(self.s(raw("A", "sim/new_tool.py", "c" * 40)),
                         {reg.ROOT_ROW: (1, 5)})

    def test_empty_diff(self):
        self.assertEqual(self.s(""), {})
        self.assertIn("No files added", reg.render({}))


class RenderTests(unittest.TestCase):
    def test_table_and_total(self):
        out = reg.render({"x": (2, 3048), "y": (1, 3 << 20)})
        self.assertIn("| `x` | 2 | 3.0 KiB | 3048 |", out)
        self.assertIn("| `y` | 1 | 3.00 MiB | 3145728 |", out)
        self.assertIn("| **Total** | 3 |", out)
        self.assertIn(f"| {3048 + (3 << 20)} |", out)


class MainTests(unittest.TestCase):
    def run_main(self, argv):
        buf = io.StringIO()
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(buf):
            rc = reg.main(argv)
        return rc, buf.getvalue()

    def test_git_failure_exits_zero_with_warning(self):
        with mock.patch.object(reg, "_git", side_effect=RuntimeError("bad ref")):
            rc, out = self.run_main(["--base", "nope"])
        self.assertEqual(rc, 0)
        self.assertIn("::warning::growth report unavailable: bad ref", out)
        self.assertIn("growth report unavailable: bad ref", out)
        self.assertNotIn("::error::", out)

    def test_success_path_uses_git_sizes(self):
        diff = raw("A", "sim/x/a.log", "a" * 40)
        with mock.patch.object(reg, "_git", side_effect=[
                diff, f"{'a' * 40} blob 1000\n"]):
            rc, out = self.run_main([])
        self.assertEqual(rc, 0)
        self.assertIn("| `x` | 1 | 1000 B | 1000 |", out)


if __name__ == "__main__":
    unittest.main()
