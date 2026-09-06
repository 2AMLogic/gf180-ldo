# `vref-transfer` / `vref-transfer-50ma` — `VREF`-to-`VOUT` transfer, and the reference accuracy-class budget

Issue #178, the follow-up campaign named by
[`DR-0021`](../../spec/decision-records/DR-0021-vref-is-a-top-level-port.md)'s
Decision #3 contract table ("Accuracy / tempco / noise / its own PSRR" row):
once `VREF` was promoted to a top-level `ldo_core` port, this became the
first campaign able to drive an AC stimulus directly onto it and measure
`|Vout(f)/Vref(f)|` instead of assuming the nominal `1/beta = 1.5` gain-up
DR-0003 already budgets the amplifier's own offset against.

This document covers **both** load conditions -- this bench (`vref-transfer`,
1 mA light load) and its full-load sibling
(`sim/vref-transfer-50ma/`, 50 mA) -- because the derived budget below is a
single number that has to hold at both. The two decks exist separately for
the same reason `sim/psrr-vs-freq/` and `sim/psrr-vs-freq-50ma/` do: ngspice's
per-`.meas` result vectors go out of scope as soon as a second `.ac` becomes
the current plot, so one deck cannot carry two DC bias points (see
`sim/psrr-vs-freq/testbench/tb_psrr.spice`'s header for the full derivation).

## What this bench measures

`Vref VREF 0 DC 1.2 AC 1` rides the small-signal probe on `VREF` instead of
`VIN` (`VIN` is a plain DC rail in this deck); `vdb(vout)` then reads the
`VREF`-to-`VOUT` transfer directly in dB, since the 1 V AC stimulus is 0 dB.
Four spot frequencies are measured per corner: 10 Hz (DC/tempco proxy), 1 kHz
and 100 kHz (the same two frequencies the ratified PSRR row is checked at),
and 1 MHz. There is no ratified numeric threshold for this transfer itself --
it is new evidence establishing one, not verifying against an existing spec
line -- so each deck's `tb.json` `checks` are limited to the harness-integrity
gates (`dc_vout_v`, `dc_iload_ma`) that confirm the `.ac` was linearized about
the physical operating point with the load sink delivering the commanded
current, the same convention `sim/psrr-vs-freq/` uses.

## Corners run, and why not the full 45-point matrix

This deck's `tb.json` requests `--corner-set mos` (`tt`/`ff`/`ss`/`fs`/`sf`)
across the full temperature/supply grid -- 45 points -- like every other
bench in this repo. The host these records were produced on is shared and
was, at the time, also running a concurrent `sim/loop-stability/` sweep from
another issue's worktree; a single point of this deck costs 50-90 s of wall
clock serially and materially more under that contention (a from-scratch
attempt at default job/timeout settings completed 0/45 points before every
point timed out -- see the superseded interrupted attempt this record set
replaces, discarded per `sim/README.md`'s append-only rule since no record
was minted from it). This is the same disclosed constraint
`DR-0021`'s "Evidence" section documents for `loop-stability`'s own partial
(72-of-4536-point) verification, and the same `--subset-reason` convention
`sim/harness/runner.py` enforces for any non-full record.

Each of the two decks (`vref-transfer`, `vref-transfer-50ma`) therefore
carries **two** records instead of one, covering two orthogonal slices of the
45-point grid rather than the whole thing:

| Record | Corners x T x V | Slice |
|---|---|---|
| light load, nominal T/V | `tt,ff,ss,fs,sf` x 27 C x 3.30 V | process-corner axis at the nominal operating point |
| light load, nominal process | `tt` x {-40,27,125} C x {2.97,3.30,3.63} V | temperature/supply plane at the nominal (`tt`) process corner |
| full load, nominal T/V | `tt,ff,ss,fs,sf` x 27 C x 3.30 V | process-corner axis at the nominal operating point |
| full load, nominal process | `tt` x {-40,27,125} C x {2.97,3.30,3.63} V | temperature/supply plane at the nominal (`tt`) process corner |

14 unique points per load condition (the `tt`/27 C/3.30 V corner is common to
both slices of each pair). The remaining 31 process x off-nominal-T/V
combinations per load condition are not run here for the same compute reason;
nothing about the deck, the manifest, or the design blocks them -- a
follow-up full-matrix re-run is a compute-only task, not a design question,
exactly as `DR-0021` disclosed for `loop-stability`.

## Measured transfer (dB vs. frequency), across the sampled PVT points

Values are the min/max observed across the 14 unique points recorded for
each load condition (see the linked records for the full per-corner table).

| Frequency | Light load (1 mA) | Full load (50 mA) |
|---|---|---|
| 10 Hz (DC) | 3.522 -- 3.525 dB | 3.522 -- 3.525 dB |
| 1 kHz | 3.525 -- 3.530 dB | 3.521 -- 3.524 dB |
| 100 kHz | -3.553 -- +0.180 dB | +1.441 -- +2.013 dB |
| 1 MHz | -29.262 -- -21.859 dB | -15.078 -- -7.826 dB |

Records:

- Light load: `sim/vref-transfer/records/20260906-035719-fff0bf0.md` (process
  axis), `sim/vref-transfer/records/20260906-035947-fff0bf0.md`
  (temperature/supply plane) -- both **PASS**.
- Full load: `sim/vref-transfer-50ma/records/20260906-040347-fff0bf0.md`
  (process axis), `sim/vref-transfer-50ma/records/20260906-040612-fff0bf0.md`
  (temperature/supply plane) -- both **PASS**.

**Sanity check against DR-0003's nominal estimate**: the DC/10 Hz transfer
measures 3.522-3.525 dB = 1.502-1.504x at every sampled corner and both load
conditions -- matching DR-0003's `1/beta = Vout/Vref = 1.5` estimate (1.8 V /
1.2 V) to better than 0.3% everywhere sampled, and varying by under 0.08%
across the whole sampled PVT/load grid. This is the expected result for a
resistive feedback divider inside a loop with enough DC gain to hold
regulation: the transfer is governed by the divider ratio, not by amplifier
or pass-device parameters, so it should be (and is) nearly PVT- and
load-invariant. At 100 kHz and 1 MHz the loop gain has rolled off (this is
the same frequency range `sim/loop-stability/`'s Bode margins are checked
over) and the transfer departs from 1.5x substantially -- full load shows
*less* attenuation at 100 kHz than light load (up to +2.01 dB vs. -3.55 to
+0.18 dB), i.e. the reference's influence on `VOUT` is measurably
load-dependent at frequencies near and above the loop's crossover, even
though the DC/tempco-relevant gain is not.

## Derived budget: what a real `VREF` driver must meet

This is the "flows straight through to `VOUT` at 1/beta = 1.5x" /
"not in any ratified row of this block's spec" gap `DR-0021`'s Decision #3
contract table names. It is closed here by converting the measured transfer
above into the accuracy-class numbers a companion reference block (a
bandgap, or the Chipalooza Challenge #5 harness's bandgap-referenced bias
slot) would need in order for a **system-level** accuracy and PSRR claim
(regulator + reference combined) to still fit the same envelope this block's
own ratified rows use -- which the ratified rows themselves, per README note
2, are not required to do on their own (`sim/mc-output-accuracy/`'s manifest
excludes the reference's error by construction, and that is unchanged by
this record).

### Accuracy / tempco budget

`sim/mc-output-accuracy/README.md`'s "Combine against the ratified window"
table is the regulator's own worst-corner-combine total against the ratified
±36 mV (±2%, 3σ) `Output` window: **24.59 mV used, 11.41 mV (32%) unused
headroom**, output-referred. Treating that unused headroom as the budget a
real reference's own error is allowed to consume -- added linearly on top of
the regulator's own worst-case combine, the same conservative (not RSS'd)
convention that record already uses for its deterministic terms -- and
converting to a `VREF`-referred figure through this bench's own measured
worst-case DC gain (3.52492 dB = 1.5030x, the highest of the 28 sampled
points across both load conditions, i.e. the most pessimistic/least
conservative gain to divide through by):

```
allowed VREF-referred error <= 11.41 mV / 1.5030 = 7.59 mV  (0.63% of 1.2 V)
```

**A real `VREF` driver's total error -- initial trim inaccuracy, tempco drift
over -40..125 C, and any DC/low-frequency noise, combined -- must not exceed
about 7.6 mV (0.63%) referred to its own 1.2 V nominal output**, for the
system-level accuracy claim to still land inside the same ±36 mV window the
regulator alone is ratified against. Two illustrative splits of that total
(neither is itself a ratified number -- the 7.59 mV **total** is the
falsifiable figure):

| Allocation | Initial accuracy | Tempco (-40..125 C, 165 C span) |
|---|---|---|
| All-tempco ceiling (zero initial error) | -- | <= 7.59 mV / 1.2 V / 165 C = **38.3 ppm/C** |
| Even 50/50 split | <= 3.8 mV (0.32%) | <= 3.8 mV / 1.2 V / 165 C = **19.2 ppm/C** |

Both numbers are inside what a real curvature-corrected gf180mcu-class
bandgap can achieve (typical published gf180mcu-generation bandgaps land in
the 10-30 ppm/C tempco range with <1% trimmed initial accuracy) -- this
budget is a real constraint on the companion block, not one that rules out
building it.

This is a DC/quasi-static budget (it uses the 10 Hz / DC-region gain, where
the measured transfer is flattest and most PVT-invariant); it does not carry
a wideband-noise term, because `Output noise` is an explicitly **waived**
row (README note 7 -- "no consumer requirement exists to substantiate a
number against"). If that waiver is ever lifted, the same measured
`Gain_ref(f)` curve tabulated above is exactly the transfer a wideband
integrated-noise budget would need; nothing further has to be re-measured.

### PSRR budget

The ratified `PSRR` row's targets are `>50 dB @ 1 kHz` (binding, light load)
and `>20 dB @ 100 kHz`, at both 1 mA and 50 mA. A real reference's own
supply rejection (`VIN` ripple appearing on `VREF`) reaches `VOUT` through
the transfer measured by this campaign, in addition to the regulator's own
direct `VIN`-to-`VOUT` path that `sim/psrr-vs-freq/` and
`sim/psrr-vs-freq-50ma/` already measure. Requiring the reference's indirect
contribution to not exceed the regulator's own direct contribution (i.e. not
become the dominant leakage path, at most a ~3 dB degradation to the
combined total if the two added in phase) gives:

```
PSRR_ref(f) [dB]  >=  PSRR_regulator_target(f) [dB]  +  Gain_ref(f) [dB]
```

using the ratified target (not the currently-measured, better-than-target
number) for `PSRR_regulator_target`, so the bound holds for any
implementation that merely meets its own ratified promise, and the
worst-case (maximum, i.e. least-attenuating) `Gain_ref(f)` sampled across
both load conditions and all 28 sampled PVT points at each frequency:

| Frequency | Ratified regulator PSRR target | Worst sampled `Gain_ref` | Required reference PSRR |
|---|---|---|---|
| 1 kHz | > 50 dB | 3.530 dB (light load) | **>= 53.6 dB** (round to >= 54 dB) |
| 100 kHz | > 20 dB | 2.013 dB (full load) | **>= 22.0 dB** (round to >= 23 dB) |

Note the 100 kHz number: the reference's own required PSRR at 100 kHz is
barely above the regulator's own ratified floor there, because the measured
`VREF`-to-`VOUT` transfer at 100 kHz is close to 0 dB (near-unity) rather
than attenuated -- the loop's own PSRR at that frequency is doing comparatively
little to help suppress a noisy reference, unlike at 1 kHz where the loop
still has gain in hand.

## What this record does not change

Per `sim/README.md`'s append-only rule and this issue's own scope: no
existing `sim/` record's ratified verdict is touched by this campaign. The
regulator-only `Output` and `PSRR` rows in `sim/CHARACTERIZATION.md` are
unchanged; this campaign adds new, previously-unmeasurable evidence and a
derived budget for a reference block that does not yet exist in this repo
(`DR-0021` Decision #2 -- this repository does not design its own bandgap).
