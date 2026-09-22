#!/usr/bin/env python3
"""Unit tests for layout/drclvs.py's host-independent parts.

    python3 -m unittest discover -s layout/tests -v

No PDK, klayout, or xschem required: these tests exercise ``write_record()``'s
append-only guard, the ``--cell`` registry, and ``deck_env()``'s pmap(1)
stand-in -- not the DRC/LVS stages themselves.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT_DIR))

import drclvs  # noqa: E402

sys.path.insert(0, str(LAYOUT_DIR.parent / "sim"))
from harness.pdk import Pdk  # noqa: E402
from harness.report import RecordExists  # noqa: E402


def fake_pdk(root: Path) -> Pdk:
    return Pdk(path=root, variant="gf180mcuD", source="test")


def fake_summary(record_id: str) -> dict:
    return {
        "record_id": record_id,
        "netlist_devices": 1,
        "klt_drc": {"status": "clean", "violations": 0, "dbu_um": 0.001},
        "pdk_drc": {"violations": 0, "rule_categories": 1, "rule_tables": 1},
        "lvs": {"match": True, "warnings": []},
        "lvs_negative_controls": {
            "topology": {"match": False, "mutation": "gate shorted to drain"},
            "parameter": {"match": False, "mutation": "device width doubled"},
        },
    }


class WriteRecordTests(unittest.TestCase):
    """write_record() must go through harness.report's append-only guard.

    Regression test for the gap #142 closes: write_record() used to write
    unconditionally via a hand-rolled mkdir/write_text, silently overwriting
    a record a concurrent --record run already spent for the same id.
    """

    def test_refuses_to_overwrite_an_existing_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            records_dir = Path(tmp) / "records"
            pdk = fake_pdk(Path(tmp) / "pdk")
            rid = "20260821-000000-abc1234"
            summary = fake_summary(rid)

            original_records_dir = drclvs.RECORDS_DIR
            drclvs.RECORDS_DIR = records_dir
            spec = drclvs.TESTCELL_SPEC
            try:
                path = drclvs.write_record(rid, summary, pdk, spec)
                self.assertEqual(path, records_dir / f"{rid}.md")
                first_text = path.read_text()
                self.assertIn(rid, first_text)

                with self.assertRaises(RecordExists):
                    drclvs.write_record(rid, summary, pdk, spec)

                # the first record must not have been clobbered
                self.assertEqual(path.read_text(), first_text)
            finally:
                drclvs.RECORDS_DIR = original_records_dir


class DeckEnvTests(unittest.TestCase):
    """The pmap(1) stand-in that keeps the PDK decks runnable off Linux."""

    def test_real_pmap_is_used_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            original = drclvs.tool_path
            drclvs.tool_path = lambda name: "/usr/bin/pmap"
            try:
                env, provenance = drclvs.deck_env(run_dir)
            finally:
                drclvs.tool_path = original
            self.assertEqual(provenance, "host")
            self.assertFalse((run_dir / "shims").exists())
            self.assertEqual(env["PATH"], os.environ["PATH"])

    def test_missing_pmap_gets_an_executable_shim_on_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            original = drclvs.tool_path
            drclvs.tool_path = lambda name: None
            try:
                env, provenance = drclvs.deck_env(run_dir)
            finally:
                drclvs.tool_path = original
            self.assertEqual(provenance, "shimmed")
            shim = run_dir / "shims" / "pmap"
            self.assertTrue(os.access(shim, os.X_OK), shim)
            self.assertEqual(env["PATH"].split(os.pathsep)[0], str(run_dir / "shims"))

    def test_shim_output_survives_the_decks_column_slice(self):
        """The decks do `pmap <pid> | tail -1`[10, 40].strip` -- that must not be nil.

        Reproduces the exact Ruby expression from the gf180mcu decks' logger
        formatter against the shim's real output: a shim whose line is shorter
        than 11 characters would slice to nil and crash the deck the same way
        a missing pmap does.
        """
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            original = drclvs.tool_path
            drclvs.tool_path = lambda name: None
            try:
                drclvs.deck_env(run_dir)
            finally:
                drclvs.tool_path = original
            proc = subprocess.run(
                [str(run_dir / "shims" / "pmap"), str(os.getpid())],
                capture_output=True, text=True, check=True,
            )
            last = proc.stdout.splitlines()[-1]
            sliced = last[10:50].strip()     # Ruby's String#[10, 40] then .strip
            self.assertTrue(sliced, f"empty slice from {last!r}")
            self.assertTrue(sliced.endswith("K"), sliced)
            self.assertTrue(sliced[:-1].strip().isdigit(), sliced)


class CellRegistryTests(unittest.TestCase):
    """The --cell registry this issue's generalization introduces."""

    def test_testcell_is_the_default_and_is_registered(self):
        self.assertIn("testcell", drclvs.CELLS)
        self.assertIs(drclvs.CELLS["testcell"], drclvs.TESTCELL_SPEC)
        self.assertEqual(drclvs.TESTCELL_SPEC.key, "testcell")

    def test_cell_spec_paths_exist_in_the_repo(self):
        spec = drclvs.TESTCELL_SPEC
        self.assertTrue(spec.gen_gds.is_file(), spec.gen_gds)
        self.assertTrue(spec.schematic.is_file(), spec.schematic)

    def test_unknown_cell_is_rejected_by_argument_parsing(self):
        with self.assertRaises(SystemExit):
            drclvs.main(["--cell", "not-a-registered-cell", "--check-env"])


if __name__ == "__main__":
    unittest.main()
