#!/usr/bin/env python3
"""Unit tests for sim/mc-output-accuracy/testbench/klt_run.py. No PDK, ngspice or klt required.

Also covers the bench's DR-0044 routing (issue #647): the driver stages into
``sim/.work/.stage/`` instead of committing under ``corners/``, refuses an
unstorable run before any fleet time, refuses a committed record id, and
mints through ``run_store_evidence.py --kind corners``; the FB-current probe
(``probe_fb_current.py``) refuses a protected ``--out`` and an unavailable
store; and ``summarize.py`` takes a directory as well as a record id.

    python3 -m unittest sim/tests/test_mc_klt_run.py -v
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

SIM_DIR = Path(__file__).resolve().parents[1]
REPO = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.loader import load_script  # noqa: E402

mc = load_script(
    "mc_klt_run", SIM_DIR / "mc-output-accuracy" / "testbench" / "klt_run.py")
probe = load_script(
    "mc_probe_fb_current",
    SIM_DIR / "mc-output-accuracy" / "testbench" / "probe_fb_current.py")
mc_summarize = load_script(
    "mc_summarize_cli", SIM_DIR / "mc-output-accuracy" / "summarize.py")

from harness import evidence_store as es  # noqa: E402
from harness import tb_adapter as ta  # noqa: E402
import driver_routing as drt  # noqa: E402

MC_RECORD = "20260905-223503-3093ea1"


def _sample(offset: float, dfb: float | None = None) -> dict:
    s = {f"dv_{k}": offset + 0.01 * k for k in range(1, mc.COPIES + 1)}
    s["dfb"] = s["dv_1"] / 1.5 if dfb is None else dfb
    return s


class Statistics(unittest.TestCase):
    def test_matches_tb_json_definitions(self):
        samples = {i: _sample(0.1 * i) for i in range(4)}
        st = mc.statistics(samples)
        dv = [v for s in samples.values() for k, v in s.items() if k.startswith("dv_")]
        mean = sum(dv) / len(dv)
        sd = math.sqrt(sum((x - mean) ** 2 for x in dv) / (len(dv) - 1))
        self.assertEqual(st["n_samples"], 100)
        self.assertAlmostEqual(st["mean_mv"], mean)
        self.assertAlmostEqual(st["sigma_mv"], sd)
        self.assertAlmostEqual(st["sigma3_mv"], 3 * sd)
        self.assertAlmostEqual(st["vos_in_sigma3_mv"], 2 * sd)
        self.assertAlmostEqual(st["worst_abs_mv"], max(abs(x) for x in dv))
        self.assertAlmostEqual(st["divider_exact_uv"], 0.0, places=6)
        self.assertEqual(st["n_bad_solves"], 0)

    def test_divider_residual_is_in_microvolts(self):
        st = mc.statistics({0: _sample(0.0, dfb=_sample(0.0)["dv_1"] / 1.5 + 0.002)})
        self.assertAlmostEqual(st["divider_exact_uv"], 1.5 * 0.002 * 1e3)

    def test_a_sample_off_regulation_is_a_bad_solve(self):
        samples = {0: _sample(0.0), 1: _sample(150.0)}
        self.assertEqual(mc.statistics(samples)["n_bad_solves"], 1)


class SampleRows(unittest.TestCase):
    def _corner(self, idx, status="pass", missing=False):
        meas = [{"name": m["name"], "value": None if (missing and m["name"] == "dv_3") else 0.1}
                for m in mc.MEASUREMENTS]
        return {"corner_id": f"tt/novdd/27C/mc{idx}", "process": "tt", "temperature_c": 27.0,
                "status": status, "supply_v": {}, "measurements": meas,
                "monte_carlo": {"sample_index": idx}}

    def test_a_lost_sample_is_not_counted(self):
        """A point that loses samples must fail the 1000-sample check, not report a thinner distribution."""
        job = mc.job("new", Path("dut.spice"), 3.30, "tt", None, 3, 1)
        report = {"corners": [self._corner(0), self._corner(1, status="error"), self._corner(2, missing=True)]}
        rows = mc.sample_rows(report, job)
        self.assertEqual({k: sorted(v) for k, v in rows.items()}, {"tt_27c_3.30v": [0]})

    def test_request_is_the_monte_carlo_form(self):
        job = mc.job("new", Path("dut.spice"), 3.63, "ff", None, 40, 469)
        req = job.request()
        self.assertEqual(req["monte_carlo"], {"n": 40, "seed": 469, "vary": "mismatch"})
        self.assertEqual(req["analysis"]["kind"], "op")
        self.assertEqual(len(req["measurements"]), mc.COPIES + 1)
        self.assertEqual(len(job.body.split("X1 ")), 2)
        self.assertIn(".param vdd_val=3.63", job.body)
        self.assertIs(req["options"]["stage_model_inputs"], True)


class McDriverRouting(unittest.TestCase):
    """DR-0044, issue #647: the mc driver stages, refuses and mints.

    ``run_ab`` is faked with a writer that emits one healthy Monte Carlo
    sample at every temperature of each shard (the axes are read off the Job
    the driver's factory builds), so the run completes and the expected-point
    check passes without any PDK, ngspice, klt or fleet."""

    def setUp(self):
        self.rid = "20261117-zz-mc-driver-test"
        self.addCleanup(shutil.rmtree, ta.stage_corner_dir(REPO, "mc-output-accuracy", self.rid),
                        ignore_errors=True)
        self.dests: list[Path] = []
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def _run_ab(self, job_factory, dut, baseline_ref, dest, repo, **kw):
        self.dests.append(Path(dest))
        j = job_factory("new", Path("dut.spice"))
        proc, vin = j.process[0], j.supplies[0]
        corners = []
        for t in j.temps:
            tl = int(t) if float(t).is_integer() else t
            corners.append({"corner_id": f"{proc}_{tl}c_{vin:.2f}v", "process": proc,
                            "temperature_c": t, "status": "pass", "supply_v": {},
                            "measurements": [{"name": m["name"], "value": 0.1}
                                             for m in mc.MEASUREMENTS],
                            "monte_carlo": {"sample_index": 0}})
        report = json.dumps({"corners": corners})
        out = {}
        for tag in (["new", "baseline"] if baseline_ref else ["new"]):
            sub = Path(dest) / tag
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "klt-report.json").write_text(report)
            (sub / "tt_27c_3.30v.log").write_text("m_x = 1.0\n")
            out[tag] = None  # the driver re-reads the report it was handed
        return out

    def _main(self, argv, preflight):
        real_run_ab, real_find = mc.run_ab, mc.pdk.find_pdk
        mc.run_ab = self._run_ab
        mc.pdk.find_pdk = lambda variant=None: types.SimpleNamespace(path=Path("/nonexistent-pdk"))
        saved_root = os.environ.get("PDK_ROOT")

        def restore():
            mc.run_ab, mc.pdk.find_pdk = real_run_ab, real_find
            if saved_root is None:
                os.environ.pop("PDK_ROOT", None)
            else:
                os.environ["PDK_ROOT"] = saved_root
        self.addCleanup(restore)
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return mc.main(argv, preflight=preflight)

    def _staged(self) -> Path:
        return ta.stage_corner_dir(REPO, "mc-output-accuracy", self.rid)

    def _committed(self) -> Path:
        return SIM_DIR / "mc-output-accuracy" / "corners" / self.rid

    def test_a_run_stages_under_sim_work_not_into_corners(self):
        seen = []
        rc = self._main(["--record-id", self.rid], lambda repo: seen.append(repo))
        self.assertEqual(rc, 0)
        self.assertEqual(len(seen), 1, "the store is probed once, before any fleet time")
        staged = self._staged()
        self.assertTrue(staged.is_dir())
        self.assertTrue(self.dests and all(staged == d or staged in d.parents for d in self.dests),
                        self.dests)
        self.assertFalse(self._committed().exists())
        out = self.stdout.getvalue()
        self.assertIn(f"staged  : {staged} (not evidence yet)", out)
        self.assertIn("run_store_evidence.py", out)
        self.assertIn("--kind corners", out)
        self.assertIn(self.rid, out)

    def test_an_unstorable_run_exits_10_before_simulating(self):
        def refuse(repo):
            raise es.StoreError("no artifact broker configured ($KLT_ARTIFACT_BROKER is unset)")

        rc = self._main(["--record-id", self.rid], refuse)
        self.assertEqual(rc, ta.EXIT_NOT_STORED)
        self.assertEqual(self.dests, [], "the fleet was never asked to run anything")
        self.assertFalse(self._staged().exists())
        self.assertFalse(self._committed().exists())
        self.assertIn("EVIDENCE STORE UNAVAILABLE", self.stderr.getvalue())

    def test_an_only_debug_point_needs_no_store(self):
        def explode(repo):
            raise AssertionError("--only must not probe the store")

        rc = self._main(["--record-id", self.rid, "--only", "tt,27,3.30"], explode)
        self.assertEqual(rc, 0)
        self.assertTrue(self._staged().is_dir())

    def test_a_record_id_already_committed_is_refused(self):
        existing = sorted(p for p in (SIM_DIR / "mc-output-accuracy" / "corners").iterdir()
                          if p.is_dir())[0].name
        with self.assertRaises(SystemExit) as cm:
            self._main(["--record-id", existing], lambda repo: None)
        self.assertIn("append-only", str(cm.exception))
        self.assertEqual(self.dests, [])

    def test_a_minted_run_commits_only_manifest_summary_and_envelopes(self):
        rc = self._main(["--record-id", self.rid], lambda repo: None)
        self.assertEqual(rc, 0)
        staged = self._staged()
        rc2, root, committed = drt.mint("mc-output-accuracy", self.rid, staged)
        self.assertEqual(rc2, 0)
        envelopes = sorted(p.relative_to(staged).as_posix() for p in staged.rglob("klt-report.json"))
        self.assertEqual(committed, sorted(
            [f"manifests/artifacts/mc-output-accuracy-{self.rid}.manifest.json",
             f"sim/mc-output-accuracy/corners/{self.rid}.md"]
            + [f"sim/mc-output-accuracy/corners/{self.rid}/{e}" for e in envelopes]))
        for env in staged.rglob("klt-report.json"):
            dst = root / "sim" / "mc-output-accuracy" / "corners" / self.rid / env.relative_to(staged)
            self.assertEqual(dst.read_bytes(), env.read_bytes())
        staged_files = sorted(p.relative_to(staged).as_posix()
                              for p in staged.rglob("*") if p.is_file())
        m = json.loads((root / "manifests" / "artifacts"
                        / f"mc-output-accuracy-{self.rid}.manifest.json").read_text())
        self.assertEqual(sorted(e["name"] for e in m["entries"]),
                         [f"sim/mc-output-accuracy/corners/{self.rid}/{f}"
                          for f in staged_files if not f.endswith("klt-report.json")])
        self.assertEqual(drt.check_manifests(root), 0)


class ProbeFbCurrentRouting(unittest.TestCase):
    """Issue #647: the FB probe is routed, not exempt -- a run of it has been
    committed under ``corners/`` before (record 20261021-fb-injection-probe),
    and it writes per-corner ``klt-report.json`` envelopes and logs, so an
    ``--out`` inside a protected tree is refused, an unavailable store refuses
    the run before anything is written, and its raw output mints to the store."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "probe-out"
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def _main(self, argv, preflight=None):
        real_run, real_find = probe.kb.run, probe.pdk.find_pdk
        probe.kb.run = lambda req, outdir, backend=None: {"corners": []}
        probe.pdk.find_pdk = lambda variant=None: types.SimpleNamespace(path=Path("/nonexistent-pdk"))
        saved_root = os.environ.get("PDK_ROOT")

        def restore():
            probe.kb.run, probe.pdk.find_pdk = real_run, real_find
            if saved_root is None:
                os.environ.pop("PDK_ROOT", None)
            else:
                os.environ["PDK_ROOT"] = saved_root
        self.addCleanup(restore)
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return probe.main(argv, preflight=preflight)

    def test_a_probe_writes_store_bound_bytes_and_prints_the_mint(self):
        rc = self._main(["--out", str(self.out)], lambda repo: None)
        self.assertEqual(rc, 0)
        self.assertTrue((self.out / "probe.csv").is_file())
        for tag in ("new", "new-nosoftstart"):
            env = list((self.out / tag).rglob("klt-report.json"))
            self.assertTrue(env, f"no klt-report.json envelope for the {tag} DUT")
        out = self.stdout.getvalue()
        self.assertIn(f"staged  : {self.out} (not evidence yet)", out)
        self.assertIn("run_store_evidence.py", out)
        self.assertIn("--kind corners", out)

    def test_an_unstorable_probe_exits_10_having_written_nothing(self):
        def refuse(repo):
            raise es.StoreError("no artifact broker configured ($KLT_ARTIFACT_BROKER is unset)")

        rc = self._main(["--out", str(self.out)], refuse)
        self.assertEqual(rc, ta.EXIT_NOT_STORED)
        self.assertFalse(self.out.exists())
        self.assertIn("EVIDENCE STORE UNAVAILABLE", self.stderr.getvalue())

    def test_an_out_inside_a_protected_tree_is_refused(self):
        for rel in ("corners/20261117-zz-probe", "records/20261117-zz-probe",
                    "netlist-snapshots/20261117-zz-probe"):
            with self.assertRaises(SystemExit) as cm:
                self._main(["--out", str(SIM_DIR / "mc-output-accuracy" / rel)])
            self.assertIn("append-only", str(cm.exception))
            self.assertIn("stage_corner_dir", str(cm.exception))
        # the protected trees of the OTHER benches refuse too
        with self.assertRaises(SystemExit):
            self._main(["--out", str(SIM_DIR / "soft-start" / "corners" / "zz")])
        # and being the tree itself, not just a path under it
        with self.assertRaises(SystemExit):
            self._main(["--out", str(SIM_DIR / "mc-output-accuracy" / "corners")])
        self.assertFalse(self.out.exists())

    def test_a_probe_run_mints_to_envelopes_not_committed_bytes(self):
        rc = self._main(["--out", str(self.out)], lambda repo: None)
        self.assertEqual(rc, 0)
        rid = "20261117-zz-probe-mint"
        rc2, root, committed = drt.mint("mc-output-accuracy", rid, self.out)
        self.assertEqual(rc2, 0)
        envelopes = sorted(p.relative_to(self.out).as_posix()
                           for p in self.out.rglob("klt-report.json"))
        self.assertEqual(committed, sorted(
            [f"manifests/artifacts/mc-output-accuracy-{rid}.manifest.json",
             f"sim/mc-output-accuracy/corners/{rid}.md"]
            + [f"sim/mc-output-accuracy/corners/{rid}/{e}" for e in envelopes]))
        self.assertEqual(drt.check_manifests(root), 0)


class McSummarizeInput(unittest.TestCase):
    """Issue #647: ``summarize.py`` takes a directory (a staged run) as well as
    a bare record id (a committed record); ``test_summarizers.py`` stays
    unmodified (AC) and keeps passing (its golden record still resolves)."""

    def _main(self, arg: str) -> tuple[int, str]:
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["summarize.py", arg]), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = mc_summarize.main()
        return rc, buf.getvalue()

    def test_a_directory_rolls_up_like_a_record(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            logs = sorted((SIM_DIR / "mc-output-accuracy" / "corners" / MC_RECORD).glob("*.log"))[:3]
            for p in logs:
                (d / p.name).write_text(p.read_text())
            rc, out = self._main(str(d))
            self.assertEqual(rc, 0)
            self.assertIn("Corners: 3", out)

    def test_a_bare_record_id_still_resolves_against_corners(self):
        rc, out = self._main(MC_RECORD)
        self.assertEqual(rc, 0)
        self.assertIn(f"record {MC_RECORD}", out)

    def test_an_unknown_argument_is_refused(self):
        rc, out = self._main("20261117-no-such-record")
        self.assertEqual(rc, 2)
        self.assertIn("no such record", out)


if __name__ == "__main__":
    unittest.main()
