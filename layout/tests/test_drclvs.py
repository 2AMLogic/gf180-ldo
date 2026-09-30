#!/usr/bin/env python3
"""Unit tests for layout/drclvs.py's host-independent parts.

    python3 -m unittest discover -s layout/tests -v

No PDK, klayout, or xschem required: these tests exercise ``write_record()``'s
append-only guard, the ``--cell`` registry, the LVS negative-control contract
(``ControlRegistryTests`` -- a registered control that cannot corrupt its own
cell's netlist must be a hard error, never a silently skipped stage), and
``deck_env()``'s pmap(1) stand-in -- not the DRC/LVS stages themselves.
"""

from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT_DIR))

import drclvs  # noqa: E402

sys.path.insert(0, str(LAYOUT_DIR.parent / "sim"))
from harness.pdk import Pdk  # noqa: E402
from harness.report import RecordExists  # noqa: E402


def fake_pdk(root: Path) -> Pdk:
    return Pdk(path=root, variant="gf180mcuD", source="test")


def fake_summary(record_id: str) -> dict:
    return {
        "record_id": record_id,
        "netlist_devices": 1,
        "klt_drc": {"status": "clean", "violations": 0, "dbu_um": 0.001},
        "pdk_drc": {"violations": 0, "rule_categories": 1, "rule_tables": 1},
        "lvs": {"match": True, "warnings": []},
        "lvs_negative_controls": {
            "topology": {"match": False, "mutation": "gate shorted to drain"},
            "parameter": {"match": False, "mutation": "device width doubled"},
        },
    }


class WriteRecordTests(unittest.TestCase):
    """write_record() must go through harness.report's append-only guard.

    Regression test for the gap #142 closes: write_record() used to write
    unconditionally via a hand-rolled mkdir/write_text, silently overwriting
    a record a concurrent --record run already spent for the same id.
    """

    def test_refuses_to_overwrite_an_existing_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            records_dir = Path(tmp) / "records"
            pdk = fake_pdk(Path(tmp) / "pdk")
            rid = "20260821-000000-abc1234"
            summary = fake_summary(rid)

            original_records_dir = drclvs.RECORDS_DIR
            drclvs.RECORDS_DIR = records_dir
            spec = drclvs.TESTCELL_SPEC
            try:
                path = drclvs.write_record(rid, summary, pdk, spec)
                self.assertEqual(path, records_dir / f"{rid}.md")
                first_text = path.read_text()
                self.assertIn(rid, first_text)

                with self.assertRaises(RecordExists):
                    drclvs.write_record(rid, summary, pdk, spec)

                # the first record must not have been clobbered
                self.assertEqual(path.read_text(), first_text)
            finally:
                drclvs.RECORDS_DIR = original_records_dir


class DeckEnvTests(unittest.TestCase):
    """The pmap(1) stand-in that keeps the PDK decks runnable off Linux."""

    def test_real_pmap_is_used_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            original = drclvs.tool_path
            drclvs.tool_path = lambda name: "/usr/bin/pmap"
            try:
                env, provenance = drclvs.deck_env(run_dir)
            finally:
                drclvs.tool_path = original
            self.assertEqual(provenance, "host")
            self.assertFalse((run_dir / "shims").exists())
            self.assertEqual(env["PATH"], os.environ["PATH"])

    def test_missing_pmap_gets_an_executable_shim_on_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            original = drclvs.tool_path
            drclvs.tool_path = lambda name: None
            try:
                env, provenance = drclvs.deck_env(run_dir)
            finally:
                drclvs.tool_path = original
            self.assertEqual(provenance, "shimmed")
            shim = run_dir / "shims" / "pmap"
            self.assertTrue(os.access(shim, os.X_OK), shim)
            self.assertEqual(env["PATH"].split(os.pathsep)[0], str(run_dir / "shims"))

    def test_shim_output_survives_the_decks_column_slice(self):
        """The decks do `pmap <pid> | tail -1`[10, 40].strip` -- that must not be nil.

        Reproduces the exact Ruby expression from the gf180mcu decks' logger
        formatter against the shim's real output: a shim whose line is shorter
        than 11 characters would slice to nil and crash the deck the same way
        a missing pmap does.
        """
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            original = drclvs.tool_path
            drclvs.tool_path = lambda name: None
            try:
                drclvs.deck_env(run_dir)
            finally:
                drclvs.tool_path = original
            proc = subprocess.run(
                [str(run_dir / "shims" / "pmap"), str(os.getpid())],
                capture_output=True, text=True, check=True,
            )
            last = proc.stdout.splitlines()[-1]
            sliced = last[10:50].strip()     # Ruby's String#[10, 40] then .strip
            self.assertTrue(sliced, f"empty slice from {last!r}")
            self.assertTrue(sliced.endswith("K"), sliced)
            self.assertTrue(sliced[:-1].strip().isdigit(), sliced)


class CellRegistryTests(unittest.TestCase):
    """The --cell registry this issue's generalization introduces."""

    def test_testcell_is_the_default_and_is_registered(self):
        self.assertIn("testcell", drclvs.CELLS)
        self.assertIs(drclvs.CELLS["testcell"], drclvs.TESTCELL_SPEC)
        self.assertEqual(drclvs.TESTCELL_SPEC.key, "testcell")

    def test_the_passive_vehicle_is_registered(self):
        self.assertIn("passives", drclvs.CELLS)
        self.assertIs(drclvs.CELLS["passives"], drclvs.PASSIVES_SPEC)

    def test_cell_spec_paths_exist_in_the_repo(self):
        for spec in drclvs.CELLS.values():
            self.assertTrue(spec.gen_gds.is_file(), spec.gen_gds)
            self.assertTrue(spec.schematic.is_file(), spec.schematic)
            # a .sym beside the .sch is what forces a real `.subckt` line
            self.assertTrue(
                spec.schematic.with_suffix(".sym").is_file(),
                spec.schematic.with_suffix(".sym"),
            )

    def test_unknown_cell_is_rejected_by_argument_parsing(self):
        with self.assertRaises(SystemExit):
            drclvs.main(["--cell", "not-a-registered-cell", "--check-env"])

    def test_every_registered_cell_is_driveable(self):
        for key, spec in drclvs.CELLS.items():
            with self.subTest(cell=key):
                self.assertEqual(spec.key, key)
                self.assertTrue(spec.gen_gds.is_file(), spec.gen_gds)
                self.assertTrue(spec.schematic.is_file(), spec.schematic)


def committed_netlist(spec: drclvs.CellSpec) -> str:
    return (spec.netlist_dir / f"{spec.cell}.spice").read_text()


class ControlRegistryTests(unittest.TestCase):
    """The LVS evidence contract, as a check rather than a convention.

    `layout/README.md` is explicit that an LVS ``MATCH`` is not evidence
    unless a known-wrong netlist demonstrably fails. Before PR #283's
    ``--cell`` registry grew a second cell, both negative controls were
    module-global and keyed off the netlist's first MOS (``M*``) element
    line -- so the first all-passive cell registered would have had **two
    controls that could not fire**, and a run that reported a clean
    ``MATCH`` on the strength of two stages that did nothing.

    These tests hold the fix: controls are per-``CellSpec``, every cell must
    register one of each required kind, and a control that cannot corrupt
    the netlist it is pointed at raises rather than being skipped.
    """

    def test_every_registered_cell_carries_both_kinds_of_control(self):
        for key, spec in drclvs.CELLS.items():
            with self.subTest(cell=key):
                drclvs.require_control_pair(spec)
                self.assertEqual(
                    sorted(c.tag for c in spec.controls),
                    sorted(drclvs.REQUIRED_CONTROL_TAGS),
                )

    def test_a_missing_control_kind_is_rejected(self):
        spec = dataclasses.replace(
            drclvs.TESTCELL_SPEC, controls=drclvs.MOS_CONTROLS[:1]
        )
        with self.assertRaises(drclvs.StageError) as caught:
            drclvs.require_control_pair(spec)
        self.assertIn("parameter", str(caught.exception))

    def test_a_duplicated_control_kind_is_rejected(self):
        spec = dataclasses.replace(
            drclvs.TESTCELL_SPEC,
            controls=drclvs.MOS_CONTROLS + drclvs.MOS_CONTROLS[:1],
        )
        with self.assertRaises(drclvs.StageError) as caught:
            drclvs.require_control_pair(spec)
        self.assertIn("duplicated", str(caught.exception))

    def test_each_cells_own_controls_apply_to_its_own_netlist(self):
        for key, spec in drclvs.CELLS.items():
            with self.subTest(cell=key):
                text = committed_netlist(spec)
                drclvs.check_controls_apply(spec, text)
                for control in spec.controls:
                    self.assertNotEqual(
                        drclvs.apply_control(spec, control, text), text
                    )

    def test_mos_controls_do_not_silently_pass_on_an_all_passive_cell(self):
        """The gap this issue closes: `M*`-keyed mutations on a resistor cell.

        Both MOS controls key off the netlist's first ``M*`` element line. A
        resistor-only netlist has none, so without this check the two stages
        would have had nothing to mutate.
        """
        passive = committed_netlist(drclvs.DIVIDER_SPEC)
        mis_registered = dataclasses.replace(
            drclvs.DIVIDER_SPEC, controls=drclvs.MOS_CONTROLS
        )
        with self.assertRaises(drclvs.ControlNotApplicable) as caught:
            drclvs.check_controls_apply(mis_registered, passive)
        message = str(caught.exception)
        self.assertIn("divider", message)
        self.assertIn("does not apply", message)
        self.assertIn("M*", message)

    def test_passive_controls_do_not_silently_pass_on_a_mos_cell(self):
        """And the converse, so the check is not one-directional."""
        mos = committed_netlist(drclvs.TESTCELL_SPEC)
        mis_registered = dataclasses.replace(
            drclvs.TESTCELL_SPEC, controls=drclvs.PASSIVE_CONTROLS
        )
        with self.assertRaises(drclvs.ControlNotApplicable) as caught:
            drclvs.check_controls_apply(mis_registered, mos)
        self.assertIn("R*", str(caught.exception))

    def test_a_control_that_mutates_nothing_is_a_hard_error(self):
        """A no-op 'corruption' compares MATCH and would prove nothing."""
        inert = (
            drclvs.Control(
                tag="topology",
                mutate=lambda text: text,
                what="nothing at all",
                implication="the control never fired",
            ),
            drclvs.MOS_CONTROLS[1],
        )
        spec = dataclasses.replace(drclvs.TESTCELL_SPEC, controls=inert)
        with self.assertRaises(drclvs.ControlNotApplicable) as caught:
            drclvs.check_controls_apply(spec, committed_netlist(spec))
        self.assertIn("identical to the original", str(caught.exception))

    def test_control_not_applicable_is_a_stage_error(self):
        """So `main()` turns it into a nonzero exit, not an unhandled crash."""
        self.assertTrue(issubclass(drclvs.ControlNotApplicable, drclvs.StageError))


class PassiveControlTests(unittest.TestCase):
    """What the all-passive mutation pair actually does to a netlist."""

    def setUp(self):
        self.text = committed_netlist(drclvs.DIVIDER_SPEC)

    def test_topology_control_shorts_two_adjacent_taps(self):
        mutated = drclvs.control_short_adjacent_taps(self.text)
        first = next(
            line for line in mutated.splitlines() if line.startswith("Rb1 ")
        )
        tokens = first.split()
        self.assertEqual(tokens[1], tokens[2], "the unit must be shorted out")
        # One internal net has disappeared -- a change no relabelling undoes.
        def nets(text):
            return {
                token
                for line in text.splitlines()
                if line[:1] == "R"
                for token in line.split()[1:4]
            }
        self.assertEqual(len(nets(self.text)) - len(nets(mutated)), 1)

    def test_topology_control_leaves_the_pin_list_alone(self):
        """Renaming a *port* would be a weaker, different corruption."""
        mutated = drclvs.control_short_adjacent_taps(self.text)
        for line in self.text.splitlines():
            if line.startswith(".subckt") or line.startswith("*.PININFO"):
                self.assertIn(line, mutated)

    def test_parameter_control_doubles_one_unit_width_and_nothing_else(self):
        mutated = drclvs.control_unit_width(self.text)
        widths = re.findall(r"\bW=(\S+)", mutated)
        self.assertEqual(widths.count("4u"), 1)
        self.assertEqual(widths.count("2u"), len(widths) - 1)
        # Topologically untouched: that is what isolates the parameter compare.
        def topology(text):
            return [
                line.split()[:4] for line in text.splitlines() if line[:1] == "R"
            ]
        self.assertEqual(topology(mutated), topology(self.text))

    def test_parameter_control_does_not_reach_for_the_resistance_value(self):
        """`R` is disabled in the deck's BResistor, so scaling it never fires."""
        mutated = drclvs.control_unit_width(self.text)
        self.assertNotIn("R=", mutated)


class NetlistDirGuardTests(unittest.TestCase):
    """A CellSpec must not be able to clobber a simulation netlist.

    Stage 2 writes `netlist_dir/<cell>.spice` unconditionally when --check is
    absent, so a spec pointing netlist_dir at design/netlist/ would silently
    overwrite the simulation netlist design/netlist.py generates and every
    sim/ testbench sources -- a corruption nothing re-checks until a sim run
    breaks (issue #313). The guard is in CellSpec.__post_init__, so the bad
    spec cannot be constructed at all.
    """

    def test_a_layout_owned_netlist_dir_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = dataclasses.replace(
                drclvs.TESTCELL_SPEC, netlist_dir=Path(tmp) / "netlist"
            )
            self.assertEqual(spec.netlist_dir, Path(tmp) / "netlist")

    def test_the_simulation_netlist_dir_itself_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            dataclasses.replace(
                drclvs.TESTCELL_SPEC, netlist_dir=drclvs.SIM_NETLIST_DIR
            )
        self.assertIn("design/netlist", str(caught.exception).replace(os.sep, "/"))

    def test_a_subdirectory_of_the_simulation_netlist_dir_is_refused(self):
        with self.assertRaises(ValueError):
            dataclasses.replace(
                drclvs.TESTCELL_SPEC,
                netlist_dir=drclvs.SIM_NETLIST_DIR / "lvs",
            )

    def test_an_unnormalized_path_to_it_is_refused_too(self):
        """`..`-walking into design/netlist/ is the same mistake spelled out."""
        with self.assertRaises(ValueError):
            dataclasses.replace(
                drclvs.TESTCELL_SPEC,
                netlist_dir=drclvs.LAYOUT_DIR / ".." / "design" / "netlist",
            )

    def test_every_registered_cell_writes_somewhere_layout_owns(self):
        for spec in drclvs.CELLS.values():
            self.assertTrue(
                drclvs.LAYOUT_DIR.resolve() in spec.netlist_dir.resolve().parents,
                f"{spec.key}: {spec.netlist_dir}",
            )


# One FET and one of each passive, in the LVS form stage 2 produces.
NETLIST = """\
.subckt cell D G S VSS RP RM CT CB
M1 D G S VSS nfet_03v3 L=0.28u W=6u nf=2 m=1
R1 RM RP VSS ppolyf_u_1k l=10u w=1u m=1
C1 CT CB cap_mim_2f0_m4m5_noshield l=20u w=20u m=1
.ends
"""


class ControlParameterTests(unittest.TestCase):
    """control_parameter() must work on any cell's first MOS line.

    Regression test for the gap #313 closes: it used to substitute the literal
    token `W=2u` -> `W=4u` and raise StageError otherwise, so it worked on the
    one-transistor bring-up cell and died on every other cell.
    """

    def test_doubles_an_integer_width(self):
        out = drclvs.control_parameter(NETLIST)
        self.assertIn("M1 D G S VSS nfet_03v3 L=0.28u W=12u nf=2 m=1", out)

    def test_still_doubles_the_original_testcell_width(self):
        out = drclvs.control_parameter(
            "M1 D G S VSS nfet_03v3 L=0.28u W=2u nf=1 m=1\n"
        )
        self.assertIn("W=4u", out)

    def test_doubles_a_fractional_width_without_float_noise(self):
        out = drclvs.control_parameter(
            "M1 D G S VSS nfet_03v3 L=0.28u W=0.22u nf=1 m=1\n"
        )
        self.assertIn("W=0.44u", out)

    def test_carries_the_unit_suffix_through(self):
        out = drclvs.control_parameter(
            "MB1 D G S VSS nfet_03v3 L=6u W=360U nf=6 m=1\n"
        )
        self.assertIn("W=720U", out)

    def test_leaves_every_other_parameter_alone(self):
        out = drclvs.control_parameter(NETLIST)
        self.assertIn("L=0.28u", out)
        self.assertIn("nf=2", out)
        # and the passives are untouched by the MOS control
        self.assertIn("R1 RM RP VSS ppolyf_u_1k l=10u w=1u m=1", out)

    def test_a_mos_line_with_no_width_is_still_a_loud_error(self):
        with self.assertRaises(drclvs.StageError):
            drclvs.control_parameter("M1 D G S VSS nfet_03v3 L=0.28u nf=1 m=1\n")

    def test_a_netlist_with_no_mos_line_is_still_a_loud_error(self):
        with self.assertRaises(drclvs.StageError):
            drclvs.control_parameter("R1 A B VSS ppolyf_u_1k l=10u w=1u m=1\n")


class ControlSetTests(unittest.TestCase):
    """The control set is a property of the netlist, not a fixed list."""

    def test_a_fet_only_netlist_gets_exactly_the_two_mos_controls(self):
        controls = drclvs.build_controls(
            "M1 D G S VSS nfet_03v3 L=0.28u W=2u nf=1 m=1\n"
        )
        self.assertEqual(sorted(controls), ["parameter", "topology"])

    def test_a_passive_bearing_netlist_gets_one_control_per_element_class(self):
        controls = drclvs.build_controls(NETLIST)
        self.assertEqual(
            sorted(controls),
            ["parameter", "passive-c", "passive-r", "topology"],
        )

    def test_the_resistor_control_doubles_only_the_resistor_length(self):
        mutate = drclvs.build_controls(NETLIST)["passive-r"].mutate
        out = mutate(NETLIST)
        self.assertIn("R1 RM RP VSS ppolyf_u_1k l=20u w=1u m=1", out)
        # the capacitor and the FET are untouched
        self.assertIn("C1 CT CB cap_mim_2f0_m4m5_noshield l=20u w=20u m=1", out)
        self.assertIn("M1 D G S VSS nfet_03v3 L=0.28u W=6u nf=2 m=1", out)

    def test_the_capacitor_control_doubles_only_the_capacitor_length(self):
        mutate = drclvs.build_controls(NETLIST)["passive-c"].mutate
        out = mutate(NETLIST)
        self.assertIn("C1 CT CB cap_mim_2f0_m4m5_noshield l=40u w=20u m=1", out)
        self.assertIn("R1 RM RP VSS ppolyf_u_1k l=10u w=1u m=1", out)

    def test_the_topology_control_still_shorts_gate_to_drain(self):
        out = drclvs.control_topology(NETLIST)
        self.assertIn("M1 D D S VSS nfet_03v3", out)

    def test_the_all_passive_divider_keeps_its_own_pair_plus_the_length_control(self):
        """The cell's registered pair is the base; the netlist adds to it.

        The divider registers PASSIVE_CONTROLS (the MOS pair cannot apply to
        it), and because its netlist carries `R` lines with a length, the
        resistor-length control is added on top -- three controls, all of
        which check_controls_apply() proves bite before any LVS runs.
        """
        spec = drclvs.DIVIDER_SPEC
        text = committed_netlist(spec)
        controls = drclvs.check_controls_apply(spec, text)
        self.assertEqual(sorted(controls), ["parameter", "passive-r", "topology"])
        self.assertIs(controls["topology"], drclvs.PASSIVE_CONTROLS[0])
        self.assertIs(controls["parameter"], drclvs.PASSIVE_CONTROLS[1])
        for control in controls.values():
            self.assertNotEqual(control.mutate(text), text)

    def test_check_controls_apply_returns_the_set_the_stages_run(self):
        for key, spec in drclvs.CELLS.items():
            with self.subTest(cell=key):
                text = committed_netlist(spec)
                self.assertEqual(
                    sorted(drclvs.check_controls_apply(spec, text)),
                    sorted(drclvs.build_controls(text, spec.controls)),
                )


if __name__ == "__main__":
    unittest.main()
