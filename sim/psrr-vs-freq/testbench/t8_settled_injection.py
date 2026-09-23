#!/usr/bin/env python3
"""T8 (and T1-at-settled): the soft-start injection element's settled residual
into FB and its supply slope, on the ratified PSRR row's own operating point.

    ./sim/psrr-vs-freq/testbench/t8_settled_injection.py              # 1 mA grid
    ./sim/psrr-vs-freq/testbench/t8_settled_injection.py --bench psrr-vs-freq-50ma
    ./sim/psrr-vs-freq/testbench/t8_settled_injection.py --corners ff \\
        --temps 125 --supply-tol 0                                    # one point

WHAT IT MEASURES

`design/softstart_injection_compensation.md` section 3 (R3) carries T8
(DR-0031 section 5, added by issue #302):

  T8  |dI_inj/dVIN| <= 10.5 nA/V at the settled operating point, at every PVT
      corner of sim/psrr-vs-freq's grid.

and T1's settled-point reading (I_inj <= 50 nA) falls out of the same run.

HOW (DR-0031 section 2.2's instrument, made a committed driver)

A 0 V ammeter (`Vt8_inj`) is inserted in series with `Mgmc_ss`'s drain lead --
the element's single point of contact with FB -- in a copy of the COMMITTED
`design/netlist/ldo_core.spice`, written next to the raw logs so the run is
auditable. An ideal 0 V source is a short at DC and in AC, so the circuit is
electrically the unmodified netlist's; the driver re-measures psrr_1k_db in the
same deck and prints it, so a reader can diff it against the sibling harness
record of the same bench. Measured for issue #302 over both 45-point grids:
agreement to <= 1.9 mdB at every corner, and to the printed digit at the
binding corners -- the residue is the extra matrix row moving the DC
continuation path's last digits, not a circuit difference.

Everything else is the named harness bench, UNMODIFIED: its stimulus fragment
(`tb_psrr.spice` / `tb_psrr_50ma.spice`), its PVT grid, its manifest options
and nodeset, and the harness's own deck composer, DC continuation ladder and
#310 pseudo-transient gate (`harness.runner.run_grid`). Only the DUT include
and the measurement block differ.

The supply slope is read from the `.ac` at 1 kHz (the ratified row's binding
frequency) with the bench's own 1 V AC on VIN, i.e. |I(Vt8_inj)| at 1 kHz IS
|dI_inj/dVIN| there. A `.dc` sweep of VIN is the WRONG instrument: SSR is a
capacitor node, so at pure DC the circuit admits a second, unstarted-ramp
root (DR-0035 section 2.2).

It does not write a harness evidence record (the harness refuses an overridden
DUT, correctly). Its per-corner CSV lands under
`sim/<bench>/corners/<record-id>-t8/` and the result is recorded by hand in
`design/softstart_injection_compensation.md` section 3.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT / "sim"))

from harness import testbench as tbmod  # noqa: E402
from harness.corners import build_grid, resolve_corners, supply_points  # noqa: E402
from harness.pdk import find_pdk  # noqa: E402
from harness.runner import (  # noqa: E402
    ngspice_binary_sha256,
    ngspice_version,
    run_grid,
)

T8_BOUND_NA_PER_V = 10.5   # DR-0031 section 5
T1_BOUND_NA = 50.0         # design/softstart_injection_compensation.md T1

AMMETER = "Vt8_inj"
PROBE_NODE = "T8INJ"
SS_BLOCK_RE = re.compile(r"(?ms)^\.subckt ldo_softstart\b.*?^\.ends[ \t]*$")
MGMC_RE = re.compile(r"(?m)^(XMgmc_ss) FB (GMSUM GMOD GMOD pfet_03v3\b)")
IPATH = f"v.xdut.xsoftstart.{AMMETER.lower()}"


def instrument(core_text: str) -> str:
    """Committed ldo_core.spice with a 0 V ammeter in Mgmc_ss's drain lead."""
    blocks = SS_BLOCK_RE.findall(core_text)
    if len(blocks) != 1:
        raise SystemExit(f"FATAL: expected one ldo_softstart subckt, found {len(blocks)}")
    block = blocks[0]
    new_block, n = MGMC_RE.subn(rf"\1 {PROBE_NODE} \2", block)
    if n != 1:
        raise SystemExit("FATAL: could not find exactly one 'XMgmc_ss FB GMSUM GMOD "
                         "GMOD pfet_03v3' card -- the netlist moved; update this driver")
    new_block = new_block.replace(
        "\n.ends", f"\n* issue #302 T8 probe: 0 V ammeter, drain lead of Mgmc_ss -> FB\n"
                   f"{AMMETER} {PROBE_NODE} FB 0\n.ends", 1)
    return core_text.replace(block, new_block, 1)


ANALYSES = (
    "op",
    "ac dec 20 10 10meg",
    "meas ac vout_1k FIND vdb(vout) AT=1k",
    f"let t8_imag = mag(i({IPATH}))",
    "meas ac t8_i1k FIND t8_imag AT=1k",
)
MEASURE = {
    "iinj_settled_na": f"op1.i({IPATH})*1e9",
    "t8_na_per_v": "t8_i1k*1e9",
    "psrr_1k_db": "-vout_1k",
    "vin_minus_vceil_v": "op1.v(vin)-op1.v(xdut.xsoftstart.vceil)",
    "ssr_settled_v": "op1.v(xdut.xsoftstart.ssr)",
    "vin_minus_ssr_v": "op1.v(vin)-op1.v(xdut.xsoftstart.ssr)",
    "dc_vout_v": "op1.v(vout)",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", default="psrr-vs-freq",
                    choices=["psrr-vs-freq", "psrr-vs-freq-50ma"])
    ap.add_argument("--corners", nargs="+", default=None)
    ap.add_argument("--temps", nargs="+", type=float, default=None)
    ap.add_argument("--supply-tol", type=float, default=None)
    ap.add_argument("-j", "--jobs", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--dut-from-rev", default="",
                    help="known-answer control: instrument design/netlist/ldo_core.spice "
                         "as committed at this git revision instead of the working tree "
                         "(e.g. the pre-#302 netlist, to reproduce DR-0031's 109.9 nA/V)")
    args = ap.parse_args()

    check = subprocess.run([sys.executable, str(REPO_ROOT / "design" / "netlist.py"),
                            "--check"], capture_output=True, text=True)
    if check.returncode != 0:
        print("FATAL: design/netlist/*.spice is stale vs the schematics:\n"
              + check.stdout + check.stderr, file=sys.stderr)
        return 3

    expdir = REPO_ROOT / "sim" / args.bench
    tb = tbmod.load(expdir / "testbench")
    short = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True).stdout.strip()
    record_id = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-{short}-t8"
    if args.dut_from_rev:
        core = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show",
             f"{args.dut_from_rev}:design/netlist/ldo_core.spice"],
            capture_output=True, text=True, check=True).stdout
        record_id += f"-control-{args.dut_from_rev[:12]}"
    else:
        core = tb.dut_netlist.read_text()
    logdir = expdir / "corners" / record_id
    logdir.mkdir(parents=True, exist_ok=True)
    workdir = REPO_ROOT / "sim" / ".work" / args.bench / record_id
    measure = dict(MEASURE)
    if not re.search(r"(?m)^\S+ .*\bVCEIL\b", core):
        # a pre-DR-0035 netlist (the known-answer control) has no VCEIL node
        del measure["vin_minus_vceil_v"]
    probe = logdir / "ldo_core_t8probe.spice"
    probe.write_text(instrument(core))
    tb = dataclasses.replace(tb, dut_netlist=probe,
                             dut_netlist_rel=str(probe.relative_to(REPO_ROOT)),
                             analyses=ANALYSES, measure=measure, checks={})

    pdk = find_pdk()
    corners = resolve_corners(args.corners or list(tb.corners))
    temps = args.temps if args.temps is not None else list(tb.temperatures_c)
    tol = args.supply_tol if args.supply_tol is not None else tb.supply_tolerance
    grid = build_grid(corners, temps, supply_points(tb.nominal_supply_v, tol))

    print(f"bench         : {args.bench} (stimulus {tb.netlist.name}, unmodified)")
    print(f"pdk           : {pdk.variant} @ {pdk.version}")
    print(f"ngspice       : {ngspice_version()}")
    print(f"ngspice sha256: {ngspice_binary_sha256()}")
    print(f"record id     : {record_id}")
    print(f"grid          : {len(grid)} PVT points")
    print()

    results = run_grid(tb, pdk, grid, workdir, jobs=args.jobs,
                       timeout_s=args.timeout, log_dir=logdir)
    bad = [r for r in results if r.status != "ok"]
    rows = []
    for r in results:
        m = r.measurements
        rows.append((r.point.corner_id, r.status, m))
    rows.sort(key=lambda x: x[0])

    cpath = logdir / "t8.csv"
    cols = list(measure)
    with cpath.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["corner_id", "status", *cols, "T8", "T1_settled"])
        for cid, status, m in rows:
            t8 = m.get("t8_na_per_v")
            i1 = m.get("iinj_settled_na")
            w.writerow([cid, status, *[f"{m[c]:.6g}" if c in m else "" for c in cols],
                        "" if t8 is None else ("PASS" if abs(t8) <= T8_BOUND_NA_PER_V else "FAIL"),
                        "" if i1 is None else ("PASS" if abs(i1) <= T1_BOUND_NA else "FAIL")])
            if status == "ok":
                print(f"  {cid:<18} T8 {m['t8_na_per_v']:9.4f} nA/V  "
                      f"I_inj {m['iinj_settled_na']:9.4f} nA  "
                      f"PSRR@1k {m['psrr_1k_db']:8.4f} dB  "
                      + (f"VIN-VCEIL {m['vin_minus_vceil_v']:.6f} V  "
                         if "vin_minus_vceil_v" in m else "")
                      + f"SSR {m['ssr_settled_v']:.4f} V  VOUT {m['dc_vout_v']:.6f} V")
            else:
                print(f"  {cid:<18} {status.upper()}")

    ok = [m for _, s, m in rows if s == "ok"]
    if ok:
        def span(key):
            vals = [m[key] for m in ok]
            return min(vals), max(vals)
        t8w = max(ok, key=lambda m: abs(m["t8_na_per_v"]))
        i1w = max(ok, key=lambda m: abs(m["iinj_settled_na"]))
        worst_cid = lambda target: next(c for c, s, m in rows if m is target)  # noqa: E731
        n8 = sum(1 for m in ok if abs(m["t8_na_per_v"]) <= T8_BOUND_NA_PER_V)
        n1 = sum(1 for m in ok if abs(m["iinj_settled_na"]) <= T1_BOUND_NA)
        print(f"\n=== {args.bench}: {len(ok)}/{len(rows)} points ok ===")
        print(f"  T8 |dI_inj/dVIN| <= {T8_BOUND_NA_PER_V} nA/V : {n8}/{len(ok)} pass, worst "
              f"{abs(t8w['t8_na_per_v']):.4f} nA/V @ {worst_cid(t8w)}")
        print(f"  T1 |I_inj| settled <= {T1_BOUND_NA} nA    : {n1}/{len(ok)} pass, worst "
              f"{abs(i1w['iinj_settled_na']):.4f} nA @ {worst_cid(i1w)}")
        for key in [k for k in ("psrr_1k_db", "vin_minus_vceil_v", "ssr_settled_v",
                                "vin_minus_ssr_v", "dc_vout_v") if k in measure]:
            lo, hi = span(key)
            print(f"  {key:<20} {lo:.6g} .. {hi:.6g}")
    print(f"\nper-corner CSV: {cpath}")
    print(f"raw logs      : {logdir}/")
    return 2 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
