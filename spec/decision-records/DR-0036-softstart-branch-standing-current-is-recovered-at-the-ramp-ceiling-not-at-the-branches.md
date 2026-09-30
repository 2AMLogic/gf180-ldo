# DR-0036: the soft-start injection branches' standing current is recovered at the ramp ceiling, not at the branches — branch-supply gating converges, and still loses

- **Status**: proposed 2026-09-30 (issue #259 / this pull request). **This
  record proposes no topology.** It closes out one line of attack on issue
  #259 — gating the FB-injection transconductor's degeneration branches — by
  measuring it head-to-head, on one tree and one host, against the mechanism
  `DR-0035` already proposes for a different reason, and recording that the
  second mechanism dominates the first on all three axes the first was
  supposed to trade between. It is filed in the style of `DR-0009` /
  `DR-0010` / `DR-0011` / `DR-0029`: a **negative result**, so the next agent
  does not re-derive it a fourth time.
  **This record changes no `design/` netlist or topology.** Every number below
  was measured with the committed testbenches unmodified and the prototype
  netlists supplied as `--dut-netlist` swaps out of the git-ignored
  `sim/.work/`, exactly as `DR-0035` did; `git diff origin/main...HEAD --
  design/netlist` is empty, and the only `design/` edit in this pull request
  is a prose update to `design/ldo_softstart.sch`'s Iq note.
  **No ratified threshold is changed, proposed to be changed, or waived.**
- **Date**: 2026-09-30
- **Decided by**: agent-builder (issue #259) — **recommending**, not deciding.
  The Iq-versus-PSRR preference call this record informs is issue #303, which
  is `loom:operator-only` / `loom:operator-decision` on purpose.
- **Supersedes nothing.** `DR-0029` stands in full; this record answers the
  "next attempt" paragraph `DR-0029`'s *Decision* section left open.

## Context

Issue #259 asks for the ~7 µA of settled-state Iq that `design/
ldo_softstart.sch`'s two `VIN`-referenced, resistor-degenerated PMOS branches
(`Rgma_ss`/`Mgma_ss`, `Rgmb_ss`/`Mgmb_ss`) burn forever after hand-over.
`DR-0023`'s cascoded mirror rectifies the element's *output*; the branches'
own bias is one node upstream of the rectification event and does not switch
off, so the element stands ~2·Ia of DC current in a state where it is doing no
work.

Three attempts have been made at the branches themselves:

1. **`DR-0029`** (merged, negative/partial): one PMOS switch `Mgmg_ss` between
   `VIN` and a new shared node `VING` that both degeneration resistors move
   onto, gated by `GMRM` — the mirror's own reference-leg diode node, so the
   switch closes as a side effect of `DR-0023`'s ratified cutoff event rather
   than off a new threshold. Recovered 1.8–7.0 µA at three of four sampled
   corners; **did not converge to a physical DC solution at
   `ss_-40c_2.97v`**.
2. **`DR-0028` / PR #267** (closed unmerged 2026-09-30 at the operator's
   direction): the same switch plus a 450 kΩ `ppolyf_u_3k` bleed `Rgmg_ss`
   permanently across it, which bounds the regenerative starvation loop that
   made (1) non-convergent. Full grids; Judge-approved; held for human merge;
   closed with *"`DR-0029` stands; `DR-0028` is not adopted."*
3. **Issue #303** (`loom:operator-decision`) recorded why the trade is a human
   call rather than an engineering one: measured on `sim/psrr-vs-freq`, a bench
   **not** in PR #267's evidence base, the mechanism costs 5–7 dB of PSRR at
   the two corners the ratified `> 50 dB @ 1 kHz` row (`DR-0004` amendment A7)
   **already fails**. `DR-0031` §2.3 gives the mechanism: interposing any
   device between `VIN` and the branches puts `VING` below `VIN` and **adds**
   `(VIN − VING)` to the forward bias standing across the mirror's two-high
   weak-inversion reference stack, whose residual — and that residual's supply
   slope, which is what PSRR sees — is exponential in it.

Meanwhile `DR-0035` (proposed 2026-09-23, issue #302) attacks the *same*
standing current from the opposite end, for the PSRR row's sake rather than
Iq's: reference `Mtop_ss`'s ramp ceiling to `VIN` instead of to `VREF`, so the
settled `V(SSR)` rides the supply, the stack's forward bias stops containing
`VIN`, and — because both branch gate references rise with the ceiling — the
branches starve themselves once the element has released. `DR-0035`'s own
Cross-consequences section says branch gating "is not needed" if it lands, and
explicitly defers to #259/#303 rather than pre-empting them.

**That deferral is what this record discharges.** The two mechanisms had never
been measured against each other on one tree; PR #267's numbers are against
`main` at `8a59d23` (2026-09-18) and `DR-0035`'s against `a6c95f8`
(2026-09-23), and `main` has since taken `DR-0033`'s resistor-flavour change
(#306) and `DR-0034`'s 2.8 mm pass device (#316), both of which move Iq.

## What was measured

One tree (`origin/main` at the head of this branch), one host, one ngspice
(`ngspice-46`, sha256 `c874869b…`), one PDK pin (`gf180mcuD @
c6d73a35f524070e85faff4a6a9eef49553ebc2b`), committed testbenches, `-j 2`.
Three DUTs:

| DUT | what it is |
|---|---|
| **baseline** | `design/netlist/ldo_core.spice` as committed on `main` |
| **gated** | baseline + `DR-0028`'s two devices, byte-identical to PR #267's head: `XMgmg_ss VING GMRM VIN VIN pfet_03v3 L=0.5u W=10u` and `XRgmg_ss VING VIN VSS ppolyf_u_3k r_width=1u r_length=150u`, with `Rgma_ss`/`Rgmb_ss` re-terminated `VIN` → `VING` |
| **ceiling** | baseline + `DR-0035`'s three lines verbatim: `XRceil_ss VIN VCEIL VSS ppolyf_u_3k r_width=1u r_length=1208u`, `Fceil_ss VCEIL VSS Vbsense_ss 1.0`, and `Mtop_ss`'s gate moved `VREF` → `VCEIL` |

### 1. Iq — `sim/quiescent-current`, full 81-point grid, all three PASS 81/81

Binding corner `ff_125c_3.63v`, binding clause full load (#249):

| clause | baseline | **gated** | **ceiling** |
|---|---|---|---|
| `iq_en_ua` (no load) | 27.3882 | **22.2696** (−5.119) | **22.2402** (−5.148) |
| `iq_full_ua` (full load) | **28.7153** | **23.7329** (−4.982) | **23.4456** (−5.270) |
| headroom to the ratified < 30 µA, full-load clause | **1.285 µA** | 6.267 µA | **6.554 µA** |

Over the whole grid: gated falls at **79 of 81 points, is flat at 2 and rises
at none** (largest fall −5.119 µA `iq_en` at `ff_125c_3.63v`, −5.014 µA
`iq_full` at `sf_125c_3.63v`). Ceiling falls further at the binding clause but
falls at only 65 and **rises at 16 of 81 points**, worst **+0.4454 µA
`iq_full`** at `res_ff_-40c_2.97v` — a cold, low-supply corner whose absolute
`iq_full_ua` is 13.4158 µA, i.e. 16.6 µA inside the bound; every one of the 16
is a 2.97 V point and the next four are +0.367/+0.340/+0.330/+0.330 µA. That
is the one axis on which gated is the better of the two, and it is not close to
binding.

**`DR-0029`'s blocking defect does not reproduce.** `ss_-40c_2.97v` solves on
the gated DUT (via `source-stepping`) with `iq_en_ua` = 8.89913 µA,
`iq_full_ua` = 8.81345 µA, `vout_full_v` = 1.79948 V — **identical to the
baseline to all six printed digits**. PR #267's own post-merge re-run reported
this corner as `ERROR`; on this tree, at `-j 2`, it does not. That is a real
correction to the record and is the reason this comparison was worth running
at all rather than closing #259 on the strength of the prior `ERROR` alone.

### 2. PSRR — `sim/psrr-vs-freq`, the three corners issue #303 measured

Ratified bar `> 50 dB @ 1 kHz` (`DR-0004` A7). `psrr_1k_db`:

| corner | baseline | **gated** | **ceiling** |
|---|---|---|---|
| `ff_125c_3.63v` | 29.4286 FAIL | **24.2278 FAIL** (−5.201) | **61.8942 PASS** (+32.466) |
| `sf_125c_3.63v` | 38.5728 FAIL | **31.4667 FAIL** (−7.106) | **59.5967 PASS** (+21.024) |
| `fs_125c_3.63v` | 67.4848 PASS | 66.8895 PASS (−0.595) | 67.7593 PASS (+0.275) |
| verdict | FAIL | **FAIL, worse** | **PASS** |

Issue #303's measurement **reproduces on today's `main`** to within 0.02 dB
(#303 read 29.4268 / 38.5620 / PR-head 24.2267 / 31.4624 against `a6c95f8`;
this run reads 29.4286 / 38.5728 / 24.2278 / 31.4667), so the 5–7 dB cost is
not an artifact of the tree it was first found on. `DR-0035`'s 59.5967 dB at
`sf_125c_3.63v` also reproduces to four decimals.

### 3. Settled output accuracy — same 81-point grid, worst corner

Error of `vout_full_v` against the 1.800 V target, worst over the grid (all at
`ff_125c_3.63v`), against the ratified ±36 mV (±2 %) allocation:

| | baseline | **gated** | **ceiling** |
|---|---|---|---|
| worst settled error | −6.430 mV (18 %) | **−11.670 mV (32 %)** | **−1.170 mV (3 %)** |
| `vout_full_v` spread over the grid | 0.329 % | 0.620 % | **0.037 %** |

### 4. T1–T5 hand-over transfer — 63 corners, `handover_t15.py`, baseline vs gated

Re-measured on today's `main` (the committed record `sim/soft-start/records/
20260918-190207-8a59d23.md` predates #306/#316); the gated column is the run
this branch's own reverted prototype commit produced at 19:45 UTC.

| target | baseline | gated | newly-failing corners |
|---|---|---|---|
| T1 (`I_inj` ≤ 50 nA above `VREF`) | 1/63 | **12/63** | none |
| T2 (`I_inj(0)` = 6.00 ±0.10 µA) | 0/63 | 0/63 | none |
| T3 (gm = −5.00 µA/V ±5 %) | 0/63 | 0/63 | none |
| T4 (release at `V(SSR)` = 1.200 V) | 1/63 | **12/63** | none |
| T5 (loop in regulation everywhere) | **63/63** | **63/63** | none |

Worst-case movements: `I_inj` at `VREF` 35.27…1432.95 → 16.77…1473.78 nA,
release `V(SSR)` 1.200…2.025 → 1.200…2.100 V, settled `Vout` error (this
bench's own, lighter-load number) −1.780…−0.500 → −2.470…−0.500 mV, gm
−4.530…−3.522 → −4.622…−3.455 µA/V, `I_inj(0)` 4.9850…5.8065 → 4.9701…5.7922
µA. Every one of those matches PR #267's record to the printed digit. **T1–T5
are not what blocks branch gating**, and the record says so explicitly so the
next reader does not look for the problem there. T6/T7 are small-signal and
were not re-run here (PR #267 measured ΔPM 0.00°, ΔGM 0.00 dB, `FB` budgets
identical); neither was the 163-point transient set, for the reason in
*Consequences*.

## Decision (recommended, not made)

**Stop working the branches. `DR-0029`'s "next attempt should start from one of
the two untested alternatives" is discharged as follows: the bled variant
(alternative 2) works numerically — the convergence defect is gone — and is
still the wrong mechanism, because the current it recovers is available from
`DR-0035`'s ramp ceiling in larger measure, with 32 dB more PSRR instead of
5 dB less, and with 5.5× less settled-accuracy cost.** Issue #259's recovery
should ride on issue #302 / `DR-0035` rather than carry a mechanism of its own.

Stated as the one-line comparison the operator's #303 decision needs:

> At the binding corner and clause, gating buys **4.982 µA** of Iq for
> **5.201 dB** of an already-failing ratified PSRR row and **5.24 mV** of
> settled accuracy. The ramp ceiling buys **5.270 µA** — more — and *pays*
> −32.466 dB (i.e. the row passes) and −5.26 mV (i.e. the error shrinks).
> There is no axis on which gating is the better purchase except a +0.45 µA
> cold-corner rise 16.5 µA inside the bound.

The remaining reason to gate the branches would be to recover Iq **on top of**
the ceiling. That is not measured here and is not recommended blind: both
mechanisms act on the same forward bias across the same reference stack, from
opposite ends, and #303's scope line already says they must be re-derived
together rather than stacked — "pair it with whatever closes #302 so the two
do not fight."

## Alternatives considered

- **Re-open `DR-0028`'s topology on the strength of the convergence fix**
  (what this branch's reverted commit `1b256142` did, 29 minutes after the
  operator closed PR #267). Rejected. The convergence `ERROR` was one of three
  reasons the PR was closed; the other two — `DR-0029` standing on `main`, and
  the PSRR cost that #303 holds for a human — are untouched by it, and §2 above
  confirms the PSRR cost on today's tree. An agent does not overturn an
  operator's stated direction by re-running the part of the evidence that
  favours it.
- **Gate the branches' return path instead of their supply** (`DR-0029`'s
  untested alternative 1, mirroring `Mgme_ss`'s NMOS-on-the-return idiom).
  Not prototyped, and the record notes why it is unpromising as posed rather
  than leaving the next agent to find out: post-release the distinguishing
  node is `GMRM` **rising** toward `VIN`, and an NMOS on the return needs a
  gate that **falls**. The cell has no such node — `GMIA` still carries Ia,
  `GMSUM` also rises, and `GMOD` only falls to ≈ `V(FB)` = 1.2 V, comfortably
  above `Vth`. Synthesising an inverted `GMRM` costs devices and re-introduces
  a threshold on the pre-release path, which `DR-0023` rules out. Note the
  *sign* of its PSRR effect would be favourable (raising `GMVSS` raises
  `GMSUM`, shrinking `VIN − V(GMSUM)`) — so if a clean falling gate signal
  ever exists, this direction is worth re-opening.
- **Raise the degeneration resistors** (200 kΩ → ~600 kΩ) as a sizing change
  rather than a topology one. Closed by derivation: degeneration sets
  gm ≈ 1/R directly, so the standing current and the ratified injection
  transconductance (`DR-0023`'s 5.0e-6 = 1.5/`Rtop` **ratio**, T3) scale
  together. There is no version of this that keeps T3 and cuts the current.
- **Size `Mtop_ss`'s ceiling instead of re-referencing it.** Closed by
  `DR-0031` §4, which sweeps that lever to the PDK's own model-bin extremes
  (`L = 50 µm` = `lmax`, `W = 0.22 µm` = `wmin`) and still lands 4.115 dB
  short.
- **Leave the adder as a documented cost.** Still available, and now strictly
  worse than waiting for #302: `main`'s own binding headroom is 1.285 µA
  measured here, and `DR-0026`'s servo needs to fit inside it.

## Consequences

- **Issue #259 does not close on this record.** Its acceptance criteria ask
  for a mechanism with full-grid Iq, T1–T7 and 163-point transient evidence;
  this record ships no mechanism, so criteria 2 and 3 are not discharged here
  and the 163-point transient set was deliberately not re-run (there is
  nothing to re-run it against). Those criteria transfer intact to issue
  #302's own acceptance set, where they are already listed. #259 should be
  parked on #302 (and on the #303 decision), not closed.
- **Issue #303's decision is now a comparison rather than a cost.** It can be
  answered "no — take #302 instead" on measured numbers from one tree, without
  anyone having to reconcile `8a59d23` against `a6c95f8`.
- **`DR-0029`'s convergence finding is corrected, not retracted.** Its
  un-bled prototype's failure at `ss_-40c_2.97v` stands as measured; what this
  record adds is that the bleed fixes it, on today's `main`, at `-j 2`, with
  that corner's Iq unchanged to six digits. Anyone re-opening the branch-gating
  line should start from that fact and from §2, not from the `ERROR`.
- **A harness gap is recorded rather than worked around silently.**
  `sim/run_corners.py` accepts `--dut-netlist`, which is why §1–§3 could be
  measured without touching `design/`. `sim/soft-start/testbench/
  handover_t15.py` and `run.sh` have no equivalent, so §4's gated column had
  to come from a run taken while the prototype was committed, and the ceiling
  DUT has **no** T1–T5 column here at all. Any future A/B of this element on
  the hand-over or transient benches needs that override first.
- **Nothing in `main`'s `design/` changes.** `design/ldo_softstart.sch`'s Iq
  note is updated in this pull request to carry today's measured baseline
  (27.3882 / 28.7153 µA at `ff_125c_3.63v`, 1.285 µA of headroom) and to point
  at this record, replacing its forward reference to a `DR-0029` mechanism
  that is now recommended against. `sim/CHARACTERIZATION.md` is unaffected: no
  `sim/` record is minted, because a record whose netlist snapshot is not a
  committed design state would make the report state a prototype's Iq as the
  design's.

## Related

- Issue #259 (this record's origin), issue #302 (`DR-0035`'s implementation),
  issue #303 (`loom:operator-decision`, the trade this record informs).
- `DR-0029` — the branch-gating negative result; §1 corrects its convergence
  finding and its *Decision* section is what this record discharges.
- `DR-0028` / PR #267 (closed unmerged) — the bled variant measured here as
  "gated"; device values identical.
- `DR-0035` — the mechanism recommended instead; §1–§3 reproduce its §2.3 and
  its PSRR numbers on a later tree.
- `DR-0031` §2.3 / §7 — why anything between `VIN` and the branches costs
  PSRR, and the prediction §2 confirms.
- `DR-0023` — the ratified cascoded mirror and its rectification-by-cutoff,
  unaffected by this record.
- `DR-0004` amendments A6 (Iq) / A7 (PSRR) — the two ratified rows the trade
  is between; neither is proposed to change.
- `design/softstart_injection_compensation.md` §3 — T1–T7's numeric targets,
  four of which §4 re-measures.
