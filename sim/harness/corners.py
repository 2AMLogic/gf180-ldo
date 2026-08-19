"""Process / voltage / temperature corner definitions for gf180mcu.

The gf180mcu ngspice model library (``sm141064.ngspice``) does not ship a
single "ss" switch that skews every device. Each device family carries its
own ``.lib`` section:

    MOS      typical | ff | ss | fs | sf
    BJT      bjt_typical | bjt_ff | bjt_ss
    diode    diode_typical | diode_ff | diode_ss
    resistor res_typical | res_ff | res_ss
    MOS cap  moscap_typical | moscap_ff | moscap_ss
    MIM cap  mimcap_typical | mimcap_ff | mimcap_ss

A *named corner* here is therefore a bundle of sections. Section ordering
follows the PDK's own xschem testbenches (MOS first, then passives), and
``design.ngspice`` is always included ahead of them because it defines the
global switch params (``sw_stat_global``, ``mc_skew``, ...) the sections
reference.

For the LDO the pass FET and error-amp MOS skew (``ff``/``ss``/``fs``/``sf``)
and the feedback divider's resistor skew (``res_ff``/``res_ss``) are what the
per-spec-line testbenches (#12) will care about most; ``--corner-set full``
adds the resistor- and BJT-only corners on top of the five MOS corners for
claims where that matters (e.g. divider-accuracy or reference claims).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

# Default PVT axes. CLAUDE.md mandates these on every recorded result;
# spec/decision-records/DR-0002-input-flavor.md fixes the 3.3 V +/-10% input.
DEFAULT_TEMPERATURES_C: tuple[float, ...] = (-40.0, 27.0, 125.0)
DEFAULT_SUPPLY_TOLERANCE: float = 0.10  # +/-10 %
DEFAULT_NOMINAL_SUPPLY_V: float = 3.3   # gf180mcu 3.3 V flavor (DR-0002)


def _bundle(mos: str, bjt: str, diode: str, res: str, moscap: str, mimcap: str) -> tuple[str, ...]:
    return (mos, res, bjt, diode, moscap, mimcap)


@dataclass(frozen=True)
class Corner:
    """A named process corner: an ordered list of model ``.lib`` sections."""

    name: str
    sections: tuple[str, ...]
    description: str = ""


def _all(skew: str, description: str) -> Corner:
    """Global corner: every device family skewed the same direction."""
    suffix = {"ff": "ff", "ss": "ss"}[skew]
    return Corner(
        name=skew,
        sections=_bundle(
            mos=suffix,
            bjt=f"bjt_{suffix}",
            diode=f"diode_{suffix}",
            res=f"res_{suffix}",
            moscap=f"moscap_{suffix}",
            mimcap=f"mimcap_{suffix}",
        ),
        description=description,
    )


_TYPICAL = _bundle(
    mos="typical",
    bjt="bjt_typical",
    diode="diode_typical",
    res="res_typical",
    moscap="moscap_typical",
    mimcap="mimcap_typical",
)


def _mos_only(name: str, mos_section: str, description: str) -> Corner:
    """MOS skewed, passives at typical."""
    sections = (mos_section,) + _TYPICAL[1:]
    return Corner(name=name, sections=sections, description=description)


def _passive_only(name: str, family_index: int, section: str, description: str) -> Corner:
    sections = list(_TYPICAL)
    sections[family_index] = section
    return Corner(name=name, sections=tuple(sections), description=description)


CORNERS: dict[str, Corner] = {
    "tt": Corner("tt", _TYPICAL, "all device families typical"),
    "ff": _all("ff", "all device families fast"),
    "ss": _all("ss", "all device families slow"),
    "fs": _mos_only("fs", "fs", "fast NMOS / slow PMOS, passives typical"),
    "sf": _mos_only("sf", "sf", "slow NMOS / fast PMOS, passives typical"),
    # Passive-dominated corners: the feedback divider's accuracy (and any
    # reference) rides on the resistor sheet rho / BJT Is-beta far more than
    # on the MOS skew.
    "res_ff": _passive_only("res_ff", 1, "res_ff", "resistors fast (low rho), rest typical"),
    "res_ss": _passive_only("res_ss", 1, "res_ss", "resistors slow (high rho), rest typical"),
    "bjt_ff": _passive_only("bjt_ff", 2, "bjt_ff", "BJTs fast, rest typical"),
    "bjt_ss": _passive_only("bjt_ss", 2, "bjt_ss", "BJTs slow, rest typical"),
}

CORNER_SETS: dict[str, tuple[str, ...]] = {
    # Minimum bar for a quick smoke run.
    "tt": ("tt",),
    # The five classic MOS corners -- the default.
    "mos": ("tt", "ff", "ss", "fs", "sf"),
    # Everything: MOS corners plus resistor / BJT skews.
    "full": ("tt", "ff", "ss", "fs", "sf", "res_ff", "res_ss", "bjt_ff", "bjt_ss"),
}
DEFAULT_CORNER_SET = "mos"


def resolve_corners(names: list[str] | tuple[str, ...] | None) -> list[Corner]:
    """Turn a list of corner *or* corner-set names into Corner objects."""
    if not names:
        names = [DEFAULT_CORNER_SET]
    resolved: list[Corner] = []
    seen: set[str] = set()
    for name in names:
        expanded = CORNER_SETS.get(name, (name,))
        for corner_name in expanded:
            if corner_name in seen:
                continue
            if corner_name not in CORNERS:
                raise KeyError(
                    f"unknown corner {corner_name!r}; "
                    f"known corners: {', '.join(sorted(CORNERS))}; "
                    f"known sets: {', '.join(sorted(CORNER_SETS))}"
                )
            seen.add(corner_name)
            resolved.append(CORNERS[corner_name])
    return resolved


def supply_points(
    nominal_v: float = DEFAULT_NOMINAL_SUPPLY_V,
    tolerance: float = DEFAULT_SUPPLY_TOLERANCE,
) -> list[float]:
    """Nominal supply and its +/- tolerance rails, low to high."""
    if tolerance <= 0:
        return [round(nominal_v, 6)]
    return [
        round(nominal_v * (1.0 - tolerance), 6),
        round(nominal_v, 6),
        round(nominal_v * (1.0 + tolerance), 6),
    ]


@dataclass(frozen=True)
class PvtPoint:
    """One point in the PVT grid -- exactly one ngspice invocation."""

    corner: Corner
    temp_c: float
    vdd: float

    @property
    def corner_id(self) -> str:
        """The ``<process>_<temp>c_<supply>v`` id from ``sim/README.md``.

        This is the ratified corner naming for evidence records: the raw log
        for this point is ``corners/<record-id>/<corner-id>.log`` (e.g.
        ``ss_-40c_2.97v.log``, ``tt_27c_3.30v.log``). ``sim/README.md`` also
        allows a single record that sweeps more than one load current within
        the same corner matrix to append the load point, e.g.
        ``ss_-40c_2.97v_50ma`` -- this harness records the load as an
        **Operating conditions** field on the record (see ``report.py``)
        rather than as a grid axis; a testbench that genuinely needs a
        load sweep composes it into its own netlist/measure set.
        """
        return f"{self.corner.name}_{self.temp_c:g}c_{self.vdd:.2f}v"

    def as_dict(self) -> dict:
        return {
            "corner": self.corner.name,
            "corner_sections": list(self.corner.sections),
            "temp_c": self.temp_c,
            "vdd": self.vdd,
            "corner_id": self.corner_id,
        }


def build_grid(
    corners: list[Corner],
    temperatures: list[float] | tuple[float, ...],
    supplies: list[float],
) -> list[PvtPoint]:
    """Full factorial P x V x T grid, in a stable, reproducible order."""
    points = [
        PvtPoint(corner=corner, temp_c=float(temp), vdd=float(vdd))
        for corner, temp, vdd in itertools.product(corners, temperatures, supplies)
    ]
    return points
