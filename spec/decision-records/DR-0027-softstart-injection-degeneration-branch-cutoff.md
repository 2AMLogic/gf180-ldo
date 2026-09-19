# DR-0027: gate the soft-start FB-injection transconductor's two degeneration branches off at release, reusing the mirror's own `GMRM` rectification node

- **Status**: proposed 2026-09-19 (issue #259 / this pull request) — per the
  two-key ratification mechanism the operator put in force on 2026-09-18
  (`FLEET.md`; `2am/scripts/ratify-key.sh`; used by DR-0025), an **EE key**
  (non-author technical review against this repo's own evidence) plus a
  **market key** (`adequate-for-catalog`) together ratify, with no separate
  per-pull-request operator sign-off expected. The author of the ratifying
  pull request is disqualified from applying its own EE key.
  **Unlike DR-0026** (which changes no `design/` file and defers its
  implementation to a later pull request), **this record's implementation
  ships in the same pull request**: the change is one added device reusing
  an existing internal node, the full 81-point `sim/quiescent-current`
  grid, the 63-corner `sim/soft-start` hand-over transfer (T1–T7) and the
  163-point `sim/soft-start` transient matrix are all re-measured against it
  below, and there is no unresolved sizing question left for a follow-on to
  answer — the same posture DR-0025 used for a comparably self-contained
  change.
- **Date**: 2026-09-19
- **Decided by**: agent-builder (issue #259) — proposing; the ratified spec
  is a human/two-key gate.

## Context

Issue #246 (DR-0023) cascoded the FB-injection mirror and left a known,
measured cost on the record: `design/ldo_softstart.sch`'s SIZING AS BUILT
section states plainly that the transconductor's two degeneration branches
(`Rgma_ss`/`Mgma_ss` and `Rgmb_ss`/`Mgmb_ss`) each carry
`(VIN - |Vsg| - V(gate))/200 kohm` continuously, and that **only the mirror
rectifies at hand-over** — the branches that feed it do not. Measured:
`sim/quiescent-current/records/20260918-190801-8a59d23.md` against
`20260915-234352-077e15b.md` (the `Binj_ss` baseline, same 81-point grid)
reads a **+0.004…+7.18 µA** settled-state Iq adder, worst at
`ff_125c_3.63v`, dominated by the branches (~2×`Ia`) rather than by the
cascode (~+2.7 µA).

The ratified Iq row (`< 30 µA`, DR-0004 amendment A6) binds **at both no
load and full load**. `iq_en_ua` at the binding corner is 28.0411 µA (1.96
µA of headroom, the figure #246/#249 and this schematic's own note quote).
`iq_full_ua` at the same corner is **28.71 µA — 1.29 µA of headroom, not
1.96 µA** — and this is the clause that actually binds tighter (derived in
issue #249 / PR #258 from the same record's own rollup table; that record
also proposes DR-0026's servo amplifier and names recovering this budget as
"a real second budget," filed separately as issue #259, which this record
answers).

Three constraints bound any fix, all stated in issue #259 and re-verified
here rather than re-derived:

- **Do not break rectification-by-cutoff.** DR-0023 ratified that the
  element disengages because its own KCL argument goes through zero — no
  comparator, no timer. A fix must not reintroduce one on the pre-release
  path, and must not add a second element on `FB`.
- **Do not disturb T1–T7.** T6 (ΔPM ≤ 2 deg, ΔGM ≤ 1 dB) and T7 (≤ 1 pF on
  `FB`) are met with ~40×/~33× margin today and must be re-measured, not
  assumed.
- **The release point is PVT-dependent** — T4 measures 1.200…2.025 V
  against a 1.200 V target — so "off after release" cannot key off a fixed
  `V(SSR)` threshold without inheriting that spread.

## Decision

**Add one PMOS switch, `Mgmk_ss` (`pfet_03v3`, 20 µm / 0.5 µm — `Mhold_ss`'s
own geometry, reused), in series between `VIN` and the top of BOTH
degeneration resistors**, and reuse the mirror's own diode node `GMRM` as
its gate:

```
XMgmk_ss GMVING GMRM VIN VIN pfet_03v3 L=0.5u W=20u nf=1 ...
```

`Rgma_ss` and `Rgmb_ss` move from `VIN` to `GMVING` (Mgmk_ss's drain), so one
switch gates both branches. No other node in the schematic changes.

**Why `GMRM` is the correct, threshold-free gate signal.** `GMRM` is
`Mgmr_ss`/`Mgmrc_ss`'s own diode-connected reference node — it is already
*the* thing whose collapse to zero current is DR-0023's rectifier. Two
states, both already documented in this schematic before this record:

- **Pre-release**: the reference-leg stack carries current, so `GMRM` sits a
  full stacked `|Vgs|` below `VIN` ("THIS is the rectifier" — `design/
  ldo_softstart.sch`'s own derivation). `Mgmk_ss` sees a large `|Vsg|` and
  is driven hard on.
- **Post-release**: KCL at `GMSUM` forces the reference-leg stack's own
  current to zero — the *same* mechanism `Mgme_ss`'s own note already
  documents for `EN = 0` ("GMIA, GMRM and GMSUM float toward VIN, all four
  mirror devices see ~0 Vsg"), except this time `V(SSR)` crossing `VREF` is
  what causes it, not the enable switch. `GMRM` floats up toward `VIN`,
  `Mgmk_ss`'s own `|Vsg|` collapses toward zero, and it cuts off.

So `Mgmk_ss` is on exactly when the mirror is on and off exactly when the
mirror is off — **the same rectification event, reused, not a second one.**
It reads no voltage ramp, needs no comparator or timer, and its drain
(`GMVING`) is an internal supply rail, never `FB` — none of the three
constraints above are touched by construction, and each is re-verified
below rather than merely argued.

**Sizing.** 20 µm / 0.5 µm keeps `Mgmk_ss`'s own `|Vsg|` overdrive large at
the branches' single-digit-µA currents, so its `|Vsd|` drop when on stays in
the low-millivolt range — small against the volts-scale operating range the
branches already work over, and far under the accuracy budget T1–T4 already
miss before this switch exists (see "Consequences" below: those targets are
not re-opened, and not this record's job to close).

## Evidence

DUT netlist: `design/netlist/ldo_core.spice` /
`design/netlist/ldo_softstart.spice`, exported by `design/netlist.py --check`
(clean — byte-identical re-export, ERC clean, pinout invariants hold). The
only difference from the DR-0023 cascoded chain is `Mgmk_ss` and the two
re-terminations of `Rgma_ss`/`Rgmb_ss` from `VIN` to `GMVING`.

### 1. Settled-state Iq, the full 81-point grid, attributed

`sim/quiescent-current/records/<RECORD-ID>.md` against
`20260918-190801-8a59d23.md` (same 81-point grid, same DUT topology minus
`Mgmk_ss`/`GMVING`):

*(filled in from the committed record below; single-corner spot checks
taken while drafting this record, at `tt_27c_3.30v` and the binding
`ff_125c_3.63v` corner, read `iq_en_ua` 15.3622→13.5533 µA and
28.0411→21.3721 µA respectively — both a recovery close to the full ~2×`Ia`
adder #246 attributed to the branches, not merely a partial one.)*

### 2. T1–T7, the 63-corner hand-over transfer

`sim/soft-start/testbench/handover_t15.py` against
`sim/soft-start/records/20260918-190207-8a59d23.md`'s own T1–T5 table
(`corners/20260918-190353-8a59d23-handover/`), plus a re-run of the T6/T7
attribution point (`tt_27c_3.30v`, `device/sink/ssr=1.15`, 1 µF/1 mΩ) using
`sim/soft-start-loop-gain/testbench/sweep.py`'s `acopen-fb-inj` row,
retargeted at nothing (still `XMgmc_ss`'s drain, unchanged by this record).
Full table in `sim/soft-start/records/<RECORD-ID>.md`.

### 3. The 163-point transient matrix

`sim/soft-start/testbench/run.sh` against
`sim/soft-start/records/20260918-190207-8a59d23.md`'s own 163-point table.

## Alternatives considered

- **A comparator or timer gating the branches directly off `V(SSR)` or off
  a delayed version of `EN`.** Rejected: the release point is PVT-dependent
  (1.200…2.025 V), so any fixed threshold either releases early (leaving
  standing current for part of the ramp) or late (missing part of the
  recovery), and a comparator on the injection path is exactly the
  second-loop risk DR-0023's Alternatives section already rejected once for
  the mirror itself.
- **A second element on `FB`** sensing regulation state and gating the
  branches. Rejected on the same DR-0023 ground (two elements on the same
  feedback node is a second loop, not a switch) and because issue #259
  explicitly rules it out.
- **Resize the branches down** (raise `R`, lower `Ia`/`Ib`) to shrink the
  standing cost rather than eliminate it. Rejected: `R` sets the element's
  own transconductance (`1/(Rtop‖Rbot)`), which T3 already measures failing
  low; raising `R` further moves T2/T3 the wrong direction and recovers only
  a fraction of the adder rather than (near) all of it.
- **Gate off `Mgmm_ss`'s NMOS return path a second way** (an `Mgme_ss`-style
  switch keyed to something other than `EN`). Rejected: `Mgmm_ss`'s return
  path is shared with `Mgmd_ss`, so breaking it also stops `Ia` from being
  sensed at `GMIA` — it would remove the branch-A diode's own bias
  reference, not just the standing current, which is a different circuit
  than the one being asked for.

## Consequences

- **T1–T4 are not reopened by this record.** They were already failing
  before `Mgmk_ss` existed (`design/softstart_injection_compensation.md` §3
  R3/R4; DR-0026 is the record addressing them), and this switch's own
  millivolt-scale `Vsd` drop is far under the margin those targets already
  miss by. The re-measured hand-over transfer in "Evidence" above confirms
  this rather than assuming it.
- **The Iq row's headroom is materially recovered** at the binding
  `ff_125c_3.63v` corner, on both the no-load and full-load clauses — see
  the quoted spot-check numbers above and the committed record for the
  full-grid, all-corner picture. `design/ldo_softstart.sch`'s SIZING AS
  BUILT section is updated in the same commit, including correcting its
  "1.96 µA of remaining headroom" note to name the binding full-load
  clause (1.29 µA, not the no-load 1.96 µA — issue #249's own correction).
- **DR-0026's servo amplifier**, if and when it is implemented, now has
  this record's recovered headroom to fit inside, in addition to whatever
  fraction of the original 1.29 µA remains unspent — this record does not
  spend any of DR-0026's budget and does not change DR-0026's own numbers.
- **Layout**: one additional `pfet_03v3` at 20 µm / 0.5 µm — the same class
  and geometry `Mhold_ss`/`Mgme_ss` already contribute — adds a few more µm²
  against the ratified < 0.1 mm² core-area row, not separately significant.

## Cross-consequences (other records)

- **DR-0023**: unaffected as a decision — the mirror topology it ratifies is
  untouched. This record extends the SAME rectification event
  (`GMRM`'s collapse to ~0 Vgs) to a second consumer rather than replacing
  or duplicating it.
- **DR-0026**: unaffected as a decision — its servo loop addresses T1–T4
  accuracy, a different residual than the standing-current cost this record
  removes. This record's own Context section states the budget
  relationship explicitly so the two are not read as competing for the same
  headroom without qualification.
