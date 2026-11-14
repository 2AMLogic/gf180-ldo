#!/usr/bin/env python3
"""Unit tests for sim/harness/loader.py (issue #625). Tool-free.

    python3 -m unittest discover -s sim/tests -t sim/tests -v

``load_script`` replaced 20 hand-written copies of the ``importlib.util``
path-loading idiom, 10 of which skipped registering the module in
``sys.modules`` before executing it. These tests hold that registration as a
contract rather than a comment: :class:`RegistrationInvariant` keeps the
unregistered idiom beside the helper as a regression oracle, so a future
rewrite of ``load_script`` that drops the registration fails here instead of
failing at some caller's next dataclass.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness.loader import load_script  # noqa: E402

#: A script in this repo's house style: deferred annotations + a dataclass.
#: This is the shape that needs `sys.modules` registration to import at all.
FUTURE_DATACLASS = """\
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Row:
    name: str
    value: float


WHO = __name__
"""


class LoaderTestCase(unittest.TestCase):
    """Writes fixture scripts to a temp dir and unregisters what it loads."""

    def setUp(self) -> None:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self._registered: list[str] = []

    def script(self, relpath: str, body: str = FUTURE_DATACLASS) -> Path:
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return path

    def load(self, name: str, path: Path):
        """``load_script``, but undo the ``sys.modules`` entry afterwards."""
        self._registered.append(name)
        self.addCleanup(lambda: sys.modules.pop(name, None))
        return load_script(name, path)


class RegistrationInvariant(LoaderTestCase):
    """The one non-obvious thing the helper exists to make unavoidable."""

    def test_future_annotations_dataclass_loads(self):
        mod = self.load("fx_registered", self.script("has_dataclass.py"))
        self.assertEqual(mod.Row("a", 1.5), mod.Row("a", 1.5))
        self.assertEqual(mod.Row("a", 1.5).value, 1.5)

    def test_unregistered_idiom_is_what_fails(self):
        """The regression oracle: the same load, minus the registration.

        This is the open-coded idiom that 10 of the 21 pre-#625 call sites
        used. It is here so the previous test's pass is attributable to the
        registration rather than to a quirk of the fixture -- if CPython ever
        guards `dataclasses._is_type`'s lookup, this test fails and the
        invariant can be revisited deliberately.
        """
        path = self.script("has_dataclass.py")
        spec = importlib.util.spec_from_file_location("fx_unregistered", path)
        module = importlib.util.module_from_spec(spec)
        self.assertNotIn("fx_unregistered", sys.modules)
        with self.assertRaises(AttributeError) as caught:
            spec.loader.exec_module(module)  # no sys.modules[...] = module
        self.assertIn("__dict__", str(caught.exception))

    def test_module_is_in_sys_modules_during_execution(self):
        """Registration happens before exec, not after it returns."""
        body = "import sys\nSELF = sys.modules[__name__]\n"
        mod = self.load("fx_during_exec", self.script("probe.py", body))
        self.assertIs(mod.SELF, mod)


class NameHandling(LoaderTestCase):
    """The caller-chosen name is load-bearing (issue #451)."""

    def test_registered_under_the_chosen_name(self):
        mod = self.load("fx_chosen_name", self.script("some_file.py"))
        self.assertIs(sys.modules["fx_chosen_name"], mod)
        self.assertEqual(mod.__name__, "fx_chosen_name")
        self.assertEqual(mod.WHO, "fx_chosen_name")
        self.assertNotIn("some_file", sys.modules)

    def test_same_filename_coexists_under_distinct_names(self):
        """Why a path load rather than a ``sys.path`` insertion: this repo has
        sixteen ``klt_run.py`` and five ``summarize.py``."""
        first = self.script("bench-one/klt_run.py")
        second = self.script("bench-two/klt_run.py")
        one = self.load("fx_one_klt_run", first)
        two = self.load("fx_two_klt_run", second)
        self.assertIsNot(one, two)
        self.assertEqual(one.WHO, "fx_one_klt_run")
        self.assertEqual(two.WHO, "fx_two_klt_run")

    def test_hyphenated_directory_is_loadable(self):
        """``sim/loop-stability/testbench/`` is not a legal package name."""
        mod = self.load(
            "fx_hyphenated", self.script("not-a-package/testbench/sweep.py"))
        self.assertEqual(mod.WHO, "fx_hyphenated")


class Failures(LoaderTestCase):
    def test_unrecognized_suffix_raises_importerror(self):
        path = self.script("deck.spice.in", "x = 1\n")
        with self.assertRaises(ImportError) as caught:
            load_script("fx_bad_suffix", path)
        self.assertIn("fx_bad_suffix", str(caught.exception))
        self.assertNotIn("fx_bad_suffix", sys.modules)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_script("fx_missing", self.tmp / "nope.py")
        sys.modules.pop("fx_missing", None)

    def test_accepts_str_and_pathlike(self):
        path = self.script("has_dataclass.py")
        as_path = self.load("fx_pathlike", path)
        self.addCleanup(lambda: sys.modules.pop("fx_str", None))
        as_str = load_script("fx_str", str(path))
        self.assertEqual(as_path.Row("a", 1.0), as_path.Row("a", 1.0))
        self.assertEqual(as_str.WHO, "fx_str")


if __name__ == "__main__":
    unittest.main()
