#!/usr/bin/env python3
"""Fail if records added/modified in a PR still carry an unwritten Reading section (#606).

Usage: check_record_reading.py --base <sha>

`sim/harness/klt_record.py` mints every record with a literal
``(to be written)`` under a ``## Reading`` heading, for the minting agent to
replace once it has read the grid. Nothing used to check that it did, and
records are append-only (`sim/check_append_only.py`), so a placeholder that
reaches `main` can only be corrected via an `sim/append-only-allowlist.txt`
entry plus a decision record -- a one-line fix before merge, a spec exception
after.

Two rules, deliberately asymmetric:

  - a known minting placeholder is an error wherever it appears;
  - a ``## Reading`` heading whose body is empty is an error, but a record
    with **no** ``## Reading`` heading at all is fine.

The second asymmetry is the design decision, not an oversight: the heading is
a convention adopted 2026-10-15, carried by only 18 of 190 committed sim
records. Requiring it would reject the other 172, including complete
hand-written records such as
`sim/soft-start/records/20261105-ss-351-peak-pvt.md`, which uses
``## Verdict`` / ``## Coverage`` / ``## Results`` instead.

Only files added or modified between <base>...HEAD are inspected, so
historical append-only evidence is never rewritten. CI passes
origin/<github.base_ref> or, on a merge-queue run, the event's
github.event.merge_group.base_sha (issue #743); an empty or unavailable
base fails explicitly -- an empty base would otherwise diff nothing and
silently pass. Stdlib + git only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Which files are evidence records, and the git query that selects the
# added/modified ones, are shared with sim/check_record_host_paths.py via
# sim/record_selection.py (issue #854): one definition, so the two gates
# can never disagree about which files they inspect. Until #854 this file
# carried its own copy of the pathspecs with a comment asking maintainers
# to keep it identical to the host-path check's -- an agreement with no
# mechanism behind it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from record_selection import changed_files  # noqa: E402  -- needs the sys.path insert above

# Literal placeholders a record writer emits for a human to replace before the
# record is committed. Shared with sim/tests/test_check_record_reading.py --
# add a writer's string here when you add the writer.
#   "(to be written)"  -- sim/harness/klt_record.py:219, the only emitter on
#                         main as of 2026-11-14 (report.py, run_corners.py and
#                         run_store_evidence.py emit no placeholder).
PLACEHOLDERS = ("(to be written)",)

# `## Reading` exactly, at any heading level. Group 2 captures prose written on
# the heading line itself ("## Reading: nominal is 1.8 V"), which counts as a
# written section. `\b` keeps "## Readings" from matching.
READING_HEADING = re.compile(r"^(#{1,6})\s+Reading\b\s*(\S.*)?$")
ANY_HEADING = re.compile(r"^#{1,6}\s")
# Fenced code blocks: a `## Reading` inside one is sample text, not a heading,
# and a fence must not end the section it sits in.
FENCE = re.compile(r"^\s*(?:```|~~~)")


def read_lines(path: str) -> list[str]:
    # errors="replace" matches sim/check_record_host_paths.py: a stray non-UTF-8
    # byte in a record must not crash the gate.
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [line.rstrip("\n") for line in fh]


def empty_reading_headings(lines: list[str]) -> list[int]:
    """1-based line numbers of `## Reading` headings with an empty body."""
    empty: list[int] = []
    in_fence = False
    i, n = 0, len(lines)
    while i < n:
        if FENCE.match(lines[i]):
            in_fence = not in_fence
            i += 1
            continue
        heading = None if in_fence else READING_HEADING.match(lines[i])
        if heading is None:
            i += 1
            continue
        if heading.group(2):  # prose on the heading line itself
            i += 1
            continue
        body_fence, has_prose, j = False, False, i + 1
        while j < n:
            if FENCE.match(lines[j]):
                body_fence, has_prose = not body_fence, True
            elif not body_fence and ANY_HEADING.match(lines[j]):
                break
            elif lines[j].strip():
                has_prose = True
            j += 1
        if not has_prose:
            empty.append(i + 1)
        i = j
    return empty


def offenders(files: list[str]) -> list[str]:
    bad = []
    for f in files:
        lines = read_lines(f)
        hits = [(n, f"minting placeholder {ph!r} was never replaced: "
                    f"{line.strip()}")
                for n, line in enumerate(lines, 1)
                for ph in PLACEHOLDERS if ph in line]
        hits += [(n, "'## Reading' heading has an empty body")
                 for n in empty_reading_headings(lines)]
        for n, why in sorted(hits):
            print(f"{f}:{n}: {why}")
        if hits:
            bad.append(f)
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    args = ap.parse_args(argv)
    if not args.base.strip():
        print("::error::--base is empty (a merge_group run whose "
              "github.event.merge_group.base_sha is empty?): refusing to "
              "claim the Reading-section check was run")
        return 2
    try:
        files = changed_files(args.base)
    except subprocess.CalledProcessError as exc:
        print(f"::error::git diff failed against base {args.base!r} "
              f"(unavailable in this checkout?): {(exc.stderr or '').strip()}")
        return 2
    bad = offenders(files)
    if bad:
        print("::error::records added or modified in this diff have an unwritten "
              "Reading section: " + " ".join(bad)
              + " -- write what the grid actually shows over the "
                "'(to be written)' placeholder minted by "
                "sim/harness/klt_record.py, or drop the '## Reading' heading if "
                "this record uses a different structure (records are "
                "append-only, so fixing this after merge needs an "
                "sim/append-only-allowlist.txt entry plus a decision record -- "
                "issue #606).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
