# DR-0006: the Startup row's 3 ms settling window cannot coexist with its 1 V/ms ramp bound on an untrimmed on-chip ramp

- **Status**: proposed
- **Date**: 2026-08-01
- **Decided by**: agent-builder (issue #38) — **proposing**. The ratified spec
  is a human gate, and nothing in this record changes the table until it is
  ratified. Until then `README.md`'s Startup row stands as written and issue
  #38's evidence (`sim/soft-start/records/20260801-071013-6026a64.md`) records
  it as **failing** on the settling clause.

## Context

DR-0004 ratified the Startup row provisionally, with this revisit trigger
stated in its own table of provisional rows:

> | Startup ≤ 1 V/ms, ±2% in 3 ms | Inrush = C·dV/dt = 4.7 µF × 1 V/ms = 4.7 mA, keeping startup at full rated load 10 mA below the minimum limit | **A soft-start slow enough to satisfy a consumer's inrush requirement cannot also settle within 3 ms** |

Issue #38 built the soft start — `design/ldo_softstart.sch`, a clamp on
`PASS_GATE` that holds `VOUT` to a linear internal voltage ramp until that ramp
passes `VREF` — and measured the row over **163 points**: the full 63-point
PVT matrix at the nominal 1 µF / 100 mΩ output, plus DR-0001's capacitor window
and the 0 mA load case over a bracketing corner subset
(`sim/soft-start/records/20260801-071013-6026a64.md`).

The trigger has fired, and the measurement says the cause is arithmetic, not a
deficiency of this particular circuit.

### The two clauses jointly admit a 1.63 : 1 window

A monotonic ramp that never exceeds 1 V/ms needs at least 1.836 ms to reach the
+2% edge of a 1.8 V output. The settling clause allows 3 ms. So the ramp rate
must lie in

    1.836 V / 3 ms = 0.612 V/ms   ≤   dV_out/dt   ≤   1.0 V/ms

— a **1.63 : 1** band, and every part in every corner of every lot has to land
inside it. (A ramp shape other than a straight line only makes this worse: the
straight line is the shape with the largest average-to-peak slope ratio, which
is exactly the quantity being squeezed. An RC reference charged toward `VREF`,
the obvious alternative, has average-to-peak ≈ 0.25 and misses by 2.4×.)

### An on-chip ramp rate spans 2.9 : 1 on this PDK

The ramp is a current into a capacitor, and the current comes from a voltage
across a resistor, so the rate is `V_REF / (R · C)` — one absolute on-chip
resistance times one absolute on-chip capacitance. This PDK's own corner cards
give:

| element | typical | ss | ff | spread |
|---|---|---|---|---|
| `rsh_ppolyf_u_3k` | 3000 Ω/□ | 3750 | 2250 | ±25% |
| `mim_corner_2p0fF` | 1.0 | 1.1 | 0.9 | ±10% |

The `ff` and `ss` corners move the resistor **and** the capacitor in the same
direction (`ff` → `res_ff` + `mimcap_ff`, `ss` → `res_ss` + `mimcap_ss`), so
the `R·C` product spans 0.675 … 1.375 — a **2.04 : 1** rate spread from process
alone. The poly resistor's temperature coefficient over −40…125 °C widens it
further. **Measured across the 163 points: 0.296 … 0.867 V/ms, a 2.93 : 1
spread.**

2.93 does not fit inside 1.63. Neither does 2.04. Re-centring the nominal rate
trades one failure for the other and cannot satisfy both:

| nominal centring | fastest corner | slowest corner | verdict |
|---|---|---|---|
| fastest corner at 1.0 V/ms | 1.00 V/ms ✓ | 0.34 V/ms → 5.4 ms | settling fails |
| slowest corner at 0.612 V/ms | 1.79 V/ms | 0.612 V/ms ✓ | ramp bound fails |

The as-built design takes the first option, with margin: the fastest measured
corner is 0.867 V/ms (13% under the bound) and the slowest is 0.296 V/ms.

This is not specific to the implementation in `ldo_softstart`. Every on-chip
time constant available in this PDK is an `R · C`; there is no clock, no
crystal, and no trim provision anywhere in this design (DR-0005 already
declined to introduce one for the current limit, on the same kind of argument).
Any untrimmed soft start on gf180mcu has this spread.

## Decision (proposed)

**Amend one clause of the Startup row.** Replace

> inside ±2% within 3 ms of enable

with

> inside ±2% within **6 ms** of enable

and add a note recording why: the ramp rate is an untrimmed on-chip `R · C`
whose measured PVT spread is 2.93 : 1, so a settling window narrower than
`1.836 ms × 2.93 ≈ 5.4 ms` cannot coexist with the ≤ 1 V/ms bound without a
trim provision. 6 ms is 5.88 ms (the slowest measured point, `ss` / −40 °C /
3.63 V at 0 mA load) plus ~2%.

**Every other clause of the row is left exactly as ratified**, including the
clauses this design does not currently meet. Specifically, this record does
**not** propose relaxing:

- *controlled ramp ≤ 1 V/ms* — the ramp itself meets it at 163 of 163 points
  and the design should keep being held to it;
- *inrush ≤ 5 mA at C_eff = 4.7 µF* — the **ramp's** inrush at that capacitor
  is 4.7 µF × 0.836 V/ms = 3.9 mA and passes; the measured **peak** of
  12.7–22.3 mA is two short transients per startup (the soft-start loop
  acquiring at the bottom of the ramp, and `error_amp` coming out of
  saturation at the hand-over), which are a circuit defect to fix, not a
  specification to move;
- *startup at full rated load stays ≥ 10 mA below the current limit* — same
  two transients;
- *overshoot ≤ +2%* — met at every corner at 0.33 µF/500 mΩ and 4.7 µF/500 mΩ,
  and missed at 9 of 63 at 1 µF/100 mΩ, all inside the ff / res_ff family that
  the **pre-#38** evidence already shows ringing in regulation
  (`vout_pp_late` = 0.179 V at `res_ff_125c_2.97v`,
  `sim/enable-shutdown/records/20260801-013308-164ab42.md`). That is main-loop
  compensation, i.e. issue #10, not this row;
- *monotonic into any load 0–50 mA and any C_eff in the stability window* —
  see the same caveat.

The distinction this record insists on: **the settling clause is unmeetable and
therefore a specification error; the other four are met by the ramp and missed
by transients, and are therefore a circuit debt.** Moving the first is a
decision record. Moving the others would be relaxing the spec to make a result
pass, which CLAUDE.md forbids and which this record declines to do.

## Alternatives considered

- **Leave the row alone and record the design as failing.** Rejected as the
  *only* action, because it leaves a ratified line in place that no untrimmed
  implementation on this PDK can satisfy — the same defect DR-0005 removed
  from the current-limit row. It is, however, exactly what happens to the row
  until this record is ratified.
- **Relax the ramp bound instead, keeping 3 ms.** Rejected. The ramp bound is
  the consumer-facing clause: it is what bounds inrush into the customer's
  supply, and DR-0004 derives the 5 mA inrush figure from it. The settling
  window has no consumer stated behind it in this repo. If a consumer later
  states one, that is a new record, and it will have to be paid for with a
  trim provision.
- **Add a trim provision (fuse or metal option) on `R_ss_bias`.** Rejected for
  now, on DR-0004's own reasoning for rejecting a trimmed reference: a trim is
  a design commitment — mask, test time, area — and nothing in the evidence
  base yet justifies buying a 3 ms settling window with it. Noted here as the
  one thing that *would* restore the ratified number, so a future consumer
  requirement has a known price.
- **A non-RC time reference (ring oscillator + counter).** Rejected: a ring
  oscillator's period is a FET-corner quantity with a *worse* spread than the
  `R · C`, plus it adds a digital block, switching noise on a regulator's own
  supply, and area, to buy nothing.
- **Two-slope ramp (fast, then slow near the target).** Rejected: it improves
  neither bound. The peak slope still has to be ≤ 1 V/ms and the total distance
  is still 1.836 V, so the minimum time is unchanged; only the *average* rate
  gets worse.

## Consequences

- **The Startup row becomes verifiable.** With a 6 ms window, 163 of 163
  measured points pass the settling clause, and the row's remaining failures
  are unambiguously circuit debt with a named cause.
- **The as-built ramp keeps 13% margin on the clause that matters.** The
  fastest measured corner is 0.867 V/ms against 1 V/ms. That margin is
  deliberate and is what the settling window is paying for; a future record
  that narrows the settling window must show where the margin came from.
- **Startup is now milliseconds, not microseconds.** Any consumer sequencing
  against this rail has to wait up to 6 ms after `EN`. That is a real,
  externally visible change from the pre-#38 behaviour (28–64 µs) and it is
  the price of the inrush bound; it should appear in whatever integration
  document this block eventually ships with.
- **Bad consequence, stated plainly:** four clauses of this row remain failing
  after this record is ratified, and this record deliberately does not cover
  them. They need a follow-on issue against `ldo_softstart`'s two transients
  and, for the low-ESR corners, against issue #10's main-loop compensation.
  Anyone reading the Startup row as "passing" once this is ratified is reading
  it wrong; `sim/soft-start/records/` is the authority on what passes.
- **DR-0004's revisit trigger for this row is discharged**, and the row leaves
  DR-0004's provisional list.

## Cross-consequences (other records)

- **DR-0004**: this record supersedes one clause of the Startup row it
  ratified, using the revisit trigger DR-0004 itself registered. The rest of
  the row, and the rest of the table, are untouched.
- **DR-0001**: unaffected as a decision, but its capacitor window is now the
  axis on which this row's remaining failures separate — every 500 mΩ ESR
  group passes overshoot at every corner and every 1 mΩ group does not, which
  is evidence for DR-0001's own ESR discussion and for issue #10.
- **DR-0005**: unaffected. The two records share a shape — an untrimmed
  on-chip resistor's absolute spread against a ratified window that is
  narrower than it — and it is worth noting that this is now the **second**
  ratified row on this block that an untrimmed `ppolyf_u` absolute value has
  broken.
