#!/usr/bin/env python3
"""Unit tests for the toolchain-portability A/B driver's ROW-log reader.

    python3 -m unittest discover -s sim/tests -v

``parse_corner_logs()`` turns the loop-stability deck's ``ROW`` lines into the
``Point -> Margin`` map the A/B comparison is computed from. It reads those
lines through the deck driver's own strict parser, so a field the deck stopped
emitting is an error here rather than a silently missing data point. No PDK,
no ngspice: the recorded per-corner logs under
``sim/toolchain-portability/corners/`` are the read-only fixture.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SIM_DIR.parent

_AB_PATH = SIM_DIR / "toolchain-portability" / "testbench" / "ab_loop_stability.py"
_spec = importlib.util.spec_from_file_location("ab_loop_stability", _AB_PATH)
ab = importlib.util.module_from_spec(_spec)
sys.modules["ab_loop_stability"] = ab
_spec.loader.exec_module(ab)

RECORD = SIM_DIR / "toolchain-portability" / "corners" / "20260919-034500-4595f97"
ARMS = ("ngspice-46-fresh", "ngspice-46-pinned", "ngspice-47")

GOOD_ROW = (
    "ROW iload_a=0 ceff_f=3.3e-07 esr_ohm=0.001 vout_v=1.79902 dcgain_db=112.827 "
    "f0_hz=1515.46 phase_at_f0_deg=-168.892 f180_hz=338150 "
    "gain_at_f180_db=-69.4337 f0_rising_hz= resurgence_db=-0.860854"
)


def _parse_text(text: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "c.log").write_text(text)
        return ab.parse_corner_logs(Path(d))


class RecordedEvidenceTests(unittest.TestCase):
    def test_each_arm_yields_216_points(self) -> None:
        # Per arm directory: the record root's own *.log files are console
        # logs with no ROW lines, so parsing the root would pass vacuously.
        total = 0
        for arm in ARMS:
            pts = ab.parse_corner_logs(RECORD / arm)
            self.assertEqual(len(pts), 216, arm)
            total += len(pts)
        self.assertEqual(total, 648)
        self.assertEqual(ab.parse_corner_logs(RECORD), {})

    def test_margins_derived_from_phase_and_gain(self) -> None:
        for arm in ARMS:
            for pt, m in ab.parse_corner_logs(RECORD / arm).items():
                self.assertIsNotNone(m.pm_deg, pt.label)
                self.assertIsNotNone(m.gm_db, pt.label)
        pts = _parse_text(GOOD_ROW)
        (m,) = pts.values()
        self.assertAlmostEqual(m.pm_deg, 180.0 - 168.892)
        self.assertAlmostEqual(m.gm_db, 69.4337)
        self.assertAlmostEqual(m.f0_hz, 1515.46)
        self.assertAlmostEqual(m.vout_v, 1.79902)

    def test_empty_value_is_none_not_error(self) -> None:
        # `f0_rising_hz=` is legitimately empty on every recorded line; an
        # empty value for a Margin field means "no crossing", i.e. None.
        pts = _parse_text(GOOD_ROW.replace("f0_hz=1515.46", "f0_hz="))
        (m,) = pts.values()
        self.assertIsNone(m.f0_hz)


class StrictnessTests(unittest.TestCase):
    def test_missing_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_text(GOOD_ROW.replace(" vout_v=1.79902", ""))

    def test_repeated_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_text(GOOD_ROW + " vout_v=1.0")

    def test_unknown_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_text(GOOD_ROW.replace("resurgence_db=", "resurge_db="))

    def test_bare_token_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_text(GOOD_ROW + " stray")


class FilterTests(unittest.TestCase):
    def test_columns_header_and_noise_excluded(self) -> None:
        text = "\n".join(
            [
                "* columns: ROW iload_a= ceff_f= esr_ohm=",
                "record id : x",
                GOOD_ROW,
            ]
        )
        self.assertEqual(len(_parse_text(text)), 1)
        self.assertEqual(_parse_text("* columns: ROW iload_a= ceff_f="), {})


if __name__ == "__main__":
    unittest.main()
