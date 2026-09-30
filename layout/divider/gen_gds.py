"""Build the feedback divider's layout: floorplan.md §4.1's unit-resistor array.

Run under KLayout's interpreter, never as a plain script::

    klayout -b -r layout/divider/gen_gds.py \
        -rd out=<path/to/fb_divider.gds> -rd pdk=<gf180mcu variant dir>

``layout/drclvs.py --cell divider`` is what normally invokes it; this file
only has to know how to draw the cell.

What this draws
---------------
`layout/floorplan.md` §4.1 fixes the divider as

    unit        50 kOhm ppolyf_u_3k, W = 2 um, L = 31.8 um
    string      18 units in series = 900 kOhm  (DR-0001's ~2 uA preload)
    tap         after 12 units from VSS -> Rbot = 600k, Rtop = 300k
    arrangement one row of 20 strips at 2.4 um pitch (PRES.2 = 0.4 um space),
                positions 1..18 active, ``B T B B T B B T B B T B B T B B T B``,
                plus one dummy strip at each end

and that is what is drawn here, at those numbers, with the top-leg units at
positions {2, 5, 8, 11, 14, 17}. Both legs' centroids therefore land on
position 9.5 -- the middle of a 1..18 row -- which is the exact 1-D common
centroid the plan's mismatch arithmetic assumes. Those constants live in
``plan.py`` beside this file, and ``layout/tests/test_divider_layout.py``
re-derives the centroid from them rather than trusting this comment.

`design/netlist/ldo_core.spice` still carries `Rtop`/`Rbot` as **ideal**
resistors; this generator plus `divider/fb_divider.sch` are the real devices
they become at layout, and `layout/area_estimate.py` already budgets the
array (not the ideal pair) into the core-area estimate.

Where the geometry comes from
-----------------------------
Every resistor strip is the PDK's *own* ``ppolyf_u_high_Rs_resistor`` PCell
(``libs.tech/klayout/tech/pymacros/klayout_api_cells``) at ``volt='3.3V'``,
so the device geometry -- poly body, salicide block, implant heads, contact
heads -- is correct by construction, exactly as ``layout/testcell`` takes its
transistor from the PDK's ``nfet`` PCell. This file adds only the things a
PCell cannot know about: the inter-unit links, the array's guard ring, and
the three net labels.

One deliberate subtraction (see ``_strip_the_per_unit_substrate_ties``): the
PCell draws a 0.42 um p-tap column immediately to the left of *each* strip,
0.71 um clear of that strip's own Metal1 head. Twenty of those columns would
wall off the entire left routing channel -- only a single Metal1 track fits
between a column and its head -- while floorplan.md §4.1 asks for the array
to have its **own** substrate-tap ring anyway. So the per-unit ties are
removed and replaced by one ring around the whole string. The removal is
asserted shape-by-shape against the exact x window they occupy, so a PDK
whose PCell moves them fails loudly instead of being quietly mangled.

How the 18 units are linked, and why the two legs use different tracks
----------------------------------------------------------------------
The interdigitation makes the electrical order differ from the physical
order, and that is what dictates the link routing. With the bottom leg
occupying positions {1,3,4,6,7,9,10,12,13,15,16,18} and the top leg
{2,5,8,11,14,17}, a series chain must alternate sides at every unit, so each
side of the row carries roughly half of *each* leg's links. Every bottom-leg
link that spans two positions jumps *over* a top-leg strip, and that strip's
own link has to leave from between the two -- i.e. the two legs' link sets
interleave in the sense that makes single-layer planar routing impossible
(e.g. bottom (1,3) against top (2,5)).

Rather than reach for Metal2, the two legs are given disjoint Metal1
channels:

* **bottom leg** -- links run in the channels just outside the strips' heads
  (left and right of the row). Its own links never interleave with each
  other, so one track per side suffices.
* **top leg** -- links run *over the resistor bodies*, on tracks in the
  middle of the array, reached by stubs that leave each head **inwards**.
  They therefore never enter the side channels at all.

Both legs stay on Metal1, which is what floorplan.md §4.1 asks for ("the 18
units are 18 straight rectangles joined on M1", with an M1 routing keep-out
over the string reserved for exactly these links). Metal1 over the salicided
poly body makes no connection -- the resistor's terminals are its two contact
heads, which is also why the extracted device's L is the 31.8 um between
them.

Net labels, the only other thing added on top of the PCells:

===========  =====================  ==================================
Net          Layer                  Placed on
===========  =====================  ==================================
``VOUT_S``   metal1 label (34/10)   position 2's left head (top of Rtop)
``FB``       metal1 label (34/10)   the divider tap link (17<->18)
``VSS``      metal1 label (34/10)   the guard ring / substrate tap ring
===========  =====================  ==================================

Those are the layers ``rule_decks/general_connections.lvs`` attaches to
``metal1_con``, so they are what turns the extracted nets into *named* nets.
"""

import os
import sys

import pya  # noqa: F401  (provided by the KLayout interpreter)

# The arrangement itself -- strip geometry, the interdigitation pattern, the
# electrical order of each leg -- lives in plan.py beside this file, so that
# layout/tests/test_divider_layout.py checks the same constants this
# generator draws rather than a second transcription of floorplan.md §4.1.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan import (  # noqa: E402
    ACTIVE_POSITIONS,
    BOT_ORDER,
    DUMMY_POSITIONS,
    N_POSITIONS,
    PITCH_UM,
    TOP_ORDER,
    UNIT_L_UM,
    UNIT_W_UM,
    chain_links,
    leg_terminal_side,
)

TOP_CELL = "FB_DIVIDER"

# gf180mcu database unit, as declared by the PDK's own KLayout tech file.
# Load bearing beyond precision -- see layout/README.md, "The database-unit
# trap in klt drc".
DBU_UM = 0.001

# (layer, datatype) pairs, from rule_decks/layers_definitions.lvs.
L_COMP = (22, 0)
L_PPLUS = (31, 0)
L_CONTACT = (33, 0)
L_METAL1 = (34, 0)
L_METAL1_LABEL = (34, 10)

# ---------------------------------------------------------------------------
# Geometry this file adds. Every clearance below is checked by the DRC decks
# stages 3/4 of layout/drclvs.py run; the numbers are chosen with margin
# rather than at the rule minimum so that a PDK bump does not silently land
# on a boundary.
# ---------------------------------------------------------------------------

M1_W = 0.30  # link/stub width (M1.1 minimum is 0.23)
M1_GAP = 0.25  # link-to-head clearance (M1.2a minimum is 0.23)

# The PCell's per-unit p-tap column, which this file removes: it occupies
# x in [-1.78, -1.32] and nothing else of the PCell reaches past -1.04.
PTAP_CLIP_X = -1.30

GR_W = 0.42  # guard-ring COMP/Metal1 width (the PCell's own p-tap width)
GR_IMPLANT_ENC = 0.02  # PPLUS overlap of the ring's COMP (the PCell's value)
GR_MARGIN_X = 1.32  # ring inner edge to the outermost link track
GR_MARGIN_Y = 2.00  # ring inner edge to the outermost head metal
CONT_SIZE = 0.22  # CO.1 -- contacts are exactly this, min and max
CONT_PITCH = 0.47  # CO.1 + CO.2b's 0.25 um contact space
CONT_ENC = 0.10  # COMP/Metal1 overlap of contact (CO.4/CO.6 need 0.07/0.06)


def _fail(message):
    """Abort the build, loudly.

    ``klayout -b -r`` **swallows SystemExit**: a bare `raise SystemExit("…")`
    prints nothing and the klayout process still exits 0 (checked against
    KLayout 0.28.16). Every assertion in this file therefore has to print its
    own message before bailing out, or a PDK change would abort the build
    with no diagnostic at all -- `layout/drclvs.py` would only report "layout
    build produced no .gds", which names the symptom and not the cause.
    """
    sys.stderr.write(f"gen_gds.py: {message}\n")
    sys.stderr.flush()
    raise SystemExit(1)


def _rd(name, default=None):
    """Read a -rd switch (KLayout injects them as globals)."""
    value = globals().get(name, default)
    if value is None:
        _fail(f"missing required switch -rd {name}=...")
    return value


def _load_pdk_pcells(pdk_path):
    """Register the PDK's KLayout-API PCell library and return its name."""
    macros = os.path.join(pdk_path, "libs.tech", "klayout", "tech", "pymacros")
    if not os.path.isdir(macros):
        _fail(f"no PCell library at {macros}")
    sys.path.insert(0, macros)
    # The gf180mcu PCells read this to pick the metal stack / MIM option; the
    # variant we build against is D (5LM, 11K top metal, MIM option B).
    os.environ.setdefault("GF_PDK_OPTION", "D")
    from klayout_api_cells import gf180mcu_klayoutapi  # noqa: E402

    gf180mcu_klayoutapi()
    return "gf180mcu_klayoutapi"


def strip_y0(position):
    """Bottom edge of the strip at ``position``, in um."""
    return position * PITCH_UM


def strip_yc(position):
    """Centre line of the strip at ``position``, in um."""
    return position * PITCH_UM + UNIT_W_UM / 2.0


class Drawing(object):
    """Accumulates Metal1 geometry per net, and checks the nets stay apart."""

    def __init__(self, layout, cell):
        self.layout = layout
        self.cell = cell
        self.m1 = layout.layer(*L_METAL1)
        self.nets = {}

    def _dbox(self, x1, y1, x2, y2):
        return pya.DBox(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def wire(self, net, x1, y1, x2, y2):
        box = self._dbox(x1, y1, x2, y2)
        self.cell.shapes(self.m1).insert(box.to_itype(self.layout.dbu))
        self.nets.setdefault(net, pya.Region()).insert(
            pya.Box(box.to_itype(self.layout.dbu))
        )

    def region(self, net, region):
        self.cell.shapes(self.m1).insert(region)
        self.nets.setdefault(net, pya.Region()).insert(region)

    def check_nets_are_disjoint(self):
        """No two nets' Metal1 may touch -- a routing bug, not a DRC one.

        This is exactly the gap DRC cannot cover. Shapes that come *close*
        (1..229 dbu, i.e. under M1.2a's 0.23 um) are a spacing violation and
        stage 3/4 report them; shapes that touch or overlap merge into one
        polygon, so DRC sees nothing wrong and the run only fails later, as
        an LVS mismatch that reads like a schematic error. Sizing one side by
        a single dbu before intersecting catches precisely the zero-distance
        case, here, where the message can name the two nets.
        """
        names = sorted(self.nets)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                grown = self.nets[a].dup().merged().sized(1)
                overlap = grown & self.nets[b].dup().merged()
                if not overlap.is_empty():
                    box = overlap.bbox().to_dtype(self.layout.dbu)
                    _fail(
                        f"nets {a!r} and {b!r} share Metal1 at "
                        f"{box} -- the link routing is wrong"
                    )


def _strip_the_per_unit_substrate_ties(layout, cell):
    """Delete the PCell's per-strip p-tap column (see the module docstring).

    Asserts, rather than assumes, that the only thing living left of
    ``PTAP_CLIP_X`` is that column: every removed shape must sit inside the
    x window the PCell puts it in, and every layer it spans must lose the
    same number of shapes as there are strips.
    """
    removed = {}
    for layer in (L_COMP, L_PPLUS, L_CONTACT, L_METAL1):
        index = layout.layer(*layer)
        victims = []
        for shape in cell.shapes(index).each():
            box = shape.bbox().to_dtype(layout.dbu)
            if box.right <= PTAP_CLIP_X:
                if box.left < -1.80 or box.right > -1.30:
                    _fail(
                        f"shape {box} on layer {layer} is left of "
                        f"{PTAP_CLIP_X} um but outside the PCell's known p-tap "
                        "window -- the PDK's resistor PCell changed, so this "
                        "file's surgery can no longer be trusted"
                    )
                victims.append(shape)
        for shape in victims:
            shape.delete()
        removed[layer] = len(victims)

    for layer in (L_COMP, L_PPLUS, L_METAL1):
        if removed[layer] != N_POSITIONS:
            _fail(
                f"expected to remove {N_POSITIONS} p-tap shapes on "
                f"layer {layer}, removed {removed[layer]} -- the PDK's resistor "
                "PCell changed"
            )
    if removed[L_CONTACT] < N_POSITIONS:
        _fail(
            f"expected at least {N_POSITIONS} p-tap contacts, "
            f"removed {removed[L_CONTACT]}"
        )
    return removed


def _merge_head_implants(layout, cell):
    """Run each column of head P+ implant together into one continuous strip.

    The PCell gives every strip its own pair of head implants, 0.18 um proud
    of the 2.0 um strip in y. At floorplan.md §4.1's 2.4 um pitch that leaves
    a 0.04 um slot between one strip's head implant and the next strip's --
    a **PP.2** violation (0.4 um minimum P+ space) 38 times over -- and puts
    each strip's *neighbour's* implant 0.22 um from its own unsalicided poly,
    which is **SB.15b** (0.32 um minimum) another 76 times. Both are artefacts
    of tiling a PCell that was drawn to stand alone; neither is a property of
    the plan's pitch.

    Filling the slots turns each column into a single implant strip, which is
    what the array wants physically in any case. It is filled in **y only**:
    the resistor body itself must stay unimplanted (that is what makes the
    high-sheet flavour high-sheet), and the PCell's implant already stops at
    the body edge in x.
    """
    index = layout.layer(*L_PPLUS)
    columns = {}
    for shape in cell.shapes(index).each():
        box = shape.bbox().to_dtype(layout.dbu)
        columns.setdefault((round(box.left, 3), round(box.right, 3)), []).append(box)
    if len(columns) != 2 or any(len(v) != N_POSITIONS for v in columns.values()):
        _fail(
            "expected two columns of "
            f"{N_POSITIONS} head implants, got "
            f"{ {k: len(v) for k, v in columns.items()} } -- the PDK's resistor "
            "PCell changed"
        )
    for (left, right), boxes in columns.items():
        cell.shapes(index).insert(
            pya.DBox(
                left,
                min(b.bottom for b in boxes),
                right,
                max(b.top for b in boxes),
            ).to_itype(layout.dbu)
        )


def _head_boxes(layout, cell):
    """The two Metal1 contact heads of every strip, keyed by (position, side).

    Found geometrically (y tells which strip, x tells which end) rather than
    at hardcoded coordinates, so a PCell whose head metal moves is caught by
    the assertions here instead of by a silently mis-placed link.
    """
    metal1 = pya.Region(cell.begin_shapes_rec(layout.layer(*L_METAL1))).merged()
    boxes = [p.bbox().to_dtype(layout.dbu) for p in metal1.each()]
    if len(boxes) != 2 * N_POSITIONS:
        _fail(
            f"expected {2 * N_POSITIONS} Metal1 head shapes "
            f"({N_POSITIONS} strips x 2 ends), got {len(boxes)} -- the PCell's "
            "geometry changed, so the link placement below cannot be trusted"
        )
    heads = {}
    for box in boxes:
        position = int(round((box.center().y - UNIT_W_UM / 2.0) / PITCH_UM))
        side = "L" if box.center().x < UNIT_L_UM / 2.0 else "R"
        if not (0 <= position < N_POSITIONS) or (position, side) in heads:
            _fail(
                f"Metal1 head {box} does not map to a unique "
                f"(position, side); got ({position}, {side})"
            )
        heads[(position, side)] = box
    return heads


def _tracks(heads):
    """x windows for the four link tracks, derived from the head geometry."""
    left_head = heads[(0, "L")]
    right_head = heads[(0, "R")]
    return {
        # Side channels, just outside the heads: the bottom leg's links.
        ("channel", "L"): (
            left_head.left - M1_GAP - M1_W,
            left_head.left - M1_GAP,
        ),
        ("channel", "R"): (
            right_head.right + M1_GAP,
            right_head.right + M1_GAP + M1_W,
        ),
        # Over the resistor bodies: the top leg's links, reached inwards.
        ("body", "L"): (UNIT_L_UM * 0.25, UNIT_L_UM * 0.25 + M1_W),
        ("body", "R"): (UNIT_L_UM * 0.75 - M1_W, UNIT_L_UM * 0.75),
    }


def _stub(draw, heads, tracks, net, position, side, kind):
    """Metal1 from a strip's head out to (or in to) one of the link tracks."""
    head = heads[(position, side)]
    x_lo, x_hi = tracks[(kind, side)]
    yc = strip_yc(position)
    if side == "L":
        x1, x2 = (x_lo, head.right) if kind == "channel" else (head.left, x_hi)
    else:
        x1, x2 = (head.left, x_hi) if kind == "channel" else (x_lo, head.right)
    draw.wire(net, x1, yc - M1_W / 2.0, x2, yc + M1_W / 2.0)


def _link(draw, heads, tracks, net, pos_a, pos_b, side, kind):
    """One inter-unit link: two stubs plus the vertical run between them."""
    _stub(draw, heads, tracks, net, pos_a, side, kind)
    _stub(draw, heads, tracks, net, pos_b, side, kind)
    x_lo, x_hi = tracks[(kind, side)]
    ya, yb = strip_yc(pos_a), strip_yc(pos_b)
    draw.wire(net, x_lo, min(ya, yb) - M1_W / 2.0, x_hi, max(ya, yb) + M1_W / 2.0)


def _guard_ring(layout, cell, draw, heads, tracks):
    """One substrate-tap ring around the whole string (floorplan.md §4.1).

    Replaces the twenty per-unit p-tap columns the PCell would have drawn,
    and is the layout's only VSS conductor: the string's bottom end, both
    dummy strips and the substrate all land on it.
    """
    dbu = layout.dbu
    x_left = tracks[("channel", "L")][0] - GR_MARGIN_X
    x_right = tracks[("channel", "R")][1] + GR_MARGIN_X
    y_bottom = heads[(0, "L")].bottom - GR_MARGIN_Y
    y_top = heads[(N_POSITIONS - 1, "L")].top + GR_MARGIN_Y

    inner = pya.DBox(x_left, y_bottom, x_right, y_top)
    outer = inner.enlarged(GR_W, GR_W)
    ring = pya.Region(outer.to_itype(dbu)) - pya.Region(inner.to_itype(dbu))

    cell.shapes(layout.layer(*L_COMP)).insert(ring)
    draw.region("VSS", ring.dup())

    implant_outer = outer.enlarged(GR_IMPLANT_ENC, GR_IMPLANT_ENC)
    implant_inner = inner.enlarged(-GR_IMPLANT_ENC, -GR_IMPLANT_ENC)
    cell.shapes(layout.layer(*L_PPLUS)).insert(
        pya.Region(implant_outer.to_itype(dbu))
        - pya.Region(implant_inner.to_itype(dbu))
    )

    # Contacts down the middle of each arm, on a CO.2b-legal pitch.
    contact = layout.layer(*L_CONTACT)
    def fill(x0, y0, x1, y1):
        count = 0
        y = y0
        while y + CONT_SIZE <= y1 + 1e-9:
            x = x0
            while x + CONT_SIZE <= x1 + 1e-9:
                cell.shapes(contact).insert(
                    pya.DBox(x, y, x + CONT_SIZE, y + CONT_SIZE).to_itype(dbu)
                )
                count += 1
                x += CONT_PITCH
            y += CONT_PITCH
        return count

    arm_lo_x = outer.left + CONT_ENC
    arm_hi_x = outer.right - CONT_ENC
    arm_lo_y = outer.bottom + CONT_ENC
    arm_hi_y = outer.top - CONT_ENC
    # The two vertical arms run the full height; the horizontal ones stop
    # short of the corners, by enough that a corner contact keeps its
    # CO.2b spacing from the vertical arm's own column.
    corner = CONT_PITCH - CONT_SIZE - CONT_ENC  # 0.15 um
    placed = fill(arm_lo_x, arm_lo_y, arm_lo_x + CONT_SIZE, arm_hi_y)
    placed += fill(arm_hi_x - CONT_SIZE, arm_lo_y, arm_hi_x, arm_hi_y)
    placed += fill(inner.left + corner, arm_lo_y,
                   inner.right - corner, arm_lo_y + CONT_SIZE)
    placed += fill(inner.left + corner, arm_hi_y - CONT_SIZE,
                   inner.right - corner, arm_hi_y)
    if placed < 4:
        _fail("guard ring got no contacts")
    return inner, outer


def _text(cell, layout, layer_index, name, x_um, y_um):
    point = pya.Point(int(round(x_um / layout.dbu)), int(round(y_um / layout.dbu)))
    cell.shapes(layer_index).insert(pya.Text(name, pya.Trans(point)))


def build(out_path, pdk_path):
    library = _load_pdk_pcells(pdk_path)

    layout = pya.Layout()
    layout.dbu = DBU_UM
    top = layout.create_cell(TOP_CELL)

    # PCell params: the resistor generator calls the *current path* `w` and
    # the *strip width* `l` (see its own display_text_impl), i.e. exactly the
    # opposite of the device's extracted L and W. Passing them the wrong way
    # round would draw a 31.8 um-wide, 2 um-long resistor and LVS would say
    # so -- but name the mapping here so nobody has to rediscover it.
    unit = layout.create_cell(
        "ppolyf_u_high_Rs_resistor",
        library,
        {
            "l": UNIT_W_UM,  # -> the extracted device's W
            "w": UNIT_L_UM,  # -> the extracted device's L
            "volt": "3.3V",
            "deepnwell": False,
            "pcmpgr": False,
        },
    )
    if unit is None:
        _fail(
            "the PDK's 'ppolyf_u_high_Rs_resistor' PCell rejected "
            "its parameters. KLayout silently ignores unknown parameter names, "
            "so a PDK version whose resistor PCell takes different ones would "
            "produce a default-sized device instead of an error -- check the "
            "installed PDK's klayout_api_cells/res.py before changing these."
        )
    for position in range(N_POSITIONS):
        top.insert(
            pya.CellInstArray(
                unit.cell_index(),
                pya.Trans(pya.Vector(0, int(round(strip_y0(position) / layout.dbu)))),
            )
        )
    # Flatten so the top cell is what DRC/LVS see directly -- hierarchy would
    # add a variable that has nothing to do with what is being verified.
    top.flatten(-1, True)

    _strip_the_per_unit_substrate_ties(layout, top)
    _merge_head_implants(layout, top)
    heads = _head_boxes(layout, top)
    tracks = _tracks(heads)
    draw = Drawing(layout, top)

    # ---- the string ------------------------------------------------------
    # Bottom leg: VSS -> FB, links in the side channels.
    for index, (pos_a, pos_b, side) in enumerate(chain_links(BOT_ORDER)):
        _link(draw, heads, tracks, f"nb{index + 1}", pos_a, pos_b, side, "channel")
    # Top leg: FB -> VOUT_S, links over the resistor bodies.
    for index, (pos_a, pos_b, side) in enumerate(chain_links(TOP_ORDER)):
        _link(draw, heads, tracks, f"nt{index + 1}", pos_a, pos_b, side, "body")

    # ---- the three ports -------------------------------------------------
    # FB is the tap: the bottom leg's last free terminal joined to the top
    # leg's first. floorplan.md §4.1 calls this a single-metal-layer change,
    # and it is: re-tapping the string moves this one link.
    fb_bot = (BOT_ORDER[-1], leg_terminal_side(len(BOT_ORDER) - 1, end=True))
    fb_top = (TOP_ORDER[0], leg_terminal_side(0, end=False))
    if fb_bot[1] != fb_top[1]:
        _fail("the divider tap's two terminals are not on one side")
    _link(draw, heads, tracks, "FB", fb_bot[0], fb_top[0], fb_bot[1], "channel")

    # VOUT_S is the top leg's last free terminal: a label on its head, no
    # route -- this cell is LVS'd standalone, so its pins are named nets.
    vout_pos = TOP_ORDER[-1]
    vout_side = leg_terminal_side(len(TOP_ORDER) - 1, end=True)
    draw.region("VOUT_S", pya.Region(heads[(vout_pos, vout_side)].to_itype(layout.dbu)))

    inner, _outer = _guard_ring(layout, top, draw, heads, tracks)

    # VSS: the bottom leg's free end plus both dummy strips, out to the ring.
    vss_stubs = [(BOT_ORDER[0], leg_terminal_side(0, end=False))]
    for position in DUMMY_POSITIONS:
        vss_stubs += [(position, "L"), (position, "R")]
    for position, side in vss_stubs:
        head = heads[(position, side)]
        yc = strip_yc(position)
        x_far = inner.left - GR_W / 2.0 if side == "L" else inner.right + GR_W / 2.0
        draw.wire(
            "VSS",
            head.left if side == "R" else head.right,
            yc - M1_W / 2.0,
            x_far,
            yc + M1_W / 2.0,
        )

    # Every head must now belong to exactly one net, and no two nets may
    # share metal. Both are routing invariants, not DRC ones.
    draw.check_nets_are_disjoint()
    for (position, side), head in sorted(heads.items()):
        owners = [
            net
            for net, region in draw.nets.items()
            if not (region.dup().merged() & pya.Region(head.to_itype(layout.dbu))).is_empty()
        ]
        if len(owners) != 1:
            _fail(
                f"strip {position} side {side} is claimed by "
                f"{len(owners)} nets ({owners}) -- expected exactly one"
            )

    # ---- labels ----------------------------------------------------------
    metal1_label = layout.layer(*L_METAL1_LABEL)
    vout_head = heads[(vout_pos, vout_side)]
    _text(top, layout, metal1_label, "VOUT_S", vout_head.center().x, vout_head.center().y)
    fb_x = sum(tracks[("channel", fb_bot[1])]) / 2.0
    _text(
        top, layout, metal1_label, "FB", fb_x,
        (strip_yc(fb_bot[0]) + strip_yc(fb_top[0])) / 2.0,
    )
    _text(
        top, layout, metal1_label, "VSS",
        inner.left - GR_W / 2.0, (inner.bottom + inner.top) / 2.0,
    )

    layout.write(out_path)
    box = top.dbbox()
    print(
        f"gen_gds.py: wrote {out_path} "
        f"(top={TOP_CELL}, dbu={layout.dbu}, "
        f"bbox={box.width():.3f}x{box.height():.3f} um, "
        f"{len(ACTIVE_POSITIONS)} units + {len(DUMMY_POSITIONS)} dummies)"
    )


build(_rd("out"), _rd("pdk"))
