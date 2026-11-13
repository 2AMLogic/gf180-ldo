#!/usr/bin/env python3
"""Unit tests for the soft-start loop-gain sweep driver. No PDK, no ngspice.

    python3 -m unittest discover -s sim/tests -v

Same contract and same shape as ``test_loop_stability.py``: these cover the
parts of ``sim/soft-start-loop-gain/testbench/`` that decide whether a number
becomes a claim in an evidence record -- the landing rule, the derived
injection current, the netlist transforms, the ``device``/``binj`` variant
A/B, the deck template's substitution, the hand-over metrics, the ``klt sim``
batch front end, and the fact that the margin semantics are *imported* from
``sim/loop-stability/`` rather than re-implemented.

**This module is the only copy of those assertions.** Since issue #593,
``sim/soft-start-loop-gain/testbench/selftest.py`` -- the pre-sweep gate
``run.sh`` runs -- delegates its whole second half to this file instead of
restating it, the same way its first half already delegates the extraction's
known-answer test to ``sim/loop-stability/testbench/selftest.py``. So a
property asserted here is enforced in two places at once: in CI (via
``sim/selftest.sh``) and before any sweep (via that selftest). Adding a check
here is the way to put it in front of a sweep; there is no second file to
keep in step, and there should not become one.

The simulation itself is validated against closed-form answers by that same
selftest, which needs ngspice. Nothing here does: no PDK, no simulator.
``TestDutVariantAB`` needs the pre-#195 commit, which is not an ancestor of
`main`, and skips with a named reason where it cannot be fetched.
"""

from __future__ import annotations

import difflib
import importlib.util
import math
import re
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))

_TB = SIM_DIR / "soft-start-loop-gain" / "testbench"
sys.path.insert(0, str(_TB))
import netlist_variants as nv  # noqa: E402

_spec = importlib.util.spec_from_file_location("ss_loop_gain_sweep", _TB / "sweep.py")
sweep = importlib.util.module_from_spec(_spec)
sys.modules["ss_loop_gain_sweep"] = sweep
_spec.loader.exec_module(sweep)

CORE = (REPO_ROOT / "design" / "netlist" / "ldo_core.spice").read_text()


def device_lines(text: str) -> list[str]:
    """The netlist's element lines, with `+` continuations folded in.

    A raw ``splitlines()`` comparison cannot tell "this instance kept every
    parameter it had" from "this instance was severed from its continuation
    lines", because both leave the line *count* alone. Folding first makes
    each element one string, so an equality over this list is a claim about
    whole devices rather than about text rows.
    """
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


def row(**kw) -> "sweep.Row":
    base = dict(
        corner_id="tt_27c_3.30v", corner="tt", temp_c=27.0, vin_v=3.3,
        iload_a=0.0, ceff_f=1e-6, esr_ohm=0.1, vout_v=0.9, dcgain_db=100.0,
        f0_hz=1e5, phase_at_f0_deg=-120.0, f180_hz=None, gain_at_f180_db=None,
        f0_rising_hz=None, resurgence_db=None, variant="device", phase="ramp",
        ssr_cmd="0.6", ssr_v=0.6, fb_v=1.2, isup_a=1e-3,
        load_model="resistive-36ohm", rload_ohm=36.0,
    )
    base.update(kw)
    return sweep.Row(**base)


class TestMarginSemanticsAreNotForked(unittest.TestCase):
    """The whole comparability claim of this experiment rests on this."""

    def test_the_bars_are_loop_stabilitys_own_objects(self):
        self.assertIs(sweep.PM_MIN_DEG, sweep.ls.PM_MIN_DEG)
        self.assertIs(sweep.GM_MIN_DB, sweep.ls.GM_MIN_DB)
        self.assertIs(sweep.RESURGENCE_MAX_DB, sweep.ls.RESURGENCE_MAX_DB)

    def test_the_ac_band_and_resolution_are_loop_stabilitys_own(self):
        self.assertIs(sweep.AC_DEC, sweep.ls.AC_DEC)
        self.assertIs(sweep.F_START, sweep.ls.F_START)
        self.assertIs(sweep.F_STOP, sweep.ls.F_STOP)
        self.assertEqual(sweep.AC_DEC, "400")

    def test_row_inherits_rather_than_restates_the_margin_definitions(self):
        self.assertTrue(issubclass(sweep.Row, sweep.ls.Row))
        for name in ("pm_deg", "gm_db", "passes", "resurges"):
            self.assertIs(getattr(sweep.Row, name), getattr(sweep.ls.Row, name),
                          f"{name} is redefined here instead of inherited")

    def test_the_pvt_grid_is_loop_stabilitys_own(self):
        self.assertIs(sweep.PROCESS_CORNERS, sweep.ls.PROCESS_CORNERS)
        self.assertIs(sweep.TEMPS_C, sweep.ls.TEMPS_C)
        self.assertEqual(sweep.SUPPLY_TOL, 0.10)


class TestLandingRule(unittest.TestCase):
    """A margin about the wrong DC branch is noise dressed up as a number."""

    def test_a_mid_ramp_point_with_fb_at_the_reference_is_accepted(self):
        self.assertEqual(row(vout_v=0.9, fb_v=1.2).landed, "")

    def test_vout_alone_cannot_discriminate_at_the_bottom_of_the_ramp(self):
        # Same VOUT; only FB says which branch this is.
        self.assertEqual(row(ssr_cmd="0", ssr_v=0.0, vout_v=2e-4, fb_v=1.2).landed, "")
        self.assertNotEqual(
            row(ssr_cmd="0", ssr_v=0.0, vout_v=2e-4, fb_v=1.3e-4).landed, "")

    def test_the_unbounded_vout_branch_is_refused(self):
        self.assertNotEqual(row(vout_v=-29.0).landed, "")

    def test_a_runaway_output_is_refused(self):
        self.assertNotEqual(row(vout_v=3.0, fb_v=2.0).landed, "")

    def test_an_unparsable_operating_point_is_refused_not_trusted(self):
        self.assertNotEqual(row(vout_v=float("nan")).landed, "")
        self.assertNotEqual(row(fb_v=float("nan")).landed, "")

    def test_the_anchor_phase_also_holds_loop_stabilitys_settled_rule(self):
        self.assertEqual(row(phase="ramp", vout_v=1.5, fb_v=1.2).landed, "")
        self.assertNotEqual(
            row(phase="anchor", ssr_cmd="free", vout_v=1.5, fb_v=1.2).landed, "")
        self.assertEqual(
            row(phase="anchor", ssr_cmd="free", vout_v=1.799, fb_v=1.2).landed, "")

    def test_the_fb_window_is_a_branch_check_not_an_accuracy_check(self):
        # 10 mV of feedback error is an accuracy question for other benches.
        self.assertEqual(row(fb_v=1.21).landed, "")


class TestDerivedInjectionCurrent(unittest.TestCase):
    def test_it_is_kcl_at_the_feedback_node(self):
        # The current is *derived* rather than measured, so the only tolerance
        # it is entitled to is floating-point noise on a ~3 uA quantity --
        # 1e-18 A, not a round number of decimal places. Anything looser would
        # let a genuinely different expression pass.
        r = row(vout_v=0.9, fb_v=1.2)
        self.assertAlmostEqual(r.iinj_a, 1.2 / 600e3 - (0.9 - 1.2) / 300e3,
                               delta=1e-18)

    def test_it_is_zero_when_the_divider_alone_balances(self):
        # VOUT = 1.5*FB is the no-injection condition of a 300k/600k divider.
        self.assertAlmostEqual(row(vout_v=1.8, fb_v=1.2).iinj_a, 0.0, places=15)

    def test_it_matches_the_designs_own_divider_values(self):
        self.assertIn("Rtop VOUT FB 300k", CORE)
        self.assertIn("Rbot FB VSS 600k", CORE)


class TestNetlistTransforms(unittest.TestCase):
    def test_ssr_promotion_adds_one_port_to_two_subckts_and_one_instance(self):
        out = nv.instrument_core(CORE)
        self.assertIn(nv.CORE_PORTS + " SSR", out)
        self.assertIn(nv.SS_PORTS + " SSR", out)
        self.assertIn(nv.SS_INSTANCE.replace(" ldo_softstart",
                                             " SSR ldo_softstart"), out)
        # ... and changes nothing else.
        self.assertEqual(len(out.splitlines()), len(CORE.splitlines()))

    def test_ssr_promotion_changes_exactly_three_lines_and_no_device(self):
        """The promotion is a *rename*, not a circuit change.

        The line count above is necessary but nowhere near sufficient: a
        transform that also retyped a device, moved a node or changed a
        parameter would keep it. This is the claim the record rests on --
        that every `device` row is a measurement of the committed circuit --
        so it is asserted as an equality over the whole folded element list,
        naming the only three lines allowed to differ. Two of them are port
        lists (not circuitry at all) and the third is the instance line that
        has to match the subckt's.
        """
        out = nv.instrument_core(CORE)
        base_lines, dev_lines = device_lines(CORE), device_lines(out)
        self.assertEqual(len(base_lines), len(dev_lines))
        changed = [(a, b) for a, b in zip(base_lines, dev_lines) if a != b]
        promoted_instance = nv.SS_INSTANCE.replace(" ldo_softstart",
                                                   " SSR ldo_softstart")
        self.assertEqual(
            set(changed),
            {(nv.CORE_PORTS, nv.CORE_PORTS + " SSR"),
             (nv.SS_PORTS, nv.SS_PORTS + " SSR"),
             (nv.SS_INSTANCE, promoted_instance)},
            "the promotion touched something other than the two port lists "
            "and the instance line that must track one of them")
        # Said the other way round, as the property rather than the fixture:
        # no element line changes except Xsoftstart's port list.
        for a, b in changed:
            if a[:1].upper() in ("X", "M", "R", "C", "L", "V", "I", "F", "B"):
                self.assertEqual((a, b), (nv.SS_INSTANCE, promoted_instance),
                                 f"element line {a!r} was modified")

    def test_ssr_promotion_is_refused_if_the_port_list_is_not_what_it_expects(self):
        with self.assertRaises(nv.TransformError):
            nv.instrument_core(CORE.replace(nv.CORE_PORTS, ".subckt ldo_core A B"))

    def test_a_missing_softstart_block_is_an_error_not_a_silent_passthrough(self):
        with self.assertRaises(nv.TransformError):
            nv.instrument_core(nv.SS_BLOCK_RE.sub("", CORE))

    def test_ac_open_moves_one_terminal_and_adds_one_inductor(self):
        # XMpre_b_ss is a real device-level FB coupling that survives #231's
        # revert. Binj_ss (the OTHER real FB coupling post-#231) is a
        # behavioural source and is covered by the B-prefix refusal test
        # below instead -- see issue #234.
        base = nv.instrument_core(CORE)
        out = nv.ac_open(base, "XMpre_b_ss", "FB", "t")
        self.assertIn("Lt FB_t FB " + nv.AC_OPEN_H, out)
        self.assertRegex(out, r"(?m)^XMpre_b_ss FB_t ")
        self.assertEqual(len(out.splitlines()), len(base.splitlines()) + 1)
        # "exactly one" as an equality, not as a line count: exactly one
        # inductor element, and exactly one *other* element differing from
        # the base. An inductor is a short at DC, so with nothing else
        # touched the operating point provably cannot move -- which is the
        # whole DC-inertness claim the attribution rows rest on.
        ol = device_lines(out)
        ind = [l for l in ol if l.lower().startswith("lt ")]
        rest = [l for l in ol if not l.lower().startswith("lt ")]
        self.assertEqual(len(ind), 1)
        base_lines = device_lines(base)
        self.assertEqual(len(rest), len(base_lines))
        diff = [(a, b) for a, b in zip(base_lines, rest) if a != b]
        self.assertEqual(len(diff), 1, f"{len(diff)} element lines moved")
        self.assertEqual(diff[0][0].split()[0], "XMpre_b_ss")
        self.assertEqual(diff[0][1].split()[1], "FB_t")

    def test_ac_open_refuses_a_behavioural_b_prefixed_instance(self):
        """Issue #234: this is the exact `acopen-fb-inj` mistake -- a series
        inductor in front of an ideal current source removes nothing (KCL
        forces the inductor current to equal the source's output at every
        frequency), so the old call applied without raising and measured a
        delta that was zero by construction, not by measurement."""
        base = nv.instrument_core(CORE)
        with self.assertRaises(nv.TransformError):
            nv.ac_open(base, "Binj_ss", "FB", "t")

    def test_ac_open_b_prefix_refusal_is_case_insensitive_and_instance_only(self):
        base = nv.instrument_core(CORE)
        with self.assertRaises(nv.TransformError):
            nv.ac_open(base, "binj_ss", "FB", "t")
        # A device whose NAME merely contains a 'b' is not behavioural --
        # only the type-letter prefix (first character) matters.
        nv.ac_open(base, "XMben_ss", "EN", "t")  # must not raise

    def test_ac_open_puts_the_inductor_after_the_continuation_lines(self):
        # Inserting it between an instance and its `+` continuation truncates
        # the instance's parameter list. This was a real bug. Binj_ss (used
        # above) is a single line with no continuation, so this needs an
        # instance that still has one -- XMpre_b_ss touches FB once and
        # survived the #231 revert.
        base = nv.instrument_core(CORE)
        out = nv.ac_open(base, "XMpre_b_ss", "FB", "t").splitlines()
        i = next(k for k, ln in enumerate(out) if ln.startswith("Lt "))
        self.assertFalse(out[i + 1].startswith("+"))
        self.assertTrue(out[i - 1].startswith("+"))
        # The placement above is the mechanism; this is the consequence it
        # exists to guarantee. A severed instance silently loses its whole
        # parameter tail (ngspice then says `Undefined parameter [nf]`), and
        # the line *count* is identical either way -- so the assertion has to
        # be over the folded element, comparing the parameters it kept.
        folded = device_lines(nv.ac_open(base, "XMpre_b_ss", "FB", "t"))
        rest = [l for l in folded if not l.lower().startswith("lt ")]
        diff = [(a, b) for a, b in zip(device_lines(base), rest) if a != b]
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0][0].split()[2:], diff[0][1].split()[2:],
                         "the moved instance lost or gained a parameter")
        self.assertIn("sd=0", diff[0][1])

    def test_ac_open_refuses_an_ambiguous_terminal(self):
        base = nv.instrument_core(CORE)
        with self.assertRaises(nv.TransformError):
            nv.ac_open(base, "XMhold_ss", "VIN", "t")   # VIN appears twice

    def test_ac_open_refuses_an_absent_instance(self):
        with self.assertRaises(nv.TransformError):
            nv.ac_open(nv.instrument_core(CORE), "XNope", "FB", "t")

    def test_ac_short_adds_one_capacitor_inside_the_softstart_subckt(self):
        # HG is a real internal node (the soft-start hold network) and is
        # chosen because it is stable across this cell's injection-element
        # churn: GMSUM, which this test used pre-#234, was deleted by #231
        # and reinstated by #246, which is exactly why it is a bad fixture.
        base = nv.instrument_core(CORE)
        out = nv.ac_short(base, "HG", "VIN", "t")
        self.assertIn("Ct HG VIN " + nv.AC_SHORT_F, out)
        self.assertEqual(len(out.splitlines()), len(base.splitlines()) + 1)
        block = nv.SS_BLOCK_RE.search(out).group(0)
        self.assertIn("Ct HG VIN", block)
        # ... and changes nothing else at all: exactly one capacitor added,
        # every other element byte-identical. A capacitor is an open at DC,
        # so on that equality the operating point cannot move either.
        sl = device_lines(out)
        caps = [l for l in sl if l.lower().startswith("ct ")]
        self.assertEqual(len(caps), 1)
        self.assertEqual([l for l in sl if not l.lower().startswith("ct ")],
                         device_lines(base))

    def test_add_cap_refuses_a_node_absent_from_the_netlist(self):
        """Issue #234: this is the exact `acshort-gmsum` mistake -- GMSUM was
        removed from `ldo_softstart` by #231, and the old call hung a
        capacitor on it anyway: floating, no DC path to ground, coupled to
        nothing in AC, so it applied without raising and measured nothing.

        The absent node is named SYNTHETICALLY here rather than reusing
        GMSUM, because GMSUM came BACK in #246 (DR-0023's cascoded mirror
        re-instates the whole Mgm* chain, mirror node included) and this
        assertion then silently inverted: it started asserting that a node
        which exists is refused, and failed. A guard test must not depend on
        which nodes the design happens to have this month.
        """
        base = nv.instrument_core(CORE)
        absent = "NODE_THAT_IS_NOT_IN_THIS_NETLIST"
        self.assertNotIn(absent, base)
        with self.assertRaises(nv.TransformError):
            nv.add_cap(base, absent, "VIN", nv.AC_SHORT_F, "t")
        with self.assertRaises(nv.TransformError):
            nv.ac_short(base, absent, "VIN", "t")
        with self.assertRaises(nv.TransformError):
            nv.ac_load(base, absent, "VIN", 1e-12, "t")

    def test_add_cap_node_check_is_a_whole_token_match(self):
        """A node name that is merely a SUBSTRING of some other token must
        not satisfy the existence check -- that would defeat the guard the
        same way a regex without word boundaries would."""
        base = nv.instrument_core(CORE)
        self.assertIn("SSR", base)      # the substring really is present...
        self.assertNotIn(" SR ", base)  # ...but "SR" alone, as a node, is not
        with self.assertRaises(nv.TransformError):
            nv.add_cap(base, "SR", "VIN", nv.AC_SHORT_F, "t")

    def test_ac_load_adds_one_capacitor_of_the_asked_for_value(self):
        base = nv.instrument_core(CORE)
        out = nv.ac_load(base, "FB", "VSS", 1e-12, "fbcap")
        self.assertIn("Cfbcap FB VSS 1e-12", out)
        self.assertEqual(len(out.splitlines()), len(base.splitlines()) + 1)

    def test_ac_load_lands_inside_the_softstart_subckt(self):
        """FB is a port of ldo_softstart; putting the capacitor at the top
        level would hang it on ldo_core's FB, which is the same node but a
        different netlist edit, and the selftest's byte-comparison of the two
        variants would stop meaning what it says."""
        out = nv.ac_load(nv.instrument_core(CORE), "FB", "VSS", 1e-12, "fbcap")
        block = nv.SS_BLOCK_RE.search(out).group(0)
        self.assertIn("Cfbcap FB VSS 1e-12", block)

    def test_ac_load_and_ac_short_are_the_same_transform(self):
        """Both are 'a capacitor from a node to a rail', which is DC-inert at
        any value; keeping them one code path is what makes that guarantee
        one fact rather than two."""
        base = nv.instrument_core(CORE)
        self.assertEqual(nv.ac_short(base, "HG", "VIN", "t"),
                         nv.add_cap(base, "HG", "VIN", nv.AC_SHORT_F, "t"))

    def test_the_fb_capacitance_ladder_brackets_the_schematics_own_estimate(self):
        """The schematic's regression note says the chain adds 'tens of
        femtofarads'; a ladder that starts above that cannot say whether that
        amount matters, and one that stops below the bar cannot state a
        budget."""
        self.assertLessEqual(sweep.FB_CAP_LADDER_F[0], 20e-15)
        self.assertGreaterEqual(sweep.FB_CAP_LADDER_F[-1], 1e-9)
        for a, b in zip(sweep.FB_CAP_LADDER_F, sweep.FB_CAP_LADDER_F[1:]):
            self.assertGreater(b, a)

    def test_the_attribution_transforms_all_apply_to_the_real_netlist(self):
        base = nv.instrument_core(CORE)
        for tag, _desc, fn in sweep.ATTRIBUTIONS:
            with self.subTest(tag=tag):
                fn(base)   # must not raise


class TestDutVariantAB(unittest.TestCase):
    """What the `device`/`binj` A/B actually differs in.

    HISTORY, because this claim has now changed twice and a reader who only
    sees the current assertion will mis-date the records:

      pre-#231  `device` was #195's device-level Mgm* chain and `binj` the
                ideal `Binj_ss` source -- the A/B WAS an injection-element
                comparison (record 20260910-015601-2387ece).
      #231/#234 the chain was reverted, so BOTH variants carried `Binj_ss`
                and the A/B degenerated into a DR-0024 cap-resize before/
                after with no injection-element content at all.
      #246      DR-0023's cascoded mirror lands, so `device` carries the
                Mgm* chain again (now with Mgmrc_ss/Mgmc_ss) and `binj`
                still carries `Binj_ss`. The A/B is an injection-element
                comparison again -- but it is CONFOUNDED by the DR-0024
                cap resize, which `binj` (frozen at bfc4a0a) predates. That
                confound is named rather than removed, because removing it
                would mean re-freezing `binj` at a commit that does not
                exist. Any record minted from this bench must say so.

    See ``netlist_variants.py``'s module docstring and ``VARIANT_BLURB``.

    ``binj`` is built from ``bfc4a0a``, which is a real commit in the
    GitHub repository but **not** an ancestor of `main`, so it has to be
    fetched by hash. A checkout that cannot reach it (no network, or a
    shallow clone whose fetch is refused) SKIPS these: the A/B is a
    property of two netlists, and without the second one there is nothing
    to assert either way. It is never a silent pass -- `skipTest` names the
    reason, and the pre-sweep gate in `run.sh` still runs it where the
    commit is reachable.
    """

    @classmethod
    def setUpClass(cls):
        cls.dev = nv.instrument_core(CORE)
        try:
            cls.binj = nv.instrument_core(
                CORE, nv.fetch_pre195_softstart(REPO_ROOT))
        except nv.TransformError as exc:
            cls.binj = None
            cls.why = str(exc)

    def setUp(self):
        if self.binj is None:
            self.skipTest(
                f"the pre-#195 netlist at {nv.PRE195_SHORT} is unreachable "
                f"from this checkout, so there is no second variant to "
                f"compare: {self.why}")

    @staticmethod
    def _outside_softstart(text: str) -> list[str]:
        return device_lines(nv.SS_BLOCK_RE.sub("", text))

    def test_the_two_variants_are_identical_outside_ldo_softstart(self):
        """The A/B has to be about the soft-start cell and nothing else.

        Pass device, 300k/600k divider, Cff, error_amp and ldo_ilimit must
        be byte-identical, or a device-vs-binj delta is not attributable to
        the injection element at all.
        """
        self.assertEqual(self._outside_softstart(self.dev),
                         self._outside_softstart(self.binj))

    def test_device_carries_the_cascoded_mirror_and_binj_the_ideal_source(self):
        dev_ss = nv.SS_BLOCK_RE.search(self.dev).group(0)
        binj_ss = nv.SS_BLOCK_RE.search(self.binj).group(0)
        cascode = ("XMgmr_ss", "XMgmrc_ss", "XMgmo_ss", "XMgmc_ss")
        missing = [n for n in cascode if f"\n{n} " not in "\n" + dev_ss]
        self.assertEqual(missing, [],
                         "post-#246 `device` must carry all four of "
                         "DR-0023's mirror devices")
        self.assertNotIn("Binj_ss", dev_ss,
                         "`device` must have no behavioural injection source")
        self.assertIn("Binj_ss", binj_ss,
                      "`binj` must carry the ideal Binj_ss source")
        for n in cascode:
            self.assertNotIn(n, binj_ss,
                             f"`binj` must not carry the mirror device {n}")

    def test_the_dr0024_cap_resize_confound_is_still_present(self):
        """The A/B's OTHER difference, named rather than removed.

        `binj` is frozen at bfc4a0a, which predates DR-0024's 5x MIM-cap
        resize, so a device-vs-binj delta from this bench carries BOTH the
        injection element and the ramp-speed resize. There is no commit that
        has one without the other, so the confound is named in every record
        instead of being removed (issues #234, #246). This test fails if the
        confound ever silently disappears -- at which point the records'
        caveat is the thing that became wrong.
        """
        dev_ss = device_lines(nv.SS_BLOCK_RE.search(self.dev).group(0))
        binj_ss = device_lines(nv.SS_BLOCK_RE.search(self.binj).group(0))
        for n in ("XCss", "XCh_ss", "XCr_ss"):
            self.assertTrue(any(l.split()[0] == n for l in dev_ss),
                            f"{n} is absent from `device`")
            self.assertTrue(any(l.split()[0] == n for l in binj_ss),
                            f"{n} is absent from `binj`")
        self.assertNotEqual([l for l in dev_ss if l.split()[0] == "XCss"],
                            [l for l in binj_ss if l.split()[0] == "XCss"],
                            "the DR-0024 cap resize is no longer a difference "
                            "between the two variants -- the confound every "
                            "record of this bench names has gone, so those "
                            "records' caveat is now wrong")


def _classify_attribution_effect(base: str, out: str) -> tuple[str, str]:
    """What an ``ATTRIBUTIONS``-shaped transform actually did to ``base``,
    read back purely from its OWN output -- not from which function
    (``ac_open``/``ac_short``/``ac_load``) produced it.

    Uses a real line-level diff (not a positional ``zip``) so an insertion
    anywhere in the file does not make every following line look "changed"
    just because it shifted down by one.

    Returns ``("ac_open", instance)`` for a transform that removed exactly
    one instance line, re-added it (with one terminal renamed) and added one
    ``L*`` inductor line, or ``("add_cap", node)`` for a transform that added
    exactly one ``C*`` line and removed nothing (its second token is the
    node it landed on). Raises ``AssertionError`` -- a hard test failure,
    not a skip -- for anything else, because an attribution this classifier
    cannot recognise is one nothing here has validated.
    """
    base_lines, out_lines = base.splitlines(), out.splitlines()
    # autojunk=False (issue #320): difflib's default "popular line"
    # heuristic kicks in once a sequence reaches 200 lines and treats any
    # line occurring in >1% of it as junk. The PDK's per-device
    # `+ ps=... nrd=... m=1` continuation lines are byte-identical across
    # instances, so once the instrumented netlist grew past 200 lines (the
    # #320 bias servo) they were junked, the matcher could not anchor on
    # them, and an untouched continuation line was reported as removed and
    # re-added -- a mis-alignment, not a real edit. Disabling the heuristic
    # makes the diff exact; it does not loosen anything checked below.
    matcher = difflib.SequenceMatcher(None, base_lines, out_lines,
                                      autojunk=False)
    added: list[str] = []
    removed: list[str] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op != "equal":
            removed.extend(base_lines[i1:i2])
            added.extend(out_lines[j1:j2])
    if len(removed) == 1:
        instance = removed[0].split()[0]
        l_added = [a for a in added if a.split()[0][:1].upper() == "L"]
        renamed = [a for a in added if a.split()[0] == instance]
        assert len(l_added) == 1 and len(renamed) == 1, (removed, added)
        return ("ac_open", instance)
    if len(removed) == 0:
        c_added = [a for a in added if a.split()[0][:1].upper() == "C"]
        assert len(added) == 1 and len(c_added) == 1, (removed, added)
        return ("add_cap", c_added[0].split()[1])
    raise AssertionError(
        f"unrecognised transform shape (-{removed} +{added}) -- this "
        "classifier does not know how to check it for a structurally-zero "
        "target")


class TestAttributionsCannotBeStructurallyZero(unittest.TestCase):
    """Issue #234: `acopen-fb-inj` (opened `Binj_ss`, an ideal current source
    with no AC contribution to remove) and `acshort-gmsum` (shorted `GMSUM`,
    a node no longer in the netlist) both ran without raising and reported a
    delta that was zero by construction, not by measurement. This class
    checks the property that would have caught both at review time --
    independent of `ac_open()`/`add_cap()`'s own internal guard rails, so it
    would still catch a future attribution built the same wrong way even if
    those guard rails were ever weakened or bypassed.
    """

    def test_every_current_attribution_targets_a_real_ac_coupling(self):
        base = nv.instrument_core(CORE)
        for tag, _desc, fn in sweep.ATTRIBUTIONS:
            with self.subTest(tag=tag):
                out = fn(base)
                self.assertNotEqual(out, base, f"{tag}: changed nothing")
                kind, target = _classify_attribution_effect(base, out)
                if kind == "ac_open":
                    self.assertNotEqual(
                        target[:1].upper(), "B",
                        f"{tag}: ac_open()'s target {target!r} is a "
                        "behavioural source -- an ideal source's current "
                        "does not depend on the terminal a series inductor "
                        "would isolate, so this row cannot move the AC "
                        "answer (the acopen-fb-inj mistake)")
                else:
                    self.assertIn(
                        target, base,
                        f"{tag}: add_cap()'s target node {target!r} does "
                        "not appear in the netlist before the transform -- "
                        "a capacitor onto it is floating and cannot move "
                        "the AC answer (the acshort-gmsum mistake)")

    def test_the_property_actually_flags_the_two_historical_mistakes(self):
        """The check above is only worth having if it rejects the two rows
        #234 removed -- reconstructed here exactly as the pre-#234 code
        would have built them, bypassing the now-fixed `ac_open()`/
        `add_cap()` so this test exercises the CLASSIFIER, not the guard
        rails already covered by `TestNetlistTransforms`.

        BOTH shapes are reconstructed against a SYNTHETIC fixture rather than
        against the live netlist (issue #246). The original version of this
        test reached into `CORE` for a real `Binj_ss ` line and a genuinely
        absent `GMSUM` node -- and both of those facts have since flipped:
        #246's cascoded mirror deleted `Binj_ss` and re-instated `GMSUM`, so
        the test errored on a `StopIteration` that said nothing about the
        classifier it exists to check. What is being tested here is a
        property of `_classify_attribution_effect`, not of this month's
        schematic, so the fixture should not be this month's schematic.
        """
        # A two-line stand-in with the same shape the classifier sees: one
        # behavioural source touching FB, inside an ldo_softstart block.
        base = (".subckt ldo_softstart VIN FB PASS_GATE EN VREF VSS BG\n"
                "Bfake_ss VIN FB I = '1e-6'\n"
                "XMfake_ss FB EN VIN VIN pfet_03v3 L=1u W=1u nf=1 m=1\n"
                ".ends\n")

        # acopen-fb-inj, reconstructed: move the B-source's FB terminal and
        # add the inductor -- exactly what ac_open() did before it refused
        # B-prefixed lines.
        lines = base.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("Bfake_ss "))
        lines[i] = lines[i].replace(" FB ", " FB_regress ", 1)
        lines.insert(i + 1, f"Lregress FB_regress FB {nv.AC_OPEN_H}")
        opened = "\n".join(lines) + "\n"
        kind, target = _classify_attribution_effect(base, opened)
        self.assertEqual((kind, target), ("ac_open", "Bfake_ss"))
        self.assertEqual(target[:1].upper(), "B")   # -> the check fails it

        # acshort-gmsum, reconstructed: hang a capacitor on a node that does
        # not exist in the netlist -- exactly what add_cap() did before it
        # refused an absent node.
        absent = "NODE_THAT_IS_NOT_IN_THIS_NETLIST"
        self.assertNotIn(absent, base)
        lines = base.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith(".subckt ldo_softstart"))
        lines.insert(i + 1, f"Cregress {absent} VIN 1.0")
        shorted = "\n".join(lines) + "\n"
        kind, target = _classify_attribution_effect(base, shorted)
        self.assertEqual((kind, target), ("add_cap", absent))
        self.assertNotIn(target, base)              # -> the check fails it


class TestDeckTemplate(unittest.TestCase):
    TEXT = (_TB / "tb_ss_loop_gain.spice.in").read_text()

    def test_the_template_breaks_the_loop_at_the_ports_ldo_core_exposes(self):
        self.assertIn("Xdut VIN VOUT EN 0 AINJ BINJ VREF SSRPIN ldo_core",
                      self.TEXT)
        self.assertIn("Vinj AINJ BINJ DC 0 AC 0", self.TEXT)
        self.assertIn("Iinj 0 BINJ DC 0 AC 0", self.TEXT)

    def test_the_template_uses_the_same_tian_arithmetic_as_loop_stability(self):
        ls_text = (SIM_DIR / "loop-stability" / "testbench"
                   / "tb_loop_stability.spice.in").read_text()
        for idiom in (
            "let tv = -v(ainj)/v(binj)",
            "let ti = -i(vinj)/(i(vinj)+1)",
            "let t = (tvv*ti - 1)/(tvv + ti + 2)",
            "let tdb = db(t)",
            "let tph = 180*cph(t)/pi",
            "meas ac f0 when tdb=0 fall=1",
            "meas ac phx find tph when tdb=0 fall=1",
            "meas ac f180 when tph=-180 fall=1",
            "meas ac gmx find tdb when tph=-180 fall=1",
            "let fres = f0*1.05",
        ):
            with self.subTest(idiom=idiom):
                self.assertIn(idiom, ls_text)
                self.assertIn(idiom, self.TEXT)

    def test_the_template_pins_the_model_binning_flag(self):
        # Without it the W=2000u pass device has no model bin on an ngspice
        # that is not in HSPICE compatibility mode, and no deck in this repo
        # parses. Recorded in the record's Environment section too.
        self.assertIn(".options wnflag=1", self.TEXT)

    def test_every_placeholder_is_substituted_by_the_driver(self):
        tokens = set(sweep.TOKEN_RE.findall(self.TEXT))
        # Mirror render_deck()'s substitution dict without running ngspice.
        provided = {
            "DESIGN_INCLUDE", "MODEL_LIB", "LDO_NETLIST", "MOS_CORNER",
            "RES_CORNER", "BJT_CORNER", "DIODE_CORNER", "MOSCAP_CORNER",
            "MIMCAP_CORNER", "TEMP_C", "VIN_V", "CORNER_ID", "CORNER_NAME",
            "AC_DEC", "F_START", "F_STOP", "CEFF_LIST", "ESR_LIST", "ILOAD",
            "RLOAD", "PHASE", "VARIANT", "SSR_SOURCE", "SSR_ALTER", "SSR_LIST",
            "DC_SEED",
        }
        self.assertEqual(tokens - provided, set())

    def test_the_row_field_list_matches_the_decks_own_echo(self):
        m = re.search(r'echo "ROW ([^"]+)"', self.TEXT)
        self.assertIsNotNone(m)
        keys = [tok.split("=")[0] for tok in m.group(1).split()]
        self.assertEqual(keys, list(sweep.ROW_FIELDS))


class TestRowParsing(unittest.TestCase):
    GOOD = ("ROW ssr_cmd=0.6 ssr_v=0.6 fb_v=1.2 vout_v=0.9 isup_a=1e-3 "
            "ceff_f=1e-06 esr_ohm=0.1 dcgain_db=100 f0_hz=1e5 "
            "phase_at_f0_deg=-120 f180_hz= gain_at_f180_db= f0_rising_hz= "
            "resurgence_db=-0.5")

    def test_all_fields_present(self):
        f = sweep.parse_row_fields(self.GOOD)
        self.assertEqual(f["vout_v"], "0.9")
        self.assertEqual(f["f180_hz"], "")

    def test_a_missing_field_is_an_error_not_a_default(self):
        with self.assertRaises(ValueError):
            sweep.parse_row_fields(self.GOOD.replace(" fb_v=1.2", ""))

    def test_a_positional_field_is_rejected(self):
        with self.assertRaises(ValueError):
            sweep.parse_row_fields(self.GOOD + " 1.234")

    def test_an_unknown_field_is_rejected(self):
        with self.assertRaises(ValueError):
            sweep.parse_row_fields(self.GOOD + " surprise=1")


class TestOperatingPoints(unittest.TestCase):
    def test_the_three_points_issue_196_names_are_all_run(self):
        ramp = sweep.PHASES["ramp"]["ssr"]
        self.assertIn(0.0, ramp)               # (a) ramp start
        self.assertIn(1.15, ramp)              # (b) VREF - 50 mV
        self.assertIn(1.25, ramp)              # (c) VREF + 50 mV
        self.assertAlmostEqual(sweep.VREF_V - 0.05, 1.15)
        self.assertAlmostEqual(sweep.VREF_V + 0.05, 1.25)

    def test_the_anchor_phase_leaves_ssr_unpinned(self):
        self.assertIsNone(sweep.PHASES["anchor"]["ssr"])

    def test_the_sink_phases_use_loop_stabilitys_own_load_model(self):
        for phase in ("sink", "anchor"):
            self.assertEqual(sweep.PHASES[phase]["iload_a"], 0.05)
            self.assertGreater(sweep.PHASES[phase]["rload_ohm"], 1e9)

    def test_the_ramp_phase_uses_a_resistive_load(self):
        self.assertEqual(sweep.PHASES["ramp"]["iload_a"], 0.0)
        self.assertAlmostEqual(sweep.PHASES["ramp"]["rload_ohm"], 36.0)
        # 36 ohm is 1.8 V / 50 mA, i.e. the rated load, not a round number.
        self.assertAlmostEqual(sweep.VOUT_NOM_V / 36.0, 0.05, places=3)

    def test_the_output_network_covers_soft_starts_own_points(self):
        # 1 uF / 100 mOhm main matrix, plus its two 4.7 uF groups.
        self.assertIn(1.0e-6, sweep.CEFFS_F)
        self.assertIn(4.7e-6, sweep.CEFFS_F)
        for esr in (0.1, 0.001, 0.5):
            self.assertIn(esr, sweep.ESRS_OHM)

    def test_all_but_one_config_is_also_a_loop_stability_grid_point(self):
        shared = [(c, e) for c in sweep.CEFFS_F for e in sweep.ESRS_OHM
                  if c in sweep.ls.CEFFS_F and e in sweep.ls.ESRS_OHM]
        total = len(sweep.CEFFS_F) * len(sweep.ESRS_OHM)
        self.assertEqual(len(shared), total - len(sweep.CEFFS_F))  # the 0.1 col


class TestDcSeed(unittest.TestCase):
    def test_the_seed_targets_the_ramp_state_not_the_settled_one(self):
        class P:
            vdd = 3.3
        self.assertIn("v(VOUT)=0.9", sweep.dc_seed_lines(P(), "0.6"))
        self.assertIn("v(VOUT)=1.8", sweep.dc_seed_lines(P(), "free"))
        self.assertIn("v(XDUT.FB)=1.2", sweep.dc_seed_lines(P(), "0.6"))

    def test_the_seed_does_not_reference_the_node_issue_189_deleted(self):
        class P:
            vdd = 3.3
        self.assertNotIn("Xsoftstart.CLG", sweep.dc_seed_lines(P(), "0.6"))
        self.assertNotIn("CLG", nv.SS_BLOCK_RE.search(CORE).group(0))


class TestCrossCheckTolerance(unittest.TestCase):
    def test_it_is_the_movement_class_issues_182_185_established(self):
        self.assertEqual(sweep.XCHECK_PM_TOL_DEG, 2.0)
        self.assertEqual(sweep.XCHECK_GM_TOL_DB, 1.0)

    def test_the_committed_loop_stability_matrix_it_compares_against_exists(self):
        self.assertTrue(sweep.LS_MATRIX_CSV.exists(), sweep.LS_MATRIX_CSV)

    def test_a_delta_inside_the_budget_agrees_and_outside_it_does_not(self):
        def d(pm):
            return (None, {"pm_deg": 0.0}, pm, 0.0, 0.0)
        self.assertTrue(sweep.xcheck_verdict([d(1.9)])[0])
        self.assertFalse(sweep.xcheck_verdict([d(2.1)])[0])
        self.assertFalse(sweep.xcheck_verdict([])[0])


class TestPoleZeroFit(unittest.TestCase):
    """The attribution's arithmetic, against a known answer."""

    @staticmethod
    def synth(fz: float, fp: float, k_db: float = 0.0):
        num, den = [], []
        for i in range(0, 900):
            f = 10 ** (-2 + i / 100.0)
            h = complex(1, f / fz) / complex(1, f / fp)
            m = k_db + 20 * math.log10(abs(h))
            ph = math.degrees(math.atan2(h.imag, h.real))
            num.append((f, m, ph))
            den.append((f, 0.0, 0.0))
        return num, den

    def test_it_recovers_a_known_pole_and_zero(self):
        num, den = self.synth(2e5, 5e4, k_db=0.0)
        k_db, fz, fp, resid = sweep.fit_pole_zero(num, den)
        self.assertLess(abs(math.log10(fz / 2e5)), 0.06)
        self.assertLess(abs(math.log10(fp / 5e4)), 0.06)
        self.assertLess(resid, 0.5)

    def test_curve_extremes_finds_the_largest_deviation(self):
        num, den = self.synth(2e5, 5e4)
        dm, f_dm, dp, f_dp = sweep.curve_extremes(num, den)
        # H = (1+jf/fz)/(1+jf/fp) tends to fp/fz = 0.25 at high frequency,
        # i.e. -12.04 dB; the extremum is signed, and the check is on its size.
        self.assertLess(abs(abs(dm) - 20 * math.log10(2e5 / 5e4)), 0.5)
        self.assertGreater(f_dm, 1e6)
        self.assertGreater(abs(dp), 5.0)

    def test_mismatched_axes_are_refused_not_interpolated(self):
        num, den = self.synth(2e5, 5e4)
        self.assertIsNone(sweep.curve_extremes(num, den[:-1]))
        self.assertIsNone(sweep.fit_pole_zero(num, den[:-1]))


def hov(**kw) -> "sweep.HovPoint":
    base = dict(ssr_cmd=0.6, ssr_v=0.6, fb_v=1.2, vout_v=0.9, pg_v=2.0,
                erramp_v=2.0, isup_a=1e-3)
    base.update(kw)
    return sweep.HovPoint(**base)


def ideal_curve(variant="binj", gm=5e-6, release=1.2, **kw):
    """A HovCurve carrying exactly what `Binj_ss` computes.

    `I = max(0, (VREF - V(SSR)) * 5e-6)`, with VOUT the value the divider then
    puts on the output, so the derived `iinj_a` has to come back out equal to
    the current that was put in.
    """
    pts = []
    for ssr in sweep.HANDOVER_SSR_V:
        i = max(0.0, (release - ssr) * gm)
        fb = sweep.VREF_V
        # KCL at FB, solved for VOUT: I = fb/600k - (vout-fb)/300k
        vout = fb - 300e3 * (i - fb / 600e3)
        pts.append(hov(ssr_cmd=ssr, ssr_v=ssr, fb_v=fb, vout_v=vout))
    base = dict(corner_id="tt_27c_3.30v", corner="tt", temp_c=27.0, vin_v=3.3,
                variant=variant, points=pts)
    base.update(kw)
    return sweep.HovCurve(**base)


class TestHandoverPoint(unittest.TestCase):
    def test_the_injection_current_is_the_same_expression_as_the_margin_rows(self):
        p = hov(fb_v=1.2, vout_v=0.9)
        r = row(fb_v=1.2, vout_v=0.9)
        self.assertAlmostEqual(p.iinj_a, r.iinj_a, places=15)

    def test_it_stays_exact_when_the_loop_is_out_of_regulation(self):
        # FB pushed above VREF with the output at zero: KCL is a statement
        # about the node's branches, not about the loop being closed.
        p = hov(fb_v=1.45, vout_v=0.0)
        self.assertAlmostEqual(p.iinj_a * 1e6, 1.45 / 0.6 + 1.45 / 0.3, places=9)

    def test_in_regulation_is_a_band_around_the_reference(self):
        self.assertTrue(hov(fb_v=sweep.VREF_V).in_regulation)
        self.assertTrue(hov(fb_v=sweep.VREF_V + 0.004).in_regulation)
        self.assertFalse(hov(fb_v=sweep.VREF_V + 0.02).in_regulation)
        self.assertFalse(hov(fb_v=0.0).in_regulation)


class TestHandoverMetricsOnTheKnownIdealElement(unittest.TestCase):
    """The `binj` variant's transfer is closed-form, so the metrics have a
    known answer and are not merely self-consistent."""

    def setUp(self):
        self.c = ideal_curve()

    def test_the_start_current_is_the_intent(self):
        self.assertAlmostEqual(self.c.iinj_start_a * 1e6, 6.0, places=6)

    def test_the_fitted_transconductance_is_the_intent(self):
        self.assertAlmostEqual(self.c.gm_a_per_v * 1e6,
                               -sweep.HANDOVER_INTENT_GM_UA_PER_V, places=6)

    def test_it_releases_exactly_at_vref(self):
        self.assertAlmostEqual(self.c.release_ssr_v,
                               sweep.HANDOVER_INTENT_RELEASE_V, places=6)
        self.assertAlmostEqual(self.c.release_overshoot_v, 0.0, places=6)

    def test_nothing_is_left_flowing_at_vref(self):
        self.assertAlmostEqual(self.c.iinj_at_vref_a, 0.0, places=12)

    def test_the_ideal_element_never_takes_the_loop_out_of_regulation(self):
        self.assertIsNone(self.c.saturated_to_ssr_v)

    def test_interpolation_hits_the_analytic_value_between_samples(self):
        # 0.6125 V is deliberately off the 25 mV grid.
        self.assertAlmostEqual(self.c.iinj_at(0.6125) * 1e6,
                               (1.2 - 0.6125) * 5.0, places=4)


class TestHandoverMetricsCatchTheDefectsTheyExistToCatch(unittest.TestCase):
    def test_a_soft_tail_is_not_reported_as_a_release(self):
        """A threshold crossing that is not final must not count.

        This is the difference between "the element let go" and "the element
        dipped": a transfer that goes below the release threshold and comes
        back has not released, and reporting the first crossing would flatter
        it by exactly the width of the dip.
        """
        c = ideal_curve()
        self.assertAlmostEqual(c.release_ssr_v, 1.2, places=6)
        # put 1 uA back at 2.0 V, well past where the transfer first went
        # quiet, and leave the points above it quiet again
        i = next(k for k, p in enumerate(c.points) if abs(p.ssr_v - 2.0) < 1e-9)
        c.points[i].vout_v = c.points[i].fb_v - 300e3 * (
            1e-6 - c.points[i].fb_v / 600e3)
        self.assertAlmostEqual(c.release_ssr_v, c.points[i + 1].ssr_v,
                               places=6)

    def test_an_element_that_never_releases_reports_none_not_the_last_point(self):
        c = ideal_curve(release=99.0)     # still injecting everywhere
        self.assertIsNone(c.release_ssr_v)
        self.assertIsNone(c.release_overshoot_v)

    def test_an_over_injecting_element_is_reported_as_out_of_regulation(self):
        c = ideal_curve()
        for p in c.points[:5]:
            p.fb_v = 1.45
            p.vout_v = 0.0
        self.assertAlmostEqual(c.saturated_to_ssr_v, c.points[4].ssr_v,
                               places=6)
        self.assertAlmostEqual(c.fb_max_v, 1.45, places=9)

    def test_the_transconductance_fit_ignores_the_saturated_bottom(self):
        """A railed loop is not part of the element's linear range.

        Left in, the out-of-regulation points drag the fitted slope away from
        the transconductance the element actually has where it is in control.
        """
        c = ideal_curve()
        for p in c.points[:8]:
            p.fb_v = 1.45
            p.vout_v = 0.0
        self.assertAlmostEqual(c.gm_a_per_v * 1e6,
                               -sweep.HANDOVER_INTENT_GM_UA_PER_V, places=6)

    def test_the_acquisition_step_is_the_landed_output_not_a_recomputation(self):
        """It has to stay true where the loop is railed.

        Recomputing the step from `I_inj` would report a large negative
        "step" at a saturated ramp state, where the truth is that the output
        is held at zero by a railed error amplifier and there is no step at
        all -- the failure there is the recovery out of saturation, which is a
        different mechanism and belongs in a different sentence.
        """
        c = ideal_curve()
        i = next(k for k, p in enumerate(c.points) if abs(p.ssr_v - 0.05) < 1e-9)
        self.assertAlmostEqual(c.acquisition_step_v(0.05), c.points[i].vout_v,
                               places=12)
        # the ideal element's step is the ramp's own value, 1.5 * V(SSR)
        self.assertAlmostEqual(c.acquisition_step_v(0.05), 1.5 * 0.05, places=6)
        for p in c.points[:i + 1]:
            p.fb_v, p.vout_v = 1.45, 0.0
        self.assertAlmostEqual(c.acquisition_step_v(0.05), 0.0, places=12)

    def test_the_acquisition_state_is_one_of_the_pinned_margin_states(self):
        """The DC transfer and the margins have to be able to talk about the
        same ramp state, or neither can say anything about the other."""
        self.assertIn(sweep.HANDOVER_ACQUISITION_SSR_V,
                      sweep.PHASES["ramp"]["ssr"])
        self.assertIn(sweep.HANDOVER_ACQUISITION_SSR_V, sweep.HANDOVER_SSR_V)

    def test_the_release_threshold_is_small_against_the_divider_current(self):
        # VREF/600k = 2 uA flows in the divider at the settled point; the
        # release bar has to be small against it or "released" means nothing.
        self.assertLess(sweep.HANDOVER_RELEASE_A, 0.05 * sweep.VREF_V / 600e3)


class TestHandoverDeck(unittest.TestCase):
    TEMPLATE = (_TB / "tb_ss_handover.spice.in").read_text()

    class _Corner:
        name = "tt"
        sections = ("typical", "res_typical", "bjt_typical", "diode_typical",
                    "moscap_typical", "mimcap_typical")

    class _Pvt:
        temp_c, vdd, corner_id = 27.0, 3.3, "tt_27c_3.30v"
        corner = None

    class _Pdk:
        design_include, model_lib = "/d.ngspice", "/m.ngspice"

    def render(self, variant):
        pvt = self._Pvt()
        pvt.corner = self._Corner()
        return sweep.render_handover_deck(pvt, self._Pdk(), variant=variant,
                                          netlist=Path("/n.spice"))

    def test_every_placeholder_is_substituted_for_both_variants(self):
        for variant in nv.DUT_VARIANTS:
            with self.subTest(variant=variant):
                self.assertEqual(
                    sweep.TOKEN_RE.findall(self.render(variant)), [])

    def test_it_is_the_same_circuit_and_the_same_break_as_the_margin_deck(self):
        margin = (_TB / "tb_ss_loop_gain.spice.in").read_text()
        for line in ("Xdut VIN VOUT EN 0 AINJ BINJ VREF SSRPIN ldo_core",
                     "Vinj AINJ BINJ DC 0 AC 0",
                     "Vref VREF 0 DC 1.2"):
            self.assertIn(line, self.TEMPLATE)
            self.assertIn(line, margin)

    def test_it_uses_the_ramp_phases_load_model(self):
        self.assertIn(f"Rload VOUT NLD {sweep.RATED_LOAD_OHM:g}", self.TEMPLATE)
        self.assertEqual(sweep.PHASES["ramp"]["rload_ohm"],
                         sweep.RATED_LOAD_OHM)

    def test_it_pins_the_model_binning_flag(self):
        self.assertIn(".options wnflag=1", self.TEMPLATE)

    def test_neither_variant_names_the_retired_mirror_node(self):
        """Issue #239: `has_gmsum`/the `GMSUM_*` substitutions are retired.

        Pre-#231 `device` was the post-#195 device-level chain and had a real
        `GMSUM` mirror node; post-#231 it is `Binj_ss`, same as `binj`, and
        there is no such node in either variant's netlist for a deck to name.
        An actual PDK run confirmed the pre-fix `device` deck's
        `v(xdut.xsoftstart.gmsum)` reference did not error but silently
        produced an empty field -- this is the node-existence check that
        closes that gap, not just a template-substitution check.
        """
        dev, binj = self.render("device"), self.render("binj")
        for text in (dev, binj):
            # The template's own retirement comment mentions "gmsum" by name
            # (institutional memory); what must be gone is any executable
            # reference to the node itself.
            self.assertNotIn("v(xdut.xsoftstart.gmsum)", text.lower())
            self.assertNotIn("gmsum_v=", text.lower())
            self.assertNotIn("let gmsum_dc", text.lower())

    def test_the_field_list_matches_the_decks_own_echo(self):
        """The parser's field list and the deck's advertised columns are two
        statements of the same thing; if they drift, the record's columns are
        mislabelled and nothing catches it."""
        for variant in nv.DUT_VARIANTS:
            with self.subTest(variant=variant):
                m = re.search(r'echo "\* columns: HOV ([^"]*)"',
                              self.render(variant))
                self.assertIsNotNone(m)
                named = tuple(t.rstrip("=") for t in m.group(1).split())
                self.assertEqual(named, sweep.HOV_FIELDS)

    def test_the_echoed_line_emits_exactly_the_advertised_columns(self):
        """...and so are the column list and the line that is actually
        written, which is what the parser has to accept."""
        for variant in nv.DUT_VARIANTS:
            with self.subTest(variant=variant):
                text = self.render(variant)
                echo = next(l for l in text.splitlines()
                            if l.strip().startswith('echo "HOV '))
                body = echo.strip()[len('echo "HOV '):].rstrip('"')
                emitted = tuple(t.split("=", 1)[0] for t in body.split())
                cols = re.search(r'echo "\* columns: HOV ([^"]*)"', text)
                self.assertEqual(
                    emitted,
                    tuple(t.rstrip("=") for t in cols.group(1).split()))
                # and the parser accepts a line of exactly that shape
                sweep.parse_hov_fields(
                    "HOV " + " ".join(f"{k}=1.0" for k in emitted))

    def test_the_ssr_grid_spans_the_whole_ramp_including_past_vref(self):
        self.assertEqual(sweep.HANDOVER_SSR_V[0], 0.0)
        self.assertGreater(sweep.HANDOVER_SSR_V[-1], sweep.VREF_V + 1.0)
        step = sweep.HANDOVER_SSR_V[1] - sweep.HANDOVER_SSR_V[0]
        self.assertLessEqual(step, 0.05)
        for a, b in zip(sweep.HANDOVER_SSR_V, sweep.HANDOVER_SSR_V[1:]):
            self.assertAlmostEqual(b - a, step, places=9)


class TestHovParsing(unittest.TestCase):
    GOOD = ("HOV ssr_cmd=0.6 ssr_v=0.6 fb_v=1.2 vout_v=0.9 pg_v=2 "
            "erramp_v=2 isup_a=1e-3")

    def test_the_required_fields_are_required(self):
        self.assertEqual(set(sweep.parse_hov_fields(self.GOOD)),
                         set(sweep.HOV_FIELDS))

    def test_the_retired_mirror_node_field_is_now_unknown(self):
        """Issue #239, reconstructed: `gmsum_v` used to be optional (the
        `device` variant's now-removed `GMSUM` mirror node); with `has_gmsum`
        retired there is no variant that can legitimately emit it any more,
        so it must be rejected exactly like any other unknown field."""
        with self.assertRaises(ValueError):
            sweep.parse_hov_fields(self.GOOD + " gmsum_v=2.3")

    def test_a_missing_field_is_an_error_not_a_default(self):
        with self.assertRaises(ValueError):
            sweep.parse_hov_fields(self.GOOD.replace(" pg_v=2", ""))

    def test_an_unknown_field_is_rejected(self):
        with self.assertRaises(ValueError):
            sweep.parse_hov_fields(self.GOOD + " nonsense=1")

    def test_a_positional_field_is_rejected(self):
        with self.assertRaises(ValueError):
            sweep.parse_hov_fields(self.GOOD + " 1.234")

    def test_every_rejection_still_names_the_HOV_line_not_a_ROW_line(self):
        """The strictness is `harness.report.parse_row_fields()`, shared with
        the margin decks' `ROW` lines, so the one thing delegation could lose
        is which line kind the operator is being told about. Each failure mode
        must still say `HOV`, because that is the word in the log line they
        will go read."""
        for bad in (self.GOOD + " 1.234",            # positional
                    self.GOOD.replace(" pg_v=2", ""),  # missing
                    self.GOOD + " nonsense=1",       # unknown
                    self.GOOD + " pg_v=3"):          # repeated
            with self.subTest(line=bad):
                with self.assertRaises(ValueError) as cm:
                    sweep.parse_hov_fields(bad)
                msg = str(cm.exception)
                # prefix, not containment: the echoed line is part of every
                # message, so `assertIn("HOV", ...)` would hold for any tag
                self.assertTrue(msg.startswith("HOV "), msg)
                self.assertNotIn("ROW", msg)


class TestHandoverConsistencyCheck(unittest.TestCase):
    def test_it_compares_only_states_the_two_decks_actually_share(self):
        c = ideal_curve(variant="device")
        r = row(variant="device", phase="ramp", ssr_cmd="0.6", ssr_v=0.6,
                ceff_f=1e-6, esr_ohm=0.1, vout_v=c.iinj_at(0.6) * 0 + 0.9)
        worst, n = sweep.handover_consistency([c], [r])
        self.assertEqual(n, 1)
        # the sink/anchor phases use a different load model, so they are not
        # comparable and must not be counted
        other = row(variant="device", phase="sink", ssr_cmd="1.25", ssr_v=1.25,
                    ceff_f=1e-6, esr_ohm=0.1)
        _, n2 = sweep.handover_consistency([c], [r, other])
        self.assertEqual(n2, 1)

    def test_a_ramp_state_the_transfer_did_not_sample_is_not_compared(self):
        c = ideal_curve(variant="device")
        r = row(variant="device", phase="ramp", ssr_cmd="0.61", ssr_v=0.61,
                ceff_f=1e-6, esr_ohm=0.1)
        _, n = sweep.handover_consistency([c], [r])
        self.assertEqual(n, 0)


class TestKltFrontEnd(unittest.TestCase):
    """The `klt sim` batch front end: request shape and report parsing.

    Issue #451 moved this experiment's grid onto `klt sim`, so
    ``klt_run.py`` now decides what is simulated and how the returned report
    becomes `ROW`/`HOV` lines. Nothing here needs klt installed or a
    simulator: the request is a dict and the report is a dict, so both sides
    are checked against the deck's own strict parsers offline.

    These are *not* a substitute for a real batch run -- they cannot catch a
    klt-side schema change, only a drift between this front end and the
    decks it stands in for.
    """

    DUT = _TB / "sweep.py"      # any file: only copied and named, never simulated
    AXES = {"process": ("tt",), "temps": (27.0,), "supplies": (2.97, 3.30)}
    CID = "tt_27c_3.30v"
    FULL = dict(ssr_v=0.05, fb_v=1.2, vout_v=0.075, isup_a=1e-4,
                dcgain_db=60.0, f0_hz=1e5, phase_at_f0_deg=-120.0,
                f180_hz=1e6, gain_at_f180_db=15.0, f0_rising_hz=2e5,
                resurgence_db=-1.0)

    @property
    def klt_run(self):
        return sweep.klt_run

    def margin_request(self, phase):
        return self.klt_run.margin_job(
            "t", sweep.PHASES[phase], 1e-6, 0.1, self.DUT, 400, "0.01", "1e9",
            self.AXES).request()

    @staticmethod
    def corner(ssr, vals, diags=()):
        return {"process": "tt", "temperature_c": 27.0, "status": "ok",
                "passes": [], "params": {"vsup": 3.3, "vssr": ssr},
                "diagnostics": list(diags),
                "measurements": [{"name": k, "value": v, "status": "ok"}
                                 for k, v in vals.items()]}

    def test_a_pinned_phase_zips_the_supply_with_every_ramp_state(self):
        """Both axes are `.param` rows, not an `alter` of a source.

        The supply and V(SSR) have to be swept as corner parameters so each
        (supply, ramp state) pair is its own corner in the report; collapsing
        either into an `alter` would make the two indistinguishable on the
        way back.
        """
        ramp = sweep.PHASES["ramp"]
        prm = self.margin_request("ramp")["corners"]["params"]
        self.assertEqual(len(prm["vsup"]), 2 * len(ramp["ssr"]))
        self.assertEqual(len(prm["vssr"]), 2 * len(ramp["ssr"]))
        self.assertEqual(
            set(zip(prm["vsup"], prm["vssr"])),
            {(s, v) for s in self.AXES["supplies"] for v in ramp["ssr"]})
        self.assertNotIn("supply_v", self.margin_request("ramp")["corners"])

    def test_the_anchor_phase_has_no_ramp_axis_and_leaves_ssrpin_floating(self):
        req = self.margin_request("anchor")
        self.assertEqual(list(req["corners"]["params"]), ["vsup"])
        body = self.klt_run.margin_body(sweep.PHASES["anchor"], 1e-6, 0.1)
        self.assertFalse(any(ln.startswith("Vssr ")
                             for ln in body.splitlines()),
                         "the anchor phase must not pin SSRPIN")

    def test_the_margin_request_grades_every_margin_field_as_a_tian_metric(self):
        req = self.margin_request("anchor")
        self.assertEqual([p["name"] for p in req["analysis"]["passes"]],
                         ["inj_v", "inj_i"])
        self.assertEqual(
            {m["name"] for m in req["measurements"]},
            {"ssr_v", "fb_v", "vout_v", "isup_a", *self.klt_run.ROW_METRICS},
            "a margin field that is not a measurement is ungraded")

    def test_the_handover_request_is_an_op_sweep_with_no_tian(self):
        req = self.klt_run.handover_job(
            "h", self.DUT, sweep.HANDOVER_SSR_V, self.AXES).request()
        self.assertEqual(req["analysis"]["kind"], "op")
        self.assertEqual(len(req["corners"]["params"]["vssr"]),
                         len(self.AXES["supplies"]) * len(sweep.HANDOVER_SSR_V))
        self.assertTrue(all("tian" not in m for m in req["measurements"]))
        self.assertEqual({m["name"] for m in req["measurements"]},
                         set(sweep.HOV_FIELDS) - {"ssr_cmd"})

    def test_report_values_are_keyed_by_corner_and_ramp_state(self):
        """Two ramp states at one corner must stay two entries.

        Keying on the corner alone would silently keep whichever ramp state
        klt happened to return last and report it for all of them.
        """
        vals, probs = self.klt_run.collect(
            {"corners": [self.corner(0.05, self.FULL),
                         self.corner(1.15, dict(self.FULL, ssr_v=1.15))]})
        self.assertEqual(probs, [])
        self.assertEqual(set(vals), {(self.CID, "0.05"), (self.CID, "1.15")})
        self.assertEqual(vals[(self.CID, "0.05")]["ssr_v"], 0.05)
        self.assertEqual(vals[(self.CID, "1.15")]["ssr_v"], 1.15)

    def test_klt_written_row_lines_parse_with_the_decks_own_strict_parser(self):
        """The front end has to emit exactly what the deck emits.

        `parse_row_fields` is the same strict parser used on a local
        ngspice log, so this is the assertion that a batch row and a local
        row are the same record. The gain margin is also sign-flipped on the
        way through: klt reports the gain at the -180 deg crossing, the deck
        reports its negation.
        """
        vals, _ = self.klt_run.collect(
            {"corners": [self.corner(0.05, self.FULL),
                         self.corner(1.15, dict(self.FULL, ssr_v=1.15))]})
        log = self.klt_run.margin_log(
            self.CID, "device", "ramp", {"ssr": (0.05, 1.15)}, [1e-6], [0.1],
            {("device", "ramp", 1e-6, 0.1): vals})
        rows = [sweep.parse_row_fields(ln)
                for ln in log.splitlines() if ln.startswith("ROW ")]
        self.assertEqual([r["ssr_cmd"] for r in rows], ["0.05", "1.15"],
                         "the ramp state is the outermost loop")
        self.assertEqual(float(rows[0]["gain_at_f180_db"]), -15.0)

    def test_a_metric_klt_reports_unavailable_is_an_empty_row_field(self):
        """No -180 deg crossing in band is an absence, not a problem.

        Locally that is a `meas` that found nothing and wrote an empty
        field; through klt it arrives as a `tian_metric_unavailable`
        diagnostic. Both have to land as the same empty field, or the batch
        path would turn a legitimately unmeasurable corner into a failure.
        """
        gone = dict(self.FULL, f180_hz=None, gain_at_f180_db=None)
        diag = [{"code": "measurement",
                 "message": f"[tian_metric_unavailable] measurement "
                            f"'{n}': no crossing"}
                for n in ("f180_hz", "gain_at_f180_db")]
        vals, probs = self.klt_run.collect(
            {"corners": [self.corner(0.05, gone, diag)]})
        self.assertEqual(probs, [])
        line = self.klt_run.row_line("0.05", 1e-6, 0.1, vals[(self.CID, "0.05")])
        self.assertEqual(sweep.parse_row_fields(line)["f180_hz"], "")

    def test_klt_written_hov_lines_parse_with_the_handover_strict_parser(self):
        hlog = self.klt_run.handover_log(
            self.CID, (0.05,), {(self.CID, "0.05"): self.FULL})
        line = next(ln for ln in hlog.splitlines() if ln.startswith("HOV "))
        self.assertEqual(sweep.parse_hov_fields(line)["ssr_cmd"], "0.05")


class TestRecordIsAppendOnly(unittest.TestCase):
    def test_the_sweep_writes_through_the_guarded_helper(self):
        src = (_TB / "sweep.py").read_text()
        self.assertIn("write_markdown_record(record_id, md, records_dir)", src)
        self.assertNotIn(".write_text(md)", src)


if __name__ == "__main__":
    unittest.main()
