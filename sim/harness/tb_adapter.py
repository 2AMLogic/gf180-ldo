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

What it deliberately does not do: a bench that chains several analyses in
``.control`` (an ``op`` then an ``ac``) or qualifies a vector by a plot the
single analysis does not produce raises :class:`UnsupportedTb` naming the
line, rather than running something different from the local deck.

Nothing here decides pass/fail beyond :func:`grade`, which applies the
manifest's own ``checks`` bounds.
"""

from __future__ import annotations

import re
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


def map_expr(expr: str, kind: str, measure_names) -> str:
    """The local ``let m_<name> = <expr>`` spelling -> what ``klt`` evaluates."""
    names = set(measure_names)

    def m_ref(m: re.Match) -> str:
        return m.group(1) if m.group(1) in names else m.group(0)

    def plot_ref(m: re.Match) -> str:
        if m.group(1).lower() == kind and m.group(2) == "1":
            return ""
        raise UnsupportedTb(
            f"expression {expr!r} reads plot {m.group(0)!r}, which a single {kind!r} "
            "analysis does not produce"
        )

    return _PLOT_REF.sub(plot_ref, _M_REF.sub(m_ref, expr))


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
            specs.append({"name": name, "spice": f".meas {kind} {name} param='{mapped}'"})
            scalars.add(name)
        else:
            specs.append({"name": name, "expr": mapped})
    return analysis, specs


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
                  measurements=specs, supply_key=supply_key,
                  ngspice_init=(f"set numdgt={DIGITS}", f"set measureprec={DIGITS}"), **axes)


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

    from .klt_ab import add_ab_args, run_ab, write_summary_csv

    repo = Path(__file__).resolve().parents[2]
    tb = tbmod.load(testbench_dir)
    ap = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_ab_args(ap, repo)
    args = ap.parse_args(argv)
    dest = tb.experiment_dir / "corners" / args.record_id
    results = run_ab(lambda n, d: job(tb, n, d, args.only), Path(args.dut), args.baseline_ref,
                     dest, repo, backend=args.backend)
    rows = []
    for tag, vals in results.items():
        for cid, v in sorted(vals.items()):
            rows.append({"dut": tag, "corner": cid, **{k: v[k] for k in v if not k.startswith("_")},
                         "status": v.get("_status"), "diagnostics": v.get("_diagnostics"),
                         "pass": grade(tb, v)})
    write_summary_csv(rows, dest / "summary.csv")
    return 0
