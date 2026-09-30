#!/usr/bin/env python3
"""Unit tests for the T1-T5 hand-over driver's DUT selection. No PDK, no ngspice.

    python3 -m unittest discover -s sim/tests -v

What these cover is one thing: **an overridden DUT cannot mint an evidence
record.** `sim/soft-start/testbench/handover_t15.py --dut-netlist PATH` (issue
#339) grades an arbitrary netlist so a candidate FB-injection element can be
A/B'd against the committed one with `git diff -- design/` empty -- the
capability `sim/run_corners.py --dut-netlist` and `run.sh`'s `LDO_NETLIST`
already had. The hazard it introduces is the one `run.sh:85-89` already
refuses: `sim/soft-start/corners/` is committed, append-only evidence
(.gitignore force-tracks `sim/*/corners/**/*.log` back through the blanket
`*.log` ignore, and nothing ignores `*.csv` there at all), so a run whose DUT
is NOT a committed design state must not be able to write there. That gate is
a guard, and a guard that is not tested is a guard that silently stops
working -- hence this file.

The CLI cases run the real script as a subprocess: every one of them is
refused *before* `find_pdk()`, which is exactly why they need no PDK and can
run in CI. `GF180_PDK_PATH` is deliberately pointed at a nonexistent path in
one of them so the ordering is asserted, not assumed.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SIM_DIR.parent
DRIVER = SIM_DIR / "soft-start" / "testbench" / "handover_t15.py"
CORNERS_DIR = SIM_DIR / "soft-start" / "corners"

sys.path.insert(0, str(SIM_DIR))
_LG_TB = SIM_DIR / "soft-start-loop-gain" / "testbench"
sys.path.insert(0, str(_LG_TB))
import netlist_variants as nv  # noqa: E402

# Loaded under a unique name (the file is a script, not an importable module
# in a package), matching test_soft_start_loop_gain.py's convention.
_spec = importlib.util.spec_from_file_location("ss_handover_t15", DRIVER)
handover = importlib.util.module_from_spec(_spec)
sys.modules["ss_handover_t15"] = handover
_spec.loader.exec_module(handover)

CORE = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()


def run_driver(*argv: str, env_extra: dict[str, str] | None = None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(DRIVER), *argv],
        capture_output=True, text=True, cwd=str(REPO_ROOT), env=env)


class TestTheWriteGate(unittest.TestCase):
    """--dut-netlist without --no-write is refused, and writes nothing."""

    def test_dut_netlist_without_no_write_is_refused(self):
        before = sorted(p.name for p in CORNERS_DIR.iterdir())
        proc = run_driver("--dut-netlist", "design/netlist/ldo_core.spice",
                          "--corners", "tt", "--temps", "27")
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("refusing to mint a record", proc.stderr)
        self.assertIn("--no-write", proc.stderr)
        # The whole point: nothing landed in the committed evidence tree.
        self.assertEqual(before, sorted(p.name for p in CORNERS_DIR.iterdir()))

    def test_the_refusal_precedes_pdk_discovery(self):
        """So the gate answers the same on a box with no PDK -- e.g. CI.

        If the gate ever moves below ``find_pdk()``, this run fails with a
        PdkNotFound traceback instead of the refusal, and this test says so.
        """
        proc = run_driver("--dut-netlist", "design/netlist/ldo_core.spice",
                          env_extra={"GF180_PDK_PATH": "/nonexistent/pdk"})
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("refusing to mint a record", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_no_write_alone_is_allowed(self):
        """--no-write is not gated on --dut-netlist -- only the reverse.

        Asserted through --help rather than a run: a bare --no-write run is a
        real 63-corner simulation, which is not a unit test's business.
        """
        proc = run_driver("--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--no-write", proc.stdout)
        self.assertIn("--dut-netlist", proc.stdout)


class TestDutSelectionIsUnambiguous(unittest.TestCase):

    def test_dut_netlist_and_variant_are_mutually_exclusive(self):
        """Both decide the same thing, so a run may not carry both."""
        proc = run_driver("--variant", "device",
                          "--dut-netlist", "design/netlist/ldo_core.spice",
                          "--no-write")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("not allowed with argument", proc.stderr)

    def test_a_missing_dut_netlist_is_reported_not_simulated(self):
        proc = run_driver("--dut-netlist", "sim/.work/nope-not-here.spice",
                          "--no-write",
                          env_extra={"GF180_PDK_PATH": "/nonexistent/pdk"})
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("does not exist", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


class TestInstrumentDut(unittest.TestCase):
    """An overridden DUT gets the same SSR instrumentation `device` gets."""

    def test_a_raw_core_netlist_is_instrumented_like_variant_device(self):
        self.assertEqual(handover.instrument_dut(CORE, DRIVER),
                         nv.build_variant(REPO_ROOT, "device"))

    def test_an_already_instrumented_netlist_passes_through_untouched(self):
        built = nv.build_variant(REPO_ROOT, "device")
        self.assertEqual(handover.instrument_dut(built, DRIVER), built)

    def test_instrumenting_is_idempotent_so_the_ssr_port_is_never_doubled(self):
        once = handover.instrument_dut(CORE, DRIVER)
        twice = handover.instrument_dut(once, DRIVER)
        self.assertEqual(once, twice)
        self.assertNotIn(nv.CORE_PORTS + " SSR SSR", twice)

    def test_a_netlist_of_the_wrong_shape_fails_loud_and_actionable(self):
        with self.assertRaises(SystemExit) as caught:
            handover.instrument_dut("* not a core netlist\n.end\n", DRIVER)
        msg = str(caught.exception)
        self.assertIn("--dut-netlist", msg)
        self.assertIn("ldo_core", msg)


if __name__ == "__main__":
    unittest.main()
