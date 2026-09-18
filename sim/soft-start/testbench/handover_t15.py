#!/usr/bin/env python3
"""T1-T5: the injection element's DC hand-over transfer, over the 63-corner grid.

    ./sim/soft-start/testbench/handover_t15.py            # all 63 PVT corners
    ./sim/soft-start/testbench/handover_t15.py --corners tt --temps 27 \
        --supplies 3.30                                   # one point
    ./sim/soft-start/testbench/handover_t15.py --help

WHY THIS LIVES HERE AND NOT IN sim/soft-start-loop-gain/

`design/softstart_injection_compensation.md` section 3 (R3) specifies seven
numeric targets any replacement FB-injection element must meet. Five of them --
T1 (residual injection above VREF), T2 (absolute current at the bottom of the
ramp), T3 (transconductance), T4 (release point), T5 (the loop in regulation at
every ramp state) -- are properties of the element's **DC hand-over transfer**,
and the deck that measures that transfer is
`sim/soft-start-loop-gain/testbench/tb_ss_handover.spice.in` (issue #196). The
other two, T6 (the element's own phase/gain-margin contribution) and T7 (the
capacitance it hangs on FB), are small-signal and stay that experiment's.

But T1-T5 are adjudicated against the **Startup row**, which is
`sim/soft-start/`'s row, and issue #246's acceptance criteria ask for them
alongside this bench's own 163-point transient matrix. Running the whole
11 450-point loop-gain matrix to get a 63-point DC transfer is the wrong trade,
so this driver runs the hand-over transfer *alone*, over the full PVT grid,
**against that experiment's own unmodified deck and its own unmodified metric
code** -- `render_handover_deck`, `run_handover`, `HandoverCurve` are all
imported from `sweep.py`, not re-implemented. There is exactly one definition
of "what I_inj is at this ramp state" in this repo and this driver uses it.

WHAT IT DOES **NOT** DO

It does not measure T6 or T7 and does not claim to: those need the AC matrix.
It does not re-run the margin phases, so it cannot and does not restate any
phase-margin number. A record minted from this driver must say so; see
`sim/soft-start/records/` for the one issue #246 wrote.

TARGETS, verbatim from `design/softstart_injection_compensation.md` section 3:

  T1  I_inj <= 50 nA for all V(SSR) >= VREF
  T2  I_inj(V(SSR)=0) = 6.00 uA, within +/-0.10 uA
  T3  transconductance -5.00 uA/V, within +/-5%
  T4  release point V(SSR) = 1.200 V
  T5  the loop in regulation (|V(FB) - VREF| <= 5 mV) at EVERY V(SSR) >= 0
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as _dt
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPDIR = HERE.parent
REPO_ROOT = EXPDIR.parent.parent
LG_TB = REPO_ROOT / "sim" / "soft-start-loop-gain" / "testbench"

sys.path.insert(0, str(REPO_ROOT / "sim"))
sys.path.insert(0, str(LG_TB))

import netlist_variants as nv  # noqa: E402
import sweep  # noqa: E402
from harness.pdk import find_pdk  # noqa: E402
from harness.runner import ngspice_binary_sha256, ngspice_version  # noqa: E402

# --- the targets, as machine-checkable predicates ---------------------------
T1_RESIDUAL_A = 50e-9          # I_inj <= 50 nA for all V(SSR) >= VREF
T2_TARGET_A = 6.00e-6          # I_inj(0)
T2_TOL_A = 0.10e-6
T3_TARGET_A_PER_V = -5.00e-6   # transconductance
T3_TOL_FRAC = 0.05
T4_RELEASE_V = 1.200           # release point
# T5 uses sweep.HANDOVER_REG_TOL_V (5 mV) and sweep's own in_regulation flag,
# so "in regulation" means here exactly what it means there.


def verdicts(curve) -> dict[str, tuple[bool, str]]:
    """T1-T5 pass/fail for one corner's transfer, with the measured value."""
    above = [p for p in curve.points if p.ssr_v >= sweep.HANDOVER_INTENT_RELEASE_V]
    t1_worst = max((p.iinj_a for p in above), default=float("nan"))
    t1 = (t1_worst <= T1_RESIDUAL_A, f"{t1_worst * 1e9:.2f} nA")

    i0 = curve.iinj_start_a
    t2 = (abs(i0 - T2_TARGET_A) <= T2_TOL_A, f"{i0 * 1e6:.4f} uA")

    gm = curve.gm_a_per_v
    t3_ok = (math.isfinite(gm)
             and abs(gm - T3_TARGET_A_PER_V)
             <= abs(T3_TARGET_A_PER_V) * T3_TOL_FRAC)
    t3 = (t3_ok, f"{gm * 1e6:.3f} uA/V")

    rel = curve.release_ssr_v
    # "+0/-0 to within the ramp's own step": the hand-over grid's step is
    # 25 mV, so a release AT 1.200 V is the only reading that passes; anything
    # higher is a release the ramp had to overshoot to reach.
    t4 = (rel is not None and rel <= T4_RELEASE_V,
          "never" if rel is None else f"{rel:.3f} V")

    sat = curve.saturated_to_ssr_v
    t5 = (sat is None, "in regulation everywhere" if sat is None
          else f"open up to V(SSR)={sat:.3f} V")

    return {"T1": t1, "T2": t2, "T3": t3, "T4": t4, "T5": t5}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corners", nargs="+", default=list(sweep.PROCESS_CORNERS))
    ap.add_argument("--temps", nargs="+", type=float, default=list(sweep.TEMPS_C))
    ap.add_argument("--supply-tol", type=float, default=sweep.SUPPLY_TOL)
    ap.add_argument("--variant", default="device",
                    choices=list(nv.DUT_VARIANTS),
                    help="`device` is design/netlist/ldo_softstart.spice as "
                         "committed; `binj` is the frozen pre-#195 ideal "
                         "source, useful only as a known-answer control")
    ap.add_argument("-j", "--jobs", type=int, default=8)
    ap.add_argument("--record-id", default="")
    args = ap.parse_args()

    pdk = find_pdk()
    check = subprocess.run(
        [sys.executable, str(REPO_ROOT / "design" / "netlist.py"), "--check"],
        capture_output=True, text=True)
    if check.returncode != 0:
        print("FATAL: design/netlist/*.spice is stale vs the schematics:",
              file=sys.stderr)
        print(check.stdout + check.stderr, file=sys.stderr)
        return 3

    short = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    record_id = args.record_id or (
        _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        + f"-{short}")

    logdir = EXPDIR / "corners" / f"{record_id}-handover"
    logdir.mkdir(parents=True, exist_ok=True)
    workdir = REPO_ROOT / "sim" / ".work" / EXPDIR.name / f"{record_id}-handover"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / ".spiceinit").write_text(sweep.SPICEINIT)

    netlist = logdir / f"ldo_core_{args.variant}.spice"
    netlist.write_text(nv.build_variant(REPO_ROOT, args.variant))

    corners = sweep.resolve_corners(args.corners)
    supplies = sweep.supply_points(sweep.NOMINAL_SUPPLY_V, args.supply_tol)
    grid = sweep.build_grid(corners, args.temps, supplies)

    print(f"pdk           : {pdk.variant} @ {pdk.version}")
    print(f"ngspice       : {ngspice_version()}")
    print(f"ngspice sha256: {ngspice_binary_sha256()}")
    print(f"record id     : {record_id}-handover")
    print(f"variant       : {args.variant}")
    print(f"grid          : {len(grid)} PVT x {len(sweep.HANDOVER_SSR_V)} "
          f"pinned V(SSR) from {sweep.HANDOVER_SSR_V[0]:g} to "
          f"{sweep.HANDOVER_SSR_V[-1]:g} V")
    print()

    curves, errs = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(sweep.run_handover, pvt, pdk, variant=args.variant,
                            netlist=netlist, workdir=workdir, logdir=logdir): pvt
                for pvt in grid}
        for n, done in enumerate(concurrent.futures.as_completed(futs), 1):
            pvt = futs[done]
            curve, err = done.result()
            if err:
                errs.append(f"{pvt.corner_id}: {err}")
                print(f"  [{n}/{len(grid)}] {pvt.corner_id:<18} SIM ERROR {err}")
                continue
            curves.append(curve)
            v = verdicts(curve)
            print(f"  [{n}/{len(grid)}] {pvt.corner_id:<18} "
                  + " ".join(f"{k}:{'PASS' if ok else 'FAIL'}"
                             for k, (ok, _) in v.items())
                  + f"   I_inj(0) {curve.iinj_start_a * 1e6:.4f} uA"
                  f"  gm {curve.gm_a_per_v * 1e6:.3f} uA/V"
                  f"  Vout_err(top) {curve.vout_top_err_v * 1e3:+.3f} mV")

    if errs:
        print("\nFATAL: hand-over transfer failures:", file=sys.stderr)
        for e in errs:
            print(f"  {e}", file=sys.stderr)
        return 2
    curves.sort(key=lambda c: c.corner_id)

    # --- per-corner verdict rollup -----------------------------------------
    vpath = logdir / "targets.csv"
    with vpath.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["corner_id", "T1", "T1_measured", "T2", "T2_measured",
                    "T3", "T3_measured", "T4", "T4_measured", "T5",
                    "T5_measured", "iinj_at_vref_na", "vout_top_err_mv"])
        for c in curves:
            v = verdicts(c)
            w.writerow([c.corner_id,
                        *[x for k in ("T1", "T2", "T3", "T4", "T5")
                          for x in ("PASS" if v[k][0] else "FAIL", v[k][1])],
                        f"{c.iinj_at_vref_a * 1e9:.3f}",
                        f"{c.vout_top_err_v * 1e3:.4f}"])

    # --- the full transfer, point by point, so the rollup is auditable -----
    tpath = logdir / "transfer.csv"
    with tpath.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["corner_id", "corner", "temp_c", "vin_v", "ssr_v", "fb_v",
                    "vout_v", "pg_v", "erramp_v", "isup_a", "iinj_a",
                    "in_regulation"])
        for c in curves:
            for p in c.points:
                w.writerow([c.corner_id, c.corner, c.temp_c, c.vin_v,
                            f"{p.ssr_v:g}", f"{p.fb_v:.8g}", f"{p.vout_v:.8g}",
                            f"{p.pg_v:.8g}", f"{p.erramp_v:.8g}",
                            f"{p.isup_a:.8g}", f"{p.iinj_a:.8g}",
                            "yes" if p.in_regulation else "no"])

    print("\n=== T1-T5 over the whole grid ===")
    tally = {k: sum(1 for c in curves if verdicts(c)[k][0])
             for k in ("T1", "T2", "T3", "T4", "T5")}
    for k, n in tally.items():
        print(f"  {k}: {n}/{len(curves)} corners pass")
    gms = [c.gm_a_per_v for c in curves if math.isfinite(c.gm_a_per_v)]
    rel = [c.release_ssr_v for c in curves if c.release_ssr_v is not None]
    print(f"  I_inj(0)          {min(c.iinj_start_a for c in curves) * 1e6:.4f}"
          f" .. {max(c.iinj_start_a for c in curves) * 1e6:.4f} uA")
    print(f"  transconductance  {min(gms) * 1e6:.3f} .. {max(gms) * 1e6:.3f}"
          f" uA/V")
    print(f"  I_inj at VREF     "
          f"{min(c.iinj_at_vref_a for c in curves) * 1e9:.2f} .. "
          f"{max(c.iinj_at_vref_a for c in curves) * 1e9:.2f} nA")
    print(f"  release V(SSR)    "
          + (f"{min(rel):.3f} .. {max(rel):.3f} V" if len(rel) == len(curves)
             else f"never, at {len(curves) - len(rel)}/{len(curves)} corners"))
    print(f"  settled Vout err  "
          f"{min(c.vout_top_err_v for c in curves) * 1e3:+.3f} .. "
          f"{max(c.vout_top_err_v for c in curves) * 1e3:+.3f} mV")

    print(f"\ntargets rollup: {vpath}")
    print(f"full transfer : {tpath}")
    print(f"raw logs      : {logdir}/")
    print(f"record-id     : {record_id}-handover")
    print(f"(write {EXPDIR}/records/<id>.md by hand -- see sim/README.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
