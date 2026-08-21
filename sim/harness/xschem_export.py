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
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# xschem exits 0 even when its own ERC/connectivity checks fail (they are
# printed, not turned into a nonzero exit code), so grep stdout+stderr for
# the failure classes it emits during netlisting: undriven/floating nodes,
# shorted nodes/pins, and missing symbols (a silently-unresolved reference
# nets everything under an auto-generated name instead of erroring -- see
# gf180-pll/design/xschemrc's warning about this failure mode).
ERC_FAILURE_RE = re.compile(
    r"(undriven node|open net|shorted output node|instance pin shorted|"
    r"symbol not found|IS MISSING)",
    re.IGNORECASE,
)


class XschemExportError(RuntimeError):
    """xschem could not be run, or its own ERC/connectivity checks failed."""


def normalize(text: str) -> str:
    """Make xschem output machine-independent (and therefore diffable)."""
    text = text.replace(str(REPO_ROOT) + os.sep, "")
    # Trailing whitespace is not load bearing and varies with symbol text.
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.rstrip("\n") + "\n"


def run_xschem_netlist(
    sch: Path, outdir: Path, env: dict[str, str], rcfile: Path
) -> str:
    """Run xschem headless (batch, ERC on) on ``sch`` and return the
    normalized text of the netlist it writes to ``outdir/<sch.stem>.spice``.

    Raises :class:`XschemExportError` if xschem exits nonzero, produces no
    output file, or its own ERC/connectivity checks report a problem.
    """
    cmd = [
        "xschem",
        "-x",  # no X11: batch
        "-q",  # quit when done
        "-r",  # no tclreadline (stdin/stdout may be redirected)
        "--rcfile", str(rcfile),
        "-o", str(outdir),
        str(sch),
        "--command", "xschem netlist -erc",
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    produced = outdir / f"{sch.stem}.spice"
    noisy = proc.stdout + proc.stderr
    erc_problem = ERC_FAILURE_RE.search(noisy)
    if proc.returncode != 0 or not produced.is_file() or erc_problem:
        raise XschemExportError(
            f"xschem failed for {sch.stem} (exit {proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return normalize(produced.read_text())
