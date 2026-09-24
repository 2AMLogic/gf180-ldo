#!/usr/bin/env bash
# Shared driver helpers for the gf180mcu device-characterization decks.
#
# Every deck in sim/devchar is a *template* (`*.sp.in`) containing @TOKENS@ that
# this library substitutes to produce a concrete, runnable ngspice deck in a
# scratch build directory. Keeping deck / corner-loop / results separate is
# deliberate so the decks can later be folded into the shared sim harness (#2)
# without rewriting them.
#
# Usage from a deck directory's run.sh:
#
#   source "$(dirname "$0")/../lib/devchar.sh"
#   dc_init
#   dc_run <template.sp.in> <output.csv> KEY=VALUE ...
#
# Environment:
#   PDK_ROOT  - defaults to $HOME/.volare
#   PDK       - defaults to gf180mcuD
#   DC_KEEP   - if set, generated decks are left in the build dir for inspection

set -euo pipefail

: "${PDK_ROOT:=$HOME/.volare}"
: "${PDK:=gf180mcuD}"

DC_MODELS=""
DC_BUILD=""
DC_ROOT=""
DC_FATAL_LOG_PATTERN=""

dc_init() {
  DC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  DC_MODELS="$PDK_ROOT/$PDK/libs.tech/ngspice"
  DC_BUILD="$DC_ROOT/.build"

  if [ ! -f "$DC_MODELS/sm141064.ngspice" ]; then
    echo "FATAL: gf180mcu ngspice models not found at $DC_MODELS" >&2
    echo "       set PDK_ROOT (currently '$PDK_ROOT') to the volare install root" >&2
    exit 1
  fi
  if ! command -v ngspice >/dev/null 2>&1; then
    echo "FATAL: ngspice not on PATH" >&2
    exit 1
  fi
  mkdir -p "$DC_BUILD"

  # Fatal-condition sentinel: single source of truth is
  # sim/harness/runner.py's FATAL_LOG_PATTERN (issue #157).
  DC_FATAL_LOG_PATTERN="$(python3 - "$DC_ROOT" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1] + "/..")
from harness.runner import FATAL_LOG_PATTERN
print(FATAL_LOG_PATTERN)
EOF
)"
}

# Fails <deck>/<log> against issue #310's DC-continuation-ladder-exhaustion
# gate -- dc_run() below calls this on every deck it runs, mirroring the
# gate issue #317 added to sim/harness/lib/run_point.sh's
# harness_run_point(). Every devchar deck is an `op`/`dc`
# device-characterization sweep with no `.tran` analysis (checked as of
# this commit -- see that gate's own analysis-kind exemption), so this
# always evaluates the ladder-exhaustion phrases in practice today; the
# exemption check still runs per-deck rather than being hardcoded away, so
# a future `.tran` devchar deck stays correctly exempt without anyone
# having to remember this comment.
#
# Shells out to sim/harness/runner.py's own
# _runs_transient_analysis()/_ladder_exhaustion_lines() rather than porting
# their regexes to bash ERE, so this copy and run_point.sh's cannot drift
# from runner.py or from each other.
#
# Prints the matched offender line(s) to stdout and returns 1 when the
# ladder was exhausted on a non-`.tran` deck; returns 0 (no output)
# otherwise.
_dc_ladder_exhaustion_check() {
  local deck="$1" log="$2"
  python3 - "$DC_ROOT" "$deck" "$log" <<'PYEOF'
import sys

sys.path.insert(0, sys.argv[1] + "/..")
from harness.runner import _ladder_exhaustion_lines, _runs_transient_analysis

deck_text = open(sys.argv[2]).read()
if _runs_transient_analysis(deck_text):
    sys.exit(0)

log_text = open(sys.argv[3]).read()
exhausted = _ladder_exhaustion_lines(log_text)
if not exhausted:
    sys.exit(0)
for line in exhausted:
    print(line)
sys.exit(1)
PYEOF
}

# dc_csv_header <outfile> <header-line>
# Truncates the CSV and writes the header. Provenance lives in the sibling
# README / conclusions, not in the CSV, so the files stay machine-readable.
dc_csv_header() {
  local out="$1"; shift
  mkdir -p "$(dirname "$out")"
  printf '%s\n' "$1" > "$out"
}

# dc_run <template> <outfile> KEY=VALUE ...
# Substitutes @KEY@ -> VALUE (plus the always-available @MODELS@ / @OUT@) and
# runs ngspice in batch mode. The deck itself appends rows to @OUT@.
dc_run() {
  local tmpl="$1"; shift
  local out="$1"; shift

  local tag
  tag="$(basename "$tmpl" .sp.in)"
  local args=("-e" "s|@MODELS@|$DC_MODELS|g" "-e" "s|@OUT@|$out|g")
  local kv key val
  for kv in "$@"; do
    key="${kv%%=*}"
    val="${kv#*=}"
    tag="${tag}_${val}"
    args+=("-e" "s|@${key}@|${val}|g")
  done
  tag="$(printf '%s' "$tag" | tr -c 'A-Za-z0-9._-' '_')"

  local deck="$DC_BUILD/${tag}.sp"
  sed "${args[@]}" "$tmpl" > "$deck"

  local log="$DC_BUILD/${tag}.log"
  if ! ngspice -b "$deck" > "$log" 2>&1; then
    echo "FATAL: ngspice failed on $deck (see $log)" >&2
    tail -30 "$log" >&2
    exit 1
  fi
  # ngspice reports model-selection and convergence problems on stdout while
  # still exiting 0 - treat those as hard failures so a broken corner can never
  # silently produce a plausible-looking table.
  if grep -qE "$DC_FATAL_LOG_PATTERN" "$log"; then
    echo "FATAL: ngspice reported an error on $deck (see $log)" >&2
    grep -nE "$DC_FATAL_LOG_PATTERN" "$log" >&2
    exit 1
  fi
  local ladder_offenders
  if ! ladder_offenders="$(_dc_ladder_exhaustion_check "$deck" "$log")"; then
    echo "FATAL: ngspice exhausted its DC continuation ladder on $deck and fell back to the pseudo-transient op; the reported operating point is an unsettled transient snapshot, not a converged DC solution (see $log)" >&2
    printf '%s\n' "$ladder_offenders" >&2
    exit 1
  fi
  if [ -z "${DC_KEEP:-}" ]; then
    rm -f "$deck" "$log"
  fi
}

# Corner / PVT matrices shared by every deck (issue #4 acceptance criteria).
DC_FET_CORNERS=(typical ff ss fs sf)
DC_RES_CORNERS=(res_typical res_ff res_ss)
DC_MIM_CORNERS=(mimcap_typical mimcap_ff mimcap_ss)
DC_MOSCAP_CORNERS=(moscap_typical moscap_ff moscap_ss)
DC_TEMPS=(-40 27 125)
DC_VINS=(2.97 3.30 3.63)
# The binding dropout test point is Vin = Vout + dropout, not Vin_min: at the
# 300 mV / 1.8 V operating point the pass device only has 2.10 V of Vsg, well
# below the 2.97 V supply floor (spec/architecture-survey.md section 3.1).
DC_VINS_DROPOUT=(2.10)
# Mid-voltage (5 V input stretch, see #7) supply set
DC_VINS_MV=(4.50 5.00 5.50)
