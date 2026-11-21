#!/usr/bin/env python3
"""Unit tests for sim/harness/klt_record.py. No PDK, ngspice or klt required.

    python3 -m unittest sim/tests/test_klt_record.py -v
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import evidence_store as es  # noqa: E402
from harness import klt_record as kr  # noqa: E402
from harness import pdk  # noqa: E402
from harness import report  # noqa: E402
from harness import tb_adapter as ta  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_evidence_store import fake_klt  # noqa: E402

SLUG = "line-regulation"


class ParsePrior(unittest.TestCase):
    def _newest(self, slug):
        return sorted((SIM_DIR / slug / "records").glob("*.md"))[-1]

    def test_reads_only_the_result_table(self):
        # The spread table that follows quotes measurement names in backticks too.
        cols, grid, shas = kr.parse_prior(self._newest("psrr-vs-freq"))
        self.assertEqual(cols[:2], ["psrr_1k_db", "psrr_100k_db"])
        self.assertEqual(len(grid), 45)
        self.assertTrue(all(c.count("_") >= 2 for c in grid), sorted(grid)[:3])
        self.assertTrue(shas)

    def test_a_cell_that_is_not_a_number_is_none(self):
        _, grid, _ = kr.parse_prior(self._newest("psrr-vs-freq"))
        row = grid["tt_27c_3.30v"]
        self.assertIsInstance(row["psrr_1k_db"], float)
        self.assertIsNone(row["pass/fail"])


class FleetJobs(unittest.TestCase):
    def _jobs(self, remote):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            rep = Path(d) / "klt-3.30v" / "new"
            rep.mkdir(parents=True)
            (rep / "klt-report.json").write_text(json.dumps({"corner_count": 4, "environment": {"remote": remote}}))
            return kr.jobs(Path(d))

    def test_split_request_lists_every_fleet_job(self):
        pdk = {"models_staged": True, "stamp_text": "open_pdks c6d73a3"}
        job = lambda i: {"job_id": f"klt-sim-{i}", "instance_type": "c7i.8xlarge", "state": "done",
                         "worker_environment": {"pdk": pdk}}
        (j,) = self._jobs({"fleet": [job(1), job(2)], "max_concurrent_jobs": 2})
        self.assertEqual(j["job"], "klt-sim-1, klt-sim-2")
        self.assertTrue(j["staged"])
        self.assertEqual(j["stamp"], "open_pdks c6d73a3")

    def test_one_unstaged_fleet_job_unsets_staged(self):
        mk = lambda s: {"job_id": "x", "worker_environment": {"pdk": {"models_staged": s}}}
        (j,) = self._jobs({"fleet": [mk(True), mk(False)]})
        self.assertFalse(j["staged"])

    def test_unsplit_request_keeps_its_single_job(self):
        (j,) = self._jobs({"job_id": "klt-sim-9", "instance_type": "m7i.4xlarge", "state": "done",
                           "worker_environment": {"pdk": {"models_staged": True}}})
        self.assertEqual((j["job"], j["instance"], j["staged"]), ("klt-sim-9", "m7i.4xlarge", True))


class FlatBenchJobs(unittest.TestCase):
    """A single-analysis bench is one request and writes ``new/klt-report.json``
    with no ``klt-*`` level; the old glob listed zero jobs for it (#594)."""

    def test_a_request_with_no_klt_level_is_still_found(self):
        with tempfile.TemporaryDirectory() as d:
            rep = Path(d) / "new"
            rep.mkdir(parents=True)
            (rep / "klt-report.json").write_text(json.dumps(
                {"corner_count": 81, "environment": {"remote": {
                    "job_id": "klt-sim-7", "instance_type": "c7i.8xlarge", "state": "done",
                    "worker_environment": {"pdk": {"models_staged": True,
                                                   "stamp_text": "open_pdks c6d73a3"}}}}}))
            (j,) = kr.jobs(Path(d))
        self.assertEqual((j["request"], j["job"], j["corners"]), ("single", "klt-sim-7", 81))

    def test_the_klt_level_layout_still_wins_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            for sub in ("klt-op1-3.30v", "klt-ac1-3.30v"):
                rep = Path(d) / sub / "new"
                rep.mkdir(parents=True)
                (rep / "klt-report.json").write_text(json.dumps(
                    {"corner_count": 27, "environment": {"remote": {"job_id": sub}}}))
            got = kr.jobs(Path(d))
        self.assertEqual([j["request"] for j in got], ["ac1-3.30v", "op1-3.30v"])

    def test_a_run_with_no_report_at_all_is_refused(self):
        """Minting a batch-fleet record with zero job data would make the
        staging claim vacuous (``all([])``); that is an error now (#604)."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "summary.csv").write_text("dut,corner\nnew,tt_27c_3.30v\n")
            with self.assertRaises(SystemExit):
                kr.jobs(Path(d))

    def test_environment_axes_are_captured_per_request(self):
        """backend / model library / solver build / stamp comparison feed the
        derived old-vs-new environment section and the PDK line (#604)."""
        with tempfile.TemporaryDirectory() as d:
            rep = Path(d) / "klt-2.97v" / "new"
            rep.mkdir(parents=True)
            (rep / "klt-report.json").write_text(json.dumps({
                "corner_count": 27,
                "environment": {
                    "backend": {"resolved": "batch"},
                    "models_lib_sha256": "a" * 64,
                    "engine_version": 47,
                    "engine_build": {"binary_sha256": "b" * 64},
                    "remote": {"job_id": "klt-sim-3", "instance_type": "m7i.4xlarge",
                               "state": "done",
                               "worker_environment": {
                                   "pdk": {"models_staged": True,
                                           "stamp_text": "open_pdks " + "f" * 40},
                                   "pdk_stamp_comparison": {"status": "match"}}}}}))
            (j,) = kr.jobs(Path(d))
        self.assertEqual(j["backend"], "batch")
        self.assertEqual(j["models_lib"], "a" * 64)
        self.assertEqual((j["engine_version"], j["engine_sha"]), (47, "b" * 64))
        self.assertEqual(j["stamp_cmp"], "match")


class StoreRun(unittest.TestCase):
    """DR-0044 (#594): minting stores the bytes and commits only the manifest,
    the record, the netlist snapshot and the ``klt-report.json`` envelopes."""

    RID = "20261113-zz-test-0abcdef"
    #: a second, distinct record id staged for the same bench (issue #802)
    SIB = "20261113-zz-sibl-0bedeca"

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.repo = Path(td.name).resolve()
        shutil.copytree(SIM_DIR / SLUG / "testbench", self.repo / "sim" / SLUG / "testbench")
        self.exp = self.repo / "sim" / SLUG
        self.stage = ta.stage_corner_dir(self.repo, SLUG, self.RID)
        self._stage()
        self.objects = {}
        self._patch(kr, "REPO", self.repo)

    def _stage(self, rid: str | None = None):
        """Write one request's worth of staged output, in run_ab/collect's layout.

        A successful mint consumes the record's own staged scratch (#802), so
        a test that mints the same record id twice must restage in between --
        otherwise the second attempt stops at the "no staged run" guard instead
        of reaching the refusal it means to exercise.
        """
        stage = ta.stage_corner_dir(self.repo, SLUG, self.RID if rid is None else rid)
        (stage / "new").mkdir(parents=True, exist_ok=True)
        (stage / "new" / "klt-report.json").write_text(json.dumps(
            {"corner_count": 1, "environment": {"remote": {
                "job_id": "klt-sim-1", "instance_type": "c7i.8xlarge", "state": "done",
                "worker_environment": {"pdk": {"models_staged": True,
                                               "stamp_text": "open_pdks c6d73a3"}}}}}))
        (stage / "new" / "tt_27c_3.30v.log").write_text("ngspice log bytes\n")
        (stage / "new" / "dut.spice").write_text("* dut\n")
        (stage / "new" / "body.spice").write_text("* body\n")
        (stage / "new" / "request.json").write_text('{"engine": "ngspice"}\n')
        (stage / "summary.csv").write_text(
            "dut,corner,line_reg_pct_per_v,status,diagnostics,pass\n"
            "new,tt_27c_3.30v,0.01,pass,,True\n")

    def _patch(self, mod, name, value):
        old = getattr(mod, name)
        setattr(mod, name, value)
        self.addCleanup(lambda: setattr(mod, name, old))

    #: the pristine writer, captured before any patch, so a retry in the same
    #: test is not routed through the previous attempt's failing stub.
    _put_files = staticmethod(es.put_files)

    def _mint(self, rid: str | None = None, **kw):
        # `store_files` resolves `put_files` from the module at call time, so
        # patching it here routes every put through the shared `fake_klt` stub.
        self._patch(es, "put_files",
                    lambda files, root, **_: self._put_files(
                        files, root, run=fake_klt(self.objects, **kw)))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = kr.main([SLUG, "--record-id", self.RID if rid is None else rid])
        self.out, self.err = out.getvalue(), err.getvalue()
        return rc

    def test_install_kept_is_evidence_store_s_one_copy(self):
        # Moved beside split_batch_run (issue #645) so a tb-free caller can
        # share it; klt_record must use that copy, not a second definition.
        self.assertIs(kr.install_kept, es.install_kept)

    def test_bytes_are_stored_and_only_the_kept_files_are_committed(self):
        self.assertEqual(self._mint(), 0)
        new = sorted(q.relative_to(self.repo).as_posix() for q in self.repo.rglob("*")
                     if q.is_file() and ".work" not in q.parts and "testbench" not in q.parts)
        self.assertEqual(new, [
            f"manifests/artifacts/{SLUG}-{self.RID}.manifest.json",
            f"sim/{SLUG}/corners/{self.RID}/new/klt-report.json",
            f"sim/{SLUG}/netlist-snapshots/{self.RID}.spice",
            f"sim/{SLUG}/records/{self.RID}.md",
        ])

    def test_the_manifest_names_the_stored_files_and_not_the_kept_ones(self):
        self._mint()
        m = json.loads((self.repo / "manifests/artifacts"
                        / f"{SLUG}-{self.RID}.manifest.json").read_text())
        names = [e["name"] for e in m["entries"]]
        prefix = f"sim/{SLUG}/corners/{self.RID}"
        self.assertEqual(names, [f"{prefix}/new/body.spice", f"{prefix}/new/dut.spice",
                                 f"{prefix}/new/request.json", f"{prefix}/new/tt_27c_3.30v.log",
                                 f"{prefix}/summary.csv"])
        # check_artifact_manifests.py fails an entry whose name is a tracked
        # path, so a file that stays in git must never also be an entry.
        self.assertNotIn(f"{prefix}/new/klt-report.json", names)

    def test_the_record_ends_with_the_stored_evidence_table(self):
        self._mint()
        text = (self.exp / "records" / f"{self.RID}.md").read_text()
        self.assertIn("## Stored evidence", text)
        self.assertIn(f"`sim/{SLUG}/corners/{self.RID}/new/tt_27c_3.30v.log`", text)
        self.assertIn("is a **manifest `name`**", text)
        self.assertIn("`klt-sim-1`", text)   # the flat layout's job, via jobs()

    def test_a_store_failure_commits_nothing_and_keeps_the_staged_run(self):
        self.assertEqual(self._mint(fail="broker_unreachable"), kr.EXIT_NOT_STORED)
        self.assertFalse((self.repo / "manifests").exists())
        self.assertFalse((self.exp / "records").exists())
        self.assertFalse((self.exp / "corners").exists())
        self.assertFalse((self.exp / "netlist-snapshots").exists())
        self.assertTrue((self.stage / "new" / "tt_27c_3.30v.log").is_file())

    def test_a_retry_after_a_store_failure_succeeds(self):
        # The first attempt leaves a staged netlist snapshot behind; the retry
        # must not be refused by it (the committed tree is still untouched).
        self.assertEqual(self._mint(fail="broker_unreachable"), kr.EXIT_NOT_STORED)
        self.assertTrue((ta.stage_experiment_dir(self.repo, SLUG)
                         / "netlist-snapshots" / f"{self.RID}.spice").is_file())
        self.assertEqual(self._mint(), 0)
        self.assertTrue((self.exp / "records" / f"{self.RID}.md").is_file())
        self.assertTrue((self.exp / "netlist-snapshots" / f"{self.RID}.spice").is_file())

    def test_minting_the_same_record_id_twice_is_refused(self):
        self.assertEqual(self._mint(), 0)
        manifest = self.repo / "manifests/artifacts" / f"{SLUG}-{self.RID}.manifest.json"
        record = self.exp / "records" / f"{self.RID}.md"
        committed = (manifest.read_text(), record.read_text())
        # Restage, or the second attempt is refused by the staging guard that
        # test_an_unstaged_record_id_is_refused_before_anything_is_written
        # already covers. The hoisted kept-destination refusal (#662) now
        # fires before `store_files`' overwrite guard; either way the mint is
        # refused and nothing is rewritten.
        self._stage()
        self.assertEqual(self._mint(), kr.EXIT_NOT_STORED)
        self.assertIn("already exists; append-only evidence is never rewritten", self.err)
        # Neither committed artifact was rewritten, and the second run's bytes
        # are still staged rather than lost.
        self.assertEqual((manifest.read_text(), record.read_text()), committed)
        self.assertTrue((self.stage / "new" / "tt_27c_3.30v.log").is_file())

    def test_a_pre_existing_kept_envelope_refuses_before_anything_is_written(self):
        """A kept envelope already at its committed destination refuses the
        mint up front (#662): left to `install_kept`, the refusal would fire
        only after the manifest and record were already committed."""
        committed = self.exp / "corners" / self.RID / "new" / "klt-report.json"
        committed.parent.mkdir(parents=True)
        committed.write_text("{}\n")
        self.assertEqual(self._mint(), kr.EXIT_NOT_STORED)
        self.assertIn("already exists; append-only evidence is never rewritten", self.err)
        self.assertFalse(self.objects)   # refused before any put reached the store
        self.assertFalse((self.repo / "manifests").exists())
        self.assertFalse((self.exp / "records" / f"{self.RID}.md").exists())
        self.assertFalse((self.exp / "netlist-snapshots").exists())
        self.assertTrue((self.stage / "new" / "klt-report.json").is_file())

    def test_an_unstaged_record_id_is_refused_before_anything_is_written(self):
        with self.assertRaises(SystemExit) as cm:
            kr.main([SLUG, "--record-id", "20261113-absent-0abcdef"])
        self.assertIn("no staged run", str(cm.exception))
        self.assertFalse((self.repo / "manifests").exists())

    def test_a_staged_run_with_no_report_is_refused_before_minting(self):
        """The empty-`corner_dir` guard fires end to end: nothing is stored
        and nothing is committed (#604, step 2)."""
        for p in self.stage.rglob("klt-report.json"):
            p.unlink()
        with self.assertRaises(SystemExit):
            self._mint()
        self.assertFalse((self.repo / "manifests").exists())
        self.assertFalse((self.exp / "records" / f"{self.RID}.md").exists())

    def test_minting_one_record_leaves_a_sibling_staged_run_alone(self):
        """Issue #802: the staging tree is shared by every record id of a
        bench, so one record's successful mint consumes only its own scratch.

        The bench-wide rmtree this replaces erased the sibling's summary.csv,
        and minting the sibling then died at the "no staged run" guard."""
        self._stage(self.SIB)
        sibling = ta.stage_corner_dir(self.repo, SLUG, self.SIB)
        self.assertEqual(self._mint(), 0)
        # The completed record's own scratch is consumed ...
        self.assertFalse(self.stage.exists())
        self.assertFalse((ta.stage_experiment_dir(self.repo, SLUG) / report.SNAPSHOT_DIR
                          / f"{self.RID}.spice").exists())
        # ... the sibling's staged bytes survived, and it still mints.
        self.assertTrue((sibling / "summary.csv").is_file())
        self.assertTrue((sibling / "new" / "tt_27c_3.30v.log").is_file())
        self.assertEqual(self._mint(self.SIB), 0)
        self.assertTrue((self.exp / "records" / f"{self.SIB}.md").is_file())
        self.assertFalse(sibling.exists())

    def test_a_run_kept_for_retry_survives_another_records_mint(self):
        """Issue #802's sharpest edge: a sibling the store refused is kept
        staged for retry (the fail-closed contract); minting a *different*
        record of the same bench must not erase those retry inputs."""
        self._stage(self.SIB)
        sibling = ta.stage_corner_dir(self.repo, SLUG, self.SIB)
        self.assertEqual(self._mint(self.SIB, fail="broker_unreachable"),
                         kr.EXIT_NOT_STORED)
        self.assertEqual(self._mint(), 0)
        self.assertTrue((sibling / "summary.csv").is_file())
        self.assertTrue((sibling / "new" / "tt_27c_3.30v.log").is_file())
        # The retry the kept bytes exist for goes through.
        self.assertEqual(self._mint(self.SIB), 0)
        self.assertTrue((self.exp / "records" / f"{self.SIB}.md").is_file())


def _fake_tb():
    return SimpleNamespace(
        experiment="scratch-bench", measure=["line_reg_mvpv"], claim="A claim.",
        checks={"line_reg_mvpv": {"max": 5.0}}, operating_conditions={"load": "1 mA"},
        netlist=SimpleNamespace(name="tb_scratch.spice"))


def _points(values):
    return [SimpleNamespace(status="ok", measurements={"line_reg_mvpv": v},
                            point=SimpleNamespace(corner_id=cid), message="pass", diagnostics="")
            for cid, v in values]


def _job(**over):
    j = {"request": "single", "job": "klt-sim-1", "instance": "c7i.8xlarge", "state": "done",
         "staged": True, "stamp": "open_pdks " + "f" * 40, "stamp_cmp": "match",
         "backend": "batch", "models_lib": "a" * 64, "engine_version": 47,
         "engine_sha": "b" * 64, "corners": 1}
    j.update(over)
    return j


NEW_RID = "20260202-new0001-rec0"
OLD_RID = "20260101-old0001-rec0"


class _RepoTree(unittest.TestCase):
    """A scratch tree laid out like ``sim/<slug>/``, with ``kr.REPO`` unused by
    ``prior_env`` (paths come from the prior record's own location)."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.repo = Path(td.name).resolve()

    def _prior(self, cited_sha, *, reports=None, text_extra=""):
        rec = self.repo / "records" / f"{OLD_RID}.md"
        rec.parent.mkdir(parents=True, exist_ok=True)
        rec.write_text("\n".join([
            f"# Record {OLD_RID}", "",
            f"Netlist sha256 `{cited_sha}`.", text_extra, "",
            "  | corner-id | line_reg_mvpv | pass/fail |",
            "  |---|---|---|",
            "  | `tt_27c_3.30v` | 1.0 | PASS |",
        ]) + "\n")
        if reports is not None:
            d = self.repo / "corners" / OLD_RID / "new"
            d.mkdir(parents=True, exist_ok=True)
            (d / "klt-report.json").write_text(json.dumps({"environment": reports}))
        return rec

    def _render(self, prior, dut_sha, grid_jobs=None):
        if grid_jobs is None:
            grid_jobs = [_job()]
        return kr.render(_fake_tb(), NEW_RID, _points([("tt_27c_3.30v", 1.1)]),
                         grid_jobs, prior, "design/netlist/ldo.spice",
                         dut_sha, "driver")


class RenderSupersedes(_RepoTree):
    """Step 5: the *Supersedes* line is derived from the priors list."""

    def test_a_prior_record_is_named(self):
        prior = self._prior("c" * 64)
        text = self._render(prior, "c" * 64)
        self.assertIn(f"- **Supersedes**: `{OLD_RID}`", text)
        self.assertNotIn("First record for this bench", text)

    def test_none_is_said_only_when_there_is_no_prior(self):
        text = self._render(None, "c" * 64)
        self.assertIn("- **Supersedes**: none", text)
        self.assertIn("No earlier record of this bench exists.", text)


class RenderPdkLine(_RepoTree):
    """Steps 3-4: staging and the stamp comparison are read, never asserted."""

    def test_a_matching_stamp_is_said_not_predicted(self):
        text = self._render(None, "c" * 64, [_job(stamp_cmp="match")])
        self.assertIn("`pdk_stamp_comparison` reads `match`", text)
        self.assertNotIn("is expected", text)
        self.assertNotIn("mismatch", text)

    def test_a_mismatching_stamp_is_said_too(self):
        text = self._render(None, "c" * 64, [_job(stamp_cmp="mismatch")])
        self.assertIn("`pdk_stamp_comparison` reads `mismatch`", text)
        self.assertNotIn("is expected", text)

    def test_staging_is_claimed_only_from_job_data(self):
        text = self._render(None, "c" * 64, [_job(), _job(request="3.63v")])
        self.assertIn("staged with every request", text)
        self.assertIn("in all 2 reports", text)

    def test_a_request_that_did_not_stage_is_named(self):
        text = self._render(None, "c" * 64, [_job(), _job(request="3.63v", staged=False)])
        self.assertIn("staged with 1 of the 2 requests", text)
        self.assertIn("`klt-3.63v`", text)
        self.assertNotIn("staged with every request", text)

    def test_no_job_data_is_never_a_vacuous_staging_claim(self):
        text = self._render(None, "c" * 64, grid_jobs=[])
        self.assertIn("Model staging is **not determined** (no job data)", text)
        self.assertNotIn("models_staged: true", text)


class CompareEnvironment(_RepoTree):
    """Step 6 (#612): the old-vs-new environment axes are derived."""

    CUR_SHA = "c" * 64
    PIN = pdk.PINNED_OPEN_PDKS_REVISION

    @staticmethod
    def _prior_reports(models_lib, engine_version, engine_sha):
        return {"backend": {"resolved": "batch"}, "models_lib_sha256": models_lib,
                "engine_version": engine_version,
                "engine_build": {"binary_sha256": engine_sha}}

    def _prior_pdk_line(self, hex40):
        # both record formats carry a PDK line naming the revision the record
        # pins; it is the authoritative PDK axis (the worker stamp is the
        # image's, and models are staged over it)
        return "- PDK: gf180mcuD @ open_pdks `" + hex40 + "`"

    def test_a_moved_build_is_named_when_backend_and_pdk_match(self):
        # The 20261113-vs-20261021 shape: same fleet, same pin, new solver.
        prior = self._prior(self.CUR_SHA, reports=self._prior_reports("a" * 64, 46, "c8" + "0" * 62),
                            text_extra=self._prior_pdk_line(self.PIN))
        text = self._render(prior, self.CUR_SHA)
        self.assertIn("differ in ngspice build", text)
        self.assertIn("ngspice-47", text)
        self.assertIn("ngspice-46", text)
        self.assertNotIn("differ in backend", text)
        self.assertNotIn("differ in open_pdks revision", text)
        self.assertNotIn("differ in model library", text)
        self.assertNotIn("c6d73a3", text)

    def test_a_pdk_delta_is_named_when_present(self):
        prior = self._prior(self.CUR_SHA, reports=self._prior_reports("a" * 64, 47, "b" * 64),
                            text_extra=self._prior_pdk_line("c" * 40))
        text = self._render(prior, self.CUR_SHA)
        self.assertIn("differ in open_pdks revision", text)
        self.assertIn(f"`{self.PIN[:8]}…` vs `{'c' * 8}…`", text)

    def test_an_axis_either_side_cannot_speak_for_is_not_a_delta(self):
        prior = self._prior(self.CUR_SHA, text_extra=self._prior_pdk_line("c" * 40)
                            + "\n- ngspice: ngspice-47 : banner")
        text = self._render(prior, self.CUR_SHA)
        self.assertIn("Not determined:", text)
        self.assertIn("backend (not determined from the earlier record)", text)
        self.assertIn("model library (not determined from the earlier record)", text)
        self.assertNotIn("differ in backend", text)
        self.assertNotIn("differ in model library", text)

    def test_the_prior_record_text_is_the_fallback_when_it_has_no_reports(self):
        prior = self._prior(self.CUR_SHA, text_extra=self._prior_pdk_line("c" * 40)
                            + "\n- ngspice: ngspice-47 : banner")
        text = self._render(prior, self.CUR_SHA)
        self.assertIn("ngspice binary build (both versions are ngspice-47)", text)
        self.assertNotIn("differ in ngspice build", text)

    def test_prior_reports_win_over_the_text_fallback(self):
        prior = self._prior(self.CUR_SHA, reports=self._prior_reports("a" * 64, 45, "d" * 64),
                            text_extra="- ngspice: ngspice-46 : banner")
        text = self._render(prior, self.CUR_SHA)
        self.assertIn("ngspice-45", text)
        self.assertNotIn("ngspice-46", text)

    def test_the_not_same_dut_branch_derives_too(self):
        prior = self._prior("9" * 64, reports=self._prior_reports("a" * 64, 46, "c8" + "0" * 62),
                            text_extra=self._prior_pdk_line(self.PIN))
        text = self._render(prior, self.CUR_SHA)
        self.assertIn("is **not** the DUT that record cites", text)
        self.assertNotIn("backend and PDK revision together", text)
        self.assertIn("differ in ngspice build", text)

    def test_every_axis_equal_is_reported_as_a_match(self):
        prior = self._prior(self.CUR_SHA, reports=self._prior_reports("a" * 64, 47, "b" * 64),
                            text_extra=self._prior_pdk_line(self.PIN))
        text = self._render(prior, self.CUR_SHA)
        self.assertIn("match on every environment axis", text)
        self.assertNotIn("differ in", text)


if __name__ == "__main__":
    unittest.main()
