#!/usr/bin/env python3
"""What ``layout/drclvs.py`` and its sibling stage modules share.

Issue #837 split the LVS negative controls (``layout/lvs_controls.py``) and
the ``klt erc`` supply stage (``layout/erc_stage.py``) out of the DRC/LVS
driver. Both siblings raise the driver's ``StageError`` and the ERC stage
runs its subprocesses from the repo root exactly as the driver's own stages
do -- so these names live here, in the one module of the family that every
other one imports and that imports nothing but the standard library.

``layout/drclvs.py`` re-exports all four names: ``drclvs.StageError`` is the
one class every stage raises and ``main()`` catches.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "LAYOUT_DIR",
    "REPO_ROOT",
    "StageError",
    "repo_arg",
]


LAYOUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = LAYOUT_DIR.parent


class StageError(RuntimeError):
    """A stage could not run at all (missing tool, bad invocation)."""


def repo_arg(path: Path) -> Path:
    """A path argument for a repo-root-cwd subprocess: repo-relative when
    the path lives in this repo (so reports record machine-independent,
    repo-scoped paths), absolute when it does not (scratch dirs elsewhere)."""
    try:
        return Path(os.path.relpath(path, REPO_ROOT))
    except ValueError:
        return path
