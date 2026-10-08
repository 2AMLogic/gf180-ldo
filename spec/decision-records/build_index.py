#!/usr/bin/env python3
"""Generate spec/decision-records/README.md, a status index of the records.

    python3 spec/decision-records/build_index.py > spec/decision-records/README.md

Read-only over the records: each ``DR-NNNN-*.md`` is parsed for its title
(first ``# DR-NNNN: ...`` line), its ``- **Status**:`` bullet (the first line
plus its indented continuation lines), and any ``superseded by DR-NNNN``
reference in that bullet. The normalized status is one of ratified, proposed,
held, superseded. CI regenerates this file and diffs it against the committed
copy (same pattern as sim/CHARACTERIZATION.md), so it cannot rot.

A record whose Status cannot be classified makes the script exit non-zero, so
new records must follow TEMPLATE.md's ``proposed | ratified | superseded by``
shape. Ratified records are immutable, so irregular existing ones are
classified in STATUS_OVERRIDES below rather than edited.

The same file also carries a "design citations of unratified records" table
(issue #387): ``design/*.sch`` is scanned for ``DR-NNNN`` and joined with the
parsed statuses. Citing a proposed/held record is report-only; citing a record
with no file, or a superseded record with no ``superseded by`` pointer, exits
non-zero.

Stdlib only; no PDK, no network. Output is deterministic.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RECORDS_DIR = Path(__file__).resolve().parent
DESIGN_DIR = RECORDS_DIR.parents[1] / "design"

# DR number -> normalized status, for records whose Status line cannot be
# classified from its first word alone.
STATUS_OVERRIDES = {
    # "proposed -- HELD": ratification deliberately deferred by the operator.
    7: "held",
}

STATUSES = ("ratified", "proposed", "held", "superseded")
ORDER_NOTE = {
    "ratified": "in force",
    "proposed": "not yet ratified",
    "held": "ratification deferred",
    "superseded": "replaced",
}


class ClassifyError(ValueError):
    pass


def parse_title(text: str, number: int) -> str:
    m = re.search(r"^# DR-%04d:\s*(.+?)\s*$" % number, text, re.M)
    if not m:
        raise ClassifyError("DR-%04d: no '# DR-%04d: <title>' header" % (number, number))
    return m.group(1)


def status_block(text: str) -> str | None:
    """Return the Status bullet's text (first line + continuation lines)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^- \*\*Status\*\*:\s*(.*)$", line)
        if not m:
            continue
        parts = [m.group(1)]
        for nxt in lines[i + 1:]:
            if not nxt.strip() or re.match(r"^- ", nxt):
                break
            parts.append(nxt.strip())
        return " ".join(parts)
    return None


def classify(number: int, block: str | None) -> tuple[str, str]:
    """Return (normalized status, superseded-by text or '')."""
    if block is None:
        raise ClassifyError("DR-%04d: no '- **Status**:' line" % number)
    by = re.search(r"superseded by\s+`?(DR-\d{4})", block, re.I)
    superseded_by = by.group(1) if by else ""
    if number in STATUS_OVERRIDES:
        return STATUS_OVERRIDES[number], superseded_by
    first = re.match(r"[\s*_`]*([A-Za-z]+)", block)
    word = first.group(1).lower() if first else ""
    if word in ("ratified", "proposed", "superseded"):
        if word == "superseded" and not superseded_by:
            raise ClassifyError(
                "DR-%04d: status 'superseded' without 'superseded by DR-NNNN'" % number
            )
        return word, superseded_by
    raise ClassifyError(
        "DR-%04d: cannot classify Status %r; use TEMPLATE.md's "
        "'proposed | ratified | superseded by DR-NNNN' or add an override"
        % (number, block[:60])
    )


def parse_record(path: Path) -> dict:
    m = re.match(r"DR-(\d{4})-", path.name)
    if not m:
        raise ClassifyError("%s: filename is not DR-NNNN-<slug>.md" % path.name)
    number = int(m.group(1))
    text = path.read_text(encoding="utf-8")
    status, by = classify(number, status_block(text))
    return {
        "number": number,
        "title": parse_title(text, number),
        "status": status,
        "superseded_by": by,
        "file": path.name,
    }


def scan_citations(design_dir: Path) -> dict[int, dict[str, int]]:
    """Map DR number -> {schematic filename: citation count}."""
    found: dict[int, dict[str, int]] = {}
    for p in sorted(design_dir.glob("*.sch")):
        for m in re.finditer(r"DR-(\d{4})", p.read_text(encoding="utf-8")):
            per = found.setdefault(int(m.group(1)), {})
            per[p.name] = per.get(p.name, 0) + 1
    return found


def citation_rows(records: list[dict], found: dict[int, dict[str, int]]) -> list[tuple]:
    """Join citations with statuses; raise on dangling/unpointed-superseded."""
    by_num = {r["number"]: r for r in records}
    rows = []
    for num, files in sorted(found.items()):
        rec = by_num.get(num)
        where = ", ".join(sorted(files))
        if rec is None:
            raise ClassifyError(
                "design cites DR-%04d (%s) but no such record file exists" % (num, where)
            )
        if rec["status"] == "superseded" and not rec["superseded_by"]:
            raise ClassifyError(
                "design cites superseded DR-%04d (%s) with no 'superseded by' pointer"
                % (num, where)
            )
        if rec["status"] == "ratified":
            continue
        for fname, n in sorted(files.items()):
            rows.append((num, rec["status"], fname, n, sum(files.values())))
    # Ranked worklist: most-cited record first, then record, then file.
    rows.sort(key=lambda r: (-r[4], r[0], r[2]))
    return rows


def render_citations(rows: list[tuple]) -> list[str]:
    out = [
        "",
        "## Design citations of unratified records",
        "",
        "`design/*.sch` cites these records that are not ratified (report-only; "
        "ranked by total citations). CI fails on a cited record with no file, "
        "or a cited superseded record with no `superseded by` pointer.",
        "",
    ]
    if not rows:
        return out + ["None.", ""]
    out += ["| DR | Status | Citing file | Count |", "|---|---|---|---|"]
    for num, status, fname, n, _ in rows:
        out.append("| DR-%04d | %s | design/%s | %d |" % (num, status, fname, n))
    out.append("")
    return out


def render(records: list[dict], cite_rows: list[tuple] | None = None) -> str:
    counts = {s: sum(1 for r in records if r["status"] == s) for s in STATUSES}
    out = [
        "# Decision records: status index",
        "",
        "<!-- GENERATED by spec/decision-records/build_index.py -- do not edit. -->",
        "<!-- Regenerate: python3 spec/decision-records/build_index.py > spec/decision-records/README.md -->",
        "",
        "Only **ratified** records are in force. Everything else is a proposal "
        "or a held/negative-result write-up awaiting the operator. Status is "
        "read from each record's `Status` line (see `TEMPLATE.md`); CI fails "
        "if this file is stale or a record's status cannot be classified.",
        "",
        "%d records: " % len(records)
        + ", ".join("%d %s" % (counts[s], s) for s in STATUSES)
        + ".",
        "",
        "| DR | Title | Status | Superseded by |",
        "|---|---|---|---|",
    ]
    for r in records:
        title = r["title"].replace("|", "\\|")
        out.append(
            "| [DR-%04d](%s) | %s | %s | %s |"
            % (r["number"], r["file"], title, r["status"], r["superseded_by"] or "-")
        )
    if cite_rows is not None:
        out += render_citations(cite_rows)
    else:
        out.append("")
    return "\n".join(out)


def build(directory: Path = RECORDS_DIR, design_dir: Path | None = None) -> str:
    if design_dir is None and directory == RECORDS_DIR:
        design_dir = DESIGN_DIR
    paths = sorted(directory.glob("DR-[0-9][0-9][0-9][0-9]-*.md"))
    records = [parse_record(p) for p in paths]
    rows = None
    if design_dir is not None:
        rows = citation_rows(records, scan_citations(design_dir))
    return render(records, rows)


def main() -> int:
    try:
        sys.stdout.write(build())
    except ClassifyError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
