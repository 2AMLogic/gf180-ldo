#!/usr/bin/env python3
"""Unit tests for layout/drclvs.py's host-independent parts.

    python3 -m unittest discover -s layout/tests -v

No PDK, klayout, or xschem required: these tests exercise ``write_record()``'s
append-only guard, the ``--cell`` registry, and ``deck_env()``'s pmap(1)
stand-in -- not the DRC/LVS stages themselves.
"""

from __future__ import annotations

import dataclasses
import os
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
        mutate = drclvs.build_controls(NETLIST)["passive-r"][0]
        out = mutate(NETLIST)
        self.assertIn("R1 RM RP VSS ppolyf_u_1k l=20u w=1u m=1", out)
        # the capacitor and the FET are untouched
        self.assertIn("C1 CT CB cap_mim_2f0_m4m5_noshield l=20u w=20u m=1", out)
        self.assertIn("M1 D G S VSS nfet_03v3 L=0.28u W=6u nf=2 m=1", out)

    def test_the_capacitor_control_doubles_only_the_capacitor_length(self):
        mutate = drclvs.build_controls(NETLIST)["passive-c"][0]
        out = mutate(NETLIST)
        self.assertIn("C1 CT CB cap_mim_2f0_m4m5_noshield l=40u w=20u m=1", out)
        self.assertIn("R1 RM RP VSS ppolyf_u_1k l=10u w=1u m=1", out)

    def test_the_topology_control_still_shorts_gate_to_drain(self):
        out = drclvs.control_topology(NETLIST)
        self.assertIn("M1 D D S VSS nfet_03v3", out)


if __name__ == "__main__":
    unittest.main()
