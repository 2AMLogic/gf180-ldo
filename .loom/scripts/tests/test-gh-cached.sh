#!/usr/bin/env bash
# test-gh-cached.sh - Unit tests for .loom/scripts/gh-cached's repo-scoped
# cache keys (issue #30) plus regression coverage for the surrounding cache
# semantics those keys must not disturb.
#
# The bug: cache_key() hashed only the joined `gh` argument list, while
# CACHE_DIR defaults to a single machine-wide /tmp/gh-cache shared by every
# repo and session on the host. `gh` infers its target repository from the
# working directory, and the cwd was nowhere in the key -- so two different
# repos issuing the identical `gh` command produced the identical key, and a
# cache entry written by one repo's session was served verbatim to another's.
# Observed live: `gh-cached pr list --label=loom:review-requested` run in
# gf180-ldo returned a PR belonging to an unrelated repository.
#
# These are black-box tests: gh-cached is a standalone CLI, so we stub `gh`
# on PATH with a script that echoes a payload naming the repo it resolved
# from cwd (exactly the ambient state the key must account for), point
# GH_CACHE_DIR at a temp directory, and invoke the real wrapper as a
# subprocess from several temp repos. Fully hermetic: no network, no live
# forge, no tokens.
#
# Usage:
#   ./.loom/scripts/tests/test-gh-cached.sh

set -uo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$TEST_DIR/.." && pwd)"
GH_CACHED="$SCRIPTS_DIR/gh-cached"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

pass() {
    TESTS_RUN=$((TESTS_RUN + 1))
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo -e "  ${GREEN}PASS${NC}: $1"
}

fail() {
    TESTS_RUN=$((TESTS_RUN + 1))
    TESTS_FAILED=$((TESTS_FAILED + 1))
    echo -e "  ${RED}FAIL${NC}: $1"
    shift
    for line in "$@"; do echo "    $line"; done
}

assert_eq() {
    local expected="$1" actual="$2" msg="$3"
    if [[ "$expected" == "$actual" ]]; then
        pass "$msg"
    else
        fail "$msg" "Expected: '$expected'" "Actual:   '$actual'"
    fi
}

assert_ne() {
    local unexpected="$1" actual="$2" msg="$3"
    if [[ "$unexpected" != "$actual" ]]; then
        pass "$msg"
    else
        fail "$msg" "Expected anything but: '$unexpected'"
    fi
}

assert_contains() {
    local haystack="$1" needle="$2" msg="$3"
    if printf '%s' "$haystack" | grep -qF -- "$needle"; then
        pass "$msg"
    else
        fail "$msg" "Expected substring: '$needle'" "In: '$haystack'"
    fi
}

# ─── Environment checks ──────────────────────────────────────────────────────

if [[ ! -x "$GH_CACHED" ]]; then
    echo "SKIP: $GH_CACHED not found or not executable"
    exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "SKIP: python3 not available"
    exit 0
fi
if ! command -v git >/dev/null 2>&1; then
    echo "SKIP: git not available"
    exit 0
fi

# ─── Harness ─────────────────────────────────────────────────────────────────

TMP_ROOT="$(mktemp -d 2>/dev/null || mktemp -d -t gh-cached)"
trap 'rm -rf "$TMP_ROOT"' EXIT

CACHE_DIR="$TMP_ROOT/cache"
STUB_DIR="$TMP_ROOT/bin"
export GH_CALL_LOG="$TMP_ROOT/gh-calls.log"
mkdir -p "$STUB_DIR"
: > "$GH_CALL_LOG"

# Stub `gh`: logs every real invocation (so we can tell a HIT from a MISS)
# and emits a payload naming the repo it would resolve from cwd. If the cache
# key is not repo-scoped, one repo's payload leaks into another's session.
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${GH_CALL_LOG:-/dev/null}"
remote="$(git remote get-url origin 2>/dev/null || true)"
printf 'PAYLOAD-FOR:%s\n' "${remote:-NO-REMOTE}"
STUB
chmod +x "$STUB_DIR/gh"
export PATH="$STUB_DIR:$PATH"

# Keep the ambient environment from leaking into scope resolution.
unset GH_CACHE_SCOPE GH_REPO GH_CACHE_DISABLE

make_repo() { # <dir> <origin-url>
    mkdir -p "$1"
    git -C "$1" init -q >/dev/null 2>&1
    git -C "$1" remote add origin "$2"
}

run_cached() { # <cwd> [gh args...]
    local dir="$1"; shift
    (cd "$dir" && GH_CACHE_DIR="$CACHE_DIR" "$GH_CACHED" "$@" 2>/dev/null)
}

gh_calls() { wc -l < "$GH_CALL_LOG" | tr -d ' '; }

cache_entries() { # count real entries (excludes the _stats.json sidecar)
    find "$CACHE_DIR" -maxdepth 1 -name '*.json' ! -name '_*' 2>/dev/null | wc -l | tr -d ' '
}

REPO_A="$TMP_ROOT/alpha"
REPO_B="$TMP_ROOT/beta"
REPO_A_SSH="$TMP_ROOT/alpha-ssh"
REPO_NO_REMOTE="$TMP_ROOT/no-remote"
PLAIN_DIR="$TMP_ROOT/plain"

make_repo "$REPO_A" "https://github.com/acme/alpha.git"
make_repo "$REPO_B" "https://github.com/acme/beta.git"
make_repo "$REPO_A_SSH" "git@github.com:acme/alpha.git"
mkdir -p "$REPO_NO_REMOTE" && git -C "$REPO_NO_REMOTE" init -q >/dev/null 2>&1
mkdir -p "$PLAIN_DIR"

# ─── Test 1: cross-repo isolation (the reported bug) ─────────────────────────

echo ""
echo "Test 1: identical gh args from two different repos do not share a cache entry"

out_a="$(run_cached "$REPO_A" issue list --state open)"
out_b="$(run_cached "$REPO_B" issue list --state open)"

assert_contains "$out_a" "acme/alpha" "first repo gets its own result"
assert_contains "$out_b" "acme/beta" "second repo gets ITS OWN result, not the first repo's"
assert_ne "$out_a" "$out_b" "the two repos' results differ (no cross-repo contamination)"
assert_eq "2" "$(gh_calls)" "both invocations reached the real gh (neither was a false HIT)"
assert_eq "2" "$(cache_entries)" "two distinct cache entries were written"

# ─── Test 2: same-repo caching is unchanged ──────────────────────────────────

echo ""
echo "Test 2: repeating a command in the SAME repo still hits the cache"

before="$(gh_calls)"
out_a2="$(run_cached "$REPO_A" issue list --state open)"
assert_eq "$out_a" "$out_a2" "repeated call returns the cached payload"
assert_eq "$before" "$(gh_calls)" "repeated call did not re-invoke gh (cache HIT)"

# ─── Test 3: transport-equivalent remotes share one entry ────────────────────

echo ""
echo "Test 3: ssh and https forms of the same remote resolve to the same scope"

before="$(gh_calls)"
out_a_ssh="$(run_cached "$REPO_A_SSH" issue list --state open)"
assert_eq "$out_a" "$out_a_ssh" "git@github.com:acme/alpha.git hits the https clone's entry"
assert_eq "$before" "$(gh_calls)" "no extra gh call for the transport-equivalent clone"

# ─── Test 4: explicit scope overrides ────────────────────────────────────────

echo ""
echo "Test 4: GH_CACHE_SCOPE and GH_REPO participate in the key"

before="$(gh_calls)"
scoped="$(cd "$REPO_A" && GH_CACHE_DIR="$CACHE_DIR" GH_CACHE_SCOPE="custom-scope" \
    "$GH_CACHED" issue list --state open 2>/dev/null)"
assert_eq "$((before + 1))" "$(gh_calls)" "GH_CACHE_SCOPE override misses repo A's entry"
assert_contains "$scoped" "PAYLOAD-FOR:" "GH_CACHE_SCOPE override still returns a result"

before="$(gh_calls)"
(cd "$REPO_A" && GH_CACHE_DIR="$CACHE_DIR" GH_REPO="acme/gamma" \
    "$GH_CACHED" issue list --state open >/dev/null 2>&1)
assert_eq "$((before + 1))" "$(gh_calls)" "GH_REPO override misses repo A's entry"

# ─── Test 5: safe fallback outside a git repo ────────────────────────────────

echo ""
echo "Test 5: degrades safely when the cwd has no origin remote / no git repo"

out_nr="$(run_cached "$REPO_NO_REMOTE" issue list --state open)"
rc_nr=$?
assert_eq "0" "$rc_nr" "git repo without an origin remote still exits 0"
assert_contains "$out_nr" "PAYLOAD-FOR:" "git repo without an origin remote still passes through"

out_plain="$(run_cached "$PLAIN_DIR" issue list --state open)"
rc_plain=$?
assert_eq "0" "$rc_plain" "non-git directory still exits 0 (no crash)"
assert_contains "$out_plain" "PAYLOAD-FOR:" "non-git directory still passes through to gh"

# ─── Test 6: --no-cache / --clear-cache / --cache-stats unchanged ────────────

echo ""
echo "Test 6: wrapper meta-flags keep their documented semantics"

before="$(gh_calls)"
run_cached "$REPO_A" --no-cache issue list --state open >/dev/null
assert_eq "$((before + 1))" "$(gh_calls)" "--no-cache bypasses a warm entry"

stats="$( (cd "$REPO_A" && GH_CACHE_DIR="$CACHE_DIR" "$GH_CACHED" --cache-stats 2>&1) )"
assert_contains "$stats" "Hit rate:" "--cache-stats still reports a hit rate"

(cd "$REPO_A" && GH_CACHE_DIR="$CACHE_DIR" "$GH_CACHED" --clear-cache >/dev/null 2>&1)
assert_eq "0" "$(cache_entries)" "--clear-cache still removes every entry"

# ─── Test 7: mutation invalidation still works ───────────────────────────────

echo ""
echo "Test 7: a mutation still invalidates the matching cached read"

run_cached "$REPO_A" issue view 42 --json labels >/dev/null
before="$(gh_calls)"
run_cached "$REPO_A" issue view 42 --json labels >/dev/null
assert_eq "$before" "$(gh_calls)" "issue view 42 is cached before the mutation"

run_cached "$REPO_A" issue edit 42 --add-label "loom:building" >/dev/null
before="$(gh_calls)"
run_cached "$REPO_A" issue view 42 --json labels >/dev/null
assert_eq "$((before + 1))" "$(gh_calls)" "issue edit 42 invalidated the cached view"

# ─── Test 8: TTL expiry still works ──────────────────────────────────────────

echo ""
echo "Test 8: GH_CACHE_TTL expiry still evicts stale entries"

# `release list` has no TTL_BY_COMMAND override, so GH_CACHE_TTL applies.
(cd "$REPO_A" && GH_CACHE_DIR="$CACHE_DIR" GH_CACHE_TTL=1 "$GH_CACHED" release list >/dev/null 2>&1)
before="$(gh_calls)"
(cd "$REPO_A" && GH_CACHE_DIR="$CACHE_DIR" GH_CACHE_TTL=1 "$GH_CACHED" release list >/dev/null 2>&1)
assert_eq "$before" "$(gh_calls)" "fresh entry is served from cache within its TTL"

sleep 2
before="$(gh_calls)"
(cd "$REPO_A" && GH_CACHE_DIR="$CACHE_DIR" GH_CACHE_TTL=1 "$GH_CACHED" release list >/dev/null 2>&1)
assert_eq "$((before + 1))" "$(gh_calls)" "entry past its TTL is re-fetched"

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "─────────────────────────────────────────"
echo "Tests run:    $TESTS_RUN"
echo -e "Tests passed: ${GREEN}${TESTS_PASSED}${NC}"
if [[ "$TESTS_FAILED" -gt 0 ]]; then
    echo -e "Tests failed: ${RED}${TESTS_FAILED}${NC}"
    exit 1
fi
echo "Tests failed: 0"
exit 0
