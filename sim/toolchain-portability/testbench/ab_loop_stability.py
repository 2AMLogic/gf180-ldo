#!/usr/bin/env python3
"""Same-netlist / same-PDK / same-host A/B of `sim/loop-stability` across builds.

Issue #254: DR-0025's `wnflag` facts are *categorical* (a bin resolves, or the
deck does not parse), so `wnflag_facts.py` answers them with a yes/no. That is
not the whole portability question. `sim/README.md`'s "a version string is not
a content fingerprint" caveat exists because two *same-version* ngspice-46
builds were measured moving phase margin by ~2 deg and gain margin by ~1 dB on
a byte-identical netlist and PDK at a numerically marginal point
(`sim/loop-stability/records/20260906-090647-3981d88.md`). The question a
major-version bump raises is whether it moves the numbers by more than that
already-accepted build-to-build spread.

This driver answers it by construction: it runs the identical
`sim/loop-stability/testbench/sweep.py` grid, on the identical DUT netlist and
PDK, on one host, once per named ngspice build -- and reports the per-point
phase-margin / gain-margin delta between builds in the same deg / dB units the
existing same-version comparison used.

    python3 sim/toolchain-portability/testbench/ab_loop_stability.py \
        --build ngspice-46-pinned=~/.local/ngspice/bin/ngspice \
        --build ngspice-47=~/.local/ngspice-47/bin/ngspice \
        --loads-ma 0 1 50 --caps-uf 0.33 1.0 4.7 --esrs 0.001 0.2 0.5 \
        --out-dir sim/toolchain-portability/corners/<record-id>

Each build is selected exactly the way
`sim/loop-stability/records/20260906-090647-3981d88.md` selected between the
two ngspice-46 builds on its host: by prepending that install's `bin/` to
`PATH`, so nothing about the deck, the harness or the PDK differs between
arms. `--no-write` is passed to `sweep.py` throughout -- an A/B arm run on an
unvalidated major version must not mint a `sim/loop-stability` record, which
would put a toolchain experiment into the design-evidence trail.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))

from harness.runner import (  # noqa: E402
    ngspice_major_version,
    ngspice_version_at,
    sha256_of,
)

SWEEP = SIM_DIR / "loop-stability" / "testbench" / "sweep.py"

_ROW_RE = re.compile(r"^ROW\s+(.*)$")
_RECORD_ID_RE = re.compile(r"^record id\s*:\s*(\S+)")


@dataclass(frozen=True)
class Point:
    """One loop-gain point: where it was taken."""

    corner_id: str
    iload_a: str
    ceff_f: str
    esr_ohm: str

    @property
    def label(self) -> str:
        return f"{self.corner_id}/{self.iload_a}A_{self.ceff_f}F_{self.esr_ohm}ohm"


@dataclass
class Margin:
    """One loop-gain point: what was measured there."""

    pm_deg: float | None
    gm_db: float | None
    f0_hz: float | None
    vout_v: float | None


def _float_or_none(tok: str) -> float | None:
    try:
        return float(tok)
    except (TypeError, ValueError):
        return None


def parse_corner_logs(logdir: Path) -> dict[Point, Margin]:
    """Every `ROW` line under `logdir`, keyed by where it was taken.

    Phase margin and gain margin are derived exactly as `sweep.py` derives
    them for its own console/record output: `PM = 180 + phase_at_f0_deg` and
    `GM = -gain_at_f180_db`.
    """
    out: dict[Point, Margin] = {}
    for log in sorted(logdir.glob("*.log")):
        corner_id = log.stem
        for line in log.read_text(errors="replace").splitlines():
            match = _ROW_RE.match(line.strip())
            if not match:
                continue
            fields = {}
            for tok in match.group(1).split():
                if "=" in tok:
                    key, value = tok.split("=", 1)
                    fields[key] = value
            point = Point(
                corner_id=corner_id,
                iload_a=fields.get("iload_a", ""),
                ceff_f=fields.get("ceff_f", ""),
                esr_ohm=fields.get("esr_ohm", ""),
            )
            phase = _float_or_none(fields.get("phase_at_f0_deg", ""))
            gain = _float_or_none(fields.get("gain_at_f180_db", ""))
            out[point] = Margin(
                pm_deg=None if phase is None else 180.0 + phase,
                gm_db=None if gain is None else -gain,
                f0_hz=_float_or_none(fields.get("f0_hz", "")),
                vout_v=_float_or_none(fields.get("vout_v", "")),
            )
    return out


def run_arm(ngspice: Path, sweep_args: list[str], console_log: Path) -> Path:
    """Run one sweep arm with `ngspice`'s install first on PATH.

    Returns the directory `sweep.py` wrote its per-corner logs into (under
    `--no-write` that is the scratch workdir, which is exactly what we want:
    the raw output, with no record minted).
    """
    env = dict(os.environ)
    env["PATH"] = f"{ngspice.parent}:{env.get('PATH', '')}"
    proc = subprocess.run(
        [sys.executable, str(SWEEP), "--no-write", *sweep_args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    text = proc.stdout + proc.stderr
    console_log.parent.mkdir(parents=True, exist_ok=True)
    console_log.write_text(text)
    record_id = None
    for line in text.splitlines():
        match = _RECORD_ID_RE.match(line.strip())
        if match:
            record_id = match.group(1)
            break
    if record_id is None:
        raise RuntimeError(f"sweep.py printed no record id (see {console_log})")
    return REPO_ROOT / "sim" / ".work" / "loop-stability" / record_id


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--build",
        action="append",
        required=True,
        metavar="LABEL=PATH",
        help="an ngspice build to run one arm with (repeatable; the FIRST is "
             "the reference every later arm is differenced against)",
    )
    ap.add_argument("--corners", nargs="+", default=None)
    ap.add_argument("--temps", nargs="+", default=None)
    ap.add_argument("--loads-ma", nargs="+", default=None)
    ap.add_argument("--caps-uf", nargs="+", default=None)
    ap.add_argument("--esrs", nargs="+", default=None)
    ap.add_argument("-j", "--jobs", default="8")
    ap.add_argument(
        "--out-dir",
        required=True,
        help="directory to write the per-arm console logs and the delta CSV "
             "into (this run's evidence)",
    )
    args = ap.parse_args()

    builds: list[tuple[str, Path]] = []
    for spec in args.build:
        if "=" not in spec:
            print(f"FATAL: --build wants LABEL=PATH, got {spec!r}", file=sys.stderr)
            return 2
        label, _, path = spec.partition("=")
        exe = Path(path).expanduser().resolve()
        if not exe.exists():
            print(f"FATAL: no such ngspice: {exe}", file=sys.stderr)
            return 2
        builds.append((label, exe))

    sweep_args = ["-j", str(args.jobs)]
    for flag, values in (
        ("--corners", args.corners),
        ("--temps", args.temps),
        ("--loads-ma", args.loads_ma),
        ("--caps-uf", args.caps_uf),
        ("--esrs", args.esrs),
    ):
        if values:
            sweep_args += [flag, *[str(v) for v in values]]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[Point, Margin]] = {}
    for label, exe in builds:
        banner = ngspice_version_at(exe)
        print(f"== arm {label}: {exe}")
        print(f"   banner : {banner}")
        print(f"   major  : {ngspice_major_version(banner)}")
        print(f"   sha256 : {sha256_of(exe)}")
        logdir = run_arm(exe, sweep_args, out_dir / f"console-{label}.log")
        rows = parse_corner_logs(logdir)
        print(f"   points : {len(rows)}")
        results[label] = rows
        # `sim/README.md`: raw per-corner ngspice output is evidence, not
        # scratch. `--no-write` leaves it in the gitignored scratch workdir,
        # so copy it under this run's own evidence directory.
        kept = out_dir / label
        kept.mkdir(parents=True, exist_ok=True)
        for log in sorted(logdir.glob("*.log")):
            shutil.copy2(log, kept / log.name)

    ref_label = builds[0][0]
    ref = results[ref_label]

    csv_path = out_dir / "ab-margins.csv"
    fieldnames = ["corner_id", "iload_a", "ceff_f", "esr_ohm"]
    for label, _ in builds:
        fieldnames += [f"pm_deg[{label}]", f"gm_db[{label}]"]
    for label, _ in builds[1:]:
        fieldnames += [f"dpm_deg[{label}-{ref_label}]",
                       f"dgm_db[{label}-{ref_label}]"]
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for point in sorted(ref, key=lambda p: (p.corner_id, p.iload_a,
                                                p.ceff_f, p.esr_ohm)):
            row = {
                "corner_id": point.corner_id,
                "iload_a": point.iload_a,
                "ceff_f": point.ceff_f,
                "esr_ohm": point.esr_ohm,
            }
            for label, _ in builds:
                margin = results[label].get(point)
                row[f"pm_deg[{label}]"] = "" if not margin or margin.pm_deg is None \
                    else f"{margin.pm_deg:.6f}"
                row[f"gm_db[{label}]"] = "" if not margin or margin.gm_db is None \
                    else f"{margin.gm_db:.6f}"
            for label, _ in builds[1:]:
                a, b = results[label].get(point), ref[point]
                dpm = "" if not a or a.pm_deg is None or b.pm_deg is None \
                    else f"{a.pm_deg - b.pm_deg:.6f}"
                dgm = "" if not a or a.gm_db is None or b.gm_db is None \
                    else f"{a.gm_db - b.gm_db:.6f}"
                row[f"dpm_deg[{label}-{ref_label}]"] = dpm
                row[f"dgm_db[{label}-{ref_label}]"] = dgm
            writer.writerow(row)
    print(f"\nwrote {csv_path} ({len(ref)} points)")

    print(f"\nreference arm: {ref_label}")
    overall_ok = True
    for label, _ in builds[1:]:
        other = results[label]
        missing = [p for p in ref if p not in other]
        extra = [p for p in other if p not in ref]
        dpm = [(abs(other[p].pm_deg - ref[p].pm_deg), p)
               for p in ref
               if p in other and other[p].pm_deg is not None
               and ref[p].pm_deg is not None]
        dgm = [(abs(other[p].gm_db - ref[p].gm_db), p)
               for p in ref
               if p in other and other[p].gm_db is not None
               and ref[p].gm_db is not None]
        n_bitident = sum(1 for d, _ in dpm if d == 0.0)
        print(f"\n-- {label} vs {ref_label}")
        print(f"   compared points      : {len(dpm)}"
              f" (missing {len(missing)}, extra {len(extra)})")
        print(f"   PM identical in the logged value  : {n_bitident}/{len(dpm)}")
        if dpm:
            worst_pm, at_pm = max(dpm, key=lambda t: t[0])
            print(f"   worst |dPM|          : {worst_pm:.6f} deg at {at_pm.label}")
        if dgm:
            worst_gm, at_gm = max(dgm, key=lambda t: t[0])
            print(f"   worst |dGM|          : {worst_gm:.6f} dB  at {at_gm.label}")
        if missing or extra:
            overall_ok = False
            print(f"   !! point-set mismatch: {len(missing)} missing, "
                  f"{len(extra)} extra -- one arm did not run the same grid")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
