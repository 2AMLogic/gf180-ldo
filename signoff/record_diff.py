#!/usr/bin/env python3
"""Diff a fresh `klt signoff --manifest` run against the committed verdict of
record and diagnose the difference (issue #623).

Stdlib only, extracted from check.sh's step 3 so the diagnosis is unit
testable (mirrors readme_claims.py, issue #398). Exit 0 with the "verdict of
record is current" line when the two documents are equal; exit 1 with a
diagnostic on stderr otherwise. A difference whose only volatile part is
item-level `stale_evidence` refusals -- a file an attested envelope covers
changed after the envelope was minted -- is reported as a re-attest case
naming every stale member and quoting the concrete re-attest command;
anything else also gets the regenerate guidance, unchanged from the inline
check this module replaces.

Usage: record_diff.py FRESH RECORD
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SIGNOFF_DIR = Path(__file__).resolve().parent

# t1_met_count moves mechanically with per-item statuses, so it is not an
# independent difference: a met -> unmet transition changes it even when
# nothing else did.
_DERIVED_COUNT_KEYS = ("t1_met_count",)


def stale_members(item: dict) -> list[dict]:
    """The artifact_binding members of item that klt signoff marked stale."""
    if item.get("reason") != "stale_evidence":
        return []
    binding = (item.get("detail") or {}).get("artifact_binding") or {}
    return [m for m in binding.get("members") or []
            if isinstance(m, dict) and m.get("status") == "stale"]


def reattest_items(fresh: dict) -> dict[int, list[dict]]:
    """Map item id -> its stale members, keyed on items[].id, never the index."""
    out: dict[int, list[dict]] = {}
    for item in fresh.get("items") or []:
        members = stale_members(item)
        if members and item.get("id") is not None:
            out[int(item["id"])] = members
    return out


def residual_differs(fresh: dict, committed: dict, ids: set[int]) -> bool:
    """True if the documents differ outside the given re-attest items.

    The re-attest items and the count derived from item statuses are dropped
    from both sides before comparing; anything left over -- another item, a
    count, the checklist itself -- is a difference re-attesting cannot fix.
    """

    def scrub(doc: dict) -> dict:
        out = {k: v for k, v in doc.items() if k not in _DERIVED_COUNT_KEYS}
        out["items"] = [it for it in doc.get("items") or []
                        if it.get("id") not in ids]
        return out

    return scrub(fresh) != scrub(committed)


def reattest_command(item_id: int) -> str:
    """The re-attest command for item_id, against check.sh's own KLT pin."""
    pin = re.search(r'^KLT_VERSION="([^"]+)"',
                    (_SIGNOFF_DIR / "check.sh").read_text(), re.MULTILINE)
    if not pin:
        raise RuntimeError("signoff/check.sh: no KLT_VERSION pin found")
    return (f'uvx --from "klayout-tools=={pin.group(1)}" klt signoff \\\n'
            f'      --attest {item_id} '
            f'--inventory signoff/inventory-item{item_id}.json \\\n'
            f'      -o signoff/evidence/item{item_id}.generic.json')


def reattest_message(record: str, items: dict[int, list[dict]]) -> str:
    lines = [
        "signoff/check.sh: the committed T1 verdict of record is stale.",
        "  A fresh 'klt signoff --manifest' run no longer matches",
        f"  {record} because attested evidence went stale -- a file an",
        "  attested envelope covers changed after the envelope was minted:",
    ]
    for item_id in sorted(items):
        for member in items[item_id]:
            lines.append(f"    - item {item_id}: {member.get('path')}")
    lines.append("  Re-attest each affected item:")
    for item_id in sorted(items):
        lines.append(f"    {reattest_command(item_id)}")
    lines += [
        "  then re-run 'bash signoff/check.sh' and follow whatever it",
        "  reports. signoff/README.md's re-attest recipe has the follow-up",
        "  steps for the case where the inventory itself changed.",
    ]
    return "\n".join(lines)


def regenerate_message(record: str) -> str:
    return (
        "signoff/check.sh: the committed T1 verdict of record is stale.\n"
        "  A fresh 'klt signoff --manifest' run no longer matches\n"
        f"  {record}. That is not a tool bug: either this block's\n"
        "  evidence moved, or the checklist did. Regenerate with\n"
        "    bash signoff/check.sh --write\n"
        "  commit the result, and update signoff/README.md's reading of any\n"
        "  item whose status or reason changed."
    )


def regenerate_tail() -> str:
    return (
        "  The run also differs outside those items. That is not a tool\n"
        "  bug: either this block's evidence moved, or the checklist did.\n"
        "  Regenerate with\n"
        "    bash signoff/check.sh --write\n"
        "  commit the result, and update signoff/README.md's reading of any\n"
        "  item whose status or reason changed."
    )


def stale_diagnosis(fresh: dict, committed: dict) -> tuple[dict[int, list[dict]], bool]:
    """Classify a known difference: (re-attest items, residual differs)."""
    items = reattest_items(fresh)
    return items, residual_differs(fresh, committed, set(items))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[1]) as fh:
        fresh = json.load(fh)
    try:
        with open(argv[2]) as fh:
            committed = json.load(fh)
    except FileNotFoundError:
        print(f"signoff/check.sh: {argv[2]} is missing -- regenerate it with "
              f"'bash signoff/check.sh --write' and commit it", file=sys.stderr)
        return 1

    if fresh != committed:
        items, residual = stale_diagnosis(fresh, committed)
        if items and residual:
            print(reattest_message(argv[2], items) + "\n\n"
                  + regenerate_tail(), file=sys.stderr)
        elif items:
            print(reattest_message(argv[2], items), file=sys.stderr)
        else:
            print(regenerate_message(argv[2]), file=sys.stderr)
        return 1

    met = fresh.get("t1_met_count")
    total = fresh.get("t1_item_count")
    print(f"signoff/check.sh: verdict of record is current -- T1 {met}/{total} "
          f"items met, tier={fresh.get('tier')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
