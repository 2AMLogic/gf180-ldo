v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {error_amp -- LDO error amplifier (issue #9).
Two-stage Miller-compensated OTA, self-biased, ~11 uA nominal.} -900 -960 0 0 0.5 0.5 {}
T {Ports -- the swap-in contract issue #8 ratified (design/README.md,
ldo_erramp_placeholder.sym). Do not reorder or rename: ldo_core, #10's
loop-break bench and #12's testbench suite instantiate this positionally.
  INP  non-inverting input, wired to FB    in ldo_core
  INN  inverting input,     wired to VREF  in ldo_core
  OUT  drives the PMOS pass-device gate
  VDD  supply (VIN)
  VSS  ground

TOPOLOGY -- full rationale, budgets and corner results in design/error_amp.md
  Stage 1  MIN1/MIN2 NMOS input pair on tail MTAIL, PMOS mirror load
                     MLD1/MLD2. INP drives MIN2, the mirror-OUTPUT side, so
                     the single inversion in stage 2 makes INP non-inverting
                     overall -- the polarity the contract fixes.
  Stage 2  M2P       PMOS common-source driver from VDD into the NMOS
                     current sink M2N. Both rails are reachable: OUT pulls
                     to within ~1 mV of VSS (pass device on hard at the
                     dropout test point) and to within ~2 mV of VDD (pass
                     device off). A PMOS-input / NMOS-driver arrangement
                     could only reach VDD - Vdsat, leaving residual Vsg on
                     the pass device at no load.
  Comp     Cc, Rz    Miller cap with a nulling resistor. Cc sets
                     UGBW = gm(MIN)/(2*pi*Cc); Rz ~ (1/gm(M2P))*(1+CL/Cc)
                     puts the zero near the OUT-node pole instead of
                     leaving it in the right half plane. CL is the measured
                     6.14 pF pass-gate Cgg (sim/devchar/CONCLUSIONS.md S1).
  Bias     MB1,Rbias Supply-referenced self-bias: Iref = (VDD - Vgs)/Rbias
                     through the diode-connected NMOS MB1, whose gate NBIAS
                     mirrors to MTAIL (1:1) and M2N (5:3). No start-up
                     circuit is needed: unlike a beta-multiplier this
                     topology has no zero-current degenerate state. Rbias is
                     ppolyf_u_1k; Rz is ppolyf_u (-27.9 ppm/degC, the flavour
                     sim/devchar/CONCLUSIONS.md S2 reserves for absolute
                     values).

WHY AN NMOS INPUT PAIR (the load-bearing headroom argument)
The feedback node sits at VREF = 1.2 V and the loop must still regulate at
the dropout test point Vin = 2.10 V (README note 4). A PMOS pair would need
VDD >= VCM + |Vsg| + Vdsat(tail) = 1.2 + 1.03 + 0.18 = 2.41 V at ss/-40 degC
(|Vtp| from sim/devchar/CONCLUSIONS.md S1) and would starve at 2.10 V. The
NMOS pair's headroom is referenced to VCM and ground instead: TAIL sits
~0.3-0.5 V above VSS at every corner, independent of VDD. The cost is that
this amp needs VCM >~ 1.0 V, i.e. a ~1.2 V reference -- which is the
reference DR-0003 assumes when it puts the offset gain-up 1/beta at
Vout/Vref = 1.5. ldo_core's divider is set to beta = 2/3 to match.

CURRENT BUDGET (nominal tt/27C/3.3V; measured values across PVT in
sim/amp-openloop/records/):
  bias branch  Rbias + MB1     ~3 uA
  stage 1      MTAIL           ~3 uA
  stage 2      M2N             ~5 uA
  total                       ~11 uA against the 10-15 uA error-amp
                               allocation in spec/architecture-survey.md S5.

NO ENABLE PORT. The ratified 5-port interface has no EN pin, so this cell
draws bias current whenever VDD is present. ldo_core's Men clamp turns the
pass device off but does not gate this cell, so the ratified
"shutdown Iq < 3 uA" row cannot be met without gating this cell's supply or
renegotiating the pinout to add EN. Flagged to #11, which owns shutdown
characterization -- see design/error_amp.md "Handoffs".

Connectivity is by net label (lab_pin) placed on each device pin, the same
convention ldo_core.sch uses -- no routed wires.} -900 -920 0 0 0.28 0.28 {}

C {devices/ipin.sym} -900 -400 0 0 {name=p_inp lab=INP}
C {devices/ipin.sym} -900 -340 0 0 {name=p_inn lab=INN}
C {devices/opin.sym} 900 -400 0 0 {name=p_out lab=OUT}
C {devices/iopin.sym} -900 -460 0 0 {name=p_vdd lab=VDD}
C {devices/iopin.sym} -900 -280 0 0 {name=p_vss lab=VSS}

C {symbols/ppolyf_u_1k.sym} -600 -600 0 0 {name=Rbias model=ppolyf_u_1k W=1u L=1000u m=1}
C {devices/lab_pin.sym} -600 -630 0 0 {name=l_rb_p sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} -600 -570 0 0 {name=l_rb_m sig_type=std_logic lab=NBIAS}
C {devices/lab_pin.sym} -620 -600 0 0 {name=l_rb_b sig_type=std_logic lab=VSS}

C {symbols/nfet_03v3.sym} -600 -400 0 0 {name=MB1 model=nfet_03v3 L=4u W=6u nf=1 m=1}
C {devices/lab_pin.sym} -580 -430 0 0 {name=l_mb1_d sig_type=std_logic lab=NBIAS}
C {devices/lab_pin.sym} -620 -400 0 0 {name=l_mb1_g sig_type=std_logic lab=NBIAS}
C {devices/lab_pin.sym} -580 -370 0 0 {name=l_mb1_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} -580 -400 0 0 {name=l_mb1_b sig_type=std_logic lab=VSS}

C {symbols/nfet_03v3.sym} -300 -150 0 0 {name=MTAIL model=nfet_03v3 L=4u W=6u nf=1 m=1}
C {devices/lab_pin.sym} -280 -180 0 0 {name=l_mt_d sig_type=std_logic lab=TAIL}
C {devices/lab_pin.sym} -320 -150 0 0 {name=l_mt_g sig_type=std_logic lab=NBIAS}
C {devices/lab_pin.sym} -280 -120 0 0 {name=l_mt_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} -280 -150 0 0 {name=l_mt_b sig_type=std_logic lab=VSS}

C {symbols/nfet_03v3.sym} -400 -350 0 0 {name=MIN1 model=nfet_03v3 L=6u W=60u nf=6 m=1}
C {devices/lab_pin.sym} -380 -380 0 0 {name=l_min1_d sig_type=std_logic lab=ND}
C {devices/lab_pin.sym} -420 -350 0 0 {name=l_min1_g sig_type=std_logic lab=INN}
C {devices/lab_pin.sym} -380 -320 0 0 {name=l_min1_s sig_type=std_logic lab=TAIL}
C {devices/lab_pin.sym} -380 -350 0 0 {name=l_min1_b sig_type=std_logic lab=VSS}

C {symbols/nfet_03v3.sym} -100 -350 0 0 {name=MIN2 model=nfet_03v3 L=6u W=60u nf=6 m=1}
C {devices/lab_pin.sym} -80 -380 0 0 {name=l_min2_d sig_type=std_logic lab=N1}
C {devices/lab_pin.sym} -120 -350 0 0 {name=l_min2_g sig_type=std_logic lab=INP}
C {devices/lab_pin.sym} -80 -320 0 0 {name=l_min2_s sig_type=std_logic lab=TAIL}
C {devices/lab_pin.sym} -80 -350 0 0 {name=l_min2_b sig_type=std_logic lab=VSS}

C {symbols/pfet_03v3.sym} -400 -600 0 0 {name=MLD1 model=pfet_03v3 L=8u W=8u nf=1 m=1}
C {devices/lab_pin.sym} -420 -600 0 0 {name=l_mld1_g sig_type=std_logic lab=ND}
C {devices/lab_pin.sym} -380 -570 0 0 {name=l_mld1_d sig_type=std_logic lab=ND}
C {devices/lab_pin.sym} -380 -630 0 0 {name=l_mld1_s sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} -380 -600 0 0 {name=l_mld1_b sig_type=std_logic lab=VDD}

C {symbols/pfet_03v3.sym} -100 -600 0 0 {name=MLD2 model=pfet_03v3 L=8u W=8u nf=1 m=1}
C {devices/lab_pin.sym} -120 -600 0 0 {name=l_mld2_g sig_type=std_logic lab=ND}
C {devices/lab_pin.sym} -80 -570 0 0 {name=l_mld2_d sig_type=std_logic lab=N1}
C {devices/lab_pin.sym} -80 -630 0 0 {name=l_mld2_s sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} -80 -600 0 0 {name=l_mld2_b sig_type=std_logic lab=VDD}

C {symbols/ppolyf_u.sym} 200 -400 0 0 {name=Rz model=ppolyf_u W=1u L=109u m=1}
C {devices/lab_pin.sym} 200 -430 0 0 {name=l_rz_p sig_type=std_logic lab=N1}
C {devices/lab_pin.sym} 200 -370 0 0 {name=l_rz_m sig_type=std_logic lab=NZ}
C {devices/lab_pin.sym} 180 -400 0 0 {name=l_rz_b sig_type=std_logic lab=VSS}

C {symbols/cap_mim_2f0fF.sym} 400 -400 0 0 {name=Cc model=cap_mim_2f0_m2m3_noshield W=39u L=39u m=1}
C {devices/lab_pin.sym} 400 -430 0 0 {name=l_cc_g sig_type=std_logic lab=NZ}
C {devices/lab_pin.sym} 400 -370 0 0 {name=l_cc_b sig_type=std_logic lab=OUT}

C {symbols/pfet_03v3.sym} 700 -600 0 0 {name=M2P model=pfet_03v3 L=2u W=150u nf=15 m=1}
C {devices/lab_pin.sym} 680 -600 0 0 {name=l_m2p_g sig_type=std_logic lab=N1}
C {devices/lab_pin.sym} 720 -570 0 0 {name=l_m2p_d sig_type=std_logic lab=OUT}
C {devices/lab_pin.sym} 720 -630 0 0 {name=l_m2p_s sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} 720 -600 0 0 {name=l_m2p_b sig_type=std_logic lab=VDD}

C {symbols/nfet_03v3.sym} 700 -150 0 0 {name=M2N model=nfet_03v3 L=4u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 720 -180 0 0 {name=l_m2n_d sig_type=std_logic lab=OUT}
C {devices/lab_pin.sym} 680 -150 0 0 {name=l_m2n_g sig_type=std_logic lab=NBIAS}
C {devices/lab_pin.sym} 720 -120 0 0 {name=l_m2n_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 720 -150 0 0 {name=l_m2n_b sig_type=std_logic lab=VSS}
