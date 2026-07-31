#!/usr/bin/env bash
# Capacitor characterization sweep (issue #4).
#
#   ./sim/devchar/caps/run.sh
#
# The bias axis is part of the sweep matrix rather than part of the deck: both
# capacitor decks take a single @VBIAS@ and the driver steps it, so the same
# deck serves the MIM voltage-coefficient check and the MOSCAP C-V curve.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" && pwd)/devchar.sh"
dc_init

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RES="$HERE/results"

# MIM: bias points spanning the 3.3 V supply, plus one reversed-polarity point.
MIM_BIAS=(-1.65 0 0.825 1.65 2.50 3.30)

# MOSCAP: full +/- supply swing at 150 mV resolution. The inversion knee of the
# 3.3 V devices is ~160 mV wide (tanh argument slope 6.25/V), so a coarser step
# would alias straight over the depletion region this sweep exists to capture.
MOSCAP_BIAS=()
for i in $(seq -22 22); do
  MOSCAP_BIAS+=("$(awk -v n="$i" 'BEGIN{printf "%.2f", n*0.15}')")
done

echo "MIM capacitor sweep (${#MIM_BIAS[@]} bias points x ${#DC_MIM_CORNERS[@]} corners x ${#DC_TEMPS[@]} temperatures)"
OUT="$RES/mim.csv"
dc_csv_header "$OUT" "device,mim_corner,temp_c,vbias_v,w_um,l_um,area_um2,c_f,c_density_ff_per_um2"
for corner in "${DC_MIM_CORNERS[@]}"; do
  for temp in "${DC_TEMPS[@]}"; do
    for vb in "${MIM_BIAS[@]}"; do
      dc_run "$HERE/mim.sp.in" "$OUT" MIMLIB="$corner" TEMP="$temp" VBIAS="$vb"
    done
  done
done

echo "MOSCAP C-V sweep (${#MOSCAP_BIAS[@]} bias points x ${#DC_MOSCAP_CORNERS[@]} corners x ${#DC_TEMPS[@]} temperatures)"
OUT="$RES/moscap.csv"
dc_csv_header "$OUT" "device,moscap_corner,temp_c,vbias_v,w_um,l_um,area_um2,c_f,c_density_ff_per_um2"
for corner in "${DC_MOSCAP_CORNERS[@]}"; do
  for temp in "${DC_TEMPS[@]}"; do
    for vb in "${MOSCAP_BIAS[@]}"; do
      dc_run "$HERE/moscap.sp.in" "$OUT" MOSCAPLIB="$corner" TEMP="$temp" VBIAS="$vb"
    done
  done
done

echo "done - results in $RES"
