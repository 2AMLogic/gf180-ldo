v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {ldo_ilimit -- constant-current (brickwall) limit + enable gating. Issue #11.} -1200 -1500 0 0 0.5 0.5 {}
T {WHAT THIS BLOCK DOES

Clamps the pass-device gate so the total output current cannot exceed a
threshold set by VREF and a resistor ratio. The clamp is a CONSTANT-CURRENT
(brickwall) limiter, not foldback: the ratified spec (README "Current limit"
row + note 5, and DR-0004's "two judgment calls") already made that decision,
because a folded-back limit that engages while starting into a loaded output
can latch the regulator low. Nothing here folds the threshold back with VOUT;
the measured flatness of the V-I characteristic is recorded in
sim/current-limit/records/.

Port order (also the .sym pin order -- do not reorder either file without
updating both, and without re-running design/netlist.py --check):
  VIN         supply, 3.3 V nominal
  VOUT        regulated output. The sense element returns here, so the sense
              current is DELIVERED to the load, not burned.
  PASS_GATE   pass-device gate: sensed (Msense's gate) and driven (Mclamp).
  EN          enable, active-high, CMOS level (0 / VIN)
  VREF        the core's reference (1.2 V, issue #9's value -- see
              design/error_amp.md "Why 1.2 V, not 0.6 V"). Sets the
              threshold; see below.
  VSS         ground

HOW THE THRESHOLD IS SET

  Msense is a 1/40 replica of ldo_core's Mpass: same L, same per-finger
  width (50 um), same source (VIN) and same gate (PASS_GATE), so it carries
  Ipass/40. Rsns returns that current to VOUT -- so the sensed current is
  DELIVERED TO THE LOAD rather than burned to ground, which is the whole
  reason a 1.8 mA sense current does not appear in the < 30 uA Iq budget.
  Returning to VOUT also keeps Msense's drain within ~100 mV of Mpass's
  drain at any output voltage, so the sense ratio stays accurate as VOUT
  collapses during an overload; that is what makes the limit brickwall
  rather than accidentally folded-back or (worse) inverse-folded-back.

  Rsns is drawn as m = 10 unit cells of W = 5 um / L = 7.6 um rather than as
  one 50 um-wide, 7.6 um-long slab: same ~56 ohm, but a shape a layout can
  actually match and one where the model's width bias is not being asked to
  extrapolate a resistor that is 6x wider than it is long.

  The threshold branch mirrors the same shape: Mrefp pushes Iref through
  Rref, also returned to VOUT, so VTH = VOUT + Iref*Rref. Both comparator
  inputs therefore ride on VOUT and the comparison is a pure differential
  one at any output voltage from 1.8 V down to a dead short.

  Trip condition:  Isense*Rsns = Iref*Rref,  Iref = VREF/Rbias

      I_limit = 41 * VREF * (Rref / Rbias) / Rsns

  (41, not 40: the sense branch's own current reaches the load too, so the
  LOAD current at trip is 41x the sense current, not 40x.)

  As built: Rbias = 360 squares of ppolyf_u_3k (~1.13 Mohm) -> Iref ~ 1.06 uA;
  Rref = 30 squares (~94 kohm) -> a ~100 mV threshold across Rsns ~ 56 ohm
  -> I_limit = 74.5 mA at tt/27 C/3.30 V, measured, and 62.0..93.8 mA over
  the full 63-point PVT matrix (sim/current-limit/records/).

  WHY 74.5 mA AND NOT LOWER. Two ratified rows bound this from below and one
  from above, and the resistor spread below makes all three unsatisfiable at
  once, so the centering is chosen to satisfy the two LOWER bounds at the
  worst corner and to overshoot the upper one by as little as possible:
    - "never engages for I_load <= 50 mA at any corner" (Current limit row)
    - "startup at full rated load stays >= 10 mA below the current limit"
      (Startup row) -> I_limit >= 60 mA at EVERY corner
    - "<= 290 mW into a Vout = 0 short at the 80 mA limit ceiling" (Thermal
      row) -> I_limit <= 79.9 mA at Vin_max = 3.63 V
  The as-built worst-case minimum is 62.0 mA (ss/-40 C/2.97 V), which clears
  both lower bounds; the maximum is 93.8 mA, which does not clear the upper
  one. Lowering the centering to clear 290 mW would put the minimum at
  ~53 mA, i.e. 6 % above the rated load -- inside the sense path's own error
  budget, so the limit would nuisance-trip inside the rated range at some
  corner. That trade is the subject of spec/decision-records/DR-0005.

  Rref and Rbias are the SAME flavour (ppolyf_u_3k), so their ratio is
  exactly corner- and temperature-invariant (sim/devchar/CONCLUSIONS.md
  section 2: global resistor spread is perfectly common-mode in these
  models) -- and their -1293 ppm/degC temperature coefficient cancels with
  it. Rsns is ppolyf_u, whose temperature coefficient is only
  -27.9 ppm/degC. What is left is ONE un-cancelled power of an absolute
  on-chip resistance, and that is irreducible: any threshold current is a
  voltage divided by a resistance. gf180mcu's resistor corner sections skew
  every poly flavour by +/-19..25 % (ppolyf_u: 295 / 369 / 442 ohm/sq at
  res_ff / typical / res_ss, i.e. 40 % ff-to-ss; the tightest flavour in the
  whole menu is npolyf_u at 38.7 %), so an untrimmed limit CANNOT be held
  inside the ratified +/-10 % window.

  The measurement isolates that cleanly: over the 63-point matrix the limit
  moves +/-20.4 %, and the corners that move it are exactly the resistor
  corners. The FET-skew corners that keep resistors typical (fs, sf) span
  71.0..72.7 mA against tt's 71.0..72.6 mA -- i.e. everything this circuit
  contributes (sense-ratio error, comparator offset drift, temperature,
  supply) is under +/-1.2 %, and the other +/-20 % is the resistor sheet
  alone. This is the DR-0004 revisit trigger for the current-limit row
  firing on measurement, and it fires on a PDK property rather than on a
  design deficiency; see spec/decision-records/DR-0005.

WHAT IS IDEALIZED HERE, AND WHY

  Fbias (a CCCS) is the ONE ideal element in the signal path. It copies the
  real current through the real Rbias branch into Mpd's drain, standing in
  for the bandgap-referenced bias-current generator this block does not own
  and which does not exist anywhere in this repo yet -- exactly as Vref1 in
  ldo_core stands in for the bandgap itself. Forcing VREF across a resistor
  without an amplifier is not possible: any diode-connected device in series
  subtracts its own Vgs (0.44-0.82 V measured, against a 0.6 V reference),
  which would make the bias -- and therefore the threshold -- Vt-dominated.
  Everything downstream of Fbias (Mpd/Mrefp mirror, the comparator, the
  clamp) is real devices at real corners, and the dominant real-world error
  term (Rsns's sheet-resistance spread) is fully in the simulation.

  Consequence to state when quoting a number from here: the measured spread
  EXCLUDES the bias generator's own error. A real bandgap-referenced Iref
  adds its error on top, so the measured spread is a LOWER BOUND on the
  as-built spread, which only strengthens the DR-0005 finding.

COMPARATOR AND CLAMP

  Mca/Mcb are a PMOS pair (Mca on ISNS, Mca conducts more while the sensed
  current is below threshold), loaded by the Mna/Mnb NMOS mirror. Idle -> CO
  is pulled to VSS -> Mg2 off -> Rl2 pulls CLG to VIN -> Mclamp is FULLY off
  and draws no static current and injects nothing into PASS_GATE. Overcurrent
  -> CO rises -> Mg2 pulls CLG down -> Mclamp sources current into PASS_GATE
  -> Mpass throttles. Negative feedback, so the limit regulates rather than
  latching.

  Rtail is a RESISTOR, not a current source, on purpose. The pair's input
  common mode is VOUT + ~100 mV, i.e. 1.9 V in regulation, and a PMOS tail
  current source needs VIN - CM - |Vt| - 2*Vov of headroom -- which at
  VIN = 2.97 V and |Vt| = 1.03 V (ss / -40 degC, sim/devchar/CONCLUSIONS.md
  section 1) does not exist. A starved tail current source leaves the
  comparator output floating and can spuriously clamp the pass gate at that
  corner. A resistor tail degrades gracefully instead: the tail node simply
  rises towards VIN and the pair slides into weak inversion, where the trip
  point (Mca and Mnb carrying equal current, i.e. V(ISNS) = V(VTH)) is
  unchanged because it does not depend on the tail current at all. The cost
  is a tail current that varies with VOUT (~1 uA in regulation, ~5 uA into a
  short, where quiescent current does not matter).

  Cc is a deliberate dominant pole on the comparator output: the limit loop
  is a SECOND feedback loop around the same pass device, and slowing it well
  below the main loop keeps the two from interacting. Sized from the
  cap_mim_2f0 density in sim/devchar/CONCLUSIONS.md section 3.

ENABLE / SHUTDOWN

  This block extends ldo_core's existing enable gate (Men) rather than
  adding a second enable path, per issue #11's guidance:

    Minv_p/n  a plain inverter producing ENB. Two devices, drawing static
              current in neither state, because EN is specified as a CMOS
              level (0 or VIN) and never sits at mid-rail. error_amp has its
              own local copy of this inverter for the same reason -- ENB is
              not routed between cells, so neither cell depends on the
              other's internal nets.
    Mben      kills the Rbias branch, so Iref -> 0.
    Men_t     opens the comparator's tail so the pair carries no current.
    Men_co    parks CO at VSS.
    Mcoff     holds CLG at VIN, so Mclamp is definitively off.

  Men_co is load-bearing and is the reason the inverter is here at all.
  Gating only the comparator's RETURN path (the first version of this block
  put an EN-switched NMOS between the Mna/Mnb mirror sources and VSS) leaves
  CO with no path to ground while Mcb still sources current from the tail:
  CO floats up to VIN, turns Mg2 fully on, and Mg2 then fights Mcoff for the
  CLG node. That measured 1.43 mA of crowbar current at tt/27 degC/3.3 V
  while DISABLED -- against a 3 uA shutdown budget. Killing the tail (Men_t)
  and actively parking the comparator output (Men_co) leaves no such fight;
  both are gated from ENB so they act exactly when EN is low.

  Disabled state therefore adds only device leakage, and the pass device is
  held off with NO active discharge of VOUT -- which is the disabled output
  state the ratified spec's Enable/shutdown row requires. Measured: 0.20 uA
  of shutdown current at the binding ff/125 C/3.63 V corner against a 3 uA
  budget, 0.21 uA of Vin->Vout leakage against a 1 uA budget
  (sim/enable-shutdown/records/). Note that this block's gating is only half
  of that number's story: issue #9's amplifier drew 9.2 uA whenever VDD was
  present and had no enable pin at all, so #11 also appended EN to error_amp
  and gated its bias there. Both had to happen; either alone leaves the row
  failing.

CLAMP AUTHORITY AGAINST THE REAL AMPLIFIER (#9)

  Mclamp wins the PASS_GATE node by out-sourcing whatever the amplifier
  sinks there. #9's error_amp drives that node from a PMOS common-source
  stage (M2P) into a ~5 uA NMOS current sink (M2N); in an overload the loop
  drives OUT low, i.e. M2P off and only M2N's few microamps left to fight.
  A 50 um / 0.5 um PMOS clamp sources milliamps, so it wins by three orders
  of magnitude -- measured, not assumed: the V-I sweeps in
  sim/current-limit/records/ are taken with the real amplifier in the loop
  and the limit regulates (flat to within 2.3 % from Vout = 1.764 V down to
  a dead short) at all 63 corners. Any future output stage with a strong
  pull-DOWN device (a class-AB or push-pull stage) would change this and
  must re-run that bench.

HANDOFF TO LAYOUT / ANY RE-SIZING OF Mpass

  N = 40 is the RATIO of Mpass's width to Msense's width, at equal L and
  equal per-finger width (50 um each). ldo_core's Mpass is W = 2000 um /
  nf = 40 today (issue #8's deliberate DC-sanity simplification of the
  ratified ~4 mm sizing). If Mpass is re-sized, Msense MUST be re-scaled
  with it or the limit moves by the same factor. In layout, Msense should be
  one unit cell of the same array as Mpass, in the array's interior, so the
  ratio survives gradients.} -1200 -1470 0 0 0.28 0.28 {}
C {devices/iopin.sym} -1200 -100 0 0 {name=p_vin lab=VIN}
C {devices/iopin.sym} -1000 -100 0 0 {name=p_vout lab=VOUT}
C {devices/iopin.sym} -800 -100 0 0 {name=p_pass_gate lab=PASS_GATE}
C {devices/ipin.sym} -600 -100 0 0 {name=p_en lab=EN}
C {devices/ipin.sym} -400 -100 0 0 {name=p_vref lab=VREF}
C {devices/iopin.sym} -200 -100 0 0 {name=p_vss lab=VSS}
C {symbols/pfet_03v3.sym} 0 -1000 0 0 {name=Msense model=pfet_03v3 L=0.28u W=50u nf=1 m=1}
C {devices/lab_pin.sym} -20 -1000 0 0 {name=l_msense_g sig_type=std_logic lab=PASS_GATE}
C {devices/lab_pin.sym} 20 -970 0 0 {name=l_msense_d sig_type=std_logic lab=ISNS}
C {devices/lab_pin.sym} 20 -1030 0 0 {name=l_msense_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 20 -1000 0 0 {name=l_msense_b sig_type=std_logic lab=VIN}
C {symbols/ppolyf_u.sym} 200 -1000 0 0 {name=Rsns model=ppolyf_u W=5u L=7.6u m=10}
C {devices/lab_pin.sym} 200 -1030 0 0 {name=l_rsns_p sig_type=std_logic lab=ISNS}
C {devices/lab_pin.sym} 200 -970 0 0 {name=l_rsns_m sig_type=std_logic lab=VOUT}
C {devices/lab_pin.sym} 180 -1000 0 0 {name=l_rsns_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 400 -1000 0 0 {name=Mpd model=pfet_03v3 L=2u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 380 -1000 0 0 {name=l_mpd_g sig_type=std_logic lab=PB}
C {devices/lab_pin.sym} 420 -970 0 0 {name=l_mpd_d sig_type=std_logic lab=PB}
C {devices/lab_pin.sym} 420 -1030 0 0 {name=l_mpd_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 420 -1000 0 0 {name=l_mpd_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 600 -1000 0 0 {name=Mrefp model=pfet_03v3 L=2u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 580 -1000 0 0 {name=l_mrefp_g sig_type=std_logic lab=PB}
C {devices/lab_pin.sym} 620 -970 0 0 {name=l_mrefp_d sig_type=std_logic lab=VTH}
C {devices/lab_pin.sym} 620 -1030 0 0 {name=l_mrefp_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 620 -1000 0 0 {name=l_mrefp_b sig_type=std_logic lab=VIN}
C {symbols/ppolyf_u_3k.sym} 800 -1000 0 0 {name=Rref model=ppolyf_u_3k W=1u L=30u m=1}
C {devices/lab_pin.sym} 800 -1030 0 0 {name=l_rref_p sig_type=std_logic lab=VTH}
C {devices/lab_pin.sym} 800 -970 0 0 {name=l_rref_m sig_type=std_logic lab=VOUT}
C {devices/lab_pin.sym} 780 -1000 0 0 {name=l_rref_b sig_type=std_logic lab=VSS}
C {devices/cccs.sym} 1000 -1000 0 0 {name=Fbias vnam=Vbsense value=1}
C {devices/lab_pin.sym} 1000 -1030 0 0 {name=l_fbias_p sig_type=std_logic lab=PB}
C {devices/lab_pin.sym} 1000 -970 0 0 {name=l_fbias_m sig_type=std_logic lab=VSS}
C {devices/vsource.sym} 1200 -1000 0 0 {name=Vbsense value=0}
C {devices/lab_pin.sym} 1200 -1030 0 0 {name=l_vbsense_p sig_type=std_logic lab=VREF}
C {devices/lab_pin.sym} 1200 -970 0 0 {name=l_vbsense_m sig_type=std_logic lab=BT}
C {symbols/ppolyf_u_3k.sym} 1400 -1000 0 0 {name=Rbias model=ppolyf_u_3k W=1u L=360u m=1}
C {devices/lab_pin.sym} 1400 -1030 0 0 {name=l_rbias_p sig_type=std_logic lab=BT}
C {devices/lab_pin.sym} 1400 -970 0 0 {name=l_rbias_m sig_type=std_logic lab=BB}
C {devices/lab_pin.sym} 1380 -1000 0 0 {name=l_rbias_b sig_type=std_logic lab=VSS}
C {symbols/nfet_03v3.sym} 1600 -1000 0 0 {name=Mben model=nfet_03v3 L=0.5u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 1620 -1030 0 0 {name=l_mben_d sig_type=std_logic lab=BB}
C {devices/lab_pin.sym} 1580 -1000 0 0 {name=l_mben_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 1620 -970 0 0 {name=l_mben_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1620 -1000 0 0 {name=l_mben_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 0 -600 0 0 {name=Mca model=pfet_03v3 L=1u W=20u nf=1 m=1}
C {devices/lab_pin.sym} -20 -600 0 0 {name=l_mca_g sig_type=std_logic lab=ISNS}
C {devices/lab_pin.sym} 20 -570 0 0 {name=l_mca_d sig_type=std_logic lab=CN}
C {devices/lab_pin.sym} 20 -630 0 0 {name=l_mca_s sig_type=std_logic lab=TAIL}
C {devices/lab_pin.sym} 20 -600 0 0 {name=l_mca_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 200 -600 0 0 {name=Mcb model=pfet_03v3 L=1u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 180 -600 0 0 {name=l_mcb_g sig_type=std_logic lab=VTH}
C {devices/lab_pin.sym} 220 -570 0 0 {name=l_mcb_d sig_type=std_logic lab=CO}
C {devices/lab_pin.sym} 220 -630 0 0 {name=l_mcb_s sig_type=std_logic lab=TAIL}
C {devices/lab_pin.sym} 220 -600 0 0 {name=l_mcb_b sig_type=std_logic lab=VIN}
C {symbols/ppolyf_u_3k.sym} 400 -600 0 0 {name=Rtail model=ppolyf_u_3k W=1u L=150u m=1}
C {devices/lab_pin.sym} 400 -630 0 0 {name=l_rtail_p sig_type=std_logic lab=TAILP}
C {devices/lab_pin.sym} 400 -570 0 0 {name=l_rtail_m sig_type=std_logic lab=TAIL}
C {devices/lab_pin.sym} 380 -600 0 0 {name=l_rtail_b sig_type=std_logic lab=VSS}
C {symbols/nfet_03v3.sym} 600 -600 0 0 {name=Mna model=nfet_03v3 L=1u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 620 -630 0 0 {name=l_mna_d sig_type=std_logic lab=CN}
C {devices/lab_pin.sym} 580 -600 0 0 {name=l_mna_g sig_type=std_logic lab=CN}
C {devices/lab_pin.sym} 620 -570 0 0 {name=l_mna_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 620 -600 0 0 {name=l_mna_b sig_type=std_logic lab=VSS}
C {symbols/nfet_03v3.sym} 800 -600 0 0 {name=Mnb model=nfet_03v3 L=1u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 820 -630 0 0 {name=l_mnb_d sig_type=std_logic lab=CO}
C {devices/lab_pin.sym} 780 -600 0 0 {name=l_mnb_g sig_type=std_logic lab=CN}
C {devices/lab_pin.sym} 820 -570 0 0 {name=l_mnb_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 820 -600 0 0 {name=l_mnb_b sig_type=std_logic lab=VSS}
C {symbols/nfet_03v3.sym} 1000 -600 0 0 {name=Men_co model=nfet_03v3 L=0.5u W=20u nf=1 m=1}
C {devices/lab_pin.sym} 1020 -630 0 0 {name=l_menco_d sig_type=std_logic lab=CO}
C {devices/lab_pin.sym} 980 -600 0 0 {name=l_menco_g sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 1020 -570 0 0 {name=l_menco_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1020 -600 0 0 {name=l_menco_b sig_type=std_logic lab=VSS}
C {symbols/cap_mim_2f0fF.sym} 1200 -600 0 0 {name=Cc model=cap_mim_2f0_m2m3_noshield W=25u L=20u m=1}
C {devices/lab_pin.sym} 1200 -630 0 0 {name=l_cc_g sig_type=std_logic lab=CO}
C {devices/lab_pin.sym} 1200 -570 0 0 {name=l_cc_b sig_type=std_logic lab=VSS}
C {symbols/nfet_03v3.sym} 1400 -600 0 0 {name=Mg2 model=nfet_03v3 L=1u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 1420 -630 0 0 {name=l_mg2_d sig_type=std_logic lab=CLG}
C {devices/lab_pin.sym} 1380 -600 0 0 {name=l_mg2_g sig_type=std_logic lab=CO}
C {devices/lab_pin.sym} 1420 -570 0 0 {name=l_mg2_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 1420 -600 0 0 {name=l_mg2_b sig_type=std_logic lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1600 -600 0 0 {name=Rl2 model=ppolyf_u_3k W=1u L=150u m=1}
C {devices/lab_pin.sym} 1600 -630 0 0 {name=l_rl2_p sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 1600 -570 0 0 {name=l_rl2_m sig_type=std_logic lab=CLG}
C {devices/lab_pin.sym} 1580 -600 0 0 {name=l_rl2_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 1800 -600 0 0 {name=Mcoff model=pfet_03v3 L=0.5u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 1780 -600 0 0 {name=l_mcoff_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 1820 -570 0 0 {name=l_mcoff_d sig_type=std_logic lab=CLG}
C {devices/lab_pin.sym} 1820 -630 0 0 {name=l_mcoff_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 1820 -600 0 0 {name=l_mcoff_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 2000 -600 0 0 {name=Mclamp model=pfet_03v3 L=0.5u W=50u nf=1 m=1}
C {devices/lab_pin.sym} 1980 -600 0 0 {name=l_mclamp_g sig_type=std_logic lab=CLG}
C {devices/lab_pin.sym} 2020 -570 0 0 {name=l_mclamp_d sig_type=std_logic lab=PASS_GATE}
C {devices/lab_pin.sym} 2020 -630 0 0 {name=l_mclamp_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 2020 -600 0 0 {name=l_mclamp_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 0 -200 0 0 {name=Minv_p model=pfet_03v3 L=0.5u W=4u nf=1 m=1}
C {devices/lab_pin.sym} -20 -200 0 0 {name=l_minvp_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 20 -170 0 0 {name=l_minvp_d sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 20 -230 0 0 {name=l_minvp_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 20 -200 0 0 {name=l_minvp_b sig_type=std_logic lab=VIN}
C {symbols/nfet_03v3.sym} 200 -200 0 0 {name=Minv_n model=nfet_03v3 L=0.5u W=2u nf=1 m=1}
C {devices/lab_pin.sym} 220 -230 0 0 {name=l_minvn_d sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 180 -200 0 0 {name=l_minvn_g sig_type=std_logic lab=EN}
C {devices/lab_pin.sym} 220 -170 0 0 {name=l_minvn_s sig_type=std_logic lab=VSS}
C {devices/lab_pin.sym} 220 -200 0 0 {name=l_minvn_b sig_type=std_logic lab=VSS}
C {symbols/pfet_03v3.sym} 400 -200 0 0 {name=Men_t model=pfet_03v3 L=0.5u W=10u nf=1 m=1}
C {devices/lab_pin.sym} 380 -200 0 0 {name=l_ment_g sig_type=std_logic lab=ENB}
C {devices/lab_pin.sym} 420 -170 0 0 {name=l_ment_d sig_type=std_logic lab=TAILP}
C {devices/lab_pin.sym} 420 -230 0 0 {name=l_ment_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 420 -200 0 0 {name=l_ment_b sig_type=std_logic lab=VIN}
