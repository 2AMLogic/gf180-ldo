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

Exit status is 0 only if **every** stage passed. The stages are described in
one place, "The stages" in layout/README.md: which run for a cell, in what
order, and what each does and does not prove.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drclvs_common import (  # noqa: E402
    LAYOUT_DIR as LAYOUT_DIR,
    REPO_ROOT as REPO_ROOT,
    StageError as StageError,
    repo_arg as repo_arg,
)
from erc_stage import (  # noqa: E402
    ERC_REPORTS_DIR as ERC_REPORTS_DIR,
    ERC_SPECS_DIR as ERC_SPECS_DIR,
    GEN_ERC_SPEC_SCRIPT as GEN_ERC_SPEC_SCRIPT,
    MUTATE_ERC_SCRIPT as MUTATE_ERC_SCRIPT,
    ErcSpec as ErcSpec,
    check_erc_control_findings as check_erc_control_findings,
    erc_finding_keys as erc_finding_keys,
    erc_result_rows as erc_result_rows,
    erc_section as erc_section,
    run_erc_control as run_erc_control,
    run_erc_spec_gen as run_erc_spec_gen,
    run_klt_erc as run_klt_erc,
    validate_erc_report as validate_erc_report,
)
from lvs_controls import (  # noqa: E402
    L_TOKEN_RE as L_TOKEN_RE,
    MOS_CONTROLS as MOS_CONTROLS,
    PASSIVE_CONTROLS as PASSIVE_CONTROLS,
    PASSIVE_ELEMENTS as PASSIVE_ELEMENTS,
    REQUIRED_CONTROL_TAGS as REQUIRED_CONTROL_TAGS,
    W_TOKEN_RE as W_TOKEN_RE,
    Control as Control,
    ControlNotApplicable as ControlNotApplicable,
    apply_control as apply_control,
    build_controls as build_controls,
    check_controls_apply as check_controls_apply,
    control_parameter as control_parameter,
    control_passive as control_passive,
    control_short_adjacent_taps as control_short_adjacent_taps,
    control_topology as control_topology,
    control_unit_width as control_unit_width,
    require_control_pair as require_control_pair,
)
from lvs_form import (  # noqa: E402
    LvsFormError,
    MIMCAP_CURATED_OPTION,
    MIMCAP_SWITCH,
    rewrite_passives,
    unrendered_device_lines,
)

TESTCELL_DIR = LAYOUT_DIR / "testcell"
PASSIVES_DIR = LAYOUT_DIR / "passives"
PASS_ARRAY_DIR = LAYOUT_DIR / "pass_array"
DIVIDER_DIR = LAYOUT_DIR / "divider"
RECORDS_DIR = LAYOUT_DIR / "records"
# Committed klt report trees, mirroring 2AMLogic/gf180-bandgap's
# layout/drc/reports/<cell>/ and layout/lvs/reports/<cell>/ layout (issue
# #784): append-only evidence files named by the same record id as the run
# record they accompany, never overwritten (a re-run mints a new id).
DRC_REPORTS_DIR = LAYOUT_DIR / "drc" / "reports"
LVS_REPORTS_DIR = LAYOUT_DIR / "lvs" / "reports"
WORK_DIR = LAYOUT_DIR / ".work"
XSCHEMRC = LAYOUT_DIR / "xschemrc"

# design/netlist/ holds the *simulation* netlists design/netlist.py generates
# and every sim/ testbench sources. Stage 2 writes `netlist_dir/<cell>.spice`
# unconditionally, so a CellSpec pointing netlist_dir there would silently
# overwrite one of them with the LVS-form export -- a corruption nothing
# re-checks until a sim run breaks. CellSpec.__post_init__ refuses it.
SIM_NETLIST_DIR = REPO_ROOT / "design" / "netlist"


#: The two routes stage 5 (and the negative controls) can take (issue #784):
#: "klt" drives the curated gf180mcu deck through `klt lvs` (engine
#: "klayout", JSON report, committed under layout/lvs/reports/); "pdk-deck"
#: keeps the raw `klayout -b -r` invocation of the PDK's own gf180mcu.lvs
#: runset. A cell stays on the raw route only for a named klt gap (see
#: CellSpec.lvs_route).
LVS_ROUTES = ("klt", "pdk-deck")


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
    # The two (or more) LVS negative controls run against this
    # cell. See REQUIRED_CONTROL_TAGS: a cell must register a topology
    # control and a parameter control, and every one of them must actually
    # apply to this cell's netlist (check_controls_apply, called before any
    # LVS run, turns "this control does nothing here" into a hard error).
    controls: tuple[Control, ...]
    # The schematic's bulk/substrate port NAME. Not an LVS deck switch: the
    # pinned deck dereferences no lvs_sub global (see lvs_switches, issue
    # #691) and names the substrate itself instead --
    # rule_decks/substrate_connections.lvs hardcodes
    # `connect_global(..., 'SUB')`. This field is only the port name the
    # schematic netlist carries; whether the deck should ever take the
    # substrate net from the run is a separate decision, deliberately not
    # made here.
    substrate_net: str = "VSS"
    # The LVS deck's `poly_res` switch: which high-sheet ppolyf_u_* flavour
    # the deck extracts. A `case POLY_RES` in rule_decks/res_extraction.lvs
    # means exactly one of 1k/2k/3k is recognised per run, so a cell built
    # from ppolyf_u_3k units is unextractable -- and mismatches -- under the
    # default. Not a free choice: it is which flavour the cell is drawn in.
    poly_res: str = "1k"
    # Whether the LVS deck may collapse series/parallel device chains before
    # comparing. Despite the name, this is not an extracted-side-only choice:
    # the pinned runset has ONE switch for it -- $simplify -- and it gates
    # BOTH sides, `netlist.simplify` and `schematic.simplify`
    # (gf180mcu.lvs:427-428), so a True here lets chains fold on the
    # schematic side too. Harmless for a cell whose devices cannot be
    # combined; for a unit-resistor string it erases the very structure the
    # layout exists to prove, so such a cell sets this False. run_lvs()
    # maps this onto $simplify -- there is no extracted-only switch to set.
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
    # numeric target). A zero-argument callable, invoked only when --record
    # writes this cell's record -- NOT evaluated at CellSpec-construction
    # time, which kept every cell's import paying for the divider's sources
    # (issue #649). None for a cell with no note; see
    # layout/divider/record_note.py for the one registered example.
    record_notes: Callable[[], str] | None = None
    # Where this cell's GDS is COMMITTED (issue #784), or None for a
    # scratch-only cell (the flow vehicles that are not design blocks). A
    # committed GDS is the input artifact every committed klt report pins by
    # content hash, so a run against it never silently regenerates it:
    # stage 1 builds a fresh copy in the scratch run directory, compares it
    # against the committed file ignoring GDS timestamp records
    # (gds_equal_modulo_timestamps), runs every stage against the COMMITTED
    # bytes, and raises on a geometry difference -- re-minting the committed
    # GDS (and the reports pinning it) is a deliberate act, not a side
    # effect of running the flow.
    gds_path: Path | None = None
    # Which LVS route stage 5 (and the negative controls) take for this cell:
    # "klt" runs `klt lvs` on the curated gf180mcu deck; "pdk-deck" keeps the
    # raw `klayout -b -r` invocation of the PDK's own gf180mcu.lvs runset.
    # A cell stays on the raw route only for a named klt gap.
    lvs_route: str = "klt"
    # Per-device-class parameters the `klt lvs` compare is scoped to for
    # this cell (request ``options.compare_parameters``). KLayout declares a
    # resistor class's L/W/A/P *secondary*, so by default NONE of them take
    # part in the compare -- the geometry negative controls would MATCH, and
    # a control that matches is a failed run. Naming ["L", "W"] for the
    # cell's resistor class puts the drawn geometry back into the compare
    # (disclosed by klt as a device.parameter_excluded warning per
    # narrowed-away sibling, e.g. R). Empty for a cell with no passives.
    lvs_compare_parameters: dict[str, tuple[str, ...]] = dataclasses.field(
        default_factory=dict
    )
    # Whether the `klt lvs` compare may fold parallel device chains on BOTH
    # sides (request ``options.combine_devices``, klt default false) for this
    # cell. pass_array needs it: its reference expresses the 40-unit array as
    # one ``nf=40`` MOS card (the schematic's own lvs_format rendering), and
    # the plain-M-card side of klt's subckt-call conversion does not expand
    # ``nf`` the way its X-card conversion does -- so the 40 drawn unit
    # devices must fold to meet the one reference card, with the negative
    # controls still proving the folded compare is live (the width control
    # still mismatches: the folded layout side holds the drawn total). A unit
    # string cell (divider) keeps this False: folding its series chain would
    # erase exactly the structure the layout exists to prove (the same
    # reason simplify_extracted is False there).
    lvs_combine_devices: bool = False
    # Request ``layout.join_same_named_nets``: KLayout's implicit join of
    # same-named label shapes before extraction -- the `klt lvs` counterpart
    # of the PDK runset's ``connect_implicit('*')`` (2AMLogic/klayout-tools#7030).
    # Needed by a cell whose reference expects disconnected same-named shapes
    # (passives' two S straps / two G labels) to land on one net. The report
    # discloses the join; it stays False wherever the layout is strapped.
    lvs_join_same_named_nets: bool = False
    # The `klt erc` supply-spec contract (issue #785), or None for a cell
    # with no committed supply spec (the flow vehicles). Registers the
    # cell's declared ties, its disclosed expected findings, and the ERC
    # negative control's mutation. When set, the flow gains two stages:
    # the intact supply run (spec emitted from the committed GDS, report
    # committed under layout/erc/reports/<key>/) and, after the LVS
    # controls, the tie-severing negative control. T1 item 11 stays
    # `unmet` on these sub-cell runs -- they are the groundwork #524's
    # ldo_core run reuses, not the item's evidence (signoff/README.md).
    erc: ErcSpec | None = None

    def __post_init__(self) -> None:
        if self.lvs_route not in LVS_ROUTES:
            raise ValueError(
                f"CellSpec({self.key!r}).lvs_route is {self.lvs_route!r}; "
                f"expected one of {sorted(LVS_ROUTES)}"
            )
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


sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness.loader import load_script  # noqa: E402
from harness.pdk import Pdk, PdkNotFound, find_pdk  # noqa: E402
from harness.report import (  # noqa: E402
    RecordExists,
    allocate_record_id,
    write_markdown_record,
)
from harness.xschem_export import XschemExportError, run_xschem_netlist  # noqa: E402

# metal_top / mim_option / metal_level per gf180mcu variant, transcribed from
# the PDK's own libs.tech/klayout/tech/lvs/run_lvs.py (the pinned revision's
# DRC driver carries the same presets as its built-in variant table). The
# variant is not a free choice: it is which metal stack the
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


def check_env(lvs_route: str, verbose: bool = True) -> tuple[bool, Pdk | None]:
    """Check the tools and PDK files required for the selected LVS route."""
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
        required_paths = [
            (pdk.klayout_dir / "drc" / "gf180mcu.drc", "DRC deck driver"),
            (pdk.klayout_dir / "drc" / "rule_decks", "DRC rule decks"),
            (pdk.klayout_dir / "pymacros", "PCell library"),
        ]
        if lvs_route == "pdk-deck":
            required_paths.append((pdk.klayout_dir / "lvs" / "gf180mcu.lvs", "LVS deck"))
        for sub, label in required_paths:
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

# The gf180mcu LVS deck (libs.tech/klayout/tech/lvs/gf180mcu.lvs, around its
# line 74) installs a Ruby Logger formatter that shells out to pmap(1) on
# EVERY log line:
#
#     "#{datetime}: Memory Usage (" + `pmap #{Process.pid} | tail -1`[10, 40].strip + ...
#
# The DRC deck no longer does this -- the pinned revision's driver
# (tech/drc/gf180mcu.drc) reads memory via KLayout's own API
# (`RBA::Timer.memory_size`) and never shells out -- but the shim must stay
# for stage 5+ (LVS).
#
# pmap is procps, i.e. Linux-only. On a host without it the backtick returns
# "", `""[10, 40]` is nil, and `nil.strip` raises -- so the deck dies on its
# very first logger.info(), before it has run a single rule. The failure reads
# as `undefined method 'strip' for nil` in gf180mcu.lvs, which looks like a
# deck bug rather than a missing utility.
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


# GDS record types whose payload is a pair of 6-entry modification/access
# timestamps (BGNLIB = 0x01, BGNSTR = 0x05): 12 bytes of "when was this
# written" that the generator refreshes on every run, so two byte streams of
# the same geometry differ in exactly these payloads.
_GDS_TIMESTAMP_RECORDS = frozenset((0x01, 0x05))


def _gds_records(data: bytes):
    """Yield ``(record_type, payload)`` for every GDS record in ``data``.

    GDSII is a flat sequence of records: a 2-byte big-endian length (the
    header's own 4 bytes included), the record type, the data type, then the
    payload. A malformed stream raises ValueError rather than yielding
    nonsense -- both files this walks were produced by KLayout, so a parse
    error means the file is not the format we think we are comparing.
    """
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError(f"truncated GDS record header at {offset}")
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 4 or offset + length > len(data):
            raise ValueError(f"bad GDS record length {length} at {offset}")
        yield data[offset + 2], data[offset + 4:offset + length]
        offset += length


def gds_equal_modulo_timestamps(a: Path, b: Path) -> bool:
    """Do two GDS streams carry identical bytes except their timestamps?

    The committed GDS a report pins by content hash must be reproducible
    from the generator, but KLayout stamps BGNLIB/BGNSTR with the build
    time, so two consecutive builds of the same geometry never hash equal.
    This comparison zeroes exactly those timestamp payloads and compares
    everything else -- so "equal" means the streams agree on every geometry,
    layer, and structure byte, and a difference is a real geometry (or
    library-metadata) change, never the clock.
    """
    def normalized(path: Path) -> list[tuple[int, bytes]]:
        data = path.read_bytes()
        return [
            (rtype, b"\x00" * len(payload) if rtype in _GDS_TIMESTAMP_RECORDS
             else payload)
            for rtype, payload in _gds_records(data)
        ]

    return normalized(a) == normalized(b)


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
        text, rewritten = rewrite_passives(
            text, cap_pdk_params=spec.lvs_route == "klt"
        )
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
# the cell registry
# --------------------------------------------------------------------------


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
    gds_path=PASSIVES_DIR / "drclvs_passives.gds",
    # The curated `klt lvs` route. The cell's two `S` straps / two `G` labels
    # rely on the PDK runset's implicit label join, which klt now expresses as
    # layout.join_same_named_nets (2AMLogic/klayout-tools#7030); the MIM cap's
    # PDK-current `cap_mim_2f0fF` spelling is accepted by the reference
    # converter (2AMLogic/klayout-tools#7031).
    lvs_join_same_named_nets=True,
    # The 2-finger nfet extracts as two unit devices against one nf=2
    # reference card; fold them as pass_array does.
    lvs_combine_devices=True,
    # Geometry compare for the H-poly resistor class (the LVS-deck analogue
    # of divider's entry; the raw route compares W/L via the deck's own
    # BResistor class).
    lvs_compare_parameters={
        "ppolyf_u_1k": ("L", "W"),
        MIMCAP_CURATED_OPTION: ("A", "P"),
    },
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
    gds_path=PASS_ARRAY_DIR / "pass_array.gds",
    # The reference expresses the array as one nf=40 MOS card; the klt
    # compare must fold the 40 drawn parallel units to meet it (see the
    # field's declaration-site comment).
    lvs_combine_devices=True,
    # The `klt erc` supply stage (issue #785): VIN and VOUT declared as
    # supplies (VOUT is the regulated rail feeding the 0-50 mA load), the
    # n-well tie to VIN declared, the p-substrate class disclosed
    # undeclared (no substrate tap exists in this pfet-only cell). The one
    # disclosed finding is the standalone cell's label-only gate bus: no
    # gate contact is drawn (gate routing lands at ldo_core assembly), so
    # erc.floating_gate on PASS_GATE is a true statement about the sub-cell
    # view, quoted in the record rather than hidden.
    erc=ErcSpec(
        ties=("nwell_vin_tie",),
        expected_findings=(("erc.floating_gate", "PASS_GATE"),),
        control_mutation=(
            "every via1 landing between the VIN straps and both n-well "
            "guard-ring arms deleted"
        ),
    ),
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
    gds_path=DIVIDER_DIR / "fb_divider.gds",
    # KLayout declares a resistor class's L/W/A/P parameters *secondary*, so
    # none of them take part in a default klt compare and the geometry
    # negative control (unit width doubled) would MATCH -- a control that
    # matches is a failed run. Scoping the class to ["L", "W"] puts the
    # drawn geometry back into the compare (klt discloses the narrowed-away
    # siblings, e.g. R, as device.parameter_excluded warnings).
    lvs_compare_parameters={"ppolyf_u_3k": ("L", "W")},
    # The `klt erc` supply stage (issue #785): VSS declared as the supply
    # (the substrate-tap ring is the cell's only VSS conductor), the
    # substrate tie asserted over the measured ring band. VOUT_S stays a
    # signal -- it is the Kelvin sense port of the regulated rail, which is
    # declared a supply where the force current flows, on the pass array.
    erc=ErcSpec(
        ties=("substrate_vss_tie",),
        expected_findings=(),
        control_mutation=(
            "every contact cut between the p+ substrate-tap ring and its "
            "metal1 VSS ring deleted"
        ),
    ),
    description=(
        "18 ppolyf_u_3k units (W=2 um, L=31.8 um) + 2 dummies, "
        "common-centroid 6 up / 12 down -- layout/floorplan.md §4.1"
    ),
    record_notes=lambda: load_script(
        "divider_record_note", DIVIDER_DIR / "record_note.py"
    ).render(),
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
# stage 3 -- klt drc (curated deck)
# --------------------------------------------------------------------------

def run_klt_drc(gds: Path, out_json: Path) -> dict:
    """Curated-deck DRC through ``klt drc``, report written by ``-o``.

    ``-o`` (rather than capturing stdout) is the committed-report contract:
    klt writes the envelope atomically, and the file at ``out_json`` is the
    same artifact a ``--record`` run commits and ``klt drc --check`` later
    re-hashes. Both paths are repo-relative and the subprocess runs from the
    repo root so the report records machine-independent, repo-scoped paths.
    """
    rel_gds = repo_arg(gds)
    rel_out = repo_arg(out_json)
    proc = subprocess.run(
        [
            "klt", "drc", str(rel_gds),
            "--deck", "gf180mcu", "--format", "json", "-o", str(rel_out),
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    # docs/cli/drc.md's contract: 0 clean, 3 violations, 1 run failure,
    # 2 usage error.
    if proc.returncode not in (0, 3):
        raise StageError(
            f"klt drc failed (exit {proc.returncode})\n{proc.stdout}\n{proc.stderr}"
        )
    try:
        report = json.loads(out_json.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StageError(f"klt drc wrote no readable report at {out_json}: {exc}")
    return report


# --------------------------------------------------------------------------
# stage 4 -- the PDK's own DRC deck, through klt
# --------------------------------------------------------------------------

def native_drc_deck_vars(pdk: Pdk) -> dict[str, str]:
    """The ``--deck-var`` set stage 4 passes to the PDK's own DRC driver.

    klt passes ``input=``/``report=`` itself and selects the top cell via
    ``--top``, so these are the remaining switches the raw ``klayout -b -r``
    invocation passed: the ``decks=all,-antenna,-density`` table selection
    (antenna and density are each carried by exactly one deck file, so the
    selection excludes exactly what the pre-driver-era assembly excluded)
    plus the variant's metal-stack switches. The driver SILENTLY IGNORES
    unknown ``-rd`` switches, so every entry here is one the driver honours
    -- see layout/tests/test_drclvs.py's stage-4 tests.
    """
    return {
        "run_mode": "deep",
        "threads": str(max(1, min(4, os.cpu_count() or 1))),
        "decks": "all,-antenna,-density",
        "verbose": "false",
        **variant_switches(pdk),
    }


def list_rule_categories(pdk: Pdk, deck_vars: dict[str, str], out: Path) -> list[str]:
    """The rule categories the PDK's DRC deck *declares* under these vars.

    ``klt drc --list-rule-categories`` runs the real deck against a
    klt-generated empty layout, so the set is independent of the layout
    being signed off (not a circular derivation). The names feed straight
    into ``--expect-rule-categories-file`` -- the exact-set coverage
    assertion that keeps a zero-category (or swapped-category) deck run a
    hard error rather than a clean pass.
    """
    cmd = [
        "klt", "drc",
        "--engine", "klayout",
        "--deck-file", str(pdk.klayout_dir / "drc" / "gf180mcu.drc"),
    ]
    for key, value in deck_vars.items():
        cmd += ["--deck-var", f"{key}={value}"]
    cmd += ["--list-rule-categories", "--format", "text"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    if proc.returncode != 0:
        raise StageError(
            "klt drc --list-rule-categories failed "
            f"(exit {proc.returncode})\n{proc.stdout}\n{proc.stderr}"
        )
    names = [line for line in proc.stdout.splitlines() if line.strip()]
    if not names:
        raise StageError(
            "the PDK DRC deck declared ZERO rule categories "
            f"({out}). A zero-category deck cannot support the coverage "
            "assertion, and a zero-violation result from a deck that ran "
            "no rules is not a DRC-clean result -- treat this as a broken "
            "invocation, not a pass."
        )
    out.write_text("\n".join(names) + "\n")
    return names


def run_pdk_drc(
    pdk: Pdk, spec: CellSpec, gds: Path, run_dir: Path, log: Path, out_json: Path
) -> dict:
    """Run the PDK's own DRC deck through ``klt drc --engine klayout``.

    The pinned open_pdks revision ships the deck as a driver script
    (``tech/drc/gf180mcu.drc``) that ``require_relative``s its own rule
    tables; klt drives the standalone klayout binary on it with our deck
    vars, then parses the RDB into the JSON-contracted report. Two
    deck-abort failure modes the raw invocation could not see are klt's
    job now: a deck that exits non-zero or prints an ``ERROR`` line is a
    failed run even when a partial report file exists, and the deck's
    declared category set is asserted against the ``--list-rule-categories``
    listing of the same deck under the same switches -- so a deck that ran
    zero (or swapped) categories is a hard error, never a clean pass.
    """
    deck_vars = native_drc_deck_vars(pdk)
    manifest = run_dir / f"{spec.cell}.categories.txt"
    expected = list_rule_categories(pdk, deck_vars, manifest)

    rel_gds = repo_arg(gds)
    rel_out = repo_arg(out_json)
    cmd = [
        "klt", "drc", str(rel_gds),
        "--engine", "klayout",
        "--deck-file", str(pdk.klayout_dir / "drc" / "gf180mcu.drc"),
        "--top", spec.top_cell,
    ]
    for key, value in deck_vars.items():
        cmd += ["--deck-var", f"{key}={value}"]
    cmd += [
        "--expect-rule-categories-file", str(repo_arg(manifest)),
        "--timeout-s", "900",
        "--format", "json", "-o", str(rel_out),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=REPO_ROOT
    )
    log.write_text(proc.stdout + proc.stderr)
    # 0 clean (assertion satisfied), 3 violations; 1/2 are failures, and a
    # failed category assertion is exit 1 with no report.
    if proc.returncode not in (0, 3):
        raise StageError(
            f"klt drc --engine klayout failed (exit {proc.returncode}); "
            f"full log at {log}\n" + "\n".join((proc.stdout + proc.stderr).splitlines()[-20:])
        )
    try:
        report = json.loads(out_json.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StageError(f"klt drc wrote no readable report at {out_json}: {exc}")

    assertion = report.get("coverage_assertion") or {}
    if not assertion.get("satisfied"):
        raise StageError(
            "the native-deck rule-category coverage assertion was not "
            f"satisfied: {json.dumps(assertion)[:400]}"
        )
    coverage = report.get("coverage") or {}
    categories = coverage.get("rule_categories") or []
    return {
        "report": out_json,
        "rule_categories": len(categories),
        "category_names": set(categories),
        "violations": report["violation_count"],
        "status": report["status"],
        "deck": "gf180mcu.drc",
        "decks_selection": deck_vars["decks"],
        "engine": "klt drc --engine klayout",
        "asserted_categories": len(expected),
        "coverage": {
            key: coverage.get(key)
            for key in (
                "layers_in_stream_without_rules", "rules_skipped", "deck_scope"
            )
        },
    }


def run_raw_pdk_drc_parity(
    pdk: Pdk, spec: CellSpec, gds: Path, run_dir: Path, log: Path
) -> dict:
    """The pre-#784 raw ``klayout -b -r`` deck run, kept only for parity.

    Issue #784 retires this invocation from the flow but requires that,
    before it goes, both routes be shown to reach the same verdict and
    rule-category count on each cell. ``--parity-raw-deck`` re-runs this
    alongside stage 4 and compares; once the three cells' parity is
    recorded, this function is the reference anyone can re-run -- the raw
    path is evidence, not the flow.
    """
    driver = pdk.klayout_dir / "drc" / "gf180mcu.drc"
    report = run_dir / f"{spec.cell}.raw-parity.lyrdb"
    switches = {
        "input": str(gds),
        "report": str(report),
        "topcell": spec.top_cell,
        **native_drc_deck_vars(pdk),
    }
    cmd = ["klayout", "-b", "-r", str(driver)]
    for key, value in switches.items():
        cmd += ["-rd", f"{key}={value}"]
    env, pmap_provenance = deck_env(run_dir)
    run_logged(cmd, log, "raw PDK DRC deck (parity)", env=env)
    if not report.is_file():
        raise StageError(f"the raw PDK DRC deck produced no report at {report}")

    text = report.read_text()
    categories = set(re.findall(r"<category>\s*<name>([^<]+)</name>", text))
    items = text.count("<item>")
    if not categories:
        raise StageError(
            f"the raw PDK DRC deck ran but registered ZERO rule categories "
            f"({report})."
        )
    return {
        "categories": categories,
        "violations": items,
        "pmap": pmap_provenance,
    }


def check_raw_parity(native: dict, raw: dict, spec: CellSpec, run_dir: Path) -> str:
    """Assert the klt native-deck run and the raw run agree; describe it.

    Same verdict (violations count) and the same category-name set. A
    difference is a hard error: per the issue's canary clause it must be
    filed upstream with both outputs, not waved through.
    """
    if native["violations"] != raw["violations"]:
        raise StageError(
            f"raw-vs-klt DRC parity failed for {spec.key}: the raw deck "
            f"reported {raw['violations']} violation(s), the klt native "
            f"run {native['violations']} -- see {run_dir}"
        )
    if native["category_names"] != raw["categories"]:
        only_klt = sorted(native["category_names"] - raw["categories"])
        only_raw = sorted(raw["categories"] - native["category_names"])
        raise StageError(
            f"raw-vs-klt DRC parity failed for {spec.key}: the rule-category "
            f"sets differ (klt-only {only_klt[:5]}, raw-only "
            f"{only_raw[:5]}) -- see {run_dir}"
        )
    return (
        f"verdict equal ({native['violations']} violation(s) both ways), "
        f"{len(raw['categories'])} rule categories both ways"
    )


# --------------------------------------------------------------------------
# stage 5/6 -- LVS
# --------------------------------------------------------------------------

def lvs_switches(
    pdk: Pdk, spec: CellSpec, gds: Path, netlist: Path, lvsdb: Path, extracted: Path
) -> dict[str, str]:
    """The ``-rd`` switch set the LVS stage passes to the PDK's deck.

    The deck is a Ruby script: ``-rd key=value`` only sets a ``$key``
    global, and a global the deck never dereferences is silently unused --
    the invocation looks valid while the code claims an intent the deck
    never carries out (the same silent-ignore failure the DRC driver
    documents). So every key here is one the pinned deck actually reads:
    layout/tests/test_lvs_switches.py holds this dict to the deck's
    dereferenced ``$global`` set and fails loudly on a stale key.

    Deliberately ABSENT (dead on the pinned revision, dropped in issue
    #691): ``thr`` (no thread pool switch in the LVS deck), ``lvs_sub``
    (the deck names the substrate itself --
    rule_decks/substrate_connections.lvs hardcodes ``connect_global``),
    ``scale`` and ``schematic_simplify`` (never dereferenced; the compare
    options the deck does take are the explicit per-side switches below).
    """
    return {
        "input": str(gds),
        "schematic": str(netlist),
        "report": str(lvsdb),
        "target_netlist": str(extracted),
        "topcell": spec.top_cell,
        "run_mode": "deep",
        "verbose": "false",
        "spice_net_names": "true",
        "spice_comments": "false",
        "net_only": "false",
        # The pinned runset reads every compare-affecting option as its own
        # -rd global, each defaulting to FALSE through `bool_check?`
        # (tech/lvs/gf180mcu.lvs:109): nothing is derived any more. The two
        # defaults below would silently change what the compare sees, so
        # both are passed explicitly:
        #   * SIMPLIFY comes from $simplify alone (gf180mcu.lvs:149) and
        #     gates BOTH sides -- `netlist.simplify` and `schematic.simplify`
        #     (gf180mcu.lvs:427-428) collapse series/parallel device chains
        #     before comparing. For a one-device cell that is invisible. For
        #     a unit-resistor string it folds the 18 drawn units into two
        #     lumped resistors, so the compare would stop being able to tell
        #     an 18-unit string from one long strip -- exactly the property
        #     DR-0003 asks the divider to preserve. CellSpec's
        #     simplify_extracted is that choice, so the switch follows it.
        #   * IMPLICIT_CONNECT comes from $implicit_connect alone
        #     (gf180mcu.lvs:179) and gates `connect_implicit('*')`
        #     (gf180mcu.lvs:415). Without it, same-named nets that touch only
        #     through the extraction stay separate nets: drclvs_passives
        #     draws no strapping metal (layout/passives/gen_gds.py) precisely
        #     so that join is what lands its two `S` straps and two `G`
        #     labels on one net each.
        "simplify": "true" if spec.simplify_extracted else "false",
        "implicit_connect": "true",
        # top_lvl_pins is an independent switch in the pinned runset
        # (gf180mcu.lvs:159) -- not SIMPLIFY's off-toggle the pre-bump deck
        # derived. Kept paired with simplify_extracted: this is the
        # combination the verification probes ran, the divider keeping
        # top-level pin creation on as it always has.
        "top_lvl_pins": "false" if spec.simplify_extracted else "true",
        "combine": "false",
        "purge": "false",
        "purge_nets": "false",
        "poly_res": spec.poly_res,
        # The MIM flavour the deck extracts this run -- and the only flavour
        # lvs_form.py's renderer lets a C line name. The switch value and
        # the registered class are one pairing transcribed in one place
        # (lvs_form.MIMCAP_SWITCH <-> lvs_form.MIMCAP_CLASS), so this
        # literal and the renderer cannot drift apart (issue #680).
        "mim_cap": MIMCAP_SWITCH,
        **variant_switches(pdk),
    }


def run_lvs(
    pdk: Pdk, spec: CellSpec, gds: Path, netlist: Path, run_dir: Path, log: Path, tag: str
) -> dict:
    """The raw PDK-runset LVS route (``CellSpec.lvs_route == "pdk-deck"``)."""
    lvsdb = run_dir / f"{tag}.lvsdb"
    extracted = run_dir / f"{tag}_extracted.cir"
    switches = lvs_switches(pdk, spec, gds, netlist, lvsdb, extracted)
    cmd = ["klayout", "-b", "-r", str(pdk.klayout_dir / "lvs" / "gf180mcu.lvs")]
    for key, value in switches.items():
        cmd += ["-rd", f"{key}={value}"]
    env, pmap_provenance = deck_env(run_dir)
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
        "pmap": pmap_provenance,
        "warnings": [
            line.split(") : ", 1)[-1]
            for line in output.splitlines()
            if "WARNING" in line or "Must-connect" in line
        ],
    }


def build_klt_lvs_request(
    spec: CellSpec, pdk: Pdk, layout_ref: str, netlist_ref: str
) -> dict:
    """The ``klt lvs`` request document for one compare (issue #784).

    Mirrors 2AMLogic/gf180-bandgap's request shape (same layout/reference
    keys; reports land in the same ``layout/lvs/reports/<cell>/`` tree).
    Three knobs are this repo's own, each carried from the raw route's
    ``lvs_switches()``:

    * ``deck_options`` -- the curated deck's flavour selectors, the
      counterparts of the raw route's ``poly_res`` / ``mim_cap`` /
      ``metal_top`` switches. ``mim_cap`` uses the curated deck's own class
      spelling (``lvs_form.MIMCAP_CURATED_OPTION``; the divergence from the
      PDK's current ``fF`` spelling is 2AMLogic/klayout-tools#7031).
    * ``reference.form: "subckt-call"`` + ``reference.deck: "gf180mcu"`` --
      the committed reference netlists are xschem ``lvs_netlist`` exports
      whose device cards name PDK model/class tokens (``pfet_03v3``,
      ``ppolyf_u_3k``); the conversion rewrites those tokens onto the
      deck's device classes.
    * ``options.compare_parameters`` (per-cell, from
      ``spec.lvs_compare_parameters``) and ``options.combine_devices``
      (per-cell, from ``spec.lvs_combine_devices``) -- see the CellSpec
      fields.

    Paths inside a request resolve against the request file's own
    directory, so callers pass ``layout_ref``/``netlist_ref`` relative to
    wherever the request will be written (committed tree or scratch run
    directory) -- never absolute host paths.
    """
    request: dict = {
        "layout": {
            "file": layout_ref,
            "deck": "gf180mcu",
            "top": spec.top_cell,
            "deck_options": {
                "poly_res": spec.poly_res,
                "mim_cap": MIMCAP_CURATED_OPTION,
                "metal_top": variant_switches(pdk)["metal_top"],
            },
        },
        "reference": {
            "netlist": netlist_ref,
            "top": spec.cell,
            "form": "subckt-call",
            "deck": "gf180mcu",
        },
        "options": {"combine_devices": spec.lvs_combine_devices},
    }
    if spec.lvs_join_same_named_nets:
        request["layout"]["join_same_named_nets"] = True
    if spec.lvs_compare_parameters:
        request["options"]["compare_parameters"] = {
            device_class: list(params)
            for device_class, params in spec.lvs_compare_parameters.items()
        }
    return request


def run_klt_lvs(
    spec: CellSpec, request: dict, request_path: Path, report_path: Path, log: Path
) -> dict:
    """One ``klt lvs`` compare (``CellSpec.lvs_route == "klt"``).

    Writes ``request`` to ``request_path`` (paths inside it must already
    be relative to that file's directory -- see
    ``build_klt_lvs_request``), runs ``klt lvs`` from the repo root so the
    report's recorded paths are repo-scoped (``klt lvs --check`` can then
    re-hash them later), and writes the JSON envelope to ``report_path``
    via ``-o`` -- the committed-report artifact. Exit 0 is a match, 3 a
    mismatch (both successful runs); anything else is a StageError
    carrying klt's own output.
    """
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(request, indent=2) + "\n")
    rel_request = repo_arg(request_path)
    rel_report = repo_arg(report_path)
    proc = subprocess.run(
        [
            "klt", "lvs", str(rel_request),
            "--format", "json", "-o", str(rel_report),
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(proc.stdout + proc.stderr)
    if proc.returncode not in (0, 3):
        raise StageError(
            f"klt lvs failed for {spec.key} (exit {proc.returncode}); "
            f"full log at {log}\n"
            + "\n".join((proc.stdout + proc.stderr).splitlines()[-20:])
        )
    try:
        report = json.loads(report_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StageError(f"klt lvs wrote no readable report at {report_path}: {exc}")
    if report.get("status") not in ("match", "mismatch"):
        raise StageError(
            f"klt lvs reported no verdict for {spec.key}: "
            f"{json.dumps(report)[:300]}"
        )
    return {
        "match": report["status"] == "match",
        "report_path": report_path,
        "request_path": request_path,
        "engine": report.get("engine", "klayout"),
        "warnings": [
            entry["description"]
            for entry in report.get("mismatches", [])
            if entry.get("severity") == "warning"
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
    ok, pdk = check_env(spec.lvs_route, verbose=args.check_env)
    if args.check_env:
        return 0 if ok else 2
    if not ok or pdk is None:
        print(
            "layout/drclvs.py: environment is incomplete. Run "
            f"`python3 layout/drclvs.py --cell {spec.key} --check-env` for details.",
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
    # A committed-GDS cell (issue #784) runs every later stage against the
    # COMMITTED bytes -- the artifact the committed klt reports pin by
    # content hash -- after proving the fresh build reproduces them:
    # re-minting the GDS (and the reports pinning it) is a deliberate act
    # (--mint-gds), never a side effect of running the flow.
    stage_gds = gds
    if spec.gds_path is not None:
        if args.mint_gds or not spec.gds_path.is_file():
            spec.gds_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(gds, spec.gds_path)
            summary["gds_minted"] = str(spec.gds_path.relative_to(REPO_ROOT))
            print(
                f"      gds       : minted {spec.gds_path.relative_to(REPO_ROOT)} "
                "from this build (reports below pin these bytes)"
            )
        elif not gds_equal_modulo_timestamps(gds, spec.gds_path):
            raise StageError(
                f"the freshly built {gds.name} differs from the committed "
                f"{spec.gds_path.relative_to(REPO_ROOT)} by more than GDS "
                "timestamps. Every committed klt report pins the committed "
                "bytes by content hash, so the flow refuses to run stages "
                "against a layout the evidence does not describe. If the "
                "generator change is intended, re-mint deliberately with "
                "`--mint-gds` and re-run `--record` to refresh the reports."
            )
        stage_gds = spec.gds_path
        layout_line += (
            f", committed at {spec.gds_path.relative_to(REPO_ROOT)}"
        )
    # --record runs are the evidence-taking runs: only they write reports
    # into the committed, append-only trees (each named by this run's record
    # id, so a record and its reports are 1:1). Plain runs keep every
    # artifact in the scratch run directory, exactly as before #784.
    committed_reports = args.record and spec.gds_path is not None
    if committed_reports:
        (DRC_REPORTS_DIR / spec.key).mkdir(parents=True, exist_ok=True)
        (LVS_REPORTS_DIR / spec.key).mkdir(parents=True, exist_ok=True)

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
    # The LVS negative controls only mean something if every control this
    # run will use can actually corrupt this cell's netlist. Prove that NOW,
    # so that a cell whose controls do not apply fails here rather than
    # after the intact LVS comparison has already printed `lvs: MATCH`.
    controls = check_controls_apply(spec, netlist_text)
    total = 5 + len(controls) + (2 if spec.erc else 0)
    stage_no = 1
    print(f"[{stage_no}/{total}] {layout_line}")
    stage_no += 1
    print(f"[{stage_no}/{total}] netlist     : {len(device_lines)} device line(s), LVS form")
    stage_no += 1
    summary["netlist_devices"] = len(device_lines)
    print(
        "      controls  : "
        + ", ".join(f"{c.tag} ({c.what})" for c in controls.values())
        + " -- all applicable"
    )

    # ---- 3. klt drc ------------------------------------------------------
    klt_out = (
        DRC_REPORTS_DIR / spec.key / f"{rid}.drc.json"
        if committed_reports else run_dir / f"{spec.cell}.klt-drc.json"
    )
    klt_report = run_klt_drc(stage_gds, klt_out)
    klt_ok = klt_report["status"] == "clean"
    summary["klt_drc"] = {
        "status": klt_report["status"],
        "violations": klt_report["violation_count"],
        "dbu_um": klt_report["dbu_um"],
        "rule_counts": klt_report.get("rule_counts", {}),
        "report": klt_out.relative_to(REPO_ROOT) if committed_reports else None,
        "coverage": {
            key: (klt_report.get("coverage") or {}).get(key)
            for key in (
                "layers_in_stream_without_rules", "rules_skipped", "deck_scope"
            )
        },
    }
    print(
        f"[{stage_no}/{total}] klt drc     : {klt_report['status']} "
        f"({klt_report['violation_count']} violation(s), curated subset)"
        + (f" -> {klt_out.relative_to(REPO_ROOT)}" if committed_reports else "")
    )
    stage_no += 1
    if not klt_ok:
        failures.append(
            f"klt drc reported {klt_report['violation_count']} violation(s): "
            f"{klt_report.get('rule_counts')}"
        )

    # ---- 4. PDK drc deck, through klt ------------------------------------
    native_out = (
        DRC_REPORTS_DIR / spec.key / f"{rid}.drc-klayout.json"
        if committed_reports else run_dir / f"{spec.cell}.klt-drc-klayout.json"
    )
    pdk_drc = run_pdk_drc(pdk, spec, stage_gds, run_dir, run_dir / "pdk-drc.log", native_out)
    summary["pdk_drc"] = {
        "violations": pdk_drc["violations"],
        "rule_categories": pdk_drc["rule_categories"],
        "deck": pdk_drc["deck"],
        "decks_selection": pdk_drc["decks_selection"],
        "engine": pdk_drc["engine"],
        "asserted_categories": pdk_drc["asserted_categories"],
        "report": native_out.relative_to(REPO_ROOT) if committed_reports else None,
        "coverage": pdk_drc["coverage"],
    }
    print(
        f"[{stage_no}/{total}] pdk drc     : {pdk_drc['status']} "
        f"({pdk_drc['violations']} violation(s) across "
        f"{pdk_drc['rule_categories']} rule categories, "
        f"{pdk_drc['deck']} via klt --engine klayout, "
        f"decks={pdk_drc['decks_selection']}, categories asserted)"
        + (f" -> {native_out.relative_to(REPO_ROOT)}" if committed_reports else "")
    )
    stage_no += 1
    if pdk_drc["violations"]:
        failures.append(
            f"the PDK DRC deck reported {pdk_drc['violations']} violation(s); "
            f"see {pdk_drc['report']}"
        )
    if args.parity_raw_deck:
        raw = run_raw_pdk_drc_parity(
            pdk, spec, stage_gds, run_dir, run_dir / "pdk-drc-raw-parity.log"
        )
        parity = check_raw_parity(pdk_drc, raw, spec, run_dir)
        summary["raw_deck_parity"] = parity
        summary["pmap"] = raw["pmap"]
        print(f"      parity    : raw klayout run agrees -- {parity}")

    # ---- 5. ERC supply spec + intact run (cells that register one) -------
    # Issue #785: emit the cell's supply spec from the committed GDS, run
    # `klt erc --deck gf180mcu --findings-only` against it, and validate the
    # envelope against the cell's own contract (disclosed findings, one
    # island per declared net, ties checked and not skipped). The committed
    # spec is regenerated from the committed bytes, so writing it here is
    # idempotent; the report tree is append-only, minted per record id.
    erc_report_intact = None
    if spec.erc is not None:
        erc_spec_path = ERC_SPECS_DIR / f"{spec.key}.erc.json"
        erc_out = (
            ERC_REPORTS_DIR / spec.key / f"{rid}.erc.json"
            if committed_reports
            else run_dir / f"{spec.cell}.erc.json"
        )
        spec_line = run_erc_spec_gen(spec, stage_gds, erc_spec_path)
        print(f"      {spec_line}")
        erc_report_intact = run_klt_erc(spec, stage_gds, erc_spec_path, erc_out)
        erc_failures, summary["erc"] = validate_erc_report(
            erc_report_intact, spec
        )
        summary["erc"]["spec"] = str(erc_spec_path.relative_to(REPO_ROOT))
        summary["erc"]["report"] = (
            str(erc_out.relative_to(REPO_ROOT)) if committed_reports else None
        )
        disclosed = ", ".join(
            f"{rule} on {net}" for rule, net in spec.erc.expected_findings
        ) or "none disclosed"
        print(
            f"[{stage_no}/{total}] klt erc     : "
            f"{summary['erc']['erc_status']} "
            f"({len(summary['erc']['findings'])}"
            f" finding(s); disclosed: {disclosed}; islands: "
            + ", ".join(
                f"{n['name']}={n['matched_islands']}"
                for n in summary["erc"]["nets"]
            )
            + ")"
            + (f" -> {erc_out.relative_to(REPO_ROOT)}" if committed_reports else "")
        )
        stage_no += 1
        failures.extend(f"ERC supply run: {failure}" for failure in erc_failures)

    # ---- LVS -------------------------------------------------------------
    if spec.lvs_route == "klt":
        reports_dir = LVS_REPORTS_DIR / spec.key
        request_path = (
            reports_dir / f"{rid}.lvs-request.json"
            if committed_reports
            else run_dir / f"{spec.cell}.lvs-request.json"
        )
        report_path = (
            reports_dir / f"{rid}.lvs.json"
            if committed_reports
            else run_dir / f"{spec.cell}.lvs.json"
        )
        request = build_klt_lvs_request(
            spec, pdk,
            os.path.relpath(stage_gds, request_path.parent),
            os.path.relpath(committed, request_path.parent),
        )
        lvs = run_klt_lvs(spec, request, request_path, report_path, run_dir / "lvs.log")
        summary["lvs"] = {
            "match": lvs["match"],
            "warnings": lvs["warnings"],
            "engine": f"klt lvs ({lvs['engine']})",
            "report": (
                str(report_path.relative_to(REPO_ROOT)) if committed_reports else None
            ),
        }
        mismatch_where = f"see {report_path}"
    else:
        lvs = run_lvs(pdk, spec, stage_gds, netlist, run_dir, run_dir / "lvs.log", "lvs")
        summary["lvs"] = {
            "match": lvs["match"],
            "warnings": lvs["warnings"],
            "engine": "PDK gf180mcu.lvs runset (raw klayout -b -r)",
        }
        summary["pmap"] = lvs["pmap"]
        mismatch_where = f"see {lvs['lvsdb']}"
    print(
        f"[{stage_no}/{total}] lvs         : {'MATCH' if lvs['match'] else 'MISMATCH'} "
        f"[{summary['lvs']['engine']}]"
    )
    stage_no += 1
    for warning in lvs["warnings"]:
        print(f"                    note: {warning}")
    if not lvs["match"]:
        failures.append(f"LVS reported a mismatch; {mismatch_where}")

    # ---- LVS negative controls ------------------------------------------
    # The set was chosen, and proven applicable, by check_controls_apply()
    # back at stage 2: the cell's own topology/parameter pair (MOS_CONTROLS,
    # or PASSIVE_CONTROLS for an all-passive cell such as the divider), plus
    # one per passive element class the netlist contains. Each control runs
    # through the SAME route the LVS stage took -- a control that only exercised
    # the other route would prove nothing about the report being committed.
    summary["lvs_negative_controls"] = {}
    for control in controls.values():
        tag, what, implication = control.tag, control.what, control.implication
        bad = run_dir / f"{spec.cell}.control-{tag}.spice"
        bad.write_text(apply_control(spec, control, netlist_text))
        if spec.lvs_route == "klt":
            request = build_klt_lvs_request(
                spec, pdk,
                os.path.relpath(stage_gds, run_dir),
                bad.name,  # sits beside the scratch request below
            )
            result = run_klt_lvs(
                spec, request,
                run_dir / f"{spec.cell}.control-{tag}.lvs-request.json",
                run_dir / f"{spec.cell}.control-{tag}.lvs.json",
                run_dir / f"lvs-control-{tag}.log",
            )
        else:
            result = run_lvs(
                pdk, spec, stage_gds, bad, run_dir,
                run_dir / f"lvs-control-{tag}.log", f"control-{tag}",
            )
        summary["lvs_negative_controls"][tag] = {
            "match": result["match"], "mutation": what,
        }
        verdict = "MISMATCH (expected)" if not result["match"] else "MATCH -- WRONG"
        print(f"[{stage_no}/{total}] control {tag:<10}: {what} -> {verdict}")
        stage_no += 1
        if result["match"]:
            failures.append(
                f"the LVS {tag} negative control ({what}) MATCHED, which means "
                f"{implication}. The LVS invocation is not actually comparing "
                "what it appears to compare -- a 'match' from it is worthless."
            )

    # ---- last: the ERC negative control (cells that register one) --------
    # After the LVS controls, through the same ERC invocation the intact
    # run took: sever the declared tie's connection in a disposable copy of
    # the committed GDS and require exactly one new erc.missing_tie on the
    # intended tie (issue #785 -- "a run that cannot fail is not evidence").
    if spec.erc is not None and erc_report_intact is not None:
        erc_control = run_erc_control(
            spec, stage_gds, ERC_SPECS_DIR / f"{spec.key}.erc.json",
            erc_report_intact, run_dir,
        )
        summary["erc_control"] = erc_control
        verdict = (
            "erc.missing_tie, as required"
            if erc_control["finding"] and not erc_control["failures"]
            else "NO FINDING -- INVALID RUN"
        )
        print(
            f"[{stage_no}/{total}] erc control: {erc_control['mutation']} "
            f"-> {verdict}"
        )
        stage_no += 1
        failures.extend(
            f"ERC negative control: {failure}"
            for failure in erc_control["failures"]
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
    if spec.erc is not None:
        print("    The klt erc supply run is clean under the cell's disclosed")
        print("    findings, and its tie-severing control fails as required.")
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

    def coverage_row(label: str, coverage: dict) -> str:
        """One disclosure row quoting a DRC report's own coverage block.

        Issue #784: the record must quote `layers_in_stream_without_rules`,
        `rules_skipped` and `deck_scope` verbatim per DRC report, so a
        "clean" claim can never silently mean "clean under the subset the
        deck happened to check".
        """
        layers = coverage.get("layers_in_stream_without_rules") or []
        skipped = coverage.get("rules_skipped") or []
        scope = coverage.get("deck_scope") or []
        if skipped:
            # Quote the whole field: a truncated list would let "clean" read
            # as covering rules the report says were skipped.
            skipped_text = f"{', '.join(skipped)} ({len(skipped)} rule(s))"
        else:
            skipped_text = "none"
        return (
            f"| DRC coverage -- {label} | "
            f"`layers_in_stream_without_rules`: {layers or 'none'}; "
            f"`rules_skipped`: {skipped_text}; "
            f"`deck_scope`: {scope or 'none'} |"
        )

    artifacts = []
    if spec.gds_path is not None:
        artifacts.append(
            f"- GDS `{spec.gds_path.relative_to(REPO_ROOT)}` -- committed "
            "(the input every report below pins by content hash); "
            "reproducibly generated by `klayout -b -r "
            f"{spec.gen_gds.relative_to(REPO_ROOT)} -rd out=<gds> "
            f"-rd pdk=<installed {pdk.variant} root>`"
            + (" -- **minted by this run**" if summary.get("gds_minted") else "")
        )
    for stage, entry in (("klt_drc", klt), ("pdk_drc", drc)):
        if summary[stage].get("report"):
            artifacts.append(
                f"- Report `{summary[stage]['report']}` "
                f"({stage == 'klt_drc' and 'curated deck' or 'PDK deck via klt --engine klayout'})"
            )
    if summary["lvs"].get("report"):
        artifacts.append(f"- Report `{summary['lvs']['report']}` (klt lvs)")
    if summary.get("erc"):
        artifacts.append(
            f"- Supply spec `{summary['erc']['spec']}` -- committed, emitted "
            "from the committed GDS by `klayout -b -r layout/erc/gen_spec.py`"
        )
        if summary["erc"].get("report"):
            artifacts.append(
                f"- Report `{summary['erc']['report']}` (klt erc, findings-only)"
            )

    pmap_row = (
        f"`{summary['pmap']}` (the PDK decks' memory logger; `shimmed` = this "
        "host has no procps pmap(1) and `drclvs.py` supplied a ps(1)-backed "
        "stand-in)"
        if summary.get("pmap")
        else "not driven (no raw PDK deck ran this flow; klt-driven stages "
        "have no pmap dependency)"
    )
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
| pmap | {pmap_row} |

## Results

| Stage | Result |
| --- | --- |
| DRC -- `klt drc --deck gf180mcu` | **{klt['status']}**, {klt['violations']} violation(s); layout dbu {klt['dbu_um']} um |
| DRC -- PDK deck via `klt drc --engine klayout` (`{drc['deck']}`, `decks={drc['decks_selection']}`, {drc['asserted_categories']} asserted categories) | **{drc['violations']} violation(s)** across {drc['rule_categories']} rule categories |
| LVS -- {summary['lvs']['engine']} vs. xschem export | **{'match' if summary['lvs']['match'] else 'MISMATCH'}** |
{control_rows(summary)}
{erc_result_rows(summary)}
{coverage_row('klt drc curated deck', klt.get('coverage') or {})}
{coverage_row('PDK deck (klt, engine klayout)', drc.get('coverage') or {})}

{('Raw-deck parity: ' + summary['raw_deck_parity'] + '.') if summary.get('raw_deck_parity') else ''}

Schematic netlist: {summary['netlist_devices']} device line(s), exported in
xschem's `lvs_netlist` form from `{schematic_rel}`.
{erc_section(summary) if summary.get("erc") else ""}
## Committed artifacts

{chr(10).join(artifacts) if artifacts else 'None (scratch-only cell: every artifact lives in the gitignored run directory).'}

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
    note = spec.record_notes() if spec.record_notes else ""
    if note:
        body += "\n" + note.rstrip("\n") + "\n"
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
        help="write an append-only run record under layout/records/ (and, "
             "for a committed-GDS cell, the klt DRC/LVS reports under "
             "layout/drc/reports/ and layout/lvs/reports/, named by the "
             "same record id)",
    )
    parser.add_argument(
        "--mint-gds", action="store_true",
        help="deliberately (re)write the cell's committed GDS from this "
             "run's fresh build. The committed GDS is what every committed "
             "klt report pins by content hash, so it never changes as a "
             "side effect -- re-run with --record afterwards to refresh "
             "the reports",
    )
    parser.add_argument(
        "--parity-raw-deck", action="store_true",
        help="also run the retired raw `klayout -b -r` PDK DRC invocation "
             "and hard-fail unless it reaches the same verdict and "
             "rule-category set as the klt native-deck stage (the "
             "migration check issue #784 requires before the raw path "
             "goes)",
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
