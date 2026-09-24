"""Current-density and IR arithmetic for the pass array, from as-drawn numbers.

``layout/pass_array/gen_gds.py`` measures its own drawn geometry (strap widths,
via counts, tap pitches, region counts) and hands the numbers to
:func:`evaluate` here.  The generator then **fails the build** if any level is
over its published limit, so "DRC-clean but cannot carry 50 mA" is not a state
this cell can be committed in (issue #285's acceptance criteria).

Everything this module compares against is published data, not a preference:

* The DC current-density limits are the ``DCCURRENTDENSITY AVERAGE`` entries in
  the gf180mcu standard-cell tech LEFs
  (``libs.ref/gf180mcu_fd_sc_mcu{7,9}t5v0/techlef/*.tlef``) -- the only
  machine-readable EM data a ``gf180mcuD`` install publishes.  ``layout/floorplan.md``
  §1 transcribes them and §8.1 derives the unit convention (mA per um of drawn
  width for routing layers, mA per cut for cut layers).
* The ``CON`` contact layer publishes **no** limit at all.  DR-0030 (proposed)
  carries a 129 uA/cut placeholder obtained by cut-area scaling from Via1;
  ``floorplan.md`` §8.3 says so, and so does the row this module emits.
* Sheet resistances and via resistances (min / nom / max) are ``floorplan.md``
  §1's transcription of the same LEFs and the magic tech file.

This file is deliberately pure Python with no KLayout import: the generator
runs it under ``klayout -b -r``, and ``layout/tests/test_em_budget.py`` runs it
under pytest on any host.
"""

from __future__ import annotations

import dataclasses

# --- published limits (layout/floorplan.md §1) -----------------------------

# mA per um of drawn width, DC average.
J_M1_M4_MA_PER_UM = 0.67
J_M5_MA_PER_UM = 1.5
# mA per cut, DC average, Via1-Via4.
I_VIA_MA = 0.18
# The CON layer publishes nothing; DR-0030's placeholder, by cut-area scaling
# from Via1. Flagged as an assumption wherever it is used.
I_CONTACT_MA_PLACEHOLDER = 0.129

# Ohm/square, nominal and max views (M1-M4 then M5).
RSH_M1_M4 = (0.090, 0.104)
RSH_M5 = (0.060, 0.070)
# Ohm per cut, nominal and max (Via1-Via4), and the p+ contact (single value).
R_VIA = (4.5, 15.0)
R_CONTACT = 5.2

# The load the block is specified at (README.md Load row).
I_LOAD_MA = 50.0


@dataclasses.dataclass(frozen=True)
class ArrayGeometry:
    """As-drawn numbers, all measured from the layout the generator just built."""

    n_units: int                 # pass-device unit cells
    m_sense: int                 # Msense replica unit cells (same unit cell)
    finger_w_um: float           # drawn gate width of one unit cell
    n_drain_regions: int         # VOUT source/drain regions in the comb
    contacts_per_region: int     # CON cuts on one source/drain region
    m1_strap_w_um: float         # PCell's own finger strap width
    via1_pitch_um: float         # pitch of the full via1 column on each strap
    via1_per_strap: int          # cuts in that column
    m2_strap_w_um: float         # vertical M2 strap over each M1 strap
    m2_tap_pitch_max_um: float   # worst same-net spacing of the M3 rows
    via2_per_power_strap: int    # via2 cuts on one VOUT M2 strap
    via2_per_sense_strap: int    # via2 cuts on the ISNS M2 strap
    upper_strap_w_um: float      # M3/M4 row width
    m5_strap_w_um: float         # metal5 row width (narrower: metal5 IS metaltop)
    n_vout_rows: int             # M3/M4/M5 rows carrying VOUT
    n_isns_rows: int             # rows carrying ISNS
    via34_per_row: int           # via3 (= via4) cuts under one row
    exits: int                   # cell edges the rows are landed on (1 or 2)


@dataclasses.dataclass(frozen=True)
class Row:
    level: str
    drawn: str          # what was drawn, in words
    density: str        # as-drawn peak, with unit
    limit: str          # published limit, with unit
    margin: float       # limit / as-drawn; < 1.0 is a fail
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.margin >= 1.0


def _conductance_shares(n_m1_m4_levels: int) -> tuple[float, float]:
    """(share of a M1-M4 level, share of the M5 level) in a parallel stack.

    Current divides by conductance, not by EM capacity, which is why M5 -- the
    thick top metal -- takes less than its capacity share and the thin levels
    bind first.  Sheet resistance at the NOMINAL view, which is the corner
    ``floorplan.md`` §3.4 says binds.
    """
    g_thin = 1.0 / RSH_M1_M4[0]
    g_thick = 1.0 / RSH_M5[0]
    total = n_m1_m4_levels * g_thin + g_thick
    return g_thin / total, g_thick / total


def evaluate(g: ArrayGeometry, i_load_ma: float = I_LOAD_MA) -> list[Row]:
    """One row per current-carrying level, worst case at ``i_load_ma``."""
    rows: list[Row] = []

    # Every drain region is shared by the two fingers either side of it, so it
    # collects 2 x (i_load / n_units) -- which is i_load / n_drain_regions.
    i_region = i_load_ma / g.n_drain_regions
    # Linear density along one finger strap: the channel injects uniformly.
    lam = i_region / g.finger_w_um
    # Msense's own drain carries the replica current.
    i_sense = i_load_ma / (g.n_units // g.m_sense)

    rows.append(Row(
        "CON (drain contacts)",
        f"{g.contacts_per_region} cuts per drain region, {g.n_drain_regions} regions",
        f"{i_region / g.contacts_per_region * 1e3:.1f} uA/cut",
        f"{I_CONTACT_MA_PLACEHOLDER * 1e3:.0f} uA/cut",
        I_CONTACT_MA_PLACEHOLDER / (i_region / g.contacts_per_region),
        "NOT a published limit -- DR-0030's placeholder (floorplan.md §8.3)",
    ))

    # M1 carries only what it must move to the nearest via1 in a continuous
    # column: half a via pitch of collected current.
    m1_peak = lam * (g.via1_pitch_um / 2) / g.m1_strap_w_um
    rows.append(Row(
        "M1 finger strap",
        f"{g.m1_strap_w_um} um wide, full via1 column at {g.via1_pitch_um} um pitch",
        f"{m1_peak:.3f} mA/um",
        f"{J_M1_M4_MA_PER_UM} mA/um",
        J_M1_M4_MA_PER_UM / m1_peak,
        "the column, not the width, is what makes this pass (floorplan.md §3.3)",
    ))

    i_via1 = i_region / g.via1_per_strap
    rows.append(Row(
        "Via1 column",
        f"{g.via1_per_strap} cuts per strap",
        f"{i_via1 * 1e3:.1f} uA/cut",
        f"{I_VIA_MA * 1e3:.0f} uA/cut",
        I_VIA_MA / i_via1,
    ))

    # M2 runs along the finger and is tapped by the same-net M3 rows; the peak
    # is at a tap, carrying half the worst same-net row spacing of collected
    # current.
    m2_peak = lam * (g.m2_tap_pitch_max_um / 2) / g.m2_strap_w_um
    rows.append(Row(
        "M2 strap",
        f"{g.m2_strap_w_um} um wide, tapped every "
        f"{g.m2_tap_pitch_max_um} um (worst same-net M3 row spacing)",
        f"{m2_peak:.3f} mA/um",
        f"{J_M1_M4_MA_PER_UM} mA/um",
        J_M1_M4_MA_PER_UM / m2_peak,
    ))

    i_via2 = i_region / g.via2_per_power_strap
    rows.append(Row(
        "Via2, VOUT strap",
        f"{g.via2_per_power_strap} cuts per M2 strap",
        f"{i_via2 * 1e3:.1f} uA/cut",
        f"{I_VIA_MA * 1e3:.0f} uA/cut",
        I_VIA_MA / i_via2,
    ))

    i_via2_sense = i_sense / g.via2_per_sense_strap
    rows.append(Row(
        "Via2, ISNS strap",
        f"{g.via2_per_sense_strap} cuts, carrying the 1/"
        f"{g.n_units // g.m_sense} replica current",
        f"{i_via2_sense * 1e3:.1f} uA/cut",
        f"{I_VIA_MA * 1e3:.0f} uA/cut",
        I_VIA_MA / i_via2_sense,
    ))

    # M3/M4/M5 are stacked over each other on the same row and stitched along
    # their whole length, so they are one parallel conductor taking the row's
    # current out of the cell.
    thin_share, thick_share = _conductance_shares(2)   # M3 and M4 are thin, M5 thick
    i_row = i_load_ma / g.n_vout_rows / g.exits
    for level, share, limit, width in (
        ("M3", thin_share, J_M1_M4_MA_PER_UM, g.upper_strap_w_um),
        ("M4", thin_share, J_M1_M4_MA_PER_UM, g.upper_strap_w_um),
        ("M5", thick_share, J_M5_MA_PER_UM, g.m5_strap_w_um),
    ):
        density = i_row * share / width
        rows.append(Row(
            f"{level} exit row",
            f"{g.n_vout_rows} VOUT rows x {width} um, "
            f"landed on {g.exits} cell edge(s)",
            f"{density:.3f} mA/um",
            f"{limit} mA/um",
            limit / density,
            "current splits by conductance, not by capacity",
        ))

    # Via3/Via4 hand the row's current between those levels; the conservative
    # reading is that everything not staying on M3 crosses via3, and everything
    # reaching M5 crosses via4.
    i_via3 = i_row * (thin_share + thick_share) / g.via34_per_row
    rows.append(Row(
        "Via3/Via4 sea",
        f"{g.via34_per_row} cuts under each row",
        f"{i_via3 * 1e3:.1f} uA/cut",
        f"{I_VIA_MA * 1e3:.0f} uA/cut",
        I_VIA_MA / i_via3,
    ))

    return rows


def series_resistance_mohm(g: ArrayGeometry, view: int = 0) -> dict[str, float]:
    """Array-internal series resistance of the VOUT path, in milliohms.

    ``view`` selects the nominal (0) or max (1) corner of the tech LEF's
    resistance spread.  ``floorplan.md`` §3.4 budgets **40 mOhm per side**
    nominal (80 mOhm total) and **80 mOhm per side** max, and buys bus length
    with whatever is left at **36.0 mOhm (nominal) per square of M4 || M5**.
    The distributed-metal term is the plan's own 2.00 / 2.31 mOhm figure: it is
    set by the tapping scheme rather than by anything this generator chooses,
    and re-deriving it here would be a different (worse) estimate of the same
    thing rather than a measurement.
    """
    r_via = R_VIA[view]
    n_drain_straps = g.n_drain_regions
    contacts = n_drain_straps * g.contacts_per_region
    via1 = n_drain_straps * g.via1_per_strap
    via2 = n_drain_straps * g.via2_per_power_strap
    via3 = g.n_vout_rows * g.via34_per_row
    terms = {
        "contacts": R_CONTACT / contacts * 1e3,
        "via1": r_via / via1 * 1e3,
        "via2": r_via / via2 * 1e3,
        "via3": r_via / via3 * 1e3,
        "via4": r_via / via3 * 1e3,
        "distributed metal": 2.00 if view == 0 else 2.31,
    }
    terms["total"] = sum(terms.values())
    return terms


def squares_left_for_the_bus(total_mohm: float, budget_mohm: float = 40.0,
                             per_square_mohm: float = 36.0) -> float:
    """How many squares of M4 || M5 the bus run may still spend, per side."""
    return (budget_mohm - total_mohm) / per_square_mohm


def format_report(g: ArrayGeometry, i_load_ma: float = I_LOAD_MA) -> tuple[str, bool]:
    """Human-readable table plus an overall pass/fail."""
    rows = evaluate(g, i_load_ma)
    width = max(len(r.level) for r in rows)
    lines = [
        f"electromigration, at {i_load_ma:.0f} mA of load current "
        f"(limits: layout/floorplan.md §1):",
    ]
    for row in rows:
        verdict = f"{row.margin:5.1f}x" if row.ok else f"{row.margin:5.2f}x OVER LIMIT"
        lines.append(
            f"  {row.level:<{width}}  {row.density:>14}  "
            f"of {row.limit:<12} {verdict}"
        )
        if row.note:
            lines.append(f"  {'':<{width}}  -- {row.note}")
    nominal = series_resistance_mohm(g, 0)
    maximum = series_resistance_mohm(g, 1)
    lines.append("")
    lines.append("IR, VOUT side of the array (budget: floorplan.md §3.4):")
    for key in ("contacts", "via1", "via2", "via3", "via4", "distributed metal", "total"):
        lines.append(f"  {key:<18} {nominal[key]:7.2f} mOhm nom   {maximum[key]:7.2f} mOhm max")
    lines.append(
        f"  bus run left       {squares_left_for_the_bus(nominal['total']):7.2f} squares "
        f"of M4 || M5 per side at the nominal corner (design rule: <= 0.75)"
    )
    ok = all(row.ok for row in rows)
    return "\n".join(lines), ok
