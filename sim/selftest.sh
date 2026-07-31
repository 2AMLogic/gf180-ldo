#!/usr/bin/env bash
#
# Harness acceptance test.
#
#   sim/selftest.sh              unit tests + smoke PVT run (no evidence written)
#   sim/selftest.sh --record     also mint an evidence record under sim/smoke-bias/
#   sim/selftest.sh --quick      unit tests + a single tt/27C/nominal point
#   sim/selftest.sh --require-pdk  fail (instead of skipping) if the PDK is absent
#
# Exit codes: 0 pass (or skipped sim stage), 1 something failed.

set -uo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

RECORD=0
QUICK=0
REQUIRE_PDK=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    --quick) QUICK=1 ;;
    --require-pdk) REQUIRE_PDK=1 ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: ${arg}" >&2; exit 1 ;;
  esac
done

echo "== 1/3 harness unit tests (no PDK required) =="
if ! python3 -m unittest discover -s "${SIM_DIR}/tests" -t "${SIM_DIR}/tests"; then
  echo "FAIL: harness unit tests"
  exit 1
fi

echo
echo "== 2/3 environment =="
if ! python3 "${SIM_DIR}/run_corners.py" --check-env; then
  if [ "${REQUIRE_PDK}" -eq 1 ]; then
    echo "FAIL: ngspice and/or the gf180mcu PDK are not available"
    exit 1
  fi
  echo
  echo "SKIP: simulation stage -- ngspice and/or the gf180mcu PDK are not available."
  echo "      Unit tests passed. Install the PDK (see the hint above) to run the"
  echo "      end-to-end PVT smoke test."
  exit 0
fi

echo
echo "== 3/3 end-to-end PVT smoke run =="
args=(smoke-bias)
[ "${QUICK}" -eq 1 ] && args+=(--corners tt --temps 27 --supply-tol 0)
[ "${RECORD}" -eq 1 ] || args+=(--no-write)
# --quick is deliberately a PVT subset; sim/README.md demands a written reason
# before a subset run may be recorded as evidence.
if [ "${QUICK}" -eq 1 ] && [ "${RECORD}" -eq 1 ]; then
  args+=(--subset-reason "sim/selftest.sh --quick: single-point harness smoke test, not a spec claim")
fi

if ! python3 "${SIM_DIR}/run_corners.py" "${args[@]}"; then
  echo "FAIL: PVT smoke run"
  exit 1
fi

echo
echo "PASS: harness is functional end to end."
