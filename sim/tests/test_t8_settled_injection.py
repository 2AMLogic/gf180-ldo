#!/usr/bin/env python3
"""Unit tests for the T8 instrument's netlist transform. No PDK, no ngspice.

    python3 -m unittest discover -s sim/tests -v

``sim/psrr-vs-freq/testbench/t8_settled_injection.py`` (issue #302) grades
target T8 by inserting a 0 V ammeter in ``Mgmc_ss``'s drain lead. Everything
it reports rests on that transform being a pure series insertion: exactly one
card rewired, exactly one ammeter added, inside ``ldo_softstart`` and nowhere
else, and a loud failure rather than a silent no-op if the netlist moves.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))

_PATH = SIM_DIR / "psrr-vs-freq" / "testbench" / "t8_settled_injection.py"
_spec = importlib.util.spec_from_file_location("t8_settled_injection", _PATH)
t8 = importlib.util.module_from_spec(_spec)
sys.modules["t8_settled_injection"] = t8
_spec.loader.exec_module(t8)

CORE = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()


class TestInstrument(unittest.TestCase):
    def test_series_insertion_only(self):
        out = t8.instrument(CORE)
        old, new = CORE.splitlines(), out.splitlines()
        removed = [ln for ln in old if ln not in new]
        added = [ln for ln in new if ln not in old]
        self.assertEqual(len(removed), 1)
        self.assertTrue(removed[0].startswith("XMgmc_ss FB GMSUM GMOD GMOD pfet_03v3"))
        self.assertIn(removed[0].replace("XMgmc_ss FB ", f"XMgmc_ss {t8.PROBE_NODE} ", 1),
                      added)
        self.assertIn(f"{t8.AMMETER} {t8.PROBE_NODE} FB 0", added)
        self.assertEqual(len([a for a in added if not a.startswith("*")]), 2)

    def test_ammeter_is_inside_ldo_softstart(self):
        block = t8.SS_BLOCK_RE.search(t8.instrument(CORE)).group(0)
        self.assertIn(f"\n{t8.AMMETER} {t8.PROBE_NODE} FB 0\n", block)
        self.assertEqual(len(re.findall(rf"(?m)^{t8.AMMETER}\b", t8.instrument(CORE))), 1)

    def test_refuses_a_moved_netlist(self):
        moved = CORE.replace("XMgmc_ss FB ", "XMgmc_ss FBX ", 1)
        with self.assertRaises(SystemExit):
            t8.instrument(moved)

    def test_committed_netlist_carries_dr0035_ceiling(self):
        # The T8 result recorded in design/softstart_injection_compensation.md
        # is for Mtop_ss gated from VCEIL; if that moves, the record is stale.
        self.assertRegex(CORE, r"(?m)^XMtop_ss VSS VCEIL SSR VIN pfet_03v3\b")
        self.assertRegex(CORE, r"(?m)^XRceil_ss VIN VCEIL VSS ppolyf_u_3k\b")
        self.assertRegex(CORE, r"(?m)^Fceil_ss VCEIL VSS Vbsense_ss 1\.0\b")


if __name__ == "__main__":
    unittest.main()
