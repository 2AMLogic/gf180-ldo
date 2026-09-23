"""Poly-resistor flavour coexistence vehicle (issue #312, DR-0036).

Run as ``klayout -b -r layout/poly_flavour/gen_gds.py -rd out=<gds> -rd pdk=<variant dir>``
(``layout/poly_flavour/run.sh`` does this for you).

Draws three unconnected resistors in one top cell, ``TOP``, from the PDK's own
KLayout PCells, all 1 um wide by 10 um long:

=====  ==============================  ==================================
Pins   PCell                           Netlist device it can extract as
=====  ==============================  ==================================
A / B  ``ppolyf_u_high_Rs_resistor``   ``ppolyf_u_1k`` / ``_2k`` / ``_3k``
                                       -- whichever ``-rd poly_res=`` names
E / F  ``ppolyf_u_high_Rs_resistor``   the same -- a second, identical
                                       H-Res strip
C / D  ``ppolyf_u_resistor``           ``ppolyf_u`` (no RESISTOR mark;
                                       extracted unconditionally)
=====  ==============================  ==================================

It answers both halves of DR-0036's premise: (1) two identical H-Res strips
cannot be named as two different flavours under ANY ``poly_res`` setting
(issue #312's finding, re-derived), and (2) a plain ``ppolyf_u`` device shares
a die with the H-Res strips under EITHER setting.
The substrate (``VSS``) needs no label -- the LVS deck names it via
``lvs_sub``. Terminal labels go on the two metal1 straps that land on poly2,
exactly as ``layout/passives/gen_gds.py`` does for its single resistor.
"""

import os
import sys

import pya  # noqa: F401  (provided by the KLayout interpreter)

L_POLY2 = (30, 0)
L_METAL1 = (34, 0)
L_METAL1_LABEL = (34, 10)
DBU_UM = 0.001
PDK_OPTION = "D"
GAP_UM = 20.0

DEVICES = (
    # (PCell, params, wrapper cell, left pin, right pin)
    (
        "ppolyf_u_high_Rs_resistor",
        {"l": 1.0, "w": 10.0, "volt": "3.3V", "deepnwell": False, "pcmpgr": False},
        "HRES",
        "A",
        "B",
    ),
    (
        "ppolyf_u_high_Rs_resistor",
        {"l": 1.0, "w": 10.0, "volt": "3.3V", "deepnwell": False, "pcmpgr": False},
        "HRES2",
        "E",
        "F",
    ),
    (
        "ppolyf_u_resistor",
        {"l": 1.0, "w": 10.0, "deepnwell": False, "pcmpgr": False},
        "PPOLY",
        "C",
        "D",
    ),
)


def _fail(message):
    print(f"gen_gds.py: {message}", file=sys.stderr)
    raise SystemExit(f"gen_gds.py: {message}")


def _rd(name):
    value = globals().get(name)
    if value is None:
        _fail(f"missing required switch -rd {name}=...")
    return value


def _device(layout, library, pcell, params, wrapper_name, left, right):
    device = layout.create_cell(pcell, library, dict(params))
    if device is None:
        _fail(f"the PDK's {pcell!r} PCell rejected {params!r}")
    wrapper = layout.create_cell(wrapper_name)
    wrapper.insert(pya.CellInstArray(device.cell_index(), pya.Trans()))
    wrapper.flatten(-1, True)
    poly = pya.Region(wrapper.begin_shapes_rec(layout.layer(*L_POLY2))).merged()
    metal1 = pya.Region(wrapper.begin_shapes_rec(layout.layer(*L_METAL1))).merged()
    straps = sorted(
        (s for s in metal1.each() if not pya.Region(s).and_(poly).is_empty()),
        key=lambda p: p.bbox().left,
    )
    if len(straps) != 2:
        _fail(f"{pcell}: expected 2 metal1 straps on poly2, got {len(straps)}")
    for strap, name in zip(straps, (left, right)):
        wrapper.shapes(layout.layer(*L_METAL1_LABEL)).insert(
            pya.Text(name, pya.Trans(strap.bbox().center()))
        )
    return wrapper


def build(out_path, pdk_path):
    macros = os.path.join(pdk_path, "libs.tech", "klayout", "tech", "pymacros")
    if not os.path.isdir(macros):
        _fail(f"no PCell library at {macros}")
    sys.path.insert(0, macros)
    os.environ["GF_PDK_OPTION"] = PDK_OPTION
    from klayout_api_cells import gf180mcu_klayoutapi  # noqa: E402

    gf180mcu_klayoutapi()
    library = "gf180mcu_klayoutapi"

    layout = pya.Layout()
    layout.dbu = DBU_UM
    top = layout.create_cell("TOP")
    cursor = 0.0
    for pcell, params, wrapper, left, right in DEVICES:
        cell = _device(layout, library, pcell, params, wrapper, left, right)
        box = cell.dbbox()
        shift = pya.DTrans(pya.DVector(cursor - box.left, -box.bottom))
        top.insert(pya.CellInstArray(cell.cell_index(), shift.to_itype(layout.dbu)))
        cursor += box.width() + GAP_UM
    top.flatten(-1, True)
    layout.write(out_path)
    print(f"gen_gds.py: wrote {out_path}")


build(_rd("out"), _rd("pdk"))
