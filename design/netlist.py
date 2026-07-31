#!/usr/bin/env python3
"""Export ngspice netlists from the xschem sources in ``design/``.

    python3 design/netlist.py            # regenerate design/netlist/*.spice
    python3 design/netlist.py --check    # verify committed netlists are current
    python3 design/netlist.py --cell ldo_erramp_placeholder

Every ``design/*.sch`` cell is netlisted **as a ``.subckt``** (never as a flat
deck), with xschem's electrical rule check enabled (``xschem netlist -erc``),
into ``design/netlist/<cell>.spice``:

* ``ldo_core.spice`` carries the whole hierarchy -- ``ldo_core`` plus every
  sub-circuit definition it instantiates (currently just
  ``ldo_erramp_placeholder``).
* ``ldo_erramp_placeholder.spice`` is that sub-circuit on its own, so a
  testbench can target it in isolation (e.g. a future amp-only bench once
  issue #9 replaces the placeholder).

The export is deterministic: absolute paths that xschem records in ``sch_path``
/ ``sym_path`` comments are rewritten repo-relative, so the same sources produce
byte-identical netlists on any machine. ``--check`` re-runs the export into a
temporary directory and diffs it against what is committed; it fails if the
committed netlists are stale, if the export is not reproducible, if xschem's
ERC reports a problem, or if a pinout/port-order invariant is broken.

PDK discovery is delegated to ``sim/harness/pdk.py`` so the repo has exactly one
implementation of "where is gf180mcu". Pattern adapted from
2AMLogic/gf180-temp-por's design/netlist.py (see CLAUDE.md's harness-bootstrap
note), trimmed to this repo's (currently two-cell) hierarchy.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DESIGN_DIR = Path(__file__).resolve().parent
REPO_ROOT = DESIGN_DIR.parent
NETLIST_DIR = DESIGN_DIR / "netlist"
XSCHEMRC = DESIGN_DIR / "xschemrc"

sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness.pdk import PdkNotFound, find_pdk  # noqa: E402

TOP_CELL = "ldo_core"

# The interface contract issue #8 establishes for #9/#10/#11/#12/#13 to build
# on. Changing this list means renegotiating that contract, not just editing
# this file -- see design/README.md.
RATIFIED_TOP_PORTS = ["VIN", "VOUT", "EN", "VSS", "ERRAMP_OUT", "PASS_GATE"]

SUBCKT_RE = re.compile(r"^\.subckt\s+(\S+)\s*(.*)$", re.IGNORECASE)
SYM_PIN_RE = re.compile(r"^B\s+\d+\s+\S+\s+\S+\s+\S+\s+\S+\s*\{(.*)\}\s*$")
SCH_PIN_RE = re.compile(r"^C\s+\{devices/(i|o|io)pin\.sym\}\s+.*?\{(.*)\}\s*$")


class ExportError(RuntimeError):
    pass


def cells() -> list[str]:
    """All cells in design/, top level first then sub-circuits alphabetically."""
    names = sorted(p.stem for p in DESIGN_DIR.glob("*.sch"))
    if TOP_CELL not in names:
        raise ExportError(f"{DESIGN_DIR}/{TOP_CELL}.sch is missing")
    return [TOP_CELL] + [n for n in names if n != TOP_CELL]


def xschem_env() -> dict[str, str]:
    """Environment for xschem: the PDK the sim harness would use."""
    pdk = find_pdk()
    env = dict(os.environ)
    env["PDK_ROOT"] = str(pdk.path.parent)
    env["PDK"] = pdk.variant
    env["GF180_PDK_PATH"] = str(pdk.path)
    # Keep batch runs off the user's ~/.xschem state.
    env.setdefault("XSCHEM_USER_LIBRARY_PATH", str(DESIGN_DIR))
    return env


def normalize(text: str) -> str:
    """Make xschem output machine-independent (and therefore diffable)."""
    text = text.replace(str(REPO_ROOT) + os.sep, "")
    # Trailing whitespace is not load bearing and varies with symbol text.
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.rstrip("\n") + "\n"


def export_cell(cell: str, outdir: Path, env: dict[str, str]) -> str:
    """Run xschem headless on one cell (ERC + netlist) and return its normalized netlist."""
    sch = DESIGN_DIR / f"{cell}.sch"
    if not sch.is_file():
        raise ExportError(f"no such cell: {sch}")
    cmd = [
        "xschem",
        "-x",  # no X11: batch
        "-q",  # quit when done
        "-r",  # no tclreadline (stdin/stdout may be redirected)
        "--rcfile", str(XSCHEMRC),
        "-o", str(outdir),
        str(sch),
        "--command", "xschem netlist -erc",
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    produced = outdir / f"{cell}.spice"
    noisy = proc.stdout + proc.stderr
    # xschem exits 0 even when ERC/connectivity checks fail (they are printed,
    # not turned into a nonzero exit code), so grep for the failure classes it
    # emits during netlisting: undriven/floating nodes, shorted nodes/pins,
    # and missing symbols (a silently-unresolved reference nets everything
    # under an auto-generated name instead of erroring -- see
    # gf180-pll/design/xschemrc's warning about this failure mode).
    erc_problem = re.search(
        r"(undriven node|open net|shorted output node|instance pin shorted|"
        r"symbol not found|IS MISSING)",
        noisy,
        re.IGNORECASE,
    )
    if proc.returncode != 0 or not produced.is_file() or erc_problem:
        raise ExportError(
            f"xschem failed for {cell} (exit {proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    text = normalize(produced.read_text())
    header = (
        f"* {cell} -- generated by design/netlist.py from design/{cell}.sch\n"
        f"* Do not edit: edit the schematic and re-run the export.\n"
    )
    return header + text


def symbol_pins(cell: str) -> list[str] | None:
    """Pin names, in order, from design/<cell>.sym (None if there is no symbol)."""
    sym = DESIGN_DIR / f"{cell}.sym"
    if not sym.is_file():
        return None
    pins: list[str] = []
    for line in sym.read_text().splitlines():
        match = SYM_PIN_RE.match(line)
        if not match:
            continue
        attrs = match.group(1)
        name = re.search(r"\bname=(\S+)", attrs)
        if name:
            pins.append(name.group(1))
    return pins


def schematic_ports(cell: str) -> list[str]:
    """Port names, in order, from the ipin/opin/iopin instances in <cell>.sch."""
    ports: list[str] = []
    for line in (DESIGN_DIR / f"{cell}.sch").read_text().splitlines():
        match = SCH_PIN_RE.match(line)
        if not match:
            continue
        lab = re.search(r"\blab=(\S+)", match.group(2))
        if lab:
            ports.append(lab.group(1))
    return ports


def subckt_ports(netlist: str, cell: str) -> list[str]:
    for line in netlist.splitlines():
        match = SUBCKT_RE.match(line.strip())
        if match and match.group(1) == cell:
            return match.group(2).split()
    raise ExportError(f".subckt {cell} not found in its own netlist")


def instance_lines(netlist: str, cell: str) -> list[list[str]]:
    """Instance lines of `cell` inside the top-level .subckt block."""
    found = []
    for line in netlist.splitlines():
        tokens = line.split()
        if len(tokens) >= 2 and tokens[0].lower().startswith("x") and tokens[-1] == cell:
            found.append(tokens)
    return found


def check_invariants(netlists: dict[str, str]) -> list[str]:
    """Pinout / port-order invariants. Returns a list of failure messages."""
    failures: list[str] = []

    top_ports = subckt_ports(netlists[TOP_CELL], TOP_CELL)
    if top_ports != RATIFIED_TOP_PORTS:
        failures.append(
            f"top-level pinout drifted from the interface issue #8 established:\n"
            f"    expected: {RATIFIED_TOP_PORTS}\n"
            f"    netlist:  {top_ports}\n"
            f"  (see design/README.md -- #9/#10/#11/#12/#13 all build on this)"
        )

    for cell, netlist in netlists.items():
        ports = subckt_ports(netlist, cell)
        pins = symbol_pins(cell)
        if pins is None:
            failures.append(f"{cell}: no design/{cell}.sym -- cell is not instantiable")
            continue
        # xschem takes the .subckt port list from the *symbol* when one exists,
        # so a symbol whose pins have drifted from the schematic's own pins
        # silently drops or renames a port on every instantiation. Compare the
        # two sources directly rather than trusting the netlist alone.
        sch_pins = schematic_ports(cell)
        if pins != sch_pins:
            failures.append(
                f"{cell}: symbol pins and schematic ports disagree.\n"
                f"    {cell}.sym:  {pins}\n"
                f"    {cell}.sch:  {sch_pins}\n"
                f"  xschem netlists the ports from the symbol, so this silently\n"
                f"  miswires or drops a port on every instantiation of the cell."
            )
        if pins != ports:
            failures.append(
                f"{cell}: symbol pin order does not match the exported .subckt.\n"
                f"    {cell}.sym:  {pins}\n"
                f"    .subckt:    {ports}"
            )

    top = netlists[TOP_CELL]
    for cell in netlists:
        if cell == TOP_CELL:
            continue
        instances = instance_lines(top, cell)
        if not instances:
            failures.append(f"{cell}: not instantiated in {TOP_CELL}")
            continue
        width = len(subckt_ports(netlists[cell], cell))
        for tokens in instances:
            nets = tokens[1:-1]
            if len(nets) != width:
                failures.append(
                    f"{TOP_CELL}: instance {tokens[0]} of {cell} connects "
                    f"{len(nets)} nets, but {cell} has {width} ports"
                )
    return failures


def run(check: bool, only: str | None, verbose: bool) -> int:
    try:
        env = xschem_env()
    except PdkNotFound as exc:
        print(f"design/netlist.py: {exc}", file=sys.stderr)
        return 2

    wanted = [only] if only else cells()
    netlists: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="gf180-ldo-netlist-") as tmp:
        outdir = Path(tmp)
        for cell in wanted:
            netlists[cell] = export_cell(cell, outdir, env)
            if verbose:
                print(f"  netlisted {cell}")

    status = 0
    if only:
        # A single-cell run cannot evaluate the cross-cell invariants.
        failures: list[str] = []
    else:
        failures = check_invariants(netlists)

    if check:
        for cell, text in netlists.items():
            committed = NETLIST_DIR / f"{cell}.spice"
            if not committed.is_file():
                failures.append(f"{committed.relative_to(REPO_ROOT)} is missing")
                continue
            have = committed.read_text()
            if have != text:
                diff = "\n".join(
                    difflib.unified_diff(
                        have.splitlines(),
                        text.splitlines(),
                        fromfile=f"committed/{cell}.spice",
                        tofile=f"regenerated/{cell}.spice",
                        lineterm="",
                    )
                )
                failures.append(
                    f"{cell}: committed netlist is stale or the export is not "
                    f"reproducible:\n{diff}"
                )
    else:
        NETLIST_DIR.mkdir(exist_ok=True)
        for cell, text in netlists.items():
            target = NETLIST_DIR / f"{cell}.spice"
            target.write_text(text)
            print(f"wrote {target.relative_to(REPO_ROOT)}")

    if failures:
        print("\nFAIL:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        status = 1
    elif check:
        print(f"OK: {len(netlists)} netlist(s) reproduce byte-for-byte, ERC is clean, "
              f"and the pinout invariants hold.")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export ngspice netlists from design/*.sch via xschem.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; verify the committed netlists are current and the "
             "pinout invariants hold",
    )
    parser.add_argument(
        "--cell",
        help="export a single cell (skips the cross-cell invariant checks)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    try:
        return run(check=args.check, only=args.cell, verbose=args.verbose)
    except ExportError as exc:
        print(f"design/netlist.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
