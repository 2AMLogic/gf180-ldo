#!/usr/bin/env python3
"""Tests for sim/record_selection.py, the shared record selector (#854).

sim/check_record_host_paths.py and sim/check_record_reading.py both ask
"which records did this diff add or modify?" and used to answer with two
copies of the same three pathspecs and the same git query -- the Reading
check's copy even carried a comment asking maintainers to keep it
identical. One copy drifting is how a record location silently falls out
of one gate while it stays green, the shape of #413's missed top-level
layout/records/. These tests pin the one shared definition and that both
gates bind *it*, not a private re-implementation.

Uses a throwaway git repo to exercise real pathspec selection, mirroring
sim/tests/test_check_record_host_paths.py. Synthetic records only; no
ngspice, KLayout, or PDK.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness.loader import load_script  # noqa: E402

import record_selection as sel  # noqa: E402

crhp = load_script(
    "check_record_host_paths", REPO / "sim" / "check_record_host_paths.py")
crr = load_script(
    "check_record_reading", REPO / "sim" / "check_record_reading.py")

HIST = "layout/records/old.md"
LAYOUT = "layout/records/new.md"
SIM = "sim/psrr-dc/records/new.md"
SIGNOFF = "signoff/records/new.md"


class SharedSelectorTests(unittest.TestCase):
    def test_pathspecs_are_the_three_record_locations(self):
        # The canary for adding a fourth location: update it here and in
        # sim/record_selection.py only -- both gates follow (issue #854).
        self.assertEqual(
            sel.PATHSPECS,
            ("sim/*/records/*", "signoff/records/*", "layout/records/*"))

    def test_both_gates_bind_the_shared_selector(self):
        # Identity, not equality: a gate that re-defines its own
        # changed_files -- however equal -- has re-opened the drift these
        # tests exist to close. PATHSPECS is bound only by record_selection
        # itself (the gates have no reason to name it), but should one ever
        # re-export it, it must be the shared object, never a private tuple.
        self.assertIs(crhp.changed_files, sel.changed_files)
        self.assertIs(crr.changed_files, sel.changed_files)
        for mod in (crhp, crr):
            self.assertIs(getattr(mod, "PATHSPECS", sel.PATHSPECS),
                          sel.PATHSPECS)


class ChangedFilesTests(unittest.TestCase):
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
        self.write(HIST, "historical evidence\n")
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

    def select(self, files, remove=()):
        for rel, text in files.items():
            self.write(rel, text)
        for rel in remove:
            Path(rel).unlink()
        self.git("add", "-A")
        self.commit("pr")
        return sel.changed_files(self.base)

    def test_added_records_in_all_three_locations_listed(self):
        found = self.select({LAYOUT: "x\n", SIM: "x\n", SIGNOFF: "x\n"})
        self.assertEqual(sorted(found), sorted([LAYOUT, SIM, SIGNOFF]))

    def test_modified_historical_record_listed(self):
        self.assertEqual(self.select({HIST: "x\nmore\n"}), [HIST])

    def test_unchanged_historical_record_not_listed(self):
        self.assertEqual(self.select({"README.md": "x\n"}), [])

    def test_deleted_record_not_listed(self):
        # Deletions are append-only's problem (sim/check_append_only.py),
        # not these gates': --diff-filter=AM excludes them.
        self.assertEqual(
            self.select({"README.md": "x\n"}, remove=[HIST]), [])

    def test_file_outside_pathspecs_not_listed(self):
        self.assertEqual(self.select({"docs/x.md": "x\n"}), [])

    def test_unavailable_base_raises(self):
        # The CLI gates map this to their exit-2 "base unavailable"
        # diagnostics; the selector itself must raise, never return [].
        with self.assertRaises(subprocess.CalledProcessError):
            sel.changed_files("0123456789abcdef0123456789abcdef01234567")


if __name__ == "__main__":
    unittest.main()
