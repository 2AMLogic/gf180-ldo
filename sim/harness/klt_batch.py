"""Run a testbench's PVT matrix through ``klt sim`` (klayout-tools) instead of
a local ``ngspice -b`` fan-out.

Why this exists (issue #320). The standalone bash drivers under
``sim/<slug>/testbench/run.sh`` fan one ``ngspice -b`` per PVT point out over
``xargs -P`` on the invoking host. On the shared dispatch workers this repo's
agents run on, a multi-corner grid must not run locally: it has to be
expressed as a ``klt sim`` request, which the host's ``KLT_SIM_BACKEND=batch``
submits to the Spot batch fleet. ``klt sim`` owns the deck's single
``.control`` block and runs exactly one analysis per corner, so a bench whose
deck chains several ``op``/``alter`` steps in ``.control`` cannot be pointed
at it unchanged -- each driver that uses this module therefore supplies a
*circuit body* (stimulus + DUT include, no ``.control``) and a measurement
list, and this module does the rest:

* corner bundles come from ``sim/harness/corners.py`` (the single source of
  truth for "corner name -> model sections"), so a ``klt`` grid and a
  ``run.sh`` grid bind the identical ``.lib`` sections;
* the DUT netlist is copied next to the body, so ``klt``'s off-host include
  staging picks it up by a relative path;
* a submission refused only because the shared fleet is at its concurrency
  cap is re-submitted after a bounded, jittered wait (``klt``'s own
  ``batch.capacity_wait_s`` covers Spot *capacity* refusals but not this one);
* the per-corner logs ``klt`` returns (``options.keep_artifacts``) are copied
  into ``sim/<slug>/corners/<record-id>/`` under this repo's
  ``<corner>_<temp>c_<vin>v`` names, next to the report JSON, so the record's
  Links point at committed evidence exactly as for ``run.sh``.

Nothing here decides pass/fail; drivers summarise the returned values against
their own bench's bounds.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .corners import CORNERS

#: The process axis the three standalone PVT benches sweep (bjt_ff/bjt_ss
#: omitted: the design has no bipolar device -- same convention as run.sh).
LDO_PROCESS = ("tt", "ff", "ss", "fs", "sf", "res_ff", "res_ss")
TEMPS = (-40, 27, 125)
SUPPLIES = (2.97, 3.30, 3.63)

#: Contents of the PDK's ``libs.tech/ngspice/design.ngspice`` (gf180mcuD),
#: inlined so a body needs no PDK-side ``.include`` that an off-host backend
#: would have to resolve. Every value here is the PDK's own default.
DESIGN_PARAMS = (
    ".param sw_stat_global=0 sw_stat_mismatch=0 mc_skew=3 res_mc_skew=3 "
    "cap_mc_skew=3 fnoicor=0"
)
#: DR-0025: gf180mcu bins on per-finger width; the pass device only resolves
#: to a declared bin with this set.
WNFLAG = ".options wnflag=1"

_CAP_REFUSAL = "exceeds BATCH_MAX_CONCURRENT_INSTANCES"


class KltError(RuntimeError):
    pass


def process_axis(names=LDO_PROCESS) -> list[dict]:
    return [{"name": n, "sections": list(CORNERS[n].sections)} for n in names]


def only_axes(only: str | None) -> dict:
    """``"tt,27,3.30"`` -> Job axis overrides for a single-point debug run."""
    if not only:
        return {}
    proc, temp, vin = only.split(",")
    return {"process": (proc,), "temps": (float(temp),), "supplies": (float(vin),)}


def corner_id(c: dict, supply_key: str) -> str:
    vin = float(c["supply_v"][supply_key])
    t = c["temperature_c"]
    t = int(t) if float(t).is_integer() else t
    return f"{c['process']}_{t}c_{vin:.2f}v"


@dataclass
class Job:
    name: str            # short label, used for the work-dir and report file names
    body: str            # circuit body; must ``.include "dut.spice"``
    dut_netlist: Path    # copied to <workdir>/dut.spice
    analysis: dict
    measurements: list
    supply_key: str = "vin"
    process: tuple = LDO_PROCESS
    temps: tuple = TEMPS
    supplies: tuple = SUPPLIES
    timeout_s: int = 1800

    def request(self) -> dict:
        return {
            "netlist": "body.spice",
            "engine": "ngspice",
            "netlist_source": "schematic",
            "models": {"pdk": "gf180mcuD", "lib": "libs.tech/ngspice/sm141064.ngspice"},
            "corners": {
                "process": process_axis(self.process),
                "supply_v": {self.supply_key: list(self.supplies)},
                "temperature_c": list(self.temps),
            },
            "analysis": self.analysis,
            "measurements": self.measurements,
            "options": {"timeout_s": self.timeout_s, "keep_artifacts": True},
        }


def stage(job: Job, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(job.dut_netlist, workdir / "dut.spice")
    (workdir / "body.spice").write_text(job.body)
    req = workdir / "request.json"
    req.write_text(json.dumps(job.request(), indent=2) + "\n")
    return req


def run(req: Path, outdir: Path, backend: str | None = None,
        max_cap_wait_s: float = 4 * 3600, log=print) -> dict:
    """Run ``klt sim`` on ``req``; return the parsed report.

    ``backend=None`` leaves the choice to ``klt`` (request field, then
    ``$KLT_SIM_BACKEND``). Re-submits only on the fleet concurrency-cap
    refusal, within ``max_cap_wait_s``; any other failure raises.
    """
    cmd = ["klt", "sim", str(req), "-o", str(outdir), "--format", "json"]
    if backend:
        cmd += ["--backend", backend]
    deadline = time.monotonic() + max_cap_wait_s
    delay = 60.0
    while True:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        try:
            report = json.loads(proc.stdout) if proc.stdout.strip() else None
        except json.JSONDecodeError:
            report = None
        if report is not None and "error" not in report:
            return report
        message = (report or {}).get("error", {}).get("message", "") + proc.stderr
        if _CAP_REFUSAL in message and time.monotonic() + delay < deadline:
            wait = delay * random.uniform(0.5, 1.0)
            log(f"  fleet at its concurrency cap; re-submitting {req.parent.name} in {wait:.0f}s")
            time.sleep(wait)
            delay = min(delay * 2, 600.0)
            continue
        raise KltError(f"klt sim failed for {req} (exit {proc.returncode}):\n{message.strip()}")


def collect(report: dict, job: Job, dest: Path, tag: str = "") -> dict[str, dict]:
    """Copy per-corner logs into ``dest`` and return {corner_id: {meas: value}}."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"klt-report{tag}.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    values: dict[str, dict] = {}
    for c in report.get("corners", []):
        cid = corner_id(c, job.supply_key)
        values[cid] = {m["name"]: m.get("value") for m in c.get("measurements", [])}
        values[cid]["_status"] = c.get("status")
        values[cid]["_diagnostics"] = ";".join(d.get("code", "") for d in c.get("diagnostics", []))
        log = (c.get("artifacts") or {}).get("log")
        if log and Path(log).is_file():
            shutil.copyfile(log, dest / f"{cid}{tag}.log")
    return values
