# DR-0006: the Startup row's 3 ms settling window cannot coexist with its 1 V/ms ramp bound on an untrimmed on-chip ramp

- **Status**: ratified 2026-08-19 (issue #106) — **pending**: this status
  line states the diff this record's ratifying pull request proposes; per
  the 2026-08-19 ratification-via-PR policy (2AMLogic/2am#357), the
  operator's review and approval **of that pull request** is the
  ratification act itself — no separate ratification comment is expected.
  Until the pull request merges, this line is a proposal, not yet true of
  `main`, and `README.md`'s Startup row keeps its originally ratified 3 ms
  settling clause.
- **Date**: 2026-08-01
- **Decided by**: agent-builder (issue #38) — recommendation only;
  ratification is #106 (drafted as a pull request, not a comment), mirroring
  how DR-0001–DR-0003 were ratified by DR-0004's merge onto `main`. Issue
  #38's original evidence
  (`sim/soft-start/records/20260801-071013-6026a64.md`) recorded the row as
  **failing** on the settling clause; see "Evidence refresh" below for the
  current, fresher record.

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

### The two clauses jointly admit a 1.70 : 1 window

A rising output enters the ±2% band at its **lower** edge, 1.764 V — that is
what `m_t_startup` measures (`sim/soft-start/testbench/tb_soft_start.spice.in`:
`TRIG v(en) ... TARG v(vout) VAL=1.764 RISE=1`), and it is the arithmetic this
record uses throughout. A monotonic ramp that never exceeds 1 V/ms therefore
needs at least 1.764 ms to reach the band. The settling clause allows 3 ms. So
the ramp rate must lie in

    1.764 V / 3 ms = 0.588 V/ms   ≤   dV_out/dt   ≤   1.0 V/ms

— a **1.70 : 1** band, and every part in every corner of every lot has to land
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

2.93 does not fit inside 1.70. Neither does 2.04. Re-centring the nominal rate
trades one failure for the other and cannot satisfy both:

| nominal centring | fastest corner | slowest corner | verdict |
|---|---|---|---|
| fastest corner at 1.0 V/ms | 1.00 V/ms ✓ | 0.34 V/ms → 5.2 ms | settling fails |
| slowest corner at 0.588 V/ms | 1.72 V/ms | 0.588 V/ms ✓ | ramp bound fails |

The as-built design takes the first option, with margin: the fastest measured
corner is 0.867 V/ms (13% under the bound) and the slowest is 0.296 V/ms.

This is not specific to the implementation in `ldo_softstart`. Every on-chip
time constant available in this PDK is an `R · C`; there is no clock, no
crystal, and no trim provision anywhere in this design (DR-0005 already
declined to introduce one for the current limit, on the same kind of argument).
Any untrimmed soft start on gf180mcu has this spread.

### Evidence refresh (issue #106, 2026-08-19)

Issue #101 (closed, merged via PR #118) minted a fresher, full-factorial
settling record after this record was first drafted:
`sim/startup/records/20260816-100018-af4d1f9.md`, an 81-point run (9 process
corners — the original 5 plus the `res_ff`/`res_ss`/`bjt_ff`/`bjt_ss`
mismatch-model corners — × 3 temperatures × 3 supplies) against the current
`design/netlist/ldo_core.spice`, measuring both the full-load (~50 mA) and
minimum/no-load (~1 µA) branches at every corner. It supersedes the
163-point record originally cited here
(`sim/soft-start/records/20260801-071013-6026a64.md`) as the settling-clause
evidence of record: it is the record `sim/CHARACTERIZATION.md` now cites for
the Startup row, and it is fresh against the current DUT (the original
citation is not — it predates issue #48's Gear-integrator fix).

The worst measured point moves from **5.88 ms** (the original citation —
`ss` / −40 °C / 3.63 V / 0 mA load, drawn from a 20-point bracketing subset
at C_eff = 1 µF) to **5.82788 ms**
(`ss_-40c_3.63v`, full-load branch, of the fresh record; the no-load
branch's worst point at the same corner is 5.82711 ms) — a ~1% change,
consistent with the different testbench, corner count and C_eff (the fresh
record deliberately runs the full grid at C_eff = 4.7 µF, DR-0001's window's
upper bound and, per the fresh record's own claim text, "the softest/slowest
startup corner", rather than a bracketing subset at 1 µF) rather than a real
discrepancy. The new number is **lower**, not higher, so it does not weaken
this record's case — if anything the 6 ms proposal below now carries
marginally more headroom than originally computed (≈2.95% instead of
≈2.04%).

This refresh does **not** touch the ramp-rate evidence cited above
(0.296–0.867 V/ms, 163 points, 2.93 : 1 spread): the fresh testbench
(`sim/startup/testbench/tb_startup.spice`) measures settling time and
overshoot only, not ramp rate, so
`sim/soft-start/records/20260801-071013-6026a64.md` remains the evidence of
record for the ramp-bound clause.

## Decision

**Amend one clause of the Startup row.** Replace

> inside ±2% within 3 ms of enable

with

> inside ±2% within **6 ms** of enable

and add a note recording why: the ramp rate is an untrimmed on-chip `R · C`
whose measured PVT spread is 2.93 : 1, so a settling window narrower than
`1.764 ms × 2.93 ≈ 5.2 ms` cannot coexist with the ≤ 1 V/ms bound without a
trim provision. 6 ms is not that floor, though — it is 5.82788 ms, the
slowest **measured** point across the current full-factorial grid
(`sim/startup/records/20260816-100018-af4d1f9.md`, `ss_-40c_3.63v`,
full-load branch — see "Evidence refresh" above), plus ~3%
(6 ms / 5.82788 ms ≈ 1.0295). The measured slowest point is the binding
number here, and it is above the arithmetic floor because the as-built ramp
is not centred with its fastest corner exactly on 1 V/ms (it is at
0.867 V/ms).

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
  neither bound. The peak slope still has to be ≤ 1 V/ms and the distance to
  the band's lower edge is still 1.764 V, so the minimum time is unchanged;
  only the *average* rate gets worse.

## Consequences

- **The Startup row becomes verifiable.** With a 6 ms window, 81 of 81
  measured points pass the settling clause in the current record of evidence
  (`sim/startup/records/20260816-100018-af4d1f9.md`; the originally-cited
  163-point record also passed 163 of 163 on this clause), and the row's
  remaining failures are unambiguously circuit debt with a named cause.
- **The as-built ramp keeps 13% margin on the clause that matters.** The
  fastest measured corner is 0.867 V/ms against 1 V/ms. That margin is
  deliberate and is what the settling window is paying for; a future record
  that narrows the settling window must show where the margin came from.
- **Startup is now milliseconds, not microseconds.** Any consumer sequencing
  against this rail has to wait up to 6 ms after `EN`. That is a real,
  externally visible change from the pre-#38 behaviour (28–64 µs) and it is
  the price of the inrush bound; it should appear in whatever integration
  document this block eventually ships with.
- **Bad consequence, mechanical:** `sim/startup/testbench/tb.json`'s checks
  (`tsettle_full_ms`/`tsettle_min_ms` `max: 3.0`) are unchanged by this
  record — evidence records are append-only and this record does not
  re-run the harness — so the current record
  (`sim/startup/records/20260816-100018-af4d1f9.md`) and
  `sim/CHARACTERIZATION.md`'s generated Startup verdict keep reading
  **FAIL** even once this record is ratified, judged against the
  superseded 3 ms bound. The raw `tsettle_full_ms`/`tsettle_min_ms` columns
  in that record already show every point under 6 ms (see "Evidence
  refresh" above), but a fresh record with `tb.json`'s checks updated to
  `max: 6.0` is a follow-on step, not part of this record.
- **Bad consequence, stated plainly:** four clauses of this row remain failing
  after this record is ratified, and this record deliberately does not cover
  them. They need a follow-on issue against `ldo_softstart`'s two transients
  and, for the low-ESR corners, against issue #10's main-loop compensation.
  Anyone reading the Startup row as "passing" once this is ratified is reading
  it wrong; `sim/startup/records/` (settling, overshoot) and
  `sim/soft-start/records/` (ramp rate, inrush) are the authority on what
  passes.
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
