"""Host-independent path rendering for published sim records (issue #365).

Records under ``sim/*/records/`` are public, append-only evidence. Absolute
host paths (home directories, builder worktree locations) carry no
reproduction value -- the open_pdks hash and variant pin the toolchain -- and
needlessly disclose host layout. Everything that writes a path into a record
or a diagnostic string goes through here.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKTREE_MARK = ".loom/worktrees"


def _repo_root_for(path: Path) -> Path | None:
    """The checkout root holding *path*: this repo, or a worktree of it."""
    parts = path.parts
    for i in range(len(parts) - 2):
        if parts[i] == ".loom" and parts[i + 1] == "worktrees":
            return Path(*parts[: i + 3])
    try:
        path.relative_to(REPO_ROOT)
    except ValueError:
        return None
    return REPO_ROOT


def display_path(path: str | os.PathLike, repo_root: Path | None = None) -> str:
    """Repo-relative inside the repo (or any of its worktrees), else
    ``<abs>/basename``. Relative inputs are returned unchanged."""
    p = Path(path)
    if not p.is_absolute():
        return str(p)
    root = repo_root if repo_root is not None else _repo_root_for(p)
    if root is not None:
        try:
            return str(p.relative_to(root))
        except ValueError:
            pass
    return f"<abs>/{p.name}"


def display_pdk_path(path: str | os.PathLike) -> str:
    """PDK location relative to its root: ``$PDK_ROOT/<variant>`` when under
    ``$PDK_ROOT``, ``~/...`` when under the home directory, else
    ``<abs>/<variant>``."""
    p = Path(path)
    if not p.is_absolute():
        return str(p)
    pdk_root = os.environ.get("PDK_ROOT")
    if pdk_root:
        try:
            return "$PDK_ROOT/" + str(p.relative_to(Path(pdk_root).expanduser()))
        except ValueError:
            pass
    return display_home(p)


def display_home(path: str | os.PathLike) -> str:
    """``~/...`` when under the home directory, else ``<abs>/basename``."""
    p = Path(path)
    try:
        return "~/" + str(p.relative_to(Path.home()))
    except (ValueError, RuntimeError):
        return f"<abs>/{p.name}"


def scrub_source(source: str) -> str:
    """Discovery-source labels such as ``search_root:/abs/dir`` -> home form."""
    head, sep, tail = source.partition(":")
    if sep and tail.startswith("/"):
        return f"{head}:{display_home(tail)}"
    return source
