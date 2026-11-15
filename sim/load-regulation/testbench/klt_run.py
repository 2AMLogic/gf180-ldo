#!/usr/bin/env python3
"""load-regulation PVT grid through ``klt sim`` (issue #467).

    python3 sim/load-regulation/testbench/klt_run.py --record-id <id> \\
        [--dut design/netlist/ldo_core.spice] [--baseline-ref origin/main] [--only tt,27,3.30]

The grid, measurements and bounds are tb.json's, mapped onto a ``klt sim``
request by sim/harness/tb_adapter.py. Output: the git-ignored staging tree
``sim/.work/.stage/load-regulation/sim/load-regulation/corners/<record-id>/``; it becomes evidence only
when ``PYTHONPATH=sim python3 -m harness.klt_record load-regulation --record-id <id>``
stores the bytes and mints the record (DR-0044).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from harness import tb_adapter  # noqa: E402

if __name__ == "__main__":
    sys.exit(tb_adapter.main(HERE, __doc__))
