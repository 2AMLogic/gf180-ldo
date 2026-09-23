v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {fb_divider -- the feedback divider, LVS reference netlist (issue #286).

This is the SCHEMATIC side of the divider that layout/divider/gen_gds.py
draws, and the only reason it exists: `design/netlist/ldo_core.spice` still
carries the divider as two IDEAL resistors (`Rtop` 300k, `Rbot` 600k), which
is not a netlist LVS can compare a real unit-resistor array against. The
array is the same 900 kOhm (DR-0001's ~2 uA preload is unchanged); it is the
same 1:2 tap (DR-0003's unit-string requirement); it is just drawn as the 18
units floorplan.md section 4.1 plans instead of as two lumped values.

STRUCTURE, matching layout/divider/gen_gds.py unit for unit:

    Rb1..Rb12   VSS -> nb1 -> ... -> nb11 -> FB      12 x 50k = 600k  (Rbot)
    Rt1..Rt6    FB  -> nt1 -> ... -> nt5  -> VOUT_S   6 x 50k = 300k  (Rtop)
    Rdum0, Rdum19                                     the end dummy strips,
                                                      both ends tied to VSS

Every unit is the same drawn device: ppolyf_u_3k, W = 2 um, L = 31.8 um. The
31.8 um is 50 kOhm against sim/devchar's MEASURED effective sheet for this
flavour (3.145 kOhm/sq, CONCLUSIONS.md section 2). The LVS deck's own nominal
3.0 kOhm/sq would call the same strip 47.7 kOhm -- which changes nothing
here, because the deck compares W and L and explicitly disables R
(BResistor in rule_decks/custom_classes.lvs).

PORTS (the .subckt port order, from fb_divider.sym):

    VOUT_S  FB  VSS

VOUT_S is the Kelvin SENSE net, not the force net (floorplan.md section 5):
the divider's ~2 uA is the only current it carries. VSS is the resistors'
bulk terminal AND the substrate net handed to the LVS deck's lvs_sub switch,
so the layout's guard ring resolves to the same net as this schematic's VSS
port.

WHY EACH INSTANCE CARRIES ITS OWN lvs_format: the PDK's ppolyf_u_3k symbol
has a `format` (an ngspice subcircuit call, `XR1 ... r_width=.. r_length=..`)
but NO `lvs_format`, so under layout/xschemrc's `lvs_netlist 1` xschem would
fall back to the simulation form -- which KLayout's SPICE reader cannot read,
and whose r_width/r_length would not reach the reader's W/L parameters at
all. The per-instance attribute below supplies the missing LVS rendering
without copying a PDK symbol into this repo. See layout/README.md.
} -600 -560 0 0 0.4 0.4 {}
C {symbols/ppolyf_u_3k.sym} 0 0 0 0 {name=Rb1 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 0 30 0 0 {name=l_rb1_m lab=nb1}
C {devices/lab_pin.sym} 0 -30 0 0 {name=l_rb1_p lab=VSS}
C {devices/lab_pin.sym} -20 0 0 0 {name=l_rb1_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 100 0 0 0 {name=Rb2 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 100 30 0 0 {name=l_rb2_m lab=nb2}
C {devices/lab_pin.sym} 100 -30 0 0 {name=l_rb2_p lab=nb1}
C {devices/lab_pin.sym} 80 0 0 0 {name=l_rb2_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 200 0 0 0 {name=Rb3 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 200 30 0 0 {name=l_rb3_m lab=nb3}
C {devices/lab_pin.sym} 200 -30 0 0 {name=l_rb3_p lab=nb2}
C {devices/lab_pin.sym} 180 0 0 0 {name=l_rb3_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 300 0 0 0 {name=Rb4 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 300 30 0 0 {name=l_rb4_m lab=nb4}
C {devices/lab_pin.sym} 300 -30 0 0 {name=l_rb4_p lab=nb3}
C {devices/lab_pin.sym} 280 0 0 0 {name=l_rb4_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 400 0 0 0 {name=Rb5 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 400 30 0 0 {name=l_rb5_m lab=nb5}
C {devices/lab_pin.sym} 400 -30 0 0 {name=l_rb5_p lab=nb4}
C {devices/lab_pin.sym} 380 0 0 0 {name=l_rb5_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 500 0 0 0 {name=Rb6 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 500 30 0 0 {name=l_rb6_m lab=nb6}
C {devices/lab_pin.sym} 500 -30 0 0 {name=l_rb6_p lab=nb5}
C {devices/lab_pin.sym} 480 0 0 0 {name=l_rb6_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 600 0 0 0 {name=Rb7 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 600 30 0 0 {name=l_rb7_m lab=nb7}
C {devices/lab_pin.sym} 600 -30 0 0 {name=l_rb7_p lab=nb6}
C {devices/lab_pin.sym} 580 0 0 0 {name=l_rb7_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 700 0 0 0 {name=Rb8 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 700 30 0 0 {name=l_rb8_m lab=nb8}
C {devices/lab_pin.sym} 700 -30 0 0 {name=l_rb8_p lab=nb7}
C {devices/lab_pin.sym} 680 0 0 0 {name=l_rb8_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 800 0 0 0 {name=Rb9 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 800 30 0 0 {name=l_rb9_m lab=nb9}
C {devices/lab_pin.sym} 800 -30 0 0 {name=l_rb9_p lab=nb8}
C {devices/lab_pin.sym} 780 0 0 0 {name=l_rb9_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 900 0 0 0 {name=Rb10 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 900 30 0 0 {name=l_rb10_m lab=nb10}
C {devices/lab_pin.sym} 900 -30 0 0 {name=l_rb10_p lab=nb9}
C {devices/lab_pin.sym} 880 0 0 0 {name=l_rb10_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1000 0 0 0 {name=Rb11 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 1000 30 0 0 {name=l_rb11_m lab=nb11}
C {devices/lab_pin.sym} 1000 -30 0 0 {name=l_rb11_p lab=nb10}
C {devices/lab_pin.sym} 980 0 0 0 {name=l_rb11_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1100 0 0 0 {name=Rb12 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 1100 30 0 0 {name=l_rb12_m lab=FB}
C {devices/lab_pin.sym} 1100 -30 0 0 {name=l_rb12_p lab=nb11}
C {devices/lab_pin.sym} 1080 0 0 0 {name=l_rb12_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1200 0 0 0 {name=Rt1 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 1200 30 0 0 {name=l_rt1_m lab=nt1}
C {devices/lab_pin.sym} 1200 -30 0 0 {name=l_rt1_p lab=FB}
C {devices/lab_pin.sym} 1180 0 0 0 {name=l_rt1_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1300 0 0 0 {name=Rt2 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 1300 30 0 0 {name=l_rt2_m lab=nt2}
C {devices/lab_pin.sym} 1300 -30 0 0 {name=l_rt2_p lab=nt1}
C {devices/lab_pin.sym} 1280 0 0 0 {name=l_rt2_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1400 0 0 0 {name=Rt3 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 1400 30 0 0 {name=l_rt3_m lab=nt3}
C {devices/lab_pin.sym} 1400 -30 0 0 {name=l_rt3_p lab=nt2}
C {devices/lab_pin.sym} 1380 0 0 0 {name=l_rt3_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1500 0 0 0 {name=Rt4 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 1500 30 0 0 {name=l_rt4_m lab=nt4}
C {devices/lab_pin.sym} 1500 -30 0 0 {name=l_rt4_p lab=nt3}
C {devices/lab_pin.sym} 1480 0 0 0 {name=l_rt4_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1600 0 0 0 {name=Rt5 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 1600 30 0 0 {name=l_rt5_m lab=nt5}
C {devices/lab_pin.sym} 1600 -30 0 0 {name=l_rt5_p lab=nt4}
C {devices/lab_pin.sym} 1580 0 0 0 {name=l_rt5_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1700 0 0 0 {name=Rt6 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 1700 30 0 0 {name=l_rt6_m lab=VOUT_S}
C {devices/lab_pin.sym} 1700 -30 0 0 {name=l_rt6_p lab=nt5}
C {devices/lab_pin.sym} 1680 0 0 0 {name=l_rt6_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1800 0 0 0 {name=Rdum0 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 1800 30 0 0 {name=l_rdum0_m lab=VSS}
C {devices/lab_pin.sym} 1800 -30 0 0 {name=l_rdum0_p lab=VSS}
C {devices/lab_pin.sym} 1780 0 0 0 {name=l_rdum0_b lab=VSS}
C {symbols/ppolyf_u_3k.sym} 1900 0 0 0 {name=Rdum19 model=ppolyf_u_3k W=2u L=31.8u m=1 lvs_format="@name @pinlist @model W=@W L=@L m=@m"}
C {devices/lab_pin.sym} 1900 30 0 0 {name=l_rdum19_m lab=VSS}
C {devices/lab_pin.sym} 1900 -30 0 0 {name=l_rdum19_p lab=VSS}
C {devices/lab_pin.sym} 1880 0 0 0 {name=l_rdum19_b lab=VSS}
C {devices/iopin.sym} 0 -200 0 0 {name=p_vout_s lab=VOUT_S}
C {devices/iopin.sym} 100 -200 0 0 {name=p_fb lab=FB}
C {devices/iopin.sym} 200 -200 0 0 {name=p_vss lab=VSS}
