#!/usr/bin/env python3
"""The soft-start loop-gain experiment's Markdown record renderer (issue #608).

Everything between the old ``# the record`` banner and ``render_record`` in
``sweep.py`` -- the state/A-B/hand-over tables, the cross-check,
attribution and FB-cap sections, and the whole-record assembly -- moved
here verbatim in the #608 split: pure text assembly over already-measured
values, with no deck rendering, ngspice invocation or measurement logic.
The driver calls exactly one entry point, ``render_record``.

The split is code motion, not a rewrite. Its acceptance check was a
differential re-render -- identical fabricated inputs pushed through the
pre-split and post-split ``render_record``, byte-identical Markdown out --
and that is the contract to preserve: a rendering change belongs in a
commit that says so, not one that moves a function.

Dependencies stay one-way. The shared value types, operating points and
tolerances come from ``model.py``, loaded by path under its unique name
through the same ``sys.modules.get`` guard ``sweep.py`` uses (see that
module's docstring for why the guard exists); the margin helpers and bars
come from ``harness.loop_margin`` directly (issue #630), exactly as the
driver imports them.
"""

from __future__ import annotations

import datetime as _dt
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness.loader import load_script  # noqa: E402
from harness.loop_margin import (  # noqa: E402
    F_START,
    F_STOP,
    GM_MIN_DB,
    PM_MIN_DEG,
    RESURGENCE_MAX_DB,
    VOUT_NOM_V,
    fmt_uf,
    gm_str,
    pm_str,
    res_str,
    worst_of,
    worst_resurgence_of,
)
from harness.report import (  # noqa: E402
    environment as harness_environment,
    environment_lines,
)
from harness.runner import ngspice_binary_sha256, ngspice_version  # noqa: E402

sys.path.insert(0, str(HERE))
import netlist_variants as nv  # noqa: E402

# The shared model layer, by path under its unique name. The guard reuses
# the copy `sweep.py` already loaded (or leaves ours for it to find)
# instead of re-executing the file: two executions would mean two `Row`
# classes -- see model.py's docstring.
model = sys.modules.get("ss_loop_gain_model")
if model is None:
    model = load_script("ss_loop_gain_model", HERE / "model.py")

# Bind the model names the moved code uses as module globals, so the
# section below is byte-for-byte what it was inside `sweep.py`.
ATTR_FLOOR_DB = model.ATTR_FLOOR_DB
ATTR_FLOOR_DEG = model.ATTR_FLOOR_DEG
FB_CAP_GM_TOL_DB = model.FB_CAP_GM_TOL_DB
FB_CAP_PM_TOL_DEG = model.FB_CAP_PM_TOL_DEG
HANDOVER_ACQUISITION_SSR_V = model.HANDOVER_ACQUISITION_SSR_V
HANDOVER_INTENT_GM_UA_PER_V = model.HANDOVER_INTENT_GM_UA_PER_V
HANDOVER_INTENT_RELEASE_V = model.HANDOVER_INTENT_RELEASE_V
HANDOVER_RELEASE_A = model.HANDOVER_RELEASE_A
HANDOVER_SSR_V = model.HANDOVER_SSR_V
HovCurve = model.HovCurve
LS_DIAGNOSTIC_RECORD = model.LS_DIAGNOSTIC_RECORD
PHASES = model.PHASES
Row = model.Row
SSR_POINT_LABEL = model.SSR_POINT_LABEL
VREF_V = model.VREF_V
XCHECK_F0_TOL_FRAC = model.XCHECK_F0_TOL_FRAC
XCHECK_GM_TOL_DB = model.XCHECK_GM_TOL_DB
XCHECK_PM_TOL_DEG = model.XCHECK_PM_TOL_DEG
XCHECK_MISMATCH_SHOWN = model.XCHECK_MISMATCH_SHOWN
_hz = model._hz
gm_mismatch_at = model.gm_mismatch_at
group = model.group
key_of = model.key_of


# ---------------------------------------------------------------------------
# the record
# ---------------------------------------------------------------------------
def _state_order(key: tuple) -> tuple:
    phase_rank = {"ramp": 0, "sink": 1, "anchor": 2}
    try:
        ssr = float(key[2])
    except ValueError:
        ssr = 99.0
    return (phase_rank.get(key[1], 9), ssr, key[0])


def state_table(rows: list[Row]) -> list[str]:
    """Worst-case margin per (phase, ramp state, variant), over the whole grid."""
    out = ["| phase | V(SSR) | variant | worst PM (deg) | GM there (dB) | f0 there (Hz) | worst corner / config | VOUT there (V) | I_inj there (uA) |",
           "|---|---|---|---|---|---|---|---|---|"]
    for key in sorted(group(rows, lambda r: (r.variant, r.phase, r.ssr_cmd)),
                      key=_state_order):
        bucket = group(rows, lambda r: (r.variant, r.phase, r.ssr_cmd))[key]
        measured = [r for r in bucket if r.pm_deg is not None]
        if not measured:
            out.append(
                f"| `{key[1]}` | {key[2]} | `{key[0]}` | *no 0 dB crossing at "
                f"any of the {len(bucket)} points* | - | - | - | "
                f"{bucket[0].vout_v:.4g} | {bucket[0].iinj_a * 1e6:+.3f} |")
            continue
        w = worst_of(measured)
        out.append(
            f"| `{key[1]}` | {key[2]} | `{key[0]}` | **{pm_str(w)}** | "
            f"{gm_str(w)} | {_hz(w.f0_hz)} | `{w.corner_id}` / {w.cfg_id} | "
            f"{w.vout_v:.4g} | {w.iinj_a * 1e6:+.3f} |")
    return out


def ab_table(rows: list[Row]) -> tuple[list[str], list[tuple]]:
    """device - binj, point for point, worst delta per (phase, ramp state)."""
    by_key = {key_of(r): r for r in rows}
    pairs: list[tuple[Row, Row, float | None, float | None]] = []
    for r in rows:
        if r.variant != "device":
            continue
        mate = by_key.get(("binj", r.phase, r.ssr_cmd, r.corner_id,
                           r.ceff_f, r.esr_ohm))
        if mate is None:
            continue
        dpm = (None if r.pm_deg is None or mate.pm_deg is None
               else r.pm_deg - mate.pm_deg)
        dgm = (None if math.isinf(r.gm_db) or math.isinf(mate.gm_db)
               else r.gm_db - mate.gm_db)
        pairs.append((r, mate, dpm, dgm))

    out = ["| phase | V(SSR) | n | worst dPM (deg) | at | worst dGM (dB) | dVOUT there (V) | dI_inj there (uA) |",
           "|---|---|---|---|---|---|---|---|"]
    buckets: dict[tuple, list] = {}
    for p in pairs:
        buckets.setdefault((p[0].phase, p[0].ssr_cmd), []).append(p)
    for key in sorted(buckets, key=lambda k: _state_order(("", k[0], k[1]))):
        b = buckets[key]
        measured = [p for p in b if p[2] is not None]
        if not measured:
            out.append(f"| `{key[0]}` | {key[1]} | {len(b)} | *no paired "
                       f"0 dB crossing* | - | - | "
                       f"{b[0][0].vout_v - b[0][1].vout_v:+.4g} | "
                       f"{(b[0][0].iinj_a - b[0][1].iinj_a) * 1e6:+.3f} |")
            continue
        w = min(measured, key=lambda p: p[2])
        wg = min((p for p in b if p[3] is not None), key=lambda p: p[3],
                 default=None)
        out.append(
            f"| `{key[0]}` | {key[1]} | {len(measured)} | **{w[2]:+.2f}** | "
            f"`{w[0].corner_id}` / {w[0].cfg_id} | "
            f"{'n/a' if wg is None else f'{wg[3]:+.2f}'} | "
            f"{w[0].vout_v - w[1].vout_v:+.4g} | "
            f"{(w[0].iinj_a - w[1].iinj_a) * 1e6:+.3f} |")
    return out, pairs


def handover_table(rows: list[Row], corner_id: str) -> list[str]:
    """The measured DC hand-over transfer at one corner: I_inj and VOUT vs SSR."""
    sel = [r for r in rows
           if r.corner_id == corner_id and r.phase == "ramp"
           and r.ceff_f == min(r2.ceff_f for r2 in rows)
           and abs(r.esr_ohm - 0.1) < 1e-12]
    out = ["| V(SSR) | variant | landed VOUT (V) | landed FB (V) | I_inj into FB (uA) | 1.5*V(SSR) (V) |",
           "|---|---|---|---|---|---|"]
    for key in sorted({(r.ssr_cmd, r.variant) for r in sel},
                      key=lambda k: (float(k[0]), k[1])):
        for r in sel:
            if (r.ssr_cmd, r.variant) == key:
                out.append(
                    f"| {r.ssr_cmd} | `{r.variant}` | {r.vout_v:.5f} | "
                    f"{r.fb_v:.5f} | {r.iinj_a * 1e6:+.4f} | "
                    f"{1.5 * r.ssr_v:.5f} |")
                break
    return out


def _ua(a: float | None, digits: int = 4) -> str:
    return "n/a" if a is None or not math.isfinite(a) else f"{a * 1e6:+.{digits}f}"


def handover_extremes_table(curves: list[HovCurve]) -> list[str]:
    """Per variant, the PVT extremes of every metric, with the corner named."""
    out = [
        "| metric | design intent (`Binj_ss`) | variant | min over PVT | max over PVT | worst corner |",
        "|---|---|---|---|---|---|",
    ]

    def block(label, intent, getter, fmt, worst_is_max=True):
        for variant in sorted({c.variant for c in curves}):
            sel = [c for c in curves if c.variant == variant]
            vals = [(getter(c), c) for c in sel]
            live = [(v, c) for v, c in vals
                    if v is not None and math.isfinite(v)]
            if not live:
                out.append(f"| {label} | {intent} | `{variant}` | *never* | "
                           f"*never* | - |")
                continue
            lo = min(live, key=lambda t: t[0])
            hi = max(live, key=lambda t: t[0])
            worst = hi if worst_is_max else lo
            miss = len(vals) - len(live)
            note = f" ({miss}/{len(vals)} corners: *never*)" if miss else ""
            out.append(
                f"| {label} | {intent} | `{variant}` | {fmt(lo[0])} | "
                f"{fmt(hi[0])}{note} | `{worst[1].corner_id}` |")

    block("`I_inj` at `V(SSR) = 0` (uA)", "+6.0000 exactly, PVT-invariant",
          lambda c: c.iinj_start_a, lambda v: _ua(v))
    block(f"output the loop must acquire at hold release, `V(SSR)` = "
          f"{HANDOVER_ACQUISITION_SSR_V:g} V (mV)",
          f"{1e3 * max(0.0, VREF_V - 300e3 * ((VREF_V - HANDOVER_ACQUISITION_SSR_V) * 5e-6 - VREF_V / 600e3)):.1f}"
          f" (= 1.5 x {HANDOVER_ACQUISITION_SSR_V:g} V, the ramp's own value)",
          lambda c: c.acquisition_step_v(HANDOVER_ACQUISITION_SSR_V),
          lambda v: f"{v * 1e3:.2f}")
    block("transconductance over the live range (uA/V)",
          "5.000 exactly, PVT-invariant",
          lambda c: c.gm_a_per_v, lambda v: f"{v * 1e6:.3f}", worst_is_max=False)
    block("`I_inj` still flowing at `V(SSR) = VREF` (uA)", "0 exactly",
          lambda c: c.iinj_at_vref_a, lambda v: _ua(v))
    block(f"`V(SSR)` at which `I_inj` falls below {HANDOVER_RELEASE_A * 1e9:g} nA and stays there (V)",
          f"{HANDOVER_INTENT_RELEASE_V:g} exactly",
          lambda c: c.release_ssr_v, lambda v: f"{v:.3f}")
    block("highest `V(SSR)` at which the loop is OUT of regulation (V)",
          "none: the ideal element never leaves the loop in regulation",
          lambda c: c.saturated_to_ssr_v, lambda v: f"{v:.3f}")
    block("largest `V(FB)` anywhere on the ramp (V)",
          f"{VREF_V:g} + a fraction of a mV",
          lambda c: c.fb_max_v, lambda v: f"{v:.5f}")
    block("`VOUT` error at the top of the swept ramp (mV)", "0",
          lambda c: c.vout_top_err_v, lambda v: f"{v * 1e3:+.2f}",
          worst_is_max=False)
    return out


def handover_curve_table(curves: list[HovCurve], corner_id: str,
                         step_v: float = 0.2) -> list[str]:
    """One worked transfer, both variants side by side, every `step_v`."""
    sel = {c.variant: c for c in curves if c.corner_id == corner_id}
    if not sel:
        return []
    variants = sorted(sel)
    head = ["| `V(SSR)` (V) | intent `I_inj` (uA) |"]
    sep = ["|---|---|"]
    for v in variants:
        head.append(f" `{v}` `I_inj` (uA) | `{v}` `VOUT` (V) | `{v}` `V(FB)` (V) |")
        sep.append("---|---|---|")
    out = ["".join(head), "".join(sep)]
    ref = sel[variants[0]]
    n = 0
    for p in ref.points:
        if abs(p.ssr_v / step_v - round(p.ssr_v / step_v)) > 1e-6:
            continue
        n += 1
        intent = max(0.0, (VREF_V - p.ssr_v) * HANDOVER_INTENT_GM_UA_PER_V)
        line = [f"| {p.ssr_v:.2f} | {intent:+.4f} |"]
        for v in variants:
            q = min(sel[v].points, key=lambda x: abs(x.ssr_v - p.ssr_v))
            flag = "" if q.in_regulation else " **(open loop)**"
            line.append(f" {_ua(q.iinj_a)} | {q.vout_v:.5f} | "
                        f"{q.fb_v:.5f}{flag} |")
        out.append("".join(line))
    return out if n else []


def handover_section(curves: list[HovCurve], consistency) -> str:
    if not curves:
        return ("  **Not run** (`--skip-handover`). This record therefore "
                "reports the injection element's margins but not its "
                "transfer.\n")
    lines: list[str] = [
        f"  `tb_ss_handover.spice.in`, {len(HANDOVER_SSR_V)} pinned `V(SSR)` "
        f"from {HANDOVER_SSR_V[0]:g} V to {HANDOVER_SSR_V[-1]:g} V in "
        f"{1e3 * (HANDOVER_SSR_V[1] - HANDOVER_SSR_V[0]):g} mV steps, on the",
        "  same circuit with the same loop break and the same resistive 36 ohm",
        "  load as the `ramp` phase above, one `op` per point. `I_inj` is the",
        "  same KCL-at-`FB` expression the margin rows use, so a point here and",
        "  a margin row at the same `V(SSR)` are the same measurement -- which",
        "  is checked below, not assumed. Every point of every corner is in the",
        "  `-handover.csv` beside this record; what follows is its extremes.",
        "",
    ]
    lines += ["  " + l for l in handover_extremes_table(curves)]
    lines += [
        "",
        "  The `design intent` column uses the `binj` transfer,",
        "  `I = max(0, (V(VREF) - V(SSR)) * 5.0e-6)`. Each measured column",
        "  uses the landed DC operating points at the pinned ramp voltages.",
        "  Ramp timing is measured separately in `sim/soft-start/`.",
        "",
    ]
    ct = handover_curve_table(curves, "tt_27c_3.30v")
    if ct:
        lines += [
            "  One worked transfer at `tt_27c_3.30v`, both variants side by",
            "  side (the full 0.025 V grid, every PVT corner, is in the CSV):",
            "",
        ]
        lines += ["  " + l for l in ct]
        lines.append("")

    # The supply dependence, computed rather than asserted: the release point
    # against VIN at fixed process and temperature.
    dev = [c for c in curves if c.variant == "device"]
    supply_lines = []
    for key in sorted({(c.corner, c.temp_c) for c in dev}):
        sel = sorted((c for c in dev if (c.corner, c.temp_c) == key),
                     key=lambda c: c.vin_v)
        rel = [(c.vin_v, c.release_ssr_v) for c in sel]
        if len(rel) < 2 or any(r is None for _, r in rel):
            continue
        dv = rel[-1][0] - rel[0][0]
        dr = rel[-1][1] - rel[0][1]
        supply_lines.append((key, dv, dr, rel))
    if supply_lines:
        worst = max(supply_lines, key=lambda t: abs(t[2]))
        slopes = [t[2] / t[1] for t in supply_lines if t[1]]
        lines += [
            "  **Supply dependence of the `device` release point.** Across",
            f"  {len(supply_lines)} (process, temperature) pairs, raising `VIN`",
            "  from the lowest to the highest measured supply changes the",
            "  release voltage `V(SSR)`",
            f"  by **{min(t[2] for t in supply_lines):+.3f} V to "
            f"{max(t[2] for t in supply_lines):+.3f} V**",
            f"  (mean {sum(slopes) / len(slopes):.3f} V of ramp node per volt of",
            "  supply). The largest absolute change occurs at",
            f"  `{worst[0][0]}`, {worst[0][1]:g} degC -- "
            + ", ".join(f"{v:.2f} V -> {r:.3f} V" for v, r in worst[3]) + ".",
            "",
        ]

    # Compare the landed output steps at the same ramp voltage and corner.
    binj_by_corner = {c.corner_id: c for c in curves if c.variant == "binj"}
    pair_lines = []
    for c in dev:
        mate = binj_by_corner.get(c.corner_id)
        if mate is None:
            continue
        device_step = c.acquisition_step_v(HANDOVER_ACQUISITION_SSR_V)
        binj_step = mate.acquisition_step_v(HANDOVER_ACQUISITION_SSR_V)
        pair_lines.append((device_step - binj_step, device_step, binj_step, c.corner_id))
    if pair_lines:
        _, device_step, binj_step, corner_id = max(pair_lines, key=lambda t: abs(t[0]))
        ratio = f"{device_step / binj_step:.1f}" if binj_step else "n/a"
        lines += [
            f"  **Output step at acquisition.** At `V(SSR)` = {HANDOVER_ACQUISITION_SSR_V:g} V,",
            "  the landed output difference (`device` minus `binj`) ranges from",
            f"  **{min(t[0] for t in pair_lines) * 1e3:+.1f} mV to "
            f"{max(t[0] for t in pair_lines) * 1e3:+.1f} mV** over {len(pair_lines)} paired corners.",
            f"  At `{corner_id}`, the corner with the largest absolute difference, the steps are",
            f"  {device_step * 1e3:.2f} mV for `device` and {binj_step * 1e3:.2f} mV for `binj`",
            f"  (ratio {ratio}).",
            "  `device` leaves regulation on the DC sweep at "
            f"{sum(c.saturated_to_ssr_v is not None for c in dev)} of {len(dev)} corners.",
            "  Transient inrush also depends on the time the loop takes to acquire the output.",
        ]
        for _, device_step, binj_step, corner_id in pair_lines:
            if corner_id == "tt_-40c_2.97v" and binj_step:
                lines.append(
                    f"  At `{corner_id}` the DC step ratio is {device_step / binj_step:.1f}. "
                    "The #191 transient A/B measured 166.7 mA against 0.468 mA at this corner.")
        lines.append("")

    if consistency and consistency[0] is not None:
        d, r, hov = consistency[0]
        lines += [
            f"  **Cross-deck consistency.** Over the {consistency[1]} points "
            f"where a hand-over sweep point and a margin row share a "
            f"(corner, variant, `V(SSR)`), the largest disagreement in the "
            f"landed output voltage is **{d * 1e6:.3f} uV** "
            f"(at `{r.corner_id}` / {r.state_id}). The two decks are separate "
            f"files running separate analyses; this is the measurement that "
            f"they are nevertheless the same circuit at the same operating "
            f"point, so the transfer above and the margins below describe one "
            f"thing and not two.",
            "",
        ]
    return "\n".join(lines) + "\n"


def xcheck_section(xcheck: dict) -> str:
    if xcheck.get("skipped"):
        return ("  **Not run** (`--skip-crosscheck`, or no anchor phase in this "
                "run). This record therefore makes no claim that its anchor "
                "reproduces `sim/loop-stability/`.\n")
    lines: list[str] = []
    if "error" in xcheck:
        lines.append(f"  The same-host re-run could not be made: "
                     f"{xcheck['error']}.\n")
    compared: set[str] = set()
    for label, key, caveat in (
        ("Same host, same session, same ngspice binary", "here",
         "This comparison has **no toolchain term in it at all**: "
         "`sim/loop-stability/testbench/sweep.py` was invoked unmodified, from "
         "this driver, on this host, in this session, against the same PDK and "
         "the same `.spiceinit`. Any delta here is the deck difference (an "
         "unconnected `SSR` port) and nothing else."),
        ("Against the committed record `20260906-071437-fff0bf0`", "committed",
         "This one **does** have a toolchain term: that record was produced on "
         "a different host with a different ngspice build, which is exactly the "
         "case `sim/README.md`'s reproducibility caveat (#182/#185) says to "
         "check before reading a delta as evidence about the design. It is "
         "reported for completeness, and the bar it is held to is #182's own "
         "~2 deg / ~1 dB movement class."),
    ):
        if key not in xcheck:
            continue
        deltas = xcheck[key]
        if not deltas:
            lines.append(f"  **{label}** -- **0 shared points**: this grid "
                         f"shares no (corner, C_eff, ESR) with the "
                         f"cross-check, so neither a delta nor a verdict is "
                         f"reported for this reference.\n")
            continue
        compared.add(key)
        ok, wpm, wgm, wf0, n, mism = xcheck[f"{key}_verdict"]
        worst = max((d for d in deltas if d[2] is not None),
                    key=lambda d: abs(d[2]), default=None)
        lines.append(f"  **{label}** -- {n} shared "
                     f"(corner, C_eff, ESR) points at 50 mA:\n")
        lines.append(f"  - worst |dPM| **{wpm:.3f} deg** (budget "
                     f"{XCHECK_PM_TOL_DEG:g} deg)")
        lines.append(f"  - worst |dGM| **{wgm:.3f} dB** (budget "
                     f"{XCHECK_GM_TOL_DB:g} dB)")
        lines.append(f"  - worst |df0/f0| **{100 * wf0:.3f}%** (budget "
                     f"{100 * XCHECK_F0_TOL_FRAC:g}%)")
        if worst is not None:
            r, ref, dpm, _dgm, _df0, _xgm = worst
            ref_pm = ref["pm_deg"]
            ref_pm_s = "n/a" if ref_pm is None else f"{ref_pm:.2f}"
            lines.append(
                f"  - largest single mover: `{r.corner_id}` / {r.cfg_id} -- "
                f"this record {pm_str(r)} deg, that one {ref_pm_s} deg "
                f"({dpm:+.3f} deg)")
        lines.extend(xcheck_mismatch_lines(n, mism))
        lines.append(f"  - **verdict: {'AGREES' if ok else 'DISAGREES'}**")
        lines.append(f"\n  {caveat}\n")
    if "committed" in compared:
        reference = ("  The most recent loop-stability record that shares points with\n"
                     "  this run is `20260906-071437-fff0bf0`, compared above")
    else:
        reference = ("  The loop-stability record this experiment's default grid is\n"
                     "  built to overlap is `20260906-071437-fff0bf0`")
        if "committed" in xcheck:
            reference += ("; this run's join\n"
                          "  against it produced no shared points, so no comparison with it\n"
                          "  is claimed")
    lines.append(
        f"  **Why `20260906-071437-fff0bf0` is the reference instead of\n"
        f"  `{LS_DIAGNOSTIC_RECORD}`, which is `sim/loop-stability/`'s\n"
        f"  latest record.** `{LS_DIAGNOSTIC_RECORD}` is a *diagnostic* record\n"
        f"  (issue #182's toolchain-provenance investigation): its own\n"
        f"  \"Netlist provenance\" field says **diagnostic -- no new full-matrix\n"
        f"  simulation**, it has no `-matrix.csv`, and its evidence is\n"
        f"  re-simulations of a single control point, `ff_125c_2.97v` at\n"
        f"  I_load = 1 mA / C_eff = 0.33 uF / ESR = 0.2 ohm. That point shares no\n"
        f"  (load, C_eff) coordinate with this experiment's default grid, which\n"
        f"  is the rated 50 mA load at 1 uF and 4.7 uF because that is the\n"
        f"  operating point `sim/soft-start/` runs and therefore the one the\n"
        f"  #191 regression is about (the grid this run actually used is listed\n"
        f"  under *Corner matrix run*). There is consequently **no shared grid\n"
        f"  point** between the two records to compare, and the honest\n"
        f"  statement is that this is a discrepancy of coverage, not of result.\n"
        + reference
        + ("; and the same-host re-run\n  above is a stronger check than "
           "either, because it removes the\n  toolchain term "
           f"`{LS_DIAGNOSTIC_RECORD}` exists to document"
           if "here" in compared else "")
        + ".\n"
    )
    return "\n".join(lines) + "\n"


def xcheck_mismatch_lines(n: int, mism: list) -> list[str]:
    """The gain-margin crossing-mismatch bullet of one anchor comparison."""
    if not mism:
        return [f"  - gain-margin crossing mismatches: **0 of {n}** (every shared "
                "point has a -180 deg crossing in band on both sides or on neither)"]
    return [
        f"  - **gain-margin crossing mismatch at {len(mism)} of {n} points** -- "
        "one sweep found a -180 deg crossing in band and the other did not. "
        "Such a pair has no dB delta, so it stands outside the "
        f"{XCHECK_GM_TOL_DB:g} dB budget whatever the finite deltas above say:\n",
        *(f"    - {gm_mismatch_at(d[0], d[1]['gm_db'])}"
          for d in mism[:XCHECK_MISMATCH_SHOWN]),
        *((f"    - ... and {len(mism) - XCHECK_MISMATCH_SHOWN} more",)
          if len(mism) > XCHECK_MISMATCH_SHOWN else ()),
    ]


def attribution_section(attribution: dict | None) -> str:
    if not attribution:
        return ("  Not run (no device-variant point with a 0 dB crossing, or "
                "`--explore`).\n")
    w = attribution["worst"]
    lines = [
        f"  Worst measured device-variant point in this record: "
        f"`{w.corner_id}` at {w.state_id}, {w.cfg_id} -- "
        f"PM {pm_str(w)} deg, GM {gm_str(w)} dB, crossover {_hz(w.f0_hz)} Hz.",
        "",
        "  Each case uses the corner, ramp state and output network named above.",
        "  The `acopen-*` and `acshort-*` cases each remove one AC coupling",
        "  from `device` using a 1 GH inductor in series with a device terminal or",
        "  a 1 F capacitor from a node to a rail: an inductor is a short at DC",
        "  and a capacitor is an open at DC, so the operating point does not",
        "  move -- which is the point, and which the landed `VOUT`/`I_inj`",
        "  columns let a reader check rather than take on trust.",
        "",
        "| case | what changed | PM (deg) | dPM vs as-committed | GM (dB) | f0 (Hz) | landed VOUT (V) | landed I_inj (uA) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    base = next((c for c in attribution["cases"]
                 if c["tag"] == "as-committed" and "row" in c), None)
    for c in attribution["cases"]:
        if "row" not in c:
            lines.append(f"| `{c['tag']}` | {c['desc']} | *failed: "
                         f"{c.get('error', 'unknown')}* | | | | | |")
            continue
        r = c["row"]
        dpm = ("-" if base is None or r.pm_deg is None or base["row"].pm_deg is None
               else f"{r.pm_deg - base['row'].pm_deg:+.3f}")
        lines.append(
            f"| `{c['tag']}` | {c['desc']} | {pm_str(r)} | {dpm} | "
            f"{gm_str(r)} | {_hz(r.f0_hz)} | {r.vout_v:.5f} | "
            f"{r.iinj_a * 1e6:+.4f} |")
    lines.append("")
    if attribution["fits"]:
        lines += [
            "  The frequency-domain form of each of those deltas, over the whole",
            "  0.01 Hz - 1 GHz curve rather than at the crossover alone. The first",
            "  two columns are model-free: the largest magnitude and phase",
            "  difference from the committed variant anywhere in band, and where. The",
            "  pole/zero columns interpret that as `T(as-committed)/T(case)` =",
            "  `k*(1+s/z)/(1+s/p)`, which is what a single added R-C on one node",
            "  produces exactly -- so the fit is a claim the data can refute, and",
            "  the residual is printed for that purpose. Where the model-free",
            f"  difference is below the numerical floor ({ATTR_FLOOR_DB:g} dB /",
            f"  {ATTR_FLOOR_DEG:g} deg) no fit is attempted: there is no pole or",
            "  zero to attribute, and reporting one anyway would be fitting noise.",
            "",
            "| ratio | max d|T| (dB) @ (Hz) | max dphase (deg) @ (Hz) | fitted zero (Hz) | fitted pole (Hz) | DC offset (dB) | fit residual |",
            "|---|---|---|---|---|---|---|",
        ]
        for f in attribution["fits"]:
            ext = f.get("extremes")
            if ext is None:
                lines.append(f"| `as-committed / {f['tag']}` | *curves not "
                             f"comparable* | | | | | |")
                continue
            emag = f"{ext[0]:+.4f} @ {ext[1]:.4g}"
            eph = f"{ext[2]:+.4f} @ {ext[3]:.4g}"
            if not f["fit"]:
                lines.append(
                    f"| `as-committed / {f['tag']}` | {emag} | {eph} | "
                    f"*below the floor* | *below the floor* | - | - |")
                continue
            k_db, fz, fp, resid = f["fit"]
            lines.append(
                f"| `as-committed / {f['tag']}` | {emag} | {eph} | {fz:.4g} | "
                f"{fp:.4g} | {k_db:+.3f} | {resid:.3f} |")
        lines += [
            "",
            "  And the same deltas read at fixed frequencies (10 Hz, 100 Hz, 1 kHz,",
            "  10 kHz, 100 kHz, 1 MHz, 10 MHz), so a reader can see the shape rather",
            "  than only its extremum:",
            "",
            "| ratio | d|T| (dB) | dphase (deg) |",
            "|---|---|---|",
        ]
        for f in attribution["fits"]:
            dm = ", ".join(f"{d[1]:+.3f}" for d in f["deltas"])
            dp = ", ".join(f"{d[2]:+.3f}" for d in f["deltas"])
            lines.append(f"| `as-committed / {f['tag']}` | {dm} | {dp} |")

    ladders = [l for l in attribution.get("fb_cap", []) if l.get("rungs")]
    if ladders:
        lines += [
            "",
            "  **How much capacitance the feedback node actually tolerates.**",
            "  `design/ldo_softstart.sch`'s regression note states a hypothesis:",
            "  *\"ANY nonzero parasitic capacitance the real transconductor adds",
            "  to FB ... is enough to destabilize the main loop's hold-release",
            "  transient\"*. The `acopen-fb-inj` case above measures the loop's",
            "  sensitivity to the device injection element's FB coupling. Adding known",
            "  capacitance to `FB` until the margins move says what any future",
            "  injection element has to stay under, and is what tests the",
            "  hypothesis as stated. Every rung is a capacitor, so every rung is",
            "  an open at DC and the landed `VOUT` column is there to show the",
            "  bias point did not move.",
            "",
            "  The budget is stated against **the same point with no added",
            f"  capacitance**, not against DR-0001's {PM_MIN_DEG:g} deg /",
            f"  {GM_MIN_DB:g} dB reference lines. A mid-ramp state is not a",
            "  DR-0001 operating point, so those bars are reference lines here",
            "  and not a criterion"
            + ("; and the worst-point ladder below starts from a baseline of "
               f"{pm_str(ladders[0]['base'])} deg with no added capacitance at "
               f"all -- already under the {PM_MIN_DEG:g} deg line. Against an "
               f"absolute bar every rung there would \"fail\" and the ladder "
               f"would say nothing about capacitance"
               if (ladders[0]["base"].pm_deg is not None
                   and ladders[0]["base"].pm_deg < PM_MIN_DEG) else "")
            + ". Against its own baseline it answers the",
            f"  question that was asked. Tolerance: PM within "
            f"{FB_CAP_PM_TOL_DEG:g} deg and GM within {FB_CAP_GM_TOL_DB:g} dB",
            "  of the baseline -- the #182/#185 movement class. Both, because",
            "  they fail in different places.",
        ]
        for lad in ladders:
            p, b = lad["point"], lad["base"]
            lines += [
                "",
                f"  *{lad['label']}* -- `{p.corner_id}` at {p.state_id}, "
                f"{p.cfg_id}:",
                "",
                "| C(FB -> VSS) | PM (deg) | dPM vs baseline | GM (dB) | dGM vs baseline | f0 (Hz) | landed VOUT (V) |",
                "|---|---|---|---|---|---|---|",
                f"| *none (baseline)* | {pm_str(b)} | - | {gm_str(b)} | - | "
                f"{_hz(b.f0_hz)} | {b.vout_v:.5f} |",
            ]
            for rung in lad["rungs"]:
                r = rung.get("row")
                if r is None:
                    lines.append(f"| {rung['c_f'] * 1e12:g} pF | *failed: "
                                 f"{rung.get('error', 'unknown')}* | | | | | |")
                    continue
                dpm = ("-" if r.pm_deg is None or b.pm_deg is None
                       else f"{r.pm_deg - b.pm_deg:+.3f}")
                dgm = ("-" if math.isinf(r.gm_db) or math.isinf(b.gm_db)
                       else f"{r.gm_db - b.gm_db:+.3f}")
                lines.append(
                    f"| {rung['c_f'] * 1e12:g} pF | {pm_str(r)} | {dpm} | "
                    f"{gm_str(r)} | {dgm} | {_hz(r.f0_hz)} | {r.vout_v:.5f} |")
            bud = lad["budget"]
            lines.append("")
            if bud["ok_f"] is not None and bud["bad_f"] is not None:
                lines.append(
                    f"  This node carries **{bud['ok_f'] * 1e12:g} pF** with "
                    f"both margins still inside the tolerance, and leaves it "
                    f"at {bud['bad_f'] * 1e12:g} pF ({bud['bad_why']}).")
            elif bud["ok_f"] is not None:
                lines.append(
                    f"  Every rung, up to **{bud['ok_f'] * 1e12:g} pF**, "
                    f"leaves both margins inside the tolerance -- so this "
                    f"ladder bounds the budget from below only: it is at "
                    f"least its top rung.")
            else:
                lines.append(
                    f"  Even the bottom rung "
                    f"({lad['rungs'][0]['c_f'] * 1e12:g} pF) moves a margin "
                    f"outside the tolerance ({bud['bad_why']}), so the budget "
                    f"is below the ladder and the ladder needs extending "
                    f"downwards before it can state one.")
        budgets = [l["budget"]["ok_f"] for l in ladders
                   if l["budget"]["ok_f"] is not None]
        if budgets:
            tight = min(budgets)
            lines += [
                "",
                f"  Taking the tighter of the two, the feedback node tolerates "
                f"at least **{tight * 1e12:g} pF** before either margin moves "
                f"by the #182/#185 movement class. `design/ldo_softstart.sch`'s "
                f"own estimate of what the device-level chain adds to `FB` is "
                f"\"tens of femtofarads\" -- call it 30 fF -- which is a factor "
                f"of **{tight / 30e-15:.0f}** below that budget, and `Cff`'s "
                f"15 pF already sits across `Rtop` on the same node for scale.",
            ]
    return "\n".join(lines) + "\n"


def render_record(*, record_id, rows, grid, ceffs, esrs, pdk, prov, args,
                  xcheck, attribution, seeded, voided=(), curves=(),
                  hov_consistency=None, klt_info=None) -> str:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dirty = prov["dirty"]
    variants = sorted({r.variant for r in rows})
    procs = ", ".join(sorted({r.corner for r in rows}))
    temps = ", ".join(f"{t:g}" for t in sorted({r.temp_c for r in rows}))
    supplies = ", ".join(f"{v:.2f}" for v in sorted({r.vin_v for r in rows}))
    if klt_info:
        klt_md = (
            f"- Backend: `klt sim` (`--backend {klt_info['backend']}`), "
            f"{klt_info['requests']} margin requests (one per variant/phase/"
            f"C_eff/ESR, the ramp state a `corners.params` row) over the PVT "
            f"grid plus one `op` request per variant for the hand-over "
            f"transfer, client `{klt_info['klt']}` (`klt_run.py`, issue "
            f"#451). The per-corner logs are `ROW`/`HOV` lines of values "
            f"`klt` returned (each request's report JSON is under "
            f"`corners/{record_id}/klt-reports/`), so the ngspice version/hash "
            f"and host above describe only the local attribution and curve "
            f"re-runs, not the grid; the grid ran on the engine and host "
            f"named in those reports. Crossings are `klt`'s log-frequency "
            f"interpolation, not the deck's `meas ... when`.\n")
    else:
        klt_md = ""

    env = harness_environment(
        pdk=pdk,
        ngspice=ngspice_version(),
        repo_root=REPO_ROOT,
        git=prov,
        ngspice_sha256=ngspice_binary_sha256(),
    )
    env_extra = [klt_md.rstrip("\n")] if klt_md else []
    env_md = "\n".join(
        environment_lines(
            env,
            command="./sim/soft-start-loop-gain/testbench/run.sh",
            extra=env_extra,
        )
    )

    st_tbl = state_table(rows)
    ab_tbl, pairs = ab_table(rows)
    ho_tbl = handover_table(rows, "tt_27c_3.30v")

    measured = [r for r in rows if r.pm_deg is not None]
    no_cross = [r for r in rows if r.pm_deg is None]
    worst_all = worst_of(measured) if measured else None
    resurging = [r for r in rows if r.resurges]
    worst_res = worst_resurgence_of(rows)

    # Why the no-crossover points have no crossover: computed, not asserted.
    # If the loop's DC gain is below 0 dB the magnitude never reaches unity
    # and there is nothing for a margin to be read at -- which is a property
    # of the ramp state (the pass device is not conducting yet), not a
    # measurement failure. Anything else in that set would be a different
    # phenomenon and has to be named rather than swept into the same sentence.
    if no_cross:
        nc_gains = [r.dcgain_db for r in no_cross if math.isfinite(r.dcgain_db)]
        nc_states = sorted({(r.variant, r.phase, r.ssr_cmd) for r in no_cross})
        nc_positive = [r for r in no_cross
                       if math.isfinite(r.dcgain_db) and r.dcgain_db > 0.0]
        no_cross_reading = (
            f" Their DC loop gain runs "
            f"{min(nc_gains):.1f} dB to {max(nc_gains):.1f} dB, i.e. "
            + ("**every one of them is below unity at DC**, so the magnitude "
               "never reaches 0 dB and there is nothing for a margin to be read "
               "at. All of them are at "
               if not nc_positive else
               f"**{len(nc_positive)} of them are above unity at DC and still "
               f"never cross**, which is not the ramp-state explanation and is "
               f"flagged here rather than folded in. The set spans ")
            + ", ".join(f"`{v}/{p}/ssr={s}`" for v, p, s in nc_states[:6])
            + (", ..." if len(nc_states) > 6 else "")
            + " -- ramp states where the pass device is not yet conducting."
            " The `dc_loop_gain_db` column of the CSV carries the number for"
            " every point.")
    else:
        no_cross_reading = ""

    # Compare only matched points with a measured phase margin on both sides.
    measured_pairs = [p for p in pairs if p[2] is not None]
    if measured_pairs:
        dpms = [p[2] for p in measured_pairs]
        device, binj, _, _ = min(measured_pairs, key=lambda p: p[2])
        span = max(map(abs, dpms))
        relation = "within" if span <= XCHECK_PM_TOL_DEG else "above"
        headline = (
            "The largest absolute phase-margin difference between `device` and `binj` "
            f"is **{span:.2f} deg** across {len(dpms)} paired points, {relation} the "
            f"{XCHECK_PM_TOL_DEG:g} deg cross-invocation tolerance from #182/#185. "
            "The A/B cannot isolate the contribution of the injection element or capacitor sizing."
        )
        ab_reading = (
            f"Across the {len(dpms)} matched points with a 0 dB crossing in both variants, "
            "the phase-margin difference (`device` minus `binj`) ranges from "
            f"**{min(dpms):+.2f} deg to {max(dpms):+.2f} deg** (mean "
            f"{sum(dpms) / len(dpms):+.2f} deg). The lowest signed difference occurs at "
            f"`{device.corner_id}` ({device.state_id}, {device.cfg_id}). The margins there are "
            f"{pm_str(device)} deg with `device` and {pm_str(binj)} deg with `binj`."
        )
    else:
        headline = ("No state measured here has a 0 dB crossing on both sides "
                    "of the A/B, so this record makes no phase-margin "
                    "comparison between `device` and `binj`.")
        ab_reading = "No point has a 0 dB crossing on both sides, so no A/B delta is computed."

    # The DC hand-over reading, also computed.
    dc_lines = []
    for variant in variants:
        sel = sorted(
            (r for r in rows
             if r.variant == variant and r.phase == "ramp"
             and r.corner_id == "tt_27c_3.30v" and abs(r.esr_ohm - 0.1) < 1e-12
             and abs(r.ceff_f - 1e-6) < 1e-15),
            key=lambda r: float(r.ssr_cmd))
        if len(sel) < 2:
            continue
        lo, mid = sel[0], sel[1]
        slope = ((mid.iinj_a - lo.iinj_a) / (mid.ssr_v - lo.ssr_v)
                 if mid.ssr_v != lo.ssr_v else float("nan"))
        # Only below VREF: the intended output is 1.5*V(SSR) while the element
        # is still injecting, and the regulation target once it has rectified
        # off. Comparing a post-hand-over point against 1.5*V(SSR) would score
        # the ideal element as being 75 mV "off" for doing exactly its job.
        below = [r for r in sel if r.ssr_v <= VREF_V] or sel
        worst_track = max(below, key=lambda r: abs(r.vout_v - 1.5 * r.ssr_v))
        dc_lines.append(
            f"  - `{variant}`: I_inj = {lo.iinj_a * 1e6:+.4f} uA at "
            f"V(SSR) = {lo.ssr_cmd} V, falling at "
            f"**{abs(slope) * 1e6:.3f} uA/V** through the linear part of the "
            f"ramp (V(SSR) = {lo.ssr_cmd} -> {mid.ssr_cmd} V), and still "
            f"**{sel[-1].iinj_a * 1e6:+.4f} uA** at V(SSR) = "
            f"{sel[-1].ssr_cmd} V. Worst departure of VOUT from the intended "
            f"1.5*V(SSR) ramp over these states: "
            f"**{(worst_track.vout_v - 1.5 * worst_track.ssr_v) * 1e3:+.1f} mV** "
            f"at V(SSR) = {worst_track.ssr_cmd} V"
        )

    # What the injection element leaves behind once the ramp is over, per
    # variant, over every anchor-phase point. Computed, not asserted.
    settled_lines = []
    for variant in variants:
        sel = [r for r in rows if r.phase == "anchor" and r.variant == variant]
        if not sel:
            continue
        wi = max(sel, key=lambda r: abs(r.iinj_a))
        wv = max(sel, key=lambda r: abs(r.vout_v - VOUT_NOM_V))
        settled_lines.append(
            f"  - `{variant}`: largest residual injection current "
            f"**{wi.iinj_a * 1e9:+.4g} nA** at `{wi.corner_id}` "
            f"(V(SSR) settles at {wi.ssr_v:.4f} V there); largest settled "
            f"output error **{(wv.vout_v - VOUT_NOM_V) * 1e3:+.2f} mV** "
            f"({100 * (wv.vout_v - VOUT_NOM_V) / VOUT_NOM_V:+.3f}% of "
            f"{VOUT_NOM_V:g} V) at `{wv.corner_id}`")

    seeded_md = ""
    if seeded:
        seeded_md = (
            f"\n  - **Intended-branch DC seed used at {len(seeded)} "
            f"(PVT, variant, phase) deck(s)**: "
            + ", ".join(f"`{s}`" for s in sorted(seeded))
            + ". Those decks first failed the landing check and were re-run once\n"
            "    with `.nodeset` cards that start Newton with the feedback node\n"
            "    at the reference and `ldo_ilimit`'s clamp gate off (see\n"
            "    `dc_seed_lines()`). The seed selects which of the circuit's DC\n"
            "    solutions Newton converges to and is released after the first\n"
            "    solve pass; the retry is held to exactly the same landing check\n"
            "    as the first attempt, and its raw log is `*_dcseed.log`.\n"
        )
    voided_md = ""
    if voided:
        voided_md = (
            f"\n  - **{len(voided)} (PVT, variant, phase) deck(s) voided -- "
            f"no DC branch near VREF even with the intended-branch seed**: "
            "each of these is a deck whose Newton solve, even started from a "
            "`.nodeset` that seeds the feedback node at `VREF` and releases "
            "`ldo_ilimit`'s clamp, still converges somewhere with `FB` far "
            "from `VREF` (or `VOUT` outside the ramp's own range). That is "
            "not a testbench defect: it means the named PVT point has no DC "
            "solution close to the intended soft-start branch for that "
            "variant, which is itself evidence about the injection element's "
            "DC behaviour at that corner. No row for a voided deck enters "
            "this record or the matrix CSV.\n"
            + "\n".join(f"    - `{v}`" for v in sorted(voided))
            + "\n"
        )
    subset_md = (f"\n  - **Subset reason**: {args.subset_reason.strip()}\n"
                 if args.subset_reason.strip() else "")

    ssr_md = []
    for phase, spec in PHASES.items():
        if phase not in args.phases:
            continue
        if spec["ssr"] is None:
            ssr_md.append(f"  - **`{phase}`** -- {spec['why']}. SSR is not "
                          f"pinned in this phase.")
        else:
            pts = "; ".join(
                f"`V(SSR) = {v:g} V` {SSR_POINT_LABEL.get(v, '')}".strip()
                for v in spec["ssr"])
            ssr_md.append(f"  - **`{phase}`** -- {spec['why']}. States: {pts}.")

    return f"""# Record {record_id}

- **Record ID**: {record_id}
- **Claim**: issue #196 -- the small-signal loop-gain / phase-margin
  characterization of the LDO main loop **with `design/ldo_softstart.sch`'s
  FB-injection element in the loop**, at pinned points of the soft-start ramp
  for the DUT variants listed below. This record substantiates **no ratified
  spec row**. It is
  the AC evidence `design/ldo_softstart.sch`'s own "WHAT THIS COSTS THE MAIN
  LOOP" note points at and that did not exist, and it is the measured input to
  `design/softstart_injection_compensation.md` and to whatever decision
  resolves #191. DR-0001's 45 deg / 10 dB bars appear throughout as the
  **reference lines** they are for the settled state; they are not a ratified
  criterion for a mid-ramp state, and no point of this record is reported as a
  DR-0001 verdict. The DR-0001 verdict for this design remains
  `sim/loop-stability/`'s and is unchanged by this record.
- **Netlist provenance**: schematic
  (`design/ldo_core.sch` -> `design/netlist/ldo_core.spice`, with
  `design/ldo_softstart.sch` -> `design/netlist/ldo_softstart.spice` inside
  it){' -- **DIRTY WORKING TREE at run time; not citable as a clean-tree result**' if dirty else ''}.
{chr(10).join(f'  - `{v}`: {nv.VARIANT_BLURB[v]}' for v in variants)}

  Each variant exposes the ramp node `SSR` through the `ldo_softstart` and
  `ldo_core` port lists and the `Xsoftstart` instance line. `SSR` is already a
  node of the cell, so promoting it to a port renames nothing and connects
  nothing; the `anchor` phase leaves the new port unconnected so that the
  cross-check below can test whether that is so. Nothing under `design/` is
  modified by this experiment. The netlist snapshots are linked below.
  The idealizations in the loop are the ones every other record here names:
  the deck's ideal 1.2 V `VREF` source (#174 / DR-0021) and `Fbias` inside
  `ldo_ilimit`.
- **Corner matrix run**:
  - Process: {procs}
  - Temperature: {temps} degC
  - Supply: {supplies} V
  - {len(grid)} PVT points x {len(variants)} DUT variant(s) x the ramp states
    below x {len(ceffs)} C_eff x {len(esrs)} ESR = **{len(rows)} loop-gain
    points**{f", plus {len(voided)} voided (PVT, variant, phase) deck(s) -- "
              f"see below" if voided else ""}.{subset_md}{seeded_md}{voided_md}
- **Operating conditions**:
  - Load: the rated 50 mA point, in two load models -- a 36 ohm resistor
    (1.8 V / 50 mA, the model `sim/soft-start/` uses, and the only one that
    has a regulating solution low on the ramp) and an ideal 50 mA DC current
    sink (the model every `sim/loop-stability/` record uses; infinite
    small-signal impedance, the conservative choice). Which one a point used
    is in its `load_model` column.
  - Output cap: C_eff in {{{', '.join(fmt_uf(c) for c in ceffs)}}} with ESR in
    {{{', '.join(f'{e:g}' for e in esrs)}}} ohm, in series, at the output pin.
    DERATED EFFECTIVE values per DR-0001. 1 uF / 100 mOhm is
    `sim/soft-start/`'s main-matrix output network; 4.7 uF / 1 mOhm and
    4.7 uF / 500 mOhm are its two 4.7 uF groups.
  - Enable state: enabled (EN = VIN), and therefore `HG` released --
    `Mhold_ss`/`Mhold_bg_ss` are in cutoff, so the pass gate belongs to the
    main loop. That is the hand-over state the #191 regression names. It is
    also what the real ramp does: `Rh_ss`/`Ch_ss` release `HG` with a time
    constant two orders of magnitude shorter than the ramp itself.
  - Ramp states (`V(SSR)` pinned by an ideal deck-level source through the
    promoted port, except in `anchor`):
{chr(10).join(ssr_md)}
  - Loop break: `ERRAMP_OUT` -> `PASS_GATE`, Tian/Middlebrook dual injection,
    exactly as `sim/loop-stability/testbench/tb_loop_stability.spice.in` does
    it -- so the reported loop gain is exact regardless of the source/load
    impedance ratio at the break and the DC operating point is the true
    closed-loop one.
- **Statistical convention**: N/A (corner-matrix measurement, not a
  distribution claim -- no Monte Carlo).

- **Result**:

  {headline}

  **1. What the DC hand-over actually does** (the operating point every margin
  below is a statement about). Measured at `tt_27c_3.30v`, 1 uF / 100 mOhm,
  resistive load; the full matrix is in the CSV:

{chr(10).join('  ' + l for l in ho_tbl)}

{chr(10).join(dc_lines)}

  **1a. The same hand-over, swept densely, over the whole PVT grid.** Four
  pinned ramp states are enough to ask whether there is a phase-margin
  problem. They are not enough to say what the injection element's transfer
  *is*, which is the question a compensation recommendation has to be built
  on, so the transfer is measured directly:

{handover_section(list(curves), hov_consistency)}
  **1b. What each element leaves behind once the ramp is over** (the `anchor`
  phase: SSR wherever `Mtop_ss`'s ceiling clamp puts it, 50 mA, over every PVT
  corner). An injection element that does not rectify fully off is a standing
  DC error at the output, because the current it still pushes into FB is
  indistinguishable, to the loop, from feedback current:

{chr(10).join(settled_lines)}

  **2. Worst-case margin per ramp state and DUT variant**, minimised over the
  whole {len(grid)}-point PVT grid and both output-network axes:

{chr(10).join('  ' + l for l in st_tbl)}

  {'' if worst_all is None else f'Worst measured point anywhere in this record: `{worst_all.corner_id}` at {worst_all.state_id}, {worst_all.cfg_id} -- PM {pm_str(worst_all)} deg, GM {gm_str(worst_all)} dB, crossover {_hz(worst_all.f0_hz)} Hz.'}
  {len(no_cross)}/{len(rows)} points have no 0 dB crossing in
  0.01 Hz - 1 GHz at all.{no_cross_reading}

  **3. Paired margin differences between DUT variants.**

  {ab_reading}

{chr(10).join('  ' + l for l in ab_tbl)}

  **4. DR-0008's precondition check (gain resurgence above the first 0 dB
  crossing, issue #59)** -- reported separately from the margins above, and
  never folded into them, exactly as `sim/loop-stability/` reports it.
  {'**' + str(len(resurging)) + '/' + str(len(rows)) + ' points** have |T| back above ' + f'{RESURGENCE_MAX_DB:g}' + ' dB somewhere above their first 0 dB crossing, worst ' + res_str(worst_res) + ' dB at `' + worst_res.corner_id + '` / ' + worst_res.state_id + ' / ' + worst_res.cfg_id + '. Where that happens the phase margin tabulated above is read at a crossing that is not the last one.' if resurging else 'No point in this record has |T| above ' + f'{RESURGENCE_MAX_DB:g}' + ' dB anywhere above its first 0 dB crossing (worst ' + res_str(worst_res) + ' dB, at `' + worst_res.corner_id + '` / ' + worst_res.state_id + ' / ' + worst_res.cfg_id + '), i.e. every point that crosses unity crosses it once and stays below. That removes the *necessary* condition for the DR-0008 misreading; it does not by itself prove the loop gain has no right-half-plane poles, and it does not replace `sim/amp-selfosc/`.'}

  **5. Cross-check against `sim/loop-stability/` (issue #196 AC2).** The
  `anchor` phase is this experiment's deck with `SSR` left unpinned and the
  ideal 50 mA sink -- i.e. `sim/loop-stability/`'s own measurement, reached
  through an SSR port that is connected to nothing. If the port promotion or
  anything else about this deck perturbed the circuit, this is where it would
  show.

{xcheck_section(xcheck)}
  **6. Pole/zero attribution at the worst corner (issue #196 AC3).**

{attribution_section(attribution)}

- **What this record does NOT claim**:
  - It is not a DR-0001 verdict. DR-0001's matrix is the settled operating
    point across load, C_eff and ESR; a pinned mid-ramp state is not in it,
    and this record does not move, relax or restate any DR-0001 result.
    `sim/loop-stability/` remains the phase-margin record for this design.
  - It is not a large-signal statement. #191's 166.7 mA inrush is a transient
    measurement (`sim/soft-start/records/20260906-230703-d3cb117.md`); nothing
    here re-runs it, and a small-signal margin cannot confirm or refute it.
    What this record can do is say whether a *margin* explanation is available,
    and the numbers above are what that question has to be answered with.
  - It measures the ramp states it pins, not the trajectory between them. A
    pinned `SSR` removes the ramp's own dynamics (`Css` charging at a few nA)
    from the problem by construction; that is what makes a frequency-domain
    answer well-posed at all, and it is why the anchor cross-check above
    exists to bound what the pinning itself costs.
  - It says nothing about `sim/loop-stability/`'s open 1-50 mA phase-margin
    gap (#51, operator-held) or the 4.7 uF inrush/current-limit clearance gap
    (#187, operator-held).

- **Links**:
  - Testbench: `sim/soft-start-loop-gain/testbench/tb_ss_loop_gain.spice.in`
    (margins), `sim/soft-start-loop-gain/testbench/tb_ss_handover.spice.in`
    (the DC transfer),
    `sim/soft-start-loop-gain/testbench/sweep.py`,
    `sim/soft-start-loop-gain/testbench/netlist_variants.py`,
    `sim/soft-start-loop-gain/testbench/run.sh`
  - Testbench self-test: `sim/soft-start-loop-gain/testbench/selftest.py`
    (delegates the loop-gain extraction's known-answer checks to
    `sim/loop-stability/testbench/selftest.py` and this experiment's own
    simulator-free checks to `sim/tests/test_soft_start_loop_gain.py`, the
    same module CI runs via `sim/selftest.sh`)
  - Frozen DUT netlists (one per variant):
{chr(10).join(f'    `sim/soft-start-loop-gain/netlist-snapshots/{record_id}-{v}.spice`' for v in variants)}
  - Raw logs (one per PVT point x variant x phase, plus the attribution and
    cross-check runs): `sim/soft-start-loop-gain/corners/{record_id}/`
  - Full {len(rows)}-point matrix, machine-readable:
    `sim/soft-start-loop-gain/records/{record_id}-matrix.csv`
{f'''  - Full {sum(len(c.points) for c in curves)}-point DC hand-over transfer,
    machine-readable:
    `sim/soft-start-loop-gain/records/{record_id}-handover.csv`''' if curves else '  - (no hand-over transfer in this run)'}
  - The experiment this one is built from, and the reference its anchor is
    compared with when the join has matches (see above):
    `sim/loop-stability/` (record `20260906-071437-fff0bf0`, and the
    toolchain-provenance investigation `{LS_DIAGNOSTIC_RECORD}`)
  - The large-signal record this one exists to explain:
    `sim/soft-start/records/20260906-230703-d3cb117.md` (device chain) and
    `sim/soft-start/records/20260906-202950-bfc4a0a.md` (ideal `Binj_ss`)
  - The recommendation this record feeds:
    `design/softstart_injection_compensation.md`
- **Timestamp / author**: {now}, {args.author}
- **Supersedes**: {args.supersedes or '(none -- first record for this experiment)'}

## Environment

Everything needed to re-run this record:

{env_md}
- ngspice startup settings, pinned by this driver rather than left to the host
  (a generated `.spiceinit` in the run's work directory, which is the cwd of
  every ngspice invocation this record made, including the cross-check's):
  `set wnflag=1` (model binning divides W by nf -- without it the pass
  device (`W=2800u nf=40`, i.e. 70 um per finger) has no model bin and no
  deck in this repo parses) and
  `set num_threads=1`. `wnflag` is also set as a `.options` card inside the
  deck itself.
- AC sweep: `dec {args.ac_dec} {F_START} {F_STOP}` per injection, two injections
  per point -- `sim/loop-stability/`'s resolution policy (issue #58), imported
  from its driver rather than restated here, so the two experiments cannot
  drift apart on it.

---

Written by `sim/soft-start-loop-gain/testbench/sweep.py`, in the
`sim/README.md` record format. Append-only: never edit or delete this file --
a re-run or correction mints a new record-id and points back here via
**Supersedes**.
"""
