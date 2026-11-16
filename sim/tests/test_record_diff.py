#!/usr/bin/env python3
"""Unit tests for signoff/record_diff.py (issue #623). Tool-free."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "record_diff", REPO / "signoff" / "record_diff.py")
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)

RECORD_PATH = REPO / "signoff" / "records" / "t1-tier-report.json"
RECORD = json.loads(RECORD_PATH.read_text())


def stale_fixture(item_id: int, member_status: str = "stale",
                  reason: str = "stale_evidence") -> dict:
    """A fresh-run copy with item_id refused for stale anchored evidence.

    Mirrors what klt signoff emits at the pinned KLT_REV: status unmet,
    citation None, and the stale member list under
    detail.artifact_binding.members (issue #623's curation).
    """
    fresh = copy.deepcopy(RECORD)
    for item in fresh["items"]:
        if item.get("id") == item_id:
            item["status"] = "unmet"
            item["reason"] = reason
            item["citation"] = None
            item["detail"] = {"artifact_binding": {"members": [
                {"path": ".github/workflows/ci.yml",
                 "content_hash": "sha256:" + "0" * 64,
                 "status": member_status}]}}
    fresh["t1_met_count"] = RECORD["t1_met_count"] - 1
    return fresh


def run_cli(fresh: dict, committed_path: Path):
    """Run record_diff.py as a subprocess; return the CompletedProcess."""
    with tempfile.NamedTemporaryFile("w", suffix=".json") as fh:
        json.dump(fresh, fh)
        fh.flush()
        return subprocess.run(
            [sys.executable, str(REPO / "signoff" / "record_diff.py"),
             fh.name, str(committed_path)],
            capture_output=True, text=True)


class StaleMembersTests(unittest.TestCase):
    def test_stale_evidence_item_yields_its_stale_member(self):
        item = stale_fixture(10)["items"][9]
        self.assertEqual(item["id"], 10)
        members = rd.stale_members(item)
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]["path"], ".github/workflows/ci.yml")

    def test_other_reason_yields_nothing(self):
        item = stale_fixture(10, reason="unverifiable_provenance")["items"][9]
        self.assertEqual(rd.stale_members(item), [])

    def test_unverifiable_member_is_not_stale(self):
        item = stale_fixture(10, member_status="unverifiable",
                             reason="stale_evidence")["items"][9]
        self.assertEqual(rd.stale_members(item), [])


class ReattestItemsTests(unittest.TestCase):
    def test_keys_on_id_not_array_index(self):
        # id 9 lives at items[8]; a stale id 9 must be reported as 9.
        self.assertEqual(sorted(rd.reattest_items(stale_fixture(9))), [9])

    def test_item_agnostic_across_attested_ids(self):
        for item_id in (1, 9, 10):
            self.assertEqual(sorted(rd.reattest_items(stale_fixture(item_id))),
                             [item_id])


class ResidualDiffersTests(unittest.TestCase):
    def test_stale_item_and_derived_count_are_not_residual(self):
        fresh = stale_fixture(10)
        self.assertFalse(rd.residual_differs(fresh, RECORD, {10}))

    def test_other_top_level_change_is_residual(self):
        fresh = copy.deepcopy(RECORD)
        fresh["t1_item_count"] = RECORD["t1_item_count"] + 1
        self.assertTrue(rd.residual_differs(fresh, RECORD, set()))

    def test_change_outside_reattest_item_is_residual(self):
        fresh = stale_fixture(10)
        fresh["t1_item_count"] = RECORD["t1_item_count"] + 1
        self.assertTrue(rd.residual_differs(fresh, RECORD, {10}))


class CliTests(unittest.TestCase):
    def test_identical_documents_pass(self):
        p = run_cli(RECORD, RECORD_PATH)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("verdict of record is current", p.stdout)
        self.assertIn(
            f"T1 {RECORD['t1_met_count']}/{RECORD['t1_item_count']} items met",
            p.stdout)
        self.assertEqual(p.stderr, "")

    def test_stale_item10_directs_reattest(self):
        p = run_cli(stale_fixture(10), RECORD_PATH)
        self.assertEqual(p.returncode, 1)
        self.assertIn(".github/workflows/ci.yml", p.stderr)
        self.assertIn("item 10", p.stderr)
        self.assertIn("--attest 10", p.stderr)
        self.assertIn("signoff/inventory-item10.json", p.stderr)
        self.assertIn("bash signoff/check.sh", p.stderr)
        self.assertNotIn("--write", p.stderr)

    def test_stale_item9_directs_reattest(self):
        p = run_cli(stale_fixture(9), RECORD_PATH)
        self.assertEqual(p.returncode, 1)
        self.assertIn("item 9", p.stderr)
        self.assertIn("--attest 9", p.stderr)
        self.assertIn("signoff/inventory-item9.json", p.stderr)
        self.assertNotIn("--write", p.stderr)

    def test_unverifiable_member_gets_regenerate_message(self):
        p = run_cli(stale_fixture(10, member_status="unverifiable",
                                  reason="unverifiable_provenance"),
                    RECORD_PATH)
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("--attest", p.stderr)
        self.assertIn("--write", p.stderr)

    def test_plain_drift_gets_regenerate_message(self):
        fresh = copy.deepcopy(RECORD)
        fresh["t1_item_count"] = RECORD["t1_item_count"] + 1
        p = run_cli(fresh, RECORD_PATH)
        self.assertEqual(p.returncode, 1)
        self.assertIn("--write", p.stderr)
        self.assertNotIn("--attest", p.stderr)

    def test_both_kinds_report_both_messages(self):
        fresh = stale_fixture(10)
        fresh["t1_item_count"] = RECORD["t1_item_count"] + 1
        p = run_cli(fresh, RECORD_PATH)
        self.assertEqual(p.returncode, 1)
        self.assertIn(".github/workflows/ci.yml", p.stderr)
        self.assertIn("--attest 10", p.stderr)
        self.assertIn("--write", p.stderr)

    def test_missing_record_keeps_regenerate_hint(self):
        p = run_cli(RECORD, RECORD_PATH.parent / "does-not-exist.json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("is missing -- regenerate it with "
                      "'bash signoff/check.sh --write'", p.stderr)

    def test_invalid_record_json_fails_loudly(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as fh:
            fh.write("{not json")
            fh.flush()
            p = run_cli(RECORD, Path(fh.name))
        self.assertNotEqual(p.returncode, 0)

    def test_reattest_command_uses_checksh_pin(self):
        cmd = rd.reattest_command(10)
        self.assertIn("--attest 10", cmd)
        self.assertIn("signoff/inventory-item10.json", cmd)
        self.assertIn("signoff/evidence/item10.generic.json", cmd)
        self.assertNotIn("$KLT_VERSION", cmd)
        self.assertNotIn("KLT_SPEC", cmd)


if __name__ == "__main__":
    unittest.main()
