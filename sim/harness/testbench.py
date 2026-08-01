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
    #: LDO-specific extension to sim/README.md's evidence record (a bandgap
    #: has no load pin and does not need this): load current / output cap
    #: / enable state, or any other operating-point property this claim
    #: depends on. Rendered verbatim as the record's **Operating
    #: conditions** field. Required whenever the claim is load- or
    #: output-network-dependent; omit (leave empty) only for claims that
    #: are provably load-independent, and say so via
    #: ``operating_conditions={"note": "N/A -- <why>"}``.
    operating_conditions: dict[str, str] = field(default_factory=dict)

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

    def include_provenance(self, repo_root: Path | None = None) -> list[dict]:
        """Path + sha256 of every design netlist this testbench includes."""
        entries = []
        for path in self.includes:
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
        operating_conditions={
            str(k): str(v) for k, v in manifest.get("operating_conditions", {}).items()
        },
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
    room temperature. Design netlists named in ``includes`` are held to the
    same rule: an xschem export that still carries a trailing ``.end`` would
    truncate the deck at the point it is included.
    """
    problems = _forbidden_directives(tb.netlist)
    if problems:
        raise ValueError(
            f"{tb.netlist}: netlist fragments must not contain "
            f"{', '.join(FORBIDDEN_DIRECTIVES)} -- the harness supplies the models, "
            "corner libs, temperature and control block:\n" + "\n".join(problems)
        )
    for include in tb.includes:
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
