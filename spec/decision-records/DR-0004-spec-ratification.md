# DR-0004: Ratification of the target specification, with amendments A1–A12

- **Status**: ratified
- **Date**: 2026-07-31
- **Decided by**: Robb Walters (operator), issue #1 — ratification comment
  [2026-07-31T22:14:45Z](https://github.com/2AMLogic/gf180-ldo/issues/1#issuecomment-5147916767);
  amended table drafted per issue #31

## Context

The `README.md` target-specification table has been a DRAFT since the repo was
scaffolded, with issue #1 as the ratification gate: design-phase work (harness,
survey, device characterization, schematic entry) was delegated against the
draft, but **layout could not lock to it** until the operator ratified. Three
decision records — DR-0001 (output capacitor and ESR window), DR-0002 (input
flavor), DR-0003 (output programmability) — were drafted against that draft
table and each ends with exact replacement text for one of its rows, but all
three stood at `Status: proposed`.

A spec-review opinion (klayout-tools #124, posted to #1 as comment
[5147818808](https://github.com/2AMLogic/gf180-ldo/issues/1#issuecomment-5147818808))
reviewed the draft table line by line against the committed device
characterization and returned **ratify-with-amendments**: every quantitative row
that existed was found achievable — dropout is measured with 2.5× margin at the
correct test point — but the table was missing canonical LDO rows (current
limit, load transient, line regulation, startup, enable/shutdown, thermal,
noise) and stated the rows it did have without conditions or binding corners.
Those findings were filed as amendments A1–A12 on issue #31. The operator
ratified conditional on those amendments and made #31 normative. This record is
that ratification.

## Decision

**The amended table under "Target specification" in `README.md` is the ratified
specification of this block as of 2026-07-31, and DR-0001, DR-0002 and DR-0003
are ratified with it.** Where the previous draft table and this record conflict,
this record governs. The layout-lock gate of the 2026-07-28 delegation on #1 is
satisfied at the merge of this record.

Disposition of each amendment:

| # | Amendment | How it landed |
|---|---|---|
| A1 | Adopt the three DR replacement rows verbatim; ratify DR-0001..0003 | Input, Output and Stability rows copied character-for-character from DR-0002 / DR-0003 / DR-0001. All three DR `Status:` lines now read ratified. |
| A2 | Output-accuracy conditions; reference inclusion; mismatch annotation | Table notes 2 and 3. ±2% = ±36 mV, 3σ, over line/load/temp, and **regulator-only — the reference's own error is excluded** (see "The two judgment calls" below). Divider mismatch annotated as a stated assumption, not a simulated result. |
| A3 | Current-limit row | New row: 65–80 mA over PVT, constant-current (brickwall), never engages for I_load ≤ 50 mA at any corner, binds ff/−40 °C, survives a continuous short at Vin_max. Rationale in note 5. |
| A4 | Load-transient row (all five quantities) | New row: 1 ↔ 50 mA, 1 µs edges, C_eff = 0.33 µF with ESR 0–500 mΩ, peak excursion ≤ 150 mV, recovery to ±1% in ≤ 20 µs. |
| A5 | Line-regulation row | New row: < 5 mV/V over 2.97–3.63 V, at 1 mA and at 50 mA. |
| A6 | Iq conditions | Row restated: < 30 µA at no load **and** at full load, binding ff/125 °C/3.63 V; the 10 µA stretch keeps DR-0001's subordination. |
| A7 | PSRR conditions | Row restated: > 50 dB @ 1 kHz and > 20 dB @ 100 kHz, at 1 mA (binding) and 50 mA, C_eff = 1 µF nominal; 1 MHz characterization moved to the stretch column. |
| A8 | Area accounting | Row restated verbatim as "< 0.1 mm² total core area, pass FET included, excluding pads and sealring". |
| A9 | Startup and enable/shutdown rows | Two new rows: controlled ≤ 1 V/ms ramp, monotonic, inside ±2% within 3 ms, overshoot ≤ +2%; shutdown Iq < 3 µA, disabled output = pass device off with no active discharge, Vin→Vout leakage ≤ 1 µA. |
| A10 | Thermal row or delegation | New row, both: 92 mW continuous at Vin_max/50 mA and ≤ 290 mW into a short at the 80 mA limit ceiling are specified here; θJA and sustained-short survivability are delegated to the package/integration spec. |
| A11 | Output-noise row or explicit waiver | **Waived explicitly**, with the rationale in note 7: no consumer requirement exists and no reference/amplifier design exists against which a µVrms number could be substantiated, so a number would be a claim without a testbench. |
| A12 | Corner bindings and minimum load | Bindings annotated per row and collected in note 1; DR-0001's minimum-load statement (0 mA external, ~2 µA divider preload) folded into the Load row. |

Two mechanical choices follow from A1 colliding with A12: because the three DR
rows are adopted **verbatim**, no binding-corner column was added to the table
(that would have appended a fourth cell to rows that must not change). A12's
"per-row annotation" option is used instead, with the conditions that do not fit
a table cell carried in the numbered notes beneath the table. Those notes are
part of the ratified spec, not commentary.

### The two judgment calls

The spec-review opinion identified these two as decisions the spec must make,
without making them:

1. **Output accuracy is regulator-only.** ±2% (36 mV) is the regulator's own
   error; the reference's error sits outside it. Taken because it is the reading
   the repo already works to — DR-0003 budgets amplifier offset gain-up against
   "#9's 36 mV budget" — and because it is the only reading that is verifiable
   with a testbench against a reference block that does not yet exist. The
   inclusive reading was rejected *for now* on the review's own evidence: an
   untrimmed CMOS bandgap is ±1–3% 3σ by itself, so an inclusive ±2% is
   near-zero-margin and would have to be bought with a trim provision — a
   design commitment (mask, test time, area) that nothing in the evidence base
   yet justifies. The cost is explicit: **this spec does not yet state a total
   output accuracy**, and note 2 forbids quoting the ±2% row as if it did.
2. **The current limit is a constant-current clamp, not foldback.** The
   amendment gives the spec the choice. Brickwall is taken because foldback's
   knee and floor cannot be specified without contradicting the startup row —
   a folded-back limit that engages during startup into a loaded output can
   latch the regulator low, which is exactly the failure #11's curation flags —
   and because the startup row is deliberately sized so the limit never engages
   during startup (≤ 1 V/ms into 4.7 µF is ≤ 5 mA of inrush; 50 mA + 5 mA is
   10 mA below the 65 mA minimum limit). The cost is the full ≤ 290 mW
   short-circuit dissipation in the Thermal row.

### Provisional values and their revisit triggers

The rows added by A3–A7 and A9 were set from measured device data plus the
architecture survey's loop budget, **before any loop-level simulation exists**.
Following DR-0002's pattern, each is stated with a falsifiable trigger rather
than presented as data-final. A triggered row is superseded by a new record; it
is never silently relaxed to make a result pass.

| Row | Basis | Revisit trigger |
|---|---|---|
| Load transient, 150 mV at C_eff = 0.33 µF | ΔV ≈ ΔI/(2π·f_c·C_eff) + ΔI·ESR ≈ 79 mV + 25 mV ≈ 104 mV at a 300 kHz crossover, i.e. ~40% margin to the bound | #10 shows the crossover needed for 150 mV cannot coexist with PM ≥ 45° at the 0.33 µF / 1 mΩ / light-load corner |
| PSRR > 20 dB @ 100 kHz | Above crossover, PSRR is carried by the output capacitor rather than loop gain; 20 dB is the low end of published practice at 1 µF | #9/#10 show > 20 dB at 100 kHz costs Iq or phase margin that the 30 µA and PM ≥ 45° rows cannot fund |
| Line reg < 5 mV/V | ≥ 60 dB DC loop gain gives ≈ 1 mV/V; 5 mV/V is 5× conservative | DC loop gain lands below ~54 dB at any corner |
| Current limit 65–80 mA | Must clear 50 mA at ff/−40 °C plus sense-path error (#11's own analysis); the W = 4 mm pass device carries 100 mA at 2.59 Ω worst corner, so the ceiling costs no re-sizing | #11's sense-path error budget cannot fit inside the 15 mA window between the two bounds |
| Startup ≤ 1 V/ms, ±2% in 3 ms | Inrush = C·dV/dt = 4.7 µF × 1 V/ms = 4.7 mA, keeping startup at full rated load 10 mA below the minimum limit | A soft-start slow enough to satisfy a consumer's inrush requirement cannot also settle within 3 ms |
| Shutdown Iq < 3 µA | Pass-FET off-state leakage measured at 0.417 µA (ff/125 °C/3.63 V) leaves ~2.6 µA for everything else | The enable network cannot hold the bias branches off within that budget across PVT |

## Alternatives considered

- **Ratify the draft table as written** — rejected. The stability row ("1 µF
  ±ESR range") names no numbers and is not ratifiable in a repo whose rule is
  that a spec line is a gate; and #11 was chartered to design a current limit
  against a threshold that did not exist anywhere in `spec/`.
- **Defer ratification until loop-level simulation exists** — rejected. That
  inverts the dependency: #10's stability matrix and #12's testbench suite are
  scoped *from* the spec table, and the layout-lock gate on #1 blocks the
  downstream epic. Ratifying with explicit revisit triggers costs a superseding
  record if a row proves wrong; deferring costs the whole schedule.
- **Add the missing rows qualitatively ("good load transient response")** —
  rejected. An unquantified row cannot be verified, which is the same defect
  A1 removes from the stability row. A provisional number with a stated trigger
  is falsifiable; an adjective is not.
- **Adopt the amendments but keep DR-0001..0003 `proposed`** — rejected as
  incoherent: the table's Input, Output and Stability rows *are* those records'
  text, so ratifying the table ratifies them.

## Consequences

- **Layout may lock to the spec.** The 2026-07-28 delegation's gate is
  satisfied; layout-stage issues unblock once this is on `main`.
- **#11 has numbers to design and verify against** — threshold window,
  behaviour, short-circuit condition, shutdown Iq, disabled output state — and
  no longer has to invent placeholders. Its "explicit foldback decision"
  acceptance item is now satisfied by this record rather than by #11.
- **#12's testbench suite grows.** Line regulation, load transient, startup,
  enable/shutdown and thermal each need a testbench that did not exist in the
  draft's row count. #10's stability matrix is unchanged (DR-0001 already
  enumerated it), but PSRR now needs a 100 kHz point at two load currents.
- **#9 gets a bounded accuracy budget** (36 mV, regulator-only, divider
  mismatch carried as an assumption per note 3) and an explicit instruction
  that a Monte Carlo run against this PDK is not evidence for the mismatch term.
- **Bad consequence, stated plainly:** six rows are provisional in the sense
  above. The most exposed is the load-transient bound at the 0.33 µF corner,
  which DR-0001 already names as the hardest point in the design and which now
  has a number attached to it. If it is missed, the correct response is a
  superseding record — tightening the component spec, or relaxing the bound with
  the measurement that justifies it — not testing at 1 µF and claiming the
  window.
- **Bad consequence:** no total output accuracy is specified. Until a reference
  block and its budget exist, this block cannot answer "what is Vout accuracy
  including the reference?" — and note 2 makes it a spec violation to imply that
  it can.
- **Issue #1 closes with this record**, and the draft-spec caveat leaves the
  README.

## Cross-consequences (other records)

- **DR-0001**: ratified verbatim. Its C_eff floor is now also the stated
  condition of the load-transient row, so the 0.33 µF corner binds two rows
  instead of one.
- **DR-0002**: ratified verbatim. Its revisit trigger condition (a) — a
  mid-voltage PMOS within ~1.3× the width of the 3.3 V device — is measurably
  failed at 2.8× (`sim/devchar/CONCLUSIONS.md` §1), so the 5 V deferral now
  stands on measurement rather than judgment.
- **DR-0003**: ratified verbatim. Its 36 mV accuracy budget is the same 36 mV
  that note 2 defines as regulator-only, which is the reading DR-0003 already
  assumed.
