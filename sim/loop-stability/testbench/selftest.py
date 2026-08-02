#!/usr/bin/env python3
"""Prove the loop-gain extraction before trusting anything it reports.

Runs ``tb_tian_selftest.spice`` -- a loop built entirely from ideal elements,
whose loop gain is known in closed form -- and checks six things:

1. **The dual-injection arithmetic is right.** The extracted
   ``T = (Tv*Ti - 1)/(Tv + Ti + 2)`` must match the analytic
   ``T(s) = A/(1+s/wp) * (1/sCl)/(Rs + Rl + 1/sCl)`` in both magnitude and
   phase, across the whole swept band.
2. **Dual injection was actually necessary.** The reference loop is
   deliberately built with Z_source >> Z_load at the break -- the same
   condition the real LDO has, where the error amp's 1 MOhm output
   resistance drives a few pF of pass-gate capacitance. Plain series-voltage
   injection must be shown to be *badly* wrong there, otherwise the extra
   machinery in the real testbench is unjustified.
3. **The margin extraction is right.** The ``meas ac ... when tdb=0`` idiom
   the real deck uses to pull out crossover frequency and phase margin must
   agree with the analytic crossover of the same reference loop.
4. **The gain-resurgence extraction is right** (issue #59, DR-0008). The
   ``meas ac ... max tdb from=f0*1.05`` idiom that reports how far ``|T|``
   climbs back above 0 dB after its first 0 dB crossing is checked twice: it
   must stay **negative** on the monotonic loop above (no false positive --
   that loop never returns above unity), and it must recover the
   analytically known peak of a **second** reference loop, built with a
   lightly damped resonance above its first crossing precisely so it does.
5. **The sweep RESOLUTION policy resolves a high-Q feature** (issue #58).
   Check 4 places its resonance *on* a grid point, so it tests the
   extraction's arithmetic and says nothing about whether the grid samples a
   sharp feature at all. A **third** reference loop closes that gap: Q = 80
   (four times check 4's Q = 20) placed at the worst-case sampling **offset**
   for ``dec 400`` -- the resolution ``sweep.py`` now runs -- so the policy is
   tested at its own blind spot rather than at a frequency that happens to be
   on-grid for it. Its gain is tuned so the true continuous peak clears 0 dB
   by only a few dB, i.e. the smallest resurgence still unambiguously over
   the DR-0008 bar. Three assertions come out of it: the OLD default
   (``dec 50``) reports this loop as a **false PASS** despite a real,
   analytically known resurgence (issue #58's general concern -- a coarse
   grid can misreport *any* sharp feature -- made concrete); ``dec 400``
   recovers the true peak inside the analytic worst-case bound
   ``sweep.py``'s ``AC_DEC`` comment derives; and ``cph()`` unwraps the
   resonance onto the correct 360 deg branch at BOTH resolutions, which is
   the other half of issue #58's question and turns out to be a non-issue
   for a minimum-phase pole pair.
6. **``resurgence_db`` is comparable across ``AC_DEC``** (issue #69). The
   scan's start offset used to be one AC-grid step above the crossing
   (``f0*10^(1/AC_DEC)``), which tied the metric's *value* to the sweep
   resolution even though the quantity it reports -- ``sup|T|`` over
   ``(f0, F_STOP]`` -- does not depend on resolution at all: raising the real
   deck's ``AC_DEC`` from 50 to 400 alone moved ``resurgence_db`` at all 4536
   matrix points by +0.061...+2.362 dB, with phase margin and crossover
   essentially unmoved. Now that the offset is a FIXED 5% of f0, the
   monotonic reference loop above is re-measured at a second ``AC_DEC``
   (400, the real deck's current default) and its ``resurgence_db`` must
   agree with the dec-20 value from check 4 to a small, stated,
   grid-quantization-only tolerance -- the property the old idiom lacked.

No PDK and no design netlist are involved, so this test is a pure statement
about the *method*. Run it before (or after) ``sweep.py``; it writes nothing.

    ./sim/loop-stability/testbench/selftest.py

Exit codes: 0 all checks pass, 1 a check failed, 3 environment problem.
"""

from __future__ import annotations

import cmath
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK = HERE / "tb_tian_selftest.spice"

# Must match the .param / control-block values in tb_tian_selftest.spice.
A = 1000.0
RP, CP = 1e3, 159.1549430918954e-9
WP = 1.0 / (RP * CP)
RS = 1e5
RL = 10.0
CL = 1e-9
# The fixed fraction above f0 the resurgence scan starts at (issue #69),
# replacing the old `f0*10^(1/AC_DEC)` grid-tied offset. Must match the
# literal `let fres... = f0*1.05` idiom in tb_loop_stability.spice.in and
# tb_tian_selftest.spice. Chosen close to the historical dec-50 grid step
# (10^(1/50) ~ 4.71%, the resolution every record through
# 20260802-171044-db620a6 was taken at) and comfortably above the current
# dec-400 grid step (10^(1/400) ~ 0.577%) -- see tb_loop_stability.spice.in's
# "gain resurgence" comment for the full derivation.
RES_START_FRAC = 1.05
# ... and the second, deliberately resurging reference loop.
A2 = 100.0
LL2 = 0.8
CL2 = 0.2e-12
# The AC resolution the resurging loop is swept at. Deliberately left at the
# HISTORICAL dec 50 even though the real deck now runs dec 400 (issue #58):
# this loop's resonance is placed on a dec-50 grid point so that the sampled
# and continuous peaks agree, which makes it a check of the extraction's
# arithmetic. Resolution is loop 3's job, below. (The monotonic loop above
# keeps its own historical dec 20, plus a second measurement at dec 400 for
# the AC_DEC-invariance check, issue #69.)
DEC2 = 50
# ... and the third, high-Q grid-blind-spot reference loop (issue #58).
A3 = 8.0
LL3 = 3.1167613229529993
CL3 = 4.868965725279348e-14
# f_res = 10^(2244.5/400) Hz -- the geometric midpoint of the *dec-400* grid
# points 10^(2244/400) and 10^(2245/400) Hz, counted from 1 Hz. That is the
# WORST-CASE sampling offset for the new default resolution (and 87.5% of
# worst case for the old dec 50), so this loop tests the policy being adopted
# at its own blind spot rather than at a frequency that happens to be
# on-grid for it.
FRES3 = 10 ** (2244.5 / 400.0)
# The old (pre-issue-#58) and new AC_DEC. Must match sweep.py's AC_DEC and
# the literal `ac dec` calls in tb_tian_selftest.spice's loop-3 section.
DEC3_OLD = 50
DEC3_NEW = 400
# Loop 3 is one real pole plus one (minimum-phase) resonant pole pair, so its
# unwrapped phase asymptotes to -270 deg. cph() mis-unwrapping the resonance
# would land 360 deg away from that.
PH3_ASYMPTOTE_DEG = -270.0
PH3_PROBE_HZ = 1e8
MAX_PH3_ERR_DEG = 5.0

# Tolerances. The extraction is exact arithmetic on exact elements, so these
# are numerical-noise budgets, not engineering tolerances.
MAX_ERR_DB = 1e-3
MAX_ERR_DEG = 1e-3
# Naive voltage injection must be wrong by at least this much somewhere in
# band, or the reference loop is not exercising the failure mode it is
# supposed to exercise.
MIN_NAIVE_ERR_DB = 20.0
# meas-based extraction vs the analytic crossover.
MAX_F0_REL_ERR = 5e-3
MAX_PM_ERR_DEG = 0.5
# meas-based resurgence vs the analytic peak of the resurging reference loop.
# This budget is dominated by the AC grid, not by the extraction: a Q = 20
# resonance sampled at dec 50 (4.7 % steps) can be missed by up to ~1 dB if
# its peak falls between grid points, so the reference resonance is placed ON
# a dec-50 grid point and the residual quantization is ~0.02 dB. The budget
# is set an order of magnitude above that, and still far below the +14 dB
# feature it has to resolve.
MAX_RESURGENCE_ERR_DB = 0.25
# The old dec-50 default must UNDER-report this loop's resurgence by at
# least this much (i.e. read a visibly less-positive, or outright negative,
# number) for the reference loop to be exercising the blind spot it exists
# to demonstrate.
MIN_GRIDBLIND_MISS_DB = 3.0
# The new dec-400 default's recovered peak vs the analytic continuous peak.
# Budget derived the same way as MAX_RESURGENCE_ERR_DB above: at Q=80 the
# worst-case (peak exactly between two grid points) miss at dec 400 is
# bounded by ~0.84 dB (20*log10(sqrt((2*eps*Q)^2+1)), eps = sqrt(10^(1/400))-1);
# the budget below is set comfortably above that bound.
MAX_GRIDBLIND_ERR_DB = 1.5
# resurgence_db, SAME netlist, dec 20 vs dec 400 (issue #69's invariance
# check). Loop 1's gain falls off steeply right after its crossing (its pole
# sits close to f0), so even with the scan's start FIXED at a constant
# fraction of f0, which grid point each resolution happens to land on just
# above that threshold still matters some: analytically, this loop's
# dec-20-sampled and dec-400-sampled resurgence (both measured from
# f0*RES_START_FRAC) differ by ~1.1 dB here. That is grid QUANTIZATION near a
# fixed threshold -- present at any resolution and bounded by it -- not the
# AC_DEC-proportional SYSTEMATIC bias the old `f0*10^(1/AC_DEC)` idiom had
# (which does not shrink as AC_DEC grows; it is the offset itself moving).
# The budget below is set comfortably above the analytic residual.
MAX_INVARIANCE_ERR_DB = 1.75


def analytic_t(f: float) -> complex:
    jw = 2j * math.pi * f
    zc = 1.0 / (jw * CL)
    return (A / (1 + jw / WP)) * zc / (RS + RL + zc)


def analytic_margins() -> tuple[float, float]:
    """(crossover frequency, phase margin) of the reference loop."""

    def mag_db(f: float) -> float:
        return 20 * math.log10(abs(analytic_t(f)))

    lo, hi = 1.0, 1e9
    if mag_db(lo) < 0:
        raise SystemExit("reference loop does not start above 0 dB")
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if mag_db(mid) > 0:
            lo = mid
        else:
            hi = mid
    f0 = math.sqrt(lo * hi)
    # Unwrapped phase: the reference is a strictly minimum-phase 2-pole
    # response whose phase runs from 0 to -180 deg, so the principal value
    # is already the continuous one once shifted into (-360, 0].
    ph = math.degrees(cmath.phase(analytic_t(f0)))
    if ph > 0:
        ph -= 360.0
    return f0, 180.0 + ph


def analytic_invariance() -> tuple[float, float, float]:
    """(f0, dec-20-sampled resurgence, dec-400-sampled resurgence) of the
    monotonic reference loop, using the SAME fixed scan-start offset the real
    deck now uses (issue #69). The two sampled values are expected to agree
    to a small, grid-quantization-only tolerance -- MAX_INVARIANCE_ERR_DB --
    unlike the old `f0*10^(1/AC_DEC)` idiom, whose start offset itself moved
    with AC_DEC.
    """
    f0_ref, _pm_ref = analytic_margins()

    def sampled(dec: int) -> float:
        start = f0_ref * RES_START_FRAC
        grid = [10 ** (k / float(dec)) for k in range(0, dec * 9 + 1)]
        return max(20 * math.log10(abs(analytic_t(f))) for f in grid if f >= start)

    return f0_ref, sampled(20), sampled(400)


def analytic_t2(f: float) -> complex:
    """The second reference loop: same topology, resonant load network.

    ``T2(s) = A2/(1+s/wp) * (1/sCL2)/(RS + RL + sLL2 + 1/sCL2)`` -- 40 dB at
    DC, down through 0 dB at ~108 kHz, then back up to ~+14 dB at the
    ~398 kHz resonance before falling for good.
    """
    jw = 2j * math.pi * f
    zc = 1.0 / (jw * CL2)
    return (A2 / (1 + jw / WP)) * zc / (RS + RL + jw * LL2 + zc)


def _db2(f: float) -> float:
    return 20 * math.log10(abs(analytic_t2(f)))


def analytic_resurgence() -> tuple[float, float, float]:
    """(first 0 dB crossing, continuous peak above it, dec-DEC2-sampled peak).

    The first crossing has to be bracketed by a scan rather than found by
    bisection: this loop crosses 0 dB three times, and a bisection would
    happily converge on the *last* crossing, which is exactly the misreading
    the resurgence metric exists to expose.
    """
    scan = [10 ** (k / 500.0) for k in range(0, 500 * 9 + 1)]
    lo = hi = None
    for a, b in zip(scan, scan[1:]):
        if _db2(a) > 0 >= _db2(b):
            lo, hi = a, b
            break
    if lo is None:
        raise SystemExit("resurging reference loop never crosses 0 dB falling")
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if _db2(mid) > 0:
            lo = mid
        else:
            hi = mid
    f0 = math.sqrt(lo * hi)

    # The FIXED scan-start offset (issue #69), not a function of DEC2.
    start = f0 * RES_START_FRAC
    fine = [10 ** (k / 5000.0) for k in range(0, 5000 * 9 + 1)]
    peak = max(_db2(f) for f in fine if f >= start)
    grid = [10 ** (k / float(DEC2)) for k in range(0, DEC2 * 9 + 1)]
    peak_on_grid = max(_db2(f) for f in grid if f >= start)
    return f0, peak, peak_on_grid


def analytic_t3(f: float) -> complex:
    """The third reference loop: same topology, a much higher-Q (80 vs 20)
    resonance placed at ``FRES3`` -- the worst-case ``dec 50`` sampling
    offset (issue #58) -- rather than on a grid point (issue #59's loop 2,
    above). ``A3`` is tuned so the true continuous peak clears 0 dB by only
    a few dB while both `dec 50` grid points immediately either side of
    ``FRES3`` read several dB below it.
    """
    jw = 2j * math.pi * f
    zc = 1.0 / (jw * CL3)
    return (A3 / (1 + jw / WP)) * zc / (RS + RL + jw * LL3 + zc)


def _db3(f: float) -> float:
    return 20 * math.log10(abs(analytic_t3(f)))


def analytic_gridblind() -> tuple[float, float, float, float]:
    """(first 0 dB crossing, continuous peak above it,
    dec-DEC3_OLD-sampled peak, dec-DEC3_NEW-sampled peak).

    Same bracket-then-bisect method as ``analytic_resurgence`` above (this
    loop also crosses 0 dB three times), evaluated against BOTH the old and
    the new AC_DEC to show the old default missing the resurgence and the
    new one recovering it.
    """
    scan = [10 ** (k / 500.0) for k in range(0, 500 * 9 + 1)]
    lo = hi = None
    for a, b in zip(scan, scan[1:]):
        if _db3(a) > 0 >= _db3(b):
            lo, hi = a, b
            break
    if lo is None:
        raise SystemExit("grid-blind-spot reference loop never crosses 0 dB falling")
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if _db3(mid) > 0:
            lo = mid
        else:
            hi = mid
    f0 = math.sqrt(lo * hi)

    fine = [10 ** (k / 5000.0) for k in range(0, 5000 * 9 + 1)]
    peak = max(_db3(f) for f in fine if f >= f0 * 10 ** (1.0 / 5000.0))

    # The FIXED scan-start offset (issue #69): the SAME threshold regardless
    # of which grid ("dec") is sampling it. Only the grid points that fall
    # at or above that fixed threshold change with `dec`.
    def sampled_peak(dec: int) -> float:
        start = f0 * RES_START_FRAC
        grid = [10 ** (k / float(dec)) for k in range(0, dec * 9 + 1)]
        return max(_db3(f) for f in grid if f >= start)

    return f0, peak, sampled_peak(DEC3_OLD), sampled_peak(DEC3_NEW)


def parse(text: str):
    """(freq, err_db, err_deg, naive_err_db) rows, plus the measured margins."""
    numeric = []
    for ln in text.splitlines():
        parts = ln.split()
        if parts and re.fullmatch(r"\d+", parts[0]):
            try:
                numeric.append([float(x) for x in parts[1:]])
            except ValueError:
                continue
    if not numeric:
        raise SystemExit("selftest: no numeric rows in ngspice output")
    # ngspice `print` emits the vectors in column groups of two, each group
    # repeating the full frequency axis: (T), (Tref), (err), (naive_err).
    n = len(numeric) // 4
    blocks = [numeric[i * n : (i + 1) * n] for i in range(4)]
    if len({len(b) for b in blocks}) != 1:
        raise SystemExit("selftest: unexpected ngspice print layout")
    rows = [
        (blocks[0][i][0], blocks[2][i][1], blocks[2][i][2], blocks[3][i][1])
        for i in range(n)
    ]
    m = re.search(
        r"MARGINS f0_hz=(\S+) phase_at_f0_deg=(\S+) resurgence_db=(\S+)", text
    )
    margins = (float(m.group(1)), float(m.group(2)), float(m.group(3))) if m else None
    r = re.search(r"RESURGING ac_dec=\S+ f0_hz=(\S+) resurgence_db=(\S+)", text)
    resurging = (float(r.group(1)), float(r.group(2))) if r else None
    c = re.search(
        r"GRIDBLIND coarse ac_dec=\S+ f0_hz=(\S+) resurgence_coarse_db=(\S+)"
        r" phase_1e8_deg=(\S+)",
        text,
    )
    gridblind_coarse = (
        (float(c.group(1)), float(c.group(2)), float(c.group(3))) if c else None
    )
    n = re.search(
        r"GRIDBLIND new ac_dec=\S+ f0_hz=(\S+) resurgence_new_db=(\S+)"
        r" phase_1e8_deg=(\S+)",
        text,
    )
    gridblind_new = (
        (float(n.group(1)), float(n.group(2)), float(n.group(3))) if n else None
    )
    i = re.search(r"INVARIANCE ac_dec=\S+ f0_hz=(\S+) resurgence_db=(\S+)", text)
    invariance = (float(i.group(1)), float(i.group(2))) if i else None
    return rows, margins, resurging, gridblind_coarse, gridblind_new, invariance


def main() -> int:
    if shutil.which("ngspice") is None:
        print("FATAL: ngspice not on PATH", file=sys.stderr)
        return 3
    proc = subprocess.run(["ngspice", "-b", str(DECK)], capture_output=True, text=True)
    text = proc.stdout + proc.stderr
    if "SELFTEST COMPLETE" not in text:
        print("FATAL: selftest deck did not complete:\n" + text[-2000:], file=sys.stderr)
        return 3

    rows, margins, resurging, gridblind_coarse, gridblind_new, invariance = parse(text)
    max_err_db = max(abs(r[1]) for r in rows)
    max_err_deg = max(abs(r[2]) for r in rows)
    max_naive = max(abs(r[3]) for r in rows)

    ok = True

    def check(label: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}: {detail}")

    print(f"reference loop: A={A:g}, fp={WP / (2 * math.pi):g} Hz, "
          f"Rs={RS:g} ohm, Rl={RL:g} ohm, Cl={CL:g} F ({len(rows)} frequency points)")
    check(
        "dual-injection magnitude matches the analytic loop gain",
        max_err_db <= MAX_ERR_DB,
        f"max |error| = {max_err_db:.3e} dB (budget {MAX_ERR_DB:g} dB)",
    )
    check(
        "dual-injection phase matches the analytic loop gain",
        max_err_deg <= MAX_ERR_DEG,
        f"max |error| = {max_err_deg:.3e} deg (budget {MAX_ERR_DEG:g} deg)",
    )
    check(
        "naive voltage injection is demonstrably wrong on this loop",
        max_naive >= MIN_NAIVE_ERR_DB,
        f"max |error| = {max_naive:.1f} dB (must exceed {MIN_NAIVE_ERR_DB:g} dB, "
        "which is why the real testbench uses dual injection)",
    )

    f0_ref, pm_ref = analytic_margins()
    if margins is None:
        check("margin extraction", False, "no MARGINS line in the ngspice output")
    else:
        f0_m, ph_m, res_m = margins
        pm_m = 180.0 + ph_m
        check(
            "meas-extracted crossover frequency",
            abs(f0_m - f0_ref) / f0_ref <= MAX_F0_REL_ERR,
            f"{f0_m:.6g} Hz vs analytic {f0_ref:.6g} Hz "
            f"({100 * abs(f0_m - f0_ref) / f0_ref:.3f}%, budget "
            f"{100 * MAX_F0_REL_ERR:g}%)",
        )
        check(
            "meas-extracted phase margin",
            abs(pm_m - pm_ref) <= MAX_PM_ERR_DEG,
            f"{pm_m:.4f} deg vs analytic {pm_ref:.4f} deg "
            f"(budget {MAX_PM_ERR_DEG:g} deg)",
        )
        check(
            "no false resurgence on a loop with a monotonic gain",
            res_m < 0.0,
            f"max |T| above the 0 dB crossing = {res_m:+.3f} dB, i.e. below "
            "the 0 dB bar (this loop rolls off monotonically, so every point "
            "above its crossing is below unity by construction)",
        )

        _f0_inv_ref, res20_ref, res400_ref = analytic_invariance()
        if invariance is None:
            check("resurgence_db AC_DEC invariance (issue #69)", False,
                  "no INVARIANCE line in the ngspice output")
        else:
            f0_400_m, res400_m = invariance
            check(
                "meas-extracted resurgence_db at dec 400 matches its own "
                "analytic dec-400-sampled value (monotonic loop)",
                abs(res400_m - res400_ref) <= MAX_RESURGENCE_ERR_DB,
                f"{res400_m:+.4f} dB vs analytic {res400_ref:+.4f} dB "
                f"({abs(res400_m - res400_ref):.4f} dB error, budget "
                f"{MAX_RESURGENCE_ERR_DB:g} dB)",
            )
            check(
                "resurgence_db is invariant (to a stated tolerance) across "
                "AC_DEC on the SAME netlist (issue #69)",
                abs(res_m - res400_m) <= MAX_INVARIANCE_ERR_DB,
                f"dec 20 = {res_m:+.4f} dB, dec 400 = {res400_m:+.4f} dB "
                f"({abs(res_m - res400_m):.4f} dB apart, budget "
                f"{MAX_INVARIANCE_ERR_DB:g} dB) -- analytically the two "
                f"grids' own nearest-sample reads differ by "
                f"{abs(res20_ref - res400_ref):.4f} dB here (GRID "
                "QUANTIZATION near the fixed threshold, present at any "
                "resolution and bounded by it), not the AC_DEC-proportional "
                "SYSTEMATIC bias the old `f0*10^(1/AC_DEC)` idiom had (which "
                "moved the real deck's resurgence_db at all 4536 matrix "
                "points, +0.061...+2.362 dB, for the SAME reason)",
            )

    f0_res_ref, peak_ref, peak_grid_ref = analytic_resurgence()
    print(f"\nresurging reference loop: A2={A2:g}, fp={WP / (2 * math.pi):g} Hz, "
          f"Ll={LL2:g} H, Cl={CL2:g} F "
          f"(f_res={1 / (2 * math.pi * math.sqrt(LL2 * CL2)):.6g} Hz, "
          f"Q={math.sqrt(LL2 / CL2) / (RS + RL):.3g}); analytic 0 dB crossing "
          f"{f0_res_ref:.6g} Hz, peak above it {peak_ref:+.4f} dB "
          f"({peak_grid_ref:+.4f} dB sampled on the dec {DEC2} grid the deck runs)")
    if resurging is None:
        check("resurgence extraction", False,
              "no RESURGING line in the ngspice output")
    else:
        f0_res_m, res2_m = resurging
        check(
            "the resurging reference loop really does resurge",
            peak_ref > 0.0 and res2_m > 0.0,
            f"analytic peak above crossover {peak_ref:+.3f} dB, measured "
            f"{res2_m:+.3f} dB -- both above the 0 dB bar, so this case "
            "exercises the fail path and not just the pass path",
        )
        check(
            "meas-extracted crossover frequency (resurging loop)",
            abs(f0_res_m - f0_res_ref) / f0_res_ref <= MAX_F0_REL_ERR,
            f"{f0_res_m:.6g} Hz vs analytic {f0_res_ref:.6g} Hz "
            f"({100 * abs(f0_res_m - f0_res_ref) / f0_res_ref:.3f}%, budget "
            f"{100 * MAX_F0_REL_ERR:g}%) -- the FIRST of this loop's three 0 dB "
            "crossings, which is the one the margin is read at",
        )
        check(
            "meas-extracted gain resurgence above the first 0 dB crossing",
            abs(res2_m - peak_ref) <= MAX_RESURGENCE_ERR_DB,
            f"{res2_m:+.4f} dB vs analytic {peak_ref:+.4f} dB "
            f"({abs(res2_m - peak_ref):.4f} dB error, budget "
            f"{MAX_RESURGENCE_ERR_DB:g} dB)",
        )

    f0_gb_ref, peak_gb_ref, peak_gb_old, peak_gb_new = analytic_gridblind()
    q3 = math.sqrt(LL3 / CL3) / (RS + RL)
    print(f"\ngrid-blind-spot reference loop (issue #58): A3={A3:g}, "
          f"fp={WP / (2 * math.pi):g} Hz, Ll={LL3:g} H, Cl={CL3:g} F "
          f"(f_res={FRES3:.6g} Hz, Q={q3:.3g}, placed at the WORST-CASE "
          f"sampling offset for dec {DEC3_NEW} -- and 87.5% of worst case for "
          f"dec {DEC3_OLD}); analytic 0 dB crossing {f0_gb_ref:.6g} Hz, "
          f"continuous peak above it {peak_gb_ref:+.4f} dB "
          f"({peak_gb_old:+.4f} dB sampled at dec {DEC3_OLD}, "
          f"{peak_gb_new:+.4f} dB sampled at dec {DEC3_NEW})")
    if gridblind_coarse is None or gridblind_new is None:
        check("grid-blind-spot extraction", False,
              "no GRIDBLIND coarse/new line in the ngspice output")
    else:
        f0_gb_coarse_m, res_gb_coarse_m, ph_gb_coarse_m = gridblind_coarse
        f0_gb_new_m, res_gb_new_m, ph_gb_new_m = gridblind_new
        check(
            "the grid-blind-spot loop really does resurge (true peak > 0 dB)",
            peak_gb_ref > 0.0,
            f"analytic continuous peak above crossover {peak_gb_ref:+.3f} dB "
            "-- a real resurgence exists for the old default to miss",
        )
        check(
            f"the OLD default (dec {DEC3_OLD}) misses it: reports a false PASS",
            res_gb_coarse_m < 0.0
            and (peak_gb_ref - res_gb_coarse_m) >= MIN_GRIDBLIND_MISS_DB,
            f"dec {DEC3_OLD} reports resurgence_db = {res_gb_coarse_m:+.4f} dB "
            f"(the DR-0008 bar is <= 0 dB, so this reads as a clean PASS) "
            f"against a true continuous peak of {peak_gb_ref:+.4f} dB -- a "
            f"{peak_gb_ref - res_gb_coarse_m:.2f} dB miss, budget "
            f">= {MIN_GRIDBLIND_MISS_DB:g} dB. This is issue #58's general "
            "concern made concrete: a coarse grid can misreport a sharp "
            "feature entirely, not only land the margin on its flank.",
        )
        check(
            "meas-extracted crossover frequency (grid-blind-spot loop)",
            abs(f0_gb_coarse_m - f0_gb_ref) / f0_gb_ref <= MAX_F0_REL_ERR,
            f"{f0_gb_coarse_m:.6g} Hz vs analytic {f0_gb_ref:.6g} Hz "
            f"({100 * abs(f0_gb_coarse_m - f0_gb_ref) / f0_gb_ref:.3f}%, "
            f"budget {100 * MAX_F0_REL_ERR:g}%)",
        )
        check(
            f"the NEW default (dec {DEC3_NEW}) recovers the true peak",
            abs(res_gb_new_m - peak_gb_ref) <= MAX_GRIDBLIND_ERR_DB,
            f"{res_gb_new_m:+.4f} dB vs analytic {peak_gb_ref:+.4f} dB "
            f"({abs(res_gb_new_m - peak_gb_ref):.4f} dB error, budget "
            f"{MAX_GRIDBLIND_ERR_DB:g} dB) -- correctly flags this loop as "
            "resurging (positive, above the DR-0008 bar) where the old "
            "default read a clean pass",
        )
        check(
            "meas-extracted crossover frequency stays consistent at the new dec",
            abs(f0_gb_new_m - f0_gb_ref) / f0_gb_ref <= MAX_F0_REL_ERR,
            f"{f0_gb_new_m:.6g} Hz vs analytic {f0_gb_ref:.6g} Hz "
            f"({100 * abs(f0_gb_new_m - f0_gb_ref) / f0_gb_ref:.3f}%, "
            f"budget {100 * MAX_F0_REL_ERR:g}%)",
        )
        # Issue #58 asks specifically whether `cph()`'s phase unwrap picks the
        # wrong 360 deg branch when a sharp feature is under-sampled. Answered
        # here rather than asserted: this loop is minimum-phase with a known
        # -270 deg asymptote, so a mis-unwrap is visible as a 360 deg offset.
        for label, dec, ph in (
            (f"OLD default (dec {DEC3_OLD})", DEC3_OLD, ph_gb_coarse_m),
            (f"NEW default (dec {DEC3_NEW})", DEC3_NEW, ph_gb_new_m),
        ):
            check(
                f"cph() unwraps the Q={math.sqrt(LL3 / CL3) / (RS + RL):.0f} "
                f"resonance onto the right branch -- {label}",
                abs(ph - PH3_ASYMPTOTE_DEG) <= MAX_PH3_ERR_DEG,
                f"unwrapped phase at {PH3_PROBE_HZ:g} Hz = {ph:+.2f} deg vs the "
                f"analytic asymptote {PH3_ASYMPTOTE_DEG:+.0f} deg "
                f"(budget {MAX_PH3_ERR_DEG:g} deg; a mis-unwrap would land "
                f"360 deg away). A minimum-phase pole PAIR has 180 deg of total "
                f"phase variation, so no sampling of it can produce a >180 deg "
                f"step -- the unwrap is safe at both resolutions, and the "
                f"resolution-sensitive quantity is the MAGNITUDE, which the "
                f"check above shows dec {DEC3_OLD} getting wrong by "
                f"{peak_gb_ref - res_gb_coarse_m:.1f} dB on this same loop.",
            )

    print(f"\nSELFTEST {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
