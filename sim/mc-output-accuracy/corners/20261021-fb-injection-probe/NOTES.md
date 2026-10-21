# FB-node current probe (issue #484) -- diagnostic, not a graded record

Single-point `op` of one `ldo_core` copy per DUT variant, local `klt sim`
(one unit per run, models staged from the pinned open_pdks `f6eeac7`), driver
`sim/mc-output-accuracy/testbench/probe_fb_current.py --baseline-ref 2a7caecb`.
No Monte Carlo, no grid; no `tb.json` bound is evaluated or changed. Data:
`probe.csv`.

KCL at FB gives `VOUT - 1.5*FB = -300k * (I(Rbot) - I(Rtop))`, so the
`divider_exact_uv` residual is 300 kohm times the current that enters FB from
anywhere other than the divider.

| DUT | corner | I(Rtop) nA | I(Rbot) nA | into FB, off-divider | VOUT - 1.5 FB |
|---|---|---|---|---|---|
| `2a7caecb` (old) | ff_125c_3.63v | 1998.72500 | 1998.72500 | 0.09 pA | -0.0026 uV |
| `2a7caecb` (old) | tt_27c_3.30v | 1999.27474 | 1999.27475 | 0.09 pA | -0.0026 uV |
| current (DR-0037) | ff_125c_3.63v | 1981.04616 | 1998.72535 | **17.68 nA** | **-5303.8 uV** |
| current (DR-0037) | tt_27c_3.30v | 1999.26745 | 1999.27483 | **7.4 pA** | **-2.215 uV** |
| current, `Xsoftstart` deleted | ff_125c_3.63v | 1998.72534 | 1998.72535 | 0.09 pA | -0.0026 uV |
| current, `Xsoftstart` deleted | tt_27c_3.30v | 1999.27482 | 1999.27483 | 0.09 pA | -0.0026 uV |

Reading:

- The current that leaves FB other than through the divider is sourced by the
  soft-start block (`Xsoftstart`, FB pin): deleting that one instance restores
  the old DUT's residual to the printed digit, and VOUT at ff/125 C/3.63 V
  returns to 1.798853 V (old DUT 1.798853 V; current 1.793549 V).
- It is the same settled injection residual `DR-0039` measured on the
  line-regulation bench (17.7 nA at ff/125 C/3.63 V there too), not a servo
  (`Mconv`) path in `ldo_ilimit`, which is not connected to FB. The 5.3 mV
  output shift here is that 17.7 nA through `Rtop`, i.e. the -6.7 mV `mean_mv`
  and the extra sigma at `ff_125c_3.63v` of the 45-point record.
- At `tt_27c_3.30v` the same element injects 7.4 pA: 2.2 uV on the identity,
  already above the 1 uV `divider_exact_uv` bound, matching the 2.2-2.6 uV
  floor of the 45-point record. The bound therefore cannot close by making the
  element's *worst* corner better alone: it needs the settled residual below
  ~3.3 pA at every point.
