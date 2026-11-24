#!/usr/bin/env python3
"""Unit tests for the boundaries of the layout/drclvs.py module family.

    python3 -m unittest discover -s layout/tests -v

No PDK, klayout or xschem required.

Issue #837 split two self-contained subsystems out of the DRC/LVS driver --
the LVS negative controls (``layout/lvs_controls.py``) and the ``klt erc``
supply stage (``layout/erc_stage.py``) -- onto a shared base
(``layout/drclvs_common.py``). ``layout/tests/test_drclvs.py`` still reaches
every moved symbol through ``drclvs.<name>``, which is the surface the split
promised to keep; what these tests hold is the structure that makes it a
split rather than a copy:

- each sibling declares exactly the public symbols the issue moves, and the
  driver re-exports each one as the very same object while defining none of
  them itself;
- one ``StageError`` class serves the whole family, so the driver's
  ``main()`` still exits nonzero on an error raised inside a sibling;
- no sibling imports the driver back, and the controls -- pure functions of
  netlist text -- import no tool either.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT_DIR))

import drclvs  # noqa: E402
import drclvs_common  # noqa: E402
import erc_stage  # noqa: E402
import lvs_controls  # noqa: E402

# The public symbols issue #837 moves out of the driver, per destination.
CONTROL_SYMBOLS = {
    "REQUIRED_CONTROL_TAGS",
    "Control",
    "ControlNotApplicable",
    "W_TOKEN_RE",
    "L_TOKEN_RE",
    "control_topology",
    "control_parameter",
    "control_short_adjacent_taps",
    "control_unit_width",
    "PASSIVE_ELEMENTS",
    "control_passive",
    "MOS_CONTROLS",
    "PASSIVE_CONTROLS",
    "build_controls",
    "require_control_pair",
    "apply_control",
    "check_controls_apply",
}
ERC_SYMBOLS = {
    "ErcSpec",
    "ERC_SPECS_DIR",
    "ERC_REPORTS_DIR",
    "GEN_ERC_SPEC_SCRIPT",
    "MUTATE_ERC_SCRIPT",
    "erc_finding_keys",
    "validate_erc_report",
    "run_erc_spec_gen",
    "run_klt_erc",
    "run_erc_control",
    "check_erc_control_findings",
    "erc_result_rows",
    "erc_section",
}
SHARED_SYMBOLS = {"LAYOUT_DIR", "REPO_ROOT", "StageError", "repo_arg"}


def top_level_names(module) -> set[str]:
    """Names a module's own source binds at top level, imports excluded."""
    names = set()
    for node in ast.parse(Path(module.__file__).read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
    return names


class DeclaredSurfaceTests(unittest.TestCase):
    """Each sibling's ``__all__`` is exactly the issue's list of moved symbols."""

    def test_the_controls_declare_the_symbols_moved_out_of_the_driver(self):
        self.assertEqual(set(lvs_controls.__all__), CONTROL_SYMBOLS)

    def test_the_erc_stage_declares_the_symbols_moved_out_of_the_driver(self):
        self.assertEqual(set(erc_stage.__all__), ERC_SYMBOLS)

    def test_the_shared_base_declares_the_shared_symbols(self):
        self.assertEqual(set(drclvs_common.__all__), SHARED_SYMBOLS)


class ReExportTests(unittest.TestCase):
    """``drclvs.<name>`` still reaches every moved symbol: the same object."""

    def test_every_moved_symbol_is_reachable_through_the_driver(self):
        for module in (drclvs_common, lvs_controls, erc_stage):
            for name in module.__all__:
                with self.subTest(module=module.__name__, symbol=name):
                    self.assertIs(getattr(drclvs, name), getattr(module, name))

    def test_the_driver_no_longer_defines_any_moved_symbol(self):
        """A split moves code; a copy would leave the originals behind."""
        still_defined = top_level_names(drclvs) & (
            CONTROL_SYMBOLS | ERC_SYMBOLS | SHARED_SYMBOLS
        )
        self.assertEqual(still_defined, set())


class StageErrorTests(unittest.TestCase):
    """One ``StageError`` for the family: ``main()`` catches it everywhere."""

    def test_the_siblings_raise_the_drivers_stage_error_class(self):
        self.assertIs(lvs_controls.StageError, drclvs.StageError)
        self.assertIs(erc_stage.StageError, drclvs.StageError)

    def test_an_error_raised_in_a_sibling_is_caught_as_the_drivers(self):
        for error in (
            lvs_controls.ControlNotApplicable("the control does not apply"),
            erc_stage.StageError("klt erc failed"),
        ):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(drclvs.StageError) as caught:
                    raise error
                self.assertIs(caught.exception, error)


class ImportBoundaryTests(unittest.TestCase):
    """No sibling imports the driver back, in a fresh interpreter."""

    @staticmethod
    def probe(statement: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", statement],
            capture_output=True,
            text=True,
            cwd=str(LAYOUT_DIR),
            check=False,
        )

    def test_the_erc_stage_imports_without_the_driver(self):
        result = self.probe(
            "import sys, erc_stage; "
            "assert 'drclvs' not in sys.modules, 'erc_stage imports drclvs'"
        )
        self.assertEqual(
            result.returncode, 0, "import erc_stage reached the driver:\n"
            + result.stderr,
        )

    def test_the_controls_import_without_the_driver_or_any_tool(self):
        """Pure functions of netlist text: no driver, no subprocess, no PDK."""
        result = self.probe(
            "import sys, lvs_controls; "
            "loaded = sorted(m for m in sys.modules if m == 'drclvs'"
            " or m.split('.')[0] in ('subprocess', 'harness')); "
            "assert not loaded, loaded"
        )
        self.assertEqual(
            result.returncode, 0, "import lvs_controls reached the driver or a "
            "tool:\n" + result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
