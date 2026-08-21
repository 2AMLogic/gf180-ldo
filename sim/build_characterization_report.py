#!/usr/bin/env python3
"""Regenerate sim/CHARACTERIZATION.md, the aggregated characterization report.

    python3 sim/build_characterization_report.py > sim/CHARACTERIZATION.md

For every ratified row of README.md's "Target specification" table, this
script finds the most recent *substantive* record under the row's mapped
``sim/<slug>/records/`` director(y/ies), extracts that record's own stated
pass/fail verdict, and determines whether the record is fresh or stale
against the current DUT netlist(s) under ``design/netlist/``.

This is issue #104 (T1/bronze checklist item 8, closed by #95's re-read):
evidence is real but was scattered across 17 independent ``sim/<slug>/
records/`` directories with no single rollup tying each ratified row to its
current verdict. This script is that rollup, and it is regenerated from the
committed evidence on every run rather than hand-maintained -- it mirrors
``sim/mc-output-accuracy/summarize.py``'s pattern of reading committed raw
evidence rather than re-stating numbers by hand.

Nothing here re-simulates anything and nothing here is evidence in its own
right: the evidence is the append-only records under ``records/`` and the
frozen netlist snapshots under ``netlist-snapshots/``. This script only
reads those, plus the current ``design/netlist/*.spice`` files and README's
own spec table, and prints Markdown. Re-running it on an unchanged tree
reproduces byte-identical output (no wall-clock timestamps are emitted).

## How a "verdict" is extracted

Every record's own prose states its result as a bolded ``**Overall...**``
span (e.g. ``**Overall: PASS**``, or ``**Overall (thermal, ratified <= 290 mW
into a short): FAIL**`` for records that carry more than one sub-claim). This
script extracts every such span from the chosen record, optionally filtered
by a keyword when one record's latest substantive result covers more than
one ratified row (e.g. ``current-limit`` covers both the "Current limit" row
and the "Thermal" row). Records that use the older ``## Result ...`` heading
style instead of a bolded ``**Overall**`` span (a handful of the earliest
hand-written testbenches) are matched via that heading as a fallback. A
record with neither is reported as UNKNOWN rather than silently guessed.

## How "fresh" vs "stale" is determined

Per record, "fresh" means the frozen netlist snapshot committed alongside it
(``sim/<slug>/netlist-snapshots/<record-id>.spice``) still contains the
*current* ``design/netlist/ldo_core.spice`` or ``design/netlist/
error_amp.spice`` content verbatim, byte for byte, as a substring -- the
same test #95's manual freshness audit applied by hand. This works uniformly
across every experiment regardless of whether its testbench used the newer
JSON-manifest harness (whose snapshots carry a provenance header stating the
DUT path and its own sha256) or an older hand-written deck (whose snapshot
is nothing but a verbatim copy of the included design netlist) -- the
substring test does not care which. A record whose snapshot contains
neither current file's content verbatim is STALE; a record with no snapshot
file at all is UNKNOWN.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SIM_DIR = REPO_ROOT / "sim"
README = REPO_ROOT / "README.md"

# The only two design netlists any experiment in sim/ instantiates as its
# "device under test" (as opposed to a supporting cell it merely includes).
# Keyed by the label used in the report.
DUT_CANDIDATES = {
    "ldo_core": REPO_ROOT / "design" / "netlist" / "ldo_core.spice",
    "error_amp": REPO_ROOT / "design" / "netlist" / "error_amp.spice",
}

OVERALL_RE = re.compile(r"\*\*Overall[^*]*\*\*")
RESULT_HEADING_RE = re.compile(r"^##\s*Result\b.*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# README spec-table parsing -- ground truth for row names/targets, so this
# script cannot silently drift from what the ratified table actually says.
# ---------------------------------------------------------------------------

def parse_spec_table() -> dict[str, tuple[str, str]]:
    text = README.read_text()
    m = re.search(
        r"\| Parameter \| Target \| Stretch \|\n\|[-\s|]+\|\n((?:\|.*\|\n)+)",
        text,
    )
    if not m:
        raise RuntimeError("could not locate README.md's spec table")
    rows = re.findall(
        r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|$", m.group(1), re.MULTILINE
    )
    return {name: (target, stretch) for name, target, stretch in rows}


# ---------------------------------------------------------------------------
# Evidence-record discovery
# ---------------------------------------------------------------------------

def latest_substantive_record(slug: str) -> tuple[pathlib.Path | None, pathlib.Path | None]:
    """The most recent record-id under sim/<slug>/records/ that has its own
    frozen netlist snapshot -- i.e. the most recent record that is itself a
    measurement, not a metadata-only correction record pointing back at an
    earlier one (sim/README.md's Supersedes/correction convention). Record
    ids sort chronologically as strings (YYYYMMDD-HHMMSS-sha), so the
    lexicographically-last one with a matching snapshot is the one wanted.
    """
    records_dir = SIM_DIR / slug / "records"
    snapshots_dir = SIM_DIR / slug / "netlist-snapshots"
    if not records_dir.is_dir():
        return None, None
    for record in sorted(records_dir.glob("*.md"), reverse=True):
        snapshot = snapshots_dir / f"{record.stem}.spice"
        if snapshot.is_file():
            return record, snapshot
    # No record has a matching snapshot -- fall back to the latest record
    # file so the gap is still visible rather than silently empty.
    records = sorted(records_dir.glob("*.md"), reverse=True)
    return (records[0], None) if records else (None, None)


def freshness(snapshot: pathlib.Path | None) -> tuple[str, str | None]:
    """Returns (status, matched-dut-label). status in {fresh, stale, unknown}."""
    if snapshot is None or not snapshot.is_file():
        return "unknown", None
    data = snapshot.read_bytes()
    for label, path in DUT_CANDIDATES.items():
        if path.read_bytes() in data:
            return "fresh", label
    return "stale", None


# ---------------------------------------------------------------------------
# Verdict extraction
# ---------------------------------------------------------------------------

def extract_verdict_snippets(text: str, keyword: str | None) -> list[str]:
    matches = OVERALL_RE.findall(text)
    if keyword:
        filtered = [m for m in matches if keyword.lower() in m.lower()]
        if filtered:
            return [_clean(m) for m in filtered]
        # keyword given but nothing matched it -- fall through to the
        # heading fallback rather than silently returning unrelated
        # sub-claims for a different row.
    elif matches:
        return [_clean(m) for m in matches]
    heading = RESULT_HEADING_RE.search(text)
    if heading:
        return [_clean(heading.group(0))]
    return []


def _clean(snippet: str) -> str:
    return re.sub(r"\s+", " ", snippet).strip(" *#")


def classify(snippets: list[str]) -> str:
    if not snippets:
        return "UNKNOWN"
    has_fail = any("FAIL" in s.upper() for s in snippets)
    has_pass = any("PASS" in s.upper() for s in snippets)
    if has_fail and has_pass:
        return "MIXED"
    if has_fail:
        return "FAIL"
    if has_pass:
        return "PASS"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Row definitions -- which experiment slug(s) substantiate each ratified
# README row. This mapping is domain knowledge (which testbench measures
# which spec line) and is the one part of this script that is necessarily
# hand-maintained; everything it points at (verdict, freshness, citation)
# is read fresh from the committed evidence on every run.
# ---------------------------------------------------------------------------

class Source:
    def __init__(self, slug: str, keyword: str | None = None, note: str = ""):
        self.slug = slug
        self.keyword = keyword
        self.note = note


class Row:
    def __init__(self, name: str, sources: list[Source] | None = None, na_note: str = ""):
        self.name = name
        self.sources = sources or []
        self.na_note = na_note


ROWS: list[Row] = [
    Row(
        "Input",
        na_note=(
            "Not independently tested: the 2.97-3.63 V input range is the "
            "Vin corner axis every other row's PVT sweep already covers, "
            "rather than a claim with a testbench of its own."
        ),
    ),
    Row(
        "Output",
        sources=[
            Source("mc-output-accuracy", note="statistical term (Monte Carlo mismatch)"),
            Source("amp-openloop", note="deterministic systematic-offset term"),
            Source("line-regulation", note="counted inside the window, not added to it"),
            Source("load-regulation", note="counted inside the window, not added to it"),
        ],
    ),
    Row(
        "Load",
        na_note=(
            "Not independently tested: the 0-50 mA operating-current axis "
            "is a condition exercised by the Dropout, Line reg, Load reg, "
            "Load transient, Current limit and PSRR rows, not a claim with "
            "a testbench of its own."
        ),
    ),
    Row(
        "Dropout @ 50 mA",
        sources=[
            Source(
                "dropout-vs-load",
                note=(
                    "verdict rests on DR-0017's measurement definition "
                    "(PROPOSED, not ratified): dropout read at the "
                    "regulation knee. The ratified < 300 mV bound itself is "
                    "unchanged. If the operator rejects DR-0017 this row "
                    "reverts to FAIL on the superseded fixed-headroom metric"
                ),
            )
        ],
    ),
    Row("Line reg", sources=[Source("line-regulation")]),
    Row("Load reg (0–50 mA)", sources=[Source("load-regulation")]),
    Row("Load transient", sources=[Source("load-transient")]),
    Row(
        "PSRR",
        sources=[
            Source("psrr-dc", note="amp-level open-loop DC term"),
            Source("psrr-vs-freq", note="closed-loop, 1 mA (binding light load)"),
            Source("psrr-vs-freq-50ma", note="closed-loop, 50 mA (full load)"),
        ],
    ),
    Row(
        "Iq (excluding load current)",
        sources=[
            Source("quiescent-current"),
            Source(
                "enable-shutdown",
                note="same run also substantiates this row's full-load enabled-state clause",
            ),
        ],
    ),
    Row(
        "Current limit",
        sources=[Source("current-limit", keyword="current limit")],
    ),
    Row("Startup", sources=[Source("startup"), Source("soft-start")]),
    Row("Enable / shutdown", sources=[Source("enable-shutdown")]),
    Row(
        "Thermal",
        sources=[
            Source(
                "current-limit",
                keyword="thermal",
                note=(
                    "only substantiates the '<=290 mW into a short' clause; "
                    "the '92 mW continuous worst case' clause has no "
                    "dedicated testbench of its own"
                ),
            )
        ],
    ),
    Row(
        "Output noise",
        na_note="Explicitly waived, README note 7 -- no consumer requirement exists to substantiate a number against.",
    ),
    Row(
        "Area",
        na_note="Not simulable pre-layout -- no LDO layout exists yet (#2).",
    ),
    Row("Stability", sources=[Source("loop-stability")]),
]

# Experiments that exist under sim/ but are not cited by any ROW above --
# supporting/precondition testbenches, harness self-tests, or device
# characterization, not a direct claim against a ratified spec row.
SUPPORTING_SLUGS_NOTE = {
    "amp-selfosc": "precondition check for loop-stability's Bode margins (the error amp's own local loop must not self-oscillate); not itself a ratified spec row.",
    "op-point-sanity": "loop-closure sanity check, not a ratified spec row.",
    "smoke-bias": "harness self-verification (PVT plumbing), not a spec claim.",
    "devchar": "PDK device characterization feeding other rows' assumptions (e.g. divider-mismatch, README note 3); has no records/ directory of its own -- see sim/devchar/CONCLUSIONS.md.",
}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def dut_current_shas() -> dict[str, str]:
    return {
        label: hashlib.sha256(path.read_bytes()).hexdigest()
        for label, path in DUT_CANDIDATES.items()
    }


def render() -> str:
    spec_table = parse_spec_table()
    dut_shas = dut_current_shas()

    out: list[str] = []
    out.append("# Characterization report\n")
    out.append(
        "Aggregated, regeneratable rollup of every ratified `README.md` "
        "Target-specification row against the evidence currently committed "
        "under `sim/<slug>/records/`. This is issue #104 (T1/bronze "
        "checklist item 8, per #95's 2026-08-15 re-read).\n"
    )
    out.append("## How this file is generated\n")
    out.append(
        "```\npython3 sim/build_characterization_report.py > sim/CHARACTERIZATION.md\n```\n"
    )
    out.append(
        "This file is **generated, not hand-edited** — see "
        "`sim/build_characterization_report.py`'s module docstring for the "
        "exact verdict-extraction and freshness rules. Re-run it after any "
        "`sim/` record lands (or any `design/netlist/*.spice` change) and "
        "commit the regenerated file; do not edit this file by hand.\n"
    )
    out.append(
        f"Current DUT netlist sha256: `design/netlist/ldo_core.spice` = "
        f"`{dut_shas['ldo_core']}`, `design/netlist/error_amp.spice` = "
        f"`{dut_shas['error_amp']}`.\n"
    )

    # ---- summary table ------------------------------------------------
    out.append("## Summary\n")
    out.append("| Spec row | Verdict | Fresh? | Evidence |")
    out.append("|---|---|---|---|")

    row_render_cache: dict[str, dict] = {}
    for row in ROWS:
        target, _stretch = spec_table.get(row.name, ("", ""))
        if not row.sources:
            out.append(f"| {row.name} | N/A | N/A | see note below |")
            row_render_cache[row.name] = {"na": True, "target": target}
            continue

        source_results = []
        for source in row.sources:
            record, snapshot = latest_substantive_record(source.slug)
            if record is None:
                source_results.append(
                    {
                        "source": source,
                        "record": None,
                        "verdict": "NO RECORDS FOUND",
                        "fresh_status": "unknown",
                        "fresh_dut": None,
                        "snippets": [],
                    }
                )
                continue
            text = record.read_text()
            snippets = extract_verdict_snippets(text, source.keyword)
            verdict = classify(snippets)
            fresh_status, fresh_dut = freshness(snapshot)
            source_results.append(
                {
                    "source": source,
                    "record": record,
                    "verdict": verdict,
                    "fresh_status": fresh_status,
                    "fresh_dut": fresh_dut,
                    "snippets": snippets,
                }
            )

        verdicts = [r["verdict"] for r in source_results]
        if "FAIL" in verdicts:
            row_verdict = "FAIL"
        elif "MIXED" in verdicts:
            row_verdict = "MIXED"
        elif "NO RECORDS FOUND" in verdicts or "UNKNOWN" in verdicts:
            row_verdict = "UNKNOWN"
        else:
            row_verdict = "PASS"

        fresh_statuses = [r["fresh_status"] for r in source_results]
        if "stale" in fresh_statuses:
            row_fresh = "STALE"
        elif "unknown" in fresh_statuses:
            row_fresh = "unknown"
        else:
            row_fresh = "fresh"

        primary = source_results[0]
        if primary["record"] is not None:
            primary_cite = f"`sim/{primary['source'].slug}/records/{primary['record'].stem}.md`"
            if len(source_results) > 1:
                primary_cite += " (+ %d more, see detail)" % (len(source_results) - 1)
        else:
            primary_cite = f"`sim/{primary['source'].slug}/records/` — no records found"

        out.append(f"| {row.name} | {row_verdict} | {row_fresh} | {primary_cite} |")
        row_render_cache[row.name] = {
            "na": False,
            "target": target,
            "sources": source_results,
            "row_verdict": row_verdict,
            "row_fresh": row_fresh,
        }

    # ---- per-row detail -------------------------------------------------
    out.append("\n## Detail\n")
    for row in ROWS:
        cache = row_render_cache[row.name]
        out.append(f"### {row.name}\n")
        out.append(f"**Ratified target**: {cache['target']}\n")
        if cache["na"]:
            out.append(f"**N/A**: {row.na_note}\n")
            continue
        out.append(f"**Verdict**: {cache['row_verdict']}  **Fresh**: {cache['row_fresh']}\n")
        for r in cache["sources"]:
            slug = r["source"].slug
            if r["record"] is None:
                out.append(f"- `{slug}`: **NO RECORDS FOUND** under `sim/{slug}/records/`.")
                continue
            cite = f"`sim/{slug}/records/{r['record'].stem}.md`"
            fresh_str = r["fresh_status"]
            if fresh_str == "fresh":
                fresh_str = f"fresh (matches current `{r['fresh_dut']}`)"
            elif fresh_str == "unknown":
                fresh_str = "unknown (no netlist snapshot committed for this record)"
            snippet_str = " / ".join(r["snippets"]) if r["snippets"] else "(no explicit Overall/Result verdict found in record text)"
            note = f" — {r['source'].note}" if r["source"].note else ""
            out.append(f"- `{slug}`{note}: {cite} — **{r['verdict']}**, {fresh_str}")
            out.append(f"  - {snippet_str}")
        out.append("")

    # ---- tallies ----------------------------------------------------------
    testable = [row_render_cache[row.name] for row in ROWS if not row_render_cache[row.name]["na"]]
    n_pass = sum(1 for c in testable if c["row_verdict"] == "PASS")
    n_fail = sum(1 for c in testable if c["row_verdict"] == "FAIL")
    n_mixed = sum(1 for c in testable if c["row_verdict"] == "MIXED")
    n_unknown = sum(1 for c in testable if c["row_verdict"] == "UNKNOWN")
    n_fresh = sum(1 for c in testable if c["row_fresh"] == "fresh")
    n_stale = sum(1 for c in testable if c["row_fresh"] == "STALE")
    n_fresh_unknown = sum(1 for c in testable if c["row_fresh"] == "unknown")
    n_na = len(ROWS) - len(testable)

    out.append("## Tally\n")
    out.append(
        f"{len(ROWS)} ratified rows: {len(testable)} testable "
        f"({n_pass} PASS, {n_fail} FAIL, {n_mixed} MIXED, {n_unknown} UNKNOWN), "
        f"{n_na} N/A.\n"
    )
    out.append(
        f"Freshness among the {len(testable)} testable rows: {n_fresh} fresh, "
        f"{n_stale} stale, {n_fresh_unknown} unknown.\n"
    )
    out.append(
        "A row is only a true current PASS if its Verdict column reads "
        "PASS **and** its Fresh column reads fresh — a stale PASS reflects "
        "a design state this repo has since moved past, not a claim about "
        "`design/netlist/ldo_core.spice` as committed today.\n"
    )

    # ---- appendix -----------------------------------------------------
    out.append("## Appendix: supporting testbenches (not a ratified spec row)\n")
    out.append(
        "These `sim/` experiment directories exist and carry real evidence "
        "but do not map to a distinct row of README.md's Target specification "
        "table — listed for completeness, not tallied above.\n"
    )
    out.append("| Experiment | Role |")
    out.append("|---|---|")
    for slug, note in SUPPORTING_SLUGS_NOTE.items():
        out.append(f"| `{slug}` | {note} |")
    out.append("")

    out.append(
        "---\n\nGenerated by `sim/build_characterization_report.py`. Not "
        "itself evidence — see the append-only records under "
        "`sim/<slug>/records/` for that. Regenerate after any `sim/` record "
        "lands or `design/netlist/*.spice` changes; do not hand-edit.\n"
    )

    return "\n".join(out) + "\n"


def main() -> int:
    all_slugs = {p.name for p in SIM_DIR.iterdir() if p.is_dir() and (p / "records").is_dir()}
    mapped_slugs = {source.slug for row in ROWS for source in row.sources}
    unmapped = all_slugs - mapped_slugs - set(SUPPORTING_SLUGS_NOTE)
    if unmapped:
        print(
            f"warning: sim/ experiment(s) with records/ not mapped to a row "
            f"or the supporting-testbench appendix: {sorted(unmapped)}",
            file=sys.stderr,
        )
    print(render(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
