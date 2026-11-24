#!/usr/bin/env python3
"""Render xschem's *simulation*-form passive lines as LVS primitives.

Why this exists
---------------
``layout/xschemrc`` sets ``lvs_netlist 1`` so that xschem renders each device
instance from its symbol's ``lvs_format`` attribute instead of its ``format``
attribute -- a plain SPICE element (``M1 D G S VSS nfet_03v3 L=.. W=..``)
rather than an ngspice subcircuit call (``XM1 ...``), because KLayout's
``RBA::NetlistSpiceReader`` (which the gf180mcu LVS deck drives) reads the
first form and cannot evaluate the second's parameter expressions.

That works for the FETs and **only** for the FETs: in the installed
gf180mcu PDK, ``lvs_format`` is present on ``nfet_*.sym`` / ``pfet_*.sym``
and on nothing else (issue #313). Every passive symbol -- the whole
``ppolyf_u_*`` / ``npolyf_*`` / ``nplus_u`` / ``rm*`` resistor family and the
whole ``cap_mim_*`` / ``cap_nmos_*`` / ``cap_pmos_*`` capacitor family --
carries a ``format`` and no ``lvs_format``, so with ``lvs_netlist 1`` they
still come out in simulation form::

    XRbias NBIAS RBT VSS ppolyf_u_1k r_width=1u r_length=1000u m=1
    XCc    NZ    OUT     cap_mim_2f0_m3m4_noshield c_width=48u c_length=48u m=1

Handing those to the LVS deck is not an option: the reader turns an ``X``
line into a *subcircuit* instantiation whose definition is not in the
netlist, so the compare sees an empty subcircuit where a device should be.

What this module does
---------------------
It translates exactly those two shapes into the primitive ``R``/``C``
elements the deck's own ``SubcircuitModelsReader`` delegate understands
(``libs.tech/klayout/tech/lvs/rule_decks/custom_classes.lvs``)::

    Rbias NBIAS RBT VSS ppolyf_u_1k l=1000u w=1u m=1
    Cc    NZ    OUT     cap_mim_2f0fF l=48u w=48u m=1

For the MIM capacitors the model token is rewritten too, and that is not
cosmetic: KLayout's compare matches device classes BY NAME. The deck's
extraction registers ``cap_mim_<n>f<m>fF`` classes
(``rule_decks/mimcap_extraction.lvs``), while the token an export carries is
the *symbol* name (``cap_mim_2f0_m3m4_noshield``), so the two names have to
be reconciled here, keyed on the flavour ``<n>f<m>`` the two spellings
share (issue #642). This mirrors the
convention the PDK's own LVS regression netlists follow: the *subcircuit*
is named after the symbol, the *device* after the extraction class --
``testing/unit/mimcap_devices/netlist/cap_mim_2f0fF_B_5LM_2p0.cdl`` has
``.SUBCKT cap_mim_2f0_m4m5_noshield`` whose device lines read
``C... cap_mim_2f0fF ...``. The deck registers one MIM flavour per run,
selected by its ``mim_cap`` switch, and ``drclvs.py`` pins that switch
(``MIMCAP_SWITCH``) -- whose case registers exactly ``cap_mim_2f0fF``
(``MIMCAP_CLASS``). So 2f0 maps, and every other ``cap_mim_*`` token is a
hard :class:`LvsFormError`, never a mapped or passed-through token --
whether neither spelling's regex can parse it into a flavour at all, or it
parses to a flavour other than the pinned ``MIMCAP_FLAVOUR``: a token
naming a class the run does not register compares as a well-formed wrong
verdict with no rule-level diagnosis (issue #680).
Resistors need no mapping -- on the
pinned deck the resistor symbols' names are the registered class names
(``ppolyf_u_1k`` & co) -- and the non-MIM capacitors register their classes
under the symbol names too (``rule_decks/moscap_extraction.lvs``), so their
tokens pass through unchanged.

Only ``l`` and ``w`` are carried over, and that is deliberate rather than
lazy: the delegate registers ``R`` with ``enable_parameter('R', false)`` and
``C`` with ``enable_parameter('C', false)``, so **resistance and capacitance
are not compared at all** -- only the geometry is. Measured on a
single-resistor vehicle against the PDK deck with the same switches
``layout/drclvs.py`` uses: an ``r=`` 30x off the true value still MATCHes,
while a 10x wrong ``l`` or a 5x wrong ``w`` mismatches. Since the sheet
resistance is flavour-dependent (issue #312), not having to compute it is a
feature.

Why here and not in the symbols
-------------------------------
The alternative was repo-local ``.sym`` overrides that add ``lvs_format`` to
the passive symbols, resolved ahead of the PDK's via
``XSCHEM_USER_LIBRARY_PATH``. That keeps xschem the single renderer, but
duplicates PDK symbol files into this repo -- one per flavour, ~20 of them
for full coverage -- and each copy silently goes stale when the PDK updates
its symbols, in a way nothing here would detect. A post-export rewrite is
one place, covers every flavour of both families by construction (the
parameter *names* ``r_width``/``r_length`` and ``c_width``/``c_length`` are
what identify the family, not a per-symbol list), and is unit-testable
without a PDK. The cost is that the LVS reference netlist is no longer
purely xschem's own rendering -- which is why the rewrite is conservative
(see below) and why ``drclvs.py`` still runs its ``SIM_FORM_RE`` guard
*after* this pass, so anything this module declined to touch is still a hard
failure rather than a silent pass.

Conservative by construction
----------------------------
A line is rewritten only if **all** of these hold:

* it is an ``X``-prefixed element line;
* its trailing tokens are all ``key=value`` pairs; and
* those pairs contain a complete ``r_width``/``r_length`` **or**
  ``c_width``/``c_length`` pair.

Anything else is passed through untouched. A genuine hierarchical subcircuit
call (``Xamp IN OUT VDD VSS error_amp``) has no ``key=value`` tail and is
therefore never rewritten.
"""

from __future__ import annotations

import re

__all__ = [
    "LvsFormError",
    "MIMCAP_CLASS",
    "MIMCAP_CURATED_OPTION",
    "MIMCAP_SWITCH",
    "rewrite_passives",
    "unrendered_device_lines",
]


class LvsFormError(RuntimeError):
    """A passive line could not be rendered in LVS form."""


# `key=value`, with the key in SPICE's identifier shape. Anchored, so a token
# that merely contains an `=` (an expression like ad='...') does not match and
# the line is left alone.
_PARAM_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(\S*)$")

# (SPICE element letter, the symbol format's width param, its length param).
# These parameter names come from the PDK symbols' own `format` strings:
#   format="@spiceprefix@name @pinlist @model r_width=@W r_length=@L m=@m"
#   format="@spiceprefix@name @pinlist @model c_width=@W c_length=@L m=@m"
# which is every resistor and every capacitor symbol in
# libs.tech/xschem/symbols/ -- so matching on the parameter names covers the
# whole family without enumerating flavours.
_FAMILIES = (
    ("R", "r_width", "r_length"),
    ("C", "c_width", "c_length"),
)

# The MIM-capacitor family's *symbol* names are not what the deck's
# extraction registers as device classes: rule_decks/mimcap_extraction.lvs
# registers cap_mim_<n>f<m>fF names, while the tokens an xschem export
# carries -- the PDK symbols' names, and the `model=` overrides this repo's
# schematics set -- are the symbol spellings:
# cap_mim_<n>f<m>_<metals>_noshield. KLayout's compare matches device
# classes BY NAME, so the rendered C line has to carry the class name.
#
# The deck registers only ONE MIM flavour per run, picked by its $mim_cap
# switch, and drclvs.py pins that switch: MIMCAP_SWITCH below is the switch
# value, whose deck case registers exactly MIMCAP_CLASS. That pairing is
# transcribed here and nowhere else, so the switch drclvs.py passes and the
# flavour this renderer accepts cannot drift apart (issue #680). A
# cap_mim_* token naming any other flavour -- in either spelling -- is a
# hard LvsFormError (see _mimcap_model_token).
MIMCAP_SWITCH = "2"
MIMCAP_FLAVOUR = "2f0"
MIMCAP_CLASS = f"cap_mim_{MIMCAP_FLAVOUR}fF"
# The same flavour as a *curated klt deck option* value. ``klt extract`` /
# ``klt lvs`` name the gf180mcu MIM classes ``cap_mim_<n>f<m>_m4m5_noshield``
# -- the previous PDK revision's LVS class names, kept by klt for netlist
# stability -- while this repo's netlists (and the installed PDK's own LVS
# deck) spell the class ``cap_mim_<n>f<m>fF`` (MIMCAP_CLASS above). The two
# spellings denote the same drawn device at the same density; transcribing
# the curated value here keeps the third spelling of the same pairing in the
# one place the other two already live. The divergence itself is
# 2AMLogic/klayout-tools#7031.
MIMCAP_CURATED_OPTION = f"cap_mim_{MIMCAP_FLAVOUR}_m4m5_noshield"
_MIMCAP_CLASS_RE = re.compile(r"^cap_mim_(\d+f\d+)fF$")
_MIMCAP_SYMBOL_RE = re.compile(r"^cap_mim_(\d+f\d+)(?:_.+)?$")


def _mimcap_model_token(model: str, line: str) -> str:
    """Map a cap_mim *symbol* name to the device class the run registers.

    Non-``cap_mim_*`` capacitor models are returned unchanged: the deck
    registers their classes under the symbol names themselves
    (``rule_decks/moscap_extraction.lvs``: ``cap_nmos_03v3`` & co).

    The MIM run registers exactly one flavour: the ``mim_cap`` switch
    drclvs.py pins (``MIMCAP_SWITCH``) selects the deck case that registers
    ``MIMCAP_CLASS``. So a ``cap_mim_*`` token naming any other flavour --
    in symbol or in class spelling -- is a hard ``LvsFormError``: mapped or
    passed through, it would name a class the run never registers.
    """
    if not model.startswith("cap_mim_"):
        return model
    match = _MIMCAP_CLASS_RE.match(model)
    if match is None:
        match = _MIMCAP_SYMBOL_RE.match(model)
    if match is None:
        raise LvsFormError(
            f"capacitor model token {model!r} is a cap_mim flavour this module "
            "cannot parse into a device class the deck's MIM extraction "
            "registers. Passing it through would compare a class the deck "
            "never registers: the compare would report a well-formed "
            "mismatch with no rule-level diagnosis:\n"
            f"    {line}\n"
            f"  Set the instance's `model=` to the flavour this flow "
            f"registers ({MIMCAP_CLASS}, deck switch mim_cap={MIMCAP_SWITCH}), "
            "or extend the extraction deck for the new flavour."
        )
    if match.group(1) != MIMCAP_FLAVOUR:
        raise LvsFormError(
            f"capacitor model token {model!r} names the cap_mim flavour "
            f"{match.group(1)!r}, but this run registers only {MIMCAP_CLASS} "
            f"(the deck's mim_cap={MIMCAP_SWITCH} case, which drclvs.py "
            "pins; issue #680). Mapped or passed through, it would compare "
            "a class the deck never extracts: the compare would report a "
            "well-formed mismatch with no rule-level diagnosis:\n"
            f"    {line}\n"
            f"  Set the instance's `model=` to a {MIMCAP_FLAVOUR} MIM "
            "capacitor -- the flavour this flow's pinned switch selects -- "
            "or change the pinned switch and the registered flavour with it."
        )
    return MIMCAP_CLASS


def _split_params(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Split ``tokens`` at the first ``key=value`` token."""
    for index, token in enumerate(tokens):
        if _PARAM_RE.match(token):
            return tokens[:index], tokens[index:]
    return tokens, []


def _rewrite_line(line: str, cap_pdk_params: bool = False) -> str | None:
    """Return the LVS-form rendering of ``line``, or None to leave it alone.

    ``cap_pdk_params`` renders a capacitor's geometry as the PDK's own
    ``c_length=``/``c_width=`` instead of ``l=``/``w=``: klt's subckt-call
    reference conversion only derives a MIM capacitor's A/P from the former
    (the latter converts with the geometry dropped).
    """
    tokens = line.split()
    if not tokens or tokens[0][:1] not in ("X", "x"):
        return None

    head, params = _split_params(tokens)
    # name + at least one net + model
    if len(head) < 3 or not params:
        return None

    values: dict[str, str] = {}
    order: list[str] = []
    for token in params:
        match = _PARAM_RE.match(token)
        if match is None:
            # A trailing token that is not a plain key=value pair: not a shape
            # this module claims to understand. Leave the whole line alone and
            # let drclvs.py's SIM_FORM_RE guard have the final word.
            return None
        key = match.group(1).lower()
        values[key] = match.group(2)
        order.append(key)

    for letter, width_key, length_key in _FAMILIES:
        if width_key in values and length_key in values:
            break
    else:
        return None

    name = head[0][1:]
    nets = head[1:-1]
    model = head[-1]
    if letter == "C":
        model = _mimcap_model_token(model, line)
    if not name:
        raise LvsFormError(f"passive instance has no name after its `X` prefix: {line}")
    if name[:1].upper() != letter:
        raise LvsFormError(
            f"the instance name {name!r} does not start with {letter!r}, the "
            f"SPICE element letter its class needs, so the line cannot be "
            f"rendered as a primitive {letter} element:\n"
            f"    {line}\n"
            f"  Rename the instance in the schematic. layout/xschemrc "
            f"documents this: in a cell that will be LVS'd, name each device "
            f"instance with the SPICE element letter its class needs "
            f"(`M*` for MOS, `R*` for resistors, `C*` for capacitors), "
            f"because the netlist's leading letter is what tells KLayout's "
            f"SPICE reader which element it is looking at."
        )

    rest = [
        f"{key}={values[key]}"
        for key in order
        if key not in (width_key, length_key)
    ]
    length_name, width_name = ("l", "w")
    if cap_pdk_params and letter == "C":
        length_name, width_name = ("c_length", "c_width")
    return " ".join(
        [
            name, *nets, model,
            f"{length_name}={values[length_key]}",
            f"{width_name}={values[width_key]}",
            *rest,
        ]
    )


def rewrite_passives(text: str, cap_pdk_params: bool = False) -> tuple[str, int]:
    """Rewrite every simulation-form passive line in ``text``.

    Returns ``(text, count)`` where ``count`` is how many lines were
    rewritten -- ``layout/drclvs.py`` uses it to decide whether the exported
    netlist's provenance header has to mention this pass at all.
    """
    out: list[str] = []
    count = 0
    for line in text.splitlines():
        rewritten = _rewrite_line(line, cap_pdk_params)
        if rewritten is None:
            out.append(line)
        else:
            out.append(rewritten)
            count += 1
    if not text.endswith("\n"):
        return "\n".join(out), count
    return "\n".join(out) + "\n", count


def unrendered_device_lines(text: str) -> list[str]:
    """X-prefixed lines that are still a *device*, not a subcircuit call.

    ``drclvs.py``'s ``SIM_FORM_RE`` guard names the device families it knows
    about (FETs and the passives above), which means a family nobody has
    needed yet -- a diode, a BJT -- would sail through it in simulation form
    and be compared as an empty subcircuit. This is the family-agnostic
    backstop for that: it does not ask *which* device a line is, only whether
    it is one.

    The discriminator is the trailing ``key=value`` parameter list. Every
    gf180mcu device symbol's ``format`` string ends in one (``L=@L W=@W ...``,
    ``r_width=@W ...``, ``area='...' pj='...'``, ``m=@m``), whereas a
    hierarchical subcircuit symbol's is ``@name @pinlist @symname`` -- bare
    nets and a cell name, no parameters. So an ``X`` line with a parameter
    tail is a device rendered from a ``format`` attribute, and in an LVS-form
    netlist that is always wrong; an ``X`` line without one is an ordinary
    subcircuit instantiation and is left alone.

    Run this *after* ``rewrite_passives()`` and after the family-specific
    guard, so the lines it reports are exactly the ones nothing else claimed.
    """
    offenders = []
    for line in text.splitlines():
        tokens = line.split()
        if not tokens or tokens[0][:1] not in ("X", "x"):
            continue
        head, params = _split_params(tokens)
        if len(head) >= 3 and params:
            offenders.append(line)
    return offenders
