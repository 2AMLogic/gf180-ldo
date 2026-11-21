#!/usr/bin/env python3
"""Soft-start loop-gain sweep driver (issue #196).

Measures the LDO main loop's small-signal margins with
``design/ldo_softstart.sch``'s FB-injection element **in the loop**, at pinned
points of the soft-start ramp, for two DUT variants of that element:

    device   `design/netlist/ldo_softstart.spice` as committed today
    binj     `Binj_ss` frozen pre-DR-0024 cap sizing (commit bfc4a0a)

NOTE: what the `device`/`binj` A/B isolates has changed twice. `device` was
the post-#195 device-level transconductor, then (issue #231 / PR #233) the
ideal `Binj_ss` source -- identical to `binj`'s element, leaving the A/B with
no injection-element content at all (issue #234) -- and is now, as of issue
#246, the device-level transconductor again WITH DR-0023's cascoded output
mirror. So the A/B is once more an injection-element comparison, confounded
by the DR-0024 MIM-cap resize that `binj` (frozen at bfc4a0a) predates. See
`netlist_variants.py`'s module docstring and `VARIANT_BLURB` for the full
three-era account, which `sim/tests/test_soft_start_loop_gain.py`'s
`TestDutVariantAB` asserts.

**`ATTRIBUTIONS` is re-expanded by #246, but only by one row.**
`acopen-fb-inj` comes back, retargeted from `XMgmo_ss` to `XMgmc_ss` (the
cascode's drain is what sits on FB now), because it is the measurement target
T6 is written against and nothing else in this repo can produce one.
`acshort-gmsum` stays retired even though `GMSUM` is a netlist token again:
it never resolved a pole or a zero. See the comment above `ATTRIBUTIONS` for
both arguments in full.

Why this experiment exists: PR #195 landed the device-level injection chain
together with a "KNOWN, UNRESOLVED REGRESSION (#191)" note, and #191's Builder
asked for exactly this measurement -- "what compensation does a real FB
injection element need" -- which nobody had. `sim/loop-stability/` measures
the main loop at its settled operating point, where the soft-start ramp is
over and the injection is off; nothing measured it *during* the hand-over.

    ./sim/soft-start-loop-gain/testbench/run.sh              # the whole thing
    ./sim/soft-start-loop-gain/testbench/sweep.py --explore  # tt/27C only, no record
    ./sim/soft-start-loop-gain/testbench/sweep.py --backend batch      # the grid on the Spot batch fleet via `klt sim` (issue #451)
    ./sim/soft-start-loop-gain/testbench/sweep.py --backend local -j2  # a PVT grid, on THIS host (explicit, issue #366)
    ./sim/soft-start-loop-gain/testbench/sweep.py --help     # every option

Everything about the loop-gain extraction itself -- the Tian/Middlebrook dual
injection, the break at ``ERRAMP_OUT``/``PASS_GATE``, the phase/gain-margin
and DR-0008 resurgence idioms, ``AC_DEC = 400`` -- is
``sim/loop-stability/``'s, imported from its driver rather than copied, so the
two experiments cannot drift apart in what a margin *means*. What is new here
is the operating points, the DUT variants, the landing rule that has to work
low on the ramp, and the attribution runs.

This file is the DRIVER half only, since issue #608: the value types,
operating points and tolerances both halves need live in ``model.py``, and
every Markdown renderer (``render_record`` and its tables/sections) lives in
``record.py`` -- both siblings beside this file, loaded by path under
unique names like ``klt_run.py`` below. ``render_record`` is re-exported
here; everything else in those two modules is reachable as ``sweep.<name>``
re-exports for the tests.

Exit codes: 0 the sweep ran and every point landed on the intended DC branch,
1 a point did not land (or the cross-check disagreed beyond tolerance),
2 a simulation failed, 3 an environment/usage problem.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as _dt
import math
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPDIR = HERE.parent                       # sim/soft-start-loop-gain
REPO_ROOT = EXPDIR.parent.parent           # repo root
TEMPLATE = HERE / "tb_ss_loop_gain.spice.in"
HANDOVER_TEMPLATE = HERE / "tb_ss_handover.spice.in"

sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness import deck, klt_grid  # noqa: E402
from harness.corners import build_grid, resolve_corners, supply_points  # noqa: E402
from harness.loader import load_script  # noqa: E402
from harness.paths import display_path  # noqa: E402
from harness.pdk import find_pdk  # noqa: E402
from harness.report import (  # noqa: E402
    allocate_record_id,
    format_record_id,
    git_provenance,
    print_provenance_banner,
    write_markdown_record,
)
from harness.runner import run_ngspice_deck  # noqa: E402

sys.path.insert(0, str(HERE))
import netlist_variants as nv  # noqa: E402

# This bench's own ``klt_run.py`` is loaded by path under its own name rather
# than imported: this driver is itself loaded by path (tests, other drivers),
# and a bare ``import klt_run`` would bind the shared module name to whichever
# bench's sibling got imported first in that process (issue #693) --
# ``sim/soft-start/testbench/klt_peak_run.py`` occupies the same name, and
# neither bench's entry points exist on the other's module. The same rule and
# pattern as ``sim/loop-stability/testbench/sweep.py`` (issue #630).
klt_run = load_script("ss_loop_gain_klt_run", HERE / "klt_run.py")

# `sim/loop-stability/`'s own driver, invoked as a SUBPROCESS by the anchor
# cross-check below (run_loop_stability_here) so the same-host comparison runs
# that bench's unmodified entry point in its own process.
_LS_PATH = REPO_ROOT / "sim" / "loop-stability" / "testbench" / "sweep.py"

# --- the shared loop-margin semantics, imported rather than copied ----------
# The margin bars, the AC band and resolution, the PVT axes and the ``Row``
# verdict semantics this experiment shares with `sim/loop-stability/` live in
# `harness/loop_margin.py` (issue #630) -- the same module that bench's own
# driver imports. Importing them (rather than copying constants over) is
# deliberate: this experiment's whole claim to comparability with
# `sim/loop-stability/`'s records rests on the two using the same bars, the
# same AC band and resolution, and the same margin semantics, and a copy would
# let those drift silently. The `Row` class in `model.py` below SUBCLASSES
# the harness Row for the same reason -- `pm_deg`, `gm_db`, `passes` and
# `resurges` are inherited, not restated.
# `sim/tests/test_soft_start_loop_gain.py` asserts that BOTH benches read
# these same objects.
from harness import loop_margin  # noqa: E402
from harness.loop_margin import (  # noqa: E402
    AC_DEC,
    F_START,
    F_STOP,
    GM_MIN_DB,  # noqa: F401  (re-export: sim/tests assert sweep.GM_MIN_DB)
    NOMINAL_SUPPLY_V,
    PM_MIN_DEG,  # noqa: F401  (re-export: sim/tests assert sweep.PM_MIN_DEG)
    PROCESS_CORNERS,
    RESURGENCE_MAX_DB,  # noqa: F401  (re-export: sim/tests assert sweep.RESURGENCE_MAX_DB)
    SUPPLY_TOL,
    TEMPS_C,
    VOUT_NOM_V,
    base_row_kwargs,
    fmt_esr,
    fmt_uf,
    gm_str,
    nan_or,
    parse_opt_float,
    pm_str,
    print_curve_log,
    res_str,
    worst_of,
    worst_resurgence_of,
)

# --- the shared model layer and the record renderer (issue #608) -----------
# `model.py` holds the value types, field lists/parsers, operating points
# and tolerances this driver and `record.py` BOTH use; `record.py` holds
# every Markdown renderer (`render_record` and its tables/sections). Both
# are siblings loaded by path under unique names, exactly like
# `klt_run.py` above (issues #451/#693, #700): a bare `import model` /
# `import record` would bind the shared module name to whichever bench's
# sibling landed on sys.path first in this process. The `sys.modules.get`
# guard reuses an already-loaded copy instead of re-executing the file --
# `load_script` re-runs it when called twice, and two executions would
# mean two `Row` classes that isinstance cannot tell apart.
model = sys.modules.get("ss_loop_gain_model")
if model is None:
    model = load_script("ss_loop_gain_model", HERE / "model.py")
record = sys.modules.get("ss_loop_gain_record")
if record is None:
    record = load_script("ss_loop_gain_record", HERE / "record.py")

# Re-exports: the driver code below and
# `sim/tests/test_soft_start_loop_gain.py` keep resolving every name this
# file always exposed (`sweep.Row`, `sweep.PHASES`, ...) after the #608
# split moved the definitions into `model.py` / `record.py`.
Row = model.Row
ROW_FIELDS = model.ROW_FIELDS
parse_row_fields = model.parse_row_fields
HOV_FIELDS = model.HOV_FIELDS
parse_hov_fields = model.parse_hov_fields
HovPoint = model.HovPoint
HovCurve = model.HovCurve
_iinj_a = model._iinj_a
_hz = model._hz
key_of = model.key_of
sort_key = model.sort_key
group = model.group
VREF_V = model.VREF_V
RATED_LOAD_A = model.RATED_LOAD_A
RATED_LOAD_OHM = model.RATED_LOAD_OHM
OPEN_LOAD_OHM = model.OPEN_LOAD_OHM
PHASES = model.PHASES
HANDOVER_SSR_V = model.HANDOVER_SSR_V
HANDOVER_ACQUISITION_SSR_V = model.HANDOVER_ACQUISITION_SSR_V
HANDOVER_INTENT_GM_UA_PER_V = model.HANDOVER_INTENT_GM_UA_PER_V
HANDOVER_INTENT_RELEASE_V = model.HANDOVER_INTENT_RELEASE_V
HANDOVER_RELEASE_A = model.HANDOVER_RELEASE_A
HANDOVER_REG_TOL_V = model.HANDOVER_REG_TOL_V
SSR_POINT_LABEL = model.SSR_POINT_LABEL
FB_TOL_V = model.FB_TOL_V
VOUT_FLOOR_V = model.VOUT_FLOOR_V
VOUT_CEIL_V = model.VOUT_CEIL_V
XCHECK_PM_TOL_DEG = model.XCHECK_PM_TOL_DEG
XCHECK_GM_TOL_DB = model.XCHECK_GM_TOL_DB
XCHECK_F0_TOL_FRAC = model.XCHECK_F0_TOL_FRAC
FB_CAP_PM_TOL_DEG = model.FB_CAP_PM_TOL_DEG
FB_CAP_GM_TOL_DB = model.FB_CAP_GM_TOL_DB
ATTR_FLOOR_DB = model.ATTR_FLOOR_DB
ATTR_FLOOR_DEG = model.ATTR_FLOOR_DEG
LS_DIAGNOSTIC_RECORD = model.LS_DIAGNOSTIC_RECORD
render_record = record.render_record


# --- the grid ---------------------------------------------------------------
# tt ff ss fs sf res_ff res_ss (PROCESS_CORNERS), TEMPS_C, NOMINAL_SUPPLY_V
# and SUPPLY_TOL come from harness.loop_margin above: loop-stability's own
# PVT axes, as the same Python objects.

# Output-network configurations, all at the rated 50 mA load point. Two of
# DR-0001's three C_eff values: the 1 uF / 100 mOhm point `sim/soft-start/`
# runs its main matrix at, and the two 4.7 uF groups it runs its capacitor
# axis at (0.001 and 0.5 ohm ESR), with the remaining ESR columns filled in
# because they cost almost nothing inside the same deck and because every
# (cap, ESR) pair here EXCEPT 100 mOhm is also a `sim/loop-stability/` grid
# point -- which is what makes the anchor phase's cross-check possible.
CEFFS_F = (1.0e-6, 4.7e-6)
ESRS_OHM = (0.001, 0.05, 0.1, 0.2, 0.5)


# --- ngspice startup file ---------------------------------------------------
# Written into the run's work directory, which every ngspice invocation this
# driver makes (including the cross-check's) uses as its cwd. ngspice reads
# `.spiceinit` from the current directory in preference to the user's home
# directory, so this pins the two startup settings that would otherwise be a
# silent, per-host, unrecorded input to the evidence:
#
#   wnflag=1      model binning divides W by nf. gf180mcu's widest model bin
#                 is W <= 100.01 um and the pass device is W=2800u nf=40, so
#                 with wnflag=0 the deck does not even parse ("could not find
#                 a valid modelname"). ngspice only defaults this to 1 in
#                 HSPICE/Spectre compatibility mode. Also set as a `.options`
#                 card inside the deck itself; see the deck's header.
#   num_threads=1 the sweep already runs one ngspice process per PVT point,
#                 so per-process threading buys nothing and costs
#                 reproducibility (#182 ruled thread count out as the cause
#                 of the drift it investigated only by pinning it).
SPICEINIT = "set wnflag=1\nset num_threads=1\n"


# ---------------------------------------------------------------------------
# deck rendering / running
# ---------------------------------------------------------------------------
def dc_seed_lines(pvt, ssr_cmd: str) -> str:
    """`.nodeset` cards that start Newton on the intended soft-start branch.

    Same device as `sim/loop-stability/`'s `dc_seed_lines()` and used the same
    way -- only on a retry of a point that already failed the landing check,
    never on the default path -- but seeded for the ramp state rather than
    the settled one: FB at the reference (true at every point of the ramp),
    VOUT at what the divider then makes it, and `ldo_ilimit`'s clamp gate
    parked at VIN, i.e. off. `ldo_softstart`'s own `CLG` node is NOT seeded:
    it no longer exists, #189 replaced the clamp comparator with FB
    injection.

    A `.nodeset` is a first-guess constraint ngspice releases after the first
    solve pass: it selects which of the circuit's DC solutions Newton walks
    to, it does not create one, and the retry is held to exactly the same
    landing check as the first attempt.
    """
    try:
        vout = min(1.5 * float(ssr_cmd), VOUT_NOM_V)
    except ValueError:            # the anchor phase's "free"
        vout = VOUT_NOM_V
    return "\n".join([
        f".nodeset v(VOUT)={vout:g} v(XDUT.FB)={VREF_V:g}",
        f".nodeset v(XDUT.Xilimit.CLG)={pvt.vdd:g}",
    ])


def render_deck(pvt, pdk, *, phase: str, variant: str, netlist: Path,
                ceffs, esrs, ac_dec, dc_seed: str = "",
                ssr_values=None) -> str:
    """Render the deck template for one (PVT, variant, phase).

    ``ssr_values`` narrows the phase's ramp-state list to a subset (used by
    the single-point attribution and curve runs); ``None`` means "the whole
    list this phase is defined by".
    """
    spec = dict(PHASES[phase])
    if ssr_values is not None and spec["ssr"] is not None:
        spec["ssr"] = tuple(float(v) for v in ssr_values)
    if spec["ssr"] is None:
        ssr_source = ("* SSR is NOT pinned in this phase: the port is left "
                      "unconnected, which\n* makes this deck electrically "
                      "sim/loop-stability/'s.")
        ssr_alter = "* (nothing to alter -- SSR is free)"
        ssr_list = "free"
    else:
        ssr_source = f"Vssr SSRPIN 0 DC {spec['ssr'][0]:g}"
        ssr_alter = "alter Vssr = $ss"
        ssr_list = " ".join(f"{v:g}" for v in spec["ssr"])
    return deck.render_file(TEMPLATE, {
        **deck.pvt_subs(pdk, pvt.corner, pvt.temp_c, pvt.vdd, netlist),
        "CORNER_ID": pvt.corner_id,
        "CORNER_NAME": pvt.corner.name,
        "AC_DEC": str(ac_dec),
        "F_START": F_START,
        "F_STOP": F_STOP,
        "CEFF_LIST": " ".join(f"{v:g}" for v in ceffs),
        "ESR_LIST": " ".join(f"{v:g}" for v in esrs),
        "ILOAD": f"{spec['iload_a']:g}",
        "RLOAD": f"{spec['rload_ohm']:g}",
        "PHASE": phase,
        "VARIANT": variant,
        "SSR_SOURCE": ssr_source,
        "SSR_ALTER": ssr_alter,
        "SSR_LIST": ssr_list,
        "DC_SEED": dc_seed,
    })


def run_point(pvt, pdk, *, phase: str, variant: str, netlist: Path, ceffs, esrs,
              ac_dec, workdir: Path, logdir: Path, dc_seed: str = "",
              ssr_values=None, stem: str | None = None):
    """Run one (PVT, variant, phase) deck. Returns (pvt, rows, error-or-None)."""
    suffix = "_dcseed" if dc_seed else ""
    stem = stem or f"{pvt.corner_id}_{variant}_{phase}{suffix}"
    deck = workdir / f"{stem}.spice"
    deck.write_text(render_deck(pvt, pdk, phase=phase, variant=variant,
                                netlist=netlist, ceffs=ceffs, esrs=esrs,
                                ac_dec=ac_dec, dc_seed=dc_seed,
                                ssr_values=ssr_values))
    log = logdir / f"{stem}.log"
    try:
        text = run_ngspice_deck(deck, log, workdir)
    except RuntimeError as exc:
        return pvt, [], str(exc)
    rows, err = rows_from_log(pvt, text, phase=phase, variant=variant, ceffs=ceffs,
                              esrs=esrs, ssr_values=ssr_values, log=log)
    return pvt, rows, err


def rows_from_log(pvt, text: str, *, phase: str, variant: str, ceffs, esrs,
                  ssr_values, log: Path):
    """Parse a deck's ``ROW`` lines and apply the landing rule. -> (rows, error | None).

    Shared by the local ngspice path and the ``klt sim`` path (``klt_run.py``
    writes the same ``ROW`` lines), so both enter a record through one parser
    and one landing check.
    """
    rows: list[Row] = []
    for line in text.splitlines():
        if not line.startswith("ROW "):
            continue
        try:
            f = parse_row_fields(line)
        except ValueError as exc:
            return [], f"{exc} (see {display_path(log)})"
        rows.append(Row(
            corner_id=pvt.corner_id, corner=pvt.corner.name,
            temp_c=pvt.temp_c, vin_v=pvt.vdd,
            iload_a=PHASES[phase]["iload_a"],
            **base_row_kwargs(f),
            variant=variant, phase=phase, ssr_cmd=f["ssr_cmd"],
            ssr_v=nan_or(f["ssr_v"]), fb_v=nan_or(f["fb_v"]),
            isup_a=nan_or(f["isup_a"]),
            load_model=PHASES[phase]["load_model"],
            rload_ohm=PHASES[phase]["rload_ohm"],
        ))

    if PHASES[phase]["ssr"] is None:
        n_ssr = 1
    elif ssr_values is not None:
        n_ssr = len(ssr_values)
    else:
        n_ssr = len(PHASES[phase]["ssr"])
    expected = n_ssr * len(ceffs) * len(esrs)
    if len(rows) != expected:
        return rows, f"expected {expected} rows, parsed {len(rows)} (see {display_path(log)})"

    bad = [r for r in rows if r.landed]
    if bad:
        w = bad[0]
        return rows, (
            f"{len(bad)}/{len(rows)} points did not land on the intended DC "
            f"branch; first is {w.state_id} / {w.cfg_id}: {w.landed}. A "
            f"loop-gain margin about a bias point that is not the one named is "
            f"meaningless, so this run is void (see {display_path(log)})"
        )
    return rows, None


def run_curve(pvt, pdk, row: Row, netlist: Path, ac_dec, logdir: Path,
              workdir: Path, tag: str) -> Path:
    """Re-run one single configuration with the whole T(f) curve printed.

    Same device as `sim/loop-stability/`'s `run_curve()`: the record cites a
    scalar margin, and the curve behind it has to be in the evidence too.
    """
    ssr_values = None if PHASES[row.phase]["ssr"] is None else [row.ssr_cmd]
    text = render_deck(pvt, pdk, phase=row.phase, variant=row.variant,
                       netlist=netlist, ceffs=[row.ceff_f], esrs=[row.esr_ohm],
                       ac_dec=ac_dec, ssr_values=ssr_values)
    header = (
        f"* full loop-gain curve T(f) for this record's {tag} point\n"
        f"* corner={pvt.corner_id} variant={row.variant} phase={row.phase} "
        f"ssr={row.ssr_cmd} ceff={fmt_uf(row.ceff_f)} esr={fmt_esr(row.esr_ohm)}\n"
    )
    return print_curve_log(text, header, logdir / f"{pvt.corner_id}_{tag}.log",
                              workdir / f"{pvt.corner_id}_{tag}.spice", cwd=workdir)


def parse_curve(path: Path) -> list[tuple[float, float, float]]:
    """(f, |T| dB, unwrapped phase deg) from a run_curve() log.

    ngspice's `print` emits the two vectors in column groups, each group
    repeating the frequency axis, so the rows are read positionally and then
    re-joined on frequency.
    """
    rows: list[tuple[float, float, float]] = []
    for ln in path.read_text().splitlines():
        parts = ln.split()
        if len(parts) == 4 and re.fullmatch(r"\d+", parts[0]):
            try:
                f, a, b = float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError:
                continue
            rows.append((f, a, b))
    return rows


# ---------------------------------------------------------------------------
# the DC hand-over transfer
# ---------------------------------------------------------------------------


def render_handover_deck(pvt, pdk, *, variant: str, netlist: Path,
                         ssr_values=HANDOVER_SSR_V) -> str:
    return deck.render_file(HANDOVER_TEMPLATE, {
        **deck.pvt_subs(pdk, pvt.corner, pvt.temp_c, pvt.vdd, netlist),
        "CORNER_ID": pvt.corner_id,
        "CORNER_NAME": pvt.corner.name,
        "VARIANT": variant,
        "SSR_LIST": " ".join(f"{v:g}" for v in ssr_values),
    }, source="hand-over template")


def run_handover(pvt, pdk, *, variant: str, netlist: Path, workdir: Path,
                 logdir: Path):
    """Run one (PVT, variant) hand-over transfer. -> (curve, error-or-None)."""
    stem = f"{pvt.corner_id}_{variant}_handover"
    deck = workdir / f"{stem}.spice"
    deck.write_text(render_handover_deck(pvt, pdk, variant=variant,
                                         netlist=netlist))
    log = logdir / f"{stem}.log"
    try:
        text = run_ngspice_deck(deck, log, workdir)
    except RuntimeError as exc:
        return None, str(exc)
    return curve_from_log(pvt, variant, text, log)


def curve_from_log(pvt, variant: str, text: str, log: Path):
    """Parse a hand-over deck's ``HOV`` lines. -> (curve, error | None).

    Shared by the local path and the ``klt sim`` path (``klt_run.py`` writes
    the same ``HOV`` lines).
    """
    pts: list[HovPoint] = []
    for line in text.splitlines():
        if not line.startswith("HOV "):
            continue
        try:
            f = parse_hov_fields(line)
        except ValueError as exc:
            return None, f"{exc} (see {display_path(log)})"
        pts.append(HovPoint(
            ssr_cmd=float(f["ssr_cmd"]),
            ssr_v=parse_opt_float(f["ssr_v"]),
            fb_v=parse_opt_float(f["fb_v"]),
            vout_v=parse_opt_float(f["vout_v"]),
            pg_v=parse_opt_float(f["pg_v"]),
            erramp_v=parse_opt_float(f["erramp_v"]),
            isup_a=parse_opt_float(f["isup_a"]),
        ))
    if len(pts) != len(HANDOVER_SSR_V):
        return None, (f"expected {len(HANDOVER_SSR_V)} HOV points, parsed "
                      f"{len(pts)} (see {display_path(log)})")
    if any(p.ssr_v is None or p.fb_v is None or p.vout_v is None for p in pts):
        return None, f"a HOV point has an unparsable operating point (see {display_path(log)})"
    return HovCurve(corner_id=pvt.corner_id, corner=pvt.corner.name,
                    temp_c=pvt.temp_c, vin_v=pvt.vdd, variant=variant,
                    points=pts), None


def handover_consistency(curves: list[HovCurve], rows: list[Row]):
    """Worst |dVOUT| between a HOV point and the ROW at the same ramp state.

    The two decks are different files running different analyses; they are
    only comparable because they are deliberately the same circuit at the same
    operating point. This measures that rather than asserting it. Compared
    only against the `ramp` phase (the shared resistive load model) at the
    1 uF / 100 mOhm output network.
    """
    by_key = {(c.corner_id, c.variant): c for c in curves}
    worst = None
    n = 0
    for r in rows:
        if r.phase != "ramp":
            continue
        if abs(r.ceff_f - 1e-6) > 1e-15 or abs(r.esr_ohm - 0.1) > 1e-12:
            continue
        c = by_key.get((r.corner_id, r.variant))
        if c is None:
            continue
        hov = min(c.points, key=lambda p: abs(p.ssr_v - r.ssr_v))
        if abs(hov.ssr_v - r.ssr_v) > 1e-6:
            continue
        d = abs(hov.vout_v - r.vout_v)
        n += 1
        if worst is None or d > worst[0]:
            worst = (d, r, hov)
    return worst, n


HANDOVER_CSV_HEADER = [
    "corner_id", "corner", "temp_c", "vin_v", "variant", "ssr_cmd_v", "ssr_v",
    "fb_v", "vout_v", "iinj_ua", "pass_gate_v", "erramp_out_v", "isup_a",
    "in_regulation",
]


def write_handover_csv(path: Path, curves: list[HovCurve]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HANDOVER_CSV_HEADER)
        for c in curves:
            for p in c.points:
                w.writerow([
                    c.corner_id, c.corner, f"{c.temp_c:g}", f"{c.vin_v:.2f}",
                    c.variant, f"{p.ssr_cmd:g}", f"{p.ssr_v:.6f}",
                    f"{p.fb_v:.6f}", f"{p.vout_v:.6f}",
                    f"{p.iinj_a * 1e6:.5f}", f"{p.pg_v:.6f}",
                    f"{p.erramp_v:.6f}", f"{p.isup_a:.6e}",
                    "yes" if p.in_regulation else "no",
                ])


# ---------------------------------------------------------------------------
# reporting helpers
# ---------------------------------------------------------------------------
CSV_HEADER = [
    "corner_id", "process", "temp_c", "vin_v", "variant", "phase",
    "ssr_cmd", "ssr_v", "load_model", "iload_ma", "rload_ohm",
    "ceff_uf", "esr_ohm", "vout_v", "fb_v", "iinj_ua", "isup_ma",
    "dc_loop_gain_db", "f_crossover_hz", "phase_margin_deg",
    "f_180_hz", "gain_margin_db", "resurgence_db",
    "margin_vs_dr0001", "resurgence_vs_dr0008",
]


def csv_row(r: Row) -> list[str]:
    return [
        r.corner_id, r.corner, f"{r.temp_c:g}", f"{r.vin_v:g}", r.variant,
        r.phase, r.ssr_cmd, f"{r.ssr_v:.6g}", r.load_model,
        f"{r.iload_a * 1e3:g}", f"{r.rload_ohm:g}",
        f"{r.ceff_f * 1e6:g}", f"{r.esr_ohm:g}",
        f"{r.vout_v:.6g}", f"{r.fb_v:.6g}", f"{r.iinj_a * 1e6:.4g}",
        f"{r.isup_a * 1e3:.4g}", f"{r.dcgain_db:.4g}",
        "" if r.f0_hz is None else f"{r.f0_hz:.6g}",
        pm_str(r),
        "" if r.f180_hz is None else f"{r.f180_hz:.6g}",
        gm_str(r),
        "" if r.resurgence_db is None else f"{r.resurgence_db:.4g}",
        "no-crossover" if r.pm_deg is None else ("PASS" if r.passes else "FAIL"),
        "n/a" if r.resurgence_db is None else ("FAIL" if r.resurges else "PASS"),
    ]


def write_matrix_csv(path: Path, rows: list[Row]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for r in rows:
            w.writerow(csv_row(r))


# ---------------------------------------------------------------------------
# pole/zero attribution
# ---------------------------------------------------------------------------
# The injection element can only reach the main loop through the nodes it
# touches: `Binj_ss` and `Mpre_b_ss`'s drain on FB, `Mhold_ss`'s drain on
# PASS_GATE, `Mhold_bg_ss`'s on BG. Each entry below removes ONE of those
# couplings in AC only, leaving the DC operating point bit-identical (see
# netlist_variants.ac_open / ac_short), so the margin delta it produces is
# attributable to that coupling and to nothing else. This is the
# element-removal sensitivity the record's attribution rests on; it is a
# measurement, not a reading of the schematic.
#
# RESOLVED (issue #234, was tracked here since #231/PR #233): this set used
# to have two more rows, `acopen-fb-inj` (Binj_ss AC-opened from FB) and
# `acshort-gmsum` (the device-level chain's GMSUM mirror node AC-shorted to
# VIN). Both are DROPPED, not re-derived, for reasons specific to each:
#
#   * `acopen-fb-inj` is a structural no-op against `Binj_ss`, and there is no
#     honest replacement in the same "remove a coupling" shape. `Binj_ss`'s
#     defining expression --
#         I = max(0, (v(VREF) - v(SSR)) * 5.0e-6) * (v(EN) > 1.4)
#     -- depends on VREF, SSR and EN only. It has NO dependence on v(FB), so
#     its small-signal admittance out of FB is already exactly zero and the
#     current it injects does not vary with anything this deck's AC probe
#     perturbs. That is not a small coupling this experiment failed to
#     remove; it is the source having no AC coupling to attribute in the
#     first place -- an ideal current source already IS an AC open. A 1 GH
#     series inductor (`ac_open()`'s only shape) cannot demonstrate that any
#     more precisely than the algebra above already has, which is why
#     `ac_open()` now refuses a `B`-prefixed instance outright instead of
#     applying and reporting a zero.
#   * `acshort-gmsum` targeted a node (`GMSUM`) that exists only in the
#     post-#195 device-level Mgm* transconductor chain #231 reverted. There is
#     nothing left in `ldo_softstart` to short. `add_cap()` (shared by
#     `ac_short()`/`ac_load()`) now refuses a node that is not already a
#     token in the netlist, so this class of mistake can no longer apply
#     silently either.
#
# Net effect: with `Binj_ss` in place, the only REAL FB couplings left to
# attribute are `XMpre_b_ss`'s drain (`acopen-fb-pre`, below) and the
# deliberate `FB_CAP_LADDER_F` parasitic budget further down this file --
# which is exactly the legitimate "both rows drop" outcome this issue's
# acceptance criteria named as acceptable. Both guard rails above are
# regression-tested by `TestNetlistTransforms` in
# `sim/tests/test_soft_start_loop_gain.py`, including reproducing these two
# exact historical calls and asserting they now raise.
#
# `sim/soft-start-loop-gain/records/20260910-015601-2387ece.md` is untouched:
# it was measured against the device-level chain, for which both rows were
# real measurements, and stays valid for that netlist.
#
# `acopen-fb-inj` IS RESTORED BY #246; `acshort-gmsum` IS NOT. DR-0023's
# cascoded mirror puts the device-level chain back into
# `design/ldo_softstart.sch`, so both retired rows have a real target again --
# and the two are restored on different evidence, so they are treated
# differently rather than as a pair:
#
#   * `acopen-fb-inj` is RESTORED, retargeted from `XMgmo_ss` to `XMgmc_ss`.
#     The cascode's drain is what sits on FB now, so this row measures exactly
#     what target T6 (`design/softstart_injection_compensation.md` section 3)
#     is written against: the element's ENTIRE small-signal loading of the
#     feedback node, with the operating-point shift held out (a 1 GH series
#     inductor is a short at DC). Without it, nothing in this repo can issue a
#     T6 verdict on the cascoded element, and issue #246's own acceptance
#     criteria ask for one. It is a real instance with a real drain on a real
#     node, so `ac_open()`'s #234 guard rails admit it; the B-source refusal
#     that retired it applied to `Binj_ss`, which no longer exists.
#   * `acshort-gmsum` stays RETIRED. `GMSUM` is a netlist token again, so
#     `add_cap()` would no longer refuse it -- but #234 retired it for the
#     stronger of its two reasons as well: the row never resolved a pole or a
#     zero (max |dT| 0.003 dB over 0.01 Hz - 1 GHz, below the 0.02 dB
#     numerical floor, `design/softstart_injection_compensation.md` section 1).
#     A row that returns a null result at ten times the cost of the guard that
#     replaced it is not worth re-running merely because its target exists
#     again. If a later record needs it, restoring it is one line here.
#
# `sim/soft-start-loop-gain/records/20260910-015601-2387ece.md` is untouched
# either way: it was measured against the UNCASCODED device-level chain, and
# both rows were real measurements for that netlist.
ATTRIBUTIONS = (
    ("acopen-fb-inj", "XMgmc_ss's drain AC-opened from FB",
     lambda t: nv.ac_open(t, "XMgmc_ss", "FB", "acopeninj")),
    ("acopen-fb-pre", "XMpre_b_ss's drain AC-opened from FB",
     lambda t: nv.ac_open(t, "XMpre_b_ss", "FB", "acopenpre")),
    ("acopen-hold", "XMhold_ss's drain AC-opened from PASS_GATE",
     lambda t: nv.ac_open(t, "XMhold_ss", "PASS_GATE", "acopenhold")),
)


# --- how much capacitance the feedback node actually tolerates --------------
# `design/ldo_softstart.sch`'s regression note states a hypothesis: "ANY
# nonzero parasitic capacitance the real transconductor adds to FB (the 'tens
# of femtofarads' already called out under WHAT THIS COSTS THE MAIN LOOP) is
# enough to destabilize the main loop's hold-release transient". That is a
# falsifiable claim about a margin, and the way to test it is not to remove
# the element's parasitic and find the delta small -- that only says THIS
# element is cheap. It is to ADD known capacitance to `FB` until the margin
# bar is crossed, which turns the answer into a budget the next injection
# element can be designed against.
#
# Every value is a capacitor, so every one is DC-inert and the operating point
# is bit-identical across the whole ladder -- the record prints the landed
# VOUT for each so that is checkable rather than asserted.
FB_CAP_LADDER_F = (10e-15, 100e-15, 1e-12, 3e-12, 10e-12, 30e-12, 100e-12,
                   300e-12, 1e-9)


def _sub(curve: list[tuple[float, float, float]], n: int = 160):
    """Log-uniform subsample of a T(f) curve, for the fit below."""
    if len(curve) <= n:
        return curve
    step = len(curve) / float(n)
    return [curve[int(i * step)] for i in range(n)]


def fit_pole_zero(num: list[tuple[float, float, float]],
                  den: list[tuple[float, float, float]]):
    """Fit ``k*(1+jf/fz)/(1+jf/fp)`` to the ratio of two measured T(f) curves.

    ``num``/``den`` are ``run_curve`` outputs (f, |T| dB, phase deg) for two
    decks that differ in exactly one coupling. Their ratio is, for a single
    added R-C on a node, exactly one pole and one zero, so this fit is a
    statement the data can refute: the residual is reported alongside the fit
    and a bad residual means the single-pole/zero reading is wrong, not that
    the numbers should be trusted anyway.

    Returns ``(k_db, fz, fp, rms_residual_db_deg)`` or ``None`` if the two
    curves do not share a frequency axis.
    """
    a, b = _sub(num), _sub(den)
    if len(a) != len(b) or not a:
        return None
    pts = []
    for (fa, ma, pa), (fb_, mb, pb) in zip(a, b):
        if abs(fa - fb_) > 1e-9 * max(fa, 1.0):
            return None
        pts.append((fa, ma - mb, pa - pb))
    lo = min(f for f, _, _ in pts if f > 0)
    hi = max(f for f, _, _ in pts)
    k_db = pts[0][1]

    def resid(fz: float, fp: float) -> float:
        s = 0.0
        for f, dm, dp in pts:
            h = complex(1, f / fz) / complex(1, f / fp)
            m = k_db + 20 * math.log10(abs(h))
            ph = math.degrees(math.atan2(h.imag, h.real))
            s += (m - dm) ** 2 + ((ph - dp) / 10.0) ** 2
        return s / len(pts)

    grid = [lo * (hi / lo) ** (i / 59.0) for i in range(60)]
    best = None
    for fz in grid:
        for fp in grid:
            r = resid(fz, fp)
            if best is None or r < best[0]:
                best = (r, fz, fp)
    # one refinement pass around the coarse optimum
    _, fz0, fp0 = best
    for _ in range(3):
        fzs = [fz0 * (1.15 ** (i - 6)) for i in range(13)]
        fps = [fp0 * (1.15 ** (i - 6)) for i in range(13)]
        for fz in fzs:
            for fp in fps:
                r = resid(fz, fp)
                if r < best[0]:
                    best = (r, fz, fp)
        _, fz0, fp0 = best
    return k_db, best[1], best[2], math.sqrt(best[0])


def curve_extremes(num, den):
    """Largest |dB| and |deg| difference between two aligned T(f) curves.

    Returned as ``(max_dmag_db, f_at_max_dmag, max_dphase_deg, f_at_max)``.
    This is the primary, model-free number for a sensitivity case: the
    pole/zero fit below is an interpretation of it, and if this is at the
    numerical floor there is nothing to interpret.
    """
    if len(num) != len(den) or not num:
        return None
    best_m = best_p = (0.0, 0.0)
    for (fa, ma, pa), (fb, mb, pb) in zip(num, den):
        if abs(fa - fb) > 1e-9 * max(fa, 1.0):
            return None
        if abs(ma - mb) > abs(best_m[0]):
            best_m = (ma - mb, fa)
        if abs(pa - pb) > abs(best_p[0]):
            best_p = (pa - pb, fa)
    return best_m[0], best_m[1], best_p[0], best_p[1]


def delta_table(num, den, decades=(1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7)):
    """|T| and phase difference between two curves at fixed frequencies."""
    out = []
    for target in decades:
        best = min(num, key=lambda r: abs(math.log10(max(r[0], 1e-12)) - math.log10(target)))
        mate = min(den, key=lambda r: abs(r[0] - best[0]))
        out.append((best[0], best[1] - mate[1], best[2] - mate[2]))
    return out


# ---------------------------------------------------------------------------
# cross-check against sim/loop-stability/
# ---------------------------------------------------------------------------
LS_MATRIX_CSV = (REPO_ROOT / "sim" / "loop-stability" / "records"
                 / "20260906-071437-fff0bf0-matrix.csv")


def run_loop_stability_here(args, workdir: Path, logdir: Path, corners, temps,
                            backend: str = "local"):
    """Run `sim/loop-stability/`'s OWN sweep, unmodified, on this host.

    The point of running it rather than only reading its committed record is
    that `sim/README.md`'s reproducibility caveat (#182/#185) says a delta
    between two records taken on different hosts with different ngspice
    binaries is toolchain provenance, not evidence about the design. A
    same-host, same-binary, same-session run has no toolchain term in it at
    all, so it is the comparison that can actually say something about this
    deck.

    It is invoked as its own entry point with its own flags -- nothing about
    it is patched -- with cwd set to this run's work directory so it picks up
    the same `.spiceinit` every other ngspice invocation here uses.
    """
    cmd = [
        sys.executable, str(_LS_PATH),
        "--corners", *corners,
        "--temps", *[f"{t:g}" for t in temps],
        "--supply-tol", f"{args.supply_tol:g}",
        "--loads-ma", f"{RATED_LOAD_A * 1e3:g}",
        "--caps-uf", *[f"{c * 1e6:g}" for c in CEFFS_F],
        "--esrs", *[f"{e:g}" for e in ESRS_OHM],
        "--ac-dec", str(args.ac_dec),
        "--no-write", "--backend", backend,
    ]
    # A grid goes to the fleet through loop-stability's own `klt sim` front end,
    # never to a local fan-out on this host (issue #451).
    cmd += ["-j", str(args.jobs)] if backend == "local" else ["--in-flight", str(args.in_flight)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(workdir))
    out = proc.stdout + proc.stderr
    (logdir / "loop-stability-rerun.console.log").write_text(
        "* `sim/loop-stability/testbench/sweep.py` run unmodified on this host,\n"
        "* in this session, for this record's cross-check. Command:\n"
        f"*   {' '.join(cmd)}\n"
        f"* (cwd = this run's work directory, so the same .spiceinit applies)\n\n"
        + out
    )
    m = re.search(r"record id\s*:\s*(\S+)", out)
    if not m:
        return None, "could not find the re-run's record id in its output"
    rerun_dir = REPO_ROOT / "sim" / ".work" / "loop-stability" / m.group(1)
    if not rerun_dir.is_dir():
        return None, f"the re-run left no logs at {rerun_dir}"
    rows: dict[tuple, dict] = {}
    dest = logdir / "loop-stability-rerun"
    dest.mkdir(parents=True, exist_ok=True)
    for log in sorted(rerun_dir.glob("*.log")):
        shutil.copyfile(log, dest / log.name)
        corner_id = log.stem
        for line in log.read_text().splitlines():
            if not line.startswith("ROW "):
                continue
            f = loop_margin.parse_row_fields(line)
            rows[(corner_id, float(f["ceff_f"]), float(f["esr_ohm"]))] = {
                "vout_v": parse_opt_float(f["vout_v"]),
                "f0_hz": parse_opt_float(f["f0_hz"]),
                "pm_deg": (None if parse_opt_float(f["phase_at_f0_deg"]) is None
                           else 180.0 + parse_opt_float(f["phase_at_f0_deg"])),
                "gm_db": (math.inf if parse_opt_float(f["gain_at_f180_db"]) is None
                          else -parse_opt_float(f["gain_at_f180_db"])),
            }
    if not rows:
        return None, "the re-run produced no ROW lines"
    return rows, None


def read_committed_ls_matrix() -> dict[tuple, dict]:
    """The committed loop-stability matrix, keyed the same way."""
    out: dict[tuple, dict] = {}
    if not LS_MATRIX_CSV.exists():
        return out
    with LS_MATRIX_CSV.open() as fh:
        for row in csv.DictReader(fh):
            if float(row["iload_ma"]) != RATED_LOAD_A * 1e3:
                continue
            key = (row["corner_id"], float(row["ceff_uf"]) * 1e-6,
                   float(row["esr_ohm"]))
            gm = row["gain_margin_db"]
            out[key] = {
                "vout_v": float(row["vout_v"]),
                "f0_hz": float(row["f_crossover_hz"]) if row["f_crossover_hz"] else None,
                "pm_deg": None if row["phase_margin_deg"] in ("", "n/a")
                          else float(row["phase_margin_deg"]),
                "gm_db": math.inf if gm == "inf" else float(gm),
            }
    return out


def compare_anchor(anchor_rows: list[Row], other: dict[tuple, dict]):
    """Join this experiment's anchor rows against a loop-stability matrix."""
    deltas = []
    for r in anchor_rows:
        ref = other.get((r.corner_id, r.ceff_f, r.esr_ohm))
        if ref is None:
            continue
        dpm = (None if r.pm_deg is None or ref["pm_deg"] is None
               else r.pm_deg - ref["pm_deg"])
        dgm = (None if math.isinf(r.gm_db) or math.isinf(ref["gm_db"])
               else r.gm_db - ref["gm_db"])
        df0 = (None if r.f0_hz is None or not ref["f0_hz"]
               else (r.f0_hz - ref["f0_hz"]) / ref["f0_hz"])
        deltas.append((r, ref, dpm, dgm, df0))
    return deltas


def xcheck_verdict(deltas):
    """(ok, worst dPM, worst dGM, worst relative df0, n compared)."""
    if not deltas:
        return False, None, None, None, 0
    wpm = max((abs(d[2]) for d in deltas if d[2] is not None), default=0.0)
    wgm = max((abs(d[3]) for d in deltas if d[3] is not None), default=0.0)
    wf0 = max((abs(d[4]) for d in deltas if d[4] is not None), default=0.0)
    ok = (wpm <= XCHECK_PM_TOL_DEG and wgm <= XCHECK_GM_TOL_DB
          and wf0 <= XCHECK_F0_TOL_FRAC)
    return ok, wpm, wgm, wf0, len(deltas)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--corners", nargs="+", default=list(PROCESS_CORNERS))
    ap.add_argument("--temps", nargs="+", type=float, default=list(TEMPS_C))
    ap.add_argument("--supply-tol", type=float, default=SUPPLY_TOL)
    ap.add_argument("--variants", nargs="+", default=list(nv.DUT_VARIANTS),
                    choices=list(nv.DUT_VARIANTS))
    ap.add_argument("--phases", nargs="+", default=list(PHASES),
                    choices=list(PHASES))
    ap.add_argument("--caps-uf", nargs="+", type=float,
                    default=[c * 1e6 for c in CEFFS_F])
    ap.add_argument("--esrs", nargs="+", type=float, default=list(ESRS_OHM))
    ap.add_argument("--ac-dec", type=int, default=int(AC_DEC),
                    help=f"AC points per decade (default {AC_DEC}, "
                         "sim/loop-stability's own resolution policy, issue "
                         "#58 -- running below it needs --subset-reason)")
    klt_grid.add_grid_args(
        ap, batch_unit="(variant, phase, C_eff, ESR) configuration",
        batch_extra=", and the DC hand-over transfer is one `op` request per "
                    "variant")
    ap.add_argument("--explore", action="store_true",
                    help="tt/27C/3.3V only; implies --no-write")
    ap.add_argument("--skip-crosscheck", action="store_true",
                    help="do not re-run sim/loop-stability/ for the anchor "
                         "cross-check (implies the record cannot claim it)")
    ap.add_argument("--skip-handover", action="store_true",
                    help="do not run the dense DC hand-over transfer sweep "
                         "(implies the record cannot report the injection "
                         "element's transfer, only its margins)")
    ap.add_argument("--author",
                    default=os.environ.get("SS_LOOP_GAIN_AUTHOR",
                                           "agent-builder (issue #196)"))
    return ap


def _klt_axes(grid, corners, temps) -> dict:
    return {"process": tuple(c.name for c in corners), "temps": tuple(temps),
            "supplies": tuple(sorted({p.vdd for p in grid}))}


BAD_DECK = "klt reported a problem for this deck (see warnings above)"


def run_grid_klt(grid, corners, args, ceffs, esrs, netlists, logdir: Path,
                 klt_backend: str):
    """Run the margin grid through ``klt sim`` (``klt_run.py``) instead of local ngspice.

    One request per (variant, phase, C_eff, ESR) over the whole PVT grid, the
    ramp state a ``corners.params`` row. The returned values are written per
    (corner, variant, phase) as ``<corner>_<variant>_<phase>.log`` ``ROW``
    lines and parsed by ``rows_from_log()`` -- the parser and landing rule the
    local path uses. A deck that misses the intended DC branch is re-run once,
    whole, with ``dc_seed_lines()`` in the body (log ``..._dcseed.log``), and
    voided if it still misses, exactly as the local path does. Returns
    ``(rows, failures, seeded, voided, info)``; never falls back to local.
    """
    phases = {p: PHASES[p] for p in args.phases}
    print(f"klt sim   : {len(args.variants) * len(phases) * len(ceffs) * len(esrs)} "
          f"requests x {len(grid)} corners, backend {klt_backend}")
    results, problems, bad = klt_run.run_margin(
        args.variants, phases, ceffs, esrs, netlists, args.ac_dec, F_START, F_STOP,
        _klt_axes(grid, corners, args.temps), logdir, klt_backend, args.in_flight)
    for pr in problems:
        print(f"  WARNING {pr}", file=sys.stderr)

    def parse(key, res, suffix=""):
        pvt, variant, phase = key
        text = klt_run.margin_log(pvt.corner_id, variant, phase, PHASES[phase],
                                  ceffs, esrs, res)
        log = logdir / f"{pvt.corner_id}_{variant}_{phase}{suffix}.log"
        log.write_text(text)
        return rows_from_log(pvt, text, phase=phase, variant=variant, ceffs=ceffs,
                             esrs=esrs, ssr_values=None, log=log)

    def run_retry(key):
        pvt, variant, phase = key
        one = {"process": (pvt.corner.name,), "temps": (pvt.temp_c,), "supplies": (pvt.vdd,)}
        res, probs, _ = klt_run.run_margin(
            [variant], {phase: PHASES[phase]}, ceffs, esrs, netlists, args.ac_dec,
            F_START, F_STOP, one, logdir, klt_backend, args.in_flight,
            dc_seed=dc_seed_lines(pvt, "free"))
        return res, probs

    def say(key, event, detail):
        pvt, variant, phase = key
        head = f"  {pvt.corner_id:<18} {variant:<7} {phase:<7}"
        if event == "retry":
            print(f"{head} DC branch miss, retrying with the intended-branch seed")
        elif event == "voided":
            # Still refuses the intended branch with the seed: the deck is
            # voided (named in the record, excluded from the row set), not a
            # run-wide failure.
            print(f"{head} VOIDED (no DC branch near VREF, even seeded) {detail}")
        else:
            print(f"{head} SIM ERROR {detail}")

    def report(key, pt_rows, note):
        pvt, variant, phase = key
        measured = [r for r in pt_rows if r.pm_deg is not None]
        w = worst_of(measured) if measured else pt_rows[0]
        print(f"  {pvt.corner_id:<18} {variant:<7} {phase:<7} worst PM "
              f"{pm_str(w):>7} deg GM {gm_str(w):>7} dB{note}"
              + ("" if measured else "  (no crossover at any point)"))

    keys = [(pvt, variant, phase) for pvt in grid
            for variant in args.variants for phase in args.phases]
    rows, failures, seeded, voided = klt_grid.run_retry_grid(
        keys, results, bad, parse=parse, run_retry=run_retry,
        miss_marker="did not land on the intended DC branch",
        name=lambda k: f"{k[0].corner_id}/{k[1]}/{k[2]}",
        bad_key=lambda k: (k[0].corner_id, k[1], k[2]),
        bad_message=BAD_DECK, retry_problem=lambda err, probs: BAD_DECK,
        say=say, report=report, void_on_miss=True)
    info = {"backend": klt_backend, "klt": klt_run.klt_version(),
            "requests": len(args.variants) * len(phases) * len(ceffs) * len(esrs)}
    return rows, failures, seeded, voided, info


def run_handover_klt(grid, corners, args, netlists, logdir: Path, klt_backend: str):
    """The DC hand-over transfer through ``klt sim``: one ``op`` request per variant.

    V(SSR) and the supply are zipped ``corners.params`` rows; the ``HOV``
    fields are ``expr`` measurements (the deck is ``op``-only, so there is no
    ``tian`` metric to map). Returns ``(curves, failures)``.
    """
    res, problems = klt_run.run_handover(
        args.variants, HANDOVER_SSR_V, netlists, _klt_axes(grid, corners, args.temps),
        logdir, klt_backend, args.in_flight)
    failures = [f"handover: {pr}" for pr in problems]
    curves: list[HovCurve] = []
    for variant in args.variants:
        for pvt in grid:
            text = klt_run.handover_log(pvt.corner_id, HANDOVER_SSR_V, res.get(variant, {}))
            log = logdir / f"{pvt.corner_id}_{variant}_handover.log"
            log.write_text(text)
            curve, err = curve_from_log(pvt, variant, text, log)
            if err:
                failures.append(f"{pvt.corner_id}/{variant}/handover: {err}")
            else:
                curves.append(curve)
    return curves, failures


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.explore:
        args.corners, args.temps, args.supply_tol = ["tt"], [27.0], 0.0
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
    stale = deck.require_fresh_netlists()
    if stale:
        print(stale, file=sys.stderr)
        return 3

    corners = resolve_corners(args.corners)
    supplies = supply_points(NOMINAL_SUPPLY_V, args.supply_tol)
    grid = build_grid(corners, args.temps, supplies)
    ceffs = [v * 1e-6 for v in args.caps_uf]
    esrs = list(args.esrs)

    full_pvt = (set(args.temps) >= set(TEMPS_C)
                and args.supply_tol >= SUPPLY_TOL
                and set(args.corners) >= set(PROCESS_CORNERS))
    full = (full_pvt
            and set(args.variants) >= set(nv.DUT_VARIANTS)
            and set(args.phases) >= set(PHASES)
            and set(args.caps_uf) >= {c * 1e6 for c in CEFFS_F}
            and set(args.esrs) >= set(ESRS_OHM)
            and args.ac_dec >= int(AC_DEC))
    if not args.no_write and not full and not args.subset_reason:
        print("FATAL: this grid is narrower than the one this experiment's "
              "README describes.\n       Re-run with the defaults, or pass "
              "--subset-reason '<why>' (copied verbatim into the record), or "
              "--no-write to just debug.", file=sys.stderr)
        return 3

    prov = git_provenance(REPO_ROOT)
    records_dir = EXPDIR / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    if args.no_write:
        record_id = format_record_id(prov["short"],
                                     _dt.datetime.now(_dt.timezone.utc))
    else:
        record_id = allocate_record_id(REPO_ROOT, records_dir, git=prov)

    workdir = REPO_ROOT / "sim" / ".work" / EXPDIR.name / record_id
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / ".spiceinit").write_text(SPICEINIT)
    logdir = EXPDIR / "corners" / record_id
    if args.no_write:
        logdir = workdir
    logdir.mkdir(parents=True, exist_ok=True)

    # --- DUT netlists ------------------------------------------------------
    netlists: dict[str, Path] = {}
    try:
        for variant in args.variants:
            text = nv.build_variant(REPO_ROOT, variant)
            p = workdir / f"ldo_core_{variant}.spice"
            p.write_text(text)
            netlists[variant] = p
    except nv.TransformError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 3

    print_provenance_banner(
        pdk, record_id, host=socket.gethostname(), dirty=prov["dirty"],
        note=" (NOT WRITTEN: --no-write)" if args.no_write else "")
    n_states = sum(1 if PHASES[p]["ssr"] is None else len(PHASES[p]["ssr"])
                   for p in args.phases)
    print(f"grid          : {len(grid)} PVT x {len(args.variants)} variant x "
          f"{n_states} ramp state x {len(ceffs)}x{len(esrs)} cap/ESR = "
          f"{len(grid) * len(args.variants) * n_states * len(ceffs) * len(esrs)} "
          f"loop-gain points")
    print()

    # On the `klt sim` path the whole margin grid is run by run_grid_klt() and
    # the local loops below have nothing to run.
    jobs = [] if use_klt else [(pvt, variant, phase)
                               for pvt in grid for variant in args.variants
                               for phase in args.phases]
    rows: list[Row] = []
    failures: list[str] = []
    seeded: list[str] = []
    voided: list[str] = []
    klt_info: dict = {}
    if use_klt:
        rows, failures, seeded, voided, klt_info = run_grid_klt(
            grid, corners, args, ceffs, esrs, netlists, logdir,
            "local" if backend == "klt-local" else "batch")

    def submit(pool, todo, seed: bool):
        return {
            pool.submit(
                run_point, pvt, pdk, phase=phase, variant=variant,
                netlist=netlists[variant], ceffs=ceffs, esrs=esrs,
                ac_dec=args.ac_dec, workdir=workdir, logdir=logdir,
                dc_seed=(dc_seed_lines(pvt, "free") if seed else ""),
            ): (pvt, variant, phase)
            for pvt, variant, phase in todo
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = submit(pool, jobs, seed=False)
        retries = []
        done_n = 0
        for done in concurrent.futures.as_completed(futures):
            pvt, variant, phase = futures[done]
            _, pt_rows, err = done.result()
            done_n += 1
            if err:
                if "did not land on the intended DC branch" in err:
                    retries.append((pvt, variant, phase))
                    print(f"  [{done_n}/{len(jobs)}] {pvt.corner_id:<18} "
                          f"{variant:<7} {phase:<7} DC branch miss, retrying "
                          f"with the intended-branch seed")
                    continue
                failures.append(f"{pvt.corner_id}/{variant}/{phase}: {err}")
                print(f"  [{done_n}/{len(jobs)}] {pvt.corner_id:<18} "
                      f"{variant:<7} {phase:<7} SIM ERROR {err}")
                continue
            rows.extend(pt_rows)
            measured = [r for r in pt_rows if r.pm_deg is not None]
            w = worst_of(measured) if measured else pt_rows[0]
            print(f"  [{done_n}/{len(jobs)}] {pvt.corner_id:<18} "
                  f"{variant:<7} {phase:<7} worst PM {pm_str(w):>7} deg "
                  f"GM {gm_str(w):>7} dB"
                  + ("" if measured else "  (no crossover at any point)"))

    if retries:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = submit(pool, retries, seed=True)
            for done in concurrent.futures.as_completed(futures):
                pvt, variant, phase = futures[done]
                _, pt_rows, err = done.result()
                if err:
                    if "did not land on the intended DC branch" in err:
                        # Still refuses the intended branch even with the
                        # seed that starts Newton on it. Per the README's
                        # landing rule, this VOIDS the deck -- it is named
                        # in the record and excluded from the row set, but
                        # is not a run-wide failure: the other (PVT, variant,
                        # phase) decks landed cleanly and their margins are
                        # not in question. A deck that never lands on the
                        # named branch even when seeded onto it is itself a
                        # measurement (that variant's injection element has no
                        # solution near VREF at that PVT point), not a
                        # testbench bug.
                        voided.append(f"{pvt.corner_id}/{variant}/{phase}: {err}")
                        print(f"  {pvt.corner_id:<18} {variant:<7} {phase:<7} "
                              f"VOIDED (no DC branch near VREF, even seeded) "
                              f"{err}")
                        continue
                    failures.append(
                        f"{pvt.corner_id}/{variant}/{phase} (with DC seed): {err}")
                    print(f"  {pvt.corner_id:<18} {variant:<7} {phase:<7} "
                          f"SIM ERROR {err}")
                    continue
                seeded.append(f"{pvt.corner_id}/{variant}/{phase}")
                rows.extend(pt_rows)

    if failures:
        print("\nFATAL: simulation failures:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 2
    if voided:
        print(f"\n{len(voided)} (PVT, variant, phase) deck(s) voided (no DC "
              f"branch near VREF, even with the intended-branch seed); named "
              f"in the record, excluded from the row set:")
        for v in voided:
            print(f"  {v}")
    if not rows:
        print("FATAL: no rows parsed", file=sys.stderr)
        return 2
    rows.sort(key=sort_key)

    # --- the DC hand-over transfer -----------------------------------------
    # Run after the margins, because it is the margins' operating point drawn
    # densely rather than a second experiment: every HOV point is the same
    # circuit, the same loop break and the same load model as the `ramp`
    # phase, and handover_consistency() below checks that the two decks land
    # on the same place where they overlap.
    curves: list[HovCurve] = []
    hov_consistency = None
    if not args.skip_handover:
        print(f"\n=== DC hand-over transfer: {len(HANDOVER_SSR_V)} pinned "
              f"V(SSR) from {HANDOVER_SSR_V[0]:g} to {HANDOVER_SSR_V[-1]:g} V, "
              f"{len(grid)} PVT x {len(args.variants)} variant ===")
        hov_jobs = [] if use_klt else [(pvt, variant) for pvt in grid
                                       for variant in args.variants]
        if use_klt:
            curves, failures = run_handover_klt(
                grid, corners, args, netlists, logdir,
                "local" if backend == "klt-local" else "batch")
            for f in failures:
                print(f"  SIM ERROR {f}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futs = {pool.submit(run_handover, pvt, pdk, variant=variant,
                                netlist=netlists[variant], workdir=workdir,
                                logdir=logdir): (pvt, variant)
                    for pvt, variant in hov_jobs}
            for done in concurrent.futures.as_completed(futs):
                pvt, variant = futs[done]
                curve, err = done.result()
                if err:
                    failures.append(f"{pvt.corner_id}/{variant}/handover: {err}")
                    print(f"  {pvt.corner_id:<18} {variant:<7} SIM ERROR {err}")
                    continue
                curves.append(curve)
        if failures:
            print("\nFATAL: hand-over transfer failures:", file=sys.stderr)
            for f in failures:
                print(f"  {f}", file=sys.stderr)
            return 2
        curves.sort(key=lambda c: (c.variant, c.corner_id))
        for variant in args.variants:
            sel = [c for c in curves if c.variant == variant]
            if not sel:
                continue
            rel = [c for c in sel if c.release_ssr_v is not None]
            sat = [c for c in sel if c.saturated_to_ssr_v is not None]
            gms = [c.gm_a_per_v for c in sel if math.isfinite(c.gm_a_per_v)]
            print(f"  {variant:<7} I_inj(0) "
                  f"{min(c.iinj_start_a for c in sel) * 1e6:.3f}.."
                  f"{max(c.iinj_start_a for c in sel) * 1e6:.3f} uA; "
                  f"gm {min(gms) * 1e6:.3f}..{max(gms) * 1e6:.3f} uA/V; "
                  f"release V(SSR) "
                  + (f"{min(c.release_ssr_v for c in rel):.3f}.."
                     f"{max(c.release_ssr_v for c in rel):.3f} V"
                     if len(rel) == len(sel) else
                     f"never, at {len(sel) - len(rel)}/{len(sel)} corners")
                  + f"; out of regulation at {len(sat)}/{len(sel)} corners")
        hov_consistency = handover_consistency(curves, rows)
        if hov_consistency[0] is not None:
            d, r, hov = hov_consistency[0]
            print(f"  cross-deck consistency: worst |dVOUT| between a HOV point "
                  f"and the margin ROW at the same V(SSR) is {d * 1e6:.3f} uV "
                  f"over {hov_consistency[1]} shared points")

    # --- cross-check -------------------------------------------------------
    anchor_rows = [r for r in rows if r.phase == "anchor" and r.variant == "device"]
    xcheck: dict = {"skipped": args.skip_crosscheck or not anchor_rows}
    if not xcheck["skipped"]:
        print("\n=== cross-check: re-running sim/loop-stability/ on this host ===")
        here_rows, err = run_loop_stability_here(
            args, workdir, logdir, args.corners, args.temps,
            backend if use_klt else "local")
        if err:
            print(f"  cross-check could not run: {err}", file=sys.stderr)
            xcheck["error"] = err
        else:
            xcheck["here"] = compare_anchor(anchor_rows, here_rows)
            xcheck["here_verdict"] = xcheck_verdict(xcheck["here"])
            ok, wpm, wgm, wf0, n = xcheck["here_verdict"]
            print(f"  same-host re-run : {n} shared points, worst |dPM| "
                  f"{wpm:.3f} deg, |dGM| {wgm:.3f} dB, |df0| {100 * wf0:.3f}% "
                  f"-> {'AGREES' if ok else 'DISAGREES'}")
        committed = read_committed_ls_matrix()
        if committed:
            xcheck["committed"] = compare_anchor(anchor_rows, committed)
            xcheck["committed_verdict"] = xcheck_verdict(xcheck["committed"])
            ok, wpm, wgm, wf0, n = xcheck["committed_verdict"]
            print(f"  committed record : {n} shared points, worst |dPM| "
                  f"{wpm:.3f} deg, |dGM| {wgm:.3f} dB, |df0| {100 * wf0:.3f}% "
                  f"-> {'AGREES' if ok else 'DISAGREES'}")

    # --- summary -----------------------------------------------------------
    print()
    by_state = group(rows, lambda r: (r.variant, r.phase, r.ssr_cmd))
    print(f"points   : {len(rows)}")
    for key in sorted(by_state, key=lambda k: (k[1], k[2], k[0])):
        bucket = by_state[key]
        measured = [r for r in bucket if r.pm_deg is not None]
        if measured:
            w = worst_of(measured)
            wres = worst_resurgence_of(bucket)
            print(f"  {key[0]:<7} {key[1]:<7} ssr={key[2]:<5} "
                  f"worst PM {pm_str(w):>7} deg  GM {gm_str(w):>7} dB  "
                  f"at {w.corner_id}/{w.cfg_id}  "
                  f"(resurgence worst {res_str(wres)} dB)")
        else:
            print(f"  {key[0]:<7} {key[1]:<7} ssr={key[2]:<5} "
                  f"no 0 dB crossing anywhere ({len(bucket)} points): the main "
                  f"loop has no gain at this state")

    # --- attribution at the worst device-variant point ---------------------
    attribution = None
    measured_device = [r for r in rows
                       if r.variant == "device" and r.pm_deg is not None]
    if measured_device and not args.explore:
        worst = worst_of(measured_device)
        attribution = run_attribution(worst, grid, pdk, netlists, args,
                                      workdir, logdir, rows)

    if args.no_write:
        print("\n(--no-write: no record, snapshot or corner logs committed)")
        return 0

    # --- evidence ----------------------------------------------------------
    snap_dir = EXPDIR / "netlist-snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    for variant, path in netlists.items():
        shutil.copyfile(path, snap_dir / f"{record_id}-{variant}.spice")
    csv_path = records_dir / f"{record_id}-matrix.csv"
    write_matrix_csv(csv_path, rows)
    hov_csv_path = None
    if curves:
        hov_csv_path = records_dir / f"{record_id}-handover.csv"
        write_handover_csv(hov_csv_path, curves)

    md = render_record(record_id=record_id, rows=rows, grid=grid, ceffs=ceffs,
                       esrs=esrs, pdk=pdk, prov=prov, args=args,
                       xcheck=xcheck, attribution=attribution, seeded=seeded,
                       voided=voided, curves=curves,
                       hov_consistency=hov_consistency, klt_info=klt_info)
    record_path = write_markdown_record(record_id, md, records_dir)

    print()
    print(f"record           : {record_path}")
    print(f"matrix csv       : {csv_path}")
    if hov_csv_path:
        print(f"hand-over csv    : {hov_csv_path}")
    print(f"netlist snapshots: {snap_dir}/{record_id}-*.spice")
    print(f"raw logs         : {logdir}/")
    return 0


def run_attribution(worst: Row, grid, pdk, netlists, args, workdir: Path,
                    logdir: Path, rows: list[Row]) -> dict:
    """Element-removal sensitivity at the worst device-variant point.

    Uses the same corner, ramp state and output network for the ``device``
    and ``binj`` variants and each AC-only coupling removal in ``ATTRIBUTIONS``.
    Every one of those removals is DC-inert by construction (an inductor is a
    short at DC, a capacitor is an open), which is checked here rather than
    asserted: each case's landed VOUT/FB/injection current is reported next to
    its margin, so a case that moved the bias point is visible and its margin
    delta is not attributed to anything.
    """
    pvt = next(p for p in grid if p.corner_id == worst.corner_id)
    device_text = netlists["device"].read_text()
    cases: list[tuple[str, str, str]] = [
        ("as-committed", "`device` variant", device_text)
    ]
    for tag, desc, fn in ATTRIBUTIONS:
        try:
            cases.append((tag, desc, fn(device_text)))
        except nv.TransformError as exc:
            print(f"  attribution: skipping {tag}: {exc}", file=sys.stderr)
    if "binj" in netlists:
        cases.append(("binj", "`binj` variant", netlists["binj"].read_text()))

    ssr_values = None if PHASES[worst.phase]["ssr"] is None else [worst.ssr_cmd]
    out: dict = {"worst": worst, "cases": [], "fits": []}
    curves: dict[str, list] = {}
    print(f"\n=== attribution at {worst.corner_id} / {worst.state_id} / "
          f"{worst.cfg_id} ===")
    for tag, desc, text in cases:
        nl = workdir / f"attr_{tag}.spice"
        nl.write_text(text)
        _, prows, err = run_point(
            pvt, pdk, phase=worst.phase, variant=tag, netlist=nl,
            ceffs=[worst.ceff_f], esrs=[worst.esr_ohm], ac_dec=args.ac_dec,
            workdir=workdir, logdir=logdir, ssr_values=ssr_values,
            stem=f"{worst.corner_id}_attr_{tag}",
        )
        if err or not prows:
            print(f"  {tag:<14} FAILED: {err}", file=sys.stderr)
            out["cases"].append({"tag": tag, "desc": desc, "error": err})
            continue
        r = prows[0]
        curve = run_curve(pvt, pdk, r, nl, args.ac_dec, logdir, workdir,
                          f"attr-{tag}-curve")
        curves[tag] = parse_curve(curve)
        out["cases"].append({
            "tag": tag, "desc": desc, "row": r,
            "curve": str(curve.resolve().relative_to(REPO_ROOT)),
        })
        print(f"  {tag:<14} PM {pm_str(r):>7} deg  GM {gm_str(r):>7} dB  "
              f"f0 {_hz(r.f0_hz):>10} Hz  VOUT {r.vout_v:.5f} V  "
              f"I_inj {r.iinj_a * 1e6:+.4f} uA")

    base = curves.get("as-committed")
    if base:
        for tag in list(curves):
            if tag == "as-committed":
                continue
            ext = curve_extremes(base, curves[tag])
            above_floor = ext is not None and (abs(ext[0]) >= ATTR_FLOOR_DB
                                               or abs(ext[2]) >= ATTR_FLOOR_DEG)
            fit = fit_pole_zero(base, curves[tag]) if above_floor else None
            deltas = delta_table(base, curves[tag])
            out["fits"].append({"tag": tag, "fit": fit, "deltas": deltas,
                                "extremes": ext, "above_floor": above_floor})
            if ext is None:
                print(f"  T(as-committed)/T({tag}): curves not comparable")
                continue
            print(f"  T(as-committed)/T({tag}): max d|T| {ext[0]:+.4f} dB at "
                  f"{ext[1]:.4g} Hz, max dphase {ext[2]:+.4f} deg at "
                  f"{ext[3]:.4g} Hz"
                  + ("" if above_floor else "  [at the numerical floor: no "
                     "pole/zero to fit]"))
            if fit:
                k_db, fz, fp, resid = fit
                print(f"      fitted zero {fz:.4g} Hz, pole {fp:.4g} Hz, "
                      f"DC offset {k_db:+.3f} dB, residual {resid:.3f}")

    # --- the FB capacitance budget ----------------------------------------
    # Run at TWO points: the worst device-variant point (which is at a corner
    # where the main loop is already thin with either injection element), and
    # the design's own nominal operating point at the hold-release ramp state
    # (which is not). One alone would be arguable; together they bracket.
    base_row = next((c["row"] for c in out["cases"]
                     if c["tag"] == "as-committed" and "row" in c), None)
    out["fb_cap"] = []
    if base_row is not None:
        out["fb_cap"].append(run_fb_cap_ladder(
            "worst measured device-variant point in this record",
            worst, base_row, device_text, grid, pdk, args, workdir, logdir))
    nominal = next(
        (r for r in rows
         if r.variant == "device" and r.phase == "ramp"
         and r.corner_id == "tt_27c_3.30v"
         and r.ssr_cmd == f"{HANDOVER_ACQUISITION_SSR_V:g}"
         and abs(r.ceff_f - 1e-6) < 1e-15 and abs(r.esr_ohm - 0.1) < 1e-12
         and r.pm_deg is not None),
        None)
    if nominal is not None and key_of(nominal) != key_of(worst):
        out["fb_cap"].append(run_fb_cap_ladder(
            "the nominal corner at the hold-release ramp state",
            nominal, nominal, device_text, grid, pdk, args, workdir, logdir))
    return out


def run_fb_cap_ladder(label: str, point: Row, base_row: Row, device_text: str,
                      grid, pdk, args, workdir: Path, logdir: Path) -> dict:
    """Add known capacitance from FB to VSS at ``point`` and watch the margins.

    The inverse of the element-removal sensitivity above. Removing this
    element's coupling says that THIS element is cheap; adding capacitance
    until the margins move says what any future injection element has to stay
    under. Every rung is a capacitor, so every rung is DC-inert and the landed
    VOUT column is there for a reader to check that.
    """
    pvt = next(p for p in grid if p.corner_id == point.corner_id)
    ssr_values = None if PHASES[point.phase]["ssr"] is None else [point.ssr_cmd]
    out = {"label": label, "point": point, "base": base_row, "rungs": []}
    print(f"\n=== feedback-node capacitance ladder at {point.corner_id} / "
          f"{point.state_id} / {point.cfg_id} ({label}) ===")
    print(f"  {'C(FB->VSS)':<14} {'PM (deg)':>9} {'dPM':>8} {'GM (dB)':>9} "
          f"{'dGM':>8} {'f0 (Hz)':>11}  landed VOUT")
    print(f"  {'(none)':<14} {pm_str(base_row):>9} {'-':>8} "
          f"{gm_str(base_row):>9} {'-':>8} {_hz(base_row.f0_hz):>11}  "
          f"{base_row.vout_v:.5f} V")
    for cf in FB_CAP_LADDER_F:
        tag = f"fbcap-{cf:g}"
        try:
            text = nv.ac_load(device_text, "FB", "VSS", cf, "fbcap")
        except nv.TransformError as exc:
            print(f"  fb-cap {cf:g} F skipped: {exc}", file=sys.stderr)
            continue
        nl = workdir / f"attr_{tag}.spice"
        nl.write_text(text)
        _, prows, err = run_point(
            pvt, pdk, phase=point.phase, variant=tag, netlist=nl,
            ceffs=[point.ceff_f], esrs=[point.esr_ohm], ac_dec=args.ac_dec,
            workdir=workdir, logdir=logdir, ssr_values=ssr_values,
            stem=f"{point.corner_id}_{point.phase}_{point.ssr_cmd}_attr_{tag}",
        )
        if err or not prows:
            print(f"  fb-cap {cf:g} F FAILED: {err}", file=sys.stderr)
            out["rungs"].append({"c_f": cf, "error": err})
            continue
        r = prows[0]
        out["rungs"].append({"c_f": cf, "row": r})
        dpm = ("-" if r.pm_deg is None or base_row.pm_deg is None
               else f"{r.pm_deg - base_row.pm_deg:+.2f}")
        dgm = ("-" if math.isinf(r.gm_db) or math.isinf(base_row.gm_db)
               else f"{r.gm_db - base_row.gm_db:+.2f}")
        print(f"  {cf:<14g} {pm_str(r):>9} {dpm:>8} {gm_str(r):>9} {dgm:>8} "
              f"{_hz(r.f0_hz):>11}  {r.vout_v:.5f} V")
    out["budget"] = fb_cap_budget(out)
    b = out["budget"]
    print("  -> budget: "
          + (f"{b['ok_f'] * 1e12:g} pF still within "
             f"{FB_CAP_PM_TOL_DEG:g} deg / {FB_CAP_GM_TOL_DB:g} dB of the "
             f"baseline" if b["ok_f"] is not None else "no rung is within "
             "tolerance of the baseline")
          + (f"; first rung outside it is {b['bad_f'] * 1e12:g} pF "
             f"({b['bad_why']})" if b["bad_f"] is not None
             else "; no rung on this ladder leaves the tolerance"))
    return out


def fb_cap_budget(ladder: dict) -> dict:
    """Largest rung whose margins are still within tolerance of the baseline.

    Both margins, because they fail in different places: capacitance at FB
    first RAISES the phase margin (the loop rolls off earlier) and only later
    collapses it, while the gain margin goes first and by tens of dB.
    """
    base = ladder["base"]
    ok_f = None
    bad_f = None
    bad_why = ""
    for rung in ladder["rungs"]:
        r = rung.get("row")
        if r is None:
            continue
        why = []
        if r.pm_deg is None or base.pm_deg is None:
            why.append("no 0 dB crossing")
        elif r.pm_deg < base.pm_deg - FB_CAP_PM_TOL_DEG:
            why.append(f"PM {r.pm_deg - base.pm_deg:+.2f} deg vs baseline")
        if not math.isinf(r.gm_db) and not math.isinf(base.gm_db) \
                and r.gm_db < base.gm_db - FB_CAP_GM_TOL_DB:
            why.append(f"GM {r.gm_db - base.gm_db:+.2f} dB vs baseline")
        if why:
            if bad_f is None:
                bad_f, bad_why = rung["c_f"], "; ".join(why)
        elif bad_f is None:
            ok_f = rung["c_f"]
    return {"ok_f": ok_f, "bad_f": bad_f, "bad_why": bad_why}


if __name__ == "__main__":
    sys.exit(main())
