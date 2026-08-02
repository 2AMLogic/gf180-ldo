#!/usr/bin/env python3
"""Prove the loop-gain extraction before trusting anything it reports.

Runs ``tb_tian_selftest.spice`` -- a loop built entirely from ideal elements,
whose loop gain is known in closed form -- and checks three things:

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
   ``meas ac ... max tdb from=f0*10^(1/dec)`` idiom that reports how far
   ``|T|`` climbs back above 0 dB after its first 0 dB crossing is checked
   twice: it must stay **negative** on the monotonic loop above (no false
   positive -- that loop never returns above unity), and it must recover the
   analytically known peak of a **second** reference loop, built with a
   lightly damped resonance above its first crossing precisely so it does.

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
# ... and the second, deliberately resurging reference loop.
A2 = 100.0
LL2 = 0.8
CL2 = 0.2e-12
# The AC resolution the resurging loop is swept at, which is also the step
# the resurgence scan starts above the crossing. It is the real deck's dec 50
# (the monotonic loop above keeps its historical dec 20).
DEC2 = 50

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

    start = f0 * 10 ** (1.0 / DEC2)
    fine = [10 ** (k / 5000.0) for k in range(0, 5000 * 9 + 1)]
    peak = max(_db2(f) for f in fine if f >= start)
    grid = [10 ** (k / float(DEC2)) for k in range(0, DEC2 * 9 + 1)]
    peak_on_grid = max(_db2(f) for f in grid if f >= start)
    return f0, peak, peak_on_grid


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
    return rows, margins, resurging


def main() -> int:
    if shutil.which("ngspice") is None:
        print("FATAL: ngspice not on PATH", file=sys.stderr)
        return 3
    proc = subprocess.run(["ngspice", "-b", str(DECK)], capture_output=True, text=True)
    text = proc.stdout + proc.stderr
    if "SELFTEST COMPLETE" not in text:
        print("FATAL: selftest deck did not complete:\n" + text[-2000:], file=sys.stderr)
        return 3

    rows, margins, resurging = parse(text)
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

    print(f"\nSELFTEST {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
