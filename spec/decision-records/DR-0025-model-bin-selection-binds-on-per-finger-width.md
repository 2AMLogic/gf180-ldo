# DR-0025: gf180mcu model-bin selection binds on the per-finger width `W/NF`; this repo pins it in the deck rather than inheriting it from the host

- **Status**: proposed (ratification tracked in **#219**) -- ratification is
  the operator's, the same process
  DR-0001, DR-0007, DR-0008 and DR-0012 through DR-0023 went through.
  This record proposes **no** `design/` change and **no** spec-value change:
  it ratifies a simulation convention and records the evidence that the
  existing `sim/` evidence trail is unaffected by it. The `sim/harness`
  change that implements the convention ships in the same pull request,
  because it is measurably inert on any host where a record could have been
  produced at all (see "Evidence", E6/E7).
- **Date**: 2026-09-15
- **Decided by**: agent-builder, issue #214 (recommendation only)

## Context

Issue #214 reported that **every** ngspice invocation on one builder host
that exercises `design/netlist/ldo_core.spice` aborts at parse time:

```
m.xdut_full.xmpass.m0 vout_full loop_full vin vin pfet_03v3 w=2.0e-03 ... nf=4.0e+01 ...
could not find a valid modelname
```

Root cause as filed, and confirmed here: `sm141064.ngspice`'s `pfet_03v3`
model cards are **binned** on `(L, W)`, and the widest declared bin stops at
`wmax = 0.000100001` (100.001 µm). `design/netlist/ldo_core.spice`'s pass
device is

```
XMpass VOUT PASS_GATE VIN VIN pfet_03v3 L=0.28u W=2000u nf=40 ...
```

— `W = 2000 µm`, which is 20× the widest bin's ceiling. The issue then raised
the much larger question this record exists to answer: if `W = 2000 µm` is out
of every declared bin's range, **what bin did every committed `sim/` record
actually simulate the pass device against?** The issue framed the fork as
(a) some hosts resolve `W/nf` against the bins, or (b) some hosts *silently
extrapolate or clamp* to the nearest bin — and observed that under the
`ngbehavior=hsa` workaround, `sim/startup`'s `tt_27c_3.30v` settling time
moved from the committed 3.79753 ms to 5.52559 ms (+45.5%), which, if it were
a binning effect, would put **DR-0006's just-ratified 6 ms startup bound** on
evidence taken against the wrong device model.

Both halves of that fork turn out to be wrong, and the settling-time shift has
nothing to do with binning. The evidence is below.

## Evidence

All measurements below are on the filing host (Linux, `ngspice-46` KLU,
binary sha256 `c874869b16dc8a31cfa9d37d2b90a2a9e0e5b996f8e2535db89eb82855072931`),
against the pinned PDK `gf180mcuD @ c6d73a35f524070e85faff4a6a9eef49553ebc2b`.

**E1 — the bin table.** `pfet_03v3` has 16 bins per process-corner group
(5 groups), on a 4 × 4 `(L, W)` grid. The `W` edges are
`0.22 / 0.5 / 1.2 / 10 / 100.001 µm`; the `L` edges are
`0.28 / 0.5 / 1.2 / 10 / 50.001 µm`. `pfet_03v3.12` is the
`L ∈ [0.28, 0.5) µm × W ∈ [10, 100.001] µm` cell. Nothing in the file covers
`W = 2000 µm`.

**E2 — which bin ngspice actually resolves.** A minimal deck instantiating
exactly the pass device's geometry through the PDK's own `.subckt pfet_03v3`
wrapper, with `set wnflag=1`, and `show` dumping the instantiated device:

```
 BSIM4v5: Berkeley Short Channel IGFET Model-4
     device              m.xmp.m0
      model          pfet_03v3.12
          l               2.8e-07
          w                 0.002
         nf                    40
```

Two things are established at once, and neither was previously verified
anywhere in this repo: the resolved bin is **`pfet_03v3.12`**, a normally
declared bin — *not* an extrapolation — and the instance's `w` is still
`0.002` (2000 µm, **undivided**). `wnflag` governs bin **selection** only; the
model evaluation keeps the total width.

**E3 — `W` is the total width, so `W/nf` is the physically right selector.**
Two devices at identical bias, `W=2000u nf=40` and `W=50u nf=1`:

```
i(vd1) = 1.2947171822e-01
i(vd2) = 3.2367929571e-03
i(vd1)/i(vd2) = 3.9999999982e+01
```

Exactly 40×. The pass device is forty fingers of 50 µm, each finger squarely
inside bin 12's 10–100.001 µm range. Binning on `W/NF` is not a compatibility
kludge — it is the only reading under which the geometry the netlist describes
lands in a bin the foundry fitted for it.

**E4 — ngspice never clamps or extrapolates.** A device whose *per-finger*
width is genuinely out of range (`W=150u nf=1`, above every bin's `wmax`)
fails with the same `could not find a valid modelname` under **both**
`wnflag=1` and `ngbehavior=hsa`. Measured, ngspice has exactly two outcomes:
a declared bin, or a hard parse error. **There is no silent-extrapolation
path**, so the issue's hypothesis (b) — "that host's ngspice silently
extrapolated to the nearest bin" — is ruled out for any host whose deck ran at
all.

**E5 — what turns it on.** Bin resolution for this device, per `.spiceinit`
setting:

| setting | result |
|---|---|
| *(none — "No compatibility mode selected!")* | `could not find a valid modelname` |
| `set wnflag=0` | `could not find a valid modelname` |
| `set wnflag=1` | `pfet_03v3.12` |
| `set ngbehavior=hs` (HSPICE) | `pfet_03v3.12` |
| `set ngbehavior=hsa` (HSPICE + all) | `pfet_03v3.12` |
| `set ngbehavior=spe` (Spectre) | `pfet_03v3.12` |
| `set ngbehavior=a` / `eg` | `could not find a valid modelname` |
| `set ngbehavior=ps` / `lt` | n/a — these break `.lib <file> <section>` before binning is reached |

`.options wnflag=1` **inside the deck** is equivalent to `set wnflag=1` for
this purpose, provided nothing has explicitly set the variable to 0 first
(verified both ways).

**E6 — `ngbehavior=hsa` is numerically a no-op relative to `set wnflag=1`.**
Running `sim/startup` at `tt_27c_3.30v` on the current tree with a plain
`set wnflag=1` (no compatibility mode) reproduces issue #214's `hsa` column
digit for digit:

| measurement | #214's `ngbehavior=hsa` | this record, `set wnflag=1` |
|---|---|---|
| `tsettle_full_ms` | 5.52559 | 5.52559 |
| `overshoot_full_mv` | -37.51 | -37.51 |
| `tsettle_min_ms` | 5.52495 | 5.52495 |
| `vfinal_short_v` | 0.0756207 | 0.0756207 |
| `ipeak_short_ma` | 77.3942 | 77.3942 |

So the workaround never selected a "different bin" — it selected the same
bin 12, by a blunter route.

**E7 — the ~45% shift is the DUT netlist, not the model bin, and the
committed record reproduces cross-host.** `sim/startup/testbench/tb_startup.spice`
is byte-identical to the one that produced the committed record
(`aaf4d1027cae8cfb28689ca7da11490e02b1efcc54eba421b83ee6dbfa81721e`), but
`design/netlist/ldo_core.spice` is not: the record was taken against
`f32ebdd07be…`, and HEAD carries `a6718bc6e4…` after the #188 / #189 / #191 /
#195 / #197 soft-start and compensation work merged in the intervening week.
Restoring the DUT netlist to the **exact recorded sha** and re-running this
host, same ngspice, same `wnflag=1`:

| | `tsettle_full_ms` | `overshoot_full_mv` | `ipeak_short_ma` |
|---|---|---|---|
| committed record (macOS host, 2026-09-06) | 3.79753 | -27.238 | 79.0348 |
| this host, recorded DUT sha | 3.79753 | -27.238 | 79.0349 |
| this host, HEAD DUT | 5.52559 | -37.51 | 77.3942 |

Extended to the full 45-point overlap between the two runs
(tt/ff/ss/fs/sf × −40/27/125 °C × 2.97/3.30/3.63 V):

| field | worst relative deviation, record vs. re-run |
|---|---|
| `tsettle_full_ms` | **0.00000 %** (bit-identical at all 45 points) |
| `vfinal_short_v` | **0.00000 %** (bit-identical at all 45 points) |
| `tsettle_min_ms` | 0.00024 % (one point, last printed digit) |
| `overshoot_full_mv` | 0.071 % (`tt_-40c_2.97v`) |
| `overshoot_min_mv` | 0.191 % (`tt_-40c_2.97v`) |
| `ipeak_short_ma` | 0.259 % (`tt_-40c_2.97v`) |

Two independently-provisioned hosts, different operating systems, different
ngspice builds, reproduce the same settling times to every printed digit. That
is only possible if both resolved the same model bin. Combined with E4 (no
extrapolation path exists), the host that produced the committed record — and
#204's host, which ran the same pinned PDK and ngspice-46 with no crash —
resolved `pfet_03v3.12`, exactly as this host does.

**E8 — `XMpass` is the only device whose raw `W` leaves the bin table, and no
other device is near a bin edge.** All 104 FET instantiations across
`design/netlist/*.spice` were enumerated with their `W`, `L` and `nf`, sorted
by per-finger width `W/NF`:

| `W/NF` | device | `W` | `L` | `nf` | resolved bin |
|---|---|---|---|---|---|
| 50 µm | `XMpass` | 2000 µm | 0.28 µm | 40 | `pfet_03v3.12` |
| 50 µm | `XMsense` (`Xilimit`) | 50 µm | 0.28 µm | 1 | `pfet_03v3.12` |
| 50 µm | `XMclamp` (`Xilimit`) | 50 µm | 0.5 µm | 1 | `pfet_03v3.13` |
| 25 µm | `XMen` | 50 µm | 0.28 µm | 2 | `pfet_03v3.12` |
| ≤ 20 µm | everything else (100 instances) | — | — | — | — |

**Zero devices have `W/NF > 100.001 µm`**, so under the `W/NF` rule ratified
below every device in the design lands in a declared bin. `XMpass` is the
only instance anywhere whose *raw* `W` (2000 µm) exceeds the widest bin's
`wmax`, because it is the only multi-finger device with `nf > 2`. There is no
second instance of this exposure to find.

The two devices that share `XMpass`'s exact finger geometry are `XMsense`
(`W=50u nf=1`, `L=0.28u`) — the 1/40 current-sense replica DR-0005's limit
window depends on — and `XMen`, and all three resolve to `pfet_03v3.12`,
which is what a replica needs. (`XMclamp` is the same 50 µm finger at a
longer `L=0.5u` and therefore bins one cell over, at `pfet_03v3.13`; it is
not a replica of anything and nothing depends on it matching.)

**E9 — the deck-level pin fixes the failure and changes nothing else.** Two
harness-generated `startup` decks for `tt_27c_3.30v` against the identical DUT
netlist — one from the harness as it was, one from the harness with the pin —
run from a working directory whose `.spiceinit` contains **no** `wnflag` and
**no** compatibility mode (ngspice's own default state, and exactly the
condition issue #214 filed against; a local `.spiceinit` replaces the home
one rather than adding to it):

```
### pinned deck, default-host .spiceinit
Note: No compatibility mode selected!
m_tsettle_full_ms   = 5.5255890000e+00
m_overshoot_full_mv = -3.751000000e+01
m_tsettle_min_ms    = 5.5249530000e+00
m_vfinal_short_v    =  7.5620680000e-02
m_ipeak_short_ma    =  7.7394240000e+01

### unpinned deck, same default-host .spiceinit
Note: No compatibility mode selected!
could not find a valid modelname
```

The pinned deck's numbers are identical to the same deck run on this host's
`wnflag=1` `~/.spiceinit`, to every printed digit. The pin is a provenance
fix, not a numerical one.

**E10 — reconciling #204: the "does not reproduce" hosts were the
misconfigured ones.** Issue #204 reported this exact error on the
`.include`-based benches, was downgraded when a peer host ran the same benches
end to end against the same pinned PDK and `ngspice-46`, and was closed
2026-09-13 as "environment-specific" — attributed to a stale `volare fetch` or
a shadowing `ngspice` on `PATH` (the #182/#184 toolchain-identity theme). E1
through E9 invert that verdict without contradicting the observations.

The host this record was produced on is one of the hosts where the benches
*do* run, and its `~/.spiceinit` — mtime 2026-09-09, i.e. four days before
#204 was closed — contains:

```
* Restore per-finger model binning for the gf180mcu PDK.
* ... ngspice only divides W by NF for bin selection when the cp variable
* `wnflag` is 1 (see src/spicelib/parser/inpgmod.c, INPgetModBin) ...
set wnflag=1
set num_threads=1
```

An earlier agent had already root-caused this correctly and fixed it **in a
home-directory file that is not in this repository**, where no record, no
document, and no reviewer could see it. That is the entire discrepancy: the
PDK fetch was never stale and no binary was ever shadowed. The hosts that
"reproduced #204" were running a stock ngspice; the hosts that "did not
reproduce" were carrying an undocumented, uncommitted `wnflag=1` out of band.
Every committed record was produced by the latter kind of host — correctly
binned, as E7 proves digit for digit, but for a reason nothing in the
evidence trail captured. Decision 3 moves that setting out of the home
directory and into the deck, where it is reviewable.

## Decision

1. **Ratify `W/NF` — the per-finger width — as the quantity gf180mcu model
   binning selects on in this repo**, and `pfet_03v3.12` as the pass device's
   (and `Msense`'s) bin. This is a statement of the PDK's intent, supported by
   E2/E3: the netlist's `W` is the total device width and the model evaluation
   uses it as such; only bin *selection* divides by `NF`.

2. **`design/netlist/ldo_core.spice` and `design/ldo_ilimit.sch` are correct as
   written and are not changed by this record.** `XMpass`'s `W=2000u nf=40` is
   the right way to express a 2 mm pass device, and `XMsense`'s `W=50u nf=1` is
   the right way to express its single-finger replica.

3. **Pin bin selection in the deck.** `sim/harness/runner.py`'s `compose_deck`
   now emits `.options wnflag=1` into every generated deck, ahead of the design
   includes, and `sim/harness/report.py` records that in every new record's
   Environment section. Bin selection stops being a property of whichever
   host's `~/.spiceinit`/`spinit` happens to be in play and becomes a property
   of this repo's decks, captured in the evidence.

4. **No `sim/` record is re-baselined on model-bin grounds.** Not `startup`,
   not `current-limit`, not `dropout-vs-load`, not `enable-shutdown`, not
   `op-point-sanity`, not `soft-start`, not any other suite that instantiates
   `XMpass`. E4 makes this exhaustive rather than a sample: a run that did not
   resolve bin 12 would not have produced a record at all — it would have died
   at parse time on the fatal-log gate. Every committed record exists *because*
   its host had `wnflag=1` in effect.

5. **DR-0006's 6 ms startup settling bound does not need re-evaluation on
   model-bin grounds.** Its evidence
   (`sim/startup/records/20260816-100018-af4d1f9.md`, and the fresher
   `20260906-004356-3093ea1.md`) was taken against bin 12, the bin this record
   ratifies. The +45.5% settling shift that raised the alarm in #214 is E7's
   DUT-netlist difference and not a modelling artifact. See "Consequences" for
   the separate, real question that shift does raise.

## Alternatives considered

- **Restate `XMpass` as `W=50u` (pre-divided by `nf`), so it bins under
  `wnflag=0` too.** Rejected, and issue #214's own scratch experiment shows
  why: it collapses `vout_full` to ~0.13 V at 50 mA, because `W` is the
  *total* width (E3) and dividing it by 40 divides the drive by 40. Expressing
  it as `W=50u nf=1 m=40` would preserve the drive, but it would restate a
  device that is already correct in order to accommodate a simulator default,
  would force the same restatement on `Msense`, and would invalidate the
  entire committed evidence trail for a device whose netlist was never wrong.

- **Set `ngbehavior=hsa` (in the deck, a `spinit`, or a documented
  `~/.spiceinit`).** Rejected as over-broad. It resolves the bin (E5) and is
  numerically identical here (E6), but it switches ngspice's whole parser into
  HSPICE compatibility — `.param` semantics, function syntax, suffix handling —
  to buy one flag. `wnflag=1` is the surgical setting and is what this record
  pins.

- **Document a required `~/.spiceinit` and leave the decks alone.** Rejected.
  That is the status quo the issue correctly objected to: it makes a
  model-selection decision an unrecorded property of the machine, which is
  precisely what "verification is the product" cannot tolerate.
  `sim/soft-start-loop-gain/` already worked around this per-suite with its own
  `.options wnflag=1` and generated `.spiceinit`, and its README flagged that
  "the other benches in this repo have the same exposure and no such pin" as a
  separate filing. This record is that filing's resolution, at the harness
  level, for all suites at once.

- **Re-baseline every suite that touches `XMpass` anyway, defensively.**
  Rejected as unjustified churn: E4 and E7 together show there is nothing to
  correct, and minting superseding records that reproduce their predecessors
  digit for digit would add noise to an append-only evidence trail without
  adding information.

## Consequences

- **The `could not find a valid modelname` failure mode is closed for the
  harness path.** Any host with a default (non-compatibility) ngspice can now
  run `sim/run_corners.py` against decks that instantiate the pass device.
  Issue #128, blocked on exactly this, is unblocked.

- **New records carry a model-binning line in their Environment section.**
  Existing records do not, and are not edited (append-only). What makes the
  older records interpretable is this record's E4/E7 argument, not a field in
  the file.

- **The pin is defeatable by a host that sets `wnflag=0` explicitly — and that
  case fails loud, never silently wrong.** `.options wnflag=1` cannot override
  an explicit `set wnflag=0` in a `spinit`/`.spiceinit` that is read first;
  measured, the pinned `startup` deck run from a directory whose `.spiceinit`
  contains `set wnflag=0` dies with `could not find a valid modelname`,
  identically to the unpinned deck of E9. This is the residual hole in
  "bin selection is now a property of the deck", and it is the harmless half
  of the failure space: by E4 there is no third outcome, so such a host
  produces **no record**, rather than a record taken against a different bin.
  Nothing in `sim/` can therefore be a silently mis-binned result — which is
  the property decision 4 rests on.

- **A testbench manifest cannot override the pin, and is refused rather than
  ignored.** The "first setting wins" rule of E5 is not specific to
  `.spiceinit` vs. deck: measured on `ngspice-46`, two `.options` cards naming
  the same key resolve to the **first** card, silently, with no warning —
  `.options wnflag=1` followed by `.options wnflag=0` runs with binning on,
  and the reverse order dies with `could not find a valid modelname`. The
  harness therefore emits its pin as the first `.options` card (that ordering
  is what makes it authoritative) and rejects a manifest `options` entry that
  sets `wnflag` at all, instead of emitting a card ngspice would discard
  without telling anyone. `sim/tests/test_ngspice_options_precedence.py` pins
  this simulator behaviour with a real run so the claim cannot rot.

- **Inert where it matters, by measurement.** On a host that already had
  `wnflag=1`, adding the card changes nothing: E7's 45-point re-run of the
  committed record is the control, and it lands bit-identical on the settling
  columns. The pin cannot change a number that a record already contains,
  because a host without it could not have produced that record.

- **Bad consequence, and the real finding hiding behind this issue:
  DR-0006's 6 ms bound is now in doubt on *design* grounds.** DR-0006 set 6 ms
  as 5.82788 ms (the worst measured point, `ss_-40c_3.63v`) plus ~3%. That
  measurement was taken against the pre-#188/#189/#191/#195/#197 DUT. On the
  current DUT, the same testbench, host and bin give 5.52559 ms at
  `tt_27c_3.30v` where the recorded netlist gave 3.79753 ms — 1.455×. If the
  `ss_-40c_3.63v` corner moved by anything like that factor it would land well
  above 6 ms. **This record does not resolve that**, and deliberately does not:
  it is a consequence of the soft-start compensation work, not of model
  binning, and it needs its own evidence run and its own record. Filed as
  **#220**. Nothing here should be read as clearing DR-0006 against
  the current design — only against the accusation that its evidence used the
  wrong device model.

- **`ngspice-42` and `ngspice-47` are not verified here.** Issue #214 reported
  that all four builds on its host (`42`, two `46`s, `47`) reject the raw
  `W=2000u` identically, so all four implement the same bin check; but only
  `ngspice-46` is installed on the host that produced this record, so the
  deck-level `.options wnflag=1` pin is confirmed working on `46` alone. Filed
  as **#221** rather than asserted. Note that by E4 the downside of a build
  that ignored the card would be a *broken run*, never a mis-binned record.

## Cross-consequences (other records)

- **DR-0006**: its evidence is confirmed to have used the ratified bin, so the
  model-binning objection against it is withdrawn. A separate re-evaluation
  against the current DUT is warranted and is filed as **#220**; the 6 ms
  number is not touched by this record.
- **DR-0005**: unaffected, and mildly reinforced. `Msense` is one finger of
  `Mpass`'s geometry, and under `W/NF` binning the two devices land in the same
  bin — the matching condition the 1/40 replica needs. Under raw-`W` binning
  the replica would bin in `pfet_03v3.12` while the device it replicates binned
  nowhere at all.
- **DR-0021 / DR-0023 and every other record citing a `sim/` number**:
  unaffected. E7 establishes that the committed numbers are reproducible on an
  independent host.
