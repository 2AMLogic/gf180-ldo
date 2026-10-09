#!/usr/bin/env python3
"""Tests for spec/check_spec_table.py (issue #397).

    python3 -m unittest discover -s sim/tests -t sim/tests -v

Each case builds a throwaway Git repository holding a tiny README spec table,
a lock and a few decision records, then mutates it. Stdlib only; no PDK,
ngspice or network.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("cst", REPO / "spec" / "check_spec_table.py")
cst = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cst)

TABLE = """# Project

| Parameter | Target | Stretch |
|---|---|---|
| Output | 1.8 V | 1.2 V |
| Load | 0-50 mA | - |
| Area | < 0.1 mm2 | - |

Notes below.
"""


def dr_text(number: int, status: str, extra: str = "") -> str:
    return "# DR-%04d: t\n\n- **Status**: %s\n- **Date**: 2026-01-01\n%s" % (number, status, extra)


class Repo:
    def __init__(self, tmp: Path):
        self.root = tmp
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "user.name", "t")
        (tmp / "spec" / "decision-records").mkdir(parents=True)
        self.write("README.md", TABLE)
        self.write_dr("DR-0001-old.md", dr_text(1, "ratified"))
        self.write_dr("DR-0002-prop.md", dr_text(2, "proposed"))
        self.write_dr("DR-0003-held.md", dr_text(3, "superseded by DR-0001"))

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.root), *a], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, rel, text):
        (self.root / rel).write_text(text, encoding="utf-8")

    def write_dr(self, name, text):
        self.write("spec/decision-records/" + name, text)

    def commit(self, msg="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def run(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cst.main([*args, "--root", str(self.root)])
        return rc, out.getvalue() + err.getvalue()

    def lock(self):
        return json.loads((self.root / cst.LOCK).read_text())

    def set_lock(self, obj):
        self.write(cst.LOCK, json.dumps(obj, indent=2, sort_keys=True) + "\n")

    def bootstrap(self):
        assert self.run("--write")[0] == 0
        self.commit("lock")


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.r = Repo(Path(td.name))
        self.r.commit("init")

    def ok(self, *args):
        rc, out = self.r.run(*args)
        self.assertEqual(rc, 0, out)
        return out

    def bad(self, *args, msg="error"):
        rc, out = self.r.run(*args)
        self.assertEqual(rc, 1, out)
        self.assertIn(msg, out)

    def branch(self):
        self.r.git("checkout", "-q", "-b", "pr")


class ParserTests(unittest.TestCase):
    def test_whitespace_and_reorder_same_hashes(self):
        a = cst.table_hashes(cst.parse_table(TABLE))
        t2 = TABLE.replace("| Load | 0-50 mA | - |", "|  Load  |  0-50   mA |   - |")
        lines = t2.splitlines()
        i = lines.index("| Output | 1.8 V | 1.2 V |")
        lines[i], lines[i + 1] = lines[i + 1], lines[i]
        self.assertEqual(a, cst.table_hashes(cst.parse_table("\n".join(lines))))

    def test_value_change_changes_hash(self):
        a = cst.table_hashes(cst.parse_table(TABLE))
        b = cst.table_hashes(cst.parse_table(TABLE.replace("1.8 V", "1.9 V")))
        self.assertNotEqual(a["Output"], b["Output"])
        self.assertEqual(a["Load"], b["Load"])

    def test_duplicate_malformed_absent(self):
        with self.assertRaises(cst.CheckError):
            cst.parse_table(TABLE.replace("| Area |", "| Load |"))
        with self.assertRaises(cst.CheckError):
            cst.parse_table(TABLE.replace("| Area | < 0.1 mm2 | - |", "| Area | < 0.1 mm2 |"))
        with self.assertRaises(cst.CheckError):
            cst.parse_table(TABLE.replace("| Area | < 0.1 mm2 | - |", "| Area |  | - |"))
        with self.assertRaises(cst.CheckError):
            cst.parse_table("no table here\n")
        with self.assertRaises(cst.CheckError):
            cst.parse_table("| Parameter | Target | Stretch |\n|---|---|---|\n\nx\n")

    def test_real_readme_parses_and_matches_report_parser(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        table = cst.parse_table(text)
        self.assertGreater(len(table), 5)
        lock = cst.parse_lock((REPO / cst.LOCK).read_text(encoding="utf-8"))
        self.assertEqual({k: v["hash"] for k, v in lock["rows"].items()},
                         cst.table_hashes(table))


class CurrentTreeTests(Base):
    def test_bootstrap_and_deterministic_write(self):
        self.r.bootstrap()
        before = (self.r.root / cst.LOCK).read_bytes()
        self.assertIn("unchanged", self.ok("--write"))
        self.assertEqual(before, (self.r.root / cst.LOCK).read_bytes())
        self.ok("--check")

    def test_missing_lock_fails(self):
        self.bad("--check", msg="missing")

    def test_stale_lock_fails(self):
        self.r.bootstrap()
        self.r.write("README.md", TABLE.replace("1.8 V", "1.7 V"))
        self.bad("--check", msg="Output")

    def test_invalid_lock_schema_fails(self):
        self.r.bootstrap()
        lock = self.r.lock()
        lock["schema_version"] = 2
        self.r.set_lock(lock)
        self.bad("--check", msg="schema_version")

    def test_lock_hash_tamper_fails(self):
        self.r.bootstrap()
        lock = self.r.lock()
        lock["rows"]["Output"]["target"] = "1.9 V"
        self.r.set_lock(lock)
        self.bad("--check", msg="hash")

    def test_whitespace_and_reorder_pass(self):
        self.r.bootstrap()
        self.r.write("README.md", TABLE.replace("| Load | 0-50 mA | - |", "| Load |   0-50 mA | -   |"))
        self.ok("--check")
        self.ok("--write")


class BaseTests(Base):
    def edit_target(self):
        self.r.write("README.md", TABLE.replace("1.8 V", "1.9 V"))

    def test_unchanged_passes(self):
        self.r.bootstrap()
        self.branch()
        self.ok("--check", "--base", "main")

    def test_missing_ref_fails_closed(self):
        self.r.bootstrap()
        self.bad("--check", "--base", "nope", msg="git")

    def test_table_and_lock_edit_with_old_dr_fails(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        self.bad("--write", "--base", "main", "--dr", "DR-0001", msg="error")
        # hand-edited lock citing an old ratified record
        self.edit_target()
        t = cst.parse_table((self.r.root / "README.md").read_text())
        bh = cst.table_hashes(cst.parse_table(TABLE))["Output"]
        am = [{"row": "Output", "before": bh, "after": cst.row_hash(*t["Output"]), "dr": "DR-0001"}]
        self.r.write(cst.LOCK, cst.render_lock(t, am))
        self.bad("--check", "--base", "main", msg="DR-0001")

    def test_new_dr_proposed_and_ratified_qualify(self):
        for status in ("proposed", "ratified 2026-10-01"):
            with self.subTest(status=status):
                self.setUp()
                self.r.bootstrap()
                self.branch()
                self.edit_target()
                self.r.write_dr("DR-0010-new.md", dr_text(10, status))
                self.ok("--write", "--base", "main", "--dr", "DR-0010")
                self.ok("--check", "--base", "main")
                self.assertEqual(len(self.r.lock()["amendments"]), 1)

    def test_new_dr_held_or_superseded_fails(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        self.r.write_dr("DR-0010-new.md", dr_text(10, "superseded by DR-0001"))
        self.bad("--write", "--base", "main", "--dr", "DR-0010", msg="error")

    def test_proposed_to_ratified_qualifies(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        self.r.write_dr("DR-0002-prop.md", dr_text(2, "ratified 2026-10-01"))
        self.ok("--write", "--base", "main", "--dr", "DR-0002")
        self.ok("--check", "--base", "main")

    def test_unchanged_proposed_fails(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        self.bad("--write", "--base", "main", "--dr", "DR-0002", msg="error")

    def test_content_edit_without_status_change_fails(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        self.r.write_dr("DR-0002-prop.md", dr_text(2, "proposed", "more\n"))
        self.bad("--write", "--base", "main", "--dr", "DR-0002", msg="error")

    def test_renamed_dr_fails(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        self.r.git("mv", "spec/decision-records/DR-0002-prop.md", "spec/decision-records/DR-0002-other.md")
        self.r.write_dr("DR-0002-other.md", dr_text(2, "ratified"))
        self.bad("--write", "--base", "main", "--dr", "DR-0002", msg="renamed")

    def test_already_ratified_or_superseded_fails(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        for dr in ("DR-0001", "DR-0003"):
            self.bad("--write", "--base", "main", "--dr", dr, msg="error")

    def test_missing_and_ambiguous_dr_fail(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        self.bad("--write", "--base", "main", "--dr", "DR-0099", msg="error")
        self.r.write_dr("DR-0010-a.md", dr_text(10, "proposed"))
        self.r.write_dr("DR-0010-b.md", dr_text(10, "proposed"))
        self.bad("--write", "--base", "main", "--dr", "DR-0010", msg="ambiguous")

    def test_write_requires_dr(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        self.bad("--write", "--base", "main", msg="--dr")
        self.bad("--write", msg="--base")

    def test_added_removed_renamed_rows(self):
        self.r.bootstrap()
        self.branch()
        self.r.write_dr("DR-0010-new.md", dr_text(10, "proposed"))
        self.r.write("README.md", TABLE.replace("| Area | < 0.1 mm2 | - |", "| Area | < 0.1 mm2 | - |\n| Extra | 1 | - |"))
        self.ok("--write", "--base", "main", "--dr", "DR-0010")
        self.ok("--check", "--base", "main")
        am = self.r.lock()["amendments"]
        self.assertEqual((am[0]["row"], am[0]["before"]), ("Extra", None))
        # removal retains before hash
        self.setUp()
        self.r.bootstrap()
        self.branch()
        self.r.write_dr("DR-0010-new.md", dr_text(10, "proposed"))
        self.r.write("README.md", TABLE.replace("| Area | < 0.1 mm2 | - |\n", ""))
        self.ok("--write", "--base", "main", "--dr", "DR-0010")
        am = self.r.lock()["amendments"]
        self.assertEqual((am[0]["row"], am[0]["after"]), ("Area", None))
        self.assertEqual(am[0]["before"], cst.table_hashes(cst.parse_table(TABLE))["Area"])
        self.ok("--check", "--base", "main")
        # rename = removal + addition (two transitions)
        self.setUp()
        self.r.bootstrap()
        self.branch()
        self.r.write_dr("DR-0010-new.md", dr_text(10, "proposed"))
        self.r.write("README.md", TABLE.replace("| Area |", "| Core area |"))
        self.ok("--write", "--base", "main", "--dr", "DR-0010")
        self.assertEqual(len(self.r.lock()["amendments"]), 2)
        self.ok("--check", "--base", "main")

    def _amended(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        self.r.write("README.md", (self.r.root / "README.md").read_text().replace("0-50 mA", "0-40 mA"))
        self.r.write_dr("DR-0010-new.md", dr_text(10, "proposed"))
        self.ok("--write", "--base", "main", "--dr", "DR-0010")
        return self.r.lock()

    def test_multi_row_one_missing_authorization_fails(self):
        lock = self._amended()
        self.assertEqual(len(lock["amendments"]), 2)
        lock["amendments"].pop()
        self.r.set_lock(lock)
        self.bad("--check", "--base", "main", msg="error")

    def test_duplicate_or_unrelated_transition_fails(self):
        lock = self._amended()
        dup = dict(lock["amendments"][0])
        lock["amendments"].append(dup)
        self.r.set_lock(lock)
        self.bad("--check", "--base", "main", msg="error")

    def test_unrelated_transition_fails(self):
        self.r.bootstrap()
        self.branch()
        self.r.write_dr("DR-0010-new.md", dr_text(10, "proposed"))
        lock = self.r.lock()
        lock["amendments"].append({"row": "Output", "before": "0" * 64, "after": "1" * 64, "dr": "DR-0010"})
        self.r.set_lock(lock)
        self.bad("--check", "--base", "main", msg="error")

    def test_history_rewrite_or_delete_fails(self):
        self._amended()
        self.r.commit("amend")
        self.r.git("checkout", "-q", "-b", "pr2")
        lock = self.r.lock()
        lock["amendments"][0]["dr"] = "DR-0001"
        self.r.set_lock(lock)
        self.bad("--check", "--base", "pr", msg="history")
        lock["amendments"] = []
        self.r.set_lock(lock)
        self.bad("--check", "--base", "pr", msg="error")

    def test_lock_deletion_after_base_lock_fails(self):
        self.r.bootstrap()
        self.branch()
        (self.r.root / cst.LOCK).unlink()
        self.bad("--check", "--base", "main", msg="missing")

    def test_bootstrap_rules(self):
        # base has no lock: bootstrap with unchanged table passes
        self.branch()
        self.ok("--write")
        self.ok("--check", "--base", "main")
        # ... with a changed table fails
        self.r.write("README.md", TABLE.replace("1.8 V", "1.9 V"))
        self.bad("--write", msg="--base")  # refuses to re-lock a changed table
        (self.r.root / cst.LOCK).unlink()
        self.ok("--write")  # fresh bootstrap of the changed table
        self.bad("--check", "--base", "main", msg="bootstrap")
        # ... or a non-empty ledger fails
        self.r.write("README.md", TABLE)
        lock = self.r.lock()
        lock["amendments"] = [{"row": "Output", "before": None, "after": lock["rows"]["Output"]["hash"], "dr": "DR-0002"}]
        self.r.set_lock(lock)
        self.bad("--check", "--base", "main", msg="error")

    def test_diverged_branches_use_merge_base(self):
        self.r.bootstrap()
        self.branch()
        self.r.git("checkout", "-q", "main")
        # main moves on (changes the table with its own lock+DR) after the branch point
        self.r.write("README.md", TABLE.replace("1.8 V", "1.9 V"))
        self.r.write_dr("DR-0010-new.md", dr_text(10, "ratified"))
        self.ok("--write", "--base", "HEAD", "--dr", "DR-0010")
        self.r.commit("main moves")
        self.r.git("checkout", "-q", "pr")
        # branch is unchanged vs its merge-base, so it passes despite main's change
        self.ok("--check", "--base", "main")

    def test_merge_checkout_shape(self):
        self.r.bootstrap()
        self.branch()
        self.edit_target()
        self.r.write_dr("DR-0010-new.md", dr_text(10, "proposed"))
        self.ok("--write", "--base", "main", "--dr", "DR-0010")
        self.r.commit("pr work")
        base_sha = self.r.git("rev-parse", "main")
        self.r.git("checkout", "-q", "main")
        self.r.git("checkout", "-q", "--detach")
        self.r.git("merge", "-q", "--no-ff", "-m", "merge", "pr")
        self.ok("--check", "--base", base_sha)
        self.ok("--check")


if __name__ == "__main__":
    unittest.main()
