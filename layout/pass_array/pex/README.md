# `layout/pass_array/pex/` -- committed `klt pex` evidence

Append-only evidence directory for `klt pex` runs on the `pass_array` cell
(issue #786). Each run commits two files, named by the record id of the
`layout/records/<id>.md` record that describes the run:

- `<id>.json` -- the `klt pex --envelope-out` report (the same bytes the
  command emitted; `scope: "repo"` paths, no host paths)
- `<id>.extracted.spice` -- the parasitic-annotated netlist snapshot the
  run extracted (`extraction.netlist_sha256` is its digest)

The layout input itself is regenerated per run with
`layout/pass_array/gen_gds.py` (see the record for the invocation and the
content hash); committing the GDS here is #784's job, not this
directory's. These reports are cell-level route evidence: T1 item 7 is about
the block and cites none of them (`signoff/README.md`).
