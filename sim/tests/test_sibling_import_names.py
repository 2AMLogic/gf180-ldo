#!/usr/bin/env python3
"""Structural guard for the unique-name sibling-load rule (issue #700).

Several ``sim/*/testbench/`` helper stems recur across benches -- 16 benches
ship a ``klt_run.py``, and ``summarize.py`` (3), ``sweep.py`` (2),
``selftest.py`` (2) and ``compare_records.py`` (2) are duplicated too -- so a
bare ``import <name>`` of one of those names binds the shared module name to
whichever bench's sibling resolves first in the interpreter. A real bench run
is one bench per process, so a collision only surfaces when two drivers share
one interpreter (the test suite, another driver) -- which is why the #630
cleanup that re-opened the #693 collision stayed green through the whole
window. The rule the tree follows: a driver that is itself loaded by
filesystem path loads its sibling by path under a *unique* module name, never
binds the bare name (loader comments in
``sim/loop-stability/testbench/sweep.py`` and
``sim/soft-start-loop-gain/testbench/sweep.py``).

This test parses every ``sim/*/testbench/*.py`` with ``ast`` -- nothing is
imported or executed -- and fails, naming file and line, on any import (at
any nesting level) of a name whose stem is ambiguous across benches. The
predicate keys on the *names*, not on how a load is written, so a
``spec_from_file_location`` path load is never flagged. Hermetic: no PDK,
ngspice, klt or fleet.

    python3 -m unittest sim/tests/test_sibling_import_names.py -v
"""

from __future__ import annotations

import ast
import unittest
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SIM = REPO / "sim"


def ambiguous_sibling_names(sim_dir: Path) -> set[str]:
    """File stems of ``sim/*/testbench/*.py`` occurring in 2+ benches."""
    benches: dict[str, set[str]] = defaultdict(set)
    for path in sorted(sim_dir.glob("*/testbench/*.py")):
        benches[path.stem].add(path.relative_to(sim_dir).parts[0])
    return {stem for stem, owners in benches.items() if len(owners) > 1}


def bare_sibling_imports(source: str, ambiguous: set[str],
                         filename: str = "<source>") -> list[str]:
    """Messages for every import binding an ambiguous name, any nesting.

    Pure syntax: the source is parsed, never imported or executed, so
    comments and string literals cannot trip it. Relative imports
    (``from . import x``) cannot resolve through ``sys.path`` and are not
    the hazard; only absolute bindings of an ambiguous root name count.
    """
    violations = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        roots = []
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
        for root in roots:
            if root in ambiguous:
                violations.append(
                    f"{filename}:{node.lineno}: import of ambiguous sibling "
                    f"name '{root}' -- load the sibling by path under a "
                    "unique module name instead (spec_from_file_location; "
                    "see sim/loop-stability/testbench/sweep.py, issue #700)")
    return violations


class SiblingImportNames(unittest.TestCase):
    def test_guard_is_non_vacuous(self):
        ambiguous = ambiguous_sibling_names(SIM)
        self.assertIn("klt_run", ambiguous)  # the name this rule exists for
        self.assertIn("sweep", ambiguous)
        self.assertNotIn("klt_peak_run", ambiguous)  # unique to soft-start
        self.assertNotIn("bias_acq", ambiguous)

    def test_no_testbench_binds_an_ambiguous_name(self):
        ambiguous = ambiguous_sibling_names(SIM)
        checked = 0
        problems = []
        for path in sorted(SIM.glob("*/testbench/*.py")):
            checked += 1
            problems.extend(bare_sibling_imports(
                path.read_text(encoding="utf-8"), ambiguous, str(path)))
        self.assertGreater(checked, 0, "no testbench sources found: guard is vacuous")
        self.assertEqual(
            problems, [],
            "bare imports of ambiguous sibling names found:\n" + "\n".join(problems))

    def test_bare_import_of_ambiguous_name_is_flagged(self):
        ambiguous = ambiguous_sibling_names(SIM)
        for bad in ("import klt_run\n",
                    "import klt_run as kr\n",
                    "from klt_run import kb, run_ab\n",
                    "from summarize import ILIM_WINDOW_MA\n",
                    "def f():\n    import sweep\n"):
            found = bare_sibling_imports(bad, ambiguous, "bench.py")
            self.assertEqual(len(found), 1, bad)
        found = bare_sibling_imports("def f():\n    import klt_run\n",
                                     ambiguous, "bench.py")
        self.assertIn("bench.py:2:", found[0])

    def test_path_load_and_unique_names_are_not_flagged(self):
        ambiguous = ambiguous_sibling_names(SIM)
        good = (
            "import importlib.util\n"
            "spec = importlib.util.spec_from_file_location(\n"
            '    "soft_start_klt_run", HERE / "klt_run.py")\n'
            "kr = importlib.util.module_from_spec(spec)\n"
            "sys.modules[spec.name] = kr\n"
            "spec.loader.exec_module(kr)\n"
        )
        self.assertEqual(bare_sibling_imports(good, ambiguous, "bench.py"), [])
        self.assertEqual(bare_sibling_imports("import klt_peak_run\n", ambiguous), [])
        self.assertEqual(bare_sibling_imports("from bias_acq import x\n", ambiguous), [])


if __name__ == "__main__":
    unittest.main()
