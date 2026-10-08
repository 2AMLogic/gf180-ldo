#!/usr/bin/env python3
"""Bias-acquisition characterization of the DR-0037 self-biased servos (issue #352).

    python3 sim/soft-start/testbench/bias_acq.py --record-id <id> \\
        [--scenario op,op_nodeset,encycle,powerup,forced,vreflate,negctl] \\
        [--only tt,27,3.30 --backend local] [--waveforms]

Both DR-0037 servos -- ``ldo_ilimit`` (nodes ``PB``/``VG``/``VX``) and
``ldo_softstart`` (``PB_SS``/``VG_SS``/``VX_SS``) -- sit inside every
``ldo_core`` instance, so every scenario below measures both of them in the
same run. Each scenario is ONE ``klt sim`` job with ONE ``ldo_core`` instance
(so a solver diagnostic on a corner belongs to that scenario and nothing
else) over the 63-point matrix ``klt_batch`` declares (7 process incl.
``res_ff``/``res_ss`` x {-40, 27, 125} C x {2.97, 3.30, 3.63} V).

Scenarios (timing constants in ``SCENARIOS``; all windows are declared here,
before any result is read):

``op``          DC operating point, EN = VIN. Reproduces the original
                observation (dynamic-gmin fallback) per corner and reads the
                settled bias without any transient.
``op_nodeset``  the same ``op`` with ``.nodeset`` hints placing both servos in
                the inactive state (PB at 3.0 V ~ VIN, VG = VX = 0). A solver
                hint, NOT evidence of physical startup: it only shows which
                root Newton lands on from that guess.
``encycle``     VIN steady, EN = 0 at t = 0 (so the t = 0 operating point is
                the *disabled* circuit, not the intended enabled root), EN
                rises at 20 us, then three disable/enable cycles with 100 us,
                1 us and 10 us off-times.
``powerup``     VIN ramps 0 -> VIN over 100 us with EN tied to VIN (the
                t = 0 operating point is the all-zero, unpowered circuit).
``forced``      EN = VIN throughout; ideal switches (``S``, Ron 10 ohm,
                Roff 1e13 ohm) clamp PB -> VIN, VG -> VSS and VX -> VSS in BOTH
                servos until 20 us, then open in 10 ns. The t = 0 operating
                point is therefore pinned to the physically motivated inactive
                state (PMOS mirror off, no conveyor drive, no Rbias current),
                and nothing the solver does can pre-select the intended root;
                after release only the circuit can leave that state.
``vreflate``    VIN and EN up, VREF = 0 until 20 us then a 100 us ramp to
                1.2 V (the startup branch's inverter is powered from VREF).
``negctl``      negative control: ``forced`` with each startup device's gate
                (``Mst``/``Mst_ss``) tied to VSS. Expected to stay inactive;
                it shows the forced-inactive test can see a stuck loop.

Instrumentation (``instrument()``): 0 V ammeters in series with each servo's
``Mconv`` drain, ``Mst`` drain and the ``Rbias``/``Rss_bias`` top terminal;
for ``forced``/``negctl`` the hold switches above, driven by the global node
``HOLD_ACQ``. Electrically the ammeters are null. The committed netlist is
never edited; the instrumented copy and its sha256 are written beside the
results.

Grading is ``classify()``; thresholds are ``TOL``. Nothing here is a spec
limit. Missing / non-finite values or an errored corner grade ``INVALID``,
never ``ACQUIRED``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import klt_batch as kb  # noqa: E402

# --------------------------------------------------------------------------
# DUT instrumentation
# --------------------------------------------------------------------------

#: per servo: subckt, the device/element names in it, and its node names
SERVOS = {
    "il": {"subckt": "ldo_ilimit", "conv": "XMconv", "st": "XMst", "rb": "XRbias",
           "pb": "PB", "vg": "VG", "vx": "VX", "vsu": "VSU", "bb": "BB"},
    "ss": {"subckt": "ldo_softstart", "conv": "XMconv_ss", "st": "XMst_ss", "rb": "XRss_bias",
           "pb": "PB_SS", "vg": "VG_SS", "vx": "VX_SS", "vsu": "VSU_SS", "bb": "BB"},
}
#: hierarchical prefix of each servo inside the single top-level instance
INST = {"il": "xdut.xilimit", "ss": "xdut.xsoftstart"}


class InstrumentError(RuntimeError):
    pass


def _sub_once(pattern: str, repl: str, text: str, what: str) -> str:
    new, n = re.subn(pattern, repl, text, count=0, flags=re.M)
    if n != 1:
        raise InstrumentError(f"expected exactly one match for {what}, found {n}")
    return new


def instrument(netlist: str, hold: bool = False, startup_disable: bool = False) -> str:
    """Return ``netlist`` with ammeters (and optionally hold switches) added.

    Each edit must match exactly once inside its own subckt, or this raises:
    a netlist regeneration that renames a device fails loudly instead of
    silently measuring nothing.
    """
    out = netlist
    for key, s in SERVOS.items():
        m = re.search(rf"^\.subckt {s['subckt']} .*?^\.ends\s*$", out, flags=re.M | re.S)
        if not m:
            raise InstrumentError(f"subckt {s['subckt']} not found")
        block = m.group(0)
        pb, vx, vsu, bb, vg = s["pb"], s["vx"], s["vsu"], s["bb"], s["vg"]
        block = _sub_once(rf"^({s['conv']}) {pb} ", rf"\1 {pb}_ACQCV ", block, f"{key} conv drain")
        st_gate = "VSS" if startup_disable else vsu
        block = _sub_once(rf"^({s['st']}) {pb} {vsu} {bb} ", rf"\1 {pb}_ACQST {st_gate} {bb} ", block,
                          f"{key} startup device")
        block = _sub_once(rf"^({s['rb']}) {bb} {vx} ", rf"\1 {bb} {vx}_ACQRB ", block, f"{key} bias resistor")
        add = [f"* --- issue-352 instrumentation ({key}) ---",
               f"Vacq_cv {pb} {pb}_ACQCV 0",
               f"Vacq_st {pb} {pb}_ACQST 0",
               f"Vacq_rb {vx} {vx}_ACQRB 0"]
        if hold:
            add += [f"Sacq_pb {pb} VIN HOLD_ACQ 0 swacq",
                    f"Sacq_vg {vg} VSS HOLD_ACQ 0 swacq",
                    f"Sacq_vx {vx} VSS HOLD_ACQ 0 swacq"]
        block = re.sub(r"^\.ends\s*$", "\n".join(add) + "\n.ends", block, count=1, flags=re.M)
        out = out[:m.start()] + block + out[m.end():]
    head = ["* issue-352 instrumented copy -- NOT a design netlist; see bias_acq.py"]
    if hold:
        head += [".global HOLD_ACQ", ".model swacq sw vt=0.5 vh=0.1 ron=10 roff=1e13"]
    return "\n".join(head) + "\n" + out


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


# --------------------------------------------------------------------------
# Declared tolerances (fixed before any matrix result was read)
# --------------------------------------------------------------------------

TOL = {
    # Acquired: VX within +/-1 % of VREF over the whole settled sub-window.
    # 1 % of VREF is a "the loop has acquired its own operating point"
    # tolerance; it is ~25x tighter than the poly sheet spread that dominates
    # DR-0005/DR-0006, and it is not a spec limit.
    "vx_err_frac": 0.01,
    # Bias current relative to VREF/R at the window end, R taken from the
    # same corner's own Rbias ammeter: (VX - BB) / VREF.
    "ibias_err_frac": 0.01,
    # Startup branch turned off: I(Mst) <= 1 % of the servo's own bias.
    "startup_off_frac": 0.01,
    # Persistently inactive: bias below 10 % of VREF/R at the window end.
    "inactive_frac": 0.10,
    # EN = 0 intended shutdown: conveyor current below 1 % of VREF/R.
    "shutdown_frac": 0.01,
    # Settled sub-window: the last SETTLE_S of each window.
    "settle_s": 40e-6,
}
VREF_NOM = 1.2

# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------

TRAN_TMAX = "50n"  # time resolution: max internal step; windows are >= 1 us
#: a guard crossing within this much of the guard step is the step itself
#: (WHEN interpolates between the two timepoints straddling it): 10 x TMAX
GUARD_MARGIN_S = 0.5e-6

#: windows: (label, edge_s, end_s, pre_edge_state). pre_edge_state is
#: "en0" when EN has been low long enough (>= 100 us) before the edge for the
#: intended-shutdown check to be graded, "en0_short" when EN was low only
#: briefly (1 us / 10 us: the pre-edge current is reported, not graded --
#: the servo is still discharging), else None.
SCENARIOS: dict[str, dict] = {
    "op": {"kind": "op", "hold": False, "stdis": False},
    "op_nodeset": {"kind": "op", "hold": False, "stdis": False, "nodeset": True},
    "encycle": {
        "kind": "tran", "tstop": 730e-6, "hold": False, "stdis": False,
        "windows": [("en_from_shutdown", 20e-6, 170e-6, "en0"),
                    ("en_off100u", 270e-6, 420e-6, "en0"),
                    ("en_off1u", 421e-6, 570e-6, "en0_short"),
                    ("en_off10u", 580e-6, 730e-6, "en0_short")],
    },
    "powerup": {
        "kind": "tran", "tstop": 260e-6, "hold": False, "stdis": False,
        "windows": [("vin_ramp_100u", 10e-6, 260e-6, None)],
    },
    "forced": {
        "kind": "tran", "tstop": 170e-6, "hold": True, "stdis": False,
        "windows": [("release", 20e-6, 170e-6, None)],
    },
    "vreflate": {
        "kind": "tran", "tstop": 270e-6, "hold": False, "stdis": False,
        "windows": [("vref_ramp_100u", 20e-6, 270e-6, None)],
    },
    "negctl": {
        "kind": "tran", "tstop": 170e-6, "hold": True, "stdis": True,
        "windows": [("release", 20e-6, 170e-6, None)],
    },
}

_LOAD = """\
Resr VOUT n_esr 0.1
Cout n_esr 0 1u
Rload VOUT 0 36
"""


def body(scen: str) -> str:
    s = SCENARIOS[scen]
    lines = [kb.DESIGN_PARAMS, kb.WNFLAG,
             f"* issue-352 bias-acquisition scenario: {scen} (generated by bias_acq.py)",
             '.include "dut.spice"']
    if s["kind"] == "tran":
        # the soft-start bench's own solver tolerances, unchanged (no tuning)
        lines.append(".options reltol=1e-3 vntol=1e-5 abstol=1e-11 chgtol=1e-14")
    lines.append("Vin VIN 0 DC 3.3")
    if s["kind"] == "op":
        lines.append("Vdum DUM 0 DC 0\nRdum DUM 0 1k  $ dummy sweep source, connected to nothing else")
    if scen == "encycle":
        lines += ["Venctl ENCTL 0 DC 0 PWL(0 0 20u 0 20.01u 1 170u 1 170.01u 0 270u 0 270.01u 1"
                  " 420u 1 420.01u 0 421u 0 421.01u 1 570u 1 570.01u 0 580u 0 580.01u 1)",
                  "Ben EN 0 V = 'v(vin) * v(enctl)'",
                  "Vref VREF 0 DC 1.2",
                  "Xdut VIN VOUT EN 0 EOUT PG VREF ldo_core"]
    elif scen == "powerup":
        lines += ["Vpu PU 0 DC 0 PWL(0 0 10u 0 110u 1)",
                  "Bvinr VINR 0 V = 'v(vin) * v(pu)'",
                  "Een EN 0 VINR 0 1",
                  "Vref VREF 0 DC 1.2",
                  "Xdut VINR VOUT EN 0 EOUT PG VREF ldo_core"]
    elif scen == "vreflate":
        lines += ["Een EN 0 VIN 0 1",
                  "Vref VREF 0 DC 0 PWL(0 0 20u 0 120u 1.2)",
                  "Xdut VIN VOUT EN 0 EOUT PG VREF ldo_core"]
    else:  # op, op_nodeset, forced, negctl
        lines += ["Een EN 0 VIN 0 1",
                  "Vref VREF 0 DC 1.2",
                  "Xdut VIN VOUT EN 0 EOUT PG VREF ldo_core"]
    if s.get("hold"):
        lines.append("Vhold HOLD_ACQ 0 DC 1 PWL(0 1 20u 1 20.01u 0)")
    if s.get("nodeset"):
        ns = []
        for k in SERVOS:
            p, sv = INST[k], SERVOS[k]
            ns += [f"v({p}.{sv['pb'].lower()})=3.0", f"v({p}.{sv['vg'].lower()})=0",
                   f"v({p}.{sv['vx'].lower()})=0"]
        lines.append(".nodeset " + " ".join(ns))
    for w, (_lbl, _edge, end, _pre) in enumerate(s.get("windows", []), 1):
        for k in SERVOS:
            # measurement-only guard signal (an isolated node; it loads nothing)
            lines.append(f"Bacq_{k}_w{w} ACQ_{k.upper()}_W{w} 0 V = '{_n(k, 'vx')} - {0.99 * VREF_NOM:.6g}"
                         f" + 10 * (time >= {end - 1e-6:.9g})'")
    lines += ["Vloop PG EOUT DC 0", _LOAD]
    return "\n".join(lines) + "\n"


def _n(k: str, node: str) -> str:
    return f"v({INST[k]}.{SERVOS[k][node].lower()})"


def _i(k: str, el: str) -> str:
    return f"i(v.{INST[k]}.vacq_{el})"


def measurements(scen: str) -> list[dict]:
    s = SCENARIOS[scen]
    out: list[dict] = []
    if s["kind"] == "op":
        # `.meas dc` cards at the first point of a two-point sweep of an
        # unconnected dummy source (see body()): the batch fleet's runner
        # rejects `measurements[].expr`, and the first DC point is the same
        # initial operating-point solve (same gmin/source-stepping path) as
        # `op`. Currents are reported in A here (no expr scaling).
        sig = {f"{k}_{q}": _n(k, q) for k in SERVOS for q in ("pb", "vg", "vx", "vsu", "bb")}
        sig.update({f"{k}_i{el}": _i(k, el) for k in SERVOS for el in ("cv", "st", "rb")})
        sig.update(vref="v(vref)", vout="v(vout)")
        for name, vec in sig.items():
            out.append({"name": name, "spice": f".meas dc {name} FIND {vec} AT=0"})
        return out
    for w, (_lbl, edge, end, pre) in enumerate(s["windows"], 1):
        t_end = end - 1e-6
        t_set = end - TOL["settle_s"]
        for k in SERVOS:
            vx = _n(k, "vx")
            cards = {
                "vx_end": f"FIND {vx} AT={t_end:.9g}",
                "bb_end": f"FIND {_n(k, 'bb')} AT={t_end:.9g}",
                "pb_end": f"FIND {_n(k, 'pb')} AT={t_end:.9g}",
                "vg_end": f"FIND {_n(k, 'vg')} AT={t_end:.9g}",
                "vsu_end": f"FIND {_n(k, 'vsu')} AT={t_end:.9g}",
                "icv_end": f"FIND {_i(k, 'cv')} AT={t_end:.9g}",
                "irb_end": f"FIND {_i(k, 'rb')} AT={t_end:.9g}",
                "ist_end": f"FIND {_i(k, 'st')} AT={t_end:.9g}",
                "vx_setmax": f"MAX {vx} FROM={t_set:.9g} TO={t_end:.9g}",
                "vx_setmin": f"MIN {vx} FROM={t_set:.9g} TO={t_end:.9g}",
                "vx_winmin": f"MIN {vx} FROM={edge:.9g} TO={t_end:.9g}",
                "ist_peak": f"MAX {_i(k, 'st')} FROM={edge:.9g} TO={t_end:.9g}",
                # ACQ_<k>_W<w> is v(vx) - 0.99*VREF with a +10 V step at the
                # window end (body()), so this card always resolves: a value at
                # t_end means "not acquired inside the window".
                "t99": f"WHEN v(acq_{k}_w{w})=0 RISE=1 TD={edge:.9g}",
            }
            if pre in ("en0", "en0_short"):
                t_pre = edge - 0.5e-6
                cards["vx_pre"] = f"FIND {vx} AT={t_pre:.9g}"
                cards["pb_pre"] = f"FIND {_n(k, 'pb')} AT={t_pre:.9g}"
                cards["icv_pre"] = f"FIND {_i(k, 'cv')} AT={t_pre:.9g}"
            for q, spec in cards.items():
                name = f"w{w}_{k}_{q}"
                out.append({"name": name, "spice": f".meas tran {name} {spec}"})
        out.append({"name": f"w{w}_vref_end", "spice": f".meas tran w{w}_vref_end FIND v(vref) AT={t_end:.9g}"})
    return out


def job(scen: str, dut_text_path: Path, axes: dict, waveforms: bool = False) -> kb.Job:
    s = SCENARIOS[scen]
    if s["kind"] == "op":
        analysis = {"kind": "dc", "args": "Vdum 0 1 1"}
        timeout = 900
    else:
        analysis = {"kind": "tran", "args": f"10n {s['tstop'] * 1e6:g}u 0 {TRAN_TMAX}"}
        timeout = 5400
    j = kb.Job(name=scen, body=body(scen), dut_netlist=dut_text_path, analysis=analysis,
               measurements=measurements(scen), timeout_s=timeout, **axes)
    if waveforms:
        j.waveforms = True  # type: ignore[attr-defined]
    return j


# --------------------------------------------------------------------------
# Log classification (solver path) and grading -- pure functions, unit-tested
# --------------------------------------------------------------------------

def solver_path(log: str | None) -> str:
    """Classify how the initial DC solve converged, from the ngspice log.

    ``direct``        no continuation was needed
    ``dyn_gmin``      dynamic gmin stepping completed
    ``true_gmin``     dynamic gmin failed, true gmin stepping completed
    ``src_step``      gmin stepping failed, source stepping completed
    ``failed``        every continuation failed / the run aborted
    ``missing``       no log
    """
    if log is None:
        return "missing"
    lo = log.lower()
    if "simulation(s) aborted" in lo or "source stepping failed" in lo or "no convergence in dc" in lo:
        return "failed"
    if "source stepping completed" in lo:
        return "src_step"
    if "true gmin stepping completed" in lo:
        return "true_gmin"
    if "dynamic gmin stepping completed" in lo:
        return "dyn_gmin"
    if "gmin stepping failed" in lo:
        return "failed"
    return "direct"


def tran_trouble(log: str | None) -> list[str]:
    """Transient-phase solver trouble after the initial operating point."""
    if not log:
        return []
    flags = []
    for pat, code in ((r"timestep too small", "timestep_too_small"),
                      (r"singular matrix", "singular_matrix"),
                      (r"trouble with node", "trouble_with_node")):
        if re.search(pat, log, flags=re.I):
            flags.append(code)
    return flags


def _ok(*vals) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vals)


def classify(v: dict, w: int, k: str, edge: float, end: float, status: str | None,
             negctl: bool = False, pre: str | None = None) -> dict:
    """Grade one (window, servo). Returns a dict with ``verdict`` and metrics.

    Verdicts: ``ACQUIRED``; ``STARTUP_ON`` (bias acquired but startup branch
    still conducting); ``UNSETTLED`` (active but outside the declared
    tolerance); ``INACTIVE`` (persistent inactive state at window end);
    ``INVALID`` (errored corner, missing or non-finite value). For the
    negative control the expected verdict is ``INACTIVE``.
    """
    g = lambda q: v.get(f"w{w}_{k}_{q}")  # noqa: E731
    vref = v.get(f"w{w}_vref_end")
    vx, bb, icv, irb, ist = g("vx_end"), g("bb_end"), g("icv_end"), g("irb_end"), g("ist_end")
    smax, smin = g("vx_setmax"), g("vx_setmin")
    r: dict = {"window": w, "servo": k}
    if status == "error" or not _ok(vref, vx, bb, icv, irb, ist, smax, smin) or not vref or vref <= 0:
        r["verdict"] = "INVALID"
        r["reason"] = "corner errored" if status == "error" else "missing or non-finite measurement"
        return r
    rel = (vx - bb) / vref
    r["ibias_rel"] = rel
    r["vx_err_mv"] = (vx - vref) * 1e3
    r["vx_set_dev_mv"] = max(abs(smax - vref), abs(smin - vref)) * 1e3
    r["icv_ua"] = icv * 1e6
    r["ist_na"] = ist * 1e9
    r["r_eff_kohm"] = (vx - bb) / irb / 1e3 if irb > 0 else None
    r["ist_frac"] = (ist / icv) if icv > 0 else math.inf
    pk = g("ist_peak")
    r["ist_peak_ua"] = pk * 1e6 if _ok(pk) else None
    t99, wmin = g("t99"), g("vx_winmin")
    lo = 0.99 * VREF_NOM
    if _ok(wmin) and wmin >= lo:
        r["t_acq_us"] = 0.0  # never left the band: nothing to acquire
    elif _ok(t99) and edge <= t99 < end - 1e-6 - GUARD_MARGIN_S:
        r["t_acq_us"] = (t99 - edge) * 1e6
    else:
        r["t_acq_us"] = None
    if pre in ("en0", "en0_short"):
        if _ok(g("icv_pre"), g("vx_pre")):
            r["en0_icv_na"] = g("icv_pre") * 1e9
            r["en0_vx"] = g("vx_pre")
            if pre == "en0":
                # intended EN = 0 shutdown, relative to this servo's own
                # acquired bias later in the same window
                r["en0_shutdown_ok"] = icv > 0 and abs(g("icv_pre")) <= TOL["shutdown_frac"] * icv
        else:
            r["verdict"] = "INVALID"
            r["reason"] = "missing or non-finite pre-edge measurement"
            return r
    if rel < TOL["inactive_frac"]:
        r["verdict"] = "INACTIVE"
    elif (r["vx_set_dev_mv"] > TOL["vx_err_frac"] * vref * 1e3
          or abs(rel - 1.0) > TOL["ibias_err_frac"]):
        r["verdict"] = "UNSETTLED"
    elif r["ist_frac"] > TOL["startup_off_frac"]:
        r["verdict"] = "STARTUP_ON"
    else:
        r["verdict"] = "ACQUIRED"
    if negctl:
        r["control_detects_inactive"] = r["verdict"] == "INACTIVE"
    return r


def classify_op(v: dict, k: str, status: str | None) -> dict:
    vref = v.get("vref")
    vx, bb, icv, ist = (v.get(f"{k}_{q}") for q in ("vx", "bb", "icv", "ist"))
    r: dict = {"servo": k}
    if status == "error" or not _ok(vref, vx, bb, icv, ist) or not vref:
        r["verdict"] = "INVALID"
        return r
    rel = (vx - bb) / vref
    r.update(ibias_rel=rel, vx_err_uv=(vx - vref) * 1e6, icv_ua=icv * 1e6, ist_na=ist * 1e9,
             ist_frac=(ist / icv) if icv > 0 else math.inf, pb=v.get(f"{k}_pb"), vg=v.get(f"{k}_vg"),
             vsu=v.get(f"{k}_vsu"), vout=v.get("vout"))
    if rel < TOL["inactive_frac"]:
        r["verdict"] = "INACTIVE"
    elif abs(vx - vref) > TOL["vx_err_frac"] * vref or abs(rel - 1) > TOL["ibias_err_frac"]:
        r["verdict"] = "UNSETTLED"
    elif r["ist_frac"] > TOL["startup_off_frac"]:
        r["verdict"] = "STARTUP_ON"
    else:
        r["verdict"] = "ACQUIRED"
    return r


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def _stage_and_run(j: kb.Job, dut_text: str, tmp: Path, backend: str | None):
    wd = tmp / j.name
    req = kb.stage(j, wd)
    if getattr(j, "waveforms", False):
        d = json.loads(req.read_text())
        d["options"]["waveforms"] = True
        req.write_text(json.dumps(d, indent=2) + "\n")
    report = kb.run(req, tmp / f"{j.name}-out", backend=backend)
    return req, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--dut", default=str(REPO / "design/netlist/ldo_core.spice"))
    ap.add_argument("--scenario", default=",".join(SCENARIOS))
    ap.add_argument("--backend", default=None)
    ap.add_argument("--only", default=None, help="one point, e.g. tt,27,3.30 (debug)")
    ap.add_argument("--axes", default=None,
                    help="subset as 'proc1+proc2,temp1+temp2,vin1+vin2' (e.g. waveform reference runs)")
    ap.add_argument("--waveforms", action="store_true",
                    help="request rawfiles (keep to a few corners: they are large)")
    ap.add_argument("--dest", default=None, help="output dir (default sim/soft-start/corners/<record-id>)")
    args = ap.parse_args(argv)
    scens = [s.strip() for s in args.scenario.split(",") if s.strip()]
    for s in scens:
        if s not in SCENARIOS:
            ap.error(f"unknown scenario {s}")
    axes = kb.only_axes(args.only)
    if args.axes:
        p, t, vv = args.axes.split(",")
        axes = {"process": tuple(p.split("+")), "temps": tuple(float(x) for x in t.split("+")),
                "supplies": tuple(float(x) for x in vv.split("+"))}
    dest = Path(args.dest) if args.dest else HERE.parent / "corners" / args.record_id
    dest.mkdir(parents=True, exist_ok=True)
    dut_src = Path(args.dut).read_text()
    manifest = {"dut": str(Path(args.dut).resolve().relative_to(REPO)) if str(Path(args.dut).resolve()).startswith(str(REPO)) else args.dut,
                "dut_sha256": sha256_text(dut_src), "tol": TOL, "tran_tmax": TRAN_TMAX,
                "command": ["python3", "sim/soft-start/testbench/bias_acq.py", *(argv if argv is not None else sys.argv[1:])],
                "klt_cmd": kb.klt_cmd(), "backend_arg": args.backend,
                "repo_head": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                                            capture_output=True, text=True).stdout.strip(),
                "scenarios": {}}
    rows, oprows = [], []
    with tempfile.TemporaryDirectory(prefix="bias-acq-") as tmpd:
        tmp = Path(tmpd)
        for scen in scens:
            s = SCENARIOS[scen]
            text = instrument(dut_src, hold=s["hold"], startup_disable=s["stdis"])
            dpath = tmp / f"{scen}-dut.spice"
            dpath.write_text(text)
            j = job(scen, dpath, axes, waveforms=args.waveforms)
            print(f"{scen}: instrumented DUT sha256 {sha256_text(text)}", flush=True)
            req, report = _stage_and_run(j, text, tmp, args.backend)
            sub = dest / scen
            vals = kb.collect(report, j, sub)
            shutil.copyfile(req.parent / "body.spice", sub / "body.spice")
            shutil.copyfile(req, sub / "request.json")
            shutil.copyfile(dpath, sub / "dut-instrumented.spice")
            if args.waveforms:
                for c in report.get("corners", []):
                    raw = (c.get("artifacts") or {}).get("raw")
                    if raw and Path(raw).is_file():
                        cid = kb.corner_id(c, j.supply_key)
                        shutil.copyfile(raw, tmp / f"{scen}_{cid}.raw")
                        extract_waveforms(tmp / f"{scen}_{cid}.raw", sub / f"{cid}.wave.csv")
            manifest["scenarios"][scen] = {"instrumented_sha256": sha256_text(text),
                                           "analysis": j.analysis,
                                           "environment": kb.redact(report).get("environment"),
                                           "provenance": report.get("provenance"),
                                           "corners_returned": len(vals)}
            for cid, v in sorted(vals.items()):
                logp = sub / f"{cid}.log"
                log = logp.read_text(errors="replace") if logp.is_file() else None
                sp, tt = solver_path(log), ";".join(tran_trouble(log) if s["kind"] == "tran" else [])
                base = {"scenario": scen, "corner": cid, "status": v.get("_status"),
                        "diagnostics": v.get("_diagnostics"), "solver_path": sp, "tran_trouble": tt}
                if s["kind"] == "op":
                    for k in SERVOS:
                        oprows.append({**base, **classify_op(v, k, v.get("_status"))})
                    continue
                for w, (lbl, edge, end, pre) in enumerate(s["windows"], 1):
                    for k in SERVOS:
                        rows.append({**base, "label": lbl,
                                     **classify(v, w, k, edge, end, v.get("_status"),
                                                negctl=scen == "negctl", pre=pre)})
    _write_csv(dest / "acquisition.csv", rows)
    _write_csv(dest / "op.csv", oprows)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True, default=str) + "\n")
    print(f"wrote {dest}")
    return 0


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


#: vectors retained from a waveform run (internal nodes + startup/bias currents)
WAVE_VECTORS = (["time", "v(vin)", "v(vinr)", "v(en)", "v(vref)", "v(vout)"]
                + [f"v({INST[k]}.{SERVOS[k][n].lower()})" for k in SERVOS
                   for n in ("pb", "vg", "vx", "vsu", "bb")]
                + [f"i(v.{INST[k]}.vacq_{e})" for k in SERVOS for e in ("cv", "st", "rb")])


def extract_waveforms(raw: Path, out_csv: Path, max_rows: int = 6000) -> None:
    """Keep the internal-node vectors of an ngspice ASCII rawfile as CSV.

    Decimated to at most ``max_rows`` rows by uniform stride, always keeping
    the first and last points. Vectors absent from the rawfile are skipped.
    """
    names, data, nvars, npts = [], [], 0, 0
    with open(raw, errors="replace") as f:
        lines = iter(f)
        for line in lines:
            if line.startswith("No. Variables:"):
                nvars = int(line.split(":")[1])
            elif line.startswith("No. Points:"):
                npts = int(line.split(":")[1])
            elif line.startswith("Variables:"):
                for _ in range(nvars):
                    parts = next(lines).split()
                    names.append(parts[1].lower())
            elif line.startswith("Values:"):
                cur: list[float] = []
                for vl in lines:
                    toks = vl.split()
                    if not toks:
                        continue
                    if len(cur) == 0 and len(toks) == 2:
                        cur.append(float(toks[1].split(",")[0]))
                    else:
                        cur.append(float(toks[-1].split(",")[0]))
                    if len(cur) == nvars:
                        data.append(cur)
                        cur = []
                break
    want = [n.lower() for n in WAVE_VECTORS]
    idx = [(n, names.index(n)) for n in want if n in names]
    stride = max(1, math.ceil(len(data) / max_rows))
    keep = list(range(0, len(data), stride))
    if data and keep[-1] != len(data) - 1:
        keep.append(len(data) - 1)
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([n for n, _ in idx])
        for i in keep:
            w.writerow([f"{data[i][j]:.7g}" for _, j in idx])
    _ = npts


if __name__ == "__main__":
    sys.exit(main())
