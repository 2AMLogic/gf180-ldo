"""Write the ERC negative control's disposable layout copy (issue #785).

Run under KLayout's interpreter, never as a plain script::

    klayout -b -r layout/erc/mutate_gds.py \
        -rd cell=pass_array -rd src=<committed gds> -rd dst=<mutated gds>

The ERC counterpart of drclvs.py's LVS negative controls: a copy of the
committed layout with the declared tie's connection deliberately severed,
run by drclvs.py against the **intact** spec and required to produce
``erc.missing_tie`` on the intended tie. The mutation is chosen so the
severed thing is the *path*, not the parts: the labelled supply metal and
the tap region itself are left in the stream, exactly the "a run that
cannot fail is not evidence" shape the LVS controls already have.

What is deleted, per cell (the tap region is the same region
``layout/erc/gen_spec.py`` declares as the tie's tap sites, so control and
declaration cannot drift apart):

- ``pass_array`` -- every via1 cut landing on the n+ guard ring (COMP &
  NPLUS): the landings between the ring's metal1 and the VIN straps' metal2
  on both ring arms. The ring, its contacts and the whole VIN stack stay;
  the n-well's tap simply no longer reaches VIN.
- ``divider`` -- every contact cut landing on the p+ substrate-tap ring
  (COMP). The ring's diffusion and its labelled metal1 VSS ring stay; the
  substrate tap simply no longer reaches VSS.
"""

import os
import sys

import pya  # noqa: F401  (provided by the KLayout interpreter)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gen_gds_common import (  # noqa: E402
    L_COMP,
    L_CONTACT,
    L_NPLUS,
    L_VIA1,
    _fail,
    _rd,
    display_path,
)

# (cut layer, tap region implant narrowing): the layer whose shapes are
# deleted, and for pass_array the implant that tells the ring's COMP apart
# from the pfets' source/drain diffusion (the divider's COMP *is* only the
# ring -- gen_spec.py asserts that on every spec emission).
_MUTATIONS = {
    "pass_array": {"cut": L_VIA1, "narrow": [L_NPLUS], "cut_name": "via1"},
    "divider": {"cut": L_CONTACT, "narrow": [], "cut_name": "contact"},
}


def build(cell, gds_src, gds_dst):
    if cell not in _MUTATIONS:
        _fail(
            f"unknown cell {cell!r}; mutate_gds.py serves {sorted(_MUTATIONS)}"
        )
    mutation = _MUTATIONS[cell]
    layout = pya.Layout()
    layout.read(gds_src)
    top = layout.top_cell()

    def merged(pair):
        return pya.Region(
            top.begin_shapes_rec(layout.layer(*pair))
        ).merged()

    tap = merged(L_COMP)
    for narrowing in mutation["narrow"]:
        tap = tap & merged(narrowing)
    if tap.is_empty():
        _fail(
            f"{cell}: the declared tie's tap region is empty in this GDS -- "
            "the mutation would remove nothing and the control would be "
            "testing a tie the layout does not draw"
        )

    cut_index = layout.layer(*mutation["cut"])
    removed = 0
    for shape in top.shapes(cut_index).each():
        if shape.is_text() or shape.polygon is None:
            continue
        if not tap.overlapping(pya.Region(shape.polygon)).is_empty():
            shape.delete()
            removed += 1
    if removed == 0:
        _fail(
            f"{cell}: no {mutation['cut_name']} shape landed on the tie's "
            "tap region -- the control has nothing to sever and any clean "
            "run of it would be vacuous"
        )
    survivors = 0
    for shape in top.shapes(cut_index).each():
        if shape.is_text() or shape.polygon is None:
            continue
        if not tap.overlapping(pya.Region(shape.polygon)).is_empty():
            survivors += 1
    if survivors:
        _fail(
            f"{cell}: {survivors} {mutation['cut_name']} shape(s) still land "
            "on the tie's tap region after the mutation"
        )
    layout.write(gds_dst)
    print(
        f"mutate_gds.py: {cell}: removed {removed} {mutation['cut_name']} "
        f"shape(s) landing on the tie's tap region -> {display_path(gds_dst)}"
    )


build(_rd("cell"), _rd("src"), _rd("dst"))
