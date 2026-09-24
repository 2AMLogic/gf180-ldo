# DR-0030: The `CON` contact layer's EM limit is a 129 µA/cut placeholder, with a falsifiable revisit trigger

- **Status**: proposed
- **Date**: 2026-09-22
- **Decided by**: agent-builder, issue #278 (recommendation only — ratification
  is the operator's act, per DR-0004)

## Context

Issue #278 asked whether this repo can sign off electromigration on a 50 mA
power path against an open PDK that publishes no DRM. The answer turned out to
be *mostly yes, with one hole*.

**What the PDK does publish.** The only machine-readable current-density data
anywhere in a `gf180mcuD` install (open_pdks
`c6d73a35f524070e85faff4a6a9eef49553ebc2b`) is the `DCCURRENTDENSITY` /
`ACCURRENTDENSITY` entries in the six standard-cell tech LEFs,
`libs.ref/gf180mcu_fd_sc_mcu{7,9}t5v0/techlef/*.tlef` (header: *"based on DRM
DM-000013-01 Rev 13"*). A `grep -rl CURRENTDENSITY` across the whole install
returns those six files and nothing else — not the KLayout DRC decks, not
`libs.tech/magic`, not `libs.tech/netgen`, not `libs.tech/openlane`, not the
ngspice models, not the I/O or SRAM LEFs. All six files agree, byte-for-byte,
on every entry:

| Layer | `DCCURRENTDENSITY AVERAGE` | `ACCURRENTDENSITY AVERAGE` |
| --- | --- | --- |
| Metal1–Metal4 | 0.67 | 1.00 |
| Metal5 | 1.5 | 2.2 |
| Via1–Via4 | 0.18 | 0.28 |
| **`CON`** | **absent** | **absent** |

`layout/floorplan.md` §8 carries the unit-convention derivation that turns
those raw entries into 0.67 mA/µm of drawn width (Metal1–Metal4), 1.5 mA/µm
(Metal5) and 0.18 mA per cut (Via1–Via4), and shows the arithmetic. This record
does not restate it.

**The hole.** The `CON` layer block is, in all six files and in full:

```
LAYER CON
    TYPE CUT ;
END CON
```

No current-density entry, no resistance, nothing. For a 50 mA pass device the
device-to-Metal1 contact array is normally the tightest constraint in the whole
stack, so this is the one number the design most needs and the one the PDK does
not give. `layout/floorplan.md` §3.3 has been sizing the drain contact array
against a proxy stated inside that document. A number that load-bearing does not
belong in a floorplan note with no revisit trigger — hence this record.

## Decision

**Adopt, as a spec-level placeholder, a `CON` DC average electromigration limit
of 129 µA per contact**, and hold `layout/floorplan.md` §3.3's contact row —
and any other contact-level EM claim this repo makes — to that number until a
revisit trigger below fires.

Derivation, from PDK data only:

- A gf180mcu contact is a **fixed** 0.22 µm × 0.22 µm square. The DRC deck's
  CO.1 is a min *and* max rule (`libs.tech/klayout/drc/rule_decks/contact.drc`:
  *"Min/max contact size. is 0.22µm"*), so there is no width to scale and the
  limit can only be expressed per cut, exactly as Via1–Via4's is.
- Scale Via1's published 0.18 mA per cut by **cut area**:
  `0.18 mA × (0.22 / 0.26)² = 0.18 × 0.71598 = 0.1289 mA` → **129 µA per cut**.
- Area scaling is the conservative of the two obvious choices: width scaling
  (`0.18 × 0.22/0.26`) would give 152 µA.

**Conditions that are explicitly NOT established by this placeholder** — this
is the part a margin cannot buy back:

- **temperature** — the tech LEFs state no temperature for any of their
  current-density entries, so neither the published metal/via limits nor this
  contact placeholder carry a stated Tj. `layout/floorplan.md` §3.3's operating
  point is Tj = 125 °C.
- **lifetime / failure criterion** — no target lifetime or cumulative-failure
  percentile is published.
- **mechanism** — a contact lands on silicide over diffusion, a via lands on
  aluminium. Their dominant EM/reliability mechanisms are not the same one, so
  scaling a via limit to a contact is a proxy whose *mechanism* may be wrong,
  not merely whose magnitude may be off. Contacts are commonly the more
  restrictive of the two per unit area, which makes this proxy plausibly
  **optimistic**, not conservative.
- **array derating** — no per-array derating factor (the usual "the outermost
  cut in a long row carries more than its share" correction) is published for
  either `CON` or the vias.

**The margin that makes the placeholder survivable.** At the shipped W = 2 mm
pass device, `layout/floorplan.md` §3.3's worst case is 25.0 µA per drain
contact, i.e. **5.2× margin** against 129 µA. The plan therefore survives a real
contact limit up to 5× more restrictive than this proxy. That margin covers the
*magnitude* being wrong; it does not cover the *mechanism* being wrong, which is
what the revisit triggers are for.

### Revisit triggers (falsifiable, re-runnable)

This placeholder is superseded, and §3.3's contact row must be re-derived, as
soon as **any** of the following becomes true. Each is a check somebody can run
and get a yes/no answer to — none requires a judgement call.

1. **The PDK starts publishing it.** Any `gf180mcu` PDK revision in which the
   `CON` layer block of any `libs.ref/*/techlef/*.tlef` gains a
   `DCCURRENTDENSITY` entry. One command, re-runnable against any install:

   ```bash
   for f in "$PDK_ROOT/$PDK"/libs.ref/*/techlef/*.tlef; do
     awk '/^LAYER CON/,/^END CON/' "$f" | grep -q DCCURRENTDENSITY \
       && echo "TRIGGER FIRED: $f"
   done
   ```

   Against `c6d73a35f524070e85faff4a6a9eef49553ebc2b` this prints nothing, in
   all six files — that is the state this record is written against.

2. **A published contact current-density number is obtained.** Any figure for
   the gf180mcu contact from GF's DRM (DM-000013-01 Rev 13 or a successor) or
   another citable published source. The published number governs on arrival,
   whichever direction it moves; this record is superseded by a new one that
   records it.

3. **The design's own margin falls below 3×.** If any change — a #139
   pass-device re-size, a re-segmentation, a contact-array change, a current
   limit increase — pushes the worst-case per-contact current above
   **43 µA** (= 129/3), the placeholder stops being survivable on margin alone
   and must be replaced with a real number before that change lands. At
   2 mm today the worst case is 25.0 µA; note that this trigger fires on a
   pass device made *narrower*, not wider (fewer contacts sharing 50 mA), so
   #139's 2.53 mm and 4 mm candidates both move away from it.

4. **An install carrying a second standard-cell family disagrees.** If a
   `gf180mcu` install is used that ships libraries beyond the two `fd_sc`
   families (e.g. `gf180mcu_osu_sc_*`, which
   [2AMLogic/klayout-tools#1215](https://github.com/2AMLogic/klayout-tools/issues/1215)
   reports as disagreeing with `fd_sc` on top metal by 24 %), the Via1 figure
   this placeholder is scaled *from* is no longer unambiguous, and the
   placeholder must be re-derived from the conservative view of whichever
   libraries that install carries.

## Alternatives considered

- **Obtain the published DRM table and cite it (issue #278's Option 1, the
  preferred one).** Not available. GF's DRM DM-000013-01 is not part of the
  open PDK distribution — the tech LEF header cites it as its own source but
  the document itself is not redistributed, and nothing in the install
  reproduces its contact current-density table. This remains the right
  resolution and is revisit trigger 2; this record is what holds the line
  until it happens, not a substitute for it.
- **Leave the proxy as a floorplan note (the status quo).** Rejected — that is
  precisely what issue #278 objected to. A note inside a design document has no
  revisit trigger, is not reviewed as a spec change, and gets copied forward
  into derived claims with the caveat silently dropped. A number that sizes the
  power path of a 50 mA regulator is a spec decision.
- **Declare the contact limit unknowable and refuse to size the array.** Would
  block the floorplan on a document this project cannot obtain. The array has to
  be drawn against *some* number; the honest options are to state one with its
  provenance and its margin, or to stop. A 5.2× margin against a conservatively
  scaled proxy is a defensible engineering position; refusing to write it down
  is not.
- **Use the width-scaled 152 µA instead of the area-scaled 129 µA.** Rejected.
  Both are guesses; the more restrictive guess is the correct one to design
  against, and the 23 µA difference costs nothing at 25.0 µA of actual
  per-contact current.
- **Take the pre-existing 150 µA assumption forward unchanged.** Rejected. That
  figure (the one `layout/floorplan.md` carried before it was rewritten against
  the tech LEFs) has no derivation attached to it at all. 129 µA is at least
  reproducible from a published Via1 number and a published contact dimension,
  and it happens to be the more conservative of the two.
- **Grade the whole EM question as an accepted open-PDK tape-out risk in
  `README.md` (issue #278's Option 3).** Partially true and partially
  misleading, so rejected as the primary resolution: after the tech LEF
  discovery, four of the five levels in the stack have real PDK data and only
  `CON` does not. Grading the whole question as "risk accepted" would overstate
  the gap in exactly the way issue #278's own edge-case requirement warns
  against. The residual risk is recorded here, scoped to the one layer that has
  it.

## Consequences

- **`layout/floorplan.md` §3.3's contact row cites this record** rather than
  carrying its own untracked proxy, and §8 states the contact limit as the one
  remaining assumption in the EM table. The metal and via rows are unaffected:
  they are PDK data and are cited as such.
- **The design-review checklist (§9) gains a provisional line scoped to the
  contact row only**, and the metal/via line is no longer provisional. The EM
  question as a whole is *not* resolved by this record — trigger 3 above means a
  reviewer has a number to check against, not a box to tick.
- **Any downstream EM claim about the contact layer inherits this caveat.** A
  claim of the form "the contact array is EM-clean at 50 mA" is only ever a
  claim of "…against DR-0030's 129 µA placeholder, with 5.2× margin", and must
  be written that way.
- **This placeholder cannot carry a tape-out sign-off on its own.** If this
  block goes to silicon through a shuttle that requires a foundry EM sign-off,
  trigger 2 has to be satisfied first — the margin argument is a design
  guardrail, not a sign-off artifact. That is a real, stated residual risk of
  building a 50 mA power device against an open PDK, and this record is where it
  is booked.
- **Nothing in `sim/` changes.** Electromigration is not simulated anywhere in
  this repo and no testbench result moves with this record.
