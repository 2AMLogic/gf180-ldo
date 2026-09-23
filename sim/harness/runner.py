"""Deck composition and ngspice execution for one PVT point."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .corners import PvtPoint
from .pdk import Pdk
from .testbench import Testbench

NGSPICE = "ngspice"
DEFAULT_TIMEOUT_S = 300

# Model-bin selection, pinned in the deck (issue #214, DR-0025).
#
# gf180mcu's `pfet_03v3`/`nfet_03v3` cards are binned on (L, W) and the widest
# declared bin stops at `wmax = 100.001 um`. `design/netlist/ldo_core.spice`'s
# pass device is `W=2000u nf=40` -- 40 fingers of 50 um each -- so it lands in
# a declared bin (`pfet_03v3.12`) only if bin selection divides W by NF.
#
# Whether ngspice does that is neither a netlist nor a PDK property: it is
# ngspice's own `wnflag`, which is 1 only under HSPICE/Spectre compatibility
# and 0 otherwise. At `wnflag=0` the deck does not even parse -- every
# instantiation of the pass device dies with "could not find a valid
# modelname" (one of FATAL_LOG_PATTERNS below). ngspice never clamps or
# extrapolates to a neighbouring bin; measured, the only two outcomes are
# "the declared bin" and "hard parse error".
#
# Before this pin, which of those two a run got was a property of whichever
# host's `~/.spiceinit`/`spinit` happened to be in play, and no record
# captured it. Pinning it in the deck makes bin selection a property of this
# repo's decks. It is provably not a thumb on the scale: on a host that
# already had `wnflag=1`, adding the card changes nothing (the setting is
# what every successful run in `sim/` was already taken under -- DR-0025's
# Evidence section reproduces a committed record field-for-field to show it).
MODEL_BINNING_OPTION = "wnflag=1"
MODEL_BINNING_KEY = MODEL_BINNING_OPTION.split("=", 1)[0]


def _option_key(option: str) -> str:
    """The key half of an ``.options`` card body (``reltol=1e-5`` -> ``reltol``)."""
    return option.split("=", 1)[0].strip().lower()

# `print` output for a length-1 vector: "m_vout = 6.9043645202e-01"
_MEAS_RE = re.compile(r"^\s*m_(\w+)\s*=\s*([-+]?[0-9.]+(?:[eE][-+]?[0-9]+)?)\s*$")
_ERROR_RE = re.compile(r"^\s*(?:Error|ERROR|Fatal|fatal error|doAnalyses:)", re.MULTILINE)

# Phrases ngspice writes to stdout/stderr for a fatal condition (bad model
# lookup, singular Jacobian, non-convergence, ...) while still exiting 0 --
# every testbench's pass/fail gate has to grep for these on top of the exit
# code. Single source of truth for that gate (issue #157): before this, six
# call sites across five files each carried their own copy of this
# alternation and had drifted into four mutually-inconsistent variants (one
# file's own pass/fail check and its own diagnostic dump even disagreed with
# each other).
#
# This tuple is the union of the seven copies' *unconditionally-safe*
# phrases, deliberately dropping the eighth ("failed"/"failed!"/"failed$",
# present in 2 of the 6 bash copies) that #157 proposed adding: ngspice's own
# "Warning: Dynamic gmin stepping failed" -- a routine, non-fatal fallback
# notice, not an error -- ends every line it appears on, so a bare/anchored
# "failed" phrase matches it too. That is not hypothetical: it appears in
# already-recorded, already-passing evidence under
# sim/current-limit/corners/ (>100 occurrences across 3 record-ids as of this
# commit) and, even more directly, `sim/loop-stability/testbench/sweep.py`'s
# own docstring documents "a failed `meas` (no such crossing in band)" as an
# *expected*, non-fatal outcome for that testbench -- exactly the string a
# "failed" phrase would also catch. Including it here would have turned this
# consolidation into a regression (spurious fatal failures on already-passing
# corners) instead of a pure cleanup. None of the six call sites' own decks
# use a ngspice `.meas` whose failure is the *only* fatal signal (the four
# DC-sweep testbenches use `print`, not `.meas`, at all), so dropping it
# loses no real detection coverage anywhere it is actually exercised.
FATAL_LOG_PATTERNS: tuple[str, ...] = (
    "could not find a valid modelname",
    "Simulation interrupted",
    "singular matrix",
    "no convergence",
    "iteration limit reached",
    "fatal error",
    "no such vector",
)

# `|`-joined alternation string, ready for `grep -E` (bash call sites, via
# the same python-heredoc-`eval` pattern used for corner_sections() /
# ngspice_version()).
FATAL_LOG_PATTERN = "|".join(FATAL_LOG_PATTERNS)

# Case-insensitive: ngspice's own capitalization of these phrases is not
# consistent, and case-insensitivity only widens the match, never narrows
# it relative to any prior case-sensitive bash copy. Direct-import Python
# call sites (e.g. sim/loop-stability/testbench/sweep.py and
# sim/soft-start-loop-gain/testbench/sweep.py) go through
# `run_ngspice_deck()` below, which wraps `FATAL_LOG_RE.search()` alongside
# the other two run+validate checks (issue #209).
FATAL_LOG_RE = re.compile(FATAL_LOG_PATTERN, re.IGNORECASE)

# A `.let`/`v(...)` scalar assignment whose RHS references a vector that
# does not exist in the netlist (issue #242). ngspice does not hard-error
# on this: it exits 0 and prints, per sweep point,
#
#   Error: RHS "v(xdut.xsoftstart.gmsum)" invalid
#   Error: &gmsum_dc: no such variable.
#
# The obvious fix -- adding the bare substring "no such variable" to
# FATAL_LOG_PATTERNS above -- was tried and rejected: ngspice reuses that
# exact wording for a second, unrelated, *expected* non-fatal outcome. A
# `.meas ... find/when` that has no crossing in the swept band (documented
# in sim/loop-stability/testbench/tb_loop_stability.spice.in's own
# "margins" comment, e.g. `f0r`/`f180`/`gmx` when the phase never reaches
# -180 deg) leaves its `.meas`-defined scalar unset, which ngspice reports
# with the identical "Error: &<name>: no such variable." line. That case
# is not distinguished from the #242 bug by the bare phrase, and adding it
# to FATAL_LOG_PATTERNS turned >1,300 already-passing, already-recorded
# sweep corners under sim/loop-stability/corners/ and
# sim/soft-start-loop-gain/corners/ into false-positive fatal failures
# (measured against origin/main @ 53cca70, 2026-09-16 curation pass).
#
# The two cases ARE distinguishable one line earlier: the #242 bug's RHS is
# itself a raw `v(...)` vector reference (`RHS "v(...)" invalid`), while the
# benign `.meas`-crossing case's `RHS` is either an arithmetic expression
# (e.g. `f0*1.05`) or absent entirely. A corpus grep for
# `RHS "v(...)" invalid` across every committed corner log under
# `sim/*/corners/**/*.log` (same date/commit as above) found zero hits, so
# this narrower pattern is checked independently of FATAL_LOG_RE/
# FATAL_LOG_PATTERNS rather than folded into that tuple's flat
# substring-list contract.
_UNDEFINED_VECTOR_LET_RE = re.compile(
    r'RHS\s+"v\([^"]*\)"\s+invalid', re.IGNORECASE
)


class NgspiceMissing(RuntimeError):
    pass


def run_ngspice_deck(deck: Path, log: Path, workdir: Path) -> str:
    """Run one ngspice deck to completion and validate its output.

    Shared "run one deck, then validate it" wrapper for the sweep
    testbenches (``loop-stability``, ``soft-start-loop-gain``) that drive
    ngspice directly rather than going through :func:`run_point` -- issue
    #209 deduped this out of ``soft-start-loop-gain/testbench/sweep.py``'s
    own ``_ngspice()`` helper and an inlined copy in ``loop-stability``'s
    ``run_point()``, which had drifted to differ only in raise-vs-return
    error handling.

    Writes ngspice's combined stdout+stderr to ``log`` unconditionally (so
    the log is available for diagnosis even on failure), then raises
    :class:`RuntimeError` unless all four checks pass:

    1. ``ngspice`` exited 0.
    2. The output does not match :data:`FATAL_LOG_RE` (a fatal condition
       ngspice can report to stdout/stderr while still exiting 0).
    3. The output does not match :data:`_UNDEFINED_VECTOR_LET_RE` -- a
       ``.let``/``v(...)`` scalar assigned directly from a vector reference
       that does not exist in the netlist (issue #242). ngspice reports
       this as ``Error: RHS "v(...)" invalid`` while still exiting 0, and
       the plain "no such variable" wording it also prints for this case
       is deliberately NOT in :data:`FATAL_LOG_PATTERNS` -- see that
       pattern's own comment for why (it collides with an unrelated,
       expected non-fatal ``.meas`` outcome).
    4. The output contains the ``SWEEP COMPLETE`` marker the caller's own
       deck template prints at the end of a successful run.

    Returns the combined stdout+stderr text on success, for the caller to
    parse further (e.g. for ``ROW ...`` / ``HOV ...`` lines). Callers that
    want a non-raising, tuple-returning contract instead should catch
    ``RuntimeError`` at the call site (as ``loop-stability``'s
    ``run_point()`` does).
    """
    proc = subprocess.run(
        [NGSPICE, "-b", str(deck)],
        capture_output=True,
        text=True,
        cwd=str(workdir),
    )
    text = proc.stdout + proc.stderr
    log.write_text(text)
    if proc.returncode != 0:
        raise RuntimeError(f"ngspice exited {proc.returncode} (see {log})")
    if FATAL_LOG_RE.search(text):
        bad = [ln for ln in text.splitlines() if FATAL_LOG_RE.search(ln)][:3]
        raise RuntimeError(f"ngspice reported a fatal condition: {bad} (see {log})")
    if _UNDEFINED_VECTOR_LET_RE.search(text):
        bad = [
            ln for ln in text.splitlines() if _UNDEFINED_VECTOR_LET_RE.search(ln)
        ][:3]
        raise RuntimeError(
            f"ngspice's .let/v(...) referenced a vector that does not exist "
            f"in the netlist: {bad} (see {log})"
        )
    if "SWEEP COMPLETE" not in text:
        raise RuntimeError(f"sweep did not complete (see {log})")
    return text


def _parse_version_banner(out: str) -> str:
    for line in out.splitlines():
        if "ngspice-" in line:
            return line.strip().lstrip("* ").strip()
    return out.strip().splitlines()[0] if out.strip() else "unknown"


def ngspice_version() -> str:
    exe = shutil.which(NGSPICE)
    if not exe:
        raise NgspiceMissing(
            "ngspice not found on PATH.\n"
            "  macOS:  brew install ngspice\n"
            "  Debian: apt-get install ngspice"
        )
    out = subprocess.run(
        [exe, "--version"], capture_output=True, text=True, check=False
    ).stdout
    return _parse_version_banner(out)


def ngspice_version_at(exe: str | Path) -> str | None:
    """``<exe> --version``'s banner line, or ``None`` if it can't be run.

    Unlike :func:`ngspice_version` (which reports the binary resolved on
    ``PATH`` and raises when there is none), this answers the question "what
    version does *this particular* install provide?" for an arbitrary path --
    which is what identity checking against a pinned toolchain root needs
    (issue #247). A non-runnable / absent path is not an error here: it just
    means that root's version is unknown.
    """
    try:
        out = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _parse_version_banner(out) if out.strip() else None


_NGSPICE_MAJOR_RE = re.compile(r"\bngspice-(\d+)\b")


def ngspice_major_version(banner: str | None) -> str | None:
    """``"ngspice-46"`` out of a full banner line, or ``None``.

    The banner ngspice prints is chatty ("``ngspice-46 : Circuit level
    simulation program``"); the only part that is comparable against
    ``docs/environment-setup.md``'s pin is the ``ngspice-<major>`` token.
    """
    if not banner:
        return None
    match = _NGSPICE_MAJOR_RE.search(banner)
    return f"ngspice-{match.group(1)}" if match else None


def sha256_of(path: Path) -> str:
    """SHA-256 of the file at ``path``, read in 1 MiB chunks.

    Chunked rather than a single ``read()`` because the callers hash
    executables (an ngspice build is tens of megabytes) and there is no
    reason to hold one in memory to fingerprint it.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ngspice_binary_sha256() -> str:
    """SHA-256 of the ``ngspice`` executable currently resolved on ``PATH``.

    ``ngspice_version()`` reports only the self-printed banner line (e.g.
    ``"ngspice-46"``), which is the tool's own *claimed* identity, not a
    fingerprint of what is actually on disk. Issue #182 found two installed
    binaries on one development machine -- one at the resolved-first PATH
    entry, one at an older, still-present install prefix -- that print the
    identical ``"ngspice-46 ... Compiled with KLU Direct Linear Solver"``
    banner yet differ byte-for-byte (a local rebuild silently replaced the
    resolved one between two evidence-gathering passes a month apart). The
    version string alone cannot detect that; a content hash can. Callers
    that want this in a record's Environment section should treat it the
    same way as the netlist/manifest hashes already recorded there: a
    reproducibility fingerprint, not a claim about correctness.
    """
    exe = shutil.which(NGSPICE)
    if not exe:
        raise NgspiceMissing(
            "ngspice not found on PATH.\n"
            "  macOS:  brew install ngspice\n"
            "  Debian: apt-get install ngspice"
        )
    return sha256_of(Path(exe))


class NgspiceIdentityMismatch(RuntimeError):
    """Raised when the ``ngspice`` resolved on ``PATH`` is not the toolchain
    ``docs/environment-setup.md`` pins.

    Issue #184 (a fleet-wide-provisioning follow-up to #182's binary-hash
    fingerprint): a content hash alone makes drift *attributable* after the
    fact, but does not stop a self-built binary from silently shadowing the
    Homebrew install the doc tells every host to use. This turns that into a
    loud, actionable failure instead.
    """


NGSPICE_ROOT_ENV = "GF180_LDO_NGSPICE_ROOT"

# The ngspice major version `docs/environment-setup.md` #1 pins (46_1 via
# Homebrew). Kept here, next to the identity check that enforces it, so the
# check can tell "the binary drifted" apart from "the *pin probe* drifted"
# -- issue #247.
PINNED_NGSPICE_VERSION = "ngspice-46"

# Homebrew formula names probed for the expected toolchain root, in order.
#
# `brew --prefix ngspice` is NOT a pin: homebrew-core's unversioned `ngspice`
# formula tracks upstream, and on 2026-09-18 it moved to ngspice-47 -- which
# inverted the #184 identity check on every host that had upgraded. It began
# reporting the host's correctly-pinned ngspice-46 as the fault and naming
# the (unpinned) ngspice-47 Cellar as the root to "fix" towards. A *versioned*
# formula's prefix (`ngspice@46` -> `.../Cellar/ngspice@46/46_1`) cannot drift
# that way, so it is probed first and the unversioned formula is only a
# last-resort fallback whose version is checked before it is trusted.
PINNED_HOMEBREW_FORMULA = "ngspice@46"
DRIFTING_HOMEBREW_FORMULA = "ngspice"


@dataclass(frozen=True)
class NgspiceRoot:
    """A candidate toolchain root, plus how it was resolved and what it holds.

    ``source`` is human-readable provenance (``"brew --prefix ngspice@46"``,
    ``"GF180_LDO_NGSPICE_ROOT"``, ...) so a mismatch message can name *which*
    probe produced the root it is talking about. ``version`` is the
    ``ngspice-<major>`` token that root's own ``bin/ngspice`` reports, or
    ``None`` when that can't be determined -- a root whose version is not the
    pinned one is not an authority to point a user at (issue #247).
    """

    path: str
    source: str
    version: str | None = None

    @property
    def matches_pin(self) -> bool:
        return self.version == PINNED_NGSPICE_VERSION

    @property
    def drifted(self) -> bool:
        """This root exists but provides a version the docs do not pin."""
        return self.version is not None and self.version != PINNED_NGSPICE_VERSION


def homebrew_prefix(formula: str) -> str | None:
    """``brew --prefix <formula>``'s output, or ``None`` if unavailable.

    Returns ``None`` -- not an exception -- whenever this can't be answered
    (no ``brew`` on ``PATH``, ``brew`` errors, the formula isn't installed via
    it, or the call hangs): a host without Homebrew is not itself a fault
    (``docs/environment-setup.md``'s Linux/apt fallback exists for exactly
    this), it just means provenance can't be verified against the Homebrew
    pin on that host.
    """
    brew = shutil.which("brew")
    if not brew:
        return None
    try:
        out = subprocess.run(
            [brew, "--prefix", formula],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    path = out.stdout.strip()
    return path or None


def _root_ngspice_version(root: str) -> str | None:
    """The ``ngspice-<major>`` a candidate toolchain root actually provides."""
    exe = Path(root) / "bin" / NGSPICE
    if not exe.exists():
        return None
    return ngspice_major_version(ngspice_version_at(exe))


def expected_ngspice_root() -> NgspiceRoot | None:
    """The toolchain root this host's ``ngspice`` is expected to resolve
    under, per ``docs/environment-setup.md``.

    Resolution order (mirrors ``pdk.py``'s override-before-discovery
    convention):

    1. ``GF180_LDO_NGSPICE_ROOT`` -- explicit override, and the documented
       supported mechanism for any host whose validated ngspice-46 install
       is not a Homebrew keg (a Linux/apt install, a from-source build, or a
       Homebrew host whose unversioned formula has since moved on). Also
       blots out the Homebrew probes below in a test/CI environment.
    2. ``brew --prefix ngspice@46`` -- a *versioned*, keg-only formula, whose
       prefix cannot drift when Homebrew's unversioned ``ngspice`` upgrades.
    3. ``brew --prefix ngspice`` -- the unversioned formula. Still probed (it
       is what a host provisioned before #247 has), but it is explicitly NOT
       a pin: the returned :class:`NgspiceRoot` carries the version that root
       actually provides so callers can refuse to treat a drifted root as the
       authority (see :func:`verify_ngspice_provenance`).
    4. ``None`` -- no override and no Homebrew on this host's ``PATH``;
       provenance is not enforced there yet (only the version banner + sha256
       fingerprint are reported by ``--check-env``).

    A Homebrew candidate whose prefix does not exist on disk is skipped:
    ``brew --prefix <formula>`` answers for a *known* formula whether or not
    it is installed.
    """
    override = os.environ.get(NGSPICE_ROOT_ENV)
    if override:
        return NgspiceRoot(override, NGSPICE_ROOT_ENV, _root_ngspice_version(override))
    for formula in (PINNED_HOMEBREW_FORMULA, DRIFTING_HOMEBREW_FORMULA):
        prefix = homebrew_prefix(formula)
        if prefix and Path(prefix).exists():
            return NgspiceRoot(
                prefix, f"brew --prefix {formula}", _root_ngspice_version(prefix)
            )
    return None


def _wrong_version_message(
    resolved_exe: str,
    resolved_real: Path,
    resolved_version: str,
    expected_root: NgspiceRoot,
) -> str:
    return (
        f"ngspice resolved on PATH ({resolved_exe} -> {resolved_real}) reports "
        f"{resolved_version}, but docs/environment-setup.md #1 pins "
        f"{PINNED_NGSPICE_VERSION}.\n"
        f"  Expected toolchain root ({expected_root.source}): "
        f"{expected_root.path} ({expected_root.version or 'version unknown'}).\n"
        "  Fix: install the pinned version and make it resolve first on PATH.\n"
        "  Do NOT adopt whichever version Homebrew's unversioned `ngspice` "
        "formula happens to provide today: moving this repo's evidence onto a "
        "new ngspice major version is a spec-adjacent decision, not a PATH "
        "change. DR-0025's `wnflag` model-bin pin is confirmed to reproduce "
        "on ngspice-42 and ngspice-47 (DR-0027, issue #254), but that is only "
        "the prerequisite -- moving the pin itself still needs a ruling on "
        "every existing record.\n"
        f"  If this host intentionally runs an already-validated "
        f"{PINNED_NGSPICE_VERSION} install at some other prefix, set "
        f"{NGSPICE_ROOT_ENV}=<prefix> to bless it.\n"
        "  See docs/environment-setup.md #1 and its \"Keeping the ngspice pin "
        "from drifting\" section."
    )


def _drifted_root_message(
    resolved_exe: str,
    resolved_real: Path,
    resolved_version: str | None,
    expected_root: NgspiceRoot,
    expected_real: Path,
) -> str:
    suggested = resolved_real.parent.parent
    return (
        f"ngspice resolved on PATH ({resolved_exe} -> {resolved_real}) is not "
        f"under the expected toolchain root -- but it is the ROOT that has "
        "drifted off the pin here, not the binary.\n"
        f"  expected root   : {expected_root.source} -> {expected_root.path} "
        f"-> {expected_real} ({expected_root.version})\n"
        f"  resolved ngspice: {resolved_real} "
        f"({resolved_version or 'version unknown'})\n"
        f"  docs/environment-setup.md #1 pins {PINNED_NGSPICE_VERSION}; the "
        f"root above provides {expected_root.version}, which this repo has "
        "not adopted (DR-0025's `wnflag` model-bin pin was established on "
        "ngspice-46 only; DR-0027 / issue #254 confirms it also holds on "
        "ngspice-42 and ngspice-47, but confirming the facts is not itself a "
        "decision to move the pin).\n"
        "  Do NOT 'fix' this by putting that root first on PATH.\n"
        "  Corrective action, either of:\n"
        f"    1. Install a non-drifting pinned root -- a versioned, keg-only "
        f"`{PINNED_HOMEBREW_FORMULA}` formula -- so this probe stops falling "
        f"back to `brew --prefix {DRIFTING_HOMEBREW_FORMULA}`; or\n"
        f"    2. Bless the {PINNED_NGSPICE_VERSION} install this host already "
        "uses:\n"
        f"         export {NGSPICE_ROOT_ENV}={suggested}\n"
        "  See docs/environment-setup.md #1 -> \"Keeping the ngspice pin from "
        "drifting\"."
    )


def _shadowed_binary_message(
    resolved_exe: str,
    resolved_real: Path,
    resolved_version: str | None,
    expected_root: NgspiceRoot,
    expected_real: Path,
) -> str:
    return (
        f"ngspice resolved on PATH ({resolved_exe} -> {resolved_real}) is not "
        f"under the pinned toolchain root ({expected_root.source}: "
        f"{expected_root.path} -> {expected_real}).\n"
        f"  resolved ngspice: {resolved_version or 'version unknown'}; "
        f"pinned root: {expected_root.version or 'version unknown'}; "
        f"docs pin: {PINNED_NGSPICE_VERSION}.\n"
        "  This is the #182 failure mode: a different ngspice build is "
        "shadowing the documented one on PATH (two builds can print the same "
        "version banner and still differ byte-for-byte).\n"
        "  Fix: `which -a ngspice` to see every candidate, then either "
        "reorder PATH so the pinned install resolves first, or remove/rename "
        "the shadowing binary.\n"
        "  If this host intentionally uses a different, already-validated "
        f"toolchain root, set {NGSPICE_ROOT_ENV}=<root> to bless it.\n"
        "  See docs/environment-setup.md #1 for the pinned version."
    )


def verify_ngspice_provenance(
    resolved_exe: str,
    expected_root: NgspiceRoot,
    resolved_version: str | None = None,
) -> None:
    """Raise :class:`NgspiceIdentityMismatch` unless ``resolved_exe`` is the
    pinned toolchain: the pinned *version*, living under ``expected_root``.

    Two independent assertions, because #247 showed that checking only the
    second one can invert the diagnosis:

    1. **Version.** ``resolved_exe`` must report
       :data:`PINNED_NGSPICE_VERSION`. Without this, a host whose Homebrew
       ``ngspice`` formula silently upgraded would pass the containment check
       (the binary really is under ``brew --prefix ngspice``) while producing
       evidence on an unvalidated major version.
    2. **Containment.** ``resolved_exe`` must live under ``expected_root``,
       so a second, byte-different build of the *same* version cannot shadow
       the documented install (the original #182/#184 purpose). Both paths go
       through ``Path.resolve()`` (following symlinks) so a Homebrew Cellar
       symlink and a self-built binary at another prefix cannot alias.

    When containment fails, which of the two sides is at fault decides the
    message: a root that does not itself provide the pinned version is the
    drifted party, and the message says so instead of naming that root as the
    thing to "fix" towards.

    ``resolved_version`` (the ``ngspice-<major>`` token) is probed from
    ``resolved_exe`` when not supplied.
    """
    resolved_real = Path(resolved_exe).resolve()
    expected_real = Path(expected_root.path).resolve()
    if resolved_version is None:
        resolved_version = ngspice_major_version(ngspice_version_at(resolved_exe))

    if resolved_version is not None and resolved_version != PINNED_NGSPICE_VERSION:
        raise NgspiceIdentityMismatch(
            _wrong_version_message(
                resolved_exe, resolved_real, resolved_version, expected_root
            )
        ) from None

    try:
        resolved_real.relative_to(expected_real)
    except ValueError:
        pass
    else:
        return

    if expected_root.drifted:
        raise NgspiceIdentityMismatch(
            _drifted_root_message(
                resolved_exe,
                resolved_real,
                resolved_version,
                expected_root,
                expected_real,
            )
        ) from None
    raise NgspiceIdentityMismatch(
        _shadowed_binary_message(
            resolved_exe, resolved_real, resolved_version, expected_root, expected_real
        )
    ) from None


def compose_deck(tb: Testbench, pdk: Pdk, point: PvtPoint) -> str:
    """Build the complete, self-contained ngspice deck for one PVT point."""
    lines: list[str] = [
        f"* {tb.name} @ {point.corner_id} -- GENERATED by sim/harness, do not edit",
        f"* corner={point.corner.name} ({point.corner.description})",
        f"* temp={point.temp_c} C  vdd={point.vdd} V  pdk={pdk.variant}@{pdk.version}",
        "",
        "* ---- PVT parameters -------------------------------------------------",
        f".param vdd_nom={tb.nominal_supply_v!r}",
        f".param vdd_val={point.vdd!r}",
        f".param temp_c={point.temp_c!r}",
    ]
    for key, value in tb.params.items():
        lines.append(f".param {key}={value}")

    lines += [
        "",
        "* ---- gf180mcu models ------------------------------------------------",
        f'.include "{pdk.design_include}"',
    ]
    for section in point.corner.sections:
        lines.append(f'.lib "{pdk.model_lib}" {section}')

    lines += [
        "",
        f".temp {point.temp_c!r}",
    ]
    # Model-bin selection is harness-owned and deliberately NOT
    # manifest-overridable.
    #
    # For two `.options` cards naming the *same* key, ngspice keeps the FIRST
    # occurrence and silently discards every later one -- no warning, no
    # diagnostic. Measured on ngspice-46 (the pinned toolchain), both at the
    # cp-variable level and at the level of the effect that actually matters
    # here:
    #
    #   `.options wnflag=1` then `.options wnflag=0` -> wnflag reads 1;
    #       a `W=2000u nf=40` pfet_03v3 resolves to `pfet_03v3.12` and runs.
    #   `.options wnflag=0` then `.options wnflag=1` -> wnflag reads 0;
    #       the same device dies with "could not find a valid modelname".
    #
    # So card order *is* precedence order, earliest-wins, and the harness pin
    # is emitted first precisely so that it is the authoritative one. (An
    # earlier revision of this comment claimed the opposite -- that a later
    # manifest card would override the pin. That was never true; see
    # `sim/tests/test_ngspice_options_precedence.py`, which pins the real
    # ngspice behaviour so the claim cannot silently rot again.)
    #
    # A manifest `wnflag=` card would therefore be a card that ngspice
    # silently ignores -- the exact "silently wrong" failure mode this pin
    # exists to remove -- so reject it here instead of emitting it. The real
    # escape hatch, per DR-0025's Consequences, is an explicit `set wnflag=0`
    # in a `spinit`/`.spiceinit`: that is read *before* the deck, so it wins
    # by this same earliest-wins rule, and it fails loud (hard parse error)
    # on any deck instantiating the pass device.
    conflicting = sorted({o for o in tb.options if _option_key(o) == MODEL_BINNING_KEY})
    if conflicting:
        raise ValueError(
            f"{tb.directory}: manifest 'options' may not set "
            f"{MODEL_BINNING_KEY!r} (found {', '.join(repr(o) for o in conflicting)}). "
            f"The harness pins '.options {MODEL_BINNING_OPTION}' (issue #214, "
            "DR-0025) and ngspice keeps the FIRST card for a duplicate key, so a "
            "manifest card here would be silently ignored rather than applied. "
            "To run with model binning off, set it where it actually takes "
            "precedence -- `set wnflag=0` in a `.spiceinit` -- and expect the "
            "deck to fail loud."
        )
    lines.append(f".options {MODEL_BINNING_OPTION}")
    for option in tb.options:
        lines.append(f".options {option}")
    if tb.nodeset:
        terms = " ".join(f"v({node})={value}" for node, value in tb.nodeset.items())
        lines.append(f".nodeset {terms}")

    # One harness-owned include block for every design netlist: the manifest's
    # 'dut_netlist' (the designated DUT, first) followed by its 'includes'.
    if tb.design_netlists:
        lines += [
            "",
            "* ---- design cells (manifest 'dut_netlist' + 'includes') --------------",
        ]
        lines += [f'.include "{path}"' for path in tb.design_netlists]

    lines += [
        "",
        "* ---- testbench ------------------------------------------------------",
        f'.include "{tb.netlist}"',
        "",
        "* ---- measurement ----------------------------------------------------",
        ".control",
        "set numdgt=10",
        "set noaskquit",
    ]
    lines += [f"  {analysis}" for analysis in tb.analyses]
    for name, expr in tb.measure.items():
        lines.append(f"  let m_{name} = {expr}")
    for name in tb.measure:
        lines.append(f"  print m_{name}")
    lines += [".endc", ".end", ""]
    return "\n".join(lines)


@dataclass
class PointResult:
    point: PvtPoint
    status: str                                   # "ok" | "failed" | "error"
    measurements: dict[str, float] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    seconds: float = 0.0
    deck: str = ""
    log: str = ""
    message: str = ""

    def as_dict(self) -> dict:
        record = self.point.as_dict()
        record.update(
            {
                "status": self.status,
                "measurements": self.measurements,
                "seconds": round(self.seconds, 3),
                "deck": self.deck,
                "log": self.log,
            }
        )
        if self.missing:
            record["missing_measurements"] = self.missing
        if self.message:
            record["message"] = self.message
        return record


def parse_measurements(text: str) -> dict[str, float]:
    found: dict[str, float] = {}
    for line in text.splitlines():
        match = _MEAS_RE.match(line)
        if match:
            try:
                found[match.group(1)] = float(match.group(2))
            except ValueError:  # pragma: no cover - regex already constrains this
                continue
    return found


def run_point(
    tb: Testbench,
    pdk: Pdk,
    point: PvtPoint,
    workdir: Path,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    log_dir: Path | None = None,
) -> PointResult:
    """Simulate one PVT point. Never raises for simulation failure.

    ``workdir`` holds the generated deck (scratch, disposable). ``log_dir``
    -- when given -- is where the raw ngspice output lands as
    ``<corner-id>.log``; that is the ``sim/<slug>/corners/<record-id>/``
    directory from ``sim/README.md``. It defaults to ``workdir`` so a
    throwaway run does not touch the evidence tree.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    log_dir = workdir if log_dir is None else log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    deck_path = workdir / f"{point.corner_id}.spice"
    log_path = log_dir / f"{point.corner_id}.log"
    deck_path.write_text(compose_deck(tb, pdk, point))

    started = time.monotonic()
    try:
        proc = subprocess.run(
            [NGSPICE, "-b", str(deck_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=workdir,
            check=False,
        )
        output = proc.stdout + "\n" + proc.stderr
        returncode = proc.returncode
    except FileNotFoundError as exc:
        raise NgspiceMissing(str(exc)) from exc
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started
        log_path.write_text(f"TIMEOUT after {timeout_s}s\n")
        return PointResult(
            point=point,
            status="error",
            seconds=elapsed,
            deck=deck_path.name,
            log=log_path.name,
            message=f"ngspice timed out after {timeout_s}s",
        )
    elapsed = time.monotonic() - started
    log_path.write_text(output)

    measurements = parse_measurements(output)
    missing = [name for name in tb.measure if name not in measurements]

    if missing:
        errors = "; ".join(_ERROR_RE.findall(output)[:3])
        first_error = next(
            (line.strip() for line in output.splitlines() if _ERROR_RE.match(line)), ""
        )
        return PointResult(
            point=point,
            status="failed",
            measurements=measurements,
            missing=missing,
            seconds=elapsed,
            deck=deck_path.name,
            log=log_path.name,
            message=first_error or errors or f"ngspice exit {returncode}, no measurements parsed",
        )

    return PointResult(
        point=point,
        status="ok",
        measurements=measurements,
        seconds=elapsed,
        deck=deck_path.name,
        log=log_path.name,
    )


def run_grid(
    tb: Testbench,
    pdk: Pdk,
    points: list[PvtPoint],
    workdir: Path,
    jobs: int = 1,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    on_result=None,
    log_dir: Path | None = None,
) -> list[PointResult]:
    """Run every PVT point; results come back in grid order regardless of jobs."""
    results: list[PointResult | None] = [None] * len(points)

    def _one(index_point):
        index, point = index_point
        result = run_point(tb, pdk, point, workdir, timeout_s=timeout_s, log_dir=log_dir)
        results[index] = result
        if on_result is not None:
            on_result(result)
        return result

    if jobs <= 1:
        for item in enumerate(points):
            _one(item)
    else:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            list(pool.map(_one, enumerate(points)))

    return [r for r in results if r is not None]
