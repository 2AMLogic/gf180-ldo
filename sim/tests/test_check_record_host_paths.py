#!/usr/bin/env python3
"""Tests for sim/check_record_host_paths.py (issue #413).

Uses a throwaway git repo to exercise real pathspec selection. Synthetic
paths only; no ngspice, KLayout, or PDK.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_record_host_paths", REPO / "sim" / "check_record_host_paths.py")
crhp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crhp)

BAD = "log at /home/alice/work/run.log\n"
GOOD = "log at sim/psrr-dc/run.log\n"
HIST = "layout/records/old.md"
LAYOUT = "layout/records/new.md"
SIM = "sim/psrr-dc/records/new.md"
SIGNOFF = "signoff/records/new.md"


class HostPathGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.cwd)
        self.git("init", "-q")
        # No detached background gc/maintenance racing temp-dir cleanup.
        self.git("config", "gc.auto", "0")
        self.git("config", "maintenance.auto", "false")
        self.write(HIST, BAD)  # historical evidence with a host path
        self.git("add", "-A")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *a):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a],
            check=True, capture_output=True, text=True).stdout

    def commit(self, msg):
        self.git("commit", "-q", "-m", msg)

    def write(self, rel, text):
        p = Path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def run_guard(self, files):
        for rel, text in files.items():
            self.write(rel, text)
        self.git("add", "-A")
        self.commit("pr")
        with contextlib.redirect_stdout(io.StringIO()):
            return crhp.main(["--base", self.base])

    def test_new_layout_record_with_host_path_fails(self):
        self.assertEqual(self.run_guard({LAYOUT: BAD}), 1)

    def test_new_layout_record_relative_paths_pass(self):
        self.assertEqual(self.run_guard({LAYOUT: GOOD}), 0)

    def test_unchanged_historical_record_ignored(self):
        self.assertEqual(self.run_guard({"README.md": "x\n"}), 0)

    def test_modified_historical_record_fails(self):
        self.assertEqual(self.run_guard({HIST: BAD + "more\n"}), 1)

    def test_sim_record_with_host_path_fails(self):
        self.assertEqual(self.run_guard({SIM: BAD}), 1)

    def test_signoff_record_with_host_path_fails(self):
        self.assertEqual(self.run_guard({SIGNOFF: BAD}), 1)

    def test_macos_style_path_fails(self):
        self.assertEqual(
            self.run_guard({LAYOUT: "/Users/bob/x\n"}), 1)

    def test_unrelated_file_not_scanned(self):
        self.assertEqual(self.run_guard({"docs/x.md": BAD}), 0)

    def test_selector_covers_top_level_layout_records(self):
        self.write(LAYOUT, GOOD)
        self.git("add", "-A")
        listed = self.git("ls-files", "--", *crhp.PATHSPECS).split()
        self.assertIn(LAYOUT, listed)


if __name__ == "__main__":
    unittest.main()
