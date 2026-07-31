# DR-0000: <short title>

<!--
USAGE NOTES

- One decision per record. Keep it to one page — if the writeup needs more
  than that, the decision is probably several decisions; split it.
- Filename convention: copy this file to
  `spec/decision-records/DR-NNNN-<slug>.md`, where NNNN is a zero-padded,
  four-digit, monotonically increasing number (DR-0001, DR-0002, ...) and
  <slug> is a short kebab-case description. Use the same NNNN in the
  filename, the header below, and the "Status" line's superseded-by
  reference — never let those three drift apart.
- Numbering / collision avoidance: before committing, check
  `spec/decision-records/` for the highest NNNN already present *and* check
  open PRs that add a new record, since a concurrent PR may have claimed
  the next number first. Two records committed with the same NNNN is a
  merge-blocking defect — rebase and renumber rather than merging a
  collision.
- A decision record is required for every spec change (see CLAUDE.md).
  Ratified records are never edited or deleted, even if later found wrong
  or incomplete — supersede them with a new record instead, and update the
  old record's "Status" line to point at the one that replaces it. This
  mirrors the append-only, supersede-don't-rewrite rule that `sim/`
  evidence records use (see issue #5 / the sim/ evidence record format,
  once it lands): both conventions treat the ratified/recorded artifact as
  immutable history, correctable only by adding a new entry that
  supersedes it.
- Ratifying an existing document: the Decision section does not have to
  restate a longer document in full — if the decision is "adopt the
  approach in <doc>", point to that committed doc by path and summarize
  the decision in one or two sentences instead of duplicating its content.

Divergence from the gf180-bandgap template this file was mirrored from:
that template instructs `DR-NNN-<slug>.md` naming, but its own two
committed records are named `0001-bandgap-topology-selection.md` and
`0001-supply-voltage-scope.md` — no `DR-` prefix, and both collide at
number 0001. This template fixes that by stating one unambiguous
convention (`DR-NNNN-<slug>.md`, four-digit, `DR-` prefix always present)
and by adding the collision-avoidance guidance above. Delete this
divergence note along with the rest of this comment block when you copy
the template for a real record.
-->

- **Status**: proposed | ratified | superseded by DR-NNNN
- **Date**: YYYY-MM-DD
- **Decided by**: <name / role>

## Context

What forced this decision? One short paragraph: the constraint, the
measurement, or the conflict that made the current spec inadequate. Link to
the issue, the simulation evidence in `sim/`, or the prior record it revises.

## Decision

The decision, stated as a change to the spec — the parameter and its new
value, or the approach now ratified. Be specific enough that design work can
lock to it without further interpretation. If this record ratifies an
existing document (e.g. an architecture survey) rather than a spec value,
say so and link to it instead of restating it.

## Alternatives considered

- **<alternative>** — why it was not chosen.
- **<alternative>** — why it was not chosen.

## Consequences

What follows from this: what becomes possible, what becomes harder, which
testbenches or corner sets change, what work is invalidated or must be
re-run. Include the bad consequences, not just the good ones.
