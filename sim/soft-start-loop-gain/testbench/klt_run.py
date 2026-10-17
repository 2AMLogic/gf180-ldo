"""Soft-start loop-gain bench through ``klt sim`` (issue #451).

Library for ``sweep.py --backend batch`` / ``--backend klt-local``. ``sweep.py``
keeps the grid, the landing rule, the DC-seed retry, the record and the report,
and parses what this module writes with its own ``ROW`` / ``HOV`` parsers, so
``compare_records.py`` and the summarisers see the same record as a local run.
This follows ``sim/loop-stability/testbench/klt_run.py`` (issue #366), whose
Tian metric table, analysis passes and report parsing it reuses.

The bench has two decks of different shapes:

**Margin deck** (``tb_ss_loop_gain.spice.in``): ``foreach`` ramp state x C_eff x
ESR with ``alter`` and a chain of ``op`` / ``ac`` / ``alter`` / ``ac``. Here each
(variant, phase, C_eff, ESR) is one request over the PVT grid
(``klt_body.spice.in``); the ramp state is a ``corners.params`` row (``vssr``,
zipped with the supply ``vsup``) rather than ``alter Vssr``; the two injection
ACs are ``analysis.passes`` and the margins are the same seven ``tian`` metrics
as loop-stability. The DC landing quantities (``ssr_v``, ``fb_v``, ``vout_v``,
``isup_a``) are ``expr`` measurements taken at the ``op`` before any alter.

**DC hand-over deck** (``tb_ss_handover.spice.in``): ``op``-only, no AC, so no
``tian`` analogue. It is a plain ``analysis.kind: "op"`` request per variant
(``klt_body_handover.spice.in``) with V(SSR) and the supply as zipped
``corners.params`` rows, and the ``HOV`` fields are ``expr`` measurements.

What is NOT identical to the local decks, so a batch record is a different
extraction of the same circuit rather than the same numbers (see
loop-stability's ``klt_run.py`` for the measured size of each):

* crossings are located by ``klt``'s log-frequency interpolation between AC
  samples; the deck's ``meas ... when`` interpolates linearly in frequency;
* the supply and V(SSR) are ``.param`` axes, not ``alter`` of their sources;
* the unwrapped phase and the first-valid-sample DC-gain proxy are ``klt``'s;
* the regulating-branch retry re-runs a whole (corner, variant, phase) deck as a
  single-corner request per (C_eff, ESR) with the seed in the body, as the local
  path re-runs the whole deck.

Quantities ``tian`` cannot grade: none in the margin deck (all seven margin
fields map onto a ``tian`` metric, an unavailable crossing is an empty field as
in the local deck). Not run through ``klt sim`` and still local, single-corner:
the attribution / feedback-capacitance-ladder runs and the full T(f) curve
re-runs, which need the printed vectors rather than scalar metrics.

A failed submit raises; this module never falls back to a local grid.
``backend="local"`` is only for a one-corner debug run and runs one request at
a time.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import klt_batch as kb  # noqa: E402

# loop-stability's klt_run is a sibling bench's module of the same file name, so
# it is loaded by path under its own name rather than imported (sweep.py does
# the same for loop-stability's sweep.py).
_LSK_PATH = REPO / "sim" / "loop-stability" / "testbench" / "klt_run.py"
_spec = importlib.util.spec_from_file_location("loop_stability_klt_run", _LSK_PATH)
lsk = importlib.util.module_from_spec(_spec)
sys.modules["loop_stability_klt_run"] = lsk
_spec.loader.exec_module(lsk)

SUPPLY_PARAM = lsk.SUPPLY_PARAM
SSR_PARAM = "vssr"

#: ROW field -> expr measured at the operating point before any alter.
_DC_EXPRS = (
    ("ssr_v", "v(ssrpin)"),
    ("fb_v", "v(xdut.fb)"),
    ("vout_v", "v(vout)"),
    ("isup_a", "-i(vin)"),
)
#: HOV field -> expr.
_HOV_EXPRS = (
    ("ssr_v", "v(ssrpin)"),
    ("fb_v", "v(xdut.fb)"),
    ("vout_v", "v(vout)"),
    ("pg_v", "v(binj)"),
    ("erramp_v", "v(ainj)"),
    ("isup_a", "-i(vin)"),
)
ROW_METRICS = tuple(m[0] for m in lsk.METRICS)

_num = lsk._num


def _g(v: float) -> str:
    """A ramp state as the local decks print it (``foreach ss <v:g ...>``)."""
    return f"{float(v):g}"


@dataclass
class SSJob(kb.Job):
    """``kb.Job`` whose ``corners.params`` zips the supply with V(SSR).

    ``kb.Job`` has one supply ``.param`` axis; the ramp state is a second
    ``.param`` of the same request, so every (supply, V(SSR)) pair is a row.
    """

    ssr_values: tuple = ()

    def request(self) -> dict:
        req = super().request()
        if self.ssr_values:
            rows = [(s, v) for v in self.ssr_values for s in self.supplies]
            req["corners"]["params"] = {
                self.supply_param: [s for s, _ in rows],
                SSR_PARAM: [float(v) for _, v in rows],
            }
        return req


def _fill(template: str, subs: dict) -> str:
    text = (HERE / template).read_text()
    for tok, val in subs.items():
        text = text.replace(f"@{tok}@", val)
    assert not re.search(r"@[A-Z_]+@", text), "unsubstituted token"
    return "\n".join([kb.DESIGN_PARAMS, kb.WNFLAG, text])


def margin_body(spec: dict, ceff: float, esr: float, dc_seed: str = "") -> str:
    pinned = spec["ssr"] is not None
    return _fill("klt_body.spice.in", {
        "ILOAD": _num(spec["iload_a"]), "RLOAD": _num(spec["rload_ohm"]),
        "CEFF": _num(ceff), "ESR": _num(esr), "DC_SEED": dc_seed,
        "SSR_SOURCE": (f"Vssr SSRPIN 0 DC {{{SSR_PARAM}}}" if pinned else
                       "* SSR is NOT pinned in this phase: SSRPIN is left unconnected."),
    })


def margin_measurements() -> list:
    # lsk's list carries `vout_v` (and the seven tian metrics); the other
    # landing quantities are added here.
    out = [m for m in lsk.measurements() if m["name"] != "vout_v"]
    return [{"name": n, "expr": e} for n, e in _DC_EXPRS] + out


def margin_job(name: str, spec: dict, ceff: float, esr: float, dut: Path, ac_dec: int,
               f_start: str, f_stop: str, axes: dict, dc_seed: str = "") -> SSJob:
    return SSJob(name=name, body=margin_body(spec, ceff, esr, dc_seed), dut_netlist=dut,
                 analysis=lsk.analysis(ac_dec, f_start, f_stop),
                 measurements=margin_measurements(), timeout_s=900,
                 supply_param=SUPPLY_PARAM,
                 ssr_values=tuple(spec["ssr"]) if spec["ssr"] is not None else (), **axes)


def handover_job(name: str, dut: Path, ssr_values, axes: dict) -> SSJob:
    return SSJob(name=name, body=_fill("klt_body_handover.spice.in", {}), dut_netlist=dut,
                 analysis={"kind": "op", "args": ""},
                 measurements=[{"name": n, "expr": e} for n, e in _HOV_EXPRS],
                 timeout_s=900, supply_param=SUPPLY_PARAM,
                 ssr_values=tuple(ssr_values), **axes)


def collect(report: dict) -> tuple[dict, list[tuple[str, str]]]:
    """``({(corner_id, ssr_cmd | None): {field: float | None}}, [(corner_id, problem)])``.

    Margin metrics go through loop-stability's ``collect_values`` (so a metric
    ``klt`` reports unavailable is an empty field and any other non-ok result
    is a problem), once per V(SSR) because several corners share a corner id.
    A hand-over report has no ``tian`` metrics, only ``expr`` values; the same
    function reads it (``gain_at_f180_db``, the one field it negates, is absent).
    """
    by_ssr: dict = {}
    for c in report.get("corners", []):
        p = (c.get("params") or {}).get(SSR_PARAM)
        by_ssr.setdefault(None if p is None else _g(p), []).append(c)
    values: dict = {}
    problems: list[tuple[str, str]] = []
    for ssr, corners in by_ssr.items():
        vals, probs = lsk.collect_values({"corners": corners}, SUPPLY_PARAM)
        problems += probs
        for cid, fields in vals.items():
            values[(cid, ssr)] = fields
    return values, problems


def _fmt(f: dict, k: str) -> str:
    v = f.get(k)
    return "" if v is None else f"{v:.9e}"


def row_line(ssr_cmd: str, ceff: float, esr: float, f: dict) -> str:
    """One ``ROW`` line in ``tb_ss_loop_gain.spice.in``'s field layout."""
    head = " ".join(f"{k}={_fmt(f, k)}" for k, _ in _DC_EXPRS)
    return (f"ROW ssr_cmd={ssr_cmd} " + head + f" ceff_f={_num(ceff)} esr_ohm={_num(esr)} "
            + " ".join(f"{n}={_fmt(f, n)}" for n in ROW_METRICS))


def hov_line(ssr_cmd: str, f: dict) -> str:
    """One ``HOV`` line in ``tb_ss_handover.spice.in``'s field layout."""
    return f"HOV ssr_cmd={ssr_cmd} " + " ".join(f"{k}={_fmt(f, k)}" for k, _ in _HOV_EXPRS)


def margin_log(cid: str, variant: str, phase: str, spec: dict, ceffs, esrs, results: dict) -> str:
    """Per-(corner, variant, phase) log: ``ROW`` lines, ramp state outermost as in the deck."""
    ssrs = [None] if spec["ssr"] is None else [_g(v) for v in spec["ssr"]]
    lines = [f"* corner_id={cid} variant={variant} phase={phase} (klt sim; see klt-reports/)"]
    for ssr in ssrs:
        for ce in ceffs:
            for es in esrs:
                f = results.get((variant, phase, ce, es), {}).get((cid, ssr))
                if f is not None:
                    lines.append(row_line("free" if ssr is None else ssr, ce, es, f))
    lines.append(f"* SWEEP COMPLETE {cid}")
    return "\n".join(lines) + "\n"


def handover_log(cid: str, ssr_values, results: dict) -> str:
    lines = [f"* corner_id={cid} (klt sim; see klt-reports/)"]
    for v in ssr_values:
        f = results.get((cid, _g(v)))
        if f is not None:
            lines.append(hov_line(_g(v), f))
    lines.append(f"* SWEEP COMPLETE {cid}")
    return "\n".join(lines) + "\n"


def _submit(jobs, outdir: Path, backend: str | None, in_flight: int, log=print):
    """Run ``[(key, Job)]``; ``({key: {(cid, ssr): fields}}, problems, bad-keys)``."""
    results: dict = {}
    problems: list[str] = []
    bad: set = set()

    def go(item):
        key, j = item
        with tempfile.TemporaryDirectory(prefix="klt-ss-") as tmp:
            req = kb.stage(j, Path(tmp) / j.name)
            report = kb.run(req, Path(tmp) / "out", backend=backend, log=log)
            rdir = outdir / "klt-reports"
            rdir.mkdir(parents=True, exist_ok=True)
            (rdir / f"{j.name}.json").write_text(
                json.dumps(kb.redact(report), indent=1, sort_keys=True) + "\n")
        vals, probs = collect(report)
        return key, j.name, vals, probs

    workers = 1 if backend == "local" else max(1, in_flight)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, tag, vals, probs in pool.map(go, jobs):
            results[key] = vals
            problems += [f"[{tag}] {c}: {p}" for c, p in probs]
            if probs:
                bad.add((key, frozenset(c for c, _ in probs)))
    return results, problems, bad


def _tag(variant: str, phase: str, ce: float, es: float, suffix: str) -> str:
    return f"{variant}_{phase}_ce{_num(ce)}_es{_num(es)}{suffix}"


def run_margin(variants, phases: dict, ceffs, esrs, netlists: dict, ac_dec: int,
               f_start: str, f_stop: str, axes: dict, outdir: Path, backend: str | None,
               in_flight: int, dc_seed: str = "", log=print):
    """One request per (variant, phase, C_eff, ESR) over the PVT grid in ``axes``.

    Returns ``({(variant, phase, ceff, esr): {(corner_id, ssr_cmd): fields}},
    problems, corners_with_problems)``; the last is a set of ``(corner_id, variant, phase)``.
    """
    suffix = "_dcseed" if dc_seed else ""
    jobs = [((v, p, ce, es),
             margin_job(_tag(v, p, ce, es, suffix), phases[p], ce, es, netlists[v], ac_dec,
                        f_start, f_stop, axes, dc_seed))
            for v in variants for p in phases for ce in ceffs for es in esrs]
    results, problems, bad = _submit(jobs, outdir, backend, in_flight, log=log)
    bad_corners = {(c, k[0], k[1]) for k, cids in bad for c in cids}
    return results, problems, bad_corners


def run_handover(variants, ssr_values, netlists: dict, axes: dict, outdir: Path,
                 backend: str | None, in_flight: int, log=print):
    """One ``op`` request per variant; ``({variant: {(cid, ssr_cmd): fields}}, problems)``."""
    jobs = [(v, handover_job(f"{v}_handover", netlists[v], ssr_values, axes)) for v in variants]
    results, problems, _ = _submit(jobs, outdir, backend, in_flight, log=log)
    return results, problems


def klt_version() -> str:
    return lsk.klt_version()
