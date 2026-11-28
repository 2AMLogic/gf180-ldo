# `sim/pass-array-pex/` -- array-alone bench for `klt pex` on `pass_array`

Issue #786. This is a **`klt pex` testbench**, not a `sim/harness` corner
bench: there is no `records/` or `corners/` tree here, the evidence it
produces is the committed `klt pex` report plus the
`layout/records/<id>.md` record (see `layout/pass_array/pex/README.md`),
and it is never run standalone through the harness's `klt_run.py` flow.

What it measures, on the array alone, at the dropout binding test point
(VIN = 2.10 V per DR-0004 note 4, PASS_GATE = 0 V -- the error amp
saturated low -- and a 50 mA sink, both drain pins tied to one node through
0 V sense sources):

- `vds_mv` / `r_on_mohm` -- pin-to-pin on-resistance of the array at 50 mA
- `replica_ratio` / `isns_ma` -- the Mpass:Msense current split at equal
  drain potential (40 by drawn geometry)
- `iload_ma` -- sink compliance sanity (50 mA)

Corner matrix: the `sim/dropout-vs-load` bench's -- process
{tt, ff, ss, fs, sf} x {-40, 27, 125} C at the single 2.10 V supply.

Files:

- `testbench/tb_pass_array.spice` -- the bench body. Its single `.include`
  line is the DUT swap point `klt pex` re-points at the extracted
  `PASS_ARRAY` netlist (exactly one `.include` is the `klt pex` contract);
  everything else is byte-identical on both legs, including the inlined PDK
  global switch params and `wnflag=1` (same preamble
  `sim/harness/tb_adapter.py` writes for every harness bench).
- `testbench/pass_array_dut.spice` -- the schematic DUT: the pinned-xschem
  ngspice export of `layout/pass_array/pass_array.sch`, with the `.subckt`
  pin line reordered to `klt extract`'s deterministic order (ports
  alphabetical) so one instantiation line is valid on both legs
  (`klt pex`'s "Pin order must match"). Device lines are byte-identical to
  the export; `layout/pass_array/netlist/pass_array.spice` remains the LVS
  reference.
- `testbench/request.json` -- the `klt sim` request `klt pex` re-runs on
  both sides (plus the `--device-only-leg` third leg).

Re-run (evidence lands in a new `layout/records/` record, never here):

```sh
klayout -b -r layout/pass_array/gen_gds.py -rd out=<work>/pass_array.gds -rd pdk=<gf180mcuD>
klt pex <work>/pass_array.gds sim/pass-array-pex/testbench/request.json \
    --deck gf180mcu --pdk gf180mcuD --top PASS_ARRAY --device-only-leg \
    --backend batch --wait-for-capacity 600 --envelope-out <report.json>
```

The measured quantities declare no limits on purpose: they are not spec
rows. The `delta[]` the pex report computes against them is the evidence,
and its reading (including why the absolute extracted R overstates a
40-branch comb -- klayout-tools#5894) is in the record, not re-derived
here.
