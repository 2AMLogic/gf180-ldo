#!/usr/bin/env python3
"""Structural guard: ``spec_from_file_location`` stays inside its allowlist
(issue #706, closing #625's declined step 5).

``load_script`` (``sim/harness/loader.py``) is this repo's one path-loading
idiom: it registers the module in ``sys.modules`` before executing it -- what
lets a script combine ``from __future__ import annotations`` with
``@dataclass`` -- and, since #706, drops that registration again if execution
fails. #625 consolidated 21 open-coded copies of the four-line incantation
into the helper; #706 then measured the count climbing straight back (16 new
open-coded sites landed on ``main`` within days, 9 of them unregistered --
the exact latent defect #625 was about), which is the evidence that nothing
else catches a new copy, and why this guard exists: the idiom may be extended
only inside the helper, never re-open-coded beside it.

The test ``ast``-parses every tracked ``*.py`` in the repo (``git ls-files``,
walking the filesystem instead only when git is unavailable -- issue #716:
a worktree may legally hold an untracked Python tree, e.g. a throwaway
``.venv``, whose vendored calls are not regrowth) -- nothing is imported or
executed, so comments and string literals cannot trip it -- and fails,
naming file and line, on any ``spec_from_file_location`` call outside the
allowlist below, or at an allowlisted path whose call count changed. A file
that is not UTF-8 or not valid Python 3 is reported with a named reason
rather than an unhandled error. The allowlist carries a one-line rationale
per site. Hermetic: no PDK, ngspice, klt or fleet.

    python3 -m unittest sim/tests/test_load_script_sites.py -v
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]

#: Repo-relative paths where a ``spec_from_file_location`` call is still
#: allowed, each with its expected call count and the reason it is not
#: ``load_script``. A new site goes through ``load_script``; it never
#: appends here without a reason a reviewer can check.
ALLOWLIST: dict[str, tuple[int, str]] = {
    "sim/harness/loader.py": (1, "the shared helper itself"),
    "sim/tests/test_loader.py": (
        1, "the unregistered idiom kept as the regression oracle beside "
           "the tests holding load_script's contract"),
    "spec/check_spec_table.py": (
        1, "documented #625 carve-out: runs from spec/, no sim/ on sys.path"),
    # The remaining sites each register the module in sys.modules before
    # executing -- the one thing load_script exists to guarantee is already
    # satisfied there -- and sit under testbench or spec directories that
    # must not put sim/ on sys.path to reach harness.loader: a bench driver
    # is loaded by path and its directory is deliberately not an import
    # root, so binding a bare sibling name or widening sys.path is the
    # hazard #630/#700 rule out (issues #706's per-site survey).
    "sim/soft-start/testbench/handover_t15.py": (
        2, "registers in sys.modules; testbench must not put sim/ on sys.path (#630/#700)"),
    "sim/soft-start/testbench/klt_peak_run.py": (
        1, "registers in sys.modules; testbench must not put sim/ on sys.path (#630/#700)"),
    "sim/loop-stability/testbench/sweep.py": (
        1, "registers in sys.modules; testbench must not put sim/ on sys.path (#630/#700)"),
    "sim/current-limit/testbench/klt_run.py": (
        1, "registers in sys.modules; testbench must not put sim/ on sys.path (#630/#700)"),
    "sim/toolchain-portability/testbench/ab_loop_stability.py": (
        1, "registers in sys.modules; testbench must not put sim/ on sys.path (#630/#700)"),
    "sim/tests/test_ab_loop_stability.py": (
        1, "registers in sys.modules; unique-name load beside its driver test (#630/#700)"),
}

#: Directories that are not source tree (Loom runtime, agent config, git).
SKIP_DIRS = {".loom", ".claude", ".git"}


def spec_load_calls(source: str, filename: str = "<source>") -> list[tuple[str, int]]:
    """``(filename, line)`` of every ``spec_from_file_location`` call.

    Pure syntax over the ``ast``: catches the attribute form
    (``importlib.util.spec_from_file_location(...)``) and the from-import
    form called bare, at any nesting level.
    """
    calls = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) \
                and node.func.attr == "spec_from_file_location":
            calls.append((filename, node.lineno))
        elif isinstance(node.func, ast.Name) \
                and node.func.id == "spec_from_file_location":
            calls.append((filename, node.lineno))
    return calls


def read_calls(path: Path, rel: str) -> tuple[list[tuple[str, int]], str | None]:
    """``spec_load_calls`` of *path*, or ``([], problem)`` naming why not.

    A file that is not UTF-8 or not valid Python 3 cannot be ast-walked;
    the guard reports it in its own ``file``/``file:line`` message style
    with the named reason instead of letting ``UnicodeDecodeError`` /
    ``SyntaxError`` escape the test body as an unhandled ERROR (#716).
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [], (f"{rel}: cannot be read as UTF-8 "
                    f"({type(exc).__name__}) -- guard cannot check it")
    try:
        return spec_load_calls(source, rel), None
    except SyntaxError as exc:
        return [], (f"{rel}:{exc.lineno}: not valid Python 3 "
                    f"({exc.msg}) -- guard cannot check it")


def _tracked_py_files(repo: Path) -> list[Path] | None:
    """Git-tracked ``*.py`` under *repo*, or ``None`` if git cannot answer.

    ``git ls-files`` reads the index, so a file is visible to the guard
    the moment it is staged -- exactly the tracked-source statement the
    guard wants to make -- while a vendored tree that merely sits inside
    the worktree (a throwaway ``.venv`` is a sanctioned workflow) never
    enters the index and so is invisible (#716).
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--", "*.py"],
            check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [repo / os.fsdecode(entry)
            for entry in out.split(b"\0") if entry]


def repo_py_files(repo: Path) -> list[Path]:
    """Every ``*.py`` the guard parses, sorted.

    Tracked content when git can answer; a filesystem walk when it cannot.
    Either way ``SKIP_DIRS`` stay out: tracked or not, they are Loom
    runtime / agent config / git plumbing, not this repo's source.
    """
    tracked = _tracked_py_files(repo)
    candidates = tracked if tracked is not None else repo.rglob("*.py")
    return sorted(
        p for p in candidates
        if not (set(p.relative_to(repo).parts) & SKIP_DIRS))


def tree_problems(repo: Path) -> list[str]:
    """Guard failures for every candidate file under *repo*, each in the
    guard's ``file:line`` message style."""
    problems = []
    for path in repo_py_files(repo):
        rel = path.relative_to(repo).as_posix()
        calls, problem = read_calls(path, rel)
        if problem is not None:
            problems.append(problem)
            continue
        if rel in ALLOWLIST:
            limit, _ = ALLOWLIST[rel]
            if len(calls) != limit:
                where = ", ".join(str(line) for _, line in calls) or "none"
                problems.append(
                    f"{rel}: {len(calls)} spec_from_file_location call(s) "
                    f"(line {where}), allowlist expects {limit} -- if a "
                    "site moved or grew, route it through load_script "
                    "rather than editing the allowlist to fit")
        else:
            problems.extend(
                f"{f}:{line}: open-coded spec_from_file_location -- use "
                "load_script (sim/harness/loader.py; issues #625/#706)"
                for f, line in calls)
    return problems


class LoadScriptSites(unittest.TestCase):
    def test_allowlist_matches_the_tree(self):
        """Every call sits at an allowlisted path, with the expected count."""
        candidates = [p.relative_to(REPO).as_posix()
                      for p in repo_py_files(REPO)]
        self.assertIn("sim/harness/loader.py", candidates,
                      "candidate enumeration lost tracked source -- the "
                      "tree test would pass vacuously")
        problems = tree_problems(REPO)
        self.assertEqual(problems, [], "spec_from_file_location outside the "
                         "allowlist:\n" + "\n".join(problems))

    def test_allowlist_is_live_and_exact(self):
        """No stale entry: every allowlisted file exists and really carries
        its expected calls -- otherwise the allowlist rots into a rubber
        stamp."""
        missing = [rel for rel in ALLOWLIST if not (REPO / rel).is_file()]
        self.assertEqual(missing, [], "allowlisted files no longer present")
        for rel, (limit, _) in ALLOWLIST.items():
            calls, problem = read_calls(REPO / rel, rel)
            self.assertIsNone(problem, problem)
            self.assertEqual(
                len(calls), limit,
                f"{rel}: allowlist expects {limit} call(s), file has {len(calls)}")

    def test_guard_flags_a_new_open_coded_site_with_file_and_line(self):
        """The non-vacuity self-check: the predicate fires on the offending
        shape, in the exact file:line form the tree test reports, and stays
        quiet on the routed-through-the-helper shape."""
        bad = (
            "import importlib.util\n"
            "\n"
            "spec = importlib.util.spec_from_file_location(\n"
            '    "one_off_klt_run", HERE / "klt_run.py")\n'
        )
        self.assertEqual(
            spec_load_calls(bad, "sim/tests/test_one_off.py"),
            [("sim/tests/test_one_off.py", 3)])
        bare = (
            "from importlib.util import spec_from_file_location\n"
            "spec = spec_from_file_location('one_off', HERE / 'x.py')\n"
        )
        self.assertEqual(
            spec_load_calls(bare, "sim/tests/test_one_off.py"),
            [("sim/tests/test_one_off.py", 2)])
        good = "from harness.loader import load_script\nmod = load_script('x', p)\n"
        self.assertEqual(spec_load_calls(good, "sim/tests/test_one_off.py"), [])

    def test_string_literals_and_comments_are_not_calls(self):
        """The grep the survey ran sees this file's own docstring; the ast
        must not."""
        prose = (
            '"""Never write spec_from_file_location open-coded.\n'
            '    # spec_from_file_location in a comment, too.\n'
            '    use = "spec_from_file_location"\n'
            '"""\n'
        )
        self.assertEqual(spec_load_calls(prose, "prose.py"), [])

    def test_tracked_source_only_and_planted_sites_still_flagged(self):
        """The #716 contract end to end on a scratch git repo: a staged
        open-coded site is flagged file:line, a staged unparseable file is
        reported with a named reason, and an untracked vendored tree -- the
        ``.venv`` workflow the host instructions sanction -- is invisible
        to the guard."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "staged_probe.py").write_text(
                "import importlib.util\n"
                "spec = importlib.util.spec_from_file_location(\n"
                '    "probe", HERE / "probe.py")\n', encoding="utf-8")
            (repo / "staged_unparseable.py").write_text(
                "def (:\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repo), "add", "staged_probe.py",
                 "staged_unparseable.py"], check=True)
            vendored = repo / ".venv" / "lib" / "site-packages"
            vendored.mkdir(parents=True)
            (vendored / "vendored.py").write_text(
                "import importlib.util\n"
                "spec = importlib.util.spec_from_file_location(\n"
                '    "vend", HERE / "vend.py")\n', encoding="utf-8")
            problems = tree_problems(repo)
            self.assertEqual(len(problems), 2, problems)
            self.assertEqual(
                problems[0],
                "staged_probe.py:2: open-coded spec_from_file_location "
                "-- use load_script (sim/harness/loader.py; issues "
                "#625/#706)", problems)
            self.assertTrue(problems[1].startswith(
                "staged_unparseable.py:1: not valid Python 3"), problems)

    def test_falls_back_to_the_filesystem_walk_without_git(self):
        """git unavailable => the pre-#716 rglob walk, same SKIP_DIRS."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "walked.py").write_text("", encoding="utf-8")
            runtime = repo / ".loom"
            runtime.mkdir()
            (runtime / "runtime.py").write_text("", encoding="utf-8")
            with mock.patch.object(sys.modules[__name__],
                                   "_tracked_py_files", return_value=None):
                walked = [p.relative_to(repo).as_posix()
                          for p in repo_py_files(repo)]
            self.assertEqual(walked, ["walked.py"])

    def test_unparseable_file_is_reported_not_raised(self):
        """Per-file read/parse failures surface in the guard's own message
        style (file, named reason) -- never an unhandled ERROR out of the
        test body."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_syntax = root / "bad_syntax.py"
            bad_syntax.write_text("def (:\n", encoding="utf-8")
            calls, problem = read_calls(bad_syntax, "bad_syntax.py")
            self.assertEqual(calls, [])
            self.assertTrue(problem.startswith(
                "bad_syntax.py:1: not valid Python 3"), problem)
            bad_bytes = root / "bad_bytes.py"
            bad_bytes.write_bytes(b"\x80\x81\xff not utf-8")
            calls, problem = read_calls(bad_bytes, "bad_bytes.py")
            self.assertEqual(calls, [])
            self.assertTrue(problem.startswith(
                "bad_bytes.py: cannot be read as UTF-8"), problem)


if __name__ == "__main__":
    unittest.main()
