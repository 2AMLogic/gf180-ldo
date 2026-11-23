"""The compliance-limited load sink's ``Bload`` card, defined once (issue #637).

Issue #46 replaced the ideal ``Iload`` sink with a behavioural one whose
current is gated by a smooth compliance factor on the output voltage,

    f(VOUT) = 0.5 * (1 + tanh((VOUT - 0.2) / 0.05))

so the deck has no sub-ground solution for the sink to sustain
(``sim/harness/README.md``, "compliance-limited sink"). Ten testbench decks
then each retyped the ``Bload`` card, and when #478 added a supply gate

    g(VIN) = 0.5 * (1 + tanh((VIN - 2.0) / 0.05))

it reached one of the ten. This module is the one place the card is spelled;
a deck carries an ``@BLOAD...@`` hole instead and every consumer of a deck
fragment fills it with :func:`render` (same ``@TOKEN@`` mechanism and guard as
:mod:`harness.deck`, issue #592). Adding the supply gate to another bench is
now a token rename in that bench's deck, and an electrical change that needs
its own evidence.

The ``Vilc`` (commanded current) and ``Vlmeas`` (ammeter) cards stay in each
deck: the commanded current is the per-bench knob, and the card this module
renders reads it as ``v(ilc)``.

Tokens (the deck's whole ``Bload`` line is replaced):

``@BLOAD@``
    ``Bload VOUT NLOAD`` -- the standard sink.
``@BLOAD_VIN_GATED@``
    The same, additionally gated on the supply (#478).
``@BLOAD_FULL@``
    ``Bload_full VOUT_FULL NLOAD_FULL`` -- the full-load instance of the
    three-instance quiescent-current deck.
"""

from __future__ import annotations

from . import deck

#: Compliance knee: the sink is half on at this output voltage ...
VOUT_KNEE_V = 0.2
#: ... and goes fully on/off over a few of these (tanh softness).
VOUT_SOFT_V = 0.05
#: #478 supply gate knee / softness (only for the opt-in ``supply_gate``).
VIN_KNEE_V = 2.0
VIN_SOFT_V = 0.05


def _gate(node: str, knee: float, soft: float) -> str:
    return f"0.5 * (1 + tanh((v({node}) - {knee}) / {soft}))"


def bload(
    *,
    suffix: str = "",
    vout: str = "VOUT",
    nload: str = "NLOAD",
    supply_gate: str | None = None,
) -> str:
    """The ``Bload`` card line.

    ``suffix`` is appended to the element name (``Bload`` + ``_full``);
    ``vout`` / ``nload`` are the node names (the compliance factor reads
    ``vout``, lower-cased as ngspice vectors are); ``supply_gate`` is the
    supply node (e.g. ``"vin"``) to also gate the sink on, or ``None`` for the
    ungated sink. The commanded current is ``v(ilc)``, set by the deck's
    ``Vilc``.
    """
    expr = f"v(ilc) * {_gate(vout.lower(), VOUT_KNEE_V, VOUT_SOFT_V)}"
    if supply_gate is not None:
        expr += f" * {_gate(supply_gate.lower(), VIN_KNEE_V, VIN_SOFT_V)}"
    return f"Bload{suffix} {vout} {nload} I = '{expr}'"


#: Every ``@TOKEN@`` a deck fragment may use for the sink -> its card.
TOKENS = {
    "BLOAD": bload(),
    "BLOAD_VIN_GATED": bload(supply_gate="vin"),
    "BLOAD_FULL": bload(suffix="_full", vout="VOUT_FULL", nload="NLOAD_FULL"),
}


def render(text: str, *, source: str = "deck fragment") -> str:
    """*text* with every sink token filled; text without tokens is unchanged.

    Raises (via :func:`harness.deck.render`) on any ``@TOKEN@`` that is not a
    sink token, so a typo cannot reach ngspice as literal text.
    """
    return deck.render(text, TOKENS, source=source) if deck.tokens(text) else text
