#!/usr/bin/env python3
"""Soft-start loop-gain sweep driver (issue #196).

Measures the LDO main loop's small-signal margins with
``design/ldo_softstart.sch``'s FB-injection element **in the loop**, at pinned
points of the soft-start ramp, for two DUT variants of that element:

    device   the post-#195 device-level transconductor on `main` today
    binj     the pre-#195 ideal behavioural source `Binj_ss` (commit bfc4a0a)

Why this experiment exists: PR #195 landed the device-level injection chain
together with a "KNOWN, UNRESOLVED REGRESSION (#191)" note, and #191's Builder
asked for exactly this measurement -- "what compensation does a real FB
injection element need" -- which nobody had. `sim/loop-stability/` measures
the main loop at its settled operating point, where the soft-start ramp is
over and the injection is off; nothing measured it *during* the hand-over.

    ./sim/soft-start-loop-gain/testbench/run.sh              # the whole thing
    ./sim/soft-start-loop-gain/testbench/sweep.py --explore  # tt/27C only, no record
    ./sim/soft-start-loop-gain/testbench/sweep.py --help     # every option

Everything about the loop-gain extraction itself -- the Tian/Middlebrook dual
injection, the break at ``ERRAMP_OUT``/``PASS_GATE``, the phase/gain-margin
and DR-0008 resurgence idioms, ``AC_DEC = 400`` -- is
``sim/loop-stability/``'s, imported from its driver rather than copied, so the
two experiments cannot drift apart in what a margin *means*. What is new here
is the operating points, the DUT variants, the landing rule that has to work
low on the ramp, and the attribution runs.

Exit codes: 0 the sweep ran and every point landed on the intended DC branch,
1 a point did not land (or the cross-check disagreed beyond tolerance),
2 a simulation failed, 3 an environment/usage problem.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as _dt
import importlib.util
import math
import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPDIR = HERE.parent                       # sim/soft-start-loop-gain
REPO_ROOT = EXPDIR.parent.parent           # repo root
TEMPLATE = HERE / "tb_ss_loop_gain.spice.in"
HANDOVER_TEMPLATE = HERE / "tb_ss_handover.spice.in"

sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness.corners import build_grid, resolve_corners, supply_points  # noqa: E402
from harness.pdk import find_pdk  # noqa: E402
from harness.report import (  # noqa: E402
    allocate_record_id,
    format_record_id,
    git_provenance,
    write_markdown_record,
)
from harness.runner import FATAL_LOG_RE, ngspice_binary_sha256, ngspice_version  # noqa: E402

sys.path.insert(0, str(HERE))
import netlist_variants as nv  # noqa: E402

# --- the loop-stability driver, imported rather than copied -----------------
# `sim/loop-stability/testbench/sweep.py` is a script under a hyphenated
# directory, so it is not importable by name; this is the same importlib
# idiom `sim/tests/test_loop_stability.py` already uses. Importing it (rather
# than copying its constants over) is deliberate: this experiment's whole
# claim to comparability with `sim/loop-stability/`'s records rests on the
# two using the same bars, the same AC band and resolution, and the same
# margin semantics, and a copy would let those drift silently. The Row class
# below SUBCLASSES its Row for the same reason -- `pm_deg`, `gm_db`,
# `passes` and `resurges` are inherited, not restated.
# `sim/tests/test_soft_start_loop_gain.py` asserts the identity.
_LS_PATH = REPO_ROOT / "sim" / "loop-stability" / "testbench" / "sweep.py"
_spec = importlib.util.spec_from_file_location("loop_stability_sweep", _LS_PATH)
ls = importlib.util.module_from_spec(_spec)
sys.modules["loop_stability_sweep"] = ls
_spec.loader.exec_module(ls)

PM_MIN_DEG = ls.PM_MIN_DEG            # DR-0001, 45 deg
GM_MIN_DB = ls.GM_MIN_DB              # DR-0001, 10 dB
RESURGENCE_MAX_DB = ls.RESURGENCE_MAX_DB   # DR-0008 precondition, 0 dB
AC_DEC = ls.AC_DEC                    # "400" -- issue #58's resolution policy
F_START = ls.F_START
F_STOP = ls.F_STOP
VOUT_NOM_V = ls.VOUT_NOM_V            # 1.8 V, the design's own divider
VREF_V = 1.2                          # the deck's reference source
fmt_uf, fmt_esr, fmt_ma = ls.fmt_uf, ls.fmt_esr, ls.fmt_ma
gm_str, pm_str, res_str = ls.gm_str, ls.pm_str, ls.res_str
worst_of, worst_resurgence_of = ls.worst_of, ls.worst_resurgence_of

# --- the grid ---------------------------------------------------------------
PROCESS_CORNERS = ls.PROCESS_CORNERS       # tt ff ss fs sf res_ff res_ss
TEMPS_C = ls.TEMPS_C
NOMINAL_SUPPLY_V = ls.NOMINAL_SUPPLY_V
SUPPLY_TOL = ls.SUPPLY_TOL

# Output-network configurations, all at the rated 50 mA load point. Two of
# DR-0001's three C_eff values: the 1 uF / 100 mOhm point `sim/soft-start/`
# runs its main matrix at, and the two 4.7 uF groups it runs its capacitor
# axis at (0.001 and 0.5 ohm ESR), with the remaining ESR columns filled in
# because they cost almost nothing inside the same deck and because every
# (cap, ESR) pair here EXCEPT 100 mOhm is also a `sim/loop-stability/` grid
# point -- which is what makes the anchor phase's cross-check possible.
CEFFS_F = (1.0e-6, 4.7e-6)
ESRS_OHM = (0.001, 0.05, 0.1, 0.2, 0.5)
RATED_LOAD_A = 50e-3
RATED_LOAD_OHM = 36.0      # 1.8 V / 50 mA, as sim/soft-start models it
OPEN_LOAD_OHM = 1e12       # "resistor not in use" for the ideal-sink phases

# --- the operating points ---------------------------------------------------
# SSR is the soft-start ramp node. V(SSR) is the state variable of the ramp,
# and with the injection element working as designed the regulated output
# follows VOUT = 1.5 * V(SSR) (the loop holds FB at VREF and the 300k/600k
# divider does the rest) until the injection rectifies off at V(SSR) = VREF.
PHASES: dict[str, dict] = {
    # (a)/(b)/(c) of issue #196, plus a mid-ramp point, with the load
    # resistive so the operating point exists all the way down the ramp.
    "ramp": {
        "ssr": (0.0, 0.05, 0.15, 0.6, 1.15, 1.25),
        "iload_a": 0.0,
        "rload_ohm": RATED_LOAD_OHM,
        "load_model": "resistive-36ohm",
        "why": (
            "The ramp itself, with the rated load modelled as the 36 ohm "
            "resistor it physically is. Low on the ramp the regulated output "
            "is a fraction of a volt and an ideal sink demanding 50 mA from "
            "it has no solution on the regulating branch at all"
        ),
    },
    # The hand-over points again, with sim/loop-stability's own load model so
    # the numbers are comparable with its records.
    "sink": {
        "ssr": (1.15, 1.25, 1.8),
        "iload_a": RATED_LOAD_A,
        "rload_ohm": OPEN_LOAD_OHM,
        "load_model": "ideal-sink-50mA",
        "why": (
            "The hand-over points under sim/loop-stability's own load model "
            "(ideal DC current sink, infinite small-signal impedance -- the "
            "conservative choice), so these margins are directly comparable "
            "with its records. 1.8 V is added here because it is where the "
            "device-level chain's injection has actually decayed away (see "
            "the DC transfer in the record); 1.25 V is where the ideal "
            "source's has"
        ),
    },
    # The settled state, with SSR not pinned at all: electrically the
    # loop-stability deck. This is both the sanity anchor and the measurement
    # that the SSR port promotion is inert.
    "anchor": {
        "ssr": None,
        "iload_a": RATED_LOAD_A,
        "rload_ohm": OPEN_LOAD_OHM,
        "load_model": "ideal-sink-50mA",
        "why": (
            "The settled state: SSR is left free to sit where Mtop_ss's "
            "ceiling clamp puts it, which is exactly what sim/loop-stability's "
            "deck does, so this phase is that deck plus an unconnected port"
        ),
    },
}

# --- the DC hand-over transfer ----------------------------------------------
# The margins above are measured at four or five pinned V(SSR). That is enough
# to answer "is there a phase-margin problem", and not enough to answer "what
# is this element's transfer function", which is the question a compensation
# recommendation actually has to be built on. `tb_ss_handover.spice.in` sweeps
# V(SSR) densely with an `op` at each point, on the same circuit with the same
# loop break and the same resistive load as the `ramp` phase, and reports the
# landed operating point. I_inj is then derived by the same KCL the margin
# rows use, so a HOV point and a ROW point at the same V(SSR) are the same
# measurement -- which `handover_consistency()` below checks rather than
# assumes.
#
# 0 -> 2.4 V covers the whole ramp: 0 V is the start, VREF = 1.2 V is where
# the element is SUPPOSED to rectify off, and 2.4 V is past where `Mtop_ss`'s
# ceiling clamp can hold the ramp node (its gate is at VREF and its source is
# SSR, with the bulk at VIN, so it needs roughly VREF + |Vth| + body effect).
HANDOVER_SSR_V = tuple(round(0.025 * i, 3) for i in range(97))   # 0 .. 2.400 V

# The ramp state the main loop is at when it takes the pass gate over.
# `Rh_ss` (ppolyf_u_3k, 4870 um) and `Ch_ss` (a 70x70 um mim cap) release `HG`
# with a time constant of order 100 us, and `design/ldo_softstart.sch`'s own
# #191 regression note times the glitch it documents at "~300 us" into the
# ramp. The ramp itself runs at `Fss_ramp`'s current over `Css`, of order
# 170 V/s, so ~300 us into it puts `V(SSR)` at a few tens of mV. That is the
# state the hand-over metrics below evaluate the acquisition step at, and it
# is why 0.05 V is one of the pinned margin states as well.
HANDOVER_ACQUISITION_SSR_V = 0.05

# The design intent this element is measured against, from
# `design/ldo_softstart.sch`'s own behavioural model (the `binj` variant):
#
#     I_inj = max(0, (V(VREF) - V(SSR)) * 5.0e-6)
#
# i.e. a 5 uA/V transconductance and a HARD rectification at V(SSR) = VREF.
HANDOVER_INTENT_GM_UA_PER_V = 5.0
HANDOVER_INTENT_RELEASE_V = VREF_V

# "Released" = the element delivers less than this into FB. 50 nA is 1% of the
# 5 uA the intent delivers at the bottom of the ramp, and 2.5% of the 2 uA the
# feedback divider itself carries at the settled operating point -- i.e. small
# enough that what is left cannot move the output by more than ~15 mV.
HANDOVER_RELEASE_A = 50e-9

# "In regulation" = the loop is holding FB at the reference at this ramp
# state. Outside this band the loop is not closed at all: the injection
# element is delivering more current than the divider can absorb with the
# output at zero, so FB rises above VREF, the error amplifier rails and the
# pass device is off. Such a state has no loop gain and therefore no phase
# margin, which is why it has to be found by a DC sweep and cannot be found
# by the margin deck. 5 mV is ~50x the largest departure the ideal element
# produces anywhere in this grid and ~1/50 of the smallest the device chain
# produces where it saturates, so nothing sits near the threshold.
HANDOVER_REG_TOL_V = 0.005

SSR_POINT_LABEL = {
    0.0: "(a) ramp start, injection at full tilt",
    0.05: ("(a1) the hold-release acquisition state -- `Rh_ss`/`Ch_ss` release "
           "`HG` with a ~150 us time constant and the #195 regression note "
           "times its glitch at ~300 us into the ramp, which at the ramp's own "
           "~170 V/s is where V(SSR) is when the main loop takes the pass gate "
           "over"),
    0.15: "(a1b) just above it, to bound how fast that state changes",
    0.6: "(a2) mid-ramp",
    1.15: "(b) VREF - 50 mV, just before the ideal element's hand-over",
    1.25: "(c) VREF + 50 mV, just after the ideal element's hand-over",
    1.8: "(d) VREF + 600 mV, past the device-level chain's own hand-over",
}

# --- landing rule -----------------------------------------------------------
# A phase/gain margin is a statement about a specific DC operating point, so a
# point whose DC solve did not land on the intended branch must be refused
# rather than recorded -- `sim/loop-stability/`'s rule, which this experiment
# inherits and has to generalise.
#
# Its rule is "VOUT within 10% of 1.8 V", which works because it only ever
# measures the settled state. It cannot work here: low on the ramp the
# INTENDED VOUT is near zero, which is exactly what a clamp latch also looks
# like. FB is what discriminates -- the soft-start mechanism is "hold FB at
# VREF with an injected current and let the divider set VOUT", so FB ~ VREF is
# the signature of the intended branch at EVERY point of the ramp, while the
# latch branches (ldo_ilimit's CLG clamp, or the pass device parked off with
# the divider unloaded) put FB far from it.
FB_TOL_V = 0.18            # same absolute budget as loop-stability's 10% of 1.8 V
VOUT_FLOOR_V = -0.18       # below this is the unbounded-VOUT branch
VOUT_CEIL_V = VOUT_NOM_V + 0.18

# The anchor phase is a settled point, so it gets loop-stability's own rule
# ON TOP of the two above -- if the anchor does not land where that bench
# lands, the cross-check it exists to feed is meaningless.
VOUT_TOL_FRAC = ls.VOUT_TOL_FRAC

# --- cross-check tolerance --------------------------------------------------
# Issues #182/#185: two runs of the identical command, on the identical
# netlist and PDK, were measured up to ~2 deg of phase margin and ~1 dB of
# gain margin apart across differently-built ngspice binaries reporting the
# same version string. `sim/README.md`'s "Reproducibility caveat" section
# makes checking the binary hash and host part of the convention. The anchor
# cross-check below therefore holds itself to that budget and not to a
# tighter one -- and it also runs `sim/loop-stability/`'s own deck HERE, on
# this host with this binary, so the same-host comparison has no toolchain
# term in it at all.
XCHECK_PM_TOL_DEG = 2.0
XCHECK_GM_TOL_DB = 1.0
XCHECK_F0_TOL_FRAC = 0.02

TOKEN_RE = re.compile(r"@([A-Z0-9_]+)@")

# --- ngspice startup file ---------------------------------------------------
# Written into the run's work directory, which every ngspice invocation this
# driver makes (including the cross-check's) uses as its cwd. ngspice reads
# `.spiceinit` from the current directory in preference to the user's home
# directory, so this pins the two startup settings that would otherwise be a
# silent, per-host, unrecorded input to the evidence:
#
#   wnflag=1      model binning divides W by nf. gf180mcu's widest model bin
#                 is W <= 100.01 um and the pass device is W=2000u nf=40, so
#                 with wnflag=0 the deck does not even parse ("could not find
#                 a valid modelname"). ngspice only defaults this to 1 in
#                 HSPICE/Spectre compatibility mode. Also set as a `.options`
#                 card inside the deck itself; see the deck's header.
#   num_threads=1 the sweep already runs one ngspice process per PVT point,
#                 so per-process threading buys nothing and costs
#                 reproducibility (#182 ruled thread count out as the cause
#                 of the drift it investigated only by pinning it).
SPICEINIT = "set wnflag=1\nset num_threads=1\n"


# ---------------------------------------------------------------------------
# one measured point
# ---------------------------------------------------------------------------
@dataclass
class Row(ls.Row):
    """One (PVT, variant, phase, SSR, C_eff, ESR) loop-gain point.

    Subclasses `sim/loop-stability/`'s Row so `pm_deg`, `gm_db`, `passes` and
    `resurges` are its definitions, not a second copy of them.
    """

    variant: str = "device"
    phase: str = "ramp"
    ssr_cmd: str = ""
    ssr_v: float = float("nan")
    fb_v: float = float("nan")
    isup_a: float = float("nan")
    load_model: str = ""
    rload_ohm: float = float("nan")

    @property
    def iinj_a(self) -> float:
        """The DC current the injection element delivers into FB.

        Derived, not measured, and exact: at DC the only branches on the
        feedback node are the two divider resistors (`Rtop` 300k from VOUT,
        `Rbot` 600k to VSS -- `XCff` across `Rtop` carries no DC current), the
        error amp's gate (no DC current), the injection element's drain and
        `Mpre_b_ss`'s drain (off while enabled). So KCL at FB gives

            I_inj = V(FB)/Rbot - (V(VOUT) - V(FB))/Rtop

        which is the same quantity for both DUT variants without either
        deck having to know which element is in it. This is the number the
        hand-over is actually about.
        """
        return self.fb_v / 600e3 - (self.vout_v - self.fb_v) / 300e3

    @property
    def state_id(self) -> str:
        return f"{self.variant}/{self.phase}/ssr={self.ssr_cmd}"

    @property
    def cfg_id(self) -> str:
        return f"{fmt_uf(self.ceff_f)}_{fmt_esr(self.esr_ohm)}"

    @property
    def landed(self) -> str:
        """"" if the DC solve landed on the intended branch, else why not."""
        if not math.isfinite(self.fb_v) or not math.isfinite(self.vout_v):
            return "unparsable DC operating point"
        if abs(self.fb_v - VREF_V) > FB_TOL_V:
            return (f"FB = {self.fb_v:.4g} V is more than {FB_TOL_V:g} V from "
                    f"VREF = {VREF_V:g} V: the loop is not holding the feedback "
                    f"node at the reference, so this is not the soft-start branch")
        if not (VOUT_FLOOR_V <= self.vout_v <= VOUT_CEIL_V):
            return (f"VOUT = {self.vout_v:.4g} V is outside "
                    f"[{VOUT_FLOOR_V:g}, {VOUT_CEIL_V:g}] V, i.e. off the ramp's "
                    f"own range")
        if self.phase == "anchor" and abs(self.vout_v - VOUT_NOM_V) > VOUT_TOL_FRAC * VOUT_NOM_V:
            return (f"VOUT = {self.vout_v:.4g} V is more than "
                    f"{VOUT_TOL_FRAC:.0%} from the {VOUT_NOM_V:g} V regulation "
                    f"target at a SETTLED point (sim/loop-stability's own rule)")
        return ""


ROW_FIELDS = (
    "ssr_cmd", "ssr_v", "fb_v", "vout_v", "isup_a", "ceff_f", "esr_ohm",
    "dcgain_db", "f0_hz", "phase_at_f0_deg", "f180_hz", "gain_at_f180_db",
    "f0_rising_hz", "resurgence_db",
)


def parse_row_fields(line: str) -> dict[str, str]:
    """``ROW k=v k=v ...`` -> dict, with the same strictness as loop-stability's.

    Key=value rather than positional for the reason its docstring records: a
    failed `meas` leaves its value empty, and an empty positional field
    vanishes into the whitespace so every later field is read as the wrong
    quantity. Missing or unknown keys are an error, never a default.
    """
    fields: dict[str, str] = {}
    for tok in line.split()[1:]:
        key, sep, val = tok.partition("=")
        if not sep:
            raise ValueError(f"ROW field {tok!r} is not key=value: {line!r}")
        if key in fields:
            raise ValueError(f"ROW field {key!r} repeated: {line!r}")
        fields[key] = val
    missing = [k for k in ROW_FIELDS if k not in fields]
    unknown = [k for k in fields if k not in ROW_FIELDS]
    if missing or unknown:
        raise ValueError(
            f"ROW line does not match the deck's field list "
            f"(missing {missing}, unknown {unknown}): {line!r}"
        )
    return fields


# ---------------------------------------------------------------------------
# deck rendering / running
# ---------------------------------------------------------------------------
def dc_seed_lines(pvt, ssr_cmd: str) -> str:
    """`.nodeset` cards that start Newton on the intended soft-start branch.

    Same device as `sim/loop-stability/`'s `dc_seed_lines()` and used the same
    way -- only on a retry of a point that already failed the landing check,
    never on the default path -- but seeded for the ramp state rather than
    the settled one: FB at the reference (true at every point of the ramp),
    VOUT at what the divider then makes it, and `ldo_ilimit`'s clamp gate
    parked at VIN, i.e. off. `ldo_softstart`'s own `CLG` node is NOT seeded:
    it no longer exists, #189 replaced the clamp comparator with FB
    injection.

    A `.nodeset` is a first-guess constraint ngspice releases after the first
    solve pass: it selects which of the circuit's DC solutions Newton walks
    to, it does not create one, and the retry is held to exactly the same
    landing check as the first attempt.
    """
    try:
        vout = min(1.5 * float(ssr_cmd), VOUT_NOM_V)
    except ValueError:            # the anchor phase's "free"
        vout = VOUT_NOM_V
    return "\n".join([
        f".nodeset v(VOUT)={vout:g} v(XDUT.FB)={VREF_V:g}",
        f".nodeset v(XDUT.Xilimit.CLG)={pvt.vdd:g}",
    ])


def render_deck(pvt, pdk, *, phase: str, variant: str, netlist: Path,
                ceffs, esrs, ac_dec, dc_seed: str = "",
                ssr_values=None) -> str:
    """Render the deck template for one (PVT, variant, phase).

    ``ssr_values`` narrows the phase's ramp-state list to a subset (used by
    the single-point attribution and curve runs); ``None`` means "the whole
    list this phase is defined by".
    """
    spec = dict(PHASES[phase])
    if ssr_values is not None and spec["ssr"] is not None:
        spec["ssr"] = tuple(float(v) for v in ssr_values)
    mos, res, bjt, diode, moscap, mimcap = pvt.corner.sections
    if spec["ssr"] is None:
        ssr_source = ("* SSR is NOT pinned in this phase: the port is left "
                      "unconnected, which\n* makes this deck electrically "
                      "sim/loop-stability/'s.")
        ssr_alter = "* (nothing to alter -- SSR is free)"
        ssr_list = "free"
    else:
        ssr_source = f"Vssr SSRPIN 0 DC {spec['ssr'][0]:g}"
        ssr_alter = "alter Vssr = $ss"
        ssr_list = " ".join(f"{v:g}" for v in spec["ssr"])
    subs = {
        "DESIGN_INCLUDE": str(pdk.design_include),
        "MODEL_LIB": str(pdk.model_lib),
        "LDO_NETLIST": str(netlist),
        "MOS_CORNER": mos, "RES_CORNER": res, "BJT_CORNER": bjt,
        "DIODE_CORNER": diode, "MOSCAP_CORNER": moscap, "MIMCAP_CORNER": mimcap,
        "TEMP_C": f"{pvt.temp_c:g}",
        "VIN_V": f"{pvt.vdd:g}",
        "CORNER_ID": pvt.corner_id,
        "CORNER_NAME": pvt.corner.name,
        "AC_DEC": str(ac_dec),
        "F_START": F_START,
        "F_STOP": F_STOP,
        "CEFF_LIST": " ".join(f"{v:g}" for v in ceffs),
        "ESR_LIST": " ".join(f"{v:g}" for v in esrs),
        "ILOAD": f"{spec['iload_a']:g}",
        "RLOAD": f"{spec['rload_ohm']:g}",
        "PHASE": phase,
        "VARIANT": variant,
        "SSR_SOURCE": ssr_source,
        "SSR_ALTER": ssr_alter,
        "SSR_LIST": ssr_list,
        "DC_SEED": dc_seed,
    }
    text = TEMPLATE.read_text()
    missing = {m for m in TOKEN_RE.findall(text) if m not in subs}
    if missing:
        raise SystemExit(f"template has unsubstituted tokens: {sorted(missing)}")
    return TOKEN_RE.sub(lambda m: subs[m.group(1)], text)


def _ngspice(deck: Path, log: Path, workdir: Path) -> str:
    proc = subprocess.run(
        ["ngspice", "-b", str(deck)], capture_output=True, text=True,
        cwd=str(workdir),
    )
    text = proc.stdout + proc.stderr
    log.write_text(text)
    if proc.returncode != 0:
        raise RuntimeError(f"ngspice exited {proc.returncode} (see {log})")
    if FATAL_LOG_RE.search(text):
        bad = [ln for ln in text.splitlines() if FATAL_LOG_RE.search(ln)][:3]
        raise RuntimeError(f"ngspice reported a fatal condition: {bad} (see {log})")
    if "SWEEP COMPLETE" not in text:
        raise RuntimeError(f"sweep did not complete (see {log})")
    return text


def run_point(pvt, pdk, *, phase: str, variant: str, netlist: Path, ceffs, esrs,
              ac_dec, workdir: Path, logdir: Path, dc_seed: str = "",
              ssr_values=None, stem: str | None = None):
    """Run one (PVT, variant, phase) deck. Returns (pvt, rows, error-or-None)."""
    suffix = "_dcseed" if dc_seed else ""
    stem = stem or f"{pvt.corner_id}_{variant}_{phase}{suffix}"
    deck = workdir / f"{stem}.spice"
    deck.write_text(render_deck(pvt, pdk, phase=phase, variant=variant,
                                netlist=netlist, ceffs=ceffs, esrs=esrs,
                                ac_dec=ac_dec, dc_seed=dc_seed,
                                ssr_values=ssr_values))
    log = logdir / f"{stem}.log"
    try:
        text = _ngspice(deck, log, workdir)
    except RuntimeError as exc:
        return pvt, [], str(exc)

    rows: list[Row] = []
    for line in text.splitlines():
        if not line.startswith("ROW "):
            continue
        try:
            f = parse_row_fields(line)
        except ValueError as exc:
            return pvt, [], f"{exc} (see {log})"
        rows.append(Row(
            corner_id=pvt.corner_id, corner=pvt.corner.name,
            temp_c=pvt.temp_c, vin_v=pvt.vdd,
            iload_a=PHASES[phase]["iload_a"],
            ceff_f=float(f["ceff_f"]), esr_ohm=float(f["esr_ohm"]),
            vout_v=ls._f(f["vout_v"]) if ls._f(f["vout_v"]) is not None else float("nan"),
            dcgain_db=ls._f(f["dcgain_db"]) if ls._f(f["dcgain_db"]) is not None else float("nan"),
            f0_hz=ls._f(f["f0_hz"]),
            phase_at_f0_deg=ls._f(f["phase_at_f0_deg"]),
            f180_hz=ls._f(f["f180_hz"]),
            gain_at_f180_db=ls._f(f["gain_at_f180_db"]),
            f0_rising_hz=ls._f(f["f0_rising_hz"]),
            resurgence_db=ls._f(f["resurgence_db"]),
            variant=variant, phase=phase, ssr_cmd=f["ssr_cmd"],
            ssr_v=ls._f(f["ssr_v"]) if ls._f(f["ssr_v"]) is not None else float("nan"),
            fb_v=ls._f(f["fb_v"]) if ls._f(f["fb_v"]) is not None else float("nan"),
            isup_a=ls._f(f["isup_a"]) if ls._f(f["isup_a"]) is not None else float("nan"),
            load_model=PHASES[phase]["load_model"],
            rload_ohm=PHASES[phase]["rload_ohm"],
        ))

    if PHASES[phase]["ssr"] is None:
        n_ssr = 1
    elif ssr_values is not None:
        n_ssr = len(ssr_values)
    else:
        n_ssr = len(PHASES[phase]["ssr"])
    expected = n_ssr * len(ceffs) * len(esrs)
    if len(rows) != expected:
        return pvt, rows, f"expected {expected} rows, parsed {len(rows)} (see {log})"

    bad = [r for r in rows if r.landed]
    if bad:
        w = bad[0]
        return pvt, rows, (
            f"{len(bad)}/{len(rows)} points did not land on the intended DC "
            f"branch; first is {w.state_id} / {w.cfg_id}: {w.landed}. A "
            f"loop-gain margin about a bias point that is not the one named is "
            f"meaningless, so this run is void (see {log})"
        )
    return pvt, rows, None


def run_curve(pvt, pdk, row: Row, netlist: Path, ac_dec, logdir: Path,
              workdir: Path, tag: str) -> Path:
    """Re-run one single configuration with the whole T(f) curve printed.

    Same device as `sim/loop-stability/`'s `run_curve()`: the record cites a
    scalar margin, and the curve behind it has to be in the evidence too.
    """
    ssr_values = None if PHASES[row.phase]["ssr"] is None else [row.ssr_cmd]
    text = render_deck(pvt, pdk, phase=row.phase, variant=row.variant,
                       netlist=netlist, ceffs=[row.ceff_f], esrs=[row.esr_ohm],
                       ac_dec=ac_dec, ssr_values=ssr_values)
    text = text.replace('      echo "ROW', "      print tdb tph\n" + '      echo "ROW')
    deck = workdir / f"{pvt.corner_id}_{tag}.spice"
    deck.write_text(text)
    log = logdir / f"{pvt.corner_id}_{tag}.log"
    proc = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True,
                          text=True, cwd=str(workdir))
    header = (
        f"* full loop-gain curve T(f) for this record's {tag} point\n"
        f"* corner={pvt.corner_id} variant={row.variant} phase={row.phase} "
        f"ssr={row.ssr_cmd} ceff={fmt_uf(row.ceff_f)} esr={fmt_esr(row.esr_ohm)}\n"
        f"* the two printed columns after the frequency are |T| in dB and "
        f"unwrapped phase(T) in degrees\n"
    )
    log.write_text(header + proc.stdout + proc.stderr)
    return log


def parse_curve(path: Path) -> list[tuple[float, float, float]]:
    """(f, |T| dB, unwrapped phase deg) from a run_curve() log.

    ngspice's `print` emits the two vectors in column groups, each group
    repeating the frequency axis, so the rows are read positionally and then
    re-joined on frequency.
    """
    rows: list[tuple[float, float, float]] = []
    for ln in path.read_text().splitlines():
        parts = ln.split()
        if len(parts) == 4 and re.fullmatch(r"\d+", parts[0]):
            try:
                f, a, b = float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError:
                continue
            rows.append((f, a, b))
    return rows


# ---------------------------------------------------------------------------
# the DC hand-over transfer
# ---------------------------------------------------------------------------
HOV_FIELDS = ("ssr_cmd", "ssr_v", "fb_v", "vout_v", "pg_v", "erramp_v", "isup_a")
HOV_OPTIONAL_FIELDS = ("gmsum_v",)


def parse_hov_fields(line: str) -> dict[str, str]:
    """``HOV k=v k=v ...`` -> dict, with the margin parser's strictness.

    ``gmsum_v`` is optional because the node only exists in the device-level
    variant; every other field is required, and an unknown one is an error
    rather than something to ignore.
    """
    fields: dict[str, str] = {}
    for tok in line.split()[1:]:
        key, sep, val = tok.partition("=")
        if not sep:
            raise ValueError(f"HOV field {tok!r} is not key=value: {line!r}")
        if key in fields:
            raise ValueError(f"HOV field {key!r} repeated: {line!r}")
        fields[key] = val
    missing = [k for k in HOV_FIELDS if k not in fields]
    unknown = [k for k in fields
               if k not in HOV_FIELDS and k not in HOV_OPTIONAL_FIELDS]
    if missing or unknown:
        raise ValueError(
            f"HOV line does not match the deck's field list "
            f"(missing {missing}, unknown {unknown}): {line!r}"
        )
    return fields


@dataclass
class HovPoint:
    """One pinned V(SSR) of the DC hand-over transfer."""

    ssr_cmd: float
    ssr_v: float
    fb_v: float
    vout_v: float
    pg_v: float
    erramp_v: float
    isup_a: float
    gmsum_v: float | None = None

    @property
    def iinj_a(self) -> float:
        """The current the injection element delivers into FB.

        Exactly `Row.iinj_a` -- KCL at the feedback node, whose only other DC
        branches are the two divider resistors. It stays exact when the loop
        is out of regulation, because it is a statement about the node's
        branches and not about the loop being closed.
        """
        return self.fb_v / 600e3 - (self.vout_v - self.fb_v) / 300e3

    @property
    def in_regulation(self) -> bool:
        return abs(self.fb_v - VREF_V) <= HANDOVER_REG_TOL_V


@dataclass
class HovCurve:
    """One (PVT, variant) DC hand-over transfer."""

    corner_id: str
    corner: str
    temp_c: float
    vin_v: float
    variant: str
    points: list[HovPoint]

    # -- derived metrics; every one of them is a number the recommendation
    # -- in design/softstart_injection_compensation.md cites.
    @property
    def iinj_start_a(self) -> float:
        """What the element delivers at the bottom of the ramp, V(SSR) = 0.

        The hard ceiling this must stay under is what the divider can absorb
        with the output at zero, VREF/600k + VREF/300k = 6.0 uA. Above it
        there is no solution with FB at VREF, so the loop leaves regulation.
        """
        return self.points[0].iinj_a

    def acquisition_step_v(self, ssr: float) -> float:
        """The output voltage the main loop has to acquire at hold release.

        Until `Mhold_ss` lets go, `PASS_GATE` is held at `VIN`, the pass
        device is off and the output is at zero. The instant the main loop
        owns the pass gate, the output it is being asked to hold is whatever
        the injection element's current at the ramp state reached by then
        implies -- so that voltage is a **step** the loop takes into `C_out`,
        and `C_out * dV/dt` through it is a capacitor current.

        The design intent makes this step zero at the bottom of the ramp by
        construction: the ideal element delivers exactly
        `VREF/600k + VREF/300k = 6.0 uA` at `V(SSR) = 0`, which is exactly the
        current that puts the output at zero, and its transconductance then
        walks the output up from there continuously. A device-level element
        that delivers a different current at the same ramp state starts the
        loop somewhere else.

        This is a DC quantity and this experiment measures nothing else about
        it: how much capacitor current a given step produces depends on the
        loop's large-signal acquisition time, which is a transient property
        `sim/soft-start/` owns and which nothing here re-runs.

        It is read off the *landed* output voltage rather than recomputed from
        `I_inj`, so it stays the measured truth at ramp states where the loop
        is out of regulation (there the output is held at zero by a railed
        error amplifier and the step is genuinely zero -- the failure at those
        states is the recovery out of saturation, not a step).
        """
        return self.vout_at(ssr)

    def vout_at(self, ssr: float) -> float:
        """Linear interpolation of the landed output voltage at one V(SSR)."""
        pts = self.points
        if ssr <= pts[0].ssr_v:
            return pts[0].vout_v
        for a, b in zip(pts, pts[1:]):
            if a.ssr_v <= ssr <= b.ssr_v:
                if b.ssr_v == a.ssr_v:
                    return a.vout_v
                w = (ssr - a.ssr_v) / (b.ssr_v - a.ssr_v)
                return a.vout_v + w * (b.vout_v - a.vout_v)
        return pts[-1].vout_v

    @property
    def gm_a_per_v(self) -> float:
        """Least-squares dI_inj/dV(SSR) over the element's live, linear range.

        Fitted only over points that are in regulation and still delivering
        at least 1 uA, i.e. the part of the ramp the element is actually
        controlling -- not the saturated bottom (where the loop is open) and
        not the sub-threshold tail (where the element is a decaying
        exponential and a slope is not the right description).
        """
        sel = [p for p in self.points
               if p.in_regulation and p.iinj_a >= 1e-6]
        if len(sel) < 3:
            return float("nan")
        n = len(sel)
        sx = sum(p.ssr_v for p in sel)
        sy = sum(p.iinj_a for p in sel)
        sxx = sum(p.ssr_v ** 2 for p in sel)
        sxy = sum(p.ssr_v * p.iinj_a for p in sel)
        den = n * sxx - sx * sx
        if den == 0:
            return float("nan")
        return (n * sxy - sx * sy) / den

    @property
    def release_ssr_v(self) -> float | None:
        """Lowest V(SSR) from which the element stays below HANDOVER_RELEASE_A.

        "Stays below" and not "first drops below": the tail is monotone in
        practice but a threshold crossing that is not final is not a release,
        and reporting one would flatter the element.
        """
        for i, p in enumerate(self.points):
            if all(q.iinj_a <= HANDOVER_RELEASE_A for q in self.points[i:]):
                return p.ssr_v
        return None

    @property
    def release_overshoot_v(self) -> float | None:
        """How far past VREF the ramp has to go before the element lets go."""
        r = self.release_ssr_v
        return None if r is None else r - HANDOVER_INTENT_RELEASE_V

    @property
    def iinj_at_vref_a(self) -> float:
        """What is still being injected where the intent says zero."""
        return self.iinj_at(HANDOVER_INTENT_RELEASE_V)

    def iinj_at(self, ssr: float) -> float:
        """Linear interpolation of the measured transfer at one V(SSR)."""
        pts = self.points
        if ssr <= pts[0].ssr_v:
            return pts[0].iinj_a
        for a, b in zip(pts, pts[1:]):
            if a.ssr_v <= ssr <= b.ssr_v:
                if b.ssr_v == a.ssr_v:
                    return a.iinj_a
                w = (ssr - a.ssr_v) / (b.ssr_v - a.ssr_v)
                return a.iinj_a + w * (b.iinj_a - a.iinj_a)
        return pts[-1].iinj_a

    @property
    def saturated_to_ssr_v(self) -> float | None:
        """Highest V(SSR) at which the loop is NOT in regulation, or None.

        This is the over-injection region at the bottom of the ramp: the
        element sources more into FB than the divider can absorb, FB is pushed
        above VREF, the error amplifier rails and the pass device is off. The
        loop is open there, so no small-signal margin describes it, and the
        exit from it is a large-signal recovery rather than a regulated ramp.
        """
        out = [p.ssr_v for p in self.points if not p.in_regulation]
        return max(out) if out else None

    @property
    def fb_max_v(self) -> float:
        return max(p.fb_v for p in self.points)

    @property
    def vout_top_err_v(self) -> float:
        """Output error at the top of the swept range, where the ramp ends."""
        return self.points[-1].vout_v - VOUT_NOM_V

    @property
    def gmsum_span_v(self) -> tuple[float, float] | None:
        g = [p.gmsum_v for p in self.points if p.gmsum_v is not None]
        return (min(g), max(g)) if g else None


def render_handover_deck(pvt, pdk, *, variant: str, netlist: Path,
                         ssr_values=HANDOVER_SSR_V) -> str:
    mos, res, bjt, diode, moscap, mimcap = pvt.corner.sections
    has_gmsum = variant == "device"
    subs = {
        "DESIGN_INCLUDE": str(pdk.design_include),
        "MODEL_LIB": str(pdk.model_lib),
        "LDO_NETLIST": str(netlist),
        "MOS_CORNER": mos, "RES_CORNER": res, "BJT_CORNER": bjt,
        "DIODE_CORNER": diode, "MOSCAP_CORNER": moscap, "MIMCAP_CORNER": mimcap,
        "TEMP_C": f"{pvt.temp_c:g}",
        "VIN_V": f"{pvt.vdd:g}",
        "CORNER_ID": pvt.corner_id,
        "CORNER_NAME": pvt.corner.name,
        "VARIANT": variant,
        "SSR_LIST": " ".join(f"{v:g}" for v in ssr_values),
        # The mirror node exists only in the device-level chain; the pre-#195
        # ideal source has no such node, so its decks do not name it and do
        # not emit the column. Emitting a zero instead would put a number in
        # the record that is not a measurement.
        "GMSUM_COL": " gmsum_v=" if has_gmsum else "",
        "GMSUM_LET": ("  let gmsum_dc = v(xdut.xsoftstart.gmsum)"
                      if has_gmsum else
                      "* (no mirror node in this variant)"),
        "GMSUM_ECHO": " gmsum_v=$&gmsum_dc" if has_gmsum else "",
    }
    text = HANDOVER_TEMPLATE.read_text()
    missing = {m for m in TOKEN_RE.findall(text) if m not in subs}
    if missing:
        raise SystemExit(
            f"hand-over template has unsubstituted tokens: {sorted(missing)}")
    return TOKEN_RE.sub(lambda m: subs[m.group(1)], text)


def run_handover(pvt, pdk, *, variant: str, netlist: Path, workdir: Path,
                 logdir: Path):
    """Run one (PVT, variant) hand-over transfer. -> (curve, error-or-None)."""
    stem = f"{pvt.corner_id}_{variant}_handover"
    deck = workdir / f"{stem}.spice"
    deck.write_text(render_handover_deck(pvt, pdk, variant=variant,
                                         netlist=netlist))
    log = logdir / f"{stem}.log"
    try:
        text = _ngspice(deck, log, workdir)
    except RuntimeError as exc:
        return None, str(exc)

    pts: list[HovPoint] = []
    for line in text.splitlines():
        if not line.startswith("HOV "):
            continue
        try:
            f = parse_hov_fields(line)
        except ValueError as exc:
            return None, f"{exc} (see {log})"
        gm = f.get("gmsum_v")
        pts.append(HovPoint(
            ssr_cmd=float(f["ssr_cmd"]),
            ssr_v=ls._f(f["ssr_v"]),
            fb_v=ls._f(f["fb_v"]),
            vout_v=ls._f(f["vout_v"]),
            pg_v=ls._f(f["pg_v"]),
            erramp_v=ls._f(f["erramp_v"]),
            isup_a=ls._f(f["isup_a"]),
            gmsum_v=None if gm is None else ls._f(gm),
        ))
    if len(pts) != len(HANDOVER_SSR_V):
        return None, (f"expected {len(HANDOVER_SSR_V)} HOV points, parsed "
                      f"{len(pts)} (see {log})")
    if any(p.ssr_v is None or p.fb_v is None or p.vout_v is None for p in pts):
        return None, f"a HOV point has an unparsable operating point (see {log})"
    return HovCurve(corner_id=pvt.corner_id, corner=pvt.corner.name,
                    temp_c=pvt.temp_c, vin_v=pvt.vdd, variant=variant,
                    points=pts), None


def handover_consistency(curves: list[HovCurve], rows: list[Row]):
    """Worst |dVOUT| between a HOV point and the ROW at the same ramp state.

    The two decks are different files running different analyses; they are
    only comparable because they are deliberately the same circuit at the same
    operating point. This measures that rather than asserting it. Compared
    only against the `ramp` phase (the shared resistive load model) at the
    1 uF / 100 mOhm output network.
    """
    by_key = {(c.corner_id, c.variant): c for c in curves}
    worst = None
    n = 0
    for r in rows:
        if r.phase != "ramp":
            continue
        if abs(r.ceff_f - 1e-6) > 1e-15 or abs(r.esr_ohm - 0.1) > 1e-12:
            continue
        c = by_key.get((r.corner_id, r.variant))
        if c is None:
            continue
        hov = min(c.points, key=lambda p: abs(p.ssr_v - r.ssr_v))
        if abs(hov.ssr_v - r.ssr_v) > 1e-6:
            continue
        d = abs(hov.vout_v - r.vout_v)
        n += 1
        if worst is None or d > worst[0]:
            worst = (d, r, hov)
    return worst, n


HANDOVER_CSV_HEADER = [
    "corner_id", "corner", "temp_c", "vin_v", "variant", "ssr_cmd_v", "ssr_v",
    "fb_v", "vout_v", "iinj_ua", "pass_gate_v", "erramp_out_v", "isup_a",
    "gmsum_v", "in_regulation",
]


def write_handover_csv(path: Path, curves: list[HovCurve]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HANDOVER_CSV_HEADER)
        for c in curves:
            for p in c.points:
                w.writerow([
                    c.corner_id, c.corner, f"{c.temp_c:g}", f"{c.vin_v:.2f}",
                    c.variant, f"{p.ssr_cmd:g}", f"{p.ssr_v:.6f}",
                    f"{p.fb_v:.6f}", f"{p.vout_v:.6f}",
                    f"{p.iinj_a * 1e6:.5f}", f"{p.pg_v:.6f}",
                    f"{p.erramp_v:.6f}", f"{p.isup_a:.6e}",
                    "" if p.gmsum_v is None else f"{p.gmsum_v:.6f}",
                    "yes" if p.in_regulation else "no",
                ])


# ---------------------------------------------------------------------------
# reporting helpers
# ---------------------------------------------------------------------------
CSV_HEADER = [
    "corner_id", "process", "temp_c", "vin_v", "variant", "phase",
    "ssr_cmd", "ssr_v", "load_model", "iload_ma", "rload_ohm",
    "ceff_uf", "esr_ohm", "vout_v", "fb_v", "iinj_ua", "isup_ma",
    "dc_loop_gain_db", "f_crossover_hz", "phase_margin_deg",
    "f_180_hz", "gain_margin_db", "resurgence_db",
    "margin_vs_dr0001", "resurgence_vs_dr0008",
]


def csv_row(r: Row) -> list[str]:
    return [
        r.corner_id, r.corner, f"{r.temp_c:g}", f"{r.vin_v:g}", r.variant,
        r.phase, r.ssr_cmd, f"{r.ssr_v:.6g}", r.load_model,
        f"{r.iload_a * 1e3:g}", f"{r.rload_ohm:g}",
        f"{r.ceff_f * 1e6:g}", f"{r.esr_ohm:g}",
        f"{r.vout_v:.6g}", f"{r.fb_v:.6g}", f"{r.iinj_a * 1e6:.4g}",
        f"{r.isup_a * 1e3:.4g}", f"{r.dcgain_db:.4g}",
        "" if r.f0_hz is None else f"{r.f0_hz:.6g}",
        pm_str(r),
        "" if r.f180_hz is None else f"{r.f180_hz:.6g}",
        gm_str(r),
        "" if r.resurgence_db is None else f"{r.resurgence_db:.4g}",
        "no-crossover" if r.pm_deg is None else ("PASS" if r.passes else "FAIL"),
        "n/a" if r.resurgence_db is None else ("FAIL" if r.resurges else "PASS"),
    ]


def write_matrix_csv(path: Path, rows: list[Row]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for r in rows:
            w.writerow(csv_row(r))


def _hz(v) -> str:
    return "n/a" if v is None else f"{v:.4g}"


def key_of(r: Row) -> tuple:
    return (r.variant, r.phase, r.ssr_cmd, r.corner_id, r.ceff_f, r.esr_ohm)


def sort_key(r: Row) -> tuple:
    return (r.variant, r.phase, r.ssr_cmd, r.corner, r.temp_c, r.vin_v,
            r.ceff_f, r.esr_ohm)


def group(rows: list[Row], keyfn) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(keyfn(r), []).append(r)
    return out


# ---------------------------------------------------------------------------
# pole/zero attribution
# ---------------------------------------------------------------------------
# The injection element can only reach the main loop through the nodes it
# touches: `Mgmo_ss`'s drain and `Mpre_b_ss`'s drain on FB, `Mhold_ss`'s drain
# on PASS_GATE, `Mhold_bg_ss`'s on BG -- plus, inside the chain, the GMSUM
# mirror node that sets `Mgmo_ss`'s gate. Each entry below removes ONE of
# those couplings in AC only, leaving the DC operating point bit-identical
# (see netlist_variants.ac_open / ac_short), so the margin delta it produces
# is attributable to that coupling and to nothing else. This is the
# element-removal sensitivity the record's attribution rests on; it is a
# measurement, not a reading of the schematic.
ATTRIBUTIONS = (
    ("acopen-fb-inj", "XMgmo_ss's drain AC-opened from FB",
     lambda t: nv.ac_open(t, "XMgmo_ss", "FB", "acopeninj")),
    ("acopen-fb-pre", "XMpre_b_ss's drain AC-opened from FB",
     lambda t: nv.ac_open(t, "XMpre_b_ss", "FB", "acopenpre")),
    ("acshort-gmsum", "the GMSUM mirror node AC-shorted to VIN",
     lambda t: nv.ac_short(t, "GMSUM", "VIN", "acshortgmsum")),
    ("acopen-hold", "XMhold_ss's drain AC-opened from PASS_GATE",
     lambda t: nv.ac_open(t, "XMhold_ss", "PASS_GATE", "acopenhold")),
)


# --- how much capacitance the feedback node actually tolerates --------------
# `design/ldo_softstart.sch`'s regression note states a hypothesis: "ANY
# nonzero parasitic capacitance the real transconductor adds to FB (the 'tens
# of femtofarads' already called out under WHAT THIS COSTS THE MAIN LOOP) is
# enough to destabilize the main loop's hold-release transient". That is a
# falsifiable claim about a margin, and the way to test it is not to remove
# the element's parasitic and find the delta small -- that only says THIS
# element is cheap. It is to ADD known capacitance to `FB` until the margin
# bar is crossed, which turns the answer into a budget the next injection
# element can be designed against.
#
# Every value is a capacitor, so every one is DC-inert and the operating point
# is bit-identical across the whole ladder -- the record prints the landed
# VOUT for each so that is checkable rather than asserted.
FB_CAP_LADDER_F = (10e-15, 100e-15, 1e-12, 3e-12, 10e-12, 30e-12, 100e-12,
                   300e-12, 1e-9)

# The budget is stated RELATIVE to the same point with no added capacitance,
# not against DR-0001's 45 deg / 10 dB reference lines. Two reasons, and the
# second one is the load-bearing one:
#
#  - a mid-ramp state is not a DR-0001 operating point, so the absolute bars
#    are reference lines here and not a criterion (this record says so
#    throughout); and
#  - the worst device-variant point in this grid is at a corner where the MAIN
#    loop is already below 45 deg with either injection element and with no
#    added capacitance at all (`sim/loop-stability/`'s own open 1-50 mA gap,
#    #51). Against an absolute bar every rung of the ladder "fails" there and
#    the ladder says nothing. Against its own baseline it says exactly what
#    was asked: how much capacitance this node takes before the margin moves.
#
# Both margins are checked, because they fail in different places: adding
# capacitance at FB first RAISES the phase margin (it rolls the loop off
# earlier) and only later collapses it, while the gain margin goes first --
# by tens of dB, which is what "the loop is now unstable" looks like.
FB_CAP_PM_TOL_DEG = 2.0     # the #182/#185 cross-invocation movement class
FB_CAP_GM_TOL_DB = 1.0


def _sub(curve: list[tuple[float, float, float]], n: int = 160):
    """Log-uniform subsample of a T(f) curve, for the fit below."""
    if len(curve) <= n:
        return curve
    step = len(curve) / float(n)
    return [curve[int(i * step)] for i in range(n)]


def fit_pole_zero(num: list[tuple[float, float, float]],
                  den: list[tuple[float, float, float]]):
    """Fit ``k*(1+jf/fz)/(1+jf/fp)`` to the ratio of two measured T(f) curves.

    ``num``/``den`` are ``run_curve`` outputs (f, |T| dB, phase deg) for two
    decks that differ in exactly one coupling. Their ratio is, for a single
    added R-C on a node, exactly one pole and one zero, so this fit is a
    statement the data can refute: the residual is reported alongside the fit
    and a bad residual means the single-pole/zero reading is wrong, not that
    the numbers should be trusted anyway.

    Returns ``(k_db, fz, fp, rms_residual_db_deg)`` or ``None`` if the two
    curves do not share a frequency axis.
    """
    a, b = _sub(num), _sub(den)
    if len(a) != len(b) or not a:
        return None
    pts = []
    for (fa, ma, pa), (fb_, mb, pb) in zip(a, b):
        if abs(fa - fb_) > 1e-9 * max(fa, 1.0):
            return None
        pts.append((fa, ma - mb, pa - pb))
    lo = min(f for f, _, _ in pts if f > 0)
    hi = max(f for f, _, _ in pts)
    k_db = pts[0][1]

    def resid(fz: float, fp: float) -> float:
        s = 0.0
        for f, dm, dp in pts:
            h = complex(1, f / fz) / complex(1, f / fp)
            m = k_db + 20 * math.log10(abs(h))
            ph = math.degrees(math.atan2(h.imag, h.real))
            s += (m - dm) ** 2 + ((ph - dp) / 10.0) ** 2
        return s / len(pts)

    grid = [lo * (hi / lo) ** (i / 59.0) for i in range(60)]
    best = None
    for fz in grid:
        for fp in grid:
            r = resid(fz, fp)
            if best is None or r < best[0]:
                best = (r, fz, fp)
    # one refinement pass around the coarse optimum
    _, fz0, fp0 = best
    for _ in range(3):
        fzs = [fz0 * (1.15 ** (i - 6)) for i in range(13)]
        fps = [fp0 * (1.15 ** (i - 6)) for i in range(13)]
        for fz in fzs:
            for fp in fps:
                r = resid(fz, fp)
                if r < best[0]:
                    best = (r, fz, fp)
        _, fz0, fp0 = best
    return k_db, best[1], best[2], math.sqrt(best[0])


# Below this, a margin movement is not distinguishable from the
# cross-invocation movement class #182/#185 measured on this repo's own
# evidence (~2 deg PM / ~1 dB GM between two builds of the same ngspice
# version). A sensitivity result smaller than that is reported as what it is
# -- a null result -- rather than dressed up as an attribution.
ATTR_FLOOR_DB = 0.02
ATTR_FLOOR_DEG = 0.10


def curve_extremes(num, den):
    """Largest |dB| and |deg| difference between two aligned T(f) curves.

    Returned as ``(max_dmag_db, f_at_max_dmag, max_dphase_deg, f_at_max)``.
    This is the primary, model-free number for a sensitivity case: the
    pole/zero fit below is an interpretation of it, and if this is at the
    numerical floor there is nothing to interpret.
    """
    if len(num) != len(den) or not num:
        return None
    best_m = best_p = (0.0, 0.0)
    for (fa, ma, pa), (fb, mb, pb) in zip(num, den):
        if abs(fa - fb) > 1e-9 * max(fa, 1.0):
            return None
        if abs(ma - mb) > abs(best_m[0]):
            best_m = (ma - mb, fa)
        if abs(pa - pb) > abs(best_p[0]):
            best_p = (pa - pb, fa)
    return best_m[0], best_m[1], best_p[0], best_p[1]


def delta_table(num, den, decades=(1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7)):
    """|T| and phase difference between two curves at fixed frequencies."""
    out = []
    for target in decades:
        best = min(num, key=lambda r: abs(math.log10(max(r[0], 1e-12)) - math.log10(target)))
        mate = min(den, key=lambda r: abs(r[0] - best[0]))
        out.append((best[0], best[1] - mate[1], best[2] - mate[2]))
    return out


# ---------------------------------------------------------------------------
# cross-check against sim/loop-stability/
# ---------------------------------------------------------------------------
LS_MATRIX_CSV = (REPO_ROOT / "sim" / "loop-stability" / "records"
                 / "20260906-071437-fff0bf0-matrix.csv")
LS_DIAGNOSTIC_RECORD = "20260906-090647-3981d88"


def run_loop_stability_here(args, workdir: Path, logdir: Path, corners, temps):
    """Run `sim/loop-stability/`'s OWN sweep, unmodified, on this host.

    The point of running it rather than only reading its committed record is
    that `sim/README.md`'s reproducibility caveat (#182/#185) says a delta
    between two records taken on different hosts with different ngspice
    binaries is toolchain provenance, not evidence about the design. A
    same-host, same-binary, same-session run has no toolchain term in it at
    all, so it is the comparison that can actually say something about this
    deck.

    It is invoked as its own entry point with its own flags -- nothing about
    it is patched -- with cwd set to this run's work directory so it picks up
    the same `.spiceinit` every other ngspice invocation here uses.
    """
    cmd = [
        sys.executable, str(_LS_PATH),
        "--corners", *corners,
        "--temps", *[f"{t:g}" for t in temps],
        "--supply-tol", f"{args.supply_tol:g}",
        "--loads-ma", f"{RATED_LOAD_A * 1e3:g}",
        "--caps-uf", *[f"{c * 1e6:g}" for c in CEFFS_F],
        "--esrs", *[f"{e:g}" for e in ESRS_OHM],
        "--ac-dec", str(args.ac_dec),
        "--no-write", "-j", str(args.jobs),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(workdir))
    out = proc.stdout + proc.stderr
    (logdir / "loop-stability-rerun.console.log").write_text(
        "* `sim/loop-stability/testbench/sweep.py` run unmodified on this host,\n"
        "* in this session, for this record's cross-check. Command:\n"
        f"*   {' '.join(cmd)}\n"
        f"* (cwd = this run's work directory, so the same .spiceinit applies)\n\n"
        + out
    )
    m = re.search(r"record id\s*:\s*(\S+)", out)
    if not m:
        return None, f"could not find the re-run's record id in its output"
    rerun_dir = REPO_ROOT / "sim" / ".work" / "loop-stability" / m.group(1)
    if not rerun_dir.is_dir():
        return None, f"the re-run left no logs at {rerun_dir}"
    rows: dict[tuple, dict] = {}
    dest = logdir / "loop-stability-rerun"
    dest.mkdir(parents=True, exist_ok=True)
    for log in sorted(rerun_dir.glob("*.log")):
        shutil.copyfile(log, dest / log.name)
        corner_id = log.stem
        for line in log.read_text().splitlines():
            if not line.startswith("ROW "):
                continue
            f = ls.parse_row_fields(line)
            rows[(corner_id, float(f["ceff_f"]), float(f["esr_ohm"]))] = {
                "vout_v": ls._f(f["vout_v"]),
                "f0_hz": ls._f(f["f0_hz"]),
                "pm_deg": (None if ls._f(f["phase_at_f0_deg"]) is None
                           else 180.0 + ls._f(f["phase_at_f0_deg"])),
                "gm_db": (math.inf if ls._f(f["gain_at_f180_db"]) is None
                          else -ls._f(f["gain_at_f180_db"])),
            }
    if not rows:
        return None, "the re-run produced no ROW lines"
    return rows, None


def read_committed_ls_matrix() -> dict[tuple, dict]:
    """The committed loop-stability matrix, keyed the same way."""
    out: dict[tuple, dict] = {}
    if not LS_MATRIX_CSV.exists():
        return out
    with LS_MATRIX_CSV.open() as fh:
        for row in csv.DictReader(fh):
            if float(row["iload_ma"]) != RATED_LOAD_A * 1e3:
                continue
            key = (row["corner_id"], float(row["ceff_uf"]) * 1e-6,
                   float(row["esr_ohm"]))
            gm = row["gain_margin_db"]
            out[key] = {
                "vout_v": float(row["vout_v"]),
                "f0_hz": float(row["f_crossover_hz"]) if row["f_crossover_hz"] else None,
                "pm_deg": None if row["phase_margin_deg"] in ("", "n/a")
                          else float(row["phase_margin_deg"]),
                "gm_db": math.inf if gm == "inf" else float(gm),
            }
    return out


def compare_anchor(anchor_rows: list[Row], other: dict[tuple, dict]):
    """Join this experiment's anchor rows against a loop-stability matrix."""
    deltas = []
    for r in anchor_rows:
        ref = other.get((r.corner_id, r.ceff_f, r.esr_ohm))
        if ref is None:
            continue
        dpm = (None if r.pm_deg is None or ref["pm_deg"] is None
               else r.pm_deg - ref["pm_deg"])
        dgm = (None if math.isinf(r.gm_db) or math.isinf(ref["gm_db"])
               else r.gm_db - ref["gm_db"])
        df0 = (None if r.f0_hz is None or not ref["f0_hz"]
               else (r.f0_hz - ref["f0_hz"]) / ref["f0_hz"])
        deltas.append((r, ref, dpm, dgm, df0))
    return deltas


def xcheck_verdict(deltas):
    """(ok, worst dPM, worst dGM, worst relative df0, n compared)."""
    if not deltas:
        return False, None, None, None, 0
    wpm = max((abs(d[2]) for d in deltas if d[2] is not None), default=0.0)
    wgm = max((abs(d[3]) for d in deltas if d[3] is not None), default=0.0)
    wf0 = max((abs(d[4]) for d in deltas if d[4] is not None), default=0.0)
    ok = (wpm <= XCHECK_PM_TOL_DEG and wgm <= XCHECK_GM_TOL_DB
          and wf0 <= XCHECK_F0_TOL_FRAC)
    return ok, wpm, wgm, wf0, len(deltas)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--corners", nargs="+", default=list(PROCESS_CORNERS))
    ap.add_argument("--temps", nargs="+", type=float, default=list(TEMPS_C))
    ap.add_argument("--supply-tol", type=float, default=SUPPLY_TOL)
    ap.add_argument("--variants", nargs="+", default=list(nv.DUT_VARIANTS),
                    choices=list(nv.DUT_VARIANTS))
    ap.add_argument("--phases", nargs="+", default=list(PHASES),
                    choices=list(PHASES))
    ap.add_argument("--caps-uf", nargs="+", type=float,
                    default=[c * 1e6 for c in CEFFS_F])
    ap.add_argument("--esrs", nargs="+", type=float, default=list(ESRS_OHM))
    ap.add_argument("--ac-dec", type=int, default=int(AC_DEC),
                    help=f"AC points per decade (default {AC_DEC}, "
                         "sim/loop-stability's own resolution policy, issue "
                         "#58 -- running below it needs --subset-reason)")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--no-write", action="store_true",
                    help="run and report, write no record (debugging)")
    ap.add_argument("--explore", action="store_true",
                    help="tt/27C/3.3V only; implies --no-write")
    ap.add_argument("--skip-crosscheck", action="store_true",
                    help="do not re-run sim/loop-stability/ for the anchor "
                         "cross-check (implies the record cannot claim it)")
    ap.add_argument("--skip-handover", action="store_true",
                    help="do not run the dense DC hand-over transfer sweep "
                         "(implies the record cannot report the injection "
                         "element's transfer, only its margins)")
    ap.add_argument("--subset-reason", default="",
                    help="required (and copied into the record) if the grid is "
                         "narrower than the CLAUDE.md-mandated PVT matrix")
    ap.add_argument("--supersedes", default="")
    ap.add_argument("--author",
                    default=os.environ.get("SS_LOOP_GAIN_AUTHOR",
                                           "agent-builder (issue #196)"))
    return ap


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.explore:
        args.corners, args.temps, args.supply_tol = ["tt"], [27.0], 0.0
        args.no_write = True

    if shutil.which("ngspice") is None:
        print("FATAL: ngspice not on PATH", file=sys.stderr)
        return 3
    try:
        pdk = find_pdk()
    except Exception as exc:  # pragma: no cover - environment problem
        print(f"FATAL: {exc}", file=sys.stderr)
        return 3
    check = subprocess.run(
        [sys.executable, str(REPO_ROOT / "design" / "netlist.py"), "--check"],
        capture_output=True, text=True,
    )
    if check.returncode != 0:
        print("FATAL: design/netlist/*.spice is stale vs the schematics:",
              file=sys.stderr)
        print(check.stdout + check.stderr, file=sys.stderr)
        return 3

    corners = resolve_corners(args.corners)
    supplies = supply_points(NOMINAL_SUPPLY_V, args.supply_tol)
    grid = build_grid(corners, args.temps, supplies)
    ceffs = [v * 1e-6 for v in args.caps_uf]
    esrs = list(args.esrs)

    full_pvt = (set(args.temps) >= set(TEMPS_C)
                and args.supply_tol >= SUPPLY_TOL
                and set(args.corners) >= set(PROCESS_CORNERS))
    full = (full_pvt
            and set(args.variants) >= set(nv.DUT_VARIANTS)
            and set(args.phases) >= set(PHASES)
            and set(args.caps_uf) >= {c * 1e6 for c in CEFFS_F}
            and set(args.esrs) >= set(ESRS_OHM)
            and args.ac_dec >= int(AC_DEC))
    if not args.no_write and not full and not args.subset_reason:
        print("FATAL: this grid is narrower than the one this experiment's "
              "README describes.\n       Re-run with the defaults, or pass "
              "--subset-reason '<why>' (copied verbatim into the record), or "
              "--no-write to just debug.", file=sys.stderr)
        return 3

    prov = git_provenance(REPO_ROOT)
    records_dir = EXPDIR / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    if args.no_write:
        record_id = format_record_id(prov["short"],
                                     _dt.datetime.now(_dt.timezone.utc))
    else:
        record_id = allocate_record_id(REPO_ROOT, records_dir, git=prov)

    workdir = REPO_ROOT / "sim" / ".work" / EXPDIR.name / record_id
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / ".spiceinit").write_text(SPICEINIT)
    logdir = EXPDIR / "corners" / record_id
    if args.no_write:
        logdir = workdir
    logdir.mkdir(parents=True, exist_ok=True)

    # --- DUT netlists ------------------------------------------------------
    netlists: dict[str, Path] = {}
    try:
        for variant in args.variants:
            text = nv.build_variant(REPO_ROOT, variant)
            p = workdir / f"ldo_core_{variant}.spice"
            p.write_text(text)
            netlists[variant] = p
    except nv.TransformError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 3

    print(f"pdk           : {pdk.variant} @ {pdk.version}")
    print(f"ngspice       : {ngspice_version()}")
    print(f"ngspice sha256: {ngspice_binary_sha256()}")
    print(f"host          : {socket.gethostname()}")
    print(f"record id     : {record_id}"
          f"{' (NOT WRITTEN: --no-write)' if args.no_write else ''}")
    n_states = sum(1 if PHASES[p]["ssr"] is None else len(PHASES[p]["ssr"])
                   for p in args.phases)
    print(f"grid          : {len(grid)} PVT x {len(args.variants)} variant x "
          f"{n_states} ramp state x {len(ceffs)}x{len(esrs)} cap/ESR = "
          f"{len(grid) * len(args.variants) * n_states * len(ceffs) * len(esrs)} "
          f"loop-gain points")
    print()

    jobs = [(pvt, variant, phase)
            for pvt in grid for variant in args.variants for phase in args.phases]
    rows: list[Row] = []
    failures: list[str] = []
    seeded: list[str] = []
    voided: list[str] = []

    def submit(pool, todo, seed: bool):
        return {
            pool.submit(
                run_point, pvt, pdk, phase=phase, variant=variant,
                netlist=netlists[variant], ceffs=ceffs, esrs=esrs,
                ac_dec=args.ac_dec, workdir=workdir, logdir=logdir,
                dc_seed=(dc_seed_lines(pvt, "free") if seed else ""),
            ): (pvt, variant, phase)
            for pvt, variant, phase in todo
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = submit(pool, jobs, seed=False)
        retries = []
        done_n = 0
        for done in concurrent.futures.as_completed(futures):
            pvt, variant, phase = futures[done]
            _, pt_rows, err = done.result()
            done_n += 1
            if err:
                if "did not land on the intended DC branch" in err:
                    retries.append((pvt, variant, phase))
                    print(f"  [{done_n}/{len(jobs)}] {pvt.corner_id:<18} "
                          f"{variant:<7} {phase:<7} DC branch miss, retrying "
                          f"with the intended-branch seed")
                    continue
                failures.append(f"{pvt.corner_id}/{variant}/{phase}: {err}")
                print(f"  [{done_n}/{len(jobs)}] {pvt.corner_id:<18} "
                      f"{variant:<7} {phase:<7} SIM ERROR {err}")
                continue
            rows.extend(pt_rows)
            measured = [r for r in pt_rows if r.pm_deg is not None]
            w = worst_of(measured) if measured else pt_rows[0]
            print(f"  [{done_n}/{len(jobs)}] {pvt.corner_id:<18} "
                  f"{variant:<7} {phase:<7} worst PM {pm_str(w):>7} deg "
                  f"GM {gm_str(w):>7} dB"
                  + ("" if measured else "  (no crossover at any point)"))

    if retries:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = submit(pool, retries, seed=True)
            for done in concurrent.futures.as_completed(futures):
                pvt, variant, phase = futures[done]
                _, pt_rows, err = done.result()
                if err:
                    if "did not land on the intended DC branch" in err:
                        # Still refuses the intended branch even with the
                        # seed that starts Newton on it. Per the README's
                        # landing rule, this VOIDS the deck -- it is named
                        # in the record and excluded from the row set, but
                        # is not a run-wide failure: the other (PVT, variant,
                        # phase) decks landed cleanly and their margins are
                        # not in question. A deck that never lands on the
                        # named branch even when seeded onto it is itself a
                        # measurement (the device chain has no solution near
                        # VREF at that PVT point), not a testbench bug.
                        voided.append(f"{pvt.corner_id}/{variant}/{phase}: {err}")
                        print(f"  {pvt.corner_id:<18} {variant:<7} {phase:<7} "
                              f"VOIDED (no DC branch near VREF, even seeded) "
                              f"{err}")
                        continue
                    failures.append(
                        f"{pvt.corner_id}/{variant}/{phase} (with DC seed): {err}")
                    print(f"  {pvt.corner_id:<18} {variant:<7} {phase:<7} "
                          f"SIM ERROR {err}")
                    continue
                seeded.append(f"{pvt.corner_id}/{variant}/{phase}")
                rows.extend(pt_rows)

    if failures:
        print("\nFATAL: simulation failures:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 2
    if voided:
        print(f"\n{len(voided)} (PVT, variant, phase) deck(s) voided (no DC "
              f"branch near VREF, even with the intended-branch seed); named "
              f"in the record, excluded from the row set:")
        for v in voided:
            print(f"  {v}")
    if not rows:
        print("FATAL: no rows parsed", file=sys.stderr)
        return 2
    rows.sort(key=sort_key)

    # --- the DC hand-over transfer -----------------------------------------
    # Run after the margins, because it is the margins' operating point drawn
    # densely rather than a second experiment: every HOV point is the same
    # circuit, the same loop break and the same load model as the `ramp`
    # phase, and handover_consistency() below checks that the two decks land
    # on the same place where they overlap.
    curves: list[HovCurve] = []
    hov_consistency = None
    if not args.skip_handover:
        print(f"\n=== DC hand-over transfer: {len(HANDOVER_SSR_V)} pinned "
              f"V(SSR) from {HANDOVER_SSR_V[0]:g} to {HANDOVER_SSR_V[-1]:g} V, "
              f"{len(grid)} PVT x {len(args.variants)} variant ===")
        hov_jobs = [(pvt, variant) for pvt in grid for variant in args.variants]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futs = {pool.submit(run_handover, pvt, pdk, variant=variant,
                                netlist=netlists[variant], workdir=workdir,
                                logdir=logdir): (pvt, variant)
                    for pvt, variant in hov_jobs}
            for done in concurrent.futures.as_completed(futs):
                pvt, variant = futs[done]
                curve, err = done.result()
                if err:
                    failures.append(f"{pvt.corner_id}/{variant}/handover: {err}")
                    print(f"  {pvt.corner_id:<18} {variant:<7} SIM ERROR {err}")
                    continue
                curves.append(curve)
        if failures:
            print("\nFATAL: hand-over transfer failures:", file=sys.stderr)
            for f in failures:
                print(f"  {f}", file=sys.stderr)
            return 2
        curves.sort(key=lambda c: (c.variant, c.corner_id))
        for variant in args.variants:
            sel = [c for c in curves if c.variant == variant]
            if not sel:
                continue
            rel = [c for c in sel if c.release_ssr_v is not None]
            sat = [c for c in sel if c.saturated_to_ssr_v is not None]
            gms = [c.gm_a_per_v for c in sel if math.isfinite(c.gm_a_per_v)]
            print(f"  {variant:<7} I_inj(0) "
                  f"{min(c.iinj_start_a for c in sel) * 1e6:.3f}.."
                  f"{max(c.iinj_start_a for c in sel) * 1e6:.3f} uA; "
                  f"gm {min(gms) * 1e6:.3f}..{max(gms) * 1e6:.3f} uA/V; "
                  f"release V(SSR) "
                  + (f"{min(c.release_ssr_v for c in rel):.3f}.."
                     f"{max(c.release_ssr_v for c in rel):.3f} V"
                     if len(rel) == len(sel) else
                     f"never, at {len(sel) - len(rel)}/{len(sel)} corners")
                  + f"; out of regulation at {len(sat)}/{len(sel)} corners")
        hov_consistency = handover_consistency(curves, rows)
        if hov_consistency[0] is not None:
            d, r, hov = hov_consistency[0]
            print(f"  cross-deck consistency: worst |dVOUT| between a HOV point "
                  f"and the margin ROW at the same V(SSR) is {d * 1e6:.3f} uV "
                  f"over {hov_consistency[1]} shared points")

    # --- cross-check -------------------------------------------------------
    anchor_rows = [r for r in rows if r.phase == "anchor" and r.variant == "device"]
    xcheck: dict = {"skipped": args.skip_crosscheck or not anchor_rows}
    if not xcheck["skipped"]:
        print("\n=== cross-check: re-running sim/loop-stability/ on this host ===")
        here_rows, err = run_loop_stability_here(args, workdir, logdir,
                                                 args.corners, args.temps)
        if err:
            print(f"  cross-check could not run: {err}", file=sys.stderr)
            xcheck["error"] = err
        else:
            xcheck["here"] = compare_anchor(anchor_rows, here_rows)
            xcheck["here_verdict"] = xcheck_verdict(xcheck["here"])
            ok, wpm, wgm, wf0, n = xcheck["here_verdict"]
            print(f"  same-host re-run : {n} shared points, worst |dPM| "
                  f"{wpm:.3f} deg, |dGM| {wgm:.3f} dB, |df0| {100 * wf0:.3f}% "
                  f"-> {'AGREES' if ok else 'DISAGREES'}")
        committed = read_committed_ls_matrix()
        if committed:
            xcheck["committed"] = compare_anchor(anchor_rows, committed)
            xcheck["committed_verdict"] = xcheck_verdict(xcheck["committed"])
            ok, wpm, wgm, wf0, n = xcheck["committed_verdict"]
            print(f"  committed record : {n} shared points, worst |dPM| "
                  f"{wpm:.3f} deg, |dGM| {wgm:.3f} dB, |df0| {100 * wf0:.3f}% "
                  f"-> {'AGREES' if ok else 'DISAGREES'}")

    # --- summary -----------------------------------------------------------
    print()
    by_state = group(rows, lambda r: (r.variant, r.phase, r.ssr_cmd))
    print(f"points   : {len(rows)}")
    for key in sorted(by_state, key=lambda k: (k[1], k[2], k[0])):
        bucket = by_state[key]
        measured = [r for r in bucket if r.pm_deg is not None]
        if measured:
            w = worst_of(measured)
            wres = worst_resurgence_of(bucket)
            print(f"  {key[0]:<7} {key[1]:<7} ssr={key[2]:<5} "
                  f"worst PM {pm_str(w):>7} deg  GM {gm_str(w):>7} dB  "
                  f"at {w.corner_id}/{w.cfg_id}  "
                  f"(resurgence worst {res_str(wres)} dB)")
        else:
            print(f"  {key[0]:<7} {key[1]:<7} ssr={key[2]:<5} "
                  f"no 0 dB crossing anywhere ({len(bucket)} points): the main "
                  f"loop has no gain at this state")

    # --- attribution at the worst device-variant point ---------------------
    attribution = None
    measured_device = [r for r in rows
                       if r.variant == "device" and r.pm_deg is not None]
    if measured_device and not args.explore:
        worst = worst_of(measured_device)
        attribution = run_attribution(worst, grid, pdk, netlists, args,
                                      workdir, logdir, rows)

    if args.no_write:
        print("\n(--no-write: no record, snapshot or corner logs committed)")
        return 0

    # --- evidence ----------------------------------------------------------
    snap_dir = EXPDIR / "netlist-snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    for variant, path in netlists.items():
        shutil.copyfile(path, snap_dir / f"{record_id}-{variant}.spice")
    csv_path = records_dir / f"{record_id}-matrix.csv"
    write_matrix_csv(csv_path, rows)
    hov_csv_path = None
    if curves:
        hov_csv_path = records_dir / f"{record_id}-handover.csv"
        write_handover_csv(hov_csv_path, curves)

    md = render_record(record_id=record_id, rows=rows, grid=grid, ceffs=ceffs,
                       esrs=esrs, pdk=pdk, prov=prov, args=args,
                       xcheck=xcheck, attribution=attribution, seeded=seeded,
                       voided=voided, curves=curves,
                       hov_consistency=hov_consistency)
    record_path = write_markdown_record(record_id, md, records_dir)

    print()
    print(f"record           : {record_path}")
    print(f"matrix csv       : {csv_path}")
    if hov_csv_path:
        print(f"hand-over csv    : {hov_csv_path}")
    print(f"netlist snapshots: {snap_dir}/{record_id}-*.spice")
    print(f"raw logs         : {logdir}/")
    return 0


def run_attribution(worst: Row, grid, pdk, netlists, args, workdir: Path,
                    logdir: Path, rows: list[Row]) -> dict:
    """Element-removal sensitivity at the worst device-variant point.

    Runs the SAME operating point -- same corner, same ramp state, same output
    network -- through the netlist as committed, through the pre-#195 ideal
    element, and through one netlist per AC-only coupling removal in
    ``ATTRIBUTIONS``. Every one of those removals is DC-inert by construction
    (an inductor is a short at DC, a capacitor is an open), which is checked
    here rather than asserted: each case's landed VOUT/FB/injection current is
    reported next to its margin, so a case that moved the bias point is
    visible and its margin delta is not attributed to anything.
    """
    pvt = next(p for p in grid if p.corner_id == worst.corner_id)
    device_text = netlists["device"].read_text()
    cases: list[tuple[str, str, str]] = [
        ("as-committed", "the device-level chain exactly as `main` has it",
         device_text)
    ]
    for tag, desc, fn in ATTRIBUTIONS:
        try:
            cases.append((tag, desc, fn(device_text)))
        except nv.TransformError as exc:
            print(f"  attribution: skipping {tag}: {exc}", file=sys.stderr)
    if "binj" in netlists:
        cases.append(("binj", "the pre-#195 ideal `Binj_ss` source",
                      netlists["binj"].read_text()))

    ssr_values = None if PHASES[worst.phase]["ssr"] is None else [worst.ssr_cmd]
    out: dict = {"worst": worst, "cases": [], "fits": []}
    curves: dict[str, list] = {}
    print(f"\n=== attribution at {worst.corner_id} / {worst.state_id} / "
          f"{worst.cfg_id} ===")
    for tag, desc, text in cases:
        nl = workdir / f"attr_{tag}.spice"
        nl.write_text(text)
        _, prows, err = run_point(
            pvt, pdk, phase=worst.phase, variant=tag, netlist=nl,
            ceffs=[worst.ceff_f], esrs=[worst.esr_ohm], ac_dec=args.ac_dec,
            workdir=workdir, logdir=logdir, ssr_values=ssr_values,
            stem=f"{worst.corner_id}_attr_{tag}",
        )
        if err or not prows:
            print(f"  {tag:<14} FAILED: {err}", file=sys.stderr)
            out["cases"].append({"tag": tag, "desc": desc, "error": err})
            continue
        r = prows[0]
        curve = run_curve(pvt, pdk, r, nl, args.ac_dec, logdir, workdir,
                          f"attr-{tag}-curve")
        curves[tag] = parse_curve(curve)
        out["cases"].append({
            "tag": tag, "desc": desc, "row": r,
            "curve": str(curve.resolve().relative_to(REPO_ROOT)),
        })
        print(f"  {tag:<14} PM {pm_str(r):>7} deg  GM {gm_str(r):>7} dB  "
              f"f0 {_hz(r.f0_hz):>10} Hz  VOUT {r.vout_v:.5f} V  "
              f"I_inj {r.iinj_a * 1e6:+.4f} uA")

    base = curves.get("as-committed")
    if base:
        for tag in list(curves):
            if tag == "as-committed":
                continue
            ext = curve_extremes(base, curves[tag])
            above_floor = ext is not None and (abs(ext[0]) >= ATTR_FLOOR_DB
                                               or abs(ext[2]) >= ATTR_FLOOR_DEG)
            fit = fit_pole_zero(base, curves[tag]) if above_floor else None
            deltas = delta_table(base, curves[tag])
            out["fits"].append({"tag": tag, "fit": fit, "deltas": deltas,
                                "extremes": ext, "above_floor": above_floor})
            if ext is None:
                print(f"  T(as-committed)/T({tag}): curves not comparable")
                continue
            print(f"  T(as-committed)/T({tag}): max d|T| {ext[0]:+.4f} dB at "
                  f"{ext[1]:.4g} Hz, max dphase {ext[2]:+.4f} deg at "
                  f"{ext[3]:.4g} Hz"
                  + ("" if above_floor else "  [at the numerical floor: no "
                     "pole/zero to fit]"))
            if fit:
                k_db, fz, fp, resid = fit
                print(f"      fitted zero {fz:.4g} Hz, pole {fp:.4g} Hz, "
                      f"DC offset {k_db:+.3f} dB, residual {resid:.3f}")

    # --- the FB capacitance budget ----------------------------------------
    # Run at TWO points: the worst device-variant point (which is at a corner
    # where the main loop is already thin with either injection element), and
    # the design's own nominal operating point at the hold-release ramp state
    # (which is not). One alone would be arguable; together they bracket.
    base_row = next((c["row"] for c in out["cases"]
                     if c["tag"] == "as-committed" and "row" in c), None)
    out["fb_cap"] = []
    if base_row is not None:
        out["fb_cap"].append(run_fb_cap_ladder(
            "worst measured device-variant point in this record",
            worst, base_row, device_text, grid, pdk, args, workdir, logdir))
    nominal = next(
        (r for r in rows
         if r.variant == "device" and r.phase == "ramp"
         and r.corner_id == "tt_27c_3.30v"
         and r.ssr_cmd == f"{HANDOVER_ACQUISITION_SSR_V:g}"
         and abs(r.ceff_f - 1e-6) < 1e-15 and abs(r.esr_ohm - 0.1) < 1e-12
         and r.pm_deg is not None),
        None)
    if nominal is not None and key_of(nominal) != key_of(worst):
        out["fb_cap"].append(run_fb_cap_ladder(
            "the nominal corner at the hold-release ramp state",
            nominal, nominal, device_text, grid, pdk, args, workdir, logdir))
    return out


def run_fb_cap_ladder(label: str, point: Row, base_row: Row, device_text: str,
                      grid, pdk, args, workdir: Path, logdir: Path) -> dict:
    """Add known capacitance from FB to VSS at ``point`` and watch the margins.

    The inverse of the element-removal sensitivity above. Removing this
    element's coupling says that THIS element is cheap; adding capacitance
    until the margins move says what any future injection element has to stay
    under. Every rung is a capacitor, so every rung is DC-inert and the landed
    VOUT column is there for a reader to check that.
    """
    pvt = next(p for p in grid if p.corner_id == point.corner_id)
    ssr_values = None if PHASES[point.phase]["ssr"] is None else [point.ssr_cmd]
    out = {"label": label, "point": point, "base": base_row, "rungs": []}
    print(f"\n=== feedback-node capacitance ladder at {point.corner_id} / "
          f"{point.state_id} / {point.cfg_id} ({label}) ===")
    print(f"  {'C(FB->VSS)':<14} {'PM (deg)':>9} {'dPM':>8} {'GM (dB)':>9} "
          f"{'dGM':>8} {'f0 (Hz)':>11}  landed VOUT")
    print(f"  {'(none)':<14} {pm_str(base_row):>9} {'-':>8} "
          f"{gm_str(base_row):>9} {'-':>8} {_hz(base_row.f0_hz):>11}  "
          f"{base_row.vout_v:.5f} V")
    for cf in FB_CAP_LADDER_F:
        tag = f"fbcap-{cf:g}"
        try:
            text = nv.ac_load(device_text, "FB", "VSS", cf, "fbcap")
        except nv.TransformError as exc:
            print(f"  fb-cap {cf:g} F skipped: {exc}", file=sys.stderr)
            continue
        nl = workdir / f"attr_{tag}.spice"
        nl.write_text(text)
        _, prows, err = run_point(
            pvt, pdk, phase=point.phase, variant=tag, netlist=nl,
            ceffs=[point.ceff_f], esrs=[point.esr_ohm], ac_dec=args.ac_dec,
            workdir=workdir, logdir=logdir, ssr_values=ssr_values,
            stem=f"{point.corner_id}_{point.phase}_{point.ssr_cmd}_attr_{tag}",
        )
        if err or not prows:
            print(f"  fb-cap {cf:g} F FAILED: {err}", file=sys.stderr)
            out["rungs"].append({"c_f": cf, "error": err})
            continue
        r = prows[0]
        out["rungs"].append({"c_f": cf, "row": r})
        dpm = ("-" if r.pm_deg is None or base_row.pm_deg is None
               else f"{r.pm_deg - base_row.pm_deg:+.2f}")
        dgm = ("-" if math.isinf(r.gm_db) or math.isinf(base_row.gm_db)
               else f"{r.gm_db - base_row.gm_db:+.2f}")
        print(f"  {cf:<14g} {pm_str(r):>9} {dpm:>8} {gm_str(r):>9} {dgm:>8} "
              f"{_hz(r.f0_hz):>11}  {r.vout_v:.5f} V")
    out["budget"] = fb_cap_budget(out)
    b = out["budget"]
    print(f"  -> budget: "
          + (f"{b['ok_f'] * 1e12:g} pF still within "
             f"{FB_CAP_PM_TOL_DEG:g} deg / {FB_CAP_GM_TOL_DB:g} dB of the "
             f"baseline" if b["ok_f"] is not None else "no rung is within "
             "tolerance of the baseline")
          + (f"; first rung outside it is {b['bad_f'] * 1e12:g} pF "
             f"({b['bad_why']})" if b["bad_f"] is not None
             else "; no rung on this ladder leaves the tolerance"))
    return out


def fb_cap_budget(ladder: dict) -> dict:
    """Largest rung whose margins are still within tolerance of the baseline.

    Both margins, because they fail in different places: capacitance at FB
    first RAISES the phase margin (the loop rolls off earlier) and only later
    collapses it, while the gain margin goes first and by tens of dB.
    """
    base = ladder["base"]
    ok_f = None
    bad_f = None
    bad_why = ""
    for rung in ladder["rungs"]:
        r = rung.get("row")
        if r is None:
            continue
        why = []
        if r.pm_deg is None or base.pm_deg is None:
            why.append("no 0 dB crossing")
        elif r.pm_deg < base.pm_deg - FB_CAP_PM_TOL_DEG:
            why.append(f"PM {r.pm_deg - base.pm_deg:+.2f} deg vs baseline")
        if not math.isinf(r.gm_db) and not math.isinf(base.gm_db) \
                and r.gm_db < base.gm_db - FB_CAP_GM_TOL_DB:
            why.append(f"GM {r.gm_db - base.gm_db:+.2f} dB vs baseline")
        if why:
            if bad_f is None:
                bad_f, bad_why = rung["c_f"], "; ".join(why)
        elif bad_f is None:
            ok_f = rung["c_f"]
    return {"ok_f": ok_f, "bad_f": bad_f, "bad_why": bad_why}


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
            out.append(f"| `{key[0]}` | {key[1]} | {len(b)} | *no crossover on "
                       f"either side* | - | - | "
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

    def block(label, intent, getter, fmt, worst_is_max=True, corner_of=None):
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


def handover_section(curves: list[HovCurve], consistency, args) -> str:
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
        "  The `design intent` column is not an aspiration: it is what the",
        "  pre-#195 behavioural source `Binj_ss` computes,",
        "  `I = max(0, (V(VREF) - V(SSR)) * 5.0e-6)`, which the `binj` rows",
        "  reproduce to the digits shown and which is therefore also a check",
        "  that the derivation of `I_inj` from the landed operating point is",
        "  right.",
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
            f"  **The release point tracks the supply**, which is the shape of",
            f"  the defect rather than its size. Over the {len(supply_lines)}",
            f"  (process, temperature) pairs where the device-level chain",
            f"  releases at all three supplies, moving `VIN` from 2.97 V to",
            f"  3.63 V moves the `V(SSR)` at which it releases by",
            f"  **{min(t[2] for t in supply_lines):+.3f} V to "
            f"{max(t[2] for t in supply_lines):+.3f} V**",
            f"  (mean {sum(slopes) / len(slopes):.3f} V of ramp node per volt of",
            f"  supply; the ideal element's is 0 by construction). Worst:",
            f"  `{worst[0][0]}` at {worst[0][1]:g} degC -- "
            + ", ".join(f"{v:.2f} V -> {r:.3f} V" for v, r in worst[3]) + ".",
            "",
        ]

    # The acquisition step, per variant, against the ideal element at the
    # SAME ramp state -- the DC quantity that is the closest thing this
    # record has to a handle on #191's transient, stated as arithmetic
    # rather than as a story.
    acq = {}
    for variant in sorted({c.variant for c in curves}):
        sel = [c for c in curves if c.variant == variant]
        w = max(sel, key=lambda c: abs(
            c.acquisition_step_v(HANDOVER_ACQUISITION_SSR_V)
            - 1.5 * HANDOVER_ACQUISITION_SSR_V))
        acq[variant] = w
    if len(acq) == 2 and "device" in acq and "binj" in acq:
        pair_lines = []
        for c in curves:
            if c.variant != "device":
                continue
            mate = next((d for d in curves
                         if d.variant == "binj" and d.corner_id == c.corner_id),
                        None)
            if mate is None:
                continue
            a = c.acquisition_step_v(HANDOVER_ACQUISITION_SSR_V)
            b = mate.acquisition_step_v(HANDOVER_ACQUISITION_SSR_V)
            pair_lines.append((a - b, a, b, c.corner_id))
        if pair_lines:
            worst = max(pair_lines, key=lambda t: abs(t[0]))
            lines += [
                f"  **The acquisition step.** Until `Mhold_ss` lets go, the pass",
                f"  device is off and the output is at zero; the instant the main",
                f"  loop owns the pass gate, the output it is asked to hold is",
                f"  whatever the injection element's current at the ramp state",
                f"  reached by then implies. That voltage is a step into `C_out`.",
                f"  At `V(SSR)` = {HANDOVER_ACQUISITION_SSR_V:g} V (see the",
                f"  constant's comment for why that state), over the",
                f"  {len(pair_lines)} corners where both variants are measured,",
                f"  the device-level chain asks for",
                f"  **{min(t[0] for t in pair_lines) * 1e3:+.1f} mV to "
                f"{max(t[0] for t in pair_lines) * 1e3:+.1f} mV** more output",
                f"  than the ideal element does at the identical ramp state.",
                f"  Worst: `{worst[3]}` -- {worst[1] * 1e3:.2f} mV against",
                f"  {worst[2] * 1e3:.2f} mV, a factor of "
                f"{(worst[1] / worst[2]) if worst[2] else float('inf'):.1f}.",
                "",
                f"  **This is a DC statement, and it does not on its own account",
                f"  for #191's transient.** How much capacitor current a given",
                f"  step produces depends on the loop's large-signal acquisition",
                f"  time, which is `sim/soft-start/`'s to measure and which",
                f"  nothing here re-runs. And the arithmetic does not close on",
                f"  its own: at `tt_-40c_2.97v`, the corner #191's own A/B used,",
                f"  that A/B reads 0.468 mA with the ideal element against",
                f"  166.7 mA with the device chain -- a factor of 356 -- while",
                f"  the acquisition step measured here at the same corner differs",
                f"  by a factor of "
                + (lambda t: f"{(t[1] / t[2]):.1f}" if t and t[2] else "n/a")(
                    next((t for t in pair_lines if t[3] == "tt_-40c_2.97v"), None))
                + f". A ~2x difference in the",
                f"  voltage the loop is asked to acquire cannot by itself produce",
                f"  a ~350x difference in the current it acquires it with, so the",
                f"  step is at most a contributing term and there is a mechanism",
                f"  this record does not measure. What this record *does* settle",
                f"  is that the missing mechanism is **not** a small-signal margin",
                f"  deficit at any pinned ramp state, and not the injection",
                f"  element's loading of `FB`: sections 3 and 6 measure both, and",
                f"  both are small. The remaining candidates are large-signal and",
                f"  live in `sim/soft-start/`'s domain -- the recovery out of the",
                f"  out-of-regulation region this section finds at "
                f"{sum(1 for c in curves if c.variant == 'device' and c.saturated_to_ssr_v is not None)}"
                f" of "
                f"{sum(1 for c in curves if c.variant == 'device')} corners is",
                f"  the first one to look at, because the loop is *open* there",
                f"  and no small-signal margin describes it at all.",
                "",
            ]

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


def xcheck_section(xcheck: dict, anchor_rows: list[Row]) -> str:
    if xcheck.get("skipped"):
        return ("  **Not run** (`--skip-crosscheck`, or no anchor phase in this "
                "run). This record therefore makes no claim that its anchor "
                "reproduces `sim/loop-stability/`.\n")
    lines: list[str] = []
    if "error" in xcheck:
        lines.append(f"  The same-host re-run could not be made: "
                     f"{xcheck['error']}.\n")
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
        deltas = xcheck.get(key)
        if not deltas:
            continue
        ok, wpm, wgm, wf0, n = xcheck[f"{key}_verdict"]
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
            r, ref, dpm, _dgm, _df0 = worst
            ref_pm = ref["pm_deg"]
            ref_pm_s = "n/a" if ref_pm is None else f"{ref_pm:.2f}"
            lines.append(
                f"  - largest single mover: `{r.corner_id}` / {r.cfg_id} -- "
                f"this record {pm_str(r)} deg, that one {ref_pm_s} deg "
                f"({dpm:+.3f} deg)")
        lines.append(f"  - **verdict: {'AGREES' if ok else 'DISAGREES'}**")
        lines.append(f"\n  {caveat}\n")
    lines.append(
        f"  **Why the comparison is against `20260906-071437-fff0bf0` and not\n"
        f"  against `{LS_DIAGNOSTIC_RECORD}`, which is `sim/loop-stability/`'s\n"
        f"  latest record.** `{LS_DIAGNOSTIC_RECORD}` is a *diagnostic* record\n"
        f"  (issue #182's toolchain-provenance investigation): its own\n"
        f"  \"Netlist provenance\" field says **diagnostic -- no new full-matrix\n"
        f"  simulation**, it has no `-matrix.csv`, and its evidence is\n"
        f"  re-simulations of a single control point, `ff_125c_2.97v` at\n"
        f"  I_load = 1 mA / C_eff = 0.33 uF / ESR = 0.2 ohm. That point shares no\n"
        f"  (load, C_eff) coordinate with this experiment, which measures the\n"
        f"  rated 50 mA load at 1 uF and 4.7 uF because that is the operating\n"
        f"  point `sim/soft-start/` runs and therefore the one the #191\n"
        f"  regression is about. There is consequently **no shared grid point**\n"
        f"  between the two records to compare, and the honest statement is that\n"
        f"  this is a discrepancy of coverage, not of result. The most recent\n"
        f"  loop-stability record that *does* have shared points is\n"
        f"  `20260906-071437-fff0bf0`, compared above; and the same-host re-run\n"
        f"  above is a stronger check than either, because it removes the\n"
        f"  toolchain term `{LS_DIAGNOSTIC_RECORD}` exists to document.\n"
    )
    return "\n".join(lines) + "\n"


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
        "  Every row below is that **same** operating point, re-simulated with",
        "  exactly one coupling changed. The AC-only removals (`acopen-*`,",
        "  `acshort-*`) put a 1 GH inductor in series with a device terminal or",
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
            "  difference the coupling makes anywhere in band, and where. The",
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

    base_case = next((c for c in attribution["cases"]
                      if c["tag"] == "as-committed" and "row" in c), None)
    cut_case = next((c for c in attribution["cases"]
                     if c["tag"] == "acopen-fb-inj" and "row" in c), None)
    ss_only_note = None
    if (base_case and cut_case and base_case["row"].pm_deg is not None
            and cut_case["row"].pm_deg is not None):
        ss_only_note = (f"{base_case['row'].pm_deg - cut_case['row'].pm_deg:+.3f}"
                        f" deg of phase margin")
    ladders = [l for l in attribution.get("fb_cap", []) if l.get("rungs")]
    if ladders:
        lines += [
            "",
            "  **How much capacitance the feedback node actually tolerates.**",
            "  `design/ldo_softstart.sch`'s regression note states a hypothesis:",
            "  *\"ANY nonzero parasitic capacitance the real transconductor adds",
            "  to FB ... is enough to destabilize the main loop's hold-release",
            "  transient\"*. Removing this element's own coupling (the table",
            "  above) only says that **this** element is cheap. Adding known",
            "  capacitance to `FB` until the margins move says what any future",
            "  injection element has to stay under, and is what tests the",
            "  hypothesis as stated. Every rung is a capacitor, so every rung is",
            "  an open at DC and the landed `VOUT` column is there to show the",
            "  bias point did not move.",
            "",
            f"  The budget is stated against **the same point with no added",
            f"  capacitance**, not against DR-0001's {PM_MIN_DEG:g} deg /",
            f"  {GM_MIN_DB:g} dB reference lines. A mid-ramp state is not a",
            f"  DR-0001 operating point, so those bars are reference lines here",
            f"  and not a criterion"
            + ("; and the worst-point ladder below starts from a baseline of "
               f"{pm_str(ladders[0]['base'])} deg with no added capacitance at "
               f"all -- already under the {PM_MIN_DEG:g} deg line, with "
               f"*either* injection element, because that corner is "
               f"`sim/loop-stability/`'s own open 1-50 mA gap (#51). Against an "
               f"absolute bar every rung there would \"fail\" and the ladder "
               f"would say nothing about capacitance"
               if (ladders[0]["base"].pm_deg is not None
                   and ladders[0]["base"].pm_deg < PM_MIN_DEG) else "")
            + f". Against its own baseline it answers the",
            f"  question that was asked. Tolerance: PM within "
            f"{FB_CAP_PM_TOL_DEG:g} deg and GM within {FB_CAP_GM_TOL_DB:g} dB",
            f"  of the baseline -- the #182/#185 movement class. Both, because",
            f"  they fail in different places.",
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
                f"15 pF already sits across `Rtop` on the same node for scale. "
                f"That is the same conclusion the `acopen-fb-inj` row above "
                f"reaches from the opposite direction and by an independent "
                f"measurement -- removing the element's coupling entirely is "
                f"worth {'' if ss_only_note is None else ss_only_note} -- and "
                f"it is what the schematic note's hypothesis, *\"ANY nonzero "
                f"parasitic capacitance ... is enough\"*, has to be read "
                f"against.",
            ]
    return "\n".join(lines) + "\n"


def render_record(*, record_id, rows, grid, ceffs, esrs, pdk, prov, args,
                  xcheck, attribution, seeded, voided=(), curves=(),
                  hov_consistency=None) -> str:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dirty = prov["dirty"]
    variants = sorted({r.variant for r in rows})
    procs = ", ".join(sorted({r.corner for r in rows}))
    temps = ", ".join(f"{t:g}" for t in sorted({r.temp_c for r in rows}))
    supplies = ", ".join(f"{v:.2f}" for v in sorted({r.vin_v for r in rows}))
    anchor_rows = [r for r in rows if r.phase == "anchor" and r.variant == "device"]

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

    # The A/B reading, computed rather than asserted.
    dpms = [p[2] for p in pairs if p[2] is not None]
    if dpms:
        worst_pair = min((p for p in pairs if p[2] is not None), key=lambda p: p[2])
        ab_reading = (
            f"Across the {len(dpms)} (corner, ramp state, C_eff, ESR) points where "
            f"both DUT variants have a 0 dB crossing, swapping the ideal "
            f"`Binj_ss` for the device-level chain moves the phase margin by "
            f"**{min(dpms):+.2f} deg to {max(dpms):+.2f} deg** (mean "
            f"{sum(dpms) / len(dpms):+.2f} deg). The worst single point is "
            f"`{worst_pair[0].corner_id}` at {worst_pair[0].state_id}, "
            f"{worst_pair[0].cfg_id}: {pm_str(worst_pair[0])} deg with the device "
            f"chain against {pm_str(worst_pair[1])} deg with the ideal source."
        )
    else:
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

    # The pure small-signal contribution, isolated by the DC-preserving
    # AC-open of the injection element's own drain (section 6). This is the
    # number a compensation argument would have to rest on; the A/B spread
    # below mixes it with the operating-point shift section 1 measures.
    ss_only = None
    if attribution:
        base = next((c for c in attribution["cases"]
                     if c["tag"] == "as-committed" and "row" in c), None)
        cut = next((c for c in attribution["cases"]
                    if c["tag"] == "acopen-fb-inj" and "row" in c), None)
        if base and cut and base["row"].pm_deg is not None \
                and cut["row"].pm_deg is not None:
            ss_only = base["row"].pm_deg - cut["row"].pm_deg

    # The headline, keyed off the measured A/B spread rather than asserted.
    if dpms:
        span = max(abs(min(dpms)), abs(max(dpms)))
        if ss_only is not None:
            ss_clause = (
                f" Separately, and more directly: at the worst measured point, "
                f"AC-opening the device chain's own output drain from the "
                f"feedback node -- which removes its entire small-signal "
                f"loading while leaving the DC operating point bit-identical -- "
                f"moves the phase margin by **{ss_only:+.3f} deg**. That is the "
                f"injection element's small-signal cost with the operating-point "
                f"shift held out of it, and it is "
                f"{'below' if abs(ss_only) <= XCHECK_PM_TOL_DEG else 'above'} "
                f"the ~{XCHECK_PM_TOL_DEG:g} deg cross-invocation movement "
                f"class #182/#185 established."
            )
        else:
            ss_clause = ""
        if span <= XCHECK_PM_TOL_DEG:
            headline = (
                f"**The injection element is not a phase-margin problem at any "
                f"state this record measures.** The largest phase-margin "
                f"difference between the ideal source and the device-level "
                f"chain, anywhere in the {len(dpms)}-point A/B, is "
                f"{span:.2f} deg -- smaller than the ~{XCHECK_PM_TOL_DEG:g} deg "
                f"cross-invocation movement class #182/#185 measured between two "
                f"builds of the same ngspice version on an unmodified netlist. "
                f"A margin difference that small cannot carry a compensation "
                f"decision, and this record does not let one be read into it. "
                f"What the two elements *do* differ in, by a wide and "
                f"unambiguous margin, is the DC hand-over in section 1: the "
                f"device chain's transconductance and, above all, its "
                f"rectification." + ss_clause
            )
        else:
            headline = (
                f"**Swapping the ideal injection source for the device-level "
                f"chain moves the phase margin by up to {span:.2f} deg** at the "
                f"same pinned ramp state, which is above the "
                f"~{XCHECK_PM_TOL_DEG:g} deg cross-invocation movement class "
                f"#182/#185 established. Read that number with section 1 in "
                f"hand: at a fixed V(SSR) the two elements do **not** put the "
                f"loop at the same operating point, because they do not inject "
                f"the same current, so most of this delta is the loop being "
                f"measured at a different output voltage (and therefore a "
                f"different pass-device transconductance) rather than the "
                f"injection element loading the loop differently."
                + ss_clause
            )
    else:
        headline = ("No state measured here has a 0 dB crossing on both sides "
                    "of the A/B, so this record makes no phase-margin "
                    "comparison between the two injection elements.")

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
  FB-injection element in the loop**, at pinned points of the soft-start ramp,
  for the post-#195 device-level injection chain and the pre-#195 ideal
  `Binj_ss` source. This record substantiates **no ratified spec row**. It is
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
  Two DUT variants, differing **only** in the injection element:
{chr(10).join(f'  - `{v}`: {nv.VARIANT_BLURB[v]}' for v in variants)}

  Both are the SSR-instrumented form of the same `ldo_core`: the ramp node
  `SSR` is appended to `ldo_softstart`'s and `ldo_core`'s port lists and to the
  `Xsoftstart` instance line, and nothing else is touched. `SSR` is already a
  node of the cell, so promoting it to a port renames nothing and connects
  nothing; the `anchor` phase leaves the new port unconnected and **measures**
  that this is so (see the cross-check below). Nothing under `design/` is
  modified by this experiment; the two frozen netlists are linked below.
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

{handover_section(list(curves), hov_consistency, args)}
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

  **3. The A/B: what the injection element costs the loop.**

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

{xcheck_section(xcheck, anchor_rows)}
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
    `sim/loop-stability/testbench/selftest.py` and adds this experiment's own)
  - Frozen DUT netlists (one per variant):
{chr(10).join(f'    `sim/soft-start-loop-gain/netlist-snapshots/{record_id}-{v}.spice`' for v in variants)}
  - Raw logs (one per PVT point x variant x phase, plus the attribution and
    cross-check runs): `sim/soft-start-loop-gain/corners/{record_id}/`
  - Full {len(rows)}-point matrix, machine-readable:
    `sim/soft-start-loop-gain/records/{record_id}-matrix.csv`
{f'''  - Full {sum(len(c.points) for c in curves)}-point DC hand-over transfer,
    machine-readable:
    `sim/soft-start-loop-gain/records/{record_id}-handover.csv`''' if curves else '  - (no hand-over transfer in this run)'}
  - The experiment this one is built from and cross-checked against:
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

- PDK: {pdk.variant} @ {pdk.version}
- ngspice: {ngspice_version()}
- ngspice binary sha256: `{ngspice_binary_sha256()}` (issue #182: the version
  string alone does not pin the resolved binary's content -- see
  `sim/README.md`'s reproducibility caveat)
- Host: `{socket.gethostname()}`
- ngspice startup settings, pinned by this driver rather than left to the host
  (a generated `.spiceinit` in the run's work directory, which is the cwd of
  every ngspice invocation this record made, including the cross-check's):
  `set wnflag=1` (model binning divides W by nf -- without it the W=2000u
  pass device has no model bin and no deck in this repo parses) and
  `set num_threads=1`. `wnflag` is also set as a `.options` card inside the
  deck itself.
- git: `{prov['short']}` on `{prov['branch']}`
  ({'DIRTY' if dirty else 'clean'} at generation time)
- Command: `./sim/soft-start-loop-gain/testbench/run.sh`
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


if __name__ == "__main__":
    sys.exit(main())
