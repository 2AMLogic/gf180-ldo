"""PDK revision pin: find_pdk() must refuse a tree not at the pinned revision.

Uses throwaway fake PDK trees (just enough of libs.tech/ngspice to count as a
variant dir), so no real PDK is needed and these run in CI.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import pdk as pdk_mod  # noqa: E402
from harness.pdk import (  # noqa: E402
    PINNED_OPEN_PDKS_REVISION,
    PdkNotFound,
    PdkPinMismatch,
    find_pdk,
)

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


if __name__ == "__main__":
    unittest.main()
