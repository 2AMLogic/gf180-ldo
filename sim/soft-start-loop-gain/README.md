# sim/soft-start-loop-gain — the main loop's margins *during* the soft-start hand-over

Small-signal loop gain, phase margin, gain margin and the DR-0008 gain-resurgence
metric of the LDO's main loop **with `design/ldo_softstart.sch`'s FB-injection
element in the loop**, measured at pinned points of the soft-start ramp, for two
versions of that element:

| variant | what it is |
|---|---|
| `device` | the post-#195 device-level transconductor (`Rgma_ss/Mgma_ss/Mgmd_ss/Rgmb_ss/Mgmb_ss/Mgmm_ss/Mgmr_ss/Mgmo_ss/Mgme_ss`), i.e. `design/netlist/ldo_softstart.spice` as committed |
| `binj` | the pre-#195 ideal behavioural source `Binj_ss`, frozen from commit `bfc4a0a` |

```bash
python3 sim/run_corners.py --check-env          # is ngspice + the gf180mcu PDK present?
./sim/soft-start-loop-gain/testbench/run.sh     # the whole thing; mints a record
```

That second line is the whole cold start. It self-tests the measurement method
first and refuses to sweep if that fails.

## Why this experiment exists

PR #195 (merged 2026-09-06) replaced `ldo_softstart`'s ideal `Binj_ss` FB
injection source with real devices and landed a **"KNOWN, UNRESOLVED
REGRESSION (#191)"** block in `design/ldo_softstart.sch` to say so: inrush
fails 81/163 points in `sim/soft-start/records/20260906-230703-d3cb117.md`
where the ideal source passed. #191's Builder closed with an explicit ask —

> *"This looks like it needs proper loop-stability characterisation … apparently
> `Binj_ss`'s zero-parasitic model was implicitly providing compensation margin
> that #189 never characterised when it removed `Cm_ss`/`Rz_ss`."*

— and nobody filed it. Meanwhile `design/ldo_softstart.sch`'s own regression
note says *"The AC consequence … is real and is NOT characterised here … The AC
evidence is `sim/loop-stability/`'s"*, and `sim/loop-stability/` measures the
**settled** operating point, where the ramp is over and the injection is off.
So the AC evidence the schematic points at did not exist for the state the
regression is about. This experiment is that evidence (issue #196).

## What it measures, and what it deliberately does not

It measures a **frequency-domain margin at a fixed operating point**. The
soft-start ramp is a transient, so the only way to ask "what is the loop's
phase margin *during* the hand-over" is to hold the ramp still: the ramp node
`SSR` is brought out as a port and pinned by an ideal source at a small,
documented set of states.

It is **not**:

- **a DR-0001 verdict.** DR-0001's matrix is the settled operating point across
  load, `C_eff` and ESR. A pinned mid-ramp state is not in it. The 45 deg /
  10 dB bars appear in the record as *reference lines* and the CSV column is
  named `margin_vs_dr0001` for that reason. `sim/loop-stability/` remains the
  phase-margin record for this design and nothing here moves it.
- **a large-signal statement.** #191's 166.7 mA inrush is a transient
  measurement; nothing here re-runs it and a small-signal margin cannot confirm
  or refute it. What this experiment can do is say whether a *margin*
  explanation for it is available.
- **a measurement of the trajectory between the states it pins.** Pinning `SSR`
  removes the ramp's own dynamics (`Css` charging at a few nA) by construction.
  The `anchor` phase below is what bounds the cost of that idealization.

## The operating points, and why each one

With the injection element working as designed the loop holds `FB` at `VREF`
and the 300k/600k divider does the rest, so the regulated output follows
`VOUT = 1.5 * V(SSR)` until the injection rectifies off at `V(SSR) = VREF`.
That relation is what makes `V(SSR)` a meaningful coordinate for "how far
through the hand-over are we".

| phase | `V(SSR)` | load model | why |
|---|---|---|---|
| `ramp` | 0 V | 36 ohm resistor | **(a)** ramp start, injection at full tilt. Issue #196's point (a). |
| `ramp` | 0.6 V | 36 ohm resistor | mid-ramp, where the loop is genuinely live and the injection is genuinely on. |
| `ramp` | 1.15 V | 36 ohm resistor | **(b)** `VREF - 50 mV`, just before the ideal element's hand-over. |
| `ramp` | 1.25 V | 36 ohm resistor | **(c)** `VREF + 50 mV`, just after the ideal element's hand-over. |
| `sink` | 1.15 / 1.25 / 1.8 V | ideal 50 mA sink | the hand-over points again under `sim/loop-stability/`'s own load model, so the margins are comparable with its records. 1.8 V is where the *device-level* chain's injection has actually decayed away. |
| `anchor` | not pinned | ideal 50 mA sink | the settled state, `SSR` wherever `Mtop_ss`'s ceiling clamp puts it — i.e. `sim/loop-stability/`'s own measurement, reached through an SSR port connected to nothing. |

`EN` is high throughout, so `HG` is at `VIN` and `Mhold_ss`/`Mhold_bg_ss` are in
cutoff: the pass gate belongs to the main loop. That is the hand-over state the
#191 regression names, and it is also what the real ramp does — `Rh_ss`/`Ch_ss`
release `HG` two orders of magnitude faster than the ramp completes.

### Why the load model changes with the ramp state

Low on the ramp the load **must** be resistive. The regulated output is a
fraction of a volt there, and an ideal sink demanding the rated 50 mA from a
0.1 V output has no solution on the regulating branch at all. A 36 ohm resistor
is what the rated load physically is (1.8 V / 50 mA) and it tracks the ramp,
exactly as `sim/soft-start/testbench/tb_soft_start.spice.in` models it.

At and above the hand-over the ideal sink is used **as well**, because that is
the model every `sim/loop-stability/` record uses and a margin measured against
a different load model is not comparable with them. A resistive load adds
`1/Rload` of damping in parallel with the output pole and flatters the result;
the sink is the conservative choice.

## The two things that make the numbers trustworthy

### 1. The extraction is `sim/loop-stability/`'s, not a copy of it

The deck's Tian/Middlebrook dual injection, its break at
`ERRAMP_OUT`/`PASS_GATE`, its `meas`-based margin extraction, its DR-0008
resurgence idiom with the fixed 5%-above-crossing scan start (#69) and its
`AC_DEC = 400` resolution policy (#58) are character for character
`tb_loop_stability.spice.in`'s. `sweep.py` **imports** that experiment's driver
and takes `PM_MIN_DEG`, `GM_MIN_DB`, `RESURGENCE_MAX_DB`, `AC_DEC`, `F_START`,
`F_STOP` and the PVT grid from it as the same Python objects, and its `Row`
subclasses that experiment's `Row` so `pm_deg` / `gm_db` / `passes` /
`resurges` are inherited rather than restated.
`sim/tests/test_soft_start_loop_gain.py` asserts that identity, and
`selftest.py` delegates the known-answer validation of the extraction to
`sim/loop-stability/testbench/selftest.py` rather than re-implementing one.

### 2. The `anchor` phase measures its own instrumentation

Reaching `SSR` at all requires bringing it out as a port. That transform is
mechanically minimal — one port name appended to `ldo_softstart`'s port list,
to `ldo_core`'s, and to the `Xsoftstart` instance line, on a **derived copy**;
nothing under `design/` is touched — and `SSR` is already a node of the cell,
so naming it in a port list renames nothing and connects nothing.

That is an argument. The measurement is the `anchor` phase: the same deck with
the new port left unconnected and the ideal 50 mA sink, which is electrically
`sim/loop-stability/`'s deck. Each run compares it point for point against

1. **`sim/loop-stability/`'s own sweep, re-run unmodified on the same host, in
   the same session, with the same binary and PDK.** This comparison has no
   toolchain term in it at all, so a delta is the deck difference and nothing
   else.
2. **the committed record `20260906-071437-fff0bf0`.** This one *does* have a
   toolchain term — a different host, a different ngspice build — which is
   exactly the case `sim/README.md`'s reproducibility caveat (#182/#185) says
   to check before reading a delta as evidence about the design. It is held to
   #182's own ~2 deg / ~1 dB movement class.

Both verdicts go in the record.

## The landing rule (and why `sim/loop-stability/`'s could not be reused as-is)

A phase margin is a statement about a *specific* DC operating point, and this
circuit has DC solutions that are not the one being named — `ldo_ilimit`'s
`CLG` clamp latched, or the pass device parked off with the divider unloaded.
`sim/loop-stability/` refuses any point whose `VOUT` is not within 10% of
1.8 V. That rule cannot work here: **low on the ramp the intended `VOUT` is
itself near zero**, which is exactly what a latch also looks like.

What discriminates is `FB`. The soft-start mechanism is "hold `FB` at `VREF`
with an injected current and let the divider set `VOUT`", so `FB ≈ VREF` is the
signature of the intended branch at *every* point of the ramp, while every
latch branch puts `FB` far from it. So a point is refused unless

- `|V(FB) − VREF| ≤ 180 mV` (the same absolute budget as loop-stability's 10%
  of 1.8 V), **and**
- `V(VOUT)` is inside the ramp's own range, **and**
- for the `anchor` phase only, `sim/loop-stability/`'s settled rule as well —
  the anchor has to land where that bench lands or the cross-check it feeds is
  empty.

A refused point voids its whole deck rather than entering the record; the deck
is retried once with `.nodeset` cards that start Newton on the intended branch,
held to the identical check, and any deck that needed the seed is named in the
record.

## The injection current is derived, not measured

Every row carries `iinj_ua`, the DC current the injection element delivers into
`FB`. It is exact KCL at the feedback node —

    I_inj = V(FB)/600k − (V(VOUT) − V(FB))/300k

— because at DC the only other branches there are the two divider resistors
(`XCff` sits across `Rtop` and carries no DC current), the error amp's gate, and
`Mpre_b_ss`'s drain (off while enabled). Deriving it this way means the *same*
expression measures both DUT variants without either deck knowing which element
is in it, which is what makes the A/B a like-for-like comparison of the thing
the hand-over is actually about.

## Pole/zero attribution: element removal that does not move the bias point

At the worst measured device-variant point, the record re-simulates that same
operating point through the netlist as committed, through the ideal element, and
through one netlist per **AC-only** removal of a single coupling:

| case | what it removes |
|---|---|
| `acopen-fb-inj` | `XMgmo_ss`'s drain, AC-opened from `FB` — the injection element's entire small-signal loading of the feedback node |
| `acopen-fb-pre` | `XMpre_b_ss`'s drain, AC-opened from `FB` |
| `acshort-gmsum` | the `GMSUM` mirror node, AC-shorted to `VIN` — whatever pole sits on `Mgmo_ss`'s gate |
| `acopen-hold` | `XMhold_ss`'s drain, AC-opened from `PASS_GATE` |

Each is a 1 GH inductor in series with a device terminal, or a 1 F capacitor
from a node to a rail. **An inductor is a short at DC and a capacitor is an open
at DC**, so the operating point is bit-identical and the margin delta is
attributable to that coupling and to nothing else — this is the difference
between an element-removal sensitivity and a re-design. The record prints each
case's landed `VOUT` and `I_inj` next to its margin so a reader can check that
rather than take it on trust.

For each case the record reports the model-free extremum (largest `|T|` and
phase difference anywhere in 0.01 Hz – 1 GHz, and where), and then fits
`T(as-committed)/T(case) = k(1+s/z)/(1+s/p)` — the exact form a single added R-C
on one node produces — with the fit residual printed, so the single-pole/zero
reading is a claim the data can refute. Where the model-free difference is below
the numerical floor (0.02 dB / 0.1 deg) **no fit is attempted**: there is no
pole or zero to attribute and reporting one anyway would be fitting noise.

## Model binning: `wnflag`, and why every deck here pins it

gf180mcu's device models are binned and the widest bin any of them has is
`W ≤ 100.01 µm` (`sm141064.ngspice`'s `wmax`). `design/ldo_core.sch`'s pass
device is `W=2000u nf=40` — 2 mm of width in 40 fingers of 50 µm — so the bin it
belongs in exists **only if the binning divides `W` by `nf`**.

Whether ngspice does that is not a property of the netlist or the PDK: it is
ngspice's `wnflag` (`src/spicelib/parser/inpgmod.c`), which defaults to 1 only
in HSPICE/Spectre compatibility mode and to 0 otherwise. On a host whose ngspice
starts with `"No compatibility mode selected!"` and has no `wnflag` in
`spinit`/`.spiceinit`, **every deck in this repo that instantiates the pass
device dies at parse time** with `could not find a valid modelname` — one of
`sim/harness/runner.py`'s `FATAL_LOG_PATTERNS`, so it is reported as a failure
rather than silently mis-simulated. That was observed on the host that produced
this experiment's first record, on all four locally-installed ngspice builds
(42, 46 ×2, 47).

This experiment therefore pins it in two places rather than depending on host
state no record captures:

- `.options wnflag=1` in the deck itself, and
- a generated `.spiceinit` (`set wnflag=1`, `set num_threads=1`) in the run's
  work directory, which is the cwd of every ngspice invocation the driver makes
  — including the `sim/loop-stability/` re-run for the cross-check, whose deck
  is used unmodified and so has to be given the setting out of band.

Both are recorded in the record's Environment section. The setting is not a
thumb on the scale: with it, `sim/loop-stability/`'s own deck reproduces its
committed record at the shared corners inside the #182/#185 movement class, so
it is what that record was taken under.

The other benches in this repo have the same exposure and no such pin; that is
filed separately rather than fixed here.

## Files

```
sim/soft-start-loop-gain/
  testbench/
    tb_ss_loop_gain.spice.in   the deck template
    sweep.py                   the driver: grid, variants, landing rule, record
    netlist_variants.py        the DUT netlist transforms (SSR port, A/B, AC-only removals)
    selftest.py                validates the method before any sweep runs
    compare_records.py         point-for-point diff of two records of this experiment
    run.sh                     the one-command entry point
  netlist-snapshots/
    <record-id>-device.spice   frozen DUT netlist, post-#195 chain
    <record-id>-binj.spice     frozen DUT netlist, pre-#195 ideal source
  corners/<record-id>/         raw ngspice logs: one per PVT point x variant x phase,
                               plus the attribution curves and the loop-stability re-run
  records/
    <record-id>.md             the append-only summary record
    <record-id>-matrix.csv     every point, machine-readable
```

Records are **append-only** per `sim/README.md`: a re-run mints a new record-id
and references the one it supersedes; nothing here is ever edited in place.

## Exit codes

`0` the sweep ran and every point landed on the intended DC branch; `1` a point
did not land, or the anchor cross-check disagreed beyond tolerance; `2` a
simulation failed; `3` an environment or usage problem. Note that unlike
`sim/loop-stability/`, a nonzero exit here is **not** a spec verdict — this
experiment has no spec row to pass or fail.
