"""Command line front end: ``python3 sim/run_corners.py <testbench> [...]``."""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import time
from pathlib import Path

from . import HARNESS_VERSION, corners as corners_mod, report, runner, testbench as tb_mod
from .pdk import PdkNotFound, find_pdk
from .runner import NgspiceMissing

REPO_ROOT = Path(__file__).resolve().parents[2]
SIM_DIR = REPO_ROOT / "sim"
WORK_DIR = SIM_DIR / ".work"

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_SIM_ERROR = 2
EXIT_ENVIRONMENT = 3


def _has_manifest(candidate: Path) -> bool:
    if candidate.is_file() and candidate.name == tb_mod.MANIFEST_NAME:
        return True
    if (candidate / tb_mod.MANIFEST_NAME).is_file():
        return True
    return (candidate / tb_mod.TESTBENCH_DIRNAME / tb_mod.MANIFEST_NAME).is_file()


def _resolve_tb_path(argument: str) -> Path:
    """Accept an experiment slug, an experiment dir, or a testbench dir."""
    candidates = [Path(argument), SIM_DIR / argument]
    for candidate in candidates:
        if _has_manifest(candidate):
            return candidate
    raise FileNotFoundError(
        f"no experiment {argument!r}; tried: "
        + ", ".join(str(c) for c in candidates)
        + ".\nAvailable: "
        + ", ".join(p.name for p in tb_mod.discover(SIM_DIR))
    )


def _parse_operating_conditions(pairs: list[str] | None) -> dict[str, str]:
    """Turn repeated ``--operating-conditions key=value`` args into a dict."""
    result: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(
                f"--operating-conditions {pair!r}: expected key=value, e.g. "
                "load_current=50mA"
            )
        key, value = pair.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_corners.py",
        description="Run a testbench across the gf180mcu PVT corner grid.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 sim/run_corners.py smoke-bias\n"
            "  python3 sim/run_corners.py smoke-bias --corners tt --temps 27 \\\n"
            "      --subset-reason 'debugging convergence, not evidence'\n"
            "  python3 sim/run_corners.py smoke-bias --corner-set full -j 8\n"
            "  python3 sim/run_corners.py --list\n"
            "  python3 sim/run_corners.py --check-env\n"
        ),
    )
    parser.add_argument(
        "testbench",
        nargs="?",
        metavar="EXPERIMENT",
        help="experiment slug under sim/ (i.e. sim/<slug>/testbench/tb.json)",
    )
    parser.add_argument("--list", action="store_true", help="list testbenches and corners")
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="report ngspice / PDK availability and exit",
    )
    parser.add_argument(
        "--print-env",
        action="store_true",
        help="print shell exports for the resolved PDK (used by sim/env.sh)",
    )
    parser.add_argument(
        "--corners",
        nargs="+",
        metavar="NAME",
        help="explicit corner or corner-set names (overrides the manifest)",
    )
    parser.add_argument(
        "--corner-set",
        choices=sorted(corners_mod.CORNER_SETS),
        help="shorthand for --corners <set>",
    )
    parser.add_argument(
        "--temps",
        nargs="+",
        type=float,
        metavar="C",
        help="temperatures in degrees C (overrides the manifest)",
    )
    parser.add_argument(
        "--supply",
        type=float,
        metavar="V",
        help="nominal supply in volts (overrides the manifest)",
    )
    parser.add_argument(
        "--supply-tol",
        type=float,
        metavar="FRAC",
        help="supply tolerance as a fraction, e.g. 0.10 (0 disables the V axis)",
    )
    parser.add_argument("-j", "--jobs", type=int, default=0, help="parallel ngspice runs")
    parser.add_argument(
        "--timeout",
        type=int,
        default=runner.DEFAULT_TIMEOUT_S,
        help="per-point ngspice timeout in seconds",
    )
    parser.add_argument(
        "--claim",
        default="",
        help="spec line this run substantiates, e.g. 'spec/ldo.md#dropout-voltage' "
        "(overrides the manifest's 'claim')",
    )
    parser.add_argument(
        "--supersedes",
        default="",
        metavar="RECORD_ID",
        help="prior record-id this record corrects or replaces",
    )
    parser.add_argument(
        "--statistical-convention",
        default="",
        metavar="TEXT",
        help="N samples / sigma level, for distribution (Monte Carlo) claims",
    )
    parser.add_argument(
        "--operating-conditions",
        action="append",
        metavar="KEY=VALUE",
        help="LDO-specific evidence field (sim/README.md): load current, output "
        "cap/ESR, enable state, etc. Repeatable, e.g. "
        "--operating-conditions load_current=50mA --operating-conditions "
        "output_cap='1.0uF, ESR=100mOhm'. Overrides/extends the manifest's "
        "'operating_conditions' map.",
    )
    parser.add_argument(
        "--subset-reason",
        default="",
        metavar="TEXT",
        help="why this run is not the full mandated PVT matrix; required before "
        "a subset run may be recorded as evidence",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="run but do not record evidence (debugging only)",
    )
    parser.add_argument("--quiet", action="store_true", help="only print the summary")
    parser.add_argument("--version", action="version", version=f"gf180-ldo harness {HARNESS_VERSION}")
    return parser


def cmd_list() -> int:
    print("Experiments (sim/<slug>/testbench/tb.json):")
    for directory in tb_mod.discover(SIM_DIR):
        try:
            tb = tb_mod.load(directory)
            print(f"  {directory.name:<20} {tb.description or tb.name}")
        except Exception as exc:  # noqa: BLE001 - surface bad manifests, keep listing
            print(f"  {directory.name:<20} !! {exc}")
    print("\nCorner sets:")
    for name, members in sorted(corners_mod.CORNER_SETS.items()):
        print(f"  {name:<20} {', '.join(members)}")
    print("\nCorners:")
    for name, corner in corners_mod.CORNERS.items():
        print(f"  {name:<20} {corner.description}")
        print(f"  {'':<20} sections: {' '.join(corner.sections)}")
    return EXIT_OK


def cmd_check_env() -> int:
    status = EXIT_OK
    try:
        version = runner.ngspice_version()
        print(f"ngspice : OK   {version}")
    except NgspiceMissing as exc:
        print(f"ngspice : MISSING\n{exc}")
        status = EXIT_ENVIRONMENT
    try:
        pdk = find_pdk()
        print(f"PDK     : OK   {pdk.path} (open_pdks {pdk.version}, via {pdk.source})")
        print(f"  models: {pdk.model_lib}")
        print(f"  xschem: {pdk.xschem_dir}")
    except PdkNotFound as exc:
        print(f"PDK     : MISSING\n{exc}")
        status = EXIT_ENVIRONMENT
    return status


def cmd_print_env() -> int:
    """Emit shell exports so xschem/ngspice see the same PDK the harness picked."""
    try:
        pdk = find_pdk()
    except PdkNotFound as exc:
        print(f"# gf180mcu PDK not found\n# {exc.args[0].splitlines()[0]}", file=sys.stderr)
        return EXIT_ENVIRONMENT
    library_path = ":".join(
        str(p)
        for p in [REPO_ROOT / "design"]
        + [d / tb_mod.TESTBENCH_DIRNAME for d in tb_mod.discover(SIM_DIR)]
    )
    print(f'export PDK_ROOT="{pdk.path.parent}"')
    print(f'export PDK="{pdk.variant}"')
    print(f'export GF180_PDK_PATH="{pdk.path}"')
    print(f'export GF180_MODELS="{pdk.ngspice_dir}"')
    print(f'export XSCHEM_USER_LIBRARY_PATH="{library_path}"')
    return EXIT_OK


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if value != 0 and (abs(value) < 1e-3 or abs(value) >= 1e5):
            return f"{value:.6e}"
        return f"{value:.6g}"
    return str(value)


def run(args: argparse.Namespace) -> int:
    tb_path = _resolve_tb_path(args.testbench)
    tb = tb_mod.load(tb_path)

    try:
        pdk = find_pdk()
        ngspice = runner.ngspice_version()
    except (PdkNotFound, NgspiceMissing) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENVIRONMENT

    corner_names = args.corners or ([args.corner_set] if args.corner_set else list(tb.corners))
    corner_list = corners_mod.resolve_corners(corner_names)
    temperatures = args.temps if args.temps is not None else list(tb.temperatures_c)
    nominal = args.supply if args.supply is not None else tb.nominal_supply_v
    tolerance = args.supply_tol if args.supply_tol is not None else tb.supply_tolerance
    supplies = corners_mod.supply_points(nominal, tolerance)
    points = corners_mod.build_grid(corner_list, temperatures, supplies)
    operating_conditions = _parse_operating_conditions(args.operating_conditions)

    # sim/README.md: an evidence record must cover the full mandated PVT
    # matrix unless it states why a subset was used. Refuse to record a thin
    # run without that justification rather than quietly banking weak evidence.
    conformance = report.matrix_conformance(tb, points)
    if not args.no_write and not conformance["full"] and not args.subset_reason:
        print(
            "error: this run is a subset of the PVT matrix CLAUDE.md mandates:\n  - "
            + "\n  - ".join(conformance["missing"])
            + "\nRecord it with --subset-reason '<why>', or re-run the full matrix,"
            "\nor use --no-write if this is just a debugging run.",
            file=sys.stderr,
        )
        return EXIT_ENVIRONMENT

    experiment_dir = tb.experiment_dir
    records_dir = experiment_dir / report.RECORDS_DIR

    jobs = args.jobs or min(8, (os.cpu_count() or 2))
    started = _dt.datetime.now(_dt.timezone.utc)
    # Sample git state *before* the run: the harness writes its own per-corner
    # logs into the tracked evidence tree, so sampling afterwards would mark
    # every record as taken against a dirty tree.
    git = report.git_provenance(REPO_ROOT)
    record_id = report.allocate_record_id(REPO_ROOT, records_dir, started, git=git)
    workdir = WORK_DIR / tb.experiment / record_id
    log_dir = None if args.no_write else experiment_dir / report.CORNERS_DIR / record_id

    if not args.quiet:
        print(f"experiment: {tb.experiment}"
              + (f"  ({tb.description})" if tb.description else ""))
        print(f"pdk       : {pdk.variant} @ {pdk.version}  ({pdk.path})")
        print(f"ngspice   : {ngspice}")
        print(f"corners   : {', '.join(c.name for c in corner_list)}")
        print(f"temps (C) : {', '.join(_fmt(t) for t in temperatures)}")
        print(f"supply (V): {', '.join(_fmt(v) for v in supplies)} "
              f"(nominal {_fmt(nominal)} +/-{tolerance * 100:g}%)")
        print(f"points    : {len(points)}  (jobs={jobs})")
        print(f"record id : {record_id}")
        print()

    completed = 0

    def progress(result):
        nonlocal completed
        completed += 1
        if args.quiet:
            return
        flag = {"ok": "ok  ", "failed": "FAIL", "error": "ERR "}[result.status]
        detail = ""
        if result.status == "ok":
            detail = "  ".join(
                f"{name}={_fmt(result.measurements[name])}" for name in tb.measure
                if name in result.measurements
            )
        else:
            detail = result.message
        print(f"[{completed:>3}/{len(points)}] {flag} {result.point.corner_id:<26} {detail}")

    wall_start = time.monotonic()
    try:
        results = runner.run_grid(
            tb,
            pdk,
            points,
            workdir,
            jobs=jobs,
            timeout_s=args.timeout,
            on_result=progress,
            log_dir=log_dir,
        )
    except NgspiceMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENVIRONMENT
    wall = time.monotonic() - wall_start

    record = report.build_record(
        tb=tb,
        pdk=pdk,
        points=points,
        results=results,
        ngspice=ngspice,
        repo_root=REPO_ROOT,
        record_id=record_id,
        started_utc=started.isoformat(timespec="seconds"),
        wall_seconds=wall,
        claim=args.claim,
        supersedes=args.supersedes,
        statistical_convention=args.statistical_convention,
        operating_conditions=operating_conditions,
        subset_reason=args.subset_reason,
        git=git,
    )

    print()
    print(f"summary ({record['grid']['points_ok']}/{len(points)} points ok, {wall:.1f}s):")
    header = f"  {'measurement':<16}{'min':>16}{'max':>16}{'mean':>16}{'spread %':>12}"
    print(header)
    for name, stats in record["summary"].items():
        if not stats.get("n"):
            print(f"  {name:<16}{'no data':>16}")
            continue
        print(
            f"  {name:<16}{_fmt(stats['min']):>16}{_fmt(stats['max']):>16}"
            f"{_fmt(stats['mean']):>16}{_fmt(stats['spread_pct']):>12}"
        )

    for failure in record["checks"]["failures"]:
        print(
            f"  CHECK FAIL {failure['measurement']} {failure['kind']}={_fmt(failure['limit'])} "
            f"got {_fmt(failure['value'])} at {failure['at']}"
        )

    if not args.no_write:
        snapshot = report.write_netlist_snapshot(tb, experiment_dir, record_id)
        record_path = report.write_record(record, experiment_dir)
        print()
        print(f"record    : {record_path}")
        print(f"snapshot  : {snapshot}")
        print(f"raw logs  : {log_dir}")
    else:
        print()
        print("evidence  : not recorded (--no-write)")
    print(f"work dir  : {workdir}")
    print(f"status    : {record['status'].upper()}")

    if record["status"] == "error":
        return EXIT_SIM_ERROR
    if record["status"] == "fail":
        return EXIT_CHECK_FAILED
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        return cmd_list()
    if args.check_env:
        return cmd_check_env()
    if args.print_env:
        return cmd_print_env()
    if not args.testbench:
        parser.print_help()
        return EXIT_ENVIRONMENT
    try:
        return run(args)
    except (FileNotFoundError, ValueError, KeyError, report.RecordExists) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENVIRONMENT
