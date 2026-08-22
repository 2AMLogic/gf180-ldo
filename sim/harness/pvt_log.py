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

import pathlib
import re
from collections.abc import Callable, Sequence

# ngspice `print`s a length-1 vector measurement as "m_foo = 1.234e+00",
# sometimes with trailing `targ=`/`trig=`/`at=` context on the same line
# (soft-start's .meas TRIG/TARG lines) that this pattern deliberately does
# not anchor past -- only the first `=`-delimited token is a measurement.
_MEAS_RE = re.compile(r"^(m_\w+)\s*=\s*([-+0-9.eE]+)")


def read_measurements(log: pathlib.Path, scalars: Sequence[str]) -> dict[str, float]:
    """Parse ``log``'s ``m_name = value`` lines into a ``{name: value}`` dict.

    Fails loud (``SystemExit``) rather than swallowing a malformed value --
    silently dropping an unparsable measurement previously masked the
    resulting "missing measurement" as if the line had never been printed
    at all, instead of naming the value that failed to parse.

    Also fails loud, as before, if any of ``scalars`` is absent from the
    parsed log: a missing measurement is a bench error, not a result.
    """
    vals: dict[str, float] = {}
    for line in log.read_text().splitlines():
        m = _MEAS_RE.match(line)
        if not m:
            continue
        try:
            vals[m.group(1)] = float(m.group(2))
        except ValueError:
            raise SystemExit(
                f"FATAL: {log.name} has an unparsable value for "
                f"{m.group(1)}: {m.group(2)!r}"
            ) from None
    missing = [s for s in scalars if s not in vals]
    if missing:
        raise SystemExit(f"FATAL: {log.name} is missing measurements: {missing}")
    return vals


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
