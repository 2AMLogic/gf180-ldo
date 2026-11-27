#!/usr/bin/env python3
"""Driver-level tests for the three hand-rolled ``klt_run.py`` benches
(current-limit, enable-shutdown, soft-start): DR-0044, issue #646 -- a run
stages into ``sim/.work/.stage/`` instead of committing under
``sim/<bench>/corners/``, an unavailable store refuses the run before any
fleet time, a committed record id is never rewritten, the driver prints the
``--kind corners`` mint, and minting commits only the manifest, the summary
and the ``klt-report.json`` envelopes. No PDK, ngspice, klt or fleet
required; ``run_ab``, ``find_pdk``, and the store's ``klt`` calls are faked.

    python3 -m unittest sim/tests/test_klt_run_drivers.py -v
"""

from __future__ import annotations

import contextlib
import csv
import io
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

from harness import pdk as pdk_mod  # noqa: E402
from harness.loader import load_script  # noqa: E402
from harness.klt_ab import write_summary_csv  # noqa: E402
import driver_routing as drt  # noqa: E402

_DRIVERS: dict[str, object] = {}


def _driver(slug: str):
    """The ``klt_run.py`` of ``sim/<slug>/testbench``, imported by path."""
    if slug not in _DRIVERS:
        _DRIVERS[slug] = load_script(
            f"klt_run_{slug.replace('-', '_')}",
            SIM_DIR / slug / "testbench" / "klt_run.py")
    return _DRIVERS[slug]


class _DriverCase(drt.RoutingContract):
    """One driver with ``run_ab`` faked: the fake writes each tag's envelope,
    one log and the frozen DUT into whatever ``dest`` the driver handed it.

    A plain mixin (not a TestCase) so the abstract base is not collected;
    the concrete classes below bind ``SLUG``."""

    SLUG = ""
    RID = "20261116-zz-driver-test"

    def setUp(self):
        self.mod = _driver(self.SLUG)
        super().setUp()

    def _run_ab(self, job_factory, dut, baseline_ref, dest, repo, **kw):
        self.dests.append(Path(dest))
        out = {}
        for tag in (["new", "baseline"] if baseline_ref else ["new"]):
            sub = Path(dest) / tag
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "klt-report.json").write_text('{"corners": []}\n')
            (sub / "tt_27c_3.30v.log").write_text("m_x = 1.0\n")
            (sub / "dut.spice").write_text("* frozen dut\n")
            out[tag] = {"tt_27c_3.30v": {"m_x": 1.0, "_status": "pass", "_diagnostics": ""}}
        return out

    def _summarize(self, cmd, **kw):
        # enable-shutdown rolls its logs up through summarize.py as a
        # subprocess; summarize takes the directory as argv and so follows
        # dest on its own -- record where it was pointed.
        self.dests.append(Path(cmd[2]))
        return types.SimpleNamespace(returncode=0)

    def _main(self, argv, preflight):
        real = self.mod.run_ab
        self.mod.run_ab = self._run_ab
        self.addCleanup(lambda: setattr(self.mod, "run_ab", real))
        drt.stub_pinned_pdk(self, pdk_mod, "/pinned/root/gf180mcuD")
        with contextlib.redirect_stdout(self.stdout), \
                contextlib.redirect_stderr(self.stderr), \
                mock.patch("subprocess.run", side_effect=self._summarize):
            return self.mod.main(argv, preflight=preflight)

    def test_a_baseline_ab_run_stages_and_stores_both_tags(self):
        rc = self._main(["--record-id", self.rid, "--baseline-ref", "origin/main"],
                        lambda repo: None)
        self.assertEqual(rc, 0)
        staged = self._staged()
        for tag in ("new", "baseline"):
            self.assertTrue(list(staged.rglob(f"{tag}/klt-report.json")),
                            f"no staged envelope for the {tag} DUT")
        rc, root, committed = drt.mint(self.SLUG, self.rid, self._staged(),
                                        cleanup=self.addCleanup)
        self.assertEqual(rc, 0)
        for env in staged.rglob("klt-report.json"):
            rel = f"sim/{self.SLUG}/corners/{self.rid}/{env.relative_to(staged)}"
            self.assertIn(rel, committed, f"the {rel} envelope was not committed")

    # -- the mint, through run_store_evidence.py --kind corners (#645) ------

    def test_a_minted_run_commits_only_manifest_summary_and_envelopes(self):
        rc = self._main(["--record-id", self.rid], lambda repo: None)
        self.assertEqual(rc, 0)
        drt.assert_corners_mint(self, self.SLUG, self.rid, self._staged())


class CurrentLimitDriver(_DriverCase, unittest.TestCase):
    SLUG = "current-limit"


class CurrentLimitGrade(unittest.TestCase):
    """Issue #823: the ``current-limit`` staged grader's one-sided
    ``thermal_ok`` bound (``p_short_mw <= PSHORT_MAX_MW``) lets ``-inf`` pass
    it, so a non-finite short-circuit current must fail closed, the way the
    two-sided ``in_window`` / ``reg_ok`` already do."""

    BASE = {"ilim_1764_ma": 80.0, "vout_50ma": 1.8}

    def test_non_finite_short_current_fails_thermal_ok_only(self):
        mod = _driver("current-limit")
        for bad in (float("-inf"), float("inf"), float("nan")):
            with self.subTest(ilim_0000_ma=bad):
                out = mod.grade({**self.BASE, "ilim_0000_ma": bad}, 1.764)
                self.assertIs(out["thermal_ok"], False)
                # the two-sided checks keep their behaviour for these inputs
                self.assertIs(out["in_window"], True)
                self.assertIs(out["reg_ok"], True)

    def test_finite_short_current_keeps_the_bounded_behaviour(self):
        mod = _driver("current-limit")
        cases = {
            None: False,   # no measurement at all
            5.0: True,     # 8.82 mW, at or below PSHORT_MAX_MW
            250.0: False,  # 441.0 mW, above PSHORT_MAX_MW
            -1.0: True,    # finite negative passes the guard (#823: in scope only
                           # as "not rejected by this change")
        }
        for ilim, expected in cases.items():
            with self.subTest(ilim_0000_ma=ilim):
                out = mod.grade({**self.BASE, "ilim_0000_ma": ilim}, 1.764)
                self.assertIs(out["thermal_ok"], expected)


class EnableShutdownDriver(_DriverCase, unittest.TestCase):
    SLUG = "enable-shutdown"


class SoftStartDriver(_DriverCase, unittest.TestCase):
    SLUG = "soft-start"

    def _summary_rows(self, name: str) -> tuple[list[str], list[dict]]:
        path = self._staged() / name
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            return list(reader.fieldnames or []), list(reader)

    def test_split_parts_accumulate_into_one_summary_csv(self):
        # Issue #704: --part main then --part extra roll up into one
        # summary.csv (the 1 + 5 shape) instead of extra clobbering main.
        rc = self._main(["--record-id", self.rid, "--part", "main"], lambda repo: None)
        self.assertEqual(rc, 0)
        _, rows = self._summary_rows("summary.csv")
        self.assertEqual(len(rows), 1, f"main alone: header + 1 row, got {rows}")
        rc = self._main(["--record-id", self.rid, "--part", "extra"], lambda repo: None)
        self.assertEqual(rc, 0)
        _, rows = self._summary_rows("summary.csv")
        self.assertEqual(len(rows), 6, f"header + main's 1 + extra's 5, got {rows}")
        self.assertEqual([r["cout"] for r in rows],
                         ["1u", "0.33u", "0.33u", "4.7u", "4.7u", "1u"],
                         "main's row must survive the extra write")
        self.assertEqual(sorted(p.name for p in self._staged().iterdir()),
                         ["extra-c1", "extra-c2", "extra-c3", "extra-c4", "extra-c5",
                          "main", "summary.csv"])

    def test_extra_expands_to_one_request_per_config_in_distinct_subdirs(self):
        # Issue #738: a 5-instance extra deck cannot fit the fleet's per-unit
        # ceiling, so --part extra submits five 1-instance requests, each
        # staged into its own extra-c<k>/ subdir (run_ab writes the envelope
        # un-suffixed into dest/<tag>); main stays one request as before.
        seen = []

        def _record(job_factory, dut, baseline_ref, dest, repo, **kw):
            job = job_factory("new", Path(dut))
            Path(dest).mkdir(parents=True, exist_ok=True)
            seen.append((Path(dest).name, job))
            return {"new": {"tt_27c_3.30v": {"m_x": 1.0, "_status": "pass", "_diagnostics": ""}}}

        self._run_ab = _record  # instance attr: _main patches run_ab to it
        rc = self._main(["--record-id", self.rid, "--part", "both"], lambda repo: None)
        self.assertEqual(rc, 0)
        self.assertEqual([name for name, _ in seen],
                         ["main"] + [f"extra-c{k}" for k in range(1, 6)])
        inst = "Xdut1 VIN1 VOUT1 EN 0 EOUT1 PG1 VREF ldo_core"
        for name, job in seen:
            insts = [ln.strip() for ln in job.body.splitlines() if ln.strip().startswith("Xdut")]
            self.assertEqual(insts, [inst], f"{name}: a 1-instance deck")
            self.assertEqual(len(job.measurements), 13)
            self.assertTrue(all(m["name"].endswith("_1") for m in job.measurements),
                            f"{name}: measurement names read as instance 1")
        main_job = dict(seen)["main"]
        self.assertEqual(main_job.measurements, self.mod.measurements(1),
                         "main's request is unchanged: the same 1-instance measurement set")

    def test_split_part_shards_at_one_process_accumulate_into_summary_tt(self):
        # Both parts at a fixed --process resolve to one summary-<process>.csv;
        # the second must merge, not clobber (#704).
        rc = self._main(["--record-id", self.rid, "--part", "main", "--process", "tt"],
                        lambda repo: None)
        self.assertEqual(rc, 0)
        _, rows = self._summary_rows("summary-tt.csv")
        self.assertEqual(len(rows), 1)
        rc = self._main(["--record-id", self.rid, "--part", "extra", "--process", "tt"],
                        lambda repo: None)
        self.assertEqual(rc, 0)
        self.assertIn("--part extra --process ff", self.stdout.getvalue(),
                      "the shard hint keeps the un-split part name (#738): one "
                      "`--part extra --process p` run covers all five requests")
        self.assertEqual(rc, 0)
        _, rows = self._summary_rows("summary-tt.csv")
        self.assertEqual(len(rows), 6, f"main's row must survive, got {rows}")
        self.assertEqual(sorted(p.name for p in self._staged().iterdir()),
                         ["extra-c1-tt", "extra-c2-tt", "extra-c3-tt", "extra-c4-tt",
                          "extra-c5-tt", "main-tt", "summary-tt.csv"],
                         "one shard file per --process, no unwritten summary.csv")

    def test_rerunning_the_same_part_replaces_its_rows_not_duplicates(self):
        rc = self._main(["--record-id", self.rid, "--part", "main"], lambda repo: None)
        self.assertEqual(rc, 0)
        rc = self._main(["--record-id", self.rid, "--part", "extra"], lambda repo: None)
        self.assertEqual(rc, 0)
        rc = self._main(["--record-id", self.rid, "--part", "extra"], lambda repo: None)
        self.assertEqual(rc, 0)
        _, rows = self._summary_rows("summary.csv")
        self.assertEqual(len(rows), 6,
                         f"extra's re-run replaces its own rows; main keeps its one: got {rows}")

    def test_shards_accumulate_into_one_record_and_mint_once_after_the_last(self):
        rc = self._main(["--record-id", self.rid, "--part", "main", "--process", "tt"],
                        lambda repo: None)
        self.assertEqual(rc, 0)
        self.assertTrue((self._staged() / "main-tt" / "new" / "klt-report.json").is_file())
        out = self.stdout.getvalue()
        self.assertIn("--part main --process ff", out)  # the shards still owed
        self.assertIn("after the last shard", out)
        self.stdout = io.StringIO()
        rc = self._main(["--record-id", self.rid, "--part", "main", "--process", "ff"],
                        lambda repo: None)
        self.assertEqual(rc, 0)
        # Both shards live in the same staged record; one mint commits both.
        staged = self._staged()
        self.assertTrue((staged / "main-tt" / "new" / "klt-report.json").is_file())
        self.assertTrue((staged / "main-ff" / "new" / "klt-report.json").is_file())
        committed, _ = drt.assert_corners_mint(self, self.SLUG, self.rid, staged)
        self.assertEqual(committed, sorted([
            f"manifests/artifacts/{self.SLUG}-{self.rid}.manifest.json",
            f"sim/{self.SLUG}/corners/{self.rid}.md",
            f"sim/{self.SLUG}/corners/{self.rid}/main-ff/new/klt-report.json",
            f"sim/{self.SLUG}/corners/{self.rid}/main-tt/new/klt-report.json",
        ]))


class WriteSummaryCsvMerge(unittest.TestCase):
    """The opt-in merge in ``harness.klt_ab.write_summary_csv`` (#704): rows
    keyed by ``merge_key`` replace their old row, headers union across
    invocations, a cell a row lacks is blank."""

    def _write(self, rows, path):
        with contextlib.redirect_stdout(io.StringIO()):
            write_summary_csv(rows, path, merge_key=("dut", "corner"))

    def test_differing_field_lists_union_with_missing_cells_blank(self):
        # klt_run's field list legitimately differs across parts ("a point
        # missing a crossing lacks derived keys") -- a verbatim strict-header
        # refusal would refuse valid runs (#704).
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "summary.csv"
            self._write([{"dut": "new", "corner": "c1", "slope_vpms": "2.0"}], path)
            self._write([{"dut": "new", "corner": "c2", "icap_peak_ma": "1.5"}], path)
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                fields = list(reader.fieldnames or [])
                rows = list(reader)
        self.assertEqual(fields, ["corner", "dut", "icap_peak_ma", "slope_vpms"])
        self.assertEqual(rows[0]["icap_peak_ma"], "")
        self.assertEqual(rows[1]["slope_vpms"], "")

    def test_string_key_rerun_replaces_not_appends(self):
        # The headline merge contract (#704): a re-run of the same string key
        # replaces its old row instead of appending a duplicate.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "summary.csv"
            self._write([{"dut": "new", "corner": "c1", "icap_peak_ma": "1.0"}], path)
            self._write([{"dut": "new", "corner": "c1", "icap_peak_ma": "2.0"}], path)
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1, "same string key: replace, not append")
        self.assertEqual(rows[0]["icap_peak_ma"], "2.0")

    def test_non_str_key_value_raises_instead_of_duplicating(self):
        # A non-str key cell (a float like 1e-6, say) never equals the str the
        # CSV round-trip wrote, so the old row would survive and a duplicate be
        # appended silently -- refuse loudly instead (#710).
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "summary.csv"
            self._write([{"dut": "new", "corner": "c1"}], path)
            with self.assertRaises(SystemExit):
                self._write([{"dut": "new", "corner": 1e-6}], path)
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual([r["corner"] for r in rows], ["c1"], "refusal leaves the file untouched")

    def test_none_key_value_raises_too(self):
        # A row missing a merge_key column reads as None -- same string-key
        # ambiguity, same refusal (#710).
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "summary.csv"
            self._write([{"dut": "new", "corner": "c1"}], path)
            with self.assertRaises(SystemExit):
                self._write([{"dut": "new", "icap_peak_ma": "1.5"}], path)

    def test_default_call_stays_truncate(self):
        # No merge_key -> the historical clobber, byte for byte: callers that
        # never opted in keep their behaviour (#704).
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "summary.csv"
            with contextlib.redirect_stdout(io.StringIO()):
                write_summary_csv([{"dut": "new", "corner": "c1"}], path)
                write_summary_csv([{"dut": "new", "corner": "c2"}], path)
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual([r["corner"] for r in rows], ["c2"], "no merge_key: clobber as before")


if __name__ == "__main__":
    unittest.main()
