v {xschem version=3.4.7 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
T {pass_array -- the LVS reference for the pass-device array and its Msense
replica (issue #285, parent #173).

WHAT THIS IS. layout/pass_array/gen_gds.py draws N = 40 pass-device unit cells
and M = 1 Msense unit cell of the SAME cell; this schematic is the netlist that
layout is compared against. It is a LAYOUT-side reference, not a simulation
cell: nothing in sim/ sources it, and design/netlist.py does not netlist it.
The devices it declares are exactly the two the LDO already ships --

    design/netlist/ldo_core.spice:
      XMpass  VOUT PASS_GATE VIN VIN pfet_03v3 L=0.28u W=2800u nf=40
      XMsense ISNS PASS_GATE VIN VIN pfet_03v3 L=0.28u W=70u   nf=1

-- copied here so the array can be LVS'd on its own rather than only as part of
a top-level assembly that does not exist yet. layout/tests/test_pass_array.py
is what stops the copy drifting: it re-derives both device lines from
design/netlist/ldo_core.spice and fails if they no longer agree.

WHY Mpass IS ONE LINE AND NOT 40. The array is drawn as 40 unit cells, but the
gf180mcu LVS deck's mos4 extractor merges fingers that share gate, source and
drain into one device -- verified, and the merge crosses the diffusion break
either side of Msense, so the layout extracts as exactly:

    M$1  VOUT PASS_GATE VIN VIN pfet_03v3 L=0.28U W=2800U
    M$41 ISNS PASS_GATE VIN VIN pfet_03v3 L=0.28U W=70U

Writing Mpass as 40 parallel 70 um devices here would therefore MISMATCH. The
unit-cell construction is checked in the generator instead (it XORs 20 abutted
unit cells against the PDK's own nf=20 pfet), not by this netlist.

THE REPLICA RATIO IS GEOMETRY. N/M = 40 is fixed by how many copies of one cell
the generator places, and design/ldo_ilimit.sch's handoff note requires exactly
that: "Msense should be one unit cell of the same array as Mpass, in the
array's interior, so the ratio survives gradients." Re-sizing Mpass without
re-scaling Msense moves the current limit by the same factor.

NO VSS PORT. The pass device is a PMOS in an n-well tied to VIN; the only bulk
terminal in this cell is that n-well. The p-substrate is the LVS deck's global
substrate net (lvs_sub=VSS in layout/drclvs.py) and nothing here connects to
it, so it is not a port.

PORTS (order is the .subckt port order -- it comes from the iopin/ipin instance
order below, and pass_array.sym must list the same order):

    VIN  VOUT  ISNS  PASS_GATE} -600 -560 0 0 0.4 0.4 {}
C {symbols/pfet_03v3.sym} 0 0 0 0 {name=Mpass model=pfet_03v3 L=0.28u W=2800u nf=40 m=1}
C {devices/lab_pin.sym} -20 0 0 0 {name=l_mpass_g sig_type=std_logic lab=PASS_GATE}
C {devices/lab_pin.sym} 20 30 0 0 {name=l_mpass_d sig_type=std_logic lab=VOUT}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l_mpass_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 20 0 0 0 {name=l_mpass_b sig_type=std_logic lab=VIN}
C {symbols/pfet_03v3.sym} 200 0 0 0 {name=Msense model=pfet_03v3 L=0.28u W=70u nf=1 m=1}
C {devices/lab_pin.sym} 180 0 0 0 {name=l_msense_g sig_type=std_logic lab=PASS_GATE}
C {devices/lab_pin.sym} 220 30 0 0 {name=l_msense_d sig_type=std_logic lab=ISNS}
C {devices/lab_pin.sym} 220 -30 0 0 {name=l_msense_s sig_type=std_logic lab=VIN}
C {devices/lab_pin.sym} 220 0 0 0 {name=l_msense_b sig_type=std_logic lab=VIN}
C {devices/iopin.sym} 0 200 0 0 {name=p_vin lab=VIN}
C {devices/iopin.sym} 100 200 0 0 {name=p_vout lab=VOUT}
C {devices/iopin.sym} 200 200 0 0 {name=p_isns lab=ISNS}
C {devices/ipin.sym} 300 200 0 0 {name=p_pass_gate lab=PASS_GATE}
