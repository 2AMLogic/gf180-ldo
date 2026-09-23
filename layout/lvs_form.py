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
(``libs.tech/klayout/lvs/rule_decks/custom_classes.lvs``)::

    Rbias NBIAS RBT VSS ppolyf_u_1k l=1000u w=1u m=1
    Cc    NZ    OUT     cap_mim_2f0_m3m4_noshield l=48u w=48u m=1

which is the shape the PDK's own LVS regression netlists use.

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

__all__ = ["LvsFormError", "rewrite_passives"]


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


def _split_params(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Split ``tokens`` at the first ``key=value`` token."""
    for index, token in enumerate(tokens):
        if _PARAM_RE.match(token):
            return tokens[:index], tokens[index:]
    return tokens, []


def _rewrite_line(line: str) -> str | None:
    """Return the LVS-form rendering of ``line``, or None to leave it alone."""
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
    return " ".join(
        [name, *nets, model, f"l={values[length_key]}", f"w={values[width_key]}", *rest]
    )


def rewrite_passives(text: str) -> tuple[str, int]:
    """Rewrite every simulation-form passive line in ``text``.

    Returns ``(text, count)`` where ``count`` is how many lines were
    rewritten -- ``layout/drclvs.py`` uses it to decide whether the exported
    netlist's provenance header has to mention this pass at all.
    """
    out: list[str] = []
    count = 0
    for line in text.splitlines():
        rewritten = _rewrite_line(line)
        if rewritten is None:
            out.append(line)
        else:
            out.append(rewritten)
            count += 1
    if not text.endswith("\n"):
        return "\n".join(out), count
    return "\n".join(out) + "\n", count
