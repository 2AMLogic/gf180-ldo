#!/usr/bin/env bash
# Regression tests for harness_local_grid_guard() (issue #366): a multi-point
# local ngspice grid is refused unless BACKEND=local, a single point is not,
# and the three bash drivers default to 2 local jobs.
#
#   sim/harness/lib/test_local_grid_guard.sh
#
# No PDK / ngspice needed. Wired into sim/selftest.sh's shell-driver stage.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
source "$HERE/local_grid_guard.sh"

FAILURES=0
check() {  # check <name> <expected-rc> <actual-rc>
  if [ "$2" = "$3" ]; then echo "  ok   $1"; else echo "  FAIL $1 (want rc=$2, got rc=$3)"; FAILURES=$((FAILURES+1)); fi
}

( unset BACKEND; harness_local_grid_guard 63 "use klt" 2>/dev/null ); check "grid, no BACKEND: refused" 3 $?
( export BACKEND=batch; harness_local_grid_guard 63 "use klt" 2>/dev/null ); check "grid, BACKEND=batch: refused" 3 $?
( export BACKEND=local; harness_local_grid_guard 63 "use klt" 2>/dev/null ); check "grid, BACKEND=local: allowed" 0 $?
( unset BACKEND; harness_local_grid_guard 1 "use klt" 2>/dev/null ); check "single point, no BACKEND: allowed" 0 $?
msg="$( unset BACKEND; harness_local_grid_guard 63 "use klt" 2>&1 )"
case "$msg" in *"63 PVT points"*"use klt"*"BACKEND=local"*) rc=0 ;; *) rc=1 ;; esac
check "refusal names the grid size, the alternative and the opt-in" 0 $rc

for slug in current-limit enable-shutdown soft-start; do
  d="$REPO_ROOT/sim/$slug/testbench/run.sh"
  grep -q '^JOBS="${JOBS:-2}"' "$d"; check "$slug: default JOBS is 2" 0 $?
  grep -q 'harness_local_grid_guard' "$d"; check "$slug: calls the guard" 0 $?
done

if [ "$FAILURES" -eq 0 ]; then
  echo "PASS: sim/harness/lib/test_local_grid_guard.sh"
else
  echo "FAIL: sim/harness/lib/test_local_grid_guard.sh ($FAILURES failing)"; exit 1
fi
