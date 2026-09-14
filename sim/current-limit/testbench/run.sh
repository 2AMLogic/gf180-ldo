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

# Shared corner name -> "mos res bjt diode moscap mimcap" model-section
# codegen (single implementation: sim/harness/lib/corner_sections.sh,
# issue #207). Single source of truth: sim/harness/corners.py's CORNERS.
source "$REPO_ROOT/sim/harness/lib/corner_sections.sh"
harness_load_corner_sections "$REPO_ROOT"

# Shared PDK / ngspice discovery (single implementation:
# sim/harness/lib/pdk_discover.sh, issue #207) -- wraps sim/harness/pdk.py
# and sim/harness/runner.py; ngspice_version() also fails loud with an
# actionable message if ngspice is missing, replacing a bare `command -v`
# guard. --------------------------------------------------------------------
source "$REPO_ROOT/sim/harness/lib/pdk_discover.sh"
harness_discover_pdk "$REPO_ROOT"

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

# Shared substitute/run/fatal-check body (single implementation: issue #193).
source "$REPO_ROOT/sim/harness/lib/run_point.sh"

# One ngspice invocation per PVT point (shared wrapper: issue #211).
run_point() {
  harness_run_pvt_point "$HERE/tb_current_limit.spice.in" "$1" "$2" "$3"
}
export -f run_point corner_sections harness_run_point harness_run_pvt_point
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
