# layout/ — GDS, DRC and LVS

Physical verification for this repo, on the gf180mcu open PDK. **There is no
LDO layout yet.** What lives here today is the *flow* and the *plan*:

- the flow — a documented, one-command DRC + LVS invocation, proven end to end
  against a deliberately trivial test cell, so that whoever lays the block out
  inherits a working loop instead of building one (the rest of this file);
- the plan — [`floorplan.md`](floorplan.md), the pass-array segmentation and
  metal strategy, the common-centroid matching plan, the Kelvin-sense scheme
  and the core-area estimate, with [`area_estimate.py`](area_estimate.py)
  re-deriving that estimate from `design/netlist/` on demand.

```bash
python3 layout/drclvs.py --check-env    # is everything installed?
python3 layout/drclvs.py                # build, export, DRC ×2, LVS, controls
python3 layout/drclvs.py --cell passives   # ... on the passive-bearing vehicle
python3 layout/drclvs.py --check        # ... and the committed netlist must be current
python3 layout/drclvs.py --record       # ... and write layout/records/<record-id>.md
```

`drclvs.py` is a **generalized driver, not a testcell-only script**: the stages
above take a `CellSpec` (GDS generator, LVS reference schematic, substrate net,
where the exported netlist is committed) rather than hardcoded constants.
`--cell testcell` (the default) and `--cell passives` are the two registered
today, both of them *flow vehicles* rather than design blocks; a real block's
layout registers its own `CellSpec` in `drclvs.py`'s `CELLS` dict and drives it
with `--cell <key>` — see that file's module docstring for the exact contract.

The stage **count** is a property of the cell. Stages 1–5 always run; stage 6
onwards is one LVS negative control per corruption the netlist can express, so
a FET-only cell has 7 stages and one that also contains a resistor and a
capacitor has 9. The two MOS controls still key off the netlist's first `M*`
element line, so an *all*-passive cell (e.g. a resistor-only feedback divider)
will need its own topology mutation rather than reusing `control_topology`
verbatim.

A run takes about a minute and prints one line per stage:

```
[1/9] layout      : drclvs_passives.gds (45508 bytes)
[2/9] netlist     : 3 device line(s), LVS form
[3/9] klt drc     : clean (0 violation(s), curated subset)
[4/9] pdk drc     : 0 violation(s) across 642 rule categories (41 rule tables)
[5/9] lvs         : MATCH
[6/9] control topology  : gate shorted to drain -> MISMATCH (expected)
[7/9] control parameter : device width doubled -> MISMATCH (expected)
[8/9] control passive-r : resistor length doubled -> MISMATCH (expected)
[9/9] control passive-c : capacitor length doubled -> MISMATCH (expected)
```

Exit status is 0 only if every stage passed. On failure the run directory
(`layout/.work/<record-id>/`, gitignored) is kept, with the raw KLayout logs,
the `.lyrdb` DRC report, the `.lvsdb` LVS database and the extracted netlist in
it.

## What is here

```
layout/
  drclvs.py                          the one command (see "The stages")
  lvs_form.py                        renders passives as primitive R/C elements
  floorplan.md                       the floorplan and matching plan (issue #15)
  area_estimate.py                   core-area estimate from design/netlist/
  xschemrc                           design/xschemrc + `lvs_netlist 1`
  testcell/
    drclvs_testcell.sch              the test cell, schematic side
    drclvs_testcell.sym              (exists only to force a real `.subckt`)
    gen_gds.py                       the test cell, layout side (a generator)
    netlist/drclvs_testcell.spice    the exported LVS reference netlist
  passives/                          same four files for the passive vehicle
  tests/                             stdlib unittest, no PDK/klayout needed
  records/<record-id>.md             append-only run records
```

## The floorplan

[`floorplan.md`](floorplan.md) is the physical plan the eventual layout has to
implement: how the pass array is segmented and strapped for 50 mA, which
devices must be common-centroid and to what numeric target, where the output is
Kelvin-sensed, and how the whole block fits the ratified `< 0.1 mm²` core
budget. Its area arithmetic is not typed in by hand — it comes from

```bash
python3 layout/area_estimate.py               # the block / per-kind table
python3 layout/area_estimate.py --devices     # ... plus every device
python3 layout/area_estimate.py --pass-width 4000   # what-if (issue #139)
```

which reads `design/netlist/ldo_core.spice` directly, so the estimate tracks
the design. `layout/tests/test_area_estimate.py` asserts the estimate still
fits the budget at every candidate pass-device width, which makes the budget
claim a check CI runs rather than a sentence that can go stale.

## Getting the tools

Four things must be on `PATH` / installed. `python3 layout/drclvs.py --check-env`
tells you which are missing.

| Tool | Why | How |
| --- | --- | --- |
| `klayout` (≥ 0.28) | the DRC/LVS engine — runs the PDK's own decks via `klayout -b -r` | `apt-get install klayout`, or a build from [klayout.de](https://www.klayout.de) |
| `klt` | [klayout-tools](https://github.com/2AMLogic/klayout-tools): headless, JSON-contracted DRC | `uv tool install klayout-tools` (or `pipx install klayout-tools`) |
| `xschem` **≥ 3.4.6** | exports the LVS reference netlist from the schematic | build from source — see [`docs/environment-setup.md`](../docs/environment-setup.md) |
| gf180mcu PDK | rule decks, LVS deck, PCells | `volare enable --pdk gf180mcu <hash>` — same install `sim/` uses |

> **The xschem version is load bearing, not a nicety.** `lvs_format` support —
> the mechanism that produces an LVS-readable netlist at all — landed after
> 3.4.4, which is what Debian and Ubuntu package. On 3.4.4 the switch is
> silently ignored and you get a simulation netlist instead. `drclvs.py` detects
> that exact case and fails with a pointer here rather than handing LVS a
> netlist it will mis-read.

The PDK is found by `sim/harness/pdk.py` — the same resolver the simulation
harness uses, so there is one implementation of "where is gf180mcu" in the repo
and `python3 sim/run_corners.py --check-env` diagnoses a missing PDK for both.

### A fifth tool you do *not* have to install: `pmap`

The gf180mcu DRC and LVS decks install a Ruby `Logger` formatter that shells out
to `pmap(1)` on **every** log line, to print the run's memory usage:

```ruby
"#{datetime}: Memory Usage (" + `pmap #{Process.pid} | tail -1`[10, 40].strip + ") : #{msg}"
```

`pmap` is procps — Linux-only, and absent from macOS and from many minimal
Linux containers. On such a host the backtick yields `""`, `""[10, 40]` is
`nil`, and `nil.strip` raises, so the deck dies on its **first** `logger.info`,
before running a single rule. It fails as

```
sh: pmap: command not found
ERROR: In .../main.drc: undefined method 'strip' for nil
```

which reads like a broken deck rather than a missing utility, and takes stages
4–7 — i.e. every DRC number and every LVS verdict this repo is willing to
quote — with it.

`drclvs.py` therefore writes a small `pmap` stand-in into the run directory and
puts it on `PATH` **for the deck subprocesses only** when the host has no real
one. It reports the process's actual resident size via `ps(1)`, in the column
layout the formatter slices, so the logged number is true rather than invented.
Which of the two ran is recorded: the stage-4 line prints `pmap shimmed`, and
every `--record` run carries a `pmap` row reading `host` or `shimmed`, so a
record never implies a stock toolchain when a stage ran against a substitute.

## The test cell

`drclvs_testcell` is **one `nfet_03v3`** (W = 2 µm, L = 0.28 µm, nf = 1) with its
bulk tied out through a guard ring. It is not part of the LDO, nothing in
`design/` or `sim/` instantiates it, and it is not meant to grow. Its whole job
is to be small enough that any failure is unambiguously a failure of the *flow*.

One 4-terminal MOS is nonetheless a real test, not a null one:

- it forces a **device-recognition** pass in the LVS deck (a net-only compare
  would not), so a broken layer or derivation setup shows up;
- `W`, `L`, `nf` and `m` all reach the extracted device, so a **parameter**
  mismatch is detectable — and stage 7 proves it is actually detected;
- the bulk tie exercises the **substrate / global-net** path, which is where a
  top-level LVS most often goes wrong first.

The two sides are kept honest against each other by construction:

- **Layout side** — `testcell/gen_gds.py` builds the cell from the PDK's *own*
  `nfet` PCell, so the geometry is correct by construction. That is deliberate:
  when the deck and the invocation are what is under test, hand-drawn geometry
  makes every failure ambiguous. The only thing the generator adds is four net
  labels (metal1 `34/10` for `S`/`D`/`VSS`, poly2 `30/10` for `G`), placed by
  finding the terminals geometrically rather than at hardcoded coordinates.
- **Schematic side** — `testcell/drclvs_testcell.sch`, netlisted by xschem with
  ERC on, exactly as `design/netlist.py` netlists the real cells.
- The GDS is **not committed**; it is regenerated each run, so the test cell
  tracks the installed PDK instead of freezing a snapshot of it. The exported
  netlist *is* committed, and `--check` re-exports it into a temp directory and
  demands a byte-for-byte match — the same staleness-plus-reproducibility gate
  `design/netlist.py --check` applies.

## The passive-bearing vehicle

A cell whose only device is a FET cannot notice that the flow is broken for
anything else — and it was. The gf180mcu PDK's xschem symbols carry an
`lvs_format` attribute **only on the FETs**; every resistor and every capacitor
symbol has a `format` and nothing else. So `lvs_netlist 1` renders the FETs as
primitive `M` elements and leaves the passives in xschem's *simulation* form,
which KLayout's SPICE reader turns into a call to an undefined subcircuit
instead of a device (issue #313):

```
XRbias NBIAS RBT VSS ppolyf_u_1k r_width=1u r_length=1000u m=1     <- simulation form
XCc    NZ OUT       cap_mim_2f0_m3m4_noshield c_width=48u c_length=48u m=1
```

`layout/lvs_form.py` renders those as the primitive elements the deck's own
SPICE reader delegate understands, carrying `l` and `w` across faithfully:

```
Rbias NBIAS RBT VSS ppolyf_u_1k l=1000u w=1u m=1
Cc    NZ OUT       cap_mim_2f0_m3m4_noshield l=48u w=48u m=1
```

The rewrite runs **before** `drclvs.py`'s simulation-form guard, not instead of
it, and only on lines that carry a complete `r_width`/`r_length` or
`c_width`/`c_length` pair — the parameter names every PDK passive symbol's
`format` uses, which is what makes the translation cover the whole family
without enumerating flavours. Anything it declines to touch is still a hard
failure — first through the existing simulation-form guard, then through a
family-agnostic backstop that rejects any *remaining* `X`-prefixed line
carrying a `key=value` parameter tail. That tail is the tell: every device
symbol's `format` ends in one, a hierarchical subcircuit symbol's
(`@name @pinlist @symname`) does not, so a device family nobody has needed
yet cannot sail through by not being named in a regex. `lvs_form.py`'s module
docstring records why this lives here rather than in repo-local `.sym`
overrides.

`drclvs_passives` is what proves it end to end: **one `ppolyf_u_1k` H-poly
resistor** (1 µm × 10 µm), **one `cap_mim_2f0` MIM cap** (20 µm × 20 µm) and
**one 2-finger `nfet_03v3`** (W = 6 µm total, L = 0.28 µm), each built from the
PDK's own PCell, sharing no nets with each other. Like the test cell it is not
part of the LDO and is not meant to grow. It earns its keep three ways a
single-FET cell cannot:

- the resistor and the cap are the devices `lvs_form.py` exists for, and stages
  8 and 9 prove the deck really compares their geometry;
- the **multi-finger** FET checks that the deck's own multifinger merge lands
  one device — its two interdigitated source straps carry the same label and
  nothing straps them in metal, so the merge is doing the work;
- the MIM cap is the only device here whose terminals are not on metal1/poly2.
  For the 5LM / MIM-option-B stack this repo builds against they are metal4 and
  metal5, which ties the layout, the deck's `mim_option`/`metal_level`/`mim_cap`
  switches and the schematic's `model=cap_mim_2f0_m4m5_noshield` into one
  self-checking loop. Get any of the three wrong and the device extracts as
  nothing at all.

## The stages

**1. Build the layout.** `klayout -b -r layout/testcell/gen_gds.py`.

**2. Export the schematic netlist.** xschem headless, ERC on, through
`layout/xschemrc`. That file is `design/xschemrc` plus one switch,
`set lvs_netlist 1`, which makes xschem render each device from its symbol's
`lvs_format` attribute instead of its `format` attribute. For the gf180mcu
symbols the difference is exactly what LVS needs:

```
format      ->  XM1 D G S VSS nfet_03v3 L=0.28u W=2u nf=1 ad='int((nf+1)/2) * W/nf * 0.18u' ...
lvs_format  ->  M1  D G S VSS nfet_03v3 L=0.28u W=2u nf=1 m=1
```

The first is an **ngspice subcircuit call** (the gf180mcu models *are*
subcircuits, hence `spiceprefix=X`). The second is a plain SPICE element whose
leading letter names the device class and whose parameters are geometric
literals. KLayout's `NetlistSpiceReader` reads the second and cannot evaluate
the first form's parameter expressions — hand it the simulation netlist and it
does not error, it quietly turns the device into a call to an undefined
subcircuit, collapses the top-level circuit to a single merged net, and reports
"nets don't match". A mismatch that reads like a layout bug but is a netlist-form
bug. `drclvs.py` checks the exported text for the simulation form and refuses to
continue.

> **Schematic-authoring consequence:** in any cell that will be LVS'd, name each
> device instance with the SPICE element letter its class needs — `M*` for MOS,
> `R*` for resistors, `C*` for capacitors. `lvs_format` starts with a bare
> `@name`, and that letter is what tells the reader which element it is looking
> at. The cells in `design/` already follow this convention.

**3. DRC — `klt drc --deck gf180mcu --format json`.** The agent-facing,
JSON-contracted path; the report is kept in the run directory. Fast (milliseconds),
and it is a **13-rule curated subset**. See "Coverage, honestly" below.

**4. DRC — the PDK's own deck.** The full gf180mcu KLayout deck, assembled the
way the PDK's own `run_drc.py` assembles it: `main.drc`, then every rule table
(minus the flat-mode `*_split` variants, matching what `run_drc.py` does in deep
mode), then `tail.drc`, with `layers_def.drc` copied beside the generated deck.
41 rule tables, and ~640 rule categories. `drclvs.py` assembles the deck itself
rather than shelling out to `run_drc.py`, which needs `docopt` and drives its
own parallel run/report layout; what we want is one deck, one report, one exit
status. **This is the DRC number worth quoting.**

Quote it from a *record*, not from this file: the category count is a property
of the deck **as the installed KLayout builds it**, not of the PDK alone. At
the same open_pdks hash it was 642 under KLayout 0.28.16 (record
`20260801-075800-9419809`) and is 640 under 0.30.10 (record
`20260922-215349-74f117f`). What matters for a DRC claim is that the count is
large and non-zero — see the zero-category trap immediately below — and that
the violation count beside it is zero.

A deck that runs but registers *zero* rule categories produces an empty report
that is indistinguishable from a clean one — that is what a mis-assembled deck
looks like, so `drclvs.py` treats zero categories as a hard error rather than a
pass.

**5. LVS.** The PDK's own `gf180mcu.lvs`, layout against the netlist from stage 2.
The deck reports its own verdict in its log and exits 0 either way, so the log is
the contract; `drclvs.py` demands exactly one of the two verdict strings, so a
deck that fell over before comparing is an error rather than a silent pass.

**6 onwards. Negative controls.** The same compare, once more per control,
against deliberately corrupted copies of the netlist. Every one **must**
mismatch:

| Control | Mutation | Registered when | What it would mean if it matched |
| --- | --- | --- | --- |
| topology | gate shorted to drain | always | a 4-net circuit compared equal to a 3-net one — the compare is not looking at connectivity |
| parameter | device width doubled | always | device parameters are not being compared at all |
| passive-r | resistor length doubled | the netlist has an `R` element | resistor geometry is not being compared at all |
| passive-c | capacitor length doubled | the netlist has a `C` element | capacitor geometry is not being compared at all |

These are not decoration. A "match" from an LVS run is not evidence unless a
*known-wrong* netlist fails: a mis-wired invocation that silently compares
nothing also "passes", and a compare that checks connectivity while ignoring
parameters would wave through a mis-sized transistor.

The passive pair is load bearing for a reason particular to this PDK's deck:
its SPICE reader delegate registers resistors and capacitors with the `R` and
`C` parameters **disabled** (`custom_classes.lvs`), so a netlist claiming a
resistance 30× off the truth legitimately still matches. Geometry is the only
thing being compared for those devices, which makes "is the geometry actually
compared?" a question worth answering with a control rather than an assumption.

## Coverage, honestly

**`klt drc`'s gf180mcu deck is a curated 13-rule subset**, transcribed from the
published design rule manual — width, space and enclosure checks across
poly2 / comp / contact / metal1, 3.3 V column only. It is a fast inner-loop
check, not signoff. `klt drc: clean` and "DRC clean" are different claims and
this repo will not conflate them: any DRC claim made in this repo cites the
**PDK deck's** result and its rule-category count.

Both are run on every invocation precisely so the two numbers stay visible next
to each other.

## What LVS here does *not* check

Verified, not assumed — a gate/drain **swap** in the reference netlist still
reports a match. The deck's compare is purely structural, so swapping which
nets the gate and drain terminals connect to is a valid graph isomorphism
(relabel the two nets) and legitimately matches. The metal1/poly2 labels give
the extracted nets *names*, but names do not constrain the compare.

The practical consequence: **"LVS clean" does not establish that a block's
top-level pinout is right.** Something else has to check pin order. In this repo
that something is `design/netlist.py --check`, which asserts the ratified port
list and order and that every symbol's pins match its schematic's ports. That is
why stage 6's control shorts two nets instead of swapping two — a swap would
have been a control that never fires.

## The database-unit trap in `klt drc`

`klt drc`'s rule thresholds are raw database-unit integers and are **not** scaled
by the layout's own `dbu`, even though the report prints `dbu_um`. The same
geometry therefore gets a different verdict depending only on the database unit
the GDS was written at — measured on this very test cell:

| stream `dbu_um` | `klt drc --deck gf180mcu` |
| --- | --- |
| 0.001 | clean, 0 violations |
| 0.005 | **violations, 210** |
| 0.0005 | clean, 0 violations |

`testcell/gen_gds.py` writes at `dbu = 0.001`, which is what the PDK's own
KLayout tech file declares, so this repo is on the right side of it. Anyone
bringing in a GDS from elsewhere should check its dbu before believing a
`klt drc` result. Filed upstream as
[klayout-tools#172](https://github.com/2AMLogic/klayout-tools/issues/172).

## Records

`--record` writes an append-only summary to `layout/records/<record-id>.md`,
with the record-id convention `sim/` uses (`<YYYYMMDD>-<HHMMSS>-<short-sha>`).
Re-runs mint a new record; records are never edited in place. Each one carries
the tool versions, the PDK variant and open_pdks hash, both DRC results with
their rule-category counts, the LVS verdict and every control verdict.

The run directory itself (`layout/.work/`) is scratch and gitignored — the
`.lyrdb` / `.lvsdb` databases are large, machine-specific and regenerable. The
record is the evidence.

## Friction filed upstream

Per CLAUDE.md's friction protocol, the gaps this bring-up hit are filed
generically against [klayout-tools](https://github.com/2AMLogic/klayout-tools):

- [#172](https://github.com/2AMLogic/klayout-tools/issues/172) — `klt drc`
  ignores the layout's database unit (above).
- [#173](https://github.com/2AMLogic/klayout-tools/issues/173) — `klt drc` can
  only run its own built-in decks; there is no way to point it at the deck the
  PDK ships. This is why stage 4 assembles and drives the PDK deck by hand.
- [#163](https://github.com/2AMLogic/klayout-tools/issues/163) (existing, part
  of the `klt lvs` epic) — commented with two requirements this bring-up
  surfaced: the simulation-vs-LVS netlist-form split, and the need for negative
  controls in the contract. `klt` had no LVS verb when stage 5 was written,
  which is why it drives the PDK's deck directly; see the note below the list.
- [#2308](https://github.com/2AMLogic/klayout-tools/issues/2308) — no verb
  reports a deck's **rule values**, so pre-layout arithmetic (everything
  `area_estimate.py` computes) hard-codes constants transcribed out of Ruby
  comment strings in the PDK's rule decks. `klt deck info` gives a content hash
  and device classes; `klt drc` needs a stream. Filed from `floorplan.md` §10.
- [#2333](https://github.com/2AMLogic/klayout-tools/issues/2333) — `klt drc
  --engine klayout` runs a PDK's **driver script** as-is, so the driver's host
  assumptions become klt's; a missing host utility aborts the deck before any
  rule runs, and the surfaced error blames the deck. This is the generic form
  of the `pmap` problem above. Asks for either deck composition from the rule
  tables alone, or a preflight that names the missing utility.

`klt` has since grown both of the verbs this section's older entries wanted:
`klt drc --engine klayout` (PDK-native DRC-DSL decks, #173) and `klt extract` /
`klt lvs` (headless extraction and compare, the #163 epic) — as of `klt 0.4.0`,
which is newer than stages 4 and 5 here. **Collapsing those two stages into
`klt` calls is real, available work, but it is not a free swap**: the negative
controls and the verdict-string contract in stage 5 are what make an LVS
"match" evidence at all, and any move has to carry them across and show the
same cell reaching the same verdict both ways before the old path is retired.
