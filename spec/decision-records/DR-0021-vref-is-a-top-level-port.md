# DR-0021: `VREF` becomes a top-level `ldo_core` port; this repo does not design its own bandgap

- **Status**: proposed -- ratification is the operator's, the same process
  DR-0001, DR-0007, DR-0008 and DR-0012 through DR-0020 went through.
  **Nothing in this record is in force until an operator ratifies it.**
  Unlike DR-0016 through DR-0018, this record *does* propose a `design/`
  change and that change is implemented in the same pull request, because
  the change is provably electrically inert (see "Evidence" below) and the
  interface it establishes is what the Chipalooza Challenge #5 submission
  needs in order to be honest about what it is asking the harness for.
- **Date**: 2026-09-05
- **Decided by**: Builder agent, issue #174 (recommendation only)
- **Builds on**: DR-0003 (which budgets the offset gain-up `1/beta =
  Vout/Vref = 1.5` against a **1.2 V** reference, and the 900 kOhm divider's
  2.0 uA standing current), DR-0004 (the ratified spec this does not touch),
  DR-0002 (3.3 V-flavor devices throughout, including "reference").
  Supersedes none of them.

## Context

`design/ldo_core.sch` regulated against `VREF`, a net driven by `Vref1` --
an **ideal 1.2 V DC voltage source instantiated inside the `ldo_core`
subcircuit**. `VREF` was not a port: `.subckt ldo_core VIN VOUT EN VSS
ERRAMP_OUT PASS_GATE` had six pins and none of them was the reference. The
net is shared by three consumers inside the cell -- `Xerramp`'s `INN`
(`design/ldo_core.sch`), `Xilimit`'s `VREF`/`Rbias` bias generator, and
`Xsoftstart`'s ramp ceiling and finish line.

`design/README.md`'s "Reference voltage assumption" section has always
disclosed this as a stand-in ("There is no bandgap block designed yet for
this repo"), so nothing here is a newly-discovered defect. What issue #174
surfaced is that the stand-in has an **interface** consequence nobody had
priced in: Chipalooza Challenge #5's harness offers a bandgap-referenced
bias-voltage slot, `docs/chipalooza/challenge-5-proposal.md` proposes to
take it, and there is no net at the top level to attach it to. The proposal
document had to disclose the slot as "**proposed, 0 of 1 today**". The same
substitution `2AMLogic/gf180-sar-adc`'s Challenge #3 proposal makes for its
own external `V_REF` pin is not available to this block, because this block
has no pin.

The choice this record settles is the one issue #174 names: promote `VREF`
to a port, design a real on-chip reference sub-block here, or defer.

## Decision

**1. `VREF` is promoted to a top-level port of `ldo_core`, appended as the
seventh pin.** The ratified interface becomes:

```
.subckt ldo_core VIN VOUT EN VSS ERRAMP_OUT PASS_GATE VREF
```

`Vref1` is **deleted** from `design/ldo_core.sch`. The identical ideal 1.2 V
source now lives in each testbench deck, one per deck, driving the `VREF`
port. `design/netlist.py`'s `RATIFIED_TOP_PORTS` assertion is updated to the
seven-port list, so the same loud-failure gate that protected the six-port
interface now protects the seven-port one.

**Appended, never inserted.** The first six positions are unchanged, so a
stale six-node instantiation fails on node count in ngspice instead of
silently shifting every net by one. This is the same convention issue #11
used when it appended `EN` to `error_amp` and issue #55 used when it
appended `BG`.

**One port, not three.** `Xerramp`, `Xilimit` and `Xsoftstart` continue to
share a single internal `VREF` net, exactly as before; only its driver moved
outside the cell. Three separate reference pins would triple the pad cost
for a node that must be the same voltage at all three consumers by
construction (the current limit's threshold and the soft-start ramp's finish
line are both *defined* relative to the same reference the loop regulates
to).

**2. This repository does not design an on-chip bandgap or reference
sub-block, and `ldo_core` does not contain one.** `ldo_core` **consumes** a
reference; it does not generate one. That is now a stated interface fact
rather than an unstated idealization.

**3. The contract a driver of `VREF` must meet** (this is the part that
becomes a spec obligation, and the reason this is a decision record rather
than a refactor):

| Requirement | Value | Where it comes from |
|---|---|---|
| Nominal voltage | 1.2 V | DR-0003's offset gain-up budget `1/beta = Vout/Vref = 1.5`; `design/error_amp.md` "Why 1.2 V, not 0.6 V" (the NMOS input pair's common-mode floor at the 2.10 V dropout test point) |
| Output impedance | low enough that the reference bias current below does not move `VREF` materially | `Xilimit` and `Xsoftstart` both draw a `VREF`/`R` bias current; `Xerramp`'s `INN` draws only gate leakage |
| Current it must source | see "Evidence" below -- now measured at the port, per corner | `sim/enable-shutdown/`, `m_iref_en_ua` / `m_iref_off_ua` |
| Accuracy / tempco / noise / its own PSRR | **flow straight through to `VOUT` at 1.5x** and are **not** in any ratified row of this block's spec | README note 2's regulator-only accuracy window; `sim/mc-output-accuracy/`'s own manifest excludes the reference's error by construction |

The last row is the substantive one. Every `VOUT` accuracy, PSRR and noise
number in `sim/` is measured against an **ideal** reference and therefore
excludes the reference's contribution entirely. That was true before this
record and is unchanged by it -- but it was invisible, because the
idealization was buried one level inside the subcircuit. It is now visible
at the interface, which is the point.

**4. Nothing about the electrical design changes, and no ratified row
moves.** No device is added, removed or resized. The one deleted element is
an ideal voltage source whose replacement is bit-identical and sits on the
same node with the same return.

## Evidence

An ideal voltage source is an ideal voltage source wherever it is declared:
`Vref1 VREF VSS 1.2` inside the subcircuit and `Vref VREF 0 DC 1.2` in a
deck whose `VSS` port is tied to node `0` flatten to the same element on the
same node pair, and both are an AC short to ground. The flattened circuit is
therefore identical, and the change is expected to be a measurement no-op.
"Expected" is not this repo's standard, so it was measured.

**Method**: `origin/main` at `ec9e530` was extracted to a scratch tree and
each affected testbench was run on **both** trees, back to back, on the same
host with the same ngspice and the same pinned PDK, and the per-corner
measurement lines compared field by field. This is a stronger comparison
than reading the committed head records, which were minted on other days
against other toolchain states.

<!-- EVIDENCE_TABLE -->

**Reading of the residuals**: the DC and `.ac` benches are **byte-identical
at every corner**, as the argument above predicts. The residuals that are
not zero are all in **transient** benches and all have the same cause:
deleting one voltage source changes the MNA matrix's dimension and pivot
order, which perturbs LU round-off, which perturbs the adaptive
timestep controller's step sequence, which moves a `.meas` extraction in the
last digits. Two independent checks confirm that reading rather than
asserting it:

1. The moved quantities with the largest *relative* deltas are the ones with
   the smallest *absolute* values -- `sim/amp-selfosc/`'s peak-to-peak
   ringing amplitudes move by tens of picovolts on a bench whose ratified
   bar is a millivolt-scale oscillation check, and `sim/quiescent-current/`'s
   disabled-state `iq_dis_ua` moves by half a picoamp at ngspice's default
   `abstol` of 1 pA, against a ratified bound of 3 uA.
2. **No corner's pass/fail verdict moves, on any bench.**

## Alternatives considered

- **Design a real on-chip bandgap / reference sub-block in this repository.**
  Rejected, and not because it is unattractive -- it is the correct thing for
  a *standalone* LDO product. It is rejected because (a) it is a whole
  second block, not an increment on this one: a gf180mcu bandgap is its own
  topology selection, its own PVT campaign, its own trim question and its own
  area budget, comfortably larger than everything `design/` currently
  contains; (b) `CLAUDE.md` already points this repo's harness bootstrap at
  a **sibling** repository, `2AMLogic/gf180-bandgap`, whose entire subject is
  that block -- designing a second one here would fork the effort across two
  repos on the same PDK for the same part; and (c) it does not remove the
  need for this record's decision anyway. A block that contains its own
  bandgap **still** cannot accept the Challenge #5 harness's bandgap-
  referenced bias slot without a port, so the port question would have to be
  answered a second time, after the more expensive work.
- **Defer: leave `VREF` internal and let the Challenge #5 proposal keep
  disclosing the slot as unavailable.** Rejected. The proposal document is
  honest about the gap, so deferring costs nothing in integrity -- but it
  costs the whole bandgap-referenced-bias-voltage slot, which is exactly the
  Challenge affordance this block most needs, and the fix is provably inert.
  Deferring an inert change that unblocks a named milestone is not
  conservatism, it is just delay.
- **Expose `VREF` *and* keep an in-cell default reference, selectable.**
  Rejected: SPICE has no optional ports, so "selectable" means either a mux
  and a mode pin (real silicon, real area, a new ratified pin, and a new
  failure mode where the block is driven from both sides at once) or two
  variant cells (two netlists, two PVT campaigns, two things to keep in
  sync). Neither is worth it to preserve a source that is ideal and therefore
  fictional in the first place.
- **Insert `VREF` in the middle of the port list** -- e.g. next to `VSS`,
  where a reader might expect a bias pin to sit. Rejected: it silently
  re-binds every net of every existing six-node instantiation instead of
  erroring, which is precisely the failure mode `design/README.md`'s
  append-not-insert convention exists to prevent.
- **Three reference ports, one per consumer** (`error_amp`, `ldo_ilimit`,
  `ldo_softstart`). Rejected: they are the same node by construction --
  the limit threshold and the soft-start finish line are both *defined*
  against the voltage the loop regulates to -- so three pins would let a
  consumer of this block create a state the design has no meaning for, at
  triple the pad cost.
- **Make `VREF` an `inout` (`iopin`) rather than an input.** Rejected: the
  cell only ever consumes this node. `iopin` is reserved here for the rails
  and `VOUT`, which genuinely carry current in both directions in different
  operating states. `VREF` does draw a real (microamp-scale) bias current,
  but so does any reference *input* pin; direction is about who drives the
  node, and nothing in this cell drives it.

## Consequences

1. **`ldo_core`'s ratified interface is now seven ports.** Every existing
   six-node instantiation must be updated; there are 15 testbench decks and
   43 instantiations in `sim/`, all updated in the same pull request.
   `python3 design/netlist.py --check` enforces the new list, so drift fails
   loudly. `design/README.md`'s pinout table is updated to match, and the
   "renegotiating with whichever of #9/#10/#11/#12/#13 depend on the field
   being changed" note in that section is discharged for this change: all
   five of those issues are closed, and the change is an append that leaves
   their fields untouched.
2. **`docs/chipalooza/challenge-5-proposal.md` can take the harness's
   bandgap-referenced bias-voltage slot** -- 1 of 1, not "proposed, 0 of 1",
   and 3 of <= 4 dedicated pads rather than 2. Its §2.2 / §2.3 / §4 / §7 are
   updated accordingly in the same pull request.
3. **The block now has an external dependency it did not visibly have
   before.** This is the honest bad consequence, and it must not be
   soft-pedalled: `ldo_core` cannot regulate at all without something driving
   `VREF`. A silicon implementation of this cell *alone* is not a complete
   regulator; it is a regulator core that needs a companion reference. That
   was already true -- an ideal 1.2 V source is not manufacturable -- but the
   interface used to hide it, and now it does not.
4. **Every accuracy / PSRR / noise number in `sim/` remains
   reference-excluded, and now says so at the interface.** When a real
   reference is eventually attached (a bandgap block, or the Challenge
   harness), its tolerance, tempco, noise and supply rejection enter `VOUT`
   at `1/beta` = 1.5x and are *not* covered by any existing record. Closing
   that gap needs a reference-referred campaign that could not even be
   written before this record, because there was no port to drive: a `.ac`
   stimulus on `VREF` for reference-to-output transfer, and a
   non-ideal-source variant for tempco and noise. That is filed as follow-up
   work rather than folded in here (see "Follow-up filed").
5. **No `sim/` record is invalidated.** Every re-run in the same pull request
   agrees with the record it supersedes to within the residuals tabulated
   above, and no corner's verdict moves. Records minted before this change
   are not in error and are left untouched, per `sim/README.md`'s
   append-only rule.
6. **Layout (#173) is unaffected in substance, but not in pinout.** `VREF`
   can still be a purely internal route inside the block's own floorplan --
   nothing about the physical design changes -- but the cell now needs a
   `VREF` terminal in its pin list for LVS against the seven-port netlist.
   #173 has not started, so this lands ahead of it rather than invalidating
   it.
7. **If an operator does NOT ratify this record**, the correct rollback is a
   single revert of the pull request: the six-port netlist, the in-cell
   `Vref1`, and the 15 decks all return together, and no `sim/` record has to
   be withdrawn, because the ones minted here are additive evidence that the
   two placements measure the same.

## Follow-up filed

The reference-referred characterization this port makes possible for the
first time -- `VREF`-to-`VOUT` transfer over frequency, and the tempco /
noise / PSRR budget a real reference would have to meet for the ratified
`Output` and `PSRR` rows to survive contact with it -- is filed as its own
issue rather than attempted here. It is a genuinely new measurement campaign
(new testbench, new claim, its own PVT matrix), not an increment on this
interface change, and folding it in would have made this record's central
claim -- *that nothing electrical moved* -- impossible to check.
