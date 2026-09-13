#!/usr/bin/env bash
# Shared "discover the gf180mcu PDK and ngspice, and pull out this run's
# fatal-log-line pattern" step for the four sim testbenches:
#
#   sim/current-limit/testbench/run.sh
#   sim/enable-shutdown/testbench/run.sh
#   sim/soft-start/testbench/run.sh
#   sim/op-point-sanity/testbench/run.sh
#
# Each of these scripts shelled out to python3 to resolve the PDK
# (sim/harness/pdk.py's find_pdk()) and pull FATAL_LOG_PATTERN /
# ngspice_version() out of sim/harness/runner.py, then parsed the six-line
# stdout back into shell variables with `sed -n`. That block had drifted
# into four near-identical copies (issue #207) -- this file is the single
# implementation, following the same shape as run_point.sh's dedup of the
# substitute/run/fatal-check body (issue #193).
#
# Usage from a testbench's run.sh:
#
#   source "$REPO_ROOT/sim/harness/lib/pdk_discover.sh"
#   harness_discover_pdk "$REPO_ROOT"
#
# Sets (in the calling shell): DESIGN_INCLUDE, MODEL_LIB, PDK_VARIANT,
# PDK_VERSION, NGSPICE_VERSION, FATAL_LOG_PATTERN. ngspice_version() also
# fails loud with an actionable message if ngspice is missing, replacing a
# bare `command -v` guard. FATAL_LOG_PATTERN's single source of truth is
# sim/harness/runner.py (issue #157).
harness_discover_pdk() {
  local repo_root="$1"
  local pdk_info
  pdk_info="$(python3 - "$repo_root" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1] + "/sim")
from harness.pdk import find_pdk
from harness.runner import FATAL_LOG_PATTERN, ngspice_version
pdk = find_pdk()
print(pdk.design_include)
print(pdk.model_lib)
print(pdk.variant)
print(pdk.version)
print(ngspice_version().split()[0])
print(FATAL_LOG_PATTERN)
EOF
)"
  DESIGN_INCLUDE="$(sed -n '1p' <<<"$pdk_info")"
  MODEL_LIB="$(sed -n '2p' <<<"$pdk_info")"
  PDK_VARIANT="$(sed -n '3p' <<<"$pdk_info")"
  PDK_VERSION="$(sed -n '4p' <<<"$pdk_info")"
  NGSPICE_VERSION="$(sed -n '5p' <<<"$pdk_info")"
  FATAL_LOG_PATTERN="$(sed -n '6p' <<<"$pdk_info")"
}
