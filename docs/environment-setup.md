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
| ngspice | **46_1** | Homebrew (`ngspice`) |
| volare | **0.20.6** | Homebrew / pip (`volare`) |
| gf180mcu PDK | commit hash **`c6d73a35f524070e85faff4a6a9eef49553ebc2b`** | `volare fetch` |
| Build deps | `cairo` 1.18.4, `tcl-tk@8` 8.6.18, `xorgproto` 2025.1, XQuartz (cask), `bison`/`flex` (system, not Homebrew) | Homebrew / macOS system tools |

The gf180mcu hash above matches the one pinned in `gf180-bandgap`'s own
`docs/environment-setup.md` -- reuse it verbatim across sister gf180 canary
repos (pinned, not "latest"; re-running `volare ls-remote` later will show
newer hashes -- do not silently switch without updating this doc and
re-validating the harness self-test in §6).

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
- [ ] Confirm `echo $PDK_ROOT $PDK` resolves correctly after sourcing your
      shell profile snippet from §4 (not just in the shell where you first
      set it).
- [ ] Confirm the gf180mcu hash in use is the **pinned** one recorded in §1
      (`volare output --pdk gf180mcu`), not silently "whatever `ls-remote`
      shows as newest today."
- [ ] Run `bash sim/selftest.sh --require-pdk` (see §6) and confirm it exits
      0 with the harness's own end-to-end PVT smoke run passing.

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
