# design/ -- xschem sources and netlist export

Schematic entry for the LDO core, in xschem, against the gf180mcu PDK. This
directory is the **source of truth for the block's electrical interface**:
`sim/` testbenches (and later `layout/` LVS) both consume the netlists
exported from here.

> **Status (issue #9): hierarchy, pinout, enable path and the error
> amplifier are real; the current limit is out of scope.** Issue #8 built
> this cell with a behavioral placeholder amp; issue #9 replaced that
> placeholder with `error_amp`, a real two-stage OTA designed against
> explicit offset / PSRR / Iq budgets (`design/error_amp.md`). See "Scope
> split" below before building on top of this.

## Cells

```
ldo_core                          top level -- issue #8
└── error_amp                     two-stage Miller-compensated OTA -- issue #9
                                  (replaced ldo_erramp_placeholder on the same
                                  INP INN OUT VDD VSS pinout; the placeholder
                                  cell is deleted, its contract is not)
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
`sim/op-point-sanity/records/` for a measured confirmation that this turns
the pass device off at the nominal PVT point. Since #9 landed a real
(self-biased) amplifier, the residual disabled-state supply current is set by
the amplifier's own bias branch (~9 uA), not by the pass device -- see
"Error amplifier" below.

## Scope split (read before building on top of this)

Three sibling issues share this schematic's territory; each owns a
different, non-overlapping piece:

- **#8**: pass device, feedback divider, compensation-ready `VOUT` node,
  enable stub, and (originally) a **placeholder** error amp -- just enough
  to close the loop for a DC sanity check.
- **#9 (error amp -- landed)**: replaced `ldo_erramp_placeholder` with
  `error_amp`, a real two-stage OTA. It keeps the `INP INN OUT VDD VSS`
  pinout and the `INP`=non-inverting / `INN`=inverting polarity (`INP` wired
  to `FB`, `INN` wired to `VREF` inside `ldo_core`) that the placeholder
  established; that polarity is what negative feedback around a PMOS
  common-source pass device requires, and it must not be flipped. #9 also
  moved `VREF` from 0.6 V to 1.2 V and re-ratioed the divider (see
  "Reference voltage" below and `design/error_amp.md`).
- **#11 (current limit / foldback, and enable verification)**: builds the
  actual current-limit/foldback circuitry at the current-sense tap described
  above, and does the full shutdown-Iq characterization the enable stub
  above does not attempt. Neither is implemented here.

## Error amplifier (`error_amp`)

- Pinout: `INP INN OUT VDD VSS` -- unchanged from the placeholder it
  replaced, so the swap was a symbol-name change in `ldo_core.sch` with no
  rewiring (`error_amp.sym` deliberately reuses the placeholder's pin
  coordinates).
- Topology: two-stage Miller-compensated OTA -- NMOS input pair with a PMOS
  mirror load, PMOS common-source second stage into an NMOS current sink,
  Miller cap plus nulling resistor, self-biased from `VDD`. ~9 uA nominal.
- Full rationale, the offset / PSRR / current budgets, and the measured PVT
  results live in **[`error_amp.md`](error_amp.md)**; the corner evidence is
  under `sim/amp-openloop/records/` and `sim/psrr-dc/records/`.
- **It has no enable pin.** The 5-port contract has none, so the amp draws
  its bias current whenever `VIN` is present: `Men` turns the *pass device*
  off but does not gate the amplifier. The measured disabled-state supply
  current of this cell is therefore ~9 uA, against a ratified
  "shutdown Iq < 3 uA" row -- an interface question for #11, which owns
  shutdown characterization. See `error_amp.md` "Handoffs".

## Reference voltage assumption

There is no bandgap block designed yet for this repo. `Vref1`, an ideal
**1.2 V** DC source, stands in for it inside `ldo_core`. The feedback divider
(`Rtop`=300k, `Rbot`=600k, plain behavioral `R`, from `VOUT` to `VSS` via the
`FB` midpoint) gives `FB = VOUT * Rbot/(Rtop+Rbot) = 2*VOUT/3`, so `VOUT`
settles at `1.5 * VREF` = 1.8 V, and the 900 kOhm total holds the divider's
standing current at 1.8 V / 900 kOhm = 2.0 uA -- the value DR-0003 budgets.

Issue #8 originally assumed 0.6 V here and said the divider **ratio** (not
the topology) is what changes if a different reference lands. Issue #9 made
that change, for two independent reasons documented in
[`error_amp.md`](error_amp.md): the offset gain-up `1/beta = Vout/Vref` is
1.5 at 1.2 V instead of 3.0 at 0.6 V (DR-0003 budgets against exactly the
1.5 figure), and a 0.6 V common mode cannot bias the NMOS input pair the
amplifier needs to survive the 2.10 V dropout test point.

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
python3 design/netlist.py --cell error_amp -v
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
  it instantiates (currently just `error_amp`). Include this to simulate the
  block.
- `error_amp.spice` -- that sub-circuit alone, which is what the amp-only
  benches `sim/amp-openloop/` and `sim/psrr-dc/` include.

```spice
.include design/netlist/ldo_core.spice
Xdut VIN VOUT EN VSS ERRAMP_OUT PASS_GATE ldo_core
```

> **Include exactly one of these files per deck.** `ldo_core.spice` already
> contains the sub-circuit definition; including it *and* `error_amp.spice`
> redefines the same `.subckt` twice.

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
- **Project cells are referenced by bare name** (`error_amp.sym`),
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
