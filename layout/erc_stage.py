#!/usr/bin/env python3
"""The ``klt erc`` supply stage (issue #785) and the run record's ERC parts.

Relocated verbatim from ``layout/drclvs.py`` by issue #837, which re-exports
every public name here; ``layout/tests/test_drclvs.py`` still exercises the
whole contract through ``drclvs.<name>``. Two groups:

- the stage, for a cell whose ``CellSpec`` registers an ``ErcSpec``:
  ``run_erc_spec_gen`` emits the supply spec from the committed GDS,
  ``run_klt_erc`` runs ``klt erc`` findings-only, ``validate_erc_report``
  holds the envelope to the cell's contract, and ``run_erc_control`` /
  ``check_erc_control_findings`` are the tie-severing negative control;
- what ``drclvs.write_record()`` renders from the run's summary:
  ``erc_result_rows`` and ``erc_section``.

``CellSpec`` -- the driver's type -- is imported for annotations only,
because the driver imports this module.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drclvs_common import (  # noqa: E402
    LAYOUT_DIR,
    REPO_ROOT,
    StageError,
    repo_arg,
)

if TYPE_CHECKING:
    from drclvs import CellSpec

__all__ = [
    "ERC_REPORTS_DIR",
    "ERC_SPECS_DIR",
    "GEN_ERC_SPEC_SCRIPT",
    "MUTATE_ERC_SCRIPT",
    "ErcSpec",
    "check_erc_control_findings",
    "erc_finding_keys",
    "erc_result_rows",
    "erc_section",
    "run_erc_control",
    "run_erc_spec_gen",
    "run_klt_erc",
    "validate_erc_report",
]


@dataclasses.dataclass(frozen=True)
class ErcSpec:
    """The ``klt erc`` supply stage's per-cell contract (issue #785).

    A cell registers one of these (``CellSpec.erc``) when it has a committed
    supply spec; the stages themselves are generic, exactly like the LVS
    controls. T1 item 11 stays ``unmet`` on these sub-cell runs -- they are
    the groundwork #524's top-level run reuses, not the item's evidence.
    """

    # The spec's declared ties, by name. Each must land in the intact run's
    # ``erc_coverage.checked`` (and NOT in ``skipped`` -- a skipped tie is a
    # degenerate declaration the docs refuse to read as a pass).
    ties: tuple[str, ...]
    # ``(rule, net)`` findings the INTACT cell legitimately reports, so the
    # stage can tell a disclosed finding from a new defect: pass_array's
    # standalone gate bus is a label-only port, which is one real
    # erc.floating_gate by design (gate routing lands at ldo_core assembly).
    expected_findings: tuple[tuple[str, str], ...] = ()
    # One line naming the ERC negative control's mutation, quoted in the
    # record beside the LVS controls' own descriptions.
    control_mutation: str = ""

    def tie_id(self, name: str) -> str:
        return f'erc.missing_tie:["{name}"]'


# --------------------------------------------------------------------------
# stage 5 -- klt erc supply spec (issue #785)
# --------------------------------------------------------------------------

#: Committed ERC spec tree (``layout/erc/specs/<key>.erc.json``), emitted by
#: ``layout/erc/gen_spec.py`` from the committed GDS -- a source artifact the
#: eventual ``ldo_core`` supply run extends, not per-run evidence (the reports
#: under ``layout/erc/reports/`` are the append-only evidence, named by record
#: id exactly like the DRC/LVS report trees).
ERC_SPECS_DIR = LAYOUT_DIR / "erc" / "specs"
ERC_REPORTS_DIR = LAYOUT_DIR / "erc" / "reports"
GEN_ERC_SPEC_SCRIPT = LAYOUT_DIR / "erc" / "gen_spec.py"
MUTATE_ERC_SCRIPT = LAYOUT_DIR / "erc" / "mutate_gds.py"


def erc_finding_keys(report: dict) -> set[tuple[str, str]]:
    """The ``(rule, net)`` identity set of a report's ``erc_findings``."""
    return {(f["rule"], f["net"]) for f in report.get("erc_findings", [])}


def validate_erc_report(report: dict, spec: CellSpec) -> tuple[list[str], dict]:
    """Check an intact-run ERC envelope against this cell's contract.

    Returns ``(failures, summary)``; ``failures`` is empty when every claim
    below held. The checks are the issue #785 acceptance criteria made
    mechanical, so a green ``--record`` run cannot quietly mean less than
    the record says:

    - the finding set is exactly the cell's disclosed ``expected_findings``
      -- in particular no ``erc.unconnected_net``, ``erc.supply_short`` or
      ``erc.missing_tie`` anywhere, and a disclosed finding that vanished
      is a failure too (the disclosure would have rotted);
    - every declared net resolved ``matched_islands == expected_islands``
      (both are labelled-island counts by the ERC contract; the report
      carries them whether or not a finding fired);
    - every declared tie is in ``erc_coverage.checked`` and none is in
      ``skipped`` (a degenerate/skipped tie "does not count as checked");
    - ``layers_in_stream_without_declaration`` is empty: the spec generator
      declares every routing layer the stream draws, so a non-empty list
      means the spec has rotted behind the layout.
    """
    erc = spec.erc
    assert erc is not None  # the stage only runs for cells that registered one
    failures: list[str] = []
    findings = erc_finding_keys(report)
    expected = set(erc.expected_findings)
    unexpected = findings - expected
    missing = expected - findings
    if unexpected:
        failures.append(
            "the ERC run reported findings the cell does not disclose: "
            + ", ".join(f"{rule} on {net}" for rule, net in sorted(unexpected))
        )
    if missing:
        failures.append(
            "the cell's disclosed ERC findings are no longer reported (the "
            "disclosure has rotted): "
            + ", ".join(f"{rule} on {net}" for rule, net in sorted(missing))
        )
    nets_summary = []
    for net in report.get("nets", []):
        nets_summary.append(
            {
                "name": net["name"],
                "matched_islands": net["matched_islands"],
                "expected_islands": net["expected_islands"],
            }
        )
        if net["matched_islands"] != net["expected_islands"]:
            failures.append(
                f"net {net['name']} resolved {net['matched_islands']} "
                f"island(s) carrying its label, expected "
                f"{net['expected_islands']}"
            )
    coverage = report.get("erc_coverage") or {}
    checked = coverage.get("checked") or []
    skipped = coverage.get("skipped") or []
    skipped_ids = [entry["id"] if isinstance(entry, dict) else entry
                   for entry in skipped]
    for tie in erc.ties:
        if erc.tie_id(tie) not in checked:
            failures.append(
                f"tie {tie!r} is not in erc_coverage.checked -- its "
                "erc.missing_tie work was not graded as checked"
            )
        if erc.tie_id(tie) in skipped_ids:
            failures.append(
                f"tie {tie!r} is listed in erc_coverage.skipped -- a skipped "
                "tie does not count as checked (degenerate declaration)"
            )
    undeclared = coverage.get("layers_in_stream_without_declaration") or []
    if undeclared:
        failures.append(
            "the stream draws layers the spec declares nowhere: "
            f"{undeclared}"
        )
    summary = {
        "erc_status": report.get("erc_status"),
        "findings": [
            {"rule": rule, "net": net} for rule, net in sorted(findings)
        ],
        "nets": nets_summary,
        "ties_checked": [
            name for name in erc.ties if spec.erc.tie_id(name) in checked
        ],
        "ties_by_well_assertion": coverage.get("checked_by_well_assertion") or [],
        "ties_skipped": skipped_ids,
        "inapplicable": coverage.get("inapplicable") or [],
        "layers_in_stream_without_declaration": undeclared,
        "deck": (report.get("provenance") or {}).get("deck"),
        "klt_version": (report.get("provenance") or {}).get("klt_version"),
    }
    return failures, summary


def run_erc_spec_gen(spec: CellSpec, gds: Path, out_json: Path) -> str:
    """Emit the cell's supply spec from the committed GDS (issue #785).

    ``layout/erc/gen_spec.py`` under ``klayout -b -r``: one parameterized
    source per cell, measuring the GDS (the divider's asserted substrate
    region) and asserting every spec claim the tool cannot check (COMP
    draws only the divider's tap ring, the array's well/tap/via landings
    exist, the supply labels are where the spec says). A nonzero exit is a
    StageError carrying the generator's message.
    """
    ERC_SPECS_DIR.mkdir(parents=True, exist_ok=True)
    rel_script = repo_arg(GEN_ERC_SPEC_SCRIPT)
    proc = subprocess.run(
        [
            "klayout", "-b", "-r", str(rel_script),
            "-rd", f"cell={spec.key}",
            "-rd", f"gds={repo_arg(gds)}",
            "-rd", f"out={repo_arg(out_json)}",
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        raise StageError(
            f"the ERC spec generator failed for {spec.key} "
            f"(exit {proc.returncode})\n{proc.stdout}\n{proc.stderr}"
        )
    if not out_json.is_file():
        raise StageError(f"the ERC spec generator wrote no spec at {out_json}")
    return proc.stdout.strip()


def run_klt_erc(
    spec: CellSpec, gds: Path, spec_json: Path, out_json: Path
) -> dict:
    """One ``klt erc`` findings-only run, report captured to ``out_json``.

    Same invocation shape the test plan fixes: ``--deck gf180mcu`` (whose
    resistor recognition carves the divider's ppolyf_u bodies out of poly2)
    plus ``--findings-only``. ``klt erc`` writes its JSON to stdout (no
    ``-o``), so the report is captured here and written to ``out_json`` --
    the committed-report artifact for a ``--record`` run. Exit 3 (findings)
    and 4 (antenna not checked, every findings-only run) are both
    successful runs; the verdict read is ``erc_status`` in the payload.
    """
    proc = subprocess.run(
        [
            "klt", "erc", str(repo_arg(gds)), str(repo_arg(spec_json)),
            "--top", spec.top_cell,
            "--deck", "gf180mcu",
            "--findings-only", "--format", "json",
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if proc.returncode not in (0, 3, 4):
        raise StageError(
            f"klt erc failed for {spec.key} (exit {proc.returncode})\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise StageError(
            f"klt erc wrote no readable JSON report for {spec.key}: {exc}"
        )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(proc.stdout.rstrip("\n") + "\n")
    return report


def run_erc_control(
    spec: CellSpec,
    stage_gds: Path,
    spec_json: Path,
    intact: dict,
    run_dir: Path,
) -> dict:
    """The ERC negative control: sever the declared tie, expect the finding.

    Mirrors the LVS controls' contract ("a run that cannot fail is not
    evidence") on the layout side: ``layout/erc/mutate_gds.py`` writes a
    disposable copy with every cut landing on the FIRST declared tie's tap
    region deleted (the tie's path to its net, not its labelled metal and
    not the tap itself), the copy is run with the **intact** spec, and the
    run passes only when the finding set grew by exactly one new
    ``erc.missing_tie`` on that tie -- a skipped check, a malformed report
    or any unrelated new finding fails the control.
    """
    erc = spec.erc
    assert erc is not None
    tie = erc.ties[0]
    mutated = run_dir / f"{spec.cell}.erc-control.gds"
    proc = subprocess.run(
        [
            "klayout", "-b", "-r", str(repo_arg(MUTATE_ERC_SCRIPT)),
            "-rd", f"cell={spec.key}",
            "-rd", f"src={repo_arg(stage_gds)}",
            "-rd", f"dst={repo_arg(mutated)}",
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        raise StageError(
            f"the ERC control mutation failed for {spec.key} "
            f"(exit {proc.returncode})\n{proc.stdout}\n{proc.stderr}"
        )
    report = run_klt_erc(
        spec, mutated, spec_json,
        run_dir / f"{spec.cell}.erc-control.erc.json",
    )
    failures, tie_nets = check_erc_control_findings(report, intact, erc)
    return {
        "mutation": erc.control_mutation,
        "finding": f"erc.missing_tie on {tie}" if tie_nets else None,
        "net": sorted(tie_nets),
        "removed": proc.stdout.strip().splitlines()[-1]
        if proc.stdout.strip() else "",
        "failures": failures,
        "report_path": run_dir / f"{spec.cell}.erc-control.erc.json",
    }


def check_erc_control_findings(
    mutant: dict, intact: dict, erc: ErcSpec
) -> tuple[list[str], set[str]]:
    """Grade the ERC negative control's report against the intact one.

    Returns ``(failures, nets)`` where ``nets`` are the declared nets the
    intended ``erc.missing_tie`` finding named. The control passes only
    when the finding set grew by exactly one new ``erc.missing_tie`` **on
    the declared tie** (the finding's ``layer`` names the tie): a skipped
    check, an absent finding, or any unrelated new finding fails it -- the
    ERC counterpart of the LVS controls' "a control that matches is a
    failed run".
    """
    tie = erc.ties[0]
    findings = erc_finding_keys(mutant)
    # Anything the intact run already reported (disclosed or not -- an
    # undisclosed intact finding already failed the intact stage) is
    # baseline; the control must add exactly one new erc.missing_tie.
    new = findings - erc_finding_keys(intact)
    failures: list[str] = []
    tie_nets = {
        f["net"]
        for f in mutant.get("erc_findings", [])
        if f["rule"] == "erc.missing_tie" and f.get("layer") == tie
    }
    if not tie_nets:
        failures.append(
            f"severing the tie ({erc.control_mutation}) produced no "
            f"erc.missing_tie on {tie!r} -- the ERC run cannot fail on this "
            "defect, so its clean verdict on the intact layout is not "
            "evidence"
        )
    unrelated = {
        (rule, net)
        for rule, net in new
        if not (rule == "erc.missing_tie" and net in tie_nets)
    }
    if unrelated:
        failures.append(
            "the ERC control run reported unrelated new findings: "
            + ", ".join(f"{rule} on {net}" for rule, net in sorted(unrelated))
        )
    skipped_ids = [
        entry["id"] if isinstance(entry, dict) else entry
        for entry in (mutant.get("erc_coverage") or {}).get("skipped") or []
    ]
    if erc.tie_id(tie) in skipped_ids:
        failures.append(
            f"the control run's tie {tie!r} landed in erc_coverage.skipped -- "
            "the control did not actually grade the severed tie"
        )
    return failures, tie_nets


def erc_result_rows(summary: dict) -> str:
    """The Results-table rows for a cell with an ERC run (issue #785)."""
    if "erc" not in summary:
        return ""
    erc = summary["erc"]
    findings = ", ".join(f"`{f['rule']}` on `{f['net']}`" for f in erc["findings"])
    if not findings:
        findings = "none"
    rows = [
        f"| ERC -- `klt erc --deck gf180mcu --findings-only` vs. `{erc['spec']}`"
        f" | **`{erc['erc_status']}`**; finding(s): {findings} |"
    ]
    control = summary.get("erc_control")
    if control:
        verdict = (
            "**erc.missing_tie on the intended tie, as required**"
            if control["finding"] and not control["failures"]
            else "**NO EXPECTED FINDING -- INVALID RUN**"
        )
        rows.append(
            f"| ERC negative control ({control['mutation']}) | {verdict} |"
        )
    return "\n".join(rows)


def erc_section(summary: dict) -> str:
    """The record's ERC section, quoting the envelope's own coverage block.

    Quotes ``erc_coverage`` and ``provenance.deck`` verbatim (issue #785's
    record contract), so a "clean" claim can never silently mean "clean
    under a tie that was skipped" or "run without the deck's device
    carve-outs".
    """
    if "erc" not in summary:
        return ""
    erc = summary["erc"]
    by_assertion = ", ".join(erc["ties_by_well_assertion"]) or "none"
    inapplicable = "; ".join(
        f"{entry['id']} ({entry['reason']})"
        if isinstance(entry, dict) else str(entry)
        for entry in erc["inapplicable"]
    ) or "none"
    deck = erc.get("deck") or {}
    deck_text = (
        f"`{deck.get('name')}` (content hash `{deck.get('content_hash')}`)"
        if deck.get("name") else "none"
    )
    control = summary.get("erc_control")
    control_par = ""
    if control:
        control_par = (
            "\nThe ERC negative control severed the declared tie's connection "
            f"({control['mutation']}) in a disposable copy of the committed "
            "GDS, ran it against the intact spec, and required exactly one "
            f"new `erc.missing_tie` on the declared tie (net "
            f"{', '.join(control['net']) or 'n/a'}). The intact layout's "
            "clean tie verdict is therefore falsifiable, not vacuous.\n"
        )
    nets_rows = "\n".join(
        f"| `{n['name']}` | {n['matched_islands']} | {n['expected_islands']} |"
        for n in erc["nets"]
    )
    return f"""
## The ERC supply run

Committed spec `{erc['spec']}` (emitted from the committed GDS by
`layout/erc/gen_spec.py`), report `{erc['report']}`. The verdict field read
is `erc_status`; the antenna half is `not_checked` by design on a
`--findings-only` run.

| Net | `matched_islands` | `expected_islands` |
| --- | --- | --- |
{nets_rows}

`erc_coverage`: `checked` includes `{', '.join(erc['ties_checked']) or 'none'}`;
`checked_by_well_assertion`: {by_assertion};
`skipped`: {erc['ties_skipped'] or 'none'};
`inapplicable`: {inapplicable};
`layers_in_stream_without_declaration`: {erc['layers_in_stream_without_declaration'] or 'none'}.
`provenance.deck`: {deck_text}; `provenance.klt_version`: `{erc.get('klt_version')}`.
{control_par}
"""
