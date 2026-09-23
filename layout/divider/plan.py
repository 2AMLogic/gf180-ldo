"""The feedback divider's arrangement, as plain numbers.

`layout/floorplan.md` §4.1 fixes the divider's geometry and its
interdigitation; this module is that plan in executable form, so the layout
generator and the tests read the *same* constants instead of each carrying
its own transcription of the document.

    unit        50 kOhm ppolyf_u_3k, W = 2 um, L = 31.8 um
    string      18 units in series = 900 kOhm  (DR-0001's ~2 uA preload)
    tap         after 12 units from VSS -> Rbot = 600k, Rtop = 300k
    arrangement one row of 20 strips at 2.4 um pitch (PRES.2 = 0.4 um space),
                positions 1..18 active, ``B T B B T B B T B B T B B T B B T B``,
                plus one dummy strip at each end

Imported by ``layout/divider/gen_gds.py`` (under KLayout's interpreter) and
by ``layout/tests/test_divider_layout.py`` (plain Python, no PDK), which is
why it imports nothing itself.
"""

# --- geometry -------------------------------------------------------------

UNIT_W_UM = 2.0  # drawn strip width  == the extracted device's W
UNIT_L_UM = 31.8  # drawn strip length == the extracted device's L
PITCH_UM = 2.4  # 2.0 um strip + PRES.2's 0.4 um minimum poly-resistor space

# floorplan.md §4.1's own numbers for the unit: 50 kOhm per strip, from
# sim/devchar's MEASURED effective sheet for this flavour rather than the
# LVS deck's nominal 3.0 kOhm/sq (CONCLUSIONS.md §2 -> 0.318 um of length
# per kOhm at w = 1 um, i.e. 3.145 kOhm/sq).
UNIT_KOHM = 50.0
UM_PER_KOHM_AT_1UM = 0.318

# --- arrangement ----------------------------------------------------------

# Physical positions, 0..19 along the row. 0 and 19 are the dummy strips;
# 1..18 are the string, in floorplan.md §4.1's own 1-based numbering.
N_POSITIONS = 20
DUMMY_POSITIONS = (0, 19)
ACTIVE_POSITIONS = tuple(range(1, 19))
TOP_POSITIONS = (2, 5, 8, 11, 14, 17)  # "B T B B T B B T B B T B B T B B T B"
BOT_POSITIONS = tuple(p for p in ACTIVE_POSITIONS if p not in TOP_POSITIONS)

# Electrical order along each leg. The bottom leg runs VSS -> FB up the row;
# the top leg runs FB -> VOUT_S *down* it, so the tap (FB) joins positions 17
# and 18 -- adjacent -- instead of needing a route the length of the array.
BOT_ORDER = BOT_POSITIONS  # 1,3,4,6,7,9,10,12,13,15,16,18
TOP_ORDER = tuple(reversed(TOP_POSITIONS))  # 17,14,11,8,5,2


def centroid(positions):
    """Mean position of a leg. floorplan.md §4.1's target is 9.5 for both."""
    return float(sum(positions)) / len(positions)


def leg_terminal_side(unit_index, end):
    """Which side of the row a series chain's terminal lands on.

    A series chain has to alternate sides at every unit (a unit's two
    terminals are its two contact heads, one per side), so the whole
    assignment follows from putting unit 0's *start* terminal on the left.
    ``end`` is False for the start terminal, True for the end terminal.
    """
    left = (unit_index % 2 == 0) != bool(end)
    return "L" if left else "R"


def chain_links(order):
    """``(position_a, position_b, side)`` for each link in a series chain."""
    return [
        (order[j], order[j + 1], leg_terminal_side(j, end=True))
        for j in range(len(order) - 1)
    ]


def spans_overlap(a, b):
    """Do two link spans, given as position pairs, share any row interval?"""
    lo_a, hi_a = sorted(a)
    lo_b, hi_b = sorted(b)
    return lo_a < hi_b and lo_b < hi_a
