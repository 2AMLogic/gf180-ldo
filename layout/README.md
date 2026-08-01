# layout/ — GDS, DRC and LVS

Physical verification for this repo, on the gf180mcu open PDK. **There is no
LDO layout yet.** What lives here today is the *flow*: a documented, one-command
DRC + LVS invocation, proven end to end against a deliberately trivial test
cell, so that whoever lays the block out inherits a working loop instead of
building one.

```bash
python3 layout/drclvs.py --check-env    # is everything installed?
python3 layout/drclvs.py                # build, export, DRC ×2, LVS, controls
python3 layout/drclvs.py --check        # ... and the committed netlist must be current
python3 layout/drclvs.py --record       # ... and write layout/records/<record-id>.md
```

A run takes about a minute and prints one line per stage:

```
[1/7] layout      : drclvs_testcell.gds (2592 bytes)
[2/7] netlist     : 1 device line(s), LVS form
[3/7] klt drc     : clean (0 violation(s), curated subset)
[4/7] pdk drc     : 0 violation(s) across 642 rule categories (41 rule tables)
[5/7] lvs         : MATCH
[6/7] control topo: gate shorted to drain -> MISMATCH (expected)
[7/7] control para: device width doubled -> MISMATCH (expected)
```

Exit status is 0 only if every stage passed. On failure the run directory
(`layout/.work/<record-id>/`, gitignored) is kept, with the raw KLayout logs,
the `.lyrdb` DRC report, the `.lvsdb` LVS database and the extracted netlist in
it.

## What is here

```
layout/
  drclvs.py                          the one command (see "The seven stages")
  xschemrc                           design/xschemrc + `lvs_netlist 1`
  testcell/
    drclvs_testcell.sch              the test cell, schematic side
    drclvs_testcell.sym              (exists only to force a real `.subckt`)
    gen_gds.py                       the test cell, layout side (a generator)
    netlist/drclvs_testcell.spice    the exported LVS reference netlist
  records/<record-id>.md             append-only run records
```

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

## The seven stages

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
41 rule tables, 642 rule categories. `drclvs.py` assembles the deck itself
rather than shelling out to `run_drc.py`, which needs `docopt` and drives its
own parallel run/report layout; what we want is one deck, one report, one exit
status. **This is the DRC number worth quoting.**

A deck that runs but registers *zero* rule categories produces an empty report
that is indistinguishable from a clean one — that is what a mis-assembled deck
looks like, so `drclvs.py` treats zero categories as a hard error rather than a
pass.

**5. LVS.** The PDK's own `gf180mcu.lvs`, layout against the netlist from stage 2.
The deck reports its own verdict in its log and exits 0 either way, so the log is
the contract; `drclvs.py` demands exactly one of the two verdict strings, so a
deck that fell over before comparing is an error rather than a silent pass.

**6 & 7. Negative controls.** The same compare, twice more, against deliberately
corrupted copies of the netlist. Both **must** mismatch:

| Control | Mutation | What it would mean if it matched |
| --- | --- | --- |
| topology | gate shorted to drain | a 4-net circuit compared equal to a 3-net one — the compare is not looking at connectivity |
| parameter | device width doubled | device parameters are not being compared at all |

These are not decoration. A "match" from an LVS run is not evidence unless a
*known-wrong* netlist fails: a mis-wired invocation that silently compares
nothing also "passes", and a compare that checks connectivity while ignoring
parameters would wave through a mis-sized transistor.

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
their rule-category counts, the LVS verdict and both control verdicts.

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
  controls in the contract. `klt` has no LVS verb today, which is why stage 5
  drives the PDK's deck directly.

When `klt` grows `lvs` and PDK-deck support, stages 4 and 5 should collapse into
`klt` calls and this file should shrink accordingly.
