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

#189 BUILT THE INJECTION AS ONE BEHAVIOURAL SOURCE (Binj_ss); #191 REPLACES
IT WITH DEVICES. The transconductor, the rectifier and the enable gate are
now Rgma_ss/Mgma_ss/Mgmd_ss/Rgmb_ss/Mgmb_ss/Mgmm_ss/Mgmr_ss/Mgmo_ss/Mgme_ss
-- see "HOW THE INJECTION IS GENERATED, AS DEVICES" below for the topology
and "WHAT IS IDEALIZED HERE" for what is still not built.

READ "KNOWN, UNRESOLVED REGRESSION (#191)" BEFORE TRUSTING THIS CELL AGAINST
THE RATIFIED STARTUP ROW. Replacing Binj_ss with real devices, even correctly
sized, destabilizes the main loop's hold-release transient at most of the PVT
matrix (inrush fails 81/163 points, by 6-77x the ratified bound, per
sim/soft-start/records/20260906-230703-d3cb117.md) -- Binj_ss's zero
parasitic capacitance was apparently load-bearing for a margin #189 never
characterised. This is a #191 regression, confirmed against main's own
committed netlist, not a #189 defect.

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

  UPDATE (#196): that AC evidence now exists, for the hand-over state and not
  only the settled one --
  sim/soft-start-loop-gain/records/20260910-015601-2387ece.md, and the
  recommendation it feeds, design/softstart_injection_compensation.md.

HOW THE INJECTION IS GENERATED, AS DEVICES (#191)

  #189 built the injection as one behavioural source:

      I(VIN -> FB) = max(0, (VREF - SSR) * 5.0e-6) * (EN > 1.4 V)

  i.e. a linear transconductor of 5 uA/V, a source-only rectifier, and an
  enable gate, in one element. #191 replaces it with the device-level
  implementation #189 already named as the intended one: two VIN-referenced,
  resistor-degenerated PMOS branches with SSR and VREF on their gates,
  differenced in a diode-connected PMOS (which IS the rectifier), mirrored
  into FB.

    Rgma_ss/Mgma_ss   the SSR branch: VIN -> Rgma_ss -> GMSA -> Mgma_ss
                      (gate SSR) -> GMIA. Current Ia = (VIN - SSR - Vsg)/R,
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
                      body = own-source fix, on Mgmb_ss's body -> GMSB): VIN
                      -> Rgmb_ss -> GMSB -> Mgmb_ss (gate VREF) -> GMSUM,
                      carrying a FIXED current Ib = (VIN - VREF - Vsg)/R,
                      injected directly into GMSUM rather than through a
                      mirror.
    Mgmm_ss           mirrors GMIA's bias (1:1 with Mgmd_ss) and sinks Ia
                      from GMSUM to GMVSS.
    Mgmr_ss           diode-connected PMOS (gate=drain=GMSUM, source=VIN).
                      GMSUM's KCL is Ib + I(Mgmr_ss) = Ia, so
                      I(Mgmr_ss) = Ia - Ib = (VREF - SSR)/R for SSR < VREF
                      (both branches share R and are degenerated off the SAME
                      VIN, so VIN and the branches' own Vsg cancel in the
                      difference -- the ~3 % residual from the two branches'
                      Vsg not matching exactly is the transconductor's own
                      error, budgeted below). For SSR > VREF, Ia < Ib and
                      Mgmr_ss would need to source negative current to
                      balance GMSUM's KCL -- it cannot, so it goes into
                      cutoff and I(Mgmr_ss) clips to exactly zero. THIS is
                      the rectifier: a property of the topology, not a
                      separate comparator.
    Mgmo_ss           mirrors Mgmr_ss (1:1) and sources the result into FB --
                      the same "VIN -> FB" direction Binj_ss carried.
    Mgme_ss           the enable gate: an NMOS (gate EN) between GMVSS and
                      VSS, shared by Mgmd_ss and Mgmm_ss. With it open
                      (EN = 0) neither NMOS has a return path, so DC current
                      in both PMOS branches goes to zero in steady state --
                      GMIA and GMSUM float toward VIN, Mgmr_ss and Mgmo_ss
                      see ~0 Vsg and stop sourcing into FB. This is the same
                      "break the branch's ground return with one EN-gated
                      NMOS" idiom Mben_ss already uses on Rss_bias.

  THE HEADROOM TRAP THIS AVOIDS: at SSR = 0 (the start of every ramp), a PMOS
  gated by SSR has its source only a Vsg above ground -- if that branch's own
  current were sensed by an NMOS diode sitting at its DRAIN (the "obvious"
  place, mirroring the way Mgmd_ss senses GMIA here), the NMOS diode would
  need its own Vgs of headroom BELOW that already-thin margin, and the branch
  cannot deliver it. Both PMOS diodes in this design (Mgmr_ss, and Mgmd_ss's
  role is filled by an NMOS only because GMIA sits well above ground once
  Ia's own IR drop across Rgma_ss is accounted for -- verified in simulation,
  not assumed) are sensed at the VIN end instead: Mgmr_ss's source is VIN
  itself, so it always has a full VIN worth of headroom regardless of where
  SSR sits. Mgmb_ss's branch (gate VREF, not SSR) never approaches this floor
  since VREF is fixed at 1.2 V, so its own diode-sensing analogue was not
  needed -- its current is taken directly into GMSUM rather than mirrored.

KNOWN, UNRESOLVED REGRESSION (#191): A REAL INJECTION ELEMENT DESTABILIZES
THE HOLD-RELEASE TRANSIENT AT MOST OF THE PVT MATRIX

  This is the single biggest finding of #191 and it is NOT fixed here. It is
  documented in this much detail because the natural next step (resize the
  transconductor) makes it WORSE, not better, and that cost real time to
  discover.

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

  This cell ships, for now, at the ORIGINAL documented sizing (pfet/nfet
  4u/1u throughout the transconductor, Mtop_ss unchanged) with the body-tie
  fix above, because every other sizing tried made the acquisition transient
  no better and sometimes worse. sim/soft-start's own record for this issue
  reports the resulting inrush failures in full, by corner, rather than
  narrowing the swept matrix to hide them.

WHAT IS IDEALIZED HERE

  Fss_ramp, as before: an ideal CCCS standing in for a large-ratio mirror off
  a bias generator this repo has not designed.

  The transconductor above is now built from devices, not idealized as a
  behavioural source, but it still does NOT model:
    * matching / layout-induced mismatch beyond what SPICE's own device
      models capture at a given corner (i.e. no explicit sigma is added to
      Mgma_ss vs Mgmb_ss, or to the two 200 kohm resistors) -- a layout-phase
      concern per design/error_amp.md's offset-table precedent, not a
      schematic-phase one;
    * flicker/thermal noise contribution to the ramp (out of this issue's
      scope; the ramp's own noise budget is not separately ratified).
  Both are the same category of simplification design/ldo_core.sch's Rtop/
  Rbot and design/error_amp.sch's input pair already carry.

  Rgma_ss and Rgmb_ss are 200 kohm IDEAL resistors (devices/res.sym, not the
  PDK's ppolyf_u_3k poly resistor), and that is a deliberate, load-bearing
  choice, not a shortcut. The coefficient the injection must hit is
  1/(Rtop||Rbot) = 1.5/Rtop = 5.0e-6 A/V (200 kohm = 300k||600k, ldo_core's
  divider). ldo_core's Rtop/Rbot are THEMSELVES ideal, fixed-value resistors
  (design/ldo_core.sch's own note 3) -- they carry NO process-corner spread
  at all, on any corner this repo's harness sweeps. If Rgma_ss/Rgmb_ss were
  built from ppolyf_u_3k instead (as Rss_bias/Rh_ss/Rr_ss are, elsewhere in
  this same cell), they would move +/-25 % on the res_ff/res_ss corners while
  Rtop/Rbot stayed exactly fixed, and the VOUT/SSR gain would move with them
  -- at -25 % the ramp would START at +0.45 V instead of 0, a step into
  C_out, i.e. exactly the failure #189 removed (see #191's issue text). Using
  the SAME ideal-resistor primitive as Rtop/Rbot, at the value that makes the
  ratio exact, is how this build tracks the divider rather than merely
  approximating it: the two are locked together by construction (both always
  exactly their nominal value, at every corner), not by a coincidence of
  typical-corner sizing. If Rtop/Rbot's values or types ever change, this
  200 kohm MUST change with them (300k||600k, not a fixed 200k).

  Mgmr_ss/Mgmo_ss's off-state subthreshold leakage is NOT modelled as zero,
  and it is measurably worse than the "3 % of the injection" residual the
  #189-era estimate above budgeted: at ff/125 C/3.63 V (this bench's hottest,
  highest-VIN corner), Mgmo_ss alone was measured sourcing ~0.8 uA into FB
  well after SSR has cleared VREF by ~0.9 V, which is enough to pull
  vout_settled to ~1.56-1.62 V against the ratified 1.764-1.836 V window --
  a real settled-accuracy failure, not just a quiescent-current cost. This
  was root-caused to Mgmo_ss's own Vgs-deficit-driven subthreshold
  conduction, not to Mpre_a_ss/Mpre_b_ss (measured leakage <1 pA at the same
  corner) and not to insufficient settling time (SSR and GMSUM are both
  flat well before the bench's 7.9 ms settled-read point). Resizing
  Mgmr_ss/Mgmo_ss to trade active-region accuracy for a bigger Vgs deficit
  (see the KNOWN, UNRESOLVED REGRESSION section above) reduces this leakage
  somewhat but destabilizes the acquisition transient far more than it
  helps, so it was not kept. This is left unresolved for the same reason:
  fixing it needs either a bandgap-independent hard-cutoff structure (a
  cascode did not help empirically -- Mgmo_ss's Vds is already fairly
  fixed regardless of FB, so cascoding barely changes its subthreshold
  current) or accepting the settled-accuracy cost at the hottest/highest-VIN
  corners, and #191 did not have room to design the former.

SIZING AS BUILT

  Everything below is a read-back of the instances in this file after
  bring-up, not a statement of intent.

  Rss_bias  ppolyf_u_3k, 1000 squares  ~3.1 Mohm  -> Iref_ss ~ 0.39 uA
  k_ss      0.0060                                -> I_ramp  ~ 2.3 nA
  Css       60 um x 60 um cap_mim_2f0             ~7.2 pF
    => nominal dSSR/dt ~ 0.32 V/ms, so dVout/dt ~ 0.48 V/ms.
  Rgma_ss/Rgmb_ss  200 kohm ideal (see WHAT IS IDEALIZED HERE) -> 1/R =
                   5.0e-6 A/V = 1.5 / Rtop, matching Binj_ss's coefficient
  Mgma_ss/Mgmb_ss  pfet 4 um / 1 um    the two input branches, gates SSR/VREF
  Mgmd_ss/Mgmm_ss  nfet 4 um / 1 um    branch-A diode + mirror pair
  Mgmr_ss/Mgmo_ss  pfet 4 um / 1 um    differencer/rectifier + output mirror
  Mgme_ss          nfet 20 um / 0.5 um enable switch, gate EN
  Rh_ss     ppolyf_u_3k, 4870 squares  ~15.1 Mohm  EN -> HG
  Ch_ss     70 um x 70 um cap_mim_2f0  ~9.75 pF    HG -> VSS   (tau ~147 us)
  Rr_ss     ppolyf_u_3k, 4870 squares  ~15.1 Mohm  ENB -> SD
  Cr_ss     70 um x 70 um cap_mim_2f0  ~9.75 pF    SD -> VSS   (tau ~147 us)
  Mhold_ss     pfet 20 um / 0.5 um   VIN -> PASS_GATE, gate HG
  Mhold_bg_ss  pfet 10 um / 0.5 um   VIN -> BG,        gate HG
  Mpre_a_ss    pfet 10 um / 0.5 um   VREF -> FBP,      gate HG
  Mpre_b_ss    pfet 10 um / 0.5 um   FBP  -> FB,       gate ENB

  Added enabled quiescent current, MEASURED (issue #191, replacing the
  arithmetic estimate this note previously carried): the two delay RCs are
  still capacitively terminated and the hold/pre-charge devices still end in
  cutoff, exactly as before, but the transconductor's two branches (Mgma_ss/
  Mgmb_ss and their mirrors) are NOT free even after hand-over -- SSR settles
  above VREF, not at it, so Mgma_ss's branch current shrinks but does not
  reach zero. sim/quiescent-current/records/<this issue's record> attributes
  the adder against the 20260905-200855-3093ea1 baseline at the binding
  ff/125 C/3.63 V corner; see that record for the measured number.

  Added area: the transconductor's six MOS devices sum to 34 um2 of gate
  area (Mgma_ss/Mgmb_ss/Mgmd_ss/Mgmm_ss/Mgmr_ss/Mgmo_ss at 4 um2 each,
  Mgme_ss at 10 um2) -- negligible against the totals below. Rgma_ss/
  Rgmb_ss are IDEAL resistors (devices/res.sym, like ldo_core's Rtop/Rbot)
  and therefore carry NO modelled on-die area here; that is the same
  idealization Rtop/Rbot themselves already carry (design/ldo_core.sch note
  3), not a new gap #191 introduces, and it is resolved together with theirs
  whenever the divider is laid out in real poly (design/README.md's #15/#13
  sizing-and-matching plan) -- at that point Rgma_ss/Rgmb_ss must track
  whatever real device Rtop/Rbot become, per WHAT IS IDEALIZED HERE above.

  Added area otherwise unchanged from #189: 13 350 um2 of capacitor (Css
  3600, Ch_ss 4900, Cr_ss 4900) plus 10 740 um2 of poly resistor (1000 +
  4870 + 4870 squares at W = 1 um), about 24 100 um2 -- roughly 24 % of the
  ratified 0.1 mm2 core-area row, against about 11 800 um2 for the #38/#43
  clamp this replaces. That is a real cost, it is dominated by the two delay
  RCs, and it is called out here rather than discovered at layout. The delay
  RCs are at their minimum-area R/C split for the tau they implement (equal
  resistor and capacitor area); buying the tau back with a smaller area
  needs a current-source ramp or a MOS pseudo-resistor in place of the RC,
  which is a follow-on, not this issue's scope.} -1200 -1470 0 0 0.28 0.28 {}
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
C {devices/res.sym} 0 -900 0 0 {name=Rgma_ss value=200k footprint=1206 device=resistor m=1}
C {devices/lab_pin.sym} 0 -930 0 0 {name=l_rgmass_p sig_type=std_logic lab=VIN}
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
C {devices/lab_pin.sym} 600 -930 0 0 {name=l_rgmbss_p sig_type=std_logic lab=VIN}
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
C {devices/lab_pin.sym} 780 -750 0 0 {name=l_mgmrss_g sig_type=std_logic lab=GMSUM}
C {devices/lab_pin.sym} 820 -720 0 0 {name=l_mgmrss_d sig_type=std_logic lab=GMSUM}
C {devices/lab_pin.sym} 820 -780 0 0 {name=l_mgmrss_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 820 -750 0 0 {name=l_mgmrss_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 1000 -750 0 0 {name=Mgmo_ss model=pfet_03v3 L=1u W=4u nf=1 m=1}
C {devices/lab_pin.sym} 980 -750 0 0 {name=l_mgmoss_g sig_type=std_logic lab=GMSUM}
C {devices/lab_pin.sym} 1020 -720 0 0 {name=l_mgmoss_d sig_type=std_logic lab=FB}
C {devices/lab_pin.sym} 1020 -780 0 0 {name=l_mgmoss_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 1020 -750 0 0 {name=l_mgmoss_b sig_type=std_logic lab=VIN}
C {symbols/nfet_03v3.sym} 1200 -750 0 0 {name=Mgme_ss model=nfet_03v3 L=0.5u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 1220 -780 0 0 {name=l_mgmess_d sig_type=std_logic lab=GMVSS}
C {devices/lab_pin.sym} 1180 -750 0 0 {name=l_mgmess_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 1220 -720 0 0 {name=l_mgmess_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1220 -750 0 0 {name=l_mgmess_b sig_type=std_logic lab=VSS}
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
