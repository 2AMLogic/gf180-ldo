#!/usr/bin/env python3
"""Tests for sim/check_record_reading.py (issue #606).

Uses a throwaway git repo to exercise real pathspec selection, mirroring
sim/tests/test_check_record_host_paths.py. Synthetic records only; no ngspice,
KLayout, or PDK.
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
    "check_record_reading", REPO / "sim" / "check_record_reading.py")
crr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crr)

HEAD = "# Run 20261113-223722\n\n## Results\n\n| corner | V |\n|---|---|\n"
# The placeholder as sim/harness/klt_record.py:219 actually mints it, built
# from the module constant so the two can never drift apart.
MINTED = HEAD + f"\n## Reading\n\n{crr.PLACEHOLDERS[0]}\n"
EMPTY = HEAD + "\n## Reading\n\n\n   \n"
EMPTY_THEN_HEADING = HEAD + "\n## Reading\n\n## Not done\n\nnothing\n"
WRITTEN = HEAD + "\n## Reading\n\nDropout is 180 mV at 150 mA, within DR-0006.\n"
# sim/soft-start/records/20261105-ss-351-peak-pvt.md's shape: a complete
# hand-written record with no `## Reading` section at all. Must pass.
NO_SECTION = HEAD + "\n## Verdict\n\nPASS\n\n## Coverage\n\nAll 9 PVT corners.\n"

HIST = "layout/records/old.md"
LAYOUT = "layout/records/new.md"
SIM = "sim/psrr-dc/records/new.md"
SIGNOFF = "signoff/records/new.md"


class ReadingSectionGuardTests(unittest.TestCase):
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
        self.write(HIST, MINTED)  # historical evidence, placeholder and all
        self.git("add", "-A")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *a):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a],
            check=True, capture_output=True, text=True).stdout

    def commit(self, msg):
        self.git("commit", "-q", "-m", msg)

    def write(self, rel, text, newline=None):
        p = Path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, newline=newline)

    def run_guard(self, files, remove=()):
        for rel, text in files.items():
            self.write(rel, text)
        for rel in remove:
            Path(rel).unlink()
        self.git("add", "-A")
        self.commit("pr")
        self.out = io.StringIO()
        with contextlib.redirect_stdout(self.out):
            return crr.main(["--base", self.base])

    # --- the placeholder rule -------------------------------------------
    def test_minted_placeholder_fails(self):
        self.assertEqual(self.run_guard({SIM: MINTED}), 1)
        self.assertIn(f"{SIM}:10:", self.out.getvalue())
        self.assertIn("::error::", self.out.getvalue())

    def test_placeholder_reported_even_without_reading_heading(self):
        self.assertEqual(self.run_guard({SIM: HEAD + "\n(to be written)\n"}), 1)

    # --- the empty-section rule -----------------------------------------
    def test_blank_reading_body_fails(self):
        self.assertEqual(self.run_guard({SIM: EMPTY}), 1)
        self.assertIn("empty body", self.out.getvalue())

    def test_reading_body_that_is_only_the_next_heading_fails(self):
        self.assertEqual(self.run_guard({SIM: EMPTY_THEN_HEADING}), 1)

    def test_written_reading_section_passes(self):
        self.assertEqual(self.run_guard({SIM: WRITTEN}), 0)

    def test_reading_body_of_only_a_code_fence_passes(self):
        body = HEAD + "\n## Reading\n\n```\nvout = 1.80 V\n```\n"
        self.assertEqual(self.run_guard({SIM: body}), 0)

    # --- the asymmetry: no section at all is fine (regression, #606) -----
    def test_record_with_no_reading_section_passes(self):
        self.assertEqual(self.run_guard({SIM: NO_SECTION}), 0)

    def test_reading_heading_inside_code_fence_is_not_a_heading(self):
        fenced = HEAD + "\n## Verdict\n\nPASS\n\n```\n## Reading\n```\n"
        self.assertEqual(self.run_guard({SIM: fenced}), 0)

    # --- edge cases ------------------------------------------------------
    def test_prose_on_the_heading_line_passes(self):
        inline = HEAD + "\n## Reading: dropout is 180 mV\n\n## Not done\n\nx\n"
        self.assertEqual(self.run_guard({SIM: inline}), 0)

    def test_similar_heading_is_not_the_reading_heading(self):
        self.assertEqual(self.run_guard({SIM: HEAD + "\n## Readings\n\n"}), 0)

    def test_crlf_record_with_placeholder_fails(self):
        self.assertEqual(self.run_guard({SIM: MINTED.replace("\n", "\r\n")}), 1)

    def test_crlf_record_with_written_reading_passes(self):
        self.assertEqual(
            self.run_guard({SIM: WRITTEN.replace("\n", "\r\n")}), 0)

    def test_non_utf8_byte_does_not_crash(self):
        Path(SIM).parent.mkdir(parents=True, exist_ok=True)
        Path(SIM).write_bytes(WRITTEN.encode() + b"\xff\n")
        self.git("add", "-A")
        self.commit("pr")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(crr.main(["--base", self.base]), 0)

    def test_empty_reading_at_end_of_file_fails(self):
        self.assertEqual(self.run_guard({SIM: HEAD + "\n## Reading\n"}), 1)

    # --- pathspec and diff-filter scoping --------------------------------
    def test_layout_record_fails(self):
        self.assertEqual(self.run_guard({LAYOUT: MINTED}), 1)

    def test_signoff_record_fails(self):
        self.assertEqual(self.run_guard({SIGNOFF: MINTED}), 1)

    def test_unchanged_historical_record_ignored(self):
        self.assertEqual(self.run_guard({"README.md": "x\n"}), 0)

    def test_modified_historical_record_fails(self):
        self.assertEqual(self.run_guard({HIST: MINTED + "\nmore\n"}), 1)

    def test_file_outside_pathspecs_not_scanned(self):
        self.assertEqual(self.run_guard({"docs/x.md": MINTED}), 0)

    def test_deleted_record_not_scanned(self):
        self.assertEqual(self.run_guard({"README.md": "x\n"}, remove=[HIST]), 0)

    def test_selector_covers_top_level_layout_records(self):
        self.write(LAYOUT, WRITTEN)
        self.git("add", "-A")
        listed = self.git("ls-files", "--", *crr.PATHSPECS).split()
        self.assertIn(LAYOUT, listed)


class PlaceholderConstantTests(unittest.TestCase):
    def test_constant_matches_what_klt_record_actually_mints(self):
        """PLACEHOLDERS must track sim/harness/klt_record.py's minting line."""
        minted = (REPO / "sim" / "harness" / "klt_record.py").read_text()
        self.assertIn('"## Reading"', minted)
        self.assertTrue(
            any(f'"{ph}"' in minted for ph in crr.PLACEHOLDERS),
            f"klt_record.py mints a placeholder absent from PLACEHOLDERS "
            f"({crr.PLACEHOLDERS}) -- add it there, the gate's single source "
            f"of truth.")


if __name__ == "__main__":
    unittest.main()
