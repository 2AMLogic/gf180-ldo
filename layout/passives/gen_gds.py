"""Build the passive-bearing DRC/LVS flow vehicle's layout, from PDK PCells.

Run under KLayout's interpreter, never as a plain script::

    klayout -b -r layout/passives/gen_gds.py \
        -rd out=<path/to/drclvs_passives.gds> [-rd pdk=<gf180mcu variant dir>]

``layout/drclvs.py`` is what normally invokes it; this file only has to know
how to draw the cell. It follows ``layout/testcell/gen_gds.py``'s pattern
exactly -- PDK PCells for the geometry, terminals located geometrically
rather than by hardcoded coordinates -- and differs from it in one way that
is the entire point of the cell: **not all of its devices are FETs.**

Why this cell exists (issue #313)
---------------------------------
``layout/testcell`` is one transistor, and a one-transistor cell cannot
detect that the flow is broken for everything else. The gf180mcu PDK's
xschem symbols carry an ``lvs_format`` attribute only on the FETs, so
``layout/drclvs.py`` stage 2 used to hard-fail on any cell containing a
resistor or a MIM capacitor -- i.e. on every real block in this design.
``layout/lvs_form.py`` fixes that; this cell is what proves it, end to end,
against the PDK's own DRC and LVS decks.

Three devices, deliberately unconnected to each other:

============  ===========================  ======================================
Device        PCell                        Why it is here
============  ===========================  ======================================
``R1``        ``ppolyf_u_high_Rs_resistor``  an H-poly resistor: the ``ppolyf_u_*k``
                                           family, extracted by the deck's
                                           ``POLY_RES`` branch, 3-terminal
                                           (bulk = substrate)
``C1``        ``cap_mim``                    a MIM cap: 2-terminal, extracted from
                                           the ``fusetop`` plate, and the only
                                           device here whose terminals are not
                                           on metal1/poly2
``M1``        ``nfet``                       a MULTI-FINGER FET: proves the deck's
                                           multifinger merge still lands one
                                           device, and gives stages 6/7 a MOS
                                           line to corrupt
============  ===========================  ======================================

They share no nets on purpose. This is a *flow* vehicle: interconnect would
add routing DRC and extraction variables that have nothing to do with what is
under test, exactly as ``layout/testcell``'s docstring argues for its own
minimality.

Where the labels go
-------------------

===========  =========================  =====================================
Net          Layer                      Placed on
===========  =========================  =====================================
``RP``       metal1 label (34/10)       resistor's left  poly-contact strap
``RM``       metal1 label (34/10)       resistor's right poly-contact strap
``CT``       metal5 label (81/10)       MIM top plate's metal5 (via fusetop)
``CB``       metal4 label (46/10)       MIM bottom plate's metal4 skirt
``S``        metal1 label (34/10)       FET's outer source/drain straps (x2)
``D``        metal1 label (34/10)       FET's centre source/drain strap
``G``        poly2  label (30/10)       FET's gate poly (every gate finger)
``VSS``      metal1 label (34/10)       FET's guard-ring metal1
===========  =========================  =====================================

Two of those are load bearing in ways a single-FET cell never exercises:

* ``S`` is placed on **two** disjoint metal1 straps. The LVS deck's
  "connectivity setup (Multifinger Devices)" pass runs ``connect_implicit('*')``,
  which is what joins same-named nets inside a circuit -- so this is also the
  check that a multi-finger device's interdigitated terminals resolve to one
  net without any strapping metal drawn here.
* ``CB`` sits on the metal4 skirt **outside** the ``fusetop`` plate. Inside
  it, metal4 is the deck's ``mimtm_virtual`` (the capacitor's P1 terminal);
  outside it is ordinary ``metal4_con``. They are connected
  (``connect(metal4_con, topmin1_metal)``), so either would work -- the skirt
  is chosen because it is unambiguous.

The metal stack is not a free choice: for the ``D`` variant this repo builds
against (5LM, MIM option B), the LVS deck extracts
``cap_mim_2f0_m4m5_noshield`` from a ``metal4``/``fusetop``/``metal5`` stack,
so the PCell must be asked for ``metal_level="M5"`` (top plate M5), not
``"M4"``. Asking for the wrong one yields a cell that is DRC-clean and
extracts nothing.
"""

import os
import sys

import pya  # noqa: F401  (provided by the KLayout interpreter)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gen_gds_common import _fail, _label, _load_pdk_pcells, _rd  # noqa: E402

TOP_CELL = "DRCLVS_PASSIVES"

# gf180mcu database unit, as declared by the PDK's own KLayout tech file
# (libs.tech/klayout/tech/gf180mcu.lyt: <dbu>0.001</dbu>). Written explicitly
# because it is load bearing for more than precision -- see layout/README.md,
# "klt drc and the database unit".
DBU_UM = 0.001

# Which metal stack the PCells are asked to draw for. gf180mcuD is 5LM with
# MIM option B; layout/drclvs.py's VARIANT_SWITCHES says the same thing to the
# DRC and LVS decks, and the two have to agree or the MIM cap extracts as
# nothing at all.
PDK_OPTION = "D"

# --- device parameters. Keep in sync with drclvs_passives.sch; the LVS compare
# --- in layout/drclvs.py is what catches a drift between them.

# H-poly resistor. NOTE the PCell's parameter names are the opposite way round
# from the device's electrical W/L: the contacts sit on the left and right
# edges, so current flows along `w` (electrical LENGTH) across a body `l` tall
# (electrical WIDTH). The PCell's own parameter *descriptions* say so --
# `param("l", ..., "Width")`, `param("w", ..., "Length")` -- which is why the
# schematic's L/W are not a copy of these numbers.
RES_PARAMS = {
    "l": 1.0,          # um, electrical WIDTH  -> schematic W=1u
    "w": 10.0,         # um, electrical LENGTH -> schematic L=10u
    "volt": "3.3V",
    "deepnwell": False,
    "pcmpgr": False,
}

# MIM capacitor. 20 x 20 um of 2 fF/um^2 plate.
CAP_PARAMS = {
    "l": 20.0,
    "w": 20.0,
    "mim_option": "MIM-B",
    "metal_level": "M5",   # 5LM: bottom plate metal4, top plate metal5
}

# Multi-finger FET. `w` is per-finger; the schematic's W is the total, so
# W = w * nf = 6 um across nf = 2 fingers.
FET_PARAMS = {
    "w": 3.0,
    "l": 0.28,         # the 3.3 V minimum channel length
    "nf": 2,
    "volt": "3.3V",
    "bulk": "Guard Ring",
}

# Gap between adjacent devices, um. Generous: these devices are unrelated and
# nothing here is trying to be area-efficient, so no inter-device spacing rule
# should ever be the reason this cell fails DRC.
DEVICE_GAP_UM = 20.0

# (layer, datatype) pairs, from rule_decks/layers_definitions.lvs.
L_POLY2 = (30, 0)
L_POLY2_LABEL = (30, 10)
L_METAL1 = (34, 0)
L_METAL1_LABEL = (34, 10)
L_METAL4 = (46, 0)
L_METAL4_LABEL = (46, 10)
L_METAL5 = (81, 0)
L_METAL5_LABEL = (81, 10)
L_FUSETOP = (75, 0)


def _device(layout, library, pcell, params, wrapper_name):
    """Instantiate ``pcell`` into a private, flattened wrapper cell.

    The wrapper exists so labels can be added in the device's own coordinate
    system: a PCell proxy cell is regenerated from its parameters, so shapes
    written straight into one are not reliably kept.
    """
    device = layout.create_cell(pcell, library, dict(params))
    if device is None:
        _fail(
            f"the PDK's {pcell!r} PCell rejected {params!r}. KLayout silently "
            "ignores unknown parameter names, so a PDK version whose PCell "
            "takes different parameter names would produce a default-sized "
            "device instead of an error -- check the installed PDK's "
            "pymacros/klayout_api_cells/ before changing these."
        )
    wrapper = layout.create_cell(wrapper_name)
    wrapper.insert(pya.CellInstArray(device.cell_index(), pya.Trans()))
    wrapper.flatten(-1, True)
    return wrapper


def _shapes(cell, layout, layer):
    """Merged polygons on ``layer``, largest-bbox last."""
    region = pya.Region(cell.begin_shapes_rec(layout.layer(*layer))).merged()
    return sorted(region.each(), key=lambda p: p.bbox().area())


def _expect(shapes, count, what, layer):
    if len(shapes) != count:
        _fail(
            f"expected {count} {what} on layer {layer[0]}/{layer[1]}, got "
            f"{len(shapes)} -- the PCell's geometry changed, so the label "
            "placement below can no longer be trusted."
        )
    return shapes


def _label_box(cell, layout, layer, name, box):
    _label(cell, layout, layer, name, box.center().x, box.center().y)


def build_resistor(layout, library):
    """H-poly resistor, terminals RP (left strap) and RM (right strap).

    The PCell draws THREE metal1 shapes, not two: the two poly-contact straps
    at either end of the body, plus a p+ COMP substrate tap off to the left.
    The tap is the device's bulk terminal and needs no label -- the LVS deck's
    ``connect_global(sub, <lvs_sub>)`` already names the substrate -- so the
    terminals are picked out as the metal1 shapes that land on poly2, which is
    true of the straps and of nothing else.
    """
    cell = _device(
        layout, library, "ppolyf_u_high_Rs_resistor", RES_PARAMS, "RES_UNIT"
    )
    poly = pya.Region(cell.begin_shapes_rec(layout.layer(*L_POLY2))).merged()
    straps = [
        s for s in _shapes(cell, layout, L_METAL1)
        if not pya.Region(s).and_(poly).is_empty()
    ]
    _expect(straps, 2, "metal1 shapes landing on poly2", L_METAL1)
    left, right = (
        s.bbox().to_dtype(layout.dbu)
        for s in sorted(straps, key=lambda p: p.bbox().left)
    )
    _label_box(cell, layout, L_METAL1_LABEL, "RP", left)
    _label_box(cell, layout, L_METAL1_LABEL, "RM", right)
    return cell


def build_capacitor(layout, library):
    """MIM capacitor, terminals CT (metal5 top plate) and CB (metal4 skirt)."""
    cell = _device(layout, library, "cap_mim", CAP_PARAMS, "CAP_UNIT")
    top = _expect(
        _shapes(cell, layout, L_METAL5), 1, "metal5 top plates", L_METAL5
    )[0].bbox().to_dtype(layout.dbu)
    bottom = _expect(
        _shapes(cell, layout, L_METAL4), 1, "metal4 bottom plates", L_METAL4
    )[0].bbox().to_dtype(layout.dbu)
    plate = _expect(
        _shapes(cell, layout, L_FUSETOP), 1, "fusetop MIM plates", L_FUSETOP
    )[0].bbox().to_dtype(layout.dbu)
    if not (bottom.left < plate.left and bottom.right > plate.right):
        _fail(
            "the MIM bottom plate no longer overhangs the fusetop plate, so "
            "there is nowhere unambiguous to put the CB label."
        )
    _label_box(cell, layout, L_METAL5_LABEL, "CT", top)
    # Middle of the left-hand metal4 skirt: inside metal4, outside fusetop.
    _label(
        cell, layout, L_METAL4_LABEL, "CB",
        (bottom.left + plate.left) / 2.0, bottom.center().y,
    )
    return cell


def build_fet(layout, library):
    """Multi-finger nfet, terminals S / D / G and a VSS guard ring."""
    cell = _device(layout, library, "nfet", FET_PARAMS, "FET_UNIT")
    metal1 = _shapes(cell, layout, L_METAL1)
    # nf fingers => nf + 1 source/drain straps, plus the guard ring (largest).
    _expect(metal1, FET_PARAMS["nf"] + 2, "metal1 shapes", L_METAL1)
    guard_ring = metal1[-1].bbox().to_dtype(layout.dbu)
    straps = [
        s.bbox().to_dtype(layout.dbu)
        for s in sorted(metal1[:-1], key=lambda p: p.bbox().left)
    ]
    # Interdigitated: alternating straps belong to alternating terminals. Both
    # S straps carry the same label and the deck's connect_implicit('*') is
    # what joins them -- no strapping metal is drawn here.
    for index, strap in enumerate(straps):
        _label_box(cell, layout, L_METAL1_LABEL, "S" if index % 2 == 0 else "D", strap)
    # A point inside the ring's left arm, not inside the (empty) ring interior.
    _label(
        cell, layout, L_METAL1_LABEL, "VSS",
        guard_ring.left + 0.18, guard_ring.center().y,
    )
    # Every gate finger, above the active region on the poly's own overhang.
    gates = _shapes(cell, layout, L_POLY2)
    if not gates:
        _fail("the FET PCell drew no poly2 gate")
    for gate in gates:
        box = gate.bbox().to_dtype(layout.dbu)
        _label(cell, layout, L_POLY2_LABEL, "G", box.center().x, box.top - 0.1)
    return cell


def build(out_path, pdk_path):
    library = _load_pdk_pcells(pdk_path, PDK_OPTION)

    layout = pya.Layout()
    layout.dbu = DBU_UM
    top = layout.create_cell(TOP_CELL)

    cursor = 0.0
    for builder in (build_fet, build_resistor, build_capacitor):
        cell = builder(layout, library)
        box = cell.dbbox()
        # Place each device left-to-right with a fixed gap, bottoms aligned.
        shift = pya.DTrans(pya.DVector(cursor - box.left, -box.bottom))
        top.insert(
            pya.CellInstArray(cell.cell_index(), pya.Trans(shift.to_itype(layout.dbu)))
        )
        cursor += box.width() + DEVICE_GAP_UM

    # Flatten so the top cell is what DRC/LVS see directly: the hierarchy here
    # is an artefact of how the labels get placed, not part of what is tested.
    top.flatten(-1, True)

    layout.write(out_path)
    box = top.dbbox()
    print(
        f"gen_gds.py: wrote {out_path} "
        f"(top={TOP_CELL}, dbu={layout.dbu}, "
        f"bbox={box.width():.3f}x{box.height():.3f} um)"
    )


build(_rd("out"), _rd("pdk"))
