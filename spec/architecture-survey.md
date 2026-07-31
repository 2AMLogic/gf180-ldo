# Architecture Survey: Pass Device and Compensation

**Status:** proposed (survey/trade-study — not yet a ratified decision; see "Path to
ratification" below)
**Date:** 2026-07-30
**Author:** Builder agent, issue #3
**Feeds:** #1 (spec ratification), #7 (scope decisions), #8 (schematic entry), #9
(error-amp design)

## Purpose and scope

This document is the foundational architecture survey requested by issue #3: a
recommendation for the LDO's pass-device type, pass-device voltage flavor, and
compensation strategy, plus an error-amplifier topology shortlist sized against the
quiescent-current (Iq) budget. It is written against the **draft** spec table in
`README.md` (engineering ratification is tracked separately in #1) and is structured
so it converts into one or more decision records with minimal rework once #6's
decision-record template lands (see "Path to ratification").

Everything below is a technical judgment call made from PDK documentation and
first-principles device physics, **not** from measured gf180mcu silicon data.
Device-level numbers (exact V_th, Rds·W, Cgg, resistor/cap menus) are #4's job;
where this survey needs such a number it states the assumption explicitly and marks
it "pending #4."

## Target spec (draft, from `README.md`)

| # | Parameter | Target | Stretch |
|---|---|---|---|
| 1 | Input | 3.3 V ±10% (Vin_min = 2.97 V, Vin_max = 3.63 V) | 5 V flavor |
| 2 | Output | 1.8 V ±2% (fixed) | programmable 1.2–3.0 V |
| 3 | Load | 50 mA | 100 mA |
| 4 | Dropout @ 50 mA | < 300 mV | < 200 mV |
| 5 | PSRR @ 1 kHz | > 50 dB | > 60 dB |
| 6 | Iq | < 30 µA | < 10 µA |
| 7 | Load reg (1–50 mA) | < 1% | — |
| 8 | Area (ex. pass-FET pad ring) | < 0.1 mm² | — |
| 9 | Stability | stable 0–50 mA with 1 µF ±ESR range | capless variant |

---

## 1. Recommendation summary (one sentence each)

- **Pass device: PMOS**, common-source, 3.3 V-flavor (`pfet_03v3`) as the primary
  device, with a straightforward flavor swap to the mid-voltage PMOS
  (`pfet_05v0`/`pfet_06v0`) if #7 pulls the 5 V input stretch into scope.
- **Compensation: external-cap, output-pole-dominant** (1 µF ±ESR, per #7's pending
  ESR-window decision) for the primary design; the **capless stretch is a separate
  compensation architecture**, not a component-value change, and should be treated
  as a forked variant.

The rest of this document is the rationale and the traceability required to defend
those two sentences.

---

## 2. Spec-row → architectural-implication traceability

| Spec row | Target | Architectural implication |
|---|---|---|
| 1. Input | 3.3 V ±10% (5 V stretch) | PMOS common-source pass device needs only a gate pulled toward GND to turn on hard — no charge pump required at 3.3 V (§3.2). The 3.3 V device flavor is used at the primary input; a 5 V stretch swaps the **pass-FET flavor only** in the straightforward case, but raises an amplifier-headroom question flagged as open (§3.4). |
| 2. Output | 1.8 V ±2% fixed (programmable stretch) | Resistive feedback divider from Vout to the error amp's inverting input; divider ratio (and hence resistor menu/area, pending #4) is fixed for the primary design. Programmability is explicitly **not** decided here — deferred to #7 (§6). |
| 3. Load | 50 mA (100 mA stretch) | Pass-FET width is sized from #4's Rds(on)-vs-W sweep (not yet landed) against the dropout target below; the compensation network (§4) must hold phase margin across the full 0–50 mA range, not just at one bias point. |
| 4. Dropout @ 50 mA | < 300 mV (< 200 mV stretch) | Direct driver of the PMOS-vs-NMOS call: only a common-source PMOS pass device can deliver low dropout at 50 mA from a single 2.97–3.63 V rail without a charge pump (§3.1–3.2, full headroom arithmetic below). |
| 5. PSRR @ 1 kHz | > 50 dB (60 dB stretch) | At 1 kHz — inside the expected loop unity-gain bandwidth for a sub-30 µA error amp (UGBW in the tens-to-low-hundreds of kHz range for typical Cgate/Cout loading) — PSRR is loop-gain-dominated, not pass-device-topology-dominated. PMOS's known high-frequency PSRR roll-off (§3.3) does not bite at 1 kHz. Amplifier gain/bandwidth budget in §5. |
| 6. Iq | < 30 µA (10 µA stretch) | Error-amp topology shortlist and current allocation in §5; divider standing current and reference bias are counted against the same 30 µA budget. |
| 7. Load reg (1–50 mA) | < 1% | Function of DC loop gain (error-amp topology, §5) and pass-device output impedance; same amplifier choice that sets PSRR margin sets this. |
| 8. Area (ex. pad ring) | < 0.1 mm² | Compensation choice trades directly against area: external-cap-dominant keeps the compensation cap off-chip (cheap on area); capless compensation needs an internal Miller/multiplier cap and (typically) an auxiliary buffer stage, both consuming on-chip area (§4.2). Pass-device W and resistor-menu area are #4's inputs, excluded from the pad-ring-excluded 0.1 mm² budget per the spec footnote. |
| 9. Stability | 0–50 mA w/ 1 µF ±ESR (capless stretch) | Primary: output-pole-dominant compensation, described fully in §4.1. Capless: a materially different compensation architecture, described in §4.2 and explicitly flagged as a fork rather than a variant of the same design. |

---

## 3. Pass-device recommendation

### 3.1 Why PMOS, not NMOS: the headroom arithmetic

The dropout spec is defined as the Vin − Vout differential at which the loop just
loses regulation at full load. For the < 300 mV @ 50 mA target, the **worst-case
dropout test point is Vin = Vout + 300 mV = 2.10 V**, at 50 mA — well below the
normal operating floor Vin_min = 2.97 V. Both device topologies must be checked
against this 2.10 V point, not just against 2.97 V.

**PMOS, common-source** (source at Vin, drain at Vout, gate driven by the error
amp): to turn the device on hard, the amplifier only needs to pull the gate toward
GND. At Vin = 2.10 V and gate ≈ 0 V, Vsg ≈ 2.10 V. Using an assumed 180 nm-class
3.3 V PMOS threshold of roughly |Vtp| ≈ 0.7 V (PDK-doc estimate — **pending #4
confirmation**), the available overdrive is Vsg − |Vtp| ≈ 1.4 V — ample overdrive to
hit a low Rds(on) at 50 mA with a reasonably sized device (#4's Rds(on)-vs-W sweep
will size W precisely; the point here is that the *headroom* is not the binding
constraint for PMOS). Even at the nominal floor Vin_min = 2.97 V, Vsg ≈ 2.97 V gives
~2.3 V of overdrive. The error amplifier's only requirement is an output stage that
swings down to (near) GND — a standard single-supply requirement, not a
rail-headroom problem.

**NMOS, source-follower** (drain at Vin, source at Vout, gate driven above Vout):
to deliver current, the gate must sit at Vgate ≥ Vout + Vgs(needed). At the same
worst-case dropout test point, Vin = 2.10 V. If the gate is driven from the Vin
rail directly (no charge pump), the gate can reach at most ~2.10 V, leaving
available Vgs = 2.10 − 1.80 = **0.30 V** — well short of the ~1.0–1.3 V total Vgs
(Vtn ≈ 0.7 V assumed, plus the overdrive needed for low Rds(on) at 50 mA) that an
NMOS pass device needs to conduct 50 mA with low series resistance. **An NMOS
follower physically cannot meet the < 300 mV dropout target from a rail that is
itself only 300 mV above Vout — the gate has nowhere higher to be driven from.**
This is not a marginal case that better biasing fixes; it requires a supply *above*
Vin at the pass-device gate, i.e. a charge pump.

A charge pump large enough to lift the gate rail well above Vin (to support 50 mA
worth of overdrive down to a 2.10 V input) would need to internally generate >3 V
from a 2.10 V input — more than a simple doubler provides efficiently at that input
floor — and charge pumps typically cost several µA of quiescent current for the
oscillator/driver alone, which would consume a large fraction (often all) of the
30 µA Iq budget (and essentially all of the 10 µA stretch budget) before the error
amp, reference, and divider are even accounted for. The switching ripple a charge
pump injects onto the gate rail also directly undermines the one PSRR advantage an
NMOS follower would otherwise bring (§3.3).

**Conclusion: PMOS is the only topology that meets the dropout spec inside the Iq
budget without a charge pump.** This matches the well-established convention in
single-supply, low-Iq LDO literature (Rincon-Mora & Allen 1998; see §7) that PMOS
pass devices dominate applications where dropout must be small relative to the
available headroom and Iq is tightly budgeted, while NMOS/charge-pump architectures
are reserved for designs that can spend the extra current and area for PSRR or
where Vin has generous headroom above Vout.

### 3.2 PSRR / loop-polarity implications

A PMOS common-source pass device places Vout at the drain — a high-impedance node
— with the error amplifier closing a negative-feedback loop from Vout (via the
resistive divider) back to the gate. Because the reference and the amplifier's own
supply rejection are ground-referenced (not Vin-referenced), Vin ripple is rejected
at frequencies inside the loop's unity-gain bandwidth by the loop gain itself: as
Vin moves, Vsg of the pass device shifts, but the loop corrects the gate voltage to
re-null the sensed output error. This is a **loop-gain-dominated PSRR mechanism**,
and it directly motivates the error-amp gain/bandwidth targets in §5.

The known weakness of PMOS common-source pass devices is PSRR roll-off **above**
the loop's unity-gain frequency: once the loop can no longer correct fast enough,
Vin ripple couples through Rds(on)/rds and Cgd of the pass device directly to Vout,
and PSRR degrades toward 0 dB well before very high frequencies. NMOS
source-followers are structurally better here (a source follower has inherent
supply rejection independent of loop gain, since Vin ripple reaching the drain is
attenuated by the device's own gm/output-impedance ratio rather than needing active
correction). **This distinction matters most above the loop UGBW, not at the 1 kHz
spec point**, which for a sub-30 µA amplifier with a UGBW plausibly in the tens to
low hundreds of kHz range sits well inside the loop-gain-dominated regime. The
recommendation is therefore PMOS with adequate loop gain/bandwidth (§5), not NMOS
for PSRR reasons — but if a future variant needs PSRR held out to much higher
frequencies (beyond the 1 kHz target in this spec), that would be a reason to
revisit this trade-off specifically at that frequency, not at 1 kHz.

### 3.3 5 V input-flavor stretch: does the PMOS choice survive?

Partially, with one open item. If #7 pulls the 5 V input stretch into scope:

- **The pass device itself swaps cleanly**: gf180mcu's mid-voltage PMOS flavors
  (`pfet_05v0`/`pfet_06v0`) replace `pfet_03v3` as the pass device. The
  common-source topology, the "pull gate to GND to turn on hard" gate-drive
  argument, and the dropout headroom argument all still hold — a 5/6 V PMOS just
  needs a proportionally larger W for the same Rds(on) (thicker gate oxide, lower
  mobility-overdrive product), which costs area but not architecture. #4's scope
  note already plans to sweep the 5 V/6 V PMOS Rds(on)·W rows for exactly this
  reason.
- **Open item**: the error amplifier's output stage must be able to swing the pass
  gate all the way to Vin to turn the PMOS **off** (Vsg = 0) at light load / at
  startup. If Vin rises to 5 V but the amplifier core stays on 3.3 V-flavor
  devices for area/Iq reasons, the amplifier's own output stage cannot swing to
  5 V without exceeding its device ratings — this needs either a 5 V-tolerant
  output stage/level-shifter (extra devices, extra Iq) or running more of the amp
  on mid-voltage devices (area/speed cost). **This is a real design fork, not a
  pass-device-only swap, and is left as an open question for #7's input-flavor
  record to resolve** (§6) — it should not be decided implicitly by whoever
  designs the amplifier in #9.

### 3.4 Device-level assumptions flagged for #4

- |Vtp| (pfet_03v3) ≈ 0.7 V, Vtn (nfet_03v3) ≈ 0.7 V — PDK-generation estimates,
  not measured. #4's characterization should confirm/replace these; if the actual
  |Vtp| is meaningfully higher, the PMOS overdrive margin in §3.1 shrinks but the
  qualitative conclusion (PMOS has comfortable margin, NMOS has none) is robust to
  several hundred mV of Vtp error given the size of the gap (2.3 V vs. 0.3 V of
  available Vgs at the worst-case point).
- Rds(on)·W at the worst dropout corner (ss, 125 °C, Vin = 2.10 V) is #4's job and
  directly sizes the pass FET; this survey does not propose a W.
- Amplifier UGBW (used qualitatively in §3.2/§3.3 to argue 1 kHz sits inside the
  loop-gain-dominated regime) depends on Cgate of the sized pass device, which is
  also #4's output (gate capacitance row).

---

## 4. Compensation recommendation

### 4.1 Primary case: external 1 µF cap, output-pole-dominant

With an external output capacitor (1 µF nominal, exact tolerance/ESR window
pending #7), the dominant pole is set at the output node:

```
p1 ≈ 1 / (2π · Rout · Cout)         Rout = Rload || Rds(pass)
```

Rout — and therefore p1 — moves with load current: at light load (1 mA), Rload is
large and p1 sits at its lowest frequency (worst case for phase margin); at full
load (50 mA), Rload shrinks and p1 moves to a higher frequency. **The classic
failure mode for output-cap-dominant LDOs is marginal phase margin at light load,
not at full load** — the stability matrix in #10 needs to sweep the full 0–50 mA
range for this reason, not just the full-load corner.

A second pole sits at the pass-device gate / amplifier-output node:

```
p2 ≈ 1 / (2π · Rgate · Cgate)
```

The output capacitor's ESR contributes a zero:

```
z_esr ≈ 1 / (2π · Resr · Cout)
```

Stability requires z_esr to fall between p2 and the loop's unity-gain frequency
(cancelling or compensating p2's phase contribution) across the full load and PVT
range — the standard reason external-cap LDOs specify **both** a minimum and a
maximum ESR (too little ESR: no zero to help phase margin; too much ESR: the zero
moves too low and itself degrades margin, or output ripple/transient response
suffers). **This is precisely the ESR-window decision #7 owns** — this survey
cannot enumerate #10's load × cap × ESR × PVT matrix without #7's concrete
min/max ESR numbers, and does not attempt to invent them here.

This is the standard architecture in single-supply, low-Iq PMOS LDO literature
(Rincon-Mora & Allen 1998, §7) and is the recommended primary compensation
strategy: it needs no dedicated on-chip compensation capacitor (favorable for the
< 0.1 mm² area budget), and it is compatible with the simpler single-stage or
two-stage error-amp candidates in §5.

### 4.2 Capless stretch: a fork, not a variant

Without an external output cap, the only capacitance at Vout is parasitic (pad,
ESD, routing — typically low tens of pF), which pushes p1 to a very high
frequency and removes the dominant-pole mechanism the primary architecture relies
on entirely. Meeting stability with 0 pF (or a few pF) of external capacitance
requires **relocating the dominant pole inside the amplifier** via one of:

- **Internal Miller compensation**: a compensation cap from Vout (or an internal
  high-impedance node) back to the amplifier's own high-impedance internal node,
  placing the dominant pole at the amplifier's output rather than at Vout.
- **Cap multiplier**: a smaller physical on-chip cap made to look like a larger
  effective cap via a buffered feedback network, trading a buffer stage's Iq for
  area savings versus a literal large on-chip cap.
- **Adaptive zero / dynamic biasing**: bias currents in the compensation or output
  stage are made to track load current so the zero-pole relationship (which
  otherwise shifts badly across a 0–50 mA range with negligible Cout) tracks
  stability requirements at both light and full load. This is the mechanism behind
  published damping-factor-control and adaptive-biasing capless LDOs (§7).

All three options typically pair with a low-output-impedance buffer stage (a
"flipped voltage follower" or super-source-follower is the most common published
choice, §7) rather than driving the pass gate directly from a single high-gain
stage, because the capless case needs the true output pole pushed to a very high
frequency independent of any external cap.

**This is a different amplifier and compensation architecture, not a
component-value change to the primary design** — it typically needs an auxiliary
buffer/local-loop stage (extra Iq and area beyond §5's primary budget) and a
purpose-built internal compensation cap (area, but on-chip MIM caps in the
picofarad-to-low-tens-of-picofarad range are plausible within the 0.1 mm² budget
per #4's expected MIM density numbers). **Recommendation: treat capless as a
forked design variant to be scoped separately (consistent with the posture #7 is
already weighing), not as a mode of the primary architecture.** This also means
the primary error-amp topology chosen in §5 does not need to be capless-capable
from day one.

---

## 5. Error-amplifier topology shortlist (Iq-budgeted)

Total Iq budget is < 30 µA (stretch < 10 µA) for the **whole regulator**, not just
the amplifier: this includes the error-amp bias branch, a voltage reference,
feedback-divider standing current, and any pass-gate bias. A rough primary-design
allocation, budgeted to leave headroom under 30 µA:

| Block | Rough current | Note |
|---|---|---|
| Feedback divider | ~1–3 µA | Requires a high total divider resistance (≳1 MΩ) to keep standing current low — an #4 resistor-menu input (area/kΩ, matching) |
| Reference (bandgap or bandgap-lite) | ~3–5 µA | Treated as a black box here; not this issue's scope |
| Error-amp bias | ~10–15 µA | See topology options below |
| Pass-gate bias / misc | ~2–3 µA | Startup, current-limit sense, enable logic |
| **Total (primary)** | **~16–26 µA** | Leaves margin under the 30 µA target; the 10 µA stretch is materially tighter and likely forces the leanest option (5T OTA) plus a very lean reference |

Shortlisted amplifier topologies, from leanest to most capable:

1. **Simple 5-transistor (5T) single-stage OTA** (one differential pair, current-mirror
   load, single-ended output driving the pass gate directly). Lowest current
   (~3–6 µA), lowest complexity, but only moderate DC gain (~40–50 dB) — may be
   short of the combined PSRR (50 dB stretch 60 dB) + load-reg (<1%) budget on its
   own. Best fit for the **10 µA stretch** Iq target if paired with a very lean
   reference, accepting a gain shortfall that must be checked against #9's PSRR
   budget once amp-level sims exist.
2. **Folded-cascode OTA**, single stage, single-ended output. Higher DC gain
   (~60–70 dB) than the 5T option for a modest current adder (cascode branches),
   with output-pole-dominant compensation (§4.1) needing only that the amplifier's
   own output node (p2) sit well above the output pole (p1) — a folded-cascode's
   naturally higher output impedance needs checking against Cgate for where p2
   lands, an #4/#9 input. Current budget ~8–12 µA. **Primary candidate.**
3. **Two-stage Miller-compensated OTA** (differential input stage + class-A
   common-source second stage driving the pass gate). More gain than a
   single-stage cascode, and the second stage can supply more slew current into a
   large pass-gate capacitance at fast 0→50 mA load transients — at the cost of
   needing its own Miller cap (which must coexist with, not fight, the primary
   output-pole compensation in §4.1). Current budget ~10–15 µA (1st stage
   ~3–5 µA, 2nd stage ~5–10 µA for adequate slew). **Primary candidate**,
   particularly if transient response at full 50 mA load steps drives the design.
4. **Flipped-voltage-follower (FVF) / super-source-follower buffer**, layered on
   top of options 2 or 3. Lower output impedance, better suited to the capless
   fork (§4.2) than to the primary design; adds its own bias branch (~5–8 µA).
   **Shortlisted specifically for the capless stretch variant, not the primary
   30 µA-budget design** — folding it into the primary design would likely blow
   the Iq budget for no benefit the primary (external-cap) architecture needs.

**Recommendation**: candidates 2 (folded-cascode) or 3 (two-stage Miller) for the
primary design, decided by #9 based on which better meets the offset/PSRR/slew
budget once amp-level sims are available; candidate 4 (FVF) reserved for the
capless fork. Candidate 1 (5T) is the fallback if the 10 µA stretch Iq target is
pursued and the resulting gain shortfall proves acceptable against #9's PSRR
budget.

Note: the **10 µA Iq stretch and the capless stretch are in tension** — an FVF/
capless-capable buffer stage typically costs more current than the leanest 5T-OTA
path to 10 µA. Whether both stretches are pursued simultaneously is a scope
question for #7/#1, not a fact this survey can resolve; flagged as an open
question below.

---

## 6. Open questions (explicitly deferred, not silently assumed)

These depend on scope decisions this survey does not own (mostly #7):

1. **Output-cap ESR window** (min and max, in ohms) — owned by #7's output-cap
   strategy record. §4.1's stability discussion is qualitative until that record
   lands; #10's stability matrix cannot be enumerated without it.
2. **Whether the primary design must also be capless-stable, or capless is a
   fully separate variant** — this survey recommends "separate variant" (§4.2)
   but the final call is #7's per its stated decision authority.
3. **5 V input-flavor timing** (now vs. deferred follow-on) — this survey shows
   the pass device swaps cleanly but flags an amplifier-headroom question (§3.4)
   that #7's input-flavor record should resolve explicitly, not leave for #9 to
   discover mid-design.
4. **Output programmability** (fixed 1.8 V vs. 1.2–3.0 V) — not addressed by this
   survey at all; owned entirely by #7's output-programmability record. If
   programmable, the feedback-divider area/current budget in §5 and the loop-gain
   assumptions in §3.2/§5 should be re-checked against the widened output range.
5. **10 µA Iq stretch vs. capless stretch simultaneity** (§5, note above) — not a
   #7 topic explicitly, but worth surfacing before #9 commits to a single
   topology assuming both stretches are free.
6. **Exact device parameters** (|Vtp|, Vtn, Rds(on)·W, Cgg, resistor/cap menus) —
   owned by #4; this survey's qualitative conclusions (§3.1, robust per §3.4) do
   not depend on precise values, but #8/#9's actual sizing does.

None of the above are silently assumed in the recommendations above — each is
either given a stated default (with rationale) or explicitly left to its owning
issue.

---

## 7. Prior art (public sources only)

- G. A. Rincon-Mora and P. E. Allen, "A Low-Voltage, Low Quiescent Current, Low
  Drop-Out Regulator," *IEEE Journal of Solid-State Circuits*, 1998. Foundational
  reference for the PMOS common-source, external-output-cap, ESR-zero
  compensation architecture recommended as the primary case in §4.1.
- G. A. Rincon-Mora, *Analog IC Design with Low-Dropout Regulators*,
  McGraw-Hill. Textbook treatment of PMOS-vs-NMOS pass-device trade-offs
  (dropout, gate-drive headroom, PSRR) referenced throughout §3.
- K. N. Leung and P. K. T. Mok, "A Capacitor-Free CMOS Low-Dropout Regulator
  with Damping-Factor-Control Frequency Compensation," *IEEE Journal of
  Solid-State Circuits*, 2003. Canonical adaptive/damping-factor-control capless
  compensation scheme cited in §4.2.
- J. Guo and K. N. Leung, "A 6-µW Chip-Area-Efficient Output-Capacitorless LDO
  in 90-nm CMOS Technology," *IEEE Journal of Solid-State Circuits*, 2010.
  Low-Iq, flipped-voltage-follower-based capless LDO cited in §4.2/§5 for the
  FVF buffer topology.
- R. J. Milliken, J. Silva-Martínez, and E. Sánchez-Sinencio, "Full On-Chip
  CMOS Low-Dropout Voltage Regulator," *IEEE Transactions on Circuits and
  Systems I*, 2007. Output-capacitorless architecture with internal Miller
  compensation, cited in §4.2.
- Open-source / open-PDK precedent: publicly published teaching and open-MPW
  LDO reference designs on the SkyWater sky130 open PDK (e.g. community
  "Zero to ASIC"-style course projects and open MPW-shuttle analog submissions)
  use the same PMOS common-source, external-output-cap architecture as their
  starting point, corroborating §4.1 as the conventional default on a comparable
  open, mature node rather than an unusual choice specific to gf180mcu.

No content, spec value, or trade-off specific to this repository was shared
externally to produce this survey; all citations above are to public literature.
Per CLAUDE.md, no proprietary content from this document is to be copied into
public issues or repos (including klayout-tools friction issues, which should
describe tool gaps generically if any arise from acting on this survey).

---

## 8. Consequences

- #8 (schematic entry) can proceed with a PMOS common-source pass device and an
  output-pole-dominant compensation topology (folded-cascode or two-stage Miller
  error amp, per #9's eventual choice) as its starting architecture, once #1
  ratifies and #4 supplies sizing data.
- #9 (error-amp design) has a topology shortlist (§5) and a rough current
  allocation to start its own budget, plus an explicit note that the FVF/capless
  buffer is out of scope for the primary design.
- #7's three scope decisions each have a concrete input from this survey: the
  output-cap record gets the qualitative stability argument for why a min/max ESR
  window matters (§4.1); the input-flavor record gets the "pass device swaps
  cleanly, amplifier headroom is the open item" finding (§3.4); the
  programmability record is untouched by this survey and remains fully #7's call.
- If #7 or #1 later overturns the PMOS or external-cap-primary recommendation,
  that is expected to happen as a superseding decision record once #6 lands
  (see below), not as a silent edit to this file.

## Path to ratification

This document predates #6's decision-record template (`spec/` currently contains
only this survey and `.gitkeep`). Per #3's acceptance criteria, it is deliberately
structured (Context/Recommendation/Alternatives-and-rationale/Consequences) to
convert cleanly once #6 lands: the pass-device recommendation (§3) and the
compensation recommendation (§4) are each self-contained enough to become their
own decision record (or to be folded into #1's ratification write-up) without
re-deriving the headroom arithmetic or the compensation trade study from scratch.
This survey itself does not ratify anything — ratification is #1's job, per repo
policy in `CLAUDE.md`.
