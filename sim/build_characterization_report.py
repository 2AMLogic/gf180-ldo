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
script extracts every such verdict from the chosen record, optionally filtered
by a keyword when one record's latest substantive result covers more than
one ratified row (e.g. ``current-limit`` covers both the "Current limit" row
and the "Thermal" row).

A verdict is not always one contiguous bold run: records also state one
verdict as *several* bold runs separated by unbolded qualifying prose
(``**Overall (...): FAIL on ramp rate** (163/163 points ...) **and FAIL on
inrush and current-limit clearance** (0/83 ...)``). Reading only the first
run dropped every later clause and made the rollup read more favourably
than the evidence it summarised (issue #251), so a verdict is taken to run
from its ``**Overall`` opener to the end of the enclosing Markdown block (a
paragraph, a list item, a table row) or to the next ``**Overall`` opener,
whichever comes first. Every PASS/FAIL-stating bold run in that span is a
clause of the verdict; the clauses are joined with `` … ``, which marks the
unbolded prose elided between them. A record that states its verdict as one
bold run renders exactly as it always did.

Records that use the older ``## Result ...`` heading style instead of a
bolded ``**Overall**`` span (a handful of the earliest hand-written
testbenches) are matched via that heading as a fallback. A record with
neither is reported as UNKNOWN rather than silently guessed.

## Coverage: no experiment may escape this rollup

Every ``sim/<slug>/records/`` directory must reach the report, either as a
``Source(...)`` under a ``Row`` (direct evidence for a ratified README row)
or as a ``SUPPORTING_SLUGS_NOTE`` entry (the appendix of supporting
testbenches that are not a ratified row). A slug reaching neither is a
**hard failure**: the report is still printed in full -- so regenerating
into ``sim/CHARACTERIZATION.md`` never truncates it -- but the exit status
is non-zero and the gap is named on stderr.

This was a stderr-only warning with an unconditional exit 0 until issue
#257, which is how ``sim/soft-start-loop-gain/`` sat outside both tables
unnoticed: CI's "Verify sim/CHARACTERIZATION.md is up to date" step diffs
stdout, so a warning nothing reads changed nothing. A rollup that silently
omits committed evidence is worse than no rollup, because it reads as
complete.

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

import csv
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

# A verdict is stated as one or more **bold runs** inside a single Markdown
# block (a paragraph, a list item, a table row). BOLD_RUN_RE finds the runs;
# BLOCK_START_RE finds where the enclosing block ends, so a verdict never
# absorbs the next bullet's or the next paragraph's bold text. See
# extract_verdict_snippets() for how the two combine (issue #251).
BOLD_RUN_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
BLOCK_START_RE = re.compile(r"^[ \t]*(?:[-+]\s|\*\s|\d+[.)]\s|\||#{1,6}\s|>)")
OVERALL_OPENER_RE = re.compile(r"^\s*Overall\b")
# A bold run *after* the opener only continues the verdict if it states a
# result; a bare emphasis run in the qualifying prose (e.g. "ruling the ramp
# node **out**") is not a verdict clause. PASS/FAIL is the same token set
# classify() reads, so a run this skips could not have changed the verdict.
RESULT_TOKEN_RE = re.compile(r"PASS|FAIL", re.IGNORECASE)
# Separator between the clauses of one verdict that the record itself wrote
# as separate bold runs, marking the unbolded prose elided between them.
CLAUSE_JOIN = " … "
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

def _markdown_blocks(text: str) -> list[str]:
    """Split ``text`` into Markdown blocks: paragraphs, list items, table
    rows, headings. A block ends at a blank line or at the start of the next
    block-level construct, so a continuation line (an indented wrap of the
    line above) stays with the statement it continues.
    """
    blocks: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip():
            blocks.append([])  # blank line: whatever follows starts anew
            continue
        if BLOCK_START_RE.match(line) or not blocks or not blocks[-1]:
            blocks.append([line])
        else:
            blocks[-1].append(line)
    return ["\n".join(block) for block in blocks if block]


def _verdict_statements(text: str) -> list[str]:
    """Every ``**Overall...**`` verdict in ``text``, each rendered with ALL
    of its bold-run clauses rather than only the first (issue #251).

    Records state a verdict either as one contiguous bold run
    (``**Overall (thermal, ratified <= 290 mW into a short): FAIL**``) or as
    several bold runs separated by unbolded prose that qualifies them
    (``**Overall (...): FAIL on ramp rate** (163/163 points ...) **and FAIL
    on inrush and current-limit clearance** (0/83 ...)``). Both forms state
    one verdict, so both must render as one snippet -- reading only the
    first bold run made the rollup read more favourably than the evidence it
    summarises.

    A verdict runs from its ``**Overall`` opener to the end of the enclosing
    Markdown block, or to the next ``**Overall`` opener, whichever comes
    first. Bold runs before the first opener in a block (e.g. a sibling
    ``- **Links**:`` bullet's own label) are not part of any verdict, and a
    bold run after the opener only continues it if it states a PASS/FAIL
    result -- prose emphasis (``ruling the ramp node **out**``) is not a
    verdict clause. The elided unbolded prose is marked with ``CLAUSE_JOIN``
    rather than reproduced: it is qualification, not verdict text, and the
    record itself remains the citation.
    """
    statements: list[list[str]] = []
    for block in _markdown_blocks(text):
        current: list[str] | None = None
        for match in BOLD_RUN_RE.finditer(block):
            run = match.group(1)
            if OVERALL_OPENER_RE.match(run):
                if current:
                    statements.append(current)
                current = [run]
            elif current is not None and RESULT_TOKEN_RE.search(run):
                current.append(run)
        if current:
            statements.append(current)
    return [CLAUSE_JOIN.join(_clean(run) for run in runs) for runs in statements]


def extract_verdict_snippets(text: str, keyword: str | None) -> list[str]:
    statements = _verdict_statements(text)
    if keyword:
        filtered = [s for s in statements if keyword.lower() in s.lower()]
        if filtered:
            return filtered
        # keyword given but nothing matched it -- fall through to the
        # heading fallback rather than silently returning unrelated
        # sub-claims for a different row.
    elif statements:
        return statements
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
# Envelope filters -- a Source may narrow its verdict to a named subset of
# its record's own committed ``-matrix.csv``, rather than the record's
# top-level prose ``**Overall...**`` verdict (issue #276).
#
# Some records (e.g. ``sim/loop-stability/``) sweep a wider grid than the
# spec currently ratifies -- DR-0018 narrowed the ``Stability`` row's claimed
# envelope on 2026-09-15 without narrowing the bench itself (its Consequence
# #2). Grading such a row from the record's own prose grades it against
# whatever matrix the *record* states its verdict over, which can be wider
# than what README.md actually claims -- silently hiding a real pass inside
# the ratified envelope (or, going forward, a real regression inside it,
# since a verdict that is already FAIL cannot get worse to signal one).
#
# Each envelope's predicate reads the record's ``-matrix.csv`` (the
# machine-readable per-point sweep every ``sim/loop-stability`` record
# already commits) so the boundary is derived from real per-point data, not
# re-spelled as a second copy of the decision record's prose. Defined once
# here so neither this report nor any future reader of it can drift from
# what the cited decision record actually narrowed the row to.
# ---------------------------------------------------------------------------

class EnvelopeFilter:
    def __init__(self, name: str, decision_record: str, predicate):
        self.name = name
        self.decision_record = decision_record
        # callable(csv_row: dict[str, str]) -> bool
        self.predicate = predicate


def _in_dr0018_stability_envelope(row: dict[str, str]) -> bool:
    """DR-0018's ratified ``Stability`` envelope: 0.1-50 mA (0 mA is excluded
    per DR-0007), C_eff = 1 uF nominal, ESR >= 200 mOhm."""
    return (
        float(row["iload_ma"]) > 0
        and abs(float(row["ceff_uf"]) - 1.0) < 1e-9
        and float(row["esr_ohm"]) >= 0.2
    )


DR0018_STABILITY_ENVELOPE = EnvelopeFilter(
    name="0.1-50 mA / C_eff=1uF nominal / ESR>=200 mOhm",
    decision_record="DR-0018",
    predicate=_in_dr0018_stability_envelope,
)


def envelope_verdict(record: pathlib.Path, envelope: EnvelopeFilter) -> dict:
    """PASS/FAIL for ``envelope``'s subset of ``record``'s own committed
    ``-matrix.csv``, alongside the full-matrix pass count for context (the
    wider-matrix result must stay visible, not be dropped -- issue #276).

    A point counts as passing the envelope only if it passes **both** the
    record's own phase/gain-margin ``result`` column and its DR-0008
    ``resurgence_result`` column -- either one failing inside the ratified
    envelope must fail the row, matching how the record's own prose states
    its envelope accounting.
    """
    csv_path = record.parent / f"{record.stem}-matrix.csv"
    if not csv_path.is_file():
        return {"available": False, "verdict": "UNKNOWN"}

    with csv_path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    n_total_full = len(rows)
    n_pass_full = sum(1 for r in rows if r.get("result", "").upper() == "PASS")

    subset = [r for r in rows if envelope.predicate(r)]
    if not subset:
        return {
            "available": True,
            "verdict": "UNKNOWN",
            "n_pass": 0,
            "n_total": 0,
            "n_total_full": n_total_full,
            "n_pass_full": n_pass_full,
        }

    def _point_passes(r: dict[str, str]) -> bool:
        result_ok = r.get("result", "").upper() == "PASS"
        resurgence_ok = r.get("resurgence_result", "PASS").upper() == "PASS"
        return result_ok and resurgence_ok

    n_pass = sum(1 for r in subset if _point_passes(r))
    n_total = len(subset)
    n_resurge_flagged = sum(
        1 for r in subset if r.get("resurgence_result", "PASS").upper() != "PASS"
    )
    result: dict = {
        "available": True,
        "verdict": "PASS" if n_pass == n_total else "FAIL",
        "n_pass": n_pass,
        "n_total": n_total,
        "n_resurge_flagged": n_resurge_flagged,
        "n_total_full": n_total_full,
        "n_pass_full": n_pass_full,
    }
    if "phase_margin_deg" in subset[0] and "gain_margin_db" in subset[0]:
        result["worst_pm"] = min(float(r["phase_margin_deg"]) for r in subset)
        result["worst_gm"] = min(float(r["gain_margin_db"]) for r in subset)
    return result


def _render_envelope_snippet(env: dict, envelope: EnvelopeFilter) -> str:
    if not env["available"]:
        return (
            f"envelope ({envelope.decision_record}, {envelope.name}): UNKNOWN "
            "-- no `-matrix.csv` committed alongside this record"
        )
    if env["n_total"] == 0:
        return (
            f"envelope ({envelope.decision_record}, {envelope.name}): UNKNOWN "
            "-- no matrix point falls inside this envelope"
        )
    margin = ""
    if "worst_pm" in env and "worst_gm" in env:
        margin = f", worst PM {env['worst_pm']:.2f} deg / worst GM {env['worst_gm']:.2f} dB"
    full = ""
    if env["n_total_full"]:
        full = (
            f"; full matrix (DR-0001's original, wider window): "
            f"{env['n_pass_full']}/{env['n_total_full']} passing"
        )
    return (
        f"envelope ({envelope.decision_record}, {envelope.name}): "
        f"**{env['verdict']}** -- {env['n_pass']}/{env['n_total']} points passing"
        f"{margin}, DR-0008 resurgence flagged {env.get('n_resurge_flagged', 0)}/"
        f"{env['n_total']}{full}"
    )


# ---------------------------------------------------------------------------
# Row definitions -- which experiment slug(s) substantiate each ratified
# README row. This mapping is domain knowledge (which testbench measures
# which spec line) and is the one part of this script that is necessarily
# hand-maintained; everything it points at (verdict, freshness, citation)
# is read fresh from the committed evidence on every run.
# ---------------------------------------------------------------------------

class Source:
    def __init__(
        self,
        slug: str,
        keyword: str | None = None,
        note: str = "",
        envelope: EnvelopeFilter | None = None,
    ):
        self.slug = slug
        self.keyword = keyword
        self.note = note
        # When set, this source's verdict is computed from the record's own
        # committed ``-matrix.csv`` filtered to ``envelope``, rather than
        # from the record's full-matrix prose verdict (issue #276).
        self.envelope = envelope


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
                    "verdict rests on DR-0020's measurement definition "
                    "(PROPOSED, not ratified): dropout read at the "
                    "regulation knee. The ratified < 300 mV bound itself is "
                    "unchanged. If the operator rejects DR-0020 this row "
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
    Row(
        "Stability",
        sources=[
            Source(
                "loop-stability",
                envelope=DR0018_STABILITY_ENVELOPE,
                note=(
                    "verdict is computed from this record's own committed "
                    "`-matrix.csv`, filtered to the ratified DR-0018 "
                    "envelope (0.1-50 mA, C_eff = 1 uF, ESR >= 200 mOhm), "
                    "not from the record's full-matrix prose verdict -- "
                    "that prose states DR-0001's ORIGINAL, wider 4536-point "
                    "matrix, which this row no longer claims (DR-0018, "
                    "ratified 2026-09-15). The wider-matrix result is kept "
                    "visible alongside the envelope verdict below, not "
                    "dropped; points outside the envelope are covered by "
                    "DR-0018 (cap/ESR) and DR-0007 (0 mA) -- subset "
                    "accounting cross-checked in sim/loop-stability/"
                    "records/20260922-022122-ac57c94.md"
                ),
            )
        ],
    ),
]

# Experiments that exist under sim/ but are not cited by any ROW above --
# supporting/precondition testbenches, harness self-tests, or device
# characterization, not a direct claim against a ratified spec row.
SUPPORTING_SLUGS_NOTE = {
    "amp-selfosc": "precondition check for loop-stability's Bode margins (the error amp's own local loop must not self-oscillate); not itself a ratified spec row.",
    "op-point-sanity": "loop-closure sanity check, not a ratified spec row.",
    "smoke-bias": "harness self-verification (PVT plumbing), not a spec claim.",
    "devchar": "PDK device characterization feeding other rows' assumptions (e.g. divider-mismatch, README note 3); has no records/ directory of its own -- see sim/devchar/CONCLUSIONS.md.",
    "vref-transfer": "VREF-to-VOUT small-signal transfer over frequency, light load (1 mA) -- issue #178 / DR-0021 Decision #3's 'accuracy / tempco / noise / its own PSRR' contract-table row; not itself a ratified spec row (no threshold exists for this transfer), but its measured gain feeds the reference accuracy-class budget derived in sim/vref-transfer/README.md.",
    "vref-transfer-50ma": "VREF-to-VOUT small-signal transfer over frequency, full load (50 mA) -- the load-dependent sibling of vref-transfer, same role.",
    "soft-start-loop-gain": "small-signal loop gain, phase margin, gain margin and the DR-0008 gain-resurgence metric of the main loop *during* the soft-start hand-over, held at pinned points of the ramp across the `device`/`binj` DUT variants (issue #196). Not a ratified spec row, and explicitly not a DR-0001 verdict: DR-0001's matrix is the settled operating point, where the ramp is over and the FB injection is off, so `loop-stability` remains the Stability row's evidence and nothing here moves it -- see sim/soft-start-loop-gain/README.md, \"What it measures, and what it deliberately does not\".",
    "toolchain-portability": "measures the *simulator*, not the design (issue #254 / DR-0027): whether DR-0025's `wnflag` model-bin facts and `sim/loop-stability`'s loop-gain margins reproduce across ngspice majors (42, 46, 47). Not a ratified spec row and explicitly never a DR-0001 (or any other spec-line) verdict -- see sim/toolchain-portability/README.md, \"What a record here may and may not conclude\". No sim/loop-stability record is added, edited, or superseded by anything under this slug.",
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
            if source.envelope is not None:
                env = envelope_verdict(record, source.envelope)
                verdict = env["verdict"]
                snippets = [_render_envelope_snippet(env, source.envelope)]
            else:
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


def unmapped_slugs() -> list[str]:
    """Every ``sim/<slug>/records/`` directory that reaches neither a ``ROWS``
    entry nor ``SUPPORTING_SLUGS_NOTE`` -- i.e. every experiment carrying
    committed evidence that this report would not mention at all.

    A slug listed in ``SUPPORTING_SLUGS_NOTE`` without a ``records/``
    directory of its own (``devchar``) is not a candidate in the first place
    and is unaffected.
    """
    all_slugs = {p.name for p in SIM_DIR.iterdir() if p.is_dir() and (p / "records").is_dir()}
    mapped_slugs = {source.slug for row in ROWS for source in row.sources}
    return sorted(all_slugs - mapped_slugs - set(SUPPORTING_SLUGS_NOTE))


def main() -> int:
    unmapped = unmapped_slugs()
    # The report is printed either way, so regenerating into the committed
    # file never truncates it; the gap is signalled by the exit status.
    print(render(), end="")
    if unmapped:
        print(
            f"error: sim/ experiment(s) with records/ not mapped to a row "
            f"or the supporting-testbench appendix: {unmapped}. Add each to "
            f"a Row's Source(...) list if it is direct evidence for a "
            f"ratified README row, or to SUPPORTING_SLUGS_NOTE with a "
            f"description of its role. Committed evidence that this rollup "
            f"does not mention is invisible to every reader of it.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
