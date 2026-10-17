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
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "sim"))
from harness import klt_batch as kb  # noqa: E402

#: ROW field -> (kind, klt metric, extra tian keys). Order is the ROW line's.
METRICS = (
    ("dcgain_db", "tian", "low_frequency_gain_db", {}),
    ("f0_hz", "tian", "unity_crossing_hz", {}),
    ("phase_at_f0_deg", "tian", "phase_at_unity_deg", {}),
    ("f180_hz", "tian", "phase_crossover_hz", {}),
    ("gain_at_f180_db", "tian", "gain_margin_db", {}),
    ("f0_rising_hz", "tian", "rising_unity_crossing_hz", {}),
    ("resurgence_db", "tian", "peak_above_crossover_db", {"from_ratio": 1.05}),
)

#: ``tian`` reasons that mean "no such crossing in band" -- an empty ROW field.
_UNAVAILABLE = "tian_metric_unavailable"

_MEAS_DIAG = re.compile(r"measurement '([A-Za-z0-9_]+)'")
#: ngspice's routine, non-fatal fallback notice; klt grades it `nonconvergence`.
_ROUTINE_NONCONVERGENCE = "Dynamic gmin stepping failed"

SUPPLY_PARAM = "vsup"

_SERIES = {"load_node": "binj", "source": "vinj"}


def _num(v: float) -> str:
    return f"{v:.9g}"


def body(iload: float, ceff: float, esr: float, dc_seed: str = "") -> str:
    text = (HERE / "klt_body.spice.in").read_text()
    for tok, val in (("@ILOAD@", _num(iload)), ("@CEFF@", _num(ceff)),
                     ("@ESR@", _num(esr)), ("@DC_SEED@", dc_seed)):
        text = text.replace(tok, val)
    assert not re.search(r"@[A-Z_]+@", text), "unsubstituted token"
    return "\n".join([kb.DESIGN_PARAMS, kb.WNFLAG, text])


def analysis(ac_dec: int, f_start: str, f_stop: str) -> dict:
    return {
        "kind": "ac",
        "args": f"dec {ac_dec} {f_start} {f_stop}",
        "passes": [
            {"name": "inj_v", "alter": [{"target": "Vinj", "value": 1}, {"target": "Iinj", "value": 0}]},
            {"name": "inj_i", "alter": [{"target": "Vinj", "value": 0}, {"target": "Iinj", "value": 1}]},
        ],
    }


def measurements() -> list:
    out = [{"name": "vout_v", "expr": "v(vout)"}]
    for name, _kind, metric, extra in METRICS:
        out.append({"name": name, "tian": {
            "voltage_pass": "inj_v", "current_pass": "inj_i",
            "series_injection": dict(_SERIES), "metric": metric, **extra}})
    return out


def job(name: str, cfg: tuple, dut: Path, ac_dec: int, f_start: str, f_stop: str,
        axes: dict, dc_seed: str = "") -> kb.Job:
    return kb.Job(name=name, body=body(*cfg, dc_seed=dc_seed), dut_netlist=dut,
                  analysis=analysis(ac_dec, f_start, f_stop), measurements=measurements(),
                  timeout_s=900, supply_param=SUPPLY_PARAM, **axes)


def collect_values(report: dict, supply_key: str = SUPPLY_PARAM) -> tuple[dict, list[tuple[str, str]]]:
    """{corner_id: {field: float | None}} and the ``(corner_id, problem)`` pairs in ``report``.

    A field is None for a metric klt reports unavailable (no crossing in band);
    any other non-ok measurement, or a corner that is not ok, is a problem and
    its field is also None (the caller treats a problem as a failed corner).
    """
    values: dict[str, dict] = {}
    problems: list[tuple[str, str]] = []
    for c in report.get("corners", []):
        cid = kb.corner_id(c, supply_key)
        # klt reports a failed measurement as a corner-level `measurement`
        # diagnostic ("[reason] measurement '<name>': ..."), not on the entry.
        meas_msgs: dict[str, str] = {}
        for d in c.get("diagnostics", []):
            code, msg = d.get("code", ""), d.get("message", "")
            m = _MEAS_DIAG.search(msg) if code == "measurement" else None
            if m:
                meas_msgs[m.group(1)] = msg
            elif code == "measurement" or _ROUTINE_NONCONVERGENCE in msg:
                # an unattributable measurement error is a problem; ngspice's
                # routine gmin-stepping fallback notice is not (see
                # harness/runner.py FATAL_LOG_PATTERNS for why)
                if code == "measurement":
                    problems.append((cid, f"measurement diagnostic: {msg}"))
            else:
                problems.append((cid, f"diagnostic {code}: {msg}"))
        for p in c.get("passes", []):
            if p.get("status") != "ok":
                problems.append((cid, f"pass {p.get('name')} status {p.get('status')}"))
        fields: dict[str, float | None] = {}
        for m in c.get("measurements", []):
            name, v = m["name"], m.get("value")
            if v is None:
                msg = meas_msgs.get(name, "")
                if name != "vout_v" and _UNAVAILABLE in msg:
                    fields[name] = None
                    continue
                problems.append((cid, f"{name} has no value ({msg.strip() or m.get('status')})"))
            fields[name] = None if v is None else (-v if name == "gain_at_f180_db" else v)
        values[cid] = fields
    return values, problems


def row_line(cfg: tuple, f: dict) -> str:
    def fmt(k):
        v = f.get(k)
        return "" if v is None else f"{v:.9e}"
    il, ce, es = cfg
    return (f"ROW iload_a={_num(il)} ceff_f={_num(ce)} esr_ohm={_num(es)} vout_v={fmt('vout_v')} "
            + " ".join(f"{n}={fmt(n)}" for n, *_ in METRICS))


def run_configs(configs, dut: Path, ac_dec: int, f_start: str, f_stop: str, axes: dict,
                workdir: Path, outdir: Path, backend: str | None, in_flight: int,
                dc_seed: str = "", log=print) -> tuple[dict, list[str], set[str]]:
    """Submit one request per configuration.

    Returns ``({cfg: {corner_id: fields}}, problems, corners_with_problems)``.

    ``backend="local"`` runs one request at a time. Raw reports go under
    ``outdir/klt-reports/`` (redacted for this public repo), with the request
    JSON next to them so a record's Links point at what was submitted.
    """
    results: dict = {}
    problems: list[str] = []
    bad: set[str] = set()
    suffix = "_dcseed" if dc_seed else ""

    def go(cfg):
        tag = f"il{_num(cfg[0])}_ce{_num(cfg[1])}_es{_num(cfg[2])}{suffix}"
        j = job(tag, cfg, dut, ac_dec, f_start, f_stop, axes, dc_seed)
        with tempfile.TemporaryDirectory(prefix="klt-ls-") as tmp:
            req = kb.stage(j, Path(tmp) / tag)
            report = kb.run(req, Path(tmp) / "out", backend=backend, log=log)
            vals_dir = outdir / "klt-reports"
            vals_dir.mkdir(parents=True, exist_ok=True)
            (vals_dir / f"{tag}.json").write_text(
                json.dumps(kb.redact(report), indent=1, sort_keys=True) + "\n")
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


def klt_version() -> str:
    """``klt --version`` of the client that submitted the requests ($KLT_CMD aware)."""
    proc = subprocess.run(kb.klt_cmd() + ["--version"], capture_output=True, text=True)
    return (proc.stdout or proc.stderr).strip()
