v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {error_amp -- LDO error amplifier (issue #9).
Two-stage Miller-compensated OTA, self-biased, ~11 uA nominal.} -900 -960 0 0 0.5 0.5 {}
T {Ports -- the swap-in contract issue #8 ratified (design/README.md,
ldo_erramp_placeholder.sym), plus EN appended by issue #11. Do not reorder
or rename: ldo_core, #10's loop-break bench and #12's testbench suite
instantiate this positionally.
  INP  non-inverting input, wired to FB    in ldo_core
  INN  inverting input,     wired to VREF  in ldo_core
  OUT  drives the PMOS pass-device gate
  VDD  supply (VIN)
  VSS  ground
  EN   enable, active-high, CMOS level (0 / VDD)   <- issue #11

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
  Bias     MB1,Rbias Supply-referenced self-bias, fed through the EN header
                     Mbias_h (see ENABLE): Iref = (VDD - Vgs)/Rbias
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

ENABLE (issue #11 -- the interface decision #9 deferred)
Issue #9 shipped this cell with no EN pin and measured the consequence:
9.24 uA of supply current with the pass device already off
(sim/op-point-sanity/records/20260801-002928-712cb87.md), against a ratified
3 uA shutdown budget, because Men gates the PASS DEVICE and not the
amplifier. #11 owns the shutdown-Iq row, so it makes the call #9 flagged:
add EN and gate the bias INSIDE this cell.

  Minv_p/Minv_n  local inverter, EN -> ENB. Both devices off in either
                 static state (EN is specified as a CMOS level, never
                 mid-rail), so the inverter itself costs no static current.
  Mbias_h        PMOS header between VDD and Rbias's top (RBT), gated by
                 ENB. Kills the ONLY DC path from VDD to VSS in this cell
                 when EN = 0. W = 20u/0.5u so its Ron drops < 5 mV of the
                 ~2.5 V across the 1 Mohm bias resistor when enabled, i.e.
                 < 0.2 % on Iref -- a deliberate over-size, since this
                 device sits directly in the bias-accuracy path #9
                 characterized.
  Mnb_pd         pulls NBIAS to VSS when disabled, so MTAIL and M2N are
                 definitively off rather than left floating on a dead
                 mirror node.
  Mn1_pu, Mnd_pu pull N1 and ND to VDD when disabled (gated by EN itself,
                 exactly like ldo_core's Men), so M2P and the mirror load
                 are definitively off and no node in the cell is left
                 floating for the operating-point solve.

Why gate here rather than put a supply header on this cell in ldo_core:
with the cell's VDD switched off, OUT is still held at VIN by ldo_core's
Men clamp, and M2P's drain-body diode (its body is this cell's VDD) then
FORWARD-BIASES and powers the whole amplifier back up through the diode --
the bias branch keeps drawing microamps out of a supply that is nominally
off. Gating the bias with the rails intact has no such path: every body
stays at its own rail and only device leakage is left.

Disabled state costs 4 devices and nothing static; enabled state is
unchanged except for Mbias_h's < 5 mV Ron drop. Measured both ways in
sim/enable-shutdown/records/ (shutdown Iq) and re-measured against #9's own
budgets in sim/amp-openloop/records/ (no enabled-state regression).

Connectivity is by net label (lab_pin) placed on each device pin, the same
convention ldo_core.sch uses -- no routed wires.} -900 -920 0 0 0.28 0.28 {}

C {devices/ipin.sym} -900 -400 0 0 {name=p_inp lab=INP}
C {devices/ipin.sym} -900 -340 0 0 {name=p_inn lab=INN}
C {devices/opin.sym} 900 -400 0 0 {name=p_out lab=OUT}
C {devices/iopin.sym} -900 -460 0 0 {name=p_vdd lab=VDD}
C {devices/iopin.sym} -900 -280 0 0 {name=p_vss lab=VSS}
C {devices/ipin.sym} -900 -220 0 0 {name=p_en lab=EN}

C {symbols/ppolyf_u_1k.sym} -600 -600 0 0 {name=Rbias model=ppolyf_u_1k W=1u L=1000u m=1}
C {devices/lab_pin.sym} -600 -630 0 0 {name=l_rb_p sig_type=std_logic lab=RBT}
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

C {symbols/pfet_03v3.sym} -600 -150 0 0 {name=Minv_p model=pfet_03v3 L=0.5u W=4u nf=1 m=1}
C {devices/lab_pin.sym} -620 -150 0 0 {name=l_invp_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} -580 -120 0 0 {name=l_invp_d sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} -580 -180 0 0 {name=l_invp_s sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} -580 -150 0 0 {name=l_invp_b sig_type=std_logic lab=VDD}

C {symbols/nfet_03v3.sym} -450 -150 0 0 {name=Minv_n model=nfet_03v3 L=0.5u W=2u nf=1 m=1}
C {devices/lab_pin.sym} -430 -180 0 0 {name=l_invn_d sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} -470 -150 0 0 {name=l_invn_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} -430 -120 0 0 {name=l_invn_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} -430 -150 0 0 {name=l_invn_b sig_type=std_logic lab=VSS}

C {symbols/pfet_03v3.sym} -750 -600 0 0 {name=Mbias_h model=pfet_03v3 L=0.5u W=20u nf=1 m=1}
C {devices/lab_pin.sym} -770 -600 0 0 {name=l_bh_g sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} -730 -570 0 0 {name=l_bh_d sig_type=std_logic lab=RBT}
C {devices/lab_pin.sym} -730 -630 0 0 {name=l_bh_s sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} -730 -600 0 0 {name=l_bh_b sig_type=std_logic lab=VDD}

C {symbols/nfet_03v3.sym} -750 -400 0 0 {name=Mnb_pd model=nfet_03v3 L=0.5u W=10u nf=1 m=1}
C {devices/lab_pin.sym} -730 -430 0 0 {name=l_nbpd_d sig_type=std_logic lab=NBIAS}
C {devices/lab_pin.sym} -770 -400 0 0 {name=l_nbpd_g sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} -730 -370 0 0 {name=l_nbpd_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} -730 -400 0 0 {name=l_nbpd_b sig_type=std_logic lab=VSS}

C {symbols/pfet_03v3.sym} 100 -600 0 0 {name=Mn1_pu model=pfet_03v3 L=0.5u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 80 -600 0 0 {name=l_n1pu_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 120 -570 0 0 {name=l_n1pu_d sig_type=std_logic lab=N1}
C {devices/lab_pin.sym} 120 -630 0 0 {name=l_n1pu_s sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} 120 -600 0 0 {name=l_n1pu_b sig_type=std_logic lab=VDD}

C {symbols/pfet_03v3.sym} -250 -600 0 0 {name=Mnd_pu model=pfet_03v3 L=0.5u W=4u nf=1 m=1}
C {devices/lab_pin.sym} -270 -600 0 0 {name=l_ndpu_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} -230 -570 0 0 {name=l_ndpu_d sig_type=std_logic lab=ND}
C {devices/lab_pin.sym} -230 -630 0 0 {name=l_ndpu_s sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} -230 -600 0 0 {name=l_ndpu_b sig_type=std_logic lab=VDD}
