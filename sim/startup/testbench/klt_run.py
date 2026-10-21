#!/usr/bin/env python3
"""startup PVT grid through ``klt sim`` (issue #469).

    python3 sim/startup/testbench/klt_run.py --record-id <id> \\
        [--dut design/netlist/ldo_core.spice] [--baseline-ref origin/main] [--only tt,27,3.30]

The grid, measurements and bounds are tb.json's, mapped onto a ``klt sim``
request by sim/harness/tb_adapter.py, one request per supply point (EN steps to ``{vdd_val}``).
A unit is a 6 ms transient into a near-short and takes anywhere from 40 s to over 15 minutes
of ngspice, so each request is split into fleet jobs of 2 units with a 1700 s per-unit timeout
(2 x 1700 + 120 s stays inside the fleet's 3600 s whole-job ceiling, past which EVERY unit of a
job comes back ``batch_job_timeout``; the 81-point grid at one job per request, then at 3
units x 1100 s, lost units to both). The fleet's instance cap is shared with other sweeps, so
each request keeps at most 2 jobs in flight and waits up to 2 h for capacity instead of
returning a refused shard as ``lost_shard``. Output: sim/startup/corners/<record-id>/.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from harness import tb_adapter  # noqa: E402

if __name__ == "__main__":
    sys.exit(tb_adapter.main(HERE, __doc__, timeout_s=1700,
                           batch={"max_units_per_job": 2, "max_concurrent_jobs": 2, "capacity_wait_s": 7200}))
