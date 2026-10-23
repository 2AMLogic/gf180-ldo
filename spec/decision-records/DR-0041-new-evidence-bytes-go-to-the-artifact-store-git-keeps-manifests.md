# DR-0041: new evidence bytes go to the fleet artifact store; git keeps a manifest and the Markdown record

- **Status**: proposed
- **Date**: 2026-10-23
- **Decided by**: operator decision 1.1 (2026-10-22) and ruling H1 in 2AMLogic/2am#5553, implemented by Builder (issue #511)

## Context

`sim/README.md` required raw per-corner logs and netlist snapshots to be
committed, and `.gitignore` force-added `sim/*/corners/**/*.log` to make that
so. Run output now dominates the repo (`du -sm sim/*` on 2026-10-23:
loop-stability 102 MB, soft-start 62, soft-start-loop-gain 28, startup 10,
enable-shutdown 9). The fleet has a common artifact store (`klt artifact
put|get|verify`). The operator ruled that evidence bytes are private and
manifests are public, and that a manifest names objects by logical
`artifact:<key>` uris, never a bucket.

## Decision

1. A run minted after this record stores its netlist snapshot and per-corner
   logs through `klt artifact put`. Git keeps
   `manifests/artifacts/<bench>-<record-id>.manifest.json` (per object: sha256,
   size, kind, producer, uri, logical name under `sim/`) and the Markdown
   record, which ends with a table of the stored objects.
2. Fail closed. No broker (`KLT_ARTIFACT_BROKER`), no `klt artifact put`, a
   `klt` older than klayout-tools `7e3561f`, an unreachable or refusing
   broker, or a failed put exits 10 and commits nothing. Bytes are never
   committed instead.
3. Manifest-forward only. Evidence already committed is not rewritten,
   moved or deleted, and the append-only rule applies unchanged; it now also
   covers `manifests/artifacts/*.manifest.json`.
4. CI (`scripts/check_artifact_manifests.py check`) validates manifest schema
   offline, accepts only `artifact:` uris, and fails if a stored object's bytes
   are also committed. It never contacts the broker, so it does not hash-verify;
   `klt artifact verify <manifest>` does, from a fleet worker.
5. No broker URL, bucket, account id or `s3://` uri is written in this repo.

## Alternatives considered

- **Rewrite history / migrate existing evidence** -- out of scope and against
  the append-only rule.
- **Commit bytes when the broker is down** -- violates fail-closed and would
  reintroduce the growth this record stops.
- **Hash-verify in CI** -- CI broker reachability is unverified, and a check
  that cannot run must not look like a pass.

## Consequences

New runs need a reachable broker and a current `klt`; without them a run
cannot mint evidence (`--no-write` is unaffected). The repo stops growing by
raw logs. The `klt`-batch adapters (`klt_record.py`, `tb_adapter.py`) still
write the old layout and are not changed here. This record changes no spec
value.
