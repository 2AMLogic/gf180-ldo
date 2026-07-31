v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {ldo_erramp_placeholder -- behavioral placeholder error amplifier (issue #8)} -400 -260 0 0 0.5 0.5 {}
T {PLACEHOLDER for issue #9 (real error-amp subcircuit). Pinout is the swap-in
contract: INP INN OUT VDD VSS, in that order, both here and on the .sym.
#9 may replace everything between the port pins below with a real
differential pair + gain stage as long as this pinout is preserved.

Implementation: a behavioral (B) source sets ERR_INT to
av*(V(INP)-V(INN)), av=3162 (~70 dB, within the 60-80 dB the issue asks
for), CLAMPED to [V(VSS), V(VDD)] -- a real op-amp output cannot swing
past its rails, and an ideal unclamped linear source overdriven by a
large differential input (e.g. during the EN=0 disabled state, where FB
collapses towards 0 V while VREF stays at 0.6 V) computes a wildly
out-of-range value that then fights ldo_core's enable clamp through
Rout instead of being dominated by it. Clamping first, THEN a 1 MOhm
Rout to OUT (finite Thevenin impedance, so the enable-clamp FET can pull
PASS_GATE to VIN without fighting a zero-impedance source), reproduces a
real amp's saturating large-signal behavior with two extra primitives.
1 MOhm has zero effect on the enabled-case DC solution (PASS_GATE only
ever sinks/sources a real MOSFET gate's ~0 DC current there) -- it only
has to be large enough that ldo_core's enable-clamp FET (a modest single
PMOS, not sized against this) reliably wins the node when EN=0. Do not
shrink Rout to "look more realistic" without re-checking the
disabled-state op point.

Sign convention (do not flip when replacing): INP is the NON-inverting
input, wired to FB in ldo_core; INN is the INVERTING input, wired to VREF.
This is the polarity required for negative feedback around ldo_core's
PMOS common-source pass device (Vout falls as the pass gate rises) -- see
design/README.md.

Rplaceholder_vdd (1 TOhm, VDD to VSS) is not design content: it only avoids
a floating VDD pin on this ideal-source stub, which has no real bias
network yet. Delete it when #9 lands a real amp that actually draws bias
current from VDD.} -400 -230 0 0 0.28 0.28 {}
C {devices/ipin.sym} -400 -40 0 0 {name=p_inp lab=INP}
C {devices/ipin.sym} -400 40 0 0 {name=p_inn lab=INN}
C {devices/opin.sym} 400 0 0 0 {name=p_out lab=OUT}
C {devices/iopin.sym} -400 -160 0 0 {name=p_vdd lab=VDD}
C {devices/iopin.sym} -400 160 0 0 {name=p_vss lab=VSS}
C {devices/bsource.sym} 0 0 0 0 {name=Bamp VAR=V FUNC="'min(V(vdd),max(V(vss),3162*(V(inp)-V(inn))))'"}
C {devices/lab_pin.sym} 0 -30 0 0 {name=l_e_out sig_type=std_logic lab=ERR_INT}
C {devices/lab_pin.sym} 0 30 0 0 {name=l_e_vss sig_type=std_logic lab=VSS}
C {devices/res.sym} 200 0 0 0 {name=Rout value=1Meg footprint=1206 device=resistor m=1}
C {devices/lab_pin.sym} 200 -30 0 0 {name=l_rout_in sig_type=std_logic lab=ERR_INT}
C {devices/lab_pin.sym} 200 30 0 0 {name=l_rout_out sig_type=std_logic lab=OUT}
C {devices/res.sym} -200 0 0 0 {name=Rplaceholder_vdd value=1T footprint=1206 device=resistor m=1}
C {devices/lab_pin.sym} -200 -30 0 0 {name=l_ph_vdd sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} -200 30 0 0 {name=l_ph_vss sig_type=std_logic lab=VSS}
