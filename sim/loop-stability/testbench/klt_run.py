"""Loop-stability PVT matrix through ``klt sim`` (issue #366).

Library for ``sweep.py --backend batch`` (the batch front end; ``sweep.py``
keeps the grid, the VOUT check, the record and the report, and parses what this
module writes with its own ``ROW`` parser, so ``compare_records.py`` and the
summarisers see the same record as a local run).

``tb_loop_stability.spice.in`` runs one ngspice per PVT point and sweeps load x
C_eff x ESR inside it (``foreach`` + ``alter``), chaining ``op`` / ``ac`` /
``alter`` / ``ac`` and a dozen ``meas`` lines. ``klt sim`` owns the single
``.control`` block, so here:

* each (load, C_eff, ESR) configuration is its own request over the whole PVT
  grid (``klt_body.spice.in`` is the shared circuit with the three values baked
  in: 72 requests of 63 corners);
* the two injection ACs are ``analysis.passes`` (``Vinj`` / ``Iinj`` altered
  per pass) and ``tian.series_injection`` forms ``T = (Tv*Ti - 1)/(Tv + Ti + 2)``
  from them (klayout-tools#2847, #3737, #3771);
* the deck's ``meas`` lines become ``tian`` metrics of the same ``T``::

      dcgain_db        low_frequency_gain_db        (tdb at the first sample, F_START)
      f0_hz            unity_crossing_hz            (first falling 0 dB crossing)
      phase_at_f0_deg  phase_at_unity_deg
      f180_hz          phase_crossover_hz           (first falling -180 deg crossing)
      gain_at_f180_db  -gain_margin_db
      f0_rising_hz     rising_unity_crossing_hz
      resurgence_db    peak_above_crossover_db, from_ratio=1.05 (max tdb over [1.05*f0, F_STOP])
      vout_v           expr v(vout)                 (the DC operating point before any alter)

  A metric ``klt`` reports unavailable (``tian_metric_unavailable``: no such
  crossing in band) is written as an empty field, exactly as a failed ``meas``
  is in the local deck; any other error code is a problem and is reported.

What is NOT identical to the local deck, so a batch record is a different
extraction of the same circuit rather than the same numbers:

* crossings are located by ``klt``'s log-frequency interpolation between AC
  samples; the deck's ``meas ... when`` interpolates linearly in frequency. At
  ``dec 400`` the difference is a fraction of a sample spacing. Measured over
  36 points (tt/27C, ss/-40C, ff/125C at 3.3 V; 3 loads x 2 caps x 2 ESRs) the
  two agree to <1e-3 relative / 0.05 deg / 0.05 dB with identical PASS/FAIL
  verdicts and failing counts;
* the supply is a ``.param`` axis (``corners.params``), not ``corners.supply_v``:
  ``alter vin``/``alter ven`` moved the crossover ~3 % at one point (see
  ``klt_body.spice.in``);
* ``unwrapped phase`` and the first-valid-sample DC-gain proxy are ``klt``'s
  (the deck uses ``cph`` and ``find tdb at=F_START``, the same sample);
* ``op`` and the two ACs are each a cold start in both; the batch ``vout_v`` is
  klt's pre-alter ``op``, as the deck's ``op`` is. The regulating-branch retry
  (``sweep.py``'s ``dc_seed_lines()``) re-runs the whole failing corner, one
  single-corner request per configuration, with the seed in the body.

Live status: the batch fleet's runner image predates ``dual_injection``
(a 3-corner request failed on the fleet with ``batch_job_failed``; see
2AMLogic/klayout-tools#3676), so ``--backend batch`` is not yet verified
end to end. The same requests agree with the local deck through
``--backend klt-local`` (one PVT point), and need a ``klt`` that has the
#3771 metrics (``KLT_CMD='uvx --from git+https://github.com/2AMLogic/klayout-tools.git@1f90efa432de... klt'``;
no release carries them yet -- 0.7.0 is the newest).

A failed submit raises; this module never falls back to a local grid.
``backend="local"`` is only for a one-corner debug run and runs one request at
a time.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import deck  # noqa: E402
from harness import klt_batch as kb  # noqa: E402
from harness.klt_tian import (  # noqa: E402
    METRICS,
    SUPPLY_PARAM,
    analysis,
    collect_values,
    fmt_num,
    klt_version,  # noqa: F401  (re-export: sweep.py calls klt_run.klt_version())
    measurements,
)
# The Tian metric table, the dual-injection analysis passes and the report
# collection above are this file's shared surface: they live in
# ``harness/klt_tian.py`` (issue #630), imported by name here and by
# ``sim/soft-start-loop-gain/testbench/klt_run.py``, which used to load this
# file by filesystem path to reach them.


def body(iload: float, ceff: float, esr: float, dc_seed: str = "") -> str:
    text = deck.render_file(HERE / "klt_body.spice.in", {
        "ILOAD": fmt_num(iload), "CEFF": fmt_num(ceff), "ESR": fmt_num(esr),
        "DC_SEED": dc_seed,
    }, source="klt_body.spice.in")
    return "\n".join([kb.DESIGN_PARAMS, kb.WNFLAG, text])


def job(name: str, cfg: tuple, dut: Path, ac_dec: int, f_start: str, f_stop: str,
        axes: dict, dc_seed: str = "") -> kb.Job:
    # timeout_s=120: issue #465's 2026-11-17 fleet probe measured the whole
    # 63-corner PVT grid at the pinned open_pdks revision on the batch runner
    # (ngspice-47) at mean 1.39 s / max 1.95 s per unit, so 120 s is a >60x
    # margin on the measured worst unit -- and it lets sweep.py's
    # KLT_MAX_UNITS_PER_JOB size itself to floor(3480/120) = 29, i.e. 3 fleet
    # jobs per configuration instead of the 21 (1512 across the grid) the
    # original timeout_s=900 forced. Do not raise this without re-measuring:
    # sweep.py's split is derived from it.
    return kb.Job(name=name, body=body(*cfg, dc_seed=dc_seed), dut_netlist=dut,
                  analysis=analysis(ac_dec, f_start, f_stop), measurements=measurements(),
                  timeout_s=120, supply_param=SUPPLY_PARAM, **axes)


def row_line(cfg: tuple, f: dict) -> str:
    def fmt(k):
        v = f.get(k)
        return "" if v is None else f"{v:.9e}"
    il, ce, es = cfg
    return (f"ROW iload_a={fmt_num(il)} ceff_f={fmt_num(ce)} esr_ohm={fmt_num(es)} vout_v={fmt('vout_v')} "
            + " ".join(f"{n}={fmt(n)}" for n, *_ in METRICS))


def run_configs(configs, dut: Path, ac_dec: int, f_start: str, f_stop: str, axes: dict,
                workdir: Path, outdir: Path, backend: str | None, in_flight: int,
                dc_seed: str = "", log=print) -> tuple[dict, list[str], set[str]]:
    """Submit one request per configuration.

    Returns ``({cfg: {corner_id: fields}}, problems, corners_with_problems)``.

    ``backend="local"`` runs one request at a time. Raw reports go under
    ``outdir/klt-reports/`` (redacted for this public repo), with the request
    JSON next to them so a record's Links point at what was submitted.

    Everything a batch submission needs is staged persistently under
    ``workdir`` (``stage/<tag>/`` request, ``run/<tag>/`` run dir) instead of
    a session-local tempdir, and batch requests are submitted with klt's
    ``--resume``: an interrupted run re-attaches to the retained shard map and
    re-submits only unfinished shards. A configuration whose report is already
    collected -- whose staged identity (request, deck body and DUT bytes,
    issue #796) matches the freshly staged inputs -- is not re-submitted at
    all, so re-invoking ``sweep.py --resume-record <id>`` continues a partial
    grid instead of repeating it (issue #465).
    """
    results: dict = {}
    problems: list[str] = []
    bad: set[str] = set()
    suffix = "_dcseed" if dc_seed else ""
    vals_dir = outdir / "klt-reports"
    vals_dir.mkdir(parents=True, exist_ok=True)

    def go(cfg):
        tag = f"il{fmt_num(cfg[0])}_ce{fmt_num(cfg[1])}_es{fmt_num(cfg[2])}{suffix}"
        j = job(tag, cfg, dut, ac_dec, f_start, f_stop, axes, dc_seed)
        req = kb.stage(j, workdir / "stage" / tag)
        saved = vals_dir / f"{tag}.json"
        req_saved = vals_dir / f"{tag}.request.json"
        ident = vals_dir / f"{tag}.identity.json"
        if saved.is_file() and kb.identity_matches(ident, req):
            vals, probs = collect_values(json.loads(saved.read_text()), SUPPLY_PARAM)
            return cfg, vals, [(tag, c, p) for c, p in probs]
        report = kb.run(req, workdir / "run" / tag, backend=backend, log=log,
                        resume=backend == "batch")
        # Payload first, identity markers last: each sidecar vouches for the
        # report beside it, so it may only exist once that report is fully
        # written. Marker-first would let a crash between the two writes
        # leave a new marker beside an OLD report from a different circuit,
        # and the guard above would trust it (issue #465, PR #745 review 3).
        saved.write_text(
            json.dumps(kb.redact(report), indent=1, sort_keys=True) + "\n")
        req_saved.write_bytes(req.read_bytes())
        kb.publish_identity(ident, req)
        vals, probs = collect_values(report, SUPPLY_PARAM)
        return cfg, vals, [(tag, c, p) for c, p in probs]

    workers = 1 if backend == "local" else max(1, in_flight)
    workdir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for cfg, vals, probs in pool.map(go, list(configs)):
            results[cfg] = vals
            problems += [f"[{tag}] {c}: {p}" for tag, c, p in probs]
            bad |= {c for _tag, c, _p in probs}
    return results, problems, bad


def corner_log(cid: str, configs, results: dict, header: str = "") -> str:
    """The per-corner log text: ``ROW`` lines in the local deck's field layout."""
    lines = [f"* corner_id={cid} (klt sim; see klt-reports/)", header] if header else [f"* corner_id={cid} (klt sim; see klt-reports/)"]
    for cfg in configs:
        f = results.get(cfg, {}).get(cid)
        if f is not None:
            lines.append(row_line(cfg, f))
    lines.append(f"* SWEEP COMPLETE {cid}")
    return "\n".join(lines) + "\n"


