#!/usr/bin/env python3
"""Unit tests for layout/lvs_form.py -- the passive-form rewrite.

    python3 -m unittest discover -s layout/tests -v

No PDK, klayout or xschem required: the inputs here are verbatim xschem
exports (captured from `layout/passives/drclvs_passives.sch` and
`design/error_amp.sch`) and the assertions are about the text that comes out.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT_DIR))

import lvs_form  # noqa: E402

# Exactly what `xschem --rcfile layout/xschemrc` emits for
# layout/passives/drclvs_passives.sch: the FET in LVS form (its symbol has an
# lvs_format), both passives still in simulation form (theirs do not).
PASSIVES_EXPORT = """\
** sch_path: layout/passives/drclvs_passives.sch
.subckt drclvs_passives RP RM CT CB D G S VSS
*.PININFO RP:B RM:B CT:B CB:B D:B G:I S:B VSS:B
XR1 RM RP VSS ppolyf_u_1k r_width=1u r_length=10u m=1
XC1 CT CB cap_mim_2f0_m4m5_noshield c_width=20u c_length=20u m=1
M1 D G S VSS nfet_03v3 L=0.28u W=6u nf=2 m=1
.ends
"""


class RewritePassivesTests(unittest.TestCase):
    """The core translation: simulation form -> primitive R/C elements."""

    def test_resistor_becomes_a_primitive_r_with_l_and_w(self):
        out, count = lvs_form.rewrite_passives(
            "XRbias NBIAS RBT VSS ppolyf_u_1k r_width=1u r_length=1000u m=1\n"
        )
        self.assertEqual(count, 1)
        self.assertEqual(
            out, "Rbias NBIAS RBT VSS ppolyf_u_1k l=1000u w=1u m=1\n"
        )

    def test_capacitor_becomes_a_primitive_c_with_l_and_w(self):
        out, count = lvs_form.rewrite_passives(
            "XCc NZ OUT cap_mim_2f0_m2m3_noshield c_width=48u c_length=48u m=1\n"
        )
        self.assertEqual(count, 1)
        self.assertEqual(
            out, "Cc NZ OUT cap_mim_2f0_m2m3_noshield l=48u w=48u m=1\n"
        )

    def test_length_and_width_are_not_transposed(self):
        """r_length -> l and r_width -> w, which is the whole point.

        Measured against the PDK deck (issue #313): the compare ignores `r`
        entirely but a wrong `l` or a wrong `w` mismatches, so transposing the
        two would produce a netlist that is silently wrong for every
        non-square device.
        """
        out, _ = lvs_form.rewrite_passives(
            "XRz NZ N1 VSS ppolyf_u_3k r_width=1u r_length=1970.88u m=1\n"
        )
        self.assertIn("l=1970.88u", out)
        self.assertIn("w=1u", out)

    def test_extra_parameters_are_carried_through_in_order(self):
        out, _ = lvs_form.rewrite_passives(
            "XR1 A B VSS ppolyf_u_1k r_width=1u m=2 r_length=5u par=1 s=1\n"
        )
        self.assertEqual(out, "R1 A B VSS ppolyf_u_1k l=5u w=1u m=2 par=1 s=1\n")

    def test_a_two_terminal_resistor_keeps_both_nets(self):
        out, count = lvs_form.rewrite_passives(
            "XR1 A B ppolyf_u_1k r_width=1u r_length=5u m=1\n"
        )
        self.assertEqual(count, 1)
        self.assertEqual(out, "R1 A B ppolyf_u_1k l=5u w=1u m=1\n")

    def test_the_whole_passives_export_rewrites_both_passives_only(self):
        out, count = lvs_form.rewrite_passives(PASSIVES_EXPORT)
        self.assertEqual(count, 2)
        lines = out.splitlines()
        self.assertIn("R1 RM RP VSS ppolyf_u_1k l=10u w=1u m=1", lines)
        self.assertIn(
            "C1 CT CB cap_mim_2f0_m4m5_noshield l=20u w=20u m=1", lines
        )
        # the FET line and every structural line survive untouched
        self.assertIn("M1 D G S VSS nfet_03v3 L=0.28u W=6u nf=2 m=1", lines)
        self.assertIn(".subckt drclvs_passives RP RM CT CB D G S VSS", lines)
        self.assertIn("*.PININFO RP:B RM:B CT:B CB:B D:B G:I S:B VSS:B", lines)
        self.assertIn(".ends", lines)

    def test_the_rewritten_export_no_longer_trips_drclvs_sim_form_guard(self):
        """The guard this rewrite exists to get past, asserted directly."""
        import drclvs  # imported here so the test file stands alone  # noqa: E402

        self.assertIsNotNone(drclvs.SIM_FORM_RE.search(PASSIVES_EXPORT))
        out, _ = lvs_form.rewrite_passives(PASSIVES_EXPORT)
        self.assertIsNone(drclvs.SIM_FORM_RE.search(out))

    def test_trailing_newline_is_preserved_either_way(self):
        with_nl, _ = lvs_form.rewrite_passives("XR1 A B ppolyf_u_1k r_width=1u r_length=5u\n")
        self.assertTrue(with_nl.endswith("\n"))
        without, _ = lvs_form.rewrite_passives("XR1 A B ppolyf_u_1k r_width=1u r_length=5u")
        self.assertFalse(without.endswith("\n"))


class ConservatismTests(unittest.TestCase):
    """What the rewrite must NOT touch."""

    def test_a_hierarchical_subcircuit_call_is_left_alone(self):
        line = "Xamp IN OUT VDD VSS error_amp\n"
        out, count = lvs_form.rewrite_passives(line)
        self.assertEqual(count, 0)
        self.assertEqual(out, line)

    def test_a_mos_simulation_form_line_is_left_alone(self):
        """Not this module's job -- and SIM_FORM_RE must still catch it.

        A FET in simulation form means `lvs_netlist` did not take effect at
        all, which is a different failure with a different fix (an xschem too
        old to know about `lvs_format`). Silently "repairing" it here would
        hide that.
        """
        line = "XM1 D G S VSS nfet_03v3 L=0.28u W=2u nf=1 ad='int((nf+1)/2)*W'\n"
        out, count = lvs_form.rewrite_passives(line)
        self.assertEqual(count, 0)
        self.assertEqual(out, line)

    def test_a_half_specified_passive_is_left_alone(self):
        """Width without length: not a family this module recognises."""
        line = "XR1 A B ppolyf_u_1k r_width=1u m=1\n"
        out, count = lvs_form.rewrite_passives(line)
        self.assertEqual(count, 0)
        self.assertEqual(out, line)

    def test_comments_and_control_lines_are_left_alone(self):
        text = "* a comment\n.subckt foo A B\n.ends\n"
        out, count = lvs_form.rewrite_passives(text)
        self.assertEqual(count, 0)
        self.assertEqual(out, text)


class NamingConventionTests(unittest.TestCase):
    """The schematic-authoring convention layout/xschemrc documents."""

    def test_a_resistor_not_named_r_is_a_loud_error(self):
        with self.assertRaises(lvs_form.LvsFormError) as caught:
            lvs_form.rewrite_passives(
                "XdivTop A B VSS ppolyf_u_1k r_width=1u r_length=5u m=1\n"
            )
        message = str(caught.exception)
        self.assertIn("divTop", message)
        self.assertIn("xschemrc", message)

    def test_a_capacitor_not_named_c_is_a_loud_error(self):
        with self.assertRaises(lvs_form.LvsFormError):
            lvs_form.rewrite_passives(
                "Xmiller A B cap_mim_2f0_m4m5_noshield c_width=5u c_length=5u m=1\n"
            )

    def test_the_letter_check_is_case_insensitive(self):
        """SPICE is case-insensitive, so `Xcomp` is a legitimate capacitor."""
        out, count = lvs_form.rewrite_passives(
            "Xcomp A B cap_mim_2f0_m4m5_noshield c_width=5u c_length=5u m=1\n"
        )
        self.assertEqual(count, 1)
        self.assertTrue(out.startswith("comp A B "), out)

    def test_a_bare_x_with_no_name_is_a_loud_error(self):
        with self.assertRaises(lvs_form.LvsFormError):
            lvs_form.rewrite_passives(
                "X A B ppolyf_u_1k r_width=1u r_length=5u m=1\n"
            )


class UnrenderedDeviceLineTests(unittest.TestCase):
    """The family-agnostic backstop behind drclvs.py's SIM_FORM_RE guard."""

    def test_a_hierarchical_subcircuit_call_is_not_a_device(self):
        self.assertEqual(
            lvs_form.unrendered_device_lines("Xamp IN OUT VDD VSS error_amp\n"), []
        )

    def test_a_bjt_in_simulation_form_is_reported(self):
        """A family SIM_FORM_RE does not name, so nothing else would catch it."""
        line = "Xq1 C B E npn_05p00x05p00 m=1"
        self.assertEqual(lvs_form.unrendered_device_lines(line + "\n"), [line])

    def test_a_rewritten_export_has_no_stragglers(self):
        out, _ = lvs_form.rewrite_passives(PASSIVES_EXPORT)
        self.assertEqual(lvs_form.unrendered_device_lines(out), [])

    def test_an_unrewritten_export_reports_both_passives(self):
        self.assertEqual(len(lvs_form.unrendered_device_lines(PASSIVES_EXPORT)), 2)

    def test_structural_lines_are_never_reported(self):
        self.assertEqual(
            lvs_form.unrendered_device_lines(
                ".subckt cell A B\n*.PININFO A:B B:B\nM1 A B A A nfet_03v3 W=2u\n.ends\n"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
