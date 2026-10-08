#!/usr/bin/env python3
"""The test cell generator's assertions must be audible (issue #296).

    python3 -m unittest discover -s layout/tests -v

``klayout -b -r`` swallows ``SystemExit``: a bare ``raise SystemExit("...")``
prints nothing and the process still exits 0 (layout/README.md, "``klayout
-b -r`` swallows ``SystemExit``"). ``layout/testcell/gen_gds.py`` therefore
routes every assertion through the shared ``_fail()`` helper in
``layout/gen_gds_common.py`` (issue #370) that writes the message
to stderr first, which is what ``layout/drclvs.py`` captures into the run
directory's ``build-gds.log``.

No PDK or klayout required: the generator is executed under a stub ``pya``
module, and only its pre-geometry assertions (missing ``-rd`` switch, missing
PCell library) are driven. The geometry assertions need the real PDK PCell;
those are covered by the static check that no bare ``raise SystemExit`` with
a message remains outside ``_fail()``.
"""

from __future__ import annotations

import ast
import contextlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parents[1]
GEN_GDS = LAYOUT_DIR / "testcell" / "gen_gds.py"
COMMON = LAYOUT_DIR / "gen_gds_common.py"


def _run_generator(**rd_switches):
    """Execute gen_gds.py as ``klayout -b -r`` would, with ``-rd`` globals.

    Returns ``(exit_code, stderr_text)``. A stub ``pya`` stands in for the
    KLayout interpreter's module; the paths driven here fail before any
    ``pya`` call.
    """
    source = GEN_GDS.read_text()
    namespace = {"__name__": "__main__", "__file__": str(GEN_GDS)}
    namespace.update(rd_switches)
    stderr = io.StringIO()
    saved_pya = sys.modules.get("pya")
    saved_path = list(sys.path)
    sys.modules["pya"] = types.ModuleType("pya")
    try:
        with contextlib.redirect_stderr(stderr):
            try:
                exec(compile(source, str(GEN_GDS), "exec"), namespace)
            except SystemExit as exc:
                return exc.code, stderr.getvalue()
    finally:
        sys.path[:] = saved_path
        if saved_pya is None:
            sys.modules.pop("pya", None)
        else:
            sys.modules["pya"] = saved_pya
    return 0, stderr.getvalue()


class TestTestcellGeneratorFailuresAreAudible(unittest.TestCase):
    def test_missing_rd_switch_is_reported_on_stderr(self):
        code, stderr = _run_generator()
        self.assertTrue(code, "must exit non-zero")
        self.assertIn("gen_gds.py: missing required switch -rd out=...", stderr)

    def test_missing_pcell_library_is_reported_on_stderr(self):
        with tempfile.TemporaryDirectory() as pdk:
            code, stderr = _run_generator(out=str(Path(pdk) / "x.gds"), pdk=pdk)
        self.assertTrue(code, "must exit non-zero")
        self.assertIn("gen_gds.py: no PCell library at", stderr)
        self.assertIn(pdk, stderr)

    def test_no_assertion_bypasses_fail(self):
        """The only ``raise SystemExit`` left is the one inside ``_fail()``.

        A bare ``raise SystemExit("message")`` anywhere else would be silent
        under ``klayout -b -r`` -- exactly the regression issue #296 fixed.
        """
        common = ast.parse(COMMON.read_text())
        fail_defs = [
            node for node in ast.walk(common)
            if isinstance(node, ast.FunctionDef) and node.name == "_fail"
        ]
        self.assertEqual(len(fail_defs), 1, "gen_gds_common.py must define _fail()")
        inside_fail = {id(n) for n in ast.walk(fail_defs[0])}

        tree = ast.parse(GEN_GDS.read_text())
        self.assertFalse(
            any(isinstance(n, ast.FunctionDef) and n.name == "_fail"
                for n in ast.walk(tree)),
            "gen_gds.py must use the shared _fail(), not a private copy",
        )
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            exc = node.exc
            target = exc.func if isinstance(exc, ast.Call) else exc
            if isinstance(target, ast.Name) and target.id == "SystemExit":
                if id(node) not in inside_fail:
                    offenders.append(node.lineno)
        self.assertEqual(
            offenders, [],
            f"bare raise SystemExit outside _fail() at line(s) {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
