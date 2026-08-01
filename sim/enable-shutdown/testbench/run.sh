#!/usr/bin/env bash
# Enable / shutdown PVT sweep for design/ldo_core.sch + design/ldo_ilimit.sch
# (issue #11).
#
#   ./sim/enable-shutdown/testbench/run.sh             # full matrix, writes evidence
#   NO_RECORD=1 CORNERS=tt TEMPS=27 SUPPLIES=3.30 \
#       ./sim/enable-shutdown/testbench/run.sh         # single point, writes nothing
#
# Same structure, and the same standalone-rather-than-sim/harness rationale,
# as sim/current-limit/testbench/run.sh -- see that script's header. The two
# are deliberately independent copies rather than a shared library: each
# experiment directory under sim/ is meant to be self-contained evidence,
# and a shared runner would make a change made for one claim silently
# re-scope the other.
#
# Corner matrix:
#   process   tt ff ss fs sf res_ff res_ss   (bjt_ff / bjt_ss omitted: the
#                                             design has no bipolar devices)
#   temp      -40 27 125 degC
#   supply    2.97 3.30 3.63 V  (3.3 V +/-10%, DR-0002)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPDIR="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$EXPDIR/../.." && pwd)"
SLUG="$(basename "$EXPDIR")"

CORNERS="${CORNERS:-tt ff ss fs sf res_ff res_ss}"
TEMPS="${TEMPS:--40 27 125}"
SUPPLIES="${SUPPLIES:-2.97 3.30 3.63}"
JOBS="${JOBS:-4}"

corner_sections() {
  case "$1" in
    tt)     echo "typical res_typical bjt_typical diode_typical moscap_typical mimcap_typical" ;;
    ff)     echo "ff res_ff bjt_ff diode_ff moscap_ff mimcap_ff" ;;
    ss)     echo "ss res_ss bjt_ss diode_ss moscap_ss mimcap_ss" ;;
    fs)     echo "fs res_typical bjt_typical diode_typical moscap_typical mimcap_typical" ;;
    sf)     echo "sf res_typical bjt_typical diode_typical moscap_typical mimcap_typical" ;;
    res_ff) echo "typical res_ff bjt_typical diode_typical moscap_typical mimcap_typical" ;;
    res_ss) echo "typical res_ss bjt_typical diode_typical moscap_typical mimcap_typical" ;;
    *) echo "FATAL: unknown corner $1" >&2; exit 1 ;;
  esac
}

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

run_point() {
  local corner="$1" temp="$2" vin="$3"
  local sections; sections="$(corner_sections "$corner")"
  read -r s_mos s_res s_bjt s_dio s_mosc s_mimc <<<"$sections"
  local corner_id; corner_id="$(printf '%s_%sc_%.2fv' "$corner" "$temp" "$vin")"
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
    "$HERE/tb_enable_shutdown.spice.in" > "$deck"

  if ! ngspice -b "$deck" > "$log" 2>&1; then
    echo "FATAL: ngspice failed on $corner_id (see $log)" >&2
    tail -40 "$log" >&2
    return 1
  fi
  if grep -qE 'could not find a valid modelname|Simulation interrupted|singular matrix|no convergence|iteration limit reached|fatal error|no such vector|failed$' "$log"; then
    echo "FATAL: ngspice reported an error on $corner_id (see $log)" >&2
    grep -nE 'could not find a valid modelname|Simulation interrupted|singular matrix|no convergence|iteration limit reached|fatal error|no such vector|failed$' "$log" >&2
    return 1
  fi
  echo "$corner_id"
}
export -f run_point corner_sections
export WORKDIR LOG_DIR HERE DESIGN_INCLUDE MODEL_LIB LDO_NETLIST

points=()
for c in $CORNERS; do for t in $TEMPS; do for v in $SUPPLIES; do
  points+=("$c $t $v")
done; done; done

printf '%s\n' "${points[@]}" \
  | xargs -P "$JOBS" -I{} bash -c 'run_point $0' "{}" \
  | sort

CSV="$LOG_DIR/summary.csv"
python3 - "$LOG_DIR" "$CSV" "$CORNERS" "$TEMPS" "$SUPPLIES" <<'EOF'
import re, sys, pathlib

log_dir, csv_path, corners, temps, supplies = sys.argv[1:6]
log_dir = pathlib.Path(log_dir)

SCALARS = ["m_vout_en", "m_iload_en_ma", "m_isup_en_ua", "m_iref_en_ua",
           "m_iq_en_ua",
           "m_vout_off", "m_pg_off", "m_clg_off", "m_isup_off_ua",
           "m_iref_off_ua", "m_iloop_off_ua", "m_nbias_off",
           "m_iq_off_ua", "m_ileak_vin_vout_ua",
           "m_t_startup", "m_vout_settled", "m_vout_max_en",
           "m_vout_min_reg", "m_isup_peak_ma", "m_clg_min_reg",
           "m_isup_peak_reg_ma", "m_vout_pp_late", "m_vout_off_tran",
           "m_vout_max_off", "m_pg_off_tran"]

def read(log):
    vals = {}
    for line in log.read_text().splitlines():
        m = re.match(r"^(m_\w+)\s*=\s*([-+0-9.eE]+)", line)
        if m:
            try:
                vals[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    missing = [s for s in SCALARS if s not in vals]
    if missing:
        raise SystemExit(f"FATAL: {log.name} is missing measurements: {missing}")
    return vals

rows = []
for c in corners.split():
    for t in temps.split():
        for v in supplies.split():
            cid = "%s_%sc_%.2fv" % (c, t, float(v))
            vals = read(log_dir / f"{cid}.log")
            vals["m_t_startup_us"] = vals["m_t_startup"] * 1e6
            vals["_vin"] = float(v)
            rows.append((cid, c, t, v, vals))

cols = SCALARS + ["m_t_startup_us"]
with open(csv_path, "w") as fh:
    fh.write("corner_id,corner,temp_c,vin_v," + ",".join(c[2:] for c in cols) + "\n")
    for cid, c, t, v, vals in rows:
        fh.write(f"{cid},{c},{t},{v}," + ",".join(f"{vals[k]:.6g}" for k in cols) + "\n")

def rep(name):
    vs = [(cid, vals[name]) for cid, _, _, _, vals in rows]
    lo = min(vs, key=lambda x: x[1]); hi = max(vs, key=lambda x: x[1])
    print(f"  {name[2:]:20s} min {lo[1]:12.5f} @ {lo[0]:20s}  max {hi[1]:12.5f} @ {hi[0]}")

print(f"\n{len(rows)} PVT points")
for m in ("m_vout_en", "m_iq_en_ua", "m_vout_off", "m_iloop_off_ua",
          "m_nbias_off", "m_iq_off_ua", "m_ileak_vin_vout_ua",
          "m_t_startup_us", "m_vout_settled", "m_vout_max_en",
          "m_vout_min_reg", "m_isup_peak_ma", "m_clg_min_reg",
          "m_isup_peak_reg_ma", "m_vout_pp_late", "m_vout_off_tran", "m_pg_off_tran"):
    rep(m)

def flag(label, pred):
    bad = [cid for cid, *_, vals in rows if pred(vals)]
    print(f"  {label:52s} {bad or 'none'}")

print()
flag("shutdown Iq above the ratified 3 uA:", lambda v: v["m_iq_off_ua"] > 3.0)
flag("enabled Iq above the ratified 30 uA:", lambda v: v["m_iq_en_ua"] > 30.0)
flag("Vin->Vout leakage above 1 uA:", lambda v: abs(v["m_ileak_vin_vout_ua"]) > 1.0)
flag("startup failed to reach 1.764 V:", lambda v: not (0 < v["m_t_startup"] < 4e-4))
flag("settled output outside +/-2% while enabled:",
     lambda v: not (1.764 <= v["m_vout_settled"] <= 1.836))
flag("regulation dipped below 1.764 V after settling:",
     lambda v: v["m_vout_min_reg"] < 1.764)
flag("startup overshoot above +2% (1.836 V):", lambda v: v["m_vout_max_en"] > 1.836)
flag("disabled output above 10 mV at the end of the tail:",
     lambda v: v["m_vout_off_tran"] > 0.010)
flag("limit clamp engaged while settled at 50 mA (CLG < VIN-0.2):",
     lambda v: v["m_clg_min_reg"] < float(v["_vin"]) - 0.2)
EOF

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
