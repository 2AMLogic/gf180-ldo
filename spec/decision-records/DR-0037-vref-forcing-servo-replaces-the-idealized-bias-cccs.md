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
- Why the current limit matches the baseline to 6 printed digits: the old
  `Vbsense` source held the top of `Rbias` at exactly `VREF`, and the servo
  now holds it within loop error of `VREF`. A local single-point `op` at
  the same tt / 27 C / 3.30 V point shows `V(VX) - V(VREF)` = -6.8 uV, with
  the bottom node `BB` at 123.26 uV in both DUTs. So the `Rbias` current,
  1.0638 uA, matches the ideal CCCS to about 6 ppm, and `PB` and `VTH` are
  the same to 7 digits. The plateau is set by that `Rbias` current through
  `Mpd`/`Mrefp`/`Rref`, and the remaining difference shows up only in the
  7th significant digit of `summary.csv` (75.78275 vs 75.78274 mA). That
  match is what the servo's loop gain is meant to produce, and it is not a
  sign that the old DUT was simulated twice. The new DUT has the servo
  (`XMconv`) in its own `dut.spice` and the baseline has `Fbias`. This
  holds at one point only: the amplifier's systematic offset and finite
  gain across PVT still need the matrix.
- The `Iq` delta is the servo amplifier's own bias, which the idealized CCCS
  did not carry.
- Open: the full `ldo_ilimit` / `ldo_softstart` / `quiescent-current` PVT
  matrices (63 / 163 / 81 points) have **not** been run: the batch fleet
  returned `batch_job_failed` for every point (see the PR and
  2AMLogic/klayout-tools#2733). This record stays `proposed` until those
  matrices are recorded and show the DR-0005 window, the DR-0006 ramp and
  the `Iq` budget hold at every corner, including loop stability and
  exact-zero EN = 0 current at the extremes.
- Open, tracked as follow-ups that must close before this record leaves
  `proposed`:
  - #352: the `nonconvergence` diagnostic `klt sim` raised on the new DUT at
    the probed point. The DC solve needs true gmin stepping after dynamic
    gmin stepping fails (the baseline needs only dynamic stepping). It
    converges to the intended point, but a self-biased loop with a startup
    branch could have a zero-current state that one point does not rule
    out.
  - #351: the soft-start peak `Icap` drops from 282 to 142 mA (and peak
    dV/dt from 369 to 99 V/ms) while the ramp slope stays within 1.1 %. The
    cause has not been found.
- This change moves the `ldo_core` netlist sha, so every
  `sim/CHARACTERIZATION.md` row now reads STALE, Stability included. The
  Stability row still shows the `DR-0018` envelope PASS from the 2.8 mm
  record, but that record no longer describes the committed DUT. A
  `loop-stability` re-mint against this DUT is part of the open matrix work
  above.

- **Update (issue #352, no status change).** Bias-acquisition evidence for
  both servos is in `sim/soft-start/records/20261008-ss-352-bias-acq.md`.
  Within the tested stimuli and 63 PVT corners no persistent inactive state
  was found with the startup branch present, and one persists without it.
  Uniqueness, mismatch and other stimuli remain unverified there. This
  record does not ratify DR-0037.

## Update (2026-11-20, issue #783, proposed)

The settled regulator loop and current limit meet their bounds on the servo
DUT. Two findings prevent an affirmative ratification recommendation. Both
bias branches carry measurable current with EN low, and the paired Iq
sweep has one invalid corner.

The settled-loop and soft-start snapshots, and the raw current-limit, Iq
and enable/shutdown decks' `dut.spice` files, match the committed
`design/netlist/ldo_core.spice` byte for byte (SHA-256
`4f99a1a9dcf681be3b470b7f11c8cff1a7a3bc63b276f0aa909fe88dfef5e4e1`).
The paired ideal-source baseline has SHA-256
`5bfa966c7d33005f28ecfe1725af798fbb130154633c334ff6d4d6b419c1889e`.

| #320 criterion | Measured result | Committed evidence |
| --- | --- | --- |
| Current limit, DR-0005 | **Pass, 63/63.** At VOUT = 1.764 V, onset spans 62.025–93.776 mA inside the 62–95 mA window. The lower margin is 0.025 mA at ss / −40 °C / 2.97 V. Worst short dissipation is 345.598 mW against 346 mW. The largest absolute change in onset versus the ideal source is 0.0033 mA. | [20261115-limits-616-658920d0, corner values](../../sim/current-limit/corners/20261115-limits-616-658920d0/summary.csv), [20261015-ilim-320-pvt, paired comparison](../../sim/current-limit/records/20261015-ilim-320-pvt.md) |
| Soft-start ramp and extra capacitors | **Matrix complete.** All 63 main points and all five 20-point extra requests produced measurements. The main 0.4–1.4 V ramp spans 1.281–3.364 V/ms (ideal-source baseline 1.30–3.41 V/ms). Extras span 1.113–3.364 V/ms. At 5 ns resolution the two DUTs' peak capacitor currents agree within 0.20% at the 161 hold-release events. This resolves the apparent peak improvement in #351. The ratified Startup row remains **MIXED**. The servo requalification did not regrade the standing ramp, inrush and current-limit clearance failures. | [20261118-pdk-f6eeac7-ss](../../sim/soft-start/records/20261118-pdk-f6eeac7-ss.md), [20261016-ss-320-pvt-main, baseline comparison](../../sim/soft-start/records/20261016-ss-320-pvt-main.md), [20261105-ss-351-peak-pvt, resolved peaks](../../sim/soft-start/records/20261105-ss-351-peak-pvt.md) |
| Enabled Iq and servo cost | **80/81 physical paired solves.** The servo adds 0.42–0.92 µA at no load and at 50 mA (+0.60 µA typical). At ff / 125 °C / 3.63 V, Iq reaches 28.303 µA unloaded and 29.631 µA loaded, leaving 0.369 µA below 30 µA at full load. Both DUTs false-converged at ss / −40 °C / 2.97 V. The pinned servo run gave −0.0549 V and delivered 0.00187 mA at the commanded 50 mA. The separate enable bench measured 9.237 µA at 49.986 mA there. The paired no-load/full-load Iq delta at that corner remains open. | [20261015-iq-320-pvt, paired](../../sim/quiescent-current/records/20261015-iq-320-pvt.md), [20261020-pdk-f6eeac7-iq](../../sim/quiescent-current/records/20261020-pdk-f6eeac7-iq.md), [enable-bench corner values](../../sim/enable-shutdown/corners/20261020-pdk-f6eeac7-en/summary.csv) |
| EN = 0 at the extremes | **Exact zero unmet.** The enable bench passes its 63-corner shutdown budget (maximum total Iq 0.277414 µA against 3 µA). The #352 EN-cycle bench inserts 0 V ammeters in both servo conveyors. At ff / 125 °C / 3.63 V, 19.5 µs into the initially disabled state, it measures 0.851118 nA in `ldo_ilimit` and 0.857408 nA in `ldo_softstart`. Its 1%-of-enabled-bias check passes with those finite currents. | [20261020-pdk-f6eeac7-en](../../sim/enable-shutdown/records/20261020-pdk-f6eeac7-en.md), [20261008-ss-352-bias-acq, instrumentation](../../sim/soft-start/records/20261008-ss-352-bias-acq.md), [EN-cycle readings, `en_from_shutdown`](../../sim/soft-start/corners/20261008-ss-352-bias-acq-encycle-part1/acquisition.csv) |
| Settled main-loop stability, DR-0001 / DR-0018 | **Pass, 630/630.** Five loads from 0.1 to 50 mA × 1 µF × ESR {0.2, 0.5} Ω × 63 PVT corners. Minimum PM is 48.68° (3.30 V, 0.2 Ω) and minimum GM is 11.20 dB (2.97 V, 0.5 Ω), both at res_ss / −40 °C / 50 mA, against 45° and 10 dB. No DR-0008 resurgence flags. The frozen snapshot contains both servos despite the record prose naming `Fbias`. | [20261119-155956-0076e52, matrix](../../sim/loop-stability/records/20261119-155956-0076e52-matrix.csv), [frozen DUT](../../sim/loop-stability/netlist-snapshots/20261119-155956-0076e52.spice) |

The settled-loop injection is between `ERRAMP_OUT` and `PASS_GATE`.
Main-loop margins during soft-start hand-over have only pre-servo evidence.
The internal VREF-forcing loop margin is unmeasured. Neither hand-over nor
internal-loop margins have a #320 acceptance threshold. [Hand-over record 20260910-015601-2387ece](../../sim/soft-start-loop-gain/records/20260910-015601-2387ece.md)
