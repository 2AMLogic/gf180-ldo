#!/usr/bin/env bash
# DC operating-point sanity check for design/ldo_core.sch (issue #8).
#
#   ./sim/op-point-sanity/testbench/run.sh
#
# This is a loop-closure sanity check at ONE nominal PVT point, not a
# corner-swept spec-line measurement -- the issue's acceptance bar is
# explicitly "DC operating-point sanity sim at nominal conditions", not a
# full PVT matrix (that is what sim/<claim-slug>/ testbenches under future
# issues, e.g. #12's dropout-vs-load, are for). Per sim/README.md, a subset
# run must state why; this script's subset-reason is baked in above, not
# user-configurable, because that IS this experiment's whole point.
#
# Runs the nominal point twice: EN=VIN (enabled, the recorded claim) and
# EN=0 (disabled, a supplementary confirmation that the enable stub gates
# the circuit into a low-current state -- also part of the issue's test
# plan). Both logs land under the SAME record-id's corners/ directory.
#
# Deliberately standalone (does not go through sim/harness/run_corners.py):
# the harness's testbench-fragment convention forbids `.include` in tb.json
# netlists, but the whole point of this check is to `.include` the exact
# netlist design/netlist.py exported from design/ldo_core.sch. This script
# instead substitutes @TOKENS@ in tb_op_point_sanity.spice.in directly
# (the same template-substitution style as sim/devchar/lib/devchar.sh) and
# runs the result with a plain `ngspice -b`, then writes the evidence
# record by hand in the sim/README.md format.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPDIR="$(cd "$HERE/.." && pwd)"           # sim/op-point-sanity
REPO_ROOT="$(cd "$EXPDIR/../.." && pwd)"

# --- PDK / ngspice discovery (single implementation: sim/harness/pdk.py,
# sim/harness/runner.py) -- ngspice_version() also fails loud with an
# actionable message if ngspice is missing, replacing a bare `command -v`
# guard. --------------------------------------------------------------------
PDK_INFO="$(python3 - "$REPO_ROOT" <<'EOF'
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
DESIGN_INCLUDE="$(sed -n '1p' <<<"$PDK_INFO")"
MODEL_LIB="$(sed -n '2p' <<<"$PDK_INFO")"
PDK_VARIANT="$(sed -n '3p' <<<"$PDK_INFO")"
PDK_VERSION="$(sed -n '4p' <<<"$PDK_INFO")"
NGSPICE_VERSION="$(sed -n '5p' <<<"$PDK_INFO")"
# Fatal-condition sentinel: single source of truth is
# sim/harness/runner.py's FATAL_LOG_PATTERN (issue #157). This also fixes
# this file's own gate-vs-diagnostic-dump inconsistency: line 94's `-q` gate
# and the old line 96 `-n` dump used to carry two different (drifted)
# copies of this pattern -- now both use the one string.
FATAL_LOG_PATTERN="$(sed -n '6p' <<<"$PDK_INFO")"

# --- committed, current netlist (fail loud if stale) ----------------------
python3 "$REPO_ROOT/design/netlist.py" --check >/dev/null
LDO_NETLIST="$REPO_ROOT/design/netlist/ldo_core.spice"

# --- record-id (sim/README.md convention) ----------------------------------
RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
LOG_DIR="$EXPDIR/corners/$RECORD_ID"
mkdir -p "$LOG_DIR"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

run_point() {
  local en_v="$1" corner_id="$2"
  local deck="$WORKDIR/${corner_id}.spice"
  local log="$LOG_DIR/${corner_id}.log"

  sed \
    -e "s|@DESIGN_INCLUDE@|$DESIGN_INCLUDE|g" \
    -e "s|@MODEL_LIB@|$MODEL_LIB|g" \
    -e "s|@LDO_NETLIST@|$LDO_NETLIST|g" \
    -e "s|@MOS_CORNER@|typical|g" \
    -e "s|@RES_CORNER@|res_typical|g" \
    -e "s|@BJT_CORNER@|bjt_typical|g" \
    -e "s|@DIODE_CORNER@|diode_typical|g" \
    -e "s|@MOSCAP_CORNER@|moscap_typical|g" \
    -e "s|@MIMCAP_CORNER@|mimcap_typical|g" \
    -e "s|@TEMP_C@|27|g" \
    -e "s|@VIN_V@|3.3|g" \
    -e "s|@EN_V@|$en_v|g" \
    "$HERE/tb_op_point_sanity.spice.in" > "$deck"

  if ! ngspice -b "$deck" > "$log" 2>&1; then
    echo "FATAL: ngspice failed on $corner_id (see $log)" >&2
    tail -40 "$log" >&2
    exit 1
  fi
  if grep -qE "$FATAL_LOG_PATTERN" "$log"; then
    echo "FATAL: ngspice reported an error on $corner_id (see $log)" >&2
    grep -nE "$FATAL_LOG_PATTERN" "$log" >&2
    exit 1
  fi

  local vout vin_m loop fb vref_m ivin_ma ien_ua
  vout="$(grep -E '^m_vout = ' "$log" | tail -1 | awk '{print $3}')"
  vin_m="$(grep -E '^m_vin = ' "$log" | tail -1 | awk '{print $3}')"
  loop="$(grep -E '^m_loop = ' "$log" | tail -1 | awk '{print $3}')"
  fb="$(grep -E '^m_fb = ' "$log" | tail -1 | awk '{print $3}')"
  vref_m="$(grep -E '^m_vref = ' "$log" | tail -1 | awk '{print $3}')"
  ivin_ma="$(grep -E '^m_ivin_ma = ' "$log" | tail -1 | awk '{print $3}')"
  ien_ua="$(grep -E '^m_ien_ua = ' "$log" | tail -1 | awk '{print $3}')"

  echo "$corner_id (EN=$en_v): vout=$vout vin=$vin_m loop=$loop fb=$fb vref=$vref_m ivin_ma=$ivin_ma ien_ua=$ien_ua"
  echo "  log: $log"
}

echo "pdk       : $PDK_VARIANT @ $PDK_VERSION"
echo "ngspice   : $NGSPICE_VERSION"
echo "record id : $RECORD_ID"
echo

run_point 3.3 tt_27c_3.30v
run_point 0 tt_27c_3.30v_endis

# Netlist snapshot: the exact DUT netlist this record was taken against.
SNAP_DIR="$EXPDIR/netlist-snapshots"
mkdir -p "$SNAP_DIR"
cp "$LDO_NETLIST" "$SNAP_DIR/$RECORD_ID.spice"

echo
echo "netlist snapshot : $SNAP_DIR/$RECORD_ID.spice"
echo "raw logs         : $LOG_DIR/"
echo "record-id        : $RECORD_ID"
echo "(write sim/op-point-sanity/records/$RECORD_ID.md by hand -- see sim/README.md format)"
