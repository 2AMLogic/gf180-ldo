"""gf180-ldo simulation harness.

Reproducible ngspice + gf180mcu PVT corner running. See sim/README.md for
the evidence record format this package writes, and sim/harness/README.md
for how to run it / write a testbench.

Ported from the pattern ratified in 2AMLogic/gf180-bandgap (issue #2, PR
#23); adapted here to this repo's LDO-specific "Operating conditions"
evidence field (load current / output cap / enable state) that a
bandgap -- which has no load pin -- does not need.
"""

HARNESS_VERSION = "0.1.0"

__all__ = ["HARNESS_VERSION"]
