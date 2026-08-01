#!/usr/bin/env python3
"""Run DRC and LVS on the gf180mcu bring-up test cell -- one command.

    python3 layout/drclvs.py               # build, export, DRC, LVS; print a summary
    python3 layout/drclvs.py --check       # same, plus: the committed netlist must be current
    python3 layout/drclvs.py --check-env   # report which tools/PDK are visible, then stop
    python3 layout/drclvs.py --record      # also write layout/records/<record-id>.md
    python3 layout/drclvs.py --keep        # keep the run directory (default: keep only on failure)

Exit status is 0 only if **every** stage passed. See layout/README.md for what
each stage means and what it does and does not prove.

What this runs, in order
------------------------

1. **Build the layout.** ``klayout -b -r layout/testcell/gen_gds.py`` draws the
   test cell from the PDK's own ``nfet`` PCell (correct by construction) and
   adds the four net labels LVS needs.
2. **Export the schematic netlist.** ``xschem`` headless, ERC on, through
   ``layout/xschemrc`` -- which is ``design/xschemrc`` plus ``lvs_netlist 1``,
   so devices render from the PDK symbols' ``lvs_format`` (``M1 D G S VSS
   nfet_03v3 L=.. W=.. nf=.. m=..``) rather than their ngspice ``format``
   (``XM1 ... ad='int((nf+1)/2) * ...'``, which KLayout's SPICE reader cannot
   evaluate). Same export mechanism as ``design/netlist.py``.
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
   netlist with the device's gate shorted to its drain. Must report a mismatch.
7. **LVS negative control -- device parameters.** And against a copy with the
   device width doubled but the topology untouched. Must also report a
   mismatch.

   Steps 6 and 7 are not decoration. Without them, "LVS passed" is not evidence
   that the compare looked at anything: a mis-wired invocation that silently
   compares nothing also "passes", and a compare that checks connectivity but
   ignores device parameters would wave through a mis-sized transistor. Each
   control isolates one of those.

Nothing here is LDO-specific: the test cell is one transistor and exists only
to prove the flow. Driving a real block through it is a later issue's job; the
invocation is the deliverable.
"""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = LAYOUT_DIR.parent
TESTCELL_DIR = LAYOUT_DIR / "testcell"
NETLIST_DIR = TESTCELL_DIR / "netlist"
RECORDS_DIR = LAYOUT_DIR / "records"
WORK_DIR = LAYOUT_DIR / ".work"
XSCHEMRC = LAYOUT_DIR / "xschemrc"
GEN_GDS = TESTCELL_DIR / "gen_gds.py"

CELL = "drclvs_testcell"
TOP_CELL = "DRCLVS_TESTCELL"   # gen_gds.py's top cell name
SUBSTRATE_NET = "VSS"          # the schematic's bulk port == the LVS substrate net

sys.path.insert(0, str(REPO_ROOT / "sim"))
from harness.pdk import Pdk, PdkNotFound, find_pdk  # noqa: E402

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


class StageError(RuntimeError):
    """A stage could not run at all (missing tool, bad invocation)."""


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
# stage 1 -- layout
# --------------------------------------------------------------------------

def build_gds(pdk: Pdk, out: Path, log: Path) -> None:
    cmd = [
        "klayout", "-b", "-r", str(GEN_GDS),
        "-rd", f"out={out}",
        "-rd", f"pdk={pdk.path}",
    ]
    run_logged(cmd, log, "layout build")
    if not out.is_file():
        raise StageError(f"layout build produced no {out} (see {log})")


# --------------------------------------------------------------------------
# stage 2 -- schematic netlist
# --------------------------------------------------------------------------

def export_netlist(pdk: Pdk, outdir: Path) -> str:
    """Netlist the test cell in LVS form. Returns the normalized text."""
    env = dict(os.environ)
    env["PDK_ROOT"] = str(pdk.path.parent)
    env["PDK"] = pdk.variant
    env["GF180_PDK_PATH"] = str(pdk.path)
    env["XSCHEM_USER_LIBRARY_PATH"] = str(TESTCELL_DIR)
    cmd = [
        "xschem",
        "-x",   # batch, no X11
        "-q",   # quit when done
        "-r",   # no tclreadline
        "--rcfile", str(XSCHEMRC),
        "-o", str(outdir),
        str(TESTCELL_DIR / f"{CELL}.sch"),
        "--command", "xschem netlist -erc",
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    produced = outdir / f"{CELL}.spice"
    noisy = proc.stdout + proc.stderr
    # xschem exits 0 even when its connectivity checks fail, so grep for the
    # failure classes it prints. Same list design/netlist.py uses.
    erc = re.search(
        r"(undriven node|open net|shorted output node|instance pin shorted|"
        r"symbol not found|IS MISSING)",
        noisy,
        re.IGNORECASE,
    )
    if proc.returncode != 0 or not produced.is_file() or erc:
        raise StageError(
            f"xschem failed for {CELL} (exit {proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )

    text = produced.read_text()
    if SIM_FORM_RE.search(text):
        raise StageError(
            "the exported netlist is in xschem's SIMULATION form "
            "(X-prefixed subcircuit calls), not the LVS form KLayout's SPICE "
            "reader needs.\n"
            "  This means `lvs_netlist` did not take effect. The usual cause is "
            "an xschem older than 3.4.6 -- the version Debian/Ubuntu package "
            "(3.4.4) has no `lvs_format` support at all and silently ignores "
            "the switch.\n"
            f"  `xschem --version` here: {xschem_version()}\n"
            "  This repo pins 3.4.7; see docs/environment-setup.md.\n"
            f"--- exported ---\n{text}"
        )
    if f".subckt {CELL}" not in text:
        raise StageError(
            f"the exported netlist has no `.subckt {CELL}` line -- xschem "
            "emitted the commented `**.subckt` form, which KLayout will not "
            "read. This is also an xschem-too-old symptom "
            f"(`xschem --version`: {xschem_version()}; this repo pins 3.4.7).\n"
            f"--- exported ---\n{text}"
        )

    # Make the export machine-independent so the committed copy is diffable.
    text = text.replace(str(REPO_ROOT) + os.sep, "")
    text = "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n") + "\n"
    header = (
        f"* {CELL} -- generated by layout/drclvs.py from "
        f"layout/testcell/{CELL}.sch\n"
        f"* LVS reference netlist (xschem lvs_netlist form). Do not edit: edit\n"
        f"* the schematic and re-run the export.\n"
    )
    return header + text


def xschem_version() -> str:
    try:
        out = subprocess.run(
            ["xschem", "--version"], capture_output=True, text=True, timeout=30
        )
        return (out.stdout + out.stderr).strip().splitlines()[0]
    except Exception:  # noqa: BLE001 -- diagnostics only
        return "unknown"


def _mos_line(text: str) -> tuple[str, list[str]]:
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) >= 6 and tokens[0].upper().startswith("M"):
            return line, tokens
    raise StageError(
        "could not build the LVS negative controls: no MOS element line found "
        "in the exported netlist"
    )


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


def control_parameter(text: str) -> str:
    """Double the device width -- a device-parameter corruption.

    Topologically identical to the real netlist, so this control fails only if
    the compare is actually checking device parameters and not just the
    connection graph.
    """
    line, tokens = _mos_line(text)
    resized = [
        re.sub(r"^W=2u$", "W=4u", token, flags=re.IGNORECASE) for token in tokens
    ]
    if resized == tokens:
        raise StageError(
            "could not build the LVS parameter control: expected a `W=2u` "
            f"parameter on the device line, got: {line}"
        )
    return text.replace(line, " ".join(resized))


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


def run_pdk_drc(pdk: Pdk, gds: Path, run_dir: Path, log: Path) -> dict:
    deck, table_count = assemble_pdk_drc_deck(pdk, run_dir)
    report = run_dir / f"{CELL}.lyrdb"
    switches = {
        "input": str(gds),
        "report": str(report),
        "topcell": TOP_CELL,
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
    run_logged(cmd, log, "PDK DRC deck")
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
    }


# --------------------------------------------------------------------------
# stage 5/6 -- LVS
# --------------------------------------------------------------------------

def run_lvs(
    pdk: Pdk, gds: Path, netlist: Path, run_dir: Path, log: Path, tag: str
) -> dict:
    lvsdb = run_dir / f"{tag}.lvsdb"
    extracted = run_dir / f"{tag}_extracted.cir"
    switches = {
        "input": str(gds),
        "schematic": str(netlist),
        "report": str(lvsdb),
        "target_netlist": str(extracted),
        "topcell": TOP_CELL,
        "thr": str(max(1, min(4, os.cpu_count() or 1))),
        "run_mode": "deep",
        "lvs_sub": SUBSTRATE_NET,
        "verbose": "false",
        "spice_net_names": "true",
        "spice_comments": "false",
        "scale": "false",
        "schematic_simplify": "false",
        "net_only": "false",
        "top_lvl_pins": "false",
        "combine": "false",
        "purge": "false",
        "purge_nets": "false",
        "poly_res": "1k",
        "mim_cap": "2",
        **variant_switches(pdk),
    }
    cmd = ["klayout", "-b", "-r", str(pdk.klayout_dir / "lvs" / "gf180mcu.lvs")]
    for key, value in switches.items():
        cmd += ["-rd", f"{key}={value}"]
    output = run_logged(cmd, log, f"LVS ({tag})")

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

def run_logged(cmd: list[str], log: Path, what: str) -> str:
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    log.write_text(output)
    if proc.returncode != 0:
        raise StageError(
            f"{what} failed (exit {proc.returncode}); full log at {log}\n"
            + "\n".join(output.splitlines()[-20:])
        )
    return output


def short_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip() or "nogit"
    except Exception:  # noqa: BLE001
        return "nogit"


def record_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{short_sha()}"


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
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

    rid = record_id()
    run_dir = WORK_DIR / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    summary: dict = {"record_id": rid, "pdk": pdk.provenance()}

    print(f"record id : {rid}")
    print(f"pdk       : {pdk.path} ({pdk.variant}, {pdk.version})")
    print(f"run dir   : {run_dir}")
    print()

    # ---- 1. layout -------------------------------------------------------
    gds = run_dir / f"{CELL}.gds"
    build_gds(pdk, gds, run_dir / "build-gds.log")
    print(f"[1/7] layout      : {gds.name} ({gds.stat().st_size} bytes)")

    # ---- 2. schematic netlist -------------------------------------------
    with tempfile.TemporaryDirectory(prefix="gf180-ldo-lvs-netlist-") as tmp:
        netlist_text = export_netlist(pdk, Path(tmp))
    committed = NETLIST_DIR / f"{CELL}.spice"
    if args.check:
        if not committed.is_file():
            failures.append(f"{committed.relative_to(REPO_ROOT)} is missing")
        elif committed.read_text() != netlist_text:
            diff = "\n".join(
                difflib.unified_diff(
                    committed.read_text().splitlines(),
                    netlist_text.splitlines(),
                    fromfile=f"committed/{CELL}.spice",
                    tofile=f"regenerated/{CELL}.spice",
                    lineterm="",
                )
            )
            failures.append(
                f"the committed LVS netlist is stale or the export is not "
                f"reproducible:\n{diff}"
            )
    else:
        NETLIST_DIR.mkdir(parents=True, exist_ok=True)
        committed.write_text(netlist_text)
    netlist = run_dir / f"{CELL}.spice"
    netlist.write_text(netlist_text)
    device_lines = [
        line for line in netlist_text.splitlines()
        if line and line[0].upper() in "MRCDQ" and not line.startswith("*")
    ]
    print(f"[2/7] netlist     : {len(device_lines)} device line(s), LVS form")
    summary["netlist_devices"] = len(device_lines)

    # ---- 3. klt drc ------------------------------------------------------
    klt_report = run_klt_drc(gds, run_dir / f"{CELL}.klt-drc.json")
    klt_ok = klt_report["status"] == "clean"
    summary["klt_drc"] = {
        "status": klt_report["status"],
        "violations": klt_report["violation_count"],
        "dbu_um": klt_report["dbu_um"],
        "rule_counts": klt_report.get("rule_counts", {}),
    }
    print(
        f"[3/7] klt drc     : {klt_report['status']} "
        f"({klt_report['violation_count']} violation(s), curated subset)"
    )
    if not klt_ok:
        failures.append(
            f"klt drc reported {klt_report['violation_count']} violation(s): "
            f"{klt_report.get('rule_counts')}"
        )

    # ---- 4. PDK drc deck -------------------------------------------------
    pdk_drc = run_pdk_drc(pdk, gds, run_dir, run_dir / "pdk-drc.log")
    summary["pdk_drc"] = {
        "violations": pdk_drc["violations"],
        "rule_categories": pdk_drc["rule_categories"],
        "rule_tables": pdk_drc["rule_tables"],
    }
    print(
        f"[4/7] pdk drc     : {pdk_drc['violations']} violation(s) across "
        f"{pdk_drc['rule_categories']} rule categories "
        f"({pdk_drc['rule_tables']} rule tables)"
    )
    if pdk_drc["violations"]:
        failures.append(
            f"the PDK DRC deck reported {pdk_drc['violations']} violation(s); "
            f"see {pdk_drc['report']}"
        )

    # ---- 5. LVS ----------------------------------------------------------
    lvs = run_lvs(pdk, gds, netlist, run_dir, run_dir / "lvs.log", "lvs")
    summary["lvs"] = {"match": lvs["match"], "warnings": lvs["warnings"]}
    print(f"[5/7] lvs         : {'MATCH' if lvs['match'] else 'MISMATCH'}")
    for warning in lvs["warnings"]:
        print(f"                    note: {warning}")
    if not lvs["match"]:
        failures.append(f"LVS reported a mismatch; see {lvs['lvsdb']}")

    # ---- 6/7. LVS negative controls -------------------------------------
    controls = {
        "topology": (
            control_topology,
            "gate shorted to drain",
            "a 4-net circuit compared equal to a 3-net one",
        ),
        "parameter": (
            control_parameter,
            "device width doubled",
            "device parameters are not being compared at all",
        ),
    }
    summary["lvs_negative_controls"] = {}
    for index, (tag, (mutate, what, implication)) in enumerate(controls.items(), 6):
        bad = run_dir / f"{CELL}.control-{tag}.spice"
        bad.write_text(mutate(netlist_text))
        result = run_lvs(
            pdk, gds, bad, run_dir, run_dir / f"lvs-control-{tag}.log", f"control-{tag}"
        )
        summary["lvs_negative_controls"][tag] = {
            "match": result["match"], "mutation": what,
        }
        verdict = "MISMATCH (expected)" if not result["match"] else "MATCH -- WRONG"
        print(f"[{index}/7] control {tag[:4]}: {what} -> {verdict}")
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
    print("    both negative controls correctly fail.")
    if args.record:
        path = write_record(rid, summary, pdk)
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


def write_record(rid: str, summary: dict, pdk: Pdk) -> Path:
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    path = RECORDS_DIR / f"{rid}.md"
    klt = summary["klt_drc"]
    drc = summary["pdk_drc"]
    warnings = summary["lvs"]["warnings"]
    body = f"""# DRC/LVS bring-up run `{rid}`

Produced by `python3 layout/drclvs.py --record`. Append-only: a re-run mints a
new record rather than editing this one.

| | |
| --- | --- |
| Cell | `{CELL}` (layout top cell `{TOP_CELL}`) -- one `nfet_03v3`, W=2 um, L=0.28 um, nf=1 |
| PDK | gf180mcu variant `{pdk.variant}`, open_pdks `{pdk.version}` |
| klayout | `{tool_version('klayout', ['-b', '-v'])}` |
| klt | `{tool_version('klt', ['--version'])}` |
| xschem | `{xschem_version()}` |

## Results

| Stage | Result |
| --- | --- |
| DRC -- `klt drc --deck gf180mcu` | **{klt['status']}**, {klt['violations']} violation(s); layout dbu {klt['dbu_um']} um |
| DRC -- PDK deck ({drc['rule_tables']} rule tables) | **{drc['violations']} violation(s)** across {drc['rule_categories']} rule categories |
| LVS -- PDK `gf180mcu.lvs` vs. xschem export | **{'match' if summary['lvs']['match'] else 'MISMATCH'}** |
{control_rows(summary)}

Schematic netlist: {summary['netlist_devices']} device line(s), exported in
xschem's `lvs_netlist` form from `layout/testcell/{CELL}.sch`.

## What this does and does not establish

- The flow runs end to end: PDK PCell -> GDS -> DRC (two decks) -> LVS against
  a netlist exported from the schematic source, with negative controls proving
  the compare is live in both topology and device parameters.
- It says **nothing** about the LDO. The cell is one transistor; no block-level
  layout exists yet.
- `klt drc`'s deck is a curated subset (see `layout/README.md`, "Coverage,
  honestly"); the PDK deck's {drc['rule_categories']} categories are the number
  worth quoting.
"""
    if warnings:
        body += "\n## LVS deck notes\n\n"
        for warning in warnings:
            body += f"- {warning}\n"
    path.write_text(body)
    return path


def tool_version(tool: str, args: list[str]) -> str:
    try:
        out = subprocess.run([tool, *args], capture_output=True, text=True, timeout=60)
        return (out.stdout + out.stderr).strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run DRC and LVS on the gf180mcu bring-up test cell.",
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
