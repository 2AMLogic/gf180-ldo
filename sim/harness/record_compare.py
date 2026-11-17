"""Matrix-record comparison helpers shared by the benches (issue #630).

The numeric parsing (``inf`` in a gain-margin column is a *value* -- "no -180
deg crossing in band" -- not a parse failure), the ``inf - inf == 0`` delta
rule, the ``resurgence_db`` AC_DEC-comparability tolerance issue #69
established, the delta-CSV writer that is the parser's inverse, and the
median/p99 summary statistics were defined in
``sim/loop-stability/testbench/compare_records.py``; a second bench
(``sim/soft-start-loop-gain/``) needs the same meanings, and reached them by
loading that file by filesystem path. They live here instead, imported by
name by both benches, so the two experiments cannot disagree about what a
delta means or about how one is written to a committed record.

What stays per-bench is the join key: a point of one experiment is not a
point of another, so each bench's ``compare_records.py`` passes its own
``key_fields`` and ``records_dir`` to :func:`load`.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Callable
from pathlib import Path

# resurgence_db's AC_DEC-invariance tolerance (issue #69) -- must match
# sim/loop-stability/testbench/selftest.py's MAX_INVARIANCE_ERR_DB, which is
# where this budget is derived and exercised. A per-point movement inside this
# budget is expected grid quantization near the metric's fixed scan-start
# offset; a movement beyond it is a signal worth investigating (different
# AC_DEC on a pre-#69 record, or a genuine change in the loop).
RESURGENCE_AC_DEC_TOLERANCE_DB = 1.75


def parse_num(tok: str) -> float | None:
    """Parse a matrix-CSV numeric cell, including the sentinels it uses.

    ``inf`` is a real, meaningful value in the gain-margin column (the loop
    phase never reaches -180 deg in band), not a parse failure. ``n/a`` and
    empty are genuinely absent quantities and come back as ``None`` so a
    delta against them is never computed.
    """
    tok = tok.strip()
    if tok in ("", "n/a"):
        return None
    if tok == "inf":
        return math.inf
    try:
        return float(tok)
    except ValueError:
        return None


def load(
    record_id: str,
    key_fields: tuple[str, ...],
    records_dir: Path,
) -> dict[tuple, dict]:
    path = records_dir / f"{record_id}-matrix.csv"
    if not path.exists():
        raise SystemExit(f"FATAL: no such matrix CSV: {path}")
    out: dict[tuple, dict] = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            key = tuple(row[f] for f in key_fields)
            if key in out:
                raise SystemExit(f"FATAL: duplicate key {key} in {path}")
            out[key] = row
    if not out:
        raise SystemExit(f"FATAL: {path} has no rows")
    return out


def delta(a: float | None, b: float | None) -> float | None:
    """b - a, with ``inf`` handled as the value it actually is.

    ``inf - inf`` is 0 here (both records say "no -180 deg crossing in band",
    which is agreement, not an indeterminate form), while a finite-vs-infinite
    pair is genuinely unbounded and comes back as ``None`` -- the flip itself
    is reported separately as a verdict change.
    """
    if a is None or b is None:
        return None
    if math.isinf(a) and math.isinf(b):
        return 0.0
    if math.isinf(a) or math.isinf(b):
        return None
    return b - a


def fmt(v: float | None, nd: int = 2) -> str:
    if v is None:
        return ""
    if math.isinf(v):
        return "inf"
    return f"{v:.{nd}f}"


def write_delta_csv(rows: list[dict], out: Path) -> None:
    """Write the per-point delta rows to ``out`` as the committed delta CSV.

    This is the inverse of :func:`parse_num` and is shared for the same
    reason ``parse_num`` is: it is what decides that an infinite gain margin
    is written ``inf``, an absent quantity an empty cell, and any other float
    ``%.6g``. Its output is append-only evidence under ``records/``, so the
    experiments that write it must not be able to drift apart on how a cell
    is spelled.
    """
    cols = list(rows[0].keys())
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow([
                "" if r[c] is None
                else ("inf" if isinstance(r[c], float) and math.isinf(r[c])
                      else (f"{r[c]:.6g}" if isinstance(r[c], float) else r[c]))
                for c in cols
            ])


def spread(
    rows: list[dict],
    field: str,
    label: str,
    unit: str,
    where: Callable[[dict], str],
    nd: int = 3,
) -> None:
    """Print median / p99 / max of ``|row[field]|`` over the comparable points.

    Shared by every experiment that summarises a record-to-record comparison,
    so "median" and "p99" cannot come to mean different indices in two scripts
    whose summaries a reader expects to compare. ``where`` renders the worst
    point in whatever coordinates the calling experiment uses. Points whose
    delta is ``None`` are not comparable: they are excluded from the statistics
    and counted in the line instead of being silently dropped.
    """
    vals = [(abs(r[field]), r) for r in rows if r[field] is not None]
    n_none = len(rows) - len(vals)
    if not vals:
        print(f"  {label}: no comparable points")
        return
    vals.sort(key=lambda t: t[0])
    worst = vals[-1][1]
    med = vals[len(vals) // 2][0]
    p99 = vals[int(0.99 * (len(vals) - 1))][0]
    print(f"  {label}: median {med:.{nd}f} {unit}, p99 {p99:.{nd}f} {unit}, "
          f"max {vals[-1][0]:.{nd}f} {unit} at {where(worst)}"
          f"{'' if not n_none else f'  ({n_none} points not comparable)'}")
