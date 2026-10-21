#!/usr/bin/env python3
"""startup PVT grid through ``klt sim`` (issue #469).

    python3 sim/startup/testbench/klt_run.py --record-id <id> \\
        [--dut design/netlist/ldo_core.spice] [--baseline-ref origin/main] [--only tt,27,3.30]

The grid, measurements and bounds are tb.json's, mapped onto a ``klt sim``
request by sim/harness/tb_adapter.py. Output: sim/startup/corners/<record-id>/.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from harness import tb_adapter  # noqa: E402

if __name__ == "__main__":
    sys.exit(tb_adapter.main(HERE, __doc__))
