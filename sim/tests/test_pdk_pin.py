"""PDK revision pin: find_pdk() must refuse a tree not at the pinned revision.

Uses throwaway fake PDK trees (just enough of libs.tech/ngspice to count as a
variant dir), so no real PDK is needed and these run in CI.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import pdk as pdk_mod  # noqa: E402
from harness.loader import load_script  # noqa: E402
from harness.pdk import (  # noqa: E402
    PINNED_OPEN_PDKS_REVISION,
    PdkNotFound,
    PdkPinMismatch,
    find_pdk,
)

SIM_DIR = Path(__file__).resolve().parents[1]

OLD_REVISION = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"


def _make_variant(root: Path, sources: str | None) -> Path:
    variant = root / "gf180mcuD"
    models = variant / "libs.tech" / "ngspice"
    models.mkdir(parents=True)
    (models / "sm141064.ngspice").write_text("* fake\n")
    if sources is not None:
        (variant / "SOURCES").write_text(sources)
    return variant


class PdkPinTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = {k: v for k, v in os.environ.items()
               if k not in ("GF180_PDK_PATH", "PDK_ROOT", "PDK")}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pin_is_not_the_retired_revision(self) -> None:
        self.assertNotEqual(PINNED_OPEN_PDKS_REVISION, OLD_REVISION)

    def test_match_resolves(self) -> None:
        _make_variant(self.root, f"open_pdks {PINNED_OPEN_PDKS_REVISION}\n")
        with mock.patch.dict(os.environ, {"PDK_ROOT": str(self.root)}):
            found = find_pdk()
        self.assertEqual(found.version, PINNED_OPEN_PDKS_REVISION)
        self.assertEqual(found.source, "PDK_ROOT")

    def test_mismatch_fails_with_clear_message(self) -> None:
        _make_variant(self.root, f"open_pdks {OLD_REVISION}\n")
        with mock.patch.dict(os.environ, {"PDK_ROOT": str(self.root)}):
            with self.assertRaises(PdkPinMismatch) as ctx:
                find_pdk()
        msg = str(ctx.exception)
        self.assertIn(OLD_REVISION, msg)
        self.assertIn(PINNED_OPEN_PDKS_REVISION, msg)
        self.assertIsInstance(ctx.exception, PdkNotFound)

    def test_missing_sources_fails(self) -> None:
        _make_variant(self.root, None)
        with mock.patch.dict(os.environ, {"PDK_ROOT": str(self.root)}):
            with self.assertRaises(PdkPinMismatch) as ctx:
                find_pdk()
        self.assertIn("SOURCES", str(ctx.exception))

    def test_explicit_override_is_checked_too(self) -> None:
        variant = _make_variant(self.root, f"open_pdks {OLD_REVISION}\n")
        with mock.patch.dict(os.environ, {"GF180_PDK_PATH": str(variant)}):
            with self.assertRaises(PdkPinMismatch):
                find_pdk()

    def test_search_root_is_checked(self) -> None:
        _make_variant(self.root, f"open_pdks {OLD_REVISION}\n")
        with mock.patch.object(pdk_mod, "BUILTIN_SEARCH_ROOTS", (str(self.root),)), \
                mock.patch.object(pdk_mod, "_load_config", return_value={}):
            with self.assertRaises(PdkPinMismatch):
                find_pdk()

    def test_ciel_is_searched_before_volare(self) -> None:
        roots = list(pdk_mod.BUILTIN_SEARCH_ROOTS)
        self.assertLess(roots.index("~/.ciel"), roots.index("~/.volare"))


def _restore_pdk_root_cleanup(testcase: unittest.TestCase) -> None:
    """Register the ``restore_root`` cleanup: assignment always writes, so a
    test that pins ``$PDK_ROOT`` must not leak it into the rest of the suite."""
    prior_root = os.environ.get("PDK_ROOT")

    def restore_root():
        if prior_root is None:
            os.environ.pop("PDK_ROOT", None)
        else:
            os.environ["PDK_ROOT"] = prior_root

    testcase.addCleanup(restore_root)


class PinKltPdkRootTests(unittest.TestCase):
    """``pin_klt_pdk_root`` exports the pin-checked tree's root (issue #639).

    ``find_pdk()`` resolves ``$GF180_PDK_PATH`` ahead of ``$PDK_ROOT``, so an
    ambient ``$PDK_ROOT`` can name a different, un-pin-checked tree than the
    ``Pdk`` it returned -- and ``klt`` stages from whatever ``$PDK_ROOT`` names.
    The helper must therefore assign, never ``setdefault``.
    """

    PINNED = pdk_mod.Pdk(path=Path("/pinned/root/gf180mcuD"), variant="gf180mcuD",
                         source="search_root:/pinned/root")

    def setUp(self) -> None:
        _restore_pdk_root_cleanup(self)

    def test_an_ambient_pdk_root_naming_another_tree_does_not_survive(self) -> None:
        with mock.patch.dict(os.environ, {"PDK_ROOT": "/stale/root"}):
            self.assertEqual("/pinned/root", pdk_mod.pin_klt_pdk_root(self.PINNED))
            self.assertEqual("/pinned/root", os.environ["PDK_ROOT"])

    def test_with_pdk_root_unset_the_pin_is_still_exported(self) -> None:
        # The Class B case: current-limit / enable-shutdown ran with no pin at
        # all before #639, so a both-set-only test would not catch it.
        os.environ.pop("PDK_ROOT", None)
        self.assertEqual("/pinned/root", pdk_mod.pin_klt_pdk_root(self.PINNED))
        self.assertEqual("/pinned/root", os.environ["PDK_ROOT"])

    def test_an_ambient_pdk_root_already_at_the_pinned_tree_is_a_no_op(self) -> None:
        with mock.patch.dict(os.environ, {"PDK_ROOT": "/pinned/root"}):
            self.assertEqual("/pinned/root", pdk_mod.pin_klt_pdk_root(self.PINNED))
            self.assertEqual("/pinned/root", os.environ["PDK_ROOT"])

    def test_a_nonexistent_ambient_pdk_root_is_overwritten_not_trusted(self) -> None:
        with mock.patch.dict(os.environ, {"PDK_ROOT": "/does/not/exist"}):
            self.assertEqual("/pinned/root", pdk_mod.pin_klt_pdk_root(self.PINNED))
            self.assertEqual("/pinned/root", os.environ["PDK_ROOT"])

    def test_without_an_argument_find_pdk_supplies_the_tree(self) -> None:
        stub = types.SimpleNamespace(path=Path("/resolved/root/gf180mcuD"))
        with mock.patch.dict(os.environ, {"PDK_ROOT": "/stale/root"}), \
                mock.patch.object(pdk_mod, "find_pdk", return_value=stub):
            self.assertEqual("/resolved/root", pdk_mod.pin_klt_pdk_root())
            self.assertEqual("/resolved/root", os.environ["PDK_ROOT"])

    def test_a_find_pdk_failure_is_not_swallowed_and_leaves_the_env_untouched(self) -> None:
        with mock.patch.dict(os.environ, {"PDK_ROOT": "/stale/root"}), \
                mock.patch.object(pdk_mod, "find_pdk",
                                  side_effect=PdkPinMismatch("no pinned tree here")):
            with self.assertRaises(PdkPinMismatch):
                pdk_mod.pin_klt_pdk_root()
            # Nothing half-written: the ambient value is left exactly as found.
            self.assertEqual("/stale/root", os.environ["PDK_ROOT"])


def _load(name: str, rel: str) -> types.ModuleType:
    """Import a testbench script by path (the loader test_summarizers uses)."""
    return load_script(name, SIM_DIR / rel)


#: What a stubbed ``find_pdk`` hands back: only ``path.parent`` is consumed.
STUB_PDK = types.SimpleNamespace(path=Path("/pinned/root/gf180mcuD"))


class StageWiringPinsPdkRootTests(unittest.TestCase):
    """Each ``stage_model_inputs=True`` entry point pins before its first submit.

    ``klt_batch``/``klt_ab`` never pin -- the pin is per caller -- so this is
    asserted per script, with the submit stubbed so nothing is sent anywhere
    and ``klt_version``-style host dependencies never load. The ambient
    ``/stale/root`` proves assignment: a ``setdefault`` would leave it standing.
    ``sim/tests/test_tb_adapter.py`` covers ``tb_adapter.main`` (which fronts 11
    of the 16 ``klt_run.py`` scripts) and ``test_loop_stability.py``'s
    ``TestRunGridKltWiring`` covers ``run_grid_klt``.
    """

    def setUp(self) -> None:
        _restore_pdk_root_cleanup(self)
        patcher = mock.patch.object(pdk_mod, "find_pdk", return_value=STUB_PDK)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _capture_submit(self, mod: types.ModuleType, seen: dict) -> None:
        real_run_ab = mod.run_ab

        def fake_run_ab(job_factory, dut, baseline_ref, dest, repo, **kw):
            # Read at submit time: the pin must already be in place by now.
            seen["pdk_root"] = os.environ.get("PDK_ROOT")
            return {}

        mod.run_ab = fake_run_ab
        self.addCleanup(setattr, mod, "run_ab", real_run_ab)

    def _stub_write_summary_csv(self, mod: types.ModuleType) -> None:
        real = mod.write_summary_csv
        mod.write_summary_csv = lambda rows, path, keys=None: None
        self.addCleanup(setattr, mod, "write_summary_csv", real)

    def test_mc_output_accuracy_pins_before_submit(self) -> None:
        mc = _load("mc_klt_run_pin_wiring", "mc-output-accuracy/testbench/klt_run.py")
        self._stub_write_summary_csv(mc)
        seen: dict = {}
        self._capture_submit(mc, seen)
        with mock.patch.dict(os.environ, {"PDK_ROOT": "/stale/root"}):
            rc = mc.main(["--record-id", "zz-pin-wiring"])
        self.assertEqual("/pinned/root", seen.get("pdk_root"))
        # The stubbed submits return nothing, so the run reports lost points;
        # the pin-before-submit ordering is what is under test here.
        self.assertEqual(1, rc)

    def test_probe_fb_current_pins_before_submit(self) -> None:
        probe = _load("probe_fb_current_pin_wiring",
                      "mc-output-accuracy/testbench/probe_fb_current.py")
        seen: dict = {}

        def fake_stage(job, workdir):
            return {}

        def fake_run(req, outdir, backend="local"):
            seen["pdk_root"] = os.environ.get("PDK_ROOT")
            return {}

        def fake_collect(report, job, sub):
            return {}

        for attr, fake in (("stage", fake_stage), ("run", fake_run),
                           ("collect", fake_collect)):
            real = getattr(probe.kb, attr)
            setattr(probe.kb, attr, fake)
            self.addCleanup(setattr, probe.kb, attr, real)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        argv = ["probe_fb_current.py", "--out", str(Path(tmp.name) / "out")]
        with mock.patch.dict(os.environ, {"PDK_ROOT": "/stale/root"}), \
                mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = probe.main()
        self.assertEqual(0, rc)
        self.assertEqual("/pinned/root", seen.get("pdk_root"))

    def test_current_limit_pins_before_submit(self) -> None:
        cl = _load("cl_klt_run_pin_wiring", "current-limit/testbench/klt_run.py")
        self._stub_write_summary_csv(cl)
        seen: dict = {}
        self._capture_submit(cl, seen)
        with mock.patch.dict(os.environ, {"PDK_ROOT": "/stale/root"}):
            rc = cl.main(["--record-id", "zz-pin-wiring"])
        self.assertEqual(0, rc)
        self.assertEqual("/pinned/root", seen.get("pdk_root"))

    def test_enable_shutdown_pins_before_submit(self) -> None:
        es = _load("es_klt_run_pin_wiring", "enable-shutdown/testbench/klt_run.py")
        seen: dict = {}
        self._capture_submit(es, seen)
        with mock.patch.dict(os.environ, {"PDK_ROOT": "/stale/root"}):
            rc = es.main(["--record-id", "zz-pin-wiring"])
        self.assertEqual(0, rc)
        self.assertEqual("/pinned/root", seen.get("pdk_root"))


if __name__ == "__main__":
    unittest.main()
