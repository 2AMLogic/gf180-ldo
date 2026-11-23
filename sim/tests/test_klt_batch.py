#!/usr/bin/env python3
"""Unit tests for ``sim/harness/klt_batch.py``'s request builder. No PDK, no klt."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import corners  # noqa: E402
from harness import klt_ab  # noqa: E402
from harness import klt_batch as kb  # noqa: E402


class CornerId(unittest.TestCase):
    """One corner-id spelling on both sides of the report join (issue #780).

    The sweep keys its grid points by :attr:`harness.corners.PvtPoint.corner_id`
    and looks the klt report's rows up by :func:`klt_batch.corner_id`; when the
    two formatters disagreed (six-significant-digit grid vs full-precision
    report) a measurement the report contained was reported as a missing row.
    """

    def test_report_rows_and_grid_points_agree_across_the_default_axes(self):
        grid = corners.build_grid(
            corners.resolve_corners(["mos"]),
            corners.DEFAULT_TEMPERATURES_C,
            corners.supply_points(),
        )
        for p in grid:
            with self.subTest(corner_id=p.corner_id):
                row = {"process": p.corner.name, "temperature_c": p.temp_c,
                       "supply_v": {"vin": p.vdd}}
                self.assertEqual(kb.corner_id(row, "vin"), p.corner_id)

    def test_report_rows_keep_fractional_temperature_and_normalize_signed_zero(self):
        self.assertEqual(
            kb.corner_id({"process": "tt", "temperature_c": 27.123456,
                          "supply_v": {"vin": 3.3}}, "vin"),
            "tt_27.123456c_3.30v",
        )
        self.assertEqual(
            kb.corner_id({"process": "tt", "temperature_c": -0.0,
                          "supply_v": {"vin": 3.3}}, "vin"),
            "tt_0c_3.30v",
        )

    def test_the_supply_is_still_klts_own_selection(self):
        """The shared formatter changed only the id's spelling; which supply a
        report row names stays klt's: the fixed override, else the
        ``corners.params`` row, else the ``corners.supply_v`` axis."""
        via_params = {"process": "tt", "temperature_c": 27.0,
                      "params": {"vsup": 2.97}, "supply_v": {"vin": 3.63}}
        via_axis = {"process": "tt", "temperature_c": 27.0,
                    "supply_v": {"vin": 3.63}}
        self.assertEqual(kb.corner_id(via_params, "vsup"), "tt_27c_2.97v")
        self.assertEqual(kb.corner_id(via_params, "vin"), "tt_27c_3.63v")
        self.assertEqual(kb.corner_id(via_axis, "vin"), "tt_27c_3.63v")
        self.assertEqual(kb.corner_id(via_axis, "vin", 2.97), "tt_27c_2.97v")


class RequestOptions(unittest.TestCase):
    def test_model_inputs_are_staged_when_requested(self):
        """The fleet worker's /opt/pdk can lag PINNED_OPEN_PDKS_REVISION (#430):
        a job that claims the pin sets stage_model_inputs so it carries this
        host's model files, not the worker's."""
        job = kb.Job(name="t", body="", dut_netlist=Path("dut.spice"),
                     analysis={"kind": "op", "args": ""}, measurements=[],
                     stage_model_inputs=True)
        opts = job.request()["options"]
        self.assertIs(opts["stage_model_inputs"], True)
        self.assertIs(opts["keep_artifacts"], True)

    def _job(self, **kw):
        return kb.Job(name="t", body="", dut_netlist=Path("dut.spice"),
                      analysis={"kind": "op", "args": ""}, measurements=[], **kw)

    def test_monte_carlo_form_is_emitted_only_when_asked(self):
        """mc-output-accuracy takes its redraws from request.monte_carlo, not a .control loop (#469)."""
        mc = {"n": 40, "seed": 469, "vary": "mismatch"}
        self.assertEqual(self._job(monte_carlo=mc).request()["monte_carlo"], mc)
        self.assertNotIn("monte_carlo", self._job().request())

    def test_every_request_carries_the_default_capacity_wait(self):
        """Fleet capacity is klt's to wait out (issue #610): the dispatch-host
        rule -- a 600 s ``batch.capacity_wait_s`` on every batch submit -- is
        applied once here, so a driver that sets no ``batch`` (89 of the 98
        committed requests when #610 was filed) still waits out a refusal."""
        for batch in (None, {}):
            with self.subTest(batch=batch):
                self.assertEqual(self._job(batch=batch).request()["batch"],
                                 {"capacity_wait_s": kb.DEFAULT_CAPACITY_WAIT_S})

    def test_driver_keys_merge_over_the_default_capacity_wait(self):
        """A shard-only mapping inherits the default; an explicit
        ``capacity_wait_s`` -- including 0, a deliberate no-wait -- wins, and
        the caller's mapping is left intact. A later default job still emits
        600: the default is rebuilt per request, never a shared mapping a
        driver could mutate."""
        shard_only = {"max_units_per_job": 2, "max_concurrent_jobs": 2}
        self.assertEqual(
            self._job(batch=shard_only).request()["batch"],
            {"max_units_per_job": 2, "max_concurrent_jobs": 2,
             "capacity_wait_s": kb.DEFAULT_CAPACITY_WAIT_S})
        self.assertEqual(shard_only, {"max_units_per_job": 2, "max_concurrent_jobs": 2})
        self.assertEqual(self._job(batch={"capacity_wait_s": 0}).request()["batch"],
                         {"capacity_wait_s": 0})
        batch = {"max_units_per_job": 2, "max_concurrent_jobs": 2, "capacity_wait_s": 7200}
        self.assertEqual(self._job(batch=batch, timeout_s=1700).request()["batch"], batch)
        self.assertEqual(self._job().request()["batch"],
                         {"capacity_wait_s": kb.DEFAULT_CAPACITY_WAIT_S})


def _report():
    """A fresh one-corner klt report (a new dict per call)."""
    return {"corners": [{
        "process": "tt", "temperature_c": 27, "supply_v": {"vin": 3.3},
        "measurements": [{"name": "vout_settled", "value": 1.8}],
        "status": "ok", "diagnostics": [],
    }]}


class TestKltBatchRunResume(unittest.TestCase):
    """``kb.run``'s resume flag and the values/collect split (issue #465).

    A grid that outlives a dispatch session must continue, not repeat: the
    resume flag is what makes klt re-attach to a sharded request's retained
    shard map, and ``values`` is what lets a resumed driver read a saved
    report whose original per-corner logs are gone.
    """

    def _run_kb(self, tmp: Path, *, resume: bool):
        proc = unittest.mock.Mock(returncode=0,
                                  stdout=json.dumps(_report()), stderr="")
        # Resume is identity-checked over the staged request/deck/DUT trio
        # (issue #796), so the request must come from a real kb.stage().
        dut = tmp / "dut.spice"
        dut.write_text("* dut\n")
        job = kb.Job(name="t", body="* body\n", dut_netlist=dut,
                            analysis={"kind": "ac", "args": "dec 10 1k 10k"},
                            measurements=[])
        req = kb.stage(job, tmp / "stage")
        with unittest.mock.patch("subprocess.run", return_value=proc) as run:
            kb.run(req, tmp / "out", backend="batch", resume=resume)
        return run.call_args.args[0]

    def test_resume_appends_klts_resume_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            argv = self._run_kb(Path(tmpdir), resume=True)
        self.assertIn("--resume", argv)

    def test_the_default_does_not_resume(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            argv = self._run_kb(Path(tmpdir), resume=False)
        self.assertNotIn("--resume", argv)

    def test_values_matches_collect(self):
        job = kb.Job(name="t", body="* b", dut_netlist=Path("d.spice"),
                            analysis={"kind": "ac", "args": "dec 10 1k 10k"},
                            measurements=[])
        report = _report()
        with tempfile.TemporaryDirectory() as tmpdir:
            # No artifact logs exist under the report's paths, so collect
            # copies nothing and the two must still agree on the values.
            collected = kb.collect(report, job, Path(tmpdir))
        self.assertEqual(collected, kb.values(report, job))
        self.assertEqual({"tt_27c_3.30v": {"vout_settled": 1.8, "_status": "ok",
                                           "_diagnostics": ""}}, collected)


class TestKltRunShardMapIdentity(unittest.TestCase):
    """``kb.run(resume=True)`` identity-checks the retained shard map (#796).

    klt's ``--resume`` re-attaches to the shard map retained under the
    outdir, so a re-submission after a circuit edit would otherwise collect
    the previous circuit's finished shards into the new circuit's report.
    The outdir records the staged identity it was submitted with; a
    mismatch drops the map and starts clean, while an interrupted run of
    the same circuit keeps it (issue #465).
    """

    def _run(self, tmp: Path, dut_text: str, body: str):
        tmp.joinpath("dut.spice").write_text(dut_text)
        job = kb.Job(name="t", body=body, dut_netlist=tmp / "dut.spice",
                            analysis={"kind": "ac", "args": "dec 10 1k 10k"},
                            measurements=[])
        req = kb.stage(job, tmp / "stage")
        proc = unittest.mock.Mock(returncode=0, stdout=json.dumps({"corners": []}),
                                  stderr="")
        with unittest.mock.patch("subprocess.run", return_value=proc), \
                contextlib.redirect_stdout(io.StringIO()):
            kb.run(req, tmp / "out", backend="batch", resume=True)

    def test_a_same_circuit_resume_keeps_the_retained_shard_map(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self._run(tmp, "* dut\n", "* body\n")
            (tmp / "out" / "shard-map.json").write_text("{}")
            self._run(tmp, "* dut\n", "* body\n")
            self.assertTrue((tmp / "out" / "shard-map.json").is_file())

    def test_a_dut_change_drops_the_retained_shard_map(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self._run(tmp, "* dut r100\n", "* body\n")
            (tmp / "out" / "shard-map.json").write_text("{}")
            self._run(tmp, "* dut r200\n", "* body\n")
            self.assertFalse((tmp / "out" / "shard-map.json").exists())

    def test_a_deck_change_drops_the_retained_shard_map(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self._run(tmp, "* dut\n", "* body a\n")
            (tmp / "out" / "shard-map.json").write_text("{}")
            self._run(tmp, "* dut\n", "* body b\n")
            self.assertFalse((tmp / "out" / "shard-map.json").exists())

    def test_a_map_without_identity_evidence_is_claimed_clean(self):
        """An outdir written before #796 recorded identities has no marker;
        a resume must not trust its shards on faith (a miss, not a match)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self._run(tmp, "* dut\n", "* body\n")
            (tmp / "out" / "run-identity.json").unlink()
            (tmp / "out" / "shard-map.json").write_text("{}")
            self._run(tmp, "* dut\n", "* body\n")
            self.assertFalse((tmp / "out" / "shard-map.json").exists())


class TestRunAbResume(unittest.TestCase):
    """``run_ab``'s run_root: persistent staging, skip-if-done, --resume.

    With a run_root the staged request and the run dir survive the session,
    so re-invoking the same driver command only submits what is still
    missing; a tag that already reported -- with a matching staged identity
    (request, deck body and DUT bytes, issue #796) -- is not re-submitted
    at all (issue #465).
    """

    @staticmethod
    def _factory(dut: Path, body: str = "* body\n", temps: tuple = (27.0,)):
        def factory(tag, dut_path):
            return kb.Job(name=tag, body=body, dut_netlist=dut_path,
                                 analysis={"kind": "ac", "args": "dec 10 1k 10k"},
                                 measurements=[], process=("tt",), temps=temps,
                                 supplies=(3.3,))
        return factory

    def _run_once(self, tmp: Path, factory):
        """One run_ab invocation with klt itself faked (a fresh report)."""
        proc = unittest.mock.Mock(returncode=0,
                                  stdout=json.dumps(_report()), stderr="")
        with unittest.mock.patch("subprocess.run", return_value=proc) as run:
            klt_ab.run_ab(factory, tmp / "dut.spice", None, tmp / "dest", tmp,
                          backend="batch", run_root=tmp / "run")
        return run

    def test_a_completed_tag_is_not_resubmitted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            tmp.joinpath("dut.spice").write_text("* dut\n")
            self._run_once(tmp, self._factory(tmp / "dut.spice"))
            with unittest.mock.patch.object(kb, "run") as run:
                res = klt_ab.run_ab(self._factory(tmp / "dut.spice"),
                                    tmp / "dut.spice", None, tmp / "dest", tmp,
                                    backend="batch", run_root=tmp / "run")
            run.assert_not_called()
        self.assertEqual({"tt_27c_3.30v": {"vout_settled": 1.8, "_status": "ok",
                                           "_diagnostics": ""}}, res["new"])

    def test_a_saved_report_from_a_changed_dut_is_rerun_not_trusted(self):
        """The request names only the deck file, so a DUT edit leaves it
        byte-identical -- the resume guard must still refuse the old report
        (issue #796)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            tmp.joinpath("dut.spice").write_text("* dut r100\n")
            self._run_once(tmp, self._factory(tmp / "dut.spice"))
            tmp.joinpath("dut.spice").write_text("* dut r200\n")
            run = self._run_once(tmp, self._factory(tmp / "dut.spice"))
            run.assert_called()
            self.assertIn("--resume", run.call_args.args[0])

    def test_a_saved_report_from_a_changed_deck_is_rerun_not_trusted(self):
        """Same grid flags and DUT, a different circuit body: the request
        alone cannot see it, the staged identity can (issue #796)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            tmp.joinpath("dut.spice").write_text("* dut\n")
            self._run_once(tmp, self._factory(tmp / "dut.spice", body="* body a\n"))
            run = self._run_once(tmp, self._factory(tmp / "dut.spice", body="* body b\n"))
            run.assert_called()
            self.assertIn("--resume", run.call_args.args[0])

    def test_a_saved_report_from_a_different_request_is_rerun_not_trusted(self):
        """A saved report from a different request (other grid flags) must
        never be read as this run's result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            tmp.joinpath("dut.spice").write_text("* dut\n")
            self._run_once(tmp, self._factory(tmp / "dut.spice", temps=(25.0,)))
            run = self._run_once(tmp, self._factory(tmp / "dut.spice"))
            run.assert_called()
            self.assertIn("--resume", run.call_args.args[0])

    def test_a_fresh_batch_run_resumes_and_stages_under_run_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest, run_root = tmp / "dest", tmp / "run"
            dut = tmp / "dut.spice"
            dut.write_text("* dut\n")
            proc = unittest.mock.Mock(returncode=0,
                                      stdout=json.dumps(_report()), stderr="")
            with unittest.mock.patch("subprocess.run", return_value=proc) as run:
                res = klt_ab.run_ab(self._factory(dut), dut, None, dest, tmp,
                                    backend="batch", run_root=run_root)
            argv = run.call_args.args[0]
            self.assertIn("--resume", argv)
            req_arg = argv[2]  # klt sim <request> -o <outdir> ... --resume
            self.assertTrue(str(req_arg).startswith(str(run_root)))
            staged_req = run_root / "new" / "stage" / "request.json"
            self.assertTrue(staged_req.is_file())
            out_arg = Path(argv[argv.index("-o") + 1])
            self.assertTrue(str(out_arg).startswith(str(run_root)))
        self.assertIn("new", res)

    def test_the_default_no_run_root_path_still_runs(self):
        """``run_root=None`` keeps the old session-tempdir behaviour for
        every pre-#465 caller (regression: the dual-typed context handle
        made ``tmp / tag`` a ``str / str`` TypeError before any staging)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "dest"
            dut = tmp / "dut.spice"
            dut.write_text("* dut\n")
            proc = unittest.mock.Mock(returncode=0,
                                      stdout=json.dumps(_report()), stderr="")
            with unittest.mock.patch("subprocess.run", return_value=proc) as run:
                res = klt_ab.run_ab(self._factory(dut), dut, None, dest, tmp,
                                    backend="batch")
            run.assert_called()
            argv = run.call_args.args[0]
            self.assertNotIn("--resume", argv)
            req_arg = Path(argv[2])
            self.assertNotIn(str(dest), str(req_arg.parent))
        self.assertEqual({"tt_27c_3.30v": {"vout_settled": 1.8, "_status": "ok",
                                           "_diagnostics": ""}}, res["new"])

    def test_a_saved_report_with_no_sidecar_request_is_rerun_not_trusted(self):
        """A ``klt-report.json`` without its ``identity.json`` sidecar -- a
        run interrupted between collect and the marker publish, or a dest
        written before #796 published identity markers -- is re-run, never
        read: identity evidence that is missing is a miss (issue #796)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest, run_root = tmp / "dest", tmp / "run"
            dut = tmp / "dut.spice"
            dut.write_text("* dut\n")
            sub = dest / "new"
            sub.mkdir(parents=True)
            (sub / "klt-report.json").write_text(json.dumps(_report()))
            proc = unittest.mock.Mock(returncode=0,
                                      stdout=json.dumps(_report()), stderr="")
            with unittest.mock.patch("subprocess.run", return_value=proc) as run:
                res = klt_ab.run_ab(self._factory(dut), dut, None, dest, tmp,
                                    backend="batch", run_root=run_root)
            run.assert_called()
        self.assertIn("new", res)

class TestKltBatchRunOutdirLockedRetry(unittest.TestCase):
    """``kb.run`` waits out klt's ``outdir_locked`` instead of failing (issue #465).

    A resumed run's outdir can still be held by a killed-but-dying earlier
    owner; the lock frees the moment the process tree is reaped, so the
    correct response is a bounded wait, not losing the grid. Fleet capacity
    is not retried here (issue #610): ``batch.capacity_wait_s`` (defaulted by
    ``Job.request``) makes waiting out ``batch_no_capacity`` and
    ``batch_concurrency_cap`` klt's own job, so a capacity error that still
    reaches the harness is final.
    """

    @staticmethod
    def _error(code="outdir_locked"):
        return {"schema_version": 1,
                "error": {"command": "sim", "code": code,
                          "message": "output directory '...' is owned by "
                                     "another run (pid 999 since 2026-11-18)"}}

    def test_a_locked_outdir_is_retried_then_succeeds(self):
        report = {"corners": []}
        procs = [unittest.mock.Mock(returncode=1,
                                    stdout=json.dumps(self._error()), stderr=""),
                 unittest.mock.Mock(returncode=1,
                                    stdout=json.dumps(self._error()), stderr=""),
                 unittest.mock.Mock(returncode=0, stdout=json.dumps(report),
                                    stderr="")]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            req = tmp / "request.json"
            req.write_text("{}")
            with unittest.mock.patch("subprocess.run", return_value=procs[0]) as run, \
                    unittest.mock.patch.object(kb.time, "sleep") as sleep, \
                    unittest.mock.patch.object(kb.random, "uniform",
                                               return_value=0.0):
                run.side_effect = procs
                out = kb.run(req, tmp / "out", backend="batch",
                                    max_lock_wait_s=600)
        self.assertEqual(3, run.call_count)
        self.assertEqual(2, sleep.call_count)
        self.assertEqual(report, out)

    def test_a_permanently_locked_outdir_raises_within_the_deadline(self):
        """A one-second budget against the 60 s initial delay: the deadline is
        already spent when the first lock response arrives, so the refusal is
        terminal -- one submission, no sleep, and the diagnostic surfaced."""
        proc = unittest.mock.Mock(returncode=1,
                                  stdout=json.dumps(self._error()), stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            req = tmp / "request.json"
            req.write_text("{}")
            with unittest.mock.patch("subprocess.run", return_value=proc) as run, \
                    unittest.mock.patch.object(kb.time, "sleep") as sleep, \
                    unittest.mock.patch.object(kb.random, "uniform",
                                               return_value=0.0), \
                    self.assertRaises(kb.KltError) as raised:
                kb.run(req, tmp / "out", backend="batch",
                              max_lock_wait_s=1)
        self.assertEqual(1, run.call_count)
        sleep.assert_not_called()
        self.assertIn("is owned by another run", str(raised.exception))

    def test_a_final_fleet_capacity_error_is_not_retried(self):
        """klt already waited out the fleet under ``capacity_wait_s`` (issue
        #610): a capacity refusal that still reaches the harness raises after
        one invocation, with no harness sleep, and the diagnostic is kept."""
        for code in ("batch_no_capacity", "batch_concurrency_cap"):
            with self.subTest(code=code):
                message = f"launch refused: {code}"
                err = {"schema_version": 1,
                       "error": {"command": "sim", "code": code,
                                 "message": message}}
                proc = unittest.mock.Mock(returncode=1,
                                          stdout=json.dumps(err), stderr="")
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp = Path(tmpdir)
                    req = tmp / "request.json"
                    req.write_text("{}")
                    with unittest.mock.patch("subprocess.run", return_value=proc) as run, \
                            unittest.mock.patch.object(kb.time, "sleep") as sleep, \
                            self.assertRaises(kb.KltError) as raised:
                        kb.run(req, tmp / "out", backend="batch",
                                      max_lock_wait_s=600)
                self.assertEqual(1, run.call_count)
                sleep.assert_not_called()
                self.assertIn(message, str(raised.exception))

    def test_the_legacy_cap_refusal_wording_is_final_too(self):
        """The pre-#610 loop keyed on the ``BATCH_MAX_CONCURRENT_INSTANCES``
        wording and re-submitted; that substring no longer buys a retry, so a
        wording change upstream cannot resurrect a dead code path."""
        message = "launch refused: request exceeds BATCH_MAX_CONCURRENT_INSTANCES"
        proc = unittest.mock.Mock(returncode=1, stdout="", stderr=message)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            req = tmp / "request.json"
            req.write_text("{}")
            with unittest.mock.patch("subprocess.run", return_value=proc) as run, \
                    unittest.mock.patch.object(kb.time, "sleep") as sleep, \
                    self.assertRaises(kb.KltError) as raised:
                kb.run(req, tmp / "out", backend="batch",
                              max_lock_wait_s=600)
        self.assertEqual(1, run.call_count)
        sleep.assert_not_called()
        self.assertIn(message, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
