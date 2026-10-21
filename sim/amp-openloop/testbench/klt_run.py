#!/usr/bin/env python3
"""amp-openloop PVT grid through ``klt sim`` (issue #468).

    python3 sim/amp-openloop/testbench/klt_run.py --record-id <id> \\
        [--dut <netlist>] [--baseline-ref origin/main] [--only tt,27,3.30]

The grid, measurements and bounds are tb.json's, mapped onto ``klt sim`` requests
by sim/harness/tb_adapter.py. tb.json chains ``op`` and ``ac`` analyses in one
``.control`` block; ``klt sim`` runs one analysis per corner, so the adapter
submits one request per analysis (``op1``, ``ac1``, ...) over the same grid and
merges the values per corner. Error-amplifier cell bench: the DUT is design/netlist/error_amp.spice.
Output: sim/amp-openloop/corners/<record-id>/ (``summary.csv``; raw reports and logs
in ``klt-<state>/new/``).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from harness import tb_adapter  # noqa: E402

if __name__ == "__main__":
    sys.exit(tb_adapter.main(HERE, __doc__))
