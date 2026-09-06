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
# call sites (e.g. sim/loop-stability/testbench/sweep.py) call
# `FATAL_LOG_RE.search()` themselves rather than going through a wrapper.
FATAL_LOG_RE = re.compile(FATAL_LOG_PATTERN, re.IGNORECASE)


class NgspiceMissing(RuntimeError):
    pass


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
    for line in out.splitlines():
        if "ngspice-" in line:
            return line.strip().lstrip("* ").strip()
    return out.strip().splitlines()[0] if out.strip() else "unknown"


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
    digest = hashlib.sha256()
    with open(exe, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def expected_ngspice_root() -> str | None:
    """The toolchain root this host's ``ngspice`` is expected to resolve
    under, per ``docs/environment-setup.md``.

    Resolution order (mirrors ``pdk.py``'s override-before-discovery
    convention):

    1. ``GF180_LDO_NGSPICE_ROOT`` -- explicit override, for a host whose
       validated toolchain docs/environment-setup.md does not (yet) describe
       a portable discovery rule for (e.g. a Linux/apt install, or a pinned
       from-source build per this issue's alternative), or to blot out the
       Homebrew probe below in a test/CI environment.
    2. ``brew --prefix ngspice`` -- the Homebrew-managed install
       ``docs/environment-setup.md`` (S1) documents as the validated one.
    3. ``None`` -- Homebrew is not on this host's ``PATH``; provenance is not
       enforced there yet (only the version banner + sha256 fingerprint are
       reported by ``--check-env``).
    """
    override = os.environ.get(NGSPICE_ROOT_ENV)
    if override:
        return override
    return homebrew_prefix("ngspice")


def verify_ngspice_provenance(resolved_exe: str, expected_root: str) -> None:
    """Raise :class:`NgspiceIdentityMismatch` unless ``resolved_exe`` lives
    under ``expected_root``.

    Both paths are resolved with ``Path.resolve()`` (following symlinks) so a
    Homebrew Cellar symlink and a self-built binary sitting at a different,
    PATH-shadowing prefix (the exact #182 failure mode) cannot alias one
    another.
    """
    resolved_real = Path(resolved_exe).resolve()
    expected_real = Path(expected_root).resolve()
    try:
        resolved_real.relative_to(expected_real)
    except ValueError:
        raise NgspiceIdentityMismatch(
            f"ngspice resolved on PATH ({resolved_exe} -> {resolved_real}) is not "
            f"under the pinned toolchain root ({expected_root} -> {expected_real}).\n"
            "  This is the #182 failure mode: a different ngspice build is "
            "shadowing the documented one on PATH.\n"
            "  Fix: `which -a ngspice` to see every candidate, then either "
            "reorder PATH so the pinned install resolves first, or remove/rename "
            "the shadowing binary.\n"
            "  If this host intentionally uses a different, already-validated "
            f"toolchain root, set {NGSPICE_ROOT_ENV}=<root> to bless it.\n"
            "  See docs/environment-setup.md #1 for the pinned version."
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
