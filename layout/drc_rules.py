"""gf180mcu DRC rule minimums, one transcription of the PDK's own rule deck.

The layout code used to restate these per file -- three names for CO.1's
0.22 um (``CO_SIZE`` / ``CONT_SIZE`` / ``CONT_UM``), two each for CO.4's
0.07 and PRES.2's 0.4 -- and the copies had already drifted: the divider's
``CONT_PITCH`` comment cited CO.2b for a 0.25 um space the deck assigns to
CO.2a. Issue #603 applies issue #588's one-transcription decision (the
layer table in ``gen_gds_common``) to the rule deck: one definition here is
what has to agree with the decks ``layout/drclvs.py`` re-runs on the drawn
GDS, where a per-file copy could only disagree in that one cell.

This module imports nothing, for the same reason ``layout/divider/plan.py``
does: it is read both by plain Python (``layout/area_estimate.py``,
``plan.py``) and under KLayout's interpreter (the generators, via
``gen_gds_common``'s re-export).

Values are quoted from the gf180mcuD KLayout DRC rule decks at open_pdks
revision f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7 -- the revision
``sim/harness/pdk.py`` pins. Each constant names the deck file it came
from; rule ids and wording follow the decks' own rule names:

    contact.rb: 'CO.1 : Min/max contact size. : 0.22µm'
    contact.rb: 'CO.2a : min. contact spacing : 0.25µm'
    contact.rb: 'CO.2b : Space in 4x4 or larger contact array. : 0.28µm'
    contact.rb: 'CO.4 : COMP overlap of contact. : 0.07µm'
    pres.rb:    'PRES.2 : Minimum space between Poly2 resistors: 0.4µm'

Only the rules more than one file draws against live here. A rule a single
file cites in a comment (CO.6a/CO.6b's 0.06 beside the divider's
deliberately wider overlap, CO.7, PRES.7, ...) stays where it is used.
"""

CO_1_SIZE_UM = 0.22  # CO.1  min/max contact size (contact.rb)
CO_2A_SPACE_UM = 0.25  # CO.2a min contact spacing (contact.rb)
CO_2B_ARRAY_SPACE_UM = 0.28  # CO.2b space in a 4x4-or-larger contact array (contact.rb)
CO_4_COMP_ENC_UM = 0.07  # CO.4  COMP overlap of contact (contact.rb)
PRES_2_SPACE_UM = 0.4  # PRES.2 min space between Poly2 resistors (pres.rb)
