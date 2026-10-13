#!/usr/bin/env python3
"""Check that README prose citing the T1 verdict agrees with the record (#398).

Stdlib only. Finds the "Today ... tier: X, T1 N of/ N/M items met" sentences in
the given files and compares them with signoff/records/t1-tier-report.json.

Usage: readme_claims.py RECORD README [README ...]
"""

from __future__ import annotations

import json
import re
import sys

# "Today it reads **`tier: null`, T1 1 of 11 items met**" and
# "**Today: `tier: null`, T1 1/11 items met**" -- markup (*, `) is stripped first.
CLAIM_RE = re.compile(
    r"Today\b[^.\n]*?tier:\s*(?P<tier>\w+)\s*,\s*T1\s+"
    r"(?P<met>\d+)\s*(?:of|/)\s*(?P<total>\d+)\s+items\s+met",
    re.IGNORECASE,
)


def find_claims(text: str) -> list[tuple[str, int, int]]:
    """Return (tier, met, total) for every matching sentence in text."""
    plain = re.sub(r"[*`]", "", text)
    plain = re.sub(r"\s+", " ", plain)
    return [(m["tier"], int(m["met"]), int(m["total"]))
            for m in CLAIM_RE.finditer(plain)]


def expected(record: dict) -> tuple[str, int, int]:
    tier = record.get("tier")
    return ("null" if tier is None else str(tier),
            int(record["t1_met_count"]), int(record["t1_item_count"]))


def check(record: dict, texts: dict[str, str]) -> list[str]:
    """Return failure messages; every file must carry at least one claim."""
    tier, met, total = expected(record)
    want = f"Today: `tier: {tier}`, T1 {met} of {total} items met"
    errors = []
    for name, text in texts.items():
        claims = find_claims(text)
        if not claims:
            errors.append(f"{name}: no 'Today ... tier: X, T1 N of M items "
                          f"met' sentence found; expected wording: {want}")
        for got in claims:
            if got != (tier, met, total):
                errors.append(
                    f"{name}: says tier: {got[0]}, T1 {got[1]} of {got[2]} "
                    f"items met but the verdict of record is tier: {tier}, "
                    f"T1 {met} of {total}; expected wording: {want}")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[1]) as fh:
        record = json.load(fh)
    texts = {}
    for path in argv[2:]:
        with open(path) as fh:
            texts[path] = fh.read()
    errors = check(record, texts)
    for e in errors:
        print(f"signoff/check.sh: README claim drift -- {e}", file=sys.stderr)
    if errors:
        return 1
    tier, met, total = expected(record)
    print(f"signoff/check.sh: README tier prose matches the record "
          f"(tier={tier}, T1 {met}/{total})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
