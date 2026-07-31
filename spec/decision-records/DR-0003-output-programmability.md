# DR-0003: Output programmability — fixed 1.8 V, mask-option taps only

- **Status**: ratified 2026-07-31 (issue #1; adopted verbatim by DR-0004)
- **Date**: 2026-07-30
- **Decided by**: Builder agent, issue #7 (recommendation only — ratification is #1)

## Context

The draft spec's output row is "1.8 V ±2 % (fixed)" with "programmable
1.2–3.0 V" as a stretch. Whether the feedback network is designed for
programmability **from the start** cannot be deferred past schematic entry:
the divider ratio sets the feedback factor β, and β sets the loop gain, the
offset gain-up into #9's 36 mV accuracy budget, and the crossover frequency
that DR-0001's stability envelope is verified against. `spec/architecture-
survey.md` does not address programmability at all and routes it here in full
(§6 item 4). A late reversal would invalidate #9's budget, #10's matrix, and
#12's testbench count simultaneously.

## Decision

**The primary design is fixed 1.8 V ±2 %. The feedback network is a
fixed two-resistor divider optimized for accuracy and standing current at
1.8 V — no tap switches, no selection pins, no register, and no digital
interface of any kind in this block.**

One hedge is adopted because it is genuinely free: **the divider is laid out as
a series string of identical unit resistors with the tap made on a single metal
layer**, so a fixed-voltage derivative (e.g. 1.2 V or 2.5 V) is a one-mask
change. Unit-resistor construction with dummies is what the matching
requirement demands anyway, so this costs zero Iq, zero accuracy, and only the
routing area of choosing where a wire lands. That is the *entire* concession:
a mask option is a manufacturing choice, not a product feature — no datasheet
claim of user programmability follows from it.

The 1.2–3.0 V user-programmable stretch is deferred, and its upper half is
additionally gated on DR-0002: at Vin_min = 2.97 V a 3.0 V output cannot
regulate at all, and at Vin = 3.3 V nominal a 3.0 V output leaves exactly
300 mV — the entire dropout budget — so anything above roughly 2.5 V is
reachable only in the 5 V input variant that DR-0002 defers. Any future
programmability record should either truncate the range to ≤ 2.5 V or follow
the 5 V variant.

## Alternatives considered

- **Design the divider for 1.2–3.0 V programmability now, taps selected by
  on-chip switches** — rejected on four compounding costs:
  - **Reference**: regulating down to 1.2 V with a ~1.2 V bandgap requires
    β = 1 (no divider at all) and cannot go lower. Programmability to 1.2 V
    therefore forces Vref ≤ ~1.0 V — a sub-bandgap or divided reference. This
    decision would silently re-spec a block outside its own scope.
  - **Accuracy**: the amp's input-referred offset appears at the output
    multiplied by 1/β = Vout/Vref. At 1.8 V with a 1.2 V reference that factor
    is 1.5; at a 3.0 V tap it is 2.5. Holding ±2 % at the top tap would require
    roughly halving the offset allocation in #9's 36 mV budget — larger input
    devices (area) or trim/chopping (Iq and complexity) — or admitting a
    looser accuracy spec at the extremes, which is a worse product than a
    tight fixed one.
  - **Leakage**: the divider must be ~900 kΩ total to keep standing current
    near 2 µA against the 30 µA Iq budget. Tap switches put their off-state
    leakage directly onto a ~500 kΩ node at 125 °C: 1 nA is 0.5 mV, 10 nA is
    5 mV — up to a seventh of the whole 36 mV window spent on a feature nobody
    has requested. Switch on-resistance in series with the sense node adds a
    further matching/TC term.
  - **Verification**: β changes per tap, so loop gain and crossover change per
    tap. DR-0001's 3240-point stability matrix and every row of #12's
    testbench suite (dropout, load/line regulation, PSRR, transients, Iq,
    startup) multiply by the number of taps. Three taps triples the entire
    verification surface of the block.
- **Bond-option or pin-strap selection** — rejected. It avoids the register and
  most of the switch leakage, but it still requires the divider to be tapped
  and the loop to be verified at every strap setting (the verification
  multiplier above is unchanged), and it spends pads on a pad-constrained
  block.
- **Register / digital-interface selection (I²C, SPI, or a simple parallel
  register)** — rejected outright. It imports a digital interface, its own
  power-on-reset and default-state behaviour, and a shutdown/leakage story into
  an analog block with a 30 µA budget. Explicitly out of scope: **no digital
  interface is part of this design.**
- **Fixed 1.8 V with no mask-option structure at all** — rejected as leaving
  free value on the table. Unit-resistor layout is required for matching
  regardless; making the tap a metal choice costs nothing and turns a future
  fixed-voltage derivative into a mask spin instead of a redesign.

## Consequences

- **#9 gets a fixed budget to design against**: one divider ratio, offset
  gain-up 1/β = Vout/Vref fixed at design time, ~900 kΩ total divider
  resistance for ~2 µA standing current, and no switch leakage or switch
  matching term in the 36 mV accuracy budget. Divider mismatch (from #4's
  σ(ΔR/R)-vs-area rows) is budgeted once, not per tap.
- **#10's matrix stays at DR-0001's 3240 points** rather than multiplying per
  tap; **#12's testbench count stays at one suite per spec row.**
- **#8 may enter a fixed divider**, laid out as a unit-resistor string with the
  tap on a single metal layer and with dummy elements at the string ends.
- **The divider standing current is also the loop's only inherent preload**
  (~2 µA), which is the assumption DR-0001's 0 mA stability corner rests on.
  Changing the divider's total resistance later changes both the accuracy
  budget and that preload — it is not a free knob.
- **Bad consequence:** a customer wanting a user-selectable output gets a
  different part, and even a mask-option derivative is a new characterization
  and a new #12 run at the new voltage — the mask option saves design effort,
  not verification effort. The claim "1.2–3.0 V programmable" may not appear in
  any datasheet or catalog entry for this block.
- **Explicit deferral, not a silent drop:** the 1.2–3.0 V stretch remains in
  the spec table as a stretch, annotated with the two conditions that would
  make it reachable (a sub-1.2 V reference, and DR-0002's 5 V variant for the
  upper half). It is deferred with a stated path, not deleted.

## Cross-consequences (other #7 records)

- **DR-0001 (output cap/ESR)**: a fixed β means the stability envelope is
  verified against a single loop gain and crossover. Programmability would have
  required re-verifying the entire cap × ESR × load × PVT matrix at every tap.
- **DR-0002 (input flavor)**: the 3.3 V ±10 % input directly caps the usable
  output range (~2.5 V at best, given the dropout budget), so the upper half of
  the programmable stretch is gated on the deferred 5 V variant. These two
  deferrals reinforce each other and should be revisited together, if at all.

## Proposed README replacement text

Replace the `Output` row of the draft spec table with, exactly:

```markdown
| Output | 1.8 V ±2% (fixed; divider laid out as a unit-resistor string for metal-mask-option derivatives) | programmable 1.2–3.0 V — deferred; needs a sub-1.2 V reference, and > ~2.5 V needs the 5 V variant (see DR-0003) |
```
