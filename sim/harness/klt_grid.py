"""Shared driver policy for ``klt sim`` PVT grids (issue #492).

The two loop-sweep scripts (``sim/loop-stability`` and
``sim/soft-start-loop-gain``) submit a whole PVT grid through ``klt sim``,
parse one log per work unit, and apply one retry policy. Only the key shape
(corner vs corner/variant/phase), the DC-branch-miss marker and the klt entry
point differ, so the state machine and the backend preamble live here and each
sweep keeps its own print format via callbacks.
"""

from __future__ import annotations

import sys
from typing import Callable, Hashable, Iterable


def select_backend(requested: str | None, n_pvt: int) -> tuple[str, bool] | None:
    """Resolve ``--backend`` to ``(backend, use_klt)``.

    ``None`` requested means ``local`` for a single PVT point and ``batch``
    otherwise. ``klt-local`` is a single-PVT-point check only: on a larger
    grid this prints the FATAL line and returns ``None`` (the caller exits 3).
    """
    backend = requested or ("local" if n_pvt == 1 else "batch")
    if backend == "klt-local" and n_pvt > 1:
        print(f"FATAL: --backend klt-local is a single-PVT-point check; this grid is "
              f"{n_pvt} PVT points. Use --backend batch.", file=sys.stderr)
        return None
    return backend, backend in ("batch", "klt-local")


def run_retry_grid(
    keys: Iterable[Hashable],
    results,
    bad,
    *,
    parse: Callable,
    run_retry: Callable,
    miss_marker: str,
    name: Callable[[Hashable], str],
    bad_key: Callable[[Hashable], Hashable],
    bad_message: str,
    retry_problem: Callable[[str | None, list[str]], str],
    say: Callable[[Hashable, str, str], None],
    report: Callable[[Hashable, list, str], None],
    void_on_miss: bool = False,
):
    """Parse every work unit; re-run DC-branch misses once, seeded.

    ``parse(key, results, suffix) -> (rows, err)`` writes the log and parses
    it. A unit whose ``bad_key(key)`` is in ``bad`` is one klt itself flagged (failed job, errored pass):
    not a DC-branch miss, so it is never retried. A unit whose ``err`` contains
    ``miss_marker`` is queued and re-run through ``run_retry(key) ->
    (results, problems)``; ``void_on_miss`` records a seeded unit that still
    misses as voided instead of failed. ``say(key, event, detail)`` is called
    for ``retry``/``error``/``voided`` events and ``report(key, rows, note)``
    for each unit that lands, so callers keep their own print format.

    Returns ``(rows, failures, seeded, voided)``.
    """
    rows: list = []
    failures: list[str] = []
    seeded: list[str] = []
    voided: list[str] = []
    retries = []
    for key in keys:
        pt_rows, err = parse(key, results, "")
        if bad_key(key) in bad:
            err = bad_message
        if err and miss_marker in err:
            retries.append(key)
            say(key, "retry", "")
        elif err:
            failures.append(f"{name(key)}: {err}")
            say(key, "error", err)
        else:
            rows.extend(pt_rows)
            report(key, pt_rows, "")

    for key in retries:
        res, probs = run_retry(key)
        for p in probs:
            print(f"  WARNING {p}", file=sys.stderr)
        pt_rows, err = parse(key, res, "_dcseed")
        if probs:
            err = retry_problem(err, probs)
        if err and void_on_miss and miss_marker in err:
            voided.append(f"{name(key)}: {err}")
            say(key, "voided", err)
        elif err:
            failures.append(f"{name(key)} (with DC seed): {err}")
            say(key, "error", err)
        else:
            seeded.append(name(key))
            rows.extend(pt_rows)
            report(key, pt_rows, "  [DC seed]")
    return rows, failures, seeded, voided
