#!/usr/bin/env bash
# Re-grade this block's T1 state from signoff/block-manifest.json and fail if
# the committed verdict of record has rotted (issue #270).
#
# Usage:
#   bash signoff/check.sh            # verify: re-run and diff against the committed record
#   bash signoff/check.sh --write    # regenerate signoff/records/t1-tier-report.json
#
# What this guards, in order
# --------------------------
# 1. **Every pinned content_hash still matches the artifact on disk.** A
#    manifest entry that pins a hash can only prove freshness if that hash is
#    the hash of something actually committed here. `klt signoff` compares the
#    manifest's pin against the *envelope's own* `provenance.input.content_hash`
#    -- it never opens the underlying artifact, so two hand-written files
#    agreeing with each other proves nothing on its own. This step closes that
#    loop: for every evidence envelope under signoff/evidence/ that names a
#    `source`, the sha256 of that source file must equal the hash the envelope
#    pins. Change sim/CHARACTERIZATION.md without re-pinning and this fails.
# 2. **`klt signoff --manifest` runs clean.** Exit 0 (T1 reached) or 3 (ran
#    fine, not yet T1) are both "ran clean"; 1 and 2 are a broken manifest or a
#    tier doc this klt cannot parse, and fail.
# 3. **The committed record matches the fresh run.** signoff/records/t1-tier-report.json
#    is the verdict of record cited by the gap-to-T1 tracker (issue #79); if it
#    no longer matches what the tool says today, it is stale prose again and the
#    whole point of the manifest is lost.
#
# Why klt is pinned to a git revision here
# ----------------------------------------
# T1 item 11 ("Power delivery (structural)", klayout-tools#2025) landed
# 2026-09-19, *after* the klayout-tools v0.5.0 PyPI release -- a `pip install
# klayout-tools` today parses a ten-item checklist and would render no item-11
# row at all. `klt signoff` parses the item list out of
# klayout-tools' own docs/design-evidence-tiers.md, so the tool version decides
# which checklist this block is graded against, and an unpinned install would
# make the committed record irreproducible. KLT_REV below is that pin. Bumping
# it is a real change to the yardstick: expect signoff/records/t1-tier-report.json
# to move in the same commit, and re-read signoff/README.md's item notes
# against any item the bump adds or rewords.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# klayout-tools revision this block is graded against. See the header above
# before changing it.
KLT_REV="d5893304afc2bfa6228609740e83292c44b854f3"
KLT_SPEC="git+https://github.com/2AMLogic/klayout-tools@${KLT_REV}"

MANIFEST="signoff/block-manifest.json"
RECORD="signoff/records/t1-tier-report.json"

WRITE=0
if [[ "${1:-}" == "--write" ]]; then
  WRITE=1
elif [[ $# -gt 0 ]]; then
  echo "usage: bash signoff/check.sh [--write]" >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# 1. Pinned hashes vs. the artifacts they claim to cover.
# ---------------------------------------------------------------------------
python3 - <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path.cwd()
failures = []
checked = 0

for envelope_path in sorted(root.glob("signoff/evidence/*.json")):
    envelope = json.loads(envelope_path.read_text())
    source = envelope.get("source")
    pinned = (envelope.get("provenance") or {}).get("input", {}).get("content_hash")
    if not source:
        continue
    if not pinned:
        failures.append(
            f"{envelope_path}: names source {source!r} but pins no "
            f"provenance.input.content_hash -- an unpinned citation's freshness "
            f"cannot be verified at all"
        )
        continue
    artifact = root / source
    if not artifact.is_file():
        failures.append(f"{envelope_path}: source {source!r} does not exist")
        continue
    actual = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
    checked += 1
    if actual != pinned:
        failures.append(
            f"{envelope_path}: pins {pinned} for {source!r}, but that file "
            f"hashes to {actual} today -- the cited evidence moved and the "
            f"citation was not re-pinned"
        )

# Whatever the manifest pins per item must equal what that item's envelope pins,
# so a re-pin that touches only one of the two files is caught rather than
# silently rendering the item stale_evidence.
manifest = json.loads((root / "signoff/block-manifest.json").read_text())
for item, entry in sorted((manifest.get("evidence") or {}).items()):
    entries = entry if isinstance(entry, list) else [entry]
    for part in entries:
        if not isinstance(part, dict):
            continue
        pinned = part.get("content_hash")
        file_ = part.get("file")
        if not pinned or not file_:
            continue
        envelope = json.loads((root / file_).read_text())
        own = (envelope.get("provenance") or {}).get("input", {}).get("content_hash")
        if own != pinned:
            failures.append(
                f"manifest item {item}: pins {pinned} for {file_!r}, but that "
                f"envelope's own provenance.input.content_hash is {own}"
            )

if failures:
    print("signoff/check.sh: pinned-hash verification FAILED", file=sys.stderr)
    for line in failures:
        print(f"  - {line}", file=sys.stderr)
    sys.exit(1)

print(f"signoff/check.sh: {checked} pinned citation(s) match their artifact")
PY

# ---------------------------------------------------------------------------
# 2 + 3. Re-grade, and compare against the committed verdict of record.
# ---------------------------------------------------------------------------
FRESH="$(mktemp)"
trap 'rm -f "$FRESH"' EXIT

set +e
uvx --from "$KLT_SPEC" klt signoff --manifest "$MANIFEST" --format json >"$FRESH"
rc=$?
set -e

# 0 = every T1 item met; 3 = ran fine, not yet T1. Both are a clean run of the
# grader. 1/2 mean the manifest or the tier doc could not be read at all.
if [[ "$rc" -ne 0 && "$rc" -ne 3 ]]; then
  echo "signoff/check.sh: klt signoff --manifest failed (exit $rc)" >&2
  cat "$FRESH" >&2
  exit 1
fi

python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$FRESH"

if [[ "$WRITE" -eq 1 ]]; then
  python3 -c '
import json, sys
report = json.load(open(sys.argv[1]))
with open(sys.argv[2], "w") as fh:
    json.dump(report, fh, indent=2, sort_keys=False)
    fh.write("\n")
' "$FRESH" "$RECORD"
  echo "signoff/check.sh: wrote $RECORD"
  exit 0
fi

python3 - "$FRESH" "$RECORD" <<'PY'
import json
import sys

fresh = json.load(open(sys.argv[1]))
try:
    committed = json.load(open(sys.argv[2]))
except FileNotFoundError:
    print(f"signoff/check.sh: {sys.argv[2]} is missing -- regenerate it with "
          f"'bash signoff/check.sh --write' and commit it", file=sys.stderr)
    sys.exit(1)

if fresh != committed:
    print(
        "signoff/check.sh: the committed T1 verdict of record is stale.\n"
        "  A fresh 'klt signoff --manifest' run no longer matches\n"
        f"  {sys.argv[2]}. That is not a tool bug: either this block's\n"
        "  evidence moved, or the checklist did. Regenerate with\n"
        "    bash signoff/check.sh --write\n"
        "  commit the result, and update signoff/README.md's reading of any\n"
        "  item whose status or reason changed.",
        file=sys.stderr,
    )
    sys.exit(1)

met = fresh.get("t1_met_count")
total = fresh.get("t1_item_count")
print(f"signoff/check.sh: verdict of record is current -- T1 {met}/{total} items met, "
      f"tier={fresh.get('tier')!r}")
PY
