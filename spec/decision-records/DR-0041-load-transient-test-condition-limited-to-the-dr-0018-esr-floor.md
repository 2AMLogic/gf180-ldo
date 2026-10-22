# DR-0041: limit the Load-transient row's test condition to the DR-0018 Stability envelope (ESR >= 200 mOhm); a bare ceramic output capacitor is not supported yet

- **Status**: proposed -- **ratification pull request**. This record narrows a
  ratified claim after a measured failure, so it is not to be merged on Judge
  approval alone: it needs the EE-key and market-key reviews
  (`ratification/ee-key`, `ratification/market-key`) and then the operator's
  ratification, per the ratification-via-PR policy (2AMLogic/2am#357). Until
  then `README.md`'s Load-transient row on `main` keeps its ratified text.
  The market-key advisory review on issue #483 (`escalate`) is cited here as
  input, not as a `RATIFY-KEY` review.
- **Date**: 2026-10-22
- **Decided by**: builder agent, issue #483, directing the operator's ruling of
  2026-10-22 (fleet:decide 20261021-r1, D17: option (a) now, option (b) as a
  tracked follow-up). Recommendation only; ratification is the operator's.
- **Builds on**: DR-0004 (amendment A4, the Load-transient row), DR-0018 (the
  narrowed Stability envelope), DR-0034 (the pass width whose stability
  evidence is the DR-0018 envelope), DR-0037 (the servo, shown not to be the
  cause). Supersedes none of them.

## Context

Re-qualifying the transient benches at open_pdks `f6eeac7`,
`sim/load-transient/records/20261021-pdk-f6eeac7-tran.md` (81 points, DR-0037
DUT) has **73/81** points meeting every bound. All 8 failures are the
peak-excursion clause (<= 150 mV) at the bench's 0.33 uF / 100 mOhm output
network: `ss_-40c_{2.97,3.30,3.63}v`, `res_ss_-40c_{2.97,3.30,3.63}v`,
`res_ss_27c_2.97v` (172.5-269.2 mV undershoot) and `sf_-40c_3.30v` (476.1 mV
overshoot). The previous DUT passed 81/81.

PR #490 (`sim/load-transient/records/20261021-483-mechanism.md`) located the
cause by measurement. The step is DR-0034's pass-device width (2000 -> 2800
um): `ss_-40c_2.97v` reads 53.7 mV at `d43df74f`, 233.2 mV at DR-0034's commit,
and the DR-0037 servo moves it by +0.1 mV. At 50 mA the loop has phase margin
-7.73 / -6.28 / -0.05 deg (`ss_-40c_2.97v`, `ss_-40c_3.30v`, `sf_-40c_3.30v`;
0.33 uF / 100 mOhm), so the "excursion" is the first trough of a sustained
oscillation. Everything passes up to 2400 um; the cliff sits between 2400 and
2500 um.

The README row promises the 0.33 uF point at ESR 0-500 mOhm, while DR-0018's
Stability envelope, where DR-0034's evidence lives, is 1 uF at ESR >= 200 mOhm.
The two ratified rows disagree, and this DUT cannot satisfy both.

Re-read from the #490 record's section 5 (this record's numbers, not the
issue's): with ESR >= 200 mOhm every probed point passes. At 0.33 uF / 200 mOhm
the worst point is 70.3 mV undershoot / 73.3 mV overshoot (`ss_125c_2.97v`),
i.e. >= 2.1x margin on 150 mV; at 1 uF / 200 mOhm the worst is 50.0 / 36.6 mV,
>= 3x. (The issue's 73.1 / 76.6 mV figures are the 100 mOhm batch-record cell
of the same corner; the 200 mOhm cell is the one that applies here.) The
failures are confined to ESR < 200 mOhm.

## Decision

1. The Load-transient row's **test condition** is limited to the DR-0018
   envelope: C_eff = 0.33 uF and **ESR >= 200 mOhm** (previously ESR 0-500
   mOhm). The bench keeps sweeping what it sweeps; the claim narrows, not the
   testbench.
2. **Unchanged**: the 150 mV peak-excursion bound, the recovery clause (+-1%
   in <= 20 us), the 1 <-> 50 mA step and the 1 us edges. The 100 mV stretch
   target is untouched.
3. `README.md` carries the narrowed condition and the disclosure below in the
   row's Target cell, with a pointer to this record.

### Disclosure: a bare ceramic output capacitor is not supported yet

This design does **not** meet the load-transient row with a bare (low-ESR)
ceramic output capacitor. At 0.33 uF with ESR below 200 mOhm the 50 mA loop has
no phase margin at the slow/cold corners and oscillates (8 of 81 points fail
the 150 mV bound, up to 476 mV). An MLCC with roughly 0.2-0.47 ohm of series
resistance (a deliberate series resistor, or a higher-ESR-class part) is the
interim way to meet the condition. Restoring the full ESR 0-500 mOhm row is the
follow-up #501.

## Alternatives considered

- **Keep the row as ratified and recompensate** (option (b)). Not chosen now:
  DR-0016/DR-0017 found compensation-network tuning largely exhausted, so a
  fix may need a topology change and a fresh 81-point plus loop-stability
  matrix, leaving the row red meanwhile. Filed as #501 so the full row can be
  restored later.
- **Cap the pass device at <= 2.4 mm** (option (c), reopen DR-0034). Declined
  by the operator: it measures as passing, but it gives up DR-0034's < 200 mV
  dropout stretch (193 mV at 2.8 mm) to buy a condition the Stability row
  already excludes. DR-0034 stands.
- **Relax the 150 mV bound.** Rejected: nothing here is a bound problem; the
  failures are a loop oscillation, not a margin shortfall.

## Consequences

- The ratified Load-transient and Stability rows agree again. Claimed support:
  0.33 uF and 1 uF at ESR >= 200 mOhm, with >= 2.1x margin on the bound.
- **Bad consequence**: the README's promise at 0.33 uF with ESR below 200 mOhm
  is given up. Any consumer using a bare ceramic output capacitor is outside
  the supported envelope until #501 lands.
- The 81-point `sim/load-transient/` grid and its failing record stay as
  evidence (`sim/` is append-only); the 8 failing points sit in the unclaimed
  region. Nothing in `design/` or `tb.json` changes.
- #501 (recompensation for ceramic caps) is the path to reverting this
  narrowing, by a superseding record.
