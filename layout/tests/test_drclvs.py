#!/usr/bin/env python3
"""Unit tests for layout/drclvs.py's record-writing path.

    python3 -m unittest discover -s layout/tests -v

No PDK, klayout, or xschem required: these tests exercise only
``write_record()``'s append-only guard, not the DRC/LVS stages themselves.
"""

from __future__ import annotations

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
            try:
                path = drclvs.write_record(rid, summary, pdk)
                self.assertEqual(path, records_dir / f"{rid}.md")
                first_text = path.read_text()
                self.assertIn(rid, first_text)

                with self.assertRaises(RecordExists):
                    drclvs.write_record(rid, summary, pdk)

                # the first record must not have been clobbered
                self.assertEqual(path.read_text(), first_text)
            finally:
                drclvs.RECORDS_DIR = original_records_dir


if __name__ == "__main__":
    unittest.main()
