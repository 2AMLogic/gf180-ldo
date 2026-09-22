#!/usr/bin/env python3
"""Pre-layout core-area estimate for the LDO, computed from the committed netlists.

The numbers in `layout/floorplan.md` are produced by this script; it exists so
that the area estimate is re-derivable against the current `design/netlist/`
rather than being a hand-typed snapshot that goes stale the first time a device
is resized.

What it is
----------
A *drawn-device* area model. It computes the silicon each instantiated device
occupies (COMP for FETs, poly body plus contact heads for resistors, plate for
MIM capacitors), then reports the block subtotals that the floorplan's block
rectangles are budgeted against. It is not an extraction and it is not a
placement: routing channels, guard rings and inter-device spacing are applied by
the floorplan document as an explicit per-block packing efficiency, stated there
rather than buried here.

Every geometric constant below is a gf180mcu DRC rule, cited by its rule name as
it appears in the PDK's own KLayout deck
(`libs.tech/klayout/drc/rule_decks/`, gf180mcuD). Nothing here is a guess.

Usage
-----
    python3 layout/area_estimate.py              # the block table
    python3 layout/area_estimate.py --devices    # ... plus every device
    python3 layout/area_estimate.py --pass-width 4000   # what-if for #139
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# gf180mcu geometric constants (gf180mcuD KLayout DRC deck, 3.3 V devices)
# --------------------------------------------------------------------------

CO_SIZE = 0.22  # CO.1   min/max contact size
CO_TO_GATE = 0.15  # CO.7   space from COMP contact to Poly2 on COMP
CO_COMP_ENC = 0.07  # CO.4   COMP overlap of contact
DF_MAX_W = 100.0  # DF.2b  max COMP width (also the widest model bin, DR-0025)

# A contacted source/drain region shared between two adjacent gates, and the
# two outer source/drain regions that terminate the finger stack.
SD_SHARED = CO_TO_GATE + CO_SIZE + CO_TO_GATE  # 0.52 um
SD_END = CO_TO_GATE + CO_SIZE + CO_COMP_ENC  # 0.44 um

# Poly resistor, drawn as a metal-linked ladder of straight segments rather
# than a poly serpentine (a poly bend is a non-uniform-current region and a
# matching hazard). Per segment terminal: the contact plus PRES.7's 0.22 um
# salicide-block-to-contact clearance and the contact's own poly enclosure
# (CO.3, 0.07 um). The head does not have to be wider than a >= 0.8 um body
# (PRES.1), so the ladder pitch is set by PRES.2 alone.
RES_HEAD = 1.0  # per terminal, along the segment
RES_SPACE = 0.4  # PRES.2  min space between Poly2 resistors
RES_SEG_MAX = 100.0  # floorplan choice: longest drawn resistor segment

# MIM bottom plate must stand off any other Metal2 by MIM.1 (1.2 um); a single
# plate is capped at MIM.8b (10000 um^2).
MIM_KEEPOUT = 1.2
MIM_MAX_PLATE = 10_000.0

# Sheet resistances, magic tech file (`libs.tech/magic/gf180mcuD.tech`,
# `resist` section, milliohm per square -> ohm per square here).
RSH_M1_M4 = 0.090
RSH_M5 = 0.060

# MIM capacitor density, measured (`sim/devchar/CONCLUSIONS.md` §3).
MIM_FF_PER_UM2 = 1.990

# Poly resistor area per kilo-ohm at w = 1 um, measured
# (`sim/devchar/CONCLUSIONS.md` §2).
AREA_PER_KOHM = {
    "ppolyf_u_3k": 0.318,
    "ppolyf_u_2k": 0.477,
    "ppolyf_u_1k": 0.969,
    "ppolyf_u": 2.69,
}

NETLIST_DIR = Path(__file__).resolve().parent.parent / "design" / "netlist"

# Ratified area budget: "< 0.1 mm^2 total core area, pass FET included,
# excluding pads and sealring" (README.md, Area row).
AREA_BUDGET_UM2 = 100_000.0

# Packing efficiency: device footprint / occupied area. The remainder is guard
# rings, well taps, dummy devices and intra-block routing. Applied per device
# *kind*, because how much overhead a device carries is a property of the
# device, not of which subcircuit it happens to belong to. Justified in
# `layout/floorplan.md` §6.
PACKING = {
    "fet_small": 0.35,  # small-signal FETs: dummies, guard rings, dense routing
    "fet_pass": 0.70,  # one regular finger array under a solid metal stack
    "res": 0.75,  # ladder pitch is already in the footprint; links + dummies
    "mim": 0.90,  # MIM.1 keep-out is already in the footprint; via rows only
}

# Inter-block routing channels, the block-level guard/seal ring inside the
# core, and the Kelvin sense trunk that must not share the power path.
ROUTING_ALLOWANCE = 1.15

# Fraction of MIM footprint that can be stacked over a resistor field instead
# of costing its own core area. MIM plates live on Metal2/Metal3 (MIM option
# A, connected through Via2 only -- MIM.10), so poly below is free provided the
# resistor exits in Metal1 at the plate edge and the *low-impedance* node of
# the capacitor is assigned to the bottom plate so it shields what is under it.
MIM_STACK_FRACTION = 0.60

# Which subcircuit each device belongs to, for the block subtotals. Keyed by
# the `.subckt` name in the netlist; `ldo_core` devices that are really the
# feedback divider are split out by instance name below.
DIVIDER_INSTANCES = {"Rtop", "Rbot", "XCff"}

# Feedback divider, as planned in `layout/floorplan.md` §4.1: a series string
# of identical unit resistors (DR-0003 requires the string so a metal-mask
# derivative can re-tap it), drawn 2 um wide rather than the 1 um the
# accuracy budget assumed, inside a full dummy ring.
DIV_UNIT_KOHM = 50.0
DIV_UNIT_W = 2.0
DIV_UNITS_TOP = 6  # 6 x 50k = 300k
DIV_UNITS_BOT = 12  # 12 x 50k = 600k
DIV_DUMMIES = 2  # one dummy strip at each end of the interdigitated row


@dataclass
class Device:
    name: str
    kind: str  # "fet" | "res" | "cap"
    model: str
    block: str
    area_um2: float
    note: str = ""


@dataclass
class Block:
    name: str
    devices: list[Device] = field(default_factory=list)

    @property
    def area(self) -> float:
        return sum(d.area_um2 for d in self.devices)


def _val(text: str, key: str) -> float | None:
    """Pull `key=<number><unit>` out of a SPICE instance line."""
    m = re.search(rf"\b{key}\s*=\s*'?([0-9.eE+-]+)\s*([a-zA-Z]?)", text)
    if not m:
        return None
    num = float(m.group(1))
    suffix = m.group(2).lower()
    scale = {"": 1.0, "u": 1e-6, "n": 1e-9, "p": 1e-12, "k": 1e3, "m": 1e-3}
    return num * scale.get(suffix, 1.0)


def fet_area(w_m: float, l_m: float, nf: int, mult: int) -> float:
    """Drawn COMP area of a multi-finger MOS, in um^2.

    Finger width Wf = W/nf; the stack is nf gates of length L separated by
    shared contacted source/drain regions, terminated by two end regions.
    Note that to first order the result is W * (L + SD_SHARED) and therefore
    almost independent of how the width is segmented -- segmentation is close
    to free in area and is chosen on EM / IR / matching grounds instead.
    """
    w_um, l_um = w_m * 1e6, l_m * 1e6
    wf = w_um / nf
    comp_len = nf * l_um + (nf - 1) * SD_SHARED + 2 * SD_END
    return wf * comp_len * mult


def res_field(w_um: float, l_um: float, mult: int) -> float:
    """Footprint of a poly resistor drawn as a metal-linked segment ladder."""
    n_seg = max(1, -(-l_um // RES_SEG_MAX))  # ceil
    seg_len = l_um / n_seg
    return n_seg * (seg_len + 2 * RES_HEAD) * (w_um + RES_SPACE) * mult


def ideal_res_field(
    r_ohm: float, model: str = "ppolyf_u_3k", width_um: float = 1.0
) -> float:
    """Footprint an ideal-resistor netlist value takes once drawn in `model`.

    `design/netlist/` still carries the feedback divider and the soft-start
    transconductor loads as ideal resistors. They have to become real devices
    at layout, so the floorplan has to budget for them.
    """
    kohm = r_ohm / 1e3
    body_len = AREA_PER_KOHM[model] * kohm  # um of length at w = 1 um
    return res_field(width_um, body_len * width_um, 1)


def divider_field() -> tuple[float, float]:
    """Footprint and 3-sigma output error of the planned divider unit array.

    Returns ``(footprint_um2, sigma3_mV)``. The mismatch arithmetic is #9's
    (`design/error_amp.md` §3.2) re-run on the planned geometry: this PDK
    publishes no local mismatch for the high-sheet flavours, so the disabled
    ``ppolyf_u`` card coefficient ``par_r = 0.021`` is used as the same proxy
    #9 sanctions, in the card's own ``sigma = 0.7071 * par_r * 1um / sqrt(A)``
    form. It is an assumption, not a simulated result, and cannot become one
    against these models -- which is exactly why the layout discipline below
    is the only mitigation available.
    """
    length_per_kohm = AREA_PER_KOHM["ppolyf_u_3k"] * DIV_UNIT_W  # at DIV_UNIT_W
    unit_len = length_per_kohm * DIV_UNIT_KOHM
    positions = DIV_UNITS_TOP + DIV_UNITS_BOT + DIV_DUMMIES
    footprint = positions * (unit_len + 2 * RES_HEAD) * (DIV_UNIT_W + RES_SPACE)

    unit_area = unit_len * DIV_UNIT_W
    sigma_unit = 0.7071 * 0.021 / (unit_area**0.5)  # fractional, 1 sigma
    sigma_top = sigma_unit / DIV_UNITS_TOP**0.5
    sigma_bot = sigma_unit / DIV_UNITS_BOT**0.5
    beta_c = DIV_UNITS_TOP / (DIV_UNITS_TOP + DIV_UNITS_BOT)  # 1 - beta = 1/3
    sigma_vout = beta_c * (sigma_top**2 + sigma_bot**2) ** 0.5 * 1800.0  # mV
    return footprint, 3 * sigma_vout


def mim_field(cw_um: float, cl_um: float, mult: int) -> float:
    """MIM footprint including MIM.1's bottom-plate keep-out to other Metal2."""
    return (cw_um + 2 * MIM_KEEPOUT) * (cl_um + 2 * MIM_KEEPOUT) * mult


def parse(path: Path, pass_width_um: float | None) -> list[Device]:
    """Parse `ldo_core.spice`, which carries every `.subckt` the block uses.

    The per-subcircuit files under `design/netlist/` are the *same* definitions
    exported standalone, so only the top-level file is read -- reading both
    would double-count every amplifier, current-limit and soft-start device.
    """
    devices: list[Device] = []
    text = path.read_text()
    # Join continuation lines.
    text = re.sub(r"\n\+", " ", text)
    block = path.stem
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith(".subckt"):
            block = line.split()[1]
            continue
        if line.lower().startswith(".ends"):
            block = path.stem
            continue
        if not line or line.startswith(("*", ".", "V", "F", "E", "G", "I")):
            continue
        name = line.split()[0]
        blk = "divider" if name in DIVIDER_INSTANCES else block

        if "fet_03v3" in line:
            model = "pfet_03v3" if "pfet_03v3" in line else "nfet_03v3"
            w = _val(line, "W")
            l = _val(line, "L")
            nf = int(_val(line, "nf") or 1)
            m = int(_val(line, "m") or 1)
            note = ""
            if name == "XMpass" and pass_width_um is not None:
                # Hold the per-finger width fixed and scale the finger count,
                # which is what re-sizing the array actually means physically.
                wf = (w * 1e6) / nf
                w = pass_width_um * 1e-6
                nf = max(1, round(pass_width_um / wf))
                note = f"what-if: W={pass_width_um:g}u, nf={nf} at Wf={wf:g}u"
            if w is None or l is None:
                continue
            devices.append(
                Device(name, "fet", model, blk, fet_area(w, l, nf, m), note)
            )
        elif "polyf_u" in line or "nplus_u" in line or "pplus_u" in line:
            model = next(
                (t for t in line.split() if "polyf" in t or "plus_u" in t), "res"
            )
            rw = _val(line, "r_width")
            rl = _val(line, "r_length")
            m = int(_val(line, "m") or 1)
            if rw is None or rl is None:
                continue
            devices.append(
                Device(name, "res", model, blk, res_field(rw * 1e6, rl * 1e6, m))
            )
        elif "cap_mim" in line:
            cw = _val(line, "c_width")
            cl = _val(line, "c_length")
            m = int(_val(line, "m") or 1)
            if cw is None or cl is None:
                continue
            cw, cl = cw * 1e6, cl * 1e6
            plate = cw * cl
            cap_ff = plate * MIM_FF_PER_UM2
            note = f"{cap_ff / 1000:.2f} pF"
            if plate > MIM_MAX_PLATE:
                note += f"  ** exceeds MIM.8b {MIM_MAX_PLATE:.0f} um^2, must be split"
            devices.append(
                Device(name, "cap", "cap_mim_2f0", blk, mim_field(cw, cl, m), note)
            )
        elif re.match(r"^R[A-Za-z0-9_]*\s", line):
            # Ideal resistor still in the netlist -- must be drawn at layout.
            toks = line.split()
            raw = toks[3]
            mult = {"k": 1e3, "meg": 1e6, "m": 1e-3}
            mm = re.match(r"([0-9.]+)([a-zA-Z]*)", raw)
            if not mm:
                continue
            r_ohm = float(mm.group(1)) * mult.get(mm.group(2).lower(), 1.0)
            devices.append(
                Device(
                    name,
                    "res",
                    "ppolyf_u_3k (ideal in netlist)",
                    blk,
                    ideal_res_field(r_ohm),
                    f"{r_ohm / 1e3:g} kohm, ideal today",
                )
            )
    return devices


def collect(pass_width_um: float | None = None) -> list[Device]:
    """Every device in the block, with `XMpass`/`XMen`/`XMsense` re-homed.

    The three of them are netlisted in two different subcircuits but are one
    physical array: `XMsense` is the current-limit replica and has to sit
    *inside* the pass array to track it (floorplan.md §3.2).
    """
    devices = parse(NETLIST_DIR / "ldo_core.spice", pass_width_um)
    for d in devices:
        if d.name in {"XMpass", "XMen", "XMsense"}:
            d.block = "pass_array"

    # `Rtop`/`Rbot` are ideal resistors in the netlist. Replace the pair with
    # the planned unit-resistor array, which is what actually gets drawn.
    devices = [d for d in devices if d.name not in {"Rtop", "Rbot"}]
    field, sigma3 = divider_field()
    devices.append(
        Device(
            "Rdiv[array]",
            "res",
            "ppolyf_u_3k unit array",
            "divider",
            field,
            f"{DIV_UNITS_TOP}+{DIV_UNITS_BOT} x {DIV_UNIT_KOHM:g}k at w="
            f"{DIV_UNIT_W:g}u + {DIV_DUMMIES} dummies; "
            f"mismatch {sigma3:.2f} mV (3 sigma)",
        )
    )
    return devices


def summarize(devices: list[Device]) -> dict[str, float]:
    """Roll the device footprints up into the core-area estimate."""
    kinds = {"fet_small": 0.0, "fet_pass": 0.0, "res": 0.0, "mim": 0.0}
    for d in devices:
        if d.kind == "fet":
            kinds["fet_pass" if d.block == "pass_array" else "fet_small"] += d.area_um2
        elif d.kind == "res":
            kinds["res"] += d.area_um2
        else:
            kinds["mim"] += d.area_um2
    occupied = sum(area / PACKING[k] for k, area in kinds.items())
    stackable = min(kinds["mim"] / PACKING["mim"], kinds["res"] / PACKING["res"])
    credit = stackable * MIM_STACK_FRACTION
    core = (occupied - credit) * ROUTING_ALLOWANCE
    return {
        **kinds,
        "footprint": sum(kinds.values()),
        "occupied": occupied,
        "mim_stack_credit": credit,
        "core_um2": core,
        "budget_fraction": core / AREA_BUDGET_UM2,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--devices", action="store_true", help="list every device")
    ap.add_argument(
        "--pass-width",
        type=float,
        default=None,
        metavar="UM",
        help="what-if pass-device total width in um (see issue #139)",
    )
    args = ap.parse_args()

    devices = collect(args.pass_width)

    blocks: dict[str, Block] = {}
    for d in devices:
        blocks.setdefault(d.block, Block(d.block)).devices.append(d)

    if args.devices:
        print(f"{'device':<16}{'block':<16}{'model':<32}{'area um2':>10}  note")
        for d in sorted(devices, key=lambda x: -x.area_um2):
            print(
                f"{d.name:<16}{d.block:<16}{d.model:<32}{d.area_um2:>10.1f}  {d.note}"
            )
        print()

    hdr = f"{'block':<16}{'FET':>10}{'res':>10}{'MIM':>10}{'footprint':>12}"
    print(hdr)
    print("-" * len(hdr))
    for name in sorted(blocks):
        b = blocks[name]
        fets = sum(d.area_um2 for d in b.devices if d.kind == "fet")
        res = sum(d.area_um2 for d in b.devices if d.kind == "res")
        cap = sum(d.area_um2 for d in b.devices if d.kind == "cap")
        print(f"{name:<16}{fets:>10.0f}{res:>10.0f}{cap:>10.0f}{b.area:>12.0f}")
    print("-" * len(hdr))

    s = summarize(devices)
    print(f"{'device footprint':<16}{'':>30}{s['footprint']:>12.0f}")
    print()

    hdr2 = f"{'kind':<16}{'footprint':>12}{'packing':>10}{'occupied':>12}"
    print(hdr2)
    print("-" * len(hdr2))
    for kind in ("fet_small", "fet_pass", "res", "mim"):
        pack = PACKING[kind]
        print(f"{kind:<16}{s[kind]:>12.0f}{pack:>10.2f}{s[kind] / pack:>12.0f}")
    print("-" * len(hdr2))
    print(f"{'occupied':<16}{'':>22}{s['occupied']:>12.0f}")
    print(
        f"{'MIM stacked':<16}{'':>22}{-s['mim_stack_credit']:>12.0f}"
        f"  ({MIM_STACK_FRACTION:.0%} of MIM)"
    )
    subtotal = s["occupied"] - s["mim_stack_credit"]
    core = s["core_um2"]
    print(f"{'subtotal':<16}{'':>22}{subtotal:>12.0f}")
    print(f"{f'routing x{ROUTING_ALLOWANCE:.2f}':<16}{'':>22}{core - subtotal:>12.0f}")
    print("=" * len(hdr2))
    print(f"{'CORE ESTIMATE':<16}{'':>22}{core:>12.0f}  um^2 = {core / 1e6:.4f} mm^2")
    print(
        f"{'':<16}{'':>22}{100 * s['budget_fraction']:>12.1f}"
        f"  % of the {AREA_BUDGET_UM2 / 1e6:g} mm^2 budget"
    )
    print(
        f"{'':<16}{'':>22}{100 * (1 - s['budget_fraction']):>12.1f}"
        "  % margin"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
