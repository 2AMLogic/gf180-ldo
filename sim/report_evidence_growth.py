#!/usr/bin/env python3
"""Non-blocking report of git-tracked evidence growth under sim/ (issue #388).

sim/ is append-only (sim/check_append_only.py, #371), so it only grows. This
reporter writes a Markdown table of files added and bytes added per
`sim/<slug>` for a pull request, so growth is visible before it hurts clones.
It is reporting only: it never fails. No ceiling, threshold or override exists
(deferred per the operator ruling on #388).

Usage (CI):
    python3 sim/report_evidence_growth.py --base origin/main

Output goes to $GITHUB_STEP_SUMMARY (stdout when unset).

Accounting:
  * Scope: only paths under `sim/`. The slug is the second path component;
    files directly under `sim/` go to a `(sim root)` row.
  * Source: `git diff --raw -M --no-abbrev <base>...HEAD`. Bytes are the size
    of the HEAD blob (`git cat-file --batch-check`), so binary files count the
    same as text.
  * A (added) and C (copied): +1 file, +blob bytes.
  * R (renamed): the destination counts as a new file and new bytes
    (conservative; renaming protected evidence is rejected by
    check_append_only.py anyway).
  * M / T (modified, type change): +blob bytes, +0 files.
  * D (deleted): nothing.
  * Sizes print as KiB/MiB with the exact byte count in its own column.

Always exits 0. Any git/metadata failure prints a `::warning::` and the
summary line "growth report unavailable: <reason>"; `::error::` is never used.
Stdlib only; no PDK or network.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
ROOT_ROW = "(sim root)"


def slug_of(path: str) -> str | None:
    """Return the report row for `path`, or None if it is outside sim/."""
    parts = path.split("/")
    if parts[0] != "sim" or len(parts) < 2:
        return None
    return ROOT_ROW if len(parts) == 2 else parts[1]


def parse_raw(text: str) -> list[tuple[str, str, str]]:
    """Parse `git diff --raw` lines into (status code, path, new blob sha).

    For R/C the path is the destination. Lines that are not raw records are
    skipped.
    """
    out: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        if not line.startswith(":"):
            continue
        meta, _, paths = line.partition("\t")
        fields = meta[1:].split()
        if len(fields) < 5 or not paths:
            continue
        code = fields[4][:1]
        path = paths.split("\t")[-1]
        out.append((code, path, fields[3]))
    return out


def summarize(raw_diff: str, size_of: Callable[[str], int]
              ) -> dict[str, tuple[int, int]]:
    """Aggregate {row: (files_added, bytes_added)} from raw diff text."""
    rows: dict[str, list[int]] = {}
    for code, path, sha in parse_raw(raw_diff):
        row = slug_of(path)
        if row is None or code == "D":
            continue
        if code not in ("A", "C", "R", "M", "T"):
            continue
        entry = rows.setdefault(row, [0, 0])
        if code in ("A", "C", "R"):
            entry[0] += 1
        entry[1] += size_of(sha)
    return {k: (v[0], v[1]) for k, v in rows.items()}


def human(n: int) -> str:
    if n >= 1 << 20:
        return f"{n / (1 << 20):.2f} MiB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.1f} KiB"
    return f"{n} B"


def render(rows: dict[str, tuple[int, int]]) -> str:
    lines = ["### Evidence growth under `sim/` (reporting only)", ""]
    if not rows:
        lines.append("No files added or changed under `sim/`.")
        return "\n".join(lines) + "\n"
    lines += ["| Slug | Files added | Size | Bytes |", "|---|---:|---:|---:|"]
    for slug in sorted(rows):
        files, size = rows[slug]
        lines.append(f"| `{slug}` | {files} | {human(size)} | {size} |")
    tf = sum(f for f, _ in rows.values())
    tb = sum(b for _, b in rows.values())
    lines.append(f"| **Total** | {tf} | {human(tb)} | {tb} |")
    return "\n".join(lines) + "\n"


def _git(args: list[str], stdin: str | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=REPO, input=stdin,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"git {args[0]} failed")
    return r.stdout


def git_sizes(shas: list[str]) -> dict[str, int]:
    """Map blob sha -> size via one `git cat-file --batch-check` call."""
    out = _git(["cat-file", "--batch-check"], "".join(f"{s}\n" for s in shas))
    sizes: dict[str, int] = {}
    for line in out.splitlines():
        f = line.split()
        if len(f) == 3 and f[1] == "blob":
            sizes[f[0]] = int(f[2])
    return sizes


def emit(text: str) -> None:
    dest = os.environ.get("GITHUB_STEP_SUMMARY")
    if dest:
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="origin/main",
                    help="base ref; diffs <base>...HEAD (default origin/main)")
    ap.add_argument("--from-file", type=Path,
                    help="read --raw diff text from a file instead of git "
                         "(sizes still come from git)")
    args = ap.parse_args(argv)
    try:
        if args.from_file:
            text = args.from_file.read_text()
        else:
            text = _git(["diff", "--raw", "-M", "--no-abbrev",
                         f"{args.base}...HEAD"])
        shas = sorted({sha for code, path, sha in parse_raw(text)
                       if code != "D" and slug_of(path) is not None})
        sizes = git_sizes(shas) if shas else {}
        rows = summarize(text, lambda s: sizes.get(s, 0))
        emit(render(rows))
    except Exception as e:  # reporting must never fail the job
        reason = " ".join(str(e).split()) or type(e).__name__
        print(f"::warning::growth report unavailable: {reason}")
        emit(f"growth report unavailable: {reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
