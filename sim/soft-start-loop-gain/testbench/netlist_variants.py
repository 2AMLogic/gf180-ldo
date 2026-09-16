#!/usr/bin/env python3
"""DUT netlist variants for the soft-start loop-gain experiment (issue #196).

This module builds, from ``design/netlist/ldo_core.spice``, the handful of
netlists this experiment needs. It never writes anything under ``design/``:
every variant is a *derived copy* the sweep freezes into
``netlist-snapshots/`` alongside the record it produced.

Five kinds of transform, each deliberately as small as it can be:

1. **SSR port promotion** (every variant). ``ldo_softstart``'s ramp node
   ``SSR`` is appended to ``ldo_softstart``'s port list, to ``ldo_core``'s,
   and to the ``Xsoftstart`` instance line. ``SSR`` is already a node of the
   cell, so naming it in a port list renames nothing, connects nothing and
   creates nothing -- it only lets the deck reach the node. The sweep's
   "anchor" phase leaves the new port unconnected and measures that this is
   so, by reproducing ``sim/loop-stability/``'s own record through it.

2. **DUT variant** ``device`` **/** ``binj``: ``device`` is
   ``design/netlist/ldo_softstart.spice`` as committed today; ``binj``
   replaces the whole ``ldo_softstart`` subcircuit with the pre-#195 one from
   commit ``bfc4a0a``, leaving the rest of ``ldo_core`` -- pass device,
   divider, error amp, current limit -- byte for byte identical.

   NOTE (issue #234): this pair used to be an injection-ELEMENT A/B --
   ``device`` was the post-#195 device-level Mgm* transconductor chain,
   ``binj`` the ideal ``Binj_ss`` behavioural source, and the two differed in
   the injection element and nothing else. Issue #231 (PR #233) reverted the
   device-level chain back to ``Binj_ss``, so as of that revert **``device``
   also uses ``Binj_ss``**: the two variants differ ONLY in three MIM-cap
   lengths -- ``XCss`` 12u<->60u, ``XCh_ss`` 14u<->70u, ``XCr_ss`` 14u<->70u,
   the `spec/decision-records/DR-0024-startup-current-budget-at-1uf.md`
   ramp-speed resize -- which ``binj`` (frozen before that resize landed)
   predates and ``device`` (`main` as committed) has. "The A/B is
   attributable to the injection element" is therefore no longer true of the
   CURRENT tree; it stays true of the historical record this module can still
   reproduce (`sim/soft-start-loop-gain/records/20260910-015601-2387ece.md`),
   which was measured against the device-level chain before the revert.
   ``binj`` is kept regardless, because it is still the ideal,
   closed-form-transfer variant ``selftest.py`` and the hand-over deck check
   the metric code against -- not because it isolates an injection element
   the current tree no longer has two versions of.

3. **AC-open sensitivity**: a named device's drain is moved onto a private
   node and reconnected through a 1 GH inductor. At DC an inductor is a
   short, so the operating point is *bit-identical*; in band it is an open,
   so the device's small-signal loading of that node is removed. This is the
   element-removal measurement the pole/zero attribution rests on -- it
   isolates one element's AC contribution without moving the bias point the
   margin is a statement about. ``ac_open()`` refuses a ``B``-prefixed
   (behavioural source) instance (issue #234): a series inductor removes a
   MOSFET's small-signal admittance, not an ideal source's frequency-flat
   output, so the same transform against a behavioural line would apply
   without raising and measure nothing.

4. **AC-short sensitivity**: a named node is tied to a rail through a 1 F
   capacitor. At DC a capacitor is an open, so again the operating point is
   bit-identical; in band the node is a short to that rail, so whatever pole
   sat on it is removed. ``add_cap()`` (shared by this and (5)) refuses a
   node that is not already a token anywhere in the supplied netlist (issue
   #234): a capacitor onto a node nothing else touches is floating, and the
   transform would otherwise apply without raising and measure nothing.

5. **AC-load budget**: the inverse of (3). A *known* capacitance is hung on a
   node -- same code path as (4), because a capacitor is an open at DC at any
   value -- so the question becomes "how much can this node take" rather than
   "what was this element worth". That turns a verdict about one injection
   element into a budget any future one can be checked against.

Every transform is a pure text operation on the netlist, asserts that it
matched exactly what it expected to match, and raises rather than silently
producing a netlist that is not what the caller asked for. ``selftest.py``
and ``sim/tests/test_soft_start_loop_gain.py`` exercise all five.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# The commit the pre-#195 (ideal ``Binj_ss``) soft-start netlist is taken
# from -- the same one `sim/soft-start/records/20260906-202950-bfc4a0a.md`
# was minted from. NOT reachable by a plain clone of `main`'s history; see
# fetch_pre195_softstart() below.
PRE195_COMMIT = "bfc4a0a6e8f59361dfbf6fd16f2653ae3f5cdcd8"
PRE195_SHORT = "bfc4a0a"
PRE195_PATH = "design/netlist/ldo_softstart.spice"

CORE_PORTS = ".subckt ldo_core VIN VOUT EN VSS ERRAMP_OUT PASS_GATE VREF"
SS_PORTS = ".subckt ldo_softstart VIN FB PASS_GATE EN VREF VSS BG"
SS_INSTANCE = "Xsoftstart VIN FB PASS_GATE EN VREF VSS BG ldo_softstart"
SS_BLOCK_RE = re.compile(r"(?ms)^\.subckt ldo_softstart\b.*?^\.ends[ \t]*$")

# The variants the sweep runs across the whole PVT grid.
DUT_VARIANTS = ("device", "binj")

VARIANT_BLURB = {
    "device": (
        "`design/netlist/ldo_softstart.spice` as committed -- as of issue "
        "#231/PR #233 this is the ideal `Binj_ss` behavioural source, the "
        "SAME injection element `binj` uses; the two variants now differ "
        "ONLY in the DR-0024 MIM-cap resize (`XCss`/`XCh_ss`/`XCr_ss`), not "
        "in the injection element (see #234)"
    ),
    "binj": (
        f"ideal behavioural injection source `Binj_ss`, frozen pre-DR-0024 "
        f"cap sizing from commit `{PRE195_SHORT}` (also pre-#195, but #195's "
        f"device-level chain was reverted by #231 and is no longer what "
        f"distinguishes this from `device`)"
    ),
}


class TransformError(RuntimeError):
    """A netlist transform did not match what it expected to match."""


def fetch_pre195_softstart(repo_root: Path) -> str:
    """``git show bfc4a0a:design/netlist/ldo_softstart.spice``.

    ``bfc4a0a`` is a real commit in the GitHub repository but is **not** an
    ancestor of ``main``, so a fresh clone/worktree cannot resolve it until
    it has been fetched by hash. Do that here rather than making the caller
    remember, and fail with the actionable command if even that does not
    work (e.g. no network).
    """
    def show() -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{PRE195_SHORT}:{PRE195_PATH}"],
            capture_output=True, text=True,
        )

    proc = show()
    if proc.returncode != 0:
        subprocess.run(
            ["git", "-C", str(repo_root), "fetch", "origin", PRE195_COMMIT],
            capture_output=True, text=True,
        )
        proc = show()
    if proc.returncode != 0:
        raise TransformError(
            f"cannot read {PRE195_PATH} at {PRE195_SHORT}. That commit is not "
            f"an ancestor of main, so it needs an explicit fetch:\n"
            f"    git fetch origin {PRE195_COMMIT}\n"
            f"git said: {proc.stderr.strip()}"
        )
    return proc.stdout


def _replace_once(text: str, old: str, new: str, what: str) -> str:
    n = text.count(old)
    if n != 1:
        raise TransformError(
            f"{what}: expected exactly one occurrence of {old!r}, found {n}"
        )
    return text.replace(old, new)


_TOKEN_BOUNDARY = r"(?<![A-Za-z0-9_.])({})(?![A-Za-z0-9_.])"


def _node_appears(text: str, node: str) -> bool:
    """Whether ``node`` is already a token somewhere in ``text``.

    Used to refuse hanging a capacitor on a node that is not actually part of
    the circuit -- see ``add_cap()``'s docstring and issue #234's
    ``acshort-gmsum`` post-mortem, where the target node had been removed
    from ``ldo_softstart`` and the transform ran anyway, on a node with no
    other connection.
    """
    pattern = re.compile(_TOKEN_BOUNDARY.format(re.escape(node)), re.IGNORECASE)
    return pattern.search(text) is not None


def promote_ssr_port(softstart_block: str) -> str:
    """Append ``SSR`` to ``ldo_softstart``'s port list. Nothing else."""
    return _replace_once(
        softstart_block, SS_PORTS, SS_PORTS + " SSR", "SSR port promotion"
    )


def instrument_core(core_text: str, softstart_block: str | None = None) -> str:
    """``ldo_core.spice`` with ``SSR`` brought out, and optionally a different
    ``ldo_softstart`` spliced in.

    ``softstart_block`` is a complete ``.subckt ldo_softstart ... .ends``
    block (the pre-#195 one, say). ``None`` keeps the block already in
    ``core_text``. Either way the block that ends up in the output has its
    ``SSR`` port promoted, and everything outside that block is untouched
    apart from the two port/instance lines named below.
    """
    m = SS_BLOCK_RE.search(core_text)
    if not m:
        raise TransformError(
            "no `.subckt ldo_softstart ... .ends` block in the core netlist"
        )
    block = softstart_block if softstart_block is not None else m.group(0)
    inner = SS_BLOCK_RE.search(block)
    if not inner:
        raise TransformError(
            "the replacement soft-start netlist has no "
            "`.subckt ldo_softstart ... .ends` block"
        )
    block = promote_ssr_port(inner.group(0))

    head, tail = core_text[: m.start()], core_text[m.end():]
    head = _replace_once(head, CORE_PORTS, CORE_PORTS + " SSR", "ldo_core ports")
    head = _replace_once(
        head, SS_INSTANCE, SS_INSTANCE.replace(" ldo_softstart", " SSR ldo_softstart"),
        "Xsoftstart instance",
    )
    return head + block + "\n" + tail.lstrip("\n")


def build_variant(repo_root: Path, variant: str) -> str:
    """The SSR-instrumented ``ldo_core`` netlist for one DUT variant."""
    core = (repo_root / "design" / "netlist" / "ldo_core.spice").read_text()
    if variant == "device":
        return instrument_core(core)
    if variant == "binj":
        return instrument_core(core, fetch_pre195_softstart(repo_root))
    raise TransformError(f"unknown DUT variant {variant!r}")


# --------------------------------------------------------------------------
# DC-preserving AC sensitivity transforms (the pole/zero attribution)
# --------------------------------------------------------------------------
AC_OPEN_H = "1e9"      # henries -- see ac_open() docstring
AC_SHORT_F = "1.0"     # farads  -- see ac_short() docstring


def ac_open(text: str, instance: str, node: str, tag: str) -> str:
    """Break ``instance``'s connection to ``node`` in AC only.

    The instance's terminal is moved onto a private node and reconnected to
    the original one through a 1 GH inductor:

        <instance> ... <node> ...        ->  <instance> ... <node>_<tag> ...
                                             L<tag> <node>_<tag> <node> 1e9

    An inductor is a short at DC, so the operating point is unchanged to the
    last digit -- which is the entire point: the margin being compared is a
    statement about a bias point, and a sensitivity test that also moves the
    bias point cannot attribute anything. In band it is an open: 1 GH is
    6.3e7 ohm at the sweep's 0.01 Hz floor and 6.3e13 ohm at 1 MHz, against
    the ~200 kohm the feedback node presents, so the branch is removed
    everywhere the margins are read.

    Only the FIRST matching terminal occurrence on the instance line is
    moved, so the caller must name a node the instance touches exactly once.

    Refuses a ``B``-prefixed (behavioural source) instance outright -- see
    issue #234. A series inductor removes a MOSFET's small-signal DRAIN
    admittance, which is the whole point of this transform; for an IDEAL
    current/voltage source it removes nothing, because KCL at the private
    node forces the inductor's current to equal the source's output at every
    frequency, so the far terminal sees an identical waveform with or
    without the inductor. The transform would apply without raising and
    produce a delta that is zero by construction, not by measurement -- which
    is exactly the `acopen-fb-inj` mistake this issue exists to fix, and
    which must not be re-recordable as an element-removal measurement.
    """
    if instance[:1].upper() == "B":
        raise TransformError(
            f"ac_open: {instance!r} is a behavioural (B-prefixed) source, "
            "not a device -- a series inductor is not an AC open for an "
            "ideal source (KCL forces the inductor current to equal the "
            "source's output at every frequency, so the far terminal sees "
            "the identical waveform with the inductor in place or not; the "
            "delta this would measure is zero by construction, not by "
            "measurement -- see issue #234). Null the source's AC "
            "contribution directly instead of trying to open its terminal."
        )
    lines = text.splitlines()
    hits = [i for i, ln in enumerate(lines) if ln.split()[:1] == [instance]]
    if len(hits) != 1:
        raise TransformError(
            f"ac_open: expected exactly one instance line for {instance!r}, "
            f"found {len(hits)}"
        )
    i = hits[0]
    toks = lines[i].split()
    where = [k for k, t in enumerate(toks) if t.upper() == node.upper()]
    if len(where) != 1:
        raise TransformError(
            f"ac_open: {instance!r} touches node {node!r} {len(where)} times "
            f"(need exactly 1): {lines[i]}"
        )
    priv = f"{node}_{tag}"
    toks[where[0]] = priv
    lines[i] = " ".join(toks)
    # The netlist exporter wraps long device lines onto `+` continuations, so
    # the inductor has to go AFTER the last of them -- inserting between an
    # instance line and its continuation silently truncates the instance's
    # parameter list (ngspice then reports "Undefined parameter [nf]").
    j = i + 1
    while j < len(lines) and lines[j].startswith("+"):
        j += 1
    lines.insert(j, f"L{tag} {priv} {node} {AC_OPEN_H}")
    return "\n".join(lines) + "\n"


def add_cap(text: str, node: str, rail: str, farads: str, tag: str) -> str:
    """Put a capacitor from ``node`` to ``rail`` inside ``ldo_softstart``.

    A capacitor is an open at DC, so the operating point cannot move whatever
    the value is -- which is what makes this usable both as an AC short (a
    huge value, ``ac_short()``) and as a deliberate parasitic load (a small
    one, ``ac_load()``), with the same guarantee in both directions.

    Refuses a ``node`` that does not already appear anywhere in ``text`` --
    see issue #234's ``acshort-gmsum`` post-mortem, where the target node had
    been removed from ``ldo_softstart`` by an earlier revert and this
    function hung a capacitor on it anyway: a capacitor to a node with no
    other connection is floating (no DC path to ground, and no AC coupling
    to anything either), so the transform ran without raising and measured
    nothing. A node that is a real terminal or subckt port is always already
    a token in the netlist text, so this check costs nothing on a legitimate
    call.
    """
    if not _node_appears(text, node):
        raise TransformError(
            f"add_cap: node {node!r} does not appear anywhere in the "
            "supplied netlist. A capacitor onto a node with no other "
            "connection is floating -- it has no DC path to ground and "
            "couples to nothing in AC either, so the transform would run "
            "without raising and measure nothing (see issue #234's "
            "acshort-gmsum post-mortem). Name a node that is actually a "
            "terminal of some instance, or a port, in this netlist."
        )
    lines = text.splitlines()
    marker = ".subckt ldo_softstart"
    for i, ln in enumerate(lines):
        if ln.startswith(marker):
            lines.insert(i + 1, f"C{tag} {node} {rail} {farads}")
            return "\n".join(lines) + "\n"
    raise TransformError("add_cap: no ldo_softstart subckt to insert into")


def ac_short(text: str, node: str, rail: str, tag: str) -> str:
    """Tie ``node`` to ``rail`` in AC only, with a 1 F capacitor.

    A capacitor is an open at DC, so again the operating point does not move;
    1 F is 16 ohm at the sweep's 0.01 Hz floor, far below any node impedance
    in this circuit, so the node is an AC short to the rail across the whole
    band. Used to ask "is the pole on this node the one that matters?".
    """
    return add_cap(text, node, rail, AC_SHORT_F, tag)


def ac_load(text: str, node: str, rail: str, farads: float, tag: str) -> str:
    """Hang a deliberate parasitic capacitance on ``node``.

    The inverse question to ``ac_open()``. Instead of removing an element's
    coupling and asking what it was worth, this ADDS a known capacitance and
    asks how much the node can take before the margin bar is crossed -- i.e.
    it turns "the injection element's parasitics are negligible" from a
    verdict about one element into a budget any future injection element can
    be checked against. DC-inert for the same reason ``ac_short()`` is.
    """
    return add_cap(text, node, rail, f"{farads:g}", tag)
