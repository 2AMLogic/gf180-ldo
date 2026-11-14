"""Deck-template rendering and the netlist-freshness preflight.

Two pieces of bench boilerplate that every Python driver under ``sim/`` needs
and that used to be copied per bench (issue #592, the same consolidation shape
as #157's fatal-sentinel regex, #203's ``parse_row_fields`` and #489's
``run_curve``).

**The ``@TOKEN@`` renderer.** A ``*.spice.in`` template is a deck with
``@UPPER_CASE@`` holes in it; the driver fills them from a substitution map.
The load-bearing half is not the substitution, it is the *guard*: a hole the
driver forgot to fill reaches ngspice as literal text, which is a silent
evidence defect rather than a crash. Eight hand-written copies of that guard
had drifted into three different strengths -- ``@([A-Z0-9_]+)@`` in the four
file-template renderers, ``@[A-Z_]+@`` in two ``klt_run.py`` drivers and
``@[A-Z]+@`` in the other two -- so a first token containing a digit (e.g.
``@RLOAD_OHM@``, ``@DC_SEED@``) added to either of the narrowest two decks
would have passed unsubstituted. Worse, the four ``klt_run.py`` copies were
``assert`` statements, which vanish under ``python -O``. :data:`TOKEN_RE` here
is the strictest of the three and :func:`render` raises rather than asserts,
so there is now one guard at one strength that cannot be optimized away.

Note that a bare ``@`` survives rendering on purpose: ngspice's own
``alter @Vinj[acmag] = 1`` syntax uses one, and it is not an ``@TOKEN@``.

**The netlist-freshness preflight.** Every driver that simulates the committed
``design/netlist/*.spice`` must first confirm they are current with
``design/*.sch``; :func:`require_fresh_netlists` is that check. Four copies
differed only in message text, and one of them named a single cell
(``design/netlist/ldo_core.spice`` vs ``design/ldo_core.sch``) even though
``design/netlist.py --check`` verifies *every* ``design/*.sch`` cell -- so a
stale sub-cell was reported under the wrong file name.

**The bash benches are deliberately not routed through here.** The three
``run.sh`` drivers substitute with ``sed`` and get their corner sections from
``sim/harness/lib/corner_sections.sh`` (issue #207's equivalent consolidation
on that side); they have their own single implementation already, and shelling
a Python renderer out per PVT point inside their ``xargs -P`` fan-out would
cost a process per point for nothing.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .pdk import REPO_ROOT

#: The one deck-template token spelling: ``@`` + upper case / digits /
#: underscore + ``@``. Strictest of the three patterns this module replaced.
TOKEN_RE = re.compile(r"@([A-Z0-9_]+)@")


def tokens(text: str) -> set[str]:
    """Every ``@TOKEN@`` name appearing in *text*."""
    return set(TOKEN_RE.findall(text))


def require_substituted(text: str, *, source: str = "template") -> str:
    """Return *text* unchanged, or raise if any ``@TOKEN@`` survived in it.

    For drivers that assemble a deck body by other means (repeating an
    instance block, concatenating harness-owned preamble) and only need the
    guard. *source* names the thing being checked in the error message.
    """
    left = tokens(text)
    if left:
        raise SystemExit(f"{source} has unsubstituted tokens: {sorted(left)}")
    return text


def render(text: str, subs: dict[str, str], *, source: str = "template") -> str:
    """Substitute every ``@TOKEN@`` in *text* from *subs*; raise on any miss.

    Single-pass: a substituted *value* that happens to contain ``@TOKEN@``
    text is emitted verbatim, never re-scanned. Keys of *subs* that the
    template does not use are ignored.
    """
    missing = {name for name in tokens(text) if name not in subs}
    if missing:
        raise SystemExit(f"{source} has unsubstituted tokens: {sorted(missing)}")
    return TOKEN_RE.sub(lambda m: str(subs[m.group(1)]), text)


def render_file(path: Path | str, subs: dict[str, str], *,
                source: str = "template") -> str:
    """:func:`render` the template at *path*."""
    return render(Path(path).read_text(), subs, source=source)


def pvt_subs(pdk, corner, temp_c: float, vdd: float, netlist: Path | str) -> dict[str, str]:
    """The PDK/corner/operating-point substitutions every deck template needs.

    ``DESIGN_INCLUDE`` / ``MODEL_LIB`` (where the PDK is), ``LDO_NETLIST``
    (the DUT), the six ``*_CORNER`` model-library sections that make up
    *corner* (see ``harness.corners``), and the ``TEMP_C`` / ``VIN_V`` of this
    PVT point. Bench-specific keys are merged on top by the caller:

        deck.render_file(TEMPLATE, {**deck.pvt_subs(...), "AC_DEC": "400"})

    *corner* is a :class:`harness.corners.Corner`; the drivers that carry a
    corner *name* resolve it with ``resolve_corners([name])[0]`` first.
    """
    mos, res, bjt, diode, moscap, mimcap = corner.sections
    return {
        "DESIGN_INCLUDE": str(pdk.design_include),
        "MODEL_LIB": str(pdk.model_lib),
        "LDO_NETLIST": str(netlist),
        "MOS_CORNER": mos,
        "RES_CORNER": res,
        "BJT_CORNER": bjt,
        "DIODE_CORNER": diode,
        "MOSCAP_CORNER": moscap,
        "MIMCAP_CORNER": mimcap,
        "TEMP_C": f"{temp_c:g}",
        "VIN_V": f"{vdd:g}",
    }


#: Headline of the preflight diagnostic. Worded for *every* ``design/*.sch``
#: cell, because that is what ``design/netlist.py --check`` verifies -- and
#: for the other invariants it enforces (reproducible export, xschem ERC,
#: pinout/port order), any of which fails the same way.
NETLIST_STALE_HEADLINE = (
    "FATAL: design/netlist.py --check failed -- the committed "
    "design/netlist/*.spice are not current with design/*.sch, or an ERC / "
    "pinout invariant is broken:"
)


def require_fresh_netlists(repo_root: Path | str = REPO_ROOT) -> str | None:
    """``None`` when the committed netlists are current, else what to print.

    Runs ``design/netlist.py --check`` and, on failure, returns a complete
    ready-to-print diagnostic (headline + the checker's own output). Drivers
    use it as their first preflight::

        stale = require_fresh_netlists()
        if stale:
            print(stale, file=sys.stderr)
            return 3
    """
    check = subprocess.run(
        [sys.executable, str(Path(repo_root) / "design" / "netlist.py"), "--check"],
        capture_output=True, text=True,
    )
    if check.returncode == 0:
        return None
    return NETLIST_STALE_HEADLINE + "\n" + check.stdout + check.stderr
