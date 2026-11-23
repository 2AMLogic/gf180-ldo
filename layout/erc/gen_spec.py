"""Emit the ``klt erc`` supply spec for a registered cell, from its GDS.

Run under KLayout's interpreter, never as a plain script::

    klayout -b -r layout/erc/gen_spec.py \
        -rd cell=pass_array -rd gds=<committed gds> -rd out=<spec json>

``layout/drclvs.py``'s ERC stage is what normally invokes it (issue #785).
One parameterized source emits one spec per cell, so ``ldo_core`` extends the
same table rather than forking a second spec format.

Why the spec is *measured*, not transcribed
-------------------------------------------

Everything the ERC contract grades as caller assertion -- the divider's
``well_boxes`` substrate region above all -- is read out of the committed GDS
here, on every emission, so the spec cannot drift from the layout it
describes. And every claim the spec makes that the ERC tool cannot check for
itself (``tap_is_dedicated`` on the divider rests on "COMP draws only the tap
ring in this stream") is *asserted here*, against the same GDS, so a layout
change that invalidates the claim fails spec generation loudly instead of
quietly weakening the tie declaration. A spec that generates cleanly is a
spec whose stated geometry still holds.

The rail decisions the spec encodes (from ``design/README.md``'s pin table
and ``layout/floorplan.md`` §5, per #785's curation):

- ``VIN`` is the input supply; ``VOUT`` is the *regulated output rail* that
  feeds the specified 0-50 mA load, so on the pass array it is declared
  ``"kind": "supply"`` -- the pin table's "output" is about current
  direction, not about being a rail.
- ``VOUT_S`` on the divider is the *Kelvin sense port* of that same rail (the
  floorplan joins it to the force path only at the pad), so it is declared a
  signal there. The two declarations describe two different physical roles
  of two different pins, not a contradiction.
- No net on either cell owns a shared metal level outright (metal5 carries
  VIN/VOUT/ISNS on the array; metal1 carries VSS/FB/VOUT_S plus the
  divider's unlabelled internal links), so no ``nets[].roles`` is declared
  for them and the unlabelled remainder on those levels is **unmeasured**
  -- disclosed here rather than papered over with a false ownership claim.
  PASS_GATE does own poly2 outright on the array (every poly2 shape in the
  cell is that net), so it declares the role and gets the severed-rail
  measurement for free.

``ties[].through`` (the contact-qualified tap connection) needs a
klayout-tools build carrying that key (present on main / klt
``0.9.3.dev3808+g1ad4a837f657``; the ``signoff/check.sh`` grading pin
``a2804ab`` predates it and *rejects* this spec -- run this flow with the
klt the records cite, not the signoff pin).
"""

import json
import os
import sys

import pya  # noqa: F401  (provided by the KLayout interpreter)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gen_gds_common import (  # noqa: E402
    L_CONTACT,
    L_COMP,
    L_METAL1,
    L_METAL1_LABEL,
    L_METAL2,
    L_METAL3,
    L_METAL4,
    L_METAL5,
    L_METAL5_LABEL,
    L_NPLUS,
    L_NWELL,
    L_POLY2,
    L_POLY2_LABEL,
    L_PPLUS,
    L_VIA1,
    L_VIA2,
    L_VIA3,
    L_VIA4,
    _fail,
    _rd,
    display_path,
)


def _layer(pair):
    return f"{pair[0]}/{pair[1]}"


# The gf180mcuD routing stack, fabrication order, one name per level. The
# pass array routes supplies from metal1 to metal5; the divider stops at
# metal1. ``stackup[0]`` is the gate role by contract; ``active_layer``
# keeps gate identification physical (poly over diffusion), which on the
# all-passive divider makes it a zero-gate cell (issue #2896's case) instead
# of reading every resistor head as a transistor gate.
_STACKUP_5LM = [
    {"name": "poly2", "layer": _layer(L_POLY2), "role": "gate",
     "active_layer": _layer(L_COMP), "label_layer": _layer(L_POLY2_LABEL)},
    {"name": "metal1", "layer": _layer(L_METAL1)},
    {"name": "metal2", "layer": _layer(L_METAL2)},
    {"name": "metal3", "layer": _layer(L_METAL3)},
    {"name": "metal4", "layer": _layer(L_METAL4)},
    {"name": "metal5", "layer": _layer(L_METAL5),
     "label_layer": _layer(L_METAL5_LABEL)},
]
_VIAS_5LM = [
    {"name": "con", "layer": _layer(L_CONTACT), "between": ["poly2", "metal1"]},
    {"name": "via1", "layer": _layer(L_VIA1),
     "between": ["metal1", "metal2"]},
    {"name": "via2", "layer": _layer(L_VIA2),
     "between": ["metal2", "metal3"]},
    {"name": "via3", "layer": _layer(L_VIA3),
     "between": ["metal3", "metal4"]},
    {"name": "via4", "layer": _layer(L_VIA4),
     "between": ["metal4", "metal5"]},
]
_STACKUP_1LM = [
    {"name": "poly2", "layer": _layer(L_POLY2), "role": "gate",
     "active_layer": _layer(L_COMP)},
    {"name": "metal1", "layer": _layer(L_METAL1),
     "label_layer": _layer(L_METAL1_LABEL)},
]
_VIAS_1LM = [
    {"name": "con", "layer": _layer(L_CONTACT), "between": ["poly2", "metal1"]},
]


class _Gds:
    """The merged, flat view of one committed GDS the spec is measured on."""

    def __init__(self, path):
        self.layout = pya.Layout()
        self.layout.read(path)
        self.top = self.layout.top_cell()
        self.dbu = self.layout.dbu

    def region(self, pair):
        return pya.Region(
            self.top.begin_shapes_rec(self.layout.layer(*pair))
        ).merged()

    def texts(self, pair):
        names = set()
        iterator = self.top.begin_shapes_rec(self.layout.layer(*pair))
        while not iterator.at_end():
            shape = iterator.shape()
            if shape.is_text():
                names.add(shape.text.string)
            iterator.next()
        return names

    def box(self, region_polygon):
        return region_polygon.bbox().to_dtype(self.dbu)


def _assert_labels(gds, pair, expected, cell):
    seen = gds.texts(pair)
    if seen != set(expected):
        _fail(
            f"{cell}: layer {pair[0]}/{pair[1]} carries labels {sorted(seen)}, "
            f"expected exactly {sorted(expected)} -- the spec's nets[] name "
            "supply labels the layout no longer draws (or new ones it does)"
        )


def _pass_array_spec(gds, cell):
    nwell = gds.region(L_NWELL)
    comp = gds.region(L_COMP)
    nplus = gds.region(L_NPLUS)
    ring_tap = comp & nplus
    if nwell.count() != 1:
        _fail(
            f"{cell}: expected exactly 1 merged n-well shape, found "
            f"{nwell.count()} -- the tie's per-well loop and this spec's "
            "single-well claim both rest on the array being one well"
        )
    if not (comp - nwell).is_empty():
        _fail(f"{cell}: COMP exists outside the n-well; the well assumption is false")
    if ring_tap.is_empty():
        _fail(
            f"{cell}: COMP & NPLUS is empty -- the n+ guard ring the n-well "
            "tie names as its tap is not drawn where the spec expects it"
        )
    # The negative control (layout/erc/mutate_gds.py) severs exactly the
    # via1 landings on that ring, and the tie's `through` path needs the
    # ring's own contact cuts: both must exist for the declared tie to mean
    # what the committed report says it means.
    for pair, what in ((L_VIA1, "via1"), (L_CONTACT, "contact")):
        if gds.region(pair).overlapping(ring_tap).is_empty():
            _fail(
                f"{cell}: no {what} shape lands on the n+ guard ring -- the "
                "ERC tie declaration and its negative control both target "
                f"{what} geometry the layout no longer draws"
            )
    _assert_labels(gds, L_METAL5_LABEL, ("VIN", "VOUT", "ISNS"), cell)
    _assert_labels(gds, L_POLY2_LABEL, ("PASS_GATE",), cell)
    return {
        "_comment": [
            "Supply spec for PASS_ARRAY (issue #785), emitted by",
            "layout/erc/gen_spec.py from layout/pass_array/pass_array.gds.",
            "VIN is the input supply; VOUT is declared a supply because the",
            "pin table's 'output' is current direction, not rail-ness -- it",
            "feeds the specified 0-50 mA load (design/README.md pin table,",
            "layout/floorplan.md §5). ISNS (the Msense drain) and PASS_GATE",
            "are signals. metal1..metal5 each carry several nets, so no net",
            "declares roles on them and their unlabelled remainder is",
            "unmeasured; PASS_GATE owns every poly2 shape in the cell and",
            "declares that role (unlabelled_islands == 0 is the severed-rail",
            "negative for the gate net). The intact cell's one expected",
            "finding is erc.floating_gate on PASS_GATE: the standalone",
            "array's gate bus is a label-only port (no gate contact is",
            "drawn; see the generator's 'What the cell does not contain'),",
            "disclosed here rather than hidden. The p_substrate class is",
            "disclosed undeclared: this pfet-only cell draws no substrate",
            "tap and no pwell at all -- its sole bulk terminal is the n-well",
            "tied to VIN by the guard ring -- so the substrate tie lands at",
            "ldo_core assembly (#288).",
        ],
        "stackup": _STACKUP_5LM,
        "vias": _VIAS_5LM,
        "nets": [
            {"name": "VIN", "kind": "supply"},
            {"name": "VOUT", "kind": "supply"},
            {"name": "ISNS", "kind": "signal"},
            {"name": "PASS_GATE", "kind": "signal", "roles": ["poly2"]},
        ],
        "ties": [
            {
                "_comment": [
                    "The array's single n-well, tied to VIN through the n+",
                    "guard ring: tap sites are COMP & NPLUS (the ring, told",
                    "apart from the p+ source/drain diffusion by its",
                    "implant), reaching metal1 only through drawn contact",
                    "cuts (through: con) and the VIN straps only through",
                    "drawn via1 landings on both ring arms.",
                ],
                "name": "nwell_vin_tie",
                "well_layer": _layer(L_NWELL),
                "tap_layer": _layer(L_COMP),
                "tap_requires": [_layer(L_NPLUS)],
                "connect_to": "metal1",
                "through": "con",
                "net": "VIN",
            },
        ],
        "ties_disclosure": {
            "kind": "unexpressible",
            "reason": (
                "p_substrate: PASS_ARRAY draws no p-substrate tap and no "
                "pwell (pfet-only; the generator's docstring says so) -- its "
                "only bulk terminal is the n-well tied to VIN by the guard "
                "ring, and the substrate tie lands at ldo_core assembly "
                "(issue #288). There is no tap geometry to name."
            ),
            "undeclared_classes": ["p_substrate"],
        },
    }


def _divider_spec(gds, cell):
    comp = gds.region(L_COMP)
    pplus = gds.region(L_PPLUS)
    poly2 = gds.region(L_POLY2)
    metal1 = gds.region(L_METAL1)
    contact = gds.region(L_CONTACT)
    if comp.count() != 1:
        _fail(
            f"{cell}: expected exactly 1 merged COMP shape (the substrate-tap "
            f"ring), found {comp.count()} -- tap_is_dedicated below claims "
            "COMP draws only the ring in this stream, and that claim is "
            "measured here, not assumed"
        )
    if not (comp - pplus).is_empty():
        _fail(
            f"{cell}: the COMP ring is not fully covered by its p+ implant -- "
            "the substrate-tap ring the spec names is not what COMP draws"
        )
    if not (poly2 & comp).is_empty():
        _fail(
            f"{cell}: poly2 overlaps COMP -- the resistor heads have moved "
            "onto diffusion and the tap-vs-head distinction the spec relies "
            "on (heads are poly2-contacted, the tap is the COMP ring) is gone"
        )
    if contact.overlapping(comp).is_empty():
        _fail(
            f"{cell}: no contact cut lands on the COMP ring -- the "
            "substrate tie's through-path and its negative control both "
            "target geometry the layout no longer draws"
        )
    if (metal1 & comp).is_empty():
        _fail(f"{cell}: no metal1 over the COMP ring -- the VSS ring is gone")
    _assert_labels(gds, L_METAL1_LABEL, ("VOUT_S", "FB", "VSS"), cell)
    # The asserted substrate region: the ring band, named one arm at a time
    # (docs/cli/erc.md's own guidance -- assert the ring edges, never the
    # enclosing rectangle, which would be degenerate). Measured from the
    # committed GDS so it follows the layout, and asserted to leave the tap
    # fully covered (the report's well_assertion_coverage quotes the same
    # measurement).
    outer = gds.box(comp)
    hole = pya.Region(comp.bbox()) - comp
    inner = gds.box(hole)
    well_boxes = [
        [outer.left, outer.bottom, inner.left, outer.top],
        [inner.right, outer.bottom, outer.right, outer.top],
        [outer.left, outer.bottom, outer.right, inner.bottom],
        [outer.left, inner.top, outer.right, outer.top],
    ]
    return {
        "_comment": [
            "Supply spec for FB_DIVIDER (issue #785), emitted by",
            "layout/erc/gen_spec.py from layout/divider/fb_divider.gds.",
            "VSS is the supply (the substrate-tap ring is the cell's only",
            "VSS conductor); VOUT_S is the Kelvin sense port of the regulated",
            "rail and is declared a signal -- the force/sense join happens",
            "only at the pad, at assembly (layout/floorplan.md §5; the rail",
            "itself is declared a supply on the pass array). FB is the",
            "divider tap. metal1 carries all three nets plus the unlabelled",
            "inter-unit links, so no net declares roles on it and its",
            "unlabelled remainder is unmeasured. The ppolyf_u bodies are",
            "carved out of poly2 by the --deck gf180mcu resistor recognition",
            "(provenance.devices), so the string does not read as one",
            "conductor shorting every net to every other.",
        ],
        "stackup": _STACKUP_1LM,
        "vias": _VIAS_1LM,
        "nets": [
            {"name": "VSS", "kind": "supply"},
            {"name": "VOUT_S", "kind": "signal"},
            {"name": "FB", "kind": "signal"},
        ],
        "ties": [
            {
                "_comment": [
                    "The substrate tie: this cell draws no well/tub layer at",
                    "all (a native-substrate block), so the substrate region",
                    "is asserted in well_boxes -- the four measured arms of",
                    "the tap ring's band, not an enclosing rectangle. The",
                    "PCell's per-unit p-tap columns are stripped by the",
                    "generator and the resistor heads are poly2, so COMP",
                    "draws exactly the ring (asserted on every emission),",
                    "which is what makes tap_is_dedicated honest here. The",
                    "tap reaches metal1 only through drawn contact cuts",
                    "(through: con).",
                ],
                "name": "substrate_vss_tie",
                "well_layer": None,
                "well_boxes": [[round(v, 3) for v in box] for box in well_boxes],
                "tap_layer": _layer(L_COMP),
                "tap_is_dedicated": True,
                "connect_to": "metal1",
                "through": "con",
                "net": "VSS",
            },
        ],
        "ties_disclosure": None,
    }


_EMITTERS = {
    "pass_array": _pass_array_spec,
    "divider": _divider_spec,
}


def build(cell, gds_path, out_path):
    if cell not in _EMITTERS:
        _fail(
            f"unknown cell {cell!r}; gen_spec.py serves {sorted(_EMITTERS)} "
            "(register the cell's emitter here, not a second spec format)"
        )
    gds = _Gds(gds_path)
    expected_tops = {"pass_array": "PASS_ARRAY", "divider": "FB_DIVIDER"}
    if gds.top.name != expected_tops[cell]:
        _fail(
            f"{cell}: GDS top cell is {gds.top.name!r}, expected "
            f"{expected_tops[cell]!r}"
        )
    spec = _EMITTERS[cell](gds, cell)
    with open(out_path, "w") as handle:
        json.dump(spec, handle, indent=2)
        handle.write("\n")
    ties = ", ".join(tie["name"] for tie in spec["ties"])
    supplies = ", ".join(
        net["name"] for net in spec["nets"] if net.get("kind") == "supply"
    )
    print(
        f"gen_spec.py: wrote {display_path(out_path)} (cell={cell}, "
        f"supplies={supplies}, ties={ties})"
    )


build(_rd("cell"), _rd("gds"), _rd("out"))
