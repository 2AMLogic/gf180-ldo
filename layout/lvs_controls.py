#!/usr/bin/env python3
"""The LVS negative controls of the DRC/LVS flow.

A control is a deliberate corruption of a cell's exported netlist that the
compare MUST report as a mismatch -- the proof that an LVS ``MATCH`` on the
intact netlist looked at something (layout/README.md, "The stages"),
relocated verbatim from ``layout/drclvs.py`` by issue #837, which
re-exports every public name here; ``layout/tests/test_drclvs.py`` still
exercises the whole contract through ``drclvs.<name>``.

Everything here is a pure transformation of netlist text: nothing runs a
tool, reads a file or loads the PDK, and the only import from this repo is
the shared base. ``CellSpec`` -- the driver's type -- is imported for
annotations only, because the driver imports this module; at runtime the
functions below need nothing from a spec but its ``key`` and ``controls``.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drclvs_common import StageError  # noqa: E402

if TYPE_CHECKING:
    from drclvs import CellSpec

__all__ = [
    "Control",
    "ControlNotApplicable",
    "L_TOKEN_RE",
    "MOS_CONTROLS",
    "PASSIVE_CONTROLS",
    "PASSIVE_ELEMENTS",
    "REQUIRED_CONTROL_TAGS",
    "W_TOKEN_RE",
    "apply_control",
    "build_controls",
    "check_controls_apply",
    "control_parameter",
    "control_passive",
    "control_short_adjacent_taps",
    "control_topology",
    "control_unit_width",
    "require_control_pair",
]


# --------------------------------------------------------------------------
# the LVS negative controls (the topology and parameter controls)
#
# Each registered cell carries its own topology/parameter pair, because a
# mutation is only a control if it can actually be applied to that cell's
# devices: the MOS pair below cannot corrupt a resistor-only cell, and the
# passive pair cannot corrupt a cell with no resistors. build_controls() then
# adds one passive-geometry control per R/C element class the netlist
# contains. `check_controls_apply()` makes "this control does not apply" a
# hard error up front rather than a stage that quietly reports nothing.
# --------------------------------------------------------------------------


# A registered cell must carry one negative control of each kind: one that
# corrupts the connection graph and one that corrupts a device parameter
# while leaving the graph alone. Those are two independent ways for an LVS
# invocation to be comparing less than it appears to, and a cell with only
# one of them has only half an evidence chain (layout/README.md, "The
# stages").
REQUIRED_CONTROL_TAGS = ("topology", "parameter")


@dataclasses.dataclass(frozen=True)
class Control:
    """One LVS negative control: a deliberate corruption that MUST mismatch.

    ``mutate`` takes the exported netlist text and returns a corrupted copy.
    It is a per-:class:`CellSpec` field rather than a module-global, because
    what counts as a corruption is a property of the cell's *devices*: the
    MOS pair below keys off an ``M*`` element line and does not exist in an
    all-passive cell, while the resistor pair keys off an ``R*`` line and
    does not exist in a cell with no resistors.
    """

    tag: str
    # Raises StageError when it cannot be applied to this netlist at all.
    mutate: Callable[[str], str]
    # One line, quoted in the stage output and in the --record run record.
    what: str
    # What a MATCH from this control would prove about the LVS invocation.
    implication: str


class ControlNotApplicable(StageError):
    """A registered negative control cannot corrupt this cell's netlist.

    Deliberately NOT a silent skip. A control that does not fire leaves the
    stage it belongs to reporting nothing, and an LVS ``MATCH`` with no
    working control behind it is not evidence at all -- so this is raised
    (and, via ``StageError`` handling in ``main()``, exits nonzero) rather
    than letting the run report a pass.
    """


def _element_line(text: str, letter: str, what: str) -> tuple[str, list[str]]:
    """The first SPICE element line of class ``letter`` (`M`, `R`, ...)."""
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) >= 6 and tokens[0].upper().startswith(letter.upper()):
            return line, tokens
    raise ControlNotApplicable(
        f"no {what} element line (`{letter.upper()}*`) in the exported netlist"
    )


def _mos_line(text: str) -> tuple[str, list[str]]:
    return _element_line(text, "M", "MOS")


def _resistor_line(text: str) -> tuple[str, list[str]]:
    return _element_line(text, "R", "resistor")


def _subckt_ports(text: str) -> set[str]:
    """The cell's own port names -- nets a control must not rename away."""
    for line in text.splitlines():
        tokens = line.split()
        if tokens and tokens[0].lower() == ".subckt":
            return set(tokens[2:])
    return set()


def _rename_net(text: str, victim: str, survivor: str) -> str:
    return re.sub(rf"(?<![\w.]){re.escape(victim)}(?![\w.])", survivor, text)


def control_topology(text: str) -> str:
    """Tie the device's gate to its drain -- a topology corruption.

    NOT a gate/drain *swap*: this deck's compare is purely structural, so a
    swap is a valid graph isomorphism (relabel the two nets) and legitimately
    still matches -- verified, see layout/README.md, "What LVS here does not
    check". Shorting the two nets changes the graph itself (4 nets become 3),
    which no relabelling can undo.
    """
    line, tokens = _mos_line(text)
    shorted = list(tokens)
    shorted[2] = shorted[1]
    return text.replace(line, " ".join(shorted))


def _dimension_token_re(param: str) -> re.Pattern[str]:
    """Compile the shared ``<param>=<number>[unit]`` dimension-token grammar.

    One grammar for every dimension control -- MOS ``W=``, divider-resistor
    ``W=``, passive ``l=`` (the spelling layout/lvs_form.py renders): 2u,
    0.22u, 2.u, 6u, 2e-6, 360U. The unit suffix is its own group so a
    doubled value stays in the original units. Case-insensitive because this
    repo's netlists spell the MOS convention uppercase (`L=`/`W=`) while the
    passive convention the LVS deck's SPICE reader delegate reads is
    lowercase (`l=`/`w=`); the split between the two constants below is about
    which parameter each control corrupts, not about case.
    """
    return re.compile(
        rf"^{param}=([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([a-zA-Z]*)$",
        re.IGNORECASE,
    )


W_TOKEN_RE = _dimension_token_re("W")
# `l=` (primitive form) or the PDK capacitor spelling `c_length=` that the
# klt route's reference carries (layout/lvs_form.py, cap_pdk_params).
L_TOKEN_RE = _dimension_token_re("(?:c_length|l)")


def _double(value: str) -> str:
    """Render ``value`` doubled, without gaining a spurious `.0`."""
    doubled = float(value) * 2
    if doubled.is_integer():
        return str(int(doubled))
    # repr() keeps the shortest round-tripping decimal (0.22 -> 0.44, not
    # 0.44000000000000006), which matters because this text goes into a
    # netlist a human may read in a failure report.
    return repr(doubled)


def _double_first_dimension(
    tokens: list[str], param_re: re.Pattern[str], prefix: str, missing: str
) -> list[str]:
    """Replace the first token matching ``param_re`` with its doubled value.

    The shared body of every parameter-doubling control: find the first
    dimension token on the element line, scale its number with ``_double``
    and carry the unit suffix through unchanged. ``prefix`` re-spells the
    parameter name in the control's output spelling (`W=`, `l=`); ``missing``
    is that control's own no-parameter diagnostic, raised verbatim.
    """
    for index, token in enumerate(tokens):
        match = param_re.match(token)
        if match is None:
            continue
        resized = list(tokens)
        resized[index] = f"{prefix}{_double(match.group(1))}{match.group(2)}"
        return resized
    raise ControlNotApplicable(missing)


def control_parameter(text: str) -> str:
    """Double the device width -- a device-parameter corruption.

    Topologically identical to the real netlist, so this control fails only if
    the compare is actually checking device parameters and not just the
    connection graph.

    The width is *parsed and scaled*, not matched against a literal: the
    first registered cell was one W=2u transistor, and a hardcoded `W=2u` ->
    `W=4u` substitution made this stage die on every other cell (issue #313).
    """
    line, tokens = _mos_line(text)
    resized = _double_first_dimension(
        tokens,
        W_TOKEN_RE,
        "W=",
        "expected a `W=<number>[unit]` parameter on the first MOS element "
        f"line, got: {line}",
    )
    return text.replace(line, " ".join(resized))


def control_short_adjacent_taps(text: str) -> str:
    """Short the first resistor's two taps together -- a topology corruption.

    The all-passive counterpart of ``control_topology``. Renaming one of the
    first unit's terminals to the other collapses two adjacent taps of the
    string into one node: the unit is shorted out and the graph loses a net,
    which no relabelling can undo -- the same reason ``control_topology``
    shorts rather than swaps (layout/README.md, "What LVS here does not
    check").

    The renamed net must not be one of the cell's own ports: renaming a port
    would change the *pin list* rather than the internal topology, which is a
    different (and weaker) corruption.
    """
    _line, tokens = _resistor_line(text)
    ports = _subckt_ports(text)
    a, b = tokens[1], tokens[2]
    if b not in ports:
        victim, survivor = b, a
    elif a not in ports:
        victim, survivor = a, b
    else:
        raise ControlNotApplicable(
            f"both taps of the first resistor ({a}, {b}) are cell ports, so "
            "shorting them would change the pin list rather than the internal "
            "topology"
        )
    return _rename_net(text, victim, survivor)


def control_unit_width(text: str) -> str:
    """Double the first resistor's drawn width -- a parameter corruption.

    The all-passive counterpart of ``control_parameter``, and deliberately
    **not** a change to the resistance value: the gf180mcu LVS deck's own
    ``BResistor`` class (rule_decks/custom_classes.lvs) does
    ``enable_parameter('R', false)`` and compares only ``W`` and ``L``, so a
    scaled ``R=`` would be a control that never fires. Doubling ``W`` leaves
    the connection graph untouched, so this control isolates the parameter
    compare exactly as the MOS parameter control does.
    """
    line, tokens = _resistor_line(text)
    resized = _double_first_dimension(
        tokens,
        W_TOKEN_RE,
        "W=",
        "expected a `W=` parameter on the first resistor element line, "
        f"got: {line}",
    )
    return text.replace(line, " ".join(resized))


PASSIVE_ELEMENTS = {"R": "resistor", "C": "capacitor"}


def _passive_line(text: str, letter: str) -> tuple[str, list[str]] | None:
    """First primitive ``letter`` element line carrying an ``l=`` parameter."""
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 4 or tokens[0][:1].upper() != letter:
            continue
        if any(L_TOKEN_RE.match(token) for token in tokens):
            return line, tokens
    return None


def control_passive(letter: str):
    """Build a control that doubles the first ``letter`` device's length.

    The MOS controls above say nothing about whether the compare looks at a
    *passive*'s geometry, and a compare that silently ignored it would wave
    through a mis-sized resistor or MIM cap -- exactly the devices
    layout/lvs_form.py exists to get into the netlist at all (issue #313). One
    of these is registered per passive element class present in the netlist, so
    a FET-only cell (layout/testcell) is unaffected.

    Length rather than width because the LVS deck's SPICE reader delegate
    derives the capacitor's compared parameters from *both* (``A = W*L*M``,
    ``P = 2*(W+L)*M``) and the resistor's ``L`` directly -- so doubling ``l``
    moves a compared parameter for either class. It does NOT touch ``r=``/``c=``:
    the delegate registers both with that parameter disabled, so a wrong
    resistance or capacitance legitimately still matches.
    """

    def mutate(text: str) -> str:
        missing = (
            f"no primitive {letter} element line with an `l=` parameter "
            "in the exported netlist"
        )
        found = _passive_line(text, letter)
        if found is None:
            raise ControlNotApplicable(missing)
        line, tokens = found
        # keep the token's own spelling (`l=` or the PDK's `c_length=`)
        spelled = next(t for t in tokens if L_TOKEN_RE.match(t)).split("=")[0]
        resized = _double_first_dimension(
            tokens, L_TOKEN_RE, f"{spelled}=", missing
        )
        return text.replace(line, " ".join(resized))

    return mutate


MOS_CONTROLS = (
    Control(
        tag="topology",
        mutate=control_topology,
        what="gate shorted to drain",
        implication="a 4-net circuit compared equal to a 3-net one",
    ),
    Control(
        tag="parameter",
        mutate=control_parameter,
        what="device width doubled",
        implication="device parameters are not being compared at all",
    ),
)

PASSIVE_CONTROLS = (
    Control(
        tag="topology",
        mutate=control_short_adjacent_taps,
        what="two adjacent taps shorted",
        implication="a string with one unit shorted out compared equal to the "
        "intact one",
    ),
    Control(
        tag="parameter",
        mutate=control_unit_width,
        what="unit resistor width doubled",
        implication="device parameters are not being compared at all",
    ),
)


def build_controls(
    text: str, base: tuple[Control, ...] = MOS_CONTROLS
) -> dict[str, Control]:
    """The LVS negative controls this netlist can support, keyed by tag.

    ``base`` is the cell's own topology/parameter pair (``CellSpec.controls``:
    ``MOS_CONTROLS`` for a cell with FETs, ``PASSIVE_CONTROLS`` for an
    all-resistor one). On top of it, one passive-geometry control is
    registered per element class the netlist actually contains, so the
    control set is a property of the cell rather than a fixed list.
    """
    controls = {control.tag: control for control in base}
    for letter, noun in PASSIVE_ELEMENTS.items():
        if _passive_line(text, letter) is not None:
            tag = f"passive-{letter.lower()}"
            controls[tag] = Control(
                tag=tag,
                mutate=control_passive(letter),
                what=f"{noun} length doubled",
                implication=f"{noun} geometry is not being compared at all",
            )
    return controls


def require_control_pair(spec: CellSpec) -> None:
    """Every registered cell must carry one control of each required kind."""
    tags = [control.tag for control in spec.controls]
    missing = [tag for tag in REQUIRED_CONTROL_TAGS if tag not in tags]
    duplicated = sorted({tag for tag in tags if tags.count(tag) > 1})
    if missing or duplicated:
        raise StageError(
            f"cell {spec.key!r} registers controls {tags} -- it must register "
            f"exactly one of each of {list(REQUIRED_CONTROL_TAGS)}"
            + (f"; missing {missing}" if missing else "")
            + (f"; duplicated {duplicated}" if duplicated else "")
        )


def apply_control(spec: CellSpec, control: Control, text: str) -> str:
    """Corrupt ``text`` with ``control``, or fail loudly.

    Two ways to fail, both hard errors rather than skips:

    * the mutation cannot be applied at all (no element of the right class,
      no parameter of the right name) -- ``ControlNotApplicable``;
    * the mutation *runs* but returns the netlist unchanged. That is the
      dangerous one: an unchanged "corrupted" netlist compares MATCH, and a
      loop that treated MATCH-on-a-no-op as a pass would report a stage that
      proved nothing. There is no netlist for which a no-op mutation is
      correct, so this is always a bug in the registered control.
    """
    try:
        mutated = control.mutate(text)
    except ControlNotApplicable as exc:
        raise ControlNotApplicable(
            f"cell {spec.key!r} registers the {control.tag} control "
            f"({control.what}), but it does not apply to this cell's netlist: "
            f"{exc}.\n"
            "  An LVS MATCH is not evidence unless a known-wrong netlist "
            "demonstrably fails, so a control that cannot corrupt this cell is "
            "a hard error, not a skipped stage. Register a control pair that "
            "matches the cell's devices (see MOS_CONTROLS / PASSIVE_CONTROLS)."
        ) from exc
    if mutated == text:
        raise ControlNotApplicable(
            f"cell {spec.key!r}'s {control.tag} control ({control.what}) ran "
            "but produced a netlist identical to the original -- it would "
            "'mismatch' nothing and the stage would prove nothing."
        )
    return mutated


def check_controls_apply(spec: CellSpec, text: str) -> dict[str, Control]:
    """Prove every control this run will use corrupts this netlist, before any LVS.

    Run up front, so a cell whose controls do not apply fails *before* stage
    5 prints ``lvs: MATCH`` -- the failure mode this guards against is a run
    that reports a match and only afterwards discovers its controls were
    inert. Covers both the cell's registered pair and the passive-geometry
    controls build_controls() adds, and returns that full set so the stages
    run exactly what was checked.
    """
    require_control_pair(spec)
    controls = build_controls(text, spec.controls)
    for control in controls.values():
        apply_control(spec, control, text)
    return controls
