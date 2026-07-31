#!/usr/bin/env bash
# Regenerate every device-characterization result under sim/devchar (issue #4).
#
#   ./sim/devchar/run_all.sh
#
# Takes roughly 15 minutes on an Apple-silicon laptop. Each sub-driver truncates
# and rewrites only its own results/*.csv, so a single directory can be re-run on
# its own (see the per-directory run.sh) without disturbing the others.
#
# Requires: ngspice on PATH, and the gf180mcuD PDK models under
# $PDK_ROOT/gf180mcuD/libs.tech/ngspice (PDK_ROOT defaults to ~/.volare).

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$HERE/fets/run.sh"
bash "$HERE/resistors/run.sh"
bash "$HERE/caps/run.sh"
python3 "$HERE/lib/summarize.py"
