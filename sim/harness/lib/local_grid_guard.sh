# shellcheck shell=bash
# Refuse a multi-point local ngspice fan-out unless it was asked for by name
# (issue #366).
#
# On a shared dispatch worker a PVT grid must go to the Spot batch fleet as a
# `klt sim` request (sim/harness/klt_batch.py), not fan out here. The bash
# drivers still can only run locally, so a grid of more than one point is
# refused unless the caller says BACKEND=local: that is a deliberate choice
# to run it on a host the caller owns, never a silent default. A single point
# (a debug probe) needs no flag.
#
# Usage (after the point list is built, before the first ngspice):
#   source "$REPO_ROOT/sim/harness/lib/local_grid_guard.sh"
#   harness_local_grid_guard "${#points[@]}" "<what to use instead>"
#
# The default worker count, `${JOBS:-2}` in each driver, is deliberately not
# nproc: the dispatch workers are shared. Raise it with JOBS=N on a box you own.

harness_local_grid_guard() {
  local n="$1" instead="$2"
  if [ "$n" -gt 1 ] && [ "${BACKEND:-}" != "local" ]; then
    {
      echo "FATAL: this grid is $n PVT points, which would fan out ngspice on this host."
      echo "       Multi-corner grids belong on the batch fleet: $instead"
      echo "       On a host you own, re-run with BACKEND=local (default JOBS=2)."
    } >&2
    return 3
  fi
}
