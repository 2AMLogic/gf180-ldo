#!/usr/bin/env python3
"""Pin the ratified README spec table (Parameter | Target | Stretch).

    python3 spec/check_spec_table.py --check                     # current tree vs lock
    python3 spec/check_spec_table.py --check --base origin/main  # + authorization diff
    python3 spec/check_spec_table.py --write                     # bootstrap / no-op regen
    python3 spec/check_spec_table.py --write --base origin/main --dr DR-0037

CLAUDE.md says agents do not relax the ratified spec; this makes a silent edit
of a table row fail CI (issue #397). The lock `spec/spec-table-lock.json`
(schema_version 1) holds, per normalized Parameter, the normalized Target and
Stretch cells and their sha256, plus an append-only `amendments` ledger of
`{row, before, after, dr}` transitions (hashes, null for absence).

What this proves, and what it does not. `--check --base <ref>` reads the
README, lock and decision-record set at `git merge-base <ref> HEAD` and
compares them with the checked-out tree. Every changed/added/removed row must
have a freshly appended, exactly matching amendment citing a decision record
that is structurally eligible: (1) a DR number absent at base and added now
with a proposed or ratified Status, or (2) a DR that was `proposed` at base
(same file name) and is `ratified` now with a changed Status block. That is a
structural audit trail. It is NOT proof of operator approval (a proposed
record is eligible because approval can happen on the same PR) and NOT proof
the DR semantically authorizes the named rows; reviewers still check that.

Row identity is the Parameter text with whitespace trimmed/collapsed; cells
are likewise normalized (case, Markdown, units, punctuation preserved), so
whitespace-only edits and row reordering pass. A rename is a removal plus an
addition. Only the table is locked; the ratified notes below it are out of
scope for this first guard.

Any Git failure (missing ref, unreadable object) or malformed input fails; it
never falls back to a current-tree check. Stdlib only; no PDK, no network.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent
README = "README.md"
LOCK = "spec/spec-table-lock.json"
DR_DIR = "spec/decision-records"
SCHEMA_VERSION = 1

_bi_spec = importlib.util.spec_from_file_location(
    "dr_build_index", HERE / "decision-records" / "build_index.py"
)
build_index = importlib.util.module_from_spec(_bi_spec)
_bi_spec.loader.exec_module(build_index)


class CheckError(Exception):
    pass


# ---------------------------------------------------------------------------
# Table parsing / hashing
# ---------------------------------------------------------------------------

def norm(cell: str) -> str:
    return " ".join(cell.split())


def row_hash(target: str, stretch: str) -> str:
    blob = json.dumps(
        [target, stretch], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|") and len(s) >= 2):
        raise CheckError("malformed spec-table row: %r" % line[:60])
    return [c for c in re.split(r"(?<!\\)\|", s[1:-1])]


def parse_table(text: str) -> dict[str, tuple[str, str]]:
    """Strict parse of the Parameter/Target/Stretch table in README text."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.fullmatch(r"\|\s*Parameter\s*\|\s*Target\s*\|\s*Stretch\s*\|\s*", line):
            start = i
            break
    if start is None:
        raise CheckError("spec table (| Parameter | Target | Stretch |) not found")
    if start + 1 >= len(lines) or not re.fullmatch(r"\|[-\s|:]+\|\s*", lines[start + 1]):
        raise CheckError("spec table has no separator row")
    rows: dict[str, tuple[str, str]] = {}
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        cells = [norm(c) for c in _split_row(line)]
        if len(cells) != 3 or not all(cells):
            raise CheckError("malformed spec-table row (need 3 non-empty cells): %r" % line[:60])
        name, target, stretch = cells
        if name in rows:
            raise CheckError("duplicate spec-table Parameter: %r" % name)
        rows[name] = (target, stretch)
    if not rows:
        raise CheckError("spec table has no rows")
    return rows


def table_hashes(table: dict[str, tuple[str, str]]) -> dict[str, str]:
    return {k: row_hash(*v) for k, v in table.items()}


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
DR_RE = re.compile(r"^DR-(\d{4})$")


def render_lock(table: dict[str, tuple[str, str]], amendments: list[dict]) -> str:
    obj = {
        "schema_version": SCHEMA_VERSION,
        "rows": {
            k: {"target": v[0], "stretch": v[1], "hash": row_hash(*v)}
            for k, v in table.items()
        },
        "amendments": amendments,
    }
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def parse_lock(text: str, label: str = "lock") -> dict:
    try:
        obj = json.loads(text)
    except ValueError as exc:
        raise CheckError("%s is not valid JSON: %s" % (label, exc))
    if not isinstance(obj, dict) or set(obj) != {"schema_version", "rows", "amendments"}:
        raise CheckError("%s: top level must have exactly schema_version, rows, amendments" % label)
    if type(obj["schema_version"]) is not int or obj["schema_version"] != SCHEMA_VERSION:
        raise CheckError("%s: unsupported schema_version %r" % (label, obj["schema_version"]))
    if not isinstance(obj["rows"], dict) or not obj["rows"]:
        raise CheckError("%s: rows must be a non-empty object" % label)
    for name, r in obj["rows"].items():
        if (
            not isinstance(r, dict)
            or set(r) != {"target", "stretch", "hash"}
            or not all(isinstance(r[k], str) for k in r)
        ):
            raise CheckError("%s: row %r must be {target, stretch, hash} strings" % (label, name))
        if name != norm(name) or r["target"] != norm(r["target"]) or r["stretch"] != norm(r["stretch"]):
            raise CheckError("%s: row %r is not normalized" % (label, name))
        if r["hash"] != row_hash(r["target"], r["stretch"]):
            raise CheckError("%s: row %r hash does not match its values" % (label, name))
    if not isinstance(obj["amendments"], list):
        raise CheckError("%s: amendments must be an array" % label)
    for a in obj["amendments"]:
        if not isinstance(a, dict) or set(a) != {"row", "before", "after", "dr"}:
            raise CheckError("%s: each amendment must be exactly {row, before, after, dr}" % label)
        if not isinstance(a["row"], str) or not a["row"]:
            raise CheckError("%s: amendment row must be a string" % label)
        for k in ("before", "after"):
            if a[k] is not None and not (isinstance(a[k], str) and HASH_RE.match(a[k])):
                raise CheckError("%s: amendment %s must be a sha256 hex or null" % (label, k))
        if a["before"] == a["after"]:
            raise CheckError("%s: amendment for %r is a no-op" % (label, a["row"]))
        if not (isinstance(a["dr"], str) and DR_RE.match(a["dr"])):
            raise CheckError("%s: amendment dr must look like DR-NNNN" % label)
    _check_chains(obj, label)
    return obj


def _check_chains(lock: dict, label: str) -> None:
    last: dict[str, str | None] = {}
    seen: set[str] = set()
    for a in lock["amendments"]:
        r = a["row"]
        if r in seen and last[r] != a["before"]:
            raise CheckError("%s: amendment chain for %r is not contiguous" % (label, r))
        seen.add(r)
        last[r] = a["after"]
    for r, after in last.items():
        cur = lock["rows"].get(r)
        want = cur["hash"] if cur else None
        if want != after:
            raise CheckError("%s: ledger for %r ends at a state that is not the locked row" % (label, r))


# ---------------------------------------------------------------------------
# Git / filesystem access
# ---------------------------------------------------------------------------

def git(root: Path, *args: str) -> str:
    try:
        p = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
    except OSError as exc:
        raise CheckError("cannot run git: %s" % exc)
    if p.returncode != 0:
        raise CheckError("git %s failed: %s" % (" ".join(args), p.stderr.strip()))
    return p.stdout


def git_path_exists(root: Path, commit: str, path: str) -> bool:
    return bool(git(root, "ls-tree", "--name-only", commit, "--", path).strip())


def read_candidate(root: Path) -> tuple[str, str | None, dict[int, dict[str, str]]]:
    readme = root / README
    if not readme.is_file():
        raise CheckError("%s not found" % README)
    lock = root / LOCK
    lock_text = lock.read_text(encoding="utf-8") if lock.is_file() else None
    drs: dict[int, dict[str, str]] = {}
    for p in sorted((root / DR_DIR).glob("DR-[0-9][0-9][0-9][0-9]-*.md")):
        drs.setdefault(int(p.name[3:7]), {})[p.name] = p.read_text(encoding="utf-8")
    return readme.read_text(encoding="utf-8"), lock_text, drs


def read_base(root: Path, ref: str) -> dict:
    commit = git(root, "merge-base", ref, "HEAD").strip()
    if not commit:
        raise CheckError("no merge-base between %s and HEAD" % ref)
    if not git_path_exists(root, commit, README):
        raise CheckError("%s missing at base %s" % (README, commit[:12]))
    readme = git(root, "show", "%s:%s" % (commit, README))
    lock_text = git(root, "show", "%s:%s" % (commit, LOCK)) if git_path_exists(root, commit, LOCK) else None
    drs: dict[int, dict[str, str]] = {}
    listing = git(root, "ls-tree", "--name-only", commit, "%s/" % DR_DIR)
    for path in listing.splitlines():
        name = path.rsplit("/", 1)[-1]
        if re.fullmatch(r"DR-\d{4}-.*\.md", name):
            drs.setdefault(int(name[3:7]), {})[name] = git(root, "show", "%s:%s" % (commit, path))
    return {"commit": commit, "readme": readme, "lock": lock_text, "drs": drs}


# ---------------------------------------------------------------------------
# Decision-record eligibility
# ---------------------------------------------------------------------------

def _status(number: int, text: str) -> tuple[str, str]:
    block = build_index.status_block(text)
    try:
        status, _ = build_index.classify(number, block)
    except build_index.ClassifyError as exc:
        raise CheckError(str(exc))
    return status, block or ""


def _unique(drs: dict[int, dict[str, str]], number: int, where: str) -> tuple[str, str] | None:
    files = drs.get(number)
    if not files:
        return None
    if len(files) > 1:
        raise CheckError("DR-%04d is ambiguous %s: %s" % (number, where, ", ".join(sorted(files))))
    return next(iter(files.items()))


def check_dr_eligible(dr: str, base_drs: dict, cand_drs: dict) -> str:
    """Return 'new' or 'ratified-now' if ``dr`` is fresh authorization."""
    number = int(DR_RE.match(dr).group(1))
    cand = _unique(cand_drs, number, "in the candidate tree")
    if cand is None:
        raise CheckError("%s cited but no DR-%04d-*.md exists in the candidate tree" % (dr, number))
    base = _unique(base_drs, number, "at base")
    cname, ctext = cand
    cstatus, cblock = _status(number, ctext)
    if base is None:
        if cstatus not in ("proposed", "ratified"):
            raise CheckError("%s is new but its status is %r (need proposed or ratified)" % (dr, cstatus))
        return "new"
    bname, btext = base
    bstatus, bblock = _status(number, btext)
    if bname != cname:
        raise CheckError("%s was renamed (%s -> %s); not fresh authorization" % (dr, bname, cname))
    if bstatus == "proposed" and cstatus == "ratified" and bblock != cblock:
        return "ratified-now"
    raise CheckError(
        "%s existed at base as %r and is %r now; only a new DR or a proposed->ratified "
        "Status change is fresh authorization" % (dr, bstatus, cstatus)
    )


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def current_tree_check(readme: str, lock_text: str | None) -> tuple[dict, dict]:
    table = parse_table(readme)
    if lock_text is None:
        raise CheckError("%s is missing" % LOCK)
    lock = parse_lock(lock_text, LOCK)
    want = table_hashes(table)
    have = {k: v["hash"] for k, v in lock["rows"].items()}
    for k in sorted(set(want) | set(have)):
        if want.get(k) != have.get(k):
            kind = "added to README" if k not in have else "removed from README" if k not in want else "changed"
            raise CheckError("spec row %r %s but %s does not match (update via a decision record; see TEMPLATE.md)" % (k, kind, LOCK))
    for k, v in lock["rows"].items():
        if (v["target"], v["stretch"]) != table[k]:
            raise CheckError("lock row %r values disagree with README" % k)
    return table, lock


def transitions(base_table: dict, cand_table: dict) -> list[tuple[str, str | None, str | None]]:
    bh, ch = table_hashes(base_table), table_hashes(cand_table)
    return [
        (k, bh.get(k), ch.get(k))
        for k in sorted(set(bh) | set(ch))
        if bh.get(k) != ch.get(k)
    ]


def base_check(base: dict, cand_table: dict, cand_lock: dict, cand_drs: dict) -> list:
    try:
        base_table = parse_table(base["readme"])
    except CheckError as exc:
        raise CheckError("base README: %s" % exc)
    trans = transitions(base_table, cand_table)
    if base["lock"] is None:
        if trans:
            raise CheckError(
                "base has no lock: bootstrap requires an unchanged spec table, but %d row(s) differ (%s)"
                % (len(trans), ", ".join(repr(t[0]) for t in trans))
            )
        if cand_lock["amendments"]:
            raise CheckError("bootstrap lock must have an empty amendments ledger")
        return []
    base_lock = parse_lock(base["lock"], "base " + LOCK)
    ba, ca = base_lock["amendments"], cand_lock["amendments"]
    if ca[: len(ba)] != ba or len(ca) < len(ba):
        raise CheckError("existing amendment history was rewritten, reordered or removed")
    new = ca[len(ba):]
    expected = list(trans)
    for a in new:
        key = (a["row"], a["before"], a["after"])
        if key not in expected:
            raise CheckError(
                "amendment for %r (%s -> %s) is duplicate, unrelated or contradicts the table change"
                % (a["row"], a["before"] and a["before"][:8], a["after"] and a["after"][:8])
            )
        expected.remove(key)
        check_dr_eligible(a["dr"], base["drs"], cand_drs)
    if expected:
        raise CheckError(
            "no fresh amendment for changed/added/removed row(s): %s"
            % ", ".join(repr(t[0]) for t in expected)
        )
    return new


def run_check(root: Path, base_ref: str | None) -> str:
    readme, lock_text, cand_drs = read_candidate(root)
    table, lock = current_tree_check(readme, lock_text)
    if base_ref is None:
        return "ok: %d spec rows match %s (current tree only)" % (len(table), LOCK)
    base = read_base(root, base_ref)
    new = base_check(base, table, lock, cand_drs)
    return "ok: %d spec rows, %d new amendment(s) vs merge-base %s" % (len(table), len(new), base["commit"][:12])


def run_write(root: Path, base_ref: str | None, dr: str | None) -> str:
    readme, lock_text, cand_drs = read_candidate(root)
    table = parse_table(readme)
    path = root / LOCK
    if base_ref is None:
        if dr is not None:
            raise CheckError("--dr requires --base")
        if lock_text is None:
            text = render_lock(table, [])
        else:
            old = parse_lock(lock_text, LOCK)
            if {k: v["hash"] for k, v in old["rows"].items()} != table_hashes(table):
                raise CheckError("table differs from lock: amending requires --base <ref> --dr DR-NNNN")
            text = render_lock(table, old["amendments"])
    else:
        base = read_base(root, base_ref)
        base_table = parse_table(base["readme"])
        trans = transitions(base_table, table)
        base_amend = parse_lock(base["lock"], "base " + LOCK)["amendments"] if base["lock"] else []
        if base["lock"] is None:
            if trans:
                raise CheckError("base has no lock and the table changed; bootstrap cannot carry amendments")
            if dr is not None:
                raise CheckError("--dr given but base has no lock; bootstrap cannot carry amendments")
            text = render_lock(table, [])
        else:
            if trans and dr is None:
                raise CheckError("table changed vs base: pass --dr DR-NNNN naming the authorizing record")
            if dr is not None:
                if not DR_RE.match(dr):
                    raise CheckError("--dr must look like DR-NNNN")
                if not trans:
                    raise CheckError("--dr given but no row differs from base")
                check_dr_eligible(dr, base["drs"], cand_drs)
            amend = base_amend + [{"row": k, "before": b, "after": a, "dr": dr} for k, b, a in trans]
            text = render_lock(table, amend)
        try:
            parse_lock(text, "generated lock")
            current_tree_check(readme, text)
            base_check(base, table, json.loads(text), cand_drs)
        except CheckError as exc:
            raise CheckError("refusing to write: %s" % exc)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return "unchanged: %s" % LOCK
    path.write_text(text, encoding="utf-8")
    return "wrote %s" % LOCK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate README against the lock")
    mode.add_argument("--write", action="store_true", help="generate/update the lock")
    ap.add_argument("--base", help="git ref; compared at its merge-base with HEAD")
    ap.add_argument("--dr", help="DR-NNNN authorizing a --write amendment")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        if args.check:
            if args.dr:
                raise CheckError("--dr is only for --write")
            msg = run_check(args.root, args.base)
        else:
            msg = run_write(args.root, args.base, args.dr)
    except CheckError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
