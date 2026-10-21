"""Turn a bench's ``tb.json`` into a :class:`harness.klt_batch.Job` (issue #467).

The standalone benches declare themselves in ``sim/<slug>/testbench/tb.json``
for the local harness (``runner.compose_deck``): ``analyses`` are raw
``.control`` lines, ``measure`` maps a name to an ngspice expression that the
local deck evaluates as ``let m_<name> = <expr>``, and ``checks`` holds the
graded bounds. ``klt sim`` owns the deck's single ``.control`` block, so a
wrapper that wants the same bench on the batch fleet has to restate all three
in the request's own vocabulary. This module does that once, so a per-bench
``klt_run.py`` is a few lines and the measurements and bounds stay in
``tb.json``:

* the first analysis line becomes ``request.analysis`` (``dc Vsup 2.2 1.75
  -0.005`` -> ``{"kind": "dc", "args": "Vsup 2.2 1.75 -0.005"}``);
* ``meas <type> <name> ...`` lines become ``measurements[].spice`` ``.meas``
  cards;
* every ``measure`` entry becomes a ``measurements[].expr``, with the local
  deck's spelling mapped onto what ``klt`` evaluates: ``m_<name>`` references
  to another measurement become the bare ``<name>`` (``klt`` writes ``let
  <name> = <expr>``, not ``let m_<name>``), and a plot-qualified vector
  (``op1.v(x)``, ``ac1.ph_ugbw``) loses its ``<kind>1.`` qualifier when the
  request's single analysis is that kind;
* the circuit body is the bench's stimulus fragment plus the harness-owned
  preamble ``compose_deck`` would have written (``design.ngspice`` params,
  ``wnflag``, manifest ``options``/``nodeset``, ``.param vdd_val``, the DUT
  ``.include``), minus the PDK ``.lib`` lines and ``.temp``, which ``klt``
  derives from the corner axes.

A bench that chains several analyses in ``.control`` (an ``op`` then an ``ac``)
cannot be one ``klt`` request, which runs one analysis per corner. :func:`states`
splits it into one request per analysis -- ``op1``, ``ac1``, ``ac2`` in the
order the deck runs them -- and assigns each ``measure`` entry to the state
whose plot it reads (``ac1.x`` and ``meas ac`` card results to ``ac1``; a vector
read with no qualifier to the LAST analysis, which is the plot ngspice leaves
current); :func:`jobs` is the multi-state counterpart of :func:`job`. The
single-analysis path (:func:`job`) is unchanged.

What it deliberately does not do: a ``measure`` entry that reads two different
plots, or qualifies a vector by a plot its state does not produce, raises
:class:`UnsupportedTb` naming the entry, rather than running something
different from the local deck.

Nothing here decides pass/fail beyond :func:`grade`, which applies the
manifest's own ``checks`` bounds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import klt_batch as kb
from . import testbench as tbmod

#: The nine-process axis the standalone PVT benches record over (the seven
#: LDO processes plus the two bipolar corners, which are no-ops for a design
#: with no BJT -- kept so a grid is point-for-point comparable to the
#: ``run_corners.py`` records).
FULL_PROCESS = kb.LDO_PROCESS + ("bjt_ff", "bjt_ss")

#: ngspice prints this many digits for a ``print``ed scalar / ``.meas`` value,
#: matching ``set numdgt=10`` in the local deck.
DIGITS = 10

_ANALYSIS_KINDS = ("op", "dc", "ac", "tran", "noise", "tf", "sens", "pz", "disto")
_M_REF = re.compile(r"\bm_([A-Za-z0-9_]+)")
_PLOT_REF = re.compile(r"\b(op|dc|ac|tran|noise|tf|sens|pz|disto)(\d+)\.", re.IGNORECASE)


_IDENT = re.compile(r"(?<![\w.])[A-Za-z_]\w*(?!\w*\()")
_VECTOR_READ = re.compile(r"\b[vi]\(", re.IGNORECASE)
#: a plot-qualified read, ``ac1.ph_ugbw`` or ``op1.v(x1.tail)``
_QUALIFIED = re.compile(r"\b(?:op|dc|ac|tran|noise|tf|sens|pz|disto)\d+\.\w+(?:\([^()]*\))?", re.IGNORECASE)


class UnsupportedTb(ValueError):
    """The manifest asks for something the single-analysis request cannot say."""


def split_analyses(analyses) -> tuple[dict, list[dict]]:
    """``tb.analyses`` -> (``request.analysis``, [``.meas`` measurement specs])."""
    analysis: dict | None = None
    cards: list[dict] = []
    for line in (a.strip() for a in analyses):
        if not line:
            continue
        head, _, rest = line.partition(" ")
        word = head.lower()
        if word in ("meas", "measure"):
            fields = rest.split()
            if len(fields) < 2:
                raise UnsupportedTb(f"malformed meas line: {line!r}")
            cards.append({"name": fields[1], "spice": f".meas {rest.strip()}"})
        elif word in _ANALYSIS_KINDS:
            if analysis is not None:
                raise UnsupportedTb(
                    f"second analysis line {line!r} after {analysis['kind']!r}: this adapter "
                    "maps a bench with ONE analysis; a chained op/ac bench needs "
                    "request.analysis_steps"
                )
            analysis = {"kind": word, "args": rest.strip()}
        else:
            raise UnsupportedTb(f"unsupported analysis line {line!r}")
    if analysis is None:
        raise UnsupportedTb("no analysis line in 'analyses'")
    return analysis, cards


def map_expr(expr: str, kind: str, measure_names, n: int = 1) -> str:
    """The local ``let m_<name> = <expr>`` spelling -> what ``klt`` evaluates.

    ``<kind><n>.`` is the request's own plot (``n`` is the 1-based index of
    that analysis kind in the deck) and is dropped; any other plot qualifier
    is refused.
    """
    names = set(measure_names)

    def m_ref(m: re.Match) -> str:
        return m.group(1) if m.group(1) in names else m.group(0)

    def plot_ref(m: re.Match) -> str:
        if m.group(1).lower() == kind and int(m.group(2)) == n:
            return ""
        raise UnsupportedTb(
            f"expression {expr!r} reads plot {m.group(0)!r}, which the {kind}{n} "
            "request does not produce"
        )

    return _PLOT_REF.sub(plot_ref, _M_REF.sub(m_ref, expr))


def param_expr(expr: str) -> str:
    """``expr`` spelled for a ``.meas ... param='<expr>'`` card.

    A ``.meas`` param is evaluated by ngspice's parameter parser, which has no
    ``db()``: the card errors out and reports no value. ``db(x)`` becomes
    ``(20*log10(abs(x)))``, which is what the control-language ``db`` computes.
    """
    for m in reversed(list(re.finditer(r"\bdb\(", expr))):
        depth, i = 1, m.end()
        while i < len(expr) and depth:
            depth += {"(": 1, ")": -1}.get(expr[i], 0)
            i += 1
        if depth:
            raise UnsupportedTb(f"unbalanced parentheses in {expr!r}")
        expr = f"{expr[:m.start()]}(20*log10(abs({expr[m.end():i - 1]}))){expr[i:]}"
    return expr


def measurements(tb: tbmod.Testbench) -> tuple[dict, list[dict]]:
    """(``request.analysis``, ``request.measurements``) for ``tb``.

    A ``meas`` card's result is a scalar ngspice prints, not a vector a later
    ``let`` can read, so a ``measure`` entry built from card results (``(vin_knee_v
    - 1.764)*1e3``) is emitted as a ``.meas <kind> <name> param='<expr>'`` card,
    which does see them. An entry that mixes card results with vector reads
    (``v(...)``/``i(...)``) has no single-request spelling and is refused.
    """
    analysis, cards = split_analyses(tb.analyses)
    kind = analysis["kind"]
    specs = list(cards)
    scalars = {c["name"] for c in cards}
    for name, expr in tb.measure.items():
        mapped = map_expr(expr, kind, tb.measure)
        if scalars & set(_IDENT.findall(mapped)):
            if _VECTOR_READ.search(mapped):
                raise UnsupportedTb(
                    f"measure {name!r} = {expr!r} mixes .meas results with vector reads"
                )
            specs.append({"name": name, "spice": f".meas {kind} {name} param='{param_expr(mapped)}'"})
            scalars.add(name)
        else:
            specs.append({"name": name, "expr": mapped})
    return analysis, specs


@dataclass
class State:
    """One analysis of a chained ``.control`` block, as its own ``klt sim`` request."""

    kind: str
    n: int                     # 1-based index among analyses of this kind: ac2 is the 2nd ``ac``
    analysis: dict
    cards: list = field(default_factory=list)
    specs: list = field(default_factory=list)
    names: list = field(default_factory=list)   # ``measure`` entries this state computes

    @property
    def name(self) -> str:
        return f"{self.kind}{self.n}"


def _split_states(analyses) -> tuple[list[State], list[str]]:
    """``tb.analyses`` -> ([State], ngspice ``set`` lines) in deck order."""
    out: list[State] = []
    counts: dict[str, int] = {}
    init: list[str] = []
    for line in (a.strip() for a in analyses):
        if not line:
            continue
        head, _, rest = line.partition(" ")
        word = head.lower()
        if word == "set":
            init.append(line)
        elif word in _ANALYSIS_KINDS:
            counts[word] = counts.get(word, 0) + 1
            out.append(State(word, counts[word], {"kind": word, "args": rest.strip()}))
        elif word in ("meas", "measure"):
            fields = rest.split()
            if len(fields) < 2:
                raise UnsupportedTb(f"malformed meas line: {line!r}")
            owner = [s for s in out if s.kind == fields[0].lower()]
            if not owner:
                raise UnsupportedTb(f"meas line {line!r} precedes any {fields[0]!r} analysis")
            owner[-1].cards.append({"name": fields[1], "spice": f".meas {rest.strip()}"})
        else:
            raise UnsupportedTb(f"unsupported analysis line {line!r}")
    if not out:
        raise UnsupportedTb("no analysis line in 'analyses'")
    return out, init


def states(tb: tbmod.Testbench) -> tuple[list[State], list[str]]:
    """Split ``tb`` into one :class:`State` per analysis, with measurements assigned.

    A ``measure`` entry belongs to the state whose plot it reads: ``<kind><n>.``
    qualifiers and ``meas`` card results name it explicitly; a vector read with
    no qualifier is the deck's current plot, i.e. the LAST analysis; an entry
    built only from other ``measure`` entries follows them. Reading two states
    in one entry has no single-request spelling and is refused. A state left
    with nothing to measure (a trailing ``ac lin 1 1k 1k`` whose only job in
    the local deck was to set the current plot) is dropped.

    Returns (non-empty states, ``set`` lines for ``options.ngspice_init``).
    """
    sts, init = _split_states(tb.analyses)
    card_state = {c["name"]: s for s in sts for c in s.cards}
    by_plot = {(s.kind, s.n): s for s in sts}
    owner: dict[str, State] = {}

    def resolve(name: str, seen=()) -> State:
        if name in owner:
            return owner[name]
        if name in seen:
            raise UnsupportedTb(f"measure {name!r} depends on itself")
        expr = tb.measure[name]
        found: set[int] = set()
        for kind, n in _PLOT_REF.findall(expr):
            s = by_plot.get((kind.lower(), int(n)))
            if s is None:
                raise UnsupportedTb(f"measure {name!r} = {expr!r} reads plot {kind}{n}, which the deck never runs")
            found.add(sts.index(s))
        found |= {sts.index(card_state[i]) for i in _IDENT.findall(expr) if i in card_state}
        found |= {sts.index(resolve(m, seen + (name,))) for m in _M_REF.findall(expr) if m in tb.measure}
        if _VECTOR_READ.search(_QUALIFIED.sub("", expr)):
            found.add(len(sts) - 1)
        if len(found) > 1:
            raise UnsupportedTb(
                f"measure {name!r} = {expr!r} reads {sorted(sts[i].name for i in found)}: a "
                "klt request has one analysis, so an entry must read one"
            )
        owner[name] = sts[found.pop()] if found else sts[-1]
        return owner[name]

    for name in tb.measure:
        resolve(name).names.append(name)
    for s in sts:
        kind = s.kind
        scalars = {c["name"] for c in s.cards}
        s.specs = list(s.cards)
        for name in s.names:
            mapped = map_expr(tb.measure[name], kind, tb.measure, s.n)
            if mapped == name and name in scalars:
                continue                      # `a0_db: ac1.a0_db`: the card already is the measurement
            if name in scalars:
                raise UnsupportedTb(f"measure {name!r} reuses the name of a .meas card in {s.name}")
            if scalars & set(_IDENT.findall(mapped)):
                if _VECTOR_READ.search(mapped):
                    raise UnsupportedTb(
                        f"measure {name!r} = {tb.measure[name]!r} mixes .meas results with vector reads"
                    )
                s.specs.append({"name": name, "spice": f".meas {kind} {name} param='{param_expr(mapped)}'"})
                scalars.add(name)
            else:
                s.specs.append({"name": name, "expr": mapped})
    return [s for s in sts if s.names], init


def body(tb: tbmod.Testbench) -> str:
    """Circuit body: the harness-owned preamble, the DUT include, the stimulus."""
    lines = [
        f"* {tb.name} -- klt sim circuit body, GENERATED by sim/harness/tb_adapter.py",
        f".param vdd_nom={tb.nominal_supply_v!r}",
        f".param vdd_val={tb.nominal_supply_v!r}",
    ]
    lines += [f".param {k}={v}" for k, v in tb.params.items()]
    lines += [kb.DESIGN_PARAMS, kb.WNFLAG]
    lines += [f".options {o}" for o in tb.options]
    if tb.nodeset:
        lines.append(".nodeset " + " ".join(f"v({n})={v}" for n, v in tb.nodeset.items()))
    lines += ['.include "dut.spice"', "", tb.netlist.read_text()]
    return "\n".join(lines)


def job(tb: tbmod.Testbench, name: str, dut: Path, only: str | None = None,
        process=FULL_PROCESS, supply_key: str = "vsup") -> kb.Job:
    """The :class:`klt_batch.Job` that runs ``tb`` on ``dut`` over its PVT grid."""
    from .corners import supply_points

    analysis, specs = measurements(tb)
    axes = {
        "process": tuple(process),
        "temps": tuple(tb.temperatures_c),
        "supplies": tuple(supply_points(tb.nominal_supply_v, tb.supply_tolerance)),
        **kb.only_axes(only),
    }
    return kb.Job(name=name, body=body(tb), dut_netlist=dut, analysis=analysis,
                  measurements=specs, supply_key=supply_key, stage_model_inputs=True,
                  ngspice_init=(f"set numdgt={DIGITS}", f"set measureprec={DIGITS}"), **axes)


def jobs(tb: tbmod.Testbench, tag: str, dut: Path, only: str | None = None,
         supply_param: str = "vdd_val") -> dict[str, kb.Job]:
    """{state name: Job} for a bench whose ``.control`` chains several analyses.

    One request per :func:`states` entry over the bench's own PVT grid
    (``tb.corners`` -> process axis). The supply axis is the ``.param`` the
    fragment reads (``vdd_val``), not an ``alter`` of a source: these fragments
    hang several supplies, and expressions of the supply (``{vdd_val-0.4-vcm}``),
    off one parameter.
    """
    from .corners import resolve_corners, supply_points

    sts, init = states(tb)
    axes = {
        "process": tuple(c.name for c in resolve_corners(tb.corners)),
        "temps": tuple(tb.temperatures_c),
        "supplies": tuple(supply_points(tb.nominal_supply_v, tb.supply_tolerance)),
        **kb.only_axes(only),
    }
    return {s.name: kb.Job(name=f"{s.name}-{tag}", body=body(tb), dut_netlist=dut,
                           analysis=s.analysis, measurements=s.specs, supply_key=supply_param,
                           supply_param=supply_param, stage_model_inputs=True,
                           ngspice_init=(*init, f"set numdgt={DIGITS}", f"set measureprec={DIGITS}"),
                           **axes)
            for s in sts}


def grade(tb: tbmod.Testbench, values: dict) -> bool:
    """Every ``checks`` bound holds; a missing value fails."""
    for key, lim in tb.checks.items():
        x = values.get(key)
        if x is None or ("max" in lim and x > lim["max"]) or ("min" in lim and x < lim["min"]):
            return False
    return True


def main(testbench_dir: Path, doc: str, argv=None) -> int:
    """The whole ``klt_run.py`` for a bench: grid -> fleet -> ``corners/<id>/``."""
    import argparse
    import os

    from . import pdk
    from .klt_ab import add_ab_args, run_ab, write_summary_csv

    repo = Path(__file__).resolve().parents[2]
    tb = tbmod.load(testbench_dir)
    chained = len(_split_states(tb.analyses)[0]) > 1
    ap = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_ab_args(ap, repo)
    # A bench with no `dut_netlist` of its own (an amplifier cell bench) runs its
    # first design include; `--dut` re-points it.
    if len(tb.design_netlists) > 1:
        raise UnsupportedTb(f"{tb.name}: several design netlists; the request body includes one DUT")
    default_dut = tb.design_netlists[0] if tb.design_netlists else repo / "design/netlist/ldo_core.spice"
    dut_rel = tb.dut_netlist_rel or str(default_dut.relative_to(repo))
    ap.set_defaults(dut=str(default_dut))
    args = ap.parse_args(argv)
    # Pin klt's PDK search to the harness-resolved, pin-checked tree: with two
    # installs of the variant on the host klt otherwise takes the first match,
    # and the client-side stamp it compares the worker's against is unavailable.
    os.environ.setdefault("PDK_ROOT", str(pdk.find_pdk().path.parent))
    dest = tb.experiment_dir / "corners" / args.record_id
    if not chained:
        results = run_ab(lambda n, d: job(tb, n, d, args.only), Path(args.dut), args.baseline_ref,
                         dest, repo, backend=args.backend)
    else:
        results = _run_states(tb, args, dest, repo, dut_rel)
    rows = []
    for tag, vals in results.items():
        for cid, v in sorted(vals.items()):
            rows.append({"dut": tag, "corner": cid, **{k: v[k] for k in v if not k.startswith("_")},
                         "status": v.get("_status"), "diagnostics": v.get("_diagnostics"),
                         "pass": grade(tb, v)})
    write_summary_csv(rows, dest / "summary.csv")
    return 0


def _run_states(tb, args, dest: Path, repo: Path, dut_rel: str) -> dict[str, dict]:
    """Run each analysis state as its own request; merge the values per corner.

    Raw reports and logs land in ``dest/klt-<state>/<new|baseline>/``. Off-host
    the states are submitted at once; a single-point or local run goes one at a
    time, never a local fan-out.
    """
    from concurrent.futures import ThreadPoolExecutor

    from .klt_ab import run_ab

    names = list(jobs(tb, "probe", Path(args.dut), args.only))

    def go(state):
        return state, run_ab(lambda n, d: jobs(tb, n, d, args.only)[state], Path(args.dut),
                             args.baseline_ref, dest / f"klt-{state}", repo,
                             backend=args.backend, dut_rel=dut_rel)

    workers = 1 if (args.only or args.backend == "local") else len(names)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        per_state = dict(pool.map(go, names))
    merged: dict[str, dict] = {}
    for state, by_tag in per_state.items():
        for tag, vals in by_tag.items():
            for cid, v in vals.items():
                m = merged.setdefault(tag, {}).setdefault(cid, {"_status": "pass", "_diagnostics": ""})
                m.update({k: x for k, x in v.items() if not k.startswith("_")})
                if v.get("_status") != "pass":
                    m["_status"] = f"{state}:{v.get('_status')}"
                if v.get("_diagnostics"):
                    m["_diagnostics"] = ";".join(filter(None, [m["_diagnostics"], f"{state}:{v['_diagnostics']}"]))
    return merged
