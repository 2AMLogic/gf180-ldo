#!/usr/bin/env python3
"""Reduce peak_probe.py .dat dumps to the committed evidence tables (issue #351).

    python3 peak_analyze.py --dat-dir /tmp/p351 --out sim/soft-start/corners/<id> \\
        --conv 100n,20n,5n,2n,1n --win-tag _x --extra-names co,clg,i2,vth,isns

Writes ``convergence.csv`` (peak Icap / dV/dt / time vs solver max step, both
DUTs, from files ``<dut>_c<tmax>.dat``), ``native_1u.csv`` (the solver's own
steps, as klt_run.py takes them, from ``<dut>_nat1u.dat``) and, from
``<dut><win-tag>.dat``, ``event_<dut>.csv``: 100 ns .. 20 ns-spaced waveforms
across the event window.
"""
import argparse, csv
from pathlib import Path

CORE = ["vout", "pg", "en", "bg", "fb", "ssr", "hg", "enb", "icap", "ivin", "iload"]


def load(p, names):
    """Parse a ``wrdata <file> time <v1> <v2> ...`` dump (one header line, then
    ``t t t v1 t v2 ...`` rows) into ``(t, {name: values})``.

    Fails loud (``ValueError``) on a dump with no data rows, on a ragged row (a
    truncated last line would otherwise be read as if complete), or on rows
    too short to hold every requested vector -- never a partial table.
    """
    rows = [list(map(float, l.split())) for l in p.read_text().splitlines()[1:] if l.strip()]
    if not rows:
        raise ValueError(f"{p.name}: no data rows")
    width = len(rows[0])
    need = 2 + 2 * len(names)
    if width < need:
        raise ValueError(f"{p.name}: rows have {width} columns, {need} needed for {len(names)} vectors")
    ragged = [k + 1 for k, r in enumerate(rows) if len(r) != width]
    if ragged:
        raise ValueError(f"{p.name}: {len(ragged)} row(s) do not have {width} columns "
                         f"(first at data row {ragged[0]}; truncated dump?)")
    return [r[0] for r in rows], {n: [r[3 + 2 * i] for r in rows] for i, n in enumerate(names)}


def peak(t, v):
    ic = v["icap"]; i = max(range(len(ic)), key=ic.__getitem__)
    dv = [(v["vout"][k + 1] - v["vout"][k]) / (t[k + 1] - t[k]) * 1e-3 for k in range(len(t) - 1) if t[k + 1] > t[k]]
    return ic[i] * 1e3, t[i] * 1e6, max(dv)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dat-dir", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--conv", default="100n,20n,5n,2n,1n")
    ap.add_argument("--win-tag", default="_x"); ap.add_argument("--extra-names", default="co,clg,i2,vth,isns")
    ap.add_argument("--win", default="151.5,152.0")
    a = ap.parse_args(argv)
    d, out = Path(a.dat_dir), Path(a.out); out.mkdir(parents=True, exist_ok=True)
    with open(out / "convergence.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["tmax", "dut", "icap_peak_ma", "t_peak_us", "dvout_max_vpms"])
        for tag, label in [("_nat1u", "native-1u(9ms)")] + [(f"_c{x}", x) for x in a.conv.split(",")]:
            for dut in ("new", "baseline"):
                p = d / f"{dut}{tag}.dat"
                if p.exists():
                    t, v = load(p, CORE); w.writerow([label, dut] + ["%.4g" % x for x in peak(t, v)])
    names = CORE + a.extra_names.split(",")
    lo, hi = (float(x) * 1e-6 for x in a.win.split(","))
    for dut in ("new", "baseline"):
        p = d / f"{dut}{a.win_tag}.dat"
        if not p.exists(): continue
        t, v = load(p, names)
        with open(out / f"event_{dut}.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(["t_us"] + names)
            for k in range(len(t)):
                if lo <= t[k] <= hi and round(t[k] * 1e9) % 20 == 0:
                    w.writerow(["%.3f" % (t[k] * 1e6)] + ["%.6g" % v[n][k] for n in names])


if __name__ == "__main__":
    main()
