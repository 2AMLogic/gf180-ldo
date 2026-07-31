#!/usr/bin/env bash
# Pass-FET characterization sweep (issue #4).
#
#   ./sim/devchar/fets/run.sh              # full PVT matrix, regenerates results/*.csv
#   DC_KEEP=1 ./sim/devchar/fets/run.sh    # keep the generated decks in sim/devchar/.build
#
# Devices, corners and the PVT matrix are data here, not copy-pasted decks: the
# *.sp.in templates carry the topology, this driver carries the sweep.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" && pwd)/devchar.sh"
dc_init

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RES="$HERE/results"

# device            L1      L2     L3     supply-set
#   L1 is the model's minimum drawn length for that flavor.
PMOS_DEVS=(
  "pfet_03v3 0.28u 0.50u 1.00u lv"
  "pfet_05v0 0.50u 0.60u 1.00u mv"
  "pfet_06v0 0.55u 0.70u 1.20u mv"
)
NMOS_DEVS=(
  "nfet_03v3 0.28u 0.50u 1.00u lv"
  "nfet_06v0 0.60u 0.80u 1.20u mv"
)

supplies_for() {
  case "$1" in
    lv) printf '%s\n' "${DC_VINS_DROPOUT[@]}" "${DC_VINS[@]}" ;;
    mv) printf '%s\n' "${DC_VINS_DROPOUT[@]}" "${DC_VINS[@]}" "${DC_VINS_MV[@]}" ;;
  esac
}

sweep() {
  local tmpl="$1" out="$2" header="$3"; shift 3
  local devlist=("$@")
  dc_csv_header "$out" "$header"
  local spec dev l1 l2 l3 vset corner temp vin
  for spec in "${devlist[@]}"; do
    read -r dev l1 l2 l3 vset <<<"$spec"
    for corner in "${DC_FET_CORNERS[@]}"; do
      for temp in "${DC_TEMPS[@]}"; do
        while read -r vin; do
          dc_run "$tmpl" "$out" \
            DEV="$dev" L1="$l1" L2="$l2" L3="$l3" \
            CORNER="$corner" TEMP="$temp" VIN="$vin"
        done < <(supplies_for "$vset")
      done
    done
    echo "  ... $dev done ($(basename "$tmpl"))"
  done
}

echo "threshold voltage extraction"
OUT="$RES/vth.csv"
dc_csv_header "$OUT" "device,corner,temp_c,w_um,l_um,vsb_v,i_criterion_a,vth_v"
for corner in "${DC_FET_CORNERS[@]}"; do
  for temp in "${DC_TEMPS[@]}"; do
    dc_run "$HERE/vth.sp.in" "$OUT" CORNER="$corner" TEMP="$temp"
  done
done

echo "PMOS dropout / Rds(on) sweep"
sweep "$HERE/rdson_pmos.sp.in" "$RES/rdson_pmos.csv" \
  "device,corner,temp_c,vin_v,l_um,w_mm,metric,vsd_v,id_a,rds_ohm,rdsw_ohm_mm,vd_v" \
  "${PMOS_DEVS[@]}"

echo "NMOS headroom sweep"
sweep "$HERE/rdson_nmos.sp.in" "$RES/rdson_nmos.csv" \
  "device,corner,temp_c,vin_v,l_um,w_mm,metric,vdrop_v,vgs_v,id_a,rds_ohm,rdsw_ohm_mm" \
  "${NMOS_DEVS[@]}"

echo "PMOS gate capacitance sweep"
sweep "$HERE/cgg_pmos.sp.in" "$RES/cgg_pmos.csv" \
  "device,corner,temp_c,vin_v,l_um,w_mm,metric,cgg_f,cgd_f,cgg_per_mm_f" \
  "${PMOS_DEVS[@]}"

echo "NMOS gate capacitance sweep"
sweep "$HERE/cgg_nmos.sp.in" "$RES/cgg_nmos.csv" \
  "device,corner,temp_c,vin_v,l_um,w_mm,metric,cgg_f,cgd_f,cgg_per_mm_f" \
  "${NMOS_DEVS[@]}"

echo "PMOS off-state leakage sweep"
sweep "$HERE/leak_pmos.sp.in" "$RES/leak_pmos.csv" \
  "device,corner,temp_c,vin_v,l_um,w_mm,metric,ioff_a,ioff_per_mm_a" \
  "${PMOS_DEVS[@]}"

echo "NMOS off-state leakage sweep"
sweep "$HERE/leak_nmos.sp.in" "$RES/leak_nmos.csv" \
  "device,corner,temp_c,vin_v,l_um,w_mm,metric,ioff_a,ioff_per_mm_a" \
  "${NMOS_DEVS[@]}"

echo "done - results in $RES"
