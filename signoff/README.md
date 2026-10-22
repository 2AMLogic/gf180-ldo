# signoff/ — this block's T1 state, graded rather than hand-read

`signoff/records/t1-tier-report.json` is **this block's verdict of record**
against the klayout-tools design-evidence ladder. It is not prose about where
the block stands; it is the output of

```bash
klt signoff --manifest signoff/block-manifest.json --format json
```

re-run by CI on every push, so it cannot quietly go stale the way a
hand-maintained checkbox list does. Issue #79 — this repo's gap-to-T1 tracker
— cites it and no longer keeps a parallel checklist of its own.

**Today: `tier: null`, T1 4/11 items met** (items 1, 8, 9 and 10). That is the honest
state of the block, not a placeholder. There is no top-level LDO layout yet
(only the pass-device array and feedback-divider cells are drawn, under #173),
so no block-level DRC,
no LVS, no extraction, no post-layout re-simulation and no power-delivery
evidence exists to cite; the PVT corner evidence that *does* exist is not
committed in a form `klt signoff` can grade. See "Why each item reads the way
it does" below.

## What is here

```
signoff/
  block-manifest.json                     the manifest: block, kind, per-item evidence
  evidence/characterization.generic.json  item 8's generic evidence envelope
  inventory-item{1,9,10}.json             attestation inventories (hand-written, versioned)
  evidence/item{1,9,10}.generic.json      envelopes produced by `klt signoff --attest`
  records/t1-tier-report.json             the verdict of record (generated)
  check.sh                                re-grade + freshness gate (CI runs this)
```

- `block` is `"gf180-ldo"`. It is required: it is how this block's row is
  identified in the fleet roll-up (`klt signoff --fleet`, 2AMLogic/2am#956),
  which consumes exactly this manifest.
- `kind` is `"analog"`. Confirmed against the block, not taken on faith: every
  cell in `design/` is a hand-captured xschem schematic (`ldo_core`,
  `error_amp`, `ldo_ilimit`, `ldo_softstart`), there is no RTL anywhere in the
  repo, no synthesis or place-and-route step, and no digital partition to
  declare a boundary for. So the Analog column of items 1, 2, 5, 7 and 11
  applies, and `mixed-signal`'s partition-boundary declaration does not arise.

## Running it

```bash
bash signoff/check.sh          # verify (what CI runs)
bash signoff/check.sh --write  # regenerate the verdict of record
```

`check.sh` pins the klayout-tools revision it grades against — see its header
for why that pin is load-bearing (T1 item 11 landed after the v0.5.0 PyPI
release, so an unpinned `pip install klayout-tools` grades this block against
a ten-item checklist and renders no item-11 row at all).

It fails on three separable conditions, so a red build says which one:

1. **A pinned `content_hash` no longer matches the artifact it covers.** `klt
   signoff` compares a manifest's pin against the *envelope's own*
   `provenance.input.content_hash`; it never opens the underlying artifact, so
   two hand-written files agreeing with each other proves nothing by itself.
   `check.sh` closes that loop by re-hashing every cited `source` on disk.
   Touch `sim/CHARACTERIZATION.md` without re-pinning and this fails — which
   is the whole point: a citation that cannot rot is a citation that proves
   nothing.
2. **`klt signoff --manifest` could not run.** Exit 0 (T1 reached) and exit 3
   (ran fine, not yet T1) are both clean runs; 1 and 2 mean a broken manifest
   or a tier doc this `klt` cannot parse.
3. **The committed record no longer matches a fresh run.** Either this block's
   evidence moved or the checklist did. Both are real news; neither should be
   discoverable only by someone re-reading prose.

## Why each item reads the way it does

The grader's verdict is in `records/t1-tier-report.json`. This section is the
part the grader structurally cannot check — what was cited, what was
deliberately *not* cited, and the disclosures `design-evidence-tiers.md`
requires of the claimant rather than of the tool.

| # | Status | Reading |
|---|---|---|
| 1 | **`met`** | `evidence/item1.generic.json`, attested from `inventory-item1.json`: every `design/*.sch`/`.sym` is present and each derived `design/netlist/*.spice` passes `design/netlist.py --check`. See "Items 1, 9 and 10" below. |
| 2 | `unmet` / `no_evidence` | **Not met.** There is no top-level LDO layout. `layout/` holds the proven DRC/LVS *flow*, a one-transistor test cell, and two block cells (`pass_array/`, `divider/`; #285, #286); the error amplifier (#284, blocked on #312), current limit (#290), soft start (#291) and top-level assembly (#288) are not drawn. |
| 3 | `unmet` / `no_evidence` | No `klt drc` envelope for this block exists, because item 2 does not. The test cell's DRC run is evidence about the test cell. |
| 4 | `unmet` / `no_evidence` | Same: no LVS compare of this block exists to cite. |
| 5 | `unmet` / `no_evidence` | Corner evidence exists in quantity under `sim/*/records/`, but as Markdown records from this repo's own harness, not `klt sim` JSON envelopes — nothing here is gradeable yet. `sim/CHARACTERIZATION.md` also reads FAIL on PSRR (issue #289 / `DR-0031`), FAIL on Line reg and Output (issue #325's re-mint, same `DR-0031` residual at the same corner family), MIXED on Startup, and, since issue #320's bias-servo netlist change (DR-0037, proposed), marks every testable row's record STALE against the current `design/netlist/*.spice` until the PVT re-mints can run. This item is the block's largest real gap, and it is an `unmet` row rather than a caveat buried in prose. |
| 6 | `unmet` / `no_evidence` | `sim/mc-output-accuracy/` is a real Monte Carlo campaign, but there is no `klt yield` report — the only kind item 6 accepts. |
| 7 | `unmet` / `no_evidence` | No layout, so no `klt pex`. Item 7 rejects every other evidence kind, so there is nothing weaker that could stand in. |
| 8 | **`met`** | Cites `evidence/characterization.generic.json`, a generic envelope wrapping `sim/CHARACTERIZATION.md`. See below. |
| 9 | **`met`** | `evidence/item9.generic.json`: every committed bench under `sim/*/testbench/`, a single-corner cold start and the pinned PDK/tool versions. See below. |
| 10 | **`met`** | `evidence/item10.generic.json`: README, licence, CI workflow, spec lock and environment doc exist and the PDK-free CI gates pass. See below. |
| 11 | `unmet` / `no_evidence` | Power delivery (structural). No layout means no `klt erc` supply run and no supply-carrying LVS compare. The item has a row here, unmet, rather than being silently absent — it was added to the checklist on 2026-09-17 (klayout-tools#2025) and invalidated every hand-read that predates it. |

### Item 8 is `met`, and what that verdict does and does not say

`sim/CHARACTERIZATION.md` is the one aggregated, current, per-spec-row rollup
this item asks for, and it names the `sim/<slug>/records/` evidence record
behind every verdict. It is generated by `sim/build_characterization_report.py`
and never hand-edited, and CI already regenerates and diffs it on every push,
so it cannot drift from the committed evidence.

Item 8 asks for that aggregation artifact to exist and be current. It does
**not** ask for every row in it to pass, and this `met` verdict must not be
read as if it did: the report currently reads **FAIL on PSRR**, **FAIL on Line
reg** (and therefore on **Output**, which counts line regulation inside its
±2% window), **MIXED on Startup**, and marks half the rows' underlying sim
record **STALE** against the
current `design/netlist/*.spice`. Those are item 5's subject matter, and item 5
is `unmet` above. (PSRR went PASS → FAIL on 2026-09-23 when issue #289's
re-run superseded a stale PASS pair from 2026-09-05; the rollup surfacing a
real design gap rather than concealing it is the property item 8 grades. Root
cause: `spec/decision-records/DR-0031`; the gap itself is issue #302. Line reg
and Output went PASS → FAIL on 2026-09-24 the same way: issue #325's re-mint
superseded a 2026-09-05 record that was stale against DR-0033/DR-0034, and
`ff_125c_3.30v` now reads 8.2345 mV/V against the ratified < 5 mV/V row —
the same supply-dependent soft-start injection residual `DR-0031` measures,
at the same corner family, so it is tracked under issue #302 too.) One green row out of eleven is not a claim about this block's
performance. (Current limit and Thermal read FAIL here until issue #139's
re-run restated them against `DR-0005`'s **ratified** 62–95 mA / ≤ 346 mW rows
rather than the superseded 65–80 mA / ≤ 290 mW ones; no measured number moved.)

Item 8 is also the only T1 item a `generic` envelope may satisfy. Every other
item rejects `"kind": "generic"` outright, so this hand-rolled wrapper cannot
be pointed at items 3–7 to make their rows go green.

### Items 1, 9 and 10 are attested; item 2 is not drawn

These three are `met` through `klt signoff --attest N --inventory
signoff/inventory-itemN.json -o signoff/evidence/itemN.generic.json`. The
envelopes are tool output, never hand-edited; the manifest pins each
envelope's `content_hash`. What each one does and does not say:

- **Item 1** checks that every inventoried schematic/symbol exists and that
  each derived netlist reproduces byte-for-byte from its schematic (ERC clean,
  pinout invariants held), via `python3 design/netlist.py --check`. That
  command needs the pinned xschem 3.4.7, so it is declared `local_only`.
- **Item 9** checks that every file under `sim/*/testbench/` (excluding
  `sim/devchar/`) exists, that the cold start exits 0, and that the PDK and
  tool pins are non-empty. The cold start is `bash sim/selftest.sh --quick
  --require-pdk`: the harness unit tests plus **one** local tt/27C/3.30 V
  ngspice point, writing no evidence. It proves the toolchain and PDK pin
  resolve and the harness runs end to end; it does not re-measure any spec
  row. Multi-corner and Monte Carlo benches are deliberately not cold-start
  commands (they run on the batch fleet). The `pins` block is declared, not
  probed: the grader checks it is non-empty, and `docs/environment-setup.md`
  is where the versions are enforced. The cold start is `local_only`.
- **Item 10** checks that README, LICENSE, the CI workflow, the spec lock and
  the environment doc exist, and that five PDK-free CI gates pass: ruff lint,
  harness unit tests, layout unit tests, `sim/CHARACTERIZATION.md` currency
  and the ratified spec-table lock.

A `met` here says the artifact exists and the named checks passed. It says
nothing about whether the design meets spec; that is items 5 and 6, still
`unmet`.

**CI/local split.** `.github/workflows/ci.yml` runs `klt signoff --attest N
--inventory ... --check ...` for all three items. Under `--check`, a
`local_only` command is not re-run (it is listed as skipped, never as a pass),
but every file-presence and content-hash check still runs, so an edited
schematic, netlist or bench file is drift and fails CI. What CI cannot do is
prove a netlist still regenerates from its schematic (item 1) or that the cold
start still runs (item 9): item 1 needs xschem 3.4.7, which this repo does not
install in CI, and item 9 needs ngspice and the PDK. Re-verify both locally,
with the klt revision `check.sh` pins:

```bash
KLT_REV="$(sed -n 's/^KLT_REV="\(.*\)"/\1/p' signoff/check.sh)"
for n in 1 9 10; do
  uvx --from "git+https://github.com/2AMLogic/klayout-tools@${KLT_REV}" \
    klt signoff --attest $n --inventory signoff/inventory-item$n.json \
    --check signoff/evidence/item$n.generic.json
done
```

That loop skips the `local_only` commands too. To actually run them, use
`python3 design/netlist.py --check` and `bash sim/selftest.sh --quick
--require-pdk` directly, or regenerate the envelope without `--check`.
After any inventoried file changes, regenerate with `--attest N --inventory
... -o signoff/evidence/itemN.generic.json`, copy
`provenance.input.content_hash` into the manifest, and run `bash
signoff/check.sh --write`.

Item 2 is not a presentation choice: the layout does not exist.

### Disclosures the claimant owes, not the grader

- **Item 3's DRC coverage** (`coverage.layers_in_stream_without_rules`,
  `coverage.rules_skipped`, `coverage.deck_scope`) is *reported* by `klt
  signoff`, never graded — a `met` item 3 is not evidence that its coverage
  gaps were disclosed. **Not applicable yet**: item 3 is `unmet` with no
  citation, so there is no `coverage` block to quote. When a DRC citation
  lands, its three coverage fields must be quoted here, from the envelope, not
  from memory.
- **Item 7's `body_bias`** is likewise reported and not graded: a `klt pex`
  citation whose `body_bias.status` is `"unbiased"` still renders `met`, and a
  resimulation of an unbiased extracted netlist is physically wrong rather than
  merely imprecise. **Not applicable yet**: item 7 is `unmet` with no citation.
  A future item-7 claim must state which it was.
- **Item 4's `power_connectivity`** and `body_verification` carry the same
  discipline, and `"unchecked"` is not `"verified"`. Not applicable yet.

## What would move the needle

In dependency order, not effort order: item 2 (a layout of the block) unblocks
3, 4, 7 and 11 at once, and is the single largest gap. Independently of it,
item 5 needs this repo's PVT corner evidence emitted as `klt sim` envelopes
rather than only as Markdown records, and item 6 needs a `klt yield` report
over the existing Monte Carlo campaign. Items 1, 9 and 10 are done.

Filing the tool-side friction this surfaces belongs at
`2AMLogic/klayout-tools`, per this repo's friction protocol.
