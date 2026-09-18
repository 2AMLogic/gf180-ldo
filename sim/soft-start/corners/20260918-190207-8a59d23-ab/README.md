# Same-binary A/B: cascoded vs. uncascoded injection mirror

Raw evidence for `sim/soft-start/records/20260918-190207-8a59d23.md`'s
"Same-binary A/B" section (issue #246).

Ten runs of `sim/soft-start/testbench/tb_soft_start.spice.in` at five
`C_eff = 1 µF / 100 mΩ / 36 Ω` PVT points, two DUT netlists each, **on one
host, in one session, with one ngspice binary**
(`4f076ec866c69842d3a9e93376ac17b3ae0e1709b4ddb05890e0e6488a900b10`,
ngspice-46, gf180mcuD @ `c6d73a35f524070e85faff4a6a9eef49553ebc2b`).

| suffix | DUT netlist | sha256 |
|---|---|---|
| `.cascoded.log` | `design/netlist/ldo_core.spice` as committed by issue #246 (DR-0023's cascoded mirror) | `53827e92c2cc5e54633284446c74d0390ff6f8b7c06a10ab27be2985df6c90fc` |
| `.uncascoded.log` | `sim/soft-start/netlist-snapshots/20260915-103035-18f664f.spice`, the frozen DUT of the superseded record (same DR-0024 cap sizing, uncascoded mirror) | `3d481db80c01e6ef69a7e57e983caff10ae7bda12e9e20a73411fa648dbcf253` |

The two netlists differ **only** in `.subckt ldo_softstart`'s injection
mirror: the cascoded one adds `XMgmrc_ss`/`XMgmc_ss` and re-terminates
`XMgmr_ss`'s diode onto `GMRM` and `XMgmo_ss`'s drain onto `GMOD`.

Produced with the `LDO_NETLIST` override issue #246 added to
`sim/soft-start/testbench/run.sh` (refused unless `NO_RECORD=1`, so no
evidence record can be minted from an overridden netlist):

```bash
NO_RECORD=1 LDO_NETLIST=<netlist> JOBS=1 \
  CORNERS=tt TEMPS=27 SUPPLIES=3.30 CAPS=1u/0.1/36 \
  EXTRA_CORNERS= EXTRA_TEMPS= EXTRA_SUPPLIES= EXTRA_CAPS= \
  ./sim/soft-start/testbench/run.sh
```

Each `.cascoded.log` was cross-checked against the corresponding row of the
committed 163-point sweep (`../20260918-190207-8a59d23/summary.csv`) and
reproduces it exactly, which is what makes these ten logs a comparison of the
two netlists and not of two sessions.

`ff_125c_3.63v_1u_0.1_36.uncascoded.log` has **no `m_t_startup` value**:
`v(vout)` never crosses 1.764 V inside the 9 ms window. That is the
settled-leakage failure `20260915-103035-18f664f.md` documents at the same
corner (it is one of that record's 8 non-converged points), reproduced here
against the cascoded run of the same corner in the same session, which
settles at 1.79357 V in 0.773 ms.
