#!/usr/bin/env bash
#
# random-file.sh - Get a random file from the workspace
#
# This script provides standalone random file selection for use without the MCP server.
# It respects .gitignore and supports include/exclude patterns.
#
# Usage:
#   ./random-file.sh                                    # Random file from workspace
#   ./random-file.sh --include "src/**/*.ts"            # Only TypeScript files in src/
#   ./random-file.sh --exclude "**/*.test.ts"           # Exclude test files
#   ./random-file.sh --include "src/**/*.ts" --exclude "**/*.test.ts"
#
# Options:
#   --include PATTERN   Glob pattern to include (can be used multiple times)
#   --exclude PATTERN   Glob pattern to exclude (can be used multiple times)
#   --help              Show this help message
#   --debug             Show debug output
#
# Examples:
#   ./random-file.sh --include "src/**/*.ts" --include "src/**/*.tsx"
#   ./random-file.sh --exclude "**/*.test.ts" --exclude "**/*.spec.ts"
#   ./random-file.sh --include "defaults/roles/*.md"
#

set -eo pipefail

# Get script directory and workspace root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
DEBUG="${DEBUG:-false}"
INCLUDE_PATTERNS=()
EXCLUDE_PATTERNS=()

# Default exclude patterns (match MCP implementation)
# NOTE: no "*.log" entry here -- .gitignore is the source of truth for which
# logs are scratch vs. evidence (see git_candidate_files() below, which uses
# `git ls-files --exclude-standard` / fd's native gitignore handling). A repo
# can `!`-negate specific log paths (e.g. append-only evidence logs); a
# hardcoded "*.log" here would silently hide those from the sampler.
DEFAULT_EXCLUDES=(
    "node_modules"
    ".git"
    "dist"
    "build"
    "target"
    ".loom/worktrees"
    "package-lock.json"
    "pnpm-lock.yaml"
    "yarn.lock"
    "Cargo.lock"
)

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --include)
                if [[ -z "${2:-}" ]]; then
                    echo "Error: --include requires a pattern argument" >&2
                    exit 1
                fi
                INCLUDE_PATTERNS+=("$2")
                shift 2
                ;;
            --exclude)
                if [[ -z "${2:-}" ]]; then
                    echo "Error: --exclude requires a pattern argument" >&2
                    exit 1
                fi
                EXCLUDE_PATTERNS+=("$2")
                shift 2
                ;;
            --debug)
                DEBUG=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                echo "Error: Unknown option: $1" >&2
                show_help >&2
                exit 1
                ;;
        esac
    done
}

show_help() {
    cat << 'EOF'
random-file.sh - Get a random file from the workspace

Usage:
  ./random-file.sh [OPTIONS]

Options:
  --include PATTERN   Glob pattern to include (can be used multiple times)
  --exclude PATTERN   Glob pattern to exclude (can be used multiple times)
  --debug             Show debug output
  --help              Show this help message

Examples:
  ./random-file.sh                                    # Random file from workspace
  ./random-file.sh --include "src/**/*.ts"            # Only TypeScript files in src/
  ./random-file.sh --exclude "**/*.test.ts"           # Exclude test files
  ./random-file.sh --include "src/**/*.ts" --exclude "**/*.test.ts"

Default exclusions:
  - node_modules/, .git/, dist/, build/, target/
  - .loom/worktrees/
  - package-lock.json, pnpm-lock.yaml, yarn.lock, Cargo.lock
  - Files matching .gitignore patterns (including negations, e.g. an
    append-only *.log path a repo's .gitignore un-ignores with "!")

The script always respects .gitignore if present in the workspace root, via
git's own ignore handling (git ls-files / fd's native gitignore support) --
not a hand-rolled parser.
EOF
}

debug() {
    if [[ "$DEBUG" == "true" ]]; then
        echo "[DEBUG] $*" >&2
    fi
}

# Get list of files matching criteria
get_matching_files() {
    cd "$WORKSPACE_ROOT"

    # Build the find command
    local include_args=""
    if [[ ${#INCLUDE_PATTERNS[@]} -gt 0 ]]; then
        # Build include patterns for find
        for pattern in "${INCLUDE_PATTERNS[@]}"; do
            # Convert glob to find pattern
            if [[ "$pattern" == *"**"* ]]; then
                # Pattern with ** - use path matching
                local converted="${pattern//\*\*/\*}"
                include_args+=" -path './$converted' -o"
            else
                include_args+=" -path './$pattern' -o"
            fi
        done
        include_args="${include_args% -o}"
    fi

    debug "Include args: $include_args"

    # Use fd if available (faster), otherwise fall back to find + grep
    if command -v fd &>/dev/null; then
        get_files_with_fd
    else
        get_files_with_find
    fi
}

# Base candidate file list: tracked files plus untracked-but-not-ignored
# files, exactly as git itself computes "not gitignored" -- handles nested
# .gitignore files and "!" negations for free, unlike a hand-rolled parser
# (see #129). Assumes WORKSPACE_ROOT is inside a git work tree (already true
# for every repo this script ships in); falls back to an empty result
# (callers fall back to a plain `find`) if git is unavailable or this is not
# a git repo.
git_candidate_files() {
    git ls-files --cached --others --exclude-standard -- . 2>/dev/null || true
}

# Use fd for fast file finding (if available)
get_files_with_fd() {
    local fd_args=("--type" "f" "--hidden")

    # Add include patterns
    if [[ ${#INCLUDE_PATTERNS[@]} -gt 0 ]]; then
        # For fd, we need to use -e for extensions or -g for globs
        for pattern in "${INCLUDE_PATTERNS[@]}"; do
            fd_args+=("-g" "$pattern")
        done
    fi

    # Add exclude patterns
    for pattern in "${DEFAULT_EXCLUDES[@]}"; do
        fd_args+=("-E" "$pattern")
    done

    for pattern in "${EXCLUDE_PATTERNS[@]}"; do
        fd_args+=("-E" "$pattern")
    done

    debug "Running: fd ${fd_args[*]}"

    # fd respects .gitignore natively by default (nested files and "!"
    # negations included) as long as we don't pass --no-ignore-vcs, so no
    # extra gitignore filtering is needed here.
    fd "${fd_args[@]}" . 2>/dev/null
}

# Use git ls-files as fallback (no fd available)
get_files_with_find() {
    local files
    files=$(git_candidate_files)

    if [[ -z "$files" ]]; then
        # Not a git repo (or git unavailable) -- fall back to a plain
        # filesystem walk with no .gitignore awareness rather than
        # returning nothing.
        debug "git ls-files returned no candidates; falling back to find"
        files=$(find . -type f 2>/dev/null | sed 's|^\./||')
    fi

    # If we have include patterns, keep only files matching at least one
    if [[ ${#INCLUDE_PATTERNS[@]} -gt 0 ]]; then
        files=$(echo "$files" | filter_by_include_patterns)
    fi

    # Apply exclusions
    files=$(echo "$files" | apply_exclusions)
    echo "$files"
}

# Keep only lines matching at least one --include glob pattern (full-path match)
filter_by_include_patterns() {
    local input
    input=$(cat)

    local include_regex=""
    for pattern in "${INCLUDE_PATTERNS[@]}"; do
        local regex
        regex=$(glob_to_regex "$pattern")
        include_regex+="|^${regex}\$"
    done
    include_regex="${include_regex#|}"

    if [[ -n "$include_regex" ]]; then
        debug "Include regex: $include_regex"
        echo "$input" | grep -E "$include_regex" || true
    else
        echo "$input"
    fi
}

# Apply exclusion patterns
apply_exclusions() {
    local input
    input=$(cat)

    # Build grep exclusion pattern
    local exclude_regex=""

    for pattern in "${DEFAULT_EXCLUDES[@]}"; do
        # Handle different pattern types
        if [[ "$pattern" == *.* ]]; then
            # File extension or specific file
            local escaped
            escaped=$(printf '%s' "$pattern" | sed 's/[.[\*^$()+?{|]/\\&/g')
            escaped="${escaped//\\\*/.*}"  # Convert \* back to .*
            exclude_regex+="|$escaped$"
        else
            # Directory name
            exclude_regex+="|/$pattern/|^$pattern/"
        fi
    done

    for pattern in "${EXCLUDE_PATTERNS[@]}"; do
        # Convert glob to regex
        local regex
        regex=$(glob_to_regex "$pattern")
        exclude_regex+="|$regex"
    done

    # Remove leading |
    exclude_regex="${exclude_regex#|}"

    if [[ -n "$exclude_regex" ]]; then
        debug "Exclude regex: $exclude_regex"
        echo "$input" | grep -v -E "$exclude_regex" || true
    else
        echo "$input"
    fi
}

# Convert glob pattern to regex
glob_to_regex() {
    local pattern="$1"
    # Escape special regex characters except * and ?
    local regex
    regex=$(printf '%s' "$pattern" | sed 's/[.[\^$()+{|]/\\&/g')
    # Convert glob wildcards to regex
    regex="${regex//\*\*/.*}"      # ** -> .* (any path)
    regex="${regex//\*/[^/]*}"     # * -> [^/]* (any chars except /)
    regex="${regex//\?/.}"         # ? -> . (any single char)
    echo "$regex"
}

# Pick a random file from the list
pick_random() {
    local files=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && files+=("$line")
    done

    if [[ ${#files[@]} -eq 0 ]]; then
        echo "No files found matching the criteria" >&2
        exit 1
    fi

    debug "Found ${#files[@]} matching files"

    # Pick random index
    local index=$((RANDOM % ${#files[@]}))
    local selected="${files[$index]}"

    # Return absolute path
    echo "$WORKSPACE_ROOT/$selected"
}

# Main
main() {
    parse_args "$@"

    debug "Workspace: $WORKSPACE_ROOT"
    debug "Include patterns: ${INCLUDE_PATTERNS[*]:-<all>}"
    debug "Exclude patterns: ${EXCLUDE_PATTERNS[*]:-<none>}"

    get_matching_files | pick_random
}

main "$@"
