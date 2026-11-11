# DR-0043: the ngspice pin is a major-version floor (at least ngspice-46), not an exact version

- **Status**: proposed
- **Date**: 2026-11-11
- **Decided by**: agent-builder, issue #568 (implements the operator ruling of 2026-10-29)

## Context

`docs/environment-setup.md` #1 pinned ngspice to exactly `ngspice-46`, and
`sim/harness/runner.py` enforced it as a string equality
(`PINNED_NGSPICE_VERSION`). When homebrew-core's `ngspice` moved to ngspice-47
the identity check refused the host (#247). [`DR-0027`](DR-0027-wnflag-facts-reproduce-across-ngspice-majors.md)
measured that DR-0025's `wnflag` model-bin facts F1-F3 reproduce on ngspice-42
and ngspice-47, but deliberately did not move the pin.

The operator ruled on 2026-10-29 that the fleet states a *floor*, not an exact
version.

## Decision

- The minimum is one constant, `NGSPICE_MIN_MAJOR = 46`, in `sim/harness/runner.py`.
  Any known `ngspice-<major>` with major >= 46 passes the version leg of the
  identity check; majors are compared as integers. There is no ceiling.
- A known major below the floor is refused with a message naming the floor.
  An unparseable or missing version stays "unknown", never "drifted".
- The containment leg is unchanged: the resolved binary must live under the
  expected toolchain root, at any version. It guards byte-different
  same-version builds (#182/#184), which a floor does not affect.
- The measured version is still recorded in every run report.
- Existing ngspice-46 records and corner logs are unchanged (append-only
  evidence); they are not re-baselined.

## Consequences

- Supersedes the exact-pin stance in `docs/environment-setup.md` #1 and the
  "pin does not move" conclusion of DR-0027 (whose facts remain valid).
- ngspice-47 hosts pass; new records minted on a newer major carry that major
  in their recorded environment.
- The `ngspice@46` versioned-formula advice remains a valid option for hosts
  wanting reproducibility with the historical records.
- Out of scope: an upper bound, the xschem pin, the PDK pin.
