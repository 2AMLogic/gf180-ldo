"""Testbench manifests.

Testbenches follow the directory convention ratified in ``sim/README.md``:
each experiment gets ``sim/<experiment-slug>/`` and its testbench lives in
that experiment's ``testbench/`` subdirectory:

    sim/<experiment-slug>/testbench/tb.json            the manifest (this module)
    sim/<experiment-slug>/testbench/<something>.spice  a *netlist fragment*

The fragment must NOT contain ``.include`` of models, ``.lib``, ``.temp``,
``.control`` or ``.end``: the harness owns all of those so that one netlist
can be swept across the whole PVT grid without editing. A testbench that
instantiates a design cell declares it in the manifest's ``includes`` list
instead (paths relative to the ``testbench/`` directory), e.g.

    "includes": ["../../../design/error_amp.spice"]

so the ``.include`` directive stays harness-owned, the included file is
validated the same way the fragment is, and both are frozen into the
record's netlist snapshot. The harness hands the fragment these parameters:

    vdd_val   the supply for this PVT point (nominal, +tol or -tol)
    vdd_nom   the nominal supply, for ratio-style measurements
    temp_c    the temperature for this PVT point (also set via .temp)

plus anything in the manifest's ``params`` map.

``dut_netlist`` (#12) sits on top of ``includes`` rather than beside it: it
*designates* which design netlist is the thing under test, e.g.

    "dut_netlist": "design/netlist/ldo_core.spice"

Two things make it worth a field of its own. It is written repo-root-relative
(not testbench-relative), because it is also a CLI knob -- ``--dut-netlist
PATH`` re-points one manifest at a different netlist source, which is how
#16's post-layout re-run swaps in an extracted netlist without forking the
testbench. And the record reports it separately from the supporting design
cells: the **Netlist provenance** field says *schematic* or *extracted*
depending on whether the path lives under ``layout/``.

Everything else about it is the ``includes`` path: the DUT is emitted as one
harness-owned ``.include`` (first, ahead of the other design cells), validated
against FORBIDDEN_DIRECTIVES like any other included netlist, and frozen into
the record's snapshot with its own path+sha256 header. See
``Testbench.design_netlists``, which is the single ordered list the rest of
the harness iterates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .corners import (
    DEFAULT_CORNER_SET,
    DEFAULT_NOMINAL_SUPPLY_V,
    DEFAULT_SUPPLY_TOLERANCE,
    DEFAULT_TEMPERATURES_C,
)
from .pdk import REPO_ROOT

MANIFEST_NAME = "tb.json"

#: Name of the per-experiment subdirectory that holds the testbench, per
#: the directory convention in ``sim/README.md``.
TESTBENCH_DIRNAME = "testbench"

FORBIDDEN_DIRECTIVES = (".control", ".endc", ".end", ".lib", ".temp", ".include")


@dataclass
class Testbench:
    directory: Path
    name: str
    netlist: Path
    #: Design netlists (xschem exports under ``design/``) this testbench
    #: instantiates. The harness emits the ``.include`` lines for these --
    #: the fragment itself never may -- and freezes their contents into the
    #: record's netlist snapshot so a record stays reproducible after the
    #: schematic moves on.
    includes: tuple[Path, ...] = ()
    description: str = ""
    claim: str = ""
    nominal_supply_v: float = DEFAULT_NOMINAL_SUPPLY_V
    supply_tolerance: float = DEFAULT_SUPPLY_TOLERANCE
    temperatures_c: tuple[float, ...] = DEFAULT_TEMPERATURES_C
    corners: tuple[str, ...] = (DEFAULT_CORNER_SET,)
    analyses: tuple[str, ...] = ("op",)
    measure: dict[str, str] = field(default_factory=dict)
    params: dict[str, str | float] = field(default_factory=dict)
    checks: dict[str, dict] = field(default_factory=dict)
    options: tuple[str, ...] = ()
    #: Optional ``.nodeset`` bias hints, e.g. ``{"vout": "1.8", "loop": "1.0"}``
    #: -> rendered as ``.nodeset v(vout)=1.8 v(loop)=1.0``. A closed-loop LDO
    #: driven from an all-zero initial guess has more than one op-point
    #: solution that satisfies KCL/KVL to ngspice's convergence tolerance --
    #: at full load, plain Newton-Raphson can converge "successfully" onto a
    #: non-physical fixed point (e.g. Vout pinned tens of volts below ground)
    #: instead of falling back to gmin/source stepping, because it never
    #: fails to converge in the first place. A nodeset biases the initial
    #: guess into the physical solution's basin of attraction without
    #: constraining the converged answer -- see #40's investigation writeup
    #: (sim/dropout-vs-load/records/ Claim field) for the reproduction.
    nodeset: dict[str, str | float] = field(default_factory=dict)
    #: LDO-specific extension to sim/README.md's evidence record (a bandgap
    #: has no load pin and does not need this): load current / output cap
    #: / enable state, or any other operating-point property this claim
    #: depends on. Rendered verbatim as the record's **Operating
    #: conditions** field. Required whenever the claim is load- or
    #: output-network-dependent; omit (leave empty) only for claims that
    #: are provably load-independent, and say so via
    #: ``operating_conditions={"note": "N/A -- <why>"}``.
    operating_conditions: dict[str, str] = field(default_factory=dict)
    #: LDO-specific extension (#12): which design netlist is the DUT, e.g.
    #: ``design/netlist/ldo_core.spice``, repo-root relative (``includes``
    #: above are testbench-relative). Included exactly like an ``includes``
    #: entry -- see ``design_netlists`` -- but named separately so it can be
    #: re-pointed from the CLI (``--dut-netlist``, for #16's extracted
    #: post-layout netlist) and reported as the record's DUT. ``None`` for
    #: testbenches with no DUT of their own (e.g. smoke-bias, which
    #: instantiates PDK devices directly, or amp-openloop, which drives a
    #: design cell listed under ``includes`` without designating a DUT).
    dut_netlist: Path | None = None
    #: The repo-relative string as given in the manifest (or ``--dut-netlist``),
    #: kept verbatim for the evidence record's Netlist provenance / Links
    #: fields -- schematic vs. extracted is inferred from this path's prefix.
    dut_netlist_rel: str = ""

    @property
    def experiment(self) -> str:
        """The ``<experiment-slug>`` this testbench belongs to.

        ``sim/<experiment-slug>/testbench/tb.json`` -> ``<experiment-slug>``.
        """
        return self.directory.parent.name

    @property
    def experiment_dir(self) -> Path:
        """``sim/<experiment-slug>/`` -- where records/corners/snapshots live."""
        return self.directory.parent

    @property
    def netlist_sha256(self) -> str:
        return hashlib.sha256(self.netlist.read_bytes()).hexdigest()

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256((self.directory / MANIFEST_NAME).read_bytes()).hexdigest()

    @property
    def dut_netlist_sha256(self) -> str | None:
        if self.dut_netlist is None:
            return None
        return hashlib.sha256(self.dut_netlist.read_bytes()).hexdigest()

    @property
    def design_netlists(self) -> tuple[Path, ...]:
        """Every design netlist the harness includes, DUT first.

        ``dut_netlist`` is not a second include mechanism: it is a
        *designation* on top of ``includes`` -- it names which design netlist
        is the thing under test (so the record can say so, and so #16 can
        re-point it at an extracted netlist), and the file it names flows
        through exactly the same pipeline as the ``includes`` entries: one
        harness-owned ``.include`` line, the same forbidden-directive
        validation, the same path+sha256 provenance entry, the same freeze
        into the record's netlist snapshot. Listing the same file in both
        places includes it once.
        """
        ordered: list[Path] = []
        if self.dut_netlist is not None:
            ordered.append(self.dut_netlist)
        for path in self.includes:
            if path not in ordered:
                ordered.append(path)
        return tuple(ordered)

    def include_provenance(self, repo_root: Path | None = None) -> list[dict]:
        """Path + sha256 of every design netlist this testbench includes."""
        entries = []
        for path in self.design_netlists:
            if self.dut_netlist is not None and path == self.dut_netlist and self.dut_netlist_rel:
                # Keep the manifest's verbatim repo-relative spelling: the
                # record's Netlist-provenance field infers schematic vs.
                # extracted from this path's prefix, and render_record matches
                # this entry against the record's `dut_netlist` field.
                shown = self.dut_netlist_rel
            else:
                try:
                    shown = str(path.relative_to(repo_root)) if repo_root else str(path)
                except ValueError:
                    shown = str(path)
            entries.append(
                {"path": shown, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
        return entries

    def provenance(self, repo_root: Path | None = None) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "claim": self.claim,
            "experiment": self.experiment,
            "directory": self.directory.name,
            "netlist": self.netlist.name,
            "netlist_sha256": self.netlist_sha256,
            "manifest_sha256": self.manifest_sha256,
            "includes": self.include_provenance(repo_root),
            "nominal_supply_v": self.nominal_supply_v,
            "supply_tolerance": self.supply_tolerance,
            "dut_netlist": self.dut_netlist_rel or None,
            "dut_netlist_sha256": self.dut_netlist_sha256,
        }


def _require(manifest: dict, key: str, path: Path):
    if key not in manifest:
        raise ValueError(f"{path}: missing required key {key!r}")
    return manifest[key]


def load(directory: str | Path) -> Testbench:
    """Load a testbench manifest into a :class:`Testbench`.

    Accepts the experiment directory (``sim/<slug>/``), its ``testbench/``
    subdirectory, or the ``tb.json`` path itself.
    """
    directory = Path(directory).resolve()
    if directory.is_file() and directory.name == MANIFEST_NAME:
        directory = directory.parent
    if (directory / TESTBENCH_DIRNAME / MANIFEST_NAME).is_file():
        directory = directory / TESTBENCH_DIRNAME
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no {MANIFEST_NAME} in {directory}")

    manifest = json.loads(manifest_path.read_text())

    netlist = directory / _require(manifest, "netlist", manifest_path)
    if not netlist.is_file():
        raise FileNotFoundError(f"{manifest_path}: netlist {netlist} does not exist")

    dut_netlist_rel = str(manifest.get("dut_netlist", "") or "")
    dut_netlist: Path | None = None
    if dut_netlist_rel:
        dut_netlist = (REPO_ROOT / dut_netlist_rel).resolve()
        if not dut_netlist.is_file():
            raise FileNotFoundError(
                f"{manifest_path}: dut_netlist {dut_netlist_rel!r} does not exist "
                f"(resolved to {dut_netlist})"
            )

    measure = dict(_require(manifest, "measure", manifest_path))
    if not measure:
        raise ValueError(f"{manifest_path}: 'measure' must define at least one measurement")
    for key in measure:
        if not key.replace("_", "").isalnum():
            raise ValueError(
                f"{manifest_path}: measurement name {key!r} must be alphanumeric/underscore "
                "(it becomes an ngspice vector name)"
            )

    includes = []
    for entry in manifest.get("includes", []):
        path = (directory / entry).resolve()
        if not path.is_file():
            raise FileNotFoundError(
                f"{manifest_path}: include {entry!r} resolves to {path}, which does not exist"
            )
        includes.append(path)

    tb = Testbench(
        directory=directory,
        name=manifest.get("name", directory.parent.name),
        netlist=netlist,
        includes=tuple(includes),
        description=manifest.get("description", ""),
        claim=manifest.get("claim", ""),
        nominal_supply_v=float(manifest.get("nominal_supply_v", DEFAULT_NOMINAL_SUPPLY_V)),
        supply_tolerance=float(manifest.get("supply_tolerance", DEFAULT_SUPPLY_TOLERANCE)),
        temperatures_c=tuple(
            float(t) for t in manifest.get("temperatures_c", DEFAULT_TEMPERATURES_C)
        ),
        corners=tuple(manifest.get("corners", (DEFAULT_CORNER_SET,))),
        analyses=tuple(manifest.get("analyses", ("op",))),
        measure=measure,
        params={k: v for k, v in manifest.get("params", {}).items()},
        checks=dict(manifest.get("checks", {})),
        options=tuple(manifest.get("options", ())),
        nodeset={str(k): manifest["nodeset"][k] for k in manifest.get("nodeset", {})},
        operating_conditions={
            str(k): str(v) for k, v in manifest.get("operating_conditions", {}).items()
        },
        dut_netlist=dut_netlist,
        dut_netlist_rel=dut_netlist_rel,
    )
    validate_netlist(tb)
    return tb


def _forbidden_directives(path: Path, allow: tuple[str, ...] = ()) -> list[str]:
    problems: list[str] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip().lower()
        if not line.startswith("."):
            continue
        directive = line.split()[0]
        if directive in FORBIDDEN_DIRECTIVES and directive not in allow:
            problems.append(f"  line {lineno}: {raw.strip()}")
    return problems


def validate_netlist(tb: Testbench) -> None:
    """Reject fragments that try to own what the harness owns.

    Catching this here is much friendlier than debugging a duplicated
    ``.end`` or a hardcoded ``.temp 27`` that silently pins every corner to
    room temperature. Design netlists named in ``includes`` (and the one named
    by ``dut_netlist``) are held to the same rule: an xschem export that still
    carries a trailing ``.end`` would truncate the deck at the point it is
    included.
    """
    problems = _forbidden_directives(tb.netlist)
    if problems:
        raise ValueError(
            f"{tb.netlist}: netlist fragments must not contain "
            f"{', '.join(FORBIDDEN_DIRECTIVES)} -- the harness supplies the models, "
            "corner libs, temperature and control block:\n" + "\n".join(problems)
        )
    for include in tb.design_netlists:
        problems = _forbidden_directives(include)
        if problems:
            raise ValueError(
                f"{include}: an included design netlist must not contain "
                f"{', '.join(FORBIDDEN_DIRECTIVES)} either -- it is pasted into a deck "
                "the harness owns (export it with xschem's top_is_subckt, which emits a "
                "bare .subckt/.ends pair):\n" + "\n".join(problems)
            )


def discover(root: str | Path) -> list[Path]:
    """Every experiment directory under ``root`` that owns a testbench.

    Looks for ``<root>/<experiment-slug>/testbench/tb.json`` and returns the
    ``<experiment-slug>`` directories, sorted.
    """
    root = Path(root)
    return sorted(
        p.parent.parent for p in root.glob(f"*/{TESTBENCH_DIRNAME}/{MANIFEST_NAME}")
    )
