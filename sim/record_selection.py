"""The changed-record selector shared by the two record CI gates (issue #854).

sim/check_record_host_paths.py (#365/#413) and sim/check_record_reading.py
(#606) must inspect the same set of added and modified evidence records.
Until #854 each carried its own copy of the three pathspecs and the git
query, and the Reading check's copy carried a comment asking maintainers
to keep it identical -- an agreement with no mechanism behind it. A fourth
record location added to one gate left the other green while it silently
skipped those files, the shape of #413's missed top-level
``layout/records/``. This module is the mechanism: one definition that
both gates (and their regression tests,
``sim/tests/test_check_record_*.py`` and ``sim/tests/test_record_selection.py``)
bind, so they cannot disagree about which files are evidence records.

The selection policy: paths added or modified between ``<base>...HEAD``
under the three record locations -- per-bench sim records, signoff
records, and top-level layout records (#413). Deletions are excluded
(``--diff-filter=AM``): a deleted record is the append-only rule's
problem (``sim/check_append_only.py``), not these gates'. Historical
records outside the diff are never inspected, so append-only evidence is
never rewritten by a check. Raises ``subprocess.CalledProcessError`` on
an unusable base; each gate's CLI turns that into its own exit-2
diagnostic. Stdlib + git only; no PDK, no network.
"""

from __future__ import annotations

import subprocess

# Single source of truth for both CI gates and their regression tests.
PATHSPECS = (
    "sim/*/records/*",
    "signoff/records/*",
    "layout/records/*",
)


def changed_files(base: str) -> list[str]:
    """Return the record paths added or modified in ``base...HEAD``."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD",
         "--", *PATHSPECS],
        check=True, capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if line]
