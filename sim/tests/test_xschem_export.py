#!/usr/bin/env python3
"""Unit tests for the xschem identity gate. No xschem, PDK, or ngspice needed.

    python3 -m unittest discover -s sim/tests -v
"""

from __future__ import annotations

import contextlib
import io
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "sim"))
sys.path.insert(0, str(REPO_ROOT / "design"))
sys.path.insert(0, str(REPO_ROOT / "layout"))

from harness import xschem_export as xe  # noqa: E402

ENV = {"PATH": "/fake/bin"}
EXE = "/fake/bin/xschem"


def cp(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


def gate(**kw):
    """Patch which() and subprocess.run inside the exporter."""
    which = unittest.mock.patch.object(
        xe.shutil, "which", return_value=kw.pop("exe", EXE)
    )
    run = unittest.mock.patch.object(xe.subprocess, "run", **kw)
    return which, run


class VersionGateTests(unittest.TestCase):
    def check(self, **kw):
        which, run = gate(**kw)
        with which, run as m:
            return xe.check_xschem_version(ENV), m

    def test_pin_matches_docs(self):
        text = (REPO_ROOT / "docs" / "environment-setup.md").read_text()
        self.assertIn(f"XSCHEM V{xe.XSCHEM_PINNED_VERSION}", text)
        self.assertEqual(xe.XSCHEM_PINNED_VERSION, "3.4.7")

    def test_match_stdout(self):
        exe, m = self.check(return_value=cp("XSCHEM V3.4.7\nCopyright\n"))
        self.assertEqual(exe, EXE)
        self.assertEqual(m.call_args.args[0], [EXE, "--version"])
        self.assertEqual(m.call_args.kwargs["env"], ENV)

    def test_match_stderr(self):
        exe, _ = self.check(return_value=cp("", "XSCHEM V3.4.7\n"))
        self.assertEqual(exe, EXE)

    def test_mismatch(self):
        with self.assertRaisesRegex(
            xe.XschemExportError,
            r"toolchain mismatch \(found 3\.4\.4, need 3\.4\.7\)",
        ):
            self.check(return_value=cp("XSCHEM V3.4.4\n"))

    def test_longer_version_not_prefix_match(self):
        with self.assertRaisesRegex(xe.XschemExportError, "mismatch"):
            self.check(return_value=cp("XSCHEM V3.4.70\n"))

    def test_nonzero_exit(self):
        with self.assertRaisesRegex(xe.XschemExportError, "exited 2"):
            self.check(return_value=cp("XSCHEM V3.4.7", "", 2))

    def test_malformed(self):
        with self.assertRaisesRegex(xe.XschemExportError, "could not parse"):
            self.check(return_value=cp("hello\n"))

    def test_timeout(self):
        with self.assertRaisesRegex(xe.XschemExportError, "timed out"):
            self.check(side_effect=subprocess.TimeoutExpired("x", 1))

    def test_oserror(self):
        with self.assertRaisesRegex(xe.XschemExportError, "could not run"):
            self.check(side_effect=PermissionError("denied"))

    def test_missing_executable(self):
        which, run = gate(exe=None)
        with which, run as m:
            with self.assertRaisesRegex(xe.XschemExportError, "not found"):
                xe.check_xschem_version(ENV)
        m.assert_not_called()

    def test_not_cached(self):
        which, run = gate(side_effect=[cp("XSCHEM V3.4.7"), cp("XSCHEM V3.4.4")])
        with which, run:
            xe.check_xschem_version(ENV)
            with self.assertRaises(xe.XschemExportError):
                xe.check_xschem_version(ENV)


class RunNetlistTests(unittest.TestCase):
    def test_rejected_probe_never_netlists(self):
        which, run = gate(return_value=cp("XSCHEM V3.4.4"))
        with tempfile.TemporaryDirectory() as d, which, run as m:
            with self.assertRaises(xe.XschemExportError):
                xe.run_xschem_netlist(
                    Path(d) / "c.sch", Path(d), ENV, Path(d) / "rc"
                )
        self.assertEqual(m.call_count, 1)  # the probe only

    def test_accepted_probe_uses_probed_executable(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)

            def fake(cmd, **kw):
                if cmd[1] == "--version":
                    return cp("XSCHEM V3.4.7")
                (out / "c.spice").write_text(".subckt c a  \n.ends\n")
                return cp()

            which, run = gate(side_effect=fake)
            with which, run as m:
                text = xe.run_xschem_netlist(out / "c.sch", out, ENV, out / "rc")
            self.assertEqual(text, ".subckt c a\n.ends\n")
            self.assertEqual(m.call_args.args[0][0], EXE)

    def test_erc_still_enforced_after_gate(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "c.spice").write_text(".subckt c\n.ends\n")

            def fake(cmd, **kw):
                if cmd[1] == "--version":
                    return cp("XSCHEM V3.4.7")
                return cp("undriven node foo")

            which, run = gate(side_effect=fake)
            with which, run, self.assertRaisesRegex(
                xe.XschemExportError, "xschem failed"
            ):
                xe.run_xschem_netlist(out / "c.sch", out, ENV, out / "rc")


class NetlistCliTests(unittest.TestCase):
    def setUp(self):
        import netlist  # design/netlist.py

        self.netlist = netlist

    def run_main(self, side_effect):
        err = io.StringIO()
        with unittest.mock.patch.object(
            self.netlist, "find_pdk"
        ), unittest.mock.patch.object(
            self.netlist, "xschem_env", return_value=ENV
        ), unittest.mock.patch.object(
            self.netlist, "run_xschem_netlist", side_effect=side_effect
        ), contextlib.redirect_stderr(err):
            rc = self.netlist.main(["--check", "--cell", "error_amp"])
        return rc, err.getvalue()

    def test_mismatch_reported_without_traceback(self):
        rc, err = self.run_main(
            xe.XschemExportError(
                "toolchain mismatch (found 3.4.4, need 3.4.7); see docs"
            )
        )
        self.assertEqual(rc, 1)
        self.assertIn("toolchain mismatch (found 3.4.4, need 3.4.7)", err)
        self.assertNotIn("Traceback", err)

    def test_real_gate_through_cli(self):
        which, run = gate(return_value=cp("XSCHEM V3.4.4"))
        real = xe.run_xschem_netlist
        with which, run as m:
            rc, err = self.run_main(real)
        self.assertEqual(rc, 1)
        self.assertIn("found 3.4.4, need 3.4.7", err)
        self.assertEqual(m.call_count, 1)

    def test_lvs_consumer_gets_gate_error(self):
        import drclvs

        which, run = gate(return_value=cp("XSCHEM V3.4.4"))
        pdk = unittest.mock.Mock()
        pdk.path = Path("/pdk/gf180mcuD")
        pdk.variant = "gf180mcuD"
        spec = unittest.mock.Mock(
            schematic=Path("/x/c.sch"), xschem_library_paths=[Path("/x")]
        )
        with which, run, tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(drclvs.StageError, "toolchain mismatch"):
                drclvs.export_netlist(pdk, spec, Path(d))


class DocstringConsistencyTests(unittest.TestCase):
    """netlist.py's docs must not name cells that design/*.sch lacks."""

    def test_docstring_cells_exist(self):
        import netlist

        cells = {p.stem for p in (REPO_ROOT / "design").glob("*.sch")}
        doc = netlist.__doc__
        named = set(re.findall(r"--cell (\w+)", doc))
        named |= set(re.findall(r"``(\w+)\.spice``", doc))
        named.discard("ldo_core")
        named.discard("cell")
        self.assertTrue(named)
        self.assertLessEqual(named, cells)
        self.assertIn(netlist.TOP_CELL, cells)
        self.assertNotIn("placeholder", doc)


if __name__ == "__main__":
    unittest.main()
