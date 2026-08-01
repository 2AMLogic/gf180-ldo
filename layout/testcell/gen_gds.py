"""Build the DRC/LVS bring-up test cell's layout, from the PDK's own PCell.

Run under KLayout's interpreter, never as a plain script::

    klayout -b -r layout/testcell/gen_gds.py \
        -rd out=<path/to/drclvs_testcell.gds> [-rd pdk=<gf180mcu variant dir>]

``layout/drclvs.py`` is what normally invokes it; this file only has to know
how to draw the cell.

Why a generator and not a committed GDS
---------------------------------------
The geometry comes from the gf180mcu PDK's *own* ``nfet`` PCell
(``libs.tech/klayout/tech/pymacros/klayout_api_cells``), so it is correct by
construction. That is the point: when the DRC deck or the LVS invocation is
what is under test, hand-drawn geometry would make every failure ambiguous
("is the deck wrong, or did I draw it wrong?"). Regenerating from the PDK
also means the test cell tracks the installed PDK version instead of
freezing a 2026 snapshot of it into the repo.

The only geometry this file adds on top of the PCell is **four net labels**,
which the PCell cannot know about:

===========  =====================  ==================================
Net          Layer                  Placed on
===========  =====================  ==================================
``S``        metal1 label (34/10)   left  source/drain metal1 strip
``D``        metal1 label (34/10)   right source/drain metal1 strip
``VSS``      metal1 label (34/10)   guard-ring metal1
``G``        poly2  label (30/10)   gate poly, above the active region
===========  =====================  ==================================

Those are the layers ``rule_decks/general_connections.lvs`` attaches to
``metal1_con`` / ``poly2_con``, so they are what turns the extracted nets
into *named* nets that can be compared against the schematic's port names.
Without them LVS can only compare topology, and a swapped pin would still
"match".

The terminals are identified by geometry rather than by hardcoded
coordinates (largest metal1 polygon = the guard ring; the remaining two
sorted left-to-right = source, drain), so changing ``W``/``L``/``nf`` below
does not silently move a label off its terminal.
"""

import os
import sys

import pya  # noqa: F401  (provided by the KLayout interpreter)

# Device under test. Keep in sync with layout/testcell/drclvs_testcell.sch --
# the LVS compare in layout/drclvs.py is what catches a drift between them.
PCELL_PARAMS = {
    "w": 2.0,          # um -- W=2u in the schematic
    "l": 0.28,         # um -- L=0.28u, the 3.3 V minimum channel length
    "nf": 1,
    "volt": "3.3V",
    "bulk": "Guard Ring",   # gives the p-tap ring that ties the bulk out
}

TOP_CELL = "DRCLVS_TESTCELL"

# gf180mcu database unit, as declared by the PDK's own KLayout tech file
# (libs.tech/klayout/tech/gf180mcu.lyt: <dbu>0.001</dbu>). Written explicitly
# because it is load bearing for more than precision -- see layout/README.md,
# "klt drc and the database unit".
DBU_UM = 0.001

# (layer, datatype) pairs, from rule_decks/layers_definitions.lvs.
L_POLY2 = (30, 0)
L_POLY2_LABEL = (30, 10)
L_METAL1 = (34, 0)
L_METAL1_LABEL = (34, 10)


def _rd(name, default=None):
    """Read a -rd switch (KLayout injects them as globals)."""
    value = globals().get(name, default)
    if value is None:
        raise SystemExit(f"gen_gds.py: missing required switch -rd {name}=...")
    return value


def _load_pdk_pcells(pdk_path):
    """Register the PDK's KLayout-API PCell library and return its name."""
    macros = os.path.join(pdk_path, "libs.tech", "klayout", "tech", "pymacros")
    if not os.path.isdir(macros):
        raise SystemExit(f"gen_gds.py: no PCell library at {macros}")
    sys.path.insert(0, macros)
    # The gf180mcu PCells read this to pick the metal stack / MIM option; the
    # variant we build against is D (5LM, 11K top metal, MIM option B).
    os.environ.setdefault("GF_PDK_OPTION", "D")
    from klayout_api_cells import gf180mcu_klayoutapi  # noqa: E402

    gf180mcu_klayoutapi()
    return "gf180mcu_klayoutapi"


def _text(cell, layout, layer_index, name, x_um, y_um):
    point = pya.Point(int(round(x_um / layout.dbu)), int(round(y_um / layout.dbu)))
    cell.shapes(layer_index).insert(pya.Text(name, pya.Trans(point)))


def build(out_path, pdk_path):
    library = _load_pdk_pcells(pdk_path)

    layout = pya.Layout()
    layout.dbu = DBU_UM
    top = layout.create_cell(TOP_CELL)
    device = layout.create_cell("nfet", library, dict(PCELL_PARAMS))
    if device is None:
        raise SystemExit(
            "gen_gds.py: the PDK's 'nfet' PCell rejected "
            f"{PCELL_PARAMS!r}. KLayout silently ignores unknown parameter "
            "names, so a PDK version whose nfet takes different parameter "
            "names would produce a default-sized device instead of an error "
            "-- check the installed PDK's cells/fet.py before changing these."
        )
    top.insert(pya.CellInstArray(device.cell_index(), pya.Trans()))
    # Flatten so the top cell is what DRC/LVS see directly: this is a
    # single-device vehicle, and hierarchy would only add a variable that has
    # nothing to do with what is being tested.
    top.flatten(-1, True)

    metal1 = pya.Region(top.begin_shapes_rec(layout.layer(*L_METAL1))).merged()
    shapes = sorted(metal1.each(), key=lambda p: p.bbox().area())
    if len(shapes) != 3:
        raise SystemExit(
            f"gen_gds.py: expected 3 metal1 shapes (source, drain, guard ring), "
            f"got {len(shapes)} -- the PCell's geometry changed, so the label "
            "placement below can no longer be trusted."
        )
    guard_ring = shapes[-1].bbox().to_dtype(layout.dbu)
    source, drain = (
        s.bbox().to_dtype(layout.dbu)
        for s in sorted(shapes[:-1], key=lambda p: p.bbox().left)
    )

    poly = pya.Region(top.begin_shapes_rec(layout.layer(*L_POLY2))).merged()
    poly_shapes = list(poly.each())
    if len(poly_shapes) != 1:
        raise SystemExit(
            f"gen_gds.py: expected 1 poly2 shape (the gate), got {len(poly_shapes)}"
        )
    gate = poly_shapes[0].bbox().to_dtype(layout.dbu)

    metal1_label = layout.layer(*L_METAL1_LABEL)
    poly2_label = layout.layer(*L_POLY2_LABEL)
    _text(top, layout, metal1_label, "S", source.center().x, source.center().y)
    _text(top, layout, metal1_label, "D", drain.center().x, drain.center().y)
    # A point inside the ring's left arm, not inside the (empty) ring interior.
    _text(
        top, layout, metal1_label, "VSS",
        guard_ring.left + 0.18, guard_ring.center().y,
    )
    # Above the active region, on the gate poly's own overhang.
    _text(top, layout, poly2_label, "G", gate.center().x, gate.top - 0.1)

    layout.write(out_path)
    box = top.dbbox()
    print(
        f"gen_gds.py: wrote {out_path} "
        f"(top={TOP_CELL}, dbu={layout.dbu}, "
        f"bbox={box.width():.3f}x{box.height():.3f} um)"
    )


build(_rd("out"), _rd("pdk"))
