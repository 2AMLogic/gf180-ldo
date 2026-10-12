#!/usr/bin/env python3
"""Fail if records added/modified in a PR embed absolute host paths (#365, #413).

Usage: check_record_host_paths.py --base <sha>

Only files added or modified between <base>...HEAD are inspected, so
historical append-only evidence is never rewritten. Stdlib + git only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# Single source of truth for the CI gate and its regression test.
PATHSPECS = (
    "sim/*/records/*",
    "signoff/records/*",
    "layout/records/*",
)
HOST_PATH = re.compile(r"/home/[a-z]|/Users/[a-z]")


def changed_files(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD",
         "--", *PATHSPECS],
        check=True, capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if line]


def offenders(files: list[str]) -> list[str]:
    bad = []
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            hits = [(n, line.rstrip("\n")) for n, line in enumerate(fh, 1)
                    if HOST_PATH.search(line)]
        for n, line in hits:
            print(f"{f}:{n}:{line}")
        if hits:
            bad.append(f)
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    args = ap.parse_args(argv)
    bad = offenders(changed_files(args.base))
    if bad:
        print("::error::records added or modified in this PR embed absolute "
              "host paths (/home/<user> or /Users/<user>): " + " ".join(bad)
              + " -- render paths repo-relative or via sim/harness/paths.py "
              "(issue #365).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
