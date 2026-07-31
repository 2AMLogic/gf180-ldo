# design/ -- xschem sources and netlist export

Schematic entry for the LDO core, in xschem, against the gf180mcu PDK. This
directory is the **source of truth for the block's electrical interface**:
`sim/` testbenches (and later `layout/` LVS) both consume the netlists
exported from here.

> **Status (issue #8): hierarchy, pinout, and the enable path are real; the
> error amplifier and current limit are placeholders / out of scope.** See
> "Scope split" below before building on top of this.

## Cells

```
ldo_core                          top level -- issue #8
└── ldo_erramp_placeholder        behavioral placeholder error amp -- issue #8
                                  (real amp lands with issue #9, same pinout)
```

## `ldo_core` pinout (established by issue #8, in netlist port order)

| Pin          | Dir   | Meaning |
| ------------ | ----- | ------- |
| `VIN`        | inout | Supply, 3.3 V nominal |
| `VOUT`       | inout | Regulated output, 1.8 V nominal. Also the current-sense tap for issue #11 (see below). |
| `EN`         | in    | Enable, active-high, CMOS-level (0 V / VIN) |
| `VSS`        | inout | Ground |
| `ERRAMP_OUT` | out   | Loop-break point, output side (error-amp output) |
| `PASS_GATE`  | in    | Loop-break point, input side (pass-device gate) |

`python3 design/netlist.py --check` asserts this exact port list (and that
the `.sym` pin order matches the `.sch` port order for every cell) so a
schematic edit that drifts from this interface fails loudly instead of
quietly shipping. Changing it means renegotiating with whichever of
#9/#10/#11/#12/#13 depend on the field being changed.

### Loop-break point: two ports, not one

`ERRAMP_OUT` and `PASS_GATE` are **deliberately not connected to each other**
inside `ldo_core` -- normally (closed-loop operation) they carry the same
node, but that tie is made *outside* the subcircuit, at the testbench level,
not inside the schematic:

```spice
Xdut VIN VOUT EN 0 LOOP LOOP ldo_core     * ties ERRAMP_OUT and PASS_GATE
                                           * to the same net ("LOOP") at
                                           * instantiation -- a plain wire
```

A future stability testbench (issue #10) replaces that plain tie with a
Middlebrook/Tian injection network instead, to measure loop gain/phase --
without ever touching `design/ldo_core.sch`. This is why the ratified
interface has 6 ports instead of the 4 a purely functional view would
suggest.

### Current-sense tap for issue #11

The pass device's drain connects directly to `VOUT` (`XMpass`'s `D` pin, in
`design/ldo_core.spice`). That direct wire is the tap point: issue #11 (which
this issue does **not** implement) cuts into that wire to insert a
current-limit/foldback sense element, without needing to restructure
anything else in this schematic.

### Enable stub

`Men`, a single `pfet_03v3` clamp (source/body tied to `VIN`, gate tied to
`EN`, drain tied to `PASS_GATE`), pulls the pass-device gate to `VIN` --
turning the pass FET off -- whenever `EN` = 0. This is a **minimal functional
stub**, not a characterized shutdown path: full shutdown-quiescent-current
verification is issue #11's job. See
`sim/op-point-sanity/records/` for a measured confirmation that this drops
supply current roughly 300x (1.007 mA -> 3.3 uA) at the nominal PVT point.

## Scope split (read before building on top of this)

Three sibling issues share this schematic's territory; each owns a
different, non-overlapping piece:

- **#8 (this issue)**: pass device, feedback divider, compensation-ready
  `VOUT` node, enable stub, and a **placeholder** error amp -- just enough
  to close the loop for a DC sanity check.
- **#9 (error amp)**: replaces `ldo_erramp_placeholder` with a real
  differential-pair + gain-stage subcircuit. Must keep the `INP INN OUT VDD
  VSS` pinout (see `ldo_erramp_placeholder.sym`) and the `INP`=non-inverting,
  `INN`=inverting polarity (`INP` wired to `FB`, `INN` wired to `VREF` inside
  `ldo_core` -- do not flip this when replacing the placeholder; it is the
  polarity negative feedback around a PMOS common-source pass device
  requires).
- **#11 (current limit / foldback, and enable verification)**: builds the
  actual current-limit/foldback circuitry at the current-sense tap described
  above, and does the full shutdown-Iq characterization the enable stub
  above does not attempt. Neither is implemented here.

## Placeholder error amp (`ldo_erramp_placeholder`)

- Pinout: `INP INN OUT VDD VSS` (the swap-in contract for #9).
- Implementation: a behavioral (`B`) source, `V(OUT') = clamp(av*(V(INP)
  - V(INN)), V(VSS), V(VDD))`, `av` = 3162 (~70 dB, within the 60-80 dB the
  issue's guidance allows), through a 1 MOhm output resistor to `OUT`.
  - The clamp matters: without it, an ideal *unclamped* linear source
    overdriven by a large differential (e.g. `EN`=0, where `FB` collapses
    towards 0 V while `VREF` stays at 0.6 V) computes a wildly
    out-of-range value that then fights the enable clamp through `Rout`
    instead of being dominated by it.
  - The 1 MOhm `Rout` has **zero effect on the enabled-case DC solution**
    (`PASS_GATE` only ever sinks/sources a real MOSFET gate's ~0 DC
    current there) -- it only has to be large enough that the enable
    clamp (a modest, unsized-for-this single PMOS) reliably wins the node
    when `EN`=0. Do not shrink it to "look more realistic" without
    re-checking the disabled-state op point.
- `Rplaceholder_vdd` (1 TOhm, `VDD` to `VSS`) is not design content -- it only
  avoids a floating `VDD` pin on a stub with no real bias network yet.
  Delete it when #9 lands a real amp that draws bias current from `VDD`.

## Reference voltage assumption

There is no bandgap block designed yet for this repo. `Vref1`, an ideal
0.6 V DC source, stands in for it inside `ldo_core`. The feedback divider
(`Rtop`=200k, `Rbot`=100k, plain behavioral `R`, from `VOUT` to `VSS` via the
`FB` midpoint) is sized against this 0.6 V assumption: `FB = VOUT *
Rbot/(Rtop+Rbot) = VOUT/3`, so `VOUT` settles at `3 * VREF` = 1.8 V. If a
future bandgap issue lands a different reference voltage, the divider
**ratio** (not the topology) is what needs to change.

The divider itself is plain behavioral `R`, not the PDK's `ppolyf_u_3k` poly
resistor -- issue #8's guidance allows either for this sanity netlist.
Sheet-resistance-accurate `ppolyf_u_3k` sizing (needed for a layout-matched
divider) is deferred to whichever future issue needs it (e.g. a mismatch /
Monte Carlo study).

## Pass device sizing (a deliberate simplification for this issue)

`Mpass` (`pfet_03v3`, `L`=0.28 um, `W`=2000 um / 2 mm, `nf`=40, `m`=1) is
**smaller** than the ~4 mm / 40-unit-cell sizing the ratified spec calls for
to clear 300 mV dropout @ 50 mA at the worst corner. 2 mm is issue #8's
guidance's stated acceptable size for the DC-sanity loop-closure test only,
at effectively no load beyond the ~1 mA the sanity testbench applies. The
full sizing (and the unit-cell partitioning a layout needs for matching) is
layout-phase work, out of scope here.

## Exporting the netlist

```bash
python3 design/netlist.py            # regenerate design/netlist/*.spice
python3 design/netlist.py --check    # verify committed netlists are current
python3 design/netlist.py --cell ldo_erramp_placeholder -v
```

Requirements: `xschem` on `PATH` and the gf180mcu PDK installed. PDK discovery
is delegated to `sim/harness/pdk.py` -- the same resolver the corner runner
uses -- so `python3 sim/run_corners.py --check-env` diagnoses a missing PDK
for both.

Under the hood, per cell, with xschem's electrical rule check enabled:

```bash
xschem -x -q -r --rcfile design/xschemrc -o <outdir> design/<cell>.sch \
  --command "xschem netlist -erc"
```

`-x` batch (no X11), `-q` quit when done, `-r` no tclreadline. `design/xschemrc`
sets the library path (xschem devices -> PDK symbols -> `design/`) and,
critically, `top_is_subckt 1`: **every** cell -- including the top -- netlists
as a `.subckt`, never as a flat simulation deck. Cells here are blocks that
testbenches instantiate; the deck belongs to the testbench.

`netlist.py` then rewrites the absolute paths xschem records in its `sch_path`
/ `sym_path` comments to repo-relative form, and treats any of xschem's
undriven-node / shorted-node / shorted-pin / missing-symbol messages as a hard
failure (xschem exits 0 even when it prints these, so a naive exit-code check
would miss them). That is what makes the export **deterministic and
ERC-checked**: the same sources produce byte-identical netlists on any
machine, and a broken wire never silently ships.

### What `--check` verifies

1. **Committed netlists are current** -- regenerating into a temp directory
   reproduces `design/netlist/*.spice` byte-for-byte. This is simultaneously
   the staleness check and the reproducibility check.
2. **ERC is clean** -- see above.
3. **The top-level pinout matches the interface table above** -- exact port
   list and order.
4. **Symbol pins match schematic ports**, per cell, in order. xschem takes
   the `.subckt` port list from the *symbol* when one exists, so a symbol
   that has drifted from its schematic silently drops or miswires a port on
   every instantiation.
5. **Every sub-circuit is instantiated in the top level** with the right
   number of nets.

`--check` exits non-zero on any failure and prints the offending diff, so it
is usable as a pre-commit or CI gate once a runner exists.

## Using the netlist from a testbench

`design/netlist/` holds one file per cell:

- `ldo_core.spice` -- the whole hierarchy: `ldo_core` plus every sub-circuit
  it instantiates (currently just `ldo_erramp_placeholder`). Include this to
  simulate the block.
- `ldo_erramp_placeholder.spice` -- that sub-circuit alone, so a future
  amp-only bench can target it in isolation.

```spice
.include design/netlist/ldo_core.spice
Xdut VIN VOUT EN VSS ERRAMP_OUT PASS_GATE ldo_core
```

> **Include exactly one of these files per deck.** `ldo_core.spice` already
> contains the sub-circuit definition; including it *and*
> `ldo_erramp_placeholder.spice` redefines the same `.subckt` twice.

Port order is positional in SPICE -- take it from the `.subckt` line of the
file you include, or from the symbol pin list, which the check above keeps in
sync.

See `sim/op-point-sanity/` for a working example (a nominal-conditions DC
operating-point sanity testbench, per this issue's acceptance criterion).

## Working in the GUI

```bash
source sim/env.sh                                   # exports GF180_PDK_PATH etc.
xschem --rcfile design/xschemrc design/ldo_core.sch
```

Conventions:

- **PDK devices are referenced as `symbols/<device>.sym`** (e.g.
  `symbols/pfet_03v3.sym`), resolved against
  `$GF180_PDK_PATH/libs.tech/xschem`. Never write an absolute PDK path into a
  schematic.
- **Generic xschem devices are referenced as `devices/<name>.sym`** (e.g.
  `devices/res.sym`, `devices/vsource.sym`, `devices/bsource.sym`,
  `devices/lab_pin.sym`).
- **Project cells are referenced by bare name** (`ldo_erramp_placeholder.sym`),
  resolved against `design/`.
- **Connectivity is expressed with net labels** (`devices/lab_pin.sym`
  placed exactly at a device pin's coordinate, or the `lab=` attribute on an
  `ipin`/`opin`/`iopin` instance), not by relying on wires happening to touch
  across the schematic -- the same convention `gf180-pll`'s cell library
  uses.
- **Do not hand-edit `design/netlist/*.spice`.** Edit the schematic and
  re-run the export; `--check` will catch it if you forget.
- **Keep symbol pins and schematic ports in the same order.** When you add a
  port, add it to both the `.sch` and the `.sym`.
- Re-run `python3 design/netlist.py` and commit the regenerated netlists with
  the schematic change, so the netlist in the tree always matches the
  sources.
