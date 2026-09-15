# DR-0023: cascode the soft-start injection mirror (`Mgmo_ss` against `Mgmr_ss`) rather than restore an output-side clamp

- **Status**: proposed
- **Date**: 2026-09-15
- **Decided by**: agent-builder (issue #191) — **proposing**; the ratified
  spec is a human gate, and nothing in this record changes `design/
  ldo_softstart.sch` until the recommendation below is ratified and a
  follow-on PR implements it (issue #191's remaining acceptance criteria).

## Context

Issue #189 rebuilt `design/ldo_softstart.sch`'s soft-start hand-over around
current injection into `FB`, closing DR-0001's ratified 4.7 µF inrush window
against an **ideal** behavioural source, `Binj_ss`. Issue #191 opened to
replace that source with real devices. The first attempt (PR #195) built the
device-level transconductor `#189` specified — two `VIN`-referenced,
resistor-degenerated PMOS branches (`Mgma_ss`/`Mgmb_ss`), differenced in a
diode-connected PMOS (`Mgmr_ss`) that mirrors 1:1 into an output device
(`Mgmo_ss`) sourcing into `FB` — and regressed the ratified Startup row: the
full 163-point sweep failed inrush at 81/163 points and settled accuracy at
28/163, confirmed by direct A/B against `main`'s ideal `Binj_ss` at an
identical corner.

Issue #196 / PR #197 (merged 2026-09-10) ruled out the leading hypothesis for
that regression — a missing `Cm_ss`/`Rz_ss`-class compensation network on the
injection path — with a negative result over an 11450-point loop-gain grid
plus a 12222-point DC hand-over transfer
(`sim/soft-start-loop-gain/records/20260910-015601-2387ece.md`). That same
record measured the actual root cause and `design/
softstart_injection_compensation.md` (issue #196) derives two candidate
fixes from it without choosing between them, explicitly deferring the choice
as "a topology decision, not a sizing one." The operator's 2026-09-14
comment on #191 routes that choice through this repo's ratification-via-PR
two-key mechanism (2AMLogic/2am#357, 2AMLogic/2am#372) and asks the Builder
to draft it as a decision record. This record is that record; it changes no
schematic.

### The measured root cause

`Mgmr_ss` is diode-connected, so its |V_ds| equals its |V_gs|. `Mgmo_ss`'s
drain is `FB`, sitting at 1.2 V, so its |V_ds| is `VIN − 1.2 V`. The mirror
therefore copies across a **drain-voltage mismatch that grows with `VIN`**,
in weak inversion — the region where drain-bias sensitivity is strongest,
since the mirror's own |V_gs| at the intended cut-off point is only
0.82–0.96 V (at or barely above a `pfet_03v3` threshold). Measured at
`V(SSR) = VREF` (the intended hand-over point, where `I_inj` should be
exactly zero), all four values read from
`sim/soft-start-loop-gain/records/20260910-015601-2387ece-handover.csv`:

| corner | `VIN` | \|V_ds\| `Mgmr_ss` | \|V_ds\| `Mgmo_ss` | mirror ΔV_ds | `I_inj` at `V(SSR)=VREF` |
|---|---|---|---|---|---|
| `tt_27c_2.97v` | 2.97 V | 0.824 V | 1.770 V | **0.947 V** | +0.451 µA |
| `tt_27c_3.30v` | 3.30 V | 0.901 V | 2.100 V | **1.199 V** | +1.347 µA |
| `tt_27c_3.63v` | 3.63 V | 0.962 V | 2.431 V | **1.469 V** | +2.538 µA |
| `ff_125c_3.63v` | 3.63 V | 0.820 V | 2.431 V | **1.611 V** | +4.125 µA |

Full-PVT consequence (63 corners, `sim/soft-start-loop-gain/records/
20260910-015601-2387ece.md` §2 / `design/softstart_injection_compensation.md`
§2):

| quantity | intent (`Binj_ss`) | device chain, measured |
|---|---|---|
| `I_inj` at `V(SSR) = VREF` (should be 0) | 0 exactly | **+0.17 … +4.12 µA** |
| release point `V(SSR)` (should be 1.200 V) | 1.200 V exactly | **1.25 … 2.30 V; never releases at 2/63 corners** |
| loop out of regulation | never | **up to `V(SSR)` = 0.70 V, at 37/63 corners** |
| settled residual → output error | +0.03 nA → −1.16 mV | **+467 nA → −141 mV (−7.85 %)** |

467 nA × `Rtop` (300 kΩ) = 140 mV against the −141.26 mV measured — the
28/163 settled-accuracy failures #191's own record reported are exactly this
mirror leakage, arithmetically. Three independent small-signal measurements
in the same record (a 4550-point A/B at matched ramp states, a DC-preserving
AC-open of the injection element's drain from `FB`, and an AC short of the
mirror's gate node) found **no** phase-margin deficit attributable to the
element (+0.053 deg / +0.01 dB worst case, against a ≥ 1 pF budget on `FB`
where the element itself contributes an estimated ~30 fF) — ruling out
`Cm_ss`/`Rz_ss`-class compensation as the fix, per #196/PR #197. The defect
is a DC transfer defect in the mirror, not a missing pole or zero.

None of #191's own sizing sweeps against the original attempt (2×/4× device
scaling, W/L in both directions, a series decoupling resistor) could have
fixed this: all of them move output resistance or threshold, and the error
term that needs to move is a drain-voltage *difference* that none of them
touches.

## Decision (proposed)

**Cascode the injection mirror's output leg (`Mgmo_ss`) against its
reference leg (`Mgmr_ss`)** — an ordinary cascode current mirror, with the
reference leg's cascode device diode-connected so both legs' output nodes
sit at matched potential — so the mirror's drain-voltage mismatch goes from
0.95–1.61 V to approximately zero. This is Recommendation R2 of `design/
softstart_injection_compensation.md`, and the numeric targets any replacement
injection element must meet (T1–T7) are already specified there; this record
ratifies the topology, not the sizing, which is issue #191's remaining
acceptance-criteria work.

**Headroom is not the constraint.** At the binding (minimum-supply) corner,
`VIN − V(FB)` = 2.97 − 1.2 = 1.77 V is available on the output leg.
`Mgmo_ss` needs |V_ds| ≈ |V_gs| ≈ 0.82 V to match its reference leg, leaving
0.95 V across the added cascode device — 5–9× a `pfet_03v3`'s |V_dsat|
requirement at these single-digit-µA currents.

**Iq and area cost, against the ratified rows:**

- **Iq.** The cascode adds two low-current MOS devices in series with the
  existing branches; it does not add a new current path, so it changes no
  branch's *magnitude*, only where each branch's drain sits. The currently
  committed (uncascoded) six-device transconductor's own measured adder is
  already on record: `sim/quiescent-current/records/
  20260906-231405-d3cb117.md`, taken against this same chain, reads
  `iq_en_ua` = 25.3658 µA at the binding ff/125 °C/3.63 V corner, against the
  pre-#191 baseline's 22.0256 µA
  (`sim/quiescent-current/records/20260905-200855-3093ea1.md`) — an adder of
  **~3.34 µA**, leaving ~4.6 µA of headroom under the ratified < 30 µA row at
  that corner. (That record's overall verdict is FAIL, on the row's
  `vout_full_v` clause at `ff_125c_3.63v` and `sf_125c_3.63v` — not on the Iq
  clause, which passes at every corner. Both failing corners are at
  125 °C/3.63 V, the same temperature/supply pairing as this document's own
  worst measured settled-output-error corner, `sf_125c_3.63v`
  (`design/softstart_injection_compensation.md` §2, −141.26 mV settled); this
  record does not establish that the two are the same mechanism under a
  different load condition, but they are plausibly connected rather than
  independent, and that connection is worth re-checking once the cascoded
  chain's own `sim/quiescent-current` re-run lands.) Cascoding adds no branch
  and no new steady-state current path, so this decision is not expected to
  move the Iq adder materially; the post-cascode number is nonetheless issue
  #191's remaining `sim/quiescent-current` acceptance criterion to
  re-measure and attribute, not something this record asserts as final.
- **Area.** Two additional small-geometry MOS devices in the same class as
  the six the transconductor already carries (4 µm² each per `design/
  ldo_softstart.sch`'s SIZING AS BUILT section, 34 µm² total for six
  devices) — call it ~10 µm² added. Against the ratified < 0.1 mm²
  (100 000 µm²) core-area row, of which this block's existing addition
  already accounts for ~24 100 µm² (~24 %, per the same section), ten more
  µm² is not separately significant.

Both figures are estimates stated here for the ratification record; issue
#191's implementation PR re-measures Iq against `sim/quiescent-current` and
states the as-built area in the schematic's SIZING AS BUILT section, per
its existing acceptance criteria.

## Alternatives considered

- **Restore an output-side clamp** (the `#38`/`#43`-class circuit `#189`
  removed), so the bottom of the ramp is defined by a clamp rather than by
  the *difference* of two microamp currents. Rejected as the recommended
  path, for three reasons documented in `design/
  softstart_injection_compensation.md` §3 (R4):
  - It reinstates a **second loop and its own compensation question** —
    `Cm_ss`/`Rz_ss` existed for exactly this clamp before `#189` removed it —
    trading one topology risk for a previously-solved-then-reopened one,
    rather than fixing the mirror that #196/PR #197 measured to be the
    actual defect.
  - **Area**: `design/ldo_softstart.sch`'s SIZING AS BUILT section records
    the `#38`/`#43` clamp this issue's chain replaced at "about 11 800 µm²"
    — over 1000× the cascode's ~10 µm² estimate above, and about 12 % of the
    entire ratified 0.1 mm² core-area row on its own.
  - **Iq**: a second active loop (the clamp's own error path) is a second
    standing-current contributor against the same < 30 µA row with ~8 µA of
    measured headroom, where the cascode adds none.
  It does not address the measured root cause either — the clamp defines the
  ramp's bottom by a different mechanism, but says nothing about the mirror
  ΔV_ds that #196/PR #197 isolated, so it is not even known to fix the
  failure it would be reintroduced to fix.
- **Scale the feedback divider down** (e.g. `Rtop`/`Rbot` = 30 k/60 k,
  raising the injection current and lowering the 300 kΩ transimpedance that
  turns every microamp of mirror error into 300 mV of output error) — named
  in `design/softstart_injection_compensation.md` §3 (R4) as a fallback if
  T2/T3 (the absolute-accuracy targets) turn out not to be reachable after
  cascoding, not as a first move. Rejected here because it is closed by the
  ratified Iq row on its own arithmetic: the divider currently draws
  `VOUT`/900 kΩ ≈ 2 µA, and the enabled Iq measures 24.81 µA against the
  ratified < 30 µA
  (`sim/enable-shutdown/records/20260802-172454-b90b2ba.md`); a 10× divider
  adds ~18 µA and blows the row on its own, before the injection current
  mismatch is even counted.
- **Leave the mirror as built and re-tune device sizing** — already tried by
  #191's original attempt (2×/4× scaling, W/L in both directions, a series
  decoupling resistor) and shown not to work, because none of those levers
  changes ΔV_ds; the decoupling resistor made settled accuracy strictly
  worse, since its own IR drop at µA currents moves `FB` off `VREF` — the
  same 300 kΩ-transimpedance problem again. Not re-considered here.
- **Add a `Cm_ss`/`Rz_ss`-class compensation network on the injection
  path** — already ruled out by #196/PR #197's negative result (no
  phase-margin deficit exists to compensate; deliberately loading `FB`
  *creates* one — 3 pF alone costs 2.29 deg of phase margin at the nominal
  hold-release state against a measured ≥ 1 pF budget). Not this record's
  decision to revisit.

## Consequences

- **Issue #191's remaining acceptance criteria become the next PR's scope**:
  device-level replacement of `Binj_ss` using the cascoded mirror topology
  ratified here, a full 163-point `sim/soft-start` re-run superseding
  `sim/soft-start/records/20260906-202950-bfc4a0a.md`, a `sim/
  quiescent-current` re-run attributing the adder, and the as-built area
  recorded in `design/ldo_softstart.sch`'s SIZING AS BUILT section. This
  record does not itself satisfy any of those — no schematic changes with
  it.
- **The check-a-fix procedure `design/softstart_injection_compensation.md`
  §6 already specifies applies unchanged**: re-run
  `sim/soft-start-loop-gain/testbench/run.sh`, compare the new record
  against `20260910-015601-2387ece` and against targets T1–T7, and confirm
  the `anchor` phase still reproduces `sim/loop-stability/`'s settled-state
  measurement — T6 and T7 (the small-signal ones) are already met by the
  present chain with large margin and must not regress.
- **The next experiment `design/softstart_injection_compensation.md` §4
  names — a transient A/B in `sim/soft-start/` with `V(SSR)` driven by an
  ideal ramp through the `SSR` port #196 promoted — remains open** and is
  explicitly named in the operator's 2026-09-14 comment on #191 as part of
  the follow-on PR's scope. It separates the injection element's own
  transfer from the ramp's dynamics and is the mechanism most likely to
  explain the 356× vs. 2.1× transient/DC discrepancy §4 of that document
  documents but does not resolve. Cascoding the mirror fixes the DC transfer
  defect measured here; it is not yet shown to fix that transient
  discrepancy, which is why the A/B stays a named follow-on rather than an
  assumed consequence of this decision.
- **If a future re-measurement finds T2 (the ±0.10 µA absolute-accuracy
  target at `V(SSR) = 0`) is not reachable after cascoding**, `design/
  softstart_injection_compensation.md` §3 (R4) is the next place to look —
  it is not resolved by this record, only left as a documented fallback that
  this record declined to adopt as the first move.

## Cross-consequences (other records)

- **DR-0001**: unaffected as a decision. This record does not reopen
  DR-0001's capacitor window; it addresses the topology of the mechanism
  issue #189 built to hold the 4.7 µF end of that window.
- **DR-0022**: unaffected. DR-0022 restated the Startup row's
  current-limit-clearance sub-clause; this record concerns the inrush and
  settled-accuracy sub-clauses of the same row, which DR-0022 explicitly
  left as open circuit debt tracked by (at the time) issue #189 and now
  #191.
