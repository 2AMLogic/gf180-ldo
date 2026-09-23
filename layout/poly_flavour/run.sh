#!/usr/bin/env bash
# Poly-resistor flavour coexistence vehicle (issue #312, DR-0036).
#
# Draws two ppolyf_u_high_Rs strips and one plain ppolyf_u strip in one layout
# (gen_gds.py), then runs the PDK's own gf180mcu.lvs against each reference
# netlist in netlist/ under each -rd poly_res= setting in the table below,
# printing the deck's verdict and the extracted resistor lines.
#
# Usage: layout/poly_flavour/run.sh [WORKDIR]
#   KLAYOUT=/path/to/klayout overrides the klayout binary (default: on PATH).
#
# Switches mirror layout/drclvs.py's run_lvs() except poly_res (the variable
# under test) and top_lvl_pins=true (so the two-device compare is not
# simplified away). The pmap(1) stand-in is drclvs.py's own PMAP_SHIM.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
WORK="${1:-$(mktemp -d "${TMPDIR:-/tmp}/poly_flavour.XXXXXX")}"
KLAYOUT="${KLAYOUT:-klayout}"
mkdir -p "$WORK/shims"

eval "$(python3 "$REPO/sim/run_corners.py" --print-env)"
PDK_DIR="$GF180_PDK_PATH"

python3 - "$REPO/layout" "$WORK/shims/pmap" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1])
import drclvs
open(sys.argv[2], "w").write(drclvs.PMAP_SHIM)
EOF
chmod +x "$WORK/shims/pmap"

"$KLAYOUT" -b -r "$HERE/gen_gds.py" -rd out="$WORK/coexist.gds" -rd pdk="$PDK_DIR"
"$KLAYOUT" -v

# tag  reference netlist          poly_res   expected
RUNS=(
  "a netlist/single_3k.spice   3k"   # MATCH    -- the design's form
  "b netlist/single_1k.spice   1k"   # MATCH    -- ppolyf_u is flavour-blind
  "c netlist/single_3k.spice   1k"   # mismatch -- wrong wafer
  "d netlist/mixed_1k_3k.spice 3k"   # mismatch -- issue #312's defect
  "e netlist/mixed_1k_3k.spice 1k"   # mismatch -- ... under either setting
)

for run in "${RUNS[@]}"; do
  read -r tag net pr <<<"$run"
  PATH="$WORK/shims:$PATH" "$KLAYOUT" -b -r "$PDK_DIR/libs.tech/klayout/lvs/gf180mcu.lvs" \
    -rd input="$WORK/coexist.gds" -rd schematic="$HERE/$net" \
    -rd report="$WORK/$tag.lvsdb" -rd target_netlist="$WORK/$tag.cir" \
    -rd topcell=TOP -rd thr=2 -rd run_mode=deep -rd lvs_sub=VSS -rd verbose=false \
    -rd spice_net_names=true -rd spice_comments=false -rd scale=false \
    -rd schematic_simplify=false -rd net_only=false -rd top_lvl_pins=true \
    -rd combine=false -rd purge=false -rd purge_nets=false \
    -rd poly_res="$pr" -rd mim_cap=2 \
    -rd metal_top=11K -rd mim_option=B -rd metal_level=5LM >"$WORK/$tag.log" 2>&1
  verdict="$(grep -o "Netlists match\|Netlists don't match" "$WORK/$tag.log" | head -1 || true)"
  echo "[$tag] poly_res=$pr  $net  ->  ${verdict:-NO VERDICT (see $WORK/$tag.log)}"
  grep -E '^\s*R' "$WORK/$tag.cir" | sed 's/^/        /' || true
done
echo "work dir: $WORK"
