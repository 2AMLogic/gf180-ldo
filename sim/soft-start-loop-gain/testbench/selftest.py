#!/usr/bin/env python3
"""Prove this experiment's machinery before trusting anything it reports.

Two halves, in this order. **Neither is implemented here**: each is
delegated, unmodified, to the suite that already owns the property.

1. **The loop-gain extraction itself** -- delegated to
   ``sim/loop-stability/testbench/selftest.py``. That is not laziness: this
   deck uses that deck's Tian dual-injection arithmetic, its
   ``meas``-based margin extraction and its DR-0008 resurgence idiom
   character for character, against loops whose loop gain is known in closed
   form. Running its known-answer test rather than re-implementing one keeps
   the two experiments' extraction provably the same thing, which is the same
   reason ``sweep.py`` imports its constants instead of copying them. If that
   selftest fails, this one fails: a margin from an unvalidated extraction is
   worse than no margin.

2. **This experiment's own additions** -- delegated to
   ``sim/tests/test_soft_start_loop_gain.py``, which is the same
   simulator-free suite ``sim/selftest.sh`` (and therefore CI) runs. Those
   are the SSR port promotion, the injection-element A/B, the AC-only
   sensitivity transforms, the landing rule, the derived injection current,
   the hand-over metrics, the imported margin semantics and the ``klt sim``
   batch front end -- exactly where a wrong number here would come from.

   Part 2 used to re-implement about 230 lines of those assertions as its
   own ``check()`` calls, duplicating the unit-test module property for
   property. That had already cost one fix in each copy (the "node absent
   from the netlist" guard, when ``GMSUM`` came back in #246), and it also
   hid the reverse gap: the two sections that existed ONLY here -- the
   variant A/B and the ``klt sim`` front end -- never ran in CI, so a
   regression in the batch front end surfaced only at the next sweep. Both
   now live in the unit-test module (``TestDutVariantAB``,
   ``TestKltFrontEnd``), which is what applying this file's own
   delegate-rather-than-re-implement rule to part 2 buys: one copy of each
   assertion, and every one of them under CI. Issue #593.

**The pre-sweep gate is unchanged.** ``run.sh`` still runs this file before
it sweeps, and it still fails on any of those properties -- it now fails
because the unit-test module failed, rather than because a second copy of
the same assertion failed.

Needs ngspice for part 1 (no PDK, no design netlist); part 2 needs the
design netlist but no simulator. Writes nothing.

    ./sim/soft-start-loop-gain/testbench/selftest.py

Exit codes: 0 all checks pass, 1 a check failed, 3 environment problem.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPDIR = HERE.parent
REPO_ROOT = EXPDIR.parent.parent
LS_SELFTEST = REPO_ROOT / "sim" / "loop-stability" / "testbench" / "selftest.py"
UNIT_TESTS = REPO_ROOT / "sim" / "tests" / "test_soft_start_loop_gain.py"

OK = True


def check(label: str, passed: bool, detail: str) -> None:
    global OK
    OK = OK and passed
    print(f"  [{'PASS' if passed else 'FAIL'}] {label}: {detail}")


def delegate(script: Path) -> subprocess.CompletedProcess:
    """Run ``script`` as its own process and echo its output, indented.

    A subprocess rather than an import: each suite is run exactly as its
    own entry point runs it, so this file cannot change the meaning of
    somebody else's test by importing it into a different environment.
    """
    proc = subprocess.run([sys.executable, str(script)],
                          capture_output=True, text=True)
    for ln in (proc.stdout + proc.stderr).splitlines():
        print("  | " + ln)
    return proc


def main() -> int:
    # ---- part 1: the extraction, via loop-stability's own known-answer test
    print("== 1/2 loop-gain extraction (sim/loop-stability/testbench/selftest.py)")
    proc = delegate(LS_SELFTEST)
    if proc.returncode == 3:
        print("\nFATAL: the extraction selftest could not run (environment)",
              file=sys.stderr)
        return 3
    check("sim/loop-stability's known-answer extraction selftest",
          proc.returncode == 0,
          "delegated unmodified; this deck uses the same Tian arithmetic, the "
          "same meas-based margin extraction and the same DR-0008 resurgence "
          "idiom, so its validation is this deck's validation")

    # ---- part 2: this experiment's own additions, via the unit-test module
    print("\n== 2/2 this experiment's own machinery "
          "(sim/tests/test_soft_start_loop_gain.py)")
    if not UNIT_TESTS.is_file():
        print(f"\nFATAL: {UNIT_TESTS} is missing -- this file delegates every "
              f"one of its own checks to it, so there is nothing left to run "
              f"(environment)", file=sys.stderr)
        return 3
    proc = delegate(UNIT_TESTS)
    check("sim/tests/test_soft_start_loop_gain.py",
          proc.returncode == 0,
          "delegated unmodified: the SSR port promotion, the device/binj A/B, "
          "the AC-only transforms, the landing rule, the derived injection "
          "current, the hand-over metrics, the imported margin semantics and "
          "the `klt sim` front end. One copy of each assertion, and the same "
          "copy CI runs via sim/selftest.sh -- see this file's docstring and "
          "issue #593")

    print(f"\nSELFTEST {'PASS' if OK else 'FAIL'}")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
