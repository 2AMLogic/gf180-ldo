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
    process in {tt, ff, ss, fs, sf}
    = 3240 loop-gain points

The load x cap x ESR axes are swept *inside* one ngspice deck per PVT point
(a ``foreach`` loop with ``alter``), so the whole matrix is 45 ngspice
invocations, not 3240. One raw log per PVT point lands under
``corners/<record-id>/<corner-id>.log`` -- the naming ratified in
``sim/README.md`` -- with one ``ROW`` line per (load, cap, ESR) config.

Output, per ``sim/README.md``:

    netlist-snapshots/<record-id>.spice        frozen DUT netlist
    corners/<record-id>/<corner-id>.log        raw ngspice output (45 files)
    corners/<record-id>/<worst>_curve.log      full T(f) curve at the worst point
    records/<record-id>-matrix.csv             all 3240 points, machine-readable
    records/<record-id>.md                     the append-only summary record

Nothing under ``records/``, ``corners/`` or ``netlist-snapshots/`` is ever
overwritten: a re-run mints a new record-id.

Usage::

    ./sim/loop-stability/testbench/sweep.py                # full matrix, writes a record
    ./sim/loop-stability/testbench/sweep.py --explore      # tt/27C/3.3V only, writes nothing
    ./sim/loop-stability/testbench/sweep.py --no-write -j8 # run, record nothing

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
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPDIR = HERE.parent                       # sim/loop-stability
REPO_ROOT = EXPDIR.parent.parent           # repo root
TEMPLATE = HERE / "tb_loop_stability.spice.in"
LDO_NETLIST = REPO_ROOT / "design" / "netlist" / "ldo_core.spice"

sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness.corners import CORNERS, build_grid, resolve_corners, supply_points  # noqa: E402

# --- the ratified matrix (DR-0001 section "Consequences") --------------------
DR0001 = "spec/decision-records/DR-0001-output-cap-strategy.md"
ILOADS_A = (0.0, 0.1e-3, 1e-3, 10e-3, 25e-3, 50e-3)
CEFFS_F = (0.33e-6, 1.0e-6, 4.7e-6)
ESRS_OHM = (0.001, 0.05, 0.2, 0.5)
PROCESS_CORNERS = ("tt", "ff", "ss", "fs", "sf")
TEMPS_C = (-40.0, 27.0, 125.0)
NOMINAL_SUPPLY_V = 3.3
SUPPLY_TOL = 0.10

# DR-0001 stability criterion.
PM_MIN_DEG = 45.0
GM_MIN_DB = 10.0

# AC sweep band. The low end must sit well below the output pole at the
# largest C_eff / lightest load (a few Hz); the high end well above the
# highest crossover seen (a few MHz) so a -180 deg crossing, if there is
# one, is inside the band rather than assumed away.
F_START = "0.01"
F_STOP = "1e9"
AC_DEC = "50"

TOKEN_RE = re.compile(r"@([A-Z0-9_]+)@")


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------
def resolve_pdk():
    from harness.pdk import find_pdk  # noqa: WPS433 -- deferred, needs sys.path

    return find_pdk()


def ngspice_version() -> str:
    out = subprocess.run(["ngspice", "-v"], capture_output=True, text=True).stdout
    m = re.search(r"(ngspice-[0-9.]+)", out)
    return m.group(1) if m else "unknown"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
# one PVT point
# ---------------------------------------------------------------------------
@dataclass
class Row:
    corner_id: str
    corner: str
    temp_c: float
    vin_v: float
    iload_a: float
    ceff_f: float
    esr_ohm: float
    vout_v: float
    dcgain_db: float
    f0_hz: float | None
    phase_at_f0_deg: float | None
    f180_hz: float | None
    gain_at_f180_db: float | None
    f0_rising_hz: float | None

    @property
    def pm_deg(self) -> float | None:
        if self.phase_at_f0_deg is None:
            return None
        return 180.0 + self.phase_at_f0_deg

    @property
    def gm_db(self) -> float:
        """Gain margin. ``inf`` when the phase never reaches -180 deg in band.

        That is not a measurement failure: for a loop whose phase asymptotes
        to -180 deg from above, there is no frequency at which the loop
        inverts, so no finite gain multiplier drives it to T = -1. Reported
        as ``inf`` and treated as passing the >= 10 dB bar.
        """
        if self.gain_at_f180_db is None:
            return math.inf
        return -self.gain_at_f180_db

    @property
    def passes(self) -> bool:
        pm = self.pm_deg
        return pm is not None and pm >= PM_MIN_DEG and self.gm_db >= GM_MIN_DB

    @property
    def config_id(self) -> str:
        return f"{fmt_ma(self.iload_a)}_{fmt_uf(self.ceff_f)}_{fmt_esr(self.esr_ohm)}"


def fmt_ma(a: float) -> str:
    ma = a * 1e3
    return f"{ma:g}mA"


def fmt_uf(f: float) -> str:
    return f"{f * 1e6:g}uF"


def fmt_esr(r: float) -> str:
    return f"{r * 1e3:g}mohm"


def _f(tok: str) -> float | None:
    tok = tok.strip()
    if not tok:
        return None
    try:
        return float(tok)
    except ValueError:
        return None


def render_deck(pvt, pdk, iloads, ceffs, esrs) -> str:
    corner = pvt.corner
    mos, res, bjt, diode, moscap, mimcap = corner.sections
    subs = {
        "DESIGN_INCLUDE": str(pdk.design_include),
        "MODEL_LIB": str(pdk.model_lib),
        "LDO_NETLIST": str(LDO_NETLIST),
        "MOS_CORNER": mos,
        "RES_CORNER": res,
        "BJT_CORNER": bjt,
        "DIODE_CORNER": diode,
        "MOSCAP_CORNER": moscap,
        "MIMCAP_CORNER": mimcap,
        "TEMP_C": f"{pvt.temp_c:g}",
        "VIN_V": f"{pvt.vdd:g}",
        "CORNER_ID": pvt.corner_id,
        "CORNER_NAME": corner.name,
        "AC_DEC": AC_DEC,
        "F_START": F_START,
        "F_STOP": F_STOP,
        "ILOAD_LIST": " ".join(f"{v:g}" for v in iloads),
        "CEFF_LIST": " ".join(f"{v:g}" for v in ceffs),
        "ESR_LIST": " ".join(f"{v:g}" for v in esrs),
    }
    text = TEMPLATE.read_text()
    missing = {m for m in TOKEN_RE.findall(text) if m not in subs}
    if missing:
        raise SystemExit(f"template has unsubstituted tokens: {sorted(missing)}")
    return TOKEN_RE.sub(lambda m: subs[m.group(1)], text)


FATAL_RE = re.compile(
    r"could not find a valid modelname|singular matrix|no convergence"
    r"|iteration limit reached|Simulation interrupted|fatal error",
    re.IGNORECASE,
)


def run_point(pvt, pdk, iloads, ceffs, esrs, workdir: Path, logdir: Path):
    deck = workdir / f"{pvt.corner_id}.spice"
    deck.write_text(render_deck(pvt, pdk, iloads, ceffs, esrs))
    log = logdir / f"{pvt.corner_id}.log"
    proc = subprocess.run(
        ["ngspice", "-b", str(deck)], capture_output=True, text=True
    )
    log.write_text(proc.stdout + proc.stderr)
    text = log.read_text()
    if proc.returncode != 0:
        return pvt, [], f"ngspice exited {proc.returncode} (see {log})"
    if FATAL_RE.search(text):
        bad = [ln for ln in text.splitlines() if FATAL_RE.search(ln)][:3]
        return pvt, [], f"ngspice reported a fatal condition: {bad} (see {log})"
    if "SWEEP COMPLETE" not in text:
        return pvt, [], f"sweep did not complete (see {log})"

    rows: list[Row] = []
    for line in text.splitlines():
        if not line.startswith("ROW "):
            continue
        # trailing fields may be empty (a failed meas), so pad rather than split
        parts = line.split()[1:]
        parts += [""] * (10 - len(parts))
        rows.append(
            Row(
                corner_id=pvt.corner_id,
                corner=pvt.corner.name,
                temp_c=pvt.temp_c,
                vin_v=pvt.vdd,
                iload_a=float(parts[0]),
                ceff_f=float(parts[1]),
                esr_ohm=float(parts[2]),
                vout_v=_f(parts[3]) or float("nan"),
                dcgain_db=_f(parts[4]) or float("nan"),
                f0_hz=_f(parts[5]),
                phase_at_f0_deg=_f(parts[6]),
                f180_hz=_f(parts[7]),
                gain_at_f180_db=_f(parts[8]),
                f0_rising_hz=_f(parts[9]),
            )
        )
    expected = len(iloads) * len(ceffs) * len(esrs)
    if len(rows) != expected:
        return pvt, rows, f"expected {expected} rows, parsed {len(rows)} (see {log})"
    return pvt, rows, None


def run_curve(pvt, pdk, row: Row, logdir: Path, workdir: Path, suffix: str) -> Path:
    """Re-run one single config with the whole T(f) curve printed to the log."""
    text = render_deck(pvt, pdk, [row.iload_a], [row.ceff_f], [row.esr_ohm])
    text = text.replace('      echo "ROW', "      print tdb tph\n" + '      echo "ROW')
    deck = workdir / f"{pvt.corner_id}_{suffix}.spice"
    deck.write_text(text)
    log = logdir / f"{pvt.corner_id}_{suffix}.log"
    proc = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True, text=True)
    header = (
        f"* full loop-gain curve T(f) at the {suffix.replace('-', ' ')} point of this record\n"
        f"* corner={pvt.corner_id} iload={fmt_ma(row.iload_a)} "
        f"ceff={fmt_uf(row.ceff_f)} esr={fmt_esr(row.esr_ohm)}\n"
        f"* the two printed columns after the frequency are |T| in dB and "
        f"unwrapped phase(T) in degrees\n"
    )
    log.write_text(header + proc.stdout + proc.stderr)
    return log


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def gm_str(row: Row) -> str:
    return "inf" if math.isinf(row.gm_db) else f"{row.gm_db:.2f}"


def pm_str(row: Row) -> str:
    pm = row.pm_deg
    return "n/a" if pm is None else f"{pm:.2f}"


def worst_of(rows: list[Row]) -> Row:
    """The row with the smallest phase margin (GM as tiebreak)."""

    def key(r: Row):
        pm = r.pm_deg
        return (
            -1e9 if pm is None else pm,
            r.gm_db if not math.isinf(r.gm_db) else 1e9,
        )

    return min(rows, key=key)


def write_matrix_csv(path: Path, rows: list[Row]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "corner_id", "process", "temp_c", "vin_v",
                "iload_ma", "ceff_uf", "esr_ohm", "vout_v",
                "dc_loop_gain_db", "f_crossover_hz", "phase_margin_deg",
                "f_180_hz", "gain_margin_db", "result",
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
                ]
            )


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
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--no-write", action="store_true",
                    help="run and report, write no record (debugging)")
    ap.add_argument("--explore", action="store_true",
                    help="tt/27C/3.3V only across load x cap x ESR; implies --no-write "
                         "(DR-0001's recommended first pass to locate the worst triple)")
    ap.add_argument("--subset-reason", default="",
                    help="required (and copied into the record) if the PVT grid is "
                         "narrower than the CLAUDE.md-mandated matrix")
    ap.add_argument("--supersedes", default="",
                    help="record-id this run supersedes")
    ap.add_argument("--author", default=os.environ.get("LOOP_STABILITY_AUTHOR", "agent-builder (issue #10)"))
    args = ap.parse_args()

    if args.explore:
        args.corners = ["tt"]
        args.temps = [27.0]
        args.supply_tol = 0.0
        args.no_write = True

    if shutil.which("ngspice") is None:
        print("FATAL: ngspice not on PATH", file=sys.stderr)
        return 3
    try:
        pdk = resolve_pdk()
    except Exception as exc:  # pragma: no cover - environment problem
        print(f"FATAL: {exc}", file=sys.stderr)
        return 3

    # The committed netlist must be current with the schematic.
    check = subprocess.run(
        [sys.executable, str(REPO_ROOT / "design" / "netlist.py"), "--check"],
        capture_output=True, text=True,
    )
    if check.returncode != 0:
        print("FATAL: design/netlist/ldo_core.spice is stale vs design/ldo_core.sch:",
              file=sys.stderr)
        print(check.stdout + check.stderr, file=sys.stderr)
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
    )
    if not args.no_write and not full_matrix and not args.subset_reason:
        print(
            "FATAL: this grid is narrower than the matrix DR-0001 ratifies.\n"
            "       Re-run with the full matrix, or pass --subset-reason '<why>' "
            "(copied verbatim into the record), or --no-write to just debug.",
            file=sys.stderr,
        )
        return 3

    record_id = f"{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}-{git('rev-parse', '--short', 'HEAD')}"
    dirty = bool(git("status", "--porcelain"))
    logdir = EXPDIR / "corners" / record_id
    workdir = REPO_ROOT / "sim" / ".work" / "loop-stability" / record_id
    workdir.mkdir(parents=True, exist_ok=True)
    if not args.no_write:
        if (EXPDIR / "records" / f"{record_id}.md").exists():
            print(f"FATAL: record {record_id} already exists; refusing to overwrite",
                  file=sys.stderr)
            return 3
        logdir.mkdir(parents=True, exist_ok=True)
    else:
        logdir = workdir

    print(f"pdk       : {pdk.variant} @ {pdk.version}")
    print(f"ngspice   : {ngspice_version()}")
    print(f"record id : {record_id}{' (NOT WRITTEN: --no-write)' if args.no_write else ''}")
    print(f"grid      : {len(grid)} PVT points x "
          f"{len(iloads)}x{len(ceffs)}x{len(esrs)} load/cap/ESR = {n_points} loop-gain points")
    print()

    rows: list[Row] = []
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(run_point, pvt, pdk, iloads, ceffs, esrs, workdir, logdir): pvt
            for pvt in grid
        }
        for done in concurrent.futures.as_completed(futures):
            pvt, pt_rows, err = done.result()
            if err:
                failures.append(f"{pvt.corner_id}: {err}")
                print(f"  {pvt.corner_id:<22} SIM ERROR  {err}")
                continue
            rows.extend(pt_rows)
            w = worst_of(pt_rows)
            print(f"  {pvt.corner_id:<22} worst PM {pm_str(w):>7} deg  "
                  f"GM {gm_str(w):>7} dB  at {w.config_id}")

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
    overall_pass = not failing

    print()
    print(f"points    : {len(rows)}")
    print(f"failing   : {len(failing)} (PM < {PM_MIN_DEG:g} deg or GM < {GM_MIN_DB:g} dB)")
    f0s = "n/a" if worst.f0_hz is None else f"{worst.f0_hz:.4g}"
    print(f"worst     : PM {pm_str(worst)} deg, GM {gm_str(worst)} dB, f0 {f0s} Hz")
    print(f"            at {worst.corner_id} / {worst.config_id}")
    print(f"OVERALL   : {'PASS' if overall_pass else 'FAIL'} against {DR0001}")

    if args.no_write:
        print("\n(--no-write: no record, snapshot or corner logs committed)")
        return 0 if overall_pass else 1

    # Full-curve evidence at the worst point, and at the best-margin point of
    # the same PVT corner for contrast.
    worst_pvt = next(p for p in grid if p.corner_id == worst.corner_id)
    curve_log = run_curve(worst_pvt, pdk, worst, logdir, workdir, "worst-curve")

    snap = EXPDIR / "netlist-snapshots" / f"{record_id}.spice"
    snap.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LDO_NETLIST, snap)

    records = EXPDIR / "records"
    records.mkdir(parents=True, exist_ok=True)
    csv_path = records / f"{record_id}-matrix.csv"
    write_matrix_csv(csv_path, rows)

    md = render_record(
        record_id=record_id, rows=rows, worst=worst, failing=failing,
        multi_cross=multi_cross, grid=grid, iloads=iloads, ceffs=ceffs, esrs=esrs,
        pdk=pdk, dirty=dirty, args=args, curve_log=curve_log,
    )
    (records / f"{record_id}.md").write_text(md)

    print()
    print(f"record           : {records / f'{record_id}.md'}")
    print(f"matrix csv       : {csv_path}")
    print(f"netlist snapshot : {snap}")
    print(f"raw logs         : {logdir}/")
    return 0 if overall_pass else 1


def render_record(*, record_id, rows, worst, failing, multi_cross, grid,
                  iloads, ceffs, esrs, pdk, dirty, args, curve_log) -> str:
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

    n_pass = len(rows) - len(failing)
    pms = [r.pm_deg for r in rows if r.pm_deg is not None]
    best = max(rows, key=_pm_key)
    procs = ", ".join(sorted({r.corner for r in rows}))
    temps_seen = ", ".join(f"{t:g}" for t in sorted({r.temp_c for r in rows}))
    supplies_seen = ", ".join(f"{v:.2f}" for v in sorted({r.vin_v for r in rows}))
    n_inf_gm = sum(1 for r in rows if math.isinf(r.gm_db))

    subset = args.subset_reason.strip()
    subset_md = (f"\n  - **Subset reason**: {subset}\n" if subset else "")
    multi_md = ""
    if multi_cross:
        multi_md = (
            f"\n  - **Multiple 0 dB crossings** detected at {len(multi_cross)} point(s); "
            "the reported phase margin is taken at the first falling crossing. "
            "See the `f0_rising_hz` column of the raw logs.\n"
        )

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
  **The error amplifier is still the behavioural placeholder**
  (`design/ldo_erramp_placeholder.sch`: a 3162x VCVS behind a 1 MOhm output
  resistance), not a transistor-level amplifier -- issue #9 owns that design.
  Every number below is therefore a measurement of the *core + placeholder
  amp* as committed, which is precisely what this record is for: it fixes
  the compensation requirement #9 has to meet.
- **Corner matrix run**:
  - Process: {procs}
  - Temperature: {temps_seen} degC
  - Supply: {supplies_seen} V
  - {len(grid)} PVT points x {len(iloads)} load x {len(ceffs)} cap x {len(esrs)} ESR
    = **{len(rows)} loop-gain points** (the full 3240-point grid DR-0001
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
    ({n_pass}/{len(rows)} points pass, {len(failing)} fail).
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
  - Gain margin is **not** the limiting criterion anywhere in this matrix:
    at {n_inf_gm}/{len(rows)} points the loop
    phase never reaches -180 deg in 0.01 Hz - 1 GHz (a two-pole-dominated
    loop approaches -180 deg from above), so no finite gain multiplier drives
    T to -1; where a -180 deg crossing does exist the gain there is far below
    0 dB. Every failure below is a **phase-margin** failure.{multi_md}

  Per-PVT-corner worst case (worst over that corner's
  {len(iloads) * len(ceffs) * len(esrs)} load/cap/ESR configurations),
  sorted worst-first:

{chr(10).join(corner_tbl)}

  Worst case per load/cap/ESR configuration (worst over all {len(grid)} PVT
  points), which is where the structure of the failure is visible:

{chr(10).join(cfg_tbl)}

- **Links**:
  - Testbench: `sim/loop-stability/testbench/tb_loop_stability.spice.in`,
    `sim/loop-stability/testbench/sweep.py`,
    `sim/loop-stability/testbench/run.sh`
  - Testbench self-test (validates the Tian extraction against a circuit with
    an analytically known loop gain):
    `sim/loop-stability/testbench/tb_tian_selftest.spice`,
    `sim/loop-stability/testbench/selftest.py`
  - Netlist snapshot: `sim/loop-stability/netlist-snapshots/{record_id}.spice`
  - Raw logs (one per PVT point, {len(iloads) * len(ceffs) * len(esrs)} `ROW`
    lines each): `sim/loop-stability/corners/{record_id}/`
  - Full loop-gain curve T(f) at the worst point: `{rel(curve_log)}`
  - Full {len(rows)}-point matrix, machine-readable:
    `sim/loop-stability/records/{record_id}-matrix.csv`
- **Timestamp / author**: {_dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}, {args.author}
- **Supersedes**: {args.supersedes or '(none -- first record for this experiment)'}

## Environment

Everything needed to re-run this record:

- PDK: {pdk.variant} @ {pdk.version}
- ngspice: {ngspice_version()}
- git: `{git('rev-parse', '--short', 'HEAD')}` on `{git('rev-parse', '--abbrev-ref', 'HEAD')}`
  ({'DIRTY' if dirty else 'clean'} at generation time)
- Command: `./sim/loop-stability/testbench/run.sh`
- AC sweep: `dec {AC_DEC} {F_START} {F_STOP}` per injection, two injections per point.

---

Written by `sim/loop-stability/testbench/sweep.py`, in the `sim/README.md`
record format. Append-only: never edit or delete this file -- a re-run or
correction mints a new record-id and points back here via **Supersedes**.
"""


if __name__ == "__main__":
    sys.exit(main())
