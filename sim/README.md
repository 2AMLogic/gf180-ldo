# sim/ — evidence record format

This directory holds simulation testbenches and their results. Results are
**append-only evidence**: once a record is written, it is never edited or
deleted. A re-run — even one that corrects a mistake — mints a new record
with a new ID; a correction references the record it supersedes rather than
overwriting it in place.

This convention exists because CLAUDE.md commits this repo to two rules that
need a concrete schema to be enforceable:

- **Verification is the product.** No claim without a testbench. Every
  recorded result carries the full PVT corner matrix (−40/27/125 °C, ±10%
  supply, process corners) unless the record explicitly states why a subset
  was used.
- **`sim/` is append-only evidence.** Re-runs get new records; records are
  never edited or deleted.

## Provenance note (checked at build time, 2026-07-30)

This convention mirrors the ratified `sim/README.md` on `2AMLogic/gf180-bandgap`
`main` (landed via their PR #22, merged 2026-07-30). At the time this doc was
written, bandgap's harness PR (#23, "Stand up the ngspice + gf180mcu PVT
simulation harness") was still **open and unmerged**, and it writes evidence
as a machine-readable JSON/CSV pair under `sim/results/<tb>/` rather than the
Markdown records described below — i.e. it is a *competing* scheme that has
not yet been reconciled with the ratified Markdown convention. Since the
Markdown convention is what is currently ratified on bandgap `main`, this
repo adopts it as-is (see "LDO-specific extensions" below for the one place
this repo diverges, with rationale). If bandgap later reconciles #23 against
this convention (or supersedes it via a decision record), re-check this doc
against bandgap `main` and update accordingly — do not let the two repos'
evidence formats silently drift apart, since cross-block tooling and review
uniformity is the whole point of matching.

## Directory / naming convention

Each testbench topic gets its own experiment directory:

```
sim/
  <experiment-slug>/                 # e.g. dropout-vs-load, psrr-dc, startup, mc-untrimmed
    testbench/                       # testbench netlist(s) / xschem export used
    netlist-snapshots/
      <record-id>.spice              # frozen DUT netlist used for this record
    corners/
      <record-id>/
        <corner-id>.log              # raw ngspice output per PVT point
                                      # e.g. ss_-40c_2.97v.log
    records/
      <record-id>.md                 # append-only summary record
```

- **`<experiment-slug>`** — short, descriptive, kebab-case name for what is
  being verified (`dropout-vs-load`, `psrr-dc`, `startup`, `mc-untrimmed`,
  ...). One directory per distinct claim being tested, not per run.
- **`<record-id>`** — unique and traceable:
  `<YYYYMMDD>-<HHMMSS>-<short-git-sha>` (e.g. `20260729-153000-1a7ef75`).
  Re-runs simply mint a new `<record-id>`; nothing under `records/` is ever
  edited in place. The same `<record-id>` ties together the netlist snapshot,
  the raw per-corner logs, and the summary record for one run.
- **`<corner-id>`** — `<process-corner>_<temp>c_<supply>v.log`, e.g.
  `ss_-40c_2.97v.log`, `tt_27c_3.3v.log`, `ff_125c_3.63v.log`. For claims that
  are also load-conditioned (see "Operating conditions" below), the load
  point may be appended, e.g. `ss_-40c_2.97v_50ma.log`, when a single record
  sweeps more than one load current within the same corner matrix.
- **`testbench/`** is not versioned per record — it holds the current
  testbench netlist(s)/xschem export(s) used to generate records. If the
  testbench itself changes in a way that could affect comparability across
  records, note that in the new record's summary (e.g. under Claim or a
  free-text note).

## Summary record format

Each run produces one `records/<record-id>.md` file with the following
fields:

- **Record ID** — the `<record-id>` for this run (matches the filename and
  the corresponding `netlist-snapshots/` / `corners/` subdirectory).
- **Claim** — which spec parameter/line this record substantiates (reference
  the ratified spec, e.g. `spec/<file>.md#<anchor>`, once ratified specs
  exist — see #1). Placeholder anchors are acceptable until #1 ratifies.
- **Netlist provenance** — `schematic` (`design/...`) or `extracted`
  (post-layout, `layout/...`). Required so post-layout re-runs are
  distinguishable from the original schematic-level record.
- **Corner matrix run** — explicit list of (process corner, temperature,
  supply) points actually executed. Must be the full PVT matrix from
  CLAUDE.md (−40/27/125 °C, ±10% supply, process corners) unless the record
  states why a subset was used.
- **Operating conditions** *(LDO-specific — see below)* — load current or
  load profile, output capacitor value + ESR range, and enable state.
  Required whenever the claim depends on load or the output network, i.e.
  most LDO spec lines (dropout, load/line regulation, stability, transients,
  startup). Omit only for claims that are provably load-independent (e.g. a
  pure reference-voltage TC check with the output disconnected), and say so.
- **Statistical convention** (when applicable, e.g. Monte Carlo mismatch
  analysis) — N samples and sigma level reported. Used for distribution
  claims that are not a per-corner pass/fail (e.g. reporting a spread against
  the untrimmed spec).
- **Result** — per-corner pass/fail, plus an overall pass/fail against the
  ratified spec value. For curve-shaped claims (e.g. PSRR vs frequency,
  transient step response) that are checked against a single spec point
  within a sweep (e.g. "PSRR ≥ 40 dB @ 1 kHz"), the Result states the value
  extracted at that spec point plus pass/fail against it; the full curve/
  waveform data lives in the raw log under `corners/`, referenced from
  Links. A record MAY report more than one spec point extracted from the
  same sweep (e.g. PSRR at 1 kHz and 100 kHz) as separate line items under
  Result, each with its own pass/fail — the sweep is run once, but every
  claim it substantiates gets an explicit, unambiguous verdict.
- **Links** — paths to the testbench file(s), the frozen netlist snapshot,
  and the raw per-corner logs used to produce this record.
- **Timestamp / author** — when the record was created and who (human or
  agent) created it.
- **Supersedes** (optional) — the prior `<record-id>` this record supersedes,
  for corrections or for a post-layout extracted re-run that reports a
  schematic-vs-extracted delta against the schematic-level record. Mirrors
  the status/supersession language proposed for `spec/` decision records
  (see #6), so both conventions read as one house style.

## LDO-specific extensions (where "match bandgap" ends)

Bandgap's corner matrix is process/temperature/supply only — a bandgap
reference has no load pin. An LDO's spec lines are additionally load- and
output-network-conditioned (dropout @ 50 mA; load regulation 1–50 mA; line
regulation; stability across 0–50 mA load with a 1 µF ± ESR output cap
range; startup into full load, minimum load, and current limit; PSRR and
transient response, both load-dependent). A PVT corner alone does not fully
specify one of these claims — the **Operating conditions** field above
closes that gap so a claim like "dropout < 300 mV @ 50 mA at ss/125 °C/
2.97 V" is fully specified by the record: process/temp/supply come from
Corner matrix run, load/cap/enable come from Operating conditions. This is
the one deliberate divergence from the bandgap convention; the field is
additive (records with no load dependency simply state N/A), so it does not
break parity for claims that don't need it.

## Append-only rule

`records/*.md` files are never edited or deleted after creation. A re-run or
a correction always creates a new record with a new `<record-id>`. If it
corrects or replaces a prior result, it references that prior record via
**Supersedes** rather than overwriting it. This applies even to typo fixes —
the append-only guarantee is what makes `sim/` usable as an evidence trail;
"fixing" an existing record in place would defeat that.

## Interim evidence note (for #4, device characterization)

#4 (characterizing gf180mcu devices for the LDO — pass FETs, resistors,
caps) is in flight and may land CSV tables with a per-directory README
(`sim/devchar/<category>/`) before or concurrent with this format landing,
per its own stated fallback ("use plain CSV tables plus a README per
directory... note in the PR that the format should be migrated once #5
ratifies"). That output is **table-shaped evidence**, not a single-claim
pass/fail record, and it does not need to be force-fit into one
`records/<record-id>.md` file per row. The relationship to this convention:

- A CSV table of measured device parameters across a corner sweep (e.g. an
  Rds(on)-vs-width table across all process/temp/supply points) is itself a
  form of raw/summarized output and belongs alongside a `corners/`-style
  directory, not in place of it — the underlying per-corner ngspice logs
  (or an equivalent single run producing the whole table) are the
  `corners/` content, and the CSV is a derived rollup.
- Where a characterization table's row is used later to *substantiate a
  spec claim* (e.g. "this pass-FET width meets the < 300 mV dropout spec"),
  that claim gets its own `records/<record-id>.md` under the relevant
  experiment slug (e.g. `sim/pass-fet-sizing/records/...`), with **Links**
  pointing back at the `sim/devchar/...` table and deck that produced the
  underlying data. The record does not have to re-run the sweep — it can
  cite the existing devchar evidence directly.
- Migration is **not required retroactively**: existing devchar CSVs/READMEs
  landed under the documented interim fallback are not invalidated by this
  format landing. New characterization work, and any record that makes a
  spec-line pass/fail claim from characterization data, should follow this
  convention going forward.

## Worked example

Directory layout for a dropout-vs-load claim on the LDO output, followed by
a post-layout extracted re-run of the same claim:

```
sim/
  dropout-vs-load/
    testbench/
      tb_dropout_vs_load.spice
    netlist-snapshots/
      20260730-120000-4e9c1a2.spice
      20260815-093000-9b3d7f1.spice
    corners/
      20260730-120000-4e9c1a2/
        tt_27c_3.30v_50ma.log
        ss_-40c_2.97v_50ma.log
        ff_125c_3.63v_50ma.log
        ...
      20260815-093000-9b3d7f1/
        tt_27c_3.30v_50ma.log
        ss_-40c_2.97v_50ma.log
        ff_125c_3.63v_50ma.log
        ...
    records/
      20260730-120000-4e9c1a2.md
      20260815-093000-9b3d7f1.md
```

`records/20260730-120000-4e9c1a2.md` (placeholder values — no ratified spec
values exist yet, see #1):

```markdown
# Record 20260730-120000-4e9c1a2

- **Record ID**: 20260730-120000-4e9c1a2
- **Claim**: `spec/ldo.md#dropout-voltage` — dropout voltage at full load
  current, TBD mV target (placeholder; ratified spec pending #1)
- **Netlist provenance**: schematic (`design/ldo.sch`)
- **Corner matrix run**:
  - Process: tt, ss, ff
  - Temperature: −40 °C, 27 °C, 125 °C
  - Supply: 2.97 V, 3.30 V, 3.63 V (±10% of 3.3 V)
  - (9 corner points total — full process x temp matrix at nominal supply,
    plus supply sweep at tt/27C; see testbench for exact point list)
- **Operating conditions**:
  - Load current: 50 mA (full-load dropout point; stretch target 100 mA not
    yet swept)
  - Output cap: 1.0 µF, ESR = 100 mΩ (nominal; ESR range 10 mΩ–1 Ω not yet
    swept for this claim — see stability experiment for ESR sensitivity)
  - Enable state: enabled (EN = VIN), steady-state (not a startup transient)
- **Statistical convention**: N/A (corner-matrix claim, not a distribution
  claim)
- **Result**:
  - tt/27C/3.30V: PASS (placeholder value)
  - ss/-40C/2.97V: PASS (placeholder value)
  - ff/125C/3.63V: PASS (placeholder value)
  - ... (remaining corners: PASS, placeholder values)
  - **Overall: PASS** (placeholder — pending ratified spec, #1)
- **Links**:
  - Testbench: `sim/dropout-vs-load/testbench/tb_dropout_vs_load.spice`
  - Netlist snapshot: `sim/dropout-vs-load/netlist-snapshots/20260730-120000-4e9c1a2.spice`
  - Raw logs: `sim/dropout-vs-load/corners/20260730-120000-4e9c1a2/`
- **Timestamp / author**: 2026-07-30T12:00:00Z, agent-builder
- **Supersedes**: (none — first record for this claim)
```

A later post-layout extracted re-run of the same claim would live under the
same `dropout-vs-load/` experiment directory with its own `<record-id>`,
`Netlist provenance: extracted (layout/ldo.gds -> extracted netlist)`, the
same **Operating conditions** fields (load/cap/enable are a test-setup
property, not a netlist-provenance property, so they carry over unless the
re-run deliberately changes them), and a `Supersedes: 20260730-120000-4e9c1a2`
field carrying a schematic-vs-extracted delta summary in its Result section.

A Monte Carlo mismatch check (e.g. of output-accuracy spread under the
feedback divider's device mismatch) would follow the same shape as bandgap's
worked example: a distinct experiment slug, `Corner matrix run` narrowed to
the nominal or worst corner with a note explaining the narrowing, and a
populated `Statistical convention` field (e.g. "N = 500 Monte Carlo samples,
distribution reported at ±3σ").
