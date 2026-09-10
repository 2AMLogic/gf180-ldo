#!/usr/bin/env bash
# Soft-start loop-gain / phase-margin sweep (issue #196).
#
#   ./sim/soft-start-loop-gain/testbench/run.sh              # full grid, mints a record
#   ./sim/soft-start-loop-gain/testbench/run.sh --explore    # tt/27C/3.3V only, no record
#   ./sim/soft-start-loop-gain/testbench/run.sh --help       # every option
#
# Cold start is this one command, after `python3 sim/run_corners.py --check-env`
# reports ngspice and the gf180mcu PDK present.
#
# Thin wrapper around sweep.py, with the same shape (and the same rationale)
# as sim/loop-stability/testbench/run.sh: it validates the measurement method
# first and refuses to run the sweep if that fails, because a loop-gain number
# from an unvalidated extraction is worse than no number, and this repo's whole
# premise is that the verification is the product.
#
# The self-test delegates the loop-gain extraction's known-answer checks to
# sim/loop-stability/testbench/selftest.py (the extraction is literally that
# deck's) and adds this experiment's own: that the SSR port promotion is a
# rename and not a circuit change, that the two DUT variants differ only in
# the injection element, that the AC-only sensitivity transforms are DC-inert,
# and that the landing rule refuses the DC branches it exists to refuse.
#
# Everything else -- PDK discovery, the DUT netlist variants, deck generation,
# the PVT grid, the cross-check against sim/loop-stability/, the attribution
# runs and the evidence record -- lives in sweep.py; see its --help and
# sim/soft-start-loop-gain/README.md.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== testbench self-test (validates the loop-gain extraction and this"
echo "=== experiment's own netlist / landing-rule machinery) ==="
python3 "$HERE/selftest.py"
echo
echo "=== soft-start loop-gain sweep ==="
exec python3 "$HERE/sweep.py" "$@"
