#!/usr/bin/env bash
# Enable / shutdown PVT sweep for design/ldo_core.sch + design/ldo_ilimit.sch
# (issue #11).
#
#   ./sim/enable-shutdown/testbench/run.sh             # full matrix, writes evidence
#   NO_RECORD=1 CORNERS=tt TEMPS=27 SUPPLIES=3.30 \
#       ./sim/enable-shutdown/testbench/run.sh         # single point, writes nothing
#
# Same structure, and the same standalone-rather-than-sim/harness rationale,
# as sim/current-limit/testbench/run.sh -- see that script's header. Each
# experiment directory under sim/ remains a self-contained deck / corner
# matrix / evidence set; only the low-level "substitute deck template, run
# ngspice, check for fatal log lines" mechanics are shared, via
# sim/harness/lib/run_point.sh (issue #193), since that body had drifted
# into three near-identical copies with no behavioral difference to
# preserve.
#
# Corner matrix:
#   process   tt ff ss fs sf res_ff res_ss   (bjt_ff / bjt_ss omitted: the
#                                             design has no bipolar devices)
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
  harness_run_pvt_point "$HERE/tb_enable_shutdown.spice.in" "$1" "$2" "$3"
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
