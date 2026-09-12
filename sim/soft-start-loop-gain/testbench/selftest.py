#!/usr/bin/env python3
"""Prove this experiment's machinery before trusting anything it reports.

Two halves, in this order:

1. **The loop-gain extraction itself** -- delegated, unmodified, to
   ``sim/loop-stability/testbench/selftest.py``. That is not laziness: this
   deck uses that deck's Tian dual-injection arithmetic, its
   ``meas``-based margin extraction and its DR-0008 resurgence idiom
   character for character, against loops whose loop gain is known in closed
   form. Running its known-answer test rather than re-implementing one keeps
   the two experiments' extraction provably the same thing, which is the same
   reason ``sweep.py`` imports its constants instead of copying them. If that
   selftest fails, this one fails: a margin from an unvalidated extraction is
   worse than no margin.

2. **This experiment's own additions**, which that selftest knows nothing
   about and which are exactly where a wrong number here would come from:

   a. the SSR port promotion is a *rename*, not a circuit change -- checked
      structurally (device lines byte-identical, one port name added to two
      subckt lines and one instance line) and, in ``sweep.py``'s ``anchor``
      phase, electrically against ``sim/loop-stability/`` itself;
   b. the injection-element A/B swaps the injection element and nothing else
      -- checked by diffing the two variants outside the ``ldo_softstart``
      block;
   c. the AC-only sensitivity transforms are DC-inert by construction --
      checked structurally here, and by measurement in the record (each
      case's landed VOUT / injection current is reported next to its margin);
   d. the landing rule refuses the DC branches it is there to refuse, at
      every point of the ramp and not only at the settled one -- the check
      that keeps a margin from being reported about a bias point that is not
      the one named.

Needs ngspice for part 1 (no PDK, no design netlist); part 2 needs the
design netlist but no simulator. Writes nothing.

    ./sim/soft-start-loop-gain/testbench/selftest.py

Exit codes: 0 all checks pass, 1 a check failed, 3 environment problem.
"""

from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPDIR = HERE.parent
REPO_ROOT = EXPDIR.parent.parent
LS_SELFTEST = REPO_ROOT / "sim" / "loop-stability" / "testbench" / "selftest.py"

sys.path.insert(0, str(HERE))
import netlist_variants as nv  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "ss_loop_gain_sweep", HERE / "sweep.py")
sweep = importlib.util.module_from_spec(_spec)
sys.modules["ss_loop_gain_sweep"] = sweep
_spec.loader.exec_module(sweep)

OK = True


def check(label: str, passed: bool, detail: str) -> None:
    global OK
    OK = OK and passed
    print(f"  [{'PASS' if passed else 'FAIL'}] {label}: {detail}")


def device_lines(text: str) -> list[str]:
    """The netlist's element lines, with continuations folded in."""
    out: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("*"):
            continue
        if s.startswith("+") and out:
            out[-1] += " " + s[1:].strip()
        else:
            out.append(s)
    return out


def main() -> int:
    # ---- part 1: the extraction, via loop-stability's own known-answer test
    print("== 1/2 loop-gain extraction (sim/loop-stability/testbench/selftest.py)")
    proc = subprocess.run([sys.executable, str(LS_SELFTEST)],
                          capture_output=True, text=True)
    for ln in (proc.stdout + proc.stderr).splitlines():
        print("  | " + ln)
    if proc.returncode == 3:
        print("\nFATAL: the extraction selftest could not run (environment)",
              file=sys.stderr)
        return 3
    check("sim/loop-stability's known-answer extraction selftest",
          proc.returncode == 0,
          "delegated unmodified; this deck uses the same Tian arithmetic, the "
          "same meas-based margin extraction and the same DR-0008 resurgence "
          "idiom, so its validation is this deck's validation")

    # ---- part 2: this experiment's own additions
    print("\n== 2/2 this experiment's own machinery")
    core = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()
    try:
        dev = nv.instrument_core(core)
    except nv.TransformError as exc:
        check("SSR port promotion runs at all", False, str(exc))
        print("\nSELFTEST FAIL")
        return 1

    # (a) the port promotion is a rename
    base_lines = device_lines(core)
    dev_lines = device_lines(dev)
    changed = [(a, b) for a, b in zip(base_lines, dev_lines) if a != b]
    expected = {
        (nv.CORE_PORTS, nv.CORE_PORTS + " SSR"),
        (nv.SS_PORTS, nv.SS_PORTS + " SSR"),
        (nv.SS_INSTANCE, nv.SS_INSTANCE.replace(" ldo_softstart",
                                                " SSR ldo_softstart")),
    }
    check("SSR port promotion changes exactly three lines, all of them port "
          "lists or the instance line that has to match one",
          len(base_lines) == len(dev_lines) and set(changed) == expected,
          f"{len(changed)} line(s) differ out of {len(base_lines)}: "
          + "; ".join(f"{a!r} -> {b!r}" for a, b in changed[:4]))
    check("no device, model, resistor or capacitor line is touched by the "
          "promotion",
          all(not a[:1].upper() in ("X", "M", "R", "C", "L", "V", "I", "F", "B")
              or (a, b) == (nv.SS_INSTANCE,
                            nv.SS_INSTANCE.replace(" ldo_softstart",
                                                   " SSR ldo_softstart"))
              for a, b in changed),
          "the only element line that changes is Xsoftstart, whose port list "
          "must match the subckt's")

    # (b) the A/B swaps the injection element and nothing else
    try:
        binj = nv.instrument_core(core, nv.fetch_pre195_softstart(REPO_ROOT))
    except nv.TransformError as exc:
        check("pre-#195 netlist is reachable", False, str(exc))
        binj = None
    if binj is not None:
        def outside_softstart(text: str) -> list[str]:
            body = nv.SS_BLOCK_RE.sub("", text)
            return device_lines(body)
        same = outside_softstart(dev) == outside_softstart(binj)
        check("the two DUT variants are identical outside ldo_softstart",
              same,
              "pass device, 300k/600k divider, Cff, error_amp and ldo_ilimit "
              "are byte-identical between the `device` and `binj` netlists, so "
              "the A/B is attributable to the injection element and nothing else")
        dev_ss = nv.SS_BLOCK_RE.search(dev).group(0)
        binj_ss = nv.SS_BLOCK_RE.search(binj).group(0)
        check("...and they really do differ in the injection element",
              ("Binj_ss" in binj_ss and "Binj_ss" not in dev_ss
               and "XMgmo_ss" in dev_ss and "XMgmo_ss" not in binj_ss),
              "`binj` has the behavioural Binj_ss and no XMgmo_ss; `device` "
              "has the transconductor chain and no Binj_ss")

    # (c) the AC-only transforms are DC-inert by construction
    opened = nv.ac_open(dev, "XMgmo_ss", "FB", "t")
    ol = device_lines(opened)
    ind = [l for l in ol if l.lower().startswith("lt ")]
    rest = [l for l in ol if not l.lower().startswith("lt ")]
    diff = [(a, b) for a, b in zip(dev_lines, rest) if a != b]
    check("ac_open() adds exactly one inductor and moves exactly one terminal",
          len(ind) == 1 and len(rest) == len(dev_lines) and len(diff) == 1
          and diff[0][0].split()[0] == "XMgmo_ss"
          and diff[0][1].split()[1] == "FB_t",
          f"inserted {ind[0] if ind else '(nothing)'}, and the only other "
          f"changed line is XMgmo_ss's drain node. An inductor is a short at "
          f"DC, so the operating point cannot move; {nv.AC_OPEN_H} H is "
          f"{1 / (2 * math.pi * float(nv.AC_OPEN_H) * 0.01):.3g} S at the "
          f"sweep's 0.01 Hz floor, i.e. an open against the ~200 kohm the "
          f"feedback node presents")
    check("ac_open() does not split a device line from its `+` continuations",
          len(diff) == 1
          and diff[0][0].split()[2:] == diff[0][1].split()[2:]
          and "sd=0" in diff[0][1],
          "the moved instance keeps every parameter it had -- inserting the "
          "inductor between an instance line and its continuation would "
          "silently truncate the parameter list (ngspice: \"Undefined "
          "parameter [nf]\"), which is a real bug this check caught")
    shorted = nv.ac_short(dev, "GMSUM", "VIN", "t")
    sl = device_lines(shorted)
    caps = [l for l in sl if l.lower().startswith("ct ")]
    check("ac_short() adds exactly one capacitor and changes nothing else",
          len(caps) == 1
          and [l for l in sl if not l.lower().startswith("ct ")] == dev_lines,
          f"inserted {caps[0] if caps else '(nothing)'} and left every other "
          f"line byte-identical -- a capacitor is an open at DC, so again the "
          f"operating point cannot move")
    for bad in (("XMgmo_ss", "VIN"), ("XNoSuchDevice", "FB")):
        try:
            nv.ac_open(dev, bad[0], bad[1], "t")
            raised = False
        except nv.TransformError:
            raised = True
        check(f"ac_open() refuses an ambiguous/absent target {bad}",
              raised,
              "a transform that cannot say exactly which terminal it moved "
              "must fail, not guess -- an attribution built on a guess is worse "
              "than none")

    # (d) the landing rule
    def row(**kw):
        base = dict(
            corner_id="tt_27c_3.30v", corner="tt", temp_c=27.0, vin_v=3.3,
            iload_a=0.0, ceff_f=1e-6, esr_ohm=0.1, vout_v=0.9,
            dcgain_db=100.0, f0_hz=1e5, phase_at_f0_deg=-120.0, f180_hz=None,
            gain_at_f180_db=None, f0_rising_hz=None, resurgence_db=None,
            variant="device", phase="ramp", ssr_cmd="0.6", ssr_v=0.6,
            fb_v=1.2, isup_a=1e-3, load_model="resistive-36ohm",
            rload_ohm=36.0,
        )
        base.update(kw)
        return sweep.Row(**base)

    check("a mid-ramp point with FB at the reference is accepted",
          row(vout_v=0.9, fb_v=1.2).landed == "",
          "VOUT = 0.9 V is nowhere near the 1.8 V regulation target, and it is "
          "still the intended branch: this is the case sim/loop-stability's "
          "settled-only rule cannot express")
    check("the clamp-latch branch is refused at the BOTTOM of the ramp, where "
          "its VOUT is indistinguishable from the intended one",
          row(ssr_cmd="0", ssr_v=0.0, vout_v=0.0002, fb_v=0.00013).landed != "",
          "VOUT ~ 0 is what the ramp's own start looks like too; FB ~ 0 "
          "instead of ~ VREF is what says the loop is not holding the feedback "
          "node, i.e. it is a latch and not a ramp state")
    check("the intended ramp start IS accepted",
          row(ssr_cmd="0", ssr_v=0.0, vout_v=0.0002, fb_v=1.2).landed == "",
          "same VOUT, FB at the reference -- accepted, and correctly so")
    check("an unbounded-VOUT branch is refused",
          row(vout_v=-29.0, fb_v=1.2).landed != "", "VOUT = -29 V")
    check("an unparsable operating point is refused, not trusted",
          row(vout_v=float('nan')).landed != "", "VOUT = nan")
    check("the anchor phase additionally holds itself to "
          "sim/loop-stability's own settled rule",
          (row(phase="anchor", ssr_cmd="free", vout_v=1.5, fb_v=1.2).landed != ""
           and row(phase="ramp", vout_v=1.5, fb_v=1.2).landed == ""),
          f"VOUT = 1.5 V is a legitimate ramp state and NOT a legitimate "
          f"settled one ({sweep.VOUT_TOL_FRAC:.0%} of "
          f"{sweep.VOUT_NOM_V:g} V) -- the anchor has to land where "
          f"sim/loop-stability lands or the cross-check it feeds is empty")

    # (e) the injection current is derived correctly
    r = row(vout_v=0.9, fb_v=1.2)
    want = 1.2 / 600e3 - (0.9 - 1.2) / 300e3
    check("the injection current is KCL at FB, not a fitted number",
          abs(r.iinj_a - want) < 1e-18,
          f"{r.iinj_a * 1e6:.4f} uA = V(FB)/600k - (V(VOUT)-V(FB))/300k, the "
          f"same expression for both DUT variants")

    # (e2) the hand-over transfer's metrics have a known answer
    # The pre-#195 element is a closed-form transconductor,
    #     I_inj = max(0, (VREF - V(SSR)) * 5 uA/V),
    # so a synthetic curve carrying exactly that is a known-answer test of
    # every metric the compensation recommendation cites -- and, because the
    # curve is built by solving KCL at FB for VOUT and the metrics read it
    # back out, it also tests that the derivation is inverted correctly.
    def hov_curve(gm=5e-6, release=1.2, variant="binj"):
        pts = []
        for ssr in sweep.HANDOVER_SSR_V:
            i = max(0.0, (release - ssr) * gm)
            fb = sweep.VREF_V
            pts.append(sweep.HovPoint(
                ssr_cmd=ssr, ssr_v=ssr, fb_v=fb,
                vout_v=fb - 300e3 * (i - fb / 600e3),
                pg_v=2.0, erramp_v=2.0, isup_a=1e-3, gmsum_v=None))
        return sweep.HovCurve(corner_id="tt_27c_3.30v", corner="tt",
                              temp_c=27.0, vin_v=3.3, variant=variant,
                              points=pts)

    ideal = hov_curve()
    check("the hand-over metrics recover the ideal element's known transfer",
          (abs(ideal.iinj_start_a * 1e6 - 6.0) < 1e-6
           and abs(ideal.gm_a_per_v * 1e6 + 5.0) < 1e-6
           and abs(ideal.release_ssr_v - sweep.VREF_V) < 1e-9
           and abs(ideal.iinj_at_vref_a) < 1e-12
           and ideal.saturated_to_ssr_v is None),
          f"I_inj(0) = {ideal.iinj_start_a * 1e6:.4f} uA (analytic 6.0000), "
          f"gm = {ideal.gm_a_per_v * 1e6:.4f} uA/V (analytic -5.0000), "
          f"releases at V(SSR) = {ideal.release_ssr_v:.4f} V (analytic "
          f"{sweep.VREF_V:g}), leaves {ideal.iinj_at_vref_a * 1e9:.3g} nA at "
          f"VREF, never takes the loop out of regulation -- i.e. the "
          f"measurement the record reports for the `binj` variant is the "
          f"behavioural model's own arithmetic read back through the landed "
          f"operating point")

    never = hov_curve(release=99.0)
    dipped = hov_curve()
    _i = next(k for k, p in enumerate(dipped.points) if abs(p.ssr_v - 2.0) < 1e-9)
    dipped.points[_i].vout_v = (dipped.points[_i].fb_v
                                - 300e3 * (1e-6 - dipped.points[_i].fb_v / 600e3))
    check("a soft tail that comes back is not reported as a release",
          (never.release_ssr_v is None
           and abs(dipped.release_ssr_v - dipped.points[_i + 1].ssr_v) < 1e-9),
          "an element that still injects everywhere reports 'never' rather "
          "than its last sample, and one that dips below the threshold and "
          "comes back is only released after the LAST crossing -- the first "
          "crossing would flatter it by the width of the dip")

    sat = hov_curve()
    for _p in sat.points[:8]:
        _p.fb_v, _p.vout_v = 1.45, 0.0
    check("an over-injecting element is reported as taking the loop out of "
          "regulation, and does not contaminate the fitted transconductance",
          (abs(sat.saturated_to_ssr_v - sat.points[7].ssr_v) < 1e-9
           and abs(sat.gm_a_per_v * 1e6 + 5.0) < 1e-6),
          f"out of regulation up to V(SSR) = {sat.saturated_to_ssr_v:.3f} V "
          f"(FB pushed to {sat.fb_max_v:.3f} V, i.e. the error amp railed and "
          f"the pass device off -- a state with no loop gain and therefore no "
          f"phase margin, which is why it has to be found by a DC sweep and "
          f"cannot be found by the margin deck), and the transconductance is "
          f"still fitted over the live range only: "
          f"{sat.gm_a_per_v * 1e6:.4f} uA/V")

    check("the hand-over deck is the same circuit and the same loop break as "
          "the margin deck",
          all(ln in sweep.HANDOVER_TEMPLATE.read_text()
              and ln in sweep.TEMPLATE.read_text()
              for ln in ("Xdut VIN VOUT EN 0 AINJ BINJ VREF SSRPIN ldo_core",
                         "Vinj AINJ BINJ DC 0 AC 0")),
          "same DUT instantiation, same break at ERRAMP_OUT->PASS_GATE with "
          "the injection source a DC short -- so a hand-over point and a "
          "margin row at the same V(SSR) are the same operating point, which "
          "the sweep then measures rather than assumes "
          "(handover_consistency())")

    # (f) the bars and the AC band are loop-stability's OBJECTS, not copies
    check("the DR-0001 bars, the resurgence bar and the AC band are imported "
          "from sim/loop-stability, not restated",
          (sweep.PM_MIN_DEG is sweep.ls.PM_MIN_DEG
           and sweep.GM_MIN_DB is sweep.ls.GM_MIN_DB
           and sweep.RESURGENCE_MAX_DB is sweep.ls.RESURGENCE_MAX_DB
           and sweep.AC_DEC is sweep.ls.AC_DEC
           and sweep.F_START is sweep.ls.F_START
           and sweep.F_STOP is sweep.ls.F_STOP
           and issubclass(sweep.Row, sweep.ls.Row)),
          f"PM >= {sweep.PM_MIN_DEG:g} deg, GM >= {sweep.GM_MIN_DB:g} dB, "
          f"resurgence <= {sweep.RESURGENCE_MAX_DB:g} dB, "
          f"dec {sweep.AC_DEC} {sweep.F_START}..{sweep.F_STOP} -- the same "
          f"objects, so the two experiments cannot drift apart on what a "
          f"margin means")

    print(f"\nSELFTEST {'PASS' if OK else 'FAIL'}")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
