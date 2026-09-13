#!/usr/bin/env bash
# Shared "corner name -> model-section codegen" step for the three
# PVT-sweep testbenches:
#
#   sim/current-limit/testbench/run.sh
#   sim/enable-shutdown/testbench/run.sh
#   sim/soft-start/testbench/run.sh
#
# (sim/op-point-sanity/testbench/run.sh doesn't need this -- it hardcodes a
# single nominal corner.) Each of the three scripts shelled out to python3
# to print a `corner_sections() { case "$1" in ... esac }` shell function
# body from sim/harness/corners.py's CORNERS dict, then `eval`'d it. That
# block had drifted into three identical copies (issue #207) -- this file
# is the single implementation, following the same shape as
# run_point.sh's dedup of the substitute/run/fatal-check body (issue #193).
#
# Usage from a testbench's run.sh:
#
#   source "$REPO_ROOT/sim/harness/lib/corner_sections.sh"
#   harness_load_corner_sections "$REPO_ROOT"
#
# Defines a `corner_sections()` function in the calling shell that maps a
# corner name to its "mos res bjt diode moscap mimcap" model sections.
# Generated once, up front, rather than shelled out to python per lookup,
# since corner_sections() runs inside the parallel `xargs -P "$JOBS"`
# fan-out in run_point() -- one python3 startup per script run, not one per
# PVT point.
harness_load_corner_sections() {
  local repo_root="$1"
  eval "$(python3 - "$repo_root" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1] + "/sim")
from harness.corners import CORNERS

print("corner_sections() {")
print('  case "$1" in')
for name, corner in CORNERS.items():
    print(f'    {name}) echo "{" ".join(corner.sections)}" ;;')
print('    *) echo "FATAL: unknown corner $1" >&2; exit 1 ;;')
print("  esac")
print("}")
EOF
)"
}
