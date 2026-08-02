v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {error_amp -- LDO error amplifier (issue #9).
Two-stage OTA with a Type-II (gain-shelf) Miller network and a class-AB\ngate buffer, self-biased, ~11 uA nominal. Compensation and buffer are #51's.} -900 -960 0 0 0.5 0.5 {}
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
                     current sink M2N, into the INTERNAL node BG. Stage 2
                     no longer drives the pass gate directly (issue #51) --
                     it drives the buffer's gate, a ~0.5 pF load instead of
                     the 6.14 pF pass gate, so its own pole sits decades
                     above the loop crossover.
  Buffer   Mbuf,     Class-AB gate driver (issue #51), the "low-impedance
           Mbufb,    gate drive" DR-0001 and spec/architecture-survey.md S5
           Mpgn,     candidate 2 call for. Mbuf is a PMOS source follower
           Rbufb     (gate BG, source OUT, drain VSS, body tied to its own
                     source so there is no body effect on the level shift);
                     Mbufb is its pull-up, a scaled replica of M2P; Mpgn is
                     a small always-on sink. See BUFFER below for why each
                     one is there and what each rail costs.
  Comp     Cc, Rz    Miller network from N1 to OUT, but Rz is deliberately
                     LARGE (6 MOhm, not the ~30 kOhm a nulling resistor
                     would be). Above f_z = 1/(2*pi*Rz*Cc) the shunt
                     feedback impedance is Rz rather than 1/(s*Cc), so the
                     amplifier's gain SHELVES at gm(MIN)*Rz instead of
                     continuing to fall. That shelf is what makes the loop
                     roll off at -20 dB/dec (not -40) where it crosses
                     unity, which is the whole point: see COMPENSATION.
           Cf1,Cf2   Inner Miller cap N1 -> BG across the stage-2 driver
                     M2P (issue #53). Two 12x12 um MIM in SERIES, i.e.
                     ~149 fF: what this device has to be is SMALL, and a
                     series pair reaches it without drawing a MIM below
                     the 5 um the model's own width branch is cut at.
                     Without it the Rz/Cc network's own loop has RHP poles
                     and the cell oscillates -- see LOCAL LOOP below.
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
  stage 2      M2N             ~2 uA   (was ~5 uA: stage 2 now drives only
                                        the buffer gate, so its current was
                                        moved into the buffer -- issue #51)
  buffer       Mbufb + Mpgn    ~3 uA
  total                       ~11 uA against the 10-15 uA error-amp
                               allocation in spec/architecture-survey.md S5.
  Measured 5.4-13.7 uA over PVT (sim/amp-openloop/records/), and the
  ASSEMBLED regulator measures 8.6-21.4 uA (sim/quiescent-current/records/)
  against the ratified < 30 uA row -- LOWER than the 22.4 uA the pre-#51
  design measured, because the current moved out of stage 2 buys more
  pass-gate bandwidth per microamp in the buffer than it did in a
  9 MOhm-output common-source stage.

LOCAL LOOP -- what Cf1/Cf2 fix, and why the cell needs them (issue #53)
Rz/Cc is not only the LDO loop's compensation -- it is a feedback loop in
its own right, from N1 around M2P and the class-AB buffer back to OUT, and
it stays closed when the LDO loop is broken at ERRAMP_OUT/PASS_GATE, which
is exactly the condition sim/loop-stability/ measures in. Above f_z that
loop is closed RESISTIVELY (through Rz), which takes away its own Miller
compensation across the whole band the LDO loop uses. As committed at
b304bd5 it was UNSTABLE: two poles (BG at ~13 kHz, and Rz against N1's
~0.9 pF at ~30 kHz) below a 813x forward gain, so it crossed unity near
500 kHz with no phase left. Measured 21-58 dB of gain peaking at
420-750 kHz with a +180 deg phase ADVANCE (an RHP pole pair) at every
corner, and 3.31 V pk-pk on BG / 2.14 V pk-pk on the pass gate / 372 mV
pk-pk on VOUT in a settled, undriven transient at tt/27C/3.30V and 50 mA
(sim/amp-selfosc/records/, and DR-0008).

Cf1/Cf2 (149 fF in series, N1 -> BG) is a Miller cap around M2P ALONE. It
splits that pair: N1's pole goes down by the Miller factor and BG's goes up
to gm(M2P)/(2*pi*Cgs(Mbuf)) ~ 10 MHz, so the local loop has ONE pole below
its crossover instead of two. Measured after: peak_excess_db -0.36...-0.13
dB at 81 of 81 PVT points (sim/amp-openloop/records/) against a +1 dB bar,
i.e. the amplifier's gain now falls monotonically through the whole
200 kHz - 5 MHz window, and sim/amp-selfosc/ is quiet.

  WHY N1 -> BG AND NOT N1 -> OUT (across Rz). Both stabilise the local loop.
  Taking it to BG encloses one gain stage instead of two, so it needs 3x
  LESS capacitance for the same margin (149 fF vs ~400 fF measured at the
  same peak_excess), which costs 3x less of the amplifier's 1 kHz gain --
  and that gain is the ratified PSRR row (see COMPENSATION). Cc is trimmed
  49u -> 48u so the 1 kHz gain floor keeps its margin: measured 53.60 dB
  worst corner against the 53.5 dB budget line, vs 53.5 dB before.

  WHAT THIS DOES NOT FIX. The local loop's crossover is also the upper
  corner of the gain shelf, f_2 ~ 180 kHz here, and the LDO loop needs the
  shelf to reach its own crossover, which at 50 mA / 0.33 uF is ~6 MHz.
  Both are set by the buffer's gm and stage 2's gm, i.e. by Iq: MEASURED,
  tripling both currents (8.6 -> 16.4 uA, already over the 15 uA amp row)
  moves f_2 only 131 -> 393 kHz. So this cell is stable but its verified
  load range is NARROW -- see design/error_amp.md S6.7 and
  spec/decision-records/DR-0009.

COMPENSATION -- why the Miller network is a gain SHELF (issue #51)
#10's stability record measured the pre-#51 loop as a textbook two-pole
system: the amplifier's Miller-set dominant pole (~2.6 Hz) and the output
pole at VOUT are BOTH far below crossover at every point of DR-0001's
matrix, so the loop rolls off at -40 dB/dec through unity and the phase
margin sits within a couple of degrees of zero everywhere. That is not a
tuning problem. With a plain Miller integrator the loop's crossover is

    f_c = sqrt( beta * UGBW_amp * gm_pass / (2*pi*C_out) )

and PM >= 45 deg needs f_c <= the output pole, which at 50 mA / 0.33 uF
needs UGBW_amp <= 2.3 kHz and at 0 mA / 4.7 uF needs UGBW_amp <= 1 mHz.
Neither is buildable (#51, and spec/decision-records/DR-0007).

Rz = 6 MOhm turns the same two components into a Type-II compensator:

  f < f_z = 1/(2*pi*Rz*Cc) ~ 5.4 kHz   amp is the usual integrator,
                                       gain = gm(MIN)/(2*pi*Cc*f).
                                       This region sets PSRR at 1 kHz.
  f > f_z                              feedback impedance is Rz, so the
                                       amp's gain SHELVES at
                                       A_plat = gm(MIN)*Rz ~ 140.
                                       The loop then rolls off at
                                       -20 dB/dec from the output pole
                                       alone -> PM approaches 90 deg.

The loop therefore crosses unity in the shelf region -- one pole, not two --
at every load from 0.1 mA up. Two hard bounds fix Rz and Cc, and the design
sits between them:

  Rz too large  -> A_plat too large -> the heavy-load crossover
                   beta*A_plat*gm_pass/(2*pi*C_out) climbs past the
                   buffer/BG poles. MEASURED: Rz = 6 MOhm passes 0.1-50 mA
                   at every PVT/cap/ESR point; Rz = 7 MOhm already loses
                   corners at 1-50 mA; Rz = 9 MOhm loses them all.
  Cc too large   -> gm(MIN)/(2*pi*Cc) falls and with it the amp's 1 kHz
                   gain, which is what the ratified PSRR > 50 dB @ 1 kHz
                   row rides on. MEASURED: Cc = 4.80 pF gives 53.5 dB
                   worst-corner amp gain at 1 kHz against a 53.5 dB floor;
                   Cc = 7.4 pF puts psrr_ldo_1k_db at 46 dB, a hard FAIL.

Rz*sqrt(Cc) sets how light a load stays in the shelf region at crossover,
and gm(MIN)/Cc sets the 1 kHz gain, so the two rows pull in opposite
directions on the same two components. This cell sits ON that frontier, not
inside it: the 0 mA / no-external-load column of DR-0001's matrix is on the
far side of it and needs nanofarad-scale on-chip Cc. That is measured, not
asserted -- spec/decision-records/DR-0007-light-load-stability-envelope.md.

BUFFER -- the class-AB gate driver, and why not a plain follower
The pass gate is a 6.14 pF load (sim/devchar/CONCLUSIONS.md S1) hanging on a
~9 MOhm node. In the shelf region the Miller shunt feedback cannot pull that
node's impedance down fast enough (the local loop's own bandwidth runs out
below the LDO crossover), so the pass-gate pole lands BELOW crossover at
heavy load and the loop is unrecoverable there. MEASURED without a buffer,
with everything else identical: worst PM -92 deg at 50 mA / 0.33 uF.

  Mbuf   PMOS source follower, gate BG, source OUT, drain VSS, body tied to
         OUT. Sets the pass-gate node impedance at 1/gm(Mbuf) ~ 20 kOhm
         instead of ~9 MOhm, moving that pole above the loop crossover.
  Mbufb  Its pull-up. NOT a fixed current source: its gate follows N1 (via
         Rbufb) so it is a scaled REPLICA of M2P and turns fully off when
         the loop demands maximum drive. This is what keeps VSS reachable.
         A plain follower with a fixed bias source cannot pull OUT below
         Vgs(Mbuf) -- its bias current has nowhere else to go -- which
         costs a whole |Vtp| of gate drive. MEASURED with a fixed-bias
         follower: the regulator loses regulation entirely at Vin = 2.10 V
         / 50 mA at 8 of 15 dropout corners (Vout runs to tens of volts
         negative). With the replica pull-up, dropout is 300.4-300.9 mV at
         all 15 corners -- the same band as the pre-#51 design.
  Mpgn   Small always-on NMOS sink (~0.4 uA, mirrored from NBIAS). With
         Mbufb off it is the only thing left at OUT, so it defines the DC
         floor at VSS rather than at a Vgs. It is also what makes the node
         non-floating for the operating-point solve.
  Rbufb  5 MOhm in series with Mbufb's gate. Mbufb's gate has to track N1
         at DC (that is the whole turn-off mechanism) but must NOT be a
         signal path: N1 -> Mbufb -> OUT is a feedforward that bypasses the
         compensated stage and re-raises the loop gain above the shelf.
         MEASURED without Rbufb: worst PM -167 deg at 50 mA / 0.33 uF.
         Rbufb against Mbufb's own ~1 pF gate capacitance puts that path's
         pole near 30 kHz, decades below the heavy-load crossover, so the
         device is a DC-tracking current source and nothing more.

BG IS A PORT (issue #55) -- the clamp-arbitration contract

Before #51 this cell drove PASS_GATE from a class-A stage whose SINK was a
~4 uA current source, and design/ldo_softstart.sch and design/ldo_ilimit.sch
were both sized against exactly that: each pulls PASS_GATE up through a
PMOS and only has to out-source a few microamps to win the node. #51's Mbuf
broke that contract silently -- a 150 um/1 um follower sinks as hard as its
Vsg allows, so both clamps lost the node (MEASURED: startup overshoot
63/63 corners over the +2 % bound, peak inrush 366 mA, the limit clamp
engaging at 54/63 corners while settled at 50 mA --
sim/enable-shutdown/records/20260801-200827-84f67b8.md).

BG is exported so a clamp can RELEASE the follower rather than fight it.
Each clamp cell adds a small PMOS from VIN to BG on the same gate as its
existing PASS_GATE clamp device (Mclamp_bg / Mclamp_bg_ss). Both are OFF
whenever the clamp is idle -- CLG rests at VIN -- so they add no DC path
and no static current. OFF is a DC statement only: each drain junction
still loads BG, and measured over the ratified 3240-point loop matrix that
moves phase margin by a median 1.9 deg and crossover by a median 1.3 %,
and drops the DR-0001 pass count 2689 -> 2632
(sim/loop-stability/records/20260802-085331-8a1a9e8.md enumerates every
moved point). When a clamp engages, BG is pulled up, Vgs(Mbuf)
goes to zero, and the clamp's PASS_GATE device is left arbitrating against
Mpgn's ~0.4 uA alone. That is a WEAKER opposition than the pre-#51 4 uA
stage, i.e. the contract is restored with margin.

Polarity contract, and why the clamps must not simply MOVE to BG: BG is the
follower's gate, so BG up = OUT up, and a clamp on BG alone reads like a
complete replacement for a clamp on PASS_GATE. It is not. Mbufb, the only
pull-UP at OUT, is off in exactly the regime the clamps exist for (the loop
demanding maximum drive during startup or an overload), so with the clamp
moved to BG there is nothing left to charge OUT and the clamp has no
authority at all. MEASURED on that variant at tt/27 C/2.97 V: the soft-start
ramp is bypassed entirely (t_startup 32 us against 3683 us pre-#51),
overshoot 2.045 V, the limit clamp saturates at CLG = 2.9 mV and still
cannot hold the node, and the output never settles (vout_pp_late 0.583 V).
The clamp devices on PASS_GATE stay; the BG devices are ADDED alongside.

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
  Mbg_pu         same job for BG, the buffer's gate node, which #51 added
                 (M2P and M2N are both off when disabled, so BG would
                 otherwise float and leave Mbuf's state undefined). BG at
                 VDD with OUT held at VIN by ldo_core's Men puts Vgs = 0
                 on Mbuf. Mbufb and Mpgn need no pull device of their own:
                 Mbufb's gate follows N1 (already pulled to VDD) through
                 Rbufb, and Mpgn's gate is NBIAS (already pulled to VSS).

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
C {devices/iopin.sym} 900 -340 0 0 {name=p_bg lab=BG}

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

C {symbols/ppolyf_u_1k.sym} 200 -400 0 0 {name=Rz model=ppolyf_u_1k W=1u L=6000u m=1}
C {devices/lab_pin.sym} 200 -430 0 0 {name=l_rz_p sig_type=std_logic lab=N1}
C {devices/lab_pin.sym} 200 -370 0 0 {name=l_rz_m sig_type=std_logic lab=NZ}
C {devices/lab_pin.sym} 180 -400 0 0 {name=l_rz_b sig_type=std_logic lab=VSS}

C {symbols/cap_mim_2f0fF.sym} 400 -400 0 0 {name=Cc model=cap_mim_2f0_m2m3_noshield W=48u L=48u m=1}
C {devices/lab_pin.sym} 400 -430 0 0 {name=l_cc_g sig_type=std_logic lab=NZ}
C {devices/lab_pin.sym} 400 -370 0 0 {name=l_cc_b sig_type=std_logic lab=OUT}

C {symbols/cap_mim_2f0fF.sym} 250 -250 0 0 {name=Cf1 model=cap_mim_2f0_m2m3_noshield W=12u L=12u m=1}
C {devices/lab_pin.sym} 250 -280 0 0 {name=l_cf1_g sig_type=std_logic lab=N1}
C {devices/lab_pin.sym} 250 -220 0 0 {name=l_cf1_b sig_type=std_logic lab=NF}

C {symbols/cap_mim_2f0fF.sym} 400 -250 0 0 {name=Cf2 model=cap_mim_2f0_m2m3_noshield W=12u L=12u m=1}
C {devices/lab_pin.sym} 400 -280 0 0 {name=l_cf2_g sig_type=std_logic lab=NF}
C {devices/lab_pin.sym} 400 -220 0 0 {name=l_cf2_b sig_type=std_logic lab=BG}

C {symbols/pfet_03v3.sym} 700 -600 0 0 {name=M2P model=pfet_03v3 L=2u W=150u nf=15 m=1}
C {devices/lab_pin.sym} 680 -600 0 0 {name=l_m2p_g sig_type=std_logic lab=N1}
C {devices/lab_pin.sym} 720 -570 0 0 {name=l_m2p_d sig_type=std_logic lab=BG}
C {devices/lab_pin.sym} 720 -630 0 0 {name=l_m2p_s sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} 720 -600 0 0 {name=l_m2p_b sig_type=std_logic lab=VDD}

C {symbols/nfet_03v3.sym} 700 -150 0 0 {name=M2N model=nfet_03v3 L=4u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 720 -180 0 0 {name=l_m2n_d sig_type=std_logic lab=BG}
C {devices/lab_pin.sym} 680 -150 0 0 {name=l_m2n_g sig_type=std_logic lab=NBIAS}
C {devices/lab_pin.sym} 720 -120 0 0 {name=l_m2n_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 720 -150 0 0 {name=l_m2n_b sig_type=std_logic lab=VSS}

C {symbols/ppolyf_u_1k.sym} 850 -600 0 0 {name=Rbufb model=ppolyf_u_1k W=1u L=5000u m=1}
C {devices/lab_pin.sym} 850 -630 0 0 {name=l_rbufb_p sig_type=std_logic lab=N1}
C {devices/lab_pin.sym} 850 -570 0 0 {name=l_rbufb_m sig_type=std_logic lab=NBP}
C {devices/lab_pin.sym} 830 -600 0 0 {name=l_rbufb_b sig_type=std_logic lab=VSS}

C {symbols/pfet_03v3.sym} 1000 -600 0 0 {name=Mbufb model=pfet_03v3 L=2u W=200u nf=20 m=1}
C {devices/lab_pin.sym} 980 -600 0 0 {name=l_bufb_g sig_type=std_logic lab=NBP}
C {devices/lab_pin.sym} 1020 -570 0 0 {name=l_bufb_d sig_type=std_logic lab=OUT}
C {devices/lab_pin.sym} 1020 -630 0 0 {name=l_bufb_s sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} 1020 -600 0 0 {name=l_bufb_b sig_type=std_logic lab=VDD}

C {symbols/pfet_03v3.sym} 1000 -300 0 0 {name=Mbuf model=pfet_03v3 L=1u W=150u nf=15 m=1}
C {devices/lab_pin.sym} 980 -300 0 0 {name=l_buf_g sig_type=std_logic lab=BG}
C {devices/lab_pin.sym} 1020 -330 0 0 {name=l_buf_d sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1020 -270 0 0 {name=l_buf_s sig_type=std_logic lab=OUT}
C {devices/lab_pin.sym} 1020 -300 0 0 {name=l_buf_b sig_type=std_logic lab=OUT}

C {symbols/nfet_03v3.sym} 1000 -100 0 0 {name=Mpgn model=nfet_03v3 L=8u W=2u nf=1 m=1}
C {devices/lab_pin.sym} 1020 -130 0 0 {name=l_pgn_d sig_type=std_logic lab=OUT}
C {devices/lab_pin.sym} 980 -100 0 0 {name=l_pgn_g sig_type=std_logic lab=NBIAS}
C {devices/lab_pin.sym} 1020 -70 0 0 {name=l_pgn_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1020 -100 0 0 {name=l_pgn_b sig_type=std_logic lab=VSS}

C {symbols/pfet_03v3.sym} 850 -150 0 0 {name=Mbg_pu model=pfet_03v3 L=0.5u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 830 -150 0 0 {name=l_bgpu_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 870 -120 0 0 {name=l_bgpu_d sig_type=std_logic lab=BG}
C {devices/lab_pin.sym} 870 -180 0 0 {name=l_bgpu_s sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} 870 -150 0 0 {name=l_bgpu_b sig_type=std_logic lab=VDD}

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
