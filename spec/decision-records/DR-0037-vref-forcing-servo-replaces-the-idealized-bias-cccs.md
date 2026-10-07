# DR-0037: a VREF-forcing V-to-I servo replaces the idealized `Fbias` / `Fss_ramp` CCCS in `ldo_ilimit` and `ldo_softstart`

- **Status**: proposed
- **Date**: 2026-10-07
- **Decided by**: Builder (issue #320)

## Context

`ldo_ilimit` (`Fbias`, `Vbsense`) and `ldo_softstart` (`Fss_ramp`,
`Vbsense_ss`) each carried the same idealization: a current-controlled
current source copying the `VREF/R` current of a resistor branch. Neither a
CCCS nor a 0 V sense source has a physical structure, so neither cell could
be laid out or LVS-matched (blockers of #290 and #291). A diode-connected
device in series with the resistor would subtract its own `Vgs`
(0.44-0.82 V against a 0.6 V reference), making `DR-0005`'s current-limit
window and the soft-start ramp rate Vt-dominated rather than
`VREF/R`-dominated, so the replacement has to force `VREF` itself across the
resistor.

## Decision

Both blocks use the same real-device circuit (port lists unchanged):

- a two-stage PMOS-input servo amplifier (`Mtl`, `Mp1`/`Mp2`, `Ml1`/`Ml2`
  mirror load, `Ms2` second stage with `Cvi` Miller cap and `Ml3` load)
  drives an NMOS conveyor `Mconv` so that the top of `Rbias` /
  `Rss_bias` sits at `VREF`;
- `Mconv`'s drain current, exactly `VREF/R`, is sunk from the block's PMOS
  diode (`Mpd`, unchanged in `ldo_ilimit`; new `Mpd_ss` in `ldo_softstart`),
  and the amplifier's tail and load are mirrored from that same diode, so
  the loop is self-biased;
- a startup branch (`Msx`/`Msd`/`Mst`) is zero-static-current once the loop
  is up and is gated through the existing `Mben`/`Mben_ss` enable device, so
  EN = 0 leaves no conduction path;
- in `ldo_softstart` the old `0.0060` CCCS gain becomes a 3:512 PMOS mirror
  (`Mramp_ss` into `SSR`).

`DR-0005` (62-95 mA window) and `DR-0006` are not relaxed. Netlists under
`design/netlist/` were regenerated from the schematics.

## Alternatives considered

- **Diode-connected NMOS self-bias (the `error_amp` pattern)** - rejected:
  subtracts a process/temperature-dependent `Vgs` from `VREF`, so the bias
  current is no longer `VREF/R`.
- **Expose the bias current as a top-level port (DR-0021 style)** -
  rejected: `VREF` is already a port; a V-to-I stage that consumes it is an
  ordinary analog block, not a new reference, and a new port would change
  `ldo_core`'s ratified pinout.
- **Leave the CCCS in place** - rejected: permanently blocks layout/LVS of
  both cells.

## Consequences

- Measured at tt / 27 C / 3.30 V only (see below): current-limit plateau
  74.953 mA vs 74.953 mA baseline; short-circuit 250.08 mW both; soft-start
  ramp 2.036 vs 2.057 V/ms; `Iq` (enabled, no load) +0.60 uA (15.96 vs
  15.36 uA); disabled `Iq` stays at the nA level (0.46 nA vs 0.29 nA). The
  `VREF` port current in the current-limit bench drops from 2.89 uA to
  ~0.6 pA, because the resistor branch is now fed from the supply instead of
  from `VREF`.
- The `Iq` delta is the servo amplifier's own bias, which the idealized CCCS
  did not carry.
- Open: the full `ldo_ilimit` / `ldo_softstart` / `quiescent-current` PVT
  matrices (63 / 163 / 81 points) have **not** been run: the batch fleet
  returned `batch_job_failed` for every point (see the PR and
  2AMLogic/klayout-tools#2733). This record stays `proposed` until those
  matrices are recorded and show the DR-0005 window, the DR-0006 ramp and
  the `Iq` budget hold at every corner, including loop stability and
  exact-zero EN = 0 current at the extremes. The `nonconvergence` diagnostic
  `klt sim` raised on the new DUT at the one probed point also needs a look.
