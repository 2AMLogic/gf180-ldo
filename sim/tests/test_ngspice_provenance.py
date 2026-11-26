#!/usr/bin/env python3
"""Unit tests for the ngspice toolchain identity checks behind
``--check-env``. No PDK and no ngspice required: every ``ngspice`` resolved
here is a stub in a temporary directory, never the host's own, and the PDK is
``test_harness.fake_pdk``.

    python3 -m unittest sim/tests/test_ngspice_provenance.py -v
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import cli, runner  # noqa: E402
from harness.pdk import PdkNotFound  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_harness import fake_pdk  # noqa: E402


def fake_ngspice_install(root: Path, version: str = "ngspice-46") -> Path:
    """An executable ``<root>/bin/ngspice`` stub that prints a real banner.

    ``_root_ngspice_version()`` / ``ngspice_version_at()`` (issue #247) decide
    a candidate root's identity by *running* its binary, so a root fixture has
    to be runnable, not just a file on disk.
    """
    exe = root / "bin" / "ngspice"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text(
        "#!/bin/sh\n"
        f"echo '** {version} : Circuit level simulation program'\n"
        "echo '** Compiled with KLU Direct Linear Solver'\n"
    )
    exe.chmod(0o755)
    return exe


def env_without_ngspice_root_override() -> dict:
    # These tests drive `expected_ngspice_root()` entirely through the
    # mocked `homebrew_prefix()`; strip any ambient GF180_LDO_NGSPICE_ROOT
    # so a developer's/CI's own real environment cannot change which branch
    # a given test exercises (the check #184 added does not depend on any
    # environment variable or state that isn't reproducible across hosts --
    # the original #182 defect).
    env = dict(os.environ)
    env.pop(runner.NGSPICE_ROOT_ENV, None)
    return env


class NgspiceBinaryFingerprintTests(unittest.TestCase):
    """Issue #182: the self-reported ``ngspice --version`` banner was found

    insufficient to detect a silent binary content change -- two
    differently-built ``ngspice-46`` binaries on one machine printed the
    identical version string. ``ngspice_binary_sha256()`` fingerprints the
    binary ``ngspice_version()`` resolves via ``PATH``, so a later comparison
    can tell a rebuild from a real change even when the version string does
    not move. Uses a fake executable, not a real ngspice install, per this
    file's own "No PDK and no ngspice required" contract.
    """

    def test_hashes_the_resolved_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_exe = Path(tmp) / "ngspice"
            fake_exe.write_bytes(b"fake ngspice binary content, build A\n")
            with unittest.mock.patch("shutil.which", return_value=str(fake_exe)):
                digest = runner.ngspice_binary_sha256()
            import hashlib
            self.assertEqual(digest, hashlib.sha256(fake_exe.read_bytes()).hexdigest())

    def test_a_content_change_moves_the_hash_even_with_the_same_path(self):
        """The whole point: a rebuild at the same resolved path is detectable."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_exe = Path(tmp) / "ngspice"
            fake_exe.write_bytes(b"fake ngspice binary content, build A\n")
            with unittest.mock.patch("shutil.which", return_value=str(fake_exe)):
                before = runner.ngspice_binary_sha256()
            fake_exe.write_bytes(b"fake ngspice binary content, build B (rebuilt)\n")
            with unittest.mock.patch("shutil.which", return_value=str(fake_exe)):
                after = runner.ngspice_binary_sha256()
            self.assertNotEqual(before, after)

    def test_missing_ngspice_raises_ngspice_missing(self):
        with unittest.mock.patch("shutil.which", return_value=None):
            with self.assertRaises(runner.NgspiceMissing):
                runner.ngspice_binary_sha256()


class NgspiceProvenanceTests(unittest.TestCase):
    """Issue #184: a version-string match is not enough -- #182 found a
    self-built ``ngspice`` shadowing the Homebrew install
    ``docs/environment-setup.md`` documents, on PATH, ahead of it. These
    cover the identity check that turns that into a loud, actionable
    ``--check-env`` failure instead of a silent "OK".

    Issue #247 extended the check after Homebrew's unversioned ``ngspice``
    formula moved to ngspice-47: the *expected root* can itself drift off the
    pin, and the check must then blame the root rather than the
    correctly-pinned binary it resolved on PATH.
    """

    def _root(self, path: Path, version: str | None = "ngspice-46", source="test"):
        return runner.NgspiceRoot(str(path), source, version)

    def test_resolved_exe_under_expected_root_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew"
            exe = fake_ngspice_install(root)
            # Should not raise.
            runner.verify_ngspice_provenance(str(exe), self._root(root))

    def test_resolved_exe_outside_expected_root_raises_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew"
            shadow_root = Path(tmp) / "local-build"
            fake_ngspice_install(root)
            exe = fake_ngspice_install(shadow_root)
            with self.assertRaises(runner.NgspiceIdentityMismatch) as ctx:
                runner.verify_ngspice_provenance(str(exe), self._root(root))
            message = str(ctx.exception)
            self.assertIn(str(exe), message)
            self.assertIn(str(root), message)
            self.assertIn("GF180_LDO_NGSPICE_ROOT", message)
            # Both sides are the pinned version here: this really IS #182's
            # shadowed-binary case, and must keep saying so.
            self.assertIn("#182 failure mode", message)

    def test_drifted_expected_root_is_blamed_not_the_pinned_binary(self):
        """Issue #247's core repro, reworked for the floor (DR-0043): the
        *root* is below the floor while the binary on PATH meets it."""
        with tempfile.TemporaryDirectory() as tmp:
            drifted_root = Path(tmp) / "homebrew-45"
            fake_ngspice_install(drifted_root, "ngspice-45")
            pinned_prefix = Path(tmp) / "pinned-46"
            exe = fake_ngspice_install(pinned_prefix, "ngspice-46")
            with self.assertRaises(runner.NgspiceIdentityMismatch) as ctx:
                runner.verify_ngspice_provenance(
                    str(exe),
                    self._root(
                        drifted_root, "ngspice-45", source="brew --prefix ngspice"
                    ),
                )
            message = str(ctx.exception)
            self.assertIn("ROOT that has drifted", message)
            self.assertNotIn("#182 failure mode", message)
            self.assertIn("Do NOT 'fix' this by putting that root first", message)
            self.assertIn(runner.PINNED_HOMEBREW_FORMULA, message)
            self.assertIn(
                f"export {runner.NGSPICE_ROOT_ENV}={pinned_prefix.resolve()}", message
            )
            self.assertIn("DR-0043", message)

    def test_newer_binary_under_the_root_is_accepted(self):
        """The floor has no ceiling: 46 and 47 both pass (DR-0043)."""
        for version in ("ngspice-46", "ngspice-47", "ngspice-100"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "homebrew"
                exe = fake_ngspice_install(root, version)
                runner.verify_ngspice_provenance(str(exe), self._root(root, version))

    def test_below_floor_binary_fails_even_when_it_lives_under_the_root(self):
        """A below-floor ngspice that really is under the expected root is
        still refused -- containment alone would call that OK."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew-45"
            exe = fake_ngspice_install(root, "ngspice-45")
            with self.assertRaises(runner.NgspiceIdentityMismatch) as ctx:
                runner.verify_ngspice_provenance(
                    str(exe), self._root(root, "ngspice-45")
                )
            message = str(ctx.exception)
            self.assertIn("reports ngspice-45", message)
            self.assertIn(f"at least {runner.NGSPICE_FLOOR_TOKEN}", message)

    def test_containment_still_enforced_at_any_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew"
            fake_ngspice_install(root, "ngspice-47")
            exe = fake_ngspice_install(Path(tmp) / "other", "ngspice-47")
            with self.assertRaises(runner.NgspiceIdentityMismatch) as ctx:
                runner.verify_ngspice_provenance(
                    str(exe), self._root(root, "ngspice-47")
                )
            self.assertIn("#182 failure mode", str(ctx.exception))

    def test_floor_compares_majors_as_integers(self):
        self.assertTrue(runner.meets_ngspice_floor("ngspice-100"))
        self.assertTrue(runner.below_ngspice_floor("ngspice-9"))
        self.assertFalse(runner.below_ngspice_floor(None))
        self.assertFalse(runner.meets_ngspice_floor(None))
        self.assertFalse(runner.below_ngspice_floor("no token"))

    def test_unrunnable_root_binary_leaves_version_unknown_not_drifted(self):
        """A blessed root we cannot probe (no runnable ``bin/ngspice``) is
        "unknown", never "drifted" -- an unknown version must not fabricate a
        drift diagnosis."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "blessed"
            root.mkdir()
            shadow = Path(tmp) / "elsewhere"
            exe = fake_ngspice_install(shadow)
            candidate = self._root(root, None)
            self.assertFalse(candidate.drifted)
            with self.assertRaises(runner.NgspiceIdentityMismatch) as ctx:
                runner.verify_ngspice_provenance(str(exe), candidate)
            self.assertIn("#182 failure mode", str(ctx.exception))

    def test_ngspice_major_version_extracts_the_pin_token(self):
        self.assertEqual(
            runner.ngspice_major_version(
                "ngspice-46 : Circuit level simulation program"
            ),
            "ngspice-46",
        )
        self.assertEqual(
            runner.ngspice_major_version("** ngspice-47 : Circuit level"), "ngspice-47"
        )
        self.assertIsNone(runner.ngspice_major_version("unknown"))
        self.assertIsNone(runner.ngspice_major_version(None))

    def test_ngspice_version_at_reads_a_specific_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = fake_ngspice_install(Path(tmp) / "root", "ngspice-47")
            self.assertEqual(
                runner.ngspice_major_version(runner.ngspice_version_at(exe)),
                "ngspice-47",
            )

    def test_ngspice_version_at_returns_none_for_a_missing_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(runner.ngspice_version_at(Path(tmp) / "nope"))

    def test_expected_ngspice_root_prefers_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            blessed = Path(tmp) / "blessed"
            fake_ngspice_install(blessed)
            with unittest.mock.patch.dict(
                "os.environ", {runner.NGSPICE_ROOT_ENV: str(blessed)}
            ):
                with unittest.mock.patch.object(
                    runner, "homebrew_prefix", return_value="/opt/homebrew"
                ) as homebrew_prefix:
                    resolved = runner.expected_ngspice_root()
                    homebrew_prefix.assert_not_called()
            self.assertEqual(resolved.path, str(blessed))
            self.assertEqual(resolved.source, runner.NGSPICE_ROOT_ENV)
            self.assertEqual(resolved.version, "ngspice-46")

    def test_expected_ngspice_root_prefers_the_versioned_homebrew_formula(self):
        """Issue #247, Option 1: a versioned keg's prefix cannot drift when
        the unversioned formula upgrades, so it wins the probe order."""
        with tempfile.TemporaryDirectory() as tmp:
            pinned = Path(tmp) / "ngspice@46"
            drifted = Path(tmp) / "ngspice"
            fake_ngspice_install(pinned, "ngspice-46")
            fake_ngspice_install(drifted, "ngspice-47")
            prefixes = {
                runner.PINNED_HOMEBREW_FORMULA: str(pinned),
                runner.DRIFTING_HOMEBREW_FORMULA: str(drifted),
            }
            with unittest.mock.patch.dict(
                os.environ, env_without_ngspice_root_override(), clear=True
            ):
                with unittest.mock.patch.object(
                    runner, "homebrew_prefix", side_effect=prefixes.get
                ):
                    resolved = runner.expected_ngspice_root()
            self.assertEqual(resolved.path, str(pinned))
            self.assertEqual(
                resolved.source, f"brew --prefix {runner.PINNED_HOMEBREW_FORMULA}"
            )
            self.assertEqual(resolved.version, "ngspice-46")
            self.assertFalse(resolved.drifted)

    def test_expected_ngspice_root_falls_back_to_the_unversioned_formula(self):
        """A host with no versioned keg still gets a root -- but one that
        reports the version it actually holds, so a drifted fallback can be
        recognised as such rather than trusted as the pin."""
        with tempfile.TemporaryDirectory() as tmp:
            drifted = Path(tmp) / "ngspice"
            fake_ngspice_install(drifted, "ngspice-45")
            prefixes = {runner.DRIFTING_HOMEBREW_FORMULA: str(drifted)}
            with unittest.mock.patch.dict(
                os.environ, env_without_ngspice_root_override(), clear=True
            ):
                with unittest.mock.patch.object(
                    runner, "homebrew_prefix", side_effect=prefixes.get
                ):
                    resolved = runner.expected_ngspice_root()
            self.assertEqual(resolved.path, str(drifted))
            self.assertEqual(
                resolved.source, f"brew --prefix {runner.DRIFTING_HOMEBREW_FORMULA}"
            )
            self.assertTrue(resolved.drifted)

    def test_expected_ngspice_root_skips_a_prefix_that_is_not_installed(self):
        """``brew --prefix <formula>`` answers for a *known* formula whether
        or not it is installed, so a non-existent prefix must not win."""
        with tempfile.TemporaryDirectory() as tmp:
            drifted = Path(tmp) / "ngspice"
            fake_ngspice_install(drifted, "ngspice-47")
            prefixes = {
                runner.PINNED_HOMEBREW_FORMULA: str(Path(tmp) / "not-installed"),
                runner.DRIFTING_HOMEBREW_FORMULA: str(drifted),
            }
            with unittest.mock.patch.dict(
                os.environ, env_without_ngspice_root_override(), clear=True
            ):
                with unittest.mock.patch.object(
                    runner, "homebrew_prefix", side_effect=prefixes.get
                ):
                    resolved = runner.expected_ngspice_root()
            self.assertEqual(resolved.path, str(drifted))

    def test_expected_ngspice_root_is_none_without_homebrew_or_override(self):
        with unittest.mock.patch.dict(
            os.environ, env_without_ngspice_root_override(), clear=True
        ):
            with unittest.mock.patch.object(runner, "homebrew_prefix", return_value=None):
                self.assertIsNone(runner.expected_ngspice_root())

    def test_homebrew_prefix_returns_none_when_brew_missing(self):
        with unittest.mock.patch("shutil.which", return_value=None):
            self.assertIsNone(runner.homebrew_prefix("ngspice"))

    def test_homebrew_prefix_returns_none_on_nonzero_exit(self):
        fake_result = unittest.mock.Mock(returncode=1, stdout="")
        with unittest.mock.patch("shutil.which", return_value="/opt/homebrew/bin/brew"):
            with unittest.mock.patch("subprocess.run", return_value=fake_result):
                self.assertIsNone(runner.homebrew_prefix("ngspice"))

    def test_homebrew_prefix_returns_stripped_stdout_on_success(self):
        fake_result = unittest.mock.Mock(returncode=0, stdout="/opt/homebrew/opt/ngspice\n")
        with unittest.mock.patch("shutil.which", return_value="/opt/homebrew/bin/brew"):
            with unittest.mock.patch("subprocess.run", return_value=fake_result):
                self.assertEqual(
                    runner.homebrew_prefix("ngspice"), "/opt/homebrew/opt/ngspice"
                )


class CheckEnvProvenanceTests(unittest.TestCase):
    """Issue #184's own acceptance criterion: ``--check-env`` must exit
    non-zero with an actionable message on a resolved/expected-root
    mismatch, not just when ``ngspice`` is entirely missing, and must stay
    ``OK`` on the happy path.
    """

    def setUp(self):
        # Default to a valid PDK so the ngspice checks determine the exit status.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pdk = fake_pdk(Path(tmp.name) / "pdk")
        patcher = unittest.mock.patch.object(cli, "find_pdk", return_value=pdk)
        self.find_pdk = patcher.start()
        self.addCleanup(patcher.stop)

    def _run_check_env(self, exe: Path, **extra_env):
        env = env_without_ngspice_root_override()
        env["PATH"] = str(exe.parent)
        env.update(extra_env)
        buffer = io.StringIO()
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            with contextlib.redirect_stdout(buffer):
                status = cli.cmd_check_env()
        return status, buffer.getvalue()

    def test_matching_provenance_reports_ok_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew"
            exe = fake_ngspice_install(root)
            with unittest.mock.patch.object(runner, "homebrew_prefix", return_value=str(root)):
                status, out = self._run_check_env(exe)
            self.assertIn("provenance OK", out)
            self.assertNotIn("MISMATCH", out)
            self.assertIn("ngspice : OK", out)
            self.assertEqual(status, cli.EXIT_OK)

    def test_shadowing_binary_fails_loudly_not_silently(self):
        """The core #182/#184 repro: a different build resolves first on
        PATH than the one the doc pins, both claiming to be ngspice-46.

        Issue #247's regression guard: this must keep failing for the #182
        reason, and must keep naming the shadowing binary."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew"
            fake_ngspice_install(root)
            shadow_exe = fake_ngspice_install(Path(tmp) / "local-build")
            with unittest.mock.patch.object(runner, "homebrew_prefix", return_value=str(root)):
                status, out = self._run_check_env(shadow_exe)
            self.assertEqual(status, cli.EXIT_ENVIRONMENT)
            self.assertIn("MISMATCH", out)
            self.assertIn(str(shadow_exe), out)
            self.assertIn("#182 failure mode", out)

    def test_drifted_homebrew_root_names_the_real_corrective_action(self):
        """Issue #247 end to end: on a host whose unversioned Homebrew
        ``ngspice`` is below the floor (45), ``--check-env`` must stop presenting the
        ngspice-45 Cellar as the root to "fix" towards."""
        with tempfile.TemporaryDirectory() as tmp:
            drifted = Path(tmp) / "homebrew-ngspice-45"
            fake_ngspice_install(drifted, "ngspice-45")
            pinned_prefix = Path(tmp) / "pinned-46"
            exe = fake_ngspice_install(pinned_prefix, "ngspice-46")
            prefixes = {runner.DRIFTING_HOMEBREW_FORMULA: str(drifted)}
            with unittest.mock.patch.object(runner, "homebrew_prefix", side_effect=prefixes.get):
                status, out = self._run_check_env(exe)
            self.assertEqual(status, cli.EXIT_ENVIRONMENT)
            self.assertIn("MISMATCH", out)
            self.assertIn("ROOT that has drifted", out)
            self.assertIn(
                f"export {runner.NGSPICE_ROOT_ENV}={pinned_prefix.resolve()}", out
            )
            self.assertNotIn("#182 failure mode", out)

    def test_blessed_root_env_var_is_a_supported_happy_path(self):
        """Issue #247, Option 2: ``GF180_LDO_NGSPICE_ROOT`` is the documented
        mechanism for a host whose pinned ngspice-46 is not a Homebrew keg --
        it must reach ``provenance OK``, not merely suppress the error."""
        with tempfile.TemporaryDirectory() as tmp:
            blessed = Path(tmp) / "blessed-46"
            exe = fake_ngspice_install(blessed)
            drifted = Path(tmp) / "homebrew-ngspice-47"
            fake_ngspice_install(drifted, "ngspice-47")
            with unittest.mock.patch.object(runner, "homebrew_prefix", return_value=str(drifted)):
                status, out = self._run_check_env(
                    exe, **{runner.NGSPICE_ROOT_ENV: str(blessed)}
                )
            self.assertIn("provenance OK", out)
            self.assertIn(runner.NGSPICE_ROOT_ENV, out)
            self.assertNotIn("MISMATCH", out)
            self.assertEqual(status, cli.EXIT_OK)

    def test_no_homebrew_and_no_override_reports_unverified_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = fake_ngspice_install(Path(tmp) / "local-46", "ngspice-46")
            with unittest.mock.patch.object(runner, "homebrew_prefix", return_value=None):
                status, out = self._run_check_env(exe)
            self.assertIn("provenance not verified", out)
            self.assertNotIn("MISMATCH", out)
            self.assertEqual(status, cli.EXIT_OK)

    def test_unverifiable_host_off_the_pin_notes_it_without_failing(self):
        """CI's own ``pvt-smoke`` job runs Ubuntu's apt ngspice-42 on purpose
        (a standing model-bin portability check; DR-0027 / issue #254
        confirms its wnflag facts reproduce). #247's version pin must be
        *reported* there, never enforced -- that host has no pinned root to
        check against and is deliberately a different build."""
        with tempfile.TemporaryDirectory() as tmp:
            exe = fake_ngspice_install(Path(tmp) / "apt-42", "ngspice-42")
            with unittest.mock.patch.object(runner, "homebrew_prefix", return_value=None):
                status, out = self._run_check_env(exe)
            self.assertIn("provenance not verified", out)
            self.assertIn("ngspice-42", out)
            self.assertIn(runner.NGSPICE_FLOOR_TOKEN, out)
            self.assertNotIn("MISMATCH", out)
            self.assertEqual(status, cli.EXIT_OK)

    def test_missing_pdk_alone_drives_the_exit_status(self):
        """The missing-PDK branch on its own (#858): ngspice provenance
        matches, so a non-zero exit has exactly one cause -- the PDK."""
        self.find_pdk.side_effect = PdkNotFound("no pdk")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "homebrew"
            exe = fake_ngspice_install(root)
            with unittest.mock.patch.object(runner, "homebrew_prefix", return_value=str(root)):
                status, out = self._run_check_env(exe)
            self.assertEqual(status, cli.EXIT_ENVIRONMENT)
            self.assertIn("ngspice : OK", out)
            self.assertIn("provenance OK", out)
            self.assertIn("PDK     : MISSING", out)


if __name__ == "__main__":
    unittest.main()
