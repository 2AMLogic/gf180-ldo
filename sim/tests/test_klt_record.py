#!/usr/bin/env python3
"""Unit tests for sim/harness/klt_record.py. No PDK, ngspice or klt required.

    python3 -m unittest sim/tests/test_klt_record.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import klt_record as kr  # noqa: E402


class ParsePrior(unittest.TestCase):
    def _newest(self, slug):
        return sorted((SIM_DIR / slug / "records").glob("*.md"))[-1]

    def test_reads_only_the_result_table(self):
        # The spread table that follows quotes measurement names in backticks too.
        cols, grid, shas = kr.parse_prior(self._newest("psrr-vs-freq"))
        self.assertEqual(cols[:2], ["psrr_1k_db", "psrr_100k_db"])
        self.assertEqual(len(grid), 45)
        self.assertTrue(all(c.count("_") >= 2 for c in grid), sorted(grid)[:3])
        self.assertTrue(shas)

    def test_a_cell_that_is_not_a_number_is_none(self):
        _, grid, _ = kr.parse_prior(self._newest("psrr-vs-freq"))
        row = grid["tt_27c_3.30v"]
        self.assertIsInstance(row["psrr_1k_db"], float)
        self.assertIsNone(row["pass/fail"])


if __name__ == "__main__":
    unittest.main()
