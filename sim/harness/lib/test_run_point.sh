#!/usr/bin/env bash
# Regression tests for harness_run_point()'s DC-continuation-ladder-
# exhaustion gate (issue #310's pseudo-transient `op` rung check,
# propagated to this standalone-bench driver by issue #317).
#
#   sim/harness/lib/test_run_point.sh
#
# No PDK / real ngspice needed: a stub `ngspice` on PATH emits canned
# output shaped like the already-committed evidence that motivated this
# gate (e.g.
# sim/current-limit/corners/20260816-080440-8e105a0/ff_-40c_3.63v.log --
# append-only, not read by this script, just cited for provenance). Wired
# into sim/selftest.sh's unit-test stage so CI exercises it on every
# push/PR without a PDK, mirroring sim/tests/test_harness.py's
# RunPointLadderGateTests / RunNgspiceDeckLadderGateTests (issue #310).
#
# Deliberately does NOT hand-port the ladder-exhaustion / transient-
# analysis regexes to bash: harness_run_point() shells out to
# sim/harness/runner.py's own _ladder_exhaustion_lines() /
# _runs_transient_analysis() (see run_point.sh's own comments), so this
# test is exercising the real single source of truth, not a bash copy of
# it.

set -uo pipefail   # deliberately NOT -e: several cases assert a non-zero
                    # return from harness_run_point().

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILURES=0
ok() { echo "ok - $1"; }
not_ok() { echo "not ok - $1"; FAILURES=$((FAILURES + 1)); }

# --- stub ngspice: ignore the deck, emit whatever $FAKE_NGSPICE_LOG holds --
mkdir -p "$WORK/bin"
cat > "$WORK/bin/ngspice" <<'STUB'
#!/usr/bin/env bash
cat "$FAKE_NGSPICE_LOG"
exit 0
STUB
chmod +x "$WORK/bin/ngspice"
export PATH="$WORK/bin:$PATH"

# Same FATAL_LOG_PATTERN a real caller's harness_discover_pdk() would
# export -- pulled the same way (single source of truth, issue #157).
FATAL_LOG_PATTERN="$(python3 - "$REPO_ROOT" <<'PYEOF'
import sys

sys.path.insert(0, sys.argv[1] + "/sim")
from harness.runner import FATAL_LOG_PATTERN

print(FATAL_LOG_PATTERN)
PYEOF
)"
export FATAL_LOG_PATTERN

# shellcheck source=./run_point.sh
source "$REPO_ROOT/sim/harness/lib/run_point.sh"

# --- fixture decks -----------------------------------------------------

cat > "$WORK/op_only.spice.in" <<'EOF'
* op-only DC-solve deck (fixture)
.options temp=@TEMP_C@
op
print v(a)
.end
EOF

cat > "$WORK/tran.spice.in" <<'EOF'
* .tran deck (fixture)
.options temp=@TEMP_C@
tran 1u 9m
.end
EOF

# --- fixture logs --------------------------------------------------------

# Shaped like the committed corpus (issue #310's own citation): source
# stepping fails and ngspice falls through to the pseudo-transient rung.
cat > "$WORK/ladder_exhausted.log" <<'EOF'
Note: Starting source stepping
Warning: source stepping failed
Note: Transient op started
Note: Transient op finished successfully
m_iq_en_ua = -137.99
EOF

# Converged on the first-guess Newton pass -- no ladder phrases at all.
cat > "$WORK/clean.log" <<'EOF'
m_iq_en_ua = 12.50
EOF

# Needed continuation, but a shallower rung solved it -- #301's
# marginality signal, not #310's broken-evidence one.
cat > "$WORK/source_stepping_completed.log" <<'EOF'
Note: Starting dynamic gmin stepping
Warning: Dynamic gmin stepping failed
Note: Starting true gmin stepping
Warning: True gmin stepping failed
Note: Starting source stepping
Note: Source stepping completed
m_iq_en_ua = 11.80
EOF

# NOTE on FAKE_NGSPICE_LOG=... placement: it must be a *prefix* on the same
# simple-command word as the invoked function (`FAKE_NGSPICE_LOG=x fn ...`),
# not a separate assignment statement before it (`FAKE_NGSPICE_LOG=x \` on
# its own line, then a bare `out=$(fn ...)` on the next). The latter only
# sets a shell-local variable -- invisible to the real `ngspice` executable
# the stub replaces, since an external program only inherits *exported*
# environment, and a prefix assignment is the one form that is temporarily
# exported for the single command it precedes (including any process that
# command execs), without polluting the rest of this script.

# --- T1: op-only deck + ladder-exhausted log -> FAILS ---------------------
out="$(FAKE_NGSPICE_LOG="$WORK/ladder_exhausted.log" \
  harness_run_point "$WORK/op_only.spice.in" t1 "$WORK/t1.spice" "$WORK/t1.log" "TEMP_C=27" 2>"$WORK/t1.err")"
rc=$?
if [ "$rc" -ne 0 ] && grep -q "pseudo-transient" "$WORK/t1.err"; then
  ok "T1: op-only deck + ladder-exhausted log fails, naming the pseudo-transient rung"
else
  not_ok "T1: op-only deck + ladder-exhausted log fails (rc=$rc, stderr: $(cat "$WORK/t1.err"))"
fi

# --- T2: .tran deck + the SAME ladder-exhausted log -> PASSES (exempt) ----
out="$(FAKE_NGSPICE_LOG="$WORK/ladder_exhausted.log" \
  harness_run_point "$WORK/tran.spice.in" t2 "$WORK/t2.spice" "$WORK/t2.log" "TEMP_C=27" 2>"$WORK/t2.err")"
rc=$?
if [ "$rc" -eq 0 ] && [ "$out" = "t2" ]; then
  ok "T2: .tran deck exempts the same ladder-exhausted log (analysis-kind gate)"
else
  not_ok "T2: .tran deck exempts the same ladder-exhausted log (rc=$rc, out=$out, stderr: $(cat "$WORK/t2.err"))"
fi

# --- T3: op-only deck + a clean (direct-solve) log -> PASSES --------------
out="$(FAKE_NGSPICE_LOG="$WORK/clean.log" \
  harness_run_point "$WORK/op_only.spice.in" t3 "$WORK/t3.spice" "$WORK/t3.log" "TEMP_C=27" 2>"$WORK/t3.err")"
rc=$?
if [ "$rc" -eq 0 ] && [ "$out" = "t3" ]; then
  ok "T3: op-only deck + a direct-solve log passes"
else
  not_ok "T3: op-only deck + a direct-solve log passes (rc=$rc, out=$out, stderr: $(cat "$WORK/t3.err"))"
fi

# --- T4: op-only deck that only reached source stepping -> PASSES ---------
out="$(FAKE_NGSPICE_LOG="$WORK/source_stepping_completed.log" \
  harness_run_point "$WORK/op_only.spice.in" t4 "$WORK/t4.spice" "$WORK/t4.log" "TEMP_C=27" 2>"$WORK/t4.err")"
rc=$?
if [ "$rc" -eq 0 ] && [ "$out" = "t4" ]; then
  ok "T4: op-only deck that only needed source stepping (not the pseudo-transient rung) passes"
else
  not_ok "T4: op-only deck that only needed source stepping passes (rc=$rc, out=$out, stderr: $(cat "$WORK/t4.err"))"
fi

# --- T5: the same failure via the REAL xargs fan-out shape -----------------
# The three PVT-sweep callers (current-limit, enable-shutdown, soft-start)
# never call harness_run_point() in-process -- they run it inside
# `xargs -P "$JOBS" -I{} bash -c 'run_point $0'`, a fresh bash process per
# point that only inherits *exported* functions/variables. This gate's own
# state (the repo-root lookup, and the helper function that shells out to
# runner.py) has to survive that boundary or every real caller silently
# loses the check -- this is a regression guard for exactly that failure
# mode, not just the gate logic itself.
run_point() {
  harness_run_point "$WORK/op_only.spice.in" t5 "$WORK/t5.spice" "$WORK/t5.log" "TEMP_C=27"
}
export -f run_point harness_run_point
export WORK FAKE_NGSPICE_LOG="$WORK/ladder_exhausted.log"
printf 'x\n' | xargs -P1 -I{} bash -c 'run_point $0' "{}" >/dev/null 2>"$WORK/t5.err"
xargs_rc=$?
unset FAKE_NGSPICE_LOG
if [ "$xargs_rc" -ne 0 ] && grep -q "pseudo-transient" "$WORK/t5.err"; then
  ok "T5: the gate fires across the real xargs/bash -c fan-out boundary"
else
  not_ok "T5: the gate fires across the real xargs/bash -c fan-out boundary (rc=$xargs_rc, stderr: $(cat "$WORK/t5.err"))"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "PASS: sim/harness/lib/test_run_point.sh (5/5)"
  exit 0
else
  echo "FAIL: sim/harness/lib/test_run_point.sh ($FAILURES failing)"
  exit 1
fi
