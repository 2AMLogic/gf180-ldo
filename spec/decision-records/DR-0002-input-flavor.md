# DR-0002: Input voltage flavor — 3.3 V now, 5 V deferred

- **Status**: proposed
- **Date**: 2026-07-30
- **Decided by**: Builder agent, issue #7 (recommendation only — ratification is #1)

## Context

The draft spec lists 3.3 V ±10 % as the input target with a "5 V flavor" as a
stretch, without saying whether 5 V compatibility constrains device selection
**now**. It cannot be left implicit: `spec/architecture-survey.md` §3.3 shows
the pass device swaps flavor cleanly (`pfet_03v3` → `pfet_05v0`/`pfet_06v0`)
but flags an open item — the error amp's output stage must swing the pass gate
all the way to Vin to turn the PMOS off, so a 5 V input with a 3.3 V amplifier
core needs a level shifter or a mid-voltage output stage. Survey §6 item 3
routes that call here, and warns it must not be decided implicitly by whoever
designs the amplifier in #9.

**#4 (device characterization) has not landed** — it is still in progress and
its `pfet_05v0`/`pfet_06v0` Rds(on)·W rows, which exist specifically to feed
this decision, are not yet available. This record is therefore stated with an
explicit, falsifiable revisit trigger (below) rather than presented as
data-final.

## Decision

**5 V compatibility does not constrain device selection now. The primary design
is 3.3 V ±10 % (2.97–3.63 V) on 3.3 V-flavor devices throughout — pass FET,
error amp, and reference. A 5 V input is a follow-on variant with its own
schematic, sizing, and verification pass.**

Two consequences of this are ratified alongside it, because they are the cheap
half of "5 V-ready" and cost nothing to hold:

1. **Survey §3.3/§3.4's open amplifier-headroom item is resolved for the
   primary design**: the error-amp output stage swings 0 V → Vin on 3.3 V
   devices, with no level shifter and no mid-voltage stage. #9 does not carry a
   5 V tolerance requirement and must not spend Iq or area on one.
2. **#4 keeps its mid-voltage PMOS Rds(on)·W rows in scope** (its scope note
   already plans them). They are one extra sweep of an existing deck, they cost
   nothing to collect now, and they are exactly the data that would trip the
   revisit trigger below. Deferring the flavor does **not** delete that row.

**Revisit trigger (the contingency on #4).** Reopen this decision — as a
superseding record, before #8 freezes the schematic — only if **both** hold:
(a) #4 shows a mid-voltage PMOS reaching the dropout target at ≤ ~1.3× the
width of the equivalent `pfet_03v3` device at the same gate drive, and (b) #9
finds a 5 V-tolerant gate-drive path costing ≤ ~2 µA and no new compensation
pole below the primary crossover. If either fails, the deferral stands without
further analysis.

## Alternatives considered

- **Design the primary for 5 V now (mid-voltage devices throughout)** —
  rejected. The penalty is paid on *every* headline spec row, not one: thicker
  gate oxide and higher |Vt| mean substantially more width for the same
  Rds(on) (the direct enemy of both the < 300 mV dropout row and the
  < 0.1 mm² area row); a mid-voltage or level-shifted amplifier output stage
  adds bias branches against a 30 µA Iq budget; and slower mid-voltage devices
  lower loop UGBW, which costs PSRR margin at the 1 kHz spec point and makes
  DR-0001's no-minimum-ESR (ceramic-stable) requirement harder to meet at the
  0.33 µF corner. Buying an unrequested capability by degrading four ratified
  rows is the wrong trade for a canary block whose product is verified margin.
- **Dual-flavor now (3.3 V core, mid-voltage pass FET and output stage only)** —
  rejected as the worst of both. It still pays the amplifier's level-shift Iq
  and the pass FET's area, still requires the full 5 V verification pass to
  claim anything, and produces a design that is optimal at neither input.
- **Delete the 5 V stretch from the spec entirely** — rejected. The topology
  carries to 5 V (survey §3.3); removing the row would discard a real, cheap
  catalog extension. Deferred ≠ abandoned, and the revisit trigger above keeps
  it honest.

## Consequences

- **What the later 5 V variant will cost, stated now so the deferral is an
  informed one:** re-size and re-lay-out the pass FET on the mid-voltage
  flavor (new W, new pad ring); add a 5 V-tolerant gate-drive path or move the
  amp output stage to mid-voltage devices; re-check ESD/rail selection; and
  re-run the entire #12 testbench suite plus #10's stability matrix at the new
  input range. What *survives* the variant: the PMOS common-source
  architecture, the compensation strategy (DR-0001), the reference, the
  feedback divider, the harness, and the testbench code itself. This is a
  variant, not a new design — which is precisely why deferring it is cheap.
- **#9 is unblocked on a question it would otherwise have had to guess.** Its
  output-stage swing requirement is 0 V → 3.63 V max, on 3.3 V devices.
- **#8 may freeze the schematic on `pfet_03v3`** once #1 ratifies and #4 lands
  sizing data, without holding a mid-voltage placeholder.
- **Bad consequence:** if a customer asks for 5 V before tape-out, the answer is
  a schedule slip for a second variant, not a device swap on the existing one.
  That is an accepted risk, bounded by the revisit trigger above and by keeping
  #4's mid-voltage rows in scope so the variant starts with data rather than
  from zero.
- **Explicit deferral (survey §6 item 6):** exact device parameters (|Vtp|,
  Vtn, Rds(on)·W, Cgg, resistor/cap menus) remain #4's, not this record's. This
  decision is deliberately structured so it does not depend on them, except
  through the stated revisit trigger.

## Cross-consequences (other #7 records)

- **DR-0001 (output cap/ESR)**: staying on 3.3 V-flavor devices keeps the pass
  FET's `Cgate` lower for a given `Rds(on)`, which pushes the gate pole `p2`
  higher and directly eases the ceramic-stable (no minimum ESR) requirement.
- **DR-0003 (programmability)**: a 3.3 V ±10 % input makes the upper end of the
  1.2–3.0 V programmable stretch unreachable — at Vin_min = 2.97 V a 3.0 V
  output cannot regulate at all. The programmable range above ~2.5 V is
  therefore gated on this record being superseded, which is a large part of why
  DR-0003 also defers.

## Proposed README replacement text

Replace the `Input` row of the draft spec table with, exactly:

```markdown
| Input | 3.3 V ±10% (2.97–3.63 V) | 5 V flavor — separate follow-on variant, not this design (see DR-0002) |
```
