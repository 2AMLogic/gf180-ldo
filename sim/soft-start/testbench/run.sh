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
# `${VAR-default}`, NOT `${VAR:-default}`, on all four: an explicitly EMPTY
# value has to mean "run no extra points", and the colon form silently
# re-expands the default for it. A single-point debug or netlist-A/B run is
# the normal reason to want that, and getting 100 extra points instead is
# both slow and easy to miss (issue #246 lost a run to exactly this).
EXTRA_CORNERS="${EXTRA_CORNERS-tt ff ss res_ff res_ss}"
EXTRA_TEMPS="${EXTRA_TEMPS--40 125}"
EXTRA_SUPPLIES="${EXTRA_SUPPLIES-2.97 3.63}"
EXTRA_CAPS="${EXTRA_CAPS-0.33u/0.001/36 0.33u/0.5/36 4.7u/0.001/36 4.7u/0.5/36 1u/0.1/1e9}"
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
# The DUT netlist. Overridable ONLY so that a same-host, same-binary A/B
# against a frozen `netlist-snapshots/<record-id>.spice` is reproducible --
# the comparison every record of this bench that attributes a change to the
# schematic has had to make, and which up to issue #246 was made with an
# uncommitted one-off script (see 20260915-103035-18f664f.md's "Pre-existing
# #191 regression" section, which says so). Cross-record comparison is not a
# safe substitute: records minted weeks apart can carry different ngspice
# binaries, and this bench's numbers are large-signal transient peaks.
#
#   NO_RECORD=1 LDO_NETLIST=sim/soft-start/netlist-snapshots/<id>.spice \
#     CORNERS=tt TEMPS=27 SUPPLIES=3.30 CAPS=1u/0.1/36 \
#     EXTRA_CORNERS= EXTRA_CAPS= ./sim/soft-start/testbench/run.sh
#
# Evidence runs MUST leave it unset: `design/netlist.py --check` above
# guarantees the default is the schematics' own export, and an override
# breaks that guarantee -- which is why the override is refused unless
# NO_RECORD is set.
if [ -n "${LDO_NETLIST:-}" ] && [ -z "${NO_RECORD:-}" ]; then
  echo "refusing to mint a record with an overridden LDO_NETLIST" >&2
  echo "(set NO_RECORD=1 -- an evidence record must be the committed export)" >&2
  exit 1
fi
LDO_NETLIST="${LDO_NETLIST:-$REPO_ROOT/design/netlist/ldo_core.spice}"

RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
LOG_DIR="$EXPDIR/corners/$RECORD_ID"
# The record id has one-second resolution, so two invocations started in the
# same second on the same commit collide -- and the collision is SILENT and
# corrupting: both write per-corner logs into one directory and whichever
# summarize.py runs last rolls up the union, attributing the other run's
# points to this run's netlist. That is not hypothetical; issue #246 hit it
# running ten single-point netlist-A/B invocations in parallel (the use case
# the LDO_NETLIST override above exists for). Refuse rather than merge --
# `mkdir` without `-p` is atomic, so this is a race-free check, and the
# caller only has to wait a second.
if ! mkdir "$LOG_DIR" 2>/dev/null; then
  echo "record id $RECORD_ID is already taken ($LOG_DIR exists)" >&2
  echo "(two runs in the same second on the same commit -- retry in 1 s)" >&2
  exit 1
fi
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

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
