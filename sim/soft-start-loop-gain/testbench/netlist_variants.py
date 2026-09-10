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

2. **Injection-element variant**: ``device`` keeps the post-#195 device-level
   transconductor that is on ``main`` today; ``binj`` replaces the whole
   ``ldo_softstart`` subcircuit with the pre-#195 one from commit ``bfc4a0a``
   (the ideal ``Binj_ss`` behavioural source), leaving the rest of
   ``ldo_core`` -- pass device, divider, error amp, current limit -- byte for
   byte identical. That is what makes the A/B attributable to the injection
   element and to nothing else.

3. **AC-open sensitivity**: a named device's drain is moved onto a private
   node and reconnected through a 1 GH inductor. At DC an inductor is a
   short, so the operating point is *bit-identical*; in band it is an open,
   so the device's small-signal loading of that node is removed. This is the
   element-removal measurement the pole/zero attribution rests on -- it
   isolates one element's AC contribution without moving the bias point the
   margin is a statement about.

4. **AC-short sensitivity**: a named node is tied to a rail through a 1 F
   capacitor. At DC a capacitor is an open, so again the operating point is
   bit-identical; in band the node is a short to that rail, so whatever pole
   sat on it is removed.

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
        "post-#195 device-level transconductor "
        "(`Rgma_ss/Mgma_ss/Mgmd_ss/Rgmb_ss/Mgmb_ss/Mgmm_ss/Mgmr_ss/Mgmo_ss/"
        "Mgme_ss`), i.e. `design/netlist/ldo_softstart.spice` as committed"
    ),
    "binj": (
        f"pre-#195 ideal behavioural injection source `Binj_ss`, frozen from "
        f"commit `{PRE195_SHORT}`"
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
    """
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
    """
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
