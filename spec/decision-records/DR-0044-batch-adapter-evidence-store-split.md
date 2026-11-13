# DR-0044: a `klt`-batch adapter run stores its bytes, and keeps the report envelope and the netlist snapshot in git

- **Status**: proposed
- **Date**: 2026-11-13
- **Decided by**: agent-builder, issue #594 (applies [`DR-0041`](DR-0041-new-evidence-bytes-go-to-the-artifact-store-git-keeps-manifests.md) to the shared batch path)

## Context

[`DR-0041`](DR-0041-new-evidence-bytes-go-to-the-artifact-store-git-keeps-manifests.md)
decided that new evidence bytes go to the fleet artifact store and git keeps a
manifest plus the Markdown record, with the stated consequence "The repo stops
growing by raw logs". Its Consequences paragraph recorded a scope limit on the
change that implemented it (issue #511): the `klt`-batch adapters "still write
the old layout and are not changed here".

That limit was never lifted. Multi-corner grids are run through the adapters,
so between 2026-10-24 and 2026-11-08 a further 913 raw evidence files (7.0 MB:
818 `.log`, 44 `.spice`, 42 `.json`, 9 `.csv`) were added to git, while
`manifests/artifacts/` held nothing but its README and the store path had no
user at all. CI's `check_artifact_manifests.py check --tree` passed on every PR
because it was validating an empty set.

Issue #594 moves the shared path — the ten benches whose `klt_run.py` calls
`tb_adapter.main`, minted by `harness.klt_record`. Applying DR-0041 to it
unchanged is not possible in two places, which is what this record decides. The
hand-rolled batch drivers are issue #596.

## Decision

A run made with `tb_adapter.main` and minted with `harness.klt_record` follows
DR-0041, with two named exceptions.

1. **The run stages, it does not commit.** `tb_adapter.main` writes the whole
   run into git-ignored `sim/.work/.stage/<bench>/sim/<bench>/corners/<id>/`
   and nothing into `sim/<bench>/corners/`. A run that is never minted is not
   evidence and leaves nothing in the tree.
2. **Fail closed, before the fleet.** Unless the run is an `--only` debug
   point, the store is probed before any request is submitted; an unstorable
   run exits 10 having written nothing. A put that fails during minting also
   exits 10, leaving `sim/` and `manifests/` untouched and the staged bytes in
   place. There is no option to commit the bytes instead.
3. **These bytes go to the store** (DR-0041 item 1, unchanged): the per-corner
   `<corner>.log`, `dut.spice`, `body.spice`, `request.json` and `summary.csv`.
   Git keeps `manifests/artifacts/<bench>-<id>.manifest.json` and
   `sim/<bench>/records/<id>.md`. In such a record, every path under
   `corners/<id>/` other than the envelope below is a manifest `name`, not a
   file in this repo.
4. **`corners/<id>/.../klt-report.json` stays committed**, at the path it has
   today. It is the redacted `klt sim` request envelope.
   `signoff/block-manifest.json` pins five of these by `content_hash`, and CI's
   `signoff/check.sh` (`klt signoff --manifest`) reads them offline, with no
   broker. A file that stays in git is never also a manifest entry
   (`check_artifact_manifests.py check` fails an entry whose `name` is a
   tracked path), so it is excluded from the manifest at staging time.
5. **`netlist-snapshots/<id>.spice` stays committed**, departing from
   DR-0041 item 1, which names the snapshot as stored.
   `sim/build_characterization_report.py` skips a record whose snapshot is not
   a committed file and compares its bytes with the current DUT to decide
   whether the row is fresh; a stored snapshot would cost that row its
   freshness verdict (the defect filed as #597 for `run_corners.py` records).

DR-0041 is not edited, its Status is unchanged, and nothing here is ratified.

## Alternatives considered

- **Store `klt-report.json` too.** Consistent with DR-0041's letter, but it
  breaks signoff item 5: `signoff/check.sh` grades those envelopes in CI with
  no broker and no credentials, and would have to fetch them instead. Changing
  how signoff is graded is a larger decision than this one.
- **Store the netlist snapshot too.** Same inconsistency as #597: the
  characterization report would stop being able to judge the row fresh. Fixing
  the report to resolve a stored snapshot needs the broker in a path that is
  deliberately offline.
- **Keep committing batch evidence, and amend DR-0041 to say so.** Honest
  about the status quo, but it abandons DR-0041's purpose on the path that
  produces most of the bytes.
- **Convert every batch driver in one change.** The nine hand-rolled drivers
  have their own roll-up scripts that re-read committed logs; they are #596.

## Consequences

- New `tb_adapter` runs stop adding most evidence files to git. Measured
  against the 913 post-DR-0041 files, this removes about two thirds of the
  file count on the paths it covers, but only about half the bytes: the kept
  `klt-report.json` envelopes are 3.3 of the 7.0 MB. Shrinking the envelope is
  out of scope.
- A batch run now needs a reachable broker and a `klt` with `artifact put` on
  the **submitting** host — the bytes are collected locally after `klt sim`
  returns, so the fleet never writes to the store. A worker without a broker
  can no longer record evidence; it exits 10 instead of committing blobs.
- `klt_run.py` and `klt_record` become two halves of one operation. Running
  the first without the second silently produces nothing, which is why the
  driver prints the minting command.
- Records written before this change are untouched (DR-0041 item 3). A reader
  of `sim/<bench>/corners/` now meets two layouts, and must read the record to
  know which: a pre-DR-0044 record's paths are files, a later one's are
  manifest names except the envelope.
- CI's `check_artifact_manifests.py check --tree` finally has data to check,
  and its "no stored object's bytes are also committed" rule can fire.
- The ten `tb_adapter` benches and the hand-rolled drivers (#596) now differ in
  where their evidence lives until #596 lands.
