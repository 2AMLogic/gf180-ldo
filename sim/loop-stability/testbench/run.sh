#!/usr/bin/env bash
# Loop-stability sweep for design/ldo_core.sch (issue #10).
#
#   ./sim/loop-stability/testbench/run.sh              # full matrix, mints a record
#   ./sim/loop-stability/testbench/run.sh --explore    # DR-0001's first pass, no record
#   ./sim/loop-stability/testbench/run.sh --help       # every option
#
# Thin wrapper around sweep.py, kept so this experiment has the same
# `testbench/run.sh` entry point as sim/op-point-sanity/. It validates the
# extraction method first (selftest.py, which needs neither the PDK nor the
# design netlist) and refuses to run the sweep if that fails -- a loop-gain
# number from an unvalidated extraction is worse than no number, and this
# repo's whole premise is that the verification is the product.
#
# Everything else -- PDK discovery, deck generation, the PVT grid, parsing,
# the evidence record -- lives in sweep.py; see its --help and
# sim/loop-stability/README.md.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== testbench self-test (validates the loop-gain extraction) ==="
python3 "$HERE/selftest.py"
echo
echo "=== loop-stability sweep ==="
exec python3 "$HERE/sweep.py" "$@"
