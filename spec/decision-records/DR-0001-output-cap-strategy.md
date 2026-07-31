# DR-0001: Output capacitor and ESR window

- **Status**: proposed
- **Date**: 2026-07-30
- **Decided by**: Builder agent, issue #7 (recommendation only — ratification is #1)

## Context

The draft spec's stability row reads "stable 0–50 mA with 1 µF ±ESR range",
which names neither a capacitance tolerance nor an ESR window, and lists
"capless variant" as a stretch without saying whether the primary design must
also be capless-stable. `spec/architecture-survey.md` §4.1 shows why this is
load-bearing rather than cosmetic: with output-pole-dominant compensation the
ESR zero `z_esr = 1/(2π·Resr·Cout)` sits in the loop, so **both** a minimum and
a maximum ESR are part of the stability contract, and §6 explicitly defers the
window to this record. #10 cannot enumerate its load × cap × ESR × PVT matrix
until the numbers below exist. Issue #4 (device characterization) has not
landed; nothing in this record depends on it — the external output capacitor is
a board component, not a PDK device.

## Decision

**The regulator is specified and verified against an effective output
capacitance of 0.33 µF to 4.7 µF with an ESR of 0 to 500 mΩ, and must be stable
with no minimum ESR (ceramic-stable). Capless operation is a separate design
fork, not a mode of the primary design.**

Concretely:

| Item | Ratified value |
|---|---|
| Recommended component | 1 µF ±20%, X5R or X7R, ≥ 6.3 V rating |
| **Verified effective capacitance** `C_eff` | **0.33 µF ≤ C_eff ≤ 4.7 µF** at the output pin, inclusive of initial tolerance, DC-bias derating at 1.8 V, temperature coefficient over −40…125 °C, and aging |
| **Verified ESR window** | **0 ≤ ESR ≤ 500 mΩ** over the same range (no minimum ESR; the loop must not depend on the ESR zero) |
| Load range | 0–50 mA, where 0 mA means no external load (the feedback divider's ~2 µA is the only inherent preload; no external preload resistor may be assumed) |
| Stability criterion | worst-corner phase margin ≥ 45° **and** gain margin ≥ 10 dB across the full matrix |
| Capless | out of scope for the primary design; a forked variant with its own compensation architecture (survey §4.2) |

The 0.33 µF floor is what "1 µF" means after derating, not an extra safety
factor invented here: 1 µF × 0.80 (tolerance) × 0.70 (DC bias, small-case
6.3 V part at 1.8 V) × 0.85 (X5R temp) × 0.95 (aging) ≈ 0.45 µF, and 0.33 µF is
the next standard value below that — so a designer may use a cheap 0402 part
without the loop leaving its verified envelope. The 4.7 µF ceiling covers one
paralleled bulk capacitor; above it the design is unverified, not known-bad.

The 500 mΩ ESR ceiling is set by the load-transient budget as much as by phase:
a 50 mA load step develops 50 mA × 0.5 Ω = 25 mV of instantaneous ESR step,
1.4 % of 1.8 V, which fits inside the ±2 % output window with room for the
loop's own recovery. It excludes tantalum and electrolytic parts (typically
1–3 Ω at this value) — deliberately, and this must be stated in any datasheet.

## Alternatives considered

- **Require a minimum ESR (e.g. 100 mΩ–1 Ω), classic ESR-zero compensation** —
  rejected. It is the cheapest architecture (the zero does the phase work for
  free, per Rincon-Mora & Allen), but modern 1 µF MLCCs have 5–20 mΩ of ESR, so
  the window would exclude every ceramic a user would actually fit and force a
  discrete series resistor. That is a usability defect and a support burden, and
  it forfeits the transient performance the low ESR buys.
- **Narrow capacitance window (0.68–1.5 µF)** — rejected. It matches "1 µF ±20 %"
  literally but is unenforceable on a real board: DC-bias and temperature
  derating alone push a nominally compliant part below 0.68 µF, so the part
  would ship out of its own verified envelope. Deriving the envelope from
  derated effective capacitance (above) is the same decision made honestly.
- **Make the primary design capless-stable as well** — rejected, consistent
  with survey §4.2. Capless removes the dominant-pole mechanism entirely and
  requires internal Miller/cap-multiplier compensation plus (typically) an
  FVF-class buffer stage — extra area against the 0.1 mm² budget and extra Iq
  against the 30 µA budget, for a capability no consumer of this block has
  asked for. Fork it if and when there is a customer.
- **Wider ceiling (10 µF or "no maximum")** — rejected for now. Each additional
  decade multiplies #10's matrix and interacts with startup inrush and
  current-limit behaviour that no testbench yet covers. 4.7 µF is one bulk cap;
  extending later is a superseding record, not a redesign.

## Consequences

- **#10 can enumerate its matrix from this record alone.** Sweep points:
  `I_load ∈ {0, 0.1, 1, 10, 25, 50} mA` (add 100 mA only when the stretch is
  pursued) × `C_eff ∈ {0.33, 1.0, 4.7} µF` × `ESR ∈ {0.001, 0.05, 0.2, 0.5} Ω`
  × `T ∈ {−40, 27, 125} °C` × `Vin ∈ {2.97, 3.3, 3.63} V` × process
  `{tt, ff, ss, fs, sf}` = 3240 loop-gain points. The 1 mΩ ESR point is the
  numerical stand-in for "ESR → 0" — it is a required point, not a courtesy one,
  because it is where the ESR zero provides no help at all. Recommended
  execution order: full cap × ESR × load sweep at tt/27 °C/3.3 V first to find
  the worst (cap, ESR, load) triple, then full PVT on that triple plus the four
  cap/ESR extremes; the full 3240-point grid is the completeness backstop, not
  the first run.
- **The stability burden moves inside the chip.** With no minimum ESR, phase
  margin must come from pole placement, not from the external zero: the
  pass-gate pole `p2 = 1/(2π·Rgate·Cgate)` must sit well above crossover at the
  0.33 µF corner. In practice this argues for the survey's §5 candidate 3
  (two-stage Miller) or candidate 2 with a low-impedance gate driver, and it
  makes #4's `Cgg` row a gating input for #9 rather than a nice-to-have.
- **Explicit deferral — the 10 µA Iq stretch (survey §6 item 5).** A ceramic-
  stable loop spends current on gate drive, and the 10 µA stretch and this
  decision are in tension. Resolved as: the 30 µA target governs; the 10 µA
  stretch is **not** to be pursued at the cost of the ratified ESR window. If
  #9 finds 10 µA reachable only by reintroducing a minimum ESR, that is a
  superseding record, not an implementation choice.
- **The capless fork gets cheaper, not free.** Requiring a high `p2` is a
  prerequisite the capless architecture also needs, so the primary design's
  compensation work is partially reusable — but the dominant-pole relocation
  and buffer stage remain a distinct architecture.
- **Bad consequence, stated plainly:** the 0.33 µF corner is the hardest point
  in the whole design and may cost Iq, area, or PSRR margin at 1 kHz. If it
  proves unmeetable, the correct response is a superseding record that tightens
  the component spec (e.g. "≥ 0603, ≥ 16 V rating" to lift the derated floor to
  0.68 µF) — not silently testing at 1 µF and claiming the window.
- Out-of-envelope operation (no cap, > 4.7 µF, ESR > 500 mΩ, tantalum) is
  **unspecified**: no claim may be made for it, per the repo's no-claim-without-
  a-testbench rule.

## Cross-consequences (other #7 records)

- **DR-0002 (input flavor)**: deferring the 5 V flavor keeps the pass device on
  `pfet_03v3`, whose lower `Cgate` per unit `Rds(on)` makes the high-`p2`
  requirement above materially easier. A 5 V-now decision would have made this
  record's no-minimum-ESR posture harder to hold.
- **DR-0003 (programmability)**: a fixed 1.8 V output keeps the feedback factor
  β constant, so this record's window is verified against one loop gain. Every
  additional output tap would multiply the 3240-point matrix above.

## Proposed README replacement text

Replace the `Stability` row of the draft spec table with, exactly:

```markdown
| Stability | stable 0–50 mA with C_out 0.33–4.7 µF effective (1 µF nominal X5R/X7R), ESR 0–500 mΩ; PM ≥ 45°, GM ≥ 10 dB worst corner | capless variant (separate design fork) |
```
