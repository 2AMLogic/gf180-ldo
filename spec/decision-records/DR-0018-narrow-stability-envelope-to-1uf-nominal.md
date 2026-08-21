# DR-0018: With compensation-network tuning exhausted, propose closing issue #51's residual gap by spec decision (DR-0016's Candidates 1 and 3), not a further circuit change

- **Status**: proposed -- ratification is the operator's, the same process
  DR-0001, DR-0007, DR-0008, DR-0012 through DR-0017 went through. **Nothing
  in this record is in force until an operator ratifies it, and it proposes
  no `design/` change.** Every count below is re-derived directly from the
  already-committed matrix CSV of the current head loop-stability record --
  no new simulation was run to produce it.
- **Date**: 2026-08-21
- **Decided by**: Builder agent, issue #51 (recommendation only)
- **Builds on**: DR-0016 (the four-candidate trade study this record acts
  on), DR-0017 (confirms the compensation-network-tuning path is exhausted
  at the shipped operating point -- `Cc` -> `BG`, a `Cf` step, and an `Rza`
  re-tune are each a wash or worse once `Mrza`/`Rza` is already shipped),
  DR-0015 (the shipped adaptive shelf and its head record,
  `sim/loop-stability/records/20260807-103351-64249c6.md`, 2930/4536),
  DR-0007 (the held 0 mA envelope decision, whose hold condition this record
  finds satisfied). Supersedes none of them. It converts two of DR-0016's
  four candidates from a trade study into a concrete, ready-to-ratify
  proposal.

## Context

Issue #51 was un-parked to execute DR-0012's Candidate 2 (adaptive
pass-device-replica bias). DR-0014/DR-0015 built and shipped the load-tracking
half of it (`Mrza`/`Rza`), moving the head loop-stability record from
1332/4536 to **2930/4536**. DR-0017, landed earlier in this same issue's
session (PR #145), then measured the two follow-on moves DR-0014/DR-0015
themselves named next -- `Cc`'s return-node move to `BG`, and a `Cf` step --
against the **shipped** topology, and found both to be a wash or a net
regression once `Mrza`/`Rza` is already absorbing most of the same slack:
`Cc` -> `BG` alone loses points in every load column from 0.1 mA up (2930 ->
2821), and a full `Cf` step recovers only 22 of those (2843/4536) against
DR-0014's own estimate of "1.5-2x of `Cc/Cf`". DR-0017's conclusion: the
remaining 1--50 mA/0.33 uF gap needs `f_hi` (the output stage's own
forward-path phase cliff, measured at 0.31 MHz against the roughly 0.76--0.95
MHz DR-0015's closed form requires), not further compensation-network tuning.
`design/` is therefore unchanged by DR-0017, and remains unchanged by this
record.

This record's own attempt to continue past DR-0017 confirmed that the next
engineering step -- raising `f_hi` by increasing the class-AB buffer's
standing current (DR-0015's "ways out" item 1, DR-0016 Candidate 2's
un-attempted half) -- is not something this session can responsibly build and
verify. `sim/loop-stability/testbench/sweep.py --explore` (a single PVT
point, 72 load/cap/ESR sub-points inside one ngspice invocation, documented
at ~30--40 s per DR-0015/DR-0017) did not complete in **8 minutes of
wall-clock time** on the host this session ran on, with `uptime` reporting a
sustained load average of 12--13 on an 8-core machine from unrelated
concurrent tenants (other Loom sweep processes and Rust builds) throughout --
the same class of host-contention DR-0017's own "Reproduction note" already
flags as a 30--80x slowdown risk, reproduced here at a coarser grain before
any circuit change was even made. Attempting the required verification chain
for a buffer-current change (`sim/amp-openloop/` at 81 points, `sim/psrr-dc/`
at 81 points, `sim/amp-selfosc/` at 45 points, and the full 4536-point
`sim/loop-stability/` matrix, likely across more than one candidate sizing)
on this host, in this session, would not produce a trustworthy result inside
any reasonable time budget -- and CLAUDE.md's "verification is the product:
no claim without a testbench" rules out shipping a circuit change without
completing that chain. This record does not attempt it, for the same reason
DR-0013/DR-0014/DR-0017 declined to ship a measurement they could not
complete to a clean, full-matrix result.

DR-0016 (issue #90, `Status: proposed`) already surveyed this exact fork and
recommended, as its first two items, two moves that need **no new
simulation at all** -- both are a re-reading of the already-committed
`20260807-103351-64249c6-matrix.csv`. This record takes DR-0016's own
recommendation, re-derives its numbers independently against that same CSV
(not trusting DR-0016's arithmetic without checking it), and turns them into
a single, concrete, ready-to-ratify proposal so that issue #51's Acceptance
Criteria can be evaluated against an explicit account of every residual
failing point rather than an implied one.

## Independent re-derivation

All numbers below are computed directly from
`sim/loop-stability/records/20260807-103351-64249c6-matrix.csv` (4536 rows,
the current head record, unchanged since DR-0015), grouping by
`iload_ma`/`ceff_uf`/`esr_ohm` and counting `result == PASS`. No `design/`
file and no testbench was touched to produce these counts.

**1. The single nominal-cap, ESR-floored point is 100% clean across the full
0.1--50 mA load axis, better than DR-0016's own conservative claim.**

| `I_load` | `C_eff` = 1 uF, ESR >= 200 mOhm |
|---|---|
| 0 mA | 0/126 |
| 0.1 mA | **126/126** |
| 1 mA | **126/126** |
| 10 mA | **126/126** |
| 25 mA | **126/126** |
| 50 mA | **126/126** |
| **0.1--50 mA total** | **630/630 (100.0%)** |

DR-0016's Recommendation #1 text claims only `1 mA <= I_load <= 50 mA` at
this operating point (following DR-0007's phrasing convention for the
adjacent decision). Re-derived directly, the **0.1 mA column is clean too**
at this cap/ESR combination (126/126) -- so the stronger, fully-verified
claim is 0.1--50 mA, not 1--50 mA. Worst-corner margins inside that set:
phase margin 55.44 deg (`res_ss_-40c_3.63v`, 50 mA), gain margin 11.96 dB
(`res_ss_-40c_2.97v`, 50 mA) -- both comfortably clear of DR-0001's 45
deg/10 dB bars, and DR-0008's resurgence check is clean at 0/630 (worst
-0.2251 dB).

**2. Neither axis alone reaches 100% -- both the cap narrowing and the ESR
floor are required, confirming DR-0016's own reading:**

| Scope | 0.1--50 mA points passing |
|---|---|
| Full cap window (0.33--4.7 uF), ESR >= 200 mOhm | 1584/1890 (83.8%) |
| `C_eff` = 0.33 uF only, ESR >= 200 mOhm | 351/630 (55.7%) |
| `C_eff` = 1.0 uF only, all ESR (>= 1 mOhm) | 1206/1260 (95.7%) |
| **`C_eff` = 1.0 uF only, ESR >= 200 mOhm** | **630/630 (100.0%)** |
| `C_eff` = 4.7 uF only, ESR >= 200 mOhm | 603/630 (95.7%) |

**3. The 0 mA column fails unconditionally, at every cap and every ESR, and
is untouched by either axis above:**

| `I_load` = 0 mA | passing |
|---|---|
| all caps, all ESR | 0/756 |
| `C_eff` = 1 uF, ESR >= 200 mOhm | 0/126 |

This reconfirms DR-0007's original 0 mA finding (536/540 failing on its
pre-DR-0008 3240-point matrix) on the current, DR-0008-admissible 4536-point
matrix: the mechanism DR-0007 derived (`gm_pass` collapsing ~110x between
0.1 mA and 0 mA, against `Rz` and `Cc` bounds that are independently pinned
by the buffer-pole ceiling and the ratified PSRR row) is unchanged by
anything DR-0012 through DR-0017 have since built, because every one of
those changes is load-proportional by construction and 0 mA is where the
load signal that drives them (`V(N1) - V(BG)`, per DR-0015) goes to zero.

## Decision

**1. Recommend narrowing DR-0001's `Stability` row to a single nominal
output-capacitor point with an ESR floor, verified across the full 0.1--50 mA
load axis.** Concretely, the proposed replacement text:

```markdown
| Stability | stable 0.1-50 mA at C_eff = 1 uF nominal (X5R/X7R), ESR >= 200 mOhm; PM >= 45 deg, GM >= 10 dB worst corner (630/630 matrix points, worst 55.44 deg / 11.96 dB, DR-0008 resurgence clean 0/630). The full 0.33-4.7 uF / no-minimum-ESR window is NOT verified: 1584/1890 of its 0.1-50 mA points pass and the shortfall is structural (DR-0015, DR-0017), needing f_hi (buffer bandwidth) to close -- see DR-0016 Candidate 2 and issue #147. 0 mA (no external load) remains outside the envelope per DR-0007. | capless variant (separate design fork) |
```

This is a **narrower** claim than DR-0001's ratified 14.2x cap window and
"no minimum ESR" clause, and DR-0016 is explicit that this is a real
usability cost, not a free lunch: many ceramic X5R/X7R parts at 1 uF sit
under 200 mOhm of ESR on their own, so a consumer would need a
higher-ESR-class part or a deliberate series resistor. It costs **zero**
silicon, **zero** Iq, and **zero** PSRR margin -- the design is completely
unchanged, and the 630/630 result is a re-reading of evidence that already
exists on `main`.

**2. Recommend updating DR-0007's `Status` line to record that its own hold
condition is now met**, on the same admissible evidence DR-0015 already
supplied (`sim/amp-selfosc/records/20260807-105211-64249c6.md` PASS 45/45,
`sim/loop-stability/records/20260807-103351-64249c6.md` 0/4536 DR-0008
resurgence) and this record's own re-derivation (0/756 at 0 mA, all caps, all
ESR, on the current matrix) reconfirms DR-0007's original conclusion on
stronger evidence than DR-0007 itself had when it was written. This does not
ratify DR-0007 -- that is still the operator's call -- it only notes that the
two things DR-0007's hold named as prerequisites ("an `amp-selfosc` pass
against the current netlist, then a loop-stability run that satisfies DR-0008
and may legitimately be cited") both now exist. A corresponding edit is made
to DR-0007's Status section alongside this record, in the same PR.

**3. Do not attempt DR-0016's Candidate 2 (the buffer-bandwidth half) inside
this issue's current session.** It remains the correct, and now the *only*,
in-silicon lever that could recover the 0.33 uF/heavy-load and 4.7 uF/light-load
cells this record's narrowing gives up (1890 - 1584 = 306 points at 0.1--50 mA
alone), with a quantified target (`f_hi` roughly 0.76--0.95 MHz against 0.31
MHz measured, per DR-0015) and a quantified Iq budget (5.19--7.40 uA
against the ratified `Iq < 30 uA` row's headroom, per DR-0015/DR-0016). It is
filed as its own issue (#147, see "Follow-up filed" below) rather than attempted
here, both because DR-0016 itself already recommends scoping it separately
and because this session's own host is demonstrably too contended to run the
required verification chain (81-point `sim/amp-openloop/`, 81-point
`sim/psrr-dc/`, 45-point `sim/amp-selfosc/`, and a full 4536-point
`sim/loop-stability/` matrix, likely more than once) to a trustworthy
result -- a single 72-point single-PVT `--explore` screen did not complete in
8 minutes against a documented ~30--40 s baseline.

**4. This record relaxes no bar.** DR-0001's 45 deg/10 dB bars themselves are
untouched. What is proposed is narrower scope for the verified envelope (a
single cap value and an ESR floor, exactly as DR-0001's own text anticipates
for "a corner that proves unmeetable"), not a weaker bar.

## Alternatives considered

- **Attempt the buffer-bandwidth change anyway, in this session, on a
  reduced verification scope (e.g. `--explore` and `sim/amp-openloop
  --corner-set tt` only, skipping the full matrix).** Rejected: issue #51's
  own Acceptance Criteria were written specifically to stop a partial-pass
  or partially-verified record from closing a ratified stability row (the
  #42/#56 pattern), and DR-0013/DR-0014/DR-0017 all declined to ship a
  measurement they could not complete to a clean, full-scope result for the
  same reason. A circuit change with only a single-PVT screen behind it is
  exactly that pattern.
- **Wait for the host to become less contended and attempt the
  buffer-bandwidth change in the same session.** Considered; not taken.
  There is no bound on how long the shared host stays contended (`uptime`
  showed a stable 12--13 load average from unrelated tenants across the
  session, not a transient spike), and issue #51 has a long history of
  sessions parking mid-attempt (the `robb-studio` stash noted on this issue's
  own thread, 2026-08-08). Filing #147 with a quantified
  target and budget, so the next session does not have to re-derive DR-0015's
  numbers, is a better use of this session than an open-ended wait.
- **Propose the narrowed spec without re-deriving DR-0016's numbers
  independently.** Rejected: this repo's own verification discipline
  ("independent verification performed in this run" is the pattern PR #140
  and others use) applies to reading existing evidence as much as to running
  new simulation -- DR-0016's arithmetic could have been rechecked and found
  wrong, and it was worth the five minutes to confirm it was not (and, in the
  0.1 mA case, to find the claim could be *stronger* than DR-0016 stated).
- **Fold Candidate 3 (0 mA) into the same proposed `Stability` row text as
  Candidate 1, rather than a separate DR-0007 status edit.** Rejected: DR-0007
  already carries the full derivation (area, PSRR-saturation, and Iq bounds
  for why 0 mA is unreachable) and is the record issue #51's own body already
  cites for that cluster; duplicating that derivation into a new record would
  create two sources of truth for the same conclusion. Pointing at DR-0007
  and updating its hold note is the smaller, more honest change.

## Consequences

1. **No `design/` change, no re-verification burden.** Every ratified bench
   (`sim/amp-openloop/`, `sim/psrr-dc/`, `sim/amp-selfosc/`,
   `sim/quiescent-current/`, `sim/enable-shutdown/`) and the head
   `sim/loop-stability/` record are unaffected; nothing here supersedes
   `sim/loop-stability/records/20260807-103351-64249c6.md`.
2. **If recommendation #1 is ratified**, DR-0001's `Stability` row narrows
   from a 14.2x cap window with no ESR floor to a single nominal value with
   a 200 mOhm ESR floor. `sim/loop-stability/testbench/run.sh` continues to
   sweep the full ratified 4536-point matrix unmodified (per DR-0001's own
   convention of never narrowing the testbench itself, only the claimed
   envelope) -- a superseding record would restate the verified subset, not
   change what is measured.
3. **If recommendation #2 is ratified**, DR-0007's `Status` line updates to
   reflect that its hold condition is met; per DR-0016, no new evidence is
   required beyond what DR-0015 and this record already supply.
4. **Issue #51's own residual gap is accounted for, point for point, on the
   current head record**: 630/630 pass under the narrowed envelope, 0/756
   fail at 0 mA and are backed by DR-0007 (this record's recommendation #2),
   and the remaining 1890 - 1584 = 306 points at 0.1--50 mA outside the
   narrowed envelope (the wide-cap/heavy-load and wide-cap/light-load cells)
   are backed by issue #147, with DR-0015's
   quantified `f_hi` target and Iq budget carried forward so that issue does
   not have to re-derive them. This satisfies issue #51's Acceptance
   Criteria's requirement that every residual failing point either pass or be
   backed by a decision record explaining why it is out of scope -- **once an
   operator ratifies recommendations #1 and #2**; until then, both remain
   proposed and issue #51 is not discharged, exactly as DR-0007's and
   DR-0012's own precedent states.
5. **#15 (floorplan/matching) and #16 (post-layout re-run)** still cite issue
   #51 as their dependency; nothing here removes that block, since neither
   recommendation is yet ratified and DR-0015's own consequences section
   already warned #15/#16 not to start from the present compensation
   regardless of when #51 itself closes.

## Follow-up filed

`f_hi` (buffer-bandwidth half of DR-0016's Candidate 2) is filed as **issue
#147** per DR-0016 Recommendation #3, with the quantified target (roughly
triple `f_hi`, 0.31 -> 0.76--0.95 MHz) and Iq budget (5.19--7.40 uA against
the ratified `Iq < 30 uA` row) carried forward from DR-0015/DR-0016, plus this
session's host-contention finding so the next attempt budgets compute
accordingly.
