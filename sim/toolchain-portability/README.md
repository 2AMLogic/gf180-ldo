# `sim/toolchain-portability/` — is a claim a property of the design, or of the simulator?

Every other experiment directory under `sim/` measures the **design**. This
one measures the **toolchain**, because two of this repo's load-bearing claims
are not statements about the LDO at all:

- [`DR-0025`](../../spec/decision-records/DR-0025-model-bin-selection-binds-on-per-finger-width.md)
  pins `.options wnflag=1` into every generated deck so gf180mcu model-bin
  selection binds on the per-finger width `W/NF`. Whether a card does that —
  and whether a *duplicate* card is honoured or discarded — is ngspice
  behaviour, established on ngspice-46 and on nothing else.
- [`sim/README.md`](../README.md)'s "a version string is not a content
  fingerprint (#182)" caveat exists because two *same-version* ngspice-46
  builds were measured moving phase margin ~2° and gain margin ~1 dB on a
  byte-identical netlist and PDK
  (`sim/loop-stability/records/20260906-090647-3981d88.md`).

`docs/environment-setup.md` §1 pins ngspice-46 and states that moving off it
is a spec-adjacent decision requiring DR-0025's re-validation on the new
version. Issue #221 scoped that re-validation and it was never performed;
issue #254 performed it. This directory holds the re-runnable form of that
measurement plus the evidence records it produced, so the next time the pin is
questioned the answer is a command, not an argument.

## What lives here

```
sim/toolchain-portability/
  testbench/
    wnflag_facts.py        # re-measure DR-0025's three wnflag facts on any ngspice
    ab_loop_stability.py   # same-netlist/same-PDK/same-host A/B across ngspice builds
  corners/
    <record-id>/           # raw ngspice logs + per-arm console logs + delta CSV
  records/
    <record-id>.md         # append-only evidence records (sim/README.md format)
```

There are no `netlist-snapshots/`: `wnflag_facts.py`'s decks are generated
inline and quoted verbatim into their own logs, and the A/B driver runs
`sim/loop-stability`'s testbench against the DUT netlist at the recorded
commit, which the record names.

## Re-running it on a new ngspice

### The three DR-0025 facts

```bash
python3 sim/toolchain-portability/testbench/wnflag_facts.py \
    --ngspice /path/to/ngspice \
    --log-dir /tmp/wnflag-facts
```

Exits `0` only if all three facts reproduce:

| | fact | DR-0025 evidence |
|---|---|---|
| **F1** | `.options wnflag=1` resolves `W=2000u nf=40` to the declared bin `pfet_03v3.12`, `w` undivided | E2 / E5 |
| **F2** | `wnflag=0` (and no card at all) fails to parse — `could not find a valid modelname`, never a silent clamp | E4 / E5 |
| **F3** | two `.options` cards naming the same key resolve to the **first**; the later one is silently discarded | "A testbench manifest cannot override the pin" |

Every probe runs in a throwaway working directory carrying a neutral
`.spiceinit`. That shadow is load-bearing, not hygiene: ngspice reads
`./.spiceinit` *instead of* `~/.spiceinit`, and DR-0025 E10 found the
reference host carrying an out-of-band `set wnflag=1` in its home directory.
Without the shadow the script would report F1 "passing" on a build that
ignores the card entirely.

### The numerical A/B

```bash
python3 sim/toolchain-portability/testbench/ab_loop_stability.py \
    --build ngspice-46-pinned=~/.local/ngspice/bin/ngspice \
    --build ngspice-47=~/.local/ngspice-47/bin/ngspice \
    --loads-ma 0 1 50 --caps-uf 0.33 1.0 4.7 --esrs 0.001 0.2 0.5 \
    -j 8 --out-dir /tmp/ab
```

Each arm is `sim/loop-stability/testbench/sweep.py` run with that install's
`bin/` first on `PATH` — the same selection mechanism
`20260906-090647-3981d88.md` used between its two ngspice-46 builds — so the
deck, the DUT netlist, the PDK and the host are identical across arms by
construction. The driver writes `ab-margins.csv` with a
`pm_deg` / `gm_db` column per arm and a `dpm_deg` / `dgm_db` delta column per
non-reference arm, in the same degrees / dB the existing comparison reports.

**Arms always run `sweep.py --no-write`, and that is deliberate.** An arm on
an unvalidated ngspice major must not mint a `sim/loop-stability` record: that
would inject a toolchain experiment into the design-evidence trail, where a
later rollup would read its DR-0001 verdict as a statement about the LDO. The
A/B's own findings belong in a record *here*, under this slug.

## Standing on a second install without disturbing the pin

`docs/environment-setup.md` §1 Option A2's principle — a *versioned* install
prefix that an upgrade of the unversioned one cannot move — is what makes this
whole directory cheap to re-run. On a Homebrew host that is a keg-only
`ngspice@46` formula. On a Linux host it is the same idea with `./configure
--prefix`:

```bash
curl -sL -o ngspice-47.tar.gz \
  "https://downloads.sourceforge.net/project/ngspice/ng-spice-rework/47/ngspice-47.tar.gz"
tar xf ngspice-47.tar.gz && cd ngspice-47
./configure --prefix="$HOME/.local/ngspice-47" \
            --disable-debug --with-readline=yes --enable-openmp=no
make -j8 && make install
```

Nothing is linked into `~/.local/bin`, so the pinned install keeps resolving
on `PATH` and `python3 sim/run_corners.py --check-env` keeps reporting the
pinned toolchain. Build the *comparison* arm the same way (same `configure`
flags, same compiler) — otherwise a measured delta cannot be attributed to the
version rather than to the build.

## What a record here may and may not conclude

A record under this slug is evidence about the **simulator**. It may say
"DR-0025's F1 reproduces on ngspice-47" or "the 46→47 per-point phase-margin
delta is bounded by X° over N points". It may **not** carry a DR-0001 (or any
other spec-line) verdict for the design: a run on an unpinned toolchain is not
design evidence, which is precisely the rule `sim/README.md`'s reproducibility
caveat and `docs/environment-setup.md` §1's pin exist to enforce. Moving the
pin is a separate, spec-adjacent decision that belongs to a decision record.
