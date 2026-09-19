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

THE INJECTION IS NOW REAL DEVICES, AND THE MIRROR IS CASCODED (#246).
#189 built the injection as one behavioural source (Binj_ss). #191 replaced
it, for one release, with a device-level transconductor
(Rgma_ss/Mgma_ss/Mgmd_ss/Rgmb_ss/Mgmb_ss/Mgmm_ss/Mgmr_ss/Mgmo_ss/Mgme_ss)
whose output mirror was NOT cascoded; #231 reverted that to Binj_ss because
the uncascoded mirror had two independent PVT-wide failure modes (an
acquisition-transient inrush spike, and a persistent settled-accuracy leak
into FB). `spec/decision-records/DR-0023-softstart-injection-mirror-
topology.md` root-caused both to ONE thing -- the mirror's two legs do not
see the same drain voltage -- and ratified the fix (PR #217, merged
2026-09-18): cascode Mgmo_ss against Mgmr_ss. #246 is that implementation.
Binj_ss is gone; the chain below is the same one #191 built PLUS the two
cascode devices DR-0023 ratifies, Mgmrc_ss (reference leg, diode-connected)
and Mgmc_ss (output leg). Read "HOW THE INJECTION IS GENERATED, AS DEVICES"
for the topology, "WHAT THE CASCODE FIXED, AND WHAT IT DID NOT" for the
measured outcome (including the two targets it does NOT reach), and
"#191'S UNCASCODED ATTEMPT (REVERTED BY #231)" for the historical record
of why no amount of resizing the uncascoded chain could have worked.

AND THE BRANCHES' OWN BIAS IS NOW GATED TOO (#259). The cascode rectifies
what the transconductor SOURCES; it does not switch off what the
transconductor BURNS. Both degeneration branches kept standing a DC current
after hand-over, measured as a +0.004...+7.18 uA Iq adder (worst at
ff_125c_3.63v) against a ratified < 30 uA row with 1.29 uA of headroom left.
#259 adds two devices -- Mgmg_ss, a PMOS between VIN and the branches' new
shared supply node VING, gated by the mirror's OWN reference node GMRM, and
Rgmg_ss, a 450 kohm bleed across it -- so the branches lose their supply as
a SIDE EFFECT of the cutoff event DR-0023 already ratified, with no
comparator, no timer, no new threshold and nothing new on FB.
`spec/decision-records/DR-0028-softstart-injection-branch-supply-gating.md`
is the record; read "HOW THE BRANCH SUPPLY IS GATED AFTER HAND-OVER" and
"WHY Rgmg_ss IS NOT OPTIONAL" below for the mechanism and its one real
hazard.

Port order (also the .sym pin order -- do not reorder either file without
updating both, and without re-running design/netlist.py --check):
  VIN        supply, 3.3 V nominal
  FB         ldo_core's feedback-divider midpoint, 2/3 * VOUT. As of #189
             this block DRIVES that node (the injection element -- Mgmc_ss's
             drain as of #246, Binj_ss before it -- sources into it, and
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
  Mgme_ss (gate EN): breaks the injection transconductor's ground return, so
  both its PMOS branches stand down and the mirror stops sourcing into FB.
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
  (ENB high... low, and HG at VIN), and the injection mirror is rectified off
  because SSR finishes above VREF. What remains on FB is two PMOS drain
  junctions -- Mpre_b_ss's, and (as of #246) Mgmc_ss's in place of the
  behavioural source's zero-capacitance terminal -- i.e. tens of femtofarads,
  against Cff's 15 pF. The cascode does NOT add a junction to FB: Mgmc_ss's
  drain REPLACES Mgmo_ss's on that node rather than joining it, so the count
  on FB is the same as the uncascoded chain's. That is strictly LESS than
  what #38/#43 left behind, which was Cm_ss's 7.2 pF and Rz_ss's 1.55 Mohm
  permanently hanging on PASS_GATE.

  MEASURED, #246 (targets T6 and T7, design/softstart_injection_
  compensation.md section 3). AC-opening Mgmc_ss's drain from FB while
  holding the DC operating point bit-identical (a 1 GH series inductor is a
  short at DC; the landed VOUT and I_inj agree to every printed digit on both
  sides) moves the main loop by 0.00 deg of phase margin and 0.00 dB of gain
  margin at tt_27c_3.30v, device/sink/ssr=1.15, 1 uF/100 mOhm -- at most
  0.0015 dB / 0.0030 deg anywhere in 0.01 Hz to 1 GHz, i.e. below the
  numerical floor, so no pole or zero is fitted. T6's bar is 2 deg / 1 dB.
  The same run's capacitance ladder puts FB's own budget at 10 pF in the
  settled-ish sink state and 3 pF at the hold-release ramp state, against
  T7's 1 pF bar and this element's tens of femtofarads. Both targets PASS
  and neither regresses against the uncascoded chain's +0.053 deg / +0.01 dB.
  One corner and two ramp states, not a PVT-wide restatement -- see
  sim/soft-start/records/20260918-190207-8a59d23.md section 5.

  The AC consequence of removing Cm_ss/Rz_ss from PASS_GATE is real and is
  NOT characterised here: sim/soft-start measures the large-signal startup
  (including 163 points of settled ripple, which is what would show a newly
  unstable main loop) and nothing else. The AC evidence is
  sim/loop-stability/'s, and a re-run there belongs to #51/#176.

  UPDATE (#196): that AC evidence now exists, for the hand-over state and not
  only the settled one --
  sim/soft-start-loop-gain/records/20260910-015601-2387ece.md, and the
  recommendation it feeds, design/softstart_injection_compensation.md.

HOW THE INJECTION IS GENERATED, AS DEVICES (#191, CASCODED BY #246/DR-0023)

  This section describes the LIVE implementation. There is no behavioural
  injection source in this cell any more.

  #189 built the injection as one behavioural source:

      I(VIN -> FB) = max(0, (VREF - SSR) * 5.0e-6) * (EN > 1.4 V)

  i.e. a linear transconductor of 5 uA/V, a source-only rectifier, and an
  enable gate, in one element. #191 replaced it with the device-level
  implementation #189 already named as the intended one: two VIN-referenced,
  resistor-degenerated PMOS branches with SSR and VREF on their gates,
  differenced in a diode-connected PMOS (which IS the rectifier), mirrored
  into FB.

    Rgma_ss/Mgma_ss   the SSR branch: VING -> Rgma_ss -> GMSA -> Mgma_ss
                      (gate SSR) -> GMIA. Current Ia = (VING - SSR - Vsg)/R,
                      and VING is VIN less Mgmg_ss's own drop, which is tens
                      of millivolts while the element is working and is a
                      COMMON-MODE term on both branches -- see "HOW THE
                      BRANCH SUPPLY IS GATED AFTER HAND-OVER". Both branches
                      hung directly off VIN before #259.
                      large when SSR is near 0 V and falling as SSR rises.
                      Mgma_ss's body is tied to its OWN source (GMSA), not
                      VIN: the 200 kohm degeneration resistor drops up to
                      ~1.6 V across Rgma_ss at SSR = 0, and body = VIN would
                      put a large, CURRENT-DEPENDENT reverse body bias on
                      Mgma_ss that Mgmb_ss's branch (a much smaller IR drop,
                      since Ib stays roughly fixed) would not share equally --
                      measured to cost ~31 % of the intended coefficient at
                      SSR = 0 (5.0e-6 A/V design target; body = VIN measured
                      ~3.4e-6 A/V-equivalent). body = own-source removes the
                      body effect from both branches entirely (Vsb = 0
                      always), which is what the ~3 % residual noted below
                      assumes.
    Mgmd_ss           diode-connected NMOS (gate=drain=GMIA) that turns Ia
                      into a gate-voltage reference at GMIA.
    Rgmb_ss/Mgmb_ss   the VREF branch, built identically (including the same
                      body = own-source fix, on Mgmb_ss's body -> GMSB): VING
                      -> Rgmb_ss -> GMSB -> Mgmb_ss (gate VREF) -> GMSUM,
                      carrying a FIXED current Ib = (VING - VREF - Vsg)/R,
                      injected directly into GMSUM rather than through a
                      mirror.
    Mgmm_ss           mirrors GMIA's bias (1:1 with Mgmd_ss) and sinks Ia
                      from GMSUM to GMVSS.
    Mgmr_ss/Mgmrc_ss  the reference leg of the mirror, a DIODE-CONNECTED
                      CASCODE STACK from VIN down to GMSUM: Mgmr_ss
                      (gate=drain=GMRM, source=VIN) on top of Mgmrc_ss
                      (gate=drain=GMSUM, source=GMRM). GMSUM's KCL is
                      Ib + I(stack) = Ia, so I(stack) = Ia - Ib =
                      (VREF - SSR)/R for SSR < VREF (both branches share R
                      and are degenerated off the SAME VIN, so VIN and the
                      branches' own Vsg cancel in the difference -- the
                      residual from the two branches' Vsg not matching
                      exactly is the transconductor's own error, measured
                      below). For SSR > VREF, Ia < Ib and the stack would
                      need to source negative current to balance GMSUM's
                      KCL -- it cannot, so BOTH its devices go into cutoff
                      and I(stack) clips to zero. THIS is the rectifier: a
                      property of the topology, not a separate comparator.
                      Mgmrc_ss is new in #246; DR-0023 is what puts it here.
    Mgmo_ss/Mgmc_ss   the output leg, the SAME stack mirrored: Mgmo_ss
                      (gate GMRM, source VIN, drain GMOD) under Mgmc_ss
                      (gate GMSUM, source GMOD, drain FB), sourcing into FB
                      in the same "VIN -> FB" direction Binj_ss carried.
                      Mgmc_ss is new in #246 and is the whole point of
                      DR-0023: because Mgmc_ss and Mgmrc_ss are matched and
                      carry the same current, |Vgs(Mgmc_ss)| = |Vgs(Mgmrc_ss)|,
                      so V(GMOD) = V(GMRM) and Mgmo_ss's |Vds| equals
                      Mgmr_ss's BY CONSTRUCTION rather than by coincidence.
                      Uncascoded, those two |Vds| differed by 0.95-1.61 V and
                      grew one-for-one with VIN (DR-0023's table); that is the
                      error term every #191 sizing sweep failed to move, and
                      it is ~0 here.
                      Mgmc_ss's body, like Mgmrc_ss's, is tied to its OWN
                      source (GMOD / GMRM) for the same reason Mgma_ss's is:
                      Vsb = 0 on both cascodes is what makes their |Vgs| match
                      rather than differ by a body-effect term that tracks
                      neither leg.
    Mgme_ss           the enable gate: an NMOS (gate EN) between GMVSS and
                      VSS, shared by Mgmd_ss and Mgmm_ss. With it open
                      (EN = 0) neither NMOS has a return path, so DC current
                      in both PMOS branches goes to zero in steady state --
                      GMIA, GMRM and GMSUM float toward VIN, all four mirror
                      devices see ~0 Vsg and nothing is sourced into FB. This
                      is the same "break the branch's ground return with one
                      EN-gated NMOS" idiom Mben_ss already uses on Rss_bias.
    Mgmg_ss/Rgmg_ss   the branch-supply gate (#259): a PMOS in series between
                      VIN and VING, the new shared supply node BOTH
                      degeneration resistors now hang off, with a 450 kohm
                      ppolyf_u_3k bleed (Rgmg_ss) permanently across it.
                      Mgmg_ss's gate is GMRM -- the mirror's own reference
                      node, NOT a new signal -- so it throttles off as a
                      consequence of the same cutoff event that rectifies the
                      mirror. See the next section.

  HOW THE BRANCH SUPPLY IS GATED AFTER HAND-OVER (#259, DR-0028). Everything
  above rectifies the transconductor's OUTPUT: once Ia < Ib the Mgmr_ss/
  Mgmrc_ss stack is in cutoff and nothing is sourced into FB. It does not
  rectify the transconductor's own BIAS. Both branches kept carrying
  (VIN - |Vsg| - V(gate))/200 kohm forever, which is the +7.18 uA worst-corner
  Iq adder the note under SIZING AS BUILT measures. Mgmg_ss/Rgmg_ss recover
  most of it WITHOUT adding a threshold, a comparator or a timer:

    Pre-release (SSR < VREF, Ia > Ib, the stack conducting). GMRM is the
    stack's own top diode node and sits a full |Vgs(Mgmr_ss)| below VIN --
    deepest exactly at the START of the ramp, where Ia, and therefore the
    branch current that matters, is largest. Mgmg_ss sees that same |Vgs| as
    its Vsg, is in deep triode at these single-digit-uA currents, and passes
    VIN through to VING with a drop of tens of millivolts. That drop is a
    COMMON-MODE term: it lands on Ia and Ib alike, and the element's output
    is their DIFFERENCE, so what it perturbs is the two branches' Vsg
    mismatch (a second-order term), not the (VREF - SSR)/R law itself. The
    measured T2/T3 movement is under 0.5 % -- see the record.

    Post-release (SSR > VREF, Ia < Ib). The stack goes into cutoff -- this is
    DR-0023's ratified rectification-by-cutoff, unchanged and not
    reimplemented -- so its reference current collapses and GMRM rises toward
    VIN. Mgmg_ss's Vsg = VIN - V(GMRM) collapses with it and the branches
    lose their low-impedance supply. This is the whole mechanism: the gate
    signal is an EXISTING internal mirror node, so there is no new threshold
    to inherit T4's PVT spread (1.200...2.025 V today) and nothing new on FB.

  WHY Rgmg_ss IS NOT OPTIONAL, AND WHY THE RECOVERY IS PARTIAL ON PURPOSE.
  The loop just described is REGENERATIVE: starving the branches lowers Ia,
  which lowers the stack's reference current, which raises GMRM, which
  starves the branches harder. Left unbounded it has a second, non-physical
  operating point, and that is measured rather than feared --
  spec/decision-records/DR-0027 prototyped exactly this mechanism WITHOUT a
  bleed and found no physical DC solution at ss_-40c_2.97v (the coldest,
  slowest corner, where the branches' own currents are already smallest);
  ngspice's dynamic-gmin, true-gmin and source-stepping continuations all
  failed there and the pseudo-transient fallback landed on VOUT = -0.075 V.
  Rgmg_ss bounds the loop by construction: however hard Mgmg_ss is off, the
  branches are still fed through 450 kohm, so GMIA / GMRM / GMSUM can never
  become undetermined and the regenerative loop cannot run away. The price is
  that the post-release branch current is throttled rather than zeroed --
  450 kohm in series with the 200 kohm degeneration, i.e. roughly a 2.8x
  reduction rather than a 100 % one -- which is why the measured recovery is
  about 5 uA of the 7.18 uA adder at the binding corner and not all of it. A
  larger bleed recovers more and is untested; DR-0028 says so explicitly.

  THE HEADROOM TRAP THIS AVOIDS: at SSR = 0 (the start of every ramp), a PMOS
  gated by SSR has its source only a Vsg above ground -- if that branch's own
  current were sensed by an NMOS diode sitting at its DRAIN (the "obvious"
  place, mirroring the way Mgmd_ss senses GMIA here), the NMOS diode would
  need its own Vgs of headroom BELOW that already-thin margin, and the branch
  cannot deliver it. Both PMOS diodes in this design (the Mgmr_ss/Mgmrc_ss
  stack, and Mgmd_ss's role is filled by an NMOS only because GMIA sits well
  above ground once Ia's own IR drop across Rgma_ss is accounted for --
  verified in simulation, not assumed) are sensed at the VIN end instead:
  Mgmr_ss's source is VIN itself, so the stack always has a full VIN worth of
  headroom regardless of where SSR sits. Mgmb_ss's branch (gate VREF, not SSR)
  never approaches this floor since VREF is fixed at 1.2 V, so its own
  diode-sensing analogue was not needed -- its current is taken directly into
  GMSUM rather than mirrored.

  WHERE THE CASCODE'S HEADROOM COMES FROM, AND WHAT IT COSTS GMSUM. On the
  OUTPUT leg the arithmetic is DR-0023's: at the binding minimum-supply
  corner VIN - V(FB) = 2.97 - 1.2 = 1.77 V is available, Mgmo_ss needs
  |Vds| ~ |Vgs| ~ 0.82 V to match its reference leg, and the ~0.95 V left
  over is 5-9x a pfet_03v3's |Vdsat| at these single-digit-uA currents. That
  is the check DR-0023 made and it holds as built.

  DR-0023 did NOT check the other side of the same change, so this note
  records it: stacking a second diode-connected device in the REFERENCE leg
  pushes V(GMSUM) DOWN by one |Vgs|, from VIN - |Vgs| to VIN - 2|Vgs|. GMSUM
  is also Mgmb_ss's drain, and a PMOS with its gate at VREF saturates only
  while its drain stays below VREF + |Vtp| ~ 1.9 V. Uncascoded, GMSUM sat at
  2.15 V (DR-0023's own table, tt_27c_2.97v) -- i.e. Mgmb_ss was in TRIODE,
  which is one more reason the reference current it sets was never as clean
  as the (VREF - SSR)/R expression above assumes. Cascoded, GMSUM sits about
  a |Vgs| lower, which moves Mgmb_ss TOWARD saturation rather than away from
  it. It is therefore not a cost at the low-supply end; at the high-supply,
  low-current end (VIN = 3.63 V with the mirror near cutoff, where both
  |Vgs| fall back toward |Vtp|) GMSUM rises again and Mgmb_ss can re-enter
  triode. That is measured, not argued: it is visible in the per-corner
  hand-over transfer as the residual-injection and release-point spread this
  cell still has at 3.63 V and 125 C (see "WHAT THE CASCODE FIXED, AND WHAT
  IT DID NOT").

WHAT THE CASCODE FIXED, AND WHAT IT DID NOT

  Measured by #246, all against the same DR-0024 cap sizing so the only
  difference from the superseded records is the two cascode devices:

    sim/soft-start/records/20260918-190207-8a59d23.md
      163-point PVT transient matrix + the 63-corner T1-T5 hand-over transfer
      + the ideal-ramp A/B, superseding 20260915-103035-18f664f.md
    sim/quiescent-current/records/20260918-190801-8a59d23.md
      81-point Iq re-run, superseding 20260915-234352-077e15b.md

  FIXED -- the DC transfer defect DR-0023 root-caused, comprehensively:

    T5, the loop in regulation at every ramp state: 37/63 corners VIOLATED
      uncascoded, 0/63 cascoded. This is the headline. The mirror no longer
      over-injects into FB at the bottom of the ramp, so the error amplifier
      never rails and the pass device never parks off. Every ramp state now
      has a loop around it.
    Settled output error: -141.26 mV worst uncascoded, -1.78 mV worst
      cascoded -- a 79x reduction, and now inside the ratified +/-2 %
      (+/-36 mV) accuracy allocation by 20x rather than failing it by 4x.
    Residual injection at hand-over: +170...+4125 nA uncascoded,
      +35...+1433 nA cascoded (2.9x better at the worst corner).
    Release point: 1.250...2.300 V uncascoded and NEVER releasing at 2/63
      corners; 1.200...2.025 V cascoded and releasing at 63/63.
    The sim/startup/sim/quiescent-current settled-accuracy failures #231
      reverted this cell over are GONE: vout_full at ff_125c_3.63v reads
      1.79357 V cascoded against 1.56863 V uncascoded (threshold 1.7 V), and
      at sf_125c_3.63v 1.79721 V against 1.65874 V. Both corners PASS.
    Convergence: 8/163 transient points never reached 1.764 V at all
      uncascoded; 0/163 cascoded. Worst settling 1.72525 ms -> 1.28724 ms.

  NOT REACHED -- the absolute-accuracy targets, and this is the R4 trigger:

    T1 (residual <= 50 nA above VREF)        1/63 corners pass
    T2 (I_inj at SSR=0 = 6.00 +/- 0.10 uA)   0/63; measured 4.985...5.807 uA
    T3 (transconductance -5.00 uA/V +/-5 %)  0/63; measured -4.53...-3.52
    T4 (release exactly at V(SSR) = 1.200 V) 1/63

    All four are IMPROVED and none is MET. Per DR-0023's own Consequences
    section and design/softstart_injection_compensation.md section 3 (R4),
    this is the documented outcome in which the next lever is the 300 kohm
    transimpedance, not a seventh sizing iteration of the element -- and that
    is a topology decision needing its own decision record. #246 does not
    take it; it measures and reports the shortfall.

  MADE WORSE -- the hold-release acquisition transient, and the reason is T2:

    Inrush at C_eff = 1 uF, against the 5 mA bound: 18/79 points clean
      uncascoded, 0/83 clean cascoded (worst 314.9 mA). Uncascoded, the
      clean points were ALL at VIN = 3.30/3.63 V (15 of 39) and none at
      2.97 V (0 of 21); cascoded, none at any supply.

    That pattern is the mechanism, not a coincidence. The loop's DC target
    at the instant Mhold_ss releases is

        VOUT(target) = 1.5 * VREF - I_inj(SSR=0) * Rtop
                     = (6.00 uA - I_inj(SSR=0)) * 300 kohm,

    which is EXACTLY T2's error expressed as a voltage. Cascoded, I_inj(0)
    is 4.985...5.807 uA at every one of the 63 corners -- always BELOW
    6.00 uA -- so that target is always positive, +58...+305 mV, and the
    loop acquires it through a 2000 um pass device in about a microsecond:
    1 uF times 0.2 V in 1 us is 200 mA. Uncascoded, the mirror's
    drain-voltage error made it OVER-inject at high VIN (DR-0023's table:
    +1.35 uA of excess at tt_27c_3.30v, +2.54 uA at tt_27c_3.63v), which
    makes the same target NEGATIVE -- the pass device simply stays off and
    nothing is acquired. Those corners were not clean because the element
    was good; they were clean because it was wrong in the direction that
    hides this edge, at the price of T5 (the loop open, the amplifier
    railed) at 37/63 corners.

    So the cascode did not introduce a new transient failure mode. It
    removed the error that was masking an OLD one, and the old one is a
    direct function of T2. Nothing that leaves T2 unmet can fix it: at the
    +/-0.10 uA T2 allows, the acquisition step is at most +/-30 mV, which is
    the level the ideal Binj_ss element already demonstrated clean.

    design/softstart_injection_compensation.md section 4's open arithmetic
    (a 2.1x voltage difference producing a 356x current difference) is
    answered by the same observation: the acquisition current is NOT
    proportional to the step, because it is slew-limited by the loop and the
    pass device, not step-limited. #246's ideal-ramp A/B measures that
    directly -- forcing V(SSR) from an ideal source, so the ramp node's own
    dynamics and source impedance are removed, leaves the spike essentially
    unchanged, which rules the ramp node out as the mechanism and leaves the
    hold-release step itself. See the record for the per-corner numbers.

#191'S UNCASCODED ATTEMPT (REVERTED BY #231) -- HISTORICAL RECORD

  Everything from here down to "WHAT IS IDEALIZED HERE" is a record of the
  chain ABOVE MINUS the two cascode devices -- what #191 landed (dce8d73),
  what #231 reverted (8fff168), and why. It is kept in full because it is
  what establishes that no amount of RESIZING could have fixed it, which is
  what makes cascoding (a topology change, DR-0023) the right move rather
  than one more sizing attempt. Read the per-measurement outcomes here as
  statements about the UNCASCODED chain; "WHAT THE CASCODE FIXED, AND WHAT IT
  DID NOT" below states which of them #246 closes and which it does not.

KNOWN REGRESSION OF THE UNCASCODED CHAIN (#191): A REAL INJECTION ELEMENT
DESTABILIZED THE HOLD-RELEASE TRANSIENT AT MOST OF THE PVT MATRIX

  This was the single biggest finding of #191. It is documented in this much
  detail because the natural next step (resize the transconductor) made it
  WORSE, not better, and that cost real time to discover.

  Corroborated again by issue #212/DR-0024's 163-point sweep (resizing only
  Css/Ch_ss/Cr_ss -- this section's transconductor is untouched): the same
  A/B check, re-run at sf/-40 C/2.97 V/1 uF/100 mOhm/50 mA, reads
  icap_peak = 231.1 mA against `main`'s own committed (pre-#212) netlist and
  271.9 mA against this record's resized one -- both wildly over the 5 mA
  budget, at the SAME order of magnitude, confirming (not merely repeating)
  that this transient is a #191 property this issue's ramp-rate resize does
  not move. The same sweep's nominal corner (tt/27 C/3.30 V) stays clean on
  both netlists (1.19 mA pre-resize, 4.76 mA post-resize, both under the
  5 mA/1 uF bound), matching "clean at nominal, not at most other points"
  above. See sim/soft-start/records/20260915-103035-18f664f.md's own
  "Pre-existing #191 regression" section for the full corner-by-corner
  breakdown this issue's record carries.

  Binj_ss (the #189 behavioural source) is electrically a ZERO-CAPACITANCE,
  ZERO-DELAY current source: it has no drain/gate/source junctions and no
  propagation lag through a bias node. Every device-level replacement tried
  here -- the as-built Mgma_ss/Mgmd_ss/.../Mgmo_ss chain at its ORIGINAL
  documented sizing (pfet/nfet 4 um / 1 um throughout), the same chain scaled
  up while holding W/L fixed (2x, 4x), and the same chain with Mgmr_ss/Mgmo_ss
  deliberately resized to trade active-region accuracy for lower off-state
  leakage -- reproduces a large (10x-50x over the ratified 5 mA bound)
  capacitor-current spike at the moment Mhold_ss releases PASS_GATE to the
  main loop, at MOST corners away from nominal VIN (3.30 V). This was
  confirmed to be a #191 REGRESSION, not a pre-existing #38/#43/#189 issue, by
  running the IDENTICAL corner (tt/-40 C/2.97 V, 1 uF/100 mOhm/50 mA) against
  main's own committed Binj_ss-based netlist side by side with this cell's:
  the Binj_ss deck reads icap_peak = 0.468 mA (clean); this cell's, at its
  cleanest tried sizing, reads 166.7 mA at the same corner. The two decks
  differ ONLY in design/netlist/ldo_softstart.spice's injection element.

  What was tried and what it did:
    * Original documented sizing (pfet/nfet 4u/1u, this file's committed
      state): clean at tt/27 C/3.30 V (the corner every earlier debugging pass
      happened to check first) but NOT at most other points, including the
      main matrix's own tt/-40 C/2.97 V/1 uF/100 mOhm/50 mA point above.
    * Scaling Mgmr_ss/Mgmo_ss UP while holding their W/L ratio fixed (2x, 4x):
      preserves the 1:1 mirror gain and does not visibly change the
      acquisition transient (still breaks at the same corners), and barely
      moves the SEPARATE settled-leakage finding below (a few mV per
      doubling) -- not a useful lever either way.
    * Changing Mgmr_ss/Mgmo_ss's W/L ratio (bigger L, or smaller W, at fixed
      L): makes the acquisition transient WORSE, monotonically, the further
      the ratio moves from the original 4:1 -- e.g. 1u/3u (a 25 % W cut, the
      most conservative ratio change tried) still breaks badly at off-nominal
      VIN even though it looked clean at the one nominal-VIN corner it was
      first checked against. A ratio change also does not track cleanly with
      "more L is safer" or "less L is safer" -- 1.33u/4u (same ratio as
      1u/3u, reached by raising L instead of cutting W) is measurably WORSE
      than 1u/3u at the identical nominal-VIN corner, so the effect is not a
      simple function of W/L alone.
    * A series decoupling resistor between Mgmo_ss's drain and FB (10 kohm,
      100 kohm, 1 Mohm): does not damp the transient at any of the three
      values tried, and at 100 kohm/1 Mohm it additionally corrupts the DC
      injection current (the resistor's own IR drop, at microamp-level
      currents, moves FB off VREF), so this is a dead end on both counts.
    * Mtop_ss's ramp ceiling (raising it, via L, to buy the separate
      settled-leakage margin below): confirmed to NOT touch the acquisition
      transient (Mtop_ss only matters near handover, ~ms into the ramp; the
      acquisition glitch is at ~300 us), so it is orthogonal to this finding,
      not a fix for it.

  What is NOT yet known: the root cause. GMSUM (the transconductor's own bias
  node) is observed to stay essentially flat through the entire glitch in
  every trace taken, which argues against "the transconductor's own node is
  slewing too slowly" as the mechanism. The working hypothesis, not yet
  substantiated by a proper AC/loop-stability sweep, is that ANY nonzero
  parasitic capacitance the real transconductor adds to FB (the "tens of
  femtofarads" already called out under WHAT THIS COSTS THE MAIN LOOP) is
  enough to destabilize the main loop's hold-release transient, because #189
  removed Cm_ss/Rz_ss (the #38/#43 clamp's own PASS_GATE compensation)
  without adding anything in its place, on the argument that Binj_ss's own
  zero parasitics meant nothing needed replacing. That argument is falsified
  by this finding: apparently the margin left on PASS_GATE after #189 is thin
  enough that it only tolerates an EXACTLY zero-parasitic FB driver, which no
  real circuit is. sim/loop-stability/ (owned by #51/#176) is the right place
  to characterise this properly; it was OUT OF SCOPE for #191 per #189's own
  scope note under WHAT THIS COSTS THE MAIN LOOP, but #191 shows that note's
  premise (soft-start evidence stands in for AC evidence) no longer holds once
  Binj_ss is gone.

  UPDATE (#196) -- THAT WORKING HYPOTHESIS IS MEASURED AND NOT SUPPORTED.
  sim/soft-start-loop-gain/records/20260910-015601-2387ece.md puts this cell
  inside a Tian dual-injection loop-gain deck at pinned ramp states, over the
  full 63-point PVT grid, against a frozen pre-#195 Binj_ss netlist. Opening
  Mgmo_ss's drain from FB in AC only (DC operating point bit-identical) is
  worth +0.053 deg of phase margin at the worst corner, and FB is measured to
  tolerate at least 1 pF before either margin moves by the #182/#185
  cross-invocation class -- against the "tens of femtofarads" this cell adds.
  What the same record does find is a DC transfer defect: I_inj(SSR=0) is
  +5.32...+8.88 uA against the 6.00 uA the divider can absorb, so the loop is
  OUT of regulation low on the ramp at 37 of 63 corners; the rectification
  point moves ~0.92 V of SSR per volt of VIN, traced to the Mgmr_ss->Mgmo_ss
  mirror seeing 0.95...1.61 V of drain-voltage mismatch; and the 467 nA it
  still injects when settled is exactly the -141 mV of settled output error
  measured here. See design/softstart_injection_compensation.md for the
  numeric targets and why a Cm_ss/Rz_ss-class network is NOT the fix. Nothing
  in this cell is changed by #196.

  This cell SHIPPED, for one release, at the ORIGINAL documented sizing
  (pfet/nfet 4u/1u throughout the transconductor, Mtop_ss unchanged) with
  the body-tie fix above, because every other sizing tried made the
  acquisition transient no better and sometimes worse. sim/soft-start's own
  record for that period reports the resulting inrush failures in full, by
  corner, rather than narrowing the swept matrix to hide them. #231 (below)
  is why it no longer ships that way.

WHAT IS IDEALIZED HERE

  Fss_ramp: an ideal CCCS standing in for a large-ratio mirror off a bias
  generator this repo has not designed. It is now the ONLY idealization left
  in this cell's injection path.

  THE INJECTION ITSELF IS NO LONGER IDEALIZED (#246). #189's behavioural
  source

      I(VIN -> FB) = max(0, (VREF - SSR) * 5.0e-6) * (EN > 1.4 V)

  packed a 5 uA/V linear transconductor, a source-only rectifier and an
  enable gate into one zero-capacitance, zero-delay, PVT-invariant element.
  All three are now real devices (see "HOW THE INJECTION IS GENERATED, AS
  DEVICES"), so this cell now DOES characterise what that source hid:
    * the transconductor's own PVT spread and its Vgs-matching error;
    * the quiescent current it adds;
    * its area;
    * its parasitic loading of FB and its finite bias-node bandwidth.
  Every one of those is measured rather than estimated, in the records this
  issue mints -- which is also why FOUR of the numeric targets in
  design/softstart_injection_compensation.md section 3 (T1, T2, T3, T4) are
  now KNOWN to be out of reach for this topology rather than merely
  unverified. See "WHAT THE CASCODE FIXED, AND WHAT IT DID NOT".

  Rgma_ss/Rgmb_ss are plain `res` primitives (200 kohm), not ppolyf_u_3k
  instances: they are the one remaining place in the injection path where a
  value is stated rather than built out of a PDK device. That is deliberate
  and is the SAME modelling choice ldo_core's feedback divider already makes
  (README.md note 3) -- and it is load-bearing for the next paragraph, which
  is a statement about the RATIO of the two.

  The 5.0e-6 coefficient is 1.5/Rtop, i.e. it is a RATIO to the feedback
  divider, not an absolute transconductance. That is deliberate and is the
  one property the device-level build must preserve: if the injection's
  reference resistor does not track Rtop, the VOUT/SSR gain moves with the
  resistor corner, and at -25 % the ramp would START at +0.45 V instead of 0.
  ldo_core's divider is itself modelled as two ideal resistors, so expressing
  the injection as a ratio to it is consistent with how the divider ratio is
  already treated (README.md note 3).

#231: THIS LEAKAGE IS WHAT sim/startup's FULL/MIN-LOAD BRANCHES ALSO
MEASURE, AND WHY THIS CELL IS REVERTED

  #128 re-ran sim/startup's 81-point full PVT matrix (unchanged since
  before #191) and found four corners -- ff_27c_3.63v, ff_125c_3.63v,
  ff_125c_3.30v, sf_125c_3.63v -- that no longer reach the ratified +/-2 %
  settling threshold within the bench's 6 ms window AT ALL, even though
  they were the FASTEST-settling corners (2.3-2.6 ms) in the pre-#191
  baseline (sim/startup/records/20260816-100018-af4d1f9.md). This is the
  exact defect the historical section above already root-caused (Mgmo_ss subthreshold
  leakage, persisting because Mtop_ss's own body effect -- B=VIN on a device
  sourcing off SSR, which sits up to a body-source drop below VIN -- clamps
  SSR ~1 V above VREF instead of at it, so the transconductor's two branches
  never rebalance), measured independently and from the opposite direction:
  design/netlist/ldo_core.spice's own tsettle_full/tsettle_min bench, not
  sim/soft-start's vout_settled bench. `git bisect`-by-hand across
  design/netlist/ldo_core.spice's history (swapping in each commit's netlist
  against the current testbench) placed the regression's start EXACTLY at
  dce8d73 (#195, this cell's own device-level landing) -- d3cb117 (Binj_ss)
  passes the same corner, every commit from dce8d73 onward fails it
  identically. At ff_27c_3.63v isolated (`python3 sim/run_corners.py startup
  --corners ff --temps 27 --supply 3.63 --supply-tol 0 -j 1 --no-write`),
  vout_full is flat (not slow -- unmoving, from ~1 ms to the 6 ms window's
  end) at 1.77317 V against the 1.782 V threshold, traced to SSR settling at
  2.2415 V (VREF is 1.2 V) and a ~220-290 nA residual injection current this
  cell's own topology cannot rectify away at that offset (see "GMSUM's KCL"
  above -- the KCL argument for an exact zero assumed SSR settles AT VREF,
  which Mtop_ss's body effect falsifies).

  #191 already knew this cell was not ready (KNOWN, UNRESOLVED REGRESSION,
  in the historical section above) on inrush grounds and every sizing fix
  tried there made the settled-accuracy leakage no better either (that
  section is dated before #231 and reaches the same "no lever" conclusion
  independently).
  With two independent PVT-wide failure modes and no untried lever on the
  UNCASCODED topology, #231 reverted this cell to Binj_ss as an
  interim fix rather than wait on the real one: `spec/decision-records/
  DR-0023-softstart-injection-mirror-topology.md` already proposes the
  cascoded-mirror redesign that root-causes and fixes both failures
  (Mgmr_ss/Mgmo_ss's drain-voltage mismatch), but it is `status: proposed`
  and its ratification PR (#217) was still open, held for a human merge, as
  of #231 -- CLAUDE.md's ratification-via-PR rule means no implementation PR
  may land it before then. The full 81-point sim/startup matrix passes
  cleanly against Binj_ss (see the record this issue superseded
  20260816-100018-af4d1f9.md's replacement), which is expected: Binj_ss is
  exactly what that baseline was measured against.

  CLOSED BY #246. PR #217 merged 2026-09-18, ratifying DR-0023, and this cell
  now carries the cascoded mirror. The settled-leakage mechanism this section
  root-causes -- SSR parking above VREF and the mirror still sourcing a few
  hundred nanoamps there, because its two legs' drains do not match -- is
  what the cascode removes; the measured residual and the resulting settled
  output error are in "WHAT THE CASCODE FIXED, AND WHAT IT DID NOT" below.
  This section is left in place as the record of what was tried, so a future
  reader does not re-discover either failure mode from scratch, and so that
  the case for cascoding (rather than resizing a seventh time) stays legible.

SIZING AS BUILT

  Everything below is a read-back of the instances in this file after
  bring-up, not a statement of intent.

  Rss_bias  ppolyf_u_3k, 1000 squares  ~3.1 Mohm  -> Iref_ss ~ 0.39 uA
  k_ss      0.0060                                -> I_ramp  ~ 2.3 nA
  Css       60 um x 12 um cap_mim_2f0             ~1.44 pF  (issue #212,
            DR-0024: was 60 um x 60 um / ~7.2 pF -- a 5x area cut, I_ramp
            and every other element on this bias branch UNCHANGED, so the
            re-centring touches only this ramp block's own time constant
            and adds/removes no DC current anywhere -- Iq is unaffected by
            construction, not merely by measurement, and the branch's own
            +/-25% (poly resistor) / +/-10% (mim cap) PVT spread and the
            2.93:1 corner-to-corner ratio DR-0006 measured are preserved
            exactly, just riding on a 5x smaller absolute time constant)
    => measured dVout/dt (163-point PVT sweep, sim/soft-start/records/
       20260915-103035-18f664f.md): 1.24 -- 2.95 V/ms, a 2.38:1
       corner-to-corner spread (looser than the 2.93:1 the raw R*C alone
       would give, because Ch_ss/Cr_ss's own hold-release delay -- scaled
       by the identical 5x factor, see "WHY Ch_ss/Cr_ss MOVE WITH Css"
       below -- rides on top of the ramp in the same measurement and does
       not track the ramp's own PVT corner one-for-one). Comfortably inside
       DR-0024's proposed 5 V/ms bound at every one of the 155 points that
       converged; the analytic ~1.6 V/ms nominal estimate this line
       previously carried undercounted real device/loop effects by roughly
       20%, which is why the record's measured range is cited here instead.
  THE INJECTION TRANSCONDUCTOR (#191's chain + #246/DR-0023's cascode). The
  design target is 5.0e-6 A/V = 1.5 / Rtop (a RATIO to the divider -- see
  WHAT IS IDEALIZED HERE), which is what sets the two 200 kohm degeneration
  resistors: 1/(Rtop||Rbot) = 1.5/300k = 5.0 uA/V, so R = 200 kohm.

  Rgma_ss/Rgmb_ss  res 200 kohm each     branch degeneration, the element's
                                         own reference. NOT a PDK resistor
                                         primitive -- see WHAT IS IDEALIZED
                                         HERE for why the ratio, not the
                                         absolute value, is the property
                                         being preserved.
  Mgma_ss/Mgmb_ss  pfet 4 um / 1 um      the two input branches, gates SSR
                                         and VREF, bodies on their OWN
                                         sources (GMSA / GMSB)
  Mgmd_ss/Mgmm_ss  nfet 4 um / 1 um      branch-A diode + its 1:1 mirror
  Mgmr_ss/Mgmo_ss  pfet 4 um / 1 um      the mirror's top devices: reference
                                         (diode at GMRM) and output
  Mgmrc_ss/Mgmc_ss pfet 4 um / 1 um      THE CASCODE (#246/DR-0023): the
                                         reference-leg cascode is diode-
                                         connected at GMSUM, the output-leg
                                         cascode shares its gate, and both
                                         have body = own source (GMRM /
                                         GMOD). Matched-and-same-current is
                                         what makes V(GMOD) = V(GMRM), which
                                         is what makes the mirror's two
                                         |Vds| equal. Identical geometry to
                                         the devices they cascode, because
                                         the matching that matters is
                                         Mgmrc_ss-to-Mgmc_ss, not either of
                                         them to Mgmr_ss/Mgmo_ss.
  Mgme_ss          nfet 20 um / 0.5 um   enable switch, gate EN
  Mgmg_ss          pfet 10 um / 0.5 um   THE BRANCH-SUPPLY GATE (#259/
                                         DR-0028): VIN -> VING, gate GMRM,
                                         body VIN. W/L = 20 is chosen so its
                                         triode drop at the few uA the
                                         branches draw is tens of mV (a
                                         common-mode term on both branches)
                                         while it is on, not so that it
                                         "matches" anything -- it is a
                                         switch, not a mirror leg, even
                                         though its gate is a mirror node.
  Rgmg_ss   ppolyf_u_3k, 150 squares   ~450 kohm   VIN -> VING, the bleed that
                                         keeps GMIA/GMRM/GMSUM determined
                                         when Mgmg_ss is off. NOT optional:
                                         DR-0027 measured what happens
                                         without it. A real PDK resistor
                                         (unlike Rgma_ss/Rgmb_ss) because
                                         nothing here depends on its ratio to
                                         the divider -- only on its being
                                         large and finite.
  Rh_ss     ppolyf_u_3k, 4870 squares  ~15.1 Mohm  EN -> HG
  Ch_ss     70 um x 14 um cap_mim_2f0  ~1.95 pF    HG -> VSS   (tau ~29.4 us;
            issue #212/DR-0024, also a 5x area cut from 70x70/~9.75pF/147us
            -- see why below)
  Rr_ss     ppolyf_u_3k, 4870 squares  ~15.1 Mohm  ENB -> SD
  Cr_ss     70 um x 14 um cap_mim_2f0  ~1.95 pF    SD -> VSS   (tau ~29.4 us;
            same #212/DR-0024 5x cut, kept EXACTLY equal to Ch_ss -- the two
            RCs stay matched to EACH OTHER, which is the property the
            ordering (hold-releases-before-ramp-starts) depends on, not on
            any particular absolute tau)

  WHY Ch_ss/Cr_ss MOVE WITH Css (issue #212/DR-0024). Speeding up ONLY the
  ramp (Css) and leaving the hold-release delay (~1.5 * tau, previously
  ~220 us) fixed turns a small tax on a ~2-6 ms ramp into a LARGE fraction
  of tax on a sub-2-ms one -- and at the corner that sets the hold delay's
  own worst case (res_ss/ss, cold, high Vin -- poly resistance moves the
  SAME direction as it does for Rss_bias, i.e. up), the untouched-Ch_ss
  build measured t_v04 (first 0.4 V crossing) alone past 1 ms, which by
  itself would blow most of any settling target this record could propose,
  regardless of how fast the ramp afterward is. Measured, same corner
  (res_ss_-40c_3.63v_1u_0.1_36): t_startup 2.033 ms with only Css cut 5x,
  vs. 1.72525 ms (this record's own worst measured point, same PVT corner)
  once Ch_ss/Cr_ss are ALSO cut 5x -- see
  sim/soft-start/records/20260915-103035-18f664f.md and DR-0024, which
  proposes a 1.8 ms settling bound (the measured 1.72525 ms worst point plus
  ~4% headroom, the same margin convention DR-0006 used) rather than the
  1.2 ms this note originally targeted before the sweep existed to check it
  against. Scaling the two delay RCs by the identical factor keeps their
  ratio to the (now faster) ramp the same as the as-built ratio was to the
  old one, and does not touch their own mutual matching (both are still
  70 um x 14 um, i.e. still exactly equal to each other) -- so the ordering
  invariant this cell's correctness depends on is unaffected by the resize.
  Mhold_ss     pfet 20 um / 0.5 um   VIN -> PASS_GATE, gate HG
  Mhold_bg_ss  pfet 10 um / 0.5 um   VIN -> BG,        gate HG
  Mpre_a_ss    pfet 10 um / 0.5 um   VREF -> FBP,      gate HG
  Mpre_b_ss    pfet 10 um / 0.5 um   FBP  -> FB,       gate ENB

  Added enabled quiescent current, #246 update. The ramp bias branch is
  ~0.4 uA at tt/27 C as before, the two delay RCs are capacitively terminated
  and the hold and pre-charge devices end in cutoff. What is NEW is that the
  injection transconductor is a real, standing DC current: its two branches
  each carry (VIN - Vsg)/200 kohm and they do NOT switch off at hand-over --
  the MIRROR rectifies, the branches do not. (THAT LAST SENTENCE IS #246's
  STATE, NOT TODAY'S: #259 gates the branch supply, see the DR-0028 update
  at the end of this note. The measurement below is left as written because
  it is the baseline the recovery is measured against.) That adder is
  measured, not
  estimated: sim/quiescent-current/records/20260918-190801-8a59d23.md against
  20260915-234352-077e15b.md (the Binj_ss baseline, same 81-point grid) reads
  +0.004...+7.18 uA, worst at ff_125c_3.63v, where enabled Iq goes 20.8645 ->
  28.0411 uA against the ratified < 30 uA row. PASS at 81/81 points -- but
  the row's OWN binding clause at this corner is 'at full load', not
  'enabled, no load': iq_full_ua reads 28.71 uA at ff_125c_3.63v (same
  record), leaving only 1.29 uA of headroom, not the 1.96 uA the no-load
  clause alone would suggest (#259 corrects this note; #249 first found the
  discrepancy). Anything that adds standing current has to fit in 1.29 uA.

  TWO THINGS ABOUT THAT NUMBER ARE WORTH STATING PLAINLY, because DR-0023
  estimated the cascode as costing no material Iq and that estimate is only
  half right.

    The adder is dominated by the TRANSCONDUCTOR, not by the cascode. Both
    degenerated branches carry (VIN - |Vsg| - V(gate))/200 kohm and neither
    switches off at hand-over -- only the mirror rectifies -- so the element
    stands ~2 x Ia of DC current forever. That is #191's cost, not #246's:
    it is the price of replacing a behavioural source with real devices, and
    Binj_ss (an ideal source with no branches) never paid it.

    The cascode is NOT free on top of that, for the reason "WHERE THE
    CASCODE'S HEADROOM COMES FROM" gives: dropping V(GMSUM) by one |Vgs|
    pulls Mgmb_ss out of triode and back toward saturation, so its branch
    delivers MORE current than it did uncascoded. Against #191's own
    uncascoded measurement at the binding corner (25.3658 uA,
    sim/quiescent-current/records/20260906-231405-d3cb117.md) the cascode's
    own share of the adder is about +2.7 uA. DR-0023's "no new current path"
    argument is correct about topology and incomplete about bias: adding no
    path is not the same as moving no operating point.

  MOST OF THAT ADDER IS NOW RECOVERED, #259/DR-0028 update. Mgmg_ss/Rgmg_ss
  (see "HOW THE BRANCH SUPPLY IS GATED AFTER HAND-OVER") take the branches'
  supply away once the mirror's reference stack cuts off, and the result is
  measured on the same 81-point grid:
  sim/quiescent-current/records/20260919-080719-de8b468.md against
  20260918-190801-8a59d23.md above.

    At ff_125c_3.63v (the binding corner) enabled Iq goes 28.0411 ->
    22.9725 uA and the binding FULL-LOAD clause goes 28.71 -> 23.7275 uA.
    Headroom against the ratified < 30 uA row: 1.29 -> 6.27 uA at full load,
    1.96 -> 7.03 uA at no load.
    Iq falls at 80 of the 81 points and rises at none; the one non-negative
    delta is +0.00003 uA (30 pA) at ss_-40c_2.97v.
    Against the ideal-Binj_ss baseline the whole element's adder goes
    +0.0001...+7.1766 -> +0.0001...+2.1080 uA, i.e. 70.6% of the worst-corner
    adder recovered. The remainder is the 450 kohm bleed's own throughput,
    which is the deliberate price of the convergence bound DR-0027 measured
    the need for.
    The cost is settled accuracy at the hot, high-supply corners: worst-corner
    settled output 1.79357 -> 1.78833 V at ff_125c_3.63v, i.e. -6.43 ->
    -11.67 mV of error against a +/-36 mV ratified allocation. Bit-identical
    at tt/27 C. T1-T7 and the 163-point transient set are re-measured in
    sim/soft-start/records/20260919-073737-de8b468.md; T5 stays 63/63, T6/T7
    do not regress, T1/T4 improve, T2/T3 do not move, and two already-failing
    transient clauses lose a point each (that record's section 1 names them).

  The 6.27 uA of remaining headroom (full-load clause, the binding one --
  see above) is still a real constraint on anything that follows: the R4
  lever (scaling the feedback divider to relax T2/T3) adds ~18 uA and is
  closed by exactly this row even now, which is why it needs a decision
  record rather than a patch.

  Added area, #246 update: the injection transconductor is
  EIGHT pfet/nfet 03v3 devices at 4 um2 each (Mgma_ss, Mgmb_ss, Mgmd_ss,
  Mgmm_ss, Mgmr_ss, Mgmo_ss, and #246's two cascodes Mgmrc_ss and Mgmc_ss) =
  32 um2, plus Mgme_ss at 10 um2, i.e. 42 um2 of transistor -- 8 um2 more
  than the uncascoded chain's 34 um2, which is DR-0023's "~10 um2 added"
  estimate confirmed to within one device. The two 200 kohm degeneration
  resistors are `res` primitives with no PDK geometry and therefore no
  modelled area (WHAT IS IDEALIZED HERE); built out of ppolyf_u_3k at
  W = 1 um they would be ~67 squares each, ~134 um2 total, which is the
  number a layout-phase build should budget and is recorded here so it is not
  rediscovered. Against the ratified < 0.1 mm2 (100 000 um2) core-area row,
  the whole transconductor -- cascode, resistors and all -- is under 0.2 %.

  Added area, #259/DR-0028 update: Mgmg_ss is 10 um x 0.5 um = 5 um2, so the
  transconductor's transistor area goes 42 -> 47 um2. Rgmg_ss is a REAL PDK
  resistor and its area is therefore modelled, unlike Rgma_ss/Rgmb_ss: 150
  squares at W = 1 um = 150 um2 of ppolyf_u_3k. Against the same < 0.1 mm2
  row that is +0.16 %, and it buys back about 5 uA of the ratified < 30 uA
  Iq row's binding clause -- the cheapest trade on this page.

  Added area, #212/DR-0024 update: 2 630 um2 of capacitor (Css 720, Ch_ss
  980, Cr_ss 980 -- all three down 5x from the #189-era 3600/4900/4900) plus
  10 740 um2 of poly resistor (1000 + 4870 + 4870 squares at W = 1 um,
  unchanged), about 13 400 um2 -- down from the #189-era 24 100 um2 (the
  three caps' 5x area cut is a net area WIN, not a cost, unlike every other
  change this note has recorded), roughly 13 % of the ratified 0.1 mm2
  core-area row, against about 11 800 um2 for the #38/#43 clamp this
  replaces. The two delay RCs (Rh_ss/Ch_ss, Rr_ss/Cr_ss) are no longer at
  the minimum-area R/C split for their (now 5x smaller) tau -- Rh_ss/Rr_ss
  were left untouched on purpose (see "WHY Ch_ss/Cr_ss MOVE WITH Css"
  above: shrinking the resistor instead would have raised its own bias
  current, which the ramp side deliberately avoided) -- so this split is no
  longer minimum-area for its tau; buying it back needs a current-source
  ramp or a MOS pseudo-resistor in place of the RC, which is a follow-on,
  not this issue's scope.} -1200 -1470 0 0 0.28 0.28 {}
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
C {symbols/cap_mim_2f0fF.sym} 800 -1000 0 0 {name=Css model=cap_mim_2f0_m2m3_noshield W=60u L=12u m=1}
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
C {symbols/pfet_03v3.sym} 1400 -1000 0 0 {name=Mgmg_ss model=pfet_03v3 L=0.5u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 1380 -1000 0 0 {name=l_mgmgss_g sig_type=std_logic lab=GMRM}
C {devices/lab_pin.sym} 1420 -970 0 0 {name=l_mgmgss_d sig_type=std_logic lab=VING}
C {devices/lab_pin.sym} 1420 -1030 0 0 {name=l_mgmgss_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 1420 -1000 0 0 {name=l_mgmgss_b sig_type=std_logic lab=VIN}
C {symbols/ppolyf_u_3k.sym} 1600 -1000 0 0 {name=Rgmg_ss model=ppolyf_u_3k W=1u L=150u m=1}
C {devices/lab_pin.sym} 1600 -1030 0 0 {name=l_rgmgss_p sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 1600 -970 0 0 {name=l_rgmgss_m sig_type=std_logic lab=VING}
C {devices/lab_pin.sym} 1580 -1000 0 0 {name=l_rgmgss_b sig_type=std_logic lab=VSS}
C {devices/res.sym} 0 -900 0 0 {name=Rgma_ss value=200k footprint=1206 device=resistor m=1}
C {devices/lab_pin.sym} 0 -930 0 0 {name=l_rgmass_p sig_type=std_logic lab=VING}
C {devices/lab_pin.sym} 0 -870 0 0 {name=l_rgmass_m sig_type=std_logic lab=GMSA}
C {symbols/pfet_03v3.sym} 200 -900 0 0 {name=Mgma_ss model=pfet_03v3 L=1u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 180 -900 0 0 {name=l_mgmass_g sig_type=std_logic lab=SSR}
C {devices/lab_pin.sym} 220 -870 0 0 {name=l_mgmass_d sig_type=std_logic lab=GMIA}
C {devices/lab_pin.sym} 220 -930 0 0 {name=l_mgmass_s sig_type=std_logic lab=GMSA}
C {devices/lab_pin.sym} 220 -900 0 0 {name=l_mgmass_b sig_type=std_logic lab=GMSA}
C {symbols/nfet_03v3.sym} 400 -900 0 0 {name=Mgmd_ss model=nfet_03v3 L=1u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 420 -930 0 0 {name=l_mgmdss_d sig_type=std_logic lab=GMIA}
C {devices/lab_pin.sym} 380 -900 0 0 {name=l_mgmdss_g sig_type=std_logic lab=GMIA}
C {devices/lab_pin.sym} 420 -870 0 0 {name=l_mgmdss_s sig_type=std_logic lab=GMVSS}
C {devices/lab_pin.sym} 420 -900 0 0 {name=l_mgmdss_b sig_type=std_logic lab=VSS}
C {devices/res.sym} 600 -900 0 0 {name=Rgmb_ss value=200k footprint=1206 device=resistor m=1}
C {devices/lab_pin.sym} 600 -930 0 0 {name=l_rgmbss_p sig_type=std_logic lab=VING}
C {devices/lab_pin.sym} 600 -870 0 0 {name=l_rgmbss_m sig_type=std_logic lab=GMSB}
C {symbols/pfet_03v3.sym} 800 -900 0 0 {name=Mgmb_ss model=pfet_03v3 L=1u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 780 -900 0 0 {name=l_mgmbss_g sig_type=std_logic lab=VREF}
C {devices/lab_pin.sym} 820 -870 0 0 {name=l_mgmbss_d sig_type=std_logic lab=GMSUM}
C {devices/lab_pin.sym} 820 -930 0 0 {name=l_mgmbss_s sig_type=std_logic lab=GMSB}
C {devices/lab_pin.sym} 820 -900 0 0 {name=l_mgmbss_b sig_type=std_logic lab=GMSB}
C {symbols/nfet_03v3.sym} 600 -750 0 0 {name=Mgmm_ss model=nfet_03v3 L=1u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 620 -780 0 0 {name=l_mgmmss_d sig_type=std_logic lab=GMSUM}
C {devices/lab_pin.sym} 580 -750 0 0 {name=l_mgmmss_g sig_type=std_logic lab=GMIA}
C {devices/lab_pin.sym} 620 -720 0 0 {name=l_mgmmss_s sig_type=std_logic lab=GMVSS}
C {devices/lab_pin.sym} 620 -750 0 0 {name=l_mgmmss_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 800 -750 0 0 {name=Mgmr_ss model=pfet_03v3 L=1u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 780 -750 0 0 {name=l_mgmrss_g sig_type=std_logic lab=GMRM}
C {devices/lab_pin.sym} 820 -720 0 0 {name=l_mgmrss_d sig_type=std_logic lab=GMRM}
C {devices/lab_pin.sym} 820 -780 0 0 {name=l_mgmrss_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 820 -750 0 0 {name=l_mgmrss_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 1000 -750 0 0 {name=Mgmrc_ss model=pfet_03v3 L=1u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 980 -750 0 0 {name=l_mgmrcss_g sig_type=std_logic lab=GMSUM}
C {devices/lab_pin.sym} 1020 -720 0 0 {name=l_mgmrcss_d sig_type=std_logic lab=GMSUM}
C {devices/lab_pin.sym} 1020 -780 0 0 {name=l_mgmrcss_s sig_type=std_logic lab=GMRM}
C {devices/lab_pin.sym} 1020 -750 0 0 {name=l_mgmrcss_b sig_type=std_logic lab=GMRM}
C {symbols/pfet_03v3.sym} 1200 -750 0 0 {name=Mgmo_ss model=pfet_03v3 L=1u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 1180 -750 0 0 {name=l_mgmoss_g sig_type=std_logic lab=GMRM}
C {devices/lab_pin.sym} 1220 -720 0 0 {name=l_mgmoss_d sig_type=std_logic lab=GMOD}
C {devices/lab_pin.sym} 1220 -780 0 0 {name=l_mgmoss_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 1220 -750 0 0 {name=l_mgmoss_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 1400 -750 0 0 {name=Mgmc_ss model=pfet_03v3 L=1u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 1380 -750 0 0 {name=l_mgmcss_g sig_type=std_logic lab=GMSUM}
C {devices/lab_pin.sym} 1420 -720 0 0 {name=l_mgmcss_d sig_type=std_logic lab=FB}
C {devices/lab_pin.sym} 1420 -780 0 0 {name=l_mgmcss_s sig_type=std_logic lab=GMOD}
C {devices/lab_pin.sym} 1420 -750 0 0 {name=l_mgmcss_b sig_type=std_logic lab=GMOD}
C {symbols/nfet_03v3.sym} 1600 -750 0 0 {name=Mgme_ss model=nfet_03v3 L=0.5u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 1620 -780 0 0 {name=l_mgmess_d sig_type=std_logic lab=GMVSS}
C {devices/lab_pin.sym} 1580 -750 0 0 {name=l_mgmess_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 1620 -720 0 0 {name=l_mgmess_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1620 -750 0 0 {name=l_mgmess_b sig_type=std_logic lab=VSS}
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
C {symbols/cap_mim_2f0fF.sym} 800 -600 0 0 {name=Ch_ss model=cap_mim_2f0_m2m3_noshield W=70u L=14u m=1}
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
C {symbols/cap_mim_2f0fF.sym} 200 -200 0 0 {name=Cr_ss model=cap_mim_2f0_m2m3_noshield W=70u L=14u m=1}
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
