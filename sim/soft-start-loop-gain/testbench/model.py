#!/usr/bin/env python3
"""The soft-start loop-gain experiment's shared model layer (issue #608).

The value types, field lists and parsers, operating-point definitions and
tolerances that BOTH halves of this experiment need -- ``sweep.py`` (the
driver) and ``record.py`` (the evidence renderer) -- split out of
``sweep.py`` so the record half could move without either sibling importing
the other: this module imports nothing from them, they each load it, and
the dependency stays one-way (driver -> renderer <- model).

Loaded by path under the unique name ``ss_loop_gain_model``, never a bare
``import model``: a driver that is itself loaded by filesystem path loads
its siblings by path under unique module names -- the rule
``sim/tests/test_sibling_import_names.py`` enforces and ``klt_run.py`` /
``netlist_variants.py`` beside this file already follow (issues #451/#693,
#700). A consumer finding it already in ``sys.modules`` MUST reuse that
copy rather than re-executing the file: ``harness.loader.load_script``
re-runs it when called twice, and two executions mean two ``Row`` classes
that ``isinstance`` cannot tell apart -- the silent-wrong-object failure
that rule exists to prevent.

Nothing here runs a simulation or touches a file: constants and pure logic
only, all of it exercised simulator-free by
``sim/tests/test_soft_start_loop_gain.py`` (which reaches these names as
``sweep.<name>`` re-exports).
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness import loop_margin  # noqa: E402,F401  (Row subclasses loop_margin.Row below)
from harness.loop_margin import (  # noqa: E402
    VOUT_NOM_V,
    VOUT_TOL_FRAC,
    fmt_esr,
    fmt_uf,
)
from harness.report import parse_row_fields as _harness_parse_row_fields  # noqa: E402

VREF_V = 1.2                          # the deck's reference source

# The load models `PHASES` below refers to. The grid axes that pair
# with them (CEFFS_F / ESRS_OHM) stay in `sweep.py`: only the driver
# and its CLI read those.
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
            "with its records. 1.8 V is added here as a margin past `VREF` "
            "where `Binj_ss`'s injection has fully decayed away in BOTH "
            "variants (see the DC transfer in the record) -- pre-#231, when "
            "`device` was the post-#195 device-level chain, this was the "
            "point where specifically that chain's decay finished, later "
            "than the ideal source's at 1.25 V; post-#231 both variants "
            "release at the same `V(SSR)` and 1.8 V is kept only as a "
            "conservative check that neither variant's injection has crept "
            "back up"
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
# measurement -- which `handover_consistency()` in `sweep.py` checks rather
# than assumes.
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
# (both variants inject through it post-#231; see #239) produces anywhere in
# this grid where it is IN regulation, and well below where either variant's
# FB lands once it saturates, so nothing sits near the threshold.
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
    1.8: "(d) VREF + 600 mV, a conservative margin past BOTH variants' "
         "hand-over (pre-#231 this was specifically past the device-level "
         "chain's own, later, hand-over -- see `PHASES['sink']['why']`)",
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
# lands, the cross-check it exists to feed is meaningless. VOUT_TOL_FRAC comes
# from harness.loop_margin (the same object loop-stability reads).

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

# ---------------------------------------------------------------------------
# one measured point
# ---------------------------------------------------------------------------
def _iinj_a(fb_v: float, vout_v: float) -> float:
    """KCL at FB: the DC current the injection element delivers into it.

    Derived, not measured, and exact: at DC the only branches on the
    feedback node are the two divider resistors (`Rtop` 300k from VOUT,
    `Rbot` 600k to VSS -- `XCff` across `Rtop` carries no DC current), the
    error amp's gate (no DC current), the injection element's drain and
    `Mpre_b_ss`'s drain (off while enabled). So KCL at FB gives

        I_inj = V(FB)/Rbot - (V(VOUT) - V(FB))/Rtop

    which is the same quantity for both DUT variants without either deck
    having to know which element is in it. This is the number the hand-over
    is actually about.

    It lives here, at module level, because `Row` (the swept AC points) and
    `HovPoint` (the pinned DC hand-over points) both need it and it is one
    statement about the node's branches, not two: a divider change must not
    be able to reach one of them and not the other.
    """
    return fb_v / 600e3 - (vout_v - fb_v) / 300e3

@dataclass
class Row(loop_margin.Row):
    """One (PVT, variant, phase, SSR, C_eff, ESR) loop-gain point.

    Subclasses the harness's loop-margin Row -- the same class
    `sim/loop-stability/`'s rows are -- so `pm_deg`, `gm_db`, `passes` and
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

        `_iinj_a()`, which states the derivation; `HovPoint.iinj_a` is the
        same call, so the two cannot drift apart.
        """
        return _iinj_a(self.fb_v, self.vout_v)

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
    """``ROW k=v k=v ...`` -> dict, against this module's own ``ROW_FIELDS``.

    The parsing/validation itself is ``harness.report.parse_row_fields()``,
    shared with ``sim/loop-stability/testbench/sweep.py`` so the two
    experiments' strictness (missing/unknown keys are a hard error, never a
    default) cannot drift apart. This wrapper just binds it to this
    experiment's own field list.
    """
    return _harness_parse_row_fields(line, ROW_FIELDS)

# --- the DC hand-over transfer's value types --------------------------------
HOV_FIELDS = ("ssr_cmd", "ssr_v", "fb_v", "vout_v", "pg_v", "erramp_v", "isup_a")

# RETIRED (issue #239): this set used to have an optional `gmsum_v` field,
# read only for the `device` variant's `GMSUM` mirror node -- the post-#195
# device-level Mgm* transconductor chain issue #231 reverted. There is
# nothing left in `ldo_softstart` to name: an actual PDK run
# (`./sim/soft-start-loop-gain/testbench/sweep.py --variants device`,
# tt/27C/3.3V) confirmed ngspice does NOT hard-error on the resulting
# `.let gmsum_dc = v(xdut.xsoftstart.gmsum)` against the undefined node --
# it prints a per-point `Error: RHS "v(...)" invalid` / `Error: &gmsum_dc: no
# such variable.` to the deck's own log (94 times over the 97-point sweep),
# exits 0, and the echoed field silently comes out empty (`gmsum_v=` with no
# value), which `_f()` then folds into `None` -- i.e. this bug was BOTH
# non-fatal AND invisible in the record, the same "floating/NaN, not a hard
# failure" shape issue #234 found for the margin deck's `acshort-gmsum` row.
# `sim/harness/runner.py`'s `FATAL_LOG_PATTERNS` also does not catch it: it
# matches "no such vector", not ngspice's actual wording here, "no such
# variable" -- see issue #239's follow-up for that harness-wide gap. `GMSUM`
# is not referenced anywhere below any more.


def parse_hov_fields(line: str) -> dict[str, str]:
    """``HOV k=v k=v ...`` -> dict, with the margin parser's strictness.

    Every field is required and an unknown one is an error rather than
    something to ignore. Like `parse_row_fields()` above, the parsing and
    that strictness are ``harness.report.parse_row_fields()`` itself rather
    than a second statement of them, so a hardening of the shared parser
    reaches the hand-over deck's lines too; this wrapper only binds it to
    this line kind's field list and name.
    """
    return _harness_parse_row_fields(line, HOV_FIELDS, tag="HOV")

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

    @property
    def iinj_a(self) -> float:
        """The current the injection element delivers into FB.

        Exactly `Row.iinj_a` -- the same `_iinj_a()` call, not a restatement
        of it. It stays exact when the loop is out of regulation, because it
        is a statement about the node's branches and not about the loop
        being closed.
        """
        return _iinj_a(self.fb_v, self.vout_v)

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

# --- keying/grouping helpers shared by the driver and the record ------------
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

# Below this, a margin movement is not distinguishable from the
# cross-invocation movement class #182/#185 measured on this repo's own
# evidence (~2 deg PM / ~1 dB GM between two builds of the same ngspice
# version). A sensitivity result smaller than that is reported as what it is
# -- a null result -- rather than dressed up as an attribution.
ATTR_FLOOR_DB = 0.02
ATTR_FLOOR_DEG = 0.10

LS_DIAGNOSTIC_RECORD = "20260906-090647-3981d88"
