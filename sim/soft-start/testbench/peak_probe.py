#!/usr/bin/env python3
"""Single-corner waveform probe of the soft-start startup peak (issue #351).

    python3 sim/soft-start/testbench/peak_probe.py --out <dir> [--cout 1u --esr 0.1 --rload 36]
        [--corner tt --temp 27 --vin 3.30] [--extra-ic]

Runs ONE ngspice transient per DUT (the frozen new/baseline netlists of record
20261007-ss-320-tt27-probe), a single corner, locally, and dumps waveforms
around the EN edge to CSV. It exists to locate the time and cause of the
peak Icap / dV/dt that the klt-measured probe reports only as a scalar. It is
a diagnostic, not a PVT matrix: grids go through klt_run.py.
"""
import argparse, csv, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness.corners import CORNERS  # noqa: E402
from harness import klt_batch as kb  # noqa: E402
from harness.pdk import find_pdk  # noqa: E402

SNAP = HERE.parent / "corners/20261007-ss-320-tt27-probe/main"
PROBES = {
    "vout": "v(vout)", "pg": "v(pg)", "en": "v(en)", "bg": "v(xdut.bg)", "fb": "v(xdut.fb)",
    "ssr": "v(xdut.xsoftstart.ssr)", "hg": "v(xdut.xsoftstart.hg)", "enb": "v(xdut.xsoftstart.enb)",
    "icap": "i(vcmeas)", "ivin": "i(vamm)", "iload": "i(vlmeas)",
    "ierr": "i(vamm)", "n1": "v(xdut.xerramp.n1)", "nbias": "v(xdut.xerramp.nbias)",
}


def deck(dut: Path, pdk, c: str, temp: float, vin: float, cout, esr, rload, tstop, tmax, lin=True, extra=()):
    lib = pdk.path / "libs.tech/ngspice/sm141064.ngspice"
    secs = "\n".join(f".lib {lib} {s}" for s in CORNERS[c].sections)
    probes = " ".join(PROBES[k] for k in ("vout", "pg", "en", "bg", "fb", "ssr", "hg", "enb", "icap", "ivin", "iload"))
    probes += "".join(" " + e.split("=", 1)[1] for e in extra)
    return f"""* peak_probe deck (issue #351)
.include {pdk.path}/libs.tech/ngspice/design.ngspice
{secs}
.temp {temp}
.include {dut}
.options wnflag=1 reltol=1e-3 vntol=1e-5 abstol=1e-11 chgtol=1e-14
Vin VIN 0 DC {vin}
Venctl ENCTL 0 DC 0 PWL(0 0 100u 0 101u 1 8m 1 8.001m 0)
Ben EN 0 V = 'v(vin) * v(enctl)'
Vref VREF 0 DC 1.2
Vamm VIN VIN1 0
Xdut VIN1 VOUT EN 0 EOUT PG VREF ldo_core
Vloop PG EOUT DC 0
Resr VOUT n_esr {esr}
Cout n_esr n_cap {cout}
Vcmeas n_cap 0 DC 0
Rload VOUT LN {rload}
Vlmeas LN 0 DC 0
.control
set noaskquit
set wr_vecnames
option numdgt=7
tran {tmax} {tstop}
@LIN@
wrdata OUTFILE time {probes}
.endc
.end
""".replace("@LIN@", "linearize" if lin else "* native (adaptive) time points, no resampling")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--corner", default="tt"); ap.add_argument("--temp", type=float, default=27)
    ap.add_argument("--vin", type=float, default=3.30)
    ap.add_argument("--cout", default="1u"); ap.add_argument("--esr", default="0.1")
    ap.add_argument("--rload", default="36")
    ap.add_argument("--tstop", default="2m"); ap.add_argument("--tmax", default="0.1u")
    ap.add_argument("--dut-new", default=str(SNAP / "new/dut.spice"))
    ap.add_argument("--dut-base", default=str(SNAP / "baseline/dut.spice"))
    ap.add_argument("--tag", default="")
    ap.add_argument("--extra", action="append", default=[], help="name=expr, appended after the 11 core vectors")
    ap.add_argument("--native", action="store_true", help="dump the solver's own time points (no linearize)")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    pdk = find_pdk()
    for name, dut in (("new", a.dut_new), ("baseline", a.dut_base)):
        csvp = out / f"{name}{a.tag}.dat"
        d = deck(Path(dut).resolve(), pdk, a.corner, a.temp, a.vin, a.cout, a.esr, a.rload, a.tstop, a.tmax, lin=not a.native, extra=a.extra)
        d = d.replace("OUTFILE", str(csvp))
        with tempfile.TemporaryDirectory() as td:
            deckp = Path(td) / "deck.sp"; deckp.write_text(d)
            r = subprocess.run(["ngspice", "-b", str(deckp)], capture_output=True, text=True, timeout=3600)
            (out / f"{name}{a.tag}.log").write_text(r.stdout[-6000:] + r.stderr[-2000:])
        print(name, "rc", r.returncode, csvp.exists())


if __name__ == "__main__":
    main()
