# layout/ — GDS, DRC and LVS

Physical verification for this repo, on the gf180mcu open PDK. **There is no
top-level LDO layout yet** — two block cells are drawn (the pass-device array
and the feedback divider); the rest is still plan. What lives here today is:

- the flow — a documented, one-command DRC + LVS invocation, proven end to end
  against a deliberately trivial test cell, so that whoever lays the block out
  inherits a working loop instead of building one (the rest of this file);
- the block cells drawn so far — [`pass_array/`](pass_array/), the LDO's
  40-unit-cell pass device and its `Msense` replica (issue #285), and
  [`divider/`](divider/), `floorplan.md` §4.1's 18-unit common-centroid
  feedback divider ("The feedback divider" below), each drawn and verified
  through that same flow;
- the plan — [`floorplan.md`](floorplan.md), the pass-array segmentation and
  metal strategy, the common-centroid matching plan, the Kelvin-sense scheme
  and the core-area estimate, with [`area_estimate.py`](area_estimate.py)
  re-deriving that estimate from `design/netlist/` on demand.

```bash
python3 layout/drclvs.py --check-env    # is everything installed?
python3 layout/drclvs.py                # build, export, DRC ×2, LVS, controls
python3 layout/drclvs.py --cell passives   # ... on the passive-bearing vehicle
python3 layout/drclvs.py --cell pass_array # ... on the LDO's pass-device array
python3 layout/drclvs.py --cell divider    # ... on the feedback divider
python3 layout/drclvs.py --check        # ... and the committed netlist must be current
python3 layout/drclvs.py --record       # ... and write layout/records/<record-id>.md
```

`drclvs.py` is a **generalized driver, not a testcell-only script**: the stages
above take a `CellSpec` (GDS generator, LVS reference schematic, substrate net,
its own pair of LVS negative controls, where the exported netlist is
committed) rather than hardcoded constants. `--cell testcell` (the default)
and `--cell passives` are *flow vehicles* rather than design blocks;
`--cell pass_array` is the first real one — the LDO's 40-unit-cell pass device
and its `Msense` replica (issue #285, under epic #173) — and `--cell divider`
is the feedback divider, the first all-passive one. A block's layout registers
its own `CellSpec` in `drclvs.py`'s `CELLS` dict and drives it with
`--cell <key>` — see that file's module docstring for the exact contract.

The stage **count** is a property of the cell, and the driver derives it rather
than hard-coding it: five stages are common to every cell (build the layout,
export the netlist, the two DRC runs and LVS), each LVS negative control the
netlist can express adds one, and a cell that registers `CellSpec.erc` adds two
more — the intact ERC supply run before LVS, and the ERC negative control after
the LVS controls. The topology/parameter pair is the cell's own
(`CellSpec.controls`): the MOS pair keys off the netlist's first `M*` element
line, so an all-passive cell registers the passive pair instead. The numbering
shifts with those optional stages, so it is given once, in
[The stages](https://github.com/2AMLogic/gf180-ldo/blob/main/layout/README.md#the-stages);
per-cell totals are deliberately not quoted here, because they drift whenever a
cell gains a control or an ERC run.

A run takes about a minute and prints one line per stage:

```
[1/9] layout      : drclvs_passives.gds (45508 bytes)
[2/9] netlist     : 3 device line(s), LVS form
[3/9] klt drc     : clean (0 violation(s), curated subset)
[4/9] pdk drc     : 0 violation(s) across 739 rule categories (gf180mcu.drc, decks=all,-antenna,-density)
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
  lvs_controls.py                    its LVS negative controls (stages 6..N): netlist
                                     mutations that MUST mismatch
  erc_stage.py                       its klt erc supply stage (issue #785) and the
                                     run record's ERC rows/section
  drclvs_common.py                   StageError, repo_arg and the repo/layout roots
                                     shared by the three files above
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
  pass_array/                        the pass-device array (issue #285)
    pass_array.sch / .sym            its LVS reference, restating ldo_core's
                                     Mpass and Msense (see the .sch's own note)
    gen_gds.py                       N unit cells + M Msense cells of the SAME
                                     cell, plus the 50 mA metal stack
    em_budget.py                     the EM/IR arithmetic gen_gds.py fails the
                                     build on, checked against floorplan.md §1
    netlist/pass_array.spice         the exported LVS reference netlist
  divider/
    plan.py                          floorplan.md §4.1's arrangement, as numbers
    gen_gds.py                       the divider, layout side (a generator)
    fb_divider.sch                   the divider, schematic side
    fb_divider.sym                   (fixes the `.subckt` port order)
    netlist/fb_divider.spice         the exported LVS reference netlist
  erc/                               the klt erc supply stage (issue #785)
    gen_spec.py                      emits each cell's supply spec from its
                                     committed GDS (one parameterized source,
                                     measured and asserted, not transcribed)
    mutate_gds.py                    the ERC negative control's tie-severing
                                     disposable layout copy
    specs/<key>.erc.json             the committed supply specs (ldo_core
                                     extends the same source)
    reports/<key>/<rid>.erc.json     append-only klt erc report envelopes
  drc/reports/<key>/<rid>.*.json     append-only klt drc report envelopes (#784)
  lvs/reports/<key>/<rid>.*.json     append-only klt lvs reports + requests (#784)
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
| `klt` | [klayout-tools](https://github.com/2AMLogic/klayout-tools): headless, JSON-contracted DRC | `uv tool install klayout-tools==0.8.0` (or `pipx install klayout-tools==0.8.0`) |
| `xschem` **≥ 3.4.6** | exports the LVS reference netlist from the schematic | build from source — see [`docs/environment-setup.md`](../docs/environment-setup.md) |
| gf180mcu PDK | rule decks, LVS deck, PCells | `ciel enable --pdk-family gf180mcu -l gf180mcu_fd_pr f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (ciel 2.6.1) — same install `sim/` uses |

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
ERROR: In .../gf180mcu.lvs: undefined method 'strip' for nil
```

(The PDK's **LVS** deck shells out to `pmap`; the pinned revision's DRC deck
does not — it reads memory through KLayout's own API — so this failure, when
it fires, is stage 5 onwards.)

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
Cc    NZ OUT       cap_mim_2f0fF l=48u w=48u m=1
```

and, for the MIM capacitors, it also maps the **model token**: the deck's
extraction registers `cap_mim_<n>f<m>fF` device classes
(`rule_decks/mimcap_extraction.lvs`), while the token an export carries is
the *symbol* name (`cap_mim_2f0_m3m4_noshield`). KLayout's compare matches
device classes **by name**, so a pass-through token pairs with nothing and
the cell mismatches with no rule-level diagnosis (issue #642). The flavour
`<n>f<m>` is common to both spellings, so the mapping is keyed on it, and it
mirrors the PDK's own LVS regression netlists, where the *subcircuit* is
named after the symbol and the *device* after the class. But the deck
registers only one MIM flavour per run (`2f0`, the `mim_cap` switch
`drclvs.py` pins), so that flavour alone maps: any other `cap_mim_*` token
is a hard `LvsFormError`, never a silently passed-through token -- whether
no spelling of it can be parsed into a flavour at all, or it names a
flavour other than the pinned one (issue #680). Resistors need no mapping
(the resistor
symbols' names are the registered class names) and neither do the non-MIM
capacitors (`rule_decks/moscap_extraction.lvs` registers `cap_nmos_03v3` &
co under their symbol names).

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
  switches, the schematic's `model=` symbol name and `lvs_form.py`'s mapping of
  it to the registered `cap_mim_2f0fF` device class into one self-checking
  loop. Get any of them wrong and the device extracts as nothing at all -- or
  pairs with no class, which since issue #642 is a loud export error rather
  than an undiagnosed mismatch.

## The feedback divider

`--cell divider` is the second cell here that is part of the LDO, after the
pass array, and the first all-passive one:
[`floorplan.md` §4.1](floorplan.md#41-feedback-divider--the-term-simulation-cannot-see)'s
18-unit `ppolyf_u_3k` string — 6 up / 12 down, one dummy strip at each end,
`B T B B T B B T B B T B B T B B T B` at a 2.4 µm pitch — which is what
`design/netlist/ldo_core.spice`'s ideal `Rtop` / `Rbot` pair becomes in
silicon. It is here rather than deferred because **the divider's dominant
error term cannot be simulated at all**: the PDK's resistor subcircuits
hard-code `mis_r = 0` and the high-sheet `ppolyf_u_*k` cards carry no local
mismatch term (`sim/devchar/CONCLUSIONS.md` §2), so the drawn common centroid
is the only mitigation the project has, and an LVS-verified drawing of it is
the only evidence available that it is the arrangement the budget assumed.

`layout/divider/plan.py` is that arrangement as numbers, imported by both the
generator and `layout/tests/test_divider_layout.py` so the two cannot drift;
the test asserts both legs' centroids land on §4.1's stated **9.5**, the
string is still 900 kΩ tapped 600 k / 300 k, and the committed reference
netlist really is an 18-unit series chain tapped after twelve.

Four things about this cell are worth knowing before drawing the next one,
because none of them is obvious and all four are properties of the PDK rather
than of this design:

- **The PDK's `ppolyf_u_3k` xschem symbol has no `lvs_format`** — the gap
  "The passive-bearing vehicle" above describes for every passive symbol.
  `fb_divider.sch` was drawn before `layout/lvs_form.py` landed and supplies
  the missing rendering **per instance** (`lvs_format="@name @pinlist @model
  W=@W L=@L m=@m"`), so its export already comes out as primitive `R` lines;
  `lvs_form.py` only rewrites `X`-prefixed simulation-form lines and leaves
  these untouched. Either route gives the deck the `W`/`L` it compares.
- **`poly_res` is not a free switch.** `rule_decks/res_extraction.lvs` wraps
  the high-sheet flavours in a `case POLY_RES`, so exactly one of `1k`/`2k`/
  `3k` is extracted per run. A `ppolyf_u_3k` cell run under the default `1k`
  extracts *nothing* and mismatches. It is a `CellSpec` field for that reason.
- **The deck no longer derives anything: every compare-affecting option is
  its own `-rd` switch, all defaulting false.** The pinned `gf180mcu.lvs`
  reads `SIMPLIFY` from `$simplify` alone, and it gates *both* sides
  (`netlist.simplify` and `schematic.simplify`). Left unset it is false, and
  `netlist.simplify` is what collapses series/parallel chains in the
  extracted netlist: on it would fold the 18 drawn units into two lumped
  resistors, so the compare could no longer tell an 18-unit string from one
  long strip — precisely the property DR-0003 asks the divider to have.
  `run_lvs()` therefore passes `simplify` explicitly from
  `CellSpec.simplify_extracted` (`false` for this cell), and passes
  `implicit_connect=true` unconditionally — the deck's
  `connect_implicit('*')` is what joins the straps a cell like
  `drclvs_passives` deliberately does not draw in metal. The divider's LVS
  `MATCH` is a device-by-device compare of all twenty strips.
- **The resistor PCell's own substrate tie had to go.** It draws a p-tap
  column 0.71 µm to the left of *each* strip, which leaves room for exactly
  one Metal1 track in the left routing channel. `gen_gds.py` removes the
  twenty per-unit columns (asserting shape-by-shape that nothing else lives
  in that x window) and replaces them with the single guard / substrate-tap
  ring §4.1 asks for. It also fills the 0.04 µm slots the tiled PCell leaves
  between adjacent head implants, which would otherwise be 38 × **PP.2** and
  76 × **SB.15b** violations — artefacts of tiling a PCell drawn to stand
  alone, not of the plan's pitch.

### `klayout -b -r` swallows `SystemExit`

A generator script's assertions are only worth writing if they are audible.
They are not, by default: a bare `raise SystemExit("…")` under `klayout -b -r`
prints **nothing** and the klayout process still exits **0** (checked on
KLayout 0.28.16). `drclvs.py` does catch the failure — stage 1 requires the
`.gds` to exist and raises otherwise — but the message it prints is "layout
build produced no …", i.e. the symptom rather than the cause, and the real
diagnostic is gone.

`divider/gen_gds.py` therefore routes every assertion through a `_fail()`
helper that writes to stderr (which `drclvs.py` captures into the run
directory's `build-gds.log`) before exiting. Any new generator should do the
same — `passives/gen_gds.py` and `pass_array/gen_gds.py` share one copy in
`layout/gen_gds_common.py` (issue #333). `testcell/gen_gds.py` carries its
own copy of the divider's helper (issue #296), so its PCell-shape assertions
are audible too.

One as-drawn deviation from §4.1's prose, recorded here and in §4.1 itself:
the plan says the units are "joined on M1", and they are — but the two legs
use **different Metal1 tracks**. The interdigitation makes every bottom-leg
link jump over a top-leg strip, so the two legs' link sets interleave and
cannot share a planar channel. The bottom leg's links run in the channels
just outside the heads; the top leg's run over the resistor bodies, inside
the M1 keep-out §4.1 already reserves for them.
`test_divider_layout.LinkRoutabilityTests` holds both halves of that
argument, so it is a check rather than a claim.

## The stages

**1. Build the layout.** `klayout -b -r <the cell's gen_gds.py>` — e.g.
`layout/testcell/gen_gds.py`, or `layout/divider/gen_gds.py` for `--cell
divider`.

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
JSON-contracted path. Fast (milliseconds), and it is a **curated subset, not
signoff** — 127 rules at klt `0.9.3.dev2575` (114 at the PyPI-pinned `0.8.0`);
re-measure with `klt drc --deck gf180mcu --list-rules`. See "Coverage,
honestly" below. On the three design cells a `--record` run also commits the
report (via `-o`) to `layout/drc/reports/<cell>/<record-id>.drc.json`.

**4. DRC — the PDK's own deck, through klt.** The full gf180mcu KLayout deck
(`libs.tech/klayout/tech/drc/gf180mcu.drc`, which `require_relative`s its rule
tables from `tech/drc/rule_decks/*.rb`), driven since issue #784 by
`klt drc --engine klayout --deck-file … --deck-var decks=all,-antenna,-density …`:
klt passes the same table selection and variant metal-stack switches
(`metal_level`/`metal_top`/`mim_option`) the raw `klayout -b -r` invocation
passed, fails a deck that aborted part-way (a partial report is never clean),
and asserts the deck's declared rule-category **set** via
`--expect-rule-categories-file` fed by a `--list-rule-categories` listing of
the same deck under the same switches — so a deck that ran zero (or swapped)
categories is a hard error, never a clean pass. **This is the DRC number worth
quoting.** `--parity-raw-deck` re-runs the retired raw invocation beside it
and hard-fails on any verdict or category-set difference; the three cells'
parity is recorded in their #784 run records. A `--record` run commits the
report to `layout/drc/reports/<cell>/<record-id>.drc-klayout.json`.

Quote it from a *record*, not from this file: the category count is a property
of the deck **as the installed KLayout builds it**, not of the PDK alone, and
it moved when the deck itself moved — 642 under the pre-bump
concatenated-deck layout (record `20260801-075800-9419809`), 640 under the
same old layout on KLayout 0.30.10 (record `20260922-215349-74f117f`), and
739 under the pinned revision's driver deck with the `decks=` selection above
(record `20261115-231214-136fe3e`). Old counts are not comparable to new ones:
they are different rule sets. What matters for a DRC claim is that the count
is large and non-zero — see the zero-category trap immediately below — and
that the violation count beside it is zero.

A deck that runs but registers *zero* rule categories produces an empty report
that is indistinguishable from a clean one — that is what a deck that ran no
rules looks like (a mis-set `decks=` selection does exactly this), so
`drclvs.py` treats zero categories as a hard error rather than a pass.

**5. ERC supply run** (issue #785; the cells that register `CellSpec.erc` --
today `pass_array` and `divider`). `klt erc --deck gf180mcu --findings-only`
against the cell's supply spec, which `layout/erc/gen_spec.py` emits from the
**committed** GDS immediately before the run: one parameterized source, one
spec per cell, so `ldo_core` extends the same source instead of forking a
spec format. The generator *measures* the GDS (the divider's asserted
substrate region is the tap ring's own band, read out of the stream) and
*asserts* every spec claim the ERC tool cannot check for itself -- the
divider's `tap_is_dedicated` rests on "COMP draws only the tap ring here",
and the day that stops being true, spec generation fails instead of the tie
quietly widening. The stage then validates the envelope against the cell's
own contract: every declared supply resolves to one labelled island
(`matched_islands == expected_islands`, both quoted in the record), every
declared tie lands in `erc_coverage.checked` (a tie in `skipped` is a
degenerate declaration and "does not count as checked"), and the finding
set is exactly the cell's disclosed expected findings -- the pass array's
one finding is `erc.floating_gate` on `PASS_GATE`, a true statement about
the standalone sub-cell (its gate bus is a label-only port; gate routing
lands at `ldo_core` assembly), quoted in the record rather than hidden.
`--deck gf180mcu` matters here beyond the report line: its resistor
recognition carves the divider's `ppolyf_u` bodies out of poly2, without
which the whole resistor string reads as one conductor shorting every net
to every other. A `--record` run commits the spec
(`layout/erc/specs/<key>.erc.json`) and the report envelope
(`layout/erc/reports/<key>/<record-id>.erc.json`). These sub-cell runs are
T1 item 11 *groundwork*, not its evidence: the item stays `unmet` until
#524's `ldo_core` run (see `signoff/README.md`). The spec's
`ties[].through` (the tie reaches its rail only through drawn contact
cuts) needs a klayout-tools build carrying that key -- the klt the records
cite has it; `signoff/check.sh`'s older grading pin does not, and rejects
the spec.

**6. LVS.** Routed per cell since issue #784 (`CellSpec.lvs_route`):

- **`klt` (the default)** — `klt lvs` on the curated gf180mcu deck (engine
  `klayout`), layout against the committed reference netlist. The request
  document is committed beside its report
  (`layout/lvs/reports/<cell>/<record-id>.lvs-request.json`), carrying the
  raw route's knobs on their klt counterparts: `deck_options`
  (`poly_res` per cell, the MIM flavour in the curated deck's own class
  spelling, `metal_top` for the installed variant), the
  `reference.form: "subckt-call"` + `reference.deck: gf180mcu` conversion for
  references whose device cards name PDK model tokens, and the per-cell
  `options` (`compare_parameters` scopes a resistor class's `L`/`W` back
  into the compare — KLayout declares them *secondary*, so without this the
  geometry controls would match — and `combine_devices` folds pass_array's
  40 drawn parallel units onto its one `nf=40` reference card). A `--record`
  run commits the report (`<record-id>.lvs.json`); its
  `provenance.input.content_hash` pins the committed GDS bytes, and
  `klt lvs --check <report>` re-verifies it.
- **`pdk-deck` (raw `klayout -b -r`, the pre-#784 path)** — no cell uses it
  now. `passives` moved to `klt` with `layout.join_same_named_nets`
  ([klayout-tools#7030](https://github.com/2AMLogic/klayout-tools/issues/7030))
  and the PDK's `cap_mim_2f0fF` spelling
  ([#7031](https://github.com/2AMLogic/klayout-tools/issues/7031)); the route
  stays available for a future named klt gap.
  The deck reports its own verdict in its log and exits 0 either way, so the
  log is the contract; `drclvs.py` demands exactly one of the two verdict
  strings, so a deck that fell over before comparing is an error rather than
  a silent pass.

**7 onwards. Negative controls.** The same compare, once more per control,
against deliberately corrupted copies of the netlist — through the **same
route stage 6 took for that cell**. Every one **must** mismatch:

| Control | Mutation | Registered when | What it would mean if it matched |
| --- | --- | --- | --- |
| topology | gate shorted to drain | the cell registers the MOS pair (`testcell`, `passives`, `pass_array`) | a 4-net circuit compared equal to a 3-net one — the compare is not looking at connectivity |
| parameter | device width doubled | the cell registers the MOS pair | device parameters are not being compared at all |
| topology | two adjacent taps of the string shorted | the cell registers the all-passive pair (`divider`) | a string with one unit shorted out compared equal to the intact one |
| parameter | unit resistor width doubled | the cell registers the all-passive pair | device parameters are not being compared at all |
| passive-r | resistor length doubled | the netlist has an `R` element | resistor geometry is not being compared at all |
| passive-c | capacitor length doubled | the netlist has a `C` element | capacitor geometry is not being compared at all |

After the LVS controls, the ERC-negative-control stage (issue #785, same
cells): `layout/erc/mutate_gds.py` writes a disposable copy of the committed
GDS with the declared tie's connection severed — every via1 landing on the
pass array's n-well guard ring, every contact cut on the divider's p+
substrate-tap ring — and the copy is run with the **intact** spec. It must
report exactly one new `erc.missing_tie` on the intended tie; a skipped
check, an absent finding, or any unrelated new finding fails the control.
The mutation severs the *path*, not the parts (the labelled supply metal and
the tap region itself stay in the stream), which is what makes the intact
run's clean tie verdict falsifiable rather than vacuous.

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

**Which topology/parameter pair runs is a property of the cell**
(`CellSpec.controls`), not of `drclvs.py`. That is load bearing rather than tidy: the MOS pair keys off the
netlist's first `M*` element line, so pointed at a resistor-only cell it
would have had nothing to mutate — **two stages that quietly did nothing,
behind a stage-5 `MATCH` that then meant nothing**. `drclvs.py` therefore

- requires every registered cell to carry one topology control **and** one
  parameter control (`REQUIRED_CONTROL_TAGS`), and
- proves, **before stage 3 runs**, that each of them — and each
  passive-geometry control added on top — actually changes *this* cell's
  netlist — a control that cannot be applied, or that runs and returns
  the netlist unchanged, is a hard error (`ControlNotApplicable`), never a
  skipped stage.

`layout/tests/test_drclvs.py` holds that contract without needing a PDK,
including both directions of the mismatch (MOS controls against the passive
cell and vice versa).

Two details the passive pair had to get right, both of them properties of the
PDK's own deck rather than of this repo:

- **Scale a *dimension*, not the resistance.** `rule_decks/custom_classes.lvs`
  defines the poly-resistor device class as `BResistor`, which does
  `enable_parameter('R', false)` and compares only `W` and `L`. A control that
  scaled `R=` would never fire — the exact "control that is not a control"
  failure these stages exist to rule out.
- **Short an *internal* tap, not a port.** Renaming one of the cell's own
  ports would change the pin list rather than the connection graph, which is a
  different and weaker corruption; `control_short_adjacent_taps` refuses to do
  it.

## Coverage, honestly

**`klt drc`'s gf180mcu deck is a curated subset**, transcribed from the
published design rule manual — **127 rules** at klt `0.9.3.dev2575` (114 at
the PyPI-pinned `0.8.0`; re-measure with `klt drc --deck gf180mcu
--list-rules`, the figure is a property of the installed klt). It is a fast
inner-loop check, not signoff. `klt drc: clean` and "DRC clean" are different
claims and this repo will not conflate them: any DRC claim made in this repo
cites the **PDK deck's** result and its rule-category count, and every
`--record` run quotes both reports' own `coverage` blocks
(`layers_in_stream_without_rules`, `rules_skipped`, `deck_scope`) so a
"clean" claim can never silently mean "clean under the subset that happened
to check".

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
their rule-category counts and coverage quotes, the LVS verdict, every control
verdict, and the committed-artifact list.

The run directory itself (`layout/.work/`) is scratch and gitignored — the
`.lyrdb` / `.lvsdb` databases are large, machine-specific and regenerable. The
record is the evidence — and, since issue #784, so are the klt reports and the
GDS they pin:

- **The GDS.** The three design cells commit their generated GDS at
  `layout/<cell>/<cell>.gds`. Every later stage runs against the *committed*
  bytes — the artifact the reports pin by content hash — after the flow proves
  the fresh build reproduces them (GDS timestamps aside,
  `gds_equal_modulo_timestamps`). Re-minting is a deliberate act
  (`--mint-gds`, then a `--record` run to refresh the reports), never a side
  effect of running the flow.
- **The klt reports.** `--record` also commits the curated and native-deck
  DRC reports (`layout/drc/reports/<cell>/<record-id>.drc{,-klayout}.json`)
  and, on the `klt` LVS route, the request + report pair
  (`layout/lvs/reports/<cell>/<record-id>.lvs-request.json` /
  `.lvs.json`), each named by the same record id as the run record it
  accompanies. Append-only like records; `klt drc --check` /
  `klt lvs --check` re-verify a report against the committed inputs, and
  `klt signoff <drc-report> <lvs-report>` aggregates a cell's pair into one
  verdict.

## Friction filed upstream

Per CLAUDE.md's friction protocol, the gaps this bring-up hit are filed
generically against [klayout-tools](https://github.com/2AMLogic/klayout-tools):

- [#172](https://github.com/2AMLogic/klayout-tools/issues/172) — `klt drc`
  ignores the layout's database unit (above).
- [#173](https://github.com/2AMLogic/klayout-tools/issues/173) — `klt drc` can
  only run its own built-in decks; there is no way to point it at the deck the
  PDK ships. This is why stage 4 drives the PDK's deck directly.
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
`klt` calls was real, available work, but not a free swap** — and it is done
(#784): stage 4 drives the PDK deck through `klt drc --engine klayout` with
the declared rule-category set asserted, stage 5 routes per cell (`klt lvs`
for all three cells), the negative controls run through the
same route as their stage 5, the raw deck invocation survives as
`--parity-raw-deck` and all three cells' records show both routes agreeing.
`passives` was the last cell on the raw LVS path; it moved once
[#7030](https://github.com/2AMLogic/klayout-tools/issues/7030) and
[#7031](https://github.com/2AMLogic/klayout-tools/issues/7031) landed.
