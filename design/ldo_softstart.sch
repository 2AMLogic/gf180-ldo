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

HOW IT HOLDS VOUT THERE CHANGED IN #189. Issues #38/#43 built a second
feedback loop -- a PMOS comparator on (FB, SSR) driving a PMOS clamp that
sourced into PASS_GATE. #189 deleted that comparator and its clamp
(Mca_ss/Mcb_ss/Mna_ss/Mnb_ss/Cc_ss/Men_l/Rl2_ss/Mg2_ss/Mpark_ss/Mclamp_ss/
Cm_ss/Rz_ss/Mclamp_bg_ss, and the node CLG with them) and replaced it with
CURRENT INJECTION INTO FB. Read the two "WHY" sections below in order: the
first is why #38 did not ramp the amplifier's reference, and the second is
why injecting into FB is not that idea and does not hit its floor.

Port order (also the .sym pin order -- do not reorder either file without
updating both, and without re-running design/netlist.py --check):
  VIN        supply, 3.3 V nominal
  FB         ldo_core's feedback-divider midpoint, 2/3 * VOUT. As of #189
             this block DRIVES that node (Binj_ss sources into it, and
             Mpre_a_ss/Mpre_b_ss pre-charge it to VREF for the first tens of
             microseconds after enable); before #189 it only sensed it. The
             divider ratio, the loop's feedback factor beta and #10's loop
             gain are still untouched in the SETTLED state, because both
             elements are off there -- see "WHAT THIS COSTS THE MAIN LOOP".
             (The .sym still annotates this pin dir=in; that annotation is
             stale as of #189 and only affects the *.PININFO comment line.)
  PASS_GATE  the pass device's gate -- held at VIN by Mhold_ss for the
             startup-hold window, and owned by the main amplifier at all
             other times
  EN         enable, active-high, CMOS level (0 / VIN); the SAME net
             ldo_core, error_amp and ldo_ilimit already gate from
  VREF       the 1.2 V reference -- the ramp's finish line, the injection's
             zero point, and this block's own bias reference
  VSS        ground
  BG         error_amp's output-buffer gate -- held at VIN by Mhold_bg_ss
             for the same window, for the reason #55 established

WHY #38 DID NOT RAMP THE AMPLIFIER'S REFERENCE

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
10.8 V/ms against the ratified 1 V/ms.

WHY INJECTING INTO FB IS NOT THAT IDEA (#189)

Injection moves the ramp to the OTHER input and keeps BOTH inputs at VREF:

  At node FB, with I_inj sourced in,  (VOUT - FB)/Rtop + I_inj = FB/Rbot.
  The main loop drives FB to VREF, so
      VOUT = 1.5 * VREF - I_inj * Rtop.
  Choose  I_inj = (VREF - SSR) / (Rtop||Rbot) = (VREF - SSR) / 200 kohm
  and this collapses to  VOUT = 1.5 * SSR,  with I_inj = 0 exactly when
  SSR = VREF, i.e. exactly when VOUT = 1.8 V.

So FB sits at 1.2 V for the whole ramp -- 1.2 V is INSIDE the NMOS pair's
common-mode range, which is the entire objection above -- and the amplifier
that regulates the ramp is the main one, already compensated for every
output network in DR-0001's window. There is no second loop to acquire
through the pass device's dead zone, which is the ~230 us acquisition lag
#43 measured, could not shrink further, and could only damp (Rz_ss).

The rectification is what makes hand-over clean: SSR finishes ABOVE VREF
(Mtop_ss's ceiling, measured 1.53-2.16 V), so a source-only injection is
hard off after hand-over and contributes exactly zero DC error to the +/-2 %
output-accuracy budget. It does not need a comparator, a switch or a timer to
disengage: it disengages because its own argument goes through zero.

WHAT #189 HAD TO ADD, AND WHY (the enable edge is not free)

Pinning FB is necessary and NOT sufficient. Measured on the injection-only
prototype at ff/125 C/2.97 V, 4.7 uF/500 mOhm, 50 mA: 238 mA of capacitor
current 4 us after the enable edge. Two mechanisms, both at the edge, both
independent of the ramp:

  (1) FB cannot slew instantly. Cff (15 pF, ldo_core) plus the input pair's
      own gate capacitance sit on that node, and 6 uA into ~17 pF needs
      several microseconds to cover 1.2 V. error_amp's bias is up ~0.5 us
      after the edge. For those few microseconds the amplifier sees FB far
      BELOW VREF and does what it should: turns the pass device fully on.
  (2) Even with FB pinned, error_amp wakes from its disabled state with N1
      and ND parked at VDD (Mn1_pu/Mnd_pu), so M2P is off, BG is pulled down
      by M2N, and Mbuf -- #51's source follower -- slams PASS_GATE down
      before the first stage has settled. Measured on its own (FB pre-charged,
      no hold): 240 mA.

The three elements below fix (1) and (2) and cost nothing in the settled
state:

  Mpre_a_ss/Mpre_b_ss PRE-CHARGE FB TO VREF through two series PMOS: one
    gated by HG (on while HG is low, i.e. from the enable edge) and one gated
    by ENB (on only while enabled, so the pair is a pulse, not a level, and
    the disabled block still draws nothing). This kills (1) outright: FB is
    at VREF within nanoseconds of the edge instead of microseconds. The
    switch carries ZERO current at its own operating point -- with VOUT = 0
    and SSR = 0 the injection's 6 uA is exactly the divider's draw at
    FB = VREF -- so opening it is glitch-free by construction, not by tuning.

  Mhold_ss/Mhold_bg_ss HOLD PASS_GATE AND BG AT VIN for the first tens of
    microseconds, on the shared gate HG. This is the same idiom the #38 clamp
    used (a PMOS from VIN onto PASS_GATE, plus #55's companion PMOS onto BG
    so Mbuf is out of the contest) and it is here for the same reason #38
    parked CLG low: there must be no window in which the pass gate is
    ungoverned. It fixes (2).

  Rh_ss/Ch_ss and Rr_ss/Cr_ss SEQUENCE THE STARTUP. HG is EN through an RC;
    SD is ENB through an identical RC. Their ORDER is the load-bearing part:

      t = 0          enable edge. Injection on, FB pre-charged to VREF,
                     PASS_GATE and BG held at VIN, ramp held at 0 by Mdis_ss
                     (whose gate is SD, not ENB, as of #189).
      t ~ 1.3 * tau  HG has risen to VIN - |Vtp|: the hold releases, softly,
                     because an RC's approach to its asymptote is slow where
                     it matters.
      t ~ 1.5 * tau  SD has fallen to Vtn: Mdis_ss lets go and the ramp
                     starts -- AFTER the hold has released, so VOUT is not
                     already behind its target when the main loop takes the
                     pass gate.

    The ramp must start after the hold releases or the lag accumulated during
    the hold is recovered as an inrush edge. The two RCs are deliberately the
    SAME R and the SAME C (both ppolyf_u_3k 4870 squares, both 70 x 70
    cap_mim), so the ordering is a ratio of matched devices and holds at every
    corner even though tau itself moves +/-25 % with the resistor corner.
    That ordering, not the absolute delay, is what the design depends on.

    HOW tau WAS CHOSEN (measured, at ff/125 C/2.97 V, 4.7 uF/500 mOhm, 50 mA,
    full 9 ms window, ratified bound 5 mA):

      tau        icap_peak    what limits it
      ------     ---------    --------------------------------------------
       3 us       105 mA      hold releases before FB is even up
      15 us        23 mA      hold releases before error_amp has settled
      50 us      4.87 mA      just inside the bound, no margin
      146 us     3.77 mA      as built; also drops peak dVout/dt to
                              0.80 V/ms, i.e. under the ratified ramp bound

    Bigger tau is monotonically better for inrush and monotonically worse for
    t_startup, because the ramp-release delay (~1.5 * tau) is dead time added
    to every startup. 146 us buys 24 % margin on the ratified inrush clause
    and costs ~0.2 ms of t_startup; that trade, and its effect on DR-0006's
    already-failing 3 ms clause, is quantified in
    sim/soft-start/records/20260906-200639-bfc4a0a.md.

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

  Mdis_ss shorts SSR to VSS whenever the block is disabled AND for the
  startup-hold window on top of that (gate SD, above). It is W = 1 um /
  L = 1 um -- small on purpose: its off-state leakage is subtracted from a
  2.3 nA ramp current, so a wide reset device would be a temperature-dependent
  error term on the ramp rate. That leakage is also why SD's slow decay is
  visible as a small (~2-4 %) reduction in the measured ramp slope: while SD
  is between Vtn and ~Vtn-0.2 V, Mdis_ss is still shunting a few percent of
  the ramp current.

  Mtop_ss is the ramp's ceiling: a PMOS with its gate on VREF and its source
  on SSR, so it starts sinking the ramp current once SSR is about a Vsg above
  VREF and holds SSR there. Below VREF it is a cutoff device with picoamps in
  it, so it does not bend the part of the ramp that matters. The ceiling only
  has to be ABOVE VREF (so the injection stays hard-rectified after
  handover) and BELOW VIN_min (so nothing floats), and it is between those
  two by a wide margin at every corner.

ENABLE / SHUTDOWN

  Minv_p/Minv_n: the local EN -> ENB inverter, the same two-device idiom
  error_amp and ldo_ilimit each carry their own copy of.
  Mben_ss (gate EN): opens the bias branch -- Iref_ss and the ramp go to 0.
  Mdis_ss (gate SD): resets SSR to 0 (SD is high whenever ENB is).
  Mpre_b_ss (gate ENB): opens the FB pre-charge path.
  Binj_ss: gated on EN in its own expression (see WHAT IS IDEALIZED HERE).
  Mhold_ss/Mhold_bg_ss (gate HG): HG sits at 0 while disabled, so the hold
  is ON before EN is ever asserted -- the same guarantee #38 got by parking
  CLG at VSS. Men (ldo_core) releases PASS_GATE within a microsecond of the
  enable edge and this hold is already on that node when it does.

  Every branch above is off in the disabled state and none of them is a
  resistor to a rail: Rh_ss returns to EN (0 V when disabled) and Rr_ss to
  ENB through Cr_ss, so both are capacitively terminated and carry no DC.
  The disabled block contributes device leakage only.

WHAT THIS COSTS THE MAIN LOOP

  In the settled enabled state every element #189 added is off:
  Mhold_ss/Mhold_bg_ss are in cutoff (HG at VIN -- adjudicated at every
  corner by the bench's own hg_end predicate), Mpre_a_ss/Mpre_b_ss are open
  (ENB high... low, and HG at VIN), and Binj_ss is rectified off because SSR
  finishes above VREF. What remains on FB is two PMOS drain junctions and one
  injection-source terminal, i.e. tens of femtofarads -- against Cff's 15 pF.
  That is strictly LESS than what #38/#43 left behind, which was Cm_ss's
  7.2 pF and Rz_ss's 1.55 Mohm permanently hanging on PASS_GATE.

  The AC consequence of removing Cm_ss/Rz_ss from PASS_GATE is real and is
  NOT characterised here: sim/soft-start measures the large-signal startup
  (including 163 points of settled ripple, which is what would show a newly
  unstable main loop) and nothing else. The AC evidence is
  sim/loop-stability/'s, and a re-run there belongs to #51/#176.

WHAT IS IDEALIZED HERE

  Fss_ramp, as before: an ideal CCCS standing in for a large-ratio mirror off
  a bias generator this repo has not designed.

  Binj_ss, NEW IN #189 and the bigger idealization of the two: a behavioural
  source implementing

      I(VIN -> FB) = max(0, (VREF - SSR) * 5.0e-6) * (EN > 1.4 V)

  i.e. a linear transconductor of 5 uA/V, a source-only rectifier, and an
  enable gate, in one element. Each of those three is realizable and the
  intended implementation is standard -- two VIN-referenced resistor-
  degenerated PMOS branches whose gates are SSR and VREF, their difference
  taken in a diode-connected PMOS (which IS the rectifier: it simply turns
  off when SSR passes VREF) and mirrored into FB -- but it is not built here,
  and this cell therefore does NOT yet characterise:
    * the transconductor's own PVT spread and its Vgs-matching error, which
      the two branches' unequal currents make ~3 % at SSR = 0 and zero at
      hand-over;
    * the quiescent current it adds (the settled Iq row has ~8 uA of headroom
      at its binding corner, ff/125 C/3.63 V, per
      sim/quiescent-current/records/);
    * its area.
  The device-level build is tracked by issue #191.

  The 5.0e-6 coefficient is 1.5/Rtop, i.e. it is a RATIO to the feedback
  divider, not an absolute transconductance. That is deliberate and is the
  one property the eventual device-level build must preserve: if the
  injection's reference resistor does not track Rtop, the VOUT/SSR gain moves
  with the resistor corner, and at -25 % the ramp would START at +0.45 V
  instead of 0. ldo_core's divider is itself modelled as two ideal resistors,
  so expressing the injection as a ratio to it is consistent with how the
  divider ratio is already treated (README.md note 3).

SIZING AS BUILT

  Everything below is a read-back of the instances in this file after
  bring-up, not a statement of intent.

  Rss_bias  ppolyf_u_3k, 1000 squares  ~3.1 Mohm  -> Iref_ss ~ 0.39 uA
  k_ss      0.0060                                -> I_ramp  ~ 2.3 nA
  Css       60 um x 60 um cap_mim_2f0             ~7.2 pF
    => nominal dSSR/dt ~ 0.32 V/ms, so dVout/dt ~ 0.48 V/ms.
  Binj_ss   5.0e-6 A/V = 1.5 / Rtop (see above)
  Rh_ss     ppolyf_u_3k, 4870 squares  ~15.1 Mohm  EN -> HG
  Ch_ss     70 um x 70 um cap_mim_2f0  ~9.75 pF    HG -> VSS   (tau ~147 us)
  Rr_ss     ppolyf_u_3k, 4870 squares  ~15.1 Mohm  ENB -> SD
  Cr_ss     70 um x 70 um cap_mim_2f0  ~9.75 pF    SD -> VSS   (tau ~147 us)
  Mhold_ss     pfet 20 um / 0.5 um   VIN -> PASS_GATE, gate HG
  Mhold_bg_ss  pfet 10 um / 0.5 um   VIN -> BG,        gate HG
  Mpre_a_ss    pfet 10 um / 0.5 um   VREF -> FBP,      gate HG
  Mpre_b_ss    pfet 10 um / 0.5 um   FBP  -> FB,       gate ENB

  Added enabled quiescent current is the bias branch only, ~0.4 uA at
  tt/27 C: the two RCs are capacitively terminated, the hold and pre-charge
  devices end in cutoff, and Binj_ss rectifies to zero. (The transconductor
  that will replace Binj_ss will NOT be free -- see WHAT IS IDEALIZED HERE.)

  Added area is 13 350 um2 of capacitor (Css 3600, Ch_ss 4900, Cr_ss 4900)
  plus 10 740 um2 of poly resistor (1000 + 4870 + 4870 squares at W = 1 um),
  about 24 100 um2 -- roughly 24 % of the ratified 0.1 mm2 core-area row,
  against about 11 800 um2 for the #38/#43 clamp this replaces. That is a
  real cost, it is dominated by the two delay RCs, and it is called out here
  rather than discovered at layout. The delay RCs are at their minimum-area
  R/C split for the tau they implement (equal resistor and capacitor area);
  buying the tau back with a smaller area needs a current-source ramp or a
  MOS pseudo-resistor in place of the RC, which is a follow-on, not this
  issue's scope.} -1200 -1470 0 0 0.28 0.28 {}
C {devices/iopin.sym} -1200 -100 0 0 {name=p_vin lab=VIN}
C {devices/ipin.sym} -1000 -100 0 0 {name=p_fb lab=FB}
C {devices/iopin.sym} -800 -100 0 0 {name=p_pass_gate lab=PASS_GATE}
C {devices/ipin.sym} -600 -100 0 0 {name=p_en lab=EN}
C {devices/ipin.sym} -400 -100 0 0 {name=p_vref lab=VREF}
C {devices/iopin.sym} -200 -100 0 0 {name=p_vss lab=VSS}
C {devices/iopin.sym} 0 -100 0 0 {name=p_bg lab=BG}
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
C {devices/lab_pin.sym} 980 -1000 0 0 {name=l_mdisss_g sig_type=std_logic lab=SD}
C {devices/lab_pin.sym} 1020 -970 0 0 {name=l_mdisss_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1020 -1000 0 0 {name=l_mdisss_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 1200 -1000 0 0 {name=Mtop_ss model=pfet_03v3 L=2u W=1u nf=1 m=1}
C {devices/lab_pin.sym} 1180 -1000 0 0 {name=l_mtopss_g sig_type=std_logic lab=VREF}
C {devices/lab_pin.sym} 1220 -970 0 0 {name=l_mtopss_d sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1220 -1030 0 0 {name=l_mtopss_s sig_type=std_logic lab=SSR}
C {devices/lab_pin.sym} 1220 -1000 0 0 {name=l_mtopss_b sig_type=std_logic lab=VIN}
C {devices/bsource.sym} 0 -600 0 0 {name=Binj_ss VAR=I FUNC="'max(0, (v(VREF) - v(SSR)) * 5.0e-6) * (v(EN) > 1.4)'" m=1}
C {devices/lab_pin.sym} 0 -630 0 0 {name=l_binjss_p sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 0 -570 0 0 {name=l_binjss_m sig_type=std_logic lab=FB}
C {symbols/pfet_03v3.sym} 200 -600 0 0 {name=Mpre_a_ss model=pfet_03v3 L=0.5u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 180 -600 0 0 {name=l_mpreass_g sig_type=std_logic lab=HG}
C {devices/lab_pin.sym} 220 -570 0 0 {name=l_mpreass_d sig_type=std_logic lab=FBP}
C {devices/lab_pin.sym} 220 -630 0 0 {name=l_mpreass_s sig_type=std_logic lab=VREF}
C {devices/lab_pin.sym} 220 -600 0 0 {name=l_mpreass_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 400 -600 0 0 {name=Mpre_b_ss model=pfet_03v3 L=0.5u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 380 -600 0 0 {name=l_mprebss_g sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 420 -570 0 0 {name=l_mprebss_d sig_type=std_logic lab=FB}
C {devices/lab_pin.sym} 420 -630 0 0 {name=l_mprebss_s sig_type=std_logic lab=FBP}
C {devices/lab_pin.sym} 420 -600 0 0 {name=l_mprebss_b sig_type=std_logic lab=VIN}
C {symbols/ppolyf_u_3k.sym} 600 -600 0 0 {name=Rh_ss model=ppolyf_u_3k W=1u L=4870u m=1}
C {devices/lab_pin.sym} 600 -630 0 0 {name=l_rhss_p sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 600 -570 0 0 {name=l_rhss_m sig_type=std_logic lab=HG}
C {devices/lab_pin.sym} 580 -600 0 0 {name=l_rhss_b sig_type=std_logic lab=VSS}
C {symbols/cap_mim_2f0fF.sym} 800 -600 0 0 {name=Ch_ss model=cap_mim_2f0_m2m3_noshield W=70u L=70u m=1}
C {devices/lab_pin.sym} 800 -630 0 0 {name=l_chss_g sig_type=std_logic lab=HG}
C {devices/lab_pin.sym} 800 -570 0 0 {name=l_chss_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 1000 -600 0 0 {name=Mhold_ss model=pfet_03v3 L=0.5u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 980 -600 0 0 {name=l_mholdss_g sig_type=std_logic lab=HG}
C {devices/lab_pin.sym} 1020 -570 0 0 {name=l_mholdss_d sig_type=std_logic lab=PASS_GATE}
C {devices/lab_pin.sym} 1020 -630 0 0 {name=l_mholdss_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 1020 -600 0 0 {name=l_mholdss_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 1200 -600 0 0 {name=Mhold_bg_ss model=pfet_03v3 L=0.5u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 1180 -600 0 0 {name=l_mholdbgss_g sig_type=std_logic lab=HG}
C {devices/lab_pin.sym} 1220 -570 0 0 {name=l_mholdbgss_d sig_type=std_logic lab=BG}
C {devices/lab_pin.sym} 1220 -630 0 0 {name=l_mholdbgss_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 1220 -600 0 0 {name=l_mholdbgss_b sig_type=std_logic lab=VIN}
C {symbols/ppolyf_u_3k.sym} 0 -200 0 0 {name=Rr_ss model=ppolyf_u_3k W=1u L=4870u m=1}
C {devices/lab_pin.sym} 0 -230 0 0 {name=l_rrss_p sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 0 -170 0 0 {name=l_rrss_m sig_type=std_logic lab=SD}
C {devices/lab_pin.sym} -20 -200 0 0 {name=l_rrss_b sig_type=std_logic lab=VSS}
C {symbols/cap_mim_2f0fF.sym} 200 -200 0 0 {name=Cr_ss model=cap_mim_2f0_m2m3_noshield W=70u L=70u m=1}
C {devices/lab_pin.sym} 200 -230 0 0 {name=l_crss_g sig_type=std_logic lab=SD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=l_crss_b sig_type=std_logic lab=VSS}
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
