#!/usr/bin/env python3
"""The feedback divider's `--record` note: the matching as drawn, vs floorplan.md.

Relocated here from `layout/drclvs.py` (issue #649). The generic DRC/LVS
driver's docstring promises that nothing about the stages is test-cell-specific,
and this note is the one thing that broke that promise: the divider's own prose
plus its own arithmetic, 60 lines sitting inside the shared driver -- and,
worse, evaluated at *import* time on every `drclvs` run regardless of cell, so
a failure in either source module below broke every cell's flow.

`drclvs.DIVIDER_SPEC` now registers a loader instead
(`record_notes=lambda: load_script(...).render()`), so this module is loaded by
path through `harness.loader.load_script` and `render()` runs only when
`--record` actually writes a divider record. The note's text and the figures it
derives are unchanged -- byte-identical to the pre-relocation render.

This module is loaded only by `drclvs.py` (and the tests), never under
KLayout's interpreter -- only `plan.py` carries that constraint -- so it may
import freely.
"""

from __future__ import annotations

import sys
from pathlib import Path

_DIVIDER_DIR = Path(__file__).resolve().parent
_LAYOUT_DIR = _DIVIDER_DIR.parent
_REPO_ROOT = _LAYOUT_DIR.parent

# `drclvs.py` happens to insert `sim/` on `sys.path` before importing
# `harness.*`, but a lazily loaded module must not lean on its loader's import
# side effects -- mirror `layout/area_estimate.py`'s insert for
# `layout/divider/`, guarded so repeated renders do not stack duplicates.
_SIM_DIR = str(_REPO_ROOT / "sim")
if _SIM_DIR not in sys.path:
    sys.path.insert(0, _SIM_DIR)

from harness.loader import load_script  # noqa: E402


def render() -> str:
    """The divider's as-drawn matching, against floorplan.md's own targets.

    Derived from `layout/divider/plan.py` (the arrangement the generator
    draws) and `layout/area_estimate.py` (the mismatch arithmetic the area
    budget was closed with), so a record can never quote a centroid or a
    sigma the drawing does not have.
    """
    # Loaded by path rather than by `sys.path` insertion: `plan.py` is also
    # imported -- under KLayout's interpreter, from its own directory -- by the
    # divider's GDS generator, and a path load keeps a bare module name like
    # `plan` out of this process's import namespace.
    plan = load_script("divider_plan", _DIVIDER_DIR / "plan.py")
    area = load_script("divider_area_estimate", _LAYOUT_DIR / "area_estimate.py")
    _footprint, sigma3 = area.divider_field()
    pattern = "".join(
        "T" if p in plan.TOP_POSITIONS else "B" for p in plan.ACTIVE_POSITIONS
    )
    top_k = len(plan.TOP_POSITIONS) * plan.UNIT_KOHM
    bot_k = len(plan.BOT_POSITIONS) * plan.UNIT_KOHM
    return f"""## Matching, as drawn

Against `layout/floorplan.md` §4.1's numeric targets. Every figure below is
read out of `layout/divider/plan.py` -- the constants the generator actually
draws -- not transcribed from the document, and
`layout/tests/test_divider_layout.py` re-checks them against §4.1 on every CI
run.

| Property | §4.1's target | As drawn |
| --- | --- | --- |
| Unit | 50 kOhm `ppolyf_u_3k`, W = 2 um, L = 31.8 um | {plan.UNIT_KOHM:g} kOhm, W = {plan.UNIT_W_UM:g} um, L = {plan.UNIT_L_UM:g} um |
| String | 18 units, 6 up / 12 down | {len(plan.ACTIVE_POSITIONS)} units, {len(plan.TOP_POSITIONS)} up / {len(plan.BOT_POSITIONS)} down |
| Value | 900 kOhm total, tapped 600 k / 300 k | {top_k + bot_k:g} kOhm, tapped {bot_k:g} k / {top_k:g} k |
| Arrangement | `B T B B T B B T B B T B B T B B T B` | `{" ".join(pattern)}` |
| Pitch | 2.4 um (2.0 um strip + PRES.2's 0.4 um) | {plan.PITCH_UM:g} um ({plan.UNIT_W_UM:g} + {plan.PITCH_UM - plan.UNIT_W_UM:g}) |
| Dummies | one strip at each end | {len(plan.DUMMY_POSITIONS)}, at positions {", ".join(str(p) for p in plan.DUMMY_POSITIONS)} |
| **Top-leg centroid** | **9.5** | **{plan.centroid(plan.TOP_POSITIONS):g}** |
| **Bottom-leg centroid** | **9.5** | **{plan.centroid(plan.BOT_POSITIONS):g}** |
| Divider mismatch | 1.68 mV (3 sigma), vs. #9's budgeted 3.36 mV | {sigma3:.2f} mV (3 sigma) |

Both centroids landing on the same position is the *whole* claim this cell
exists to support, and it is the one term in the output-accuracy budget that
**cannot be simulated against this PDK at all**: the resistor subcircuits
hard-code `mis_r = 0` and the high-sheet `ppolyf_u_*k` cards carry no local
mismatch term (`sim/devchar/CONCLUSIONS.md` §2). The 3-sigma figure above is
therefore an arithmetic projection from a *proxy* coefficient (`ppolyf_u`'s
disabled `par_r = 0.021`, the proxy `README.md` note 3 sanctions), not a
measured or simulated result -- and it can only be claimed at all because the
drawn arrangement is the one it assumes, which is what this record's LVS
verdict establishes.

## What this LVS verdict does not cover

- **Resistance is not a compared parameter.** The deck's `BResistor` class
  (`rule_decks/custom_classes.lvs`) does `enable_parameter('R', false)` and
  compares `W` and `L` only. The match above therefore says the drawn
  *geometry* is the netlisted geometry, not that any resistance value is
  right. (It also means the deck's own nominal 3.0 kOhm/sq would call each
  unit 47.7 kOhm rather than 50 kOhm -- the 50 kOhm comes from
  `sim/devchar`'s measured effective sheet, 3.145 kOhm/sq, and is what the
  drawn 31.8 um length is sized from.)
- **Pin order is not checked here**, as for every cell in this flow -- see
  `layout/README.md`, "What LVS here does *not* check".
"""
