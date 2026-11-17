"""The Tian loop-gain metric surface for ``klt sim`` front ends (issue #630).

The ``tian`` metric table, the dual-injection ``analysis`` passes and the
report collection of ``sim/loop-stability/testbench/klt_run.py`` are the
loop-gain extraction itself, so ``sim/soft-start-loop-gain/testbench/
klt_run.py`` reuses them rather than restating them -- it used to reach them
by loading that file by filesystem path, which bound a foreign module name in
``sys.modules``; they live here instead, imported by name by both benches
(issue #630).

See ``sim/loop-stability/testbench/klt_run.py``'s module docstring for what
each metric is and how a batch record's extraction differs from the local
deck's; this module is that file's shared surface, not a new semantics.
"""

from __future__ import annotations

import re
import subprocess

from . import klt_batch as kb

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


def fmt_num(v: float) -> str:
    return f"{v:.9g}"


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


def klt_version() -> str:
    """``klt --version`` of the client that submitted the requests ($KLT_CMD aware)."""
    proc = subprocess.run(kb.klt_cmd() + ["--version"], capture_output=True, text=True)
    return (proc.stdout or proc.stderr).strip()
