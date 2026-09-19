# DR-0027: gate the soft-start injection transconductor's degeneration branches off a self-referential mirror node — proposed mechanism, not yet ready to ratify

- **Status**: proposed 2026-09-19 (issue #259 / this pull request) — per the
  2026-08-19 ratification-via-PR policy (2AMLogic/2am#357, the mechanism used
  for DR-0005/PR #137, DR-0006/PR #127, DR-0018/PR #199, DR-0023/PR #217,
  DR-0024/PR #228 and DR-0026/PR #258), the operator's review and approval of
  a ratifying pull request is the ratification act itself. **This record does
  not propose ratification of the mechanism it describes.** Unlike DR-0023 and
  DR-0026, which proposed a specific topology for the operator to approve,
  this record's own prototype evidence (below) finds a genuine DC
  convergence failure at one of four sampled PVT corners — a blocking defect,
  not a stylistic one. It is filed as a **negative/partial result**, in the
  style of DR-0009/DR-0010/DR-0011, so the next attempt does not have to
  re-discover either the promising part or the failure mode from scratch.
  **This record changes no `design/` file.** The prototype netlist edit used
  to gather the numbers below was built, measured, and reverted in the same
  session — `git diff origin/main...HEAD -- design/netlist` is empty except
  for the one-line `ldo_softstart.sch` documentation correction §"Related"
  describes, which does not touch device topology.
- **Date**: 2026-09-19
- **Decided by**: agent-builder (issue #259) — **not decided**; a mechanism
  with a known blocking failure mode is not a decision for the operator to
  ratify yet. Filed so the failure mode and the promising baseline are both
  on record before the next attempt.

## Context

Issue #191's device-level FB-injection transconductor (`design/
ldo_softstart.sch`) has two `VIN`-referenced, resistor-degenerated PMOS
branches (`Rgma_ss`/`Mgma_ss`, `Rgmb_ss`/`Mgmb_ss`) that carry
`(VIN − |Vsg| − V(gate))/200 kOhm` **forever** — DR-0023's cascoded mirror
rectifies the *output* of the transconductor (no current sources into `FB`
after hand-over), but neither branch's own bias current switches off, because
rectification happens one node downstream of them (the `Mgmr_ss`/`Mgmrc_ss`
reference stack going into cutoff, not the branches themselves). Measured,
`sim/quiescent-current/records/20260918-190801-8a59d23.md` against
`20260915-234352-077e15b.md`: the branches' standing current is the dominant
share of a **+0.004…+7.18 µA** Iq adder, worst at `ff_125c_3.63v`. Issue #249
established that the ratified `< 30 µA` row (DR-0004 amendment A6) binds
tighter than commonly quoted — **1.29 µA** of headroom at the full-load
clause (`iq_full_ua` = 28.71 µA), not the 1.96 µA the no-load clause
(`iq_en_ua` = 28.0411 µA) alone suggests. Issue #259 asks for the branches'
standing current to be recovered, subject to three hard constraints already
named there:

1. Must not break DR-0023's rectification-by-cutoff (no comparator, no
   timer, nothing new on `FB`).
2. Must not disturb T1–T7 (the hand-over transfer characteristics
   `design/softstart_injection_compensation.md` §3 defines).
3. Must not key off a fixed `V(SSR)` threshold — T4's release point is
   PVT-dependent (1.200…2.025 V, `sim/soft-start/records/
   20260918-190207-8a59d23.md`) — so a hard-coded comparator reference would
   inherit that spread.

## The proposed mechanism

Add one PMOS switch (`Mgmg_ss`, prototype sizing `pfet_03v3 L=0.5u W=10u`)
in series between `VIN` and a new shared node (`VING_ss`) that both
degeneration branches' `VIN`-side terminal moves to (previously both tied
directly to `VIN`). `Mgmg_ss`'s gate is **not** a new signal — it is tied to
`GMRM`, the existing diode node at the top of the mirror's reference-leg
cascode stack (`Mgmr_ss`/`Mgmrc_ss`), and its source is `VIN`:

```
Pre-release  (Ia > Ib, stack conducting):
  GMRM sits a healthy |Vgs(Mgmr_ss)| below VIN (the stack's own diode drop,
  larger when Ia is larger, i.e. largest at the START of the ramp where the
  branches' current matters most). Mgmg_ss sees a correspondingly healthy
  Vsg and stays on, low-Ron, passing VIN through to the branches with
  negligible drop.

Post-release (Ia < Ib, stack in cutoff -- DR-0023's own rectification event):
  With nothing to conduct, GMRM rises toward VIN (the diode's own Vgs
  collapsing). Mgmg_ss's Vsg = VIN - GMRM shrinks with it, throttling and
  then substantially cutting the branches' own supply.
```

This is deliberately **not** a new threshold: `Mgmg_ss` turns off as a
*consequence* of the same "argument goes through zero" event DR-0023 already
ratified for the mirror itself, one node upstream, using an internal mirror
node rather than `SSR` or `FB`. No comparator, no timer, nothing added to
`FB`. It is the same "break the branch's own supply/return with one
self-gated device" idiom this file already uses twice (`Mben_ss` on
`Rss_bias`'s return, `Mgme_ss` on the transconductor's own ground return) —
here applied to the branches' *supply* side instead, self-gated by the
mirror's own state rather than by `EN`.

## Prototype evidence

Built directly in `design/ldo_softstart.sch` (two `res.sym` pin relabels,
one `pfet_03v3.sym` instance), netlisted (`python3 design/netlist.py`, ERC
clean, ports unchanged, pinout invariants held), and measured against
`sim/quiescent-current`'s `tb_quiescent.spice` at four spot corners chosen to
bracket the grid (the record's own worst corner, its nominal corner, a
second 125 °C/3.63 V corner recorded elsewhere in the grid, and its coldest/
slowest corner) before being reverted — **not** committed to `design/` by
this record.

| corner | `iq_en_ua` baseline → prototype | `iq_full_ua` baseline → prototype | `vout_full_v` baseline → prototype |
|---|---|---|---|
| `ff_125c_3.63v` (binding, Iq) | 28.0411 → **21.0306** (−7.01 µA) | 28.71 → **22.0131** (−6.70 µA) | 1.79357 → 1.77721 (−16.4 mV; error −6.4 mV → −22.8 mV) |
| `sf_125c_3.63v` | 23.3693 → **16.9693** (−6.40 µA) | 23.2712 → **16.8742** (−6.40 µA) | 1.79721 → 1.78792 (−9.3 mV; error −2.8 mV → −12.1 mV) |
| `tt_27c_3.30v` (nominal) | 15.3622 → **13.5533** (−1.81 µA) | 15.2568 → **13.4479** (−1.81 µA) | 1.79934 → **1.79934** (bit-identical) |
| `ss_-40c_2.97v` (coldest, slowest) | 8.8988 → **non-physical** | 8.80826 → **non-physical** | 1.79948 → **−0.075 V (non-physical)** |

Baselines are `sim/quiescent-current/records/20260918-190801-8a59d23.md`'s
own committed rows; prototype values are this session's `--no-write` spot
runs against the same testbench, same PDK pin (`gf180mcuD @
c6d73a35f524070e85faff4a6a9eef49553ebc2b`), same ngspice (`ngspice-46`).

**The promising part.** At three of four sampled corners the mechanism
recovers 1.8–7.0 µA — at the binding corner, essentially the entire
previously-measured +7.18 µA adder — while moving settled output error by at
most 16.4 mV, comfortably inside the ratified ±36 mV (±2 %) allocation, and
at the nominal corner moving it by **nothing measurable** (`vout_full_v`
identical to the printed digit). This is close to the outcome issue #259
asks for.

**The blocking finding.** At `ss_-40c_2.97v` the prototype does **not**
converge to a physical operating point. The baseline netlist solves this
corner cleanly (`op` succeeds directly). With the prototype in place,
ngspice's `.op` sequence fails at every stage it tries —

```
Note: Starting dynamic gmin stepping
Warning: Dynamic gmin stepping failed
Note: Starting true gmin stepping
Warning: True gmin stepping failed
Note: Starting source stepping
Warning: source stepping failed
Note: Transient op started
Note: Transient op finished successfully
```

— and the pseudo-transient fallback that does finish lands on a
**non-physical** solution: `vout_full_v` = −0.075 V, `iload_full_ma` ≈ 0 (the
compliance-limited 50 mA sink is not delivering its commanded current at
all), `iq_full_ua` and `iq_en_ua` both negative. This is the same *class* of
failure `sim/quiescent-current/records/20260918-190801-8a59d23.md`'s own
provenance note documents from this bench's history (a second, unphysical DC
root that a cold Newton-Raphson start or a degenerate homotopy path can
land on) — not evidence that the mechanism is unfixable, but evidence that
starving both branches' bias at once can leave `GMIA`/`GMRM`/`GMSUM` weakly
enough determined, at the corner where the branches' own currents are
already smallest (slow process, cold), that the solver's continuation
methods cannot find the real root and fall back to a spurious one. **This is
exactly the failure mode the curator's complexity rationale on issue #259
warned about**: a change that looks correct at the corners it happens to be
checked against and fails only at a PVT extreme nobody re-checked.

## Alternatives considered (not yet prototyped)

- **Gate the branches' return path (ground side) instead of the supply
  side**, mirroring `Mgme_ss`'s existing NMOS-on-the-return idiom rather than
  adding a new PMOS-on-the-supply one. Might avoid weakening `GMIA`'s own
  bias node the same way, since `Mgme_ss` already demonstrates that this
  idiom converges cleanly when EN-gated; whether it converges cleanly when
  gated by an internal mirror node instead of `EN` is untested.
- **A small bleed resistor from `GMIA`/`GMRM`/`GMSUM` to a fixed rail**, sized
  to keep those nodes weakly but unambiguously determined even with both
  branches starved, trading back a small fraction of the recovered Iq for
  numerical (and possibly physical) robustness at the coldest/slowest
  corner. Not sized or tested here.
- **Do nothing further and leave the adder as a known, documented cost**
  (the status quo `design/ldo_softstart.sch` already states). Always
  available; not preferred, because 1.29 µA is the tightest the ratified Iq
  row has ever been (see "Related" below) and leaves no margin for anything
  else that might need it.

## Decision

**Not made.** This record documents a mechanism with real promise (near-full
recovery of the targeted adder at the binding corner, zero measured cost at
nominal) and a real, corner-specific blocking defect (a non-physical DC
solution at `ss_-40c_2.97v`). Ratifying a topology change on three-of-four
sampled corners, with the fourth non-convergent, would be exactly the kind
of unverified claim `CLAUDE.md` rules out ("no claim without a testbench").
The next attempt should start from one of the two untested alternatives
above, re-run this same four-corner spot check first (cheap: under a minute
of ngspice per corner), and only proceed to the full 81-point
`sim/quiescent-current` grid, the 63-corner `sim/soft-start`/
`sim/soft-start-loop-gain` T1–T7 hand-over transfer, and the 163-point
`sim/soft-start` transient set once a variant converges cleanly across a
first-pass spot check of the grid's extremes.

## Consequences

- No `design/` file changes as a result of this record. `design/
  ldo_softstart.sch`'s SIZING AS BUILT section is corrected in this same
  pull request to name the binding full-load clause (1.29 µA of headroom at
  `ff_125c_3.63v`, not the no-load clause's 1.96 µA) — a documentation
  correction independent of whether or how this mechanism eventually lands —
  and now points at this record.
- Issue #259 stays open for the follow-on engineering this record's
  "Alternatives considered" section names; this pull request is filed as
  `Part of #259`, not `Closes #259`.
- If a follow-on variant does converge cleanly across the grid, `T1`–`T7`
  and the 163-point transient set still need their own full-grid
  re-verification before ratification — this record's four-corner spot
  check substantiates feasibility, not compliance.

## Related

- Issue #259 — this record's origin, and the 1.29 µA/1.96 µA headroom
  correction it also asks for.
- DR-0023 — ratified the cascoded mirror this mechanism builds on top of;
  its rectification-by-cutoff property (the mirror's reference-leg stack
  going into cutoff at hand-over) is the event `GMRM` rising is a
  side-effect of, and what this mechanism's gate signal piggybacks on.
- DR-0026 (PR #258, proposed) — names this issue's Iq adder as the "second
  budget" its own servo amplifier falls back to if it does not fit in
  1.29 µA; this record does not change that budget, since nothing here is
  ratified or implemented in `design/` yet.
- `design/softstart_injection_compensation.md` §3 — the T1–T7 numeric
  targets any change to this element, including this one if it proceeds,
  must be re-measured against.
