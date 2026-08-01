# `mc-output-accuracy` — Monte Carlo mismatch vs. the ±2 % output-accuracy window

Issue #13. This is the combine document `tb.json`'s `claim` field and
`design/error_amp.md` §3 both point at: it takes the **statistical** result
this experiment measures (the error-amp input-pair + mirror mismatch, via the
PDK's real `sw_stat_mismatch` model) and combines it with the **deterministic**
and **non-simulable** terms from `design/error_amp.md` §3 to verify the
ratified README row — 1.8 V ±2 % (±36 mV, 3σ), regulator-only per README
note 2 — the way `design/error_amp.md` §3 says to combine them.

Every number below is regenerated from the committed raw evidence by
`sim/mc-output-accuracy/summarize.py <record-id>`; nothing here is a
hand-typed rollup. Re-run it yourself:

```
python3 sim/mc-output-accuracy/summarize.py 20260801-030232-969e423
```

## What is, and is not, Monte-Carlo'd here

- **Simulated (this deck):** every FET in the closed loop —
  the error amp's input pair, mirror load, tail and bias devices, second
  stage, and the pass device — carries the PDK's real per-instance
  `sw_stat_mismatch` local-mismatch model, redrawn every `mc_source`. Global
  (die-to-die) spread is deliberately off (`sw_stat_global = 0`); it is
  common-mode across a matched pair and does not move an offset or a divider
  ratio (`sim/devchar/CONCLUSIONS.md` §2).
- **NOT simulated, and cannot be against this PDK:** the feedback divider.
  `design/netlist/ldo_core.spice`'s `Rtop`/`Rbot` are ideal SPICE resistors
  (no statistical model at all), and even the PDK's own resistor subcircuits
  hard-code `mis_r = 0` — a matched pair returns bit-identical values over 200
  Monte Carlo runs (`sim/devchar/CONCLUSIONS.md` §2). A "Monte Carlo pass" on
  the divider through these models is not evidence and must not be cited as
  one (README note 3). `design/error_amp.md` §3.2's fixed **3.36 mV (3σ)**
  divider term is a hand-computed assumption from the PDK's disabled
  `ppolyf_u` `par_r = 0.021` card value, added in below, never simulated.
  The testbench's own `divider_exact_uv` measurement (see Result table in the
  record) proves the divider contributed nothing to this run's own sigma:
  it checks `|dVOUT − 1.5·dFB|` sample-by-sample and every corner comes back
  under 4 µV, ~250,000× smaller than the 1 µV integrity ceiling the check
  imposes — confirming the divider ratio held exactly and this run's spread
  is the amplifier's alone.
- **Excluded, not zero:** the voltage reference's own tolerance. README
  note 2 makes the ±2 % window regulator-only; the bandgap companion block's
  error is a separate budget line this repo does not carry.

## Corners run and why `mos`, not `full`

`tb.json` requests `--corner-set mos` (`tt`/`ff`/`ss`/`fs`/`sf`) × the full
−40/27/125 °C × 2.97/3.30/3.63 V grid — **45 points**, 1000 samples each.
`sim/harness/corners.py`'s own docstring says the four corners `full` adds on
top of `mos` (`res_ff`/`res_ss`/`bjt_ff`/`bjt_ss`) are "for claims where that
matters (e.g. divider-accuracy or reference claims)" — and this deck is
neither: `design/netlist/ldo_core.spice` instantiates **zero BJTs** (a
`bjt_ff`/`bjt_ss` corner is a no-op on this circuit by construction), and the
divider is drawn as ideal resistors immune to any resistor-model corner in
simulation (the same "ideal R" fact §3.2 already relies on). The two PDK poly
resistors that do exist here (`XRbias`, `XRz`) set the deterministic bias
point and compensation zero, not the FET mismatch statistic this deck exists
to measure — a legitimate but separate bias-sensitivity question for a future
targeted testbench. See the testbench header for the full argument. 45
full-factorial points at the full temperature and supply axes still satisfies
`sim/harness`'s own PVT-matrix-conformance check (≥ 3 process corners, full
temp/supply axes), so this record needed no `--subset-reason`.

## Sample count

1000 samples per PVT point (`mcm = 25` independent `ldo_core` copies ×
`mcit = 40` `mc_source` redraws — see the testbench header for why that
split, not e.g. 1000 redraws of 1 copy). At N = 1000 the standard error of
the sample sigma is ≈ 1/√(2·999) ≈ 2.2 % of sigma itself, i.e. the 3σ figures
below are resolved well inside the margin against the 3.49 mV / 2.33 mV
targets (§3.1) they are checked against. The normality cross-check below
(observed vs. Gaussian population within 1σ/2σ/3σ, over all 45,000 pooled
samples) confirms the Pelgrom `agauss()` draws are behaving as the expected
Gaussian, so the usual 3σ ≈ 3× the sample sigma reading is a legitimate
per-corner extrapolation and not being stretched past what 1000 samples can
support.

## Evidence

- **Record**: `sim/mc-output-accuracy/records/20260801-030232-969e423.md` —
  **PASS**, 45/45 points, every check (`n_samples`, `n_bad_solves`,
  `sigma_mv` integrity floor, `sigma3_mv`, `vos_in_sigma3_mv`, `worst_abs_mv`,
  `divider_exact_uv`, `mean_mv`) passing at every corner.
- **Raw per-corner logs** (including the per-sample `MCSAMPLE` echoes this
  rollup reads): `sim/mc-output-accuracy/corners/20260801-030232-969e423/`
- **Frozen netlist**: `sim/mc-output-accuracy/netlist-snapshots/20260801-030232-969e423.spice`

## Rollup (regenerated from the record above)

### Per-corner distribution, worst points

Full 45-corner table is in `summarize.py`'s output (regenerate with the
command above); the extremes:

- **Worst sigma**: `ss_27c_2.97v` — σ = 0.763 mV, 3σ = **2.288 mV** output /
  **1.526 mV** input-referred. This is the number checked against §3.1's
  calculated target below.
- **Worst |mean|**: `sf_125c_3.63v` — mean = **−0.906 mV**, inside the
  deterministic ±2.56 mV budget line at every one of the 45 points.
- **Worst single sample**: `tt_-40c_3.63v` — |ΔVout| = 3.720 mV, far inside
  the 18 mV one-sided static-budget check.

### Normality cross-check (45,000 pooled samples, each corner centred on its own mean)

| within | observed | Gaussian |
|---|---|---|
| 1σ | 68.09 % | 68.27 % |
| 2σ | 95.48 % | 95.45 % |
| 3σ | 99.74 % | 99.73 % |

Largest \|z\| observed: 4.55σ over 45,000 samples (expected order of
magnitude for a clean Gaussian at this N) — no fat tail, no truncation
artifact from the `worst_abs_mv`/`n_bad_solves` integrity checks.

### Combine against the ratified window (`design/error_amp.md` §3 method)

Statistical terms RSS at a common 3σ; deterministic terms add linearly;
everything output-referred through 1/β = 1.5, per §3's combine convention.

| Term | Output-referred | Kind | Source |
|---|---|---|---|
| Amp input-pair + mirror mismatch | **2.29 mV** (3σ) | statistical | **this run**, worst corner `ss_27c_2.97v` |
| Feedback-divider mismatch | 3.36 mV (3σ) | statistical, **assumption** | `design/error_amp.md` §3.2 — not simulable (`mis_r = 0`) |
| Systematic offset + line regulation | 2.56 mV | deterministic | ratified budget (0.91 + 1.65 mV) |
| (same, as measured by this run's worst per-corner mean) | 0.91 mV | deterministic | **this run**, `sf_125c_3.63v` |
| **Statistical RSS** | **4.07 mV** | | |
| **Total static (ratified deterministic)** | **6.63 mV** | | vs 18 mV available |
| **Total static (measured deterministic)** | **4.97 mV** | | |
| Load regulation (allowance, #12 verifies) | 18.0 mV | | |
| **Total against the ±36 mV window** | **24.63 mV** | | **32 % margin** |

The measured amp-mismatch term (2.29 mV) beats §3.1's calculated 3.49 mV
target, so this run's total-static-vs-window margin (32 %) is slightly better
than §3's calculated 29 %.

### Yield

- Combined statistical 1σ (amp RSS divider): 1.355 mV
- Headroom after the deterministic terms and the load-regulation allowance:
  36 − 18 − 2.56 = 15.44 mV
- That headroom is **11.4σ** of the combined statistical distribution →
  parametric yield ≈ 100.000000 % (≈ 0 ppm outside), i.e. device mismatch and
  the divider assumption are nowhere near the limiting term for this window;
  the 18 mV load-regulation allowance dominates the budget.

## Verdict against `design/error_amp.md` §3.1

| | Output-referred (3σ) | Input-referred (3σ) |
|---|---|---|
| Measured (this run, worst corner) | **2.29 mV** | **1.53 mV** |
| §3.1 calculated target | 3.49 mV | 2.33 mV |
| Measured / calculated | 0.656 | 0.656 |

**PASS.** The amplifier's measured mismatch is comfortably inside its
calculated Pelgrom-based target at every one of the 45 PVT points run.

## Acceptance (issue #13)

**Meets the ±2 % output-accuracy window at 3σ across the selected corners.**
Total against the ±36 mV window: 24.63 mV → **32 % margin**. No `spec/`
budget revision is needed.
