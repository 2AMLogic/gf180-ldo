#!/usr/bin/env python3
"""Roll up a mc-output-accuracy Monte Carlo run into a histogram + budget combine.

    python3 sim/mc-output-accuracy/summarize.py <record-id>

Reads the per-sample data out of the committed raw corner logs
(``sim/mc-output-accuracy/corners/<record-id>/<corner-id>.log``) and prints a
Markdown report: the per-corner sigma table, the pooled histogram, a normality
cross-check, and the combine of this run's *statistical* result with the
*deterministic* and *non-simulable* terms of ``design/error_amp.md`` S3.

Nothing here re-simulates anything and nothing here is evidence in its own
right: the evidence is the record under ``records/`` and the raw logs under
``corners/``, both append-only. This script exists so every number quoted in
``sim/mc-output-accuracy/README.md`` can be regenerated from those logs by
anyone, rather than being a hand-typed rollup nobody can check.

Sample lines are emitted by the testbench's Monte Carlo loop as

    "MCSAMPLE <iteration> <dv_1> <dv_2> ... <dv_25>"

where each ``dv_i`` is (V(vo_i) - 1.8 V) in mV for one of the 25 independent
ldo_core copies in that solve. stdlib only, no numpy -- the harness's own rule.
"""

from __future__ import annotations

import math
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent

# --- design/error_amp.md S3, the terms this run does NOT measure -------------
# Statistical, 3 sigma, output-referred. NOT simulable against this PDK
# (mis_r = 0 -- sim/devchar/CONCLUSIONS.md S2), so it is a stated assumption
# hand-computed from the model card's disabled ppolyf_u par_r = 0.021.
DIVIDER_3SIGMA_MV = 3.36
# Deterministic, output-referred, added linearly (S3's combine convention).
SYSTEMATIC_MV = 0.91          # measured, sim/amp-openloop
LINE_REG_MV = 1.65            # ratified allowance, 5 mV/V x 0.33 V
# The load-regulation allowance the ratified window explicitly counts inside
# itself (README: Load-reg < 1 % = 18 mV, verified by #12).
LOAD_REG_MV = 18.0
# The ratified window: 1.8 V +/-2 %, 3 sigma.
WINDOW_MV = 36.0
# design/error_amp.md S3.1's calculated targets for the term this run measures.
TARGET_OUT_3SIGMA_MV = 3.49
TARGET_IN_3SIGMA_MV = 2.33
BETA_INV = 1.5                # 1/beta = Vout/Vref

SAMPLE_RE = re.compile(r'"?MCSAMPLE\s+(\d+)\s+(.*?)"?\s*$')


def read_corner(path: pathlib.Path) -> list[float]:
    samples: list[float] = []
    for line in path.read_text().splitlines():
        match = SAMPLE_RE.match(line.strip())
        if not match:
            continue
        samples.extend(float(v) for v in match.group(2).split())
    return samples


def stats(values: list[float]) -> dict:
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    sd = math.sqrt(var)
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "min": min(values),
        "max": max(values),
        "worst_abs": max(abs(v) for v in values),
    }


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def histogram(values: list[float], bins: int = 25, width: int = 54) -> list[str]:
    lo, hi = min(values), max(values)
    span = hi - lo
    edges = [lo + span * i / bins for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / span * bins), bins - 1)
        counts[idx] += 1
    peak = max(counts)
    out = []
    for i, count in enumerate(counts):
        bar = "#" * round(width * count / peak)
        out.append(f"  {edges[i]:+7.3f} .. {edges[i+1]:+7.3f} mV | {bar:<{width}} {count:5d}")
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    record_id = sys.argv[1]
    corner_dir = HERE / "corners" / record_id
    if not corner_dir.is_dir():
        print(f"no such record: {corner_dir}", file=sys.stderr)
        return 2

    per_corner = {}
    for path in sorted(corner_dir.glob("*.log")):
        values = read_corner(path)
        if values:
            per_corner[path.stem] = values
    if not per_corner:
        print(f"no MCSAMPLE lines under {corner_dir}", file=sys.stderr)
        return 2

    pooled = [v for values in per_corner.values() for v in values]
    pooled_stats = stats(pooled)

    print(f"# mc-output-accuracy rollup -- record {record_id}\n")
    print(f"Corners: {len(per_corner)}   samples/corner: "
          f"{len(next(iter(per_corner.values())))}   total samples: {len(pooled)}\n")

    # ---- per-corner table --------------------------------------------------
    print("## Per-corner distribution (output-referred, mV from 1.8 V)\n")
    print("| corner-id | N | mean | sigma | 3 sigma | min | max | in-referred 3 sigma |")
    print("|---|---|---|---|---|---|---|---|")
    rows = []
    for corner, values in per_corner.items():
        st = stats(values)
        rows.append((corner, st))
        print(f"| `{corner}` | {st['n']} | {st['mean']:+.3f} | {st['sd']:.3f} | "
              f"{3*st['sd']:.3f} | {st['min']:+.3f} | {st['max']:+.3f} | "
              f"{3*st['sd']/BETA_INV:.3f} |")

    worst_sigma = max(rows, key=lambda r: r[1]["sd"])
    worst_mean = max(rows, key=lambda r: abs(r[1]["mean"]))
    worst_sample = max(rows, key=lambda r: r[1]["worst_abs"])
    print()
    print(f"- Worst sigma:            `{worst_sigma[0]}`  sigma = {worst_sigma[1]['sd']:.3f} mV, "
          f"3 sigma = {3*worst_sigma[1]['sd']:.3f} mV out / "
          f"{3*worst_sigma[1]['sd']/BETA_INV:.3f} mV in")
    print(f"- Worst |mean|:           `{worst_mean[0]}`  mean = {worst_mean[1]['mean']:+.3f} mV")
    print(f"- Worst single sample:    `{worst_sample[0]}`  "
          f"|dVout| = {worst_sample[1]['worst_abs']:.3f} mV")

    # ---- pooled distribution ----------------------------------------------
    print("\n## Pooled distribution, all corners (output-referred, mV from 1.8 V)\n")
    print(f"- N = {pooled_stats['n']}, mean = {pooled_stats['mean']:+.4f} mV, "
          f"sigma = {pooled_stats['sd']:.4f} mV, range "
          f"[{pooled_stats['min']:+.3f}, {pooled_stats['max']:+.3f}] mV")
    print("- The pooled sigma mixes corner-to-corner mean shift into the spread and is")
    print("  therefore NOT the mismatch sigma; the per-corner sigmas above are. It is")
    print("  shown only as the population the histogram below is drawn from.\n")
    print("```")
    for line in histogram(pooled):
        print(line)
    print("```")

    # ---- normality cross-check (centred per corner) ------------------------
    print("\n## Normality cross-check (each corner centred on its own mean)\n")
    centred = []
    for values in per_corner.values():
        st = stats(values)
        centred.extend((v - st["mean"]) / st["sd"] for v in values)
    print("| within | observed | Gaussian |")
    print("|---|---|---|")
    for k in (1, 2, 3):
        observed = sum(1 for z in centred if abs(z) <= k) / len(centred)
        expected = 2 * normal_cdf(k) - 1
        print(f"| {k} sigma | {observed*100:.2f} % | {expected*100:.2f} % |")
    print(f"\n- Largest |z| observed over {len(centred)} samples: "
          f"{max(abs(z) for z in centred):.2f} sigma")

    # ---- the combine -------------------------------------------------------
    amp_3sigma = 3 * worst_sigma[1]["sd"]
    stat_rss = math.hypot(amp_3sigma, DIVIDER_3SIGMA_MV)
    det_ratified = SYSTEMATIC_MV + LINE_REG_MV
    det_measured = abs(worst_mean[1]["mean"])
    total_ratified = stat_rss + det_ratified
    total_measured = stat_rss + det_measured

    print("\n## Combine against the ratified window (design/error_amp.md S3 method)\n")
    print("Statistical terms RSS at a common 3 sigma; deterministic terms add linearly;")
    print("everything output-referred through 1/beta = 1.5.\n")
    print("| Term | Output-referred | Kind | Source |")
    print("|---|---|---|---|")
    print(f"| Amp input-pair + mirror mismatch | **{amp_3sigma:.2f} mV** (3 sigma) | "
          f"statistical | THIS RUN, worst corner `{worst_sigma[0]}` |")
    print(f"| Feedback-divider mismatch | {DIVIDER_3SIGMA_MV:.2f} mV (3 sigma) | statistical, "
          f"**assumption** | design/error_amp.md S3.2 -- not simulable (mis_r = 0) |")
    print(f"| Systematic offset + line regulation | {det_ratified:.2f} mV | deterministic | "
          f"ratified budget ({SYSTEMATIC_MV:.2f} + {LINE_REG_MV:.2f}) |")
    print(f"| (same, as measured by this run's worst per-corner mean) | {det_measured:.2f} mV | "
          f"deterministic | THIS RUN, `{worst_mean[0]}` |")
    print(f"| **Statistical RSS** | **{stat_rss:.2f} mV** | | |")
    print(f"| **Total static (ratified deterministic)** | **{total_ratified:.2f} mV** | | "
          f"vs {WINDOW_MV - LOAD_REG_MV:.0f} mV available |")
    print(f"| **Total static (measured deterministic)** | **{total_measured:.2f} mV** | | |")
    print(f"| Load regulation (allowance, #12 verifies) | {LOAD_REG_MV:.1f} mV | | |")
    print(f"| **Total against the +/-{WINDOW_MV:.0f} mV window** | "
          f"**{total_ratified + LOAD_REG_MV:.2f} mV** | | "
          f"**{100*(1 - (total_ratified + LOAD_REG_MV)/WINDOW_MV):.0f} % margin** |")

    # ---- yield -------------------------------------------------------------
    sigma_combined = math.hypot(worst_sigma[1]["sd"], DIVIDER_3SIGMA_MV / 3)
    headroom = WINDOW_MV - LOAD_REG_MV - det_ratified
    k_sigma = headroom / sigma_combined
    yield_frac = 2 * normal_cdf(k_sigma) - 1
    print("\n## Yield\n")
    print(f"- Combined statistical 1 sigma (amp RSS divider): {sigma_combined:.3f} mV")
    print(f"- Headroom after the deterministic terms and the load-regulation")
    print(f"  allowance: {WINDOW_MV:.0f} - {LOAD_REG_MV:.0f} - {det_ratified:.2f} = "
          f"{headroom:.2f} mV")
    print(f"- That headroom is **{k_sigma:.1f} sigma** of the combined statistical")
    print(f"  distribution -> parametric yield {yield_frac*100:.6f} % "
          f"({(1-yield_frac)*1e6:.3g} ppm outside)")

    # ---- verdict against S3.1's calculated target --------------------------
    print("\n## Verdict against design/error_amp.md S3.1\n")
    print(f"- Measured worst-corner amp mismatch: **{amp_3sigma:.2f} mV output-referred / "
          f"{amp_3sigma/BETA_INV:.2f} mV input-referred** (3 sigma)")
    print(f"- S3.1 calculated target:             {TARGET_OUT_3SIGMA_MV:.2f} mV out / "
          f"{TARGET_IN_3SIGMA_MV:.2f} mV in (3 sigma)")
    ratio = amp_3sigma / TARGET_OUT_3SIGMA_MV
    verdict = "PASS" if ratio <= 1.0 else "FAIL"
    print(f"- Measured / calculated = {ratio:.3f} -> **{verdict}**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
