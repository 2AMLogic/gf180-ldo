#!/usr/bin/env python3
"""Roll the raw ngspice sweep output under sim/devchar/*/results into summary
tables with the worst case flagged per parameter (issue #4).

This module derives nothing that was not measured: every number below is either
a value read from a raw CSV row or an arithmetic combination of such values
(ratio, difference, interpolation between two measured points). Rows that a
deck reported as infeasible are dropped, not extrapolated over.

    python3 sim/devchar/lib/summarize.py            # rebuild every summary table
"""

from __future__ import annotations

import csv
import math
import os
import statistics
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Rds targets that the dropout spec translates into at the two load points.
RDS_TARGETS = [
    ("6.0", 6.0, "300 mV @ 50 mA"),
    ("4.0", 4.0, "200 mV @ 50 mA"),
    ("3.0", 3.0, "300 mV @ 100 mA"),
]
LV_SUPPLIES = {"2.97", "3.30", "3.63"}
# The dropout test point (Vin = Vout + dropout) is a separate supply class: it is
# the condition the dropout spec is actually defined at, and it gives the pass
# device markedly less Vsg than the 2.97 V supply floor does.
DROPOUT_SUPPLY = "2.10"


def read(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def write(path, fieldnames, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  wrote {os.path.relpath(path, ROOT)} ({len(rows)} rows)")


def fmt(x, sig=6):
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if x == 0:
        return "0"
    return f"{x:.{sig}g}"


def supply_class(vin):
    if vin == DROPOUT_SUPPLY:
        return "dropout_testpoint"
    return "lv" if vin in LV_SUPPLIES else "mv"


# --------------------------------------------------------------------------
# Pass FETs
# --------------------------------------------------------------------------

def summarize_pass_fet():
    src = os.path.join(ROOT, "fets", "results", "rdson_pmos.csv")
    rows = read(src)

    # ---- worst case per (device, L, W, metric, supply class) -------------
    groups = defaultdict(list)
    for r in rows:
        key = (r["device"], r["l_um"], float(r["w_mm"]), r["metric"],
               supply_class(r["vin_v"]))
        groups[key].append(r)

    out = []
    for key in sorted(groups, key=lambda k: (k[0], k[1], k[2], k[3], k[4])):
        dev, l, w, metric, cls = key
        rs = groups[key]
        feasible = [r for r in rs if float(r["vd_v"]) > 0.0]
        worst = max(feasible, key=lambda r: float(r["rds_ohm"])) if feasible else None
        best = min(feasible, key=lambda r: float(r["rds_ohm"])) if feasible else None
        out.append({
            "device": dev, "l_um": l, "w_mm": fmt(w), "metric": metric,
            "supply_class": cls,
            "n_cases": len(rs),
            "n_infeasible": len(rs) - len(feasible),
            "worst_rds_ohm": fmt(float(worst["rds_ohm"])) if worst else "",
            "worst_vsd_v": fmt(float(worst["vsd_v"])) if worst else "",
            "worst_corner": worst["corner"] if worst else "",
            "worst_temp_c": worst["temp_c"] if worst else "",
            "worst_vin_v": worst["vin_v"] if worst else "",
            "best_rds_ohm": fmt(float(best["rds_ohm"])) if best else "",
            "best_corner": best["corner"] if best else "",
            "best_temp_c": best["temp_c"] if best else "",
            "best_vin_v": best["vin_v"] if best else "",
        })
    write(os.path.join(ROOT, "fets", "results", "summary_pass_fet.csv"),
          list(out[0].keys()), out)

    # ---- required W for each Rds target, worst case over the matrix ------
    # For every individual (corner, temp, vin) case the measured R(W) curve is
    # interpolated in log-log to the target; the reported W is the largest such
    # requirement across the matrix, i.e. the size that holds at every corner.
    cases = defaultdict(dict)      # (dev,l,metric,cls,corner,temp,vin) -> {W: R}
    for r in rows:
        if float(r["vd_v"]) <= 0.0:
            continue
        key = (r["device"], r["l_um"], r["metric"], supply_class(r["vin_v"]),
               r["corner"], r["temp_c"], r["vin_v"])
        cases[key][float(r["w_mm"])] = float(r["rds_ohm"])

    req = defaultdict(list)        # (dev,l,metric,cls,target) -> [(W,case)]
    below = defaultdict(int)       # target already met by the narrowest device
    above = defaultdict(int)       # target NOT met even by the widest device
    for key, curve in cases.items():
        dev, l, metric, cls, corner, temp, vin = key
        pts = sorted(curve.items())
        rs = [r for _, r in pts]
        for name, target, _ in RDS_TARGETS:
            k = (dev, l, metric, cls, name)
            w = interp_w_for_r(pts, target)
            if w is not None:
                req[k].append((w, (corner, temp, vin)))
            elif target > max(rs):
                below[k] += 1      # required width is under the swept range
            else:
                above[k] += 1      # required width is over the swept range
                req[k]              # touch so the key exists

    out = []
    for key in sorted(set(req) | set(above)):
        dev, l, metric, cls, name = key
        note = dict((n, d) for n, _, d in RDS_TARGETS)[name]
        solved = req.get(key) or []
        if solved:
            wmax, case = max(solved)
            wmin, bcase = min(solved)
        else:
            wmax = wmin = None
            case = bcase = ("", "", "")
        out.append({
            "device": dev, "l_um": l, "metric": metric, "supply_class": cls,
            "rds_target_ohm": name, "target_meaning": note,
            "w_required_mm_worst_case": fmt(wmax),
            "worst_corner": case[0], "worst_temp_c": case[1], "worst_vin_v": case[2],
            "w_required_mm_best_case": fmt(wmin),
            "best_corner": bcase[0], "best_temp_c": bcase[1], "best_vin_v": bcase[2],
            "n_cases_solved": len(solved),
            "n_cases_below_swept_widths": below.get(key, 0),
            "n_cases_above_swept_widths": above.get(key, 0),
            # The worst case is only trustworthy when no case needed a device
            # wider than the sweep covered; otherwise the number is a lower bound.
            "worst_case_bounded": "yes" if not above.get(key, 0) else "NO - lower bound only",
        })
    write(os.path.join(ROOT, "fets", "results", "summary_sizing.csv"),
          list(out[0].keys()), out)


def interp_w_for_r(pts, target):
    """Width (mm) at which the measured R(W) curve crosses `target` ohms.

    `pts` is a sorted [(W, R)] list from one corner/temp/supply case. The
    interpolation is linear in log(W) vs log(R) - Rds(on) is very nearly 1/W, so
    that space is close to a straight line and the interpolation adds almost
    nothing on top of the measurement. Returns None when the target lies outside
    the simulated width range, so nothing is silently extrapolated.
    """
    ws = [w for w, _ in pts]
    rs = [r for _, r in pts]
    if not rs or target > max(rs) or target < min(rs):
        return None
    for i in range(len(pts) - 1):
        r0, r1 = rs[i], rs[i + 1]
        if (r0 - target) * (r1 - target) <= 0 and r0 != r1:
            lw0, lw1 = math.log(ws[i]), math.log(ws[i + 1])
            lr0, lr1 = math.log(r0), math.log(r1)
            frac = (math.log(target) - lr0) / (lr1 - lr0)
            return math.exp(lw0 + frac * (lw1 - lw0))
    return None


def summarize_nmos_headroom():
    src = os.path.join(ROOT, "fets", "results", "rdson_nmos.csv")
    rows = read(src)
    groups = defaultdict(list)
    for r in rows:
        key = (r["device"], r["l_um"], float(r["w_mm"]), r["metric"],
               supply_class(r["vin_v"]))
        groups[key].append(r)
    out = []
    for key in sorted(groups, key=lambda k: (k[0], k[1], k[2], k[3], k[4])):
        dev, l, w, metric, cls = key
        rs = groups[key]
        ids = [float(r["id_a"]) for r in rs]
        worst = min(rs, key=lambda r: float(r["id_a"]))
        best = max(rs, key=lambda r: float(r["id_a"]))
        out.append({
            "device": dev, "l_um": l, "w_mm": fmt(w), "metric": metric,
            "supply_class": cls, "vgs_v": rs[0]["vgs_v"],
            "worst_id_a": fmt(min(ids)),
            "worst_corner": worst["corner"], "worst_temp_c": worst["temp_c"],
            "worst_vin_v": worst["vin_v"],
            "best_id_a": fmt(max(ids)),
            "best_corner": best["corner"], "best_temp_c": best["temp_c"],
            "best_vin_v": best["vin_v"],
            "meets_50mA_at_all_corners": "yes" if min(ids) >= 0.05 else "no",
            "meets_100mA_at_all_corners": "yes" if min(ids) >= 0.10 else "no",
        })
    write(os.path.join(ROOT, "fets", "results", "summary_nmos_headroom.csv"),
          list(out[0].keys()), out)


def summarize_vth():
    """Threshold voltage across the corner/temperature matrix.

    The architecture survey (spec/architecture-survey.md section 3.4) proceeds on
    an assumed |Vtp| = Vtn = 0.7 V and explicitly flags it for confirmation here,
    so the delta against 0.7 V is carried as a column rather than left to the
    reader.
    """
    src = os.path.join(ROOT, "fets", "results", "vth.csv")
    rows = read(src)
    groups = defaultdict(list)
    for r in rows:
        groups[(r["device"], r["l_um"], r["vsb_v"])].append(r)
    out = []
    for key in sorted(groups):
        dev, l, vsb = key
        rs = groups[key]
        hi = max(rs, key=lambda r: float(r["vth_v"]))
        lo = min(rs, key=lambda r: float(r["vth_v"]))
        typ27 = [r for r in rs if r["corner"] == "typical" and r["temp_c"] == "27"][0]
        vtyp = float(typ27["vth_v"])
        out.append({
            "device": dev, "l_um": l, "vsb_v": vsb,
            "vth_typical_27c_v": fmt(vtyp),
            "vth_max_v": fmt(float(hi["vth_v"])),
            "vth_max_corner": hi["corner"], "vth_max_temp_c": hi["temp_c"],
            "vth_min_v": fmt(float(lo["vth_v"])),
            "vth_min_corner": lo["corner"], "vth_min_temp_c": lo["temp_c"],
            "pvt_spread_v": fmt(float(hi["vth_v"]) - float(lo["vth_v"])),
            "survey_assumed_v": "0.7",
            "delta_vs_survey_assumption_v": fmt(vtyp - 0.7),
        })
    write(os.path.join(ROOT, "fets", "results", "summary_vth.csv"),
          list(out[0].keys()), out)


def summarize_cgg():
    for kind in ("pmos", "nmos"):
        src = os.path.join(ROOT, "fets", "results", f"cgg_{kind}.csv")
        rows = read(src)
        groups = defaultdict(list)
        for r in rows:
            key = (r["device"], r["l_um"], float(r["w_mm"]),
                   supply_class(r["vin_v"]))
            groups[key].append(r)
        out = []
        for key in sorted(groups, key=lambda k: (k[0], k[1], k[2], k[3])):
            dev, l, w, cls = key
            rs = groups[key]
            worst = max(rs, key=lambda r: float(r["cgg_f"]))
            best = min(rs, key=lambda r: float(r["cgg_f"]))
            wcgd = max(rs, key=lambda r: float(r["cgd_f"]))
            out.append({
                "device": dev, "l_um": l, "w_mm": fmt(w), "supply_class": cls,
                "cgg_max_f": fmt(float(worst["cgg_f"])),
                "cgg_max_corner": worst["corner"], "cgg_max_temp_c": worst["temp_c"],
                "cgg_max_vin_v": worst["vin_v"],
                "cgg_min_f": fmt(float(best["cgg_f"])),
                "cgd_max_f": fmt(float(wcgd["cgd_f"])),
                "cgd_max_corner": wcgd["corner"],
                "cgg_per_mm_max_f": fmt(float(worst["cgg_per_mm_f"])),
            })
        write(os.path.join(ROOT, "fets", "results", f"summary_cgg_{kind}.csv"),
              list(out[0].keys()), out)


def summarize_leakage():
    for kind in ("pmos", "nmos"):
        src = os.path.join(ROOT, "fets", "results", f"leak_{kind}.csv")
        rows = read(src)
        groups = defaultdict(list)
        for r in rows:
            key = (r["device"], r["l_um"], float(r["w_mm"]), r["temp_c"],
                   supply_class(r["vin_v"]))
            groups[key].append(r)
        out = []
        for key in sorted(groups, key=lambda k: (k[0], k[1], k[2], float(k[3]), k[4])):
            dev, l, w, temp, cls = key
            rs = groups[key]
            worst = max(rs, key=lambda r: float(r["ioff_a"]))
            out.append({
                "device": dev, "l_um": l, "w_mm": fmt(w), "temp_c": temp,
                "supply_class": cls,
                "ioff_max_a": fmt(float(worst["ioff_a"])),
                "worst_corner": worst["corner"], "worst_vin_v": worst["vin_v"],
                "ioff_max_ua": fmt(float(worst["ioff_a"]) * 1e6),
                "frac_of_30ua_iq_budget": fmt(float(worst["ioff_a"]) / 30e-6),
                "frac_of_10ua_iq_stretch": fmt(float(worst["ioff_a"]) / 10e-6),
            })
        write(os.path.join(ROOT, "fets", "results", f"summary_leak_{kind}.csv"),
              list(out[0].keys()), out)


# --------------------------------------------------------------------------
# Resistors
# --------------------------------------------------------------------------

def summarize_resistors():
    src = os.path.join(ROOT, "resistors", "results", "rsheet.csv")
    rows = read(src)
    # index by (device, corner, temp) -> {(w,l,i): R}
    idx = defaultdict(dict)
    nominal = {}
    for r in rows:
        key = (r["device"], r["res_corner"], r["temp_c"])
        idx[key][(r["w_um"], r["l_um"], r["i_test"])] = float(r["r_ohm"])
        nominal[r["device"]] = r["rsh_nominal_ohm_sq"]

    out = []
    for key in sorted(idx, key=lambda k: (k[0], k[1], float(k[2]))):
        dev, corner, temp = key
        g = idx[key]
        r10 = g[("1", "10", "1u")]
        r50 = g[("1", "50", "1u")]
        # two-length extraction: 40 squares of a 1 um wide strip separate them,
        # so the head/terminal resistance cancels out of the difference.
        rsh = (r50 - r10) / 40.0
        r_vcr = g[("1", "50", "50u")]
        out.append({
            "device": dev, "res_corner": corner, "temp_c": temp,
            "rsh_extracted_ohm_sq": fmt(rsh),
            "rsh_model_card_ohm_sq": nominal[dev],
            "rsh_ratio_extracted_over_card": fmt(rsh / float(nominal[dev])),
            "r_w1_l10_ohm": fmt(r10),
            "r_w1_l50_ohm": fmt(r50),
            "r_w2_l20_ohm": fmt(g[("2", "20", "1u")]),
            "r_w5_l50_ohm": fmt(g[("5", "50", "1u")]),
            "area_per_kohm_um2": fmt(1000.0 * (1 * 50) / r50),
            "r_w1_l50_at_50ua_ohm": fmt(r_vcr),
            # bias dependence: same device, 1 uA vs 50 uA test current
            "dr_over_r_1ua_to_50ua_ppm": fmt(1e6 * (r_vcr - r50) / r50),
        })
    write(os.path.join(ROOT, "resistors", "results", "summary_rsheet.csv"),
          list(out[0].keys()), out)

    # ---- temperature coefficient, per device per corner ------------------
    tcs = []
    devs = sorted({r["device"] for r in rows})
    corners = sorted({r["res_corner"] for r in rows})
    for dev in devs:
        for corner in corners:
            def rat(t):
                return idx[(dev, corner, t)][("1", "50", "1u")]
            r_cold, r_room, r_hot = rat("-40"), rat("27"), rat("125")
            tcs.append({
                "device": dev, "res_corner": corner,
                "r_m40c_ohm": fmt(r_cold),
                "r_27c_ohm": fmt(r_room),
                "r_125c_ohm": fmt(r_hot),
                "tc_27_to_125_ppm_per_c": fmt(1e6 * (r_hot - r_room) / r_room / 98.0),
                "tc_m40_to_27_ppm_per_c": fmt(1e6 * (r_room - r_cold) / r_room / 67.0),
                "total_spread_m40_to_125_pct": fmt(
                    100.0 * (max(r_cold, r_room, r_hot) - min(r_cold, r_room, r_hot))
                    / r_room),
            })
    write(os.path.join(ROOT, "resistors", "results", "summary_tempco.csv"),
          list(tcs[0].keys()), tcs)

    # ---- corner spread of the extracted sheet ----------------------------
    spread = []
    for dev in devs:
        for temp in ("-40", "27", "125"):
            vals = {}
            for corner in corners:
                g = idx[(dev, corner, temp)]
                vals[corner] = (g[("1", "50", "1u")] - g[("1", "10", "1u")]) / 40.0
            typ = vals["res_typical"]
            spread.append({
                "device": dev, "temp_c": temp,
                "rsh_res_typical": fmt(typ),
                "rsh_res_ff": fmt(vals["res_ff"]),
                "rsh_res_ss": fmt(vals["res_ss"]),
                "corner_spread_pct_of_typical": fmt(
                    100.0 * (vals["res_ss"] - vals["res_ff"]) / typ),
                "worst_high_corner": "res_ss", "worst_low_corner": "res_ff",
            })
    write(os.path.join(ROOT, "resistors", "results", "summary_corner_spread.csv"),
          list(spread[0].keys()), spread)


def summarize_matching():
    src = os.path.join(ROOT, "resistors", "results", "mismatch_mc_raw.csv")
    rows = read(src)
    groups = defaultdict(list)
    for r in rows:
        key = (r["mode"], r["temp_c"], r["device"], float(r["area_um2"]),
               r["quantity"], r["w_um"], r["l_um"])
        groups[key].append((float(r["val_a"]), float(r["val_b"])))

    out = []
    for key in sorted(groups, key=lambda k: (k[0], float(k[1]), k[2], k[3], k[4])):
        mode, temp, dev, area, qty, w, l = key
        pairs = groups[key]
        a = [p[0] for p in pairs]
        b = [p[1] for p in pairs]
        both = a + b
        mean = statistics.fmean(both)
        deltas = [x - y for x, y in pairs]
        sd_delta = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
        sd_abs = statistics.pstdev(both) if len(both) > 1 else 0.0
        row = {
            "mode": mode, "temp_c": temp, "device": dev,
            "w_um": w, "l_um": l, "area_um2": fmt(area), "quantity": qty,
            "n_runs": len(pairs),
            "mean": fmt(mean),
            "sigma_absolute": fmt(sd_abs),
            "sigma_absolute_pct_of_mean": fmt(100.0 * sd_abs / mean) if mean else "",
            "sigma_delta_pair": fmt(sd_delta),
            "sigma_delta_pair_pct_of_mean": fmt(100.0 * sd_delta / mean) if mean else "",
            # single-device matching sigma = pair sigma / sqrt(2)
            "sigma_single_device": fmt(sd_delta / math.sqrt(2.0)),
            # Pelgrom-style area coefficient: sigma(delta) * sqrt(WL)
            "pelgrom_coeff_delta_sqrt_area": fmt(sd_delta * math.sqrt(area)),
        }
        out.append(row)
    write(os.path.join(ROOT, "resistors", "results", "summary_matching.csv"),
          list(out[0].keys()), out)


# --------------------------------------------------------------------------
# Capacitors
# --------------------------------------------------------------------------

def summarize_mim():
    src = os.path.join(ROOT, "caps", "results", "mim.csv")
    rows = read(src)
    idx = defaultdict(dict)     # (dev,corner,temp) -> {(w,vbias): (C, density)}
    for r in rows:
        idx[(r["device"], r["mim_corner"], r["temp_c"])][
            (r["w_um"], r["vbias_v"])] = (float(r["c_f"]),
                                          float(r["c_density_ff_per_um2"]))

    out = []
    for key in sorted(idx, key=lambda k: (k[0], k[1], float(k[2]))):
        dev, corner, temp = key
        g = idx[key]
        widths = sorted({k[0] for k in g}, key=float)
        biases = sorted({k[1] for k in g}, key=float)
        w0 = widths[0]
        c_at = {vb: g[(w0, vb)][0] for vb in biases}
        c0 = c_at["0"]
        cmax = max(c_at.values())
        cmin = min(c_at.values())
        row = {
            "device": dev, "mim_corner": corner, "temp_c": temp,
            "size_um": w0,
            "c_at_0v_f": fmt(c0),
            "density_at_0v_ff_per_um2": fmt(g[(w0, "0")][1]),
            "c_spread_over_bias_ppm": fmt(1e6 * (cmax - cmin) / c0),
            "voltage_coeff_0_to_3v3_ppm_per_v": fmt(
                1e6 * (c_at["3.30"] - c0) / c0 / 3.3),
        }
        if len(widths) > 1:
            w1 = widths[1]
            # C = c_cox*area + c_capsw*perimeter, solved from the two sizes
            a0, p0 = float(w0) ** 2, 4 * float(w0)
            a1, p1 = float(w1) ** 2, 4 * float(w1)
            ca, cb = g[(w0, "0")][0], g[(w1, "0")][0]
            det = a0 * p1 - a1 * p0
            cox = (ca * p1 - cb * p0) / det
            capsw = (a0 * cb - a1 * ca) / det
            row["area_density_ff_per_um2"] = fmt(cox * 1e15)
            row["perimeter_density_ff_per_um"] = fmt(capsw * 1e15)
            row["density_at_0v_large_ff_per_um2"] = fmt(g[(w1, "0")][1])
        else:
            row["area_density_ff_per_um2"] = ""
            row["perimeter_density_ff_per_um"] = ""
            row["density_at_0v_large_ff_per_um2"] = ""
        out.append(row)
    write(os.path.join(ROOT, "caps", "results", "summary_mim.csv"),
          list(out[0].keys()), out)

    # ---- temperature and corner rollup, worst case flagged ---------------
    roll = defaultdict(dict)
    for r in out:
        roll[(r["device"], r["size_um"])][(r["mim_corner"], r["temp_c"])] = r
    tab = []
    for key in sorted(roll):
        dev, size = key
        g = roll[key]
        c_by = {k: float(v["c_at_0v_f"]) for k, v in g.items()}
        hi = max(c_by, key=c_by.get)
        lo = min(c_by, key=c_by.get)
        nom = c_by[("mimcap_typical", "27")]
        t27 = c_by[("mimcap_typical", "27")]
        t125 = c_by[("mimcap_typical", "125")]
        tm40 = c_by[("mimcap_typical", "-40")]
        tab.append({
            "device": dev, "size_um": size,
            "c_typical_27c_f": fmt(nom),
            "c_max_f": fmt(c_by[hi]), "c_max_corner": hi[0], "c_max_temp_c": hi[1],
            "c_min_f": fmt(c_by[lo]), "c_min_corner": lo[0], "c_min_temp_c": lo[1],
            "pvt_spread_pct_of_typical": fmt(100.0 * (c_by[hi] - c_by[lo]) / nom),
            "tc_27_to_125_ppm_per_c": fmt(1e6 * (t125 - t27) / t27 / 98.0),
            "tc_m40_to_27_ppm_per_c": fmt(1e6 * (t27 - tm40) / t27 / 67.0),
        })
    write(os.path.join(ROOT, "caps", "results", "summary_mim_pvt.csv"),
          list(tab[0].keys()), tab)


def summarize_moscap():
    src = os.path.join(ROOT, "caps", "results", "moscap.csv")
    rows = read(src)
    idx = defaultdict(dict)
    for r in rows:
        idx[(r["device"], r["moscap_corner"], r["temp_c"], r["w_um"])][
            float(r["vbias_v"])] = float(r["c_density_ff_per_um2"])

    out = []
    for key in sorted(idx, key=lambda k: (k[0], k[1], float(k[2]), float(k[3]))):
        dev, corner, temp, w = key
        cv = idx[key]
        vs = sorted(cv)
        ds = [cv[v] for v in vs]
        dmax, dmin = max(ds), min(ds)
        half = 0.5 * (dmax + dmin)
        knee = None
        for i in range(len(vs) - 1):
            if (ds[i] - half) * (ds[i + 1] - half) <= 0 and ds[i] != ds[i + 1]:
                frac = (half - ds[i]) / (ds[i + 1] - ds[i])
                knee = vs[i] + frac * (vs[i + 1] - vs[i])
                break
        # usable bias window: where the density is within 10% of its maximum
        usable = [v for v, d in zip(vs, ds) if d >= 0.9 * dmax]
        out.append({
            "device": dev, "moscap_corner": corner, "temp_c": temp, "size_um": w,
            "density_max_ff_per_um2": fmt(dmax),
            "vbias_at_max_v": fmt(vs[ds.index(dmax)]),
            "density_min_ff_per_um2": fmt(dmin),
            "vbias_at_min_v": fmt(vs[ds.index(dmin)]),
            "density_at_0v_ff_per_um2": fmt(cv[0.0]),
            "density_at_p1v65_ff_per_um2": fmt(cv[1.65]),
            "density_at_m1v65_ff_per_um2": fmt(cv[-1.65]),
            "max_over_min_ratio": fmt(dmax / dmin if dmin else None),
            "knee_v_at_half_swing": fmt(knee),
            "usable_bias_min_v": fmt(min(usable)) if usable else "",
            "usable_bias_max_v": fmt(max(usable)) if usable else "",
        })
    write(os.path.join(ROOT, "caps", "results", "summary_moscap.csv"),
          list(out[0].keys()), out)


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------

# (relative path, corner column, expected corners, temperature column)
COVERAGE_SPECS = [
    ("fets/results/vth.csv", "corner", {"typical", "ff", "ss", "fs", "sf"}, "temp_c"),
    ("fets/results/rdson_pmos.csv", "corner", {"typical", "ff", "ss", "fs", "sf"}, "temp_c"),
    ("fets/results/rdson_nmos.csv", "corner", {"typical", "ff", "ss", "fs", "sf"}, "temp_c"),
    ("fets/results/cgg_pmos.csv", "corner", {"typical", "ff", "ss", "fs", "sf"}, "temp_c"),
    ("fets/results/cgg_nmos.csv", "corner", {"typical", "ff", "ss", "fs", "sf"}, "temp_c"),
    ("fets/results/leak_pmos.csv", "corner", {"typical", "ff", "ss", "fs", "sf"}, "temp_c"),
    ("fets/results/leak_nmos.csv", "corner", {"typical", "ff", "ss", "fs", "sf"}, "temp_c"),
    ("resistors/results/rsheet.csv", "res_corner",
     {"res_typical", "res_ff", "res_ss"}, "temp_c"),
    ("caps/results/mim.csv", "mim_corner",
     {"mimcap_typical", "mimcap_ff", "mimcap_ss"}, "temp_c"),
    ("caps/results/moscap.csv", "moscap_corner",
     {"moscap_typical", "moscap_ff", "moscap_ss"}, "temp_c"),
]
EXPECTED_TEMPS = {"-40", "27", "125"}


def check_coverage():
    """Assert every device in every raw table carries the full corner and
    temperature matrix. A missing corner is the failure mode that produces a
    plausible-looking but silently optimistic table, so it is checked
    mechanically rather than by eye."""
    out = []
    failures = 0
    for rel, ccol, corners, tcol in COVERAGE_SPECS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        rows = read(path)
        seen = defaultdict(lambda: (set(), set()))
        for r in rows:
            c, t = seen[r["device"]]
            c.add(r[ccol])
            t.add(r[tcol])
        for dev in sorted(seen):
            got_c, got_t = seen[dev]
            miss_c = sorted(corners - got_c)
            miss_t = sorted(EXPECTED_TEMPS - got_t)
            ok = not miss_c and not miss_t
            failures += 0 if ok else 1
            out.append({
                "table": rel, "device": dev,
                "corners_present": "|".join(sorted(got_c)),
                "temps_present": "|".join(sorted(got_t, key=float)),
                "missing_corners": "|".join(miss_c),
                "missing_temps": "|".join(miss_t),
                "status": "PASS" if ok else "FAIL",
            })
    write(os.path.join(ROOT, "coverage.csv"), list(out[0].keys()), out)
    print(f"  coverage: {len(out) - failures}/{len(out)} device/table pairs complete")
    return failures


def main():
    print("summarizing device characterization results")
    have = lambda *p: os.path.exists(os.path.join(ROOT, *p))
    if have("fets", "results", "rdson_pmos.csv"):
        summarize_pass_fet()
    if have("fets", "results", "rdson_nmos.csv"):
        summarize_nmos_headroom()
    if have("fets", "results", "vth.csv"):
        summarize_vth()
    if have("fets", "results", "cgg_pmos.csv"):
        summarize_cgg()
    if have("fets", "results", "leak_pmos.csv"):
        summarize_leakage()
    if have("resistors", "results", "rsheet.csv"):
        summarize_resistors()
    if have("resistors", "results", "mismatch_mc_raw.csv"):
        summarize_matching()
    if have("caps", "results", "mim.csv"):
        summarize_mim()
    if have("caps", "results", "moscap.csv"):
        summarize_moscap()
    failures = check_coverage()
    print("done")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
