"""Shared driver policy for ``klt sim`` PVT grids (issue #492).

The two loop-sweep scripts (``sim/loop-stability`` and
``sim/soft-start-loop-gain``) submit a whole PVT grid through ``klt sim``,
parse one log per work unit, and apply one retry policy. Only the key shape
(corner vs corner/variant/phase), the DC-branch-miss marker and the klt entry
point differ, so the state machine and the backend preamble live here and each
sweep keeps its own print format via callbacks.

The CLI block that *selects* that policy lives here too (``DEFAULT_JOBS`` and
``add_grid_args``, issue #621) -- it was duplicated in both sweeps and its help
text had drifted apart in four places.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, Hashable, Iterable

#: Default local worker count. Capped at 2 rather than ``os.cpu_count()``
#: (issue #366): these drivers are run on shared dispatch workers where a grid
#: that defaults to every core starves other sweeps. Pass ``-j`` to raise it on
#: a box you own. One definition for every driver that fans ngspice out
#: locally, so the cap cannot reach some of them and miss the rest (issue
#: #621).
DEFAULT_JOBS = min(2, os.cpu_count() or 2)


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


def add_grid_args(ap: argparse.ArgumentParser, *, batch_unit: str,
                  batch_extra: str = "") -> None:
    """Register the local-grid CLI block shared by the two loop sweeps.

    One definition of ``--backend``, ``--in-flight``, ``-j/--jobs``,
    ``--no-write``, ``--subset-reason`` and ``--supersedes`` (issue #621):
    these select the policy this module already implements, so their help text
    lives next to it rather than in a per-sweep copy that drifts.

    ``batch_unit`` names what one ``klt sim`` request covers for this bench
    (e.g. ``"(load, C_eff, ESR) configuration"``) and ``batch_extra`` appends
    any bench-specific clause to the ``batch`` sentence -- the only genuinely
    per-bench parts of the ``--backend`` help. Each sweep adds its own
    bench-specific flags itself.
    """
    ap.add_argument("--backend", choices=("local", "batch", "klt-local"), default=None,
                    help=f"where the grid runs (issues #366, #451). `batch`: "
                         f"each {batch_unit} is a `klt sim` request over the "
                         "PVT grid, submitted to the Spot batch fleet "
                         f"(klt_run.py){batch_extra} -- the default for any "
                         "grid of more than one PVT point, as the "
                         "dispatch-worker rule requires. `local` fans ngspice "
                         "out on THIS host and must be passed explicitly for "
                         "more than one PVT point. `klt-local` runs the same "
                         "`klt sim` requests as `batch` but locally, one at a "
                         "time, for a single-PVT-point batch-vs-local check "
                         "only. A single-PVT run (e.g. --explore) is `local` "
                         "without the flag. A failed batch submit is an "
                         "error; it never falls back to a local grid.")
    ap.add_argument("--in-flight", type=int, default=6,
                    help="with --backend batch, how many configuration "
                         "requests are submitted at once (default: 6; the "
                         "fleet's own concurrency cap re-queues the rest)")
    ap.add_argument("-j", "--jobs", type=int, default=DEFAULT_JOBS,
                    help=f"local worker threads (default: {DEFAULT_JOBS}, "
                         "deliberately not os.cpu_count(): dispatch workers "
                         "are shared). Only meaningful with --backend local.")
    ap.add_argument("--no-write", action="store_true",
                    help="run and report, write no record (debugging)")
    ap.add_argument("--subset-reason", default="",
                    help="required (and copied into the record) if the PVT "
                         "grid is narrower than the CLAUDE.md-mandated matrix")
    ap.add_argument("--supersedes", default="",
                    help="record-id this run supersedes")


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
