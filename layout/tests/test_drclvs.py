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
import json
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
        "klt_drc": {
            "status": "clean",
            "violations": 0,
            "dbu_um": 0.001,
            "rule_counts": {},
            "report": None,
            "coverage": {
                "layers_in_stream_without_rules": ["34/10"],
                "rules_skipped": [],
                "deck_scope": ["7.4 Nwell"],
            },
        },
        "pdk_drc": {
            "violations": 0,
            "rule_categories": 1,
            "deck": "gf180mcu.drc",
            "decks_selection": "all,-antenna,-density",
            "engine": "klt drc --engine klayout",
            "asserted_categories": 1,
            "report": None,
            "coverage": {
                "layers_in_stream_without_rules": [],
                "rules_skipped": [],
                "deck_scope": [],
            },
        },
        "lvs": {
            "match": True,
            "warnings": [],
            "engine": "klt lvs (klayout)",
            "report": None,
        },
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


class RunPdkDrcKltTests(unittest.TestCase):
    """Stage 4 must drive the PDK's own deck through klt, with the deck's
    declared rule-category set asserted.

    The driver (`tech/drc/gf180mcu.drc`) SILENTLY IGNORES unknown ``-rd``
    switches -- it exits 0 and writes a valid report regardless -- so a stale
    ``--deck-var`` would change nothing while the code claimed an intent the
    deck never carries out (issue #784 kept the raw route's switch contract;
    these tests hold the klt route to the same one). The category-set
    assertion is what keeps a zero-category (or swapped-category) deck run a
    hard error rather than a clean pass.
    """

    STALE_SWITCHES = (
        # the pre-bump invocation's switch set: none of these exist in the
        # driver's contract, and every one of them would be silently ignored
        "feol", "beol", "conn_drc", "offgrid",
        "split_deep", "table_name", "thr",
    )

    def run_stage4(
        self,
        report: dict | None = None,
        categories: tuple[str, ...] = ("cat.a", "cat.b"),
    ):
        """Run run_pdk_drc() with the klt subprocess stubbed.

        ``--list-rule-categories`` and the deck run are both ``klt drc``
        invocations; the stub answers the listing from ``categories`` and
        writes ``report`` (default: clean, all categories declared, the
        assertion satisfied) to the run's ``-o`` path.
        """
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured.setdefault("cmds", []).append(list(cmd))
            captured["kwargs"] = kwargs
            if "--list-rule-categories" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 0, "\n".join(categories) + "\n", ""
                )
            out = Path(cmd[cmd.index("-o") + 1])
            payload = report if report is not None else {
                "status": "clean",
                "violation_count": 0,
                "coverage": {"rule_categories": list(categories)},
                "coverage_assertion": {"satisfied": True},
            }
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        original = drclvs.subprocess.run
        drclvs.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp)
                spec = drclvs.CELLS["testcell"]
                result = drclvs.run_pdk_drc(
                    fake_pdk(run_dir / "pdk"),
                    spec, run_dir / "in.gds", run_dir, run_dir / "pdk-drc.log",
                    run_dir / "out.json",
                )
        finally:
            drclvs.subprocess.run = original
        return captured, result

    @staticmethod
    def deck_vars_of(cmd: list[str]) -> dict[str, str]:
        switches = {}
        for index, arg in enumerate(cmd):
            if arg == "--deck-var":
                key, _, value = cmd[index + 1].partition("=")
                switches[key] = value
        return switches

    def test_drives_the_pdk_deck_through_klt(self):
        captured, result = self.run_stage4()
        deck_run = captured["cmds"][-1]
        self.assertEqual(deck_run[:2], ["klt", "drc"])
        self.assertIn("--engine", deck_run)
        self.assertEqual(
            deck_run[deck_run.index("--engine") + 1], "klayout"
        )
        deck_file = deck_run[deck_run.index("--deck-file") + 1]
        self.assertTrue(deck_file.endswith("/drc/gf180mcu.drc"), deck_file)
        self.assertEqual(result["deck"], "gf180mcu.drc")

    def test_the_run_selects_the_top_cell_and_writes_the_report(self):
        captured, result = self.run_stage4()
        deck_run = captured["cmds"][-1]
        spec = drclvs.CELLS["testcell"]
        self.assertEqual(
            deck_run[deck_run.index("--top") + 1], spec.top_cell
        )
        self.assertIn("--expect-rule-categories-file", deck_run)
        self.assertEqual(result["status"], "clean")
        self.assertEqual(result["violations"], 0)

    def test_no_stale_switch_from_the_old_deck_contract_is_emitted(self):
        captured, _ = self.run_stage4()
        for cmd in captured["cmds"]:
            deck_vars = self.deck_vars_of(cmd)
            for stale in self.STALE_SWITCHES:
                self.assertNotIn(stale, deck_vars, f"stale deck var {stale!r}")

    def test_every_emitted_deck_var_is_in_the_driver_contract(self):
        captured, _ = self.run_stage4()
        known = {
            "input", "report", "topcell", "run_mode", "verbose", "workers",
            "threads", "variant", "metal_level", "metal_top", "mim_option",
            "decks", "help",
        }
        for cmd in captured["cmds"]:
            unknown = set(self.deck_vars_of(cmd)) - known
            self.assertEqual(unknown, set(), "deck vars the driver would ignore")

    def test_decks_selection_excludes_exactly_antenna_and_density(self):
        captured, result = self.run_stage4()
        deck_run = captured["cmds"][-1]
        self.assertEqual(result["decks_selection"], "all,-antenna,-density")
        self.assertEqual(
            self.deck_vars_of(deck_run)["decks"], "all,-antenna,-density"
        )

    def test_run_mode_is_deep_and_threads_replaces_thr(self):
        captured, _ = self.run_stage4()
        deck_vars = self.deck_vars_of(captured["cmds"][-1])
        self.assertEqual(deck_vars["run_mode"], "deep")
        self.assertIn("threads", deck_vars)

    def test_variant_switches_carry_the_metal_stack(self):
        captured, _ = self.run_stage4()
        deck_vars = self.deck_vars_of(captured["cmds"][-1])
        self.assertEqual(deck_vars["metal_top"], "11K")
        self.assertEqual(deck_vars["mim_option"], "B")
        self.assertEqual(deck_vars["metal_level"], "5LM")

    def test_a_zero_category_listing_is_a_hard_error(self):
        with self.assertRaises(drclvs.StageError) as ctx:
            self.run_stage4(categories=())
        self.assertIn("ZERO rule categories", str(ctx.exception))

    def test_an_unsatisfied_category_assertion_is_a_hard_error(self):
        report = {
            "status": "coverage_unknown",
            "violation_count": 0,
            "coverage": {"rule_categories": ["cat.a"]},
            "coverage_assertion": {"satisfied": False},
        }
        with self.assertRaises(drclvs.StageError) as ctx:
            self.run_stage4(report=report)
        self.assertIn("assertion", str(ctx.exception))

    def test_the_coverage_triple_is_carried_for_the_record(self):
        _, result = self.run_stage4()
        self.assertEqual(
            sorted(result["coverage"]),
            [
                "deck_scope",
                "layers_in_stream_without_rules",
                "rules_skipped",
            ],
        )


class RawDeckParityTests(unittest.TestCase):
    """check_raw_parity(): a verdict or category-set difference is a hard
    error, never a silent divergence between the retired raw route and the
    klt route that replaced it (issue #784's migration gate)."""

    def test_agreement_passes_and_describes_it(self):
        native = {
            "violations": 0,
            "category_names": {"cat.a", "cat.b"},
        }
        raw = {"violations": 0, "categories": {"cat.a", "cat.b"}}
        line = drclvs.check_raw_parity(
            native, raw, drclvs.CELLS["testcell"], Path("/tmp")
        )
        self.assertIn("verdict equal", line)
        self.assertIn("2 rule categories", line)

    def test_a_verdict_difference_is_a_hard_error(self):
        native = {"violations": 0, "category_names": {"cat.a"}}
        raw = {"violations": 2, "categories": {"cat.a"}}
        with self.assertRaises(drclvs.StageError) as ctx:
            drclvs.check_raw_parity(
                native, raw, drclvs.CELLS["testcell"], Path("/tmp")
            )
        self.assertIn("parity failed", str(ctx.exception))

    def test_a_category_set_difference_is_a_hard_error(self):
        native = {"violations": 0, "category_names": {"cat.a", "cat.x"}}
        raw = {"violations": 0, "categories": {"cat.a", "cat.b"}}
        with self.assertRaises(drclvs.StageError) as ctx:
            drclvs.check_raw_parity(
                native, raw, drclvs.CELLS["testcell"], Path("/tmp")
            )
        self.assertIn("cat.x", str(ctx.exception))


def lvs_switches_of(cmd: list[str]) -> dict[str, str]:
    """Pull the ``-rd key=value`` switches out of an emitted klayout command."""
    switches = {}
    it = iter(cmd)
    for arg in it:
        if arg == "-rd":
            key, _, value = next(it).partition("=")
            switches[key] = value
    return switches


class RunLvsSwitchesTests(unittest.TestCase):
    """Stage 5 must pass the switches the pinned runset actually reads.

    The pinned ``gf180mcu.lvs`` reads every compare-affecting option as its
    own ``-rd`` global, each defaulting to FALSE through ``bool_check?``
    (``tech/lvs/gf180mcu.lvs:109``): nothing is derived any more. A driver
    that relies on the pre-bump derivation therefore runs a compare whose
    SIMPLIFY and IMPLICIT_CONNECT are both off -- parallel devices never
    merge, same-named nets never join -- and gets a well-formed WRONG
    verdict, not an error (issue #642). These tests hold ``run_lvs()`` to
    the switch set the pinned deck needs, so the next PDK bump that changes
    the defaults cannot silently reintroduce the gap.
    """

    def run_stage5(self, spec_key: str):
        """Run run_lvs() with run_logged stubbed; return the emitted switches."""
        captured: dict = {}

        def fake_run_logged(cmd, log, what, env=None):
            captured["cmd"] = cmd
            captured["env"] = env
            for arg in cmd:
                if arg.startswith("report="):
                    Path(arg.split("=", 1)[1]).write_text("<lvsdb/>")
            return "INFO : Congratulations! Netlists match."

        original = drclvs.run_logged
        drclvs.run_logged = fake_run_logged
        try:
            with tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp)
                spec = drclvs.CELLS[spec_key]
                drclvs.run_lvs(
                    fake_pdk(run_dir / "pdk"), spec,
                    run_dir / "in.gds", run_dir / "ref.spice", run_dir,
                    run_dir / "lvs.log", "lvs",
                )
        finally:
            drclvs.run_logged = original
        return lvs_switches_of(captured["cmd"])

    def test_simplify_is_passed_and_tracks_simplify_extracted(self):
        """``$simplify`` alone gates SIMPLIFY now (``gf180mcu.lvs:149``, both
        sides at :427-428): if it stops being passed, the deck silently runs
        with it FALSE and parallel devices stop merging."""
        for key, spec in drclvs.CELLS.items():
            with self.subTest(cell=key):
                switches = self.run_stage5(key)
                self.assertEqual(
                    switches.get("simplify"),
                    "true" if spec.simplify_extracted else "false",
                )
        self.assertEqual(self.run_stage5("testcell")["simplify"], "true")
        self.assertEqual(self.run_stage5("divider")["simplify"], "false")

    def test_implicit_connect_is_always_passed_true(self):
        """``$implicit_connect`` alone gates ``connect_implicit('*')``
        (``gf180mcu.lvs:179`` / :415): drclvs_passives draws no strapping
        metal and relies on that join, so it must never be left unset."""
        for key in drclvs.CELLS:
            with self.subTest(cell=key):
                self.assertEqual(self.run_stage5(key).get("implicit_connect"), "true")

    def test_top_lvl_pins_stays_paired_with_simplify_extracted(self):
        """An independent switch in the pinned runset (``gf180mcu.lvs:159``),
        kept inverted against ``simplify`` exactly as probe-verified: the
        flow vehicles run ``top_lvl_pins=false``, the divider ``true``."""
        self.assertEqual(self.run_stage5("testcell")["top_lvl_pins"], "false")
        self.assertEqual(self.run_stage5("divider")["top_lvl_pins"], "true")

    def test_stage5_drives_the_pinned_runset(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            cmd = None

            def fake_run_logged(cap_cmd, log, what, env=None):
                nonlocal cmd
                cmd = cap_cmd
                for arg in cap_cmd:
                    if arg.startswith("report="):
                        Path(arg.split("=", 1)[1]).write_text("<lvsdb/>")
                return "INFO : Congratulations! Netlists match."

            original = drclvs.run_logged
            drclvs.run_logged = fake_run_logged
            try:
                drclvs.run_lvs(
                    fake_pdk(run_dir / "pdk"), drclvs.TESTCELL_SPEC,
                    run_dir / "in.gds", run_dir / "ref.spice", run_dir,
                    run_dir / "lvs.log", "lvs",
                )
            finally:
                drclvs.run_logged = original
            self.assertEqual(cmd[:3], ["klayout", "-b", "-r"])
            self.assertTrue(cmd[3].endswith("/lvs/gf180mcu.lvs"), cmd[3])


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


# One FET and one of each passive, in the LVS form stage 2 produces -- the
# MIM cap carries the device class the deck's extraction registers
# (rule_decks/mimcap_extraction.lvs), which lvs_form.py maps the exported
# symbol-name token to.
NETLIST = """\
.subckt cell D G S VSS RP RM CT CB
M1 D G S VSS nfet_03v3 L=0.28u W=6u nf=2 m=1
R1 RM RP VSS ppolyf_u_1k l=10u w=1u m=1
C1 CT CB cap_mim_2f0fF l=20u w=20u m=1
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
        self.assertIn("C1 CT CB cap_mim_2f0fF l=20u w=20u m=1", out)
        self.assertIn("M1 D G S VSS nfet_03v3 L=0.28u W=6u nf=2 m=1", out)

    def test_the_capacitor_control_doubles_only_the_capacitor_length(self):
        mutate = drclvs.build_controls(NETLIST)["passive-c"].mutate
        out = mutate(NETLIST)
        self.assertIn("C1 CT CB cap_mim_2f0fF l=40u w=20u m=1", out)
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


class KltLvsRequestTests(unittest.TestCase):
    """build_klt_lvs_request(): the committed-report request shape (issue
    #784), mirroring the sibling precedent's keys and carrying the raw
    route's per-cell knobs onto their klt counterparts."""

    def request_for(self, spec_key: str) -> dict:
        spec = drclvs.CELLS[spec_key]
        with tempfile.TemporaryDirectory() as tmp:
            return drclvs.build_klt_lvs_request(
                spec, fake_pdk(Path(tmp) / "pdk"), "layout.gds", "ref.spice"
            )

    def test_layout_side_selects_the_curated_deck_and_flavours(self):
        request = self.request_for("divider")
        self.assertEqual(request["layout"]["deck"], "gf180mcu")
        self.assertEqual(request["layout"]["top"], "FB_DIVIDER")
        options = request["layout"]["deck_options"]
        self.assertEqual(options["poly_res"], "3k")
        # the curated deck's own MIM class spelling (klayout-tools#7031),
        # transcribed in one place: lvs_form.MIMCAP_CURATED_OPTION
        self.assertEqual(options["mim_cap"], "cap_mim_2f0_m4m5_noshield")
        self.assertEqual(options["metal_top"], "11K")

    def test_reference_side_uses_the_subckt_call_conversion(self):
        request = self.request_for("pass_array")
        self.assertEqual(request["reference"]["form"], "subckt-call")
        self.assertEqual(request["reference"]["deck"], "gf180mcu")
        self.assertEqual(request["reference"]["top"], "pass_array")

    def test_geometry_parameters_are_scoped_per_cell(self):
        request = self.request_for("divider")
        self.assertEqual(
            request["options"]["compare_parameters"],
            {"ppolyf_u_3k": ["L", "W"]},
        )
        self.assertFalse(request["options"]["combine_devices"])

    def test_parallel_folding_is_per_cell(self):
        request = self.request_for("pass_array")
        self.assertTrue(request["options"]["combine_devices"])
        self.assertNotIn("compare_parameters", request["options"])

    def test_a_cell_without_passives_scopes_nothing(self):
        request = self.request_for("testcell")
        self.assertEqual(request["options"], {"combine_devices": False})


class LvsRouteRegistryTests(unittest.TestCase):
    """The per-cell LVS routing (issue #784): klt wherever the curated path
    can express the reference, raw PDK runset only for a named gap."""

    def test_the_three_committed_cells_have_a_committed_gds(self):
        for key in ("pass_array", "divider", "passives"):
            spec = drclvs.CELLS[key]
            self.assertIsNotNone(spec.gds_path, key)
            self.assertEqual(
                spec.gds_path, spec.gds_path.parent / f"{spec.cell}.gds", key
            )

    def test_the_scratch_flow_vehicles_commit_no_gds(self):
        self.assertIsNone(drclvs.CELLS["testcell"].gds_path)

    def test_the_default_route_is_klt(self):
        for key in ("testcell", "pass_array", "divider"):
            self.assertEqual(drclvs.CELLS[key].lvs_route, "klt", key)

    def test_passives_stays_raw_for_the_implicit_connect_gap(self):
        spec = drclvs.CELLS["passives"]
        self.assertEqual(spec.lvs_route, "pdk-deck")

    def test_an_unknown_route_is_refused(self):
        with tempfile.TemporaryDirectory():
            with self.assertRaises(ValueError):
                dataclasses.replace(
                    drclvs.CELLS["testcell"], lvs_route="carrier-pigeon"
                )


class GdsEqualModuloTimestampsTests(unittest.TestCase):
    """gds_equal_modulo_timestamps(): the committed-GDS freshness check."""

    @staticmethod
    def gds_with_timestamps(stamp: bytes, geometry: bytes = b"\x00\x06\x0d\x02\x00\x01") -> bytes:
        # HEADER record (rectype 0x00, no payload) then a BGNSTR timestamp
        # record (rectype 0x05, 12-byte payload) then a geometry-ish record.
        header = b"\x00\x06\x00\x02\x00\x01"
        bgnstr = b"\x00\x10\x05\x02" + stamp
        return header + bgnstr + geometry

    def test_same_geometry_different_stamps_is_equal(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.gds"
            b = Path(tmp) / "b.gds"
            a.write_bytes(
                self.gds_with_timestamps(b"\x07\xe6\x00\x01" * 3)
            )
            b.write_bytes(
                self.gds_with_timestamps(b"\x07\xe6\x00\x02" * 3)
            )
            self.assertTrue(drclvs.gds_equal_modulo_timestamps(a, b))

    def test_different_geometry_is_not_equal(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.gds"
            b = Path(tmp) / "b.gds"
            a.write_bytes(
                self.gds_with_timestamps(b"\x07\xe6\x00\x01" * 3, b"\x00\x06\x0d\x02\x00\x01")
            )
            b.write_bytes(
                self.gds_with_timestamps(b"\x07\xe6\x00\x01" * 3, b"\x00\x06\x0d\x02\x00\x02")
            )
            self.assertFalse(drclvs.gds_equal_modulo_timestamps(a, b))

    def test_a_truncated_stream_is_an_error_not_a_false_equal(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.gds"
            b = Path(tmp) / "b.gds"
            a.write_bytes(self.gds_with_timestamps(b"\x00" * 12))
            b.write_bytes(b"\x00\x40")  # declares 64 bytes, has 2
            with self.assertRaises(ValueError):
                drclvs.gds_equal_modulo_timestamps(a, b)


if __name__ == "__main__":
    unittest.main()
