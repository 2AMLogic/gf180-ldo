#!/usr/bin/env python3
"""Regression test for issue #242: ``run_ngspice_deck()`` must treat a
``.let``/``v(...)`` reference to a nonexistent netlist node as fatal.

Reproduces the exact bug report: ngspice does not hard-error (exit 0) when a
``.let`` scalar is assigned directly from ``v(<node not in the netlist>)``.
It instead prints, per occurrence,

    Error: RHS "v(<name>)" invalid
    Error: &<let-name>: no such variable.

and lets the run "succeed" -- the affected field comes out empty/``None``
downstream instead of raising. #239 hit this for real
(``sim/soft-start-loop-gain/testbench/tb_ss_handover.spice.in``'s pre-fix
``.let gmsum_dc = v(xdut.xsoftstart.gmsum)`` against a netlist that no
longer has a ``GMSUM`` node post-#231); this module pins the harness-level
fix as a minimal, netlist-free fixture rather than re-running that history.

The straightforward fix -- adding the bare substring "no such variable" to
``FATAL_LOG_PATTERNS`` -- was rejected: ngspice reuses that exact wording
for an unrelated, *expected* non-fatal outcome (a ``.meas ... find/when``
with no crossing in the swept band, e.g. ``f0r``/``f180``/``gmx`` in
``sim/loop-stability/testbench/tb_loop_stability.spice.in``). This module
also pins that the fix does NOT regress that case.

Unlike ``test_harness.py`` (deliberately ngspice-free and PDK-free), this
module shells out to a real ngspice, following
``test_ngspice_options_precedence.py``'s pattern: it skips cleanly when
ngspice is not on ``PATH`` so the no-tooling CI lane stays green.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness.runner import run_ngspice_deck  # noqa: E402

NGSPICE = shutil.which("ngspice")


@unittest.skipIf(NGSPICE is None, "ngspice not on PATH")
class UndefinedVectorLetTests(unittest.TestCase):
    """The reproduction case from the issue body: a ``.let`` scalar built
    from a ``v(...)`` reference to a node absent from the netlist."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workdir = Path(self.tmp.name)

    def _run(self, deck_text: str) -> tuple[Path, Path]:
        deck = self.workdir / "deck.spice"
        deck.write_text(deck_text)
        log = self.workdir / "deck.log"
        return deck, log

    def test_a_let_referencing_a_nonexistent_node_raises(self):
        """Exact reproduction shape: ``Error: RHS "v(...)" invalid`` then
        ``Error: &<name>: no such variable.`` -- issue #242's own repro."""
        deck, log = self._run(
            "* issue #242 repro: .let assigned from a nonexistent v(...)\n"
            "r1 a 0 1k\n"
            "v1 a 0 dc 1\n"
            ".control\n"
            "op\n"
            "let gmsum_dc = v(nonexistent_node)\n"
            'echo "GMSUM=$&gmsum_dc"\n'
            'echo "SWEEP COMPLETE"\n'
            ".endc\n"
            ".end\n"
        )
        with self.assertRaises(RuntimeError) as ctx:
            run_ngspice_deck(deck, log, self.workdir)
        self.assertIn("v(...)", str(ctx.exception))
        # The log is still written for diagnosis, even on a fatal result.
        self.assertIn("RHS \"v(nonexistent_node)\" invalid", log.read_text())

    def test_a_let_referencing_a_nonexistent_node_raises_even_without_a_later_reference(self):
        """The RHS itself is fatal; a deck need not go on to reference the
        broken scalar (e.g. via ``print``/``echo &...``) for this to be a
        real, silently-empty field downstream."""
        deck, log = self._run(
            "* issue #242 repro, no downstream reference\n"
            "r1 a 0 1k\n"
            "v1 a 0 dc 1\n"
            ".control\n"
            "op\n"
            "let gmsum_dc = v(nonexistent_node)\n"
            'echo "SWEEP COMPLETE"\n'
            ".endc\n"
            ".end\n"
        )
        with self.assertRaises(RuntimeError):
            run_ngspice_deck(deck, log, self.workdir)

    def test_a_valid_let_still_succeeds(self):
        """Control: a `.let`/`v(...)` reference to a real node is unaffected."""
        deck, log = self._run(
            "* control: v(...) references a node that really exists\n"
            "r1 a 0 1k\n"
            "v1 a 0 dc 1\n"
            ".control\n"
            "op\n"
            "let a_dc = v(a)\n"
            'echo "SWEEP COMPLETE"\n'
            ".endc\n"
            ".end\n"
        )
        text = run_ngspice_deck(deck, log, self.workdir)
        self.assertIn("SWEEP COMPLETE", text)

    def test_the_f0r_style_no_crossing_meas_case_stays_non_fatal(self):
        """sim/loop-stability/testbench/tb_loop_stability.spice.in:285-296:
        a `.meas ... find/when` with no crossing in the swept band is an
        *expected*, non-fatal outcome, and prints the same bare "no such
        variable" wording as the #242 bug for the unset `.meas` scalar
        (``f0r``, and anything derived from it like ``fres = f0*1.05``).
        That RHS is an arithmetic expression / absent, never a raw
        ``v(...)`` reference, so the new check must not flag it.
        """
        deck, log = self._run(
            "* benign no-crossing .meas case, mirrors loop-stability's f0r/fres\n"
            "r1 in out 1k\n"
            "c1 out 0 1n\n"
            "vin in 0 dc 1 ac 1\n"
            ".control\n"
            "ac dec 10 1 1meg\n"
            "let tdb = db(v(out))\n"
            "meas ac f0 when tdb=0 fall=1\n"
            "let fres = f0*1.05\n"
            "meas ac f0r when tdb=0 rise=1\n"
            'echo "F0R=$&f0r"\n'
            'echo "SWEEP COMPLETE"\n'
            ".endc\n"
            ".end\n"
        )
        text = run_ngspice_deck(deck, log, self.workdir)
        self.assertIn("no such variable", text.lower())
        self.assertIn("SWEEP COMPLETE", text)


if __name__ == "__main__":
    unittest.main()
