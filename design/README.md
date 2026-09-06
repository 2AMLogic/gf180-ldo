# design/ -- xschem sources and netlist export

Schematic entry for the LDO core, in xschem, against the gf180mcu PDK. This
directory is the **source of truth for the block's electrical interface**:
`sim/` testbenches (and later `layout/` LVS) both consume the netlists
exported from here.

> **Status (issue #38): hierarchy, pinout, error amplifier, current limit,
> soft start and the full enable path are real.** Issue #8 built this cell
> with a behavioral placeholder amp and a one-transistor enable stub; #9
> replaced the placeholder with `error_amp`, a real two-stage OTA
> (`design/error_amp.md`); #11 added `ldo_ilimit` (constant-current limit)
> and turned the enable stub into a real low-current disabled state by
> gating every bias branch in the cell; #38 added `ldo_softstart`, the
> controlled output ramp the ratified Startup row asks for; #174 promoted
> `VREF` from an internal net to a seventh top-level port
> (`spec/decision-records/DR-0021`). What is still
> a stand-in: the **reference itself** -- no bandgap block exists, so every
> testbench drives `VREF` with an ideal 1.2 V source, and `ldo_core`
> consumes a reference rather than generating one -- and `Mpass`'s width
> (2 mm, #8's DC-sanity simplification of the ratified ~4 mm sizing). See
> "Scope split" below.

## Cells

```
ldo_core                          top level -- issue #8
├── error_amp                     two-stage Miller-compensated OTA -- issue #9
│                                 (replaced ldo_erramp_placeholder on the same
│                                 INP INN OUT VDD VSS pinout; the placeholder
│                                 cell is deleted, its contract is not.
│                                 Issue #11 APPENDED a sixth pin, EN)
├── ldo_ilimit                    constant-current limit + enable gating -- #11
└── ldo_softstart                 controlled output ramp at enable -- #38
```

## `ldo_core` pinout (established by issue #8, in netlist port order)

| Pin          | Dir   | Meaning |
| ------------ | ----- | ------- |
| `VIN`        | inout | Supply, 3.3 V nominal |
| `VOUT`       | inout | Regulated output, 1.8 V nominal. Also the current-sense return for `ldo_ilimit` (see below). |
| `EN`         | in    | Enable, active-high, CMOS-level (0 V / VIN). Gates the pass device, the amplifier's bias, the limit block's bias and the soft-start block's bias and ramp reset. |
| `VSS`        | inout | Ground |
| `ERRAMP_OUT` | out   | Loop-break point, output side (error-amp output) |
| `PASS_GATE`  | in    | Loop-break point, input side (pass-device gate) |
| `VREF`       | in    | Reference voltage, 1.2 V nominal. **Appended by issue #174** (`spec/decision-records/DR-0021`); it was an internal net driven by an in-cell ideal source before that. Shared by `error_amp`'s `INN`, `ldo_ilimit`'s bias generator and `ldo_softstart`'s ramp ceiling -- one net, one port. See "Reference voltage" below for the contract a driver of this pin must meet. |

`python3 design/netlist.py --check` asserts this exact port list (and that
the `.sym` pin order matches the `.sch` port order for every cell) so a
schematic edit that drifts from this interface fails loudly instead of
quietly shipping. Changing it means renegotiating with whichever of
#9/#10/#11/#12/#13 depend on the field being changed.

**Ports are appended, never inserted.** `VREF` is seventh, not tucked in
next to `VSS` where a reader might expect a bias pin, precisely so the first
six positions never move: a stale six-node instantiation then fails on node
count in ngspice instead of silently re-binding every net by one. Same
convention #11 used to append `EN` to `error_amp` and #55 used to append
`BG`.

### Loop-break point: two ports, not one

`ERRAMP_OUT` and `PASS_GATE` are **deliberately not connected to each other**
inside `ldo_core` -- normally (closed-loop operation) they carry the same
node, but that tie is made *outside* the subcircuit, at the testbench level,
not inside the schematic:

```spice
Vref VREF 0 DC 1.2                         * the reference this cell consumes
Xdut VIN VOUT EN 0 LOOP LOOP VREF ldo_core * ties ERRAMP_OUT and PASS_GATE
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
`VOUT`, `PASS_GATE`, `EN`, `VREF`, `VSS`) and adds no top-level port. (`VREF`
itself became a top-level port later, in #174 -- but by promoting the net
`Xilimit` was already on, not by adding one for `Xilimit`.)

**If `Mpass` is re-sized, `Msense` must be re-scaled with it**, or the limit
moves by the same factor. In layout `Msense` should be one unit cell of the
same array as `Mpass`, in the array's interior, so the ratio survives
gradients.

### Enable path and the disabled state

`EN` gates four things, all off the same net -- there is no second enable
path anywhere in the hierarchy:

| Gated by | Device(s) | Effect when `EN` = 0 |
| --- | --- | --- |
| `ldo_core` (#8) | `Men` | Pass-device gate clamped to `VIN`; pass device off |
| `error_amp` (#11) | `Mbias_h`, `Mnb_pd`, `Mn1_pu`, `Mnd_pu` | Amplifier bias branch opened, mirror node grounded, both internal high-impedance nodes parked at `VDD` |
| `ldo_ilimit` (#11) | `Mben`, `Men_t`, `Men_co`, `Mcoff` | Threshold bias opened, comparator tail opened and its output parked, clamp gate held at `VIN` |
| `ldo_softstart` (#38, rebuilt by #189) | `Mben_ss`, `Mdis_ss` (via `SD`), `Mpre_b_ss`, `Binj_ss`, and `HG` resting at 0 | Ramp bias branch opened, ramp capacitor shorted to `VSS`, `FB` pre-charge path opened, injection gated off, and the startup hold **on** (`Mhold_ss` holding `PASS_GATE` at `VIN`, `Mhold_bg_ss` holding `BG` there) so the pass gate is never ungoverned at the enable edge |

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

Four sibling issues share this schematic's territory; each owns a
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
- **#38 (soft start -- landed; rebuilt by #189)**: added `ldo_softstart`,
  which holds `VOUT` to a linear internal ramp until that ramp passes `VREF`.
  #38/#43 did it with a *second feedback loop* -- a comparator on
  (`FB`, ramp) driving a clamp on `PASS_GATE`; **#189 replaced that with
  current injection into `FB`**, so the ramp is now regulated by the main
  loop and there is no second loop to acquire. It still changes no existing
  net in `ldo_core` and no other cell. The one ratified clause it cannot meet
  -- the 3 ms settling window, at the slow end of the ramp's own resistor x
  capacitor corner spread -- is `spec/decision-records/DR-0006`; the evidence
  is `sim/soft-start/records/`.

## Error amplifier (`error_amp`)

- Pinout: `INP INN OUT VDD VSS EN BG`. The first five are unchanged from the
  placeholder this cell replaced (`error_amp.sym` reuses the placeholder's
  pin coordinates), so #9's swap was a symbol-name change with no rewiring;
  `EN` was **appended** by #11 and `BG` by #55, so the original five keep both
  their order and their coordinates in every case. Positional instantiations
  need the extra nodes -- ngspice errors on the node count rather than
  mis-wiring silently.
- **`BG` is an output, not an input** (issue #55). It is the class-AB gate
  buffer's own gate node -- the follower `Mbuf`'s gate, driven by stage 2 --
  exported so `ldo_softstart` and `ldo_ilimit` can *steer* the buffer while
  they clamp `PASS_GATE` instead of fighting it. Both clamps were sized
  against the ~4 uA class-A sink this cell had before #51; #51's follower
  sinks as hard as its Vsg allows and took the node away from them. A small
  PMOS from `VIN` to `BG` in each clamp cell, on the same gate as that cell's
  existing `PASS_GATE` clamp device, removes `Mbuf` from the contest whenever
  a clamp engages and is off whenever one does not. "Off" is a DC statement
  and only a DC statement: the added device contributes no DC path and no
  static current (settled `VOUT` is bit-identical at all 3240 loop-stability
  points, and DC loop gain moves at 12 of them by at most 0.10 dB), but its
  drain junction loads `BG` whether it conducts or not, and that **does**
  move the small-signal loop. Measured over the full matrix
  (`sim/loop-stability/records/20260802-085331-8a1a9e8.md`, comparing
  `20260801-191742-84f67b8` with `20260802-071154-166834d`): only 203/3240
  points are bit-identical in phase margin and crossover, the median
  crossover shift is 1.3 % (p95 1.8 %, p99 3.9 %) and the median phase-margin
  shift 1.9 deg (p95 6.1 deg), and 14 points shift crossover by more than
  10 % -- worst `ff_-40c_3.63v` at 1 mA / 4.7 uF / 0.2 ohm, 295 kHz ->
  1.20 MHz, which that record shows is the extraction switching between two
  0 dB crossings rather than a 4x change in bandwidth. The DR-0001 pass count
  over the same matrix falls 2689 -> 2632; the record enumerates all 57 moved
  points and what they are and are not evidence of. The clamp devices on `PASS_GATE`
  **stay**: `Mbufb`, the only pull-up at `OUT`, is off exactly when the loop
  demands maximum drive, so a clamp on `BG` *alone* has no authority at all
  (measured: the soft-start ramp is bypassed outright). See `error_amp.sch`'s
  "BG IS A PORT" note.
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

## Reference voltage

**`ldo_core` consumes a reference; it does not generate one** (issue #174,
[`spec/decision-records/DR-0021`](../spec/decision-records/DR-0021-vref-is-a-top-level-port.md)).
`VREF` is a top-level port. There is still no bandgap block designed for this
repo, and there is not going to be one *here* -- that block is the subject of
the sibling repository `2AMLogic/gf180-bandgap`, and DR-0021 records why
building a second one in this repo was rejected.

Until #174, `Vref1` -- an ideal **1.2 V** DC source -- stood in for the
reference *inside* the subcircuit. That source is deleted; the identical
ideal source now lives in each testbench deck and drives the `VREF` port.
The flattened circuit is the same one (an ideal vsource is an ideal vsource
wherever it is declared, and its return was already the `VSS` port), which is
why no ratified row moved -- DR-0021's "Evidence" section tabulates the
back-to-back re-run of every affected bench against `origin/main` on the same
host. What changed is that the idealization is **visible at the interface**
instead of buried a level down, and a real reference (a bandgap block, or the
Chipalooza Challenge #5 harness's bandgap-referenced bias-voltage slot) can
drive this cell without editing the schematic.

**What a driver of `VREF` must supply** (DR-0021 "Decision" item 3): 1.2 V
nominal, at an impedance low enough that this cell's own reference bias
current -- `ldo_ilimit`'s and `ldo_softstart`'s `VREF`/`R` branches; the
amplifier's `INN` draws only gate leakage -- does not move the node. That
current is measured at the port, per corner, by `sim/enable-shutdown/`
(`m_iref_en_ua` / `m_iref_off_ua`).

**What no record in `sim/` covers**: the reference's *own* error. Every
accuracy, PSRR and noise number in this repo is measured against an ideal
1.2 V source, so the reference's tolerance, tempco, noise and supply
rejection are excluded from all of them -- and they enter `VOUT` at
`1/beta` = **1.5x** when a real one is attached. That was already true before
#174; the port makes it stateable rather than hidden. DR-0021's "Follow-up
filed" section tracks the reference-referred campaign that would close it.

The feedback divider
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

- Pinout: `VIN VOUT PASS_GATE EN VREF VSS BG`. No new `ldo_core` port -- `BG`
  (appended by #55) is `error_amp`'s buffer-input node, an existing internal
  net of `ldo_core`.
- Topology: a 1/40 replica sense FET off `PASS_GATE` returning its current to
  `VOUT` through `Rsns`; a `VREF`/`Rbias`-derived reference current through
  `Rref`, also returned to `VOUT`, so both comparator inputs ride on the
  output and the comparison stays differential all the way down to a dead
  short; a PMOS comparator pair with a resistor tail (headroom, not
  elegance -- see the schematic notes) driving a PMOS clamp that sources
  current into `PASS_GATE`, plus (since #55) a second, small PMOS on the same
  gate that pulls `error_amp`'s `BG` up so the class-AB follower stops
  fighting the clamp while it is engaged.
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

## Soft start (`ldo_softstart`)

- Pinout: `VIN FB PASS_GATE EN VREF VSS BG`. No new `ldo_core` port, and —
  like `ldo_ilimit` — it only attaches to nets that already existed (`BG`,
  appended by #55, is `error_amp`'s buffer-input node). #189 changed what the
  cell *does* with `FB`: it drives that node now, where #38/#43 only sensed
  it. (`ldo_softstart.sym` still annotates `FB` as `dir=in`; that annotation
  is stale and affects only the `*.PININFO` comment line in the netlist.)
- Topology **since #189**: a linear voltage ramp (`Css` charged by a scaled
  copy of the same `VREF`/`Rbias` current `ldo_ilimit` uses, with a
  `VREF`-referenced ceiling device above it) converted into a **current
  injected into `FB`**, `I_inj = (V_REF − SSR)/(Rtop‖Rbot)`, which makes the
  *main* loop hold `VOUT = 1.5 × SSR`. Solving the `FB` node with the loop
  holding `FB` at `V_REF` gives `VOUT = 1.5·V_REF − I_inj·Rtop`, so that
  choice of `I_inj` collapses to `1.5 × SSR` and reaches exactly 1.8 V as
  `SSR` reaches `V_REF`. The injection is **source-only**, so it rectifies
  hard off once `SSR` passes `V_REF` (which it always does — `Mtop_ss`'s
  ceiling lands at 1.53–2.43 V over PVT) and leaves no DC error behind.
- **This replaced a second feedback loop, and that is the point.** #38/#43
  built the same behaviour as a PMOS comparator on (`FB`, `SSR`) driving a
  clamp that sourced into `PASS_GATE`. That loop closes through the output
  node, so it had to *acquire* through the pass device's dead zone; #43
  measured the acquisition at ~230 µs and 4.5 V/ms, damped it with a nulling
  resistor (`Rz_ss`) whose usable window was 400–600 squares wide, and still
  could not bring the 4.7 µF end of DR-0001's capacitor window inside the
  ratified 5 mA inrush bound (8.78–14.86 mA, 0/40 points). Injection deletes
  the acquisition rather than damping it, because the loop that regulates the
  ramp is the main one and it never opens. Measured effect at those same 40
  points: **2.10–4.97 mA, 40/40 inside the bound**
  (`sim/soft-start/records/20260906-202950-bfc4a0a.md`).
- **It is *not* "ramp the amplifier's reference"**, which is the obvious way
  to build a soft start and does not work on this amplifier: `error_amp`'s
  input pair is NMOS, so with `VOUT` near 0 both inputs are under the pair's
  common-mode floor and the loop is not closed over the bottom of the ramp (a
  prototype of that topology free-runs to an 11 mA charging edge in ~2 µs at
  tt/27 °C). Injection keeps **both** inputs at 1.2 V for the entire ramp,
  which is inside that range by a wide margin — the objection does not apply.
- **The enable edge needs three more elements, and they are measured, not
  assumed.** Injection alone leaves two transients that have nothing to do
  with the ramp: `Cff`'s 15 pF means 6 µA needs several microseconds to lift
  `FB` to `V_REF` while the amplifier is already awake (238 mA measured), and
  `error_amp` wakes with `N1`/`ND` parked at `VDD` so `Mbuf` slams
  `PASS_GATE` down before its first stage settles (240 mA measured, even with
  `FB` pinned). `Mpre_a_ss`/`Mpre_b_ss` pre-charge `FB` to `V_REF` through two
  series PMOS (a pulse, gated by `HG` and `ENB`, carrying **zero** current at
  its own operating point); `Mhold_ss`/`Mhold_bg_ss` hold `PASS_GATE` and `BG`
  at `VIN` — the same idiom, and the same #55 companion device, the #38 clamp
  used; and two matched RCs (`Rh_ss`/`Ch_ss`, `Rr_ss`/`Cr_ss`, τ ≈ 147 µs)
  sequence them so the hold releases (≈1.3 τ) **before** the ramp starts
  (≈1.5 τ). The ordering is a ratio of matched devices, so it survives the
  ±25 % resistor corner; τ itself is a measured trade between inrush margin
  and `t_startup`, tabulated in `design/ldo_softstart.sch`'s notes.
- **What it now leaves on the main loop's nodes is strictly less than before.**
  In the settled state the hold devices are in cutoff (adjudicated at every
  corner: `hg_end` is flagged at **0 of 163** points), the pre-charge switch is
  open and the injection is rectified off, so `FB` carries two PMOS drain
  junctions and `PASS_GATE` carries nothing from this cell. #38/#43 left
  `Cm_ss`'s 7.2 pF behind `Rz_ss`'s 1.55 MΩ on `PASS_GATE` permanently.
  Removing them is a change to a main-loop node and it is **not**
  characterised in AC here — `sim/loop-stability/` owns that evidence and a
  re-run there belongs to `#51`/`#176`.
- Measured, current state (`sim/soft-start/records/20260906-202950-bfc4a0a.md`,
  163 points, superseding `20260906-125202-f1096c9`):
  - **inrush ≤ 5 mA: 159/163**, from 119/163. Both 4.7 µF groups go 0/20 →
    **20/20** (8.78–14.86 → 2.10–4.97 mA); the nominal 1 µF matrix, the 0 mA
    group and 0.33 µF/500 mΩ stay 63/63 and 20/20 and improve 3–5×. The four
    that remain are the 0.33 µF/1 mΩ group's ringing corners (`#51`).
  - **overshoot ≤ +2 %:** every in-scope group holds its pass count and the
    ranges collapse to 1.7988–1.7996 V — `VOUT` approaches 1.8 V from below
    instead of ringing past it.
  - **peak `dVout/dt` ≤ 1 V/ms: 148/163**, from **0/163** — the first record
    in this bench's history where that predicate passes anywhere.
  - **settled output inside ±2 %: 163/163**, from 161/163.
  - **peak supply current ≤ 52 mA:** the 4.7 µF groups improve 2/20 →
    **10/20**; the residue is the arithmetic DR-0022 owns
    (`C_eff × dV/dt` riding on the 50 mA load), not a transient.
  What the block still does **not** meet:
  - the ratified 3 ms settling window, now at **131 of 163 points** against
    118 before — the ramp-release delay adds ~150 µs and the slower `Mdis_ss`
    release another ~4 % of ramp time, for +223 µs mean. All 13 newly-failing
    points sat at 2.83–2.90 ms and now sit at 3.01–3.04 ms. This is
    `spec/decision-records/DR-0006`'s clause, it is a regression against it,
    and the record reconciles it point by point rather than absorbing it.
  - the 0.33 µF/1 mΩ corners: 16 of those 20 points improve 4–6×, the pass
    count holds at 16/20, and the group's worst point degrades 311.9 →
    384.0 mA. That is `#51`'s unstable **main** loop, excluded from every
    statement above.
- **`Binj_ss` is idealized**, and it is the largest idealization in this cell:
  a behavioural source implementing the transconductor, the rectifier and the
  enable gate in one element. The intended device-level build (two
  `VIN`-referenced resistor-degenerated PMOS branches on `SSR` and `VREF`,
  differenced in a diode-connected PMOS that *is* the rectifier, mirrored into
  `FB`) is standard, and the one property it must preserve is that the
  transconductance is a **ratio to `Rtop`** rather than an absolute value —
  otherwise the `VOUT`/`SSR` gain moves with the resistor corner and the ramp
  no longer starts at 0. See the schematic's "WHAT IS IDEALIZED HERE"; the
  device-level build is tracked by issue #191.
- Added quiescent current: the bias branch only (~0.4 µA at tt/27 °C) in this
  build — the two delay RCs are capacitively terminated, the hold and
  pre-charge devices end in cutoff, and the injection rectifies to zero. The
  device-level transconductor will not be free; the `Iq` row has ~8 µA of
  headroom at its binding ff/125 °C/3.63 V corner.
- Added area: ~24 100 µm² (13 350 µm² of capacitor, 10 740 µm² of poly
  resistor) against ~11 800 µm² for the #38/#43 clamp it replaces, i.e. about
  24 % of the ratified 0.1 mm² core-area row. It is dominated by the two
  delay RCs, which sit at their minimum-area R/C split for the τ they
  implement.

## Pass device sizing (a deliberate simplification for this issue)

`Mpass` (`pfet_03v3`, `L`=0.28 um, `W`=2000 um / 2 mm, `nf`=40, `m`=1) is
**smaller** than the ~4 mm / 40-unit-cell sizing the ratified spec calls for
to clear 300 mV dropout @ 50 mA at the worst corner. 2 mm is issue #8's
guidance's stated acceptable size for the DC-sanity loop-closure test only,
at effectively no load beyond the ~1 mA the sanity testbench applies. The
full sizing (and the unit-cell partitioning a layout needs for matching) is
layout-phase work, out of scope here.

## Loop compensation: `Cff` (issue #42)

`Cff` (`cap_mim_2f0`, 87 um x 87 um, ~15.1 pF) sits in `ldo_core.sch` from
`VOUT` to `FB`, in parallel with `Rtop` -- a feedforward zero at
`1/(2*pi*Rtop*Cff)` with a companion pole at `1/(2*pi*(Rtop||Rbot)*Cff)`,
the lever `design/error_amp.md` section 6 named ahead of time. It is an
`ldo_core`-level addition: `error_amp.sch` and its netlist are untouched, so
none of #9's offset/PSRR/Iq records (measured with the amplifier driving its
own 6.14 pF gate load in isolation) need re-verification.

**Why here and not across `Rbot`.** A feedforward cap in parallel with the
resistor on the `VOUT` side (`Rtop`) gives a genuine left-half-plane zero
before its companion pole; the same cap in parallel with the ground-side
resistor (`Rbot`) gives a pure pole (added phase lag, not lead) -- confirmed
both by the transfer-function derivation and by a control run that measured
materially worse margins with it wired across `Rbot`. Do not move it.

**What it does and does not fix.** `sim/loop-stability/records/` (issue
#10's testbench, unmodified) shows `Cff` substantially improves the
matrix's moderate-to-heavy-load, higher-ESR corners, but does not bring the
very-light-load (0-0.1 mA) corners over the ratified 45 deg / 10 dB bar: at
that load the loop's two lowest poles (the amplifier's own Miller-set pole
and the output pole set by `Rtop+Rbot` = 900 kOhm against DR-0001's cap
window) both sit at sub-Hz frequencies regardless of any on-chip
compensation this issue tried, and a feedforward network's fixed
`Rtop/(Rtop||Rbot)` = 1.5x zero/pole spacing caps its phase lift at roughly
11.5 deg -- far short of what that corner needs. See the loop-stability
record for the full worst-corner table, the empirical rescaling experiments
that ruled out fixing this via `error_amp.sch`'s `XCc`/`XRz` alone, and the
follow-up issue this hands to the next compensation iteration.

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
Vref VREF 0 DC 1.2
Xdut VIN VOUT EN VSS ERRAMP_OUT PASS_GATE VREF ldo_core
```

`VREF` has no in-cell driver, so **a deck that does not drive it will not
regulate** -- that is the interface, not a bug (DR-0021). Every deck under
`sim/` declares its own ideal 1.2 V source for exactly this reason.

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
