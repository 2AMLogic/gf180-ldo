#!/usr/bin/env python3
"""Check that README prose citing the T1 verdict agrees with the record (#398).

Stdlib only. Two independent checks:

- Finds the "Today ... tier: X, T1 N of/ N/M items met" sentences in the
  given files and compares them with signoff/records/t1-tier-report.json.
- Finds per-item markdown table rows ("| 5 | `unmet` / `<reason>` | ...") and
  compares each status/reason cell with the record. A file with no table rows
  passes this check (#617).

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

# A per-item table row: "| 5 | `unmet` / `partial_coverage` | ... |". Only the
# leading item id and the status cell are captured; the Reading column is
# hand-written analysis the record cannot reproduce, so it is never parsed.
TABLE_ROW_RE = re.compile(r"^\s*\|\s*(\d+)\s*\|\s*([^|]*)\|")

# "`met`" or "`unmet` / `partial_coverage`" -- markup is stripped first, so the
# cell arrives as plain "met" or "unmet / <reason>".
TABLE_STATUS_RE = re.compile(r"^(?P<status>met|unmet)(?:\s*/\s*(?P<reason>\S+))?$")


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


def _fmt(status: str | None, reason: str | None) -> str:
    if status is None:
        return "no verdict"
    if reason is None:
        return "met"
    return f"unmet / {reason}"


def table_rows(text: str) -> list[tuple[int, str]]:
    """Return (item id, plain status cell) for every per-item table row."""
    rows = []
    for line in text.splitlines():
        m = TABLE_ROW_RE.match(line)
        if not m:
            continue
        cell = re.sub(r"[*`]", "", m[2])
        cell = re.sub(r"\s+", " ", cell).strip()
        rows.append((int(m[1]), cell))
    return rows


def check_tables(record: dict, texts: dict[str, str]) -> list[str]:
    """Check per-item table rows against the record (#617).

    A file with no table rows passes (the top-level README.md has none). A
    file with at least one row must carry exactly one row per item id in the
    record, none outside it, and each cell's `met` or `unmet / <reason>` must
    equal the record's status and reason verbatim.
    """
    by_id = {i["id"]: i for i in record["items"] if i.get("id") is not None}
    errors = []
    for name, text in texts.items():
        rows = table_rows(text)
        if not rows:
            continue
        seen: dict[int, str] = {}
        for item_id, cell in rows:
            if item_id in seen:
                errors.append(f"{name}: item {item_id} has more than one "
                              f"table row; keep exactly one")
                continue
            seen[item_id] = cell
        for item_id in sorted(set(seen) - set(by_id)):
            errors.append(f"{name}: table has a row for item {item_id} "
                          f"but the record has no such item")
        missing = sorted(set(by_id) - set(seen))
        if missing:
            ids = ", ".join(str(i) for i in missing)
            errors.append(f"{name}: the table has no row for item(s) {ids}; "
                          f"every item in the record needs exactly one row")
        for item_id, cell in seen.items():
            if item_id not in by_id:
                continue
            item = by_id[item_id]
            want = (item.get("status"), item.get("reason"))
            m = TABLE_STATUS_RE.match(cell)
            if not m:
                errors.append(
                    f"{name}: item {item_id} table status cell '{cell}' is "
                    f"neither 'met' nor 'unmet / <reason>'; the record says "
                    f"{_fmt(*want)}")
                continue
            got = (m["status"], m["reason"])
            if got != want:
                errors.append(
                    f"{name}: item {item_id} table row says "
                    f"'{_fmt(*got)}' but the record says {_fmt(*want)}")
    return errors


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
    errors = check(record, texts) + check_tables(record, texts)
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
