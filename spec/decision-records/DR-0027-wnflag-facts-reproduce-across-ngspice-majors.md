# DR-0027: DR-0025's `wnflag` model-bin facts reproduce on ngspice-42 and ngspice-47; the ngspice-46 pin does not move

- **Status**: proposed
- **Date**: 2026-09-19
- **Decided by**: agent-builder, issue #254 (recommendation only)

## Context

[`DR-0025`](DR-0025-model-bin-selection-binds-on-per-finger-width.md)
established three properties of ngspice's model-bin selection -- all
measured on ngspice-46 alone:

- **F1** -- `.options wnflag=1` resolves `design/netlist/ldo_core.spice`'s
  `W=2000u nf=40` pass device to the declared bin `pfet_03v3.12`, with the
  instance's `w` left undivided.
- **F2** -- `wnflag=0` (and no card at all) fails to parse
  (`could not find a valid modelname`); there is no silent clamp to a
  neighbouring bin, and a genuinely out-of-range per-finger width hard-errors
  even at `wnflag=1`.
- **F3** -- for two `.options` cards naming the same key, the **first** card
  wins and the later one is silently discarded, with no warning -- the
  property that makes `sim/harness/runner.py`'s deck-level pin authoritative
  rather than decorative.

DR-0025's own text flagged this as an open gap rather than asserting it:
*"`ngspice-42` and `ngspice-47` are not verified here ... Filed as #221
rather than asserted."* Issue #221 scoped that verification and was closed
without performing it. That became load-bearing rather than theoretical when
#247 (PR #252) made the missing validation the documented, user-visible
prerequisite for ever moving the ngspice-46 pin
(`docs/environment-setup.md` #1, `sim/harness/runner.py`'s mismatch
messages) -- and Homebrew's unversioned `ngspice` formula moved to
ngspice-47 on 2026-09-18, so hosts keep arriving at that wall. Issue #254
re-opened the scope #221 left unperformed and this record is its outcome.

This record is an **amendment**, not an edit: per `sim/README.md`'s and this
template's append-only convention, DR-0025's own text and evidence are left
exactly as written. Nothing here supersedes DR-0025 -- it extends validation
to ngspice majors DR-0025 explicitly declined to assert anything about.

## Decision

**Ratify that DR-0025's three `wnflag` facts (F1, F2, F3) hold, unchanged,
on ngspice-42 and ngspice-47, in addition to the ngspice-46 they were
established on.** Measured directly (`sim/toolchain-portability/`, issue
#254), on one host, one PDK (`gf180mcuD @
c6d73a35f524070e85faff4a6a9eef49553ebc2b`), across four independently
provisioned ngspice builds:

| build | ngspice | binary sha256 | F1 | F2 | F3 |
|---|---|---|---|---|---|
| this repo's pinned install | 46 | `c874869b16d...072931` | HOLDS | HOLDS | HOLDS |
| independently built, same `configure` flags | 46 | `cec9502049...484ff0` | HOLDS | HOLDS | HOLDS |
| independently built, same `configure` flags | **47** | `ad57436ca0a...2600b9e` | HOLDS | HOLDS | HOLDS |
| Ubuntu 24.04 apt package (CI's `pvt-smoke` toolchain) | **42** | `820658317b0...b7fc45` | HOLDS | HOLDS | HOLDS |

Full raw ngspice logs and per-fact verdicts:
`sim/toolchain-portability/records/20260919-033900-4595f97.md` (F1),
`20260919-034000-4595f97.md` (F2), `20260919-034100-4595f97.md` (F3).

**Additionally**, a same-netlist/same-PDK/same-host numerical A/B of
`sim/loop-stability`'s loop-gain margins (216 points, `ff`/125 degC, the full
load/cap/ESR grid, all three supply rails) found a worst-case
ngspice-46-to-ngspice-47 delta of **1.972 deg phase margin / 0.908 dB gain
margin** at the operating point already identified in
`sim/loop-stability/records/20260906-090647-3981d88.md` as this repo's most
sensitive measured point -- the same order of magnitude as that record's own
already-accepted, non-design-causal same-version (ngspice-46-vs-ngspice-46)
build spread. Two independently-built ngspice-46 binaries agreed
bit-for-bit on all 216 points in the same run, establishing that this
particular grid's build-to-build noise floor, on this host, is exactly zero
-- so the ngspice-47 delta is attributable to the major-version change, not
to generic build noise. Full data:
`sim/toolchain-portability/records/20260919-034500-4595f97.md`.

**This decision does not move the ngspice-46 pin.** `docs/environment-setup.md`
#1 continues to pin ngspice-46 as the only validated install for producing
`sim/` evidence, and `sim/harness/runner.py`'s provenance check continues to
treat any other resolved major as a fault to fix, not a variant to adopt.
What this decision changes is narrower: **the documented prerequisite for
that future decision -- DR-0025's facts holding on another major -- is now
satisfied for ngspice-42 and ngspice-47**, where before this record it was
an asserted-but-unverified gap. Moving the pin itself remains a separate,
future decision that would additionally have to rule on every existing
`sim/` record, which this record does not attempt.

## Alternatives considered

- **Move the ngspice-46 pin to ngspice-47 now, on the strength of this
  record.** Rejected. Issue #254 scoped this explicitly as out of scope
  ("Explicitly NOT in scope: Moving the pin ... the decision itself is
  spec-adjacent and belongs to a decision record, not to whoever performs
  the measurement"). This record establishes the facts a future
  pin-move decision would need; it does not make that decision, and does not
  rule on the ~132 existing `sim/` records such a move would also have to
  address.
- **Treat the A/B's 1.972 deg / 0.908 dB delta as disqualifying ngspice-47
  outright.** Rejected as an overreach in the other direction: the delta is
  comparable in magnitude to spread this repo already measured between two
  same-version ngspice-46 builds and ruled non-design-causal
  (`20260906-090647-3981d88.md`). Treating a same-order-of-magnitude delta as
  disqualifying only for the major-version arm, while accepting it for the
  same-version arms, would not be a principled distinction on this evidence
  alone.
- **Re-baseline any existing `sim/` record on ngspice-47 grounds.** Rejected,
  and out of scope: no `sim/` record's own PASS/FAIL verdict changes on the
  strength of this record, and none is edited (`sim/README.md`'s append-only
  rule).
- **Skip the numerical A/B and stop at the three categorical facts.** The
  three facts are pass/fail (a bin resolves, or it does not) and do not, by
  themselves, bound *how much* a future pin move could shift a marginal
  design point. The A/B was added because issue #254's own scope named it
  explicitly, and because a categorical "the pin still works" result would
  otherwise leave the more practically relevant "how much could moving it
  cost a nearly-passing corner" question unanswered.

## Consequences

- **The `docs/environment-setup.md` #1 / `sim/harness/runner.py` citations
  of #221 as "the still-open gap" are now stale** and are updated by this
  same pull request to cite this record instead, per issue #254's own
  Acceptance Criteria. The pin itself, and the enforcement behaviour of the
  provenance check, are unchanged.
- **A future decision to move the ngspice-46 pin now has DR-0025's
  categorical facts and one numerically-marginal-point A/B to draw on for
  ngspice-42/47**, rather than an asserted-but-unverified gap. That future
  decision would still need, at minimum: a ruling on the ~132 existing
  `sim/` records' comparability, and (if the numerical delta matters to any
  record sitting close to a spec bar) a wider corner sweep than this
  record's single-corner/single-temperature A/B.
- **No `sim/` record outside `sim/toolchain-portability/` is added, edited,
  or superseded.** `sim/loop-stability`'s own records stand exactly as
  written; the A/B ran with `--no-write` throughout for exactly this reason.
- **`ngspice-42` (CI's `pvt-smoke` toolchain) now has direct evidence behind
  its long-standing informal role** as "the standing #221 model-bin
  portability check" (`docs/environment-setup.md` #4's wording, now updated)
  -- it was already running in CI; this record is the first time its
  wnflag-facts behaviour was actually checked against DR-0025 rather than
  merely relied upon not to crash.
