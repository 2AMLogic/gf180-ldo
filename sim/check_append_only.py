#!/usr/bin/env python3
"""PR-level guard for the append-only evidence rule (issue #371).

sim/README.md ("Append-only rule") says committed evidence records are never
edited, deleted, or renamed. The writer enforces that in-process; this script
enforces it on a pull request's diff. Only *Added* paths are allowed under:

    sim/*/records/    sim/*/corners/    sim/*/netlist-snapshots/
    layout/records/

(signoff/records/ is deliberately not covered: signoff/check.sh regenerates
and re-commits the tier report by design.)

Usage (CI):
    python3 sim/check_append_only.py --base origin/main

which runs `git diff --name-status -M origin/main...HEAD` and classifies it.

Exceptions: sim/append-only-allowlist.txt, one per line,
    <path>  DR-NNNN   # why
The DR must exist under spec/decision-records/. The path is matched exactly
(for a rename, the old path). Stdlib only; no PDK or network.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROTECTED = ("sim/*/records/*", "sim/*/corners/*", "sim/*/netlist-snapshots/*",
             "layout/records/*")
DEFAULT_ALLOWLIST = REPO / "sim" / "append-only-allowlist.txt"
DR_RE = re.compile(r"^DR-\d{4}$")


def is_protected(path: str) -> bool:
    # fnmatch's '*' crosses '/', which is what we want for nested files.
    return any(fnmatch.fnmatchcase(path, g) for g in PROTECTED)


def parse_allowlist(text: str) -> dict[str, str]:
    """Return {path: DR-NNNN}. Raises ValueError on a malformed line."""
    out: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or not DR_RE.match(parts[1]):
            raise ValueError(
                f"allowlist line {n}: expected '<path> DR-NNNN', got {raw!r}")
        out[parts[0]] = parts[1]
    return out


def classify(name_status: str, allow: dict[str, str] | None = None
             ) -> tuple[list[str], list[str]]:
    """Classify `git diff --name-status` output.

    Returns (violations, allowed) as human-readable strings. Any status other
    than A (M, D, R, C-source, T, ...) touching a protected path is a
    violation unless the affected pre-existing path is allowlisted.
    """
    allow = allow or {}
    violations: list[str] = []
    allowed: list[str] = []
    for raw in name_status.splitlines():
        if not raw.strip():
            continue
        fields = raw.split("\t")
        status = fields[0].strip()
        paths = fields[1:]
        code = status[:1]
        if code == "A":
            continue
        if code == "C":
            # Copy: the source is untouched; only the (new) destination matters.
            continue
        # Existing paths affected: M/D/T -> the path; R -> the old path
        # (the new path is an addition, but the old one vanished).
        affected = paths[:1] if code == "R" else paths
        for p in affected:
            if not is_protected(p):
                continue  # (a rename *into* a protected dir is just an add)
            desc = f"{status}\t" + "\t".join(paths)
            if p in allow:
                allowed.append(f"{desc}  (allowed by {allow[p]})")
            else:
                violations.append(desc)
    return violations, allowed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="origin/main",
                    help="base ref; diffs <base>...HEAD (default origin/main)")
    ap.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    ap.add_argument("--from-file", type=Path,
                    help="read --name-status text from a file instead of git")
    args = ap.parse_args(argv)

    allow: dict[str, str] = {}
    if args.allowlist.exists():
        try:
            allow = parse_allowlist(args.allowlist.read_text())
        except ValueError as e:
            print(f"::error::{e}")
            return 2
        for p, dr in allow.items():
            if not list((REPO / "spec" / "decision-records").glob(f"{dr}-*.md")):
                print(f"::error::allowlist entry {p} cites {dr}, which does "
                      "not exist in spec/decision-records/")
                return 2

    if args.from_file:
        text = args.from_file.read_text()
    else:
        r = subprocess.run(
            ["git", "diff", "--name-status", "-M", f"{args.base}...HEAD"],
            cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"::error::git diff failed: {r.stderr.strip()}")
            return 2
        text = r.stdout

    violations, allowed = classify(text, allow)
    for a in allowed:
        print(f"allowed exception: {a}")
    if violations:
        for v in violations:
            print(f"::error::append-only evidence modified: {v}")
        print("Committed records/corner logs are append-only (sim/README.md, "
              "'Append-only rule'). Mint a new record instead; a justified "
              "exception needs a decision record and an entry in "
              "sim/append-only-allowlist.txt.")
        return 1
    print("append-only check: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
