# ADR 0001 — Local persistence: content-addressed files

**Status:** accepted
**Date:** 2026-09-01
**Increment:** foundation

## Context

The foundation needs somewhere to put objects, receipts and checkpoints. The
options considered were SQLite, an embedded key/value store, and structured
files.

What the runtime actually stores, at least at first, is immutable and
content-addressed: an object's name is the hash of its bytes, so it is
written once and never updated. Receipts are append-only and chained.
Checkpoints are snapshots. None of it is relational, none of it needs
transactions across multiple rows, and none of it is queried by anything but
its hash.

## Decision

**Content-addressed files on the local filesystem**, implemented in
`crates/storage`.

Objects live at `<root>/<first two hex>/<remaining hex>`, sharded so one
directory does not accumulate every object. Writes go to a `.partial` file
and are renamed into place, so a crash cannot leave a truncated object under
a hash that claims to describe complete content. Reads re-hash and compare.

## Why not SQLite

SQLite is the obvious answer and would be the right one if the workload were
relational. It is not, and it brings costs that are real here:

- **A second source of truth.** Objects are already named by their content.
  Storing them in a database means the database's row identity and the
  content hash can disagree, and something has to reconcile them.
- **A dependency with a build story.** `rusqlite` either bundles a C library
  or links a system one. Both are manageable; neither is free, and this
  increment's dependency list is three crates.
- **Nothing to gain yet.** There are no joins, no transactions spanning
  objects, no queries by anything but hash.

SQLite becomes correct the moment there is an **index** — "which receipts
mention this artifact", "what is in this neighbourhood of the graph". That
is a different thing from the object store, and it can be added beside it
without moving the objects. An index is rebuildable from the objects; the
objects are not rebuildable from an index.

## Why not an embedded key/value store

`sled`, `redb` and similar would work. They add a dependency and a storage
format for a mapping the filesystem already provides, and they make the
store harder to inspect: an object under a content-addressed path can be
read with `cat` and verified with `sha256sum`, which is worth more during
foundation work than the performance difference.

## Consequences

**Good.** No external dependency. Objects are inspectable and verifiable
with standard tools. Idempotent writes fall out of content addressing.
Corruption is caught on read.

**Bad.** No secondary indexes — finding objects by anything but hash means a
scan. No transactions across objects. Many small objects use a filesystem
block each. Directory listing gets slow at scale, which the two-character
sharding defers rather than solves.

**Revisit when** an index is needed, at which point add SQLite *for the
index* and leave the object store alone.
