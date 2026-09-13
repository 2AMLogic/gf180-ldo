#!/usr/bin/env bash
# Startup / soft-start PVT sweep for design/ldo_core.sch + design/ldo_softstart.sch
# (issue #38).
#
#   ./sim/soft-start/testbench/run.sh                  # full matrix, writes evidence
#   NO_RECORD=1 CORNERS=tt TEMPS=27 SUPPLIES=3.30 CAPS=1u/0.1 \
#       ./sim/soft-start/testbench/run.sh              # single point, writes nothing
#
# Same structure, and the same standalone-rather-than-sim/harness rationale,
# as sim/enable-shutdown/testbench/run.sh and sim/current-limit/testbench/run.sh
# -- see those scripts' headers. Each experiment directory under sim/ is meant
# to be self-contained evidence.
#
# Axes:
#   process   tt ff ss fs sf res_ff res_ss   (bjt_ff / bjt_ss omitted: the
#                                             design has no bipolar devices)
#   temp      -40 27 125 degC
#   supply    2.97 3.30 3.63 V  (3.3 V +/-10%, DR-0002)
#   output    C_eff / ESR pairs from DR-0001's ratified window
#   load      36 ohm (~50 mA, full rated) and 1 Gohm (0 mA external)
#
# The full 7x3x3 PVT matrix is run at the nominal 1 uF / 100 mOhm output and
# the full rated load. The DR-0001 capacitor window and the no-load case are
# then swept over a corner subset that brackets the ramp rate (the fastest and
# slowest resistor/capacitor corner combinations), because inrush and overshoot
# are both capacitor-conditioned and the ramp rate is what conditions them.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPDIR="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$EXPDIR/../.." && pwd)"
SLUG="$(basename "$EXPDIR")"

CORNERS="${CORNERS:-tt ff ss fs sf res_ff res_ss}"
TEMPS="${TEMPS:--40 27 125}"
SUPPLIES="${SUPPLIES:-2.97 3.30 3.63}"
# "C_eff/ESR/Rload" triples for the main matrix.
CAPS="${CAPS:-1u/0.1/36}"
# Extra points: the DR-0001 window corners and the no-load case, over a
# bracketing corner subset.
EXTRA_CORNERS="${EXTRA_CORNERS:-tt ff ss res_ff res_ss}"
EXTRA_TEMPS="${EXTRA_TEMPS:--40 125}"
EXTRA_SUPPLIES="${EXTRA_SUPPLIES:-2.97 3.63}"
EXTRA_CAPS="${EXTRA_CAPS:-0.33u/0.001/36 0.33u/0.5/36 4.7u/0.001/36 4.7u/0.5/36 1u/0.1/1e9}"
JOBS="${JOBS:-8}"

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

run_point() {
  local corner="$1" temp="$2" vin="$3" cap="$4"
  local sections; sections="$(corner_sections "$corner")"
  read -r s_mos s_res s_bjt s_dio s_mosc s_mimc <<<"$sections"
  local cout esr rload
  IFS='/' read -r cout esr rload <<<"$cap"
  local corner_id
  corner_id="$(printf '%s_%sc_%.2fv_%s' "$corner" "$temp" "$vin" "$(echo "$cap" | tr '/' '_')")"
  local deck="$WORKDIR/${corner_id}.spice"
  local log="$LOG_DIR/${corner_id}.log"

  harness_run_point "$HERE/tb_soft_start.spice.in" "$corner_id" "$deck" "$log" \
    "DESIGN_INCLUDE=$DESIGN_INCLUDE" \
    "MODEL_LIB=$MODEL_LIB" \
    "LDO_NETLIST=$LDO_NETLIST" \
    "MOS_CORNER=$s_mos" \
    "RES_CORNER=$s_res" \
    "BJT_CORNER=$s_bjt" \
    "DIODE_CORNER=$s_dio" \
    "MOSCAP_CORNER=$s_mosc" \
    "MIMCAP_CORNER=$s_mimc" \
    "TEMP_C=$temp" \
    "VIN_V=$vin" \
    "COUT=$cout" \
    "ESR_OHM=$esr" \
    "RLOAD_OHM=$rload"
}
export -f run_point corner_sections harness_run_point
export WORKDIR LOG_DIR HERE DESIGN_INCLUDE MODEL_LIB LDO_NETLIST FATAL_LOG_PATTERN

points=()
for c in $CORNERS; do for t in $TEMPS; do for v in $SUPPLIES; do for k in $CAPS; do
  points+=("$c $t $v $k")
done; done; done; done
for c in $EXTRA_CORNERS; do for t in $EXTRA_TEMPS; do for v in $EXTRA_SUPPLIES; do for k in $EXTRA_CAPS; do
  points+=("$c $t $v $k")
done; done; done; done

printf '%s\n' "${points[@]}" \
  | xargs -P "$JOBS" -I{} bash -c 'run_point $0' "{}" \
  | sort

CSV="$LOG_DIR/summary.csv"
python3 "$HERE/summarize.py" "$LOG_DIR" "$CSV"

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
