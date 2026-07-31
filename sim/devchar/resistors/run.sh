#!/usr/bin/env bash
# Resistor flavour characterization sweep (issue #4).
#
#   ./sim/devchar/resistors/run.sh          # full corner/temperature matrix + MC
#   DC_MC_RUNS=500 ./sim/devchar/resistors/run.sh
#
# Resistors have no supply-voltage axis: every gf180mcu resistor card carries
# r_vc1 = r_vc2 = 0, so R is bias independent. The rsheet deck still records a
# 50 uA row next to the 1 uA reference row for each flavour so that claim is
# backed by a measurement rather than by reading the model file.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" && pwd)/devchar.sh"
dc_init

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RES="$HERE/results"
: "${DC_MC_RUNS:=200}"

echo "resistor flavour / corner / temperature sweep"
OUT="$RES/rsheet.csv"
dc_csv_header "$OUT" "device,res_corner,temp_c,w_um,l_um,i_test,r_ohm,rsh_nominal_ohm_sq"
for corner in "${DC_RES_CORNERS[@]}"; do
  for temp in "${DC_TEMPS[@]}"; do
    dc_run "$HERE/rsheet.sp.in" "$OUT" RESLIB="$corner" TEMP="$temp"
  done
done

echo "matching Monte Carlo ($DC_MC_RUNS runs per mode per temperature)"
OUT="$RES/mismatch_mc_raw.csv"
dc_csv_header "$OUT" "mode,temp_c,run,device,w_um,l_um,area_um2,quantity,val_a,val_b"
for temp in "${DC_TEMPS[@]}"; do
  dc_run "$HERE/mismatch_mc.sp.in" "$OUT" \
    MODE=mismatch SWG=0 SWM=1 RESLIB=res_typical FETLIB=typical \
    TEMP="$temp" NRUNS="$DC_MC_RUNS"
  dc_run "$HERE/mismatch_mc.sp.in" "$OUT" \
    MODE=global SWG=1 SWM=0 RESLIB=res_statistical FETLIB=statistical \
    TEMP="$temp" NRUNS="$DC_MC_RUNS"
done

echo "done - results in $RES"
