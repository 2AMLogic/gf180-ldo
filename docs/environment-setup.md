# Environment Setup: xschem + ngspice + gf180mcu (macOS / Homebrew)

Bootstrap steps for the open-source design/sim flow described in
[`CLAUDE.md`](../CLAUDE.md): xschem (schematic capture / netlisting) +
ngspice (simulation) against the gf180mcu PDK (fetched via
[volare](https://github.com/efabless/volare)).

This doc is intended to be followed **verbatim, from a clean shell**, on any
fresh machine or agent session. It is ported from the reference bootstrap in
[2AMLogic/gf180-bandgap](https://github.com/2AMLogic/gf180-bandgap)'s
`docs/environment-setup.md` (CLAUDE.md: "Harness bootstrap: copy the
sim-harness pattern from gf180-bandgap ... rather than reinventing").

Recorded on macOS (Darwin, arm64) with Homebrew. If you are on a different
OS, the `xschem` source build steps are the same; substitute your platform's
package manager for the Homebrew dependency installs.

## 1. Versions used to validate this doc (2026-07-31)

| Tool | Version | Source |
|---|---|---|
| xschem | **3.4.7** (tag `3.4.7`) | built from source, see §2 |
| ngspice | **46_1** (banner `ngspice-46`) | Homebrew — see "Keeping the ngspice pin from drifting" below; `brew install ngspice` is **not** by itself a pin |
| volare | **0.20.6** | Homebrew / pip (`volare`) |
| gf180mcu PDK | commit hash **`c6d73a35f524070e85faff4a6a9eef49553ebc2b`** | `volare fetch` |
| Build deps | `cairo` 1.18.4, `tcl-tk@8` 8.6.18, `xorgproto` 2025.1, XQuartz (cask), `bison`/`flex` (system, not Homebrew) | Homebrew / macOS system tools |

The gf180mcu hash above matches the one pinned in `gf180-bandgap`'s own
`docs/environment-setup.md` -- reuse it verbatim across sister gf180 canary
repos (pinned, not "latest"; re-running `volare ls-remote` later will show
newer hashes -- do not silently switch without updating this doc and
re-validating the harness self-test in §6).

### Keeping the ngspice pin from drifting (#247)

**`brew install ngspice` installs the pinned version only until Homebrew
upgrades it.** homebrew-core's *unversioned* `ngspice` formula tracks
upstream: on 2026-09-18 it moved to **ngspice-47**, so on every host that had
run `brew upgrade` since, `brew --prefix ngspice` stopped pointing at the
46_1 this table pins. That is not a cosmetic drift -- ngspice-47 is a major
version this repo has never validated, and
[`DR-0025`](../spec/decision-records/DR-0025-model-bin-selection-binds-on-per-finger-width.md)'s
`.options wnflag=1` model-bin pin was established on ngspice-46 only (closed
issue #221 scoped re-validating it on other majors; that was not performed).

So the pin needs a mechanism that survives `brew upgrade`. **Either of these
two is a fully supported provisioning of this doc** -- pick one:

**Option A — a Homebrew install that cannot be moved by an upgrade.** Two
shapes, depending on where the host already is:

*A1, the host is still on 46_1:* pin the formula so `brew upgrade` skips it.

```bash
brew pin ngspice
brew list --pinned      # must list: ngspice
```

A pinned formula is never upgraded by a bare `brew upgrade`, so
`brew --prefix ngspice` keeps resolving to the 46_1 keg. This is the cheapest
fix and the one to apply **before** a host drifts.

*A2, the host has already moved past 46_1* (the state that produced #247 --
`brew --prefix ngspice` -> `.../Cellar/ngspice/47`): install 46_1 as a
**versioned, keg-only** formula. A versioned formula's prefix
(`$(brew --prefix)/opt/ngspice@46` -> `.../Cellar/ngspice@46/46_1`) cannot be
moved by an upgrade of the unversioned `ngspice`, and being keg-only it is
not linked into `$(brew --prefix)/bin`, so it coexists with whatever `ngspice`
is linked. homebrew-core ships no `ngspice@46`, so this means a local tap
carrying homebrew-core's 46_1 `ngspice.rb` under the versioned name:

```bash
brew tap-new local/ngspice46
brew extract --version=46 ngspice local/ngspice46   # writes Formula/ngspice@46.rb
# then, in the generated formula, confirm both of:
#   class NgspiceAT46 < Formula      (the versioned class name)
#   keg_only :versioned_formula      (add it if `brew extract` did not)
brew install local/ngspice46/ngspice@46
export PATH="$(brew --prefix ngspice@46)/bin:$PATH"   # keg-only: not auto-linked
```

The harness probes `brew --prefix ngspice@46` **before** `brew --prefix
ngspice` precisely so this install wins on a host that has both -- so the
identity check stops naming the unpinned ngspice-47 keg as the "correct"
root even before you touch `PATH`.

**Option B — bless the ngspice-46 install this host already has.** For a host
whose validated ngspice-46 is not a Homebrew keg at all (a from-source build
under `~/.local`, a Linux/apt install, a container image), export the prefix
it lives under:

```bash
export GF180_LDO_NGSPICE_ROOT="$HOME/.local"   # such that $ROOT/bin/ngspice is the pinned build
```

`GF180_LDO_NGSPICE_ROOT` takes priority over both Homebrew probes and is a
first-class supported mechanism, not an escape hatch: put it in the same
shell-profile snippet as the `PDK_ROOT`/`PDK` exports in §4 so it survives a
fresh shell. `python3 sim/run_corners.py --check-env` prints `provenance OK
(under <root>, via GF180_LDO_NGSPICE_ROOT)` once it is set correctly.

**What is *not* an option:** silently adopting whatever version `brew
--prefix ngspice` provides today. Moving this repo's evidence onto a new
ngspice major version is a spec-adjacent decision -- it requires DR-0025's
`wnflag` re-validation on that version (#221) and a ruling on every existing
record -- not a `PATH` edit. The identity check enforces this: it fails if
the resolved `ngspice` is not `ngspice-46`, **even when that binary really is
the one `brew --prefix ngspice` points at.**

#### The ngspice-46 builds already in `sim/*/records/` are an accepted, historical split

The pin above was not enforceable before #184's identity check, and the check
itself was pin-blind until #247. What that left behind is a **known,
accepted** split in the evidence tree: the committed records were produced by
several byte-different builds that all self-report `ngspice-46`. Census of
`sim/*/records/`, re-derived against `origin/main` at `e07ee92` (2026-09-18)
-- 15 of 132 records carry an `ngspice binary sha256` field at all (the field
postdates #182; earlier records predate it):

| ngspice binary sha256 | records | where |
|---|---|---|
| `e6038926…8523da2` | 7 | `loop-stability` ×1, `quiescent-current` ×3, `soft-start` ×2, `startup` ×1 |
| `555e04b8…2aa5dd5` | 4 | `soft-start` ×2, `soft-start-loop-gain` ×1, `startup` ×1 |
| `4f076ec8…900b10` | 3 | `loop-stability` ×1, `quiescent-current` ×1, `soft-start` ×1 |
| `c874869b…5072931` | 1 | `startup` ×1 |

(Note this is **four** builds, not the two named in #247 -- that issue quoted
the two it had met. A fifth, `6c5c98a9…afc8810`, appears on-disk in
`sim/loop-stability/records/20260906-090647-3981d88.md`'s own #182
investigation but was never the resolved binary for any record.)

**This split is documented, not reconciled, and that is deliberate.**
`sim/README.md`'s append-only rule means records are never rewritten or
regenerated to make a fingerprint column tidy; and the divergence is real,
not clerical -- that same loop-stability record measured ~2° of phase margin
and ~1 dB of gain margin moving between two of these builds on a
byte-identical netlist and PDK.

What it licenses and what it does not:

- Each record's own PASS/FAIL verdict against its own stated bar **stands as
  recorded**. A fingerprint split does not retroactively invalidate a
  verdict.
- A **comparison across two records with different fingerprints** is
  toolchain-crossing and cannot on its own carry a claim about the design --
  [`sim/README.md`](../sim/README.md)'s "Reproducibility caveat: a version
  string is not a content fingerprint (#182)" section is the governing rule,
  and #246's same-host/same-binary A/B (via
  `sim/soft-start/testbench/run.sh`'s `LDO_NETLIST` override) is the pattern
  to follow when a before/after is load-bearing.
- Going forward, the checks above are what stop the split from growing: a new
  record can only be minted on a host whose resolved `ngspice` is
  `ngspice-46` **and** lives under the pinned root, so a new fingerprint now
  means a new *pinned-version* build, not an unnoticed major-version jump.

## 2. Build xschem from source

`xschem` has **no Homebrew formula** on macOS (`brew search xschem` / `brew
info xschem` both come back empty; there is no relevant tap, and there is no
MacPorts `port` binary either as a fallback). Build it from the upstream
[xschem](https://github.com/StefanSchippers/xschem) repository:

```bash
# Build dependencies (Homebrew + macOS system tools):
brew install cairo tcl-tk@8 xorgproto
brew install --cask xquartz   # provides /opt/X11 (X11 headers/libs)
# bison and flex ship with the macOS command line tools (/usr/bin/bison,
# /usr/bin/flex) -- no separate install needed on a machine with Xcode CLT.

# Clone the exact tag this doc was validated against:
git clone --branch 3.4.7 https://github.com/StefanSchippers/xschem.git
cd xschem

# tcl-tk@8 is keg-only on Homebrew -- point configure/make at it explicitly:
export PATH="/opt/homebrew/opt/tcl-tk@8/bin:$PATH"
export PKG_CONFIG_PATH="/opt/homebrew/opt/tcl-tk@8/lib/pkgconfig:$PKG_CONFIG_PATH"
export LDFLAGS="-L/opt/homebrew/opt/tcl-tk@8/lib"
export CPPFLAGS="-I/opt/homebrew/opt/tcl-tk@8/include"

./configure --prefix=/opt/homebrew
make -j4
make install PREFIX=/opt/homebrew
```

(On Intel Macs, substitute `/usr/local` for `/opt/homebrew` throughout.)

Verify the headless netlist mode works against a trivial schematic (no GUI,
no PDK needed for this check):

```bash
xschem -n -x -q -r /opt/homebrew/share/doc/xschem/examples/lm317.sch -o /tmp
# no "Error:" lines expected; produces /tmp/lm317.spice
```

`-n` (netlist), `-x`/`--no_x` (headless, no X11 window), `-q` (quit after),
`-r`/`--no_readline` (safe for non-interactive/redirected stdin+stdout).

### A note on `~/.xschem/xschemrc` (machine-specific gotcha)

xschem loads, in order: the system-wide `xschemrc`, then
`~/.xschem/xschemrc` (**user**-level, overrides the system one), then a
project-local `./xschemrc` in the current working directory (overrides
both) -- **or** whatever file `--rcfile <path>` points at, if given.

If a machine already has a stale/unrelated `~/.xschem/xschemrc` (e.g. left
over from a prior, unrelated project), it can silently override
`XSCHEM_LIBRARY_PATH` and break even the generic `devices/` symbol library.
This repo does not yet have its own project-local `design/xschemrc` (schematic
entry lands in #8) -- once it does, always invoke xschem for this repo with
`--rcfile design/xschemrc` so behavior does not depend on whatever is (or
isn't) in any given machine's user-level dotfile, mirroring
`gf180-bandgap`'s `design/xschemrc`.

## 3. Fetch the gf180mcu PDK via volare

```bash
volare --version                              # expect 0.20.6 (or record whatever is installed)
volare ls-remote --pdk gf180mcu               # lists available commit hashes, newest first
volare fetch  --pdk gf180mcu c6d73a35f524070e85faff4a6a9eef49553ebc2b
volare enable --pdk gf180mcu c6d73a35f524070e85faff4a6a9eef49553ebc2b
volare output --pdk gf180mcu                  # confirm: c6d73a35f524070e85faff4a6a9eef49553ebc2b
```

This creates `~/.volare/gf180mcuA` / `gf180mcuB` / `gf180mcuC` / `gf180mcuD`
(symlinks into `~/.volare/volare/gf180mcu/versions/<hash>/...`) -- one
directory per gf180mcu voltage/rule-deck variant. Per
[`spec/decision-records/DR-0002-input-flavor.md`](../spec/decision-records/DR-0002-input-flavor.md),
this repo's primary design uses the **3.3 V flavor**, which is variant
**`gf180mcuD`**.

## 4. `PDK_ROOT` / `PDK` environment convention

```bash
export PDK_ROOT="$(volare path)"   # -> ~/.volare (volare's PDK root)
export PDK="gf180mcuD"             # the 3.3V variant this repo targets
```

So `$PDK_ROOT/$PDK` resolves to `~/.volare/gf180mcuD`, and the ngspice
models live under `$PDK_ROOT/$PDK/libs.tech/ngspice/`.

Add this as a small sourceable snippet rather than a one-off manual export,
e.g. append to your shell profile:

```bash
# gf180-ldo: xschem/ngspice/gf180mcu env (see docs/environment-setup.md)
export PDK_ROOT="$(volare path)"
export PDK="gf180mcuD"
```

Demonstrate it survives a fresh shell:

```bash
$ echo $PDK_ROOT $PDK
/Users/you/.volare gf180mcuD
```

## 5. Reproducibility checklist

- [ ] From a **new terminal** (nothing pre-sourced from a prior session),
      confirm `xschem --version` reports `XSCHEM V3.4.7` and `ngspice -v`
      reports `ngspice-46`.
- [ ] Confirm the ngspice pin cannot be moved out from under you by a
      `brew upgrade` — one of §1's "Keeping the ngspice pin from drifting"
      options is in place (`brew list --pinned` lists `ngspice`, **or**
      `brew --prefix ngspice@46` resolves, **or**
      `GF180_LDO_NGSPICE_ROOT` is exported from your shell profile).
- [ ] Confirm `echo $PDK_ROOT $PDK` resolves correctly after sourcing your
      shell profile snippet from §4 (not just in the shell where you first
      set it).
- [ ] Confirm the gf180mcu hash in use is the **pinned** one recorded in §1
      (`volare output --pdk gf180mcu`), not silently "whatever `ls-remote`
      shows as newest today."
- [ ] Run `bash sim/selftest.sh --require-pdk` (see §6) and confirm it exits
      0 with the harness's own end-to-end PVT smoke run passing.

### A version banner is not a toolchain identity (#182 / #184)

`ngspice --version` only reports what the binary *claims* to be, not what it
actually is. Issue #182 found two independently-built `ngspice-46` binaries
coexisting on one host with **different content**, both printing the exact
same version banner -- and found that this host's `PATH` was resolving a
self-built `~/.local/bin/ngspice` **ahead of** the Homebrew install this
section (§1) pins, with nothing catching the mismatch.

`python3 sim/run_corners.py --check-env` (`cmd_check_env` in
`sim/harness/cli.py`) now enforces toolchain identity, not just presence:

```bash
python3 sim/run_corners.py --check-env
```

- Reports the resolved `ngspice`'s version banner **and** a content sha256
  fingerprint (`ngspice_binary_sha256()` in `sim/harness/runner.py`, from
  #182) -- a banner match alone is not proof of a binary match.
- Resolves the *expected* toolchain root, in this order (`GF180_LDO_NGSPICE_ROOT`
  -> `brew --prefix ngspice@46` -> `brew --prefix ngspice`), and enforces
  **two** things against it -- failing loudly, non-zero exit with `MISMATCH`
  in the output, on either:
  1. **Version.** The resolved `ngspice` must report `ngspice-46` (§1's pin).
     This catches a host whose Homebrew `ngspice` upgraded under it: that
     binary really *is* under `brew --prefix ngspice`, so a containment check
     alone would have called it `OK` (#247).
  2. **Containment.** The resolved `ngspice` must live under the expected
     root, so a second, byte-different build of the *same* version cannot
     shadow the documented install. This is the original #182 failure mode.
- On the happy path it prints `provenance OK (under <root>, via <probe>)` and
  exits `0`; nothing changes for a correctly-provisioned host.

**If `--check-env` reports `MISMATCH`, read which side it blames** -- since
#247 the message distinguishes three cases and names the corrective action
for the one you are actually in:

| The message says | What happened | What to do |
|---|---|---|
| "reports ngspice-NN, but ... pins ngspice-46" | The `ngspice` on `PATH` is off the pinned major version | Install ngspice-46 per "Keeping the ngspice pin from drifting" (§1) and make it resolve first. **Do not** adopt the new major version to make the check pass |
| "it is the **ROOT** that has drifted off the pin here, not the binary" | Homebrew's unversioned `ngspice` moved past 46_1, so the *probe*, not your binary, is wrong | Apply Option A2 or Option B from §1. The message prints the exact `export GF180_LDO_NGSPICE_ROOT=...` line for this host |
| "This is the #182 failure mode" | Two ngspice-46 builds; a different one is shadowing the pinned install on `PATH` | `which -a ngspice` to see every candidate, then reorder `PATH` so the pinned install resolves first, or remove/rename the shadowing binary (e.g. a stale `~/.local/bin/ngspice`) |

Re-run `python3 sim/run_corners.py --check-env` afterwards and confirm it
reports `provenance OK`.

**If a host legitimately needs a different, already-validated toolchain
root** (a Linux/apt install, a from-source build, a container image -- this
doc is written for macOS/Homebrew per its title, and does not pin a portable
discovery rule for apt), bless it explicitly rather than letting
`--check-env` guess -- this is Option B in §1:

```bash
export GF180_LDO_NGSPICE_ROOT=/path/to/that/install/prefix
```

`GF180_LDO_NGSPICE_ROOT`, when set, takes priority over both `brew --prefix`
probes. On a host with neither probe resolving and no override set,
`--check-env` reports `provenance not verified` (not `OK`, not `MISMATCH`)
-- version and sha256 are still reported, plus a `note:` line if the version
is off the pin, but identity cannot be checked against a pin there. That
branch stays non-fatal on purpose: CI's `pvt-smoke` job deliberately runs
Ubuntu's apt ngspice (a *different* major version) as the standing #221
model-bin portability check.

### `could not find a valid modelname` on the pass device (#214 / DR-0025)

If a deck dies at parse time with

```
m.xdut_full.xmpass.m0 ... pfet_03v3 w=2.0e-03 ... nf=4.0e+01 ...
could not find a valid modelname
```

this is **not** a broken PDK fetch or a shadowed binary -- it is ngspice's
model-bin selection rule. gf180mcu's `pfet_03v3`/`nfet_03v3` cards are binned
on `(L, W)` and the widest declared bin stops at `wmax = 100.001 µm`, while
`design/netlist/ldo_core.spice`'s pass device is `W=2000u nf=40`: 40 fingers
of 50 µm. It lands in a declared bin (`pfet_03v3.12`) only if bin selection
divides `W` by `NF`, which is ngspice's `wnflag` -- 1 under HSPICE/Spectre
compatibility, 0 otherwise. `W` stays the *total* width in the model
evaluation either way; `wnflag` affects selection only. ngspice never clamps
or extrapolates to a neighbouring bin: the only two outcomes are the declared
bin and this hard error.

**The harness handles this for you.** `sim/harness/runner.py`'s
`compose_deck` pins `.options wnflag=1` in every generated deck, so anything
run through `sim/run_corners.py` (or `sim/selftest.sh`) works on a
default-configured ngspice with no `~/.spiceinit` at all. You only need the
setting by hand when invoking `ngspice` directly on a hand-written deck that
instantiates the pass device -- add `.options wnflag=1` to the deck, or
`set wnflag=1` to the `.spiceinit` in the directory you run from. Note that a
`.spiceinit` in the current directory **replaces** `~/.spiceinit` rather than
adding to it, so anything else you rely on there (e.g. `set num_threads=1`)
has to be repeated.

## 6. Next: the PVT corner harness

Everything above establishes the *install*. The evidence-producing harness
sits on top of it and resolves the same PDK by a superset of the same rules
(`GF180_PDK_PATH` -> `PDK_ROOT` + `PDK` -> `sim/pdk.local.json` ->
`sim/pdk.json` -> the usual install prefixes, volare first), so the
`PDK_ROOT`/`PDK` exports from §4 are all it needs:

```bash
python3 sim/run_corners.py --check-env   # what the harness resolved, or how to fix it
python3 sim/run_corners.py --print-env   # shell exports for the resolved PDK
source sim/env.sh                        # same exports, for xschem and ad-hoc ngspice
bash sim/selftest.sh                     # unit tests + an 81-point PVT smoke run
```

Unlike `gf180-bandgap`, this repo does not yet have a standalone
`sim/smoke_test/` install-only check (that repo's, driven from a bespoke
`design/smoke_test.sch`, exists mainly to validate the xschem netlisting step
in isolation) -- schematic entry has not landed here yet (#8). Until it does,
`sim/smoke-bias/` (via `bash sim/selftest.sh`) is both the install check
*and* the harness acceptance test: it exercises ngspice + the gf180mcu models
directly (bypassing xschem netlisting, which nothing in this repo needs yet)
across the full 81-point PVT grid.

`design/xschemrc` (once #8 lands schematic entry) must resolve the PDK by
that same superset of rules, so xschem and the corner runner never disagree
about which PDK is in use; compare `sim/run_corners.py --print-env` against
the path xschem reports if you ever suspect they have drifted apart.

The full harness reference -- PDK resolution, corner definitions, how to
write a testbench manifest, and the `sim/smoke-bias/` acceptance test -- is
[`sim/harness/README.md`](../sim/harness/README.md). The record format it
writes into is [`sim/README.md`](../sim/README.md).

## 7. Also: DRC/LVS (only needed for `layout/`)

Physical verification needs two tools beyond the simulation flow. Neither is
required to run anything under `sim/`, so install them only when you touch
`layout/`.

| Tool | Version validated | Source |
|---|---|---|
| KLayout | **0.28.16** | `apt-get install klayout` (Debian/Ubuntu); [klayout.de](https://www.klayout.de) elsewhere. Needs to be the **standalone binary**, not just the `klayout` pip module -- the PDK's decks are run as `klayout -b -r <deck>`. |
| klayout-tools (`klt`) | **0.1.0** | `uv tool install klayout-tools`, or `pipx install klayout-tools` |

**The xschem version in §1 is load bearing for LVS specifically.** The LVS
reference netlist is produced by xschem's `lvs_format` mechanism, which does
not exist in xschem 3.4.4 -- the version Debian/Ubuntu package. On 3.4.4 the
switch is silently ignored and you get a simulation netlist, which KLayout's
SPICE reader mis-reads into a meaningless mismatch. Build 3.4.7 per §2;
`layout/drclvs.py` detects the wrong netlist form and fails with a pointer
rather than running a bogus compare.

Check the whole set, and what the PDK resolver found, with:

```bash
python3 layout/drclvs.py --check-env
```

The DRC/LVS flow itself -- what it runs, what each result does and does not
establish, and the known tool caveats -- is
[`layout/README.md`](../layout/README.md).
