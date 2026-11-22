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
  into the caller's ``dest`` under this repo's ``<corner>_<temp>c_<vin>v``
  names, next to the report JSON. :func:`collect` writes wherever it is
  pointed; a ``tb_adapter`` run points it at the git-ignored staging tree and
  ``harness.klt_record`` then stores those bytes (DR-0044), while the
  hand-rolled drivers still point it straight at
  ``sim/<slug>/corners/<record-id>/`` (issue #596).

Nothing here decides pass/fail; drivers summarise the returned values against
their own bench's bounds.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .corners import CORNERS, format_corner_id

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
_OUTDIR_LOCKED = "outdir_locked"


class KltError(RuntimeError):
    pass


def klt_cmd() -> list[str]:
    """The ``klt`` invocation: ``$KLT_CMD`` (shell-split) or plain ``klt``.

    Lets a run use a pinned client in a throwaway environment, e.g.
    ``KLT_CMD='uvx --from git+https://github.com/2AMLogic/klayout-tools.git@<sha> klt'``,
    without touching the host-wide install (issue #352).
    """
    return shlex.split(os.environ.get("KLT_CMD", "klt"))


def process_axis(names=LDO_PROCESS) -> list[dict]:
    return [{"name": n, "sections": list(CORNERS[n].sections)} for n in names]


def only_axes(only: str | None) -> dict:
    """``"tt,27,3.30"`` -> Job axis overrides for a single-point debug run."""
    if not only:
        return {}
    proc, temp, vin = only.split(",")
    return {"process": (proc,), "temps": (float(temp),), "supplies": (float(vin),)}


def corner_id(c: dict, supply_key: str, fixed_supply: float | None = None) -> str:
    """The grid's corner id for one ``klt`` report row (issue #780).

    The supply is klt's own selection -- the fixed-supply override, else the
    ``corners.params`` row, else the ``corners.supply_v`` axis -- and the id
    itself is the one shared formatter, :func:`harness.corners.format_corner_id`,
    so a report row always spells the id the grid point it belongs to was
    keyed under.
    """
    vin = (float(fixed_supply) if fixed_supply is not None
           else float(c["params"][supply_key] if supply_key in (c.get("params") or {})
                      else c["supply_v"][supply_key]))
    return format_corner_id(c["process"], c["temperature_c"], vin)


@dataclass
class Job:
    name: str            # short label, used for the work-dir and report file names
    body: str            # circuit body; must ``.include "dut.spice"``
    dut_netlist: Path    # copied to <workdir>/dut.spice
    analysis: dict
    measurements: list
    supply_key: str = "vin"
    #: When set, the supply axis is the ``corners.params`` row of this top-level
    #: ``.param`` (``alterparam`` + ``reset``) instead of ``corners.supply_v``
    #: (``alter``). For a bench whose result must not pass through an ``alter``
    #: of its supply sources (see loop-stability/testbench/klt_body.spice.in).
    supply_param: str | None = None
    process: tuple = LDO_PROCESS
    temps: tuple = TEMPS
    supplies: tuple = SUPPLIES
    timeout_s: int = 1800
    #: ``options.ngspice_init`` lines (``set numdgt=10``, ...); empty leaves
    #: ``klt``'s defaults. See ``tb_adapter.py``.
    ngspice_init: tuple = ()
    #: ``options.stage_model_inputs``: ship the submitter's model files with
    #: the job instead of resolving ``models`` on the runner image. Off-host
    #: backends otherwise execute whatever PDK revision the image carries
    #: (the batch image was at open_pdks ``c6d73a3`` when #467 checked), not
    #: the revision ``sim/harness/pdk.py`` pins; a record that claims the pin
    #: must stage. No effect on ``local``.
    stage_model_inputs: bool = False
    #: The supply is written into ``body`` (``.param vdd_val=<v>``), not swept:
    #: the request has no supply axis and ``supplies`` is the single value the
    #: body carries, which names the corners. For a bench whose supply is a
    #: ``.param`` the fragment's expressions read, on a backend whose worker
    #: predates ``corners.params`` (it answers ``params_unsupported_worker``).
    supply_in_body: bool = False
    #: ``request.monte_carlo`` (``{"n", "seed", "vary"}``): every corner point is
    #: re-run ``n`` times with a seed derived from ``seed``. Sample ``k`` of a
    #: corner comes back as its own unit, ``<corner_id>`` + ``sample_index``.
    monte_carlo: dict | None = None
    #: ``request.batch`` keys. ``max_units_per_job`` splits the request into
    #: ``ceil(units / N)`` fleet jobs: a unit that takes minutes (a 6 ms transient
    #: into a near-short) otherwise lets one job run into the fleet's 3600 s
    #: whole-job ceiling, which reports EVERY unit of it ``batch_job_timeout``
    #: (klt refuses a cap unless ``timeout_s * N + 120 <= 3600``, so ``timeout_s``
    #: is lowered with it). A split request's shards that the fleet's instance cap
    #: refuses come back ``lost_shard``, not retried: ``max_concurrent_jobs`` bounds
    #: this request's jobs in flight and ``capacity_wait_s`` waits out a refusal.
    batch: dict | None = None

    def request(self) -> dict:
        return {
            "netlist": "body.spice",
            "engine": "ngspice",
            "netlist_source": "schematic",
            "models": {"pdk": "gf180mcuD", "lib": "libs.tech/ngspice/sm141064.ngspice"},
            "corners": {
                "process": process_axis(self.process),
                **({} if self.supply_in_body
                   else {"params": {self.supply_param: list(self.supplies)}} if self.supply_param
                   else {"supply_v": {self.supply_key: list(self.supplies)}}),
                "temperature_c": list(self.temps),
            },
            "analysis": self.analysis,
            **({"monte_carlo": self.monte_carlo} if self.monte_carlo else {}),
            "measurements": self.measurements,
            **({"batch": self.batch} if self.batch else {}),
            "options": {"timeout_s": self.timeout_s, "keep_artifacts": True,
                        **({"stage_model_inputs": True} if self.stage_model_inputs else {}),
                        **({"ngspice_init": list(self.ngspice_init)} if self.ngspice_init else {})},
        }


def stage(job: Job, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(job.dut_netlist, workdir / "dut.spice")
    (workdir / "body.spice").write_text(job.body)
    req = workdir / "request.json"
    req.write_text(json.dumps(job.request(), indent=2) + "\n")
    return req


def staged_identity(req: Path) -> dict[str, str]:
    """Named sha256 digests over every staged byte the simulator consumes.

    ``request.json`` names the deck only as a file name (``"netlist":
    "body.spice"``) and the deck reaches the DUT by relative include, so the
    request alone cannot see a circuit edit: :func:`stage` writes the deck
    body and the DUT netlist into separate files beside it. A resume
    decision that compared the request alone could therefore reuse a report
    -- or re-attach a batch shard map -- from a different circuit under one
    record id (issue #796). The identity covers all three staged files.
    """
    return {"request_sha256": _sha256_file(req),
            "body_sha256": _sha256_file(req.parent / "body.spice"),
            "dut_sha256": _sha256_file(req.parent / "dut.spice")}


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _identity_text(req: Path) -> str:
    return json.dumps(staged_identity(req), sort_keys=True) + "\n"


def identity_matches(marker: Path, req: Path) -> bool:
    """True iff ``marker`` exists and holds ``req``'s staged identity.

    A missing marker -- a legacy result from before identity sidecars, or a
    run interrupted before its result was complete -- is a miss, never a
    match (issue #796).
    """
    try:
        return marker.read_text() == _identity_text(req)
    except FileNotFoundError:
        return False


def publish_identity(marker: Path, req: Path) -> None:
    """Record ``req``'s staged identity beside the result it produced.

    Publish only for a complete result, after the report and its other
    sidecars are written: the marker vouches for the report beside it, so a
    marker-first ordering could pair a new marker with an old report from a
    different circuit, which the resume guard would then trust (issue #796;
    the same torn-write rule as PR #745 review 3).
    """
    marker.write_text(_identity_text(req))


def _claim_resume_outdir(outdir: Path, req: Path, log=print) -> None:
    """Make ``outdir``'s retained shard map safe to re-attach to (issue #796).

    ``--resume`` re-attaches to the shard map retained under ``outdir``, so
    the outdir records the staged identity it was submitted with. A
    re-submission whose circuit changed must not collect the previous
    circuit's finished shards: the stale outdir is dropped and the
    submission starts clean. An outdir with no recorded identity -- written
    before this marker existed, or by a non-resume run into the same path --
    is claimed the same way; an interrupted run of the *same* circuit keeps
    its shard map and continues (issue #465).
    """
    marker = outdir / "run-identity.json"
    text = _identity_text(req)
    if outdir.is_dir():
        try:
            same = marker.read_text() == text
        except FileNotFoundError:
            same = False
        if same:
            return
        shutil.rmtree(outdir)
        log(f"  {outdir.name}: dropped retained shard map -- staged circuit changed")
    outdir.mkdir(parents=True, exist_ok=True)
    marker.write_text(text)


def run(req: Path, outdir: Path, backend: str | None = None,
        max_cap_wait_s: float = 4 * 3600, log=print,
        resume: bool = False) -> dict:
    """Run ``klt sim`` on ``req``; return the parsed report.

    ``backend=None`` leaves the choice to ``klt`` (request field, then
    ``$KLT_SIM_BACKEND``). Re-submits on two transient conditions, within
    ``max_cap_wait_s``: the fleet concurrency-cap refusal, and klt's
    ``outdir_locked`` -- a resumed run's outdir can still be held by a
    killed-but-dying earlier owner (its ``flock`` frees the moment the
    process tree is reaped, and the pid in the message is diagnostic only),
    so waiting is the correct response to that refusal; any other failure
    raises.

    ``resume`` passes klt's ``--resume``: a sharded batch request re-attaches
    to the shard map retained under ``outdir`` -- shards whose fleet jobs
    already finished are collected, only the unfinished ones are submitted
    again -- so re-invoking a driver after an interruption continues that
    request instead of repeating it. It needs the same staged ``req`` and
    ``outdir`` as the interrupted run, so a caller that wants resumability
    must keep both out of any tempdir that dies with the session (issue #465).
    Re-attachment is identity-checked: ``outdir`` records the staged identity
    (:func:`staged_identity`) it was submitted with, and a re-submission
    whose circuit changed drops the retained shard map instead of collecting
    the previous circuit's finished shards (issue #796).
    """
    cmd = klt_cmd() + ["sim", str(req), "-o", str(outdir), "--format", "json"]
    if backend:
        cmd += ["--backend", backend]
    if resume:
        _claim_resume_outdir(outdir, req, log=log)
        cmd += ["--resume"]
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
        code = (report or {}).get("error", {}).get("code", "")
        transient = _CAP_REFUSAL in message or code == _OUTDIR_LOCKED
        if transient and time.monotonic() + delay < deadline:
            wait = delay * random.uniform(0.5, 1.0)
            if code == _OUTDIR_LOCKED:
                log(f"  {req.parent.name}'s outdir is locked by another run; "
                    f"retrying in {wait:.0f}s")
            else:
                log(f"  fleet at its concurrency cap; re-submitting {req.parent.name} in {wait:.0f}s")
            time.sleep(wait)
            delay = min(delay * 2, 600.0)
            continue
        raise KltError(f"klt sim failed for {req} (exit {proc.returncode}):\n{message.strip()}")


def redact(report: dict) -> dict:
    """Copy of ``report`` safe to commit to this public repo.

    The batch backend echoes the fleet's job bucket in
    ``environment.remote.bucket``; its name carries deployment account detail
    that klt's own docs deliberately never reproduce, so it is replaced here.
    The job id, instance type and state -- what a reader needs to correlate a
    run -- are kept.
    """
    out = json.loads(json.dumps(report))
    remote = (out.get("environment") or {}).get("remote")
    if isinstance(remote, dict) and "bucket" in remote:
        remote["bucket"] = "<redacted>"
    return out


def values(report: dict, job: Job) -> dict[str, dict]:
    """``{corner_id: {meas: value}}`` parsed from a report, no side effects.

    The value-parsing half of :func:`collect`, separate so a resumed run can
    read values back out of a saved ``klt-report.json`` whose artifact paths
    (the original run's per-corner logs) no longer exist.
    """
    out: dict[str, dict] = {}
    for c in report.get("corners", []):
        cid = corner_id(c, job.supply_key, job.supplies[0] if getattr(job, "supply_in_body", False) else None)
        out[cid] = {m["name"]: m.get("value") for m in c.get("measurements", [])}
        out[cid]["_status"] = c.get("status")
        out[cid]["_diagnostics"] = ";".join(d.get("code", "") for d in c.get("diagnostics", []))
    return out


def collect(report: dict, job: Job, dest: Path, tag: str = "") -> dict[str, dict]:
    """Copy per-corner logs into ``dest`` and return {corner_id: {meas: value}}."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"klt-report{tag}.json").write_text(json.dumps(redact(report), indent=1, sort_keys=True) + "\n")
    for c in report.get("corners", []):
        cid = corner_id(c, job.supply_key, job.supplies[0] if getattr(job, "supply_in_body", False) else None)
        log = (c.get("artifacts") or {}).get("log")
        if log and Path(log).is_file():
            shutil.copyfile(log, dest / f"{cid}{tag}.log")
    return values(report, job)
