#!/usr/bin/env python3
"""Run DRC and LVS on a registered gf180mcu layout cell -- one command.

    python3 layout/drclvs.py                     # bring-up test cell (default)
    python3 layout/drclvs.py --cell testcell      # same, named explicitly
    python3 layout/drclvs.py --cell passives      # the passive-bearing flow vehicle
    python3 layout/drclvs.py --cell pass_array    # the LDO's pass-device array (#285)
    python3 layout/drclvs.py --cell divider       # the feedback-divider array (#286)
    python3 layout/drclvs.py --check             # same, plus: the committed netlist must be current
    python3 layout/drclvs.py --check-env         # report which tools/PDK are visible, then stop
    python3 layout/drclvs.py --record            # also write layout/records/<record-id>.md
    python3 layout/drclvs.py --keep              # keep the run directory (default: keep only on failure)

Exit status is 0 only if **every** stage passed. See layout/README.md for what
each stage means and what it does and does not prove.

Driving a real block through this flow
---------------------------------------
This file used to be hardcoded to the one-transistor bring-up test cell
(issue #14). It is now a **generalized driver**: the stages below take a
:class:`CellSpec` -- a GDS generator script, an LVS reference schematic, a
substrate net, this cell's own topology/parameter pair of LVS negative
controls, and where the exported netlist is committed -- rather than
module-level constants for the test cell specifically. ``CELLS`` is the
registry a real block's layout plugs into; add an entry there (see
``TESTCELL_SPEC`` / ``DIVIDER_SPEC`` for the shape) and drive it with
``--cell <key>``.
Nothing about the stages is test-cell-specific; only the registered
cell specs and their generators are.

The stage COUNT is a property of the cell, not a constant: stages 1-5 always
run, and stage 6 onwards is one LVS negative control per corruption the
netlist can express (see ``build_controls``). A FET-only cell has 7 stages; a
cell that also contains a resistor and a capacitor has 9; the all-resistor
feedback divider has 8.

What this runs, in order
------------------------

1. **Build the layout.** ``klayout -b -r <the cell's gen_gds.py>``, which draws
   the cell from the PDK's *own* PCells (correct by construction) and adds the
   net labels LVS needs.
2. **Export the schematic netlist.** ``xschem`` headless, ERC on, through
   ``layout/xschemrc`` -- which is ``design/xschemrc`` plus ``lvs_netlist 1``,
   so devices render from the PDK symbols' ``lvs_format`` (``M1 D G S VSS
   nfet_03v3 L=.. W=.. nf=.. m=..``) rather than their ngspice ``format``
   (``XM1 ... ad='int((nf+1)/2) * ...'``, which KLayout's SPICE reader cannot
   evaluate). The xschem invocation itself is shared with
   ``design/netlist.py`` via ``sim/harness/xschem_export.py``.
3. **DRC, klt.** ``klt drc --deck gf180mcu --format json``. This is the
   agent-facing, JSON-contracted path; it is also a **curated 13-rule subset**,
   not signoff. See "Coverage, honestly" in layout/README.md.
4. **DRC, the PDK's own deck.** The full gf180mcu KLayout deck, assembled the
   way the PDK's ``run_drc.py`` assembles it (``main.drc`` + every rule table +
   ``tail.drc``, with ``layers_def.drc`` beside it). Hundreds of rule
   categories. This is the DRC result worth quoting.
5. **LVS.** The PDK's own ``gf180mcu.lvs`` deck, layout vs. the netlist from
   step 2.
6. **LVS negative control -- topology.** The same compare against a copy of that
   netlist with the connection graph deliberately corrupted (for a MOS cell:
   the device's gate shorted to its drain; for an all-passive one: two
   adjacent taps of the string shorted). Must report a mismatch.
7. **LVS negative control -- device parameters.** And against a copy with a
   device dimension doubled (the MOS width; for an all-passive cell, the
   first unit resistor's width) but the topology untouched. Must also report
   a mismatch.
8+. **LVS negative controls -- passive geometry.** One more per passive element
   class the netlist contains (``R``, ``C``), each with that device's length
   doubled. Registered only when the class is present, so a FET-only cell stops
   at stage 7.

   None of these are decoration. Without them, "LVS passed" is not evidence
   that the compare looked at anything: a mis-wired invocation that silently
   compares nothing also "passes"; a compare that checks connectivity but
   ignores device parameters would wave through a mis-sized transistor; and one
   that compares MOS parameters but not passive geometry would wave through a
   resistor of the wrong length -- which matters here because the deck
   deliberately does NOT compare resistance or capacitance itself (see
   ``layout/lvs_form.py``). Each control isolates one of those.

   **Which stage 6/7 pair runs is a property of the cell**, not of this file:
   ``CellSpec.controls``. A MOS-keyed mutation cannot corrupt a resistor-only
   netlist and vice versa, so a cell registers the pair that matches its own
   devices (``MOS_CONTROLS`` / ``PASSIVE_CONTROLS``); the passive-geometry
   controls of stage 8+ are then added from the netlist. That every one of
   those controls can in fact corrupt this cell's netlist is checked **before
   stage 3** by ``check_controls_apply()``, and a control that cannot is a
   hard error -- never a silently skipped stage, because a run that printed
   ``lvs: MATCH`` with inert controls behind it would be reporting a pass it
   has not earned.

Nothing here is LDO-specific in the stages themselves: only the registered
``CellSpec`` is. Two of the three cells registered today are flow vehicles
rather than design blocks -- ``testcell`` (the default) is one transistor, and
``passives`` adds an H-poly resistor and a MIM cap because a FET-only cell
cannot notice that the flow is broken for anything else (issue #313).
``pass_array`` is the first real block: the LDO's 40-unit-cell pass device and
its ``Msense`` replica (issue #285, under epic #173). ``divider`` is the
second, and the first all-passive one: layout/floorplan.md §4.1's
common-centroid feedback-divider array (issue #286). Driving another block
through this means registering that block's own ``CellSpec`` in ``CELLS``
below.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

LAYOUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = LAYOUT_DIR.parent
TESTCELL_DIR = LAYOUT_DIR / "testcell"
PASSIVES_DIR = LAYOUT_DIR / "passives"
PASS_ARRAY_DIR = LAYOUT_DIR / "pass_array"
DIVIDER_DIR = LAYOUT_DIR / "divider"
RECORDS_DIR = LAYOUT_DIR / "records"
WORK_DIR = LAYOUT_DIR / ".work"
XSCHEMRC = LAYOUT_DIR / "xschemrc"

# design/netlist/ holds the *simulation* netlists design/netlist.py generates
# and every sim/ testbench sources. Stage 2 writes `netlist_dir/<cell>.spice`
# unconditionally, so a CellSpec pointing netlist_dir there would silently
# overwrite one of them with the LVS-form export -- a corruption nothing
# re-checks until a sim run breaks. CellSpec.__post_init__ refuses it.
SIM_NETLIST_DIR = REPO_ROOT / "design" / "netlist"


# A registered cell must carry one negative control of each kind: one that
# corrupts the connection graph and one that corrupts a device parameter
# while leaving the graph alone. Those are two independent ways for an LVS
# invocation to be comparing less than it appears to, and a cell with only
# one of them has only half an evidence chain (layout/README.md, "6 onwards.
# Negative controls").
REQUIRED_CONTROL_TAGS = ("topology", "parameter")


class StageError(RuntimeError):
    """A stage could not run at all (missing tool, bad invocation)."""


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


@dataclasses.dataclass(frozen=True)
class CellSpec:
    """Everything the stages need to know about one layout cell.

    A real block's layout registers one of these in ``CELLS`` instead of
    editing the stage functions below -- the stages themselves are generic.
    """

    key: str
    # Base name used for generated file names (<cell>.gds, <cell>.spice, ...)
    # and, by convention, the schematic's own .subckt name.
    cell: str
    # The layout top cell name gen_gds emits -- the DRC/LVS decks' `topcell`
    # switch. Not necessarily equal to `cell` (see testcell: DRCLVS_TESTCELL).
    top_cell: str
    # klayout -b -r script that builds the GDS (see layout/testcell/gen_gds.py
    # for the expected -rd out=/-rd pdk= contract).
    gen_gds: Path
    # The .sch xschem netlists in LVS form for the LVS reference netlist.
    schematic: Path
    # Where the committed LVS reference netlist (<cell>.spice) lives. Stage 2
    # WRITES `netlist_dir/<cell>.spice` (unless --check), so this must be a
    # directory owned by the layout flow -- by convention layout/<block>/netlist/,
    # mirroring layout/testcell/netlist/. It must NOT be design/netlist/, which
    # holds the simulation netlists design/netlist.py generates; __post_init__
    # enforces that, see SIM_NETLIST_DIR.
    netlist_dir: Path
    # Directories joined into XSCHEM_USER_LIBRARY_PATH so the schematic's own
    # symbol references resolve (e.g. design/ for a cell that instantiates
    # design/error_amp.sym and friends).
    xschem_library_paths: tuple[Path, ...]
    # The two (or more) LVS negative controls stages 6..N run against this
    # cell. See REQUIRED_CONTROL_TAGS: a cell must register a topology
    # control and a parameter control, and every one of them must actually
    # apply to this cell's netlist (check_controls_apply, called before any
    # LVS run, turns "this control does nothing here" into a hard error).
    controls: tuple[Control, ...]
    # The schematic's bulk/substrate port == the LVS deck's lvs_sub switch.
    substrate_net: str = "VSS"
    # The LVS deck's `poly_res` switch: which high-sheet ppolyf_u_* flavour
    # the deck extracts. A `case POLY_RES` in rule_decks/res_extraction.lvs
    # means exactly one of 1k/2k/3k is recognised per run, so a cell built
    # from ppolyf_u_3k units is unextractable -- and mismatches -- under the
    # default. Not a free choice: it is which flavour the cell is drawn in.
    poly_res: str = "1k"
    # Whether the LVS deck may collapse series/parallel device chains in the
    # EXTRACTED netlist before comparing (`netlist.simplify`). Harmless for a
    # cell whose devices cannot be combined; for a unit-resistor string it
    # erases the very structure the layout exists to prove, so such a cell
    # sets this False. See run_lvs() for how the deck's switches express it.
    simplify_extracted: bool = True
    # One-line human description, quoted verbatim in --record's run record.
    description: str = ""
    # What a passing run of THIS cell does not establish, quoted verbatim in
    # --record's run record. Left empty for a real block, where the generic
    # "certifies exactly this cell, nothing more" note is the right one; a
    # flow vehicle sets it so no record can be read as a claim about the LDO.
    scope_note: str = ""
    # Extra markdown sections --record appends to the run record: whatever
    # this cell's own verification claim needs stated alongside the verdicts
    # (for a matched array, the as-drawn matching against floorplan.md's
    # numeric target). Derived, not typed in -- see _divider_record_note().
    record_notes: str = ""

    def __post_init__(self) -> None:
        # Structural guard, not a convention: a CellSpec that would clobber a
        # simulation netlist cannot be constructed at all, so the mistake is
        # an import-time crash with a name attached rather than a silently
        # corrupted design/netlist/<cell>.spice discovered days later by a
        # failing sim run. Checked on the resolved path so `../design/netlist`
        # and a symlink to it are caught too.
        target = self.netlist_dir.resolve()
        forbidden = SIM_NETLIST_DIR.resolve()
        if target == forbidden or forbidden in target.parents:
            raise ValueError(
                f"CellSpec({self.key!r}).netlist_dir points inside "
                f"{forbidden}, which holds the SIMULATION netlists "
                "design/netlist.py generates and every sim/ testbench "
                "sources. layout/drclvs.py stage 2 writes "
                f"{self.netlist_dir}/{self.cell}.spice unconditionally, so "
                "this would overwrite one of them with the LVS-form export. "
                f"Use a layout-owned directory instead, e.g. "
                f"{LAYOUT_DIR / self.key / 'netlist'}."
            )


sys.path.insert(0, str(LAYOUT_DIR))
from lvs_form import (  # noqa: E402
    LvsFormError,
    rewrite_passives,
    unrendered_device_lines,
)

sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness.pdk import Pdk, PdkNotFound, find_pdk  # noqa: E402
from harness.report import (  # noqa: E402
    RecordExists,
    allocate_record_id,
    write_markdown_record,
)
from harness.xschem_export import XschemExportError, run_xschem_netlist  # noqa: E402

# metal_top / mim_option / metal_level per gf180mcu variant, transcribed from
# the PDK's own libs.tech/klayout/lvs/run_lvs.py (and the identical table in
# run_drc.py). The variant is not a free choice: it is which metal stack the
# installed PDK was built for.
VARIANT_SWITCHES = {
    "A": {"metal_top": "30K", "mim_option": "A", "metal_level": "3LM"},
    "B": {"metal_top": "11K", "mim_option": "B", "metal_level": "4LM"},
    "C": {"metal_top": "9K", "mim_option": "B", "metal_level": "5LM"},
    "D": {"metal_top": "11K", "mim_option": "B", "metal_level": "5LM"},
}

# xschem's `format` (simulation) rendering of a PDK device, which must NOT
# appear in an LVS-form netlist. See layout/xschemrc.
SIM_FORM_RE = re.compile(r"^\s*[Xx]\S+\s+.*\b(nfet|pfet|ppolyf|npolyf|cap_)", re.M)


# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------

def tool_path(name: str) -> str | None:
    return shutil.which(name)


def check_env(verbose: bool = True) -> tuple[bool, Pdk | None]:
    """Report tool + PDK availability. Returns (ok, pdk)."""
    ok = True
    rows = []
    for tool, why in (
        ("klayout", "DRC/LVS engine; runs the PDK's own decks (klayout -b -r)"),
        ("klt", "klayout-tools: JSON-contracted DRC (klt drc --deck gf180mcu)"),
        ("xschem", "schematic capture; exports the LVS reference netlist"),
    ):
        path = tool_path(tool)
        rows.append((tool, path or "NOT FOUND", why))
        if path is None:
            ok = False

    pdk: Pdk | None = None
    try:
        pdk = find_pdk()
    except PdkNotFound as exc:
        ok = False
        pdk_line = f"NOT FOUND -- {exc}"
    else:
        pdk_line = f"{pdk.path} (variant {pdk.variant})"
        for sub, label in (
            (pdk.klayout_dir / "drc" / "rule_decks" / "main.drc", "DRC rule decks"),
            (pdk.klayout_dir / "lvs" / "gf180mcu.lvs", "LVS deck"),
            (pdk.path / "libs.tech" / "klayout" / "tech" / "pymacros", "PCell library"),
        ):
            if not sub.exists():
                ok = False
                pdk_line += f"\n    MISSING {label}: {sub}"

    if verbose:
        print("tools:")
        for tool, path, why in rows:
            print(f"  {tool:<8} {path}")
            print(f"           {why}")
        if tool_path("pmap") is None:
            print(
                "  pmap     NOT FOUND -- not required; the PDK decks' memory "
                "logger calls it,\n"
                "           and drclvs.py supplies a ps(1)-backed stand-in on "
                "hosts without it."
            )
        print(f"\npdk:\n  {pdk_line}")
        if pdk is not None and pdk.variant[-1] not in VARIANT_SWITCHES:
            print(
                f"  WARNING: variant {pdk.variant} does not end in one of "
                f"{sorted(VARIANT_SWITCHES)}; the metal-stack switches below "
                f"will fall back to D."
            )
        print(f"\nresult: {'ok' if ok else 'INCOMPLETE'}")
        if not ok:
            print(
                "\nSee layout/README.md ('Getting the tools') for how to install "
                "what is missing."
            )
    return ok, pdk


def variant_switches(pdk: Pdk) -> dict[str, str]:
    letter = pdk.variant[-1].upper()
    return dict(VARIANT_SWITCHES.get(letter, VARIANT_SWITCHES["D"]))


# --------------------------------------------------------------------------
# host portability: the PDK decks' `pmap` dependency
# --------------------------------------------------------------------------

# The gf180mcu DRC and LVS decks install a Ruby Logger formatter that shells
# out to pmap(1) on EVERY log line:
#
#     "#{datetime}: Memory Usage (" + `pmap #{Process.pid} | tail -1`[10, 40].strip + ...
#
# pmap is procps, i.e. Linux-only. On a host without it the backtick returns
# "", `""[10, 40]` is nil, and `nil.strip` raises -- so the deck dies on its
# very first logger.info(), before it has run a single rule. The failure reads
# as `undefined method 'strip' for nil` in main.drc, which looks like a deck
# bug rather than a missing utility.
#
# Rather than let that make the whole flow Linux-only, supply a pmap that
# reports the process's real RSS via ps(1), on PATH for the deck subprocesses
# only. Truthful (the number is this process's actual resident size, in KiB,
# which is what pmap's own `total` line reports) and scoped (it lives in the
# gitignored run directory and is never put on the caller's PATH).
PMAP_SHIM = """\
#!/bin/sh
# pmap(1) stand-in, written by layout/drclvs.py for hosts without procps.
# Emits one pmap-style "total <N>K" line for the pid in $1, from ps(1)'s RSS,
# because the gf180mcu decks' logger parses column 10.. of `pmap <pid> | tail -1`.
rss=$(ps -o rss= -p "${1:-$$}" 2>/dev/null | tr -d ' ')
[ -n "$rss" ] || rss=0
printf 'total %12sK\\n' "$rss"
"""


def deck_env(run_dir: Path) -> tuple[dict[str, str], str]:
    """Environment for a PDK-deck klayout subprocess.

    Returns ``(env, provenance)`` where ``provenance`` is ``"host"`` when the
    host has a real pmap(1) and ``"shimmed"`` when this function supplied the
    stand-in above -- the run record prints it, so a record never implies a
    stock toolchain when one stage ran against a substitute.
    """
    env = dict(os.environ)
    if tool_path("pmap") is not None:
        return env, "host"
    shim_dir = run_dir / "shims"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "pmap"
    shim.write_text(PMAP_SHIM)
    shim.chmod(0o755)
    env["PATH"] = os.pathsep.join([str(shim_dir), env.get("PATH", "")])
    return env, "shimmed"


# --------------------------------------------------------------------------
# stage 1 -- layout
# --------------------------------------------------------------------------

def build_gds(pdk: Pdk, spec: CellSpec, out: Path, log: Path) -> str:
    """Draw the cell. Returns whatever the generator printed about it.

    The generator is the only thing in this flow that knows what it actually
    drew -- how many unit cells, how wide the straps came out, how many via
    cuts fitted. ``--record`` quotes this verbatim (see ``write_record``), so
    those as-drawn numbers land in the append-only record rather than having
    to be transcribed by hand into it afterwards.
    """
    cmd = [
        "klayout", "-b", "-r", str(spec.gen_gds),
        "-rd", f"out={out}",
        "-rd", f"pdk={pdk.path}",
    ]
    output = run_logged(cmd, log, "layout build")
    if not out.is_file():
        raise StageError(f"layout build produced no {out} (see {log})")
    return output


# --------------------------------------------------------------------------
# stage 2 -- schematic netlist
# --------------------------------------------------------------------------

def export_netlist(pdk: Pdk, spec: CellSpec, outdir: Path) -> str:
    """Netlist ``spec``'s cell in LVS form. Returns the normalized text."""
    env = dict(os.environ)
    env["PDK_ROOT"] = str(pdk.path.parent)
    env["PDK"] = pdk.variant
    env["GF180_PDK_PATH"] = str(pdk.path)
    env["XSCHEM_USER_LIBRARY_PATH"] = os.pathsep.join(
        str(p) for p in spec.xschem_library_paths
    )
    sch = spec.schematic
    try:
        text = run_xschem_netlist(sch, outdir, env, XSCHEMRC)
    except XschemExportError as exc:
        raise StageError(str(exc)) from exc

    # The PDK's passive symbols carry no `lvs_format`, so `lvs_netlist 1`
    # leaves every resistor and capacitor in xschem's simulation form even
    # when the FETs come out right (issue #313). Render those as the
    # primitive R/C elements the LVS deck's SPICE reader delegate wants.
    # This runs BEFORE the SIM_FORM_RE guard on purpose: whatever
    # rewrite_passives() declined to touch is still a hard failure below.
    try:
        text, rewritten = rewrite_passives(text)
    except LvsFormError as exc:
        raise StageError(f"{exc}\n--- exported ---\n{text}") from exc

    if SIM_FORM_RE.search(text):
        raise StageError(
            "the exported netlist is in xschem's SIMULATION form "
            "(X-prefixed subcircuit calls), not the LVS form KLayout's SPICE "
            "reader needs.\n"
            "  This means `lvs_netlist` did not take effect. The usual cause is "
            "an xschem older than 3.4.6 -- the version Debian/Ubuntu package "
            "(3.4.4) has no `lvs_format` support at all and silently ignores "
            "the switch.\n"
            f"  `xschem --version` here: {tool_version('xschem', ['--version'])}\n"
            "  This repo pins 3.4.7; see docs/environment-setup.md.\n"
            f"--- exported ---\n{text}"
        )
    # Family-agnostic backstop behind SIM_FORM_RE, which only names the device
    # families this repo has needed so far: anything still X-prefixed AND
    # carrying a parameter tail is a device rendered from a symbol's `format`,
    # and KLayout's reader would silently compare it as an empty subcircuit.
    stragglers = unrendered_device_lines(text)
    if stragglers:
        raise StageError(
            "the exported netlist still contains device line(s) in xschem's "
            "SIMULATION form that layout/lvs_form.py does not know how to "
            "render as a primitive SPICE element:\n"
            + "".join(f"    {line}\n" for line in stragglers)
            + "  KLayout's SPICE reader would turn each of these into a call "
            "to an undefined subcircuit and compare it as an empty circuit, "
            "so the LVS verdict would be meaningless rather than wrong in an "
            "obvious way.\n"
            "  Add the family to layout/lvs_form.py (see its _FAMILIES table) "
            "if this design needs the device.\n"
            f"--- exported ---\n{text}"
        )
    if f".subckt {spec.cell}" not in text:
        raise StageError(
            f"the exported netlist has no `.subckt {spec.cell}` line -- "
            "xschem emitted the commented `**.subckt` form, which KLayout "
            "will not read. This is also an xschem-too-old symptom "
            f"(`xschem --version`: {tool_version('xschem', ['--version'])}; this repo pins 3.4.7).\n"
            f"--- exported ---\n{text}"
        )

    header = (
        f"* {spec.cell} -- generated by layout/drclvs.py from "
        f"{sch.relative_to(REPO_ROOT)}\n"
        f"* LVS reference netlist (xschem lvs_netlist form). Do not edit: edit\n"
        f"* the schematic and re-run the export.\n"
    )
    if rewritten:
        # Provenance: this netlist is not purely xschem's own rendering, and a
        # reader diffing it against an xschem export by hand deserves to know
        # which lines this repo produced and why.
        header += (
            f"* {rewritten} passive device line(s) rendered as primitive R/C\n"
            f"* elements by layout/lvs_form.py -- the PDK's resistor and MIM-cap\n"
            f"* symbols carry no lvs_format attribute (issue #313).\n"
        )
    return header + text


# --------------------------------------------------------------------------
# the LVS negative controls (stages 6..N)
#
# Each registered cell carries its own topology/parameter pair, because a
# mutation is only a control if it can actually be applied to that cell's
# devices: the MOS pair below cannot corrupt a resistor-only cell, and the
# passive pair cannot corrupt a cell with no resistors. build_controls() then
# adds one passive-geometry control per R/C element class the netlist
# contains. `check_controls_apply()` makes "this control does not apply" a
# hard error up front rather than a stage that quietly reports nothing.
# --------------------------------------------------------------------------

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


# `W=<number><unit>` on a MOS element line: 2u, 0.22u, 6u, 2e-6, 360U. The
# unit suffix is carried through unchanged, so the doubled value stays in the
# same units as the original.
W_TOKEN_RE = re.compile(
    r"^W=([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([a-zA-Z]*)$",
    re.IGNORECASE,
)


def _double(value: str) -> str:
    """Render ``value`` doubled, without gaining a spurious `.0`."""
    doubled = float(value) * 2
    if doubled.is_integer():
        return str(int(doubled))
    # repr() keeps the shortest round-tripping decimal (0.22 -> 0.44, not
    # 0.44000000000000006), which matters because this text goes into a
    # netlist a human may read in a failure report.
    return repr(doubled)


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
    resized = list(tokens)
    for index, token in enumerate(tokens):
        match = W_TOKEN_RE.match(token)
        if match is None:
            continue
        resized[index] = f"W={_double(match.group(1))}{match.group(2)}"
        break
    else:
        raise ControlNotApplicable(
            "expected a `W=<number>[unit]` parameter on the first MOS element "
            f"line, got: {line}"
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
    compare exactly as stage 7's MOS version does.
    """
    line, tokens = _resistor_line(text)
    resized = []
    hits = 0
    for token in tokens:
        match = re.fullmatch(
            r"(W)=([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)([a-zA-Z]*)",
            token,
            flags=re.IGNORECASE,
        )
        if match and hits == 0:
            hits += 1
            resized.append(f"{match.group(1)}={float(match.group(2)) * 2:g}{match.group(3)}")
        else:
            resized.append(token)
    if not hits:
        raise ControlNotApplicable(
            "expected a `W=` parameter on the first resistor element line, "
            f"got: {line}"
        )
    return text.replace(line, " ".join(resized))


# `l=<number><unit>` on a primitive R/C element line, as layout/lvs_form.py
# renders it. Separate from W_TOKEN_RE because the MOS convention in this
# repo's netlists is uppercase `L=`/`W=` while the passive convention (which
# the LVS deck's SPICE reader delegate reads) is lowercase `l=`/`w=`; both
# regexes are case-insensitive anyway, so the split is about which parameter
# each control corrupts, not about case.
L_TOKEN_RE = re.compile(
    r"^l=([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([a-zA-Z]*)$",
    re.IGNORECASE,
)

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
        found = _passive_line(text, letter)
        if found is None:
            raise ControlNotApplicable(
                f"no primitive {letter} element line with an `l=` parameter "
                "in the exported netlist"
            )
        line, tokens = found
        resized = list(tokens)
        for index, token in enumerate(tokens):
            match = L_TOKEN_RE.match(token)
            if match is None:
                continue
            resized[index] = f"l={_double(match.group(1))}{match.group(2)}"
            break
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


# --------------------------------------------------------------------------
# the cell registry
# --------------------------------------------------------------------------

def _load_module(name: str, path: Path):
    """Import a file by path, under a name of our choosing.

    Used for ``layout/divider/plan.py``, which is also imported -- under
    KLayout's interpreter, from its own directory -- by the divider's GDS
    generator. Loading it by path rather than by ``sys.path`` insertion keeps
    a bare module name like ``plan`` out of this process's import namespace.
    """
    module_spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(module_spec)
    # Register before executing: `@dataclass` resolves its annotations
    # through `sys.modules[cls.__module__]`, so a module that defines one
    # raises AttributeError if it is not there yet.
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _divider_record_note() -> str:
    """The divider's as-drawn matching, against floorplan.md's own targets.

    Derived from `layout/divider/plan.py` (the arrangement the generator
    draws) and `layout/area_estimate.py` (the mismatch arithmetic the area
    budget was closed with), so a record can never quote a centroid or a
    sigma the drawing does not have.
    """
    plan = _load_module("divider_plan", DIVIDER_DIR / "plan.py")
    area = _load_module("divider_area_estimate", LAYOUT_DIR / "area_estimate.py")
    _footprint, sigma3 = area.divider_field()
    pattern = "".join(
        "T" if p in plan.TOP_POSITIONS else "B" for p in plan.ACTIVE_POSITIONS
    )
    top_k = len(plan.TOP_POSITIONS) * plan.UNIT_KOHM
    bot_k = len(plan.BOT_POSITIONS) * plan.UNIT_KOHM
    return f"""## Matching, as drawn

Against `layout/floorplan.md` §4.1's numeric targets. Every figure below is
read out of `layout/divider/plan.py` -- the constants the generator actually
draws -- not transcribed from the document, and
`layout/tests/test_divider_layout.py` re-checks them against §4.1 on every CI
run.

| Property | §4.1's target | As drawn |
| --- | --- | --- |
| Unit | 50 kOhm `ppolyf_u_3k`, W = 2 um, L = 31.8 um | {plan.UNIT_KOHM:g} kOhm, W = {plan.UNIT_W_UM:g} um, L = {plan.UNIT_L_UM:g} um |
| String | 18 units, 6 up / 12 down | {len(plan.ACTIVE_POSITIONS)} units, {len(plan.TOP_POSITIONS)} up / {len(plan.BOT_POSITIONS)} down |
| Value | 900 kOhm total, tapped 600 k / 300 k | {top_k + bot_k:g} kOhm, tapped {bot_k:g} k / {top_k:g} k |
| Arrangement | `B T B B T B B T B B T B B T B B T B` | `{" ".join(pattern)}` |
| Pitch | 2.4 um (2.0 um strip + PRES.2's 0.4 um) | {plan.PITCH_UM:g} um ({plan.UNIT_W_UM:g} + {plan.PITCH_UM - plan.UNIT_W_UM:g}) |
| Dummies | one strip at each end | {len(plan.DUMMY_POSITIONS)}, at positions {", ".join(str(p) for p in plan.DUMMY_POSITIONS)} |
| **Top-leg centroid** | **9.5** | **{plan.centroid(plan.TOP_POSITIONS):g}** |
| **Bottom-leg centroid** | **9.5** | **{plan.centroid(plan.BOT_POSITIONS):g}** |
| Divider mismatch | 1.68 mV (3 sigma), vs. #9's budgeted 3.36 mV | {sigma3:.2f} mV (3 sigma) |

Both centroids landing on the same position is the *whole* claim this cell
exists to support, and it is the one term in the output-accuracy budget that
**cannot be simulated against this PDK at all**: the resistor subcircuits
hard-code `mis_r = 0` and the high-sheet `ppolyf_u_*k` cards carry no local
mismatch term (`sim/devchar/CONCLUSIONS.md` §2). The 3-sigma figure above is
therefore an arithmetic projection from a *proxy* coefficient (`ppolyf_u`'s
disabled `par_r = 0.021`, the proxy `README.md` note 3 sanctions), not a
measured or simulated result -- and it can only be claimed at all because the
drawn arrangement is the one it assumes, which is what this record's LVS
verdict establishes.

## What this LVS verdict does not cover

- **Resistance is not a compared parameter.** The deck's `BResistor` class
  (`rule_decks/custom_classes.lvs`) does `enable_parameter('R', false)` and
  compares `W` and `L` only. The match above therefore says the drawn
  *geometry* is the netlisted geometry, not that any resistance value is
  right. (It also means the deck's own nominal 3.0 kOhm/sq would call each
  unit 47.7 kOhm rather than 50 kOhm -- the 50 kOhm comes from
  `sim/devchar`'s measured effective sheet, 3.145 kOhm/sq, and is what the
  drawn 31.8 um length is sized from.)
- **Pin order is not checked here**, as for every cell in this flow -- see
  `layout/README.md`, "What LVS here does *not* check".
"""


TESTCELL_SPEC = CellSpec(
    key="testcell",
    cell="drclvs_testcell",
    top_cell="DRCLVS_TESTCELL",
    gen_gds=TESTCELL_DIR / "gen_gds.py",
    schematic=TESTCELL_DIR / "drclvs_testcell.sch",
    netlist_dir=TESTCELL_DIR / "netlist",
    xschem_library_paths=(TESTCELL_DIR,),
    controls=MOS_CONTROLS,
    substrate_net="VSS",
    description="one nfet_03v3, W=2 um, L=0.28 um, nf=1",
    scope_note=(
        "It says **nothing** about the LDO. The cell is one transistor; no "
        "block-level layout exists yet."
    ),
)

PASSIVES_SPEC = CellSpec(
    key="passives",
    cell="drclvs_passives",
    top_cell="DRCLVS_PASSIVES",
    gen_gds=PASSIVES_DIR / "gen_gds.py",
    schematic=PASSIVES_DIR / "drclvs_passives.sch",
    netlist_dir=PASSIVES_DIR / "netlist",
    xschem_library_paths=(PASSIVES_DIR,),
    controls=MOS_CONTROLS,
    substrate_net="VSS",
    description=(
        "one ppolyf_u_1k H-poly resistor, one cap_mim_2f0 MIM cap, and one "
        "2-finger nfet_03v3 -- the passive-bearing flow vehicle (issue #313)"
    ),
    scope_note=(
        "It says **nothing** about the LDO. The cell is three unconnected "
        "devices that exist only to prove the flow handles a netlist whose "
        "devices are not all FETs; no block-level layout exists yet."
    ),
)

PASS_ARRAY_SPEC = CellSpec(
    key="pass_array",
    cell="pass_array",
    top_cell="PASS_ARRAY",
    gen_gds=PASS_ARRAY_DIR / "gen_gds.py",
    schematic=PASS_ARRAY_DIR / "pass_array.sch",
    netlist_dir=PASS_ARRAY_DIR / "netlist",
    xschem_library_paths=(PASS_ARRAY_DIR,),
    controls=MOS_CONTROLS,
    # The pass device is a PMOS in an n-well tied to VIN; nothing in this cell
    # touches the p-substrate, but the deck still needs a name for it.
    substrate_net="VSS",
    description=(
        "40 pfet_03v3 pass unit cells (L=0.28 um, W=70 um, nf=1) plus 1 "
        "Msense unit cell of the same cell at the array centroid -- "
        "Mpass W=2.8 mm, N/M = 40 (issue #285)"
    ),
)

DIVIDER_SPEC = CellSpec(
    key="divider",
    cell="fb_divider",
    top_cell="FB_DIVIDER",
    gen_gds=DIVIDER_DIR / "gen_gds.py",
    schematic=DIVIDER_DIR / "fb_divider.sch",
    netlist_dir=DIVIDER_DIR / "netlist",
    xschem_library_paths=(DIVIDER_DIR,),
    controls=PASSIVE_CONTROLS,
    substrate_net="VSS",
    poly_res="3k",
    simplify_extracted=False,
    description=(
        "18 ppolyf_u_3k units (W=2 um, L=31.8 um) + 2 dummies, "
        "common-centroid 6 up / 12 down -- layout/floorplan.md §4.1"
    ),
    record_notes=_divider_record_note(),
)

# The registry a real block's layout plugs into -- add an entry here (see
# TESTCELL_SPEC's / DIVIDER_SPEC's fields) and drive it with `--cell <key>`.
# Two of the four entries are flow vehicles rather than design blocks:
# `testcell` proves the flow on a single FET, `passives` proves it on a cell
# whose devices are NOT all FETs (the case layout/lvs_form.py exists for).
# `pass_array` is the first real block -- issue #285, under epic #173 -- and
# `divider` the first all-passive one (issue #286).
CELLS: dict[str, CellSpec] = {
    TESTCELL_SPEC.key: TESTCELL_SPEC,
    PASSIVES_SPEC.key: PASSIVES_SPEC,
    PASS_ARRAY_SPEC.key: PASS_ARRAY_SPEC,
    DIVIDER_SPEC.key: DIVIDER_SPEC,
}


# --------------------------------------------------------------------------
# stage 3 -- klt drc
# --------------------------------------------------------------------------

def run_klt_drc(gds: Path, out_json: Path) -> dict:
    proc = subprocess.run(
        ["klt", "drc", str(gds), "--deck", "gf180mcu", "--format", "json"],
        capture_output=True, text=True,
    )
    # docs/cli/drc.md's contract: 0 clean, 3 violations, 1 run failure,
    # 2 usage error.
    if proc.returncode not in (0, 3):
        raise StageError(
            f"klt drc failed (exit {proc.returncode})\n{proc.stdout}\n{proc.stderr}"
        )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise StageError(f"klt drc emitted non-JSON output: {exc}\n{proc.stdout}")
    out_json.write_text(json.dumps(report, indent=2) + "\n")
    return report


# --------------------------------------------------------------------------
# stage 4 -- the PDK's own DRC deck
# --------------------------------------------------------------------------

def assemble_pdk_drc_deck(pdk: Pdk, run_dir: Path) -> tuple[Path, int]:
    """Concatenate the PDK's rule tables into one runnable deck.

    This mirrors ``generate_drc_run_template()`` in the PDK's own
    ``libs.tech/klayout/drc/run_drc.py``: ``main.drc`` first, then every rule
    table, then ``tail.drc``, with ``layers_def.drc`` copied next to the
    generated deck because ``main.drc`` loads it from the run directory.

    We assemble it ourselves rather than shelling out to ``run_drc.py`` because
    that script needs ``docopt`` and drives its own parallel run/report layout;
    what we want is one deck, one report, one exit status.

    ``*_split`` tables are excluded, matching what ``run_drc.py`` does for the
    ``deep`` run mode (they are the flat-mode variants of the same rules).
    """
    rule_decks = pdk.klayout_dir / "drc" / "rule_decks"
    excluded = ("antenna", "density", "main", "layers_def", "split", "tail")
    tables = sorted(
        os.path.basename(f)
        for f in glob.glob(str(rule_decks / "*.drc"))
        if all(token not in os.path.basename(f) for token in excluded)
    )
    if not tables:
        raise StageError(f"no DRC rule tables found under {rule_decks}")

    shutil.copyfile(rule_decks / "layers_def.drc", run_dir / "layers_def.drc")
    deck = run_dir / "main.drc"
    with deck.open("wb") as out:
        for name in ["main.drc"] + tables + ["tail.drc"]:
            out.write((rule_decks / name).read_bytes())
    return deck, len(tables)


def run_pdk_drc(pdk: Pdk, spec: CellSpec, gds: Path, run_dir: Path, log: Path) -> dict:
    deck, table_count = assemble_pdk_drc_deck(pdk, run_dir)
    report = run_dir / f"{spec.cell}.lyrdb"
    switches = {
        "input": str(gds),
        "report": str(report),
        "topcell": spec.top_cell,
        "thr": str(max(1, min(4, os.cpu_count() or 1))),
        "run_mode": "deep",
        "feol": "true",
        "beol": "true",
        "conn_drc": "false",
        "offgrid": "true",
        "verbose": "false",
        "split_deep": "false",
        "table_name": "main",
        **variant_switches(pdk),
    }
    cmd = ["klayout", "-b", "-r", str(deck)]
    for key, value in switches.items():
        cmd += ["-rd", f"{key}={value}"]
    env, pmap_provenance = deck_env(run_dir)
    run_logged(cmd, log, "PDK DRC deck", env=env)
    if not report.is_file():
        raise StageError(f"the PDK DRC deck produced no report at {report}")

    text = report.read_text()
    categories = text.count("<category>")
    items = text.count("<item>")
    if categories == 0:
        raise StageError(
            f"the PDK DRC deck ran but registered ZERO rule categories "
            f"({report}). A zero-violation result from a deck that ran no "
            "rules is not a DRC-clean result -- treat it as a broken "
            "invocation, not a pass."
        )
    return {
        "report": report,
        "rule_categories": categories,
        "violations": items,
        "rule_tables": table_count,
        "pmap": pmap_provenance,
    }


# --------------------------------------------------------------------------
# stage 5/6 -- LVS
# --------------------------------------------------------------------------

def run_lvs(
    pdk: Pdk, spec: CellSpec, gds: Path, netlist: Path, run_dir: Path, log: Path, tag: str
) -> dict:
    lvsdb = run_dir / f"{tag}.lvsdb"
    extracted = run_dir / f"{tag}_extracted.cir"
    switches = {
        "input": str(gds),
        "schematic": str(netlist),
        "report": str(lvsdb),
        "target_netlist": str(extracted),
        "topcell": spec.top_cell,
        "thr": str(max(1, min(4, os.cpu_count() or 1))),
        "run_mode": "deep",
        "lvs_sub": spec.substrate_net,
        "verbose": "false",
        "spice_net_names": "true",
        "spice_comments": "false",
        "scale": "false",
        "schematic_simplify": "false",
        "net_only": "false",
        # NOT a stray switch: gf180mcu.lvs derives its own SIMPLIFY as
        # "net_only, top_lvl_pins, combine, purge and purge_nets are ALL
        # false" -- i.e. leaving every option off is what *enables*
        # `netlist.simplify`, which collapses series/parallel device chains
        # in the extracted netlist (and only there: `schematic.simplify` is
        # gated separately, and off). For a one-device cell that is
        # invisible. For a unit-resistor string it is not: it collapses the
        # 18 drawn units into two lumped resistors, so the compare would
        # stop being able to tell an 18-unit string from one long strip --
        # exactly the property DR-0003 asks the divider to have. Turning
        # `top_lvl_pins` on is what switches SIMPLIFY off, and it is the
        # option with no other cost here, because creating the top-level
        # pins is a step `netlist.simplify` was performing anyway.
        "top_lvl_pins": "false" if spec.simplify_extracted else "true",
        "combine": "false",
        "purge": "false",
        "purge_nets": "false",
        "poly_res": spec.poly_res,
        "mim_cap": "2",
        **variant_switches(pdk),
    }
    cmd = ["klayout", "-b", "-r", str(pdk.klayout_dir / "lvs" / "gf180mcu.lvs")]
    for key, value in switches.items():
        cmd += ["-rd", f"{key}={value}"]
    env, _ = deck_env(run_dir)
    output = run_logged(cmd, log, f"LVS ({tag})", env=env)

    # The deck reports its own verdict; klayout exits 0 either way, so the log
    # IS the contract. Demand exactly one of the two verdicts so that a deck
    # that fell over before comparing is a hard error, not a silent pass.
    matched = "INFO : Congratulations! Netlists match." in output
    mismatched = "ERROR : Netlists don't match" in output
    if matched == mismatched:
        raise StageError(
            f"the LVS deck did not report a verdict for {tag} (matched="
            f"{matched}, mismatched={mismatched}) -- see {log}"
        )
    if not lvsdb.is_file():
        raise StageError(f"LVS produced no report database at {lvsdb}")
    return {
        "match": matched,
        "lvsdb": lvsdb,
        "extracted": extracted if extracted.is_file() else None,
        "warnings": [
            line.split(") : ", 1)[-1]
            for line in output.splitlines()
            if "WARNING" in line or "Must-connect" in line
        ],
    }


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------

def run_logged(
    cmd: list[str], log: Path, what: str, env: dict[str, str] | None = None
) -> str:
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    output = proc.stdout + proc.stderr
    log.write_text(output)
    if proc.returncode != 0:
        raise StageError(
            f"{what} failed (exit {proc.returncode}); full log at {log}\n"
            + "\n".join(output.splitlines()[-20:])
        )
    return output


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    spec = CELLS[args.cell]
    ok, pdk = check_env(verbose=args.check_env)
    if args.check_env:
        return 0 if ok else 2
    if not ok or pdk is None:
        print(
            "layout/drclvs.py: environment is incomplete. Run "
            "`python3 layout/drclvs.py --check-env` for details.",
            file=sys.stderr,
        )
        return 2

    rid = allocate_record_id(REPO_ROOT, RECORDS_DIR)
    run_dir = WORK_DIR / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    summary: dict = {"record_id": rid, "pdk": pdk.provenance(), "cell": spec.key}

    print(f"cell      : {spec.key} ({spec.cell})")
    print(f"record id : {rid}")
    print(f"pdk       : {pdk.path} ({pdk.variant}, {pdk.version})")
    print(f"run dir   : {run_dir}")
    print()

    # ---- 1. layout -------------------------------------------------------
    gds = run_dir / f"{spec.cell}.gds"
    generator_output = build_gds(pdk, spec, gds, run_dir / "build-gds.log")
    summary["generator_output"] = generator_output
    # Printed once the stage count is known: how many LVS negative controls a
    # cell supports is a property of its netlist (see build_controls), so the
    # `[i/N]` denominator cannot be settled until stage 2 has run.
    layout_line = f"layout      : {gds.name} ({gds.stat().st_size} bytes)"

    # ---- 2. schematic netlist -------------------------------------------
    with tempfile.TemporaryDirectory(prefix="gf180-ldo-lvs-netlist-") as tmp:
        netlist_text = export_netlist(pdk, spec, Path(tmp))
    committed = spec.netlist_dir / f"{spec.cell}.spice"
    if args.check:
        if not committed.is_file():
            failures.append(f"{committed.relative_to(REPO_ROOT)} is missing")
        elif committed.read_text() != netlist_text:
            diff = "\n".join(
                difflib.unified_diff(
                    committed.read_text().splitlines(),
                    netlist_text.splitlines(),
                    fromfile=f"committed/{spec.cell}.spice",
                    tofile=f"regenerated/{spec.cell}.spice",
                    lineterm="",
                )
            )
            failures.append(
                f"the committed LVS netlist is stale or the export is not "
                f"reproducible:\n{diff}"
            )
    else:
        spec.netlist_dir.mkdir(parents=True, exist_ok=True)
        committed.write_text(netlist_text)
    netlist = run_dir / f"{spec.cell}.spice"
    netlist.write_text(netlist_text)
    device_lines = [
        line for line in netlist_text.splitlines()
        if line and line[0].upper() in "MRCDQ" and not line.startswith("*")
    ]
    # ---- the evidence contract, checked before anything can report a pass -
    # Stages 6.. only mean something if every control this run will use can
    # actually corrupt this cell's netlist. Prove that NOW, so that a cell
    # whose controls do not apply fails here rather than after stage 5 has
    # already printed `lvs: MATCH`.
    controls = check_controls_apply(spec, netlist_text)
    total = 5 + len(controls)
    print(f"[1/{total}] {layout_line}")
    print(f"[2/{total}] netlist     : {len(device_lines)} device line(s), LVS form")
    summary["netlist_devices"] = len(device_lines)
    print(
        "      controls  : "
        + ", ".join(f"{c.tag} ({c.what})" for c in controls.values())
        + " -- all applicable"
    )

    # ---- 3. klt drc ------------------------------------------------------
    klt_report = run_klt_drc(gds, run_dir / f"{spec.cell}.klt-drc.json")
    klt_ok = klt_report["status"] == "clean"
    summary["klt_drc"] = {
        "status": klt_report["status"],
        "violations": klt_report["violation_count"],
        "dbu_um": klt_report["dbu_um"],
        "rule_counts": klt_report.get("rule_counts", {}),
    }
    print(
        f"[3/{total}] klt drc     : {klt_report['status']} "
        f"({klt_report['violation_count']} violation(s), curated subset)"
    )
    if not klt_ok:
        failures.append(
            f"klt drc reported {klt_report['violation_count']} violation(s): "
            f"{klt_report.get('rule_counts')}"
        )

    # ---- 4. PDK drc deck -------------------------------------------------
    pdk_drc = run_pdk_drc(pdk, spec, gds, run_dir, run_dir / "pdk-drc.log")
    summary["pdk_drc"] = {
        "violations": pdk_drc["violations"],
        "rule_categories": pdk_drc["rule_categories"],
        "rule_tables": pdk_drc["rule_tables"],
    }
    summary["pmap"] = pdk_drc["pmap"]
    print(
        f"[4/{total}] pdk drc     : {pdk_drc['violations']} violation(s) across "
        f"{pdk_drc['rule_categories']} rule categories "
        f"({pdk_drc['rule_tables']} rule tables)"
        + ("" if pdk_drc["pmap"] == "host" else ", pmap shimmed")
    )
    if pdk_drc["violations"]:
        failures.append(
            f"the PDK DRC deck reported {pdk_drc['violations']} violation(s); "
            f"see {pdk_drc['report']}"
        )

    # ---- 5. LVS ----------------------------------------------------------
    lvs = run_lvs(pdk, spec, gds, netlist, run_dir, run_dir / "lvs.log", "lvs")
    summary["lvs"] = {"match": lvs["match"], "warnings": lvs["warnings"]}
    print(f"[5/{total}] lvs         : {'MATCH' if lvs['match'] else 'MISMATCH'}")
    for warning in lvs["warnings"]:
        print(f"                    note: {warning}")
    if not lvs["match"]:
        failures.append(f"LVS reported a mismatch; see {lvs['lvsdb']}")

    # ---- 6.. LVS negative controls --------------------------------------
    # The set was chosen, and proven applicable, by check_controls_apply()
    # back at stage 2: the cell's own topology/parameter pair (MOS_CONTROLS,
    # or PASSIVE_CONTROLS for an all-passive cell such as the divider), plus
    # one per passive element class the netlist contains.
    summary["lvs_negative_controls"] = {}
    for index, control in enumerate(controls.values(), 6):
        tag, what, implication = control.tag, control.what, control.implication
        bad = run_dir / f"{spec.cell}.control-{tag}.spice"
        bad.write_text(apply_control(spec, control, netlist_text))
        result = run_lvs(
            pdk, spec, gds, bad, run_dir, run_dir / f"lvs-control-{tag}.log", f"control-{tag}"
        )
        summary["lvs_negative_controls"][tag] = {
            "match": result["match"], "mutation": what,
        }
        verdict = "MISMATCH (expected)" if not result["match"] else "MATCH -- WRONG"
        print(f"[{index}/{total}] control {tag:<10}: {what} -> {verdict}")
        if result["match"]:
            failures.append(
                f"the LVS {tag} negative control ({what}) MATCHED, which means "
                f"{implication}. The LVS invocation is not actually comparing "
                "what it appears to compare -- a 'match' from it is worthless."
            )

    print()
    if failures:
        print("FAIL:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(f"\nrun directory kept at {run_dir}", file=sys.stderr)
        return 1

    print("OK: DRC clean (klt subset and the PDK's own deck), LVS matches, and")
    print(f"    all {len(controls)} negative controls correctly fail.")
    if args.record:
        try:
            path = write_record(rid, summary, pdk, spec)
        except RecordExists as exc:
            raise StageError(
                f"could not write the run record: {exc}. Records are "
                "append-only (CLAUDE.md): a concurrent --record run already "
                f"spent record id {rid} -- re-run this command to mint a "
                "fresh id rather than overwriting the existing record."
            ) from exc
        print(f"\nwrote {path.relative_to(REPO_ROOT)}")
    if args.keep:
        print(f"\nrun directory kept at {run_dir}")
    else:
        shutil.rmtree(run_dir, ignore_errors=True)
    return 0


def control_rows(summary: dict) -> str:
    """One record-table row per LVS negative control."""
    rows = []
    for tag, result in summary["lvs_negative_controls"].items():
        verdict = (
            "mismatch, as required" if not result["match"]
            else "MATCHED -- INVALID RUN"
        )
        rows.append(
            f"| LVS negative control, {tag} ({result['mutation']}) | **{verdict}** |"
        )
    return "\n".join(rows)


def write_record(rid: str, summary: dict, pdk: Pdk, spec: CellSpec) -> Path:
    """Render and write ``layout/records/<rid>.md``.

    Writing goes through ``harness.report.write_markdown_record()`` rather
    than a hand-rolled ``mkdir``/``write_text``, so a collision with a
    record another concurrent ``--record`` run already spent for this same
    ``rid`` raises :class:`RecordExists` instead of silently overwriting
    it -- see ``run()``'s handling of that exception.
    """
    klt = summary["klt_drc"]
    drc = summary["pdk_drc"]
    warnings = summary["lvs"]["warnings"]
    schematic_rel = spec.schematic.relative_to(REPO_ROOT)
    scope_note = "- " + (
        spec.scope_note
        or (
            f"It certifies exactly `{spec.cell}` as netlisted from "
            f"`{schematic_rel}`, nothing more or less. A full-`ldo_core` "
            "DRC/LVS claim requires running this same flow against "
            "`ldo_core`'s own top-level schematic and its full layout."
        )
    )
    controls = ", ".join(sorted(summary["lvs_negative_controls"]))
    body = f"""# DRC/LVS run `{rid}` -- `{spec.key}`

Produced by `python3 layout/drclvs.py --cell {spec.key} --record`. Append-only:
a re-run mints a new record rather than editing this one.

| | |
| --- | --- |
| Cell | `{spec.cell}` (layout top cell `{spec.top_cell}`){' -- ' + spec.description if spec.description else ''} |
| PDK | gf180mcu variant `{pdk.variant}`, open_pdks `{pdk.version}` |
| klayout | `{tool_version('klayout', ['-b', '-v'])}` |
| klt | `{tool_version('klt', ['--version'])}` |
| xschem | `{tool_version('xschem', ['--version'])}` |
| pmap | `{summary.get('pmap', 'host')}` (the PDK decks' memory logger; `shimmed` = this host has no procps pmap(1) and `drclvs.py` supplied a ps(1)-backed stand-in) |

## Results

| Stage | Result |
| --- | --- |
| DRC -- `klt drc --deck gf180mcu` | **{klt['status']}**, {klt['violations']} violation(s); layout dbu {klt['dbu_um']} um |
| DRC -- PDK deck ({drc['rule_tables']} rule tables) | **{drc['violations']} violation(s)** across {drc['rule_categories']} rule categories |
| LVS -- PDK `gf180mcu.lvs` vs. xschem export | **{'match' if summary['lvs']['match'] else 'MISMATCH'}** |
{control_rows(summary)}

Schematic netlist: {summary['netlist_devices']} device line(s), exported in
xschem's `lvs_netlist` form from `{schematic_rel}`.

## What this does and does not establish

- The flow runs end to end: PDK PCell -> GDS -> DRC (two decks) -> LVS against
  a netlist exported from the schematic source, with {len(summary['lvs_negative_controls'])}
  negative control(s) ({controls}) proving the compare is live in each of
  those respects rather than silently comparing nothing.
{scope_note}
- `klt drc`'s deck is a curated subset (see `layout/README.md`, "Coverage,
  honestly"); the PDK deck's {drc['rule_categories']} categories are the number
  worth quoting.
"""
    if spec.record_notes:
        body += "\n" + spec.record_notes.rstrip("\n") + "\n"
    if warnings:
        body += "\n## LVS deck notes\n\n"
        for warning in warnings:
            body += f"- {warning}\n"
    generator_output = (summary.get("generator_output") or "").strip()
    if generator_output:
        body += (
            "\n## What the generator drew\n\n"
            f"Verbatim stdout of `{spec.gen_gds.relative_to(REPO_ROOT)}` for this\n"
            "run -- the as-drawn geometry, measured by the generator from the\n"
            "layout it had just built, not transcribed by hand.\n\n"
            "```\n" + generator_output + "\n```\n"
        )
    return write_markdown_record(rid, body, RECORDS_DIR)


def tool_version(tool: str, args: list[str]) -> str:
    try:
        out = subprocess.run([tool, *args], capture_output=True, text=True, timeout=60)
        return (out.stdout + out.stderr).strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run DRC and LVS on a registered gf180mcu layout cell.",
    )
    parser.add_argument(
        "--cell", choices=sorted(CELLS), default=TESTCELL_SPEC.key,
        help="which registered cell to run DRC/LVS against (default: "
             f"{TESTCELL_SPEC.key!r}, the bring-up test cell). See CELLS in "
             "this file to register a real block's layout.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="also require the committed LVS netlist to be current and the "
             "export reproducible (do not rewrite it)",
    )
    parser.add_argument(
        "--check-env", action="store_true",
        help="report tool and PDK availability, then stop",
    )
    parser.add_argument(
        "--record", action="store_true",
        help="write an append-only run record under layout/records/",
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="keep the run directory even on success",
    )
    args = parser.parse_args(argv)
    try:
        return run(args)
    except StageError as exc:
        print(f"layout/drclvs.py: {exc}", file=sys.stderr)
        return 1
    except PdkNotFound as exc:
        print(f"layout/drclvs.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
