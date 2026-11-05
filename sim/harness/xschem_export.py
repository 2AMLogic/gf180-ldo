"""Shared xschem headless netlist-export invocation.

``design/netlist.py`` and ``layout/drclvs.py`` both need to run xschem
headless, with ERC enabled, to netlist a single ``.sch`` cell -- one for
simulation, one for LVS. The invocation, the ERC-failure detection, and the
output normalization are identical between the two call sites, so this is
the one implementation of "run xschem on a cell and get clean, diffable
text back", continuing the pattern ``sim/harness/pdk.py`` already
established for PDK discovery.

Deliberately scoped to just that shared step. Downstream checks legitimately
diverge per caller -- e.g. ``layout/drclvs.py`` additionally verifies the
export landed in xschem's LVS form (``lvs_format``, not ``format``) -- so
those stay in each caller, layered on top of the text this module returns.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The one xschem release this repo's netlists (and LVS exports) are generated
# with. Keep in sync with docs/environment-setup.md (a unit test checks it).
# This is version enforcement, not a claim that every build bearing this
# version string is byte-identical.
XSCHEM_PINNED_VERSION = "3.4.7"

XSCHEM_VERSION_TIMEOUT_S = 30

# Bound on one `klt netlist` export (real runs take well under a second).
KLT_NETLIST_TIMEOUT_S = 120
KLT_NETLIST_GRACE_S = 30
KLT_PROVENANCE_PREFIX = "** klt-netlist-inputs:"

_XSCHEM_VERSION_RE = re.compile(r"XSCHEM\s+V(\d+(?:\.\d+)+)", re.IGNORECASE)

_SETUP_HINT = "see docs/environment-setup.md section 2 (Build xschem from source)"


class XschemExportError(RuntimeError):
    """xschem could not be run, or its own ERC/connectivity checks failed."""


def check_xschem_version(env: dict[str, str]) -> str:
    """Verify the ``xschem`` resolved from ``env`` is ``XSCHEM_PINNED_VERSION``.

    Returns the absolute path of the probed executable so the caller invokes
    exactly what was validated. Not cached: every call re-probes. Raises
    :class:`XschemExportError` if xschem is missing, the probe fails, times
    out, prints nothing parseable, or reports a different version.
    """
    exe = shutil.which("xschem", path=env.get("PATH", os.defpath))
    if exe is None:
        raise XschemExportError(
            f"xschem not found on PATH; need {XSCHEM_PINNED_VERSION} "
            f"({_SETUP_HINT})"
        )
    try:
        proc = subprocess.run(
            [exe, "--version"], env=env, capture_output=True, text=True,
            timeout=XSCHEM_VERSION_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise XschemExportError(
            f"toolchain check failed: `{exe} --version` timed out after "
            f"{XSCHEM_VERSION_TIMEOUT_S}s"
        ) from exc
    except OSError as exc:
        raise XschemExportError(
            f"toolchain check failed: could not run `{exe} --version`: {exc}"
        ) from exc
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise XschemExportError(
            f"toolchain check failed: `{exe} --version` exited "
            f"{proc.returncode}\n{output.strip()}"
        )
    m = _XSCHEM_VERSION_RE.search(output)
    if m is None:
        raise XschemExportError(
            f"toolchain check failed: could not parse a version from "
            f"`{exe} --version` output: {output.strip()!r}"
        )
    found = m.group(1)
    if found != XSCHEM_PINNED_VERSION:
        raise XschemExportError(
            f"toolchain mismatch (found {found}, need "
            f"{XSCHEM_PINNED_VERSION}); {_SETUP_HINT}"
        )
    return exe


def normalize(text: str) -> str:
    """Make xschem output machine-independent (and therefore diffable)."""
    text = text.replace(str(REPO_ROOT) + os.sep, "")
    # Trailing whitespace is not load bearing and varies with symbol text.
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.rstrip("\n") + "\n"


def run_xschem_netlist(
    sch: Path, outdir: Path, env: dict[str, str], rcfile: Path
) -> str:
    """Netlist ``sch`` headless (ERC on) via ``klt netlist`` and return the
    normalized text of ``outdir/<sch.stem>.spice``.

    ``klt netlist`` owns the xschem invocation: it forces the headless flags,
    bounds the run with ``--timeout-s`` (killing the whole process group on
    expiry, so a hung xschem cannot block the caller), and fails on ERC
    findings and unresolved symbols (``--erc``).

    Raises :class:`XschemExportError` if xschem is not the pinned version
    (checked before anything is netlisted), ``klt`` is missing, or the export
    fails, times out, or reports an ERC/connectivity problem.
    """
    xschem = check_xschem_version(env)
    klt = shutil.which("klt", path=env.get("PATH", os.defpath))
    if klt is None:
        raise XschemExportError(
            "klt not found on PATH; `klt netlist` performs the xschem export "
            "(see docs/environment-setup.md)"
        )
    produced = outdir / f"{sch.stem}.spice"
    cmd = [
        klt, "netlist", "--erc",
        "--timeout-s", str(KLT_NETLIST_TIMEOUT_S),
        "--xschem-binary", xschem,
        "--rcfile", str(rcfile),
        "-o", str(produced),
        str(sch),
    ]
    try:
        # klt enforces its own bound; this outer one only guards klt itself.
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True,
            timeout=KLT_NETLIST_TIMEOUT_S + KLT_NETLIST_GRACE_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise XschemExportError(
            f"klt netlist timed out for {sch.stem} after "
            f"{KLT_NETLIST_TIMEOUT_S + KLT_NETLIST_GRACE_S}s"
        ) from exc
    except OSError as exc:
        raise XschemExportError(
            f"could not run `{klt} netlist` for {sch.stem}: {exc}"
        ) from exc
    if proc.returncode != 0 or not produced.is_file():
        raise XschemExportError(
            f"klt netlist failed for {sch.stem} (exit {proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    # klt stamps a provenance comment into every export; drop it so the text
    # stays identical to what xschem itself writes (committed netlists and
    # the LVS pipeline were generated without it).
    body = "".join(
        line
        for line in produced.read_text().splitlines(keepends=True)
        if not line.startswith(KLT_PROVENANCE_PREFIX)
    )
    return normalize(body)
