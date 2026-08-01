# design/ -- xschem sources and netlist export

Schematic entry for the LDO core, in xschem, against the gf180mcu PDK. This
directory is the **source of truth for the block's electrical interface**:
`sim/` testbenches (and later `layout/` LVS) both consume the netlists
exported from here.

> **Status (issue #11): hierarchy, pinout, error amplifier, current limit
> and the full enable path are real.** Issue #8 built this cell with a
> behavioral placeholder amp and a one-transistor enable stub; #9 replaced
> the placeholder with `error_amp`, a real two-stage OTA
> (`design/error_amp.md`); #11 added `ldo_ilimit` (constant-current limit)
> and turned the enable stub into a real low-current disabled state by
> gating every bias branch in the cell. What is still a stand-in: `Vref1`
> (an ideal source -- no bandgap block exists) and `Mpass`'s width (2 mm,
> #8's DC-sanity simplification of the ratified ~4 mm sizing). See "Scope
> split" below.

## Cells

```
ldo_core                          top level -- issue #8
├── error_amp                     two-stage Miller-compensated OTA -- issue #9
│                                 (replaced ldo_erramp_placeholder on the same
│                                 INP INN OUT VDD VSS pinout; the placeholder
│                                 cell is deleted, its contract is not.
│                                 Issue #11 APPENDED a sixth pin, EN)
└── ldo_ilimit                    constant-current limit + enable gating -- #11
```

## `ldo_core` pinout (established by issue #8, in netlist port order)

| Pin          | Dir   | Meaning |
| ------------ | ----- | ------- |
| `VIN`        | inout | Supply, 3.3 V nominal |
| `VOUT`       | inout | Regulated output, 1.8 V nominal. Also the current-sense return for `ldo_ilimit` (see below). |
| `EN`         | in    | Enable, active-high, CMOS-level (0 V / VIN). Gates the pass device, the amplifier's bias and the limit block's bias. |
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

### Current sensing: a replica, not a series element

Issue #8 left the `XMpass` drain-to-`VOUT` wire as the place a series sense
element would be cut in. **Issue #11 did not use it**, and the reason is the
Iq budget: any series element in the pass path either burns the sensed
current or drops voltage the dropout row cannot afford. Instead
`ldo_ilimit`'s `Msense` is a 1/40 replica of `Mpass` (same `L`, same
per-finger width, same source and same gate), and its current is returned to
`VOUT` through the sense resistor. So the sensed current is *delivered to the
load* rather than burned, the pass path is untouched, and `ldo_core`'s
topology is unchanged -- `Xilimit` only attaches to existing nets (`VIN`,
`VOUT`, `PASS_GATE`, `EN`, `VREF`, `VSS`) and adds no top-level port.

**If `Mpass` is re-sized, `Msense` must be re-scaled with it**, or the limit
moves by the same factor. In layout `Msense` should be one unit cell of the
same array as `Mpass`, in the array's interior, so the ratio survives
gradients.

### Enable path and the disabled state

`EN` gates three things, all off the same net -- there is no second enable
path anywhere in the hierarchy:

| Gated by | Device(s) | Effect when `EN` = 0 |
| --- | --- | --- |
| `ldo_core` (#8) | `Men` | Pass-device gate clamped to `VIN`; pass device off |
| `error_amp` (#11) | `Mbias_h`, `Mnb_pd`, `Mn1_pu`, `Mnd_pu` | Amplifier bias branch opened, mirror node grounded, both internal high-impedance nodes parked at `VDD` |
| `ldo_ilimit` (#11) | `Mben`, `Men_t`, `Men_co`, `Mcoff` | Threshold bias opened, comparator tail opened and its output parked, clamp gate held at `VIN` |

The disabled output state is **pass device off with no internal active
discharge** -- nothing pulls `VOUT` down, which is what the ratified
Enable/shutdown row asks for. With no external load the output therefore
floats up on leakage until the 900 kOhm feedback divider sinks it: a real,
measured ~0.18 V at the hottest/leakiest corner rather than 0 V.

Measured (`sim/enable-shutdown/records/`, 63 PVT points): disabled-state
supply current **0.20 uA** and `VIN`->`VOUT` leakage **0.21 uA** at the
binding ff/125 C/3.63 V corner, against ratified budgets of 3 uA and 1 uA.
Before #11 gated the amplifier the same disabled state drew **9.24 uA**
(`sim/op-point-sanity/records/20260801-002928-712cb87.md`).

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
- **#11 (current limit + enable -- landed)**: added `ldo_ilimit`, a
  constant-current (brickwall) limit, and made the enable path real by
  gating every bias branch in the hierarchy -- which required appending an
  `EN` pin to `error_amp`, the interface decision #9 explicitly deferred to
  here. Current-limit centering, the hard-limit-vs-foldback argument and
  what is idealized live in `design/ldo_ilimit.sch`'s own notes; the corner
  evidence is under `sim/current-limit/records/` and
  `sim/enable-shutdown/records/`, and the one ratified row it cannot meet
  (the +/-10 % current-limit window) is `spec/decision-records/DR-0005`.

## Error amplifier (`error_amp`)

- Pinout: `INP INN OUT VDD VSS EN`. The first five are unchanged from the
  placeholder this cell replaced (`error_amp.sym` reuses the placeholder's
  pin coordinates), so #9's swap was a symbol-name change with no rewiring;
  `EN` was **appended** by #11 so the first five keep both their order and
  their coordinates. Positional instantiations need the extra node --
  ngspice errors on the node count rather than mis-wiring silently.
- Topology: two-stage Miller-compensated OTA -- NMOS input pair with a PMOS
  mirror load, PMOS common-source second stage into an NMOS current sink,
  Miller cap plus nulling resistor, self-biased from `VDD`. ~9 uA nominal.
- Full rationale, the offset / PSRR / current budgets, and the measured PVT
  results live in **[`error_amp.md`](error_amp.md)**; the corner evidence is
  under `sim/amp-openloop/records/` and `sim/psrr-dc/records/`.
- **`EN` gates the bias in-cell** (issue #11). A supply header on this cell
  would *not* work: with its `VDD` switched off while `Men` holds the
  pass-gate -- and therefore this cell's `OUT` -- at `VIN`, `M2P`'s
  drain-body diode forward-biases and powers the amplifier back up through
  the diode. Gating the bias branch with the rails intact leaves every body
  at its own rail and only leakage behind. The enabled-state cost is
  `Mbias_h`'s < 5 mV of `Ron` drop on a ~2.5 V bias branch: re-running #9's
  own 81-point open-loop and PSRR benches after the change moves every
  measured quantity by < 0.2 % (`sim/amp-openloop/records/`,
  `sim/psrr-dc/records/`).

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

## Current limit (`ldo_ilimit`)

- Pinout: `VIN VOUT PASS_GATE EN VREF VSS`. No new `ldo_core` port.
- Topology: a 1/40 replica sense FET off `PASS_GATE` returning its current to
  `VOUT` through `Rsns`; a `VREF`/`Rbias`-derived reference current through
  `Rref`, also returned to `VOUT`, so both comparator inputs ride on the
  output and the comparison stays differential all the way down to a dead
  short; a PMOS comparator pair with a resistor tail (headroom, not
  elegance -- see the schematic notes) driving a PMOS clamp that sources
  current into `PASS_GATE`.
- **Constant-current (brickwall), not foldback.** Ratified: note 5 of the
  spec table makes foldback a superseding decision record rather than an
  implementation choice, because a folded-back limit can prevent startup
  into an already-loaded output. Measured flatness from `Vout` = 1.764 V
  down to a dead short is within 2.3 % at every corner.
- **Threshold: 74.5 mA** at tt/27 C/3.30 V, 62.0..93.8 mA over the 63-point
  PVT matrix. It never engages inside the rated 0..50 mA load at any corner
  (worst-case onset 62.0 mA, +24 % over the rated load). The +/-20 % spread
  is the gf180mcu poly-resistor sheet corner and nothing else -- the
  FET-skew corners that hold resistors typical move it by under +/-1.2 % --
  so it cannot be squeezed into the ratified +/-10 % window without trim.
  See `spec/decision-records/DR-0005` and `sim/current-limit/records/`.

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
