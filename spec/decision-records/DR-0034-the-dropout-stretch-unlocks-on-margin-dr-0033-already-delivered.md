# DR-0034: The 1.9 dB `DR-0032` was short of arrived with `DR-0033`, not from a compensation change — the pass device goes to W = 2.8 mm and the `< 200 mV` dropout stretch is met

- **Status**: proposed (issue #294 / this pull request). **This record
  proposes no change to any ratified `README.md` row, and relaxes none.**
  Every ratified bar the width change touches — Stability, Dropout, Current
  limit, Thermal, Iq, Area — is re-measured on fresh evidence minted in this
  same pull request and shown to hold. What moves is a *stretch* column that
  was never a gate.
- **Date**: 2026-09-23
- **Decided by**: Builder agent, issue #294 (recommendation only)
- **Builds on**: `DR-0032` (the finding this record answers, and whose
  Decision items 1, 2 and 4 it supersedes), `DR-0033` (the change that
  actually delivered the margin), `DR-0018` (the ratified envelope the margin
  is graded against), `DR-0005` (the ratified current-limit and Thermal rows
  that bound the width from above), `DR-0020` (the dropout measurement),
  `DR-0025` (the per-finger-width model-bin rule the resize has to respect).
- **Supersedes**: `DR-0032` Decision items **1** (`Mpass` stays at 2 mm /
  `Msense` at `W=50u`), **2** (the stretch is re-classified as a compensation
  problem) and **4** (the pass array is settled at 40 unit cells of `W=50u
  nf=1`). `DR-0032` item **3** ("no ratified row moves") is *not* superseded —
  it still holds, and this record re-verifies it. `DR-0032`'s measurements are
  not retracted: every one of them was correct on the design state it was taken
  against, and that state changed one day later.

## Context

`DR-0032` (2026-09-22, issue #139) measured the pass-device width from both
sides and found the two bounds did not overlap. The `< 200 mV` dropout stretch
needed `W ≳ 2.7 mm`; the ratified `GM ≥ 10 dB` of `DR-0018`'s envelope capped
`W` at `≈ 2.5 mm`. It closed with a budget for the gap: **roughly 1.9 dB of
extra gain margin at 50 mA / `C_eff` = 1 µF / ESR = 500 mΩ** would have to be
found first, and it named the `f_hi` / buffer-bandwidth lever of `DR-0016`
Candidate 2 as the only known source — a lever `DR-0019` had already measured
**foreclosed** at the ratified `< 30 µA` Iq allocation. Issue #294 asked
whether that 1.9 dB is available and at what cost, and said plainly that "the
stretch is unreachable without an Iq or envelope decision" would be an
acceptable answer.

It is available. It cost nothing, and nobody had to go looking for it: it
landed on `main` the day after `DR-0032` was written, in a pull request about
**resistor area**.

## Measured: the 1.9 dB is already banked

`DR-0033` re-flavoured `error_amp`'s three zero-DC-current poly resistors
(`Rz`, `Rza`, `Rbufb`) from `ppolyf_u_1k` to `ppolyf_u_3k`, taking ~17 % of the
core-area budget back. The compensation network's *resistance values* were held
constant by construction — only the sheet resistance and therefore the drawn
geometry changed — but the parasitics that come with 3× less poly did not hold
constant, and the loop gained margin.

No new simulation is needed to see it. Both figures below are re-derived
directly from the **already-committed** full-matrix CSVs of two consecutive
head loop-stability records, filtered to `DR-0018`'s ratified envelope
(`0.1–50 mA` × `C_eff = 1 µF` × `ESR ≥ 200 mΩ` × the 63-point PVT grid = 630
points):

| head record | design state | envelope | worst PM | worst GM | binding point |
|---|---|---|---|---|---|
| `20260922-012628-ac57c94` | pre-`DR-0033` | 630/630 | 55.75° | **12.080 dB** | `res_ss_-40c_2.97v`, 50 mA / 1 µF / 500 mΩ |
| `20260923-000113-a406143` | post-`DR-0033`, shipped 2 mm | 630/630 | 55.45° | **14.170 dB** | same point |
| | | | | **+2.090 dB** | |

The first row is exactly the 12.08 dB `DR-0032` cites, so this is a difference
between two committed numbers, not between two reconstructions. **The answer to
issue #294's question is therefore: 4.17 dB of gain margin is available above
the ratified bar at 50 mA / 1 µF / 500 mΩ, 2.09 dB of it new since `DR-0032`,
and the cost of the new part was negative** — `DR-0033` returned core area
rather than spending it, added no standing current, and never touched the
amplifier's Iq allocation. `DR-0019`'s foreclosure is not on this path at all;
the `f_hi` lever remains foreclosed and remains un-pulled.

`DR-0032`'s conclusion was not wrong. It was **stale within a day**, for an
unrelated reason, which is the ordinary hazard of a two-sided bound measured on
a moving design.

## Measured: the width ceiling, re-derived rather than reused

`DR-0032`'s `≈ 2.5 mm` ceiling was bracketed (2.4 mm passed, 2.6 mm failed) on
a nine-point scan. It is re-derived here on the **full** 630-point envelope, at
the current `main`, sweeping `Mpass`'s width with `nf` held at 40 so that the
per-finger width tracks the total (see the Decision for why), and `Msense`
re-scaled to keep the 1/40 replica ratio exact at every point:

| `Mpass` W | per-finger | worst PM (bar ≥ 45°) | worst GM (bar ≥ 10 dB) | `DR-0018` envelope | source |
|---|---|---|---|---|---|
| **2.00 mm (was shipped)** | 50.0 µm | 55.45° | 14.170 dB | **630/630** | committed `20260923-000113-a406143-matrix.csv` |
| **2.80 mm (decided)** | **70.0 µm** | **48.65°** | **11.210 dB** | **630/630** | committed `20260923-132038-a992b52-matrix.csv` |
| 2.88 mm | 72.0 µm | 47.91° | 10.962 dB | **630/630** | envelope-only re-run, not committed |
| 3.00 mm | 75.0 µm | 46.69° | 10.582 dB | **630/630** | envelope-only re-run, not committed |
| 3.20 mm | 80.0 µm | 44.56° | 10.006 dB | **628/630 — FAIL** | envelope-only re-run, not committed |

The two shipped-candidate rows are read off the two *committed* full-matrix
records' own `-matrix.csv`, filtered to the envelope; the three candidate rows
are 630-point envelope-only runs of netlists this repo does not ship, run with
`--no-write` and deliberately **not** minted as records (a head record for an
unshipped netlist would hijack `sim/CHARACTERIZATION.md`'s
most-recent-record-wins row selection — the same reasoning `DR-0032` gives).
Reproduction commands are in Consequences below. A cross-check that the two
extraction paths agree: the decided width's envelope reads 48.65° / 11.210 dB
off the committed CSV and 48.65° / 11.211 dB off the raw per-point `ROW` lines
of an independent envelope-only run — the 0.001 dB is the CSV's rounding.

Two things changed versus `DR-0032`:

- **The ceiling moved from `≈ 2.5 mm` to between 3.00 mm and 3.20 mm.**
  3.00 mm — the width `DR-0032` measured at 8.49 dB and rejected — now passes
  the whole envelope at 10.582 dB. The shift is the same +2.09 dB, to within
  the resolution of a re-run (`DR-0032`: 8.49 dB; here: 10.582 dB).
- **The binding term is no longer gain margin alone.** At 3.20 mm the two
  failing points fail on *phase* margin (44.56° against the 45° bar) while gain
  margin sits at 10.006 dB — 0.006 dB inside its own bar. The two bars now run
  out together, so there is no third lever hiding behind the first.

And the dropout side, measured at each candidate width over the ratified
27-corner dropout grid (`sim/run_corners.py dropout-vs-load --corner-set full`,
worst corner `ss`/125 °C in every case):

| `Mpass` W | worst dropout | vs. the `< 200 mV` stretch | vs. the ratified `< 300 mV` row |
|---|---|---|---|
| 2.00 mm | 267.383 mV | misses at 9/27 corners | passes, 32.6 mV margin |
| 2.68 mm | 201.572 mV | **misses** | passes |
| 2.72 mm | 198.701 mV | clears 27/27, **1.3 mV** | passes |
| **2.80 mm (decided)** | **193.200 mV** | **clears 27/27, 6.8 mV** | **passes, 106.8 mV margin** |
| 2.88 mm | 187.996 mV | clears 27/27, 12.0 mV | passes |
| 3.00 mm | 180.699 mV | clears 27/27, 19.3 mV | passes |
| 3.20 mm | 169.726 mV | clears 27/27, 30.3 mV | passes |
| 4.00 mm | 136.603 mV | clears 27/27, 63.4 mV | passes — but fails `DR-0005` Thermal |

**The two intervals now overlap.** The stretch opens between 2.68 mm (misses at
201.572 mV) and 2.72 mm; the ratified envelope closes between 3.00 mm and
3.20 mm. `DR-0032`'s empty interval is now an open band roughly 2.7–3.1 mm
wide, and 2.80 mm sits inside it with margin on both sides.

## Decision

1. **`Mpass` becomes `pfet_03v3 L=0.28u W=2800u nf=40`** in
   `design/ldo_core.sch` — i.e. **N = 40 unit cells of `W=70u nf=1`**, the same
   N as before with a wider unit cell.
2. **`Xilimit`'s `Msense` becomes `pfet_03v3 L=0.28u W=70u nf=1`**: exactly one
   more of that same unit cell. The 1/40 replica ratio `DR-0005`'s ratified
   current-limit window is built on stays **exact**, and the two devices keep
   **equal per-finger width**, which is what selects the model bin under
   `DR-0025` (70 µm is inside `pfet_03v3`'s widest declared bin, `W/NF` in
   `[10, 100.001] µm`; the bin is unchanged, `.12`).
3. **`nf` stays at 40 rather than rising to 56.** Holding `nf = 40` is what
   makes `Msense` an integer replica of a single unit cell. The alternative —
   keeping the 50 µm unit cell and going to `nf = 56` — would make `Msense`
   1.4 cells, i.e. either a broken integer ratio or a sense device whose
   per-finger width differs from the array it is replicating. Diffusion area
   (`ad`/`as`) is identical either way at even `nf`; only perimeter differs, by
   0.1 %.
4. **The `< 200 mV` dropout stretch is now met, and it is still a stretch.**
   `README.md`'s ratified `< 300 mV` Dropout row, its `< 200 mV` Stretch
   column, and every other ratified row are unchanged by this record. No spec
   value moves.
5. **The `f_hi` / buffer-bandwidth lever stays closed.** `DR-0016`
   Candidate 2 and `DR-0019` are untouched: this record does not open the
   buffer's standing-current question, and nothing here should be read as
   evidence about it.

### Verified at the decided width

All six rows re-measured against the 2.8 mm netlist, on records minted in this
pull request (record-ids in the References section):

| ratified row | bar | measured at W = 2.8 mm | margin | record |
|---|---|---|---|---|
| Stability (`DR-0018` envelope) | PM ≥ 45°, GM ≥ 10 dB, 630 points | 630/630, 48.65° / 11.210 dB, `DR-0008` resurgence clean 0/630 | 3.65° / 1.21 dB | `loop-stability/20260923-132038-a992b52` |
| Dropout @ 50 mA | < 300 mV, 27 corners | 193.200 mV worst (`ss`/125 °C), 27/27 | 106.8 mV | `dropout-vs-load/20260923-141156-33035d7` |
| Dropout stretch | < 200 mV | 193.200 mV worst, **27/27** | 6.8 mV | same record |
| Current limit (`DR-0005`) | 62–95 mA, 63 corners; never engages ≤ 50 mA | 62.0253 … 93.7746 mA, 63/63; never engages | 0.0253 mA at the floor | `current-limit/20260923-141325-33035d79` |
| Thermal (`DR-0005`) | ≤ 346 mW into a `Vout = 0` short | 345.586 mW (`ff`/125 °C/3.63 V) | 0.414 mW | same record |
| Iq | < 30 µA, no load and full load | 28.7153 µA worst (81 points) | 1.28 µA | `quiescent-current/20260923-141210-33035d7` |
| Area | < 0.1 mm² core | 0.0575 mm² (`python3 layout/area_estimate.py`) | 42.5 % | n/a (not a simulation) |

The one *unratified* figure that moves the wrong way is `DR-0001`'s original,
wider cap/ESR window, which `DR-0018` explicitly stopped grading against: over
the full 0.33–4.7 µF window at ESR ≥ 200 mΩ and 0.1–50 mA it goes from
1640/1890 points passing at 2 mm to **1523/1890** at 2.8 mm, and the whole
4536-point `DR-0001` matrix from 2974/4536 to 2790/4536. `README.md`'s
Stability row states that count as measured evidence, so it is updated with
the rest; the ratified *bar* it sits next to is untouched, and the shortfall
is the same structural one `DR-0015`/`DR-0017`/`DR-0019` already attribute to
`f_hi`.

## Alternatives considered

- **Stay at 2.00 mm and book the margin as a negative result.** Rejected. The
  stretch is reachable now, on measured evidence, without relaxing anything;
  recording "we found the margin and declined to spend it" would leave
  `layout/floorplan.md` and `sim/devchar/CONCLUSIONS.md` §1 carrying a width
  rationale (`DR-0032`) that is no longer true, which is worse than either
  moving or not moving.
- **2.72 mm — the narrowest measured width that clears the stretch.**
  Rejected: it clears `< 200 mV` by **1.3 mV** at the binding corner, and the
  next width down (2.68 mm) misses at 201.572 mV. A 1.3 mV margin on a knee
  measurement is inside the measurement's own reproducibility, so a width
  chosen there would be a coin flip rather than a decision.
- **2.88 mm and 3.00 mm — more dropout margin.** Rejected as a bad trade in
  the other direction: both spend the ratified `GM ≥ 10 dB` row down below
  1 dB (10.962 dB and 10.582 dB), and 3.00 mm leaves only 1.69° of phase
  margin. Buying stretch-column margin with ratified-row margin is the trade
  `DR-0032` refused, and refusing it is still right — the bound moved, the
  principle did not. 2.80 mm keeps > 1 dB and > 3.5° on the ratified row while
  clearing the stretch by 3.4 %.
- **3.20 mm or wider.** Rejected: measured failing, 628/630, on phase margin.
- **4.00 mm — `sim/devchar/CONCLUSIONS.md` §1's device-level recommendation.**
  Still rejected, on `DR-0005`'s Thermal row exactly as `DR-0032` found
  (346.049 mW against ≤ 346 mW). Nothing in this record changes that: the
  clamp's inverse-fold still grows with pass-device width, and the Thermal
  margin at the decided 2.8 mm is 0.414 mW, down from 0.785 mW at 2 mm.
- **Keeping the 50 µm unit cell (`nf = 56`).** Rejected — see Decision item 3:
  it breaks the integer `Msense` replica that `layout/floorplan.md` §3.2 and
  `DR-0005`'s current-limit derivation both rest on.
- **Pulling the `f_hi` lever anyway, to buy headroom above 3.2 mm.** Not
  attempted, and deliberately so. It is `DR-0019`'s foreclosed lever, it costs
  quiescent current the ratified `< 30 µA` row does not have, and there is no
  ratified row asking for a width above 3.2 mm.

## Consequences

- **The Dropout row's stretch column is met for the first time**, at 27/27
  corners with 6.8 mV of margin. It remains a stretch: nothing is now *graded*
  against 200 mV, and `sim/dropout-vs-load`'s automated check still gates on
  the ratified 300 mV.
- **Thermal margin halves, from 0.785 mW to 0.414 mW.** `DR-0005`'s ceiling
  was set as the 2 mm measurement rounded up to the next milliwatt, so this row
  has been thin by construction since it was ratified; it is now thinner. Any
  future widening must re-measure it, and the 4 mm device remains excluded by
  it.
- **The pass array's unit cell changes from 50 µm to 70 µm at the same N = 40.**
  `layout/floorplan.md` §3.1/§3.2's unit cell, §5's model-bin census row for
  `XMpass`/`XMsense`, §1's decided-width row and §6's area column all move with
  it. Every EM / IR / thermal-spreading number in §3.3–§3.5 *improves* with
  width, so the 2 mm columns those sections are written against are now
  conservative rather than wrong.
- **`DR-0025`'s per-finger census moves but its rule does not.** `XMpass` and
  `XMsense` go from 50 µm to 70 µm per finger; still zero instances above the
  100.001 µm bin edge, so the invariant that record ratifies is intact.
- **`DR-0001`'s original, wider cap/ESR window degrades**, from 1640/1890 to
  1523/1890 at 0.1–50 mA / ESR ≥ 200 mΩ (2974/4536 to 2790/4536 over the whole
  original matrix). `DR-0018` ratified the narrower envelope precisely because
  that window was already not verified and its shortfall is structural; this
  record spends some of the unratified surplus and says so, in `README.md`'s
  Stability row as well as here. Anyone who later re-opens the wider window is
  re-opening it against these numbers, not against the 2 mm ones.
- **Every committed `sim/` record that snapshots `design/netlist/ldo_core.spice`
  is now STALE**, including rows this pull request does not re-run.
  `sim/CHARACTERIZATION.md` is regenerated to say so rather than to hide it.
- **The DC continuation ladder moved, and the record now says so.** With
  issue #301 / #314's rung attribution in place, the 81-point
  `quiescent-current` grid solves on `dynamic-gmin` × 71 / `true-gmin` × 10 at
  2.8 mm — no corner reaches source-stepping, where `ss_-40c_2.97v` sat on the
  2 mm DUT. That is a numerical-path observation, not an electrical claim, and
  nothing here is graded on it; it is recorded because #301's whole point is
  that such moves used to be invisible.
- **`DR-0032` stops being the live width rationale** and becomes the record of
  how the bound was found, and of the state in which it was true. Its
  measurements are left untouched per the append-only rule; its Status line
  points here.
- **The lesson is about coupling, not about resistors.** A change whose stated
  purpose was core area moved a ratified loop-margin row by 2.09 dB. This one
  happened to move it the right way. A two-sided bound like `DR-0032`'s should
  be re-derived, not cited, whenever anything in the forward path has changed —
  which is why this record re-ran the ceiling instead of reusing `≈ 2.5 mm`.

### Reproduction

Every number above is reproducible from a clean checkout of this branch. The
four shipped-width records are minted by:

```
python3 sim/loop-stability/testbench/sweep.py -j8            # full 4536-point matrix
python3 sim/run_corners.py dropout-vs-load --corner-set full --subset-reason '...'
python3 sim/run_corners.py quiescent-current --corner-set full
./sim/current-limit/testbench/run.sh                         # record written by hand
python3 sim/build_characterization_report.py > sim/CHARACTERIZATION.md
```

The `DR-0018` envelope verdict is not a separate run: it is the committed
`-matrix.csv` filtered to `0.1 ≤ I_load ≤ 50 mA`, `C_eff = 1 µF`,
`ESR ≥ 200 mΩ` (630 of the 4536 rows), which is exactly what
`sim/build_characterization_report.py` does for the Stability row.

For a candidate width `W` (not shipped, not recorded): set `Mpass` to
`L=0.28u W=<W>u nf=40` in `design/ldo_core.sch` and `Msense` to
`L=0.28u W=<W/40>u nf=1` in `design/ldo_ilimit.sch`, run
`python3 design/netlist.py`, then

- gain/phase margin over the ratified envelope:
  `python3 sim/loop-stability/testbench/sweep.py --no-write --loads-ma 0.1 1 10 25 50 --caps-uf 1.0 --esrs 0.2 0.5`
- dropout: `python3 sim/run_corners.py dropout-vs-load --corner-set full --no-write`
- thermal / current limit:
  `NO_RECORD=1 CORNERS=ff TEMPS=125 SUPPLIES=3.63 ./sim/current-limit/testbench/run.sh`
- area: `python3 layout/area_estimate.py --pass-width <W>`

and restore the two device lines afterwards (`python3 design/netlist.py --check`
must read clean before anything is committed).

## References

- Issue #294 — the question this record answers; issue #139 / `DR-0032` — the
  finding it starts from
- `spec/decision-records/DR-0033-poly-resistor-flavour-is-set-by-dc-current-not-by-area.md`
  — the change that delivered the 2.09 dB
- `spec/decision-records/DR-0018-narrow-stability-envelope-to-1uf-nominal.md` —
  the ratified envelope; `DR-0005` — the ratified current-limit and Thermal
  rows; `DR-0020` — the dropout measurement; `DR-0025` — the per-finger bin rule
- `spec/decision-records/DR-0016-compensation-pareto-front.md`,
  `spec/decision-records/DR-0019-buffer-standing-current-blocked-by-amp-iq-allocation.md`
  — the `f_hi` lever this record leaves closed
- Pre-existing evidence re-read for the +2.09 dB claim (no new simulation):
  `sim/loop-stability/records/20260922-012628-ac57c94-matrix.csv`,
  `sim/loop-stability/records/20260923-000113-a406143-matrix.csv`
- Records minted alongside this one, all against the 2.8 mm DUT
  (`design/netlist/ldo_core.spice` sha256 `5bfa966c…`):
  - `sim/loop-stability/records/20260923-132038-a992b52.md` (+ `-matrix.csv`) —
    full 4536-point matrix; its `Supersedes` field names the 2 mm head record
    `20260923-000113-a406143` as the record it replaces as *head*, not as a
    correction: nothing in that record is retracted
  - `sim/dropout-vs-load/records/20260923-141156-33035d7.md` — 27/27
  - `sim/quiescent-current/records/20260923-141210-33035d7.md` — 81/81
  - `sim/current-limit/records/20260923-141325-33035d79.md` — 63/63, hand-written
    per this bench's convention
  - The loop-stability record's id carries the pre-rebase branch sha
    (`a992b52`) because it was run before this branch was rebased onto
    `origin/main`'s harness commit (#314, which does not touch
    `sim/loop-stability`'s own driver). Its frozen netlist snapshot is
    byte-identical to `design/netlist/ldo_core.spice` as committed here, which
    is what the freshness check and every claim above actually rest on.
- `layout/floorplan.md` §§1, 3.1–3.2, 5, 6 — the layout-side half of the same
  decision
