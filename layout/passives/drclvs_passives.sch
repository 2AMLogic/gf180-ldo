v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {drclvs_passives -- the passive-bearing DRC/LVS flow vehicle (issue #313).

WHAT IT IS FOR: layout/testcell is one nfet, and a cell whose only device is
a FET cannot notice that the flow is broken for everything else. The gf180mcu
PDK's xschem symbols carry an `lvs_format` attribute ONLY on the FETs, so with
`lvs_netlist 1` every resistor and capacitor still comes out in xschem's
SIMULATION form (an X-prefixed subcircuit call), which KLayout's SPICE reader
turns into an empty subcircuit instead of a device. layout/lvs_form.py renders
those as primitive R/C elements; this cell is what proves that end to end
against the PDK's own DRC and LVS decks.

Like drclvs_testcell it is NOT part of the LDO: nothing in design/ or sim/
instantiates it, and it says nothing about the regulator.

THREE DEVICES, DELIBERATELY UNCONNECTED TO EACH OTHER:

  R1  ppolyf_u_1k        1 um x 10 um H-poly resistor. 3-terminal: its bulk
                         is the substrate, which the LVS deck names via its
                         own connect_global(sub, <lvs_sub>).
  C1  cap_mim_2f0        20 um x 20 um MIM capacitor. The only device here
                         whose terminals are not on metal1/poly2 -- for the
                         5LM/MIM-option-B stack this repo builds against they
                         are metal4 (bottom) and metal5 (top, through
                         fusetop), hence the model name below.
  M1  nfet_03v3          W=6 um total across nf=2 fingers, L=0.28 um. Gives
                         stages 6/7 a MOS line to corrupt, and checks that the
                         deck's multifinger merge still lands ONE device.

They share no nets on purpose: interconnect would add routing-DRC and
extraction variables that have nothing to do with what is under test.

MODEL NAMES ARE NOT FREE CHOICES. KLayout's netlist compare matches device
classes BY NAME, so each `model=` here has to be the name the LVS deck's own
extraction registers:
  - `ppolyf_u_1k` because layout/drclvs.py passes poly_res=1k (the deck
    extracts exactly one H-poly flavour per run -- see issue #312);
  - `cap_mim_2f0_m4m5_noshield` because the deck's MIM branch for
    mim_option=B + metal_level=5LM + mim_cap=2 registers that name.
Changing either switch in layout/drclvs.py means changing the model here.

PARAMETERS ARE THE ELECTRICAL ONES, not the PCell's. The resistor PCell's `w`
is the electrical LENGTH (contacts sit on the left and right edges, so current
flows along it) and its `l` is the electrical WIDTH; the FET PCell's `w` is
per-finger while `W` here is the total. layout/passives/gen_gds.py spells both
out, and the LVS compare is what catches a drift between the two files.

PORTS (order is the .subckt port order -- it comes from the iopin/ipin
instance order below, and drclvs_passives.sym must list the same order):

    RP  RM  CT  CB  D  G  S  VSS

VSS is the FET's bulk AND the substrate net name handed to the LVS deck's
lvs_sub switch; the resistor's bulk terminal resolves to the same net.} -600 -560 0 0 0.4 0.4 {}
C {symbols/ppolyf_u_1k.sym} 0 0 0 0 {name=R1 model=ppolyf_u_1k W=1u L=10u m=1}
C {symbols/cap_mim_2f0fF.sym} 200 0 0 0 {name=C1 model=cap_mim_2f0_m4m5_noshield W=20u L=20u m=1}
C {symbols/nfet_03v3.sym} 400 0 0 0 {name=M1 model=nfet_03v3 L=0.28u W=6u nf=2 m=1}
C {devices/lab_pin.sym} -20 0 0 0 {name=l_rb sig_type=std_logic lab=VSS}
C {devices/iopin.sym} 0 -30 0 0 {name=p_rp lab=RP}
C {devices/iopin.sym} 0 30 0 0 {name=p_rm lab=RM}
C {devices/iopin.sym} 200 -30 0 0 {name=p_ct lab=CT}
C {devices/iopin.sym} 200 30 0 0 {name=p_cb lab=CB}
C {devices/iopin.sym} 420 -30 0 0 {name=p_d lab=D}
C {devices/ipin.sym} 380 0 0 0 {name=p_g lab=G}
C {devices/iopin.sym} 420 30 0 0 {name=p_s lab=S}
C {devices/iopin.sym} 420 0 0 0 {name=p_vss lab=VSS}
