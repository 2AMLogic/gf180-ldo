"""Shared per-corner ngspice log rollup helpers for standalone summarize.py
scripts.

Three testbenches (current-limit, enable-shutdown, soft-start) each carried
an independent "parse a per-corner log into a measurement dict, validate the
required scalars are all present, report min/max across corners, flag
out-of-bound corners" pipeline. The three copies had already drifted --
current-limit's parser raised an uncaught ``ValueError`` traceback on a
malformed measurement instead of a ``FATAL:`` message, while
enable-shutdown/soft-start silently swallowed the same error -- so this
module is the one canonical implementation, following the same
``sys.path.insert(0, str(REPO_ROOT / "sim"))`` + ``from harness.X import Y``
pattern ``sim/loop-stability/testbench/sweep.py`` already uses for the
harness proper.

Each testbench's own ``SCALARS`` list, CSV schema, and pass/fail thresholds
stay in that testbench's ``summarize.py`` -- those are legitimately
testbench-specific, not duplicated boilerplate.
"""

from __future__ import annotations

import math
import pathlib
import re
from collections.abc import Callable, Sequence
from typing import NamedTuple

# ngspice `print`s a length-1 vector measurement as "m_foo = 1.234e+00",
# sometimes with trailing `targ=`/`trig=`/`at=` context on the same line
# (soft-start's .meas TRIG/TARG lines) that this pattern deliberately does
# not anchor past -- only the first `=`-delimited token is a measurement.
# A `.meas` that never triggered prints `failed` in place of the number.
_MEAS_RE = re.compile(r"^\s*(m_\w+)\s*=\s*([-+0-9.eE]+|failed)")


class MeasParse(NamedTuple):
    """Result of :func:`parse_meas_lines`; every name keeps its ``m_`` prefix."""

    values: dict[str, float]  # finite measurements
    nonfinite: list[str]  # numeric token that overflowed to inf/nan (e.g. 1e999)
    failed: list[str]  # `.meas` printed `failed`
    unparsable: dict[str, str]  # name -> raw token ``float()`` rejected


def parse_meas_lines(text: str) -> MeasParse:
    """Single definition of a valid ngspice ``m_name = value`` line.

    Tolerates leading whitespace and trailing ``targ=``/``trig=`` context.
    A later line for the same name replaces an earlier one, so a name is
    reported in at most one of the four result fields.
    """
    values: dict[str, float] = {}
    nonfinite: list[str] = []
    failed: list[str] = []
    unparsable: dict[str, str] = {}
    for line in text.splitlines():
        m = _MEAS_RE.match(line)
        if not m:
            continue
        name, token = m.group(1), m.group(2)
        values.pop(name, None)
        unparsable.pop(name, None)
        for bucket in (nonfinite, failed):
            if name in bucket:
                bucket.remove(name)
        if token == "failed":
            failed.append(name)
            continue
        try:
            value = float(token)
        except ValueError:
            unparsable[name] = token
            continue
        if math.isfinite(value):
            values[name] = value
        else:
            nonfinite.append(name)
    return MeasParse(values, nonfinite, failed, unparsable)


def read_measurements(log: pathlib.Path, scalars: Sequence[str]) -> dict[str, float]:
    """Parse ``log``'s ``m_name = value`` lines into a ``{name: value}`` dict.

    Fails loud (``SystemExit``) rather than swallowing a malformed value --
    silently dropping an unparsable measurement previously masked the
    resulting "missing measurement" as if the line had never been printed
    at all, instead of naming the value that failed to parse.

    Also fails loud, as before, if any of ``scalars`` is absent from the
    parsed log: a missing measurement is a bench error, not a result.
    """
    parsed = parse_meas_lines(log.read_text())
    for name, token in parsed.unparsable.items():
        raise SystemExit(
            f"FATAL: {log.name} has an unparsable value for {name}: {token!r}"
        )
    if parsed.nonfinite:
        name = parsed.nonfinite[0]
        raise SystemExit(f"FATAL: {log.name} has a non-finite value for {name}")
    vals = parsed.values
    missing = [s for s in scalars if s not in vals]
    if missing:
        raise SystemExit(f"FATAL: {log.name} is missing measurements: {missing}")
    return vals


def grid_rollup(
    log_dir: pathlib.Path,
    corners: str,
    temps: str,
    supplies: str,
    scalars: Sequence[str],
    derive: Callable[[dict], None],
) -> list[tuple]:
    """Read ``<log_dir>/<corner>_<temp>c_<vin>v.log`` for every point of the
    full-factorial ``corners x temps x supplies`` grid and return
    ``(cid, corner, temp, vin, vals)`` rows. ``derive(vals)`` adds the
    testbench's derived columns to each point's ``vals`` in place.
    Pure: no printing, no writing.

    Fails loud on a missing log (``FileNotFoundError``), on a log with a
    missing or unparsable measurement (``SystemExit``, via
    ``read_measurements``), and on an empty grid -- every grid point is
    required.
    """
    rows = []
    for c in corners.split():
        for t in temps.split():
            for v in supplies.split():
                cid = "%s_%sc_%.2fv" % (c, t, float(v))
                vals = read_measurements(pathlib.Path(log_dir) / f"{cid}.log", scalars)
                derive(vals)
                vals["_vin"] = float(v)
                rows.append((cid, c, t, v, vals))
    if not rows:
        raise SystemExit("FATAL: empty corner grid")
    return rows


def write_corner_csv(rows: Sequence[tuple], csv_path, csv_cols: Sequence[str]) -> None:
    """Write ``rows`` (as returned by ``grid_rollup``) to ``csv_path`` with one
    ``corner_id,corner,temp_c,vin_v`` prefix plus ``csv_cols`` per point
    (header drops each column's ``m_`` prefix)."""
    with open(csv_path, "w") as fh:
        fh.write("corner_id,corner,temp_c,vin_v," + ",".join(c[2:] for c in csv_cols) + "\n")
        for cid, c, t, v, vals in rows:
            fh.write(f"{cid},{c},{t},{v}," + ",".join(f"{vals[k]:.6g}" for k in csv_cols) + "\n")


def report_minmax(
    rows: Sequence[tuple],
    name: str,
    scale: float = 1.0,
    unit: str = "",
    name_width: int = 20,
    cid_width: int = 20,
    val_width: int = 11,
    val_prec: int = 4,
) -> None:
    """Print the min/max of measurement ``name`` across ``rows``.

    ``rows`` is a sequence of ``(corner_id, ..., vals)`` tuples where
    ``vals`` is the last element and is a ``{name: value}`` dict (the shape
    every ``summarize.py``'s ``rows`` list already uses). Generalized from
    soft-start's ``rep(name, scale, unit)``; the width/precision knobs let
    each testbench keep its own already-committed column alignment (the
    three copies had already drifted on those before this consolidation --
    that drift is cosmetic, not behavioral, and is deliberately preserved
    rather than papered over here).
    """
    vs = [(row[0], row[-1][name] * scale) for row in rows]
    lo = min(vs, key=lambda x: x[1])
    hi = max(vs, key=lambda x: x[1])
    print(
        f"  {name[2:]:{name_width}s} min {lo[1]:{val_width}.{val_prec}f}{unit}"
        f" @ {lo[0]:{cid_width}s}  max {hi[1]:{val_width}.{val_prec}f}{unit}"
        f" @ {hi[0]}"
    )


def report_flag(
    rows: Sequence[tuple],
    label: str,
    pred: Callable[[dict], bool],
    max_shown: int = 6,
    label_width: int = 56,
) -> None:
    """Print the corner ids where ``pred(vals)`` holds, truncated past
    ``max_shown`` (soft-start's already-generalized ``flag()``, which
    enable-shutdown's un-truncated copy had drifted from -- applying the
    truncation there uniformly is one of the two documented behavioral
    fixes this consolidation makes)."""
    bad = [row[0] for row in rows if pred(row[-1])]
    n = len(bad)
    shown = bad if n <= max_shown else bad[:max_shown] + [f"... (+{n - max_shown} more)"]
    print(f"  {label:{label_width}s} {shown or 'none'}")
