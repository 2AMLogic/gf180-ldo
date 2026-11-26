#!/usr/bin/env python3
"""Loop-stability sweep driver for issue #10.

Runs the Tian dual-injection loop-gain testbench
(``tb_loop_stability.spice.in``) over the full matrix ratified in
``spec/decision-records/DR-0001-output-cap-strategy.md``:

    I_load in {0, 0.1, 1, 10, 25, 50} mA
    C_eff  in {0.33, 1.0, 4.7} uF
    ESR    in {0.001, 0.05, 0.2, 0.5} ohm
    T      in {-40, 27, 125} degC
    Vin    in {2.97, 3.3, 3.63} V
    process in {tt, ff, ss, fs, sf, res_ff, res_ss}
    = 4536 loop-gain points

    ``res_ff``/``res_ss`` were added by issue #54: since #51/#56 recompensated
    the loop as a Type-II gain shelf, ``Rz`` (a ``ppolyf_u_1k`` resistor) sets
    both the shelf gain and the shelf corner frequency, so it is a first-order
    compensation parameter rather than a second-order one -- and
    `sim/devchar/CONCLUSIONS.md` section 2 puts `ppolyf_u_1k`'s process
    (ff/ss) spread at ~40%, close to the ~17% margin the measured pass/fail
    boundary in `Rz` leaves. These two corners follow the same
    ``CORNERS="tt ff ss fs sf res_ff res_ss"`` seven-process set as the
    harness's PVT grid (``sim/harness/klt_batch.py``'s ``LDO_PROCESS``, from
    ``sim/harness/corners.py``'s ``CORNERS``); ``bjt_ff``/``bjt_ss``
    are omitted from that set for the same reason they are omitted here -- this
    design has no bipolar devices in the loop.

The load x cap x ESR axes are swept *inside* one ngspice deck per PVT point
(a ``foreach`` loop with ``alter``), so the whole matrix is 63 ngspice
invocations, not 4536. One raw log per PVT point lands under
``corners/<record-id>/<corner-id>.log`` -- the naming ratified in
``sim/README.md`` -- with one ``ROW`` line per (load, cap, ESR) config.

Output, per ``sim/README.md``:

    netlist-snapshots/<record-id>.spice        frozen DUT netlist
    corners/<record-id>/<corner-id>.log        raw ngspice output (63 files)
    corners/<record-id>/<worst>_curve.log      full T(f) curve at the worst point
    records/<record-id>-matrix.csv             all 4536 points, machine-readable
    records/<record-id>.md                     the append-only summary record

Nothing under ``records/``, ``corners/`` or ``netlist-snapshots/`` is ever
overwritten: a re-run mints a new record-id.

Usage::

    ./sim/loop-stability/testbench/sweep.py                # full matrix, writes a record
    ./sim/loop-stability/testbench/sweep.py --explore      # tt/27C/3.3V only, writes nothing
    ./sim/loop-stability/testbench/sweep.py --backend batch  # full matrix on the Spot batch fleet via `klt sim`
    ./sim/loop-stability/testbench/sweep.py --no-write --backend local -j2  # run locally (explicit), record nothing

Exit codes mirror ``sim/run_corners.py``: 0 pass, 1 a stability check failed,
2 a simulation failed, 3 an environment/usage problem.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as _dt
import math
import os
import shutil
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPDIR = HERE.parent                       # sim/loop-stability
REPO_ROOT = EXPDIR.parent.parent           # repo root
TEMPLATE = HERE / "tb_loop_stability.spice.in"
LDO_NETLIST = REPO_ROOT / "design" / "netlist" / "ldo_core.spice"

sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness import deck, klt_grid  # noqa: E402
from harness.corners import build_grid, resolve_corners, supply_points  # noqa: E402
from harness.loader import load_script  # noqa: E402
from harness.loop_margin import (  # noqa: E402
    AC_DEC,
    F_START,
    F_STOP,
    GM_MIN_DB,
    NOMINAL_SUPPLY_V,
    PM_MIN_DEG,
    PROCESS_CORNERS,
    RESURGENCE_MAX_DB,
    ROW_FIELDS,  # noqa: F401  (re-export: sim/tests assert sweep.ROW_FIELDS)
    Row,
    SUPPLY_TOL,
    TEMPS_C,
    VOUT_NOM_V,
    VOUT_TOL_FRAC,
    base_row_kwargs,
    fmt_esr,
    fmt_ma,
    fmt_uf,
    gm_str,
    parse_row_fields,
    pm_str,
    print_curve_log,
    res_str,
    worst_of,
    worst_resurgence_of,
)
from harness.paths import display_home, display_path  # noqa: E402
from harness.pdk import find_pdk  # noqa: E402
from harness.pdk import pin_klt_pdk_root as _pdk_pin_klt_pdk_root  # noqa: E402
from harness.report import (  # noqa: E402
    allocate_record_id,
    environment as harness_environment,
    environment_lines,
    format_record_id,
    git_provenance,
    print_provenance_banner,
    write_markdown_record,
)
from harness.runner import (  # noqa: E402
    MODEL_BINNING_OPTION,
    ngspice_binary_sha256,
    ngspice_version,
    run_ngspice_deck,
)

# The margin bars, the AC band/resolution, the PVT grid axes and the ``Row``
# verdict semantics this driver enforces live in ``harness/loop_margin.py``
# (issue #630): they are shared -- as the same Python objects -- with
# ``sim/soft-start-loop-gain/testbench/sweep.py``, whose records are only
# comparable with this experiment's because the two read one definition.
# Their rationale (DR-0001, DR-0008, issue #58's resolution policy) is
# documented there.
#
# This bench's own ``klt_run.py`` is a sibling under a hyphenated directory,
# so it is loaded by path under its own name rather than imported -- and this
# driver must not put its bench directory on ``sys.path`` or bind the bare
# module name, because both leak into whatever process loads this file
# (issue #630).
klt_run = load_script("loop_stability_klt_run", HERE / "klt_run.py")

DR0001 = "spec/decision-records/DR-0001-output-cap-strategy.md"
# The swept (load, cap, ESR) axes are this experiment's own; the PVT axes
# (PROCESS_CORNERS / TEMPS_C / NOMINAL_SUPPLY_V / SUPPLY_TOL) are shared and
# come from harness.loop_margin above.
ILOADS_A = (0.0, 0.1e-3, 1e-3, 10e-3, 25e-3, 50e-3)
CEFFS_F = (0.33e-6, 1.0e-6, 4.7e-6)
ESRS_OHM = (0.001, 0.05, 0.2, 0.5)

# --- `klt sim` request shape, batch backend (issue #615) -------------------
#
#: The fleet's whole-job ceiling, in seconds (``batch.max_job_seconds``;
#: ``klt``'s own default when the fleet publishes no ``MaxJobSeconds`` tag).
#: The harness kills the whole job at this age, and the interrupted report is
#: not a complete one, so EVERY unit of that job -- including the units that
#: had already finished -- comes back ``batch_job_timeout``. That is why one
#: slow unit must not be allowed to take 62 finished ones down with it.
KLT_JOB_CEILING_S = 3600
#: The fixed per-job overhead in klt's pre-submit bound,
#: ``job_bound_s = options.timeout_s * units + KLT_JOB_OVERHEAD_S``.
KLT_JOB_OVERHEAD_S = 120

#: ``request.batch.max_units_per_job``: klt splits the request into
#: ``ceil(units / N)`` balanced fleet jobs, so no one job's bound reaches the
#: ceiling above. The grid request is 63 units (7 process x 3 temps x
#: 3 supplies), so N = 29 gives 3 jobs per load/C_eff/ESR configuration.
#:
#: **29 is the largest N that fits, not a preference.** klt's own auto-sizing
#: form of this cap (``job_ceiling_check: "split"``) computes exactly
#: ``floor((KLT_JOB_CEILING_S - KLT_JOB_OVERHEAD_S) / timeout_s)``. The
#: ``timeout_s=900`` this bench's ``klt_run.job()`` originally submitted
#: forced ``floor(3480/900) = 3`` -- 21 jobs per configuration, 1512 fleet
#: jobs across the grid, which is the capacity problem issue #465 was parked
#: on. The measured per-unit runtime that resize was waiting for now exists:
#: issue #465's 2026-11-17 fleet probe ran the whole 63-corner PVT grid at
#: the pinned open_pdks ``f6eeac7`` on the batch runner (ngspice-47) -- mean
#: 1.39 s, max 1.95 s per unit. ``klt_run.job()`` therefore submits
#: ``timeout_s=120`` (a >60x margin on the measured worst unit) and N sizes
#: itself to ``floor(3480/120) = 29``; ``test_loop_stability.py`` derives N
#: from the built request's own ``timeout_s`` with ``==``, so the two cannot
#: drift apart silently.
#:
#: An explicit cap is *honored* rather than refused when its bound still
#: exceeds the ceiling (klayout-tools#4982 -- the bound is a fully-serial
#: upper bound, so klt only warns on stderr, and the fleet harness still kills
#: a job that really runs long). So nothing downstream fails loudly if this
#: pair drifts out of the inequality: ``test_loop_stability.py`` asserts it
#: from the built request's own ``options.timeout_s``, which is what makes a
#: later ``timeout_s`` bump in ``klt_run.py`` fail a test rather than silently
#: hand the fleet jobs it will kill. Do not combine this cap with
#: ``job_ceiling_check: "enforce"``; klt rejects that combination.
KLT_MAX_UNITS_PER_JOB = 29

#: ``request.batch.max_concurrent_jobs``: once a request is split, the shards
#: that the fleet's instance cap refuses come back ``lost_shard`` and are not
#: re-submitted by this repo's harness -- ``capacity_wait_s`` below is what
#: waits out a refusal (inside ``klt``). Bounding this request's jobs in
#: flight keeps its 3 shards from provoking that refusal in the first place.
KLT_MAX_CONCURRENT_JOBS = 3

#: ``request.batch.capacity_wait_s``: wait out a Spot capacity refusal with
#: backoff instead of failing the submit. This is the request-level form of
#: ``klt sim --wait-for-capacity`` the dispatch-host rules require of every
#: batch submit (600 s there is the minimum, not a cap). 600 s was exhausted
#: after 5-6 launch attempts during the 2026-11-19 saturation burst (#465):
#: the shared spot quota sat at the BATCH_MAX_VCPU ceiling for over half an
#: hour, every shard of 4 of the 72 requests came back ``lost_shard``, and
#: since a lost shard fails its corners terminally the whole grid died. 1800 s
#: rides out bursts of that length; shards are lost only when the quota is
#: truly gone for ~30 min.
KLT_CAPACITY_WAIT_S = 1800


# ---------------------------------------------------------------------------
# regulating-branch check
# ---------------------------------------------------------------------------
def nonregulating(rows: list[Row]) -> list[Row]:
    """Rows whose DC output is not on the regulating branch.

    A phase/gain margin is a statement about a *specific* operating point. The
    core has a second, non-regulating DC solution (the current-limit latch
    state -- see the deck's "removing the non-physical DC branch" comment),
    and margins extracted about it are meaningless numbers that look exactly
    like meaningful ones.
    Any row this returns voids the run rather than entering a record.

    NaN counts as non-regulating: an unparsable VOUT is not evidence that the
    bias point was right.
    """
    return [
        r for r in rows
        if not (abs(r.vout_v - VOUT_NOM_V) <= VOUT_TOL_FRAC * VOUT_NOM_V)
    ]


def dc_seed_lines(pvt) -> str:
    """`.nodeset` cards that start Newton on the REGULATING DC branch.

    ``ldo_ilimit`` clamps ``PASS_GATE`` to ``VIN`` through its ``CLG`` gate
    while the feedback node sits below the reference, and "FB low, so clamp
    on, so FB stays low" is a self-consistent DC solution at a finite,
    positive VOUT -- one the deck's ``Dclamp`` (which only denies VOUT the
    escape below -0.7 V) cannot see. Every AC analysis in the deck
    cold-starts its own operating-point solve, so each one is an independent
    chance to land on it; issue #51 hit that at exactly one of the 63 PVT
    corners.

    Every value here is a constant of the design or of the corner -- the
    ratified 1.8 V output target, the 1.2 V feedback node its divider
    defines, and ``ldo_ilimit``'s clamp gate parked at VIN, i.e. off -- so
    this carries no per-corner tuning. A ``.nodeset`` is a first-guess
    constraint that ngspice releases after the first solve pass: it selects
    which solution Newton converges to, it does not create one, and the
    caller re-checks every row's VOUT afterwards exactly as it does without
    the seed.

    ``ldo_softstart`` is deliberately NOT seeded (issue #307). Its old
    ``CLG`` node no longer exists (#189 replaced the clamp comparator with FB
    injection; ngspice warned "Nodeset on non-existent node" and ignored
    it), and its replacement clamp gate ``HG`` needs no seed: ``HG`` is
    driven from ``EN`` through ``XRh_ss`` with only MOS gates and a cap
    hanging off it, so at DC it is ``EN`` = ``VIN`` (clamp off) on every
    branch of this deck, where ``EN`` is a fixed source. Seeding it would
    restate the only DC value it can take. Checked on ngspice at
    ``ss_-40c_2.97v``: with the ``Xilimit`` seed alone the warning is gone
    and the retry still lands on the regulating branch (VOUT 1.79948 V).
    This matches ``sim/soft-start-loop-gain``'s ``dc_seed_lines()``.
    """
    return "\n".join([
        f".nodeset v(VOUT)={VOUT_NOM_V:g} v(XDUT.FB)={VOUT_NOM_V * 2 / 3:g}",
        f".nodeset v(XDUT.Xilimit.CLG)={pvt.vdd:g}",
    ])


def render_deck(pvt, pdk, iloads, ceffs, esrs, ac_dec, dc_seed="") -> str:
    return deck.render_file(TEMPLATE, {
        **deck.pvt_subs(pdk, pvt.corner, pvt.temp_c, pvt.vdd, LDO_NETLIST),
        "CORNER_ID": pvt.corner_id,
        "CORNER_NAME": pvt.corner.name,
        "AC_DEC": str(ac_dec),
        "F_START": F_START,
        "F_STOP": F_STOP,
        "ILOAD_LIST": " ".join(f"{v:g}" for v in iloads),
        "CEFF_LIST": " ".join(f"{v:g}" for v in ceffs),
        "ESR_LIST": " ".join(f"{v:g}" for v in esrs),
        "DC_SEED": dc_seed,
    })


def run_point(pvt, pdk, iloads, ceffs, esrs, ac_dec, workdir: Path, logdir: Path,
              dc_seed: str = ""):
    suffix = "_dcseed" if dc_seed else ""
    deck = workdir / f"{pvt.corner_id}{suffix}.spice"
    deck.write_text(render_deck(pvt, pdk, iloads, ceffs, esrs, ac_dec, dc_seed))
    log = logdir / f"{pvt.corner_id}{suffix}.log"
    try:
        text = run_ngspice_deck(deck, log, workdir)
    except RuntimeError as exc:
        return pvt, [], str(exc)
    rows, err = rows_from_log(pvt, text, len(iloads) * len(ceffs) * len(esrs), log)
    return pvt, rows, err


def rows_from_log(pvt, text: str, expected: int, log: Path):
    """Parse a corner's ``ROW`` lines and apply the regulating-branch check.

    Shared by the local ngspice path and the ``klt sim`` batch path
    (``klt_run.py`` writes the same ``ROW`` lines), so both enter a record
    through one parser and one VOUT test. Returns ``(rows, error | None)``.
    """
    rows: list[Row] = []
    for line in text.splitlines():
        if not line.startswith("ROW "):
            continue
        try:
            f = parse_row_fields(line)
        except ValueError as exc:
            return [], f"{exc} (see {display_path(log)})"
        rows.append(
            Row(
                corner_id=pvt.corner_id,
                corner=pvt.corner.name,
                temp_c=pvt.temp_c,
                vin_v=pvt.vdd,
                iload_a=float(f["iload_a"]),
                **base_row_kwargs(f),
            )
        )
    if len(rows) != expected:
        return rows, f"expected {expected} rows, parsed {len(rows)} (see {display_path(log)})"

    # A margin is only meaningful about the REGULATING bias point. The core has
    # a second, non-regulating DC solution (the current-limit latch state -- see
    # the .nodeset comment in the deck), and a margin extracted about it is
    # noise dressed up as a number. Any row whose VOUT is not within
    # VOUT_TOL_FRAC of the regulation target fails the whole run rather than
    # entering the record: this is the check that keeps the deck's convergence
    # seed honest if the design later moves.
    off = nonregulating(rows)
    if off:
        w = off[0]
        return rows, (
            f"{len(off)}/{len(rows)} points did not settle on the regulating DC "
            f"solution (|VOUT - {VOUT_NOM_V:g} V| > {VOUT_TOL_FRAC:.0%}); first is "
            f"{w.config_id} at VOUT = {w.vout_v:g} V. A loop-gain margin about a "
            f"non-regulating bias point is meaningless, so this run is void "
            f"(see {display_path(log)})"
        )
    return rows, None


def run_curve(pvt, pdk, row: Row, ac_dec, logdir: Path, workdir: Path, suffix: str) -> Path:
    """Re-run one single config with the whole T(f) curve printed to the log."""
    text = render_deck(pvt, pdk, [row.iload_a], [row.ceff_f], [row.esr_ohm], ac_dec)
    header = (
        f"* full loop-gain curve T(f) at the {suffix.replace('-', ' ')} point of this record\n"
        f"* corner={pvt.corner_id} iload={fmt_ma(row.iload_a)} "
        f"ceff={fmt_uf(row.ceff_f)} esr={fmt_esr(row.esr_ohm)}\n"
    )
    return print_curve_log(text, header, logdir / f"{pvt.corner_id}_{suffix}.log",
                           workdir / f"{pvt.corner_id}_{suffix}.spice")


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def write_matrix_csv(path: Path, rows: list[Row]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "corner_id", "process", "temp_c", "vin_v",
                "iload_ma", "ceff_uf", "esr_ohm", "vout_v",
                "dc_loop_gain_db", "f_crossover_hz", "phase_margin_deg",
                "f_180_hz", "gain_margin_db", "result",
                "resurgence_db", "resurgence_result",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r.corner_id, r.corner, f"{r.temp_c:g}", f"{r.vin_v:g}",
                    f"{r.iload_a * 1e3:g}", f"{r.ceff_f * 1e6:g}", f"{r.esr_ohm:g}",
                    f"{r.vout_v:.6g}", f"{r.dcgain_db:.4g}",
                    "" if r.f0_hz is None else f"{r.f0_hz:.6g}",
                    pm_str(r),
                    "" if r.f180_hz is None else f"{r.f180_hz:.6g}",
                    gm_str(r),
                    "PASS" if r.passes else "FAIL",
                    "" if r.resurgence_db is None else f"{r.resurgence_db:.4g}",
                    "FAIL" if r.resurges else "PASS",
                ]
            )


def axis_table(rows: list[Row], axis: str, label: str, fmt) -> list[str]:
    """Worst phase margin along one axis, minimised over every other axis."""
    buckets: dict[float, list[Row]] = {}
    for r in rows:
        buckets.setdefault(getattr(r, axis), []).append(r)
    out = [f"| {label} | worst PM (deg) | crossover at that point (Hz) | worst PVT corner |",
           "|---|---|---|---|"]
    for key in sorted(buckets):
        w = worst_of(buckets[key])
        f0 = "n/a" if w.f0_hz is None else f"{w.f0_hz:.4g}"
        out.append(f"| {fmt(key)} | {pm_str(w)} | {f0} | `{w.corner_id}` |")
    return out


def render_analysis(rows: list[Row]) -> str:
    """Report worst phase margins by axis and the DR-0001 result at the #10 point."""
    min_load = min(r.iload_a for r in rows)
    min_ceff = min(r.ceff_f for r in rows)
    min_esr = min(r.esr_ohm for r in rows)
    light_rows = [
        r for r in rows
        if r.iload_a == min_load and r.ceff_f == min_ceff and r.esr_ohm == min_esr
    ]
    worst = worst_of(light_rows)
    n_pass = sum(r.passes for r in light_rows)
    verdict = "PASS" if n_pass == len(light_rows) else "FAIL"

    lines = [
        "## Structure of the result",
        "",
        "Each table shows the worst phase margin over the other sampled axes and PVT corners.",
        "",
        "**By load current**",
        "",
        *axis_table(rows, "iload_a", "I_load", fmt_ma),
        "",
        "**By effective output capacitance**",
        "",
        *axis_table(rows, "ceff_f", "C_eff", fmt_uf),
        "",
        "**By ESR**",
        "",
        *axis_table(rows, "esr_ohm", "ESR", lambda v: f"{v:g} ohm"),
        "",
        "At the lightest sampled load, minimum C_eff and minimum ESR (issue #10),",
        f"{fmt_ma(min_load)} / {fmt_uf(min_ceff)} / {min_esr:g} ohm,",
        f"the DR-0001 result is **{verdict}** ({n_pass}/{len(light_rows)} corners pass).",
        f"The worst phase margin there is {pm_str(worst)} deg at `{worst.corner_id}`.",
    ]
    return "\n".join(lines) + "\n"


def klt_axes(process, temps, supplies, *, split: bool = True) -> dict:
    """The ``kb.Job`` keyword arguments for one ``klt sim`` request of this bench.

    The three PVT axes, plus the two request options a batch submit of this
    bench needs:

    * ``stage_model_inputs``: ship this host's model files with the job. An
      off-host backend otherwise simulates whatever open_pdks revision the
      runner image carries (``c6d73a3`` when issue #467 checked it), not the
      revision ``sim/harness/pdk.py`` pins, and a record minted that way cannot
      claim the pin. Staging is only half of that claim -- see
      :func:`pin_klt_pdk_root` for the other half.
    * ``batch``: the whole-job ceiling split and its two companions. See
      ``KLT_MAX_UNITS_PER_JOB`` and below.

    ``split=False`` drops ``max_units_per_job``/``max_concurrent_jobs``: the
    DC-seed retry request covers a single PVT point, so it is one unit and one
    job, with nothing to split or to bound. It keeps ``capacity_wait_s``, which
    applies to any submit.

    Factored out of :func:`run_grid_klt` so a test can build the exact request
    the sweep would submit, offline -- see ``sim/tests/test_loop_stability.py``.
    """
    batch = {"capacity_wait_s": KLT_CAPACITY_WAIT_S}
    if split:
        batch = {"max_units_per_job": KLT_MAX_UNITS_PER_JOB,
                 "max_concurrent_jobs": KLT_MAX_CONCURRENT_JOBS, **batch}
    return {"process": tuple(process), "temps": tuple(temps), "supplies": tuple(supplies),
            "stage_model_inputs": True, "batch": batch}


def pin_klt_pdk_root(pdk) -> str:
    """Point the ``klt`` client at the same PDK install ``find_pdk()`` pin-checked.

    ``stage_model_inputs`` (see :func:`klt_axes`) is not by itself enough to
    make a record claim the pin, because ``klt`` decides *which* local install
    to stage from on its own: it searches the usual prefixes first-match-wins
    and, when several provide the variant, warns and proceeds. On a host
    carrying both a pinned ``~/.ciel`` tree and a stale ``~/.volare`` one, the
    models that ship with the job are then chosen by sort order rather than by
    the pin -- silently, with no error. ``$PDK_ROOT`` is the only client-side
    pin the ``batch`` backend accepts.

    ``find_pdk()`` has already run ``check_pin()`` on this ``Pdk``, so its
    variant directory's parent (``sim/env.sh``'s ``PDK_ROOT`` convention) is
    the one tree a record may claim. Assigned rather than ``setdefault``-ed:
    an ambient ``$PDK_ROOT`` that lost to ``$GF180_PDK_PATH`` inside
    ``find_pdk()`` names a *different*, un-pin-checked tree, and leaving it in
    place would send klt there. Returns the value exported.

    Kept as this experiment's name for the shared implementation,
    ``harness.pdk.pin_klt_pdk_root`` -- the reasoning above now lives beside
    ``find_pdk()``/``check_pin()`` where every staging call site can see it.
    """
    return _pdk_pin_klt_pdk_root(pdk)


def run_grid_klt(grid, corners, args, pdk, iloads, ceffs, esrs, logdir: Path, workdir: Path, klt_backend: str):
    """Run the PVT grid through ``klt sim`` (``klt_run.py``) instead of local ngspice.

    One request per (load, C_eff, ESR) configuration over the whole grid; the
    returned values are written per corner as ``<corner-id>.log`` ``ROW`` lines
    and parsed by ``rows_from_log()`` -- the same parser and the same
    regulating-branch VOUT check the local path uses. A corner that misses the
    regulating branch is re-run once, whole, with ``dc_seed_lines()`` in the
    body (log ``<corner-id>_dcseed.log``), exactly as the local path does.
    Returns ``(rows, failures, seeded, info)``; never falls back to local.
    """
    configs = [(il, ce, es) for il in iloads for ce in ceffs for es in esrs]
    axes = klt_axes((c.name for c in corners), args.temps, sorted({p.vdd for p in grid}))
    # Before anything is staged: klt resolves its own PDK install, so pin it to
    # the tree find_pdk() pin-checked (issue #615).
    pdk_root = pin_klt_pdk_root(pdk)
    klt_backend_arg = klt_backend  # "batch" or "local", passed to `klt sim --backend`
    print(f"klt sim   : {len(configs)} requests x {len(grid)} corners, backend {klt_backend}")
    print(f"klt pdk   : PDK_ROOT={display_home(pdk_root)} "
          f"(pin-checked {pdk.variant} @ {pdk.version})")
    if klt_backend == "batch":
        # Staging and the split are both no-ops on the local backend.
        print(f"klt batch : models staged with every job, <= {KLT_MAX_UNITS_PER_JOB} "
              f"units per job ({math.ceil(len(grid) / KLT_MAX_UNITS_PER_JOB)} jobs "
              f"per request, <= {KLT_MAX_CONCURRENT_JOBS} in flight)")
    results, problems, bad = klt_run.run_configs(
        configs, LDO_NETLIST, args.ac_dec, F_START, F_STOP, axes, workdir, logdir,
        klt_backend_arg, args.in_flight)
    for p in problems:
        print(f"  WARNING {p}", file=sys.stderr)

    def parse(pvt, res, suffix=""):
        text = klt_run.corner_log(pvt.corner_id, configs, res)
        log = logdir / f"{pvt.corner_id}{suffix}.log"
        log.write_text(text)
        return rows_from_log(pvt, text, len(configs), log)

    def run_retry(pvt):
        # One PVT point, so one unit and one fleet job: nothing to split.
        one = klt_axes((pvt.corner.name,), (pvt.temp_c,), (pvt.vdd,), split=False)
        res, probs, _ = klt_run.run_configs(
            configs, LDO_NETLIST, args.ac_dec, F_START, F_STOP, one, workdir, logdir,
            klt_backend_arg, args.in_flight, dc_seed=dc_seed_lines(pvt))
        return res, probs

    def say(pvt, event, detail):
        if event == "retry":
            print(f"  {pvt.corner_id:<22} DC branch miss, retrying with the regulating-branch seed")
        else:
            print(f"  {pvt.corner_id:<22} SIM ERROR  {detail}")

    def report(pvt, pt_rows, note):
        w = worst_of(pt_rows)
        print(f"  {pvt.corner_id:<22} worst PM {pm_str(w):>7} deg  GM {gm_str(w):>7} dB  "
              f"at {w.config_id}" + (note and "  [regulating-branch DC seed]"))

    rows, failures, seeded, _ = klt_grid.run_retry_grid(
        grid, results, bad, parse=parse, run_retry=run_retry,
        miss_marker="regulating DC solution", name=lambda pvt: pvt.corner_id,
        bad_key=lambda pvt: pvt.corner_id,
        bad_message="klt reported a problem for this corner (see warnings above)",
        retry_problem=lambda err, probs: err or "; ".join(probs), say=say, report=report)
    info = {"backend": klt_backend, "requests": len(configs), "klt": klt_run.klt_version(),
            "units_per_job": KLT_MAX_UNITS_PER_JOB, "pdk_root": display_home(pdk_root)}
    return rows, failures, seeded, info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corners", nargs="+", default=list(PROCESS_CORNERS),
                    help=f"process corners (default: {' '.join(PROCESS_CORNERS)})")
    ap.add_argument("--temps", nargs="+", type=float, default=list(TEMPS_C))
    ap.add_argument("--supply-tol", type=float, default=SUPPLY_TOL)
    ap.add_argument("--loads-ma", nargs="+", type=float,
                    default=[v * 1e3 for v in ILOADS_A])
    ap.add_argument("--caps-uf", nargs="+", type=float,
                    default=[v * 1e6 for v in CEFFS_F])
    ap.add_argument("--esrs", nargs="+", type=float, default=list(ESRS_OHM))
    ap.add_argument("--ac-dec", type=int, default=int(AC_DEC),
                    help=f"AC points per decade (default: {AC_DEC}). The sweep "
                         "resolution is part of the measurement, not a "
                         "performance knob -- see the \"Sweep resolution\" "
                         "section of sim/loop-stability/README.md for how the "
                         "default is derived and what sampling error it "
                         "bounds. Running BELOW the default needs "
                         "--subset-reason, exactly as a narrowed PVT grid "
                         "does.")
    klt_grid.add_grid_args(ap, batch_unit="(load, C_eff, ESR) configuration")
    ap.add_argument("--resume-record", default="",
                    help="continue an interrupted batch run: reuse this record "
                         "id and its corners/ staging, skipping configurations "
                         "that already reported (issue #465). Pass the same "
                         "grid flags as the interrupted run; the record is "
                         "minted under the same id when the grid completes.")
    ap.add_argument("--explore", action="store_true",
                    help="tt/27C/3.3V only across load x cap x ESR; implies --no-write "
                         "(DR-0001's recommended first pass to locate the worst triple)")
    ap.add_argument("--author", default=os.environ.get("LOOP_STABILITY_AUTHOR", "agent-builder (issue #10)"))
    args = ap.parse_args()

    if args.explore:
        args.corners = ["tt"]
        args.temps = [27.0]
        args.supply_tol = 0.0
        args.no_write = True

    n_pvt = len(resolve_corners(args.corners)) * len(args.temps) * len(
        supply_points(NOMINAL_SUPPLY_V, args.supply_tol))
    selected = klt_grid.select_backend(args.backend, n_pvt)
    if selected is None:
        return 3
    backend, use_klt = selected
    if shutil.which("ngspice") is None:
        print("FATAL: ngspice not on PATH", file=sys.stderr)
        return 3
    try:
        pdk = find_pdk()
    except Exception as exc:  # pragma: no cover - environment problem
        print(f"FATAL: {exc}", file=sys.stderr)
        return 3

    # The committed netlists must be current with the schematics.
    stale = deck.require_fresh_netlists()
    if stale:
        print(stale, file=sys.stderr)
        return 3

    corners = resolve_corners(args.corners)
    supplies = supply_points(NOMINAL_SUPPLY_V, args.supply_tol)
    grid = build_grid(corners, args.temps, supplies)
    iloads = [v * 1e-3 for v in args.loads_ma]
    ceffs = [v * 1e-6 for v in args.caps_uf]
    esrs = list(args.esrs)
    n_points = len(grid) * len(iloads) * len(ceffs) * len(esrs)

    # Same "subsets need a reason" rule the shared harness enforces.
    full_pvt = (
        set(args.temps) >= set(TEMPS_C)
        and args.supply_tol >= SUPPLY_TOL
        and len(corners) >= 3
    )
    full_matrix = (
        full_pvt
        and set(args.loads_ma) >= {v * 1e3 for v in ILOADS_A}
        and set(args.caps_uf) >= {v * 1e6 for v in CEFFS_F}
        and set(args.esrs) >= set(ESRS_OHM)
        # Resolution is an axis of the measurement too (issue #58): a record
        # taken below the default AC_DEC is a narrower claim than the ratified
        # one in exactly the way a missing process corner is, so it needs the
        # same written reason rather than passing silently.
        and args.ac_dec >= int(AC_DEC)
    )
    if not args.no_write and not full_matrix and not args.subset_reason:
        print(
            "FATAL: this grid is narrower than the matrix DR-0001 ratifies.\n"
            "       Re-run with the full matrix, or pass --subset-reason '<why>' "
            "(copied verbatim into the record), or --no-write to just debug.",
            file=sys.stderr,
        )
        return 3

    prov = git_provenance(REPO_ROOT)
    dirty = prov["dirty"]
    if not args.no_write:
        if args.resume_record:
            record_id = args.resume_record
            if (EXPDIR / "records" / f"{record_id}.md").is_file():
                print(f"FATAL: record {record_id} is already minted; append-only "
                      "evidence is never rewritten -- start a new record.",
                      file=sys.stderr)
                return 3
        else:
            record_id = allocate_record_id(REPO_ROOT, EXPDIR / "records", git=prov)
    else:
        record_id = format_record_id(prov["short"], _dt.datetime.now(_dt.timezone.utc))
    logdir = EXPDIR / "corners" / record_id
    workdir = REPO_ROOT / "sim" / ".work" / "loop-stability" / record_id
    workdir.mkdir(parents=True, exist_ok=True)
    if not args.no_write:
        logdir.mkdir(parents=True, exist_ok=True)
    else:
        logdir = workdir

    print_provenance_banner(
        pdk, record_id, host=socket.gethostname(), dirty=dirty,
        note=" (NOT WRITTEN: --no-write)" if args.no_write else "")
    print(f"{'grid':<14}: {len(grid)} PVT points x "
          f"{len(iloads)}x{len(ceffs)}x{len(esrs)} load/cap/ESR = {n_points} loop-gain points")
    print()

    rows: list[Row] = []
    failures: list[str] = []
    seeded: list[str] = []
    klt_info: dict = {}
    if use_klt:
        # The `klt sim` path fills rows/failures/seeded; the local loops below
        # then have nothing to run (`local_grid` is empty).
        rows, failures, seeded, klt_info = run_grid_klt(
            grid, corners, args, pdk, iloads, ceffs, esrs, logdir, workdir,
            "local" if backend == "klt-local" else "batch")
    local_grid = [] if use_klt else grid
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(run_point, pvt, pdk, iloads, ceffs, esrs, args.ac_dec,
                        workdir, logdir): pvt
            for pvt in local_grid
        }
        retries = []
        for done in concurrent.futures.as_completed(futures):
            pvt, pt_rows, err = done.result()
            if err:
                # A corner that misses the regulating DC branch gets ONE
                # retry, with the `.nodeset` seed that starts Newton on it
                # (see dc_seed_lines()). The retry is checked by exactly the
                # same VOUT test as the first attempt -- the seed buys a
                # starting point, never a verdict -- and any corner that
                # needs it is named in the record, so the default, unseeded
                # path stays comparable with every record taken before this
                # one at every corner that does not.
                if "regulating DC solution" in err:
                    retries.append(pvt)
                    print(f"  {pvt.corner_id:<22} DC branch miss, retrying "
                          f"with the regulating-branch seed")
                    continue
                failures.append(f"{pvt.corner_id}: {err}")
                print(f"  {pvt.corner_id:<22} SIM ERROR  {err}")
                continue
            rows.extend(pt_rows)
            w = worst_of(pt_rows)
            print(f"  {pvt.corner_id:<22} worst PM {pm_str(w):>7} deg  "
                  f"GM {gm_str(w):>7} dB  at {w.config_id}")

    if retries:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {
                pool.submit(run_point, pvt, pdk, iloads, ceffs, esrs, args.ac_dec,
                            workdir, logdir, dc_seed_lines(pvt)): pvt
                for pvt in retries
            }
            for done in concurrent.futures.as_completed(futures):
                pvt, pt_rows, err = done.result()
                if err:
                    failures.append(f"{pvt.corner_id} (with DC seed): {err}")
                    print(f"  {pvt.corner_id:<22} SIM ERROR  {err}")
                    continue
                seeded.append(pvt.corner_id)
                rows.extend(pt_rows)
                w = worst_of(pt_rows)
                print(f"  {pvt.corner_id:<22} worst PM {pm_str(w):>7} deg  "
                      f"GM {gm_str(w):>7} dB  at {w.config_id}  "
                      f"[regulating-branch DC seed]")

    if failures:
        print("\nFATAL: simulation failures:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 2
    if not rows:
        print("FATAL: no rows parsed", file=sys.stderr)
        return 2

    rows.sort(key=lambda r: (r.corner, r.temp_c, r.vin_v, r.iload_a, r.ceff_f, r.esr_ohm))
    worst = worst_of(rows)
    failing = [r for r in rows if not r.passes]
    multi_cross = [r for r in rows
                   if r.f0_rising_hz is not None and r.f0_hz is not None
                   and r.f0_rising_hz > r.f0_hz]
    resurging = [r for r in rows if r.resurges]
    worst_res = worst_resurgence_of(rows)
    dr0001_pass = not failing
    overall_pass = dr0001_pass and not resurging

    print()
    print(f"points    : {len(rows)}")
    print(f"failing   : {len(failing)} (PM < {PM_MIN_DEG:g} deg or GM < {GM_MIN_DB:g} dB)")
    f0s = "n/a" if worst.f0_hz is None else f"{worst.f0_hz:.4g}"
    print(f"worst     : PM {pm_str(worst)} deg, GM {gm_str(worst)} dB, f0 {f0s} Hz")
    print(f"            at {worst.corner_id} / {worst.config_id}")
    print(f"DR-0001   : {'PASS' if dr0001_pass else 'FAIL'} against {DR0001}")
    print(f"resurging : {len(resurging)} (|T| > {RESURGENCE_MAX_DB:g} dB above the "
          f"first 0 dB crossing; worst {res_str(worst_res)} dB at "
          f"{worst_res.corner_id} / {worst_res.config_id})")
    print(f"OVERALL   : {'PASS' if overall_pass else 'FAIL'} "
          f"(both the DR-0001 margins and the DR-0008 precondition check)")

    if args.no_write:
        print("\n(--no-write: no record, snapshot or corner logs committed)")
        return 0 if overall_pass else 1

    # Full-curve evidence at the worst point, and at the best-margin point of
    # the same PVT corner for contrast.
    worst_pvt = next(p for p in grid if p.corner_id == worst.corner_id)
    curve_log = run_curve(worst_pvt, pdk, worst, args.ac_dec, logdir, workdir,
                          "worst-curve")

    snap = EXPDIR / "netlist-snapshots" / f"{record_id}.spice"
    snap.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LDO_NETLIST, snap)

    records = EXPDIR / "records"
    records.mkdir(parents=True, exist_ok=True)
    csv_path = records / f"{record_id}-matrix.csv"
    write_matrix_csv(csv_path, rows)

    md = render_record(
        record_id=record_id, rows=rows, worst=worst, failing=failing,
        multi_cross=multi_cross, resurging=resurging, grid=grid, iloads=iloads,
        ceffs=ceffs, esrs=esrs, pdk=pdk, dirty=dirty, args=args,
        curve_log=curve_log, seeded=seeded, prov=prov, klt_info=klt_info,
    )
    # Append-only: the record-id was minted before the sweep ran, so re-check
    # that it is still free rather than clobbering whatever landed meanwhile.
    record_path = write_markdown_record(record_id, md, records)

    print()
    print(f"record           : {record_path}")
    print(f"matrix csv       : {csv_path}")
    print(f"netlist snapshot : {snap}")
    print(f"raw logs         : {logdir}/")
    return 0 if overall_pass else 1


def render_record(*, record_id, rows, worst, failing, multi_cross, resurging,
                  grid, iloads, ceffs, esrs, pdk, dirty, args, curve_log,
                  prov, seeded=(), klt_info=None) -> str:
    rel = lambda p: str(Path(p).resolve().relative_to(REPO_ROOT))  # noqa: E731
    overall = "PASS" if not failing else "FAIL"
    by_corner: dict[str, list[Row]] = {}
    for r in rows:
        by_corner.setdefault(r.corner_id, []).append(r)

    def _pm_key(r: Row) -> float:
        return -1e9 if r.pm_deg is None else r.pm_deg

    def _hz(v) -> str:
        return "n/a" if v is None else f"{v:.4g}"

    corner_tbl = ["| corner-id | worst PM (deg) | GM (dB) | f_crossover (Hz) | at (I_load / C_eff / ESR) | result |",
                  "|---|---|---|---|---|---|"]
    for cid in sorted(by_corner, key=lambda c: _pm_key(worst_of(by_corner[c]))):
        w = worst_of(by_corner[cid])
        corner_tbl.append(
            f"| `{cid}` | {pm_str(w)} | {gm_str(w)} | {_hz(w.f0_hz)} | "
            f"{fmt_ma(w.iload_a)} / {fmt_uf(w.ceff_f)} / {w.esr_ohm:g} ohm | "
            f"{'PASS' if w.passes else '**FAIL**'} |"
        )

    # worst config across all PVT, per (load, cap, ESR) cell
    by_cfg: dict[tuple, list[Row]] = {}
    for r in rows:
        by_cfg.setdefault((r.iload_a, r.ceff_f, r.esr_ohm), []).append(r)
    cfg_tbl = ["| I_load | C_eff | ESR | worst PM (deg) | worst GM (dB) | worst PVT corner | result |",
               "|---|---|---|---|---|---|---|"]
    for key in sorted(by_cfg):
        w = worst_of(by_cfg[key])
        cfg_tbl.append(
            f"| {fmt_ma(key[0])} | {fmt_uf(key[1])} | {key[2]:g} ohm | {pm_str(w)} | "
            f"{gm_str(w)} | `{w.corner_id}` | {'PASS' if w.passes else '**FAIL**'} |"
        )

    # DR-0008's precondition check, per load current: the axis DR-0008's own
    # 720-point spot check was taken along.
    by_load_res: dict[float, list[Row]] = {}
    for r in rows:
        by_load_res.setdefault(r.iload_a, []).append(r)
    res_tbl = ["| I_load | points resurging | worst resurgence (dB) | at (C_eff / ESR / PVT corner) |",
               "|---|---|---|---|"]
    for key in sorted(by_load_res):
        bucket = by_load_res[key]
        w = worst_resurgence_of(bucket)
        n_res_load = sum(1 for r in bucket if r.resurges)
        res_tbl.append(
            f"| {fmt_ma(key)} | {n_res_load}/{len(bucket)} | {res_str(w)} | "
            f"{fmt_uf(w.ceff_f)} / {w.esr_ohm:g} ohm / `{w.corner_id}` |"
        )

    n_pass = len(rows) - len(failing)
    pms = [r.pm_deg for r in rows if r.pm_deg is not None]
    best = max(rows, key=_pm_key)
    procs = ", ".join(sorted({r.corner for r in rows}))
    temps_seen = ", ".join(f"{t:g}" for t in sorted({r.temp_c for r in rows}))
    supplies_seen = ", ".join(f"{v:.2f}" for v in sorted({r.vin_v for r in rows}))
    n_inf_gm = sum(1 for r in rows if math.isinf(r.gm_db))
    analysis = render_analysis(rows)

    # Which of DR-0001's two bars actually bites is a property of the loop
    # being measured, not a constant -- so read it off the data rather than
    # asserting it. A loop whose phase only asymptotes to -180 deg has no
    # finite gain margin to fail; one that crosses -180 deg below its 0 dB
    # crossing fails both bars at once, and saying so is the whole point.
    n_gm_fail = sum(1 for r in rows if r.gm_db < GM_MIN_DB)
    n_pm_fail = sum(1 for r in rows if r.pm_deg is None or r.pm_deg < PM_MIN_DEG)
    if n_gm_fail == 0:
        gm_reading = (
            f"Gain margin is **not** the limiting criterion anywhere in this "
            f"matrix: at {n_inf_gm}/{len(rows)} points the loop phase never "
            f"reaches -180 deg in 0.01 Hz - 1 GHz (a loop that approaches "
            f"-180 deg from above), so no finite gain multiplier drives T to "
            f"-1; where a -180 deg crossing does exist the gain there is below "
            f"0 dB. Every failure below is a **phase-margin** failure."
        )
    else:
        gm_reading = (
            f"**Both** of DR-0001's bars are broken here, and by the same "
            f"mechanism: {n_pm_fail}/{len(rows)} points miss the "
            f">= {PM_MIN_DEG:g} deg phase-margin bar and "
            f"{n_gm_fail}/{len(rows)} miss the >= {GM_MIN_DB:g} dB gain-margin "
            f"bar. A negative gain margin means the phase reaches -180 deg "
            f"while |T| is still above 0 dB -- the -180 deg crossing sits "
            f"*below* the 0 dB crossing rather than above it. Only "
            f"{n_inf_gm}/{len(rows)} points have no -180 deg crossing in "
            f"0.01 Hz - 1 GHz at all. This record reports the two Bode margins "
            f"DR-0001 asks for and nothing beyond them: a closed-loop "
            f"stability verdict would need a Nyquist reading, which is not "
            f"attempted here and is not what the ratified criterion is written "
            f"in terms of."
        )

    if klt_info:
        klt_md = (
            f" (`--backend {klt_info['backend']}`)\n"
            f"- Backend: `klt sim`, {klt_info['requests']} requests (one per load/C_eff/ESR "
            f"configuration) over the PVT grid, client `{klt_info['klt']}` "
            f"(`klt_run.py`, issue #366). The per-corner logs and the full-curve "
            f"log are `ROW` lines of values `klt` returned (the report JSON of each "
            f"request is under `corners/{record_id}/klt-reports/`), so the ngspice "
            f"version/hash and host above describe only the local full-curve re-run, "
            f"not the grid; the grid ran on the engine and host named in those reports."
            # `stage_model_inputs` and the fleet-job split are no-ops on the
            # klt-local backend, so only a batch record may claim either.
            + (
                f"\n- PDK on the grid: the model files of the pin-checked install above "
                f"were staged with every job (`options.stage_model_inputs`, with the `klt` "
                f"client pinned to that install via `PDK_ROOT={klt_info['pdk_root']}`), so "
                f"the grid ran the pinned open_pdks revision and not whatever revision the "
                f"runner image carries -- expect `pdk_stamp_comparison: mismatch` in each "
                f"report, which is the reason for staging. Each request was split into "
                f"fleet jobs of at most {klt_info['units_per_job']} units "
                f"(`batch.max_units_per_job`) so no job reaches the fleet's whole-job "
                f"ceiling, which would report every unit of it `batch_job_timeout` "
                f"(issue #615)."
                if klt_info["backend"] == "batch" else ""
            )
        )
    else:
        klt_md = ""
    env = harness_environment(
        pdk=pdk,
        ngspice=ngspice_version(),
        repo_root=REPO_ROOT,
        git=prov,
        ngspice_sha256=ngspice_binary_sha256(),
    )
    env_md = "\n".join(
        environment_lines(
            env,
            command="./sim/loop-stability/testbench/run.sh",
            command_suffix=klt_md,
            # DR-0025, Consequences: "New records carry a model-binning line
            # in their Environment section." The harness canonical wording,
            # so every record path renders one wording of the same pin.
            extra=[
                f"- Model binning: deck pins `.options {MODEL_BINNING_OPTION}`"
                " -- gf180mcu bins on the per-finger width W/NF, and the pass device"
                " (`W=2800u nf=40`, i.e. 70 um per finger) resolves to a declared bin"
                " only with it; without it"
                " ngspice hard-errors rather than clamping, so a record either carries"
                " this setting or does not exist (issue #214,"
                " spec/decision-records/DR-0025)",
            ],
        )
    )
    subset = args.subset_reason.strip()
    subset_md = (f"\n  - **Subset reason**: {subset}\n" if subset else "")
    if seeded:
        seeded_md = (
            "\n  - **DC branch seed used at "
            f"{len(seeded)}/{len(grid)} PVT corner(s)**: "
            + ", ".join(f"`{c}`" for c in sorted(seeded))
            + ". Those corners first missed the regulating DC solution and\n"
            "    were re-run once with `.nodeset` cards that start Newton with\n"
            "    `ldo_softstart`/`ldo_ilimit`'s `PASS_GATE` clamps released --\n"
            "    see `dc_seed_lines()` in `sweep.py` and the \"removing the\n"
            "    non-physical DC branch\" comment in the deck. The seed selects\n"
            "    which of the circuit's DC solutions Newton converges to and is\n"
            "    released after the first solve pass; the retry is held to the\n"
            "    same VOUT check as the first attempt, and the raw log for it is\n"
            "    `<corner-id>_dcseed.log`. Every other corner ran unseeded, so\n"
            "    its numbers are directly comparable with earlier records.\n"
        )
    else:
        seeded_md = ""
    subset_md = subset_md + seeded_md
    multi_md = ""
    if multi_cross:
        multi_md = (
            f"\n  - **Multiple 0 dB crossings** detected at {len(multi_cross)} point(s); "
            "the reported phase margin is taken at the first falling crossing. "
            "See the `f0_rising_hz` column of the raw logs.\n"
        )

    # The DR-0008 precondition check (issue #59). Reported as its own verdict,
    # never folded into the DR-0001 PASS/FAIL above.
    worst_res = worst_resurgence_of(rows)
    n_measured_res = sum(1 for r in rows if r.resurgence_db is not None)
    if resurging:
        res_verdict = (
            f"**{len(resurging)}/{len(rows)} points** have `|T|` back above "
            f"{RESURGENCE_MAX_DB:g} dB somewhere above their first 0 dB crossing, "
            f"worst **{res_str(worst_res)} dB** at `{worst_res.corner_id}` / "
            f"{fmt_ma(worst_res.iload_a)} / {fmt_uf(worst_res.ceff_f)} / "
            f"{worst_res.esr_ohm:g} ohm. Where that happens, the phase margin "
            f"tabulated above is read at a crossing that is not the last one, "
            f"and DR-0008's finding is that on this design the crossing sits on "
            f"the far side of a resonance whose right-half-plane pole pair has "
            f"already advanced the phase by ~ +180 deg -- so `180 + phase` "
            f"returns a large positive number for a loop that is oscillating."
        )
    else:
        res_verdict = (
            f"**No point** in this matrix has `|T|` above "
            f"{RESURGENCE_MAX_DB:g} dB anywhere above its first 0 dB crossing "
            f"(worst {res_str(worst_res)} dB, at `{worst_res.corner_id}` / "
            f"{fmt_ma(worst_res.iload_a)} / {fmt_uf(worst_res.ceff_f)} / "
            f"{worst_res.esr_ohm:g} ohm), i.e. every point crosses unity once "
            f"and stays below it. That removes the *necessary* condition for "
            f"the DR-0008 misreading, it does not by itself prove the loop gain "
            f"has no right-half-plane poles."
        )
    resurgence_md = f"""
- **Precondition check (DR-0008 / issue #59): gain resurgence above the first
  0 dB crossing** -- reported and failed **separately** from the two DR-0001
  bars above, and deliberately not folded into the PASS/FAIL column.

  A Bode phase/gain margin is a stability test only when `T(s)` has no
  right-half-plane poles. `design/error_amp.sch` closes a local feedback loop
  inside the amplifier that stays closed when the LDO loop is broken at
  `ERRAMP_OUT`/`PASS_GATE`, so that precondition is a real question here;
  `spec/decision-records/DR-0008-loop-gain-rhp-pole-precondition.md` records
  that it did not hold for the amplifier as committed at `b304bd5`. This row
  is the cheap frequency-domain signature of that failure: `resurgence_db` is
  the largest `|T|` in dB anywhere above the first (falling) 0 dB crossing,
  scanned from a fixed 5% above the crossing (issue #69 -- a constant
  independent of `AC_DEC`, so the value is comparable across records taken at
  different resolutions) so the crossing itself is never reported as its own
  resurgence. For a loop that rolls off monotonically through crossover the
  quantity is negative by construction, which is why the bar is
  **<= {RESURGENCE_MAX_DB:g} dB** with no slack in it.

  {res_verdict}

  This is **necessary-but-not-sufficient** evidence of a right-half-plane pole
  pair: a well-damped but under-margined loop could in principle resurge
  without one. It does **not** replace `sim/amp-selfosc/`, which measures the
  oscillation directly in the time domain and remains the load-bearing check
  per DR-0008. Measured at {n_measured_res}/{len(rows)} points (a point with
  no 0 dB crossing at all has no region above one, and already fails the
  phase-margin bar on its own account).

  By load current:

{chr(10).join(res_tbl)}
"""

    return f"""# Record {record_id}

- **Record ID**: {record_id}
- **Claim**: `{DR0001}` -- stability criterion "worst-corner phase margin
  >= {PM_MIN_DEG:g} deg **and** gain margin >= {GM_MIN_DB:g} dB across the full matrix",
  verified over the ratified `I_load` x `C_eff` x `ESR` x PVT matrix
  (issue #10). This is the stability evidence for the LDO loop; per #10's
  scope note it is *the* phase-margin record, and #12's spec-line testbench
  suite should reference it rather than duplicate a phase-margin testbench.
- **Netlist provenance**: schematic (`design/ldo_core.sch`, via
  `design/netlist/ldo_core.spice`){' -- **DIRTY WORKING TREE at run time; not citable as a clean-tree result**' if dirty else ''}.
  The DUT is the **real** loop: `design/error_amp.sch` (transistor-level,
  Miller-compensated) and `design/ldo_ilimit.sch` (the real limit block), with
  the pass device and the 300k/600k feedback divider from
  `design/ldo_core.sch`. No behavioural amplifier is used. The only
  idealizations in the loop are the ones the other records already name:
  the ideal 1.2 V source this deck drives `ldo_core`'s `VREF` port with,
  standing in for a bandgap block that does not exist yet (issue #174 /
  DR-0021 promoted `VREF` from an internal net to a top-level port; the
  source itself is unchanged, it just lives in the deck now), and `Fbias`
  inside `ldo_ilimit`. The load is an ideal DC current
  source (see "Operating conditions"), which is the conservative choice for a
  stability measurement.
- **Corner matrix run**:
  - Process: {procs}
  - Temperature: {temps_seen} degC
  - Supply: {supplies_seen} V
  - {len(grid)} PVT points x {len(iloads)} load x {len(ceffs)} cap x {len(esrs)} ESR
    = **{len(rows)} loop-gain points** (the full
    {len(PROCESS_CORNERS) * len(TEMPS_C) * 3 * len(ILOADS_A) * len(CEFFS_F) * len(ESRS_OHM)}-point
    grid DR-0001 (plus issue #54's `res_ff`/`res_ss` process corners)
    enumerates, when run with the defaults).{subset_md}
- **Operating conditions**:
  - Load current: {', '.join(fmt_ma(v) for v in iloads)}, modelled as an ideal DC
    current source (infinite small-signal impedance -- the conservative LDO
    stability model; a resistive load would add damping in parallel with the
    output pole and flatter the result). 0 mA means no external load, i.e.
    only the feedback divider's ~6 uA, per DR-0001.
  - Output cap: C_eff in {{{', '.join(fmt_uf(v) for v in ceffs)}}} with
    ESR in {{{', '.join(f'{v:g}' for v in esrs)}}} ohm, in series, at the output
    pin. These are DERATED EFFECTIVE values per DR-0001, not nominal
    component values. The 1 mOhm point is the numerical stand-in for
    "ESR -> 0" (no ESR zero to help), which DR-0001 makes a required point.
  - Enable state: enabled (EN = VIN), steady state.
  - Loop break: `ERRAMP_OUT` -> `PASS_GATE`, the two deliberately-unconnected
    ports `design/ldo_core.sch` exposes. Tian/Middlebrook dual injection
    (series voltage + shunt current), so the reported loop gain is exact
    regardless of the source/load impedance ratio at the break, and the DC
    operating point is the true closed-loop one (the injection source is a
    DC short).
  - Capless operation is **not** swept: DR-0001 scopes it out of the primary
    design as a separate fork.
- **Statistical convention**: N/A (corner-matrix claim, not a distribution
  claim -- no Monte Carlo).
- **Result**:
  - **Overall: {overall}** against `{DR0001}`
    ({n_pass}/{len(rows)} points pass, {len(failing)} fail). This verdict is
    the DR-0001 phase/gain-margin criterion and nothing else; the DR-0008
    precondition check below is reported as its own, separate verdict.
  - **Worst point**: `{worst.corner_id}` at
    I_load = {fmt_ma(worst.iload_a)}, C_eff = {fmt_uf(worst.ceff_f)},
    ESR = {worst.esr_ohm:g} ohm --
    **phase margin {pm_str(worst)} deg** (bar: >= {PM_MIN_DEG:g} deg),
    gain margin {gm_str(worst)} dB (bar: >= {GM_MIN_DB:g} dB),
    crossover {_hz(worst.f0_hz)} Hz, DC loop gain {worst.dcgain_db:.4g} dB.
  - **Best point** (for range): `{best.corner_id}` at
    {fmt_ma(best.iload_a)} / {fmt_uf(best.ceff_f)} / {best.esr_ohm:g} ohm --
    phase margin {pm_str(best)} deg.
  - Phase margin across the whole matrix spans
    {min(pms):.2f} deg to {max(pms):.2f} deg.
  - {gm_reading}{multi_md}

  Per-PVT-corner worst case (worst over that corner's
  {len(iloads) * len(ceffs) * len(esrs)} load/cap/ESR configurations),
  sorted worst-first:

{chr(10).join(corner_tbl)}

  Worst case per load/cap/ESR configuration (worst over all {len(grid)} PVT
  points), which is where the structure of the failure is visible:

{chr(10).join(cfg_tbl)}
{resurgence_md}
- **Links**:
  - Testbench: `sim/loop-stability/testbench/tb_loop_stability.spice.in`,
    `sim/loop-stability/testbench/sweep.py`,
    `sim/loop-stability/testbench/run.sh`
  - Testbench self-test (validates the Tian extraction, the margin extraction
    and the resurgence extraction against loops with an analytically known
    loop gain -- one monotonic, one deliberately resurging):
    `sim/loop-stability/testbench/tb_tian_selftest.spice`,
    `sim/loop-stability/testbench/selftest.py`
  - Precondition the resurgence row is evidence for:
    `spec/decision-records/DR-0008-loop-gain-rhp-pole-precondition.md`; the
    load-bearing time-domain measurement of the same precondition is
    `sim/amp-selfosc/`
  - Netlist snapshot: `sim/loop-stability/netlist-snapshots/{record_id}.spice`
  - Raw logs (one per PVT point, {len(iloads) * len(ceffs) * len(esrs)} `ROW`
    lines each): `sim/loop-stability/corners/{record_id}/`
  - Full loop-gain curve T(f) at the worst point: `{rel(curve_log)}`
  - Full {len(rows)}-point matrix, machine-readable:
    `sim/loop-stability/records/{record_id}-matrix.csv`
- **Timestamp / author**: {_dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}, {args.author}
- **Supersedes**: {args.supersedes or '(none -- first record for this experiment)'}

{analysis}
## Environment

Everything needed to re-run this record:

{env_md}
- AC sweep: `dec {args.ac_dec} {F_START} {F_STOP}` per injection, two injections
  per point{'' if args.ac_dec == int(AC_DEC) else f' (**not** the default `dec {AC_DEC}` -- see Subset reason)'}.
  The resolution is part of this measurement, not a performance setting
  (issue #58). Sampling a resonance of quality factor `Q` on a log grid worst
  case (peak midway between two samples, relative detuning
  `d = 10^(1/(2*dec)) - 1`) reads `20*log10(sqrt((2*Q*d)^2 + 1))` dB low, so
  `dec {args.ac_dec}` holds any resonance up to
  **Q ~ {math.sqrt(10 ** 0.1 - 1) / (2 * (10 ** (1 / (2 * args.ac_dec)) - 1)):.0f}**
  to within 1 dB -- a tenth of the {GM_MIN_DB:g} dB gain-margin bar. `dec 50`,
  which every record through `20260802-171044-db620a6` used, held that only to
  Q ~ 11. This is a stated capability, not a proof of sufficiency: no finite
  grid resolves an arbitrarily sharp feature. See "Sweep resolution" in
  `sim/loop-stability/README.md`.

---

Written by `sim/loop-stability/testbench/sweep.py`, in the `sim/README.md`
record format. Append-only: never edit or delete this file -- a re-run or
correction mints a new record-id and points back here via **Supersedes**.
"""


if __name__ == "__main__":
    sys.exit(main())
