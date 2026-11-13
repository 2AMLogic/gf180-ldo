"""Shared helpers for the per-cell ``gen_gds.py`` KLayout generators.

``layout/passives/gen_gds.py`` and ``layout/pass_array/gen_gds.py`` each
carried byte-identical copies of ``_fail``, ``_rd``, ``_load_pdk_pcells``
and ``_label`` (issue #333). Consolidated here, following the same
``sys.path.insert`` + ``from X import Y`` idiom ``sim/harness/pvt_log.py``'s
callers and ``layout/drclvs.py`` (``sys.path.insert(0, str(LAYOUT_DIR))``)
already use for exactly this kind of module.

Issue #508 added ``_create_pcell`` and ``_merged_region``, the PCell
instantiate-or-fail block and the merged-layer ``Region`` expression that
each generator had been spelling out for itself.

Issue #555 moved the substrate/well-tap guard ring (``guard_ring``) and the
contact-grid fill it rests on here from the divider and pass-array generators.

Issue #370 routed ``layout/divider/gen_gds.py`` and
``layout/testcell/gen_gds.py`` through here as well, so all four generators
share one copy. The latter two had used
``os.environ.setdefault("GF_PDK_OPTION", "D")``; every generator now passes
its variant ("D") explicitly and ``_load_pdk_pcells`` assigns it
unconditionally, so an ambient ``GF_PDK_OPTION`` cannot silently change the
metal stack or MIM option a cell is drawn with.

Issue #588 moved the PDK *facts* the four generators had each restated for
themselves -- the variant (``PDK_OPTION``), the database unit (``DBU_UM``) and
the ``(layer, datatype)`` table -- here beside those helpers, so the cells
agree with each other by construction and a single definition is what has to
agree with ``layout/drclvs.py`` and the PDK's layer file.
"""

import os
import sys

import pya  # noqa: F401  (provided by the KLayout interpreter)


# ---------------------------------------------------------------------------
# gf180mcu PDK facts (issue #588). All four generators draw for the same
# variant, on the same database unit, from the same layer table, so each is
# defined once here and imported rather than restated per generator -- a cell
# cannot drift onto a different metal stack or a mistyped layer on its own.
# ---------------------------------------------------------------------------

# Which metal stack the PCells are asked to draw for. gf180mcu variant D is
# 5LM, 11K top metal, MIM option B. Must agree with layout/drclvs.py's
# VARIANT_SWITCHES, which says the same thing to the DRC and LVS decks: the
# two have to agree or the MIM cap extracts as nothing at all. Each generator
# still passes this explicitly to _load_pdk_pcells(), as issue #370 requires,
# so an ambient GF_PDK_OPTION cannot change the stack a cell is drawn with.
PDK_OPTION = "D"

# gf180mcu database unit, as declared by the PDK's own KLayout tech file
# (libs.tech/klayout/tech/gf180mcu.lyt: <dbu>0.001</dbu>). Load bearing beyond
# precision -- see layout/README.md, "The database-unit trap in klt drc":
# klt drc's rule thresholds are raw database-unit integers and are not scaled
# by the layout's own dbu, so the same geometry gets a different verdict at a
# different database unit.
DBU_UM = 0.001

# (layer, datatype) pairs, from the PDK's rule_decks/layers_definitions.lvs.
# One transcription of a PDK file, reviewed once: a mistyped pair here would
# draw on the wrong layer, and in a per-generator copy it would do so in that
# one cell only.
L_NWELL = (21, 0)
L_COMP = (22, 0)
L_POLY2 = (30, 0)
L_POLY2_LABEL = (30, 10)
L_PPLUS = (31, 0)
L_NPLUS = (32, 0)
L_CONTACT = (33, 0)
L_METAL1 = (34, 0)
L_METAL1_LABEL = (34, 10)
L_VIA1 = (35, 0)
L_METAL2 = (36, 0)
L_VIA2 = (38, 0)
L_VIA3 = (40, 0)
L_VIA4 = (41, 0)
L_METAL3 = (42, 0)
L_METAL4 = (46, 0)
L_METAL4_LABEL = (46, 10)
L_FUSETOP = (75, 0)
L_METAL5 = (81, 0)
L_METAL5_LABEL = (81, 10)


def _fail(message):
    """Abort with ``message`` actually visible.

    ``klayout -b -r`` swallows a bare ``SystemExit``'s message *and* still
    exits 0, so a generator that aborts this way looks to its caller like a
    silent success that happened to write no file. Printing to stderr first
    is what makes the reason survive; ``layout/drclvs.py``'s "layout build
    produced no <path>" check is the backstop for the exit status.
    """
    print(f"gen_gds.py: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def _rd(name, default=None):
    """Read a -rd switch (KLayout injects them as globals).

    KLayout injects ``-rd`` switches into the *executed script's own*
    module globals -- i.e. the caller's, not this shared module's. Reading
    plain ``globals()`` here would always miss them once this function is
    imported rather than defined inline, so the lookup goes through the
    immediate caller's frame instead.
    """
    caller_globals = sys._getframe(1).f_globals
    value = caller_globals.get(name, default)
    if value is None:
        _fail(f"missing required switch -rd {name}=...")
    return value


def _load_pdk_pcells(pdk_path, pdk_option):
    """Register the PDK's KLayout-API PCell library and return its name."""
    macros = os.path.join(pdk_path, "libs.tech", "klayout", "tech", "pymacros")
    if not os.path.isdir(macros):
        _fail(f"no PCell library at {macros}")
    sys.path.insert(0, macros)
    # The gf180mcu PCells read this to pick the metal stack / MIM option. It is
    # not advisory: cap_mim's produce_impl() raises outright if MIM-B is asked
    # for under option A.
    os.environ["GF_PDK_OPTION"] = pdk_option
    from klayout_api_cells import gf180mcu_klayoutapi  # noqa: E402

    gf180mcu_klayoutapi()
    return "gf180mcu_klayoutapi"


def _label(cell, layout, layer, name, x_um, y_um):
    point = pya.Point(int(round(x_um / layout.dbu)), int(round(y_um / layout.dbu)))
    cell.shapes(layout.layer(*layer)).insert(pya.Text(name, pya.Trans(point)))


def _create_pcell(layout, library, name, params, hint):
    """Instantiate PDK PCell ``name`` with ``params``; ``_fail`` if it is None.

    ``hint`` is where under the PDK to look when the parameter names change.
    """
    cell = layout.create_cell(name, library, dict(params))
    if cell is None:
        _fail(
            f"the PDK's {name!r} PCell rejected {params!r}. KLayout silently "
            "ignores unknown parameter names, so a PDK version whose PCell "
            "takes different parameter names would produce a default-sized "
            f"device instead of an error -- check the installed PDK's {hint} "
            "before changing these."
        )
    return cell


def _merged_region(cell, layout, layer):
    """Merged ``Region`` of ``layer`` (a ``(layer, datatype)`` pair) in ``cell``."""
    return pya.Region(cell.begin_shapes_rec(layout.layer(*layer))).merged()


def ring_region(layout, outer, inner):
    """Annulus between two micron ``DBox``es, as a ``Region``."""
    return pya.Region(outer.to_itype(layout.dbu)) - pya.Region(inner.to_itype(layout.dbu))


def _grid(lo, hi, size, pitch, enclosure, align="center"):
    """Centres of a row of ``size``-wide cuts inside [lo, hi], ``pitch`` apart.

    Returns [] when not even one cut fits with ``enclosure`` on each side.
    ``align="start"`` packs the row against ``lo + enclosure`` instead of
    centring it (same cut count, different positions).
    """
    usable = (hi - enclosure) - (lo + enclosure)
    if usable < size - 1e-9:
        return []
    count = int((usable - size) / pitch + 1e-9) + 1
    span = (count - 1) * pitch + size
    if align == "start":
        start = lo + enclosure + size / 2.0
    else:
        start = (lo + hi - span) / 2.0 + size / 2.0
    return [start + i * pitch for i in range(count)]


def cut_grid(cell, layout, layer, box, pitch, enclosure, size, align="center"):
    """Fill micron ``box`` with a grid of ``size`` cuts; returns the count."""
    xs = _grid(box.left, box.right, size, pitch, enclosure, align)
    ys = _grid(box.bottom, box.top, size, pitch, enclosure, align)
    half = size / 2.0
    for x in xs:
        for y in ys:
            cell.shapes(layout.layer(*layer)).insert(
                pya.DBox(x - half, y - half, x + half, y + half).to_itype(layout.dbu)
            )
    return len(xs) * len(ys)


def guard_ring(layout, cell, inner, *, arm_w, comp_layer, implant_layer,
               implant_enc, cont_layer, cont_pitch, cont_size, cont_enc,
               extra_layers=(), well=None, align="center", corner_inset=None):
    """Annular tap ring around micron box ``inner``, with contacts on each arm.

    Draws COMP (plus every layer in ``extra_layers``) on the ring, the implant
    ``implant_enc`` outside and inside it, and optionally ``well=(layer, enc)``
    as a filled box enclosing the ring. Each arm gets a centred grid of
    contacts (``align`` as in ``_grid``); the horizontal arms are pulled
    ``corner_inset`` (default a whole ``cont_pitch``) clear of the vertical
    ones at each end, because two independently placed grids otherwise put
    their corner cuts closer than CO.2b allows.

    ``_fail``s if any arm has no room for a contact. Returns ``(inner, outer)``.
    """
    outer = inner.enlarged(arm_w, arm_w)
    ring = ring_region(layout, outer, inner)
    for layer in (comp_layer, *extra_layers):
        cell.shapes(layout.layer(*layer)).insert(ring.dup())
    cell.shapes(layout.layer(*implant_layer)).insert(ring_region(
        layout,
        outer.enlarged(implant_enc, implant_enc),
        inner.enlarged(-implant_enc, -implant_enc),
    ))
    if well is not None:
        well_layer, well_enc = well
        cell.shapes(layout.layer(*well_layer)).insert(
            outer.enlarged(well_enc, well_enc).to_itype(layout.dbu)
        )

    if corner_inset is None:
        corner_inset = cont_pitch
    arms = (
        pya.DBox(outer.left, outer.bottom, inner.left, outer.top),
        pya.DBox(inner.right, outer.bottom, outer.right, outer.top),
        pya.DBox(inner.left + corner_inset, inner.top,
                 inner.right - corner_inset, outer.top),
        pya.DBox(inner.left + corner_inset, outer.bottom,
                 inner.right - corner_inset, inner.bottom),
    )
    for arm in arms:
        if not cut_grid(cell, layout, cont_layer, arm, cont_pitch, cont_enc,
                         cont_size, align):
            _fail("no contacts fitted in one of the guard-ring arms")
    return inner, outer
