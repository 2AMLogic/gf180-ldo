#!/usr/bin/env python3
"""Quiescent-current grid through ``klt sim`` (issue #320).

    python3 sim/quiescent-current/testbench/klt_run.py --record-id <id> \\
        [--dut design/netlist/ldo_core.spice] [--baseline-ref origin/main] [--only tt,27,3.30]

The 81-point grid tb.json declares (tt ff ss fs sf res_ff res_ss bjt_ff bjt_ss
x -40/27/125 C x 2.97/3.30/3.63 V), same measurements and same bounds, plus
the VREF-port current of each instance (see klt_body.spice). With
``--baseline-ref`` the DUT at that ref is run as a second job on the same
backend. Output: the git-ignored staging tree
``sim/.work/.stage/quiescent-current/sim/quiescent-current/corners/<record-id>/``; it becomes evidence only
when ``PYTHONPATH=sim python3 -m harness.klt_record quiescent-current --record-id <id>``
stores the bytes and mints the record (DR-0044).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from harness import klt_batch as kb  # noqa: E402
from harness import tb_adapter  # noqa: E402

# Bench-specific: three separate VREF sources so each state's VREF-port current is metered.
BODY = "\n".join([kb.DESIGN_PARAMS, kb.WNFLAG, (HERE / "klt_body.spice").read_text()])
IREF = [{"name": f"iref_{s}_na", "expr": f"-i(vref_{s})*1e9"} for s in ("en", "dis", "full")]

if __name__ == "__main__":
    sys.exit(tb_adapter.main(HERE, __doc__, body_override=BODY, extra_measurements=IREF, timeout_s=900))
