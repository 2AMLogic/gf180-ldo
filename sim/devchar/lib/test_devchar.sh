#!/usr/bin/env bash
# Regression tests for devchar.sh's DC-continuation-ladder-exhaustion gate
# (issue #310's pseudo-transient `op` rung check, propagated to this
# standalone driver by issue #317 -- the same gate sim/harness/lib/
# test_run_point.sh exercises for run_point.sh's harness_run_point()).
#
#   sim/devchar/lib/test_devchar.sh
#
# Exercises _dc_ladder_exhaustion_check() directly rather than the full
# dc_run()/dc_init() path: dc_init() hard-fails without a real gf180mcu PDK
# install and a real `ngspice` on PATH (by design -- devchar's own decks
# need the real device models, unlike the PVT-sweep benches), which this
# repo's CI deliberately does not provision (see .github/workflows/ci.yml's
# "Explicitly excluded from CI" note). _dc_ladder_exhaustion_check() itself
# needs neither: it only reads a deck/log file pair and shells out to
# sim/harness/runner.py's pure-Python _ladder_exhaustion_lines() /
# _runs_transient_analysis(), so it is testable standalone.

set -uo pipefail   # deliberately NOT -e: several cases assert a non-zero
                    # return from _dc_ladder_exhaustion_check().

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILURES=0
ok() { echo "ok - $1"; }
not_ok() { echo "not ok - $1"; FAILURES=$((FAILURES + 1)); }

# shellcheck source=./devchar.sh
source "$HERE/devchar.sh"
# devchar.sh's own module-scope `set -euo pipefail` runs in THIS shell (a
# `source`, not a subshell) and turning `-o pipefail`/`-u` back on does not
# clear `-e` -- it has to be turned off explicitly, or every assertion
# below that expects a non-zero return aborts this script on the first one.
set +e
set -uo pipefail

# _dc_ladder_exhaustion_check() reads $DC_ROOT to locate sim/ for its
# `from harness.runner import ...` -- set it the same way dc_init() does
# (which sourcing devchar.sh above reset to "" -- it must be set AFTER the
# source, not before), without dc_init()'s PDK/ngspice hard checks.
DC_ROOT="$(cd "$HERE/.." && pwd)"

# --- fixture decks -------------------------------------------------------

cat > "$WORK/op_only.sp" <<'EOF'
* op-only DC-solve deck (fixture)
.options temp=27
op
print v(a)
.end
EOF

cat > "$WORK/tran.sp" <<'EOF'
* .tran deck (fixture)
.options temp=27
tran 1u 9m
.end
EOF

# --- fixture logs ---------------------------------------------------------

cat > "$WORK/ladder_exhausted.log" <<'EOF'
Note: Starting source stepping
Warning: source stepping failed
Note: Transient op started
Note: Transient op finished successfully
vth = -1.2345
EOF

cat > "$WORK/clean.log" <<'EOF'
vth = -0.6789
EOF

# --- T1: op-only deck + ladder-exhausted log -> FAILS ---------------------
out="$(_dc_ladder_exhaustion_check "$WORK/op_only.sp" "$WORK/ladder_exhausted.log" 2>"$WORK/t1.err")"
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -qi "transient op"; then
  ok "T1: op-only deck + ladder-exhausted log fails, naming the offending line"
else
  not_ok "T1: op-only deck + ladder-exhausted log fails (rc=$rc, out=$out)"
fi

# --- T2: .tran deck + the SAME ladder-exhausted log -> PASSES (exempt) ----
out="$(_dc_ladder_exhaustion_check "$WORK/tran.sp" "$WORK/ladder_exhausted.log" 2>"$WORK/t2.err")"
rc=$?
if [ "$rc" -eq 0 ]; then
  ok "T2: .tran deck exempts the same ladder-exhausted log (analysis-kind gate)"
else
  not_ok "T2: .tran deck exempts the same ladder-exhausted log (rc=$rc, out=$out)"
fi

# --- T3: op-only deck + a clean (direct-solve) log -> PASSES --------------
out="$(_dc_ladder_exhaustion_check "$WORK/op_only.sp" "$WORK/clean.log" 2>"$WORK/t3.err")"
rc=$?
if [ "$rc" -eq 0 ]; then
  ok "T3: op-only deck + a direct-solve log passes"
else
  not_ok "T3: op-only deck + a direct-solve log passes (rc=$rc, out=$out)"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "PASS: sim/devchar/lib/test_devchar.sh (3/3)"
  exit 0
else
  echo "FAIL: sim/devchar/lib/test_devchar.sh ($FAILURES failing)"
  exit 1
fi
