v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {ldo_core -- LDO core (pass device, feedback divider, error amp, current
limit, enable network). Fixed 1.8 V output from a 3.3 V nominal input.
Issue #8 (skeleton), #9 (amp), #11 (current limit + enable).} -700 -650 0 0 0.5 0.5 {}
T {Port order (also the .sym pin order -- do not reorder either file without
updating both, and without re-running design/netlist.py --check):
  VIN         supply in, 3.3 V nominal (dropout spec assumes 2.10-3.63 V)
  VOUT        regulated output, 1.8 V nominal. Also the current-sense
              RETURN for issue #11's Xilimit: Msense inside that block is a
              1/40 replica of Mpass whose current is returned here through
              Rsns, so the Mpass.D-to-VOUT wire was never cut and no series
              element was inserted in the pass path -- the sense current is
              delivered to the load rather than burned, which is what keeps
              it out of the Iq budget.
  EN          enable, active-high, CMOS-level (0 / VIN). Gates Men, a PMOS
              clamp that pulls PASS_GATE to VIN (pass device off) when
              EN=0. Issue #11 EXTENDS this same net rather than adding a
              second enable path: it also gates Xerramp's bias (error_amp's
              EN pin, appended by #11) and Xilimit's bias, comparator tail
              and clamp. Shutdown-Iq characterization is #11's, in
              sim/enable-shutdown/records/.
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

Loop compensation -- Cff (issue #42): a feedforward capacitor from VOUT to
FB, in parallel with Rtop, per the lever design/error_amp.md section 6
already named ("the conventional one is a feedforward capacitor across
Rtop"). #10's stability record (sim/loop-stability/records/
20260801-050406-65416d2.md) measured a hard FAIL (worst PM -12.89 deg,
worst GM -28.87 dB) with a -180 deg crossing at every PVT point: the
amplifier's own Miller-set dominant pole (~2.6 Hz, XCc/XRz in
design/error_amp.sch) and the load-dependent output pole at VOUT are BOTH
always many decades below crossover across the whole matrix -- an
unavoidable consequence of a two-pole system with the ~140 dB DC loop gain
the load-regulation and PSRR rows require (crossover self-consistently
lands near sqrt(A0*fp1*fp2), never close to either pole) -- so no amount of
re-scaling XCc alone moves the phase margin off its near-0 deg floor
(confirmed empirically: 3-100x XCc rescaling left the light-load floor
within a degree of 0 deg either way). Cff adds a genuine LHP zero at
1/(2*pi*Rtop*Cff) with a companion pole at 1/(2*pi*(Rtop||Rbot)*Cff) --
DOES NOT depend on the external output cap's ESR (DR-0001's "no minimum
ESR" constraint), costs no quiescent current, and needs no change to
design/error_amp.sch (so none of #9's offset/PSRR/Iq records, measured with
the amplifier driving its own 6.14 pF gate load in isolation, need
re-verification). NOTE the sign: a feedforward cap across Rbot instead
(the resistor to ground) gives a PURE POLE, not a zero -- it must go across
Rtop (VOUT side), confirmed both by the transfer-function derivation and by
a control experiment that measured a further ~50 deg WORSE margin with it
across Rbot.

ISSUE #51 UPDATE -- Cff is retained, but it is no longer the load-bearing
compensation. #51 rebuilt the compensation inside design/error_amp.sch (a
class-AB gate buffer plus a Type-II gain-shelf Miller network) and that is
what closes the loop: every point of DR-0001's matrix at I_load >= 1 mA now
meets PM >= 45 deg and GM >= 10 dB, and 525 of the 540 points at 0.1 mA do.
Cff's LHP zero at 1/(2*pi*Rtop*Cff) still contributes and still costs no
quiescent current, so it stays; what changed is that the amplifier no longer
rolls the loop off at -40 dB/dec through crossover, so Cff's ~11.5 deg
ceiling is no longer being asked to carry the whole result. Raising Cff was
re-tried against #51's remaining light-load failures (87u -> 150u, i.e.
15 pF -> 45 pF) and moved 3 of 15 points, so it was not kept: those points
are on the PSRR-vs-stability frontier that
spec/decision-records/DR-0007-light-load-stability-envelope.md documents, not
short of feedforward zero. The paragraph below is #42's reading of the
pre-#51 design and is kept as written for the record it describes.

Measured, sim/loop-stability/records/ (this record supersedes
20260801-050406-65416d2): Cff materially improves the matrix (most of the
moderate-to-heavy-load, higher-ESR corners now clear both bars, some by a
wide margin), but it does not reach a full pass. The near-0 deg PM floor at
very light load (0-0.1 mA) is NOT fixed by Cff or by any XCc rescaling this
issue tried: at that corner both dominant poles sit at sub-Hz frequencies
(the output pole there is set by the 900 kOhm feedback divider DR-0003
ratifies, not by load), so closing even a fraction of the gap needs a zero
sited at a few hundred Hz -- a feedforward network with the fixed 1.5x
Rtop/(Rtop||Rbot) spacing has a hard ceiling of about 11.5 deg of phase lift
regardless of Cff's value (confirmed empirically at 10 pF and 22 pF), and an
on-chip cap large enough to relocate the zero itself down to that frequency
against a realistic on-chip resistance is one to two orders of magnitude
over the < 0.1 mm^2 core area budget. See the evidence record for the full
worst-corner table and the follow-up issue this hands to the next
compensation iteration.

Pass device Mpass: pfet_03v3, L=0.28u (model minimum), W=2000u (2 mm),
nf=40, m=1. This is a SIMPLIFICATION of the full ~4 mm / 40-unit-cell
sizing the ratified spec calls for (needed to clear 300 mV dropout @
50 mA at the worst corner) -- 2 mm is the guidance's stated acceptable
size for THIS issue's DC-sanity loop-closure test only, at effectively no
load beyond the feedback divider's ~6 uA. The full sizing (and the
unit-cell partitioning a layout needs for matching) is layout-phase work,
out of scope here. NOTE (issue #11): Xilimit's Msense is a 1/40 replica of
Mpass at equal L and equal per-finger width, so re-sizing Mpass without
re-scaling Msense moves the current limit by the same factor.

Current limit (issue #11): Xilimit (design/ldo_ilimit.sch) adds the
constant-current (brickwall) clamp the ratified spec's Current-limit row
calls for, plus the enable gating of its own bias. It attaches to VIN /
VOUT / PASS_GATE / EN / VREF / VSS only -- no new top-level port, no
change to any existing net's topology. See design/ldo_ilimit.sch for the
threshold derivation, the hard-limit-vs-foldback decision, and what is
idealized in it.

Soft start (issue #38): Xsoftstart (design/ldo_softstart.sch) gives the
ratified Startup row its controlled ramp. Like Xilimit it is a clamp on
PASS_GATE -- it holds VOUT to 1.5 * (an internally generated linear
voltage ramp) until that ramp passes VREF, then disengages and hands the
pass gate to Xerramp. It attaches to VIN / FB / PASS_GATE / EN / VREF /
VSS only: no new top-level port, no change to any existing net, and in
particular Men's gate is still EN and Xerramp's INN is still VREF, so
nothing about the settled loop (#9's offset budget, #10's compensation)
moves. Its only touch on FB is one MOS gate, so beta is unchanged. See
design/ldo_softstart.sch for why the ramp is NOT applied to Xerramp's
reference (that amplifier's NMOS input pair has no gain with VOUT near 0,
measured), and spec/decision-records/DR-0006 for the settling-window
amendment the measured ramp-rate spread forces.} -700 -600 0 0 0.28 0.28 {}
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
C {symbols/cap_mim_2f0fF.sym} 750 -250 0 0 {name=Cff model=cap_mim_2f0_m2m3_noshield W=87u L=87u m=1}
C {devices/lab_pin.sym} 750 -280 0 0 {name=l_cff_g sig_type=std_logic lab=VOUT}
C {devices/lab_pin.sym} 750 -220 0 0 {name=l_cff_b sig_type=std_logic lab=FB}
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
C {devices/lab_pin.sym} -100 -400 0 0 {name=l_amp_en sig_type=std_logic lab=EN}
C {ldo_ilimit.sym} 0 200 0 0 {name=Xilimit}
C {devices/lab_pin.sym} -100 150 0 0 {name=l_il_vin sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 100 170 0 0 {name=l_il_vout sig_type=std_logic lab=VOUT}
C {devices/lab_pin.sym} -100 190 0 0 {name=l_il_pg sig_type=std_logic lab=PASS_GATE}
C {devices/lab_pin.sym} -100 210 0 0 {name=l_il_en sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} -100 230 0 0 {name=l_il_vref sig_type=std_logic lab=VREF}
C {devices/lab_pin.sym} -100 250 0 0 {name=l_il_vss sig_type=std_logic lab=VSS}
C {ldo_softstart.sym} 0 500 0 0 {name=Xsoftstart}
C {devices/lab_pin.sym} -100 450 0 0 {name=l_ss_vin sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} -100 470 0 0 {name=l_ss_fb sig_type=std_logic lab=FB}
C {devices/lab_pin.sym} -100 490 0 0 {name=l_ss_pg sig_type=std_logic lab=PASS_GATE}
C {devices/lab_pin.sym} -100 510 0 0 {name=l_ss_en sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} -100 530 0 0 {name=l_ss_vref sig_type=std_logic lab=VREF}
C {devices/lab_pin.sym} -100 550 0 0 {name=l_ss_vss sig_type=std_logic lab=VSS}
