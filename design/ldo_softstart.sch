v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {ldo_softstart -- controlled output ramp at enable. Issue #38.} -1200 -1500 0 0 0.5 0.5 {}
T {WHAT THIS BLOCK DOES

With EN asserted it holds VOUT to 1.5 * SSR, where SSR is a linear voltage
ramp generated on an internal capacitor, until SSR passes VREF -- at which
point this block disengages completely and ldo_core's main loop regulates
1.8 V exactly as it did before. That is the whole soft start: the ratified
Startup row's <= 1 V/ms bound becomes a property of a ramp this block sizes,
instead of a property of how fast Mpass can dump charge into C_out (the #38
finding: 153-289 mA of peak supply current and up to +6.5% overshoot at 62 of
63 corners).

Port order (also the .sym pin order -- do not reorder either file without
updating both, and without re-running design/netlist.py --check):
  VIN        supply, 3.3 V nominal
  FB         ldo_core's feedback-divider midpoint, 2/3 * VOUT. SENSE ONLY:
             this block puts nothing but a MOS gate on that node, so the
             divider ratio, the loop's feedback factor beta and therefore
             #9's offset gain-up and #10's loop gain are all unchanged.
  PASS_GATE  the pass device's gate -- the node this block clamps
  EN         enable, active-high, CMOS level (0 / VIN); the SAME net
             ldo_core, error_amp and ldo_ilimit already gate from
  VREF       the 1.2 V reference -- the ramp's finish line and this block's
             own bias reference
  VSS        ground

WHY A CLAMP ON PASS_GATE AND NOT A RAMP ON THE AMPLIFIER'S REFERENCE

The obvious soft start is to feed error_amp's INN from a ramped copy of VREF
and let the main loop follow it. It does not work on THIS amplifier, and the
failure is measured, not argued: error_amp has an NMOS input pair (MIN1/MIN2,
design/netlist/error_amp.spice), so with VOUT near 0 both of its inputs are
below the pair's common-mode floor, the pair is starved, its first stage has
no gain, and the loop is simply not closed over the bottom of the ramp. A
prototype of exactly that topology, simulated at tt/27 C/3.3 V into the full
50 mA load, releases Men and then free-runs to an 11 mA charging edge in
about 2 us -- the pass device parks at whatever current the dead first stage
happens to leave it at (~12 mA) rather than tracking the ramp, and VOUT jumps
to ~0.4 V before the ramp reference has moved 20 mV. Peak dVout/dt was
10.8 V/ms against the ratified 1 V/ms; the ramp only starts controlling
anything once VOUT is high enough to wake the input pair.

A clamp on PASS_GATE does not have that floor, because the ramp comparison
happens in THIS block, on a PMOS input pair whose common-mode range includes
0 V. So the loop that sets dVout/dt is closed from VOUT = 0 -- which is the
entire requirement.

It also has three properties the reference-ramp version does not:

  * It adds no DC error term. The reference-ramp version puts a follower's
    offset (a few mV) permanently in series with VREF, i.e. permanently
    inside the +/-2% output-accuracy budget, at every corner, forever. This
    block's steady-state footprint on the main loop is one MOS gate on FB,
    plus Mclamp_ss and Cm_ss on PASS_GATE. Mclamp_ss is INTENDED to sit in
    cutoff there (CLG parked at VIN, Vsg = 0) and does at 147 of the 163
    measured points; at the other 16 CLG ends the enable window more than
    0.2 V below VIN (11 of them by more than 0.3 V, worst 0.85 V), i.e.
    Mclamp_ss carries a Vsg rather than none. That is measured, it is not
    what this note originally claimed, and it is adjudicated by
    sim/soft-start/testbench/summarize.py and written up as a caveat in
    sim/soft-start/records/20260801-071013-6026a64.md. Cm_ss's 7.2 pF stays
    on PASS_GATE unconditionally: see HOW THE CLAMP WORKS below.
  * It leaves ldo_core's existing nets alone. #8's Men still has its gate on
    EN, error_amp's INN is still VREF: ldo_core.sch's diff for this issue is
    purely the addition of one instance.
  * It is the same idiom as ldo_ilimit -- PMOS pair, resistor tail, mirror
    load, common-source stage, PMOS clamp sourcing into PASS_GATE -- so the
    two clamps are structurally identical and behave the same way when they
    hand the pass gate back to the main amplifier.

HOW THE RAMP IS GENERATED

  Vbsense_ss/Rss_bias/Mben_ss reproduce ldo_ilimit's VREF-and-a-resistor bias
  generator (same idiom, longer resistor): Iref_ss = VREF/Rss_bias ~ 0.39 uA
  at tt/27 C, and Mben_ss opens the branch's return path when EN = 0 so the
  current is exactly zero while disabled.

  Fss_ramp is a CCCS scaling Iref_ss down by k_ss into SSR -- the same "ideal
  large-ratio mirror standing in for the bandgap-referenced bias generator
  that does not exist in this repo yet" idealization ldo_ilimit's Fbias
  already carries, not a new one. It is deliberately NOT an ideal fixed
  current source: keeping Iref_ss = VREF/R in the expression is what makes
  the resistor's +/-25% corner spread show up in the measured ramp rate
  instead of being hidden by an idealization, which is the whole subject of
  DR-0006.

  Css integrates that current, so SSR is a straight line, not an RC
  exponential. That distinction is the reason the ratified Startup row is
  meetable at all in its ramp-rate clause: an RC reference charged toward
  VREF has its steepest slope at t = 0 and needs 3.9 time constants to get
  inside +/-2%, so the same tau that bounds dVout/dt to 1 V/ms lands the
  settling point at ~7 ms. A constant current into a capacitor spends the
  entire ramp at the bound instead of only the first instant of it.

  Mdis_ss (gate ENB) shorts SSR to VSS whenever the block is disabled, so
  every enable starts from a known 0 V rather than from whatever charge Css
  kept. It is W = 1 um / L = 1 um -- small on purpose: its off-state leakage
  is subtracted from a 2.7 nA ramp current, so a wide reset device would be
  a temperature-dependent error term on the ramp rate.

  Mtop_ss is the ramp's ceiling: a PMOS with its gate on VREF and its source
  on SSR, so it starts sinking the ramp current once SSR is about a Vsg above
  VREF and holds SSR there. Below VREF it is a cutoff device with picoamps in
  it, so it does not bend the part of the ramp that matters. The ceiling only
  has to be ABOVE VREF (so the comparator stays hard-disengaged after
  handover) and BELOW VIN_min (so nothing floats), and it is between those
  two by a wide margin at every corner.

HOW THE CLAMP WORKS

  Mca_ss (gate FB) and Mcb_ss (gate SSR) are a PMOS pair with a resistor tail
  (Rtail_ss via Men_t_ss), loaded by the Mna_ss/Mnb_ss NMOS mirror. PMOS
  inputs are the point: FB and SSR both start at 0 V and this pair works
  there.

    FB > SSR (output ahead of the ramp)  -> I(Mcb_ss) > I(Mca_ss) -> CO rises
      -> Mg2_ss pulls CLG down -> Mclamp_ss sources into PASS_GATE -> the
      pass device backs off -> VOUT falls.
    FB < SSR (output behind the ramp)    -> CO falls -> CLG rises -> the
      clamp lets go -> the main amplifier, which is saturated on the
      more-current side for the whole ramp, gets the pass gate.

  So VOUT is held at 1.5 * SSR by negative feedback the entire time, at any
  load in 0-50 mA and any C_out in DR-0001's window: the loop delivers
  whatever current the load and the capacitor need in order for VOUT to move
  at the ramp's rate, which is exactly what a soft start is.

  Cm_ss is the clamp stage's local compensation, and it is deliberately the
  same 60 um x 60 um plate as Css (7.2 pF). It sits gate-to-drain across
  Mclamp_ss, i.e. it is a Miller capacitor around the clamp device: with
  Rl2_ss's ~6.2 Mohm on CLG it puts this loop's dominant pole far below the
  main loop's, which is the same reason ldo_ilimit's Cc exists -- a SECOND
  feedback loop around the same pass device has to be slow relative to the
  first or the two interact. It is sized against the pass device's own
  Cgd = 3.02 pF (sim/devchar/CONCLUSIONS.md section 3): the compensation
  capacitor has to dominate the pass gate's gate-drain capacitance for the
  pole split to be set by this block rather than by Mpass, and 7.2 pF is
  2.4x it. The cost is stated in design/README.md and repeated here because
  it is the one part of this block that does NOT vanish after hand-over:
  whatever Mclamp_ss ends up doing, Cm_ss is still 7.2 pF hanging on
  PASS_GATE, and that is an added capacitance on a main-loop node that this
  issue does not characterise in AC. Issue #10 owns that loop.

  Rl2_ss/Men_l are the common-source stage's load. The load is in SERIES with
  an EN-gated PMOS switch, not tied straight to VIN as ldo_ilimit's Rl2 is,
  because this block's disabled state parks CLG LOW (below) and a bare
  resistor to the rail would then burn VIN/Rl2 permanently -- issue #38's
  clause 5 names that exact pattern as the easy way to regress the measured
  0.20 uA shutdown Iq.

ENABLE / SHUTDOWN

  Minv_p/Minv_n: the local EN -> ENB inverter, the same two-device idiom
  error_amp and ldo_ilimit each carry their own copy of.
  Mben_ss (gate EN): opens the bias branch -- Iref_ss and the ramp go to 0.
  Men_t_ss (gate ENB): opens the comparator's tail.
  Men_l (gate ENB): opens the common-source stage's load.
  Mdis_ss (gate ENB): resets SSR to 0.
  Mpark_ss (gate ENB): parks CLG at VSS.

  Parking CLG at VSS means the clamp is ON before EN is ever asserted, and it
  is what makes the handover from #8's Men clean: Men releases PASS_GATE
  within a microsecond of the enable edge, and this clamp is already holding
  that node at VIN when it does. There is no window in which the pass gate is
  ungoverned -- which is the window the pre-#38 design fell through.

  Every branch above is off in the disabled state and none of them is a
  resistor to a rail, so the disabled block contributes device leakage only.

WHAT IS IDEALIZED HERE

  Fss_ramp, as above: an ideal CCCS standing in for a large-ratio mirror off
  a bias generator this repo has not designed. A real 1:130 mirror at these
  currents runs in weak inversion, where ratio accuracy is more PVT-sensitive
  than the strong-inversion mirrors elsewhere in this design
  (sim/devchar/CONCLUSIONS.md, matching section). That is why the ramp rate
  is MEASURED across the full 63-point corner matrix and across DR-0001's
  capacitor window (sim/soft-start/records/) rather than asserted from the
  nominal arithmetic here, and why the sizing below sits below the 1 V/ms
  bound at nominal rather than on it.

SIZING AS BUILT

  Everything below is a read-back of the instances in this file after
  bring-up, not a statement of intent, and every derived number is labelled
  either "nominal" (arithmetic from the values above) or "MEASURED" (from the
  163-point sweep in sim/soft-start/records/20260801-071013-6026a64.md).
  Where the two disagree, the measurement wins and the arithmetic is the
  thing that is wrong.

  Rss_bias  ppolyf_u_3k, 1000 squares  ~3.1 Mohm  -> Iref_ss ~ 0.39 uA
  k_ss      0.0060                                -> I_ramp  ~ 2.3 nA
  Css       60 um x 60 um cap_mim_2f0             ~7.2 pF
    => nominal dSSR/dt ~ 0.32 V/ms, so dVout/dt ~ 0.48 V/ms.
       MEASURED at tt/27 C/3.30 V, 1 uF/100 mOhm, 50 mA (corner
       tt_27c_3.30v_1u_0.1_36): 0.4936 V/ms, with startup to 1.764 V in
       3.75 ms. Over all 163 points: 0.296 .. 0.867 V/ms.
  Rtail_ss  ppolyf_u_3k, 600 squares   ~1.86 Mohm -> tail 0.7..1.4 uA
  Rl2_ss    ppolyf_u_3k, 2000 squares  ~6.2 Mohm  (carries ~0 once handed over)
  Cc_ss     25 um x 20 um cap_mim_2f0  ~1.0 pF    CO to VSS
  Cm_ss     60 um x 60 um cap_mim_2f0  ~7.2 pF    CLG to PASS_GATE

  k_ss and Rl2_ss are the two values that moved during bring-up (from 0.0077
  and 1000 squares). k_ss sets the ramp rate directly and was reduced to put
  the fastest corner under the ratified 1 V/ms bound with margin -- the
  measured fastest point is 0.867 V/ms. Rl2_ss is the common-source stage's
  load, so it sets that stage's gain and the pull-up on CLG; it was doubled
  to keep the clamp in control at the corners where Mg2_ss is strongest. Both
  changes are upstream of every number in the record above: the 163 points
  were run against the values printed here, from the frozen netlist snapshot
  sim/soft-start/netlist-snapshots/20260801-071013-6026a64.spice, so the
  record is the authority on what this sizing does and this block is only the
  arithmetic that led to it.

  Capacitor values use the 1.990 fF/um2 measured for cap_mim_2f0 in
  sim/devchar/CONCLUSIONS.md section 3, not the 2.0 fF/um2 of the model name:
  3600 um2 -> 7.16 pF, quoted as 7.2 pF. Css and Cm_ss are the same plate.

  Added enabled quiescent current is the tail plus the bias branch, ~1.5 uA
  at tt/27 C; the common-source stage's load carries no current in the
  settled enabled state because CO ends up at VSS and Mg2_ss ends up off.
  Added area is 7700 um2 of capacitor (Css 3600, Cm_ss 3600, Cc_ss 500) plus
  3600 um2 of poly resistor (1000 + 600 + 2000 squares at W = 1 um), about
  11300 um2 -- roughly 11% of the ratified 0.1 mm2 core-area row. That is a
  real cost, it is dominated by the two 60 x 60 capacitors, and it is called
  out here rather than discovered at layout.} -1200 -1470 0 0 0.28 0.28 {}
C {devices/iopin.sym} -1200 -100 0 0 {name=p_vin lab=VIN}
C {devices/ipin.sym} -1000 -100 0 0 {name=p_fb lab=FB}
C {devices/iopin.sym} -800 -100 0 0 {name=p_pass_gate lab=PASS_GATE}
C {devices/ipin.sym} -600 -100 0 0 {name=p_en lab=EN}
C {devices/ipin.sym} -400 -100 0 0 {name=p_vref lab=VREF}
C {devices/iopin.sym} -200 -100 0 0 {name=p_vss lab=VSS}
C {devices/vsource.sym} 0 -1000 0 0 {name=Vbsense_ss value=0}
C {devices/lab_pin.sym} 0 -1030 0 0 {name=l_vbsensess_p sig_type=std_logic lab=VREF}
C {devices/lab_pin.sym} 0 -970 0 0 {name=l_vbsensess_m sig_type=std_logic lab=BT}
C {symbols/ppolyf_u_3k.sym} 200 -1000 0 0 {name=Rss_bias model=ppolyf_u_3k W=1u L=1000u m=1}
C {devices/lab_pin.sym} 200 -1030 0 0 {name=l_rssbias_p sig_type=std_logic lab=BT}
C {devices/lab_pin.sym} 200 -970 0 0 {name=l_rssbias_m sig_type=std_logic lab=BB}
C {devices/lab_pin.sym} 180 -1000 0 0 {name=l_rssbias_b sig_type=std_logic lab=VSS}
C {symbols/nfet_03v3.sym} 400 -1000 0 0 {name=Mben_ss model=nfet_03v3 L=0.5u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 420 -1030 0 0 {name=l_mbenss_d sig_type=std_logic lab=BB}
C {devices/lab_pin.sym} 380 -1000 0 0 {name=l_mbenss_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 420 -970 0 0 {name=l_mbenss_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 420 -1000 0 0 {name=l_mbenss_b sig_type=std_logic lab=VSS}
C {devices/cccs.sym} 600 -1000 0 0 {name=Fss_ramp vnam=Vbsense_ss value=0.0060}
C {devices/lab_pin.sym} 600 -1030 0 0 {name=l_fssramp_p sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 600 -970 0 0 {name=l_fssramp_m sig_type=std_logic lab=SSR}
C {symbols/cap_mim_2f0fF.sym} 800 -1000 0 0 {name=Css model=cap_mim_2f0_m2m3_noshield W=60u L=60u m=1}
C {devices/lab_pin.sym} 800 -1030 0 0 {name=l_css_g sig_type=std_logic lab=SSR}
C {devices/lab_pin.sym} 800 -970 0 0 {name=l_css_b sig_type=std_logic lab=VSS}
C {symbols/nfet_03v3.sym} 1000 -1000 0 0 {name=Mdis_ss model=nfet_03v3 L=1u W=1u nf=1 m=1}
C {devices/lab_pin.sym} 1020 -1030 0 0 {name=l_mdisss_d sig_type=std_logic lab=SSR}
C {devices/lab_pin.sym} 980 -1000 0 0 {name=l_mdisss_g sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 1020 -970 0 0 {name=l_mdisss_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1020 -1000 0 0 {name=l_mdisss_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 1200 -1000 0 0 {name=Mtop_ss model=pfet_03v3 L=2u W=1u nf=1 m=1}
C {devices/lab_pin.sym} 1180 -1000 0 0 {name=l_mtopss_g sig_type=std_logic lab=VREF}
C {devices/lab_pin.sym} 1220 -970 0 0 {name=l_mtopss_d sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1220 -1030 0 0 {name=l_mtopss_s sig_type=std_logic lab=SSR}
C {devices/lab_pin.sym} 1220 -1000 0 0 {name=l_mtopss_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 0 -600 0 0 {name=Men_t_ss model=pfet_03v3 L=0.5u W=10u nf=1 m=1}
C {devices/lab_pin.sym} -20 -600 0 0 {name=l_mentss_g sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 20 -570 0 0 {name=l_mentss_d sig_type=std_logic lab=TAILP}
C {devices/lab_pin.sym} 20 -630 0 0 {name=l_mentss_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 20 -600 0 0 {name=l_mentss_b sig_type=std_logic lab=VIN}
C {symbols/ppolyf_u_3k.sym} 200 -600 0 0 {name=Rtail_ss model=ppolyf_u_3k W=1u L=600u m=1}
C {devices/lab_pin.sym} 200 -630 0 0 {name=l_rtailss_p sig_type=std_logic lab=TAILP}
C {devices/lab_pin.sym} 200 -570 0 0 {name=l_rtailss_m sig_type=std_logic lab=TAIL}
C {devices/lab_pin.sym} 180 -600 0 0 {name=l_rtailss_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 400 -600 0 0 {name=Mca_ss model=pfet_03v3 L=1u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 380 -600 0 0 {name=l_mcass_g sig_type=std_logic lab=FB}
C {devices/lab_pin.sym} 420 -570 0 0 {name=l_mcass_d sig_type=std_logic lab=CN}
C {devices/lab_pin.sym} 420 -630 0 0 {name=l_mcass_s sig_type=std_logic lab=TAIL}
C {devices/lab_pin.sym} 420 -600 0 0 {name=l_mcass_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 600 -600 0 0 {name=Mcb_ss model=pfet_03v3 L=1u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 580 -600 0 0 {name=l_mcbss_g sig_type=std_logic lab=SSR}
C {devices/lab_pin.sym} 620 -570 0 0 {name=l_mcbss_d sig_type=std_logic lab=CO}
C {devices/lab_pin.sym} 620 -630 0 0 {name=l_mcbss_s sig_type=std_logic lab=TAIL}
C {devices/lab_pin.sym} 620 -600 0 0 {name=l_mcbss_b sig_type=std_logic lab=VIN}
C {symbols/nfet_03v3.sym} 800 -600 0 0 {name=Mna_ss model=nfet_03v3 L=1u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 820 -630 0 0 {name=l_mnass_d sig_type=std_logic lab=CN}
C {devices/lab_pin.sym} 780 -600 0 0 {name=l_mnass_g sig_type=std_logic lab=CN}
C {devices/lab_pin.sym} 820 -570 0 0 {name=l_mnass_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 820 -600 0 0 {name=l_mnass_b sig_type=std_logic lab=VSS}
C {symbols/nfet_03v3.sym} 1000 -600 0 0 {name=Mnb_ss model=nfet_03v3 L=1u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 1020 -630 0 0 {name=l_mnbss_d sig_type=std_logic lab=CO}
C {devices/lab_pin.sym} 980 -600 0 0 {name=l_mnbss_g sig_type=std_logic lab=CO}
C {devices/lab_pin.sym} 1020 -570 0 0 {name=l_mnbss_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1020 -600 0 0 {name=l_mnbss_b sig_type=std_logic lab=VSS}
C {symbols/cap_mim_2f0fF.sym} 1200 -600 0 0 {name=Cc_ss model=cap_mim_2f0_m2m3_noshield W=25u L=20u m=1}
C {devices/lab_pin.sym} 1200 -630 0 0 {name=l_ccss_g sig_type=std_logic lab=CO}
C {devices/lab_pin.sym} 1200 -570 0 0 {name=l_ccss_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 0 -200 0 0 {name=Men_l model=pfet_03v3 L=0.5u W=10u nf=1 m=1}
C {devices/lab_pin.sym} -20 -200 0 0 {name=l_menl_g sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 20 -170 0 0 {name=l_menl_d sig_type=std_logic lab=LP}
C {devices/lab_pin.sym} 20 -230 0 0 {name=l_menl_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 20 -200 0 0 {name=l_menl_b sig_type=std_logic lab=VIN}
C {symbols/ppolyf_u_3k.sym} 200 -200 0 0 {name=Rl2_ss model=ppolyf_u_3k W=1u L=2000u m=1}
C {devices/lab_pin.sym} 200 -230 0 0 {name=l_rl2ss_p sig_type=std_logic lab=LP}
C {devices/lab_pin.sym} 200 -170 0 0 {name=l_rl2ss_m sig_type=std_logic lab=CLG}
C {devices/lab_pin.sym} 180 -200 0 0 {name=l_rl2ss_b sig_type=std_logic lab=VSS}
C {symbols/nfet_03v3.sym} 400 -200 0 0 {name=Mg2_ss model=nfet_03v3 L=1u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 420 -230 0 0 {name=l_mg2ss_d sig_type=std_logic lab=CLG}
C {devices/lab_pin.sym} 380 -200 0 0 {name=l_mg2ss_g sig_type=std_logic lab=CO}
C {devices/lab_pin.sym} 420 -170 0 0 {name=l_mg2ss_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 420 -200 0 0 {name=l_mg2ss_b sig_type=std_logic lab=VSS}
C {symbols/nfet_03v3.sym} 600 -200 0 0 {name=Mpark_ss model=nfet_03v3 L=0.5u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 620 -230 0 0 {name=l_mparkss_d sig_type=std_logic lab=CLG}
C {devices/lab_pin.sym} 580 -200 0 0 {name=l_mparkss_g sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 620 -170 0 0 {name=l_mparkss_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 620 -200 0 0 {name=l_mparkss_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 800 -200 0 0 {name=Mclamp_ss model=pfet_03v3 L=0.5u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 780 -200 0 0 {name=l_mclampss_g sig_type=std_logic lab=CLG}
C {devices/lab_pin.sym} 820 -170 0 0 {name=l_mclampss_d sig_type=std_logic lab=PASS_GATE}
C {devices/lab_pin.sym} 820 -230 0 0 {name=l_mclampss_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 820 -200 0 0 {name=l_mclampss_b sig_type=std_logic lab=VIN}
C {symbols/cap_mim_2f0fF.sym} 900 -200 0 0 {name=Cm_ss model=cap_mim_2f0_m2m3_noshield W=60u L=60u m=1}
C {devices/lab_pin.sym} 900 -230 0 0 {name=l_cmss_g sig_type=std_logic lab=CLG}
C {devices/lab_pin.sym} 900 -170 0 0 {name=l_cmss_b sig_type=std_logic lab=PASS_GATE}
C {symbols/pfet_03v3.sym} 1000 -200 0 0 {name=Minv_p model=pfet_03v3 L=0.5u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 980 -200 0 0 {name=l_minvp_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 1020 -170 0 0 {name=l_minvp_d sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 1020 -230 0 0 {name=l_minvp_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 1020 -200 0 0 {name=l_minvp_b sig_type=std_logic lab=VIN}
C {symbols/nfet_03v3.sym} 1200 -200 0 0 {name=Minv_n model=nfet_03v3 L=0.5u W=2u nf=1 m=1}
C {devices/lab_pin.sym} 1220 -230 0 0 {name=l_minvn_d sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 1180 -200 0 0 {name=l_minvn_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 1220 -170 0 0 {name=l_minvn_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1220 -200 0 0 {name=l_minvn_b sig_type=std_logic lab=VSS}
