"""Summaries, spec checks, and append-only evidence records.

The output format here is the one ratified in ``sim/README.md``: a run
produces a Markdown summary record at

    sim/<experiment-slug>/records/<record-id>.md

alongside a frozen netlist at ``netlist-snapshots/<record-id>.spice`` and the
raw per-corner ngspice logs at ``corners/<record-id>/<corner-id>.log``.

``<record-id>`` is ``<YYYYMMDD>-<HHMMSS>-<short-git-sha>``.

CLAUDE.md and ``sim/README.md``: "sim/ results are append-only evidence."
This module never overwrites an existing record -- on a collision it mints a
new (still conforming) record-id rather than clobbering, and corrections are
expected to reference the prior record via ``Supersedes``. Deleting evidence
is a human decision, not a script's.

This repo's ``sim/README.md`` adds one field bandgap's convention does not
need: **Operating conditions** (load current, output cap/ESR, enable state --
an LDO's spec lines are load- and output-network-conditioned; a bandgap has
no load pin). ``build_record``/``render_record`` below carry that field
through in the ratified position (after "Corner matrix run", before
"Statistical convention").
"""

from __future__ import annotations

import datetime as _dt
import getpass
import platform
import socket
import subprocess
import sys
from pathlib import Path

from . import HARNESS_VERSION
from .corners import (
    DEFAULT_SUPPLY_TOLERANCE,
    DEFAULT_TEMPERATURES_C,
    PvtPoint,
)
from .pdk import Pdk
from .runner import PointResult
from .testbench import Testbench

#: Subdirectories of ``sim/<experiment-slug>/`` defined by ``sim/README.md``.
TESTBENCH_DIR = "testbench"
SNAPSHOT_DIR = "netlist-snapshots"
CORNERS_DIR = "corners"
RECORDS_DIR = "records"

#: Minimum number of distinct process corners for the matrix to count as
#: "full" without a written justification.
MIN_PROCESS_CORNERS = 3


def _git(*args: str, cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
        )
        return out.stdout.strip()
    except OSError:  # pragma: no cover - git always present in this repo
        return ""


def git_provenance(repo_root: Path) -> dict:
    commit = _git("rev-parse", "HEAD", cwd=repo_root)
    dirty = bool(_git("status", "--porcelain", cwd=repo_root))
    return {
        "commit": commit or "unknown",
        "short": (commit[:7] if commit else "unknown"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root) or "unknown",
        "dirty": dirty,
    }


def format_record_id(short_sha: str, when: _dt.datetime) -> str:
    """``<YYYYMMDD>-<HHMMSS>-<short-git-sha>`` -- see ``sim/README.md``.

    The git sha is the *only* provenance carried in the id; a dirty tree is
    reported inside the record body instead, so the id keeps the exact shape
    the ratified convention specifies.
    """
    return f"{when.strftime('%Y%m%d-%H%M%S')}-{short_sha}"


def allocate_record_id(
    repo_root: Path,
    records_dir: Path,
    when: _dt.datetime | None = None,
    git: dict | None = None,
) -> str:
    """Mint a fresh, unused ``<record-id>``.

    Append-only: if a record with this id already exists (same second, same
    commit) we advance the timestamp until the id is free rather than
    overwriting or inventing a non-conforming suffix.
    """
    when = when or _dt.datetime.now(_dt.timezone.utc)
    short_sha = (git or git_provenance(repo_root))["short"]
    while True:
        record_id = format_record_id(short_sha, when)
        if not (records_dir / f"{record_id}.md").exists():
            return record_id
        when += _dt.timedelta(seconds=1)


def summarize(results: list[PointResult], measure_names: list[str]) -> dict:
    """Min / max / mean / spread of each measurement across the PVT grid."""
    summary: dict[str, dict] = {}
    ok = [r for r in results if r.status == "ok"]
    for name in measure_names:
        samples = [(r.measurements[name], r.point.corner_id) for r in ok if name in r.measurements]
        if not samples:
            summary[name] = {"n": 0}
            continue
        values = [v for v, _ in samples]
        lo_value, lo_at = min(samples, key=lambda s: s[0])
        hi_value, hi_at = max(samples, key=lambda s: s[0])
        mean = sum(values) / len(values)
        spread_pct = (hi_value - lo_value) / abs(mean) * 100.0 if mean else None
        summary[name] = {
            "n": len(values),
            "min": lo_value,
            "min_at": lo_at,
            "max": hi_value,
            "max_at": hi_at,
            "mean": mean,
            "spread_pct": spread_pct,
        }
    return summary


def evaluate_checks(
    checks: dict[str, dict],
    results: list[PointResult],
    summary: dict,
) -> list[dict]:
    """Return a list of check failures (empty list == everything passed)."""
    failures: list[dict] = []
    for name, spec in checks.items():
        low = spec.get("min")
        high = spec.get("max")
        if low is not None or high is not None:
            for result in results:
                if result.status != "ok" or name not in result.measurements:
                    continue
                value = result.measurements[name]
                if low is not None and value < low:
                    failures.append(
                        {
                            "measurement": name,
                            "kind": "min",
                            "limit": low,
                            "value": value,
                            "at": result.point.corner_id,
                        }
                    )
                if high is not None and value > high:
                    failures.append(
                        {
                            "measurement": name,
                            "kind": "max",
                            "limit": high,
                            "value": value,
                            "at": result.point.corner_id,
                        }
                    )
        # Grid-level spread checks. max_spread_pct is the usual "this must be
        # stable over PVT" assertion; min_spread_pct is its inverse and exists
        # to prove the harness is actually *moving* the corner -- a measurement
        # that is supposed to be strongly PVT-sensitive but comes back flat
        # means .temp / .lib never took effect.
        for kind, limit in (
            ("max_spread_pct", spec.get("max_spread_pct")),
            ("min_spread_pct", spec.get("min_spread_pct")),
        ):
            if limit is None:
                continue
            observed = (summary.get(name) or {}).get("spread_pct")
            violated = (
                observed is None
                or (kind == "max_spread_pct" and observed > limit)
                or (kind == "min_spread_pct" and observed < limit)
            )
            if violated:
                failures.append(
                    {
                        "measurement": name,
                        "kind": kind,
                        "limit": limit,
                        "value": observed,
                        "at": "grid",
                    }
                )
    return failures


def environment(pdk: Pdk, ngspice: str, repo_root: Path, git: dict | None = None) -> dict:
    """Reproducibility provenance for the record.

    ``git`` should be sampled *before* the run starts. The harness writes its
    own per-corner logs into the tracked evidence tree, so sampling afterwards
    would report every record as taken against a dirty tree.
    """
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - unusual environments
        user = "unknown"
    return {
        "harness_version": HARNESS_VERSION,
        "ngspice": ngspice,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "host": socket.gethostname(),
        "user": user,
        "pdk": pdk.provenance(),
        "git": git if git is not None else git_provenance(repo_root),
    }


def matrix_conformance(tb: Testbench, points: list[PvtPoint]) -> dict:
    """Is this run the full PVT matrix CLAUDE.md mandates, or a subset?

    ``sim/README.md`` requires every record's *Corner matrix run* field to be
    the full matrix (−40/27/125 °C, ±10 % supply, process corners) "unless the
    record states why a subset was used". This returns what is missing so the
    CLI can insist on a written justification instead of quietly recording a
    thinner run.
    """
    temps = {round(p.temp_c, 6) for p in points}
    supplies = {round(p.vdd, 6) for p in points}
    process = {p.corner.name for p in points}

    required_temps = {round(t, 6) for t in DEFAULT_TEMPERATURES_C}
    nominal = tb.nominal_supply_v
    required_supplies = {
        round(nominal * (1.0 - DEFAULT_SUPPLY_TOLERANCE), 6),
        round(nominal, 6),
        round(nominal * (1.0 + DEFAULT_SUPPLY_TOLERANCE), 6),
    }

    missing: list[str] = []
    if not required_temps <= temps:
        missing.append(
            "temperature: missing "
            + ", ".join(f"{t:g} C" for t in sorted(required_temps - temps))
        )
    if not required_supplies <= supplies:
        missing.append(
            "supply: missing "
            + ", ".join(f"{v:.2f} V" for v in sorted(required_supplies - supplies))
        )
    if len(process) < MIN_PROCESS_CORNERS:
        missing.append(
            f"process: only {len(process)} corner(s) "
            f"({', '.join(sorted(process))}); at least {MIN_PROCESS_CORNERS} expected"
        )

    return {"full": not missing, "missing": missing}


def build_record(
    tb: Testbench,
    pdk: Pdk,
    points: list[PvtPoint],
    results: list[PointResult],
    ngspice: str,
    repo_root: Path,
    record_id: str,
    started_utc: str,
    wall_seconds: float,
    claim: str = "",
    supersedes: str = "",
    statistical_convention: str = "",
    subset_reason: str = "",
    operating_conditions: dict[str, str] | None = None,
    git: dict | None = None,
) -> dict:
    measure_names = list(tb.measure)
    summary = summarize(results, measure_names)
    failures = evaluate_checks(tb.checks, results, summary)
    n_ok = sum(1 for r in results if r.status == "ok")

    if n_ok != len(results):
        status = "error"
    elif failures:
        status = "fail"
    else:
        status = "pass"

    corners = []
    seen = set()
    for point in points:
        if point.corner.name not in seen:
            seen.add(point.corner.name)
            corners.append(
                {
                    "name": point.corner.name,
                    "sections": list(point.corner.sections),
                    "description": point.corner.description,
                }
            )

    # CLI-supplied fields (--operating-conditions key=value) win over the
    # testbench manifest's defaults, same override precedence as --claim.
    resolved_oc = dict(tb.operating_conditions)
    if operating_conditions:
        resolved_oc.update(operating_conditions)

    return {
        "record_id": record_id,
        "experiment": tb.experiment,
        "status": status,
        "started_utc": started_utc,
        "wall_seconds": round(wall_seconds, 2),
        "claim": claim or tb.claim,
        "supersedes": supersedes,
        "statistical_convention": statistical_convention,
        "operating_conditions": resolved_oc,
        "subset_reason": subset_reason,
        "matrix": matrix_conformance(tb, points),
        "testbench": tb.provenance(repo_root),
        "environment": environment(pdk, ngspice, repo_root, git),
        "grid": {
            "corners": corners,
            "temperatures_c": sorted({p.temp_c for p in points}),
            "supplies_v": sorted({p.vdd for p in points}),
            "points": len(points),
            "points_ok": n_ok,
        },
        "measure": dict(tb.measure),
        "checks": {
            "spec": tb.checks,
            "passed": not failures,
            "failures": failures,
        },
        "summary": summary,
        "points": [r.as_dict() for r in results],
    }


def _fmt(value) -> str:
    """Human-readable scalar for the Markdown record."""
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if value != 0 and (abs(value) < 1e-3 or abs(value) >= 1e5):
            return f"{value:.6e}"
        return f"{value:.6g}"
    return str(value)


class RecordExists(RuntimeError):
    """Refused to overwrite an existing append-only record."""


def write_netlist_snapshot(tb: Testbench, experiment_dir: Path, record_id: str) -> Path:
    """Freeze the DUT netlist for this record.

    ``sim/README.md``: ``netlist-snapshots/<record-id>.spice`` is "the frozen
    DUT netlist used for this record", so later edits to ``testbench/`` never
    change what an existing record refers to.

    When the manifest names design netlists (``dut_netlist`` and/or
    ``includes``), the DUT is spread across several files. They are
    concatenated into the same single snapshot file -- the designated DUT
    first, then the other design cells in include order, then the testbench
    fragment -- each behind a header naming its source path and sha256. That
    keeps the ratified one-snapshot-per-record shape while still freezing
    everything the record's numbers depend on: the DUT (the netlist most
    likely to change between records -- a new error amp, an extracted
    post-layout re-run for #16) *and* the stimulus that produced them.
    Testbenches with no design netlist at all (e.g. smoke-bias) snapshot just
    the fragment, as before.
    """
    repo_root = experiment_dir.parent.parent
    out_dir = experiment_dir / SNAPSHOT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{record_id}.spice"
    if path.exists():
        raise RecordExists(f"{path} already exists; append-only evidence is never rewritten")

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(repo_root))
        except ValueError:
            return str(p)

    chunks = [
        "\n".join(
            [
                f"* Frozen netlist snapshot for record {record_id}",
                "* This is a verbatim copy taken at record time. Do not edit.",
                "",
            ]
        )
    ]
    for entry, source in zip(tb.include_provenance(repo_root), tb.design_netlists):
        label = "DUT netlist" if source == tb.dut_netlist else "included design cell"
        chunks.append(
            "\n".join(
                [
                    "* ======================================================================",
                    f"* {label:<21}: {entry['path']}",
                    f"* sha256               : {entry['sha256']}",
                    "* ======================================================================",
                    "",
                ]
            )
            + source.read_text()
        )
    chunks.append(
        "\n".join(
            [
                "* ======================================================================",
                f"* testbench fragment   : {_rel(tb.netlist)}",
                f"* sha256               : {tb.netlist_sha256}",
                "* ======================================================================",
                "",
            ]
        )
        + tb.netlist.read_text()
    )
    path.write_text("\n".join(chunks))
    return path


def _corner_matrix_lines(record: dict) -> list[str]:
    grid = record["grid"]
    lines = [
        "- **Corner matrix run**:",
        "  - Process: " + ", ".join(c["name"] for c in grid["corners"]),
        "  - Temperature: " + ", ".join(f"{t:g} °C" for t in grid["temperatures_c"]),
        "  - Supply: " + ", ".join(f"{v:.2f} V" for v in grid["supplies_v"]),
        f"  - {grid['points']} point full-factorial grid "
        f"(process × temperature × supply), {grid['points_ok']} completed",
    ]
    if record["matrix"]["full"]:
        lines.append(
            "  - Full PVT matrix per CLAUDE.md (−40/27/125 °C, ±10 % supply, "
            "process corners)."
        )
    else:
        lines.append("  - **Subset of the mandated PVT matrix.** Gaps: "
                     + "; ".join(record["matrix"]["missing"]) + ".")
        lines.append("  - Justification: " + record["subset_reason"])
    return lines


def _operating_conditions_lines(record: dict) -> list[str]:
    """LDO-specific extension to sim/README.md's record (bandgap has none).

    Renders whatever key/value pairs the testbench manifest (or a
    ``--operating-conditions`` CLI override) supplied. Falls back to an
    explicit "not stated" line rather than silently omitting the field --
    sim/README.md requires the field to *say* it does not apply, not just
    leave it out, for claims that are load-dependent.
    """
    oc = record.get("operating_conditions") or {}
    lines = ["- **Operating conditions**:"]
    if not oc:
        lines.append(
            "  - Not stated by the testbench manifest. Acceptable only when this "
            "claim is provably load-independent (see sim/README.md); otherwise "
            "the testbench should set `operating_conditions` (load current, "
            "output cap/ESR, enable state)."
        )
        return lines
    for key, value in oc.items():
        label = key.replace("_", " ").strip()
        label = label[:1].upper() + label[1:] if label else label
        lines.append(f"  - {label}: {value}")
    return lines


def _result_lines(record: dict) -> list[str]:
    measure_names = list(record["measure"])
    failures_at: dict[str, list[str]] = {}
    for failure in record["checks"]["failures"]:
        failures_at.setdefault(failure["at"], []).append(
            f"{failure['measurement']} {failure['kind']}={_fmt(failure['limit'])} "
            f"(got {_fmt(failure['value'])})"
        )

    lines = ["- **Result**:", ""]
    lines.append("  | corner-id | " + " | ".join(measure_names) + " | pass/fail |")
    lines.append("  |---|" + "---|" * (len(measure_names) + 1))
    for point in record["points"]:
        cells = [_fmt(point["measurements"].get(name)) for name in measure_names]
        problems = failures_at.get(point["corner_id"], [])
        if point["status"] != "ok":
            verdict = f"ERROR — {point.get('message', point['status'])}"
        elif problems:
            verdict = "FAIL — " + "; ".join(problems)
        else:
            verdict = "PASS"
        lines.append(f"  | `{point['corner_id']}` | " + " | ".join(cells) + f" | {verdict} |")

    grid_failures = failures_at.get("grid", [])
    if grid_failures:
        lines.append("")
        lines.append("  Grid-level check failures: " + "; ".join(grid_failures) + ".")

    lines.append("")
    lines.append("  Spread across the grid:")
    lines.append("")
    lines.append("  | measurement | min | max | mean | spread % | limits |")
    lines.append("  |---|---|---|---|---|---|")
    for name, stats in record["summary"].items():
        spec = record["checks"]["spec"].get(name, {})
        limits = ", ".join(
            f"{key}={_fmt(spec[key])}"
            for key in ("min", "max", "max_spread_pct", "min_spread_pct")
            if key in spec
        ) or "—"
        if not stats.get("n"):
            lines.append(f"  | `{name}` | no data | | | | {limits} |")
            continue
        lines.append(
            f"  | `{name}` | {_fmt(stats['min'])} (`{stats['min_at']}`) "
            f"| {_fmt(stats['max'])} (`{stats['max_at']}`) "
            f"| {_fmt(stats['mean'])} | {_fmt(stats['spread_pct'])} | {limits} |"
        )

    verdict = {"pass": "PASS", "fail": "FAIL", "error": "ERROR"}[record["status"]]
    lines.append("")
    lines.append(f"  - **Overall: {verdict}**")
    return lines


def render_record(record: dict, experiment: str) -> str:
    """Render the ratified ``records/<record-id>.md`` summary.

    Field set and order follow ``sim/README.md``: Record ID, Claim, Netlist
    provenance, Corner matrix run, Operating conditions (LDO-specific
    extension), Statistical convention, Result, Links, Timestamp / author,
    Supersedes.
    """
    record_id = record["record_id"]
    env = record["environment"]
    tb = record["testbench"]
    git = env["git"]
    pdk = env["pdk"]

    # `includes` (#35) lists every design netlist frozen into this record;
    # `dut_netlist` (#12) names which of them is the DUT, and whether it came
    # from the schematic or from an extracted layout. The DUT is always the
    # first entry of `includes` when set (Testbench.design_netlists), so
    # `other_includes` is the supporting design cells around it.
    includes = tb.get("includes") or []
    dut_netlist_rel = tb.get("dut_netlist")
    other_includes = [entry for entry in includes if entry["path"] != dut_netlist_rel]
    if includes:
        kind = "extracted" if (dut_netlist_rel or "").startswith("layout/") else "schematic"
        provenance = (
            f"{kind} ("
            + ", ".join(f"`{entry['path']}`" for entry in includes)
            + f"), driven by `sim/{experiment}/{TESTBENCH_DIR}/{tb['netlist']}`"
        )
    else:
        provenance = f"schematic (`sim/{experiment}/{TESTBENCH_DIR}/{tb['netlist']}`)"
    if git["dirty"]:
        provenance += (
            f" — **taken against a dirty working tree** at commit `{git['commit']}`; "
            "not citable as a clean-tree result"
        )

    lines = [
        f"# Record {record_id}",
        "",
        f"- **Record ID**: {record_id}",
        f"- **Claim**: {record['claim'] or 'harness self-verification — no spec claim'}",
        f"- **Netlist provenance**: {provenance}",
    ]
    lines += _corner_matrix_lines(record)
    lines += _operating_conditions_lines(record)
    lines.append(
        "- **Statistical convention**: "
        + (record["statistical_convention"]
           or "N/A (corner-matrix claim, not a distribution claim)")
    )
    lines += _result_lines(record)
    lines += [
        "- **Links**:",
        f"  - Testbench: `sim/{experiment}/{TESTBENCH_DIR}/{tb['netlist']}`, "
        f"`sim/{experiment}/{TESTBENCH_DIR}/tb.json`",
    ]
    if dut_netlist_rel:
        lines.append(f"  - DUT netlist: `{dut_netlist_rel}`")
    if other_includes:
        lines.append(
            "  - Design cells: " + ", ".join(f"`{entry['path']}`" for entry in other_includes)
        )
    lines += [
        f"  - Netlist snapshot: `sim/{experiment}/{SNAPSHOT_DIR}/{record_id}.spice`",
        f"  - Raw logs: `sim/{experiment}/{CORNERS_DIR}/{record_id}/`",
        f"- **Timestamp / author**: {record['started_utc']}, {env['user']}",
        f"- **Supersedes**: {record['supersedes'] or '(none)'}",
        "",
        "## Environment",
        "",
        "Everything needed to re-run this record:",
        "",
        f"- PDK: {pdk.get('variant')} @ open_pdks `{pdk.get('open_pdks_version')}`"
        f" ({pdk.get('path')}, found via {pdk.get('discovered_via')})",
        f"- ngspice: {env['ngspice']}",
        f"- Harness: sim/harness {env['harness_version']}, python {env['python']}",
        f"- git: `{git['commit']}` on `{git['branch']}`"
        + (" (dirty)" if git["dirty"] else " (clean)"),
        f"- Testbench netlist sha256: `{tb['netlist_sha256']}`",
    ]
    if tb.get("dut_netlist_sha256"):
        lines.append(f"- DUT netlist sha256: `{tb['dut_netlist_sha256']}`")
    lines += [
        f"- Manifest sha256: `{tb['manifest_sha256']}`",
    ]
    for entry in other_includes:
        lines.append(f"- Included design netlist `{entry['path']}` sha256: `{entry['sha256']}`")
    lines += [
        f"- Wall time: {record['wall_seconds']} s",
        "",
        "Per-corner model sections used:",
        "",
    ]
    for corner in record["grid"]["corners"]:
        lines.append(f"- `{corner['name']}`: {' '.join(corner['sections'])}")
    lines += [
        "",
        "---",
        "",
        "Written by `sim/run_corners.py`. Append-only: never edit or delete this",
        "file — a re-run or correction mints a new record-id and points back here",
        "via **Supersedes** (see `sim/README.md`).",
        "",
    ]
    return "\n".join(lines)


def write_record(record: dict, experiment_dir: Path) -> Path:
    """Write ``records/<record-id>.md``; never overwrite an existing record."""
    out_dir = experiment_dir / RECORDS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{record['record_id']}.md"
    if path.exists():
        raise RecordExists(
            f"{path} already exists; records are append-only -- mint a new record-id"
        )
    path.write_text(render_record(record, experiment_dir.name))
    return path
