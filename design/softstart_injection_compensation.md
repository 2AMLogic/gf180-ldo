# What compensation a real soft-start FB-injection element needs

Issue #196. This is the answer to the question #191's Builder closed with —

> *"This looks like it needs proper loop-stability characterisation
> (`sim/loop-stability/`, #51/#176's territory) — apparently `Binj_ss`'s
> zero-parasitic model was implicitly providing compensation margin that #189
> never characterised when it removed `Cm_ss`/`Rz_ss`. Suggest either an
> architect look at what compensation a real `FB` injection element needs …"*

— and the answer is **none, and none is what should be added**. The measurement
that question presumed does not find a margin deficit anywhere; what it finds
instead is a DC transfer defect with four separately-quantified failure modes,
and the numbers to fix it against are in §3.

This is a **recommendation, not an implementation**. Nothing in `design/`
changes because of it beyond a one-line pointer in
`design/ldo_softstart.sch`'s existing regression note. Implementing any of it
belongs to #191's follow-on.

## Evidence

Every number below is from one record:

- **`sim/soft-start-loop-gain/records/20260910-015601-2387ece.md`** — the main
  loop's small-signal margins with `design/ldo_softstart.sch`'s FB-injection
  element *in the loop*, at pinned points of the soft-start ramp, for the
  post-#195 device-level chain (`device`) and the pre-#195 ideal `Binj_ss`
  (`binj`, frozen from `bfc4a0a`); plus the DC hand-over transfer of both, and
  an element-removal / capacitance-loading sensitivity at the worst corner.
  63 PVT points × 2 variants × 9 ramp states × 2 C_eff × 5 ESR = 11450
  loop-gain points, plus a 12222-point DC transfer.

That record's own anchor phase reproduces `sim/loop-stability/`'s measurement
to **0.009 deg / 0.016 dB** on a same-host, same-session re-run of that
experiment's unmodified driver, and to **0.726 deg / 0.252 dB** against its
committed matrix record `20260906-071437-fff0bf0` — inside the ~2 deg / ~1 dB
cross-invocation movement class #182/#185 established. So the deck is
`sim/loop-stability/`'s deck, and the numbers below are comparable with its
records.

Referenced for context, not re-run here:
`sim/soft-start/records/20260906-230703-d3cb117.md` (device chain, large
signal) and `sim/soft-start/records/20260906-202950-bfc4a0a.md` (ideal
source).

---

## 1. There is no phase-margin deficit to compensate

Three independent measurements, each of which could have found one:

| measurement | what it isolates | result |
|---|---|---|
| **A/B at matched ramp states**, 4550 (corner, state, C_eff, ESR) points where both elements have a crossover | the two elements' total effect, operating-point shift included | ΔPM **−20.84 … +14.17 deg**, **mean +0.08 deg** |
| **`acopen-fb-inj`** — `XMgmo_ss`'s drain AC-opened from `FB` at the worst measured device-variant point (`res_ss_-40c_3.63v`, `device/sink/ssr=1.15`, 1 µF/1 mΩ). A 1 GH inductor is a short at DC, so the operating point is bit-identical (landed `VOUT` 1.06953 V and `I_inj` +2.4329 µA on both sides) | the element's **entire** small-signal loading of the feedback node, with the operating-point shift held out | ΔPM **+0.053 deg**, ΔGM **+0.01 dB** |
| **`acshort-gmsum`** — the `GMSUM` mirror node AC-shorted to `VIN`, same point | whatever pole sits on `Mgmo_ss`'s gate | ΔPM **−0.001 deg**; max \|ΔT\| **0.003 dB** anywhere in 0.01 Hz – 1 GHz, i.e. below the 0.02 dB numerical floor, so **no pole or zero is fitted** |

The A/B's ±20 deg spread is **not** the element loading the loop: at a fixed
`V(SSR)` the two elements do not inject the same current, so they do not put
the loop at the same output voltage, and most of that spread is the pass
device being measured at a different transconductance. The `acopen-fb-inj`
row is the same question asked without that confound, and it answers
**+0.053 deg**.

Structurally this is what should be expected, and the measurement confirms it:
`Mgmo_ss`'s gate is driven by `SSR` and `VREF` only. The injection element is
a one-way current source into `FB`; the loop has no path back into it. Its
only possible small-signal effect on the main loop is its impedance at `FB`,
and removing that impedance entirely is worth 0.053 deg.

### The schematic note's hypothesis, tested directly

`design/ldo_softstart.sch`'s regression note says:

> *"ANY nonzero parasitic capacitance the real transconductor adds to FB (the
> 'tens of femtofarads' already called out under WHAT THIS COSTS THE MAIN
> LOOP) is enough to destabilize the main loop's hold-release transient."*

Removing this element's coupling only shows that *this* element is cheap. The
record therefore also **adds** known capacitance from `FB` to `VSS` on a ladder
from 10 fF to 1 nF (a capacitor is an open at DC, so every rung has a
bit-identical operating point — the record prints the landed `VOUT` for each so
that is checkable), at two points:

| point | budget: largest rung with PM within 2 deg and GM within 1 dB of the same point's own no-added-capacitance baseline | first rung outside it |
|---|---|---|
| worst measured device-variant point, `res_ss_-40c_3.63v` / `device/sink/ssr=1.15` / 1 µF/1 mΩ | **30 pF** | 100 pF (GM −73.69 dB) |
| nominal corner at the hold-release ramp state, `tt_27c_3.30v` / `device/ramp/ssr=0.05` / 1 µF/100 mΩ | **1 pF** | 3 pF (PM −2.29 deg) |

The feedback node therefore tolerates **at least 1 pF** before either margin
moves by the #182/#185 movement class. The schematic's own estimate of what
the device chain adds is "tens of femtofarads" — call it 30 fF — which is a
factor of **33** below that budget, on the same node where `Cff`'s 15 pF
already sits across `Rtop`. The hypothesis as stated is not supported.

*(The budget is stated against each point's own baseline, not against
DR-0001's 45 deg / 10 dB lines. A pinned mid-ramp state is not a DR-0001
operating point; and the worst-point ladder starts from 30.83 deg with no
added capacitance at all and with **either** injection element, because that
corner is `sim/loop-stability/`'s own open 1–50 mA gap, #51. Against an
absolute bar every rung there would "fail" and the ladder would say nothing
about capacitance.)*

### Recommendation R1 — add no compensation network

**Do not add a `Cm_ss`/`Rz_ss`-class network on the injection path, and do not
bandwidth-limit the `GMSUM` mirror.** There is no margin deficit for either to
fix (0.053 deg and 0.001 deg respectively), and the capacitance ladder shows
that deliberately loading `FB` is what *creates* one: 3 pF already costs
2.29 deg at the nominal hold-release state, and 100 pF collapses the gain
margin by 73.69 dB at the worst corner. A network sized to do anything at all
on a node whose whole budget is ~1 pF would be a net loss.

The corners in the record that *are* below 45 deg are below with **either**
injection element (see §5): they are `sim/loop-stability/`'s open 1–50 mA
phase-margin gap, #51, not the soft-start element's, and nothing in this
document touches them.

---

## 2. What is actually wrong: a 300 kΩ transimpedance on an inaccurate current

`#189` replaced the `#38`/`#43` clamp with pure current injection into `FB`.
That makes the regulated output during the ramp

```
VOUT = V(FB) + Rtop * ( V(FB)/Rbot - I_inj )        [ KCL at FB ]
     = 1.2 V + 300 kOhm * ( 2.0 uA - I_inj )
```

so **every microamp of injection error becomes 300 mV of output error**, and
every failure mode below is that one conversion factor applied to a different
part of the transfer. The ideal `Binj_ss` hides it by being exact:
`I = max(0, (V(VREF) − V(SSR)) · 5.0 µA/V)`, PVT-invariant, which the record's
`binj` rows reproduce to five digits at all 63 corners. A real element cannot
be exact, and the record measures how inexact this one is.

### The measured transfer, both elements, over the full PVT grid

| quantity | intent (`Binj_ss`) | `binj` measured | `device` measured | worst corner |
|---|---|---|---|---|
| `I_inj` at `V(SSR) = 0` | +6.0000 µA exactly | +6.0000 … +6.0000 µA | **+5.3230 … +8.8758 µA** | `ff_125c_3.63v` |
| transconductance over the live range | −5.000 µA/V exactly | −5.000 … −5.000 µA/V | **−4.560 … −3.730 µA/V** | `res_ff_-40c_2.97v` |
| `I_inj` still flowing at `V(SSR) = VREF` | 0 exactly | ±0.0000 µA | **+0.1707 … +4.1248 µA** | `ff_125c_3.63v` |
| `V(SSR)` at which `I_inj` drops below 50 nA and stays there | 1.200 V exactly | 1.200 … 1.200 V | **1.250 … 2.300 V, and never at 2/63 corners** | `ff_27c_3.63v` |
| highest `V(SSR)` at which the loop is **out of regulation** | never | never | **up to 0.700 V, at 37/63 corners** | `ff_125c_3.63v` |
| largest `V(FB)` anywhere on the ramp | 1.2 V + a fraction of a mV | 1.20012 … 1.20014 V | **1.19943 … 1.77535 V** | `ff_125c_3.63v` |
| residual injection at the settled point | +0.03333 nA | +0.03333 nA | **+467.1 nA** | `sf_125c_3.63v` |
| settled output error | −1.16 mV (−0.064%) | −1.16 mV | **−141.26 mV (−7.848%)** | `sf_125c_3.63v` |

The last two rows are the same number twice: 467.1 nA × 300 kΩ = 140 mV, and
the measured settled error is −141.26 mV. That is the ratified Startup row's
±2% accuracy clause failing by ~4×, and it is the same failure
`sim/soft-start/records/20260906-230703-d3cb117.md` reports as 28/163 settled
points.

### Root cause of the rectification failure, measured

The chain is meant to rectify by construction: for `V(SSR) > VREF`, `Mgma_ss`'s
branch current falls below `Mgmb_ss`'s, `Mgmr_ss` would have to source negative
current, so it cuts off and `Mgmo_ss` (its 1:1 mirror) stops sourcing into
`FB`. The record shows why it does not: **the two legs of that mirror do not
see the same drain voltage, and the mismatch grows one-for-one with `VIN`.**
`Mgmr_ss` is diode-connected, so its |V_ds| equals its |V_gs|; `Mgmo_ss`'s
drain is the feedback node at 1.2 V, so its |V_ds| is `VIN − 1.2 V`. At
`V(SSR) = VREF`, where the intent is zero (all values read out of the record's
`-handover.csv`):

| corner | `VIN` | `V(GMSUM)` | \|V_gs\| both legs | \|V_ds\| `Mgmr_ss` | \|V_ds\| `Mgmo_ss` | mirror ΔV_ds | `I_inj` at `V(SSR)=VREF` |
|---|---|---|---|---|---|---|---|
| `tt_27c_2.97v` | 2.97 V | 2.1465 V | 0.824 V | 0.824 V | 1.770 V | **0.947 V** | +0.451 µA |
| `tt_27c_3.30v` | 3.30 V | 2.3986 V | 0.901 V | 0.901 V | 2.100 V | **1.199 V** | +1.347 µA |
| `tt_27c_3.63v` | 3.63 V | 2.6683 V | 0.962 V | 0.962 V | 2.431 V | **1.469 V** | +2.538 µA |
| `ff_125c_3.63v` | 3.63 V | 2.8104 V | 0.820 V | 0.820 V | 2.431 V | **1.611 V** | +4.125 µA |

Two things follow, and both are load-bearing for §3:

1. **The mirror's |V_gs| at the intended cut-off point is 0.82 – 0.96 V**, i.e.
   at or barely above a gf180mcu `pfet_03v3` threshold. The element is asked to
   turn off in weak inversion, which is exactly the region where drain-bias
   sensitivity is strongest — so a 0.95 – 1.61 V drain-voltage mismatch between
   the copying leg and the copied leg does not produce a few per cent of mirror
   error, it produces the microamps the table shows.
2. **The error is supply-driven, not process- or temperature-driven.** Over the
   19 (process, temperature) pairs where the chain releases at all three
   supplies, moving `VIN` from 2.97 V to 3.63 V moves the `V(SSR)` at which it
   lets go by **+0.375 V to +0.675 V** — a mean of **0.917 V of ramp node per
   volt of supply**, against 0 for the ideal element. Worst: `sf` at −40 °C,
   releasing at 1.400 V / 1.725 V / 2.075 V for 2.97 / 3.30 / 3.63 V. That is
   the fingerprint of `VIN − V(FB)` appearing in the mirror's error term, and
   it is why the #191 sizing sweeps (2×/4× scaling, W/L both directions) could
   not help: none of them changes ΔV_ds.

---

## 3. The recommendation, with numbers

### R1 — no compensation network (§1)

Restated here so the list is complete: nothing should be added on the
injection path, on `GMSUM`, or on `PASS_GATE` in the name of compensating this
element. The evidence is 0.053 deg, 0.001 deg, and a ≥ 1 pF budget on `FB`
against a ~30 fF contribution.

### R2 — match the mirror's drain voltages: cascode `Mgmo_ss` against `Mgmr_ss`

This is the fix the measurement points at. Make `Mgmo_ss`'s drain sit at the
same potential as `Mgmr_ss`'s (a cascode on the output leg, with the reference
leg cascoded to match — an ordinary cascode current mirror), so the mirror's
ΔV_ds goes from 0.95 – 1.61 V to ~0.

**Headroom check, at the binding corner (minimum supply):** `VIN − V(FB)` =
2.97 − 1.2 = **1.77 V** is available on the output leg. `Mgmo_ss` needs
|V_ds| ≈ |V_gs| ≈ **0.82 V** to match its reference leg, leaving **0.95 V**
across the cascode device. A `pfet_03v3` at these currents (single-digit µA)
needs |V_dsat| of order 0.1 – 0.2 V, so the available headroom is **5 – 9×**
the requirement. The fix is not headroom-limited.

**Small-signal cost, pre-checked:** a cascode adds a node in the injection
path and some capacitance at `FB`. §1's budget is ≥ 1 pF at `FB` and the whole
present element is worth 0.053 deg; a cascode's contribution is in the same
tens-of-femtofarads class. **This is affordable, and §1's ladder is the check
to re-run after the change rather than an argument to have again.**

**Why not the levers already tried.** #191 swept `Mgmr_ss`/`Mgmo_ss` scaling
(2×, 4×) and W/L both directions and found none of them helped. This record
explains it: those levers move output resistance and threshold, and the error
term they need to move is a **drain-voltage difference** that none of them
touches. A series decoupling resistor between `Mgmo_ss`'s drain and `FB` (also
tried, 10 k/100 k/1 M) makes it strictly worse — at µA currents its own IR drop
moves `FB` off `VREF`, which is the same 300 kΩ-transimpedance problem again.

### R3 — the numeric targets any replacement injection element must meet

Each target, its derivation, and where the present chain sits.

| # | target, all 63 PVT corners | derivation | `device` today |
|---|---|---|---|
| **T1** | `I_inj ≤ 50 nA` for all `V(SSR) ≥ VREF` | residual injection reaches the output as `Rtop × I_res` = 300 kΩ × I_res. The ratified accuracy clause is ±2% of 1.8 V = ±36 mV; allocating ≤ 15 mV (0.83%) to this term gives 50 nA | **+170 nA … +4125 nA at `V(SSR) = VREF`**; **+467 nA still flowing settled**, = −141 mV of output error, a ratified-row failure |
| **T2** | `I_inj(V(SSR) = 0) ≤ 6.00 µA`, and within ±0.10 µA of it | 6.00 µA = `VREF/Rbot + VREF/Rtop` is exactly the current the divider absorbs with the output at zero. **Above it there is no DC solution with `FB` at `VREF`** — the loop opens, the error amplifier rails and the pass device parks off. Below it, the shortfall is a nonzero starting output, 300 kΩ per µA; ±0.10 µA is ±30 mV | **+5.32 … +8.88 µA** (−11% … +48%). Loop out of regulation up to `V(SSR) = 0.70 V` at **37/63 corners**, with `V(FB)` pushed to 1.775 V |
| **T3** | transconductance −5.00 µA/V ±5% | 1/(`Rtop`‖`Rbot`) = 1.5/`Rtop` = 5.0 µA/V is what makes `VOUT = 1.5·V(SSR)` exact; ±5% keeps the ramp slope and therefore the 3 ms settling clause inside the allocation the ideal element was verified against | **−4.56 … −3.73 µA/V** (−9% … −25%) |
| **T4** | release point `V(SSR)` = 1.200 V, +0/−0 to within the ramp's own step | the whole hand-over is defined at `V(SSR) = VREF`; a release above it stretches the ramp into the 3 ms settling window, and a release that never happens is T1's failure | **1.250 … 2.300 V; never releases at 2/63 corners** |
| **T5** | the loop is in regulation (`\|V(FB) − VREF\| ≤ 5 mV`) at **every** `V(SSR)` from 0 upward | a ramp state where the loop is open has no loop gain, no phase margin, and no small-signal description at all; it is also the state whose *exit* is the leading unexplained candidate for #191's transient (§4) | violated up to `V(SSR) = 0.70 V` at **37/63 corners** |
| **T6** | the element's own contribution to the main loop: ΔPM ≤ 2 deg and ΔGM ≤ 1 dB, measured by DC-preserving AC-open of its output drain from `FB` | the #182/#185 cross-invocation movement class — below it, a delta is not distinguishable from re-running the same command | **+0.053 deg / +0.01 dB — met, with ~40× margin** |
| **T7** | total capacitance the element hangs on `FB` ≤ 1 pF | the tighter of the record's two capacitance ladders (§1) | **~30 fF (schematic estimate) — met, with ~33× margin** |

**T6 and T7 are already met and are listed so a fix does not break them.**
T1–T5 are the work.

### R4 — the structural point, if T2/T3 turn out not to be reachable

T2 is an *absolute* accuracy requirement on a microamp current: ±0.10 µA out of
6.00 µA is ±1.7%, over process, ±10% supply and −40…125 °C, on an
uncalibrated on-chip transconductor. R2 removes the dominant error term but
does not by itself make that budget comfortable.

If it cannot be met, the lever is the **300 kΩ transimpedance**, not the
element:

- **Scaling the divider down** (e.g. `Rtop`/`Rbot` = 30 k/60 k, injection
  60 µA, transimpedance 30 kΩ) buys a 10× relaxation on every target above.
  It is **closed by the ratified Iq row**: the divider currently draws
  `VOUT`/900 kΩ ≈ 2 µA, and the enabled Iq measures 24.81 µA against a
  ratified < 30 µA (`sim/enable-shutdown/records/20260802-172454-b90b2ba.md`).
  A 10× divider adds ~18 µA and blows it on its own, before the injection
  current is counted. Recorded here so it is not re-derived.
- **Restoring an output-side clamp** — the thing #189 removed — so the bottom
  of the ramp is defined by a clamp rather than by the *difference* of two
  microamp currents. That reinstates a second loop and its compensation
  question (`Cm_ss`/`Rz_ss` existed for it), and is a topology decision, not a
  sizing one: it needs a DR, not a patch.

Both are named so the follow-on starts from the constraint rather than
rediscovering it.

---

## 4. What this does *not* explain, stated plainly

The record does not close #191's transient arithmetic, and it says so:

- At `tt_-40c_2.97v` — the corner #191's own A/B used — the output the loop is
  asked to acquire at hold release (`V(SSR)` ≈ 0.05 V) is **74.5 mV** with the
  ideal element and **159.3 mV** with the device chain: a factor of **2.1**.
- #191's transient A/B at that same corner reads **0.468 mA** and **166.7 mA**:
  a factor of **356**.
- A 2.1× difference in the voltage the loop must acquire cannot by itself
  produce a 356× difference in the current it acquires it with.

The ideal element's half *is* consistent: 1 µF × 74.5 mV / 0.468 mA implies an
acquisition time of **159 µs**, which is the `Rh_ss`·`Ch_ss` hold release
(4870 µm of 3 kΩ/□ `ppolyf_u_3k` ≈ 14.6 MΩ into a 70 × 70 µm mim cap ≈ 9.8 pF,
≈ 143 µs) and is consistent with #195's own note timing its glitch at ~300 µs.
Apply the same 159 µs to the device chain's 159.3 mV and the prediction is
**1.0 mA**, not 166.7 mA. So the device chain's transient is not a scaled
version of the ideal one — something in it does not track the hold release.

What §1 *does* settle is that the missing mechanism is **not** a small-signal
margin deficit at any pinned ramp state, and **not** the element's loading of
`FB`. The leading remaining candidate is in §2's T5: the loop is genuinely
**open** at the bottom of the ramp at 37 of 63 corners with this element, and
the exit from that state is a large-signal recovery of a railed error
amplifier onto an uncompensated `PASS_GATE` — a mechanism no pinned-`V(SSR)`
small-signal margin can describe, and the one place where the removal of
`Cm_ss`/`Rz_ss` could still matter.

**The next experiment, named so it does not have to be re-invented:** a
transient A/B in `sim/soft-start/` with `V(SSR)` driven by an *ideal* ramp
source through the same promoted `SSR` port this experiment adds, instead of by
`Fss_ramp`. That separates the injection element's transfer from the ramp's own
dynamics and from the hold release, and it makes the out-of-regulation exit
observable as a time rather than inferred from a DC sweep. It is a
`sim/soft-start/` change, not a `design/` change, and it is out of scope for
#196.

---

## 5. The margins themselves, for reference

Worst case over the whole 63-point PVT grid and both output-network axes, per
ramp state, both elements. DR-0001's 45 deg / 10 dB are **reference lines**
here, not a criterion: a pinned mid-ramp state is not a DR-0001 operating
point, and `sim/loop-stability/` remains this design's phase-margin record.

| ramp state | `binj` worst PM / GM, at | `device` worst PM / GM, at |
|---|---|---|
| `ramp`, `V(SSR)` = 0 | *no 0 dB crossing at any of its 630 points — the pass device is not conducting, so there is no loop to have a margin* | 46.22 deg / 32.13 dB, `fs_125c_2.97v` 4.7 µF/1 mΩ |
| `ramp`, 0.05 (hold release) | 48.08 deg / 33.77 dB, `fs_125c_2.97v` | 45.51 deg / 32.62 dB, `res_ff_125c_2.97v` |
| `ramp`, 0.15 | 44.98 deg / 32.38 dB, `res_ff_125c_2.97v` | 44.62 deg / 31.72 dB, `res_ff_125c_2.97v` |
| `ramp`, 0.6 | 39.16 deg / 10.25 dB, `res_ss_-40c_3.63v` | 43.05 deg / 10.80 dB, `res_ss_-40c_3.30v` |
| `ramp`, 1.15 (VREF − 50 mV) | 32.45 deg / 8.35 dB, `res_ss_-40c_3.63v` | 36.25 deg / 8.90 dB, `res_ss_-40c_3.30v` |
| `ramp`, 1.25 (VREF + 50 mV) | 32.06 deg / 8.24 dB, `res_ss_-40c_3.63v` | 35.51 deg / 8.70 dB, `res_ss_-40c_3.30v` |
| `sink`, 1.15 | 31.34 deg / 8.13 dB, `res_ss_-40c_3.63v` | 30.83 deg / 8.00 dB, `res_ss_-40c_3.63v` |
| `sink`, 1.25 | 31.41 deg / 8.15 dB, `res_ss_-40c_3.63v` | 30.91 deg / 8.02 dB, `res_ss_-40c_3.63v` |
| `sink`, 1.8 | 31.41 deg / 8.15 dB, `res_ss_-40c_3.63v` | 31.38 deg / 8.14 dB, `res_ss_-40c_3.63v` |
| `anchor` (settled) | 31.41 deg / 8.15 dB, `res_ss_-40c_3.63v` | 31.42 deg / 8.16 dB, `res_ss_-40c_3.63v` |

All worst-case cells are at 1 µF / 1 mΩ except the three at `*_125c_2.97v`,
which are at 4.7 µF / 1 mΩ. The `device` variant's `ramp` rows exclude the 20
(PVT, variant, phase) decks the record voids because the device chain has no
DC solution near `VREF` there — every one of them a `device` deck, and 17 of
the 20 at `VIN` = 3.63 V. That exclusion is itself T2/T5's failure showing up a
second way, and the record names each voided deck.

The states below 45 deg are below with **both** elements, at the same corner,
and the settled row matches `sim/loop-stability/`'s own measurement to
0.009 deg on a same-host re-run. They are #51's open 1–50 mA main-loop gap,
which is operator-held and is not this element's to fix.

No point in the record — 11450 of them — has \|T\| back above 0 dB anywhere
above its first 0 dB crossing (worst −0.07 dB), so DR-0008's misreading
precondition is absent throughout.

---

## 6. How to check a fix

One command, from a clean checkout:

```bash
python3 sim/run_corners.py --check-env
./sim/soft-start-loop-gain/testbench/run.sh
```

Then read the new record against **R3**'s table and against
`20260910-015601-2387ece` point for point:

```bash
./sim/soft-start-loop-gain/testbench/compare_records.py \
    20260910-015601-2387ece <NEW_ID>
```

A fix is done when T1–T5 pass at all 63 corners, T6 and T7 are still met, and
the record's `anchor` phase still reproduces `sim/loop-stability/` — that last
one because a change to the injection element must not move the settled loop,
and the anchor is what would show it if it did.

The settled-accuracy and inrush verdicts remain `sim/soft-start/`'s; this
experiment cannot issue them and does not try to.
