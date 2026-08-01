v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {ldo_core -- LDO core (pass device, feedback divider, placeholder error amp,
enable stub). Fixed 1.8 V output from a 3.3 V nominal input. Issue #8.} -700 -650 0 0 0.5 0.5 {}
T {Port order (also the .sym pin order -- do not reorder either file without
updating both, and without re-running design/netlist.py --check):
  VIN         supply in, 3.3 V nominal (dropout spec assumes 2.10-3.63 V)
  VOUT        regulated output, 1.8 V nominal. Also the current-sense tap
              for issue #11: the wire from Mpass.D to this net is the
              series point a future current-limit/foldback sense element
              cuts into -- nothing else needs to change when #11 does that.
  EN          enable, active-high, CMOS-level (0 / VIN). Gates Men, a PMOS
              clamp that pulls PASS_GATE to VIN (pass device off) when
              EN=0. Full shutdown-Iq verification is issue #11's job; this
              is a minimal functional stub only.
  VSS         ground
  ERRAMP_OUT  error-amp output (loop-break point, output side)
  PASS_GATE   pass-device gate (loop-break point, input side)

ERRAMP_OUT and PASS_GATE are deliberately NOT connected to each other
inside this cell -- that is the loop-break point issue #10 needs for a
Middlebrook/Tian stability injection, exposed as two ports so no rewiring
of this schematic is ever needed to reach it. A normal-operation testbench
(e.g. sim/op-point-sanity) simply ties the two ports to the same net at
instantiation (a plain wire); a stability testbench replaces that tie with
an injection network instead. See design/README.md.

Error amp: instantiates error_amp (design/error_amp.sch), the real
two-stage Miller-compensated OTA issue #9 designed against the offset /
PSRR / Iq budgets in design/error_amp.md. It replaced issue #8's behavioral
ldo_erramp_placeholder on the pinout that cell established -- INP INN OUT
VDD VSS, with INP=FB (non-inverting) and INN=VREF (inverting), the polarity
negative feedback around a PMOS common-source pass device requires (Vout
falls as the gate voltage rises). The swap was a symbol-name change only:
error_amp.sym reuses the placeholder's pin coordinates.

Reference: VREF is an ideal 1.2 V source (Vref1), not a real bandgap --
there is no bandgap block designed yet for this repo. 1.2 V (not the 0.6 V
issue #8 first assumed) is the reference DR-0003 budgets against: it puts the
amplifier's offset gain-up at 1/beta = Vout/Vref = 1.5, and it is the input
common mode design/error_amp.sch's NMOS input pair needs to keep its tail
source in saturation at the 2.10 V dropout test point. Changed with issue #9
-- see design/error_amp.md "Why 1.2 V, not 0.6 V".

Feedback divider: Rtop=300k, Rbot=600k (plain behavioral R, not the PDK's
ppolyf_u_3k poly resistor -- guidance said either is acceptable for this
sanity netlist; sheet-resistance-accurate sizing and the unit-resistor
matching plan are #15's/#13's, and design/error_amp.md's offset table states
the area the mismatch assumption implies). FB = VOUT * Rbot/(Rtop+Rbot)
= 2*VOUT/3, so VOUT settles at 1.5*VREF = 1.8 V. The 900 kOhm total is what
DR-0003 calls for to hold the divider's standing current near 2 uA
(1.8 V / 900 kOhm = 2.0 uA).

Pass device Mpass: pfet_03v3, L=0.28u (model minimum), W=2000u (2 mm),
nf=40, m=1. This is a SIMPLIFICATION of the full ~4 mm / 40-unit-cell
sizing the ratified spec calls for (needed to clear 300 mV dropout @
50 mA at the worst corner) -- 2 mm is the guidance's stated acceptable
size for THIS issue's DC-sanity loop-closure test only, at effectively no
load beyond the feedback divider's ~6 uA. The full sizing (and the
unit-cell partitioning a layout needs for matching) is layout-phase work,
out of scope here.} -700 -600 0 0 0.28 0.28 {}
C {devices/iopin.sym} -700 -300 0 0 {name=p_vin lab=VIN}
C {devices/iopin.sym} 700 -300 0 0 {name=p_vout lab=VOUT}
C {devices/ipin.sym} -700 -100 0 0 {name=p_en lab=EN}
C {devices/iopin.sym} -700 300 0 0 {name=p_vss lab=VSS}
C {devices/opin.sym} -100 -700 0 0 {name=p_erramp_out lab=ERRAMP_OUT}
C {devices/ipin.sym} 100 -700 0 0 {name=p_pass_gate lab=PASS_GATE}
C {symbols/pfet_03v3.sym} 300 -100 0 0 {name=Mpass model=pfet_03v3 L=0.28u W=2000u nf=40 m=1}
C {devices/lab_pin.sym} 280 -100 0 0 {name=l_mpass_g sig_type=std_logic lab=PASS_GATE}
C {devices/lab_pin.sym} 320 -70 0 0 {name=l_mpass_d sig_type=std_logic lab=VOUT}
C {devices/lab_pin.sym} 320 -130 0 0 {name=l_mpass_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 320 -100 0 0 {name=l_mpass_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 300 -450 0 0 {name=Men model=pfet_03v3 L=0.28u W=50u nf=2 m=1}
C {devices/lab_pin.sym} 280 -450 0 0 {name=l_men_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 320 -420 0 0 {name=l_men_d sig_type=std_logic lab=PASS_GATE}
C {devices/lab_pin.sym} 320 -480 0 0 {name=l_men_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 320 -450 0 0 {name=l_men_b sig_type=std_logic lab=VIN}
C {devices/res.sym} 550 -250 0 0 {name=Rtop value=300k footprint=1206 device=resistor m=1}
C {devices/lab_pin.sym} 550 -280 0 0 {name=l_rtop_p sig_type=std_logic lab=VOUT}
C {devices/lab_pin.sym} 550 -220 0 0 {name=l_rtop_m sig_type=std_logic lab=FB}
C {devices/res.sym} 550 -100 0 0 {name=Rbot value=600k footprint=1206 device=resistor m=1}
C {devices/lab_pin.sym} 550 -130 0 0 {name=l_rbot_p sig_type=std_logic lab=FB}
C {devices/lab_pin.sym} 550 -70 0 0 {name=l_rbot_m sig_type=std_logic lab=VSS}
C {devices/vsource.sym} -300 -350 0 0 {name=Vref1 value=1.2}
C {devices/lab_pin.sym} -300 -380 0 0 {name=l_vref_p sig_type=std_logic lab=VREF}
C {devices/lab_pin.sym} -300 -320 0 0 {name=l_vref_m sig_type=std_logic lab=VSS}
C {error_amp.sym} 0 -450 0 0 {name=Xerramp}
C {devices/lab_pin.sym} -100 -480 0 0 {name=l_amp_inp sig_type=std_logic lab=FB}
C {devices/lab_pin.sym} -100 -460 0 0 {name=l_amp_inn sig_type=std_logic lab=VREF}
C {devices/lab_pin.sym} 100 -450 0 0 {name=l_amp_out sig_type=std_logic lab=ERRAMP_OUT}
C {devices/lab_pin.sym} -100 -440 0 0 {name=l_amp_vdd sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} -100 -420 0 0 {name=l_amp_vss sig_type=std_logic lab=VSS}
