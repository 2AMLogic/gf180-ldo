#!/usr/bin/env bash
# Current-limit PVT sweep for design/ldo_core.sch + design/ldo_ilimit.sch
# (issue #11).
#
#   ./sim/current-limit/testbench/run.sh              # full matrix, writes evidence
#   NO_RECORD=1 CORNERS=tt TEMPS=27 SUPPLIES=3.30 \
#       ./sim/current-limit/testbench/run.sh          # single point, writes nothing
#
# Deliberately standalone rather than a sim/harness/ testbench, for the same
# reason sim/op-point-sanity/testbench/run.sh is: the harness's testbench
# fragments may not contain `.include`, and the whole point of this bench is
# to include the exact netlist design/netlist.py exported from the
# schematic. This script substitutes @TOKENS@ into the deck template (the
# same style as sim/devchar/lib/devchar.sh) and runs `ngspice -b`, then
# leaves a per-corner CSV rollup that the hand-written record cites.
#
# Corner matrix (sim/README.md requires the full mandated PVT matrix or a
# stated reason for a subset -- the reason is stated in the record):
#   process   tt ff ss fs sf res_ff res_ss   (a superset of the harness's
#                                             default `mos` set; bjt_ff /
#                                             bjt_ss are omitted because the
#                                             design contains no bipolar
#                                             devices)
#   temp      -40 27 125 degC
#   supply    2.97 3.30 3.63 V  (3.3 V +/-10%, DR-0002)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPDIR="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$EXPDIR/../.." && pwd)"
SLUG="$(basename "$EXPDIR")"

CORNERS="${CORNERS:-tt ff ss fs sf res_ff res_ss}"
TEMPS="${TEMPS:--40 27 125}"
SUPPLIES="${SUPPLIES:-2.97 3.30 3.63}"
JOBS="${JOBS:-4}"

# corner name -> "mos res bjt diode moscap mimcap" model sections. Single
# source of truth: sim/harness/corners.py's CORNERS. Generated once, up
# front (like PDK_INFO below) rather than shelled out to python per lookup,
# since corner_sections() runs inside the parallel `xargs -P "$JOBS"`
# fan-out in run_point() -- one python3 startup per script run, not one per
# PVT point.
eval "$(python3 - "$REPO_ROOT" <<'EOF'
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
# sim/harness/runner.py's FATAL_LOG_PATTERN (issue #157).
FATAL_LOG_PATTERN="$(sed -n '6p' <<<"$PDK_INFO")"

# --- committed, current netlist (fail loud if stale) ----------------------
python3 "$REPO_ROOT/design/netlist.py" --check >/dev/null
LDO_NETLIST="$REPO_ROOT/design/netlist/ldo_core.spice"

RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
LOG_DIR="$EXPDIR/corners/$RECORD_ID"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
mkdir -p "$LOG_DIR"

echo "experiment : $SLUG"
echo "pdk        : $PDK_VARIANT @ $PDK_VERSION"
echo "ngspice    : $NGSPICE_VERSION"
echo "record id  : $RECORD_ID"
echo

# One ngspice invocation per PVT point.
run_point() {
  local corner="$1" temp="$2" vin="$3"
  local sections; sections="$(corner_sections "$corner")"
  read -r s_mos s_res s_bjt s_dio s_mosc s_mimc <<<"$sections"
  local corner_id; corner_id="$(printf '%s_%sc_%.2fv' "$corner" "$temp" "$vin")"
  local deck="$WORKDIR/${corner_id}.spice"
  local log="$LOG_DIR/${corner_id}.log"

  sed \
    -e "s|@DESIGN_INCLUDE@|$DESIGN_INCLUDE|g" \
    -e "s|@MODEL_LIB@|$MODEL_LIB|g" \
    -e "s|@LDO_NETLIST@|$LDO_NETLIST|g" \
    -e "s|@MOS_CORNER@|$s_mos|g" \
    -e "s|@RES_CORNER@|$s_res|g" \
    -e "s|@BJT_CORNER@|$s_bjt|g" \
    -e "s|@DIODE_CORNER@|$s_dio|g" \
    -e "s|@MOSCAP_CORNER@|$s_mosc|g" \
    -e "s|@MIMCAP_CORNER@|$s_mimc|g" \
    -e "s|@TEMP_C@|$temp|g" \
    -e "s|@VIN_V@|$vin|g" \
    "$HERE/tb_current_limit.spice.in" > "$deck"

  if ! ngspice -b "$deck" > "$log" 2>&1; then
    echo "FATAL: ngspice failed on $corner_id (see $log)" >&2
    tail -40 "$log" >&2
    return 1
  fi
  if grep -qE "$FATAL_LOG_PATTERN" "$log"; then
    echo "FATAL: ngspice reported an error on $corner_id (see $log)" >&2
    grep -nE "$FATAL_LOG_PATTERN" "$log" >&2
    return 1
  fi
  echo "$corner_id"
}
export -f run_point corner_sections
export WORKDIR LOG_DIR HERE DESIGN_INCLUDE MODEL_LIB LDO_NETLIST FATAL_LOG_PATTERN

points=()
for c in $CORNERS; do for t in $TEMPS; do for v in $SUPPLIES; do
  points+=("$c $t $v")
done; done; done

printf '%s\n' "${points[@]}" \
  | xargs -P "$JOBS" -I{} bash -c 'run_point $0' "{}" \
  | sort

# --- rollup ---------------------------------------------------------------
CSV="$LOG_DIR/summary.csv"
python3 "$HERE/summarize.py" "$LOG_DIR" "$CSV" "$CORNERS" "$TEMPS" "$SUPPLIES"

if [ -n "${NO_RECORD:-}" ]; then
  echo
  echo "NO_RECORD set: logs left in $LOG_DIR (not evidence -- delete or keep out of git)"
  exit 0
fi

SNAP_DIR="$EXPDIR/netlist-snapshots"
mkdir -p "$SNAP_DIR"
cp "$LDO_NETLIST" "$SNAP_DIR/$RECORD_ID.spice"

echo
echo "netlist snapshot : $SNAP_DIR/$RECORD_ID.spice"
echo "raw logs         : $LOG_DIR/"
echo "rollup           : $CSV"
echo "record-id        : $RECORD_ID"
echo "(write $EXPDIR/records/$RECORD_ID.md by hand -- see sim/README.md format)"
