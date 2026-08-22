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

PDK_INFO="$(python3 - "$REPO_ROOT" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1] + "/sim")
from harness.pdk import find_pdk
pdk = find_pdk()
print(pdk.design_include)
print(pdk.model_lib)
print(pdk.variant)
print(pdk.version)
EOF
)"
DESIGN_INCLUDE="$(sed -n '1p' <<<"$PDK_INFO")"
MODEL_LIB="$(sed -n '2p' <<<"$PDK_INFO")"
PDK_VARIANT="$(sed -n '3p' <<<"$PDK_INFO")"
PDK_VERSION="$(sed -n '4p' <<<"$PDK_INFO")"

command -v ngspice >/dev/null 2>&1 || { echo "FATAL: ngspice not on PATH" >&2; exit 1; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n 's/^\*\* \(ngspice-[0-9.]*\).*/\1/p' | head -1)"

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

# "1u/0.1/36" -> "1u_0.1_36" with the dots kept out of the field separators.
cap_tag() { echo "$1" | tr '/' '_'; }

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
    -e "s|@COUT@|$cout|g" \
    -e "s|@ESR_OHM@|$esr|g" \
    -e "s|@RLOAD_OHM@|$rload|g" \
    "$HERE/tb_soft_start.spice.in" > "$deck"

  if ! ngspice -b "$deck" > "$log" 2>&1; then
    echo "FATAL: ngspice failed on $corner_id (see $log)" >&2
    tail -40 "$log" >&2
    return 1
  fi
  if grep -qE 'could not find a valid modelname|Simulation interrupted|singular matrix|no convergence|iteration limit reached|fatal error|no such vector' "$log"; then
    echo "FATAL: ngspice reported an error on $corner_id (see $log)" >&2
    grep -nE 'could not find a valid modelname|Simulation interrupted|singular matrix|no convergence|iteration limit reached|fatal error|no such vector' "$log" >&2
    return 1
  fi
  echo "$corner_id"
}
export -f run_point corner_sections
export WORKDIR LOG_DIR HERE DESIGN_INCLUDE MODEL_LIB LDO_NETLIST

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
