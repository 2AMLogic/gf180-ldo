# Chipalooza Challenge #5 (GF180MCU / Wafer.Space) — 1.8 V LDO proposal

Submission target: Open Circuit Design's [Chipalooza Challenge
#5](https://opencircuitdesign.com/chipalooza/) (GF180MCU test chip fabricated
through Wafer.Space; proposals launch ~2027-01-04, due 2027-01-18). Challenge
#5 follows the same structure and slot budget as Challenge #3.

**Source repository**: `2AMLogic/gf180-ldo` (public, Apache-2.0 — see §8).
Every number in §4 is transcribed from this repository's own append-only
`sim/` evidence, with a dated citation to the record it came from — nothing
here is asserted without a re-runnable testbench. This document is written to
be emailed verbatim as the block's public proposal. It contains no personal
or institutional identifiers; designer CVs and the test-equipment list are
separate email attachments the submitting operator supplies outside this
repository.

**Maturity disclosure, stated up front**: unlike a proposal written against a
block that already has committed layout, this repository has **no GDS
anywhere** as of this writing (2026-09-05) — a repo-tree search finds zero
`.gds` files. What exists is a ratified specification, four xschem schematics
covering the full LDO hierarchy with corner-swept schematic-level simulation
evidence, and a DRC/LVS-clean physical-verification *flow* proven end to end
on a deliberately trivial one-transistor test cell (`layout/README.md`) — but
no layout of the LDO block itself. Per the operating principle behind this
whole proposal (and the one `2AMLogic/gf180-sar-adc`'s Challenge #3 proposal
already followed): **the acceptance criterion for this document is to state
the design honestly at its current maturity, not to have already closed every
gap.** §7 lists what remains, with the issue tracking each item.

---

## 0. Rail-scope decision (stated explicitly, per this repository's own spec)

Challenge #5 offers **3.3 V digital + 5.0 V analog rails**, with analog blocks
expected to operate across 3.3–5.0 V. **This proposal is 3.3 V-only.** This
block's ratified spec
([`spec/decision-records/DR-0004-spec-ratification.md`](../../spec/decision-records/DR-0004-spec-ratification.md))
targets **3.3 V ±10 % (2.97–3.63 V) on 3.3 V-flavor devices throughout** (pass
FET, error amplifier, reference), with the 5.0 V input explicitly deferred as
a separate follow-on variant
([`spec/decision-records/DR-0002-input-flavor.md`](../../spec/decision-records/DR-0002-input-flavor.md)).
DR-0002's own revisit trigger has not fired — no `pfet_05v0`/`pfet_06v0`
sizing study meeting its stated bar has been run, and no amplifier-headroom
study for a 5 V-tolerant gate drive exists. **No decision record has been
opened to scope in the 5.0 V variant**, so per DR-0002's default and this
epic issue's own instruction, this design does not use the Challenge's 5.0 V
analog rail at all. This is a scope choice stated plainly, not a gap silently
absorbed — it is the same move `gf180-sar-adc`'s Challenge #3 proposal made
for its own 3.3 V-only design. What a future 5.0 V variant would cost is
already estimated in DR-0002's "Consequences" section: a re-sized and
re-laid-out mid-voltage pass FET, a 5 V-tolerant gate-drive path in the error
amp, and a full re-run of every `sim/` PVT campaign and the loop-stability
matrix at the new input range — a variant, not a new design.

---

## 1. Type of IP block

A fixed-output, single-rail **low-dropout linear voltage regulator (LDO)**:
1.8 V ± 2 % output from a 3.3 V ± 10 % input, PMOS common-source pass device,
two-stage Miller-compensated error amplifier, constant-current (brickwall)
current limit, and a controlled-ramp soft-start. Rated load 0–50 mA
(100 mA stretch, not yet separately verified). Target application: a
general-purpose point-of-load regulator — the natural power-management
companion to a bandgap/voltage-reference block, and the design rationale
this repository's own README states for choosing an LDO as an agent-designed
canary on this PDK.

---

## 2. I/O list, including test ports

### 2.1 Rails: this block uses the Challenge's 3.3 V digital rail only

Per §0, this design draws its single `VIN`/`VSS` supply from the Challenge's
3.3 V digital rail and does not use the 5.0 V analog rail at all — this
block has never been simulated, laid out, or characterized above 3.63 V.

### 2.2 Pad table, mapped to the Challenge #5 slot budget

| Signal | Dir | Challenge slot | Count used | Notes |
|---|---|---|---|---|
| `VIN`, `VSS` | supply | 3.3 V digital rail (`VSS` shared ground) | — (rail, not a slot line item) | `VIN` still needs to be **independently drivable across 1.75–3.63 V** by the bench/harness for line-regulation, dropout, and PSRR tests — see the dedicated-pad note below on why the rail alone is not enough |
| `VIN` (dedicated sweep access) | in, dedicated | dedicated pad (budget: up to 4) | 1 of 4 | This block's own PVT matrix sweeps `VIN` down to 1.75 V during dropout characterization (`sim/dropout-vs-load/`) and across 2.97–3.63 V for line regulation — well outside a fixed "3.3 V digital rail" tap. A dedicated pad the harness/bench can independently source is required; the shared rail cannot double as this pin without defeating the measurement |
| `VOUT` | out, dedicated | dedicated pad (budget: up to 4) | 1 of 4 | The regulated output — the block's entire product, and the node the ratified current-limit test forces to a dead short (§4). Must sink/source up to the current-limit ceiling (~65–94 mA measured, §4) continuously; a shared multiplexed analog line is not rated for that and would also add series resistance that corrupts the sub-mV/sub-mA precision the Load reg and Line reg rows measure at |
| `EN` | in | digital control input (budget: up to 24) | 1 of 24 | Active-high, CMOS-level (0 V / `VIN`). Gates the pass device, the amplifier bias, the current-limit block's bias, and soft-start's bias/ramp reset — one enable path, no second path anywhere in the hierarchy (`design/README.md`, "Enable path and the disabled state") |
| `VREF` (bandgap-referenced bias voltage) | in, dedicated | bandgap-referenced bias voltage (budget: 1) | **1 of 1** | 1.2 V nominal reference input. This **is a real top-level port** of `ldo_core` as of issue #174 / [DR-0021](../../spec/decision-records/DR-0021-vref-is-a-top-level-port.md): `.subckt ldo_core VIN VOUT EN VSS ERRAMP_OUT PASS_GATE VREF`. `ldo_core` **consumes** a reference and does not generate one — so this pin is not optional, and the harness's bandgap-referenced bias voltage is exactly what it is asking for (the same substitution `gf180-sar-adc`'s Challenge #3 proposal makes for its own `V_REF`). Feeds three consumers on one net: `error_amp`'s `INN`, `ldo_ilimit`'s bias generator, `ldo_softstart`'s ramp ceiling. **The driver must source this block's reference bias current** (measured at the port, per corner — §4 `I_ref` row) and its own tolerance/tempco/noise/PSRR pass to `VOUT` at 1/β = 1.5× — see §6 |
| `ERRAMP_OUT`, `PASS_GATE` (loop-break test ports) | test-only | not proposed to consume Challenge pad budget | 0 of 4 | Two internal loop-break points (`design/README.md`, "Loop-break point: two ports, not one") that every existing testbench ties together at instantiation for closed-loop operation, and only separates for bench stability-injection testing. In the production/submission wrapper these are proposed tied together on-chip (as every testbench already does), consuming none of the Challenge's dedicated-pad or shared-analog-line budget |

**Totals against the Challenge #5 budget**: **1 of 1** bandgap-referenced
bias voltage (`VREF`, a real pin since #174/DR-0021), 0 of ≤2
bandgap-referenced current sources, 1 of ≤24 digital control inputs, 0 of ≤12
digital test outputs, **3 of ≤4 dedicated pads** (`VIN`, `VOUT`, `VREF`),
**0 of ≤4** shared (multiplexed) analog lines. Every category fits inside
budget, with the entire current-source and digital-test-output allocation
unused by this block.

### 2.3 What's dropped, multiplexed, or substituted relative to this repo's own port list

- **Nothing is dropped.** `VIN`, `VOUT`, `EN`, `VSS`, `VREF` are exactly the
  production-facing subset of `ldo_core`'s seven netlist ports
  (`design/README.md`'s pinout table); `ERRAMP_OUT`/`PASS_GATE` are
  test-only and were never proposed as customer-facing pins even in this
  repository's own testbenches.
- **`VREF` is substituted by the harness's bandgap-referenced bias
  voltage** — the one substitution, and now the *same* substitution
  `gf180-sar-adc`'s Challenge #3 proposal makes for its own `V_REF`, rather
  than an aspiration: issue #174 / DR-0021 promoted `VREF` to a real
  top-level port, deleting the ideal in-cell source that stood in for it.
  Verified electrically inert — DR-0021's "Evidence" section tabulates a
  back-to-back re-run of every affected `sim/` bench against the pre-change
  tree on the same host, with no corner's verdict moved (§4).
- **No pins are shared/multiplexed.** Both `VIN` (needs independent sweep
  access down to the dropout knee) and `VOUT` (needs to carry the full rated
  and current-limited load current) have requirements a multiplexed analog
  line's added series impedance would directly violate.

---

## 3. Functional description

A PMOS common-source pass device (`XMpass`, `pfet_03v3`, `W` = 2000 µm)
regulates `VOUT` to 1.5×`VREF` = 1.8 V via a 300 kΩ/600 kΩ resistive feedback
divider and a two-stage Miller-compensated error amplifier (NMOS input pair,
PMOS mirror load, PMOS common-source second stage, ~9 µA nominal —
`design/error_amp.md`). A constant-current (brickwall, not foldback) current
limit senses a 1/40 replica of the pass device's current and clamps the pass
gate before the sensed current is delivered back to `VOUT` rather than
burned, preserving the Iq budget. A controlled linear ramp (soft-start)
clamps `VOUT`'s rise at enable to avoid excess inrush and current-limit
engagement during startup. `EN` gates every bias branch in the hierarchy off
one net, so the disabled state is pass device fully off with no internal
active discharge and no second enable path. Full topology and per-cell
rationale: `design/README.md`.

**Material, stated gaps in physical and reference readiness**:

1. **No layout exists.** `layout/README.md`'s one-transistor DRC/LVS flow is
   proven end to end (`klt` DRC, PDK DRC, LVS, and two negative controls all
   pass on the trivial test cell) but has never been run against `ldo_core`
   itself. Tracked in a follow-up issue filed alongside this proposal (§7).
2. **No bandgap/reference block exists, and this design does not contain
   one — by decision, not by omission.** Issue #174 /
   [DR-0021](../../spec/decision-records/DR-0021-vref-is-a-top-level-port.md)
   settled this: `ldo_core` **consumes** a 1.2 V reference through its
   `VREF` port and does not generate one, and a bandgap is not built in this
   repository (that block is the subject of the sibling repo
   `2AMLogic/gf180-bandgap`; DR-0021 records why forking a second one here
   was rejected). This is now exactly the same shape of dependency
   `gf180-sar-adc`'s proposal disclosed for its own externally-supplied
   `V_REF` — and it is what the Challenge's bandgap-referenced bias-voltage
   slot exists to satisfy (§2.2). **The honest cost**: every accuracy, PSRR
   and noise number in §4 is measured against an *ideal* reference, so the
   real reference's own tolerance, tempco, noise and supply rejection are
   excluded from all of them and enter `VOUT` at 1/β = 1.5× once a real one
   is attached (§6).

Everything else in the hierarchy — the pass device, feedback divider,
amplifier, current-limit block, and soft-start block — is drawn at
transistor level in `design/*.sch` and exported to a checked, byte-reproducible
netlist (`python3 design/netlist.py --check`).

---

## 4. Target specification at the Challenge rails

**What "at the challenge rails" means here**: per §0/§2.1, this block runs
its single 3.3 V supply from the Challenge's 3.3 V digital rail and does not
use the 5.0 V analog rail. Every row below is reported at this repository's
own ratified PVT grid — process corners {tt, ff, ss, fs, sf} (plus, where the
cited record's own matrix includes them, the `res_ff`/`res_ss`/`bjt_ff`/
`bjt_ss` device-level corners) × temperature {−40, 27, 125} °C × `VIN`
{2.97, 3.30, 3.63} V — which **is** this design's full coverage of the
Challenge's 3.3 V digital rail. No row below has ever been measured at, or is
claimed to hold at, a 5.0 V supply.

**Governing source**: [`sim/CHARACTERIZATION.md`](../../sim/CHARACTERIZATION.md),
a generated (not hand-maintained) rollup regenerated for this proposal on
2026-09-05 against the current `design/netlist/ldo_core.spice` /
`error_amp.spice` (sha256 `3aeb2259…`/`ddccc445…`, unchanged since the cited
records were produced — every row below is fresh, not stale, against the
netlist committed alongside this document). This table is a pointer with the
worst-case numbers pulled out for each row, not a re-derivation; full
per-corner data lives at each citation.

| Parameter | Ratified target (min/typ/max) | Stretch | Measured (worst corner, schematic-level, 2.97–3.63 V grid) | Verdict at Challenge rails | Source (dated) |
|---|---|---|---|---|---|
| Input | 3.3 V ± 10 % (2.97–3.63 V) | 5.0 V flavor — not used, §0 | Spanned by every PVT sweep cited below | **N/A** (not an independent testbench claim — it's the corner axis every other row sweeps) | `README.md` note 1 |
| Output | 1.8 V ± 2 % (± 36 mV, 3σ) | — | Statistical (mismatch) 3σ worst 2.223 mV; combined worst-case deviation 3.578 mV (`fs_125c_3.63v`) | **PASS**, ~10× margin | [`sim/mc-output-accuracy/records/20260816-141924-9f85f6b.md`](../../sim/mc-output-accuracy/records/20260816-141924-9f85f6b.md) |
| Load | 0–50 mA (100 mA stretch) | not separately verified | Exercised as the operating condition of every row below | **N/A** (condition, not its own claim) | `README.md` note — |
| Dropout @ 50 mA | < 300 mV (binds ss/125 °C/`VIN`=2.10 V) | < 200 mV | 267.4 mV worst (`ss_125c_2.10v`), 136.2–267.4 mV over 27 corners | **PASS** target; **misses** the 200 mV stretch at the ss/125 °C corners. Rests on DR-0020's measurement definition, **pending operator ratification** (§ notes below) | [`sim/dropout-vs-load/records/20260822-081238-2387db1.md`](../../sim/dropout-vs-load/records/20260822-081238-2387db1.md) |
| Line reg | < 5 mV/V (1 mA and 50 mA, 2.97–3.63 V) | — | 0.458 mV/V worst (`sf_125c_3.30v`) | **PASS**, ~11× margin | [`sim/line-regulation/records/20260816-083627-8e105a0.md`](../../sim/line-regulation/records/20260816-083627-8e105a0.md) |
| Load reg (0–50 mA) | < 1 % (18 mV) | — | 0.006 mV worst (`ff_125c_3.63v`), 1 mA → 50 mA | **PASS**, wide margin | [`sim/load-regulation/records/20260816-090135-4316537.md`](../../sim/load-regulation/records/20260816-090135-4316537.md) |
| Load transient | 1↔50 mA step, `C_eff`=0.33 µF: peak ≤150 mV, recovery ≤20 µs to ±1 % | peak ≤100 mV | Worst undershoot 113.6 mV (`sf_125c_2.97v`), worst overshoot 86.0 mV (`ss_125c_2.97v`); recovery-time not separately measured by this deck (disclosed gap in the record itself) | **PASS** target; **misses** the 100 mV stretch; recovery-time clause **not measured** | [`sim/load-transient/records/20260816-084229-3634e48.md`](../../sim/load-transient/records/20260816-084229-3634e48.md) |
| PSRR | >50 dB@1 kHz, >20 dB@100 kHz (1 mA and 50 mA) | >60 dB@1 kHz, >30 dB@100 kHz | At 1 mA: 59.2–70.4 dB@1 kHz, 35.5–38.3 dB@100 kHz. At 50 mA: 59.2–71.2 dB@1 kHz, 30.0–36.4 dB@100 kHz | **PASS** target at both load points, wide margin; stretch >60 dB@1 kHz **missed by ~0.8 dB** at the worst corner (`sf_125c_3.63v`, both load points); stretch >30 dB@100 kHz met, but with under 0.1 dB margin at 50 mA's worst corner (`ss_125c_2.97v`) | [`sim/psrr-vs-freq/records/20260816-054629-39afa38.md`](../../sim/psrr-vs-freq/records/20260816-054629-39afa38.md); [`sim/psrr-vs-freq-50ma/records/20260816-054705-7b1dacc.md`](../../sim/psrr-vs-freq-50ma/records/20260816-054705-7b1dacc.md) |
| Iq (excl. load current) | < 30 µA (binds ff/125 °C/3.63 V) | < 10 µA (not gating) | 22.0 µA (no load), 22.6 µA (50 mA), both worst at `ff_125c_3.63v` | **PASS**, ~27 % margin to target | [`sim/quiescent-current/records/20260807-105203-64249c6.md`](../../sim/quiescent-current/records/20260807-105203-64249c6.md) |
| Current limit | 65–80 mA over PVT, brickwall; never engages ≤50 mA; survives `VOUT`=0 short | — | Onset 62.0–93.8 mA over 63 corners; never engages below 50 mA (confirmed); short survived electrically | **FAIL** — 36/63 corners outside the ratified 65–80 mA window. `spec/decision-records/DR-0005` proposes a relaxed window, **pending operator ratification** | [`sim/current-limit/records/20260816-080440-8e105a0.md`](../../sim/current-limit/records/20260816-080440-8e105a0.md) |
| Startup | monotonic, ramp ≤1 V/ms, inside ±2 % within 3 ms, overshoot ≤+2 % | — | Settling 2.32–5.83 ms over 81 corners (worst `ss_-40c_3.63v`); no positive overshoot observed at any corner | **FAIL** — settling exceeds the 3 ms bound at the slow (`ss`, cold) corners. `spec/decision-records/DR-0006` proposes a revised window, **pending operator ratification** | [`sim/startup/records/20260816-100018-af4d1f9.md`](../../sim/startup/records/20260816-100018-af4d1f9.md) |
| Enable / shutdown | shutdown Iq < 3 µA, `VIN`→`VOUT` leak ≤1 µA (ff/125 °C/3.63 V) | — | Shutdown Iq 0.204 µA; leakage 0.214 µA; disabled `VOUT` 0.180 V (pass device off, no active discharge) | **PASS**, ~14× and ~5× margin | [`sim/enable-shutdown/records/20260807-105239-64249c6.md`](../../sim/enable-shutdown/records/20260807-105239-64249c6.md) |
| Thermal | ≤92 mW continuous @ 50 mA/3.63 V; ≤290 mW into a `VOUT`=0 short | — | Continuous clause has **no dedicated testbench**; short-circuit dissipation 345.2 mW worst (`ff_125c_3.63v`), 12/63 corners exceed 290 mW | **FAIL** on the measured short-circuit clause; continuous clause **not independently measured** | [`sim/current-limit/records/20260816-080440-8e105a0.md`](../../sim/current-limit/records/20260816-080440-8e105a0.md) |
| Output noise | not specified — waived | 10 Hz–100 kHz µVrms if asked | — | **N/A**, explicitly waived (README note 7) | — |
| Area | < 0.1 mm² (core, excl. pads/sealring) | — | No layout exists (§3 item 1) | **N/A / UNMET** — cannot be measured pre-layout | tracked in follow-up issue, §7 |
| Stability | PM ≥45°, GM ≥10 dB, 0–50 mA, `C_eff` 0.33–4.7 µF, ESR 0–500 mΩ | capless variant (not this design) | 2930/4536 points pass (64.6 %); worst point PM = −6.81°, GM = −1.47 dB (`res_ss_-40c_2.97v`, 50 mA/0.33 µF/0.001 Ω); best point PM = 130.16° | **FAIL** — the 1–50 mA / 0.33 µF corner is the residual gap. `spec/decision-records/DR-0018` proposes closing it by narrowing the ratified envelope, **pending operator ratification** | [`sim/loop-stability/records/20260807-103351-64249c6.md`](../../sim/loop-stability/records/20260807-103351-64249c6.md) |

**On the Dropout row's pending measurement-definition change**: the PASS
verdict above rests on
[DR-0020](../../spec/decision-records/DR-0020-dropout-measurement-definition.md),
which changes what quantity the `dropout-vs-load` testbench computes when it
claims to measure "dropout" (regulation-knee headroom, not a fixed-`VIN`
regulation-error proxy). **DR-0020's `Status` is `proposed`, pending operator
approval of its ratifying pull request** (2AMLogic/2am#357 policy, tracked at
issue #138 — closed as the root-cause/fix issue, but the ratifying PR for
DR-0020's own `Status` flip has not landed as of 2026-09-05). The ratified
< 300 mV target and < 200 mV stretch numbers are **unchanged** by this record
either way; only the measurement-definition wording is pending. If the
operator does not ratify DR-0020, this row reverts to FAIL under the
superseded fixed-headroom metric (see the cited record's own note).

### Reproducing this table

Every citation above is re-runnable from a clean clone with the gf180mcu PDK
installed (`docs/environment-setup.md`). This repository does not (yet) have
a single aggregating `make` target the way `gf180-sar-adc` does; each
experiment is re-run independently via its own `sim/<slug>/testbench/run.sh`
(or the harness's per-experiment driver), and the rollup itself is
regenerated with:

```bash
python3 sim/build_characterization_report.py > sim/CHARACTERIZATION.md
```

`sim/README.md` documents the append-only evidence convention: a re-run mints
a new, dated `sim/<slug>/records/<record-id>.md` rather than editing an
existing one, so any reviewer re-running an experiment gets a *new* record
whose numbers should be compared against, not identical to, the one cited
above.

### Rows currently unmet at these rails, and what would close them

1. **Stability (FAIL, 64.6 % pass rate)** — the largest open item.
   `spec/decision-records/DR-0018-narrow-stability-envelope-to-1uf-nominal.md`
   is a drafted, ready-to-ratify proposal to close the residual 1–50 mA /
   0.33 µF gap by narrowing the ratified stability envelope rather than a
   further circuit change (compensation-network tuning is documented as
   exhausted, DR-0017). It requires operator ratification — tracked at #51,
   itself blocked since 2026-08-27 when the operator-decision issue that
   would have ratified it (#149) was closed `not planned` without a
   successor ratification PR. No design fix is currently proposed as an
   alternative.
2. **Current limit (FAIL, 36/63 corners outside the 65–80 mA window)** —
   `spec/decision-records/DR-0005-current-limit-window.md` proposes a
   relaxed window; pending operator ratification (open PR #137 proposes
   ratifying it).
3. **Startup (FAIL, settling up to 5.83 ms vs. the 3 ms bound)** —
   `spec/decision-records/DR-0006-startup-settling-window.md` proposes a
   revised window; pending operator ratification (open PR #127 proposes
   ratifying it).
4. **Thermal (FAIL, 345.2 mW worst-case into a short vs. the 290 mW bound)**
   — no design fix or spec-revision proposal exists yet for this row; a
   genuinely open gap.
5. **No layout / Area unmeasured** — the largest single item toward a
   Challenge-conformant *design*, as opposed to a Challenge-conformant
   *proposal document*. Tracked in a follow-up issue filed alongside this
   proposal (§7), currently blocked on the floorplan/matching-plan issue
   which is itself blocked on item 1 (stability) closing.
6. **The reference's own error is not budgeted anywhere** — `VREF` is a
   real top-level port as of #174/DR-0021 (§2.2), so the Challenge's
   bandgap-referenced bias slot is usable; what is *not* closed is that no
   `sim/` record covers a non-ideal reference's contribution to the `Output`,
   `PSRR` or noise rows. DR-0021 states the 1/β = 1.5× pass-through
   explicitly and files the reference-referred campaign that would measure
   it — a disclosed exclusion, not a silent one.

None of the above rows had any evidence at a 5.0 V rail to report as
"unmet" in the sense of a missed 5.0 V measurement, because — per §0/§2.1 —
this block is proposed to run only on the Challenge's 3.3 V digital rail.
Every row's coverage gap is against this design's own ratified 2.97–3.63 V
grid, not against an unattempted 5.0 V point.

None of the above blocks *submitting this document* when Challenge #5's
window opens — per the governing 2026-08-25 operator ruling in the 2am
Chipalooza epic, the goal is to design against the brief with this
repository's own system, not to force every row green by a deadline: this
proposal states the design honestly at its current maturity, and nothing
here relaxes a ratified spec row to make it pass.

---

## 5. Test-plan outline (packaged part, QFN on a daughterboard + test board)

All measurements below use only the pads in §2.2 — `VIN`, `VOUT`, `EN`, and
the harness bandgap-referenced `VREF` input. None require the Challenge's
shared analog mux lines, which this block does not use.

1. **Bring-up / DC sanity.** Apply `VIN` = 3.3 V, `VREF` = 1.2 V (harness
   bandgap or bench-supplied), `EN` = `VIN`. Confirm `VOUT` regulates to
   1.8 V ± 2 % at no load and quiescent current is within the Iq row's
   budget. **`VREF` must be driven** — the part does not regulate without it
   (§2.2), which makes this step the direct bench check on that dependency.
   Meter the current the block draws from the `VREF` source and compare
   against the simulated `I_ref` row (§4).
2. **Line regulation.** Sweep `VIN` 2.97–3.63 V at 1 mA and 50 mA fixed
   load; compute mV/V and compare against the < 5 mV/V bound.
3. **Load regulation.** Step the load 1 mA → 50 mA at fixed `VIN`; compare
   the resulting `VOUT` shift against the < 18 mV bound.
4. **Dropout.** Sweep `VIN` down from 3.3 V toward the regulation knee at
   50 mA fixed load; record the `VIN` − `VOUT` headroom at the point `VOUT`
   falls to −2 % of nominal, per DR-0020's measurement definition (§4 note).
5. **Load transient.** Step the load 1 mA ↔ 50 mA with 1 µs edges at
   `C_eff` = 0.33 µF; capture peak excursion and recovery time to ±1 % —
   this closes the "recovery-time not measured" gap the schematic-level
   deck left open (§4).
6. **PSRR.** Inject a swept-frequency ripple onto `VIN` at 1 mA and 50 mA
   load; measure `VOUT` ripple and derive PSRR at 1 kHz and 100 kHz.
7. **Current limit / short-circuit survival.** Sweep the load resistance
   down to a dead short at `VIN_max`; record the current-limit onset and
   confirm the part survives (does not latch up or fail) a sustained short.
8. **Startup.** Step `EN` 0 → `VIN` into 0 mA and 50 mA loads at
   `C_eff` = 4.7 µF (the softest corner); capture the ramp rate, inrush,
   overshoot, and settling time to ±2 %.
9. **Enable / shutdown.** Confirm disabled-state supply current and
   `VIN`→`VOUT` leakage against the ratified bounds, and that `VOUT` shows no
   internal active discharge when disabled.
10. **Stability, if a bench technique permits it without the internal
    loop-break ports** (§2.2 notes these are not brought off-chip in the
    production wrapper) — otherwise this row stays a simulation-only claim
    for the packaged part, disclosed as such rather than asserted from the
    bench.

---

## 6. Input interface note

- **Single, fixed output.** This design has no run-time mode selection —
  `VOUT` regulates to a fixed 1.8 V, and the programmable 1.2–3.0 V stretch
  from this repository's own spec is deferred
  ([DR-0003](../../spec/decision-records/DR-0003-output-programmability.md)),
  not part of this proposal.
- **Reference note.** Full-scale accuracy of `VOUT` is set by the
  **externally supplied** 1.2 V reference on the `VREF` pin and the
  300 k/600 kΩ feedback divider ratio (`design/README.md`), giving
  `VOUT` = 1.5 × `VREF`. That 1.5× is also the pass-through: the reference's
  tolerance, tempco, noise and supply rejection all land on `VOUT` multiplied
  by 1/β = 1.5, and **none of them is inside any §4 row**, every one of which
  was measured against an ideal source. A driver of `VREF` must also source
  this block's reference bias current at every corner (§4 `I_ref` row). Full
  contract:
  [DR-0021](../../spec/decision-records/DR-0021-vref-is-a-top-level-port.md)
  "Decision" item 3.

---

## 7. Open items before a schematic/layout review

1. **No layout exists (largest gap toward a Challenge-conformant design).**
   Tracked in
   [#173](https://github.com/2AMLogic/gf180-ldo/issues/173), currently
   blocked on the floorplan/matching-plan issue
   ([#15](https://github.com/2AMLogic/gf180-ldo/issues/15)), which is itself
   blocked on loop stability closing
   ([#51](https://github.com/2AMLogic/gf180-ldo/issues/51), pending DR-0018
   operator ratification).
2. **Stability gap (§4 item 1)** — open, `spec/decision-records/DR-0018`
   drafted and awaiting operator ratification via #51/#149's chain.
3. **Current-limit window (§4 item 2)** and **startup settling (§4 item 3)**
   — both have drafted, ready-to-ratify decision records (DR-0005, DR-0006)
   with open ratification PRs (#137, #127 respectively).
4. **Thermal short-circuit dissipation (§4 item 4)** — no proposed fix yet;
   a genuinely open gap.
5. **`VREF` port promotion — CLOSED.**
   [#174](https://github.com/2AMLogic/gf180-ldo/issues/174) is resolved:
   `VREF` is a real top-level `ldo_core` port, the ideal in-cell source is
   deleted, and all 15 `sim/` decks now drive it.
   [DR-0021](../../spec/decision-records/DR-0021-vref-is-a-top-level-port.md)
   carries the decision and its equivalence evidence (`Status: proposed`,
   pending operator ratification like every other decision record here).
   **What remains open** is not the pin but the reference's own
   contribution: no `sim/` record covers a non-ideal reference, and its error
   enters `VOUT` at 1.5× (§6). Disclosed, quantified as a multiplier, and
   filed as follow-up work in DR-0021.

None of the above blocks *submitting* this proposal by Challenge #5's
window — the proposal's own acceptance criteria are to state the design
honestly at its current maturity, not to have already closed every gap. Per
the governing 2026-08-25 operator ruling recorded in the 2am Chipalooza epic,
the goal is to design against the Challenge #5 brief with this repository's
own system, not to force every row green by the deadline: if this document
is ready when a window is open the operator submits it; if not, nothing here
is rushed and no spec row is relaxed to make the date.

---

## 8. Licensing and EDA flow

- **License**: this entire repository — schematics, generators, layout
  tooling, testbenches, and every evidence record cited above — is licensed
  [Apache-2.0](../../LICENSE), satisfying the Challenge's requirement for a
  standard open license with all modifiable sources public.
- **Flow**: fully open-source. Schematic capture and netlisting via
  [xschem](https://xschem.sourceforge.io/); simulation via
  [ngspice](https://ngspice.sourceforge.io/); layout, DRC, and LVS (once
  layout exists, §7 item 1) via [KLayout](https://www.klayout.de/) driven by
  [klayout-tools](https://github.com/2AMLogic/klayout-tools/) (`klt`) — the
  same tool this repository already exercises end to end on its
  one-transistor DRC/LVS test cell (`layout/README.md`); the gf180mcu PDK
  fetched and pinned via [volare](https://github.com/efabless/volare) under
  the `PDK_ROOT`/`PDK` environment convention this repository documents in
  [`docs/environment-setup.md`](../environment-setup.md). Every simulation
  record cited in §4 states the exact pinned toolchain (PDK hash, ngspice
  version, git commit) that produced it, under that record's own
  "Environment" section, so any reviewer can re-run the evidence this
  proposal cites from a clean checkout.
