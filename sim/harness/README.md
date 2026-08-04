# sim/harness — the PVT corner runner

Reproducible ngspice simulation against the gf180mcu PDK. This document covers
**how to run** the harness and **how to write a testbench**.

The *output* of a run — directory layout, record-id format, the summary record
field set, and the append-only rule — is defined by
[`sim/README.md`](../README.md), not here. That convention is authoritative;
this harness exists to produce records that conform to it.

Ported from the pattern ratified in
[2AMLogic/gf180-bandgap](https://github.com/2AMLogic/gf180-bandgap) (issue #2,
PR #23) — see `sim/README.md`'s provenance note for why this repo's evidence
format matches bandgap's Markdown convention rather than reinventing one. The
one deliberate divergence in the harness itself is the **Operating
conditions** record field below, which a bandgap (no load pin) does not need.

```
sim/
  run_corners.py            CLI entry point (stdlib python3, no venv)
  env.sh                    `source sim/env.sh` to export the same PDK to your shell
  selftest.sh               harness acceptance test (unit tests + end-to-end PVT run)
  pdk.json                  committed PDK defaults (variant, extra search roots)
  harness/                  the runner itself (this directory)
  tests/                    harness unit tests (no PDK, no ngspice required)
  .work/                    generated ngspice decks (git-ignored, disposable)

  <experiment-slug>/        one per claim under test -- see sim/README.md
    testbench/              tb.json + netlist fragment      <- you write these
    netlist-snapshots/      frozen netlist per record       <- the harness writes these
    corners/<record-id>/    raw <corner-id>.log per PVT point
    records/<record-id>.md  append-only summary record
```

## Quick start

```bash
python3 sim/run_corners.py --check-env     # is ngspice + the PDK present?
python3 sim/run_corners.py --list          # experiments, corners, corner sets
python3 sim/run_corners.py smoke-bias      # run the full PVT grid, mint a record
bash sim/selftest.sh                       # prove the harness works (writes nothing)
```

## Prerequisites

| Tool | Why | Install |
|---|---|---|
| `ngspice` | simulation | `brew install ngspice` / `apt-get install ngspice` |
| gf180mcu PDK | device models | `pip install volare && volare enable --pdk gf180mcu <hash>` |
| `xschem` | schematic capture (optional for simulation) | `brew install xschem` / distro package |
| python3 ≥ 3.9 | the harness | stdlib only, no packages |

See [`docs/environment-setup.md`](../../docs/environment-setup.md) for the full
bootstrap (xschem build-from-source, the pinned gf180mcu hash, and the
`PDK_ROOT`/`PDK` shell convention).

The harness never hardcodes a PDK path. It resolves one, in order:

1. `GF180_PDK_PATH` — the *variant* directory, e.g. `~/.volare/gf180mcuD`
   (the one containing `libs.tech/`).
2. `PDK_ROOT` (+ `PDK`, default `gf180mcuD`) — the open_pdks / OpenLane convention.
3. `sim/pdk.local.json` — machine-local, git-ignored.
4. `sim/pdk.json` — committed defaults.
5. Built-in search roots: `~/.volare`, `~/.ciel`, `/usr/share/pdk`,
   `/usr/local/share/pdk`, `~/share/pdk`, `/opt/pdk`.

If nothing is found the runner exits 3 with install instructions rather than
producing a misleading result. `sim/run_corners.py --print-env` emits the
resolved paths as shell exports; `source sim/env.sh` applies them so that an
interactive ngspice or xschem session uses the identical PDK. `design/xschemrc`
(once #8 lands schematic entry) must resolve the PDK the same way, so xschem
and the corner runner never disagree about which install is in use.

## The PVT grid

`CLAUDE.md` requires PVT corners on every recorded result, and
[`spec/decision-records/DR-0002-input-flavor.md`](../../spec/decision-records/DR-0002-input-flavor.md)
fixes the input at 3.3 V ±10 %. The defaults are baked into `corners.py` and
are what a testbench gets unless its manifest says otherwise:

- **Temperature**: −40, 27, 125 °C
- **Voltage**: nominal ±10 % (3.3 V flavor → 2.97 / 3.3 / 3.63 V)
- **Process**: see below

gf180mcu has no single global corner switch — each device family carries its
own `.lib` section in `sm141064.ngspice`, so a named corner here is a bundle of
six sections (MOS, resistor, BJT, diode, MOS cap, MIM cap):

| Corner | Meaning |
|---|---|
| `tt` | everything typical |
| `ff` / `ss` | every device family fast / slow |
| `fs` / `sf` | fast-N/slow-P and slow-N/fast-P, passives typical |
| `res_ff` / `res_ss` | resistor sheet rho skewed, rest typical |
| `bjt_ff` / `bjt_ss` | BJT skewed, rest typical |

Corner sets: `tt` (1), `mos` (5, the default — pass FET and error-amp MOS
skew), `full` (9 — add this for anything whose accuracy rides on the
feedback divider's resistors, e.g. an accuracy or trim claim).
`full` × 3 temperatures × 3 supplies = 81 operating points, a few seconds.

Each point becomes one `<corner-id>` — `<process>_<temp>c_<supply>v`, the
naming `sim/README.md` ratifies — and one raw log under
`corners/<record-id>/`.

Override any axis from the command line:

```bash
python3 sim/run_corners.py smoke-bias --corner-set full -j 8
python3 sim/run_corners.py smoke-bias --corners tt res_ss --temps -40 125
python3 sim/run_corners.py smoke-bias --supply 5.0 --supply-tol 0.10   # not this design's input (DR-0002 defers 5 V)
```

**Subsets need a reason.** `sim/README.md` requires every record's *Corner
matrix run* field to be the full mandated matrix "unless the record states why
a subset was used". The runner enforces that: if the grid you asked for is
missing a mandated temperature, a mandated supply, or has fewer than three
process corners, it refuses to write a record unless you supply
`--subset-reason '<why>'` (which is copied verbatim into the record), or pass
`--no-write` because you are only debugging.

```bash
# debugging: runs, records nothing
python3 sim/run_corners.py smoke-bias --corners tt --temps 27 --supply-tol 0 --no-write

# a deliberate, justified subset: runs and records, with the reason on the record
python3 sim/run_corners.py smoke-bias --corners tt --temps 27 \
    --subset-reason "nominal-only mismatch sweep; distribution claim, see Statistical convention"
```

## Writing a testbench

Create `sim/<experiment-slug>/testbench/` with a manifest and a netlist
fragment. The slug is the experiment directory from `sim/README.md`: one per
distinct claim under test, kebab-case.

`tb.json`:

```json
{
  "name": "my-experiment",
  "description": "one line, shows up in --list and in the record",
  "claim": "spec/ldo.md#dropout-voltage",
  "netlist": "my_tb.spice",
  "dut_netlist": "design/netlist/ldo_core.spice",
  "includes": ["../../../design/netlist/error_amp.spice"],
  "nominal_supply_v": 3.3,
  "supply_tolerance": 0.1,
  "temperatures_c": [-40, 27, 125],
  "corners": ["mos"],
  "analyses": ["op"],
  "params": {"iload": "50m"},
  "options": ["reltol=1e-5"],
  "nodeset": {"vout": "1.8", "loop": "0.7"},
  "operating_conditions": {
    "load_current": "50mA (full-load dropout point)",
    "output_cap": "1.0uF, ESR=100mOhm (nominal)",
    "enable_state": "enabled (EN = VIN), steady-state"
  },
  "measure": {"vdrop_mv": "(v(vin) - v(vout))*1e3", "iq_ua": "-i(vsup)*1e6"},
  "checks": {"vdrop_mv": {"max": 300.0, "description": "spec/ldo.md#dropout-voltage target"}}
}
```

`claim` is the default for the record's **Claim** field — the ratified spec
line this experiment substantiates. `--claim` overrides it per run.

`includes` and `dut_netlist` are the two halves of one mechanism: the design
netlists the harness includes for you. The netlist *fragment* (`netlist`
above, see "must not contain" below) may not `.include` anything, so anything
the fragment instantiates has to be named in the manifest. Both are emitted as
harness-owned `.include` lines ahead of the fragment, both are validated
against the same forbidden-directive rule, and both are frozen (path +
sha256, each behind its own header) into the record's single netlist snapshot.

- `includes` (#35) is the list of design cells — paths relative to the
  `testbench/` directory, e.g. `["../../../design/netlist/error_amp.spice"]`.
- `dut_netlist` (#12) *designates* which design netlist is the thing under
  test, written **repo-root relative** (e.g.
  `design/netlist/ldo_core.spice`). It is included first, and the record names
  it separately: the **Netlist provenance** field reads *schematic* normally
  and **extracted** when the path lives under `layout/` — that is how #16's
  post-layout re-run is recorded. Being repo-root relative is what makes it a
  usable CLI knob: `--dut-netlist PATH` re-points one manifest at a different
  netlist source per run (the same pattern as `--claim`) without forking the
  testbench. Naming the same file in both places includes it once.

Omit both for a testbench that instantiates only PDK primitives (e.g.
smoke-bias); omit just `dut_netlist` for a testbench that drives a design cell
without designating a DUT of its own (e.g. amp-openloop).

**`nodeset` (#40) biases the initial DC operating-point guess, without
constraining the converged answer.** A closed, high-gain feedback loop driven
from ngspice's default all-zero initial guess can have more than one
KCL/KVL-satisfying fixed point — plain Newton-Raphson can converge
"successfully" onto a non-physical one (e.g. the pass device latched off, with
an ideal current-sink load forcing the output rail to tens of volts to satisfy
KCL through parasitic leakage) instead of falling back to gmin/source
stepping, because it never fails to converge in the first place. `nodeset`
renders as `.nodeset v(<node>)=<value> ...`; pick values from a corner that
already converges to the physical solution (e.g. by adding a `print
v(<node>)` to a generated deck under `sim/.work/<slug>/<run-id>/` and
re-running it by hand with `ngspice -b`). It is a hint, not a constraint — it
only affects which basin of attraction the solver starts in. It is not a
universal fix: for a testbench that also sweeps load current or PVT supply
inside one deck (a `.dc`/`.tran` sweep, or several DUT instances sharing one
deck), a single nodeset value tuned to one bias point may still leave some
grid points on the wrong root, in which case treat that as a genuine open
problem per `sim/README.md` (see #40) rather than as evidence.

**Compliance-limited load sinks (#46) delete the unphysical root instead of
biasing the solver away from it.** `nodeset` above is a *hint* — for a
testbench that sweeps load current or PVT supply inside one deck (a
`.dc`/`.tran` sweep, or several DUT instances sharing one deck), a single
nodeset tuned to one bias point was found (#40, #46) to still leave a
persistent tail of grid points on the wrong root. The root cause: an ideal
current-sink load (`Iload VOUT 0 DC 50m`) demands its commanded current at
*any* terminal voltage, including tens of volts below ground — a genuine
second KCL/KVL-satisfying DC solution in which the pass device is off and
the sink pulls VOUT deeply negative to draw its current through forward-biased
substrate junctions in the PDK device models. No real load does that: a real
load stops sinking current once its terminal drops to (or below) its own
ground reference. Replacing the ideal sink with a **compliance-limited**
behavioral sink encodes that physical fact directly into the deck, so the
unphysical branch has no solution to converge to in the first place — this
is a stronger fix than a nodeset hint, and (unlike a nodeset) it is
insensitive to the sweep's or the multi-instance deck's own initial bias:

```spice
Vilc ILC 0 DC 1m
Bload VOUT NLOAD I = 'v(ilc) * 0.5 * (1 + tanh((v(vout) - 0.2) / 0.05))'
Vlmeas NLOAD 0 DC 0
```

- `Vilc` carries the *commanded* load current as a voltage (1 V == 1 A) —
  a control node only, so a `.dc`/`.tran` sweep of the load can drive it
  directly (`dc Vilc 1m 50m 49m`, or a `PWL` for a transient step) in place
  of sweeping/stepping the old `Iload` source.
- `Bload` is a behavioral current source that draws `v(ilc)` amperes out of
  `VOUT` through the ammeter `Vlmeas`, scaled by a smooth compliance factor
  `f(VOUT) = 0.5*(1 + tanh((VOUT - 0.2) / 0.05))` that is 1 for `VOUT` well
  above ground and 0 at or below it. At `VOUT >= 1.0 V` (this design's
  entire useful output range), `1 - f < 1.3e-14` and `df/dVOUT < 5.1e-13`
  per volt — under `2.6e-14 S` of small-signal conductance even at 50 mA,
  and smaller by another 14 orders of magnitude at the ~1.8 V the design
  actually regulates to. The sink is therefore an ideal current sink to well
  past double precision everywhere the design operates, including in
  small-signal (AC) analyses, where that residual conductance is negligible
  compared to the loop's own output impedance. (Pick the `0.2 V` knee and
  `0.05 V` softness to sit well below the lowest output voltage a deck
  legitimately visits — including transient undershoot — so the bound never
  engages on a real operating point.)
- `Vlmeas` is a zero-volt ammeter: `i(vlmeas)` reads the *actually delivered*
  current, so a testbench should measure and check it against the commanded
  value (e.g. `iload_50ma_ma: "i(vlmeas)[1]*1e3"`, checked with a tight
  `min`/`max` band) rather than assume compliance held. This is what turns
  "the sink is ideal to 1.3e-14" from a claim into a per-corner-checked fact.
  Pair it with a `vout`-range check where the deck has one (`dc_vout_v`,
  `vout_full_v`) so a record asserts *both* that the sink stayed ideal and
  that the solver landed on the physical root.

Two properties of the fix are worth knowing, both established by hand at
`tt_27c_3.30v` under #46 and reproducible with `ngspice -b` on a deck under
`sim/.work/<slug>/<run-id>/`:

- **It is analysis-order independent, which a `nodeset` is not.** ngspice's
  `ac` command solves its own operating point, so an `.op` listed before it
  does not steer it. With the old ideal sink, running `ac` cold gives
  `vdb(vout)@1kHz = +25.2 dB` — a small-signal expansion about the sub-ground
  root, i.e. PSRR = −25 dB — while `op` *then* `ac` happens to recover
  `−77.91 dB`. With the compliance-limited sink both orderings give
  `−77.91 dB`. The unphysical root is gone, not merely avoided by a lucky
  initial guess.
- **In a multi-instance deck the artifact is not confined to the instance
  that has the sink.** `sim/quiescent-current/` runs three `ldo_core`
  instances in one `.op`; only `_full` has a load. With the old ideal sink
  `_full` sat at `vout_full = −28.65 V`, *and* the unloaded `_en` instance
  was also off its physical root (`vout_en = 1.014 V` with `fb = 0.677 V`,
  nowhere near its 1.2 V reference). All instances share one Newton
  iteration over one matrix, so a pathological branch drags its deck-mates
  with it — do not assume a sibling measurement is trustworthy just because
  its own sub-circuit looks innocent.

This is a **testbench fix, not a harness-mechanism change** — no new
manifest field or runner code is needed, it is plain SPICE inside the
netlist fragment, so it composes with everything else `nodeset` and this
section describe. Reach for a compliance-limited sink instead of (or in
addition to) a `nodeset` hint whenever a deck's load sink is an ideal
current sink and the deck sweeps load/PVT/multiple instances in one run; a
`nodeset` alone remains the right (cheaper) tool for a single-instance
`.op`-only deck like `sim/dropout-vs-load/`. A deck that loads the DUT
**resistively** (e.g. `sim/startup/`) has no unphysical branch to begin with
and needs neither.

**Gotcha: `vdd_val`/`vdd_nom` are `.param`s, not vectors — reference the node
instead.** They work fine substituted into the *netlist fragment* itself
(`Vsup VIN 0 DC {vdd_val}`, standard SPICE `.param` substitution), but a bare
`vdd_val` inside a `measure`/`analyses` expression (evaluated by the control
block's `let`, not by SPICE's own parser) fails with `RHS "..." invalid` —
`let` only resolves plot vectors. Use the corresponding circuit node instead
(`v(vin)` gives the identical numeric value, since the fragment already tied
`VIN` to `{vdd_val}`).

`operating_conditions` is this repo's one addition to bandgap's convention
(see `sim/README.md`'s "LDO-specific extensions"): a free-form map rendered
verbatim as the record's **Operating conditions** field. Required whenever the
claim depends on load or the output network (dropout, load/line regulation,
stability, transients, startup — i.e. most LDO spec lines); omit only for
claims that are provably load-independent, and then say so explicitly, e.g.
`"operating_conditions": {"note": "N/A -- reference-only, output disconnected"}`.
A run's evidence record renders whatever keys are given (`load_current`,
`output_cap`, `enable_state`, or any other free-form key); if the manifest
supplies nothing at all, the record says so rather than silently omitting the
field. `--operating-conditions key=value` (repeatable) overrides/extends the
manifest per run, the same way `--claim` overrides the manifest's `claim`.

The netlist is a **fragment**, not a complete deck. It must not contain
`.include`, `.lib`, `.temp`, `.control`, `.endc` or `.end` — the harness owns
all of those, which is what lets one netlist sweep the whole grid unedited.
The loader rejects fragments that break this rule instead of silently pinning
every corner to 27 °C. The harness hands the fragment:

| Parameter | Value |
|---|---|
| `vdd_val` | supply for this PVT point |
| `vdd_nom` | nominal supply, for ratio measurements |
| `temp_c` | temperature for this PVT point (also applied via `.temp`) |

Each `measure` entry becomes `let m_<name> = <expr>` followed by `print` inside
the control block, so the expression must reduce to a **scalar**: fine for
`op`; for `tran`/`ac` reduce with `maximum()`, `mean()`, `v(out)[0]`, etc.

`checks` are evaluated after the sweep:

| Key | Applies to | Meaning |
|---|---|---|
| `min` / `max` | every point | hard limit; failure names the offending corner-id |
| `max_spread_pct` | the grid | `(max−min)/\|mean\|` must stay under the limit |
| `min_spread_pct` | the grid | must *exceed* it — asserts the sweep really moved |

`min_spread_pct` is a harness-integrity check: if `.temp` or a `.lib` section
silently failed to apply, a strongly PVT-sensitive measurement would come back
flat, and this catches that instead of reporting a suspiciously perfect result.

## What a run writes

One run mints one `<record-id>` (`<YYYYMMDD>-<HHMMSS>-<short-git-sha>`) and
writes, under `sim/<experiment-slug>/`:

| Path | Contents |
|---|---|
| `records/<record-id>.md` | the append-only summary record (the fields from `sim/README.md`, including the LDO-specific Operating conditions field, plus an Environment section with PDK / ngspice / harness / git provenance and the per-corner model sections) |
| `netlist-snapshots/<record-id>.spice` | verbatim frozen copy of the testbench fragment, with its sha256 |
| `corners/<record-id>/<corner-id>.log` | raw ngspice output, one file per PVT point |

Nothing is ever overwritten: the runner refuses to write over an existing
record or snapshot, and mints a later record-id if one is somehow already
taken. Corrections and re-runs get a new record-id and reference the prior one
with `--supersedes <record-id>`. Do not edit or delete anything under
`records/`, `netlist-snapshots/` or `corners/` — see the append-only rule in
`sim/README.md`.

A run taken against a dirty working tree says so in the record's **Netlist
provenance** field and is not citable as a clean-tree result. Git state is
sampled *before* the run starts (the run itself writes new evidence files
into the tracked tree, which would otherwise always self-report as dirty).

Exit codes: `0` pass · `1` a check failed · `2` a simulation failed or did not
converge · `3` environment problem (no ngspice, no PDK, bad manifest,
unjustified PVT subset).

Generated decks land in `sim/.work/<experiment-slug>/<record-id>/` and are
git-ignored, so a failing corner can be reproduced by hand with
`ngspice -b sim/.work/<slug>/<record-id>/<corner-id>.spice`.

## smoke-bias

`sim/smoke-bias/` is the harness acceptance test, not a circuit deliverable and
not a spec claim (its `operating_conditions` says so explicitly — see
`testbench/tb.json`). Three independent branches, each proving a different
part of the plumbing:

1. an ideal resistor divider — must read exactly 0.5·vdd at all 81 points,
   proving parameter substitution and measurement parsing;
2. a PDK `ppolyf_u` resistor into a diode-connected `nfet_03v3` — proves the
   MOS and resistor `.lib` sections load and actually change between corners;
3. a diode-connected `npn_10p00x10p00` at 10 µA — Vbe is strongly CTAT, so it
   proves `.temp` and the BJT corner take effect.

Run it directly, or via `bash sim/selftest.sh` which also runs the unit tests
first and skips (rather than fails) the end-to-end stage when the PDK/ngspice
are not installed.

## xschem

Schematic entry (`design/`, `design/xschemrc`) has not landed yet — see #8.
When it does, its `xschemrc` should resolve the PDK by this same order (env
var → `PDK_ROOT`/`PDK` → the usual install prefixes, volare first) so that
xschem and this harness never disagree about which install is in use; compare
`sim/run_corners.py --print-env` against the path xschem reports if they ever
seem to drift apart. `sim/env.sh` exports the harness's resolved PDK to any
shell so an interactive ngspice/xschem session sees the identical install.

Note: xschem itself is not required to run any of the above; the corner
runner only needs ngspice and the PDK.
