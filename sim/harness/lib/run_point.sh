#!/usr/bin/env bash
# Shared "substitute deck template, run ngspice, check the log for fatal
# lines" driver for the per-PVT-point sweep testbenches:
#
#   sim/current-limit/testbench/run.sh
#   sim/enable-shutdown/testbench/run.sh
#   sim/soft-start/testbench/run.sh
#
# These three testbenches (deliberately standalone rather than
# sim/harness/ fragments -- see their own headers) each drove an
# independent copy of the same substitute/run/fatal-check body. This file
# is the single implementation, following the same shape as
# sim/devchar/lib/devchar.sh's dc_run() but generalized with an explicit
# deck/log path pair instead of dc_run's build-dir/tag convention: these
# testbenches already compute a per-point `corner_id` used for both the
# deck/log filenames and the fan-out's stdout line, and that computation
# (which varies per script -- soft-start folds a cap/ESR/Rload triple into
# it) is left to each caller.
#
# Usage from a testbench's run.sh:
#
#   source "$REPO_ROOT/sim/harness/lib/run_point.sh"
#   harness_run_point <template> <corner_id> <deck> <log> [KEY=VALUE ...]
#
# Substitutes @KEY@ -> VALUE for each KEY=VALUE pair (in the order given)
# into <template>, writes the result to <deck>, and runs `ngspice -b` on
# it with output captured to <log>. The log is then checked against
# $FATAL_LOG_PATTERN, which the caller must have exported (single source
# of truth: sim/harness/runner.py's FATAL_LOG_PATTERN, issue #157).
#
# On success: echoes <corner_id> to stdout and returns 0.
# On failure: prints a "FATAL: ..." message plus context to stderr and
# returns 1 -- never `exit`, since callers run this function inside an
# `xargs -P "$JOBS"` fan-out where a hard exit would only kill one worker.
harness_run_point() {
  local tmpl="$1" corner_id="$2" deck="$3" log="$4"
  shift 4

  local args=()
  local kv key val
  for kv in "$@"; do
    key="${kv%%=*}"
    val="${kv#*=}"
    args+=("-e" "s|@${key}@|${val}|g")
  done
  sed "${args[@]}" "$tmpl" > "$deck"

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

# Shared per-PVT-point wrapper for the two testbenches whose `corner_id`
# computation is identical -- current-limit and enable-shutdown (issue
# #211). Both take just (corner, temp, vin) with the same
# `<corner>_<temp>c_<vin>v` corner_id format and the same 10-key
# harness_run_point() argument list, differing only in which deck template
# they substitute into. soft-start folds an extra cap/ESR/Rload triple into
# its corner_id (see the file header above) and op-point-sanity does its
# own log-parsing on top, so neither can be folded in here -- this covers
# only the pair that is genuinely identical.
#
# Usage from a testbench's run.sh:
#
#   harness_run_pvt_point <template> <corner> <temp> <vin>
#
# Requires the same exported context as harness_run_point(), plus:
#   WORKDIR, LOG_DIR   -- deck/log output directories
#   corner_sections()  -- sourced from sim/harness/lib/corner_sections.sh
harness_run_pvt_point() {
  local tmpl="$1" corner="$2" temp="$3" vin="$4"
  local sections; sections="$(corner_sections "$corner")"
  read -r s_mos s_res s_bjt s_dio s_mosc s_mimc <<<"$sections"
  local corner_id; corner_id="$(printf '%s_%sc_%.2fv' "$corner" "$temp" "$vin")"
  local deck="$WORKDIR/${corner_id}.spice"
  local log="$LOG_DIR/${corner_id}.log"

  harness_run_point "$tmpl" "$corner_id" "$deck" "$log" \
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
    "VIN_V=$vin"
}
