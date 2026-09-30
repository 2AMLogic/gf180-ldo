"""Build the LDO pass-device array and its Msense replica, from PDK PCells.

Run under KLayout's interpreter, never as a plain script::

    klayout -b -r layout/pass_array/gen_gds.py \
        -rd out=<path/to/pass_array.gds> [-rd pdk=<gf180mcu variant dir>]

``layout/drclvs.py --cell pass_array`` is what normally invokes it.  Issue
#285; the physical commitments it implements are ``layout/floorplan.md`` §3.

What is drawn, and why it is drawn this way
-------------------------------------------

**The array is N copies of one unit cell, not one wide transistor.**  The unit
is the PDK's own ``pfet`` PCell at ``L = 0.28 um, W = 70 um, nf = 1`` -- the
per-finger geometry ``design/ldo_core.sch``'s ``Mpass`` (``W=2800u nf=40``) and
``design/ldo_ilimit.sch``'s ``Msense`` (``W=70u nf=1``) already ship.  The
instances are placed on the PCell's own finger pitch, which the generator
*derives* (see :func:`_finger_pitch_um`) rather than hardcodes, so abutting
``k`` of them reproduces the PDK's ``nf=k`` comb exactly.  That is not an
assertion of faith: :func:`_assert_abutment_matches_pcell` XORs the two
geometries and aborts if they differ on any layer.

**Msense is M instances of that same unit cell, inside the array.**  The
1/``N/M`` replica ratio is therefore a property of the drawn geometry -- of how
many copies of one cell were placed -- rather than of two independently edited
``W=`` strings that can drift.  ``floorplan.md`` §3.2's placement rules are
implemented literally:

* the replica sits at the array centroid (the pass fingers are split into two
  equal halves either side of it), so it sees the array's average temperature
  and the average VIN metal drop;
* its drain region is ``ISNS`` and is **not** merged into the ``VOUT`` drain
  comb -- a diffusion break of ``GAP_UM`` either side isolates it;
* the cells either side of the break present a ``VIN`` source region, so the
  break is symmetric;
* its gate is on the same ``PASS_GATE`` poly bus as every other finger, tapped
  at its own position in the bus rather than from the end.

**The metal stack carries 50 mA, and the generator checks that it does.**
``layout/pass_array/em_budget.py`` gets the as-drawn numbers (strap widths, via
counts, worst-case tap pitch, row counts -- all measured from what was just
drawn, not from these constants) and the build FAILS if any level is over the
tech LEFs' published ``DCCURRENTDENSITY`` limit.  The stack:

===== ============================ =============================================
Level Geometry                     Job
===== ============================ =============================================
M1    PCell's finger straps         collect the channel current over one region
Via1  full column, every strap      ``floorplan.md`` §3.3: "a full column along
                                    every source and drain strap, not a via per
                                    strap".  This is what makes M1 a
                                    non-issue -- M1 never carries more than half
                                    a via pitch of collected current.
M2    one strap per M1 strap        run the region's current along the finger
Via2  at every same-net M3 crossing hand it to the orthogonal rows
M3/4/5 horizontal rows, VIN/VOUT/   take it out of the cell.  All three levels
      ISNS interdigitated           are stacked on the same rows and stitched
                                    along their whole length by via3/via4 seas,
                                    so they act as one parallel conductor.
===== ============================ =============================================

M2 runs *along* the finger rather than orthogonal to it (``floorplan.md`` §3.3
sketches the orthogonal alternative) because the same section's via1
requirement -- a full column on every strap -- can only be met by a level that
covers the strap along its whole length.  The orthogonality the plan wants
moves up one level, to M3.  The consequence is in the record: M1 stops being
the binding EM row.

**What the cell does not contain.**  No bus to the pads and no pad landing
(top-level assembly, out of scope for #285); no p-substrate ring (this cell's
only bulk terminal is the n-well, tied to VIN by the guard ring drawn here).
The M3/M4/M5 rows reach *both* x edges of the cell, and the EM margins below
are quoted for landing them on both -- see the run record.

Net labels
----------

Exactly **one** label per net, deliberately.  Labelling every shape of a net
would let ``connect_implicit('*')`` in the LVS deck join pieces the layout
never actually connected, and LVS would pass on a broken stack.  One label per
net means every strap, via and row has to be genuinely connected for the
extraction to find the net at all.

=============  ========================  ==========================================
Net            Layer                     Placed on
=============  ========================  ==========================================
``VIN``        metal5 label (81/10)      one M5 VIN row -- proves the whole source
                                         stack AND the n-well guard ring are tied
``VOUT``       metal5 label (81/10)      one M5 VOUT row
``ISNS``       metal5 label (81/10)      one M5 ISNS row (Msense's drain)
``PASS_GATE``  poly2  label (30/10)      the top gate bus
=============  ========================  ==========================================
"""

import os
import sys

import pya  # noqa: F401  (provided by the KLayout interpreter)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import em_budget  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gen_gds_common import _fail, _label, _load_pdk_pcells, _rd  # noqa: E402

TOP_CELL = "PASS_ARRAY"

# gf180mcu database unit, as declared by the PDK's own KLayout tech file
# (libs.tech/klayout/tech/gf180mcu.lyt: <dbu>0.001</dbu>).
DBU_UM = 0.001

# 5LM, MIM option B. Must agree with layout/drclvs.py's VARIANT_SWITCHES.
PDK_OPTION = "D"

# ---------------------------------------------------------------------------
# the array, parameterised on the unit COUNT (issue #285) rather than on a
# total width. Keep in sync with design/ldo_core.sch / design/ldo_ilimit.sch;
# layout/tests/test_pass_array.py is what catches a drift, and the
# LVS compare in layout/drclvs.py is what catches a drift from the schematic
# this cell is netlisted against.
# ---------------------------------------------------------------------------

N_UNITS = 40          # pass-device unit cells  -> Mpass W = N_UNITS * 70 um
M_SENSE = 1           # Msense replica cells, of the SAME unit cell
REPLICA_RATIO = 40    # N_UNITS / M_SENSE, asserted below. design/ldo_ilimit.sch

UNIT_PARAMS = {
    "w": 70.0,        # um, per finger -- W/NF = 70 um keeps the device in
                      # DR-0025's widest pfet_03v3 bin, W/NF in [10, 100.001]
    "l": 0.28,        # um, the 3.3 V model minimum
    "nf": 1,
    "volt": "3.3V",
    "bulk": "None",   # one guard ring around the whole array, drawn below
}

# ---------------------------------------------------------------------------
# geometry constants. Every one is either a gf180mcuD design rule (named) or
# the PDK's own draw_fet.py constant for the same construction (named).
# ---------------------------------------------------------------------------

# Diffusion break either side of the Msense unit. 0.44 um is not arbitrary: it
# is the value that puts the strap either side of the break exactly one finger
# pitch (0.80 um) apart, so the comb's rhythm -- and therefore the M2 strap
# spacing, which at 0.40 um breaks M2.2a -- is the same across the break as
# everywhere else. Comfortably over cmp2cmp (0.32) in the PDK's own draw_fet.py.
GAP_UM = 0.44
GR_ARM_UM = 0.44         # guard-ring arm width; the PDK uses 0.36, widened so
                         # a via1 lands with 0.09 um of metal1 overlap
GR_GAP_X_UM = 0.32       # cmp2cmp, draw_fet.py
GR_GAP_Y_UM = 0.26       # ply2gr, draw_fet.py
NP_ENC_CMP_UM = 0.16     # np_enc_cmp, draw_fet.py
NW_ENC_NCMP_UM = 0.12    # nwell_enc_ncomp, draw_fet.py
CONT_UM = 0.22           # CO.1
CONT_PITCH_UM = 0.50     # CO.1 + CO.2b (0.22 + 0.28)
CMP2CONT_UM = 0.07       # cmp2cont, draw_fet.py

GATE_BUS_W_UM = 0.45     # >= PL.1 (0.28)
GATE_BUS_OVERLAP_UM = 0.05

VIA_UM = 0.26            # V1.1 / V2.1 / V3.1 / V4.1: min AND max
VIA_PITCH_UM = 0.52      # V*.2a: 0.26 space. Columns narrower than 4 cuts.
VIA_ARRAY_PITCH_UM = 0.62  # V*.2b: 0.36 space inside a 4x4-or-larger array
VIA_ENC_UM = 0.06        # V*.3c / V*.4b end-of-line overlap

M2_W_UM = 0.50           # <= finger pitch (0.80) - M2.2a space (0.30)
UPPER_W_UM = 2.20        # M3/M4/M5 row width
UPPER_PITCH_UM = 2.50    # leaves 0.30 um, i.e. M3.2b/M4.2b's wide-metal space
# Metal5 is METALTOP on a 5LM variant, so MT.2a (0.46 um) governs its spacing,
# not M5.2a (0.28 um). Insetting the top-level row by 0.10 um a side takes the
# gap to 0.50 um without moving the pitch the other two levels are drawn on.
M5_INSET_UM = 0.10

# Every ISNS_ROW_PERIOD'th row is ISNS. The phase is chosen so the ISNS rows
# are symmetric about the array's vertical centre (floorplan.md §3.2 wants the
# replica's own connections to be as centroid-symmetric as its channel is).
ISNS_ROW_PERIOD = 7
ISNS_ROW_PHASE = 3

# How many cell edges the M3/M4/M5 rows are landed on by the top-level
# assembly. The rows reach both; the EM margins are quoted for that.
EXIT_EDGES = 2

# (layer, datatype) pairs, from rule_decks/layers_definitions.lvs.
L_NWELL = (21, 0)
L_COMP = (22, 0)
L_POLY2 = (30, 0)
L_POLY2_LABEL = (30, 10)
L_PPLUS = (31, 0)
L_NPLUS = (32, 0)
L_CONTACT = (33, 0)
L_METAL1 = (34, 0)
L_VIA1 = (35, 0)
L_METAL2 = (36, 0)
L_VIA2 = (38, 0)
L_VIA3 = (40, 0)
L_VIA4 = (41, 0)
L_METAL3 = (42, 0)
L_METAL4 = (46, 0)
L_METAL5 = (81, 0)
L_METAL5_LABEL = (81, 10)

VIN, VOUT, ISNS, GATE = "VIN", "VOUT", "ISNS", "PASS_GATE"


# ---------------------------------------------------------------------------
# small geometry helpers
# ---------------------------------------------------------------------------

def _pfet(layout, library, **overrides):
    """One pfet PCell instance's cell, with UNIT_PARAMS plus ``overrides``."""
    params = dict(UNIT_PARAMS)
    params.update(overrides)
    cell = layout.create_cell("pfet", library, params)
    if cell is None:
        _fail(
            f"the PDK's 'pfet' PCell rejected {params!r}. KLayout silently "
            "ignores unknown parameter names, so a PDK version whose pfet "
            "takes different parameter names would produce a default-sized "
            "device instead of an error -- check the installed PDK's "
            "pymacros/klayout_api_cells/fet.py before changing these."
        )
    return cell


def _region(cell, layout, layer):
    return pya.Region(cell.begin_shapes_rec(layout.layer(*layer))).merged()


def _boxes(cell, layout, layer):
    """Merged shapes on ``layer`` as micron boxes, ordered left to right."""
    region = _region(cell, layout, layer)
    boxes = [p.bbox().to_dtype(layout.dbu) for p in region.each()]
    return sorted(boxes, key=lambda b: (b.left, b.bottom))


def _insert(cell, layout, layer, dbox):
    cell.shapes(layout.layer(*layer)).insert(dbox)


def _insert_region(cell, layout, layer, region):
    cell.shapes(layout.layer(*layer)).insert(region)


def _ring(layout, outer, inner):
    """Annulus between two micron boxes, as a Region."""
    return pya.Region(outer.to_itype(layout.dbu)) - pya.Region(inner.to_itype(layout.dbu))


def _grid(lo, hi, size, pitch, enclosure):
    """Centres of a row of ``size``-wide cuts inside [lo, hi], ``pitch`` apart.

    Returns [] when not even one cut fits with ``enclosure`` on each side.
    """
    usable = (hi - enclosure) - (lo + enclosure)
    if usable < size - 1e-9:
        return []
    count = int((usable - size) / pitch + 1e-9) + 1
    span = (count - 1) * pitch + size
    start = (lo + hi - span) / 2.0 + size / 2.0
    return [start + i * pitch for i in range(count)]


def _cuts(cell, layout, layer, box, pitch, enclosure=VIA_ENC_UM, size=VIA_UM):
    """Fill ``box`` with a grid of ``size`` cuts; returns how many were drawn."""
    xs = _grid(box.left, box.right, size, pitch, enclosure)
    ys = _grid(box.bottom, box.top, size, pitch, enclosure)
    half = size / 2.0
    for x in xs:
        for y in ys:
            _insert(cell, layout, layer,
                    pya.DBox(x - half, y - half, x + half, y + half))
    return len(xs) * len(ys)


# ---------------------------------------------------------------------------
# the unit cell and its abutment
# ---------------------------------------------------------------------------

def _scratch_layout():
    """A throwaway layout for measurements, so nothing lands in the output."""
    layout = pya.Layout()
    layout.dbu = DBU_UM
    return layout


def _finger_pitch_um(layout, library):
    """The PCell's own finger pitch, derived rather than hardcoded.

    An ``nf = k`` comb is ``k - 1`` pitches wider than an ``nf = 1`` one, so
    differencing the two COMP widths recovers the pitch whatever the PDK's
    contacted-pitch constants happen to be in this install.
    """
    one = _boxes(_pfet(layout, library, nf=1), layout, L_COMP)
    two = _boxes(_pfet(layout, library, nf=2), layout, L_COMP)
    if len(one) != 1 or len(two) != 1:
        _fail("the pfet PCell no longer draws a single merged COMP region")
    return two[0].width() - one[0].width()


def _assert_abutment_matches_pcell(layout, library, pitch, count):
    """``count`` abutted unit cells == the PDK's own ``nf = count`` comb.

    The whole "N unit cells" construction rests on this.  If the PCell's
    internal pitch ever stopped matching what :func:`_finger_pitch_um`
    recovers, the array would still look plausible -- merged diffusion,
    plausible DRC -- while quietly being a different device from the one every
    ``sim/`` record was taken against.  So XOR the two geometries, layer by
    layer, and refuse to build if they are not identical.
    """
    unit = _pfet(layout, library)
    abutted = layout.create_cell("_ABUT_CHECK")
    for index in range(count):
        abutted.insert(pya.CellInstArray(
            unit.cell_index(),
            pya.Trans(pya.DTrans(pya.DVector(index * pitch, 0.0)).to_itype(layout.dbu)),
        ))
    abutted.flatten(-1, True)
    reference = layout.create_cell("_ABUT_REF")
    reference.insert(pya.CellInstArray(
        _pfet(layout, library, nf=count).cell_index(), pya.Trans()))
    reference.flatten(-1, True)

    for layer in (L_COMP, L_POLY2, L_PPLUS, L_NWELL, L_CONTACT, L_METAL1):
        difference = _region(abutted, layout, layer) ^ _region(reference, layout, layer)
        if not difference.is_empty():
            _fail(
                f"{count} abutted unit cells at a {pitch} um pitch do NOT "
                f"reproduce the PDK's own nf={count} pfet on layer "
                f"{layer[0]}/{layer[1]} ({difference.count()} differing "
                "polygon(s)). The unit-cell construction is only meaningful "
                "while these are the same geometry -- see this file's "
                "docstring."
            )


# ---------------------------------------------------------------------------
# the build
# ---------------------------------------------------------------------------

def _place_units(layout, top, unit, pitch, unit_comp_w):
    """Half the pass fingers, the Msense group, then the other half.

    Returns the per-group counts of source/drain regions, in placement order.
    """
    if N_UNITS % 2:
        _fail(f"N_UNITS must be even so the array splits around Msense; got {N_UNITS}")
    if M_SENSE < 1 or N_UNITS % M_SENSE or N_UNITS // M_SENSE != REPLICA_RATIO:
        _fail(
            f"N_UNITS / M_SENSE must be exactly {REPLICA_RATIO} "
            f"(design/ldo_ilimit.sch's replica ratio); got "
            f"{N_UNITS} / {M_SENSE}"
        )
    half = N_UNITS // 2
    groups = (half, M_SENSE, half)

    cursor = 0.0
    for count in groups:
        for index in range(count):
            top.insert(pya.CellInstArray(
                unit.cell_index(),
                pya.Trans(pya.DTrans(
                    pya.DVector(cursor + index * pitch, 0.0)).to_itype(layout.dbu)),
            ))
        cursor += (count - 1) * pitch + unit_comp_w + GAP_UM
    # k abutted fingers share k-1 regions, so they present k+1 of them.
    return [count + 1 for count in groups]


def _strap_nets(region_counts):
    """One net name per source/drain region, in left-to-right order.

    The halves alternate VIN (source) / VOUT (drain) starting and ending on a
    source, so the break either side of Msense is flanked by VIN -- which is
    ``floorplan.md`` §3.2's rule, and also puts the outer regions of each half
    on the source rather than the drain.  The Msense group alternates VIN /
    ISNS the same way, so its drain never touches the VOUT comb.
    """
    nets = []
    for group, count in enumerate(region_counts):
        drain = ISNS if group == 1 else VOUT
        nets += [VIN if index % 2 == 0 else drain for index in range(count)]
    return nets


def _gate_buses(top, layout, gates, comp):
    """Two poly2 buses tying every finger's gate into one PASS_GATE net.

    The PCell draws each finger's gate as its own poly rectangle -- an ``nf=k``
    instance has ``k`` unconnected ones -- so without these the array's gates
    would only be "connected" by the LVS deck's ``connect_implicit('*')``, i.e.
    not connected at all.  Top and bottom both, so the bus resistance from the
    tap to the furthest finger is halved and ``Msense``'s gate sits at the same
    point of the same bus as its neighbours.
    """
    top_y = max(gate.top for gate in gates)
    bottom_y = min(gate.bottom for gate in gates)
    left = min(gate.left for gate in gates)
    right = max(gate.right for gate in gates)
    if left < comp.left or right > comp.right:
        _fail("the gate fingers stick out past COMP; the bus would need its own room")
    buses = (
        pya.DBox(left, top_y - GATE_BUS_OVERLAP_UM,
                 right, top_y - GATE_BUS_OVERLAP_UM + GATE_BUS_W_UM),
        pya.DBox(left, bottom_y + GATE_BUS_OVERLAP_UM - GATE_BUS_W_UM,
                 right, bottom_y + GATE_BUS_OVERLAP_UM),
    )
    for bus in buses:
        _insert(top, layout, L_POLY2, bus)
    return buses


def _guard_ring(top, layout, comp, buses):
    """n+ ring in the n-well, the array's only bulk terminal.

    Geometry follows the PDK's own ``draw_fet.py`` guard ring: COMP ring at
    ``cmp2cmp`` from the device diffusion and ``ply2gr`` from the poly, nplus
    over it with ``np_enc_cmp`` of enclosure, metal1 on the ring, and n-well
    enclosing it by ``nwell_enc_ncomp``.  Returns (inner, outer) micron boxes.
    """
    inner = pya.DBox(
        comp.left - GR_GAP_X_UM,
        min(bus.bottom for bus in buses) - GR_GAP_Y_UM,
        comp.right + GR_GAP_X_UM,
        max(bus.top for bus in buses) + GR_GAP_Y_UM,
    )
    outer = inner.enlarged(GR_ARM_UM, GR_ARM_UM)
    ring = _ring(layout, outer, inner)
    _insert_region(top, layout, L_COMP, ring)
    _insert_region(top, layout, L_METAL1, ring)
    _insert_region(top, layout, L_NPLUS, _ring(
        layout,
        outer.enlarged(NP_ENC_CMP_UM, NP_ENC_CMP_UM),
        inner.enlarged(-NP_ENC_CMP_UM, -NP_ENC_CMP_UM),
    ))
    _insert(top, layout, L_NWELL, outer.enlarged(NW_ENC_NCMP_UM, NW_ENC_NCMP_UM))

    # The vertical arms run the ring's full height; the horizontal ones are
    # pulled a whole contact pitch clear of them at each end. Without that the
    # two grids are independently centred and their corner cuts land 0.22 um
    # apart -- CO.2b wants 0.28 -- which is four violations in exactly the four
    # corners.
    arms = (
        pya.DBox(outer.left, outer.bottom, inner.left, outer.top),
        pya.DBox(inner.right, outer.bottom, outer.right, outer.top),
        pya.DBox(inner.left + CONT_PITCH_UM, inner.top,
                 inner.right - CONT_PITCH_UM, outer.top),
        pya.DBox(inner.left + CONT_PITCH_UM, outer.bottom,
                 inner.right - CONT_PITCH_UM, inner.bottom),
    )
    for arm in arms:
        if not _cuts(top, layout, L_CONTACT, arm, CONT_PITCH_UM,
                     enclosure=CMP2CONT_UM, size=CONT_UM):
            _fail("no contacts fitted in one of the guard-ring arms")
    return inner, outer


def _m2_and_via1(top, layout, straps, nets, ring_inner, ring_outer):
    """One M2 strap per M1 strap, each with a full via1 column.

    ``floorplan.md`` §3.3: "Via1 must be a full column along every source and
    drain strap, not a via per strap."  The VIN straps run on past the array to
    land a via on the guard ring, which is how the n-well gets tied to VIN --
    and, because VIN is labelled on M5 rather than on the ring, how LVS gets to
    prove that tie exists.
    """
    m2 = []
    via1_per_strap = 0
    for strap, net in zip(straps, nets):
        mid = (strap.left + strap.right) / 2.0
        if net == VIN:
            box = pya.DBox(mid - M2_W_UM / 2, ring_outer.bottom,
                           mid + M2_W_UM / 2, ring_outer.top)
        else:
            box = pya.DBox(mid - M2_W_UM / 2, strap.bottom,
                           mid + M2_W_UM / 2, strap.top)
        _insert(top, layout, L_METAL2, box)
        m2.append((box, net))
        count = _cuts(top, layout, L_VIA1,
                      pya.DBox(strap.left, strap.bottom, strap.right, strap.top),
                      VIA_PITCH_UM)
        if not count:
            _fail(f"no via1 fitted on the {net} strap at x = {mid:.3f} um")
        via1_per_strap = count
        if net == VIN:
            for arm in (
                pya.DBox(box.left, ring_inner.top, box.right, ring_outer.top),
                pya.DBox(box.left, ring_outer.bottom, box.right, ring_inner.bottom),
            ):
                if not _cuts(top, layout, L_VIA1, arm, VIA_PITCH_UM):
                    _fail("no via1 fitted between an M2 VIN strap and the guard ring")
    return m2, via1_per_strap


def _m5(row):
    """The metal5 shape for a row: narrower, because metal5 is metaltop."""
    return row.enlarged(0.0, -(M5_INSET_UM))


def _row_nets(count):
    """VIN / VOUT / ISNS for each M3/M4/M5 row, bottom to top.

    Every ``ISNS_ROW_PERIOD``'th row is ISNS, phased so those rows are
    symmetric about the array's vertical centre; the rest alternate VIN and
    VOUT in sequence, which keeps the worst same-net row spacing at
    ``ISNS_ROW_PERIOD - 1`` pitches rather than putting a hole in an otherwise
    uniform grid.
    """
    nets = []
    power = 0
    for index in range(count):
        if index % ISNS_ROW_PERIOD == ISNS_ROW_PHASE:
            nets.append(ISNS)
        else:
            nets.append(VIN if power % 2 == 0 else VOUT)
            power += 1
    return nets


def _upper_rows(top, layout, comp, m2):
    """M3/M4/M5 rows, the via2 taps into them, and the via3/via4 seas.

    M3, M4 and M5 are drawn on the same rows and stitched to each other along
    their whole length, so the three act as one parallel conductor taking the
    row's current out of the cell rather than as three levels each waiting to
    be relieved by the next.
    """
    count = int((comp.height() + 1e-9) // UPPER_PITCH_UM)
    if count < 4:
        _fail(f"only {count} M3/M4/M5 rows fit on a {comp.height()} um finger")
    nets = _row_nets(count)
    rows = []
    for index, net in enumerate(nets):
        bottom = comp.bottom + index * UPPER_PITCH_UM
        box = pya.DBox(comp.left, bottom, comp.right, bottom + UPPER_W_UM)
        _insert(top, layout, L_METAL3, box)
        _insert(top, layout, L_METAL4, box)
        # Metal5 IS metaltop on a 5LM variant, so it is the MT rules that
        # apply to it and not the M5 ones: MT.2a wants 0.46 um of space where
        # M5.2a would have been happy with 0.28. Narrow the top-level row
        # rather than open out the pitch of all three.
        _insert(top, layout, L_METAL5, _m5(box))
        rows.append((box, net))

    via2 = {VIN: 0, VOUT: 0, ISNS: 0}
    for strap, strap_net in m2:
        tally = 0
        for box, row_net in rows:
            if row_net != strap_net:
                continue
            overlap = pya.DBox(strap.left, box.bottom, strap.right, box.top)
            tally += _cuts(top, layout, L_VIA2, overlap, VIA_PITCH_UM)
        if not tally:
            _fail(f"an M2 {strap_net} strap got no via2 at all")
        via2[strap_net] = min(via2[strap_net], tally) if via2[strap_net] else tally

    via34 = 0
    for box, _net in rows:
        via34 = _cuts(top, layout, L_VIA3, box, VIA_ARRAY_PITCH_UM)
        # Offset via4 half a pitch so it never lands exactly on via3: stacked
        # cuts are legal here, but staggering them keeps each level's enclosure
        # check independent of the other's. Gridded on the narrowed metal5 row,
        # which is what has to enclose it.
        m5 = _m5(box)
        via34_top = _cuts(
            top, layout, L_VIA4,
            pya.DBox(m5.left + VIA_ARRAY_PITCH_UM / 2, m5.bottom, m5.right, m5.top),
            VIA_ARRAY_PITCH_UM)
        if not via34 or not via34_top:
            _fail("a M3/M4/M5 row got no via3 or no via4")
        via34 = min(via34, via34_top)
    return rows, nets, via2, via34


def _worst_same_net_pitch(nets):
    """Worst same-net row spacing, in um -- what sets the M2 peak density."""
    worst = 0.0
    for net in (VIN, VOUT):
        indices = [i for i, value in enumerate(nets) if value == net]
        for before, after in zip(indices, indices[1:]):
            worst = max(worst, (after - before) * UPPER_PITCH_UM)
    return worst


def build(out_path, pdk_path):
    library = _load_pdk_pcells(pdk_path, PDK_OPTION)
    layout = pya.Layout()
    layout.dbu = DBU_UM
    top = layout.create_cell(TOP_CELL)

    unit = _pfet(layout, library)
    unit_comp = _boxes(unit, layout, L_COMP)
    if len(unit_comp) != 1:
        _fail(f"the unit cell has {len(unit_comp)} COMP regions, expected 1")
    scratch = _scratch_layout()
    pitch = _finger_pitch_um(scratch, library)
    # Measured now, because top.flatten() below prunes the PCell proxy away.
    contacts_per_region = _contacts_per_region(unit, layout)
    _assert_abutment_matches_pcell(scratch, library, pitch, N_UNITS // 2)

    region_counts = _place_units(layout, top, unit, pitch, unit_comp[0].width())
    top.flatten(-1, True)

    # Everything below is located from what the PCells drew, never from a
    # coordinate written here.
    straps = _boxes(top, layout, L_METAL1)
    nets = _strap_nets(region_counts)
    if len(straps) != len(nets):
        _fail(
            f"found {len(straps)} metal1 source/drain straps but the placement "
            f"says there should be {len(nets)} -- the PCell's geometry changed, "
            "so every net assignment below is untrustworthy."
        )
    gates = _boxes(top, layout, L_POLY2)
    if len(gates) != N_UNITS + M_SENSE:
        _fail(f"found {len(gates)} gate fingers, expected {N_UNITS + M_SENSE}")
    comp = _region(top, layout, L_COMP).bbox().to_dtype(layout.dbu)

    # One pplus over the whole array. The per-unit pplus boxes overhang their
    # own COMP by np_enc_cmp in x and np_enc_gate in y, so the diffusion breaks
    # either side of Msense would otherwise leave 0.12 um pplus gaps -- PP.2
    # wants 0.4. Taking the bounding box of what the PCells drew keeps the
    # implant one rectangle without inventing an extent of our own.
    _insert(top, layout, L_PPLUS,
            _region(top, layout, L_PPLUS).bbox().to_dtype(layout.dbu))

    buses = _gate_buses(top, layout, gates, comp)
    ring_inner, ring_outer = _guard_ring(top, layout, comp, buses)
    m2, via1_per_strap = _m2_and_via1(top, layout, straps, nets, ring_inner, ring_outer)
    rows, row_nets, via2, via34 = _upper_rows(top, layout, comp, m2)

    # --- labels: exactly one per net, see the module docstring --------------
    for net in (VIN, VOUT, ISNS):
        box = next(box for box, row_net in rows if row_net == net)
        _label(top, layout, L_METAL5_LABEL, net,
               box.center().x, box.center().y)
    _label(top, layout, L_POLY2_LABEL, GATE,
           buses[0].center().x, buses[0].center().y)

    layout.write(out_path)

    # --- does it carry 50 mA? ----------------------------------------------
    geometry = em_budget.ArrayGeometry(
        n_units=N_UNITS,
        m_sense=M_SENSE,
        finger_w_um=UNIT_PARAMS["w"],
        n_drain_regions=sum(1 for net in nets if net == VOUT),
        contacts_per_region=contacts_per_region,
        m1_strap_w_um=straps[0].width(),
        via1_pitch_um=VIA_PITCH_UM,
        via1_per_strap=via1_per_strap,
        m2_strap_w_um=M2_W_UM,
        m2_tap_pitch_max_um=_worst_same_net_pitch(row_nets),
        via2_per_power_strap=via2[VOUT],
        via2_per_sense_strap=via2[ISNS],
        upper_strap_w_um=UPPER_W_UM,
        m5_strap_w_um=UPPER_W_UM - 2 * M5_INSET_UM,
        n_vout_rows=sum(1 for net in row_nets if net == VOUT),
        n_isns_rows=sum(1 for net in row_nets if net == ISNS),
        via34_per_row=via34,
        exits=EXIT_EDGES,
    )
    report, ok = em_budget.format_report(geometry)

    box = top.dbbox()
    print(
        f"gen_gds.py: wrote {os.path.basename(str(out_path))} "
        f"(top={TOP_CELL}, dbu={layout.dbu}, "
        f"bbox={box.width():.3f}x{box.height():.3f} um)"
    )
    print(
        f"gen_gds.py: {N_UNITS} pass unit cell(s) + {M_SENSE} Msense unit "
        f"cell(s) of the SAME cell, N/M = {N_UNITS // M_SENSE}; "
        f"{geometry.n_drain_regions} VOUT drain region(s), "
        f"{len(straps)} metal1 strap(s), "
        f"{len(rows)} M3/M4/M5 row(s) "
        f"({geometry.n_vout_rows} VOUT / {geometry.n_isns_rows} ISNS)"
    )
    print(report)
    print(f"\nas-drawn geometry handed to em_budget: {geometry}")
    if not ok:
        _fail(
            "the array as drawn is over a published current-density limit at "
            "50 mA (see the table above). A DRC-clean array that cannot carry "
            "the load current is not a pass -- issue #285."
        )


def _contacts_per_region(unit, layout):
    """CON cuts on one source/drain region of the unit cell."""
    contacts = _boxes(unit, layout, L_CONTACT)
    regions = _boxes(unit, layout, L_METAL1)
    if len(regions) != 2:
        _fail(f"the unit cell has {len(regions)} metal1 straps, expected 2")
    left = sum(1 for cut in contacts if cut.right <= regions[0].right)
    if not left:
        _fail("no contacts found on the unit cell's source region")
    return left


build(_rd("out"), _rd("pdk"))
